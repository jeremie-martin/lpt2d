"""Curated cloister clean-room family."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_beacon_stack_spec, make_splitter_web_spec

FAMILY = "cloisters"

_STACK_PROFILES = [
    ("aisle", (-0.62, 0.62), 4, "prism", "mirror", "stack", 3.1, 0.02),
    ("nave", (-0.72, 0.0, 0.72), 4, "ball", "soft", "stack", 3.12, 0.03),
    ("ambulatory", (-0.54, 0.54), 5, "focus", "mirror", "zigzag", 3.16, 0.04),
    ("arcade", (-0.78, -0.26, 0.26, 0.78), 3, "prism", "soft", "stack", 3.08, 0.02),
    ("gallery", (-0.46, 0.0, 0.46), 5, "ball", "mirror", "sway", 3.14, 0.03),
    ("transept", (-0.66, 0.66), 6, "focus", "soft", "stack", 3.16, 0.04),
    ("quad", (-0.82, -0.28, 0.28, 0.82), 3, "prism", "mirror", "zigzag", 3.12, 0.03),
    ("portico", (-0.58, 0.58), 5, "ball", "soft", "sway", 3.1, 0.03),
]

_STACK_BEAMS = [
    ("warm", "warm_white", 0.0, 0.0),
    ("triad", "triad", 0.08, 0.02),
    ("guiding", "left_top", 0.04, 0.01),
]

_WEB_PROFILES = [
    ("passage", "corridor", 3.08, 0.02),
    ("apse", "trident", 3.12, 0.03),
    ("walk", "exchange", 3.1, 0.03),
    ("axis", "compass", 3.16, 0.04),
    ("oratory", "corridor", 3.12, 0.03),
    ("court", "exchange", 3.1, 0.03),
    ("choir", "trident", 3.14, 0.04),
    ("crossing", "compass", 3.18, 0.04),
]

_WEB_BEAMS = [
    ("warm", "warm_white", 0.0, 0.0),
    ("crest", "left_top", 0.06, 0.02),
    ("triad", "triad", 0.08, 0.02),
]


SCENES = [
    make_beacon_stack_spec(
        f"cloister_stack_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} cloister rails frame a clean {beam_tag.replace('_', ' ')} beam aisle.",
        lanes=lanes,
        rows=rows,
        beam_layout=beam_layout,
        base_exposure=base_exposure + exposure_bias,
        node_kind=node_kind,
        rail_kind=rail_kind,
        layout=layout,
        support_fill=support_fill + fill_bias,
    )
    for name, lanes, rows, node_kind, rail_kind, layout, base_exposure, support_fill in _STACK_PROFILES
    for beam_tag, beam_layout, exposure_bias, fill_bias in _STACK_BEAMS
] + [
    make_splitter_web_spec(
        f"cloister_web_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} splitter aisles redirect warm and white light through a mirror cloister.",
        layout=layout,
        beam_layout=beam_layout,
        base_exposure=base_exposure + exposure_bias,
        support_fill=support_fill + fill_bias,
    )
    for name, layout, base_exposure, support_fill in _WEB_PROFILES
    for beam_tag, beam_layout, exposure_bias, fill_bias in _WEB_BEAMS
]
