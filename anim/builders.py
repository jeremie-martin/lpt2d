"""Shape composition helpers — common geometry from primitives."""

from __future__ import annotations

import math
from typing import Literal

from .types import Arc, Circle, Material, Polygon, Segment, Shape


def polygon(vertices: list[list[float]], material: Material) -> Polygon:
    """Closed polygon from a list of [x, y] vertices."""
    return Polygon(vertices=[list(v) for v in vertices], material=material)


def regular_polygon(
    center: tuple[float, float],
    radius: float,
    n: int,
    material: Material,
    rotation: float = 0.0,
) -> Polygon:
    """Regular *n*-sided polygon inscribed in a circle.

    *rotation* offsets the first vertex (radians, 0 = right).
    """
    cx, cy = center
    verts = [
        [
            cx + radius * math.cos(rotation - i * math.tau / n),
            cy + radius * math.sin(rotation - i * math.tau / n),
        ]
        for i in range(n)
    ]
    return polygon(verts, material)


def rectangle(
    center: tuple[float, float],
    width: float,
    height: float,
    material: Material,
) -> Polygon:
    """Axis-aligned rectangle centered at *center*."""
    cx, cy = center
    hw, hh = width / 2, height / 2
    return polygon(
        [[cx - hw, cy - hh], [cx - hw, cy + hh], [cx + hw, cy + hh], [cx + hw, cy - hh]],
        material,
    )


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
    sweep: float,
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
            sweep=sweep,
            material=material,
        ),
        Arc(
            center=[cx, cy],
            radius=r_inner,
            angle_start=angle_start,
            sweep=sweep,
            material=material,
        ),
    ]
    # End-cap segments connecting the two arcs
    for angle in (angle_start, angle_start + sweep):
        p_inner = [cx + r_inner * math.cos(angle), cy + r_inner * math.sin(angle)]
        p_outer = [cx + r_outer * math.cos(angle), cy + r_outer * math.sin(angle)]
        shapes.append(Segment(a=p_inner, b=p_outer, material=material))
    return shapes


def _convex_face(
    center_y: float,
    vertex_x: float,
    semi_aperture: float,
    radius: float,
    side: Literal["left", "right"],
    material: Material,
) -> tuple[Arc, list[float], list[float]]:
    if radius < semi_aperture:
        raise ValueError("convex face radius must be at least the lens semi-aperture")

    theta = math.asin(semi_aperture / radius)
    if side == "left":
        center_x = vertex_x + radius
        angle_start = math.pi - theta
        sweep = 2.0 * theta
        top = [center_x + radius * math.cos(angle_start), center_y + semi_aperture]
        bottom = [center_x + radius * math.cos(angle_start + sweep), center_y - semi_aperture]
    else:
        center_x = vertex_x - radius
        angle_start = math.tau - theta
        sweep = 2.0 * theta
        bottom = [center_x + radius * math.cos(angle_start), center_y - semi_aperture]
        top = [center_x + radius * math.cos(angle_start + sweep), center_y + semi_aperture]

    return (
        Arc(
            center=[center_x, center_y],
            radius=radius,
            angle_start=angle_start,
            sweep=sweep,
            material=material,
        ),
        top,
        bottom,
    )


def _plane_face(
    center_y: float,
    vertex_x: float,
    semi_aperture: float,
    side: Literal["left", "right"],
    material: Material,
) -> tuple[Segment, list[float], list[float]]:
    top = [vertex_x, center_y + semi_aperture]
    bottom = [vertex_x, center_y - semi_aperture]
    if side == "left":
        face = Segment(a=bottom, b=top, material=material)
    else:
        face = Segment(a=top, b=bottom, material=material)
    return face, top, bottom


def _build_lens(
    center: tuple[float, float],
    aperture: float,
    center_thickness: float,
    left_face: tuple[str, float | None],
    right_face: tuple[str, float | None],
    material: Material,
) -> list[Shape]:
    """Closed lens outline from left/right faces plus top/bottom edge segments."""
    eps = 1e-9
    cx, cy = center
    semi_aperture = aperture * 0.5
    half_thickness = center_thickness * 0.5
    left_vertex_x = cx - half_thickness
    right_vertex_x = cx + half_thickness

    def make_face(
        face: tuple[str, float | None], side: Literal["left", "right"]
    ) -> tuple[Shape, list[float], list[float]]:
        kind, radius = face
        if kind == "plane":
            return _plane_face(
                cy,
                left_vertex_x if side == "left" else right_vertex_x,
                semi_aperture,
                side,
                material,
            )
        if kind == "convex" and radius is not None:
            return _convex_face(
                cy,
                left_vertex_x if side == "left" else right_vertex_x,
                semi_aperture,
                radius,
                side,
                material,
            )
        raise ValueError(f"unsupported lens face: {face!r}")

    left_shape, left_top, left_bottom = make_face(left_face, "left")
    right_shape, right_top, right_bottom = make_face(right_face, "right")

    if left_top[0] - right_top[0] > eps or left_bottom[0] - right_bottom[0] > eps:
        raise ValueError("lens aperture closes before the edge; adjust thickness or curvature")

    shapes: list[Shape] = [left_shape]
    if abs(left_top[0] - right_top[0]) > eps or abs(left_top[1] - right_top[1]) > eps:
        shapes.append(Segment(a=left_top, b=right_top, material=material))
    shapes.append(right_shape)
    if abs(right_bottom[0] - left_bottom[0]) > eps or abs(right_bottom[1] - left_bottom[1]) > eps:
        shapes.append(Segment(a=right_bottom, b=left_bottom, material=material))
    return shapes


def biconvex_lens(
    center: tuple[float, float],
    aperture: float,
    center_thickness: float,
    left_radius: float,
    right_radius: float,
    material: Material,
) -> list[Shape]:
    """Biconvex lens from two real convex faces plus edge segments.

    *aperture* is the full clear aperture (height in this 2D cross-section).
    *center_thickness* is the lens thickness on the optical axis.
    """
    return _build_lens(
        center=center,
        aperture=aperture,
        center_thickness=center_thickness,
        left_face=("convex", left_radius),
        right_face=("convex", right_radius),
        material=material,
    )


def plano_convex_lens(
    center: tuple[float, float],
    aperture: float,
    center_thickness: float,
    radius: float,
    material: Material,
    curved_side: Literal["left", "right"] = "right",
) -> list[Shape]:
    """Plano-convex lens with one plane face and one convex circular face."""
    left_face: tuple[str, float | None] = ("plane", None)
    right_face: tuple[str, float | None] = ("plane", None)
    if curved_side == "left":
        left_face = ("convex", radius)
    elif curved_side == "right":
        right_face = ("convex", radius)
    else:
        raise ValueError("curved_side must be 'left' or 'right'")

    return _build_lens(
        center=center,
        aperture=aperture,
        center_thickness=center_thickness,
        left_face=left_face,
        right_face=right_face,
        material=material,
    )


def hemispherical_lens(
    center: tuple[float, float],
    radius: float,
    material: Material,
    curved_side: Literal["left", "right"] = "right",
) -> list[Shape]:
    """Hemispherical lens: a plano-convex lens whose curved face is a semicircle."""
    return plano_convex_lens(
        center=center,
        aperture=2.0 * radius,
        center_thickness=radius,
        radius=radius,
        material=material,
        curved_side=curved_side,
    )


def ball_lens(center: tuple[float, float], radius: float, material: Material) -> list[Circle]:
    """Ball lens represented by its actual circular boundary."""
    cx, cy = center
    return [Circle(center=[cx, cy], radius=radius, material=material)]
