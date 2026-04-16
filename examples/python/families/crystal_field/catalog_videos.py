"""Render 2x2 video collages for all medium-grid catalog entries.

Each collage tiles up to 4 videos (960x540 each) into one 1920x1080 output.
Partial final groups are padded with black tiles so no catalog entries are dropped.
Videos are grouped by material, with rows ordered by light color × n_lights.

Run::

    python -m examples.python.families.crystal_field catalog_videos
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from dataclasses import asdict
from pathlib import Path

from anim import Camera2D, Shot, render

from .catalog import (
    _build_catalog_entries,
    _entry_tag,
    _find_good_params,
)
from .params import DURATION
from .scene import build

_TILE_WIDTH = 960
_TILE_HEIGHT = 540
_COLLAGE_SIZE = 4
_VIDEO_FPS = 30


def _collage_groups(video_paths: list[Path], size: int = _COLLAGE_SIZE) -> list[list[Path]]:
    return [video_paths[i : i + size] for i in range(0, len(video_paths), size)]


def _collage_cmd(group: list[Path], output: Path) -> list[str]:
    cmd = ["ffmpeg", "-y"]
    labels: list[str] = []
    for idx, path in enumerate(group):
        cmd.extend(["-i", str(path)])
        labels.append(f"[{idx}:v]")

    while len(labels) < _COLLAGE_SIZE:
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                (
                    f"color=c=black:s={_TILE_WIDTH}x{_TILE_HEIGHT}:"
                    f"d={DURATION}:r={_VIDEO_FPS}"
                ),
            ]
        )
        labels.append(f"[{len(labels)}:v]")

    filter_complex = (
        f"{labels[0]}{labels[1]}hstack=inputs=2[top];"
        f"{labels[2]}{labels[3]}hstack=inputs=2[bot];"
        "[top][bot]vstack=inputs=2[out]"
    )
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(output),
        ]
    )
    return cmd


def run_catalog_videos(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Crystal field catalog video collages")
    parser.add_argument("--out", type=str, default="renders/families/crystal_field/catalog_videos")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    entries = _build_catalog_entries()
    medium = [e for e in entries if e["grid"] == "medium"]
    outcome_order = [
        "glass",
        "black_diffuse",
        "gray_diffuse",
        "colored_diffuse",
        "brushed_metal",
    ]
    total_collages = sum(
        len(_collage_groups([e for e in medium if e["outcome"] == outcome]))
        for outcome in outcome_order
    )
    print(f"Medium entries: {len(medium)} → {total_collages} collages")

    shot = Shot.preset("preview", width=_TILE_WIDTH, height=_TILE_HEIGHT, rays=2_000_000, depth=12)
    cam = Camera2D(center=[0, 0], width=3.2)

    # Group by outcome, then render videos + 2x2 collages.
    for outcome in outcome_order:
        outcome_entries = [e for e in medium if e["outcome"] == outcome]
        outcome_dir = out / outcome
        outcome_dir.mkdir(parents=True, exist_ok=True)

        # Render individual videos
        video_paths: list[Path] = []
        for e in outcome_entries:
            tag = _entry_tag(e)
            video_path = outcome_dir / f"{tag}.mp4"
            video_paths.append(video_path)

            if video_path.exists():
                print(f"  skip {outcome}/{tag} (exists)", flush=True)
                continue

            entry_rng = random.Random(f"videos:{outcome}/{tag}")
            p, result = _find_good_params(e, entry_rng)

            animate = build(p)
            status = "OK" if result.verdict.ok else "FAIL"
            print(
                f"  rendering {outcome}/{tag} {status} exp={p.look.exposure:.2f} ...",
                flush=True,
            )
            render(animate, DURATION, str(video_path), settings=shot, camera=cam, crf=18)

            # Save params
            json_path = video_path.with_suffix(".json")
            json_path.write_text(json.dumps(asdict(p), indent=2))

        # Build 2x2 collages from groups of up to 4, padding any short final group.
        for collage_idx, group in enumerate(_collage_groups(video_paths), start=1):
            collage_path = outcome_dir / f"collage_{collage_idx}.mp4"

            if collage_path.exists():
                print(f"  skip collage {outcome}/collage_{collage_idx} (exists)", flush=True)
                continue

            # Check the real videos exist; any remaining slots will be black pads.
            if not all(v.exists() for v in group):
                print(
                    f"  skip collage {outcome}/collage_{collage_idx} (missing videos)", flush=True
                )
                continue

            cmd = _collage_cmd(group, collage_path)
            subprocess.run(cmd, capture_output=True)
            print(f"  collage {outcome}/collage_{collage_idx}.mp4", flush=True)

    print("Done!")
