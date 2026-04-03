"""Registry for clean-room example animations."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from anim.examples._clean_room_shared import SceneSpec, with_family
from anim.examples.clean_room_aperture_waltz import SPEC as APERTURE_WALTZ
from anim.examples.clean_room_arc_bloom import SPEC as ARC_BLOOM
from anim.examples.clean_room_arc_lantern import SPEC as ARC_LANTERN
from anim.examples.clean_room_arc_resonator import SPEC as ARC_RESONATOR
from anim.examples.clean_room_arc_resonator_dual_beam import SPEC as ARC_RESONATOR_DUAL_BEAM
from anim.examples.clean_room_beam_exchange import SPEC as BEAM_EXCHANGE
from anim.examples.clean_room_breathing_lenses import SPEC as BREATHING_LENSES
from anim.examples.clean_room_bridge_ribbon import SPEC as BRIDGE_RIBBON
from anim.examples.clean_room_caustic_ladder import SPEC as CAUSTIC_LADDER
from anim.examples.clean_room_caustic_stair import SPEC as CAUSTIC_STAIR
from anim.examples.clean_room_corner_crossfire import SPEC as CORNER_CROSSFIRE
from anim.examples.clean_room_counter_rotor import SPEC as COUNTER_ROTOR
from anim.examples.clean_room_crescent_duet import SPEC as CRESCENT_DUET
from anim.examples.clean_room_doublet_grid import SPEC as DOUBLET_GRID
from anim.examples.clean_room_dual_ribbon import SPEC as DUAL_RIBBON
from anim.examples.clean_room_focus_columns import SPEC as FOCUS_COLUMNS
from anim.examples.clean_room_halo_lenses import SPEC as HALO_LENSES
from anim.examples.clean_room_iris_gate import SPEC as IRIS_GATE
from anim.examples.clean_room_lens_quartet import SPEC as LENS_QUARTET
from anim.examples.clean_room_louver_fan import SPEC as LOUVER_FAN
from anim.examples.clean_room_mirror_compass import SPEC as MIRROR_COMPASS
from anim.examples.clean_room_mirror_fan import SPEC as MIRROR_FAN
from anim.examples.clean_room_mirror_shutters import SPEC as MIRROR_SHUTTERS
from anim.examples.clean_room_orbiting_crescents import SPEC as ORBITING_CRESCENTS
from anim.examples.clean_room_orbiting_triplet import SPEC as ORBITING_TRIPLET
from anim.examples.clean_room_prism_bridge import SPEC as PRISM_BRIDGE
from anim.examples.clean_room_prism_constellation import SPEC as PRISM_CONSTELLATION
from anim.examples.clean_room_prism_crown import SPEC as PRISM_CROWN
from anim.examples.clean_room_prism_drum import SPEC as PRISM_DRUM
from anim.examples.clean_room_prism_parade import SPEC as PRISM_PARADE
from anim.examples.clean_room_prism_sweep import SPEC as PRISM_SWEEP
from anim.examples.clean_room_resonator_weave import SPEC as RESONATOR_WEAVE
from anim.examples.clean_room_ribbon_exchange import SPEC as RIBBON_EXCHANGE
from anim.examples.clean_room_rotor_cascade import SPEC as ROTOR_CASCADE
from anim.examples.clean_room_silk_waveguide import SPEC as SILK_WAVEGUIDE
from anim.examples.clean_room_splitter_braid import SPEC as SPLITTER_BRAID
from anim.examples.clean_room_splitter_compass import SPEC as SPLITTER_COMPASS
from anim.examples.clean_room_splitter_corridor import SPEC as SPLITTER_CORRIDOR
from anim.examples.clean_room_splitter_crown import SPEC as SPLITTER_CROWN
from anim.examples.clean_room_tri_ribbon import SPEC as TRI_RIBBON
from anim.examples.clean_room_trident_crossfire import SPEC as TRIDENT_CROSSFIRE
from anim.examples.clean_room_waveguide_ribbon import SPEC as WAVEGUIDE_RIBBON


def _load_family_scenes() -> list[SceneSpec]:
    family_dir = Path(__file__).with_name("clean_room_families")
    scenes: list[SceneSpec] = []
    for module_info in sorted(pkgutil.iter_modules([str(family_dir)]), key=lambda item: item.name):
        module = importlib.import_module(f"anim.examples.clean_room_families.{module_info.name}")
        family = getattr(module, "FAMILY", module_info.name.removesuffix("_family"))
        for spec in getattr(module, "SCENES", []):
            scenes.append(spec if spec.family else with_family(spec, family))
    return scenes


LEGACY_SCENES = [
    with_family(ORBITING_TRIPLET, "lenses"),
    with_family(SPLITTER_BRAID, "splitters"),
    with_family(BREATHING_LENSES, "lenses"),
    with_family(MIRROR_SHUTTERS, "mirrors"),
    with_family(PRISM_CROWN, "prisms"),
    with_family(WAVEGUIDE_RIBBON, "ribbons"),
    with_family(CORNER_CROSSFIRE, "crossfires"),
    with_family(CAUSTIC_LADDER, "lenses"),
    with_family(APERTURE_WALTZ, "mirrors"),
    with_family(ARC_RESONATOR, "arcs"),
    with_family(ARC_RESONATOR_DUAL_BEAM, "arcs"),
    with_family(MIRROR_FAN, "mirrors"),
    with_family(ARC_BLOOM, "arcs"),
    with_family(CRESCENT_DUET, "arcs"),
    with_family(RESONATOR_WEAVE, "arcs"),
    with_family(ARC_LANTERN, "arcs"),
    with_family(ORBITING_CRESCENTS, "arcs"),
    with_family(PRISM_BRIDGE, "prisms"),
    with_family(PRISM_DRUM, "prisms"),
    with_family(PRISM_SWEEP, "prisms"),
    with_family(PRISM_CONSTELLATION, "prisms"),
    with_family(PRISM_PARADE, "prisms"),
    with_family(COUNTER_ROTOR, "rotors"),
    with_family(IRIS_GATE, "rotors"),
    with_family(LOUVER_FAN, "rotors"),
    with_family(MIRROR_COMPASS, "rotors"),
    with_family(ROTOR_CASCADE, "rotors"),
    with_family(DUAL_RIBBON, "ribbons"),
    with_family(BRIDGE_RIBBON, "ribbons"),
    with_family(RIBBON_EXCHANGE, "ribbons"),
    with_family(SILK_WAVEGUIDE, "ribbons"),
    with_family(TRI_RIBBON, "ribbons"),
    with_family(FOCUS_COLUMNS, "lenses"),
    with_family(CAUSTIC_STAIR, "lenses"),
    with_family(LENS_QUARTET, "lenses"),
    with_family(DOUBLET_GRID, "lenses"),
    with_family(HALO_LENSES, "lenses"),
    with_family(SPLITTER_CORRIDOR, "splitters"),
    with_family(SPLITTER_COMPASS, "splitters"),
    with_family(TRIDENT_CROSSFIRE, "crossfires"),
    with_family(BEAM_EXCHANGE, "splitters"),
    with_family(SPLITTER_CROWN, "splitters"),
]


SCENES = LEGACY_SCENES + _load_family_scenes()
SCENE_MAP = {spec.name: spec for spec in SCENES}
