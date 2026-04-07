"""Repeated timing measurement with warm-up and statistical summary."""

from __future__ import annotations

from dataclasses import dataclass
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
class TimedFrame:
    """One timed frame measurement from a specific launch."""

    launch_index: int
    frame_index: int
    render_time_ms: float
    wall_time_ms: float
    result: Any


@dataclass(frozen=True)
class SceneBenchmark:
    """Detailed timing for one scene across launches and frames."""

    samples: list[TimedFrame]
    render_summary: TimingSummary
    wall_summary: TimingSummary
    launches: int
    frames_per_launch: int
    warmup: int

    @property
    def sample_count(self) -> int:
        return len(self.samples)


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


def _build_frame_shots(scene_path: str, frames: int):
    """Prepare deterministic frame shots once and reuse them across launches."""
    import _lpt2d

    from .animate import animate_scene

    if frames < 1:
        raise ValueError("frames must be >= 1")

    if frames == 1:
        return [_lpt2d.load_shot(scene_path)]

    scene_dict = json.loads(Path(scene_path).read_text())
    shots = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        for frame_index in range(frames):
            modified = animate_scene(scene_dict, frame_index, frames)
            tmp_path = tmp_root / f"frame_{frame_index:04d}.json"
            tmp_path.write_text(json.dumps(modified))
            shots.append(_lpt2d.load_shot(str(tmp_path)))
    return shots


def benchmark_scene(
    scene_path: str,
    *,
    frames: int = 1,
    launches: int = 1,
    warmup: int = 1,
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

    base_shot = _lpt2d.load_shot(scene_path)
    frame_shots = _build_frame_shots(scene_path, frames)

    samples: list[TimedFrame] = []
    width = base_shot.canvas.width
    height = base_shot.canvas.height

    for launch_index in range(launches):
        session = _lpt2d.RenderSession(width, height)

        for warmup_index in range(warmup):
            frame_index = warmup_index % frames
            session.render_shot(frame_shots[frame_index], frame_index)

        for frame_index, frame_shot in enumerate(frame_shots):
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

    return SceneBenchmark(
        samples=samples,
        render_summary=summarize_times([sample.render_time_ms for sample in samples]),
        wall_summary=summarize_times([sample.wall_time_ms for sample in samples]),
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
    return benchmark_result.render_summary, fidelity_result


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
