# Frame Analysis

Frame analysis is the numeric description of the final camera image. It is the
data layer used by scripts, the Python API, and the GUI Stats panel to answer
questions such as:

- Is the image too dark, too bright, clipped, or washed out?
- How much contrast and color does the final image have?
- How large and sharp is the visible disk produced by each authored point light?

The public API is `FrameAnalysis` in C++ and `rr.analysis` in Python.

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

Frame analysis should be resolution independent wherever the value is meant to
be compared across images.

| Kind | Unit |
|---|---|
| Luminance values | BT.709 luminance on the final `0..255` RGB8 scale |
| Percentiles | Luminance bin values on the same `0..255` scale |
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

print(analysis.luminance.mean, analysis.luminance.contrast_spread)
print(analysis.color.richness, analysis.color.colored_fraction)

for light in analysis.lights:
    print(light.id, light.radius_ratio, light.transition_width_ratio, light.confidence)
```

## Luminance

`FrameAnalysis.luminance` describes whole-frame brightness, contrast, shadows,
highlights, and clipping in the final image.

| Field | Meaning |
|---|---|
| `width`, `height` | Dimensions of the image actually analyzed |
| `histogram` | 256-bin luminance histogram; counts sum to `width * height` |
| `mean` | Average brightness |
| `median` | 50th-percentile brightness |
| `shadow_floor` | 5th-percentile brightness |
| `highlight_ceiling` | 95th-percentile brightness |
| `highlight_peak` | 99th-percentile brightness |
| `contrast_std` | Standard deviation of luminance |
| `contrast_spread` | `highlight_ceiling - shadow_floor` |
| `near_black_fraction` | Fraction of the image at or below the near-black threshold |
| `near_white_fraction` | Fraction of the image at or above the near-white threshold |
| `clipped_channel_fraction` | Fraction of the image where any RGB channel is exactly 255 |

Interpretation:

- `mean` is the broad brightness estimate.
- `contrast_std` is sensitive to global variation across the frame.
- `contrast_spread` ignores extreme outliers and is useful for washed-out or
  flat-image checks.
- `shadow_floor` and `near_black_fraction` describe dark occupancy.
- `highlight_ceiling`, `highlight_peak`, `near_white_fraction`, and
  `clipped_channel_fraction` describe bright occupancy and saturation.
- `clipped_channel_fraction` is not the same as white-pixel fraction; it counts
  any pixel with at least one saturated RGB channel.

Scripts should prefer fractions and percentiles over raw histogram counts unless
they intentionally need resolution-dependent information.

## Color

`FrameAnalysis.color` summarizes chromatic content in the final image.

| Field | Meaning |
|---|---|
| `mean_saturation` | Average HSV saturation of pixels above the chroma threshold |
| `hue_entropy` | Shannon entropy of the hue histogram |
| `colored_fraction` | Fraction of the image considered chromatic |
| `richness` | Combined colorfulness score: entropy, saturation, and area |
| `n_colored` | Raw count of chromatic pixels |
| `hue_histogram` | 36-bin hue histogram |

`richness` is a compact "does this frame contain meaningful color variety?"
score. Use the component fields when a decision needs to distinguish "small but
very saturated" from "large but mildly colored".

## Point-Light Appearance

`FrameAnalysis.lights` contains one `PointLightAppearance` per authored
`PointLight`. These values describe the visible light disk in the final image,
not the physical light object in isolation.

This sensitivity is intentional. Exposure, white point, contrast, gamma,
reflections, occlusion, bloom-like post-processing, nearby objects, and the
background can all change the apparent disk. The analysis should report the
disk visible in the current final frame.

| Field | Meaning |
|---|---|
| `id` | Authored point-light id |
| `world_x`, `world_y` | Light position in world coordinates |
| `image_x`, `image_y` | Projected light center in the analyzed camera image |
| `visible` | Whether a measurable light appearance was found |
| `radius_ratio` | Official apparent light-disk radius, normalized by image short side |
| `radius_candidate_sector_consensus_ratio` | Temporary comparison candidate: radius with strongest angular-sector edge agreement |
| `coverage_fraction` | Area of that disk as a fraction of the image |
| `transition_width_ratio` | Estimated edge or falloff width, normalized by image short side |
| `saturated_radius_ratio` | Diagnostic radius of the saturated or near-saturated core |
| `peak_luminance` | Brightest measured luminance associated with the light |
| `background_luminance` | Estimated local background near the light |
| `peak_contrast` | `peak_luminance - background_luminance` |
| `touches_frame_edge` | Whether the estimated disk is truncated by the frame boundary |
| `confidence` | Heuristic confidence in `[0, 1]` |

`radius_ratio` is the main answer for "how big is the circle of light?" It
should be the value used by tooling, overlays, and automated filters.

`radius_candidate_sector_consensus_ratio` is the only remaining comparison
candidate. It is exported so the GPU analyzer, C++ API, Python bindings, GUI,
and characterization gallery can compare the official radius with the strongest
alternate result from the same final camera image. It is not intended to become
permanent API surface.

The light-radius characterization gallery includes stability sweeps for gamma,
ray count, and resolution. These are meant to catch detector drift caused by
post-processing, stochastic noise, or image-size changes. All radius values in
those tables are normalized by the image short side, so resolution changes
should ideally produce very small drift for the same apparent image.

The light-radius detector intentionally uses an internal grayscale radius signal
rather than raw RGB channels: BT.709 luminance from the real final RGB8 camera
image, remapped with `lights.radius_signal_gamma` before radial profiles are
measured. This is equivalent to asking "what circle would be visible if this
final image were converted to luminance and viewed with a low gamma", without
changing the rendered image, the public post-processing settings, or the
whole-frame luminance/color metrics.

The official radius and sector-consensus candidate subtract a local background
estimate in the same low-gamma radius-signal space before looking for the
apparent light-disk boundary. Older profile-knee, robust-sector-edge, and
outer-shoulder detector experiments were pruned from active code after the
low-gamma luminance characterization pass; see `docs/LIGHT_RADIUS_DETECTOR_HISTORY.md`.

`saturated_radius_ratio` is only a diagnostic. It can be useful for debugging
clipping, but it is not the general apparent radius because many valid light
disks are soft, colored, or not fully saturated.

`transition_width_ratio` describes edge sharpness. Lower values mean a crisper
boundary; higher values mean a soft halo or gradual falloff.

Low `confidence` means the radius should be treated cautiously. Common causes
include weak contrast, a very soft edge, contamination from nearby geometry,
occlusion, an off-frame light disk, or inconsistent evidence around the light.

## Parameters

`FrameAnalysisParams` controls which metric groups are computed and the few
thresholds that define public semantic boundaries.

| Field | Meaning |
|---|---|
| `analyze_luminance` | Populate `luminance` |
| `analyze_color` | Populate `color` |
| `analyze_lights` | Populate `lights` |
| `near_black_bin_max` | Upper luminance bin counted as near black |
| `near_white_bin_min` | Lower luminance bin counted as near white |
| `saturation_threshold` | Chroma threshold used by color analysis |
| `lights.search_radius_ratio` | Maximum search distance around each light, as a short-side fraction |
| `lights.radius_signal_gamma` | Gamma used only for the internal grayscale light-radius signal; default `0.5` |
| `lights.saturated_core_threshold` | Threshold for the diagnostic saturated-core radius |
| `lights.saturated_core_percentile` | Percentile used for the diagnostic saturated-core radius |
| `lights.min_saturated_core_pixels` | Minimum evidence for the diagnostic saturated core |

Most callers should not tune these values casually. The default parameters are
part of the meaning of the API, especially for scripts that compare results
across many scenes.

## Practical Use

- Use `luminance.mean`, `contrast_std`, `contrast_spread`, shadows, highlights,
  peak, near-black, near-white, and clipped-channel fractions for exposure and
  washed-out checks.
- Use `color.richness` and its component fields for colorfulness checks.
- Use `lights[*].radius_ratio` for the apparent size of point-light disks.
- Use `lights[*].transition_width_ratio` and `confidence` to decide whether a
  radius measurement is sharp and trustworthy.
- Avoid raw pixels for thresholds unless the operation is intentionally tied to
  a specific image resolution.
