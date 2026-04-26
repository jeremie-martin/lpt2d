"""Verify that ``iris_motion.RegimeRunner`` is a correct pure-function-of-(seed, t).

Three properties tested:
  1. **Equivalence to manual stepping**: ``RegimeRunner.at(t)`` produces the
     exact same trajectory as a hand-rolled loop using the same regime class
     at the same internal step rate. This is also the contract that path_explorer
     follows (its UI loop steps the *same* regime instances the same way), so
     "match the explorer" == "match a manual loop".
  2. **Call-order independence**: position at any t depends only on (seed, t),
     not on how many at(t') calls came before with t' < t.
  3. **Rewind-safe (probe-then-render)**: simulating the iris_batch flow
     (advance to t=duration, then restart at t=0) reproduces the trajectory
     exactly.
"""

from __future__ import annotations

import sys

import numpy as np

from examples.python.families import iris_motion as fam


def _params() -> fam.MotionParams:
    return fam.MotionParams(
        w_corner=0.40, w_vert=0.12, a_y=1.00, ring_radius=0.45,
        drift=0.10, noise_amp=0.30, n_sines=3, base_period=4.0,
        D=0.30, gamma=3.0, dwell=0.5,
        smoothness=0.90, speed_scale=0.70,
    )


def test_runner_vs_manual():
    """RegimeRunner.at(k / INTERNAL_HZ) must match a manual loop that steps
    the same regime class at INTERNAL_HZ with eff_dt = speed_scale / INTERNAL_HZ.
    """
    p = _params()
    seed = 12345
    HZ = fam.RegimeRunner.INTERNAL_HZ
    eff_dt = p.speed_scale / HZ
    N = HZ * 15  # 15 s of stepping

    print("Test 1: RegimeRunner ↔ manual-loop parity")
    print(f"{'regime':<14} {'max |Δx|':>12} {'max |Δy|':>12} {'parity':>10}")
    all_ok = True
    for name in fam.REGIME_NAMES:
        # Runner-driven trajectory
        runner = fam.RegimeRunner(name, p, seed)
        runner_pts = np.array([runner.at(k / HZ) for k in range(N + 1)])

        # Manual loop trajectory — same code path the explorer uses
        cls = fam.REGIME_CLASSES[name]
        regime = cls()
        rng = np.random.default_rng(seed)
        regime.reseed(rng, p)
        x0, y0 = regime.step(0.0, p, rng)
        manual_pts = [(x0, y0)]
        for _ in range(N):
            manual_pts.append(regime.step(eff_dt, p, rng))
        manual_pts = np.array(manual_pts)

        dx = float(np.max(np.abs(runner_pts[:, 0] - manual_pts[:, 0])))
        dy = float(np.max(np.abs(runner_pts[:, 1] - manual_pts[:, 1])))
        parity = "EXACT" if max(dx, dy) < 1e-10 else "MISMATCH"
        if max(dx, dy) >= 1e-10:
            all_ok = False
        print(f"  {name:<12} {dx:>12.2e} {dy:>12.2e} {parity:>10}")
    print()
    return all_ok


def test_call_order_independence():
    """Position at any t depends only on (seed, t), not on prior call sequence."""
    fp = _params()
    seed = 9999
    ts_in_order = [0.0, 1.0, 2.0, 5.0, 7.5, 10.0, 12.0, 15.0]
    ts_shuffled = [10.0, 0.0, 15.0, 1.0, 7.5, 12.0, 5.0, 2.0]

    print("Test 2: call-order independence (shuffled-vs-monotonic queries)")
    print(f"{'regime':<14} {'max |Δ|':>12} {'parity':>10}")
    all_ok = True
    for name in fam.REGIME_NAMES:
        r1 = fam.RegimeRunner(name, fp, seed)
        ordered = {t: r1.at(t) for t in ts_in_order}
        r2 = fam.RegimeRunner(name, fp, seed)
        shuffled = {t: r2.at(t) for t in ts_shuffled}
        diffs = []
        for t in ts_in_order:
            x1, y1 = ordered[t]; x2, y2 = shuffled[t]
            diffs.append(max(abs(x1 - x2), abs(y1 - y2)))
        max_diff = max(diffs)
        parity = "EXACT" if max_diff < 1e-10 else "MISMATCH"
        if max_diff >= 1e-10:
            all_ok = False
        print(f"  {name:<12} {max_diff:>12.2e} {parity:>10}")
    print()
    return all_ok


def test_rewind_after_probe():
    """Simulate iris_batch flow: probe advances runner to t=duration, then
    render starts again at t=0. Render must produce same trajectory as fresh."""
    fp = _params()
    seed = 4242
    duration = 15.0
    fps_render = 24
    render_ts = [k / fps_render for k in range(int(duration * fps_render) + 1)]

    print("Test 3: render trajectory after pick_best_frame probe")
    print(f"{'regime':<14} {'max |Δ|':>12} {'parity':>10}")
    all_ok = True
    for name in fam.REGIME_NAMES:
        # Fresh runner: just the render
        fresh = fam.RegimeRunner(name, fp, seed)
        baseline = [fresh.at(t) for t in render_ts]

        # Polluted runner: simulate probe (fps=4, monotonic 0→duration) then render (0→duration)
        polluted = fam.RegimeRunner(name, fp, seed)
        probe_fps = 4
        probe_ts = [k / probe_fps for k in range(int(duration * probe_fps) + 1)]
        for t in probe_ts:
            polluted.at(t)
        # Now also a save_frame_shot at the "best" t (mid-clip is fine for the test)
        polluted.at(duration / 2)
        # ...then the render
        after_render = [polluted.at(t) for t in render_ts]

        ba = np.array(baseline); ar = np.array(after_render)
        max_diff = float(np.max(np.abs(ba - ar)))
        parity = "EXACT" if max_diff < 1e-10 else "MISMATCH"
        if max_diff >= 1e-10:
            all_ok = False
        print(f"  {name:<12} {max_diff:>12.2e} {parity:>10}")
    print()
    return all_ok


def test_fps_independence():
    """The position at any external time t must NOT depend on the render fps.
    Probe at fps=4, render at fps=24, render at fps=60 must all see the
    same trajectory at the timestamps they share. This is the contract the
    family relies on (probe and render call the same `animate` instance)."""
    p = _params()
    seed = 31415
    test_ts = [0.0, 0.5, 1.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0]

    print("Test 5: FPS-independence (same external time → same position)")
    print(f"{'regime':<14} {'max |Δ| 4↔24':>14} {'max |Δ| 4↔60':>14} {'parity':>10}")
    all_ok = True
    for name in fam.REGIME_NAMES:
        # fps=4: probe-like cadence
        r4 = fam.RegimeRunner(name, p, seed)
        ts4 = [k / 4 for k in range(int(15 * 4) + 1)]
        # Walk the runner through the full ts4 sequence, then sample at test_ts
        for t in ts4:
            r4.at(t)
        # Now sample at test_ts; rewind safely if needed
        pts4 = [r4.at(t) for t in test_ts]

        # fps=24: render cadence A
        r24 = fam.RegimeRunner(name, p, seed)
        ts24 = [k / 24 for k in range(int(15 * 24) + 1)]
        for t in ts24:
            r24.at(t)
        pts24 = [r24.at(t) for t in test_ts]

        # fps=60: render cadence B
        r60 = fam.RegimeRunner(name, p, seed)
        ts60 = [k / 60 for k in range(int(15 * 60) + 1)]
        for t in ts60:
            r60.at(t)
        pts60 = [r60.at(t) for t in test_ts]

        a4 = np.array(pts4); a24 = np.array(pts24); a60 = np.array(pts60)
        d_4_24 = float(np.max(np.abs(a4 - a24)))
        d_4_60 = float(np.max(np.abs(a4 - a60)))
        parity = "EXACT" if max(d_4_24, d_4_60) < 1e-10 else "MISMATCH"
        if max(d_4_24, d_4_60) >= 1e-10:
            all_ok = False
        print(f"  {name:<12} {d_4_24:>14.2e} {d_4_60:>14.2e} {parity:>10}")
    print()
    return all_ok


def test_motion_actually_happens():
    """Sanity: per-regime, position actually changes over the 15s clip."""
    fp = _params()
    print("Test 4: motion actually happens in 15 s (sanity)")
    print(f"{'regime':<14} {'x range':>12} {'y range':>12} {'arclen':>10}")
    for name in fam.REGIME_NAMES:
        runner = fam.RegimeRunner(name, fp, 7)
        pts = np.array([runner.at(k / 60.0) for k in range(60 * 15 + 1)])
        dx = pts[1:] - pts[:-1]
        arclen = float(np.sum(np.linalg.norm(dx, axis=1)))
        x_range = float(pts[:, 0].max() - pts[:, 0].min())
        y_range = float(pts[:, 1].max() - pts[:, 1].min())
        print(f"  {name:<12} {x_range:>12.3f} {y_range:>12.3f} {arclen:>10.2f}")


if __name__ == "__main__":
    ok1 = test_runner_vs_manual()
    ok2 = test_call_order_independence()
    ok3 = test_rewind_after_probe()
    ok4 = test_fps_independence()
    test_motion_actually_happens()
    print(f"\nSummary: runner-parity={'OK' if ok1 else 'FAIL'}  "
            f"order={'OK' if ok2 else 'FAIL'}  "
            f"rewind={'OK' if ok3 else 'FAIL'}  "
            f"fps-indep={'OK' if ok4 else 'FAIL'}")
    sys.exit(0 if (ok1 and ok2 and ok3 and ok4) else 1)
