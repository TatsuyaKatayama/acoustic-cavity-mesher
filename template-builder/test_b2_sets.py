"""Independent synthetic checks for B2 grouped approximation references."""

from copy import deepcopy
import json
import unittest

import cadquery as cq

from OCP.TopAbs import TopAbs_EDGE
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool

import b2_simplification as simplification
from b2_sets import edge_references
from b2_review import make_handoff
from build_template import target_contacts
import test_b2_web as web_fixture


def plan(*operations):
    return {"operations": [{"operation": operation, "parameters": {}} for operation in
                            (operations or ("sketch", "extrude", "draft", "chamfer", "fillet"))],
            "parameter_status": "define_in_B3"}


class SimplificationSetTests(unittest.TestCase):
    def setUp(self):
        fixture = web_fixture.WebReviewTests(methodName="test_pending_handoff_blocked")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.parts = fixture.session.parts
        state = fixture.session.save(fixture.accepted())
        self.draft = deepcopy(state["draft"])

    def record(self):
        record = simplification.build_proposal(self.parts, self.draft)
        for row in record["proposals"]:
            row["decision"] = "keep"
        record["sets"] = []
        record["confirmed"] = True
        return record

    def same_part_faces(self, record, part="1/1"):
        return [row["face"] for row in record["proposals"] if row["face"][0] == part]

    def add_set(self, record, *, identifier="set-a", faces=None, decision="simplify", approximation=None):
        faces = faces or self.same_part_faces(record)[:2]
        item = {"id": identifier, "name": "合成段差", "faces": deepcopy(faces),
                "decision": decision, "approximation": plan() if approximation is None and decision == "simplify" else approximation}
        record["sets"].append(item)
        members = {tuple(face) for face in faces}
        for row in record["proposals"]:
            if tuple(row["face"]) in members:
                row["decision"] = decision
        return item

    def test_multiface_set_and_multiple_sets_complete(self):
        record = self.record()
        self.add_set(record)
        self.add_set(record, identifier="set-b", faces=self.same_part_faces(record, "1/2")[:2], decision="keep")
        simplification.validate_review(record, self.draft, self.parts, require_complete=True)

    def test_simplify_decision_needs_explicit_set(self):
        record = self.record()
        record["proposals"][0]["decision"] = "simplify"
        with self.assertRaises(ValueError):
            simplification.validate_review(record, self.draft, self.parts, require_complete=True)

    def test_accepted_contact_cannot_enter_approximation_or_omission_set(self):
        for decision in ("simplify", "omit"):
            with self.subTest(decision=decision):
                record = self.record()
                self.add_set(record, faces=[self.draft["reviews"][0]["faces"][0]], decision=decision)
                with self.assertRaises(ValueError):
                    simplification.validate_review(record, self.draft, self.parts)

    def test_sets_cannot_span_parts(self):
        record = self.record()
        self.add_set(record, faces=[self.same_part_faces(record, "1/1")[0], self.same_part_faces(record, "1/2")[0]])
        with self.assertRaises(ValueError):
            simplification.validate_review(record, self.draft, self.parts)

    def test_overlapping_set_membership_rejected(self):
        record = self.record()
        item = self.add_set(record)
        self.add_set(record, identifier="set-b", faces=item["faces"], decision="simplify")
        with self.assertRaises(ValueError):
            simplification.validate_review(record, self.draft, self.parts)

    def test_duplicate_set_id_rejected(self):
        record = self.record()
        self.add_set(record)
        self.add_set(record, faces=self.same_part_faces(record, "1/2")[:2])
        with self.assertRaises(ValueError):
            simplification.validate_review(record, self.draft, self.parts)

    def test_empty_members_and_invalid_sets_container_rejected(self):
        for members in ([], None, "1/1"):
            record = self.record()
            item = self.add_set(record)
            item["faces"] = members
            with self.subTest(members=members), self.assertRaises(ValueError):
                simplification.validate_review(record, self.draft, self.parts)
        for value in ({}, "sets"):
            record = self.record()
            record["sets"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                simplification.validate_review(record, self.draft, self.parts)

    def test_duplicate_face_within_set_rejected(self):
        record = self.record()
        face = self.same_part_faces(record)[0]
        self.add_set(record, faces=[face, face])
        with self.assertRaises(ValueError):
            simplification.validate_review(record, self.draft, self.parts)

    def test_set_row_decision_must_match(self):
        record = self.record()
        item = self.add_set(record)
        next(row for row in record["proposals"] if row["face"] == item["faces"][0])["decision"] = "omit"
        with self.assertRaises(ValueError):
            simplification.validate_review(record, self.draft, self.parts)

    def test_unknown_and_invalid_face_references_rejected(self):
        for face in (["1/1", 99999], ["missing", 1], ["1/1", True]):
            with self.subTest(face=face):
                record = self.record()
                self.add_set(record, faces=[face])
                with self.assertRaises(ValueError):
                    simplification.validate_review(record, self.draft, self.parts)

    def test_operation_order_and_unknown_operations_rejected(self):
        for operations in (("extrude", "sketch"), ("sketch",), ("sketch", "loft"),
                           ("sketch", "fillet", "extrude"), ("sketch", "draft")):
            with self.subTest(operations=operations):
                record = self.record()
                self.add_set(record, approximation=plan(*operations))
                with self.assertRaises(ValueError):
                    simplification.validate_review(record, self.draft, self.parts)

    def test_cut_plan_is_supported(self):
        record = self.record()
        self.add_set(record, approximation=plan("sketch", "cut", "chamfer", "fillet"))
        simplification.validate_review(record, self.draft, self.parts, require_complete=True)

    def test_invalid_operation_parameters_are_rejected(self):
        for operation, parameters in (("extrude", {"direction": [0, 0, 0]}),
                                      ("extrude", {"direction": [0, True, 0]}),
                                      ("extrude", {"length_mm": float("nan")}),
                                      ("fillet", {"radius_mm": -1}),
                                      ("chamfer", {"distance_mm": 0}),
                                      ("draft", {"angle_deg": 89}),
                                      ("sketch", {"code": "untrusted"})):
            with self.subTest(operation=operation, parameters=parameters):
                record = self.record()
                recipe = plan()
                next(step for step in recipe["operations"] if step["operation"] == operation)["parameters"] = parameters
                self.add_set(record, approximation=recipe)
                with self.assertRaises(ValueError):
                    simplification.validate_review(record, self.draft, self.parts)

    def test_keep_and_omit_cannot_smuggle_approximation(self):
        for decision in ("keep", "omit"):
            with self.subTest(decision=decision):
                record = self.record()
                self.add_set(record, decision=decision, approximation=plan())
                with self.assertRaises(ValueError):
                    simplification.validate_review(record, self.draft, self.parts)

    def test_legacy_no_sets_keep_omit_preserved(self):
        record = self.record()
        record.pop("sets")
        record["proposals"][0]["decision"] = "omit"
        simplification.validate_review(record, self.draft, self.parts, require_complete=True)
        guidance = simplification.handoff_guidance(record, self.draft, self.parts)
        self.assertIn(record["proposals"][0]["face"], guidance["omitted_faces"])
        self.assertTrue(guidance["explicitly_preserved_faces"])

    def test_set_includes_valid_nonproposal_face(self):
        record = simplification.build_proposal(self.parts, self.draft, threshold_mm=.1)
        self.assertEqual(record["proposals"], [])
        record["sets"] = []
        record["confirmed"] = True
        # Side wall is deliberately not among small-face suggestions.
        self.add_set(record, faces=[["1/1", 1]])
        simplification.validate_review(record, self.draft, self.parts, require_complete=True)

    def expected_edges(self, refs):
        part = refs[0][0]
        global_edges = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(self.parts[part][0], TopAbs_EDGE, global_edges)
        expected = set()
        for _, index in refs:
            local = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(self.parts[part][1].FindKey(index), TopAbs_EDGE, local)
            for i in range(1, local.Extent()+1):
                expected.add((part, global_edges.FindIndex(local.FindKey(i))))
        return expected, global_edges

    def test_keep_export_uses_independently_indexed_edges_and_lengths(self):
        record = self.record()
        item = self.add_set(record, decision="keep")
        exported = simplification.handoff_guidance(record, self.draft, self.parts)["sets"]
        group = next(g for g in exported if g["decision"] == "keep" and item["faces"][0] in g["faces"])
        expected, indexed = self.expected_edges(group["faces"])
        self.assertEqual(group["reference_policy"], "edges")
        self.assertEqual({tuple(e["edge"]) for e in group["edge_references"]}, expected)
        self.assertEqual(len(group["edge_references"]), len(expected))
        self.assertEqual(group["surface_references"], [])
        for edge in group["edge_references"]:
            props = GProp_GProps()
            BRepGProp.LinearProperties_s(TopoDS.Edge_s(indexed.FindKey(edge["edge"][1])), props)
            self.assertAlmostEqual(edge["length_mm"], props.Mass(), places=8)
            self.assertTrue(edge["source_faces"])
            self.assertTrue(all(ref in group["faces"] for ref in edge["source_faces"]))
            self.assertTrue(all(-2.000001 <= xyz[2] <= .000001 for xyz in edge["endpoints_mm"]))

    def test_simplify_export_has_surface_geometry_and_ordered_plan_only(self):
        record = self.record()
        item = self.add_set(record)
        groups = simplification.handoff_guidance(record, self.draft, self.parts)["sets"]
        group = next(g for g in groups if g["id"] == item["id"])
        self.assertEqual(group["reference_policy"], "surfaces_and_policy")
        self.assertEqual(group["edge_references"], [])
        self.assertEqual({tuple(ref["face"]) for ref in group["surface_references"]}, {tuple(ref) for ref in item["faces"]})
        self.assertEqual(group["approximation"], {"policy": "unspecified", "notes": "", "detail_policy": "omit_chamfers_and_fillets"})
        for reference in group["surface_references"]:
            self.assertEqual(reference["surface_type"], "planar")
            self.assertEqual(len(reference["origin_mm"]), 3)
            self.assertAlmostEqual(sum(v*v for v in reference["normal"]), 1, places=8)
            self.assertEqual(len(reference["uv_bounds"]), 4)

    def test_omitted_only_component_edges_never_exported(self):
        record = self.record()
        faces = [["1/3", i] for i in range(1, self.parts["1/3"][1].Extent()+1)]
        item = self.add_set(record, identifier="omit-part", faces=faces, decision="omit")
        groups = simplification.handoff_guidance(record, self.draft, self.parts)["sets"]
        omitted = next(g for g in groups if g["decision"] == "omit" and item["faces"][0] in g["faces"])
        self.assertEqual(omitted["reference_policy"], "ignore")
        self.assertEqual(omitted["edge_references"], [])
        self.assertEqual(omitted["surface_references"], [])
        self.assertFalse(any(edge["edge"][0] == "1/3" for group in groups for edge in group["edge_references"]))

    def test_shared_edge_still_available_from_kept_adjacent_face(self):
        record = self.record()
        keep = self.add_set(record, identifier="keep-side", faces=[["1/1", 1]], decision="keep")
        omit = self.add_set(record, identifier="omit-side", faces=[["1/1", 3]], decision="omit")
        expected, _ = self.expected_edges(keep["faces"])
        omitted_edges, _ = self.expected_edges(omit["faces"])
        shared = expected & omitted_edges
        self.assertTrue(shared)
        groups = simplification.handoff_guidance(record, self.draft, self.parts)["sets"]
        kept = next(g for g in groups if g["decision"] == "keep" and keep["faces"][0] in g["faces"])
        self.assertTrue(shared <= {tuple(e["edge"]) for e in kept["edge_references"]})
        self.assertEqual(next(g for g in groups if g["decision"] == "omit" and omit["faces"][0] in g["faces"])["edge_references"], [])

    def test_cylindrical_surface_and_circle_edges_keep_absolute_coordinates(self):
        shape = cq.Solid.makeCylinder(2, 6, cq.Vector(20, 3, -4), cq.Vector(0, 1, 0)).wrapped
        faces = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
        self.parts["1/3"] = (shape, faces)
        record = self.record()
        side = next(r["face"] for r in record["proposals"] if r["face"][0] == "1/3" and r["measurement"]["surface_type"] == "cylindrical")
        item = self.add_set(record, faces=[side])
        groups = simplification.handoff_guidance(record, self.draft, self.parts)["sets"]
        group = next(g for g in groups if g["id"] == item["id"])
        surface = group["surface_references"][0]
        self.assertEqual(surface["surface_type"], "cylindrical")
        self.assertAlmostEqual(surface["radius_mm"], 2)
        self.assertEqual(surface["axis_origin_mm"], [20, 3, -4])
        self.assertEqual(surface["axis_direction"], [0, 1, 0])
        circles = [edge for g in groups for edge in g["edge_references"] if edge["edge"][0] == "1/3"]
        self.assertTrue(circles)
        for circle in circles:
            self.assertAlmostEqual(circle["radius_mm"], 2)
            self.assertAlmostEqual(circle["center_mm"][0], 20)
            self.assertAlmostEqual(circle["center_mm"][2], -4)
            self.assertIn(circle["center_mm"][1], (3, 9))

    def test_degenerate_edges_remain_identified_without_fake_curve_hints(self):
        shape = cq.Solid.makeSphere(10).wrapped
        faces = TopTools_IndexedMapOfShape()
        indexed = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
        TopExp.MapShapes_s(shape, TopAbs_EDGE, indexed)
        expected = {i for i in range(1, indexed.Extent()+1)
                    if BRep_Tool.Degenerated_s(TopoDS.Edge_s(indexed.FindKey(i)))}
        self.assertTrue(expected)
        refs = [["sphere", i] for i in range(1, faces.Extent()+1)]
        exported = edge_references(refs, {"sphere": (shape, faces)})
        actual = {edge["edge"][1] for edge in exported if edge["curve_type"] == "degenerate"}
        self.assertEqual(actual, expected)
        for edge in exported:
            if edge["edge"][1] in expected:
                self.assertEqual(edge["length_mm"], 0)
                self.assertNotIn("endpoints_mm", edge)
                self.assertNotIn("radius_mm", edge)

    def test_mounting_block_refuses_unimplemented_reference_set_policies(self):
        record = self.record()
        self.add_set(record)
        handoff = make_handoff(self.draft, self.parts, record)
        with self.assertRaisesRegex(ValueError, "cannot enforce B2 reference sets"):
            target_contacts(handoff, self.draft["manifest_sha256"], self.parts, "1/1", [])

    def test_legacy_mounting_block_empty_contacts_path_still_works(self):
        legacy = {"schema_version": 1, "manifest_sha256": self.draft["manifest_sha256"],
                  "length_unit": "mm", "contact_constraints": []}
        self.assertEqual(target_contacts(legacy, self.draft["manifest_sha256"], self.parts, "1/1", []), [])
        other_part = deepcopy(legacy)
        other_part["simplification_guidance"] = {"face_review": {"sets": [
            {"id": "other", "faces": [["1/3", 1]]}]}}
        self.assertEqual(target_contacts(other_part, self.draft["manifest_sha256"], self.parts, "1/1", []), [])

    def start_request(self):
        state = self.fixture.session.state()
        return {"revision": state["revision"], "simplification_revision": state["simplification_revision"], "threshold_mm": 5}

    def set_request(self, state, *, identifier=None, decision="simplify", faces=None):
        return {"revision": state["revision"], "simplification_revision": state["simplification_revision"],
                "notes": "synthetic set review only", "set": {"id": identifier, "name": "合成段差",
                "faces": faces or self.same_part_faces(state["simplification"])[:2],
                "decision": decision, "approximation": plan() if decision == "simplify" else None}}

    def test_web_set_save_reopen_and_delete(self):
        session = self.fixture.session
        state = session.start_simplification(self.start_request())
        state = session.save_simplification_set(self.set_request(state))
        approximate = [g for g in state["simplification"]["sets"] if g["decision"] == "simplify"]
        self.assertEqual(len(approximate), 1)
        item = approximate[0]
        self.assertEqual(item["decision"], "simplify")
        self.assertFalse(state["simplification"]["confirmed"])
        reopened = web_fixture.ReviewSession(session.bundle, session.candidate_path, session.review_path).state()
        self.assertEqual(reopened["simplification"], state["simplification"])
        request = {"revision": state["revision"], "simplification_revision": state["simplification_revision"], "id": item["id"]}
        state = session.delete_simplification_set(request)
        self.assertFalse(any(g["decision"] == "simplify" for g in state["simplification"]["sets"]))
        self.assertTrue(all(row["decision"] == "pending" for row in state["simplification"]["proposals"] if row["face"] in item["faces"]))

    def test_web_stale_set_save_conflict_does_not_write(self):
        session = self.fixture.session
        state = session.start_simplification(self.start_request())
        request = self.set_request(state)
        session.save_simplification_set(request)
        before = session.simplification_path.read_bytes()
        with self.assertRaises(ValueError):
            session.save_simplification_set(request)
        self.assertEqual(session.simplification_path.read_bytes(), before)

    def test_web_edit_members_restores_removed_rows_pending(self):
        session = self.fixture.session
        state = session.start_simplification(self.start_request())
        state = session.save_simplification_set(self.set_request(state))
        group = next(g for g in state["simplification"]["sets"] if g["decision"] == "simplify")
        retained = group["faces"][:1]
        removed = group["faces"][1:]
        state = session.save_simplification_set(self.set_request(state, identifier=group["id"], faces=retained))
        self.assertEqual(len([g for g in state["simplification"]["sets"] if g["decision"] == "simplify"]), 1)
        self.assertTrue(all(row["decision"] == "pending" for row in state["simplification"]["proposals"] if row["face"] in removed))
        self.assertTrue(all(row["decision"] == "simplify" for row in state["simplification"]["proposals"] if row["face"] in retained))

    def test_regular_row_save_cannot_override_grouped_face(self):
        session = self.fixture.session
        state = session.start_simplification(self.start_request())
        state = session.save_simplification_set(self.set_request(state))
        member = next(g for g in state["simplification"]["sets"] if g["decision"] == "simplify")["faces"][0]
        row = next(r for r in state["simplification"]["proposals"] if r["face"] == member)
        request = {"revision": state["revision"], "simplification_revision": state["simplification_revision"],
                   "item": {"id": row["id"], "decision": "omit"}, "notes": "must refuse"}
        with self.assertRaises(ValueError):
            session.save_simplification(request)


if __name__ == "__main__":
    unittest.main()
