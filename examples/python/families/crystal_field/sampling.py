"""Parameter generation for crystal_field.

The sampler picks a visual mode first, then derives everything else from it.
Each decision is transparent and follows logically from the previous one.

Visual modes
------------
- **glass**: transparent circles refracting light into caustic webs.
  Single slow light preferred.  No mixed object colours (caustics provide
  the visual interest).  Optionally a warm-coloured light.

- **shadow**: opaque polygons casting shadow fans.  Rounded corners always.
  One or two lights.  Colour comes from fill (colored_fill) or from a
  warm moving light (dark style).  Metallic-rough is a third option that
  gives soft reflections.

Grid, exposure, ambient, and speed are straightforward and independent of
the mode — just pick reasonable values.

Look dims (gamma, contrast, white_point, temperature, vignette, chromatic
aberration) are drawn in ``_random_look`` alongside the structural params.
Some are conditionally suppressed based on the already-drawn material and
light colour (see ``_random_look``).
"""

from __future__ import annotations

import math
import random

from .params import (
    PALETTE,
    AmbientConfig,
    GridConfig,
    LightConfig,
    LookConfig,
    MaterialConfig,
    Params,
    RotationConfig,
    ShapeConfig,
)

# ── Grid ─────────────────────────────────────────────────────────────────


def _random_grid(rng: random.Random) -> GridConfig:
    spacing = rng.uniform(0.20, 0.32)

    # Rows: Gaussian-like centered on 5, min 3, max 8.
    rows = max(3, min(8, round(rng.gauss(5.0, 1.2))))

    # Cols: enough to fill the frame but leave ≥15% margin on each side.
    # Mirror box is 3.2 wide; 15% margin each side = 70% usable = 2.24 units.
    max_cols = max(3, int(2.24 / spacing))
    cols = rng.randint(4, max_cols)

    offset_rows = rng.choice([True, False])
    hole_fraction = 0.0 if rng.random() < 0.75 else rng.uniform(0.05, 0.15)
    return GridConfig(
        rows=rows, cols=cols, spacing=spacing, offset_rows=offset_rows, hole_fraction=hole_fraction
    )


# ── Shape ────────────────────────────────────────────────────────────────


def _glass_shape(rng: random.Random, spacing: float) -> ShapeConfig:
    """Glass mode: always circles."""
    size = spacing * rng.uniform(0.25, 0.38)
    return ShapeConfig(kind="circle", size=size, n_sides=0, corner_radius=0.0, rotation=None)


def _shadow_shape(rng: random.Random, spacing: float) -> ShapeConfig:
    """Shadow mode: always polygons with rounded corners."""
    n_sides = rng.choice([3, 4, 5, 6])
    size = spacing * rng.uniform(0.25, 0.40)
    corner_radius = size * rng.uniform(0.12, 0.35)

    rotation: RotationConfig | None = None
    if rng.random() < 0.65:
        base_angle = rng.uniform(0, 2 * math.pi / n_sides)
        jitter = rng.uniform(0.05, math.pi / n_sides) if rng.random() < 0.35 else 0.0
        rotation = RotationConfig(base_angle=base_angle, jitter=jitter)

    return ShapeConfig(
        kind="polygon", size=size, n_sides=n_sides, corner_radius=corner_radius, rotation=rotation
    )


# ── Material ─────────────────────────────────────────────────────────────


def _glass_material(rng: random.Random) -> MaterialConfig:
    """Glass: moderate IOR, no object colours (caustics are the colour)."""
    return MaterialConfig(
        style="glass",
        ior=rng.uniform(1.40, 1.55),
        cauchy_b=rng.uniform(15_000, 25_000),
        absorption=rng.uniform(0.3, 2.0),
        fill=rng.uniform(0.05, 0.13),
        n_color_groups=0,
        diffuse_style="dark",
        color_names=[],
        albedo=0.8,
    )


def _shadow_material(rng: random.Random) -> MaterialConfig:
    """Shadow: one of three sub-styles, each with its own colour logic."""
    sub = rng.choices(["dark", "colored_fill", "metallic_rough"], weights=[3, 5, 2])[0]

    if sub == "dark":
        return MaterialConfig(
            style="diffuse",
            ior=1.5,
            cauchy_b=0.0,
            absorption=0.0,
            fill=0.0,
            n_color_groups=0,
            diffuse_style="dark",
            color_names=[],
            albedo=0.15,
        )

    if sub == "colored_fill":
        colors = rng.sample(PALETTE, 1)
        return MaterialConfig(
            style="diffuse",
            ior=1.5,
            cauchy_b=0.0,
            absorption=0.0,
            fill=rng.uniform(0.12, 0.22),
            n_color_groups=1,
            diffuse_style="colored_fill",
            color_names=colors,
            albedo=rng.uniform(0.7, 1.0),
        )

    colors = rng.sample(PALETTE, 1)
    return MaterialConfig(
        style="diffuse",
        ior=1.5,
        cauchy_b=0.0,
        absorption=0.0,
        fill=rng.uniform(0.04, 0.12),
        n_color_groups=1,
        diffuse_style="metallic_rough",
        color_names=colors,
        albedo=rng.uniform(0.7, 1.0),
    )


# ── Light ────────────────────────────────────────────────────────────────

# Warm spectral ranges for coloured moving lights.
_WARM_SPECTRA = [
    (550.0, 700.0),  # orange
    (515.0, 700.0),  # yellow-orange
    (570.0, 700.0),  # deep orange
    (500.0, 620.0),  # warm green-yellow
]


def _random_light(
    rng: random.Random,
    mode: str,
    has_object_color: bool,
) -> LightConfig:
    # Number of lights: glass prefers 1; shadow allows 1-2.
    if mode == "glass":
        n_lights = rng.choices([1, 2], weights=[7, 3])[0]
    else:
        n_lights = rng.choices([1, 2, 3], weights=[5, 4, 1])[0]

    # Path style.
    path_style = rng.choices(
        ["waypoints", "random_walk", "vertical_drift", "drift", "channel"],
        weights=[2, 1, 1, 3, 3],
    )[0]

    n_waypoints = rng.randint(5, 10)

    # Speed: base 0.08–0.20, slower with more lights.
    speed_max = 0.20 if n_lights == 1 else 0.14
    speed = rng.uniform(0.08, speed_max)

    amb_style = rng.choices(["corners", "sides"], weights=[8, 2])[0]
    amb_intensity = rng.uniform(0.05, 1.2)
    ambient = AmbientConfig(style=amb_style, intensity=amb_intensity)

    moving_intensity = rng.uniform(0.15, 1.5)

    # Light colour: warm tint when the scene has no object colour.
    # 70% of achromatic scenes get coloured light to avoid too much gray.
    wl_min, wl_max = 380.0, 780.0
    if not has_object_color and rng.random() < 0.70:
        wl_min, wl_max = rng.choice(_WARM_SPECTRA)

    return LightConfig(
        n_lights=n_lights,
        path_style=path_style,
        n_waypoints=n_waypoints,
        ambient=ambient,
        speed=speed,
        moving_intensity=moving_intensity,
        wavelength_min=wl_min,
        wavelength_max=wl_max,
    )


# ── Look ─────────────────────────────────────────────────────────────────


def _random_look(
    rng: random.Random,
    material: MaterialConfig,
    light: LightConfig,
) -> LookConfig:
    """Draw a LookConfig alongside the structural params.

    Positive temperature on warm light and chromatic aberration on glass are
    suppressed here (and also hard-rejected in ``check.py``) — the first
    pushes warm scenes into red mush, the second confuses refractive scenes.
    """
    exposure = rng.uniform(-6.5, -2.5)
    gamma = rng.uniform(1.0, 2.2)
    contrast = rng.uniform(1.00, 1.05)
    white_point = rng.uniform(0.3, 1.0)

    # Temperature: 50% off, 50% uniform(0.0, 0.55) — but forbidden on warm light.
    if rng.random() < 0.5 or light.wavelength_min >= 500.0:
        temperature = 0.0
    else:
        temperature = rng.uniform(0.0, 0.55)

    # Vignette: 50% off (strength 0, radius default), 50% subtle fade.
    if rng.random() < 0.5:
        vignette = 0.0
        vignette_radius = 0.7
    else:
        vignette = rng.uniform(0.0, 0.2)
        vignette_radius = rng.uniform(1.5, 1.8)

    # Chromatic aberration: 50% off, 50% subtle — forbidden on glass.
    if rng.random() < 0.5 or material.style == "glass":
        chromatic_aberration = 0.0
    else:
        chromatic_aberration = rng.uniform(0.0, 0.006)

    return LookConfig(
        exposure=exposure,
        gamma=gamma,
        contrast=contrast,
        white_point=white_point,
        temperature=temperature,
        vignette=vignette,
        vignette_radius=vignette_radius,
        chromatic_aberration=chromatic_aberration,
    )


# ── Top-level sampler ────────────────────────────────────────────────────


def sample(rng: random.Random) -> Params:
    """Generate one random crystal_field variant.

    Picks a visual mode (glass or shadow), then derives grid, shape,
    material, light, and look from it.  Every scene gets ambient lights.

    Look dims (exposure, gamma, contrast, etc.) are drawn in one shot
    alongside the structural params — there is no inner search loop.
    ``Family.search`` retries the whole sample on rejection.
    """
    # 1. Visual mode — equal chance.
    mode = rng.choice(["glass", "shadow"])

    # 2. Grid — same for both modes.
    grid = _random_grid(rng)

    # 3. Shape — mode-specific.
    if mode == "glass":
        shape = _glass_shape(rng, grid.spacing)
    else:
        shape = _shadow_shape(rng, grid.spacing)

    # 4. Material — mode-specific.
    if mode == "glass":
        material = _glass_material(rng)
    else:
        material = _shadow_material(rng)

    # 5. Light — aware of mode and whether objects have colour.
    has_object_color = material.n_color_groups > 0
    light = _random_light(rng, mode, has_object_color)

    # 6. Look — draws exposure and all the post-process dials together,
    #    with conditional suppression based on material and light colour.
    look = _random_look(rng, material, light)

    build_seed = rng.randint(0, 2**32)

    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=light,
        look=look,
        build_seed=build_seed,
    )
