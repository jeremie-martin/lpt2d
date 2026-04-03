"""A small grid of mixed lenses glows between warm and white side beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_lens_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_lens_field_spec(
    "doublet_grid",
    "A small grid of mixed lenses glows between warm and white side beams.",
    layout="grid",
    count=6,
    beam_layout="warm_white",
    base_exposure=3.35,
    support_fill=0.05,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
