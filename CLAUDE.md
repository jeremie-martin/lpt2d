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

# Headless (EGL, no display needed) — honors shot camera/look/trace from file
./build/lpt2d-cli --scene scenes/prism.json --output render.png

# CLI flags override shot defaults
./build/lpt2d-cli --scene scenes/prism.json --exposure 3 --rays 50000000

# Python animation
python anim/examples/orbiting_beam.py
```

Key CLI flags: `--scene` (builtin name or path to `.json` file), `--rays`, `--width/height`, `--depth`, `--batch`, `--exposure`, `--gamma`, `--tonemap (none|reinhard|reinhardx|aces|log)`, `--white-point`, `--ambient`, `--background`, `--opacity`, `--intensity`. All flags override the shot file's saved values.

## Benchmarking

```bash
# General benchmark/gallery snapshot
RAYS=100000000 bash benchmark.sh
bash benchmark-compare.sh benchmarks/dir_a benchmarks/dir_b

# Focused optimization harness
bench/bench.sh
bench/bench.sh --quick
```

`benchmark.sh` is the best general benchmark snapshot over the built-in scene
set, especially for answering "where are we on performance now, and how does it
compare with before?"

`bench/bench.sh` is a focused optimization harness for particular benchmark
work and should not be treated as the general benchmark entry point.

## Architecture

2D spectral light path tracer. GPU compute shader traces rays, emits line segments to an SSBO, then instanced draw rasterizes them as anti-aliased quads with additive blending to a float32 FBO.

### Shot: the authored document

The central concept is the **Shot** — the complete authored document that preserves what the user sees. A Shot contains:

- **Scene** (content): shapes, lights, groups, materials
- **Camera2D**: authored viewport framing (bounds or center+width)
- **Canvas**: output resolution (width x height)
- **Look**: post-processing settings (exposure, tonemap, gamma, normalize, etc.)
- **TraceDefaults**: ray tracing quality (rays, batch, depth, intensity)

The GUI save/load, CLI, and Python API all operate on Shots. The one GUI-only exception is trace batch size: the GUI always uses a session batch of `20_000`, ignores any saved `trace.batch` when loading, and omits `trace.batch` when saving.

### Layer model

The same data flows through five layers. **All layers must stay consistent.**

| Layer | Material fields | Shot fields | Materials dict |
|-------|----------------|-------------|----------------|
| **C++ scene.h** | 8 fields on `Material` struct | `Shot` (Scene + Camera2D + Canvas + Look + TraceDefaults) | `Scene::materials` (map) |
| **GPU structs** (renderer.cpp) | Same 8 fields in std430 layout | `PostProcess` + `TraceConfig` (runtime) | Flattened at upload |
| **GLSL shader** (trace.comp) | Same 8 fields in `Hit` struct | Uniforms | N/A |
| **JSON** (serialize.cpp) | All 8 read/written | v4 format: camera/canvas/look/trace blocks | `"materials"` dict |
| **Python** (anim/types.py) | Same 8 fields on `Material` dataclass | `Shot` (Scene + Camera2D + Canvas + Look + TraceDefaults) | `Scene.materials` dict |

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
  types.py                  — Shot model mirroring C++ (Shot, Scene, Canvas, Look, TraceDefaults, Camera2D, Material, Shape, Light, Group)
  renderer.py               — C++ subprocess wrapper, render/render_still/render_contact_sheet
  builders.py               — Shape composition: polygon, regular_polygon, mirror_box/mirror_block, thick_arc/thick_segment, biconvex_lens, prism, slit, double_slit, grating, waveguide, elliptical_lens
  track.py                  — Keyframe animation with easing
  easing.py                 — 11 built-in easing functions
  stats.py                  — Frame statistics (luminance, clipping, percentiles)
  examples/                 — Working animation examples
scenes/                     — JSON shot files (v4 format, the single source of truth)
src/
  core/                     — lpt2d-core static library (no GUI/windowing deps)
    scene.h/cpp             — Vec2, Material, Shape/Light variants, Scene, Shot, Camera2D, Canvas, Look, TraceDefaults, intersection, bounds
    scenes.h/cpp            — runtime scene discovery from scenes/ directory (returns Shot)
    renderer.h/cpp          — GPU pipeline: framebuffers, compute dispatch, instanced draw, post-processing
    spectrum.h/cpp          — CIE 1931 wavelength→RGB (Gaussian fit), uploaded as 1D texture LUT
    export.h/cpp            — PNG export via stb_image_write
    serialize.h/cpp         — JSON shot save/load (v4 format, file and string APIs)
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
4. Upload to SSBOs (GPUCircle, GPUSegment, GPUArc, GPUBezier, GPUEllipse, GPULight)
5. GPU struct layout verified by `static_assert` on sizeof

### GUI editing

- **Selection**: Click to select shapes/lights/groups. Shift-click for multi-select. Box select.
- **Transforms**: G=grab, R=rotate, S=scale. Axis lock with X/Y. Numeric input. Shift=snap.
- **Enter-group editing**: Double-click a group member to enter the group. Properties panel shows individual member materials. Escape exits.
- **Material Library**: Named materials with create/edit/delete/apply-to-selection. Preset buttons for common materials.
- **Undo/Redo**: Ctrl+Z/Ctrl+Shift+Z, 200-level history (tracks Scene only, not Look/TraceDefaults).
- **Save/Load**: Ctrl+S/Ctrl+O saves/loads the Shot (scene content + camera + look + trace + canvas), except GUI trace batch size, which is session-only and always resets to `20_000`.

### Important constraints

- **NVIDIA EGL driver quirk**: `glGetTexImage` returns stale data after many additive-blend draw operations. Always use `glReadPixels` on an FBO with `glFinish()` for reliable readback.
- **GPU struct layout**: C++ structs (GPUCircle/GPUSegment/GPUArc/GPUBezier/GPUEllipse/GPULight) must exactly match GLSL std430 layout. All have `static_assert` on sizeof.
- **Shader editing**: Edit `.glsl` files in `src/shaders/`, not embedded strings. The build system generates `build/generated/shaders.h` automatically.
- **Scene editing**: Edit `.json` files in `scenes/`. Scenes are loaded from disk at runtime — no rebuild needed.
- **String-to-enum parsing**: Use `parse_tonemap()` and `parse_normalize_mode()` from `scene.h` — do not duplicate the string-matching logic.

### JSON shot format (version 4)

```json
{
  "version": 4,
  "name": "scene_name",
  "camera": { "bounds": [-1.2, -0.675, 1.2, 0.675] },
  "canvas": { "width": 1920, "height": 1080 },
  "look": { "exposure": -5, "gamma": 2, "tonemap": "reinhardx", "white_point": 0.5, "normalize": "rays" },
  "trace": { "rays": 10000000, "depth": 12 },
  "materials": {
    "glass": {"ior": 1.5, "transmission": 1, "cauchy_b": 20000},
    "mirror": {"metallic": 1, "roughness": 0.1, "albedo": 0.95, "transmission": 1}
  },
  "shapes": [
    {"type": "circle", "center": [0, 0], "radius": 0.2, "material": "glass"},
    {"type": "segment", "a": [-1, -0.7], "b": [1, -0.7], "material": {"albedo": 0}},
    {"type": "ellipse", "center": [0, 0], "semi_a": 0.3, "semi_b": 0.15, "rotation": 0.5, "material": "glass"}
  ],
  "lights": [
    {"type": "point", "pos": [0, 0.5], "intensity": 1},
    {"type": "parallel_beam", "a": [-0.5, 0.8], "b": [0.5, 0.8], "direction": [0, -1], "angular_width": 0, "intensity": 1},
    {"type": "spot", "pos": [0, 1], "direction": [0, -1], "angular_width": 0.5, "falloff": 2, "intensity": 1}
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

Camera, canvas, look, and trace blocks are at the root level alongside scene content. Shapes can reference materials by name (string) or inline (object). Named references are resolved from the `materials` dict at load time.

**Camera** can specify `bounds` (explicit viewport) or `center` + `width` (height derived from canvas aspect). Omit for auto-fit from scene geometry.

**Look** only needs to include non-default values. Defaults: exposure=-5, contrast=1, gamma=2, tonemap=reinhardx, white_point=0.5, normalize=rays, ambient=0, background=[0,0,0], opacity=1.

**Trace** only needs to include non-default values. Defaults: rays=10M, batch=200K, depth=12, intensity=1. The GUI does not persist `trace.batch`: it always uses `20_000` as an interactive session default.

### Python animation API

```python
from anim import Shot, Scene, Frame, Look, Camera2D, Timeline, render

# Load a shot file
shot = Shot.load("scenes/three_spheres.json")

# Create from preset
shot = Shot.preset("production", rays=20_000_000)

# Animation callback returns Scene or Frame
def animate(ctx):
    return Frame(
        scene=Scene(shapes=[...], lights=[...]),
        camera=Camera2D(bounds=[-1, -1, 1, 1]),
        look=Look(exposure=3.0, tonemap="reinhardx"),
    )

render(animate, Timeline(10.0), "output.mp4", settings="preview")
```

Key types: `Shot` (authored document), `Scene` (content only), `Canvas`, `Look`, `TraceDefaults`, `Camera2D`, `Frame` (per-frame return from animate callback), `Quality` presets (draft/preview/production/final).

**Shape types**: `Circle`, `Segment`, `Arc`, `Bezier`, `Polygon`, `Ellipse` (center + semi_a/semi_b + rotation).

**Light types**: `PointLight`, `SegmentLight`, `BeamLight`, `ParallelBeamLight` (segment origin + direction + spread), `SpotLight` (point + direction + cone + cosine-power falloff).

**Builder functions** (`anim/builders.py`): `polygon`, `regular_polygon`, `rectangle`, `mirror_box`, `mirror_block`, `thick_arc`, `thick_segment`, `prism`, `slit`, `double_slit`, `grating`, `waveguide`, `elliptical_lens`, `biconvex_lens`, `plano_convex_lens`, `hemispherical_lens`, `ball_lens`.
