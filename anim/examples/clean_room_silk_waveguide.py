"""Four fine ribbons create a brighter silk-like waveguide sheet."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_ribbon_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_ribbon_spec(
    "silk_waveguide",
    "Four fine ribbons create a brighter silk-like waveguide sheet.",
    count=4,
    spacing=0.16,
    cross_bias=0.22,
    beam_layout="left_top",
    base_exposure=3.45,
    support_fill=0.07,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
