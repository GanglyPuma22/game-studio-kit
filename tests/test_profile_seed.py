"""Declared bytes, ownership and final pre-spawn guards; no engine is run."""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import cli, launch, playtest, profile, profile_seed as seeds
from studio_tools.common import StudioError, read_json, sha256, write_json


class SeedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio seed ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "game"
        self.root.mkdir()
        (self.root / "project.godot").touch()
        self.raw = b"private-setting=keep-CRLF\r\n[physics]\r\nvalue=100000.0\r\n"
        self.source = self.root / "settings.cfg"
        self.source.write_bytes(self.raw)
        self.engine = Path(self.tmp.name) / "fake-engine.exe"
        self.engine.write_bytes(b"fake engine, never executed")
        self.engine.chmod(0o755)
        self.config = {"executables": {"godot": str(self.engine)}, "timeout": 5,
                       "path_mappings": []}
        self.seed = {"platform": "windows", "files": [{"source": "settings.cfg",
                     "target": "Godot/app_userdata/EXAMPLE/override.cfg",
                     "sha256": sha256(self.source)}]}
        self.addCleanup(patch.stopall)
        patch("studio_tools.profile_seed.IS_WINDOWS", True).start()
        patch("studio_tools.launch.prelaunch_baseline", return_value={}).start()
        patch("studio_tools.playtest.prelaunch_baseline", return_value={}).start()
        patch("studio_tools.launch.stop_survivors", return_value={"status": "ok", "pids": []}).start()
        patch("studio_tools.playtest.stop_survivors", return_value={"status": "ok", "pids": []}).start()
        patch("studio_tools.playtest._revision", return_value=(None, None)).start()

    def target(self, command="launch", label="seeded"):
        namespace = "launches" if command == "launch" else "playtests"
        return self.root / f"artifacts/{namespace}/{label}/profile" / self.seed["files"][0]["target"]

    def fake_run(self, args, **kwargs):
        if self.seed is not None:
            self.assertEqual(self.target(self.command).read_bytes(), self.raw)
        else:
            self.assertEqual(list(Path(kwargs["env"]["APPDATA"]).iterdir()), [])
        self.last_args = args
        job = kwargs["job_dir"]
        job.mkdir()
        write_json(job / "process.json", {"schema_version": 1, "pid": 111,
                   "status": "completed", "returncode": 0, "elapsed_seconds": .01})
        (job / "stdout.log").write_text("Godot Engine fake\n")

    def execute(self, command="launch", **kwargs):
        self.command = command
        module = launch if command == "launch" else playtest
        with patch.object(module, "run", side_effect=self.fake_run) as run:
            result = module.execute(self.config, self.root, sha256_expected=sha256(self.engine),
                                    label="seeded", profile_seed=self.seed, **kwargs)
        return result, run


class DeclarationTests(SeedCase):
    def test_unsafe_portable_paths_are_refused_without_output(self):
        values = ["../x", "./x", "x//y", "/x", "C:/x", "C:x", "//host/share",
                  "x\\y", "x:y", "x\n", "x/", "x/..", "x/.", "x. ", "x.",
                  "NUL.cfg", "dir/COM1.txt", "CONIN$", "con .txt", "LPT².cfg",
                  "{label}/x", "x?", "x\x7f", "x*", 'x"']
        for field in ("source", "target"):
            for value in values:
                with self.subTest(field=field, value=value):
                    declared = json.loads(json.dumps(self.seed))
                    declared["files"][0][field] = value
                    with self.assertRaises(StudioError):
                        seeds.snapshot(self.config, self.root, declared)
        self.assertFalse((self.root / "artifacts").exists())

    def test_nested_fields_and_types_remain_strict(self):
        bad = [None, {}, [], {**self.seed, "hook": "run"}, {**self.seed, "files": []},
               {**self.seed, "platform": "linux"}, {**self.seed, "platform": True},
               {**self.seed, "files": self.seed["files"] * 9},
               {**self.seed, "files": [{**self.seed["files"][0], "contents": "private"}]}]
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(StudioError):
                    seeds.declaration(value)
        for field, value in [("sha256", "0"), ("sha256", True), ("source", []), ("target", True)]:
            declared = json.loads(json.dumps(self.seed))
            declared["files"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(StudioError):
                seeds.declaration(declared)

    def test_casefold_duplicates_and_parent_child_collisions(self):
        for first, second in [("Dir/A.cfg", "dir/a.CFG"), ("a", "a/b"), ("a/b", "A")]:
            entries = [{**self.seed["files"][0], "target": target} for target in (first, second)]
            with self.subTest(targets=(first, second)), self.assertRaisesRegex(StudioError, "collide"):
                seeds.declaration({**self.seed, "files": entries})

    def test_source_missing_mismatch_oversized_and_directory_refuse(self):
        for kind in ("missing", "wrong_hash", "oversized", "directory"):
            self.source.unlink(missing_ok=True)
            if kind == "directory":
                self.source.mkdir()
            elif kind != "missing":
                self.source.write_bytes(b"x" * (seeds.MAX_FILE_BYTES + 1) if kind == "oversized" else b"changed")
            with self.subTest(kind=kind), self.assertRaises(StudioError):
                seeds.snapshot(self.config, self.root, self.seed)
            if kind == "directory":
                self.source.rmdir()
        self.assertFalse((self.root / "artifacts").exists())

    def test_native_configured_engine_host_conflict_mapping_and_sc_refuse(self):
        with patch.object(seeds, "IS_WINDOWS", False), self.assertRaisesRegex(StudioError, "native Windows"):
            seeds.snapshot(self.config, self.root, self.seed)
        with self.assertRaisesRegex(StudioError, "conflicts"):
            seeds.snapshot(self.config, self.root, self.seed, use_host_profile=True)
        with self.assertRaisesRegex(StudioError, "mappings"):
            seeds.snapshot({**self.config, "path_mappings": [{"from": "x", "to": "y"}]}, self.root, self.seed)
        with self.assertRaisesRegex(StudioError, "configured .exe"):
            seeds.snapshot({**self.config, "executables": {}}, self.root, self.seed)
        (self.engine.parent / "_sc_").touch()
        with self.assertRaisesRegex(StudioError, "self-contained"):
            seeds.snapshot(self.config, self.root, self.seed)

    def test_maximum_eight_exact_one_mib_files_copy_without_normalizing(self):
        raw = b"\r\n" * (seeds.MAX_FILE_BYTES // 2)
        self.source.write_bytes(raw)
        declared = {"platform": "windows", "files": [
            {"source": "settings.cfg", "target": f"seed/{i}.cfg", "sha256": sha256(self.source)}
            for i in range(8)]}
        snapshot = seeds.snapshot(self.config, self.root, declared)
        folder = self.root / "profile"
        snapshot.prepare(folder)
        snapshot.recheck(folder)
        self.assertEqual(sum(item["bytes"] for item in snapshot.receipt["files"]), 8 * 1024 * 1024)
        self.assertEqual((folder / "seed/7.cfg").read_bytes(), raw)

    def test_existing_profile_is_not_reused_or_overwritten(self):
        snapshot = seeds.snapshot(self.config, self.root, self.seed)
        folder = self.root / "profile"
        folder.mkdir()
        (folder / "keep").write_bytes(b"keep")
        with self.assertRaisesRegex(StudioError, "preparation failed"):
            snapshot.prepare(folder)
        self.assertEqual((folder / "keep").read_bytes(), b"keep")

    def test_linked_source_and_artifacts_ancestry_are_refused(self):
        actual = self.root / "actual.cfg"
        actual.write_bytes(self.raw)
        self.source.unlink()
        try:
            self.source.symlink_to(actual)
        except OSError as exc:
            self.skipTest(f"native symlink capability unavailable: {getattr(exc, 'winerror', None) or exc.errno}")
        with self.assertRaisesRegex(StudioError, "link or reparse"):
            seeds.snapshot(self.config, self.root, self.seed)
        self.source.unlink()
        self.source.write_bytes(self.raw)
        owned = self.root / "owned"
        owned.mkdir()
        (self.root / "artifacts").symlink_to(owned, target_is_directory=True)
        with self.assertRaisesRegex(StudioError, "link or reparse"):
            self.execute()
        self.assertEqual(list(owned.iterdir()), [])

    def test_windows_reparse_attribute_is_refused_before_resolve(self):
        original = Path.lstat
        def linked(path):
            result = original(path)
            if path == self.source:
                class Reparse:
                    st_mode = result.st_mode
                    st_file_attributes = 0x400
                return Reparse()
            return result
        with patch.object(Path, "lstat", linked), self.assertRaisesRegex(StudioError, "reparse"):
            seeds.snapshot(self.config, self.root, self.seed)

    def test_hardlinked_source_is_refused(self):
        try:
            os.link(self.source, self.root / "alias.cfg")
        except OSError as exc:
            self.skipTest(f"native hardlink capability unavailable: {getattr(exc, 'winerror', None) or exc.errno}")
        with self.assertRaisesRegex(StudioError, "regular files"):
            seeds.snapshot(self.config, self.root, self.seed)

    def test_hardlink_count_refuses_even_with_correct_declared_bytes(self):
        original = Path.lstat
        def linked(path):
            result = original(path)
            if path == self.source:
                class Hardlink:
                    st_mode = result.st_mode
                    st_nlink = 2
                return Hardlink()
            return result
        with patch.object(Path, "lstat", linked), self.assertRaisesRegex(StudioError, "regular files"):
            seeds.snapshot(self.config, self.root, self.seed)

    def test_linked_output_ancestor_refuses_before_label_reservation(self):
        artifacts = self.root / "artifacts"
        artifacts.mkdir()
        original = Path.lstat
        def linked(path):
            result = original(path)
            if path == artifacts:
                class Reparse:
                    st_mode = result.st_mode
                    st_file_attributes = 0x400
                return Reparse()
            return result
        with patch.object(Path, "lstat", linked), self.assertRaisesRegex(StudioError, "reparse"):
            self.execute()
        self.assertEqual(list(artifacts.iterdir()), [])


class RuntimeTests(SeedCase):
    def test_launch_and_playtest_copy_exact_raw_bytes_before_child(self):
        for command in ("launch", "playtest"):
            with self.subTest(command=command):
                result, run = self.execute(command)
                self.assertEqual(run.call_count, 1)
                self.assertTrue(result["ok"])
                receipt = result["profile_seed"]
                self.assertEqual(receipt["status"], "verified_before_spawn")
                self.assertEqual(receipt["files"][0]["copied_sha256"], sha256(self.source))
                self.assertEqual(receipt["files"][0]["bytes"], len(self.raw))
                self.assertGreaterEqual(receipt["setup_seconds"], 0)
                folder = Path(result["run_dir"])
                for path in folder.glob("*.json"):
                    self.assertNotIn("private-setting", path.read_text())
                    self.assertNotIn(str(self.source), path.read_text())
                if command == "playtest":
                    name = "relaunch.cmd" if playtest.IS_WINDOWS else "relaunch.sh"
                    self.assertIn("does not reproduce profile seed initialization", (folder / name).read_text())

    def test_no_seed_defaults_keep_an_empty_profile_and_no_seed_receipt(self):
        self.seed = None
        for command in ("launch", "playtest"):
            with self.subTest(command=command):
                result, run = self.execute(command)
                run.assert_called_once()
                self.assertTrue(result["ok"])
                self.assertNotIn("profile_seed", result)

    def test_sources_destinations_and_profile_json_changed_during_baseline_refuse(self):
        for command in ("launch", "playtest"):
            for changed in ("source", "destination", "profile", "source_missing", "destination_directory"):
                label = f"{command}-{changed}"
                namespace = "launches" if command == "launch" else "playtests"
                target = self.root / f"artifacts/{namespace}/{label}/profile" / self.seed["files"][0]["target"]
                self.source.write_bytes(self.raw)
                named = self.root / "profile.json"
                named.write_bytes(b"{}")
                claim = {"path": "profile.json", "sha256": sha256(named)}
                def tamper(**kwargs):
                    if changed == "source":
                        self.source.write_bytes(b"tampered")
                    elif changed == "source_missing":
                        self.source.unlink()
                    elif changed == "profile":
                        named.write_bytes(b"changed")
                    elif changed == "destination_directory":
                        target.unlink()
                        target.mkdir()
                    else:
                        target.write_bytes(b"tampered")
                    return {}
                module = launch if command == "launch" else playtest
                with self.subTest(command=command, changed=changed):
                    with patch.object(module, "prelaunch_baseline", side_effect=tamper), patch.object(module, "run") as run:
                        result = module.execute(self.config, self.root, sha256_expected=sha256(self.engine),
                                                label=label, profile_seed=self.seed, launch_profile=claim)
                    run.assert_not_called()
                    self.assertEqual(result["verdict"], "profile_seed_refused")
                    self.assertEqual(result["profile_seed"]["status"], "refused")
                    self.assertEqual(result["status"], "refused")
                    self.assertIsNone(result["process_record"])

    def test_attended_route_prepares_and_rechecks_before_start(self):
        def fake(args, **kwargs):
            self.assertEqual(self.target("playtest").read_bytes(), self.raw)
            job = kwargs["job_dir"]
            job.mkdir()
            write_json(job / "process.json", {"schema_version": 1, "pid": 111, "status": "launched"})
            (job / "stdout.log").write_text("Godot Engine fake\n")
            return {"pid": 111, "process_record": str(job / "process.json"), "log": str(job / "stdout.log")}
        with patch.object(playtest, "start", side_effect=fake) as start:
            result, run = self.execute("playtest", session="attended", emit_launcher=False)
        start.assert_called_once()
        run.assert_not_called()
        self.assertEqual(result["profile_seed"]["status"], "verified_before_spawn")
        with patch.object(playtest, "alive", return_value=False):
            collected = playtest.collect(self.config, self.root, "seeded")
        self.assertEqual(collected["verdict"], "collected")
        self.assertEqual(collected["profile_seed"], result["profile_seed"])
        self.assertEqual(collected["acceptance"], "not_established")

    def test_attended_tamper_after_preparation_is_refused_before_start(self):
        original = seeds.Snapshot.prepare
        def tamper(snapshot, folder):
            original(snapshot, folder)
            self.target("playtest").write_bytes(b"changed")
        with patch.object(seeds.Snapshot, "prepare", tamper), patch.object(playtest, "start") as start:
            result, run = self.execute("playtest", session="attended", emit_launcher=False)
        start.assert_not_called()
        self.assertEqual(result["verdict"], "profile_seed_refused")

    def test_replaced_owned_profile_refuses_even_when_seed_bytes_still_match(self):
        def replace(**kwargs):
            target = self.target()
            folder = target.parents[3]
            folder.rename(folder.with_name("held-profile"))
            target.parent.mkdir(parents=True)
            target.write_bytes(self.raw)
            return {}
        with patch.object(launch, "prelaunch_baseline", side_effect=replace):
            result, run = self.execute()
        run.assert_not_called()
        self.assertEqual(result["verdict"], "profile_seed_refused")
        self.assertIn("owned profile changed", result["failure"])

    def test_destination_reparse_component_introduced_after_copy_refuses(self):
        original = Path.lstat
        tampered = False
        def baseline(**kwargs):
            nonlocal tampered
            tampered = True
            return {}
        def reparse(path):
            result = original(path)
            if tampered and path == self.target().parent:
                class Reparse:
                    st_mode = result.st_mode
                    st_file_attributes = 0x400
                return Reparse()
            return result
        with patch.object(launch, "prelaunch_baseline", side_effect=baseline), patch.object(Path, "lstat", reparse):
            result, run = self.execute()
        run.assert_not_called()
        self.assertEqual(result["verdict"], "profile_seed_refused")
        self.assertIn("reparse", result["failure"])

    def test_copy_failure_and_existing_profile_after_label_reservation_refuse(self):
        original = seeds.Snapshot.prepare
        def existing(snapshot, folder):
            folder.mkdir()
            (folder / "keep").write_bytes(b"keep")
            original(snapshot, folder)
        with patch.object(seeds.Snapshot, "prepare", existing):
            result, run = self.execute()
        run.assert_not_called()
        self.assertEqual(result["verdict"], "profile_seed_refused")
        self.assertEqual((self.target().parents[3] / "keep").read_bytes(), b"keep")

    def test_reused_label_refuses_without_changing_prepared_file(self):
        self.execute()
        with self.assertRaisesRegex(StudioError, "directory exists"):
            self.execute()
        self.assertEqual(self.target().read_bytes(), self.raw)

    def test_cutoff_is_last_after_seed_setup_recheck_and_engine_rehash(self):
        before = datetime.now(timezone.utc)
        cutoff = before + timedelta(seconds=1)
        class Clock:
            fromisoformat = staticmethod(datetime.fromisoformat)
            calls = 0
            @classmethod
            def now(cls, tz=None):
                cls.calls += 1
                return before if cls.calls == 1 else cutoff + timedelta(seconds=1)
        with patch.object(launch, "datetime", Clock):
            result, run = self.execute(cutoff_utc=cutoff.isoformat())
        run.assert_not_called()
        self.assertEqual(result["verdict"], "cutoff_passed")
        self.assertEqual(result["profile_seed"]["status"], "verified_before_spawn")
        self.assertEqual(self.target().read_bytes(), self.raw)

    def test_direct_api_refuses_invalid_seed_before_label_reservation(self):
        self.seed["files"][0]["sha256"] = "0" * 64
        for command in ("launch", "playtest"):
            with self.subTest(command=command), self.assertRaisesRegex(StudioError, "mismatch"):
                self.execute(command)
        self.assertFalse((self.root / "artifacts").exists())

    def test_exclusive_copy_does_not_overwrite_a_file_created_during_preparation(self):
        original = Path.open
        def occupied(path, mode="r", *args, **kwargs):
            if mode == "xb":
                with original(path, "wb") as stream:
                    stream.write(b"keep-existing")
            return original(path, mode, *args, **kwargs)
        with patch.object(Path, "open", occupied):
            result, run = self.execute()
        run.assert_not_called()
        self.assertEqual(result["verdict"], "profile_seed_refused")
        self.assertEqual(self.target().read_bytes(), b"keep-existing")
        self.assertIsNone(result["profile_seed"]["files"][0]["copied_sha256"])

    def test_baseline_failure_keeps_a_refusal_receipt_and_starts_nothing(self):
        for command in ("launch", "playtest"):
            module = launch if command == "launch" else playtest
            with self.subTest(command=command), patch.object(module, "prelaunch_baseline", side_effect=StudioError("private failure")):
                result, run = self.execute(command)
            run.assert_not_called()
            self.assertEqual(result["verdict"], "profile_seed_refused")
            self.assertEqual(result["status"], "refused")
            self.assertNotIn("private failure", json.dumps(result))

    def test_interrupted_copy_records_interruption_and_does_not_start(self):
        for command in ("launch", "playtest"):
            module = launch if command == "launch" else playtest
            with self.subTest(command=command), patch.object(seeds.Snapshot, "prepare", side_effect=KeyboardInterrupt), patch.object(module, "run") as run:
                with self.assertRaises(KeyboardInterrupt):
                    self.execute(command)
            run.assert_not_called()
            namespace = "launches" if command == "launch" else "playtests"
            receipt = read_json(self.root / f"artifacts/{namespace}/seeded/exit.json")
            self.assertEqual(receipt["verdict"], "interrupted")
            self.assertEqual(receipt["profile_seed"]["status"], "refused")


    def test_interrupted_final_recheck_records_terminal_receipts_without_spawn(self):
        for command, session in (("launch", None), ("playtest", "handoff"), ("playtest", "attended")):
            with self.subTest(command=command, session=session):
                label = f"recheck-interrupt-{command}-{session or 'owned'}"
                module = launch if command == "launch" else playtest
                with patch.object(seeds.Snapshot, "recheck", side_effect=KeyboardInterrupt), \
                     patch.object(module, "run") as run, \
                     contextlib.ExitStack() as stack:
                    start = stack.enter_context(patch.object(playtest, "start")) if command == "playtest" else None
                    kwargs = {"sha256_expected": sha256(self.engine), "label": label,
                              "profile_seed": self.seed}
                    if command == "playtest":
                        kwargs.update(session=session, emit_launcher=False)
                    with self.assertRaises(KeyboardInterrupt):
                        module.execute(self.config, self.root, **kwargs)
                run.assert_not_called()
                if start is not None:
                    start.assert_not_called()
                namespace = "launches" if command == "launch" else "playtests"
                directory = self.root / f"artifacts/{namespace}/{label}"
                name = "owned-launch.json" if command == "launch" else "playtest.json"
                beginning = read_json(directory / name)
                end = read_json(directory / "exit.json")
                self.assertEqual(beginning["status"], "interrupted")
                self.assertIsNone(beginning["process_record"])
                self.assertIsNone(beginning["pid"])
                self.assertEqual(end["verdict"], "interrupted")
                self.assertEqual(end["profile_seed"]["status"], "refused")
                self.assertFalse((directory / "process/process.json").exists())


class ResolutionTests(SeedCase):
    def named_profile(self, command="playtest"):
        path = self.root / "play.json"
        words = [f"--public-example-{index}" for index in range(120)]
        write_json(path, {"schema_version": 1, "kind": "launch-profile", "command": command,
                         "profile_seed": self.seed, "passthrough": words})
        return path, words

    def test_check_validates_real_seed_and_preserves_all_120_words_in_resolution(self):
        path, words = self.named_profile()
        checked = profile.resolve(self.config, self.root, "playtest", {}, path=path, check=True)
        self.assertTrue(checked["refused"]["ok"])
        self.assertEqual(checked["refused"]["passthrough_count"], 120)
        self.assertEqual(checked["refused"]["profile_seed"]["status"], "validated")
        resolved = profile.resolve(self.config, self.root, "playtest", {}, path=path)
        self.assertEqual(resolved["arguments"]["passthrough"], ["--", *words])
        self.assertEqual(resolved["arguments"]["profile_seed"], self.seed)
        self.assertFalse((self.root / "artifacts").exists())
        self.assertNotIn("private-setting", json.dumps(checked))

    def test_check_catches_hash_platform_and_host_conflicts_without_child_or_profile(self):
        path, _ = self.named_profile()
        with self.assertRaisesRegex(StudioError, "conflicts"):
            profile.resolve(self.config, self.root, "playtest", {}, path=path, check=True, use_host_profile=True)
        with patch.object(seeds, "IS_WINDOWS", False), self.assertRaisesRegex(StudioError, "native Windows"):
            profile.resolve(self.config, self.root, "playtest", {}, path=path, check=True)
        self.source.write_bytes(b"changed")
        with self.assertRaisesRegex(StudioError, "mismatch"):
            profile.resolve(self.config, self.root, "playtest", {}, path=path, check=True)
        self.assertFalse((self.root / "artifacts").exists())

    def test_cli_forwards_seeds_for_both_commands_and_check_host_conflict(self):
        host = Path(self.tmp.name) / "host.json"
        write_json(host, self.config)
        for command in ("launch", "playtest"):
            path, _ = self.named_profile(command)
            args = [command, *(["start"] if command == "playtest" else []), "--project", str(self.root),
                    "--config", str(host), "--profile", path.name, "--sha256", sha256(self.engine)]
            module = launch if command == "launch" else playtest
            with patch.object(module, "execute", return_value={"ok": True}) as execute:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(cli.main(args), 0)
                self.assertEqual(execute.call_args.kwargs["profile_seed"], self.seed)
            if command == "playtest":
                with patch.object(module, "execute") as execute:
                    with contextlib.redirect_stderr(io.StringIO()) as err:
                        self.assertEqual(cli.main([*args, "--check", "--use-host-profile"]), 1)
                    self.assertIn("conflicts", err.getvalue())
                    execute.assert_not_called()
        self.assertFalse((self.root / "artifacts").exists())

    def test_unknown_original_metadata_stays_refused(self):
        path, _ = self.named_profile()
        record = read_json(path)
        for name in ("settings_override", "source", "status"):
            with self.subTest(name=name):
                write_json(path, {**record, name: "legacy"})
                with self.assertRaisesRegex(StudioError, "not a playtest field"):
                    profile.load(self.root, path)


if __name__ == "__main__":
    unittest.main()
