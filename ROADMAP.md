# Roadmap

*Revised 2026-04-05. Replaces the first-generation roadmap after its core Foundations, Expressiveness, and Workflow phases were largely shipped.*

**Project identity:** A physically accurate 2D spectral light path tracer built to make it effortless to create large quantities of beautiful animations procedurally in Python. Physical accuracy is non-negotiable, but it serves aesthetics rather than education. The renderer matters, but the real product is the whole authoring experience: Python API, JSON scenes, GUI exploration, and the workflow that connects them.

---

## What This Roadmap Is For

This roadmap is about defining **what the project should become next** and **why those directions matter**. It is not meant to lock in implementation details too early.

The first roadmap mostly made the engine capable. The next roadmap should make the tool **coherent**, **pleasant to author with**, and **trustworthy enough to support more ambitious optics** without becoming confusing or fragile.

The ordering below reflects that priority. Phase 1 has now shipped as the
strict authored-v5 baseline, and Phase 2 is intentionally the roadmap’s
detailed next phase and current center of gravity:

1. first, make authored scenes easier to identify, address, reuse, mutate, and understand
2. then, make visual iteration much stronger, since look development and clutter remain major friction
3. then, reduce structural ambiguity and unnecessary complexity in the tool itself before deeper capability work
4. then, deepen the physical model where it risks becoming the next real limitation

Performance remains important, but it should stay a permanent engineering discipline guarded by benchmarks rather than a roadmap phase for now. If throughput becomes the dominant pain again, it should be promoted back into explicit roadmap structure.

---

## Phase 0 — Consolidated The New Baseline

Status: shipped on 2026-04-05. This phase remains here as the baseline that
sets up the rest of the roadmap.

### 0.1 Retire stale project stories

Some repo guidance reflected the old `clean_room` era and the previous
foundations roadmap. That cleanup was the last step needed before the next
chapter of work could become legible.

**What we now have:** the docs, examples, and roadmap make it explicit that the
project has already crossed the “missing core primitives and workflow basics”
stage and is now solving a different class of problems. The repo now clearly
distinguishes:
- a canonical public example surface
- the built-in scene set that still drives runtime discovery and benchmarks
- secondary exploratory material that is no longer the public face of the tool

### 0.2 Define a compact canonical example pack

The roadmap should not be driven by a giant example library. It should be
driven by a **small canonical set** of scenes and animations that pressure-test
the tool honestly.

**What we now have:** a dedicated top-level canonical example surface with a
fresh first pack, not a relabeling of older exploratory scripts. The initial
pack is workflow-first and compact: procedural-from-scratch,
builder/composition, and load-modify-animate. It is not a content-production
phase; it is the proving ground for the later phases.

### 0.3 Keep the guardrails alive

The project already has valuable benchmark and render-based regression
infrastructure. That must remain active throughout the roadmap.

**What we now have:** physics tests, workflow tests, and benchmark discipline
staying in place while the authored-scene model evolves. The built-in scene set
remains stable enough to support `benchmark.sh` as the general performance
snapshot workflow, while focused optimization work continues to use
`bench/bench.sh`. Render artifacts remain out of scope for this phase.

---

## Phase 1 — Authoring Coherence

Status: shipped on 2026-04-05. This phase is now the authored-scene baseline
for the repo.

The engine is now strong enough that the main weakness is no longer “missing
core rendering features.” The main weakness that this phase closed was
authored-scene coherence.

**What we now have:** built-in scenes, benchmark scenes, canonical examples,
the GUI save path, the CLI, the C++ core, and the Python API all operate on one
normalized authored model: stable ids, named materials, and strict v5 shot
JSON. The repo no longer carries committed pre-v5 assets, legacy `root_*`
entity ids, or fallback authored-format stories.

### 1.1 Stable authored identity across Python, JSON, and GUI

**Problem:** groups are addressable, but most of the rest of a scene still behaves like anonymous list data. Loading an existing scene and modifying it procedurally can still require brittle index scanning, type checks, or structural inference.

**What we want:** shapes, lights, groups, and other authored entities should carry stable authored identity across all surfaces of the tool. They should be easy to address precisely because they remain identifiable and meaningful as scenes move between Python, JSON, and GUI. A scene should feel like an authored structure the user can reason about, not just a bag of arrays.

This matters because the tool is supposed to support:
- creating scenes from scratch in Python
- loading scenes from JSON and animating or modifying only parts of them
- moving fluidly between GUI exploration and procedural authoring

### 1.2 First-class material workflows

**Problem:** materials exist, but they do not yet feel like a fully coherent authored system. Reuse, editing, and bulk updates still feel more fragile and indirect than they should.

**What we want:** materials should become first-class authored assets in the project’s mental model. Reusing a material should feel intentional. Editing a material should feel predictable. The GUI, Python API, and JSON format should all tell the same story about what a material is and how it is shared.

This is important not just for neatness, but because optical scenes are heavily shaped by material identity: glass families, mirror families, emissive families, and deliberate variation all need a cleaner workflow than ad hoc copying.

### 1.3 Composition-driven Python API

**Problem:** builders are much better than before, but example code can still carry too much custom layout math and too much one-off scene surgery. That means the tool is still not extracting enough reusable structure from the kinds of animations it is already good at.

**What we want:** scene composition in Python should become more reusable, more declarative, and more pressure-tested by real animation authoring. Reusable motifs, parameterized templates, composition helpers, and cleaner load-modify-animate flows should emerge from actual use rather than from abstract API design.

The goal is not to add abstraction layers for their own sake. The goal is to make common animation-building patterns feel natural and short.

### 1.4 One coherent authored language

**Problem:** even if scene entities become identifiable and addressable, the project can still feel fragmented if Python, GUI, and JSON present mismatched concepts, names, or expectations.

**What we want:** a scene explored in the GUI, saved to JSON, loaded in Python, modified procedurally, and rendered again should preserve the same concepts and mental model all the way through. This is about conceptual consistency of the whole tool.

This phase is the one that should make the project feel meaningfully more mature.

### 1.5 Round-trip and migration confidence

**Problem:** once authored identity, shared materials, and richer scene relationships become more explicit, casual format evolution becomes more dangerous. Round-trip and migration confidence are not background maintenance here; they are part of making the authored model trustworthy.

**Decision:** the project is now strict v5-only for authored shot JSON. Older
authored versions are rejected by the loaders. The repo does not keep fallback
readers, fallback writers, or compatibility branches for pre-v5 shots.

**What we now have:** authored-scene evolution is treated as an explicit
repo-wide migration problem rather than an indefinite backward-compatibility
story. When the scene model changes again, the expectation is to migrate the
repo assets, tests, and docs together so meaning stays intact across
save/load/edit cycles without dragging old authored formats forward forever.

---

## Phase 2 — Visual Iteration

Once authored scenes are more coherent, the next bottleneck is the creative loop itself: making scenes readable, balanced, and beautiful without trial and error, and comparing alternatives with confidence.

### 2.1 Shot-wide look development

**Problem:** look development remains one of the most time-consuming parts of authoring. The current auto-look work is a strong first step, but it is still mostly about finding a plausible look from sampled frames.

**What we want:** look development should work at the level of a shot or animation, not just isolated frames. Exposure, tonemap, normalization, and related choices should hold together across time. The tool should help the author compare candidate looks across representative frames or scene states and choose one that is not only good, but also stable.

### 2.2 Clutter diagnostics

**Problem:** a dense optical scene can become visually confusing very quickly. Too many refractive elements, too much absorption, or too many overlapping contributions can turn a promising idea into something unreadable, and the tool still does too little to explain why.

**What we want:** the tool should help explain clutter instead of merely rendering it. It should become easier to understand:
- where the energy is coming from
- where it is being lost
- which lights dominate the frame
- which structures are helping or hurting legibility
- why a scene has become muddy, dark, or visually incoherent

It should make the tool better at both debugging hard scenes and improving artistic readability.

### 2.3 GUI as an exploration and comparison tool

**Problem:** the GUI is already useful, but its strongest long-term value is still underdeveloped: being a fast place to explore looks, clutter, balance, framing, and scene comprehension before returning to Python.

**What we want:** the GUI should become a stronger companion for visual iteration. It should help with exposure decisions, readability, scene inspection, comparing looks, comparing scene states, comparing diagnostic views, and experimentation. It should remain grounded in the same authored concepts as Python rather than becoming a disconnected side tool.

### 2.4 Focused polish that directly helps iteration

This is the right phase for light polish that directly supports look development.

**What we want:** small additions such as vignette or other tightly scoped iteration aids can move forward here when they genuinely help the core iteration loop. Broader aesthetic surface area should still wait.

This phase should feel successful when trying, comparing, and understanding alternative looks becomes materially faster and less guess-driven.

---

## Phase 3 — Structural Cleanup Before Deeper Semantics

After visual iteration, the next risk is not a missing-physics problem alone.
It is the amount of duplicated meaning and mixed responsibility now
accumulating inside the tool.

The project is no longer mainly suffering from absent fundamentals. The more
immediate structural risk is that the same authored ideas now have to move
through Python scene types, JSON and stream formats, CLI and GUI override
paths, C++ runtime structures, diagnostics, and render helpers. The codebase’s
structural problem is less class proliferation than fragmented ownership and a
few oversized coordination surfaces that silently span several conceptual
layers. The GUI app is one visible concentration of that problem, but it is
not the whole of it.

This phase exists to keep the tool coherent before deeper physical semantics
add more state and more meaning. It should stay problem-led. The point is not
to freeze one refactor plan, but to make explicit where the current structure
is becoming harder to evolve safely.

### 3.1 Give the scene language clearer ownership

**Problem:** shapes, lights, materials, ids, transforms, bounds, validation
rules, selection-facing behavior, and diagnostic meaning are increasingly being
taught to multiple parts of the system separately. The same authored concepts
are being re-expressed across Python model code, the C++ core, serializers,
editor behavior, render helpers, and GPU-preparation paths. Local scene-model
changes therefore risk becoming repo-wide synchronization work.

This is not only a parsing issue. It includes the repeated per-kind handling
that now shows up around transforms, bounds, emission behavior, selection
semantics, diagnostics, and related authored rules. That repetition is
especially visible in editor-facing code, but it is not confined there.

**What we want:** the project should have a much clearer sense of where
scene-language meaning lives. Evolving a shape kind, a material rule, or an
identity rule should not feel like updating a stack of parallel
interpretations and hoping they still agree.

### 3.2 Clarify the boundary between authored shots, transient render directives, and runtime state

**Problem:** saved authored shots, session defaults, editor-only filters,
comparison snapshots, resolved runtime settings, CLI overrides, streaming
directives, and per-frame render controls are now close enough in shape to
look like one concept while still doing materially different jobs. Some
authored-facing types are starting to carry extra protocol meaning just to
support transient override behavior, and some render paths now hide more
normalization, override, and serialization work than their public shape
suggests.

That makes the project harder to explain and easier to couple in the wrong
places. It also makes future semantics work riskier, because more physical
meaning will have to travel through these same blurred boundaries.

**What we want:** authored documents, temporary render/session directives,
editor-only transient state, and internal runtime state should feel clearly
distinct in the project’s mental model. The path between them should be easier
to reason about, and transient render or editor behavior should not quietly
muddy the meaning of authored concepts.

### 3.3 Reduce dependence on oversized mixed-role modules

**Problem:** several important parts of the codebase now combine too many jobs
at once. Data modeling, normalization, serialization, transport/wire concerns,
diagnostics, render orchestration, workflow helpers, and UI control flow can
become concentrated in a few large surfaces or single entrypoints instead of
being expressed as clearer subsystems. The structural problem is less “too
many layers” than “too much hidden layering inside a small number of broad
modules.”

That makes the code harder to read, harder to test in isolation, and easier to
disturb accidentally with collateral edits. It also makes the real dependency
structure harder to see, because large control surfaces can look simple from
the outside while quietly coordinating many unrelated responsibilities.

**What we want:** the codebase should rely less on broad coordination surfaces
that silently own several conceptual layers at once. Authored-scene
operations, protocol concerns, diagnostics, render orchestration, and
higher-level workflow logic should be easier to locate and easier to evolve
without cross-cutting incidental churn.

### 3.4 Keep the Python authored surface concrete rather than mechanically overloaded

**Problem:** the Python API is the primary authored surface, but it is now
carrying a growing mix of scene model objects, sparse override behavior,
report types, render wrappers, and analysis helpers. Even when each piece is
individually justified, together they risk making the Python layer feel more
abstract and indirect than the actual authored concepts it is supposed to
expose.

This is especially risky because Python is supposed to be the clearest place
to understand the tool. If authored concepts, transient override semantics,
and analysis plumbing stop feeling separable there, the main user-facing
surface starts to inherit the most accidental complexity.

**What we want:** the Python layer should remain the most conceptually direct
part of the project. Its types and helpers should continue to map cleanly to
real authored structures and real workflow needs, rather than accumulating
machinery that obscures where authored meaning ends and transient control
behavior begins.

### 3.5 Make GUI/editor evolution less dependent on one broad mutable control surface

**Problem:** the GUI is strategically important, but its implementation can
become the next source of drag if scene operations, selection mechanics,
transforms, filtering, diagnostics, export logic, comparison workflows,
undoable editing, and presentation remain too tightly coupled through broad
shared mutable state. Index-based selection and repeated per-kind editor logic
also make local changes more fragile than they should be, because small UI
adjustments can end up depending on unstable addressing rules and several
parallel interpretations of the same scene concepts. When those responsibilities
blur together, even the meaning of an authored edit versus a transient session
or view change becomes harder to reason about.

This matters because the GUI is no longer a side tool. It now participates
directly in the authored workflow and in the project’s understanding of
scenes, looks, and structure.

**What we want:** the GUI/editor layer should be easier to extend without
routing every change through one oversized control surface. Rendering
concerns, editor state transitions, authored-scene operations, selection
addressing, transient view/filter state, diagnostics, and presentation should
feel more legible as distinct responsibilities. The GUI should remain an
important part of the authored workflow without becoming the place where
structural fragility accumulates fastest.

### 3.6 Keep diagnostic and analysis meaning coherent across the tool

**Problem:** clutter diagnostics, source-contribution analysis, structure
contribution, and related interpretive features are now important enough that
they can become their own coherence problem. If Python, GUI, and core code
each grow adjacent but not identical diagnostic stories, the tool will start
explaining the same scene in multiple subtly different ways.

This is especially dangerous because those features are not just technical
aides anymore; they influence author judgment. Parallel heuristics that only
resemble one another are not good enough for a tool that is trying to become
more trustworthy.

**What we want:** when the project explains where energy is coming from, why a
shot is muddy, which sources dominate, or what a structure is contributing,
those explanations should come from one coherent project story rather than
from several nearby interpretations.

This phase should feel complete when:
- scene-language meaning has clearer ownership and less semantic drift across
  Python, core, serializers, editor behavior, and diagnostics
- authored shots, transient render directives, and runtime state are easier to
  distinguish and easier to explain, including in GUI-facing workflows
- the main Python and GUI surfaces are easier to extend without pushing more
  unrelated work through broad mixed-role control points
- diagnostics and analysis feel coherent across the whole tool rather than
  duplicated in adjacent forms
- deeper physical semantics can land without first requiring another round of
  structural untangling

---

## Phase 4 — Deeper Physical Semantics

After the authoring and iteration loop is stronger, the next foundational question becomes: what kinds of optics can the renderer model honestly before its physical simplifications start to become the limiting factor?

This phase is specifically about nested media, touching media, and other scenes where medium boundaries become ambiguous under the current model.

### 4.1 Stronger medium semantics

**Problem:** the current model is already good enough for many scenes, but it risks becoming the next invisible ceiling as scenes become more ambitious. There is a difference between “looks convincing in many cases” and “has a clear physical meaning in harder cases.”

**What we want:** the renderer should support a deeper, more trustworthy understanding of optical media than a simple surface-boundary worldview. More complex medium interactions should have a clear and defensible interpretation.

This matters because otherwise the project may become *more expressive while becoming less trustworthy*, which would conflict directly with its identity.

At the authored-scene level, success means authors can build nested-glass, touching-solid, and similarly ambiguous boundary scenes and rely on them to behave consistently rather than only working by accident.

### 4.2 Physical safety for seductive scenes

The more advanced and beautiful the scenes become, the more dangerous it is for the renderer to be physically wrong in ways that are not obvious.

**What we want:** the project should be safe to use for more complex optics without quietly producing scenes that are attractive but physically incoherent underneath.

This is about guarding against plausible-looking but wrong results: incorrect medium assignment, impossible enter/exit behavior, or subtly broken energy behavior in scenes that still render beautifully enough to fool the author.

### 4.3 Expand physics verification accordingly

As the physical model deepens, the validation must deepen too.

**What we want:** richer render-based physics tests that defend new correctness claims with the same spirit as the existing Snell, dispersion, and optical-setup tests.

This phase should come **before** reopening more seductive advanced geometry, not after. It should feel complete when those harder medium-boundary cases have explicit semantics the project can defend with tests.

---

## Phase 5 — Advanced Expressiveness

Only after the physical foundations above are stronger should the roadmap reopen major expansion of the scene language.

### 5.1 Advanced geometry and composite optics

Ideas like CSG, more powerful composite shape systems, and richer constructive optics can be very valuable, but they should land on top of a stronger authored model and a stronger physical model.

**What we want:** advanced geometry that actually expands what kinds of animations can be made, rather than merely adding impressive-sounding surface area.

### 5.2 High-value new expressive systems

The next wave of expressive features should be chosen for the animation families they unlock.

**What we want:** new lights, materials, or higher-level optical constructs should only move forward when they clearly enable scene families the project genuinely wants to make. If a proposed feature cannot name those scene families concretely, it should wait.

### 5.3 Reuse over sprawl

This phase should continue the discipline of extracting reusable motifs from real work instead of accumulating disconnected features.

**What we want:** the scene language becomes richer without becoming messy, and each addition earns its place by unlocking reusable families of scenes rather than one-off novelty.

---

## Phase 6 — Studio Workflow

This is the long-term destination rather than a near-term commitment.

### 6.1 Animation-level GUI/Python fluency

Once scene-level coherence exists, the remaining long-term gap is animation-level workflow between the GUI and Python authoring workflows.

**What we want:** authors should be able to move more fluidly between GUI-based inspection and exploration of animations and Python-based animation authoring, with parameter discoveries and workflow intent carrying naturally between them.

### 6.2 Animation-aware GUI

The GUI is already essential for scene exploration. In the long run, it can become more than that.

**What we want:** the GUI gradually evolves from scene editor toward lightweight animation tool: able to inspect animations, preview them intelligently, expose animation-specific controls, and eventually support more interactive editing of animated parameters.

### 6.3 Long-term studio vision

Timeline- and keyframe-oriented editing belongs here, after the earlier phases make that kind of workflow worth building properly.

---

## Ongoing Tracks

These are important, but they should remain cross-cutting rather than becoming
roadmap phases unless one of them clearly becomes the dominant bottleneck.
Strict migration discipline should also remain active after Phase 1 as the
authored model continues to evolve.

### Performance discipline

The benchmark harness and optimization work should not go to waste.

**What we want:** feature work should not casually regress throughput, and performance opportunities should continue to be explored carefully. But performance should not dominate the roadmap unless it clearly becomes the project’s main bottleneck again.

### Canonical examples as pressure test

The compact canonical example pack defined in Phase 0 should keep shaping decisions throughout the roadmap.

**What we want:** if a planned change does not make the canonical examples cleaner, clearer, more reusable, or more beautiful, it should be questioned.

---

## Design Constraints

- **Physical accuracy is non-negotiable.** The project exists to make beautiful animations, but it must do so through physically correct optics rather than visual fakery.
- **API convenience is king.** The Python API is the primary authored surface. If common scene-authoring tasks remain awkward, the design is not done.
- **One cohesive tool.** Python, JSON, and GUI must feel like parts of the same system, not parallel worlds with mismatched concepts.
- **Authoring concepts must stay consistent across layers.** The core scene model, renderer layer, JSON format, GUI, and Python API should all agree about what entities exist and how they behave.
- **Render-based validation matters more than abstract confidence.** The strongest tests in this project are scenes with known physical behavior and measurable expected outcomes.
- **Performance stays under discipline.** Feature work must respect the benchmark harness and avoid casual regressions, even when performance is not the active roadmap focus.
- **Pragmatic evolution over premature freezing.** The format and API should keep evolving where necessary, but changes should remain understandable, testable, and recoverable.
- **Clean, simple, minimal implementation.** The roadmap defines *what* to build, but every phase assumes the same implementation standard: easy to read, easy to maintain, easy to evolve, and free of unnecessary abstraction or complexity.
