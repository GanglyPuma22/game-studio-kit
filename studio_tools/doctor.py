"""Offline discovery is evidence of installation, not production readiness."""

import os
import platform
import re
from .config import executable
from .processes import run
from .common import StudioError

ACTIONS = {
    "blender": "Install Blender 5.0.x; set executables.blender to its full executable path; run the fixture round trip.",
    "godot": "Install Godot 4.5.1 standard; set executables.godot; run import and headless smoke, then native review.",
    "gaea": "Install an entitled Gaea edition; save a working graph and verify its installed-version build command in the UI.",
    "ffmpeg": "Optional: install FFmpeg and set executables.ffmpeg for capture/transcode.",
    "ffprobe": "Optional: install FFprobe and set executables.ffprobe for encoded-media measurements.",
    "meshy": "Optional: set MESHY_API_KEY (or the configured variable), confirm a work-card budget and current account rates before submit.",
    "elevenlabs": "Optional: set ELEVENLABS_API_KEY (or the configured variable), confirm rights, entitlement and work-card budget.",
    "computer_use": "The active host must expose computer-use tools and inspect the native app; follow docs/windows-smoke.md.",
}


def inspect(config):
    capabilities = {}
    for name in ("blender", "godot", "gaea", "ffmpeg", "ffprobe"):
        exe = executable(config, name)
        entry = {
            "status": "needs_setup",
            "installed": bool(exe),
            "next_step": ACTIONS[name],
            "operations": "unverified",
        }
        if exe:
            if name == "gaea":
                entry.update(
                    status="unverified",
                    reason="Gaea version/entitlement requires an installed-version UI check; no speculative CLI probe",
                )
            else:
                try:
                    args = [
                        exe,
                        "-version" if name in {"ffmpeg", "ffprobe"} else "--version",
                    ]
                    result = run(args, timeout=10)
                    line = next(
                        (s.strip() for s in result["stdout"].splitlines() if s.strip()),
                        "",
                    )
                    # Return only a recognizable version, never arbitrary tool output.
                    match = re.search(r"\d+\.\d+(?:\.\d+)?(?:\.stable)?", line)
                    entry.update(
                        status="ready" if match else "unverified",
                        version=match.group(0) if match else None,
                    )
                    if match and name in {"blender", "godot"}:
                        minimum = (5, 0) if name == "blender" else (4, 5)
                        current = tuple(map(int, match.group(0).split(".")[:2]))
                        if current < minimum:
                            entry.update(
                                status="unsupported",
                                reason="Installed version is older than the supported adapter profile",
                            )
                except StudioError:
                    entry.update(
                        status="needs_setup",
                        reason="Executable could not report its version; check path and execution permission",
                    )
        capabilities[name] = entry
    for provider in ("meshy", "elevenlabs"):
        present = bool(os.environ.get(config["credentials"][provider]))
        capabilities[provider] = {
            "status": "unverified" if present else "needs_setup",
            "credential_present": present,
            "network_probed": False,
            "next_step": ACTIONS[provider],
        }
    capabilities["computer_use"] = {
        "status": "unverified",
        "next_step": ACTIONS["computer_use"],
        "reason": "A Python helper cannot detect the active agent's tools or visual access",
    }
    return {
        "schema_version": 1,
        "host": platform.system(),
        "capabilities": capabilities,
    }


def setup(report):
    return {
        "actions": [
            {"capability": key, "status": value["status"], "action": value["next_step"]}
            for key, value in report["capabilities"].items()
            if value["status"] != "ready" or value.get("operations") == "unverified"
        ],
        "applied": [],
        "note": "No installations or credential probes performed. Follow the actions within your existing authorization.",
    }
