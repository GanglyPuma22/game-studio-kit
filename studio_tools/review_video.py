"""One bounded Gemini Interactions video request, with full context and dense frames.

Official API/schema references and current limits are recorded in validation-loop.md.
No installation, implicit upload, retry, remote URL input, or perception self-attestation.
"""
import base64
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.request
from .common import StudioError, digest, file_record, read_json, relative, safe_id, sha256, write_json
from .config import credential
from .records import VERDICTS, required, verify_file
from .validation import interval, number, tool_identity, validate_run

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"


def analysis_profile(budget):
    return {"version": 2, "model": budget["model"], "video_fps": 1, "image_resolution": "high",
            "thinking_level": "low", "max_output_tokens": budget["max_output_tokens"], "store": False}


def cost_bound(budget):
    # Deliberately use the whole documented supported-model ceilings: compressed
    # bytes and approximate media tokenization are not a defensible dollar cap.
    if budget.get("model") != "gemini-3.7-flash" or budget.get("rates_model") != budget["model"] or budget.get("rates_profile") != "standard-all-context":
        raise StudioError("Current cost profile requires verified gemini-3.7-flash standard all-context rates")
    try:
        checked = datetime.fromisoformat(budget["rate_verified_utc"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - checked).total_seconds()
        if not -300 <= age <= 7 * 86400:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise StudioError("Rate verification must be timezone-aware and within seven days") from None
    rates = budget.get("rates_usd_per_million", {})
    if not isinstance(rates, dict):
        raise StudioError("Verified rates must be an input/output/thought object")
    reservation = number(budget.get("reserve_per_request_usd"), "request reservation", .000001, 100)
    multiplier = 2 if datetime.now(timezone.utc).year >= 2027 else 1
    for key, floor in (("input", .75 * multiplier), ("output", 3.75 * multiplier), ("thought", 3.75 * multiplier)):
        number(rates.get(key), "verified " + key + " rate", floor, 1000)
    upper = (1048576 * rates["input"] + 65536 * rates["output"] + 65536 * rates["thought"]) / 1000000
    if upper > reservation:
        raise StudioError("Request reservation is below conservative input/output/thought cost bound")
    return {"input_tokens_upper": 1048576, "output_tokens_upper": 65536, "additional_thought_tokens_upper": 65536,
            "estimated_upper_bound_usd": upper, "method": "documented model ceilings; separate conservative thought allowance"}


def reserve(root, budget, run_id, clip_hash):
    if budget.get("upload_authorized") is not True or clip_hash not in budget.get("approved_media_sha256", []):
        raise StudioError("Video upload needs explicit approval for this exact media hash")
    required(budget, ["authorization_id", "model", "rate_verified_utc", "max_request_bytes", "max_output_tokens"])
    bound = cost_bound(budget)
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
                              "clip_sha256": clip_hash, "reserved_usd": cost, "budget_digest": digest(budget), "cost_bound": bound})
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



def request_questions(card, expected):
    schema = {"type": "object", "properties": {**{k: {"type": "string"} for k in expected},
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            **{k: {"type": "string"} for k in ("criterion_id", "status", "category", "observation", "severity", "hypothesis", "next_check")},
            "interval": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "action": {"type": "object", "properties": {"input_seconds": {"type": "number"}, "outcome_seconds": {"type": ["number", "null"]},
                "before_state": {"type": "string"}, "after_state": {"type": "string"}, "outcome_window": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}},
                "required": ["input_seconds", "outcome_seconds", "before_state", "after_state", "outcome_window"]}},
            "required": ["criterion_id", "status", "category", "interval", "observation", "severity", "hypothesis", "next_check"]}}},
        "required": list(expected) + ["findings"]}
    prompt = ("Review the full continuous video and supplemental original frames. Report observed symptoms with exact second intervals, severity, uncertainty and next checks. "
              "For interaction findings include the observed input, outcome window, timestamp/state transition (null outcome if absent). Separate hypotheses from observations. Do not infer real game frame time from encoded FPS, sound output from stream presence, or an interaction from input alone. "
              "Status proposals do not establish coverage or acceptance. Do not invent defects on a clean control. Return the bound identity and criterion IDs exactly. "
              + json.dumps({"identity": expected, "criteria": card["criteria"], "actions": card["actions"]}))
    return schema, prompt

def build_request(root, name, budget, dense=None, *, config=None):
    data = validate_run(root, name, current=False, config=config)
    if "prompt_contract_id" in data["card"]:
        from .review_records import validate_neutral_run
        validate_neutral_run(data)
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
        # Regenerate the complete declared dense selection from approved video.
        # A matching sidecar's own hashes cannot authorize unrelated images.
        from .config import load, require_executable
        from .processes import run
        start, end = interval(dense_record["interval"], capture["media"]["duration_seconds"])
        expected_indexes = [i for i, t in enumerate(capture["media"]["timestamps_seconds"]) if start <= t <= end]
        if [f.get("frame_index") for f in frames] != expected_indexes:
            raise StudioError("Dense selection does not match the approved clip interval")
        with tempfile.TemporaryDirectory(prefix="studio-verify-dense-") as temporary:
            run([require_executable(config or load(), "ffmpeg"), "-v", "error", "-n", "-i", str(clip), "-vf",
                 f"select=between(n\\,{expected_indexes[0]}\\,{expected_indexes[-1]})", "-vsync", "0", str(Path(temporary) / "%05d.png")], timeout=120)
            regenerated = sorted(Path(temporary).glob("*.png"))
            if len(regenerated) != len(frames) or any(sha256(p) != f["sha256"] for p, f in zip(regenerated, frames)):
                raise StudioError("Supplemental image is not derived from the approved clip")
        for frame in frames:
            image = verify_file(root, frame)
            index = frame["frame_index"]
            if type(index) is not int or not 0 <= index < len(capture["media"]["timestamps_seconds"]) or frame["time_seconds"] != capture["media"]["timestamps_seconds"][index] or frame["original_pts_seconds"] != capture["media"]["original_pts_seconds"][index]:
                raise StudioError("Dense timestamp does not match original video PTS")
            inputs += [{"type": "text", "text": f"Supplemental original video frame at {frame['time_seconds']:.9f} seconds (original PTS {frame['original_pts_seconds']:.9f})."},
                       {"type": "image", "mime_type": "image/png", "resolution": "high", "data": base64.b64encode(image.read_bytes()).decode()}]
            files.append(file_record(root, image))
    schema, prompt = request_questions(data["card"], expected)
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
        return raw


def validate_analysis(root, name, run, analysis):
    """Replay retained inputs; analysis.json is derived, never its own authority.

    Invalid/ambiguous outcomes remain inspectable but cannot be edited into
    observations. Successful legacy receipts without the replay inputs require
    review under their original source; this helper does not upgrade evidence.
    """
    try:
        _replay_analysis(root, relative(root, name), run, analysis)
    except StudioError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise StudioError("Analysis replay needs intact request/response/outcome evidence") from exc



def validate_neutral_request(run, payload, expected, frames):
    from .review_records import validate_neutral_run
    validate_neutral_run(run)
    schema, prompt = request_questions(run["card"], expected)
    parts = payload["input"]
    types = ["video"] + [kind for _ in frames for kind in ("text", "image")] + ["text"]
    texts = [{"type": "text", "text": f"Supplemental original video frame at {frame['time_seconds']:.9f} seconds (original PTS {frame['original_pts_seconds']:.9f})."} for frame in frames]
    texts.append({"type": "text", "text": prompt})
    if (set(payload) != {"model", "input", "store", "generation_config", "response_format"}
        or [part.get("type") for part in parts] != types
        or [part for part in parts if part["type"] == "text"] != texts
        or payload.get("response_format") != {"type": "text", "mime_type": "application/json", "schema": schema}):
        raise StudioError("Qualification request text/layout differs from frozen neutral contract")
    for part in parts:
        if part["type"] in {"video", "image"}:
            video = part["type"] == "video"
            keys = {"type", "mime_type", "data", "processing" if video else "resolution"}
            if set(part) != keys or part["mime_type"] != ("video/mp4" if video else "image/png"):
                raise StudioError("Qualification media input differs from neutral contract")

def _replay_analysis(root, folder, run, analysis):
    dest = folder / "analysis-request"
    request = read_json(dest / "request.json")
    outcome = read_json(dest / "outcome.json")
    recorded_status = outcome.get("status")
    expected_status = {"completed": "observations_received", "over_budget": "observations_received",
        "usage_unverified": "received_invalid", "received_invalid": "received_invalid", "rejected": "rejected",
        "ambiguous": "ambiguous", "submitting": "ambiguous"}.get(recorded_status)
    if expected_status is None or analysis.get("status") != expected_status or analysis.get("ok") is not (recorded_status == "completed"):
        raise StudioError("Analysis status/acceptance contradicts retained outcome")
    # No pass consumes fields from invalid or ambiguous observations. Keep those
    # original receipts inspectable, including their bounded error response.
    if expected_status != "observations_received":
        return
    required(request, ["replay_version", "execution_scope", "analysis_tool", "budget", "ledger_path"])
    if request["replay_version"] != 1 or request["execution_scope"] not in {"provider", "test"}:
        raise StudioError("Analysis request has no known execution scope/replay contract")
    if any(outcome.get(k) != value for k, value in request.items() if k != "status"):
        raise StudioError("Analysis outcome changed original request identity")
    if read_json(relative(root, request["ledger_path"])) != outcome:
        raise StudioError("Analysis outcome differs from retained budget ledger")
    payload_path = dest / "request.original.json"
    if sha256(payload_path) != request["request_sha256"] or payload_path.stat().st_size != request["request_bytes"]:
        raise StudioError("Analysis request bytes differ from recorded submission")
    retained = analysis.get("files", [])
    for path in (dest / "request.json", dest / "outcome.json", payload_path, dest / "response.original.json"):
        if file_record(root, path) not in retained:
            raise StudioError("Analysis must retain the original request/response/outcome references")
    budget = read_json(verify_file(root, request["budget"]))
    if digest(budget) != request["budget_digest"] or request["endpoint"] != ENDPOINT:
        raise StudioError("Analysis budget/endpoint identity differs from submission")
    payload = read_json(payload_path)
    expected = {"run_id": run["run_id"], "candidate_id": run["candidate"]["candidate_id"], "clip_sha256": sha256(folder / "capture.mp4")}
    if request["run_id"] != expected["run_id"] or request["clip_sha256"] != expected["clip_sha256"] or payload["model"] != budget["model"]:
        raise StudioError("Analysis request belongs to another run/media/model")
    profile = analysis_profile(budget)
    if payload.get("store") is not False or payload.get("generation_config") != {"max_output_tokens": profile["max_output_tokens"], "thinking_level": "low"}:
        raise StudioError("Analysis request configuration differs from its profile")
    videos = [part for part in payload["input"] if part["type"] == "video"]
    images = [part for part in payload["input"] if part["type"] == "image"]
    if (len(videos) != 1 or videos[0].get("processing") != {"type": "static", "fps": 1}
        or hashlib.sha256(base64.b64decode(videos[0]["data"], validate=True)).hexdigest() != expected["clip_sha256"]):
        raise StudioError("Analysis full-video input differs from the captured clip")
    dense = read_json(verify_file(root, request["dense"])) if request.get("dense") else None
    frames = dense["frames"] if dense else []
    if "prompt_contract_id" in run["card"]:
        validate_neutral_request(run, payload, expected, frames)
    if len(images) != len(frames):
        raise StudioError("Analysis dense inputs differ from retained coverage")
    gap = None
    if dense:
        capture = read_json(folder / "capture.json")
        start, end = interval(dense["interval"], run["card"]["duration_seconds"])
        times = capture["media"]["timestamps_seconds"]
        indexes = [i for i, timestamp in enumerate(times) if start <= timestamp <= end]
        if (dense["run_sha256"] != sha256(folder / "run.json") or dense["capture_sha256"] != expected["clip_sha256"]
            or [frame["frame_index"] for frame in frames] != indexes):
            raise StudioError("Analysis dense selection differs from original run/PTS")
        for image, frame in zip(images, frames):
            verify_file(root, frame)
            if image.get("resolution") != "high" or hashlib.sha256(base64.b64decode(image["data"], validate=True)).hexdigest() != frame["sha256"] or frame["time_seconds"] != times[frame["frame_index"]] or frame["original_pts_seconds"] != capture["media"]["original_pts_seconds"][frame["frame_index"]]:
                raise StudioError("Analysis dense image/timestamp differs from original submission")
        selected = [times[i] for i in indexes]
        gap = max(b-a for a, b in zip([start]+selected, selected+[end]))
    coverage = {"requested_video_fps": 1, "full_video_submitted": True, "dense_frame_count": len(frames),
        "effective_model_gap_seconds": None, "fixture_detection": "not_run", "dense_interval": dense["interval"] if dense else None,
        "dense_max_gap_seconds": gap}
    response = read_json(dest / "response.original.json")
    if response.get("status") != "completed" or not response.get("id") or response.get("model", "").removeprefix("models/") != budget["model"] or outcome.get("response_truncated"):
        raise StudioError("Analysis original response was not a completed matching result")
    text = "".join(part["text"] for step in response.get("steps", []) if step.get("type") == "model_output" for part in step.get("content", []) if part.get("type") == "text")
    parsed = validate_findings(json.loads(text), expected, [c["id"] for c in run["card"]["criteria"]], run["card"]["duration_seconds"])
    usage = response.get("usage") or {}
    if type(usage.get("total_tokens")) is not int or usage["total_tokens"] < 0:
        raise StudioError("Analysis original response has invalid usage")
    cost = usage["total_tokens"] * max(number(rate, "recorded token rate", .000001, 1000) for rate in budget["rates_usd_per_million"].values()) / 1000000
    if (outcome.get("usage") != usage or outcome.get("provider_id") != response["id"] or outcome.get("conservative_cost_usd") != cost
        or recorded_status != ("completed" if cost <= request["reserved_usd"] else "over_budget")):
        raise StudioError("Analysis returned usage/cost differs from retained outcome")
    derived = {"identity": expected, "model": budget["model"], "backend": "gemini_interactions", "profile": profile,
        "analysis_tool": request["analysis_tool"], "execution_scope": request["execution_scope"], "coverage": coverage,
        "usage": usage, "provider_id": response["id"], "reported_model": response["model"], "findings": parsed["findings"]}
    if any(analysis.get(k) != value for k, value in derived.items()):
        raise StudioError("Analysis fields differ from replayed request/response evidence")


def analyze(config, root, name, budget, *, dense=None, transport=None):
    folder = relative(root, name)
    if (folder / "analysis.json").exists() or (folder / "analysis-request").exists():
        raise StudioError("Run already submitted/prepared; do not retry an ambiguous operation")
    # All local/media checks and credential presence before reserving or sending.
    cost_bound(budget)
    body, expected, files, dense_record = build_request(root, name, budget, dense, config=config)
    if budget.get("upload_authorized") is not True:
        raise StudioError("Video upload authorization is absent")
    secret = "offline-test-transport" if transport is not None else credential(config, "gemini")
    slot = reserve(root, budget, expected["run_id"], expected["clip_sha256"])
    dest = folder / "analysis-request"
    dest.mkdir(exist_ok=False)
    state = read_json(slot)
    execution_scope = "test" if transport is not None else "provider"
    analysis_tool = tool_identity()
    state.update(replay_version=1, execution_scope=execution_scope, analysis_tool=analysis_tool, budget=file_record(root, slot.parent / "budget.json"),
                 ledger_path=slot.relative_to(Path(root)).as_posix(), dense=file_record(root, relative(root, dense)) if dense else None, status="submitting", model=budget["model"], endpoint=ENDPOINT, request_sha256=__import__("hashlib").sha256(body).hexdigest(),
                 request_bytes=len(body), created_utc=datetime.now(timezone.utc).isoformat())
    write_json(slot, state)
    write_json(dest / "request.json", state)
    (dest / "request.original.json").write_bytes(body)
    files.append(file_record(root, dest / "request.original.json"))
    result = {"schema_version": 1, "run_sha256": sha256(folder / "run.json"), "status": "ambiguous",
              "execution_scope": execution_scope, "backend": "gemini_interactions", "model": budget["model"], "identity": expected, "analysis_tool": analysis_tool, "profile": analysis_profile(budget),
              "coverage": {"requested_video_fps": 1, "full_video_submitted": True,
                           "dense_frame_count": len(dense_record["frames"]) if dense_record else 0,
                           "effective_model_gap_seconds": None, "fixture_detection": "not_run", "dense_interval": dense_record["interval"] if dense_record else None, "dense_max_gap_seconds": dense_record["max_gap_seconds"] if dense_record else None},
              "usage": None, "findings": [], "files": files}
    received = False
    try:
        raw = (transport or _submit)(body, secret, min(config["timeout"], 180))
        received = True
        oversized = len(raw) > 4000000
        raw = raw[:4000000]
        result["response_truncated"] = oversized
        state["response_truncated"] = oversized
        (dest / "response.original.json").write_bytes(raw)
        result["files"].append(file_record(root, dest / "response.original.json"))
        if oversized:
            raise StudioError("Received response exceeded preservation limit")
        response = json.loads(raw)
        result.update(provider_id=response.get("id"), reported_model=response.get("model"), usage=response.get("usage"))
        if response.get("status") != "completed" or not response.get("id"):
            raise StudioError("Provider result incomplete; reconcile before retry")
        if response.get("model", "").removeprefix("models/") != budget["model"]:
            raise StudioError("Provider returned an unexpected model; preserve response for review")
        text = "".join(p["text"] for step in response.get("steps", []) if step.get("type") == "model_output" for p in step.get("content", []) if p.get("type") == "text")
        data = validate_run(root, name, current=False, config=config)
        parsed = validate_findings(json.loads(text), expected, [c["id"] for c in data["card"]["criteria"]], data["card"]["duration_seconds"])
        result.update(status="observations_received", findings=parsed["findings"])
        # Conservatively price every reported token at the higher approved rate.
        usage = response.get("usage") or {}
        rates = budget.get("rates_usd_per_million", {})
        if type(usage.get("total_tokens")) is not int or usage["total_tokens"] < 0 or not rates:
            state["status"] = "usage_unverified"
            result.update(status="received_invalid", reason="Received response lacks valid usage; reconcile before further submissions")
        else:
            price = max(number(v, "token rate", .000001, 1000) for v in rates.values())
            upper_cost = usage["total_tokens"] * price / 1000000
            state.update(status="completed" if upper_cost <= state["reserved_usd"] else "over_budget", conservative_cost_usd=upper_cost)
        state.update(provider_id=response["id"], usage=usage)
    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read(4000001)
            truncated = len(error_body) > 4000000
        except (OSError, ValueError):
            error_body, truncated = b"", False
        exc.close()
        error_body = error_body[:4000000].replace(secret.encode(), b"[redacted]")
        (dest / "response.error.original").write_bytes(error_body)
        result["files"].append(file_record(root, dest / "response.error.original"))
        state.update(status="rejected", http_status=exc.code, response_truncated=truncated,
                     response_headers={k: str(v).replace(secret, "[redacted]") for k, v in (exc.headers or {}).items() if k.lower() in {"content-type", "retry-after", "x-request-id"}})
        result.update(status="rejected", http_status=exc.code, reason="Provider returned HTTP rejection; bytes retained, no retry")
    except (Exception, KeyboardInterrupt):
        status = "received_invalid" if received else "ambiguous"
        state.update(status=status, provider_id=result.get("provider_id"), usage=result.get("usage"))
        result.update(status=status, findings=[])
        result["reason"] = "Received result is invalid; inspect original response and usage" if received else "Transport outcome unknown; reconcile account evidence before any new authorization"
        result["reconciliation"] = "store=false prevents relying on later retrieval; preserve local bytes/account evidence, no automatic retry or recapture"
    finally:
        write_json(slot, state)
        write_json(dest / "outcome.json", state)
        result["files"] += [file_record(root, dest / "request.json"), file_record(root, dest / "outcome.json")]
        result["ok"] = result["status"] == "observations_received" and state["status"] == "completed"
        write_json(folder / "analysis.json", result)
    return result
