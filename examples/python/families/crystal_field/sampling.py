"""Random parameter samplers — one per config layer."""

from __future__ import annotations

import math
import random

from .params import (
    AmbientConfig,
    GridConfig,
    LightConfig,
    MaterialConfig,
    PALETTE,
    Params,
    RotationConfig,
    ShapeConfig,
)


def random_grid(rng: random.Random) -> GridConfig:
    if rng.random() < 0.30:
        # Small sparse grid — fewer objects, more breathing room.
        rows = rng.randint(3, 5)
        cols = rng.randint(4, 7)
        spacing = rng.uniform(0.25, 0.35)
    else:
        spacing = rng.uniform(0.18, 0.30)
        cols = max(3, int(2.4 / spacing) + rng.randint(-1, 1))
        rows = max(3, int(1.4 / spacing) + rng.randint(-1, 1))
    offset_rows = rng.choice([True, False])
    hole_fraction = rng.choice([0.0, 0.0, 0.0, rng.uniform(0.05, 0.20)])
    return GridConfig(
        rows=rows, cols=cols, spacing=spacing, offset_rows=offset_rows, hole_fraction=hole_fraction
    )


def random_shape(rng: random.Random, spacing: float, small_grid: bool = False) -> ShapeConfig:
    kind = rng.choices(["circle", "polygon"], weights=[2, 3])[0]
    # Bigger objects on smaller grids — they need visual weight.
    lo, hi = (0.28, 0.42) if small_grid else (0.22, 0.35)
    size = spacing * rng.uniform(lo, hi)

    if kind == "circle":
        return ShapeConfig(kind="circle", size=size, n_sides=0, corner_radius=0.0, rotation=None)

    # Polygon
    n_sides = rng.choice([3, 4, 5, 6])
    corner_radius = size * rng.uniform(0.10, 0.35)

    # Gate: do we add rotation?
    if rng.random() < 0.6:
        base_angle = rng.uniform(0, 2 * math.pi / n_sides)
        # Gate: uniform rotation or per-object jitter?
        if rng.random() < 0.4:
            jitter = rng.uniform(0.05, math.pi / n_sides)
        else:
            jitter = 0.0
        rotation = RotationConfig(base_angle=base_angle, jitter=jitter)
    else:
        rotation = None

    return ShapeConfig(
        kind="polygon", size=size, n_sides=n_sides, corner_radius=corner_radius, rotation=rotation
    )


def random_material(rng: random.Random, shape_kind: str) -> MaterialConfig:
    # Polygons should be opaque — straight edges + glass = chaotic reflections.
    # Circles are fine as glass.
    if shape_kind == "polygon":
        style = "diffuse"
    else:
        style = rng.choices(["glass", "glass", "diffuse"], weights=[5, 5, 1])[0]

    # IOR 1.3–1.75, biased toward higher values (wider caustics).
    ior = 1.3 + rng.betavariate(2.0, 1.5) * 0.45
    cauchy_b = rng.uniform(10_000, 30_000)
    absorption = rng.uniform(0.2, 2.5)

    # Diffuse sub-style: dark silhouettes, colored fill, or brushed metal
    diffuse_style = "dark"
    if style == "diffuse":
        diffuse_style = rng.choices(["dark", "colored_fill", "metallic_rough"], weights=[3, 4, 2])[
            0
        ]

    # Fill: always nonzero for glass; for diffuse depends on sub-style
    if style == "glass":
        fill = rng.uniform(0.08, 0.18)
    elif diffuse_style in ("colored_fill", "metallic_rough"):
        fill = rng.uniform(0.06, 0.15)
    else:
        fill = 0.0

    # Color groups.  Glass circles should NOT have mixed spectral colors —
    # alternating colored glass looks messy.  Colors work on diffuse shapes.
    if style == "glass":
        n_color_groups = 0
    else:
        n_color_groups = rng.choice([0, 0, 1, 2, 3])
    color_names: list[str] = []
    if n_color_groups > 0:
        color_names = rng.sample(PALETTE, min(n_color_groups, len(PALETTE)))

    return MaterialConfig(
        style=style,
        ior=ior,
        cauchy_b=cauchy_b,
        absorption=absorption,
        fill=fill,
        n_color_groups=n_color_groups,
        diffuse_style=diffuse_style,
        color_names=color_names,
    )


def random_light(rng: random.Random, material_style: str, n_color_groups: int) -> LightConfig:
    # Fewer lights with glass — caustics from multiple lights overlap chaotically.
    if material_style == "glass":
        n_lights = rng.choices([1, 2, 3], weights=[7, 2, 1])[0]
    else:
        n_lights = rng.choices([1, 2, 3], weights=[5, 3, 1])[0]
    path_style = rng.choices(
        ["waypoints", "random_walk", "vertical_drift", "drift", "channel"],
        weights=[2, 1, 1, 2, 2],
    )[0]
    n_waypoints = rng.randint(5, 12)

    # Speed: slower with more lights, slower with glass (caustics are complex).
    speed_max = 0.25
    if n_lights >= 2:
        speed_max *= 0.7
    if material_style == "glass":
        speed_max *= 0.8
    speed = rng.uniform(0.08, speed_max)

    # Ambient lighting — most scenes benefit from some fixed illumination.
    # Ambient intensity is always less than the moving-light intensity (1.0)
    # to keep the moving circles visually dominant.
    amb_style = rng.choices(["corners", "sides", "none"], weights=[8, 2, 0.5])[0]
    amb_intensity = rng.uniform(0.1, 0.4) if amb_style != "none" else 0.0
    ambient = AmbientConfig(style=amb_style, intensity=amb_intensity)

    # Colored moving lights: when objects have no spectral color, the moving
    # light itself can be warm-colored for visual interest.  Ambient stays
    # white to attenuate the color dominance.
    wl_min, wl_max = 380.0, 780.0  # full spectrum (white)
    if n_color_groups == 0 and rng.random() < 0.35:
        # Warm spectral ranges — intentional, not random.
        wl_min, wl_max = rng.choice([
            (550.0, 700.0),  # orange
            (515.0, 700.0),  # yellow-orange
            (570.0, 700.0),  # deep orange
            (500.0, 620.0),  # warm green-yellow
        ])

    return LightConfig(
        n_lights=n_lights,
        path_style=path_style,
        n_waypoints=n_waypoints,
        ambient=ambient,
        speed=speed,
        wavelength_min=wl_min,
        wavelength_max=wl_max,
    )


def sample(rng: random.Random) -> Params:
    grid = random_grid(rng)
    small_grid = grid.rows <= 5 and grid.cols <= 7
    shape = random_shape(rng, grid.spacing, small_grid=small_grid)
    material = random_material(rng, shape.kind)
    light = random_light(rng, material.style, material.n_color_groups)
    exposure = rng.uniform(-5.5, -3.5)
    build_seed = rng.randint(0, 2**32)
    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=light,
        exposure=exposure,
        build_seed=build_seed,
    )
