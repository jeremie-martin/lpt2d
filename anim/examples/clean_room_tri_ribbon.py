"""Three ribbon lanes braid through warm and white side beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_ribbon_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_ribbon_spec(
    "tri_ribbon",
    "Three ribbon lanes braid through warm and white side beams.",
    count=3,
    spacing=0.26,
    cross_bias=0.48,
    beam_layout="warm_white",
    base_exposure=3.15,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
