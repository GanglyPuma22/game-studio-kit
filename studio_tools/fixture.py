"""Compose a portable original Blender -> GLB/audio/terrain -> Godot project."""

from pathlib import Path
import shutil
from .common import StudioError, write_json, file_record, read_json
from .adapters import blender, audio, terrain
from . import __version__

TEMPLATE = Path(__file__).resolve().parent / "godot_template"


def create(config, project, source_fixture=None):
    root = Path(project)
    if any(root.iterdir()):
        raise StudioError(
            "Fixture needs an empty game project directory; existing work is preserved"
        )
    source = root / "source"
    source.mkdir()
    (source / ".gdignore").write_text("")
    if source_fixture:
        src = Path(source_fixture)
        if (
            not (src / "harbor-bell.blend").is_file()
            or not (src / "harbor-bell.glb").is_file()
        ):
            raise StudioError("Source fixture needs both editable .blend and GLB")
        for name in [
            "harbor-bell.blend",
            "harbor-bell.glb",
            "source-inspection.json",
            "roundtrip.json",
        ]:
            shutil.copy2(src / name, source / name)
        result = {
            "source": read_json(source / "source-inspection.json"),
            "roundtrip": read_json(source / "roundtrip.json"),
            "glb": blender.glb_info(source / "harbor-bell.glb"),
        }
    else:
        result = blender.fixture(config, source)
    assets = root / "assets"
    assets.mkdir()
    shutil.copy2(source / "harbor-bell.glb", assets / "harbor-bell.glb")
    for p in TEMPLATE.iterdir():
        if p.is_file():
            shutil.copy2(p, root / p.name)
    terrain.create(source / "terrain", resolution=33, width=4, depth=8, elevation=0.7)
    shutil.copy2(source / "terrain" / "terrain.obj", assets / "terrain.obj")
    cues = []
    for name, duration, loop in [("response", 0.8, False), ("ambience", 4, True)]:
        original = source / (name + ".wav")
        runtime = assets / (name + ".wav")
        audio.synthesize(original, duration=duration, kind=name)
        measured = audio.prepare(original, runtime, loop=loop)
        cues.append(
            {
                "event_id": "harbor." + name,
                "purpose": "Functional pipeline test " + name,
                "source": file_record(root, original),
                "runtime": file_record(root, runtime),
                "loop": loop,
                "loop_start_seconds": 0,
                "loop_end_seconds": measured["duration_seconds"],
                "bus": "Ambience" if loop else "SFX",
                "priority": 0 if loop else 10,
                "provenance": {
                    "author": "Game Studio Kit contributors",
                    "rights": "Original procedural test cue; MIT",
                    "provider": None,
                },
                "measured": measured,
                "listening": "not_run",
            }
        )
    write_json(
        root / "audio-cues.json",
        {"schema_version": 1, "kind": "audio-cues", "cues": cues},
    )
    write_json(
        root / "project.json",
        {
            "schema_version": 1,
            "kind": "project",
            "project_id": "harbor-pocket",
            "engine": {"name": "Godot", "version": "4.5.1"},
            "target_platform": "desktop",
            "settings": {
                "renderer": "gl_compatibility",
                "viewport": [1280, 720],
                "camera_fov_degrees": 70,
            },
            "input_route": "WASD/arrows; click and mouse look; E within 3 metres; Escape releases mouse",
            "references": [],
            "artifact_root": "artifacts",
            "current_candidate": None,
            "workflow_version": __version__,
        },
    )
    write_json(
        root / "asset.json",
        {
            "schema_version": 1,
            "kind": "asset",
            "asset_id": "harbor-bell",
            "stage": "exported",
            "source": [file_record(root, source / "harbor-bell.blend")],
            "runtime": [file_record(root, assets / "harbor-bell.glb")],
            "units": "metres",
            "dimensions_m": result["roundtrip"]["dimensions_m"],
            "pivot": "ground center; Blender Z up, exported glTF Y up",
            "materials": result["roundtrip"]["material_names"],
            "collision": "decorative; walkable terrain is separate",
            "animated": True,
            "rig": {"bones": ["Root", "Frond"], "body_type": "nonhumanoid"},
            "clips": result["source"]["clips"],
            "provenance": {
                "author": "Game Studio Kit contributors",
                "rights": "Original procedural fixture; MIT",
            },
            "review_links": [],
        },
    )
    return {
        "project": "harbor-pocket",
        "status": "exported",
        "asset": result["glb"],
        "next_step": "godot import, then godot smoke; native visual, motion and listening review remain separate",
    }
