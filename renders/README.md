# Renders

This directory is for render artifacts and notes about how to treat them.

## Current Status

There is currently **no large canonical render library** in this repo. The old
`clean_room` story has been retired, and the project is intentionally not
pretending that a giant example/render catalog is the current source of truth.

For now, the main reference surfaces are:

- the canonical example pack in [`examples/`](/home/holo/prog/lpt2d/examples)
- saved scene files in [`scenes/`](/home/holo/prog/lpt2d/scenes)
- secondary exploratory scripts in
  [`anim/examples/secondary/`](/home/holo/prog/lpt2d/anim/examples/secondary)
- the roadmap direction in [ROADMAP.md](/home/holo/prog/lpt2d/ROADMAP.md)

## What Belongs Here

This directory may contain:

- curated preview or HQ renders worth keeping
- contact sheets or representative stills
- temporary artifacts that are useful for discussion or validation
- notes about render organization and retention policy

It should not quietly become a second source of truth for scene definitions.

## Policy

- Scene structure belongs in JSON scenes and canonical example code, not in render outputs.
- Saved renders should be intentional and curated, not generated in bulk without purpose.
- If the canonical example pack later grows a curated render surface, that
  should happen explicitly rather than by drift.
