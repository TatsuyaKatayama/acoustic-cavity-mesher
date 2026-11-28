---
name: trace-and-repair-short-edges
description: Find the source of short edges and recheck the space after a repair.
---

Use tools/measure_features.py and tools/view_short_edges.py to locate
short edges and inspect their neighboring faces. Follow available Boolean history
to their source faces and use boundary proximity as supporting evidence.
If provenance is unavailable, record that limitation. The ALLAssy tracing
and repair scripts illustrate case-specific use of topology history.
The author saves each repair as a separate candidate. The independent checker
repeats the space evaluation under the same conditions and compares validity,
short edges, volume, connectivity and required openings. Recheck assembly
interfaces if the repair affects placement or contacts.
