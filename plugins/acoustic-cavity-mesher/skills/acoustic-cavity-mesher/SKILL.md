---
name: acoustic-cavity-mesher
description: Use the acoustic-cavity-mesher project to inspect STEP or BREP files, run CAD simplification and assembly or cavity checks, measure short edges, and open CAD views in Codex. Use for this project's B1–B5 workflow and CAD tooling.
---

Run in the user's checkout of acoustic-cavity-mesher. Locate the repository
from the active workspace and verify it contains `template-builder/README.md`
and `SPEC.md`. Run tools from the checkout, since the installed plugin skill
is cached separately. Read the checkout's `AGENTS.md` and the section of
`template-builder/README.md` for the requested stage. Use
`template-builder/.venv/Scripts/python.exe` on Windows. If it is missing, use
the setup section of the root README.

- B1 extracts placements and checks the original STEP independently.
- B2 proposes simplifications and contact rules. Use the combined part review
  workflow and keep proposals distinct from recorded human approvals.
- B3 writes per-placement CadQuery source and reproducible history. Read the
  worker role in `template-builder/agents/b3-worker/AGENT.md`.
- B4 independently checks the candidate using the checker role in
  `template-builder/agents/b4-checker/AGENT.md`. Record both fit and
  simplification judgments, measurements and any separate human decisions.
- B5.1 verifies placement, contacts and interference before subtracting any
  shapes. For B5.2 document the envelope, port boundaries, probes and
  short-edge criteria. Record the source boundaries of suspect edges. After
  B5.3 repairs, use B5.2 again to verify the new cavity against the same criteria.

Use `compare_cad.py` to compare the same world-coordinate views,
`measure_features.py` for BREP minima, `view_short_edges.py` for edge and
incident-face highlighting, and `check_same_domain.py` to test fusion and
cross-part face unification separately. Web viewers use loopback on the PC
running the project. When the user asks for a capture, show the actual viewer
and attach its screenshot.

Keep input CAD, approval records and generated results in Git-ignored case
directories. Archive new attempts separately. Proceed only to the requested
stage and stop at any required human decision.
