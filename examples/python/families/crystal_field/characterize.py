"""Parameter sweep: render strips of metric-annotated variations.

Characterize how each metric reacts as a single parameter is swept from
low to high, holding everything else fixed.  The output is a small set
of horizontal strips (one per parameter, per base scene) with the
metric overlay drawn on each frame.  This is the groundwork for tuning
``check.py`` thresholds from data instead of guesses.

Scope
-----
- 3 hand-crafted base scenes (glass, colored_diffuse, black_diffuse) — deliberately
  not pulled from the catalog matrix so the scenes are stable across
  refactors of the catalog structure.
- 7 swept parameters: exposure, gamma, white_point, contrast,
  amb_intensity, mov_intensity, temperature.  Vignette and chromatic
  aberration are not swept because they're probabilistic (50% off), which
  makes a monotonic sweep awkward; revisit once the main dials are
  understood.
- 7 steps per parameter, evenly spaced across the sampler's range.

Run::

    python -m examples.python.families.crystal_field characterize
    python -m examples.python.families.crystal_field characterize --out /tmp/characterize
"""

from __future__ import annotations

import argparse
import dataclasses
import random
import time
from pathlib import Path

import numpy as np
from PIL import Image

from anim import Camera2D, Shot, Timeline, render_frame, save_image

from .check import _measure_and_verdict
from .overlay import draw_metrics_overlay
from .params import (
    DURATION,
    GridConfig,
    LightConfig,
    LookConfig,
    MaterialConfig,
    Params,
    RotationConfig,
    ShapeConfig,
    range_spectrum,
)
from .sampling import ambient_for_moving_spectrum
from .scene import build

# ---------------------------------------------------------------------------
# Render settings (small enough to iterate, large enough to read the overlay)
# ---------------------------------------------------------------------------

_WIDTH = 960
_HEIGHT = 540
_RAYS = 2_000_000
_CAM = Camera2D(center=[0, 0], width=3.2)

_SHOT = Shot.preset("draft", width=_WIDTH, height=_HEIGHT, rays=_RAYS, depth=12)


# ---------------------------------------------------------------------------
# Base scenes (hand-crafted, deterministic)
# ---------------------------------------------------------------------------


def _base_look() -> LookConfig:
    """Neutral defaults — every swept dim starts from the middle of its range."""
    return LookConfig(
        exposure=-5.5,
        gamma=1.7,
        contrast=1.025,
        white_point=0.5,
        temperature=0.0,
        vignette=0.0,
        vignette_radius=0.7,
        chromatic_aberration=0.0,
    )


def _base_grid() -> GridConfig:
    return GridConfig(
        rows=5,
        cols=7,
        spacing=0.26,
        offset_rows=True,
        hole_fraction=0.0,
    )


def _base_light(wl_min: float = 380.0, wl_max: float = 780.0) -> LightConfig:
    spectrum = range_spectrum(wl_min, wl_max)
    ambient = ambient_for_moving_spectrum(
        random.Random(f"characterize:{wl_min}:{wl_max}"),
        style="corners",
        intensity=0.25,
        moving_spectrum=spectrum,
    )
    return LightConfig(
        n_lights=2,
        path_style="channel",
        n_waypoints=8,
        ambient=ambient,
        speed=0.12,
        moving_intensity=0.8,
        spectrum=spectrum,
    )


def _glass_scene() -> Params:
    grid = _base_grid()
    shape = ShapeConfig(
        kind="circle",
        size=grid.spacing * 0.30,
        n_sides=0,
        corner_radius=0.0,
        rotation=None,
    )
    # Glass at the analysis anchor (dispersion ≈ 20 000, IOR in the good range).
    material = MaterialConfig(
        outcome="glass",
        albedo=0.8,  # irrelevant for glass (transmission=1), set for consistency
        fill=0.09,
        ior=1.52,
        cauchy_b=20_000,
        absorption=1.0,
        color_names=[],
    )
    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=_base_light(),
        look=_base_look(),
        build_seed=12345,
    )


def _colored_diffuse_scene() -> Params:
    grid = _base_grid()
    shape = ShapeConfig(
        kind="polygon",
        size=grid.spacing * 0.32,
        n_sides=5,
        corner_radius=grid.spacing * 0.32 * 0.22,
        rotation=RotationConfig(base_angle=0.15, jitter=0.0),
    )
    material = MaterialConfig(
        outcome="colored_diffuse",
        albedo=0.85,
        fill=0.17,
        color_names=["cyan"],
    )
    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=_base_light(),
        look=_base_look(),
        build_seed=12345,
    )


def _black_diffuse_scene() -> Params:
    grid = _base_grid()
    shape = ShapeConfig(
        kind="polygon",
        size=grid.spacing * 0.32,
        n_sides=6,
        corner_radius=grid.spacing * 0.32 * 0.22,
        rotation=RotationConfig(base_angle=0.15, jitter=0.0),
    )
    # High albedo + fill=0 -> dark silhouettes.  Albedo is never 0.15 (analysis
    # rules that out).  White light (not warm) lets the temperature sweep reach
    # positive values without changing the light-colour axis at the same time.
    material = MaterialConfig(
        outcome="black_diffuse",
        albedo=0.85,
        fill=0.0,
        color_names=[],
    )
    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=_base_light(),
        look=_base_look(),
        build_seed=12345,
    )


BASE_SCENES: dict[str, Params] = {
    "glass": _glass_scene(),
    "colored_diffuse": _colored_diffuse_scene(),
    "black_diffuse": _black_diffuse_scene(),
}


# ---------------------------------------------------------------------------
# Parameter sweeps
# ---------------------------------------------------------------------------


# (name, low, high, steps) — ranges match the sampler's distributions.
SWEEPS: list[tuple[str, float, float, int]] = [
    ("exposure", -6.5, -4.5, 7),
    ("gamma", 1.2, 2.2, 7),
    ("white_point", 0.4, 0.6, 7),
    ("contrast", 1.00, 1.10, 7),
    ("amb_intensity", 0.25, 1.0, 7),
    ("mov_intensity", 0.75, 1.75, 7),
    ("temperature", 0.0, 0.5, 7),
]


def _apply_sweep(base: Params, param: str, value: float) -> Params:
    """Return a new Params with ``param`` set to ``value`` (others unchanged)."""
    if param == "exposure":
        return dataclasses.replace(base, look=dataclasses.replace(base.look, exposure=value))
    if param == "gamma":
        return dataclasses.replace(base, look=dataclasses.replace(base.look, gamma=value))
    if param == "white_point":
        return dataclasses.replace(base, look=dataclasses.replace(base.look, white_point=value))
    if param == "contrast":
        return dataclasses.replace(base, look=dataclasses.replace(base.look, contrast=value))
    if param == "temperature":
        return dataclasses.replace(base, look=dataclasses.replace(base.look, temperature=value))
    if param == "amb_intensity":
        new_amb = dataclasses.replace(base.light.ambient, intensity=value)
        return dataclasses.replace(base, light=dataclasses.replace(base.light, ambient=new_amb))
    if param == "mov_intensity":
        return dataclasses.replace(
            base, light=dataclasses.replace(base.light, moving_intensity=value)
        )
    raise ValueError(f"Unknown sweep param: {param}")


# ---------------------------------------------------------------------------
# Rendering + strip assembly
# ---------------------------------------------------------------------------


def _render_and_overlay(p: Params, out_path: Path) -> None:
    """Render the selected analysis frame, save PNG, overlay metrics."""
    animate = build(p)
    result = _measure_and_verdict(p, animate)
    timeline = Timeline(DURATION, fps=result.analysis_fps)
    rr = render_frame(
        animate,
        timeline,
        frame=result.analysis_frame,
        settings=_SHOT,
        camera=_CAM,
    )
    save_image(str(out_path), rr.pixels, _WIDTH, _HEIGHT)
    draw_metrics_overlay(out_path, result.metrics, font_size=14, padding=6, margin=8)


def _concat_strip(frame_paths: list[Path], out_path: Path) -> None:
    """Concatenate PNGs horizontally into a single strip image."""
    images = [Image.open(p).convert("RGB") for p in frame_paths]
    heights = {im.height for im in images}
    assert len(heights) == 1, f"mixed frame heights: {heights}"
    h = heights.pop()
    total_w = sum(im.width for im in images)
    strip = Image.new("RGB", (total_w, h), color=(0, 0, 0))
    x = 0
    for im in images:
        strip.paste(im, (x, 0))
        x += im.width
    strip.save(out_path)


def _write_index(out_dir: Path, scenes: list[str], params: list[str]) -> None:
    html = [
        """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Crystal Field Characterize</title>
<style>
body { margin:0; background:#111; color:#ccc; font-family:monospace; }
h1 { text-align:center; padding:1em 0 .3em; font-size:1.3em; color:#ddd; }
h2 { text-align:center; font-size:1.1em; margin-top:2em; padding-top:1em; border-top:1px solid #333; color:#ddd; }
h3 { text-align:center; font-size:0.9em; color:#888; margin:.6em 0 .3em; }
.strip { display:block; margin:0 auto; max-width:95vw; }
</style></head><body>
<h1>Crystal Field — Characterization</h1>
<p style="text-align:center;font-size:0.85em;color:#777">
Each row sweeps one parameter (low → high) over a fixed base scene.<br>
Every frame is annotated with the metrics <code>check.py</code> would see.</p>
"""
    ]
    for scene in scenes:
        html.append(f"<h2>{scene}</h2>")
        for param in params:
            html.append(f"<h3>{param}</h3>")
            html.append(f'<img class="strip" src="{scene}/{param}.png">')
    html.append("</body></html>")
    (out_dir / "index.html").write_text("\n".join(html))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_characterize(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field parameter characterization sweep")
    parser.add_argument("--out", type=str, default="renders/families/crystal_field/characterize")
    parser.add_argument(
        "--scenes",
        type=str,
        default="glass,colored_diffuse,black_diffuse",
        help="Comma-separated list of base scenes (default: all three)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scene_names = [s.strip() for s in args.scenes.split(",") if s.strip()]
    unknown = [s for s in scene_names if s not in BASE_SCENES]
    if unknown:
        raise SystemExit(f"Unknown scene(s): {unknown}. Known: {sorted(BASE_SCENES)}")

    t0 = time.monotonic()
    total_frames = 0

    for scene_name in scene_names:
        base = BASE_SCENES[scene_name]
        scene_dir = out_dir / scene_name
        scene_dir.mkdir(parents=True, exist_ok=True)

        for param, low, high, steps in SWEEPS:
            print(f"  {scene_name} / {param}  [{low} → {high}]", flush=True)
            frame_paths: list[Path] = []
            for i, value in enumerate(np.linspace(low, high, steps)):
                frame_path = scene_dir / f"{param}_{i:02d}.png"
                p = _apply_sweep(base, param, value)
                _render_and_overlay(p, frame_path)
                frame_paths.append(frame_path)
                total_frames += 1

            strip_path = scene_dir / f"{param}.png"
            _concat_strip(frame_paths, strip_path)

    elapsed = time.monotonic() - t0
    print(f"\nDone: {total_frames} frames in {elapsed:.0f}s → {out_dir}/")

    _write_index(out_dir, scene_names, [p[0] for p in SWEEPS])
    print(f"Index: {out_dir}/index.html")


if __name__ == "__main__":
    run_characterize()
