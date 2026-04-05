# Renders

This directory is split into two layers:

- `clean_room/`
  Canonical outputs from the current clean-room registry in `anim/examples/`.
- `archive/`
  Preserved legacy or validation outputs that are no longer the canonical source of truth.

## Clean Room Contract

The canonical clean-room tree is now family-based:

- `clean_room/<family>/<scene>/`
  Per-scene current outputs.
- `clean_room/manifest.json`
  Current library inventory.
- `clean_room/library_audit*.json`
  Non-visual analysis reports used to tune and police the library.

Each current scene folder under `clean_room/<family>/` is expected to contain:

- `frame_000.json`
  Representative scene snapshot exported from the current script.
- Optional `sheet.png`
  Contact sheet for scenes that have been promoted to media-rendered status.
- Optional `tuning.json`
  Exposure tuning report for scenes that were explicitly tuned and rendered.
- Optional `preview.mp4` or `hq.mp4`
  Intentionally rendered videos for scenes that have been promoted beyond the baseline JSON/audit pass.

Current library policy:

- The full registry should have canonical `frame_000.json` exports and a current `manifest.json`.
- The manifest should reflect the full current registry after any promoted-render pass; if a curated subset is rendered separately, rerun the full no-render export afterward to refresh inventory.
- Full-library quality control is primarily driven by `library_audit.json` and targeted follow-up audit reports.
- Image/video renders are curated and staged, not blindly generated for every scene in a large library wave.
- Preview renders are intentionally a little cleaner than before (`640x360` by current default), while HQ renders remain opt-in promotions.

## Archive Policy

Archived outputs are kept when one of these is true:

- they came from an older layout or naming scheme
- they were generated from an older version of a scene script
- they were validation or smoke-test renders rather than canonical assets
- they belonged to the pre-family flat layout that was replaced by the current family-aware tree
