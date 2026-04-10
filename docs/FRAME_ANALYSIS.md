# Frame Analysis

A rendered frame in lpt2d is an RGB image produced by path-tracing an authored
`Shot`. **Frame analysis** is the set of numbers you can ask for alongside that
image — summary statistics that describe what the render actually looks like,
without having to eyeball it. The same numbers drive the GUI Stats window,
feed the crystal_field acceptance filter, and are what `rr.analysis` returns
to every Python tool that wants to talk about a frame quantitatively.

This document describes **what each value means, what scale it lives on, and
what range you should expect** for a well-formed animation frame. It does not
describe the implementation — for that, see `src/shaders/analysis.comp` and
`src/core/gpu_image_analysis.cpp`.

## What analysis answers

Three questions about the just-rendered frame:

1. **How bright is it?**  → `FrameAnalysis.lum` (luminance statistics)
2. **How colorful is it?** → `FrameAnalysis.color` (HSV-based color statistics)
3. **Where are the lights and how do they look?** → `FrameAnalysis.circles`
   (one measurement per authored `PointLight`)

All three are computed from the post-tonemap display texture — the same RGB8
image the user sees on screen — so every number is "what the eye actually
sees," not "what the tracer had in the HDR buffer."

## How to get it

**Python (per-render opt-in):**

```python
from anim.renderer import render_frame

rr = render_frame(animate, timeline, settings=shot, analyze=True)
a  = rr.analysis

a.lum.mean_lum      # brightness
a.color.color_richness
for c in a.circles:
    print(c.id, c.radius_px, c.sharpness)
```

Without `analyze=True`, only the cheap luminance histogram on
`rr.metrics` is populated; `rr.analysis.circles` is empty and the GPU
skips the Voronoi pass entirely. Video-batch paths leave it off.

**GUI (live):** open the floating **Stats** window (`!` hotkey). While the
window is visible and the **Live** checkbox is on, the GPU analyser runs
every frame (~1–2 ms). Close the window or uncheck Live to stop dispatching.

**C++:** `Renderer::run_frame_analysis()` returns a full `FrameAnalysis`
from the current display FBO.

## Luminance — `FrameAnalysis.lum`

All luminance values are on the **0–255 BT.709 integer scale**, matching
the post-tonemap RGB8 buffer. Every scalar is derived from a single
256-bin histogram, so they are mutually consistent.

| Field | What it measures | Scale | Typical range |
|---|---|---|---|
| `mean_lum` | Average brightness of the whole frame | 0–255 | 40–140 |
| `p50` | Median luminance (half of pixels below) | 0–255 | usually 10–40 lower than `mean_lum` on high-contrast scenes |
| `p05` | 5th-percentile luminance — the **shadow floor** | 0–255 | 0–20 for most scenes |
| `p95` | 95th-percentile luminance — the **highlight ceiling** | 0–255 | 120–220 |
| `p99` | Top 1% luminance — the **peak** | 0–255 | 180–255 |
| `std_dev` | Standard deviation — the **global contrast** | 0–255 | 20–80 |
| `lum_min` | Smallest populated histogram bin | 0–255 | often 0 for scenes with any black |
| `lum_max` | Largest populated histogram bin | 0–255 | often 255 on scenes with any highlight |
| `pct_black` | Fraction of pixels at luminance 0 (crushed blacks) | 0–1 | 0.05–0.40 for most scenes |
| `pct_clipped` | Fraction of pixels with any channel at 255 (clipped whites) | 0–1 | 0.00–0.05 for well-exposed frames |
| `histogram[256]` | Raw bin counts for the Stats panel histogram display | integer counts summing to W·H | — |
| `width`, `height` | Image dimensions the stats were measured at | pixels | matches `rr.pixels` |

### How to read these together

- **"Is this frame well-exposed?"** Look at `mean_lum` ≈ 60–120 AND
  `pct_clipped` < 0.05 AND `pct_black` < 0.40. Any two of those three
  failing is a clear exposure problem.
- **"Is it flat or punchy?"** `std_dev` says it. Flat/washed out < 20;
  punchy 40–80; extreme contrast > 100 (usually means most of the image
  is black with a few bright specks).
- **"Is it crushing shadows or clipping highlights?"** `pct_black` vs
  `pct_clipped`. Both high → the tonemap is fighting the scene and you
  want to adjust exposure or white point.
- **"What's the dynamic range the viewer sees?"** `p95 - p05`. This is
  the "contrast spread" crystal_field uses (`MIN_CONTRAST_SPREAD = 0.25`
  on a 0–1 scale, i.e. 64/255).

### What extremes mean

| Value | What it indicates |
|---|---|
| `mean_lum < 30` | Near-black frame, probably underexposed or almost empty. |
| `mean_lum > 180` | Overexposed; check `pct_clipped` and the tonemap's `white_point`. |
| `pct_black > 0.70` | Mostly black — intentional only for dramatic dark scenes. |
| `pct_clipped > 0.15` | Aggressive clipping; lower exposure or raise `white_point`. |
| `std_dev < 10` | Flat/uniform — greyfield, fog, or totally unlit. |
| `p99 - p05 < 30` | Low dynamic range, probably washed out. |

## Color — `FrameAnalysis.color`

Color stats summarise **chromatic content** — how much of the image is
actually colored, how vivid it is, and how varied. All calculations use
HSV over pixels whose saturation is above `saturation_threshold` (0.05
by default). Greyscale-ish pixels are excluded so a dim red candle in a
black room still reports the red as the dominant hue, not as "mostly
black".

| Field | What it measures | Scale | Typical range |
|---|---|---|---|
| `mean_saturation` | Average HSV saturation of chromatic pixels | 0–1 | 0.15–0.60 |
| `hue_entropy` | Shannon entropy of the 36-bin hue histogram | bits (0–5.17 max) | 0.5–3.5 |
| `chromatic_fraction` | Fraction of pixels above the chroma threshold | 0–1 | 0.10–0.90 |
| `color_richness` | Composite: `hue_entropy × mean_saturation × chromatic_fraction` | 0+ | 0.1–2.0 |
| `n_chromatic` | Raw count of chromatic pixels | integer | `W·H · chromatic_fraction` |
| `hue_histogram[36]` | 36-bin hue histogram (10° per bin), chromatic pixels only | integer counts | — |

### How to read these together

- **`color_richness` is the single number** to eyeball when you want "is
  this frame colourful or is it just a greyfield". It multiplies the three
  components together:
  - `hue_entropy` = "how many distinct colors" (1 color → 0, 2 equal colors →
    1 bit, 6 equal hues → ~2.58, full rainbow → ~5.17)
  - `mean_saturation` = "how vivid" (pure white/gray → 0, pure primary → 1)
  - `chromatic_fraction` = "how much of the image has any color at all"
- crystal_field accepts a frame if `color_richness ≥ 0.15` — that's the
  floor for "the scene shows some actual color".
- **`hue_entropy` alone** is useful for "is this monochrome or multi-hue"
  — a single dominant color gives <0.5 bits; a distinctly bi-chromatic
  scene (orange + blue for example) gives ~1 bit; a rainbow gives
  3+ bits.

### What extremes mean

| Value | What it indicates |
|---|---|
| `color_richness < 0.05` | Effectively greyscale — no usable color signal. |
| `mean_saturation > 0.8` with `chromatic_fraction < 0.1` | A few very saturated specks on an otherwise grey frame. |
| `hue_entropy < 0.3` | Single dominant hue — good for mood pieces, bad if you wanted variety. |
| `chromatic_fraction = 1.0` | Every pixel is above the chroma threshold — very colorful frame (or saturation_threshold is set too low). |
| `color_richness > 2.0` | Vibrant multi-color frame. |

## Light circles — `FrameAnalysis.circles`

For each authored `PointLight` in the scene, the analyser measures the
**apparent bright halo** the tracer actually produced around that light's
world position. Every pixel in the image is attributed to its nearest
light via a Voronoi partition, and then five numbers are extracted from
each light's cell.

This is the measurement crystal_field uses to answer *"did the moving
light actually show up as a visible circle, or did the glass absorb it?"*

`circles` contains exactly one `LightCircle` per `PointLight` in the
scene, in the order they appear in `upload_scene`'s flattened light
list (group transforms already applied). When `analyze_circles=false`
the list is still present but measurement fields are zeroed.

| Field | What it measures | Scale | Typical range |
|---|---|---|---|
| `id` | PointLight id from the scene | string | — |
| `world_x`, `world_y` | Light centre in world coordinates | world units | — |
| `pixel_x`, `pixel_y` | Light centre in image pixels (top-left origin) | pixels | — |
| `radius_px` | **Size.** 90th-percentile distance among bright pixels in the cell. The "how big is this light's bright blob" metric. | pixels | 2–100 for crystal_field probe (640×360); scales with render resolution |
| `radius_half_max_px` | **Core.** FWHM — radius where the radial profile drops to half its peak. Less sensitive to stray bright specks at the Voronoi boundary than `radius_px`. | pixels | usually within ±30% of `radius_px` on clean frames |
| `n_bright_pixels` | Total pixels above the bright threshold inside the cell. A sanity counter. | integer | crystal_field requires ≥ 20 for the radius to be trusted |
| `sharpness` | **Edge slope.** Luminance drop per pixel across `[0.5r, 1.5r]`. | 0–1/pixel | 0.01–0.10 on well-defined lights |
| `mean_luminance` | Global frame mean luminance (NOT per-cell — same value on every circle in the list) | 0–1 | 0.15–0.55 |
| `profile[]` | Radial luminance profile: element `r` is the mean luminance in the ring at distance `r` from the centre | array of floats 0–1, length ≤ 201 | — |

### Why two radii

The two radius fields answer the same question with different failure
modes, and crystal_field checks both:

- **`radius_px` (90th percentile)** is the historical metric. It's
  robust to a few missing pixels inside the disc but can be inflated
  by a handful of stray bright pixels far from the light that happen
  to fall inside the Voronoi cell.
- **`radius_half_max_px` (FWHM)** measures where the radial luminance
  *profile* drops to half its peak. It ignores the outlier bright
  pixels entirely — it's what you'd get from fitting a Gaussian to the
  profile and reading the half-width. If this disagrees wildly with
  `radius_px`, it means the Voronoi cell contains bright pixels that
  don't belong to a clean circular halo.

### Why `sharpness`

A perfectly sharp disc has a step-function profile: 1.0 inside, 0.0
outside. A diffuse glow has a smooth falloff. `sharpness` is the
luminance drop per pixel across the transition band (half-radius to
1.5× radius). Higher = crisper edge.

crystal_field's `MIN_SHARPNESS = 0.010` rejects lights where the edge
is so soft that the "circle" is really just an ambient bloom. Values
much above 0.05 mean the light is a tiny hard-edged disc.

### What extremes mean per-circle

| Value | What it indicates |
|---|---|
| `radius_px = 0` | No bright pixels found (below `min_bright_pixels` or below `bright_threshold`). The light is invisible in this frame. |
| `radius_px` very large (approaching `max_radius_px = 200`) | The bright threshold is hitting pixels far from the light — either the frame is globally overexposed, or the Voronoi cell is huge because there are only 1–2 lights. |
| `n_bright_pixels < 20` | Suspect — crystal_field treats this as "the measurement isn't trustworthy, reject". |
| `radius_half_max_px << radius_px` | The cell has bright outliers far from the center; FWHM is the more honest number here. |
| `sharpness < 0.005` | Very soft halo / bloom, not a crisp circle. |

## Tunable parameters — `FrameAnalysisParams`

The call-time parameter block. Defaults are tuned for crystal_field-style
animations; you'd rarely override most of these.

| Field | Default | What it controls |
|---|---|---|
| `analyze_luminance` | `true` | Whether to populate `lum`. (The GPU always builds the histogram; this only gates the CPU finalize.) |
| `analyze_color` | `true` | Whether to populate `color`. |
| `analyze_circles` | `true` | Whether to run the per-pixel Voronoi pass. **The only flag that actually affects GPU cost.** Set to `false` for a metrics-only probe. |
| `saturation_threshold` | `0.05` | Pixels below this HSV-S are treated as achromatic and excluded from color stats. |
| `circles.max_radius_px` | `200` | Upper bound on the radial profile. Pixels farther than this from their nearest light are dropped from the bright-pixel count. |
| `circles.bright_threshold` | `0.92` | Luminance (0–1) above which a pixel counts as "bright" for the radius percentile and `n_bright_pixels`. |
| `circles.min_bright_pixels` | `6` | Below this count the per-light `radius_px` is forced to 0 instead of reporting a noisy percentile on a tiny sample. |
| `circles.radius_percentile` | `90.0` | Which percentile of bright-pixel distances `radius_px` reports. |
| `circles.half_max_fraction` | `0.5` | Fraction of peak luminance at which `radius_half_max_px` is measured (0.5 → FWHM). |

## A "good" animation frame at a glance

For the crystal_field family (the most stringent consumer today) these are
the numbers a passing frame looks like:

```
Brightness:      mean_lum ≈ 100,  std_dev ≈ 40
Shadows/peaks:   p05 ≈ 2,  p95 ≈ 180,  p99 ≈ 230
Black/clipped:   pct_black ≈ 0.20,  pct_clipped ≈ 0.02
Color:           chromatic_fraction ≈ 0.45,  mean_saturation ≈ 0.40,
                 hue_entropy ≈ 1.2,  color_richness ≈ 0.22
Moving light:    radius_px ≈ 5,  radius_half_max_px ≈ 6,
                 sharpness ≈ 0.05,  n_bright_pixels ≈ 80
```

Frames that drift far from these usually fail one of the
`crystal_field/check.py` thresholds. The common failure modes:

- `mean > 0.70` → *"too bright"* — aggressive tonemap; drop exposure.
- `mean < 0.12` → *"too dark"* — something is blocking all the light.
- `p95 - p05 < 0.25` → *"washed out"* — low dynamic range.
- `moving_r < 3 px` → light never shows up as a visible blob.
- `moving_r > 80 px` → there's no distinct light, just a glow.
- `sharpness < 0.01` → fuzzy halo, no edge.
- `n_bright_pixels < 20` → speckle, not a real circle.
- `color_richness < 0.15` → visually greyscale.

## Cost and opt-in

Analysis is an **opt-in**, GPU-accelerated pass. One compute dispatch,
one ~50 KB SSBO readback, typically ~1–2 ms on modern hardware
regardless of image resolution. Specifically:

- `render_shot(analyze=False)` (the default) pays zero analysis cost.
  Video batch paths, contact sheets, CLI export, and most tests leave
  it off.
- `render_shot(analyze=True)` runs the full pass. Crystal_field probes
  and per-frame quality checks pass `True`.
- The GUI dispatches once per frame, gated on **both** the Stats window
  being open **and** the Live checkbox being on. Closing the window or
  unchecking Live stops all analysis work.
- `analyze_circles=false` is the only flag that meaningfully reduces
  cost — it skips the O(W·H·L) per-pixel Voronoi loop on the GPU and
  the matching readback. The luminance and colour histograms run on
  every `analyze=True` call regardless.

## Quick reference

```
FrameAnalysis
├── lum : LuminanceStats          (always populated when analyze=True)
│   ├── mean_lum         float    0–255, BT.709 mean
│   ├── p05, p50, p95, p99 float  percentiles, 0–255
│   ├── std_dev          float    standard deviation, 0–255
│   ├── lum_min, lum_max int      first/last populated histogram bin
│   ├── pct_black        float    0–1, fraction at luminance 0
│   ├── pct_clipped      float    0–1, any-channel-255 fraction
│   ├── histogram[256]   int[]    raw counts, Σ = width·height
│   └── width, height    int      image dimensions
│
├── color : ColorStats            (always populated when analyze=True)
│   ├── mean_saturation  float    0–1, HSV S over chromatic pixels
│   ├── hue_entropy      float    bits, 0–log2(36) ≈ 5.17
│   ├── chromatic_fraction float  0–1, n_chromatic / W·H
│   ├── color_richness   float    entropy × sat × chromatic_fraction
│   ├── n_chromatic      int      pixel count
│   └── hue_histogram[36] int[]   10° bins, chromatic pixels only
│
└── circles : LightCircle[]       (one per PointLight; empty when
    │                              analyze_circles=false)
    ├── id                 string  scene PointLight id
    ├── world_x, world_y   float   world coords
    ├── pixel_x, pixel_y   float   top-left image pixels
    ├── radius_px          float   90th-percentile bright radius (px)
    ├── radius_half_max_px float   FWHM radius (px)
    ├── n_bright_pixels    int     bright-pixel count in Voronoi cell
    ├── sharpness          float   luminance drop per pixel at edge
    ├── mean_luminance     float   global frame mean (0–1)
    └── profile            float[] radial profile (0–1), len ≤ 201
```
