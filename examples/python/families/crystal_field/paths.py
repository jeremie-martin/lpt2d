"""Light path generators and track conversion."""

from __future__ import annotations

import math
import random

from anim import Key, Track, Wrap

from .channels import ChannelGraph, _shortest_path
from .params import DURATION, LightConfig


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
