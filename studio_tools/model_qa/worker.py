"""Blender entrypoint, launched once and synchronously by the public CLI."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import traceback


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(request):
    import bpy
    import numpy as np
    import trimesh
    from studio_tools.model_qa import attachment, clipping, ecology, geometry, silhouettes
    from studio_tools.model_qa.report import row, write, CHECKS, initial, budget, overlaps

    out = Path(request["out"])
    render_dir = out / "silhouettes"
    render_dir.mkdir()
    settings = request["settings"]
    report = initial(request)
    report['runtime'] = {"blender": bpy.app.version_string, "python": sys.version.split()[0],
                          "dependencies": {name: importlib.metadata.version(name)
                                           for name in ("numpy", "trimesh", "scipy", "networkx", "rtree", "pygltflib", "pillow", "PyYAML")}}
    write(report, out)
    entries = iter(report['models'])
    def record(entry, check):
        entry['checks'] = [check if c['check'] == check['check'] else c for c in entry['checks']]
        write(report, out)
    tiles = []
    for family in request["families"]:
        loaded = []
        manifest = family.get('manifest', {'structure': 'assembly'})
        for item in family["files"]:
            entry = next(entries)
            try:
                if sha(item["path"]) != item["sha256"]:
                    raise ValueError("Input changed after the CLI hashed it")
                tm, parts, names, skin = geometry.load(item["path"])
                entry['notes'] = tm.metadata.get('qa_notes', [])
                record(entry, budget(len(tm.faces), settings['budget_tris']))
                entry["parts"] = geometry.part_inventory(parts, names)
                attach = attachment.measure(parts, skin, samples=settings["samples"],
                                            structure=manifest['structure'], ground_y_m=manifest.get('ground_y_m', 0.0))
                for r in attach["parts"]:
                    if isinstance(r["part"], int):
                        r["name"] = names[r["part"]]
                    elif "part_id" in r:
                        r["name"] = names[r["part_id"]]
                record(entry, row("M12", attach["result"] == "PASS",
                                            f"{attach['floating']} floating / {attach['part_count']} parts; {attach['poses']} poses; 3 mm",
                                            attach))
                poses = [("rest", 0.0)] + ([(clip, float(t)) for clip in skin.anims
                                          for t in np.linspace(0, skin.duration(clip), settings["samples"])] if skin else [])
                clips = []
                skin_labels = attachment.part_labels(skin) if skin else None
                for clip, time in poses:
                    posed = tm
                    posed_parts = parts
                    if skin:
                        posed = trimesh.Trimesh(skin.posed(None if clip == "rest" else clip, time), skin.idx, process=False)
                        # Keep rest topology identities when parts touch in a pose.
                        # Re-welding the posed geometry could merge a collision away.
                        posed_parts = [posed.submesh([np.flatnonzero(skin_labels == i)], append=True)
                                       for i in range(int(skin_labels.max()) + 1)]
                        for part in posed_parts:
                            part.merge_vertices(merge_tex=True, merge_norm=True)
                    check = clipping.check(posed, posed_parts)
                    for collision in check["clipping"]:
                        collision["a_name"] = names[collision["a"]] if collision["a"] < len(names) else f"part-{collision['a']}"
                        collision["b_name"] = names[collision["b"]] if collision["b"] < len(names) else f"part-{collision['b']}"
                    clips.append({"pose": clip, "time": time, **check})
                record(entry, overlaps(clips, manifest['structure']))
                loaded.append((item, entry, tm, parts, names))
            except Exception as exc:
                report["errors"].append(f"{family['name']} LOD{item['lod']}: {type(exc).__name__}: {exc}")
                entry['checks'] = [row(c['check'], 'UNMEASURED', 'Measurement incomplete', {'error': str(exc)})
                                   if c['result'] == 'UNMEASURED' else c for c in entry['checks']]
                write(report, out)
                traceback.print_exc()

        distances = settings.get("switch_distances")
        declared = distances is not None and len(distances) == len(family["files"])
        valid_chain = len(loaded) == len(family["files"]) >= 2 and [
            f["lod"] for f in family["files"]] == list(range(len(family["files"])))
        if not loaded:
            continue
        # A common center from the complete family prevents recentering from hiding shrinkage.
        bounds = np.array([tm.bounds for _, _, tm, _, _ in loaded])
        center = (bounds[:, 0].min(axis=0) + bounds[:, 1].max(axis=0)) / 2
        radius = float(np.linalg.norm(bounds[:, 1].max(axis=0) - bounds[:, 0].min(axis=0)))
        fallback = max(2.0, radius * 2)
        previous = None
        for index, (item, entry, tm, parts, names) in enumerate(loaded):
            distance = distances[index] if declared else fallback * (3 ** index)
            details = {"switch_distance_m": distance, "distance_declared": declared,
                       "valid_chain": valid_chain, "views": [], "disappeared_parts": []}
            try:
                for side in silhouettes.SIDES:
                    path = render_dir / f"{family['id']}-lod{item['lod']}-{side}.png"
                    mask = silhouettes.render(tm, center, distance, side, path, settings["width"], settings["height"], settings["fov"])
                    tiles.append((path, f"{family['name']} LOD{item['lod']} {side} {distance:g}m"))
                    if previous:
                        pitem, _, ptm, _, _ = previous
                        before_path = render_dir / f"{family['id']}-lod{pitem['lod']}-at-{item['lod']}-{side}.png"
                        before = silhouettes.render(ptm, center, distance, side, before_path, settings["width"], settings["height"], settings["fov"])
                        tiles.append((before_path, f"LOD{pitem['lod']} before {side} {distance:g}m"))
                    else:
                        before = mask
                    details["views"].append({"side": side, **silhouettes.compare(before, mask)})
                if previous:
                    details["disappeared_parts"] = silhouettes.disappeared(previous[3], previous[4], tm, settings["part_match_mm"])
                worst = max(v["difference_fraction"] for v in details["views"])
                passed = (declared and valid_chain and not details["disappeared_parts"] and
                          worst <= settings["max_pixel_difference"] and
                          all(v["before_pixels"] and v["after_pixels"] and not v["frame_clipped"] for v in details["views"]))
                record(entry, row("M5", passed,
                                            f"max XOR/union={worst:.6f} / {settings['max_pixel_difference']}; "
                                            f"{len(details['disappeared_parts'])} missing parts; distance={distance:g}m; declared={declared}",
                                            details))
            except Exception as exc:
                record(entry, row("M5", "UNMEASURED", "0 complete four-side comparisons", {"error": str(exc), **details}))
                report["errors"].append(f"Silhouettes {family['name']} LOD{item['lod']}: {exc}")
                traceback.print_exc()
            previous = (item, entry, tm, parts, names)
        for item in family["files"]:
            if sha(item["path"]) != item["sha256"]:
                report["errors"].append(f"Input changed during QA: {Path(item['path']).name}")
    if request.get("ecology_sha256") != (sha(request["ecology"]) if request.get('ecology') and Path(request["ecology"]).is_file() else None):
        report["errors"].append("Ecology entry changed during QA")
    for model in report["models"]:
        model["checks"].sort(key=lambda r: CHECKS.index(r["check"]))
    try:
        silhouettes.contact_sheet(tiles, out)
    except Exception as exc:
        report['errors'].append(f'Contact sheet unmeasured: {type(exc).__name__}: {exc}')
    return write(report, out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--python-site-packages")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    if args.python_site_packages:
        sys.path.insert(0, args.python_site_packages)
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    execute(request)
    # Geometry failures are reported data; the parent supplies exit code 1.


if __name__ == "__main__":
    main()
