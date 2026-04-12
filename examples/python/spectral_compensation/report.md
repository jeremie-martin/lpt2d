# Spectral Compensation Study

## Question

Can we choose a small fixed post-process correction from the moving-light color
alone?

The model is intentionally simple:

```python
exposure += exposure_delta
gamma *= gamma_multiplier
```

The model may know only the moving-light spectral band. It may not know scene
geometry, material, grid size, light count, light intensity, or final image
content.

The target is to preserve both:

- final-frame brightness relative to the same scene rendered with a white
  moving light;
- apparent moving-light circle size relative to that white-light version.

## Main Result

The final calibration dataset is the augmented clean existing-catalog dataset:

```text
renders/brightness_experiment_shots/fixed_compensation_existing_catalog_intensity.json
```

It contains 404 clean non-glass scene/intensity cases from 94 distinct source
shot JSONs. The moving-light intensity multipliers are:

```text
0.8, 0.9, 1.0, 1.1, 1.2
```

The fitted fixed corrections are:

```python
ORANGE_EXPOSURE_DELTA = 0.240
ORANGE_GAMMA_MULTIPLIER = 0.850

DEEP_ORANGE_EXPOSURE_DELTA = 0.710
DEEP_ORANGE_GAMMA_MULTIPLIER = 0.700
```

Interpretation:

- Orange is usable as a fixed heuristic for most clean non-glass cases. It keeps
  brightness tight and improves radius substantially, but there are still
  detector discontinuity outliers.
- Deep orange is not solved by one fixed exposure/gamma pair. The bounded
  `gamma * 0.700` result is a diagnostic compromise, not a production-quality
  universal correction.
- Do not use the old deep-orange value `+0.725`, `gamma * 0.450`. That value
  came from allowing visually destructive low gamma to hide the brightness
  side-effect of a large exposure boost.

## Final Fixed Results

| Band | Fixed correction | Mean abs brightness error | P90 abs brightness error | Max abs brightness error | Mean abs radius error | P90 abs radius error | Max abs radius error |
|---|---|---:|---:|---:|---:|---:|---:|
| orange | `+0.240`, `gamma * 0.850` | 3.7% | 7.9% | 17.7% | 12.0% | 22.1% | 566.1% |
| deep orange | `+0.710`, `gamma * 0.700` | 16.8% | 30.5% | 50.1% | 22.4% | 45.0% | 459.6% |

The very large max radius errors are real measured outliers, not averages. They
come from cases where the radius detector changes component or responds
discontinuously. For decision-making, the p90 values are the better summary of
typical behavior; the max values are still important because they show that the
fixed model is not universally safe.

## Why Deep Orange Fails

The spectral boost keeps first-order brightness fairly close before any
exposure/gamma correction. The hard part is circle size.

Deep orange strongly shrinks the detected moving-light radius. Recovering that
radius requires a large exposure increase, and that exposure increase raises
brightness. The optimizer then wants a low gamma multiplier to pull brightness
back down.

On the 404-case augmented dataset:

| Band | Median gamma needed at fixed exposure | Min | Max |
|---|---:|---:|---:|
| orange | 0.811 | 0.563 | 0.923 |
| deep orange | 0.480 | 0.250 | 0.737 |

Deep orange often wants gamma below the fixed selection floor. The diagnostic
search hit the `0.250` lower bound in 24 of 404 fixed-exposure cases and 34 of
404 per-scene optima. That is the core conflict: the simple model needs a tone
curve that we do not want to apply visually.

## Metrics

The study uses renderer-facing appearance metrics, not raw radiometric energy.

- Brightness: `FrameAnalysis.image.mean_luma`, final RGB8 BT.709 mean luma.
- Circle size: mean `FrameAnalysis.lights[*].radius_ratio` over moving lights.
- Error: each warm-band render is compared with the same shot rendered with a
  white moving light at the same moving-light intensity multiplier.

Ratios are multiplicative. A brightness ratio of `1.10` means 10% brighter than
the white-light reference; a radius ratio of `0.80` means 20% smaller.

## Clean Data Rule

Glass is excluded by default. It is a different optical problem because
refraction/caustics make the apparent radius and brightness response much less
comparable to diffuse/metal cases. It can still be included explicitly with
`--include-glass`.

White baselines are kept only if they pass:

| Filter | Value |
|---|---:|
| Mean brightness | `60 <= mean <= 140` |
| Mean saturation | `<= 0.66` |
| Shadow fraction | `<= 0.20` |
| Moving radius | `>= 0.010` |

These filters are applied to every source shot and intensity multiplier before
the warm-band compensation analysis.

## Dataset

The existing `renders/lpt2d_crystal_field_catalog_*` roots contain 372 white
shot files. After exact JSON de-duplication, that is 163 distinct white shots,
including glass. Excluding glass leaves 121 non-glass source shots.

With five moving-light intensity multipliers, the study checks 815 total cases:

| Quantity | Count |
|---|---:|
| Input white shot files | 372 |
| Exact-unique source shots | 163 |
| Unique non-glass source shots | 121 |
| Candidate source/intensity cases | 815 |
| Excluded glass cases | 210 |
| Clean accepted source/intensity cases | 404 |
| Distinct source shots represented after filtering | 94 |

Rejected non-glass candidate cases:

| Reason | Count |
|---|---:|
| Shadow fraction above 0.20 | 88 |
| Mean brightness above 140 | 85 |
| Mean saturation above 0.66 | 40 |
| Moving radius below 0.010 | 37 |
| Mean brightness below 60 | 20 |

Accepted case distribution:

| Group | Count |
|---|---:|
| black diffuse | 98 |
| brushed metal | 120 |
| colored diffuse | 90 |
| gray diffuse | 96 |
| intensity 0.8 | 77 |
| intensity 0.9 | 85 |
| intensity 1.0 | 85 |
| intensity 1.1 | 78 |
| intensity 1.2 | 79 |

Accepted white-baseline ranges:

| Metric | Min | Median | Max |
|---|---:|---:|---:|
| Mean brightness | 72.485 | 114.979 | 139.926 |
| Mean saturation | 0.075 | 0.119 | 0.636 |
| Shadow fraction | 0.000 | 0.047 | 0.200 |
| Moving radius | 0.010 | 0.018 | 0.185 |

## Method

Run:

```bash
python examples/python/spectral_compensation/fixed_compensation_study.py \
  --shot-root-glob 'renders/lpt2d_crystal_field_catalog_*' \
  --moving-intensity-multipliers 0.8,0.9,1.0,1.1,1.2 \
  --out renders/brightness_experiment_shots/fixed_compensation_existing_catalog_intensity.json
```

Important defaults:

- glass excluded;
- exact duplicate shot JSONs removed;
- clean white-baseline filters enabled;
- fixed correction cannot select `gamma_multiplier < 0.70`;
- diagnostic per-case searches may still go below `0.70`, so the report can
  show when the desired simple model is incompatible with the data.

For each warm band and clean scene/intensity case:

1. Load the source shot and apply the moving-light intensity multiplier.
2. Render the white baseline and measure brightness/radius.
3. Render the same case with only the moving light recolored to the warm band
   and luminance-boosted.
4. Sweep exposure with `RenderSession.postprocess()` to find the per-case
   exposure offset that best restores the white moving-light radius.
5. At the median exposure offset, find each case's gamma multiplier needed to
   match white brightness.
6. Run a small direct fixed grid around those median exposure/gamma centers.
7. Choose the fixed pair that minimizes:

```text
p90(abs(log(brightness_ratio)) + abs(log(radius_ratio)))
  + 0.25 * mean(abs(log(brightness_ratio)) + abs(log(radius_ratio)))
```

The direct grid is important. Gamma is not fully neutral for radius because the
radius detector observes the final displayed image.

## Group Characterization

Mean absolute fixed-correction errors on the 404-case augmented dataset:

| Band | Group | Brightness error | Radius error |
|---|---|---:|---:|
| orange | black diffuse | 2.2% | 14.3% |
| orange | brushed metal | 3.0% | 9.0% |
| orange | colored diffuse | 6.4% | 13.9% |
| orange | gray diffuse | 3.5% | 11.8% |
| deep orange | black diffuse | 17.0% | 15.7% |
| deep orange | brushed metal | 16.2% | 24.0% |
| deep orange | colored diffuse | 14.5% | 25.7% |
| deep orange | gray diffuse | 19.2% | 23.9% |

By intensity multiplier:

| Band | Intensity | Brightness error | Radius error |
|---|---:|---:|---:|
| orange | 0.8 | 3.6% | 6.6% |
| orange | 0.9 | 3.6% | 15.3% |
| orange | 1.0 | 3.6% | 11.3% |
| orange | 1.1 | 3.7% | 12.5% |
| orange | 1.2 | 3.8% | 14.0% |
| deep orange | 0.8 | 18.1% | 14.4% |
| deep orange | 0.9 | 17.2% | 19.1% |
| deep orange | 1.0 | 16.5% | 20.4% |
| deep orange | 1.1 | 16.3% | 27.9% |
| deep orange | 1.2 | 15.8% | 30.3% |

The intensity sweep is useful: it shows that the compensation error is not
constant across light intensity even within the same source scene. Higher
intensity tends to make deep-orange radius error worse.

## Outliers

Worst orange radius outlier:

```text
lpt2d_crystal_field_catalog_replay_20260411/black_diffuse/white_large_1light@I0.9
fixed radius ratio = 6.661
fixed brightness ratio = 0.999
white moving radius = 0.0272
```

Worst deep-orange radius outlier:

```text
lpt2d_crystal_field_catalog_replay_20260411/brushed_metal/white_medium_1light@I1.1
fixed radius ratio = 5.596
fixed brightness ratio = 1.111
white moving radius = 0.0263
```

Worst deep-orange brightness outlier:

```text
lpt2d_crystal_field_catalog_feedback_20260411/brushed_metal/white_small_1light@I0.8
fixed brightness ratio = 1.501
fixed radius ratio = 0.915
fixed gamma needed at median exposure = 0.250
```

These are mostly detector/control edge cases, not average behavior. They are a
sign that the radius measurement itself may need a confidence gate or a
component-stability check before the fixed constants are promoted.

## Cross-Checks

Earlier runs are still useful as cross-checks, but they are no longer the main
calibration source.

The generated 48-shot clean non-glass dataset selected:

| Band | Fixed correction | Mean abs brightness error | P90 abs brightness error | Mean abs radius error | P90 abs radius error |
|---|---|---:|---:|---:|---:|
| orange | `+0.250`, `gamma * 0.817` | 4.7% | 8.4% | 8.1% | 17.2% |
| deep orange | `+0.675`, `gamma * 0.700` | 17.9% | 30.1% | 18.9% | 45.3% |

The original 30-shot replay catalog, after excluding glass and applying the
clean filters, left 22 scenes and selected:

| Band | Fixed correction | Mean abs brightness error | P90 abs brightness error | Mean abs radius error | P90 abs radius error |
|---|---|---:|---:|---:|---:|
| orange | `+0.295`, `gamma * 0.697` | 9.8% | 15.5% | 11.5% | 28.9% |
| deep orange | `+0.725`, `gamma * 0.550` | 8.9% | 20.5% | 22.7% | 41.3% |

The larger augmented run is more representative because it samples multiple
operating intensities and uses more existing source scenes.

## Practical Guidance

Use the orange correction only as a calibrated heuristic:

```python
if band == "orange":
    exposure += 0.240
    gamma *= 0.850
```

Do not apply a fixed deep-orange correction as if it solves the problem. If a
bounded fallback is still needed, this is the current measured compromise:

```python
if band == "deep_orange":
    exposure += 0.710
    gamma *= 0.700
```

but it should be documented as visibly imperfect. The expected residual error
is large, and the p90 errors remain around 30% for brightness and 45% for
radius.

The honest conclusion is:

- spectral boost solves most of the first-order brightness issue;
- orange fixed compensation is useful for typical clean non-glass cases;
- deep-orange fixed compensation is not robust under the simple two-number
  model;
- a better deep-orange result likely needs either a scene-dependent measurement
  step, a different color band, or a different compensation model.

## Older Scripts

- `color_impact_study.py` measures the uncorrected warm-band brightness/radius
  impact after spectral boost.
- `relationship_study.py` is a diagnostic response sweep. Its global power-law
  constants should not be used as the final source of truth.
- `circle_brightness_matching.py` demonstrates per-scene search. It proves a
  scene-specific correction can often be found, but it does not validate a
  scene-independent formula by itself.
- `fixed_compensation_study.py` is the source-of-truth fixed-pair calibration.
- `build_clean_dataset.py` generates clean non-glass calibration shots with
  varied scene parameters and strict baseline filters.
- `render_hq_variants.py` produces visual comparisons.

## Next Improvement

The next useful work is validation and outlier handling, not a more complicated
global formula:

- validate by held-out source shot, not by random intensity case;
- regenerate independent clean generated datasets with different seeds;
- report constants and error summaries per dataset;
- add a radius-detector confidence or component-stability gate;
- only promote a constant if p90 errors and worst-case behavior are stable.

If repeated runs keep showing the same deep-orange failure, the result is clear:
deep orange needs a scene-dependent calibration step or a different
compensation model.
