"""Unit tests for crystal_field rejection thresholds."""

from __future__ import annotations

import pytest

from examples.python.families.crystal_field.check import (
    MAX_AMBIENT_RADIUS_RATIO,
    MAX_MEAN_LUMINANCE,
    MAX_MOVING_RADIUS_RATIO,
    MAX_NEAR_BLACK_FRACTION,
    MAX_RADIUS_RATIO,
    MIN_AMBIENT_RADIUS_RATIO,
    MIN_CONTRAST_SPREAD,
    MIN_MOVING_RADIUS_RATIO,
    MIN_RADIUS_RATIO,
    _verdict_for_metrics,
)


def _passing_metrics() -> dict[str, float]:
    return {
        "mean": 120.0,
        "contrast_spread": 8.0,
        "near_black_fraction": 0.03,
        "moving_radius_min": 0.015,
        "moving_radius_mean": 0.024,
        "moving_radius_max": 0.035,
        "ambient_radius_min": 0.010,
        "ambient_radius_mean": 0.014,
        "ambient_radius_max": 0.025,
        "moving_to_ambient_radius_ratio": 1.71,
    }


def _verdict(metrics: dict[str, float], *, moving_count: int = 1, ambient_count: int = 4):
    return _verdict_for_metrics(
        metrics,
        moving_count=moving_count,
        ambient_count=ambient_count,
    )


def test_passing_metrics_are_accepted():
    assert _verdict(_passing_metrics()).ok


@pytest.mark.parametrize(
    ("override", "summary_token"),
    [
        ({"moving_radius_min": MIN_MOVING_RADIUS_RATIO - 0.001}, "moving_radius_min"),
        ({"moving_radius_max": MAX_MOVING_RADIUS_RATIO + 0.001}, "moving_radius_max"),
        ({"ambient_radius_min": MIN_AMBIENT_RADIUS_RATIO - 0.001}, "ambient_radius_min"),
        ({"ambient_radius_max": MAX_AMBIENT_RADIUS_RATIO + 0.001}, "ambient_radius_max"),
        (
            {"moving_to_ambient_radius_ratio": MIN_RADIUS_RATIO - 0.01},
            "moving_to_ambient_radius_ratio",
        ),
        (
            {"moving_to_ambient_radius_ratio": MAX_RADIUS_RATIO + 0.01},
            "moving_to_ambient_radius_ratio",
        ),
        ({"near_black_fraction": MAX_NEAR_BLACK_FRACTION + 0.001}, "near_black"),
        ({"mean": MAX_MEAN_LUMINANCE + 1.0}, "brightness"),
        ({"contrast_spread": MIN_CONTRAST_SPREAD - 0.1}, "contrast_spread"),
    ],
)
def test_rejection_thresholds(override: dict[str, float], summary_token: str):
    metrics = _passing_metrics()
    metrics.update(override)

    verdict = _verdict(metrics)

    assert not verdict.ok
    assert summary_token in verdict.summary


def test_missing_moving_lights_are_rejected():
    verdict = _verdict(_passing_metrics(), moving_count=0)
    assert not verdict.ok
    assert "no moving lights" in verdict.summary


def test_missing_ambient_lights_are_rejected():
    verdict = _verdict(_passing_metrics(), ambient_count=0)
    assert not verdict.ok
    assert "no ambient lights" in verdict.summary
