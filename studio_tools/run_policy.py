"""Synchronous run-decision validation; no scheduler or execution permission grant.

Authority files provide reviewable provenance, not authentication of a human.
Quality observations remain separate from candidate performance qualification.
"""

from datetime import datetime
import math
import re

from .common import StudioError, read_json, safe_id
from .records import required, verify_file

STOP_TYPES = {"deadline", "overall_budget", "human_stop", "global_safety",
              "goal_done", "development_complete", "hard_gate", "all_lanes_blocked"}
BLOCK_TYPES = {"identity", "compile", "host", "resource", "authorization",
               "dependency", "hard_gate"}
MATURITIES = ("in-progress", "source-ready", "root-reviewed", "integrated",
              "native-reviewed", "user-accepted")
COMPARISON_CONDITIONS = {"route", "scope", "engine", "renderer", "resolution",
                         "hardware", "metric", "statistic"}


def number(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise StudioError(field + " must be a finite nonnegative number")
    return value


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value
    ):
        raise StudioError("Expected an exact UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StudioError("Invalid UTC timestamp") from exc


def authority(item, root, allowed):
    if not isinstance(item, dict) or set(item) != {"type", "reference", "rule_id"}:
        raise StudioError("Authority needs only type, reference and rule_id")
    if item["type"] not in allowed:
        raise StudioError("Unknown or denied authority: " + str(item["type"]))
    safe_id(item["rule_id"])
    verify_file(root, item["reference"])


def evidence(items, root):
    if not isinstance(items, list) or not items:
        raise StudioError("Binding evidence must be a nonempty list")
    for item in items:
        verify_file(root, item)


def unique(items, field):
    if not isinstance(items, list):
        raise StudioError(field + " must be a list")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise StudioError(field + " rows must be objects")
        safe_id(item.get("id"))
        if item["id"] in result:
            raise StudioError("Duplicate " + field + " ID")
        result[item["id"]] = item
    return result


def validate_policy(record, root):
    required(record, ["run_id", "project_id", "authorization", "started_utc",
                      "cutoff_utc", "goals", "lanes", "overall_limits", "hard_gates"])
    safe_id(record["run_id"])
    safe_id(record["project_id"])
    verify_file(root, record["authorization"])
    if utc(record["started_utc"]) >= utc(record["cutoff_utc"]):
        raise StudioError("Run cutoff must follow its actual start")
    mode = record.get("mode", "development")
    if mode not in {"development", "strict_qualification"}:
        raise StudioError("Unknown run policy mode")
    if mode == "strict_qualification":
        authority(record.get("strict_authority"), root, {"human_instruction", "contract"})
    goals = record["goals"]
    if not isinstance(goals, list) or not goals or len(set(goals)) != len(goals):
        raise StudioError("Policy needs unique authorized goal IDs")
    for goal in goals:
        safe_id(goal)
    lanes = unique(record["lanes"], "lane")
    if not lanes or {lane.get("goal_id") for lane in lanes.values()} != set(goals):
        raise StudioError("Every authorized goal needs a policy lane")
    for lane in lanes.values():
        required(lane, ["goal_id", "scope", "dependencies"])
        safe_id(lane["scope"])
        if "completion_maturity" in lane and lane["completion_maturity"] not in MATURITIES[1:]:
            raise StudioError("Lane completion_maturity must be a known maturity beyond in-progress")
        deps = lane["dependencies"]
        if not isinstance(deps, list) or len(set(deps)) != len(deps) or any(d not in lanes for d in deps):
            raise StudioError("Unknown or duplicate lane dependency")
    def visit(lane_id, active):
        if lane_id in active:
            raise StudioError("Cyclic lane dependency")
        for dep in lanes[lane_id]["dependencies"]:
            visit(dep, active | {lane_id})
    for lane_id in lanes:
        visit(lane_id, set())
    for limit in unique(record["overall_limits"], "overall limit").values():
        number(limit.get("maximum"), "Overall maximum")
        if limit.get("unit") not in {"seconds", "tokens", "launches"}:
            raise StudioError("Unknown overall limit unit")
        authority(limit.get("authority"), root, {"human_instruction", "contract"})
    for gate in unique(record["hard_gates"], "hard gate").values():
        if mode != "strict_qualification":
            raise StudioError("Qualification hard gates require explicit strict mode")
        if gate.get("effect") not in {"block_action", "block_scope", "stop_run"}:
            raise StudioError("Unknown hard gate effect")
        affected = gate.get("affected", {})
        if affected.get("kind") not in {"action", "scope", "run"}:
            raise StudioError("Unknown hard gate affected kind")
        safe_id(affected.get("id"))
        if (gate["effect"] == "stop_run") != (affected["kind"] == "run"):
            raise StudioError("Hard stop gate must explicitly affect the run")
        if affected["kind"] == "run" and affected["id"] != record["run_id"]:
            raise StudioError("Hard stop gate belongs to another run")
        authority(gate.get("authority"), root, {"human_instruction", "contract"})
    return {"ok": True, "kind": "run-policy", "mode": mode}


def lane_complete(lane, row, mode):
    """Compare declared completion targets after inventory evidence validation."""
    target = lane.get("completion_maturity", "user-accepted") if mode == "development" else "user-accepted"
    return (row["status"] == "complete" and bool(row.get("completion_evidence"))
            and MATURITIES.index(row["maturity"]) >= MATURITIES.index(target))


def compare_baseline(baseline, candidate, target):
    """Conservative observation summary; never creates performance pass evidence.

    Comparability is an exact match of caller-declared conditions. A demonstrated
    regression additionally needs both repeat counts and the declared tolerance.
    """
    number(target, "Target")
    for observation in (baseline, candidate):
        if observation is not None:
            if not isinstance(observation, dict):
                raise StudioError("Comparison observation must be an object")
            number(observation.get("value_ms"), "Frame metric")
    valid = candidate is not None and candidate.get("performance_class") == "clean_qualification"
    comparable = (valid and baseline is not None
                  and baseline.get("performance_class") == "clean_qualification"
                  and isinstance(baseline.get("conditions"), dict)
                  and COMPARISON_CONDITIONS <= set(baseline["conditions"])
                  and all(baseline["conditions"][key] not in (None, "", []) for key in COMPARISON_CONDITIONS)
                  and baseline["conditions"] == candidate.get("conditions"))
    regression = "unproven"
    if comparable:
        delta = candidate["value_ms"] - baseline["value_ms"]
        tolerance = number(candidate.get("tolerance_ms", 0), "Comparison tolerance")
        repeats = candidate.get("repeat_count", 0)
        required_repeats = candidate.get("required_repeats", 2)
        if type(repeats) is not int or type(required_repeats) is not int or repeats < 0 or required_repeats < 2:
            raise StudioError("Comparison requires integer repeat counts")
        if delta <= tolerance:
            regression = "not_observed"
        elif repeats >= required_repeats and type(baseline.get("repeat_count")) is int and baseline["repeat_count"] >= required_repeats:
            regression = "demonstrated"
    return {
        "target_status": ("met" if candidate["value_ms"] <= target else "missed") if valid else "unverified",
        "baseline_shortfall": "unverified" if baseline is None else (
            "present" if baseline["value_ms"] > target else "absent"),
        "regression_status": regression,
        "development_action": "bounded_repair" if regression == "demonstrated" else "continue",
    }


def validate_decision(record, root):
    required(record, ["decision_id", "run_id", "at_utc", "policy", "candidate",
                      "candidate_id", "content_digest", "lane_inventory", "disposition",
                      "remaining", "affected", "trigger", "rationale"])
    if not isinstance(record["remaining"], dict) or not isinstance(record["trigger"], dict):
        raise StudioError("Remaining budget and trigger must be objects")
    safe_id(record["decision_id"])
    policy = read_json(verify_file(root, record["policy"]))
    if policy.get("kind") != "run-policy" or policy.get("schema_version") != 1:
        raise StudioError("Decision policy must be a run-policy version 1")
    validate_policy(policy, root)
    if record["run_id"] != policy["run_id"]:
        raise StudioError("Decision belongs to a different run")
    candidate = read_json(verify_file(root, record["candidate"]))
    from .evidence import validate_candidate
    if candidate.get("kind") != "candidate":
        raise StudioError("Decision needs a candidate record")
    validate_candidate(candidate, root)
    if candidate.get("candidate_id") != record["candidate_id"] or candidate.get("content_digest") != record["content_digest"]:
        raise StudioError("Decision candidate identity mismatch")
    at = utc(record["at_utc"])
    cutoff = utc(policy["cutoff_utc"])
    if at < utc(policy["started_utc"]):
        raise StudioError("Decision predates its run")
    remaining_seconds = max(0, (cutoff - at).total_seconds())
    if number(record["remaining"].get("seconds_until_cutoff"), "Remaining seconds") != remaining_seconds:
        raise StudioError("Remaining time disagrees with actual cutoff")
    limits = unique(policy["overall_limits"], "overall limit")
    usages = unique(record["remaining"].get("explicit_limits"), "limit usage")
    if set(usages) != set(limits):
        raise StudioError("Every explicit overall limit needs current usage")
    exhausted = set()
    for limit_id, limit in limits.items():
        used = usages[limit_id].get("used")
        if used is None:
            raise StudioError("Unknown overall usage cannot be treated as zero")
        if number(used, "Overall usage") >= limit["maximum"]:
            exhausted.add(limit_id)
    lanes = unique(policy["lanes"], "lane")
    inventory = unique(record["lane_inventory"], "lane inventory")
    if set(inventory) != set(lanes):
        raise StudioError("Incomplete lane inventory; account for every authorized lane")
    gates = unique(policy["hard_gates"], "hard gate")
    for lane_id, row in inventory.items():
        if row.get("maturity") not in MATURITIES or row.get("status") not in {"feasible", "deferred", "blocked", "complete"}:
            raise StudioError("Unknown lane maturity or status")
        if row.get("status") != "complete":
            required(row, ["next_operation"])
            if not isinstance(row["next_operation"], str) or not row["next_operation"].strip():
                raise StudioError("Unfinished lane needs a concrete text next operation")
        if row["status"] == "blocked":
            blocker = row.get("blocker", {})
            authority(blocker.get("authority"), root, BLOCK_TYPES)
            evidence(blocker.get("evidence"), root)
            if blocker["authority"]["type"] == "hard_gate":
                gate = gates.get(blocker.get("gate_id"))
                if not gate or gate["effect"] == "stop_run":
                    raise StudioError("Lane needs an applicable action/scope gate")
                affected = gate["affected"]
                expected = lanes[lane_id]["scope"] if affected["kind"] == "scope" else lane_id
                if affected["id"] != expected:
                    raise StudioError("Hard gate does not affect this lane")
            if blocker["authority"]["type"] == "dependency":
                dep = blocker.get("lane_id")
                if dep not in lanes[lane_id]["dependencies"] or inventory[dep]["status"] == "complete":
                    raise StudioError("Dependency blocker must name an unfinished dependency")
        if row["status"] == "complete":
            evidence(row.get("completion_evidence"), root)
        if row["status"] == "feasible" and any(inventory[d]["status"] != "complete" for d in lanes[lane_id]["dependencies"]):
            raise StudioError("Feasible lane has unfinished dependencies")
    feasible = [key for key, row in inventory.items() if row["status"] == "feasible"]
    mode = policy.get("mode", "development")
    completed = {key for key, row in inventory.items() if lane_complete(lanes[key], row, mode)}
    pending_human_review = [key for key, row in inventory.items() if row["maturity"] != "user-accepted"]
    disposition = record["disposition"]
    if disposition not in {"continue", "switch_lane", "block_action", "stop_experiment", "handback", "stop_run"}:
        raise StudioError("Unknown run disposition")
    affected = record["affected"]
    if not isinstance(affected, dict) or affected.get("kind") not in {"experiment", "action", "scope", "run"}:
        raise StudioError("Unknown affected scope")
    safe_id(affected.get("id"))
    if affected["kind"] == "action" and affected["id"] not in lanes:
        raise StudioError("Affected action must name an authorized lane")
    if affected["kind"] == "scope" and affected["id"] not in {lane["scope"] for lane in lanes.values()}:
        raise StudioError("Affected scope must be authorized")
    stop = record.get("stop_authority")
    if stop is not None:
        authority(stop, root, STOP_TYPES)
    final = disposition in {"handback", "stop_run"}
    if final:
        if stop is None or affected != {"kind": "run", "id": policy["run_id"]}:
            raise StudioError("Whole-run handback requires recorded run stop authority")
        kind = stop["type"]
        evidence(record["trigger"].get("evidence"), root)
        allowed = {
            "deadline": at >= cutoff,
            "overall_budget": stop["rule_id"] in exhausted,
            "human_stop": record["trigger"].get("code") == "human_stop",
            "global_safety": record["trigger"].get("code") == "global_safety",
            "goal_done": all(row["status"] == "complete" and row["maturity"] == "user-accepted"
                             for row in inventory.values()),
            "development_complete": mode == "development" and completed == set(lanes),
            "all_lanes_blocked": (any(row["status"] == "blocked" for row in inventory.values())
                                  and all(row["status"] == "blocked" or key in completed
                                          for key, row in inventory.items())),
            "hard_gate": (stop["rule_id"] in gates and gates[stop["rule_id"]]["effect"] == "stop_run"
                          and record["trigger"].get("code") == "hard_gate_failed"
                          and record["trigger"].get("gate_id") == stop["rule_id"]),
        }[kind]
        if not allowed:
            next_lane = feasible[0] if feasible else "inventory requires review"
            raise StudioError("Denied stop authority: " + kind + "; next lane: " + next_lane)
        if kind == "hard_gate" and stop["reference"] != gates[stop["rule_id"]]["authority"]["reference"]:
            raise StudioError("Hard stop must cite the gate's explicit authority")
    else:
        failed_gate = gates.get(record["trigger"].get("gate_id"), {})
        hard_stop = (record["trigger"].get("code") == "hard_gate_failed"
                     and failed_gate.get("effect") == "stop_run")
        if stop is not None or at >= cutoff or exhausted or hard_stop or record["trigger"].get("code") in {"human_stop", "global_safety"}:
            raise StudioError("A binding whole-run stop prohibits continuation")
        if feasible:
            selected = record.get("selected_lane")
            if selected not in feasible or record.get("selected_operation") != inventory[selected]["next_operation"]:
                raise StudioError("Mandatory continuation needs a concrete feasible lane and operation")
        elif disposition in {"continue", "switch_lane"}:
            raise StudioError("Continuation needs a safe actionable lane")
        if disposition == "stop_experiment":
            hypothesis = record.get("hypothesis", {})
            if not isinstance(hypothesis, dict):
                raise StudioError("Hypothesis must be an object")
            safe_id(hypothesis.get("stable_family_id"))
            if affected != {"kind": "experiment", "id": hypothesis["stable_family_id"]}:
                raise StudioError("Hypothesis stop must be scoped to its stable family")
            trials = number(hypothesis.get("used_trials"), "Used trials")
            if type(trials) is not int:
                raise StudioError("Used trials must be an integer")
            seconds = number(hypothesis.get("used_seconds"), "Hypothesis seconds")
            if trials < 3 and seconds < 900:
                raise StudioError("Hypothesis allowance has not been exhausted")
    return {"ok": True, "kind": "run-decision", "disposition": disposition,
            "stop_authorized": final, "mandatory_continuation": bool(feasible) and not final,
            "next_lane": record.get("selected_lane") if not final else None,
            "pending_human_review": pending_human_review, "human_acceptance_established": False}
