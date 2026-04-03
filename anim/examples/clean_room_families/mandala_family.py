"""Curated mandala-focused clean-room scenes."""

from __future__ import annotations

from anim.examples._clean_room_factories import (
    make_arc_cluster_spec,
    make_prism_field_spec,
    make_spoke_array_spec,
)
from anim.examples._clean_room_shared import with_family

FAMILY = "mandalas"

BEAM_PHRASES = {
    "left": "a single warm beam",
    "dual_side": "balanced warm and white side beams",
    "exchange": "crossing warm and white beams",
    "left_top": "a warm side beam and a soft top support beam",
    "triad": "a warm-white triad of beams",
    "warm_white": "paired warm and white beams",
}


def _describe(theme: str, slug: str, beam_layout: str) -> str:
    return f"{slug.replace('_', ' ').capitalize()} forms a {theme} mandala under {BEAM_PHRASES[beam_layout]}."


def _spoke(
    name: str,
    theme: str,
    slug: str,
    *,
    count: int,
    radius_inner: float,
    radius_outer: float,
    beam_layout: str,
    base_exposure: float,
    segment_kind: str = "mixed",
    node_kind: str = "prism",
    twist: float = 0.22,
    support_fill: float = 0.02,
):
    return with_family(
        make_spoke_array_spec(
            name,
            _describe(theme, slug, beam_layout),
            count=count,
            radius_inner=radius_inner,
            radius_outer=radius_outer,
            beam_layout=beam_layout,
            base_exposure=base_exposure,
            segment_kind=segment_kind,
            node_kind=node_kind,
            twist=twist,
            support_fill=support_fill,
        ),
        FAMILY,
    )


def _arc(
    name: str,
    theme: str,
    slug: str,
    *,
    ring_count: int,
    orbit_rx: float,
    orbit_ry: float,
    arc_radius: float,
    local_start: float,
    local_sweep: float,
    beam_layout: str,
    base_exposure: float,
    support_fill: float = 0.03,
):
    return with_family(
        make_arc_cluster_spec(
            name,
            _describe(theme, slug, beam_layout),
            ring_count=ring_count,
            orbit_rx=orbit_rx,
            orbit_ry=orbit_ry,
            arc_radius=arc_radius,
            local_start=local_start,
            local_sweep=local_sweep,
            beam_layout=beam_layout,
            base_exposure=base_exposure,
            support_fill=support_fill,
        ),
        FAMILY,
    )


def _prism(
    name: str,
    theme: str,
    slug: str,
    *,
    layout: str,
    count: int,
    prism_radius: float,
    beam_layout: str,
    base_exposure: float,
    support_fill: float = 0.03,
):
    return with_family(
        make_prism_field_spec(
            name,
            _describe(theme, slug, beam_layout),
            layout=layout,
            count=count,
            prism_radius=prism_radius,
            beam_layout=beam_layout,
            base_exposure=base_exposure,
            support_fill=support_fill,
        ),
        FAMILY,
    )


def _series(theme: str, rows: list[tuple[str, int, float, float, str, float, str, str, float, float]]) -> list:
    prefix = f"mandala_{theme.replace(' ', '_')}"
    scenes = []
    for slug, count, inner, outer, beam_layout, exposure, node_kind, segment_kind, twist, fill in rows:
        scenes.append(
            _spoke(
                f"{prefix}_{slug}",
                theme,
                slug,
                count=count,
                radius_inner=inner,
                radius_outer=outer,
                beam_layout=beam_layout,
                base_exposure=exposure,
                node_kind=node_kind,
                segment_kind=segment_kind,
                twist=twist,
                support_fill=fill,
            )
        )
    return scenes


SCENES = [
    *_series(
        "rosette",
        [
            ("petal", 6, 0.14, 0.66, "warm_white", 3.20, "prism", "mixed", 0.20, 0.02),
            ("bloom", 7, 0.16, 0.72, "dual_side", 3.18, "ball", "mixed", 0.24, 0.03),
            ("lace", 5, 0.12, 0.62, "triad", 3.24, "biconvex", "mixed", 0.18, 0.03),
            ("halo", 6, 0.15, 0.74, "exchange", 3.16, "plano", "mixed", 0.26, 0.02),
            ("crest", 7, 0.17, 0.80, "left_top", 3.28, "focus", "mixed", 0.22, 0.03),
            ("medallion", 6, 0.13, 0.68, "warm_white", 3.22, "prism", "mixed", 0.28, 0.02),
        ],
    ),
    *_series(
        "halo",
        [
            ("aureole", 5, 0.14, 0.70, "warm_white", 3.18, "ball", "soft", 0.20, 0.02),
            ("corona", 6, 0.12, 0.76, "dual_side", 3.20, "plano", "soft", 0.18, 0.02),
            ("ringlet", 7, 0.16, 0.82, "triad", 3.24, "focus", "soft", 0.22, 0.03),
            ("wreath", 5, 0.15, 0.66, "exchange", 3.12, "biconvex", "soft", 0.24, 0.02),
            ("nimbus", 6, 0.13, 0.78, "left_top", 3.26, "ball", "soft", 0.20, 0.03),
            ("glow", 6, 0.14, 0.72, "warm_white", 3.18, "none", "soft", 0.26, 0.02),
        ],
    ),
    *_series(
        "crown",
        [
            ("diadem", 6, 0.14, 0.68, "triad", 3.26, "prism", "splitter", 0.24, 0.03),
            ("circlet", 5, 0.12, 0.74, "warm_white", 3.18, "focus", "splitter", 0.20, 0.02),
            ("tiara", 7, 0.16, 0.82, "left_top", 3.24, "biconvex", "splitter", 0.22, 0.03),
            ("coronet", 6, 0.15, 0.70, "dual_side", 3.20, "prism", "splitter", 0.26, 0.02),
            ("aureate", 5, 0.13, 0.76, "exchange", 3.14, "ball", "splitter", 0.18, 0.03),
            ("regalia", 6, 0.14, 0.80, "warm_white", 3.22, "prism", "splitter", 0.28, 0.03),
        ],
    ),
    *_series(
        "web",
        [
            ("lattice", 6, 0.11, 0.64, "exchange", 3.16, "none", "splitter", 0.16, 0.02),
            ("mesh", 8, 0.10, 0.72, "dual_side", 3.18, "focus", "splitter", 0.20, 0.02),
            ("filigree", 7, 0.12, 0.70, "triad", 3.22, "none", "splitter", 0.18, 0.03),
            ("tracery", 6, 0.11, 0.78, "left_top", 3.24, "prism", "splitter", 0.22, 0.02),
            ("net", 8, 0.10, 0.66, "warm_white", 3.12, "none", "splitter", 0.16, 0.01),
            ("webwork", 7, 0.11, 0.74, "exchange", 3.20, "focus", "splitter", 0.24, 0.03),
        ],
    ),
    *_series(
        "compass",
        [
            ("northstar", 6, 0.12, 0.68, "triad", 3.22, "prism", "mixed", 0.20, 0.02),
            ("bearing", 7, 0.13, 0.76, "warm_white", 3.18, "biconvex", "mixed", 0.24, 0.03),
            ("quadrant", 8, 0.10, 0.80, "exchange", 3.24, "ball", "mixed", 0.18, 0.02),
            ("radius", 6, 0.14, 0.72, "dual_side", 3.20, "focus", "mixed", 0.22, 0.03),
            ("needle", 7, 0.11, 0.66, "left_top", 3.26, "prism", "mixed", 0.16, 0.02),
            ("cardinal", 6, 0.12, 0.78, "warm_white", 3.14, "biconvex", "mixed", 0.20, 0.03),
        ],
    ),
    *_series(
        "bloom",
        [
            ("blossom", 6, 0.16, 0.70, "warm_white", 3.20, "ball", "mixed", 0.22, 0.02),
            ("petal_ring", 7, 0.14, 0.78, "dual_side", 3.18, "prism", "mixed", 0.18, 0.03),
            ("flare", 6, 0.15, 0.82, "triad", 3.26, "focus", "mixed", 0.24, 0.03),
            ("seed", 5, 0.13, 0.68, "left_top", 3.22, "plano", "mixed", 0.20, 0.02),
            ("pollen", 8, 0.10, 0.74, "exchange", 3.16, "ball", "mixed", 0.18, 0.02),
            ("sprig", 7, 0.12, 0.80, "warm_white", 3.24, "biconvex", "mixed", 0.26, 0.03),
        ],
    ),
    *_series(
        "lattice",
        [
            ("ring", 6, 0.11, 0.64, "dual_side", 3.14, "prism", "mixed", 0.18, 0.02),
            ("star", 7, 0.12, 0.72, "warm_white", 3.20, "focus", "mixed", 0.22, 0.03),
            ("crown", 8, 0.10, 0.76, "triad", 3.26, "ball", "mixed", 0.20, 0.02),
            ("lace", 6, 0.11, 0.68, "exchange", 3.18, "biconvex", "mixed", 0.18, 0.03),
            ("open", 7, 0.12, 0.76, "left_top", 3.24, "plano", "mixed", 0.24, 0.03),
            ("bright", 6, 0.13, 0.74, "warm_white", 3.22, "prism", "mixed", 0.20, 0.02),
        ],
    ),
    _arc(
        "mandala_arc_rosette",
        "arc rosette",
        "rosette",
        ring_count=4,
        orbit_rx=0.56,
        orbit_ry=0.26,
        arc_radius=0.28,
        local_start=0.16 * 3.141592653589793,
        local_sweep=0.78 * 3.141592653589793,
        beam_layout="warm_white",
        base_exposure=3.18,
    ),
    _arc(
        "mandala_arc_halo",
        "arc halo",
        "halo",
        ring_count=5,
        orbit_rx=0.62,
        orbit_ry=0.30,
        arc_radius=0.30,
        local_start=0.20 * 3.141592653589793,
        local_sweep=0.84 * 3.141592653589793,
        beam_layout="dual_side",
        base_exposure=3.20,
    ),
    _arc(
        "mandala_arc_crown",
        "arc crown",
        "crown",
        ring_count=6,
        orbit_rx=0.68,
        orbit_ry=0.34,
        arc_radius=0.26,
        local_start=0.18 * 3.141592653589793,
        local_sweep=0.74 * 3.141592653589793,
        beam_layout="triad",
        base_exposure=3.24,
    ),
    _arc(
        "mandala_arc_wreath",
        "arc wreath",
        "wreath",
        ring_count=4,
        orbit_rx=0.50,
        orbit_ry=0.40,
        arc_radius=0.24,
        local_start=0.12 * 3.141592653589793,
        local_sweep=0.90 * 3.141592653589793,
        beam_layout="exchange",
        base_exposure=3.14,
    ),
    _arc(
        "mandala_arc_filigree",
        "arc filigree",
        "filigree",
        ring_count=5,
        orbit_rx=0.72,
        orbit_ry=0.24,
        arc_radius=0.22,
        local_start=0.22 * 3.141592653589793,
        local_sweep=0.64 * 3.141592653589793,
        beam_layout="left_top",
        base_exposure=3.22,
    ),
    _arc(
        "mandala_arc_bloom",
        "arc bloom",
        "bloom",
        ring_count=6,
        orbit_rx=0.60,
        orbit_ry=0.28,
        arc_radius=0.32,
        local_start=0.14 * 3.141592653589793,
        local_sweep=0.82 * 3.141592653589793,
        beam_layout="warm_white",
        base_exposure=3.20,
    ),
    _prism(
        "mandala_prism_rosette",
        "prism rosette",
        "rosette",
        layout="ring",
        count=4,
        prism_radius=0.16,
        beam_layout="warm_white",
        base_exposure=3.18,
    ),
    _prism(
        "mandala_prism_halo",
        "prism halo",
        "halo",
        layout="ring",
        count=5,
        prism_radius=0.15,
        beam_layout="dual_side",
        base_exposure=3.20,
    ),
    _prism(
        "mandala_prism_crown",
        "prism crown",
        "crown",
        layout="ring",
        count=6,
        prism_radius=0.14,
        beam_layout="triad",
        base_exposure=3.26,
    ),
    _prism(
        "mandala_prism_wreath",
        "prism wreath",
        "wreath",
        layout="ring",
        count=5,
        prism_radius=0.15,
        beam_layout="exchange",
        base_exposure=3.16,
    ),
    _prism(
        "mandala_prism_compass",
        "prism compass",
        "compass",
        layout="ring",
        count=4,
        prism_radius=0.17,
        beam_layout="left_top",
        base_exposure=3.24,
    ),
    _prism(
        "mandala_prism_bloom",
        "prism bloom",
        "bloom",
        layout="ring",
        count=6,
        prism_radius=0.13,
        beam_layout="warm_white",
        base_exposure=3.22,
    ),
]

assert len(SCENES) == 54
