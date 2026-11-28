---
name: build-and-verify-space-cad
description: Build the analysis space and verify its volume and connectivity.
---

The author records the envelope, fill, any temporary caps and the intended
regions and probes. Use tools/b5_build_rebuild_space.py for a rebuilt-part
trial, or tools/build_trial_space.py for the fit-based workflow.
The independent checker uses the resulting diagnostics and, for the fit-based
outputs, tools/check_trial_space.py. Check solid validity, region volumes,
expected connectivity and unintended leaks or isolated regions. Record the
configuration and probe findings. Keep temporary caps explicit in the evidence.
