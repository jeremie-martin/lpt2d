# Wall Albedo Aesthetics

Empirical note on what makes procedural scene families look dim vs.
alive. Derived from a 2026-04-19 iteration pass on cathedral_aperture,
iris, and grating_splitter.

## The finding

Wall albedo is the dominant knob on a scene's overall "mood". Every other
post-process and intensity tweak is secondary. Two useful poles:

| Look | Albedo | Roughness | Feel                                        |
|------|--------|-----------|---------------------------------------------|
| C    | 0.40   | 0.30      | shadowy cathedral, moody, dark chamber      |
| G    | 1.00   | 0.10      | luminous mirror hall, clean, colorful, full |

The range from C through G is all legitimate — avoid optimizing toward
any single point.

## Why albedo, not post-processing

Post-process knobs (`ambient`, `shadows`, `contrast`, `exposure`, `gamma`,
tonemap, `white_point`, `normalize=max`) can reshape the value histogram
but cannot synthesize light in image regions that received no rays. Low
albedo causes rays to be absorbed after a few bounces, so indirect-lit
chamber areas have near-zero signal. Lifting darks there reveals noise,
not bounce light — the image looks muddy and desaturates because a
constant grey offset stacks on every pixel.

High albedo causes rays to bounce 5–10+ times before dying. Each pixel
integrates over many paths, which (a) fills indirect areas with real,
spatially-varying signal, and (b) has lower variance per pixel (less
noise).

## Coordinated sampling

Exposure and roughness should slide with albedo so mean-luma stays in a
reasonable band regardless of the drawn look. The linear fit we used in
cathedral_aperture / iris / grating_splitter:

```python
WALL_ALBEDO_RANGE = (0.45, 1.0)

def _wall_material(albedo):
    roughness = max(0.10, 0.43 - 0.33 * albedo)
    return Material(metallic=1.0, roughness=roughness, albedo=albedo)

def _exposure_for_albedo(albedo, n_lights):
    base = -1.75 * albedo - 3.45
    return base + (0.0 if n_lights == 1 else -0.2 if n_lights == 2 else -0.4)
```

Derived from a sweep of 8 (albedo, exposure) pairs spanning 0.18–1.00.

## Gates

The gate that worked across the C→G range:

| Gate                     | Value        |
|--------------------------|--------------|
| mean_luma                | 0.12 – 0.65  |
| P90_luma (min)           | 0.35         |
| IDR (min)                | 0.30         |
| near_black_fraction max  | 0.55         |
| clipped max              | 0.07 – 0.08  |
| colorfulness (warm-dom)  | ≥ 0.08       |
| colorfulness (other)     | ≥ 0.01       |
| passing frame fraction   | ≥ 0.30       |

Do **not** use `mean_luma` as a narrow target — it varies 3× across the
C→G band without any of them being "wrong".

## Spectrum-intensity compensation

Separate concern but often conflated with the albedo one: narrow warm
bands and full-spectrum white deliver very different perceived luminance
per photon. Author intensity in white-equivalent units and wrap with
`anim.intensity_for_spectrum(white_intensity, spectrum)` — it's what
crystal_field does, now hoisted to `anim/light_intensity.py`.

Without this, warm projectors at the same "authored intensity" as white
silently produce ~5× less apparent brightness, which tricks you into
raising wall albedo or exposure to compensate — and then the white variants
blow out.

## Anti-patterns seen and corrected

1. **Darkening walls to "increase contrast".** Measuring flat-midgray
   scenes and lowering albedo to push the mean down is backwards. The
   flatness came from weak features, not bright walls. Walls stay bright,
   features get stronger (higher intensity, spectrum-compensated).
2. **Mean-luma gates.** Rejecting scenes outside a narrow mean band filters
   out the G-style luminous variants. Gate on IDR and colorfulness; mean
   is a wide band, not a target.
3. **Post-process lifting of darks.** `ambient`, `shadows +X`, `contrast
   < 1.0`, `normalize=max` all produce muddy grey fogs when applied to
   low-albedo scenes. See `tmp/diag/h_vs_g/contact_sheet.png` for the
   proof — none of the H+post variants approach G.

## Related files

- `anim/light_intensity.py` — spectrum-luminance compensation
- `examples/python/families/cathedral_aperture.py` — reference implementation
- `tmp/diag/wall_sweep/` — the eight-point sweep (throwaway, may be gone)
- `tmp/diag/h_vs_g/` — proof that post can't recover G from H (throwaway)
