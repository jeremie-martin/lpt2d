"""Unit tests for crystal_field rejection thresholds."""

from __future__ import annotations

import pytest

from examples.python.families.crystal_field.check import (
    GLASS_MAX_MEAN_LUMA,
    MAX_BRIGHT_NEUTRAL_FRACTION,
    MAX_AMBIENT_RADIUS_RATIO,
    MAX_MEAN_LUMA,
    MAX_MEAN_SATURATION,
    MAX_MOVING_RADIUS_RATIO,
    MAX_NEAR_BLACK_FRACTION,
    MAX_P05_LUMA,
    MAX_RADIUS_RATIO,
    MIN_AMBIENT_RADIUS_RATIO,
    MIN_INTERDECILE_LUMA_RANGE,
    MIN_LOCAL_CONTRAST,
    MIN_MEAN_LUMA,
    MIN_MOVING_RADIUS_RATIO,
    MIN_RADIUS_RATIO,
    _verdict_for_metrics,
)


def _passing_metrics() -> dict[str, float]:
    return {
        "mean_luma": 0.35,
        "p05_luma": 0.10,
        "interdecile_luma_range": 0.40,
        "local_contrast": 0.03,
        "bright_neutral_fraction": 0.10,
        "near_black_fraction": 0.03,
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
        ({"mean_luma": MIN_MEAN_LUMA - 0.001}, "mean_luma"),
        ({"mean_luma": MAX_MEAN_LUMA + 0.001}, "mean_luma"),
        ({"p05_luma": MAX_P05_LUMA + 0.001}, "p05_luma"),
        (
            {"interdecile_luma_range": MIN_INTERDECILE_LUMA_RANGE - 0.001},
            "interdecile_luma_range",
        ),
        ({"local_contrast": MIN_LOCAL_CONTRAST - 0.001}, "local_contrast"),
        (
            {"bright_neutral_fraction": MAX_BRIGHT_NEUTRAL_FRACTION + 0.001},
            "bright_neutral",
        ),
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
    metrics["mean_luma"] = GLASS_MAX_MEAN_LUMA + 0.001

    verdict = _verdict(metrics, outcome="glass")

    assert not verdict.ok
    assert "mean_luma" in verdict.summary


def test_missing_moving_lights_are_rejected():
    verdict = _verdict(_passing_metrics(), moving_count=0)
    assert not verdict.ok
    assert "no moving lights" in verdict.summary


def test_missing_ambient_lights_are_rejected():
    verdict = _verdict(_passing_metrics(), ambient_count=0)
    assert not verdict.ok
    assert "no ambient lights" in verdict.summary
