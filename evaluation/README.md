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
  multiple deterministic frames across multiple repeated launches.

The benchmark unit is a benchmark case:

- one scene
- at one deterministic frame
- measured across repeated launches

Each case gets its own median render time. Evaluation then normalizes each
case median against the captured baseline case median and aggregates those
ratios with a geometric mean.

The primary optimization target is therefore `render_ratio_gmean`. Lower is
better. The reciprocal `render_speedup_gmean` is also reported for readability.
This avoids letting a single heavy case dominate the score just because its raw
milliseconds are larger.

## Command-line usage

```bash
# One-time: capture baseline (builds first)
python -m evaluation capture

# After code changes: build + evaluate against baseline
python -m evaluation

# Skip build if you already rebuilt
python -m evaluation --skip-build

# Control the evaluation contract explicitly
python -m evaluation --frames 5 --launches 5 --warmup 1
python -m evaluation --resolution 1280x720 --rays 2000000
```

Output:
```
overall:    PASS ratio=0.9731 speedup=1.0276x render_case=402.5ms scenes=3 cases=15 samples=75

verdict:    pass
fidelity_verdict: pass
scenes:     3
cases:      15
frames:     5
launches:   5
samples:    75
render_case_median_ms: 402.5
render_ratio_gmean: 0.973125
render_speedup_gmean: 1.027617
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

This is the right primitive for repeated measurement, but the full evaluation
harness should compare per-case medians against a fixed baseline instead of
pooling raw samples across different cases.

## Scene evaluation contract

For the full evaluation harness, use `benchmark_scene()`:

```python
from evaluation import benchmark_scene

measurement = benchmark_scene(
    "evaluation/scenes/solid_surface_gallery.json",
    frames=5,
    launches=5,
    warmup=1,
)
print(measurement.cases[0].render_summary.median_ms)   # frame 0 across launches
print(measurement.case_render_summary.median_ms)       # summary across case medians
print(measurement.pooled_render_summary.median_ms)     # pooled raw samples (diagnostic only)
print(measurement.sample_count)                        # launches * frames
```

This matches the CLI contract:

- `frames`: deterministic benchmark cases per scene
- `launches`: repeated measurements per case
- `warmup`: discarded frames inside each fresh session
- `resolution`: evaluation render resolution, default `1280x720`
- `rays`: evaluation ray count, default `2000000`

The primary speed metric remains `RenderResult.time_ms`. The harness also
records a Python wall-clock timing around each `render_shot()` call so the
report can show whether the engine timing and end-to-end call timing stay
aligned.

The benchmark score is computed as:

1. for each case, take the median across launches
2. divide by the baseline case median
3. aggregate all case ratios with a geometric mean

That score is the single optimization metric. Pooled raw sample medians remain
available in JSON for diagnostics only.

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
- `render_case_median_ms:`
- `render_ratio_gmean:`
- `render_speedup_gmean:`
- `wall_ratio_gmean:`
- `wall_speedup_gmean:`

The JSON report stays detailed; the terminal report stays concise.

## Benchmark Hygiene

For reliable Linux benchmarking, keep the environment as controlled as
practical:

- run the machine otherwise idle
- prefer a stable CPU governor such as `performance`
- avoid thermal drift when comparing runs
- keep the scene corpus, frame count, launch count, and warm-up count fixed
- compare only runs captured under the same evaluation contract
- keep a fixed baseline capture as the anchor for the whole optimization loop

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
