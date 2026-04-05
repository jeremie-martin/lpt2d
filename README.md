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

## Run

```bash
# Interactive GUI
./build/lpt2d --scene diamond

# Headless render from a saved scene
./build/lpt2d-cli --scene scenes/prism.json --output render.png

# Python animation example
python anim/examples/orbiting_beam.py
```

## Repository Layout

- `src/` — C++ core, shaders, GUI app, and CLI
- `anim/` — Python authoring and animation library
- `scenes/` — saved JSON shots
- `tests/` — physics, workflow, and regression tests
- `bench/` — benchmark harness and benchmark scenes
- `docs/` — documentation that is not specific to one subsystem
- `renders/` — curated output notes and render artifacts

## Key Docs

- [ROADMAP.md](/home/holo/prog/lpt2d/ROADMAP.md)
  Strategic project direction.
- [docs/README.md](/home/holo/prog/lpt2d/docs/README.md)
  Documentation index.
- [docs/ROADMAP_GUIDELINES.md](/home/holo/prog/lpt2d/docs/ROADMAP_GUIDELINES.md)
  What a good roadmap should be for this project.
- [CLAUDE.md](/home/holo/prog/lpt2d/CLAUDE.md)
  Technical repo guide for coding agents and contributors.
- [OPTIMIZATION_LOG.md](/home/holo/prog/lpt2d/OPTIMIZATION_LOG.md)
  Benchmark-driven performance work and findings.
- [pre-phase1-plan-transcript.md](/home/holo/prog/lpt2d/pre-phase1-plan-transcript.md)
  Historical planning transcript that led to the first major roadmap reset.

## Examples And Scenes

The repo currently has:

- built-in JSON scenes in [`scenes/`](/home/holo/prog/lpt2d/scenes)
- Python animation examples in [`anim/examples/`](/home/holo/prog/lpt2d/anim/examples)

Those examples and scenes are important, but they should not be mistaken for a
massive canonical content library. The roadmap intentionally favors a compact,
high-signal example set that pressure-tests the tool honestly.

## Design Priorities

- Physical accuracy is non-negotiable.
- The Python API is the primary authored surface.
- The GUI, JSON format, and Python API should feel like one coherent tool.
- Render-based tests and benchmarks matter more than hand-wavy confidence.
- Simplicity matters: avoid unnecessary abstraction and needless complexity.
