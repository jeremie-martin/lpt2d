"""Subprocess wrapper for lpt2d-cli --stream and output backends."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Callable, cast

from .stats import (
    FrameStats,
    LightContribution,
    LookComparison,
    LookProfile,
    LookReport,
    QualityGate,
    StatsDiff,
    StructureReport,
    check_quality,
    frame_stats,
    frame_stats_from_report,
)
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

# Draft quality for analysis functions (auto_look, compare_looks, look_report, etc.)
_ANALYSIS_CANVAS = Canvas(width=480, height=480)
_ANALYSIS_TRACE = TraceDefaults(rays=500_000, batch=100_000, depth=12)


def _require_pipe(pipe, name: str):
    if pipe is None:
        raise RuntimeError(f"Subprocess {name} pipe is unavailable")
    return pipe


class Renderer:
    """Manages a persistent lpt2d-cli --stream subprocess."""

    last_report: FrameReport | None = None

    def __init__(
        self,
        shot: Shot | None = None,
        binary: str = DEFAULT_BINARY,
        fast: bool = False,
        histogram: bool = False,
    ):
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
        if histogram:
            cmd.append("--histogram")
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
        if look.saturation != 1.0:
            cmd.extend(["--saturation", str(look.saturation)])
        if look.vignette > 0:
            cmd.extend(["--vignette", str(look.vignette)])
        if look.vignette_radius != 0.7:
            cmd.extend(["--vignette-radius", str(look.vignette_radius)])
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
                        time_ms_exact=meta.get("time_ms_exact"),
                        max_hdr=meta.get("max_hdr", 0.0),
                        total_rays=meta.get("total_rays", 0),
                        mean=meta.get("mean"),
                        pct_black=meta.get("pct_black"),
                        pct_clipped=meta.get("pct_clipped"),
                        p50=meta.get("p50"),
                        p95=meta.get("p95"),
                        stats_ms=meta.get("stats_ms"),
                        histogram=meta.get("histogram"),
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


def _resolve_frame_camera(
    frame: Frame,
    camera: Camera2D | None,
    shot_camera: Camera2D | None,
) -> Camera2D | None:
    """Resolve camera precedence for Python render helpers.

    Per-frame camera overrides the explicit helper argument, which overrides the
    authored Shot camera. If all are absent, the renderer auto-fits bounds.
    """
    if frame.camera is not None:
        return frame.camera
    if camera is not None:
        return camera
    return shot_camera


def _build_wire_json(
    frame: Frame,
    camera: Camera2D | None,
    shot_camera: Camera2D | None,
    aspect: float,
) -> str:
    """Serialize a Frame into the v5 wire-format JSON that C++ expects."""
    d = frame.scene.to_wire_dict()
    d["version"] = 5

    render_block: dict = {}

    # Camera precedence: per-frame override > explicit helper argument > authored Shot
    effective_camera = _resolve_frame_camera(frame, camera, shot_camera)
    if effective_camera is not None:
        bounds = effective_camera.resolve(aspect)
        if bounds is not None:
            render_block["bounds"] = bounds

    # Per-frame look overrides
    if frame.look is not None:
        render_block.update(frame.look.to_override_dict())

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


def _sample_frame_indices(timeline: Timeline, frame: int | None, sample_count: int) -> list[int]:
    if frame is not None:
        return [frame]
    total = timeline.total_frames
    if total <= 1 or sample_count <= 1:
        return [0]
    return sorted({round(i * (total - 1) / (sample_count - 1)) for i in range(sample_count)})


def _analysis_canvas(base: Canvas | None) -> Canvas:
    """Analysis renders keep authored framing while capping resolution."""
    if base is None:
        return _ANALYSIS_CANVAS
    longest = max(base.width, base.height)
    if longest <= max(_ANALYSIS_CANVAS.width, _ANALYSIS_CANVAS.height):
        return Canvas(width=base.width, height=base.height)
    scale = max(_ANALYSIS_CANVAS.width, _ANALYSIS_CANVAS.height) / longest
    return Canvas(
        width=max(1, round(base.width * scale)),
        height=max(1, round(base.height * scale)),
    )


def _analysis_trace(base: TraceDefaults | None, *, rays: int | None = None) -> TraceDefaults:
    """Analysis renders reuse authored intent while staying cheap."""
    ref = base or TraceDefaults()
    chosen_rays = ref.rays if rays is None else rays
    return TraceDefaults(
        rays=min(chosen_rays, _ANALYSIS_TRACE.rays) if rays is None else chosen_rays,
        batch=min(ref.batch, _ANALYSIS_TRACE.batch),
        depth=min(ref.depth, _ANALYSIS_TRACE.depth),
        intensity=ref.intensity,
    )


def _analysis_result_look(
    authored: Look,
    *,
    tonemap: str,
    normalize: str,
    normalize_ref: float = 0.0,
) -> Look:
    look = authored.with_overrides(tonemap=tonemap, normalize=normalize)
    if normalize_ref > 0.0:
        look = look.with_overrides(normalize_ref=normalize_ref)
    return look


def _resolve_analysis_subject(
    subject: Scene | Shot | AnimateFn,
    timeline_or_none: Timeline | float | None,
    settings: Shot | Quality | str | None,
) -> tuple[AnimateFn, Timeline, Shot]:
    if isinstance(subject, Shot):
        if settings is not None:
            raise ValueError("settings= is not supported when the analysis subject is a Shot")
        timeline = (
            Timeline(duration=1.0, fps=1)
            if timeline_or_none is None
            else _resolve_args(timeline_or_none, None)[0]
        )

        def animate_from_shot(_ctx: FrameContext, _scene: Scene = subject.scene) -> Frame:
            return Frame(scene=_scene)

        return animate_from_shot, timeline, subject

    if isinstance(subject, Scene):
        timeline, shot = _resolve_args(
            Timeline(duration=1.0, fps=1) if timeline_or_none is None else timeline_or_none,
            settings,
        )

        def animate_from_scene(_ctx: FrameContext, _scene: Scene = subject) -> Frame:
            return Frame(scene=_scene)

        return animate_from_scene, timeline, shot

    if timeline_or_none is None:
        raise ValueError("timeline is required when passing an animate callback")
    timeline, shot = _resolve_args(timeline_or_none, settings)
    return subject, timeline, shot


def _resolve_static_scene_subject(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    look: Look | None = None,
    trace: TraceDefaults | None = None,
) -> tuple[Scene, Shot]:
    if isinstance(subject, Shot):
        shot = subject
        scene = subject.scene
    else:
        shot = Shot(scene=subject)
        scene = subject
    if camera is not None:
        shot = dc_replace(shot, camera=camera)
    if canvas is not None:
        shot = dc_replace(shot, canvas=canvas)
    if look is not None:
        shot = dc_replace(shot, look=look)
    if trace is not None:
        shot = dc_replace(shot, trace=trace)
    return scene, shot


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
        camera: Explicit helper camera. Per-frame Frame.camera overrides this,
                and this overrides ``settings.camera`` when present.
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
        wire = _build_wire_json(f, camera, shot.camera, aspect)
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
    """Render a single frame to an image file.

    Camera precedence matches :func:`render`: per-frame camera override,
    then explicit ``camera=``, then ``settings.camera``.
    """
    timeline, shot = _resolve_args(timeline, settings)

    renderer = Renderer(shot, binary=binary, fast=fast)
    try:
        ctx = timeline.context_at(frame)
        result = animate(ctx)
        f = result if isinstance(result, Frame) else Frame(scene=result)
        wire = _build_wire_json(f, camera, shot.camera, shot.canvas.aspect)
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
    """Render a grid of frames spread across the timeline.

    Camera precedence matches :func:`render`: per-frame camera override,
    then explicit ``camera=``, then ``settings.camera``.
    """
    timeline, shot = _resolve_args(timeline, settings)

    w, h = shot.canvas.width, shot.canvas.height
    rows = math.ceil(count / cols)
    sheet_w = w * cols
    sheet_h = h * rows

    # Sample frames evenly across timeline
    indices = _sample_frame_indices(timeline, None, count)

    renderer = Renderer(shot, binary=binary, fast=fast)
    try:
        frames_rgb: list[bytes] = []
        for idx, fi in enumerate(indices):
            ctx = timeline.context_at(fi)
            result = animate(ctx)
            f = result if isinstance(result, Frame) else Frame(scene=result)
            wire = _build_wire_json(f, camera, shot.camera, shot.canvas.aspect)
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
    """Render frames and return their statistics. No file output.

    Camera precedence matches :func:`render`: per-frame camera override,
    then explicit ``camera=``, then ``settings.camera``.
    """
    timeline, shot = _resolve_args(timeline, settings)

    # Resolve frame indices
    if frames is None:
        indices = _sample_frame_indices(timeline, None, count)
    elif isinstance(frames, int):
        indices = [frames]
    else:
        indices = list(frames)

    w, h = shot.canvas.width, shot.canvas.height
    aspect = shot.canvas.aspect

    renderer = Renderer(shot, binary=binary, fast=fast, histogram=True)
    results: list[tuple[int, float, FrameStats]] = []
    try:
        for fi in indices:
            ctx = timeline.context_at(fi)
            result = animate(ctx)
            f = result if isinstance(result, Frame) else Frame(scene=result)
            wire = _build_wire_json(f, camera, shot.camera, aspect)
            rgb = renderer.render_frame(wire)
            stats = None
            if renderer.last_report is not None:
                stats = frame_stats_from_report(renderer.last_report, w, h)
            if stats is None:
                stats = frame_stats(rgb, w, h)
            results.append((fi, ctx.time, stats))
    finally:
        renderer.close()
    return results


def auto_look(
    scene_or_animate: Scene | Shot | AnimateFn,
    timeline_or_none: Timeline | float | None = None,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    target_mean: float = 0.35,
    max_clipping: float = 0.02,
    tonemap: str | None = None,
    normalize: str | None = None,
    binary: str = DEFAULT_BINARY,
    frame: int | None = None,
    sample_count: int = 8,
) -> Look:
    """Analyze a scene and return a Look with good exposure settings.

    Works with a static Scene or an (animate, timeline) pair. Renders a
    low-quality draft pass over sampled frames, measures brightness, and
    computes exposure to hit *target_mean* (0-1 scale) without exceeding
    *max_clipping*.

    When passed a :class:`Shot`, authored camera/canvas/trace defaults are used
    automatically. For animated callbacks, pass ``settings=shot`` to make the
    analysis match the authored shot instead of the generic draft defaults.
    """
    animate, timeline, shot = _resolve_analysis_subject(scene_or_animate, timeline_or_none, settings)
    analysis_frames = _sample_frame_indices(timeline, frame, sample_count)

    draft_canvas = canvas or _analysis_canvas(shot.canvas)
    draft_trace = _analysis_trace(shot.trace)
    chosen_tonemap = shot.look.tonemap if tonemap is None else tonemap
    chosen_normalize = shot.look.normalize if normalize is None else normalize

    def measure_per_frame(look: Look) -> list[tuple[int, float, FrameStats]]:
        draft_shot = dc_replace(shot, canvas=draft_canvas, look=look, trace=draft_trace)
        return render_stats(
            animate,
            timeline,
            frames=analysis_frames,
            settings=draft_shot,
            camera=camera or shot.camera,
            binary=binary,
            fast=True,
        )

    # Calibrate normalize_ref if using fixed mode
    chosen_normalize_ref = 0.0
    if chosen_normalize == "fixed":
        chosen_normalize_ref = calibrate_normalize_ref(
            animate,
            timeline,
            settings=Shot(canvas=draft_canvas, trace=draft_trace),
            camera=camera or shot.camera,
            binary=binary,
            frame=analysis_frames,
        )

    result_base = _analysis_result_look(
        shot.look,
        tonemap=chosen_tonemap,
        normalize=chosen_normalize,
        normalize_ref=chosen_normalize_ref,
    )

    # Measure at baseline exposure
    baseline_look = result_base.with_overrides(exposure=-5.0)

    per_frame = measure_per_frame(baseline_look)
    if not per_frame:
        return result_base

    # Compute per-frame brightness
    brightnesses = [s.mean / 255.0 for _, _, s in per_frame]
    measured_mean = sum(brightnesses) / len(brightnesses)

    # Stability check: if brightness varies a lot, target the dimmer frames
    # to prevent clipping on bright frames while keeping dark frames visible.
    if len(brightnesses) > 1:
        std_b = (
            sum((b - measured_mean) ** 2 for b in brightnesses) / (len(brightnesses) - 1)
        ) ** 0.5
        if std_b > 0.05:
            sorted_b = sorted(brightnesses)
            measured_mean = sorted_b[len(sorted_b) // 4]  # 25th percentile

    if measured_mean > 0.001:
        exposure = -5.0 + math.log2(target_mean / measured_mean)
    else:
        exposure = -1.0

    exposure = max(-15.0, min(exposure, 10.0))
    best_exposure = exposure

    candidate_stats = measure_per_frame(result_base.with_overrides(exposure=exposure))
    if candidate_stats:
        candidate_clipping = max(s.pct_clipped for _, _, s in candidate_stats)
        if candidate_clipping > max_clipping:
            low = -15.0
            high = exposure
            best_exposure = low
            for _ in range(8):
                mid = (low + high) * 0.5
                mid_stats = measure_per_frame(result_base.with_overrides(exposure=mid))
                if not mid_stats:
                    high = mid
                    continue
                mid_clipping = max(s.pct_clipped for _, _, s in mid_stats)
                if mid_clipping <= max_clipping:
                    best_exposure = mid
                    low = mid
                else:
                    high = mid

    return result_base.with_overrides(exposure=round(best_exposure, 2))


def calibrate_normalize_ref(
    animate: AnimateFn,
    timeline: Timeline | float,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    binary: str = DEFAULT_BINARY,
    fast: bool = False,
    frame: int | list[int] | None = 0,
) -> float:
    """Render one or more frames with max-normalize to determine a good normalize_ref.

    Returns the HDR max value suitable for use as ``Look(normalize="fixed",
    normalize_ref=...)``.

    Camera precedence matches :func:`render`: per-frame camera override,
    then explicit ``camera=``, then ``settings.camera``.
    """
    timeline, shot = _resolve_args(timeline, settings)
    frames = [frame] if isinstance(frame, int) else frame
    frame_indices = [0] if frames is None else list(frames)

    # Force max mode so the C++ renderer computes and reports true HDR peak.
    cal_shot = shot.with_look(normalize="max", normalize_pct=1.0)

    renderer = Renderer(cal_shot, binary=binary, fast=fast)
    try:
        max_hdr = 0.0
        for fi in frame_indices:
            ctx = timeline.context_at(fi)
            result = animate(ctx)
            f = result if isinstance(result, Frame) else Frame(scene=result)
            wire = _build_wire_json(f, camera, cal_shot.camera, cal_shot.canvas.aspect)
            renderer.render_frame(wire)  # discard pixels, we want the report

            rpt = renderer.last_report
            if rpt is None or rpt.max_hdr <= 0:
                raise RuntimeError("Calibration failed: no max_hdr in renderer report")
            max_hdr = max(max_hdr, rpt.max_hdr)
        return max_hdr
    finally:
        renderer.close()


def compare_looks(
    scene_or_animate: Scene | Shot | AnimateFn,
    timeline_or_looks: Timeline | float | list[Look] | None = None,
    looks: list[Look] | None = None,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    binary: str = DEFAULT_BINARY,
    count: int = 8,
    frames: list[int] | None = None,
) -> LookComparison:
    """Render candidate Looks against the same frames and compare.

    All candidates are evaluated on the same frame set for fair comparison.
    Uses draft quality for speed while preserving the authored shot aspect when
    enough shot context is available.
    """
    if looks is None:
        if not isinstance(timeline_or_looks, list):
            raise ValueError("looks are required")
        timeline_or_none: Timeline | float | None = None
        candidate_looks = list(cast(list[Look], timeline_or_looks))
    else:
        timeline_or_none = timeline_or_looks  # type: ignore[assignment]
        candidate_looks = looks

    animate, timeline, shot = _resolve_analysis_subject(scene_or_animate, timeline_or_none, settings)
    draft_canvas = canvas or _analysis_canvas(shot.canvas)
    draft_trace = _analysis_trace(shot.trace)
    frame_indices = _sample_frame_indices(timeline, None, count) if frames is None else list(frames)

    profiles: list[LookProfile] = []
    for look in candidate_looks:
        draft_shot = Shot(canvas=draft_canvas, look=look, trace=draft_trace)
        stats = render_stats(
            animate,
            timeline,
            frames=frame_indices,
            settings=draft_shot,
            camera=camera or shot.camera,
            binary=binary,
            fast=True,
        )
        profiles.append(LookProfile.from_stats(look, stats))
    return LookComparison(profiles=profiles, frame_indices=frame_indices)


def look_report(
    scene_or_animate: Scene | Shot | AnimateFn,
    timeline_or_look: Timeline | float | Look | None = None,
    look: Look | None = None,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    binary: str = DEFAULT_BINARY,
    count: int = 12,
    frames: list[int] | None = None,
    dark_threshold: float = 0.15,
    bright_threshold: float = 0.70,
    clip_threshold: float = 0.05,
    contrast_threshold: float = 30.0,
) -> LookReport:
    """Diagnose how a Look performs across an animation's timeline.

    Renders at sampled frames and identifies problem regions.
    """
    if look is None:
        if not isinstance(timeline_or_look, Look):
            raise ValueError("look is required")
        timeline_or_none: Timeline | float | None = None
        candidate_look = cast(Look, timeline_or_look)
    else:
        timeline_or_none = timeline_or_look  # type: ignore[assignment]
        candidate_look = look

    animate, timeline, shot = _resolve_analysis_subject(scene_or_animate, timeline_or_none, settings)
    draft_canvas = canvas or _analysis_canvas(shot.canvas)
    draft_trace = _analysis_trace(shot.trace)
    frame_indices = _sample_frame_indices(timeline, None, count) if frames is None else list(frames)

    draft_shot = Shot(canvas=draft_canvas, look=candidate_look, trace=draft_trace)
    stats = render_stats(
        animate,
        timeline,
        frames=frame_indices,
        settings=draft_shot,
        camera=camera or shot.camera,
        binary=binary,
        fast=True,
    )
    profile = LookProfile.from_stats(candidate_look, stats)
    return LookReport.from_profile(
        profile,
        dark_threshold=dark_threshold,
        bright_threshold=bright_threshold,
        clip_threshold=clip_threshold,
        contrast_threshold=contrast_threshold,
    )


# --- Clutter diagnostics ---


def _neutral_contribution_look(normalize_ref: float) -> Look:
    """Neutral linear look for additive source-comparison work."""
    return Look(
        exposure=0.0,
        contrast=1.0,
        gamma=1.0,
        tonemap="none",
        normalize="fixed",
        normalize_ref=normalize_ref,
        ambient=0.0,
        background=[0.0, 0.0, 0.0],
        opacity=1.0,
        saturation=1.0,
        vignette=0.0,
        vignette_radius=0.7,
    )


def _collect_light_sources(scene: Scene) -> list[tuple[str, str]]:
    """Collect (display_label, kind:key) for all authored light sources.

    Includes explicit lights and emissive shapes (which auto-generate lights
    during C++ upload_scene).  The second element encodes the source type:
    ``"light:0"``, ``"group:1:0"``, ``"emissive:3"``, ``"emissive_group:1:2"``.
    """
    from .types import Material

    sources: list[tuple[str, str]] = []
    for i, light in enumerate(scene.lights):
        sources.append((light.id or f"light_{i}", f"light:{i}"))
    for gi, group in enumerate(scene.groups):
        for li, light in enumerate(group.lights):
            label = (group.id or f"group_{gi}") + "/" + (light.id or f"light_{li}")
            sources.append((label, f"group:{gi}:{li}"))
    # Emissive shapes act as light sources via auto-generated synthetic lights
    for si, shape in enumerate(scene.shapes):
        mat: Material = shape.material  # type: ignore[union-attr]
        if mat.emission > 0:
            sources.append((shape.id or f"emissive_shape_{si}", f"emissive:{si}"))  # type: ignore[union-attr]
    for gi, group in enumerate(scene.groups):
        for si, shape in enumerate(group.shapes):
            mat = shape.material  # type: ignore[union-attr]
            if mat.emission > 0:
                label = (group.id or f"group_{gi}") + "/" + (shape.id or f"emissive_{si}")  # type: ignore[union-attr]
                sources.append((label, f"emissive_group:{gi}:{si}"))
    return sources


def _zero_emission(shape: object) -> object:
    """Return a copy of *shape* with emission zeroed out."""
    mat = shape.material  # type: ignore[union-attr]
    if mat.emission > 0:
        new_mat = dc_replace(mat, emission=0.0)
        return dc_replace(shape, material=new_mat)  # type: ignore[type-var]
    return shape


def _scene_with_solo_source(scene: Scene, key: str) -> Scene:
    """Build a scene with only one light source active.

    *key* is a ``kind:detail`` string from ``_collect_lights``.
    """
    kind, _, detail = key.partition(":")

    if kind == "light":
        idx = int(detail)
        return dc_replace(
            scene,
            lights=[scene.lights[idx]],
            shapes=[_zero_emission(s) for s in scene.shapes],  # type: ignore[misc]
            groups=[
                dc_replace(g, lights=[], shapes=[_zero_emission(s) for s in g.shapes])  # type: ignore[misc]
                for g in scene.groups
            ],
        )

    if kind == "group":
        parts = detail.split(":")
        gi, li = int(parts[0]), int(parts[1])
        new_groups = []
        for i, g in enumerate(scene.groups):
            kept_lights = [g.lights[li]] if i == gi else []
            new_groups.append(
                dc_replace(g, lights=kept_lights, shapes=[_zero_emission(s) for s in g.shapes])  # type: ignore[misc]
            )
        return dc_replace(
            scene,
            lights=[],
            shapes=[_zero_emission(s) for s in scene.shapes],  # type: ignore[misc]
            groups=new_groups,
        )

    if kind in ("emissive", "emissive_group"):
        # Keep this one emissive shape, zero all others, remove explicit lights.
        target_gi = -1
        target_si = int(detail)
        if kind == "emissive_group":
            group_part, shape_part = detail.split(":")
            target_gi = int(group_part)
            target_si = int(shape_part)
        new_shapes = []
        for si, s in enumerate(scene.shapes):
            if target_gi < 0 and si == target_si:
                new_shapes.append(s)
            else:
                new_shapes.append(_zero_emission(s))  # type: ignore[misc]
        new_groups = []
        for gi, g in enumerate(scene.groups):
            gs = []
            for si, s in enumerate(g.shapes):
                if gi == target_gi and si == target_si:
                    gs.append(s)
                else:
                    gs.append(_zero_emission(s))  # type: ignore[misc]
            new_groups.append(dc_replace(g, lights=[], shapes=gs))
        return dc_replace(scene, lights=[], shapes=new_shapes, groups=new_groups)

    return scene  # fallback


def _contribution_reference_shot(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays_per_light: int = 500_000,
    binary: str = DEFAULT_BINARY,
) -> tuple[Scene, Shot]:
    scene, shot = _resolve_static_scene_subject(subject, camera=camera, canvas=canvas)
    scene = scene.clone()
    scene.ensure_ids()
    analysis_shot = Shot(
        scene=scene,
        camera=shot.camera,
        canvas=_analysis_canvas(shot.canvas),
        trace=_analysis_trace(shot.trace, rays=rays_per_light),
    )
    normalize_ref = calibrate_normalize_ref(
        lambda _ctx, _scene=scene: Frame(scene=_scene),
        1.0,
        settings=analysis_shot,
        camera=analysis_shot.camera,
        binary=binary,
        fast=True,
        frame=[0],
    )
    return scene, dc_replace(analysis_shot, look=_neutral_contribution_look(normalize_ref))


def light_contributions(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays_per_light: int = 500_000,
    binary: str = DEFAULT_BINARY,
) -> list[LightContribution]:
    """Render each source solo and measure its linear frame contribution.

    Includes explicit lights and emissive shapes. The measurement uses a shared
    fixed normalization reference captured from the full scene plus a neutral
    linear look, so source shares remain additive and comparable.
    """
    scene, analysis_shot = _contribution_reference_shot(
        subject,
        camera=camera,
        canvas=canvas,
        rays_per_light=rays_per_light,
        binary=binary,
    )
    all_sources = _collect_light_sources(scene)
    if not all_sources:
        return []

    results: list[tuple[str, int, float, float]] = []  # (label, idx, mean, coverage)
    total_mean = 0.0

    for idx, (label, key) in enumerate(all_sources):
        solo_scene = _scene_with_solo_source(scene, key)

        def animate_solo(_ctx: FrameContext, _s: Scene = solo_scene) -> Frame:
            return Frame(scene=_s)

        stats_list = render_stats(
            animate_solo,
            1.0,
            frames=[0],
            settings=dc_replace(analysis_shot, scene=solo_scene),
            camera=analysis_shot.camera,
            binary=binary,
            fast=True,
        )
        if stats_list:
            s = stats_list[0][2]
            results.append((label, idx, s.mean, 1.0 - s.pct_black))
            total_mean += s.mean
        else:
            results.append((label, idx, 0.0, 0.0))

    contributions = []
    for label, idx, mean, coverage in results:
        frac = mean / total_mean if total_mean > 0 else 0.0
        contributions.append(
            LightContribution(
                source_id=label,
                source_index=idx,
                mean_linear_luma=mean,
                coverage_fraction=coverage,
                share=frac,
            )
        )
    contributions.sort(key=lambda c: c.share, reverse=True)
    return contributions


def structure_contribution(
    subject: Scene | Shot,
    shape_id: str,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays: int = 5_000_000,
    binary: str = DEFAULT_BINARY,
) -> StructureReport:
    """Measure one shape's effect with the same neutral reference on both runs."""
    if isinstance(subject, Shot):
        subject.scene.require_shape(shape_id)
    else:
        subject.require_shape(shape_id)

    scene, analysis_shot = _contribution_reference_shot(
        subject,
        camera=camera,
        canvas=canvas,
        rays_per_light=rays,
        binary=binary,
    )

    # Build scene without the shape
    scene_without = dc_replace(
        scene,
        shapes=[s for s in scene.shapes if s.id != shape_id],
        groups=[
            dc_replace(
                g,
                shapes=[s for s in g.shapes if s.id != shape_id],
            )
            for g in scene.groups
        ],
    )

    stats_with = render_stats(
        lambda _ctx, _s=scene: Frame(scene=_s),
        1.0,
        frames=[0],
        settings=dc_replace(analysis_shot, scene=scene),
        camera=analysis_shot.camera,
        binary=binary,
        fast=True,
    )
    stats_without = render_stats(
        lambda _ctx, _s=scene_without: Frame(scene=_s),
        1.0,
        frames=[0],
        settings=dc_replace(analysis_shot, scene=scene_without),
        camera=analysis_shot.camera,
        binary=binary,
        fast=True,
    )

    s_with = stats_with[0][2] if stats_with else FrameStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 480, 480)
    s_without = (
        stats_without[0][2] if stats_without else FrameStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 480, 480)
    )

    diff = StatsDiff(
        mean=s_without.mean - s_with.mean,
        pct_black=s_without.pct_black - s_with.pct_black,
        pct_clipped=s_without.pct_clipped - s_with.pct_clipped,
        p50=s_without.p50 - s_with.p50,
        p95=s_without.p95 - s_with.p95,
    )

    # Infer the role from the neutral linear delta.
    if diff.mean > 5.0:
        role = "dimmer"  # removing the shape makes it brighter
    elif diff.mean < -5.0:
        role = "brightener"  # removing the shape makes it dimmer
    else:
        role = "neutral"

    return StructureReport(
        shape_id=shape_id,
        stats_with=s_with,
        stats_without=s_without,
        diff=diff,
        role=role,
    )


def scene_light_report(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    binary: str = DEFAULT_BINARY,
) -> str:
    """Human-readable contribution report for authored light sources."""
    contribs = light_contributions(subject, camera=camera, canvas=canvas, binary=binary)

    if not contribs:
        return "No lights in scene."

    lines = ["Light contribution report:"]
    lines.append(f"  {'ID':<20} {'Share%':>8} {'Coverage%':>10} {'Mean':>8}")
    for c in contribs:
        lines.append(
            f"  {c.source_id:<20} {c.share:>7.1%} {c.coverage_fraction:>9.1%} {c.mean_linear_luma:>8.1f}"
        )

    # Warnings
    warnings = []
    for c in contribs:
        if c.share < 0.01 and c.mean_linear_luma > 0:
            warnings.append(f"  {c.source_id}: contributes <1% of linear frame share")
        if c.share > 0.70:
            warnings.append(f"  {c.source_id}: dominates the frame (>70% share)")
        if c.coverage_fraction > 0.50 and c.share < 0.10:
            warnings.append(f"  {c.source_id}: wide coverage but low share (potential clutter)")

    if warnings:
        lines.append("Warnings:")
        lines.extend(warnings)

    return "\n".join(lines)


def scene_energy_report(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    binary: str = DEFAULT_BINARY,
) -> str:
    """Compatibility alias for older worktree code; prefer scene_light_report()."""
    return scene_light_report(subject, camera=camera, canvas=canvas, binary=binary)
