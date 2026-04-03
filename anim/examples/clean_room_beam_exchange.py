"""Two diagonal splitters stage a clean warm-white beam exchange."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_splitter_web_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_splitter_web_spec(
    "beam_exchange",
    "Two diagonal splitters stage a clean warm-white beam exchange.",
    layout="exchange",
    beam_layout="warm_white",
    base_exposure=3.00,
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
