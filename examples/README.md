# Examples

This directory is the canonical public example surface for the repo.

The Phase 0 baseline defines a compact, workflow-first pack instead of treating
every historical script as an equal-status exemplar. The goal is to show how
the project is meant to be used now.

The canonical examples follow the same authored conventions as the committed
JSON scene corpus: stable ids, named material libraries, and strict v5-only
scene semantics.

## Canonical Pack

- [beam_chamber_starter.py](/home/holo/prog/lpt2d/examples/python/beam_chamber_starter.py)
  Procedural-from-scratch authoring: build a compact animated scene entirely in
  Python.
- [prism_crown_builder.py](/home/holo/prog/lpt2d/examples/python/prism_crown_builder.py)
  Builder/composition authoring: reusable optical motifs, repeated structure,
  and group-driven composition.
- [twin_prisms_scene_patch.py](/home/holo/prog/lpt2d/examples/python/twin_prisms_scene_patch.py)
  Load-modify-animate authoring: start from a saved shot, patch named groups,
  shared materials, and lights procedurally, and animate the result.

Run them from the repo root, for example:

```bash
python examples/python/beam_chamber_starter.py
python examples/python/prism_crown_builder.py --hq
python examples/python/twin_prisms_scene_patch.py --frame 0
```

## Relationship To Other Surfaces

- Built-in JSON shots in [`scenes/`](/home/holo/prog/lpt2d/scenes) remain the
  runtime and benchmark scene set.
- Secondary or exploratory Python scripts live in
  [`anim/examples/secondary/`](/home/holo/prog/lpt2d/anim/examples/secondary).
  They are still useful, but they are not the canonical example pack.
- Render artifacts are intentionally out of scope here. Phase 0 defines the
  source surfaces first.

## Visual Iteration Snippet

The canonical examples are authored scenes and animations first, but the Phase
2 workflow now also expects them to pair cleanly with the Python lookdev and
diagnostic helpers:

```python
from anim import Look, Shot, compare_looks, look_report, scene_light_report

shot = Shot.load("scenes/prism.json")
looks = [
    shot.look,
    shot.look.with_overrides(exposure=shot.look.exposure + 0.75),
]

print(compare_looks(shot, looks=looks).summary())
print(look_report(shot, shot.look).summary())
print(scene_light_report(shot))
```

That shot-aware workflow is documented in
[docs/VISUAL_ITERATION.md](/home/holo/prog/lpt2d/docs/VISUAL_ITERATION.md).
