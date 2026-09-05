"""Every mutation has an explicit game/project or output destination."""

import argparse
import json
from pathlib import Path
import sys
from .common import StudioError, read_json, write_json, output_root, relative
from .config import load


def parser():
    p = argparse.ArgumentParser(
        prog="studio",
        description="Portable game studio helpers; no implicit installs or paid calls",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def command(name, project=False):
        c = sub.add_parser(name)
        c.add_argument("--config")
        if project:
            c.add_argument(
                "--project",
                required=True,
                help="Explicit game/output root outside the toolkit",
            )
        return c

    c = command("check-package")
    c.add_argument("--root", required=True)
    c = command("doctor")
    c.add_argument("--output")
    c = command("setup")
    c.add_argument("--report")
    c.add_argument("--output")
    c = command("validate-record", True)
    c.add_argument("--record", required=True)
    c = command("fixture", True)
    c.add_argument(
        "--source-fixture",
        help="Reuse a previously generated and inspected original fixture directory",
    )
    c = command("blender", True)
    c.add_argument("operation", choices=["fixture", "inspect", "export", "render"])
    c.add_argument("--source")
    c.add_argument("--collection")
    c.add_argument("--camera")
    c.add_argument("--frames", default="1")
    c.add_argument("--angles", default="0")
    c.add_argument("--target", default="0,0,0")
    c.add_argument("--output", default="artifacts/blender")
    c = command("terrain", True)
    c.add_argument("--output", default="source/terrain")
    c.add_argument("--resolution", type=int, default=33)
    c.add_argument("--width", type=float, default=12)
    c.add_argument("--depth", type=float, default=12)
    c.add_argument("--elevation", type=float, default=0.7)
    c = command("audio", True)
    c.add_argument(
        "operation",
        choices=["local", "prepare", "measure", "effects", "speech", "music"],
    )
    c.add_argument("--output", default="assets/cue.wav")
    c.add_argument("--source")
    c.add_argument(
        "--kind", choices=["response", "ambience", "footstep"], default="response"
    )
    c.add_argument("--duration", type=float, default=0.8)
    c.add_argument("--start", type=float, default=0)
    c.add_argument("--end", type=float)
    c.add_argument("--gain-db", type=float, default=0)
    c.add_argument("--fade", type=float, default=0.01)
    c.add_argument("--loop", action="store_true")
    c.add_argument("--request")
    c.add_argument("--budget")
    c.add_argument("--provenance")
    c.add_argument("--record", default="artifacts/audio-task.json")
    c = command("meshy", True)
    c.add_argument("operation", choices=["submit", "observe", "reconcile", "archive"])
    c.add_argument(
        "--profile",
        choices=["image", "preview", "refine", "remesh", "retexture", "rig", "animate"],
    )
    c.add_argument("--request")
    c.add_argument("--budget")
    c.add_argument("--eligibility")
    c.add_argument("--record", required=True)
    c.add_argument("--task-id")
    c.add_argument("--output", default="source/provider-assets")
    c.add_argument("--attempts", type=int, default=1)
    c.add_argument("--interval", type=float, default=5)
    c = command("gaea", True)
    c.add_argument("--recipe", required=True)
    c.add_argument("--output", default="source/gaea-build")
    c = command("godot", True)
    c.add_argument("operation", choices=["import", "smoke", "run", "export"])
    c.add_argument("--output")
    c.add_argument("--preset")
    c = command("candidate", True)
    c.add_argument("--id", required=True)
    c.add_argument("--engine-version", default="4.5.1")
    c.add_argument("--output", default="artifacts/candidate.json")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result.get("ok", True) else 1
    except (StudioError, OSError, KeyError, TypeError, ValueError) as exc:
        # Only application errors deliberately constructed as safe strings are exposed.
        error = (
            str(exc)
            if isinstance(exc, StudioError)
            else "Input or filesystem error; check required parameters and project/config files"
        )
        print(json.dumps({"ok": False, "error": error}), file=sys.stderr)
        return 1


def dispatch(a):
    config = load(a.config)
    if a.command == "check-package":
        from .package import check

        return check(a.root)
    if a.command in {"doctor", "setup"}:
        from .doctor import inspect, setup

        result = (
            inspect(config)
            if a.command == "doctor"
            else setup(read_json(a.report) if a.report else inspect(config))
        )
        if a.output:
            dest = Path(a.output).resolve()
            output_root(dest.parent)
            write_json(dest, result)
        return result
    # Read-only validation does not create the project directory.
    root = (
        Path(a.project).resolve()
        if a.command == "validate-record"
        else output_root(a.project)
    )

    def path(name):
        return relative(root, name)

    if a.command == "validate-record":
        from .records import validate

        return validate(read_json(path(a.record)), root)
    if a.command == "fixture":
        from .fixture import create

        return create(config, root, a.source_fixture)
    if a.command == "blender":
        from .adapters import blender

        out = path(a.output)
        if a.operation == "fixture":
            return blender.fixture(config, out)
        if not a.source:
            raise StudioError(
                "Blender operation requires --source relative to the project"
            )
        if a.operation == "inspect":
            return blender.inspect(config, path(a.source), out)
        if a.operation == "render":
            return blender.render(
                config, path(a.source), out, a.camera, a.frames, a.angles, a.target
            )
        if not a.collection:
            raise StudioError("Blender export requires --collection")
        return blender.export(config, path(a.source), a.collection, out)
    if a.command == "terrain":
        from .adapters.terrain import create

        return create(path(a.output), a.resolution, a.width, a.depth, a.elevation)
    if a.command == "audio":
        from .adapters import audio

        if a.operation == "local":
            return audio.synthesize(path(a.output), a.duration, kind=a.kind)
        if a.operation in {"prepare", "measure"}:
            if not a.source:
                raise StudioError("Audio operation requires --source")
            if a.operation == "measure":
                return audio.measure(path(a.source))
            return audio.prepare(
                path(a.source),
                path(a.output),
                a.start,
                a.end,
                a.gain_db,
                a.fade,
                a.loop,
            )
        from .adapters.elevenlabs import generate

        if not all([a.request, a.budget, a.provenance]):
            raise StudioError(
                "Hosted audio needs --request, --budget and --provenance JSON files"
            )
        return generate(
            config,
            a.operation,
            read_json(path(a.request)),
            path(a.record),
            path(a.output),
            read_json(path(a.budget)),
            read_json(path(a.provenance)),
        )
    if a.command == "meshy":
        from .adapters import meshy

        record = path(a.record)
        if a.operation == "submit":
            if not all([a.profile, a.request, a.budget]):
                raise StudioError(
                    "Meshy submit needs --profile, --request and --budget"
                )
            return meshy.submit(
                config,
                a.profile,
                read_json(path(a.request)),
                record,
                read_json(path(a.budget)),
                read_json(path(a.eligibility)) if a.eligibility else None,
            )
        if a.operation == "observe":
            return meshy.poll(config, record, a.attempts, a.interval)
        if a.operation == "reconcile":
            return meshy.attach_task(record, a.task_id)
        return meshy.archive(record, path(a.output))
    if a.command == "gaea":
        from .adapters.gaea import build

        return build(config, read_json(path(a.recipe)), path(a.output))
    if a.command == "godot":
        from .adapters.godot import execute

        return execute(
            config, root, a.operation, path(a.output) if a.output else None, a.preset
        )
    if a.command == "candidate":
        from .evidence import new_candidate
        from . import __version__

        result = new_candidate(root, a.id, a.engine_version, __version__)
        if not a.output.startswith("artifacts/"):
            raise StudioError(
                "Candidate record belongs under artifacts/ so it cannot hash itself"
            )
        write_json(path(a.output), result)
        return result
    raise StudioError("Unknown command")
