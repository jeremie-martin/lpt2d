"""Scene constants and parameter dataclasses for crystal_field."""

from __future__ import annotations

from dataclasses import dataclass, field

from anim import Material

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
    style: str  # "glass" or "diffuse"
    ior: float  # only for glass
    cauchy_b: float  # only for glass
    absorption: float  # only for glass
    fill: float  # interior fill visibility
    n_color_groups: int  # 0 = no color
    diffuse_style: str = "dark"  # "dark", "colored_fill", "metallic_rough" — only for diffuse
    color_names: list[str] = field(default_factory=list)
    albedo: float = 0.8  # diffuse albedo; dark style ignores this and uses a fixed low value


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
