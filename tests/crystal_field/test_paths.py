"""Motion path tests for crystal_field."""

from __future__ import annotations

import math
import random

import pytest

from examples.python.families.crystal_field.channels import ChannelGraph
from examples.python.families.crystal_field.params import AmbientConfig, LightConfig
from examples.python.families.crystal_field.paths import (
    CircleObstacle,
    build_light_path,
    channel_path,
    obstacle_aware_drift_path,
    path_obstacle_fraction,
)


def _path_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(points[i - 1], points[i]) for i in range(1, len(points)))


def test_active_path_distance_scales_with_duration():
    light = LightConfig(
        n_lights=1,
        path_style="drift",
        n_waypoints=8,
        ambient=AmbientConfig(style="corners", intensity=0.3),
        speed=0.2,
    )
    bounds = (-10.0, -10.0, 10.0, 10.0)

    short = build_light_path(light, 0, bounds, 0.3, random.Random(9), duration=5.0)
    long = build_light_path(light, 0, bounds, 0.3, random.Random(9), duration=10.0)

    assert _path_length(short) == pytest.approx(1.0)
    assert _path_length(long) == pytest.approx(2.0)


def test_path_obstacle_fraction_measures_time_inside_objects():
    points = [(-1.0, 0.0), (1.0, 0.0)]
    obstacles = [CircleObstacle(center=(0.0, 0.0), radius=0.5)]

    assert path_obstacle_fraction(points, obstacles, sample_step=0.002) == pytest.approx(
        0.5,
        abs=0.01,
    )


def test_obstacle_aware_drift_keeps_distance_budget():
    points = obstacle_aware_drift_path(
        total_distance=1.5,
        bounds=(-1.0, -1.0, 1.0, 1.0),
        rng=random.Random(12),
        obstacles=[CircleObstacle(center=(0.0, 0.0), radius=0.35)],
    )

    assert _path_length(points) == pytest.approx(1.5)


def test_channel_path_avoids_immediate_backtracking_when_alternatives_exist():
    graph = ChannelGraph(
        nodes=[
            (0.0, 0.0),
            (1.0, 0.0),
            (2.0, 0.0),
            (1.0, 1.0),
            (2.0, 1.0),
        ],
        adj=[
            [1],
            [0, 2, 3],
            [1, 4],
            [1, 4],
            [2, 3],
        ],
    )

    points = channel_path(graph, total_distance=5.0, rng=random.Random(4))

    assert _path_length(points) == pytest.approx(5.0)
    triples = zip(points, points[1:], points[2:], strict=False)
    assert all(a != c for a, _b, c in triples)
