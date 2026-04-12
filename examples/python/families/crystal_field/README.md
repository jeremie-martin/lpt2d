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
| `study.py` | Measured probe datasets and offline analysis |
| `GENERATION.md` | High-level algorithm and validation notes |

## How parameter generation works

`sample(rng)` builds a `Params` through a layered decision tree:

1. **Grid** — spacing is sampled in [0.20, 0.32] with a mild bias toward
   the low, packed end and drives the number of rows/columns that fit
   inside the mirror box.
2. **Shape** — active free-sampler scenes use rounded polygons with
   optional shared rotation and per-object jitter. Glass circle support is
   still present for targeted tools, but glass is temporarily excluded from
   the active free sampler. Sparse polygon grids gently bias the sampled
   size factor upward, keeping the same maximum size while avoiding tiny
   polygons in low-object-count diffuse scenes. Triangles remain possible,
   but are sampled less often than four-, five-, and six-sided polygons.
3. **Material** — one of four active peer outcomes is sampled with equal
   probability: black diffuse, gray diffuse, colored diffuse, or brushed
   metal.
4. **Light** — 1–3 moving lights at constant speed.  Speed decreases
   with more lights. When objects have no spectral color, warm range
   spectra (orange/deep-orange) are sampled often. Colored moving lights
   get one shared complementary ambient color with randomized hue jitter
   and white mix; per-light ambient variation is left for future
   exploration.

Moving and ambient intensities are sampled as white-equivalent values.
`scene.py` converts them to render-time point-light intensities through one
shared spectrum compensation helper. The sampler picks moving intensity
first, builds the ambient spectrum, then caps the ambient draw so its
rendered intensity cannot exceed the rendered moving-light intensity.

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

# Compare white ambient against complementary ambient
python -m examples.python.families.crystal_field ambient_compare --limit 4

# Measured free-sampler probe dataset, no final renders
python -m examples.python.families.crystal_field study measure \
  --out renders/families/crystal_field/studies/measured_noglass_1000_seed0.jsonl \
  --n 1000 --seed 0
python -m examples.python.families.crystal_field study analyze \
  --in renders/families/crystal_field/studies/measured_noglass_1000_seed0.jsonl \
  --out renders/families/crystal_field/studies/measured_noglass_1000_seed0_analysis

# Interrupt/resume-safe 50k task
bash examples/python/families/crystal_field/run_measured_study_50k.sh

# Interrupt/resume-safe 1M task
bash examples/python/families/crystal_field/run_measured_study_1m.sh
```

The analysis directory contains CSV tables plus a static `index.html`
dashboard. The dashboard reports group pass rates, first-failure reasons,
single-parameter quantile bins, conditional bins by categorical scenario, and
two-parameter interaction heatmaps such as exposure versus ambient intensity,
or ambient intensity versus probe metrics like ambient radius and mean
brightness. Probe metrics appear in the dashboard with a `metric_` prefix.
See `SAMPLER_TUNING_NOTES.md` for the first measured-study interpretation
and sampler-policy refactor notes.

## Key tunable ranges

| Parameter | Range | Notes |
|-----------|-------|-------|
| IOR | outcome-specific | Glass derives IOR from dispersion; brushed metal samples 1.0 or [1.0, 1.4] |
| Spacing | 0.20–0.32 | Controls object density; biased toward the low, packed end |
| Spacing pack bias | 1.4 | 1.0 is uniform; higher values prefer tighter spacing within the same range |
| Polygon size factor | 0.28–0.43 | Multiplied by spacing; sparse grids bias small draws upward within this range |
| Diffuse transmission | 0.00–0.05 | Gray and colored diffuse only |
| Diffuse absorption | 0.75–1.25 | Gray and colored diffuse only |
| Brushed-metal color saturation | 0.10–0.40 | HSV saturation for colored brushed-metal object slots |
| Speed | 0.08–0.20 u/s | Max is 0.20 for one light, 0.14 for multi-light |
| Ambient intensity | 0.25–1.0, capped by moving light | Per corner/side white-equivalent light; cap is applied after spectrum compensation |
| Ambient white mix | 0.35–0.85 | Only for complementary colored ambient |
| Moving intensity | 0.75–1.75 | White-equivalent per moving light; range/RGB spectra get render-time compensation |
| Exposure | -6.5 to -4.5 | Log scale brightness; warm ranges get small offsets |
| Gamma | 1.2 to 2.2 | Tonemap curve; warm ranges get small multipliers |
| Contrast | 1.00 to 1.10 | Subtle post-process contrast boost |
| White point | 0.4 to 0.6 | Tonemap shoulder / brightness control |
| Corner radius | 10–30% of size | Always applied to polygons |

## Rejection Criteria

Variants are rejected only by the current light-radius and luminance gates:

- Moving light radius: 1.0% to 4.2% of the short image side.
- Ambient light radius: 0.8% to 4.2% of the short image side.
- Mean moving radius divided by mean ambient radius: 1.33 to 2.33.
- Near-black fraction: below 3.5%.
- Brightness: 60 to 140 on the 0-255 luminance scale (glass max: 80).
- Shadow floor: at most 80 on the 0-255 luminance scale.
- Contrast spread: at least 50 on the 0-255 luminance scale.
- Shadow pixels: at most 20% (black diffuse max: 50%).
- Mean saturation: below 0.66.

`check.py` first selects the frame where moving lights are furthest from
object centres, then computes all gates from the core `FrameAnalysis`
binding for that frame.  Catalog PNGs and authored `.shot.json` exports
use that same selected frame, and each catalog entry also writes a
`.metrics.json` sidecar with the selected frame and canonical metric names.

Catalog search now separates structure from post-processing.  For each
structural scene candidate it traces the selected analysis frame once, then
replays up to 100 random post-processing looks over that retained frame.  If
none of those looks passes, only then does the catalog sample a new scene.
