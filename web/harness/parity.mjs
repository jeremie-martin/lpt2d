// Headless WebGPU parity harness (rung 1).
// Renders a scene through the WASM core + WebGPU fill path and reports PSNR
// against the committed native baseline PNG. No browser required (Dawn via the
// `webgpu` node package).
//
// Usage: node web/harness/parity.mjs scenes/web_fill_smoke.json
//   env FLIP_Y=1   vertically flip our output before comparing
//   env DUMP=path  write our render to a PNG (path relative to repo root)
//
// Structured as top-level await (not a wrapped main()): Dawn's native teardown
// can crash the process during exit, so we finish all work and synchronously
// emit the result BEFORE returning, and never call process.exit().

import { readFileSync, writeFileSync, writeSync } from "node:fs";
import { dirname, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { create, globals } from "webgpu";
import { PNG } from "pngjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..", "..");
const THRESHOLD = 40.0;

const scenePath = resolve(REPO, process.argv[2] || "scenes/web_fill_smoke.json");
const baselinePath = resolve(REPO, "web/baselines", basename(scenePath).replace(/\.json$/, ".png"));

function psnr(a, b) {
  if (a.length !== b.length) throw new Error(`size mismatch ${a.length} vs ${b.length}`);
  let sse = 0;
  for (let i = 0; i < a.length; i++) { const d = a[i] - b[i]; sse += d * d; }
  const mse = sse / a.length;
  return mse === 0 ? Infinity : 10 * Math.log10((255 * 255) / mse);
}

// ── WebGPU device (Dawn) ────────────────────────────────────────────────
Object.assign(globalThis, globals);
const gpu = create([]);
const adapter = await gpu.requestAdapter();
if (!adapter) throw new Error("no WebGPU adapter (Dawn)");
const device = await adapter.requestDevice();
device.onuncapturederror = (e) => writeSync(2, "WGPU UNCAPTURED: " + e.error.message + "\n");

// ── Resolve scene via the WASM core ─────────────────────────────────────
const createLpt2dModule = (await import(resolve(REPO, "web/public/lpt2d_web.js"))).default;
const m = await createLpt2dModule();
const plan = JSON.parse(m.resolve_scene(readFileSync(scenePath, "utf8")));
if (plan.error) throw new Error(`resolve_scene: ${plan.error}`);

// ── Render via the shared WebGPU path ───────────────────────────────────
const { renderPlan } = await import(resolve(REPO, "web/src/render.mjs"));
const { rgb, width, height } = await renderPlan(device, plan, { flipY: process.env.FLIP_Y === "1" });

// ── Baseline PNG -> tight RGB8 ──────────────────────────────────────────
const png = PNG.sync.read(readFileSync(baselinePath));
if (png.width !== width || png.height !== height) {
  throw new Error(`baseline ${png.width}x${png.height} != render ${width}x${height}`);
}
const baseRgb = new Uint8Array(width * height * 3);
for (let i = 0, j = 0; i < png.data.length; i += 4, j += 3) {
  baseRgb[j] = png.data[i]; baseRgb[j + 1] = png.data[i + 1]; baseRgb[j + 2] = png.data[i + 2];
}

if (process.env.DUMP) {
  const out = new PNG({ width, height });
  for (let p = 0, q = 0; p < rgb.length; p += 3, q += 4) {
    out.data[q] = rgb[p]; out.data[q + 1] = rgb[p + 1]; out.data[q + 2] = rgb[p + 2]; out.data[q + 3] = 255;
  }
  writeFileSync(resolve(REPO, process.env.DUMP), PNG.sync.write(out));
  writeSync(2, `dumped render -> ${process.env.DUMP}\n`);
}

// ── Report (synchronously, before any teardown) ─────────────────────────
const value = psnr(rgb, baseRgb);
const shown = value === Infinity ? "inf" : value.toFixed(2);
const pass = value >= THRESHOLD;
const line = `PARITY PSNR=${shown} dB (threshold ${THRESHOLD.toFixed(1)}) ${pass ? "PASS" : "FAIL"}`;
writeSync(1, line + "\n");
writeFileSync(resolve(REPO, "web/harness/parity_result.txt"), line + "\n");
process.exitCode = pass ? 0 : 1;
