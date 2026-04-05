from __future__ import annotations

import math

import pytest

from anim import mirror_block
from anim.builders import thick_arc
from anim.types import Material, Polygon, Segment


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


def test_mirror_block_returns_clockwise_per_face_segments():
    default = Material(metallic=1.0, transmission=0.0, albedo=0.95)

    shapes = mirror_block(center=(1.0, -2.0), width=4.0, height=2.0, material=default)

    assert [type(shape) for shape in shapes] == [Segment, Segment, Segment, Segment]
    assert [(shape.a, shape.b) for shape in shapes] == [
        ([-1.0, -3.0], [-1.0, -1.0]),
        ([-1.0, -1.0], [3.0, -1.0]),
        ([3.0, -1.0], [3.0, -3.0]),
        ([3.0, -3.0], [-1.0, -3.0]),
    ]
    assert all(shape.material == default for shape in shapes)


def test_mirror_block_applies_per_face_material_overrides():
    default = Material(albedo=0.2)
    top = Material(metallic=1.0, albedo=0.95)
    right = Material(transmission=1.0, ior=1.5)
    bottom = Material(albedo=0.0)
    left = Material(albedo=0.8)

    shapes = mirror_block(
        center=(0.0, 0.0),
        width=2.0,
        height=1.0,
        material=default,
        top=top,
        right=right,
        bottom=bottom,
        left=left,
    )

    assert [shape.material for shape in shapes] == [left, top, right, bottom]


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (0.0, 1.0),
        (-1.0, 1.0),
        (1.0, 0.0),
        (1.0, -1.0),
    ],
)
def test_mirror_block_rejects_non_positive_dimensions(width: float, height: float):
    with pytest.raises(ValueError):
        mirror_block(center=(0.0, 0.0), width=width, height=height, material=Material())
