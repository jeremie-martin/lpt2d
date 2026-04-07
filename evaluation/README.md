# evaluation/

Fidelity comparison and timing measurement for lpt2d. This module provides
the measurement surface for autonomous optimization — render a frame, compare
it against a reference, get a machine-readable verdict.

## Purpose

This is the authoritative evaluation surface for `lpt2d` renderer work.

- It measures renderer speed in a way that is stable enough for benchmarking
  and optimization loops.
- It measures renderer fidelity in a way that can reject meaningful visual
  regressions.
- It aims to stay representative of real Python animation usage by timing
  multiple deterministic frames across multiple fresh render sessions.

The primary optimization target is the reported render median. A lower
`render_median_ms` should correspond to a real renderer improvement, not a
scene-specific trick or a noisy measurement artifact.

## Command-line usage

```bash
# One-time: capture baseline (builds first)
python -m evaluation capture

# After code changes: build + evaluate against baseline
python -m evaluation

# Skip build if you already rebuilt
python -m evaluation --skip-build

# Control the evaluation contract explicitly
python -m evaluation --frames 5 --launches 3 --warmup 1
python -m evaluation --resolution 1280x720 --rays 2000000
```

Output:
```
overall:    PASS render=565.7ms wall=566.2ms scenes=3 samples=45

verdict:    pass
scenes:     3
frames:     5
launches:   3
samples:    45
median_ms:  565.7
wall_ms:    566.2
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

## Scene evaluation contract

For the full evaluation harness, use `benchmark_scene()`:

```python
from evaluation import benchmark_scene

measurement = benchmark_scene(
    "evaluation/scenes/solid_surface_gallery.json",
    frames=5,
    launches=3,
    warmup=1,
)
print(measurement.render_summary.median_ms)
print(measurement.wall_summary.median_ms)
print(measurement.sample_count)  # launches * frames
```

This matches the CLI contract:

- `frames`: deterministic frames compared against matching baseline frames
- `launches`: fresh `RenderSession` instances per scene
- `warmup`: discarded frames inside each fresh session
- `resolution`: evaluation render resolution, default `1280x720`
- `rays`: evaluation ray count, default `2000000`

The primary speed metric remains `RenderResult.time_ms`. The harness also
records a Python wall-clock timing around each `render_shot()` call so the
report can show whether the engine timing and end-to-end call timing stay
aligned.

The scene corpus is explicit and ordered via
[`evaluation/scenes/manifest.json`](/home/holo/prog/lpt2d/evaluation/scenes/manifest.json).
That file defines the benchmark set on purpose; the harness does not treat the
directory as an open-ended wildcard corpus.

## Build Contract

The evaluation command is intended to be the central validation command for
rendering work. It explicitly configures the build tree with
`-DCMAKE_BUILD_TYPE=Release` and builds with `--config Release` before running
evaluation.

The report records that requested build contract directly instead of trying to
reverse-engineer every CMake generator detail from cache files.

## Terminal Summary

The terminal output is intentionally grep-friendly. The key summary lines are:

- `fidelity_verdict:`
- `render_median_ms:`
- `wall_median_ms:`

The JSON report stays detailed; the terminal report stays concise.

## Benchmark Hygiene

For reliable Linux benchmarking, keep the environment as controlled as
practical:

- run the machine otherwise idle
- prefer a stable CPU governor such as `performance`
- avoid thermal drift when comparing runs
- keep the scene corpus, frame count, launch count, and warm-up count fixed
- compare only runs captured under the same evaluation contract

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

For multi-frame scene baselines:

```python
from evaluation import load_baseline_set, save_baseline_set

save_baseline_set(
    "baselines/gallery",
    {0: frame0_result, 1: frame1_result, 2: frame2_result},
    metadata={"frames": 3, "launches": 3, "warmup": 1},
)

baseline_set = load_baseline_set("baselines/gallery")
baseline_frame_1 = baseline_set["frames"][1]
cr = compare_to_baseline(new_frame_1_result, baseline_frame_1)
```

Baseline directory layout:
```
baselines/gallery/
  image.png          # legacy single-frame baseline
  frame_0000.png     # multi-frame baseline image
  frame_0001.png
  ...
  metadata.json      # metrics, timing, frame list, custom metadata
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
