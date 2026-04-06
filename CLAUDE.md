# Repo Guide

This file is for Claude Code and other contributors working directly inside the
repository.

## Build

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

Install the Python package and extension module:

```bash
uv pip install -e .
```

Python examples and tests import `_lpt2d` from the editable install, not from
`build/` directly. After C++ or nanobind changes, rebuild and rerun
`uv pip install -e .` before trusting Python behavior.

## Test And Analysis

```bash
python -m pytest tests -q
cmake --build build --target static-analysis-cppcheck
cmake --build build --target static-analysis-iwyu
```

`cppcheck` and IWYU are optional cleanup passes, not part of every build.

## Run

```bash
# GUI
./build/lpt2d --scene diamond

# CLI
./build/lpt2d-cli --scene scenes/prism.json --output render.png

# Save a resolved shot without rendering
./build/lpt2d-cli --scene prism --save-shot /tmp/prism.json

# Canonical Python example
python examples/python/beam_chamber_starter.py --frame 0
```

## Benchmarking

```bash
# General benchmark/gallery snapshot
bash benchmark.sh

# Focused optimization harness
bench/bench.sh
bench/bench.sh --quick
```

`benchmark.sh` is the broad built-in-scene snapshot. `bench/bench.sh` is the
purpose-built optimization harness with fidelity comparison against a local
baseline.

## Current Repo Truth

- Authored shot JSON is strict `version: 6`.
- Committed scene and benchmark JSON use named materials plus `material_id`
  bindings.
- The C++ authored model uses `MaterialBinding` (`Material` or material-id
  reference).
- Python and CLI rendering both use the in-process C++ `RenderSession`.
- `seed_mode` lives in `Shot.trace`; `frame_index` is runtime-only render
  context.
- The GUI, CLI, Python API, and JSON format are all expected to preserve the
  same authored shot meaning.

## Architecture

The central authored document is `Shot`:

- `Scene` - shapes, lights, groups, materials
- `Camera2D` - authored framing
- `Canvas` - output size
- `Look` - post-process settings
- `TraceDefaults` - ray-tracing defaults

Main runtime layers:

- `src/core/scene.*` - scene model, validation, transforms, geometry helpers
- `src/core/serialize_json.cpp` - strict authored v6 JSON save/load using
  `nlohmann::ordered_json`
- `src/core/session.*` - `RenderSession`, the headless render entry point used
  by Python and CLI
- `src/core/renderer.*` - GPU tracing, rasterization, post-process, readback
- `src/app/` - GUI/editor
- `src/bindings/lpt2d_bindings.cpp` - nanobind bridge for the Python package
- `anim/` - Python authoring, rendering helpers, analysis, builders, tracks

## Project Layout

- `examples/` - canonical public example pack
- `anim/examples/secondary/` - exploratory or superseded examples
- `scenes/` - built-in authored shots
- `bench/scenes/` - benchmark-only shots
- `tests/` - workflow, physics, and regression coverage
- `docs/` - small stable documentation set
- `renders/` - curated render outputs

## Practical Notes

- Edit GLSL in `src/shaders/`; the build regenerates embedded shader headers.
- Edit scene JSON under `scenes/` or `bench/scenes/`; no rebuild is required.
- Use `parse_tonemap()` and `parse_normalize_mode()` from `scene.h` instead of
  duplicating enum parsing logic.
- Keep docs aligned with the code. Delete superseded design notes instead of
  leaving them behind as parallel truth.
