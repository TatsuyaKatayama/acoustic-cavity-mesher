"""Serve the B2 face review locally; persist decisions without running B3."""

import argparse
from copy import deepcopy
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from threading import Lock
from urllib.parse import urlsplit
import webbrowser

from OCP.TopoDS import TopoDS

from b2_faces import load_scene, validate_pair, write_json
from b2_review import open_review, validate_decision
from b2_simplification import build_proposal, validate_review
from propose_contacts import measure_contact


def measure_pair(pair, parts):
    pair = validate_pair(pair, parts)
    return measure_contact(*(TopoDS.Face_s(parts[p][1].FindKey(i)) for p, i in pair))


def render_scene(parts, nodes=None):
    """Each selectable viewer leaf is built from ONE explicitly indexed BREP face.

    Viewer element numbers are deliberately never interpreted as BREP indices.
    The returned path table is the sole bridge from display to source topology.
    """
    import cadquery as cq
    from ocp_viewer import Camera
    from ocp_viewer_core.offline import _convert

    assembly = cq.Assembly(name="B2")
    refs = {}
    groups = {}
    for node in nodes or []:
        label = (node["definition_name"] or node["name"]).replace("/", "_")
        group = cq.Assembly(name=f'{label} [{node["id"].replace("/", "_")}]')
        groups[node["id"]] = group
    for part_id, (_, faces) in parts.items():
        if part_id in groups:
            group = groups[part_id]
        else:
            group = cq.Assembly(name="p" + part_id.replace("/", "_"))
        for i in range(1, faces.Extent() + 1):
            name = f'face_{part_id.replace("/", "_")}_{i}'
            group.add(cq.Face(TopoDS.Face_s(faces.FindKey(i))), name=name,
                      color=cq.Color(0.62, 0.68, 0.75))
            refs[name] = [part_id, i]
        if part_id not in groups:
            assembly.add(group)
    for node in reversed(nodes or []):
        (groups[node["parent_id"]] if node["parent_id"] else assembly).add(groups[node["id"]])
    payload = _convert(assembly, reset_camera=Camera.RESET, ortho=True,
                       control="trackball", parallel=False)[0]
    mapping = {}

    def walk(node, ancestors=()):
        names = (*ancestors, node["name"])
        if "parts" in node:
            for child in node["parts"]:
                walk(child, names)
        else:
            reference = refs.get(names[-1])
            if reference is None or reference in mapping.values():
                raise ValueError("Ambiguous viewer to BREP face mapping")
            mapping[node["id"]] = reference
    walk(payload["data"]["shapes"])
    mapped = {tuple(ref) for ref in mapping.values()}
    omitted = [ref for ref in refs.values() if tuple(ref) not in mapped]
    refined = []
    # Some valid narrow/complex planar wires fail the default display mesh.
    # Retry ONLY omitted faces with a finer mesh, retaining the same BREP ref.
    # This changes display tessellation, never the source CAD or OCCT metrics.
    for part_id, index in list(omitted):
        face = cq.Face(TopoDS.Face_s(parts[part_id][1].FindKey(index)))
        fallback = _convert(face, deviation=0.0001, reset_camera=Camera.RESET,
                            parallel=False)[0]["data"]
        if not fallback["instances"]:
            continue
        offset = len(payload["data"]["instances"])
        payload["data"]["instances"].extend(fallback["instances"])
        retry_name = f"面 {index}"
        retry_root = fallback["shapes"]

        def find_group(node):
            wanted = groups[part_id].name if part_id in groups else "p"+part_id.replace("/", "_")
            if node["name"] == wanted:
                return node
            for child in node.get("parts", []):
                found = find_group(child)
                if found is not None:
                    return found
            return None
        parent = find_group(payload["data"]["shapes"])
        if parent is None:
            parent = payload["data"]["shapes"]
            retry_name = f'{part_id} 面 {index}'

        def rebase(node, path):
            node["id"] = path
            if "parts" in node:
                for child in node["parts"]:
                    rebase(child, path+"/"+child["name"])
            else:
                node["shape"]["ref"] += offset
                node["color"] = "#9eacbf"
                mapping[path] = [part_id, index]
        retry_root["name"] = retry_name
        rebase(retry_root, parent["id"]+"/"+retry_name)
        parent["parts"].append(retry_root)
        refined.append([part_id, index])
        omitted.remove([part_id, index])
    from propose_contacts import bounds
    return {"model": payload, "face_map": mapping, "unrendered_faces": omitted, "refined_faces": refined,
            "part_bounds": {p: list(bounds(s).Get()) for p, (s, _) in parts.items()}}


class ReviewSession:
    def __init__(self, bundle, candidates, review, simplification_review=None):
        self.bundle, self.candidate_path, self.review_path = bundle, candidates, review
        self.digest, self.parts, self.nodes = load_scene(bundle)
        self.candidates, self.draft = open_review(self.digest, self.parts, candidates, review)
        self.source_digest = sha256(candidates.read_bytes()).hexdigest()
        self.token = secrets.token_urlsafe(32)
        self.lock = Lock()
        self.unrendered_faces = []
        self.simplification_path = simplification_review or review.with_name(review.stem+".simplification.json")

    def ensure_sources(self):
        if sha256((self.bundle / "assembly.json").read_bytes()).hexdigest() != self.digest or sha256(self.candidate_path.read_bytes()).hexdigest() != self.source_digest:
            raise ValueError("B1または候補ファイルが変更されています。サーバーを再起動してください。")
        for reference in {n['geometry'] for n in self.nodes if n['kind'] == 'part'}:
            if sha256((self.bundle/reference).read_bytes()).hexdigest() != Path(reference).stem:
                raise ValueError("B1形状ファイルが変更されています。")

    def revision(self):
        return sha256(self.review_path.read_bytes()).hexdigest() if self.review_path.exists() else "new"

    def state(self):
        self.ensure_sources()
        _, draft = open_review(self.digest, self.parts, self.candidate_path, self.review_path)
        self.draft = draft
        complete = all(row["decision"] != "pending" for row in draft["reviews"])
        simplification = None
        status, error = ("not_started" if complete else "locked"), ""
        if self.simplification_path.exists():
            try:
                simplification = json.loads(self.simplification_path.read_text(encoding="utf-8"))
                validate_review(simplification, draft, self.parts)
                status = "confirmed" if simplification["confirmed"] else "reviewing"
            except (ValueError, KeyError, TypeError) as exc:
                status, error = ("stale" if complete else "locked"), str(exc)
                simplification = None
        return {"draft": draft, "revision": self.revision(), "token": self.token,
                "candidates": json.loads(self.candidate_path.read_text(encoding="utf-8"))["candidates"],
                "nodes": self.nodes, "contacts_complete": complete,
                "simplification": simplification, "simplification_status": status,
                "simplification_error": error, "simplification_revision": self.simplification_revision()}

    def simplification_revision(self):
        return sha256(self.simplification_path.read_bytes()).hexdigest() if self.simplification_path.exists() else "new"

    def check_revision(self, request, *, simplification=False):
        self.ensure_sources()
        if request["revision"] != self.revision():
            raise ValueError("接合面レビューが更新されました。再読込してください。")
        if simplification and request["simplification_revision"] != self.simplification_revision():
            raise ValueError("簡略化レビューが別のタブで更新されました。再読込してください。")

    def start_simplification(self, request):
        with self.lock:
            self.check_revision(request, simplification=True)
            state = self.state()
            if state["simplification"] is not None:
                return state
            record = build_proposal(self.parts, state["draft"], request.get("threshold_mm", 5))
            if self.simplification_path.exists():
                # Retain previous judgments when contacts change; regeneration is explicit.
                old = self.simplification_path.read_bytes()
                archive = self.simplification_path.with_name(self.simplification_path.stem+".previous-"+sha256(old).hexdigest()[:16]+".json")
                if not archive.exists():
                    with archive.open("xb") as stream:
                        stream.write(old)
            write_json(self.simplification_path, record)
            return self.state()

    def save_simplification(self, request):
        with self.lock:
            self.check_revision(request, simplification=True)
            state = self.state()
            record = deepcopy(state["simplification"])
            if record is None:
                raise ValueError("接合面レビューを完了し、削除提案を作成してください。")
            item = request["item"]
            index = item["id"]
            if type(index) is not int or not 1 <= index <= len(record["proposals"]):
                raise ValueError("Unknown simplification proposal")
            # The client supplies a decision only, never editable face references.
            if set(item) != {"id", "decision"}:
                raise ValueError("削除対象の面参照は変更できません。接合面は省略できません。")
            reference = record["proposals"][index-1]["face"]
            if item["decision"] == "omit" and reference in self.unrendered_faces:
                raise ValueError("描画できない面は省略判断を保存できません。")
            record["proposals"][index-1]["decision"] = item["decision"]
            record["notes"] = request["notes"]
            record["confirmed"] = False
            validate_review(record, state["draft"], self.parts)
            write_json(self.simplification_path, record)
            return self.state()

    def finish_simplification(self, request):
        with self.lock:
            self.check_revision(request, simplification=True)
            state = self.state()
            record = deepcopy(state["simplification"])
            if record is None:
                raise ValueError("削除提案が未作成または接合面レビュー変更で無効です。")
            record.update(confirmed=True, notes=request["notes"])
            validate_review(record, state["draft"], self.parts, require_complete=True)
            write_json(self.simplification_path, record)
            return self.state()

    def save(self, request):
        with self.lock:
            self.ensure_sources()
            if request["revision"] != self.revision():
                raise ValueError("別のタブで更新されました。再読込してから保存してください。")
            state = self.state()
            draft = deepcopy(state["draft"])
            item = request["item"]
            index = item["candidate_id"]
            if type(index) is not int or not 1 <= index <= len(draft["reviews"]):
                raise ValueError("Unknown candidate ID")
            validate_decision(item, self.parts)
            measurement = measure_pair(item["faces"], self.parts)
            if item["decision"] == "accepted" and measurement is None:
                raise ValueError("対応外または重なりのない面ペアは採用できません。")
            if item["decision"] == "accepted" and any(list(ref) in self.unrendered_faces for ref in item["faces"]):
                raise ValueError("描画できない面が含まれています。別の表示手段で確認してください。")
            notes = request["simplification_notes"]
            if not isinstance(notes, str):
                raise ValueError("Invalid simplification notes")
            draft["reviews"][index-1] = {"candidate_id": index, "faces": item["faces"],
                "decision": item["decision"], "condition": item["condition"], "measurement": measurement}
            draft["simplification_notes"] = notes
            write_json(self.review_path, draft)
            return self.state()


def handler_for(session, scene):
    from ocp_viewer import __file__ as viewer_module
    assets = (Path(viewer_module).parent / "server" / "static").resolve()
    here = Path(__file__).resolve().parent
    scene_bytes = json.dumps(scene, separators=(",", ":")).encode()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, value, mime="application/json; charset=utf-8"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; worker-src 'self' blob:")
            self.end_headers()
            self.wfile.write(body)

        def trusted(self):
            host = f"127.0.0.1:{self.server.server_port}"
            return self.headers.get("Host") == host and self.headers.get("Origin", "http://"+host) == "http://"+host

        def do_GET(self):
            if not self.trusted():
                self.reply(403, {"error": "Local origin required"})
                return
            path = urlsplit(self.path).path
            try:
                if path == "/api/state":
                    with session.lock:
                        self.reply(200, session.state())
                elif path == "/api/scene":
                    self.reply(200, scene_bytes)
                elif path in ("/", "/review_contacts_web.js"):
                    name = "review_contacts_web.html" if path == "/" else path[1:]
                    self.reply(200, (here/name).read_bytes(), "text/html; charset=utf-8" if path == "/" else "text/javascript; charset=utf-8")
                elif path.startswith("/assets/"):
                    asset = (assets/path.removeprefix("/assets/")).resolve()
                    mime = {".css": "text/css", ".js": "text/javascript", ".png": "image/png"}.get(asset.suffix)
                    if not asset.is_relative_to(assets) or not mime or not asset.is_file():
                        self.reply(404, {"error": "Not found"})
                    else:
                        self.reply(200, asset.read_bytes(), mime)
                else:
                    self.reply(404, {"error": "Not found"})
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.reply(409, {"error": str(exc)})

        def do_POST(self):
            if not self.trusted() or self.headers.get("X-B2-Token") != session.token:
                self.reply(403, {"error": "Local review token required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1_000_000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                path = urlsplit(self.path).path
                if path == "/api/save":
                    self.reply(200, session.save(data))
                elif path == "/api/simplification/start":
                    self.reply(200, session.start_simplification(data))
                elif path == "/api/simplification/save":
                    self.reply(200, session.save_simplification(data))
                elif path == "/api/simplification/finish":
                    self.reply(200, session.finish_simplification(data))
                elif path == "/api/measure":
                    with session.lock:
                        session.ensure_sources()
                        self.reply(200, {"measurement": measure_pair(data["faces"], session.parts)})
                else:
                    self.reply(404, {"error": "Not found"})
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                self.reply(409, {"error": str(exc)})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--simplification-review", type=Path,
                        help="Separate face simplification review JSON")
    parser.add_argument("--port", type=int, default=3941)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        session = ReviewSession(args.bundle, args.candidates, args.review, args.simplification_review)
        print("Preparing BREP face display mapping...", flush=True)
        scene = render_scene(session.parts, session.nodes)
        session.unrendered_faces = scene["unrendered_faces"]
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(session, scene)) as server:
            url = f"http://127.0.0.1:{server.server_port}/"
            print(url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.exit(1, f"Web contact review failed: {exc}\n")


if __name__ == "__main__":
    main()
