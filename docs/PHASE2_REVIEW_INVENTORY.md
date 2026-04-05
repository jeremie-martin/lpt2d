# Phase 2 Review Inventory

This document turns the current Phase 2 implementation into reviewable
behavior slices so correctness bugs can be found systematically rather than by
ad hoc file reading.

The point is not style review. The point is to find accuracy bugs, semantic
mismatches, parity breaks, state leakage, missing edge cases, and claims that
the code or tests cannot actually defend.

## Source Of Truth

- `ROADMAP.md` Phase 2: what the phase is supposed to accomplish
- `docs/VISUAL_ITERATION.md`: the currently claimed Phase 2 workflow surface
- `README.md`: public summary of what now exists
- the current Phase 2 implementation across Python, CLI, C++, GUI, shader, and
  tests

## Review Rules

- Review by behavior slice, not by individual file.
- Trace each feature end to end:
  authored model -> Python API -> wire/JSON/CLI transport -> C++ renderer/GUI
  -> export/output -> tests/docs.
- Check accuracy and correctness in general, not just the checklist items.
- Treat missing tests, docs overclaims, and GUI/CLI/Python parity breaks as
  real findings.
- Prefer concrete findings with a clear argument or repro over vague concern.

Each review should answer:

1. What is this feature supposed to mean?
2. Does every layer implement the same meaning?
3. Where can default values, resets, state transitions, or aspect/resolution
   differences break that meaning?
4. What important cases are untested or undocumented?

Each reviewer should return:

- findings first, ordered by severity
- exact file and line references
- why the behavior is wrong or risky
- open questions and missing coverage after the findings

## Current Phase 2 Surface Map

- Python look and diagnostic helpers:
  `auto_look`, `compare_looks`, `look_report`, `diagnose_scene`,
  `light_contributions`, `scene_light_report`, `structure_contribution`
- Look/stat model additions:
  `Look`, `LookProfile`, `LookComparison`, `LookReport`,
  `LightContribution`, `StructureReport`
- CLI and stream overrides for look fields, histogram metrics, and frame
  reports
- GUI snapshot A/B comparison, stats delta view, scene warnings, and authored
  source contribution analysis
- Postprocess additions:
  saturation and vignette
- Test additions:
  workflow, stats, and authored-v5 round-trip coverage

## Review Groups

### 1. Look Model, Transport, And Override Semantics

Goal:
Make sure authored `Look` meaning survives every transport path and can be
overridden or reset correctly.

Primary files:

- `anim/types.py`
- `anim/renderer.py`
- `src/core/scene.h`
- `src/core/serialize.cpp`
- `src/core/serialize.h`
- `src/cli/main.cpp`

What to verify:

- every `Look` field survives save/load and Python/C++ interchange
- per-frame `Frame.look` overrides have correct partial-override semantics
- default-valued fields can still be explicitly reset when the user asks
- stream session defaults and per-frame overrides merge correctly
- CLI flags, shot JSON, and GUI-authored state mean the same thing
- analysis helpers that intentionally use neutral looks actually neutralize all
  relevant fields

Likely subtle bug classes:

- explicit-zero or reset values silently dropped
- field added in one transport path but missing in another
- session defaults leaking into per-frame overrides
- save/load round-trip success masking stream/render-path bugs
- analysis helpers accidentally inheriting artistic look fields

### 2. Shot-Wide Look Development And Statistics

Goal:
Verify that the shot-aware Python helpers actually operate at shot/animation
scope and that the stats they report are numerically coherent.

Primary files:

- `anim/renderer.py`
- `anim/stats.py`
- `tests/test_workflow.py`
- `tests/test_stats.py`

What to verify:

- static `Scene`, `Shot`, and animated callback subjects all resolve correctly
- authored camera/canvas/trace defaults are inherited where promised
- frame sampling and representative-frame selection are correct
- `auto_look` heuristics are defensible and stable across time
- `compare_looks` compares the same frames under the same draft conditions
- `look_report` flags are numerically consistent with `FrameStats`
- `LookProfile.best()` scoring matches the intended concept of a good look

Likely subtle bug classes:

- wrong frame indices or off-by-one sampling
- wrong camera/canvas/trace inheritance
- static and animated paths diverging semantically
- analysis renders not matching claimed authored framing
- mean/stability/clipping heuristics behaving differently than documented

### 3. Structural Diagnostics And Contribution Analysis

Goal:
Check whether the tool actually explains clutter and source/structure influence
the way the Phase 2 docs claim.

Primary files:

- `anim/types.py`
- `anim/renderer.py`
- `src/core/scene.cpp`
- `src/core/scene.h`
- `src/app/app.cpp`
- `docs/VISUAL_ITERATION.md`

What to verify:

- Python and GUI `diagnose_scene` semantics stay aligned
- group transforms and grouped lights/shapes are handled correctly
- source enumeration covers explicit lights, group lights, and emissive shapes
- solo-source isolation logic is correct and non-mutating
- shared normalization reference logic stays additive and comparable
- structure contribution diffs are interpreted correctly
- GUI contribution analysis tells the same story as Python helpers

Likely subtle bug classes:

- grouped content handled differently from top-level content
- transformed bounds or overlaps analyzed incorrectly
- unnamed emissive shapes merged or mislabeled
- contributor isolation mutating the caller scene
- Python and GUI using different notions of "contribution"
- warnings or reports overclaiming what they actually measure

### 4. GUI Comparison Workflow And State Separation

Goal:
Verify the GUI as an exploration/comparison tool rather than just isolated UI
controls.

Primary files:

- `src/app/app.cpp`
- `docs/VISUAL_ITERATION.md`

What to verify:

- `Snapshot A` captures the correct scene, look, filters, and framing
- `Show A` / `Show B` switches between isolated states without bleeding edits
- comparison framing lock behaves as described
- snapshot stats and live stats are actually comparable
- hidden/solo/filter state is captured and reused correctly
- compare mode and export/output paths use the correct shot state
- keyboard shortcuts and disabled UI states match the intended workflow

Likely subtle bug classes:

- snapshot/live state leakage
- stale metrics after toggles or scene changes
- filters/view bounds captured from the wrong state
- export using live state while UI shows snapshot state, or vice versa
- compare mode accidentally using window/session state instead of authored shot

### 5. Postprocess, Renderer, Shader, And Output Parity

Goal:
Verify that Phase 2 polish features and display metrics behave consistently
across live GUI, CLI output, Python output, and exported images.

Primary files:

- `src/core/renderer.cpp`
- `src/core/renderer.h`
- `src/shaders/postprocess.frag`
- `src/cli/main.cpp`
- `src/app/app.cpp`

What to verify:

- saturation and vignette semantics are well defined and stable
- aspect, resolution, and camera differences are intentional and consistent
- postprocess order is defensible and consistent with docs/UI expectations
- GUI preview and exported/rendered output use the same look semantics
- histogram, clipping, and luminance stats are computed from the intended stage
- neutral diagnostic looks remain neutral in every path

Likely subtle bug classes:

- GUI preview parity differing from CLI/export parity
- aspect-sensitive effects keyed to window aspect instead of authored canvas
- postprocess applied in different orders in different paths
- stats measured from the wrong buffer or color space
- fields exposed in UI but not honored by output paths

### 6. Tests, Docs, And Claim Coverage

Goal:
Find where the code claims more than the tests or docs can currently support.

Primary files:

- `tests/test_workflow.py`
- `tests/test_stats.py`
- `tests/test_authored_v5.py`
- `README.md`
- `docs/README.md`
- `docs/VISUAL_ITERATION.md`

What to verify:

- each public Phase 2 feature has at least one behavioral test, not just
  serialization coverage
- cross-layer parity has direct tests where the implementation is fragile
- docs describe actual semantics rather than aspirational semantics
- docs avoid ambiguous words like "energy" when the metric is really display
  share or linear luma
- examples reflect current APIs and defaults

Likely subtle bug classes:

- serializer tests passing while runtime behavior is wrong
- docs calling something "shot-aware" or "stable" without strong evidence
- important negative cases untested: reset semantics, grouped content,
  snapshot/export parity, GUI-vs-output parity

## Suggested Sub-Agent Package

Use `gpt-5.4` with `xhigh` reasoning effort. Each agent should do review only,
not patching, and should focus on correctness and accuracy rather than style.

### Agent A: Look Transport Semantics

Scope:

- `anim/types.py`
- `anim/renderer.py` (`Renderer` setup and `_build_wire_json`)
- `src/core/scene.h`
- `src/core/serialize.cpp`
- `src/core/serialize.h`
- `src/cli/main.cpp`

Mission:
Review `Look` and render-override transport semantics end to end. Focus on
field survival, reset behavior, partial overrides, session/default merges, and
Python/CLI/C++ parity.

### Agent B: Lookdev Analysis And Stats

Scope:

- `anim/renderer.py`
- `anim/stats.py`
- `tests/test_workflow.py`
- `tests/test_stats.py`

Mission:
Review `auto_look`, `compare_looks`, `look_report`, `LookProfile`,
`LookComparison`, and `LookReport` for correctness, sampling accuracy,
heuristic defensibility, and test gaps.

### Agent C: Diagnostics And Contribution Analysis

Scope:

- `anim/types.py`
- `anim/renderer.py`
- `src/core/scene.cpp`
- `src/core/scene.h`
- diagnostic/contribution sections of `src/app/app.cpp`

Mission:
Review structural warnings, authored source enumeration, solo-source isolation,
shared normalization references, structure contribution semantics, and Python
vs GUI parity.

### Agent D: GUI Comparison Workflow

Scope:

- compare/snapshot/view/state/output/stats sections of `src/app/app.cpp`
- `docs/VISUAL_ITERATION.md`

Mission:
Review Snapshot A/B, state capture, view lock, stats delta comparability,
filter capture, and export behavior. Focus on state separation and user-visible
workflow correctness.

### Agent E: Postprocess And Output Parity

Scope:

- `src/core/renderer.cpp`
- `src/core/renderer.h`
- `src/shaders/postprocess.frag`
- `src/app/app.cpp`
- `src/cli/main.cpp`

Mission:
Review saturation/vignette/postprocess semantics, stage ordering, aspect and
resolution dependence, live-preview vs export parity, and stats readback
correctness.

### Agent F: Tests And Docs Audit

Scope:

- `tests/test_workflow.py`
- `tests/test_stats.py`
- `tests/test_authored_v5.py`
- `README.md`
- `docs/README.md`
- `docs/VISUAL_ITERATION.md`

Mission:
Audit whether the current tests and docs actually justify the public Phase 2
claims. Focus on missing behavioral coverage, misleading language, and places
where subtle bugs could still hide because coverage is too shallow.

## Ready-To-Send Prompt Template

Use this template for each agent, replacing the scope and mission:

```text
Review the current Phase 2 implementation for correctness and accuracy.

Scope:
- <files>

Mission:
- <mission>

Review rules:
- Review only. Do not patch code.
- Look for behavioral bugs, semantic mismatches, parity breaks, state leakage,
  numerical mistakes, missing edge cases, missing tests, and docs that
  overclaim.
- Trace the feature end to end across the layers in scope.
- Be skeptical of "it looks wired" without proof.

Return format:
1. Findings first, ordered by severity.
2. Each finding must include exact file references and a concrete explanation
   of why it is wrong or risky.
3. Then list open questions or coverage gaps.
4. Keep the summary brief.
```

## Recommended Execution Order

- Run Agents A through E in parallel.
- Run Agent F in parallel as a coverage/docs cross-check.
- Synthesize duplicate findings centrally before making fixes.
- After fixes, run one final parity review focused on:
  Python vs CLI vs GUI vs export behavior for the same authored shot.
