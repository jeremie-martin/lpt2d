"""A ring of lenses forms a halo beneath a three-way beam setup."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_lens_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_lens_field_spec(
    "halo_lenses",
    "A ring of lenses forms a halo beneath a three-way beam setup.",
    layout="halo",
    count=5,
    beam_layout="triad",
    base_exposure=3.02,
    support_fill=0.02,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
