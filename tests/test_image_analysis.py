"""Session-integrated frame analysis tests.

The public path is `RenderSession.render_shot(..., analyze=True)`, which
renders the authored camera, reads the final RGB8 image, and runs the shared
CPU frame-analysis core. These tests cover the end-to-end binding surface.
"""

from __future__ import annotations

import _lpt2d
import pytest
from anim.types import (
    Canvas,
    Circle,
    Material,
    PointLight,
    Scene,
    Shot,
    Timeline,
    TraceDefaults,
)
from anim.renderer import render_frame


def _probe_shot() -> Shot:
    return Shot(
        canvas=Canvas(width=128, height=128),
        trace=TraceDefaults(rays=50_000, batch=50_000, depth=4),
    )


def test_render_frame_no_analyze_leaves_analysis_zeroed():
    """Default path: analyze=False → rr.analysis is present but empty."""
    scene = Scene(
        materials={"emit": Material(emission=2.0)},
        shapes=[Circle(center=[0.0, 0.0], radius=0.2, material_id="emit")],
    )

    def animate(_ctx):
        return scene

    rr = render_frame(animate, Timeline(1.0, fps=1), settings=_probe_shot())
    # metrics is still computed cheaply, analysis is not.
    assert rr.metrics.width == 128
    assert rr.metrics.height == 128
    # Light list is empty when analyze=False — the expensive per-light
    # analysis is not dispatched at all.
    assert list(rr.analysis.lights) == []


def test_render_frame_analyze_true_populates_luminance_color_lights():
    """analyze=True runs frame analysis and populates every sub-struct."""
    scene = Scene(
        lights=[PointLight(id="light_0", position=[0.0, 0.0], intensity=1.0,
                           wavelength_min=550.0, wavelength_max=560.0)],
        materials={"glass": Material(ior=1.5, transmission=0.8)},
        shapes=[Circle(center=[0.0, 0.0], radius=0.15, material_id="glass")],
    )

    def animate(_ctx):
        return scene

    rr = render_frame(animate, Timeline(1.0, fps=1),
                      settings=_probe_shot(), analyze=True)

    # Luminance — the rr.metrics alias must match .analysis.luminance exactly.
    assert rr.metrics.mean == rr.analysis.luminance.mean
    assert rr.metrics.median == rr.analysis.luminance.median
    assert rr.metrics.highlight_ceiling == rr.analysis.luminance.highlight_ceiling
    assert (
        rr.metrics.clipped_channel_fraction
        == rr.analysis.luminance.clipped_channel_fraction
    )
    assert rr.analysis.luminance.width == 128
    assert rr.analysis.luminance.height == 128

    # Color — any real render produces at least some chromatic content
    # from the spectrum → RGB conversion, so colored_fraction >= 0.
    assert rr.analysis.color.colored_fraction >= 0.0
    assert rr.analysis.color.richness >= 0.0

    # Lights — one PointLight means exactly one measured appearance record.
    assert len(list(rr.analysis.lights)) == 1
    light = list(rr.analysis.lights)[0]
    assert light.id == "light_0"
    assert light.radius_ratio >= 0.0
    assert light.radius_candidate_sector_consensus_ratio >= 0.0
    assert not hasattr(light, "radius_candidate_knee_ratio")
    assert not hasattr(light, "radius_candidate_robust_sector_edge_ratio")
    assert not hasattr(light, "radius_candidate_outer_shoulder_ratio")
    assert light.coverage_fraction >= 0.0


def test_luminance_stats_default_constructible():
    """anim/light_analysis.py uses LuminanceStats() as a zero sentinel."""
    s = _lpt2d.LuminanceStats()
    assert s.mean == 0.0
    assert s.median == 0.0
    assert s.width == 0
    assert s.height == 0


def test_point_light_params_expose_radius_signal_gamma():
    params = _lpt2d.PointLightAppearanceParams()
    assert params.radius_signal_gamma == pytest.approx(0.5)
    params.radius_signal_gamma = 0.3
    assert params.radius_signal_gamma == pytest.approx(0.3)
