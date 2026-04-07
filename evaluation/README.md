# evaluation/

Evaluation harness for `lpt2d`: fidelity comparison and timing measurement.
Render a case, compare it against a reference, and emit a machine-readable
verdict.

## Purpose

This is the default evaluation harness for `lpt2d` renderer work.

- It measures renderer speed in a way that is stable enough for benchmarking
  and optimization loops.
- It measures renderer fidelity in a way that can reject meaningful visual
  regressions.
- It aims to stay representative of real Python animation usage by timing
  a fixed sweep of deterministic scene variants inside multiple fresh sessions.

## Glossary

- `base scene`: the original scene JSON before per-case animation is applied
- `case`: one deterministic scene variant identified by a frame index
- `frame`: the frame index used to generate a case
- `launch`: one fresh `RenderSession` sweep over all cases for a scene; not a new process
- `repeat`: repeated renders of the same shot within one existing session, used by `benchmark()`

Scoring is case-based:

- one scene
- at one deterministic frame index / scene variant
- measured across repeated launches (`launches`), where each launch is one fresh session

In the full harness, each case is rendered once per launch. Case medians are
taken across launches, not repeated renders within one session. Evaluation
then normalizes each case median against the captured baseline case median and
aggregates those ratios with a geometric mean.

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
overall:    PASS ratio=0.9731 speedup=1.0276x scenes=3 cases=15 samples=75

verdict:    pass
scenes:     3
cases:      15
frames:     5
launches:   5
warmup:     1 base-scene render per fresh session
samples:    75
render_sample_total_ms: 30187.5
baseline_render_sample_total_ms: 31020.4
wall_sample_total_ms: 30205.1
baseline_wall_sample_total_ms: 31043.8
render_ratio_gmean: 0.973125
render_speedup_gmean: 1.027617
wall_ratio_gmean: 0.981002
wall_speedup_gmean: 1.019366
```

Exit code `0` = all scenes pass, `1` = any fidelity `warn` or `fail`,
`2` = setup/build/baseline contract error, `3` = no baseline directory.
`warn` is therefore not severe enough to count as `FAIL` under the fidelity
thresholds, but it still makes the evaluation fail for automation purposes.

The optimization target is `render_ratio_gmean`. The raw sample totals in the
summary are diagnostic accounting, not the optimization score.

## Build

After any C++ or shader change, rebuild and reinstall the Python package:

```bash
cmake --build build -j$(nproc)
uv pip install -e .
```

Both steps are required — the C++ build produces the shared library, and
`uv pip install -e .` makes it importable as `_lpt2d`. Skipping the reinstall
can leave Python importing a stale or missing extension, depending on the
current editable-install state. `python -m evaluation` handles both steps
automatically unless `--skip-build` is passed.

## Quick start

```python
import _lpt2d
from evaluation import compare_render_results, save_baseline, load_baseline, compare_to_baseline

# Render a scene
shot = _lpt2d.load_shot("evaluation/scenes/solid_surface_gallery.json")
session = _lpt2d.RenderSession(1280, 720)

# Warm-up render (may include one-time session costs such as shader compilation)
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
compilation, buffer allocation). The harness treats warm-up as a session
warm-up on the base scene before the timed case sweep.

## Benchmarking (repeated timing)

For repeated timing of one shot inside one existing session, use `benchmark()`:

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

Here, `repeats` means repeated timed renders of the same shot within one
existing `RenderSession`. It does not mean evaluation `launches`.

`benchmark()` warm-up also differs from the full harness warm-up:

- `benchmark()`: repeated warm-up renders of the same shot in the current session
- `benchmark_scene()`: untimed base-scene renders in each fresh session before the case sweep

`benchmark()` is the right primitive for local repeated measurement, but the
full evaluation harness should compare per-case medians against a fixed
baseline instead of pooling raw samples across different cases.

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
print(measurement.cases[0].render_summary.median_ms)   # case 0 median across launches
print(sum(measurement.cases[0].render_summary.times_ms))  # total ms for case 0 samples
print(measurement.pooled_render_summary.median_ms)     # pooled raw-sample summary (diagnostic only)
print(measurement.sample_count)                        # total timed case renders
```

This matches the CLI contract:

- `frames`: deterministic benchmark cases per scene
- `launches`: repeated measurements per case, implemented as fresh `RenderSession` sweeps
- `warmup`: untimed base-scene renders inside each fresh session
- `resolution`: evaluation render resolution, default `1280x720`
- `rays`: evaluation ray count, default `2000000`

The code still uses `frame_index` in several APIs because that integer is
passed through to `render_shot()`. In scoring terms, each `frame_index`
identifies one benchmark case.

The harness is strict by design:

- baseline capture is all-or-nothing
- evaluation is all-or-nothing
- the baseline schema is explicit and versioned
- there is no legacy fallback path for old baseline layouts
- a successful evaluation always reports a complete benchmark score for the full corpus

For reproducibility, capture and evaluation both copy the exact JSON used for
the warm-up render and for each benchmark case into the corresponding
`baselines/<scene>/` and `runs/<run>/<scene>/` directories.

The primary speed metric remains `RenderResult.time_ms`. The harness also
records a Python wall-clock timing around each `render_shot()` call so the
report can show whether the engine timing and end-to-end call timing stay
aligned.

The benchmark score is computed as:

1. for each case, take the median across launches
2. divide by the baseline case median
3. aggregate all case ratios with a geometric mean

That score is the single optimization metric. Pooled raw-sample summaries and
sample totals remain available in JSON and terminal output for diagnostics only.

The scene corpus is explicit and ordered via
[`evaluation/scenes/manifest.json`](evaluation/scenes/manifest.json). That
file defines the benchmark set on purpose; the harness does not treat the
directory as an open-ended wildcard corpus. Manifest order controls traversal,
terminal/log ordering, and artifact layout; the geometric-mean score itself is
order-independent.

## Build Contract

The evaluation command is intended to be the standard validation command for
rendering work. It explicitly configures the build tree with
`-DCMAKE_BUILD_TYPE=Release` and builds with `--config Release` before running
evaluation.

The report records that requested build configuration directly instead of
trying to infer every realized generator detail from CMake cache files.

## Terminal Summary

The terminal output is intentionally grep-friendly. Each scene prints one line
per case with candidate median, baseline median, and ratio. The final summary
keeps the key corpus-level lines:

- `verdict:`
- `render_sample_total_ms:`
- `baseline_render_sample_total_ms:`
- `render_ratio_gmean:`
- `render_speedup_gmean:`
- `wall_sample_total_ms:`
- `baseline_wall_sample_total_ms:`
- `wall_ratio_gmean:`
- `wall_speedup_gmean:`

`render_ratio_gmean` remains the optimization score. The total-ms lines are
there to show benchmark accounting and to make baseline/candidate time budgets
easy to compare.

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

This section covers the generic baseline helpers. The full evaluation harness
uses the baseline-set layout documented in the next section.

```python
# Save a baseline
save_baseline("baselines/gallery", result, metadata={"commit": "abc123"})

# Later: load and compare
baseline = load_baseline("baselines/gallery")
cr = compare_to_baseline(new_result, baseline)
print(cr.verdict, cr.psnr)
```

## Full Harness Baseline Sets

For multi-case scene baselines:

```python
from evaluation import load_baseline_set, save_baseline_set

save_baseline_set(
    "baselines/gallery",
    {0: frame0_result, 1: frame1_result, 2: frame2_result},
    metadata={"frames": 3, "launches": 3, "warmup": 1, "warmup_mode": "base_scene"},
    scene_json_by_case={
        0: case0_json_text,
        1: case1_json_text,
        2: case2_json_text,
    },
    warmup_scene_json=warmup_json_text,
)

baseline_set = load_baseline_set("baselines/gallery")
baseline_case_1 = baseline_set["cases"][1]
cr = compare_to_baseline(new_frame_1_result, baseline_case_1)
```

Baseline directory layout:
```
baselines/gallery/
  warmup.json
  case_0000.json
  case_0000.png
  case_0001.json
  case_0001.png
  ...
  metadata.json      # schema version, case timing, custom metadata
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

`compare_images()` expects same-shape `(H, W, 3)` `uint8` RGB arrays.

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
from evaluation import compute_psnr, compute_ssim, compute_mse, max_abs_diff, pct_pixels_changed

psnr = compute_psnr(a, b)   # dB
ssim = compute_ssim(a, b)   # 0-1
mse  = compute_mse(a, b)    # float
md   = max_abs_diff(a, b)   # int 0-255
pc   = pct_pixels_changed(a, b)  # fraction of changed pixels
```

All metric functions take `(H, W, 3)` uint8 numpy arrays.
