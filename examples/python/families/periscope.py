"""Periscope — two metallic 45-degree mirrors elbow a beam around a dispersing prism.

A projector shines into a chamber where two thick metallic mirrors sit at 45
degrees, elbowing the beam around a corner. A glass prism sits mid-path
between them; when the beam crosses it, the path splits into spectral rays
that continue on to bounce off the second mirror, then exit toward the far
wall. Reads like a periscope diagram with rainbow inside.

Branches (explicit per-branch params):

- solo_white      : one full-spectrum projector
- solo_warm       : one orange projector
- duet_contrast   : warm + white entering the periscope together

Elbow composition:

- elbow_right : first mirror upper-left, exit to the right
- elbow_left  : medieval inversion — first mirror upper-right, exit to the left
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from anim import (
    Camera2D,
    Frame,
    FrameContext,
    LightSpectrum,
    Look,
    Material,
    ProjectorLight,
    Scene,
    Shot,
    Timeline,
    glass,
    mirror_box,
    prism,
    render,
    thick_segment,
)
from anim.renderer import RenderSession, _resolve_frame_shot

WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
CAMERA = Camera2D(center=[0, 0], width=3.2)
DURATION = 6.0
CHAMBER_HW, CHAMBER_HH = 1.6, 0.9

WALL_ID = "wall"

PRISM_GLASSES = [
    glass(1.52, cauchy_b=28_000, color=(0.97, 0.97, 0.97), fill=0.10),
    glass(1.60, cauchy_b=35_000, color=(0.95, 0.96, 1.0), fill=0.10),
]
PRISM_IDS = ["prism_a", "prism_b"]

MATERIALS = {
    WALL_ID: WALL,
    PRISM_IDS[0]: PRISM_GLASSES[0],
    PRISM_IDS[1]: PRISM_GLASSES[1],
}

ELBOW_LAYOUTS = {"elbow_right": +1, "elbow_left": -1}


@dataclass
class LightDef:
    offset_along_entry: float   # how far outside the chamber, along the beam entry axis
    offset_perp: float
    angle_drift_rate: float
    base_angle_offset: float
    spread: float
    source: str
    source_radius: float
    intensity: float
    color: str


@dataclass
class AnimParams:
    elbow_composition: str
    mirror_a_x: float            # horizontal position of first mirror
    mirror_a_y: float
    mirror_b_x: float
    mirror_b_y: float
    mirror_length: float
    mirror_thickness: float
    prism_x: float
    prism_y: float
    prism_size: float
    prism_rotation_speed: float
    prism_glass_idx: int
    lights: list[LightDef] = field(default_factory=list)
    branch: str = "solo_white"
    look_exposure: float = -4.55


def _elbow_sign(p) -> int:
    return ELBOW_LAYOUTS[p.elbow_composition]


def _mirror_shapes(p):
    """Two thick segments angled at 45 degrees to elbow the beam."""
    sign = _elbow_sign(p)
    # For elbow_right (sign=+1), first mirror is upper-left (receives a leftward-going horizontal beam
    # and reflects it downward); second mirror is lower-right (reflects downward beam to rightward exit).
    # Both segments tilted at 45° — their normals bisect the 90° turn.
    # Segment A: tilted from upper-right-ish to lower-left-ish so that ray coming from the left
    # hits and reflects downward.
    length = p.mirror_length
    # Mirror A: tilted at +45° (for elbow_right); this reflects (+x, 0) to (0, -1).
    ax = p.mirror_a_x
    ay = p.mirror_a_y
    if sign > 0:
        ea = (ax + 0.5 * length * math.sqrt(0.5), ay + 0.5 * length * math.sqrt(0.5))
        eb = (ax - 0.5 * length * math.sqrt(0.5), ay - 0.5 * length * math.sqrt(0.5))
    else:
        ea = (ax - 0.5 * length * math.sqrt(0.5), ay + 0.5 * length * math.sqrt(0.5))
        eb = (ax + 0.5 * length * math.sqrt(0.5), ay - 0.5 * length * math.sqrt(0.5))
    mir_a = thick_segment(ea, eb, p.mirror_thickness, WALL_ID, id_prefix="mirror_a")

    bx = p.mirror_b_x
    by = p.mirror_b_y
    if sign > 0:
        # Mirror B: tilted at -45°, reflects (0, -1) to (+1, 0).
        ea2 = (bx - 0.5 * length * math.sqrt(0.5), by + 0.5 * length * math.sqrt(0.5))
        eb2 = (bx + 0.5 * length * math.sqrt(0.5), by - 0.5 * length * math.sqrt(0.5))
    else:
        ea2 = (bx + 0.5 * length * math.sqrt(0.5), by + 0.5 * length * math.sqrt(0.5))
        eb2 = (bx - 0.5 * length * math.sqrt(0.5), by - 0.5 * length * math.sqrt(0.5))
    mir_b = thick_segment(ea2, eb2, p.mirror_thickness, WALL_ID, id_prefix="mirror_b")

    return [mir_a, mir_b]


def _spectrum_for(color):
    if color == "warm":
        return LightSpectrum.range(wavelength_min=580, wavelength_max=650)
    if color == "white":
        return LightSpectrum.range(wavelength_min=380, wavelength_max=780)
    raise ValueError(color)


def _projectors(p, progress):
    sign = _elbow_sign(p)
    # Projector enters from the far side of mirror A, aimed horizontally at it.
    out = []
    for i, L in enumerate(p.lights):
        # Entry point: on the side wall opposite mirror A's horizontal side.
        # elbow_right: mirror_a is upper-left, projector is on LEFT wall, beam aimed right at mirror_a.
        if sign > 0:
            lx = -CHAMBER_HW + 0.06 + L.offset_along_entry
            ly = p.mirror_a_y + L.offset_perp
            base_dir = (1.0, 0.0)
        else:
            lx = CHAMBER_HW - 0.06 - L.offset_along_entry
            ly = p.mirror_a_y + L.offset_perp
            base_dir = (-1.0, 0.0)
        base_angle = math.atan2(base_dir[1], base_dir[0])
        drift = L.angle_drift_rate * (progress - 0.5)
        a = base_angle + L.base_angle_offset + drift
        out.append(ProjectorLight(
            id=f"beam_{i}",
            position=[lx, ly],
            direction=[math.cos(a), math.sin(a)],
            source_radius=L.source_radius,
            spread=L.spread,
            source=L.source,
            intensity=L.intensity,
            spectrum=_spectrum_for(L.color),
        ))
    return out


def build_animate(p):
    def animate(ctx):
        progress = ctx.progress if ctx.total_frames > 1 else 0.5
        t = ctx.time
        prism_shape = prism(
            center=(p.prism_x, p.prism_y),
            size=p.prism_size,
            material_id=PRISM_IDS[p.prism_glass_idx % len(PRISM_IDS)],
            rotation=p.prism_rotation_speed * t / DURATION,
            id_prefix="prism",
        )
        scene = Scene(
            materials=MATERIALS,
            shapes=[
                *mirror_box(CHAMBER_HW, CHAMBER_HH, WALL_ID, id_prefix="chamber"),
                *_mirror_shapes(p),
                prism_shape,
            ],
            lights=_projectors(p, progress),
        )
        warm_frac = sum(1 for L in p.lights if L.color == "warm") / max(1, len(p.lights))
        look = Look(exposure=p.look_exposure, gamma=2.0, tonemap="reinhardx",
                    white_point=0.5, normalize="rays", temperature=0.25 * warm_frac)
        return Frame(scene=scene, look=look)

    return animate


def _sample_light(rng, *, color, intensity):
    return LightDef(
        offset_along_entry=rng.uniform(0.0, 0.15),
        offset_perp=rng.uniform(-0.06, 0.06),
        angle_drift_rate=rng.uniform(-0.08, 0.08),
        base_angle_offset=rng.uniform(-0.04, 0.04),
        spread=rng.uniform(0.04, 0.08),
        source=rng.choice(["ball", "line"]),
        source_radius=rng.uniform(0.008, 0.018),
        intensity=intensity,
        color=color,
    )


def _sample_solo_white(rng): return [_sample_light(rng, color="white", intensity=rng.uniform(0.55, 0.82))]
def _sample_solo_warm(rng): return [_sample_light(rng, color="warm", intensity=rng.uniform(0.22, 0.36))]


def _sample_duet_contrast(rng):
    w = _sample_light(rng, color="warm", intensity=rng.uniform(0.15, 0.22))
    wh = _sample_light(rng, color="white", intensity=rng.uniform(0.40, 0.58))
    w.offset_perp = rng.uniform(-0.06, -0.01)
    wh.offset_perp = rng.uniform(0.01, 0.06)
    return [w, wh]


_BRANCH_SAMPLERS = {"solo_white": _sample_solo_white, "solo_warm": _sample_solo_warm, "duet_contrast": _sample_duet_contrast}
_BRANCH_WEIGHTS = {"solo_white": 1.4, "solo_warm": 1.0, "duet_contrast": 1.3}


def _pick_branch(rng):
    names = list(_BRANCH_WEIGHTS.keys())
    return rng.choices(names, weights=[_BRANCH_WEIGHTS[n] for n in names], k=1)[0]


def random_params(rng):
    branch = _pick_branch(rng)
    elbow = rng.choice(list(ELBOW_LAYOUTS.keys()))
    sign = ELBOW_LAYOUTS[elbow]
    # Mirror A horizontal position: far into the upper-left (or upper-right) region of the chamber.
    mirror_a_x = -sign * rng.uniform(0.55, 0.85)
    mirror_a_y = rng.uniform(0.15, 0.45)
    mirror_b_x = sign * rng.uniform(0.55, 0.85)
    mirror_b_y = rng.uniform(-0.45, -0.15)
    mirror_length = rng.uniform(0.30, 0.45)
    mirror_thickness = rng.uniform(0.03, 0.06)
    # Prism mid-path between the two mirrors (on the vertical leg).
    prism_x = (mirror_a_x + mirror_b_x) / 2 + rng.uniform(-0.05, 0.05)
    prism_y = rng.uniform(-0.10, 0.10)
    prism_size = rng.uniform(0.13, 0.20)
    prism_rotation_speed = rng.uniform(-math.pi, math.pi) * 0.6
    prism_glass_idx = rng.randint(0, 1)
    lights = _BRANCH_SAMPLERS[branch](rng)
    base_exp = -4.5 if len(lights) == 1 else -4.72
    look_exposure = base_exp + rng.uniform(-0.20, 0.15)
    return AnimParams(
        elbow_composition=elbow,
        mirror_a_x=mirror_a_x, mirror_a_y=mirror_a_y,
        mirror_b_x=mirror_b_x, mirror_b_y=mirror_b_y,
        mirror_length=mirror_length, mirror_thickness=mirror_thickness,
        prism_x=prism_x, prism_y=prism_y, prism_size=prism_size,
        prism_rotation_speed=prism_rotation_speed, prism_glass_idx=prism_glass_idx,
        lights=lights, branch=branch, look_exposure=look_exposure,
    )


PROBE_FPS = 4
PROBE_W, PROBE_H = 640, 360
GATE_MEAN_LUMA = (0.08, 0.42)
GATE_CLIPPED_MAX = 0.09
GATE_NEAR_BLACK_MAX = 0.80
GATE_IDR_MIN = 40.0 / 255.0
GATE_COLORFULNESS_MIN_WARM_DOMINANT = 0.08
GATE_COLORFULNESS_MIN_OTHER = 0.010
GATE_MIN_PASSING_FRAMES_FRAC = 0.25


def _is_warm_dominant(p):
    warm = sum(1 for L in p.lights if L.color == "warm")
    return warm / max(1, len(p.lights)) >= 0.5


def make_probe_shot():
    shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=300_000, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(exposure=-4.6, gamma=2.0, tonemap="reinhardx",
                                          white_point=0.5, normalize="rays", temperature=0.0)
    return shot


def check_beauty(p):
    animate = build_animate(p)
    shot = make_probe_shot()
    timeline = Timeline(DURATION, fps=PROBE_FPS)
    session = RenderSession(PROBE_W, PROBE_H, False)
    color_min = GATE_COLORFULNESS_MIN_WARM_DOMINANT if _is_warm_dominant(p) else GATE_COLORFULNESS_MIN_OTHER
    n_frames = timeline.total_frames
    passes = 0
    agg = {"mean_luma": [], "clipped": [], "near_black": [], "idr": [], "color": []}
    for fi in range(n_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        rr = session.render_shot(cpp_shot, fi, True)
        st = rr.analysis.image
        for k, v in [("mean_luma", st.mean_luma), ("clipped", st.clipped_channel_fraction),
                     ("near_black", st.near_black_fraction), ("idr", st.interdecile_luma_range),
                     ("color", st.colorfulness)]:
            agg[k].append(v)
        if (GATE_MEAN_LUMA[0] <= st.mean_luma <= GATE_MEAN_LUMA[1]
                and st.clipped_channel_fraction <= GATE_CLIPPED_MAX
                and st.near_black_fraction <= GATE_NEAR_BLACK_MAX
                and st.interdecile_luma_range >= GATE_IDR_MIN
                and st.colorfulness >= color_min):
            passes += 1
    def avg(k): return sum(agg[k]) / max(1, len(agg[k]))
    s = {k: avg(k) for k in agg}
    s["passing_frames"] = passes; s["total_frames"] = n_frames
    return passes >= int(GATE_MIN_PASSING_FRAMES_FRAC * n_frames), s


def make_preview_shot(width, height, rays):
    shot = Shot.preset("preview", width=width, height=height, rays=rays, depth=10)
    shot.camera = CAMERA
    shot.look = shot.look.with_overrides(exposure=-4.6, gamma=2.0, tonemap="reinhardx",
                                          white_point=0.5, normalize="rays", temperature=0.0)
    return shot


def _params_to_dict(p): return asdict(p)


def render_and_save(p, out_dir, *, width, height, rays, fps):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "params.json").write_text(json.dumps(_params_to_dict(p), indent=2))
    animate = build_animate(p)
    settings = make_preview_shot(width, height, rays)
    timeline = Timeline(DURATION, fps=fps)
    video_path = out_dir / "video.mp4"
    render(animate, timeline, str(video_path), settings=settings, crf=18)
    print(f"  video  -> {video_path}")


MAX_ATTEMPTS = 250


def main():
    seed = int(time.time()) if "--seed" not in sys.argv else int(sys.argv[sys.argv.index("--seed") + 1])
    target_count = int(sys.argv[sys.argv.index("-n") + 1]) if "-n" in sys.argv else 3
    hq = "--hq" in sys.argv
    width, height, rays = (1280, 720, 3_000_000) if hq else (640, 360, 800_000)
    fps = 30
    rng = random.Random(seed)
    print(f"seed={seed} target={target_count} hq={hq}")
    base_dir = Path("renders/families/periscope")
    found = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        p = random_params(rng)
        print(f"[{attempt}] branch={p.branch} {p.elbow_composition} exp={p.look_exposure:.2f} "
              f"— checking...", flush=True)
        ok, s = check_beauty(p)
        print(f"  passes={s['passing_frames']}/{s['total_frames']} "
              f"mean_luma={s['mean_luma']:.3f} color={s['color']:.3f} "
              f"idr={s['idr']:.3f} near_black={s['near_black']:.2f} clipped={s['clipped']:.3f}",
              flush=True)
        if not ok:
            continue
        found += 1
        tag = f"{found:03d}_{p.branch}_{p.elbow_composition.replace('elbow_','')}"
        out_dir = base_dir / tag
        print(f"  FOUND #{found} — rendering...")
        render_and_save(p, out_dir, width=width, height=height, rays=rays, fps=fps)
        print("  done.\n")
        if found >= target_count:
            break
    if found == 0:
        print(f"No valid animation found in {MAX_ATTEMPTS} attempts.")


if __name__ == "__main__":
    main()
