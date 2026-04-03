"""Curated beacon-focused clean-room scenes."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_beacon_stack_spec
from anim.examples._clean_room_shared import with_family

FAMILY = "beacons"

_VARIANTS = [
    ("warm", "under a warm-white lane", "warm_white", 0.00, 0.00),
    ("dual", "with balanced dual-side beams", "dual_side", 0.01, -0.01),
    ("triad", "under a bright triad cap", "triad", 0.01, -0.02),
]

_THEMES = [
    (
        "spire",
        "A narrow beacon spire climbs cleanly",
        dict(lanes=(0.0,), rows=6, layout="stack", node_kind="prism", rail_kind="mirror", base_exposure=3.18, support_fill=0.02),
    ),
    (
        "tower",
        "A paired tower stack keeps the rails close",
        dict(lanes=(-0.08, 0.08), rows=5, layout="stack", node_kind="biconvex", rail_kind="soft", base_exposure=3.14, support_fill=0.02),
    ),
    (
        "pier",
        "A low pier of lights reaches outward without crowding the room",
        dict(lanes=(-0.24, 0.24), rows=4, layout="sway", node_kind="ball", rail_kind="mixed", base_exposure=3.09, support_fill=0.01),
    ),
    (
        "ladder",
        "A clean ladder of beacons rises in stepped order",
        dict(lanes=(-0.34, 0.0, 0.34), rows=4, layout="zigzag", node_kind="plano", rail_kind="mirror", base_exposure=3.17, support_fill=0.02),
    ),
    (
        "nave",
        "A nave-like beacon hall keeps the center bright",
        dict(lanes=(-0.28, 0.28), rows=6, layout="stack", node_kind="prism", rail_kind="soft", base_exposure=3.22, support_fill=0.02),
    ),
    (
        "axis",
        "A single axis tower reads like a bright marker",
        dict(lanes=(0.0,), rows=5, layout="zigzag", node_kind="focus", rail_kind="mirror", base_exposure=3.07, support_fill=0.00),
    ),
    (
        "harbor",
        "A harbor of short towers balances left and right",
        dict(lanes=(-0.42, 0.0, 0.42), rows=3, layout="sway", node_kind="ball", rail_kind="mixed", base_exposure=3.08, support_fill=0.00),
    ),
    (
        "crown",
        "A compact crown of beacons opens overhead",
        dict(lanes=(-0.18, 0.0, 0.18), rows=5, layout="stack", node_kind="prism", rail_kind="mirror", base_exposure=3.24, support_fill=0.02),
    ),
    (
        "quay",
        "A quay of rails and stacked optics stays broad but contained",
        dict(lanes=(-0.48, -0.16, 0.16, 0.48), rows=3, layout="sway", node_kind="plano", rail_kind="soft", base_exposure=3.12, support_fill=0.01),
    ),
    (
        "rail",
        "A rail-focused stack keeps the beam path disciplined",
        dict(lanes=(-0.30, 0.30), rows=4, layout="zigzag", node_kind="biconvex", rail_kind="mirror", base_exposure=3.10, support_fill=0.01),
    ),
    (
        "sentinel",
        "A sentinel pair guards the room with a bright core",
        dict(lanes=(-0.12, 0.12), rows=6, layout="stack", node_kind="focus", rail_kind="mirror", base_exposure=3.19, support_fill=0.02),
    ),
    (
        "column",
        "A centered column of beacons reads from wall to wall",
        dict(lanes=(-0.26, 0.26), rows=5, layout="stack", node_kind="prism", rail_kind="mixed", base_exposure=3.20, support_fill=0.02),
    ),
    (
        "rampart",
        "A staggered rampart of lights keeps a firm silhouette",
        dict(lanes=(-0.40, 0.0, 0.40), rows=4, layout="zigzag", node_kind="biconvex", rail_kind="soft", base_exposure=3.15, support_fill=0.01),
    ),
    (
        "corridor",
        "A corridor of towers runs cleanly through the middle",
        dict(lanes=(-0.36, 0.36), rows=5, layout="sway", node_kind="plano", rail_kind="mirror", base_exposure=3.13, support_fill=0.01),
    ),
    (
        "mast",
        "A clustered mast keeps the beacons tightly aligned",
        dict(lanes=(-0.10, 0.0, 0.10), rows=6, layout="stack", node_kind="focus", rail_kind="mixed", base_exposure=3.23, support_fill=0.02),
    ),
    (
        "plinth",
        "A small plinth of optics stays simple and luminous",
        dict(lanes=(-0.22, 0.22), rows=4, layout="zigzag", node_kind="prism", rail_kind="soft", base_exposure=3.16, support_fill=0.01),
    ),
    (
        "gallery",
        "A shallow gallery of beacons uses width without clutter",
        dict(lanes=(-0.44, -0.14, 0.14, 0.44), rows=3, layout="sway", node_kind="ball", rail_kind="mirror", base_exposure=3.09, support_fill=0.00),
    ),
    (
        "lantern",
        "A lantern-like beacon pair keeps the room open",
        dict(lanes=(-0.18, 0.18), rows=5, layout="stack", node_kind="biconvex", rail_kind="mixed", base_exposure=3.18, support_fill=0.01),
    ),
]


def _scene(
    name: str,
    description: str,
    *,
    lanes: tuple[float, ...],
    rows: int,
    layout: str,
    node_kind: str,
    rail_kind: str,
    beam_layout: str,
    base_exposure: float,
    support_fill: float,
):
    return with_family(
        make_beacon_stack_spec(
            name,
            description,
            lanes=lanes,
            rows=rows,
            layout=layout,
            node_kind=node_kind,
            rail_kind=rail_kind,
            beam_layout=beam_layout,
            base_exposure=base_exposure,
            support_fill=support_fill,
        ),
        FAMILY,
    )


SCENES = [
    _scene(
        f"beacon_{theme}_{variant}",
        f"{subject} {variant_desc}.",
        lanes=params["lanes"],
        rows=params["rows"],
        layout=params["layout"],
        node_kind=params["node_kind"],
        rail_kind=params["rail_kind"],
        beam_layout=beam_layout,
        base_exposure=params["base_exposure"] + exposure_delta,
        support_fill=max(0.0, params["support_fill"] + fill_delta),
    )
    for theme, subject, params in _THEMES
    for variant, variant_desc, beam_layout, exposure_delta, fill_delta in _VARIANTS
]
