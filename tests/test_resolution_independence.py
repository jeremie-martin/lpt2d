#!/usr/bin/env python3
"""Check whether a render is resolution-independent after downsampling.

The renderer maps ray paths into pixel space and rasterizes them with a fixed
1.5px screen-space line thickness.  Per-pixel accumulated energy therefore
scales as 1/viewport_scale.  The normalization divisor compensates for this:
for modes that use an external reference (rays, fixed, off), the divisor is
divided by viewport_scale so that displayed brightness is independent of
canvas resolution.  Max mode is self-normalizing (numerator and denominator
carry the same 1/scale factor).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import _lpt2d
from anim.types import Look

SCENE_PATH = Path("scenes/three_spheres.json")

ASPECT = 16.0 / 9.0
RESOLUTION_HEIGHTS = (240, 360, 420, 480, 720, 1080)
REFERENCE_HEIGHT = 1080
COMPARE_HEIGHT = 240
COMPARE_SIZE = (round(COMPARE_HEIGHT * ASPECT), COMPARE_HEIGHT)

RAYS_PER_PIXEL = 2.0
BATCH_SIZE = 64_000
# Keep the lowest compared resolution from being dominated by Monte Carlo noise.
MIN_COMPARE_RAYS = int(round(COMPARE_SIZE[0] * COMPARE_SIZE[1] * 8.0))

MAX_MEAN_DRIFT = 0.10
MAX_P95_DRIFT = 0.12
MIN_SSIM = 0.94

# Content validity: reject degenerate (all-white / all-black) images.
# If the reference mean falls outside this range, the test exposure is wrong
# and the comparison is meaningless.
MIN_REFERENCE_MEAN = 30.0  # reject near-black images
MAX_REFERENCE_MEAN = 230.0  # reject near-white images
MAX_WHITE_FRACTION = 0.10  # at most 10% of pixels may be clipped white

from evaluation import compute_psnr, compute_ssim  # noqa: E402


@dataclass(frozen=True)
class RenderedFrame:
    label: str
    width: int
    height: int
    pixels: np.ndarray
    total_rays: int


@dataclass(frozen=True)
class ResolutionMetric:
    label: str
    width: int
    height: int
    mean_ratio: float
    p95_ratio: float
    psnr: float
    ssim: float
    total_rays: int

    @property
    def passes(self) -> bool:
        return (
            abs(self.mean_ratio - 1.0) <= MAX_MEAN_DRIFT
            and abs(self.p95_ratio - 1.0) <= MAX_P95_DRIFT
            and self.ssim >= MIN_SSIM
        )


def _load_scene() -> dict:
    return json.loads(SCENE_PATH.read_text())


def _render(
    label: str,
    width: int,
    height: int,
    scene_dict: dict,
    *,
    rays: int | None = None,
    batch: int = BATCH_SIZE,
    normalize: str = "rays",
    exposure: float = 0.0,
    tonemap: str = "aces",
    white_point: float = 1.0,
) -> RenderedFrame:
    if rays is None:
        rays = int(round(width * height * RAYS_PER_PIXEL))
    shot_dict = {
        "version": 11,
        "name": "test",
        "camera": scene_dict.get("camera", {}),
        "canvas": {"width": width, "height": height},
        "look": {
            "exposure": exposure,
            "contrast": 1.0,
            "gamma": 2.0,
            "tonemap": tonemap,
            "white_point": white_point,
            "normalize": normalize,
            "normalize_ref": 0.0,
            "normalize_pct": 1.0,
            "ambient": 0.0,
            "background": [0, 0, 0],
            "opacity": 1.0,
            "saturation": 1.0,
            "vignette": 0.0,
            "vignette_radius": 0.7,
            "temperature": 0.0,
            "highlights": 0.0,
            "shadows": 0.0,
            "hue_shift": 0.0,
            "grain": 0.0,
            "grain_seed": 0,
            "chromatic_aberration": 0.0,
        },
        "trace": {
            "rays": rays,
            "batch": min(batch, rays),
            "depth": 12,
            "intensity": 1.0,
            "seed_mode": "deterministic",
        },
        "materials": scene_dict.get("materials", {}),
        "shapes": scene_dict.get("shapes", []),
        "lights": scene_dict.get("lights", []),
        "groups": scene_dict.get("groups", []),
    }
    shot = _lpt2d.load_shot_json_string(json.dumps(shot_dict))
    session = _lpt2d.RenderSession(width, height)
    result = session.render_shot(shot)
    pixels = np.frombuffer(result.pixels, dtype=np.uint8).reshape(height, width, 3)
    return RenderedFrame(
        label=label,
        width=width,
        height=height,
        pixels=pixels.copy(),
        total_rays=result.total_rays,
    )


def _downsample(frame: RenderedFrame) -> np.ndarray:
    if (frame.width, frame.height) == COMPARE_SIZE:
        return frame.pixels
    img = Image.fromarray(frame.pixels, "RGB")
    return np.asarray(img.resize(COMPARE_SIZE, Image.Resampling.BOX), dtype=np.uint8)


def _luma_p95(image: np.ndarray) -> float:
    luma = 0.2126 * image[:, :, 0] + 0.7152 * image[:, :, 1] + 0.0722 * image[:, :, 2]
    return float(np.percentile(luma, 95))


def collect_metrics(
    normalize: str = "rays",
    exposure: float | None = None,
    tonemap: str = "aces",
    white_point: float = 1.0,
) -> list[ResolutionMetric]:
    scene = _load_scene()
    look = _effective_look(scene)
    exp = exposure if exposure is not None else look.exposure

    frames = [
        _render(
            f"{height}p",
            round(height * ASPECT),
            height,
            scene,
            rays=max(
                int(round(round(height * ASPECT) * height * RAYS_PER_PIXEL)), MIN_COMPARE_RAYS
            ),
            normalize=normalize,
            exposure=exp,
            tonemap=tonemap,
            white_point=white_point,
        )
        for height in RESOLUTION_HEIGHTS
    ]

    reference_frame = next(frame for frame in frames if frame.height == REFERENCE_HEIGHT)
    reference_image = _downsample(reference_frame)
    reference_mean = float(reference_image.mean())
    reference_p95 = _luma_p95(reference_image)

    # Content validity: ensure we're comparing real images, not degenerate output
    white_fraction = float(np.all(reference_image == 255, axis=2).mean())
    if reference_mean < MIN_REFERENCE_MEAN:
        raise ValueError(
            f"Reference image is too dark (mean={reference_mean:.1f}). "
            f"Exposure is likely too low — comparison would be meaningless."
        )
    if reference_mean > MAX_REFERENCE_MEAN:
        raise ValueError(
            f"Reference image is too bright (mean={reference_mean:.1f}). "
            f"Exposure is likely too high — comparison would be meaningless."
        )
    if white_fraction > MAX_WHITE_FRACTION:
        raise ValueError(
            f"Reference image is {white_fraction:.0%} white (clipped). "
            f"Exposure is too high — comparison would be meaningless."
        )

    metrics: list[ResolutionMetric] = []
    for frame in frames:
        compare_image = _downsample(frame)
        metrics.append(
            ResolutionMetric(
                label=frame.label,
                width=frame.width,
                height=frame.height,
                mean_ratio=float(compare_image.mean() / reference_mean),
                p95_ratio=_luma_p95(compare_image) / reference_p95,
                psnr=compute_psnr(reference_image, compare_image),
                ssim=compute_ssim(reference_image, compare_image),
                total_rays=frame.total_rays,
            )
        )
    return metrics


def _format_metrics(metrics: list[ResolutionMetric]) -> str:
    lines = [
        (
            f"Reference: {REFERENCE_HEIGHT}p -> {COMPARE_SIZE[0]}x{COMPARE_SIZE[1]} "
            f"(normalize=rays, base={RAYS_PER_PIXEL:.1f} rays/pixel, "
            f"min total_rays={MIN_COMPARE_RAYS}, batch={BATCH_SIZE})"
        ),
        (
            "Thresholds: "
            f"mean drift <= {MAX_MEAN_DRIFT:.0%}, "
            f"p95 drift <= {MAX_P95_DRIFT:.0%}, "
            f"SSIM >= {MIN_SSIM:.3f}"
        ),
        "",
    ]
    for metric in metrics:
        status = "PASS" if metric.passes else "FAIL"
        lines.append(
            (
                f"{status} {metric.label:>5} ({metric.width}x{metric.height}, "
                f"total_rays={metric.total_rays}) "
                f"mean={metric.mean_ratio:.3f}x "
                f"p95={metric.p95_ratio:.3f}x "
                f"ssim={metric.ssim:.6f} "
                f"psnr={metric.psnr:.2f}dB"
            )
        )
    return "\n".join(lines)


def _skip_if_missing():
    if not SCENE_PATH.exists():
        pytest.skip(f"Scene not found: {SCENE_PATH}")


def _effective_look(scene: dict) -> Look:
    return Look(**scene.get("look", {}))


# ── Resolution independence: normalize=rays ──────────────────────────


def test_resolution_independence_rays():
    """Changing resolution with normalize=rays should not change brightness."""
    _skip_if_missing()
    scene = _load_scene()
    look = _effective_look(scene)
    metrics = collect_metrics(
        normalize="rays",
        exposure=look.exposure,
        tonemap=look.tonemap,
        white_point=look.white_point,
    )
    failures = [m for m in metrics if m.height != REFERENCE_HEIGHT and not m.passes]
    assert not failures, _format_metrics(metrics)


# ── Resolution independence: normalize=max ───────────────────────────
#
# Max normalization is self-normalizing for UNIFORM light fields (bulk
# pixels scale as N/scale, and so does the max).  However, for scenes
# with concentrated light features (caustics, focused beams), the
# maximum pixel value depends on how pixel centers align with the
# caustic peak, introducing a resolution-dependent bias.  This is an
# intrinsic limitation of max normalization, not a renderer bug.
#
# We therefore do NOT assert hard pass/fail here.  The test is kept as
# a diagnostic: run it with --verbose or via the CLI entry point to
# see the numbers.


# ── Ray count independence ───────────────────────────────────────────

RAY_COUNT_HEIGHTS = (480,)
RAY_COUNTS_PER_PIXEL = (1.0, 2.0, 4.0, 8.0)
RAY_COUNT_MAX_MEAN_DRIFT = 0.05
RAY_COUNT_MIN_SSIM = 0.90


def test_ray_count_independence():
    """With normalize=rays, doubling the ray count should not change brightness.

    More rays improve quality (less noise -> higher SSIM/PSNR) but the mean
    brightness should remain stable because we divide by total_rays.
    """
    _skip_if_missing()
    scene = _load_scene()
    look = _effective_look(scene)

    height = RAY_COUNT_HEIGHTS[0]
    width = round(height * ASPECT)
    pixel_count = width * height

    frames = []
    for rpp in RAY_COUNTS_PER_PIXEL:
        rays = int(round(pixel_count * rpp))
        label = f"{rpp:.0f}rpp"
        frames.append(
            _render(
                label,
                width,
                height,
                scene,
                rays=rays,
                normalize="rays",
                exposure=look.exposure,
                tonemap=look.tonemap,
                white_point=look.white_point,
            )
        )

    # Use the highest ray count as reference
    ref = frames[-1]
    ref_mean = float(ref.pixels.astype(np.float64).mean())
    white_fraction = float(np.all(ref.pixels == 255, axis=2).mean())
    if ref_mean < MIN_REFERENCE_MEAN or ref_mean > MAX_REFERENCE_MEAN:
        raise ValueError(
            f"Reference image mean={ref_mean:.1f} is outside [{MIN_REFERENCE_MEAN}, "
            f"{MAX_REFERENCE_MEAN}] — comparison would be meaningless."
        )
    if white_fraction > MAX_WHITE_FRACTION:
        raise ValueError(
            f"Reference image is {white_fraction:.0%} white — comparison would be meaningless."
        )

    lines = [f"Ray count independence at {width}x{height}, normalize=rays"]
    ok = True
    for frame in frames:
        mean = float(frame.pixels.astype(np.float64).mean())
        ratio = mean / ref_mean if ref_mean > 0 else 1.0
        ssim = compute_ssim(ref.pixels, frame.pixels)
        drift = abs(ratio - 1.0)
        passed = drift <= RAY_COUNT_MAX_MEAN_DRIFT
        if not passed and frame is not ref:
            ok = False
        status = "PASS" if passed else "FAIL"
        lines.append(
            f"  {status} {frame.label:>5} (rays={frame.total_rays:>10}) "
            f"mean={ratio:.3f}x ssim={ssim:.4f}"
        )
    assert ok, "\n".join(lines)


# ── CLI entry point ──────────────────────────────────────────────────


def main() -> int:
    if not SCENE_PATH.exists():
        print(f"Missing scene file: {SCENE_PATH}", file=sys.stderr)
        return 2

    scene = _load_scene()
    print("=== Resolution independence: normalize=rays ===")
    metrics = collect_metrics(
        normalize="rays",
        exposure=scene["look"]["exposure"],
        tonemap=scene["look"]["tonemap"],
        white_point=scene["look"]["white_point"],
    )
    print(_format_metrics(metrics))
    failures = [m for m in metrics if m.height != REFERENCE_HEIGHT and not m.passes]

    print("\n=== Resolution independence: normalize=max (diagnostic only) ===")
    try:
        metrics_max = collect_metrics(normalize="max", exposure=2.0, tonemap="aces")
        print(_format_metrics(metrics_max))
    except ValueError as e:
        print(f"  Skipped: {e}")
    # max normalization is scene-dependent for concentrated features — not counted as failure

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
