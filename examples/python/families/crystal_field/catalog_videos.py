"""Render 2x2 video collages for all medium-grid catalog entries.

Each collage tiles 4 videos (960x540 each) into one 1920x1080 output.
Videos are grouped by material, with rows ordered by light color × n_lights.

Run::

    python -m examples.python.families.crystal_field catalog_videos
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

from anim import Camera2D, Shot, Timeline, render
from .catalog import (
    EXPOSURE_RANGE,
    _build_catalog_entries,
    _entry_tag,
    _entry_to_params,
    _search_good_params,
)
from .params import DURATION
from .scene import build


def run_catalog_videos(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field catalog video collages")
    parser.add_argument("--out", type=str, default="renders/families/crystal_field/catalog_videos")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    entries = _build_catalog_entries()
    medium = [e for e in entries if e["grid"] == "medium"]
    print(f"Medium entries: {len(medium)} → {len(medium) // 4} collages")

    shot = Shot.preset("preview", width=960, height=540, rays=2_000_000, depth=12)
    cam = Camera2D(center=[0, 0], width=3.2)

    # Group by material, then by shape
    for mat in ["glass", "dark", "colored_fill", "metallic_rough"]:
        mat_entries = [e for e in medium if e["mat"] == mat]
        mat_dir = out / mat
        mat_dir.mkdir(parents=True, exist_ok=True)

        # Render individual videos
        video_paths: list[Path] = []
        for e in mat_entries:
            tag = _entry_tag(e)
            video_path = mat_dir / f"{tag}.mp4"
            video_paths.append(video_path)

            if video_path.exists():
                print(f"  skip {mat}/{tag} (exists)", flush=True)
                continue

            p = _search_good_params(e)
            if p is None:
                print(f"  skip {mat}/{tag} (no valid params)", flush=True)
                continue

            animate = build(p)
            print(f"  rendering {mat}/{tag} exp={p.exposure:.2f} ...", flush=True)
            render(animate, DURATION, str(video_path), settings=shot, camera=cam, crf=18)

            # Save params
            json_path = video_path.with_suffix(".json")
            json_path.write_text(json.dumps(asdict(p), indent=2))

        # Build 2x2 collages from groups of 4
        for i in range(0, len(video_paths), 4):
            group = video_paths[i : i + 4]
            if len(group) < 4:
                continue

            collage_idx = i // 4 + 1
            collage_path = mat_dir / f"collage_{collage_idx}.mp4"

            if collage_path.exists():
                print(f"  skip collage {mat}/collage_{collage_idx} (exists)", flush=True)
                continue

            # Check all 4 videos exist
            if not all(v.exists() for v in group):
                print(f"  skip collage {mat}/collage_{collage_idx} (missing videos)", flush=True)
                continue

            cmd = [
                "ffmpeg", "-y",
                "-i", str(group[0]), "-i", str(group[1]),
                "-i", str(group[2]), "-i", str(group[3]),
                "-filter_complex",
                "[0:v][1:v]hstack=inputs=2[top];[2:v][3:v]hstack=inputs=2[bot];[top][bot]vstack=inputs=2[out]",
                "-map", "[out]",
                "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                str(collage_path),
            ]
            subprocess.run(cmd, capture_output=True)
            print(f"  collage {mat}/collage_{collage_idx}.mp4", flush=True)

    print("Done!")
