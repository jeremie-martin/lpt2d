"""Curated orbital clean-room scene family."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import (
    make_arc_cluster_spec,
    make_lens_field_spec,
    make_prism_field_spec,
)

FAMILY = "orbits"

_ARC_VARIANTS = [
    ("aureole", 3, 0.52, 0.26, 0.28, 0.17 * math.pi, 0.80 * math.pi, "dual_side", 3.10, 0.04),
    ("calyx", 4, 0.58, 0.32, 0.31, 0.20 * math.pi, 0.88 * math.pi, "warm_white", 3.16, 0.05),
    ("petal", 5, 0.62, 0.28, 0.29, 0.24 * math.pi, 0.74 * math.pi, "dual_side", 3.12, 0.04),
    ("diadem", 6, 0.68, 0.34, 0.26, 0.16 * math.pi, 0.70 * math.pi, "triad", 3.22, 0.06),
    ("lantern", 4, 0.46, 0.44, 0.33, 0.12 * math.pi, 0.92 * math.pi, "left_top", 3.18, 0.06),
    ("garland", 5, 0.72, 0.30, 0.24, 0.20 * math.pi, 0.78 * math.pi, "dual_side", 3.08, 0.03),
    ("crown", 4, 0.56, 0.22, 0.36, 0.18 * math.pi, 0.86 * math.pi, "warm_white", 3.20, 0.05),
    ("sundial", 3, 0.74, 0.26, 0.38, 0.22 * math.pi, 0.62 * math.pi, "triad", 3.28, 0.07),
    ("harbor", 5, 0.48, 0.36, 0.27, 0.14 * math.pi, 0.90 * math.pi, "left_top", 3.14, 0.05),
    ("filigree", 6, 0.66, 0.42, 0.25, 0.18 * math.pi, 0.72 * math.pi, "triad", 3.24, 0.07),
    ("oval", 4, 0.76, 0.20, 0.33, 0.20 * math.pi, 0.68 * math.pi, "warm_white", 3.18, 0.04),
    ("harp", 5, 0.60, 0.46, 0.23, 0.10 * math.pi, 0.94 * math.pi, "left_top", 3.26, 0.08),
    ("reef", 3, 0.54, 0.38, 0.37, 0.18 * math.pi, 0.76 * math.pi, "dual_side", 3.12, 0.04),
    ("parasol", 4, 0.64, 0.24, 0.35, 0.25 * math.pi, 0.56 * math.pi, "warm_white", 3.18, 0.05),
    ("spire", 5, 0.50, 0.40, 0.29, 0.14 * math.pi, 0.84 * math.pi, "triad", 3.22, 0.07),
    ("wreath", 6, 0.70, 0.30, 0.22, 0.16 * math.pi, 0.74 * math.pi, "dual_side", 3.10, 0.03),
    ("orbit", 4, 0.62, 0.34, 0.32, 0.18 * math.pi, 0.82 * math.pi, "warm_white", 3.16, 0.05),
    ("veil", 5, 0.58, 0.44, 0.24, 0.12 * math.pi, 0.92 * math.pi, "left_top", 3.24, 0.07),
    ("rondel", 3, 0.72, 0.24, 0.39, 0.22 * math.pi, 0.60 * math.pi, "dual_side", 3.14, 0.04),
    ("corona", 6, 0.68, 0.36, 0.24, 0.16 * math.pi, 0.78 * math.pi, "triad", 3.26, 0.08),
]

_PRISM_VARIANTS = [
    ("halo", "ring", 4, 0.18, "warm_white", 3.18, 0.04),
    ("wreath", "ring", 5, 0.16, "dual_side", 3.12, 0.03),
    ("garland", "ring", 6, 0.14, "triad", 3.24, 0.06),
    ("crown", "constellation", 6, 0.17, "warm_white", 3.18, 0.05),
    ("bracelet", "ring", 5, 0.19, "dual_side", 3.14, 0.04),
    ("tiara", "bridge", 5, 0.16, "warm_white", 3.16, 0.05),
    ("ripple", "sweep", 5, 0.15, "left_top", 3.22, 0.06),
    ("sash", "bridge", 4, 0.20, "dual_side", 3.10, 0.03),
    ("compass", "constellation", 6, 0.13, "triad", 3.28, 0.07),
    ("meridian", "sweep", 5, 0.17, "warm_white", 3.20, 0.05),
    ("parade", "bridge", 6, 0.14, "dual_side", 3.14, 0.04),
    ("aurora", "ring", 4, 0.21, "warm_white", 3.22, 0.05),
    ("braid", "constellation", 6, 0.15, "left_top", 3.24, 0.07),
    ("relay", "bridge", 5, 0.18, "triad", 3.26, 0.06),
    ("sundial", "ring", 6, 0.13, "dual_side", 3.12, 0.03),
    ("drift", "sweep", 4, 0.19, "warm_white", 3.18, 0.04),
    ("vane", "constellation", 6, 0.14, "triad", 3.24, 0.06),
    ("bloom", "ring", 5, 0.17, "warm_white", 3.20, 0.05),
    ("silhouette", "bridge", 4, 0.22, "dual_side", 3.14, 0.04),
    ("echo", "sweep", 6, 0.13, "left_top", 3.22, 0.06),
]

_LENS_VARIANTS = [
    ("halo", "orbit", 4, "warm_white", 3.22, 0.05),
    ("crown", "orbit", 5, "dual_side", 3.16, 0.04),
    ("meridian", "diamond", 4, "triad", 3.28, 0.07),
    ("satellite", "orbit", 6, "warm_white", 3.24, 0.05),
    ("ring", "orbit", 5, "left_top", 3.26, 0.07),
    ("cartwheel", "grid", 6, "warm_white", 3.20, 0.05),
    ("constellation", "orbit", 4, "dual_side", 3.18, 0.04),
    ("quartet", "diamond", 4, "triad", 3.30, 0.07),
    ("sweep", "columns", 4, "left_top", 3.24, 0.06),
    ("arcade", "orbit", 6, "warm_white", 3.22, 0.05),
    ("parasol", "orbit", 5, "dual_side", 3.18, 0.04),
    ("compass", "diamond", 4, "triad", 3.28, 0.07),
    ("drift", "orbit", 6, "warm_white", 3.24, 0.05),
    ("lantern", "columns", 4, "left_top", 3.26, 0.06),
    ("parade", "grid", 6, "warm_white", 3.20, 0.05),
    ("ripple", "orbit", 5, "dual_side", 3.18, 0.04),
    ("echo", "orbit", 4, "triad", 3.26, 0.06),
    ("beacon", "diamond", 4, "warm_white", 3.24, 0.05),
    ("glide", "orbit", 6, "left_top", 3.28, 0.07),
    ("wreath", "orbit", 5, "warm_white", 3.22, 0.05),
]


SCENES = [
    make_arc_cluster_spec(
        f"orbital_arc_{name}",
        f"{name.replace('_', ' ').title()} arcs circle a warm-white core.",
        ring_count=ring_count,
        orbit_rx=orbit_rx,
        orbit_ry=orbit_ry,
        arc_radius=arc_radius,
        local_start=local_start,
        local_sweep=local_sweep,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, ring_count, orbit_rx, orbit_ry, arc_radius, local_start, local_sweep, beam_layout, base_exposure, support_fill in _ARC_VARIANTS
] + [
    make_prism_field_spec(
        f"orbital_prism_{name}",
        f"{name.replace('_', ' ').title()} prisms orbit a bright mirror-room center.",
        layout=layout,
        count=count,
        prism_radius=prism_radius,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, layout, count, prism_radius, beam_layout, base_exposure, support_fill in _PRISM_VARIANTS
] + [
    make_lens_field_spec(
        f"orbital_lens_{name}",
        f"{name.replace('_', ' ').title()} lenses circle a warm-and-white beam field.",
        layout=layout,
        count=count,
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
    )
    for name, layout, count, beam_layout, base_exposure, support_fill in _LENS_VARIANTS
]
