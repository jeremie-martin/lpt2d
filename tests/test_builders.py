from __future__ import annotations

import math

from anim.builders import thick_arc
from anim.types import Material, Polygon


def _polygon_area2(vertices: list[list[float]]) -> float:
    area2 = 0.0
    for i, a in enumerate(vertices):
        b = vertices[(i + 1) % len(vertices)]
        area2 += a[0] * b[1] - b[0] * a[1]
    return area2


def test_thick_arc_returns_clockwise_annular_sector_polygon():
    shapes = thick_arc(
        center=(1.0, -0.5),
        radius=2.0,
        thickness=0.4,
        angle_start=0.25,
        sweep=1.5,
        material=Material(transmission=1.0, ior=1.5),
    )

    assert len(shapes) == 1
    shape = shapes[0]
    assert isinstance(shape, Polygon)
    assert len(shape.vertices) >= 24

    radii = [math.hypot(x - 1.0, y + 0.5) for x, y in shape.vertices]
    assert math.isclose(min(radii), 1.8, rel_tol=1e-6, abs_tol=1e-6)
    assert math.isclose(max(radii), 2.2, rel_tol=1e-6, abs_tol=1e-6)
    assert _polygon_area2(shape.vertices) < 0.0
