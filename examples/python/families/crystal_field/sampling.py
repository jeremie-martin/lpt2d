"""Parameter generation for crystal_field.

Top-level ``sample()`` currently uses ``DEFAULT_SAMPLER_POLICY`` to pick one
of **four active peer outcomes** with equal probability (25% each), then
draws grid, shape, material, light, and look parameters. Glass support is
intentionally still present below, but temporarily excluded from the active
free sampler while the non-glass outcomes are tuned from measured probe data.

The active peer outcomes:

1. ``black_diffuse``   — high-albedo diffuse, fill = 0 (dark silhouettes)
2. ``gray_diffuse``    — high-albedo diffuse, fill ∈ [0.15, 0.3], no color
3. ``colored_diffuse`` — high-albedo diffuse, fill ∈ [0.12, 0.22], strictly 1 color
4. ``brushed_metal``   — metallic+roughness, fill ∈ [0.066, 0.15], 0/1/2 colors

The policy object owns the broad tunable ranges and weighted choices. Material
branches remain normal Python functions because their rules are local and
outcome-specific. Look dims (gamma, contrast, white_point, temperature,
highlights, shadows, chromatic aberration) are drawn by ``_random_look``
alongside the structural params, with conditional suppression based on the
already-drawn material and light colour. Saturation is sampled directly as
a replayable color-strength dial. Vignette is temporarily disabled because
it corrupts the frame analysis thresholds.
"""

from __future__ import annotations

import colorsys
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from anim import LightSpectrum

from .params import (
    PALETTE,
    AmbientConfig,
    GridConfig,
    LightConfig,
    LightSpectrumConfig,
    LookConfig,
    MaterialConfig,
    MaterialOutcome,
    Params,
    RotationConfig,
    ShapeConfig,
    color_spectrum,
    range_spectrum,
)
from .scene import ambient_intensity_multiplier, rendered_light_intensity

T = TypeVar("T")
FloatRange = tuple[float, float]
IntRange = tuple[int, int]
WeightedChoices = tuple[tuple[T, float], ...]


# ── Sampling policy ─────────────────────────────────────────────────────
#
# These dataclasses are intentionally small Python objects, not a declarative
# mini-language. They collect the tunable ranges and weighted choices so the
# sampler can be inspected and adjusted without hunting through control flow.


@dataclass(frozen=True)
class GridPolicy:
    spacing: FloatRange = (0.20, 0.32)
    spacing_pack_bias: float = 1.4
    rows_mean: float = 5.0
    rows_sigma: float = 1.2
    rows_min: int = 3
    rows_max: int = 8
    usable_width: float = 2.24
    cols_min: int = 4
    hole_probability: float = 0.25
    hole_fraction: FloatRange = (0.05, 0.15)


@dataclass(frozen=True)
class ShapePolicy:
    glass_size_factor: FloatRange = (0.25, 0.38)
    polygon_size_factor: FloatRange = (0.30, 0.45)
    polygon_size_bias: float = 2.0
    polygon_sides: WeightedChoices[int] = ((3, 0.53), (4, 1.0), (5, 1.0), (6, 1.0))
    corner_radius_factor: FloatRange = (0.1, 0.3)
    rotation_probability: float = 0.7
    rotation_jitter_probability: float = 0.4
    rotation_jitter_min: float = 0.06


@dataclass(frozen=True)
class AmbientPolicy:
    style_weights: WeightedChoices[str] = (("corners", 8.0), ("sides", 2.0))
    intensity: FloatRange = (0.25, 1.0)
    hue_jitter_degrees: float = 22.0
    white_mix: FloatRange = (0.3, 0.8)


@dataclass(frozen=True)
class LightPolicy:
    glass_n_lights: WeightedChoices[int] = ((1, 7.0), (2, 3.0))
    non_glass_n_lights: WeightedChoices[int] = ((1, 5.0), (2, 4.0), (3, 1.0))
    path_style_weights: WeightedChoices[str] = (
        ("waypoints", 0.0),
        ("random_walk", 0.0),
        ("vertical_drift", 0.0),
        ("drift", 2.0),
        ("channel", 3.0),
    )
    n_waypoints: IntRange = (5, 10)
    speed_min: float = 0.08
    one_light_speed_max: float = 0.20
    multi_light_speed_max: float = 0.14
    moving_intensity: FloatRange = (0.75, 1.75)
    warm_light_probability_for_achromatic: float = 0.70
    warm_spectra: tuple[FloatRange, ...] = (
        (550.0, 700.0),
        (570.0, 700.0),
    )
    ambient: AmbientPolicy = field(default_factory=AmbientPolicy)


@dataclass(frozen=True)
class LookPolicy:
    exposure: FloatRange = (-6.5, -4.5)
    gamma: FloatRange = (1.2, 2.2)
    contrast: FloatRange = (1.00, 1.10)
    white_point: FloatRange = (0.4, 0.6)
    saturation: FloatRange = (1.0, 2.2)
    temperature_enabled_probability: float = 0.50
    temperature: FloatRange = (0.0, 0.5)
    highlights: FloatRange = (-0.3, 0.3)
    shadows: FloatRange = (-0.3, 0.3)
    vignette: float = 0.0
    vignette_radius: float = 1.5
    chromatic_aberration_enabled_probability: float = 0.50
    chromatic_aberration: FloatRange = (0.001, 0.006)


_ORANGE_EXPOSURE_OFFSET = 0.240
_ORANGE_GAMMA_MULTIPLIER = 0.850
_DEEP_ORANGE_EXPOSURE_OFFSET = 0.710
_DEEP_ORANGE_GAMMA_MULTIPLIER = 0.700


@dataclass(frozen=True)
class SamplerPolicy:
    outcomes: WeightedChoices[MaterialOutcome] = (
        ("black_diffuse", 1.0),
        ("gray_diffuse", 1.0),
        ("colored_diffuse", 1.0),
        ("brushed_metal", 1.0),
    )
    grid: GridPolicy = field(default_factory=GridPolicy)
    shape: ShapePolicy = field(default_factory=ShapePolicy)
    light: LightPolicy = field(default_factory=LightPolicy)
    look: LookPolicy = field(default_factory=LookPolicy)

    @property
    def active_outcomes(self) -> tuple[MaterialOutcome, ...]:
        return tuple(outcome for outcome, _weight in self.outcomes)


DEFAULT_SAMPLER_POLICY = SamplerPolicy()
OUTCOMES = DEFAULT_SAMPLER_POLICY.active_outcomes


@dataclass(frozen=True)
class SampleOverrides:
    """Optional fixed axes for systematic tools like the catalog.

    Unset fields are drawn exactly like the free sampler. This keeps targeted
    tools on the same sampling path while allowing a small number of axes to
    be pinned for matrix-style comparisons.
    """

    outcome: MaterialOutcome | None = None
    grid: GridConfig | None = None
    n_lights: int | None = None
    path_style: str | None = None
    n_waypoints: int | None = None
    ambient_style: str | None = None
    speed: float | None = None
    spectrum: LightSpectrumConfig | None = None


def _uniform(rng: random.Random, bounds: FloatRange) -> float:
    return rng.uniform(bounds[0], bounds[1])


def _biased_uniform_low(rng: random.Random, bounds: FloatRange, bias: float) -> float:
    t = rng.random() ** max(bias, 1e-6)
    return bounds[0] + (bounds[1] - bounds[0]) * t


def _biased_uniform_high(rng: random.Random, bounds: FloatRange, bias: float) -> float:
    t = 1.0 - rng.random() ** max(bias, 1e-6)
    return bounds[0] + (bounds[1] - bounds[0]) * t


def _randint(rng: random.Random, bounds: IntRange) -> int:
    return rng.randint(bounds[0], bounds[1])


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _weighted_choice(rng: random.Random, choices: WeightedChoices[T]) -> T:
    values, weights = zip(*choices, strict=True)
    return rng.choices(values, weights=weights)[0]


def _optional_uniform(
    rng: random.Random,
    *,
    enabled_probability: float,
    bounds: FloatRange,
    fallback: float = 0.0,
    force_disabled: bool = False,
) -> float:
    enabled_draw = rng.random()
    if force_disabled or enabled_draw >= enabled_probability:
        return fallback
    return _uniform(rng, bounds)


def _muted_hsv_rgb(rng: random.Random) -> list[float]:
    rgb = colorsys.hsv_to_rgb(rng.random(), rng.uniform(0.1, 0.4), 1.0)
    return [float(rgb[0]), float(rgb[1]), float(rgb[2])]


def sample_ambient_intensity(
    rng: random.Random,
    policy: AmbientPolicy | None = None,
    *,
    moving_intensity: float | None = None,
    moving_spectrum: LightSpectrumConfig | None = None,
    ambient_spectrum: LightSpectrumConfig | None = None,
) -> float:
    policy = policy or DEFAULT_SAMPLER_POLICY.light.ambient
    low, high = policy.intensity
    if moving_intensity is not None:
        if moving_spectrum is None or ambient_spectrum is None:
            raise ValueError(
                "moving_spectrum and ambient_spectrum are required when "
                "capping ambient intensity from moving_intensity"
            )
        max_authored_ambient = rendered_light_intensity(
            moving_intensity,
            moving_spectrum,
        ) / ambient_intensity_multiplier(ambient_spectrum)
        high = min(high, max(0.0, max_authored_ambient))
    if high <= low:
        return high
    return _uniform(rng, (low, high))


def sample_moving_intensity(
    rng: random.Random,
    policy: LightPolicy | None = None,
) -> float:
    return _uniform(rng, (policy or DEFAULT_SAMPLER_POLICY.light).moving_intensity)


# ── Grid ─────────────────────────────────────────────────────────────────


def _random_grid(
    rng: random.Random,
    policy: GridPolicy | None = None,
) -> GridConfig:
    policy = policy or DEFAULT_SAMPLER_POLICY.grid
    spacing = _biased_uniform_low(rng, policy.spacing, policy.spacing_pack_bias)

    # Rows: Gaussian-like centered on 5, min 3, max 8.
    rows = max(
        policy.rows_min,
        min(policy.rows_max, round(rng.gauss(policy.rows_mean, policy.rows_sigma))),
    )

    # Cols: enough to fill the frame but leave ≥15% margin on each side.
    # Mirror box is 3.2 wide; 15% margin each side = 70% usable = 2.24 units.
    max_cols = max(policy.cols_min, int(policy.usable_width / spacing))
    cols = rng.randint(policy.cols_min, max_cols)

    offset_rows = rng.choice([True, False])
    hole_fraction = 0.0
    if rng.random() < policy.hole_probability:
        hole_fraction = _uniform(rng, policy.hole_fraction)
    return GridConfig(
        rows=rows,
        cols=cols,
        spacing=spacing,
        offset_rows=offset_rows,
        hole_fraction=hole_fraction,
    )


def _planned_grid_count(grid: GridConfig) -> float:
    return grid.rows * grid.cols * (1.0 - grid.hole_fraction)


# ── Shape ────────────────────────────────────────────────────────────────


def _glass_shape(
    rng: random.Random,
    spacing: float,
    policy: ShapePolicy | None = None,
) -> ShapeConfig:
    """Glass outcome: always circles."""
    policy = policy or DEFAULT_SAMPLER_POLICY.shape
    size = spacing * _uniform(rng, policy.glass_size_factor)
    return ShapeConfig(kind="circle", size=size, n_sides=0, corner_radius=0.0, rotation=None)


def _polygon_shape(
    rng: random.Random,
    spacing: float,
    planned_count: float | None = None,
    policy: ShapePolicy | None = None,
) -> ShapeConfig:
    """Non-glass outcomes (black / gray / colored diffuse + brushed metal): rounded polygons."""
    policy = policy or DEFAULT_SAMPLER_POLICY.shape
    n_sides = _weighted_choice(rng, policy.polygon_sides)
    size_factor = _biased_uniform_high(
        rng,
        policy.polygon_size_factor,
        policy.polygon_size_bias,
    )
    if planned_count is not None:
        # Sparse diffuse fields look weak when polygons are tiny. Keep the same
        # maximum size, but gently pull small sparse-grid draws toward it.
        sparse_bias = _clamp01((36.0 - planned_count) / 24.0)
        size_factor += (policy.polygon_size_factor[1] - size_factor) * 0.45 * sparse_bias
    size = spacing * size_factor
    corner_radius = size * _uniform(rng, policy.corner_radius_factor)

    rotation: RotationConfig | None = None
    if rng.random() < policy.rotation_probability:
        base_angle = rng.uniform(0, 2 * math.pi / n_sides)
        jitter = (
            rng.uniform(policy.rotation_jitter_min, math.pi / n_sides)
            if rng.random() < policy.rotation_jitter_probability
            else 0.0
        )
        rotation = RotationConfig(base_angle=base_angle, jitter=jitter)

    return ShapeConfig(
        kind="polygon",
        size=size,
        n_sides=n_sides,
        corner_radius=corner_radius,
        rotation=rotation,
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
        fill=rng.uniform(0.15, 0.3),
        transmission=rng.uniform(0.0, 0.05),
        absorption=rng.uniform(0.75, 1.25),
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
        transmission=rng.uniform(0.0, 0.05),
        absorption=rng.uniform(0.75, 1.25),
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
        color_names: list[list[float] | None] = []
    elif sub == "one_color":
        color_names = [_muted_hsv_rgb(rng)]
    elif sub == "mixed":
        color_names = [_muted_hsv_rgb(rng), None]
    else:  # "two_colors"
        color_names = [_muted_hsv_rgb(rng), _muted_hsv_rgb(rng)]

    return MaterialConfig(
        outcome="brushed_metal",
        albedo=albedo,
        fill=fill,
        ior=ior,
        color_names=color_names,
        wall_metallic=wall_metallic,
    )


# ── Light ────────────────────────────────────────────────────────────────


def _is_colored_light_spectrum(spectrum: LightSpectrumConfig) -> bool:
    if spectrum.type == "range":
        return spectrum.wavelength_max - spectrum.wavelength_min < 300.0
    rgb = spectrum.linear_rgb
    effective = [channel + (1.0 - channel) * spectrum.white_mix for channel in rgb]
    return max(effective) - min(effective) > 1e-5 or min(effective) < 1.0 - 1e-5


def _spectrum_hue_rgb(spectrum: LightSpectrumConfig) -> list[float]:
    if spectrum.type == "color":
        return list(spectrum.linear_rgb)

    converted, _scale = LightSpectrum.from_range_as_color(
        spectrum.wavelength_min,
        spectrum.wavelength_max,
    )
    return [converted.linear_r, converted.linear_g, converted.linear_b]


def _complementary_ambient_spectrum(
    rng: random.Random,
    moving_spectrum: LightSpectrumConfig,
    policy: AmbientPolicy | None = None,
) -> LightSpectrumConfig:
    policy = policy or DEFAULT_SAMPLER_POLICY.light.ambient
    if not _is_colored_light_spectrum(moving_spectrum):
        return LightSpectrumConfig()

    rgb = _spectrum_hue_rgb(moving_spectrum)
    hue, saturation, _value = colorsys.rgb_to_hsv(rgb[0], rgb[1], rgb[2])
    if saturation <= 1e-5:
        return LightSpectrumConfig()

    jitter = rng.uniform(-policy.hue_jitter_degrees, policy.hue_jitter_degrees) / 360.0
    ambient_rgb = colorsys.hsv_to_rgb((hue + 0.5 + jitter) % 1.0, 1.0, 1.0)
    white_mix = _uniform(rng, policy.white_mix)
    return color_spectrum(ambient_rgb, white_mix=white_mix)


def ambient_for_moving_spectrum(
    rng: random.Random,
    *,
    style: str,
    intensity: float,
    moving_spectrum: LightSpectrumConfig,
    policy: AmbientPolicy | None = None,
) -> AmbientConfig:
    # All ambient lights currently share one complementary color. Per-light
    # hue/white-mix variation is intentionally left for future exploration.
    return AmbientConfig(
        style=style,
        intensity=intensity,
        spectrum=_complementary_ambient_spectrum(rng, moving_spectrum, policy=policy),
    )


def sample_ambient_for_moving_light(
    rng: random.Random,
    *,
    style: str,
    moving_intensity: float,
    moving_spectrum: LightSpectrumConfig,
    policy: AmbientPolicy | None = None,
) -> AmbientConfig:
    policy = policy or DEFAULT_SAMPLER_POLICY.light.ambient
    spectrum = _complementary_ambient_spectrum(rng, moving_spectrum, policy=policy)
    intensity = sample_ambient_intensity(
        rng,
        policy,
        moving_intensity=moving_intensity,
        moving_spectrum=moving_spectrum,
        ambient_spectrum=spectrum,
    )
    return AmbientConfig(style=style, intensity=intensity, spectrum=spectrum)


def _random_light(
    rng: random.Random,
    is_glass: bool,
    has_object_color: bool,
    policy: LightPolicy | None = None,
    overrides: SampleOverrides | None = None,
) -> LightConfig:
    policy = policy or DEFAULT_SAMPLER_POLICY.light
    overrides = overrides or SampleOverrides()

    # Number of lights: glass prefers 1; non-glass allows 1-3.
    n_lights = (
        overrides.n_lights
        if overrides.n_lights is not None
        else _weighted_choice(
            rng,
            policy.glass_n_lights if is_glass else policy.non_glass_n_lights,
        )
    )

    # Path style.
    path_style = (
        overrides.path_style
        if overrides.path_style is not None
        else _weighted_choice(rng, policy.path_style_weights)
    )

    n_waypoints = (
        overrides.n_waypoints
        if overrides.n_waypoints is not None
        else _randint(rng, policy.n_waypoints)
    )

    # Speed: base 0.08–0.20, slower with more lights.
    speed_max = policy.one_light_speed_max if n_lights == 1 else policy.multi_light_speed_max
    speed = (
        overrides.speed if overrides.speed is not None else rng.uniform(policy.speed_min, speed_max)
    )

    moving_intensity = sample_moving_intensity(rng, policy)

    # Light colour: warm tint when the scene has no object colour.
    # 70% of achromatic scenes get coloured light to avoid too much gray.
    if overrides.spectrum is not None:
        spectrum = overrides.spectrum
    else:
        wl_min, wl_max = 380.0, 780.0
        if not has_object_color and rng.random() < policy.warm_light_probability_for_achromatic:
            wl_min, wl_max = rng.choice(policy.warm_spectra)
        spectrum = range_spectrum(wl_min, wl_max)

    amb_style = (
        overrides.ambient_style
        if overrides.ambient_style is not None
        else _weighted_choice(rng, policy.ambient.style_weights)
    )
    ambient = sample_ambient_for_moving_light(
        rng,
        style=amb_style,
        moving_intensity=moving_intensity,
        moving_spectrum=spectrum,
        policy=policy.ambient,
    )

    return LightConfig(
        n_lights=n_lights,
        path_style=path_style,
        n_waypoints=n_waypoints,
        ambient=ambient,
        speed=speed,
        moving_intensity=moving_intensity,
        spectrum=spectrum,
    )


# ── Look ─────────────────────────────────────────────────────────────────


def _random_look(
    rng: random.Random,
    material: MaterialConfig,
    light: LightConfig,
    policy: LookPolicy | None = None,
) -> LookConfig:
    """Draw a LookConfig alongside the structural params.

    Positive temperature on warm light and chromatic aberration on glass are
    suppressed here (and also hard-rejected in ``check.py``) — the first
    pushes warm scenes into red mush, the second confuses refractive scenes.
    """
    policy = policy or DEFAULT_SAMPLER_POLICY.look
    exposure = _uniform(rng, policy.exposure)
    gamma = _uniform(rng, policy.gamma)
    contrast = _uniform(rng, policy.contrast)
    white_point = _uniform(rng, policy.white_point)

    if light.spectrum.type == "range":
        wl_min = light.spectrum.wavelength_min
        wl_max = light.spectrum.wavelength_max
        # Warm narrow bands keep smaller measured circles after spectral_boost.
        # Exposure restores circle size; gamma compensates the extra brightness.
        if math.isclose(wl_min, 550.0) and math.isclose(wl_max, 700.0):
            exposure += _ORANGE_EXPOSURE_OFFSET
            gamma *= _ORANGE_GAMMA_MULTIPLIER
        elif math.isclose(wl_min, 570.0) and math.isclose(wl_max, 700.0):
            exposure += _DEEP_ORANGE_EXPOSURE_OFFSET
            gamma *= _DEEP_ORANGE_GAMMA_MULTIPLIER

    gamma = max(gamma, 1.0)  # avoid extreme crush that hides the look variation

    # Temperature: 50% off, 50% uniform(0.0, 0.55) — but forbidden on warm light.
    warm_light = (light.spectrum.type == "range" and light.spectrum.wavelength_min >= 500.0) or (
        light.spectrum.type == "color" and light.spectrum.linear_rgb != [1.0, 1.0, 1.0]
    )
    temperature = _optional_uniform(
        rng,
        enabled_probability=policy.temperature_enabled_probability,
        bounds=policy.temperature,
        force_disabled=warm_light,
    )

    highlights = _uniform(rng, policy.highlights)
    shadows = _uniform(rng, policy.shadows)

    # Vignette is temporarily disabled because it biases frame-analysis metrics.
    vignette = policy.vignette
    vignette_radius = policy.vignette_radius

    # Chromatic aberration: 50% off, 50% subtle — forbidden on glass.
    chromatic_aberration = _optional_uniform(
        rng,
        enabled_probability=policy.chromatic_aberration_enabled_probability,
        bounds=policy.chromatic_aberration,
        force_disabled=material.outcome == "glass",
    )
    saturation = _uniform(rng, policy.saturation)

    return LookConfig(
        exposure=exposure,
        gamma=gamma,
        contrast=contrast,
        white_point=white_point,
        saturation=saturation,
        temperature=temperature,
        highlights=highlights,
        shadows=shadows,
        vignette=vignette,
        vignette_radius=vignette_radius,
        chromatic_aberration=chromatic_aberration,
    )


# ── Top-level sampler ────────────────────────────────────────────────────


_MATERIAL_SAMPLERS: dict[MaterialOutcome, Callable[[random.Random], MaterialConfig]] = {
    "glass": _glass_material,
    "black_diffuse": _black_diffuse_material,
    "gray_diffuse": _gray_diffuse_material,
    "colored_diffuse": _colored_diffuse_material,
    "brushed_metal": _brushed_metal_material,
}


def sample(
    rng: random.Random,
    policy: SamplerPolicy | None = None,
    overrides: SampleOverrides | None = None,
) -> Params:
    """Generate one random crystal_field variant.

    Picks one of the active policy outcomes and draws grid, shape, material,
    light, and look for it in one shot. ``Family.search`` retries the whole
    sample on rejection — there is no inner search loop. ``overrides`` lets
    systematic tools pin a few axes while keeping the normal sampler path for
    everything else.

    Glass is temporarily excluded from the active free sampler. The glass
    branch remains below so targeted tools, old params, and future tuning
    can continue to use it deliberately.
    """
    policy = policy or DEFAULT_SAMPLER_POLICY
    overrides = overrides or SampleOverrides()
    outcome = (
        overrides.outcome
        if overrides.outcome is not None
        else _weighted_choice(rng, policy.outcomes)
    )

    grid = overrides.grid if overrides.grid is not None else _random_grid(rng, policy.grid)

    if outcome == "glass":
        shape = _glass_shape(rng, grid.spacing, policy.shape)
    else:
        shape = _polygon_shape(
            rng,
            grid.spacing,
            planned_count=_planned_grid_count(grid),
            policy=policy.shape,
        )
    material = _MATERIAL_SAMPLERS[outcome](rng)

    has_object_color = any(name is not None for name in material.color_names)
    light = _random_light(
        rng,
        is_glass=(outcome == "glass"),
        has_object_color=has_object_color,
        policy=policy.light,
        overrides=overrides,
    )
    look = _random_look(rng, material, light, policy=policy.look)

    build_seed = rng.randint(0, 2**32)

    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=light,
        look=look,
        build_seed=build_seed,
    )
