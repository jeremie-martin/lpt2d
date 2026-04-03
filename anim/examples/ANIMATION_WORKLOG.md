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
- `_clean_room_factories.py`
  Reusable scene-construction helpers for large family waves, including arc, prism, ribbon, fin, spoke, and beacon patterns.
- `_clean_room_registry.py`
  Batch registry for clean-room examples.
- `clean_room_families/`
  Large curated family modules used for high-scene-count expansion.
- `clean_room_scene.py`
  Named scene runner for the registry.
- `clean_room_audit.py`
  Bulk non-visual audit runner for bounds and base-exposure metrics.
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

## Library Expansion Notes

- The library now sits at `1,064` registry scenes across `20` families:
  `arcs`, `beacons`, `canopies`, `cloisters`, `crossfires`, `fins`, `gates`, `hybrids`, `lenses`, `mandalas`, `mirrors`, `orbits`, `prisms`, `ribbons`, `rotors`, `spines`, `splitters`, `trusses`, `vaults`, and `wells`.
- Preview defaults were raised slightly to `640x360` so promoted previews stay cleaner without turning the promotion pass into an HQ-only workflow.
- The large-wave expansion is now driven by reusable pattern helpers rather than only by top-level one-off scene files.
- The newest structural helpers that paid off are:
  `make_fin_array_spec`, `make_spoke_array_spec`, and `make_beacon_stack_spec`.
- The current canonical render tree is family-based under `renders/clean_room/<family>/<scene>/`.
- Full-library baseline assets are now:
  `frame_000.json`, `manifest.json`, and `library_audit*.json`.
- Full-library media renders are now intentionally staged rather than required for every scene in a large wave.

## Current Audit Findings

- Bounds failures in `rotor_family` were fixed by tightening the `CROSS`/`QUAD` pivot spreads and a few overlong blade variants.
- `lens_family` was the main clipping hotspot; layout-aware exposure trims brought it down materially, but it still runs hotter than the rest of the library.
- A mild family-wide lift helped `splitter_family` and `prism_family` avoid the dimmest tails without causing a new clipping spike.
- `ribbon_family` remains acceptable overall, but some `left` and `exchange` motifs still read moodier than the house preference.
- In the third-wave structural families, `mandalas` and `wells` currently give the cleanest brightness/clipping balance, while `beacons`, `fins`, and `vaults` still run hotter in their triad-heavy variants.
- `make_beacon_stack_spec` initially spaced rows too tall for the largest lens nodes; tightening the row span and rail height fixed the whole beacon/spine cluster in one place.
- Targeted scene-side bounds trims were needed for `gate_threshold_spine_*` and `mandala_lattice_open`.
- For mirror-room work, clipping diagnostics are still harsher than the artistic target; the current numeric thresholds are useful for ranking outliers but not as absolute accept/reject gates.

## Promotion Notes

- New-wave scenes promoted to rendered sheet/preview status in the current pass:
  `beacon_rampart_warm`, `canopy_fin_awning_crest`, `canopy_spoke_spray_crest`, `cloister_web_apse_crest`, `fin_bracket_crest`, `gate_portcullis_dual`, `mandala_rosette_crest`, `spine_bridge_beamline`, `truss_bastion`, `vault_arc_nave_warm`, `vault_fin_span_warm`, and `well_aperture_window`.
- Families that are currently strongest for clean readable expansion work:
  `mandalas`, `wells`, `canopies`, and `trusses`.
- Families that likely need another brightness/clipping pass before broad promotion:
  `beacons`, `fins`, `vaults`, and the hotter `spines` variants.

## Scaling Direction

- For `5,000+` scenes, treat the work as a catalog problem rather than a flat authored-example problem.
- Add families through curated recipe modules, not through one-off top-level files.
- Keep non-visual audit first, metadata export second, and media render promotion third.
- Reserve full preview/video renders for curated subsets, family samples, or on-demand promotion passes.

## Future `anim` Package Ideas

Not to implement now, but worth recording:

- Wireframe or object-outline overlays for readability checks.
- Built-in bounds auditing for animated groups and lights.
- Better non-visual diagnostics for color balance and subject legibility.
- Scene-side reports that combine exposure tuning, bounds audit, and clipping summaries automatically.
