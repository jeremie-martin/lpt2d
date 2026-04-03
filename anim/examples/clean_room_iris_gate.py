"""An iris of mirror blades opens and closes under a bright top beam."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_rotor_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_rotor_spec(
    "iris_gate",
    "An iris of mirror blades opens and closes under a bright top beam.",
    pivots=[(0.0, 0.0)],
    blade_count=8,
    blade_length=0.52,
    spread=0.0,
    radial=True,
    beam_layout="triad",
    base_exposure=3.40,
    hub_kind="lens",
    support_fill=0.06,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
