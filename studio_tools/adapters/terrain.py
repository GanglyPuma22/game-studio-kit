"""Original finite local heightfield with reproducible dimensions and mask."""

import math
from pathlib import Path
import struct
from ..common import StudioError, write_json, file_record


def create(root, resolution=33, width=12.0, depth=12.0, elevation=0.7):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if (
        type(resolution) is not int
        or not 3 <= resolution <= 1025
        or not all(math.isfinite(x) and x > 0 for x in (width, depth, elevation))
    ):
        raise StudioError(
            "Terrain needs resolution 3–1025 and positive finite dimensions"
        )
    heights = []
    for z in range(resolution):
        row = []
        for x in range(resolution):
            u = x / (resolution - 1)
            v = z / (resolution - 1)
            # Flatten the full boundary for easy adjacent-tile validation.
            row.append(
                math.sin(math.pi * u) ** 2
                * math.sin(math.pi * v) ** 2
                * (0.65 + 0.35 * math.cos(2 * math.pi * u))
            )
        heights.append(row)
    maximum = max(max(row) for row in heights)
    heights = [[v / maximum for v in row] for row in heights]
    raw = b"".join(struct.pack(">H", round(v * 65535)) for row in heights for v in row)
    pgm = root / "height.pgm"
    pgm.write_bytes(f"P5\n{resolution} {resolution}\n65535\n".encode() + raw)
    mask = root / "shore-mask.pgm"
    mask.write_bytes(
        f"P5\n{resolution} {resolution}\n255\n".encode()
        + bytes(round((1 - v) * 255) for row in heights for v in row)
    )
    obj = root / "terrain.obj"
    lines = ["# Original Game Studio Kit procedural terrain; metres; Y up"]
    for z, row in enumerate(heights):
        for x, h in enumerate(row):
            lines.append(
                f"v {x / (resolution - 1) * width - width / 2:.6f} {h * elevation:.6f} {z / (resolution - 1) * depth - depth / 2:.6f}"
            )
    for z in range(resolution - 1):
        for x in range(resolution - 1):
            a = z * resolution + x + 1
            b = a + 1
            c = a + resolution
            d = c + 1
            lines.extend([f"f {a} {c} {b}", f"f {b} {c} {d}"])
    obj.write_text("\n".join(lines) + "\n", encoding="utf-8")
    record = {
        "schema_version": 1,
        "kind": "terrain",
        "resolution": [resolution, resolution],
        "dimensions_m": [width, depth],
        "elevation_m": [0, elevation],
        "bit_depth": 16,
        "encoding": "PGM P5 unsigned big-endian",
        "coordinates": "Y-up, X-east, Z-south; row zero is negative Z",
        "origin_m": [-width / 2, 0, -depth / 2],
        "tile_layout": [1, 1],
        "edge_heights_m": {"north": 0, "south": 0, "east": 0, "west": 0},
        "files": [file_record(root, p) for p in (pgm, mask, obj)],
        "provenance": "Original procedural fixture, MIT",
        "godot_review": "not_run",
    }
    write_json(root / "terrain.json", record)
    return record


def validate(record, root):
    from ..records import verify_file

    if (
        record.get("schema_version") != 1
        or record.get("bit_depth") != 16
        or record.get("tile_layout") != [1, 1]
    ):
        raise StudioError("Unsupported terrain record profile")
    for item in record["files"]:
        verify_file(root, item)
    data = (Path(root) / "height.pgm").read_bytes()
    header = (
        f"P5\n{record['resolution'][0]} {record['resolution'][1]}\n65535\n".encode()
    )
    if (
        not data.startswith(header)
        or len(data) - len(header)
        != record["resolution"][0] * record["resolution"][1] * 2
    ):
        raise StudioError("Terrain resolution/bit depth does not match heightfield")
    values = struct.unpack(
        ">" + "H" * ((len(data) - len(header)) // 2), data[len(header) :]
    )
    if min(values) != 0 or max(values) != 65535:
        raise StudioError("Heightfield does not span declared elevation range")
    n, m = record["resolution"]
    edges = (
        list(values[:n])
        + list(values[-n:])
        + list(values[::n])
        + list(values[n - 1 :: n])
    )
    if any(edges):
        raise StudioError("Local fixture tile has nonzero seams")
    return {"ok": True, "seams": "flat", "range": record["elevation_m"]}
