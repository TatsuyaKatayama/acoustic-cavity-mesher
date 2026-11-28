import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from advance_case import Case, digest


class CaseWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = self.root / "test.step"
        source.write_text("test STEP", encoding="utf-8")
        (self.root / "case.json").write_text(json.dumps({"input": str(source)}), encoding="utf-8")
        self.case = Case(self.root)

    def ready(self):
        return {task["key"]: task for task in self.case.next()}

    def record(self, key, outcome="ok", *, placements=(), revision=None):
        task = self.ready()[key]
        artifact = self.root / (key.replace("/", "-") + ".json")
        part = key.removeprefix("B2/approve/").rsplit("/", 1)[0]
        data = {"parts": {part: {"proposal_revision": revision,
                                  "approval_source": "human_part_confirmation"}}}
        artifact.write_text(json.dumps(data), encoding="utf-8")
        self.case.record(digest(task), outcome, [artifact], list(placements), revision)

    def approve(self, part):
        revision = f"proposal-{part}"
        self.record(f"B2/propose/{part}/1", revision=revision)
        self.record(f"B2/check/{part}/1", "presentable", revision=revision)
        self.record(f"B2/approve/{part}/1", "approved", revision=revision)

    def test_approval_gate_and_reopen(self):
        self.record("B1", placements=["1/1", "1/2"])
        self.approve("1/1")
        self.case = Case(self.root)
        self.assertEqual(list(self.ready()), ["B2/propose/1/2/1"])
        self.approve("1/2")
        self.assertEqual(list(self.ready()), ["B2/final"])
        self.record("B2/final", "approved")
        self.record("B3/1/1/1")
        self.assertIn("B4/1/1/1", self.ready())
        self.case.reopen("B2/propose/1/1/1")
        self.assertEqual(list(self.ready()), ["B2/propose/1/1/1"])
        self.approve("1/1")
        self.assertEqual(list(self.ready()), ["B2/final"])

    def test_rejects_other_proposal_revision(self):
        self.record("B1", placements=["1/1"])
        self.record("B2/propose/1/1/1", revision="displayed")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.record("B2/check/1/1/1", "presentable", revision="older")

    def test_repair_loop_and_closeout(self):
        self.record("B1", placements=["1/1"])
        self.approve("1/1")
        self.record("B2/final", "approved")
        self.record("B3/1/1/1")
        self.record("B4/1/1/1")
        self.record("B5.1/build/1")
        self.record("B5.1/check/1")
        self.record("B5.2/build/1")
        self.record("B5.2/check/1", "repair")
        self.record("B5.3/repair/1/1")
        self.record("B5.3/check/1/1", "reassemble")
        self.record("B5.1/build/2")
        self.record("B5.1/check/2")
        self.record("B5.2/build/2")
        self.record("B5.2/check/2")
        self.record("B5/deliver")
        self.record("B6/propose")
        self.record("B6/adopt", "approved")
        self.record("B6/apply")
        self.record("B6/report")
        self.assertEqual(self.ready(), {})
