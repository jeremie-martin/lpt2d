# Ideas And To-Dos

This file is the single parking lot for unscheduled follow-up work.

It is not a roadmap and it is not a promise. It exists so future ideas stay in
one place instead of spreading across multiple planning docs.

## Near-Term Cleanup

- Tighten `anim.__init__` into a smaller author-facing surface and move
  advanced analysis/report types to explicit submodule imports.
- Keep trimming broad mixed-role modules when the result removes code and
  reduces coupling rather than just redistributing it.
- Continue include and dead-code cleanup after the recent structural changes.

## Physics And Renderer

- Strengthen medium semantics for nested media, touching solids, and other
  cases where the current surface-boundary model becomes ambiguous.
- Expand physics verification alongside that work so harder optical claims are
  defended by tests, not only by plausible renders.

## Expressiveness

- Revisit advanced geometry and composite optics once the deeper medium model
  is in place.
- Only add new lights, materials, or higher-level optical systems when they
  unlock reusable scene families rather than one-off novelty.

## Workflow

- Improve animation-level fluency between GUI inspection and Python authoring.
- Grow the GUI toward better animation-aware preview and inspection only when
  that work clearly strengthens the authoring loop.

## Ongoing Discipline

- Keep benchmark discipline active while feature work continues.
- Keep the canonical example pack small and use it as a pressure test for new
  API and workflow ideas.
