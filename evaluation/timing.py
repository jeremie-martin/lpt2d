"""Repeated timing measurement with warm-up and statistical summary."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from statistics import mean, median, stdev
import json
import tempfile
import time
from typing import Any


@dataclass(frozen=True)
class TimingSummary:
    """Statistical summary of repeated render timings."""

    times_ms: list[float]
    median_ms: float
    mean_ms: float
    std_ms: float
    min_ms: float
    max_ms: float
    repeats: int

    @property
    def cv_pct(self) -> float:
        """Coefficient of variation (%) — lower means more stable."""
        if self.mean_ms < 1e-6:
            return 0.0
        return self.std_ms / self.mean_ms * 100


@dataclass(frozen=True)
class SpeedupResult:
    """Comparison of two timing summaries."""

    baseline: TimingSummary
    candidate: TimingSummary
    speedup: float  # baseline_median / candidate_median (>1 = faster)
    confidence: str  # "confirmed", "likely", "noise", "regression", "confirmed_regression"


@dataclass(frozen=True)
class RatioSummary:
    """Summary of normalized timing ratios against a fixed baseline."""

    ratios: list[float]
    geometric_mean: float
    median: float
    min: float
    max: float
    count: int

    @property
    def speedup_gmean(self) -> float:
        """Reciprocal of the geometric mean ratio (>1 = faster than baseline)."""
        if self.geometric_mean <= 0:
            return 0.0
        return 1.0 / self.geometric_mean


@dataclass(frozen=True)
class TimedFrame:
    """One timed frame measurement from a specific launch."""

    launch_index: int
    frame_index: int
    render_time_ms: float
    wall_time_ms: float
    result: Any


@dataclass(frozen=True)
class CaseBenchmark:
    """Timing for one benchmark case (one deterministic frame) across launches."""

    frame_index: int
    samples: list[TimedFrame]
    render_summary: TimingSummary
    wall_summary: TimingSummary

    @property
    def repeats(self) -> int:
        return len(self.samples)


@dataclass(frozen=True)
class SceneBenchmark:
    """Detailed timing for one scene across launches and benchmark cases."""

    samples: list[TimedFrame]
    cases: dict[int, CaseBenchmark]
    case_scene_jsons: dict[int, str]
    warmup_scene_json: str
    pooled_render_summary: TimingSummary
    pooled_wall_summary: TimingSummary
    case_render_summary: TimingSummary
    case_wall_summary: TimingSummary
    launches: int
    frames_per_launch: int
    warmup: int

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def case_count(self) -> int:
        return len(self.cases)


def summarize_times(times: list[float]) -> TimingSummary:
    """Build a TimingSummary from raw timing samples."""
    if not times:
        raise ValueError("At least one timing sample is required")

    std = stdev(times) if len(times) >= 2 else 0.0
    return TimingSummary(
        times_ms=times,
        median_ms=median(times),
        mean_ms=mean(times),
        std_ms=std,
        min_ms=min(times),
        max_ms=max(times),
        repeats=len(times),
    )


def summarize_ratios(ratios: list[float]) -> RatioSummary:
    """Build a RatioSummary from normalized candidate/baseline ratios."""
    if not ratios:
        raise ValueError("At least one ratio is required")
    if any(ratio <= 0 for ratio in ratios):
        raise ValueError("Ratios must be > 0")

    log_mean = sum(math.log(ratio) for ratio in ratios) / len(ratios)
    return RatioSummary(
        ratios=ratios,
        geometric_mean=math.exp(log_mean),
        median=median(ratios),
        min=min(ratios),
        max=max(ratios),
        count=len(ratios),
    )


def benchmark(
    session,
    shot,
    *,
    repeats: int = 5,
    warmup: int = 1,
    frame_index: int = 0,
):
    """Render a shot repeatedly and return timing statistics.

    Args:
        session: ``_lpt2d.RenderSession`` instance.
        shot: ``_lpt2d.Shot`` to render.
        repeats: Number of timed renders (default 5).
        warmup: Number of warm-up renders to discard (default 1).
        frame_index: Frame index passed to ``render_shot``.

    Returns:
        ``(TimingSummary, RenderResult)`` — the summary covers timing only;
        the RenderResult is from the last timed render (for fidelity comparison).
    """
    # Warm-up renders (discard results, prime GPU pipeline)
    for _ in range(warmup):
        session.render_shot(shot, frame_index)

    # Timed renders
    times: list[float] = []
    last_result = None
    for _ in range(repeats):
        result = session.render_shot(shot, frame_index)
        times.append(result.time_ms)
        last_result = result

    return summarize_times(times), last_result


def _apply_render_settings(shot, *, width: int | None, height: int | None, rays: int | None):
    """Apply evaluation render settings to a loaded shot in place."""
    if width is not None:
        shot.canvas.width = width
    if height is not None:
        shot.canvas.height = height
    if rays is not None:
        shot.trace.rays = rays
    return shot


def _scene_json_text(scene_dict: dict) -> str:
    return json.dumps(scene_dict, indent=2) + "\n"


def _build_benchmark_inputs(
    scene_path: str,
    frames: int,
    *,
    width: int | None,
    height: int | None,
    rays: int | None,
):
    """Prepare a warm-up shot plus deterministic benchmark cases."""
    import _lpt2d

    from .animate import animate_scene

    if frames < 1:
        raise ValueError("frames must be >= 1")

    scene_dict = json.loads(Path(scene_path).read_text())
    warmup_scene_json = _scene_json_text(scene_dict)
    case_scene_jsons: dict[int, str] = {}
    case_shots = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        warmup_path = tmp_root / "warmup.json"
        warmup_path.write_text(warmup_scene_json)
        warmup_shot = _apply_render_settings(
            _lpt2d.load_shot(str(warmup_path)),
            width=width,
            height=height,
            rays=rays,
        )

        for case_index in range(frames):
            if frames == 1:
                case_scene_json = warmup_scene_json
            else:
                case_scene_json = _scene_json_text(animate_scene(scene_dict, case_index, frames))

            case_path = tmp_root / f"case_{case_index:04d}.json"
            case_path.write_text(case_scene_json)
            case_shots.append(
                _apply_render_settings(
                    _lpt2d.load_shot(str(case_path)),
                    width=width,
                    height=height,
                    rays=rays,
                )
            )
            case_scene_jsons[case_index] = case_scene_json

    return warmup_shot, warmup_scene_json, case_shots, case_scene_jsons


def _close_session(session: Any) -> None:
    """Release a RenderSession deterministically between launches."""
    close = getattr(session, "close", None)
    if callable(close):
        close()


def benchmark_scene(
    scene_path: str,
    *,
    frames: int = 1,
    launches: int = 1,
    warmup: int = 1,
    width: int | None = None,
    height: int | None = None,
    rays: int | None = None,
) -> SceneBenchmark:
    """Measure one scene across multiple fresh sessions and deterministic frames.

    The primary metric remains the engine-reported ``RenderResult.time_ms``.
    We also record a wall-clock timing around each ``render_shot()`` call so
    the evaluation report can show how closely the Python-side timing tracks
    the engine timing.
    """
    import _lpt2d

    if launches < 1:
        raise ValueError("launches must be >= 1")
    if warmup < 0:
        raise ValueError("warmup must be >= 0")

    warmup_shot, warmup_scene_json, case_shots, case_scene_jsons = _build_benchmark_inputs(
        scene_path,
        frames,
        width=width,
        height=height,
        rays=rays,
    )

    samples: list[TimedFrame] = []
    width = warmup_shot.canvas.width
    height = warmup_shot.canvas.height

    for launch_index in range(launches):
        session = _lpt2d.RenderSession(width, height)
        try:
            # Warm up the session on the base scene before the timed case sweep.
            for _ in range(warmup):
                session.render_shot(warmup_shot, 0)

            for frame_index, frame_shot in enumerate(case_shots):
                wall_t0 = time.perf_counter()
                result = session.render_shot(frame_shot, frame_index)
                wall_ms = (time.perf_counter() - wall_t0) * 1000.0
                render_ms = result.time_ms if result.time_ms > 0 else wall_ms
                samples.append(
                    TimedFrame(
                        launch_index=launch_index,
                        frame_index=frame_index,
                        render_time_ms=render_ms,
                        wall_time_ms=wall_ms,
                        result=result,
                    )
                )
        finally:
            _close_session(session)
            del session

    case_samples: dict[int, list[TimedFrame]] = {frame_index: [] for frame_index in range(frames)}
    for sample in samples:
        case_samples[sample.frame_index].append(sample)

    cases: dict[int, CaseBenchmark] = {}
    for frame_index in range(frames):
        frame_samples = case_samples[frame_index]
        cases[frame_index] = CaseBenchmark(
            frame_index=frame_index,
            samples=frame_samples,
            render_summary=summarize_times([sample.render_time_ms for sample in frame_samples]),
            wall_summary=summarize_times([sample.wall_time_ms for sample in frame_samples]),
        )

    return SceneBenchmark(
        samples=samples,
        cases=cases,
        case_scene_jsons=case_scene_jsons,
        warmup_scene_json=warmup_scene_json,
        pooled_render_summary=summarize_times([sample.render_time_ms for sample in samples]),
        pooled_wall_summary=summarize_times([sample.wall_time_ms for sample in samples]),
        case_render_summary=summarize_times(
            [case.render_summary.median_ms for case in cases.values()]
        ),
        case_wall_summary=summarize_times(
            [case.wall_summary.median_ms for case in cases.values()]
        ),
        launches=launches,
        frames_per_launch=frames,
        warmup=warmup,
    )


def benchmark_animated(
    scene_path: str,
    *,
    frames: int = 5,
    warmup: int = 1,
):
    """Render an animated sequence and return timing statistics.

    Each frame applies gentle transforms to scene groups so the GPU cannot
    cache across frames. This gives more representative timing on hardware
    with variable clocks (laptops, thermal throttling).

    Args:
        scene_path: Path to the scene JSON file.
        frames: Number of animated frames to render and time.
        warmup: Number of warm-up renders to discard.

    Returns:
        ``(TimingSummary, RenderResult)`` — the summary covers per-frame
        timing; the RenderResult is from frame 0 (static, for fidelity).
    """
    benchmark_result = benchmark_scene(scene_path, frames=frames, launches=1, warmup=warmup)
    fidelity_result = benchmark_result.samples[0].result
    return benchmark_result.case_render_summary, fidelity_result


def classify_speedup(baseline: TimingSummary, candidate: TimingSummary) -> SpeedupResult:
    """Compare two timing summaries and classify the speedup confidence.

    Confidence levels:
    - ``confirmed``: candidate's worst time beats baseline's best time.
    - ``likely``: median improved >5% with CV <10%.
    - ``noise``: change is within measurement noise.
    - ``regression``: median worsened >5% with CV <10%.
    - ``confirmed_regression``: candidate's best time is worse than baseline's worst.
    """
    b_med = baseline.median_ms
    c_med = candidate.median_ms
    speedup = b_med / c_med if c_med > 0 else 0.0

    if max(candidate.times_ms) < min(baseline.times_ms):
        confidence = "confirmed"
    elif min(candidate.times_ms) > max(baseline.times_ms):
        confidence = "confirmed_regression"
    elif b_med < 1e-6:
        confidence = "noise"
    else:
        change = (b_med - c_med) / b_med
        cv = candidate.cv_pct
        if change > 0.05 and cv < 10:
            confidence = "likely"
        elif change < -0.05 and cv < 10:
            confidence = "regression"
        else:
            confidence = "noise"

    return SpeedupResult(
        baseline=baseline,
        candidate=candidate,
        speedup=round(speedup, 4),
        confidence=confidence,
    )
