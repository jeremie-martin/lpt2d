# Family API

A *family* is a visual concept that can produce many animation variants
from one definition.  The framework owns workflow plumbing.  The family
owns creative judgment.

## What the framework provides

```python
from anim.family import Family, Verdict, ProbeFrame, probe
```

| Item | Purpose |
|------|---------|
| `Verdict(ok, summary)` | What `check` returns |
| `probe(animate, duration)` | Render probe frames, return per-frame stats |
| `ProbeFrame` | Per-frame stats (color_richness, mean, std, ...) |
| `Family(...)` | Runner with search/survey/render/main methods |

## What a family script provides

| Item | Signature | Required |
|------|-----------|----------|
| Params | any dataclass | yes |
| sample | `(rng) -> Params \| None` | yes |
| build | `(params) -> AnimateFn` | yes |
| check | `(params, animate) -> Verdict` | no |
| describe | `(params) -> str` | no |

## Minimal example

```python
from dataclasses import dataclass
from anim.family import Family, Verdict, probe
from anim import Frame, Look, Scene, glass, mirror_box, prism, ProjectorLight

DURATION = 8.0

@dataclass
class Params:
    prism_size: float
    beam_angle: float
    exposure: float

def sample(rng):
    return Params(
        prism_size=rng.uniform(0.25, 0.40),
        beam_angle=rng.uniform(-0.1, 0.1),
        exposure=rng.uniform(-5.5, -4.5),
    )

def build(p):
    def animate(ctx):
        scene = Scene(
            materials={"wall": WALL, "glass": GLASS},
            shapes=[*mirror_box(1.6, 0.9, "wall"), prism((0, 0), p.prism_size, "glass")],
            lights=[ProjectorLight(id="beam", position=[-1.4, 0], ...)],
        )
        return Frame(scene=scene, look=Look(exposure=p.exposure))
    return animate

def check(p, animate):
    frames = probe(animate, DURATION)
    colorful = sum(1 for f in frames if f.color_richness > 0.3)
    return Verdict(colorful >= 8, f"colorful={colorful}")

FAMILY = Family("my_family", DURATION, Params, sample, build, check=check)

if __name__ == "__main__":
    FAMILY.main()
```

## How check works

`check(params, animate)` receives both the params and the built animate
function.  This enables all types of filtering with natural control flow:

**Arithmetic on params** (microseconds):
```python
def check(p, animate):
    if p.grid_width > 2.8:
        return Verdict(False, "grid too wide")
    ...
```

**Scene inspection** (milliseconds):
```python
def check(p, animate):
    mid = animate(FrameContext(time=4.0, frame=0, ...))
    for light in mid.scene.lights:
        if abs(light.position[0]) > 1.4:
            return Verdict(False, "light outside box")
    ...
```

**Render-based probe** (seconds):
```python
def check(p, animate):
    frames = probe(animate, 10.0)
    avg = sum(f.color_richness for f in frames) / len(frames)
    return Verdict(avg > 0.2, f"avg_richness={avg:.3f}")
```

**Staged pipeline with early exit** (cheap first, expensive only if cheap passes):
```python
def check(p, animate):
    # Stage 1: geometry (cheap)
    geo_ok, t_enter = check_geometry(p)
    if not geo_ok:
        return Verdict(False, f"geometry miss t={t_enter:.2f}")

    # Stage 2: probe render (expensive, only runs if geometry passed)
    frames = probe(animate, 10.0)
    colorful = sum(1 for f in frames if f.color_richness > 0.4)
    return Verdict(colorful >= 12, f"geo ok, colorful={colorful}")
```

## Build-time randomness

If `build` needs extra randomness (e.g., random hole removal in a grid),
put a seed in the params.  The framework saves `asdict(params)` which
includes the seed, making variants fully reproducible:

```python
@dataclass
class Params:
    grid: GridConfig
    build_seed: int

def sample(rng):
    return Params(grid=random_grid(rng), build_seed=rng.randint(0, 2**32))

def build(p):
    rng = random.Random(p.build_seed)
    positions = remove_holes(build_grid(p.grid), rng)
    ...
```

## CLI modes

```bash
# Search with filtering (default mode)
python families/my_family.py search -n 5 --hq --seed 42

# Backward-compatible (no subcommand = search)
python families/my_family.py -n 5 --hq --seed 42

# Survey: no filtering, render stills for browsing
python families/my_family.py survey -n 32

# Re-render a saved variant
python families/my_family.py render path/to/params.json --hq
```

## probe() defaults

| Parameter | Default | Notes |
|-----------|---------|-------|
| fps | 4 | Probe frame rate |
| width | 640 | Probe width |
| height | 360 | Probe height |
| rays | 200,000 | Rays per frame |
| depth | 10 | Max ray depth |
| camera | center=[0,0] width=3.2 | Override if needed |

## Family constructor

```python
Family(
    name,          # str — used for output dirs and CLI
    duration,      # float — animation duration (seconds)
    params_type,   # type — dataclass type for JSON round-tripping
    sample,        # (rng) -> Params | None
    build,         # (Params) -> AnimateFn
    *,
    check=None,    # (Params, AnimateFn) -> Verdict
    describe=None, # (Params) -> str
    camera=None,   # Camera2D — default center=[0,0] width=3.2
    depth=12,      # int — max ray depth for final renders
)
```

## Programmatic use

```python
from families.my_family import FAMILY

# Run search from another script
accepted = FAMILY.search(n=4, seed=42, hq=True)

# Re-render a saved variant
FAMILY.render("renders/families/my_family/001/params.json", hq=True)
```
