"""Curated splitter-focused clean-room family."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_splitter_web_spec

FAMILY = "splitters"

_EXPOSURE_BIAS = {
    "top": 0.12,
    "left": 0.10,
    "bottom": 0.10,
    "left_top": 0.06,
    "exchange": 0.04,
    "triad": 0.04,
    "trident": 0.04,
    "dual_side": 0.03,
    "warm_white": 0.03,
}

_FILL_BIAS = {
    "top": 0.01,
    "left": 0.01,
    "bottom": 0.01,
}


def _spec(
    name: str,
    description: str,
    *,
    layout: str,
    beam_layout: str,
    base_exposure: float,
    core_radius: float = 0.07,
    support_fill: float = 0.0,
):
    return make_splitter_web_spec(
        name,
        description,
        layout=layout,
        beam_layout=beam_layout,
        base_exposure=base_exposure + _EXPOSURE_BIAS.get(beam_layout, 0.0),
        core_radius=core_radius,
        support_fill=max(0.0, support_fill + _FILL_BIAS.get(beam_layout, 0.0)),
    )


SCENES = [
    _spec("splitter_hallway", "A long corridor split by a centered warm-white beam.", layout="corridor", beam_layout="warm_white", base_exposure=3.18, core_radius=0.07, support_fill=0.03),
    _spec("splitter_nave", "Three splitter ribs frame a bright axial passage.", layout="triad", beam_layout="triad", base_exposure=3.12, core_radius=0.08, support_fill=0.04),
    _spec("splitter_crosswalk", "A crossing web catches side light from both walls.", layout="exchange", beam_layout="dual_side", base_exposure=3.16, core_radius=0.07, support_fill=0.02),
    _spec("splitter_crownlight", "A crown of splitters keeps a warm beam centered.", layout="compass", beam_layout="left_top", base_exposure=3.08, core_radius=0.06, support_fill=0.05),
    _spec("splitter_braidline", "Two beams braid through a narrow splitter lane.", layout="corridor", beam_layout="exchange", base_exposure=3.14, core_radius=0.06, support_fill=0.02),
    _spec("splitter_lattice", "A compact lattice sends light into a bright core.", layout="compass", beam_layout="warm_white", base_exposure=3.20, core_radius=0.05, support_fill=0.04),
    _spec("splitter_gatehouse", "A gate-like web opens under a white support beam.", layout="trident", beam_layout="triad", base_exposure=3.10, core_radius=0.07, support_fill=0.05),
    _spec("splitter_river", "A soft splitter river runs between warm side beams.", layout="corridor", beam_layout="left", base_exposure=3.22, core_radius=0.08, support_fill=0.03),
    _spec("splitter_keel", "A keel-shaped web keeps the center line luminous.", layout="triad", beam_layout="left_top", base_exposure=3.15, core_radius=0.06, support_fill=0.04),
    _spec("splitter_fern", "Three splitters branch like a bright fern.", layout="trident", beam_layout="warm_white", base_exposure=3.17, core_radius=0.05, support_fill=0.02),

    _spec("splitter_pier", "A small pier holds a centered beam against both walls.", layout="exchange", beam_layout="dual_side", base_exposure=3.11, core_radius=0.07, support_fill=0.04),
    _spec("splitter_sash", "A sash-like web crosses the room with a white echo.", layout="compass", beam_layout="exchange", base_exposure=3.19, core_radius=0.06, support_fill=0.03),
    _spec("splitter_bastion", "A heavy splitter bastion anchors a warm-white crossing.", layout="trident", beam_layout="trident", base_exposure=3.06, core_radius=0.08, support_fill=0.05),
    _spec("splitter_chancel", "A narrow chancel keeps the beam path clean and bright.", layout="corridor", beam_layout="top", base_exposure=3.24, core_radius=0.06, support_fill=0.02),
    _spec("splitter_causeway", "A bright causeway runs through a centered splitter web.", layout="triad", beam_layout="warm_white", base_exposure=3.20, core_radius=0.07, support_fill=0.03),
    _spec("splitter_dock", "A docked core lets a side beam skim the web.", layout="exchange", beam_layout="left_top", base_exposure=3.13, core_radius=0.05, support_fill=0.02),
    _spec("splitter_ledger", "A ledger-like web keeps the lines measured and clear.", layout="compass", beam_layout="left", base_exposure=3.18, core_radius=0.07, support_fill=0.03),
    _spec("splitter_mill", "A mill-wheel web turns under a warm and white pair.", layout="triad", beam_layout="warm_white", base_exposure=3.09, core_radius=0.06, support_fill=0.04),
    _spec("splitter_orchard", "A branching orchard of splitters stays open at the center.", layout="trident", beam_layout="dual_side", base_exposure=3.14, core_radius=0.05, support_fill=0.02),
    _spec("splitter_promenade", "A promenade of two beams glides through a quiet web.", layout="corridor", beam_layout="exchange", base_exposure=3.21, core_radius=0.07, support_fill=0.03),

    _spec("splitter_quay", "A quay-like corridor keeps both beams in view.", layout="corridor", beam_layout="warm_white", base_exposure=3.17, core_radius=0.08, support_fill=0.02),
    _spec("splitter_rosette", "A rosette of splitters opens around a bright core.", layout="compass", beam_layout="triad", base_exposure=3.07, core_radius=0.06, support_fill=0.05),
    _spec("splitter_span", "A spanning exchange keeps the room visually balanced.", layout="exchange", beam_layout="dual_side", base_exposure=3.16, core_radius=0.07, support_fill=0.03),
    _spec("splitter_trellis", "A trellis web catches a warm beam and a white lift.", layout="triad", beam_layout="left_top", base_exposure=3.12, core_radius=0.06, support_fill=0.04),
    _spec("splitter_underpass", "A low splitter underpass leaves a clean central lane.", layout="corridor", beam_layout="bottom", base_exposure=3.19, core_radius=0.07, support_fill=0.03),
    _spec("splitter_valence", "A valence-like trident keeps the center exposed.", layout="trident", beam_layout="warm_white", base_exposure=3.10, core_radius=0.06, support_fill=0.02),
    _spec("splitter_wicket", "A wicket web frames a narrow beam exchange.", layout="exchange", beam_layout="exchange", base_exposure=3.18, core_radius=0.05, support_fill=0.04),
    _spec("splitter_xbridge", "An X bridge crosses the room with a bright core.", layout="compass", beam_layout="trident", base_exposure=3.14, core_radius=0.07, support_fill=0.02),
    _spec("splitter_yard", "A small yard of splitters leaves room for the beams.", layout="triad", beam_layout="dual_side", base_exposure=3.20, core_radius=0.08, support_fill=0.03),
    _spec("splitter_zigzag", "A zigzag web turns a side beam into a bright trace.", layout="corridor", beam_layout="left_top", base_exposure=3.11, core_radius=0.06, support_fill=0.04),

    _spec("splitter_apron", "An apron of splitters softens the crossing light.", layout="compass", beam_layout="warm_white", base_exposure=3.15, core_radius=0.06, support_fill=0.03),
    _spec("splitter_balcony", "A balcony-like web hangs beneath a bright top beam.", layout="trident", beam_layout="top", base_exposure=3.06, core_radius=0.07, support_fill=0.05),
    _spec("splitter_canal", "A canal of light stays clear between mirrored walls.", layout="corridor", beam_layout="left", base_exposure=3.23, core_radius=0.08, support_fill=0.02),
    _spec("splitter_daisy", "A daisy ring of splitters holds a warm-white center.", layout="compass", beam_layout="warm_white", base_exposure=3.13, core_radius=0.05, support_fill=0.04),
    _spec("splitter_easel", "An easel web presents the core to a side beam.", layout="exchange", beam_layout="left_top", base_exposure=3.19, core_radius=0.06, support_fill=0.03),
    _spec("splitter_fjord", "A fjord-like gap keeps the beam water bright.", layout="corridor", beam_layout="dual_side", base_exposure=3.16, core_radius=0.07, support_fill=0.02),
    _spec("splitter_gantry", "A gantry of splitters frames a clean luminous passage.", layout="triad", beam_layout="triad", base_exposure=3.09, core_radius=0.08, support_fill=0.04),
    _spec("splitter_hinge", "A hinge-like web pivots around a small bright core.", layout="exchange", beam_layout="exchange", base_exposure=3.17, core_radius=0.05, support_fill=0.03),
    _spec("splitter_ion", "A compact ion-web keeps the beam footprint tight.", layout="compass", beam_layout="left", base_exposure=3.21, core_radius=0.06, support_fill=0.02),
    _spec("splitter_junction", "A junction web keeps all routes readable and bright.", layout="trident", beam_layout="warm_white", base_exposure=3.12, core_radius=0.07, support_fill=0.03),

    _spec("splitter_knuckle", "A knuckled splitter chain catches a warm-white pair.", layout="triad", beam_layout="dual_side", base_exposure=3.08, core_radius=0.06, support_fill=0.05),
    _spec("splitter_lagoon", "A lagoon of light opens in the middle of the web.", layout="corridor", beam_layout="exchange", base_exposure=3.22, core_radius=0.08, support_fill=0.02),
    _spec("splitter_mast", "A mast-like splitter stack keeps the scene vertical.", layout="compass", beam_layout="top", base_exposure=3.10, core_radius=0.07, support_fill=0.04),
    _spec("splitter_niche", "A niche web tucks the core between two bright beams.", layout="exchange", beam_layout="warm_white", base_exposure=3.18, core_radius=0.05, support_fill=0.03),
    _spec("splitter_offset", "An offset web keeps the crossing asymmetrical but clear.", layout="trident", beam_layout="left_top", base_exposure=3.14, core_radius=0.06, support_fill=0.02),
    _spec("splitter_pylon", "A pylon web holds the beam line with extra weight.", layout="triad", beam_layout="dual_side", base_exposure=3.07, core_radius=0.08, support_fill=0.04),
    _spec("splitter_quarry", "A quarry gap lets the white support beam shine through.", layout="corridor", beam_layout="warm_white", base_exposure=3.19, core_radius=0.07, support_fill=0.03),
    _spec("splitter_rampart", "A rampart of splitters guards a luminous center.", layout="compass", beam_layout="triad", base_exposure=3.11, core_radius=0.06, support_fill=0.05),
    _spec("splitter_scribe", "A scribe-like web traces a narrow bright corridor.", layout="exchange", beam_layout="left", base_exposure=3.20, core_radius=0.05, support_fill=0.02),
    _spec("splitter_tandem", "Two beam families run tandem through a splitter web.", layout="triad", beam_layout="warm_white", base_exposure=3.13, core_radius=0.07, support_fill=0.03),

    _spec("splitter_umbra", "An umbra web keeps the center bright despite the shadows.", layout="corridor", beam_layout="bottom", base_exposure=3.23, core_radius=0.06, support_fill=0.03),
    _spec("splitter_vault", "A vault of splitters arches around a clean beam axis.", layout="compass", beam_layout="left_top", base_exposure=3.10, core_radius=0.08, support_fill=0.04),
    _spec("splitter_waypost", "A waypost web points two beams toward the core.", layout="exchange", beam_layout="dual_side", base_exposure=3.16, core_radius=0.06, support_fill=0.02),
    _spec("splitter_yoke", "A yoke-like trident keeps the beam line centered.", layout="trident", beam_layout="warm_white", base_exposure=3.09, core_radius=0.07, support_fill=0.05),
    _spec("splitter_zenith", "A zenith web is lit by a top beam and a warm echo.", layout="compass", beam_layout="top", base_exposure=3.18, core_radius=0.05, support_fill=0.03),
    _spec("splitter_arcade", "An arcade of splitter ribs carries a bright crossing.", layout="triad", beam_layout="triad", base_exposure=3.12, core_radius=0.06, support_fill=0.04),
    _spec("splitter_blind", "A blind window keeps the beam path crisp and narrow.", layout="corridor", beam_layout="left_top", base_exposure=3.21, core_radius=0.07, support_fill=0.02),
    _spec("splitter_chain", "A chained web keeps warm and white beams braided.", layout="exchange", beam_layout="exchange", base_exposure=3.14, core_radius=0.05, support_fill=0.03),
    _spec("splitter_dome", "A dome of splitters opens over a bright central lens.", layout="compass", beam_layout="warm_white", base_exposure=3.08, core_radius=0.08, support_fill=0.04),
    _spec("splitter_ember", "A small ember core glows between a side beam pair.", layout="trident", beam_layout="dual_side", base_exposure=3.17, core_radius=0.05, support_fill=0.02),

    _spec("splitter_fairway", "A fairway web keeps the beam travel straight and clear.", layout="corridor", beam_layout="warm_white", base_exposure=3.20, core_radius=0.07, support_fill=0.03),
    _spec("splitter_grille", "A grille web makes the crossing geometry easy to read.", layout="triad", beam_layout="left", base_exposure=3.15, core_radius=0.06, support_fill=0.04),
    _spec("splitter_harbor", "A harbor of splitters shelters a bright central beam.", layout="exchange", beam_layout="dual_side", base_exposure=3.11, core_radius=0.08, support_fill=0.02),
    _spec("splitter_inlet", "An inlet web opens a clean channel for warm light.", layout="corridor", beam_layout="left_top", base_exposure=3.19, core_radius=0.05, support_fill=0.03),
    _spec("splitter_javelin", "A javelin-like trident sends the beam through a slit.", layout="trident", beam_layout="top", base_exposure=3.07, core_radius=0.06, support_fill=0.05),
    _spec("splitter_keystone", "A keystone web stabilizes the bright center mass.", layout="compass", beam_layout="warm_white", base_exposure=3.13, core_radius=0.07, support_fill=0.03),
    _spec("splitter_laneway", "A laneway keeps both side beams visible and controlled.", layout="corridor", beam_layout="exchange", base_exposure=3.22, core_radius=0.06, support_fill=0.02),
    _spec("splitter_mosaic", "A mosaic of splitters keeps the core crisp and luminous.", layout="triad", beam_layout="triad", base_exposure=3.09, core_radius=0.05, support_fill=0.04),
    _spec("splitter_narrowway", "A narrow way stays bright even as the web turns.", layout="corridor", beam_layout="bottom", base_exposure=3.18, core_radius=0.07, support_fill=0.03),
    _spec("splitter_overpass", "An overpass web leaves a clean underbeam lane.", layout="exchange", beam_layout="left_top", base_exposure=3.14, core_radius=0.08, support_fill=0.02),

]
