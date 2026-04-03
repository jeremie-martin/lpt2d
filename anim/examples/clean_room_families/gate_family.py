"""Curated gate-focused clean-room scenes."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import (
    make_beacon_stack_spec,
    make_fin_array_spec,
    make_spoke_array_spec,
)
from anim.examples._clean_room_shared import SceneSpec, with_family

FAMILY = "gates"


def _fin(
    name: str,
    description: str,
    *,
    centers: list[tuple[float, float]],
    beam_layout: str,
    base_exposure: float,
    base_angle: float,
    fin_length: float,
    swing: float,
    material_kind: str,
    core_kind: str,
    support_fill: float,
) -> SceneSpec:
    return with_family(
        make_fin_array_spec(
            name,
            description,
            centers=centers,
            beam_layout=beam_layout,
            base_exposure=base_exposure,
            base_angle=base_angle,
            fin_length=fin_length,
            swing=swing,
            material_kind=material_kind,
            core_kind=core_kind,
            support_fill=support_fill,
        ),
        FAMILY,
    )


def _spoke(
    name: str,
    description: str,
    *,
    count: int,
    radius_inner: float,
    radius_outer: float,
    beam_layout: str,
    base_exposure: float,
    segment_kind: str,
    node_kind: str,
    twist: float,
    support_fill: float,
) -> SceneSpec:
    return with_family(
        make_spoke_array_spec(
            name,
            description,
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


def _beacon(
    name: str,
    description: str,
    *,
    lanes: tuple[float, ...],
    rows: int,
    beam_layout: str,
    base_exposure: float,
    node_kind: str,
    rail_kind: str,
    layout: str,
    support_fill: float,
) -> SceneSpec:
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


def _paired_columns(x: float, *, rows: int, span: float, y_shift: float = 0.0) -> list[tuple[float, float]]:
    ys = [y_shift + (-0.5 + row / max(rows - 1, 1)) * span for row in range(rows)]
    return [(-x, y) for y in ys] + [(x, y) for y in ys]


def _triple_columns(xs: tuple[float, float, float], *, rows: int, span: float, y_shift: float = 0.0) -> list[tuple[float, float]]:
    ys = [y_shift + (-0.5 + row / max(rows - 1, 1)) * span for row in range(rows)]
    return [(x, y) for x in xs for y in ys]


def _grid(xs: tuple[float, ...], ys: tuple[float, ...]) -> list[tuple[float, float]]:
    return [(x, y) for y in ys for x in xs]


def _ring(count: int, rx: float, ry: float, *, phase: float = 0.0, y_shift: float = 0.0) -> list[tuple[float, float]]:
    return [
        (rx * math.cos(phase + index * math.tau / count), y_shift + ry * math.sin(phase + index * math.tau / count))
        for index in range(count)
    ]


_FIN_VARIANTS = [
    ("dual", "dual-side beams", "dual_side", 3.08, 0.02, 0.96, 0.92),
    ("warm", "warm-white beams", "warm_white", 3.16, 0.03, 1.00, 1.00),
    ("triad", "triad beams", "triad", 3.24, 0.04, 1.04, 1.06),
]

_FIN_PATTERNS = [
    (
        "shutter_pair",
        "Twin shutters breathe around a central slot.",
        dict(
            centers=_paired_columns(0.60, rows=4, span=0.84),
            base_angle=math.pi / 2,
            fin_length=0.62,
            swing=0.22,
            material_kind="mirror",
            core_kind="prism",
        ),
    ),
    (
        "wicket_pair",
        "A narrow wicket opens on a bright side beam.",
        dict(
            centers=_paired_columns(0.42, rows=3, span=0.60),
            base_angle=math.pi / 2,
            fin_length=0.50,
            swing=0.18,
            material_kind="soft",
            core_kind="ball",
        ),
    ),
    (
        "threshold_row",
        "A low threshold row slides across the room.",
        dict(
            centers=_grid((-0.76, -0.34, 0.10, 0.54, 0.86), (-0.18, 0.18)),
            base_angle=0.0,
            fin_length=0.54,
            swing=0.14,
            material_kind="mixed",
            core_kind="plano",
        ),
    ),
    (
        "louver_stack",
        "A louvered gate fans open under warm and white beams.",
        dict(
            centers=_paired_columns(0.72, rows=5, span=0.72),
            base_angle=math.pi / 2,
            fin_length=0.60,
            swing=0.28,
            material_kind="mirror",
            core_kind="biconvex",
        ),
    ),
    (
        "gatefold",
        "A folded gate keeps a clean central gap.",
        dict(
            centers=_triple_columns((-0.68, 0.0, 0.68), rows=4, span=0.70),
            base_angle=math.pi / 2,
            fin_length=0.58,
            swing=0.24,
            material_kind="mixed",
            core_kind="prism",
        ),
    ),
    (
        "portcullis",
        "A portcullis grid rises in a calm, readable lattice.",
        dict(
            centers=_grid((-0.74, -0.37, 0.0, 0.37, 0.74), (-0.48, -0.14, 0.20)),
            base_angle=math.pi / 2,
            fin_length=0.46,
            swing=0.18,
            material_kind="soft",
            core_kind="none",
        ),
    ),
    (
        "aperture_gate",
        "A ring of gate fins turns like an aperture.",
        dict(
            centers=_ring(6, 0.72, 0.34, phase=0.12),
            base_angle=math.pi / 2,
            fin_length=0.54,
            swing=0.20,
            material_kind="mirror",
            core_kind="ball",
        ),
    ),
    (
        "blade_gate",
        "A diagonal blade gate cuts the room with a clean opening.",
        dict(
            centers=[(-0.68, -0.24), (-0.34, -0.12), (0.0, 0.0), (0.34, 0.12), (0.68, 0.24)],
            base_angle=math.pi / 4,
            fin_length=0.56,
            swing=0.16,
            material_kind="mixed",
            core_kind="prism",
        ),
    ),
]

_SPOKE_VARIANTS = [
    ("dual", "dual-side beams", "dual_side", 3.10, 0.02, 0.96, 0.92),
    ("warm", "warm-white beams", "warm_white", 3.18, 0.03, 1.00, 1.00),
    ("triad", "triad beams", "triad", 3.26, 0.04, 1.04, 1.04),
]

_SPOKE_PATTERNS = [
    (
        "rosette",
        "A rosette aperture turns like a clean iris.",
        dict(count=6, radius_inner=0.08, radius_outer=0.62, segment_kind="mixed", node_kind="prism", twist=0.18),
    ),
    (
        "halo",
        "A halo wheel breathes under the beam pair.",
        dict(count=8, radius_inner=0.09, radius_outer=0.68, segment_kind="soft", node_kind="ball", twist=0.22),
    ),
    (
        "compass",
        "A compass aperture keeps a bright axial cross.",
        dict(count=10, radius_inner=0.10, radius_outer=0.62, segment_kind="splitter", node_kind="focus", twist=0.15),
    ),
    (
        "wreath",
        "A wreath of spokes locks around a white center.",
        dict(count=12, radius_inner=0.09, radius_outer=0.70, segment_kind="mixed", node_kind="plano", twist=0.12),
    ),
]

_BEACON_VARIANTS = [
    ("dual", "dual-side beams", "dual_side", 3.12, 0.02),
    ("warm", "warm-white beams", "warm_white", 3.20, 0.03),
    ("triad", "triad beams", "triad", 3.28, 0.04),
]

_BEACON_PATTERNS = [
    (
        "sluice_stack",
        "A stacked sluice gate keeps its rails narrow and bright.",
        dict(lanes=(-0.60, 0.0, 0.60), rows=4, node_kind="prism", rail_kind="mirror", layout="stack"),
    ),
    (
        "wicket_rails",
        "A wicket gate ripples between soft rails.",
        dict(lanes=(-0.44, 0.44), rows=5, node_kind="ball", rail_kind="soft", layout="zigzag"),
    ),
    (
        "drawbridge",
        "A drawbridge lane sweeps through a measured threshold.",
        dict(lanes=(-0.74, -0.26, 0.26, 0.74), rows=3, node_kind="focus", rail_kind="splitter", layout="sway"),
    ),
    (
        "threshold_spine",
        "A spine of threshold posts climbs the room center.",
        dict(lanes=(-0.44, 0.0, 0.44), rows=5, node_kind="ball", rail_kind="mirror", layout="stack"),
    ),
]


SCENES = [
    _fin(
        f"gate_{slug}_{variant}",
        f"{description} {variant_desc}.",
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
        fin_length=params["fin_length"] * length_scale,
        swing=params["swing"] * swing_scale,
        material_kind=params["material_kind"],
        core_kind=params["core_kind"],
        base_angle=params["base_angle"],
        centers=params["centers"],
    )
    for slug, description, params in _FIN_PATTERNS
    for variant, variant_desc, beam_layout, base_exposure, support_fill, length_scale, swing_scale in _FIN_VARIANTS
] + [
    _spoke(
        f"gate_{slug}_{variant}",
        f"{description} {variant_desc}.",
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
        count=params["count"],
        radius_inner=params["radius_inner"],
        radius_outer=params["radius_outer"],
        segment_kind=params["segment_kind"],
        node_kind=params["node_kind"],
        twist=params["twist"],
    )
    for slug, description, params in _SPOKE_PATTERNS
    for variant, variant_desc, beam_layout, base_exposure, support_fill, _, _ in _SPOKE_VARIANTS
] + [
    _beacon(
        f"gate_{slug}_{variant}",
        f"{description} {variant_desc}.",
        beam_layout=beam_layout,
        base_exposure=base_exposure,
        support_fill=support_fill,
        lanes=params["lanes"],
        rows=params["rows"],
        node_kind=params["node_kind"],
        rail_kind=params["rail_kind"],
        layout=params["layout"],
    )
    for slug, description, params in _BEACON_PATTERNS
    for variant, variant_desc, beam_layout, base_exposure, support_fill in _BEACON_VARIANTS
]
