# Frame Analysis

Frame analysis is the numeric summary of the final rendered image. It exists to
answer three questions about a frame without eyeballing the pixels:

1. How bright is it?
2. How colorful is it?
3. What visible bright structure does each authored `PointLight` produce?

The public API is `rr.analysis` in Python and `FrameAnalysis` in C++.

## Image Semantics

All metrics are measured on the final post-tonemap RGB8 image, not on HDR
buffers.

- Luminance values use BT.709 on the `0..255` scale.
- Histogram bins are raw counts that sum to `width * height`.
- Length-like light metrics are normalized by `min(width, height)`.
- Area-like light metrics are fractions of the full image area.

That normalization is intentional: a light radius of `0.05` means "5% of the
short image side", regardless of probe resolution.

## Current Paths

- Python/headless render paths analyze the authored camera at the shot canvas
  size.
- GUI Stats analyzes the authored camera too, but caps the live probe resolution
  to keep interactive editing responsive. Public GUI metrics are normalized
  ratios/fractions; `luminance.width` and `luminance.height` report the actual
  probe dimensions used for raw histogram counts and overlay scaling.
- `rr.metrics` is the luminance-only alias view of `rr.analysis.luminance`.
- When the GUI editor viewport diverges from the authored camera, the live
  light overlay is hidden because overlay geometry would no longer line up
  with the visible viewport. The Stats numbers remain authored-camera numbers.

## Python Example

```python
from anim.renderer import render_frame

rr = render_frame(animate, timeline, settings=shot, analyze=True)
a = rr.analysis

print(a.luminance.mean, a.luminance.contrast_spread)
print(a.color.richness, a.color.colored_fraction)
for light in a.lights:
    print(light.id, light.radius_ratio, light.transition_width_ratio, light.confidence)
```

## Luminance

`FrameAnalysis.luminance` describes whole-frame brightness and contrast.

| Field | Meaning |
|---|---|
| `mean` | Mean frame luminance on the `0..255` scale |
| `median` | 50th-percentile luminance |
| `shadow_floor` | 5th-percentile luminance |
| `highlight_ceiling` | 95th-percentile luminance |
| `highlight_peak` | 99th-percentile luminance |
| `contrast_std` | Luminance standard deviation |
| `contrast_spread` | `highlight_ceiling - shadow_floor` |
| `near_black_fraction` | Fraction of pixels with luminance `<= near_black_bin_max` (default `5`) |
| `near_white_fraction` | Fraction of pixels with luminance `>= near_white_bin_min` (default `250`) |
| `clipped_channel_fraction` | Fraction of pixels where any RGB channel is `255` |
| `histogram` | 256-bin luminance histogram |
| `width`, `height` | Image dimensions used for the analysis |

### Reading It

- Washed-out frames usually have low `contrast_spread`.
- Shadow-heavy frames have high `near_black_fraction`.
- Aggressively blown highlights show up in `near_white_fraction` and
  `clipped_channel_fraction`.
- `clipped_channel_fraction` is not the same as "white pixels": it catches any
  per-channel saturation.

### Histogram-Derived Occupancy

The histogram already contains enough information to compute cumulative dark or
bright occupancy ratios in Python:

```python
hist = rr.metrics.histogram
n = rr.metrics.width * rr.metrics.height

near_black_fraction = sum(hist[:6]) / n
near_white_fraction = sum(hist[250:]) / n
```

## Color

`FrameAnalysis.color` summarizes chromatic content over pixels above the
saturation threshold.

| Field | Meaning |
|---|---|
| `mean_saturation` | Mean HSV saturation of chromatic pixels |
| `hue_entropy` | Shannon entropy of the 36-bin hue histogram |
| `colored_fraction` | Fraction of pixels above the chroma threshold |
| `richness` | `hue_entropy * mean_saturation * colored_fraction` |
| `n_colored` | Raw count of chromatic pixels |
| `hue_histogram` | 36-bin hue histogram |

`richness` is the single-number "is this frame actually colorful?" summary.

## Point-Light Appearance

`FrameAnalysis.lights` contains one `PointLightAppearance` per authored
`PointLight`.

These measurements are intentionally sensitive to anything that changes the
visible light disc in the final image: exposure, white point, contrast,
reflections, occlusion, bloom, and surrounding geometry. They are not meant to
be invariant to those choices; they are meant to describe the final appearance
robustly.

| Field | Meaning |
|---|---|
| `id` | Source `PointLight` id |
| `world_x`, `world_y` | Light position in world coordinates |
| `image_x`, `image_y` | Projected image-space center in pixels |
| `visible` | Whether a connected bright structure was found |
| `radius_ratio` | Primary size metric: equivalent connected-component radius, normalized by short side |
| `coverage_fraction` | Connected-component area as a fraction of the whole image |
| `saturated_radius_ratio` | Secondary size metric from the legacy bright-threshold radius |
| `transition_width_ratio` | Edge width (`r20 - r80`) normalized by short side |
| `peak_luminance` | Peak luminance at the light structure |
| `background_luminance` | Estimated local background luminance |
| `peak_contrast` | `peak_luminance - background_luminance` |
| `touches_frame_edge` | Whether the measured bright structure hits the image boundary |
| `confidence` | Heuristic confidence in `[0, 1]` |

### Interpretation

- `radius_ratio` is the primary "how big is the light disc?" answer.
- `saturated_radius_ratio` preserves the old threshold-based behavior as a
  secondary metric.
- Small `transition_width_ratio` means a sharper edge.
- Large `peak_contrast` means the light stands out strongly from local
  background.
- Low `confidence` usually means weak contrast, tiny area, center mismatch, or
  truncation at the frame edge.

### Common Cases

- `visible = false`, `radius_ratio = 0`: the light is not visually resolved in
  this frame.
- `touches_frame_edge = true`: size is truncated by the frame boundary.
- Large `radius_ratio` with large `transition_width_ratio`: broad soft halo.
- Large `radius_ratio` with small `transition_width_ratio`: big but crisp disc.

## FrameAnalysisParams

`FrameAnalysisParams` controls which parts of the analysis run and the default
thresholds used by the CPU analyzer.

| Field | Meaning |
|---|---|
| `analyze_luminance` | Populate `luminance` |
| `analyze_color` | Populate `color` |
| `analyze_lights` | Populate `lights` |
| `lights.search_radius_ratio` | Search radius for each light patch |
| `lights.legacy_bright_threshold` | Threshold for `saturated_radius_ratio` |
| `lights.legacy_radius_percentile` | Percentile for `saturated_radius_ratio` |
| `lights.legacy_min_bright_pixels` | Minimum sample count for the legacy radius |
| `lights.seed_fraction` | Seed threshold relative to peak excess luminance |
| `lights.grow_fraction` | Grow threshold for connected-component expansion |
| `lights.center_snap_px` | Max image-space snap distance when the exact center is not a seed |
| `saturation_threshold` | Color-analysis chroma threshold |
| `near_black_bin_max` | Upper histogram bin for `near_black_fraction` |
| `near_white_bin_min` | Lower histogram bin for `near_white_fraction` |

## Summary

- Use `luminance` for exposure and washed-out detection.
- Use `color` for chromatic richness.
- Use `lights` for per-light apparent size, edge softness, contrast, and
  confidence.
- Prefer normalized ratios over raw pixels when writing filters.
