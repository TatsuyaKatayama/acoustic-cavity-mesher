---
name: rebuild-parametric-solid
description: Construct a dimension-driven simplified solid with reproducible history.
---

Read the assigned task and reviewed face sets. Build a new solid with reproducible
CadQuery history and record dimensional references. Use retained face regions,
contacts, openings and declared tolerances as constraints. Minimize unnecessary
faces, edges, steps and features. Extend retained surfaces or use draft where
needed. Explain remaining steps. Dimensions must not rely on omitted-only geometry.
Write one part-specific `.py` in the ignored placement directory. Define
`build_history()` as a generator yielding `(step_id, model)` after each solid
construction step, in world coordinates and millimetres. Use CadQuery
workplanes or shapes and explicit dimensions and datums in the script. Keep
file and network I/O, process execution and detailed CAD imports out of the
script. Review the code before running it. Pair it with a schema 1 construction
record whose operations each contain `id`, `source_faces` and `rationale`.
Record explicit whole-part tolerances in `policy_checks`. Use
`b3_build.py --python-source` to save the code, BREP history and artifact.
