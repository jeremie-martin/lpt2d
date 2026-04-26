"""Render the iris motion catalog.

The cell axis is ``pace × light_kind × geom_kind = 2 × 2 × 4 = 16``.
Branch is fixed to ``solo_white`` and layout to ``iris_horizontal``.

For each cell, sample with the three motion axes pinned, leaving every
other parameter free. Run ``iris.check`` and accept the first variant
that passes the gate. After ``--max-attempts`` failed tries, render the
last variant anyway and mark the cell as failed-gate (red border in the
index).

Outputs::

    renders/families/iris/catalog_<date>/
      <pace>__<light_kind>__<geom_kind>/{video.mp4, params.json,
                                         frame.shot.json, verdict.json}
      index.html

Run::

    python examples/python/families/iris_catalog.py --out <dir>
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

BRANCH = "solo_white"
LAYOUT = "iris_diagonal"


def _cell_slug(pace: str, light_kind: str, geom_kind: str) -> str:
    return f"{pace}__{light_kind}__{geom_kind}"


def _cell_dir(out: Path, pace: str, light_kind: str, geom_kind: str) -> Path:
    return out / _cell_slug(pace, light_kind, geom_kind)


def _make_catalog_shot(*, width: int, height: int, rays: int, depth: int) -> Shot:
    """Catalog render shot. Defaults to a preview-quality look."""
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


def _search_cell(
    rng: random.Random,
    pace: str,
    light_kind: str,
    geom_kind: str,
    max_attempts: int,
) -> tuple[iris.Params, iris.Verdict, int, bool]:
    """Sample variants with the three motion axes pinned (plus branch + layout
    held constant) until the gate passes or attempts run out."""
    last_params: iris.Params | None = None
    last_verdict: iris.Verdict | None = None
    for attempt in range(1, max_attempts + 1):
        p = iris.sample(
            rng,
            branch=BRANCH,
            layout=LAYOUT,
            pace=pace,
            light_kind=light_kind,
            geom_kind=geom_kind,
        )
        animate = iris.build(p)
        v = iris.check(animate)
        last_params, last_verdict = p, v
        if v.ok:
            return p, v, attempt, True
    assert last_params is not None and last_verdict is not None
    return last_params, last_verdict, max_attempts, False


def _render_cell(
    cell_dir: Path,
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
    cell_dir.mkdir(parents=True, exist_ok=True)
    animate = iris.build(p)

    shot = _make_catalog_shot(width=width, height=height, rays=rays, depth=depth)
    shot.name = name
    extra = iris.final_look(p)
    if extra:
        shot.look = shot.look.with_overrides(**extra)

    try:
        _, ctx, _ = pick_best_frame(animate, duration, camera=iris.CAMERA, depth=depth)
        save_frame_shot(
            animate, shot, ctx, cell_dir / "frame.shot.json", camera=iris.CAMERA, name=name
        )
    except Exception as e:  # noqa: BLE001
        print(f"  frame-export skipped ({type(e).__name__}: {e})", flush=True)

    timeline = Timeline(duration, fps=fps)
    render(animate, timeline, str(cell_dir / "video.mp4"), settings=shot, crf=18)


def _write_verdict(
    cell_dir: Path,
    pace: str,
    light_kind: str,
    geom_kind: str,
    v: iris.Verdict,
    attempts: int,
    passed: bool,
) -> None:
    (cell_dir / "verdict.json").write_text(json.dumps({
        "pace": pace,
        "light_kind": light_kind,
        "geom_kind": geom_kind,
        "branch": BRANCH,
        "layout": LAYOUT,
        "ok": v.ok,
        "summary": v.summary,
        "attempts": attempts,
        "gate_passed": passed,
    }, indent=2))


def _write_params(cell_dir: Path, p: iris.Params) -> None:
    (cell_dir / "params.json").write_text(json.dumps(asdict(p), indent=2))


# ── Index.html ─────────────────────────────────────────────────────────


_INDEX_HEAD = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Iris Motion Catalog</title>
<style>
:root { color-scheme: dark; --bg:#10100f; --panel:#1a1916; --ink:#f2eee5; --muted:#aaa194; --line:#36322b; --accent:#8fd3ff; --bad:#ff8b5f; --good:#8dff9d; }
* { box-sizing: border-box; }
body { margin:0; padding:22px; background:var(--bg); color:var(--ink); font-family:ui-sans-serif, system-ui, sans-serif; }
a { color:var(--accent); }
header { max-width:1320px; margin:0 auto 22px; }
h1 { margin:0 0 8px; font-size:clamp(28px, 5vw, 52px); letter-spacing:-0.04em; }
.muted { color:var(--muted); }
.table-wrap { max-width:1320px; margin:0 auto 24px; overflow-x:auto; border:1px solid var(--line); border-radius:12px; background:var(--panel); }
table { width:100%; border-collapse:collapse; min-width:1100px; }
th, td { padding:10px; border-bottom:1px solid var(--line); text-align:center; vertical-align:top; }
th { color:var(--good); background:#13120f; font-size:13px; }
th.row-label { text-align:left; min-width:160px; color:var(--ink); font-family:ui-monospace, monospace; }
td.failed { background:rgba(255, 105, 64, .08); }
.cell { display:flex; flex-direction:column; gap:6px; align-items:center; }
.cell video { width:100%; max-width:200px; aspect-ratio:9 / 16; background:#050505; border:1px solid var(--line); border-radius:8px; display:block; }
td.failed .cell video { border-color:var(--bad); }
.cell .meta { font-size:10px; color:var(--muted); font-family:ui-monospace, monospace; word-break:break-word; }
td.failed .cell .meta { color:var(--bad); }
.links { font-size:11px; display:flex; gap:8px; flex-wrap:wrap; justify-content:center; }
</style></head><body>
<header>
<h1>Iris Motion Catalog</h1>
<p class="muted">
Rows = <code>pace × light_kind</code>; columns = <code>geom_kind</code>.<br>
<code>solo_white · iris_diagonal</code> for every cell. Red border = the gate
(<code>iris.check</code>) never passed within the attempt budget; the cell
is rendered from the last sampled variant anyway.<br>
Hover any video to play it.</p>
</header>
"""


def _write_index(out: Path, cells: list[dict]) -> None:
    parts: list[str] = [_INDEX_HEAD]
    cell_index = {(c["pace"], c["light_kind"], c["geom_kind"]): c for c in cells}

    parts.append('<section class="table-wrap"><table>\n')
    parts.append('<tr><th class="row-label">pace × light \\ geom</th>')
    for geom in iris.GEOM_KINDS:
        parts.append(f"<th>{_html.escape(geom)}</th>")
    parts.append("</tr>\n")

    for pace in iris.PACES:
        for light in iris.LIGHT_KINDS:
            row_label = f"{pace} · {light}"
            parts.append(f'<tr><th class="row-label">{_html.escape(row_label)}</th>')
            for geom in iris.GEOM_KINDS:
                c = cell_index.get((pace, light, geom))
                if c is None:
                    parts.append("<td><div class='cell'><div class='meta'>missing</div></div></td>")
                    continue
                failed_class = "" if c["gate_passed"] else ' class="failed"'
                slug = _cell_slug(pace, light, geom)
                video = f"{slug}/video.mp4"
                params = f"{slug}/params.json"
                shot = f"{slug}/frame.shot.json"
                verdict = f"{slug}/verdict.json"
                status = "OK" if c["gate_passed"] else f"FAIL@{c['attempts']}"
                meta_text = f"{status} · {c['summary']}"
                parts.append(
                    f"<td{failed_class}><div class='cell'>"
                    f"<video src='{_html.escape(video, quote=True)}' "
                    f"preload='metadata' muted loop playsinline controls></video>"
                    f"<div class='meta'>{_html.escape(meta_text)}</div>"
                    f"<div class='links'>"
                    f"<a href='{_html.escape(params, quote=True)}'>params</a>"
                    f"<a href='{_html.escape(shot, quote=True)}'>shot</a>"
                    f"<a href='{_html.escape(verdict, quote=True)}'>verdict</a>"
                    f"</div></div></td>"
                )
            parts.append("</tr>\n")

    parts.append("</table></section>\n")
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
    parser = argparse.ArgumentParser(description="Iris motion catalog")
    parser.add_argument("--out", type=str, required=True, help="Output directory")
    parser.add_argument("--max-attempts", type=int, default=500,
                        help="Search budget per cell (default 500)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Master RNG seed (default: time-based)")
    parser.add_argument("--width", type=int, default=854)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--rays", type=int, default=1_000_000)
    parser.add_argument("--depth", type=int, default=10)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--duration", type=float, default=iris.DURATION)
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip cells whose video.mp4 already exists")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seed = args.seed if args.seed is not None else int(time.time())
    cells_total = len(iris.PACES) * len(iris.LIGHT_KINDS) * len(iris.GEOM_KINDS)
    print(f"catalog seed={seed} cells={cells_total} max_attempts={args.max_attempts}", flush=True)
    print(f"render: {args.width}x{args.height} @ {args.fps}fps  rays={args.rays}  "
          f"depth={args.depth}  duration={args.duration}s", flush=True)

    cells: list[dict] = []
    cell_idx = 0

    for pace in iris.PACES:
        for light in iris.LIGHT_KINDS:
            for geom in iris.GEOM_KINDS:
                cell_idx += 1
                cell_dir = _cell_dir(out, pace, light, geom)
                slug = _cell_slug(pace, light, geom)

                if args.skip_existing and (cell_dir / "video.mp4").exists():
                    vfile = cell_dir / "verdict.json"
                    if vfile.exists():
                        cells.append(json.loads(vfile.read_text()))
                    print(f"[{cell_idx}/{cells_total}] {slug}  skip", flush=True)
                    continue

                print(f"[{cell_idx}/{cells_total}] {slug}  searching...", flush=True)
                rng = random.Random((seed, pace, light, geom).__hash__())
                p, v, attempts, passed = _search_cell(
                    rng, pace, light, geom, args.max_attempts
                )
                print(
                    f"  {'OK' if passed else 'FAIL'} after {attempts}: {v.summary}",
                    flush=True,
                )

                cell_dir.mkdir(parents=True, exist_ok=True)
                _write_params(cell_dir, p)

                print(f"  rendering {cell_dir}/video.mp4 ...", flush=True)
                _render_cell(
                    cell_dir, p,
                    width=args.width, height=args.height,
                    duration=args.duration, fps=args.fps,
                    rays=args.rays, depth=args.depth,
                    name=f"iris_catalog_{slug}",
                )

                # verdict.json is written LAST so its presence is the "render
                # complete" signal — see iris_batch.py for the full rationale.
                _write_verdict(cell_dir, pace, light, geom, v, attempts, passed)
                cells.append({
                    "pace": pace, "light_kind": light, "geom_kind": geom,
                    "branch": BRANCH, "layout": LAYOUT,
                    "ok": v.ok, "summary": v.summary,
                    "attempts": attempts, "gate_passed": passed,
                })

    _write_index(out, cells)
    print(f"\nWrote {out / 'index.html'}", flush=True)


if __name__ == "__main__":
    main()
