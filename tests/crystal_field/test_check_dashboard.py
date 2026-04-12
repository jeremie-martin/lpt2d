"""Dashboard model for the crystal_field rejection constraints."""

from __future__ import annotations

import importlib

from examples.python.families.crystal_field.check_dashboard import constraint_model

CHECK = importlib.import_module("examples.python.families.crystal_field.check")


def test_constraint_dashboard_model_matches_current_overrides():
    model = constraint_model()
    outcomes = {row["outcome"]: row for row in model["effective_outcomes"]}

    assert outcomes["glass"]["active"] == "no"
    assert outcomes["glass"]["mean"] == (
        f"{CHECK.MIN_MEAN_LUMINANCE:.1f} to {CHECK.GLASS_MAX_MEAN_LUMINANCE:.1f}"
    )
    assert outcomes["black_diffuse"]["shadow_fraction"] == (
        f"<= {100 * CHECK.BLACK_DIFFUSE_MAX_SHADOW_FRACTION:.1f}%"
    )
    assert outcomes["gray_diffuse"]["shadow_fraction"] == (
        f"<= {100 * CHECK.MAX_SHADOW_FRACTION:.1f}%"
    )


def test_constraint_dashboard_records_gate_order():
    model = constraint_model()
    order = model["check_order"]

    assert order[0]["metric"] == "moving_count"
    assert order[1]["metric"] == "ambient_count"
    assert order[-1]["metric"] == "mean_saturation"
    assert any(row["pass_rule"] == "outcome dependent" for row in order)
