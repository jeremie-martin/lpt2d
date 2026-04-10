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
| `check.py` | Quality gates (color richness + point-light appearance metrics) |
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
   (orange/yellow spectral range).  Ambient lights at corners are the
   default (70%).

## Commands

```bash
# Standard Family commands
python -m examples.python.families.crystal_field search -n 4
python -m examples.python.families.crystal_field survey -n 16
python -m examples.python.families.crystal_field render path/to/params.json

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

## Quality checks

Variants must pass two gates:

1. **Color richness** — at least 2.5 seconds of the 10s animation must
   have richness > 0.15 (measured via probe rendering at 4 fps).
2. **Point-light appearance** — the apparent size and edge quality of each
   moving light is measured on the final image in normalized camera units:
   - Moving radius: 0.8%–22.2% of the short image side
   - Edge width: ≤ 3.3% of the short image side
   - Peak contrast: ≥ 0.08
   - Confidence: ≥ 0.35
   - Moving/ambient size ratio: ≤ 2.66:1
