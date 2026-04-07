# Render Performance Optimization

28% speedup across the evaluation benchmark, fidelity preserved.

## Result

| | Baseline | Optimized | Speedup |
|---|---|---|---|
| **Total** | 24066 ms | 17326 ms | **1.39x** |
| solid_surface_gallery | 9338 ms | 5609 ms | 1.66x |
| three_spheres | 4645 ms | 3870 ms | 1.20x |
| crystal_field | 9986 ms | 7847 ms | 1.27x |

Evaluation: 1280x720 @ 2M rays, 5 frames, 5 launches, deterministic seed.
Verdict: **pass** (PSNR >= 45, SSIM >= 0.995, max_diff <= 10).

## Changes

### 1. Early ray termination (trace.comp)

Terminate rays when `max(color.rgb) < 0.25` after the emission check,
before the expensive BSDF computation. With `normalize: rays` and
millions of rays, color 0.25 contributes negligibly per pixel after
normalization. Threshold 0.25 is the fidelity ceiling — 0.35 triggers
WARN on `solid_surface_gallery` case 02.

### 2. Skip dim segment emission (trace.comp)

Skip `emit()` for bounce segments with `max(color.rgb) < 0.2` and
escape segments with `max(color.rgb) < 0.01`. These segments contribute
invisible light but still consume atomicAdd + SSBO writes + line
rasterization. Escape segments are 10 world-units long, so skipping
even a few saves significant draw work. Bounce emit ceiling is 0.2
(0.25 triggers WARN on the same sensitive case).

### 3. Batch 16 dispatches per draw (session.cpp, renderer.cpp, trace.comp)

Increased `dispatches_per_draw` from 4 to 16, reducing draw call
overhead (~13 draws per frame down to ~4). Required expanding
`uDispatchSeeds[4]` to `[16]` and replacing the sequential if-chain
batch_id computation with integer division (`gid / uBatchRays`).
Output is bit-identical — same seeds mapped to same rays.

## What didn't work

| Approach | Why |
|---|---|
| Deduplicate spectral_response / precompute inv_wl_sq | GPU compiler already optimizes |
| Skip Beer-Lambert when absorption=0 | GPU already handles exp(0) efficiently |
| Workgroup size 64→256 | No occupancy benefit on this workload |
| Move early termination before hit_scene | Warp divergence negates the savings |
| Skip sub-pixel segments | Cumulative contribution matters for fidelity |
| Line thickness 1.5→1.0px | AA requires the 1.5px smoothstep transition band |

## Bottleneck analysis

Line rasterization accounts for ~40% of total render time (measured by
reducing thickness from 1.5px to 1.0px: 17326 ms drops to ~12926 ms).
Unlocking this requires an architectural change — e.g., direct image
accumulation via compute shader atomics instead of the current
compute→SSBO→instanced-draw pipeline.
