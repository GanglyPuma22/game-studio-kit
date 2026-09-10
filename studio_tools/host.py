"""Host readiness for an unattended window: update pause, pending reboot, active hours, power.

Preflight is read-only Python. Apply runs the packaged PowerShell script, which
supports -WhatIf and requires elevation; it changes only Windows Update pause,
active hours and the power scheme.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from .common import StudioError, outside_package, write_json

HOST_ROOT = Path(__file__).resolve().parents[1] / "skills" / "studio-review" / "scripts" / "host"
IS_WINDOWS = os.name == "nt"
SCRIPT = "Prepare-OvernightHost.ps1"
UX_KEY = r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
PENDING_KEYS = {
    "cbs": r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
    "wu": r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
}
HIGH_PERFORMANCE_GUIDS = {"8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "e9a42b02-d5df-448d-aa00-03f14749eb61"}
LIMITS = [
    "registry state is read at one instant; a later Settings change is not observed",
    "tool entitlement and licence state are not checked here; run doctor separately",
    "apply changes Windows Update pause, active hours and the power scheme only",
]


def parse_utc(text, what):
    if not isinstance(text, str) or not text.strip():
        raise StudioError(f"{what} must be an ISO 8601 timestamp with a UTC offset")
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise StudioError(f"{what} must be an ISO 8601 timestamp with a UTC offset") from None
    if value.tzinfo is None:
        raise StudioError(f"{what} needs an explicit UTC offset")
    return value.astimezone(timezone.utc)


def _registry_reader():
    import winreg

    def value(key, name):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                return winreg.QueryValueEx(handle, name)[0]
        except OSError:
            return None

    def exists(key):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key):
                return True
        except OSError:
            return False

    from .cleanroom import read_battery, read_power_scheme

    return {
        "host_kind": "windows",
        "windows_update": {
            "pause_start": value(UX_KEY, "PauseUpdatesStartTime"),
            "pause_expiry": value(UX_KEY, "PauseUpdatesExpiryTime"),
            "feature_end": value(UX_KEY, "PauseFeatureUpdatesEndTime"),
            "quality_end": value(UX_KEY, "PauseQualityUpdatesEndTime"),
        },
        "active_hours": {"start": value(UX_KEY, "ActiveHoursStart"), "end": value(UX_KEY, "ActiveHoursEnd")},
        "pending_reboot": {
            "cbs": exists(PENDING_KEYS["cbs"]),
            "wu": exists(PENDING_KEYS["wu"]),
            "pending_file_rename": value(r"SYSTEM\CurrentControlSet\Control\Session Manager", "PendingFileRenameOperations") is not None,
        },
        "power_scheme": read_power_scheme(),
        "battery": read_battery(),
    }


def read_state(reader=None):
    if reader is None:
        if not IS_WINDOWS:
            return {"host_kind": "unsupported", "platform": os.name}
        reader = _registry_reader
    state = reader()
    if not isinstance(state, dict) or "host_kind" not in state:
        raise StudioError("Host state reader must return an object with host_kind")
    return state


def _parse_registry_time(text):
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return parse_utc(text, "Pause time")
    except StudioError:
        return None


def hours_covered(start, end, hours):
    """Active hours wrap at midnight; each window hour must fall inside [start, end)."""
    if start is None or end is None or not 0 <= start <= 23 or not 0 <= end <= 23 or start == end:
        return False
    active = set()
    hour = start
    while hour != end:
        active.add(hour)
        hour = (hour + 1) % 24
    return all(h in active for h in hours)


def evaluate(state, window=None, *, now=None, tz=None):
    """Pure readiness decision; window is (start_utc, end_utc) datetimes or None."""
    now = now or datetime.now(timezone.utc)
    if state.get("host_kind") != "windows":
        return {"ready": False, "reasons": ["host kind is not Windows; preflight is informational only"], "checks": {}}
    reasons = []
    checks = {}
    pending = state.get("pending_reboot", {})
    checks["pending_reboot"] = {k: bool(pending.get(k)) for k in ("cbs", "wu", "pending_file_rename")}
    if any(checks["pending_reboot"].values()):
        reasons.append("a reboot is pending; restart before the window")
    expiry = _parse_registry_time(state.get("windows_update", {}).get("pause_expiry"))
    checks["windows_update"] = {"paused": bool(expiry and expiry > now), "pause_expiry": expiry.isoformat() if expiry else None}
    if expiry is None or expiry <= now:
        reasons.append("Windows Update is not paused")
    elif window is not None and expiry < window[1]:
        reasons.append("Windows Update pause expires before the window ends")
    hours = state.get("active_hours", {})
    start, end = hours.get("start"), hours.get("end")
    checks["active_hours"] = {"start": start, "end": end}
    if window is not None:
        span = window[1] - window[0]
        sane = timedelta(0) < span <= timedelta(hours=18)
        if not sane:
            reasons.append("window must be between 1 minute and 18 hours long")
        # Step the UTC timeline itself and read the local hour fresh at each
        # step; adding timedeltas to an already-localized cursor instead would
        # silently skip or repeat an hour across a DST change. The step is one
        # minute, not one hour: an hourly step from 10:59 lands past 11:01 and
        # would miss local hour 11 entirely. The last instant before the end is
        # added explicitly so a window ending mid-hour still counts that hour,
        # while the exclusive end instant itself is never counted.
        needed = set()
        if sane:
            cursor = window[0]
            while cursor < window[1]:
                needed.add(cursor.astimezone(tz).hour)
                cursor += timedelta(minutes=1)
            needed.add((window[1] - timedelta(microseconds=1)).astimezone(tz).hour)
        checks["active_hours"]["window_hours_local"] = sorted(needed)
        checks["active_hours"]["covers_window"] = bool(needed) and hours_covered(start, end, needed)
        if not checks["active_hours"]["covers_window"]:
            reasons.append("active hours do not cover the whole window")
    elif start is None or end is None:
        reasons.append("active hours are not set")
    scheme = state.get("power_scheme", {})
    checks["power_scheme"] = scheme
    if scheme.get("status") != "ok":
        reasons.append("power scheme could not be read")
    elif scheme.get("guid") not in HIGH_PERFORMANCE_GUIDS:
        reasons.append("power scheme is not High performance")
    battery = state.get("battery", {})
    checks["battery"] = battery
    if battery.get("status") == "ok" and battery.get("on_ac") is False:
        reasons.append("host is on battery power")
    return {"ready": not reasons, "reasons": reasons, "checks": checks}


def preflight(config, *, window_start=None, window_end=None, output=None, reader=None):
    if (window_start is None) != (window_end is None):
        raise StudioError("Give both --window-start and --window-end, or neither")
    window = None
    if window_start is not None:
        window = (parse_utc(window_start, "Window start"), parse_utc(window_end, "Window end"))
        if window[1] <= window[0]:
            raise StudioError("Window end must be after window start")
    state = read_state(reader)
    verdict = evaluate(state, window)
    result = {
        "schema_version": 1,
        "kind": "host-preflight",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "host_kind": state.get("host_kind"),
        "window": {"start_utc": window[0].isoformat(), "end_utc": window[1].isoformat()} if window else None,
        "ready": verdict["ready"],
        "reasons": verdict["reasons"],
        "checks": verdict["checks"],
        "state": state,
        "limits": LIMITS,
        "ok": verdict["ready"],
    }
    if output:
        # A receipt written into the installed toolkit would make the read-only
        # package a mutable evidence store; refuse it like every other output.
        target = outside_package(output)
        if target.exists():
            raise StudioError("Preflight output exists; choose a new filename")
        write_json(target, result)
        result["output"] = str(target)
    return result


def _powershell():
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    raise StudioError("Host apply needs PowerShell (pwsh or powershell)")


def apply(config, *, receipt, pause_days=3, active_start=18, active_end=12, what_if=False, restore=False):
    if not IS_WINDOWS:
        raise StudioError("Host apply runs only on native Windows; use preflight elsewhere")
    if not receipt:
        raise StudioError("Host apply needs --receipt for its JSON receipt")
    for name, value, low, high in (("pause days", pause_days, 1, 35), ("active start", active_start, 0, 23), ("active end", active_end, 0, 23)):
        if type(value) is not int or not low <= value <= high:
            raise StudioError(f"Host apply {name} must be an integer {low}–{high}")
    if active_start == active_end:
        raise StudioError("Active hours start and end must differ")
    target = outside_package(receipt)
    if target.exists():
        raise StudioError("Host receipt exists; choose a new filename")
    command = [
        _powershell(), "-NoProfile", "-NonInteractive", "-File", str(HOST_ROOT / SCRIPT),
        "-ReceiptPath", str(target), "-PauseDays", str(pause_days),
        "-ActiveStart", str(active_start), "-ActiveEnd", str(active_end),
    ]
    if restore:
        command.append("-Restore")
    if what_if:
        command.append("-WhatIf")
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StudioError("Could not run the host preparation script") from exc
    if completed.returncode:
        raise StudioError("Host preparation script failed; inspect its receipt path and run it by hand with -WhatIf")
    # On Windows, -WhatIf prints ShouldProcess diagnostics to stdout before the
    # receipt JSON, so the receipt file the script wrote is the trustworthy
    # result; stdout is only a fallback for the rare case the receipt is missing.
    if target.is_file():
        result = _read_receipt(target)
        if not isinstance(result, dict):
            raise StudioError("Host preparation receipt is not a JSON object")
    else:
        result = _last_json_object(completed.stdout)
        if result is None:
            raise StudioError("Host preparation script returned invalid JSON and wrote no receipt")
    # The script writes its receipt even under -WhatIf; say plainly whether the
    # path being reported is a file that exists.
    return {**result, "ok": True, "what_if": what_if, "receipt": str(target), "receipt_written": target.is_file()}


def _read_receipt(path):
    """Read the PowerShell receipt tolerating a byte-order mark.

    Windows PowerShell 5.1 writes UTF-8 with a BOM through several of its
    output paths. The host has already been changed by the time the receipt is
    read, so a BOM must not turn a successful apply into a decode failure.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise StudioError(f"Cannot read JSON record: {Path(path).name}") from exc


def _last_json_object(text):
    """The last self-contained JSON object in text, ignoring any leading diagnostics."""
    for match in reversed(list(re.finditer(r"\{", text or ""))):
        try:
            candidate = json.loads(text[match.start():])
        except ValueError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None
