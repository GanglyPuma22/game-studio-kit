"""Validate a character run record: owner gates, spend caps and stage order.

The record is bookkeeping for the character pipeline
(skills/studio-director/references/character-pipeline.md). Validation checks
that no stage ran ahead of its gate or its inputs, that every finished stage
names hashed outputs and a passing check, and that recorded spend stays under
each approved cap. It cannot prove that a person approved anything.
"""

import math

from .common import StudioError, safe_id
from .records import required, verify_file

GATES = ("concept", "voice")
GATE_STATES = {"open", "provisional", "approved"}
STAGE_STATES = {"pending", "running", "done", "stopped", "reopened"}
CHECK_VERDICTS = {"pass", "fail", "not_run"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _amount(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise StudioError(field + " must be a finite nonnegative number")
    return value


def _gate(name, gate, builder, root):
    if not isinstance(gate, dict):
        raise StudioError("gates." + name + " must be an object")
    status = gate.get("status")
    if status not in GATE_STATES:
        raise StudioError("gates." + name + ".status must be open, provisional or approved")
    if status == "open":
        return status
    required(gate, ["choice", "file"])
    if not _text(gate["choice"]):
        raise StudioError("gates." + name + ".choice must name the picked option")
    verify_file(root, gate["file"])
    if status == "approved":
        required(gate, ["approved_by", "approved_at"])
        if not _text(gate["approved_by"]) or not _text(gate["approved_at"]):
            raise StudioError("gates." + name + " needs approved_by and approved_at text")
        if gate["approved_by"].strip() == builder:
            raise StudioError("gates." + name + " was approved by the builder; the owner approves gates")
    return status


def _budgets(budgets, builder):
    if not isinstance(budgets, list):
        raise StudioError("budgets must be a list")
    caps = {}
    for index, budget in enumerate(budgets):
        label = "budgets[" + str(index) + "]"
        if not isinstance(budget, dict):
            raise StudioError(label + " must be an object")
        required(budget, ["route", "unit", "cap", "approved_by", "approved_at"])
        route = budget["route"]
        safe_id(route)
        if route in caps:
            raise StudioError("Duplicate budget route: " + route)
        if not _text(budget["approved_by"]) or budget["approved_by"].strip() == builder:
            raise StudioError(label + " cap must be approved by the owner, not the builder")
        caps[route] = _amount(budget["cap"], label + ".cap")
    return caps


def validate_character_run(record, root):
    required(record, ["character_id", "builder", "brief", "gates", "budgets",
                      "repair_round_cap", "stages"])
    safe_id(record["character_id"])
    builder = record["builder"]
    if not _text(builder):
        raise StudioError("builder must name the session or agent doing the work")
    builder = builder.strip()
    if not isinstance(record["brief"], dict) or not record["brief"]:
        raise StudioError("brief must be a nonempty object")
    if type(record["repair_round_cap"]) is not int or record["repair_round_cap"] < 1:
        raise StudioError("repair_round_cap must be a positive integer")

    gates = record["gates"]
    if not isinstance(gates, dict) or set(gates) != set(GATES):
        raise StudioError("gates must hold exactly concept and voice")
    gate_state = {name: _gate(name, gates[name], builder, root) for name in GATES}
    caps = _budgets(record["budgets"], builder)

    stages = record["stages"]
    if not isinstance(stages, list) or not stages:
        raise StudioError("stages must be a nonempty list")
    seen = {}
    spent = {route: 0 for route in caps}
    for index, stage in enumerate(stages):
        label = "stages[" + str(index) + "]"
        if not isinstance(stage, dict):
            raise StudioError(label + " must be an object")
        required(stage, ["id", "status", "needs"])
        stage_id = stage["id"]
        safe_id(stage_id)
        if stage_id in seen:
            raise StudioError("Duplicate stage id: " + stage_id)
        status = stage["status"]
        if status not in STAGE_STATES:
            raise StudioError(label + ".status is not a known stage state")
        needs = stage["needs"]
        if not isinstance(needs, list):
            raise StudioError(label + ".needs must be a list")
        for need in needs:
            if not isinstance(need, str):
                raise StudioError(label + ".needs entries must be text")
            if need.startswith("gate:"):
                if need[5:] not in GATES:
                    raise StudioError(label + " needs unknown gate " + need)
            elif need not in seen:
                raise StudioError(label + " needs " + need + ", which is not an earlier stage")
        # A reopened stage waits for its reopened inputs like a pending one.
        if status not in {"pending", "reopened"}:
            for need in needs:
                if need.startswith("gate:"):
                    if gate_state[need[5:]] == "open":
                        raise StudioError(stage_id + " started before the " + need[5:] + " gate")
                elif seen[need]["status"] != "done":
                    raise StudioError(stage_id + " started before " + need + " was done")
        # The run ends at review, so both gates need the owner's confirmation
        # whatever the review stage lists as its inputs.
        if stage_id == "review" and status == "done":
            for name in GATES:
                if gate_state[name] != "approved":
                    raise StudioError("review cannot finish before the owner approves the " + name
                                      + " gate (" + gate_state[name] + ")")
        rounds = stage.get("repair_rounds", 0)
        if type(rounds) is not int or rounds < 0:
            raise StudioError(label + ".repair_rounds must be a nonnegative integer")
        cap = record["repair_round_cap"]
        failing = isinstance(stage.get("check"), dict) and stage["check"].get("verdict") == "fail"
        if status not in {"stopped", "done"} and (rounds > cap or (rounds == cap and failing)):
            raise StudioError(stage_id + " still fails after the repair round cap; stop it and report")
        for paid in stage.get("paid", []):
            if not isinstance(paid, dict):
                raise StudioError(label + ".paid entries must be objects")
            required(paid, ["route", "spent"])
            if paid["route"] not in caps:
                raise StudioError(stage_id + " spent on " + str(paid["route"])
                                  + " without an approved cap")
            spent[paid["route"]] += _amount(paid["spent"], label + ".paid.spent")
        if status == "done":
            outputs = stage.get("outputs")
            if not isinstance(outputs, list) or not outputs:
                raise StudioError(stage_id + " is done but lists no outputs")
            for item in outputs:
                verify_file(root, item)
            check = stage.get("check")
            if not isinstance(check, dict) or check.get("verdict") != "pass":
                raise StudioError(stage_id + " is done without a passing check")
            verify_file(root, check.get("evidence", {}))
        elif isinstance(stage.get("check"), dict) and stage["check"].get("verdict") not in CHECK_VERDICTS:
            raise StudioError(label + ".check.verdict must be pass, fail or not_run")
        seen[stage_id] = stage
    for route, total in spent.items():
        if total > caps[route]:
            raise StudioError("Spend on " + route + " (" + str(total) + ") passed its approved cap ("
                              + str(caps[route]) + ")")
    rounds = record.get("review_rounds", [])
    if not isinstance(rounds, list):
        raise StudioError("review_rounds must be a list")
    for entry in rounds:
        if not isinstance(entry, dict):
            raise StudioError("review_rounds entries must be objects")
        required(entry, ["at", "reopened"])
        if not isinstance(entry["reopened"], list) or any(r not in seen for r in entry["reopened"]):
            raise StudioError("review_rounds can only reopen known stages")
    return {"gates": gate_state, "spent": spent, "caps": caps}
