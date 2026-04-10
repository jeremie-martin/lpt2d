"""LookConfig JSON round-trip: save Params, reload, confirm look dims flow
through to the renderer.

This pins down the plumbing from ``Params.look`` → ``scene.py`` → ``anim.Look``
so that regressions in the LookConfig wiring are caught immediately.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from anim.params import params_from_dict
from examples.python.families.crystal_field.params import (
    AmbientConfig,
    GridConfig,
    LightConfig,
    LookConfig,
    MaterialConfig,
    Params,
    ShapeConfig,
)
from examples.python.families.crystal_field.scene import build


def _params_with_populated_look() -> Params:
    """Baseline Params with every LookConfig dim set to a non-default value."""
    grid = GridConfig(rows=4, cols=5, spacing=0.28, offset_rows=False, hole_fraction=0.0)
    shape = ShapeConfig(
        kind="circle",
        size=0.084,
        n_sides=0,
        corner_radius=0.0,
        rotation=None,
    )
    material = MaterialConfig(
        style="glass",
        ior=1.5,
        cauchy_b=18_000.0,
        absorption=1.0,
        fill=0.08,
        n_color_groups=0,
        diffuse_style="dark",
        color_names=[],
        albedo=0.8,
    )
    light = LightConfig(
        n_lights=1,
        path_style="channel",
        n_waypoints=8,
        ambient=AmbientConfig(style="corners", intensity=0.25),
        speed=0.12,
        moving_intensity=0.8,
        wavelength_min=380.0,
        wavelength_max=780.0,
    )
    # Every field set to something non-default so the round-trip catches drops.
    look = LookConfig(
        exposure=-4.2,
        gamma=1.7,
        contrast=1.03,
        white_point=0.6,
        temperature=0.15,
        vignette=0.12,
        vignette_radius=1.6,
        chromatic_aberration=0.0,  # must stay 0 — glass material
    )
    return Params(grid=grid, shape=shape, material=material, light=light, look=look, build_seed=7)


def test_look_config_dict_roundtrip():
    """asdict → json → parse → Params preserves every LookConfig field."""
    p = _params_with_populated_look()
    raw = json.loads(json.dumps(asdict(p)))
    restored = params_from_dict(Params, raw)

    assert restored.look == p.look
    assert restored.material.albedo == p.material.albedo
    assert restored.light.moving_intensity == p.light.moving_intensity


def test_look_config_flows_into_anim_look():
    """Params.look → scene.build → Frame.look must carry every field through.

    We call the animate callback directly (no render) and inspect the
    returned Frame's Look to confirm each value lands.
    """
    from anim import Look, Timeline

    p = _params_with_populated_look()
    animate = build(p)
    tl = Timeline(1.0, fps=1)
    frame = animate(tl.context_at(0))
    assert isinstance(frame.look, Look), f"expected Look, got {type(frame.look)}"
    look: Look = frame.look

    assert abs(look.exposure - p.look.exposure) < 1e-6
    assert abs(look.gamma - p.look.gamma) < 1e-6
    assert abs(look.contrast - p.look.contrast) < 1e-6
    assert abs(look.white_point - p.look.white_point) < 1e-6
    assert abs(look.temperature - p.look.temperature) < 1e-6
    assert abs(look.vignette - p.look.vignette) < 1e-6
    assert abs(look.vignette_radius - p.look.vignette_radius) < 1e-6
    assert abs(look.chromatic_aberration - p.look.chromatic_aberration) < 1e-6
