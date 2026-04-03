"""Curated mirror-fin clean-room family."""

from __future__ import annotations

import math

from anim.examples._clean_room_factories import make_fin_array_spec

FAMILY = "fins"


def _line_centers(count: int, *, y: float, span: float) -> list[tuple[float, float]]:
    return [(-span + 2 * span * index / max(count - 1, 1), y) for index in range(count)]


def _fan_centers(count: int, *, y: float, rise: float, span: float) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for index in range(count):
        x = -span + 2 * span * index / max(count - 1, 1)
        offset = index - 0.5 * (count - 1)
        centers.append((x, y + rise * math.cos(0.65 * offset)))
    return centers


def _stagger_centers(count: int, *, y0: float, y1: float, span: float) -> list[tuple[float, float]]:
    centers: list[tuple[float, float]] = []
    for index in range(count):
        x = -span + 2 * span * index / max(count - 1, 1)
        centers.append((x, y0 if index % 2 == 0 else y1))
    return centers


_PROFILES = [
    ("louver", _line_centers(5, y=0.0, span=0.82), math.pi * 0.5, 0.58, 0.18, "mirror", "focus", 3.02, 0.00),
    ("wicket", _line_centers(4, y=0.0, span=0.6), math.pi * 0.5, 0.66, 0.22, "mirror", "prism", 3.04, 0.01),
    ("comb", _stagger_centers(6, y0=-0.22, y1=0.22, span=0.84), math.pi * 0.5, 0.56, 0.2, "mirror", "ball", 3.08, 0.02),
    ("blind", _line_centers(6, y=0.28, span=0.9), math.pi * 0.5, 0.54, 0.16, "soft", "none", 3.06, 0.02),
    ("quill", _fan_centers(5, y=0.08, rise=0.16, span=0.72), 0.0, 0.62, 0.24, "mirror", "focus", 3.12, 0.03),
    ("bracket", _fan_centers(4, y=-0.12, rise=0.2, span=0.62), 0.0, 0.72, 0.26, "soft", "prism", 3.1, 0.03),
    ("cascade", _stagger_centers(5, y0=-0.28, y1=0.12, span=0.76), math.pi * 0.5, 0.6, 0.24, "mirror", "ball", 3.1, 0.02),
    ("fanline", _fan_centers(6, y=0.0, rise=0.12, span=0.86), 0.0, 0.52, 0.2, "soft", "focus", 3.06, 0.01),
    ("sash", _line_centers(3, y=0.0, span=0.44), math.pi * 0.5, 0.82, 0.3, "mirror", "prism", 3.08, 0.02),
    ("cleft", _stagger_centers(4, y0=-0.18, y1=0.18, span=0.58), math.pi * 0.5, 0.7, 0.28, "mirror", "focus", 3.1, 0.02),
    ("arcade", _fan_centers(5, y=-0.08, rise=0.1, span=0.78), 0.0, 0.66, 0.22, "soft", "ball", 3.14, 0.03),
    ("lantern", _line_centers(4, y=0.34, span=0.52), math.pi * 0.5, 0.52, 0.18, "mirror", "ball", 3.1, 0.02),
    ("portico", _stagger_centers(6, y0=-0.12, y1=0.28, span=0.9), math.pi * 0.5, 0.5, 0.16, "mirror", "prism", 3.12, 0.03),
    ("bastion", _line_centers(5, y=-0.2, span=0.82), math.pi * 0.5, 0.64, 0.2, "soft", "focus", 3.08, 0.02),
    ("hush", _fan_centers(4, y=0.14, rise=0.22, span=0.58), 0.0, 0.74, 0.28, "mirror", "none", 3.04, 0.01),
    ("veil", _fan_centers(6, y=0.22, rise=0.14, span=0.92), 0.0, 0.5, 0.18, "soft", "focus", 3.08, 0.02),
]

_BEAMS = [
    ("warm", "warm_white", 0.0, 0.0),
    ("triad", "triad", 0.08, 0.02),
    ("crest", "left_top", 0.04, 0.01),
]


SCENES = [
    make_fin_array_spec(
        f"fin_{name}_{beam_tag}",
        f"{name.replace('_', ' ').title()} mirror fins sweep a clean {beam_tag.replace('_', ' ')} beam field.",
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
    for name, centers, base_angle, fin_length, swing, material_kind, core_kind, base_exposure, support_fill in _PROFILES
    for beam_tag, beam_layout, exposure_bias, fill_bias in _BEAMS
]
