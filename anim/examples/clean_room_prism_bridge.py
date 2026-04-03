"""A bridge of prisms floats between warm and white side beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_prism_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_prism_field_spec(
    "prism_bridge",
    "A bridge of prisms floats between warm and white side beams.",
    layout="bridge",
    count=4,
    prism_radius=0.18,
    beam_layout="warm_white",
    base_exposure=3.15,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
