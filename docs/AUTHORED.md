# Authored Format

This repo treats authored shot JSON as a strict `version: 10` format.

## Policy

- Python and C++ loaders reject authored JSON whose `version` is not `10`.
- The repo does not keep fallback readers or compatibility branches for older
  authored shot versions.
- Format changes should land as explicit repo-wide migrations across scenes,
  tests, examples, and docs.

## Committed Scene Conventions

Committed files in [`scenes/`](/home/holo/prog/lpt2d/scenes) follow one
normalized authored model:

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

## Polygon Fields

`Polygon` supports four authored corner/shading controls:

- `corner_radius`
  Uniform convex corner bevel-fillet radius.
- `corner_radii`
  Optional per-vertex bevel-fillet override. When non-empty, it must match
  `vertices.size()` and overrides `corner_radius`.
- `join_modes`
  Optional per-vertex shading join override. When non-empty, it must match
  `vertices.size()`. Entries are `auto`, `sharp`, or `smooth`.
- `smooth_angle`
  Optional shading-normal threshold in radians for `auto` polygon joins. It
  only affects polygon edge shading; intersection geometry, fill, perimeter,
  and emission remain geometric.

Concave polygon vertices stay sharp for both smoothing and bevel-filleting.

## Surface Alignment

The same authored concepts should mean the same thing in:

- Python `Shot` and `Scene`
- C++ `Shot` and `Scene`
- GUI save and load
- CLI load and save
- built-in JSON scenes
- benchmark scenes

Frame-specific render choices such as the runtime `frame` stay outside
the authored document. They are render context, not saved shot state.
