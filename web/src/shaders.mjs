// WGSL ports of the native fill + postprocess shaders (rung 1: fill-only path).
// Shared by the browser app and the headless parity harness.

// Port of src/shaders/fill.vert + fill.frag.
// World -> pixel -> NDC, additive fill color. Antialiasing comes from 4x MSAA
// on the render target (matching the native MSAA fill FBO), not from here.
export const FILL_WGSL = /* wgsl */ `
struct FillU {
  boundsMin : vec2f,
  viewScale : vec2f,
  viewOffset: vec2f,
  resolution: vec2f,
};
@group(0) @binding(0) var<uniform> u : FillU;

struct VOut {
  @builtin(position) pos : vec4f,
  @location(0) color : vec3f,
};

@vertex
fn vs(@location(0) aPos : vec2f, @location(1) aColor : vec3f) -> VOut {
  let pixel = (aPos - u.boundsMin) * u.viewScale + u.viewOffset;
  let ndc = (pixel / u.resolution) * 2.0 - vec2f(1.0);
  var o : VOut;
  // WebGPU framebuffer origin is top-left, so world +y maps to the top row
  // with no explicit flip (the GL path flips because its origin is bottom-left).
  o.pos = vec4f(ndc.x, ndc.y, 0.0, 1.0);
  o.color = aColor;
  return o;
}

@fragment
fn fs(i : VOut) -> @location(0) vec4f {
  return vec4f(i.color, 1.0);
}
`;

// Port of src/shaders/postprocess.frag for the fill-only subset.
// The HDR/trace texture is zero in rung 1, so only the fill -> background mask
// -> tonemap -> contrast -> saturation -> temperature -> gamma -> opacity chain
// is active. Vignette/grain/hue/CA/highlights/shadows are all neutral here and
// omitted; later rungs reintroduce them as scenes exercise them.
export const POST_WGSL = /* wgsl */ `
struct PostU {
  background  : vec3f,
  ambient     : f32,
  contrast    : f32,
  white_point : f32,
  inv_gamma   : f32,
  tonemap     : f32,
  saturation  : f32,
  temperature : f32,
  opacity     : f32,
  _pad        : f32,
};
@group(0) @binding(0) var<uniform> p : PostU;
@group(0) @binding(1) var fillTex : texture_2d<f32>;
@group(0) @binding(2) var samp : sampler;

fn sanitize(v : f32) -> f32 { return clamp(v, 0.0, 1.0e10); }

fn tmReinhard(v : f32) -> f32 { return v / (1.0 + v); }

fn tmReinhardExt(vin : f32, wp : f32) -> f32 {
  let v = sanitize(vin);
  let w2 = max(wp * wp, 1.0e-12);
  if (v > 1.0) { return (1.0 + v / w2) / (1.0 + 1.0 / v); }
  return (v * (1.0 + v / w2)) / (1.0 + v);
}

fn tmACES(vin : f32) -> f32 {
  let v = sanitize(vin);
  let a = 2.51; let b = 0.03; let c = 2.43; let d = 0.59; let e = 0.14;
  return clamp((v * (a * v + b)) / (v * (c * v + d) + e), 0.0, 1.0);
}

fn tmLog(vin : f32, wp : f32) -> f32 {
  let v = sanitize(vin);
  return log(1.0 + v) / log(1.0 + max(wp, 1.0e-6));
}

fn toneMap(vin : f32, op : i32, wp : f32) -> f32 {
  let v = sanitize(vin);
  if (op == 1) { return tmReinhard(v); }
  if (op == 2) { return tmReinhardExt(v, wp); }
  if (op == 3) { return tmACES(v); }
  if (op == 4) { return tmLog(v, wp); }
  return clamp(v, 0.0, 1.0);
}

@vertex
fn vs(@builtin(vertex_index) vi : u32) -> @builtin(position) vec4f {
  var xy = array<vec2f, 3>(vec2f(-1.0, -1.0), vec2f(3.0, -1.0), vec2f(-1.0, 3.0));
  return vec4f(xy[vi], 0.0, 1.0);
}

@fragment
fn fs(@builtin(position) fragCoord : vec4f) -> @location(0) vec4f {
  let dims = vec2f(textureDimensions(fillTex));
  let uv = fragCoord.xy / dims;

  // Trace/HDR contribution is zero in rung 1; start from the fill color.
  var color = textureSampleLevel(fillTex, samp, uv, 0.0).rgb;

  // Background replaces pixels with negligible light (post-exposure threshold).
  let mask = step(vec3f(1.0e-6), color);
  color = mix(p.background, color + vec3f(p.ambient), mask);

  // Tone mapping (per channel).
  let op = i32(p.tonemap);
  color = vec3f(toneMap(color.r, op, p.white_point),
                toneMap(color.g, op, p.white_point),
                toneMap(color.b, op, p.white_point));
  color = clamp(color, vec3f(0.0), vec3f(1.0e10));

  // Contrast.
  color = clamp((color - vec3f(0.5)) * p.contrast + vec3f(0.5), vec3f(0.0), vec3f(1.0));

  // Saturation (BT.709 luma).
  if (p.saturation != 1.0) {
    let lum = dot(color, vec3f(0.2126, 0.7152, 0.0722));
    color = clamp(mix(vec3f(lum), color, p.saturation), vec3f(0.0), vec3f(1.0));
  }

  // Temperature.
  if (p.temperature != 0.0) {
    color = color * vec3f(1.0 + p.temperature * 0.3, 1.0, 1.0 - p.temperature * 0.3);
  }

  // Gamma.
  color = pow(color, vec3f(p.inv_gamma));

  color = color * p.opacity;
  return vec4f(color, 1.0);
}
`;
