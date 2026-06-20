# Web Port — Plan & First `/goal`

Bringing lpt2d to the browser as an **interactive playground**: visitors tweak a
scene and see a freshly rendered frame, computed **client-side**. This document
records the decisions behind that effort and the exact `/goal` that drives its
first milestone.

## The constraint that shapes everything

The engine's core (`src/shaders/trace.comp`, `max_reduce.comp`, `analysis.comp`)
is built on **OpenGL 4.3 compute shaders + SSBOs**, dispatched via
`glDispatchCompute` through a headless **EGL** context, with `glReadPixels`
readback. Browsers run **WebGL2, which has no compute shaders and no SSBOs**, so
the renderer cannot be recompiled to the web as-is.

The path that keeps compute shaders is **WebGPU** (WGSL has compute + storage
buffers). Verification is possible **without a browser** via Dawn's headless node
bindings (`node-webgpu`), so render parity can be measured in a script.

## Architecture: Path B (hybrid), web-additive

Decision: **C++ core compiled to WASM for scene/serialize/geometry; the renderer
re-implemented in TypeScript + WGSL.** The native engine under `src/` is the
immutable physical reference and is **not refactored** for this work — all web
code is additive under `web/`.

- **WASM (Emscripten):** the GL-free core — `scene`, `serialize_json`,
  `geometry`, `spectrum`, `color` — parses a `Shot` JSON and returns the resolved
  `Scene` + camera `Bounds` + fill geometry. **No** `renderer.cpp` / OpenGL / EGL
  / GLEW is compiled.
- **TypeScript + WebGPU:** builds GPU buffers (the `std430`-equivalent packing is
  re-implemented in TS) and runs WGSL ports of the shaders.

### Known risk — accepted

Because GPU-buffer packing is re-implemented in TS rather than reused from
`renderer.cpp`, the scene→GPU byte layout now lives in **two languages and can
drift**. The PSNR parity metric (below) is the **only** guard against this: treat
any parity regression as "the TS packing diverged from C++."

## Verification: render parity vs the native engine

Every milestone reduces to a number the `/goal` evaluator can read from the
transcript:

> a headless `node-webgpu` (Dawn) harness renders a scene and computes **PSNR**
> against the committed native baseline PNG.

This is the same fidelity comparison the `evaluation/` module already performs for
C++→C++ work. The native baseline is ground truth and is never regenerated to
chase the metric.

## Milestone ladder

Each rung is a separate, parity-gated `/goal`. The harness built in rung 1 is
reused for the entire ladder.

0. **Foundation** — Emscripten+WebGPU build green; headless runner reads back
   pixels. *(folded into rung 1)*
1. **Fill parity (no tracer)** — toolchain + harness + WGSL `fill` +
   `postprocess`; a fill-only scene matches its baseline. **← first `/goal`**
2. **Trace core** — port `trace.comp` → WGSL compute; a circle + point-light
   scene matches baseline.
3. **Primitives, one at a time** — segments → arcs → béziers → ellipses →
   materials → spectral, each gated by a parity scene that exercises it.
4. **WASM core + JS frontend** — live controls in the browser. UX, **not**
   auto-verifiable; reviewed manually.

## Why rung 1 is fill-only

`session.cpp` traces only when `num_lights > 0 && total_rays > 0`; otherwise it
runs clear → fills → postprocess. A **fill-only scene with zero rays** therefore
exercises the entire plumbing (WASM packing → WGSL fill → WGSL postprocess →
readback → PSNR) **without** needing `trace.comp` ported. Smallest real render.

Fill + postprocess is fully deterministic (no Monte Carlo), so true parity should
land well above the starting bar — 40 dB is achievable; tighten toward
visually-lossless (~50 dB) once it passes.

## First `/goal`

Run under **auto mode** (otherwise every turn prompts for tool approval). Setting
the goal starts the loop immediately.

```
/goal Stand up a client-side WebGPU render path for lpt2d and prove it matches the native C++ engine on a fill-only scene.

DONE WHEN, all in one turn's transcript:
- `node web/harness/parity.mjs scenes/web_fill_smoke.json` prints `PARITY PSNR=<n> dB (threshold 40.0)` with n >= 40.0
- `npm --prefix web run build` exits 0
- `web/scripts/build-wasm.sh` (Emscripten core build) exits 0
Or stop after 40 turns and report the best PSNR reached.

WHAT TO BUILD (everything new lives under web/ and scenes/; this work is ADDITIVE):
- Emscripten build of the GL-free C++ core only (scene, serialize_json, geometry, spectrum, color) -> a WASM module that parses a Shot JSON and returns the resolved Scene + camera Bounds + fill geometry. Do NOT compile renderer.cpp or any OpenGL/EGL/GLEW code.
- A TypeScript + Vite app under web/ that loads the WASM module, builds WebGPU vertex/uniform buffers in TS (packing is reimplemented in TS by design), and runs WGSL ports of fill.vert/fill.frag and postprocess.vert/postprocess.frag.
- A headless harness web/harness/parity.mjs using node-webgpu (Dawn) that renders the scene at its canvas size, reads back RGB8, loads the committed PNG baseline, computes PSNR, and prints the PARITY line above.

SCENE + BASELINE:
- scenes/web_fill_smoke.json: a tiny fill-only shot (background + 1-2 filled shapes, no lights, trace.rays = 0) so no ray tracing is needed.
- web/baselines/web_fill_smoke.png: native ground truth, rendered ONCE via `./build/lpt2d-cli --scene scenes/web_fill_smoke.json --output web/baselines/web_fill_smoke.png`. Never regenerate or edit it to chase the metric.

CONSTRAINTS:
- Do not modify any file under src/. The native engine is the immutable reference.
- Do not lower the threshold or alter the baseline to pass. If PSNR stalls below 40, print the actual value and the largest per-pixel diffs each turn and keep fixing the WGSL/tonemap math.
- Each turn, run all three checks and show their output.

REPORT each turn: current PSNR, which checks pass, and the next concrete fix.
```

### Caveats (these may consume the early turns — toolchain, not logic)

- `node-webgpu` / Dawn pulls native binaries; install can be slow or finicky in
  CI-less environments. Fallback: build `dawn/node` from source (heavier).
- Emscripten must be on `PATH` (`emcc`). If not, the first turns go to setup.

## References

- `/goal` docs: <https://code.claude.com/docs/en/goal>
- Emscripten WebGPU (emdawnwebgpu): <https://github.com/emscripten-core/emscripten/issues/23432>
- Dawn node bindings: <https://github.com/dawn-gpu/node-webgpu>
- naga GLSL→WGSL translation: <https://deepwiki.com/gfx-rs/wgpu/4.3-shader-translation>
