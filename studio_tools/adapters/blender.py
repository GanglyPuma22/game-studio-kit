"""Owned background Blender execution and GLB structural inspection."""

from datetime import datetime, timezone
import json
import os
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
from ..blender_scripts.topology import clean as topology_clean
from ..config import require_executable, app_path
from ..processes import run, stop_survivors

SCRIPTS = Path(__file__).resolve().parents[1] / "blender_scripts"
RUN_DEFAULT_TIMEOUT = 600
RUN_MAX_TIMEOUT = 3600
RUN_LIMITS = (
    "a clean exit is not visual acceptance: this records that the script ran headlessly "
    "and which declared files this run produced, never that the bake, export or repair "
    "looks right; stdout and stderr are combined in one log the script may fill with "
    "private data; descendants are enumerated by process group (POSIX) or parent walk "
    "(Windows), so a process that re-parented out of both is not seen"
)
REDUCE_TIMEOUT = 1800
REDUCE_MIN_TRIANGLES = 100
REDUCE_MAX_TRIANGLES = 5_000_000
REDUCE_LIMITS = (
    "a clean topology audit is not visual acceptance: this records that the saved mesh "
    "reaches the requested triangle budget with no boundary, nonmanifold or "
    "inconsistently wound edges, never that the silhouette, UVs, underside detail or "
    "material response still read correctly; nothing here fills a hole or closes an "
    "opening, so an intentional walk-through gap stays open and is counted as boundary "
    "edges, and collision remains a separate simplified surface, never this mesh"
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
    blender_digest = _readable_digest(executable)
    if blender_digest is None:
        # Without a digest there is no identity to record or to re-check below.
        raise StudioError("Blender executable could not be read to record its identity")
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
        digest = _readable_digest(target) if present else None
        if present and digest is None:
            # Without a baseline there is nothing to compare the run's output
            # against, so a file the script merely made readable would pass for
            # one it wrote. Refuse now rather than report an unprovable ok.
            raise StudioError(
                "Declared result exists but cannot be read before the run, so this run "
                "could not be shown to have produced it: " + item
            )
        results_before.append({"path": item, "present": present, "sha256": digest})
    script_digest = sha256(program)
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise StudioError("Blender run directory exists; choose a new label") from None
    # Blender runs the script where the project keeps it, so a script that
    # resolves its siblings through __file__ finds them. That means the file can
    # change between the digest above and the process below, or while it runs,
    # so it is read again after the process ends and both hashes are recorded.
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
        "blender": {"path": str(executable), "sha256": blender_digest},
        "source": file_record(root, blend),
        "script": {
            "path": program.relative_to(root).as_posix(),
            "sha256": script_digest,
            "sha256_after_exit": None,
        },
    }
    started = datetime.now(timezone.utc)
    failure = None
    interrupt = None
    record = {"status": "start_failed"}
    left = None
    result_files = []
    # The digest above described bytes that could have been replaced while this
    # run was prepared, so the executable is read again here: only the verified
    # identity may start, and a mismatch is a receipt rather than a launch.
    if _readable_digest(executable) != blender_digest:
        failure = (
            "Blender executable changed before the run; the verified identity did not start"
        )
        status = "refused"
    else:
        try:
            run(
                args, cwd=str(root), timeout=float(limit),
                hide_window=True, job_dir=run_dir / "process",
            )
        except StudioError as exc:
            # A nonzero exit or a timeout is this command's answer, not its crash.
            failure = str(exc)
        except KeyboardInterrupt as exc:
            # The runner has already stopped its own child; the receipt for the
            # label this run reserved is still written, then the interrupt goes on.
            interrupt = exc
            failure = "Blender run interrupted before the script finished"
        record_path = run_dir / "process" / "process.json"
        if record_path.is_file():
            record = read_json(record_path)
        try:
            if interrupt is None and record.get("pid") and record.get("status") != "timed_out":
                # The runner stops the tree itself on timeout; otherwise Blender
                # exited on its own and whatever its script spawned is still
                # this run's. Stop it before anything below is measured: a bake
                # helper still running could rewrite a result after its digest.
                left = stop_survivors(
                    record["pid"], hide_window=True,
                    ownership=record.get("windows_ownership"),
                )
                if left.get("unverified"):
                    # These were left running on purpose: this run's evidence
                    # does not show they are its own, so they are not its to kill.
                    failure = failure or (
                        "Processes under this run could not be attributed to it and were "
                        "left running: "
                        + ", ".join(str(entry["pid"]) for entry in left["unverified"])
                    )
                elif left["pids"]:
                    failure = failure or (
                        "Processes from this run outlived Blender; "
                        + ("they were stopped" if left["stopped"]
                           else "stopping them could not be verified")
                    )
                elif left["status"] != "ok":
                    failure = failure or (
                        "Processes from this run could not be enumerated on this host"
                    )
            identity["script"]["sha256_after_exit"] = _readable_digest(program)
            result_files = _run_results(root, run_dir, expected, results_before)
        except KeyboardInterrupt as exc:
            # An interrupt after the process started must still leave a receipt:
            # the label is reserved and something ran under it.
            interrupt = exc
            failure = failure or "Blender run interrupted before its receipts were complete"
        status = "interrupted" if interrupt is not None else record.get("status", "start_failed")
    # Whatever was not reached above is reported as not produced, never as absent
    # from the receipt: a partial account of declared results is still an account.
    result_files += [
        {"path": item, "present": False, "stale": False, "unreadable": False,
         "invalid": False, "sha256": None}
        for item in expected[len(result_files):]
    ]
    owned_tree_clear = left is None or (left["status"] == "ok" and not left["pids"])
    script_changed = (
        identity["script"]["sha256_after_exit"] is not None
        and identity["script"]["sha256_after_exit"] != script_digest
    )
    if script_changed:
        failure = failure or "script changed during the run"
    if failure is None and not all(entry["present"] for entry in result_files):
        stale_paths = [e["path"] for e in result_files if e["stale"]]
        unreadable_paths = [e["path"] for e in result_files if e["unreadable"]]
        invalid_paths = [e["path"] for e in result_files if e["invalid"]]
        missing_paths = [e["path"] for e in result_files
                         if not any((e["present"], e["stale"], e["unreadable"], e["invalid"]))]
        if stale_paths:
            failure = ("Declared results are unchanged since before the run, so this run "
                       "did not produce them: " + ", ".join(stale_paths))
        elif invalid_paths:
            failure = ("Declared results no longer resolve to a file this run could have "
                       "produced: " + ", ".join(invalid_paths))
        elif unreadable_paths:
            failure = "Declared results cannot be read: " + ", ".join(unreadable_paths)
        else:
            failure = "Declared results are missing after the run: " + ", ".join(missing_paths)
    log_path = run_dir / "process" / "stdout.log"
    record_path = run_dir / "process" / "process.json"
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
        "survivors": left,
        "result_files": result_files,
        "failure": failure,
        "ok": (
            status == "completed"
            and record.get("returncode") == 0
            and all(entry["present"] for entry in result_files)
            and owned_tree_clear
            and not script_changed
        ),
        "limits": RUN_LIMITS,
    }
    write_json(run_dir / "run.json", receipt)
    if interrupt is not None:
        raise interrupt
    return {
        **receipt,
        "run_dir": str(run_dir),
        "run_record": str(run_dir / "run.json"),
        "process_record": str(record_path) if record_path.is_file() else None,
        "log": str(log_path) if log_path.is_file() else None,
    }


def _run_results(root, run_dir, expected, results_before):
    """Describe each declared result now that the run and its tree are over.

    Containment is checked again here, not only before the run: a script can
    replace a declared result with a symlink to this runner's own log, and the
    bytes of a file this runner wrote are not evidence that the script produced
    anything.
    """
    before = {entry["path"]: entry for entry in results_before}
    result_files = []
    for item in expected:
        entry = {"path": item, "present": False, "stale": False,
                 "unreadable": False, "invalid": False, "sha256": None}
        try:
            target = relative(root, item)
        except StudioError:
            # A declared result that only now resolves outside the project (a
            # symlink the script created) is not evidence of this run.
            entry["invalid"] = True
            result_files.append(entry)
            continue
        if target == run_dir or target.is_relative_to(run_dir):
            entry["invalid"] = True
            result_files.append(entry)
            continue
        exists = target.is_file()
        digest = _readable_digest(target) if exists else None
        # A result this runner cannot read cannot be shown to be new output.
        unreadable = exists and digest is None
        prior = before.get(item, {"present": False, "sha256": None})
        stale = exists and not unreadable and prior["present"] and prior["sha256"] == digest
        entry.update(present=exists and not stale and not unreadable,
                     stale=stale, unreadable=unreadable, sha256=digest)
        result_files.append(entry)
    return result_files


def reduce_mesh(
    config, project, *, source, target_triangles, output, object_name=None, label=None
):
    """Reduce a mesh locally from an intact original, and qualify the result.

    Measured on one hero tree and one creature: a provider remesh to 120k
    triangles returned 91 boundary and 87 nonmanifold edges, and an image-to-3d
    request for 30k triangles returned 83 boundary and 90 nonmanifold edges,
    while a local weld-and-decimate of the same intact 4.85M-triangle original
    down to 300k returned none of the three defects and better underside detail,
    for no credits. So this exists to make the local path the cheap one to take.

    It reduces and audits; it never repairs. `ok` is true only when the source
    was already clean and the saved mesh still is: a reduction that starts from
    a defective mesh cannot qualify it, and one that introduces a defect has
    failed even if it hit the triangle budget.
    """
    root = Path(project).resolve()
    if not root.is_dir():
        raise StudioError("Blender reduce needs an existing game project directory")
    original = relative(root, source)
    if not original.is_file() or original.suffix.lower() not in {".blend", ".glb"}:
        raise StudioError(
            "Blender reduce needs an existing .blend or .glb --source relative to the project"
        )
    if type(target_triangles) is not int or not (
        REDUCE_MIN_TRIANGLES <= target_triangles <= REDUCE_MAX_TRIANGLES
    ):
        raise StudioError(
            f"Blender reduce --target-triangles must be "
            f"{REDUCE_MIN_TRIANGLES}–{REDUCE_MAX_TRIANGLES}"
        )
    destination = outside_package(relative(root, output))
    if destination.suffix.lower() != ".blend":
        raise StudioError("Blender reduce --output must be a .blend this command writes")
    if object_name is not None and (not isinstance(object_name, str) or not object_name):
        raise StudioError("Blender reduce --object must name one mesh object")
    label = safe_id(label) if label else uuid.uuid4().hex
    # Everything that can be refused is refused before anything is created: a
    # host without Blender configured must not leave a reservation or a receipt
    # directory behind for a reduction that never started.
    executable = Path(require_executable(config, "blender"))
    blender_digest = _readable_digest(executable)
    if blender_digest is None:
        # Without a digest there is no identity to record or to re-check below.
        raise StudioError("Blender executable could not be read to record its identity")
    # The source as it was before launch is the record; comparing to it
    # afterwards is what proves the reduction did not edit its own input.
    source_record = file_record(root, original)
    # Two reductions with different labels and the same --output would both
    # test-then-save and the second would silently overwrite the first. The
    # destination is claimed here, in one atomic step, and Blender saves over
    # the claim. Testing for the file and hoping is the bug this replaces.
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.close(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    except FileExistsError:
        # The intact original is the asset; overwriting a .blend to save a
        # reduction is how the thing worth keeping gets lost.
        raise StudioError("Blender reduce --output already exists; choose a new file") from None
    except OSError as exc:
        raise StudioError("Blender reduce --output could not be created") from exc
    reduce_dir = outside_package(relative(root, f"artifacts/blender/reduce/{label}"))
    try:
        reduce_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        # The claim belongs to a reduction that is not going to happen.
        destination.unlink(missing_ok=True)
        raise StudioError("Blender reduce directory exists; choose a new label") from None
    audit_path = reduce_dir / "audit.json"
    started = datetime.now(timezone.utc)
    failure = None
    interrupt = None
    record = {"status": "start_failed"}
    blender_after = None
    # The digest above described bytes that could have been replaced while this
    # reduction was prepared, so the executable is read again here: only the
    # verified identity may start, and a mismatch is a receipt, not a launch.
    if _readable_digest(executable) != blender_digest:
        failure = (
            "Blender executable changed before the reduction; "
            "the verified identity did not start"
        )
        status = "refused"
    else:
        try:
            run(
                command(
                    config,
                    "reduce.py",
                    [
                        app_path(config, original, "blender"),
                        str(target_triangles),
                        app_path(config, destination, "blender"),
                        app_path(config, audit_path, "blender"),
                        object_name or "",
                    ],
                ),
                cwd=str(root),
                timeout=float(max(config["timeout"], REDUCE_TIMEOUT)),
                hide_window=True,
                job_dir=reduce_dir / "process",
            )
        except StudioError as exc:
            # A failed or timed-out reduction is this command's answer, not a
            # crash: the receipt explaining it is more useful than the exception.
            failure = str(exc)
        except KeyboardInterrupt as exc:
            # The runner has already stopped its own child; the receipt for the
            # label and the destination this run claimed is still written, and
            # then the interrupt goes on.
            interrupt = exc
            failure = "Blender reduce interrupted before the reduction finished"
        record_path = reduce_dir / "process" / "process.json"
        if record_path.is_file():
            record = read_json(record_path)
        blender_after = _readable_digest(executable)
        status = "interrupted" if interrupt is not None else record.get("status", "start_failed")
    audit = None
    if audit_path.is_file():
        try:
            audit = read_json(audit_path)
        except StudioError:
            audit = None
    # An untouched claim is an empty file: it is this command's reservation, not
    # a reduction, and leaving it behind would block the retry.
    if destination.is_file() and destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
    saved = destination.is_file()
    before = (audit or {}).get("before")
    after = (audit or {}).get("after")
    objects = (audit or {}).get("objects", [])
    # A source that is gone or unreadable afterwards still gets a receipt; it
    # is the digest that is missing, not the reason to stop writing one.
    source_after = {
        "present": original.is_file(),
        "sha256": _readable_digest(original) if original.is_file() else None,
    }
    empty = [
        entry.get("index")
        for entry in objects
        if not (entry.get("before") or {}).get("triangles")
        or not (entry.get("after") or {}).get("triangles")
    ]
    over = [
        (entry.get("index"), (entry.get("after") or {}).get("triangles"))
        for entry in objects
        if ((entry.get("after") or {}).get("triangles") or 0) > target_triangles
    ]
    if status == "interrupted":
        reason = "the reduction was interrupted; nothing here was qualified"
    elif status != "completed" or record.get("returncode") != 0:
        reason = failure if status == "refused" else "Blender did not complete the reduction; read the log"
    elif blender_after != blender_digest:
        reason = (
            "the Blender executable changed while it ran: "
            f"{blender_digest} before, {blender_after or 'unreadable'} after; "
            "the binary that produced this mesh is not the one that was recorded"
        )
    elif source_after["sha256"] != source_record["sha256"]:
        reason = (
            "source changed or became unreadable during reduction: "
            f"{source_record['sha256']} before, {source_after['sha256'] or 'unreadable'} "
            "after; reduce from an untouched archived original"
        )
    elif audit is None:
        reason = "no topology audit was written; the reduction did not run to completion"
    elif audit.get("status") != "measured":
        reason = audit.get("reason") or "topology could not be measured"
    elif not objects:
        reason = "nothing was reduced: no mesh object was selected"
    elif empty:
        # A mesh with no triangles reports zero of every defect, which is not
        # the same thing as a mesh that was qualified.
        reason = "nothing was reduced: objects {} hold no triangles before or after".format(
            ", ".join(str(index) for index in empty)
        )
    elif not topology_clean(before):
        reason = "source topology not clean; reduction cannot qualify it"
    elif not saved:
        reason = "no reduced .blend was saved"
    elif not topology_clean(after):
        reason = (
            "reduction introduced boundary, nonmanifold or inconsistently wound edges, "
            "or a nonmanifold vertex"
        )
    elif over:
        reason = "over target: " + "; ".join(
            f"object {index} holds {count} triangles against a target of {target_triangles}"
            for index, count in over
        )
    else:
        reason = None
    receipt = {
        "schema_version": 1,
        "kind": "blender-reduce",
        "label": label,
        "blender": {
            "path": str(executable),
            "sha256": blender_digest,
            "sha256_after_exit": blender_after,
        },
        "source": source_record,
        "source_after": source_after,
        "output": {
            # Blender saved over the claim this command made before launch;
            # there is no staging copy and no other path was written.
            "path": destination.relative_to(root).as_posix(),
            "reserved_before_launch": True,
            "present": saved,
            "sha256": _readable_digest(destination) if saved else None,
        },
        "target_triangles": target_triangles,
        "object_selected": object_name is not None,
        "weld_distance": (audit or {}).get("weld_distance"),
        "scenes": (audit or {}).get("scenes"),
        "objects": objects,
        "before": before,
        "after": after,
        "ratio": (audit or {}).get("ratio"),
        "saved": saved,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "returncode": record.get("returncode"),
        "elapsed_seconds": record.get("elapsed_seconds"),
        "timed_out": status == "timed_out",
        "failure": failure,
        "ok": reason is None,
        "reason": reason,
        "limits": REDUCE_LIMITS,
    }
    write_json(reduce_dir / "reduce.json", receipt)
    if interrupt is not None:
        raise interrupt
    return {
        **receipt,
        "reduce_dir": str(reduce_dir),
        "reduce_record": str(reduce_dir / "reduce.json"),
        "audit_record": str(audit_path) if audit_path.is_file() else None,
        "log": str(reduce_dir / "process" / "stdout.log")
        if (reduce_dir / "process" / "stdout.log").is_file()
        else None,
    }
