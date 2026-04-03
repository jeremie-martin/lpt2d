"""Curated axial clean-room scenes built around stacked spine structures."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_beacon_stack_spec
from anim.examples._clean_room_shared import SceneSpec, with_family

FAMILY = "spines"

CENTER = [0.0]
PAIR = [-0.54, 0.54]
WIDE_PAIR = [-0.68, 0.68]
TRIPLE = [-0.66, 0.0, 0.66]
STACK = [-0.44, 0.0, 0.44]
QUAD = [-0.72, -0.24, 0.24, 0.72]
NARROW = [-0.34, 0.34]
STAGGER = [-0.6, -0.16, 0.18, 0.58]
LADDER = [-0.76, -0.32, 0.12, 0.56]
SLOPE = [-0.66, -0.28, 0.1, 0.48]

BEAM_LABELS = {
    "left_top": "left-plus-top beams",
    "dual_side": "dual-side beams",
    "warm_white": "warm-white beams",
    "triad": "triad beams",
    "exchange": "exchange beams",
    "trident": "trident beams",
    "top": "top beam",
    "left": "left beam",
    "bottom": "bottom beam",
}

NODE_LABELS = {
    "prism": "prism nodes",
    "ball": "round nodes",
    "focus": "focus nodes",
    "biconvex": "biconvex nodes",
    "plano": "plano nodes",
}

RAIL_LABELS = {
    "mirror": "mirror rails",
    "splitter": "splitter rails",
    "soft": "soft mirror rails",
    "mixed": "mixed rails",
}

LAYOUT_LABELS = {
    "stack": "stacked",
    "zigzag": "zigzagged",
    "sway": "swaying",
}


def _make(
    name: str,
    *,
    lanes: list[float],
    rows: int,
    beam_layout: str,
    base_exposure: float,
    node_kind: str,
    rail_kind: str,
    layout: str,
    support_fill: float,
) -> SceneSpec:
    description = (
        f"{LAYOUT_LABELS[layout].capitalize()} spine columns with {NODE_LABELS[node_kind]} "
        f"and {RAIL_LABELS[rail_kind]} under {BEAM_LABELS[beam_layout]}."
    )
    return with_family(
        make_beacon_stack_spec(
            name,
            description,
            lanes=lanes,
            rows=rows,
            beam_layout=beam_layout,
            base_exposure=base_exposure,
            node_kind=node_kind,
            rail_kind=rail_kind,
            layout=layout,
            support_fill=support_fill,
        ),
        FAMILY,
    )


def _series(
    prefix: str,
    lanes: list[float],
    entries: list[tuple[str, int, str, float, str, str, str, float]],
) -> list[SceneSpec]:
    scenes: list[SceneSpec] = []
    for slug, rows, beam_layout, exposure, node_kind, rail_kind, layout, support_fill in entries:
        scenes.append(
            _make(
                f"{prefix}_{slug}",
                lanes=lanes,
                rows=rows,
                beam_layout=beam_layout,
                base_exposure=exposure,
                node_kind=node_kind,
                rail_kind=rail_kind,
                layout=layout,
                support_fill=support_fill,
            )
        )
    return scenes


SCENES: list[SceneSpec] = [
    *_series(
        "spine_axis",
        CENTER,
        [
            ("pillar", 5, "warm_white", 3.16, "prism", "mirror", "stack", 0.03),
            ("vertebra", 6, "triad", 3.24, "biconvex", "mixed", "stack", 0.04),
            ("core", 5, "dual_side", 3.12, "focus", "mirror", "sway", 0.03),
            ("lattice", 6, "left_top", 3.22, "plano", "splitter", "zigzag", 0.04),
            ("mast", 5, "exchange", 3.18, "prism", "soft", "stack", 0.03),
            ("rivet", 6, "trident", 3.20, "ball", "mixed", "sway", 0.04),
            ("beam", 5, "top", 3.14, "focus", "mirror", "stack", 0.02),
            ("spindle", 6, "warm_white", 3.22, "biconvex", "soft", "zigzag", 0.04),
        ],
    ),
    *_series(
        "spine_column",
        PAIR,
        [
            ("pair", 5, "dual_side", 3.18, "prism", "mirror", "stack", 0.03),
            ("gate", 6, "warm_white", 3.20, "focus", "mixed", "sway", 0.04),
            ("rib", 5, "left_top", 3.24, "biconvex", "splitter", "zigzag", 0.04),
            ("sleeve", 6, "exchange", 3.16, "ball", "soft", "stack", 0.03),
            ("rail", 5, "triad", 3.22, "plano", "mirror", "sway", 0.04),
            ("joint", 6, "trident", 3.14, "focus", "mixed", "zigzag", 0.03),
            ("narrow", 5, "left", 3.26, "prism", "soft", "stack", 0.02),
            ("clear", 6, "warm_white", 3.18, "biconvex", "splitter", "sway", 0.03),
        ],
    ),
    *_series(
        "spine_bridge",
        WIDE_PAIR,
        [
            ("span", 5, "dual_side", 3.18, "prism", "mirror", "stack", 0.03),
            ("arch", 6, "warm_white", 3.24, "focus", "mixed", "zigzag", 0.04),
            ("brace", 5, "left_top", 3.20, "ball", "splitter", "sway", 0.03),
            ("cross", 6, "exchange", 3.16, "plano", "soft", "stack", 0.03),
            ("hinge", 5, "triad", 3.22, "biconvex", "mirror", "zigzag", 0.04),
            ("frame", 6, "trident", 3.14, "focus", "mixed", "sway", 0.03),
            ("latch", 5, "warm_white", 3.26, "prism", "soft", "stack", 0.02),
            ("beamline", 6, "top", 3.18, "ball", "mirror", "zigzag", 0.03),
        ],
    ),
    *_series(
        "spine_triple",
        TRIPLE,
        [
            ("crest", 5, "triad", 3.22, "prism", "mirror", "stack", 0.03),
            ("cable", 6, "warm_white", 3.18, "focus", "mixed", "sway", 0.04),
            ("joints", 5, "dual_side", 3.20, "biconvex", "splitter", "zigzag", 0.04),
            ("ladder", 6, "left_top", 3.24, "ball", "soft", "stack", 0.03),
            ("braid", 5, "exchange", 3.16, "plano", "mirror", "sway", 0.03),
            ("hinged", 6, "trident", 3.14, "focus", "mixed", "zigzag", 0.03),
            ("channel", 5, "warm_white", 3.26, "prism", "soft", "stack", 0.02),
            ("suture", 6, "top", 3.18, "biconvex", "mirror", "sway", 0.03),
        ],
    ),
    *_series(
        "spine_stack",
        STACK,
        [
            ("sacrum", 5, "warm_white", 3.16, "prism", "mirror", "stack", 0.03),
            ("cervix", 6, "dual_side", 3.22, "focus", "mixed", "zigzag", 0.04),
            ("thorax", 5, "left_top", 3.24, "biconvex", "splitter", "sway", 0.04),
            ("lumbar", 6, "exchange", 3.18, "ball", "soft", "stack", 0.03),
            ("neck", 5, "triad", 3.20, "plano", "mirror", "zigzag", 0.04),
            ("atlas", 6, "trident", 3.14, "focus", "mixed", "sway", 0.03),
            ("axis", 5, "top", 3.26, "prism", "soft", "stack", 0.02),
            ("spine", 6, "warm_white", 3.18, "biconvex", "mirror", "zigzag", 0.03),
        ],
    ),
    *_series(
        "spine_ladder",
        LADDER,
        [
            ("rung", 5, "dual_side", 3.20, "prism", "mirror", "stack", 0.03),
            ("rail", 6, "warm_white", 3.18, "focus", "mixed", "zigzag", 0.04),
            ("brace", 5, "left_top", 3.24, "ball", "splitter", "sway", 0.04),
            ("climb", 6, "exchange", 3.16, "plano", "soft", "stack", 0.03),
            ("step", 5, "triad", 3.22, "biconvex", "mirror", "zigzag", 0.04),
            ("rise", 6, "trident", 3.14, "focus", "mixed", "sway", 0.03),
            ("span", 5, "warm_white", 3.26, "prism", "soft", "stack", 0.02),
            ("quiet", 6, "top", 3.18, "ball", "mirror", "zigzag", 0.03),
        ],
    ),
    *_series(
        "spine_slope",
        SLOPE,
        [
            ("tilt", 5, "warm_white", 3.16, "prism", "mirror", "stack", 0.03),
            ("drift", 6, "dual_side", 3.22, "focus", "mixed", "sway", 0.04),
            ("lean", 5, "left_top", 3.20, "biconvex", "splitter", "zigzag", 0.04),
            ("hinge", 6, "exchange", 3.18, "ball", "soft", "stack", 0.03),
            ("arc", 5, "triad", 3.24, "plano", "mirror", "sway", 0.04),
            ("rise", 6, "trident", 3.14, "focus", "mixed", "zigzag", 0.03),
            ("slant", 5, "warm_white", 3.26, "prism", "soft", "stack", 0.02),
            ("edge", 6, "top", 3.18, "biconvex", "mirror", "sway", 0.03),
        ],
    ),
]

