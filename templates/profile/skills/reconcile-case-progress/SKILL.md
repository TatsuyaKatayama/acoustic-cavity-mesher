---
name: reconcile-case-progress
description: Reconcile case evidence and identify the next admissible CAD task.
---

Run workflows/python/advance_case.py CASE status. Read the relevant dependency
records and base workflow before dispatch. Select one ready task and pass its
record references, applicable role instructions and only the necessary evidence.
Use advance_case.py CASE dispatch TICKET to load the task package.
Save outputs under a distinct attempt or revision path. Record results with
the corresponding ticket, including human decisions only after they occur.
On interruption, request status again and resume the missing task. On changes
to a prior decision or input, reopen the earliest affected task and recompute
readiness. Preserve past results for review.
