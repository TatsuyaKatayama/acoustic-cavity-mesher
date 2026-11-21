"""Build a new B3 mounting-block solid and package it for B4."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedMapOfShape

from b1_step import brep_bytes
from b2_faces import load_parts, validate_pair
from b2_review import validate_decision
import mounting_block


def target_contacts(handoff, digest, parts, part_id, mappings):
    if handoff["schema_version"] != 1 or handoff["manifest_sha256"] != digest or handoff["length_unit"] != "mm":
        raise ValueError("Expected a B3 input file that belongs to this B1 bundle and uses mm")
    if part_id not in parts:
        raise ValueError(f"Unknown target part ID: {part_id}")
    requested = {}
    for item in mappings:
        candidate, separator, name = item.partition("=")
        if not separator or not candidate.isdecimal() or name not in mounting_block.NAMED_FACES:
            raise ValueError(f"Expected --map-face CANDIDATE_ID=mounting_plane, got {item}")
        candidate_id = int(candidate)
        if candidate_id in requested:
            raise ValueError(f"Duplicate --map-face for candidate {candidate_id}")
        requested[candidate_id] = name

    contacts = []
    seen = set()
    for constraint in handoff["contact_constraints"]:
        pair = validate_pair(constraint["faces"], parts)
        source = next((face for face in pair if face[0] == part_id), None)
        if source is None:
            continue
        candidate_id = constraint["candidate_id"]
        if type(candidate_id) is not int or candidate_id < 1 or candidate_id in seen:
            raise ValueError(f"Invalid or duplicate candidate ID: {candidate_id}")
        seen.add(candidate_id)
        if candidate_id not in requested:
            raise ValueError(f"Candidate {candidate_id} needs a named face mapping for part {part_id}")
        condition = {key: constraint[key] for key in ("mode", "target_gap_mm", "tolerance_mm")}
        validate_decision({"faces": pair, "decision": "accepted", "condition": condition}, parts)
        detail_face = TopoDS.Face_s(parts[part_id][1].FindKey(source[1]))
        if BRepAdaptor_Surface(detail_face).GetType() != GeomAbs_Plane:
            raise ValueError(f"Candidate {candidate_id}: source face for mounting_plane must be planar")
        contacts.append({
            "candidate_id": candidate_id,
            "detailed_face": source,
            "mate_face": next(face for face in pair if face != source),
            "template_face": requested[candidate_id],
            **condition,
        })
    unused = requested.keys() - seen
    if unused:
        raise ValueError(f"Mapped candidates do not refer to the target part: {sorted(unused)}")
    return contacts


def write_build(output, parameters, digest, input_digest, part_id, contacts, guidance):
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temporary:
        bundle = Path(temporary) / "template"
        bundle.mkdir()
        history = []
        for index, (operation, model) in enumerate(mounting_block.build_history(parameters), 1):
            shape = model.val()
            if not shape.isValid() or len(shape.Solids()) != 1:
                raise ValueError(f"Invalid single solid after {operation}")
            filename = f"{index:02d}-{operation}.brep"
            (bundle / filename).write_bytes(brep_bytes(shape.wrapped))
            history.append({"operation": operation, "geometry": filename})

        index_map = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape.wrapped, TopAbs_FACE, index_map)
        faces = {
            name: index_map.FindIndex(face) for name, face in mounting_block.named_faces(model).items()
        }
        if 0 in faces.values():
            raise ValueError("A named face was not found on the final solid")
        template_code = Path(mounting_block.__file__).read_bytes()
        (bundle / "mounting_block.py").write_bytes(template_code)
        record = {
            "schema_version": 1,
            "template_id": mounting_block.TEMPLATE_ID,
            "template_version": mounting_block.TEMPLATE_VERSION,
            "template_code_sha256": sha256(template_code).hexdigest(),
            "template_code": "mounting_block.py",
            "level": "default",
            "length_unit": "mm",
            "manifest_sha256": digest,
            "b3_input_sha256": input_digest,
            "source_part_id": part_id,
            "parameters": parameters,
            "datum": {"mounting_plane": "XY at z=0", "body_direction": "+Z"},
            "simplification_guidance": guidance,
            "feature_policy": {"required_through_hole": "keep at every diameter in the template domain"},
            "history": history,
            "geometry": history[-1]["geometry"],
            "named_faces": faces,
            "contact_constraints": contacts,
        }
        (bundle / "template.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        bundle.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="B1 extraction directory")
    parser.add_argument("handoff", type=Path, help="B3 input JSON exported from B2")
    parser.add_argument("part_id", help="Target detailed part occurrence")
    parser.add_argument("parameters", type=Path, help="Mounting block dimensions in mm as JSON")
    parser.add_argument("output", type=Path, help="New template build directory")
    parser.add_argument("--map-face", action="append", default=[], metavar="CANDIDATE_ID=NAME")
    args = parser.parse_args()
    try:
        digest, parts = load_parts(args.bundle)
        handoff_bytes = args.handoff.read_bytes()
        handoff = json.loads(handoff_bytes)
        parameters = json.loads(args.parameters.read_text(encoding="utf-8"))
        contacts = target_contacts(handoff, digest, parts, args.part_id, args.map_face)
        write_build(args.output, parameters, digest, sha256(handoff_bytes).hexdigest(),
                    args.part_id, contacts, handoff["simplification_guidance"])
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        parser.exit(1, f"Template build failed: {error}\n")


if __name__ == "__main__":
    main()
