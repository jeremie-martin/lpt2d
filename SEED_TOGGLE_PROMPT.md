# Seed Toggle Prompt

Implement a clean shared-core toggle for ray-seed behavior across frames.

Context:
- Current behavior is deterministic.
- A temporary hardcoded randomization experiment was removed.
- GUI, CLI, and Python should all use the same core behavior.

Requirements:
- Support two modes: deterministic across frames, and decorrelated across frames.
- Put the setting in the right shared abstraction and be explicit about why.
- Keep the core renderer as the single source of truth.
- Expose the setting consistently through C++, CLI, Python, and GUI.
- Preserve deterministic as the default unless there is a strong reason not to.
- Avoid frontend-specific hacks and avoid threading ad hoc booleans everywhere.
- Add tests and update docs/help text where needed.

Questions to resolve:
- Should this live in authored shot state, runtime render state, or session state?
- Should decorrelated mean per-frame reseeding only, or per-dispatch reseeding too?
- Should preview and export share the same explicit setting?

Deliverables:
- Code changes
- Wiring across interfaces
- Tests
- A short design note explaining the choice and tradeoffs
