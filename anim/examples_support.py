from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from .renderer import render, render_still
from .types import Frame, FrameContext, Scene, Shot, Timeline


AnimateFn = Callable[[FrameContext], Scene | Frame]
SettingsFn = Callable[[str], Shot]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = REPO_ROOT / "build" / "lpt2d-cli"


def parse_example_args(
    argv: list[str] | None = None,
    *,
    description: str | None,
    default_binary: Path = DEFAULT_BINARY,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--hq", action="store_true", help="render the HQ variant")
    parser.add_argument("--frame", type=int, help="render a still frame instead of a video")
    parser.add_argument("--output", type=Path, help="explicit output path")
    parser.add_argument("--fast", action="store_true", help="pass --fast to the CLI renderer")
    parser.add_argument("--binary", type=Path, default=default_binary, help="path to lpt2d-cli")
    return parser.parse_args(argv)


def run_example(
    *,
    name: str,
    duration: float,
    make_settings: SettingsFn,
    animate: AnimateFn,
    argv: list[str] | None = None,
    description: str | None = None,
    preview_fps: int = 30,
    hq_fps: int = 60,
    preview_crf: int = 18,
    hq_crf: int = 16,
) -> None:
    args = parse_example_args(argv, description=description)
    mode = "hq" if args.hq else "preview"
    settings = make_settings(mode)
    timeline = Timeline(duration, fps=hq_fps if args.hq else preview_fps)

    if args.frame is not None:
        output = args.output or (REPO_ROOT / f"{name}_{mode}_{args.frame:04d}.png")
        render_still(
            animate,
            timeline,
            str(output),
            frame=args.frame,
            settings=settings,
            binary=str(args.binary),
            fast=args.fast,
        )
        return

    output = args.output or (REPO_ROOT / f"{name}_{mode}.mp4")
    render(
        animate,
        timeline,
        str(output),
        settings=settings,
        binary=str(args.binary),
        fast=args.fast,
        crf=hq_crf if args.hq else preview_crf,
    )
