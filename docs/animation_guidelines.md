# Animation Guidelines

How to make lpt2d animations that look good. Written from experience building
the first procedural animation pipeline.

## The Scene

A typical animation has one transparent shape (the subject), one projector beam
(the drama), and reflective walls (the stage).

**Walls.** The standard enclosure is a mirror box matching the camera bounds:

```python
WALL = Material(metallic=1.0, roughness=0.1, transmission=0.0, cauchy_b=0.0, albedo=1.0)
mirror_box(1.6, 0.9, WALL, id_prefix="wall")  # matches Camera2D(bounds=[-1.6, -0.9, 1.6, 0.9])
```

Walls trap and scatter the beam, creating soft ambient fill from reflections
alone. No second light source is needed. Camera and wall dimensions must match
exactly, and both must share the canvas aspect ratio (e.g. 16:9) to avoid
letterboxing.

**Transparent shapes need fill.** Glass is invisible without it. A near-white
fill gives the shape a body without hiding the light paths:

```python
glass(1.52, cauchy_b=28_000, color=(0.968, 0.968, 0.968), fill=0.15)
```

The color `(0.968, 0.968, 0.968)` is the brightest neutral the spectral system
allows. `fill=0.15` is enough to read the shape. This is not a special trick —
it should be the default for most transparent shapes.

**Projector lights are the workhorse.** `source="ball"` gives a clean point
origin. `source_radius=0.01` and `spread=0.03–0.05` produces a focused beam
that is narrow enough to read as a directed ray but wide enough to interact
meaningfully with the subject.

Don't mix point lights with projectors. Even at intensity 0.004, a point light
floods the scene omnidirectionally and fights the projector's directed drama.

## Exposure

Mirror-box scenes accumulate energy from bouncing light. With `normalize="rays"`
and reflective walls, exposure values land around **-3 to -6** — much lower than
open scenes.

**Use `render_stats`, not your eyes:**

```python
reports = render_stats(animate, Timeline(10.0, fps=30),
                       settings=settings, frames=[0, 75, 150])
for fi, ms, stats in reports:
    print(f"frame {fi}: {stats.summary()}")
```

Target **mean 70–130**. Some clipping is fine and often desirable — a projector
beam is expected to clip at its core. That bright, condensed source that then
disperses and fills the scene through diffuse reflections is part of what makes
these scenes beautiful. Don't chase zero clipping.

Exposure calibration typically happens once per scene family: find a good value
for the nominal configuration, then lock it. Per-frame exposure tracks can apply
relative offsets for stylistic effects (dimming, reveals), but the baseline is
fixed. This is how the procedural generator works — it uses a single exposure
for all variants of the same template.

## Easing and Perceived Speed

**ease_in_out_sine is slow at the endpoints and fast in the middle.** This
single fact dominates how an animation feels.

If the beam starts NEAR the subject, the easing makes it linger there — slow
start, gentle entry, meditative feel. The fast phase burns through empty space
where nothing interesting happens. This feels right.

If the beam starts FAR from the subject, the easing wastes its slow phase on
dead air. The beam then rushes across the subject at peak velocity. This feels
frantic and unsatisfying, even when the total sweep angle is identical.

The lesson: place the easing endpoints on the interesting content. Start the
beam just outside the subject so entry happens during the deceleration phase.
The viewer spends the most time watching the most interesting part of the scene.

## Dispersion

Spectral dispersion through a prism requires a specific combination of beam
angle and prism face orientation. A few degrees off in either and the output is
monochrome grey. This is not a rendering issue — it is how physics works.

This means finding good dispersion configurations is fundamentally a search
problem. The `prism_sweep_generator.py` example solves it in two stages:

1. **Geometric filtering** (analytical, no rendering): compute beam–triangle
   intersection over time, verify entry/exit timing. Reject bad candidates
   instantly.
2. **Color evaluation** (render-based): render low-res frames, measure spectral
   richness, count colorful seconds. Accept candidates that meet a threshold.

A key optimization: compute the angular hit-range of the prism first, then
construct beam angles just outside that range. This raised the geometry pass
rate from 0.2% to 4% compared to pure random sampling.

Color richness is measured by converting rendered RGB to HSV, computing hue
entropy over a 36-bin histogram and multiplying by mean saturation. Grey frames
score ~0.17; strong dispersion scores 0.5–1.0+.

## Fast Mode

`--fast` enables half-float GPU precision. It does not change the ray count.
Half-float accumulation produces ~10% dimmer results than full precision. This
means fast mode is useful for checking composition and rough exposure, but not
for final exposure tuning. For quick iteration, prefer rendering at a lower
resolution with full precision over rendering at full resolution with fast mode.

## Post-Processing

- `temperature=0.1` — subtle warmth, not a tint.
- Vignette — sparingly, and only when corners are genuinely empty. With
  reflective walls, corners usually have content.
- Canonical tonemap: `reinhardx`, `white_point=0.5`.

## Procedural Generation

The long-term vision is mass-producing animations: define a scene template with
controlled variation, sample parameters, evaluate quality automatically, render
the good ones. This is not aspirational — `prism_sweep_generator.py` does it
today for a single-prism scene.

The pattern is:

1. Define a parameter space (beam position, angles, object rotation, etc.).
2. Sample randomly but intelligently — compute the hit range first, then build
   angles around it.
3. Check analytical constraints (geometry, timing).
4. Check perceptual constraints (color richness, exposure balance).
5. Render accepted candidates in HQ.

Even a simple template generates effectively infinite variations. The constraint
system ensures they all look good.

## What the Library Could Do Better

Observations from building the first animation pipeline. These are not
requirements — they are needs and ideas to be explored.

**Color statistics.** `FrameStats` only provides luminance metrics. For a
spectral renderer, color diversity is a first-class concern. Adding mean
saturation and hue entropy would make spectral quality evaluation trivial
instead of requiring custom analysis on raw bytes.

**Exposure guidance.** A `suggest_exposure` function that shows the
exposure–clipping tradeoff for a scene would eliminate the biggest iteration
time sink. Not an auto-exposure that fights artistic intent — a calibration
tool that gets you to the ballpark and lets you take it from there.

**Scene ray-cast query.** A simple `scene.ray_intersect(origin, direction)`
returning the hit shape ID would eliminate the need to reimplement 2D
ray-segment intersection in Python. This is useful any time procedural
generation needs to reason about light–object interaction. The engine already
does this millions of times per frame — exposing a single-ray version is
trivial.

**Track derivatives.** `track.velocity_at(t)` — the analytical derivative of
the easing function. Useful for reasoning about motion speed, smoothness
analysis, and adaptive quality. Currently requires manual finite differences.

**Aspect ratio validation.** Camera bounds that don't match the canvas aspect
ratio produce silent black bars. The common case is wanting them to match;
`Camera2D` could derive height from the canvas aspect when only width is given,
and warn when explicit bounds don't match.

**Beam–shape overlap intervals.** Given a light and a shape, compute the time
ranges where the beam center ray intersects the shape. This is the compound
query behind every "ensure the beam spends enough time on the subject"
constraint. Whether it belongs in the library or stays in user scripts is an
open question — it is specific, but it came up immediately and will likely come
up for every animation template.

The guiding principle: **the library provides the primitives, the author
composes the constraint.** Don't try to auto-detect "smooth animation" — give
people the building blocks (ray casts, track derivatives, overlap queries) and
let them define what smooth means for their scene.
