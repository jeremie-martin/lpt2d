# GUI User Experience

This document examines the current state of the interactive GUI, identifies its
purpose and identity, catalogs the friction points that slow down the core
workflow, and proposes directions for improvement.

It is a living reference, not a specification. Nothing here is committed to a
timeline. Items are tagged with their status:

- **(open)** — not yet addressed
- **(partial)** — partially addressed, description of what was done
- **(done)** — fully resolved

---

## 1. What the GUI Is

The GUI is a **real-time optical workbench**. It is not a scene editor that
renders on demand, nor a render viewer that loads pre-built scenes. The
rendering is the medium: you think by seeing light, and you work by changing
something and watching what happens.

The core interaction loop is:

    change something --> see the light respond --> change something else --> repeat

Every feature in the application either serves this loop or gets in its way.

### Primary workflows

Three concrete use cases, roughly ordered by frequency:

1. **Feature testing and debugging.** After implementing something new in the
   engine (a shape, a material property, smooth shading, corner radii), the GUI
   is the laboratory. The workflow is: place geometry, throw light at it, try
   different materials, observe how the feature behaves under varying
   conditions. Speed matters because you may iterate dozens of times in a single
   session.

2. **Template authoring.** The project's production goal is procedural
   generation of thousands of video variations from a single seed scene. The GUI
   is where that seed gets crafted: checking exposure, placement, material
   choices, composition. Every flaw in the template multiplies across all
   variations, so the authoring session needs to be precise and thorough.

3. **Evaluation and inspiration.** An LLM agent or a Python script generates a
   scene JSON. The GUI loads it so the author can evaluate what works, discover
   what looks good, and feed that insight back into the procedural pipeline.
   This is a read-heavy workflow with quick adjustments to understand the
   generated scene.

### Future directions (not current priorities)

- **Better shape modeling.** Vertex-level editing, edge operations,
  more direct manipulation of polygon geometry. Medium-term.
- **Animation timeline.** Keyframe editing in the GUI. Long-term and low
  priority since the Python API is the primary animation surface.

### What the GUI is not

It is not a precision CAD tool. It is not a tool for producing single finished
images. It is not an animation editor. The Python API and procedural pipeline
handle production output; the GUI handles exploration, testing, and authoring.

---

## 2. Where We Are Today

### What works well

The application has strong foundations that serve the real-time iteration loop:

- **Rendering is always on.** Every change produces immediate visual feedback.
  This is correct and non-negotiable.
- **Modal transforms (G/R/S).** Grab, rotate, and scale with axis constraints
  and numeric input. Fast and familiar to anyone who has used Blender.
- **Single-key tool switching.** Q for select, C for circle, L for segment,
  P for point light, etc. Low-friction creation.
- **A/B snapshot comparison.** Freeze the current state, make changes, toggle
  back. Essential for evaluating whether a change improved the scene.
- **Exposure shortcuts.** `[`/`]` for nudging, `Alt+scroll` for scrubbing.
  The kind of always-available adjustment that makes iteration fast.
- **Escape cascade.** Pressing Escape walks back through nested states
  (path creation, tool mode, group editing, selection) in a predictable order.
- **Alignment guides.** Smart snapping when dragging objects near other
  geometry.
- **Undo/redo.** 200-step history. Reliable.

### Current panel structure

The right side of the screen is a single scrollable column (280px, DPI-scaled)
containing 10 collapsible sections, all open by default:

1. **Scene** -- scene picker, new/save/load/save-as
2. **Edit** -- tool buttons, wireframe/grid toggles
3. **Camera** -- camera bounds, canvas resolution
4. **Objects** -- hierarchical list of shapes, lights, groups
5. **Properties** -- selected object parameters, material binding
6. **Material Library** -- material CRUD, presets
7. **Tracer** -- batch size, depth, intensity, seed mode, frame, pause
8. **Display** -- look presets, A/B comparison, tone mapping, color grading
9. **Output** -- ray count, FPS, export
10. **Stats** -- histogram, luminance metrics

### Keyboard shortcut coverage

| Shortcut            | Action                        | Status     |
|---------------------|-------------------------------|------------|
| Q/C/L/A/B/E/D/...  | Tool switching                | works      |
| G / R / S           | Grab / Rotate / Scale         | works      |
| `[` / `]`           | Exposure nudge                | works      |
| Ctrl+Z / Ctrl+Sh+Z | Undo / Redo                   | works      |
| `` ` ``             | A/B snapshot toggle           | works      |
| Space               | Pause / unpause               | works      |
| H / Alt+H           | Hide selected / Show all      | works      |
| F / Home            | Fit selection / Fit scene     | works      |
| Tab                 | Toggle controls panel         | works      |
| V                   | Wireframe toggle              | works      |
| N / Shift+N         | Material cycle fwd/back       | works      |
| J                   | Join mode cycle (polygon)     | works      |
| Shift+1-6           | Look presets                  | works      |
| Ctrl+Shift+S        | Save As                       | works      |
| Shift+A             | Add menu at cursor            | works      |
| ?                   | Shortcut reference overlay    | works      |

---

## 3. Friction Points

### 3.1 The panel hierarchy problem — (open)

All 10 sections are presented with equal visual weight. When tuning a material,
the Scene, Camera, and Tracer panels are still open and consuming screen space.
When placing lights, the Display panel's 15 sliders are still visible. There is
no notion of "what am I doing right now" and the UI does not adapt.

The consequence is constant scrolling. To go from adjusting a material property
to tweaking exposure, you scroll past Objects, Properties, and Material Library.
In a fast iteration session where you alternate between these constantly, the
scrolling becomes the dominant interaction.

### 3.2 No fullscreen viewport — (done)

Tab toggles the controls panel, giving a fullscreen viewport for evaluation.
`648a1f5`

### 3.3 Corner radius editing is indirect — (open)

Editing per-vertex corner radii on a polygon requires finding the vertex index
in a 180px scrollable table and mentally matching it to the viewport. There is
no way to click a corner in the viewport and adjust it directly.

Planned: viewport-based vertex editing (Phase 3 in the implementation plan).

### 3.4 Join mode editing is indirect — (partial)

J cycles all vertices through Auto/Sharp/Smooth. `648a1f5`

Per-vertex viewport editing (right-click to cycle individual vertices) is
planned for Phase 3.

### 3.5 Too many clicks, not enough keystrokes — (partial)

Addressed: material cycling (N), wireframe toggle (V), look presets
(Shift+1-6), join mode cycling (J), Add menu at cursor (Shift+A),
shortcut reference overlay (?). `648a1f5`

Remaining gaps: light intensity adjustment, individual post-processing sliders.

### 3.6 Viewport zoom and navigation friction — (open)

The `F` (fit to selection) and `Home` (fit to scene) shortcuts exist but are
not always discoverable. No way to toggle between a detail view and the full
scene, or to match the authored camera exactly.

### 3.7 Scene evaluation has no dedicated workflow — (partial)

Addressed: drag-and-drop JSON loading, auto-fit on load, look presets via
Shift+1-6, Save As via Ctrl+Shift+S, improved Load popup (auto-focus, Enter
to confirm, pre-fill path). `648a1f5`

---

## 4. Observations About Usage Patterns

### What a typical session looks like

A feature-testing session might look like:

1. Open a scene (built-in or loaded JSON).
2. Add or modify a shape.
3. Add a light, move it around to see how the shape responds.
4. Try a different material.
5. Tweak exposure to see detail in dark or bright areas.
6. Adjust smooth/sharp settings on the shape.
7. Try corner radii.
8. Change the light position again.
9. Try another material.
10. Repeat steps 3-9 many times.

The dominant pattern is **rapid alternation between different parameter
domains**: geometry, lighting, materials, post-processing. The current UI
treats these as separate panel sections you navigate between sequentially.

### What operations cluster together

Some operations naturally pair and are often done in quick succession:

- Move light + adjust exposure
- Change material + check how light interacts
- Toggle smooth/sharp + adjust corner radius
- Pan/zoom + adjust post-processing to evaluate composition

The UI could benefit from acknowledging these clusters rather than treating
every parameter as an independent panel entry.

---

## 5. Directions for Improvement

### 5.1 Panel management — (open)

**Context-sensitive collapse.** When an object is selected, auto-expand
Properties and collapse less relevant sections (Scene, Camera). When nothing is
selected, keep Display prominent. This does not remove access -- sections stay
manually expandable -- but it reduces the default scroll depth.

**Panel pinning or tabs.** Instead of one long scroll, organize panels into
tabs or allow pinning a few sections to stay visible while others collapse. For
example, a "Look" tab (Display + Output + Stats) vs an "Edit" tab (Objects +
Properties + Material Library) would match the natural workflow clusters.

### 5.2 More keyboard shortcuts — (open)

Remaining candidates:

- **Light intensity adjustment** via scroll or shortcut while a light is
  selected or hovered
- **Post-processing slider shortcuts** for common adjustments beyond exposure

### 5.3 Viewport-based polygon editing — (open)

**Click-to-select vertex.** When a polygon is selected, clicking near a vertex
in the viewport highlights it and shows a small floating widget (or activates
scroll-to-adjust) for its corner radius and join mode. This eliminates the
index-matching problem entirely.

**Edge-click for join mode.** Clicking on a polygon edge (between two vertices)
could toggle or cycle the join mode for that edge's vertices. One click instead
of six.

**Drag handle for corner radius.** When hovering near a convex vertex, show a
radius handle that can be dragged to visually set the fillet size. This would
make corner radius editing feel as direct as moving a circle's center.

### 5.4 Hover-based quick adjustments — (open)

When hovering over a light in the viewport, scroll wheel could adjust intensity
(or a modifier + scroll for wavelength). This avoids navigating to the
Properties panel entirely for the single most common light adjustment.

Similarly, hovering over a shape and using a modifier + scroll could cycle
materials or adjust a primary property.

This pattern turns the viewport into the primary editing surface rather than
just a display.

### 5.5 Viewport navigation improvements — (open)

- **Toggle between authored camera and free view** with a single key, so you
  can quickly check "how does this look at the final framing?"
- **Named view bookmarks** to save and recall viewport positions during
  exploration sessions.
- **Smooth animated transitions** when using Fit (F) or Home, instead of
  instant snaps, to maintain spatial orientation.

---

## 6. Guiding Principles

Whatever improvements are made, they should follow these principles:

1. **The viewport is primary.** The render is the product. Every pixel taken by
   panels is a pixel taken from the actual work. Minimize chrome, maximize
   light.

2. **Speed of iteration above all.** If an improvement adds a feature but
   slows down the common path, it is a net negative. The core loop must stay
   fast.

3. **Direct manipulation over indirect editing.** Clicking a thing in the
   viewport should be the preferred way to edit it. Panels are for precise
   numeric entry and for properties that have no spatial representation.

4. **Progressive disclosure.** Show the most relevant controls for what the
   user is doing right now. Everything else should be reachable but not in the
   way.

5. **Keyboard for flow, mouse for precision.** Frequent toggles and mode
   switches should have shortcuts. Continuous adjustments (sliders, drags) are
   fine as mouse operations.

6. **Don't add complexity to reduce friction.** A simpler panel layout may be
   better than a sophisticated adaptive one. Prefer removing barriers over
   adding new mechanisms.
