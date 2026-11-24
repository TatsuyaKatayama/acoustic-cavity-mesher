"""Independent synthetic-only tests for local B2 review persistence and HTTP."""

from copy import deepcopy
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

import cadquery as cq

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.gp import gp_Ax3, gp_Cylinder
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

from b1_step import brep_bytes
from b2_review import make_handoff
from b2_simplification import build_proposal
from review_contacts_web import ReviewSession, handler_for, render_scene


IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]


def synthetic_handoff(draft, parts):
    simplification = build_proposal(parts, draft)
    for proposal in simplification["proposals"]:
        proposal["decision"] = "keep"
    simplification["confirmed"] = True
    return make_handoff(draft, parts, simplification)


class WebReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        (self.bundle / "parts").mkdir()
        shapes = [cq.Solid.makeBox(4, 4, 2, cq.Vector(-2, -2, -2)),
                  cq.Solid.makeBox(4, 4, 2, cq.Vector(-2, -2, 0)),
                  cq.Solid.makeBox(4, 4, 2, cq.Vector(-1, -2, 0))]
        nodes = [{"id": "1", "parent_id": None, "kind": "assembly", "name": "synthetic",
                  "definition_name": "synthetic", "world_transform": IDENTITY, "local_transform": IDENTITY}]
        self.top = None
        self.bottom = {}
        for index, shape in enumerate(shapes, 1):
            data = brep_bytes(shape.wrapped)
            digest = sha256(data).hexdigest()
            path = f"parts/{digest}.brep"
            (self.bundle / path).write_bytes(data)
            part = f"1/{index}"
            nodes.append({"id": part, "parent_id": "1", "kind": "part", "name": f"Box{index}",
                          "definition_name": f"Box{index}", "world_transform": IDENTITY,
                          "local_transform": IDENTITY, "geometry": path})
            for face_index, face in enumerate(shape.Faces(), 1):
                if abs(face.Center().z) < 1e-7 and face.normalAt().z > .9:
                    self.top = [part, face_index]
                if abs(face.Center().z) < 1e-7 and face.normalAt().z < -.9:
                    self.bottom[part] = [part, face_index]
        manifest = {"schema_version": 1, "source_sha256": "synthetic", "length_unit": "mm", "nodes": nodes}
        manifest_bytes = json.dumps(manifest).encode()
        (self.bundle / "assembly.json").write_bytes(manifest_bytes)
        self.candidates = self.bundle / "contacts.json"
        self.review = self.bundle / "review.json"
        self.original_pair = [self.top, self.bottom["1/2"]]
        self.corrected_pair = [self.top, self.bottom["1/3"]]
        self.candidates.write_text(json.dumps({"schema_version": 1,
            "manifest_sha256": sha256(manifest_bytes).hexdigest(),
            "max_gap_mm": .1, "min_overlap_mm2": .01,
            "candidates": [{"faces": self.original_pair, "contact_type": "planar", "gap_mm": 0, "overlap_mm2": 16}]}))
        self.session = ReviewSession(self.bundle, self.candidates, self.review)

    def request(self, *, decision="pending", pair=None, condition=None, revision=None):
        return {"revision": revision if revision is not None else self.session.state()["revision"],
                "simplification_notes": "synthetic fixture only",
                "item": {"candidate_id": 1, "faces": pair or self.original_pair,
                         "decision": decision, "condition": condition}}

    def accepted(self, pair=None):
        return self.request(decision="accepted", pair=pair,
                            condition={"mode": "close", "target_gap_mm": 0, "tolerance_mm": .01})

    def test_save_reload_corrected_references_and_recomputed_measurement(self):
        state = self.session.save(self.accepted(self.corrected_pair))
        row = state["draft"]["reviews"][0]
        self.assertEqual(row["faces"], self.corrected_pair)
        self.assertAlmostEqual(row["measurement"]["overlap_mm2"], 12)
        self.assertEqual(row["measurement"]["contact_type"], "planar")
        reopened = ReviewSession(self.bundle, self.candidates, self.review).state()
        self.assertEqual(reopened["draft"], state["draft"])
        handoff = synthetic_handoff(reopened["draft"], self.session.parts)
        self.assertEqual([list(f) for f in handoff["contact_constraints"][0]["faces"]], self.corrected_pair)
        self.assertEqual(handoff["contact_constraints"][0]["contact_type"], "planar")
        self.assertAlmostEqual(handoff["contact_constraints"][0]["source_measurement"]["overlap_mm2"], 12)

    def test_handoff_recomputes_stored_measurement(self):
        state = self.session.save(self.accepted(self.corrected_pair))
        draft = deepcopy(state["draft"])
        draft["reviews"][0]["measurement"] = {"contact_type": "cylindrical", "overlap_mm2": 1000000, "gap_mm": 999}
        constraint = synthetic_handoff(draft, self.session.parts)["contact_constraints"][0]
        self.assertEqual(constraint["contact_type"], "planar")
        self.assertAlmostEqual(constraint["source_measurement"]["overlap_mm2"], 12)

    def test_cylindrical_handoff_preserves_contact_type_and_gap(self):
        outside = BRepBuilderAPI_MakeFace(gp_Cylinder(gp_Ax3(), 10), 0, 2 * math.pi, 0, 5).Face()
        inside = BRepBuilderAPI_MakeFace(gp_Cylinder(gp_Ax3(), 10.05), 0, 2 * math.pi, 0, 5).Face()
        inside = TopoDS.Face_s(inside.Reversed())
        parts = {}
        for name, face in [("outer", outside), ("inner", inside)]:
            faces = TopTools_IndexedMapOfShape()
            faces.Add(face)
            parts[name] = (face, faces)
        draft = deepcopy(self.session.state()["draft"])
        draft["reviews"][0].update(faces=[["outer", 1], ["inner", 1]], decision="accepted",
            condition={"mode": "keep_gap", "target_gap_mm": .05, "tolerance_mm": .01})
        constraint = synthetic_handoff(draft, parts)["contact_constraints"][0]
        self.assertEqual(constraint["contact_type"], "cylindrical")
        self.assertAlmostEqual(constraint["source_measurement"]["gap_mm"], .05)
        self.assertAlmostEqual(constraint["source_measurement"]["overlap_mm2"], 100 * math.pi)

    def test_pending_handoff_blocked(self):
        state = self.session.save(self.request())
        with self.assertRaisesRegex(ValueError, "pending"):
            make_handoff(state["draft"], self.session.parts)

    def test_optimistic_conflict_preserves_saved_content(self):
        stale = self.request()
        self.session.save(self.accepted())
        before = self.review.read_bytes()
        with self.assertRaises(ValueError):
            self.session.save(stale)
        self.assertEqual(self.review.read_bytes(), before)

    def test_changed_manifest_or_candidates_rejected(self):
        request = self.request()
        self.candidates.write_bytes(self.candidates.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            self.session.save(request)
        with self.assertRaises(ValueError):
            self.session.state()

    def test_review_wrong_manifest_hash_rejected(self):
        self.session.save(self.request())
        data = json.loads(self.review.read_text())
        data["manifest_sha256"] = "wrong"
        self.review.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            ReviewSession(self.bundle, self.candidates, self.review)

    def test_geometry_hash_mutation_rejected(self):
        request = self.request()
        path = next((self.bundle / "parts").glob("*.brep"))
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(ValueError):
            self.session.save(request)
        with self.assertRaises(ValueError):
            self.session.state()
        self.assertFalse(self.review.exists())

    def test_invalid_decision_and_keep_gap_rejected(self):
        for request in [self.request(decision="unknown"),
                        self.request(decision="accepted", condition={"mode": "keep_gap", "target_gap_mm": .1, "tolerance_mm": .1}),
                        self.request(decision="accepted", condition={"mode": "keep_gap", "target_gap_mm": 0, "tolerance_mm": .01})]:
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.session.save(request)
        self.assertFalse(self.review.exists())

    def test_invalid_and_unrendered_face_acceptance_rejected(self):
        with self.assertRaises(ValueError):
            self.session.save(self.accepted([self.top, ["1/2", 999]]))
        self.session.unrendered_faces = [self.top]
        with self.assertRaises(ValueError):
            self.session.save(self.accepted())

    def test_client_cannot_forge_measurement(self):
        request = self.accepted(self.corrected_pair)
        request["item"]["measurement"] = {"overlap_mm2": 1000000, "gap_mm": 999}
        state = self.session.save(request)
        self.assertAlmostEqual(state["draft"]["reviews"][0]["measurement"]["overlap_mm2"], 12)

    def test_scene_explicit_brep_mapping(self):
        scene = render_scene(self.session.parts, self.session.nodes)
        expected = {(part, index) for part, (_, faces) in self.session.parts.items()
                    for index in range(1, faces.Extent() + 1)}
        actual = {tuple(ref) for ref in scene["face_map"].values()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(scene["face_map"]), 18)
        self.assertEqual(scene["unrendered_faces"], [])
        self.assertTrue(all(isinstance(path, str) for path in scene["face_map"]))

    def test_scene_missing_face_refined_and_mapped_once(self):
        from ocp_viewer_core.offline import _convert as real_convert
        calls = []
        dropped = []

        def convert(*args, **kwargs):
            result = real_convert(*args, **kwargs)
            payload = deepcopy(result[0])
            calls.append(kwargs)
            if len(calls) == 1:
                def drop_leaf(node):
                    for index, child in enumerate(node.get("parts", [])):
                        if "parts" not in child:
                            dropped.append(child)
                            node["parts"].pop(index)
                            return True
                        if drop_leaf(child):
                            return True
                    return False
                self.assertTrue(drop_leaf(payload["data"]["shapes"]))
            return (payload, *result[1:])

        with patch("ocp_viewer_core.offline._convert", side_effect=convert):
            scene = render_scene(self.session.parts, self.session.nodes)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["deviation"], .0001)
        expected_ref = ["/".join(dropped[0]["name"].split("_")[1:-1]), int(dropped[0]["name"].split("_")[-1])]
        self.assertEqual(scene["refined_faces"], [expected_ref])
        self.assertEqual(scene["unrendered_faces"], [])
        expected = {(part, index) for part, (_, faces) in self.session.parts.items()
                    for index in range(1, faces.Extent() + 1)}
        self.assertEqual({tuple(ref) for ref in scene["face_map"].values()}, expected)
        self.assertEqual(len(scene["face_map"]), 18)
        leaves = {}
        def walk(node):
            if "parts" in node:
                for child in node["parts"]:
                    walk(child)
            else:
                self.assertNotIn(node["id"], leaves)
                leaves[node["id"]] = node
        walk(scene["model"]["data"]["shapes"])
        self.assertEqual(set(leaves), set(scene["face_map"]))
        for leaf in leaves.values():
            self.assertLess(leaf["shape"]["ref"], len(scene["model"]["data"]["instances"]))
        refined_path = next(path for path, ref in scene["face_map"].items() if ref == expected_ref)
        part_group = f'/Box{expected_ref[0].split("/")[-1]} [{expected_ref[0].replace("/", "_")}]'
        self.assertIn(part_group + "/", refined_path)

    def test_http_token_origin_and_save(self):
        handler = handler_for(self.session, {"test": True})
        handler.log_message = lambda *args: None
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_port

        def call(method, path, data=None, headers=None):
            connection = HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                body = json.dumps(data) if data is not None else None
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        self.assertEqual(call("GET", "/api/state")[0], 200)
        self.assertEqual(call("GET", "/api/state", headers={"Origin": "https://other.invalid"})[0], 403)
        self.assertEqual(call("GET", "/api/state", headers={"Host": "other.invalid"})[0], 403)
        self.assertEqual(call("POST", "/api/save", self.request())[0], 403)
        headers = {"X-B2-Token": self.session.token, "Origin": f"http://127.0.0.1:{port}"}
        self.assertEqual(call("POST", "/api/save", self.request(), {**headers, "Origin": "https://other.invalid"})[0], 403)
        status, raw = call("POST", "/api/measure", {"faces": self.corrected_pair}, headers)
        self.assertEqual(status, 200)
        self.assertAlmostEqual(json.loads(raw)["measurement"]["overlap_mm2"], 12)
        self.assertEqual(call("POST", "/api/save", self.request(), headers)[0], 200)
        self.assertEqual(call("GET", "/assets/../../review_contacts_web.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
