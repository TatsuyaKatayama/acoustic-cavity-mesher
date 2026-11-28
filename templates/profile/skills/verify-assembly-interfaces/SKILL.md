---
name: verify-assembly-interfaces
description: Inspect rebuilt assembly contacts, openings and interference.
---

Use tools/b5_check_rebuild.py for a B3 artifact or tools/check_reassembly.py
for the fit-based path. Compare overlap, gaps and interference against the
approved criteria. Check openings by examining the assembled geometry and, when
space evidence is available, the relevant probes in tools/check_trial_space.py.
Distinguish intended fill from unexpected interference and flag unresolved cases.
