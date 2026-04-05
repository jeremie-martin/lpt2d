# Examples

This directory is the canonical public example surface for the repo.

The Phase 0 baseline defines a compact, workflow-first pack instead of treating
every historical script as an equal-status exemplar. The goal is to show how
the project is meant to be used now.

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
