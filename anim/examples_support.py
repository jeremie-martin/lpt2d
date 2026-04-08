from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from .renderer import render, render_still
from .types import (
    Frame,
    FrameContext,
    Scene,
    Shot,
    Timeline,
    _apply_look_override,
    _apply_trace_override,
)

AnimateFn = Callable[[FrameContext], Scene | Frame]
SettingsFn = Callable[[str], Shot]

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_example_args(
    argv: list[str] | None = None,
    *,
    description: str | None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--hq", action="store_true", help="render the HQ variant")
    parser.add_argument("--frame", type=int, help="render a still frame instead of a video")
    parser.add_argument("--output", type=Path, help="explicit output path")
    parser.add_argument("--save-json", type=Path, help="optional authored shot export path")
    parser.add_argument("--fast", action="store_true", help="pass --fast to the renderer")
    parser.add_argument(
        "--binary",
        type=Path,
        help="accepted for compatibility with legacy example harnesses; ignored by in-process rendering",
    )
    return parser.parse_args(argv)


def _scene_is_empty(scene: Scene) -> bool:
    return (
        len(scene.shapes) == 0
        and len(scene.lights) == 0
        and len(scene.groups) == 0
        and len(scene.materials) == 0
    )


def _authored_shot(settings: Shot, animate: AnimateFn, ctx: FrameContext) -> Shot:
    result = animate(ctx)
    frame = result if isinstance(result, Frame) else Frame(scene=result)
    scene = frame.scene if not _scene_is_empty(frame.scene) else settings.scene
    return Shot(
        name=settings.name,
        scene=scene,
        camera=frame.camera or settings.camera,
        canvas=settings.canvas,
        look=_apply_look_override(settings.look, frame.look),
        trace=_apply_trace_override(settings.trace, frame.trace),
    )


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

    if args.save_json is not None:
        frame_number = args.frame if args.frame is not None else 0
        authored = _authored_shot(settings, animate, timeline.context_at(frame_number))
        authored.save(args.save_json)
        print(f"saved {args.save_json}")
        return

    if args.frame is not None:
        output = args.output or (REPO_ROOT / f"{name}_{mode}_{args.frame:04d}.png")
        render_still(
            animate,
            timeline,
            str(output),
            frame=args.frame,
            settings=settings,
            fast=args.fast,
        )
        return

    output = args.output or (REPO_ROOT / f"{name}_{mode}.mp4")
    render(
        animate,
        timeline,
        str(output),
        settings=settings,
        fast=args.fast,
        crf=hq_crf if args.hq else preview_crf,
    )
