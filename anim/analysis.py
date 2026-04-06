"""Scene analysis utilities: auto_look, compare_looks, look_report."""

from __future__ import annotations

import math
from dataclasses import replace as dc_replace
from typing import Callable, cast

from . import renderer as renderer_mod
from .stats import (
    FrameStats,
    LookComparison,
    LookProfile,
    LookReport,
)
from .types import (
    Camera2D,
    Canvas,
    Frame,
    FrameContext,
    Look,
    Quality,
    Scene,
    Shot,
    Timeline,
    TraceDefaults,
)

AnimateFn = Callable[[FrameContext], Scene | Frame]

# Draft quality for analysis functions (auto_look, compare_looks, look_report, etc.)
_ANALYSIS_CANVAS = Canvas(width=480, height=480)
_ANALYSIS_TRACE = TraceDefaults(rays=500_000, batch=100_000, depth=12)


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
            else renderer_mod._resolve_args(timeline_or_none, None)[0]
        )

        def animate_from_shot(_ctx: FrameContext, _scene: Scene = subject.scene) -> Frame:
            return Frame(scene=_scene)

        return animate_from_shot, timeline, subject

    if isinstance(subject, Scene):
        timeline, shot = renderer_mod._resolve_args(
            Timeline(duration=1.0, fps=1) if timeline_or_none is None else timeline_or_none,
            settings,
        )

        def animate_from_scene(_ctx: FrameContext, _scene: Scene = subject) -> Frame:
            return Frame(scene=_scene)

        return animate_from_scene, timeline, shot

    if timeline_or_none is None:
        raise ValueError("timeline is required when passing an animate callback")
    timeline, shot = renderer_mod._resolve_args(timeline_or_none, settings)
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
    binary: str = renderer_mod.DEFAULT_BINARY,
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
    animate, timeline, shot = _resolve_analysis_subject(
        scene_or_animate, timeline_or_none, settings
    )
    analysis_frames = renderer_mod._sample_frame_indices(timeline, frame, sample_count)

    draft_canvas = canvas or _analysis_canvas(shot.canvas)
    draft_trace = _analysis_trace(shot.trace)
    chosen_tonemap = shot.look.tonemap if tonemap is None else tonemap
    chosen_normalize = shot.look.normalize if normalize is None else normalize

    def measure_per_frame(look: Look) -> list[tuple[int, float, FrameStats]]:
        draft_shot = dc_replace(shot, canvas=draft_canvas, look=look, trace=draft_trace)
        return renderer_mod.render_stats(
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
    binary: str = renderer_mod.DEFAULT_BINARY,
    fast: bool = False,
    frame: int | list[int] | None = 0,
) -> float:
    """Render one or more frames with max-normalize to determine a good normalize_ref.

    Returns the HDR max value suitable for use as ``Look(normalize="fixed",
    normalize_ref=...)``.

    Camera precedence matches :func:`render`: per-frame camera override,
    then explicit ``camera=``, then ``settings.camera``.
    """
    timeline, shot = renderer_mod._resolve_args(timeline, settings)
    frames = [frame] if isinstance(frame, int) else frame
    frame_indices = [0] if frames is None else list(frames)

    # Force max mode so the C++ renderer computes and reports true HDR peak.
    cal_shot = shot.with_look(normalize="max", normalize_pct=1.0)

    renderer = renderer_mod.Renderer(cal_shot, binary=binary, fast=fast)
    try:
        max_hdr = 0.0
        for fi in frame_indices:
            ctx = timeline.context_at(fi)
            result = animate(ctx)
            f = result if isinstance(result, Frame) else Frame(scene=result)
            wire = renderer_mod._build_wire_json(
                f, camera, cal_shot.camera, cal_shot.canvas.aspect
            )
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
    binary: str = renderer_mod.DEFAULT_BINARY,
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

    animate, timeline, shot = _resolve_analysis_subject(
        scene_or_animate, timeline_or_none, settings
    )
    draft_canvas = canvas or _analysis_canvas(shot.canvas)
    draft_trace = _analysis_trace(shot.trace)
    frame_indices = (
        renderer_mod._sample_frame_indices(timeline, None, count)
        if frames is None
        else list(frames)
    )

    profiles: list[LookProfile] = []
    for look in candidate_looks:
        draft_shot = Shot(canvas=draft_canvas, look=look, trace=draft_trace)
        stats = renderer_mod.render_stats(
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
    binary: str = renderer_mod.DEFAULT_BINARY,
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

    animate, timeline, shot = _resolve_analysis_subject(
        scene_or_animate, timeline_or_none, settings
    )
    draft_canvas = canvas or _analysis_canvas(shot.canvas)
    draft_trace = _analysis_trace(shot.trace)
    frame_indices = (
        renderer_mod._sample_frame_indices(timeline, None, count)
        if frames is None
        else list(frames)
    )

    draft_shot = Shot(canvas=draft_canvas, look=candidate_look, trace=draft_trace)
    stats = renderer_mod.render_stats(
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
