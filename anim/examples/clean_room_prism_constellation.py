"""A loose constellation of prisms sparkles under side and top beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_prism_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_prism_field_spec(
    "prism_constellation",
    "A loose constellation of prisms sparkles under side and top beams.",
    layout="constellation",
    count=6,
    prism_radius=0.15,
    beam_layout="left_top",
    base_exposure=3.25,
    support_fill=0.05,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
