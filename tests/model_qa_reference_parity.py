"""Opt-in same-file comparison with externally supplied, audited reference scripts.

Run with Blender --background --python this-file -- --help. References stay
outside the kit. This checks measured outputs, not strings copied from old reports.
"""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def original(script, model, output):
    old_argv = sys.argv
    sys.argv = [str(script), str(model), "--json", str(output)]
    log = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(log):
            try:
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.argv = old_argv
    output.with_suffix(".log").write_text(log.getvalue(), encoding="utf-8")
    if code not in (0, 1) or not output.is_file():
        raise RuntimeError(f"Reference failed to produce a verdict: {script.name}")
    return json.loads(output.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-static", required=True, type=Path)
    parser.add_argument("--reference-skin", required=True, type=Path)
    parser.add_argument("--reference-clip", required=True, type=Path)
    parser.add_argument("--models", nargs="+", required=True, type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--python-site-packages")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if args.python_site_packages:
        sys.path.insert(0, args.python_site_packages)
    sys.path.insert(0, str(args.reference_skin.parent))
    from studio_tools.model_qa import attachment, clipping, geometry
    port_files = sorted(Path(geometry.__file__).parent.glob("*.py"))
    port_hashes = {p.name: digest(p) for p in port_files}
    args.out.mkdir(parents=True, exist_ok=False)
    results = []
    for i, path in enumerate(args.models):
        tm, parts, names, skin = geometry.load(path)
        reference = original(args.reference_skin if skin else args.reference_static, path, args.out / f"{i}-attach.json")
        port = attachment.skinned(skin) if skin else attachment.static(parts)
        original_floaters = [r["part"] for r in reference["parts"] if r["status"] == "FLOATING"]
        port_floaters = [r["part"] for r in port["parts"] if r["status"] == "FLOATING"]
        a = {"reference": reference["result"], "port": port["result"],
             "reference_floating": original_floaters, "port_floating": port_floaters,
             "equal": reference["result"] == port["result"] and original_floaters == port_floaters}
        c = None
        if not skin:
            reference_clip = original(args.reference_clip, path, args.out / f"{i}-clip.json")
            port_clip = clipping.check(tm, parts)
            c = {"reference": {k: reference_clip[k] for k in ("result", "major", "minor")},
                 "port": {k: port_clip[k] for k in ("result", "major", "minor")},
                 "reference_pairs": [(r["a"], r["b"]) for r in reference_clip["clipping"]],
                 "port_pairs": [(r["a"], r["b"]) for r in port_clip["clipping"]]}
            c["equal"] = c["reference"] == c["port"] and c["reference_pairs"] == c["port_pairs"]
        results.append({"input": str(path), "sha256": digest(path), "M12": a, "M13": c,
                        "part_names": names if not a["equal"] or c and not c["equal"] else []})
    report = {"result": "PASS" if all(r["M12"]["equal"] and (r["M13"] is None or r["M13"]["equal"]) for r in results) else "FAIL",
              "port_sha256": port_hashes,
              "reference_sha256": {key: digest(getattr(args, key)) for key in ("reference_static", "reference_skin", "reference_clip")},
              "files": results}
    if any(digest(p) != port_hashes[p.name] for p in port_files):
        report["result"] = "FAIL"
        report["error"] = "Port source changed during the comparison"
    (args.out / "parity.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "files": len(results)}))
    if report["result"] != "PASS":
        raise RuntimeError("Reference parity failed; inspect named parts in parity.json")


if __name__ == "__main__":
    main()
