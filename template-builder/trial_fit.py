"""Fit the B3 mounting block and export it in assembly coordinates."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from OCP.gp import gp_Trsf
from OCP.TopLoc import TopLoc_Location

from b1_step import brep_bytes, matrix
from b2_faces import load_parts
from b4_geometry import fitting_frame, indexed_faces, measurements, template_source, to_local
import mounting_block


def fit(bundle_digest, parts, template_path, world_x, output):
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    template, template_digest, source, face = template_source(template_path, bundle_digest, parts)
    frame = fitting_frame(source, face, world_x)
    parameters = measurements(to_local(source, frame))
    for operation, model in mounting_block.build_history(parameters):
        if not model.val().isValid() or len(model.val().Solids()) != 1:
            raise ValueError(f"Invalid generated solid after {operation}")

    world_to_template = gp_Trsf()
    world_to_template.SetTransformation(frame)
    location = TopLoc_Location(world_to_template.Inverted())
    local_shape = model.val().wrapped
    face_index = indexed_faces(local_shape).FindIndex(mounting_block.named_faces(model)["mounting_plane"])
    if face_index == 0:
        raise ValueError("Generated mounting_plane was not found")
    geometry = brep_bytes(local_shape.Moved(location))
    record = {
        "schema_version": 1,
        "length_unit": "mm",
        "manifest_sha256": bundle_digest,
        "template_sha256": template_digest,
        "source_part_id": template["source_part_id"],
        "world_x_direction": world_x,
        "template_to_world": matrix(location),
        "parameters": parameters,
        "named_faces": {"mounting_plane": face_index},
        "geometry_sha256": sha256(geometry).hexdigest(),
        "contact_constraints": template["contact_constraints"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        result = Path(temp) / "fit"
        result.mkdir()
        (result / "fitted.brep").write_bytes(geometry)
        (result / "fit.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        result.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="B1 extraction directory")
    parser.add_argument("template", type=Path, help="B3 template build directory")
    parser.add_argument("output", type=Path, help="New B4 fit directory")
    parser.add_argument("--world-x", type=float, nargs=3, required=True, metavar=("X", "Y", "Z"),
                        help="Template +X direction in assembly coordinates")
    args = parser.parse_args()
    try:
        digest, parts = load_parts(args.bundle)
        fit(digest, parts, args.template, args.world_x, args.output)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Trial fit failed: {error}\n")


if __name__ == "__main__":
    main()
