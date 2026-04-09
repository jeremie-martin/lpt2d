"""Crystal Field — point lights drifting through a grid of small objects.

A regular grid of small objects fills a mirror box.  One or more point lights
travel slowly through the interstitial spaces, refracting through the field
and painting evolving caustic webs across the walls.  The original discovery
was a hand-placed grid of glass spheres with a single point light drifting
downward through the center — the effect was striking enough to warrant a
full family of variations.

The visual concept
------------------
The beauty comes from the *density* of interactions: each object refracts
the point light into tiny caustic fans, and because the objects are packed
in a grid, these fans overlap and interfere.  As the light moves, the
entire pattern shifts continuously.  The mirror walls bounce escaped light
back into the field, adding a second layer of structure.

What varies
-----------
- **Grid layout**: rows, cols, spacing.  Offset (brick-like) rows shift
  odd rows by half a cell, creating a denser packing.  Random holes punch
  gaps in the grid — sometimes a few missing objects make the pattern more
  interesting than a perfect lattice.

- **Object shape**: circles (the original discovery) or regular polygons
  (triangles through hexagons).  Polygons refract differently — triangles
  act like tiny prisms, squares create cross-shaped caustics, hexagons
  tile tightly.  Corner radius softens polygon edges.

- **Rotation**: only meaningful for polygons.  A uniform base rotation
  orients the entire grid (e.g., pointy-top vs flat-top hexagons).
  Per-object jitter adds randomness — each object gets its own small
  angular offset, breaking the grid regularity.  Some scenes look better
  with all objects aligned; others benefit from the chaos.

- **Material**: glass is the primary mode — IOR, dispersion (cauchy_b),
  and absorption control how much each object bends and colors the light.
  Higher IOR (1.8-2.0) produces stronger refraction and more dramatic
  caustics.  Diffuse objects (rough metallic) create shadow patterns
  instead of caustics.  "Mixed" scenes combine both — glass objects
  refract while diffuse ones block and scatter.

- **Color**: named spectral colors (red, gold, violet, etc.) applied in
  groups.  All objects share the same optical properties (IOR, dispersion)
  but can have different spectral tinting.  Scenes with 1-3 color groups
  tend to score highest on color richness.  Zero-color scenes rely purely
  on white-light dispersion for their rainbow effects.

- **Light paths**: point lights (not projectors — omni-directional) that
  travel through the field.  Three path styles:
  - *Waypoints*: random points within the grid bounds, connected by
    straight segments at constant velocity (no easing — the light just
    travels, like light does).
  - *Random walk*: correlated angular perturbation at each step, with
    reflection at the grid bounds.  Produces organic, wandering paths.
  - *Vertical drift*: simple top-to-bottom at a fixed x.  The original
    effect that looked so good — the light slowly descending through
    the field like a sunrise.
  Multiple lights (1-3) are supported; each follows its own independent
  path.

- **Exposure**: varied per variant to compensate for different object
  counts and light configurations.

Ideas explored but not yet implemented
--------------------------------------
- **Levy flights**: heavy-tailed random walks where the light occasionally
  makes long jumps.  Would create dramatic shifts in the caustic pattern.

- **Non-circle shapes as objects**: the grid positions could hold any
  authored shape — a flower outline, a wheel, a sword silhouette.  The
  concept is "crystal field", not "sphere grid".  The shape just needs
  to be small enough relative to the spacing to leave interstitial room
  for the light.

- **Animated rotation**: objects slowly rotating during the animation,
  so the caustic pattern evolves even with a stationary light.

- **Size variation**: objects of varying radius within the same grid.
  Larger objects refract more dramatically; smaller ones add texture.

- **Grid patterns beyond rectangular**: hexagonal packing, radial grids,
  Penrose tilings, or even grids that curve or warp.

- **Path constraints**: light paths that specifically thread through the
  interstitial channels between objects, rather than moving freely.
  Would require a simple pathfinding or channel-following algorithm.

Architecture note
-----------------
The parameter space is organized as layered configs — each concern (grid,
shape, material, light) is a small focused dataclass with its own random
sampler and gating logic.  Parameters that only matter when a feature is
enabled (e.g., rotation angles for polygons, diffuse fraction for mixed
materials) live inside that feature's config block rather than in a flat
bag.  This keeps the sampling code readable as new knobs are added.

The params JSON includes a ``build_seed`` alongside the config so that
any saved variant can be exactly reproduced.
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from anim import (
    Camera2D,
    Circle,
    Frame,
    FrameContext,
    Key,
    Look,
    Material,
    PointLight,
    Polygon,
    Scene,
    Shot,
    Timeline,
    Track,
    Wrap,
    color_stats,
    glass,
    mirror_box,
    regular_polygon,
    render,
)
from anim.renderer import RenderSession, _resolve_frame_shot

# ---------------------------------------------------------------------------
# Scene constants
# ---------------------------------------------------------------------------

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
WALL_ID = "wall"

CAMERA = Camera2D(center=[0, 0], width=3.2)
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
    style: str  # "glass", "diffuse", "mixed"
    ior: float
    cauchy_b: float
    absorption: float
    fill: float
    diffuse_fraction: float  # only used when style="mixed"
    n_color_groups: int  # 0 = no color
    color_names: list[str] = field(default_factory=list)


@dataclass
class LightConfig:
    n_lights: int
    path_style: str  # "waypoints", "random_walk", "vertical_drift"
    n_waypoints: int  # segment count for waypoints / steps for random walk


@dataclass
class AnimParams:
    grid: GridConfig
    shape: ShapeConfig
    material: MaterialConfig
    light: LightConfig
    exposure: float


# ---------------------------------------------------------------------------
# Grid builder
# ---------------------------------------------------------------------------


def build_grid(cfg: GridConfig) -> list[tuple[float, float]]:
    """Generate grid positions centered at the origin."""
    grid_w = (cfg.cols - 1) * cfg.spacing
    grid_h = (cfg.rows - 1) * cfg.spacing
    x0 = -grid_w / 2
    y0 = -grid_h / 2
    positions = []
    for r in range(cfg.rows):
        for c in range(cfg.cols):
            x = x0 + c * cfg.spacing
            y = y0 + r * cfg.spacing
            if cfg.offset_rows and r % 2 == 1:
                x += cfg.spacing / 2
            positions.append((x, y))
    return positions


def remove_holes(
    positions: list[tuple[float, float]],
    fraction: float,
    rng: random.Random,
) -> list[tuple[float, float]]:
    """Randomly remove a fraction of positions."""
    n_remove = int(len(positions) * fraction)
    if n_remove <= 0 or len(positions) <= 1:
        return positions
    drop = set(rng.sample(range(len(positions)), min(n_remove, len(positions) - 1)))
    return [p for i, p in enumerate(positions) if i not in drop]


# ---------------------------------------------------------------------------
# Shape builder
# ---------------------------------------------------------------------------


def build_object(
    idx: int,
    center: tuple[float, float],
    shape_cfg: ShapeConfig,
    material_id: str,
    rng: random.Random,
) -> Circle | Polygon:
    """Build one grid object according to the shape config."""
    if shape_cfg.kind == "circle":
        return Circle(
            id=f"obj_{idx}",
            center=list(center),
            radius=shape_cfg.size,
            material_id=material_id,
        )

    # Polygon
    rotation = 0.0
    if shape_cfg.rotation is not None:
        rotation = shape_cfg.rotation.base_angle
        if shape_cfg.rotation.jitter > 0:
            rotation += rng.uniform(-shape_cfg.rotation.jitter, shape_cfg.rotation.jitter)

    return regular_polygon(
        center=center,
        radius=shape_cfg.size,
        n=shape_cfg.n_sides,
        material_id=material_id,
        rotation=rotation,
        corner_radius=shape_cfg.corner_radius,
        id_prefix=f"obj_{idx}",
    )


# ---------------------------------------------------------------------------
# Material builder
# ---------------------------------------------------------------------------


def build_materials(cfg: MaterialConfig) -> dict[str, Material]:
    mats: dict[str, Material] = {WALL_ID: WALL}

    if cfg.style in ("glass", "mixed"):
        mats["crystal"] = glass(
            cfg.ior, cauchy_b=cfg.cauchy_b, absorption=cfg.absorption, fill=cfg.fill
        )
        for i, cname in enumerate(cfg.color_names):
            mats[f"crystal_c{i}"] = glass(
                cfg.ior,
                cauchy_b=cfg.cauchy_b,
                absorption=cfg.absorption,
                color=cname,
                fill=cfg.fill,
            )

    if cfg.style in ("diffuse", "mixed"):
        mats["crystal_diffuse"] = Material(
            roughness=0.8, metallic=0.3, albedo=0.9, transmission=0.0
        )

    return mats


def assign_material_ids(
    n_objects: int,
    cfg: MaterialConfig,
    rng: random.Random,
) -> list[str]:
    n_colors = len(cfg.color_names)
    ids: list[str] = []
    for i in range(n_objects):
        if cfg.style == "diffuse":
            ids.append("crystal_diffuse")
        elif cfg.style == "mixed" and rng.random() < cfg.diffuse_fraction:
            ids.append("crystal_diffuse")
        elif n_colors > 0:
            ids.append(f"crystal_c{i % n_colors}")
        else:
            ids.append("crystal")
    return ids


# ---------------------------------------------------------------------------
# Light path generators
# ---------------------------------------------------------------------------


def waypoint_path(
    rng: random.Random,
    n_waypoints: int,
    bounds: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    x_lo, y_lo, x_hi, y_hi = bounds
    m = 0.05
    return [
        (rng.uniform(x_lo + m, x_hi - m), rng.uniform(y_lo + m, y_hi - m))
        for _ in range(n_waypoints)
    ]


def random_walk_path(
    rng: random.Random,
    n_steps: int,
    step_size: float,
    bounds: tuple[float, float, float, float],
) -> list[tuple[float, float]]:
    x_lo, y_lo, x_hi, y_hi = bounds
    m = 0.04
    x = rng.uniform(x_lo + m, x_hi - m)
    y = rng.uniform(y_lo + m, y_hi - m)
    angle = rng.uniform(0, 2 * math.pi)
    pts = [(x, y)]
    for _ in range(n_steps):
        angle += rng.gauss(0, 0.4)
        nx = x + step_size * math.cos(angle)
        ny = y + step_size * math.sin(angle)
        if nx < x_lo + m or nx > x_hi - m:
            angle = math.pi - angle
            nx = x + step_size * math.cos(angle)
        if ny < y_lo + m or ny > y_hi - m:
            angle = -angle
            ny = y + step_size * math.sin(angle)
        nx = max(x_lo + m, min(x_hi - m, nx))
        ny = max(y_lo + m, min(y_hi - m, ny))
        pts.append((nx, ny))
        x, y = nx, ny
    return pts


def vertical_drift_path(
    x: float,
    y_top: float,
    y_bottom: float,
) -> list[tuple[float, float]]:
    return [(x, y_top), (x, y_bottom)]


# ---------------------------------------------------------------------------
# Light path -> Track conversion
# ---------------------------------------------------------------------------


def path_to_tracks(
    waypoints: list[tuple[float, float]],
    duration: float,
) -> tuple[Track, Track]:
    """Constant-velocity linear interpolation along the path."""
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")

    # Arc-length parameterization for uniform speed
    dists = [0.0]
    for i in range(1, len(waypoints)):
        dx = waypoints[i][0] - waypoints[i - 1][0]
        dy = waypoints[i][1] - waypoints[i - 1][1]
        dists.append(dists[-1] + math.hypot(dx, dy))
    total = max(dists[-1], 1e-9)

    x_keys = []
    y_keys = []
    for i, (wx, wy) in enumerate(waypoints):
        t = (dists[i] / total) * duration
        x_keys.append(Key(t, wx, ease="linear"))
        y_keys.append(Key(t, wy, ease="linear"))

    return Track(x_keys, wrap=Wrap.CLAMP), Track(y_keys, wrap=Wrap.CLAMP)


# ---------------------------------------------------------------------------
# Scene assembly
# ---------------------------------------------------------------------------


def grid_bounds(
    positions: list[tuple[float, float]], margin: float
) -> tuple[float, float, float, float]:
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


def build_light_path(
    cfg: LightConfig,
    light_idx: int,
    bounds: tuple[float, float, float, float],
    spacing: float,
    rng: random.Random,
) -> list[tuple[float, float]]:
    if cfg.path_style == "vertical_drift":
        if cfg.n_lights == 1:
            lx = (bounds[0] + bounds[2]) / 2
        else:
            lx = bounds[0] + (bounds[2] - bounds[0]) * light_idx / (cfg.n_lights - 1)
        return vertical_drift_path(lx, bounds[3] + spacing * 0.5, bounds[1] - spacing * 0.5)
    elif cfg.path_style == "random_walk":
        return random_walk_path(rng, cfg.n_waypoints * 3, spacing * 0.8, bounds)
    else:
        return waypoint_path(rng, cfg.n_waypoints, bounds)


def build_animate(p: AnimParams, rng: random.Random):
    """Return an animate(ctx) -> Frame callable."""
    materials = build_materials(p.material)

    # Grid
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)

    # Materials per object
    mat_ids = assign_material_ids(len(positions), p.material, rng)

    # Shapes
    shapes: list[Circle | Polygon] = []
    for i, pos in enumerate(positions):
        shapes.append(build_object(i, pos, p.shape, mat_ids[i], rng))

    wall_shapes = mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall")

    # Light tracks
    gb = grid_bounds(positions, p.grid.spacing) if positions else (-1.0, -0.6, 1.0, 0.6)
    light_x_tracks: list[Track] = []
    light_y_tracks: list[Track] = []
    for li in range(p.light.n_lights):
        wps = build_light_path(p.light, li, gb, p.grid.spacing, rng)
        xt, yt = path_to_tracks(wps, DURATION)
        light_x_tracks.append(xt)
        light_y_tracks.append(yt)

    def animate(ctx: FrameContext) -> Frame:
        lights = []
        for li in range(p.light.n_lights):
            lx = light_x_tracks[li].s(ctx.time)
            ly = light_y_tracks[li].s(ctx.time)
            lights.append(PointLight(id=f"light_{li}", position=[lx, ly], intensity=1.0))

        scene = Scene(
            materials=materials,
            shapes=[*wall_shapes, *shapes],
            lights=lights,
        )
        return Frame(scene=scene, look=Look(exposure=p.exposure))

    return animate


# ---------------------------------------------------------------------------
# Random parameter samplers — one per config layer
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


def random_grid(rng: random.Random) -> GridConfig:
    spacing = rng.uniform(0.18, 0.30)
    cols = max(3, int(2.4 / spacing) + rng.randint(-1, 1))
    rows = max(3, int(1.4 / spacing) + rng.randint(-1, 1))
    offset_rows = rng.choice([True, False])
    hole_fraction = rng.choice([0.0, 0.0, 0.0, rng.uniform(0.05, 0.20)])
    return GridConfig(
        rows=rows, cols=cols, spacing=spacing, offset_rows=offset_rows, hole_fraction=hole_fraction
    )


def random_shape(rng: random.Random, spacing: float) -> ShapeConfig:
    kind = rng.choices(["circle", "polygon"], weights=[3, 2])[0]
    size = spacing * rng.uniform(0.22, 0.35)

    if kind == "circle":
        return ShapeConfig(kind="circle", size=size, n_sides=0, corner_radius=0.0, rotation=None)

    # Polygon
    n_sides = rng.choice([3, 4, 5, 6])
    corner_radius = rng.choice([0.0, 0.0, size * rng.uniform(0.05, 0.15)])

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


def random_material(rng: random.Random) -> MaterialConfig:
    style = rng.choices(["glass", "glass", "diffuse", "mixed"], weights=[4, 4, 1, 2])[0]

    ior = rng.choice([1.3, 1.5, 1.8, 2.0])
    cauchy_b = rng.uniform(10_000, 30_000)
    absorption = rng.uniform(0.2, 2.5)
    fill = rng.uniform(0.0, 0.15) if style != "diffuse" else 0.0

    # Color groups — gate: only for glass or mixed
    n_color_groups = 0
    color_names: list[str] = []
    if style in ("glass", "mixed"):
        n_color_groups = rng.choice([0, 0, 1, 2, 3])
        if n_color_groups > 0:
            color_names = rng.sample(PALETTE, min(n_color_groups, len(PALETTE)))

    diffuse_fraction = rng.uniform(0.15, 0.45) if style == "mixed" else 0.0

    return MaterialConfig(
        style=style,
        ior=ior,
        cauchy_b=cauchy_b,
        absorption=absorption,
        fill=fill,
        diffuse_fraction=diffuse_fraction,
        n_color_groups=n_color_groups,
        color_names=color_names,
    )


def random_light(rng: random.Random) -> LightConfig:
    n_lights = rng.choices([1, 2, 3], weights=[5, 3, 1])[0]
    path_style = rng.choice(["waypoints", "waypoints", "random_walk", "vertical_drift"])
    n_waypoints = rng.randint(5, 12)
    return LightConfig(n_lights=n_lights, path_style=path_style, n_waypoints=n_waypoints)


def random_params(rng: random.Random) -> AnimParams:
    grid = random_grid(rng)
    shape = random_shape(rng, grid.spacing)
    material = random_material(rng)
    light = random_light(rng)
    exposure = rng.uniform(-6.0, -4.0)
    return AnimParams(grid=grid, shape=shape, material=material, light=light, exposure=exposure)


# ---------------------------------------------------------------------------
# Beauty check
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = 500
RICHNESS_THRESHOLD = 0.15
MIN_COLORFUL_SECONDS = 2.5
PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360


def make_probe_shot() -> Shot:
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def check_beauty(p: AnimParams, rng: random.Random) -> tuple[bool, int, float]:
    """Render low-res frames and count colorful ones."""
    animate = build_animate(p, rng)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)

    n_frames = timeline.total_frames
    colorful = 0
    total_richness = 0.0

    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        rr = session.render_shot(cpp_shot, fi)
        cs = color_stats(rr.pixels, PROBE_W, PROBE_H)
        total_richness += cs.color_richness
        if cs.color_richness > RICHNESS_THRESHOLD:
            colorful += 1

    avg = total_richness / n_frames if n_frames > 0 else 0.0
    return colorful >= int(MIN_COLORFUL_SECONDS * PROBE_FPS), colorful, avg


# ---------------------------------------------------------------------------
# HQ render
# ---------------------------------------------------------------------------


def make_hq_shot(width: int = 1920, height: int = 1080, rays: int = 5_000_000) -> Shot:
    shot = Shot.preset("production", width=width, height=height, rays=rays, depth=12)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(
        exposure=-5.0,
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def render_and_save(
    p: AnimParams,
    out_dir: Path,
    build_seed: int,
    width: int = 1920,
    height: int = 1080,
    rays: int = 5_000_000,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "params.json").write_text(
        json.dumps({"params": asdict(p), "build_seed": build_seed}, indent=2)
    )

    animate = build_animate(p, random.Random(build_seed))
    settings = make_hq_shot(width, height, rays)
    timeline = Timeline(DURATION, fps=60)
    video_path = out_dir / "video.mp4"
    render(animate, timeline, str(video_path), settings=settings, crf=16)
    print(f"  video -> {video_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def describe_params(p: AnimParams) -> str:
    s = p.shape
    shape_desc = "circle" if s.kind == "circle" else f"{s.n_sides}-gon"
    if s.rotation:
        shape_desc += f" rot={math.degrees(s.rotation.base_angle):.0f}°"
        if s.rotation.jitter > 0:
            shape_desc += f"±{math.degrees(s.rotation.jitter):.0f}°"
    return (
        f"grid={p.grid.rows}x{p.grid.cols} {shape_desc} "
        f"mat={p.material.style} ior={p.material.ior:.1f} "
        f"lights={p.light.n_lights}({p.light.path_style}) "
        f"colors={p.material.n_color_groups}"
    )


def main() -> None:
    seed = (
        int(time.time())
        if "--seed" not in sys.argv
        else int(sys.argv[sys.argv.index("--seed") + 1])
    )
    target = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 1
    hq = "--hq" in sys.argv
    width = 1920 if hq else 320
    height = 1080 if hq else 180
    rays = 5_000_000 if hq else 2_000_000
    rng = random.Random(seed)
    print(f"seed={seed} target={target} hq={hq}")

    base_dir = Path("renders/families/crystal_field")
    found = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] {describe_params(p)} -- checking...", flush=True)

        beauty_rng = random.Random(rng.randint(0, 2**32))
        ok, n_colorful, avg_rich = check_beauty(p, beauty_rng)
        print(f"  colorful={n_colorful / PROBE_FPS:.1f}s avg={avg_rich:.3f}", flush=True)

        if not ok:
            continue

        found += 1
        out_dir = base_dir / f"{found:03d}"
        print(f"  FOUND #{found} -- rendering...")
        build_seed = rng.randint(0, 2**32)
        render_and_save(p, out_dir, build_seed, width, height, rays)
        print("  done.\n")

        if found >= target:
            break

    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")


if __name__ == "__main__":
    main()
