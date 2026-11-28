"""Independent synthetic checks for singleton classification and face transfers."""
from copy import deepcopy
import unittest

import b2_sets
from b2_simplification import build_proposal
import test_b2_web as fixture_module


POLICY = {"policy": "preserve_volume", "notes": "", "detail_policy": "omit_chamfers_and_fillets"}


def group(identifier, faces, decision):
    return {"id": identifier, "name": identifier or "synthetic selection", "faces": deepcopy(faces),
            "decision": decision, "approximation": deepcopy(POLICY) if decision == "simplify" else None}


class SingletonTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.WebReviewTests(methodName="test_pending_handoff_blocked")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.session = self.fixture.session
        self.state = self.session.save(self.fixture.accepted())
        self.record = build_proposal(self.session.parts, self.state["draft"])
        self.faces = [row["face"] for row in self.record["proposals"] if row["face"][0] == "1/3"]
        self.assertGreaterEqual(len(self.faces), 4)

    def canonical(self, record):
        return b2_sets.canonicalize_sets(record)

    def start(self):
        state = self.session.state()
        return self.session.start_simplification({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "threshold_mm": 5})

    def save(self, decision, faces, identifier=None):
        state = self.session.state()
        return self.session.save_simplification_set({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "notes": "synthetic",
            "set": group(identifier, faces, decision)})

    def test_migration_preserves_decisions_and_multiple_approximation_groups(self):
        record = deepcopy(self.record)
        record["sets"] = [group("oldkeep1", [self.faces[0]], "keep"),
            group("oldkeep2", [self.faces[1]], "keep"),
            group("approx1", [self.faces[2]], "simplify"),
            group("approx2", [self.faces[3]], "simplify")]
        assigned = {tuple(ref): item["decision"] for item in record["sets"] for ref in item["faces"]}
        for row in record["proposals"]:
            row["decision"] = assigned.get(tuple(row["face"]), "omit")
        before = deepcopy(record)
        result = self.canonical(record)
        self.assertEqual(record, before)
        self.assertEqual(result["proposals"], before["proposals"])
        self.assertEqual([g for g in result["sets"] if g["decision"] == "simplify"], before["sets"][2:])
        owners = {tuple(ref): g["decision"] for g in result["sets"] for ref in g["faces"]}
        for row in before["proposals"]:
            self.assertEqual(owners[tuple(row["face"])], row["decision"])
        keys = [(g["faces"][0][0], g["decision"]) for g in result["sets"] if g["decision"] != "simplify"]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(self.canonical(result), result)

    def test_validator_rejects_duplicate_singletons(self):
        record = self.canonical(self.record)
        record["sets"] += [group("keep-a", [self.faces[0]], "keep"), group("keep-b", [self.faces[1]], "keep")]
        for row in record["proposals"]:
            if row["face"] in self.faces[:2]:
                row["decision"] = "keep"
        with self.assertRaises(ValueError):
            b2_sets.validate_sets(record, self.state["draft"], self.session.parts)

    def test_transfer_preserves_other_members_and_removes_empty_source(self):
        self.start()
        self.save("simplify", self.faces[:2])
        self.save("omit", self.faces[:1])
        record = self.session.state()["simplification"]
        approximate = [g for g in record["sets"] if g["decision"] == "simplify"]
        self.assertEqual(approximate[0]["faces"], self.faces[1:2])
        self.save("omit", self.faces[:2])
        record = self.session.state()["simplification"]
        self.assertFalse(any(g["decision"] == "simplify" for g in record["sets"]))
        omitted = [g for g in record["sets"] if g["decision"] == "omit" and g["faces"][0][0] == "1/3"]
        self.assertEqual(len(omitted), 1)
        self.assertEqual(set(map(tuple, omitted[0]["faces"])), set(map(tuple, self.faces[:2])))

    def test_invalid_transfer_and_stale_revision_leave_file_unchanged(self):
        self.start()
        stale = self.session.state()
        self.save("keep", self.faces[:1])
        before = self.session.simplification_path.read_bytes()
        with self.assertRaises(ValueError):
            self.save("omit", [self.faces[0], self.record["protected_faces"][0]])
        self.assertEqual(self.session.simplification_path.read_bytes(), before)
        with self.assertRaises(ValueError):
            self.session.save_simplification_set({"revision": stale["revision"],
                "simplification_revision": stale["simplification_revision"], "notes": "",
                "set": group(None, self.faces[:1], "omit")})
        self.assertEqual(self.session.simplification_path.read_bytes(), before)

    def test_read_does_not_persist_migration(self):
        self.start()
        self.record["sets"] = [group("legacy-a", self.faces[:1], "keep"),
                               group("legacy-b", self.faces[1:2], "keep")]
        for row in self.record["proposals"]:
            if row["face"] in self.faces[:2]:
                row["decision"] = "keep"
        self.session.simplification_path.write_text(__import__("json").dumps(self.record), encoding="utf-8")
        before = self.session.simplification_path.read_bytes()
        state = self.session.state()
        self.assertEqual(self.session.simplification_path.read_bytes(), before)
        kept = [g for g in state["simplification"]["sets"] if g["decision"] == "keep" and g["faces"][0][0] == "1/3"]
        self.assertEqual(len(kept), 1)
        self.assertEqual(set(map(tuple, kept[0]["faces"])), set(map(tuple, self.faces[:2])))

    def test_protected_face_cannot_be_omitted_or_approximated(self):
        self.start()
        protected = self.record["protected_faces"][0]
        for decision in ("omit", "simplify"):
            before = self.session.simplification_path.read_bytes()
            with self.assertRaises(ValueError):
                self.save(decision, [protected])
            self.assertEqual(self.session.simplification_path.read_bytes(), before)

    def test_mixed_part_transfer_rejected_without_changes(self):
        self.start()
        other = next(row["face"] for row in self.record["proposals"] if row["face"][0] != "1/3")
        before = self.session.simplification_path.read_bytes()
        with self.assertRaises(ValueError):
            self.save("keep", [self.faces[0], other])
        self.assertEqual(self.session.simplification_path.read_bytes(), before)

    def test_confirmed_review_can_be_reopened_by_set_transfer(self):
        self.start()
        for part in sorted({row["face"][0] for row in self.record["proposals"]}):
            self.save("keep", [row["face"] for row in self.record["proposals"] if row["face"][0] == part])
        state = self.session.state()
        state = self.session.finish_simplification({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "notes": "confirmed synthetic"})
        self.assertTrue(state["simplification"]["confirmed"])
        state = self.save("omit", self.faces[:1])
        self.assertFalse(state["simplification"]["confirmed"])
        decisions = {tuple(row["face"]): row["decision"] for row in state["simplification"]["proposals"]}
        self.assertEqual(decisions.pop(tuple(self.faces[0])), "omit")
        self.assertEqual(set(decisions.values()), {"keep"})
        self.assertTrue(any(self.faces[0] in g["faces"] and g["decision"] == "omit" for g in state["simplification"]["sets"]))
        reopened = fixture_module.ReviewSession(self.fixture.bundle, self.fixture.candidates, self.fixture.review).state()
        self.assertEqual(reopened["simplification"], state["simplification"])

    def test_protected_keep_members_cannot_disappear_on_edit_or_delete(self):
        self.start()
        protected = self.record["protected_faces"][0]
        free = next(row["face"] for row in self.record["proposals"] if row["face"][0] == protected[0])
        state = self.save("keep", [free])
        keep = next(g for g in state["simplification"]["sets"] if g["decision"] == "keep" and protected in g["faces"])
        state = self.save("keep", [free], keep["id"])
        self.assertTrue(any(protected in g["faces"] and g["decision"] == "keep" for g in state["simplification"]["sets"]))
        try:
            self.session.delete_simplification_set({"revision": state["revision"],
                "simplification_revision": state["simplification_revision"], "id": keep["id"]})
        except ValueError:
            pass
        record = self.session.state()["simplification"]
        self.assertTrue(any(protected in g["faces"] and g["decision"] == "keep" for g in record["sets"]))


if __name__ == "__main__":
    unittest.main()
