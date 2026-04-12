"""Compare white ambient lights against complementary colored ambient lights.

Example:

    python -m examples.python.families.crystal_field ambient_compare \
        --in renders/families/crystal_field/catalog \
        --out renders/families/crystal_field/ambient_compare \
        --limit 12
"""

from __future__ import annotations

import argparse
import dataclasses
import html
import json
import random
from pathlib import Path

from PIL import Image

from anim import Camera2D, Shot, Timeline, render_frame, save_image
from anim.params import params_from_dict

from .catalog import _CAM
from .check import _measure_and_verdict
from .params import DURATION, LightSpectrumConfig, Params
from .sampling import ambient_for_moving_spectrum
from .scene import build


def _param_paths(root: Path) -> list[Path]:
    candidates = sorted(root.rglob("*.json")) if root.is_dir() else [root]
    paths: list[Path] = []
    for path in candidates:
        if path.name in {"manifest.json", "verdicts.json"}:
            continue
        if path.name.endswith(".metrics.json") or path.name.endswith(".shot.json"):
            continue
        paths.append(path)
    return paths


def _tag(root: Path, path: Path) -> str:
    if root.is_dir():
        rel = path.relative_to(root)
        return "__".join([*rel.parent.parts, rel.stem])
    return path.stem


def _with_white_ambient(p: Params) -> Params:
    ambient = dataclasses.replace(p.light.ambient, spectrum=LightSpectrumConfig())
    light = dataclasses.replace(p.light, ambient=ambient)
    return dataclasses.replace(p, light=light)


def _with_complementary_ambient(p: Params, seed: str) -> Params:
    ambient = ambient_for_moving_spectrum(
        random.Random(seed),
        style=p.light.ambient.style,
        intensity=p.light.ambient.intensity,
        moving_spectrum=p.light.spectrum,
    )
    light = dataclasses.replace(p.light, ambient=ambient)
    return dataclasses.replace(p, light=light)


def _render_variant(
    p: Params,
    output: Path,
    *,
    width: int,
    height: int,
    rays: int,
    batch: int,
    depth: int,
) -> dict:
    animate = build(p)
    result = _measure_and_verdict(p, animate)
    settings = Shot.preset("draft", width=width, height=height, rays=rays, depth=depth)
    settings.trace.batch = batch
    timeline = Timeline(DURATION, fps=result.analysis_fps)
    rr = render_frame(
        animate,
        timeline,
        frame=result.analysis_frame,
        settings=settings,
        camera=Camera2D(center=_CAM.center, width=_CAM.width),
    )
    save_image(str(output), rr.pixels, width, height)
    return {
        "verdict": {"ok": result.verdict.ok, "summary": result.verdict.summary},
        "analysis_frame": result.analysis_frame,
        "analysis_time": result.analysis_time,
        "metrics": result.metrics,
    }


def _write_side_by_side(left: Path, right: Path, output: Path) -> None:
    left_img = Image.open(left).convert("RGB")
    right_img = Image.open(right).convert("RGB")
    h = max(left_img.height, right_img.height)
    out = Image.new("RGB", (left_img.width + right_img.width, h), color=(0, 0, 0))
    out.paste(left_img, (0, 0))
    out.paste(right_img, (left_img.width, 0))
    out.save(output)


def _write_index(out: Path, rows: list[dict]) -> None:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Crystal Field Ambient Comparison</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:24px;background:#111;color:#eee}",
        ".row{margin:0 0 28px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}",
        "img{width:100%;height:auto}.meta{color:#aaa;font-size:14px;margin:6px 0 10px}",
        "h2{font-size:18px;margin:0 0 4px}a{color:#9cf}",
        "</style></head><body>",
        "<h1>Crystal Field Ambient Comparison</h1>",
        "<p>White ambient, complementary ambient, and side-by-side render.</p>",
    ]
    for row in rows:
        title = html.escape(row["tag"])
        parts.append("<div class='row'>")
        parts.append(f"<h2>{title}</h2>")
        parts.append(
            "<div class='meta'>"
            f"white: {html.escape(row['white']['verdict']['summary'])}<br>"
            f"complement: {html.escape(row['complement']['verdict']['summary'])}"
            "</div>"
        )
        parts.append("<div class='grid'>")
        for key, label in [
            ("white_image", "white ambient"),
            ("complement_image", "complementary ambient"),
            ("side_by_side", "side by side"),
        ]:
            src = html.escape(row[key])
            parts.append(f"<figure><img src='{src}'><figcaption>{label}</figcaption></figure>")
        parts.append("</div></div>")
    parts.append("</body></html>")
    (out / "index.html").write_text("\n".join(parts))


def run_ambient_compare(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare white and complementary ambient lights")
    parser.add_argument("--in", dest="in_path", default="renders/families/crystal_field/catalog")
    parser.add_argument("--out", default="renders/families/crystal_field/ambient_compare")
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=540)
    parser.add_argument("--rays", type=int, default=2_000_000)
    parser.add_argument("--batch", type=int, default=200_000)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    in_path = Path(args.in_path)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    paths = _param_paths(in_path)
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print(f"No crystal-field parameter JSONs found under {in_path}")
        return

    rows = []
    for path in paths:
        tag = _tag(in_path, path)
        try:
            p = params_from_dict(Params, json.loads(path.read_text()))
        except Exception as exc:  # noqa: BLE001 - keep scanning mixed artifact dirs
            print(f"skip {path}: {exc}")
            continue

        white = out / f"{tag}.white.png"
        complement = out / f"{tag}.complement.png"
        side_by_side = out / f"{tag}.side_by_side.png"
        metrics = out / f"{tag}.metrics.json"

        print(tag)
        white_metrics = _render_variant(
            _with_white_ambient(p),
            white,
            width=args.width,
            height=args.height,
            rays=args.rays,
            batch=args.batch,
            depth=args.depth,
        )
        complement_metrics = _render_variant(
            _with_complementary_ambient(p, tag),
            complement,
            width=args.width,
            height=args.height,
            rays=args.rays,
            batch=args.batch,
            depth=args.depth,
        )
        _write_side_by_side(white, complement, side_by_side)

        payload = {"white": white_metrics, "complement": complement_metrics}
        metrics.write_text(json.dumps(payload, indent=2))
        rows.append(
            {
                "tag": tag,
                "white_image": white.name,
                "complement_image": complement.name,
                "side_by_side": side_by_side.name,
                "white": white_metrics,
                "complement": complement_metrics,
            }
        )

    _write_index(out, rows)
    print(f"Wrote {out / 'index.html'}")


if __name__ == "__main__":
    run_ambient_compare()
