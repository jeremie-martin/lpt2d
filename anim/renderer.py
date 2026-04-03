"""Subprocess wrapper for lpt2d-cli --stream and output backends."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .stats import FrameStats, frame_stats
from .types import Camera2D, Frame, FrameContext, FrameReport, RenderSettings, Scene, Timeline

DEFAULT_BINARY = "./build/lpt2d-cli"


def _require_pipe(pipe, name: str):
    if pipe is None:
        raise RuntimeError(f"Subprocess {name} pipe is unavailable")
    return pipe


class Renderer:
    """Manages a persistent lpt2d-cli --stream subprocess."""

    last_report: FrameReport | None = None

    def __init__(self, settings: RenderSettings | None = None, binary: str = DEFAULT_BINARY):
        if settings is None:
            settings = RenderSettings()
        self.width = settings.width
        self.height = settings.height
        self.frame_bytes = settings.width * settings.height * 3
        cmd = [
            binary,
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
        cmd.extend(["--normalize", settings.normalize])
        if settings.normalize_ref > 0:
            cmd.extend(["--normalize-ref", str(settings.normalize_ref)])
        if settings.normalize_pct < 1.0:
            cmd.extend(["--normalize-pct", str(settings.normalize_pct)])
        self._proc: subprocess.Popen[bytes] | None = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def render_frame(self, wire_json: str) -> bytes:
        """Send wire-format JSON, receive raw RGB8 pixels.

        After each call, ``self.last_report`` holds the structured
        :class:`FrameReport` parsed from the C++ renderer's stderr.
        """
        proc = self._proc
        if proc is None:
            raise RuntimeError("Renderer process is not running")
        stdin = _require_pipe(proc.stdin, "stdin")
        stdout = _require_pipe(proc.stdout, "stdout")
        stderr = _require_pipe(proc.stderr, "stderr")
        stdin.write((wire_json + "\n").encode())
        stdin.flush()

        data = stdout.read(self.frame_bytes)
        if len(data) != self.frame_bytes:
            raise RuntimeError(f"Renderer died after {len(data)}/{self.frame_bytes} bytes")

        # Parse structured metadata from stderr (one line per frame).
        # Format: "frame N: {JSON}\n"
        self.last_report = None
        line = stderr.readline().decode(errors="replace").strip()
        if line:
            colon_pos = line.find(": {")
            if colon_pos >= 0:
                try:
                    meta = json.loads(line[colon_pos + 2 :])
                    # Extract frame index from "frame N:" prefix
                    prefix = line[:colon_pos]
                    frame_idx = int(prefix.split()[-1]) if prefix.split() else 0
                    self.last_report = FrameReport(
                        frame=frame_idx,
                        rays=meta.get("rays", 0),
                        time_ms=meta.get("time_ms", 0),
                        max_hdr=meta.get("max_hdr", 0.0),
                        total_rays=meta.get("total_rays", 0),
                    )
                except (json.JSONDecodeError, ValueError):
                    pass

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


def _save_image(path: str, rgb: bytes, width: int, height: int) -> None:
    """Save raw RGB8 pixels to an image file.  Format inferred from extension.

    ``.ppm`` uses the fast built-in writer (no dependencies).
    Everything else (``.png``, ``.jpg``, ...) uses Pillow.
    """
    if path.lower().endswith(".ppm"):
        with open(path, "wb") as f:
            f.write(f"P6\n{width} {height}\n255\n".encode())
            f.write(rgb)
    else:
        from PIL import Image

        Image.frombytes("RGB", (width, height), rgb).save(path)


class PpmOutput:
    """Saves individual PPM frames to a directory."""

    def __init__(self, directory: str, width: int, height: int):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._width = width
        self._height = height
        self._frame = 0

    def write_frame(self, rgb_data: bytes):
        path = str(self._dir / f"frame_{self._frame:06d}.ppm")
        _save_image(path, rgb_data, self._width, self._height)
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


# --- Helpers ---

AnimateFn = Callable[[FrameContext], Scene | Frame]


def _resolve_args(
    timeline: Timeline | float, settings: RenderSettings | str | None
) -> tuple[Timeline, RenderSettings]:
    if isinstance(timeline, (int, float)):
        timeline = Timeline(duration=float(timeline))
    if settings is None:
        settings = RenderSettings()
    elif isinstance(settings, str):
        settings = RenderSettings.preset(settings)
    return timeline, settings


def render(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    settings: RenderSettings | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
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
        binary: Path to lpt2d-cli executable.
        codec: Video codec (default: libx264).
        crf: Video quality (default: 18, visually lossless).
        start: Start time in seconds (skip earlier frames).
        end: End time in seconds (default: full duration).
        stride: Render every Nth frame (default: 1 = all frames).
        frame: Render a single frame by index. Overrides start/end/stride.
    """
    timeline, settings = _resolve_args(timeline, settings)
    width, height, aspect = settings.width, settings.height, settings.aspect

    # Choose output backend
    if output.endswith("/") or (Path(output).exists() and Path(output).is_dir()):
        out: FFmpegOutput | PpmOutput = PpmOutput(output, width, height)
    else:
        out = FFmpegOutput(output, width, height, timeline.fps, codec, crf)

    renderer = Renderer(settings, binary=binary)

    def _render_frame(i: int) -> bytes:
        ctx = timeline.context_at(i)
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, aspect)
        return renderer.render_frame(wire)

    try:
        if frame is not None:
            # Single-frame mode
            out.write_frame(_render_frame(frame))
            rpt = renderer.last_report
            ms = f", {rpt.time_ms}ms" if rpt else ""
            sys.stderr.write(f"frame {frame} ({timeline.time_at(frame):.2f}s{ms})\n")
        else:
            # Range mode
            start_frame = int(start * timeline.fps)
            end_frame = int(end * timeline.fps) if end is not None else timeline.total_frames
            end_frame = min(end_frame, timeline.total_frames)

            frames = range(start_frame, end_frame, stride)
            total = len(frames)

            for idx, i in enumerate(frames):
                out.write_frame(_render_frame(i))
                rpt = renderer.last_report
                ms = f" {rpt.time_ms}ms" if rpt else ""
                sys.stderr.write(f"\rframe {idx + 1}/{total} ({timeline.time_at(i):.2f}s{ms})")
                sys.stderr.flush()
            sys.stderr.write("\n")
    finally:
        out.close()
        renderer.close()


# --- Convenience functions ---


def render_still(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    frame: int = 0,
    settings: RenderSettings | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
) -> None:
    """Render a single frame to an image file.

    Args:
        animate: Callback receiving FrameContext, returning Scene or Frame.
        timeline: Timeline object, or duration in seconds.
        output: Output image path (.png, .ppm, .jpg, ...).
        frame: Frame index to render (default: 0).
        settings: RenderSettings, preset name, or None for defaults.
        camera: Session-level camera.
        binary: Path to lpt2d-cli executable.
    """
    timeline, settings = _resolve_args(timeline, settings)

    renderer = Renderer(settings, binary=binary)
    try:
        ctx = timeline.context_at(frame)
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, settings.aspect)
        rgb = renderer.render_frame(wire)
        _save_image(output, rgb, settings.width, settings.height)
        sys.stderr.write(f"wrote {output} ({settings.width}x{settings.height}, frame {frame})\n")
    finally:
        renderer.close()


def render_contact_sheet(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    cols: int = 4,
    count: int = 16,
    settings: RenderSettings | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
) -> None:
    """Render a grid of frames spread across the timeline.

    Intended for human visual inspection during look development.
    For automated/agent workflows, use frame_stats() instead.

    Args:
        animate: Callback receiving FrameContext, returning Scene or Frame.
        timeline: Timeline object, or duration in seconds.
        output: Output image path (.png, .ppm, .jpg, ...).
        cols: Number of columns in the grid (default: 4).
        count: Total number of frames to sample (default: 16).
        settings: RenderSettings, preset name, or None for defaults.
        camera: Session-level camera.
        binary: Path to lpt2d-cli executable.
    """
    timeline, settings = _resolve_args(timeline, settings)

    w, h = settings.width, settings.height
    rows = math.ceil(count / cols)
    sheet_w = w * cols
    sheet_h = h * rows

    # Sample frames evenly across timeline
    total = timeline.total_frames
    indices = [round(i * (total - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]

    renderer = Renderer(settings, binary=binary)
    try:
        frames_rgb: list[bytes] = []
        for idx, fi in enumerate(indices):
            ctx = timeline.context_at(fi)
            result = animate(ctx)
            f = result if isinstance(result, Frame) else Frame(scene=result)
            wire = _build_wire_json(f, camera, settings.aspect)
            frames_rgb.append(renderer.render_frame(wire))
            sys.stderr.write(f"\rcontact sheet: {idx + 1}/{count}")
            sys.stderr.flush()
        sys.stderr.write("\n")
    finally:
        renderer.close()

    # Assemble grid
    sheet = bytearray(sheet_w * sheet_h * 3)
    for idx, rgb in enumerate(frames_rgb):
        col = idx % cols
        row = idx // cols
        for y in range(h):
            src_off = y * w * 3
            dst_off = ((row * h + y) * sheet_w + col * w) * 3
            sheet[dst_off : dst_off + w * 3] = rgb[src_off : src_off + w * 3]

    _save_image(output, bytes(sheet), sheet_w, sheet_h)
    sys.stderr.write(f"wrote {output} ({sheet_w}x{sheet_h}, {count} frames, {cols}x{rows} grid)\n")


def render_stats(
    animate: AnimateFn,
    timeline: Timeline | float,
    *,
    frames: list[int] | int | None = None,
    count: int = 8,
    settings: RenderSettings | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
) -> list[tuple[int, float, FrameStats]]:
    """Render frames and return their statistics. No file output.

    Returns a list of (frame_index, time, FrameStats) tuples.
    Designed for automated workflows and agent-driven analysis.

    Args:
        animate: Callback receiving FrameContext, returning Scene or Frame.
        timeline: Timeline object, or duration in seconds.
        frames: Specific frame indices to render. An int renders that single frame.
                None samples `count` frames evenly across the timeline.
        count: Number of frames to sample when `frames` is None (default: 8).
        settings: RenderSettings, preset name, or None for defaults.
        camera: Session-level camera.
        binary: Path to lpt2d-cli executable.
    """
    timeline, settings = _resolve_args(timeline, settings)

    # Resolve frame indices
    total = timeline.total_frames
    if frames is None:
        indices = [round(i * (total - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
    elif isinstance(frames, int):
        indices = [frames]
    else:
        indices = list(frames)

    w, h = settings.width, settings.height
    aspect = settings.aspect

    renderer = Renderer(settings, binary=binary)
    results: list[tuple[int, float, FrameStats]] = []
    try:
        for fi in indices:
            ctx = timeline.context_at(fi)
            result = animate(ctx)
            f = result if isinstance(result, Frame) else Frame(scene=result)
            wire = _build_wire_json(f, camera, aspect)
            rgb = renderer.render_frame(wire)
            results.append((fi, ctx.time, frame_stats(rgb, w, h)))
    finally:
        renderer.close()
    return results


def calibrate_normalize_ref(
    animate: AnimateFn,
    timeline: Timeline | float,
    *,
    settings: RenderSettings | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
    frame: int = 0,
) -> float:
    """Render one frame with max-normalize to determine a good normalize_ref.

    Uses the standard :class:`Renderer` with ``normalize="max"`` to capture
    the HDR peak from the :class:`FrameReport` metadata.
    The returned value can be used as ``RenderSettings(normalize="fixed",
    normalize_ref=...)`` for temporally stable animation renders.

    Args:
        animate: Callback receiving FrameContext, returning Scene or Frame.
        timeline: Timeline object, or duration in seconds.
        settings: RenderSettings, preset name, or None for defaults.
        camera: Session-level camera.
        binary: Path to lpt2d-cli executable.
        frame: Frame index to calibrate on (default: 0).

    Returns:
        The HDR max value suitable for use as ``normalize_ref``.
    """
    timeline, settings = _resolve_args(timeline, settings)

    # Force max mode so the C++ renderer computes and reports true HDR peak.
    cal_settings = replace(settings, normalize="max", normalize_pct=1.0)

    renderer = Renderer(cal_settings, binary=binary)
    try:
        ctx = timeline.context_at(frame)
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, cal_settings.aspect)
        renderer.render_frame(wire)  # discard pixels, we want the report

        rpt = renderer.last_report
        if rpt is None or rpt.max_hdr <= 0:
            raise RuntimeError("Calibration failed: no max_hdr in renderer report")
        return rpt.max_hdr
    finally:
        renderer.close()
