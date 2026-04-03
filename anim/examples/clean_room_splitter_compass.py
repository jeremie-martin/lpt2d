"""A compass of splitters catches a warm-white trident of beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_splitter_web_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_splitter_web_spec(
    "splitter_compass",
    "A compass of splitters catches a warm-white trident of beams.",
    layout="compass",
    beam_layout="trident",
    base_exposure=3.10,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
