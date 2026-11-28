---
name: apply-simplification-instructions
description: Translate user instructions into a revised placement proposal.
---

Look up matching reusable policies with tools/b2_part_rules.py, then prepare
the placement proposal with tools/b2_propose_part.py. Preserve the original
instruction and interpretation, and resolve semantic features on the current
geometry. Ask in chat about ambiguous mappings or tolerances. Before contact
changes, archive both judgments and invalidate the simplification assessment.
Use the integrated review backed by tools/b2_confirm.py to record confirmation
of the displayed revision after the user adopts the proposal.
