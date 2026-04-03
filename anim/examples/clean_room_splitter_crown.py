"""A crown of splitters sits under a side beam and a top wash."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_splitter_web_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_splitter_web_spec(
    "splitter_crown",
    "A crown of splitters sits under a side beam and a top wash.",
    layout="crown",
    beam_layout="left_top",
    base_exposure=3.10,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
