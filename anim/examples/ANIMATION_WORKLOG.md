# Animation Worklog

Scope: example-layer authoring only. No changes to `anim/` core modules, shaders, or renderer behavior are assumed here.

## House Preferences

- Prefer one Python file per animation.
- Prefer keeping materially different versions as sibling files instead of overwriting the older script.
- Prefer per-animation output folders so preview/HQ/sheet/json assets stay grouped.
- Prefer mirror-box rooms with metallic walls and a little roughness.
- Prefer brighter images over darker ones as a general rule, unless a scene needs stronger contrast.
- Prefer no ambient by default.
- Prefer lifting brightness with exposure, white point, or carefully placed support beams before falling back to ambient.
- Prefer warm beam ranges around `550-780 nm`, especially when paired with broader white light.
- Prefer beam-heavy scenes over emissive-material lighting for now.

## Current Layout

- `_clean_room_shared.py`
  Shared example-only utilities: room/material constants, tuning, bounds audit, rendering/export helpers.
- `_clean_room_registry.py`
  Batch registry for clean-room examples.
- `clean_room_*.py`
  One authored file per animation or preserved variant.
- `clean_room_gallery.py`
  Thin batch runner only.

## What Works Well

- `clean_room_mirror_shutters.py`
  Strong central silhouette, good candidate for longer HQ renders.
- `clean_room_orbiting_triplet.py`
  Nice motion language once the top fill is removed and the beam path stays wall-safe.
- `clean_room_caustic_ladder.py`
  Good legibility because the objects are compact and simple.
- `clean_room_arc_resonator.py`
  Strong result from script-side scene changes, not from a renderer bug fix.
- Warm beam plus white beam pairings
  Good direction for future variants.

## Current Pain Points

- Stats-only tuning does not measure object legibility.
- Stats-only tuning does not measure color harmony.
- Mirror rooms amplify clutter quickly when refractive geometry gets dense.
- There is still no built-in wireframe/object-outline overlay for scene readability checks.
- There is still no core built-in bounds audit; the current bounds check lives in example code only.
- Beams can dominate a frame so strongly that extra fill lights become distracting instead of helpful.

## Practical Rules For New Scenes

- Keep animated beam origins inside the room at sampled frames.
- Keep animated geometry inside the room at sampled frames.
- Avoid top-edge segment fill unless it is the explicit point of the composition.
- Prefer wall-lighting or sidewash support beams over direct point-light fill on hero objects.
- For complex refractive scenes, simplify geometry first before adding more lights.
- Keep emissive materials out of this iteration track.

## Scene Notes

### Orbiting Triplet

- Removed the top segment fill.
- Moved the beam to a wall-safe elliptical orbit.
- Better as a bright, beam-led scene than as a fill-led scene.

### Breathing Lenses

- Simpler two-lens layout is easier to read than the denser lens bank.
- This scene benefits from keeping the beam path direct and the motion restrained.

### Mirror Shutters

- Best example so far of a clean central idea.
- Good candidate for exploring longer durations and higher ray counts.

### Arc Resonator

- The good version is the new wall-safe center-gap version.
- A useful next variant is a dual-beam composition with one warm beam and one white beam.

## Second Wave Notes

- Strong new additions:
  `arc_bloom`, `resonator_weave`, `prism_bridge`, `prism_drum`, `iris_gate`, `splitter_compass`, and `splitter_crown`.
- The warm-plus-white pairing worked especially well for:
  `prism_drum`, `counter_rotor`, `louver_fan`, and `beam_exchange`.
- A targeted brightness rescue pass materially improved:
  `counter_rotor`, `iris_gate`, `louver_fan`, `prism_drum`, `silk_waveguide`, and `caustic_stair`.
- Scenes that still read as moodier than the current house preference:
  `mirror_fan`, `bridge_ribbon`, and `prism_constellation`.
- Scenes that are bright but clip more than ideal:
  `focus_columns`, `doublet_grid`, and `halo_lenses`.

## Future `anim` Package Ideas

Not to implement now, but worth recording:

- Wireframe or object-outline overlays for readability checks.
- Built-in bounds auditing for animated groups and lights.
- Better non-visual diagnostics for color balance and subject legibility.
- Scene-side reports that combine exposure tuning, bounds audit, and clipping summaries automatically.
