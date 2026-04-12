"""Systematic parameter space exploration for crystal_field.

Generates a structured catalog of renders varying one axis at a time
(material × shape × grid × light colour × n_lights), so the visual effect
of each choice can be assessed directly.

Catalog structure vs. general sampling path
-------------------------------------------
The catalog **fixes** the structural dimensions per entry (material preset,
shape, grid size, wavelength range, n_lights) and **draws** the rest:
``build_seed``, full :class:`LookConfig` (including exposure, gamma,
contrast, white_point, temperature, highlights, shadows, chromatic_aberration),
``ambient.intensity``, and ``moving_intensity``.  For each entry the
catalog runs a retry loop over structural candidates; each candidate traces
the selected analysis frame once, then tries many random post-processing
looks via replay before the scene is discarded.
Failing entries are still saved (best-effort closest-to-passing) and
tagged in the HTML gallery with a red border + verdict tooltip.

Run::

    python -m examples.python.families.crystal_field catalog
    python -m examples.python.families.crystal_field catalog --out renders/catalog
"""

from __future__ import annotations

import argparse
import html as _html
import json
import math
import random as _rng_mod
import shutil
import time
from dataclasses import asdict, replace
from pathlib import Path

from PIL import Image

from anim import Camera2D, Shot, Timeline, render_frame, save_image
from anim.examples_support import _authored_shot
from anim.family import Verdict

from .check import (
    BLACK_DIFFUSE_MAX_SHADOW_FRACTION,
    GLASS_MAX_MEAN_LUMINANCE,
    MAX_AMBIENT_RADIUS_RATIO,
    MAX_MEAN_LUMINANCE,
    MAX_MEAN_SATURATION,
    MAX_MOVING_RADIUS_RATIO,
    MAX_NEAR_BLACK_FRACTION,
    MAX_RADIUS_RATIO,
    MAX_SHADOW_FLOOR,
    MAX_SHADOW_FRACTION,
    METRIC_KEYS,
    MIN_AMBIENT_RADIUS_RATIO,
    MIN_CONTRAST_SPREAD,
    MIN_MEAN_LUMINANCE,
    MIN_MOVING_RADIUS_RATIO,
    MIN_RADIUS_RATIO,
    PROBE_H,
    PROBE_RAYS,
    PROBE_W,
    MeasurementResult,
    measure_look_variants,
)
from .overlay import draw_metrics_overlay
from .params import (
    DURATION,
    GridConfig,
    LightConfig,
    Params,
    range_spectrum,
)
from .sampling import (
    _black_diffuse_material,
    _brushed_metal_material,
    _colored_diffuse_material,
    _glass_material,
    _glass_shape,
    _gray_diffuse_material,
    _polygon_shape,
    _random_look,
    ambient_for_moving_spectrum,
    sample_ambient_intensity,
    sample_moving_intensity,
)
from .scene import build

# ── Fixed defaults ───────────────────────────────────────────────────────

_CAM = Camera2D(center=[0, 0], width=3.2)
_SHOT = Shot.preset("production", width=1920, height=1080, rays=10_000_000, depth=12)
# Bake the camera onto _SHOT so _authored_shot() can use settings.camera
# when exporting the authored scene JSON.  render_frame still takes an
# explicit camera= kwarg below and the values agree.
_SHOT.camera = Camera2D(center=_CAM.center, width=_CAM.width)
DEFAULT_LOOK_ATTEMPTS = 100


# ── Axes ─────────────────────────────────────────────────────────────────

GRID_SIZES = {
    "small": GridConfig(rows=4, cols=5, spacing=0.28, offset_rows=False, hole_fraction=0.0),
    "medium": GridConfig(rows=5, cols=7, spacing=0.26, offset_rows=True, hole_fraction=0.0),
    "large": GridConfig(rows=6, cols=9, spacing=0.24, offset_rows=False, hole_fraction=0.0),
}

LIGHT_COLORS = {
    "white": (380.0, 780.0),
    "orange": (550.0, 700.0),
    "deep_orange": (570.0, 700.0),
}


# ── Outcome → material sampler ───────────────────────────────────────────
#
# Each catalog entry fixes only the ``outcome`` (one of the 5 peers) and a
# thin structural scaffolding (grid, light topology, wavelengths,
# n_lights).  Everything else — **including the shape** — is drawn fresh
# per attempt via the same per-branch sampling functions as the general
# path.  No hardcoded material constants inside catalog.py, and no
# shape-in-the-matrix multiplier.

_OUTCOME_MATERIAL_SAMPLERS = {
    "glass": _glass_material,
    "black_diffuse": _black_diffuse_material,
    "gray_diffuse": _gray_diffuse_material,
    "colored_diffuse": _colored_diffuse_material,
    "brushed_metal": _brushed_metal_material,
}

_CATALOG_OUTCOMES: tuple[str, ...] = (
    "glass",
    "black_diffuse",
    "gray_diffuse",
    "colored_diffuse",
    "brushed_metal",
)


# ── Catalog definition ───────────────────────────────────────────────────


def _build_catalog_entries() -> list[dict]:
    """Build the list of all (outcome, grid, light_color, n_lights) combos.

    Shape is no longer a matrix axis — it's part of the per-attempt
    randomness (same as material params, look dims, intensities).  With
    5 outcomes × 3 grids × 3 light colors × 2 n_lights, the catalog
    contains **90 entries**.
    """
    entries = []

    for outcome in _CATALOG_OUTCOMES:
        for grid_name, grid in GRID_SIZES.items():
            for lc_name, (wl_min, wl_max) in LIGHT_COLORS.items():
                for n_lights in [1, 2]:
                    entries.append(
                        {
                            "outcome": outcome,
                            "grid": grid_name,
                            "light_color": lc_name,
                            "n_lights": n_lights,
                            "grid_cfg": grid,
                            "wl_min": wl_min,
                            "wl_max": wl_max,
                        }
                    )

    return entries


# ── Per-entry sampling ───────────────────────────────────────────────────


def _entry_sample(e: dict, rng: _rng_mod.Random) -> Params:
    """Draw a full Params for a catalog entry.

    The entry fixes only the thin structural scaffolding (outcome name,
    grid size, light wavelengths, n_lights).  Shape, material, look,
    build_seed, and light intensities are drawn freshly per attempt via
    the same per-branch sampling functions as the general path.  This
    keeps catalog and general paths using **exactly** the same logic;
    catalog.py no longer hardcodes shape or material constants.
    """
    grid = e["grid_cfg"]

    # Shape: drawn per attempt.  Glass always gets a circle, non-glass
    # outcomes get a randomized polygon (3/4/5/6 sides, varied size and
    # rotation).  Same helpers the general sampling path uses.
    if e["outcome"] == "glass":
        shape = _glass_shape(rng, grid.spacing)
    else:
        shape = _polygon_shape(rng, grid.spacing)

    # Material: drawn fresh per attempt via the matching per-outcome function.
    material = _OUTCOME_MATERIAL_SAMPLERS[e["outcome"]](rng)

    spectrum = range_spectrum(e["wl_min"], e["wl_max"])

    # Light topology fixed per entry; intensities drawn per attempt.
    ambient = ambient_for_moving_spectrum(
        rng,
        style="corners",
        intensity=sample_ambient_intensity(rng),
        moving_spectrum=spectrum,
    )
    light = LightConfig(
        n_lights=e["n_lights"],
        path_style="channel",
        n_waypoints=8,
        ambient=ambient,
        speed=0.12,
        moving_intensity=sample_moving_intensity(rng),
        spectrum=spectrum,
    )

    # Look drawn with material/light-aware suppression (same as sampling.py).
    look = _random_look(rng, material, light)

    build_seed = rng.randint(0, 2**32)

    return Params(
        grid=grid,
        shape=shape,
        material=material,
        light=light,
        look=look,
        build_seed=build_seed,
    )


# ── Retry loop ───────────────────────────────────────────────────────────


def _look_candidates(
    p: Params,
    rng: _rng_mod.Random,
    count: int,
):
    """Yield post-process looks for one fixed structural scene.

    The first look is the one sampled with the scene, preserving the old
    one-look behavior when ``count == 1``. Remaining looks are fresh random
    post-process draws that can be replayed over the same traced frame.
    """
    yield "look_000", p.look
    for idx in range(1, max(1, count)):
        yield f"look_{idx:03d}", _random_look(rng, p.material, p.light)


def _failure_distance(result: MeasurementResult, outcome: str | None = None) -> float:
    """Heuristic score: how far a failing result is from passing.

    Lower = closer.  Used to pick the best-effort fallback from amongst
    many failed attempts.  Each failing threshold contributes a scaled
    distance to the numeric boundary it missed.
    """
    m = result.metrics
    dist = 0.0

    max_mean_luminance = (
        GLASS_MAX_MEAN_LUMINANCE if outcome == "glass" else MAX_MEAN_LUMINANCE
    )
    max_shadow_fraction = (
        BLACK_DIFFUSE_MAX_SHADOW_FRACTION
        if outcome == "black_diffuse"
        else MAX_SHADOW_FRACTION
    )

    if m["mean"] < MIN_MEAN_LUMINANCE:
        dist += (MIN_MEAN_LUMINANCE - m["mean"]) / 255.0
    if m["mean"] > max_mean_luminance:
        dist += (m["mean"] - max_mean_luminance) / 255.0

    if m["shadow_floor"] > MAX_SHADOW_FLOOR:
        dist += (m["shadow_floor"] - MAX_SHADOW_FLOOR) / 255.0

    if m["contrast_spread"] < MIN_CONTRAST_SPREAD:
        dist += (MIN_CONTRAST_SPREAD - m["contrast_spread"]) / 255.0

    if m["near_black_fraction"] > MAX_NEAR_BLACK_FRACTION:
        dist += m["near_black_fraction"] - MAX_NEAR_BLACK_FRACTION

    if m["shadow_fraction"] > max_shadow_fraction:
        dist += m["shadow_fraction"] - max_shadow_fraction

    if m["mean_saturation"] >= MAX_MEAN_SATURATION:
        dist += m["mean_saturation"] - MAX_MEAN_SATURATION

    if m["moving_radius_min"] < MIN_MOVING_RADIUS_RATIO:
        dist += (MIN_MOVING_RADIUS_RATIO - m["moving_radius_min"]) * 100.0
    if m["moving_radius_max"] > MAX_MOVING_RADIUS_RATIO:
        dist += (m["moving_radius_max"] - MAX_MOVING_RADIUS_RATIO) * 100.0

    if m["ambient_radius_min"] < MIN_AMBIENT_RADIUS_RATIO:
        dist += (MIN_AMBIENT_RADIUS_RATIO - m["ambient_radius_min"]) * 100.0
    if m["ambient_radius_max"] > MAX_AMBIENT_RADIUS_RATIO:
        dist += (m["ambient_radius_max"] - MAX_AMBIENT_RADIUS_RATIO) * 100.0

    radius_ratio = m["moving_to_ambient_radius_ratio"]
    if radius_ratio < MIN_RADIUS_RATIO:
        dist += MIN_RADIUS_RATIO - radius_ratio
    elif radius_ratio > MAX_RADIUS_RATIO:
        dist += radius_ratio - MAX_RADIUS_RATIO

    return dist


def _find_good_params(
    e: dict,
    rng: _rng_mod.Random,
    max_attempts: int = 500,
    look_attempts: int = DEFAULT_LOOK_ATTEMPTS,
) -> tuple[Params, MeasurementResult]:
    """Draw scene candidates, replay many looks, and return the first pass.

    Returns the (Params, MeasurementResult) pair.  If no attempt passed,
    returns the closest-to-passing one (``result.verdict.ok == False``).
    """
    best: tuple[Params, MeasurementResult] | None = None
    best_score = math.inf

    for _ in range(max_attempts):
        p = _entry_sample(e, rng)
        animate = build(p)
        looks = _look_candidates(p, rng, look_attempts)

        for _name, look, result in measure_look_variants(p, animate, looks):
            candidate = replace(p, look=look)
            if result.verdict.ok:
                return (candidate, result)

            score = _failure_distance(result, outcome=e["outcome"])
            if score < best_score:
                best = (candidate, result)
                best_score = score

    assert best is not None  # max_attempts > 0
    return best


def _entry_tag(e: dict) -> str:
    return f"{e['light_color']}_{e['grid']}_{e['n_lights']}light"


def _metrics_payload(key: str, result: MeasurementResult) -> dict:
    metric_keys = (*METRIC_KEYS, "analysis_frame", "analysis_fps", "analysis_time")
    return {
        "schema": 1,
        "source": (
            "core FrameAnalysis via _lpt2d; Python only aggregates per-light "
            "radius_ratio values into moving/ambient group metrics"
        ),
        "entry": key,
        "analysis_frame": result.analysis_frame,
        "analysis_fps": result.analysis_fps,
        "analysis_time": result.analysis_time,
        "probe": {
            "width": PROBE_W,
            "height": PROBE_H,
            "rays": PROBE_RAYS,
        },
        "metrics": {k: result.metrics[k] for k in metric_keys if k in result.metrics},
        "verdict": {
            "ok": result.verdict.ok,
            "summary": result.verdict.summary,
        },
    }


# ── Main ─────────────────────────────────────────────────────────────────


def run_catalog(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field parameter catalog")
    parser.add_argument("--out", type=str, default="renders/families/crystal_field/catalog")
    parser.add_argument("--web-out", type=str, help="optional JPEG web gallery output")
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=91,
        help="JPEG quality for --web-out images (default: 91)",
    )
    parser.add_argument("--seed", type=int, default=0, help="RNG seed (default: 0)")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=500,
        help="Max structural scene attempts per entry (default: 500)",
    )
    parser.add_argument(
        "--look-attempts",
        type=int,
        default=DEFAULT_LOOK_ATTEMPTS,
        help="Post-process looks to replay per structural attempt (default: 100)",
    )
    args = parser.parse_args(argv)

    entries = _build_catalog_entries()
    print(f"Catalog: {len(entries)} combinations")
    print(
        f"Search budget: {args.max_attempts} structural attempts × "
        f"{max(1, args.look_attempts)} looks"
    )

    for outcome in _CATALOG_OUTCOMES:
        outcome_entries = [e for e in entries if e["outcome"] == outcome]
        print(f"  {outcome}: {len(outcome_entries)} entries")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    # Per-entry verdicts keyed by "{outcome}/{tag}".  Persisted to
    # verdicts.json so resumed runs keep red-border annotations on
    # already-rendered entries.
    verdicts_path = out / "verdicts.json"
    verdicts: dict[str, Verdict] = _load_verdicts(verdicts_path)

    for outcome in _CATALOG_OUTCOMES:
        outcome_dir = out / outcome
        outcome_dir.mkdir(parents=True, exist_ok=True)

        outcome_entries = [e for e in entries if e["outcome"] == outcome]

        for e in outcome_entries:
            tag = _entry_tag(e)
            key = f"{outcome}/{tag}"
            img_path = outcome_dir / f"{tag}.png"
            params_path = outcome_dir / f"{tag}.json"
            shot_path = outcome_dir / f"{tag}.shot.json"
            metrics_path = outcome_dir / f"{tag}.metrics.json"

            if (
                img_path.exists()
                and params_path.exists()
                and shot_path.exists()
                and metrics_path.exists()
            ):
                continue

            entry_rng = _rng_mod.Random(f"{args.seed}:{key}")
            p, result = _find_good_params(
                e,
                entry_rng,
                max_attempts=args.max_attempts,
                look_attempts=max(1, args.look_attempts),
            )
            verdicts[key] = result.verdict

            animate = build(p)
            analysis_timeline = Timeline(DURATION, fps=result.analysis_fps)
            rr = render_frame(
                animate,
                analysis_timeline,
                frame=result.analysis_frame,
                settings=_SHOT,
                camera=_CAM,
            )
            save_image(str(img_path), rr.pixels, 1920, 1080)
            draw_metrics_overlay(img_path, result.metrics)

            # Four artifacts per entry:
            #   *.png        — the overlay-annotated render
            #   *.json       — the crystal_field Params that drove this render
            #   *.metrics.json — canonical core-analysis metrics + selected frame
            #   *.shot.json  — the authored Shot (version:10) that the engine sees
            params_path.write_text(json.dumps(asdict(p), indent=2))
            metrics_path.write_text(json.dumps(_metrics_payload(key, result), indent=2))
            authored = _authored_shot(
                _SHOT,
                animate,
                analysis_timeline.context_at(result.analysis_frame),
            )
            authored.name = f"crystal_field/{key}"
            authored.save(shot_path)
            _save_verdicts(verdicts_path, verdicts)

            status = "OK" if result.verdict.ok else "FAIL"
            print(
                f"  {key} {status} exp={p.look.exposure:.2f} "
                f"t={result.analysis_time:.2f}s ({rr.time_ms:.0f}ms) — "
                f"{result.verdict.summary}",
                flush=True,
            )

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.0f}s — {len(entries)} images in {out}/")

    _write_index(out, verdicts)
    print(f"Index: {out}/index.html")
    if args.web_out:
        web_out = Path(args.web_out)
        _write_web_gallery(out, web_out, verdicts, jpeg_quality=args.jpeg_quality)
        print(f"Web index: {web_out}/index.html")


def _load_verdicts(path: Path) -> dict[str, Verdict]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {k: Verdict(ok=v["ok"], summary=v["summary"]) for k, v in raw.items()}


def _save_verdicts(path: Path, verdicts: dict[str, Verdict]) -> None:
    data = {k: {"ok": v.ok, "summary": v.summary} for k, v in verdicts.items()}
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _write_index(
    out: Path,
    verdicts: dict[str, Verdict],
    *,
    image_ext: str = "png",
) -> None:
    """Write an HTML gallery grouped by outcome, rows=light color, cols=grid size.

    Entries whose verdict did not pass are tagged with a ``failed`` CSS
    class (red-orange border) and a tooltip showing ``verdict.summary``.
    """
    parts = [
        """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crystal Field Catalog</title>
<style>
:root { color-scheme: dark; --bg:#10100f; --panel:#1a1916; --ink:#f2eee5; --muted:#aaa194; --line:#36322b; --accent:#8fd3ff; --bad:#ff8b5f; --good:#8dff9d; }
* { box-sizing: border-box; }
body { margin:0; padding:22px; background:var(--bg); color:var(--ink); font-family:ui-sans-serif, system-ui, sans-serif; }
a { color:var(--accent); }
header { max-width:1180px; margin:0 auto 22px; }
h1 { margin:0 0 8px; font-size:clamp(28px, 5vw, 52px); letter-spacing:-0.04em; }
h2 { margin:34px auto 14px; max-width:1180px; font-size:clamp(22px, 3vw, 34px); }
.muted { color:var(--muted); }
.table-wrap { max-width:1180px; margin:0 auto 24px; overflow-x:auto; border:1px solid var(--line); border-radius:12px; background:var(--panel); }
table { width:100%; border-collapse:collapse; min-width:900px; }
th,td { padding:8px; border-bottom:1px solid var(--line); text-align:center; vertical-align:top; }
th { color:var(--good); background:#13120f; font-size:12px; }
td.failed { background:rgba(255, 105, 64, .08); }
button.thumb { appearance:none; border:1px solid var(--line); border-radius:10px; padding:0; margin:0; background:#050505; color:var(--ink); cursor:zoom-in; overflow:hidden; width:100%; max-width:320px; text-align:left; position:relative; }
td.failed button.thumb { border-color:var(--bad); }
button.thumb img { display:block; width:100%; aspect-ratio:16 / 9; object-fit:contain; background:#050505; }
button.thumb span { position:absolute; left:8px; bottom:8px; padding:3px 6px; border-radius:999px; background:rgba(0,0,0,.72); font-size:12px; }
.cell-links { margin-top:6px; font-size:11px; display:flex; justify-content:center; gap:7px; flex-wrap:wrap; }
.cell-links small { color:var(--muted); }
td.failed .cell-links small { color:var(--bad); }
.viewer[hidden] { display:none; }
.viewer { position:fixed; inset:0; z-index:20; display:grid; grid-template-rows:auto 1fr auto; background:rgba(0,0,0,.94); }
.viewer-bar { display:flex; align-items:center; gap:8px; padding:9px; border-bottom:1px solid #333; background:#090909; }
.viewer-title { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); }
.viewer button { border:1px solid #444; border-radius:8px; background:#181818; color:var(--ink); padding:8px 10px; font:inherit; }
.stage { min-height:0; overflow:auto; display:flex; align-items:center; justify-content:center; padding:12px; }
.stage img { max-width:100%; max-height:100%; height:auto; width:auto; }
.stage.zoomed { align-items:flex-start; justify-content:flex-start; }
.caption { padding:9px 12px; color:var(--muted); border-top:1px solid #333; background:#090909; font-size:13px; }
.no-scroll { overflow:hidden; }
@media (max-width:640px) {
  body { padding:14px; }
  .viewer-bar { gap:5px; padding:7px; }
  .viewer button { padding:7px 8px; }
  .viewer-title { font-size:12px; }
}
</style></head><body>
<header>
<h1>Crystal Field Catalog</h1>
<p class="muted">
Rows = light color &times; n_lights, Columns = grid size, Grouped by outcome.<br>
Shape is drawn per attempt (not a matrix axis) — expect variety within each cell.<br>
Red borders mark entries that failed <code>check.py</code>. Click any image for previous/next, arrow keys, swipe, or zoom controls.</p>
</header>
"""
    ]

    for outcome in _CATALOG_OUTCOMES:
        parts.append(f"<h2>{_html.escape(outcome)}</h2>")
        parts.append('<section class="table-wrap"><table><tr><th></th>')
        for gn in ["small", "medium", "large"]:
            g = GRID_SIZES[gn]
            parts.append(f"<th>{_html.escape(gn)}<br>{g.rows}×{g.cols}</th>")
        parts.append("</tr>")

        for lc_name in LIGHT_COLORS:
            for nl in [1, 2]:
                parts.append(f"<tr><th>{_html.escape(lc_name)} {nl}L</th>")
                for gn in ["small", "medium", "large"]:
                    tag = f"{lc_name}_{gn}_{nl}light"
                    key = f"{outcome}/{tag}"
                    verdict = verdicts.get(key)
                    td_class = ""
                    verdict_text = "pending"
                    if verdict is not None and not verdict.ok:
                        td_class = ' class="failed"'
                    if verdict is not None:
                        verdict_text = ("OK: " if verdict.ok else "FAIL: ") + verdict.summary
                    caption = f"{key} -- {verdict_text}"
                    src = f"{key}.{image_ext}"
                    params = f"{key}.json"
                    metrics = f"{key}.metrics.json"
                    shot = f"{key}.shot.json"
                    parts.append(
                        f'{td_class and f"<td{td_class}>" or "<td>"}'
                        f'<button class="thumb" data-full="{_html.escape(src, quote=True)}" '
                        f'data-caption="{_html.escape(caption, quote=True)}">'
                        f'<img src="{_html.escape(src, quote=True)}" loading="lazy" '
                        f'alt="{_html.escape(caption, quote=True)}"><span>Open</span></button>'
                        f'<div class="cell-links"><small>{_html.escape(tag)}</small>'
                        f'<a href="{_html.escape(params, quote=True)}">params</a>'
                        f'<a href="{_html.escape(metrics, quote=True)}">metrics</a>'
                        f'<a href="{_html.escape(shot, quote=True)}">shot</a></div></td>'
                    )
                parts.append("</tr>")

        parts.append("</table></section>")

    parts.append(
        """
<div class="viewer" id="viewer" hidden>
  <div class="viewer-bar">
    <button type="button" id="prevBtn">Prev</button>
    <button type="button" id="nextBtn">Next</button>
    <button type="button" id="fitBtn">Fit</button>
    <button type="button" id="zoomOutBtn">-</button>
    <button type="button" id="zoomInBtn">+</button>
    <div class="viewer-title" id="viewerTitle"></div>
    <button type="button" id="closeBtn">Close</button>
  </div>
  <div class="stage" id="stage"><img id="viewerImg" alt=""></div>
  <div class="caption" id="viewerCaption"></div>
</div>
<script>
const thumbs = Array.from(document.querySelectorAll("[data-full]"));
const items = thumbs.map((el) => ({ src: el.dataset.full, caption: el.dataset.caption || el.dataset.full }));
const viewer = document.getElementById("viewer");
const stage = document.getElementById("stage");
const img = document.getElementById("viewerImg");
const title = document.getElementById("viewerTitle");
const caption = document.getElementById("viewerCaption");
let current = 0;
let zoom = 0;
let touchX = null;

function applyZoom() {
  if (zoom <= 0) {
    stage.classList.remove("zoomed");
    img.style.width = "";
    img.style.maxWidth = "100%";
    img.style.maxHeight = "100%";
    return;
  }
  stage.classList.add("zoomed");
  img.style.maxWidth = "none";
  img.style.maxHeight = "none";
  img.style.width = `${Math.max(1, img.naturalWidth * zoom)}px`;
}
function show(index) {
  current = (index + items.length) % items.length;
  const item = items[current];
  img.src = item.src;
  img.alt = item.caption;
  title.textContent = `${current + 1} / ${items.length}`;
  caption.textContent = item.caption;
  applyZoom();
}
function openViewer(index) {
  zoom = 0;
  viewer.hidden = false;
  document.body.classList.add("no-scroll");
  show(index);
}
function closeViewer() {
  viewer.hidden = true;
  document.body.classList.remove("no-scroll");
}
thumbs.forEach((el, index) => el.addEventListener("click", () => openViewer(index)));
document.getElementById("prevBtn").addEventListener("click", () => show(current - 1));
document.getElementById("nextBtn").addEventListener("click", () => show(current + 1));
document.getElementById("closeBtn").addEventListener("click", closeViewer);
document.getElementById("fitBtn").addEventListener("click", () => { zoom = 0; applyZoom(); });
document.getElementById("zoomInBtn").addEventListener("click", () => { zoom = zoom <= 0 ? 1 : Math.min(4, zoom * 1.35); applyZoom(); });
document.getElementById("zoomOutBtn").addEventListener("click", () => { zoom = zoom <= 0 ? 0 : Math.max(0.25, zoom / 1.35); applyZoom(); });
img.addEventListener("load", applyZoom);
viewer.addEventListener("click", (event) => { if (event.target === viewer) closeViewer(); });
stage.addEventListener("touchstart", (event) => { touchX = event.changedTouches[0].clientX; }, { passive: true });
stage.addEventListener("touchend", (event) => {
  if (touchX === null) return;
  const dx = event.changedTouches[0].clientX - touchX;
  touchX = null;
  if (Math.abs(dx) > 55) show(current + (dx < 0 ? 1 : -1));
}, { passive: true });
window.addEventListener("keydown", (event) => {
  if (viewer.hidden) return;
  if (event.key === "Escape") closeViewer();
  if (event.key === "ArrowLeft") show(current - 1);
  if (event.key === "ArrowRight") show(current + 1);
});
</script>
</body></html>"""
    )
    (out / "index.html").write_text("\n".join(parts))


def _write_web_gallery(
    src: Path,
    dst: Path,
    verdicts: dict[str, Verdict],
    *,
    jpeg_quality: int,
) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for outcome in _CATALOG_OUTCOMES:
        src_dir = src / outcome
        dst_dir = dst / outcome
        dst_dir.mkdir(parents=True, exist_ok=True)
        for png_path in src_dir.glob("*.png"):
            jpg_path = dst_dir / f"{png_path.stem}.jpg"
            image = Image.open(png_path).convert("RGB")
            image.save(jpg_path, "JPEG", quality=jpeg_quality, optimize=True, progressive=True)
        for sidecar in src_dir.glob("*.json"):
            shutil.copy2(sidecar, dst_dir / sidecar.name)

    verdicts_src = src / "verdicts.json"
    if verdicts_src.exists():
        shutil.copy2(verdicts_src, dst / "verdicts.json")
    _write_index(dst, verdicts, image_ext="jpg")
