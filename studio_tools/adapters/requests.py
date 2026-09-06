"""Durable provider intents, authorization and original-file archives."""
import json
import math
import os
from pathlib import Path
import tempfile
from ..common import StudioError, write_json, sha256
from .http import Transport, validate_download

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



def redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, dict):
        return {redact(k, secret): redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    return value


def archive_audio(record_path, output, record, url, headers, wire, secret, transport=None):
    path = Path(output)
    record_path = Path(record_path)
    if path.suffix != ".mp3" or path.exists() or path.is_symlink():
        raise StudioError("Choose a new .mp3 output; preserve existing originals")
    if path.resolve() == Path(record_path).resolve():
        raise StudioError("Intent and original need separate paths")
    path.parent.mkdir(parents=True, exist_ok=True)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve recovery storage before any paid submission. Keep it beside the
    # intent so even an unchanged SUBMISSION_UNKNOWN record locates the bytes.
    try:
        fd, name = tempfile.mkstemp(prefix="received-", suffix=".mp3.part", dir=record_path.parent)
    except OSError:
        raise StudioError("Cannot reserve audio recovery storage; no request submitted") from None
    recovery = Path(name)
    # Persist uncertainty before POST, so a crash or failed final metadata write
    # cannot leave a falsely successful/retryable intent.
    record["status"] = "SUBMISSION_UNKNOWN"
    record["recovery"] = {"path": recovery.name, "state": "reserved"}
    record = redact(record, secret)
    try:
        claim(record_path, record)
    except Exception:
        os.close(fd)
        recovery.unlink(missing_ok=True)
        raise
    received = False
    saved = False
    try:
        with os.fdopen(fd, "wb") as f:
            data, metadata = (transport or Transport(timeout=180)).request(
                "POST", url, headers, wire, binary=True)
            received = True
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        record["recovery"].update(state="received", sha256=sha256(recovery),
                                  bytes=recovery.stat().st_size, validated=False)
        saved = True
        safe_metadata = {k: v for k, v in metadata.items()
                         if k.lower() in {"content-type", "content-length", "request-id", "x-request-id", "character-cost"}}
        record["response_metadata"] = redact(safe_metadata, secret)
        validate_download(recovery, ".mp3")
        record["recovery"]["validated"] = True
        # Exclusive publication protects an output created during POST. If hard
        # links are unsupported (including cross-device paths), keep recovery.
        os.link(recovery, path)
        record.update(status="ARCHIVED",
                      output={"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size})
        write_json(record_path, record)
    except Exception:
        if saved:
            record["status"] = "RECEIVED_UNARCHIVED"
            try:
                write_json(record_path, record)
            except Exception:
                # The pre-POST intent still identifies recovery, but storage
                # failure can prevent recording its completed hash/state.
                raise StudioError("Hosted audio archive outcome unknown; preserve the intent and its recovery path, metadata durability unconfirmed; do not automatically regenerate") from None
            raise StudioError("Hosted audio received; preserve the intent and recorded recovery bytes for manual reconciliation; do not automatically regenerate") from None
        if received:
            raise StudioError("Hosted audio received but recovery durability unconfirmed; preserve the intent and any recovery bytes, reconcile in provider history; do not automatically regenerate") from None
        raise StudioError("Hosted audio outcome unknown; preserve record and reconcile in provider history, do not automatically regenerate") from None
    return record
