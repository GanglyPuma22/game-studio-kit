#!/usr/bin/env python3
"""Original isolated Godot QOA regression; no desktop, credentials or listening claim."""
import argparse
import array
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


def check(executable, timeout=90):
    with tempfile.TemporaryDirectory(prefix="studio-audio-import-") as folder:
        root = Path(folder)
        project = root / "project"
        project.mkdir()
        (project / "project.godot").write_text('[application]\nconfig/name="Original QOA regression"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
        rate, frames = 24000, 576000
        values = array.array("h", (round(2000 * math.sin(2 * math.pi * 220 * (i // 2) / rate)) for i in range(frames * 2)))
        if sys.byteorder != "little":
            values.byteswap()
        with wave.open(str(project / "original.wav"), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(values.tobytes())
        (project / "original.wav.import").write_text('''[remap]
importer="wav"
type="AudioStreamWAV"
[deps]
source_file="res://original.wav"
[params]
compress/mode=2
force/max_rate=false
edit/trim=false
edit/normalize=false
edit/loop_mode=0
''')
        template = Path(__file__).resolve().parents[1] / "studio_tools/godot_template/main.gd"
        # Execute the shipped assignment, so this regression fails if it reverts
        # to a PCM-width division of compressed bytes.
        assignment = next(line.strip() for line in template.read_text().splitlines() if "stream.loop_end =" in line)
        (project / "check.gd").write_text('''extends SceneTree
func fail_check(message: String):
    push_error("STUDIO_QOA_FAILURE: " + message)
    quit(1)

func _initialize():
    var stream = load("res://original.wav") as AudioStreamWAV
    if stream == null:
        fail_check("AudioStreamWAV failed to load")
        return
    if stream.format != AudioStreamWAV.FORMAT_QOA or not stream.stereo or stream.mix_rate != 24000 or abs(stream.get_length() - 24.0) >= 0.0001:
        fail_check("Expected stereo QOA at 24000 Hz for 24 seconds")
        return
    stream.loop_begin = 0
    ''' + assignment + '''
    stream.loop_mode = AudioStreamWAV.LOOP_FORWARD
    if stream.loop_end != 576000 or stream.data.size() / 4 == stream.loop_end:
        fail_check("Expected 576000 decoded loop frames; got " + str(stream.loop_end))
        return
    print("STUDIO_QOA_RESULT=" + JSON.stringify({"format":stream.format, "sample_rate":stream.mix_rate, "duration_seconds":stream.get_length(), "data_bytes":stream.data.size(), "loop_end_frame":stream.loop_end, "listening":"not_run"}))
    quit()
''')
        env = dict(os.environ)
        for key in ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"]:
            isolated = root / key.lower()
            isolated.mkdir()
            env[key] = str(isolated)
        diagnostics = []
        def run(args):
            try:
                p = subprocess.run([str(Path(executable).resolve()), "--headless", "--path", str(project), *args], env=env, capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                captured = [value.decode(errors="replace") if isinstance(value, bytes) else value or ""
                            for value in (exc.stdout, exc.stderr)]
                raise RuntimeError(f"Godot QOA check timed out after {timeout} seconds (" + " ".join(args) + "):\n" + "".join(captured)) from None
            diagnostics.extend(line for line in (p.stdout + p.stderr).splitlines() if "ERROR:" in line)
            if p.returncode or "SCRIPT ERROR" in p.stdout + p.stderr:
                raise RuntimeError(p.stdout + p.stderr)
            return p.stdout
        run(["--editor", "--import"])
        output = run(["--script", "check.gd"])
        marker = "STUDIO_QOA_RESULT="
        matches = [line.split(marker, 1)[1] for line in output.splitlines() if marker in line]
        if len(matches) != 1:
            raise RuntimeError("Missing QOA result: " + output)
        result = json.loads(matches[0])
        result["engine_diagnostics"] = sorted(set(diagnostics))
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(check(args.godot), indent=2))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
