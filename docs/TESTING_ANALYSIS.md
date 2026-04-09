# Production Testability Execution Spec

This document is the short-to-medium term execution plan for testing work on
the real production code in `lpt2d`: `src/core/` and `anim/`.

It is intentionally PR-oriented. Each section describes a concrete slice of
work that should be reviewable on its own.


## Scope

In scope:

- `anim/analysis.py`
- `anim/light_analysis.py`
- `anim/stats.py` where it supports extracted analysis logic
- `src/core/*.cpp` and `src/core/*.h`
- test files that directly cover the production code above
- CMake changes needed to build and run native C++ tests

Out of scope for this plan:

- `evaluation/`
- benchmark capture or reporting workflows
- GUI automation
- broad CI redesign
- large public API redesign unless a smaller extraction is impossible


## Constraints

- Prefer small PRs with one clear testing or testability objective each.
- Do not add abstraction layers just to satisfy a testing pattern.
- Do not add test-only hooks that distort the production API.
- Keep existing public behavior stable unless a test exposes a real bug.
- Prefer deterministic contracts and direct assertions over mocks.


## Order of work

Short term:

1. Extract pure look-selection logic from `anim.analysis.auto_look()`.
2. Add a native C++ test harness to the build.
3. Add first-wave C++ geometry tests.

Medium term:

4. Add C++ scene-validation and serialization coverage.
5. Clean up shared analysis helpers across `anim.analysis` and
   `anim.light_analysis`.
6. Add C++ color and spectrum reference tests.


## PR 1: Extract auto-look decision logic

### Goal

Remove the need to monkeypatch renderer calls when testing `auto_look()`
behavior.

Today `auto_look()` mixes three concerns:

- subject and frame selection
- normalize-ref calibration and render orchestration
- exposure and look selection from `FrameStats`

The third piece should be directly testable without patching
`renderer_mod.render_stats()`.

### Production changes

- Extract the pure decision logic from `anim.analysis.auto_look()` into a small
  helper or helpers.
- Keep `auto_look()` as the render-orchestration wrapper.
- Keep authored look-field preservation in the wrapper result path.
- Keep normalize-ref calibration in the wrapper path, not in the pure helper.

Possible shapes are acceptable as long as the boundary is clear. Examples:

- `_compute_auto_look_from_stats(...) -> Look`
- `_choose_auto_exposure(...) -> float`
- `_summarize_brightness(...) -> float`

Do not spend this PR on naming debates. The key requirement is that the logic
become directly testable from `FrameStats`.

### Test changes

- Replace the monkeypatched `auto_look()` logic tests in
  `tests/test_workflow.py` with direct tests of the extracted helper.
- Keep or add a small wrapper-level test for:
  - authored look-field preservation
  - shot-derived draft canvas and trace settings
  - explicit `normalize="rays"` skipping fixed normalize calibration

The wrapper tests may still patch true render boundaries if needed, but the
core look-selection behavior should no longer depend on patching renderer
internals.

### Acceptance criteria

- The core exposure-selection behavior is covered by direct data-driven tests.
- The `auto_look()` wrapper remains the public entry point.
- `tests/test_workflow.py` no longer needs monkeypatching for the pure decision
  path.

### Not in this PR

- `evaluation/`
- `compare_looks()` and `look_report()` cleanup beyond what is necessary to keep
  the extraction coherent


## PR 2: Add a native C++ test harness

### Goal

Create a fast native test layer for `src/core/` so low-level failures are found
before they surface as noisy Python or render regressions.

### Production and build changes

- Add `enable_testing()` to CMake.
- Add a native test target, for example `lpt2d-core-tests`.
- Add a `tests/cpp/` directory with one test executable built from multiple test
  source files.
- Keep the harness lightweight. Do not introduce a large dependency stack or a
  framework evaluation detour.

The harness can be:

- a tiny in-tree assertion runner, or
- a single-header framework if it is added with minimal friction

The choice matters less than keeping the first PR small and usable.

### Initial test surface

This PR should include only enough tests to prove the harness works:

- one geometry-focused file
- one scene or serialization-focused smoke file

### Acceptance criteria

- `ctest` runs and reports native test results.
- The native tests build as part of the existing CMake workflow.
- No Python bindings are required to exercise the new native tests.

### Not in this PR

- broad coverage across all core modules
- benchmark or performance assertions


## PR 3: First-wave C++ geometry tests

### Goal

Cover the most deterministic geometry helpers and intersection primitives with
fast native tests.

### Focus area

Start with functions whose contracts are already explicit in `src/core/geometry.h`
and `src/core/scene.h`:

- angle normalization and arc sweep helpers
- arc point and bounds helpers
- polygon winding helpers
- per-vertex corner-radius and join-mode helpers
- selected primitive intersections with analytic expected results

Recommended first set:

- `normalize_angle()`
- `clamp_arc_sweep()`
- `arc_end_angle()`
- `angle_in_arc()`
- `arc_bounds()`
- `polygon_signed_area2()`
- `polygon_is_clockwise()`
- `polygon_effective_corner_radius()`
- `polygon_effective_join_mode()`
- `intersect()` for segment, circle, and arc cases with simple deterministic
  scenes

### Production changes

- Refactor only where needed to make deterministic geometry behavior testable.
- If a helper is too entangled to test directly, split the helper. Do not push
  the test back up into a render.

### Acceptance criteria

- Geometry failures point to geometry tests rather than only to image-level
  regressions.
- The added tests are deterministic and fast.
- No render session is involved in this layer.

### Not in this PR

- polygon fill raster behavior through rendered images
- shader behavior


## PR 4: C++ scene-validation and serialization coverage

### Goal

Move more authored-contract failures down to the layer where they actually
occur: scene validation and shot parsing.

### Focus area

- `validate_scene()`
- `try_load_shot_json_string()`
- `load_shot_json_string()`
- JSON roundtrip invariants where they are well-defined

Key cases:

- duplicate entity ids
- unknown `material_id`
- polygon `corner_radii` / `join_modes` length mismatches
- malformed or missing required JSON fields
- strict format rejection
- successful parse of a minimal valid shot

### Production changes

- Keep parser and validation behavior explicit.
- If error reporting is too implicit to test well, tighten the code boundary or
  helper split rather than broadening mocks on the Python side.

### Acceptance criteria

- Parser and validator regressions fail at the native layer.
- Python authored tests can focus more on cross-language and user-facing
  behavior instead of being the first line of defense for every validation case.

### Not in this PR

- legacy-format migration work
- evaluation scene corpus changes


## PR 5: Consolidate analysis helpers across `anim.analysis` and `anim.light_analysis`

### Goal

Reduce duplicated render-analysis setup in the Python production code so the
analysis surface is easier to test and evolve.

### Why this matters

`anim.analysis` and `anim.light_analysis` both build draft analysis shots,
sample frames, call `render_stats()`, and interpret `FrameStats`. The overlap is
not the main correctness risk today, but it is a medium-term maintainability and
testability issue.

### Production changes

Extract small internal helpers for patterns such as:

- building a draft analysis shot from a subject shot
- rendering one analysis frame versus multiple sampled frames
- converting absent stats results into a single explicit fallback path

The result should be less duplicated orchestration, not a new framework.

### Test changes

- Add direct tests where logic becomes data-driven.
- Keep render-backed tests for behavior that is genuinely about rendered output.

### Acceptance criteria

- `anim.analysis` and `anim.light_analysis` share obvious internal behavior
  through small helpers instead of copy-pasted orchestration.
- The changes improve readability and testability without broad API churn.

### Not in this PR

- new public analysis APIs unless a tiny public helper is clearly justified
- evaluation integration


## PR 6: Add C++ color and spectrum reference tests

### Goal

Put a native correctness floor under color and spectrum behavior that is
currently under-tested relative to its importance.

### Focus area

- neutral/default material spectral behavior
- reference wavelength-to-RGB behavior
- stability of helper functions under representative wavelengths
- simple conservation or monotonicity properties where the contract is clear

### Production changes

- Prefer narrow helper extraction if a function cannot be tested without pulling
  in unrelated machinery.
- Keep this focused on deterministic helpers, not renderer-wide image tests.

### Acceptance criteria

- The core color and spectrum math has at least a small direct native test set.
- Regressions in these helpers do not have to be inferred only through rendered
  images.

### Not in this PR

- look-development threshold tuning
- benchmark threshold changes


## Definition of done for this plan

This execution spec is complete when:

- `auto_look()` decision logic is directly testable without renderer monkeypatch
- `src/core/` has a working native test harness in CMake
- geometry, validation, serialization, and at least one color/spectrum slice
  have native deterministic coverage
- duplicated analysis orchestration in `anim/` is reduced where it blocks clear
  tests


## Explicitly deferred

These are valid topics, but not part of this execution plan:

- `evaluation/` refactors
- benchmark-corpus policy
- end-to-end CLI benchmarking workflows
- GUI automation strategy
- broad pytest marker and CI policy work unless it becomes necessary to support
  the production-code PRs above
