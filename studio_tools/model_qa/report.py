"""Portable reports: every requested check gets an explicit PASS or FAIL row."""
import json
import struct
import zlib
from pathlib import Path

CHECKS = ("M12", "M13", "M5", "triangles", "ecology")


def row(check, passed, numbers, details=None):
    return {"check": check, "result": "PASS" if passed else "FAIL",
            "numbers": numbers, "details": details or {}}


def write(report, out):
    report["result"] = "PASS" if report["models"] and all(
        r["result"] == "PASS" for m in report["models"] for r in m["checks"]
    ) and not report.get("errors") else "FAIL"
    out = Path(out)
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
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
    lines += ["", "## Settings", "", "```json", json.dumps(report["settings"], indent=2), "```",
              "", "## Limits", "",
              "- M12 uses 3 mm contact; M13 fails on any major or more than two minor clips per 100 parts.",
              "- M5 pixel fraction is XOR / union at identical cameras for each adjacent pair. The configured threshold is a mechanical QA policy, not a calibrated perceptual pass.",
              "- Part correspondence flags parts with at most half their vertices near the next LOD surface. This can also flag a moved or strongly simplified part; inspect the named geometry.",
              "- Silhouettes measure opaque geometry, not alpha textures, materials, animation blending, runtime fades or engine visibility ranges.",
              "- Missing switch distances fail M5. Fallback distances produce diagnostic images only.",
              "- Ecology checks document structure, not biological truth.",
              "", "## Failures and flagged parts", ""]
    failures = False
    for model in report["models"]:
        for check in model["checks"]:
            if check["result"] == "FAIL":
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
