"""Curated arc-focused clean-room scenes."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import make_arc_cluster_spec
from anim.examples._clean_room_shared import SceneSpec, with_family

FAMILY = "arcs"


def _arc(
    name: str,
    description: str,
    *,
    ring_count: int,
    orbit_rx: float,
    orbit_ry: float,
    arc_radius: float,
    local_start: float,
    local_sweep: float,
    beam_layout: str,
    base_exposure: float,
    support_fill: float = 0.0,
    spin_rate: float = 0.16,
    wobble: float = 0.14,
    core_radius: float = 0.07,
) -> SceneSpec:
    return with_family(
        make_arc_cluster_spec(
            name,
            description,
            ring_count=ring_count,
            orbit_rx=orbit_rx,
            orbit_ry=orbit_ry,
            arc_radius=arc_radius,
            local_start=local_start,
            local_sweep=local_sweep,
            beam_layout=beam_layout,
            base_exposure=base_exposure,
            support_fill=support_fill,
            spin_rate=spin_rate,
            wobble=wobble,
            core_radius=core_radius,
        ),
        FAMILY,
    )


_THEMES = [
    (
        "bloom",
        "Four mirrored crescents orbit a bright core",
        dict(
            ring_count=4,
            orbit_rx=0.58,
            orbit_ry=0.32,
            arc_radius=0.31,
            local_start=0.18 * math.pi,
            local_sweep=0.92 * math.pi,
            spin_rate=0.16,
            wobble=0.14,
            core_radius=0.07,
            base_exposure=3.10,
        ),
    ),
    (
        "lantern",
        "A lantern cage of arcs frames the beam",
        dict(
            ring_count=5,
            orbit_rx=0.52,
            orbit_ry=0.40,
            arc_radius=0.26,
            local_start=-0.05 * math.pi,
            local_sweep=1.16 * math.pi,
            spin_rate=0.13,
            wobble=0.10,
            core_radius=0.06,
            base_exposure=3.18,
        ),
    ),
    (
        "crown",
        "A shallow crown of crescents opens overhead",
        dict(
            ring_count=4,
            orbit_rx=0.70,
            orbit_ry=0.36,
            arc_radius=0.29,
            local_start=0.06 * math.pi,
            local_sweep=1.02 * math.pi,
            spin_rate=0.10,
            wobble=0.12,
            core_radius=0.06,
            base_exposure=3.15,
        ),
    ),
    (
        "bridge",
        "A compact arc bridge spans the center gap",
        dict(
            ring_count=3,
            orbit_rx=0.82,
            orbit_ry=0.22,
            arc_radius=0.36,
            local_start=0.24 * math.pi,
            local_sweep=0.84 * math.pi,
            spin_rate=0.11,
            wobble=0.08,
            core_radius=0.07,
            base_exposure=3.22,
        ),
    ),
    (
        "exchange",
        "Two arc families trade the spotlight across the room",
        dict(
            ring_count=2,
            orbit_rx=0.76,
            orbit_ry=0.28,
            arc_radius=0.33,
            local_start=0.08 * math.pi,
            local_sweep=1.10 * math.pi,
            spin_rate=0.18,
            wobble=0.16,
            core_radius=0.07,
            base_exposure=3.14,
        ),
    ),
    (
        "weave",
        "A crescent weave bends through a warm-white wash",
        dict(
            ring_count=6,
            orbit_rx=0.62,
            orbit_ry=0.34,
            arc_radius=0.27,
            local_start=0.14 * math.pi,
            local_sweep=0.88 * math.pi,
            spin_rate=0.17,
            wobble=0.13,
            core_radius=0.06,
            base_exposure=3.12,
        ),
    ),
    (
        "halo",
        "A halo of arcs rotates around a glass core",
        dict(
            ring_count=5,
            orbit_rx=0.66,
            orbit_ry=0.42,
            arc_radius=0.25,
            local_start=-0.10 * math.pi,
            local_sweep=1.20 * math.pi,
            spin_rate=0.14,
            wobble=0.11,
            core_radius=0.06,
            base_exposure=3.20,
        ),
    ),
    (
        "gate",
        "A shutter-like arc set breathes open and closed",
        dict(
            ring_count=4,
            orbit_rx=0.56,
            orbit_ry=0.46,
            arc_radius=0.30,
            local_start=0.28 * math.pi,
            local_sweep=0.78 * math.pi,
            spin_rate=0.09,
            wobble=0.10,
            core_radius=0.06,
            base_exposure=3.18,
        ),
    ),
    (
        "crossfire",
        "A crossfire of crescents keeps the room lit",
        dict(
            ring_count=4,
            orbit_rx=0.74,
            orbit_ry=0.30,
            arc_radius=0.28,
            local_start=0.02 * math.pi,
            local_sweep=1.00 * math.pi,
            spin_rate=0.15,
            wobble=0.15,
            core_radius=0.07,
            base_exposure=3.16,
        ),
    ),
    (
        "stack",
        "A tall arc stack climbs through the center",
        dict(
            ring_count=5,
            orbit_rx=0.44,
            orbit_ry=0.52,
            arc_radius=0.24,
            local_start=-0.16 * math.pi,
            local_sweep=1.06 * math.pi,
            spin_rate=0.12,
            wobble=0.09,
            core_radius=0.05,
            base_exposure=3.25,
        ),
    ),
]


_VARIANTS = [
    (
        "compact",
        "in a compact dual-side beam layout",
        dict(
            beam_layout="dual_side",
            orbit_rx_scale=0.92,
            orbit_ry_scale=0.96,
            arc_radius_scale=0.94,
            local_start_shift=0.00,
            local_sweep_scale=0.96,
            base_exposure_delta=0.00,
            support_fill=0.03,
            spin_rate_scale=1.02,
            wobble_scale=0.95,
            core_radius_scale=1.00,
        ),
    ),
    (
        "wide",
        "with a wider warm-white pair",
        dict(
            beam_layout="warm_white",
            orbit_rx_scale=1.10,
            orbit_ry_scale=1.02,
            arc_radius_scale=1.00,
            local_start_shift=0.04 * math.pi,
            local_sweep_scale=1.02,
            base_exposure_delta=0.05,
            support_fill=0.02,
            spin_rate_scale=0.96,
            wobble_scale=1.00,
            core_radius_scale=1.00,
        ),
    ),
    (
        "triad",
        "with a triad and a soft top support",
        dict(
            beam_layout="triad",
            orbit_rx_scale=0.98,
            orbit_ry_scale=1.08,
            arc_radius_scale=0.92,
            local_start_shift=-0.03 * math.pi,
            local_sweep_scale=1.06,
            base_exposure_delta=0.06,
            support_fill=0.05,
            spin_rate_scale=0.92,
            wobble_scale=0.96,
            core_radius_scale=0.98,
        ),
    ),
    (
        "toplit",
        "with a left-top support beam",
        dict(
            beam_layout="left_top",
            orbit_rx_scale=1.00,
            orbit_ry_scale=1.00,
            arc_radius_scale=0.98,
            local_start_shift=0.06 * math.pi,
            local_sweep_scale=1.00,
            base_exposure_delta=0.03,
            support_fill=0.06,
            spin_rate_scale=1.00,
            wobble_scale=1.00,
            core_radius_scale=1.00,
        ),
    ),
    (
        "exchange",
        "with crossing side beams that stay legible",
        dict(
            beam_layout="exchange",
            orbit_rx_scale=0.96,
            orbit_ry_scale=0.98,
            arc_radius_scale=0.95,
            local_start_shift=0.12 * math.pi,
            local_sweep_scale=0.94,
            base_exposure_delta=0.02,
            support_fill=0.04,
            spin_rate_scale=1.05,
            wobble_scale=1.00,
            core_radius_scale=1.00,
        ),
    ),
    (
        "trident",
        "with a warm-white trident and extra wall light",
        dict(
            beam_layout="trident",
            orbit_rx_scale=1.02,
            orbit_ry_scale=1.02,
            arc_radius_scale=1.02,
            local_start_shift=-0.08 * math.pi,
            local_sweep_scale=1.06,
            base_exposure_delta=0.04,
            support_fill=0.05,
            spin_rate_scale=0.98,
            wobble_scale=1.05,
            core_radius_scale=1.00,
        ),
    ),
    (
        "wash",
        "under a subtle warm-white wash",
        dict(
            beam_layout="warm_white",
            orbit_rx_scale=1.00,
            orbit_ry_scale=0.94,
            arc_radius_scale=0.99,
            local_start_shift=0.00,
            local_sweep_scale=1.00,
            base_exposure_delta=0.07,
            support_fill=0.07,
            spin_rate_scale=0.94,
            wobble_scale=0.92,
            core_radius_scale=0.98,
        ),
    ),
]


def _build_scene(theme_name: str, theme_desc: str, theme_params: dict[str, float], variant_name: str, variant_note: str, variant_params: dict[str, float]) -> SceneSpec:
    orbit_rx = theme_params["orbit_rx"] * variant_params["orbit_rx_scale"]
    orbit_ry = theme_params["orbit_ry"] * variant_params["orbit_ry_scale"]
    arc_radius = theme_params["arc_radius"] * variant_params["arc_radius_scale"]
    local_start = theme_params["local_start"] + variant_params["local_start_shift"]
    local_sweep = theme_params["local_sweep"] * variant_params["local_sweep_scale"]
    spin_rate = theme_params["spin_rate"] * variant_params["spin_rate_scale"]
    wobble = theme_params["wobble"] * variant_params["wobble_scale"]
    core_radius = theme_params["core_radius"] * variant_params["core_radius_scale"]
    base_exposure = theme_params["base_exposure"] + variant_params["base_exposure_delta"]
    description = f"{theme_desc} {variant_note}."
    return _arc(
        f"arc_{theme_name}_{variant_name}",
        description,
        ring_count=int(theme_params["ring_count"]),
        orbit_rx=orbit_rx,
        orbit_ry=orbit_ry,
        arc_radius=arc_radius,
        local_start=local_start,
        local_sweep=local_sweep,
        beam_layout=str(variant_params["beam_layout"]),
        base_exposure=base_exposure,
        support_fill=float(variant_params["support_fill"]),
        spin_rate=spin_rate,
        wobble=wobble,
        core_radius=core_radius,
    )


SCENES = [
    _build_scene(theme_name, theme_desc, theme_params, variant_name, variant_note, variant_params)
    for theme_name, theme_desc, theme_params in _THEMES
    for variant_name, variant_note, variant_params in _VARIANTS
]

assert len(SCENES) == 70
