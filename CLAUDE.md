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

# Python animation
python anim/examples/orbiting_beam.py
```

Key CLI flags: `--scene` (builtin name or path to `.json` file), `--rays`, `--width/height`, `--depth`, `--batch`, `--exposure`, `--tonemap (none|reinhard|reinhardx|aces|log)`, `--ambient`, `--background`, `--opacity`, `--intensity`.

## Benchmarking

```bash
RAYS=100000000 bash benchmark.sh                          # run all 10 scenes
bash benchmark-compare.sh benchmarks/dir_a benchmarks/dir_b  # HTML side-by-side
```

## Architecture

2D spectral light path tracer. GPU compute shader traces rays, emits line segments to an SSBO, then instanced draw rasterizes them as anti-aliased quads with additive blending to a float32 FBO.

### Layer model

The same scene data flows through five layers. **All layers must stay consistent.**

| Layer | Material fields | Render params | Materials dict |
|-------|----------------|---------------|----------------|
| **C++ scene.h** | 8 fields on `Material` struct | `PostProcess` (11) + `TraceConfig` (3) | `Scene::materials` (map) |
| **GPU structs** (renderer.cpp) | Same 8 fields in std430 layout | Uniforms | Flattened at upload |
| **GLSL shader** (trace.comp) | Same 8 fields in `Hit` struct | Uniforms | N/A |
| **JSON** (serialize.cpp) | All 8 read/written | Per-frame overrides in `render` block | `"materials"` dict |
| **Python** (anim/types.py) | Same 8 fields on `Material` dataclass | `RenderSettings` (unified) | `Scene.materials` dict |

### Material system

Materials have 8 properties: `ior`, `roughness`, `metallic`, `transmission`, `absorption`, `cauchy_b`, `albedo`, `emission`.

**Named materials**: Scenes can define a `materials` dictionary mapping names to material definitions. Shapes can reference materials by name (`"material": "glass"`) or inline (`"material": {...}`). Named references are resolved at parse time — shapes always have resolved inline materials at runtime.

**Convenience constructors** (C++ `mat_*`, Python functions):
- `glass(ior, cauchy_b, absorption)` — transparent dielectric
- `mirror(reflectance, roughness)` / `opaque_mirror(...)` — metallic reflector
- `diffuse(reflectance)` — Lambertian scatterer
- `absorber()` — pure black
- `emissive(emission, base)` — adds emission to any base material

**Emissive surfaces**: Shapes with `emission > 0` auto-generate synthetic lights during `upload_scene()`. The shader also boosts energy when rays hit emissive surfaces (dual-path sampling). An emissive-only scene (no explicit lights) renders correctly.

### Post-processing pipeline

Applied per-pixel in `postprocess.frag`:
1. Normalize by divisor (mode: max/rays/fixed/off)
2. Exposure multiply (`2^exposure`)
3. Background replaces unlit pixels; ambient adds to lit pixels
4. Tone map (none/reinhard/reinhardx/aces/log)
5. Contrast
6. Gamma
7. Opacity fade

### Project structure

```
CMakeLists.txt              — three targets: lpt2d-core (lib), lpt2d (GUI), lpt2d-cli (headless)
anim/                       — Python animation library (pip install -e .)
  types.py                  — Scene model mirroring C++ (Material, Shape, Light, Group, Scene)
  renderer.py               — C++ subprocess wrapper, render/render_still/render_contact_sheet
  builders.py               — Shape composition: polygon, regular_polygon, mirror_box, thick_arc, biconvex_lens
  track.py                  — Keyframe animation with easing
  easing.py                 — 11 built-in easing functions
  stats.py                  — Frame statistics (luminance, clipping, percentiles)
  examples/                 — Working animation examples
scenes/                     — JSON scene files (the single source of truth for all scenes)
src/
  core/                     — lpt2d-core static library (no GUI/windowing deps)
    scene.h/cpp             — Vec2, Material, Shape/Light variants, Scene, intersection, bounds
    scenes.h/cpp            — runtime scene discovery from scenes/ directory
    renderer.h/cpp          — GPU pipeline: framebuffers, compute dispatch, instanced draw, post-processing
    spectrum.h/cpp          — CIE 1931 wavelength→RGB (Gaussian fit), uploaded as 1D texture LUT
    export.h/cpp            — PNG export via stb_image_write
    serialize.h/cpp         — JSON scene save/load (file and string APIs)
  shaders/                  — standalone GLSL files (embedded at build time → build/generated/shaders.h)
    trace.comp              — main ray tracing compute kernel
    line.vert/frag          — instanced anti-aliased line rasterization
    postprocess.vert/frag   — HDR tone mapping + gamma correction
    max_reduce.comp         — parallel max reduction for normalization
  app/                      — lpt2d interactive GUI executable
    app.h/cpp               — GLFW window + ImGui frame loop
    editor.h/cpp            — scene editing: selection, transforms, handles, undo, clipboard, group enter/exit
    ui.h/cpp                — ImGui panels, material editor, overlay drawing, style
  cli/                      — lpt2d-cli headless executable
    main.cpp                — CLI entry point, --stream mode for Python bridge
    headless.h/cpp          — EGL context (GL 4.3+ required)
```

### Scene upload pipeline

1. Flatten all shapes: ungrouped `scene.shapes` + transform `scene.groups[*].shapes` → `all_shapes`
2. Flatten all lights: ungrouped `scene.lights` + transform `scene.groups[*].lights` → `all_lights`
3. Auto-generate lights from emissive shapes and append to `all_lights`
4. Upload to SSBOs (GPUCircle, GPUSegment, GPUArc, GPUBezier, GPULight)
5. GPU struct layout verified by `static_assert` on sizeof

### GUI editing

- **Selection**: Click to select shapes/lights/groups. Shift-click for multi-select. Box select.
- **Transforms**: G=grab, R=rotate, S=scale. Axis lock with X/Y. Numeric input. Shift=snap.
- **Enter-group editing**: Double-click a group member to enter the group. Properties panel shows individual member materials. Escape exits.
- **Material Library**: Named materials with create/edit/delete/apply-to-selection. Preset buttons for common materials.
- **Undo/Redo**: Ctrl+Z/Ctrl+Shift+Z, 200-level history.

### Important constraints

- **NVIDIA EGL driver quirk**: `glGetTexImage` returns stale data after many additive-blend draw operations. Always use `glReadPixels` on an FBO with `glFinish()` for reliable readback.
- **GPU struct layout**: C++ structs (GPUCircle/GPUSegment/GPULight) must exactly match GLSL std430 layout. All have `static_assert` on sizeof.
- **Shader editing**: Edit `.glsl` files in `src/shaders/`, not embedded strings. The build system generates `build/generated/shaders.h` automatically.
- **Scene editing**: Edit `.json` files in `scenes/`. Scenes are loaded from disk at runtime — no rebuild needed.
- **String-to-enum parsing**: Use `parse_tonemap()` and `parse_normalize_mode()` from `scene.h` — do not duplicate the string-matching logic.

### JSON scene format (version 3)

```json
{
  "version": 3,
  "name": "scene_name",
  "materials": {
    "glass": {"ior": 1.5, "transmission": 1, "cauchy_b": 20000},
    "mirror": {"metallic": 1, "albedo": 0.95, "transmission": 1}
  },
  "shapes": [
    {"type": "circle", "center": [0, 0], "radius": 0.2, "material": "glass"},
    {"type": "segment", "a": [-1, -0.7], "b": [1, -0.7], "material": {"albedo": 0}}
  ],
  "lights": [
    {"type": "point", "pos": [0, 0.5], "intensity": 1}
  ],
  "groups": [
    {
      "name": "prism",
      "transform": {"translate": [0, 0], "rotate": 0, "scale": [1, 1]},
      "shapes": [...],
      "lights": [...]
    }
  ]
}
```

Shapes can reference materials by name (string) or inline (object). Named references are resolved from the `materials` dict at load time.
