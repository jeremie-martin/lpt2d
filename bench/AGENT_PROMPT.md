# Autonomous Performance Optimization — lpt2d

You are optimizing a 2D spectral light path tracer. Your goal: **improve total benchmark throughput while preserving image fidelity and maintaining code correctness, stability, and methodological rigor.**

## Project

- Location: `/home/holo/prog/lpt2d`
- Language: C++23, GLSL 430, CMake
- Build: `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j$(nproc)`

## Architecture

GPU compute shader traces rays, emits line segments to an SSBO, then instanced draw rasterizes them as anti-aliased quads with additive blending to a float32 FBO.

**Pipeline per batch:**
1. **Compute shader** (`src/shaders/trace.comp`, workgroup 64) — each thread traces 1 ray: light sampling → O(n) intersection over 4 shape types (circle, segment, arc, bezier) → Fresnel/Snell/Cauchy BSDF → emit line segments to SSBO via atomicAdd
2. **Instanced line draw** (`src/shaders/line.vert/frag`) — vertex shader reads SSBO, expands each segment to 6-vertex quad, additive blend to RGBA32F FBO
3. **Post-process** (`src/shaders/postprocess.frag`) — normalize by max, exposure, tonemap, gamma
4. **Max readback** — `compute_max_gpu()` reads ENTIRE float FBO to CPU via glReadPixels

Read `CLAUDE.md` for constraints (NVIDIA EGL quirk, GPU struct layout, gold standard).

## The Benchmark Harness

**This is your primary tool. Every change must pass through it.**

```bash
# Full benchmark (build + render 12 scenes + compare to baseline)
bench/bench.sh

# Quick mode (1 repeat, no warm-up — for rapid iteration)
bench/bench.sh --quick

# Output: benchmarks/<commit>_bench_<timestamp>/verdict.json
```

The harness renders 12 purpose-built scenes at 1280x720 with 10M rays each. It measures:
- **Image fidelity**: SHA-256 match, PSNR, SSIM, max pixel diff, histogram overlap
- **Performance**: wall-clock time with N=3 repeats, median, CV%, speedup vs baseline

### Reading verdict.json

```json
{
  "overall": "PASS",           // PASS = all scenes ok, FAIL = fidelity regression
  "fidelity_pass": true,
  "performance": {
    "total_speedup": 1.12,     // >1 = faster
    "total_confidence": "likely" // confirmed|likely|noise|regression
  },
  "scenes": {
    "<name>": {
      "fidelity": {"verdict": "PASS", "byte_identical": true},
      "performance": {
        "speedup": 1.116,
        "confidence": "likely",
        "current_median_ms": 2150,
        "current_cv_pct": 0.16
      }
    }
  }
}
```

**Fidelity verdicts**: PASS (identical or PSNR>=45 + SSIM>=0.995 + max_diff<=10), WARN (PSNR>=40 + SSIM>=0.98), FAIL (below WARN).

**Performance confidence**: "confirmed" = non-overlapping timing ranges, "likely" = >5% faster + low variance, "noise" = within noise floor, "regression" = >5% slower.

## Baselines

There are two baselines. They serve different purposes.

**Reference baseline** (`bench/baseline/`, local-only): The trusted standard captured before any optimization work begins. It is intentionally ignored by git. This never changes during an optimization campaign. All cumulative speedup numbers are reported against this. It is the ground truth for fidelity. If you need to preserve it long-term or share it, archive it outside the repository.

**Working baseline**: The current accepted state on the master branch, stored locally in `bench/baseline/`. When you merge a successful optimization to master, the working baseline moves forward. Subsequent attempts compare fidelity and performance against this working baseline. To update it:
```bash
bench/bench.sh --capture-baseline
```

The reference baseline lets you measure total progress. The working baseline lets you evaluate incremental changes cleanly (each change is measured against a codebase that already includes all previously accepted optimizations).

## Workflow

For each optimization attempt:

1. **HYPOTHESIZE** — State what you will change, why it should help, which scenes you expect to benefit, and your risk assessment. Every attempt needs a clear rationale. "X should reduce Y because Z" — not "let's try X and see."

2. **BRANCH** — `git checkout -b opt/<short-name>`

3. **IMPLEMENT** — Keep diffs minimal and focused. One conceptual change at a time.

4. **BUILD** — `cmake --build build -j$(nproc)`. If a change breaks the build and the fix isn't immediately obvious after a short focused attempt, revert the change (`git checkout -- .`), record the failure and what went wrong, and move on.

5. **SMOKE TEST** — Quick check:
   ```bash
   bench/bench.sh --quick
   ```

6. **BENCHMARK** — Full run:
   ```bash
   bench/bench.sh
   ```

7. **READ VERDICT** — Parse `verdict.json` from the run directory.

8. **ANALYZE** — This is critical. For every result, reason about root cause:
   - **If it helped**: Why? Was your hypothesis confirmed? Which part of the pipeline benefited? Does the speedup pattern across scenes match your prediction? If not, what does the actual pattern tell you?
   - **If it didn't help**: Why not? Was the hypothesis wrong, or was the implementation insufficient? Is the bottleneck elsewhere? What does this tell you about where time is actually spent?
   - **If fidelity changed**: Why? Was it expected (e.g., floating-point reordering) or unexpected (a bug)? Are the changes uniformly distributed or localized?

   This analysis feeds your next hypothesis. Optimization is not trial-and-error — each result should deepen your understanding of where time goes.

9. **DECIDE**:
   - **Fidelity PASS + meaningful speedup (confirmed/likely)**: Merge to master. Update the working baseline.
   - **Fidelity PASS + noise-level change**: Not worth the complexity. Log it, delete branch.
   - **Fidelity FAIL**: Do NOT merge. Log it, keep branch for reference — it may contain useful ideas.
   - **Mixed results**: See acceptance criteria below.

10. **LOG** — Record everything in `OPTIMIZATION_LOG.md` (format below). Include your root-cause analysis.

11. **Return to master** before starting next attempt.

### Mixed Results Acceptance

When an optimization helps some scenes but hurts others, apply ALL of:
- Geometric mean of per-scene speedups > 1.05 (net 5% improvement)
- No single scene regresses more than 10%
- Total fidelity: all scenes PASS or WARN
- No meaningful increase in timing variance (CV% should not significantly worsen for any scene)
- The performance pattern makes sense given the hypothesis (e.g., an acceleration structure helping dense scenes and slightly hurting minimal ones is explainable; random scene-to-scene variation is suspicious)

When in doubt, don't merge. A clean codebase with fewer wins is better than an unstable one with marginal gains.

## Optimization Landscape

Here are known areas of opportunity, organized roughly by risk and expected reward. Use this as a starting map, not a rigid checklist — you should apply your own judgment about what to investigate and in what order based on what you learn from profiling and from each attempt's results.

**Low-hanging fruit** (no rendering math changes):
- `compute_max_gpu()` does a full CPU readback of the float FBO. The `max_reduce.comp` shader is compiled but unused.
- Batch size is 50K for benchmarks. Larger batches amortize dispatch overhead.
- Compute workgroup size is 64. Modern GPUs may prefer larger.
- Output SSBO is allocated at `batch_size * max_depth` — most rays die much earlier.

**Shader-level** (low risk):
- Fresnel computation, intersection loops, scattering functions — look for redundant work, strength reductions, better branch patterns.

**Algorithmic** (medium risk):
- No spatial acceleration structure exists — intersection is O(n) per ray per bounce. Most impactful for the dense_grid scene (34 shapes).
- Compute/rasterize overlap, SSBO compaction, adaptive batching.

**Architectural** (high risk, high reward):
- The instanced-line-draw pipeline (compute → SSBO → vertex expansion → additive blend) could potentially be replaced by direct image-space accumulation. The `experiment/direct-to-image` branch explored this but had fidelity issues.
- Persistent-thread compute models, reduced precision, tile-based approaches.

Start with whatever you judge to be the highest expected value after reading the code. Low-risk items are good for building confidence in the workflow before attempting bigger changes, but if your analysis reveals a clear bottleneck, go after it directly.

## Statistical Rigor

- **Never accept < 3% improvement from a single run.** The noise floor is ~2-3%.
- **3-10% improvement**: require the full 3 repeats. Check that confidence is "likely" or "confirmed".
- **> 10% improvement**: 2 repeats suffice (use `REPEATS=2 bench/bench.sh`).
- The primary metric is **total_speedup** across all scenes. Per-scene speedups are diagnostic.
- If a scene has CV > 10%, its timing is unstable — increase repeats or investigate why.
- Be wary of changes that reduce median time but increase variance. Consistent performance matters.

## Stopping Criteria

Stop when ANY of:
- Last 3 consecutive attempts each yielded < 2% total improvement
- Total cumulative improvement from reference baseline exceeds 3x
- You've explored the major optimization avenues and further attempts are hitting diminishing returns or failing fidelity

Write a **FINAL SUMMARY** in the log when stopping, covering: total speedup achieved, what worked, what didn't, and what you believe the remaining opportunities are.

## Optimization Log Format

Maintain at: `OPTIMIZATION_LOG.md` in the project root.

```markdown
# lpt2d Optimization Log

## Reference Baseline
- Date: YYYY-MM-DD HH:MM
- Commit: <hash>
- Run dir: benchmarks/<dir>
- Total median: XXXXXms
- Per-scene: <table>

## Attempt N: <short-name>
- Branch: opt/<short-name>
- Hypothesis: <what and why>
- Risk: low/medium/high
- Changes: <files modified, brief>
- Build: OK/FAIL
- Fidelity: PASS/WARN/FAIL
- Performance:
  | Scene | Before (ms) | After (ms) | Speedup | Confidence |
  |-------|-------------|------------|---------|------------|
  | ...   |             |            |         |            |
  | TOTAL |             |            |         |            |
- Verdict: MERGED / REJECTED / SHELVED
- Cumulative speedup vs reference: X.XXx
- Analysis: <root-cause reasoning — why did this help/fail? was the hypothesis confirmed? what does the per-scene pattern reveal?>
- Lessons: <what this teaches about where time is spent and what to try next>
```

## Non-Negotiable Rules

These protect the integrity of the optimization process. They are not guidelines.

1. **Benchmark validity**: Never modify anything under `bench/` (scenes, metrics, harness). Changing measurement methodology invalidates all prior data and breaks the entire optimization loop. If you believe the harness has a bug, document it in the log and continue working within its constraints.
2. **One change at a time.** Never combine unrelated optimizations in a single attempt. Composability testing (merging 2+ independent wins) is a separate, explicit step.
3. **Always return to master** between attempts.
4. **Never force-push to master.** History is the record of what was tried.
5. **Every change needs a hypothesis** grounded in reasoning about the code, not random experimentation.
6. **Never look at rendered images.** Rely only on the objective metrics in verdict.json.
7. **Commit messages** reference the optimization: `opt: <description>`.
8. **Composability**: When 2+ optimizations work independently, test them combined. Interaction effects are real — the combined result may differ from the sum.
