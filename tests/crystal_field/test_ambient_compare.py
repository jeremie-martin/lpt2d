from __future__ import annotations

import pytest

from examples.python.families.crystal_field.ambient_compare import _with_white_ambient
from examples.python.families.crystal_field.params import (
    AmbientConfig,
    GridConfig,
    LightConfig,
    LookConfig,
    MaterialConfig,
    Params,
    ShapeConfig,
    color_spectrum,
    range_spectrum,
)
from examples.python.families.crystal_field.scene import rendered_light_intensity


def _params() -> Params:
    return Params(
        grid=GridConfig(rows=3, cols=4, spacing=0.30, offset_rows=False, hole_fraction=0.0),
        shape=ShapeConfig(
            kind="polygon",
            size=0.08,
            n_sides=5,
            corner_radius=0.0,
            rotation=None,
        ),
        material=MaterialConfig(
            outcome="black_diffuse",
            albedo=0.85,
            fill=0.0,
            color_names=[],
        ),
        light=LightConfig(
            n_lights=1,
            path_style="channel",
            n_waypoints=8,
            ambient=AmbientConfig(
                style="corners",
                intensity=0.3,
                spectrum=color_spectrum((0.0, 0.0, 1.0), white_mix=0.25),
            ),
            speed=0.12,
            moving_intensity=0.7,
            spectrum=range_spectrum(550.0, 700.0),
        ),
        look=LookConfig(exposure=-5.0),
        build_seed=123,
    )


def test_with_white_ambient_preserves_rendered_intensity():
    original = _params()
    white = _with_white_ambient(original)

    assert white.light.ambient.spectrum.type == "range"
    assert white.light.ambient.spectrum.wavelength_min == 380.0
    assert white.light.ambient.spectrum.wavelength_max == 780.0
    assert rendered_light_intensity(
        white.light.ambient.intensity,
        white.light.ambient.spectrum,
    ) == pytest.approx(
        rendered_light_intensity(
            original.light.ambient.intensity,
            original.light.ambient.spectrum,
        )
    )
    assert white.light.ambient.intensity != pytest.approx(original.light.ambient.intensity)
