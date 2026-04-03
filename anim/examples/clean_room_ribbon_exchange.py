"""A ribbon pair bends into an off-center beam exchange."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_ribbon_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_ribbon_spec(
    "ribbon_exchange",
    "A ribbon pair bends into an off-center beam exchange.",
    count=2,
    spacing=0.34,
    cross_bias=0.58,
    beam_layout="exchange",
    base_exposure=3.05,
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
