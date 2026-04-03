"""Two wide ribbons exchange a warm beam and white support light."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_ribbon_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_ribbon_spec(
    "dual_ribbon",
    "Two wide ribbons exchange a warm beam and white support light.",
    count=2,
    spacing=0.28,
    cross_bias=0.44,
    beam_layout="dual_side",
    base_exposure=3.20,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
