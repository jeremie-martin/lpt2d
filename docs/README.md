# Documentation

This directory holds the small set of first-party docs that are meant to stay
useful over time.

## Core Docs

- [README.md](/home/holo/prog/lpt2d/README.md)
  Project overview, build, run, and doc entry points.
- [AUTHORED.md](/home/holo/prog/lpt2d/docs/AUTHORED.md)
  The authored JSON contract used by committed scenes and benchmark shots.
- [GLOSSARY.md](/home/holo/prog/lpt2d/docs/GLOSSARY.md)
  Canonical terminology across the engine and authoring surfaces.
- [OUTLINE_JOIN_SEMANTICS.md](/home/holo/prog/lpt2d/docs/OUTLINE_JOIN_SEMANTICS.md)
  Conceptual model for hard, smooth, and rounded shape joins.
- [VISUAL_ITERATION.md](/home/holo/prog/lpt2d/docs/VISUAL_ITERATION.md)
  Current Python and GUI workflow for look development and diagnostics.
- [GUI_UX.md](/home/holo/prog/lpt2d/docs/GUI_UX.md)
  GUI identity, friction analysis, and improvement directions.
- [SEED_MODE.md](/home/holo/prog/lpt2d/docs/SEED_MODE.md)
  Shared semantics for deterministic and decorrelated rendering.
- [FILL_SEMANTICS.md](/home/holo/prog/lpt2d/docs/FILL_SEMANTICS.md)
  Fill pipeline position, tonemap desaturation, and candidate fixes.
- [IDEAS.md](/home/holo/prog/lpt2d/IDEAS.md)
  Centralized unscheduled ideas and follow-up work.

## Related Docs

- [examples/README.md](/home/holo/prog/lpt2d/examples/README.md)
  Canonical example pack.
- [evaluation/](/home/holo/prog/lpt2d/evaluation/)
  Fidelity comparison and timing measurement.
- [CLAUDE.md](/home/holo/prog/lpt2d/CLAUDE.md)
  In-tree contributor and agent guide.
- [OPTIMIZATION_LOG.md](/home/holo/prog/lpt2d/OPTIMIZATION_LOG.md)
  Canonical performance history and retained optimization lessons.

## Documentation Rules

- Keep it current.
- Prefer durable facts over planning prose.
- Delete superseded docs instead of letting them rot.
- Do not keep standalone resolved-bug notes, dated discussion transcripts, or
  one-off research dumps once their durable conclusions have been folded into
  the canonical docs, examples, tests, or optimization log.
- Put unscheduled future work in one place instead of spreading it across
  multiple roadmaps, prompts, or review checklists.
