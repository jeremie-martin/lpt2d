"""A ring of prisms turns like a drum under a warm lead beam."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_prism_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_prism_field_spec(
    "prism_drum",
    "A ring of prisms turns like a drum under a warm lead beam.",
    layout="ring",
    count=5,
    prism_radius=0.17,
    beam_layout="warm_white",
    base_exposure=3.35,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
