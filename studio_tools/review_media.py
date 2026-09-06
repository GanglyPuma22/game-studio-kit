"""Original-file media and explicit Windows FFmpeg capture; never desktop input."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import struct
import wave
from .common import StudioError, file_record, output_root, read_json, relative, sha256, write_json
from .config import require_executable
from .processes import record, run
from .validation import interval, number, validate_run


def inspect_media(config, source):
    source = Path(source).resolve()
    probe = run([require_executable(config, "ffprobe"), "-v", "error", "-show_streams", "-show_format",
                 "-show_frames", "-show_entries", "frame=media_type,best_effort_timestamp_time,pkt_duration_time:stream:format", "-of", "json", str(source)], timeout=120)
    raw = json.loads(probe["stdout"])
    video = [s for s in raw.get("streams", []) if s["codec_type"] == "video"]
    pts = [float(f["best_effort_timestamp_time"]) for f in raw.get("frames", []) if f.get("media_type") == "video" and "best_effort_timestamp_time" in f]
    if len(video) != 1 or len(pts) < 2 or any(b <= a for a, b in zip(pts, pts[1:])):
        raise StudioError("Media needs one decodable video stream with increasing frame PTS")
    duration = float(raw["format"]["duration"])
    number(duration, "media duration", .01)
    # A readable header or packet list alone cannot finalize an incomplete container.
    run([require_executable(config, "ffmpeg"), "-v", "error", "-xerror", "-err_detect", "explode", "-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"], timeout=120)
    normalized = [round(p - pts[0], 9) for p in pts]
    return {"duration_seconds": duration, "streams": raw["streams"], "frame_count": len(pts),
            "original_pts_seconds": pts, "timestamps_seconds": normalized,
            "first_pts_seconds": pts[0], "max_pts_gap_seconds": max(b-a for a, b in zip(pts, pts[1:])),
            "has_audio": any(s["codec_type"] == "audio" for s in raw["streams"]),
            "decode": "completed", "game_present_cadence": "unknown", "recorder_drops": "unknown",
            "duplicate_images": "unknown", "listening": "not_run"}


def _native_args(profile, duration):
    grant = profile.get("authorization", {})
    if os.name != "nt" or profile.get("host") != platform.node() or grant.get("permitted_recorder") != "ffmpeg_ddagrab" or grant.get("operator") != profile.get("operator"):
        raise StudioError("Native recording requires this Windows host, operator and permitted recorder receipt")
    if grant.get("target") != profile.get("target") or not grant.get("target") or not grant.get("receipt"):
        raise StudioError("Native recording requires an exact authorized target and receipt")
    deadline = datetime.fromisoformat(grant["deadline_utc"].replace("Z", "+00:00"))
    if (deadline - datetime.now(timezone.utc)).total_seconds() < duration + 5:
        raise StudioError("Native recording exceeds the authorized window")
    for key in ("output_index", "offset_x", "offset_y", "width", "height", "fps"):
        if type(profile.get(key)) is not int or profile[key] < (1 if key in {"width", "height", "fps"} else 0):
            raise StudioError("Native capture needs explicit target geometry and cadence")
    if profile["fps"] > 60:
        raise StudioError("Capture profile supports up to 60 FPS")
    source = (f"ddagrab=output_idx={profile['output_index']}:framerate={profile['fps']}:"
              f"offset_x={profile['offset_x']}:offset_y={profile['offset_y']}:"
              f"video_size={profile['width']}x{profile['height']}:draw_mouse=0:dup_frames=0")
    args = ["-f", "lavfi", "-i", source]
    if profile.get("audio_device"):
        if grant.get("audio_device") != profile["audio_device"]:
            raise StudioError("Audio device is outside capture authorization")
        args += ["-f", "dshow", "-i", "audio=" + profile["audio_device"], "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac"]
    args += ["-c:v", "h264_nvenc"]
    return args


def capture(config, root, name, profile, *, cancelled=None):
    data = validate_run(root, name)
    folder = relative(root, name)
    if (folder / "capture.json").exists() or (folder / "recorder").exists():
        raise StudioError("Capture is immutable; prepare a new run")
    duration = data["card"]["duration_seconds"]
    route = profile.get("route")
    ffmpeg = require_executable(config, "ffmpeg")
    require_executable(config, "ffprobe")
    if route == "file":
        source = Path(profile["source"]).resolve()
        if not source.is_file():
            raise StudioError("Capture source missing")
        args = ["-i", str(source), "-map", "0:v:0", "-map", "0:a?", "-c", "copy"]
        source_identity = {"sha256": sha256(source), "route": "file", "native_recording": False}
    elif route == "windows_ddagrab":
        args = _native_args(profile, duration)
        source_identity = {"route": route, "host": profile["host"], "operator": profile["operator"],
                           "target": profile["target"], "authorization": profile["authorization"],
                           "native_recording": True}
    else:
        raise StudioError("Unknown/denied recorder route; configure file or permitted windows_ddagrab")
    output = folder / "capture.mp4"
    args = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-n", "-stdin"] + args + ["-t", str(duration), "-movflags", "+faststart", str(output)]
    process = record(args, job_dir=folder / "recorder", duration=duration, cancelled=cancelled)
    result = {"schema_version": 1, "run_sha256": sha256(folder / "run.json"), "status": "incomplete",
              "source": source_identity, "process": process, "requested_duration_seconds": duration,
              "requested_fps": profile.get("fps"), "audio_capture_source": profile.get("audio_device", "source file" if route == "file" else "none"),
              "exclusions": [], "media": None, "files": [file_record(root, folder / "recorder/process.json"), file_record(root, folder / "recorder/stdout.log")]}
    if output.is_file():
        result["files"].append(file_record(root, output))
        try:
            result["media"] = inspect_media(config, output)
            enough = result["media"]["duration_seconds"] >= duration - .15
            if process["status"] == "completed" and enough:
                result["status"] = "completed"
            else:
                result["reason"] = "Capture ended early or was interrupted"
        except StudioError:
            result["reason"] = "Container failed complete video/audio decode"
    else:
        result["reason"] = "Recorder produced no media"
    # Source/candidate mutation during capture invalidates acceptance, preserving output.
    try:
        validate_run(root, name)
        if route == "file" and sha256(source) != source_identity["sha256"]:
            raise StudioError("Source changed")
    except StudioError:
        result.update(status="incomplete", reason="Candidate or source changed during capture")
    result["ok"] = result["status"] == "completed"
    write_json(folder / "capture.json", result)
    return result


def dense_frames(config, root, name, selected):
    validate_run(root, name, current=False)
    folder = relative(root, name)
    captured = read_json(folder / "capture.json")
    if captured["status"] != "completed":
        raise StudioError("Dense review needs a finalized capture")
    start, end = interval(selected, captured["media"]["duration_seconds"])
    pts = captured["media"]["timestamps_seconds"]
    indexes = [i for i, t in enumerate(pts) if start <= t <= end]
    if not indexes or len(indexes) > 180:
        raise StudioError("Dense interval requires 1–180 original frames; choose a bounded window")
    dest = folder / ("dense-" + str(len(list(folder.glob("dense-*")))))
    dest.mkdir(exist_ok=False)
    run([require_executable(config, "ffmpeg"), "-v", "error", "-n", "-i", str(folder / "capture.mp4"),
         "-vf", f"select=between(n\\,{indexes[0]}\\,{indexes[-1]})", "-vsync", "0", str(dest / "%05d.png")], timeout=120)
    images = sorted(dest.glob("*.png"))
    if len(images) != len(indexes):
        raise StudioError("Dense decode did not preserve the expected frame count")
    times = [pts[i] for i in indexes]
    result = {"schema_version": 1, "run_sha256": sha256(folder / "run.json"),
              "capture_sha256": sha256(folder / "capture.mp4"), "interval": selected,
              "max_gap_seconds": max(b-a for a, b in zip([start]+times, times+[end])),
              "frames": [{**file_record(root, path), "time_seconds": pts[index], "frame_index": index,
                          "original_pts_seconds": captured["media"]["original_pts_seconds"][index]} for path, index in zip(images, indexes)],
              "model_perception": "not_run"}
    write_json(dest / "frames.json", result)
    return result


def fixtures(config, destination):
    """Create anonymous moving original geometry + cue; truth is a separate file."""
    dest = Path(destination)
    output_root(dest.parent)
    dest.mkdir(parents=True, exist_ok=False)
    ffmpeg = require_executable(config, "ffmpeg")
    # 160x96 original raster frames. No licensed art, screenshots or player media.
    cases = {"clean": [], "brief": [27, 28, 29], "single": [28], "stutter": [], "recorder_drop": [], "interaction_success": [], "interaction_failure": [], "silent": []}
    outputs = []
    truth = {}
    for name, missing in cases.items():
        raw = dest / (name + ".rgb")
        fps = 60 if name == "single" else 30
        count = fps * 2
        if name == "single":
            missing = [56]
        with raw.open("wb") as stream:
            for n in range(count):
                motion_n = 26 if name == "stutter" and 27 <= n <= 30 else n
                pixels = bytearray()
                for y in range(96):
                    for x in range(160):
                        color = (30, 57, 67)
                        if y > 62 and n not in missing:
                            color = (164 + (x + motion_n) % 20, 112, 56)
                        if abs(x - (30 + motion_n)) < 10 and 40 < y < 65:
                            color = (219, 219, 191)
                        if name.startswith("interaction") and 115 < x < 135 and 35 < y < 62:
                            color = (33, 190, 92) if name == "interaction_success" and n >= 30 else (199, 44, 34)
                        pixels.extend(color)
                stream.write(pixels)
        wav = dest / (name + ".wav")
        import math
        with wave.open(str(wav), "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(2*math.pi*440*i/16000)) if name != "silent" and .95 <= i/16000 <= 1.15 else 0) for i in range(32000)))
        output = dest / (name + ".mp4")
        run([ffmpeg, "-v", "error", "-n", "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "160x96", "-framerate", str(fps), "-i", str(raw), "-i", str(wav)] + (["-vf", "select=not(between(n\\,27\\,29))", "-vsync", "vfr"] if name == "recorder_drop" else []) + ["-c:v", "mpeg4", "-q:v", "2", "-c:a", "aac", "-movflags", "+faststart", str(output)], timeout=60)
        metadata = inspect_media(config, output)
        outputs.append({**file_record(dest, output), "case": name, "frames": metadata["frame_count"]})
        telemetry = []
        time_seconds = 0
        while time_seconds < 2 - .00001:
            ms = 133.333333 if name == "stutter" and len(telemetry) == 27 else 1000/fps
            telemetry.append({"time_seconds": time_seconds, "frame_ms": ms})
            time_seconds += ms/1000
        write_json(dest / (name + "-timing.json"), telemetry)
        truth[name] = {"missing_frame_indexes": missing, "fps": fps, "event_interval": [min(missing)/fps, (max(missing)+1)/fps] if missing else None,
                       "game_stall": name == "stutter", "recorder_frame_loss": name == "recorder_drop",
                       "interaction_outcome": name == "interaction_success" if name.startswith("interaction") else None,
                       "cue_present": name != "silent", "perception": "not_run"}
    write_json(dest / "ground-truth.json", truth)
    manifest = {"schema_version": 1, "original": True, "fps": 30, "outputs": outputs, "perception": "not_run",
                "note": "Generated/decoded media only. Truth excluded from analyzer prompt. No detection claims."}
    write_json(dest / "fixtures.json", manifest)
    return manifest
