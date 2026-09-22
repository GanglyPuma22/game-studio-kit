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

    def command(name, project=False, config_required=False):
        c = sub.add_parser(name)
        c.add_argument("--config", required=config_required)
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
    c = command("launch", True)
    c.description = (
        "Run the engine once for a project-owned script and return one verdict. "
        "The command blocks until the engine exits, for up to --timeout seconds, "
        "so the caller's harness must be told to wait at least that long."
    )
    c.add_argument("--sha256", required=True, help="Expected SHA-256 of executables.godot from the host config")
    # Defaults live in dispatch rather than here, so a profile can supply a
    # value and an explicitly typed flag can still be told apart from silence.
    c.add_argument("--mode", choices=["import", "test", "check", "native"], default=None,
                   help="Default import; a --profile may supply it instead")
    c.add_argument("--script", help="Engine script argument, for example res://tests/test_runner.gd")
    c.add_argument("--timeout", type=float, help="Seconds; defaults to host timeout, bounded by --cutoff-utc")
    c.add_argument("--cutoff-utc", help="ISO 8601 UTC instant after which no launch may start or run")
    c.add_argument("--label", help="Run identity under artifacts/launches; default is a new UUID")
    c.add_argument("--scope", help="Scope rung this launch is evidence for; persisted in the receipts")
    c.add_argument("--result", action="append", default=[], help="Project-relative file the run must produce")
    c.add_argument("--scrub-env", action="append", default=[], help="Environment prefix removed from the child")
    c.add_argument("--profile", help="Project-relative launch profile JSON; see templates/launch-profile.json")
    c.add_argument("--check", action="store_true",
                   help="Verify the profile's identity manifest and print the resolved argument "
                        "counts without launching anything")
    c.add_argument("passthrough", nargs=argparse.REMAINDER, help="-- and the arguments after it go to the engine unchanged")
    # Several launches, one blocking call. This is a command of its own rather
    # than a `launch` sub-verb because `launch`'s passthrough is a remainder
    # positional and argparse cannot put another positional in front of one.
    c = command("batch", True)
    c.description = (
        "Run the planned launches in order and return one verdict. The command "
        "blocks until the last run has finished, for up to --max-minutes (60 "
        "when omitted), so the caller's harness must be told to wait at least "
        "that long."
    )
    c.add_argument("--plan", required=True, help="JSON plan listing the runs; see templates/batch-plan.json")
    c.add_argument("--sha256", required=True, help="Expected SHA-256 of executables.godot from the host config")
    c.add_argument("--label", help="Batch identity under artifacts/batches; default is a new UUID")
    c.add_argument("--max-minutes", type=float,
                   help="Total wall clock for the whole batch, separate from each run's own timeout; "
                        "default 60, maximum 1440")
    c.add_argument("--stop-on-first-failure", action="store_true",
                   help="Stop after the first run that is not ok; by default every run is attempted")
    # A remainder positional cannot follow another positional, so playtest nests
    # its operation the way bench does: `start` carries the engine passthrough,
    # and `collect` completes one attended session.
    playtest = sub.add_parser(
        "playtest",
        description=(
            "Play a build and collect the session. `start` blocks while a "
            "handoff or driven session runs, for up to --max-minutes (60 when "
            "omitted, uncapped for handoff at 0), so the caller's harness must "
            "be told to wait at least that long; an attended session is never "
            "waited for and is completed by one later collect."
        ),
    )
    ops = playtest.add_subparsers(dest="operation", required=True)
    c = ops.add_parser("start")
    c.add_argument("--config")
    c.add_argument("--project", required=True, help="Explicit game/output root outside the toolkit")
    c.add_argument("--sha256", required=True, help="Expected SHA-256 of executables.godot from the host config")
    c.add_argument("--session", choices=["handoff", "attended", "driven"], default=None,
                   help="handoff blocks until the player quits; attended returns for one later collect; "
                        "driven runs a harness. Default handoff; a --profile may supply it instead")
    c.add_argument("--scene", help="res:// scene to play; omitted plays the project's main scene")
    c.add_argument("--script", help="Harness script for --session driven, for example res://tests/route.gd")
    c.add_argument("--label", help="Run identity under artifacts/playtests; default is a new UUID")
    c.add_argument("--max-minutes", type=float,
                   help="Session cap in minutes; 0 runs until the player quits. "
                        "Default 60, except attended, which is never waited for and cannot be capped")
    c.add_argument("--result", action="append", default=[], help="Project-relative file a driven harness must produce")
    c.add_argument("--scrub-env", action="append", default=[], help="Environment prefix removed from the child")
    c.add_argument("--rendering-method", choices=["forward_plus", "mobile", "gl_compatibility"],
                   help="Override the renderer; default is whatever the project declares")
    c.add_argument("--resolution", help="Override the window size as WIDTHxHEIGHT; "
                                        "default is whatever the project declares")
    c.add_argument("--use-host-profile", action="store_true",
                   help="Play on the real user profile so saves and settings persist")
    c.add_argument("--no-launcher", action="store_true", help="Skip the re-runnable relaunch script")
    c.add_argument("--cutoff-utc", help="ISO 8601 UTC instant after which no playtest may start or run")
    c.add_argument("--profile", help="Project-relative launch profile JSON; see templates/launch-profile.json")
    c.add_argument("--check", action="store_true",
                   help="Verify the profile's identity manifest and print the resolved argument "
                        "counts without launching anything")
    c.add_argument("passthrough", nargs=argparse.REMAINDER, help="-- and the arguments after it go to the engine unchanged")
    c = ops.add_parser("collect")
    c.add_argument("--config")
    c.add_argument("--project", required=True, help="Explicit game/output root outside the toolkit")
    c.add_argument("--label", required=True, help="The attended session to complete, exactly once")
    c = command("evidence")
    c.add_argument("operation", choices=["launches", "verify"])
    c.add_argument("run_root", nargs="?", help="Run root to index; `launches` only")
    c.add_argument("--output", help="Inventory JSON path; default is a dated file under the run root")
    c.add_argument("--receipt", help="Receipt whose recorded result files are re-hashed; `verify` only")
    c.add_argument("--project", help="Project root the receipt's recorded paths are relative to")
    # A remainder positional cannot follow another positional, so bench nests its operation.
    bench = sub.add_parser("bench")
    c = bench.add_subparsers(dest="operation", required=True).add_parser("cleanroom")
    c.add_argument("--config")
    c.add_argument("--project", required=True, help="Explicit game/output root outside the toolkit")
    c.add_argument("--label", help="Bench identity under artifacts/bench; default is a new UUID")
    c.add_argument("--scope", help="Scope rung this bench is evidence for; persisted in the receipt")
    c.add_argument("--settle", type=float, default=0.0, help="Seconds to wait before the first snapshot")
    c.add_argument("--sample-interval", type=float, default=10.0, help="Seconds between mid-window process samples; 1-60")
    c.add_argument("--agent-log", help="Agent activity log; timestamps inside the window break attribution")
    c.add_argument("--timeout", type=float, help="Capture timeout in seconds; default 3600")
    c.add_argument("--busy-fraction", type=float, default=0.05, help="CPU seconds per window second that count as busy")
    c.add_argument("--busy-floor-seconds", type=float, default=1.0)
    c.add_argument("--heavy-working-set-mb", type=float, default=200.0)
    c.add_argument("capture", nargs=argparse.REMAINDER, help="Capture command after --, typically studio launch")
    c = command("host")
    c.add_argument("operation", choices=["preflight", "apply"])
    c.add_argument("--window-start", help="ISO 8601 UTC start of the unattended window")
    c.add_argument("--window-end", help="ISO 8601 UTC end of the unattended window")
    c.add_argument("--output", help="Preflight receipt path")
    c.add_argument("--receipt", help="Apply receipt path written by the PowerShell script")
    c.add_argument("--pause-days", type=int, default=3)
    c.add_argument("--active-start", type=int, default=18)
    c.add_argument("--active-end", type=int, default=12)
    c.add_argument("--what-if", action="store_true", help="Print intended changes without writing them")
    c.add_argument("--restore", action="store_true", help="Clear the pause and return to Balanced")
    c = command("validate-record", True)
    c.add_argument("--record", required=True)
    c = command("fixture", True)
    c.add_argument(
        "--source-fixture",
        help="Reuse a previously generated and inspected original fixture directory",
    )
    # A remainder positional cannot follow another positional, so blender nests
    # its operation the way playtest does: `run` carries the script passthrough.
    # The four packaged operations keep the argument set they always had, and
    # every shared option is accepted on either side of the operation name, as
    # it was when this was one flat parser. A subparser default of SUPPRESS is
    # what makes that work: argparse copies a subparser's namespace over the
    # parent's, so an ordinary default would erase a value given before the
    # operation. Nothing is required here; `dispatch` asks for what it needs,
    # so neither spelling is refused for the other one's sake.
    SHARED = (
        ("--config", {}),
        ("--project", {"help": "Explicit game/output root outside the toolkit"}),
        ("--source", {}),
        ("--collection", {}),
        ("--camera", {}),
        ("--frames", {"default": "1"}),
        ("--angles", {"default": "0"}),
        ("--target", {"default": "0,0,0"}),
        ("--output", {"help": "Required .glb destination for export; otherwise defaults to artifacts/blender"}),
    )
    blender_command = sub.add_parser("blender")
    for flag, options in SHARED:
        blender_command.add_argument(flag, **options)
    blender_ops = blender_command.add_subparsers(dest="operation", required=True)
    ops = {}
    for name in ("fixture", "inspect", "export", "render", "run", "reduce"):
        c = blender_ops.add_parser(name)
        for flag, options in SHARED:
            c.add_argument(flag, **{**options, "default": argparse.SUPPRESS})
        ops[name] = c
    # `reduce` takes the triangle budget and the file it writes; neither is
    # declared required, because a shared option given before the operation
    # name has to stay legal and `dispatch` is where what is missing is named.
    c = ops["reduce"]
    c.add_argument("--target-triangles", type=int,
                   help="Triangles each reduced mesh object should hold; 100-5000000")
    c.add_argument("--object", help="Reduce only this mesh object; default is every mesh object")
    c.add_argument("--label", help="Reduction identity under artifacts/blender/reduce; default is a new UUID")
    c = ops["run"]
    c.add_argument("--script", help="Project-relative .py Blender runs inside that file")
    c.add_argument("--label", help="Run identity under artifacts/blender/runs; default is a new UUID")
    c.add_argument("--timeout", type=float, help="Seconds; default 600, maximum 3600")
    c.add_argument("--result", action="append", default=[], help="Project-relative file the script must produce")
    c.add_argument("passthrough", nargs=argparse.REMAINDER,
                   help="-- and the arguments after it go to the script after Blender's own --")
    c = command("blender-mcp", True, config_required=True)
    c.add_argument("operation", choices=["ensure", "status", "stop", "contracts"])
    c.add_argument("--source")
    c.add_argument("--session")
    c.add_argument("--receipt")
    c.add_argument("--plan-only", action="store_true")
    c.add_argument(
        "--probe",
        action="store_true",
        help="Force the full native protocol round-trip (ensure/status only); "
        "requires no connected app client",
    )
    c = command("terrain", True)
    c.add_argument("--output", default="source/terrain")
    c.add_argument("--resolution", type=int, default=33)
    c.add_argument("--width", type=float, default=12)
    c.add_argument("--depth", type=float, default=12)
    c.add_argument("--elevation", type=float, default=0.7)
    # `balance` is read-only like `meshy balance`: it writes nothing, so it
    # needs neither a project nor a task record, and dispatch checks both for
    # every other operation.
    c = command("audio")
    c.add_argument("--project", help="Explicit game/output root outside the toolkit; every operation but balance")
    c.add_argument("--provider", choices=["elevenlabs", "fish"], default="elevenlabs")
    c.add_argument(
        "operation",
        choices=["local", "prepare", "measure", "effects", "speech", "music", "balance"],
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
    # `balance` is read-only: it writes nothing, so it needs neither a project
    # nor a task record, and both are checked in dispatch for the rest.
    c = command("meshy")
    c.add_argument("--project", help="Explicit game/output root outside the toolkit; every operation but balance")
    c.add_argument("operation", choices=["submit", "observe", "reconcile", "archive", "balance"])
    c.add_argument(
        "--profile",
        choices=["image", "preview", "refine", "remesh", "retexture", "rig", "animate"],
    )
    c.add_argument("--request")
    c.add_argument("--budget")
    c.add_argument("--eligibility")
    c.add_argument("--record", help="Durable task record; every operation but balance")
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
    c = command("review", True)
    c.add_argument("operation", choices=["validate-card", "prepare", "capture", "dense", "analyze", "assess", "compare", "validate-run", "fixtures", "ingest", "qualify"])
    c.add_argument("--review", help="Named observer/evaluator JSON approved by host review_trust")
    c.add_argument("--card")
    c.add_argument("--candidate", default="artifacts/candidate.json")
    c.add_argument("--run")
    c.add_argument("--before")
    c.add_argument("--after")
    c.add_argument("--previous")
    c.add_argument("--affected", nargs="+")
    c.add_argument("--role", choices=["standalone", "before", "after"], default="standalone")
    c.add_argument("--profile", help="Explicit local recorder profile JSON")
    c.add_argument("--budget", help="Explicit clip-specific video authorization JSON")
    c.add_argument("--dense", help="Saved dense frames.json relative to project")
    c.add_argument("--evidence", help="Bound timing/action evidence JSON")
    c.add_argument("--interval", nargs=2, type=float)
    c.add_argument("--output", default="artifacts/review-fixtures")
    c = command("candidate", True)
    c.add_argument("operation", nargs="?", choices=["new", "verify"], default="new")
    c.add_argument("--id", help="Candidate identity for new")
    c.add_argument("--manifest", help="Identity manifest JSON for verify")
    c.add_argument("--engine-version", default="4.5.1")
    c.add_argument("--output", help="Record under artifacts/: candidate.json for new, the receipt for verify")
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


def _profile_fields(config, root, command, a, overrides):
    """Resolve `--profile`/`--check` into the arguments a launcher already takes.

    Returns (fields, receipt extras, refusal). Without `--profile` this is the
    caller's own flags and nothing else, so a command that never names a
    profile behaves exactly as it did.
    """
    if not a.profile:
        if a.check:
            raise StudioError(
                "--check verifies a launch profile's identity manifest; name one with --profile"
            )
        fields = {name: value for name, value in overrides.items() if value not in (None, [])}
        fields["label"] = a.label
        return fields, {}, None
    from . import profile as profiles

    resolved = profiles.resolve(
        config, root, command, overrides, path=a.profile, label=a.label, check=a.check
    )
    if "refused" in resolved:
        return {}, {}, resolved["refused"]
    return resolved["arguments"], resolved["receipt"], None


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
    if a.command == "blender-mcp":
        from .blender_mcp_lifecycle import execute

        if a.plan_only and a.operation != "ensure":
            raise StudioError("--plan-only is supported by blender-mcp ensure only")
        if a.probe and a.operation not in {"ensure", "status"}:
            raise StudioError("--probe is supported by blender-mcp ensure and status only")
        return execute(
            config,
            a.config,
            Path(a.project).resolve(),
            a.operation,
            source=a.source,
            session=a.session,
            receipt=a.receipt,
            plan_only=a.plan_only,
            probe=a.probe,
        )
    if a.command == "launch":
        from .launch import execute as launch_execute

        # A launch needs a game project that already exists, so the project is
        # not created here: a mistyped --project must fail, not be built empty.
        # Godot exposes only arguments after `--` through OS.get_cmdline_user_args(),
        # so the separator itself must reach the engine.
        root = Path(a.project).resolve()
        fields, extra, refusal = _profile_fields(config, root, "launch", a, {
            "mode": a.mode, "script": a.script, "timeout": a.timeout, "scope": a.scope,
            "results": a.result, "scrub_env": a.scrub_env, "passthrough": list(a.passthrough),
        })
        if refusal is not None:
            return refusal
        return launch_execute(
            config, root, sha256_expected=a.sha256, mode=fields.get("mode") or "import",
            script=fields.get("script"), timeout=fields.get("timeout"), cutoff_utc=a.cutoff_utc,
            label=fields.get("label"), scope=fields.get("scope"),
            results=fields.get("results", []), scrub=fields.get("scrub_env", []),
            passthrough=fields.get("passthrough", []), **extra,
        )
    if a.command == "batch":
        from .batch import execute as batch_execute

        # Like launch, a batch needs a game project that already exists, and it
        # reuses that launcher for every run rather than starting anything here.
        # The runs live in the plan file because N launches, each with its own
        # script, results and passthrough, do not fit one argument list.
        return batch_execute(
            config, Path(a.project).resolve(), plan=a.plan, sha256_expected=a.sha256,
            label=a.label, max_minutes=a.max_minutes,
            stop_on_first_failure=a.stop_on_first_failure,
        )
    if a.command == "playtest":
        from .playtest import collect as playtest_collect, execute as playtest_execute

        # Like launch, a playtest needs a game project that already exists, and
        # the `--` separator itself must reach the engine for
        # OS.get_cmdline_user_args() to expose anything after it.
        if a.operation == "collect":
            return playtest_collect(config, Path(a.project).resolve(), a.label)
        root = Path(a.project).resolve()
        fields, extra, refusal = _profile_fields(config, root, "playtest", a, {
            "session": a.session, "scene": a.scene, "script": a.script,
            "rendering_method": a.rendering_method, "resolution": a.resolution,
            "max_minutes": a.max_minutes, "results": a.result, "scrub_env": a.scrub_env,
            "passthrough": list(a.passthrough),
        })
        if refusal is not None:
            return refusal
        return playtest_execute(
            config, root, sha256_expected=a.sha256,
            session=fields.get("session") or "handoff",
            scene=fields.get("scene"), script=fields.get("script"),
            label=fields.get("label"), max_minutes=fields.get("max_minutes"),
            cutoff_utc=a.cutoff_utc, results=fields.get("results", []),
            scrub=fields.get("scrub_env", []), passthrough=fields.get("passthrough", []),
            use_host_profile=a.use_host_profile, emit_launcher=not a.no_launcher,
            rendering_method=fields.get("rendering_method"),
            resolution=fields.get("resolution"), **extra,
        )
    if a.command == "evidence":
        if a.operation == "verify":
            from .evidence import verify_receipt

            if not a.receipt:
                raise StudioError("evidence verify needs --receipt")
            return verify_receipt(a.receipt, a.project)
        from .launch import inventory

        if not a.run_root:
            raise StudioError("evidence launches needs a run root")
        return inventory(a.run_root, a.output)
    if a.command == "host":
        from .host import apply as host_apply, preflight

        if a.operation == "preflight":
            return preflight(config, window_start=a.window_start, window_end=a.window_end, output=a.output)
        return host_apply(
            config, receipt=a.receipt, pause_days=a.pause_days, active_start=a.active_start,
            active_end=a.active_end, what_if=a.what_if, restore=a.restore,
        )
    if a.command == "bench":
        from .cleanroom import execute as bench_execute

        capture = list(a.capture)
        if capture[:1] == ["--"]:
            capture = capture[1:]
        # A bench measures a project that already exists; creating the root here
        # would turn a mistyped --project into a new empty directory instead of
        # the refusal `cleanroom.execute` is written to give.
        return bench_execute(
            config, Path(a.project).resolve(), capture, label=a.label, scope=a.scope, settle=a.settle,
            agent_log=a.agent_log, timeout=a.timeout, busy_fraction=a.busy_fraction,
            busy_floor_seconds=a.busy_floor_seconds, heavy_working_set_mb=a.heavy_working_set_mb,
            sample_interval=a.sample_interval,
        )
    if a.command == "blender" and not a.project:
        raise StudioError("blender " + a.operation + " needs --project")
    if a.command == "blender" and a.operation == "run":
        from .adapters import blender

        # A run needs a game project that already exists, so the project is not
        # created here: a mistyped --project must fail, not be built empty.
        # The receipts, not the exit code, are the reason this command exists.
        if not a.source or not a.script:
            raise StudioError("blender run needs --source and --script relative to the project")
        return blender.script_run(
            config, Path(a.project).resolve(), source=a.source, script=a.script,
            label=a.label, timeout=a.timeout, results=a.result,
            passthrough=list(a.passthrough),
        )
    if a.command == "blender" and a.operation == "reduce":
        from .adapters import blender

        # Reducing from an intact archived original is the alternative to
        # paying for a remesh that arrives defective, so like `run` it works on
        # a project that already exists and is not created by asking for it.
        if not a.source or not a.output or a.target_triangles is None:
            raise StudioError(
                "blender reduce needs --source, --target-triangles and --output "
                "relative to the project"
            )
        return blender.reduce_mesh(
            config, Path(a.project).resolve(), source=a.source,
            target_triangles=a.target_triangles, output=a.output,
            object_name=a.object, label=a.label,
        )
    if a.command == "audio" and a.operation == "balance":
        from .adapters import audio

        # Read-only and receiptless: answered before any project root is made.
        return audio.balance(config, a.provider)
    if a.command == "audio" and not a.project:
        raise StudioError("audio " + a.operation + " needs --project")
    if a.command == "meshy" and a.operation == "balance":
        from .adapters import meshy

        # Read-only and receiptless: answered before any project root is made.
        return meshy.balance(config)
    if a.command == "meshy":
        # Both before the project root is created below: a mistyped --project
        # with a missing --record must leave no directory behind either.
        if not a.project:
            raise StudioError("meshy " + a.operation + " needs --project")
        if not a.record:
            raise StudioError("meshy " + a.operation + " needs --record")
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
    if a.command == "review":
        from . import validation, review_media, review_video
        def needed(field):
            value = getattr(a, field)
            if value is None:
                raise StudioError("review " + a.operation + " requires --" + field)
            return value
        if a.operation == "qualify":
            from .review_records import qualify
            return {"qualification": qualify(config, root, needed("review"))}
        if a.operation == "ingest":
            from .review_records import ingest
            return {"review": ingest(config, root, needed("run"), needed("review"))}
        if a.operation == "fixtures":
            return review_media.fixtures(config, path(a.output))
        if a.operation in {"validate-card", "prepare"}:
            card = read_json(path(needed("card")))
            candidate = read_json(path(a.candidate))
            if a.operation == "validate-card":
                return validation.validate_card(card, candidate, root)
            return {"run": validation.prepare_run(root, card, candidate, role=a.role, previous=a.previous, affected=a.affected, config=config)}
        if a.operation == "compare":
            return validation.compare_runs(root, needed("before"), needed("after"), config=config)
        name = needed("run")
        if a.operation == "validate-run":
            validation.validate_run(root, name, config=config)
            return {"ok": True, "run": name}
        if a.operation == "capture":
            return review_media.capture(config, root, name, read_json(path(needed("profile"))))
        if a.operation == "dense":
            return review_media.dense_frames(config, root, name, needed("interval"))
        if a.operation == "analyze":
            return review_video.analyze(config, root, name, read_json(path(needed("budget"))), dense=a.dense)
        return validation.assess(root, name, a.evidence, config=config)
    if a.command == "fixture":
        from .fixture import create

        return create(config, root, a.source_fixture)
    if a.command == "blender":
        from .adapters import blender

        if a.operation == "export" and not a.output:
            raise StudioError("Blender export requires --output assets/name.glb relative to the project")
        out = path(a.output or "artifacts/blender")
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
        from .adapters.audio import generate

        if not all([a.request, a.budget, a.provenance]):
            raise StudioError(
                "Hosted audio needs --request, --budget and --provenance JSON files"
            )
        return generate(
            config,
            a.provider,
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
        output = a.output or ("artifacts/candidate.json" if a.operation == "new" else None)
        if output is not None and not output.startswith("artifacts/"):
            raise StudioError(
                "Candidate record belongs under artifacts/ so it cannot hash itself"
            )
        if a.operation == "verify":
            from .manifest import verify

            if not a.manifest:
                raise StudioError("candidate verify needs --manifest")
            return verify(root, a.manifest, output=path(output) if output else None, config=config)
        from .evidence import new_candidate
        from . import __version__

        if not a.id:
            raise StudioError("candidate new needs --id")
        result = new_candidate(root, a.id, a.engine_version, __version__)
        write_json(path(output), result)
        return result
    raise StudioError("Unknown command")
