"""Render a batch of randomly-sampled iris variants under user constraints.

Use this when you want N variants drawn freely from the family's space, with
a few axes pinned (e.g. pace, layout, branch). Unlike ``iris_catalog`` which
forces every (pace, light_kind, geom_kind) cell, this runner samples
light_kind, geom_kind, and all numeric params freely; only the explicitly
constrained axes are held fixed.

For each variant, search up to ``--max-attempts`` for one that passes the
gate; if none does, render the last sampled variant and mark it failed-gate
(red border).

Run::

    python examples/python/families/iris_batch.py \
        --out renders/iris_batch_demo \
        -n 12 --pace fast_light --layout iris_vertical --branch solo_white \
        --width 854 --height 480 --rays 1000000 --depth 10 --fps 24 \
        --duration 15
"""

from __future__ import annotations

import argparse
import html as _html
import json
import random
import time
from dataclasses import asdict
from pathlib import Path

from anim import Shot, render
from anim.family import pick_best_frame, save_frame_shot
from anim.types import Timeline

from examples.python.families import iris


def _make_batch_shot(*, width: int, height: int, rays: int, depth: int) -> Shot:
    shot = Shot.preset("preview", width=width, height=height, rays=rays, depth=depth)
    shot.camera = iris.CAMERA
    shot.look = shot.look.with_overrides(
        gamma=2.0,
        tonemap="reinhardx",
        white_point=0.5,
        normalize="rays",
        temperature=0.1,
    )
    return shot


def _parse_layout_weights(spec: str | None) -> dict[str, float] | None:
    """Parse a string like 'iris_horizontal:1,iris_vertical:3' into a weight map.

    None or empty → None (caller treats as uniform). Unknown layout names raise.
    """
    if not spec:
        return None
    weights: dict[str, float] = {}
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece:
            continue
        key, _, val = piece.partition(":")
        key = key.strip()
        if key not in iris.IRIS_LAYOUTS:
            raise ValueError(
                f"Unknown layout {key!r} in --layout-weights. "
                f"Choices: {list(iris.IRIS_LAYOUTS)}"
            )
        weights[key] = float(val)
    return weights


def _pick_layout(
    rng: random.Random,
    pinned: str | None,
    weights: dict[str, float] | None,
) -> str | None:
    """If pinned, return that layout. Else if weighted, sample. Else None
    (which lets ``iris.sample`` choose uniformly)."""
    if pinned is not None:
        return pinned
    if not weights:
        return None
    layouts = list(weights)
    return rng.choices(layouts, weights=[weights[k] for k in layouts], k=1)[0]


def _search_variant(
    rng: random.Random,
    *,
    branch: str | None,
    layout: str | None,
    layout_weights: dict[str, float] | None,
    pace: str | None,
    light_kind: str | None,
    geom_kind: str | None,
    max_attempts: int,
) -> tuple[iris.Params, iris.Verdict, int, bool]:
    """Sample with the requested axes pinned (any None = freely sampled).
    ``layout_weights`` only takes effect when ``layout`` is None — it lets the
    runner draw a weighted-random layout per attempt. Returns (params,
    verdict, attempts_used, gate_passed)."""
    last_params: iris.Params | None = None
    last_verdict: iris.Verdict | None = None
    for attempt in range(1, max_attempts + 1):
        chosen_layout = _pick_layout(rng, layout, layout_weights)
        p = iris.sample(
            rng, branch=branch, layout=chosen_layout, pace=pace,
            light_kind=light_kind, geom_kind=geom_kind,
        )
        animate = iris.build(p)
        v = iris.check(animate)
        last_params, last_verdict = p, v
        if v.ok:
            return p, v, attempt, True
    assert last_params is not None and last_verdict is not None
    return last_params, last_verdict, max_attempts, False


def _render_variant(
    out_dir: Path,
    p: iris.Params,
    *,
    width: int,
    height: int,
    duration: float,
    fps: int,
    rays: int,
    depth: int,
    name: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    animate = iris.build(p)

    shot = _make_batch_shot(width=width, height=height, rays=rays, depth=depth)
    shot.name = name
    extra = iris.final_look(p)
    if extra:
        shot.look = shot.look.with_overrides(**extra)

    try:
        _, ctx, _ = pick_best_frame(animate, duration, camera=iris.CAMERA, depth=depth)
        save_frame_shot(
            animate, shot, ctx, out_dir / "frame.shot.json", camera=iris.CAMERA, name=name
        )
    except Exception as e:  # noqa: BLE001
        print(f"  frame-export skipped ({type(e).__name__}: {e})", flush=True)

    timeline = Timeline(duration, fps=fps)
    render(animate, timeline, str(out_dir / "video.mp4"), settings=shot, crf=18)


# ── Index.html ─────────────────────────────────────────────────────────


_INDEX_HEAD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root { color-scheme: dark; --bg:#10100f; --panel:#1a1916; --ink:#f2eee5; --muted:#aaa194; --line:#36322b; --accent:#8fd3ff; --bad:#ff8b5f; --good:#8dff9d; }
* { box-sizing: border-box; }
body { margin:0; padding:22px; background:var(--bg); color:var(--ink); font-family:ui-sans-serif, system-ui, sans-serif; }
a { color:var(--accent); }
header { max-width:1320px; margin:0 auto 22px; }
h1 { margin:0 0 8px; font-size:clamp(28px, 5vw, 52px); letter-spacing:-0.04em; }
.muted { color:var(--muted); }
.grid { max-width:1320px; margin:0 auto; display:grid; grid-template-columns:repeat(auto-fill, minmax(420px, 1fr)); gap:18px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px; display:flex; flex-direction:column; gap:8px; }
.card.failed { border-color:var(--bad); background:rgba(255, 105, 64, .04); }
.card h3 { margin:0; font-family:ui-monospace, monospace; font-size:14px; color:var(--good); }
.card.failed h3 { color:var(--bad); }
.card video { width:100%; aspect-ratio:16 / 9; background:#050505; border:1px solid var(--line); border-radius:8px; display:block; }
.card .meta { font-size:11px; color:var(--muted); font-family:ui-monospace, monospace; word-break:break-all; }
.card.failed .meta { color:var(--bad); }
.links { font-size:12px; display:flex; gap:10px; flex-wrap:wrap; }
</style></head><body>
<header>
<h1>__HEADING__</h1>
<p class="muted">__BLURB__</p>
</header>
<section class="grid">
"""


def _write_index(
    out: Path,
    cells: list[dict],
    *,
    title: str,
    heading: str,
    blurb: str,
) -> None:
    parts: list[str] = [
        _INDEX_HEAD
        .replace("__TITLE__", _html.escape(title))
        .replace("__HEADING__", _html.escape(heading))
        .replace("__BLURB__", blurb)  # blurb may contain HTML; trust caller
    ]
    for c in cells:
        slug = c["slug"]
        failed_class = "" if c["gate_passed"] else " failed"
        status = "OK" if c["gate_passed"] else f"FAIL@{c['attempts']}"
        meta_text = (
            f"{status} · pace={c['pace']} light={c['light_kind']} geom={c['geom_kind']}"
            f" · {c['summary']}"
        )
        video = f"{slug}/video.mp4"
        params = f"{slug}/params.json"
        shot = f"{slug}/frame.shot.json"
        verdict = f"{slug}/verdict.json"
        parts.append(
            f"<div class='card{failed_class}'>"
            f"<h3>{_html.escape(slug)}</h3>"
            f"<video src='{_html.escape(video, quote=True)}' "
            f"preload='metadata' muted loop playsinline controls></video>"
            f"<div class='meta'>{_html.escape(meta_text)}</div>"
            f"<div class='links'>"
            f"<a href='{_html.escape(params, quote=True)}'>params</a>"
            f"<a href='{_html.escape(shot, quote=True)}'>shot</a>"
            f"<a href='{_html.escape(verdict, quote=True)}'>verdict</a>"
            f"</div></div>\n"
        )
    parts.append("</section>\n")
    parts.append(
        "<script>\n"
        "for (const v of document.querySelectorAll('video')) {\n"
        "  v.addEventListener('mouseenter', () => v.play().catch(()=>{}));\n"
        "  v.addEventListener('mouseleave', () => { v.pause(); v.currentTime = 0; });\n"
        "}\n"
        "</script>\n"
    )
    parts.append("</body></html>\n")
    (out / "index.html").write_text("".join(parts))


# ── Main ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Iris random batch")
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    parser.add_argument("-n", type=int, default=12, help="Number of variants")
    parser.add_argument("--max-attempts", type=int, default=500,
                        help="Search budget per variant (default 500)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Master RNG seed (default: time-based)")
    # Constraint pinning. Any unset axis is sampled freely.
    parser.add_argument("--branch", type=str, default=None,
                        choices=["solo_white", "solo_warm", "duet_contrast"])
    parser.add_argument("--layout", type=str, default=None,
                        choices=list(iris.IRIS_LAYOUTS),
                        help="Pin layout for every variant (mutually exclusive with --layout-weights)")
    parser.add_argument("--layout-weights", type=str, default=None,
                        help="Weighted layout sampling, e.g. 'iris_horizontal:1,iris_vertical:3'. "
                             "Ignored if --layout is set.")
    parser.add_argument("--pace", type=str, default=None, choices=list(iris.PACES))
    parser.add_argument("--light-kind", type=str, default=None,
                        choices=list(iris.LIGHT_KINDS))
    parser.add_argument("--geom-kind", type=str, default=None,
                        choices=list(iris.GEOM_KINDS))
    # Render config.
    parser.add_argument("--width", type=int, default=854)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--rays", type=int, default=1_000_000)
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--duration", type=float, default=iris.DURATION)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seed = args.seed if args.seed is not None else int(time.time())
    layout_weights = _parse_layout_weights(args.layout_weights)
    if args.layout is not None and layout_weights is not None:
        layout_weights = None  # explicit pin wins
    pinned = {
        "branch": args.branch, "layout": args.layout, "pace": args.pace,
        "light_kind": args.light_kind, "geom_kind": args.geom_kind,
    }
    pinned_str = ", ".join(f"{k}={v}" for k, v in pinned.items() if v is not None) or "<none>"
    weights_str = (
        ", ".join(f"{k}={v:g}" for k, v in layout_weights.items())
        if layout_weights else "<uniform>"
    )
    print(f"batch seed={seed} n={args.n} pinned: {pinned_str}", flush=True)
    print(f"layout weights: {weights_str}", flush=True)
    print(f"render: {args.width}x{args.height} @ {args.fps}fps  rays={args.rays}  "
          f"depth={args.depth}  duration={args.duration}s", flush=True)

    cells: list[dict] = []
    for i in range(1, args.n + 1):
        slug = f"{i:03d}"
        out_dir = out / slug
        rng = random.Random((seed, i).__hash__())

        print(f"[{i}/{args.n}] {slug}  searching...", flush=True)
        p, v, attempts, passed = _search_variant(
            rng, **pinned, layout_weights=layout_weights,
            max_attempts=args.max_attempts,
        )
        print(f"  {'OK' if passed else 'FAIL'} after {attempts}: {iris.describe(p)}", flush=True)
        print(f"  gate: {v.summary}", flush=True)

        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "params.json").write_text(json.dumps(asdict(p), indent=2))
        (out_dir / "verdict.json").write_text(json.dumps({
            "ok": v.ok, "summary": v.summary,
            "attempts": attempts, "gate_passed": passed,
            "pace": p.pace, "light_kind": p.light_kind, "geom_kind": p.geom_kind,
            "branch": p.branch, "layout": p.iris_composition,
        }, indent=2))

        print(f"  rendering {out_dir}/video.mp4 ...", flush=True)
        _render_variant(
            out_dir, p,
            width=args.width, height=args.height,
            duration=args.duration, fps=args.fps,
            rays=args.rays, depth=args.depth,
            name=f"iris_batch_{slug}",
        )

        cells.append({
            "slug": slug,
            "ok": v.ok, "summary": v.summary,
            "attempts": attempts, "gate_passed": passed,
            "pace": p.pace, "light_kind": p.light_kind, "geom_kind": p.geom_kind,
            "branch": p.branch, "layout": p.iris_composition,
        })

    title = f"Iris batch — n={args.n}"
    heading = f"Iris Random Batch (n={args.n})"
    pinned_pieces = [
        f"<code>{_html.escape(k)}={_html.escape(v)}</code>"
        for k, v in pinned.items() if v is not None
    ]
    weights_html = (
        " · ".join(f"<code>{_html.escape(k)}={v:g}</code>" for k, v in layout_weights.items())
        if layout_weights else "<i>uniform</i>"
    )
    blurb = (
        f"Render: {args.width}×{args.height} @ {args.fps} fps, {args.duration:g}s, "
        f"{args.rays:,} rays, depth {args.depth}.<br>"
        f"Pinned axes: {' · '.join(pinned_pieces) or '<i>none</i>'}.<br>"
        f"Layout weights: {weights_html}.<br>"
        "Hover any video to play it. Red border = the gate never passed within "
        "the attempt budget; the variant is rendered from the last sample anyway."
    )
    _write_index(out, cells, title=title, heading=heading, blurb=blurb)
    print(f"\nWrote {out / 'index.html'}", flush=True)


if __name__ == "__main__":
    main()
