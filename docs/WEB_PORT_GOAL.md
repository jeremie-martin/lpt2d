# Web Port — Full Project Plan & Terminal `/goal`

## The destination (what "done" means)

A **browser-based, interactive lpt2d** that a person opens locally and uses to
**author and render shots with desktop-GUI parity** — every rendering computed
**client-side via WebGPU**, at **fidelity parity** with the native C++ engine.

Concretely, "done" is all of:

1. **Render parity** — the web renderer reproduces the native engine across the
   entire `scenes/` corpus (not bespoke fixtures), within a PSNR threshold.
2. **Authoring parity** — the in-browser editor matches the desktop GUI's
   authoring power: object list, add/select/drag/delete/duplicate shapes
   (circle, segment, arc, bézier, polygon, ellipse, path), property editing,
   material library, lights, camera, tracer + look controls, groups /
   enter-group, path drawing, **save/load Shot JSON**, **export PNG**.
3. **Interactivity** — live viewport: pan/zoom, edit-and-re-render, selection,
   direct manipulation.
4. **Runs locally** — `npm run dev` / `npm run build` serve the app in a
   browser. (No hosting/deploy in scope.)
5. **Acceptance suite is green** — an automated headless-browser suite exercises
   the whole app and passes. This suite is the project's machine-checkable
   terminus.

The only thing outside the automated terminus is **aesthetic taste**: a suite
can prove the app is functionally complete and correct, not that it feels good.
So the final step is a **human aesthetic review** (you), once the suite is green.

## How to follow this document to the end

This is a **rung ladder**. Each rung has a **gate**: a command whose output lands
in a transcript and proves the rung works. **Following this document means
climbing every rung in order until the terminal gate passes — not stopping at the
first.** After each rung's gate passes, **commit** (durable, resumable progress).

The terminal gate (the single completion condition) is:

> `npm --prefix web run build` exits 0
> **and** `node web/harness/parity_corpus.mjs` reports every `scenes/*.json` at
> PSNR ≥ threshold
> **and** `npm --prefix web run acceptance` (headless-browser suite) passes.

A `/goal` pointed at this document is **not complete until that terminal gate
holds.** The `/goal` block is at the bottom.

## Architecture (decided)

**Path B, hybrid, web-additive.** The native engine under `src/` is the
immutable reference and is **never modified**; all web code is additive under
`web/`.

- **WASM (Emscripten):** the GL-free C++ core (`scene`, `geometry`,
  `serialize_json`, `serialize`, `spectrum`, `color`) — parses/serializes Shot
  JSON and resolves the physics-laden values (spectral→RGB, dispersion,
  material/light flattening, camera bounds). The web side **reuses** this rather
  than reimplementing physics.
- **TypeScript + WebGPU:** the renderer (WGSL ports of the shaders) and the
  editor UI.

**Drift risk (accepted):** GPU-buffer *packing* is re-implemented in TS, so the
scene→GPU byte layout lives in two languages. **Rung 4 (corpus parity) is the
guard** — any divergence shows up as a parity regression across `scenes/`.

## Verification strategy

Two machine-checkable gate types, both browser-free where possible:

- **Render parity** (rungs 1–4): headless **Dawn** (`webgpu` npm) renders a
  scene; PSNR vs the committed native baseline (the same comparison
  `evaluation/` does for C++→C++). Native baselines are ground truth — never
  regenerated to chase the metric.
- **Authoring + interactivity** (rungs 5–6) and the **terminal acceptance suite**
  (rung 7): **Playwright** drives the app in headless Chromium with WebGPU
  enabled, simulates user actions, and asserts on resulting pixels and on the
  **Shot JSON the editor produces**. A strong correctness tie-back: web-authored
  JSON, rendered by the **native CLI**, must match the web render — so authoring
  is validated against the real engine, not just itself.

## The rung ladder

Each rung: **Goal**, **Gate** (the command + pass condition), **Notes**.

### Rung 1 — Fill parity (no tracer) ✅ COMPLETE
- **Goal:** toolchain (Emscripten + Vite + Dawn harness) + WGSL `fill` +
  `postprocess`; a fill-only scene renders client-side.
- **Gate:** `node web/harness/parity.mjs scenes/web_fill_smoke.json` → PSNR ≥ 40.
- **Result:** **bit-exact** (`PSNR=inf`, MSE=0). Built `web/wasm/lpt2d_web.cpp`,
  `web/scripts/build-wasm.sh`, `web/src/{shaders,render}.mjs`,
  `web/harness/parity.mjs`, minimal browser app (`web/src/main.ts`,
  `web/index.html`).

### Rung 2 — Trace core (the heart of the engine)
- **Goal:** port `src/shaders/trace.comp` → WGSL compute (storage buffers,
  workgroups) + the line rasterization (`line.vert/frag`) and ray accumulation
  loop. Render a circle + single point-light scene client-side.
- **Gate:** `node web/harness/parity.mjs scenes/web_trace_smoke.json` → PSNR ≥
  threshold vs a committed native baseline (author the scene; one circle, one
  point light, modest ray count, deterministic seed).
- **Notes:** this is the largest single technical step. Match the native ray
  batching/accumulation and the deterministic seed so results are comparable;
  expect to tune the PSNR threshold (Monte-Carlo noise means not bit-exact —
  pick a threshold that's meaningful but achievable, e.g. start ~30 dB at a high
  ray count and tighten).

### Rung 3 — Full primitive / material / light coverage
- **Goal:** every shape (segment, arc, bézier, polygon, ellipse, path), every
  material parameter (ior, roughness, metallic, transmission, absorption, cauchy
  dispersion, albedo, emission, spectral coeffs, fill), every light type
  (point, segment, projector) and profile, plus interior fill for all fillable
  shapes — all rendering via the WebGPU path.
- **Gate:** a **scene matrix** (one committed scene per feature) all pass parity:
  `node web/harness/parity_corpus.mjs --dir scenes/web_feature_matrix` → every
  scene ≥ threshold.
- **Notes:** add features incrementally; each new feature adds a scene + baseline
  and must not regress earlier ones.

### Rung 4 — Whole-corpus render parity (the "web renderer == engine" gate)
- **Goal:** a single web render entry — `renderShot(shotJson, frame)` driven by
  the WASM core + WebGPU — that matches `RenderSession::render_shot` across the
  **committed `scenes/` library**.
- **Gate:** `node web/harness/parity_corpus.mjs` renders **every** `scenes/*.json`
  via the web path and vs native baselines; **all** ≥ threshold. (Generate the
  native baselines once via the existing CLI; commit them under `web/baselines/`.)
- **Notes:** this is the milestone that proves the port is faithful and is the
  permanent guard against TS-packing drift.

### Rung 5 — Interactive viewport
- **Goal:** the app shows a live render on a canvas; pan/zoom camera; edits
  trigger re-render; selection works. Reuses the rung-4 render entry.
- **Gate:** `npm --prefix web run acceptance -- --grep viewport` (Playwright):
  load app → assert canvas renders the default scene (pixel checksum) → simulate
  zoom/pan → assert pixels changed and match an expected re-render.

### Rung 6 — Authoring / editor parity
- **Goal:** mirror the desktop GUI's authoring (see `src/app/`): Objects list,
  Properties, Material Library, Camera, Tracer, Display/Look panels; add /
  select / drag / delete / duplicate shapes; groups + enter-group; path drawing;
  **save/load Shot JSON**; **export PNG**.
- **Gate:** `npm --prefix web run acceptance -- --grep editor` (Playwright):
  drive each action; after authoring, **export the Shot JSON, render it with the
  native CLI, and assert the web render matches** (parity tie-back). Assert
  save→load round-trips losslessly through the native `serialize_json`.
- **Notes:** the desktop GUI (`src/app/`, ~6k lines) is the behavioral spec, not
  a code source to copy — match *behavior*, authored via the WASM core's
  serialize so the JSON stays canonical.

### Rung 7 — Acceptance + polish (terminal)
- **Goal:** the full automated acceptance suite green; a basic performance budget
  (interactive frame time on the sample corpus); README for `web/`.
- **Gate (terminal):** `npm --prefix web run build` exit 0 **and**
  `node web/harness/parity_corpus.mjs` all-pass **and**
  `npm --prefix web run acceptance` all-pass.
- **Then:** human aesthetic review (you) — the one non-automatable step.

## Carried-over gotchas (don't relearn these)

- Authored scene version is **12**.
- Fill-only path: trace/HDR texture is zero, so `uMaxVal`/exposure/normalize drop
  out; only fill → background-mask → tonemap → contrast → gamma is active.
  `inv_gamma = 1/gamma`; `reinhardx` is tonemap op **2**. Fill color =
  `spectral_fill_rgb(c0,c1,c2)` (normalized) × `mat.fill`; circle fill is a
  64-segment triangle fan; native fill uses **4× MSAA**.
- Native viewport is aspect-fit min-scale, centered (`viewport_xform`).
- The Dawn harness needs **real GPU access** (Vulkan → `/dev/dri`); it won't run
  under a syscall sandbox. Headless-Chromium WebGPU (Playwright) likewise needs
  GPU flags (`--enable-unsafe-webgpu --enable-features=Vulkan`) or a software
  fallback.
- Dawn's native teardown can crash on process exit and truncate buffered stdout —
  emit results via synchronous `writeSync` **before** returning; never
  `process.exit()`.
- Root `.gitignore` has broad `*.png` and `*.ts` rules — `git add -f` real
  baselines and TypeScript sources.

## Terminal `/goal`

Run under **auto mode**. This goal climbs the remaining rungs (2→7) in order and
**does not complete until the terminal gate holds**. It is large; expect many
turns. Commit after every rung so progress is durable and resumable.

```
/goal Build the interactive browser lpt2d to completion by climbing the rung ladder in docs/WEB_PORT_GOAL.md (rungs 2..7), in order, without stopping at the first.

DONE WHEN, all in one turn's transcript:
- `npm --prefix web run build` exits 0
- `node web/harness/parity_corpus.mjs` renders every scenes/*.json via the web WebGPU path and reports each at PSNR >= its threshold (no scene below threshold, none skipped)
- `npm --prefix web run acceptance` runs the full Playwright suite headless and reports 0 failures
Or stop after 120 turns (or when the token budget is nearly exhausted) and report the highest rung whose gate passes.

HOW TO WORK:
- Implement rungs 2,3,4,5,6,7 from docs/WEB_PORT_GOAL.md in order. Each rung has a Gate; make that gate pass before moving on. Commit after each rung passes.
- All new code is ADDITIVE under web/. Do NOT modify anything under src/ — the native engine is the immutable reference. Reuse the WASM core (web/wasm) for all scene parse/serialize/physics; only the GPU execution and UI live in TS.
- For render rungs, author a scene + generate its native baseline ONCE with ./build/lpt2d-cli, commit it (git add -f past *.png), and never regenerate a baseline to chase the metric. If parity stalls, print the actual PSNR and largest per-pixel diffs each turn and keep fixing the WGSL/packing.
- For editor rungs, validate authoring against the real engine: export the editor's Shot JSON, render it with ./build/lpt2d-cli, and assert the web render matches; assert save/load round-trips through the native serializer.
- Build the missing harness/tooling as needed: web/harness/parity_corpus.mjs (corpus PSNR), the Playwright acceptance suite + `acceptance` npm script, and any baselines.

CONSTRAINTS:
- Do not modify src/. Do not lower a threshold or alter a baseline to pass. Do not mark a rung done unless its Gate command actually passed in the transcript.
- Each turn: report the current rung, which gates pass, and the next concrete step.

REPORT each turn: rung in progress, gate status, next step.
```

### Why the previous version stopped at rung 1

The earlier document defined only **one** auto-verifiable goal (fill parity) and
explicitly scoped itself to "the first rung, not the whole climb." Pointed at a
`/goal`, it correctly stopped there. This rewrite fixes that: the destination is
the **whole product**, every rung has a machine gate, and the **terminal gate is
the completion condition**, so following it runs to the end.

## References

- `/goal` docs: <https://code.claude.com/docs/en/goal>
- Emscripten WebGPU (emdawnwebgpu): <https://github.com/emscripten-core/emscripten/issues/23432>
- Dawn node bindings: <https://github.com/dawn-gpu/node-webgpu>
- naga GLSL→WGSL translation: <https://deepwiki.com/gfx-rs/wgpu/4.3-shader-translation>
- Playwright WebGPU (headless Chromium): <https://playwright.dev/>
