# Visual Iteration

This document describes the current look-development, comparison, and
diagnostic workflow across Python and the GUI.

## Python

Shot-aware helpers work best when you pass a full `Shot` or an animation
callback plus authored settings.

Top-level helpers:

- `auto_look(...)`
  Suggest one stable look from representative frames.
- `compare_looks(...)`
  Compare candidate looks across the same sampled frames.
- `look_report(...)`
  Flag dark, bright, clipped, or low-contrast frames.
- `diagnose_scene(scene)`
  Report structural warnings for dense or clutter-prone scenes.
- `light_contributions(...)`
  Measure authored source share with one neutral linear reference.
- `scene_light_report(...)`
  Summarize source contribution results.
- `structure_contribution(...)`
  Estimate whether removing one structure brightens, dims, or barely changes
  the frame.

The heavier report types live under `anim.stats`.

## GUI

The GUI supports three related iteration loops:

- frozen A/B comparison
  `Snapshot A` captures the current authored shot, frame index, framing, and
  metrics; `Show A` and `Show B (live)` toggle between the frozen capture and
  the live shot
- live stats inspection
  the `Stats` panel shows histogram and luminance metrics, plus deltas against
  snapshot A when comparison is active
- authored-scene diagnostics
  scene warnings come from `diagnose_scene`, and `Analyze Contributions` uses
  the authored shot framing plus a neutral fixed-reference look

Useful shortcuts:

- `Alt+scroll` - exposure scrub
- `[` / `]` - exposure nudge
- `` ` `` - toggle snapshot A/B when a snapshot exists

## Shared Semantics

Contribution analysis is intentionally a diagnostic, not a claim about
post-tonemap "energy". Python and GUI both use:

- one neutral linear look
- one shared fixed normalization reference captured from the full scene
- the same authored framing for every compared render

That keeps the reported source shares additive and comparable.

## Output

`Export PNG` renders the active authored shot at its authored canvas size.
When snapshot A is showing, export uses the captured authored shot state
rather than the live viewport buffer.
