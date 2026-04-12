# Spectral Compensation: Matching Brightness and Circle Size Across Light Colors

## Scope

When a crystal-field scene uses a narrow-band spectral light (e.g. orange
550-700nm) instead of full-spectrum white (380-780nm), two things change:

1. **Brightness** — fewer wavelengths means less total energy, so the scene
   gets dimmer unless we compensate.
2. **Circle size** — narrow-band light produces more coherent caustics,
   changing the apparent size of the light circle in the render.

This study characterizes how the renderer's post-process controls (exposure,
gamma) affect brightness and circle size, and derives correction formulas
that match both to the white baseline.

## Three-stage compensation

### Stage 1: Luminance-weighted intensity boost

The `spectral_boost()` function in `scene.py` integrates the CIE 1931
luminance curve over the spectral band and scales the light's intensity so
that the perceived energy matches full-spectrum white.

```
boost = white_mean_luminance / band_mean_luminance
```

This uses the actual `wavelength_to_rgb()` from the C++ spectrum module (now
exposed to Python) with Rec.709 luminance weights (0.2126, 0.7152, 0.0722).

**Result** (measured across 30 catalog shots, 5 material types):

| Band | Boost | Brightness vs white |
|------|-------|-------------------|
| orange 550-700nm | 0.787 | 100.3% mean, 2.6% stdev |
| deep orange 570-700nm | 1.052 | 99.5% mean, 3.3% stdev |

Brightness is matched within 3%. The old formula (`400/width`) was 35-79%
too bright for these bands.

### Color impact on circle size (after stage 1)

After the luminance boost matches brightness, the circle radius is
consistently smaller than white. Measured across all 30 catalog shots:

| Band | R (radius ratio) | Stdev | Range |
|------|-----------------|-------|-------|
| orange 550-700nm | 0.736 | 0.154 | 0.19 - 1.00 |
| deep orange 570-700nm | 0.464 | 0.125 | 0.11 - 0.72 |

Per-material breakdown:

| Material | Orange R | Deep orange R |
|----------|---------|--------------|
| glass | 0.817 ± 0.043 | 0.544 ± 0.042 |
| brushed_metal | 0.745 ± 0.099 | 0.467 ± 0.069 |
| colored_diffuse | 0.766 ± 0.290 | 0.510 ± 0.206 |
| black_diffuse | 0.685 ± 0.145 | 0.426 ± 0.118 |
| gray_diffuse | 0.667 ± 0.058 | 0.372 ± 0.073 |

Glass has the most stable circle sizes (lowest stdev). Gray diffuse shows
the most shrinkage. Colored diffuse has the highest variance due to
material-color/light-color interaction.

The narrower the band, the smaller the circle: the light refracts more
coherently, concentrating the caustic pattern rather than smearing it
across wavelengths.

### Stage 2: Exposure correction for circle size

Increasing exposure grows the visible circle because more of the light's
spatial falloff exceeds the detection threshold. This can restore the
circle size to match the white baseline.

### Stage 3: Gamma correction for brightness

Exposure changes brightness as a side effect. Gamma adjusts brightness
without affecting circle size, so it can undo the brightness shift from
stage 2.

## Measured relationships

All relationships were measured across 30 crystal-field catalog shots
spanning 5 material types (glass, gray_diffuse, black_diffuse,
brushed_metal, colored_diffuse) and 3 grid sizes (small, medium, large),
with both 1-light and 2-light variants.

### Exposure to brightness

```
brightness_ratio = 1.624 ^ delta_exposure
```

- R-squared: 0.997
- Mean prediction error: 1.7%
- Per-scene coefficient of variation: 11.1%

A +1.0 exposure step multiplies brightness by ~1.62x. The relationship is
exponential (linear in log space) and highly consistent across scenes.

### Exposure to circle radius

```
radius_ratio = 3.353 ^ delta_exposure
```

- R-squared: 0.976
- Mean prediction error: 15.3%
- Per-scene coefficient of variation: 18.0%

A +1.0 exposure step multiplies the circle radius by ~3.35x. More variance
than the brightness relationship because circle detection is noisier,
especially at high exposure where circles saturate.

### Gamma to brightness

```
brightness_ratio = gamma_multiplier ^ 0.832
```

- R-squared: 0.979
- Mean prediction error: 3.7%
- Per-scene coefficient of variation: 15.1%

Multiplying gamma by 1.5x increases brightness by 1.5^0.832 = 1.39x. The
relationship follows a power law.

### Gamma to circle size

Gamma does not affect circle size. Across all 30 scenes and 12 gamma
values, the moving-light radius ratio stays at 1.00 (stdev < 0.01 for
gamma multipliers below 1.0). This is expected: gamma is a post-tonemap
pixel-value transform that redistributes brightness without changing where
light falls spatially.

## Correction recipe

Given:
- R = circle radius ratio (orange / white), measured after stage 1
- B = brightness ratio (orange / white), measured after stage 1

Step 1: compute exposure offset to restore circle size:

```
delta_exposure = ln(1/R) / ln(3.353) = ln(1/R) / 1.210
```

Step 2: predict brightness change from that exposure shift:

```
brightness_after_exposure = B * 1.624 ^ delta_exposure
```

Step 3: compute gamma multiplier to restore brightness:

```
gamma_multiplier = (1 / brightness_after_exposure) ^ (1 / 0.832)
```

### Worked examples

| Band | R | delta_exp | gamma_mult | Predicted brightness | Predicted radius |
|------|---|-----------|------------|---------------------|-----------------|
| orange 550-700 | 0.75 | +0.24 | 0.871 | 1.000 | 1.000 |
| deep orange 570-700 | 0.50 | +0.57 | 0.716 | 1.000 | 1.000 |

### Validation (binary-search ground truth)

The recipe was validated against brute-force binary search across 10 scenes
and 2 bands (20 combinations). The search independently found the optimal
exposure and gamma by rendering at each candidate and measuring:

| Metric | Mean error | Max error |
|--------|-----------|-----------|
| Brightness | 2.5% | 50.7%* |
| Circle radius | 2.3% | 23.3% |

*The 50.7% outlier occurred when the required gamma fell below 0.4 (the
search floor). Excluding that case, mean brightness error is 0.0%.

## Constants

The three constants that define the compensation model:

```python
EXPOSURE_BRIGHTNESS_BASE = 1.624   # brightness_ratio = base ^ delta_exp
EXPOSURE_RADIUS_BASE     = 3.353   # radius_ratio = base ^ delta_exp
GAMMA_BRIGHTNESS_EXP     = 0.832   # brightness_ratio = gamma_mult ^ exp
```

## Limitations

- The exposure-to-radius relationship has 18% per-scene CV. Scenes with
  very small or very large circles deviate more from the mean model.
- At high exposure offsets (above +1.0), circles can saturate and the
  detector loses accuracy.
- The gamma floor at ~0.4 limits correction for deep orange where gamma
  needs to drop substantially (from e.g. 1.17 to 0.40).
- Colored-diffuse materials show slightly higher variance because the
  material's spectral color interacts with the light's spectrum.

## Scripts

- `color_impact_study.py` — measures brightness and circle radius for orange
  and deep orange (with luminance boost) across all 30 catalog shots.
  Produces the R and B values that feed into the correction recipe.
- `relationship_study.py` — sweeps exposure and gamma across all 30 catalog
  shots, fits the three power-law models, reports per-scene consistency.
- `circle_brightness_matching.py` — validates the recipe by binary-searching
  for the optimal exposure+gamma pair per scene/band.
- `render_hq_variants.py` — renders HQ comparison images (white, orange,
  deep orange) with shot JSONs saved alongside.

Run from the repo root:

```bash
python examples/python/spectral_compensation/color_impact_study.py
python examples/python/spectral_compensation/relationship_study.py
python examples/python/spectral_compensation/circle_brightness_matching.py
python examples/python/spectral_compensation/render_hq_variants.py
```

Results are written to `renders/brightness_experiment_shots/`.
