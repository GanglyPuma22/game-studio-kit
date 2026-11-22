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
        self.assertEqual(self.check(self.record)["gates"], {
            "concept": "open", "voice": "open", "target": "open", "body": "open", "look": "open"})

    def test_stage_cannot_start_before_its_gate(self):
        self.stage(self.record, "model")["status"] = "running"
        with self.assertRaisesRegex(StudioError, "before the concept gate"):
            self.check(self.record)
        self.approve(self.record, "concept")
        with self.assertRaisesRegex(StudioError, "before the target gate"):
            self.check(self.record)
        self.approve(self.record, "target")
        self.check(self.record)

    def without_design_gates(self):
        """The record shape from before the design gates existed."""
        record = copy.deepcopy(self.record)
        for name in ("target", "body", "look"):
            del record["gates"][name]
        del record["gate_round_cap"]
        record["stages"] = [s for s in record["stages"]
                            if s["id"] not in ("grey_build", "look_bench", "production")]
        for stage in record["stages"]:
            stage["needs"] = [n for n in stage["needs"]
                              if n not in ("gate:target", "gate:body", "gate:look", "production")]
        return record

    def test_design_gates_are_optional(self):
        record = self.without_design_gates()
        self.assertEqual(self.check(record)["gates"], {"concept": "open", "voice": "open"})
        record["gates"]["palette"] = copy.deepcopy(record["gates"]["concept"])
        with self.assertRaisesRegex(StudioError, "may hold target, body and look"):
            self.check(record)
        del record["gates"]["palette"]
        del record["gates"]["voice"]
        with self.assertRaisesRegex(StudioError, "must hold concept and voice"):
            self.check(record)

    def test_a_stage_cannot_need_a_gate_the_record_lacks(self):
        record = self.without_design_gates()
        self.stage(record, "model")["needs"].append("gate:target")
        with self.assertRaisesRegex(StudioError, "unknown gate gate:target"):
            self.check(record)

    def reach_look_bench(self):
        for gate in ("concept", "target", "body"):
            self.approve(self.record, gate)
        for stage_id in ("model", "model_qa", "library", "animation", "grey_build", "look_bench"):
            self.finish(self.record, stage_id)

    def test_production_waits_for_a_picked_look(self):
        self.reach_look_bench()
        self.check(self.record)
        production = self.stage(self.record, "production")
        production["status"] = "running"
        with self.assertRaisesRegex(StudioError, "before the look gate"):
            self.check(self.record)
        # Editing the stage's inputs does not buy final art on an unpicked look.
        production["needs"] = ["look_bench"]
        with self.assertRaisesRegex(StudioError, "production started before the look gate"):
            self.check(self.record)
        self.record["gates"]["look"]["status"] = "stopped"
        with self.assertRaisesRegex(StudioError, "production started before the look gate"):
            self.check(self.record)
        self.record["gates"]["look"] = {"status": "provisional", "choice": "B",
                                        "file": self.file("gates/look.txt", "look")}
        self.check(self.record)
        self.approve(self.record, "look")
        self.check(self.record)

    def test_production_needs_a_look_gate_in_the_record(self):
        record = self.without_design_gates()
        record["stages"].insert(1, {"id": "production", "status": "running", "needs": ["model"]})
        self.approve(record, "concept")
        self.finish(record, "model")
        with self.assertRaisesRegex(StudioError, "production started before the look gate"):
            self.check(record)

    def test_gate_round_cap_forces_a_stop(self):
        self.reach_look_bench()
        look = self.record["gates"]["look"]
        look["rounds"] = 3
        self.check(self.record)
        look["rounds"] = 4
        with self.assertRaisesRegex(StudioError, "gates.look has had 4 rounds without approval"):
            self.check(self.record)
        look["status"] = "stopped"
        self.assertEqual(self.check(self.record)["gates"]["look"], "stopped")
        self.record["gate_round_cap"] = 5
        look["status"] = "open"
        self.check(self.record)
        self.record["gate_round_cap"] = 0
        with self.assertRaisesRegex(StudioError, "gate_round_cap must be a positive integer"):
            self.check(self.record)
        self.record["gate_round_cap"] = 3
        look["rounds"] = -1
        with self.assertRaisesRegex(StudioError, "rounds must be a nonnegative integer"):
            self.check(self.record)
        # An approved gate keeps its history; the count no longer stops anything.
        self.approve(self.record, "look")
        self.record["gates"]["look"]["rounds"] = 4
        self.check(self.record)

    def test_a_stopped_gate_holds_its_stages(self):
        self.approve(self.record, "concept")
        self.record["gates"]["target"]["status"] = "stopped"
        self.stage(self.record, "model")["status"] = "running"
        with self.assertRaisesRegex(StudioError, "before the target gate"):
            self.check(self.record)

    def test_builder_cannot_approve_its_own_gate(self):
        self.approve(self.record, "concept", by="builder-session")
        with self.assertRaisesRegex(StudioError, "approved by the builder"):
            self.check(self.record)

    def test_stage_cannot_start_before_its_inputs(self):
        self.approve(self.record, "concept")
        self.approve(self.record, "target")
        self.stage(self.record, "model_qa")["status"] = "running"
        with self.assertRaisesRegex(StudioError, "before model was done"):
            self.check(self.record)

    def test_done_needs_hashed_outputs_and_a_passing_check(self):
        self.approve(self.record, "concept")
        self.approve(self.record, "target")
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
        self.approve(self.record, "target")
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
        self.approve(self.record, "target")
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
        for gate in ("concept", "target", "body"):
            self.approve(self.record, gate)
        self.record["gates"]["voice"] = {"status": "provisional", "choice": "cool-302",
                                         "file": self.file("gates/voice.txt", "voice")}
        self.record["gates"]["look"] = {"status": "provisional", "choice": "B",
                                        "file": self.file("gates/look.txt", "look")}
        for stage_id in ("model", "model_qa", "library", "animation", "grey_build", "look_bench",
                         "production", "voice_lines", "effects", "sounds", "integration"):
            self.finish(self.record, stage_id)
        self.check(self.record)
        self.finish(self.record, "review")
        with self.assertRaisesRegex(StudioError, "approves the voice gate"):
            self.check(self.record)
        self.stage(self.record, "review")["needs"] = ["integration"]
        with self.assertRaisesRegex(StudioError, "approves the voice gate"):
            self.check(self.record)
        self.approve(self.record, "voice")
        with self.assertRaisesRegex(StudioError, "approves the look gate"):
            self.check(self.record)
        self.approve(self.record, "look")
        self.check(self.record)

    def test_reopened_stages_wait_for_reopened_inputs(self):
        self.approve(self.record, "concept")
        self.approve(self.record, "target")
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
