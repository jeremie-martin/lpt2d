# Render Speed Autoresearch Report

Date: 2026-04-07

## Goal

Improve rendering speed in:

- `src/core/**`
- `src/shaders/**`

Metric:

- `median_ms` from `uv run python -m evaluation`

Guard:

- fidelity must `PASS` in the same evaluation run

Direction:

- lower is better

## Final Outcome

Baseline at iteration 0:

- commit: `b226cee`
- median: `499.7 ms`
- fidelity: `PASS`

Best retained result:

- iteration: `36`
- commit: `a8e572b`
- median: `373.6 ms`
- fidelity: `PASS`
- improvement vs baseline: `126.1 ms`
- speedup vs baseline: about `1.338x`

Best exact evaluation run:

- run dir: `/tmp/lpt2d-autoresearch-JCHewz/runs/20260406-235840_a8e572b/`
- report: `/tmp/lpt2d-autoresearch-JCHewz/runs/20260406-235840_a8e572b/report.json`

Search summary:

- measured iterations: `47`
- kept: `10`
- discarded: `37`
- fidelity failures among measured experiments: `4`

The search stopped on user request after the result had flattened out. The final best remained iteration `36`; the following `11` measured iterations did not beat it.

## Retained Changes

These commits were kept and are the changes merged onto `feature/polygon-corner-radius`.

| Commit | Median After Keep | Change | Summary |
| --- | ---: | ---: | --- |
| `03fbb3d` | `498.6 ms` | `-1.1 ms` | Remove redundant normalized-ray math and cache `uBatchRays` uniform location |
| `49bf1d3` | `497.2 ms` | `-1.4 ms` | Fuse pixel copy and frame-metrics scan |
| `ef1377b` | `377.2 ms` | `-120.0 ms` | Switch accumulation buffer from RGBA to RGB |
| `7d87b27` | `376.9 ms` | `-0.3 ms` | Streamline display readback to RGB |
| `f0d27cd` | `376.8 ms` | `-0.1 ms` | Precompute segment and ellipse invariants |
| `ef98e9c` | `376.3 ms` | `-0.5 ms` | Cache circle and arc radius invariants |
| `9621956` | `376.1 ms` | `-0.2 ms` | Special-case small light counts |
| `0bd621e` | `376.0 ms` | `-0.1 ms` | Prune farther primitive hits early |
| `255b711` | `374.3 ms` | `-1.7 ms` | Collapse multi-batch dispatches into one larger dispatch while preserving per-batch seeds |
| `a8e572b` | `373.6 ms` | `-0.7 ms` | Replace merged-dispatch batch index divide/mod with compare-subtract logic |

## What Mattered

### 1. Buffer format changes dominated the total gain

The biggest single improvement was switching the accumulation path away from RGBA:

- `ef1377b` reduced median from roughly `497 ms` to `377 ms`
- `7d87b27` then cut a bit more by keeping the display/readback path RGB-focused

This tells us the benchmark is highly sensitive to bandwidth and format costs in the accumulation and export path.

### 2. Cheap shader invariants still helped

Small but real wins came from pushing repeated math out of the per-hit path:

- segment inverse length
- ellipse inverse squared axes and rotation sin/cos
- circle and arc radius squared / inverse radius

These were not individually dramatic, but they stacked cleanly and all preserved fidelity.

### 3. The merged-dispatch path was the last productive frontier

Two late wins came from reducing CPU-side compute dispatch overhead without changing the sample stream:

- `255b711`: merge multiple logical batches into one compute launch per draw
- `a8e572b`: simplify batch-id reconstruction inside the shader

Several nearby variants were tested and rejected, which suggests this area is now close to locally exhausted.

## What Did Not Work

### Failed guard experiments

These produced lower medians but failed fidelity and were rejected:

- iteration `21`: trim one RNG warm-up step
- iteration `33`: increase dispatches per draw to `5`
- iteration `40`: skip deterministic BSDF roulette RNG
- iteration `43`: default render sessions to half float

The half-float default was especially instructive:

- median: `173.3 ms`
- fidelity: `FAIL`
- max diff: `255`

So precision-reduction shortcuts are not acceptable for this benchmark target.

### Regressions or noise

The following classes consistently failed to beat the incumbent:

- primitive test reordering
- workgroup-size sweeps (`32`, `128`)
- small GL state hoists
- readback sync tweaks
- pixel-pack-buffer readback
- line-quad strip conversion
- per-shape bounds culling
- buffer usage-hint tweaks

In practice, once the merged-dispatch work landed, most remaining local changes were noise or small regressions.

## Profiling Findings

A targeted single-shot profile was taken with:

```bash
LPT2D_PROFILE_RENDER=1 ./build/lpt2d-cli --scene evaluation/scenes/solid_surface_gallery.json --output /tmp/test.png
```

On the best retained tree, the stage breakdown was:

```text
upload_scene=0.12ms
upload_fills=0.17ms
clear=0.02ms
trace=6.87ms
read_pixels=384.53ms
total=391.72ms
```

Readback was then broken down one level deeper:

```text
update_display=0.07ms
readback=383.33ms
row_flip=0.15ms
metrics=0.98ms
```

This changed the direction of the late search:

- the CPU-visible cost was overwhelmingly at the display readback boundary
- the trace submission cost visible from CPU was already small
- however, alternate readback paths tested here still regressed under the exact benchmark guard

Interpretation:

- for this scene and stack, the obvious CPU/GPU synchronization tweaks were not enough to reduce the guarded benchmark
- the driver appears to prefer the original `glFinish` + `glReadPixels` path over the variants we tried

## Important Scene-Specific Context

The benchmark scene has properties that shaped the search:

- many rounded polygons decompose into lots of segments and arcs
- only `4` lights are present, which is why the small-light fast path helped
- most materials are spectrally neutral
- fill is effectively irrelevant for this scene, but skipping fill-path work still did not beat the incumbent
- the evaluation harness intentionally renders the same shot repeatedly for statistics; no benchmark-logic changes were made

## Files Changed By The Final Retained Set

- `src/core/renderer.h`
- `src/core/renderer.cpp`
- `src/core/session.cpp`
- `src/shaders/trace.comp`

## Recommendation

The retained result is worth merging as-is.

The next likely step, if more speed is needed, is not another micro-tweak. The productive directions left are larger architectural changes, for example:

- a different display/export path that avoids the current blocking readback cost while still satisfying evaluation fidelity
- a stronger scene/intersection acceleration structure than the flat primitive loops
- benchmark-aware but fidelity-safe batching or accumulation redesign

For this autoresearch run, the merged set is the best validated result.
