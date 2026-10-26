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
from .report import initial, write


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_manifest(path):
    data = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    if not isinstance(data, dict) or set(data) - {"schema_version", "structure", "living", "ground_y_m"}:
        raise ValueError("Model QA manifest needs an object with schema_version, structure, living, ground_y_m only")
    if data.get("schema_version", 1) != 1 or data.get("structure", "assembly") not in ("assembly", "scatter", "clump"):
        raise ValueError("Manifest schema_version must be 1; structure must be assembly, scatter or clump")
    if "living" in data and not isinstance(data['living'], bool):
        raise ValueError("Manifest living must be a boolean")
    ground = data.get('ground_y_m', 0.0)
    if isinstance(ground, bool) or not isinstance(ground, (float, int)) or not math.isfinite(ground):
        raise ValueError("Manifest ground_y_m must be finite")
    return {"schema_version": 1, "structure": "assembly", "ground_y_m": 0.0, **data}


def discover(inputs, manifest=None):
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
        candidate = Path(manifest).resolve() if manifest else next(
            (p for p in (parent / (name + '.model-qa.json'), parent / 'model-qa.json') if p.is_file()), None)
        family.update(manifest=read_manifest(candidate), manifest_path=str(candidate) if candidate else None,
                      manifest_sha256=digest(candidate) if candidate else None)
        if counts[name] > 1:
            family["name"] = f"{parent.name}/{name}"
        family["files"].sort(key=lambda f: f["lod"])
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("inputs", nargs="+")
    p.add_argument("--budget-tris", type=lambda s: None if s.lower() == 'not-set' else int(s), required=True,
                   help="Positive maximum only, or not-set; never implies a minimum")
    p.add_argument("--ecology", help="Ecology Markdown/YAML entry, or none with --reason")
    p.add_argument("--reason", help="Required non-living rationale when --ecology none is used")
    p.add_argument("--manifest", help="Explicit model QA JSON manifest; otherwise use each family's sidecar")
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
    p.add_argument("--timeout", type=int, default=90, help="Total Blender worker time, default 90; 1..32400 seconds")
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    settings = {key: getattr(args, key) for key in (
        "budget_tris", "switch_distances", "max_pixel_difference", "part_match_mm", "samples", "width", "height", "fov")}
    try:
        if (args.budget_tris is not None and args.budget_tris <= 0) or not 1 <= args.timeout <= 32400 or not 2 <= args.samples <= 120:
            raise ValueError("Budget must be positive or not-set; timeout 1..32400; samples 2..120")
        if args.ecology == 'none' and not (args.reason and args.reason.strip()):
            raise ValueError("--ecology none requires --reason")
        if args.reason and args.ecology != 'none':
            raise ValueError("--reason is only valid with --ecology none")
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
        families = discover(args.inputs, args.manifest)
        if args.ecology == 'none' and any(f['manifest'].get('living') is True for f in families):
            raise ValueError("--ecology none conflicts with manifest living: true")
        if args.switch_distances and any(len(f["files"]) != len(args.switch_distances) for f in families):
            raise ValueError("Provide exactly one distance per LOD in each family")
        out = Path(args.out).resolve()
        # Reusing old PNGs or reports would conceal a failed worker.
        out.mkdir(parents=True, exist_ok=False)
    except (ValueError, OSError) as exc:
        p.error(str(exc))
    eco_path = str(Path(args.ecology).resolve()) if args.ecology and args.ecology != 'none' else None
    request = {"families": families, "settings": settings, "out": str(out), "ecology_reason": args.reason,
               "ecology": eco_path, "ecology_sha256": digest(eco_path) if eco_path and Path(eco_path).is_file() else None}
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
        report = initial(request)
        report['errors'] = errors or ["Worker produced no report"]
    for family in families:
        try:
            if family['manifest_path'] and digest(family['manifest_path']) != family['manifest_sha256']:
                report['errors'].append('Model QA manifest changed during execution')
        except OSError as exc:
            report['errors'].append(f'Model QA manifest unavailable after execution: {exc}')
    write(report, out)
    execution["result"] = report["result"]
    (out / "execution.json").write_text(json.dumps(execution, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "report": str(report_path), "models": len(report["models"])}))
    return 0 if report["result"] in ("PASS", "N/A", "INFO") else 1


if __name__ == "__main__":
    sys.exit(main())
