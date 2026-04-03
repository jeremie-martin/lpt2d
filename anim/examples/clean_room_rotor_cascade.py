"""Three small rotors climb diagonally through a warm-white beam exchange."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_rotor_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_rotor_spec(
    "rotor_cascade",
    "Three small rotors climb diagonally through a warm-white beam exchange.",
    pivots=[(-0.72, -0.28), (0.0, 0.0), (0.72, 0.28)],
    blade_count=4,
    blade_length=0.46,
    spread=0.9,
    radial=False,
    beam_layout="warm_white",
    base_exposure=3.10,
    hub_kind="prism",
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
