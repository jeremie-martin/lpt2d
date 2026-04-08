# Outline Join Discussion Log (2026-04-08)

This file preserves the discussion that led to
[OUTLINE_JOIN_SEMANTICS.md](/home/holo/prog/lpt2d/docs/OUTLINE_JOIN_SEMANTICS.md).

It is a conversation record, not the canonical design contract. The canonical
reference is the semantics document. This file exists to preserve the context,
questions, examples, and reasoning that led to that model.

## Starting Point: The Concave Thick-Arc Problem

### User

Smooth shading was confirmed visually in the GUI. Reflection bands disappear on
the convex side of a thick arc, but they still appear on the concave inner
side. The question was why that behavior exists, what design logic is behind
it, and how to think about it in a way that protects the quality of the engine
instead of applying a quick local fix.

### Assistant

The current behavior is deliberate. The implementation excludes concave polygon
vertices from smooth-normal generation. The important point is that the current
feature is a conservative shading heuristic, not a general "recover any smooth
curve from any polyline" system.

For convex corners, interpolating adjacent outward normals is a defensible
approximation of a rounded exterior surface. For generic concave corners, the
same operation is much more ambiguous: it starts making rays behave as if there
were an inward fillet or cavity that the actual geometry does not contain.

The thick arc is the counterexample: its inner chain is concave topologically
but is still semantically intended as a smooth curve. The current heuristic
cannot distinguish "sampled inner arc" from "real hard notch."

The immediate design reading was:

- do not globally remove the concave check just to make the demo work
- keep the current rule as a safe default
- introduce a way to express intended surface continuity explicitly
- treat thick arcs as a strong example of why the engine needs that concept

The deeper long-term possibility raised was that if thick stroked curves become
central, a native stroked-curve or offset-path shape would likely be cleaner
than making polygons carry all that meaning.

## Step Back: What Is A Shape Supposed To Mean?

### User

The conversation should step back completely before discussing solutions.
Rather than immediately talking about polygons, concavity, or implementation,
the goal was to clarify what the engine is really trying to achieve at a high
level.

### Assistant

The discussion was reframed around the question:

- should the renderer follow the literal polyline that was authored?
- or should it follow the smooth surface the author meant, with the polyline
  serving only as an approximation?

The current polygon is doing too many jobs at once:

- boundary geometry
- approximation of another intended surface
- shading continuity carrier

The thick-arc case exposes the conflict. Topologically the inner side is
concave. Semantically it is still part of one smooth manufactured surface. The
current implementation chooses topology over author intent.

Three broad directions were laid out:

1. Literal-geometry model
   A polygon means exactly its edges. Smooth shading is only a narrow
   convenience heuristic.

2. Intent-first surface model
   A polygon may approximate a smooth surface even in concave regions if the
   author says so.

3. Semantic-primitives model
   Polygons stay literal. More meaningful higher-level shapes such as thick
   arcs, stroked curves, offset paths, and filleted profiles become first-class
   primitives.

The assistant's bias was toward `3`, possibly with some `2` as a bridge.

## User Intuition: "If I Ask For Smooth, Why Is Only Part Of The Object Smooth?"

### User

The user's intuition came from Blender-like tools. When smooth shading is
applied to an object, it feels natural to expect that the object will be smooth
as a whole rather than only on convex regions. The current result feels
inconsistent because smooth shading is being asked for globally, yet the
concave side still behaves as flat-shaded.

The user also questioned whether the distinction being drawn was actually
fundamental, or whether it reflected engine limitations rather than a real
modeling truth.

### Assistant

That intuition was validated as legitimate. The tension is real: the user's
mental model is based on surface intent, while the current implementation is
based on topology.

The assistant then clarified an important distinction specific to lpt2d:

- in a DCC viewport, smooth shading is often visual
- in this engine, the shading normal affects reflection and refraction

So the design cannot be treated as merely a cosmetic rasterization issue. The
questions become:

- what is the actual hit geometry?
- what normal is used for the bounce?
- what did the author mean the surface to be?

The assistant introduced a distinction that proved important later:

- optical smoothness: keep polygonal geometry, smooth the normals
- true geometric smoothness: represent an actual curved boundary

The argument was that these must not be blurred together.

## The Higher-Level Product Goal

### User

The user clarified that the goal was not "better polygon smoothing" in
isolation. The goal is to make it possible to author arbitrary 2D solid shapes
cleanly and robustly:

- a sword
- a knife
- a leaf
- a flower
- water or other fluid-like silhouettes

Some regions should be straight, some smooth, some hard, some rounded. The
result should look good under reflection and other optical effects. The user
does not want faceting artifacts or brittle engine-specific rules to leak into
the experience.

The user also pointed out that mixed curve-and-line outlines will likely be
needed in the long term.

### Assistant

That product framing was accepted as the real target.

The assistant proposed that the missing concept is not "concave smoothing" but
"surface continuity intent." Convexity is merely a heuristic for one aspect of
that intent. It is not the concept itself.

The assistant also defined "continuity" more concretely:

- hard join: direction changes abruptly and the normal should jump
- smooth join: the surface should read continuously across the join
- fillet/bevel: the corner is actually replaced by new rounded geometry

This formulation became the foundation for the rest of the discussion.

## Example-Driven Questions

### Assistant

To get away from abstract debate, the assistant proposed concrete examples:

1. Thick `C`
   Should both curved runs be smooth while end caps stay hard unless explicitly
   beveled?

2. Star shape
   Should inward notches remain hard even if smooth shading is globally enabled?

3. Sword outline
   Should some joints be marked hard and some smooth, or should mixed curves and
   lines be enough on their own?

4. Leaf outline
   Should it mostly be one smooth boundary, perhaps with only a few special
   joins?

5. Serrated blade
   Should the body smooth while the teeth remain sharp?

### User

The user worked through these examples and, while still uncertain on some
details, started converging on a structure:

- for a thick `C` built from polygonal geometry, the cap joins should stay hard
  if the geometry is hard
- if geometry is really rounded, then the join should be rounded because of the
  geometry, not because shading fakes it
- smooth shading and rounded corners are separate concepts
- the question is not whether everything should simply become smooth

The user also started to entertain the possibility that some of the intuition
about "hard edges from geometry alone" might come from confusing smooth shading
with subdivision workflows.

## Blender Comparison: Shade Smooth, Auto Smooth, Mark Sharp, Support Geometry

### User

The user recalled Blender workflows where:

- global smooth shading can be applied
- specific edges can be marked sharp
- auto smooth can infer sharpness from angle
- support loops or extra cuts can change the behavior under subdivision

The user asked whether something like Blender's model would make sense for
lpt2d, while explicitly wanting the conversation to stay conceptual rather than
turn into implementation planning.

### Assistant

The assistant separated two Blender mechanisms that had been mixed together:

1. Shade Smooth / Auto Smooth / Mark Sharp
   This changes the shading normals.

2. Support loops / extra cuts / subdivision shaping
   This changes the geometry produced by a subdivision scheme.

That distinction turned out to be critical.

The assistant answered the central question directly:

- if smooth-normal interpolation is applied globally, truly hard edges do not
  remain hard just because more vertices are added around the same corner
- a hard edge is preserved either by a normal discontinuity (`sharp`) or by
  changing the geometry (`bevel`, `fillet`, `chamfer`, support geometry, etc.)

From that came the clean separation:

- `smooth` = shading continuity
- `sharp` = shading discontinuity
- `rounded` = geometric continuity

The assistant also agreed strongly with the user's instinct that "smooth" and
"rounded" must remain separate, and pointed out that the current GUI already
partly reflects that separation because `smooth_angle` and `corner_radius` are
distinct controls.

## The Breakthrough: Hard Edges Are Real Authored Intent

### User

This was the turning point of the conversation. The user explicitly recognized
that in their previous mental model, "hard edges" had not been treated as a
real authored concept; they had been treated as something geometry could always
fake.

The user then acknowledged that Blender's model of:

- smooth shading
- auto smooth
- mark sharp

probably maps much better to what is actually needed here.

The user also made an important clarification:

- when saying "smooth" in this context, the user meant smooth shading,
  i.e. normal interpolation
- rounded corners / bevel fillets are a separate and already meaningful
  geometric feature

### Assistant

The assistant confirmed that convergence and proposed the key conceptual shift:

- the engine should be organized around `join intent`, not `convex` vs
  `concave`

The right authored object is not really the segment or the vertex in isolation,
but the `join`:

- for polygons, the join is a polygon vertex
- for future mixed paths, the join is the node between adjacent segments

That led to a cleaner glossary:

- `segment`: one boundary piece
- `join` or `node`: where two boundary pieces meet
- `smooth` / `sharp`: shading continuity behavior across the join
- `rounded`: geometric replacement of the join

The assistant proposed a model with:

- `auto smooth` as a per-shape default inference rule
- explicit per-join overrides such as `sharp` and `smooth`
- separate rounded geometry controls

The assistant also explicitly pointed out that the current engine's convexity
rule is only a heuristic and not the real concept.

## Concrete Expected Behaviors

### Assistant

The assistant then translated the model into expected examples:

- square + smooth shading should not become geometrically rounded
- square + angle-based auto smooth should stay sharp by default
- segmented thick `C` + auto smooth should smooth both curved chains while cap
  joins stay sharp
- any join can later be manually forced sharp or smooth

The assistant asked whether the following conceptual join modes matched the
user's emerging model:

- `auto`
- `sharp`
- `smooth`
- `rounded` as a separate geometric operation

### User

The user explicitly answered "Yes."

That "yes" effectively locked the conceptual model.

## Final Convergence

### Assistant

Once the user agreed, the assistant summarized the result:

- the engine should center its semantics on join intent
- `auto | sharp | smooth` should govern shading continuity
- `rounded` should remain a separate geometric operation
- polygons should remain literal line-segment geometry
- long-term, the engine should support closed outlines made from mixed line,
  arc, and bezier segments

This was framed not as an implementation plan but as the actual modeling
contract the engine should aim to express.

### User

The user agreed strongly and asked for a durable reference document that:

- explains the scope and context
- captures where the engine is today
- states where it wants to go conceptually
- can later serve as a reference when checking whether the engine matches the
  intended model

### Assistant

That request led to the creation of the canonical design reference:

- [OUTLINE_JOIN_SEMANTICS.md](/home/holo/prog/lpt2d/docs/OUTLINE_JOIN_SEMANTICS.md)

## Discussion Outcome

The high-level result of the discussion is:

- the current convexity-gated polygon smoothing is defensible as a safe
  heuristic, but it is not the right conceptual foundation
- hard edges are real authored intent
- smooth shading and rounded geometry are distinct concepts
- the correct semantic unit is the join
- future work should be judged against a join-centered model, not against local
  polygon convexity alone

## Canonical Follow-Up

The normative outcome of this discussion lives in:

- [OUTLINE_JOIN_SEMANTICS.md](/home/holo/prog/lpt2d/docs/OUTLINE_JOIN_SEMANTICS.md)

If this discussion log and the reference doc ever drift, the reference doc
should be treated as canonical.
