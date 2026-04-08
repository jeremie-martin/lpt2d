# Authored Format

This repo treats authored shot JSON as a strict `version: 11` format.

## Policy

- Python and C++ loaders reject authored JSON whose `version` is not `11`.
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
- every shape binds to that library through `material_id`
- authored JSON keeps explicit `camera`, `canvas`, `look`, `trace`,
  `materials`, `shapes`, `lights`, and `groups` blocks
- `look`, `trace`, and material objects store their full canonical field sets
- authored `trace` includes `seed_mode`

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

For shading:

- `auto` keeps the conservative angle-based heuristic
- `sharp` forces a flat shading join
- `smooth` forces shading continuity even on concave joins when the normal
  build remains well-defined

Concave polygon joins stay sharp in `auto`, and concave polygon vertices remain
ineligible for bevel fillets. Explicit `join_modes: smooth` can still request
shading continuity at a concave join. Fillets remain convex-only geometry.

## Polygon Examples

Python authoring example:

```python
from anim import Polygon, Scene, mirror

scene = Scene(
    materials={"steel": mirror(1.0)},
    shapes=[
        Polygon(
            id="blade",
            vertices=[
                [-0.8, -0.2],
                [-0.8, 0.2],
                [0.7, 0.2],
                [1.0, 0.0],
                [0.7, -0.2],
            ],
            material_id="steel",
            join_modes=["auto", "sharp", "smooth", "smooth", "auto"],
            corner_radii=[0.0, 0.0, 0.02, 0.0, 0.0],
            smooth_angle=0.9,
        )
    ],
)
```

Authored JSON example:

```json
{
  "id": "blade",
  "type": "polygon",
  "vertices": [[-0.8, -0.2], [-0.8, 0.2], [0.7, 0.2], [1.0, 0.0], [0.7, -0.2]],
  "join_modes": ["auto", "sharp", "smooth", "smooth", "auto"],
  "corner_radii": [0.0, 0.0, 0.02, 0.0, 0.0],
  "smooth_angle": 0.9,
  "material_id": "steel"
}
```

`builders.thick_arc(...)` is a specialized convenience case: when
`smooth_angle > 0`, it keeps the four flat cap joins explicitly `sharp` and
leaves the curved-chain joins in `auto`, so later edits to `smooth_angle`
remain a real threshold rather than a baked smoothing override.

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
