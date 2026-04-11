"""Unit tests for crystal_field rejection thresholds."""

from __future__ import annotations

import pytest

from examples.python.families.crystal_field.check import (
    BLACK_DIFFUSE_MAX_SHADOW_FRACTION,
    GLASS_MAX_MEAN_LUMINANCE,
    MAX_AMBIENT_RADIUS_RATIO,
    MAX_MEAN_LUMINANCE,
    MAX_MEAN_SATURATION,
    MAX_MOVING_RADIUS_RATIO,
    MAX_NEAR_BLACK_FRACTION,
    MAX_RADIUS_RATIO,
    MAX_SHADOW_FLOOR,
    MAX_SHADOW_FRACTION,
    MIN_AMBIENT_RADIUS_RATIO,
    MIN_CONTRAST_SPREAD,
    MIN_MEAN_LUMINANCE,
    MIN_MOVING_RADIUS_RATIO,
    MIN_RADIUS_RATIO,
    _verdict_for_metrics,
)


def _passing_metrics() -> dict[str, float]:
    return {
        "mean": 100.0,
        "shadow_floor": 50.0,
        "contrast_spread": 80.0,
        "near_black_fraction": 0.03,
        "shadow_fraction": 0.10,
        "mean_saturation": 0.40,
        "moving_radius_min": 0.015,
        "moving_radius_mean": 0.024,
        "moving_radius_max": 0.035,
        "ambient_radius_min": 0.010,
        "ambient_radius_mean": 0.014,
        "ambient_radius_max": 0.025,
        "moving_to_ambient_radius_ratio": 1.71,
    }


def _verdict(
    metrics: dict[str, float],
    *,
    moving_count: int = 1,
    ambient_count: int = 4,
    outcome: str | None = None,
):
    return _verdict_for_metrics(
        metrics,
        moving_count=moving_count,
        ambient_count=ambient_count,
        outcome=outcome,
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
        ({"mean": MIN_MEAN_LUMINANCE - 1.0}, "brightness"),
        ({"mean": MAX_MEAN_LUMINANCE + 1.0}, "brightness"),
        ({"shadow_floor": MAX_SHADOW_FLOOR + 1.0}, "shadows"),
        ({"contrast_spread": MIN_CONTRAST_SPREAD - 0.1}, "contrast_spread"),
        ({"shadow_fraction": MAX_SHADOW_FRACTION + 0.001}, "shadow_pixels"),
        ({"mean_saturation": MAX_MEAN_SATURATION}, "saturation"),
    ],
)
def test_rejection_thresholds(override: dict[str, float], summary_token: str):
    metrics = _passing_metrics()
    metrics.update(override)

    verdict = _verdict(metrics)

    assert not verdict.ok
    assert summary_token in verdict.summary


def test_glass_uses_lower_brightness_ceiling():
    metrics = _passing_metrics()
    metrics["mean"] = GLASS_MAX_MEAN_LUMINANCE + 1.0

    verdict = _verdict(metrics, outcome="glass")

    assert not verdict.ok
    assert "brightness" in verdict.summary


def test_black_diffuse_uses_relaxed_shadow_pixel_ceiling():
    metrics = _passing_metrics()
    metrics["shadow_fraction"] = MAX_SHADOW_FRACTION + 0.05

    assert _verdict(metrics, outcome="black_diffuse").ok

    metrics["shadow_fraction"] = BLACK_DIFFUSE_MAX_SHADOW_FRACTION + 0.001
    verdict = _verdict(metrics, outcome="black_diffuse")

    assert not verdict.ok
    assert "shadow_pixels" in verdict.summary


def test_missing_moving_lights_are_rejected():
    verdict = _verdict(_passing_metrics(), moving_count=0)
    assert not verdict.ok
    assert "no moving lights" in verdict.summary


def test_missing_ambient_lights_are_rejected():
    verdict = _verdict(_passing_metrics(), ambient_count=0)
    assert not verdict.ok
    assert "no ambient lights" in verdict.summary
