"""Serve two synchronized OCP CAD views on the local machine."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit
import webbrowser

from view_cad import load_model
from viewer_licenses import viewer_licenses


def render_data(left, right):
    # Core 1.2 ships this offline converter but has no public equivalent.
    from ocp_viewer import Camera
    from ocp_viewer_core.offline import _convert

    payloads = [
        _convert(load_model(path), reset_camera=Camera.RESET, ortho=True, control="trackball")[0]
        for path in (left, right)
    ]
    shapes = [payload["data"]["shapes"] for payload in payloads]
    shared_bounds = {
        f"{axis}{end}": combine(shape["bb"][f"{axis}{end}"] for shape in shapes)
        for axis in "xyz"
        for end, combine in (("min", min), ("max", max))
    }
    for shape in shapes:
        shape["bb"] = shared_bounds
    return json.dumps(payloads, separators=(",", ":")).encode("utf-8")


def handler_for(models):
    from ocp_viewer import __file__ as viewer_module

    assets = (Path(viewer_module).parent / "server" / "static").resolve()
    here = Path(__file__).resolve().parent
    pages = {
        "/": ("text/html; charset=utf-8", (here / "compare_cad.html").read_bytes()),
        "/models.json": ("application/json", models),
        "/viewer-licenses": ("text/plain; charset=utf-8", viewer_licenses()),
    }
    mime_types = {".css": "text/css", ".js": "text/javascript", ".png": "image/png"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            response = pages.get(path)
            if response is None and path.startswith("/assets/"):
                asset = (assets / path.removeprefix("/assets/")).resolve()
                mime = mime_types.get(asset.suffix)
                if asset.is_relative_to(assets) and mime and asset.is_file():
                    response = mime, asset.read_bytes()
            if response is None:
                self.send_error(404)
                return
            mime, body = response
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("detailed", type=Path)
    parser.add_argument("simplified", type=Path)
    parser.add_argument("--port", type=int, default=3940)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        handler = handler_for(render_data(args.detailed, args.simplified))
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            url = f"http://127.0.0.1:{server.server_port}/"
            print(url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(1, f"CAD comparison failed: {error}\n")


if __name__ == "__main__":
    main()
