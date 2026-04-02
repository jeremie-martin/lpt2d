# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

Produces three targets: `build/lpt2d` (interactive GUI), `build/lpt2d-cli` (headless renderer), and `liblpt2d-core.a` (static library). C++23 required. System dependencies: OpenGL, GLEW, GLFW3, EGL (Mesa).

## Run

```bash
# Interactive (GLFW window + ImGui controls)
./build/lpt2d --scene diamond

# Headless (EGL, no display needed)
./build/lpt2d-cli --scene prism --width 1920 --height 1080 --rays 100000000 --output render.png
```

Key CLI flags: `--scene`, `--rays`, `--width/height`, `--depth`, `--batch`, `--exposure`, `--tonemap (none|reinhard|aces|log)`.

## Benchmarking

```bash
RAYS=100000000 bash benchmark.sh                          # run all 10 scenes
bash benchmark-compare.sh benchmarks/dir_a benchmarks/dir_b  # HTML side-by-side
```

The benchmark script forces Release build, archives the binary, and produces `results.json` + `index.html` gallery.

## Architecture

2D spectral light path tracer. GPU compute shader traces rays, emits line segments to an SSBO, then instanced draw rasterizes them as anti-aliased quads with additive blending to a float32 FBO.

### Project structure

```
CMakeLists.txt              — three targets: lpt2d-core (lib), lpt2d (GUI), lpt2d-cli (headless)
cmake/embed_shaders.cmake   — build-time GLSL→C++ header embedding
src/
  core/                     — lpt2d-core static library (no GUI/windowing deps)
    scene.h/cpp             — Vec2, Material, Shape/Light variants, Scene, intersection, bounds
    renderer.h/cpp          — GPU pipeline: framebuffers, compute dispatch, instanced draw, post-processing
    spectrum.h/cpp          — CIE 1931 wavelength→RGB (Gaussian fit), uploaded as 1D texture LUT
    export.h/cpp            — PNG export via stb_image_write
    serialize.h/cpp         — JSON scene save/load
    scenes.h                — 10 built-in scene factory functions + SceneFactory type + get_all_scenes()
  shaders/                  — standalone GLSL files (embedded at build time → build/generated/shaders.h)
    trace.comp              — main ray tracing compute kernel
    line.vert/frag          — instanced anti-aliased line rasterization
    postprocess.vert/frag   — HDR tone mapping + gamma correction
    max_reduce.comp         — parallel max reduction for normalization
  app/                      — lpt2d interactive GUI executable
    main.cpp                — GUI entry point
    app.h/cpp               — GLFW window + ImGui frame loop
    editor.h/cpp            — scene editing: selection, transforms, handles, undo, clipboard
    ui.h/cpp                — ImGui panels, material editor, overlay drawing, style
  cli/                      — lpt2d-cli headless executable
    main.cpp                — CLI entry point
    headless.h/cpp          — EGL context (GL 4.3+ required)
```

### Pipeline

1. **Scene upload** — `std::variant`-based shapes/lights/materials flattened into SSBOs (GPUCircle, GPUSegment, GPULight structs must match std430 layout)
2. **Trace compute shader** (`src/shaders/trace.comp`) — each thread traces one ray: light sampling → intersection → Fresnel/Snell scattering with Cauchy dispersion → emit line segments to output SSBO with atomic counter
3. **Instanced line draw** — vertex shader reads segments from SSBO, expands to 3px quads (6 verts per instance via gl_VertexID), fragment shader applies smoothstep AA, additive blend (GL_ONE, GL_ONE) to RGBA32F FBO
4. **Post-process fragment shader** — normalizes by max, applies exposure → tone mapping → contrast → gamma → 8-bit display texture
5. **Max readback** — `glReadPixels` on FBO with `glFinish()` (not `glGetTexImage` — unreliable on NVIDIA EGL after many blending operations)

### Important constraints

- **NVIDIA EGL driver quirk**: `glGetTexImage` returns stale data after many additive-blend draw operations. Always use `glReadPixels` on an FBO with `glFinish()` for reliable readback.
- **GPU struct layout**: C++ structs (GPUCircle/GPUSegment/GPULight) must exactly match GLSL std430 layout. All have `static_assert` on sizeof.
- **Gold standard**: The GPU renderer matches the original CPU tracer output (mean pixel difference < 0.13 at 100M rays, archived in `benchmarks/01_cpu_release_100M/`). Any rendering changes must preserve this.
- **Experiment branch**: `experiment/direct-to-image` has an alternative architecture (Wu AA lines, R32UI fixed-point accumulation, no instanced draw). Faster on light scenes but introduces brightness differences — not production quality.
- **Shader editing**: Edit `.glsl` files in `src/shaders/`, not embedded strings. The build system generates `build/generated/shaders.h` automatically.
