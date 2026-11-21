"""Check a B1 extraction against a fresh read of its source STEP."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from b1_step import read_assembly


def check(bundle, expected, definitions):
    actual = json.loads((bundle / "assembly.json").read_text(encoding="utf-8"))
    if not isinstance(actual, dict) or not isinstance(actual.get("nodes"), list):
        raise ValueError("Invalid assembly manifest")
    issues = []
    for field in ("schema_version", "source_sha256", "length_unit"):
        if actual.get(field) != expected[field]:
            issues.append({"code": "manifest_field_mismatch", "field": field})
    remaining = {node["id"]: node for node in expected["nodes"]}
    seen = set()
    for node in actual["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            issues.append({"code": "invalid_node"})
            continue
        node_id = node["id"]
        if node_id in seen:
            issues.append({"code": "duplicate_node", "id": node_id})
            continue
        seen.add(node_id)
        reference = remaining.pop(node_id, None)
        if reference is None:
            issues.append({"code": "unexpected_node", "id": node_id})
            continue
        for field, value in reference.items():
            if node.get(field) != value:
                issues.append({"code": "node_field_mismatch", "id": node_id, "field": field})
    for node_id in remaining:
        issues.append({"code": "missing_node", "id": node_id})
    for digest in definitions:
        path = bundle / "parts" / f"{digest}.brep"
        if not path.is_file():
            issues.append({"code": "missing_geometry", "file": path.name})
        elif sha256(path.read_bytes()).hexdigest() != digest:
            issues.append({"code": "geometry_mismatch", "file": path.name})
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        expected, definitions = read_assembly(args.source)
        issues = check(args.bundle, expected, definitions)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "error", "message": str(error)}, ensure_ascii=True))
        return 1
    print(json.dumps({"status": "ng" if issues else "ok", "issues": issues}, indent=2))
    return 2 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
