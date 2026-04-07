"""In-process rendering via C++ RenderSession and output backends."""

from __future__ import annotations

import math
import subprocess
import sys
import time
import warnings
from pathlib import Path

import _lpt2d

from .stats import (
    FrameStats,
    QualityGate,
    check_quality,
    frame_stats_from_report,
)
from .types import (
    AnimateFn,
    Camera2D,
    Frame,
    FrameReport,
    Quality,
    RenderSession,
    Scene,
    Shot,
    Timeline,
    _apply_look_override,
    _apply_trace_override,
    _report_from_result,
)

# ─── Output backends ─────────────────────────────────────────────


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
        if proc.stdin is None:
            raise RuntimeError("FFmpeg stdin pipe is unavailable")
        proc.stdin.write(rgb_data)

    def close(self):
        if self._proc and self._proc.poll() is None:
            if self._proc.stdin:
                self._proc.stdin.close()
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
        path = str(self._dir / f"frame_{self._frame:06d}.ppm")
        _save_image(path, rgb_data, self._width, self._height)
        self._frame += 1

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _save_image(path: str, rgb: bytes, width: int, height: int) -> None:
    if path.lower().endswith(".ppm"):
        with open(path, "wb") as f:
            f.write(f"P6\n{width} {height}\n255\n".encode())
            f.write(rgb)
    else:
        from PIL import Image

        Image.frombytes("RGB", (width, height), rgb).save(path)


# ─── Core rendering ──────────────────────────────────────────────


def _resolve_args(
    timeline: Timeline | float, settings: Shot | Quality | str | None
) -> tuple[Timeline, Shot]:
    if isinstance(timeline, (int, float)):
        timeline = Timeline(duration=float(timeline))
    if settings is None:
        settings = Shot()
    elif isinstance(settings, str):
        settings = Shot.preset(settings)
    elif isinstance(settings, Quality):
        settings = Shot.preset(settings)
    return timeline, settings


def _sample_frame_indices(timeline: Timeline, frame: int | None, sample_count: int) -> list[int]:
    if frame is not None:
        return [frame]
    total = timeline.total_frames
    if total <= 1 or sample_count <= 1:
        return [0]
    return sorted({round(i * (total - 1) / (sample_count - 1)) for i in range(sample_count)})


def _resolve_frame_shot(
    shot: Shot,
    result: Scene | Frame,
    camera: Camera2D | None,
) -> _lpt2d.Shot:
    """Resolve animate callback result + base shot into a C++ Shot for rendering."""
    f = result if isinstance(result, Frame) else Frame(scene=result)

    look = _apply_look_override(shot.look, f.look)
    trace = _apply_trace_override(shot.trace, f.trace)

    # Camera precedence: per-frame > explicit arg > shot camera > auto-fit
    effective_camera = f.camera or camera or shot.camera
    cpp_camera = effective_camera if effective_camera is not None else Camera2D()

    # Warn if explicit camera bounds don't match canvas aspect ratio.
    # Python's default warning filter deduplicates by message+location.
    canvas = shot.canvas
    if cpp_camera.bounds is not None and canvas is not None:
        cam_bounds = cpp_camera.bounds
        cam_w = cam_bounds.max[0] - cam_bounds.min[0]
        cam_h = cam_bounds.max[1] - cam_bounds.min[1]
        if cam_h > 0:
            cam_aspect = cam_w / cam_h
            canvas_aspect = canvas.width / canvas.height
            if abs(cam_aspect - canvas_aspect) / canvas_aspect > 0.01:
                warnings.warn(
                    f"Camera aspect ratio ({cam_aspect:.3f}) does not match canvas "
                    f"aspect ratio ({canvas_aspect:.3f}). This will produce black bars. "
                    f"Consider using Camera2D(width=...) to derive height from the canvas.",
                    stacklevel=2,
                )

    return _lpt2d.Shot(
        name=shot.name,
        scene=f.scene,
        camera=cpp_camera,
        canvas=shot.canvas,
        look=look,
        trace=trace,
    )


def render(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    fast: bool = False,
    codec: str = "libx264",
    crf: int = 18,
    start: float = 0.0,
    end: float | None = None,
    stride: int = 1,
    frame: int | None = None,
    gate: QualityGate | None = None,
) -> None:
    """Render an animation to video or image sequence."""
    timeline, shot = _resolve_args(timeline, settings)
    width, height = shot.canvas.width, shot.canvas.height

    if output.endswith("/") or (Path(output).exists() and Path(output).is_dir()):
        out: FFmpegOutput | PpmOutput = PpmOutput(output, width, height)
    else:
        out = FFmpegOutput(output, width, height, timeline.fps, codec, crf)

    session = RenderSession(width, height, fast)
    gate_warnings: list[str] = []
    last_report: FrameReport | None = None

    def _render_frame(i: int) -> bytes:
        nonlocal last_report
        ctx = timeline.context_at(i)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, camera)
        t0 = time.monotonic()
        render_result = session.render_shot(cpp_shot, i)
        ms = (time.monotonic() - t0) * 1000
        last_report = _report_from_result(render_result, i, ms)
        return render_result.pixels

    def _check_gate(frame_idx: int) -> None:
        if gate is None or last_report is None:
            return
        warns = check_quality(last_report, gate)
        for w in warns:
            msg = f"frame {frame_idx}: WARN: {w}"
            gate_warnings.append(msg)
            sys.stderr.write(f"\n  {msg}")

    try:
        if frame is not None:
            out.write_frame(_render_frame(frame))
            _check_gate(frame)
            ms = f", {last_report.time_ms}ms" if last_report else ""
            sys.stderr.write(f"frame {frame} ({timeline.time_at(frame):.2f}s{ms})\n")
        else:
            start_frame = int(start * timeline.fps)
            end_frame = int(end * timeline.fps) if end is not None else timeline.total_frames
            end_frame = min(end_frame, timeline.total_frames)
            frames = range(start_frame, end_frame, stride)
            total = len(frames)

            for idx, i in enumerate(frames):
                out.write_frame(_render_frame(i))
                _check_gate(i)
                ms = f" {last_report.time_ms}ms" if last_report else ""
                sys.stderr.write(f"\rframe {idx + 1}/{total} ({timeline.time_at(i):.2f}s{ms})")
                sys.stderr.flush()
            sys.stderr.write("\n")

        if gate_warnings:
            sys.stderr.write(f"Quality gate: {len(gate_warnings)} warning(s)\n")
    finally:
        out.close()


def render_still(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    frame: int = 0,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    fast: bool = False,
) -> None:
    """Render a single frame to an image file."""
    timeline, shot = _resolve_args(timeline, settings)
    session = RenderSession(shot.canvas.width, shot.canvas.height, fast)

    ctx = timeline.context_at(frame)
    result = animate(ctx)
    cpp_shot = _resolve_frame_shot(shot, result, camera)
    render_result = session.render_shot(cpp_shot, frame)
    _save_image(output, render_result.pixels, shot.canvas.width, shot.canvas.height)
    sys.stderr.write(f"wrote {output} ({shot.canvas.width}x{shot.canvas.height}, frame {frame})\n")


def render_contact_sheet(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    cols: int = 4,
    count: int = 16,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    fast: bool = False,
) -> None:
    """Render a grid of frames spread across the timeline."""
    timeline, shot = _resolve_args(timeline, settings)
    w, h = shot.canvas.width, shot.canvas.height
    rows = math.ceil(count / cols)
    sheet_w = w * cols
    sheet_h = h * rows

    indices = _sample_frame_indices(timeline, None, count)
    session = RenderSession(w, h, fast)
    frames_rgb: list[bytes] = []

    for idx, fi in enumerate(indices):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, camera)
        render_result = session.render_shot(cpp_shot, fi)
        frames_rgb.append(render_result.pixels)
        sys.stderr.write(f"\rcontact sheet: {idx + 1}/{count}")
        sys.stderr.flush()
    sys.stderr.write("\n")

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
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    fast: bool = False,
) -> list[tuple[int, float, FrameStats]]:
    """Render frames and return their statistics."""
    timeline, shot = _resolve_args(timeline, settings)
    w, h = shot.canvas.width, shot.canvas.height

    if frames is None:
        indices = _sample_frame_indices(timeline, None, count)
    elif isinstance(frames, int):
        indices = [frames]
    else:
        indices = list(frames)

    session = RenderSession(w, h, fast)
    results: list[tuple[int, float, FrameStats]] = []

    for fi in indices:
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, camera)
        t0 = time.monotonic()
        render_result = session.render_shot(cpp_shot, fi)
        ms = (time.monotonic() - t0) * 1000
        report = _report_from_result(render_result, fi, ms)
        stats = frame_stats_from_report(report, w, h)
        if stats is None:
            raise RuntimeError("No stats report from renderer")
        results.append((fi, ctx.time, stats))

    return results
