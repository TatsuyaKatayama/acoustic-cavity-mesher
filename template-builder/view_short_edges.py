"""Report short BREP edges and show their incident faces in a CAD comparison."""
import argparse
from functools import lru_cache
from html import escape
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import cadquery as cq
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopoDS import TopoDS

from b3_check import indexed, read_brep
from compare_cad import handler_for
from measure_features import measure_features


def inspect(shape, limit):
    features = measure_features(shape, min_edge_length_mm=limit, inclusive=True)
    hits = {hit['index']: hit for hit in features['below_threshold']}
    edges = indexed(shape, TopAbs_EDGE)
    faces = indexed(shape, TopAbs_FACE)
    for hit in hits.values():
        hit['face_ids'] = []
    for index in range(1, faces.Extent()+1):
        local = indexed(faces.FindKey(index), TopAbs_EDGE)
        for j in range(1, local.Extent()+1):
            hit = hits.get(edges.FindIndex(local.FindKey(j)))
            if hit is not None:
                hit['face_ids'].append(index)
    return {
        'edge_limit_mm_inclusive': limit,
        'minimum_edge': features['edges']['minimum'],
        'short_edges': list(hits.values()),
        'highlight_face_ids': sorted({face for hit in hits.values() for face in hit['face_ids']}),
    }


def viewer_models(shape, report):
    from ocp_viewer import Camera
    from ocp_viewer_core.offline import _convert

    source = cq.Shape.cast(shape)
    scene = cq.Assembly(name='Highlighted geometry')
    faces = indexed(shape, TopAbs_FACE)
    flagged = set(report['highlight_face_ids'])
    for name, group, color in (
        ('Other faces', [i for i in range(1, faces.Extent()+1) if i not in flagged], cq.Color(.67,.71,.76)),
        ('Incident faces', sorted(flagged), cq.Color(1,.43,.08)),
    ):
        if group:
            compound = cq.Compound.makeCompound([cq.Shape.cast(faces.FindKey(i)) for i in group])
            scene.add(compound, name=name, color=color)
    edges = indexed(shape, TopAbs_EDGE)
    if report['short_edges']:
        compound = cq.Compound.makeCompound([
            cq.Shape.cast(TopoDS.Edge_s(edges.FindKey(hit['index']))) for hit in report['short_edges']])
        scene.add(compound, name='Short edges', color=cq.Color(.9,.05,.1))
    payload = [_convert(model, reset_camera=Camera.RESET, ortho=True, control='trackball')[0]
               for model in (source, scene)]
    payload[1]['data']['shapes']['bb'] = payload[0]['data']['shapes']['bb']
    return json.dumps(payload, separators=(',', ':')).encode('utf-8')


def inventory_handler(entries):
    base = handler_for(b'')
    template = Path(__file__).with_name('compare_cad.html').read_text(encoding='utf-8')
    template = (template.replace('>詳細形状<', '>簡略形状<').replace('>簡易形状<', '>短辺を含む面<')
                .replace('fetch("/models.json")', 'fetch("/models.json" + location.search)'))

    @lru_cache(maxsize=4)
    def models(index):
        entry = entries[index]
        return viewer_models(read_brep(entry['brep']), entry)

    class Handler(base):
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path not in ('/', '/models.json'):
                return super().do_GET()
            try:
                index = int(parse_qs(url.query).get('part', ['0'])[0])
                if not 0 <= index < len(entries):
                    raise ValueError
            except ValueError:
                return self.send_error(404)
            if url.path == '/models.json':
                data, mime = models(index), 'application/json'
            else:
                options = ''.join(
                    f'<option value="{i}"{" selected" if i == index else ""}>{escape(e["part"])} '
                    f'({escape(e["id"])}) · {len(e["short_edges"])}辺</option>'
                    for i,e in enumerate(entries))
                selector = ('<form action="/" style="margin:0 12px 0 auto">'
                            '<label>部品 <select name="part" onchange="this.form.submit()">'
                            + options + '</select></label> '
                            '<span>橙：該当面　赤：該当エッジ</span></form>')
                data = template.replace('</h1>', '</h1>'+selector, 1).encode('utf-8')
                mime = 'text/html; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('brep', type=Path, nargs='?')
    source.add_argument('--inventory', type=Path, help='JSON array of placement inspection results')
    parser.add_argument('--edge-limit-mm', type=float)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if args.inventory:
        if args.port is None or args.edge_limit_mm is not None or args.report:
            parser.error('--inventory requires --port and uses the limits and reports in the inventory')
        entries = json.loads(args.inventory.read_text(encoding='utf-8-sig'))
    else:
        if args.edge_limit_mm is None:
            parser.error('BREP inspection requires --edge-limit-mm')
        shape = read_brep(args.brep)
        report = inspect(shape, args.edge_limit_mm)
        if args.report:
            with args.report.open('x', encoding='utf-8') as stream:
                json.dump(report, stream, indent=2)
        if args.port is None:
            print(json.dumps(report, indent=2))
            return
        entries = [dict(part=args.brep.stem, id='BREP', brep=str(args.brep), **report)]
    with ThreadingHTTPServer(('127.0.0.1', args.port), inventory_handler(entries)) as server:
        print(f'http://127.0.0.1:{server.server_port}/', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
