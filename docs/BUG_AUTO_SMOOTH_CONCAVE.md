# Bug: Auto smooth mode ignores concave polygon joins

## Summary

`PolygonJoinMode::auto` with a nonzero `smooth_angle` correctly smooths
convex joins but never smooths concave joins, regardless of the angle
threshold. This makes thick arcs and other curved polygons look faceted on
their inner (concave) surface even when the geometry clearly warrants
smooth shading.

## Expected vs actual

| Mode       | Convex side | Concave side |
|------------|-------------|--------------|
| all_sharp  | faceted     | faceted      |
| all_smooth | smooth      | smooth       |
| auto       | smooth      | **faceted** (should be smooth) |

## Reproduce

```bash
# Render the thick-arc demo, open in GUI, set smooth mode to "auto"
python examples/python/thick_arc_demo.py --frame 0 --save-json /tmp/thick_arc.json
./build/lpt2d /tmp/thick_arc.json

# Or run the regression test — auto-concave fails
python -m pytest tests/test_smooth_shading.py -v -k auto-concave
```

## Where to look

The auto join decision lives in the C++ geometry code that resolves
`PolygonJoinMode::auto` into sharp or smooth at trace time. The heuristic
likely rejects concave joins unconditionally (e.g. checking that the cross
product of adjacent edges is positive) instead of comparing the join angle
against `smooth_angle`.

Start from `src/core/geometry.cpp` — search for `auto` or `smooth_angle`
in the polygon normal resolution path.
