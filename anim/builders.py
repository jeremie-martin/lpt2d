"""Shape composition helpers — common geometry from primitives."""

from __future__ import annotations

import math
from typing import Literal

from .types import Arc, Circle, Ellipse, Material, Polygon, Segment, Shape


def _shape_id(id_prefix: str | None, suffix: str) -> str:
    if id_prefix is None:
        return ""
    return f"{id_prefix}_{suffix}"


def polygon(
    vertices: list[list[float]],
    material: Material,
    *,
    corner_radius: float = 0.0,
    id_prefix: str | None = None,
) -> Polygon:
    """Closed polygon from a list of [x, y] vertices."""
    return Polygon(
        id=_shape_id(id_prefix, "body"), vertices=[list(v) for v in vertices],
        material=material, corner_radius=corner_radius,
    )


def regular_polygon(
    center: tuple[float, float],
    radius: float,
    n: int,
    material: Material,
    rotation: float = 0.0,
    *,
    corner_radius: float = 0.0,
    id_prefix: str | None = None,
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
    return polygon(verts, material, corner_radius=corner_radius, id_prefix=id_prefix)


def rectangle(
    center: tuple[float, float],
    width: float,
    height: float,
    material: Material,
    *,
    corner_radius: float = 0.0,
    id_prefix: str | None = None,
) -> Polygon:
    """Axis-aligned rectangle centered at *center*."""
    cx, cy = center
    hw, hh = width / 2, height / 2
    return polygon(
        [[cx - hw, cy - hh], [cx - hw, cy + hh], [cx + hw, cy + hh], [cx + hw, cy - hh]],
        material,
        corner_radius=corner_radius,
        id_prefix=id_prefix,
    )


def mirror_box(
    half_w: float,
    half_h: float,
    material: Material,
    *,
    id_prefix: str | None = None,
) -> list[Segment]:
    """Axis-aligned rectangular enclosure (4 segments, normals face inward)."""
    return [
        Segment(
            id=_shape_id(id_prefix, "bottom"),
            a=[-half_w, -half_h],
            b=[half_w, -half_h],
            material=material,
        ),
        Segment(
            id=_shape_id(id_prefix, "top"),
            a=[half_w, half_h],
            b=[-half_w, half_h],
            material=material,
        ),
        Segment(
            id=_shape_id(id_prefix, "left"),
            a=[-half_w, half_h],
            b=[-half_w, -half_h],
            material=material,
        ),
        Segment(
            id=_shape_id(id_prefix, "right"),
            a=[half_w, -half_h],
            b=[half_w, half_h],
            material=material,
        ),
    ]


def thick_arc(
    center: tuple[float, float],
    radius: float,
    thickness: float,
    angle_start: float,
    sweep: float,
    material: Material,
    *,
    id_prefix: str | None = None,
) -> list[Shape]:
    """Arc with physical thickness, approximated as a polygonal annular sector.

    *radius* is the mid-line radius; the shape spans from ``radius - thickness/2``
    to ``radius + thickness/2``.
    """
    if thickness <= 0:
        raise ValueError("thickness must be positive")
    sweep = max(0.0, min(sweep, math.tau))
    if sweep <= 0:
        raise ValueError("sweep must be positive")

    cx, cy = center
    r_inner = radius - thickness / 2
    r_outer = radius + thickness / 2
    if r_inner <= 0:
        raise ValueError("thickness is too large for the given radius")

    steps = max(12, min(128, math.ceil(r_outer * sweep / 0.03)))

    def ring_point(r: float, angle: float) -> list[float]:
        return [cx + r * math.cos(angle), cy + r * math.sin(angle)]

    end_angle = angle_start + sweep
    outer = [ring_point(r_outer, end_angle - sweep * (i / steps)) for i in range(steps + 1)]
    inner = [ring_point(r_inner, angle_start + sweep * (i / steps)) for i in range(steps + 1)]
    return [Polygon(id=_shape_id(id_prefix, "sector"), vertices=outer + inner, material=material)]


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
    *,
    id_prefix: str | None = None,
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
    left_shape.id = _shape_id(id_prefix, "left_face")
    right_shape.id = _shape_id(id_prefix, "right_face")

    if left_top[0] - right_top[0] > eps or left_bottom[0] - right_bottom[0] > eps:
        raise ValueError("lens aperture closes before the edge; adjust thickness or curvature")

    shapes: list[Shape] = [left_shape]
    if abs(left_top[0] - right_top[0]) > eps or abs(left_top[1] - right_top[1]) > eps:
        shapes.append(
            Segment(id=_shape_id(id_prefix, "top_edge"), a=left_top, b=right_top, material=material)
        )
    shapes.append(right_shape)
    if abs(right_bottom[0] - left_bottom[0]) > eps or abs(right_bottom[1] - left_bottom[1]) > eps:
        shapes.append(
            Segment(
                id=_shape_id(id_prefix, "bottom_edge"),
                a=right_bottom,
                b=left_bottom,
                material=material,
            )
        )
    return shapes


def biconvex_lens(
    center: tuple[float, float],
    aperture: float,
    center_thickness: float,
    left_radius: float,
    right_radius: float,
    material: Material,
    *,
    id_prefix: str | None = None,
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
        id_prefix=id_prefix,
    )


def plano_convex_lens(
    center: tuple[float, float],
    aperture: float,
    center_thickness: float,
    radius: float,
    material: Material,
    curved_side: Literal["left", "right"] = "right",
    *,
    id_prefix: str | None = None,
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
        id_prefix=id_prefix,
    )


def hemispherical_lens(
    center: tuple[float, float],
    radius: float,
    material: Material,
    curved_side: Literal["left", "right"] = "right",
    *,
    id_prefix: str | None = None,
) -> list[Shape]:
    """Hemispherical lens: a plano-convex lens whose curved face is a semicircle."""
    return plano_convex_lens(
        center=center,
        aperture=2.0 * radius,
        center_thickness=radius,
        radius=radius,
        material=material,
        curved_side=curved_side,
        id_prefix=id_prefix,
    )


def ball_lens(
    center: tuple[float, float],
    radius: float,
    material: Material,
    *,
    id_prefix: str | None = None,
) -> list[Circle]:
    """Ball lens represented by its actual circular boundary."""
    cx, cy = center
    return [
        Circle(id=_shape_id(id_prefix, "body"), center=[cx, cy], radius=radius, material=material)
    ]


# ─── Thick shapes ───────────────────────────────────────────────────────


def thick_segment(
    a: tuple[float, float],
    b: tuple[float, float],
    thickness: float,
    material: Material,
    *,
    corner_radius: float = 0.0,
    id_prefix: str | None = None,
) -> Polygon:
    """Segment with physical width — creates a rectangle Polygon.

    The rectangle is centered on the line from *a* to *b*, with total width
    *thickness* perpendicular to the segment direction.
    """
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-10:
        raise ValueError("thick_segment endpoints must be distinct")
    nx, ny = -dy / length * thickness / 2, dx / length * thickness / 2
    return Polygon(
        id=_shape_id(id_prefix, "body"),
        vertices=[
            [ax + nx, ay + ny],
            [bx + nx, by + ny],
            [bx - nx, by - ny],
            [ax - nx, ay - ny],
        ],
        material=material,
        corner_radius=corner_radius,
    )


# ─── Enhanced builders ──────────────────────────────────────────────────


def prism(
    center: tuple[float, float],
    size: float,
    material: Material,
    rotation: float = math.pi / 2,
    *,
    corner_radius: float = 0.0,
    id_prefix: str | None = None,
) -> Polygon:
    """Equilateral triangular prism (2D cross-section).

    Convenience wrapper around :func:`regular_polygon` with *n=3*.
    """
    return regular_polygon(center, size, 3, material, rotation=rotation,
                           corner_radius=corner_radius, id_prefix=id_prefix)


def mirror_block(
    center: tuple[float, float],
    width: float,
    height: float,
    material: Material,
    *,
    id_prefix: str | None = None,
    top: Material | None = None,
    right: Material | None = None,
    bottom: Material | None = None,
    left: Material | None = None,
) -> list[Segment]:
    """Rectangle convenience builder with per-face material overrides.

    The returned segments follow the same clockwise boundary order as
    :func:`rectangle`: left, top, right, bottom. This keeps outward normals
    coherent for solid-block use while still allowing face-specific materials.
    """
    if width <= 0:
        raise ValueError("width must be positive")
    if height <= 0:
        raise ValueError("height must be positive")

    verts = rectangle(center, width, height, material).vertices
    face_materials = [
        left if left is not None else material,
        top if top is not None else material,
        right if right is not None else material,
        bottom if bottom is not None else material,
    ]
    face_ids = ["left", "top", "right", "bottom"]
    return [
        Segment(
            id=_shape_id(id_prefix, face_ids[i]),
            a=list(verts[i]),
            b=list(verts[(i + 1) % len(verts)]),
            material=face_materials[i],
        )
        for i in range(len(verts))
    ]


def elliptical_lens(
    center: tuple[float, float],
    semi_a: float,
    semi_b: float,
    material: Material,
    rotation: float = 0.0,
    *,
    id_prefix: str | None = None,
) -> list[Ellipse]:
    """Elliptical lens — single Ellipse shape."""
    cx, cy = center
    return [
        Ellipse(
            id=_shape_id(id_prefix, "body"),
            center=[cx, cy],
            semi_a=semi_a,
            semi_b=semi_b,
            rotation=rotation,
            material=material,
        )
    ]


def slit(
    center: tuple[float, float],
    width: float,
    gap: float,
    material: Material,
    thickness: float = 0.0,
    *,
    id_prefix: str | None = None,
) -> list[Shape]:
    """Barrier with a centered opening.

    *width* is the total barrier extent, *gap* is the opening width.
    If *thickness* > 0, uses :func:`thick_segment` (Polygons); otherwise bare Segments.
    """
    cx, cy = center
    hw, hg = width / 2, gap / 2
    if thickness > 0:
        left = thick_segment((cx - hw, cy), (cx - hg, cy), thickness, material)
        right = thick_segment((cx + hg, cy), (cx + hw, cy), thickness, material)
        left.id = _shape_id(id_prefix, "left")
        right.id = _shape_id(id_prefix, "right")
        return [left, right]
    return [
        Segment(
            id=_shape_id(id_prefix, "left"), a=[cx - hw, cy], b=[cx - hg, cy], material=material
        ),
        Segment(
            id=_shape_id(id_prefix, "right"), a=[cx + hg, cy], b=[cx + hw, cy], material=material
        ),
    ]


def double_slit(
    center: tuple[float, float],
    width: float,
    gap: float,
    separation: float,
    material: Material,
    thickness: float = 0.0,
    *,
    id_prefix: str | None = None,
) -> list[Shape]:
    """Classic double-slit barrier.

    Two gaps of *gap* width, separated by *separation* (center-to-center).
    """
    cx, cy = center
    hw, hg, hs = width / 2, gap / 2, separation / 2
    edges = [cx - hw, cx - hs - hg, cx - hs + hg, cx + hs - hg, cx + hs + hg, cx + hw]
    shapes: list[Shape] = []
    for i in range(0, len(edges), 2):
        a_x, b_x = edges[i], edges[i + 1]
        if b_x - a_x > 1e-6:
            if thickness > 0:
                shape = thick_segment((a_x, cy), (b_x, cy), thickness, material)
            else:
                shape = Segment(a=[a_x, cy], b=[b_x, cy], material=material)
            shape.id = _shape_id(id_prefix, f"barrier_{len(shapes)}")
            shapes.append(shape)
    return shapes


def grating(
    center: tuple[float, float],
    n: int,
    spacing: float,
    gap: float,
    width: float,
    material: Material,
    thickness: float = 0.0,
    *,
    id_prefix: str | None = None,
) -> list[Shape]:
    """Diffraction grating: *n* evenly-spaced slits."""
    cx, cy = center
    slit_centers = [cx + (i - (n - 1) / 2) * spacing for i in range(n)]
    hg = gap / 2
    hw = width / 2
    edges: list[float] = [cx - hw]
    for sc in slit_centers:
        edges.append(sc - hg)
        edges.append(sc + hg)
    edges.append(cx + hw)
    shapes: list[Shape] = []
    for i in range(0, len(edges), 2):
        a_x, b_x = edges[i], edges[i + 1]
        if b_x - a_x > 1e-6:
            if thickness > 0:
                shape = thick_segment((a_x, cy), (b_x, cy), thickness, material)
            else:
                shape = Segment(a=[a_x, cy], b=[b_x, cy], material=material)
            shape.id = _shape_id(id_prefix, f"barrier_{len(shapes)}")
            shapes.append(shape)
    return shapes


def waveguide(
    points: list[tuple[float, float]],
    width: float,
    material: Material,
    *,
    id_prefix: str | None = None,
) -> list[Polygon]:
    """Chain of thick segments following a path."""
    shapes = [
        thick_segment(points[i], points[i + 1], width, material) for i in range(len(points) - 1)
    ]
    for i, shape in enumerate(shapes):
        shape.id = _shape_id(id_prefix, f"segment_{i}")
    return shapes
