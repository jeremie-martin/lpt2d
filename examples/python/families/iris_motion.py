"""Light-motion regimes for the iris family.

Six regimes share a common 1D angular density target p(θ) over the world angle
and a common elliptical path centred on the chamber. Each regime has its own
character; the family samples one per variant.

Density:
    log p(θ) = w_corner · log Σᵢ exp(κ cos(θ - cᵢ)) - w_vert · cos(2θ)
where cᵢ are the four chamber-corner directions
(=±atan2(HH−margin, HW−margin) and reflections; ~±60°/±120° for the
0.9×1.6 portrait chamber). Soft mixture of von Mises peaks → corners,
plus the cos(2θ) term for gentle horizontal-avoidance.

Regimes:
    loop      — deterministic inv-sines on velocity (always forward, exact density)
    patrol    — waypoint hops with optional dwell, forward-biased
    two_well  — two attractors picked at reseed, light swings between them
    chase     — single attractor slowly drifting around the path
    wander2d  — 2D underdamped Langevin in the annular region
    polar     — angular loop + radial breathing

Use :class:`RegimeRunner` to drive a regime from the family's animate callback;
it advances at a fixed internal rate (60 Hz) so probe and render frames are
deterministic w.r.t. wall-clock time.

See ``tmp/iris/path_explorer.py`` for an interactive visualizer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# ── Constants (mirror iris.py) ──────────────────────────────────────────

CHAMBER_HW, CHAMBER_HH = 0.9, 1.6
WALL_MARGIN = 0.08
WEDGE_SIZE_MAX = 0.12
PATH_SAFETY = 0.10

PATH_X_AXIS = CHAMBER_HW - WALL_MARGIN
TWO_PI = 2.0 * math.pi
N_GRID = 4096

CHAMBER_CORNER_ANGLE = math.atan2(CHAMBER_HH - WALL_MARGIN, PATH_X_AXIS)
CORNER_ANGLES = (
    CHAMBER_CORNER_ANGLE,
    math.pi - CHAMBER_CORNER_ANGLE,
    math.pi + CHAMBER_CORNER_ANGLE,
    TWO_PI - CHAMBER_CORNER_ANGLE,
)
# von Mises concentration for the 4 corner bumps. Must be high enough that the
# bumps don't merge — at κ ≤ 4 the constructive interference puts the actual
# density peak at vertical (90°/270°) instead of at the chamber corners. At
# κ=8 the peak is clearly at the corner direction (~1.34× higher than vertical).
CORNER_KAPPA = 8.0


# ── Density model ───────────────────────────────────────────────────────

def _logsumexp_array(arr: np.ndarray, axis: int) -> np.ndarray:
    m = np.max(arr, axis=axis, keepdims=True)
    return np.squeeze(m, axis=axis) + np.log(np.sum(np.exp(arr - m), axis=axis))


def density_grid(w_corner: float, w_vert: float):
    theta = np.linspace(0.0, TWO_PI, N_GRID + 1)
    bumps = np.stack([CORNER_KAPPA * np.cos(theta - c) for c in CORNER_ANGLES], axis=0)
    log_corner_unwt = _logsumexp_array(bumps, axis=0)
    log_p = w_corner * log_corner_unwt - w_vert * np.cos(2.0 * theta)
    log_p -= log_p.max()
    p = np.exp(log_p)
    integrate = getattr(np, "trapezoid", None) or np.trapz  # type: ignore[attr-defined]
    p /= integrate(p, theta)
    cdf = np.concatenate(([0.0], np.cumsum(0.5 * (p[1:] + p[:-1]) * np.diff(theta))))
    cdf /= cdf[-1]
    return theta, p, cdf


def inv_cdf_scalar(u: float, theta_grid: np.ndarray, cdf: np.ndarray) -> float:
    return float(np.interp(u % 1.0, cdf, theta_grid))


def grad_log_p(theta: float, w_corner: float, w_vert: float) -> float:
    """Pure-Python analytical ∂(log p)/∂θ. ~10× faster than numerical diff."""
    c0, c1, c2, c3 = CORNER_ANGLES
    u0 = CORNER_KAPPA * math.cos(theta - c0)
    u1 = CORNER_KAPPA * math.cos(theta - c1)
    u2 = CORNER_KAPPA * math.cos(theta - c2)
    u3 = CORNER_KAPPA * math.cos(theta - c3)
    m = u0
    if u1 > m: m = u1
    if u2 > m: m = u2
    if u3 > m: m = u3
    e0 = math.exp(u0 - m); e1 = math.exp(u1 - m)
    e2 = math.exp(u2 - m); e3 = math.exp(u3 - m)
    z = e0 + e1 + e2 + e3
    dL_dtheta = (-CORNER_KAPPA / z) * (
        e0 * math.sin(theta - c0) + e1 * math.sin(theta - c1) +
        e2 * math.sin(theta - c2) + e3 * math.sin(theta - c3)
    )
    return w_corner * dL_dtheta + 2.0 * w_vert * math.sin(2.0 * theta)


# ── Geometry ────────────────────────────────────────────────────────────

def path_xy_at(theta: float, a_y: float) -> tuple[float, float]:
    b = PATH_X_AXIS
    r = b * a_y / math.sqrt(a_y * a_y * math.cos(theta) ** 2 + b * b * math.sin(theta) ** 2)
    return r * math.cos(theta), r * math.sin(theta)


def chamber_max_r_at(theta: float) -> float:
    eps = 1e-9
    rx = (CHAMBER_HW - WALL_MARGIN) / max(abs(math.cos(theta)), eps)
    ry = (CHAMBER_HH - WALL_MARGIN) / max(abs(math.sin(theta)), eps)
    return min(rx, ry)


def safe_inner_r(ring_radius: float) -> float:
    """Minimum allowed light radius — outside the wedge envelope by PATH_SAFETY."""
    return ring_radius + WEDGE_SIZE_MAX + PATH_SAFETY


SOFT_WALL_MARGIN = 0.06    # outer (chamber wall) barrier soft-zone width
SOFT_INNER_MARGIN = 0.05   # inner (prism ring) barrier soft-zone width


def grad_log_p_xy(x: float, y: float, w_corner: float, w_vert: float,
                   r_in: float, barrier_K: float) -> tuple[float, float]:
    """Analytical 2D gradient for the wander2d regime.

    Three components:
      - Angular density gradient (corner peaks + horizontal-avoidance)
      - **Inner radial barrier** (push outward from prism-ring + safety),
        soft-zoned: starts pushing when ``r < r_in + SOFT_INNER_MARGIN``.
      - **Outer rectangular barrier** matching the chamber walls (NOT
        radial — a radial outer barrier is exactly zero AT the wall, so
        the walker can sit right on it). Each axis pushes inward when
        within ``SOFT_WALL_MARGIN`` of its wall.
    """
    r2 = x * x + y * y
    if r2 < 1e-12:
        return 0.0, 0.0
    r = math.sqrt(r2)
    theta = math.atan2(y, x)
    g_theta = grad_log_p(theta, w_corner, w_vert)
    inv_r2 = 1.0 / r2
    inv_r = 1.0 / r
    dt_dx = -y * inv_r2; dt_dy = x * inv_r2
    dr_dx = x * inv_r;   dr_dy = y * inv_r

    # Inner radial barrier (push outward) with soft zone
    db_dr = 0.0
    if r < r_in + SOFT_INNER_MARGIN:
        excess = r_in + SOFT_INNER_MARGIN - r
        db_dr = 2.0 * barrier_K * excess

    # Outer rectangular barrier — matches chamber walls
    x_max = CHAMBER_HW - WALL_MARGIN
    y_max = CHAMBER_HH - WALL_MARGIN
    gx_wall = 0.0
    gy_wall = 0.0
    x_threshold = x_max - SOFT_WALL_MARGIN
    y_threshold = y_max - SOFT_WALL_MARGIN
    if x > x_threshold:
        gx_wall = -2.0 * barrier_K * (x - x_threshold)
    elif x < -x_threshold:
        gx_wall = -2.0 * barrier_K * (x + x_threshold)
    if y > y_threshold:
        gy_wall = -2.0 * barrier_K * (y - y_threshold)
    elif y < -y_threshold:
        gy_wall = -2.0 * barrier_K * (y + y_threshold)

    return (g_theta * dt_dx + db_dr * dr_dx + gx_wall,
            g_theta * dt_dy + db_dr * dr_dy + gy_wall)


# ── SineMix — deterministic non-periodic carrier (velocity formulation) ──

PHI = (1.0 + math.sqrt(5.0)) / 2.0


@dataclass
class SineMix:
    drift: float
    amps: np.ndarray
    periods: np.ndarray
    phases: np.ndarray

    def position(self, t: float) -> float:
        # u(t) = ∫₀^t v(s) ds, closed form, mod 1.
        sine_int = float(np.sum(
            self.amps * self.periods *
            (np.cos(self.phases) - np.cos(TWO_PI * t / self.periods + self.phases))
        ))
        return (self.drift * t + self.drift * sine_int / TWO_PI) % 1.0


def sample_sine_mix(rng, *, n_sines: int, drift: float, amp_total: float,
                     base_period: float) -> SineMix:
    n = max(1, int(n_sines))
    periods = base_period * (PHI ** np.arange(n))
    raw = rng.uniform(0.5, 1.5, size=n)
    s = float(raw.sum())
    amps = (amp_total * (raw / s)) if s > 0 else np.zeros(n)
    phases = rng.uniform(0.0, TWO_PI, size=n)
    return SineMix(drift=drift, amps=amps, periods=periods, phases=phases)


# ── Per-variant motion params ───────────────────────────────────────────

class MotionParams:
    """All knobs needed by the regimes. Fixed for the lifetime of a variant
    (no live-mutation as in the path explorer). Density grid is cached."""

    def __init__(self, *, w_corner: float, w_vert: float, a_y: float,
                  ring_radius: float, drift: float, noise_amp: float, n_sines: int,
                  base_period: float, D: float, gamma: float, dwell: float,
                  smoothness: float, speed_scale: float):
        self.w_corner = w_corner
        self.w_vert = w_vert
        self.a_y = a_y
        self.ring_radius = ring_radius
        self.drift = drift
        self.noise_amp = noise_amp
        self.n_sines = n_sines
        self.base_period = base_period
        self.D = D
        self.gamma = gamma
        self.dwell = dwell
        self.smoothness = smoothness
        self.speed_scale = speed_scale
        self.recompute_density()

    def recompute_density(self) -> None:
        self.theta_grid, self.p_grid, self.cdf_grid = density_grid(self.w_corner, self.w_vert)


# ── Regimes ─────────────────────────────────────────────────────────────

class Regime:
    name: str = "?"

    def reseed(self, rng, params: MotionParams) -> None: ...

    def step(self, dt: float, params: MotionParams, rng) -> tuple[float, float]:
        raise NotImplementedError


class LoopRegime(Regime):
    """Velocity-formulation inv-sines on the elliptical path. Always forward."""
    name = "loop"

    def __init__(self):
        self.sine_mix: SineMix | None = None
        self.u0 = 0.0
        self.t_local = 0.0

    def reseed(self, rng, params):
        self.sine_mix = sample_sine_mix(
            rng, n_sines=params.n_sines, drift=params.drift,
            amp_total=min(params.noise_amp, 0.95),
            base_period=params.base_period,
        )
        self.u0 = float(rng.uniform())
        self.t_local = 0.0

    def step(self, dt, params, rng):
        self.t_local += dt
        u = (self.u0 + self.sine_mix.position(self.t_local)) % 1.0
        theta = inv_cdf_scalar(u, params.theta_grid, params.cdf_grid)
        return path_xy_at(theta, params.a_y)


class PatrolRegime(Regime):
    """Slide along the path toward sampled targets. Forward-biased; optional dwell."""
    name = "patrol"
    FWD_BIAS = 0.7
    FWD_TRIES = 5

    def __init__(self):
        self.theta = 0.0
        self.target = 0.0
        self.direction = 1.0
        self.dwell_remaining = 0.0
        self.last_theta = 0.0

    def _draw_target(self, rng, params):
        return inv_cdf_scalar(float(rng.uniform()), params.theta_grid, params.cdf_grid)

    def _new_target(self, rng, params):
        target = self._draw_target(rng, params)
        if rng.random() < self.FWD_BIAS:
            for _ in range(self.FWD_TRIES):
                diff = (target - self.theta + math.pi) % TWO_PI - math.pi
                if (self.direction > 0 and diff > 0.05) or (self.direction < 0 and diff < -0.05):
                    break
                target = self._draw_target(rng, params)
        return target

    def reseed(self, rng, params):
        self.theta = self._draw_target(rng, params)
        self.direction = 1.0 if rng.random() < 0.5 else -1.0
        self.target = self._new_target(rng, params)
        self.dwell_remaining = 0.0
        self.last_theta = self.theta

    def step(self, dt, params, rng):
        if self.dwell_remaining > 0:
            self.dwell_remaining -= dt
            self.last_theta = self.theta
            return path_xy_at(self.theta, params.a_y)
        diff = (self.target - self.theta + math.pi) % TWO_PI - math.pi
        speed = max(params.drift * TWO_PI, 0.10)
        if abs(diff) < speed * dt + 0.015:
            self.theta = self.target
            self.direction = 1.0 if diff >= 0 else -1.0
            if params.dwell > 1e-3:
                self.dwell_remaining = float(rng.uniform(0.5 * params.dwell, 1.5 * params.dwell))
            self.target = self._new_target(rng, params)
        else:
            self.direction = 1.0 if diff > 0 else -1.0
            self.theta = (self.theta + self.direction * speed * dt) % TWO_PI
        a = max(0.0, min(0.95, 0.5 * params.smoothness))
        sin_mix = (1.0 - a) * math.sin(self.theta) + a * math.sin(self.last_theta)
        cos_mix = (1.0 - a) * math.cos(self.theta) + a * math.cos(self.last_theta)
        smoothed = math.atan2(sin_mix, cos_mix) % TWO_PI
        self.last_theta = smoothed
        return path_xy_at(smoothed, params.a_y)


class TwoWellRegime(Regime):
    """Two attractors fixed at reseed; light swings between them in a soft double well."""
    name = "two_well"
    KAPPA_WELL = 4.0

    def __init__(self):
        self.attractors: tuple[float, float] = (0.0, math.pi)
        self.theta = 0.0
        self.thetadot = 0.0
        self.thetadot_smooth = 0.0

    def reseed(self, rng, params):
        a1 = inv_cdf_scalar(float(rng.uniform()), params.theta_grid, params.cdf_grid)
        a2 = a1
        for _ in range(10):
            a2 = inv_cdf_scalar(float(rng.uniform()), params.theta_grid, params.cdf_grid)
            if abs((a2 - a1 + math.pi) % TWO_PI - math.pi) > 0.6:
                break
        self.attractors = (a1, a2)
        self.theta = a1
        diff = (a2 - a1 + math.pi) % TWO_PI - math.pi
        self.thetadot = (1.0 if diff > 0 else -1.0) * 1.0
        self.thetadot_smooth = self.thetadot

    def _grad_well(self, theta):
        a1, a2 = self.attractors
        u1 = self.KAPPA_WELL * math.cos(theta - a1)
        u2 = self.KAPPA_WELL * math.cos(theta - a2)
        m = max(u1, u2)
        e1, e2 = math.exp(u1 - m), math.exp(u2 - m)
        z = e1 + e2
        w1, w2 = e1 / z, e2 / z
        return -self.KAPPA_WELL * (w1 * math.sin(theta - a1) + w2 * math.sin(theta - a2))

    def step(self, dt, params, rng):
        g = self._grad_well(self.theta)
        self.thetadot += (params.D * g - params.gamma * self.thetadot) * dt
        self.thetadot += math.sqrt(2.0 * params.gamma * params.D * dt) * float(rng.normal())
        a = max(0.0, min(0.99, params.smoothness))
        self.thetadot_smooth = a * self.thetadot_smooth + (1.0 - a) * self.thetadot
        self.theta = (self.theta + self.thetadot_smooth * dt) % TWO_PI
        return path_xy_at(self.theta, params.a_y)


class ChaseRegime(Regime):
    """One attractor drifting around the path; light is pulled toward it with damping."""
    name = "chase"
    KAPPA_PULL = 3.0

    def __init__(self):
        self.attractor = LoopRegime()
        self.theta = 0.0
        self.thetadot = 0.0
        self.thetadot_smooth = 0.0

    def reseed(self, rng, params):
        self.attractor.reseed(rng, params)
        # Half the configured drift speed → the chase reads as "light tracks
        # a slowly-moving anchor", not a foot-race.
        self.attractor.sine_mix.drift = params.drift * 0.5
        self.theta = inv_cdf_scalar(float(rng.uniform()), params.theta_grid, params.cdf_grid)
        self.thetadot = 0.0
        self.thetadot_smooth = 0.0

    def step(self, dt, params, rng):
        ax, ay = self.attractor.step(dt, params, rng)
        att_theta = math.atan2(ay, ax) % TWO_PI
        g = -self.KAPPA_PULL * math.sin(self.theta - att_theta)
        self.thetadot += (params.D * g - params.gamma * self.thetadot) * dt
        self.thetadot += math.sqrt(2.0 * params.gamma * params.D * dt) * float(rng.normal())
        a = max(0.0, min(0.99, params.smoothness))
        self.thetadot_smooth = a * self.thetadot_smooth + (1.0 - a) * self.thetadot
        self.theta = (self.theta + self.thetadot_smooth * dt) % TWO_PI
        return path_xy_at(self.theta, params.a_y)


class Wander2DRegime(Regime):
    """2D underdamped Langevin in the annular region, off the path."""
    name = "wander2d"
    BARRIER_K = 1500.0  # outer/inner soft-barrier strength

    def __init__(self):
        self.x = 0.0; self.y = 0.0
        self.vx = 0.0; self.vy = 0.0
        self.vx_smooth = 0.0; self.vy_smooth = 0.0

    def reseed(self, rng, params):
        theta = inv_cdf_scalar(float(rng.uniform()), params.theta_grid, params.cdf_grid)
        r = 0.5 * (safe_inner_r(params.ring_radius) + chamber_max_r_at(theta))
        self.x = r * math.cos(theta); self.y = r * math.sin(theta)
        self.vx = float(rng.normal()) * 0.2
        self.vy = float(rng.normal()) * 0.2
        self.vx_smooth = self.vx; self.vy_smooth = self.vy

    def step(self, dt, params, rng):
        r_in = safe_inner_r(params.ring_radius)
        gx, gy = grad_log_p_xy(self.x, self.y, params.w_corner, params.w_vert,
                                 r_in, self.BARRIER_K)
        self.vx += (params.D * gx - params.gamma * self.vx) * dt
        self.vy += (params.D * gy - params.gamma * self.vy) * dt
        ns = math.sqrt(2.0 * params.gamma * params.D * dt)
        self.vx += ns * float(rng.normal())
        self.vy += ns * float(rng.normal())
        a = max(0.0, min(0.99, params.smoothness))
        self.vx_smooth = a * self.vx_smooth + (1.0 - a) * self.vx
        self.vy_smooth = a * self.vy_smooth + (1.0 - a) * self.vy
        self.x += self.vx_smooth * dt
        self.y += self.vy_smooth * dt
        # Hard clip to chamber rectangle. If the walker hits a wall (the soft
        # barrier wasn't enough), zero the velocity component perpendicular to
        # that wall — both raw and smoothed — so the next frame's barrier kick
        # isn't fighting a stale lagged momentum vector pinning it to the wall.
        x_max = CHAMBER_HW - WALL_MARGIN
        y_max = CHAMBER_HH - WALL_MARGIN
        if self.x > x_max:
            self.x = x_max; self.vx = 0.0; self.vx_smooth = 0.0
        elif self.x < -x_max:
            self.x = -x_max; self.vx = 0.0; self.vx_smooth = 0.0
        if self.y > y_max:
            self.y = y_max; self.vy = 0.0; self.vy_smooth = 0.0
        elif self.y < -y_max:
            self.y = -y_max; self.vy = 0.0; self.vy_smooth = 0.0
        return self.x, self.y


class PolarRegime(Regime):
    """Angular = loop; radial = sinusoidal breath between safe inner and chamber wall."""
    name = "polar"

    def __init__(self):
        self.angular = LoopRegime()
        self.radial_phase = 0.0
        self.radial_period = 7.0
        self.radial_dir = 1.0
        self.t_local = 0.0

    def reseed(self, rng, params):
        self.angular.reseed(rng, params)
        self.radial_phase = float(rng.uniform(0, TWO_PI))
        self.radial_period = 7.0 * float(rng.uniform(0.7, 1.3))
        self.radial_dir = 1.0 if rng.random() < 0.5 else -1.0
        self.t_local = 0.0

    def step(self, dt, params, rng):
        self.t_local += dt
        x_path, y_path = self.angular.step(dt, params, rng)
        theta = math.atan2(y_path, x_path)
        r_in = safe_inner_r(params.ring_radius)
        r_out = chamber_max_r_at(theta)
        if r_out <= r_in + 0.01:
            r = 0.5 * (r_in + r_out)
        else:
            breath = 0.5 + 0.5 * math.sin(
                TWO_PI * self.t_local * self.radial_dir / max(self.radial_period, 0.1)
                + self.radial_phase
            )
            r = r_in + (r_out - r_in) * breath
        return r * math.cos(theta), r * math.sin(theta)


REGIME_CLASSES: dict[str, type[Regime]] = {
    cls().name: cls for cls in [
        LoopRegime, PatrolRegime, TwoWellRegime, ChaseRegime, Wander2DRegime, PolarRegime,
    ]
}
REGIME_NAMES = tuple(REGIME_CLASSES.keys())


# ── Runner ──────────────────────────────────────────────────────────────

class RegimeRunner:
    """Stateful driver that *behaves* as a pure function of ``(seed, t_external)``.

    Steps the regime at a fixed external rate of ``INTERNAL_HZ`` Hz, with each
    step receiving ``eff_dt = speed_scale / INTERNAL_HZ`` — exactly the same
    discretization used by ``tmp/iris/path_explorer.py``. Same seed + same
    params therefore produce a bit-identical trajectory in both places.

    Two correctness properties:

    * **Length-independence**: ``at(t)`` depends only on
      ``int(t * INTERNAL_HZ)`` steps from the seeded initial state. The clip
      duration has no effect on motion speed.
    * **Rewind-safe**: when ``at(t)`` is called with ``t < last_t`` (e.g. the
      family pipeline runs ``pick_best_frame`` then restarts at ``t=0`` for
      ``render``), the runner re-seeds and replays from step 0. Trajectory is
      then identical to a fresh runner.
    """

    INTERNAL_HZ = 60

    def __init__(self, regime_name: str, params: MotionParams, seed: int):
        self.regime_name = regime_name
        self.params = params
        self.seed = seed
        self._reset_from_seed()

    def _reset_from_seed(self) -> None:
        cls = REGIME_CLASSES[self.regime_name]
        self.regime = cls()
        self.rng = np.random.default_rng(self.seed)
        self.regime.reseed(self.rng, self.params)
        self.steps_taken = 0
        self.last_t = 0.0
        # Initial position from a zero-dt step (no state advance, no noise).
        self.last_xy = self.regime.step(0.0, self.params, self.rng)

    def at(self, t_external: float) -> tuple[float, float]:
        if t_external < self.last_t - 1e-9:
            self._reset_from_seed()
        # +1e-9 absorbs IEEE-754 roundoff so that t_external == k / INTERNAL_HZ
        # always maps to target_steps == k. (E.g. 123/60 * 60 = 122.9999…
        # naively floors to 122, silently skipping a step.)
        target_steps = int(t_external * self.INTERNAL_HZ + 1e-9)
        eff_dt = self.params.speed_scale / self.INTERNAL_HZ
        while self.steps_taken < target_steps:
            self.last_xy = self.regime.step(eff_dt, self.params, self.rng)
            self.steps_taken += 1
        self.last_t = t_external
        return self.last_xy
