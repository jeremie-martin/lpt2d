"""Registry for clean-room example animations."""

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

SCENES = [
    ORBITING_TRIPLET,
    SPLITTER_BRAID,
    BREATHING_LENSES,
    MIRROR_SHUTTERS,
    PRISM_CROWN,
    WAVEGUIDE_RIBBON,
    CORNER_CROSSFIRE,
    CAUSTIC_LADDER,
    APERTURE_WALTZ,
    ARC_RESONATOR,
    ARC_RESONATOR_DUAL_BEAM,
    MIRROR_FAN,
    ARC_BLOOM,
    CRESCENT_DUET,
    RESONATOR_WEAVE,
    ARC_LANTERN,
    ORBITING_CRESCENTS,
    PRISM_BRIDGE,
    PRISM_DRUM,
    PRISM_SWEEP,
    PRISM_CONSTELLATION,
    PRISM_PARADE,
    COUNTER_ROTOR,
    IRIS_GATE,
    LOUVER_FAN,
    MIRROR_COMPASS,
    ROTOR_CASCADE,
    DUAL_RIBBON,
    BRIDGE_RIBBON,
    RIBBON_EXCHANGE,
    SILK_WAVEGUIDE,
    TRI_RIBBON,
    FOCUS_COLUMNS,
    CAUSTIC_STAIR,
    LENS_QUARTET,
    DOUBLET_GRID,
    HALO_LENSES,
    SPLITTER_CORRIDOR,
    SPLITTER_COMPASS,
    TRIDENT_CROSSFIRE,
    BEAM_EXCHANGE,
    SPLITTER_CROWN,
]

SCENE_MAP = {spec.name: spec for spec in SCENES}
