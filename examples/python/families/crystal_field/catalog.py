"""Systematic parameter space exploration for crystal_field.

Generates a structured catalog of renders varying one axis at a time,
so the visual effect of each parameter choice can be assessed directly.

Run::

    python -m examples.python.families.crystal_field catalog
    python -m examples.python.families.crystal_field catalog --out renders/catalog
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from anim import Camera2D, Shot, Timeline, render_frame, save_image

from .params import (
    AmbientConfig,
    DURATION,
    GridConfig,
    LightConfig,
    MaterialConfig,
    Params,
    RotationConfig,
    ShapeConfig,
)
from .scene import build

# ── Fixed defaults ───────────────────────────────────────────────────────

_AMBIENT = AmbientConfig(style="corners", intensity=0.25)
_CAM = Camera2D(center=[0, 0], width=3.2)
_SHOT = Shot.preset("production", width=1920, height=1080, rays=10_000_000, depth=12)
_TIMELINE = Timeline(DURATION, fps=30)
_FRAME = int(_TIMELINE.total_frames * 0.4)  # 40% of animation


# ── Axes ─────────────────────────────────────────────────────────────────

GRID_SIZES = {
    "small": GridConfig(rows=4, cols=5, spacing=0.28, offset_rows=False, hole_fraction=0.0),
    "medium": GridConfig(rows=5, cols=7, spacing=0.26, offset_rows=True, hole_fraction=0.0),
    "large": GridConfig(rows=6, cols=9, spacing=0.24, offset_rows=False, hole_fraction=0.0),
}

LIGHT_COLORS = {
    "white": (380.0, 780.0),
    "orange": (550.0, 700.0),
    "yellow": (515.0, 700.0),
    "deep_orange": (570.0, 700.0),
}

# Spectral intensity boost for narrow-band lights.
def _intensity(wl_min: float, wl_max: float) -> float:
    w = wl_max - wl_min
    return min(400.0 / max(w, 50.0), 3.0) if w < 300 else 1.0


# ── Material presets ─────────────────────────────────────────────────────

def _glass_mat() -> MaterialConfig:
    return MaterialConfig(
        style="glass", ior=1.52, cauchy_b=20_000, absorption=1.0,
        fill=0.12, n_color_groups=0, diffuse_style="dark", color_names=[],
    )

def _dark_mat() -> MaterialConfig:
    return MaterialConfig(
        style="diffuse", ior=1.5, cauchy_b=0.0, absorption=0.0,
        fill=0.0, n_color_groups=0, diffuse_style="dark", color_names=[],
    )

def _colored_fill_mat(colors: list[str]) -> MaterialConfig:
    return MaterialConfig(
        style="diffuse", ior=1.5, cauchy_b=0.0, absorption=0.0,
        fill=0.14, n_color_groups=len(colors),
        diffuse_style="colored_fill", color_names=colors,
    )

def _metallic_rough_mat(colors: list[str]) -> MaterialConfig:
    return MaterialConfig(
        style="diffuse", ior=1.5, cauchy_b=0.0, absorption=0.0,
        fill=0.08, n_color_groups=len(colors),
        diffuse_style="metallic_rough", color_names=colors,
    )


# ── Shape presets ────────────────────────────────────────────────────────

def _circle_shape(spacing: float) -> ShapeConfig:
    return ShapeConfig(kind="circle", size=spacing * 0.30, n_sides=0,
                       corner_radius=0.0, rotation=None)

def _polygon_shape(n_sides: int, spacing: float) -> ShapeConfig:
    size = spacing * 0.32
    cr = size * 0.22
    rot = RotationConfig(base_angle=0.15, jitter=0.0)
    return ShapeConfig(kind="polygon", size=size, n_sides=n_sides,
                       corner_radius=cr, rotation=rot)


# ── Catalog definition ───────────────────────────────────────────────────

EXPOSURE_RANGE = {
    "glass": (-7.0, -3.0),
    "dark": (-7.0, -2.5),
    "colored_fill": (-7.0, -2.5),
    "metallic_rough": (-7.0, -2.5),
}

# Representative polygon sides per material (not all 4 for every material).
SHAPES_FOR_MATERIAL = {
    "glass": [("circle", 0)],
    "dark": [("triangle", 3), ("square", 4), ("hexagon", 6)],
    "colored_fill": [("triangle", 3), ("pentagon", 5), ("hexagon", 6)],
    "metallic_rough": [("pentagon", 5), ("hexagon", 6)],
}

# Color palettes for colored materials.
COLOR_PALETTES = {
    "colored_fill": ["cyan", "gold", "pink"],
    "metallic_rough": ["cyan", "gold"],
}


def _build_catalog_entries() -> list[dict]:
    """Build the list of all (material, shape, grid, light_color, n_lights) combos."""
    entries = []

    for mat_name in ["glass", "dark", "colored_fill", "metallic_rough"]:
        for shape_name, n_sides in SHAPES_FOR_MATERIAL[mat_name]:
            for grid_name, grid in GRID_SIZES.items():
                for lc_name, (wl_min, wl_max) in LIGHT_COLORS.items():
                    for n_lights in [1, 2]:
                        entries.append({
                            "mat": mat_name,
                            "shape": shape_name,
                            "grid": grid_name,
                            "light_color": lc_name,
                            "n_lights": n_lights,
                            "grid_cfg": grid,
                            "wl_min": wl_min,
                            "wl_max": wl_max,
                            "n_sides": n_sides,
                        })

    return entries


def _entry_to_params(e: dict, exposure: float, build_seed: int) -> Params:
    """Convert a catalog entry to a Params object with given exposure and seed."""
    grid = e["grid_cfg"]
    spacing = grid.spacing

    # Shape
    if e["n_sides"] == 0:
        shape = _circle_shape(spacing)
    else:
        shape = _polygon_shape(e["n_sides"], spacing)

    # Material
    colors = COLOR_PALETTES.get(e["mat"], [])
    if e["mat"] == "glass":
        material = _glass_mat()
    elif e["mat"] == "dark":
        material = _dark_mat()
    elif e["mat"] == "colored_fill":
        material = _colored_fill_mat(colors)
    else:
        material = _metallic_rough_mat(colors)

    # Light
    light = LightConfig(
        n_lights=e["n_lights"],
        path_style="channel",
        n_waypoints=8,
        ambient=_AMBIENT,
        speed=0.12,
        wavelength_min=e["wl_min"],
        wavelength_max=e["wl_max"],
    )

    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=light,
        exposure=exposure,
        build_seed=build_seed,
    )


def _search_good_params(e: dict, max_attempts: int = 500) -> Params:
    """Search for exposure + build_seed that produce acceptable brightness.

    Tries random exposures from a wide range until the mean luminance
    lands within [0.12, 0.70].  The range is wide enough (-7.0 to -2.5)
    that every material/light combination should have valid exposures.
    """
    import random as _rng_mod

    import numpy as np
    from anim import Camera2D, Shot, Timeline, render_frame
    from .check import MAX_MEAN_LUMINANCE, MIN_MEAN_LUMINANCE, PROBE_W, PROBE_H

    rng = _rng_mod.Random(hash((_entry_tag(e), 0)))
    exp_lo, exp_hi = EXPOSURE_RANGE[e["mat"]]
    cam = Camera2D(center=[0, 0], width=3.2)
    probe_shot = Shot.preset("draft", width=PROBE_W, height=PROBE_H, rays=200_000, depth=10)
    probe_timeline = Timeline(DURATION, fps=30)

    best_p = None
    best_dist = float("inf")

    for _ in range(max_attempts):
        exposure = rng.uniform(exp_lo, exp_hi)
        seed = rng.randint(0, 2**32)
        p = _entry_to_params(e, exposure, seed)
        animate = build(p)

        rr = render_frame(animate, probe_timeline, frame=_FRAME,
                          settings=probe_shot, camera=cam)
        arr = np.frombuffer(rr.pixels, dtype=np.uint8)
        mean_lum = arr.mean() / 255.0

        if MIN_MEAN_LUMINANCE <= mean_lum <= MAX_MEAN_LUMINANCE:
            return p

        # Track the closest-to-valid attempt as fallback.
        target = (MIN_MEAN_LUMINANCE + MAX_MEAN_LUMINANCE) / 2
        dist = abs(mean_lum - target)
        if dist < best_dist:
            best_dist = dist
            best_p = p

    # Return the best attempt even if it didn't pass — better than nothing.
    return best_p  # type: ignore[return-value]


def _entry_tag(e: dict) -> str:
    return f"{e['shape']}_{e['light_color']}_{e['grid']}_{e['n_lights']}light"


# ── Main ─────────────────────────────────────────────────────────────────


def run_catalog(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field parameter catalog")
    parser.add_argument("--out", type=str, default="renders/families/crystal_field/catalog")
    args = parser.parse_args(argv)

    entries = _build_catalog_entries()
    print(f"Catalog: {len(entries)} combinations")

    for mat_name in ["glass", "dark", "colored_fill", "metallic_rough"]:
        mat_entries = [e for e in entries if e["mat"] == mat_name]
        print(f"  {mat_name}: {len(mat_entries)} entries")

    out = Path(args.out)
    t0 = time.monotonic()

    for mat_name in ["glass", "dark", "colored_fill", "metallic_rough"]:
        mat_dir = out / mat_name
        mat_dir.mkdir(parents=True, exist_ok=True)

        mat_entries = [e for e in entries if e["mat"] == mat_name]

        for e in mat_entries:
            tag = _entry_tag(e)
            img_path = mat_dir / f"{tag}.png"
            json_path = mat_dir / f"{tag}.json"

            if img_path.exists():
                continue

            p = _search_good_params(e)
            if p is None:
                print(f"  {mat_name}/{tag} SKIP (no valid params found)", flush=True)
                continue
            animate = build(p)
            rr = render_frame(animate, _TIMELINE, frame=_FRAME,
                              settings=_SHOT, camera=_CAM)
            save_image(str(img_path), rr.pixels, 1920, 1080)
            json_path.write_text(json.dumps(asdict(p), indent=2))
            print(f"  {mat_name}/{tag} exp={p.exposure:.2f} ({rr.time_ms:.0f}ms)", flush=True)

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.0f}s — {len(entries)} images in {out}/")

    # Generate index HTML
    _write_index(out, entries)
    print(f"Index: {out}/index.html")


def _write_index(out: Path, entries: list[dict]) -> None:
    """Write an HTML gallery grouped by material, rows=light color, cols=grid size."""
    html = ["""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Crystal Field Catalog</title>
<style>
body { margin:0; background:#111; color:#ccc; font-family:monospace; }
h1,h2,h3 { text-align:center; color:#ddd; }
h1 { padding:1em 0 .3em; font-size:1.3em; }
h2 { font-size:1.1em; border-top:1px solid #333; margin-top:2em; padding-top:1em; }
h3 { font-size:0.9em; color:#888; }
table { margin:0 auto; border-collapse:collapse; }
td { padding:2px; text-align:center; vertical-align:top; }
td img { width:100%; max-width:320px; display:block; cursor:pointer; }
td img.big { position:fixed; top:0; left:0; width:100vw; height:100vh;
  object-fit:contain; z-index:10; background:#000; cursor:zoom-out; }
td small { font-size:10px; color:#777; }
th { padding:4px 8px; color:#aaa; font-size:11px; }
</style></head><body>
<h1>Crystal Field — Parameter Catalog</h1>
<p style="text-align:center;font-size:0.85em;color:#777">
Rows = light color &times; n_lights, Columns = grid size, Grouped by material &times; shape</p>
"""]

    for mat_name in ["glass", "dark", "colored_fill", "metallic_rough"]:
        mat_entries = [e for e in entries if e["mat"] == mat_name]
        shapes_used = sorted(set((e["shape"], e["n_sides"]) for e in mat_entries))

        for shape_name, n_sides in shapes_used:
            shape_entries = [e for e in mat_entries
                            if e["shape"] == shape_name]

            html.append(f'<h2>{mat_name} — {shape_name}</h2>')
            html.append('<table><tr><th></th>')
            for gn in ["small", "medium", "large"]:
                g = GRID_SIZES[gn]
                html.append(f'<th>{gn}<br>{g.rows}×{g.cols}</th>')
            html.append('</tr>')

            for lc_name in ["white", "orange", "yellow", "deep_orange"]:
                for nl in [1, 2]:
                    html.append(f'<tr><th>{lc_name} {nl}L</th>')
                    for gn in ["small", "medium", "large"]:
                        tag = f"{shape_name}_{lc_name}_{gn}_{nl}light"
                        src = f"{mat_name}/{tag}.png"
                        html.append(f'<td><img src="{src}" loading="lazy" '
                                    f'onclick="this.classList.toggle(\'big\')">'
                                    f'<small>{tag}</small></td>')
                    html.append('</tr>')

            html.append('</table>')

    html.append('</body></html>')
    (out / "index.html").write_text("\n".join(html))
