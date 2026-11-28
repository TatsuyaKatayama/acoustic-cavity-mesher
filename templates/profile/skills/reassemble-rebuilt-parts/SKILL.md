---
name: reassemble-rebuilt-parts
description: Reassemble rebuilt solids in the source placements.
---

Match each candidate to its source placement and coordinate frame. Use the
bundle and candidate inputs accepted by tools/b5_build_rebuild_space.py for a
single replacement in context. For a full assembly, use the ALLAssy pattern:
collect placement-specific world solids without applying their transforms twice,
export the assembly, and read it back to check solid counts and placement bounds.
Retain the source-to-candidate mapping for independent inspection.
