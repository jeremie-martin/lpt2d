# Renders

This directory is split into two layers:

- `clean_room/`
  Canonical outputs from the current per-animation example scripts in `anim/examples/clean_room_*.py`.
- `archive/`
  Preserved legacy or validation outputs that are no longer the canonical source of truth.

## Clean Room Contract

Each scene folder under `clean_room/` is expected to contain:

- `frame_000.json`
  Representative scene snapshot exported from the current script.
- `sheet.png`
  Baseline low-resolution contact sheet for the scene.
- `tuning.json`
  Exposure tuning report used for script-side validation.
- Optional `preview.mp4` or `hq.mp4`
  Intentionally rendered videos for scenes that have been promoted beyond the baseline sheet/json pass.

The current root overview image is:

- `clean_room/overview_sheet.png`

## Archive Policy

Archived outputs are kept when one of these is true:

- they came from an older layout or naming scheme
- they were generated from an older version of a scene script
- they were validation or smoke-test renders rather than canonical assets

All current clean-room scenes now have canonical `sheet.png` outputs. Preview videos are present for the full set, and `mirror_shutters` also has a canonical `hq.mp4`.
