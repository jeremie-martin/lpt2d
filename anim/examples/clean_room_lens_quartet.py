"""A diamond quartet of lenses is lit by a side beam and a top wash."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_lens_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_lens_field_spec(
    "lens_quartet",
    "A diamond quartet of lenses is lit by a side beam and a top wash.",
    layout="diamond",
    count=4,
    beam_layout="left_top",
    base_exposure=3.25,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
