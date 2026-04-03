"""A short corridor of splitters carries light from both side walls."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_splitter_web_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_splitter_web_spec(
    "splitter_corridor",
    "A short corridor of splitters carries light from both side walls.",
    layout="corridor",
    beam_layout="dual_side",
    base_exposure=3.00,
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
