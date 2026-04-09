# Family API Improvements

Observations from building the `crystal_field` family and reviewing all
13 existing family scripts.

---

## Implemented

- **Track.s(t)** — scalar shorthand that returns `float` with proper type
  narrowing.  Replaces `float(track(t))` pattern used in every family script.
- **params_from_dict()** — generic nested-dataclass round-trip helper in
  `anim/params.py`.  Handles `Optional[Dataclass]` fields automatically.
- **build_seed in params JSON** — `crystal_field` now saves
  `{"params": {...}, "build_seed": N}` so scenes are fully reproducible from
  JSON alone.

---

## The central pattern: rejection sampling

Every family script is a **rejection sampler**.  The structure is identical
across all 13 scripts:

1. Draw random params from the family's parameter space
2. Optionally run cheap analytical pre-checks (only mirror_corridor does this)
3. Probe-render ~32 frames at 640x360, 200K rays, 4 FPS
4. Compute per-frame statistics (color_stats or frame_stats)
5. Count how many frames pass a threshold
6. Accept if enough frames are good; otherwise discard and draw again
7. HQ render only the accepted variants

This is not optimization.  There is no gradient, no fitness to maximize,
no parameter tuning.  It is pure **filtering** — draw, check, keep or
discard.  The parameter space is sampled uniformly (or with weighted
`rng.choices`), and the filter is the creative judgment that separates
interesting scenes from boring or broken ones.

### What varies across families

Only three things differ:

| Concern | Examples |
|---------|----------|
| **Which metric** | color_richness, frame std (contrast), luminance mean, or combinations |
| **Threshold** | 0.15 to 0.30 for richness; 15 to 30 for contrast std |
| **Duration requirement** | 2.0 to 3.0 seconds of "good" frames out of the total |

Everything else — the probe loop, the session management, the
`_resolve_frame_shot` call, the progress printing, the CLI, the params
serialization — is copy-pasted verbatim.

### What the framework should own

The **probe render loop** is the most duplicated code (~15 identical lines
in every script).  The framework should provide it as a utility:

```python
def probe_render(
    animate: AnimateFn,
    shot: Shot,
    duration: float,
    fps: float = 4.0,
) -> list[ProbeFrame]:
    """Render low-res probe frames, return pixels + stats for each."""
```

This is not a filter — it's plumbing.  The filter is what you do with the
results.  The framework provides the frames; the script decides accept or
reject.

### What the framework should NOT own

- Threshold values
- Which metric to check
- How many frames must pass
- Built-in filter types ("color filter", "contrast filter", etc.)
- Any notion of "score" or "fitness"

The filter is a **callable provided by the script**: it receives params,
does whatever checks it wants (analytical, probe-based, or both), and
returns a verdict.

### Design sketch: Verdict and FamilyRunner

```python
@dataclass
class Verdict:
    """Result of filtering one parameter set."""
    accept: bool
    summary: str  # one-line description for progress output

# The script provides these four callables:
random_params:  (Random) -> P
build_animate:  (P, Random) -> AnimateFn
check:          (P, Random) -> Verdict
describe:       (P) -> str

# The framework runs the search loop:
runner = FamilyRunner(
    name="crystal_field",
    duration=10.0,
    random_params=random_params,
    build_animate=build_animate,
    check=check,
    describe=describe_params,
)
runner.main()  # handles CLI, search loop, params JSON, rendering
```

The `check` callable is fully opaque to the framework.  It might:
- Do a pure geometry check and return immediately
- Call `probe_render()` and analyze color richness
- Do both (cheap check first, probe only if the cheap check passes)
- Do something we haven't thought of yet

The framework doesn't care.  It calls `check()`, reads `verdict.accept`,
prints `verdict.summary`, and moves on.

### Built-in modes the runner would support

```bash
# Search and render accepted variants as video
python families/crystal_field.py search -n 5 --hq

# Survey: render mid-frame stills for N random params (no filtering)
python families/crystal_field.py survey -n 32 --rays 10M

# Render a specific params.json as video
python families/crystal_field.py render params.json --hq

# Collage: render N accepted variants side-by-side
python families/crystal_field.py collage -n 4 --grid 2x2
```

---

## Other improvements (smaller scope)

### Video collage rendering

`render_contact_sheet` exists for still grids.  The video equivalent — tile
N animations into a single video — required shelling out to ffmpeg.

This could live in `anim/renderer.py`:

```python
def render_collage(
    animates: list[AnimateFn],
    timeline: Timeline,
    output: str,
    *,
    grid: tuple[int, int] = (2, 2),
    settings: Shot | None = None,
) -> None:
```

### Material color variant helper

All objects share the same optical properties but have different spectral
colors.  Currently requires creating N separate Material instances.
A convenience like `glass(...).with_color("red")` would reduce this.

---

## Not doing (and why)

- **ScalarTrack / VectorTrack types**: `Track.s(t)` handles the need.

- **Generic "Family" base class with abstract methods**: The runner
  takes callables, not base classes.  No inheritance.

- **Built-in filter types**: Each family's acceptance criterion is
  fundamentally different.  The framework should provide probe_render
  as plumbing, not pre-built filters.

- **Optimization / fitness maximization**: The current approach is
  rejection sampling, not optimization.  There's no gradient to follow.
  If we ever need optimization, it would be a separate tool, not a
  complication of the family runner.
