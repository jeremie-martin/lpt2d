"""Curated prism-focused clean-room scenes."""

from __future__ import annotations

from anim.examples._clean_room_factories import make_prism_field_spec

FAMILY = "prisms"

_EXPOSURE_BIAS = {
    "left": 0.10,
    "exchange": 0.05,
    "left_top": 0.03,
    "dual_side": 0.02,
    "warm_white": 0.02,
    "triad": 0.01,
}

_FILL_BIAS = {
    "left": 0.01,
    "exchange": 0.01,
}


def _scene(
    name: str,
    description: str,
    *,
    layout: str,
    count: int,
    prism_radius: float,
    beam_layout: str,
    base_exposure: float,
    support_fill: float = 0.0,
):
    return make_prism_field_spec(
        name,
        description,
        layout=layout,
        count=count,
        prism_radius=prism_radius,
        beam_layout=beam_layout,
        base_exposure=base_exposure + _EXPOSURE_BIAS.get(beam_layout, 0.0),
        support_fill=max(0.0, support_fill + _FILL_BIAS.get(beam_layout, 0.0)),
    )


SCENES = [
    _scene("prism_ledger", "Three prisms line up under a warm-white side wash.", layout="bridge", count=3, prism_radius=0.16, beam_layout="warm_white", base_exposure=3.26, support_fill=0.03),
    _scene("prism_veil", "A soft prism veil catches a dual beam from both sides.", layout="ring", count=4, prism_radius=0.15, beam_layout="dual_side", base_exposure=3.22, support_fill=0.02),
    _scene("prism_cascade", "A staggered prism cascade drifts through a narrow beam lane.", layout="sweep", count=5, prism_radius=0.14, beam_layout="left_top", base_exposure=3.28, support_fill=0.04),
    _scene("prism_helix", "Two prism lanes trade light in a gentle helix.", layout="bridge", count=4, prism_radius=0.13, beam_layout="exchange", base_exposure=3.25, support_fill=0.02),
    _scene("prism_podium", "A compact prism podium stands in a bright two-beam room.", layout="grid", count=4, prism_radius=0.17, beam_layout="warm_white", base_exposure=3.30, support_fill=0.05),
    _scene("prism_orbit", "Prisms orbit a calm core with balanced warm and white light.", layout="ring", count=5, prism_radius=0.15, beam_layout="dual_side", base_exposure=3.24, support_fill=0.02),
    _scene("prism_current", "A prism current runs diagonally through the room.", layout="sweep", count=4, prism_radius=0.14, beam_layout="left", base_exposure=3.18, support_fill=0.03),
    _scene("prism_barrier", "A bright prism barrier holds the center of the room.", layout="bridge", count=6, prism_radius=0.12, beam_layout="triad", base_exposure=3.34, support_fill=0.04),
    _scene("prism_lattice", "A small prism lattice reflects a warm-white triad.", layout="grid", count=6, prism_radius=0.11, beam_layout="triad", base_exposure=3.20, support_fill=0.03),
    _scene("prism_bay", "A prism bay opens toward a soft supporting top beam.", layout="constellation", count=5, prism_radius=0.14, beam_layout="left_top", base_exposure=3.27, support_fill=0.05),
    _scene("prism_lilt", "Light steps across a loose prism ring with a white echo.", layout="ring", count=3, prism_radius=0.18, beam_layout="warm_white", base_exposure=3.31, support_fill=0.02),
    _scene("prism_rampart", "A prism rampart turns slowly under a bright side pair.", layout="bridge", count=5, prism_radius=0.13, beam_layout="dual_side", base_exposure=3.29, support_fill=0.04),
    _scene("prism_galley", "A narrow prism galley keeps the light path clean.", layout="sweep", count=4, prism_radius=0.13, beam_layout="left_top", base_exposure=3.23, support_fill=0.03),
    _scene("prism_crest", "A crest of prisms rises into a white-topped wash.", layout="constellation", count=4, prism_radius=0.15, beam_layout="triad", base_exposure=3.36, support_fill=0.05),
    _scene("prism_harbor", "Prisms settle in a quiet harbor of warm and white beams.", layout="ring", count=6, prism_radius=0.12, beam_layout="warm_white", base_exposure=3.18, support_fill=0.02),
    _scene("prism_motif", "A minimal prism motif stays centered and readable.", layout="grid", count=3, prism_radius=0.18, beam_layout="exchange", base_exposure=3.21, support_fill=0.01),
    _scene("prism_parlor", "A small prism parlor pairs a side beam with a top wash.", layout="bridge", count=4, prism_radius=0.14, beam_layout="left_top", base_exposure=3.25, support_fill=0.04),
    _scene("prism_fan", "Prisms fan outward from a bright dual-source core.", layout="constellation", count=5, prism_radius=0.13, beam_layout="dual_side", base_exposure=3.28, support_fill=0.03),
    _scene("prism_plinth", "A centered prism plinth keeps the geometry clear.", layout="grid", count=4, prism_radius=0.16, beam_layout="warm_white", base_exposure=3.33, support_fill=0.04),
    _scene("prism_gauge", "A prism gauge reads cleanly beneath a warm-white sweep.", layout="sweep", count=5, prism_radius=0.12, beam_layout="left_top", base_exposure=3.27, support_fill=0.04),
    _scene("prism_ribbon", "A prism ribbon turns through a bright exchange beam.", layout="bridge", count=6, prism_radius=0.11, beam_layout="exchange", base_exposure=3.24, support_fill=0.02),
    _scene("prism_clock", "A prism clock keeps a steady bright rhythm.", layout="ring", count=4, prism_radius=0.15, beam_layout="dual_side", base_exposure=3.26, support_fill=0.02),
    _scene("prism_field", "A clean prism field stays open to the walls.", layout="grid", count=6, prism_radius=0.11, beam_layout="triad", base_exposure=3.19, support_fill=0.03),
    _scene("prism_shelf", "A prism shelf leans into a warm-and-white crossfade.", layout="constellation", count=5, prism_radius=0.13, beam_layout="warm_white", base_exposure=3.29, support_fill=0.03),
    _scene("prism_foil", "A thin prism foil catches a bright side beam.", layout="sweep", count=3, prism_radius=0.17, beam_layout="left", base_exposure=3.17, support_fill=0.02),
    _scene("prism_spire", "A prism spire lifts into a restrained top support beam.", layout="bridge", count=4, prism_radius=0.15, beam_layout="left_top", base_exposure=3.34, support_fill=0.04),
    _scene("prism_arcade", "A prism arcade reads like a bright mirrored passage.", layout="ring", count=6, prism_radius=0.12, beam_layout="dual_side", base_exposure=3.23, support_fill=0.02),
    _scene("prism_lumen", "A luminous prism set favors clarity over density.", layout="grid", count=4, prism_radius=0.16, beam_layout="warm_white", base_exposure=3.35, support_fill=0.05),
    _scene("prism_celeste", "A soft prism constellation opens under a white cap.", layout="constellation", count=6, prism_radius=0.12, beam_layout="triad", base_exposure=3.30, support_fill=0.04),
    _scene("prism_corridor", "A prism corridor keeps the beam path long and legible.", layout="bridge", count=5, prism_radius=0.12, beam_layout="exchange", base_exposure=3.22, support_fill=0.02),
    _scene("prism_trellis", "A prism trellis catches a warm-white side pair.", layout="grid", count=6, prism_radius=0.10, beam_layout="dual_side", base_exposure=3.20, support_fill=0.03),
    _scene("prism_drift", "A drifting prism row stays bright and restrained.", layout="sweep", count=4, prism_radius=0.14, beam_layout="left_top", base_exposure=3.26, support_fill=0.04),
    _scene("prism_gleam", "A gentle gleam runs across a minimal prism ring.", layout="ring", count=3, prism_radius=0.18, beam_layout="warm_white", base_exposure=3.28, support_fill=0.01),
    _scene("prism_span", "A prism span bridges the room with balanced light.", layout="bridge", count=5, prism_radius=0.13, beam_layout="dual_side", base_exposure=3.27, support_fill=0.03),
    _scene("prism_window", "A prism window keeps the silhouette open and calm.", layout="constellation", count=4, prism_radius=0.15, beam_layout="left", base_exposure=3.19, support_fill=0.02),
    _scene("prism_lantern", "A lantern-like prism cluster glows from a top wash.", layout="grid", count=5, prism_radius=0.12, beam_layout="left_top", base_exposure=3.32, support_fill=0.04),
    _scene("prism_bastion", "A compact prism bastion resists clutter.", layout="bridge", count=4, prism_radius=0.16, beam_layout="warm_white", base_exposure=3.35, support_fill=0.05),
    _scene("prism_sonar", "A prism sonar sweep traces the mirrored room.", layout="sweep", count=6, prism_radius=0.11, beam_layout="exchange", base_exposure=3.21, support_fill=0.03),
    _scene("prism_alloy", "A prism alloy blends a warm lead beam with a white echo.", layout="constellation", count=5, prism_radius=0.13, beam_layout="warm_white", base_exposure=3.29, support_fill=0.03),
    _scene("prism_dome", "A low prism dome keeps the center bright and simple.", layout="ring", count=4, prism_radius=0.16, beam_layout="triad", base_exposure=3.31, support_fill=0.04),
    _scene("prism_ladder", "A diagonal prism ladder holds a clean beam slope.", layout="sweep", count=5, prism_radius=0.12, beam_layout="left_top", base_exposure=3.24, support_fill=0.03),
    _scene("prism_courtyard", "A prism courtyard stays open under side lighting.", layout="grid", count=6, prism_radius=0.10, beam_layout="dual_side", base_exposure=3.18, support_fill=0.03),
    _scene("prism_march", "A measured prism march keeps the motion disciplined.", layout="bridge", count=4, prism_radius=0.14, beam_layout="exchange", base_exposure=3.25, support_fill=0.02),
    _scene("prism_niche", "A prism niche uses a small top beam for readability.", layout="constellation", count=3, prism_radius=0.17, beam_layout="left_top", base_exposure=3.33, support_fill=0.04),
    _scene("prism_knot", "A prism knot stays readable by holding a compact layout.", layout="constellation", count=5, prism_radius=0.12, beam_layout="warm_white", base_exposure=3.27, support_fill=0.03),
    _scene("prism_glint", "A bright prism glint favors the white source slightly.", layout="ring", count=4, prism_radius=0.15, beam_layout="dual_side", base_exposure=3.22, support_fill=0.02),
    _scene("prism_rill", "A prism rill runs in a narrow and luminous channel.", layout="sweep", count=4, prism_radius=0.13, beam_layout="left_top", base_exposure=3.28, support_fill=0.04),
    _scene("prism_beacon", "A prism beacon lands a strong warm-white pair.", layout="bridge", count=6, prism_radius=0.11, beam_layout="warm_white", base_exposure=3.34, support_fill=0.05),
    _scene("prism_spark", "A prism spark keeps the geometry small and bright.", layout="constellation", count=4, prism_radius=0.14, beam_layout="exchange", base_exposure=3.20, support_fill=0.02),
    _scene("prism_halo", "A halo of prisms opens around a centered beam cross.", layout="ring", count=6, prism_radius=0.11, beam_layout="triad", base_exposure=3.29, support_fill=0.03),
    _scene("prism_pier", "A prism pier reaches into a soft top-lit room.", layout="bridge", count=3, prism_radius=0.17, beam_layout="left_top", base_exposure=3.35, support_fill=0.04),
    _scene("prism_loom", "A prism loom weaves a clear warm and white exchange.", layout="grid", count=5, prism_radius=0.12, beam_layout="exchange", base_exposure=3.23, support_fill=0.03),
    _scene("prism_tangent", "A tangent prism group keeps the motion side-on and crisp.", layout="sweep", count=6, prism_radius=0.10, beam_layout="dual_side", base_exposure=3.19, support_fill=0.02),
    _scene("prism_solid", "A solid prism pack stays centered under clean light.", layout="grid", count=4, prism_radius=0.17, beam_layout="warm_white", base_exposure=3.31, support_fill=0.05),
    _scene("prism_flux", "A bright prism flux uses a gentle top support wash.", layout="constellation", count=5, prism_radius=0.13, beam_layout="left_top", base_exposure=3.28, support_fill=0.04),
    _scene("prism_hush", "A quiet prism hush favors form over clutter.", layout="ring", count=3, prism_radius=0.18, beam_layout="left", base_exposure=3.16, support_fill=0.01),
    _scene("prism_axis", "A prism axis keeps the beam path honest.", layout="bridge", count=4, prism_radius=0.15, beam_layout="dual_side", base_exposure=3.26, support_fill=0.02),
    _scene("prism_driftline", "A prism driftline tilts under a warm-white pair.", layout="sweep", count=5, prism_radius=0.12, beam_layout="exchange", base_exposure=3.24, support_fill=0.03),
    _scene("prism_rosette", "A prism rosette gives the room a soft bright center.", layout="ring", count=5, prism_radius=0.13, beam_layout="warm_white", base_exposure=3.30, support_fill=0.03),
    _scene("prism_passage", "A prism passage uses the room width without crowding it.", layout="bridge", count=6, prism_radius=0.11, beam_layout="left_top", base_exposure=3.32, support_fill=0.04),
    _scene("prism_compass", "A prism compass points the light cleanly through the room.", layout="constellation", count=4, prism_radius=0.15, beam_layout="triad", base_exposure=3.27, support_fill=0.03),
    _scene("prism_margin", "A prism margin leaves plenty of room around the subject.", layout="grid", count=3, prism_radius=0.18, beam_layout="dual_side", base_exposure=3.21, support_fill=0.02),
    _scene("prism_slate", "A prism slate keeps the shapes broad and readable.", layout="bridge", count=5, prism_radius=0.13, beam_layout="warm_white", base_exposure=3.34, support_fill=0.05),
    _scene("prism_fence", "A prism fence screens a clean white support beam.", layout="sweep", count=4, prism_radius=0.14, beam_layout="left_top", base_exposure=3.25, support_fill=0.04),
    _scene("prism_ion", "A prism ion composition stays compact and luminous.", layout="constellation", count=6, prism_radius=0.11, beam_layout="exchange", base_exposure=3.22, support_fill=0.03),
    _scene("prism_channel", "A prism channel guides the beam without excess motion.", layout="sweep", count=5, prism_radius=0.12, beam_layout="left", base_exposure=3.18, support_fill=0.02),
    _scene("prism_keystone", "A prism keystone settles under a balanced dual beam.", layout="grid", count=4, prism_radius=0.16, beam_layout="dual_side", base_exposure=3.33, support_fill=0.04),
    _scene("prism_ledgerline", "A prism ledgerline keeps the horizon clear.", layout="bridge", count=4, prism_radius=0.14, beam_layout="exchange", base_exposure=3.23, support_fill=0.03),
    _scene("prism_breath", "A prism breath scene stays light, open, and bright.", layout="ring", count=3, prism_radius=0.18, beam_layout="warm_white", base_exposure=3.20, support_fill=0.01),
    _scene("prism_mosaic", "A small prism mosaic reads well from the walls inward.", layout="grid", count=6, prism_radius=0.10, beam_layout="triad", base_exposure=3.28, support_fill=0.03),
]
