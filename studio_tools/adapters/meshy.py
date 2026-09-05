"""Deliberately narrow Meshy profiles with durable, non-retrying submission."""

import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from ..common import StudioError, digest, read_json, write_json, sha256, safe_id
from ..config import credential
from .http import Transport, ProviderError

BASE = "https://api.meshy.ai"
ENDPOINTS = {
    "image": "/openapi/v1/image-to-3d",
    "preview": "/openapi/v2/text-to-3d",
    "refine": "/openapi/v2/text-to-3d",
    "remesh": "/openapi/v1/remesh",
    "retexture": "/openapi/v1/retexture",
    "rig": "/openapi/v1/rigging",
    "animate": "/openapi/v1/animations",
}
FIELDS = {
    "image": (
        {"image_url"},
        {"image_url", "ai_model", "should_texture", "enable_pbr", "target_formats"},
    ),
    "preview": (
        {"prompt"},
        {"prompt", "ai_model", "mode", "should_remesh", "target_polycount", "topology"},
    ),
    "refine": (
        {"preview_task_id"},
        {
            "preview_task_id",
            "mode",
            "ai_model",
            "enable_pbr",
            "texture_prompt",
            "texture_image_url",
            "target_formats",
        },
    ),
    "remesh": (
        {"input_task_id"},
        {"input_task_id", "target_polycount", "topology", "target_formats"},
    ),
    "retexture": (
        {"input_task_id", "text_style_prompt"},
        {"input_task_id", "text_style_prompt", "enable_pbr", "ai_model"},
    ),
    "rig": ({"input_task_id", "height_meters"}, {"input_task_id", "height_meters"}),
    "animate": ({"rig_task_id", "action_id"}, {"rig_task_id", "action_id"}),
}


def profile(operation, body, eligibility=None):
    if operation not in FIELDS or not isinstance(body, dict):
        raise StudioError("Unknown Meshy operation/profile")
    req, allowed = FIELDS[operation]
    if set(body) - allowed:
        raise StudioError(
            "Unsupported Meshy fields: " + ", ".join(sorted(set(body) - allowed))
        )
    if req - set(body):
        raise StudioError("Missing Meshy fields: " + ", ".join(sorted(req - set(body))))
    result = dict(body)
    for key in ("prompt", "texture_prompt", "text_style_prompt"):
        if key in result and (
            not isinstance(result[key], str) or not 1 <= len(result[key]) <= 800
        ):
            raise StudioError(
                key + " must be a nonempty string of at most 800 characters"
            )
    for key in ("should_texture", "should_remesh", "enable_pbr"):
        if key in result and type(result[key]) is not bool:
            raise StudioError(key + " must be a boolean")
    if result.get("enable_pbr") and result.get("should_texture") is False:
        raise StudioError("PBR requires texture generation")
    if "texture_prompt" in result and "texture_image_url" in result:
        raise StudioError("Choose one texture guidance input")
    for key in ("image_url", "texture_image_url"):
        if key in result and (
            not isinstance(result[key], str)
            or not result[key].startswith(
                ("https://", "data:image/png;base64,", "data:image/jpeg;base64,")
            )
        ):
            raise StudioError(
                "Reference must be an HTTPS image URL or supported image data URI"
            )
    for key in req:
        if result[key] is None or result[key] == "":
            raise StudioError("Empty Meshy field: " + key)
    for key, value in result.items():
        if key.endswith("_task_id"):
            safe_id(value)
    if operation in {"image", "preview", "retexture"}:
        result.setdefault("ai_model", "meshy-6")
    if "ai_model" in result and result["ai_model"] not in {
        "meshy-5",
        "meshy-6",
        "meshy-7",
    }:
        raise StudioError(
            "Choose an explicit supported Meshy model; latest is not a reproducible profile"
        )
    if operation in {"preview", "refine"}:
        if result.get("mode", operation) != operation:
            raise StudioError("Mode disagrees with operation")
        result["mode"] = operation
    if "target_formats" in result and result["target_formats"] != ["glb"]:
        raise StudioError(
            "This profile exports GLB only; extend/test the profile for other formats"
        )
    if operation in {"image", "refine", "remesh"}:
        result.setdefault("target_formats", ["glb"])
    if "target_polycount" in result and (
        type(result["target_polycount"]) is not int
        or not 100 <= result["target_polycount"] <= 300000
    ):
        raise StudioError("target_polycount must be 100–300000")
    if result.get("topology", "triangle") not in {"triangle", "quad"}:
        raise StudioError("Invalid topology")
    if "image_url" in result and not str(result["image_url"]).startswith(
        ("https://", "data:image/png;base64,", "data:image/jpeg;base64,")
    ):
        raise StudioError(
            "Reference must be an HTTPS image URL or supported image data URI"
        )
    if operation == "rig":
        eligibility = eligibility or {}
        if (
            eligibility.get("body_type") != "humanoid_biped"
            or eligibility.get("textured") is not True
            or eligibility.get("checked") is not True
            or eligibility.get("limbs_clear") is not True
            or type(eligibility.get("face_count")) is not int
            or not 0 < eligibility["face_count"] <= 300000
        ):
            raise StudioError(
                "Rig eligibility not met: route nonhumanoid or unchecked assets to studio-animation before any paid call"
            )
        if (
            not isinstance(result["height_meters"], (int, float))
            or not 0 < result["height_meters"] <= 100
        ):
            raise StudioError("height_meters must be positive and at most 100")
    if operation == "animate" and (
        type(result["action_id"]) is not int or result["action_id"] < 0
    ):
        raise StudioError(
            "action_id must be an integer from the current animation library"
        )
    return result


def claim(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as f:
            json.dump(record, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
    except FileExistsError:
        raise StudioError(
            "Task record already exists; observe/resume it. Never resubmit an ambiguous paid request"
        ) from None


def budget_check(budget):
    if (
        not isinstance(budget, dict)
        or budget.get("authorized") is not True
        or not budget.get("work_card")
        or not budget.get("rate_checked_at")
        or not budget.get("units")
    ):
        raise StudioError(
            "Paid submission needs the authorized work card, units, current rate check and budget"
        )
    maximum = budget.get("maximum")
    estimated = budget.get("estimated")
    if (
        type(maximum) not in (int, float)
        or type(estimated) not in (int, float)
        or not math.isfinite(maximum)
        or not math.isfinite(estimated)
        or not 0 < estimated <= maximum
    ):
        raise StudioError(
            "Estimated request cost must be positive and within the authorized budget"
        )


def submit(
    config, operation, body, record_path, budget, eligibility=None, transport=None
):
    payload = profile(operation, body, eligibility)
    budget_check(budget)
    key = credential(config, "meshy")
    record = {
        "schema_version": 1,
        "provider": "meshy",
        "operation": operation,
        "endpoint": ENDPOINTS[operation],
        "request": payload,
        "request_digest": digest(payload),
        "budget": budget,
        "eligibility": eligibility,
        "status": "SUBMITTING",
        "task_id": None,
        "outputs": [],
    }
    claim(
        record_path, record
    )  # durable before network, including crashes before/after the POST
    try:
        response = (transport or Transport()).request(
            "POST",
            BASE + ENDPOINTS[operation],
            {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            payload,
        )
        task_id = safe_id(response["result"])
    except Exception:
        record["status"] = "SUBMISSION_UNKNOWN"
        write_json(record_path, record)
        raise StudioError(
            "Submission outcome unknown; reconcile this record with the provider dashboard/task list. Do not submit again"
        ) from None
    record.update(task_id=task_id, status="PENDING")
    write_json(record_path, record)  # persist identity before any observation
    return record


def attach_task(record_path, task_id):
    record = read_json(record_path)
    if record.get("task_id") or record.get("status") not in {
        "SUBMITTING",
        "SUBMISSION_UNKNOWN",
    }:
        raise StudioError(
            "Only an ambiguous record without a task ID can be reconciled"
        )
    record.update(task_id=safe_id(task_id), status="PENDING", reconciled=True)
    write_json(record_path, record)
    return record


def observe(config, record_path, transport=None):
    record = read_json(record_path)
    if not record.get("task_id"):
        raise StudioError(
            "Task identity unknown; reconcile before observing, never automatically resubmit"
        )
    task_id = safe_id(record["task_id"])
    endpoint = ENDPOINTS.get(record.get("operation"))
    if endpoint != record.get("endpoint"):
        raise StudioError("Task endpoint does not match its supported operation")
    try:
        response = (transport or Transport()).request(
            "GET",
            BASE + endpoint + "/" + task_id,
            {"Authorization": "Bearer " + credential(config, "meshy")},
        )
    except ProviderError as exc:
        if exc.status in {404, 410}:
            record["status"] = "UNAVAILABLE"
            write_json(record_path, record)
        raise
    if response.get("id") != task_id:
        raise StudioError("Provider returned a different task identity")
    status = response.get("status")
    if status not in {
        "PENDING",
        "IN_PROGRESS",
        "SUCCEEDED",
        "FAILED",
        "CANCELED",
        "EXPIRED",
    }:
        raise StudioError("Unknown provider status; inspect task without resubmitting")
    # Providers sometimes echo request/auth context in diagnostic strings.
    key = credential(config, "meshy")

    def redact(value):
        if isinstance(value, str):
            return value.replace(key, "[REDACTED]")
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(v) for v in value]
        return value

    record.update(status=status, response=redact(response))
    write_json(record_path, record)
    return record


def poll(config, record_path, attempts=1, interval=5, transport=None):
    if not 1 <= attempts <= 120 or not 0 <= interval <= 30:
        raise StudioError("Polling bounds: 1–120 attempts, 0–30 seconds interval")
    for i in range(attempts):
        record = observe(config, record_path, transport)
        if record["status"] not in {"PENDING", "IN_PROGRESS"} or i + 1 == attempts:
            return record
        time.sleep(interval)


def output_urls(response):
    """Collect GLBs, textures and review media, including nested rig/animation result shapes."""
    urls = []

    def walk(value, trail):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, trail + [k])
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, trail + [str(i)])
        elif isinstance(value, str) and value.startswith("https://"):
            suffix = Path(urlsplit(value).path).suffix.lower()
            if suffix in {".glb", ".png", ".jpg", ".jpeg", ".mp4", ".fbx"}:
                stem = re.sub(r"[^A-Za-z0-9_-]", "_", "_".join(trail))[:150]
                urls.append((stem + suffix, value))

    for key in (
        "model_urls",
        "texture_urls",
        "thumbnail_url",
        "thumbnail_urls",
        "video_url",
        "result",
        "animation_glb_url",
        "animation_fbx_url",
    ):
        if key in response:
            walk(response[key], [key])
    return urls


def archive(record_path, directory, transport=None):
    record = read_json(record_path)
    if record.get("status") != "SUCCEEDED":
        raise StudioError(
            "Only successful tasks can be archived; failure/pending is not an asset"
        )
    urls = output_urls(record.get("response", {}))
    if not any(name.endswith(".glb") for name, url in urls):
        raise StudioError("Successful task has no GLB output; inspect response schema")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    previous = {x["name"]: x for x in record.get("outputs", [])}
    for name, url in urls:
        path = root / name
        if (
            name in previous
            and path.is_file()
            and sha256(path) == previous[name]["sha256"]
        ):
            continue
        (transport or Transport()).download(url, path)
        previous[name] = {
            "name": name,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        record["outputs"] = list(previous.values())
        record["archive_complete"] = False
        write_json(record_path, record)  # restart preserves each completed file
    record["archive_complete"] = True
    write_json(record_path, record)
    return record
