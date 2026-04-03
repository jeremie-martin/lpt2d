"""Shape composition helpers — common geometry from primitives."""

from __future__ import annotations

import math

from .types import Arc, Circle, Material, Segment, Shape


def polygon(vertices: list[list[float]], material: Material) -> list[Segment]:
    """Closed polygon from a list of [x, y] vertices."""
    n = len(vertices)
    return [
        Segment(a=list(vertices[i]), b=list(vertices[(i + 1) % n]), material=material)
        for i in range(n)
    ]


def regular_polygon(
    center: tuple[float, float],
    radius: float,
    n: int,
    material: Material,
    rotation: float = 0.0,
) -> list[Segment]:
    """Regular *n*-sided polygon inscribed in a circle.

    *rotation* offsets the first vertex (radians, 0 = right).
    """
    cx, cy = center
    verts = [
        [
            cx + radius * math.cos(rotation + i * math.tau / n),
            cy + radius * math.sin(rotation + i * math.tau / n),
        ]
        for i in range(n)
    ]
    return polygon(verts, material)


def mirror_box(half_w: float, half_h: float, material: Material) -> list[Segment]:
    """Axis-aligned rectangular enclosure (4 segments, normals face inward)."""
    return [
        Segment(a=[-half_w, -half_h], b=[half_w, -half_h], material=material),
        Segment(a=[half_w, half_h], b=[-half_w, half_h], material=material),
        Segment(a=[-half_w, half_h], b=[-half_w, -half_h], material=material),
        Segment(a=[half_w, -half_h], b=[half_w, half_h], material=material),
    ]


def thick_arc(
    center: tuple[float, float],
    radius: float,
    thickness: float,
    angle_start: float,
    angle_end: float,
    material: Material,
) -> list[Shape]:
    """Arc with physical thickness (two concentric arcs + two end-cap segments).

    *radius* is the mid-line radius; the shape spans from ``radius - thickness/2``
    to ``radius + thickness/2``.
    """
    cx, cy = center
    r_inner = radius - thickness / 2
    r_outer = radius + thickness / 2
    shapes: list[Shape] = [
        Arc(
            center=[cx, cy],
            radius=r_outer,
            angle_start=angle_start,
            angle_end=angle_end,
            material=material,
        ),
        Arc(
            center=[cx, cy],
            radius=r_inner,
            angle_start=angle_start,
            angle_end=angle_end,
            material=material,
        ),
    ]
    # End-cap segments connecting the two arcs
    for angle in (angle_start, angle_end):
        p_inner = [cx + r_inner * math.cos(angle), cy + r_inner * math.sin(angle)]
        p_outer = [cx + r_outer * math.cos(angle), cy + r_outer * math.sin(angle)]
        shapes.append(Segment(a=p_inner, b=p_outer, material=material))
    return shapes


def biconvex_lens(
    center: tuple[float, float],
    r1: float,
    r2: float,
    separation: float,
    material: Material,
) -> list[Circle]:
    """Biconvex lens from two overlapping circles.

    *r1* and *r2* are the radii of curvature of the two faces.
    *separation* is the distance between circle centers along the optical axis.
    The lens is centered at *center*, oriented horizontally.
    """
    cx, cy = center
    half = separation / 2
    return [
        Circle(center=[cx - half, cy], radius=r1, material=material),
        Circle(center=[cx + half, cy], radius=r2, material=material),
    ]
