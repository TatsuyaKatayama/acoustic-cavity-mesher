"""Subtract the checked assembly and optional exterior fillers from a cylinder."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.TopTools import TopTools_ListOfShape

from b1_step import brep_bytes
from b4_geometry import read_brep, read_record
from b5_geometry import cylinder, load_reassembly, require_solids


def build(bundle, fit_path, contact_path, config_path, output):
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    digest, parts, fit, fit_digest, fitted = load_reassembly(bundle, fit_path)
    contacts, contact_digest = read_record(contact_path)
    if (
        contacts["schema_version"] != 1 or contacts["status"] != "ok"
        or contacts["manifest_sha256"] != digest or contacts["fit_sha256"] != fit_digest
    ):
        raise ValueError("B5 needs a passing contact report for this exact B1 bundle and B4 fit")
    config, config_digest = read_record(config_path)
    envelope = cylinder(config)
    inputs, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    inputs.Append(envelope)
    for part_id, (original, _) in parts.items():
        shape = fitted if part_id == fit["source_part_id"] else original
        require_solids(shape, f"part {part_id}")
        tools.Append(shape)
    fills = []
    for name in config.get("outside_fill_breps", []):
        data = (config_path.parent / name).read_bytes()
        shape = read_brep(data)
        require_solids(shape, name)
        tools.Append(shape)
        fills.append({"file": name, "sha256": sha256(data).hexdigest()})
    cut = BRepAlgoAPI_Cut()
    cut.SetArguments(inputs)
    cut.SetTools(tools)
    cut.Build()
    if not cut.IsDone() or cut.Shape().IsNull():
        raise RuntimeError("Failed to subtract the assembly from the B5 cylinder")
    geometry = brep_bytes(cut.Shape())
    record = {
        "schema_version": 1, "length_unit": "mm",
        "manifest_sha256": digest, "fit_sha256": fit_digest,
        "contact_report_sha256": contact_digest, "config_sha256": config_digest,
        "geometry_sha256": sha256(geometry).hexdigest(), "outside_fill_breps": fills,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temp:
        result = Path(temp) / "space"
        result.mkdir()
        (result / "space.brep").write_bytes(geometry)
        (result / "space.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        result.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("fit", type=Path)
    parser.add_argument("contact_report", type=Path)
    parser.add_argument("config", type=Path)
    parser.add_argument("output", type=Path, help="New cylindrical subtraction output directory")
    args = parser.parse_args()
    try:
        build(args.bundle, args.fit, args.contact_report, args.config, args.output)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Trial space build failed: {error}\n")


if __name__ == "__main__":
    main()
