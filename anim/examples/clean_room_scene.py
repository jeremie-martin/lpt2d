"""Render a named clean-room animation from the registry."""

from __future__ import annotations

import argparse
from pathlib import Path

from anim.examples._clean_room_registry import SCENE_MAP
from anim.examples._clean_room_shared import DEFAULT_OUTDIR, process_scene


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__ or "Render a named clean-room animation.")
    parser.add_argument("name", help="scene name from the clean-room registry")
    parser.add_argument("--sheet", action="store_true", help="render a contact sheet instead of video")
    parser.add_argument("--hq", action="store_true", help="render the HQ video variant")
    parser.add_argument("--duration", type=float, help="override duration in seconds")
    parser.add_argument("--rays", type=int, help="override ray count")
    parser.add_argument("--batch", type=int, help="override batch size")
    parser.add_argument("--depth", type=int, help="override max depth")
    parser.add_argument("--fps", type=int, help="override fps")
    parser.add_argument("--width", type=int, help="override render width")
    parser.add_argument("--height", type=int, help="override render height")
    parser.add_argument("--exposure", type=float, help="explicit exposure override")
    parser.add_argument("--skip-tune", action="store_true", help="skip exposure tuning")
    parser.add_argument("--export-json", action="store_true", help="export a representative frame JSON")
    parser.add_argument("--frame", type=int, default=0, help="frame index for JSON export")
    parser.add_argument("--no-render", action="store_true", help="skip image/video rendering")
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR, help="output root override")
    args = parser.parse_args()

    spec = SCENE_MAP.get(args.name)
    if spec is None:
        available = ", ".join(sorted(SCENE_MAP))
        raise SystemExit(f"unknown scene '{args.name}'. available: {available}")

    process_scene(spec, args, gallery=False)


if __name__ == "__main__":
    main()
