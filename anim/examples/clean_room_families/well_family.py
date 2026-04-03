"""Curated well-focused clean-room scenes."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import (
    make_arc_cluster_spec,
    make_lens_field_spec,
    make_spoke_array_spec,
)
from anim.examples._clean_room_shared import SceneSpec, with_family

FAMILY = "wells"

_EXPOSURE_BIAS = {
    "dual_side": 0.03,
    "warm_white": 0.02,
    "left_top": 0.03,
    "triad": 0.01,
    "exchange": 0.02,
    "top": 0.02,
}

_FILL_BIAS = {
    "left_top": 0.01,
    "triad": 0.01,
    "top": 0.01,
}

_BEAM_LABELS = {
    "left": "left beam",
    "dual_side": "dual-side beams",
    "left_top": "left-plus-top beams",
    "triad": "triad beams",
    "warm_white": "warm-white pair",
    "exchange": "exchange beams",
    "top": "top beam",
}


def _spoke(
    name: str,
    description: str,
    *,
    count: int,
    radius_inner: float,
    radius_outer: float,
    beam_layout: str,
    base_exposure: float,
    segment_kind: str = "mixed",
    node_kind: str = "prism",
    twist: float = 0.22,
    support_fill: float = 0.0,
) -> SceneSpec:
    return with_family(
        make_spoke_array_spec(
            name,
            description,
            count=count,
            radius_inner=radius_inner,
            radius_outer=radius_outer,
            beam_layout=beam_layout,
            base_exposure=base_exposure + _EXPOSURE_BIAS.get(beam_layout, 0.0),
            segment_kind=segment_kind,
            node_kind=node_kind,
            twist=twist,
            support_fill=max(0.0, support_fill + _FILL_BIAS.get(beam_layout, 0.0)),
        ),
        FAMILY,
    )


def _rim(
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
    spin_rate: float = 0.12,
    wobble: float = 0.10,
    core_radius: float = 0.06,
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
            base_exposure=base_exposure + _EXPOSURE_BIAS.get(beam_layout, 0.0),
            support_fill=max(0.0, support_fill + _FILL_BIAS.get(beam_layout, 0.0)),
            spin_rate=spin_rate,
            wobble=wobble,
            core_radius=core_radius,
        ),
        FAMILY,
    )


def _window(
    name: str,
    description: str,
    *,
    layout: str,
    count: int,
    beam_layout: str,
    base_exposure: float,
    support_fill: float = 0.0,
) -> SceneSpec:
    return with_family(
        make_lens_field_spec(
            name,
            description,
            layout=layout,
            count=count,
            beam_layout=beam_layout,
            base_exposure=base_exposure + _EXPOSURE_BIAS.get(beam_layout, 0.0),
            support_fill=max(0.0, support_fill + _FILL_BIAS.get(beam_layout, 0.0)),
        ),
        FAMILY,
    )


def _series(
    theme_label: str,
    rows: list[tuple[str, ...]],
) -> list[SceneSpec]:
    prefix = theme_label.replace(" ", "_")
    scenes: list[SceneSpec] = []
    for row in rows:
        slug = row[0]
        beam_layout = row[5]
        description = f"{slug.replace('_', ' ').capitalize()} {theme_label} with {_BEAM_LABELS[beam_layout]}."
        scenes.append(
            _spoke(
                f"{prefix}_{slug}",
                description,
                count=int(row[1]),
                radius_inner=float(row[2]),
                radius_outer=float(row[3]),
                beam_layout=beam_layout,
                base_exposure=float(row[4]),
                segment_kind=row[6],
                node_kind=row[7],
                twist=float(row[8]),
                support_fill=float(row[9]),
            )
        )
    return scenes


def _rim_series(
    theme_label: str,
    rows: list[tuple[str, int, float, float, float, float, float, str, float, float]],
) -> list[SceneSpec]:
    prefix = theme_label.replace(" ", "_")
    scenes: list[SceneSpec] = []
    for slug, ring_count, orbit_rx, orbit_ry, arc_radius, local_start, local_sweep, beam_layout, exposure, fill in rows:
        description = f"{slug.replace('_', ' ').capitalize()} {theme_label} with {_BEAM_LABELS[beam_layout]}."
        scenes.append(
            _rim(
                f"{prefix}_{slug}",
                description,
                ring_count=ring_count,
                orbit_rx=orbit_rx,
                orbit_ry=orbit_ry,
                arc_radius=arc_radius,
                local_start=local_start,
                local_sweep=local_sweep,
                beam_layout=beam_layout,
                base_exposure=exposure,
                support_fill=fill,
            )
        )
    return scenes


def _window_series(
    theme_label: str,
    rows: list[tuple[str, str, int, str, float, float]],
) -> list[SceneSpec]:
    prefix = theme_label.replace(" ", "_")
    scenes: list[SceneSpec] = []
    for slug, layout, count, beam_layout, exposure, fill in rows:
        description = f"{slug.replace('_', ' ').capitalize()} {theme_label} with {_BEAM_LABELS[beam_layout]}."
        scenes.append(
            _window(
                f"{prefix}_{slug}",
                description,
                layout=layout,
                count=count,
                beam_layout=beam_layout,
                base_exposure=exposure,
                support_fill=fill,
            )
        )
    return scenes


SCENES = [
    *_series(
        "well core",
        [
            ("open", 6, 0.12, 0.74, 3.10, "warm_white", "prism", "prism", 0.18, 0.03),
            ("bright", 7, 0.14, 0.80, 3.14, "dual_side", "mixed", "focus", 0.20, 0.03),
            ("calm", 6, 0.10, 0.68, 3.08, "exchange", "soft", "ball", 0.16, 0.02),
            ("lifted", 8, 0.16, 0.84, 3.18, "left_top", "splitter", "prism", 0.24, 0.04),
            ("clear", 6, 0.11, 0.72, 3.12, "triad", "mixed", "biconvex", 0.19, 0.03),
            ("amber", 7, 0.13, 0.76, 3.16, "warm_white", "mixed", "plano", 0.22, 0.03),
            ("white", 6, 0.12, 0.70, 3.09, "dual_side", "soft", "focus", 0.17, 0.02),
            ("narrow", 5, 0.09, 0.64, 3.06, "left", "splitter", "ball", 0.15, 0.01),
        ],
    ),
    *_series(
        "well collar",
        [
            ("ring", 6, 0.14, 0.78, 3.12, "warm_white", "mixed", "prism", 0.18, 0.03),
            ("brace", 7, 0.13, 0.82, 3.16, "dual_side", "splitter", "focus", 0.20, 0.03),
            ("halo", 6, 0.10, 0.74, 3.11, "triad", "soft", "biconvex", 0.17, 0.02),
            ("crown", 8, 0.16, 0.86, 3.20, "left_top", "mixed", "prism", 0.23, 0.04),
            ("rim", 6, 0.12, 0.80, 3.14, "exchange", "splitter", "plano", 0.19, 0.03),
            ("shell", 7, 0.11, 0.76, 3.10, "warm_white", "soft", "focus", 0.18, 0.02),
            ("arc", 6, 0.15, 0.84, 3.17, "dual_side", "mixed", "prism", 0.21, 0.03),
            ("veil", 5, 0.09, 0.70, 3.08, "left_top", "splitter", "ball", 0.16, 0.02),
        ],
    ),
    *_series(
        "well spine",
        [
            ("column", 5, 0.08, 0.78, 3.09, "warm_white", "mixed", "prism", 0.20, 0.02),
            ("axis", 6, 0.10, 0.80, 3.12, "dual_side", "splitter", "focus", 0.22, 0.03),
            ("stack", 7, 0.12, 0.82, 3.15, "triad", "mixed", "biconvex", 0.24, 0.03),
            ("lattice", 6, 0.09, 0.74, 3.11, "exchange", "soft", "prism", 0.18, 0.02),
            ("rail", 5, 0.08, 0.72, 3.07, "left_top", "splitter", "plano", 0.16, 0.02),
            ("keel", 6, 0.11, 0.76, 3.14, "warm_white", "mixed", "focus", 0.19, 0.03),
            ("needle", 7, 0.10, 0.84, 3.18, "dual_side", "mixed", "prism", 0.23, 0.03),
            ("spoke", 6, 0.09, 0.78, 3.10, "left", "soft", "ball", 0.17, 0.01),
        ],
    ),
    *_series(
        "well aperture",
        [
            ("iris", 6, 0.10, 0.70, 3.12, "triad", "mixed", "focus", 0.18, 0.03),
            ("slit", 5, 0.08, 0.68, 3.07, "left_top", "splitter", "plano", 0.15, 0.02),
            ("gate", 7, 0.12, 0.76, 3.15, "warm_white", "mixed", "prism", 0.20, 0.03),
            ("wicket", 6, 0.09, 0.74, 3.10, "exchange", "soft", "ball", 0.17, 0.02),
            ("threshold", 8, 0.14, 0.82, 3.18, "dual_side", "splitter", "biconvex", 0.22, 0.03),
            ("passage", 6, 0.11, 0.78, 3.13, "warm_white", "mixed", "prism", 0.19, 0.03),
            ("window", 5, 0.08, 0.72, 3.09, "left_top", "soft", "focus", 0.16, 0.02),
            ("notch", 6, 0.10, 0.76, 3.11, "triad", "mixed", "plano", 0.18, 0.02),
        ],
    ),
    *_rim_series(
        "well rim",
        [
            ("crown", 4, 0.56, 0.26, 0.28, 0.18 * math.pi, 0.88 * math.pi, "warm_white", 3.12, 0.03),
            ("gate", 5, 0.60, 0.32, 0.26, 0.12 * math.pi, 0.96 * math.pi, "dual_side", 3.15, 0.03),
            ("halo", 4, 0.50, 0.22, 0.30, 0.22 * math.pi, 0.80 * math.pi, "triad", 3.10, 0.02),
            ("shell", 6, 0.64, 0.34, 0.24, 0.14 * math.pi, 0.92 * math.pi, "left_top", 3.18, 0.04),
        ],
    ),
    *_window_series(
        "well window",
        [
            ("ring", "ring", 4, "warm_white", 3.14, 0.03),
            ("diamond", "diamond", 4, "dual_side", 3.12, 0.03),
            ("grid", "grid", 5, "triad", 3.11, 0.02),
            ("stair", "stair", 5, "left_top", 3.16, 0.03),
        ],
    ),
]

assert len(SCENES) == 40
