"""Subprocess wrapper for lpt2d-cli --stream and ffmpeg output."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

from .types import Scene


def _require_pipe(pipe, name: str):
    if pipe is None:
        raise RuntimeError(f"Subprocess {name} pipe is unavailable")
    return pipe


class Renderer:
    """Manages a persistent lpt2d-cli --stream subprocess."""

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        rays: int = 10_000_000,
        batch: int = 200_000,
        depth: int = 12,
        exposure: float = 2.0,
        contrast: float = 1.0,
        gamma: float = 2.2,
        tonemap: str = "aces",
        white_point: float = 1.0,
        binary: str = "./build/lpt2d-cli",
    ):
        self.width = width
        self.height = height
        self.frame_bytes = width * height * 3
        self._proc: subprocess.Popen[bytes] | None = subprocess.Popen(
            [
                binary,
                "--stream",
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
                "--exposure",
                str(exposure),
                "--contrast",
                str(contrast),
                "--gamma",
                str(gamma),
                "--tonemap",
                tonemap,
                "--white-point",
                str(white_point),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )

    def render_frame(self, scene: Scene) -> bytes:
        """Send scene JSON, receive raw RGB8 pixels."""
        proc = self._proc
        if proc is None:
            raise RuntimeError("Renderer process is not running")
        stdin = _require_pipe(proc.stdin, "stdin")
        stdout = _require_pipe(proc.stdout, "stdout")
        stdin.write((scene.to_json() + "\n").encode())
        stdin.flush()

        data = stdout.read(self.frame_bytes)
        if len(data) != self.frame_bytes:
            raise RuntimeError(f"Renderer died after {len(data)}/{self.frame_bytes} bytes")
        return data

    def close(self):
        if self._proc and self._proc.poll() is None:
            _require_pipe(self._proc.stdin, "stdin").close()
            self._proc.wait()
        self._proc = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FFmpegOutput:
    """Pipes raw RGB frames to ffmpeg for video encoding."""

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        fps: int = 30,
        codec: str = "libx264",
        crf: int = 18,
    ):
        self._proc = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                f"{width}x{height}",
                "-r",
                str(fps),
                "-i",
                "pipe:0",
                "-c:v",
                codec,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                path,
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def write_frame(self, rgb_data: bytes):
        proc = self._proc
        if proc is None:
            raise RuntimeError("FFmpeg process is not running")
        _require_pipe(proc.stdin, "stdin").write(rgb_data)

    def close(self):
        if self._proc and self._proc.poll() is None:
            _require_pipe(self._proc.stdin, "stdin").close()
            self._proc.wait()
        self._proc = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class PpmOutput:
    """Saves individual PPM frames to a directory."""

    def __init__(self, directory: str, width: int, height: int):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._width = width
        self._height = height
        self._frame = 0

    def write_frame(self, rgb_data: bytes):
        # Use raw PPM (universally readable, no dependencies)
        path = self._dir / f"frame_{self._frame:06d}.ppm"
        with open(path, "wb") as f:
            f.write(f"P6\n{self._width} {self._height}\n255\n".encode())
            f.write(rgb_data)
        self._frame += 1

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def render(
    animate_fn: Callable[[float], Scene],
    duration: float,
    output: str,
    fps: int = 30,
    **renderer_kwargs,
):
    """Render an animation to video or image sequence.

    Args:
        animate_fn: Function mapping time (seconds) to a Scene.
        duration: Total animation duration in seconds.
        output: Output path. Ending in .mp4/.webm/.mkv → video via ffmpeg.
                Ending in / or being a directory → PNG sequence.
        fps: Frames per second.
        **renderer_kwargs: Passed to Renderer (width, height, rays, etc.)
    """
    width = renderer_kwargs.get("width", 1920)
    height = renderer_kwargs.get("height", 1080)

    total_frames = int(duration * fps)

    # Choose output backend
    if output.endswith("/") or (Path(output).exists() and Path(output).is_dir()):
        out = PpmOutput(output, width, height)
    else:
        out = FFmpegOutput(output, width, height, fps)

    renderer = Renderer(**renderer_kwargs)
    try:
        for i in range(total_frames):
            t = i / fps
            scene = animate_fn(t)
            rgb = renderer.render_frame(scene)
            out.write_frame(rgb)
            sys.stderr.write(f"\rframe {i + 1}/{total_frames} ({t:.2f}s)")
            sys.stderr.flush()
        sys.stderr.write("\n")
    finally:
        out.close()
        renderer.close()
