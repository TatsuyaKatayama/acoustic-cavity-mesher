---
name: extract-assembly-placements
description: Extract STEP parts and placements and organize available dimensional input.
---

Run tools/extract_assembly.py with the source STEP and a new output directory.
Preserve the source and inspect assembly.json for units, placement IDs and transforms.
If dimensional inputs exist, record their units and source and associate them with
the corresponding placements. Flag missing or ambiguous dimensions.
Pass the source and extraction bundle to the independent extraction checker.
