"""Two opposing rotor fans trade warm and white light across the room."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_rotor_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_rotor_spec(
    "counter_rotor",
    "Two opposing rotor fans trade warm and white light across the room.",
    pivots=[(-0.6, 0.0), (0.6, 0.0)],
    blade_count=5,
    blade_length=0.64,
    spread=1.1,
    radial=False,
    beam_layout="triad",
    base_exposure=3.25,
    hub_kind="prism",
    support_fill=0.05,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
