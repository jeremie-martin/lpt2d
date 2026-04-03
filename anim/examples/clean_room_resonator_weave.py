"""Three offset resonator arcs weave under a warm-white triad of beams."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_arc_cluster_spec
from anim.examples._clean_room_shared import run_scene_cli

SPEC = make_arc_cluster_spec(
    "resonator_weave",
    "Three offset resonator arcs weave under a warm-white triad of beams.",
    ring_count=3,
    orbit_rx=0.76,
    orbit_ry=0.2,
    arc_radius=0.38,
    local_start=0.12 * 3.141592653589793,
    local_sweep=0.84 * 3.141592653589793,
    beam_layout="triad",
    base_exposure=3.02,
    support_fill=0.03,
)


if __name__ == "__main__":
    run_scene_cli(SPEC, __doc__ or SPEC.description)
