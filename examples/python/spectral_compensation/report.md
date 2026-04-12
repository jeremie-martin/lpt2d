# Spectral Compensation Study

## Question

For crystal-field scenes with warm narrow-band moving lights, can we choose a
small fixed post-process correction from the light color alone?

The target is simple:

- preserve final-frame brightness relative to the white-light version;
- preserve apparent moving-light circle size relative to the white-light
  version;
- do this without knowing the scene geometry, material, grid size, or number of
  lights.

The model is intentionally only two numbers per light band:

```python
exposure += exposure_delta
gamma *= gamma_multiplier
```

## Metrics

The study uses renderer-facing appearance metrics, not raw radiometric energy.

- Brightness: `FrameAnalysis.luminance.mean`, final RGB8 BT.709 mean luminance.
- Circle size: mean `FrameAnalysis.lights[*].radius_ratio` over moving lights.
- Error: ratios are always measured against the same scene rendered with white
  moving light.

This matters because the radius detector operates on the final displayed image.
Exposure and gamma can therefore change the measured apparent radius, even
though gamma is "just" a post-process transform.

## Data

Input shots:

```text
renders/lpt2d_crystal_field_catalog_replay_20260411/**/white*.shot.json
```

Coverage:

- 30 catalog shots;
- 5 material groups: glass, gray_diffuse, black_diffuse, brushed_metal,
  colored_diffuse;
- 3 grid sizes: small, medium, large;
- 1-light and 2-light variants.

The current result file is:

```text
renders/brightness_experiment_shots/fixed_compensation_study.json
```

This is a calibration result on the 30-shot catalog, not an independent
holdout validation.

## Method

The source-of-truth script is:

```bash
python examples/python/spectral_compensation/fixed_compensation_study.py
```

For each warm band and scene it does this:

1. Render the white baseline.
2. Render the same shot with only the moving light recolored to the warm band
   and luminance-boosted.
3. Sweep exposure using `RenderSession.postprocess()` and find the per-scene
   exposure offset that best matches the white moving-light radius.
4. At the median exposure offset, find each scene's gamma multiplier needed to
   match white brightness.
5. Run a small direct grid around those median exposure/gamma centers.
6. Choose the fixed pair that minimizes:

```text
p90(abs(log(brightness_ratio)) + abs(log(radius_ratio)))
  + 0.25 * mean(abs(log(brightness_ratio)) + abs(log(radius_ratio)))
```

The direct grid is important. Earlier relationship fits assumed that gamma did
not affect radius. That is approximately true in many scenes, but it is false
for some large/high-fill scenes where the radius detector changes component.

## Stage 1: Spectral Boost

Before exposure/gamma compensation, the moving light intensity is scaled by
the mean renderer luminance of the spectral band:

```python
boost = white_mean_luminance / band_mean_luminance
```

This uses `_lpt2d.wavelength_to_rgb()` and BT.709 weights
`0.2126, 0.7152, 0.0722`.

Result after boost, before exposure/gamma correction:

| Band | Boost | Brightness mean | Mean abs brightness error | P90 abs brightness error |
|---|---:|---:|---:|---:|
| orange 550-700nm | 0.787 | 1.003x | 1.4% | 3.4% |
| deep orange 570-700nm | 1.052 | 0.995x | 2.3% | 5.9% |

Conclusion: the luminance boost is doing the right job for brightness.

## Color Impact On Radius

After brightness is matched by spectral boost, warm bands still shrink the
measured moving-light radius.

| Band | Radius mean | Radius median | Mean abs radius error | P90 abs radius error | Max abs radius error |
|---|---:|---:|---:|---:|---:|
| orange 550-700nm | 0.736x | 0.763x | 26.4% | 44.0% | 80.9% |
| deep orange 570-700nm | 0.464x | 0.475x | 53.6% | 68.5% | 88.5% |

This is the real compensation problem. Brightness is mostly solved by boost;
radius is not.

## Per-Scene Upper Bound

If scene-specific tuning were allowed, the script can usually match both
targets well. This is not the final model, but it tells us whether the controls
have enough range.

| Band | Median scene exposure delta | Median scene gamma multiplier | Mean abs final brightness error | Mean abs final radius error | P90 abs final radius error |
|---|---:|---:|---:|---:|---:|
| orange | +0.250 | 0.825 | ~0.0% | 6.0% | 10.7% |
| deep orange | +0.775 | 0.531 | 1.7% | 5.0% | 6.5% |

The large max outliers remain important:

- orange max radius error: 70.7%;
- deep orange max brightness error: 42.1%;
- deep orange max radius error: 70.7%.

Those are not formula noise; they indicate scenes where the detector/control
response is discontinuous or the required gamma falls near the search floor.

## Fixed Corrections

The calibrated fixed corrections from the direct joint grid are:

```python
ORANGE_EXPOSURE_DELTA = 0.200
ORANGE_GAMMA_MULTIPLIER = 0.829

DEEP_ORANGE_EXPOSURE_DELTA = 0.725
DEEP_ORANGE_GAMMA_MULTIPLIER = 0.450
```

Result across the 30-shot calibration catalog:

| Band | Fixed correction | Mean abs brightness error | P90 abs brightness error | Max abs brightness error | Mean abs radius error | P90 abs radius error | Max abs radius error |
|---|---|---:|---:|---:|---:|---:|---:|
| orange | `+0.200`, `gamma * 0.829` | 4.0% | 8.0% | 12.8% | 12.3% | 22.0% | 75.8% |
| deep orange | `+0.725`, `gamma * 0.450` | 12.5% | 24.7% | 37.0% | 20.9% | 39.5% | 80.3% |

Interpretation:

- Orange has a useful fixed correction. It is not perfect, but it improves the
  radius error substantially while keeping brightness reasonably close.
- Deep orange is much less universal. A fixed correction improves radius a lot
  compared with no correction, but the brightness/radius tradeoff remains
  scene-dependent.

## Worst Cases

The hardest repeated outlier is:

```text
colored_diffuse/white_large_2light
```

For orange:

- base radius ratio: 0.191x;
- fixed-corrected radius ratio: 0.242x;
- fixed-corrected brightness ratio: 0.887x.

For deep orange:

- base radius ratio: 0.115x;
- fixed-corrected radius ratio: 0.197x;
- fixed-corrected brightness ratio: 0.630x.

This scene cannot be treated as a small perturbation around the average model.
It should be tracked separately when deciding whether the fixed compensation is
acceptable for production sampling.

## What The Older Scripts Mean Now

- `color_impact_study.py` measures the uncorrected warm-band brightness/radius
  impact after spectral boost.
- `relationship_study.py` is a diagnostic response sweep. It is useful for
  understanding trends, but its global power-law constants should not be used
  as the final source of truth.
- `circle_brightness_matching.py` demonstrates per-scene search. It proves a
  scene-specific correction can often be found, but it does not validate a
  scene-independent formula by itself.
- `fixed_compensation_study.py` directly answers the current question and is
  the script to rerun when changing the renderer, analyzer, catalog, or bands.
- `render_hq_variants.py` produces visual comparisons.

## Practical Conclusion

Use a fixed correction only as a calibrated heuristic:

```python
if band == "orange":
    exposure += 0.200
    gamma *= 0.829
elif band == "deep_orange":
    exposure += 0.725
    gamma *= 0.450
```

These values are better supported than the earlier formula-derived constants,
because they are selected against the actual fixed-color-only objective. They
are still not universal physical laws. The correct confidence statement is:

- brightness boost is reliable;
- orange fixed compensation is reasonably good on the current catalog;
- deep-orange fixed compensation is a rough compromise;
- hard outliers remain and should be measured, not hidden.

The next clean improvement would be to rerun the same script on a fresh
independent catalog and compare the fixed-error summaries.
