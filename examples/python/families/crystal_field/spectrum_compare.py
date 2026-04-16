"""Compare legacy range spectra against fitted color spectra for crystal-field shots.

Example:

    python -m examples.python.families.crystal_field spectrum_compare \
        --in renders/lpt2d_crystal_field_catalog_replay_20260411 \
        --out renders/lpt2d_crystal_field_spectrum_compare_20260411 \
        --width 1920 --height 1080 --rays 10000000
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

CLI = Path("build/lpt2d-cli")


def _shot_paths(root: Path) -> list[Path]:
    return sorted(root.rglob("*orange*.shot.json"))


def _tag(root: Path, path: Path) -> str:
    rel = path.relative_to(root)
    stem = rel.name.removesuffix(".shot.json")
    return "__".join([*rel.parent.parts, stem])


def _render(
    shot: Path,
    output: Path,
    *,
    width: int,
    height: int,
    rays: int,
    batch: int,
    depth: int,
    convert: bool,
) -> None:
    cmd = [
        str(CLI),
        "--scene",
        str(shot),
        "--output",
        str(output),
        "--width",
        str(width),
        "--height",
        str(height),
        "--rays",
        str(rays),
        "--batch",
        str(batch),
        "--depth",
        str(depth),
    ]
    if convert:
        cmd.extend(["--convert-light-spectrum", "range-to-color"])
    subprocess.run(cmd, check=True)


def _metrics_and_diff(exact_path: Path, converted_path: Path, diff_path: Path) -> dict:
    exact = np.asarray(Image.open(exact_path).convert("RGB"), dtype=np.int16)
    converted = np.asarray(Image.open(converted_path).convert("RGB"), dtype=np.int16)
    diff = np.abs(exact - converted)
    diff_image = np.clip(diff * 4, 0, 255).astype(np.uint8)
    Image.fromarray(diff_image, "RGB").save(diff_path)
    return {
        "mean_abs_diff": float(np.mean(diff)),
        "p95_abs_diff": float(np.percentile(diff, 95)),
        "max_abs_diff": int(np.max(diff)),
    }


def _write_index(out: Path, rows: list[dict]) -> None:
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Crystal Field Spectrum Comparison</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:24px;background:#111;color:#eee}",
        ".row{margin:0 0 28px}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}",
        "img{width:100%;height:auto}.meta{color:#aaa;font-size:14px;margin:6px 0 10px}",
        "h2{font-size:18px;margin:0 0 4px}a{color:#9cf}",
        "</style></head><body>",
        "<h1>Crystal Field Spectrum Comparison</h1>",
        "<p>Exact legacy range, fitted color spectrum, and amplified absolute difference.</p>",
    ]
    for row in rows:
        title = html.escape(row["tag"])
        parts.append("<div class='row'>")
        parts.append(f"<h2>{title}</h2>")
        parts.append(
            "<div class='meta'>"
            f"mean diff {row['metrics']['mean_abs_diff']:.2f}, "
            f"p95 {row['metrics']['p95_abs_diff']:.2f}, "
            f"max {row['metrics']['max_abs_diff']}"
            "</div>"
        )
        parts.append("<div class='grid'>")
        for key, label in [("exact", "exact range"), ("converted", "converted color"), ("diff", "diff x4")]:
            src = html.escape(row[key])
            parts.append(f"<figure><img src='{src}'><figcaption>{label}</figcaption></figure>")
        parts.append("</div></div>")
    parts.append("</body></html>")
    (out / "index.html").write_text("\n".join(parts))


def run_spectrum_compare(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Compare range and fitted-color light spectra")
    parser.add_argument("--in", dest="in_dir", default="renders/lpt2d_crystal_field_catalog_replay_20260411")
    parser.add_argument("--out", default="renders/lpt2d_crystal_field_spectrum_compare")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--rays", type=int, default=10_000_000)
    parser.add_argument("--batch", type=int, default=200_000)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    in_dir = Path(args.in_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    paths = _shot_paths(in_dir)
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print(f"No orange shot JSONs found under {in_dir}")
        return

    rows = []
    for shot in paths:
        tag = _tag(in_dir, shot)
        exact = out / f"{tag}.exact.png"
        converted = out / f"{tag}.converted.png"
        diff = out / f"{tag}.diff.png"
        metrics_path = out / f"{tag}.metrics.json"

        print(f"{tag}")
        if not exact.exists():
            _render(shot, exact, width=args.width, height=args.height, rays=args.rays,
                    batch=args.batch, depth=args.depth, convert=False)
        if not converted.exists():
            _render(shot, converted, width=args.width, height=args.height, rays=args.rays,
                    batch=args.batch, depth=args.depth, convert=True)
        metrics = _metrics_and_diff(exact, converted, diff)
        metrics_path.write_text(json.dumps(metrics, indent=2))
        rows.append({
            "tag": tag,
            "exact": exact.name,
            "converted": converted.name,
            "diff": diff.name,
            "metrics": metrics,
        })

    _write_index(out, rows)
    print(f"Wrote {out / 'index.html'}")


if __name__ == "__main__":
    run_spectrum_compare()
