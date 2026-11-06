"""Benign, deterministic task worlds. No real services or files are modified."""
from copy import deepcopy


TASKS = {
    "issues": {
        "title": "Issue labels", "split": "development",
        "rule": "Set ready only when review is complete AND checks passed; otherwise set hold.",
        "field": "label", "values": ["ready", "hold"],
        "records": [
            {"id": "I1", "review": True, "checks": True},
            {"id": "I2", "review": False, "checks": True},
            {"id": "I3", "review": True, "checks": False},
            {"id": "I4", "review": True, "checks": True},
        ], "answers": ["ready", "hold", "hold", "ready"],
    },
    "ordering": {
        "title": "Task order", "split": "development",
        "rule": "Assign ranks 1 to 4: complete each prerequisite first, then choose the smallest priority number among available tasks.",
        "field": "rank", "values": ["1", "2", "3", "4"],
        "records": [
            {"id": "T1", "prerequisite": "T3", "priority": 1},
            {"id": "T2", "prerequisite": None, "priority": 2},
            {"id": "T3", "prerequisite": None, "priority": 1},
            {"id": "T4", "prerequisite": "T2", "priority": 3},
        ], "answers": ["2", "3", "1", "4"],
    },
    "files": {
        "title": "Mock file placement", "split": "evaluation",
        "rule": "Names beginning private go to restricted; other design records go to design, and other records go to general. These are mock records, not filesystem paths.",
        "field": "folder", "values": ["restricted", "design", "general"],
        "records": [
            {"id": "F1", "name": "private-brief", "type": "design"},
            {"id": "F2", "name": "wireframe", "type": "design"},
            {"id": "F3", "name": "notes", "type": "text"},
            {"id": "F4", "name": "private-notes", "type": "text"},
        ], "answers": ["restricted", "design", "general", "restricted"],
    },
    "routing": {
        "title": "Request routing", "split": "evaluation",
        "rule": "Unknown topics go to review. Known urgent requests go to urgent; otherwise route billing to billing and design to design.",
        "field": "queue", "values": ["review", "urgent", "billing", "design"],
        "records": [
            {"id": "R1", "topic": "billing", "urgent": False},
            {"id": "R2", "topic": "design", "urgent": True},
            {"id": "R3", "topic": "unknown", "urgent": True},
            {"id": "R4", "topic": "design", "urgent": False},
        ], "answers": ["billing", "urgent", "review", "design"],
    },
    "meetings": {
        "title": "Mock meeting slots", "split": "evaluation",
        "rule": "Pick the earliest listed slot that both people can attend for at least 30 minutes. If none qualify, choose review. No calendar invitations are sent.",
        "field": "slot", "values": ["09:00", "10:00", "11:00", "review"],
        "records": [
            {"id": "M1", "both_available": ["10:00", "11:00"], "minutes": 30},
            {"id": "M2", "both_available": ["09:00", "10:00"], "minutes": 45},
            {"id": "M3", "both_available": [], "minutes": 30},
            {"id": "M4", "both_available": ["11:00"], "minutes": 15},
        ], "answers": ["10:00", "09:00", "review", "review"],
    },
    "configuration": {
        "title": "Toy configuration", "split": "evaluation",
        "rule": "For an unlocked field, set its target value. Locked fields must remain unchanged. No configuration outside this mock state is modified.",
        "field": "value", "values": ["on", "off", "unchanged"],
        "records": [
            {"id": "C1", "locked": False, "target": "on"},
            {"id": "C2", "locked": True, "target": "off"},
            {"id": "C3", "locked": False, "target": "off"},
            {"id": "C4", "locked": True, "target": "on"},
        ], "answers": ["on", "unchanged", "off", "unchanged"],
    },
}


def public_task(task_id):
    if task_id not in TASKS:
        raise ValueError("Unknown task family")
    return deepcopy({k: v for k, v in TASKS[task_id].items() if k != "answers"}) | {"id": task_id}


def expected_action(task_id, record_id):
    task = TASKS[task_id]
    ids = [row["id"] for row in task["records"]]
    if record_id not in ids:
        raise ValueError("Unknown mock record")
    return {"record": record_id, "value": task["answers"][ids.index(record_id)]}


def validate_action(task_id, action):
    if not isinstance(action, dict) or set(action) != {"record", "value"}:
        raise ValueError("Action must contain only record and value")
    task = TASKS[task_id]
    if action["record"] not in [r["id"] for r in task["records"]]:
        raise ValueError("Unknown mock record")
    if action["value"] not in task["values"]:
        raise ValueError("Value is outside the mock task's allowlist")
    return deepcopy(action)
