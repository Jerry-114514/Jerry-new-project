"""Bounded propose/validate/commit loop with separate final scoring."""

from .analysis import analyze, gate, score
from .core import initial_state, public_task
from .oracle import evaluate


def run_task(task, actor, policy="dynamic", max_repairs=3, redact_events=False):
    if policy not in {"none", "fixed", "dynamic"}:
        raise ValueError("Unknown policy")
    state = initial_state(task)
    visible = public_task(task)
    history = []
    counters = {"actor_calls": 0, "checks": 0, "rejected": 0, "verifications": 0, "proposed_actions": 0}
    status = "finished"
    findings = []
    try:
        counters["actor_calls"] += 1
        response = actor.propose(visible, state.clone(), "initial")
        counters["proposed_actions"] += len(response["actions"])
        state.apply(response["actions"])
        events_visible = not redact_events
        findings = analyze(visible, state, events_visible)
        counters["checks"] += 1
        history.append({"phase": "initial", "actions": response["actions"], "findings": findings, "score": score(findings)})
        if policy != "none":
            for attempt in range(max_repairs):
                if any(f["status"] == "unknown" for f in findings) and policy == "dynamic":
                    # Reading the authoritative in-memory log is an explicit, counted observation.
                    counters["verifications"] += 1
                    counters["checks"] += 1
                    findings = analyze(visible, state, True)
                    events_visible = True
                    history.append({"phase": "verify", "findings": findings})
                failures = [f for f in findings if f["status"] == "violated"]
                if not failures:
                    break
                if policy == "dynamic":
                    failures.sort(key=lambda f: (not f["hard"], f["id"]))
                target = failures[0]["id"]
                counters["actor_calls"] += 1
                proposal = actor.propose(visible, state.clone(), "repair", target, attempt)
                counters["proposed_actions"] += len(proposal["actions"])
                candidate = state.clone()
                candidate.apply(proposal["actions"])
                new = analyze(visible, candidate, events_visible)
                counters["checks"] += 1
                accepted, reason = gate(findings, new)
                history.append({"phase": "repair", "target": target, "actions": proposal["actions"],
                                "findings": new, "accepted": accepted, "reason": reason})
                if accepted:
                    state, findings = candidate, new
                else:
                    counters["rejected"] += 1
    except (ValueError, KeyError, TypeError, OSError, TimeoutError) as exc:
        status = "error"
        history.append({"phase": "error", "message": str(exc)})
    final = evaluate(task, state)
    return {"task_id": task["id"], "family": task["family"], "split": task["split"], "policy": policy,
            "actor": type(actor).__name__, "status": status, "metrics": final, "cost": counters,
            "history": history, "final_state": {"files": state.files, "events": state.events}}
