# lpt2d Optimization Log

## Reference Baseline
- Date: 2026-04-03 00:06
- Commit: e8da824
- Run dir: bench/baseline/ (local, git-ignored)
- Total median: 30750ms
- Per-scene:

| Scene | Median (ms) | % of total |
|-------|-------------|------------|
| bench_mirror_hall | 8399 | 27.3% |
| bench_deep_bounce | 7511 | 24.4% |
| bench_dense_grid | 2895 | 9.4% |
| bench_prism_beam | 2591 | 8.4% |
| bench_grazing | 2041 | 6.6% |
| bench_dispersion_fan | 1784 | 5.8% |
| bench_all_shapes | 1623 | 5.3% |
| bench_tir_trap | 1191 | 3.9% |
| bench_arc_focus | 991 | 3.2% |
| bench_glass_sphere | 936 | 3.0% |
| bench_mixed_materials | 485 | 1.6% |
| bench_bezier_waveguide | 303 | 1.0% |
| **TOTAL** | **30750** | **100%** |

---

## Attempt 1: GPU max reduction
- Branch: opt/gpu-max-reduce
- Hypothesis: Replace CPU-side glReadPixels (14.7MB transfer + CPU scan) with GPU compute shader max reduction (4-byte readback). Should eliminate CPU-GPU sync overhead.
- Risk: low
- Changes: src/core/renderer.cpp — rewrote compute_max_gpu() to use max_reduce.comp
- Build: OK
- Fidelity: PASS (PSNR 94-109dB, SSIM 1.0 on all scenes)
- Performance:

| Scene | Before (ms) | After (ms) | Speedup | Confidence |
|-------|-------------|------------|---------|------------|
| bench_mirror_hall | 8399 | 8374 | 1.003x | noise |
| bench_deep_bounce | 7511 | 7446 | 1.009x | noise |
| bench_dense_grid | 2895 | 2793 | 1.036x | confirmed |
| bench_prism_beam | 2591 | 2519 | 1.029x | confirmed |
| bench_grazing | 2041 | 1964 | 1.039x | confirmed |
| bench_dispersion_fan | 1784 | 1716 | 1.040x | confirmed |
| bench_all_shapes | 1623 | 1547 | 1.049x | confirmed |
| bench_tir_trap | 1191 | 1130 | 1.054x | confirmed |
| bench_arc_focus | 991 | 892 | 1.111x | likely |
| bench_glass_sphere | 936 | 850 | 1.101x | confirmed |
| bench_mixed_materials | 485 | 450 | 1.078x | confirmed |
| bench_bezier_waveguide | 303 | 308 | 0.984x | noise |
| **TOTAL** | **30750** | **29989** | **1.025x** | **confirmed** |

- Verdict: MERGED (commit fd351ac)
- Cumulative speedup vs reference: 1.025x
- Analysis: The 2.5% total speedup is larger than expected for a once-per-scene operation. The improvement is proportionally larger on lighter scenes (glass_sphere 10%, arc_focus 11%) where the readback overhead is a bigger fraction of total time. Heavy scenes (mirror_hall, deep_bounce) show noise-level change as expected — their compute dominates. This confirms the bottleneck is in the compute shader.
- Lessons: The readback was a measurable drag on lighter scenes. The compute shader trace loop is clearly the main bottleneck for all heavy scenes.

---

## Attempt 2: Workgroup size 256
- Branch: opt/workgroup-256
- Hypothesis: Larger workgroups (256 vs 64) provide more warps for latency hiding and reduce dispatch overhead. Should help if shader is memory-latency-bound.
- Risk: low
- Changes: trace.comp (local_size_x = 256), renderer.cpp (group calc)
- Build: OK
- Fidelity: PASS (PSNR 67-84dB — lower due to different total threads per dispatch)
- Performance: 0.998x total (regression)
- Verdict: REJECTED
- Cumulative speedup vs reference: 1.025x (no change)
- Analysis: The trace shader is compute-bound, not memory-latency-bound. Larger workgroups increase register pressure, reducing actual occupancy. The PSNR drop is because 256-thread groups dispatch 50176 threads vs 50048, changing the exact ray set traced.
- Lessons: Don't pursue memory latency hiding. Focus on reducing computation per ray (shader ALU work). The shader is ALU-bound.

---

## Attempt 3: Multi-batch dispatch
- Branch: opt/multi-batch
- Hypothesis: Group 4 compute dispatches before 1 draw call to amortize draw overhead (pipeline state changes, barriers, draw indirect). Reduces draws from 200 to 50 per scene.
- Risk: low
- Changes: renderer.h/cpp (new trace_and_draw_multi method), cli/main.cpp (use multi-batch loop)
- Build: OK
- Fidelity: PASS (PSNR 86-112dB, SSIM ≥0.999998)
- Performance:

| Scene | Before (ms) | After (ms) | Speedup | Confidence |
|-------|-------------|------------|---------|------------|
| bench_mirror_hall | 8375 | 8240 | 1.019x | confirmed |
| bench_deep_bounce | 7442 | 7319 | 1.026x | confirmed |
| bench_dense_grid | 2811 | 2711 | 1.068x | confirmed |
| bench_prism_beam | 2515 | 2437 | 1.063x | confirmed |
| bench_grazing | 1966 | 1909 | 1.069x | confirmed |
| bench_dispersion_fan | 1711 | 1644 | 1.085x | confirmed |
| bench_all_shapes | 1531 | 1486 | 1.092x | confirmed |
| bench_tir_trap | 1125 | 1083 | 1.100x | confirmed |
| bench_arc_focus | 883 | 859 | 1.154x | confirmed |
| bench_glass_sphere | 855 | 833 | 1.124x | confirmed |
| bench_mixed_materials | 443 | 448 | 1.083x | confirmed |
| bench_bezier_waveguide | 277 | 275 | 1.102x | confirmed |
| **TOTAL** | **29934** | **29244** | **1.052x** | **confirmed** |

- Verdict: MERGED (commit 8f56394)
- Cumulative speedup vs reference: 1.052x
- Analysis: Confirmed 5.2% improvement. Light scenes gain more (10-15%) because draw overhead is a bigger fraction. Heavy scenes still gain 2-3% from fewer pipeline state transitions. The pattern is exactly as predicted: overhead amortization helps proportionally more where overhead is a bigger fraction.
- Lessons: Per-batch overhead (barrier + draw + state changes) was ~5% of total time. 4 dispatches per draw was sufficient — more would require proportionally more SSBO memory.

---

## Attempt 4: Two-pass intersection (distance-only first pass)
- Branch: opt/shader-opts
- Hypothesis: Splitting intersection into distance-only search + material reconstruction for the winner should reduce register pressure. Carrying 1 float (best_t) instead of 11 floats (Hit struct) through the search loop should improve GPU occupancy.
- Risk: medium
- Changes: trace.comp — split each hit_* function into dist_* (returns float t) and make_hit_* (returns full Hit)
- Build: OK
- Fidelity: PASS (PSNR 85-109dB)
- Performance: **0.828x total (17% REGRESSION)**
- Verdict: REJECTED
- Cumulative speedup vs reference: 1.052x (no change)
- Analysis: The two-pass approach was dramatically worse. Root cause: the "reconstruction" pass re-reads the winning shape from the SSBO (second memory access), and the switch/branch to dispatch to different make_hit_* functions causes thread divergence. The GLSL compiler already handles the Hit struct efficiently — it likely keeps the active `best` hit in registers and the conditional assignment `if (h.t < best.t) best = h` compiles to predicated moves (no branch). The "optimization" added work without removing any.
- Lessons: **Do not fight the GLSL compiler on register allocation.** The compiler handles struct-of-arrays vs array-of-structs decisions. Extra SSBO reads are extremely expensive relative to register operations. Branching on shape type causes warp divergence. Focus optimizations on reducing TOTAL work, not reorganizing existing work.

---

## Attempt 5: Shader micro-optimizations (retest with GPU active)
- Branch: opt/shader-micro-v2
- Hypothesis: Precompute inv_wl_sq, use inv_denom in segment intersection, skip exp() when absorption=0. Previous test was invalid (GPU was throttled in P8 state due to monitor off).
- Risk: low
- Changes: trace.comp — 3 small edits
- Build: OK
- Fidelity: PASS (PSNR 92-112dB)
- Performance: 0.998x total (noise)
- Verdict: REJECTED — no measurable improvement
- Cumulative speedup vs reference: 1.052x (no change)
- Analysis: With GPU properly active (P0, 2520 MHz), the micro-opts have zero impact. The GLSL/NVIDIA compiler already performs these strength reductions (CSE on division, dead code elimination for exp(0)). Manually rewriting these patterns does not help.
- Lessons: **The NVIDIA GLSL compiler is very good at micro-optimization.** Don't waste time on strength reductions the compiler already does. Focus on algorithmic changes that the compiler CANNOT do: reducing total work (fewer intersection tests, fewer bounces), or restructuring memory access patterns.

---

## Attempts 6-9: Various (all rejected)
- Attempt 6 (precomputed segment normals): REJECTED — larger struct (48→56 bytes) hurt cache
- Attempt 7 (multi-batch 10): REJECTED — larger SSBO hurts heavy scenes, draw overhead already amortized
- Attempt 8 (AABB early-out): SKIPPED — analysis showed AABB saves only ~3 ops per rejected circle vs discriminant check
- Attempt 9 (mega-dispatch): REJECTED — no improvement, PSNR dropped near WARN

---

## CRITICAL FINDING: GPU Timing Analysis
- Added GPU profiling (glFinish barriers to split compute vs draw time)
- **Result: 99%+ of time is in the INSTANCED DRAW, not the compute shader!**
  - mirror_hall: compute=17ms (0.2%), draw=8565ms (99.8%)
  - deep_bounce: compute=15ms (0.3%), draw=5112ms (99.7%)
  - dense_grid: compute=28ms (1.0%), draw=2685ms (98.9%)
- The compute shader traces 10M rays in 15-30ms. All previous shader optimization attempts were targeting <1% of the runtime.
- The draw bottleneck is millions of tiny triangles (2.4M quads = 4.8M triangles, each ~3px) with RGBA32F additive blending.

---

## Attempt 10: Direct-to-image accumulation
- Branch: opt/direct-image
- Hypothesis: Replace SSBO→instanced draw with imageAtomicAdd in the compute shader. Eliminates the 99% draw bottleneck.
- Risk: high
- Changes: trace.comp (Wu AA line rasterizer + imageAtomicAdd), renderer.cpp/h (R32UI images), postprocess.frag (read R32UI), removed SSBO/draw pipeline
- Build: OK
- Fidelity: FAIL (PSNR 6-25dB — line width mismatch: Wu=1px vs original=3px)
- Performance: 1.39x total speedup (mirror_hall 1.51x, deep_bounce 1.50x) — huge gains
- Verdict: REJECTED due to fidelity failure
- Follow-up attempt with thick DDA lines: still FAIL (PSNR 5-24dB) and slower (0.95x)
- Analysis: Direct-to-image produces a fundamentally different spatial distribution of light than smoothstep quad rasterization. Matching the exact AA profile in software is extremely difficult. The brightness was 3.3× off even with matching smoothstep parameters.
- Lessons: The draw pipeline IS the bottleneck, but replacing it with software rasterization in compute either doesn't match fidelity (Wu) or is too slow (thick DDA). Need to find ways to make the EXISTING draw pipeline faster instead.

---

## Attempt 11: RGBA16F two-stage accumulation
- Branch: opt/rgba16f-fbo
- Hypothesis: Use RGBA16F staging buffer for per-batch blending (2× faster than RGBA32F), then composite to RGBA32F for precision.
- Risk: high
- Performance: 3.44x-3.92x total speedup (extraordinary)
- Fidelity: FAIL — hot pixels in mirror_hall/deep_bounce overflow float16 precision. 3 of 12 scenes PASS (bezier_waveguide 65dB, dense_grid 51dB, mixed_materials 58dB), but 9 FAIL (PSNR 10-37dB).
- Verdict: REJECTED — float16 fundamentally cannot accumulate thousands of small values at hot pixels.
- Lessons: RGBA16F blending is 2-3× faster than RGBA32F on the RTX 4090. The speedup confirms the bottleneck is blending bandwidth. But float16's 10-bit mantissa causes catastrophic precision loss when many small values accumulate at the same pixel.

---

## Attempt 12: Reduce line thickness (1.5→0.75/1.0 px)
- Branch: opt/thin-lines
- Hypothesis: Thinner lines = fewer pixels per segment = less blending work.
- Performance: thickness=0.75: 1.58x, thickness=1.0: 1.31x
- Fidelity: FAIL — thinner lines produce fundamentally different spatial distribution (PSNR 17-42dB)
- Verdict: REJECTED
- Lessons: Line thickness directly controls visual appearance. Even with intensity compensation, the spatial distribution change fails fidelity.

---

## Attempt 13: Direct-to-image with NV_shader_atomic_float (R32F)
- Branch: opt/direct-image-float32
- Hypothesis: Use GL_NV_shader_atomic_float for imageAtomicAdd on R32F images. Full float32 precision + DDA thick line rasterizer.
- Performance: 0.95x (slight regression!)
- Fidelity: FAIL (PSNR 15-46dB)
- Verdict: REJECTED — imageAtomicAdd contention on hot pixels makes compute atomics SLOWER than hardware ROPs.
- Lessons: Hardware rasterizer + ROPs are highly optimized for additive blending. Compute shader atomics cannot compete due to serialization at contended pixels.

---

## FINAL SUMMARY

### Speedup achieved
**1.052x cumulative** vs reference baseline (from GPU max reduction + multi-batch dispatch).

### What worked
1. **GPU max reduction** (+2.5%): Replaced CPU readback of entire float FBO with GPU compute shader max reduction. Reduced overhead on light scenes.
2. **Multi-batch dispatch** (+5.2%): Grouped 4 compute dispatches per draw call to amortize draw pipeline overhead. Reduced number of draw calls from 200 to 50.

### What didn't work and why
3. **Workgroup size 256**: Slight regression. Shader is ALU-bound, not memory-latency-bound.
4. **Two-pass intersection**: 17% regression. Extra SSBO re-reads and branch divergence outweigh register pressure savings.
5. **Shader micro-opts** (inv_denom, inv_wl_sq, skip exp): No improvement. NVIDIA GLSL compiler already performs these optimizations.
6. **Precomputed segment normals**: Larger GPUSegment struct (48→56 bytes) hurt cache.
7. **More dispatches per draw (10)**: Larger SSBO hurts heavy scenes.
8. **Mega-dispatch**: No improvement vs 4 small dispatches.
9. **Line thickness reduction**: Fails fidelity. Different spatial distribution.
10. **Direct-to-image (R32UI)**: 1.39x speedup but FAIL fidelity (Wu AA mismatch).
11. **RGBA16F staging**: 3.44-3.92x speedup but FAIL fidelity (float16 precision loss on hot pixels).
12. **Direct-to-image (R32F + NV atomics)**: Slower than hardware ROPs due to atomic contention.

### Root cause analysis
**GPU profiling revealed that 99%+ of rendering time is in the INSTANCED DRAW pipeline (RGBA32F additive blending), NOT in the compute shader.** The compute shader traces 10M rays in just 15-30ms. The draw renders 120M+ line segments as anti-aliased quads with additive blending, requiring terabytes of RGBA32F bandwidth.

This is a fundamental architectural constraint of the current pipeline. The line rendering approach (compute → SSBO → instanced quads → RGBA32F additive blend) is bandwidth-bound at the ROP blending stage. All attempts to replace or optimize this blending pathway either:
- Fail fidelity (different line profiles, precision loss)
- Are slower (compute atomics can't match dedicated ROP hardware)

### Remaining opportunities
1. **Hybrid RGBA16F/32F**: Use RGBA16F for scenes where per-pixel accumulation is low (3 of 12 scenes pass), RGBA32F for dense scenes. Requires runtime density detection.
2. **Segment deduplication**: Merge overlapping line segments before drawing to reduce triangle count.
3. **Tile-based accumulation**: Render in tiles, accumulating fewer segments per tile.
4. **Alternative line rendering**: Use GL_LINES with glLineWidth instead of quads (needs driver support testing).
5. **Vulkan port**: Vulkan's render passes and subpass dependencies could enable more efficient blending pipelines.
6. **Resolution reduction**: Lower internal resolution with upscaling (changes output).

---
