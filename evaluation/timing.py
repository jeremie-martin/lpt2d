"""Repeated timing measurement with warm-up and statistical summary."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median, stdev


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

    std = stdev(times) if len(times) >= 2 else 0.0
    summary = TimingSummary(
        times_ms=times,
        median_ms=median(times),
        mean_ms=mean(times),
        std_ms=std,
        min_ms=min(times),
        max_ms=max(times),
        repeats=repeats,
    )
    return summary, last_result


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
    import json
    import tempfile
    from pathlib import Path

    import _lpt2d

    from .animate import animate_scene

    scene_dict = json.loads(Path(scene_path).read_text())

    # Load the unmodified shot for fidelity comparison and session setup
    shot = _lpt2d.load_shot(scene_path)
    session = _lpt2d.RenderSession(shot.canvas.width, shot.canvas.height)

    # Warm-up with animated frames
    for i in range(warmup):
        session.render_shot(shot, i)

    # Render frame 0 (static) for fidelity comparison
    fidelity_result = session.render_shot(shot, 0)

    # Timed animated renders
    times: list[float] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for f in range(frames):
            modified = animate_scene(scene_dict, f, frames)
            tmp_path = Path(tmpdir) / "frame.json"
            tmp_path.write_text(json.dumps(modified))
            frame_shot = _lpt2d.load_shot(str(tmp_path))
            result = session.render_shot(frame_shot, f)
            times.append(result.time_ms)

    std = stdev(times) if len(times) >= 2 else 0.0
    summary = TimingSummary(
        times_ms=times,
        median_ms=median(times),
        mean_ms=mean(times),
        std_ms=std,
        min_ms=min(times),
        max_ms=max(times),
        repeats=frames,
    )
    return summary, fidelity_result


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
