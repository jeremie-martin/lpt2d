# Examples

This directory is the canonical public example pack for the repo.

The goal is a small, workflow-first set of examples that show how the project
is meant to be used now.

## Canonical Pack

- [beam_chamber_starter.py](/home/holo/prog/lpt2d/examples/python/beam_chamber_starter.py)
  Procedural-from-scratch authoring.
- [prism_crown_builder.py](/home/holo/prog/lpt2d/examples/python/prism_crown_builder.py)
  Builder- and composition-driven authoring.
- [twin_prisms_scene_patch.py](/home/holo/prog/lpt2d/examples/python/twin_prisms_scene_patch.py)
  Load, patch, and animate an authored shot.
- [three_spheres_center_zoom.py](/home/holo/prog/lpt2d/examples/python/three_spheres_center_zoom.py)
  Camera-only animation on a saved authored shot.

Run examples from the repo root:

```bash
python examples/python/beam_chamber_starter.py
python examples/python/prism_crown_builder.py --hq
python examples/python/twin_prisms_scene_patch.py --frame 0
python examples/python/three_spheres_center_zoom.py --fast
```

Shared example flags:

- `--hq` - render the HQ preset instead of preview
- `--frame N` - render a still instead of a movie
- `--output PATH` - override the default output path
- `--fast` - enable the renderer's half-float fast mode

## Relationship To Other Surfaces

- Built-in JSON shots in [`scenes/`](/home/holo/prog/lpt2d/scenes) remain the
  runtime and benchmark scene set.
- Secondary or exploratory Python scripts live in
  [`anim/examples/secondary/`](/home/holo/prog/lpt2d/anim/examples/secondary).
- Render outputs belong under [`renders/`](/home/holo/prog/lpt2d/renders) or
  local scratch space, not in the example pack itself.
