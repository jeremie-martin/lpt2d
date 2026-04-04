"""Subprocess wrapper for lpt2d-cli --stream and output backends."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .stats import FrameStats, QualityGate, check_quality, frame_stats
from .types import (
    Camera2D,
    Canvas,
    Frame,
    FrameContext,
    FrameReport,
    Look,
    Quality,
    Scene,
    Shot,
    Timeline,
    TraceDefaults,
)

DEFAULT_BINARY = "./build/lpt2d-cli"


def _require_pipe(pipe, name: str):
    if pipe is None:
        raise RuntimeError(f"Subprocess {name} pipe is unavailable")
    return pipe


class Renderer:
    """Manages a persistent lpt2d-cli --stream subprocess."""

    last_report: FrameReport | None = None

    def __init__(self, shot: Shot | None = None, binary: str = DEFAULT_BINARY, fast: bool = False):
        if shot is None:
            shot = Shot()
        canvas = shot.canvas
        look = shot.look
        trace = shot.trace
        self.width = canvas.width
        self.height = canvas.height
        self.frame_bytes = canvas.width * canvas.height * 3
        cmd = [
            binary,
            "--stream",
            "--width",
            str(canvas.width),
            "--height",
            str(canvas.height),
            "--rays",
            str(trace.rays),
            "--batch",
            str(trace.batch),
            "--depth",
            str(trace.depth),
            "--exposure",
            str(look.exposure),
            "--contrast",
            str(look.contrast),
            "--gamma",
            str(look.gamma),
            "--tonemap",
            look.tonemap,
            "--white-point",
            str(look.white_point),
        ]
        cmd.extend(["--normalize", look.normalize])
        if look.normalize_ref > 0:
            cmd.extend(["--normalize-ref", str(look.normalize_ref)])
        if look.normalize_pct < 1.0:
            cmd.extend(["--normalize-pct", str(look.normalize_pct)])
        if look.ambient != 0:
            cmd.extend(["--ambient", str(look.ambient)])
        bg = look.background
        if any(v != 0 for v in bg):
            cmd.extend(["--background", f"{bg[0]},{bg[1]},{bg[2]}"])
        if look.opacity < 1.0:
            cmd.extend(["--opacity", str(look.opacity)])
        if trace.intensity != 1.0:
            cmd.extend(["--intensity", str(trace.intensity)])
        if fast:
            cmd.append("--fast")
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
                        mean=meta.get("mean"),
                        pct_black=meta.get("pct_black"),
                        pct_clipped=meta.get("pct_clipped"),
                        p50=meta.get("p50"),
                        p95=meta.get("p95"),
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
    """Serialize a Frame into the v4 wire-format JSON that C++ expects."""
    d = frame.scene.to_dict()
    d["version"] = 4

    render_block: dict = {}

    # Camera: per-frame overrides session-level
    effective_camera = frame.camera if frame.camera is not None else session_camera
    if effective_camera is not None:
        bounds = effective_camera.resolve(aspect)
        if bounds is not None:
            render_block["bounds"] = bounds

    # Per-frame look overrides
    if frame.look is not None:
        render_block.update(frame.look.to_dict())

    # Per-frame trace overrides
    if frame.trace is not None:
        render_block.update(frame.trace.to_dict())

    if render_block:
        d["render"] = render_block

    return json.dumps(d, separators=(",", ":"))


# --- Helpers ---

AnimateFn = Callable[[FrameContext], Scene | Frame]


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


def render(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
    fast: bool = False,
    codec: str = "libx264",
    crf: int = 18,
    start: float = 0.0,
    end: float | None = None,
    stride: int = 1,
    frame: int | None = None,
    gate: QualityGate | None = None,
) -> None:
    """Render an animation to video or image sequence.

    Args:
        animate: Callback receiving FrameContext, returning Scene or Frame.
        timeline: Timeline object, or duration in seconds (uses fps=30).
        output: Output path. .mp4/.webm/.mkv -> video via ffmpeg.
                Trailing / or directory -> PPM sequence.
        settings: Shot, Quality preset, preset name (str), or None for defaults.
        camera: Session-level camera. Per-frame Frame.camera overrides this.
        binary: Path to lpt2d-cli executable.
        codec: Video codec (default: libx264).
        crf: Video quality (default: 18, visually lossless).
        start: Start time in seconds (skip earlier frames).
        end: End time in seconds (default: full duration).
        stride: Render every Nth frame (default: 1 = all frames).
        frame: Render a single frame by index. Overrides start/end/stride.
        gate: Optional quality gate — prints warnings when thresholds are exceeded.
    """
    timeline, shot = _resolve_args(timeline, settings)
    width, height, aspect = shot.canvas.width, shot.canvas.height, shot.canvas.aspect

    # Choose output backend
    if output.endswith("/") or (Path(output).exists() and Path(output).is_dir()):
        out: FFmpegOutput | PpmOutput = PpmOutput(output, width, height)
    else:
        out = FFmpegOutput(output, width, height, timeline.fps, codec, crf)

    renderer = Renderer(shot, binary=binary, fast=fast)
    gate_warnings: list[str] = []

    def _render_frame(i: int) -> bytes:
        ctx = timeline.context_at(i)
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, aspect)
        return renderer.render_frame(wire)

    def _check_gate(frame_idx: int) -> None:
        if gate is None:
            return
        rpt = renderer.last_report
        if rpt is None:
            return
        warns = check_quality(rpt, gate)
        for w in warns:
            msg = f"frame {frame_idx}: WARN: {w}"
            gate_warnings.append(msg)
            sys.stderr.write(f"\n  {msg}")

    try:
        if frame is not None:
            # Single-frame mode
            out.write_frame(_render_frame(frame))
            _check_gate(frame)
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
                _check_gate(i)
                rpt = renderer.last_report
                ms = f" {rpt.time_ms}ms" if rpt else ""
                sys.stderr.write(f"\rframe {idx + 1}/{total} ({timeline.time_at(i):.2f}s{ms})")
                sys.stderr.flush()
            sys.stderr.write("\n")

        if gate_warnings:
            sys.stderr.write(f"Quality gate: {len(gate_warnings)} warning(s)\n")
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
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
    fast: bool = False,
) -> None:
    """Render a single frame to an image file."""
    timeline, shot = _resolve_args(timeline, settings)

    renderer = Renderer(shot, binary=binary, fast=fast)
    try:
        ctx = timeline.context_at(frame)
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, shot.canvas.aspect)
        rgb = renderer.render_frame(wire)
        _save_image(output, rgb, shot.canvas.width, shot.canvas.height)
        sys.stderr.write(
            f"wrote {output} ({shot.canvas.width}x{shot.canvas.height}, frame {frame})\n"
        )
    finally:
        renderer.close()


def render_contact_sheet(
    animate: AnimateFn,
    timeline: Timeline | float,
    output: str,
    *,
    cols: int = 4,
    count: int = 16,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
    fast: bool = False,
) -> None:
    """Render a grid of frames spread across the timeline."""
    timeline, shot = _resolve_args(timeline, settings)

    w, h = shot.canvas.width, shot.canvas.height
    rows = math.ceil(count / cols)
    sheet_w = w * cols
    sheet_h = h * rows

    # Sample frames evenly across timeline
    total = timeline.total_frames
    indices = [round(i * (total - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]

    renderer = Renderer(shot, binary=binary, fast=fast)
    try:
        frames_rgb: list[bytes] = []
        for idx, fi in enumerate(indices):
            ctx = timeline.context_at(fi)
            result = animate(ctx)
            f = result if isinstance(result, Frame) else Frame(scene=result)
            wire = _build_wire_json(f, camera, shot.canvas.aspect)
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
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
    fast: bool = False,
) -> list[tuple[int, float, FrameStats]]:
    """Render frames and return their statistics. No file output."""
    timeline, shot = _resolve_args(timeline, settings)

    # Resolve frame indices
    total = timeline.total_frames
    if frames is None:
        indices = [round(i * (total - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
    elif isinstance(frames, int):
        indices = [frames]
    else:
        indices = list(frames)

    w, h = shot.canvas.width, shot.canvas.height
    aspect = shot.canvas.aspect

    renderer = Renderer(shot, binary=binary, fast=fast)
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


def auto_look(
    scene_or_animate: Scene | AnimateFn,
    timeline_or_none: Timeline | float | None = None,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    target_mean: float = 0.35,
    max_clipping: float = 0.02,
    tonemap: str = "aces",
    normalize: str = "rays",
    binary: str = DEFAULT_BINARY,
    frame: int = 0,
) -> Look:
    """Analyze a scene and return a Look with good exposure settings.

    Works with a static Scene or an (animate, timeline) pair. Renders a
    low-quality test frame, measures brightness, and computes exposure to
    hit *target_mean* (0–1 scale) without exceeding *max_clipping*.
    """
    # Build animate callback from static Scene
    if isinstance(scene_or_animate, Scene):
        scene = scene_or_animate
        animate: AnimateFn = lambda ctx: Frame(scene=scene)
        timeline: Timeline | float = 1.0
    else:
        animate = scene_or_animate
        if timeline_or_none is None:
            raise ValueError("timeline is required when passing an animate callback")
        timeline = timeline_or_none

    # Render a fast draft with the target tonemap and gamma so the measured
    # brightness matches what the user will see in the final render.
    draft_canvas = canvas or Canvas(width=480, height=480)
    draft_shot = Shot(
        canvas=draft_canvas,
        look=Look(exposure=2.0, tonemap=tonemap, normalize=normalize),
        trace=TraceDefaults(rays=500_000, batch=100_000, depth=12),
    )

    stats_results = render_stats(
        animate,
        timeline,
        frames=frame,
        settings=draft_shot,
        camera=camera,
        binary=binary,
        fast=True,
    )
    if not stats_results:
        return Look(tonemap=tonemap, normalize=normalize)

    _, _, stats = stats_results[0]

    # Compute exposure adjustment to hit target brightness
    measured_mean = stats.mean / 255.0
    if measured_mean > 0.001:
        # Current exposure is 2.0 (the draft default). Adjust to hit target_mean.
        exposure = 2.0 + math.log2(target_mean / measured_mean)
    else:
        exposure = 4.0  # very dark scene, boost aggressively

    # Clamp to reasonable range
    exposure = max(-2.0, min(exposure, 10.0))

    if stats.pct_clipped > max_clipping:
        exposure = exposure - 1.0

    result = Look(exposure=round(exposure, 2), tonemap=tonemap, normalize=normalize)

    # For fixed normalization, calibrate the reference value
    if normalize == "fixed":
        ref = calibrate_normalize_ref(
            animate, timeline, settings=draft_shot, camera=camera, binary=binary, frame=frame
        )
        result.normalize_ref = ref

    return result


def calibrate_normalize_ref(
    animate: AnimateFn,
    timeline: Timeline | float,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
    fast: bool = False,
    frame: int = 0,
) -> float:
    """Render one frame with max-normalize to determine a good normalize_ref.

    Returns the HDR max value suitable for use as ``Look(normalize="fixed",
    normalize_ref=...)``.
    """
    timeline, shot = _resolve_args(timeline, settings)

    # Force max mode so the C++ renderer computes and reports true HDR peak.
    cal_shot = shot.with_look(normalize="max", normalize_pct=1.0)

    renderer = Renderer(cal_shot, binary=binary, fast=fast)
    try:
        ctx = timeline.context_at(frame)
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, cal_shot.canvas.aspect)
        renderer.render_frame(wire)  # discard pixels, we want the report

        rpt = renderer.last_report
        if rpt is None or rpt.max_hdr <= 0:
            raise RuntimeError("Calibration failed: no max_hdr in renderer report")
        return rpt.max_hdr
    finally:
        renderer.close()
