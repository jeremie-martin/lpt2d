# lpt2d

A physically accurate 2D spectral light path tracer for creating beautiful
animations procedurally in Python.

The project is not trying to be a general-purpose DCC or a teaching toy. Its
center of gravity is physically grounded optics in service of visual creation:
strong rendering foundations, a convenient Python authoring surface, JSON scene
interchange, and a GUI for exploration and iteration.

## Current Focus

The engine has already shipped its first major round of foundations,
expressiveness, and workflow work. The current strategic focus is now on making
the whole tool more coherent:

- better authored-scene workflows across Python, JSON, and GUI
- better look development and scene readability
- deeper physical semantics where the current model would become the next limit

For the current roadmap, see [ROADMAP.md](/home/holo/prog/lpt2d/ROADMAP.md).

## Build

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

This produces:

- `build/lpt2d` — interactive GUI
- `build/lpt2d-cli` — headless renderer
- `build/liblpt2d-core.a` — core static library

System dependencies include OpenGL, GLEW, GLFW3, and EGL.
The Python extension module is built when `-DLPT2D_BUILD_PYTHON=ON` (default)
and compatible Python development components are available.

## Static Analysis

The default build keeps compiler warnings enabled on project-owned C++ targets:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

The repo exports `build/compile_commands.json`, and the opt-in analysis targets
reuse that compile database instead of maintaining separate include or flag
lists.

```bash
# Lightweight bug finding
cmake --build build --target static-analysis-cppcheck

# Include hygiene
cmake --build build --target static-analysis-iwyu

# Run both
cmake --build build --target static-analysis
```

Notes:

- `cppcheck` and IWYU are optional local tools, not required for a normal build
- enable `-DLPT2D_CPPCHECK_INCONCLUSIVE=ON` if you want extra advisory cppcheck findings
- the analysis targets only inspect project-owned translation units under `src/`
- normal builds do not use `-Werror`
- IWYU is intended as an explicit cleanup pass after header or API churn, not as
  a constant background task

## Run

```bash
# Interactive GUI
./build/lpt2d --scene diamond

# Headless render from a saved scene
./build/lpt2d-cli --scene scenes/prism.json --output render.png

# Canonical Python animation example
python examples/python/beam_chamber_starter.py
```

## Repository Layout

- `examples/` — canonical public example pack
- `src/` — C++ core, shaders, GUI app, and CLI
- `anim/` — Python authoring and animation library
- `scenes/` — built-in JSON shots for runtime and benchmarks
- `tests/` — physics, workflow, and regression tests
- `bench/` — benchmark harness and benchmark scenes
- `docs/` — documentation that is not specific to one subsystem
- `renders/` — curated output notes and render artifacts

## Key Docs

- [ROADMAP.md](/home/holo/prog/lpt2d/ROADMAP.md)
  Strategic project direction.
- [docs/README.md](/home/holo/prog/lpt2d/docs/README.md)
  Documentation index.
- [docs/AUTHORED_V6.md](/home/holo/prog/lpt2d/docs/AUTHORED_V6.md)
  Strict v6 authored-scene policy and committed scene conventions.
- [docs/SEED_MODE.md](/home/holo/prog/lpt2d/docs/SEED_MODE.md)
  Shared frame-seed semantics across renderer, CLI, Python, and GUI.
- [docs/VISUAL_ITERATION.md](/home/holo/prog/lpt2d/docs/VISUAL_ITERATION.md)
  Shot-aware look development, clutter diagnostics, and GUI comparison workflows.
- [examples/README.md](/home/holo/prog/lpt2d/examples/README.md)
  Canonical example pack and how to run it.
- [docs/ROADMAP_GUIDELINES.md](/home/holo/prog/lpt2d/docs/ROADMAP_GUIDELINES.md)
  What a good roadmap should be for this project.
- [CLAUDE.md](/home/holo/prog/lpt2d/CLAUDE.md)
  Technical repo guide for coding agents and contributors.
- [OPTIMIZATION_LOG.md](/home/holo/prog/lpt2d/OPTIMIZATION_LOG.md)
  Benchmark-driven performance work and findings.

## Examples And Scenes

The repo currently has:

- the canonical example pack in [`examples/`](/home/holo/prog/lpt2d/examples)
- built-in JSON scenes in [`scenes/`](/home/holo/prog/lpt2d/scenes)
- secondary exploratory scripts in
  [`anim/examples/secondary/`](/home/holo/prog/lpt2d/anim/examples/secondary)

The canonical pack is intentionally compact and workflow-first. The built-in
scene set remains important because it still drives runtime discovery and the
general `benchmark.sh` performance workflow.

Built-in authored JSON, the Python API, the CLI, and the GUI all target one
strict v6 authored format. Older authored versions are intentionally rejected;
the project no longer carries fallback compatibility for pre-v6 shot JSON.

## Visual Iteration

Phase 2 work now spans both the Python authoring surface and the GUI:

- Python exposes shot-aware look-development and diagnostic helpers such as
  `auto_look`, `compare_looks`, `look_report`, `diagnose_scene`,
  `light_contributions`, `scene_light_report`, and `structure_contribution`.
- The GUI supports frozen snapshot A/B comparison, live histogram/stat
  inspection, authored-framing light-contribution analysis, structural scene
  warnings, and authored-size PNG export.

See [docs/VISUAL_ITERATION.md](/home/holo/prog/lpt2d/docs/VISUAL_ITERATION.md)
for the current Phase 2 workflow surface.

## Design Priorities

- Physical accuracy is non-negotiable.
- The Python API is the primary authored surface.
- The GUI, JSON format, and Python API should feel like one coherent tool.
- Render-based tests and benchmarks matter more than hand-wavy confidence.
- Simplicity matters: avoid unnecessary abstraction and needless complexity.
