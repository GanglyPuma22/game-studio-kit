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
    if path.suffix != ".mp3" or path.exists() or path.is_symlink():
        raise StudioError("Choose a new .mp3 output; preserve existing originals")
    if path.resolve() == Path(record_path).resolve():
        raise StudioError("Intent and original need separate paths")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Persist uncertainty before POST, so a crash or failed final metadata write
    # cannot leave a falsely successful/retryable intent.
    record["status"] = "SUBMISSION_UNKNOWN"
    record = redact(record, secret)
    claim(record_path, record)
    partial = None
    try:
        data, metadata = (transport or Transport(timeout=180)).request(
            "POST", url, headers, wire, binary=True)
        fd, name = tempfile.mkstemp(prefix=path.name+".", suffix=".part", dir=path.parent)
        partial = Path(name)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        validate_download(partial, ".mp3")
        # Exclusive final creation also protects an output created during POST.
        os.link(partial, path)  # atomic, exclusive publication on the same filesystem
        safe_metadata = {k: v for k, v in metadata.items()
                         if k.lower() in {"content-type", "content-length", "request-id", "x-request-id", "character-cost"}}
        record.update(status="ARCHIVED", response_metadata=redact(safe_metadata, secret),
                      output={"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size})
        write_json(record_path, record)
    except Exception:
        # The durable record already says unknown, even if storage itself failed.
        raise StudioError("Hosted audio outcome unknown; preserve record and reconcile in provider history, do not automatically regenerate") from None
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
    return record
