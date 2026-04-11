"""Parameter generation for crystal_field.

Top-level ``sample()`` picks one of **five peer outcomes** with equal
probability (20% each) and draws every parameter for that outcome
inline.  There is no umbrella "diffuse" category and no shared constants
hoisted across outcomes — every range is spelled out literally in the
branch where it is used, even when branches happen to agree on the same
numbers.  This is deliberate: see ``analysis.md`` and
``feedback_explicit_per_branch`` for the reasoning.

The five peer outcomes:

1. ``glass``           — refractive spheres, dispersion-aware IOR
2. ``black_diffuse``   — high-albedo diffuse, fill = 0 (dark silhouettes)
3. ``gray_diffuse``    — high-albedo diffuse, fill ∈ [0.12, 0.22], no color
4. ``colored_diffuse`` — high-albedo diffuse, fill ∈ [0.12, 0.22], strictly 1 color
5. ``brushed_metal``   — metallic+roughness, fill ∈ [0.066, 0.15], 0/1/2 colors

Look dims (gamma, contrast, white_point, temperature, highlights, shadows,
chromatic aberration) are drawn by ``_random_look`` alongside the structural
params, with conditional suppression based on the already-drawn material and
light colour. Vignette is temporarily disabled because it corrupts the frame
analysis thresholds.
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
    range_spectrum,
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
    """Glass outcome: always circles."""
    size = spacing * rng.uniform(0.25, 0.38)
    return ShapeConfig(kind="circle", size=size, n_sides=0, corner_radius=0.0, rotation=None)


def _polygon_shape(rng: random.Random, spacing: float) -> ShapeConfig:
    """Non-glass outcomes (black / gray / colored diffuse + brushed metal): rounded polygons."""
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


# ── Materials: one function per outcome ─────────────────────────────────
#
# Every range below is defined **inline, per outcome**.  The fact that
# several branches happen to draw albedo from [0.7, 1.0] is intentional
# duplication: each outcome is its own self-contained decision and the
# values are written where they're used.  Do not hoist.


def _glass_material(rng: random.Random) -> MaterialConfig:
    """Glass — refractive spheres.

    Dispersion-aware IOR range (see ``analysis.md``).  The analysis gives
    one anchor point + one exchange rate:

    - At dispersion = 20 000, the good IOR range is [1.40, 1.55].
    - 25 000 dispersion ≈ 0.1 IOR in terms of caustic effect.

    Treat caustic prominence as a linear function of an effective IOR:

        effective_IOR = IOR + dispersion / 250_000

    (because 25 000 / 250 000 = 0.1 — the stated exchange rate).  The
    anchor point pins the "good" range in effective-IOR space:

        effective ∈ [1.40 + 20_000/250_000, 1.55 + 20_000/250_000]
                  = [1.48, 1.63]

    For any drawn dispersion D, back out the actual IOR range:

        ior ∈ [1.48 − D/250_000, 1.63 − D/250_000]

    Sanity check endpoints:
        D =      0  → [1.48, 1.63]
        D = 20 000  → [1.40, 1.55]   ← matches analysis anchor
        D = 30 000  → [1.36, 1.51]

    Albedo is drawn from [0.7, 1.0] to keep the per-branch rule uniform,
    but is visually irrelevant for glass (transmission = 1 inside
    ``anim.glass()``).
    """
    cauchy_b = rng.uniform(0.0, 30_000.0)
    shift = cauchy_b / 250_000.0
    ior = rng.uniform(1.48 - shift, 1.63 - shift)
    return MaterialConfig(
        outcome="glass",
        albedo=rng.uniform(0.7, 1.0),  # irrelevant for glass — see docstring
        fill=rng.uniform(0.05, 0.13),
        ior=ior,
        cauchy_b=cauchy_b,
        absorption=rng.uniform(0.3, 2.0),
        color_names=[],
    )


def _black_diffuse_material(rng: random.Random) -> MaterialConfig:
    """Black diffuse — high albedo but ``fill = 0`` reads as dark silhouettes.

    See ``analysis.md``: the black look comes from ``fill = 0``, not from
    low albedo.  High albedo keeps the surface smooth under the moving
    lights (low-albedo diffuse looks like wet wood).
    """
    return MaterialConfig(
        outcome="black_diffuse",
        albedo=rng.uniform(0.7, 1.0),
        fill=0.0,
        color_names=[],
    )


def _gray_diffuse_material(rng: random.Random) -> MaterialConfig:
    """Gray diffuse — high albedo, visible fill, no color.

    A shade of gray: the fill makes the interior show through as a neutral
    tint, but no palette color is applied.  See ``analysis.md``.
    """
    return MaterialConfig(
        outcome="gray_diffuse",
        albedo=rng.uniform(0.7, 1.0),
        fill=rng.uniform(0.12, 0.22),
        color_names=[],
    )


def _colored_diffuse_material(rng: random.Random) -> MaterialConfig:
    """Colored diffuse — high albedo, visible fill, **exactly one** palette color.

    Strictly one color per scene for now; multiple-color diffuse is
    deferred until we understand the interaction with fill and lighting.
    See ``analysis.md``.
    """
    return MaterialConfig(
        outcome="colored_diffuse",
        albedo=rng.uniform(0.7, 1.0),
        fill=rng.uniform(0.12, 0.22),
        color_names=[rng.choice(PALETTE)],
    )


def _brushed_metal_material(rng: random.Random) -> MaterialConfig:
    """Brushed metal — metallic+roughness, narrower fill, 4 color sub-cases at 25%.

    Fill range is narrower than the diffuse outcomes on purpose (see
    ``analysis.md``).

    Internal color distribution (25% each):
      - no color   : ``color_names = []``                      → single uncolored material
      - one color  : ``color_names = [name]``                  → every object the same color
      - mixed      : ``color_names = [name, None]``            → half colored, half uncolored
      - two colors : ``color_names = [name_a, name_b]``        → half color A, half color B

    The fill value is drawn **once** and applied to every material in the
    scene (including the uncolored slot in the mixed case).  This is the
    "same fill per scene" rule — see ``analysis.md``.
    """
    albedo = rng.uniform(0.7, 1.0)
    fill = rng.uniform(0.066, 0.15)
    ior = 1.0 if rng.random() < 0.5 else rng.uniform(1.0, 1.4)
    wall_metallic = rng.uniform(0.66, 1.0)

    sub = rng.choice(["no_color", "one_color", "mixed", "two_colors"])
    if sub == "no_color":
        color_names: list[str | None] = []
    elif sub == "one_color":
        color_names = [rng.choice(PALETTE)]
    elif sub == "mixed":
        color_names = [rng.choice(PALETTE), None]
    else:  # "two_colors"
        a, b = rng.sample(PALETTE, 2)
        color_names = [a, b]

    return MaterialConfig(
        outcome="brushed_metal",
        albedo=albedo,
        fill=fill,
        ior=ior,
        color_names=color_names,
        wall_metallic=wall_metallic,
    )


# ── Light ────────────────────────────────────────────────────────────────

# Warm spectral ranges for coloured moving lights.
_WARM_SPECTRA = [
    (550.0, 700.0),  # orange
    (570.0, 700.0),  # deep orange
]


def _random_light(
    rng: random.Random,
    is_glass: bool,
    has_object_color: bool,
) -> LightConfig:
    # Number of lights: glass prefers 1; non-glass allows 1-3.
    if is_glass:
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
        spectrum=range_spectrum(wl_min, wl_max),
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
    warm_light = (
        light.spectrum.type == "range"
        and light.spectrum.wavelength_min >= 500.0
    ) or (
        light.spectrum.type == "color"
        and light.spectrum.linear_rgb != [1.0, 1.0, 1.0]
    )
    if rng.random() < 0.5 or warm_light:
        temperature = 0.0
    else:
        temperature = rng.uniform(0.0, 0.55)

    highlights = rng.uniform(-0.22, 0.22)
    shadows = rng.uniform(-0.22, 0.22)

    # Vignette is temporarily disabled because it biases frame-analysis metrics.
    vignette = 0.0
    vignette_radius = 0.7

    # Chromatic aberration: 50% off, 50% subtle — forbidden on glass.
    if rng.random() < 0.5 or material.outcome == "glass":
        chromatic_aberration = 0.0
    else:
        chromatic_aberration = rng.uniform(0.0, 0.006)

    return LookConfig(
        exposure=exposure,
        gamma=gamma,
        contrast=contrast,
        white_point=white_point,
        temperature=temperature,
        highlights=highlights,
        shadows=shadows,
        vignette=vignette,
        vignette_radius=vignette_radius,
        chromatic_aberration=chromatic_aberration,
    )


# ── Top-level sampler ────────────────────────────────────────────────────


OUTCOMES: tuple[str, ...] = (
    "glass",
    "black_diffuse",
    "gray_diffuse",
    "colored_diffuse",
    "brushed_metal",
)


def sample(rng: random.Random) -> Params:
    """Generate one random crystal_field variant.

    Picks one of the five peer outcomes with equal probability (20% each)
    and draws grid, shape, material, light, and look for it in one shot.
    ``Family.search`` retries the whole sample on rejection — there is no
    inner search loop.

    The even-ish 20% distribution is a provisional default.  Once the
    catalog walk shows what actually looks good across all five outcomes
    (with every shape / grid / light-colour combination), we revisit.
    """
    outcome = rng.choice(OUTCOMES)

    grid = _random_grid(rng)

    if outcome == "glass":
        shape = _glass_shape(rng, grid.spacing)
        material = _glass_material(rng)
    elif outcome == "black_diffuse":
        shape = _polygon_shape(rng, grid.spacing)
        material = _black_diffuse_material(rng)
    elif outcome == "gray_diffuse":
        shape = _polygon_shape(rng, grid.spacing)
        material = _gray_diffuse_material(rng)
    elif outcome == "colored_diffuse":
        shape = _polygon_shape(rng, grid.spacing)
        material = _colored_diffuse_material(rng)
    else:  # "brushed_metal"
        shape = _polygon_shape(rng, grid.spacing)
        material = _brushed_metal_material(rng)

    has_object_color = any(name is not None for name in material.color_names)
    light = _random_light(rng, is_glass=(outcome == "glass"), has_object_color=has_object_color)
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
