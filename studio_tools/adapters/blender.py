"""Owned background Blender execution and GLB structural inspection."""

import json
from pathlib import Path
import struct
from ..common import StudioError, read_json, sha256
from ..config import require_executable, app_path
from ..processes import run

SCRIPTS = Path(__file__).resolve().parents[1] / "blender_scripts"


def command(config, script, args=(), source=None):
    path = SCRIPTS / script
    if not path.is_file():
        raise StudioError("Unknown packaged Blender script")
    cmd = [require_executable(config, "blender"), "--background", "--factory-startup"]
    if source:
        cmd.append(app_path(config, source, "blender"))
    cmd += [
        "--python-exit-code",
        "1",
        "--python",
        app_path(config, path, "blender"),
        "--",
        *[str(a) for a in args],
    ]
    return cmd


def glb_info(path):
    data = Path(path).read_bytes()
    from .http import validate_download

    validate_download(path, ".glb")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A or length + 20 > len(data):
        raise StudioError("GLB JSON chunk is invalid")
    doc = json.loads(data[20 : 20 + length])
    meshes = doc.get("meshes", [])
    animations = doc.get("animations", [])
    if not meshes:
        raise StudioError("GLB has no mesh")
    clips = []
    for clip in animations:
        times = [
            doc["accessors"][sampler["input"]] for sampler in clip.get("samplers", [])
        ]
        clips.append(
            {
                "name": clip.get("name"),
                "duration_seconds": max(
                    (t.get("max", [0])[0] for t in times), default=0
                )
                - min((t.get("min", [0])[0] for t in times), default=0),
                "channels": len(clip.get("channels", [])),
            }
        )
    return {
        "mesh_count": len(meshes),
        "material_count": len(doc.get("materials", [])),
        "skin_count": len(doc.get("skins", [])),
        "node_count": len(doc.get("nodes", [])),
        "clips": clips,
        "generator": doc.get("asset", {}).get("generator"),
    }


def fixture(config, root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if (root / "harbor-bell.blend").exists():
        raise StudioError(
            "Blender fixture already exists; choose a new output or inspect it"
        )
    run(
        command(config, "fixture.py", [app_path(config, root, "blender")]),
        timeout=max(config["timeout"], 300),
        log=root / "blender-create.log",
        hide_window=True,
    )
    info = inspect(config, root / "harbor-bell.glb", root / "roundtrip.json")
    glb = glb_info(root / "harbor-bell.glb")
    names = {c["name"] for c in glb["clips"]}
    if (
        not {"idle", "response"} <= names
        or glb["skin_count"] < 1
        or glb["material_count"] < 3
        or info["mesh_count"] < 4
        or set(info["bone_names"]) != {"Root", "Frond"}
    ):
        raise StudioError(
            "Animated fixture round trip lost expected clips, skin, materials or geometry"
        )
    return {
        "source": read_json(root / "source-inspection.json"),
        "roundtrip": info,
        "glb": glb,
    }


def inspect(config, source, output):
    source = Path(source)
    output = Path(output)
    if not source.is_file():
        raise StudioError("Blender inspection input is missing")
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        command(
            config,
            "inspect.py",
            [app_path(config, source, "blender"), app_path(config, output, "blender")],
        ),
        timeout=config["timeout"],
        log=output.with_suffix(".log"),
        hide_window=True,
    )
    return read_json(output)


def export(config, source, collection, output):
    if not Path(source).is_file():
        raise StudioError("Editable Blender source is missing")
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or source.suffix.lower() != ".blend" or output.suffix.lower() != ".glb":
        raise StudioError("Export needs distinct .blend source and .glb destination")
    destinations = [output, output.with_suffix(".export.log"),
                    output.with_suffix(".inspection.json"), output.with_suffix(".inspection.log")]
    if any(p.exists() and p.samefile(source) for p in destinations):
        raise StudioError("Export output and metadata must not alias editable source")
    source_hash = sha256(source)
    run(
        command(
            config,
            "export.py",
            [collection, app_path(config, output, "blender")],
            source,
        ),
        timeout=config["timeout"],
        log=Path(output).with_suffix(".export.log"),
        hide_window=True,
    )
    if sha256(source) != source_hash:
        raise StudioError("Editable source changed during export; inspect source before continuing")
    return {
        "source": {"name": source.name, "sha256": source_hash, "operation": "export_edited_source"},
        "glb": glb_info(output),
        "roundtrip": inspect(
            config, output, Path(output).with_suffix(".inspection.json")
        ),
    }


def render(config, source, output, camera, frames="1", angles="0", target="0,0,0"):
    source, output = Path(source), Path(output)
    if not source.is_file() or not camera:
        raise StudioError("Render needs an editable source and named review camera")
    try:
        frame_values = [int(v) for v in frames.split(",")]
        angle_values = [float(v) for v in angles.split(",")]
        target_values = [float(v) for v in target.split(",")]
        import math

        if len(target_values) != 3 or not all(
            math.isfinite(v) for v in angle_values + target_values
        ):
            raise ValueError()
        if not 1 <= len(frame_values) * len(angle_values) <= 120:
            raise ValueError()
    except ValueError:
        raise StudioError(
            "Render needs comma-separated frames/angles, a three-number target and 1–120 samples"
        ) from None
    if output.exists() and any(output.iterdir()):
        raise StudioError("Render needs a new empty evidence directory")
    output.mkdir(parents=True, exist_ok=True)
    run(
        command(
            config,
            "render.py",
            [app_path(config, output, "blender"), camera, frames, angles, target],
            source,
        ),
        timeout=config["timeout"],
        log=output / "blender-render.log",
        hide_window=True,
    )
    result = read_json(output / "renders.json")
    from ..common import file_record

    for sample in result["samples"]:
        sample["artifact"] = file_record(output, output / sample["file"])
    return result
