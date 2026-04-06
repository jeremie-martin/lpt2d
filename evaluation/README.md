# evaluation/

Fidelity comparison and timing measurement for lpt2d. This module provides
the measurement surface for autonomous optimization — render a frame, compare
it against a reference, get a machine-readable verdict.

## Command-line usage

```bash
# One-time: capture baseline (builds first)
python -m evaluation capture

# After code changes: build + evaluate against baseline
python -m evaluation

# Skip build if you already rebuilt
python -m evaluation --skip-build
```

Output:
```
  solid_surface_gallery: PASS  psnr=105.7dB ssim=1.000000  565.7ms  speedup=1.000x (noise)

verdict:    pass
scenes:     1
median_ms:  565.7
total  speedup: 1.000x
```

Exit code 0 = all scenes pass, 1 = fidelity failure, 2 = setup error,
3 = no baseline.

## Build

After any C++ or shader change, rebuild and reinstall the Python package:

```bash
cmake --build build -j$(nproc)
uv pip install -e .
```

Both steps are required — the C++ build produces the shared library, and
`uv pip install -e .` makes it importable as `_lpt2d`. Skipping the reinstall
means Python will use a stale binary. `python -m evaluation` handles both
steps automatically unless `--skip-build` is passed.

## Quick start

```python
import _lpt2d
from evaluation import compare_render_results, save_baseline, load_baseline, compare_to_baseline

# Render a scene
shot = _lpt2d.load_shot("evaluation/scenes/solid_surface_gallery.json")
session = _lpt2d.RenderSession(1920, 1080)

# Warm-up render (first frame includes shader compilation overhead)
_ = session.render_shot(shot)

# Timed render
result = session.render_shot(shot)
print(f"{result.time_ms:.1f} ms")
```

## Timing

`RenderResult.time_ms` is wall-clock time measured inside C++
`render_frame()`. It covers the full GPU pipeline: scene upload, ray tracing,
post-processing, pixel readback, and metrics computation. The `glFinish()`
inside `read_pixels()` ensures GPU work is drained before the clock stops.

The first render after session creation includes one-time costs (shader
compilation, buffer allocation). Always do a warm-up render before timing.

## Benchmarking (repeated timing)

For statistically sound timing, use `benchmark()` which handles warm-up and
repeated measurement:

```python
from evaluation import benchmark, classify_speedup

# Render 5 times with 1 warm-up, get timing stats + last RenderResult
summary, result = benchmark(session, shot, repeats=5, warmup=1)
print(f"{summary.median_ms:.1f} ms (std={summary.std_ms:.1f}, n={summary.repeats})")
print(f"CV: {summary.cv_pct:.1f}%")  # coefficient of variation

# Compare two timing summaries for speedup confidence
baseline_summary, baseline_result = benchmark(session, baseline_shot)
candidate_summary, candidate_result = benchmark(session, candidate_shot)

speedup = classify_speedup(baseline_summary, candidate_summary)
print(f"{speedup.speedup:.3f}x ({speedup.confidence})")
# confidence: "confirmed", "likely", "noise", "regression", "confirmed_regression"
```

This is what an optimization loop should use — not raw `time_ms`.

## Comparing two renders

```python
# Direct comparison of two RenderResult objects
cr = compare_render_results(result_a, result_b)
print(cr.verdict)      # Verdict.PASS / WARN / FAIL
print(cr.psnr)         # dB (inf = identical)
print(cr.ssim)         # 0-1
print(cr.max_diff)     # max per-channel pixel difference
print(cr.time_a_ms)    # timing from result A
print(cr.time_b_ms)    # timing from result B

# FrameMetrics comparison (secondary diagnostic signal)
if cr.metrics:
    print(cr.metrics.histogram_overlap)  # 1.0 = identical distribution
    print(cr.metrics.warnings)           # threshold violations
```

## Comparing against a saved baseline

```python
# Save a baseline
save_baseline("baselines/gallery", result, metadata={"commit": "abc123"})

# Later: load and compare
baseline = load_baseline("baselines/gallery")
cr = compare_to_baseline(new_result, baseline)
print(cr.verdict, cr.psnr)
```

Baseline directory layout:
```
baselines/gallery/
  image.png          # reference render
  metadata.json      # metrics, timing, custom metadata
```

## Comparing numpy arrays directly

```python
from evaluation import compare_images
import numpy as np
from PIL import Image

a = np.asarray(Image.open("before.png").convert("RGB"))
b = np.asarray(Image.open("after.png").convert("RGB"))
cr = compare_images(a, b)
```

## Verdict thresholds

| Verdict | PSNR     | SSIM    | Max diff |
|---------|----------|---------|----------|
| PASS    | >= 45 dB | >= 0.995 | <= 10   |
| WARN    | >= 40 dB | >= 0.98  | (any)   |
| FAIL    | below WARN thresholds          |

Thresholds are configurable:

```python
from evaluation import Thresholds

strict = Thresholds(pass_psnr=50.0, pass_ssim=0.999, pass_max_diff=5)
cr = compare_render_results(a, b, thresholds=strict)
```

FrameMetrics secondary signal thresholds (produce warnings, don't override
pixel verdict):

| Metric              | Default threshold |
|---------------------|-------------------|
| mean_lum_delta      | <= 5.0            |
| histogram_overlap   | >= 0.98           |
| p50_delta           | <= 10.0           |
| p95_delta           | <= 15.0           |
| pct_black_delta     | <= 0.05           |
| pct_clipped_delta   | <= 0.05           |

## Reference scenes

`evaluation/scenes/` contains authored scenes for benchmarking. These are
purpose-built to exercise diverse renderer paths (geometry types, materials,
light types, groups, transforms).

## Individual metrics

```python
from evaluation import compute_psnr, compute_ssim, compute_mse, max_abs_diff

psnr = compute_psnr(a, b)   # dB
ssim = compute_ssim(a, b)   # 0-1
mse  = compute_mse(a, b)    # float
md   = max_abs_diff(a, b)   # int 0-255
```

All metric functions take `(H, W, 3)` uint8 numpy arrays.
