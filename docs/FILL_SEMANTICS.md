# Fill Semantics

Interior fill for closed shapes (circle, polygon, ellipse). Rasterized as flat-colored
triangles into a separate RGB16F texture, composited additively onto ray-traced light
during post-processing.

## Pipeline position

```
1. color = raytraced / maxVal * exposure     ← fill is NOT here
2. color += fillColor                        ← fill enters raw
3. background / ambient mask
4. highlights / shadows
5. tone mapping (per-channel)
6. contrast
7. saturation, temperature, hue rotation
8. gamma
9. grain, vignette, opacity
```

Fill bypasses exposure normalization. Its brightness is absolute, not relative to scene
energy. Changing exposure, SPP, or adding lights shifts the visual balance between fill
and traced light without changing the fill itself.

Everything from tone mapping onward (steps 5-9) does affect fill appearance.

## Per-channel tonemap desaturation

At high fill values, the dominant color channel saturates against the tone curve while
weaker channels catch up, shifting the perceived color toward white.

Example for a red spectral color normalized to (1.0, 0.3, 0.1):

| fill | post-tonemap ratio | appearance       |
|------|--------------------|------------------|
| 0.15 | 1.0 : 0.24 : 0.08 | saturated red    |
| 1.0  | 1.0 : 0.51 : 0.13 | washed-out pink  |

The authored color you see depends on the fill intensity. This is inherent to per-channel
tone mapping and affects ray-traced light the same way, but it is less desirable for fill
where the intent is to show a specific chosen color.

## Candidate fixes

1. **Post-tonemap fill** — apply fill after tone mapping so the authored color is exactly
   what appears on screen. Tradeoff: fill would not integrate with traced light under the
   same tone curve.
2. **Luminance-preserving tonemap for fill** — compress brightness while preserving hue
   ratios. Tradeoff: adds a second tone-mapping path.

Neither is implemented yet.

## Shape support

- Circle, polygon, ellipse: fully supported (CPU triangulation, 4x MSAA).
- Segment, arc, bezier: silently ignored (no fillable interior).
- Polygon fill boundary uses 8 arc samples per rounded corner (hardcoded).

## Material interaction

`Material.fill` is a float intensity multiplier. Fill color comes from the material's
spectral coefficients, normalized so the brightest RGB channel = 1.0, then scaled by
`fill`. Fill does not participate in ray tracing — no emission, no refraction, no
secondary bounces from filled interiors.
