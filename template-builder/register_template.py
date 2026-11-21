"""Register an immutable B6 template revision with its validation evidence."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from b4_geometry import read_record, template_source
from b5_geometry import load_reassembly
import mounting_block


def load_json_artifact(path):
    data = path.read_bytes()
    return json.loads(data), data


def require_match(record, expected, label):
    mismatches = [key for key, value in expected.items() if record.get(key) != value]
    if mismatches:
        raise ValueError(f"{label}: invalid or mismatched {', '.join(mismatches)}")


def validation_evidence(args):
    manifest_sha, parts, fit, fit_sha, _ = load_reassembly(args.bundle, args.fit)
    template, template_sha, _, _ = template_source(args.template, manifest_sha, parts)
    evidence_paths = {
        "b4-fit-report.json": args.fit_report,
        "b5-contact-report.json": args.contact_report,
        "b5-space-report.json": args.space_report,
        "b5-space-config.json": args.space_config,
    }
    evidence = {name: load_json_artifact(path) for name, path in evidence_paths.items()}
    fit_report, _ = evidence["b4-fit-report.json"]
    contacts, contact_data = evidence["b5-contact-report.json"]
    space_report, _ = evidence["b5-space-report.json"]
    config, config_data = evidence["b5-space-config.json"]
    space, space_sha = read_record(args.space / "space.json")
    geometry_sha = sha256((args.space / "space.brep").read_bytes()).hexdigest()
    config_sha = sha256(config_data).hexdigest()

    require_match(fit, {
        "template_sha256": template_sha,
        "source_part_id": template["source_part_id"],
        "contact_constraints": template["contact_constraints"],
    }, "B4 result")
    require_match(fit_report, {
        "schema_version": 1, "status": "ok", "manifest_sha256": manifest_sha,
        "template_sha256": template_sha, "fit_sha256": fit_sha,
        "source_part_id": fit["source_part_id"],
    }, "B4 report")
    for stage in ("fit", "simplification"):
        require_match(fit_report[stage], {"status": "ok"}, f"B4 {stage} report")
    require_match(contacts, {
        "schema_version": 1, "status": "ok", "manifest_sha256": manifest_sha,
        "fit_sha256": fit_sha, "interferences": [],
    }, "B5 contact report")
    if (
        not contacts["contacts"]
        or any(item["issues"] for item in contacts["contacts"])
        or [item["candidate_id"] for item in contacts["contacts"]]
        != [item["candidate_id"] for item in fit["contact_constraints"]]
    ):
        raise ValueError("B5 report must cover every contact and contain no contact issues")
    require_match(config, {"schema_version": 1, "length_unit": "mm"}, "B5 configuration")
    require_match(space, {
        "schema_version": 1, "length_unit": "mm", "manifest_sha256": manifest_sha,
        "fit_sha256": fit_sha, "contact_report_sha256": sha256(contact_data).hexdigest(),
        "config_sha256": config_sha, "geometry_sha256": geometry_sha,
    }, "B5 space result")
    require_match(space_report, {
        "schema_version": 1, "status": "ok", "space_record_sha256": space_sha,
        "space_sha256": geometry_sha, "config_sha256": config_sha, "issues": [],
    }, "B5 space report")
    if not space_report["component_volumes_cc"]:
        raise ValueError("B5 space report must include at least one air component")

    template_code = (args.template / "mounting_block.py").read_bytes()
    if sha256(template_code).hexdigest() != template["template_code_sha256"]:
        raise ValueError("Template code does not match its B3 record")
    mounting_block.dimensions(fit["parameters"])
    artifacts = {name: data for name, (_, data) in evidence.items()}
    for name, path, digest in (
        ("b3-template.json", args.template / "template.json", template_sha),
        ("b4-fit.json", args.fit / "fit.json", fit_sha),
        ("b5-space.json", args.space / "space.json", space_sha),
    ):
        data = path.read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"Input changed during registration: {name}")
        artifacts[name] = data
    artifacts["mounting_block.py"] = template_code
    return template, fit, artifacts


def register(args):
    if args.version < 1:
        raise ValueError("Registration version must be a positive integer")
    destination = args.registry / mounting_block.TEMPLATE_ID / f"v{args.version}"
    if destination.exists():
        raise ValueError(f"Registration already exists: {destination}")
    template, fit, artifacts = validation_evidence(args)
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "template_id": template["template_id"],
        "registration_version": args.version,
        "template_code_version": template["template_version"],
        "template_code": "mounting_block.py",
        "level": template["level"],
        "length_unit": "mm",
        "named_faces": list(fit["named_faces"]),
        "applicability": {
            "geometry": "Mounting block with one planar mounting surface and one axial through-hole",
            "parameter_constraints": "mounting_block.dimensions",
            "validated_cases": [{
                "source_part_id": fit["source_part_id"],
                "parameters_mm": fit["parameters"],
                "regression_case_ref": args.regression_case,
            }],
        },
        "simplification_guidance": template["simplification_guidance"],
        "feature_policy": template["feature_policy"],
        "artifacts_sha256": {name: sha256(data).hexdigest() for name, data in artifacts.items()},
    }
    with TemporaryDirectory(dir=destination.parent) as temp:
        entry = Path(temp) / "entry"
        entry.mkdir()
        for name, data in artifacts.items():
            (entry / name).write_bytes(data)
        (entry / "registration.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        entry.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("template", type=Path)
    parser.add_argument("fit", type=Path)
    parser.add_argument("space", type=Path)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--fit-report", type=Path, required=True)
    parser.add_argument("--contact-report", type=Path, required=True)
    parser.add_argument("--space-report", type=Path, required=True)
    parser.add_argument("--space-config", type=Path, required=True)
    parser.add_argument("--regression-case", help="Optional ID of the A-side NG case retested by this run")
    args = parser.parse_args()
    try:
        registered = register(args)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        parser.exit(1, f"Template registration failed: {error}\n")
    print(json.dumps({"status": "ok", "registration": str(registered)}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
