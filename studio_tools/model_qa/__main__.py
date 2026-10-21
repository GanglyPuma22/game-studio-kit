"""python -m studio_tools.model_qa: one bounded Blender job and portable reports."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

from studio_tools.common import StudioError
from studio_tools.processes import prelaunch_baseline, run, stop_survivors
from .report import CHECKS, row, write


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def discover(inputs):
    files = []
    for value in inputs:
        path = Path(value).resolve()
        if path.is_dir():
            files.extend(sorted(path.rglob("*.glb")))
        elif path.is_file() and path.suffix.lower() == ".glb":
            files.append(path)
        else:
            raise ValueError(f"Not a model folder or GLB: {value}")
    files = sorted(set(files))
    if not files:
        raise ValueError("No GLBs found")
    families = {}
    for path in files:
        match = re.fullmatch(r"(.+?)[-_]lod(\d+)", path.stem, re.I)
        name, lod = (match[1], int(match[2])) if match else (path.stem, 0)
        key = (path.parent, name)
        family = families.setdefault(key, {"name": name, "id": f"model-{len(families)}", "files": []})
        if any(f["lod"] == lod for f in family["files"]):
            raise ValueError(f"Duplicate LOD{lod} in family {name}")
        family["files"].append({"path": str(path), "lod": lod, "sha256": digest(path)})
    result = list(families.values())
    counts = Counter(f["name"] for f in result)
    for (parent, name), family in families.items():
        if counts[name] > 1:
            family["name"] = f"{parent.name}/{name}"
        family["files"].sort(key=lambda f: f["lod"])
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("inputs", nargs="+")
    p.add_argument("--budget-tris", type=int, required=True)
    p.add_argument("--ecology", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--blender", default=os.environ.get("MODEL_QA_BLENDER") or shutil.which("blender"))
    p.add_argument("--python-site-packages", default=os.environ.get("MODEL_QA_PYTHON_SITE_PACKAGES"),
                   help="Optional dependency directory matching Blender's Python ABI; no installation is performed")
    p.add_argument("--switch-distances", type=float, nargs="+",
                   help="LOD0 preview distance then LOD1, LOD2... incoming switch distances, in metres")
    p.add_argument("--max-pixel-difference", type=float, default=0.05, help="Maximum XOR/union fraction; default 0.05")
    p.add_argument("--part-match-mm", type=float, default=3.0, help="Missing-part surface correspondence tolerance")
    p.add_argument("--samples", type=int, default=6)
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fov", type=float, default=75, help="Vertical perspective FOV in degrees")
    p.add_argument("--timeout", type=int, default=1800, help="Total Blender worker time, 1..32400 seconds")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    settings = {key: getattr(args, key) for key in (
        "budget_tris", "switch_distances", "max_pixel_difference", "part_match_mm", "samples", "width", "height", "fov")}
    try:
        if args.budget_tris <= 0 or not 1 <= args.timeout <= 32400 or not 2 <= args.samples <= 120:
            raise ValueError("Budget must be positive; timeout 1..32400; samples 2..120")
        if not 16 <= args.width <= 4096 or not 16 <= args.height <= 4096:
            raise ValueError("Image dimensions must be 16..4096")
        if not math.isfinite(args.fov) or not 1 < args.fov < 179:
            raise ValueError("FOV must be finite and between 1 and 179 degrees")
        if not math.isfinite(args.max_pixel_difference) or not 0 <= args.max_pixel_difference <= 1:
            raise ValueError("Pixel difference must be in [0, 1]")
        if not math.isfinite(args.part_match_mm) or args.part_match_mm <= 0:
            raise ValueError("Part correspondence tolerance must be finite and positive")
        if args.switch_distances and (any(not math.isfinite(d) or d <= 0 for d in args.switch_distances)
                                      or any(a >= b for a, b in zip(args.switch_distances, args.switch_distances[1:]))):
            raise ValueError("Switch distances must be finite, positive, and strictly increasing")
        families = discover(args.inputs)
        if args.switch_distances and any(len(f["files"]) != len(args.switch_distances) for f in families):
            raise ValueError("Provide exactly one distance per LOD in each family")
        out = Path(args.out).resolve()
        # Reusing old PNGs or reports would conceal a failed worker.
        out.mkdir(parents=True, exist_ok=False)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    request = {"families": families, "settings": settings, "out": str(out),
               "ecology": str(Path(args.ecology).resolve()),
               "ecology_sha256": digest(args.ecology) if Path(args.ecology).is_file() else None}
    (out / "request.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    execution = {"result": "FAIL", "timeout_seconds": args.timeout}
    errors = []
    try:
        if not args.blender or not Path(args.blender).is_file():
            raise ValueError("Blender unavailable; pass --blender or set MODEL_QA_BLENDER")
        worker = Path(__file__).with_name("worker.py")
        source_paths = sorted(Path(__file__).parent.glob("*.py"))
        before = {path.name: digest(path) for path in source_paths}
        executable_digest = digest(args.blender)
        command = [str(Path(args.blender).resolve()), "--background", "--factory-startup", "--disable-autoexec",
                   "--python-exit-code", "2", "--python", str(worker), "--", "--request", str(out / "request.json")]
        if args.python_site_packages:
            if not Path(args.python_site_packages).is_dir():
                raise ValueError("Dependency directory does not exist")
            command += ["--python-site-packages", str(Path(args.python_site_packages).resolve())]
        baseline = prelaunch_baseline(hide_window=True)
        if digest(args.blender) != executable_digest:
            raise ValueError("Blender executable changed before launch")
        execution.update(blender_sha256=executable_digest, source_sha256=before)
        try:
            result = run(command, timeout=args.timeout, job_dir=out / "process", hide_window=True, baseline=baseline)
            execution["process"] = {k: v for k, v in result.items() if k != "stdout"}
        finally:
            # Keep cleanup on the failed-worker path too, before inspecting output.
            record_path = out / "process/process.json"
            if record_path.is_file():
                process_record = json.loads(record_path.read_text(encoding="utf-8"))
                pid = process_record.get("pid")
                if pid and process_record.get("status") != "timed_out":
                    cleanup = stop_survivors(pid, hide_window=True, ownership=process_record.get("windows_ownership"))
                    execution["cleanup"] = cleanup
                    if cleanup.get("pids") or cleanup.get("unverified") or cleanup.get("status") != "ok":
                        errors.append("Worker descendants could not be fully accounted for; see execution.json")
        if digest(args.blender) != executable_digest or any(digest(path) != before[path.name] for path in source_paths):
            errors.append("Executable or QA source changed during execution")
    except (ValueError, OSError, StudioError, KeyboardInterrupt) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report_path = out / "report.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["errors"].extend(errors)
    else:
        report = {"schema_version": 1, "settings": settings, "errors": errors or ["Worker produced no report"], "models": [
            {"model": family["name"], "lod": item["lod"], "file": Path(item["path"]).name, "sha256": item["sha256"],
             "checks": [row(c, False, "0 completed measurements", {"error": "No complete worker report"}) for c in CHECKS]}
            for family in families for item in family["files"]]}
    write(report, out)
    execution["result"] = report["result"]
    (out / "execution.json").write_text(json.dumps(execution, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "report": str(report_path), "models": len(report["models"])}))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
