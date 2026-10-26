"""Character run record: gates before stages, owner approvals, caps and outputs."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from studio_tools.common import StudioError, file_record
from studio_tools.records import validate

ROOT = Path(__file__).resolve().parents[1]


class CharacterRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.record = json.loads((ROOT / "templates/character-run.json").read_text(encoding="utf-8"))
        self.record["character_id"] = "quarry"
        self.record["builder"] = "builder-session"
        self.record["brief"]["role"] = "stone giant"

    def file(self, name, text="x"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return file_record(self.root, path)

    def approve(self, record, gate, by="owner"):
        record["gates"][gate] = {"status": "approved", "choice": "B", "notes": None,
                                 "approved_by": by, "approved_at": "2026-10-26T08:00:00Z",
                                 "file": self.file("gates/" + gate + ".txt", gate)}

    def stage(self, record, stage_id):
        return next(s for s in record["stages"] if s["id"] == stage_id)

    def finish(self, record, stage_id):
        stage = self.stage(record, stage_id)
        stage["status"] = "done"
        stage["outputs"] = [self.file("out/" + stage_id + ".bin", stage_id)]
        stage["check"] = {"verdict": "pass", "evidence": self.file("out/" + stage_id + ".report", "ok")}

    def check(self, record):
        return validate(record, self.root)

    def test_template_is_valid(self):
        self.assertEqual(self.check(self.record)["gates"], {"concept": "open", "voice": "open"})

    def test_stage_cannot_start_before_its_gate(self):
        self.stage(self.record, "model")["status"] = "running"
        with self.assertRaisesRegex(StudioError, "before the concept gate"):
            self.check(self.record)

    def test_builder_cannot_approve_its_own_gate(self):
        self.approve(self.record, "concept", by="builder-session")
        with self.assertRaisesRegex(StudioError, "approved by the builder"):
            self.check(self.record)

    def test_stage_cannot_start_before_its_inputs(self):
        self.approve(self.record, "concept")
        self.stage(self.record, "model_qa")["status"] = "running"
        with self.assertRaisesRegex(StudioError, "before model was done"):
            self.check(self.record)

    def test_done_needs_hashed_outputs_and_a_passing_check(self):
        self.approve(self.record, "concept")
        record = copy.deepcopy(self.record)
        self.stage(record, "model")["status"] = "done"
        with self.assertRaisesRegex(StudioError, "lists no outputs"):
            self.check(record)
        self.finish(self.record, "model")
        self.stage(self.record, "model")["check"]["verdict"] = "fail"
        with self.assertRaisesRegex(StudioError, "without a passing check"):
            self.check(self.record)
        self.finish(self.record, "model")
        (self.root / "out/model.bin").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(StudioError, "Hash mismatch"):
            self.check(self.record)

    def test_spend_needs_an_owner_cap_and_stays_under_it(self):
        self.approve(self.record, "concept")
        model = self.stage(self.record, "model")
        model["status"] = "running"
        model["paid"] = [{"route": "meshy", "spent": 40}]
        with self.assertRaisesRegex(StudioError, "without an approved cap"):
            self.check(self.record)
        self.record["budgets"] = [{"route": "meshy", "unit": "credits", "cap": 300,
                                   "approved_by": "owner", "approved_at": "2026-10-26T08:00:00Z"}]
        self.assertEqual(self.check(self.record)["spent"], {"meshy": 40})
        model["paid"].append({"route": "meshy", "spent": 261})
        with self.assertRaisesRegex(StudioError, "passed its approved cap"):
            self.check(self.record)
        self.record["budgets"][0]["approved_by"] = "builder-session"
        with self.assertRaisesRegex(StudioError, "approved by the owner"):
            self.check(self.record)

    def test_repair_cap_forces_a_stop(self):
        self.approve(self.record, "concept")
        self.finish(self.record, "model")
        qa = self.stage(self.record, "model_qa")
        qa["status"] = "running"
        qa["repair_rounds"] = 3
        self.check(self.record)
        qa["check"] = {"verdict": "fail"}
        with self.assertRaisesRegex(StudioError, "repair round cap"):
            self.check(self.record)
        qa["check"] = {"verdict": "not_run"}
        qa["repair_rounds"] = 4
        with self.assertRaisesRegex(StudioError, "repair round cap"):
            self.check(self.record)
        qa["status"] = "stopped"
        self.check(self.record)

    def test_review_cannot_finish_on_a_provisional_pick(self):
        self.approve(self.record, "concept")
        self.record["gates"]["voice"] = {"status": "provisional", "choice": "cool-302",
                                         "file": self.file("gates/voice.txt", "voice")}
        for stage_id in ("model", "model_qa", "library", "animation", "voice_lines",
                         "effects", "sounds", "integration"):
            self.finish(self.record, stage_id)
        self.check(self.record)
        self.finish(self.record, "review")
        with self.assertRaisesRegex(StudioError, "approves the voice gate"):
            self.check(self.record)
        self.stage(self.record, "review")["needs"] = ["integration"]
        with self.assertRaisesRegex(StudioError, "approves the voice gate"):
            self.check(self.record)
        self.approve(self.record, "voice")
        self.check(self.record)

    def test_reopened_stages_wait_for_reopened_inputs(self):
        self.approve(self.record, "concept")
        for stage_id in ("model", "model_qa", "library"):
            self.finish(self.record, stage_id)
        for stage_id in ("model", "model_qa", "library"):
            self.stage(self.record, stage_id)["status"] = "reopened"
        self.check(self.record)
        self.stage(self.record, "model_qa")["status"] = "running"
        with self.assertRaisesRegex(StudioError, "before model was done"):
            self.check(self.record)

    def test_needs_must_name_earlier_stages(self):
        self.stage(self.record, "model")["needs"] = ["gate:concept", "review"]
        with self.assertRaisesRegex(StudioError, "not an earlier stage"):
            self.check(self.record)

    def test_review_rounds_reopen_known_stages(self):
        self.record["review_rounds"] = [{"at": "2026-10-27T08:00:00Z", "reopened": ["hair"]}]
        with self.assertRaisesRegex(StudioError, "known stages"):
            self.check(self.record)


if __name__ == "__main__":
    unittest.main()
