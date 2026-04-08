"""Smooth-shading tests for polygon join modes on a thick-arc mirror.

A collimated projector beam hits a thick-arc (half-circle "C" shape) mirror.
With flat/sharp shading the reflected light fans into distinct stripes (zebra
pattern) because each polygon facet reflects at a slightly different angle.
With smooth shading the reflected fan is a continuous gradient.

Scenarios:
  - all_sharp × {convex, concave}  → must produce faceted stripes
  - all_smooth × {convex, concave} → must produce a smooth fan
  - auto × {convex, concave}       → should match all_smooth

The concave side is where the beam enters the opening of the "C" and reflects
off the inner surface.  The convex side is the opposite: the beam hits the
outer surface.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import _lpt2d
from anim.builders import mirror_box, thick_arc
from anim.types import (
    Camera2D,
    Canvas,
    Look,
    Material,
    PolygonJoinMode,
    ProjectorLight,
    Scene,
    Shot,
    TraceDefaults,
)

W, H = 480, 270
RAYS = 1_000_000
FACETED_THRESHOLD = 1.3  # mean bright-runs above this → faceted stripes

MATERIALS = {
    "mirror": Material(metallic=1.0, albedo=1.0),
    "absorb": Material(albedo=0.0),
}

CAMERA = Camera2D(bounds=[-1.2, -0.675, 1.2, 0.675])


def _make_arc(join_mode: str) -> _lpt2d.Polygon:
    """Build a thick-arc polygon with the given join mode override.

    join_mode: "all_sharp", "all_smooth", or "auto"
    """
    shapes = thick_arc(
        center=(0, 0),
        radius=0.5,
        thickness=0.15,
        angle_start=math.pi / 2,
        sweep=math.pi,
        material_id="mirror",
        smooth_angle=1.0,
    )
    poly = shapes[0]
    n = len(poly.vertices)
    if join_mode == "all_sharp":
        poly.join_modes = [PolygonJoinMode.sharp] * n
    elif join_mode == "all_smooth":
        poly.join_modes = [PolygonJoinMode.smooth] * n
    # "auto" keeps the default from thick_arc (auto on curve, sharp on caps)
    return poly


def _render(poly: _lpt2d.Polygon, beam_pos: tuple, beam_dir: tuple) -> np.ndarray:
    """Render the scene and return an (H, W, 3) uint8 pixel array."""
    scene = Scene(
        materials=MATERIALS,
        shapes=[*mirror_box(1.2, 0.675, "absorb"), poly],
        lights=[
            ProjectorLight(
                id="beam",
                position=beam_pos,
                direction=beam_dir,
                source_radius=0.05,
                spread=0.0,
                intensity=1.0,
            )
        ],
    )
    shot = Shot(
        name="test_smooth_shading",
        scene=scene,
        camera=CAMERA,
        canvas=Canvas(width=W, height=H),
        look=Look(
            exposure=-4.5,
            contrast=1.2,
            gamma=2.0,
            tonemap="reinhardx",
            white_point=0.5,
            normalize="rays",
            ambient=0.0,
        ),
        trace=TraceDefaults(rays=RAYS, batch=200_000, depth=12, seed_mode="deterministic"),
    )
    session = _lpt2d.RenderSession(W, H)
    result = session.render_shot(shot.to_cpp())
    return np.frombuffer(result.pixels, dtype=np.uint8).reshape(H, W, 3)


def _count_bright_runs(profile: np.ndarray, threshold: float = 8.0) -> int:
    """Count separate bright segments in a 1-D brightness profile."""
    above = profile > threshold
    return int(np.sum(np.diff(above.astype(np.int8), prepend=0) > 0))


def _faceting_metric(pixels: np.ndarray, side: str) -> float:
    """Mean number of bright runs per column in the reflection fan.

    A value near 1.0 means a single smooth fan; values above ~1.3 indicate
    visible faceted stripes ("zebra" pattern).
    """
    lum = pixels.mean(axis=2).astype(float)

    if side == "concave":
        col_start, col_end = 300, 460
    else:
        col_start, col_end = 20, 180

    margin = 20
    beam_half = 25
    rows = list(range(margin, H // 2 - beam_half)) + list(range(H // 2 + beam_half, H - margin))

    run_counts = []
    for col in range(col_start, col_end, 3):
        runs = _count_bright_runs(lum[rows, col])
        if runs > 0:
            run_counts.append(runs)

    if not run_counts:
        return 0.0
    return float(np.mean(run_counts))


# -- Test matrix ---------------------------------------------------------------
#
#   (join_mode,    side,      beam_pos,     beam_dir)

_CONCAVE = ("concave", (0.9, 0.0), (-1.0, 0.0))
_CONVEX = ("convex", (-0.9, 0.0), (1.0, 0.0))

FACETED_CASES = [
    pytest.param("all_sharp", *_CONCAVE, id="sharp-concave"),
    pytest.param("all_sharp", *_CONVEX, id="sharp-convex"),
]

SMOOTH_CASES = [
    pytest.param("all_smooth", *_CONCAVE, id="smooth-concave"),
    pytest.param("all_smooth", *_CONVEX, id="smooth-convex"),
    pytest.param("auto", *_CONVEX, id="auto-convex"),
    pytest.param("auto", *_CONCAVE, id="auto-concave"),
]


@pytest.mark.parametrize(("join_mode", "side", "beam_pos", "beam_dir"), FACETED_CASES)
def test_faceted_reflection(join_mode: str, side: str, beam_pos: tuple, beam_dir: tuple):
    """Sharp joins must produce visible faceted stripes in the reflection fan."""
    poly = _make_arc(join_mode)
    pixels = _render(poly, beam_pos, beam_dir)
    metric = _faceting_metric(pixels, side)
    assert metric > FACETED_THRESHOLD, (
        f"Expected faceted stripes (>{FACETED_THRESHOLD}), got {metric:.2f}"
    )


@pytest.mark.parametrize(("join_mode", "side", "beam_pos", "beam_dir"), SMOOTH_CASES)
def test_smooth_reflection(join_mode: str, side: str, beam_pos: tuple, beam_dir: tuple):
    """Smooth and auto joins must produce a continuous reflection fan."""
    poly = _make_arc(join_mode)
    pixels = _render(poly, beam_pos, beam_dir)
    metric = _faceting_metric(pixels, side)
    assert metric <= FACETED_THRESHOLD, (
        f"Expected smooth fan (<={FACETED_THRESHOLD}), got {metric:.2f}"
    )
