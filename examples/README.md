# Examples

This directory is the canonical public example pack for the repo.

The goal is a small, workflow-first set of examples that show how the project
is meant to be used now.

## Canonical Pack

- [beam_chamber_starter.py](/home/holo/prog/lpt2d/examples/python/beam_chamber_starter.py)
  Procedural-from-scratch authoring.
- [prism_crown_builder.py](/home/holo/prog/lpt2d/examples/python/prism_crown_builder.py)
  Builder- and composition-driven authoring.
- [solid_surface_gallery.py](/home/holo/prog/lpt2d/examples/python/solid_surface_gallery.py)
  A compact survey of solid-object surface authoring and simple group animation.
- [thick_arc_demo.py](/home/holo/prog/lpt2d/examples/python/thick_arc_demo.py)
  Auto-smoothed thick-arc shading, explicit sharp cap joins, and selective
  end-cap beveling.
- [twin_prisms_scene_patch.py](/home/holo/prog/lpt2d/examples/python/twin_prisms_scene_patch.py)
  Load, patch, and animate an authored shot.
- [three_spheres_center_zoom.py](/home/holo/prog/lpt2d/examples/python/three_spheres_center_zoom.py)
  Camera-only animation on a saved authored shot.

Run examples from the repo root:

```bash
python examples/python/beam_chamber_starter.py
python examples/python/prism_crown_builder.py --hq
python examples/python/solid_surface_gallery.py --fast
python examples/python/thick_arc_demo.py
python examples/python/twin_prisms_scene_patch.py --frame 0
python examples/python/three_spheres_center_zoom.py --fast
```

Shared example flags:

- `--hq` - render the HQ preset instead of preview
- `--frame N` - render a still instead of a movie
- `--output PATH` - override the default output path
- `--fast` - enable the renderer's half-float fast mode

## Polygon Join Notes

- `thick_arc_demo.py` shows the current builder behavior: `smooth_angle`
  drives polygon `auto` smoothing, the flat cap joins are authored `sharp`, and
  end-cap beveling remains separate geometric rounding.
- Explicit per-vertex polygon join overrides are authored with
  `Polygon(..., join_modes=[...])`; see
  [docs/AUTHORED.md](/home/holo/prog/lpt2d/docs/AUTHORED.md) for concrete
  Python and JSON examples.
- The conceptual distinction between `auto`, `sharp`, `smooth`, and geometric
  rounding is documented in
  [docs/OUTLINE_JOIN_SEMANTICS.md](/home/holo/prog/lpt2d/docs/OUTLINE_JOIN_SEMANTICS.md).

## Relationship To Other Surfaces

- Built-in JSON shots in [`scenes/`](/home/holo/prog/lpt2d/scenes) remain the
  runtime and benchmark scene set.
- Secondary or exploratory Python scripts live in
  [`anim/examples/secondary/`](/home/holo/prog/lpt2d/anim/examples/secondary).
- Render outputs belong under [`renders/`](/home/holo/prog/lpt2d/renders) or
  local scratch space, not in the example pack itself.
