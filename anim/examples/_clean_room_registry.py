"""Registry for clean-room example animations."""

from anim.examples.clean_room_aperture_waltz import SPEC as APERTURE_WALTZ
from anim.examples.clean_room_arc_resonator import SPEC as ARC_RESONATOR
from anim.examples.clean_room_arc_resonator_dual_beam import SPEC as ARC_RESONATOR_DUAL_BEAM
from anim.examples.clean_room_breathing_lenses import SPEC as BREATHING_LENSES
from anim.examples.clean_room_caustic_ladder import SPEC as CAUSTIC_LADDER
from anim.examples.clean_room_corner_crossfire import SPEC as CORNER_CROSSFIRE
from anim.examples.clean_room_mirror_fan import SPEC as MIRROR_FAN
from anim.examples.clean_room_mirror_shutters import SPEC as MIRROR_SHUTTERS
from anim.examples.clean_room_orbiting_triplet import SPEC as ORBITING_TRIPLET
from anim.examples.clean_room_prism_crown import SPEC as PRISM_CROWN
from anim.examples.clean_room_splitter_braid import SPEC as SPLITTER_BRAID
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
]

SCENE_MAP = {spec.name: spec for spec in SCENES}
