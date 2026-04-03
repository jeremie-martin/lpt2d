"""A straight parade of prisms glows between a warm beam and white support light."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_prism_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_prism_field_spec(
    "prism_parade",
    "A straight parade of prisms glows between a warm beam and white support light.",
    layout="line",
    count=5,
    prism_radius=0.16,
    beam_layout="warm_white",
    base_exposure=3.05,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
