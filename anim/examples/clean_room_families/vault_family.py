"""Curated vaulted clean-room family."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import (
    make_arc_cluster_spec,
    make_fin_array_spec,
    make_spoke_array_spec,
)

FAMILY = "vaults"


def _rib_centers(count: int, *, y: float, rise: float, span: float) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for index in range(count):
        angle = math.pi * index / max(count - 1, 1)
        x = -span + 2 * span * index / max(count - 1, 1)
        centers.append((x, y + rise * math.sin(angle)))
    return centers


_ARC_PROFILES = [
    ("nave", 4, 0.72, 0.24, 0.34, 0.12 * math.pi, 0.82 * math.pi, 3.12, 0.04),
    ("bay", 5, 0.64, 0.34, 0.28, 0.16 * math.pi, 0.8 * math.pi, 3.16, 0.05),
    ("apse", 3, 0.56, 0.46, 0.32, 0.1 * math.pi, 0.88 * math.pi, 3.18, 0.06),
    ("transept", 6, 0.68, 0.28, 0.24, 0.18 * math.pi, 0.74 * math.pi, 3.2, 0.06),
    ("clerestory", 4, 0.58, 0.42, 0.26, 0.12 * math.pi, 0.92 * math.pi, 3.18, 0.06),
    ("ribbed", 5, 0.76, 0.22, 0.22, 0.22 * math.pi, 0.68 * math.pi, 3.1, 0.03),
    ("lantern", 4, 0.52, 0.48, 0.3, 0.1 * math.pi, 0.9 * math.pi, 3.18, 0.06),
    ("oculus", 6, 0.7, 0.26, 0.2, 0.16 * math.pi, 0.72 * math.pi, 3.14, 0.04),
]

_ARC_BEAMS = [
    ("warm", "warm_white", 0.0, 0.0),
    ("crown", "triad", 0.08, 0.02),
]

_FIN_PROFILES = [
    ("arcade", _rib_centers(5, y=0.08, rise=0.18, span=0.84), math.pi * 0.5, 0.6, 0.18, "mirror", "focus", 3.1, 0.02),
    ("buttress", _rib_centers(4, y=-0.02, rise=0.24, span=0.64), math.pi * 0.5, 0.72, 0.2, "soft", "prism", 3.14, 0.03),
    ("coffer", _rib_centers(6, y=0.14, rise=0.12, span=0.92), 0.0, 0.54, 0.22, "mirror", "ball", 3.12, 0.02),
    ("ribway", _rib_centers(5, y=-0.1, rise=0.16, span=0.74), 0.0, 0.66, 0.26, "soft", "focus", 3.16, 0.03),
    ("cleric", _rib_centers(4, y=0.24, rise=0.18, span=0.58), math.pi * 0.5, 0.5, 0.16, "mirror", "ball", 3.1, 0.02),
    ("span", _rib_centers(6, y=0.04, rise=0.08, span=0.98), 0.0, 0.48, 0.18, "soft", "prism", 3.08, 0.02),
    ("portal", _rib_centers(3, y=-0.02, rise=0.28, span=0.42), math.pi * 0.5, 0.84, 0.28, "mirror", "focus", 3.12, 0.03),
    ("vaultline", _rib_centers(5, y=0.18, rise=0.14, span=0.8), 0.0, 0.58, 0.2, "soft", "none", 3.08, 0.01),
]

_SPOKE_PROFILES = [
    ("cupola", 6, 0.16, 0.66, "mixed", "prism", 0.2, 3.14, 0.03),
    ("dome", 7, 0.12, 0.62, "mixed", "ball", 0.24, 3.16, 0.03),
    ("rose", 8, 0.1, 0.58, "splitter", "focus", 0.28, 3.18, 0.04),
    ("rotunda", 5, 0.2, 0.7, "mirror", "prism", 0.18, 3.1, 0.02),
    ("halo", 9, 0.08, 0.54, "mixed", "ball", 0.26, 3.18, 0.04),
    ("ciborium", 6, 0.18, 0.64, "mirror", "focus", 0.16, 3.12, 0.02),
    ("lanthorn", 7, 0.14, 0.6, "splitter", "prism", 0.22, 3.16, 0.03),
    ("crownwell", 8, 0.1, 0.56, "mixed", "ball", 0.24, 3.18, 0.04),
]

_SECONDARY_BEAMS = [
    ("warm", "warm_white", 0.0, 0.0),
    ("triad", "triad", 0.06, 0.02),
]


SCENES = [
    make_arc_cluster_spec(
        f"vault_arc_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} vaulted arcs gather a clean {beam_tag.replace('_', ' ')} beam relay.",
        ring_count=ring_count,
        orbit_rx=orbit_rx,
        orbit_ry=orbit_ry,
        arc_radius=arc_radius,
        local_start=local_start,
        local_sweep=local_sweep,
        beam_layout=beam_layout,
        base_exposure=base_exposure + exposure_bias,
        support_fill=support_fill + fill_bias,
    )
    for name, ring_count, orbit_rx, orbit_ry, arc_radius, local_start, local_sweep, base_exposure, support_fill in _ARC_PROFILES
    for beam_tag, beam_layout, exposure_bias, fill_bias in _ARC_BEAMS
] + [
    make_fin_array_spec(
        f"vault_fin_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} vault ribs open under a bright {beam_tag.replace('_', ' ')} beam field.",
        centers=centers,
        beam_layout=beam_layout,
        base_exposure=base_exposure + exposure_bias,
        base_angle=base_angle,
        fin_length=fin_length,
        swing=swing,
        material_kind=material_kind,
        core_kind=core_kind,
        support_fill=support_fill + fill_bias,
    )
    for name, centers, base_angle, fin_length, swing, material_kind, core_kind, base_exposure, support_fill in _FIN_PROFILES
    for beam_tag, beam_layout, exposure_bias, fill_bias in _SECONDARY_BEAMS
] + [
    make_spoke_array_spec(
        f"vault_spoke_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} radial ribs crown a vaulted mirror room.",
        count=count,
        radius_inner=radius_inner,
        radius_outer=radius_outer,
        beam_layout=beam_layout,
        base_exposure=base_exposure + exposure_bias,
        segment_kind=segment_kind,
        node_kind=node_kind,
        twist=twist,
        support_fill=support_fill + fill_bias,
    )
    for name, count, radius_inner, radius_outer, segment_kind, node_kind, twist, base_exposure, support_fill in _SPOKE_PROFILES
    for beam_tag, beam_layout, exposure_bias, fill_bias in _SECONDARY_BEAMS
]
