"""Two bright columns of lenses are scanned by warm and white side beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_lens_field_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_lens_field_spec(
    "focus_columns",
    "Two bright columns of lenses are scanned by warm and white side beams.",
    layout="columns",
    count=4,
    beam_layout="dual_side",
    base_exposure=3.20,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
