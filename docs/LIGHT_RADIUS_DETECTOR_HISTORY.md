# Light Radius Detector History

This note records detector variants that were useful during light-radius
characterization but are no longer part of the active public API. The production
GUI overlay and the `Radius %` metric use `radius_ratio`. The only retained
comparison candidate is `radius_candidate_sector_consensus_ratio`.

## Current Signal Contract

Circle-boundary metrics use an internal grayscale signal derived from the final
RGB8 camera image:

- Convert each pixel to BT.709 luminance.
- Remap that luminance with `PointLightAppearanceParams.radius_signal_gamma`
  (`0.5` by default).
- Subtract a local background estimate before radial/sector edge detection.

Whole-frame luminance/color metrics and light brightness diagnostics still use
the normal final RGB8 image semantics.

## Retained Candidate

`radius_candidate_sector_consensus_ratio` looks for the radius with the strongest
agreement across angular sectors. It remains exposed because it often tracks the
official radius closely and gives a useful independent check when refining the
production detector.

## Pruned Variants

These experiments were removed from active code and public bindings after the
low-gamma luminance run made the official and sector-consensus results strong
enough to keep the UI focused:

- Profile knee: selected the knee of the global radial signal profile. It was
  simple but too sensitive to gradual halos and two-scale profiles.
- Robust sector edge: shaped each sector profile and took a robust median of
  per-sector edges. It helped during exploration, but added complexity and often
  duplicated the better sector-consensus evidence.
- Outer shoulder: searched for a broader secondary shoulder after a bright core.
  It was useful for diagnosing two-scale cases, but was not reliable enough to
  keep as public API.

## Characterization Snapshots

The historical galleries are the source of truth for comparing detector behavior:

- Low-gamma luminance detector pass: http://194.32.76.176:8741/lpt2d_light_radius_low_gamma_luminance_gpu_1080p_10m_20260411/
- Pre-pruning luminance stability pass with all candidates: http://194.32.76.176:8741/lpt2d_light_radius_luminance_stability_gpu_1080p_10m_20260411/
