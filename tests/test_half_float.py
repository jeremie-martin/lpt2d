"""Half-float (fast mode) fidelity: GL_RGB16F vs GL_RGB32F accumulation.

At low ray counts the two formats should produce near-identical images.
As ray count increases, fp16 precision loss becomes measurable.  These
tests quantify that curve using the crystal_field evaluation scene.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from evaluation import compare_render_results
from evaluation.image_metrics import compute_psnr

try:
    import _lpt2d
except ImportError:
    pytest.skip("_lpt2d not available", allow_module_level=True)

SCENE = Path(__file__).resolve().parent.parent / "evaluation" / "scenes" / "crystal_field.json"
W, H = 256, 144  # 16:9, small enough for fast tests

# (rays, min_psnr_db, min_ssim)
# Floors set ~10 dB / 0.001 below observed values to absorb GPU variance.
# Observed (2026-04, 256x144): 1k=64.9/1.000, 10k=62.1/1.000, 50k=59.1/0.9998, 128k=56.5/0.9993
LEVELS = [
    (1_000, 55.0, 0.999),
    (10_000, 52.0, 0.999),
    (50_000, 48.0, 0.998),
    (128_000, 45.0, 0.995),
]


def _load():
    if not SCENE.exists():
        pytest.skip("crystal_field.json not found")
    return _lpt2d.load_shot(str(SCENE))


def _render(shot, half_float: bool) -> _lpt2d.RenderResult:
    session = _lpt2d.RenderSession(W, H, half_float)
    try:
        return session.render_shot(shot)
    finally:
        session.close()


def _pixels(result) -> np.ndarray:
    return np.frombuffer(result.pixels, dtype=np.uint8).reshape(result.height, result.width, 3)


# ── Per-level fidelity ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rays, min_psnr, min_ssim",
    LEVELS,
    ids=[f"{r // 1000}k" for r, *_ in LEVELS],
)
def test_half_float_fidelity(rays, min_psnr, min_ssim):
    """fp16 renders should match fp32 within expected tolerances."""
    shot = _load()
    shot.trace.rays = rays
    shot.trace.seed_mode = "deterministic"

    ref = _render(shot, half_float=False)
    fast = _render(shot, half_float=True)

    cmp = compare_render_results(ref, fast)

    t_ref = f"{cmp.time_a_ms:.1f}ms" if cmp.time_a_ms else "n/a"
    t_fast = f"{cmp.time_b_ms:.1f}ms" if cmp.time_b_ms else "n/a"
    print(
        f"\n  {rays:>7,} rays: PSNR={cmp.psnr:.1f} dB  SSIM={cmp.ssim:.4f}  "
        f"max_diff={cmp.max_diff}  changed={cmp.pct_changed:.1%}  "
        f"fp32={t_ref}  fp16={t_fast}"
    )

    assert cmp.psnr >= min_psnr, f"PSNR {cmp.psnr:.1f} dB below {min_psnr} dB floor at {rays} rays"
    assert cmp.ssim >= min_ssim, f"SSIM {cmp.ssim:.4f} below {min_ssim} floor at {rays} rays"


# ── Monotonic degradation ────────────────────────────────────────────


def test_degradation_increases_with_rays():
    """Quality gap between fp16 and fp32 should widen as ray count grows."""
    shot = _load()
    shot.trace.seed_mode = "deterministic"

    psnrs: list[tuple[int, float]] = []
    for rays, *_ in LEVELS:
        shot.trace.rays = rays
        ref = _render(shot, half_float=False)
        fast = _render(shot, half_float=True)
        psnr = compute_psnr(_pixels(ref), _pixels(fast))
        psnrs.append((rays, psnr))

    print("\n  Degradation curve:")
    for rays, psnr in psnrs:
        print(f"    {rays:>7,} rays: PSNR = {psnr:.1f} dB")

    # Each step should have equal or lower PSNR (allow 2 dB noise margin)
    for i in range(1, len(psnrs)):
        prev_rays, prev_psnr = psnrs[i - 1]
        curr_rays, curr_psnr = psnrs[i]
        assert curr_psnr <= prev_psnr + 2.0, (
            f"Quality improved from {prev_rays} rays ({prev_psnr:.1f} dB) to "
            f"{curr_rays} rays ({curr_psnr:.1f} dB) — expected monotonic degradation"
        )


# ── Speed advantage ──────────────────────────────────────────────────


def test_half_float_is_faster():
    """Fast mode should not be slower than full precision."""
    shot = _load()
    shot.trace.rays = 128_000
    shot.trace.seed_mode = "deterministic"

    ref = _render(shot, half_float=False)
    fast = _render(shot, half_float=True)

    if ref.time_ms <= 0 or fast.time_ms <= 0:
        pytest.skip("render timing not available")

    speedup = ref.time_ms / fast.time_ms
    print(f"\n  128k rays: fp32={ref.time_ms:.1f}ms  fp16={fast.time_ms:.1f}ms  speedup={speedup:.2f}x")

    # Soft floor — timing is noisy, just verify it's not dramatically slower
    assert speedup > 0.7, f"Fast mode unexpectedly slow: speedup={speedup:.2f}x"
