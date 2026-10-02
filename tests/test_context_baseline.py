"""Source-slot identity and native evidence must fail closed without selection writes."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from studio_tools import context_baseline as baseline
from studio_tools.common import StudioError, file_record, sha256, write_json


def png(width=1920, height=1080, fill=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raster = (b"\x00" + bytes([fill]) * (width * 3)) * height
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raster)) + chunk(b"IEND", b"")


class ContextBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_lfs_asset_and_committed_crlf_source_are_bound_to_registered_slot(self):
        asset = self.root / "assets/a.glb"
        asset.parent.mkdir()
        asset.write_bytes(b"registered baseline")
        identity = sha256(asset)
        source = (f'const ASSET_PATH := "res://assets/a.glb"\n'
                  f'const ASSET_SHA256 := "{identity}"\n').encode()
        copied = self.root / "scripts/context.gd"
        copied.parent.mkdir()
        copied.write_bytes(source.replace(b"\n", b"\r\n"))
        slot = {"name": "one-runtime-slot", "model_id": "mite", "attempt_id": "one", "sha256": identity,
                "asset": "assets/a.glb", "source": "scripts/context.gd",
                "git_path": "game/scripts/context.gd", "sha_constant": "ASSET_SHA256",
                "path_constant": "ASSET_PATH"}
        pointer = f"version https://git-lfs.github.com/spec/v1\noid sha256:{identity}\nsize {asset.stat().st_size}\n".encode()
        with patch.object(baseline, "_committed", side_effect=lambda _repo, _commit, path: pointer if path.endswith(".glb") else source):
            result = baseline._source_slot(self.root, self.root, "a" * 40, slot,
                                           {"one": {"id": "one", "model_id": "mite", "sha256": identity}})
            self.assertEqual(result["committed_asset_proof"], "lfs-oid")
            self.assertTrue(result["source"]["line_endings_normalized"])
            committed_crlf = source.replace(b"\n", b"\r\n")
            for checkout in (committed_crlf, source):
                copied.write_bytes(checkout)
                with patch.object(baseline, "_committed", side_effect=lambda _r, _c, path:
                                  pointer if path.endswith(".glb") else committed_crlf):
                    checked = baseline._source_slot(self.root, self.root, "a"*40, slot,
                              {"one": {"id": "one", "model_id": "mite", "sha256": identity}})
                    self.assertEqual(checked["source"]["line_endings_normalized"], checkout != committed_crlf)
            malformed = [
                f"oid sha256:{identity}\n".encode(),
                pointer.replace(b"version https://git-lfs.github.com/spec/v1", b"version wrong"),
                pointer.replace(b"size " + str(asset.stat().st_size).encode(), b"size 999"),
                pointer.replace(b"size ", b"size -"),
                pointer + b"unexpected content\n",
            ]
            for bad in malformed:
                with self.subTest(pointer=bad), patch.object(baseline, "_committed", return_value=bad):
                    with self.assertRaisesRegex(StudioError, "Committed .* differs"):
                        baseline._source_slot(self.root, self.root, "a" * 40, slot,
                                              {"one": {"id": "one", "model_id": "mite", "sha256": identity}})
            copied.write_bytes(copied.read_bytes().replace(b"ASSET_PATH", b"OTHER_PATH"))
            with self.assertRaisesRegex(StudioError, "differs from pinned commit"):
                baseline._source_slot(self.root, self.root, "a" * 40, slot,
                                      {"one": {"id": "one", "model_id": "mite", "sha256": identity}})

    def test_owned_launch_report_state_and_complete_png_are_required(self):
        name = "native-one"
        output = self.root / "reports/one.json"
        output.parent.mkdir()
        write_json(output, {"passed": True, "states": [{"phase": "feed"}, {"phase": "shelter"}],
                            "captures": [{"path": "res://captures/one.png", "save_error": 0}]})
        picture = self.root / "captures/one.png"
        picture.parent.mkdir()
        picture.write_bytes(png())
        script = self.root / "tests/one.gd"
        script.parent.mkdir()
        script.write_bytes(b"extends SceneTree\n")
        project = self.root / "project.godot"
        project.write_bytes(b'config_version=5\n')
        data = self.root / "tests/input.json"
        data.write_bytes(b'{"seed": 1}\n')
        committed = {"game/tests/one.gd": script.read_bytes(), "game/project.godot": project.read_bytes(),
                     "game/tests/input.json": data.read_bytes()}
        reservation = self.root / "resource.json"
        write_json(reservation, {"checked_utc": "2026-10-01T15:00:00Z",
                                 "window_end_utc": "2026-10-01T15:20:00Z",
                                 "process_status": "ok", "competing_godot_blender_ffmpeg": [],
                                 "competing_heavy_jobs_verified": True, "host_ready": True})
        folder = self.root / "artifacts/launches" / name
        folder.mkdir(parents=True)
        engine = self.root / "engine.exe"
        pe = bytearray(68)
        pe[:2] = b"MZ"
        pe[60:64] = (64).to_bytes(4, "little")
        pe[64:68] = b"PE\x00\x00"
        engine.write_bytes(pe)
        engine_hash = sha256(engine)
        kit = {"version": "test", "source_digest": "a" * 64}
        survivors = {"status": "ok", "stopped": True, "pids": [],
                     "unstopped_pids": [], "unverified": []}
        write_json(folder / "exit.json", {"ok": True, "label": name, "scope": "mite",
                                          "schema_version": 1, "kind": "launch-exit", "kit": kit,
                                          "verdict": "completed", "status": "completed", "returncode": 0,
                                          "timed_out": False, "elapsed_seconds": 60.0,
                                          "finished_utc": "2026-10-01T15:01:13Z", "survivors": survivors,
                                          "result_files": [{"path": "reports/one.json", "sha256": sha256(output),
                                                            "present": True, "stale": False,
                                                            "unreadable": False, "escaped": False}]})
        write_json(folder / "owned-launch.json", {"label": name, "scope": "mite",
                                                  "schema_version": 1, "kind": "owned-launch", "kit": kit,
                                                  "status": "launched", "pid": 42, "passthrough_count": 0,
                                                  "process_record": "process/process.json",
                                                  "expected_results": ["reports/one.json"],
                                                  "survivors": survivors,
                                                  "project": str(self.root),
                                                  "started_utc": "2026-10-01T15:00:10Z",
                                                  "cutoff_utc": "2026-10-01T15:05:00Z",
                                                  "timeout_seconds_effective": 120.0,
                                                  "mode": "native", "script": "res://tests/one.gd",
                                                  "engine": {"name": "godot.exe", "sha256": engine_hash,
                                                             "sha256_after_exit": engine_hash}})
        process_path = folder / "process/process.json"
        process_path.parent.mkdir()
        write_json(process_path, {"schema_version": 1, "status": "completed", "returncode": 0,
                                  "pid": 42, "elapsed_seconds": 60.0,
                                  "started_utc": "2026-10-01T15:00:11Z",
                                  "finished_utc": "2026-10-01T15:01:11Z",
                                  "windows_ownership": {"status": "ok", "identity": {
                                      "pid": 42, "name": "godot.exe", "created_filetime": "123",
                                      "exited_filetime": "456"}}})
        run = {"name": "mite", "label": name, "scope": "mite", "mode": "native",
               "script": "res://tests/one.gd", "report": "reports/one.json",
               "fixture_inputs": ["tests/input.json"],
               "checks": {"equal": {"passed": True}, "coverage": [{"path": "states", "field": "phase",
                                                               "required": ["feed", "shelter"]}]},
               "captures": ["captures/one.png"], "capture_report": "captures",
               "reservation": {"path": str(reservation), "sha256": sha256(reservation)},
               "owned_launch_sha256": sha256(folder / "owned-launch.json"),
               "process_sha256": sha256(process_path)}
        retained = {"scope": "mite", "launch": file_record(self.root, folder / "exit.json"),
                    "owned_launch": file_record(self.root, folder / "owned-launch.json"),
                    "process": file_record(self.root, process_path),
                    "fixture_source_sha256": sha256(script),
                    "fixture_inputs": [{**file_record(self.root, path), "committed_sha256": sha256(path)}
                                       for path in (project, script, data)],
                    "report": file_record(self.root, output),
                    "captures": [file_record(self.root, picture)]}
        with patch.object(baseline, "_committed", side_effect=lambda _repo, _commit, path: committed[path]):
            verify = lambda: baseline._run(self.root, self.root, "a" * 40, run, engine_hash, kit, retained,
                                          baseline._engine_platform(engine.read_bytes()))
            result = verify()
            self.assertEqual(result["functional_checks"], "passed")
            self.assertEqual(result["selected_animation_qualification"], "not_attempted")
            for scope in (None, "", "unsafe/scope", True):
                with self.subTest(scope=scope), self.assertRaises(StudioError):
                    baseline._run(self.root, self.root, "a" * 40, {**run, "scope": scope},
                                  engine_hash, kit, retained, "windows")
            launch_path = folder / "owned-launch.json"
            original = launch_path.read_bytes()
            for count in (None, 1, True, 0.0):
                changed = json.loads(original)
                changed["passthrough_count"] = count
                write_json(launch_path, changed)
                run["owned_launch_sha256"] = sha256(launch_path)
                with self.subTest(count=count), self.assertRaisesRegex(StudioError, "differs from the pinned fixture"):
                    verify()
            launch_path.write_bytes(original)
            run["owned_launch_sha256"] = sha256(launch_path)
            for path in (project, data):
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(StudioError, "fixture input differs"):
                    verify()
                path.write_bytes(original)
            old_inputs = retained.pop("fixture_inputs")
            with self.assertRaisesRegex(StudioError, "historical evidence"):
                verify()
            retained["fixture_inputs"] = old_inputs
            old_field = run.pop("capture_report")
            with self.assertRaisesRegex(StudioError, "captures require a complete report manifest"):
                verify()
            run["capture_report"] = old_field
            # These are synthetic fixtures of the actual POSIX v1 shapes: no
            # Windows identity or unstopped_pids field is emitted there.
            original_process = process_path.read_bytes()
            original_exit = (folder / "exit.json").read_bytes()
            original_launch = (folder / "owned-launch.json").read_bytes()
            old_proofs = {key: retained[key] for key in ("launch", "owned_launch", "process")}
            posix_process = json.loads(original_process)
            posix_process.pop("windows_ownership")
            write_json(process_path, posix_process)
            run["process_sha256"] = sha256(process_path)
            with self.assertRaisesRegex(StudioError, "Windows process ownership is unverified"):
                verify()
            posix_exit = json.loads(original_exit)
            posix_exit["survivors"].pop("unstopped_pids")
            write_json(folder / "exit.json", posix_exit)
            posix_launch = json.loads(original_launch)
            posix_launch["survivors"] = posix_exit["survivors"]
            write_json(folder / "owned-launch.json", posix_launch)
            run["owned_launch_sha256"] = sha256(folder / "owned-launch.json")
            for key, path in (("launch", folder / "exit.json"), ("owned_launch", folder / "owned-launch.json"),
                              ("process", process_path)):
                retained[key] = file_record(self.root, path)
            verify_posix = lambda: baseline._run(self.root, self.root, "a" * 40, run, engine_hash, kit, retained, "posix")
            self.assertEqual(verify_posix()["process_platform"], "posix")
            for key, value in (("status", "unavailable"), ("stopped", False), ("pids", [43]),
                               ("unverified", [43]), ("unstopped_pids", [43])):
                bad = json.loads((folder / "exit.json").read_bytes())
                bad["survivors"][key] = value
                write_json(folder / "exit.json", bad)
                with self.assertRaisesRegex(StudioError, "did not finish cleanly"):
                    verify_posix()
                write_json(folder / "exit.json", posix_exit)
            process_path.write_bytes(original_process)
            (folder / "exit.json").write_bytes(original_exit)
            (folder / "owned-launch.json").write_bytes(original_launch)
            run["process_sha256"] = sha256(process_path)
            run["owned_launch_sha256"] = sha256(folder / "owned-launch.json")
            retained.update(old_proofs)
            for mode in ("import", "check"):
                launch = json.loads((folder / "owned-launch.json").read_text())
                launch["mode"] = mode
                write_json(folder / "owned-launch.json", launch)
                run["mode"] = mode
                run["owned_launch_sha256"] = sha256(folder / "owned-launch.json")
                with self.assertRaisesRegex(StudioError, "mode must be test or native"):
                    verify()
            launch["mode"] = "native"
            write_json(folder / "owned-launch.json", launch)
            run["mode"] = "native"
            run["owned_launch_sha256"] = sha256(folder / "owned-launch.json")
            original_checks = run["checks"]
            for empty in ({}, {"equal": {}}, {"coverage": [{"path": "states", "field": "phase", "required": []}]}):
                run["checks"] = empty
                with self.assertRaisesRegex(StudioError, "at least one functional assertion"):
                    verify()
            run["checks"] = original_checks
            original_reservation = reservation.read_bytes()
            unsafe = json.loads(original_reservation)
            unsafe["host_ready"] = False
            write_json(reservation, unsafe)
            run["reservation"]["sha256"] = sha256(reservation)
            with self.assertRaisesRegex(StudioError, "reservation did not cover"):
                verify()
            reservation.write_bytes(original_reservation)
            run["reservation"]["sha256"] = sha256(reservation)
            original_process = process_path.read_bytes()
            forged = json.loads(original_process)
            forged["windows_ownership"]["identity"]["created_filetime"] = "987"
            write_json(process_path, forged)
            run["process_sha256"] = sha256(process_path)
            with self.assertRaisesRegex(StudioError, "bytes differ from historical evidence"):
                verify()
            process_path.write_bytes(original_process)
            run["process_sha256"] = sha256(process_path)
            original_launch = (folder / "owned-launch.json").read_bytes()
            forged_launch = json.loads(original_launch)
            forged_launch["started_utc"] = "2026-10-01T15:00:09Z"
            write_json(folder / "owned-launch.json", forged_launch)
            run["owned_launch_sha256"] = sha256(folder / "owned-launch.json")
            with self.assertRaisesRegex(StudioError, "bytes differ from historical evidence"):
                verify()
            (folder / "owned-launch.json").write_bytes(original_launch)
            run["owned_launch_sha256"] = sha256(folder / "owned-launch.json")
            process_bytes = process_path.read_bytes()
            process_path.unlink()
            with self.assertRaisesRegex(StudioError, "process receipt bytes changed"):
                verify()
            process_path.write_bytes(process_bytes)
            process = json.loads(process_bytes)
            process["pid"] = 43
            write_json(process_path, process)
            run["process_sha256"] = sha256(process_path)
            with self.assertRaisesRegex(StudioError, "does not pair with launch"):
                verify()
            process_path.write_bytes(process_bytes)
            run["process_sha256"] = sha256(process_path)
            exit_bytes = (folder / "exit.json").read_bytes()
            late_exit = json.loads(exit_bytes)
            late_exit["finished_utc"] = "2026-10-01T15:25:00Z"
            write_json(folder / "exit.json", late_exit)
            with self.assertRaisesRegex(StudioError, "exceeded its bounded launch"):
                verify()
            (folder / "exit.json").write_bytes(exit_bytes)
            launch_path = folder / "owned-launch.json"
            launch_bytes = launch_path.read_bytes()
            launch = json.loads(launch_bytes)
            launch["cutoff_utc"] = "2026-10-01T15:30:00Z"
            launch["timeout_seconds_effective"] = 1800.0
            write_json(launch_path, launch)
            run["owned_launch_sha256"] = sha256(launch_path)
            late_process = json.loads(process_bytes)
            late_process["finished_utc"] = "2026-10-01T15:24:00Z"
            late_process["elapsed_seconds"] = 1429.0
            write_json(process_path, late_process)
            run["process_sha256"] = sha256(process_path)
            late_exit["elapsed_seconds"] = 1429.0
            write_json(folder / "exit.json", late_exit)
            with self.assertRaisesRegex(StudioError, "reservation did not cover"):
                verify()
            launch_path.write_bytes(launch_bytes)
            run["owned_launch_sha256"] = sha256(launch_path)
            process_path.write_bytes(process_bytes)
            run["process_sha256"] = sha256(process_path)
            (folder / "exit.json").write_bytes(exit_bytes)
            picture.write_bytes(png(fill=1))
            with self.assertRaisesRegex(StudioError, "capture bytes differ from historical evidence"):
                verify()
            picture.write_bytes(png())
            picture.write_bytes(picture.read_bytes()[:-1] + bytes([picture.read_bytes()[-1] ^ 1]))
            with self.assertRaisesRegex(StudioError, "capture is missing or invalid"):
                verify()
            picture.write_bytes(png())
            changed = json.loads(output.read_text())
            changed["states"].pop()
            write_json(output, changed)
            exit_record = json.loads((folder / "exit.json").read_text())
            exit_record["result_files"][0]["sha256"] = sha256(output)
            write_json(folder / "exit.json", exit_record)
            with self.assertRaisesRegex(StudioError, "state coverage is incomplete"):
                verify()
            write_json(reservation, {"checked_utc": "2026-10-01T14:00:00Z",
                                     "window_end_utc": "2026-10-01T15:20:00Z",
                                     "process_status": "ok", "competing_godot_blender_ffmpeg": [],
                                     "competing_heavy_jobs_verified": True})
            with self.assertRaisesRegex(StudioError, "reservation changed"):
                verify()

    def test_catalog_only_role_cannot_claim_runtime_source(self):
        asset = self.root / "assets/a.glb"
        asset.parent.mkdir()
        asset.write_bytes(b"catalog")
        identity = sha256(asset)
        slot = {"name": "catalog", "model_id": "slug", "attempt_id": "a", "sha256": identity,
                "asset": "assets/a.glb", "runtime_slot": False, "source": "scripts/pocket.gd"}
        with patch.object(baseline, "_committed", return_value=b"catalog"):
            with self.assertRaisesRegex(StudioError, "cannot impersonate"):
                baseline._source_slot(self.root, self.root, "a" * 40, slot,
                                      {"a": {"id": "a", "model_id": "slug", "sha256": identity}})
            slot.pop("source")
            slot["catalog_current"] = True
            with self.assertRaisesRegex(StudioError, "differs from the fieldbook pin"):
                baseline._source_slot(self.root, self.root, "a" * 40, slot,
                                      {"a": {"id": "a", "model_id": "slug", "sha256": identity}},
                                      {"slug": {"current_game_sha256": identity,
                                                "current_game_path": "res://assets/other.glb"}})

    def test_boolean_and_number_equality_preserves_nested_json_types(self):
        for actual, expected in ((1, True), (0, False), (True, 1), (False, 0), (1.0, 1),
                                 ({"pass": [1]}, {"pass": [True]})):
            with self.subTest(actual=actual, expected=expected):
                with self.assertRaisesRegex(StudioError, "equality check failed"):
                    baseline._checks({"value": actual}, {"equal": {"value": expected}})
        baseline._checks({"value": {"pass": [True, 1, 1.0, None]}},
                         {"equal": {"value": {"pass": [True, 1, 1.0, None]}}})

    def test_empty_plans_and_duplicate_execution_labels_fail_before_io(self):
        plan = {"schema_version": 1, "kind": "source-context-baseline", "source_commit": "a" * 40,
                "slots": [{"name": "asset"}], "runs": [{"name": "one", "label": "launch-one", "scope": "one"}]}
        for key in ("slots", "runs"):
            for value in ([], None, {}):
                with self.subTest(key=key, value=value), patch.object(baseline, "read_json", return_value={**plan, key: value}):
                    with self.assertRaisesRegex(StudioError, "requires nonempty " + key):
                        baseline.verify(self.root, self.root / "manifest.json", "receipt.json")
        plan["runs"].append({"name": "two", "label": "launch-one"})
        with patch.object(baseline, "read_json", return_value=plan), patch.object(baseline, "_run") as runner:
            with self.assertRaisesRegex(StudioError, "runs label values must be distinct"):
                baseline.verify(self.root, self.root / "manifest.json", "receipt.json")
            runner.assert_not_called()

    def test_platform_is_bound_to_engine_bytes_not_missing_windows_ownership(self):
        engine = self.root / "engine"
        pe = bytearray(68)
        pe[:2] = b"MZ"
        pe[60:64] = (64).to_bytes(4, "little")
        pe[64:68] = b"PE\x00\x00"
        engine.write_bytes(pe)
        self.assertEqual(baseline._engine_platform(engine.read_bytes()), "windows")
        for magic in (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
            engine.write_bytes(magic + b"\x00" * 60)
            self.assertEqual(baseline._engine_platform(engine.read_bytes()), "posix")
        for bad in (b"MZ", b"unknown", bytes(pe[:-4]) + b"bad!"):
            engine.write_bytes(bad)
            with self.assertRaisesRegex(StudioError, "platform cannot be verified"):
                baseline._engine_platform(engine.read_bytes())

    def test_known_text_accepts_committed_crlf_and_binary_requires_exact_bytes(self):
        committed = b'extends SceneTree\r\n'
        script = self.root / 'fixture.gd'
        project = self.root / 'project.godot'
        project.write_bytes(b'config_version=5\r\n')
        for copied in (committed, committed.replace(b'\r\n', b'\n')):
            script.write_bytes(copied)
            with patch.object(baseline, '_committed', side_effect=lambda _r, _c, name:
                              committed if name.endswith('.gd') else project.read_bytes()):
                self.assertEqual(len(baseline._fixture_inputs(self.root, self.root, 'a'*40,
                                     {'script': 'res://fixture.gd'})), 2)
        data = self.root / 'input.bin'
        data.write_bytes(b'a\r\nb')
        with patch.object(baseline, '_committed', side_effect=lambda _r, _c, name:
                          b'a\nb' if name.endswith('.bin') else (script if name.endswith('.gd') else project).read_bytes()):
            with self.assertRaisesRegex(StudioError, 'fixture input differs'):
                baseline._fixture_inputs(self.root, self.root, 'a'*40,
                                         {'script': 'res://fixture.gd', 'fixture_inputs': ['input.bin']})

    def test_catalog_duplicates_and_missing_scope_fail_before_run_verification(self):
        catalog_path = self.root / 'catalog.json'
        plan = {'schema_version': 1, 'kind': 'source-context-baseline', 'source_commit': 'a'*40,
                'source_repository': str(self.root), 'catalog_snapshot': str(catalog_path),
                'slots': [{'name': 'asset'}], 'runs': [{'name': 'one', 'label': 'one', 'scope': 'one'}]}
        for collection in ('attempts', 'models'):
            catalog = {'attempts': [{'id': 'a'}], 'models': [{'id': 'm'}]}
            catalog[collection].append(dict(catalog[collection][0]))
            write_json(catalog_path, catalog)
            manifest = {**plan, 'catalog_sha256': sha256(catalog_path)}
            with patch.object(baseline, 'read_json', side_effect=[manifest, catalog]), patch.object(baseline, '_run') as run:
                with self.assertRaisesRegex(StudioError, collection + ' IDs must be distinct'):
                    baseline.verify(self.root, 'manifest.json', 'receipt.json')
                run.assert_not_called()
        for scope in (None, '', 'one/two', True):
            manifest = {**plan, 'runs': [{**plan['runs'][0], 'scope': scope}]}
            with patch.object(baseline, 'read_json', return_value=manifest), patch.object(baseline, 'sha256') as hashed:
                with self.assertRaises(StudioError):
                    baseline.verify(self.root, 'manifest.json', 'receipt.json')
                hashed.assert_not_called()

    def test_engine_replacement_cannot_select_platform_for_different_hash(self):
        engine = self.root / 'engine'
        pe = bytearray(68)
        pe[:2] = b'MZ'
        pe[60:64] = (64).to_bytes(4, 'little')
        pe[64:] = b'PE\x00\x00'
        engine.write_bytes(pe)
        catalog = {'attempts': [], 'models': []}
        catalog_path = self.root / 'catalog.json'
        write_json(catalog_path, catalog)
        plan = {'schema_version': 1, 'kind': 'source-context-baseline', 'source_commit': 'a'*40,
                'source_repository': str(self.root), 'catalog_snapshot': str(catalog_path),
                'catalog_sha256': sha256(catalog_path), 'engine': {'path': str(engine), 'sha256': sha256(engine)},
                'slots': [{'name': 'asset'}], 'runs': [{'name': 'one', 'label': 'one', 'scope': 'one'}]}
        classify = baseline._engine_platform
        def replace_then_classify(raw):
            engine.write_bytes(b'\x7fELF' + b'\x00'*60)
            self.assertEqual(classify(raw), 'windows')
            return classify(raw)
        with patch.object(baseline, 'read_json', side_effect=[plan, catalog]), \
                patch.object(baseline, '_engine_platform', side_effect=replace_then_classify) as platform:
            with self.assertRaisesRegex(StudioError, 'pinned retained run evidence'):
                baseline.verify(self.root, 'manifest.json', 'receipt.json')
            platform.assert_called_once_with(bytes(pe))


if __name__ == "__main__":
    unittest.main()
