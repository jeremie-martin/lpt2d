# Visual Iteration

This document describes the current Phase 2 workflow surface for look
development, clutter diagnostics, and fast comparison.

Static `Scene` and `Shot` subjects are analyzed once by default. Animated
callbacks are the shot-aware path that samples representative frames across
time.

## Python

Shot-aware analysis works best when you pass a full [`Shot`](/home/holo/prog/lpt2d/anim/types.py)
or an animation callback plus `settings=shot`.

Key helpers:

- `auto_look(...)`
  Sample representative frames and suggest one stable look.
- `compare_looks(...)`
  Compare candidate looks across the same sampled frames.
- `look_report(...)`
  Flag dark, bright, clipped, or low-contrast frames across a shot.
- `diagnose_scene(scene)`
  Fast structural warnings for dense or clutter-prone scenes.
- `light_contributions(...)`
  Measure authored source share with one neutral linear reference.
- `scene_light_report(...)`
  Human-readable light contribution summary.
- `structure_contribution(...)`
  Measure whether removing one shape brightens, dims, or barely changes the frame.

Example:

```python
from anim import Look, Shot, compare_looks, look_report, scene_light_report

shot = Shot.load("scenes/prism.json")

comparison = compare_looks(
    shot,
    looks=[
        shot.look,
        shot.look.with_overrides(exposure=shot.look.exposure + 0.75),
    ],
)
print(comparison.summary())
print(look_report(shot, shot.look).summary())
print(scene_light_report(shot))
```

## GUI

The GUI now supports three complementary iteration loops:

- Full-shot A/B comparison.
  `Snapshot A` captures a frozen viewport image, its metrics, the authored shot
  state at capture time, and the current comparison framing. `Show A` displays
  that frozen capture; `Show B` returns to the live shot inside the same
  captured framing.
- Diagnostic comparison.
  The `Stats` panel shows the current histogram and luminance metrics, and when
  a snapshot is active it also shows the delta versus snapshot A.
- Clutter inspection.
  `Analyze Contributions` reports authored source share using the same neutral
  linear reference, authored shot framing, and authored source set as the
  Python helper. The scene panel surfaces structural warnings from
  `diagnose_scene` on that same authored scene.

Useful shortcuts:

- `Alt+scroll`
  Exposure scrub.
- `[` / `]`
  Exposure nudge.
- `` ` ``
  Toggle snapshot A/B when a snapshot exists.

## Semantics

The contribution report is intentionally *not* a post-tonemap “energy” claim.
It is a linear frame-share diagnostic measured with:

- one neutral linear look
- one shared fixed normalization reference captured from the full scene
- the same authored framing for every compared render

That keeps source shares additive and makes GUI/Python diagnostics tell the
same story.

## Output

`Export PNG` renders the active authored shot at its authored canvas size.
When snapshot A is showing, export uses the captured authored shot state rather
than the live viewport buffer.
