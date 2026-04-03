"""A stair of lenses climbs diagonally through a warm scan beam."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_lens_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_lens_field_spec(
    "caustic_stair",
    "A stair of lenses climbs diagonally through a warm scan beam.",
    layout="stair",
    count=5,
    beam_layout="left_top",
    base_exposure=3.25,
    support_fill=0.06,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
