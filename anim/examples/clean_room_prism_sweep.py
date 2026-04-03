"""A diagonal prism sweep catches light from both side walls."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_prism_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_prism_field_spec(
    "prism_sweep",
    "A diagonal prism sweep catches light from both side walls.",
    layout="sweep",
    count=4,
    prism_radius=0.18,
    beam_layout="dual_side",
    base_exposure=3.10,
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
