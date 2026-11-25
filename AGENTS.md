# Repository agent instructions

Keep detailed CAD, review data, and generated artifacts outside version control.
Use the project virtual environment at `template-builder/.venv/Scripts/python.exe`.

For B4, assign a checker separate from the B3 author. Follow the repository's
[B4 checker role](template-builder/agents/b4-checker/AGENT.md), which declares its skills.
Preserve the input geometry and record the two B4 judgments separately.

For B2, present simplification proposals before asking the user to classify faces.
Include per-part keep/simplify/omit sets, face references, reasons, and unresolved
questions. Protect contact candidates and required openings. Keep proposals
separate from saved decisions and human approval; do not advance to B3 until
the B2 decisions are resolved. Ask the user about ambiguous cases, not every face.
Provide assembly-wide or per-part batch adoption of the displayed proposal;
preserve saved decisions and keep final confirmation separate. Do not require
one approval per CAD face.

Use the Codex chat as the primary B2 policy/approval interface. Translate the
user's natural-language instructions into face sets, preserve the instruction
and its interpretation, and ask only about ambiguity. The CAD sidebar is for
part selection and visual inspection, not logs, long proposal lists, or manual
face/set approval forms. Keep detailed reports in artifacts and the chat.
Retain face-ID inspection: clicking a CAD face must reveal its part/placement
and B1 BREP face reference in a compact, replace-in-place display with copy support.

Accumulate per-part B2 policies with b2_part_rules.py in the Git-ignored
template-builder/b1-output/part-rules store. Preserve the user's original text,
semantic interpretation, applicability, unresolved criteria, and revision history.
Consult matching rules before proposing simplification. Accumulate and load
semantic rules by normalized part name by default, including changed geometry;
append instruction history and merge interpretations by semantic target.
An exact-geometry restriction or cross-name family can be requested. Face IDs
from another geometry are not reusable. A policy draft or approval is distinct
from approval of a case's B2 face sets. Do not claim that a natural-language rule
was geometrically applied when feature mapping or tolerances remain unresolved.
Archive both contact and simplification judgments before contact edits;
invalidate the current simplification assessment when contact references or
conditions change. Accept contact corrections through chat.

B2 is a single combined, per-placement confirmation of contact and
simplification proposals. Show the proposal colors immediately and offer a
left-side "approve and next part" action. Corrections, including contact
corrections, are given in chat; do not show a separate contact-edit button or
two sequential review stages. Keep Face ID inspection. Approval must bind the
displayed proposal revision; changed conditions require reconfirmation.
