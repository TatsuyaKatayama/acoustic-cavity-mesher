---
name: b4-check
description: Evaluate fit reachability and simplification suitability for a B3 CAD candidate.
---

Check only. Read the B1 geometry, B2 constraints and the B3 candidate in the same frame.
Preserve the inputs. Save a separate report naming the candidate and evidence.

1. Check geometry validity, retained surfaces, contact references and measured fit.
   Distinguish whether constraints are met from whether parameter adjustment has
   reached the best available fit. State missing evidence explicitly.
2. Determine added space and removed space in this order:
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
3. Report both volumes and their sum divided by the original detailed part volume.
   The numerical criterion is at most 5%. Keep net volume change separate.
4. Finish with a same-view and relevant section comparison of the unchanged inputs.
   Inspect retained boundaries, functional openings, and intended simplifications.
   Report what is visible and what remains uncertain. Record a separate visual
   judgment. A pass on the numerical criterion alone does not complete B4.
   Report the two B4 judgments and stop before B5.

Record the selected method and the attempts that failed. Sum per-solid volumes
rather than relying on a single compound measurement when they disagree.
Report the 5% numerical judgment and the visual judgment separately. If only
some sections could be inspected, identify them and report the remaining scope.

Record B4 technical status separately from human review. Mark fit OK when its
geometric constraints are met. Report optimization evidence if available.
Unevaluated optimization is informational. A B4 technical OK leaves human
review pending and does not authorize registration.
