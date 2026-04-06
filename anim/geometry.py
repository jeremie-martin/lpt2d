"""Geometry utilities for shape bounds, transforms, and overlap tests."""

from __future__ import annotations

import math
from dataclasses import replace

from .types import (
    Arc,
    Bezier,
    Circle,
    Ellipse,
    Material,
    Polygon,
    Segment,
    Shape,
    Transform2D,
    clamp_arc_sweep,
    normalize_angle,
)


def _shape_bounds(shape: Shape) -> tuple[float, float, float, float] | None:
    """Approximate AABB (xmin, ymin, xmax, ymax) for a shape."""
    if isinstance(shape, Circle):
        cx, cy = shape.center
        r = shape.radius
        return (cx - r, cy - r, cx + r, cy + r)
    if isinstance(shape, Ellipse):
        cx, cy = shape.center
        cr, sr = math.cos(shape.rotation), math.sin(shape.rotation)
        hx = math.sqrt(
            shape.semi_a * shape.semi_a * cr * cr
            + shape.semi_b * shape.semi_b * sr * sr
        )
        hy = math.sqrt(
            shape.semi_a * shape.semi_a * sr * sr
            + shape.semi_b * shape.semi_b * cr * cr
        )
        return (cx - hx, cy - hy, cx + hx, cy + hy)
    if isinstance(shape, Segment):
        ax, ay = shape.a
        bx, by = shape.b
        return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
    if isinstance(shape, Arc):
        return _arc_bounds(shape)
    if isinstance(shape, Polygon):
        xs = [v[0] for v in shape.vertices]
        ys = [v[1] for v in shape.vertices]
        return (min(xs), min(ys), max(xs), max(ys))
    if isinstance(shape, Bezier):
        xs = [shape.p0[0], shape.p1[0], shape.p2[0]]
        ys = [shape.p0[1], shape.p1[1], shape.p2[1]]
        return (min(xs), min(ys), max(xs), max(ys))
    return None


def _aabb_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _shape_material(shape: Shape) -> Material:
    return shape.material  # type: ignore[union-attr]


def _transform_point(p: list[float], t: Transform2D) -> list[float]:
    sx, sy = t.scale
    rx, ry = p[0] * sx, p[1] * sy
    cos_r, sin_r = math.cos(t.rotate), math.sin(t.rotate)
    return [
        rx * cos_r - ry * sin_r + t.translate[0],
        rx * sin_r + ry * cos_r + t.translate[1],
    ]


def _arc_point(arc: Arc, angle: float) -> tuple[float, float]:
    return (
        arc.center[0] + arc.radius * math.cos(angle),
        arc.center[1] + arc.radius * math.sin(angle),
    )


def _angle_in_arc(angle: float, arc: Arc) -> bool:
    sweep = clamp_arc_sweep(arc.sweep)
    if sweep >= math.tau - 1e-5:
        return True
    delta = normalize_angle(angle - arc.angle_start)
    return delta <= sweep + 1e-5


def _arc_bounds(arc: Arc) -> tuple[float, float, float, float]:
    if clamp_arc_sweep(arc.sweep) >= math.tau - 1e-5:
        cx, cy = arc.center
        r = arc.radius
        return (cx - r, cy - r, cx + r, cy + r)

    points = [
        _arc_point(arc, arc.angle_start),
        _arc_point(arc, normalize_angle(arc.angle_start + clamp_arc_sweep(arc.sweep))),
    ]
    for angle in (0.0, 0.5 * math.pi, math.pi, 1.5 * math.pi):
        if _angle_in_arc(angle, arc):
            points.append(_arc_point(arc, angle))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _transform_ellipse_affine(ellipse: Ellipse, t: Transform2D) -> Ellipse:
    out = replace(ellipse)
    out.center = _transform_point(ellipse.center, t)

    cr, sr = math.cos(ellipse.rotation), math.sin(ellipse.rotation)
    tc, ts = math.cos(t.rotate), math.sin(t.rotate)
    sx, sy = t.scale
    a = ellipse.semi_a
    b = ellipse.semi_b

    b00 = a * (tc * sx * cr - ts * sy * sr)
    b01 = -b * (tc * sx * sr + ts * sy * cr)
    b10 = a * (ts * sx * cr + tc * sy * sr)
    b11 = b * (-ts * sx * sr + tc * sy * cr)

    c00 = b00 * b00 + b01 * b01
    c01 = b00 * b10 + b01 * b11
    c11 = b10 * b10 + b11 * b11
    trace = c00 + c11
    det = c00 * c11 - c01 * c01
    disc = math.sqrt(max(0.0, trace * trace * 0.25 - det))
    lambda_major = max(0.0, trace * 0.5 + disc)
    lambda_minor = max(0.0, trace * 0.5 - disc)

    out.semi_a = max(math.sqrt(lambda_major), 0.01)
    out.semi_b = max(math.sqrt(lambda_minor), 0.01)

    major_x, major_y = 1.0, 0.0
    if abs(c01) > 1e-6 or abs(lambda_major - c00) > 1e-6:
        major_x, major_y = c01, lambda_major - c00
        if major_x * major_x + major_y * major_y < 1e-12:
            major_x, major_y = lambda_major - c11, c01
        length_sq = major_x * major_x + major_y * major_y
        if length_sq > 1e-12:
            length = math.sqrt(length_sq)
            major_x /= length
            major_y /= length
    out.rotation = normalize_angle(math.atan2(major_y, major_x))
    return out


def _transform_shape(shape: Shape, t: Transform2D) -> Shape:
    if t.translate == [0.0, 0.0] and t.rotate == 0.0 and t.scale == [1.0, 1.0]:
        return shape
    uniform_scale = math.sqrt(abs(t.scale[0] * t.scale[1]))

    if isinstance(shape, Circle):
        return replace(
            shape,
            center=_transform_point(shape.center, t),
            radius=max(shape.radius * uniform_scale, 0.01),
        )
    if isinstance(shape, Segment):
        return replace(shape, a=_transform_point(shape.a, t), b=_transform_point(shape.b, t))
    if isinstance(shape, Arc):
        return replace(
            shape,
            center=_transform_point(shape.center, t),
            radius=max(shape.radius * uniform_scale, 0.01),
            angle_start=normalize_angle(shape.angle_start + t.rotate),
            sweep=clamp_arc_sweep(shape.sweep),
        )
    if isinstance(shape, Bezier):
        return replace(
            shape,
            p0=_transform_point(shape.p0, t),
            p1=_transform_point(shape.p1, t),
            p2=_transform_point(shape.p2, t),
        )
    if isinstance(shape, Polygon):
        return replace(shape, vertices=[_transform_point(v, t) for v in shape.vertices])
    if isinstance(shape, Ellipse):
        return _transform_ellipse_affine(shape, t)
    return shape
