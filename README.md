# lpt2d

`lpt2d` is a physically accurate 2D spectral light path tracer built for
procedural animation. The repo combines a C++ renderer, a Python authoring
surface, strict JSON shot interchange, and a GUI for exploration.

## Current Baseline

- authored shot JSON is strict `version: 10`
- Python and CLI rendering both go through the C++ `RenderSession`
- committed scenes use named material libraries plus `material_id` bindings
- the canonical example pack lives in [`examples/python/`](/home/holo/prog/lpt2d/examples/python)

## Build

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

For the Python package and examples:

```bash
uv pip install -e .
```

This builds:

- `build/lpt2d` - interactive GUI
- `build/lpt2d-cli` - headless renderer
- `build/liblpt2d-core.a` - core static library
- `_lpt2d` - Python extension module installed by the editable package build

## Run

```bash
# GUI
./build/lpt2d --scene diamond

# CLI render
./build/lpt2d-cli --scene scenes/prism.json --output render.png

# Save a resolved shot without rendering
./build/lpt2d-cli --scene prism --save-shot /tmp/prism.json

# Canonical Python example
python examples/python/beam_chamber_starter.py --frame 0

# Authoritative renderer evaluation
python -m evaluation
```

`python -m evaluation` is the central render-speed and render-fidelity
validation command. It builds the project, runs the explicit evaluation scene
corpus, scores performance with a baseline-normalized geometric mean across
benchmark cases, reports grep-friendly summary keys, and writes a detailed
JSON report.

## Test

```bash
python -m pytest tests -q
```

Optional C++ analysis targets:

```bash
cmake --build build --target static-analysis-cppcheck
cmake --build build --target static-analysis-iwyu
```

## Repository Layout

- `src/` - C++ core, CLI, GUI, shaders, and Python bindings
- `anim/` - Python authoring and rendering library
- `examples/` - canonical public example pack
- `scenes/` - built-in authored shots
- `evaluation/` - fidelity comparison and timing measurement
- `tests/` - workflow, physics, and regression tests
- `docs/` - compact project documentation
- `renders/` - curated outputs and render notes

## Key Docs

- [docs/README.md](/home/holo/prog/lpt2d/docs/README.md)
  Documentation index.
- [docs/AUTHORED.md](/home/holo/prog/lpt2d/docs/AUTHORED.md)
  Authored JSON policy and committed scene conventions.
- [docs/VISUAL_ITERATION.md](/home/holo/prog/lpt2d/docs/VISUAL_ITERATION.md)
  Current look-development, comparison, and diagnostic workflow.
- [docs/SEED_MODE.md](/home/holo/prog/lpt2d/docs/SEED_MODE.md)
  Shared seed semantics across Python, CLI, GUI, and renderer.
- [examples/README.md](/home/holo/prog/lpt2d/examples/README.md)
  Canonical examples and how to run them.
- [evaluation/](/home/holo/prog/lpt2d/evaluation/)
  Fidelity comparison and timing measurement.
- [IDEAS.md](/home/holo/prog/lpt2d/IDEAS.md)
  Centralized unscheduled ideas and follow-up work.
- [CLAUDE.md](/home/holo/prog/lpt2d/CLAUDE.md)
  Repo guide for coding agents and contributors working in-tree.
- [OPTIMIZATION_LOG.md](/home/holo/prog/lpt2d/OPTIMIZATION_LOG.md)
  Accepted performance work and rejected experiments.

## Design Priorities

- Physical accuracy is non-negotiable.
- Python is the primary authored surface.
- Python, JSON, CLI, and GUI should tell the same story about a shot.
- Render-based tests and benchmarks matter more than vague confidence.
- Simplicity matters more than elaborate abstraction.
