---
name: measure-volume-change
description: Measure added and removed space with documented fallback methods.
---

Determine added space and removed space in this order:
   - Method 1: compute detailed minus simplified and simplified minus detailed.
     Sum all valid solid components. Verify that added minus removed matches the
     original volume minus simplified volume within a stated measurement tolerance.
   - Method 2: if method 1 cannot supply both reliable volumes, compute the valid
     common solid volume and subtract it from each original operand volume.
     Check nonnegative results and compare any valid method 1 partial measurement.
     Record discrepancies. The balance is an identity for this method and is not
     independent validation.
   - Method 3: if method 2 cannot supply a usable estimate, scale a separate
     simplified comparison copy by 1.00001 about a recorded part datum. Repeat
     direct differences with that copy, validate the results and check balance
     against the scaled volume. Mark the result approximate and record the scale
     and datum. Preserve any failures and keep unresolved results for review.

Report both volumes and their sum divided by the original detailed part volume.
Keep net volume change separate.

Record the selected method and the attempts that failed. Sum per-solid volumes
rather than relying on a single compound measurement when they disagree.
