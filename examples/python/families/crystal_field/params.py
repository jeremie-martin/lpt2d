"""Scene constants and parameter dataclasses for crystal_field."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
    size: float  # radius (circle) or circumscribed radius (polygon)
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
    - ``gray_diffuse``    : ``albedo``, ``fill``. ``color_names`` empty.
    - ``colored_diffuse`` : ``albedo``, ``fill``, ``color_names`` has exactly one
                            palette entry (strictly 1 color for now).
    - ``brushed_metal``   : ``albedo``, ``fill``. ``color_names`` has 0, 1, or 2
                            entries. Any slot may be ``None`` meaning
                            "no color for this group, just fill" — this is
                            how the "mixed" brushed-metal sub-case expresses
                            one colored half and one uncolored half sharing
                            the same fill value.

    The same-fill-per-scene rule applies to every outcome: the ``fill`` value
    is drawn once for the scene and used for every material inside it,
    including across color groups in brushed-metal.
    """

    outcome: MaterialOutcome
    albedo: float  # always ∈ [0.7, 1.0] — defined inline per branch (not hoisted)
    fill: float
    ior: float = 0.0  # glass only
    cauchy_b: float = 0.0  # glass only
    absorption: float = 0.0  # glass only
    color_names: list[str | None] = field(default_factory=list)


@dataclass
class AmbientConfig:
    """Fixed ambient lights that illuminate the scene globally."""

    style: str  # "corners", "sides", "none"
    intensity: float  # per-light intensity (typically 0.2-0.4)


@dataclass
class LightConfig:
    n_lights: int
    path_style: str  # "waypoints", "random_walk", "vertical_drift", "drift", "channel"
    n_waypoints: int  # segment count for waypoints / steps for random walk
    ambient: AmbientConfig  # fixed background illumination
    speed: float  # world units per second (drift and channel styles)
    moving_intensity: float = 1.0  # base intensity for moving lights
    wavelength_min: float = 380.0  # moving-light spectral range (nm)
    wavelength_max: float = 780.0  # 380-780 = white (full spectrum)


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
    temperature: float = 0.0
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
