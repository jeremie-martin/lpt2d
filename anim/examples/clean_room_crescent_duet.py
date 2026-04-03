"""Two large crescents trade the spotlight between a side beam and a top beam."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_arc_cluster_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_arc_cluster_spec(
    "crescent_duet",
    "Two large crescents trade the spotlight between a side beam and a top beam.",
    ring_count=2,
    orbit_rx=0.12,
    orbit_ry=0.56,
    arc_radius=0.42,
    local_start=0.24 * 3.141592653589793,
    local_sweep=1.08 * 3.141592653589793,
    beam_layout="left_top",
    base_exposure=3.18,
    support_fill=0.05,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
