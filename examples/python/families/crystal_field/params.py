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
    wavelength_min: float = 380.0  # moving-light spectral range (nm)
    wavelength_max: float = 780.0  # 380-780 = white (full spectrum)


@dataclass
class Params:
    grid: GridConfig
    shape: ShapeConfig
    material: MaterialConfig
    light: LightConfig
    exposure: float
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
