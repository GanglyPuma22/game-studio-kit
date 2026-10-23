"""`studio assets` (offline): the source catalogue, licence rules, downloads and the ledger.

The helper's urlopen is replaced with a fake that serves canned bytes; no test
reaches the network.
"""

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
import urllib.error
import zipfile
from unittest.mock import patch

from studio_tools import assets, cli
from studio_tools.common import StudioError, read_json

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/studio-assets/SKILL.md"
GUIDE = ROOT / "skills/studio-assets/references/sources.md"


class FakeResponse(io.BytesIO):
    def __init__(self, body, content_type="application/octet-stream", length=True):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}
        if length:
            self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeWeb:
    def __init__(self, routes):
        self.routes = copy.deepcopy(routes)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        url = request.full_url
        if url not in self.routes:
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        value = self.routes[url]
        if isinstance(value, FakeResponse):
            value.seek(0)
            return value
        if isinstance(value, (dict, list)):
            return FakeResponse(json.dumps(value).encode(), "application/json")
        return FakeResponse(value)


def md5(data):
    return hashlib.md5(data).hexdigest()


DIFFUSE = b"diffuse-bytes"
NORMAL = b"normal-bytes"
PH = "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/brick/"
POLYHAVEN = {
    "https://api.polyhaven.com/info/brick": {"type": 1, "name": "Brick", "authors": {"A": "Photo", "B": "Proc"}},
    "https://api.polyhaven.com/files/brick": {
        "Diffuse": {"1k": {"jpg": {"url": PH + "brick_diffuse_1k.jpg", "md5": md5(DIFFUSE)}}},
        "nor_gl": {"1k": {"jpg": {"url": PH + "brick_nor_gl_1k.jpg", "md5": md5(NORMAL)}}},
    },
    PH + "brick_diffuse_1k.jpg": DIFFUSE,
    PH + "brick_nor_gl_1k.jpg": NORMAL,
}


class AssetsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="studio assets ")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def web(self, routes):
        fake = FakeWeb(routes)
        patcher = patch.object(assets, "_urlopen", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def ledger(self):
        return read_json(self.root / "assets/third_party/ledger.json")


class CatalogueTests(unittest.TestCase):
    def test_every_source_is_described_in_the_guide_and_has_known_fields(self):
        data = read_json(assets.CATALOG)
        guide = GUIDE.read_text(encoding="utf-8")
        routes = set(data["route_meanings"])
        for s in data["sources"]:
            self.assertIn("`" + s["id"] + "`", guide, s["id"])
            self.assertIn(s["route"], routes, s["id"])
            self.assertTrue(s["url"].startswith("https://") and s["licence_url"].startswith("https://"))
            self.assertIn(s["licence_scope"], {"site", "asset"})
            if s["licence_scope"] == "site":
                self.assertIn(s["licence"], {"CC0-1.0"}, s["id"])

    def test_the_users_starting_list_is_all_catalogued(self):
        ids = {s["id"] for s in read_json(assets.CATALOG)["sources"]}
        self.assertLessEqual({"polyhaven", "ambientcg", "sharetextures", "cgbookcase", "texturecan",
                              "thebasemesh", "quaternius", "kenney", "polypizza", "opengameart",
                              "itch", "blendswap"}, ids)

    def test_kind_filter(self):
        result = assets.catalog("hdris")
        self.assertTrue(result["sources"])
        self.assertTrue(all("hdris" in s["kinds"] for s in result["sources"]))

    def test_skill_names_its_command(self):
        self.assertIn("`studio assets", SKILL.read_text(encoding="utf-8"))


class FetchTests(AssetsCase):
    def test_polyhaven_texture_is_fetched_md5_checked_and_ledgered(self):
        self.web(POLYHAVEN)
        result = assets.fetch_polyhaven(self.root, None, "brick")
        self.assertEqual(result["licence"], "CC0-1.0")
        self.assertEqual(len(result["files"]), 2)
        entry = self.ledger()["assets"][0]
        self.assertEqual(entry["asset_id"], "polyhaven/brick")
        self.assertEqual(entry["author"], "A, B")
        self.assertTrue(entry["refetchable"])
        first = self.root / entry["files"][0]["path"]
        self.assertEqual(first.read_bytes(), DIFFUSE)
        self.assertEqual(result["provenance"]["file"]["sha256"], hashlib.sha256(DIFFUSE).hexdigest())

    def test_md5_mismatch_keeps_nothing(self):
        routes = dict(POLYHAVEN)
        routes[PH + "brick_diffuse_1k.jpg"] = b"tampered"
        self.web(routes)
        with self.assertRaisesRegex(StudioError, "md5"):
            assets.fetch_polyhaven(self.root, None, "brick", maps=["Diffuse"])
        self.assertEqual(list((self.root / "assets/third_party/polyhaven/brick/1k").iterdir()), [])
        self.assertFalse((self.root / "assets/third_party/ledger.json").exists())

    def test_ambientcg_picks_the_requested_variant(self):
        url = "https://ambientcg.com/get?file=Bricks076C_1K-JPG.zip"
        self.web({
            "https://ambientcg.com/api/v2/full_json?id=Bricks076C&include=downloadData": {"foundAssets": [{
                "assetId": "Bricks076C", "displayName": "Bricks 076 C", "dataType": "Material",
                "downloadFolders": {"default": {"downloadFiletypeCategories": {"zip": {"downloads": [
                    {"attribute": "1K-JPG", "fullDownloadPath": url, "fileName": "Bricks076C_1K-JPG.zip"},
                    {"attribute": "2K-JPG", "fullDownloadPath": url + "2", "fileName": "x.zip"}]}}}}}]},
            url: b"zip-bytes",
        })
        result = assets.fetch_ambientcg(self.root, None, "Bricks076C")
        self.assertTrue(result["files"][0]["path"].endswith("Bricks076C_1K-JPG.zip"))
        with self.assertRaisesRegex(StudioError, "offered: 1K-JPG, 2K-JPG"):
            assets.fetch_ambientcg(self.root, None, "Bricks076C", "8K")

    def test_site_wide_cc0_source_fills_the_licence_and_rejects_a_different_one(self):
        url = "https://kenney.nl/media/pages/assets/kit/abc/kenney_kit_10.zip"
        self.web({url: b"kit"})
        result = assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/kit", None, "Kenney",
                                  source="kenney")
        self.assertEqual(result["licence"], "CC0-1.0")
        self.assertEqual(result["asset_id"], "kenney/kenney_kit_10")
        with self.assertRaisesRegex(StudioError, "disagree"):
            assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/kit", "CC-BY-4.0", "Kenney",
                             attribution="x", source="kenney")

    def test_per_asset_sources_need_a_reusable_licence_and_cc_by_needs_attribution(self):
        url = "https://opengameart.org/sites/default/files/house.zip"
        self.web({url: b"house"})
        page = "https://opengameart.org/content/house"
        with self.assertRaisesRegex(StudioError, "--licence is required"):
            assets.fetch_url(self.root, None, url, page, None, "A", source="opengameart")
        for bad in ("CC-BY-SA 3.0", "CC BY-NC 4.0", "GPL-3.0", "free for personal use"):
            with self.assertRaisesRegex(StudioError, "not reusable"):
                assets.fetch_url(self.root, None, url, page, bad, "A", source="opengameart")
        with self.assertRaisesRegex(StudioError, "--attribution"):
            assets.fetch_url(self.root, None, url, page, "CC BY 4.0", "A", source="opengameart")
        result = assets.fetch_url(self.root, None, url, page, "cc_by-4.0", "A",
                                  attribution="House by A, CC BY 4.0", source="opengameart")
        self.assertEqual(result["licence"], "CC-BY-4.0")

    def test_a_web_page_instead_of_a_file_is_refused(self):
        url = "https://www.blendswap.com/blend/1/download"
        self.web({url: FakeResponse(b"<html>Log in</html>", "text/html; charset=utf-8")})
        with self.assertRaisesRegex(StudioError, "web page"):
            assets.fetch_url(self.root, None, url, "https://www.blendswap.com/blend/1", "CC0", "A",
                             source="blendswap")

    def test_size_cap_keeps_nothing(self):
        url = "https://kenney.nl/big.zip"
        self.web({url: b"x" * 2048})
        with self.assertRaisesRegex(StudioError, "max-mb"):
            assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/big", None, "K",
                             source="kenney", max_bytes=1024)
        self.assertFalse(any((self.root / "assets/third_party/kenney/big").iterdir()))

    def test_http_only_and_referer_are_enforced(self):
        with self.assertRaisesRegex(StudioError, "HTTPS"):
            assets.fetch_url(self.root, None, "http://kenney.nl/a.zip", "https://kenney.nl/a", None, "K",
                             source="kenney")
        url = "https://cgbookcase-volume.b-cdn.net/t/Moss_1K.zip"
        fake = self.web({url: b"moss"})
        assets.fetch_url(self.root, None, url, "https://www.cgbookcase.com/textures/moss", None, "",
                         source="cgbookcase", referer="https://www.cgbookcase.com/")
        self.assertEqual(fake.requests[-1].get_header("Referer"), "https://www.cgbookcase.com/")
        self.assertIn("game-studio-kit", fake.requests[-1].get_header("User-agent"))
        self.assertEqual(self.ledger()["assets"][0]["referer"], "https://www.cgbookcase.com/")

    def test_extract_unpacks_beside_the_original_and_refuses_escaping_names(self):
        def make(names):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                for n in names:
                    z.writestr(n, "x")
            return buf.getvalue()
        good, bad = "https://kenney.nl/good.zip", "https://kenney.nl/bad.zip"
        self.web({good: make(["Models/a.glb", "License.txt"]), bad: make(["../../evil.txt"])})
        result = assets.fetch_url(self.root, None, good, "https://kenney.nl/assets/good", None, "K",
                                  source="kenney", extract=True)
        self.assertTrue((self.root / "assets/third_party/kenney/good/extracted/Models/a.glb").is_file())
        self.assertEqual(self.ledger()["assets"][0]["files"][0]["extracted_to"],
                         "assets/third_party/kenney/good/extracted")
        self.assertIn("good.zip", result["files"][0]["path"])
        with self.assertRaises(StudioError):
            assets.fetch_url(self.root, None, bad, "https://kenney.nl/assets/bad", None, "K",
                             source="kenney", extract=True)
        self.assertFalse((self.root / "evil.txt").exists())
        self.assertFalse((self.root / "assets/third_party/kenney/bad/bad.zip").exists())


    def test_a_symlinked_asset_folder_pointing_outside_is_refused_before_writing(self):
        outside = tempfile.TemporaryDirectory(prefix="studio outside ")
        self.addCleanup(outside.cleanup)
        victim = Path(outside.name) / "kit.zip"
        victim.write_bytes(b"precious")
        link = self.root / "assets/third_party/kenney/kit"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside.name, target_is_directory=True)
        url = "https://kenney.nl/kit.zip"
        fake = self.web({url: b"new"})
        with self.assertRaises(StudioError):
            assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/kit", None, "K", source="kenney")
        self.assertEqual(victim.read_bytes(), b"precious")
        self.assertEqual(fake.requests, [])

    def test_a_failed_later_file_leaves_the_earlier_ones_untouched(self):
        web = self.web(POLYHAVEN)
        assets.fetch_polyhaven(self.root, None, "brick")
        diffuse = self.root / "assets/third_party/polyhaven/brick/1k/brick_diffuse_1k.jpg"
        changed = b"new diffuse"
        web.routes["https://api.polyhaven.com/files/brick"]["Diffuse"]["1k"]["jpg"]["md5"] = md5(changed)
        web.routes[PH + "brick_diffuse_1k.jpg"] = changed
        del web.routes[PH + "brick_nor_gl_1k.jpg"]
        with self.assertRaisesRegex(StudioError, "HTTP 404"):
            assets.fetch_polyhaven(self.root, None, "brick")
        self.assertEqual(diffuse.read_bytes(), DIFFUSE)
        self.assertTrue(assets.verify(self.root, None)["ok"])
        self.assertEqual([p.name for p in diffuse.parent.iterdir() if p.suffix == ".part"], [])

class LedgerTests(AssetsCase):
    def test_verify_restore_and_changed_source(self):
        web = self.web(POLYHAVEN)
        assets.fetch_polyhaven(self.root, None, "brick")
        self.assertTrue(assets.verify(self.root, None)["ok"])
        first = self.root / self.ledger()["assets"][0]["files"][0]["path"]
        first.unlink()
        report = assets.verify(self.root, None)
        self.assertFalse(report["ok"])
        self.assertEqual(len(report["missing"]), 1)
        report = assets.verify(self.root, None, restore=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(first.read_bytes(), DIFFUSE)
        first.unlink()
        web.routes[PH + "brick_diffuse_1k.jpg"] = b"changed upstream"
        report = assets.verify(self.root, None, restore=True)
        self.assertFalse(report["ok"])
        self.assertFalse(first.exists())
        first.write_bytes(b"edited")
        self.assertEqual(len(assets.verify(self.root, None)["mismatched"]), 1)

    def test_another_variant_adds_files_instead_of_dropping_them(self):
        self.web(POLYHAVEN)
        assets.fetch_polyhaven(self.root, None, "brick", maps=["Diffuse"])
        assets.fetch_polyhaven(self.root, None, "brick", maps=["nor_gl"])
        entries = self.ledger()["assets"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(sorted(Path(f["path"]).name for f in entries[0]["files"]),
                         ["brick_diffuse_1k.jpg", "brick_nor_gl_1k.jpg"])

    def test_restore_also_recreates_the_extracted_folder(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Models/a.glb", "glb")
        url = "https://kenney.nl/kit.zip"
        self.web({url: buf.getvalue()})
        assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/kit", None, "K",
                         source="kenney", extract=True)
        folder = self.root / "assets/third_party/kenney/kit"
        import shutil
        shutil.rmtree(folder / "extracted")
        self.assertFalse(assets.verify(self.root, None)["ok"])
        (folder / "kit.zip").unlink()
        report = assets.verify(self.root, None, restore=True)
        self.assertTrue(report["ok"], report)
        self.assertTrue((folder / "extracted/Models/a.glb").is_file())

    def test_a_bad_refresh_keeps_the_recorded_archive(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.glb", "glb")
        url = "https://kenney.nl/kit.zip"
        web = self.web({url: buf.getvalue()})
        args = (self.root, None, url, "https://kenney.nl/assets/kit", None, "K")
        assets.fetch_url(*args, source="kenney", extract=True)
        web.routes[url] = b"not a zip"
        with self.assertRaisesRegex(StudioError, "zip"):
            assets.fetch_url(*args, source="kenney", extract=True)
        self.assertTrue(assets.verify(self.root, None)["ok"])

    def test_restore_replays_every_archive_unpacked_into_the_folder(self):
        def make(name):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr(name, "x")
            return buf.getvalue()
        a, b = "https://kenney.nl/a.zip", "https://kenney.nl/b.zip"
        self.web({a: make("from_a.glb"), b: make("from_b.glb")})
        for url in (a, b):
            assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/kit", None, "K",
                             source="kenney", asset="kit", extract=True)
        import shutil
        folder = self.root / "assets/third_party/kenney/kit/extracted"
        shutil.rmtree(folder)
        self.assertTrue(assets.verify(self.root, None, restore=True)["ok"])
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["from_a.glb", "from_b.glb"])

    def test_one_id_never_carries_two_rights_records(self):
        for name, licence, attribution in (("house", "CC-BY-4.0", "House by A, CC BY 4.0"), ("car", "CC0", None)):
            path = self.root / "assets/third_party/polypizza" / name / "model.glb"
            path.parent.mkdir(parents=True)
            path.write_bytes(name.encode())
        assets.add_file(self.root, None, "assets/third_party/polypizza/house/model.glb",
                        "https://poly.pizza/m/house", "CC-BY-4.0", "A", attribution="House by A, CC BY 4.0",
                        source="polypizza")
        with self.assertRaisesRegex(StudioError, "distinct --id"):
            assets.add_file(self.root, None, "assets/third_party/polypizza/car/model.glb",
                            "https://poly.pizza/m/car", "CC0", "B", source="polypizza")
        self.assertEqual(assets.credits(self.root, None, "CREDITS.md")["attribution_required"], 1)

    def test_credits_never_write_into_the_kit(self):
        with patch.object(assets, "outside_package", side_effect=StudioError("inside kit")):
            with self.assertRaisesRegex(StudioError, "inside kit"):
                assets.credits(self.root, None, "CREDITS.md")

    def test_a_rights_conflict_is_refused_before_any_file_is_replaced(self):
        url = "https://opengameart.org/sites/default/files/cart.zip"
        fake = self.web({url: b"cart"})
        assets.fetch_url(self.root, None, url, "https://opengameart.org/content/cart", "CC0", "A",
                         source="opengameart")
        fake.routes[url] = b"other cart"
        before = len(fake.requests)
        with self.assertRaisesRegex(StudioError, "distinct --id"):
            assets.fetch_url(self.root, None, url, "https://opengameart.org/content/other", "CC0", "B",
                             source="opengameart")
        self.assertEqual(len(fake.requests), before)
        self.assertTrue(assets.verify(self.root, None)["ok"])

    def test_each_file_keeps_its_own_referer_and_refetch_setting(self):
        a, b = "https://cgbookcase-volume.b-cdn.net/t/A_1K.zip", "https://cgbookcase-volume.b-cdn.net/t/B_1K.zip"
        fake = self.web({a: b"a", b: b"b"})
        page = "https://www.cgbookcase.com/textures/set"
        assets.fetch_url(self.root, None, a, page, None, "", source="cgbookcase", asset="set",
                         referer="https://www.cgbookcase.com/")
        assets.fetch_url(self.root, None, b, page, None, "", source="cgbookcase", asset="set", refetchable=False)
        (self.root / "assets/third_party/cgbookcase/set/A_1K.zip").unlink()
        report = assets.verify(self.root, None, restore=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(fake.requests[-1].get_header("Referer"), "https://www.cgbookcase.com/")

    def test_restore_replays_archives_in_fetch_order(self):
        def make(body):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("model.glb", body)
            return buf.getvalue()
        a, b = "https://kenney.nl/a.zip", "https://kenney.nl/b.zip"
        self.web({a: make("old"), b: make("new")})
        for url in (a, b):
            assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/kit", None, "K",
                             source="kenney", asset="kit", extract=True)
        model = self.root / "assets/third_party/kenney/kit/extracted/model.glb"
        self.assertEqual(model.read_text(), "new")
        import shutil
        shutil.rmtree(model.parent)
        assets.verify(self.root, None, restore=True)
        self.assertEqual(model.read_text(), "new")

    def test_extraction_never_writes_into_the_kit(self):
        url = "https://kenney.nl/kit.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.glb", "x")
        self.web({url: buf.getvalue()})
        real = assets.outside_package
        def guard(path, subject="Output"):
            if subject == "Extraction":
                raise StudioError("inside kit")
            return real(path, subject)
        with patch.object(assets, "outside_package", side_effect=guard):
            with self.assertRaisesRegex(StudioError, "inside kit"):
                assets.fetch_url(self.root, None, url, "https://kenney.nl/assets/kit", None, "K",
                                 source="kenney", extract=True)
        self.assertFalse((self.root / "assets/third_party/kenney/kit/extracted").exists())

    def test_manual_add_is_hashed_not_refetchable_and_must_sit_in_the_library(self):
        outside = self.root / "downloads/well.blend"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"blend")
        with self.assertRaisesRegex(StudioError, "under assets/third_party"):
            assets.add_file(self.root, None, "downloads/well.blend", "https://www.blendswap.com/blend/9",
                            "CC0", "A", source="blendswap")
        inside = self.root / "assets/third_party/blendswap/well.blend"
        inside.parent.mkdir(parents=True)
        inside.write_bytes(b"blend")
        result = assets.add_file(self.root, None, "assets/third_party/blendswap/well.blend",
                                 "https://www.blendswap.com/blend/9", "CC-BY-3.0", "A",
                                 attribution="Well by A, CC BY 3.0", source="blendswap")
        entry = self.ledger()["assets"][0]
        self.assertFalse(entry["refetchable"])
        self.assertEqual(result["files"][0]["sha256"], hashlib.sha256(b"blend").hexdigest())
        inside.unlink()
        self.assertEqual(assets.verify(self.root, None, restore=True)["unrestorable"],
                         ["assets/third_party/blendswap/well.blend"])

    def test_refetch_replaces_one_entry_and_credits_split_by_licence(self):
        url = "https://opengameart.org/sites/default/files/cart.zip"
        self.web({url: b"cart", PH + "brick_diffuse_1k.jpg": DIFFUSE, **POLYHAVEN})
        args = (self.root, None, url, "https://opengameart.org/content/cart", "CC-BY-4.0", "B")
        assets.fetch_url(*args, attribution="Cart by B, CC BY 4.0", source="opengameart", asset="cart")
        assets.fetch_url(*args, attribution="Cart by B (CC BY 4.0)", source="opengameart", asset="cart")
        assets.fetch_polyhaven(self.root, None, "brick")
        self.assertEqual([a["asset_id"] for a in self.ledger()["assets"]], ["opengameart/cart", "polyhaven/brick"])
        result = assets.credits(self.root, None, "CREDITS.md")
        self.assertEqual((result["attribution_required"], result["cc0"]), (1, 1))
        text = (self.root / "CREDITS.md").read_text(encoding="utf-8")
        self.assertIn("Cart by B (CC BY 4.0)", text)
        self.assertIn("Brick by A, B, CC0-1.0", text)

    def test_ledger_entry_is_a_valid_texture_base(self):
        from studio_tools.records import validate_provenance
        self.web(POLYHAVEN)
        result = assets.fetch_polyhaven(self.root, None, "brick")
        validate_provenance({"texture_bases": [result["provenance"]]}, self.root)


class CommandTests(AssetsCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, json.loads(out.getvalue() or err.getvalue())

    def test_sources_needs_no_project_and_writes_nothing(self):
        code, result = self.run_cli("assets", "sources", "--kind", "textures")
        self.assertEqual(code, 0)
        self.assertIn("polyhaven", {s["id"] for s in result["sources"]})

    def test_writing_operations_need_a_project(self):
        code, result = self.run_cli("assets", "fetch", "--source", "polyhaven", "--id", "brick")
        self.assertEqual(code, 1)
        self.assertIn("needs --project", result["error"])

    def test_search_maps_api_results(self):
        self.web({"https://api.polyhaven.com/search?q=plaster%20wall&t=textures":
                  {"results": [{"slug": "plastered_wall_05"}, {"slug": "plastered_wall_02"}]}})
        code, result = self.run_cli("assets", "search", "--source", "polyhaven", "--query", "plaster wall",
                                    "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual(result["results"], [{"id": "plastered_wall_05",
                                              "page_url": "https://polyhaven.com/a/plastered_wall_05"}])

    def test_fetch_through_the_command(self):
        self.web(POLYHAVEN)
        code, result = self.run_cli("assets", "fetch", "--project", str(self.root), "--source", "polyhaven",
                                    "--id", "brick", "--maps", "Diffuse")
        self.assertEqual(code, 0, result)
        self.assertEqual(len(result["files"]), 1)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", result["files"][0]["sha256"]))


if __name__ == "__main__":
    unittest.main()
