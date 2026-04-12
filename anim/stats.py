"""Frame statistics for automated analysis and agent workflows.

The actual image-stat and point-light appearance math lives in
the C++ frame-analysis core (see `src/core/image_analysis.cpp`). Callers
should read `rr.metrics` / `rr.analysis.image` / `rr.analysis.debug`
directly after rendering a frame with ``analyze=True``.

What remains in this module:

- `QualityGate` / `check_quality` — threshold policy on top of `FrameReport`.
- `StatsDiff` / `compare_stats` / `compare_summary` — A/B comparison.
- `LookProfile` / `LookComparison` / `LookReport` — Look-quality analytics.
- `LightContribution` / `StructureReport` and the shape-clutter diagnostics.

All of these operate on normalized `ImageStats`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import _lpt2d

from .types import (
    Arc,
    Bezier,
    Circle,
    Ellipse,
    ImageStats,
    FrameReport,
    Look,
    Material,
    Polygon,
    Scene,
    Segment,
    Shape,
    Transform2D,
    clamp_arc_sweep,
    normalize_angle,
)


# --- Quality gates ---


@dataclass
class QualityGate:
    """Threshold configuration for automated quality checks.

    All thresholds use the public normalized image-stat scale.
    """

    max_clipped_channel_fraction: float = 0.05  # warn if any-channel clipping > 5%
    min_mean: float = 0.3  # warn if mean brightness < 0.3
    max_near_black_fraction: float = 0.8  # warn if near-black occupancy > 80%


def check_quality(report: FrameReport, gate: QualityGate) -> list[str]:
    """Check live metrics from a FrameReport against quality thresholds.

    Returns a list of warning strings (empty means all checks passed).
    Gracefully returns empty if live metrics are not available.
    """
    warnings: list[str] = []
    if report.mean_luma is None:
        return warnings
    if (
        report.clipped_channel_fraction is not None
        and report.clipped_channel_fraction > gate.max_clipped_channel_fraction
    ):
        warnings.append(
            "clipping "
            f"{report.clipped_channel_fraction:.1%} > {gate.max_clipped_channel_fraction:.1%}"
        )
    if report.mean_luma < gate.min_mean:
        warnings.append(f"mean brightness {report.mean_luma:.2f} < {gate.min_mean}")
    if (
        report.near_black_fraction is not None
        and report.near_black_fraction > gate.max_near_black_fraction
    ):
        warnings.append(
            "near-black occupancy "
            f"{report.near_black_fraction:.1%} > {gate.max_near_black_fraction:.1%}"
        )
    return warnings


# --- A/B comparison ---


@dataclass(frozen=True)
class StatsDiff:
    """Per-field difference between two normalized ImageStats values (b - a)."""

    mean_luma: float
    near_black_fraction: float
    clipped_channel_fraction: float
    median_luma: float
    p95_luma: float
    interdecile_luma_range: float

    def summary(self) -> str:
        """One-line summary with signed deltas."""

        def _fmt(name: str, val: float) -> str:
            return f"{name}={val:+.2f}"

        return " ".join(
            [
                _fmt("mean_luma", self.mean_luma),
                _fmt("near_black", self.near_black_fraction),
                _fmt("clipped", self.clipped_channel_fraction),
                _fmt("median_luma", self.median_luma),
                _fmt("p95_luma", self.p95_luma),
                _fmt("interdecile_range", self.interdecile_luma_range),
            ]
        )


def compare_stats(
    a: list[tuple[int, float, ImageStats]],
    b: list[tuple[int, float, ImageStats]],
) -> list[tuple[int, float, StatsDiff]]:
    """Compare two render_stats() results frame-by-frame.

    Both lists must have the same length and frame indices.
    Returns per-frame StatsDiff (b - a).
    """
    if len(a) != len(b):
        raise ValueError(f"Mismatched frame counts: {len(a)} vs {len(b)}")
    diffs: list[tuple[int, float, StatsDiff]] = []
    for (fi_a, t_a, sa), (fi_b, _, sb) in zip(a, b, strict=True):
        if fi_a != fi_b:
            raise ValueError(f"Frame index mismatch: {fi_a} vs {fi_b}")
        diffs.append(
            (
                fi_a,
                t_a,
                StatsDiff(
                    mean_luma=sb.mean_luma - sa.mean_luma,
                    near_black_fraction=sb.near_black_fraction - sa.near_black_fraction,
                    clipped_channel_fraction=(
                        sb.clipped_channel_fraction - sa.clipped_channel_fraction
                    ),
                    median_luma=sb.median_luma - sa.median_luma,
                    p95_luma=sb.p95_luma - sa.p95_luma,
                    interdecile_luma_range=(
                        sb.interdecile_luma_range - sa.interdecile_luma_range
                    ),
                ),
            )
        )
    return diffs


def compare_summary(diffs: list[tuple[int, float, StatsDiff]]) -> str:
    """Multi-line summary of an A/B stats comparison."""
    if not diffs:
        return "(no frames to compare)"
    lines = [f"A/B comparison ({len(diffs)} frames):"]
    for fi, t, d in diffs:
        lines.append(f"  frame {fi} ({t:.2f}s): {d.summary()}")
    # Aggregate
    n = len(diffs)
    avg_mean = sum(d.mean_luma for _, _, d in diffs) / n
    avg_clip = sum(d.clipped_channel_fraction for _, _, d in diffs) / n
    lines.append(f"  average: mean={avg_mean:+.2f} clipped={avg_clip:+.4f}")
    return "\n".join(lines)


# --- Clutter diagnostics ---


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
            shape.semi_a * shape.semi_a * cr * cr + shape.semi_b * shape.semi_b * sr * sr
        )
        hy = math.sqrt(
            shape.semi_a * shape.semi_a * sr * sr + shape.semi_b * shape.semi_b * cr * cr
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


def _shape_material(shape: Shape, scene: Scene) -> Material:
    return _lpt2d.resolve_material(shape, scene)  # type: ignore[arg-type]


def _transform_point(p: Sequence[float], t: Transform2D) -> list[float]:
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
    bounds = (min(xs), min(ys), max(xs), max(ys))
    return cast(
        tuple[float, float, float, float],
        tuple(0.0 if abs(value) < 1e-6 else value for value in bounds),
    )


def _transform_ellipse_affine(ellipse: Ellipse, t: Transform2D) -> Ellipse:
    out = cast(Ellipse, _copy_shape(ellipse, center=_transform_point(ellipse.center, t)))

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


def _shape_binding_kwargs(shape: Shape) -> dict[str, Any]:
    return {"material_id": getattr(shape, "material_id", "")}


def _copy_shape(shape: Shape, **overrides) -> Shape:
    binding = {"material_id": overrides.pop("material_id")} if "material_id" in overrides else _shape_binding_kwargs(shape)

    if isinstance(shape, Circle):
        return Circle(
            id=overrides.get("id", shape.id),
            center=overrides.get("center", shape.center),
            radius=overrides.get("radius", shape.radius),
            **binding,
        )
    if isinstance(shape, Segment):
        return Segment(
            id=overrides.get("id", shape.id),
            a=overrides.get("a", shape.a),
            b=overrides.get("b", shape.b),
            **binding,
        )
    if isinstance(shape, Arc):
        return Arc(
            id=overrides.get("id", shape.id),
            center=overrides.get("center", shape.center),
            radius=overrides.get("radius", shape.radius),
            angle_start=overrides.get("angle_start", shape.angle_start),
            sweep=overrides.get("sweep", shape.sweep),
            **binding,
        )
    if isinstance(shape, Bezier):
        return Bezier(
            id=overrides.get("id", shape.id),
            p0=overrides.get("p0", shape.p0),
            p1=overrides.get("p1", shape.p1),
            p2=overrides.get("p2", shape.p2),
            **binding,
        )
    if isinstance(shape, Polygon):
        return Polygon(
            id=overrides.get("id", shape.id),
            vertices=overrides.get("vertices", shape.vertices),
            corner_radius=overrides.get("corner_radius", shape.corner_radius),
            corner_radii=overrides.get("corner_radii", shape.corner_radii),
            join_modes=overrides.get("join_modes", shape.join_modes),
            smooth_angle=overrides.get("smooth_angle", shape.smooth_angle),
            **binding,
        )
    if isinstance(shape, Ellipse):
        return Ellipse(
            id=overrides.get("id", shape.id),
            center=overrides.get("center", shape.center),
            semi_a=overrides.get("semi_a", shape.semi_a),
            semi_b=overrides.get("semi_b", shape.semi_b),
            rotation=overrides.get("rotation", shape.rotation),
            **binding,
        )
    return shape


def _transform_shape(shape: Shape, t: Transform2D) -> Shape:
    if tuple(t.translate) == (0.0, 0.0) and t.rotate == 0.0 and tuple(t.scale) == (1.0, 1.0):
        return shape
    uniform_scale = math.sqrt(abs(t.scale[0] * t.scale[1]))

    if isinstance(shape, Circle):
        return _copy_shape(
            shape,
            center=_transform_point(shape.center, t),
            radius=max(shape.radius * uniform_scale, 0.01),
        )
    if isinstance(shape, Segment):
        return _copy_shape(shape, a=_transform_point(shape.a, t), b=_transform_point(shape.b, t))
    if isinstance(shape, Arc):
        return _copy_shape(
            shape,
            center=_transform_point(shape.center, t),
            radius=max(shape.radius * uniform_scale, 0.01),
            angle_start=normalize_angle(shape.angle_start + t.rotate),
            sweep=clamp_arc_sweep(shape.sweep),
        )
    if isinstance(shape, Bezier):
        return _copy_shape(
            shape,
            p0=_transform_point(shape.p0, t),
            p1=_transform_point(shape.p1, t),
            p2=_transform_point(shape.p2, t),
        )
    if isinstance(shape, Polygon):
        cr = shape.corner_radius
        scaled_cr = max(cr * uniform_scale, 0.0) if cr > 0.0 else 0.0
        scaled_corner_radii = [max(radius * uniform_scale, 0.0) for radius in shape.corner_radii]
        return _copy_shape(
            shape,
            vertices=[_transform_point(v, t) for v in shape.vertices],
            corner_radius=scaled_cr,
            corner_radii=scaled_corner_radii,
        )
    if isinstance(shape, Ellipse):
        return _transform_ellipse_affine(shape, t)
    return shape


def diagnose_scene(scene: Scene) -> list[str]:
    """Fast non-rendering structural analysis for potential clutter issues."""
    warnings: list[str] = []

    all_shapes: list[Shape] = list(scene.shapes)
    for group in scene.groups:
        all_shapes.extend(_transform_shape(shape, group.transform) for shape in group.shapes)

    n_surfaces = len(all_shapes)
    if n_surfaces > 20:
        warnings.append(
            f"High surface count ({n_surfaces}): many optical surfaces increase scatter probability"
        )

    glass_no_absorb = [
        shape
        for shape in all_shapes
        for material in [_shape_material(shape, scene)]
        if material.transmission > 0.5 and material.absorption < 0.01
    ]
    if len(glass_no_absorb) > 5:
        warnings.append(
            f"{len(glass_no_absorb)} transparent shapes with near-zero absorption: "
            f"rays may bounce indefinitely, creating muddy renders"
        )

    bounds_list: list[tuple[Shape, tuple[float, float, float, float]]] = []
    for shape in all_shapes:
        bounds = _shape_bounds(shape)
        if bounds is not None:
            bounds_list.append((shape, bounds))
    overlap_count = 0
    for i, (_, bounds_i) in enumerate(bounds_list):
        for _, bounds_j in bounds_list[i + 1 :]:
            if _aabb_overlap(bounds_i, bounds_j):
                overlap_count += 1
    if overlap_count > 10:
        warnings.append(f"{overlap_count} overlapping shape pairs: may cause visual clutter")

    all_lights = list(scene.lights)
    for group in scene.groups:
        all_lights.extend(group.lights)
    emissive_sources = sum(
        1 for shape in all_shapes if _shape_material(shape, scene).emission > 0.0
    )

    total_sources = len(all_lights) + emissive_sources
    if total_sources > 10:
        warnings.append(f"High light/source count ({total_sources}): may create visual noise")

    return warnings


# --- Look profiling ---


@dataclass(frozen=True)
class LookProfile:
    """How a Look performs across sampled frames.

    ``mean_brightness`` and ``std_brightness`` are on 0-1 scale.
    """

    look: Look
    per_frame: list[tuple[int, float, ImageStats]]
    mean_brightness: float
    std_brightness: float
    max_clipped_channel_fraction: float
    max_near_black_fraction: float
    mean_interdecile_luma_range: float
    std_interdecile_luma_range: float

    @property
    def stability(self) -> float:
        """0-1 score: 1 = perfectly stable, 0 = wildly varying."""
        if self.mean_brightness < 1e-6:
            return 0.0
        cv = self.std_brightness / self.mean_brightness
        return max(0.0, 1.0 - cv * 5.0)  # cv of 0.2 → stability 0

    def summary(self) -> str:
        """Multi-line profile summary."""
        lines = [
            f"Look: exposure={self.look.exposure} tonemap={self.look.tonemap}"
            f" normalize={self.look.normalize}",
            f"Stability: {self.stability:.2f}",
            f"Brightness: mean={self.mean_brightness:.3f} std={self.std_brightness:.3f}",
            "Max clipping: "
            f"{self.max_clipped_channel_fraction:.1%}  "
            f"Max near-black: {self.max_near_black_fraction:.1%}",
            "Interdecile luma range: "
            f"mean={self.mean_interdecile_luma_range:.3f} "
            f"std={self.std_interdecile_luma_range:.3f}",
            f"Frames sampled: {len(self.per_frame)}",
        ]
        return "\n".join(lines)

    @staticmethod
    def from_stats(look: Look, results: list[tuple[int, float, ImageStats]]) -> "LookProfile":
        """Compute profile from render_stats output."""
        if not results:
            return LookProfile(
                look=look,
                per_frame=[],
                mean_brightness=0,
                std_brightness=0,
                max_clipped_channel_fraction=0,
                max_near_black_fraction=0,
                mean_interdecile_luma_range=0,
                std_interdecile_luma_range=0,
            )
        brightnesses = [s.mean_luma for _, _, s in results]
        contrast_ranges = [s.interdecile_luma_range for _, _, s in results]
        n = len(results)
        mean_b = sum(brightnesses) / n
        std_b = (sum((b - mean_b) ** 2 for b in brightnesses) / max(n - 1, 1)) ** 0.5
        mean_cr = sum(contrast_ranges) / n
        std_cr = (sum((c - mean_cr) ** 2 for c in contrast_ranges) / max(n - 1, 1)) ** 0.5
        return LookProfile(
            look=look,
            per_frame=list(results),
            mean_brightness=mean_b,
            std_brightness=std_b,
            max_clipped_channel_fraction=max(
                s.clipped_channel_fraction for _, _, s in results
            ),
            max_near_black_fraction=max(s.near_black_fraction for _, _, s in results),
            mean_interdecile_luma_range=mean_cr,
            std_interdecile_luma_range=std_cr,
        )


@dataclass(frozen=True)
class LookComparison:
    """Side-by-side comparison of Look candidates."""

    profiles: list[LookProfile]
    frame_indices: list[int]

    def summary(self) -> str:
        """Tabular summary comparing all candidates."""
        lines = [
            f"Look comparison ({len(self.profiles)} candidates, {len(self.frame_indices)} frames):"
        ]
        lines.append(
            f"  {'Exposure':>10} {'Tonemap':>10} {'Mean':>6} {'Std':>6} {'Clip':>6} {'Stab':>5}"
        )
        for p in self.profiles:
            lines.append(
                f"  {p.look.exposure:>10.2f} {p.look.tonemap:>10}"
                f" {p.mean_brightness:>6.3f} {p.std_brightness:>6.3f}"
                f" {p.max_clipped_channel_fraction:>5.1%} {p.stability:>5.2f}"
            )
        return "\n".join(lines)

    def best(self, *, target_mean: float = 0.35, weight_stability: float = 0.3) -> LookProfile:
        """Return the profile closest to target with stability bonus."""
        if not self.profiles:
            raise ValueError("No profiles to compare")

        def score(p: LookProfile) -> float:
            mean_err = abs(p.mean_brightness - target_mean)
            return (
                mean_err
                - weight_stability * p.stability
                + 2.0 * p.max_clipped_channel_fraction
            )

        return min(self.profiles, key=score)


@dataclass(frozen=True)
class LookReport:
    """Diagnostic report: how a Look holds up across an animation's timeline."""

    profile: LookProfile
    dark_frames: list[int]
    bright_frames: list[int]
    clipping_frames: list[int]
    low_contrast_frames: list[int]

    def summary(self) -> str:
        """Human-readable diagnostic."""
        p = self.profile
        lines = [p.summary()]
        if self.dark_frames:
            lines.append(f"Dark frames ({len(self.dark_frames)}): {self.dark_frames[:10]}")
        if self.bright_frames:
            lines.append(f"Bright frames ({len(self.bright_frames)}): {self.bright_frames[:10]}")
        if self.clipping_frames:
            lines.append(
                f"Clipping frames ({len(self.clipping_frames)}): {self.clipping_frames[:10]}"
            )
        if self.low_contrast_frames:
            lines.append(
                f"Low contrast frames ({len(self.low_contrast_frames)}): {self.low_contrast_frames[:10]}"
            )
        if not (
            self.dark_frames
            or self.bright_frames
            or self.clipping_frames
            or self.low_contrast_frames
        ):
            lines.append("No problem frames detected.")
        return "\n".join(lines)

    @staticmethod
    def from_profile(
        profile: LookProfile,
        *,
        dark_threshold: float = 0.15,
        bright_threshold: float = 0.70,
        clipped_channel_threshold: float = 0.05,
        interdecile_luma_range_threshold: float = 30.0 / 255.0,
    ) -> "LookReport":
        """Analyze a profile and flag problem frames."""
        dark = []
        bright = []
        clipping = []
        low_contrast = []
        for fi, _t, s in profile.per_frame:
            b = s.mean_luma
            if b < dark_threshold:
                dark.append(fi)
            if b > bright_threshold:
                bright.append(fi)
            if s.clipped_channel_fraction > clipped_channel_threshold:
                clipping.append(fi)
            if s.interdecile_luma_range < interdecile_luma_range_threshold:
                low_contrast.append(fi)
        return LookReport(
            profile=profile,
            dark_frames=dark,
            bright_frames=bright,
            clipping_frames=clipping,
            low_contrast_frames=low_contrast,
        )


# --- Clutter diagnostics ---


@dataclass(frozen=True)
class LightContribution:
    """Linear contribution of one authored light source to the frame.

    The measurement is taken with a neutral linear look and one shared fixed
    normalization reference captured from the full scene. That keeps the
    contribution shares additive and comparable across authored sources.
    """

    source_id: str
    source_index: int
    mean_linear_luma: float  # linear mean BT.709 luminance, normalized display scale
    coverage_fraction: float  # spatial coverage (1 - near_black_fraction)
    share: float  # this source's linear mean / summed linear mean across sources


@dataclass(frozen=True)
class StructureReport:
    """Effect of a shape on the scene's appearance."""

    shape_id: str
    stats_with: ImageStats
    stats_without: ImageStats
    diff: StatsDiff
    role: str  # "brightener", "dimmer", "neutral"

    def summary(self) -> str:
        return f"{self.shape_id}: role={self.role} {self.diff.summary()}"
