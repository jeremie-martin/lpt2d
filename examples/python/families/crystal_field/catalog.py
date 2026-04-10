"""Systematic parameter space exploration for crystal_field.

Generates a structured catalog of renders varying one axis at a time
(material × shape × grid × light colour × n_lights), so the visual effect
of each choice can be assessed directly.

Catalog structure vs. general sampling path
-------------------------------------------
The catalog **fixes** the structural dimensions per entry (material preset,
shape, grid size, wavelength range, n_lights) and **draws** the rest:
``build_seed``, full :class:`LookConfig` (including exposure, gamma,
contrast, white_point, temperature, vignette, chromatic_aberration),
``ambient.intensity``, and ``moving_intensity``.  For each entry the
catalog runs a plain retry loop against the full ``check.py`` pipeline
until a passing candidate is found or the attempt budget is exhausted.
Failing entries are still saved (best-effort closest-to-passing) and
tagged in the HTML gallery with a red border + verdict tooltip.

Run::

    python -m examples.python.families.crystal_field catalog
    python -m examples.python.families.crystal_field catalog --out renders/catalog
"""

from __future__ import annotations

import argparse
import json
import math
import random as _rng_mod
import time
from dataclasses import asdict
from pathlib import Path

from anim import Camera2D, Shot, Timeline, render_frame, save_image
from anim.examples_support import _authored_shot
from anim.family import Verdict

from .check import (
    MAX_MEAN_LUMINANCE,
    MAX_MOVING_RADIUS_RATIO,
    MAX_RADIUS_RATIO,
    MAX_TRANSITION_WIDTH_RATIO,
    MIN_COLORFUL_SECONDS,
    MIN_CONTRAST_SPREAD,
    MIN_CONFIDENCE,
    MIN_COVERAGE_FRACTION,
    MIN_MEAN_LUMINANCE,
    MIN_MOVING_RADIUS_RATIO,
    MIN_PEAK_CONTRAST,
    MeasurementResult,
    _measure_and_verdict,
)
from .overlay import draw_metrics_overlay
from .params import (
    DURATION,
    AmbientConfig,
    GridConfig,
    LightConfig,
    Params,
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
)
from .scene import build

# ── Fixed defaults ───────────────────────────────────────────────────────

_CAM = Camera2D(center=[0, 0], width=3.2)
_SHOT = Shot.preset("production", width=1920, height=1080, rays=10_000_000, depth=12)
# Bake the camera onto _SHOT so _authored_shot() can use settings.camera
# when exporting the authored scene JSON.  render_frame still takes an
# explicit camera= kwarg below and the values agree.
_SHOT.camera = Camera2D(center=_CAM.center, width=_CAM.width)
_TIMELINE = Timeline(DURATION, fps=30)
_FRAME = int(_TIMELINE.total_frames * 0.4)  # 40% of animation
_CTX = _TIMELINE.context_at(_FRAME)


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
    5 outcomes × 3 grids × 4 light colors × 2 n_lights, the catalog
    contains **120 entries**.
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

    # Light topology fixed per entry; intensities drawn per attempt.
    # Ranges are defined inline here (not imported from sampling.py) per the
    # per-branch explicitness rule, even though they match the general path.
    ambient = AmbientConfig(
        style="corners",
        intensity=rng.uniform(0.05, 1.2),
    )
    light = LightConfig(
        n_lights=e["n_lights"],
        path_style="channel",
        n_waypoints=8,
        ambient=ambient,
        speed=0.12,
        moving_intensity=rng.uniform(0.15, 1.5),
        wavelength_min=e["wl_min"],
        wavelength_max=e["wl_max"],
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


def _failure_distance(result: MeasurementResult) -> float:
    """Heuristic score: how far a failing result is from passing.

    Lower = closer.  Used to pick the best-effort fallback from amongst
    many failed attempts.  Each failing threshold contributes a scaled
    distance to the numeric boundary it missed.
    """
    m = result.metrics
    dist = 0.0

    if m["colorful_seconds"] < MIN_COLORFUL_SECONDS:
        dist += (MIN_COLORFUL_SECONDS - m["colorful_seconds"]) * 10.0

    if m["mean"] < MIN_MEAN_LUMINANCE:
        dist += (MIN_MEAN_LUMINANCE - m["mean"]) * 5.0
    elif m["mean"] > MAX_MEAN_LUMINANCE:
        dist += (m["mean"] - MAX_MEAN_LUMINANCE) * 5.0

    if m["contrast_spread"] < MIN_CONTRAST_SPREAD:
        dist += (MIN_CONTRAST_SPREAD - m["contrast_spread"]) * 3.0

    if m["moving_radius_ratio"] > 0:
        if m["moving_radius_ratio"] < MIN_MOVING_RADIUS_RATIO:
            dist += (MIN_MOVING_RADIUS_RATIO - m["moving_radius_ratio"]) * 100.0
        elif m["moving_radius_ratio"] > MAX_MOVING_RADIUS_RATIO:
            dist += (m["moving_radius_ratio"] - MAX_MOVING_RADIUS_RATIO) * 100.0

    if (
        m["moving_radius_ratio"] > 0
        and m["transition_width_ratio"] > MAX_TRANSITION_WIDTH_RATIO
    ):
        dist += (m["transition_width_ratio"] - MAX_TRANSITION_WIDTH_RATIO) * 100.0

    if m["moving_radius_ratio"] > 0 and m["peak_contrast"] < MIN_PEAK_CONTRAST:
        dist += (MIN_PEAK_CONTRAST - m["peak_contrast"]) * 10.0

    if m["moving_radius_ratio"] > 0 and m["confidence"] < MIN_CONFIDENCE:
        dist += (MIN_CONFIDENCE - m["confidence"]) * 5.0

    coverage = m.get("coverage_fraction", MIN_COVERAGE_FRACTION)
    if m["moving_radius_ratio"] > 0 and coverage < MIN_COVERAGE_FRACTION:
        dist += (MIN_COVERAGE_FRACTION - coverage) * 5000.0

    if m["ambient_radius_ratio"] > 0 and m["radius_ratio"] > MAX_RADIUS_RATIO:
        dist += m["radius_ratio"] - MAX_RADIUS_RATIO

    return dist


def _find_good_params(
    e: dict,
    rng: _rng_mod.Random,
    max_attempts: int = 500,
) -> tuple[Params, MeasurementResult]:
    """Draw brightness+look until ``check.py`` passes; fall back to best.

    Returns the (Params, MeasurementResult) pair.  If no attempt passed,
    returns the closest-to-passing one (``result.verdict.ok == False``).
    """
    best: tuple[Params, MeasurementResult] | None = None
    best_score = math.inf

    for _ in range(max_attempts):
        p = _entry_sample(e, rng)
        animate = build(p)
        result = _measure_and_verdict(p, animate)

        if result.verdict.ok:
            return (p, result)

        score = _failure_distance(result)
        if score < best_score:
            best = (p, result)
            best_score = score

    assert best is not None  # max_attempts > 0
    return best


def _entry_tag(e: dict) -> str:
    return f"{e['light_color']}_{e['grid']}_{e['n_lights']}light"


# ── Main ─────────────────────────────────────────────────────────────────


def run_catalog(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field parameter catalog")
    parser.add_argument("--out", type=str, default="renders/families/crystal_field/catalog")
    parser.add_argument("--seed", type=int, default=0, help="RNG seed (default: 0)")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=500,
        help="Max brightness+look attempts per entry (default: 500)",
    )
    args = parser.parse_args(argv)

    entries = _build_catalog_entries()
    print(f"Catalog: {len(entries)} combinations")

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

            if img_path.exists():
                continue

            entry_rng = _rng_mod.Random(f"{args.seed}:{key}")
            p, result = _find_good_params(e, entry_rng, max_attempts=args.max_attempts)
            verdicts[key] = result.verdict

            animate = build(p)
            rr = render_frame(animate, _TIMELINE, frame=_FRAME, settings=_SHOT, camera=_CAM)
            save_image(str(img_path), rr.pixels, 1920, 1080)
            draw_metrics_overlay(img_path, result.metrics)

            # Three artifacts per entry:
            #   *.png        — the overlay-annotated render
            #   *.json       — the crystal_field Params that drove this render
            #   *.shot.json  — the authored Shot (version:10) that the engine sees
            params_path.write_text(json.dumps(asdict(p), indent=2))
            authored = _authored_shot(_SHOT, animate, _CTX)
            authored.name = f"crystal_field/{key}"
            authored.save(shot_path)
            _save_verdicts(verdicts_path, verdicts)

            status = "OK" if result.verdict.ok else "FAIL"
            print(
                f"  {key} {status} exp={p.look.exposure:.2f} "
                f"({rr.time_ms:.0f}ms) — {result.verdict.summary}",
                flush=True,
            )

    elapsed = time.monotonic() - t0
    print(f"\nDone in {elapsed:.0f}s — {len(entries)} images in {out}/")

    _write_index(out, verdicts)
    print(f"Index: {out}/index.html")


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
) -> None:
    """Write an HTML gallery grouped by outcome, rows=light color, cols=grid size.

    Entries whose verdict did not pass are tagged with a ``failed`` CSS
    class (red-orange border) and a tooltip showing ``verdict.summary``.
    """
    html = [
        """<!DOCTYPE html>
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
td.failed img { border:2px solid #e63; }
td img.big { position:fixed; top:0; left:0; width:100vw; height:100vh;
  object-fit:contain; z-index:10; background:#000; cursor:zoom-out; }
td small { font-size:10px; color:#777; }
td.failed small { color:#e63; }
th { padding:4px 8px; color:#aaa; font-size:11px; }
</style></head><body>
<h1>Crystal Field — Parameter Catalog</h1>
<p style="text-align:center;font-size:0.85em;color:#777">
Rows = light color &times; n_lights, Columns = grid size, Grouped by outcome.<br>
Shape is drawn per attempt (not a matrix axis) — expect variety within each cell.<br>
Red borders mark entries that failed <code>check.py</code>; hover for the reason.</p>
"""
    ]

    for outcome in _CATALOG_OUTCOMES:
        html.append(f"<h2>{outcome}</h2>")
        html.append("<table><tr><th></th>")
        for gn in ["small", "medium", "large"]:
            g = GRID_SIZES[gn]
            html.append(f"<th>{gn}<br>{g.rows}×{g.cols}</th>")
        html.append("</tr>")

        for lc_name in ["white", "orange", "yellow", "deep_orange"]:
            for nl in [1, 2]:
                html.append(f"<tr><th>{lc_name} {nl}L</th>")
                for gn in ["small", "medium", "large"]:
                    tag = f"{lc_name}_{gn}_{nl}light"
                    key = f"{outcome}/{tag}"
                    src = f"{key}.png"
                    verdict = verdicts.get(key)
                    td_class = ""
                    tooltip = ""
                    if verdict is not None and not verdict.ok:
                        td_class = ' class="failed"'
                        tooltip = f' title="{verdict.summary}"'
                    html.append(
                        f'<td{td_class}><img src="{src}" loading="lazy"{tooltip} '
                        f"onclick=\"this.classList.toggle('big')\">"
                        f"<small>{tag}</small></td>"
                    )
                html.append("</tr>")

        html.append("</table>")

    html.append("</body></html>")
    (out / "index.html").write_text("\n".join(html))
