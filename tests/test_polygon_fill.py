from __future__ import annotations

import math

import pytest

import _lpt2d


def _polygon_area(vertices: list[tuple[float, float]]) -> float:
    area2 = 0.0
    for i, a in enumerate(vertices):
        b = vertices[(i + 1) % len(vertices)]
        area2 += a[0] * b[1] - b[0] * a[1]
    return abs(area2) * 0.5


def _triangles_area(vertices: list[tuple[float, float]], indices: list[int]) -> float:
    total = 0.0
    for i in range(0, len(indices), 3):
        a = vertices[indices[i]]
        b = vertices[indices[i + 1]]
        c = vertices[indices[i + 2]]
        total += abs(a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1])) * 0.5
    return total


def test_polygon_fill_matches_rounded_rectangle_area() -> None:
    polygon = _lpt2d.Polygon(
        vertices=[(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)],
        material=_lpt2d.Material(fill=1.0),
        corner_radius=0.2,
    )

    boundary = _lpt2d._polygon_fill_boundary(polygon, arc_segments=48)
    indices = _lpt2d._triangulate_simple_polygon(boundary)

    expected = 2.0 - (4.0 - math.pi) * 0.2 * 0.2
    assert len(indices) >= 6
    assert len(indices) % 3 == 0
    assert _triangles_area(boundary, indices) == pytest.approx(expected, rel=5e-3, abs=5e-3)


def test_polygon_fill_handles_concave_polygon_with_partial_rounding() -> None:
    polygon = _lpt2d.Polygon(
        vertices=[(0.0, 0.0), (0.0, 3.0), (1.0, 3.0), (1.0, 1.0), (3.0, 1.0), (3.0, 0.0)],
        material=_lpt2d.Material(fill=1.0),
        corner_radius=0.3,
    )

    boundary = _lpt2d._polygon_fill_boundary(polygon, arc_segments=24)
    indices = _lpt2d._triangulate_simple_polygon(boundary)

    assert len(boundary) > len(polygon.vertices)
    assert len(indices) >= 9
    assert len(indices) % 3 == 0
    assert _triangles_area(boundary, indices) == pytest.approx(
        _polygon_area(boundary), rel=1e-4, abs=1e-4
    )


def test_polygon_fill_handles_per_vertex_corner_radii_override() -> None:
    polygon = _lpt2d.Polygon(
        vertices=[(0.0, 0.0), (0.0, 3.0), (1.0, 3.0), (1.0, 1.0), (3.0, 1.0), (3.0, 0.0)],
        material=_lpt2d.Material(fill=1.0),
        corner_radius=0.4,
        corner_radii=[0.3, 0.0, 0.2, 0.3, 0.0, 0.1],
    )

    boundary = _lpt2d._polygon_fill_boundary(polygon, arc_segments=24)
    indices = _lpt2d._triangulate_simple_polygon(boundary)

    assert (1.0, 1.0) in boundary
    assert len(boundary) > len(polygon.vertices)
    assert len(indices) % 3 == 0
    assert _triangles_area(boundary, indices) == pytest.approx(
        _polygon_area(boundary), rel=1e-4, abs=1e-4
    )
