"""B3 worker: rebuild one assigned part from a dimensional CadQuery plan."""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite, sqrt
from pathlib import Path
from tempfile import TemporaryDirectory

import cadquery as cq

from b1_step import brep_bytes


def digest(data):
    return sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8")


def _vector(value):
    if not isinstance(value, list) or len(value) != 3 or any(type(v) not in (int, float) or not isfinite(v) for v in value):
        raise ValueError("Frame vectors must have three finite numeric components")
    return value


def validate_plan(task, plan):
    if task.get("schema_version") != 1 or task.get("length_unit") != "mm" or not isinstance(task.get("part_id"), str):
        raise ValueError("Expected a B3 task in mm with a part_id")
    allowed = {tuple(ref) for group in task["face_sets"] if group["decision"] in ("keep", "simplify") for ref in group["faces"]}
    omitted = {tuple(ref) for group in task["face_sets"] if group["decision"] == "omit" for ref in group["faces"]}
    if allowed & omitted:
        raise ValueError("Task contains conflicting face ownership")
    if not isinstance(plan, dict) or not {"schema_version", "operations"} <= set(plan) or set(plan) - {"schema_version", "operations", "policy_checks"} or plan["schema_version"] != 1 or not isinstance(plan["operations"], list) or not plan["operations"]:
        raise ValueError("Expected a nonempty schema 1 operation plan")
    if not isinstance(plan.get('policy_checks', []), list):
        raise ValueError('policy_checks must be a list')
    identifiers = set()
    for index, op in enumerate(plan["operations"]):
        if not isinstance(op, dict) or set(op) != {"id", "operation", "combine", "parameters", "frame", "source_faces", "rationale"}:
            raise ValueError("Operation requires id, primitive, combine, parameters, frame, source_faces and rationale")
        identifier = op["id"]
        if not isinstance(identifier, str) or not identifier or len(identifier) > 100 or identifier in identifiers:
            raise ValueError("Operation IDs must be unique nonempty strings of at most 100 characters")
        identifiers.add(identifier)
        if op["operation"] not in ("box", "cylinder"):
            raise ValueError("Only box and cylinder primitives are supported in the initial B3 worker")
        if op["combine"] not in (("new",) if index == 0 else ("union", "cut")):
            raise ValueError("The first primitive must be new; later primitives must union or cut")
        keys = {"length_mm", "width_mm", "height_mm"} if op["operation"] == "box" else {"radius_mm", "height_mm"}
        params = op["parameters"]
        if not isinstance(params, dict) or set(params) != keys or any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in params.values()):
            raise ValueError("Primitive dimensions must be finite positive millimetres")
        frame = op["frame"]
        if not isinstance(frame, dict) or set(frame) != {"origin_mm", "x_direction", "normal"}:
            raise ValueError("Each operation requires an explicit world-coordinate frame")
        _vector(frame["origin_mm"])
        x, normal = _vector(frame["x_direction"]), _vector(frame["normal"])
        nx, nn = sqrt(sum(v*v for v in x)), sqrt(sum(v*v for v in normal))
        if nx < 1e-12 or nn < 1e-12 or abs(sum(a*b for a, b in zip(x, normal))/(nx*nn)) > 1e-10:
            raise ValueError("Frame x_direction and normal must be nonzero and perpendicular")
        if not isinstance(op["source_faces"], list):
            raise ValueError("source_faces must be an explicit list")
        seen = set()
        for ref in op["source_faces"]:
            if not isinstance(ref, list) or len(ref) != 2 or ref[0] != task["part_id"] or type(ref[1]) is not int:
                raise ValueError("Source references must be faces of the assigned part")
            key = tuple(ref)
            if key not in allowed or key in omitted or key in seen:
                raise ValueError("Unknown, omitted, or duplicate source face reference")
            seen.add(key)
        if not isinstance(op["rationale"], str) or not op["rationale"].strip() or len(op["rationale"]) > 4000:
            raise ValueError("Each operation needs a rationale, including any independently supplied dimensions")
    return deepcopy(plan)


def build_history(plan):
    """Build only new primitives; never import or edit a detailed BREP."""
    model = None
    for op in plan["operations"]:
        frame, p = op["frame"], op["parameters"]
        plane = cq.Plane(origin=tuple(frame["origin_mm"]), xDir=tuple(frame["x_direction"]), normal=tuple(frame["normal"]))
        primitive = cq.Workplane(plane)
        if op["operation"] == "box":
            primitive = primitive.box(p["length_mm"], p["width_mm"], p["height_mm"], centered=(True, True, False))
        else:
            primitive = primitive.circle(p["radius_mm"]).extrude(p["height_mm"])
        model = primitive if model is None else model.union(primitive) if op["combine"] == "union" else model.cut(primitive)
        shape = model.val()
        if not shape.isValid() or len(shape.Solids()) != 1 or shape.Volume() <= 0:
            raise ValueError("Every operation must produce one valid positive-volume solid: "+op["id"])
        yield op, model


def generated_code(plan):
    # Reuse only the dimensional generator, not a source model or arbitrary code.
    import inspect
    return ("\"\"\"B3 dimensional construction history; no detailed CAD import.\"\"\"\n"
            "import cadquery as cq\n\nPLAN = "+repr(plan)+"\n\n"+inspect.getsource(build_history)+
            "\n\ndef build():\n    return list(build_history(PLAN))[-1][1]\n\n"
            "if __name__ == '__main__':\n    result = build()\n").encode("utf-8")


def build_task(task, plan, output):
    """Write a reproducible worker artifact. Checking is a separate command."""
    from b3_task import validate_task
    validate_task(task)
    output = Path(output)
    plan = validate_plan(task, plan)
    if output.exists():
        raise ValueError("Output already exists: "+str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as temporary:
        work = Path(temporary)/"artifact"
        work.mkdir()
        history = []
        for index, (operation, model) in enumerate(build_history(plan), 1):
            data = brep_bytes(model.val().wrapped)
            name = f"history-{index:03d}.brep"
            (work/name).write_bytes(data)
            history.append({"operation_id": operation["id"], "geometry": name, "sha256": digest(data),
                            "volume_mm3": model.val().Volume(), "source_faces": operation["source_faces"]})
        final = brep_bytes(model.val().wrapped)
        (work/"final.brep").write_bytes(final)
        code, task_data, plan_data = generated_code(plan), json_bytes(task), json_bytes(plan)
        for name, data in (("generated.py", code), ("task.json", task_data), ("plan.json", plan_data)):
            (work/name).write_bytes(data)
        artifact = {"schema_version": 1, "stage": "B3", "status": "awaiting_check", "length_unit": "mm",
                    "coordinate_frame": "world", "part_id": task["part_id"],
                    "manifest_sha256": task["manifest_sha256"], "handoff_sha256": task["handoff_sha256"],
                    "task_sha256": digest(task_data), "plan_sha256": digest(plan_data),
                    "roles": task['roles'], "worker": task['roles']['worker'],
                    "code": "generated.py", "code_sha256": digest(code), "geometry": "final.brep",
                    "geometry_sha256": digest(final), "history": history,
                    "contact_constraints": task.get("contact_constraints", []),
                    "note": "B3 worker output only; independent check and B4/B5 validation remain required"}
        (work/"artifact.json").write_bytes(json_bytes(artifact))
        work.rename(output)
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        from b3_task import load_task
        artifact = build_task(load_task(args.task), json.loads(args.plan.read_text(encoding="utf-8")), args.output)
        print(json.dumps({"status": artifact["status"], "part_id": artifact["part_id"], "output": str(args.output)}))
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        parser.exit(1, f"B3 build failed: {exc}\n")


if __name__ == "__main__":
    main()
