"""Independent synthetic tests for high-level B2 approximation policy."""

from copy import deepcopy
import unittest

import b2_sets
from b2_review import make_handoff
from b2_simplification import build_proposal, validate_review
import test_b2_web as web_fixture


def policy(value="unspecified", notes=""):
    return {"policy": value, "notes": notes, "detail_policy": "omit_chamfers_and_fillets"}


def legacy_recipe():
    return {"operations": [
        {"operation": "sketch", "parameters": {}},
        {"operation": "extrude", "parameters": {"length_mm": 12}},
        {"operation": "draft", "parameters": {"angle_deg": 3}},
        {"operation": "chamfer", "parameters": {"distance_mm": 0.5}},
        {"operation": "fillet", "parameters": {"radius_mm": 0.3}}],
        "parameter_status": "define_in_B3"}


class ApproximationPolicyTests(unittest.TestCase):
    def setUp(self):
        fixture = web_fixture.WebReviewTests(methodName="test_pending_handoff_blocked")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.parts = fixture.session.parts
        self.draft = deepcopy(fixture.session.save(fixture.accepted())["draft"])

    def record(self, approximation=None):
        record = build_proposal(self.parts, self.draft)
        faces = [r["face"] for r in record["proposals"] if r["face"][0] == "1/1"][:2]
        for row in record["proposals"]:
            row["decision"] = "simplify" if row["face"] in faces else "keep"
        record["sets"] = [{"id": "policy-set", "name": "合成近似方針", "faces": faces,
                           "decision": "simplify", "approximation": approximation or policy()}]
        record["confirmed"] = True
        return record

    def exported_group(self, record):
        handoff = make_handoff(self.draft, self.parts, record)
        return next(g for g in handoff["simplification_guidance"]["face_review"]["sets"]
                    if g["id"] == "policy-set")

    def test_optional_unspecified_policy_needs_no_construction_recipe(self):
        record = self.record()
        validate_review(record, self.draft, self.parts, require_complete=True)
        self.assertEqual(self.exported_group(record)["approximation"], policy())

    def test_volume_and_envelope_are_supported_high_level_goals(self):
        for value in ("preserve_volume", "preserve_envelope"):
            with self.subTest(value=value):
                record = self.record(policy(value, "開口は別に保持する"))
                group = self.exported_group(record)
                self.assertEqual(group["approximation"], policy(value, "開口は別に保持する"))
                self.assertEqual(group["reference_policy"], "surfaces_and_policy")

    def test_legacy_recipe_is_read_without_mutating_saved_judgments(self):
        record = self.record(legacy_recipe())
        before = deepcopy(record)
        validate_review(record, self.draft, self.parts, require_complete=True)
        exported = self.exported_group(record)
        self.assertEqual(record, before)
        self.assertEqual(exported["approximation"], policy())

    def test_legacy_operations_and_numeric_details_never_reach_b3_recipe(self):
        group = self.exported_group(self.record(legacy_recipe()))
        self.assertNotIn("operations", group["approximation"])
        self.assertNotIn("parameter_status", group["approximation"])
        self.assertNotIn("parameters", group["approximation"])
        self.assertEqual(group["approximation"]["detail_policy"], "omit_chamfers_and_fillets")
        self.assertEqual(group["reference_policy"], "surfaces_and_policy")

    def test_normalization_does_not_guess_volume_goal_from_old_recipe(self):
        self.assertEqual(b2_sets.normalize_plan(legacy_recipe())["policy"], "unspecified")
        self.assertEqual(b2_sets.normalize_plan(policy("preserve_volume")), policy("preserve_volume"))

    def test_simplified_set_retains_surface_refs_but_no_fine_edge_refs(self):
        group = self.exported_group(self.record(policy("preserve_volume")))
        self.assertEqual(len(group["surface_references"]), 2)
        self.assertEqual(group["edge_references"], [])
        self.assertTrue(all(r["surface_type"] == "planar" for r in group["surface_references"]))

    def test_unknown_policy_or_construction_extras_are_rejected(self):
        for approximation in (
            policy("chamfer"), policy(True),
            {**policy(), "operations": legacy_recipe()["operations"]},
            {**policy(), "tolerance_mm": .01},
            {**policy(), "notes": []},
            {**policy(), "detail_policy": "keep_fillets"},
        ):
            with self.subTest(approximation=approximation), self.assertRaises(ValueError):
                validate_review(self.record(approximation), self.draft, self.parts)

    def test_contact_protection_still_applies_to_policy_only_sets(self):
        record = self.record(policy("preserve_volume"))
        record["sets"][0]["faces"] = [self.draft["reviews"][0]["faces"][0]]
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts)

    def test_keep_and_omit_cannot_carry_approximation_policy(self):
        for decision in ("keep", "omit"):
            with self.subTest(decision=decision):
                record = self.record()
                group = record["sets"][0]
                group["decision"] = decision
                for row in record["proposals"]:
                    if row["face"] in group["faces"]:
                        row["decision"] = decision
                with self.assertRaises(ValueError):
                    validate_review(record, self.draft, self.parts)

    def test_policy_session_save_reopen_and_handoff(self):
        session = self.fixture.session
        state = session.state()
        state = session.start_simplification({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "threshold_mm": 5})
        group = self.record(policy("preserve_volume", "体積維持を目標"))["sets"][0]
        group["id"] = None
        state = session.save_simplification_set({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "set": group, "notes": ""})
        saved = next(g for g in state["simplification"]["sets"] if g["name"] == group["name"])
        self.assertEqual(saved["approximation"], group["approximation"])
        reopened = type(session)(session.bundle, session.candidate_path, session.review_path).state()
        self.assertEqual(reopened["simplification"], state["simplification"])
        self.assertFalse(reopened["simplification"]["confirmed"])
        for row in list(state["simplification"]["proposals"]):
            if row["decision"] == "pending":
                state = session.save_simplification({"revision": state["revision"],
                    "simplification_revision": state["simplification_revision"],
                    "item": {"id": row["id"], "decision": "keep"}, "notes": ""})
        state = session.finish_simplification({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "notes": ""})
        handoff = make_handoff(state["draft"], self.parts, state["simplification"])
        exported = next(g for g in handoff["simplification_guidance"]["face_review"]["sets"]
                        if g["id"] == saved["id"])
        self.assertEqual(exported["approximation"], policy("preserve_volume", "体積維持を目標"))

    def test_new_api_save_normalizes_legacy_recipe_to_policy_only(self):
        session = self.fixture.session
        state = session.state()
        state = session.start_simplification({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "threshold_mm": 5})
        group = self.record(legacy_recipe())["sets"][0]
        group["id"] = None
        original = deepcopy(group)
        state = session.save_simplification_set({"revision": state["revision"],
            "simplification_revision": state["simplification_revision"], "set": group, "notes": ""})
        self.assertEqual(group, original)
        saved = state["simplification"]["sets"][0]
        self.assertEqual(saved["approximation"], policy())
        self.assertNotIn("operations", saved["approximation"])
        reopened = type(session)(session.bundle, session.candidate_path, session.review_path).state()
        self.assertEqual(reopened["simplification"]["sets"][0]["approximation"], policy())


if __name__ == "__main__":
    unittest.main()
