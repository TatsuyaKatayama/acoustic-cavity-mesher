"""Independent synthetic checks for B2 contact protection and omission review."""

from copy import deepcopy
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import subprocess
import sys
from threading import Thread
import unittest

import cadquery as cq
from OCP.TopTools import TopTools_IndexedMapOfShape

from b2_simplification import build_proposal, contact_signature, validate_review
from b2_review import make_handoff
import test_b2_web as web_fixture


class SimplificationTests(unittest.TestCase):
    def setUp(self):
        # Reuse only the fixture builder, never inherit its test methods.
        fixture = web_fixture.WebReviewTests(methodName="test_pending_handoff_blocked")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.parts = fixture.session.parts
        self.draft = deepcopy(fixture.session.state()["draft"])
        self.draft["reviews"][0].update(
            decision="accepted",
            condition={"mode": "close", "target_gap_mm": 0, "tolerance_mm": .01},
        )

    def proposal(self):
        return build_proposal(self.parts, self.draft)

    def completed(self):
        record = self.proposal()
        for item in record["proposals"]:
            item["decision"] = "keep"
        record["confirmed"] = True
        return record

    def test_contact_review_must_be_complete_first(self):
        self.draft["reviews"][0].update(decision="pending", condition=None)
        with self.assertRaises(ValueError):
            self.proposal()

    def test_contact_faces_are_never_omission_proposals(self):
        record = self.proposal()
        protected = {tuple(ref) for ref in self.draft["reviews"][0]["faces"]}
        self.assertEqual({tuple(ref) for ref in record["protected_faces"]}, protected)
        proposed = {tuple(item["face"]) for item in record["proposals"]}
        self.assertTrue(proposed)
        self.assertFalse(protected & proposed)
        self.assertTrue(all(item["decision"] == "pending" for item in record["proposals"]))
        validate_review(record, self.draft, self.parts)

    def test_rejected_contact_is_not_protected(self):
        self.draft["reviews"][0].update(decision="rejected", condition=None)
        record = self.proposal()
        self.assertEqual(record["protected_faces"], [])
        validate_review(record, self.draft, self.parts)

    def test_contact_protection_cannot_be_removed_from_record(self):
        record = self.proposal()
        record["protected_faces"] = []
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts)

    def test_forged_contact_omission_is_rejected(self):
        record = self.completed()
        record["proposals"][0].update(face=self.draft["reviews"][0]["faces"][0], decision="omit")
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts, require_complete=True)

    def test_unknown_face_is_rejected(self):
        record = self.completed()
        record["proposals"][0]["face"] = ["1/1", 99999]
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts)

    def test_pending_rows_cannot_be_removed_to_bypass_review(self):
        record = self.proposal()
        record["proposals"].pop()
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts, require_complete=True)

    def test_pending_rows_block_completion(self):
        with self.assertRaises(ValueError):
            validate_review(self.proposal(), self.draft, self.parts, require_complete=True)

    def test_decision_values_are_validated(self):
        record = self.completed()
        record["proposals"][0]["decision"] = "delete_now"
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts)

    def test_omission_and_preservation_are_review_decisions(self):
        record = self.completed()
        record["proposals"][0]["decision"] = "omit"
        validate_review(record, self.draft, self.parts, require_complete=True)

    def test_explicit_confirmation_is_required_even_after_all_rows(self):
        record = self.completed()
        record["confirmed"] = False
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts, require_complete=True)

    def test_unproposed_faces_are_preserved_by_default(self):
        record = build_proposal(self.parts, self.draft, threshold_mm=.1)
        self.assertEqual(record["default_policy"], "preserve")
        self.assertEqual(record["proposals"], [])
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts, require_complete=True)
        record["confirmed"] = True
        validate_review(record, self.draft, self.parts, require_complete=True)

    def test_measurements_cannot_be_forged(self):
        record = self.completed()
        record["proposals"][0]["measurement"] = {"area_mm2": 999999}
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts)

    def test_contact_changes_invalidate_simplification(self):
        record = self.completed()
        self.draft["reviews"][0]["condition"]["tolerance_mm"] = .02
        with self.assertRaises(ValueError):
            validate_review(record, self.draft, self.parts)

    def test_signature_ignores_derived_measurement(self):
        signature = contact_signature(self.draft)
        self.draft["reviews"][0]["measurement"] = {"gap_mm": 99999}
        self.assertEqual(contact_signature(self.draft), signature)

    def test_bad_thresholds_are_rejected(self):
        for threshold in [0, -1, math.nan, math.inf, True, "5"]:
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                build_proposal(self.parts, self.draft, threshold_mm=threshold)

    def test_planar_width_uses_face_frame_not_world_bbox(self):
        wire = cq.Workplane("XY").rect(2, 20).val()
        face = cq.Face.makeFromWires(wire).rotate((0, 0, 0), (0, 0, 1), 45)
        indexed = TopTools_IndexedMapOfShape()
        indexed.Add(face.wrapped)
        draft = deepcopy(self.draft)
        draft["reviews"] = []
        record = build_proposal({"narrow": (face.wrapped, indexed)}, draft, threshold_mm=3)
        self.assertEqual(len(record["proposals"]), 1)
        self.assertAlmostEqual(record["proposals"][0]["measurement"]["area_mm2"], 40)
        self.assertAlmostEqual(min(record["proposals"][0]["measurement"]["planar_spans_mm"]), 2)

    def test_cylindrical_diameter_and_axial_span_are_separate_reasons(self):
        from test_b2_cylinders import cylinder
        draft = deepcopy(self.draft)
        draft["reviews"] = []
        parts = {}
        for name, face in [("bore", cylinder(radius=2, inward=True, v=(0, 20))),
                           ("rim", cylinder(radius=10, v=(0, 2))),
                           ("large", cylinder(radius=10, v=(0, 20)))]:
            indexed = TopTools_IndexedMapOfShape()
            indexed.Add(face)
            parts[name] = (face, indexed)
        record = build_proposal(parts, draft, threshold_mm=5)
        by_name = {row["face"][0]: row for row in record["proposals"]}
        self.assertEqual(set(by_name), {"bore", "rim"})
        self.assertEqual(by_name["bore"]["measurement"]["diameter_mm"], 4)
        self.assertEqual(by_name["rim"]["measurement"]["axial_span_mm"], 2)
        self.assertTrue(all(row["decision"] == "pending" for row in by_name.values()))

    def test_geometry_files_remain_unchanged(self):
        paths = list((self.fixture.bundle / "parts").glob("*.brep"))
        before = {path: sha256(path.read_bytes()).hexdigest() for path in paths}
        record = self.completed()
        record["proposals"][0]["decision"] = "omit"
        validate_review(record, self.draft, self.parts, require_complete=True)
        after = {path: sha256(path.read_bytes()).hexdigest() for path in paths}
        self.assertEqual(before, after)

    def test_handoff_requires_simplification_review(self):
        with self.assertRaises(ValueError):
            make_handoff(self.draft, self.parts)
        with self.assertRaises(ValueError):
            make_handoff(self.draft, self.parts, self.proposal())
        result = make_handoff(self.draft, self.parts, self.completed())
        self.assertEqual(len(result["contact_constraints"]), 1)
        guidance = result["simplification_guidance"]["face_review"]
        self.assertEqual(guidance["protected_contact_faces"], self.completed()["protected_faces"])
        self.assertEqual(guidance["default_face_policy"], "preserve")

    def session_request(self, **values):
        state = self.fixture.session.state()
        return {"revision": state["revision"],
                "simplification_revision": state["simplification_revision"], **values}

    def start(self, threshold=5):
        self.fixture.session.save(self.fixture.accepted())
        return self.fixture.session.start_simplification(self.session_request(threshold_mm=threshold))

    def decide(self, index, decision):
        return self.fixture.session.save_simplification(self.session_request(
            item={"id": index, "decision": decision}, notes="synthetic omission policy"))

    def test_web_phase_gate_and_separate_pending_file(self):
        session = self.fixture.session
        self.assertEqual(session.state()["simplification_status"], "locked")
        with self.assertRaises(ValueError):
            session.start_simplification(self.session_request())
        self.assertFalse(session.simplification_path.exists())
        state = self.start()
        self.assertEqual(state["simplification_status"], "reviewing")
        self.assertTrue(all(row["decision"] == "pending" for row in state["simplification"]["proposals"]))
        self.assertTrue(session.simplification_path.exists())
        self.assertNotEqual(session.review_path, session.simplification_path)

    def test_web_pending_proposals_block_finish_without_writing(self):
        self.start()
        session = self.fixture.session
        before = session.simplification_path.read_bytes()
        with self.assertRaises(ValueError):
            session.finish_simplification(self.session_request(notes="not complete"))
        self.assertEqual(session.simplification_path.read_bytes(), before)

    def test_web_save_reopen_finish_and_handoff(self):
        state = self.start()
        ids = [row["id"] for row in state["simplification"]["proposals"]]
        for index in ids:
            state = self.decide(index, "omit" if index == ids[0] else "keep")
        self.assertFalse(state["simplification"]["confirmed"])
        state = self.fixture.session.finish_simplification(self.session_request(notes="confirmed synthetic policy"))
        self.assertEqual(state["simplification_status"], "confirmed")
        from review_contacts_web import ReviewSession
        reopened = ReviewSession(self.fixture.bundle, self.fixture.candidates, self.fixture.review).state()
        self.assertEqual(reopened["simplification"], state["simplification"])
        handoff = make_handoff(state["draft"], self.parts, state["simplification"])
        guidance = handoff["simplification_guidance"]["face_review"]
        self.assertEqual(len(guidance["omitted_faces"]), 1)
        self.assertFalse({tuple(ref) for ref in guidance["protected_contact_faces"]}
                         & {tuple(ref) for ref in guidance["omitted_faces"]})
        self.decide(ids[0], "keep")
        self.assertEqual(self.fixture.session.state()["simplification_status"], "reviewing")

    def test_web_forged_face_and_invalid_decisions_do_not_write(self):
        state = self.start()
        session = self.fixture.session
        before = session.simplification_path.read_bytes()
        for item in [
            {"id": 1, "decision": "omit", "face": state["simplification"]["protected_faces"][0]},
            {"id": 1, "decision": "delete_now"},
            {"id": 99999, "decision": "omit"},
        ]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                session.save_simplification(self.session_request(item=item, notes="forged"))
            self.assertEqual(session.simplification_path.read_bytes(), before)

    def test_web_unrendered_face_cannot_be_omitted(self):
        state = self.start()
        session = self.fixture.session
        item = state["simplification"]["proposals"][0]
        session.unrendered_faces = [item["face"]]
        with self.assertRaises(ValueError):
            self.decide(item["id"], "omit")
        self.decide(item["id"], "keep")

    def test_web_stale_concurrent_edit_is_rejected(self):
        self.start()
        request = self.session_request(item={"id": 1, "decision": "omit"}, notes="stale")
        self.decide(1, "keep")
        before = self.fixture.session.simplification_path.read_bytes()
        with self.assertRaises(ValueError):
            self.fixture.session.save_simplification(request)
        self.assertEqual(self.fixture.session.simplification_path.read_bytes(), before)

    def test_web_new_contact_invalidates_old_omission_and_preserves_evidence(self):
        state = self.start()
        new_contact = self.fixture.corrected_pair[1]
        proposal = next(row for row in state["simplification"]["proposals"] if row["face"] == new_contact)
        self.decide(proposal["id"], "omit")
        session = self.fixture.session
        previous = session.simplification_path.read_bytes()
        state = session.save(self.fixture.accepted(self.fixture.corrected_pair))
        self.assertEqual(state["simplification_status"], "stale")
        self.assertIsNone(state["simplification"])
        self.assertEqual(session.simplification_path.read_bytes(), previous)
        with self.assertRaises(ValueError):
            make_handoff(state["draft"], self.parts, json.loads(previous))
        state = session.start_simplification(self.session_request())
        self.assertIn(new_contact, state["simplification"]["protected_faces"])
        self.assertNotIn(new_contact, [row["face"] for row in state["simplification"]["proposals"]])
        archives = list(session.simplification_path.parent.glob("*.previous-*.json"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), previous)

    def test_web_empty_proposals_still_require_explicit_finish(self):
        state = self.start(threshold=.1)
        self.assertEqual(state["simplification"]["proposals"], [])
        self.assertFalse(state["simplification"]["confirmed"])
        state = self.fixture.session.finish_simplification(self.session_request(notes="nothing to omit"))
        self.assertEqual(state["simplification_status"], "confirmed")

    def test_corrupt_confirmed_pending_record_is_not_reported_complete(self):
        self.start()
        session = self.fixture.session
        record = json.loads(session.simplification_path.read_text())
        record["confirmed"] = True
        session.simplification_path.write_text(json.dumps(record), encoding="utf-8")
        state = session.state()
        self.assertNotEqual(state["simplification_status"], "confirmed")

    def test_http_sequential_review_routes(self):
        from review_contacts_web import handler_for
        session = self.fixture.session
        handler = handler_for(session, {"synthetic": True})
        handler.log_message = lambda *args: None
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_port

        def call(path, request, token=True):
            headers = {"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}
            if token:
                headers["X-B2-Token"] = session.token
            connection = HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                connection.request("POST", path, json.dumps(request), headers)
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        self.assertEqual(call("/api/simplification/start", self.session_request())[0], 409)
        self.assertEqual(call("/api/save", self.fixture.accepted())[0], 200)
        status, state = call("/api/simplification/start", self.session_request())
        self.assertEqual(status, 200)
        row = state["simplification"]["proposals"][0]
        request = self.session_request(item={"id": row["id"], "decision": "keep"}, notes="HTTP synthetic")
        self.assertEqual(call("/api/simplification/save", request, token=False)[0], 403)
        self.assertEqual(call("/api/simplification/save", request)[0], 200)
        self.assertEqual(call("/api/simplification/finish", self.session_request(notes="pending"))[0], 409)

    def test_cli_proposal_and_export_require_both_reviews(self):
        self.fixture.session.save(self.fixture.accepted())
        builder = Path(__file__).resolve().parents[1] / 'tools'
        policy_path = self.fixture.bundle / "cli-simplification.json"
        output_path = self.fixture.bundle / "handoff.json"
        arguments = [str(self.fixture.bundle), str(self.fixture.candidates), str(self.fixture.review)]
        proposal = subprocess.run([sys.executable, str(builder / "propose_simplification.py"),
                                   *arguments, str(policy_path)], capture_output=True, text=True)
        self.assertEqual(proposal.returncode, 0, proposal.stderr)
        record = json.loads(policy_path.read_text(encoding="utf-8"))
        self.assertFalse(record["confirmed"])
        export_args = [sys.executable, str(builder / "export_template_inputs.py"),
                       *arguments, str(output_path), "--simplification-review", str(policy_path)]
        pending = subprocess.run(export_args, capture_output=True, text=True)
        self.assertEqual(pending.returncode, 1)
        self.assertFalse(output_path.exists())
        for row in record["proposals"]:
            row["decision"] = "keep"
        record["confirmed"] = True
        policy_path.write_text(json.dumps(record), encoding="utf-8")
        complete = subprocess.run(export_args, capture_output=True, text=True)
        self.assertEqual(complete.returncode, 0, complete.stderr)
        handoff = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(handoff["simplification_guidance"]["face_review"]["default_face_policy"], "preserve")


if __name__ == "__main__":
    unittest.main()
