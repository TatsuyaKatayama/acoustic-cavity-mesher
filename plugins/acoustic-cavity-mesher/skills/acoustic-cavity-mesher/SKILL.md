---
name: acoustic-cavity-mesher
description: Use the acoustic-cavity-mesher project to inspect STEP or BREP files, run CAD simplification and assembly or cavity checks, measure short edges, and open CAD views in Codex. Use for this project's CAD simplification and validation workflow.
---

Run in the user's CAD Rebuilder checkout. Locate the repository
from the active workspace and verify it contains `docs/cad-workflow.md`
and `SPEC.md`. Run tools from the checkout, since the installed plugin skill
is cached separately. Read the checkout's `AGENTS.md` and the section of
`docs/cad-workflow.md` for the requested operation. Use
`template-builder/.venv/Scripts/python.exe` on Windows. If it is missing, use
the setup section of the root README. Run `tools/workspace.py init` with
that interpreter before reading local role definitions. Run CAD command
scripts from `tools/` with the repository root as the working directory.

- Extract part placements and independently check them against the source STEP.
- Propose simplifications and contact rules. Use the combined part review
  workflow and keep proposals distinct from recorded human approvals.
- Write per-placement CadQuery source and reproducible construction history. Read the
  worker role in `local/profile/agents/b3-worker/AGENT.md`.
- Independently check the candidate using the checker role in
  `local/profile/agents/b4-checker/AGENT.md`. Record both fit and
  simplification judgments, measurements and any separate human decisions.
- Verify placement, contacts and interference before subtracting any shapes.
  For cavity extraction, document the envelope, port boundaries, probes and
  short-edge criteria. Record the source boundaries of suspect edges. After
  repairs, repeat extraction and verify against the same criteria.

Use `compare_cad.py` to compare the same world-coordinate views,
`measure_features.py` for BREP minima, `view_short_edges.py` for edge and
incident-face highlighting, and `check_same_domain.py` to test fusion and
cross-part face unification separately. Web viewers use loopback on the PC
running the project. When the user asks for a capture, show the actual viewer
and attach its screenshot.

Keep input CAD, approval records and generated results in Git-ignored case
directories. Archive new attempts separately. Proceed only to the requested
operation and stop at any required human decision.
