"""One bounded Gemini Interactions video request, with full context and dense frames.

Official API/schema references and current limits are recorded in validation-loop.md.
No installation, implicit upload, retry, remote URL input, or perception self-attestation.
"""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import urllib.request
from .common import StudioError, digest, file_record, read_json, relative, safe_id, sha256, write_json
from .config import credential
from .records import VERDICTS, required, verify_file
from .validation import interval, number, tool_identity, validate_run

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


def reserve(root, budget, run_id, clip_hash):
    if budget.get("upload_authorized") is not True or clip_hash not in budget.get("approved_media_sha256", []):
        raise StudioError("Video upload needs explicit approval for this exact media hash")
    required(budget, ["authorization_id", "model", "rate_verified_utc", "max_request_bytes", "max_output_tokens"])
    safe_id(budget["authorization_id"])
    if not re.fullmatch(r"gemini-[A-Za-z0-9.-]+", budget["model"]):
        raise StudioError("Select an explicit Gemini model")
    max_requests = budget.get("max_requests")
    if type(max_requests) is not int or not 1 <= max_requests <= 20:
        raise StudioError("Need a bounded request count")
    total = number(budget.get("max_total_usd"), "video budget", .000001, 100)
    cost = number(budget.get("reserve_per_request_usd"), "request reservation", .000001, total)
    number(budget["max_request_bytes"], "request byte cap", 1, 19000000)
    number(budget["max_output_tokens"], "output token cap", 1, 8192)
    if type(budget["max_request_bytes"]) is not int or type(budget["max_output_tokens"]) is not int:
        raise StudioError("Request byte and token caps must be integers")
    ledger = Path(root) / "artifacts/review-budgets" / budget["authorization_id"]
    ledger.mkdir(parents=True, exist_ok=True)
    lock = ledger / "reservation.lock"
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise StudioError("Budget is owned by another operation or interrupted; reconcile its lock") from None
    try:
        with handle:
            definition = ledger / "budget.json"
            if definition.exists() and read_json(definition) != budget:
                raise StudioError("Budget definition changed; preserve authorization identity")
            if not definition.exists():
                write_json(definition, budget)
            prior = [read_json(p) for p in ledger.glob("request-*.json")]
            if any(p["status"] != "completed" for p in prior):
                raise StudioError("An unresolved or ambiguous request blocks further submissions; reconcile first")
            if len(prior) >= max_requests or (len(prior) + 1) * cost > total + 1e-9:
                raise StudioError("Video request/usage budget exhausted")
            if any(p["run_id"] == run_id for p in prior):
                raise StudioError("This run already has a request; do not resubmit")
            slot = ledger / ("request-" + str(len(prior)+1) + ".json")
            write_json(slot, {"schema_version": 1, "status": "reserved", "run_id": run_id,
                              "clip_sha256": clip_hash, "reserved_usd": cost, "budget_digest": digest(budget)})
            return slot
    finally:
        lock.unlink(missing_ok=True)


def validate_findings(result, expected, criterion_ids, duration):
    if not isinstance(result, dict) or any(result.get(k) != v for k, v in expected.items()):
        raise StudioError("Analyzer response belongs to a different run/candidate/media")
    findings = result.get("findings")
    if not isinstance(findings, list):
        raise StudioError("Analyzer response needs findings")
    for item in findings:
        required(item, ["criterion_id", "status", "interval", "observation", "severity", "next_check"])
        if item["criterion_id"] not in criterion_ids or item["status"] not in VERDICTS:
            raise StudioError("Analyzer returned unknown criterion/verdict")
        interval(item["interval"], duration)
        if not isinstance(item["observation"], str) or not item["observation"].strip():
            raise StudioError("Analyzer needs concrete observations")
    return result


def build_request(root, name, budget, dense=None):
    data = validate_run(root, name, current=False)
    folder = relative(root, name)
    capture = read_json(folder / "capture.json")
    if capture["status"] != "completed":
        raise StudioError("Video analysis needs a complete capture")
    clip = folder / "capture.mp4"
    expected = {"run_id": data["run_id"], "candidate_id": data["candidate"]["candidate_id"], "clip_sha256": sha256(clip)}
    if clip.stat().st_size * 4 / 3 > budget["max_request_bytes"]:
        raise StudioError("Full video exceeds inline request budget; prepare an explicitly approved shorter run")
    inputs = [{"type": "video", "mime_type": "video/mp4", "data": base64.b64encode(clip.read_bytes()).decode(),
               "processing": {"type": "static", "fps": 1}}]
    files = [file_record(root, clip), file_record(root, folder / "capture.json")]
    dense_record = None
    if dense:
        dense_record = read_json(relative(root, dense))
        if dense_record["run_sha256"] != sha256(folder / "run.json") or dense_record["capture_sha256"] != expected["clip_sha256"]:
            raise StudioError("Dense frames belong to different run/media")
        frames = dense_record["frames"]
        if not frames or len(frames) > 180:
            raise StudioError("Dense supplemental frame count outside supported bound")
        files.append(file_record(root, relative(root, dense)))
        for frame in frames:
            image = verify_file(root, frame)
            index = frame["frame_index"]
            if type(index) is not int or not 0 <= index < len(capture["media"]["timestamps_seconds"]) or frame["time_seconds"] != capture["media"]["timestamps_seconds"][index]:
                raise StudioError("Dense timestamp does not match original video PTS")
            inputs += [{"type": "text", "text": f"Supplemental original video frame at {frame['time_seconds']:.9f} seconds (original PTS {frame['original_pts_seconds']:.9f})."},
                       {"type": "image", "mime_type": "image/png", "data": base64.b64encode(image.read_bytes()).decode()}]
            files.append(file_record(root, image))
    schema = {"type": "object", "properties": {**{k: {"type": "string"} for k in expected},
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            **{k: {"type": "string"} for k in ("criterion_id", "status", "observation", "severity", "hypothesis", "next_check")},
            "interval": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
            "required": ["criterion_id", "status", "interval", "observation", "severity", "hypothesis", "next_check"]}}},
        "required": list(expected) + ["findings"]}
    prompt = ("Review the full continuous video and supplemental original frames. Report observed symptoms with exact second intervals, severity, uncertainty and next checks. "
              "Separate hypotheses from observations. Do not infer real game frame time from encoded FPS, sound output from stream presence, or an interaction from input alone. "
              "Status proposals do not establish coverage or acceptance. Do not invent defects on a clean control. Return the bound identity and criterion IDs exactly. "
              + json.dumps({"identity": expected, "criteria": data["card"]["criteria"], "actions": data["card"]["actions"]}))
    inputs.append({"type": "text", "text": prompt})
    payload = {"model": budget["model"], "input": inputs, "store": False,
               "generation_config": {"max_output_tokens": budget["max_output_tokens"], "thinking_level": "low"},
               "response_format": {"type": "text", "mime_type": "application/json", "schema": schema}}
    body = json.dumps(payload, allow_nan=False).encode()
    if len(body) > budget["max_request_bytes"] or len(body) >= 20000000:
        raise StudioError("Video plus dense frames exceeds total inline request byte budget")
    return body, expected, files, dense_record


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise StudioError("Video endpoint redirect refused; request outcome requires reconciliation")


def _submit(body, secret, timeout):
    request = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": secret}, method="POST")
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        raw = response.read(4000001)
        if len(raw) > 4000000:
            raise StudioError("Video response exceeded preservation bound; reconcile request")
        return raw


def analyze(config, root, name, budget, *, dense=None, transport=None):
    folder = relative(root, name)
    if (folder / "analysis.json").exists() or (folder / "analysis-request").exists():
        raise StudioError("Run already submitted/prepared; do not retry an ambiguous operation")
    # All local/media checks and credential presence before reserving or sending.
    body, expected, files, dense_record = build_request(root, name, budget, dense)
    if budget.get("upload_authorized") is not True:
        raise StudioError("Video upload authorization is absent")
    secret = credential(config, "gemini")
    slot = reserve(root, budget, expected["run_id"], expected["clip_sha256"])
    dest = folder / "analysis-request"
    dest.mkdir(exist_ok=False)
    state = read_json(slot)
    state.update(status="submitting", model=budget["model"], endpoint=ENDPOINT, request_sha256=__import__("hashlib").sha256(body).hexdigest(),
                 request_bytes=len(body), created_utc=datetime.now(timezone.utc).isoformat())
    write_json(slot, state)
    write_json(dest / "request.json", state)
    result = {"schema_version": 1, "run_sha256": sha256(folder / "run.json"), "status": "ambiguous",
              "backend": "gemini_interactions", "model": budget["model"], "identity": expected, "analysis_tool": tool_identity(),
              "coverage": {"requested_video_fps": 1, "full_video_submitted": True,
                           "dense_frame_count": len(dense_record["frames"]) if dense_record else 0,
                           "effective_model_gap_seconds": None, "fixture_detection": "not_run"},
              "usage": None, "findings": [], "files": files}
    try:
        raw = (transport or _submit)(body, secret, min(config["timeout"], 180))
        (dest / "response.original.json").write_bytes(raw)
        result["files"].append(file_record(root, dest / "response.original.json"))
        response = json.loads(raw)
        result.update(provider_id=response.get("id"), reported_model=response.get("model"), usage=response.get("usage"))
        if response.get("status") != "completed" or not response.get("id"):
            raise StudioError("Provider result incomplete; reconcile before retry")
        if response.get("model", "").removeprefix("models/") != budget["model"]:
            raise StudioError("Provider returned an unexpected model; preserve response for review")
        text = "".join(p["text"] for step in response.get("steps", []) if step.get("type") == "model_output" for p in step.get("content", []) if p.get("type") == "text")
        data = validate_run(root, name, current=False)
        parsed = validate_findings(json.loads(text), expected, [c["id"] for c in data["card"]["criteria"]], data["card"]["duration_seconds"])
        result.update(status="observations_received", findings=parsed["findings"])
        # Conservatively price every reported token at the higher approved rate.
        usage = response.get("usage") or {}
        rates = budget.get("rates_usd_per_million", {})
        if type(usage.get("total_tokens")) is not int or usage["total_tokens"] < 0 or not rates:
            state["status"] = "usage_unverified"
        else:
            price = max(number(v, "token rate", .000001, 1000) for v in rates.values())
            upper_cost = usage["total_tokens"] * price / 1000000
            state.update(status="completed" if upper_cost <= state["reserved_usd"] else "over_budget", conservative_cost_usd=upper_cost)
        state.update(provider_id=response["id"], usage=usage)
    except (Exception, KeyboardInterrupt):
        state["status"] = "ambiguous"
        result.update(status="ambiguous", findings=[])
        result["reason"] = "Submission or response could not be confirmed; preserve and reconcile, never automatically resubmit"
    finally:
        write_json(slot, state)
        write_json(dest / "outcome.json", state)
        result["files"] += [file_record(root, dest / "request.json"), file_record(root, dest / "outcome.json")]
        result["ok"] = result["status"] == "observations_received" and state["status"] == "completed"
        write_json(folder / "analysis.json", result)
    return result
