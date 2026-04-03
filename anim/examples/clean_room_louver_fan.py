"""A wide right-wall fan throws mirror slats across a warm side beam."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_rotor_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_rotor_spec(
    "louver_fan",
    "A wide right-wall fan throws mirror slats across a warm side beam.",
    pivots=[(0.78, 0.0)],
    blade_count=6,
    blade_length=0.78,
    spread=1.15,
    radial=False,
    beam_layout="warm_white",
    base_exposure=3.25,
    hub_kind="prism",
    support_fill=0.06,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
