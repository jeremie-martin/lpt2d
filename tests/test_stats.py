"""Unit tests for the stats pipeline: quality gates and A/B comparison."""

from __future__ import annotations

import math
from typing import Any

import pytest

from anim import diagnose_scene
from anim import types as types_mod
from anim.stats import (
    LookComparison,
    LookProfile,
    LookReport,
    QualityGate,
    StatsDiff,
    _shape_bounds,
    _transform_shape,
    check_quality,
    compare_stats,
    compare_summary,
)
from anim.types import (
    Arc,
    Circle,
    Ellipse,
    FrameReport,
    Group,
    Look,
    Material,
    Polygon,
    Scene,
    Transform2D,
)

from _metrics_fixtures import fake_metrics

MAT_ID = "mat"
GLASS_ID = "glass"
EMISSIVE_ID = "emissive"


# --- QualityGate / check_quality ---


def _report(**kwargs) -> FrameReport:
    """Build a FrameReport with live metrics."""
    defaults: dict = dict(
        frame=0,
        rays=1000,
        time_ms=10,
        max_hdr=1.0,
        total_rays=1000,
        mean=50.0,
        median=40.0,
        shadow_floor=5.0,
        highlight_ceiling=180.0,
        highlight_peak=220.0,
        contrast_std=30.0,
        contrast_spread=175.0,
        near_black_fraction=0.3,
        near_white_fraction=0.0,
        clipped_channel_fraction=0.01,
    )
    defaults.update(kwargs)
    return FrameReport(**defaults)


def test_quality_gate_passes():
    gate = QualityGate()
    report = _report(mean=100.0, clipped_channel_fraction=0.01, near_black_fraction=0.3)
    warnings = check_quality(report, gate)
    assert warnings == []


def test_quality_gate_clipping():
    gate = QualityGate(max_clipped_channel_fraction=0.05)
    report = _report(mean=200.0, clipped_channel_fraction=0.12)
    warnings = check_quality(report, gate)
    assert len(warnings) == 1
    assert "clipping" in warnings[0]


def test_quality_gate_underexposed():
    gate = QualityGate(min_mean=0.3)
    # mean=10 => 10/255 = 0.039, well below 0.3
    report = _report(mean=10.0)
    warnings = check_quality(report, gate)
    assert any("mean brightness" in w for w in warnings)


def test_quality_gate_too_black():
    gate = QualityGate(max_near_black_fraction=0.5)
    report = _report(near_black_fraction=0.85)
    warnings = check_quality(report, gate)
    assert any("near-black" in w for w in warnings)


def test_quality_gate_no_metrics():
    """When live metrics are absent, check_quality returns empty."""
    gate = QualityGate()
    report = FrameReport(frame=0, rays=1000, time_ms=10, max_hdr=1.0, total_rays=1000)
    warnings = check_quality(report, gate)
    assert warnings == []


# --- StatsDiff / compare_stats ---


_FRAME_STATS_DEFAULTS = dict(
    mean=50.0,
    median=40.0,
    shadow_floor=5.0,
    highlight_ceiling=180.0,
    highlight_peak=220.0,
    contrast_std=30.0,
    contrast_spread=175.0,
    near_black_fraction=0.3,
    near_white_fraction=0.0,
    clipped_channel_fraction=0.02,
)


def _frame_stats(**kwargs) -> Any:
    """Build a FrameMetrics-shaped fake for compare_stats / LookProfile tests.

    Defaults match the normal luminance happy values so each call site only
    overrides what it cares about.
    """
    return fake_metrics(**{**_FRAME_STATS_DEFAULTS, **kwargs})


def test_compare_stats_zero_diff():
    a = [(0, 0.0, _frame_stats())]
    b = [(0, 0.0, _frame_stats())]
    diffs = compare_stats(a, b)
    assert len(diffs) == 1
    _, _, d = diffs[0]
    assert d.mean == 0.0
    assert d.clipped_channel_fraction == 0.0


def test_compare_stats_exposure_change():
    a = [(0, 0.0, _frame_stats(mean=50.0, clipped_channel_fraction=0.02, highlight_ceiling=180.0))]
    b = [(0, 0.0, _frame_stats(mean=80.0, clipped_channel_fraction=0.08, highlight_ceiling=220.0))]
    diffs = compare_stats(a, b)
    _, _, d = diffs[0]
    assert d.mean == pytest.approx(30.0)
    assert d.clipped_channel_fraction == pytest.approx(0.06)
    assert d.highlight_ceiling == pytest.approx(40.0)


def test_compare_stats_length_mismatch():
    a = [(0, 0.0, _frame_stats())]
    b = [(0, 0.0, _frame_stats()), (1, 0.5, _frame_stats())]
    with pytest.raises(ValueError, match="Mismatched"):
        compare_stats(a, b)


def test_compare_summary():
    a = [(0, 0.0, _frame_stats(mean=50.0)), (1, 0.5, _frame_stats(mean=60.0))]
    b = [(0, 0.0, _frame_stats(mean=70.0)), (1, 0.5, _frame_stats(mean=80.0))]
    diffs = compare_stats(a, b)
    summary = compare_summary(diffs)
    assert "A/B comparison" in summary
    assert "2 frames" in summary
    assert "average" in summary


def test_stats_diff_summary():
    d = StatsDiff(
        mean=5.0,
        near_black_fraction=-0.1,
        clipped_channel_fraction=0.02,
        median=3.0,
        highlight_ceiling=10.0,
    )
    s = d.summary()
    assert "mean=+5.00" in s
    assert "clipped=+0.02" in s


# frame_stats_from_report was deleted alongside the Python FrameStats
# dataclass when luminance statistics moved to the C++ image_analysis
# module. The equivalent now is `RenderResult.metrics` straight out of
# `RenderSession.render_shot()` — no histogram reconstruction needed.


# --- LookProfile / LookComparison / LookReport ---


def _make_profile(brightnesses: list[float], clipping: float = 0.0) -> LookProfile:
    """Build a LookProfile from per-frame brightness values (0-1 scale)."""
    per_frame = [
        (i, i * 0.1, _frame_stats(mean=b * 255.0, clipped_channel_fraction=clipping))
        for i, b in enumerate(brightnesses)
    ]
    return LookProfile.from_stats(Look(), per_frame)


def test_look_profile_from_stats_basic():
    profile = _make_profile([0.3, 0.35, 0.4])
    assert profile.mean_brightness == pytest.approx(0.35, abs=0.01)
    assert profile.std_brightness > 0
    assert profile.max_clipped_channel_fraction == 0.0
    assert len(profile.per_frame) == 3


def test_look_profile_stability_perfect():
    profile = _make_profile([0.35, 0.35, 0.35, 0.35])
    assert profile.stability == pytest.approx(1.0, abs=0.01)


def test_look_profile_stability_poor():
    profile = _make_profile([0.1, 0.5, 0.1, 0.5])
    assert profile.stability < 0.5


def test_look_profile_empty():
    profile = LookProfile.from_stats(Look(), [])
    assert profile.mean_brightness == 0
    assert profile.stability == 0


def test_look_comparison_summary():
    p1 = _make_profile([0.3, 0.35])
    p2 = _make_profile([0.4, 0.45])
    comp = LookComparison(profiles=[p1, p2], frame_indices=[0, 1])
    summary = comp.summary()
    assert "2 candidates" in summary
    assert "2 frames" in summary


def test_look_comparison_best():
    good = _make_profile([0.34, 0.35, 0.36])  # stable around target
    bad = _make_profile([0.1, 0.5, 0.8])  # unstable
    comp = LookComparison(profiles=[bad, good], frame_indices=[0, 1, 2])
    winner = comp.best(target_mean=0.35)
    assert winner.mean_brightness == pytest.approx(good.mean_brightness, abs=0.01)


def test_look_report_flags_dark_frames():
    profile = _make_profile([0.1, 0.35, 0.35, 0.1])
    report = LookReport.from_profile(profile, dark_threshold=0.15)
    assert 0 in report.dark_frames
    assert 3 in report.dark_frames
    assert 1 not in report.dark_frames


def test_look_report_flags_clipping():
    per_frame = [
        (0, 0.0, _frame_stats(clipped_channel_fraction=0.0)),
        (1, 0.1, _frame_stats(clipped_channel_fraction=0.10)),
    ]
    profile = LookProfile.from_stats(Look(), per_frame)
    report = LookReport.from_profile(profile, clipped_channel_threshold=0.05)
    assert 1 in report.clipping_frames
    assert 0 not in report.clipping_frames


def test_look_report_flags_bright_frames():
    profile = _make_profile([0.35, 0.8, 0.36])
    report = LookReport.from_profile(profile, bright_threshold=0.7)
    assert report.bright_frames == [1]


def test_look_report_flags_low_contrast_frames():
    per_frame = [
        (0, 0.0, _frame_stats(shadow_floor=10.0, highlight_ceiling=60.0)),
        (1, 0.1, _frame_stats(shadow_floor=40.0, highlight_ceiling=55.0)),
    ]
    profile = LookProfile.from_stats(Look(), per_frame)
    report = LookReport.from_profile(profile, contrast_spread_threshold=20.0)
    assert report.low_contrast_frames == [1]


def test_look_report_no_problems():
    profile = _make_profile([0.35, 0.36, 0.34])
    report = LookReport.from_profile(profile)
    assert not report.dark_frames
    assert not report.bright_frames
    assert not report.clipping_frames
    summary = report.summary()
    assert "No problem frames" in summary


# --- diagnose_scene ---


def test_diagnose_scene_empty():
    scene = Scene()
    warnings = diagnose_scene(scene)
    assert warnings == []


def test_diagnose_scene_high_surface_count():
    shapes = [Circle(center=[float(i), 0], radius=0.1, material_id=MAT_ID) for i in range(25)]
    scene = Scene(materials={MAT_ID: Material()}, shapes=shapes)
    warnings = diagnose_scene(scene)
    assert any("surface count" in w.lower() for w in warnings)


def test_diagnose_scene_transparent_no_absorption():
    glass_mat = Material(transmission=1.0, absorption=0.0)
    shapes = [Circle(center=[float(i) * 0.1, 0], radius=0.1, material_id=GLASS_ID) for i in range(8)]
    scene = Scene(materials={GLASS_ID: glass_mat}, shapes=shapes)
    warnings = diagnose_scene(scene)
    assert any("absorption" in w.lower() for w in warnings)


def test_diagnose_scene_counts_emissive_shapes_as_sources():
    emissive = Material(emission=1.0)
    shapes = [Circle(center=[float(i), 0], radius=0.1, material_id=EMISSIVE_ID) for i in range(11)]
    scene = Scene(materials={EMISSIVE_ID: emissive}, shapes=shapes)
    warnings = diagnose_scene(scene)
    assert any("light/source count" in w.lower() for w in warnings)


def test_diagnose_scene_overlapping_shapes():
    """Many shapes at the same position trigger the overlap warning."""
    shapes = [Circle(center=[0.0, 0.0], radius=0.5, material_id=MAT_ID) for _ in range(6)]
    scene = Scene(materials={MAT_ID: Material()}, shapes=shapes)
    warnings = diagnose_scene(scene)
    assert any("overlapping" in w.lower() for w in warnings)


def test_diagnose_scene_grouped_rotated_arc_uses_precise_bounds():
    scene = Scene(
        shapes=[
            Circle(
                center=[-0.45, -0.45 + 0.09 * i],
                radius=0.02,
                material_id=MAT_ID,
            )
            for i in range(11)
        ],
        groups=[
            Group(
                id="g",
                transform=Transform2D(rotate=math.pi / 6),
                shapes=[
                    Arc(
                        center=[0.0, 0.0],
                        radius=0.5,
                        angle_start=0.0,
                        sweep=0.2,
                        material_id=MAT_ID,
                    )
                ],
            )
        ],
        materials={MAT_ID: Material()},
    )

    warnings = diagnose_scene(scene)

    assert not any("overlapping" in w.lower() for w in warnings)


def test_diagnose_scene_rotated_ellipse_uses_precise_bounds():
    scene = Scene(
        shapes=[
            Ellipse(
                center=[0.0, 0.0],
                semi_a=1.0,
                semi_b=0.2,
                rotation=math.pi / 4,
                material_id=MAT_ID,
            )
        ]
        + [
            Circle(
                center=[0.76, -0.45 + 0.09 * i],
                radius=0.02,
                material_id=MAT_ID,
            )
            for i in range(11)
        ],
        materials={MAT_ID: Material()},
    )

    warnings = diagnose_scene(scene)

    assert not any("overlapping" in w.lower() for w in warnings)


def test_internal_transform_shape_keeps_arc_bounds_tight():
    arc = types_mod.Arc(
        center=[0.0, 0.0],
        radius=1.0,
        angle_start=0.0,
        sweep=math.pi / 2,
        material_id=MAT_ID,
    )

    transformed = _transform_shape(arc, Transform2D(rotate=math.pi / 2))
    bounds = _shape_bounds(transformed)

    assert bounds == pytest.approx((-1.0, 0.0, 0.0, 1.0))


def test_internal_transform_shape_scales_polygon_corner_radii_but_not_smooth_angle():
    polygon = Polygon(
        vertices=[[-1.0, -1.0], [-1.0, 1.0], [1.0, 1.0], [1.0, -1.0]],
        material_id=MAT_ID,
        corner_radius=0.2,
        corner_radii=[0.0, 0.1, 0.2, 0.0],
        join_modes=["auto", "sharp", "smooth", "auto"],
        smooth_angle=1.25,
    )

    transformed = _transform_shape(polygon, Transform2D(scale=[4.0, 1.0]))

    assert transformed.corner_radius == pytest.approx(0.4)
    assert transformed.corner_radii == pytest.approx([0.0, 0.2, 0.4, 0.0])
    assert list(transformed.join_modes) == list(polygon.join_modes)
    assert transformed.smooth_angle == pytest.approx(1.25)


def test_internal_shape_bounds_keep_rotated_ellipse_tight():
    bounds = _shape_bounds(
        Ellipse(
            center=[0.0, 0.0],
            semi_a=1.0,
            semi_b=0.2,
            rotation=math.pi / 4,
            material_id=MAT_ID,
        )
    )

    tight_extent = math.sqrt(0.52)
    assert bounds == pytest.approx((-tight_extent, -tight_extent, tight_extent, tight_extent))
