"""Bounded propose/validate/commit loop with separate final scoring."""

import time
from copy import deepcopy

from .analysis import analyze, gate, score
from .core import initial_state, public_task
from .oracle import evaluate
from .planner import repair_scope
from .requirements import extract_requirements
from .learning import predict
from .hard_guard import repair_hard_guard


def run_task(task, actor, policy="dynamic", max_repairs=3, redact_events=False, analyzer=None, risk_weights=None,
             hard_guard=True, evaluator=None, scope_selector=None, max_tool_steps=1):
    if policy not in {"none", "fixed", "fixed-full", "dynamic"}:
        raise ValueError("Unknown policy")
    if type(max_tool_steps) is not int or not 1 <= max_tool_steps <= 8:
        raise ValueError("Tool feedback steps must be between one and eight")
    started = time.perf_counter()
    state = initial_state(task)
    def inspect(public, observed_state, visible_history):
        rows = (analyzer or analyze)(public, observed_state, visible_history)
        if risk_weights is not None:
            for row in rows:
                if "features" not in row or len(risk_weights) != len(row["features"]) + 1:
                    raise ValueError("Risk model schema does not match this analyzer")
                row["risk_score"] = predict(risk_weights, row["features"])
        return rows
    visible = public_task(task)
    history = []
    counters = {"actor_calls": 0, "checks": 0, "rejected": 0, "verifications": 0, "proposed_actions": 0,
                'hard_rejections': 0, 'tool_step_limit_hits': 0}
    status = "finished"
    findings = []
    requirements = []
    initial_observation = state.clone()
    initial_active, active_repair = False, None
    def propose_plan(plan_state, entry, phase, target=None, attempt=0):
        for tool_step in range(max_tool_steps):
            counters["actor_calls"] += 1
            response = actor.propose(visible, plan_state.clone(), phase if tool_step == 0 else phase + "_continue", target, attempt)
            actions = response["actions"]
            done = response.get("done", True)  # Existing scripted/HTTP actors remain one-batch by default.
            if type(done) is not bool or not isinstance(actions, list):
                raise ValueError("Actions list and boolean completion flag required")
            counters["proposed_actions"] += len(actions)
            if len(entry["actions"]) + len(actions) > 16:
                raise ValueError("A complete multi-step proposal may contain at most 16 actions")
            plan_state.apply(actions)
            entry["actions"].extend(deepcopy(actions))
            entry["tool_steps"].append({"step": tool_step, "action_count": len(actions), "declared_done": done,
                                       "strict_interface_valid": response.get("strict_interface_valid"),
                                       "ignored_envelope_fields": response.get("ignored_envelope_fields", [])})
            if done:
                return
        counters["tool_step_limit_hits"] += 1
    try:
        requirements = visible["requirements"] if "requirements" in visible else extract_requirements(visible["request"])
        initial_entry = {"phase": "initial", "actions": [], "tool_steps": [], "findings": []}
        history.append(initial_entry)
        initial_active = True
        propose_plan(state, initial_entry, "initial")
        initial_observation = state.clone()
        initial_active = False
        events_visible = not redact_events
        findings = inspect(visible, state, events_visible)
        counters["checks"] += 1
        initial_entry.update(findings=findings, score=score(findings))
        if policy != "none":
            for attempt in range(max_repairs):
                if any(f["status"] == "unknown" for f in findings) and policy == "dynamic" and not events_visible:
                    # Reading the authoritative in-memory log is an explicit, counted observation.
                    counters["verifications"] += 1
                    counters["checks"] += 1
                    findings = inspect(visible, state, True)
                    events_visible = True
                    history.append({"phase": "verify", "findings": findings})
                failures = [f for f in findings if f["status"] == "violated"]
                if not failures:
                    break
                if policy == "dynamic":
                    failures.sort(key=lambda f: (not f["hard"], -f.get("risk_score", 0), f["id"]))
                target = (scope_selector(visible, failures, policy, counters["rejected"] > 0)
                          if scope_selector else repair_scope(failures[0]["id"], policy, counters["rejected"] > 0))
                candidate = state.clone()
                active_repair = {"phase": "repair", "target": target, "actions": [], "tool_steps": [],
                                 "findings": [], "accepted": False, "reason": "incomplete_proposal", "hard_guard_passed": None}
                history.append(active_repair)
                propose_plan(candidate, active_repair, "repair", target, attempt)
                hard_allowed, hard_reason = (repair_hard_guard(visible, state, candidate)
                                             if hard_guard else (True, "independent_guard_disabled"))
                active_repair["hard_guard_passed"] = hard_allowed if hard_guard else None
                counters['hard_rejections'] += not hard_allowed
                new = inspect(visible, candidate, events_visible)
                counters["checks"] += 1
                accepted, reason = gate(findings, new) if hard_allowed else (False, hard_reason)
                active_repair.update(findings=new, accepted=accepted, reason=reason)
                if accepted:
                    state, findings = candidate, new
                else:
                    counters["rejected"] += 1
                active_repair = None
    except (ValueError, KeyError, TypeError, OSError, TimeoutError, RuntimeError) as exc:
        status = "error"
        if initial_active:
            initial_observation = state.clone()
        if active_repair is not None:
            active_repair["reason"] = "proposal_error:" + type(exc).__name__
            counters["rejected"] += 1
        history.append({"phase": "error", "message": str(exc)})
    interaction_seconds = time.perf_counter() - started
    judge = evaluator or evaluate
    # Both evaluations happen only after the model/repair loop. Offline truth
    # cannot influence target choice, acceptance, stopping or tool execution.
    final = judge(task, state)
    initial_metrics = judge(task, initial_observation)
    irreversible = initial_metrics.get("irreversible_hard_violations")
    violations = final.get("hard_violation_events")
    repair_violations = (sorted({event["requirement_id"] for event in violations
                                if event["event_index"] >= len(initial_observation.events)})
                         if violations is not None else None)
    return {"task_id": task["id"], "family": task["family"], "split": task["split"], "policy": policy,
            "hard_guard_enabled": hard_guard,
            "parsed_requirements": requirements,
            "actor": type(actor).__name__, "status": status, "metrics": final, "cost": counters,
            "initial_metrics": initial_metrics,
            "initial_event_count": len(initial_observation.events), "max_tool_steps": max_tool_steps,
            "feasible_at_repair_start": not irreversible if irreversible is not None else None,
            "repair_introduced_hard_violations": repair_violations,
            "interaction_seconds": interaction_seconds,
            "evaluation_seconds": time.perf_counter() - started - interaction_seconds,
            "elapsed_seconds": time.perf_counter() - started,
            "history": history, "final_state": {"files": state.files, "events": state.events}}
