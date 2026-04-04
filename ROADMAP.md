# Roadmap

*Revised 2026-04-04. Replaces the original feature-checklist roadmap (now fully shipped).*

**Project identity:** A physically accurate 2D spectral light path tracer built to make it effortless to produce large quantities of beautiful animations procedurally in Python. Physical accuracy is non-negotiable — it serves aesthetics, not education.

---

## Phase 0 — Housekeeping

Archive the `anim/examples/clean_room*` library and `renders/clean_room/` tree. These 1000+ scenes were a proof-of-concept on the old primitives. New examples will be built on the new foundations.

Keep: `orbiting_beam.py` (canonical example), `anim/` library code, `scenes/*.json` (built-in shots).

---

## Phase 1 — Foundations

The engine works, but the abstractions have gaps. Fix them before adding more surface area.

### 1.1 Fix emission model

**Problem:** Setting `emission > 0` on a shape should make it glow naturally from its surface — like a neon tube or an incandescent surface. Instead, the current system places a single point light at the shape's center, which makes emissive segments appear one-sided and emissive circles emit from a single interior point rather than their surface.

**What we want:** An emissive shape should auto-generate light sources that match its geometry — light distributed along a segment's length, around a circle's circumference, along an arc, or along each edge of a polygon. The user sets `emission` on a material and the shape just glows correctly. No manual light placement needed.

The existing shader-side emission boost (energy added when rays hit emissive surfaces) stays — it's additive and helps convergence in scenes that also have explicit lights.

### 1.2 Native polygon primitive

**Problem:** The engine thinks in *boundaries* (segments, arcs, circles) but the user thinks in *solid objects* (a glass prism, a mirror block, a lens). Currently, circles are the only shape that naturally acts as a solid — a glass circle refracts light correctly because it's a closed boundary. Making a glass prism requires manually composing 3 segments with exact coordinates and shared materials. It works physically, but it's fragile and unintuitive.

**What we want:** `Polygon` as a first-class shape type across all layers (C++, JSON, Python, GUI). A polygon is defined by its vertices and a material. It represents a solid object — light refracts when entering through one edge and exiting through another, with correct Fresnel/Snell behavior. The user says "glass triangle" and gets a glass triangle.

Also add convenience constructors: `rectangle(center, w, h, material)`, `regular_polygon(n, center, radius, material)` — common shapes shouldn't require computing vertex coordinates by hand.

### 1.3 Physics verification tests

End-to-end integration tests that render known optical setups and verify physical correctness. We know from theory what the output should be — the test renders the scene and checks:

- **Snell's law**: Beam at known angle through glass slab → exit angle must match `arcsin(sin(θ)/n)`
- **Energy conservation**: Total light energy out ≈ total energy in (reflected + transmitted + absorbed)
- **Dispersion accuracy**: White beam through prism → spectral separation must match Cauchy equation
- **Known optical setups**: Lens focusing distance, total internal reflection critical angle, Brewster angle

These tests serve as a safety net: if a shader change or refraction fix breaks the physics, we know immediately and we know exactly which property is wrong.

### 1.4 Look auto-tuning

**Problem:** Getting exposure, tonemap, and normalize settings right is the biggest time sink when iterating on animations. Every scene needs different settings, and there's no systematic way to find them — it's pure trial and error.

**What we want:** A function you call on a scene that gives you back a good-looking `Look`. One call, done. It should analyze the scene's actual light distribution and suggest exposure, normalization reference, and tonemap settings that produce a well-exposed, non-clipping result. This should be fast enough to use as part of the normal iteration loop — not a special step you run separately.

---

## Phase 2 — Expressiveness

New primitives and lights that unlock animations you can't currently make.

### 2.1 Parallel segment beam (beam with width)

The current beam light starts from a single point, which makes it look like a cone rather than a proper laser. People unfamiliar with optics find it hard to read. A beam that starts from a line segment — all rays parallel but originating from different points along a width — would look like a true collimated light sheet. Much cleaner, much more legible, and it's the missing combination between "segment light" (wide source, all directions) and "beam light" (point source, one direction).

### 2.2 Thick shapes

**Problem:** Segments and arcs are infinitely thin boundaries. In a render, you only see them when light happens to bounce off them — the optical elements themselves are invisible. In animations, you often can't tell what's in the scene. A mirror looks like empty space until a ray hits it.

**What we want:** A way to give segments and arcs physical width, turning them into visible solid objects. A thick segment becomes a thin rectangle; a thick arc becomes an annular sector. The user should be able to say "this mirror is 2mm thick" and see it as a real object in the scene.

### 2.3 Ellipse primitive

Elliptical shapes for oval lenses, elliptical mirrors, egg shapes. Center + semi-axes + rotation. Ray-ellipse intersection is a quadratic (same solver as circle, with axis scaling). Opens up elliptical focusing, which creates distinct caustic patterns from circular lenses.

### 2.4 Spot light

Point source with angular falloff — Gaussian or cosine-power profile. Defined by position, direction, cone angle, falloff exponent, intensity. The 2D equivalent of a flashlight or stage spot.

### 2.5 Enhanced Python builders

Common optical elements should be one-liners, not 10 lines of vertex math. This means richer builder functions for things like: glass prisms, mirror blocks with per-face material control, slits and barriers with openings, diffraction gratings, waveguides. The exact API should emerge from real animation authoring needs — these are examples, not a spec.

---

## Phase 3 — Workflow

Make the authoring and iteration loop faster.

### 3.1 Stats pipeline

Lightweight per-frame statistics integrated into the render pipeline:
- **Live metrics**: brightness, clipping %, histogram streamed on stderr during animation renders
- **Quality gates**: define thresholds (clipping < 5%, mean brightness > 0.3); system warns when violated
- **Comparison tools**: A/B render two looks with stats diff

All CPU-side on the readback buffer. Target: < 1% overhead.

### 3.2 Scene load-modify-animate workflow

Make it more ergonomic to load an existing scene and animate parts of it:
- `Shot.load()` already works — ensure it's well-documented
- Add mutation helpers: `shot.with_look(exposure=3)`, `scene.find_group("prism")`
- Animate loaded scenes by mutating specific elements in the callback

### 3.3 Scene debugging tools

- **Light soloing**: Render with only one light source active (isolate contributions)
- **Object visibility**: Toggle shapes/groups on/off without removing them
- **Wireframe overlay**: Show shape outlines in the GUI without rendering rays

### 3.4 GUI improvements

The GUI is essential for scene design exploration:
- Grid snap and alignment guides
- Measurement tool (distances, angles)
- Better visual feedback for selected objects
- Exposure/look presets panel

---

## Phase 4 — Polish

Broader strokes. Tackle when the core is solid.

### 4.1 Post-processing additions
- **Vignette**: darken edges for artistic framing
- **Background gradient**: radial or linear, replacing pure black void
- **Color grading**: hue/saturation/temperature adjustments

### 4.2 More light types
- **Ring/radial light**: point source with angular range
- **Area light with directional bias**: segment light biased toward one hemisphere
- Revisit light types as new scene needs emerge

### 4.3 Advanced primitives
- **Boolean/CSG operations**: union, subtract, intersect shapes to form complex optics
- **Spline curves**: cubic Bezier or Catmull-Rom for smooth freeform boundaries

### 4.4 GUI animation editor (long-term dream)
- Load Python animations in the GUI
- Keyframe timeline
- Modify parameters interactively while previewing animation
- Bidirectional: edit in GUI, export to Python

---

## Design constraints

- **Physical accuracy**: All rendering must be physically correct. No faking effects.
- **API convenience is king**: The Python API is the primary user interface. Optimize for ergonomics. If a common task takes more than a few lines, the API is wrong.
- **Cohesive feel**: The Python API, the GUI, and the JSON format should feel like parts of the same tool. A scene designed in the GUI should be immediately usable in Python and vice versa. Concepts should have consistent names and behavior everywhere.
- **5-layer consistency**: C++ scene.h ↔ GPU structs ↔ GLSL shader ↔ JSON ↔ Python types. Every concept that exists in one layer must be correctly represented in all others.
- **Clean, simple, minimal implementation**: No unnecessary layers of abstraction. No speculative generality. The code should be easy to read, easy to maintain, and easy to evolve. Complexity is the enemy — if an implementation feels heavy, step back and find the simpler design. This is hard but essential.
- **No breaking changes without migration**: When the format evolves, existing scenes must still load (or be auto-migrated).
- **Performance budget**: Stats and analysis features must add < 1% overhead to rendering.
