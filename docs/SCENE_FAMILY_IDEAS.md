# Scene Family Ideas

A creative brainstorm of new animation-family generators for the `anim/`
Python package, together with the iteration methodology used to take any
one of them from sketch to a shippable family.

This is a design note, not a roadmap. Ideas here are unscheduled and any
of them may be dropped, merged, or reshaped.

## Context

`Crystal Field` is the current reference family. It is a dense hexagonal
lattice of small colored glass objects lit by drifting `PointLight`s,
with a heavy rejection-probe pipeline. It is beautiful but hard to read:
too many glass objects compete for attention and the optical story gets
lost.

The families below move in the opposite direction: fewer, larger, more
legible optical subjects, with the light source treated as the
protagonist of the scene. The engine's `ProjectorLight` (with
`source="line"` or `source="ball"`, configurable spread and profile) is
underused across the current example pack and is the natural hero light
for these compositions.

## Shared Anchors (Lifted Verbatim From Crystal Field)

These are the bits of Crystal Field that should carry over unchanged
unless a specific family needs to depart from them.

- Chamber walls: `metallic=1.0, roughness=0.1, albedo=1.0,
  transmission=0.0`. A soft-edged perfect mirror that scatters light
  across the chamber.
- Look: `tonemap="reinhardx", white_point=0.5, ambient=0.0,
  exposure=-5.0, gamma=2.0, normalize="rays"`.
- Camera bounds: `[-1.2, -0.675, 1.2, 0.675]` (16:9, 3.2 wide).
- Preview render: 640x360, 30fps, 500K-1M rays, depth 10.
- Duration: 5-10s.

## Shared Rules

- One light character per scene: a scene uses either `PointLight`s *or*
  `ProjectorLight`s, never both.
- Prefer prisms, wedges, lenses, and flat glass over spheres. Spheres
  are allowed when a specific family wants a ball lens, but they are not
  the default.
- Per-branch parameters are defined inline, even when values coincide
  across branches. No hoisting of shared constants.
- No backward-compatibility shims. Families are pre-1.0 and can change
  shape freely.

## Fresh Family Proposals

### Architectural, Single-Shaft Dramatic

**Cathedral Aperture.** A thick wall built from `mirror_block` or
`mirror_box` with a narrow slit (`slit` builder). A single projector
sits behind the wall and throws one dramatic shaft of light through the
slit onto a prism in the foreground. Stained-glass-window vibe. The
shaft is the subject; the prism breaks it into color on the opposite
wall. Motion is either slow beam angle drift or slow prism rotation,
not both.

**Periscope.** Two metallic mirrors at 45 degrees elbow the beam around
a corner, with a dispersing prism sitting mid-path between them. Reads
like an architectural drawing come alive: light enters the top, exits
the side, dispersed. Motion is a slow projector translation at the
entry.

**Sundial.** A large `thick_arc` overhead represents the sky ring, a
prism sits on a pedestal below, and an orange projector rotates along
the arc so its beam always points at the pedestal. A spectral stripe
walks across the floor like the shadow on a sundial. Motion is pure
rotation.

### One Idea, Done Cleanly (Iconic, Low Object Count)

**Chromatic Pendulum.** One prism swinging on an arc through a fixed
horizontal white beam. Rainbow sweeps back and forth on the far wall.
Maximum simplicity, highest iconic value, fastest proving ground for
the family scaffolding.

**Orbital Prism.** Fixed projector, prism orbits it slowly. Spectrum
fan rotates around the chamber walls. Reads like a lazy lighthouse.
Motion is pure orbit of the prism, camera static.

**Iris.** A ring of small prism wedges arranged in aperture formation
around the center, with a projector shining through from one side. As
the ring rotates, the transmitted light's spectral character shifts as
different wedge orientations pass into the beam. One compound
refractive aperture instead of many competing refractors.

### Physics-Diagram Beauty (Uses Underexplored Shapes)

**Parabolic Reflector.** `function_curve` builds an actual parabola as
a metallic reflector. A projector aims roughly along the parabola's
axis; the reflected beam converges at the focal point where a small
prism explodes it into dispersion. Uses a capability that no other
current family touches.

**Grating Splitter.** A `grating` intercepts a single projector beam
and splits it into a fan of parallel beams. Each beam hits a different
small prism downstream. Never tried in the existing examples. Motion
is a slow projector angle drift so the beam fan rotates across the
downstream prism row.

**Double-Slit Dispersion.** `double_slit` illuminated by an orange
projector. The two exit beams pass through two tinted glass wedges
(one warm, one cool) and cross on the far wall, where the two colored
stripes overlap briefly.

### Compound, Narrative Element (Beam As Traveler)

**Light Pipe.** A `waveguide` snakes across the frame from upper-left
to lower-right. A projector feeds one end; caustics leak at every bend
of the waveguide. Light is treated as a character traveling along the
pipe. Motion is mostly on the entry beam angle or intensity.

**Glass Organ Pipes.** A horizontal row of tall thin glass rectangles,
each with a different fill color and a small IOR offset. Projector
sweeps horizontally across the row; the chamber lights up in a bar
chart of color as each pipe is illuminated in turn.

**Spectral Staircase.** Glass rectangles fanned out like playing cards
held in a hand, each one offset in both position and angle. The
projector reveals a visible staircase of overlapping spectra as the
beam grazes the stack.

### Wildcards

**Hexagonal Prism Stack.** One compound hexagonal glass body, built
from six prisms packed tightly into a single hex shape. Not a lattice
of them - one jewel. Produces one large compound caustic instead of
many small ones. Reads as a single identifiable subject where
Crystal Field would read as a field.

**Veil.** A very wide, very thin `thick_arc` acting as a curtain of
glass across the frame. Projector behind it. The arc's continuously
varying curvature makes caustic ripples across the opposite wall.

**Wedge Fan Bloom.** A cluster of dispersive wedges whose positions
expand outward from a center over time. Spectrum fan blooms like a
flower opening.

## Parked For Later

Arbitrary-polygon subjects authored as custom shapes: flower, sword,
signature curve, or other silhouettes built with `polygon(...)` or
`path_from_samples(...)`. The engine can already support this but we
want the projector-driven families above to mature first.

## Iteration Methodology

The loop is render, measure, adjust, repeat, with an explicit
subjective check at the end because the metrics cannot judge "is it
beautiful".

### Per-Variant Inner Loop

1. Write the intent down in one sentence before tuning anything.
   Example, for Chromatic Pendulum: "the spectrum stripe reads clearly
   on the far wall, the prism is recognizable as a solid crystal, the
   beam is visible but does not saturate the frame".
2. Probe render at 320x180 or 640x360, 200-300K rays, at the one
   "hero moment" frame of the animation.
3. Read the metrics. From `ImageStats`: `mean_luma`,
   `clipped_channel_fraction`, `near_black_fraction`,
   `interdecile_luma_range`, `colorfulness`, `mean_saturation`. From
   `PointLightAppearance` or projector measurements: `peak_contrast`,
   `radius_ratio`, `transition_width_ratio`. From
   `light_contributions`: no single source above ~0.7 share unless
   intentional.
4. Gate against intent-derived thresholds. Typical anchors:
   `mean_luma` in `[0.15, 0.45]`, `clipped_channel_fraction < 0.03`,
   `near_black_fraction < 0.30`, `interdecile_luma_range > 50/255`.
   Dispersion scenes additionally require `colorfulness > 0.10`.
5. Adjust cheapest-first. Exposure first via `render_frame_variants`
   which reuses one trace across many looks. Then light intensity and
   position. Only then geometry and material parameters. Re-probe.

### Animation-Wide Check

Run `render_stats` on 6-8 frames spread across the timeline. Any
outlier frame (dark, clipped, colorless) kills the variant. A scene
that looks right at `t=0` but goes dull at `t=3s` is a failure.

### Seed Robustness

Once one seed passes, run 3-5 more seeds through the same gate. If
most of them fail, the parameter ranges are too loose and the family
is tightened, not the individual render.

### Done Criteria (First Family Shipping)

- Reference variant passes the probe gate and the animation-wide
  gate.
- Three or more seeds produce visually distinct but aesthetically
  consistent results.
- One preview MP4 at 640x360, 30fps, 1M rays or less, around 5
  seconds, that reads the intent on playback.
- Two or three variants shown to the user. The user's reaction is
  the real stop signal because the metrics can verify "bright enough,
  not clipped" objectively but not "beautiful".

### Signs To Stop Tuning And Rethink Intent

- Four or more tuning passes with thresholds fighting each other
  (for example, colorfulness cannot go up without clipping going up
  too). The composition is wrong, not the parameters.
- A variant passes every gate but looks boring. The intent sentence
  was too weak. Rewrite the intent, then re-probe.

## Shipped Status

The batch run through 2026-04-18/19 produced the following new families in
`examples/python/families/`, each with its own probe-gated sampler and
preview MP4 renders:

Shipped:

- `cathedral_aperture.py` — 6 light branches x 2 golden-ratio wall layouts.
- `parabolic_reflector.py` — 3 branches x 2 dish layouts, uses
  `function_curve` for the dish.
- `sundial.py` — projector rotates along a `thick_arc` sky ring aimed at a
  pedestal prism.
- `orbital_prism.py` — fixed projector, prism orbits it on a circle.
- `glass_organ_pipes.py` — row of coloured glass rectangles with a sweeping
  projector.
- `spectral_staircase.py` — fanned glass rectangles as playing cards.
- `veil.py` — thin wide glass `thick_arc` curtain, projector refracts
  through it.
- `wedge_fan_bloom.py` — cluster of dispersive wedges expanding outward.
- `iris.py` — rotating ring of prism wedges forming an aperture.
- `hex_jewel.py` — one compound hexagonal body of six packed prisms,
  different from the existing `hexfield.py`.
- `refraction_corridor.py` — chain of tilted glass blocks the beam threads
  through.
- `periscope.py` — two 45-degree metallic mirrors elbow a beam with a
  prism mid-path.
- `grating_splitter.py` — vertical multi-slit barrier splits one beam into
  a row of per-slit prisms.
- `double_slit_dispersion.py` — two-slit barrier with differently tinted
  glass wedges in front of each slit.

All shipped families share: metallic chamber walls, `reinhardx` /
white_point=0.5 / ambient=0 look, camera width 3.2, duration 6.0 s, preview
render 640x360 / 30 fps / 0.8 M rays. Each has an explicit layout axis
(left/right, standard/medieval inversion) as a compositional flip.

Still parked:

- Arbitrary-polygon silhouette subjects (flower, sword, signature curve).
- HD (1080p) final renders of winning seeds, which are per-request.
