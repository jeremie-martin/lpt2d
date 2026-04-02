# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

The single executable is `build/lpt2d`. C++23 required. System dependencies: OpenGL, GLEW, GLFW3, EGL (Mesa).

## Run

```bash
# Interactive (GLFW window + ImGui controls)
./build/lpt2d --scene diamond

# Headless (EGL, no display needed)
./build/lpt2d --headless --scene prism --width 1920 --height 1080 --rays 100000000 --output render.png
```

Key CLI flags: `--scene`, `--rays`, `--width/height`, `--depth`, `--batch`, `--exposure`, `--tonemap (none|reinhard|aces|log)`.

## Benchmarking

```bash
RAYS=100000000 bash benchmark.sh                          # run all 8 scenes
bash benchmark-compare.sh benchmarks/dir_a benchmarks/dir_b  # HTML side-by-side
```

The benchmark script forces Release build, archives the binary, and produces `results.json` + `index.html` gallery.

## Architecture

2D spectral light path tracer. GPU compute shader traces rays, emits line segments to an SSBO, then instanced draw rasterizes them as anti-aliased quads with additive blending to a float32 FBO.

### Pipeline

1. **Scene upload** — `std::variant`-based shapes/lights/materials flattened into SSBOs (GPUCircle, GPUSegment, GPULight structs must match std430 layout)
2. **Trace compute shader** (`renderer.cpp`, embedded GLSL) — each thread traces one ray: light sampling → intersection → Fresnel/Snell scattering with Cauchy dispersion → emit line segments to output SSBO with atomic counter
3. **Instanced line draw** — vertex shader reads segments from SSBO, expands to 3px quads (6 verts per instance via gl_VertexID), fragment shader applies smoothstep AA, additive blend (GL_ONE, GL_ONE) to RGBA32F FBO
4. **Post-process fragment shader** — normalizes by max, applies exposure → tone mapping → contrast → gamma → 8-bit display texture
5. **Max readback** — `glReadPixels` on FBO with `glFinish()` (not `glGetTexImage` — unreliable on NVIDIA EGL after many blending operations)

### Key files

- `src/renderer.h/cpp` — GPU pipeline: shaders (embedded), framebuffers, compute dispatch, instanced draw, post-processing
- `src/scene.h` — Value types: Vec2, Ray, Hit, Material (`std::variant<Diffuse, Specular, Refractive>`), Shape, Light, Scene
- `src/scenes.h` — 8 built-in scene factory functions
- `src/spectrum.cpp` — CIE 1931 wavelength→RGB (Gaussian fit), uploaded as 1D texture LUT
- `src/app.cpp` — GLFW+ImGui interactive mode
- `src/headless.cpp` — EGL context (GL 4.3+ required, no fallback)

### Important constraints

- **NVIDIA EGL driver quirk**: `glGetTexImage` returns stale data after many additive-blend draw operations. Always use `glReadPixels` on an FBO with `glFinish()` for reliable readback.
- **GPU struct layout**: C++ structs (GPUCircle/GPUSegment/GPULight) must exactly match GLSL std430 layout. All have `static_assert` on sizeof.
- **Gold standard**: The GPU renderer matches the original CPU tracer output (mean pixel difference < 0.13 at 100M rays, archived in `benchmarks/01_cpu_release_100M/`). Any rendering changes must preserve this.
- **Experiment branch**: `experiment/direct-to-image` has an alternative architecture (Wu AA lines, R32UI fixed-point accumulation, no instanced draw). Faster on light scenes but introduces brightness differences — not production quality.
