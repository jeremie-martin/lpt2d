"""A four-point mirror compass catches light from both sides and above."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_rotor_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_rotor_spec(
    "mirror_compass",
    "A four-point mirror compass catches light from both sides and above.",
    pivots=[(0.0, 0.0)],
    blade_count=4,
    blade_length=0.72,
    spread=0.0,
    radial=True,
    beam_layout="triad",
    base_exposure=3.15,
    hub_kind="lens",
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
