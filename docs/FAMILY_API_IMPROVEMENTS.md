# Family API Improvements

Observations from building the `crystal_field` family and reviewing all
existing family scripts.  Items 1-3 from the original list have been
implemented; what remains are larger ideas that need design discussion.

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

## Needs design / bigger scope

### 1. Family search harness

The main search loop is copy-pasted across all 13 family scripts:

- CLI arg parsing (`--seed`, `-n`, `--hq`)
- The `for attempt in range(MAX_ATTEMPTS)` loop
- `render_and_save` (mkdir, save params JSON, render video)
- Progress printing

A reusable harness could reduce each family to just:

```python
from anim.families import FamilyRunner

runner = FamilyRunner(
    name="crystal_field",
    duration=10.0,
    random_params=random_params,
    build_animate=build_animate,
    check_beauty=check_beauty,
    describe=describe_params,
)

if __name__ == "__main__":
    runner.main()
```

The harness would own CLI parsing, the search loop, params serialization,
progress output, and the survey/collage workflows below.

### 2. Survey mode (render one frame per variant)

The workflow of "generate N params, render the mid-frame of each, collect
stats, browse PNGs" was extremely useful for crystal_field.  This should be
a built-in mode of the family runner:

```bash
python families/crystal_field.py survey --n 32 --rays 10M --resolution 4k
```

Produces: `renders/families/crystal_field/survey/01.png`, `01_params.json`,
and a `stats.csv` summarizing richness/std/mean for each.

### 3. Video collage rendering

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

Each cell renders independently, frames are composited in-memory, piped to
ffmpeg as one stream.  No temp files.

### 4. The "same material optically, different colors" pattern

Crystal field highlighted a common need: all objects share the same optical
properties (IOR, cauchy_b, absorption) but have different spectral colors.
Currently this requires creating N separate Material instances:

```python
for i, color in enumerate(colors):
    mats[f"crystal_c{i}"] = glass(ior, cauchy_b=cb, absorption=abs, color=color, fill=fill)
```

A convenience like `glass(...).with_color("red")` or a batch helper would
reduce this boilerplate.  Not urgent but it'll recur in every family that
uses colored variants of the same base material.

---

## Not doing (and why)

- **ScalarTrack / VectorTrack types**: Too much API surface for the benefit.
  `Track.s(t)` handles the practical need.

- **Generic "Family" base class with abstract methods**: Over-abstraction.
  The runner (item 1) provides the shared structure without inheritance.

- **Auto-beauty-check**: Each family's beauty criterion is fundamentally
  different (color richness vs. contrast vs. geometric timing).  The
  harness should call a user-provided function, not try to be generic.
