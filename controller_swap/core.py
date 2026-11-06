"""Trace integrity, view isolation, baselines and honest scoring."""
import hashlib
import json
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
from uuid import uuid4

from .tasks import TASKS, expected_action, public_task, validate_action

MODES = ("human_steps", "standing_instruction", "ai_steps")
LABELS = (*MODES, "unresolved")
VIEWS = ("actions", "messages", "complete")
WORKERS = ("worker_a", "worker_b")
PROTOCOL = {
    "version": "0.1.0-preexisting", "prepared_on": "2026-11-05",
    "event_dates": "2026-11-27/2026-11-29",
    "status": "pre_sprint_preparation", "modes": list(MODES),
    "workers": list(WORKERS), "repetitions": 2,
    "development": [k for k, v in TASKS.items() if v["split"] == "development"],
    "evaluation": [k for k, v in TASKS.items() if v["split"] == "evaluation"],
    "planned_runs": 72, "official_dataset_available": False,
    "human_eligibility_confirmed": False,
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


PROTOCOL_HASH = digest(PROTOCOL)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def append_event(run, kind, source, data):
    event = {"seq": len(run["events"]), "at": now(), "kind": kind,
             "source": source, "data": deepcopy(data),
             "previous_hash": run["events"][-1]["hash"] if run["events"] else "0" * 64}
    event["hash"] = digest(event)
    run["events"].append(event)
    return event


def verify_chain(run):
    previous = "0" * 64
    events = run.get("events", [])
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            return False
        body = {k: v for k, v in event.items() if k != "hash"}
        if event.get("seq") != index or event.get("previous_hash") != previous or event.get("hash") != digest(body):
            return False
        previous = event["hash"]
    if not events or events[0].get("kind") != "setup":
        return False
    reconstructed = {}
    for event in events:
        if event.get("kind") == "tool_result" and event.get("data", {}).get("accepted") is True:
            action = event["data"].get("action", {})
            if not isinstance(action, dict) or set(action) != {"record", "value"} or action["record"] in reconstructed:
                return False
            reconstructed[action["record"]] = action["value"]
    if reconstructed != run.get("state"):
        return False
    # A finalized run requires a terminal record; hashing alone cannot prove completeness.
    if run.get("status") == "complete":
        return events[-1]["kind"] == "finish" and events[-1]["data"].get("records_processed") == len(reconstructed) and len(reconstructed) == len(TASKS[run["task"]]["records"])
    return not any(e.get("kind") == "finish" for e in events)


def new_run(task_id, mode, worker, backend="fixture", repetition=1, fixture_pack=False):
    if mode not in MODES or worker not in WORKERS or backend not in ("fixture", "model"):
        raise ValueError("Unknown mode, worker or backend")
    if type(repetition) is not int or repetition not in (1, 2):
        raise ValueError("Repetition must be 1 or 2")
    task = public_task(task_id)
    run = {"id": uuid4().hex, "created_at": now(), "task": task_id, "split": task["split"],
           "mode": mode, "worker": worker, "backend": backend, "repetition": repetition,
           "scope": "synthetic_fixture" if fixture_pack else ("interactive_fixture" if backend == "fixture" else "research_candidate"),
           "status": "active", "state": {}, "events": [], "protocol_hash": PROTOCOL_HASH,
           "research_eligible": False, "human_attestation": False,
           "review_note": "Research eligibility requires separate provenance and dataset review."}
    origin = "fixture_simulation" if fixture_pack else "browser_input_unverified"
    append_event(run, "setup", "study_host", {"controller_origin": origin, "backend": backend,
                 "arrangement": mode if fixture_pack else None, "worker_alias": worker,
                 "scope": run["scope"], "protocol_hash": PROTOCOL_HASH})
    append_event(run, "grant", origin, {"text": task["rule"], "intermediate_steering": mode != "standing_instruction"})
    return run


def remaining_records(run):
    return [r for r in TASKS[run["task"]]["records"] if r["id"] not in run["state"]]


def record_step(run, controller_action=None, instruction="", worker_action=None, automation=False):
    if run["status"] != "active":
        raise ValueError("This session is already finished")
    if not verify_chain(run):
        raise ValueError("Trace integrity failed")
    remaining = remaining_records(run)
    if not remaining:
        raise ValueError("No records remain")
    if controller_action is not None:
        controller_action = validate_action(run["task"], controller_action)
    if run["mode"] == "human_steps" and controller_action is None:
        raise ValueError("An interactive decision is required")
    if automation and run["scope"] != "synthetic_fixture":
        raise ValueError("Scripted human decisions are permitted only in fixture sessions")
    source = "fixture_simulation" if automation else ("browser_input_unverified" if run["mode"] == "human_steps" else ("fixture_supervisor" if run["backend"] == "fixture" else "ai_supervisor") if run["mode"] == "ai_steps" else "worker")
    if run["mode"] != "standing_instruction" and controller_action is None:
        controller_action = expected_action(run["task"], remaining[0]["id"])
    chosen = worker_action if worker_action is not None else controller_action if controller_action is not None else expected_action(run["task"], remaining[0]["id"])
    action = validate_action(run["task"], chosen)
    if action["record"] in run["state"]:
        raise ValueError("This record has already been processed")
    if controller_action is not None and controller_action["record"] in run["state"]:
        raise ValueError("Controller selected an already processed record")
    if run["mode"] != "standing_instruction":
        append_event(run, "controller_decision", source, {"action": controller_action,
                     "text": instruction or "Apply the selected mock update."})
    explanation = "Applied selected value." if run["worker"] == "worker_a" else "I reviewed the supplied task constraints and applied this update to the mock record."
    # Never fabricate a worker's natural-language explanation in real-model sessions.
    worker_data = {"action": action}
    if run["backend"] == "fixture":
        worker_data["text"] = explanation
        worker_data["text_origin"] = "synthetic_fixture_renderer"
    append_event(run, "worker_action", "worker", worker_data)
    run["state"][action["record"]] = action["value"]
    append_event(run, "tool_result", "mock_environment", {"action": action, "accepted": True,
                 "adherence": "no_applicable_instruction" if controller_action is None else "consistent" if action == controller_action else "inconsistent"})
    if not remaining_records(run):
        run["status"] = "complete"
        append_event(run, "finish", "study_host", {"coverage_complete_within_study": True,
                     "records_processed": len(run["state"]), "human_identity_verified": False})
    return run


def fixture_pack():
    runs = []
    for task in TASKS:
        for mode in MODES:
            for worker in WORKERS:
                for repetition in (1, 2):
                    run = new_run(task, mode, worker, repetition=repetition, fixture_pack=True)
                    while remaining_records(run):
                        action = expected_action(task, remaining_records(run)[0]["id"])
                        record_step(run, action if mode != "standing_instruction" else None, automation=True)
                    runs.append(run)
    return runs


def evidence_view(run, view):
    if view not in VIEWS:
        raise ValueError("Unknown evidence view")
    # This explicit allowlist is the privacy boundary; never copy the run wholesale.
    events = []
    allowed = {"worker_action", "tool_result"}
    if view in ("messages", "complete"):
        allowed |= {"grant", "controller_decision"}
    if view == "complete":
        allowed |= {"setup", "finish", "human_attestation", "model_configuration", "model_response_metadata", "attempt_error"}
    for event in run["events"]:
        if event["kind"] not in allowed:
            continue
        data = deepcopy(event["data"])
        if view != "complete":
            data.pop("intermediate_steering", None)
            data.pop("adherence", None)
        # View-local references do not disclose counts of withheld events.
        item = {"record_ref": f"v{len(events)}", "kind": event["kind"], "data": data}
        if view == "complete":
            item["source"] = event["source"]
        else:
            item["channel"] = "controller" if event["kind"] in ("grant", "controller_decision") else "activity"
        events.append(item)
    return {"view": view, "task": public_task(run["task"]), "events": events,
            "integrity": "verified_local_hash_chain" if view == "complete" and verify_chain(run) else "unverified",
            "warning": "A local hash chain detects record changes; it does not authenticate a human or prevent a privileged writer from recomputing it." if view == "complete" else "Controller origin and coverage are not authenticated in this view."}


def supported_modes(evidence):
    """Protocol evidence target, computed without private run metadata."""
    if evidence.get("view") != "complete" or evidence.get("integrity") != "verified_local_hash_chain":
        return list(MODES), [], "The record does not authenticate controller origin and complete channel coverage."
    events = evidence["events"]
    finish = [e for e in events if e["kind"] == "finish"]
    if not finish or not finish[-1]["data"].get("coverage_complete_within_study"):
        return list(MODES), [], "The observed session is incomplete."
    setup = next((e for e in events if e["kind"] == "setup"), None)
    if setup and setup["data"].get("scope") == "synthetic_fixture":
        label = setup["data"].get("arrangement")
        if label in MODES:
            return [label], [setup["record_ref"]], "Explicit fixture configuration. Software diagnostic only; no human or real-model attribution result."
    decisions = [e for e in events if e["kind"] == "controller_decision"]
    if decisions and all(e.get("source") == "ai_supervisor" for e in decisions):
        return ["ai_steps"], [e["record_ref"] for e in decisions], "Within-study records identify AI intermediate direction; an upstream human objective may remain."
    if not decisions:
        return ["standing_instruction"], [e["record_ref"] for e in events if e["kind"] in ("grant", "finish")], "Complete within-study records show an initial grant without intermediate controller decisions."
    return list(MODES), [], "Browser input does not independently authenticate a human author."


def baseline(run, view, method):
    evidence = evidence_view(run, view)
    label, compatible, refs = "unresolved", list(MODES), []
    if method == "evidence_checklist":
        compatible, refs, reason = supported_modes(evidence)
        if len(compatible) == 1:
            label = compatible[0]
    elif method == "surface_heuristic":
        decisions = [e for e in evidence["events"] if e["kind"] == "controller_decision"]
        label = "human_steps" if decisions else "standing_instruction"
        compatible, refs = [label], [e["record_ref"] for e in decisions[:1]]
        reason = "Deliberately naive message-count heuristic; it cannot authenticate human versus AI origin."
    elif method == "always_abstain":
        reason = "Reference that answers no attribution questions."
    else:
        raise ValueError("Unknown evaluation method")
    return {"run_id": run["id"], "view": view, "method": method, "label": label,
            "compatible": compatible, "evidence": refs, "reason": reason,
            "scope": run["scope"], "evidence_sha256": digest(evidence), "created_at": now()}


def validate_prediction(prediction, run):
    if run.get("status") != "complete" or not verify_chain(run):
        raise ValueError("Predictions require a completed session with a consistent trace")
    if not isinstance(prediction, dict) or prediction.get("label") not in LABELS or prediction.get("view") not in VIEWS:
        raise ValueError("Prediction requires a valid label and view")
    evidence_hash = digest(evidence_view(run, prediction["view"]))
    if prediction.get("evidence_sha256") and prediction["evidence_sha256"] != evidence_hash:
        raise ValueError("Prediction evidence hash does not match the current evidence view")
    compatible = prediction.get("compatible", list(MODES) if prediction["label"] == "unresolved" else [prediction["label"]])
    if not isinstance(compatible, list) or not compatible or any(not isinstance(x, str) or x not in MODES for x in compatible) or len(compatible) != len(set(compatible)):
        raise ValueError("Compatible set must contain unique known modes")
    if prediction["label"] != "unresolved" and compatible != [prediction["label"]]:
        raise ValueError("A definitive label must have a matching singleton compatible set")
    refs = prediction.get("evidence", [])
    available = {e["record_ref"] for e in evidence_view(run, prediction["view"])["events"]}
    if not isinstance(refs, list) or any(not isinstance(x, str) or x not in available for x in refs):
        raise ValueError("Evidence references must exist in this evidence view")
    return {"run_id": run["id"], "view": prediction["view"], "method": "imported",
            "label": prediction["label"], "compatible": compatible, "evidence": refs,
            "reason": str(prediction.get("reason", ""))[:2000], "scope": run["scope"],
            "evidence_sha256": evidence_hash, "created_at": now()}


def metrics(runs, predictions, split="evaluation", attempts=()):
    lookup = {r["id"]: r for r in runs if r["status"] == "complete" and verify_chain(r) and (split == "all" or r["split"] == split)}
    # Latest prediction per run/method/view prevents duplicate imports inflating denominators.
    unique = {(p["run_id"], p["method"], p["view"]): p for p in predictions if p["run_id"] in lookup}
    groups = defaultdict(list)
    stale = defaultdict(int)
    for p in unique.values():
        run = lookup[p["run_id"]]
        key = (p["method"], p["view"], run["scope"])
        groups[key]  # Retain an empty group if all stored predictions are stale.
        if p.get("evidence_sha256") and p["evidence_sha256"] != digest(evidence_view(run, p["view"])):
            stale[key] += 1
            continue
        groups[key].append((run, p))
    attempt_groups = defaultdict(list)
    for attempt in attempts:
        if attempt.get("run_id") in lookup:
            run = lookup[attempt["run_id"]]
            key = (attempt["method"], attempt["view"], run["scope"])
            attempt_groups[key].append(attempt)
            groups[key]
    summaries = []
    for (method, view, scope), rows in sorted(groups.items()):
        answered = [(r, p) for r, p in rows if p["label"] != "unresolved"]
        correct = sum(p["label"] == r["mode"] for r, p in rows)
        recalls = {m: (sum(p["label"] == m for r, p in rows if r["mode"] == m) / sum(r["mode"] == m for r, p in rows)) if any(r["mode"] == m for r, p in rows) else None for m in MODES}
        # Public views cannot authenticate origin; definitive claims are unsupported under this protocol.
        supports = [(p, supported_modes(evidence_view(r, view))[0]) for r, p in rows]
        unsupported = sum(p["label"] != "unresolved" and compatible != [p["label"]] for p, compatible in supports)
        evidence_set_correct = sum(set(p["compatible"]) == set(compatible) for p, compatible in supports)
        # More than one session in a design cell is ambiguous, not extra matched pairs.
        cells = defaultdict(list)
        available_cells = defaultdict(int)
        for r in lookup.values():
            if r["scope"] == scope:
                available_cells[(r["protocol_hash"], r["backend"], r["task"], r["repetition"], r["mode"], r["worker"])] += 1
        for r, p in rows:
            cells[(r["protocol_hash"], r["backend"], r["task"], r["repetition"], r["mode"], r["worker"])].append((r, p))
        pairs = defaultdict(list)
        controller_groups = defaultdict(list)
        for key, cell in cells.items():
            if len(cell) == 1 and available_cells[key] == 1:
                protocol, backend, task, repetition, mode, worker = key
                pairs[(protocol, backend, task, mode, repetition)].extend(cell)
                controller_groups[(protocol, backend, task, worker, repetition)].extend(cell)
        paired = [(a, b) for group in pairs.values() for a, b in combinations(group, 2) if a[0]["worker"] != b[0]["worker"]]
        controller_pairs = [(a, b) for group in controller_groups.values() for a, b in combinations(group, 2) if a[0]["mode"] != b[0]["mode"]]
        eligible = sum(r["scope"] == scope for r in lookup.values())
        history = attempt_groups[(method, view, scope)]
        latest_attempts = {a["run_id"]: a for a in history}
        available_recalls = [v for v in recalls.values() if v is not None]
        summaries.append({"method": method, "view": view, "scope": scope, "n": len(rows),
            "eligible_n": eligible, "missing_predictions": eligible - len(rows),
            "prediction_completion": len(rows) / eligible if eligible else None,
            "answer_coverage_over_eligible": len(answered) / eligible if eligible else None,
            "correct_over_eligible": correct / eligible if eligible else None,
            "stale_predictions_excluded": stale[(method, view, scope)],
            "legacy_unbound_predictions": sum(not p.get("evidence_sha256") for r, p in rows),
            "evaluation_attempts": len(history), "failed_attempts": sum(a["status"] == "failed" for a in history),
            "latest_failed_runs": sum(a["status"] == "failed" for a in latest_attempts.values()),
            "ambiguous_pair_cells": sum(n > 1 for n in available_cells.values()),
            "answered": len(answered), "correct": correct, "coverage": len(answered) / len(rows) if rows else None,
            "assigned_mode_accuracy": correct / len(rows) if rows else None, "macro_recall": sum(available_recalls) / len(available_recalls) if available_recalls else None,
            "recall_by_mode": recalls, "answered_error": (sum(p["label"] != r["mode"] for r, p in answered) / len(answered)) if answered else None,
            "unsupported_definitive": unsupported, "evidence_set_correct": evidence_set_correct, "worker_pairs": len(paired),
            "worker_pair_both_correct": sum(all(p["label"] == r["mode"] for r, p in pair) for pair in paired),
            "worker_pair_disagreement": sum(a[1]["label"] != b[1]["label"] for a, b in paired),
            "controller_pairs": len(controller_pairs),
            "controller_pair_both_correct": sum(all(p["label"] == r["mode"] for r, p in pair) for pair in controller_pairs),
            "controller_pair_prediction_changed": sum(a[1]["label"] != b[1]["label"] for a, b in controller_pairs),
            "family_count": len({r["task"] for r, p in rows})})
    return {"split": split, "summaries": summaries, "note": "Fixture metrics verify software behavior only. Evidence views and repetitions are dependent; no statistical significance or real-model research finding is claimed."}


def task_score(run):
    task = TASKS[run["task"]]
    correct = sum(run["state"].get(r["id"]) == task["answers"][i] for i, r in enumerate(task["records"]))
    return {"correct": correct, "total": len(task["records"])}
