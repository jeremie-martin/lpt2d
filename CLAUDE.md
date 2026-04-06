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

## Evaluation

The `evaluation/` Python package provides fidelity comparison and timing
measurement for optimization work:

```python
from evaluation import compare_render_results, save_baseline, load_baseline

# Compare two render results (pixels + FrameMetrics + timing)
result = compare_render_results(result_a, result_b)
print(result.verdict, result.psnr, result.time_a_ms, result.time_b_ms)

# Save/load baselines
save_baseline("baselines/scene_name", result)
baseline = load_baseline("baselines/scene_name")
```

`RenderResult.time_ms` gives wall-clock frame time measured inside C++
`render_frame()` (excludes session creation / cold start).

## Current Repo Truth

- Authored shot JSON is strict `version: 7`.
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
- `src/core/serialize_json.cpp` - strict authored v7 JSON save/load using
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
- `evaluation/` - fidelity comparison and timing measurement
- `tests/` - workflow, physics, and regression coverage
- `docs/` - small stable documentation set
- `renders/` - curated render outputs

## Practical Notes

- Edit GLSL in `src/shaders/`; the build regenerates embedded shader headers.
- Edit scene JSON under `scenes/`; no rebuild is required.
- Use `parse_tonemap()` and `parse_normalize_mode()` from `scene.h` instead of
  duplicating enum parsing logic.
- Keep docs aligned with the code. Delete superseded design notes instead of
  leaving them behind as parallel truth.
