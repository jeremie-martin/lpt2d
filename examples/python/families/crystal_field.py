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

Design history
--------------
First iteration used a flat AnimParams with 16+ fields.  This was
restructured into layered configs (GridConfig, ShapeConfig, etc.) so
that parameters gated by a feature live inside that feature's block.

The first 32-still survey revealed several problems:

- **Polygons + glass = chaos.**  Straight edges create harsh refraction
  fans that splatter light everywhere instead of focusing it into clean
  caustics the way circles do.  Solution: polygons are always opaque
  (diffuse, metallic-rough, or dark absorbing).  Circles keep glass.
  Exception: very small polygons with rounded corners can sometimes
  pull off glass, but it's risky.

- **Scenes too dark with one light.**  A single point light traveling
  through the grid left most of the scene in deep shadow.  Solution:
  fixed ambient point lights at corners (4) or sides (2) at full
  intensity.  These lift the base brightness so the traveling lights
  add variation on top of a readable scene rather than being the only
  source of visibility.

- **Fill=0 on glass objects.**  Without fill, glass circles are
  invisible until light refracts through them.  Solution: fill always
  0.08-0.18 for glass.

- **Polygon material variety.**  All-black polygons looked surprisingly
  good (clean silhouettes), but the lack of variety was limiting.
  Solution: three diffuse sub-styles:
  - *dark*: low albedo, no fill — black silhouettes.
  - *colored_fill*: moderate albedo + fill color — visible colored shapes.
  - *metallic_rough*: metallic=1, roughness=0.6 — brushed metal.

- **Corner radius on polygons.**  Sharp-cornered polygons look harsher
  and produce more problematic edge reflections.  Rounded corners
  soften the look.  Now always applied.

Architecture note
-----------------
The parameter space is organized as layered configs — each concern (grid,
shape, material, light) is a small focused dataclass with its own random
sampler and gating logic.  Parameters that only matter when a feature is
enabled (e.g., rotation angles for polygons, diffuse sub-style for opaque
materials) live inside that feature's config block rather than in a flat
bag.  This keeps the sampling code readable as new knobs are added.

The ``build_seed`` field inside Params ensures that any saved variant can
be exactly reproduced from its params JSON alone.
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass, field

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
    glass,
    mirror_box,
    regular_polygon,
    render_frame,
)
from anim.family import Family, Verdict, probe

from .light_circle import LightCircle, measure_light_circles

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
    from anim import diffuse as diffuse_mat

    mats: dict[str, Material] = {WALL_ID: WALL}

    if cfg.style == "glass":
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

    elif cfg.style == "diffuse":
        if cfg.diffuse_style == "dark":
            # Low albedo, no fill — black silhouettes that absorb most light.
            # Colors are irrelevant for dark style — all objects look the same.
            mats["crystal"] = Material(albedo=0.15, transmission=0.0)
        elif cfg.diffuse_style == "colored_fill":
            # Visible colored interior via fill
            mats["crystal"] = diffuse_mat(0.7, fill=cfg.fill)
            for i, cname in enumerate(cfg.color_names):
                mats[f"crystal_c{i}"] = diffuse_mat(0.7, color=cname, fill=max(cfg.fill, 0.10))
        elif cfg.diffuse_style == "metallic_rough":
            # Brushed metal look — reflects light softly
            mats["crystal"] = Material(
                metallic=1.0, roughness=0.6, albedo=0.8, transmission=0.0, fill=cfg.fill
            )
            for i, cname in enumerate(cfg.color_names):
                from anim import mirror as mirror_mat

                mats[f"crystal_c{i}"] = mirror_mat(0.8, roughness=0.6, color=cname, fill=cfg.fill)

    return mats


def assign_material_ids(
    n_objects: int,
    cfg: MaterialConfig,
) -> list[str]:
    n_colors = len(cfg.color_names)
    ids: list[str] = []
    for i in range(n_objects):
        if n_colors > 0:
            ids.append(f"crystal_c{i % n_colors}")
        else:
            ids.append("crystal")
    return ids


# ---------------------------------------------------------------------------
# Channel graph — corridor network between grid objects
# ---------------------------------------------------------------------------


@dataclass
class ChannelGraph:
    """Navigable corridor network between grid objects.

    Nodes sit at the centres of interstitial cells (the spaces between
    objects).  Edges connect adjacent cells through the gaps.
    """

    nodes: list[tuple[float, float]]
    adj: list[list[int]]  # adj[i] = indices of neighbours of node i


def _build_channel_graph_regular(
    rows: int,
    cols: int,
    spacing: float,
    x0: float,
    y0: float,
) -> ChannelGraph:
    """Dual grid for a non-offset rectangular lattice.

    Each rectangular cell formed by four neighbouring objects becomes a
    node at its centre.  Adjacent cells (sharing a side) are connected.
    """
    nodes: list[tuple[float, float]] = []
    idx: dict[tuple[int, int], int] = {}

    for r in range(rows - 1):
        for c in range(cols - 1):
            idx[(r, c)] = len(nodes)
            nodes.append((x0 + (c + 0.5) * spacing, y0 + (r + 0.5) * spacing))

    adj: list[list[int]] = [[] for _ in range(len(nodes))]
    for (r, c), i in idx.items():
        for dr, dc in [(0, 1), (1, 0)]:
            nb = (r + dr, c + dc)
            if nb in idx:
                j = idx[nb]
                adj[i].append(j)
                adj[j].append(i)

    return ChannelGraph(nodes, adj)


def _build_channel_graph_offset(
    rows: int,
    cols: int,
    spacing: float,
    x0: float,
    y0: float,
) -> ChannelGraph:
    """Dual graph for a brick-stagger (offset rows) lattice.

    Between each pair of consecutive rows the stagger creates triangular
    cells.  Each triangle becomes a node at its centroid; triangles sharing
    an edge of the triangulation are adjacent in the channel graph.
    """
    s = spacing
    nodes: list[tuple[float, float]] = []

    # Map each edge of the object triangulation (pair of object ids) to
    # the triangle indices that border it.  Two triangles sharing an edge
    # are adjacent corridor junctions.
    edge_to_tris: dict[frozenset[int], list[int]] = {}

    def obj_id(r: int, c: int) -> int:
        return r * cols + c

    def add_triangle(verts: list[tuple[int, int]], centroid: tuple[float, float]) -> None:
        tri_idx = len(nodes)
        nodes.append(centroid)
        ids = [obj_id(r, c) for r, c in verts]
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                edge = frozenset((ids[a], ids[b]))
                edge_to_tris.setdefault(edge, []).append(tri_idx)

    for r in range(rows - 1):
        yr = y0 + r * s
        if r % 2 == 0:
            # Even → odd transition.
            # "Up" triangles: (r,c), (r,c+1), (r+1,c)
            for c in range(cols - 1):
                add_triangle(
                    [(r, c), (r, c + 1), (r + 1, c)],
                    (x0 + c * s + s / 2, yr + s / 3),
                )
            # "Down" triangles: (r,c), (r+1,c-1), (r+1,c)
            for c in range(1, cols):
                add_triangle(
                    [(r, c), (r + 1, c - 1), (r + 1, c)],
                    (x0 + c * s, yr + 2 * s / 3),
                )
        else:
            # Odd → even transition.
            # Type A: (r,c), (r+1,c), (r+1,c+1)
            for c in range(cols - 1):
                add_triangle(
                    [(r, c), (r + 1, c), (r + 1, c + 1)],
                    (x0 + c * s + s / 2, yr + 2 * s / 3),
                )
            # Type B: (r,c), (r,c+1), (r+1,c+1)
            for c in range(cols - 1):
                add_triangle(
                    [(r, c), (r, c + 1), (r + 1, c + 1)],
                    (x0 + (c + 1) * s, yr + s / 3),
                )

    adj: list[list[int]] = [[] for _ in range(len(nodes))]
    for tris in edge_to_tris.values():
        for a in range(len(tris)):
            for b in range(a + 1, len(tris)):
                adj[tris[a]].append(tris[b])
                adj[tris[b]].append(tris[a])

    return ChannelGraph(nodes, adj)


def build_channel_graph(cfg: GridConfig) -> ChannelGraph:
    """Build the corridor junction graph for a grid configuration.

    The graph represents the navigable interstitial space between grid
    objects.  Lights using the ``"channel"`` path style walk this graph.

    NOTE: the graph is built from the full grid before hole removal.
    Holes could open shortcuts through the corridor network — this is
    a consideration for future experimentation.
    """
    if cfg.rows < 2 or cfg.cols < 2:
        return ChannelGraph([], [])
    grid_w = (cfg.cols - 1) * cfg.spacing
    grid_h = (cfg.rows - 1) * cfg.spacing
    x0 = -grid_w / 2
    y0 = -grid_h / 2
    if cfg.offset_rows:
        return _build_channel_graph_offset(cfg.rows, cfg.cols, cfg.spacing, x0, y0)
    return _build_channel_graph_regular(cfg.rows, cfg.cols, cfg.spacing, x0, y0)


def _shortest_path(graph: ChannelGraph, start: int, end: int) -> list[int]:
    """Dijkstra shortest path on the channel graph.  Returns node indices."""
    n = len(graph.nodes)
    dist = [float("inf")] * n
    prev = [-1] * n
    dist[start] = 0.0
    heap: list[tuple[float, int]] = [(0.0, start)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        if u == end:
            break
        for v in graph.adj[u]:
            dx = graph.nodes[v][0] - graph.nodes[u][0]
            dy = graph.nodes[v][1] - graph.nodes[u][1]
            nd = d + math.hypot(dx, dy)
            if nd < dist[v]:
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    path: list[int] = []
    u = end
    while u != -1:
        path.append(u)
        u = prev[u]
    path.reverse()
    return path if path and path[0] == start else [start]


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


def drift_path(
    total_distance: float,
    bounds: tuple[float, float, float, float],
    rng: random.Random,
) -> list[tuple[float, float]]:
    """Free-movement constant-speed path with random direction changes.

    The light moves in straight segments, turning by a random angle at each
    segment boundary.  Reflects off the grid bounds.  Total path length
    equals *total_distance* for constant-speed playback.
    """
    x_lo, y_lo, x_hi, y_hi = bounds
    m = 0.05
    x = rng.uniform(x_lo + m, x_hi - m)
    y = rng.uniform(y_lo + m, y_hi - m)
    angle = rng.uniform(0, 2 * math.pi)

    span = max(x_hi - x_lo, y_hi - y_lo)
    seg_base = span * 0.3

    pts: list[tuple[float, float]] = [(x, y)]
    accumulated = 0.0

    while accumulated < total_distance:
        seg = min(seg_base * rng.uniform(0.5, 1.5), total_distance - accumulated)
        nx = x + seg * math.cos(angle)
        ny = y + seg * math.sin(angle)
        # Boundary reflection
        if nx < x_lo + m or nx > x_hi - m:
            angle = math.pi - angle
            nx = x + seg * math.cos(angle)
        if ny < y_lo + m or ny > y_hi - m:
            angle = -angle
            ny = y + seg * math.sin(angle)
        nx = max(x_lo + m, min(x_hi - m, nx))
        ny = max(y_lo + m, min(y_hi - m, ny))
        step = math.hypot(nx - x, ny - y)
        if step < 1e-9:
            break  # stuck at boundary — close enough
        accumulated += step
        pts.append((nx, ny))
        x, y = nx, ny
        angle += rng.gauss(0, 0.8)

    return pts if len(pts) >= 2 else [pts[0], pts[0]]


def channel_path(
    graph: ChannelGraph,
    total_distance: float,
    rng: random.Random,
) -> list[tuple[float, float]]:
    """Path through the corridor network by chaining shortest routes.

    Picks a random start node, then repeatedly selects random destination
    nodes and follows the shortest corridor path to each one.  Continues
    until the cumulative path length reaches *total_distance*.
    """
    if len(graph.nodes) < 2:
        return [(0.0, 0.0), (0.0, 0.0)]

    current = rng.randrange(len(graph.nodes))
    waypoints: list[tuple[float, float]] = [graph.nodes[current]]
    accumulated = 0.0

    while accumulated < total_distance:
        # Pick a random destination different from the current node.
        dest = rng.randrange(len(graph.nodes))
        if dest == current:
            dest = (dest + 1) % len(graph.nodes)

        route = _shortest_path(graph, current, dest)
        if len(route) < 2:
            break  # graph is disconnected or degenerate

        for i in range(1, len(route)):
            px, py = graph.nodes[route[i]]
            seg = math.hypot(px - waypoints[-1][0], py - waypoints[-1][1])

            if accumulated + seg >= total_distance:
                # Partial segment to hit the exact target distance.
                frac = (total_distance - accumulated) / seg if seg > 0 else 0
                waypoints.append(
                    (
                        waypoints[-1][0] + (px - waypoints[-1][0]) * frac,
                        waypoints[-1][1] + (py - waypoints[-1][1]) * frac,
                    )
                )
                accumulated = total_distance
                break

            waypoints.append((px, py))
            accumulated += seg

        current = route[-1]

    return waypoints if len(waypoints) >= 2 else [waypoints[0], waypoints[0]]


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
    graph: ChannelGraph | None = None,
) -> list[tuple[float, float]]:
    total_dist = cfg.speed * DURATION

    if cfg.path_style == "drift":
        return drift_path(total_dist, bounds, rng)

    if cfg.path_style == "channel":
        if graph is not None and len(graph.nodes) >= 2:
            return channel_path(graph, total_dist, rng)
        # Fallback: free drift if the grid is too small for a channel graph.
        return drift_path(total_dist, bounds, rng)

    # Legacy styles (speed field is ignored; timing comes from path length).
    if cfg.path_style == "vertical_drift":
        if cfg.n_lights == 1:
            lx = (bounds[0] + bounds[2]) / 2
        else:
            lx = bounds[0] + (bounds[2] - bounds[0]) * light_idx / (cfg.n_lights - 1)
        return vertical_drift_path(lx, bounds[3] + spacing * 0.5, bounds[1] - spacing * 0.5)
    elif cfg.path_style == "random_walk":
        return random_walk_path(rng, cfg.n_waypoints * 3, spacing * 0.8, bounds)
    elif cfg.path_style == "waypoints":
        return waypoint_path(rng, cfg.n_waypoints, bounds)
    else:
        raise ValueError(f"Unknown path_style: {cfg.path_style!r}")


def build(p: Params):
    """Build an animate(ctx) -> Frame callable from params."""
    rng = random.Random(p.build_seed)
    materials = build_materials(p.material)

    # Grid
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)

    # Materials per object
    mat_ids = assign_material_ids(len(positions), p.material)

    # Shapes
    shapes: list[Circle | Polygon] = []
    for i, pos in enumerate(positions):
        shapes.append(build_object(i, pos, p.shape, mat_ids[i], rng))

    wall_shapes = mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall")

    # Channel graph (built once, shared by all channel-mode lights)
    ch_graph = build_channel_graph(p.grid) if p.light.path_style == "channel" else None

    # Light tracks
    # Tight margin keeps moving lights inside the grid rather than
    # wandering to the mirror-box edges where they overlap with ambient.
    gb = grid_bounds(positions, p.grid.spacing * 0.3) if positions else (-0.8, -0.5, 0.8, 0.5)
    light_x_tracks: list[Track] = []
    light_y_tracks: list[Track] = []
    for li in range(p.light.n_lights):
        wps = build_light_path(p.light, li, gb, p.grid.spacing, rng, ch_graph)
        xt, yt = path_to_tracks(wps, DURATION)
        light_x_tracks.append(xt)
        light_y_tracks.append(yt)

    # Fixed ambient lights
    ambient_lights: list[PointLight] = []
    amb = p.light.ambient
    if amb.style == "corners":
        for i, (ax, ay) in enumerate([(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]):
            ambient_lights.append(
                PointLight(id=f"amb_{i}", position=[ax, ay], intensity=amb.intensity)
            )
    elif amb.style == "sides":
        for i, (ax, ay) in enumerate([(-1.4, 0.0), (1.4, 0.0)]):
            ambient_lights.append(
                PointLight(id=f"amb_{i}", position=[ax, ay], intensity=amb.intensity)
            )

    def animate(ctx: FrameContext) -> Frame:
        lights = list(ambient_lights)
        for li in range(p.light.n_lights):
            lx = light_x_tracks[li].s(ctx.time)
            ly = light_y_tracks[li].s(ctx.time)
            lights.append(PointLight(
                id=f"light_{li}", position=[lx, ly], intensity=1.0,
                wavelength_min=p.light.wavelength_min,
                wavelength_max=p.light.wavelength_max,
            ))

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
    corner_radius = size * rng.uniform(0.05, 0.20)

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

    ior = rng.choice([1.3, 1.5, 1.8, 2.0])
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

    # Color groups
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
    amb_style = rng.choices(["corners", "sides", "none"], weights=[4, 3, 1])[0]
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
    shape = random_shape(rng, grid.spacing)
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


# ---------------------------------------------------------------------------
# Check — colour richness + light circle quality
# ---------------------------------------------------------------------------

RICHNESS_THRESHOLD = 0.15
MIN_COLORFUL_SECONDS = 2.5

# Light circle thresholds (at probe resolution 640×360).
MAX_BACKGROUND = 0.92  # reject if scene is washed out
MIN_MOVING_RADIUS_PX = 5.0  # moving light must be a visible blob
MAX_MOVING_RADIUS_PX = 60.0  # not a featureless wash
MAX_RADIUS_RATIO = 2.0  # max moving / ambient circle size ratio
MIN_SHARPNESS = 0.008  # minimum edge definition

PROBE_W, PROBE_H, PROBE_RAYS = 640, 360, 200_000


def _min_object_distance(
    light_pos: tuple[float, float],
    object_positions: list[tuple[float, float]],
) -> float:
    """Minimum Euclidean distance from a light to any object centre."""
    if not object_positions:
        return float("inf")
    return min(
        math.hypot(light_pos[0] - ox, light_pos[1] - oy)
        for ox, oy in object_positions
    )


def _find_clear_frame(
    animate,
    duration: float,
    object_positions: list[tuple[float, float]],
    fps: int = 4,
) -> int:
    """Frame index where moving lights are furthest from objects.

    Calls ``animate()`` without rendering to inspect light positions.
    Returns the single best frame index for circle measurement.
    """
    timeline = Timeline(duration, fps=fps)
    best_idx = 0
    best_clearance = -1.0

    for fi in range(timeline.total_frames):
        ctx = timeline.context_at(fi)
        frame = animate(ctx)
        moving = [
            (l.position[0], l.position[1])
            for l in frame.scene.lights
            if l.id.startswith("light_")
        ]
        if not moving:
            continue
        # Worst-case clearance across all moving lights in this frame.
        clearance = min(_min_object_distance(lp, object_positions) for lp in moving)
        if clearance > best_clearance:
            best_clearance = clearance
            best_idx = fi

    return best_idx


_PROBE_CAMERA = Camera2D(center=[0, 0], width=3.2)


def _measure_circles_at_frame(
    animate,
    frame_idx: int,
    duration: float,
) -> list[LightCircle]:
    """Render one probe-quality frame and measure all light circles."""
    probe_shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=PROBE_RAYS, depth=10)
    rr = render_frame(
        animate, Timeline(duration, fps=4),
        frame=frame_idx, settings=probe_shot, camera=_PROBE_CAMERA,
    )

    # Extract light positions from the animate callback's scene (call again;
    # render_frame already called it internally, but the result isn't exposed).
    ctx = Timeline(duration, fps=4).context_at(frame_idx)
    frame_result = animate(ctx)
    positions = [(l.position[0], l.position[1]) for l in frame_result.scene.lights]
    labels = [l.id for l in frame_result.scene.lights]

    return measure_light_circles(
        rr.pixels, PROBE_W, PROBE_H, positions,
        camera_center=(float(_PROBE_CAMERA.center[0]), float(_PROBE_CAMERA.center[1])),
        camera_width=float(_PROBE_CAMERA.width),
        labels=labels,
    )


def check(p: Params, animate) -> Verdict:
    # --- colour richness (existing) ---
    frames = probe(animate, DURATION)
    colorful = sum(1 for f in frames if f.color_richness > RICHNESS_THRESHOLD)
    colorful_s = colorful / 4  # probe runs at 4 fps
    avg = sum(f.color_richness for f in frames) / len(frames)
    if colorful_s < MIN_COLORFUL_SECONDS:
        return Verdict(False, f"color={colorful_s:.1f}s avg={avg:.3f}")

    # --- light circle quality ---
    # Reconstruct object positions (same RNG sequence as build()).
    rng = random.Random(p.build_seed)
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)

    best_fi = _find_clear_frame(animate, DURATION, positions)
    circles = _measure_circles_at_frame(animate, best_fi, DURATION)

    moving = [c for c in circles if c.label.startswith("light_")]
    ambient = [c for c in circles if c.label.startswith("amb_")]

    # All moving lights must be distinguishable.
    if not moving:
        return Verdict(False, f"color={colorful_s:.1f}s -- no moving lights")

    # Background saturation check.
    avg_bg = sum(c.background for c in circles) / len(circles) if circles else 0
    if avg_bg > MAX_BACKGROUND:
        return Verdict(False, f"color={colorful_s:.1f}s bg={avg_bg:.2f} (washed)")

    # Moving light radius bounds.
    med_moving_r = sorted(c.radius_px for c in moving)[len(moving) // 2]
    if med_moving_r < MIN_MOVING_RADIUS_PX:
        return Verdict(False, f"color={colorful_s:.1f}s moving_r={med_moving_r:.1f}px (too small)")
    if med_moving_r > MAX_MOVING_RADIUS_PX:
        return Verdict(False, f"color={colorful_s:.1f}s moving_r={med_moving_r:.1f}px (too large)")

    # Sharpness floor.
    min_sharp = min(c.sharpness for c in moving)
    if min_sharp < MIN_SHARPNESS:
        return Verdict(False, f"color={colorful_s:.1f}s sharp={min_sharp:.4f} (too soft)")

    # Ambient/moving ratio (only when ambient lights exist).
    ratio_msg = ""
    if ambient:
        med_amb_r = sorted(c.radius_px for c in ambient)[len(ambient) // 2]
        if med_amb_r > 0:
            ratio = med_moving_r / med_amb_r
            if ratio > MAX_RADIUS_RATIO:
                return Verdict(
                    False,
                    f"color={colorful_s:.1f}s ratio={ratio:.1f} (moving {med_moving_r:.0f}px / amb {med_amb_r:.0f}px)",
                )
            ratio_msg = f" ratio={ratio:.1f}"

    return Verdict(
        True,
        f"color={colorful_s:.1f}s moving_r={med_moving_r:.0f}px sharp={min_sharp:.3f}{ratio_msg}",
    )


# ---------------------------------------------------------------------------
# Describe
# ---------------------------------------------------------------------------


def describe(p: Params) -> str:
    s = p.shape
    shape_desc = "circle" if s.kind == "circle" else f"{s.n_sides}-gon"
    if s.rotation:
        shape_desc += f" rot={math.degrees(s.rotation.base_angle):.0f}\u00b0"
        if s.rotation.jitter > 0:
            shape_desc += f"\u00b1{math.degrees(s.rotation.jitter):.0f}\u00b0"
    mat_desc = p.material.style
    if p.material.style == "diffuse":
        mat_desc = f"diffuse/{p.material.diffuse_style}"
    amb = p.light.ambient.style if p.light.ambient.style != "none" else ""
    light_desc = f"lights={p.light.n_lights}({p.light.path_style})"
    if p.light.path_style in ("drift", "channel"):
        light_desc += f" v={p.light.speed:.2f}"
    if p.light.wavelength_max - p.light.wavelength_min < 300:
        light_desc += f" wl={p.light.wavelength_min:.0f}-{p.light.wavelength_max:.0f}"
    return (
        f"grid={p.grid.rows}x{p.grid.cols} {shape_desc} "
        f"mat={mat_desc} "
        f"{light_desc} "
        f"colors={p.material.n_color_groups}" + (f" amb={amb}" if amb else "")
    )


# ---------------------------------------------------------------------------
# Family definition
# ---------------------------------------------------------------------------

FAMILY = Family(
    "crystal_field",
    DURATION,
    Params,
    sample,
    build,
    check=check,
    describe=describe,
)

if __name__ == "__main__":
    FAMILY.main()
