"""Subprocess wrapper for lpt2d-cli --stream and output backends."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .types import Camera2D, Frame, FrameContext, RenderSettings, Scene, Timeline


def _require_pipe(pipe, name: str):
    if pipe is None:
        raise RuntimeError(f"Subprocess {name} pipe is unavailable")
    return pipe


class Renderer:
    """Manages a persistent lpt2d-cli --stream subprocess."""

    def __init__(self, settings: RenderSettings | None = None):
        if settings is None:
            settings = RenderSettings()
        self.width = settings.width
        self.height = settings.height
        self.frame_bytes = settings.width * settings.height * 3
        cmd = [
            settings.binary,
            "--stream",
            "--width",
            str(settings.width),
            "--height",
            str(settings.height),
            "--rays",
            str(settings.rays),
            "--batch",
            str(settings.batch),
            "--depth",
            str(settings.depth),
            "--exposure",
            str(settings.exposure),
            "--contrast",
            str(settings.contrast),
            "--gamma",
            str(settings.gamma),
            "--tonemap",
            settings.tonemap,
            "--white-point",
            str(settings.white_point),
        ]
        if not settings.normalize:
            cmd.append("--no-normalize")
        self._proc: subprocess.Popen[bytes] | None = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
        )

    def render_frame(self, wire_json: str) -> bytes:
        """Send wire-format JSON, receive raw RGB8 pixels."""
        proc = self._proc
        if proc is None:
            raise RuntimeError("Renderer process is not running")
        stdin = _require_pipe(proc.stdin, "stdin")
        stdout = _require_pipe(proc.stdout, "stdout")
        stdin.write((wire_json + "\n").encode())
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
            stderr=subprocess.PIPE,
        )

    def write_frame(self, rgb_data: bytes):
        proc = self._proc
        if proc is None:
            raise RuntimeError("FFmpeg process is not running")
        _require_pipe(proc.stdin, "stdin").write(rgb_data)

    def close(self):
        if self._proc and self._proc.poll() is None:
            stdin = _require_pipe(self._proc.stdin, "stdin")
            stdin.close()
            # communicate() flushes stdin when the handle is still attached.
            # Detach it after closing so final stderr draining works on Python 3.13.
            self._proc.stdin = None
            _, err = self._proc.communicate()
            if self._proc.returncode != 0 and err:
                sys.stderr.write(
                    f"ffmpeg failed (exit {self._proc.returncode}): {err.decode(errors='replace')}\n"
                )
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


# --- Wire format bridge ---


def _build_wire_json(frame: Frame, session_camera: Camera2D | None, aspect: float) -> str:
    """Serialize a Frame into the wire-format JSON that C++ expects."""
    d = frame.scene.to_dict()

    render_block: dict = {}

    # Camera: per-frame overrides session-level
    effective_camera = frame.camera if frame.camera is not None else session_camera
    if effective_camera is not None:
        bounds = effective_camera.resolve(aspect)
        if bounds is not None:
            render_block["bounds"] = bounds

    # Per-frame render overrides
    if frame.render is not None:
        render_block.update(frame.render.to_dict())

    if render_block:
        d["render"] = render_block

    return json.dumps(d, separators=(",", ":"))


# --- Main render function ---

AnimateFn = Callable[[FrameContext], Scene | Frame]


def render(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    settings: RenderSettings | str | None = None,
    camera: Camera2D | None = None,
    codec: str = "libx264",
    crf: int = 18,
    start: float = 0.0,
    end: float | None = None,
    stride: int = 1,
    frame: int | None = None,
) -> None:
    """Render an animation to video or image sequence.

    Args:
        animate: Callback receiving FrameContext, returning Scene or Frame.
        timeline: Timeline object, or duration in seconds (uses fps=30).
        output: Output path. .mp4/.webm/.mkv -> video via ffmpeg.
                Trailing / or directory -> PPM sequence.
        settings: RenderSettings, Quality preset name (str), or None for defaults.
        camera: Session-level camera. Per-frame Frame.camera overrides this.
        codec: Video codec (default: libx264).
        crf: Video quality (default: 18, visually lossless).
        start: Start time in seconds (skip earlier frames).
        end: End time in seconds (default: full duration).
        stride: Render every Nth frame (default: 1 = all frames).
        frame: Render a single frame by index. Overrides start/end/stride.
    """
    # Resolve timeline
    if isinstance(timeline, (int, float)):
        timeline = Timeline(duration=float(timeline))

    # Resolve settings
    if settings is None:
        settings = RenderSettings()
    elif isinstance(settings, str):
        settings = RenderSettings.preset(settings)

    width = settings.width
    height = settings.height
    aspect = settings.aspect

    # Choose output backend
    if output.endswith("/") or (Path(output).exists() and Path(output).is_dir()):
        out: FFmpegOutput | PpmOutput = PpmOutput(output, width, height)
    else:
        out = FFmpegOutput(output, width, height, timeline.fps, codec, crf)

    renderer = Renderer(settings)

    def _render_frame(i: int) -> bytes:
        ctx = FrameContext(
            frame=i,
            time=timeline.time_at(i),
            progress=timeline.progress_at(i),
            fps=timeline.fps,
            dt=timeline.dt,
            total_frames=timeline.total_frames,
            duration=timeline.duration,
        )
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, aspect)
        return renderer.render_frame(wire)

    try:
        if frame is not None:
            # Single-frame mode
            out.write_frame(_render_frame(frame))
            sys.stderr.write(f"frame {frame} ({timeline.time_at(frame):.2f}s)\n")
        else:
            # Range mode
            start_frame = int(start * timeline.fps)
            end_frame = int(end * timeline.fps) if end is not None else timeline.total_frames
            end_frame = min(end_frame, timeline.total_frames)

            frames = range(start_frame, end_frame, stride)
            total = len(frames)

            for idx, i in enumerate(frames):
                out.write_frame(_render_frame(i))
                sys.stderr.write(f"\rframe {idx + 1}/{total} ({timeline.time_at(i):.2f}s)")
                sys.stderr.flush()
            sys.stderr.write("\n")
    finally:
        out.close()
        renderer.close()
