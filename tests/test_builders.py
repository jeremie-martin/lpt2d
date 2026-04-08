from __future__ import annotations

import math
from typing import Any

import pytest

from anim import mirror_block
from anim.builders import biconvex_lens, double_slit, mirror_box, rectangle, regular_polygon, thick_arc, waveguide
from anim.types import Material, Polygon, PolygonJoinMode, Segment


def _polygon_area2(vertices: list[tuple[float, float]]) -> float:
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


def test_thick_arc_supports_smooth_angle_and_end_cap_radii():
    shapes = thick_arc(
        center=(0.0, 0.0),
        radius=1.0,
        thickness=0.2,
        angle_start=0.25,
        sweep=1.75,
        material=Material(transmission=1.0, ior=1.5),
        smooth_angle=1.0,
        end_cap_radii=(0.05, 0.08),
    )

    assert len(shapes) == 1
    shape = shapes[0]
    assert isinstance(shape, Polygon)
    assert shape.smooth_angle == pytest.approx(1.0)
    assert shape.corner_radius == pytest.approx(0.0)

    steps = (len(shape.vertices) - 2) // 2
    expected = [0.0] * len(shape.vertices)
    expected[steps] = 0.05
    expected[steps + 1] = 0.05
    expected[0] = 0.08
    expected[-1] = 0.08
    assert shape.corner_radii == pytest.approx(expected)

    expected_join_modes = [PolygonJoinMode.auto] * len(shape.vertices)
    expected_join_modes[steps] = PolygonJoinMode.sharp
    expected_join_modes[steps + 1] = PolygonJoinMode.sharp
    expected_join_modes[0] = PolygonJoinMode.sharp
    expected_join_modes[-1] = PolygonJoinMode.sharp
    assert list(shape.join_modes) == expected_join_modes

    shape.smooth_angle = 0.0
    assert list(shape.join_modes) == expected_join_modes


@pytest.mark.parametrize(
    ("builder", "kwargs", "expected_vertex_count"),
    [
        (rectangle, {"center": (0.0, 0.0), "width": 2.0, "height": 1.0}, 4),
        (regular_polygon, {"center": (0.0, 0.0), "radius": 1.0, "n": 5}, 5),
    ],
)
def test_polygon_wrappers_forward_corner_radii_join_modes_and_smooth_angle(
    builder: Any,
    kwargs: dict[str, Any],
    expected_vertex_count: int,
):
    join_modes = [PolygonJoinMode.auto] * expected_vertex_count
    if expected_vertex_count > 0:
        join_modes[-1] = PolygonJoinMode.smooth
    shape = builder(
        material=Material(transmission=1.0, ior=1.5),
        corner_radius=0.25,
        corner_radii=[0.0] * expected_vertex_count,
        join_modes=join_modes,
        smooth_angle=1.0,
        **kwargs,
    )

    assert isinstance(shape, Polygon)
    assert len(shape.vertices) == expected_vertex_count
    assert shape.corner_radius == pytest.approx(0.25)
    assert shape.corner_radii == pytest.approx([0.0] * expected_vertex_count)
    assert list(shape.join_modes) == join_modes
    assert shape.smooth_angle == pytest.approx(1.0)


def test_polygon_positional_constructor_keeps_smooth_angle_slot():
    shape = Polygon(
        "poly",
        [(-1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (1.0, -1.0)],
        Material(),
        "",
        0.0,
        [],
        1.25,
    )

    assert shape.smooth_angle == pytest.approx(1.25)
    assert list(shape.join_modes) == []


def test_mirror_block_returns_clockwise_per_face_segments():
    default = Material(metallic=1.0, transmission=0.0, albedo=0.95)

    shapes = mirror_block(center=(1.0, -2.0), width=4.0, height=2.0, material=default)

    assert [type(shape) for shape in shapes] == [Segment, Segment, Segment, Segment]
    assert [(shape.a, shape.b) for shape in shapes] == [
        ((-1.0, -3.0), (-1.0, -1.0)),
        ((-1.0, -1.0), (3.0, -1.0)),
        ((3.0, -1.0), (3.0, -3.0)),
        ((3.0, -3.0), (-1.0, -3.0)),
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


def test_multi_shape_builders_accept_id_prefix():
    material = Material(transmission=1.0, ior=1.5)

    box = mirror_box(half_w=1.0, half_h=0.5, material=material, id_prefix="room")
    assert [shape.id for shape in box] == [
        "room_bottom",
        "room_top",
        "room_left",
        "room_right",
    ]

    lens = biconvex_lens(
        center=(0.0, 0.0),
        aperture=0.4,
        center_thickness=0.1,
        left_radius=0.8,
        right_radius=0.8,
        material=material,
        id_prefix="lens",
    )
    assert [shape.id for shape in lens] == [
        "lens_left_face",
        "lens_top_edge",
        "lens_right_face",
        "lens_bottom_edge",
    ]

    slits = double_slit(
        center=(0.0, 0.0),
        width=4.0,
        gap=0.3,
        separation=1.0,
        material=Material(albedo=0.0),
        id_prefix="barrier",
    )
    assert [shape.id for shape in slits] == [
        "barrier_barrier_0",
        "barrier_barrier_1",
        "barrier_barrier_2",
    ]

    guide = waveguide(
        points=[(-1.0, 0.0), (0.0, 0.5), (1.0, 0.0)],
        width=0.2,
        material=material,
        id_prefix="guide",
    )
    assert [shape.id for shape in guide] == [
        "guide_segment_0",
        "guide_segment_1",
    ]


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
