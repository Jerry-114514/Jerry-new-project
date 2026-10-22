"""Offline counterfactual candidate scoring; never called during interaction."""

from copy import deepcopy

from .core import canonical, digest, replay_events
from .execution_oracle import evaluate_execution


def audit_candidates(task, reference, record):
    events = record["final_state"]["events"]
    boundary = record["initial_event_count"]
    if type(boundary) is not int or not 0 <= boundary <= len(events):
        raise ValueError("Invalid initial boundary for candidate replay")
    current = replay_events(task, events[:boundary])
    initial = next((step for step in record["history"] if step["phase"] == "initial"), {"actions": []})
    initial_state = replay_events(task, [])
    initial_state.apply(initial["actions"])
    if canonical(initial_state.events) != canonical(current.events):
        raise ValueError("Initial proposal history differs from committed prefix")
    candidates = []
    for step in record["history"]:
        if step["phase"] != "repair":
            continue
        if type(step["accepted"]) is not bool or (step["hard_guard_passed"] is not None and type(step["hard_guard_passed"]) is not bool) \
                or not isinstance(step["reason"], str) or type(step.get("proposal_complete")) is not bool:
            raise ValueError("Explicit candidate acceptance, guard result and reason required")
        complete = step["proposal_complete"]
        if step["accepted"] and not complete:
            raise ValueError("An incomplete candidate cannot be committed")
        candidate = current.clone()
        candidate.apply(deepcopy(step["actions"]))
        truth = evaluate_execution(task, candidate, reference) if complete else None
        compliant = truth["compliant_success"] if truth is not None else None
        new_hard = (sorted({event["requirement_id"] for event in truth["hard_violation_events"]
                            if event["event_index"] >= len(current.events)}) if truth is not None else None)
        false_block = (not step["accepted"] and compliant) if complete else None
        candidates.append({"attempt_index": len(candidates), "complete_proposal": complete,
            "trial_status": "incomplete_proposal" if not complete else "decision_error" if step["reason"].startswith("proposal_error:") else "evaluated",
            "accepted": step["accepted"], "hard_guard_passed": step["hard_guard_passed"], "reason": step["reason"],
            "committed_before_event_count": len(current.events), "proposed_action_count": len(step["actions"]),
            "candidate_state_hash": digest({"files": candidate.files, "events": candidate.events}),
            "offline_compliant": compliant, "offline_metrics": truth, "candidate_new_hard_violations": new_hard,
            "false_block": false_block,
            "independent_guard_false_block": (false_block and step["hard_guard_passed"] is False) if complete else None})
        if step["accepted"]:
            current = candidate
    if canonical(current.events) != canonical(events) or canonical(current.files) != canonical(record["final_state"]["files"]):
        raise ValueError("Accepted candidate history does not reproduce committed final state")
    return {"schema_version": 1, "definition": "rejected_complete_fully_compliant_candidate",
        "initial_event_count": boundary, "candidates": candidates, "accepted_candidates_replay_final": True,
        "warning": "Static-reference counterfactual scoring after all interactions. Incomplete proposal stages have null truth; decision errors after a complete submission remain eligible trials. No causal or human-reference correctness guarantee."}
