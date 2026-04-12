# Crystal Field Generation Logic

This document describes the current crystal-field generation pipeline at
the algorithm level. It is meant to explain what is sampled, why the
lighting is scaled the way it is, how scenes are accepted or rejected, and
how catalog artifacts are produced.

## 1. Sampling A Candidate Scene

Each candidate is represented by a `Params` object. The sampler chooses one
complete scene description before anything is rendered.

The active free sampler currently chooses one of four non-glass peers with
equal weight:

- `black_diffuse`
- `gray_diffuse`
- `colored_diffuse`
- `brushed_metal`

The glass branch still exists for old parameter files, targeted tools, and
the structured catalog, but it is temporarily excluded from free sampling
while the non-glass outcomes are tuned from measured probe data.

The outcome determines the shape and material branch. Active free-sampler
scenes use rounded polygons with randomized side count, size, corner radius,
and optional rotation/jitter. Targeted glass scenes use circles. Materials
are sampled inside each outcome branch, so local material rules stay close to
the branch they affect, while broad tunable ranges and weighted choices live
in the explicit sampler policy objects in `sampling.py`.

The grid is sampled independently from the material outcome. Spacing
controls density, rows are centered around medium-sized layouts, columns
are chosen to fit inside the mirror box, and a small fraction of candidates
may remove some grid positions.

## 2. Moving Lights

Moving lights are the main visual driver. The sampler chooses:

- number of moving lights;
- path style;
- path speed;
- moving-light intensity;
- moving-light spectrum.

The current colored moving lights deliberately remain wavelength-range
lights. This preserves the useful visual character of the old system:
orange and deep-orange ranges emit only their wavelength band, so their
bright cores clip toward their own color rather than toward white.

For achromatic scenes, warm moving-light ranges are sampled often:

- orange: `550-700 nm`
- deep orange: `570-700 nm`

Full visible range `380-780 nm` remains the white moving-light case.

Moving-light intensity is stored as white-equivalent intent. At scene-build
time, range and RGB spectra receive the same spectrum compensation used by
ambient lights, so the rendered `PointLight.intensity` is explicit and
comparable across light colors.

## 3. Ambient Lights

Ambient lights are fixed point lights at the corners or sides of the mirror
box. They exist to keep the frame readable and to reveal the surrounding
structure.

Historically these ambient lights were white. That made warm moving-light
scenes readable, but it also washed out the colored look. The current
logic keeps the moving lights as they are and adds color only to ambient
lights when the moving light itself is colored.

When the moving light is white/full-range, ambient stays white.

When the moving light is colored, the sampler generates one shared
complementary ambient color for the whole scene:

1. Estimate the moving light hue.
2. Rotate the hue by 180 degrees.
3. Add one scene-level random hue jitter in `[-18 degrees, +18 degrees]`.
4. Use full HSV saturation and value for the base ambient color.
5. Sample `white_mix` in `[0.35, 0.85]`.
6. Store that RGB color plus white mix directly in `Params`.

All ambient lights in a scene share this color. Per-light color variation
is intentionally left for later exploration.

## 4. White-Equivalent Light Intensity

Moving and ambient intensities are authored as white-equivalent values. In
other words, `ambient.intensity = 0.3` means "roughly as bright as a white
ambient light with intensity 0.3," even if the ambient spectrum is blue or
cyan. The same contract applies to `moving_intensity`.

For range spectra, the scene builder computes a luminance-weighted boost
relative to full-range white. For color spectra, it computes the effective
RGB after white mix:

```text
effective_rgb = rgb + (1 - rgb) * white_mix
```

Then it estimates linear Rec.709 luminance:

```text
luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
```

The rendered point-light intensity is:

```text
rendered_intensity = authored_intensity * spectrum_intensity_multiplier(spectrum)
```

This is not a guarantee that every post-processed image will have exactly
the same final pixel mean. Once tonemapping, gamma, clipping, caustics, and
material interactions are involved, exact image equality is not possible
from a single scalar. The contract is narrower and more useful: for the
white-mixed ambient colors used here, the physical input energy is scaled
so the colored ambient light lands close to the luminance of its white
equivalent.

The sampler chooses `moving_intensity` before `ambient.intensity`. After it
knows both spectra, it caps the ambient draw so:

```text
rendered_ambient_intensity <= rendered_moving_intensity
```

If a custom policy ever makes that cap fall below the ambient lower bound,
the cap wins; keeping ambient below the moving light is the stronger
contract.

Validation currently covers three levels:

- the fitted spectral color preserves representative ambient target
  luminance within 5%;
- simple render probes show colored ambient means close to white ambient
  means over several colors and intensities;
- crystal-field ambient-only probes show sampled real scenes close to the
  white-ambient baseline, with expected deviations when clipping is already
  present.

The `ambient_compare` command is the visual validation tool for this
feature. It renders a white-ambient baseline next to the complementary
ambient variant, writes metrics for both, and generates an HTML index for
side-by-side inspection.

## 5. RGB Light Conversion In The GUI

The GUI can convert a range light to a color-spectrum light. This is a
separate workflow from crystal-field ambient generation.

The conversion first estimates the RGB energy of the old wavelength range,
then fits a color spectrum to that RGB. A `Conversion headroom` slider
defaults to `0.5`, so the fitted RGB target is intentionally dimmer than
maximum value. The conversion then recomputes an intensity multiplier so
the dimmed spectrum recovers the old range's approximate linear RGB energy.

This avoids the most obvious white-core artifact that appears when a
saturated color fit runs too close to full channel value.

The CLI conversion keeps the old default headroom of `1.0`; the more
artist-facing headroom control currently lives in the GUI.

## 6. Choosing The Analysis Frame

A candidate animation is not judged on an arbitrary frame. The checker
first scans the animation without rendering and chooses the frame where
the moving lights are furthest from object centers. This is the clearest
probe frame for measuring light discs and scene readability.

The probe render uses a fixed low-resolution analysis shot:

- `960 x 540`
- `400,000` rays
- depth `10`
- fixed camera centered on the mirror box
- fixed analysis look

The renderer returns frame analysis through the C++ bindings. Python then
groups light measurements into moving lights and ambient lights by ID
prefix.

## 7. Acceptance Criteria

The rejection policy is intentionally small and explicit. A scene must
pass light-radius, luminance, contrast, shadow, and saturation gates.

The main measured quantities are:

- moving light radius min/mean/max;
- ambient light radius min/mean/max;
- moving-to-ambient radius ratio;
- mean luminance;
- near-black fraction;
- shadow floor;
- contrast spread;
- shadow fraction;
- mean saturation.

Some thresholds depend on material outcome:

- glass has a lower maximum mean luminance;
- black diffuse allows more shadow pixels.

The current checker deliberately does not use older color-colorfulness,
edge-width, peak-contrast, confidence, coverage, or pre-render geometry
guards.

## 8. Catalog Search

The catalog is a structured sweep. Unlike the active free sampler, it still
includes the targeted glass branch so old and experimental glass behavior can
be inspected deliberately. It fixes:

- material outcome;
- grid size;
- moving-light color range;
- number of moving lights.

For each catalog cell, everything else is sampled per attempt: exact
material parameters, shape parameters, build seed, ambient intensity,
ambient color, moving intensity, and post-processing look.

For one structural candidate, the catalog chooses the clear analysis frame
once, traces it once, and then replays many random post-processing looks
over the retained frame. This is much cheaper than retracing the whole
scene for every look. If no look passes, the catalog samples a new
structural scene.

If no attempt passes, the catalog still saves the closest failed candidate
so the failure mode can be inspected visually.

## 9. Outputs

Accepted or best-effort catalog entries write:

- a PNG still with metric overlay;
- the `Params` JSON that generated the scene;
- a metrics JSON sidecar;
- an authored `.shot.json` scene export;
- an HTML gallery with failure states and links.

Animations and other outputs are generated later from the same `Params` or
authored shot data. The catalog itself is primarily a visual and metric
survey of the parameter space.
