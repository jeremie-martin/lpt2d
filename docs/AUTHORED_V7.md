# Authored V7

This repo treats authored shot JSON as a strict `version: 7` format.

## Policy

- Python and C++ loaders reject authored JSON whose `version` is not `6`.
- The repo does not keep fallback readers or compatibility branches for older
  authored shot versions.
- Format changes should land as explicit repo-wide migrations across scenes,
  tests, examples, and docs.

## Committed Scene Conventions

Committed files in [`scenes/`](/home/holo/prog/lpt2d/scenes) and
[`bench/scenes/`](/home/holo/prog/lpt2d/bench/scenes) follow one normalized
authored model:

- every persisted shape, light, and group has a stable non-empty authored `id`
- committed ids do not use legacy generated names such as `root_*`
- scenes define a top-level `materials` library
- committed shapes use `material_id` bindings instead of inline `material`
  payloads
- authored JSON keeps explicit `camera`, `canvas`, `look`, `trace`,
  `materials`, `shapes`, `lights`, and `groups` blocks
- `look`, `trace`, and material objects store their full canonical field sets
- authored `trace` includes `seed_mode`

Inline shape materials are still supported for transient or one-off data, but
the committed repo baseline uses named materials and explicit bindings.

## Surface Alignment

The same authored concepts should mean the same thing in:

- Python `Shot` and `Scene`
- C++ `Shot` and `Scene`
- GUI save and load
- CLI load and save
- built-in JSON scenes
- benchmark scenes

Frame-specific render choices such as the runtime `frame_index` stay outside
the authored document. They are render context, not saved shot state.
