"""Parametric mounting block rebuilt from dimensions in millimeters."""

from math import isfinite

import cadquery as cq

TEMPLATE_ID = "mounting_block"
TEMPLATE_VERSION = 1
PARAMETERS = ("length", "width", "height", "hole_diameter", "hole_x", "hole_y")
NAMED_FACES = {"mounting_plane": "<Z"}


def dimensions(values):
    if not isinstance(values, dict) or set(values) != set(PARAMETERS):
        raise ValueError(f"Expected exactly these parameters in mm: {', '.join(PARAMETERS)}")
    if any(type(value) not in (float, int) or not isfinite(value) for value in values.values()):
        raise ValueError("Parameters must be finite numbers")
    length, width, height, diameter, x, y = (values[key] for key in PARAMETERS)
    if min(length, width, height, diameter) <= 0:
        raise ValueError("Block dimensions and hole diameter must be positive")
    if abs(x) + diameter / 2 >= length / 2 or abs(y) + diameter / 2 >= width / 2:
        raise ValueError("The through-hole must have clearance to every side of the block")
    return length, width, height, diameter, x, y


def build_history(values):
    """Yield each solid in order. Stop after any operation to inspect that state."""
    length, width, height, diameter, x, y = dimensions(values)
    body = cq.Workplane("XY").box(length, width, height, centered=(True, True, False))
    yield "solid_extrusion", body
    final = body.faces(">Z").workplane(centerOption="CenterOfBoundBox").center(x, y).hole(diameter)
    yield "required_through_hole", final


def named_faces(model):
    """Resolve semantic names against the regenerated solid."""
    result = {}
    for name, selector in NAMED_FACES.items():
        matches = model.faces(selector).vals()
        if len(matches) != 1:
            raise ValueError(f"Named face {name}: expected one face, found {len(matches)}")
        result[name] = matches[0].wrapped
    return result
