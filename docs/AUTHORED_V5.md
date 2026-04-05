# Authored V5

This project now treats authored shot JSON as a strict `version: 5` format.

## Policy

- The repo does not carry fallback support for older authored shot versions.
- Python and C++ loaders reject authored JSON whose `version` is not `5`.
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
- default-only `look` and `trace` blocks are omitted

Inline shape materials remain supported by the format for one-off or transient
data, but the committed repo corpus is intentionally normalized to named
materials so the GUI, Python API, CLI, and docs all tell the same authored
story.

## Surface Alignment

The same authored concepts should mean the same thing everywhere:

- Python `Shot` / `Scene`
- C++ `Shot` / `Scene`
- GUI save/load
- CLI load/save
- built-in JSON scenes
- benchmark scenes

Phase 1 closed only because those surfaces now agree on stable ids, shared
material bindings, and strict v5-only authored assets.
