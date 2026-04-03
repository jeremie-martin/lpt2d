"""Curated mixed clean-room scene family."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import (
    make_arc_cluster_spec,
    make_lens_field_spec,
    make_prism_field_spec,
    make_ribbon_spec,
    make_rotor_spec,
    make_splitter_web_spec,
)

FAMILY = "hybrids"

_ARC_SCENES = [
    ("hybrid_arc_crownbridge", 4, 0.60, 0.30, 0.30, "warm_white", 3.16, 0.05),
    ("hybrid_arc_lanternweave", 5, 0.54, 0.42, 0.24, "triad", 3.24, 0.07),
    ("hybrid_arc_crosshalo", 3, 0.72, 0.24, 0.37, "dual_side", 3.12, 0.04),
    ("hybrid_arc_veilrelay", 6, 0.66, 0.34, 0.23, "left_top", 3.24, 0.07),
    ("hybrid_arc_gatelattice", 4, 0.50, 0.40, 0.31, "triad", 3.20, 0.06),
    ("hybrid_arc_orbitbraid", 5, 0.62, 0.28, 0.28, "warm_white", 3.14, 0.05),
    ("hybrid_arc_compassreef", 3, 0.68, 0.26, 0.38, "dual_side", 3.14, 0.04),
    ("hybrid_arc_petalshield", 6, 0.58, 0.38, 0.25, "left_top", 3.26, 0.07),
]

_PRISM_SCENES = [
    ("hybrid_prism_arcade", "bridge", 5, 0.18, "warm_white", 3.18, 0.05),
    ("hybrid_prism_lantern", "constellation", 6, 0.14, "triad", 3.24, 0.06),
    ("hybrid_prism_compass", "ring", 4, 0.20, "dual_side", 3.14, 0.04),
    ("hybrid_prism_braid", "sweep", 5, 0.16, "left_top", 3.22, 0.06),
    ("hybrid_prism_sash", "bridge", 6, 0.15, "warm_white", 3.18, 0.05),
    ("hybrid_prism_relay", "constellation", 6, 0.13, "triad", 3.26, 0.07),
    ("hybrid_prism_exchange", "bridge", 4, 0.21, "dual_side", 3.12, 0.04),
    ("hybrid_prism_halo", "ring", 5, 0.17, "warm_white", 3.20, 0.05),
]

_ROTOR_SCENES = [
    ("hybrid_rotor_compassgate", [(-0.58, 0.0), (0.58, 0.0)], 4, 0.44, math.pi * 0.55, False, "warm_white", 3.20, "prism", 0.16, 0.05),
    ("hybrid_rotor_lanternfan", [(-0.42, -0.18), (0.42, 0.18)], 5, 0.40, math.pi * 0.8, True, "triad", 3.26, "ball", 0.18, 0.07),
    ("hybrid_rotor_shutterbraid", [(-0.68, 0.0), (0.0, 0.0), (0.68, 0.0)], 3, 0.32, math.pi * 0.4, False, "dual_side", 3.14, "prism", 0.14, 0.04),
    ("hybrid_rotor_crownrelay", [(-0.46, 0.28), (0.46, -0.28)], 6, 0.38, math.pi * 0.9, True, "warm_white", 3.22, "ball", 0.20, 0.06),
    ("hybrid_rotor_arcade", [(-0.64, 0.22), (0.0, -0.22), (0.64, 0.22)], 4, 0.30, math.pi * 0.5, False, "left_top", 3.24, "prism", 0.16, 0.06),
    ("hybrid_rotor_meridian", [(-0.52, -0.26), (0.52, 0.26)], 5, 0.42, math.pi * 0.7, True, "triad", 3.28, "ball", 0.18, 0.07),
    ("hybrid_rotor_harbor", [(-0.34, 0.0), (0.34, 0.0)], 7, 0.34, math.pi * 0.85, True, "warm_white", 3.24, "prism", 0.19, 0.06),
    ("hybrid_rotor_orbitgate", [(-0.6, -0.14), (0.0, 0.22), (0.6, -0.14)], 4, 0.36, math.pi * 0.6, False, "dual_side", 3.18, "ball", 0.15, 0.05),
]

_RIBBON_SCENES = [
    ("hybrid_ribbon_arcade", 3, 0.22, 0.18, "warm_white", 3.18, 0.05),
    ("hybrid_ribbon_exchange", 4, 0.18, 0.26, "dual_side", 3.12, 0.04),
    ("hybrid_ribbon_lattice", 5, 0.16, 0.22, "triad", 3.24, 0.06),
    ("hybrid_ribbon_meridian", 4, 0.20, 0.30, "left_top", 3.24, 0.06),
    ("hybrid_ribbon_crownpath", 3, 0.26, 0.14, "warm_white", 3.16, 0.05),
    ("hybrid_ribbon_shield", 5, 0.15, 0.34, "dual_side", 3.18, 0.04),
    ("hybrid_ribbon_halo", 4, 0.18, 0.28, "triad", 3.26, 0.07),
    ("hybrid_ribbon_braid", 6, 0.14, 0.18, "warm_white", 3.20, 0.05),
]

_LENS_SCENES = [
    ("hybrid_lens_compass", "diamond", 4, "warm_white", 3.24, 0.05),
    ("hybrid_lens_corridor", "columns", 4, "left_top", 3.24, 0.06),
    ("hybrid_lens_halo", "orbit", 5, "dual_side", 3.18, 0.04),
    ("hybrid_lens_lattice", "grid", 6, "warm_white", 3.22, 0.05),
    ("hybrid_lens_meridian", "diamond", 4, "triad", 3.28, 0.07),
    ("hybrid_lens_arcade", "orbit", 6, "warm_white", 3.20, 0.05),
    ("hybrid_lens_exchange", "columns", 4, "left_top", 3.26, 0.06),
    ("hybrid_lens_beacon", "orbit", 5, "triad", 3.28, 0.07),
]

_SPLITTER_SCENES = [
    ("hybrid_splitter_crownline", "crown", "warm_white", 3.16, 0.05),
    ("hybrid_splitter_compassline", "compass", "triad", 3.24, 0.06),
    ("hybrid_splitter_braidline", "exchange", "dual_side", 3.14, 0.04),
    ("hybrid_splitter_lanternline", "corridor", "left_top", 3.24, 0.06),
    ("hybrid_splitter_gate", "trident", "warm_white", 3.20, 0.05),
    ("hybrid_splitter_halo", "compass", "dual_side", 3.18, 0.04),
    ("hybrid_splitter_meridian", "corridor", "triad", 3.26, 0.07),
    ("hybrid_splitter_exchange", "exchange", "warm_white", 3.18, 0.05),
    ("hybrid_splitter_arcade", "crown", "left_top", 3.24, 0.06),
    ("hybrid_splitter_signal", "trident", "dual_side", 3.18, 0.04),
]


SCENES = [
    make_arc_cluster_spec(
        name,
        f"{name.replace('_', ' ').title()} mixes arc motion with a bright beam-led core.",
        ring_count=ring_count,
        orbit_rx=orbit_rx,
        orbit_ry=orbit_ry,
        arc_radius=arc_radius,
        local_start=0.18 * math.pi,
        local_sweep=0.80 * math.pi,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, ring_count, orbit_rx, orbit_ry, arc_radius, beam_layout, base_exposure, support_fill in _ARC_SCENES
] + [
    make_prism_field_spec(
        name,
        f"{name.replace('_', ' ').title()} blends prism rhythm with a mirror-room beam relay.",
        layout=layout,
        count=count,
        prism_radius=prism_radius,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, layout, count, prism_radius, beam_layout, base_exposure, support_fill in _PRISM_SCENES
] + [
    make_rotor_spec(
        name,
        f"{name.replace('_', ' ').title()} layers rotor motion into a clean warm-white light field.",
        pivots=pivots,
        blade_count=blade_count,
        blade_length=blade_length,
        spread=spread,
        radial=radial,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        hub_kind=hub_kind,
        spin_rate=spin_rate,
        support_fill=support_fill,
    )
    for name, pivots, blade_count, blade_length, spread, radial, beam_layout, base_exposure, hub_kind, spin_rate, support_fill in _ROTOR_SCENES
] + [
    make_ribbon_spec(
        name,
        f"{name.replace('_', ' ').title()} crosses ribbons under bright side-lit beams.",
        count=count,
        spacing=spacing,
        cross_bias=cross_bias,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, count, spacing, cross_bias, beam_layout, base_exposure, support_fill in _RIBBON_SCENES
] + [
    make_lens_field_spec(
        name,
        f"{name.replace('_', ' ').title()} arranges lenses as a bright hybrid optical study.",
        layout=layout,
        count=count,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, layout, count, beam_layout, base_exposure, support_fill in _LENS_SCENES
] + [
    make_splitter_web_spec(
        name,
        f"{name.replace('_', ' ').title()} redirects warm and white beams through a clean splitter web.",
        layout=layout,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, layout, beam_layout, base_exposure, support_fill in _SPLITTER_SCENES
]
