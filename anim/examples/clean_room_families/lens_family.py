"""Curated refractive studies centered on lenses."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_lens_field_spec
from anim.examples._clean_room_shared import SceneSpec, with_family

FAMILY = "lenses"

_LAYOUT_EXPOSURE_BIAS = {
    "columns": -0.52,
    "grid": -0.26,
    "ring": -0.15,
    "diamond": -0.12,
    "stair": -0.10,
}

_BEAM_EXPOSURE_BIAS = {
    "triad": -0.05,
    "top": -0.03,
}

_LAYOUT_FILL_BIAS = {
    "columns": -0.02,
    "grid": -0.01,
}

BEAM_LABELS = {
    "left": "left beam",
    "dual_side": "dual-side beams",
    "left_top": "left-plus-top beams",
    "triad": "triad beams",
    "warm_white": "warm-white pair",
    "top": "top beam",
}


def _make(
    name: str,
    description: str,
    *,
    layout: str,
    count: int,
    beam_layout: str,
    base_exposure: float,
    support_fill: float,
) -> SceneSpec:
    return with_family(
        make_lens_field_spec(
            name,
            description,
            layout=layout,
            count=count,
            beam_layout=beam_layout,
            base_exposure=(
                base_exposure
                + _LAYOUT_EXPOSURE_BIAS.get(layout, 0.0)
                + _BEAM_EXPOSURE_BIAS.get(beam_layout, 0.0)
            ),
            support_fill=max(0.0, support_fill + _LAYOUT_FILL_BIAS.get(layout, 0.0)),
        ),
        FAMILY,
    )


def _series(
    theme_label: str,
    layout: str,
    rows: list[tuple[str, int, str, float, float]],
) -> list[SceneSpec]:
    prefix = theme_label.replace(" ", "_")
    scenes: list[SceneSpec] = []
    for slug, count, beam_layout, exposure, support_fill in rows:
        description = f"{slug.replace('_', ' ').capitalize()} {theme_label} with {BEAM_LABELS[beam_layout]}."
        scenes.append(
            _make(
                f"{prefix}_{slug}",
                description,
                layout=layout,
                count=count,
                beam_layout=beam_layout,
                base_exposure=exposure,
                support_fill=support_fill,
            )
        )
    return scenes


SCENES: list[SceneSpec] = [
    *_series(
        "column wash",
        "columns",
        [
            ("soft", 4, "warm_white", 3.34, 0.05),
            ("bright", 4, "dual_side", 3.30, 0.04),
            ("lifted", 4, "left_top", 3.44, 0.05),
            ("split", 4, "triad", 3.25, 0.03),
            ("narrow", 4, "left", 3.48, 0.02),
            ("airy", 4, "warm_white", 3.36, 0.04),
            ("crisp", 4, "dual_side", 3.33, 0.03),
            ("white", 4, "top", 3.40, 0.04),
            ("warm", 4, "triad", 3.29, 0.05),
            ("open", 4, "warm_white", 3.37, 0.04),
        ],
    ),
    *_series(
        "column edge",
        "columns",
        [
            ("soft", 4, "dual_side", 3.38, 0.04),
            ("tall", 4, "left_top", 3.46, 0.05),
            ("bright", 4, "warm_white", 3.32, 0.04),
            ("split", 4, "triad", 3.31, 0.03),
            ("sleek", 4, "left", 3.50, 0.02),
            ("open", 4, "top", 3.42, 0.04),
            ("calm", 4, "dual_side", 3.35, 0.04),
            ("white", 4, "warm_white", 3.34, 0.05),
            ("lit", 4, "left_top", 3.47, 0.05),
            ("clear", 4, "triad", 3.30, 0.03),
        ],
    ),
    *_series(
        "stair scan",
        "stair",
        [
            ("ascending", 4, "left_top", 3.35, 0.04),
            ("descending", 5, "warm_white", 3.42, 0.05),
            ("stepped", 4, "triad", 3.28, 0.03),
            ("shallow", 5, "dual_side", 3.31, 0.04),
            ("bright", 4, "left_top", 3.44, 0.05),
            ("open", 5, "warm_white", 3.36, 0.04),
            ("tight", 4, "left", 3.48, 0.02),
            ("white", 5, "top", 3.40, 0.05),
            ("airy", 4, "triad", 3.30, 0.03),
            ("balanced", 5, "dual_side", 3.33, 0.04),
        ],
    ),
    *_series(
        "diamond gate",
        "diamond",
        [
            ("centered", 4, "warm_white", 3.34, 0.04),
            ("lifted", 4, "dual_side", 3.36, 0.04),
            ("bright", 4, "triad", 3.28, 0.03),
            ("soft", 4, "left_top", 3.43, 0.05),
            ("open", 4, "warm_white", 3.31, 0.04),
            ("white", 4, "top", 3.40, 0.04),
            ("clear", 4, "triad", 3.29, 0.03),
            ("paired", 4, "dual_side", 3.35, 0.04),
            ("narrow", 4, "left", 3.46, 0.02),
            ("airy", 4, "warm_white", 3.33, 0.05),
        ],
    ),
    *_series(
        "grid lattice",
        "grid",
        [
            ("square", 4, "warm_white", 3.35, 0.04),
            ("cross", 6, "dual_side", 3.30, 0.05),
            ("layered", 5, "triad", 3.28, 0.03),
            ("bright", 6, "left_top", 3.42, 0.05),
            ("open", 4, "top", 3.39, 0.04),
            ("white", 5, "warm_white", 3.34, 0.04),
            ("compact", 4, "left", 3.46, 0.02),
            ("airy", 6, "dual_side", 3.32, 0.04),
            ("crisp", 5, "triad", 3.29, 0.03),
            ("balanced", 4, "warm_white", 3.37, 0.04),
        ],
    ),
    *_series(
        "ring halo",
        "ring",
        [
            ("soft", 4, "warm_white", 3.34, 0.04),
            ("bright", 5, "dual_side", 3.31, 0.04),
            ("lifted", 6, "left_top", 3.44, 0.05),
            ("split", 5, "triad", 3.27, 0.03),
            ("white", 4, "top", 3.40, 0.04),
            ("open", 6, "warm_white", 3.33, 0.05),
            ("airy", 5, "dual_side", 3.35, 0.04),
            ("crisp", 4, "left", 3.47, 0.02),
            ("clear", 6, "triad", 3.29, 0.03),
            ("warm", 5, "warm_white", 3.36, 0.05),
        ],
    ),
    *_series(
        "ring window",
        "ring",
        [
            ("windowed", 4, "left_top", 3.41, 0.04),
            ("amber", 5, "warm_white", 3.33, 0.05),
            ("white", 6, "dual_side", 3.30, 0.04),
            ("lifted", 4, "triad", 3.28, 0.03),
            ("narrow", 5, "left", 3.45, 0.02),
            ("open", 6, "top", 3.39, 0.04),
            ("bright", 4, "warm_white", 3.35, 0.04),
            ("paired", 5, "dual_side", 3.32, 0.04),
            ("clear", 6, "triad", 3.29, 0.03),
            ("airy", 4, "warm_white", 3.36, 0.05),
        ],
    ),
]

assert len(SCENES) == 70
