"""Curated canopy clean-room family."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import make_fin_array_spec, make_spoke_array_spec

FAMILY = "canopies"


def _canopy_centers(count: int, *, y: float, rise: float, span: float) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for index in range(count):
        angle = math.pi * index / max(count - 1, 1)
        x = -span + 2 * span * index / max(count - 1, 1)
        centers.append((x, y + rise * math.sin(angle)))
    return centers


_FIN_PROFILES = [
    ("awning", _canopy_centers(5, y=0.36, rise=0.12, span=0.86), math.pi * 0.5, 0.5, 0.16, "soft", "focus", 3.08, 0.02),
    ("fringe", _canopy_centers(6, y=0.42, rise=0.08, span=0.96), math.pi * 0.5, 0.44, 0.14, "mirror", "none", 3.06, 0.01),
    ("eave", _canopy_centers(4, y=0.28, rise=0.16, span=0.62), 0.0, 0.68, 0.24, "soft", "ball", 3.12, 0.03),
    ("veil", _canopy_centers(5, y=0.22, rise=0.18, span=0.82), 0.0, 0.58, 0.2, "mirror", "focus", 3.14, 0.03),
    ("harbor", _canopy_centers(6, y=0.18, rise=0.14, span=0.94), 0.0, 0.52, 0.18, "soft", "prism", 3.1, 0.02),
    ("cornice", _canopy_centers(4, y=0.5, rise=0.06, span=0.54), math.pi * 0.5, 0.42, 0.14, "mirror", "ball", 3.08, 0.02),
    ("shade", _canopy_centers(5, y=0.3, rise=0.1, span=0.74), math.pi * 0.5, 0.56, 0.18, "soft", "focus", 3.1, 0.02),
    ("frond", _canopy_centers(6, y=0.14, rise=0.2, span=0.9), 0.0, 0.54, 0.22, "mirror", "prism", 3.14, 0.03),
]

_SPOKE_PROFILES = [
    ("halo", 6, 0.18, 0.56, "mixed", "prism", 0.16, 3.12, 0.03),
    ("crown", 7, 0.14, 0.52, "mixed", "ball", 0.2, 3.14, 0.03),
    ("frill", 8, 0.1, 0.48, "splitter", "focus", 0.24, 3.18, 0.04),
    ("spray", 5, 0.2, 0.6, "mirror", "prism", 0.14, 3.1, 0.02),
    ("tiara", 9, 0.08, 0.5, "mixed", "ball", 0.22, 3.18, 0.04),
    ("wreath", 6, 0.16, 0.54, "mirror", "focus", 0.18, 3.12, 0.02),
    ("crest", 7, 0.12, 0.5, "splitter", "prism", 0.2, 3.16, 0.03),
    ("sweep", 8, 0.1, 0.46, "mixed", "ball", 0.24, 3.16, 0.03),
]

_BEAMS = [
    ("warm", "warm_white", 0.0, 0.0),
    ("crest", "left_top", 0.06, 0.02),
    ("triad", "triad", 0.08, 0.02),
]


SCENES = [
    make_fin_array_spec(
        f"canopy_fin_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} canopy fins hang in a bright {beam_tag.replace('_', ' ')} room.",
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
    for beam_tag, beam_layout, exposure_bias, fill_bias in _BEAMS
] + [
    make_spoke_array_spec(
        f"canopy_spoke_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} canopy spokes crown the scene with warm and white light.",
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
    for beam_tag, beam_layout, exposure_bias, fill_bias in _BEAMS
]
