// Browser entry: load the WASM core, resolve a scene, render the fill path to a
// canvas via the shared WebGPU renderer. Mirrors the headless parity harness so
// the same code path is exercised in-browser.
import { renderPlan } from "./render.mjs";

const status = document.getElementById("status") as HTMLDivElement;
const canvas = document.getElementById("view") as HTMLCanvasElement;

async function main() {
  if (!navigator.gpu) { status.textContent = "WebGPU not available in this browser."; return; }

  // Public asset emitted by web/scripts/build-wasm.sh.
  const createLpt2dModule = (await import(/* @vite-ignore */ "/lpt2d_web.js")).default;
  const m = await createLpt2dModule();

  const sceneJson = await (await fetch("/web_fill_smoke.json")).text();
  const plan = JSON.parse(m.resolve_scene(sceneJson));
  if (plan.error) { status.textContent = `scene error: ${plan.error}`; return; }

  const adapter = await navigator.gpu.requestAdapter();
  const device = await adapter!.requestDevice();
  const { rgb, width, height } = await renderPlan(device, plan, {});

  // Blit the RGB8 result into the canvas.
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(width, height);
  for (let p = 0, q = 0; p < rgb.length; p += 3, q += 4) {
    img.data[q] = rgb[p]; img.data[q + 1] = rgb[p + 1]; img.data[q + 2] = rgb[p + 2]; img.data[q + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  status.textContent = `rendered ${width}×${height} · ${plan.fills.length} fills`;
}

main().catch((e) => { status.textContent = `error: ${e.message}`; });
