"""Owned background Blender execution and GLB structural inspection."""

from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import uuid
from ..common import (
    StudioError,
    file_record,
    outside_package,
    read_json,
    relative,
    safe_id,
    sha256,
    write_json,
)
from ..config import require_executable, app_path
from ..processes import run

SCRIPTS = Path(__file__).resolve().parents[1] / "blender_scripts"
RUN_DEFAULT_TIMEOUT = 600
RUN_MAX_TIMEOUT = 3600
RUN_LIMITS = (
    "a clean exit is not visual acceptance: this records that the script ran headlessly "
    "and which declared files exist afterwards, never that the bake, export or repair "
    "looks right; stdout and stderr are combined in one log the script may fill with "
    "private data"
)


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


def _readable_digest(path):
    """Hash a file, reporting no digest instead of raising when it cannot be read."""
    try:
        return sha256(path)
    except OSError:
        return None


def script_run(
    config, project, *, source, script, label=None, timeout=None, results=(), passthrough=()
):
    """Run a project-owned script inside a project-owned .blend, once, with receipts.

    The packaged operations above run scripts this kit ships. This one runs the
    bake, export or mesh-repair script the game project owns, which is why it
    takes a source and a script rather than an operation name. It returns a
    verdict instead of raising on a failed or timed-out run, so the receipts
    that explain the run are always written and readable.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Blender run needs an existing game project directory")
    blend = relative(root, source)
    if not blend.is_file() or blend.suffix.lower() != ".blend":
        raise StudioError("Blender run needs an existing .blend --source relative to the project")
    program = relative(root, script)
    if not program.is_file() or program.suffix.lower() != ".py":
        raise StudioError("Blender run needs an existing .py --script relative to the project")
    limit = RUN_DEFAULT_TIMEOUT if timeout is None else timeout
    if type(limit) not in (int, float) or not 0 < limit <= RUN_MAX_TIMEOUT:
        raise StudioError("Blender run timeout must be 1–3600 seconds")
    extra = list(passthrough)
    # argparse hands the separator over with the remainder; Blender gets its own.
    if extra[:1] == ["--"]:
        extra = extra[1:]
    if not all(isinstance(item, str) for item in extra):
        raise StudioError("Passthrough arguments must be strings")
    label = safe_id(label) if label else uuid.uuid4().hex
    executable = Path(require_executable(config, "blender"))
    # The run directory is contained like a declared result: a symlinked
    # artifacts/ must not move these receipts out of the project or into the kit.
    run_dir = outside_package(relative(root, f"artifacts/blender/runs/{label}"))
    expected = []
    results_before = []
    for item in results:
        target = relative(root, item)
        if target == run_dir or target.is_relative_to(run_dir):
            # run.json, the process record and the log are written here:
            # declaring one as a required result would let a script that
            # produced nothing still be reported as ok.
            raise StudioError("Declared results must not be files this runner writes")
        expected.append(item)
        # A result that already exists with the same bytes after the run was
        # not produced by it: yesterday's bake would otherwise pass for today's.
        present = target.is_file()
        results_before.append({
            "path": item, "present": present,
            "sha256": _readable_digest(target) if present else None,
        })
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Blender run directory exists; choose a new label") from None
    args = [
        str(executable),
        "--background",
        "--factory-startup",
        app_path(config, blend, "blender"),
        "--python-exit-code",
        "1",
        "--python",
        app_path(config, program, "blender"),
        "--",
        *extra,
    ]
    identity = {
        "blender": {"path": str(executable), "sha256": _readable_digest(executable)},
        "source": file_record(root, blend),
        "script": file_record(root, program),
    }
    started = datetime.now(timezone.utc)
    failure = None
    try:
        run(
            args, cwd=str(root), timeout=float(limit),
            hide_window=True, job_dir=run_dir / "process",
        )
    except StudioError as exc:
        # A nonzero exit or a timeout is this command's answer, not its crash.
        failure = str(exc)
    record_path = run_dir / "process" / "process.json"
    record = read_json(record_path) if record_path.is_file() else {"status": "start_failed"}
    log_path = run_dir / "process" / "stdout.log"
    before = {entry["path"]: entry for entry in results_before}
    result_files = []
    for item in expected:
        try:
            target = relative(root, item)
        except StudioError:
            # A declared result that only now resolves outside the project (a
            # symlink the script created) is not evidence of this run.
            result_files.append({"path": item, "present": False, "stale": False,
                                 "unreadable": False, "sha256": None})
            continue
        exists = target.is_file()
        digest = _readable_digest(target) if exists else None
        # A result this runner cannot read cannot be shown to be new output.
        unreadable = exists and digest is None
        prior = before.get(item, {"present": False, "sha256": None})
        stale = exists and not unreadable and prior["present"] and prior["sha256"] == digest
        result_files.append({
            "path": item, "present": exists and not stale and not unreadable,
            "stale": stale, "unreadable": unreadable, "sha256": digest,
        })
    status = record.get("status", "start_failed")
    if failure is None and not all(entry["present"] for entry in result_files):
        stale_paths = [e["path"] for e in result_files if e["stale"]]
        unreadable_paths = [e["path"] for e in result_files if e["unreadable"]]
        missing_paths = [e["path"] for e in result_files
                         if not e["present"] and not e["stale"] and not e["unreadable"]]
        if stale_paths:
            failure = ("Declared results are unchanged since before the run, so this run "
                       "did not produce them: " + ", ".join(stale_paths))
        elif unreadable_paths:
            failure = "Declared results cannot be read: " + ", ".join(unreadable_paths)
        else:
            failure = "Declared results are missing after the run: " + ", ".join(missing_paths)
    receipt = {
        "schema_version": 1,
        "kind": "blender-run",
        "label": label,
        **identity,
        "passthrough_count": len(extra),
        "results_before": results_before,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "returncode": record.get("returncode"),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "timed_out": status == "timed_out",
        "cleanup": record.get("cleanup"),
        "result_files": result_files,
        "failure": failure,
        "ok": (
            status == "completed"
            and record.get("returncode") == 0
            and all(entry["present"] for entry in result_files)
        ),
        "limits": RUN_LIMITS,
    }
    write_json(run_dir / "run.json", receipt)
    return {
        **receipt,
        "run_dir": str(run_dir),
        "run_record": str(run_dir / "run.json"),
        "process_record": str(record_path) if record_path.is_file() else None,
        "log": str(log_path) if log_path.is_file() else None,
    }
