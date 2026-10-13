"""Optional, read-only defect/revision evidence report; never an acceptance gate.

``assess(root, source)`` consumes a schema-1 ``review-revision`` JSON record.
Candidates are hashed references to existing candidate manifests. Criteria name
their kind (visual/temporal/interaction), subjects, required_scope and environment
(any/native/lab/blender). Evidence names a candidate identity, criterion, subjects,
method, environment, observer, inspection, capability, inspected_scope, unknowns,
location and retained files. Clip/live temporal inspection additionally declares
an interval, duration_seconds and temporal_inspection; live observations declare
context and actions. Interaction declares ordinary/human/synthetic input_route.
Defects link before/after evidence IDs and candidate identities with named critic
and root rechecks (observer, status, verdict, candidate identity, evidence IDs,
inspected_scope, unknowns, observation). The independent critic differs from the
record's builder. The root may be the builder.

These are local named attestations: hashes detect drift, but cannot establish that
someone saw the media, operated the app, or told the truth. No video is decoded,
desktop lock implemented, native capability granted, or aesthetic/human verdict
inferred. This module does not feed validation.assess, qualify, or acceptance.
"""
from pathlib import Path
from .common import StudioError, digest, file_record, read_json, relative
from .evidence import canonical_inventory
from .records import required, verify_file
from .validation import interval, number


METHODS = {"still", "clip", "model_inspection", "scene_inspection", "live_interaction"}
ENVIRONMENTS = {"native", "lab", "blender", "any"}


def _object(value, label):
    if not isinstance(value, dict):
        raise StudioError(label + " must be an object")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise StudioError(label + " must be nonempty text")
    return value


def _strings(value, label, *, nonempty=False):
    if not isinstance(value, list) or nonempty and not value:
        raise StudioError(label + " must be a list" + (" with entries" if nonempty else ""))
    for item in value:
        _text(item, label)
    if len(set(value)) != len(value):
        raise StudioError(label + " has duplicate entries")
    return value


def _identity(value):
    _object(value, "Candidate identity")
    required(value, ["candidate_id", "content_digest"])
    return (_text(value["candidate_id"], "candidate_id"),
            _text(value["content_digest"], "content_digest"))


def _candidates(root, references):
    if not isinstance(references, list) or not references:
        raise StudioError("Review revision needs candidate manifest references")
    candidates = {}
    for reference in references:
        value = _object(read_json(verify_file(root, _object(reference, "Candidate reference"))), "Candidate")
        if value.get("kind") != "candidate" or value.get("schema_version") != 1:
            raise StudioError("Expected candidate schema_version 1")
        identity = _identity(value)
        if identity in candidates:
            raise StudioError("Duplicate candidate identity")
        if type(value.get("inventory_version", 1)) is not int or value.get("inventory_version", 1) not in {1, 2}:
            raise StudioError("Unsupported candidate inventory version")
        for prefix in ("content", "workflow"):
            files = value.get(prefix + "_files")
            if not isinstance(files, list) or not files:
                raise StudioError("Candidate needs retained " + prefix + " inventory")
            for item in files:
                required(_object(item, "Inventory entry"), ["path", "sha256"])
                relative(root, item["path"])
                sha = item["sha256"]
                if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                    raise StudioError("Inventory SHA-256 must be lowercase hex")
            ordered = canonical_inventory(files, portable=value.get("inventory_version", 1) == 2)
            if value.get("inventory_version", 1) == 2 and ordered != files:
                raise StudioError("Candidate version 2 inventory must be canonical")
            if digest(files) != value.get(prefix + "_digest"):
                raise StudioError("Candidate inventory identity mismatch")
        # Historical manifests are snapshots; do not demand yesterday's files
        # match the current working tree, or reinterpret them as current evidence.
        candidates[identity] = reference
    return candidates


def _evidence(root, value, candidates, criteria):
    required(value, ["id", "candidate_id", "content_digest", "criterion_id", "subjects",
                     "method", "environment", "observer", "inspection", "capability",
                     "inspected_scope", "unknowns", "files", "location"])
    for key in ("id", "observer", "location", "criterion_id", "method", "environment", "inspection", "capability"):
        _text(value[key], key)
    for key in ("subjects", "inspected_scope", "unknowns"):
        _strings(value[key], key, nonempty=key == "subjects")
    if value["method"] not in METHODS or value["environment"] not in ENVIRONMENTS - {"any"}:
        raise StudioError("Unknown evidence method/environment")
    if value["inspection"] not in {"performed", "not_run", "unsupported"} or value["capability"] not in {"supported", "unsupported", "unknown"}:
        raise StudioError("Unknown inspection/capability")
    criterion = criteria.get(value["criterion_id"])
    issues = []
    if _identity(value) not in candidates:
        issues.append("candidate identity is not retained")
    if criterion is None:
        issues.append("criterion is not declared")
    elif not set(value["subjects"]) <= set(criterion["subjects"]):
        issues.append("evidence names undeclared subjects")
    if value["inspection"] != "performed" or value["capability"] != "supported":
        issues.append("inspection was not performed with a supported capability")
    if not value["inspected_scope"]:
        issues.append("actual inspected scope is unknown")
    if not isinstance(value["files"], list):
        raise StudioError("Evidence files must be a list")
    if not value["files"]:
        issues.append("retained media or inspection notes are missing")
    for reference in value["files"]:
        try:
            verify_file(root, _object(reference, "Evidence reference"))
        except StudioError as exc:
            issues.append(str(exc))
    if value["method"] == "clip":
        media = value.get("media")
        if not isinstance(media, dict) or media not in value["files"]:
            issues.append("clip inspection needs its retained media file reference")
        try:
            interval(value.get("interval"), number(value.get("duration_seconds"), "inspected duration", .001))
        except StudioError as exc:
            issues.append(str(exc))
    if value["method"] == "live_interaction" and (not isinstance(value.get("context"), str)
            or not value["context"].strip() or not value.get("actions")):
        issues.append("live inspection needs actual context and actions")
    handoff = value.get("handoff")
    operational = []
    if handoff is not None:
        _object(handoff, "handoff")
        if _text(handoff.get("control_mode"), "handoff control_mode") not in {"exclusive", "operator_mediated"}:
            raise StudioError("Unknown handoff control_mode")
        if handoff["control_mode"] == "exclusive" and (handoff.get("released") is not True or handoff.get("state_reconciled") is not True):
            operational.append("exclusive inspection control release/state reconciliation is unresolved")
            issues.extend(operational)
    if criterion:
        if criterion["environment"] != "any" and value["environment"] != criterion["environment"]:
            issues.append("evidence environment differs from required criterion environment")
        if criterion["kind"] == "temporal":
            if value["method"] not in {"clip", "scene_inspection", "live_interaction"} or value.get("temporal_inspection") is not True:
                issues.append("temporal criterion needs actual clip or live temporal inspection")
            else:
                try:
                    interval(value.get("interval"), number(value.get("duration_seconds"), "inspected duration", .001))
                except StudioError as exc:
                    issues.append(str(exc))
                if value["method"] != "clip" and (not isinstance(value.get("context"), str) or not value["context"].strip() or not value.get("actions")):
                    issues.append("live temporal inspection needs actual context and actions")
        if criterion["kind"] == "interaction":
            if value["environment"] != "native" or value["method"] not in {"clip", "live_interaction"} or value.get("input_route") not in {"ordinary", "human"}:
                issues.append("gameplay criterion needs native ordinary-input interaction")
            if not isinstance(value.get("context"), str) or not value["context"].strip() or not value.get("actions"):
                issues.append("interaction needs actual context and actions")
            if value["method"] == "clip" and value.get("temporal_inspection") is not True:
                issues.append("interaction clip needs actual temporal inspection")
        if "actions" in value:
            _strings(value["actions"], "actions", nonempty=True)
    return {"record": value, "issues": issues, "operational_findings": operational}


def _coverage(identity, criterion, subjects, ids, evidence):
    issues, selected = [], []
    for eid in ids:
        entry = evidence.get(eid)
        if entry is None:
            issues.append("unknown evidence ID: " + eid)
        elif _identity(entry["record"]) != identity or entry["record"]["criterion_id"] != criterion["id"]:
            issues.append("evidence candidate/criterion mismatch: " + eid)
        elif entry["issues"]:
            issues.extend(eid + ": " + reason for reason in entry["issues"])
        else:
            selected.append(entry["record"])
    rows = []
    for subject in subjects:
        matching = [e for e in selected if subject in e["subjects"]]
        scopes = sorted({scope for e in matching for scope in e["inspected_scope"]})
        missing = sorted(set(criterion["required_scope"]) - set(scopes))
        rows.append({"subject": subject, "status": "observed" if matching and not missing else "partial" if matching else "unobserved",
                     "inspected_scope": scopes, "missing_scope": missing,
                     "evidence": [e["id"] for e in matching],
                     "unknowns": sorted({u for e in matching for u in e["unknowns"]})})
        if not matching or missing:
            issues.append("uncovered subject/scope: " + subject + (" / " + ", ".join(missing) if missing else ""))
    return rows, issues


def _recheck(value, label, identity, ids, criterion, builder):
    if value is None:
        return [label + " recheck was not run"]
    _object(value, label + " recheck")
    required(value, ["observer", "status", "verdict", "candidate_id", "content_digest", "evidence", "inspected_scope", "unknowns", "observation"])
    _text(value["observer"], "observer")
    _text(value["observation"], "observation")
    for key in ("evidence", "inspected_scope", "unknowns"):
        _strings(value[key], key)
    issues = []
    if value["status"] != "performed" or value["verdict"] != "met":
        issues.append(label + " recheck does not report the requested outcome met")
    if _identity(value) != identity or not value["evidence"] or not set(value["evidence"]) <= set(ids):
        issues.append(label + " recheck does not bind the revised candidate/evidence")
    if not set(criterion["required_scope"]) <= set(value["inspected_scope"]):
        issues.append(label + " recheck omits required scope")
    if label == "critic" and value["observer"].strip().casefold() == builder.strip().casefold():
        issues.append("critic must differ from the builder")
    return issues


def _lineage(root, defect, before, after, criterion_id):
    refs = [defect.get("before_run"), defect.get("after_run")]
    if not any(refs):
        return []
    if not all(refs):
        return ["both existing before/after run references are required when supplied"]
    try:
        from .validation import validate_run
        runs = []
        for reference in refs:
            path = verify_file(root, _object(reference, "Run reference"))
            if path.name != "run.json":
                raise StudioError("Expected existing run.json reference")
            runs.append(validate_run(root, path.parent.relative_to(root).as_posix(), current=False, check_assessment=False))
        a, b = runs
        if (_identity(a["candidate"]) != before or _identity(b["candidate"]) != after
            or b.get("previous") != refs[0] or criterion_id not in b.get("affected", [])
            or a.get("role") != "before" or b.get("role") != "after"):
            return ["existing affected before/after lineage differs from defect"]
    except StudioError as exc:
        return [str(exc)]
    return []


def assess(root, source):
    """Report structural coverage/closure; do not mutate or accept anything.

    Malformed record structure raises StudioError. Incomplete or contradictory
    evidence produces per-defect reasons and partial coverage, without gating the
    project. Human acceptance is always not_established by this operation.
    """
    root = Path(root).resolve()
    path = relative(root, source)
    value = _object(read_json(path), "Review revision")
    if value.get("schema_version") != 1 or value.get("kind") != "review-revision":
        raise StudioError("Expected review-revision schema_version 1")
    builder = _text(value.get("builder"), "builder")
    for key in ("criteria", "evidence", "defects"):
        if not isinstance(value.get(key), list):
            raise StudioError(key + " must be a list")
    candidates = _candidates(root, value.get("candidates"))
    criteria = {}
    for criterion in value.get("criteria", []):
        _object(criterion, "Criterion")
        required(criterion, ["id", "kind", "subjects", "required_scope", "environment"])
        for key in ("id", "kind", "environment"):
            _text(criterion[key], "Criterion " + key)
        if criterion["id"] in criteria or criterion["kind"] not in {"visual", "temporal", "interaction"} or criterion["environment"] not in ENVIRONMENTS:
            raise StudioError("Duplicate/unknown criterion kind/environment")
        _strings(criterion["subjects"], "criterion subjects", nonempty=True)
        _strings(criterion["required_scope"], "required_scope", nonempty=True)
        criteria[criterion["id"]] = criterion
    if not criteria:
        raise StudioError("Review revision needs declared criteria")
    evidence = {}
    for item in value.get("evidence", []):
        checked = _evidence(root, _object(item, "Evidence"), candidates, criteria)
        if item["id"] in evidence:
            raise StudioError("Duplicate evidence ID")
        evidence[item["id"]] = checked
    coverage = []
    for identity in candidates:
        for criterion in criteria.values():
            ids = [eid for eid, e in evidence.items() if _identity(e["record"]) == identity and e["record"]["criterion_id"] == criterion["id"]]
            rows, _ = _coverage(identity, criterion, criterion["subjects"], ids, evidence)
            coverage.append({"candidate_id": identity[0], "content_digest": identity[1], "criterion_id": criterion["id"], "subjects": rows})
    defects, seen = [], set()
    for defect in value.get("defects", []):
        _object(defect, "Defect")
        required(defect, ["defect_id", "criterion_id", "subjects", "candidate_before", "before_evidence", "observed_defect", "requested_outcome", "root_decision"])
        for key in ("defect_id", "observed_defect", "requested_outcome"):
            _text(defect[key], key)
        _text(defect["criterion_id"], "defect criterion_id")
        if defect["defect_id"] in seen or defect["criterion_id"] not in criteria:
            raise StudioError("Duplicate defect ID or unknown criterion")
        seen.add(defect["defect_id"])
        criterion = criteria[defect["criterion_id"]]
        subjects = _strings(defect["subjects"], "defect subjects", nonempty=True)
        if not set(subjects) <= set(criterion["subjects"]):
            raise StudioError("Defect names undeclared subjects")
        before = _identity(defect["candidate_before"])
        after = _identity(defect["candidate_after"]) if defect.get("candidate_after") else None
        before_ids = _strings(defect["before_evidence"], "before_evidence")
        after_ids = _strings(defect.get("after_evidence", []), "after_evidence")
        _, issues = _coverage(before, criterion, subjects, before_ids, evidence)
        if before not in candidates or after not in candidates:
            issues.append("before/revised candidate is not retained")
        if after is None or before[1] == after[1]:
            issues.append("closure needs changed candidate content")
        if not isinstance(defect.get("change_summary"), str) or not defect["change_summary"].strip():
            issues.append("revision change summary is missing")
        _, after_issues = _coverage(after, criterion, subjects, after_ids, evidence)
        issues.extend(after_issues)
        for label in ("critic", "root"):
            recheck = defect.get(label + "_recheck")
            issues.extend(_recheck(recheck, label, after, after_ids, criterion, builder))
            if recheck:
                _, recheck_issues = _coverage(after, criterion, subjects, recheck["evidence"], evidence)
                issues.extend(label + ": " + reason for reason in recheck_issues)
        issues.extend(_lineage(root, defect, before, after, criterion["id"]))
        decision = _text(defect["root_decision"], "root_decision")
        if decision not in {"open", "closed", "rejected"}:
            raise StudioError("Unknown root decision")
        rejected = decision == "rejected" and (isinstance(defect.get("decision_reason"), str)
                   and bool(defect["decision_reason"].strip()) and defect.get("decision_basis") in {"reference", "user_intent"})
        if decision == "rejected" and not rejected:
            issues.append("rejected finding needs an explicit reference/user-intent basis and reason")
        supported = decision == "closed" and not issues
        defects.append({"defect_id": defect["defect_id"], "criterion_id": criterion["id"],
                        "subjects": subjects, "root_decision": decision,
                        "closure_supported_by_record": supported,
                        "state": "closure_supported_by_record" if supported else "rejected_by_root" if rejected else "open",
                        "decision_reason": defect.get("decision_reason"), "decision_basis": defect.get("decision_basis"),
                        "reasons": sorted(set(issues)),
                        "recheck_unknowns": {label: (defect.get(label + "_recheck") or {}).get("unknowns", []) for label in ("critic", "root")}})
    return {"schema_version": 1, "kind": "review-revision-report", "source": file_record(root, path),
            "authority": "local_named_attestation", "human_acceptance": "not_established",
            "limitation": "Hashes bind retained bytes and named declarations; inspection, aesthetic quality, native capability and human acceptance are not independently established.",
            "coverage": coverage, "defects": defects,
            "open_defects": [d["defect_id"] for d in defects if d["state"] == "open"],
            "rejected_findings": [d["defect_id"] for d in defects if d["state"] == "rejected_by_root"],
            "unsupported_closure_claims": [d["defect_id"] for d in defects if d["root_decision"] == "closed" and not d["closure_supported_by_record"]],
            "evidence_issues": [{"evidence_id": eid, "reasons": e["issues"]} for eid, e in evidence.items() if e["issues"]],
            "inspections": [{"evidence_id": eid, "candidate_id": e["record"]["candidate_id"],
                             "content_digest": e["record"]["content_digest"], "criterion_id": e["record"]["criterion_id"],
                             "subjects": e["record"]["subjects"], "method": e["record"]["method"],
                             "declared_environment": e["record"]["environment"], "observer": e["record"]["observer"],
                             "inspection": e["record"]["inspection"], "capability": e["record"]["capability"],
                             "inspected_scope": e["record"]["inspected_scope"], "unknowns": e["record"]["unknowns"],
                             "location": e["record"]["location"], "interval": e["record"].get("interval"),
                             "files": e["record"]["files"]} for eid, e in evidence.items()],
            "operational_findings": [{"evidence_id": eid, "findings": e["operational_findings"]} for eid, e in evidence.items() if e["operational_findings"]]}
