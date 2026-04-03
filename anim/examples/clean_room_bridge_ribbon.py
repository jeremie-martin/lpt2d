"""Three ribbons form a gentle bridge beneath a side beam and a top wash."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_ribbon_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_ribbon_spec(
    "bridge_ribbon",
    "Three ribbons form a gentle bridge beneath a side beam and a top wash.",
    count=3,
    spacing=0.22,
    cross_bias=0.32,
    beam_layout="left_top",
    base_exposure=3.25,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
