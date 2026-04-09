# Family API Improvements

Observations from building the `crystal_field` family and reviewing
existing family scripts.

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

Every family script is a **rejection sampler**: draw random params, check
whether they're worth rendering, keep or discard.  This is not optimization
— there is no gradient, no fitness to maximize.  It is pure filtering.

### What filtering could look like

The existing 13 scripts all happen to use multi-frame probe renders for
their checks, but this is an artifact of copy-paste, not a design insight.
The scripts were generated from a single template and the pattern was
never questioned.  In practice, filtering could take many forms:

- **Arithmetic on params alone**: does the grid fit in the camera?  Is
  the light starting inside an object?  Are the objects too dense to
  leave interstitial space?  These checks are instantaneous and could
  reject many bad configs before touching the renderer.

- **Geometric analysis**: does the beam intersect the target shape?  Do
  any shapes overlap?  What's the minimum clearance between objects?
  The existing `ray_intersect()` utility already supports this.

- **Single-frame probe**: render one frame at the "interesting" moment
  (e.g., mid-animation) and check luminance/richness.  Faster than
  multi-frame by 30x.  May be sufficient for many families where the
  animation character is roughly uniform.

- **Multi-frame probe**: render several frames across the timeline and
  check that enough of them pass.  The current approach — useful when
  the animation evolves and you care about sustained quality, not just
  one good moment.

- **Structural / semantic checks**: count how many distinct caustic
  regions exist, check symmetry properties, verify that light reaches
  certain parts of the scene.

- **No check at all**: generate everything, render stills, let the human
  browse.  The survey workflow we used for crystal_field.

- **Combinations**: cheapest checks first, expensive probes only if the
  cheap checks pass.  A pipeline of increasingly expensive filters.

A well-designed framework should make all of these equally easy without
privileging any one pattern.

### What the framework should own

**Plumbing, not judgment.**

The framework should provide reusable building blocks:

- `probe_render(animate, shot, duration, fps)` — run probe frames,
  return pixels + stats.  This is the most common expensive check and
  the most duplicated code.  But it's a tool the filter uses, not the
  filter itself.

- `Verdict(accept, summary)` — the return type of a filter.  The
  framework reads `accept` and prints `summary`.  That's it.

- `FamilyRunner` — the search loop, CLI, params JSON serialization,
  progress output.  Takes a filter callable from the script.

The filter callable is **fully opaque** to the framework.  The framework
calls it, reads the verdict, moves on.  It doesn't know or care whether
the filter did arithmetic, geometry, rendering, or nothing.

### What the framework should NOT own

- Threshold values or metrics
- Built-in filter types ("color filter", "contrast filter")
- Any notion of "score" or "fitness"
- Decisions about which checks to run or in what order

### Design sketch

```python
@dataclass
class Verdict:
    """Result of filtering one parameter set."""
    accept: bool
    summary: str  # one-line for progress output

# A family script provides these callables:
random_params:  (Random) -> P
build_animate:  (P, Random) -> AnimateFn
check:          (P, Random) -> Verdict   # opaque — does whatever it wants
describe:       (P) -> str

# The framework runs the loop:
runner = FamilyRunner(
    name="crystal_field",
    duration=10.0,
    random_params=random_params,
    build_animate=build_animate,
    check=check,
    describe=describe_params,
)
runner.main()
```

The `check` callable might:
- Return `Verdict(True, "grid fits")` after a microsecond of arithmetic
- Call `probe_render()`, compute richness, return after 2 seconds
- Chain three checks with early exit on the first failure
- Always accept (for survey-style exploration)

### Built-in runner modes

```bash
# Search with filtering and render accepted variants
python families/crystal_field.py search -n 5 --hq

# Survey: no filtering, render mid-frame still for each
python families/crystal_field.py survey -n 32 --rays 10M

# Re-render a saved params.json
python families/crystal_field.py render params.json --hq

# Collage: render N accepted variants side-by-side
python families/crystal_field.py collage -n 4 --grid 2x2
```

---

## Other improvements

### Video collage rendering

`render_contact_sheet` exists for still grids.  The video equivalent
requires ffmpeg.  A `render_collage()` in `anim/renderer.py` would
composite cells in-memory and pipe to ffmpeg as one stream.

### Material color variant helper

Common need: same optical properties, different spectral colors.
A convenience like `glass(...).with_color("red")` would reduce the
boilerplate of creating N separate Material instances.

---

## Not doing (and why)

- **ScalarTrack / VectorTrack types**: `Track.s(t)` handles the need.

- **Family base class with abstract methods**: The runner takes
  callables.  No inheritance.

- **Built-in filter types**: The filter is the script's creative
  judgment.  The framework provides probe_render as a tool, not
  pre-built filters.

- **Optimization / fitness**: Rejection sampling is the right model
  for now.  If optimization is ever needed, it's a separate tool.
