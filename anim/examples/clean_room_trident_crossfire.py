"""Three beams strike a staggered splitter trident through the room center."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_splitter_web_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_splitter_web_spec(
    "trident_crossfire",
    "Three beams strike a staggered splitter trident through the room center.",
    layout="trident",
    beam_layout="trident",
    base_exposure=2.95,
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
