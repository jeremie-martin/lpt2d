"""A lantern-like cage of crescents is lit from the side and from above."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_arc_cluster_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_arc_cluster_spec(
    "arc_lantern",
    "A lantern-like cage of crescents is lit from the side and from above.",
    ring_count=4,
    orbit_rx=0.36,
    orbit_ry=0.56,
    arc_radius=0.3,
    local_start=0.18 * 3.141592653589793,
    local_sweep=0.74 * 3.141592653589793,
    beam_layout="left_top",
    base_exposure=3.15,
    support_fill=0.05,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
