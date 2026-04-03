"""Four mirrored crescents orbit around warm and white beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_arc_cluster_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_arc_cluster_spec(
    "arc_bloom",
    "Four mirrored crescents orbit around warm and white beams.",
    ring_count=4,
    orbit_rx=0.62,
    orbit_ry=0.34,
    arc_radius=0.34,
    local_start=0.18 * 3.141592653589793,
    local_sweep=0.92 * 3.141592653589793,
    beam_layout="dual_side",
    base_exposure=3.10,
    support_fill=0.04,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
