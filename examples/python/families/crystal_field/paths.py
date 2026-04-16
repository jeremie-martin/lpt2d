"""Light path generators and track conversion."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from anim import Key, Track, Wrap

from .channels import ChannelGraph, _shortest_path
from .params import LightConfig

Point = tuple[float, float]

_DRIFT_OBSTACLE_CANDIDATES = 8
_DRIFT_OBSTACLE_TARGET_FRACTION = 0.35
_OBSTACLE_SAMPLE_STEP = 0.01


@dataclass(frozen=True)
class CircleObstacle:
    center: Point
    radius: float


@dataclass(frozen=True)
class PolygonObstacle:
    vertices: tuple[Point, ...]


LightObstacle = CircleObstacle | PolygonObstacle


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
) -> list[Point]:
    return [(x, y_top), (x, y_bottom)]


def _distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _point_in_polygon(point: Point, vertices: tuple[Point, ...]) -> bool:
    if len(vertices) < 3:
        return False

    x, y = point
    inside = False
    j = len(vertices) - 1
    for i, (xi, yi) in enumerate(vertices):
        xj, yj = vertices[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_inside_obstacle(point: Point, obstacle: LightObstacle) -> bool:
    if isinstance(obstacle, CircleObstacle):
        dx = point[0] - obstacle.center[0]
        dy = point[1] - obstacle.center[1]
        return dx * dx + dy * dy <= obstacle.radius * obstacle.radius
    return _point_in_polygon(point, obstacle.vertices)


def _point_inside_any_obstacle(point: Point, obstacles: list[LightObstacle]) -> bool:
    return any(_point_inside_obstacle(point, obstacle) for obstacle in obstacles)


def path_obstacle_fraction(
    points: list[Point],
    obstacles: list[LightObstacle],
    *,
    sample_step: float = _OBSTACLE_SAMPLE_STEP,
) -> float:
    """Approximate the arc-length fraction of a path spent inside objects."""
    if len(points) < 2 or not obstacles:
        return 0.0

    total = 0.0
    inside = 0.0
    for start, end in zip(points, points[1:], strict=False):
        length = _distance(start, end)
        if length <= 1e-9:
            continue

        steps = max(1, math.ceil(length / max(sample_step, 1e-6)))
        step_length = length / steps
        for idx in range(steps):
            t = (idx + 0.5) / steps
            point = (
                start[0] + (end[0] - start[0]) * t,
                start[1] + (end[1] - start[1]) * t,
            )
            total += step_length
            if _point_inside_any_obstacle(point, obstacles):
                inside += step_length

    return inside / total if total > 0.0 else 0.0


def _append_to_distance(points: list[Point], target: Point, remaining: float) -> float:
    """Append a full or partial segment and return the distance consumed."""
    current = points[-1]
    seg = _distance(current, target)
    if seg <= 1e-9:
        return 0.0
    if seg > remaining:
        frac = remaining / seg
        points.append(
            (
                current[0] + (target[0] - current[0]) * frac,
                current[1] + (target[1] - current[1]) * frac,
            )
        )
        return remaining
    points.append(target)
    return seg


def _reflected_step(
    x: float,
    y: float,
    angle: float,
    distance: float,
    bounds: tuple[float, float, float, float],
    margin: float,
) -> tuple[float, float, float]:
    x_lo, y_lo, x_hi, y_hi = bounds
    nx = x + distance * math.cos(angle)
    ny = y + distance * math.sin(angle)

    if nx < x_lo + margin or nx > x_hi - margin:
        angle = math.pi - angle
        nx = x + distance * math.cos(angle)
    if ny < y_lo + margin or ny > y_hi - margin:
        angle = -angle
        ny = y + distance * math.sin(angle)

    nx = max(x_lo + margin, min(x_hi - margin, nx))
    ny = max(y_lo + margin, min(y_hi - margin, ny))
    return nx, ny, angle


def drift_path(
    total_distance: float,
    bounds: tuple[float, float, float, float],
    rng: random.Random,
) -> list[Point]:
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
    seg_base = max(span * 0.42, total_distance * 0.22)

    pts: list[Point] = [(x, y)]
    accumulated = 0.0
    previous_direction: tuple[float, float] | None = None

    while accumulated < total_distance:
        remaining = total_distance - accumulated
        seg = min(seg_base * rng.uniform(0.75, 1.35), remaining)
        best: tuple[float, float, float, float] | None = None

        for attempt in range(12):
            candidate_angle = angle if attempt == 0 else angle + rng.gauss(0, 0.65)
            nx, ny, reflected_angle = _reflected_step(x, y, candidate_angle, seg, bounds, m)
            dx = nx - x
            dy = ny - y
            step = math.hypot(dx, dy)
            if step < 1e-9:
                continue

            reverse_penalty = 0.0
            if previous_direction is not None:
                dot = (dx * previous_direction[0] + dy * previous_direction[1]) / step
                if dot < -0.55:
                    reverse_penalty = step
                    if attempt < 10:
                        continue

            score = step - reverse_penalty
            if best is None or score > best[0]:
                best = (score, nx, ny, reflected_angle)

        if best is None:
            break

        _, nx, ny, angle = best
        step = math.hypot(nx - x, ny - y)
        if step < 1e-9:
            break
        accumulated += step
        pts.append((nx, ny))
        previous_direction = ((nx - x) / step, (ny - y) / step)
        x, y = nx, ny
        angle += rng.gauss(0, 0.55)

    return pts if len(pts) >= 2 else [pts[0], pts[0]]


def obstacle_aware_drift_path(
    total_distance: float,
    bounds: tuple[float, float, float, float],
    rng: random.Random,
    obstacles: list[LightObstacle],
) -> list[Point]:
    """Pick a drift path that does not spend most of its length inside objects."""
    if not obstacles:
        return drift_path(total_distance, bounds, rng)

    best = drift_path(total_distance, bounds, rng)
    best_fraction = path_obstacle_fraction(best, obstacles)
    if best_fraction <= _DRIFT_OBSTACLE_TARGET_FRACTION:
        return best

    for _ in range(_DRIFT_OBSTACLE_CANDIDATES - 1):
        candidate = drift_path(total_distance, bounds, rng)
        fraction = path_obstacle_fraction(candidate, obstacles)
        if fraction < best_fraction:
            best = candidate
            best_fraction = fraction
            if best_fraction <= _DRIFT_OBSTACLE_TARGET_FRACTION:
                break

    return best


def _route_distance(graph: ChannelGraph, route: list[int]) -> float:
    return sum(
        _distance(graph.nodes[route[i - 1]], graph.nodes[route[i]])
        for i in range(1, len(route))
    )


def _mean_channel_edge_length(graph: ChannelGraph) -> float:
    lengths = [
        _distance(graph.nodes[i], graph.nodes[j])
        for i, neighbours in enumerate(graph.adj)
        for j in neighbours
        if i < j
    ]
    return sum(lengths) / len(lengths) if lengths else 0.0


def _pick_channel_route(
    graph: ChannelGraph,
    current: int,
    previous: int | None,
    min_distance: float,
    rng: random.Random,
) -> list[int]:
    long_routes: list[tuple[list[int], float]] = []
    non_backtracking_routes: list[tuple[list[int], float]] = []
    backtracking_routes: list[tuple[list[int], float]] = []

    for dest in range(len(graph.nodes)):
        if dest == current:
            continue

        route = _shortest_path(graph, current, dest)
        if len(route) < 2:
            continue

        distance = _route_distance(graph, route)
        if previous is not None and len(graph.adj[current]) > 1 and route[1] == previous:
            backtracking_routes.append((route, distance))
            continue

        non_backtracking_routes.append((route, distance))
        if distance >= min_distance:
            long_routes.append((route, distance))

    routes = long_routes or non_backtracking_routes or [
        item for item in backtracking_routes if item[1] >= min_distance
    ] or backtracking_routes
    if not routes:
        return [current]

    weights = [max(distance, 1e-6) ** 2 for _route, distance in routes]
    return rng.choices([route for route, _distance in routes], weights=weights, k=1)[0]


def channel_path(
    graph: ChannelGraph,
    total_distance: float,
    rng: random.Random,
) -> list[Point]:
    """Path through the corridor network by chaining shortest routes.

    Picks a random start node, then repeatedly selects longer corridor legs
    and follows the shortest route to each destination. Immediate backtracking
    is avoided when another route exists. Continues until the cumulative path
    length reaches *total_distance*.
    """
    if len(graph.nodes) < 2:
        return [(0.0, 0.0), (0.0, 0.0)]

    current = rng.randrange(len(graph.nodes))
    previous: int | None = None
    waypoints: list[Point] = [graph.nodes[current]]
    accumulated = 0.0
    mean_edge = _mean_channel_edge_length(graph)

    while accumulated < total_distance - 1e-9:
        remaining = total_distance - accumulated
        min_leg = min(remaining, max(mean_edge * 2.0, total_distance * 0.30))
        route = _pick_channel_route(graph, current, previous, min_leg, rng)
        if len(route) < 2:
            break  # graph is disconnected or degenerate

        for next_node in route[1:]:
            consumed = _append_to_distance(
                waypoints,
                graph.nodes[next_node],
                total_distance - accumulated,
            )
            if consumed <= 1e-9:
                accumulated = total_distance
                break
            accumulated += consumed
            if accumulated >= total_distance - 1e-9:
                break
            previous, current = current, next_node

    return waypoints if len(waypoints) >= 2 else [waypoints[0], waypoints[0]]


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


def build_light_path(
    cfg: LightConfig,
    light_idx: int,
    bounds: tuple[float, float, float, float],
    spacing: float,
    rng: random.Random,
    graph: ChannelGraph | None = None,
    obstacles: list[LightObstacle] | None = None,
    *,
    duration: float,
) -> list[tuple[float, float]]:
    total_dist = cfg.speed * duration

    if cfg.path_style == "drift":
        return obstacle_aware_drift_path(total_dist, bounds, rng, obstacles or [])

    if cfg.path_style == "channel":
        if graph is not None and len(graph.nodes) >= 2:
            return channel_path(graph, total_dist, rng)
        # Fallback: free drift if the grid is too small for a channel graph.
        return obstacle_aware_drift_path(total_dist, bounds, rng, obstacles or [])

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
