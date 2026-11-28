---
name: define-and-trial-fit
description: Define geometry references and parameters and try fitting a rebuilt part.
---

From the approved task, identify datums, stable measurement references, adjustable
dimensions, ranges and contact constraints. Record the measured values and rationale.
Use tools/trial_fit.py for its supported mounting-block template. For other
parts, derive dimensions from their own geometry and use the existing CadQuery
rebuild path via tools/b3_build.py. Record which parameters were tried and
which constraints remain unresolved for independent evaluation.
