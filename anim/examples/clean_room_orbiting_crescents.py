"""Five small crescents circulate around a bright dual-beam core."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_arc_cluster_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_arc_cluster_spec(
    "orbiting_crescents",
    "Five small crescents circulate around a bright dual-beam core.",
    ring_count=5,
    orbit_rx=0.72,
    orbit_ry=0.4,
    arc_radius=0.26,
    local_start=0.16 * 3.141592653589793,
    local_sweep=0.7 * 3.141592653589793,
    beam_layout="dual_side",
    base_exposure=3.20,
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
