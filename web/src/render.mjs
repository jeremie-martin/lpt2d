// Framework-agnostic WebGPU renderer for the fill-only path (rung 1).
// Consumes the resolved scene plan from the WASM core and returns RGB8 pixels.
// Shared verbatim by the browser app and the headless parity harness.

import { FILL_WGSL, POST_WGSL } from "./shaders.mjs";

export const FAN_SEGMENTS = 64; // must match the 64-vertex fan in renderer.cpp upload_fills
const FILL_FORMAT = "rgba16float";
const SAMPLE_COUNT = 4; // matches the native 4x MSAA fill FBO
const FLOATS_PER_VERTEX = 5; // [x, y, r, g, b]

// Build the additive triangle-fan vertices for every filled circle, matching
// renderer.cpp upload_fills exactly (center, p(a0), p(a1) per segment).
export function buildFillVertices(plan) {
  const TWO_PI = Math.PI * 2;
  const data = [];
  for (const f of plan.fills) {
    const [r, g, b] = f.color;
    for (let i = 0; i < FAN_SEGMENTS; i++) {
      const a0 = (TWO_PI * i) / FAN_SEGMENTS;
      const a1 = (TWO_PI * (i + 1)) / FAN_SEGMENTS;
      data.push(f.cx, f.cy, r, g, b);
      data.push(f.cx + f.r * Math.cos(a0), f.cy + f.r * Math.sin(a0), r, g, b);
      data.push(f.cx + f.r * Math.cos(a1), f.cy + f.r * Math.sin(a1), r, g, b);
    }
  }
  return new Float32Array(data);
}

// Render the plan and return { rgb: Uint8Array(w*h*3), width, height }.
export async function renderPlan(device, plan, opts = {}) {
  const flipY = !!opts.flipY;
  const w = plan.width;
  const h = plan.height;

  // ── Fill pass resources ──────────────────────────────────────────────
  const fillVerts = buildFillVertices(plan);
  const vbo = device.createBuffer({
    size: Math.max(fillVerts.byteLength, 4),
    usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
  });
  if (fillVerts.byteLength > 0) device.queue.writeBuffer(vbo, 0, fillVerts);

  const fillU = new Float32Array([
    plan.bounds[0], plan.bounds[1],            // boundsMin
    plan.viewport.scale, plan.viewport.scale,  // viewScale
    plan.viewport.ox, plan.viewport.oy,        // viewOffset
    w, h,                                      // resolution
  ]);
  const fillUBuf = device.createBuffer({ size: fillU.byteLength, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
  device.queue.writeBuffer(fillUBuf, 0, fillU);

  const fillModule = device.createShaderModule({ code: FILL_WGSL });
  const fillPipeline = device.createRenderPipeline({
    layout: "auto",
    vertex: {
      module: fillModule,
      entryPoint: "vs",
      buffers: [{
        arrayStride: FLOATS_PER_VERTEX * 4,
        attributes: [
          { shaderLocation: 0, offset: 0, format: "float32x2" },
          { shaderLocation: 1, offset: 8, format: "float32x3" },
        ],
      }],
    },
    fragment: {
      module: fillModule,
      entryPoint: "fs",
      targets: [{
        format: FILL_FORMAT,
        blend: {
          color: { srcFactor: "one", dstFactor: "one", operation: "add" },
          alpha: { srcFactor: "one", dstFactor: "one", operation: "add" },
        },
      }],
    },
    primitive: { topology: "triangle-list" },
    multisample: { count: SAMPLE_COUNT },
  });

  const msaaTex = device.createTexture({
    size: [w, h], format: FILL_FORMAT, sampleCount: SAMPLE_COUNT,
    usage: GPUTextureUsage.RENDER_ATTACHMENT,
  });
  const fillTex = device.createTexture({
    size: [w, h], format: FILL_FORMAT,
    usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.TEXTURE_BINDING,
  });

  const fillBind = device.createBindGroup({
    layout: fillPipeline.getBindGroupLayout(0),
    entries: [{ binding: 0, resource: { buffer: fillUBuf } }],
  });

  // ── Postprocess pass resources ───────────────────────────────────────
  const post = plan.post;
  const postU = new Float32Array([
    post.background[0], post.background[1], post.background[2], post.ambient,
    post.contrast, post.white_point, post.inv_gamma, post.tonemap,
    post.saturation, post.temperature, post.opacity, 0,
  ]);
  const postUBuf = device.createBuffer({ size: postU.byteLength, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
  device.queue.writeBuffer(postUBuf, 0, postU);

  const sampler = device.createSampler({ magFilter: "nearest", minFilter: "nearest" });
  const postModule = device.createShaderModule({ code: POST_WGSL });
  const outFormat = "rgba8unorm";
  const postPipeline = device.createRenderPipeline({
    layout: "auto",
    vertex: { module: postModule, entryPoint: "vs" },
    fragment: { module: postModule, entryPoint: "fs", targets: [{ format: outFormat }] },
    primitive: { topology: "triangle-list" },
  });
  const outTex = device.createTexture({
    size: [w, h], format: outFormat,
    usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC,
  });
  const postBind = device.createBindGroup({
    layout: postPipeline.getBindGroupLayout(0),
    entries: [
      { binding: 0, resource: { buffer: postUBuf } },
      { binding: 1, resource: fillTex.createView() },
      { binding: 2, resource: sampler },
    ],
  });

  // ── Encode ───────────────────────────────────────────────────────────
  const enc = device.createCommandEncoder();

  const fillPass = enc.beginRenderPass({
    colorAttachments: [{
      view: msaaTex.createView(),
      resolveTarget: fillTex.createView(),
      clearValue: { r: 0, g: 0, b: 0, a: 0 },
      loadOp: "clear", storeOp: "store",
    }],
  });
  fillPass.setPipeline(fillPipeline);
  fillPass.setBindGroup(0, fillBind);
  fillPass.setVertexBuffer(0, vbo);
  fillPass.draw(fillVerts.length / FLOATS_PER_VERTEX);
  fillPass.end();

  const postPass = enc.beginRenderPass({
    colorAttachments: [{ view: outTex.createView(), clearValue: { r: 0, g: 0, b: 0, a: 1 }, loadOp: "clear", storeOp: "store" }],
  });
  postPass.setPipeline(postPipeline);
  postPass.setBindGroup(0, postBind);
  postPass.draw(3);
  postPass.end();

  // Readback (bytesPerRow must be 256-aligned).
  const bytesPerRow = Math.ceil((w * 4) / 256) * 256;
  const readBuf = device.createBuffer({ size: bytesPerRow * h, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
  enc.copyTextureToBuffer({ texture: outTex }, { buffer: readBuf, bytesPerRow }, { width: w, height: h });
  device.queue.submit([enc.finish()]);

  await readBuf.mapAsync(GPUMapMode.READ);
  const padded = new Uint8Array(readBuf.getMappedRange()).slice();
  readBuf.unmap();

  // Repack to tight RGB8, dropping row padding and alpha.
  const rgb = new Uint8Array(w * h * 3);
  for (let y = 0; y < h; y++) {
    const srcRow = (flipY ? (h - 1 - y) : y) * bytesPerRow;
    for (let x = 0; x < w; x++) {
      const s = srcRow + x * 4;
      const d = (y * w + x) * 3;
      rgb[d] = padded[s];
      rgb[d + 1] = padded[s + 1];
      rgb[d + 2] = padded[s + 2];
    }
  }
  return { rgb, width: w, height: h };
}
