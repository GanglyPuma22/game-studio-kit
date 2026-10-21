"""Portable reports with separate measurement, applicability and missing-policy states."""
import json
import struct
import zlib
from pathlib import Path

CHECKS = ("M12", "M13", "M5", "triangles", "ecology")


def row(check, passed, numbers, details=None):
    state = passed if isinstance(passed, str) else ("PASS" if passed else "FAIL")
    if state not in {"PASS", "FAIL", "N/A", "NOT SET", "INFO", "UNMEASURED"}:
        raise ValueError("Unknown QA state: " + str(state))
    return {"check": check, "result": state,
            "numbers": numbers, "details": details or {}}


def budget(triangles, maximum):
    if maximum is None:
        return row("triangles", "NOT SET", f"{triangles if triangles is not None else 'unmeasured'} triangles; maximum NOT SET",
                   {"triangles": triangles, "maximum": None})
    return row("triangles", "UNMEASURED" if triangles is None else triangles <= maximum,
               f"{triangles if triangles is not None else 'unmeasured'} / {maximum} triangles (maximum only)",
               {"triangles": triangles, "maximum": maximum})


def overlaps(poses, structure):
    return row("M13", "INFO" if structure == "clump" else all(p["result"] == "PASS" for p in poses),
               f"max {max(p['major'] for p in poses)} major, {max(p['minor'] for p in poses)} minor; "
               f"limit 2/100 parts; {len(poses)} poses; structure={structure}",
               {"poses": poses, "structure": structure, "applicability": "informational" if structure == "clump" else "strict"})


def metadata_rows(family, request, triangles=None):
    from .ecology import check
    eco = check(request.get("ecology"), living=family.get("manifest", {}).get("living"), reason=request.get("ecology_reason"))
    return [budget(triangles, request["settings"]["budget_tris"]),
            row("ecology", eco["result"], f"{eco['reason']}; status={eco['status']}; review={eco['review_status']}", eco)]


def initial(request):
    return {"schema_version": 2, "settings": request["settings"], "errors": [], "models": [
        {"model": family["name"], "lod": item["lod"], "file": Path(item["path"]).name, "sha256": item["sha256"],
         "manifest": family.get("manifest", {"structure": "assembly"}), "manifest_sha256": family.get("manifest_sha256"),
         "checks": [row(c, "UNMEASURED", "0 completed measurements") for c in CHECKS[:3]] + metadata_rows(family, request)}
        for family in request["families"] for item in family["files"]]}


def write(report, out):
    states = [r["result"] for m in report["models"] for r in m["checks"]]
    report["result"] = 'UNMEASURED' if not states or report.get('errors') else next((s for s in ("UNMEASURED", "FAIL", "NOT SET", "INFO") if s in states),
                            "N/A" if all(s == "N/A" for s in states) else "PASS")
    report["state_counts"] = {s: states.count(s) for s in sorted(set(states))}
    out = Path(out)
    (out / "report.json.tmp").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "report.json.tmp").replace(out / "report.json")
    lines = ["# Model QA", "", f"Result: **{report['result']}**", "",
             "Mechanical QA only; artistic quality and in-game transitions still need human review.",
             "", "| Model | LOD | Check | Result | Measurements |",
             "|---|---:|---|---|---|"]
    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    for model in report["models"]:
        for check in model["checks"]:
            lines.append("| " + " | ".join(map(safe, (model["model"], model["lod"], check["check"],
                                                        check["result"], check["numbers"]))) + " |")
    lines += ["", "## Inputs", ""]
    for m in report["models"]:
        lines.append(f"- `{safe(m['file'])}`: `{m['sha256']}`")
        for note in m.get('notes', []):
            lines.append(f"  - {safe(note)}")
    lines += ["", "## Settings", "", "```json", json.dumps(report["settings"], indent=2), "```",
              "", "## Limits", "",
              "- M12 uses 3 mm contact: assembly attachment, or per-piece contact with the manifest's Y-up ground plane for scatter/clump.",
              "- M13 fails on any major or more than two minor clips per 100 parts for assemblies/scatters. Declared clumps retain the same raw measurements as INFO.",
              "- M5 pixel fraction is XOR / union at identical cameras for each adjacent pair. The configured threshold is a mechanical QA policy, not a calibrated perceptual pass.",
              "- Part correspondence flags parts with at most half their vertices near the next LOD surface. This can also flag a moved or strongly simplified part; inspect the named geometry.",
              "- Silhouettes measure opaque geometry, not alpha textures, materials, animation blending, runtime fades or engine visibility ranges.",
              "- Missing switch distances fail M5. Fallback distances produce diagnostic images only.",
              "- Ecology checks document structure, not biological truth or proposal approval. Explicit non-living declarations are N/A.",
              "- NOT SET means no triangle maximum was declared; there is no implied minimum. UNMEASURED means evidence is incomplete, never a geometric pass or defect.",
              "", "## Check details and limitations", ""]
    failures = False
    for model in report["models"]:
        for check in model["checks"]:
            if check["result"] != "PASS":
                failures = True
                details = check["details"]
                # The machine report keeps every part. Keep the review sheet
                # readable even for a model with thousands of disconnected leaves.
                if len(details.get("disappeared_parts", [])) > 20:
                    details = {**details, "disappeared_parts": details["disappeared_parts"][:20],
                               "additional_flagged_parts": len(details["disappeared_parts"]) - 20,
                               "full_evidence": "report.json"}
                if len(details.get("parts", [])) > 20:
                    bad = [r for r in details["parts"] if r.get("status") == "FLOATING"]
                    details = {**details, "parts": bad[:20],
                               "additional_floating_parts": max(0, len(bad) - 20),
                               "full_evidence": "report.json"}
                lines += [f"### {safe(model['model'])} LOD{model['lod']} {check['check']}", "",
                          "```json", json.dumps(details, indent=2, allow_nan=False), "```", ""]
    if not failures:
        lines.append("None.")
    if report.get("errors"):
        lines += ["", "## Execution errors", "", *[f"- {safe(e)}" for e in report["errors"]]]
    lines += ["", "## Silhouettes", "", "![Four side geometric silhouettes](contact-sheet.png)", "",
              "The contact sheet uses one shared center crop with its pixel scale labelled. Full resolution PNGs are in `silhouettes/`.",
              "Each transition includes both LODs at the incoming LOD's distance.", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    if not (out / "contact-sheet.png").exists():
        # No optional dependency is needed to leave an unmistakable failure tile.
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        pixels = b"".join(b"\0" + bytes([190, 20, 20]) * 64 for _ in range(64))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
        (out / "contact-sheet.png").write_bytes(png + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))
    return report
