"""path_explorer — interactive visualizer for ``iris_motion`` regimes.

All math, geometry, density and regime implementations are imported from
:mod:`examples.python.families.iris_motion` so this tool and the family
share a single source of truth — no risk of divergence between what you
see here and what the family renders.

Density:
    log p(θ) = w_corner · log Σᵢ exp(κ cos(θ - cᵢ)) - w_vert · cos(2θ)
where cᵢ are the four chamber-corner directions (~±60°/±120° for the
0.9×1.6 portrait chamber).

Regimes (radio):
    1. loop       — inv-sines on velocity (always forward, exact density)
    2. patrol     — point-to-point waypoint walker, optional dwell
    3. two-well   — two attractors fixed at reseed
    4. chase      — single attractor slowly drifting around the path
    5. 2D wander  — underdamped Langevin in (x, y)
    6. polar      — angular loop + radial breathing

The empirical histogram (yellow) shows where the light has spent its time —
it converges to the blue p(θ) curve when the regime is sampling correctly.
The velocity sub-panel below the density makes noise_amp / # sines / D / γ
visible at a glance.

Run:
    python tmp/iris/path_explorer.py
"""

from __future__ import annotations

import math
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Circle, Rectangle
from matplotlib.widgets import Button, RadioButtons, Slider

from examples.python.families.iris_motion import (
    CHAMBER_HW,
    CHAMBER_HH,
    CORNER_ANGLES,
    MotionParams,
    PATH_X_AXIS,
    REGIME_CLASSES,
    REGIME_NAMES,
    TWO_PI,
    chamber_max_r_at,
)
from examples.python.families.iris_motion import (
    WALL_MARGIN,  # noqa: F401  (handy default for ad-hoc tweaking)
)

# Defaults that mirror iris.py family limits, used only for slider extents.
WEDGE_SIZE_MAX = 0.12
PATH_SAFETY = 0.10
RING_RADIUS_MIN, RING_RADIUS_MAX = 0.35, 0.55
PATH_Y_MIN = PATH_X_AXIS
PATH_Y_MAX = CHAMBER_HH - WALL_MARGIN

# Friendly labels for the radio (one per regime in REGIME_NAMES order)
REGIME_LABEL_FOR = {
    "loop":     "loop (inv-sines)",
    "patrol":   "patrol (waypoints)",
    "two_well": "two-well (double attractor)",
    "chase":    "chase (drifting attractor)",
    "wander2d": "2D wander",
    "polar":    "polar (θ + r breath)",
}
REGIME_LABELS = [REGIME_LABEL_FOR[n] for n in REGIME_NAMES]
LABEL_TO_NAME = {v: k for k, v in REGIME_LABEL_FOR.items()}

# Which sliders matter for each regime (for graying-out the rest)
REGIME_SLIDERS: dict[str, set[str]] = {
    "loop":     {"w_corner", "w_vert", "a_y", "ring", "drift", "noise", "nsines", "speed_scale"},
    "patrol":   {"w_corner", "w_vert", "a_y", "ring", "drift", "dwell", "speed_scale", "smoothness"},
    "two_well": {"w_corner", "w_vert", "a_y", "ring", "D", "gamma", "speed_scale", "smoothness"},
    "chase":    {"w_corner", "w_vert", "a_y", "ring", "drift", "D", "gamma", "speed_scale", "smoothness"},
    "wander2d": {"w_corner", "w_vert", "ring", "D", "gamma", "speed_scale", "smoothness"},
    "polar":    {"w_corner", "w_vert", "a_y", "ring", "drift", "noise", "nsines", "D", "gamma",
                 "speed_scale", "smoothness"},
}


# ── Vectorized geometry helpers (UI-only; iris_motion has the scalar versions) ──

def path_xy_array(theta: np.ndarray, a_y: float):
    b = PATH_X_AXIS
    r = b * a_y / np.sqrt(a_y * a_y * np.cos(theta) ** 2 + b * b * np.sin(theta) ** 2)
    return r * np.cos(theta), r * np.sin(theta)


def path_inner_radius(a_y: float) -> float:
    return min(PATH_X_AXIS, a_y)


# ── UI ──

def _make_default_params() -> MotionParams:
    """Defaults seeded from the midpoint of each iris.py sampling range, so
    the first thing you see in the explorer is "what a typical sampled
    family variant looks like". Update both files together."""
    return MotionParams(
        w_corner=0.1125,    # mid of (0.00, 0.225)
        w_vert=0.0375,      # mid of (0.00, 0.075)
        a_y=0.96,           # mid of (0.82, 1.10)
        ring_radius=0.45,   # mid of (0.35, 0.55)
        drift=0.10,         # mid of (0.09, 0.11)
        noise_amp=0.35,     # mid of family NOISE_AMP_RANGE (0.20, 0.50)
        n_sines=3,          # mid of (2, 4)
        base_period=4.0,
        D=0.35,             # mid of (0.20, 0.50)
        gamma=3.0,          # mid of (2.0, 4.0)
        dwell=0.5,          # mid of (0.0, 1.0)
        smoothness=0.935,   # mid of (0.90, 0.97)
        speed_scale=0.25,   # mid of (0.10, 0.40)
    )


def build_ui() -> FuncAnimation:
    params = _make_default_params()
    # Fresh instances of the shared regime classes — same code as iris_motion.
    REGIMES = {name: cls() for name, cls in REGIME_CLASSES.items()}
    master_rng = np.random.default_rng(0)
    state_rng = np.random.default_rng(0)
    active = {"name": REGIME_NAMES[0], "seed": 0}

    def reseed_active() -> int:
        nonlocal state_rng
        seed = int(master_rng.integers(0, 1 << 31))
        state_rng = np.random.default_rng(seed)
        REGIMES[active["name"]].reseed(state_rng, params)
        active["seed"] = seed
        return seed

    reseed_active()

    plt.rcParams.update({
        "figure.facecolor": "#1a1916", "axes.facecolor": "#10100f",
        "axes.edgecolor": "#666", "axes.labelcolor": "#e0d8c8",
        "axes.titlecolor": "#f2eee5", "xtick.color": "#aaa",
        "ytick.color": "#aaa", "text.color": "#f2eee5", "axes.titlesize": 11,
    })

    fig = plt.figure(figsize=(15, 10))
    fig.canvas.manager.set_window_title("Iris path explorer")

    # Geometry view
    ax_geo = fig.add_axes([0.04, 0.42, 0.40, 0.55])
    ax_geo.set_aspect("equal")
    ax_geo.set_xlim(-CHAMBER_HW - 0.10, CHAMBER_HW + 0.10)
    ax_geo.set_ylim(-CHAMBER_HH - 0.10, CHAMBER_HH + 0.10)
    ax_geo.set_title("Chamber · prism ring · path · light")
    ax_geo.add_patch(Rectangle(
        (-CHAMBER_HW, -CHAMBER_HH), 2 * CHAMBER_HW, 2 * CHAMBER_HH,
        fill=False, edgecolor="#888", lw=1.5))
    theta_dense = np.linspace(0.0, TWO_PI, 360)
    px, py = path_xy_array(theta_dense, params.a_y)
    # Mark slider-updatable artists `animated=True` so blit re-draws them
    # every frame; otherwise they live in the captured background and the
    # ellipse / ring / target curve appear frozen when sliders move.
    path_line, = ax_geo.plot(px, py, color="#cccccc", lw=1.0, ls="--",
                                label="path", animated=True)
    ring_circle = Circle((0, 0), params.ring_radius, fill=False,
                          edgecolor="#5fb4ff", lw=1.5)
    ring_outer = Circle((0, 0), params.ring_radius + WEDGE_SIZE_MAX, fill=False,
                        edgecolor="#5fb4ff", lw=0.6, ls=":")
    ring_circle.set_animated(True); ring_outer.set_animated(True)
    ax_geo.add_patch(ring_circle); ax_geo.add_patch(ring_outer)
    for ca in CORNER_ANGLES:
        rmax = chamber_max_r_at(ca)
        ax_geo.plot([0, rmax * math.cos(ca)], [0, rmax * math.sin(ca)],
                      color="#444", lw=0.5, ls=":")
    trace_line, = ax_geo.plot([], [], color="#ffd166", lw=1.0, alpha=0.4,
                                label="trail", animated=True)
    init_dot, = ax_geo.plot([0], [0], "o", ms=8, color="#ef476f", mec="#1a1916",
                              alpha=0.8, zorder=9, label="start", animated=True)
    light_dot, = ax_geo.plot([0], [0], "o", ms=14, color="#ffd166", mec="#1a1916",
                               zorder=10, label="now", animated=True)
    warn_text = ax_geo.text(0.0, -CHAMBER_HH - 0.06, "", ha="center", va="top",
                              color="#ff5566", fontsize=9, weight="bold",
                              animated=True)
    ax_geo.legend(loc="upper right", fontsize=8, facecolor="#10100f",
                   edgecolor="#444", labelcolor="#e0d8c8")

    # Density panel
    ax_density = fig.add_axes([0.50, 0.59, 0.46, 0.38])
    target_line, = ax_density.plot(params.theta_grid, params.p_grid,
                                     color="#5fb4ff", lw=0.5, label="target p(θ)",
                                     animated=True)
    HIST_BINS = 96
    hist_edges = np.linspace(0.0, TWO_PI, HIST_BINS + 1)
    hist_centers = 0.5 * (hist_edges[:-1] + hist_edges[1:])
    hist_line, = ax_density.plot(hist_centers, np.zeros(HIST_BINS), color="#ffd166",
                                   lw=1.4, label="empirical (live)", animated=True)
    cur_marker, = ax_density.plot([0], [0], "o", ms=10, color="#ffd166",
                                    mec="#1a1916", zorder=10, animated=True)
    ax_density.set_xlim(0, TWO_PI)
    # Fixed ylim covers any reasonable (w_corner, w_vert) within slider range —
    # avoids needing background re-capture when the density curve rescales.
    ax_density.set_ylim(0, 0.5)
    ax_density.set_xlabel("θ on path  (0 = +x, π/2 = +y, π = −x, 3π/2 = −y)")
    ax_density.set_ylabel("density")
    ax_density.set_title("Target p(θ) vs realized time-average")
    for ca in CORNER_ANGLES:
        ax_density.axvline(ca, color="#5fb4ff", lw=0.4, ls=":")
    for k in range(8):
        ax_density.axvline(k * math.pi / 4, color="#444", lw=0.3, ls=":")
    for tx, lbl in [(0, "+x"), (math.pi / 2, "+y"), (math.pi, "−x"),
                     (3 * math.pi / 2, "−y")]:
        ax_density.text(tx, params.p_grid.max() * 1.42, lbl, ha="center",
                          color="#aaa", fontsize=8)
    ax_density.legend(loc="upper right", fontsize=9, facecolor="#10100f",
                        edgecolor="#444", labelcolor="#e0d8c8")

    # Velocity sub-panel
    ax_vel = fig.add_axes([0.50, 0.42, 0.46, 0.13])
    SPEED_HIST = 300
    SPEED_YMAX = 5.0
    speed_buf: deque[float] = deque([0.0] * SPEED_HIST, maxlen=SPEED_HIST)
    speed_x = np.linspace(-SPEED_HIST / 60.0, 0.0, SPEED_HIST)
    speed_line, = ax_vel.plot(speed_x, np.zeros(SPEED_HIST), color="#ffd166", lw=1.0,
                                animated=True)
    speed_avg_line, = ax_vel.plot(speed_x, np.zeros(SPEED_HIST), color="#5fb4ff",
                                    lw=0.6, ls="--", animated=True)
    ax_vel.set_xlim(-SPEED_HIST / 60.0, 0)
    ax_vel.set_ylim(0, SPEED_YMAX)
    ax_vel.set_xlabel("t (s, last 5s)", labelpad=2)
    ax_vel.set_ylabel("|v| (units/s)")
    ax_vel.set_title("Speed over time", fontsize=10, pad=2)

    # Sliders
    sliders: dict[str, Slider] = {}

    def make_slider(name, label, lo, hi, init, row, col, fmt="%.2f", valstep=None):
        col_x = [0.06, 0.40]
        col_w = 0.28
        y = 0.34 - row * 0.034
        ax = fig.add_axes([col_x[col], y, col_w, 0.020], facecolor="#222")
        s = Slider(ax, label, lo, hi, valinit=init, valfmt=fmt, valstep=valstep,
                    color="#5fb4ff", track_color="#333")
        s.label.set_color("#e0d8c8"); s.label.set_fontsize(9)
        s.valtext.set_color("#ffd166"); s.valtext.set_fontsize(9)
        sliders[name] = s
        return s

    make_slider("w_corner",   "w_corner (peaks)",      0.0, 2.5,  params.w_corner,  0, 0)
    make_slider("w_vert",     "w_vert (avoid horiz)",  0.0, 1.5,  params.w_vert,    1, 0)
    make_slider("a_y",        "ellipse a_y",            PATH_Y_MIN, PATH_Y_MAX, params.a_y, 2, 0)
    make_slider("ring",       "ring radius",            RING_RADIUS_MIN, RING_RADIUS_MAX,
                params.ring_radius, 3, 0)
    make_slider("drift",      "drift speed (cyc/s)",   0.0, 1.0,  params.drift,     4, 0)
    make_slider("dwell",      "dwell (s, patrol)",     0.0, 2.0,  params.dwell,     5, 0)
    make_slider("noise",      "noise amp Σaᵢ (loop)",  0.0, 0.95, params.noise_amp, 0, 1)
    make_slider("nsines",     "# sines (loop)",        1, 6, params.n_sines, 1, 1, fmt="%d", valstep=1)
    make_slider("D",          "Langevin D",            0.0, 1.5,  params.D,         2, 1)
    make_slider("gamma",      "damping γ",             0.2, 6.0,  params.gamma,     3, 1)
    make_slider("speed_scale", "speed scale (×dt)",    0.1, 2.0,  params.speed_scale, 4, 1)
    make_slider("smoothness", "smoothness (low-pass)", 0.0, 0.97, params.smoothness, 5, 1)

    # Regime radio
    radio_ax = fig.add_axes([0.74, 0.13, 0.22, 0.22], facecolor="#222")
    radio_ax.set_title("regime", color="#e0d8c8", fontsize=10, pad=4)
    regime_radio = RadioButtons(radio_ax, REGIME_LABELS, active=0, activecolor="#ffd166")
    for lbl in regime_radio.labels:
        lbl.set_color("#e0d8c8"); lbl.set_fontsize(9)

    reseed_ax = fig.add_axes([0.74, 0.06, 0.10, 0.04])
    reset_ax  = fig.add_axes([0.86, 0.06, 0.10, 0.04])
    reseed_btn = Button(reseed_ax, "Reseed", color="#333", hovercolor="#444")
    reset_btn  = Button(reset_ax, "Reset trail/hist", color="#333", hovercolor="#444")
    reseed_btn.label.set_color("#e0d8c8"); reseed_btn.label.set_fontsize(10)
    reset_btn.label.set_color("#e0d8c8"); reset_btn.label.set_fontsize(9)

    seed_text = fig.text(0.04, 0.005, "", color="#888", fontsize=9)
    info_text = fig.text(0.50, 0.005, "", color="#888", fontsize=9, ha="center")

    trace_x: list[float] = []
    trace_y: list[float] = []
    theta_history: list[float] = []
    TRACE_CAP = 250
    HISTORY_CAP = 8000
    prev_xy: list[float] = [0.0, 0.0]

    def recompute_density():
        params.recompute_density()
        target_line.set_data(params.theta_grid, params.p_grid)

    def update_path():
        px2, py2 = path_xy_array(theta_dense, params.a_y)
        path_line.set_data(px2, py2)

    def update_ring_and_warn():
        ring_circle.set_radius(params.ring_radius)
        ring_outer.set_radius(params.ring_radius + WEDGE_SIZE_MAX)
        clearance = path_inner_radius(params.a_y) - (params.ring_radius + WEDGE_SIZE_MAX)
        if clearance < PATH_SAFETY:
            warn_text.set_text(f"⚠ clearance {clearance:+.2f} < safety {PATH_SAFETY:.2f}")
        else:
            warn_text.set_text("")

    def reset_trails():
        trace_x.clear(); trace_y.clear(); theta_history.clear()
        for _ in range(SPEED_HIST):
            speed_buf.append(0.0)

    def refresh_seed_text():
        seed_text.set_text(f"seed={active['seed']}  regime={active['name']}  "
                            f"n_sines={params.n_sines}")
        info_text.set_text(
            "regime classes from iris_motion · slider changes other than "
            "w_corner/w_vert/a_y/ring need a Reseed"
        )
        fig.canvas.draw_idle()

    def gray_inactive():
        live = REGIME_SLIDERS[active["name"]]
        for name, s in sliders.items():
            alpha = 1.0 if name in live else 0.30
            s.label.set_alpha(alpha)
            s.valtext.set_alpha(alpha)
            s.poly.set_alpha(alpha)

    # Slider callbacks. Note: drift/noise/D/γ/etc only take effect on Reseed
    # (the regimes don't live-mutate their sine_mix etc), preserving exact
    # parity with the family RegimeRunner. The geometry/density artists are
    # all `animated=True` so blit redraws them on the next frame.
    def on_w_corner(v): params.w_corner = float(v); recompute_density()
    def on_w_vert(v):   params.w_vert = float(v); recompute_density()
    def on_a_y(v):      params.a_y = float(v); update_path(); update_ring_and_warn()
    def on_ring(v):     params.ring_radius = float(v); update_ring_and_warn()
    def on_drift(v):    params.drift = float(v)
    def on_dwell(v):    params.dwell = float(v)
    def on_noise(v):    params.noise_amp = float(v)
    def on_nsines(v):
        params.n_sines = int(v)
        REGIMES[active["name"]].reseed(state_rng, params)
        refresh_seed_text()
    def on_D(v):           params.D = float(v)
    def on_gamma(v):       params.gamma = float(v)
    def on_speed_scale(v): params.speed_scale = float(v)
    def on_smoothness(v):  params.smoothness = float(v)

    def on_regime(label):
        active["name"] = LABEL_TO_NAME[label]
        REGIMES[active["name"]].reseed(state_rng, params)
        reset_trails()
        x, y = REGIMES[active["name"]].step(0.0, params, state_rng)
        init_dot.set_data([x], [y])
        prev_xy[0] = x; prev_xy[1] = y
        gray_inactive()
        refresh_seed_text()

    def on_reseed(_event):
        reseed_active()
        reset_trails()
        x, y = REGIMES[active["name"]].step(0.0, params, state_rng)
        init_dot.set_data([x], [y])
        prev_xy[0] = x; prev_xy[1] = y
        refresh_seed_text()

    def on_reset(_event):
        reset_trails()

    sliders["w_corner"].on_changed(on_w_corner)
    sliders["w_vert"].on_changed(on_w_vert)
    sliders["a_y"].on_changed(on_a_y)
    sliders["ring"].on_changed(on_ring)
    sliders["drift"].on_changed(on_drift)
    sliders["dwell"].on_changed(on_dwell)
    sliders["noise"].on_changed(on_noise)
    sliders["nsines"].on_changed(on_nsines)
    sliders["D"].on_changed(on_D)
    sliders["gamma"].on_changed(on_gamma)
    sliders["speed_scale"].on_changed(on_speed_scale)
    sliders["smoothness"].on_changed(on_smoothness)
    regime_radio.on_clicked(on_regime)
    reseed_btn.on_clicked(on_reseed)
    reset_btn.on_clicked(on_reset)

    update_path()
    update_ring_and_warn()
    refresh_seed_text()
    gray_inactive()
    x0, y0 = REGIMES[active["name"]].step(0.0, params, state_rng)
    init_dot.set_data([x0], [y0])
    prev_xy[0] = x0; prev_xy[1] = y0

    # Animation. Step rate matches RegimeRunner exactly:
    #   one step per frame at INTERNAL_HZ=60 Hz, with eff_dt = speed_scale/60.
    DT = 1.0 / 60.0

    def step(_frame):
        eff_dt = DT * max(0.05, params.speed_scale)
        x, y = REGIMES[active["name"]].step(eff_dt, params, state_rng)

        speed = math.hypot(x - prev_xy[0], y - prev_xy[1]) / DT
        prev_xy[0] = x; prev_xy[1] = y
        speed_buf.append(speed)

        light_dot.set_data([x], [y])
        trace_x.append(x); trace_y.append(y)
        if len(trace_x) > TRACE_CAP:
            del trace_x[: len(trace_x) - TRACE_CAP]
            del trace_y[: len(trace_y) - TRACE_CAP]
        trace_line.set_data(trace_x, trace_y)

        theta = math.atan2(y, x) % TWO_PI
        theta_history.append(theta)
        if len(theta_history) > HISTORY_CAP:
            del theta_history[: len(theta_history) - HISTORY_CAP]
        cur_marker.set_data([theta],
                              [float(np.interp(theta, params.theta_grid, params.p_grid))])
        if len(theta_history) >= 30 and _frame % 8 == 0:
            counts, _ = np.histogram(theta_history, bins=hist_edges, density=True)
            hist_line.set_data(hist_centers, counts)
        if _frame % 4 == 0:
            arr = np.minimum(np.fromiter(speed_buf, dtype=float, count=SPEED_HIST), SPEED_YMAX)
            speed_line.set_data(speed_x, arr)
            avg = min(float(arr.mean()), SPEED_YMAX)
            speed_avg_line.set_data(speed_x, np.full(SPEED_HIST, avg))

        return (light_dot, init_dot, hist_line, cur_marker, trace_line,
                  speed_line, speed_avg_line,
                  path_line, ring_circle, ring_outer, warn_text, target_line)

    anim = FuncAnimation(fig, step, interval=1000.0 / 60.0, blit=True, cache_frame_data=False)
    plt.show()
    return anim


if __name__ == "__main__":
    build_ui()
