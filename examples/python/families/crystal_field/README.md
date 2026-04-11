# Crystal Field

Point lights drifting through a grid of small objects in a mirror box.

Each object refracts or scatters the light into caustic fans.  Because
the objects are packed in a grid, these fans overlap and interfere.  As
the light moves, the entire pattern shifts continuously.  The mirror
walls bounce escaped light back into the field.

## Package structure

| File | Purpose |
|------|---------|
| `params.py` | Config dataclasses (Grid, Shape, Material, Light, Params), constants |
| `grid.py` | Grid position generation, hole removal |
| `shapes.py` | Object construction (circles, rounded polygons) |
| `materials.py` | Glass and diffuse material creation |
| `channels.py` | Corridor graph for channel-constrained light paths |
| `paths.py` | 5 light path generators + arc-length track conversion |
| `scene.py` | Scene assembly — the `build()` function |
| `sampling.py` | Parameter generation — the `sample()` function |
| `check.py` | Rejection gates (light-radius + luminance metrics) |
| `describe.py` | One-line variant summary |
| `stats.py` | Parameter distribution analysis (no rendering) |

## How parameter generation works

`sample(rng)` builds a `Params` through a layered decision tree:

1. **Grid** — spacing drives density.  30% chance of a small sparse grid
   (3–5 rows, 4–7 cols); otherwise derived from spacing.
2. **Shape** — 60% polygon (3–6 sides, always with rounded corners),
   40% circle.  Polygons get optional rotation and per-object jitter.
3. **Material** — polygons are always diffuse (straight edges + glass =
   chaotic).  Circles are mostly glass (90%).  IOR is continuous
   [1.3, 2.2] biased toward high values (wider caustics).
4. **Light** — 1–3 moving lights at constant speed.  Speed decreases
   with more lights and with glass material.  When objects have no
   spectral color, 35% chance the moving light gets a warm color
   (orange/deep-orange spectral range).  Ambient lights at corners are the
   default (70%).

## Commands

```bash
# Standard Family commands
python -m examples.python.families.crystal_field search -n 4
python -m examples.python.families.crystal_field survey -n 16
python -m examples.python.families.crystal_field render path/to/params.json
python -m examples.python.families.crystal_field catalog \
  --out renders/lpt2d_crystal_field_catalog_YYYYMMDD \
  --web-out renders/lpt2d_crystal_field_catalog_YYYYMMDD_web

# Parameter distributions (instant, no rendering)
python -m examples.python.families.crystal_field stats
python -m examples.python.families.crystal_field stats -n 50000 --seed 99
```

## Key tunable ranges

| Parameter | Range | Notes |
|-----------|-------|-------|
| IOR | 1.3–2.2 (beta, mode ~1.8) | Higher = wider caustics |
| Spacing | 0.18–0.30 | Controls object density |
| Speed | 0.08–0.25 u/s | Reduced for multi-light and glass |
| Ambient intensity | 0.1–0.4 | Per corner/side light |
| Exposure | -5.5 to -3.5 | Log scale brightness |
| Corner radius | 10–35% of size | Always applied to polygons |

## Rejection Criteria

Variants are rejected only by the current light-radius and luminance gates:

- Moving light radius: 1.0% to 4.2% of the short image side.
- Ambient light radius: 0.8% to 4.2% of the short image side.
- Mean moving radius divided by mean ambient radius: 1.0 to 2.33.
- Near-black fraction: below 3.5%.
- Brightness: below 150 on the 0-255 luminance scale.
- Contrast spread: above 5 on the 0-255 luminance scale.

`check.py` first selects the frame where moving lights are furthest from
object centres, then computes all gates from the core `FrameAnalysis`
binding for that frame.  Catalog PNGs and authored `.shot.json` exports
use that same selected frame, and each catalog entry also writes a
`.metrics.json` sidecar with the selected frame and canonical metric names.
