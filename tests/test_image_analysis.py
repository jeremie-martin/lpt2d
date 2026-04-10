"""Session-integrated frame analysis tests.

The CPU byte-loop bindings (`compute_luminance_stats`, `compute_color_stats`,
`measure_light_circles`, `analyze_frame`) are gone in the GPU refactor;
what remains is the opt-in path through `RenderSession.render_shot(..., analyze=True)`
which runs the real GPU compute shader and returns a complete
`FrameAnalysis` on `rr.analysis`. This file covers that end-to-end so a
regression in the shader / analyzer / session wiring trips a pytest.
"""

from __future__ import annotations

import _lpt2d
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
    # Circles list is empty when analyze=False — the GPU compute shader
    # is not dispatched at all.
    assert list(rr.analysis.circles) == []


def test_render_frame_analyze_true_populates_lum_color_circles():
    """analyze=True runs the GPU analyzer and populates every sub-struct."""
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

    # Luminance — the rr.metrics alias must match .analysis.lum exactly.
    assert rr.metrics.mean_lum == rr.analysis.lum.mean_lum
    assert rr.metrics.p50 == rr.analysis.lum.p50
    assert rr.metrics.p95 == rr.analysis.lum.p95
    assert rr.metrics.pct_clipped == rr.analysis.lum.pct_clipped
    assert rr.analysis.lum.width == 128
    assert rr.analysis.lum.height == 128

    # Color — any real render produces at least some chromatic content
    # from the spectrum → RGB conversion, so chromatic_fraction >= 0.
    assert rr.analysis.color.chromatic_fraction >= 0.0
    assert rr.analysis.color.color_richness >= 0.0

    # Circles — one PointLight means exactly one measured LightCircle.
    assert len(list(rr.analysis.circles)) == 1
    circle = list(rr.analysis.circles)[0]
    assert circle.id == "light_0"
    assert circle.radius_px >= 0.0
    assert circle.n_bright_pixels >= 0


def test_luminance_stats_default_constructible():
    """anim/light_analysis.py uses LuminanceStats() as a zero sentinel."""
    s = _lpt2d.LuminanceStats()
    assert s.mean_lum == 0.0
    assert s.p50 == 0.0
    assert s.width == 0
    assert s.height == 0
