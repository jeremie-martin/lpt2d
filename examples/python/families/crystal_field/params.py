"""Scene constants and parameter dataclasses for crystal_field."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import Literal, TypeAlias

from anim import Material

# ---------------------------------------------------------------------------
# Outcome alias — one of the five peer material outcomes. Declared as a
# Literal so construction sites catch typos at type-check time instead of
# failing silently in the dispatch dict.
# ---------------------------------------------------------------------------

MaterialOutcome = Literal[
    "glass",
    "black_diffuse",
    "gray_diffuse",
    "colored_diffuse",
    "brushed_metal",
]
MaterialColor: TypeAlias = str | list[float] | tuple[float, float, float] | None

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
WALL_ID = "wall"
DURATION = 10.0

# ---------------------------------------------------------------------------
# Config layers
# ---------------------------------------------------------------------------


@dataclass
class GridConfig:
    rows: int
    cols: int
    spacing: float
    offset_rows: bool  # brick-like stagger on odd rows
    hole_fraction: float  # fraction of positions to remove (0 = full grid)


@dataclass
class RotationConfig:
    """Per-object rotation (only meaningful for polygons)."""

    base_angle: float  # shared base rotation (rad)
    jitter: float  # max random offset per object (rad); 0 = all identical


@dataclass
class ShapeConfig:
    kind: str  # "circle" or "polygon"
    size: float  # radius; for polygons, distance from object center to each vertex
    n_sides: int  # ignored for circle; 3=triangle, 4=square, 5=pentagon, 6=hex
    corner_radius: float  # fillet on polygon corners; 0 = sharp
    rotation: RotationConfig | None  # None = no rotation (or circle)


@dataclass
class MaterialConfig:
    """Per-scene material config.

    One ``outcome`` per scene — never mixed.  See
    ``analysis.md`` for the visual reasoning behind each outcome and
    ``sampling.py`` for the exact parameter ranges of each branch.

    Outcomes and the fields they actually use:

    - ``glass``           : ``albedo`` (drawn but visually irrelevant — transmission=1),
                            ``ior``, ``cauchy_b``, ``absorption``, ``fill``.
                            ``color_names`` is always empty.
    - ``black_diffuse``   : ``albedo``, ``fill`` (= 0.0). ``color_names`` empty.
    - ``gray_diffuse``    : ``albedo``, ``fill``, ``transmission``, ``absorption``.
                            ``color_names`` empty.
    - ``colored_diffuse`` : ``albedo``, ``fill``, ``transmission``, ``absorption``,
                            ``color_names`` has exactly one palette entry.
    - ``brushed_metal``   : ``albedo``, ``fill``, ``ior``, ``wall_metallic``.
                            ``color_names`` has 0, 1, or 2 entries. Any slot
                            may be ``None`` meaning "no color for this group,
                            just fill" — this is how the "mixed" brushed-metal
                            sub-case expresses one colored half and one
                            uncolored half sharing the same fill value.

    The same-fill-per-scene rule applies to every outcome: the ``fill`` value
    is drawn once for the scene and used for every material inside it,
    including across color groups in brushed-metal.
    """

    outcome: MaterialOutcome
    albedo: float  # always ∈ [0.7, 1.0] — defined inline per branch (not hoisted)
    fill: float
    transmission: float = 0.0  # gray_diffuse + colored_diffuse
    ior: float = 0.0  # glass + brushed_metal
    cauchy_b: float = 0.0  # glass only
    absorption: float = 0.0  # glass + gray_diffuse + colored_diffuse
    color_names: list[MaterialColor] = field(default_factory=list)
    wall_metallic: float = 1.0  # brushed_metal only; others keep the mirror wall fully metallic


@dataclass
class LightSpectrumConfig:
    """Serializable light spectrum intent for moving and ambient lights."""

    type: str = "range"  # "range" or "color"
    wavelength_min: float = 380.0
    wavelength_max: float = 780.0
    linear_rgb: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    white_mix: float = 0.0


def range_spectrum(wavelength_min: float, wavelength_max: float) -> LightSpectrumConfig:
    return LightSpectrumConfig(
        type="range",
        wavelength_min=wavelength_min,
        wavelength_max=wavelength_max,
    )


def color_spectrum(
    linear_rgb: tuple[float, float, float] | list[float],
    white_mix: float = 0.0,
) -> LightSpectrumConfig:
    return LightSpectrumConfig(
        type="color",
        linear_rgb=[float(linear_rgb[0]), float(linear_rgb[1]), float(linear_rgb[2])],
        white_mix=white_mix,
    )


@dataclass
class AmbientConfig:
    """Fixed ambient lights that illuminate the scene globally."""

    style: str  # "corners", "sides", "none"
    intensity: float  # per-light white-equivalent intensity
    spectrum: LightSpectrumConfig = field(default_factory=LightSpectrumConfig)


@dataclass
class LightConfig:
    n_lights: int
    path_style: str  # "waypoints", "random_walk", "vertical_drift", "drift", "channel"
    n_waypoints: int  # segment count for waypoints / steps for random walk
    ambient: AmbientConfig  # fixed background illumination
    speed: float  # world units per second (drift and channel styles)
    moving_intensity: float = 1.0  # per-light white-equivalent moving-light intensity
    spectrum: LightSpectrumConfig = field(default_factory=LightSpectrumConfig)
    # Deprecated replay compatibility. Old params JSONs carry these fields.
    wavelength_min: InitVar[float | None] = None
    wavelength_max: InitVar[float | None] = None

    def __post_init__(self, wavelength_min: float | None, wavelength_max: float | None) -> None:
        if wavelength_min is not None and wavelength_max is not None:
            self.spectrum = range_spectrum(wavelength_min, wavelength_max)


@dataclass
class LookConfig:
    """Post-process / tonemap dials threaded into ``anim.Look``.

    Defaults mirror the C++ engine defaults in ``src/core/scene.h`` so a
    ``LookConfig(exposure=x)`` with everything else default is equivalent
    to today's ``Look(exposure=x)``.
    """

    exposure: float
    gamma: float = 2.0
    contrast: float = 1.0
    white_point: float = 0.5
    saturation: float = 1.0
    temperature: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0
    vignette: float = 0.0
    vignette_radius: float = 0.7
    chromatic_aberration: float = 0.0


@dataclass
class Params:
    grid: GridConfig
    shape: ShapeConfig
    material: MaterialConfig
    light: LightConfig
    look: LookConfig
    build_seed: int  # rng seed for build-time randomness (holes, material assignment, light paths)


# ---------------------------------------------------------------------------
# Colour palette for spectral tinting
# ---------------------------------------------------------------------------

PALETTE = [
    "red",
    "orange",
    "amber",
    "yellow",
    "green",
    "cyan",
    "blue",
    "violet",
    "pink",
    "magenta",
    "gold",
]
