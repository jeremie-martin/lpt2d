# Seed Mode

`seed_mode` is an authored trace setting with two values:

- `deterministic`
- `decorrelated`

The default is `deterministic`.

## Why It Lives In `Shot.trace`

Seed behavior changes the meaning of a render over time. A user who saves a
shot and reopens it should get the same frame-to-frame seed policy in the GUI,
CLI, Python, and export paths. That makes it authored trace intent, not a
frontend-only toggle and not hidden renderer session state.

The authored shot stores `seed_mode`. The runtime render call separately
provides `frame_index`.

## Why `frame_index` Is Runtime-Only

`frame_index` is not part of the authored document. It is render context:

- Python animation renders derive it from the timeline frame
- CLI can accept it explicitly
- GUI preview/export can point at a chosen frame number

Persisting `frame_index` in shot JSON would mix timeline position into authored
trace defaults and would make static shots carry accidental runtime state.

## Decorrelated Semantics

`decorrelated` means:

- keep the renderer's existing per-dispatch seed progression
- add a stable salt derived from `frame_index`

This gives:

- different noise from frame to frame
- repeatable frame `N` across separate executions
- the renderer as the only source of truth for actual GPU seed derivation

It does not use session entropy, wall-clock time, or ad hoc GUI-only reseeding.
