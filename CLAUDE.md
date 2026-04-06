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

# Canonical Python animation
python examples/python/beam_chamber_starter.py
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

**Authored version policy:** committed authored JSON is strict `version: 5`.
Older authored shot versions are intentionally rejected; the repo does not
carry compatibility fallback for pre-v5 authored files.

### Layer model

The same data flows through five layers. **All layers must stay consistent.**

| Layer | Material fields | Shot fields | Materials dict |
|-------|----------------|-------------|----------------|
| **C++ scene.h** | 8 fields on `Material` struct | `Shot` (Scene + Camera2D + Canvas + Look + TraceDefaults) | `Scene::materials` (map) |
| **GPU structs** (renderer.cpp) | Same 8 fields in std430 layout | `PostProcess` + `TraceConfig` (runtime) | Flattened at upload |
| **GLSL shader** (trace.comp) | Same 8 fields in `Hit` struct | Uniforms | N/A |
| **JSON** (serialize.cpp) | All 8 read/written | v5 format: authored ids + camera/canvas/look/trace blocks | `"materials"` dict + `material_id` bindings |
| **Python** (anim/types.py) | Same 8 fields on `Material` dataclass | `Shot` (Scene + Camera2D + Canvas + Look + TraceDefaults) | `Scene.materials` dict |

### Material system

Materials have 8 properties: `ior`, `roughness`, `metallic`, `transmission`, `absorption`, `cauchy_b`, `albedo`, `emission`.

**Named materials**: Scenes can define a `materials` dictionary mapping authored material ids to shared material assets. Shapes reference shared assets with `"material_id": "glass"` or carry an inline custom `"material": {...}` block, but never both. Runtime shape structs still keep a resolved material value alongside the authored `material_id` binding.

**Repo policy**: committed scene and benchmark JSON should use named materials
plus `material_id` bindings only. Inline shape materials remain format support
for one-off data, not the normalized repo baseline.

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
7. Saturation (BT.709 luminance mix in post-tonemap linear space)
8. Gamma
9. Vignette (radial edge darkening with configurable radius)
10. Opacity fade

### Project structure

```
CMakeLists.txt              — three targets: lpt2d-core (lib), lpt2d (GUI), lpt2d-cli (headless)
examples/                   — canonical public example pack
  python/                   — workflow-first canonical Python animations
anim/                       — Python animation library (pip install -e .)
  __init__.py               — compact author-facing package surface; advanced APIs use explicit submodules
  types.py                  — Shot model mirroring C++ (Shot, Scene, Canvas, Look, TraceDefaults, Camera2D, Material, Shape, Light, Group)
  renderer.py               — C++ subprocess wrapper plus render/render_still/render_contact_sheet/render_stats
  analysis.py               — auto_look, calibrate_normalize_ref, compare_looks, look_report
  light_analysis.py         — light_contributions, scene_light_report, structure_contribution
  diagnostics.py            — diagnose_scene
  builders.py               — Shape composition: polygon, regular_polygon, mirror_box/mirror_block, thick_arc/thick_segment, biconvex_lens, prism, slit, double_slit, grating, waveguide, elliptical_lens
  track.py                  — Keyframe animation with easing
  easing.py                 — 11 built-in easing functions
  stats.py                  — Frame statistics, QualityGate, StatsDiff, LookProfile/LookComparison/LookReport, LightContribution, StructureReport
  examples/secondary/       — exploratory or superseded Python examples
scenes/                     — JSON shot files (v5 authored format, built-in runtime and benchmark scene set)
src/
  core/                     — lpt2d-core static library (no GUI/windowing deps)
    scene.h/cpp             — Vec2, Material, Shape/Light variants, Scene, Shot, Camera2D, Canvas, Look, TraceDefaults, intersection, bounds
    scenes.h/cpp            — runtime scene discovery from scenes/ directory (returns Shot)
    renderer.h/cpp          — GPU pipeline: framebuffers, compute dispatch, instanced draw, post-processing
    spectrum.h/cpp          — CIE 1931 wavelength→RGB (Gaussian fit), uploaded as 1D texture LUT
    export.h/cpp            — PNG export via stb_image_write
    serialize.h/cpp         — JSON shot save/load (v5 format, file and string APIs)
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
- **Material Library**: Shared materials with create/rename/delete/apply-to-selection. Editing a bound object or library entry updates the shared asset through `material_id`.
- **Undo/Redo**: Ctrl+Z/Ctrl+Shift+Z, 200-level history (tracks Scene only, not Look/TraceDefaults).
- **Save/Load**: Ctrl+S/Ctrl+O saves/loads the Shot (scene content + camera + look + trace + canvas), except GUI trace batch size, which is session-only and always resets to `20_000`.
- **Look scrubbing**: `[`/`]` nudge exposure ±0.5 stops. Alt+scroll in viewport adjusts exposure. Look A/B snapshot/toggle via Display panel buttons or `` ` `` key.
- **Stats overlay**: Collapsible Stats panel shows live histogram, mean/median/p95, black%/clipped%.
- **Light analysis**: "Analyze Lights" button in Objects panel renders each light solo and shows per-light energy% and coverage%.

### Important constraints

- **NVIDIA EGL driver quirk**: `glGetTexImage` returns stale data after many additive-blend draw operations. Always use `glReadPixels` on an FBO with `glFinish()` for reliable readback.
- **GPU struct layout**: C++ structs (GPUCircle/GPUSegment/GPUArc/GPUBezier/GPUEllipse/GPULight) must exactly match GLSL std430 layout. All have `static_assert` on sizeof.
- **Shader editing**: Edit `.glsl` files in `src/shaders/`, not embedded strings. The build system generates `build/generated/shaders.h` automatically.
- **Scene editing**: Edit `.json` files in `scenes/`. Scenes are loaded from disk at runtime — no rebuild needed.
- **String-to-enum parsing**: Use `parse_tonemap()` and `parse_normalize_mode()` from `scene.h` — do not duplicate the string-matching logic.

## Code evolution policy

- No legacy code, no fallbacks, no backward compatibility layers.
- Prefer clean breaks when refactoring or redesigning systems.
- Keep a single canonical implementation; remove superseded paths.
- Optimize for simplicity and iteration speed over stability of old behavior.

### JSON shot format (version 5)

```json
{
  "version": 5,
  "name": "scene_name",
  "camera": { "bounds": [-1.2, -0.675, 1.2, 0.675] },
  "canvas": { "width": 1920, "height": 1080 },
  "look": {
    "exposure": -5.0,
    "contrast": 1.0,
    "gamma": 2.0,
    "tonemap": "reinhardx",
    "white_point": 0.5,
    "normalize": "rays",
    "normalize_ref": 0.0,
    "normalize_pct": 1.0,
    "ambient": 0.0,
    "background": [0.0, 0.0, 0.0],
    "opacity": 1.0,
    "saturation": 1.0,
    "vignette": 0.0,
    "vignette_radius": 0.7
  },
  "trace": { "rays": 10000000, "batch": 200000, "depth": 12, "intensity": 1.0 },
  "materials": {
    "glass": {"ior": 1.5, "roughness": 0.0, "metallic": 0.0, "transmission": 1.0, "absorption": 0.0, "cauchy_b": 20000.0, "albedo": 1.0, "emission": 0.0},
    "floor_absorber": {"ior": 1.0, "roughness": 0.0, "metallic": 0.0, "transmission": 0.0, "absorption": 0.0, "cauchy_b": 0.0, "albedo": 0.0, "emission": 0.0},
    "mirror": {"ior": 1.0, "roughness": 0.1, "metallic": 1.0, "transmission": 1.0, "absorption": 0.0, "cauchy_b": 0.0, "albedo": 0.95, "emission": 0.0}
  },
  "shapes": [
    {"id": "lens", "type": "circle", "center": [0, 0], "radius": 0.2, "material_id": "glass"},
    {"id": "floor", "type": "segment", "a": [-1, -0.7], "b": [1, -0.7], "material_id": "floor_absorber"},
    {"id": "collector", "type": "ellipse", "center": [0, 0], "semi_a": 0.3, "semi_b": 0.15, "rotation": 0.5, "material_id": "glass"}
  ],
  "lights": [
    {"id": "spark", "type": "point", "pos": [0, 0.5], "intensity": 1.0, "wavelength_min": 380.0, "wavelength_max": 780.0},
    {"id": "wash", "type": "parallel_beam", "a": [-0.5, 0.8], "b": [0.5, 0.8], "direction": [0, -1], "angular_width": 0.0, "intensity": 1.0, "wavelength_min": 380.0, "wavelength_max": 780.0},
    {"id": "spot", "type": "spot", "pos": [0, 1], "direction": [0, -1], "angular_width": 0.5, "falloff": 2.0, "intensity": 1.0, "wavelength_min": 380.0, "wavelength_max": 780.0}
  ],
  "groups": [
    {
      "id": "prism",
      "transform": {"translate": [0, 0], "rotate": 0, "scale": [1, 1]},
      "shapes": [...],
      "lights": [...]
    }
  ]
}
```

Authored v5 shots use an explicit root schema: `camera`, `canvas`, `look`,
`trace`, `materials`, `shapes`, `lights`, and `groups` are always present
alongside `version` and `name`. Persisted shapes, lights, and groups all carry
authored `id` values that are globally unique within a scene. Committed repo
scenes use named materials plus `material_id` bindings throughout.

**Camera** can specify `bounds` (explicit viewport) or `center` + `width`
(height derived from canvas aspect). Use `{}` for auto-fit from scene
geometry; the block itself still exists in authored JSON.

**Look** authored blocks are explicit, not sparse. Fields: `exposure`,
`contrast`, `gamma`, `tonemap`, `white_point`, `normalize`,
`normalize_ref`, `normalize_pct`, `ambient`, `background`, `opacity`,
`saturation`, `vignette`, `vignette_radius`. Sparse look overrides only exist
in transient stream `render` payloads and `Frame.look`.

**Trace** authored blocks are explicit, not sparse. Fields: `rays`, `batch`,
`depth`, `intensity`.

**Materials** in authored JSON also use the full explicit field set:
`ior`, `roughness`, `metallic`, `transmission`, `absorption`, `cauchy_b`,
`albedo`, `emission`.

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

Top-level `anim` is intentionally compact now. Advanced APIs should be
imported from explicit submodules such as `anim.types`, `anim.builders`,
`anim.stats`, `anim.renderer`, and `anim.analysis`.

Key top-level types: `Shot` (authored document), `Scene` (content only),
`Canvas`, `Look`, `TraceDefaults`, `Camera2D`, `Frame` (per-frame return from
animate callback).

Additional authored-model types from `anim.types`: `Quality` presets
(`draft`/`preview`/`production`/`final`), `PointLight`, `SpotLight`,
`Bezier`, `Polygon`, `Ellipse`, `FrameReport`, and material helpers such as
`absorber`, `diffuse`, `emissive`, `opaque_mirror`.

**Shape types**: top-level `anim` keeps the most common ones
(`Circle`, `Segment`, `Arc`). Additional authored shapes such as `Bezier`,
`Polygon`, and `Ellipse` live in `anim.types`.

**Light types**: top-level `anim` keeps `BeamLight`, `ParallelBeamLight`, and
`SegmentLight`. `PointLight` and `SpotLight` live in `anim.types`.

**Builder functions**: top-level `anim` keeps `mirror_box`, `prism`,
`elliptical_lens`, and `thick_segment`. The full builder set lives in
`anim/builders.py`: `polygon`, `regular_polygon`, `rectangle`, `mirror_box`,
`mirror_block`, `thick_arc`, `thick_segment`, `prism`, `slit`,
`double_slit`, `grating`, `waveguide`, `elliptical_lens`, `biconvex_lens`,
`plano_convex_lens`, `hemispherical_lens`, `ball_lens`.
