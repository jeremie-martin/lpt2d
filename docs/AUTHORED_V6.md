# Authored V6

This project now treats authored shot JSON as a strict `version: 6` format.

## Policy

- The repo does not carry fallback support for older authored shot versions.
- Python and C++ loaders reject authored JSON whose `version` is not `6`.
- Future format changes should land as explicit repo-wide migrations, not as
  indefinite backward-compatibility baggage.

## Committed Scene Conventions

Committed files in [`scenes/`](/home/holo/prog/lpt2d/scenes) and
[`bench/scenes/`](/home/holo/prog/lpt2d/bench/scenes) are normalized to one
authored model:

- every persisted shape, light, and group has a stable non-empty authored `id`
- committed ids do not use legacy generated `root_*` names
- scenes define a top-level `materials` library
- committed shapes use `material_id` bindings rather than inline `material`
  payloads
- authored JSON is fully explicit: `camera`, `canvas`, `look`, `trace`,
  `materials`, `shapes`, `lights`, and `groups` are always present
- the `camera` block may be `{}` for auto-fit, but the block itself is still
  present
- `look`, `trace`, and material objects use canonical field names only and
  always include their full field sets; material objects include `emission`
- authored `trace` now includes `seed_mode`; runtime frame numbering remains
  separate render state and is not persisted in shot JSON

Inline shape materials remain supported by the format for one-off or transient
data, but authored files are machine-written and strict: there is no fallback
support for sparse authored JSON, legacy aliases, or older on-disk variants.
Sparse per-frame overrides belong to stream `render` payloads, not persisted
authored shots.

## Surface Alignment

The same authored concepts should mean the same thing everywhere:

- Python `Shot` / `Scene`
- C++ `Shot` / `Scene`
- GUI save/load
- CLI load/save
- built-in JSON scenes
- benchmark scenes

Phase 1 closed only because those surfaces now agree on stable ids, shared
material bindings, and strict v6-only authored assets.
