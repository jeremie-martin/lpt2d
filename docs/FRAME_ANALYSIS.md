# Frame Analysis

Frame analysis is the numeric description of the final authored-camera image.
It is used by scripts, the Python API, and the GUI Stats panel to answer:

- Is the image too dark, too bright, clipped, or washed out?
- How much robust contrast and color does the final image have?
- How large and sharp is the visible disk produced by each authored point light?

The public API is `FrameAnalysis` in C++ and `rr.analysis` in Python.
`RenderResult.metrics` is the compact `ImageStats` value from
`RenderResult.analysis.image`.

## Image Contract

All metrics describe the rendered camera image after tone mapping and
post-processing. They do not describe HDR transport buffers, material state,
scene geometry, or the editor viewport.

Production analysis is GPU-first: the renderer analyzes the final RGB8 display
texture with compact GPU reductions and reads back summary data. The live and
scripted renderer contract does not rely on full-frame CPU readback analysis.

The GUI must preserve camera semantics:

- Stats values come from the authored camera, not from the visible viewport.
- If the viewport is zoomed, panned, resized, or cropped, the numbers must not
  change just because the viewport changed.
- The light overlay is only drawn when the visible viewport matches the authored
  camera closely enough for the camera-space measurements to line up visually.

## Units

All public image values are normalized and resolution independent unless the
field explicitly says it is a raw histogram count.

| Kind | Unit |
|---|---|
| Luma values | BT.709 luma on the final RGB8 image, normalized to `[0, 1]` |
| Saturation and colorfulness | Normalized to `[0, 1]` |
| Occupancy values | Fraction of the full image area in `[0, 1]` |
| Light radius and edge width | Fraction of `min(width, height)` |
| Light coverage | Fraction of the full image area |
| Light center | Image coordinates in the analyzed camera image |
| Histograms | Raw bin counts; use fractions for resolution-independent filters |

Example: `radius_ratio = 0.05` means the measured radius is 5% of the image
short side. It does not mean 5 pixels.

## Python Example

```python
from anim.renderer import render_frame

rr = render_frame(animate, timeline, settings=shot, analyze=True)
analysis = rr.analysis

print(analysis.image.mean_luma, analysis.image.interdecile_luma_range)
print(analysis.image.colorfulness, analysis.debug.colored_fraction)

for light in analysis.lights:
    print(light.id, light.radius_ratio, light.transition_width_ratio, light.confidence)
```

## ImageStats

`FrameAnalysis.image` is the compact set intended for normal scripts and
filters. The same value is exposed as `RenderResult.metrics`.

| Field | Meaning |
|---|---|
| `width`, `height` | Dimensions of the image actually analyzed |
| `mean_luma` | Average BT.709 luma |
| `median_luma` | 50th-percentile luma |
| `p05_luma`, `p95_luma` | 5th and 95th percentile luma |
| `near_black_fraction` | Fraction of pixels with luma `<= near_black_luma`; default `10/255` |
| `near_white_fraction` | Fraction of pixels with luma `>= near_white_luma`; default `245/255` |
| `clipped_channel_fraction` | Fraction of pixels where any RGB channel is exactly 255 |
| `rms_contrast` | Standard deviation of normalized luma |
| `interdecile_luma_range` | `p90_luma - p10_luma`; robust contrast spread |
| `interdecile_luma_contrast` | `(p90_luma - p10_luma) / (p90_luma + p10_luma + eps)` |
| `local_contrast` | Mean Sobel luma gradient on a coarse averaged grid, scaled by grid short side and clamped to `[0, 1]` |
| `mean_saturation` | Average HSV saturation over all pixels |
| `p95_saturation` | 95th-percentile HSV saturation |
| `colorfulness` | Normalized opponent-channel colorfulness |
| `bright_neutral_fraction` | Fraction of pixels that are bright and low-saturation |

Interpretation:

- `mean_luma` is the broad brightness estimate.
- `rms_contrast` captures global variation and is sensitive to large dark or
  bright regions.
- `interdecile_luma_range` is the preferred robust contrast spread for flat or
  washed-out image checks.
- `local_contrast` captures low-frequency spatial edge contrast, so it can
  distinguish a smooth gradient from a frame with similar global luma spread but
  sharper structure without treating per-pixel render noise as structure.
- `bright_neutral_fraction` is a direct washed-out signal: bright pixels with
  low saturation.
- `clipped_channel_fraction` is not the same as white-pixel fraction; it counts
  any pixel with at least one saturated RGB channel.

## ImageDebugStats

`FrameAnalysis.debug` carries expanded diagnostics. It is useful for tuning and
dashboards, but most filters should start with `ImageStats`.

| Field | Meaning |
|---|---|
| `p01_luma`, `p10_luma`, `p90_luma`, `p99_luma` | Additional luma percentiles |
| `luma_entropy` | Shannon entropy of the 256-bin luma histogram, in bits |
| `luma_entropy_normalized` | Luma entropy divided by 8 bits |
| `hue_entropy` | Shannon entropy of the 36-bin hue histogram |
| `colored_fraction` | Fraction of pixels with HSV saturation above `colored_saturation_threshold` |
| `mean_saturation_colored` | Mean saturation among pixels above `colored_saturation_threshold` |
| `saturation_coverage` | `mean_saturation_colored * colored_fraction` |
| `colorfulness_raw` | Unnormalized opponent-channel colorfulness |
| `luma_histogram` | 256-bin luma histogram |
| `saturation_histogram` | 256-bin HSV saturation histogram |
| `hue_histogram` | 36-bin hue histogram for chromatic pixels |

Scripts should prefer normalized summary fields over raw histogram counts unless
they intentionally need distribution-level diagnostics.

## Point-Light Appearance

`FrameAnalysis.lights` contains one `PointLightAppearance` per authored
`PointLight`. These values describe the visible light disk in the final image,
not the physical light object in isolation.

This sensitivity is intentional. Exposure, white point, contrast, gamma,
reflections, occlusion, bloom-like post-processing, nearby objects, and the
background can all change the apparent disk. The analysis reports the disk
visible in the current final frame.

| Field | Meaning |
|---|---|
| `id` | Authored point-light id |
| `world_x`, `world_y` | Light position in world coordinates |
| `image_x`, `image_y` | Projected light center in the analyzed camera image |
| `visible` | Whether a measurable light appearance was found |
| `radius_ratio` | Official apparent light-disk radius, normalized by image short side |
| `coverage_fraction` | Area of that disk as a fraction of the image |
| `saturated_radius_ratio` | Diagnostic radius of the saturated or near-saturated core |
| `transition_width_ratio` | Estimated edge or falloff width, normalized by image short side |
| `peak_luminance` | Brightest measured luma associated with the light |
| `background_luminance` | Estimated local background near the light |
| `peak_contrast` | `peak_luminance - background_luminance` |
| `touches_frame_edge` | Whether the estimated disk is truncated by the frame boundary |
| `confidence` | Heuristic confidence in `[0, 1]` |

`radius_ratio` is the main answer for "how big is the circle of light?" It
should be the value used by tooling, overlays, and automated filters.

The light-radius detector intentionally uses an internal grayscale radius signal
rather than raw RGB channels: BT.709 luma from the real final RGB8 camera image,
remapped with `lights.radius_signal_gamma` before radial profiles are measured.
This is equivalent to asking "what circle would be visible if this final image
were converted to luma and viewed with a low gamma", without changing the
rendered image, the public post-processing settings, or the whole-frame image
stats.

`saturated_radius_ratio` is only a diagnostic. It can be useful for debugging
clipping, but it is not the general apparent radius because many valid light
disks are soft, colored, or not fully saturated.

Low `confidence` means the radius should be treated cautiously. Common causes
include weak contrast, a very soft edge, contamination from nearby geometry,
occlusion, an off-frame light disk, or inconsistent evidence around the light.

## Parameters

`FrameAnalysisParams` controls which metric groups are computed and the few
thresholds that define public semantic boundaries.

| Field | Meaning |
|---|---|
| `analyze_image` | Populate `image` |
| `analyze_debug` | Populate `debug` |
| `analyze_lights` | Populate `lights` |
| `near_black_luma` | Inclusive near-black luma threshold; default `10/255` |
| `near_white_luma` | Inclusive near-white luma threshold; default `245/255` |
| `bright_luma_threshold` | Bright threshold for `bright_neutral_fraction`; default `0.75` |
| `neutral_saturation_threshold` | Low-saturation threshold for `bright_neutral_fraction`; default `0.10` |
| `colored_saturation_threshold` | Chroma threshold for hue/color debug stats; default `0.05` |
| `lights.search_radius_ratio` | Maximum search distance around each light, as a short-side fraction |
| `lights.radius_signal_gamma` | Gamma used only for the internal grayscale light-radius signal; default `0.5` |
| `lights.saturated_core_threshold` | Threshold for the diagnostic saturated-core radius |
| `lights.saturated_core_percentile` | Percentile used for the diagnostic saturated-core radius |
| `lights.min_saturated_core_pixels` | Minimum evidence for the diagnostic saturated core |

Most callers should not tune these values casually. The default parameters are
part of the meaning of the API, especially for scripts that compare results
across many scenes.

## Practical Use

- Use `image.mean_luma`, `image.p05_luma`, `image.p95_luma`,
  `image.rms_contrast`, `image.interdecile_luma_range`,
  `image.local_contrast`, `image.near_black_fraction`,
  `image.near_white_fraction`, and `image.clipped_channel_fraction` for
  exposure and contrast checks.
- Use `image.bright_neutral_fraction` for washed-out bright neutral areas.
- Use `image.mean_saturation`, `image.p95_saturation`, and
  `image.colorfulness` for color checks.
- Use `lights[*].radius_ratio` for the apparent size of point-light disks.
- Use `lights[*].transition_width_ratio` and `confidence` to decide whether a
  radius measurement is sharp and trustworthy.
- Avoid raw pixels for thresholds unless the operation is intentionally tied to
  a specific image resolution.
