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
- `iter_frame_variants(...)`
  Trace one frame once, then stream many post-processing variants over that
  retained frame.
- `render_frame_variants(...)`
  Materialize a small named set of post-processing variants for one traced
  frame.
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

### Render Once, Tune Many

Post-processing parameters such as exposure, contrast, gamma, tonemap,
temperature, saturation, highlights, and shadows are replayable in Python.
They use the same retained HDR accumulation that the GUI uses for real-time
look edits.

```python
for variant in iter_frame_variants(
    animate,
    timeline,
    frame=analysis_frame,
    settings=shot,
    camera=camera,
    variants=random_look_overrides,
    analyze=True,
):
    metrics = metrics_from_analysis(variant.result.analysis)
    if verdict_for(metrics).ok:
        save_image(path, variant.result.pixels, variant.result.width, variant.result.height)
        accepted_look = variant.look
        break
```

This is intended for workflows such as crystal-field catalog search: generate
one scene, choose the analysis frame, try many random post-processing variants,
accept the first one whose metrics pass, and only generate a new scene if none
of those variants works.

Replay targets the most recent traced frame in the session. Scene, camera,
resolution, trace depth, ray count, or light changes require a fresh render.
`normalize="max"` is replayable, but it still scans the retained HDR buffer to
find the max/percentile, so it is cheaper than tracing but not free.

See `examples/experiments/post_process_sweep.py` for a minimal runnable sweep.

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

Polygon authoring is inspector-first: the polygon panel exposes the
`Auto smooth angle`, per-vertex `join_modes` (`auto`, `sharp`, `smooth`), and
uniform or per-vertex bevel editing. The viewport overlay follows rounded
polygon geometry instead of always drawing the raw vertex chain.

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
