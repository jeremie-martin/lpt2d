"""Scene analysis utilities: auto_look, compare_looks, look_report."""

from __future__ import annotations

import math
from typing import cast

from . import renderer as renderer_mod
from .stats import (
    FrameStats,
    LookComparison,
    LookProfile,
    LookReport,
)
from .types import (
    AnimateFn,
    Camera2D,
    Canvas,
    Frame,
    FrameContext,
    Look,
    Quality,
    RenderSession,
    Scene,
    Shot,
    Timeline,
    TraceDefaults,
    _apply_look_override,
)

_ANALYSIS_CANVAS = Canvas(width=480, height=480)
_ANALYSIS_TRACE = TraceDefaults(rays=500_000, batch=100_000, depth=12)


def _analysis_canvas(base: Canvas | None) -> Canvas:
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
    ref = base or TraceDefaults()
    chosen_rays = ref.rays if rays is None else rays
    return TraceDefaults(
        rays=min(chosen_rays, _ANALYSIS_TRACE.rays) if rays is None else chosen_rays,
        batch=min(ref.batch, _ANALYSIS_TRACE.batch),
        depth=min(ref.depth, _ANALYSIS_TRACE.depth),
        intensity=ref.intensity,
        seed_mode=ref.seed_mode,
    )


def _analysis_result_look(
    authored: Look,
    *,
    tonemap: str,
    normalize: str,
    normalize_ref: float = 0.0,
) -> Look:
    look = _apply_look_override(authored, {"tonemap": tonemap, "normalize": normalize})
    if normalize_ref > 0.0:
        look = _apply_look_override(look, {"normalize_ref": normalize_ref})
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
        shot = Shot(name=shot.name, scene=shot.scene, camera=camera, canvas=shot.canvas,
                    look=shot.look, trace=shot.trace)
    if canvas is not None:
        shot = Shot(name=shot.name, scene=shot.scene, camera=shot.camera, canvas=canvas,
                    look=shot.look, trace=shot.trace)
    if look is not None:
        shot = Shot(name=shot.name, scene=shot.scene, camera=shot.camera, canvas=shot.canvas,
                    look=look, trace=shot.trace)
    if trace is not None:
        shot = Shot(name=shot.name, scene=shot.scene, camera=shot.camera, canvas=shot.canvas,
                    look=shot.look, trace=trace)
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
    frame: int | None = None,
    sample_count: int = 8,
) -> Look:
    """Analyze a scene and return a Look with good exposure settings."""
    animate, timeline, shot = _resolve_analysis_subject(
        scene_or_animate, timeline_or_none, settings
    )
    analysis_frames = renderer_mod._sample_frame_indices(timeline, frame, sample_count)

    draft_canvas = canvas or _analysis_canvas(shot.canvas)
    draft_trace = _analysis_trace(shot.trace)
    chosen_tonemap = shot.look.tonemap if tonemap is None else tonemap
    chosen_normalize = shot.look.normalize if normalize is None else normalize

    def measure_per_frame(look: Look) -> list[tuple[int, float, FrameStats]]:
        draft_shot = Shot(canvas=draft_canvas, look=look, trace=draft_trace)
        return renderer_mod.render_stats(
            animate,
            timeline,
            frames=analysis_frames,
            settings=draft_shot,
            camera=camera or shot.camera,
            fast=True,
        )

    chosen_normalize_ref = 0.0
    if chosen_normalize == "fixed":
        chosen_normalize_ref = calibrate_normalize_ref(
            animate,
            timeline,
            settings=Shot(canvas=draft_canvas, trace=draft_trace),
            camera=camera or shot.camera,
            frame=analysis_frames,
        )

    result_base = _analysis_result_look(
        shot.look,
        tonemap=chosen_tonemap,
        normalize=chosen_normalize,
        normalize_ref=chosen_normalize_ref,
    )

    baseline_look = _apply_look_override(result_base, {"exposure": -5.0})
    per_frame = measure_per_frame(baseline_look)
    if not per_frame:
        return result_base

    brightnesses = [s.mean / 255.0 for _, _, s in per_frame]
    measured_mean = sum(brightnesses) / len(brightnesses)

    if len(brightnesses) > 1:
        std_b = (
            sum((b - measured_mean) ** 2 for b in brightnesses) / (len(brightnesses) - 1)
        ) ** 0.5
        if std_b > 0.05:
            sorted_b = sorted(brightnesses)
            measured_mean = sorted_b[len(sorted_b) // 4]

    if measured_mean > 0.001:
        exposure = -5.0 + math.log2(target_mean / measured_mean)
    else:
        exposure = -1.0

    exposure = max(-15.0, min(exposure, 10.0))
    best_exposure = exposure

    candidate_stats = measure_per_frame(_apply_look_override(result_base, {"exposure": exposure}))
    if candidate_stats:
        candidate_clipping = max(s.pct_clipped for _, _, s in candidate_stats)
        if candidate_clipping > max_clipping:
            low = -15.0
            high = exposure
            best_exposure = low
            for _ in range(8):
                mid = (low + high) * 0.5
                mid_stats = measure_per_frame(
                    _apply_look_override(result_base, {"exposure": mid})
                )
                if not mid_stats:
                    high = mid
                    continue
                mid_clipping = max(s.pct_clipped for _, _, s in mid_stats)
                if mid_clipping <= max_clipping:
                    best_exposure = mid
                    low = mid
                else:
                    high = mid

    return _apply_look_override(result_base, {"exposure": round(best_exposure, 2)})


def calibrate_normalize_ref(
    animate: AnimateFn,
    timeline: Timeline | float,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    fast: bool = False,
    frame: int | list[int] | None = 0,
) -> float:
    """Render frames with max-normalize to determine a good normalize_ref."""
    timeline, shot = renderer_mod._resolve_args(timeline, settings)
    frames = [frame] if isinstance(frame, int) else frame
    frame_indices = [0] if frames is None else list(frames)

    cal_shot = shot.with_look(normalize="max", normalize_pct=1.0)
    session = RenderSession(cal_shot.canvas.width, cal_shot.canvas.height, fast)

    max_hdr = 0.0
    for fi in frame_indices:
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = renderer_mod._resolve_frame_shot(cal_shot, result, camera)
        render_result = session.render_shot(cpp_shot, fi)
        if render_result.max_hdr <= 0:
            raise RuntimeError("Calibration failed: no max_hdr")
        max_hdr = max(max_hdr, render_result.max_hdr)
    return max_hdr


def compare_looks(
    scene_or_animate: Scene | Shot | AnimateFn,
    timeline_or_looks: Timeline | float | list[Look] | None = None,
    looks: list[Look] | None = None,
    *,
    settings: Shot | Quality | str | None = None,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    count: int = 8,
    frames: list[int] | None = None,
) -> LookComparison:
    """Render candidate Looks against the same frames and compare."""
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
    count: int = 12,
    frames: list[int] | None = None,
    dark_threshold: float = 0.15,
    bright_threshold: float = 0.70,
    clip_threshold: float = 0.05,
    contrast_threshold: float = 30.0,
) -> LookReport:
    """Diagnose how a Look performs across an animation's timeline."""
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
