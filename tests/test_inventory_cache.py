"""Inventory parity, traversal pruning and explicitly advisory hash reuse."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from studio_tools import evidence
from studio_tools.common import StudioError, digest, file_record, read_json, write_json


def legacy_inventory(root, *, portable=True):
    root = Path(root).resolve()
    return evidence.canonical_inventory([
        file_record(root, path) for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
        and not any(part in evidence.EXCLUDED for part in path.relative_to(root).parts)
        and path.name != ".studio-local.json"
    ], portable=portable)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="studio inventory ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.put("project.godot", "project")
        self.put("assets/one.bin", "abcd")

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def cached(self):
        stats = {}
        files = evidence.inventory(self.root, cache=True, stats=stats)
        return files, stats

    def test_exact_legacy_parity_and_excluded_file_names(self):
        for folder in evidence.EXCLUDED:
            self.put(f"nested/{folder}/deep/ignored.bin", "ignored")
            self.put(f"file-names/{folder}", "excluded file name")
        self.put("nested/.studio-local.json", "host")
        self.put("assets/Élan.bin", "unicode")
        for portable in (True, False):
            old = legacy_inventory(self.root, portable=portable)
            new = evidence.inventory(self.root, portable=portable)
            self.assertEqual(json.dumps(old), json.dumps(new))
            self.assertEqual(digest(old), digest(new))

    def test_excluded_directories_are_never_entered(self):
        for folder in evidence.EXCLUDED:
            for index in range(4):
                self.put(f"nested/{folder}/deep/{index}.txt", "ignored")
        scanned = []
        original = os.scandir
        expected = legacy_inventory(self.root)

        def scandir(path):
            path = Path(path)
            self.assertFalse(any(part in evidence.EXCLUDED for part in path.relative_to(self.root).parts))
            scanned.append(path)
            return original(path)

        with patch("studio_tools.evidence.os.scandir", side_effect=scandir):
            self.assertEqual(evidence.inventory(self.root), expected)
        self.assertIn(self.root / "nested", scanned)

    def test_walk_error_fails_closed(self):
        self.put("unreadable/inside.txt", "content")
        original = os.scandir

        def scandir(path):
            if Path(path).name == "unreadable":
                raise PermissionError("fixture subtree cannot be listed")
            return original(path)

        with patch("studio_tools.evidence.os.scandir", side_effect=scandir):
            with self.assertRaises(PermissionError):
                evidence.inventory(self.root, cache=True)
        self.assertFalse((self.root / ".studio/inventory-cache.json").exists())

    def test_directory_and_file_symlink_parity(self):
        external = Path(self.temp.name) / "external"
        external.mkdir()
        (external / "outside.txt").write_text("outside")
        try:
            (self.root / "directory-link").symlink_to(external, target_is_directory=True)
            (self.root / "file-link").symlink_to(self.root / "assets/one.bin")
        except OSError as exc:
            self.skipTest(f"Host cannot create symlinks: {exc}")
        self.assertEqual(evidence.inventory(self.root), legacy_inventory(self.root))
        self.assertFalse(any("link" in item["path"] for item in evidence.inventory(self.root)))

    def junction(self, source, target):
        if os.name != "nt":
            self.skipTest("Windows junction observation")
        import _winapi
        try:
            _winapi.CreateJunction(str(source), str(target))
        except OSError as exc:
            self.skipTest(f"Host cannot create junctions: {exc}")

    def test_junction_descent_preserves_legacy_alias_rejection(self):
        self.junction(self.root / "assets", self.root / "junction")
        with self.assertRaisesRegex(StudioError, "Duplicate"):
            legacy_inventory(self.root)
        with self.assertRaisesRegex(StudioError, "Duplicate"):
            evidence.inventory(self.root)

    def test_cache_does_not_write_through_junction(self):
        external = Path(self.temp.name) / "external"
        external.mkdir()
        self.junction(external, self.root / ".studio")
        files, stats = self.cached()
        self.assertEqual(files, legacy_inventory(self.root))
        self.assertEqual(stats["method"], "byte-hashed")
        self.assertEqual(list(external.iterdir()), [])

    def test_cache_does_not_read_or_replace_symlinked_file(self):
        external = Path(self.temp.name) / "external-cache.json"
        external.write_text("external sentinel")
        folder = self.root / ".studio"
        folder.mkdir()
        try:
            (folder / "inventory-cache.json").symlink_to(external)
        except OSError as exc:
            self.skipTest(f"Host cannot create symlinks: {exc}")
        _, stats = self.cached()
        self.assertEqual(stats["method"], "byte-hashed")
        self.assertEqual(external.read_text(), "external sentinel")

    def test_cached_receipts_stay_unknown_and_cannot_claim_current(self):
        candidate = evidence.new_candidate(self.root, "trust", "4.5", "fixture")
        note = self.put("artifacts/note.txt", "human observed silhouette")
        row = {**file_record(self.root, note), "content_digest": candidate["content_digest"],
               "method": "native_visual", "observer": "fixture observer", "identity": "current"}
        receipt = {"content_digest": candidate["content_digest"],
                   "content_identity_method": "metadata-cached"}
        self.assertEqual(evidence.receipt_identity(receipt, candidate), "unknown")
        attached = evidence.attach_evidence(candidate, "visual", row, receipt=receipt)
        self.assertEqual(attached["identity"], "unknown")
        self.assertEqual(attached["content_identity_method"], "metadata-cached")
        self.assertEqual(attached["observer"], "fixture observer")
        self.assertEqual(candidate["verdicts"]["visual"]["evidence_current"], 0)
        evidence.validate_candidate(candidate, self.root)
        attached["identity"] = "current"  # Caller override cannot bypass trust.
        with self.assertRaisesRegex(StudioError, "byte-hashed"):
            evidence.validate_candidate(candidate, self.root)
        strict = {**receipt, "content_identity_method": "byte-hashed"}
        self.assertEqual(evidence.receipt_identity(strict, candidate), "current")
        conflicting = evidence.attach_evidence(
            candidate, "motion", {**row, "content_identity_method": "metadata-cached"}, receipt=strict)
        self.assertEqual(conflicting["identity"], "unknown")
        self.assertEqual(conflicting["content_identity_method"], "metadata-cached")

    def test_cold_warm_change_touch_add_delete_and_corruption(self):
        cold, first = self.cached()
        self.assertEqual(cold, legacy_inventory(self.root))
        self.assertEqual(first["cache_hits"], 0)
        with patch("studio_tools.evidence.file_record", wraps=file_record) as hashed:
            warm, second = self.cached()
        self.assertEqual(warm, cold)
        self.assertEqual(second, {"files": 2, "cache_hits": 2, "method": "metadata-cached"})
        hashed.assert_not_called()
        path = self.root / "assets/one.bin"
        old_time = path.stat().st_mtime_ns
        os.utime(path, ns=(old_time, old_time + 1_000_000_000))
        touched, stats = self.cached()
        self.assertEqual(touched, cold)
        self.assertEqual(stats["cache_hits"], 1)
        path.write_text("wxyz")
        changed, stats = self.cached()
        self.assertNotEqual(changed, cold)
        self.assertEqual(stats["cache_hits"], 1)
        added = self.put("assets/two.bin", "new")
        self.assertEqual(len(self.cached()[0]), 3)
        added.unlink()
        self.assertEqual(self.cached()[0], changed)
        cache = self.root / ".studio/inventory-cache.json"
        self.assertNotIn("assets/two.bin", read_json(cache)["files"])
        cache.write_text("broken JSON")
        recovered, stats = self.cached()
        self.assertEqual(recovered, changed)
        self.assertEqual(stats["cache_hits"], 0)
        self.assertEqual(read_json(cache)["schema_version"], 1)
        path.write_text("abcd")
        self.assertEqual(self.cached()[0], cold)

    def test_cache_io_errors_fall_back_to_hashing(self):
        expected = evidence.inventory(self.root)
        with patch("studio_tools.evidence._cache_path", side_effect=OSError("unsafe cache")):
            files, stats = self.cached()
        self.assertEqual(files, expected)
        self.assertEqual(stats["method"], "byte-hashed")
        with patch("studio_tools.evidence.write_json", side_effect=OSError("cache write failed")):
            self.assertEqual(self.cached()[0], expected)

    def test_change_during_hash_cannot_publish_reusable_cache(self):
        original = file_record

        def changing(root, path):
            result = original(root, path)
            if Path(path).name == "one.bin":
                Path(path).write_text("changed while hashing")
            return result

        with patch("studio_tools.evidence.file_record", side_effect=changing):
            with self.assertRaisesRegex(StudioError, "changed while inventorying"):
                self.cached()
        self.assertFalse((self.root / ".studio/inventory-cache.json").exists())

    def test_candidate_remains_strict_when_metadata_cache_is_stale(self):
        candidate = evidence.new_candidate(self.root, "strict", "4.5", "fixture")
        candidate["content_files"] = legacy_inventory(self.root)
        candidate["content_digest"] = digest(candidate["content_files"])
        evidence.validate_candidate(candidate, self.root)
        self.cached()
        path = self.root / "assets/one.bin"
        before = path.stat()
        path.write_text("wxyz")  # same size, restored modification time
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        # Deliberately forge all cache metadata to demonstrate its trust limit.
        cache = self.root / ".studio/inventory-cache.json"
        record = read_json(cache)
        record["files"]["assets/one.bin"]["metadata"] = evidence._file_metadata(path)
        write_json(cache, record)
        self.assertEqual(digest(self.cached()[0]), candidate["content_digest"])
        with self.assertRaises(StudioError):
            evidence.validate_candidate(candidate, self.root)
        self.assertNotEqual(digest(evidence.inventory(self.root)), candidate["content_digest"])


if __name__ == "__main__":
    unittest.main()
