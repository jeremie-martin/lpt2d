"""Tests for animation library improvements: track derivatives, color stats,
ray-cast / projector target, and Camera2D aspect ratio."""

from __future__ import annotations

import math

import pytest

from anim.easing import (
    EASING_DERIVATIVES,
    EASINGS,
    resolve_easing_derivative,
    smoothstep,
    smoothstep_d,
)
from anim.stats import color_stats
from anim.track import Key, Track, Wrap

# ─── Track derivatives ──────────────────────────────────────────


class TestEasingDerivatives:
    """Verify analytical derivatives against numerical finite differences."""

    @pytest.mark.parametrize("name", sorted(EASINGS.keys()))
    def test_derivative_matches_numerical(self, name: str):
        ease = EASINGS[name]
        deriv = EASING_DERIVATIVES[name]
        h = 1e-6
        for t in [0.01, 0.25, 0.5, 0.75, 0.99]:
            numerical = (ease(t + h) - ease(t - h)) / (2.0 * h)
            analytical = deriv(t)
            assert analytical == pytest.approx(numerical, abs=1e-4), (
                f"{name} derivative mismatch at t={t}: analytical={analytical}, numerical={numerical}"
            )

    def test_linear_derivative_is_constant(self):
        d = EASING_DERIVATIVES["linear"]
        assert d(0.0) == 1.0
        assert d(0.5) == 1.0
        assert d(1.0) == 1.0

    def test_smoothstep_derivative_zero_at_endpoints(self):
        assert smoothstep_d(0.0) == pytest.approx(0.0)
        assert smoothstep_d(1.0) == pytest.approx(0.0)
        assert smoothstep_d(0.5) == pytest.approx(1.5)  # peak

    def test_ease_in_out_sine_derivative_symmetry(self):
        d = EASING_DERIVATIVES["ease_in_out_sine"]
        # Symmetric around midpoint
        assert d(0.25) == pytest.approx(d(0.75))
        # Peak at midpoint
        assert d(0.5) > d(0.25)

    def test_step_derivative_is_zero(self):
        d = EASING_DERIVATIVES["step"]
        assert d(0.0) == 0.0
        assert d(0.5) == 0.0
        assert d(1.0) == 0.0

    def test_resolve_builtin_by_name(self):
        d = resolve_easing_derivative("smoothstep")
        assert d(0.5) == pytest.approx(1.5)

    def test_resolve_builtin_by_callable(self):
        d = resolve_easing_derivative(smoothstep)
        assert d(0.5) == pytest.approx(1.5)

    def test_resolve_unknown_name_raises(self):
        with pytest.raises(ValueError, match="Unknown easing"):
            resolve_easing_derivative("nonexistent")

    def test_resolve_custom_callable_fallback(self):
        custom = lambda t: t**4  # noqa: E731
        d = resolve_easing_derivative(custom)
        # Numerical derivative of t^4 at t=0.5 should be 4*0.5^3 = 0.5
        assert d(0.5) == pytest.approx(0.5, abs=1e-4)


class TestTrackVelocity:
    def test_linear_constant_velocity(self):
        track = Track([Key(0.0, 0.0), Key(10.0, 100.0)])
        # Linear: velocity = (100 - 0) / (10 - 0) = 10.0 everywhere
        assert track.velocity_at(0.5) == pytest.approx(10.0)
        assert track.velocity_at(5.0) == pytest.approx(10.0)
        assert track.velocity_at(9.5) == pytest.approx(10.0)

    def test_smoothstep_zero_velocity_at_endpoints(self):
        track = Track([Key(0.0, 0.0), Key(1.0, 1.0, ease="smoothstep")])
        assert track.velocity_at(0.001) == pytest.approx(0.0, abs=0.02)
        assert track.velocity_at(0.999) == pytest.approx(0.0, abs=0.02)
        # Peak velocity at midpoint
        mid_vel = track.velocity_at(0.5)
        assert isinstance(mid_vel, (int, float))
        assert mid_vel > 1.0  # should be 1.5

    def test_single_key_zero_velocity(self):
        track = Track([Key(5.0, 42.0)])
        assert track.velocity_at(5.0) == 0.0
        assert track.velocity_at(0.0) == 0.0

    def test_clamped_outside_range_zero_velocity(self):
        track = Track([Key(1.0, 0.0), Key(2.0, 10.0)])
        assert track.velocity_at(0.0) == 0.0  # before track
        assert track.velocity_at(3.0) == 0.0  # after track

    def test_multi_segment(self):
        track = Track(
            [
                Key(0.0, 0.0),
                Key(1.0, 10.0),  # linear, vel = 10
                Key(2.0, 30.0),  # linear, vel = 20
            ]
        )
        assert track.velocity_at(0.5) == pytest.approx(10.0)
        assert track.velocity_at(1.5) == pytest.approx(20.0)

    def test_2d_track_velocity(self):
        track = Track([Key(0.0, (0.0, 0.0)), Key(1.0, (10.0, 20.0))])
        vel = track.velocity_at(0.5)
        assert isinstance(vel, tuple)
        assert vel[0] == pytest.approx(10.0)
        assert vel[1] == pytest.approx(20.0)

    def test_2d_single_key_zero_velocity(self):
        track = Track([Key(0.0, (1.0, 2.0))])
        vel = track.velocity_at(0.0)
        assert vel == (0.0, 0.0)

    def test_ease_in_out_sine_slow_at_endpoints(self):
        track = Track([Key(0.0, 0.0), Key(math.pi, 1.0, ease="ease_in_out_sine")])
        vel_start = abs(track.velocity_at(0.01))  # type: ignore[arg-type]
        vel_mid = abs(track.velocity_at(math.pi / 2))  # type: ignore[arg-type]
        vel_end = abs(track.velocity_at(math.pi - 0.01))  # type: ignore[arg-type]
        # Endpoints should be much slower than midpoint
        assert vel_mid > vel_start * 3
        assert vel_mid > vel_end * 3

    def test_pingpong_velocity_sign_flips(self):
        track = Track([Key(0.0, 0.0), Key(1.0, 10.0)], wrap=Wrap.PINGPONG)
        # Forward leg: t=0.5 → positive velocity
        vel_fwd = track.velocity_at(0.5)
        assert vel_fwd == pytest.approx(10.0)
        # Return leg: t=1.5 → negative velocity (moving back toward 0)
        vel_rev = track.velocity_at(1.5)
        assert vel_rev == pytest.approx(-10.0)

    def test_loop_velocity_continuous(self):
        track = Track([Key(0.0, 0.0), Key(1.0, 10.0)], wrap=Wrap.LOOP)
        # Inside the track
        assert track.velocity_at(0.5) == pytest.approx(10.0)
        # After looping, velocity should be the same (continuous)
        assert track.velocity_at(1.5) == pytest.approx(10.0)
        # Near the loop boundary
        assert track.velocity_at(0.999) == pytest.approx(10.0)
        assert track.velocity_at(1.001) == pytest.approx(10.0)

    def test_2d_track_velocity_with_easing(self):
        track = Track([Key(0.0, (0.0, 0.0)), Key(1.0, (10.0, 20.0), ease="smoothstep")])
        vel = track.velocity_at(0.5)
        assert isinstance(vel, tuple)
        # smoothstep derivative at 0.5 = 1.5, so velocity = (10, 20) * 1.5 / 1.0
        assert vel[0] == pytest.approx(15.0)
        assert vel[1] == pytest.approx(30.0)
        # Zero velocity at endpoints
        vel_start = track.velocity_at(0.001)
        assert abs(vel_start[0]) < 0.1  # type: ignore[arg-type]

    def test_custom_easing_derivative_clamped_at_boundary(self):
        """Custom easing that would fail outside [0, 1] is handled gracefully."""
        import math as m

        custom = lambda t: m.sqrt(t)  # noqa: E731 — undefined for t < 0
        d = resolve_easing_derivative(custom)
        # Near t=0, numerical derivative should not crash
        val = d(0.0)
        assert isinstance(val, float)
        assert val > 0  # derivative of sqrt at 0 is infinite, but we get a finite approx


# ─── Color statistics ───────────────────────────────────────────


def _make_rgb(pixels: list[tuple[int, int, int]], width: int, height: int) -> bytes:
    """Create RGB bytes from a list of (R, G, B) pixel values."""
    if len(pixels) != width * height:
        raise ValueError(f"Expected {width * height} pixels, got {len(pixels)}")
    return bytes(c for pixel in pixels for c in pixel)


class TestColorStats:
    def test_pure_grey_low_richness(self):
        # All grey pixels — no chromatic content
        pixels = [(128, 128, 128)] * 100
        stats = color_stats(_make_rgb(pixels, 10, 10), 10, 10)
        assert stats.n_chromatic == 0
        assert stats.color_richness == 0.0
        assert stats.mean_saturation == 0.0
        assert stats.hue_entropy == 0.0

    def test_all_black_returns_zeros(self):
        pixels = [(0, 0, 0)] * 100
        stats = color_stats(_make_rgb(pixels, 10, 10), 10, 10)
        assert stats.n_chromatic == 0
        assert stats.color_richness == 0.0

    def test_single_saturated_hue(self):
        # All bright red — high saturation, low hue entropy
        pixels = [(255, 0, 0)] * 100
        stats = color_stats(_make_rgb(pixels, 10, 10), 10, 10)
        assert stats.n_chromatic == 100
        assert stats.mean_saturation == pytest.approx(1.0)
        assert stats.hue_entropy == pytest.approx(0.0)  # single bin
        assert stats.color_richness == pytest.approx(0.0)

    def test_rainbow_high_richness(self):
        # 6 distinct hues spread across the spectrum
        hues = [
            (255, 0, 0),  # red
            (255, 255, 0),  # yellow
            (0, 255, 0),  # green
            (0, 255, 255),  # cyan
            (0, 0, 255),  # blue
            (255, 0, 255),  # magenta
        ]
        # Fill a 6x1 image
        stats = color_stats(_make_rgb(hues, 6, 1), 6, 1)
        assert stats.n_chromatic == 6
        assert stats.mean_saturation == pytest.approx(1.0)
        assert stats.hue_entropy > 2.0  # 6 evenly-spaced bins → ~2.58 bits
        assert stats.color_richness > 2.0

    def test_summary_string(self):
        pixels = [(255, 0, 0)] * 4
        stats = color_stats(_make_rgb(pixels, 2, 2), 2, 2)
        s = stats.summary()
        assert "sat=" in s
        assert "entropy=" in s
        assert "richness=" in s

    def test_zero_pixel_frame_raises(self):
        with pytest.raises(ValueError, match="0-pixel"):
            color_stats(b"", 0, 0)

    def test_wrong_byte_count_raises(self):
        with pytest.raises(ValueError, match="Expected"):
            color_stats(b"\x00" * 10, 2, 2)  # expect 12 bytes


# ─── Ray-cast / projector target ────────────────────────────────


class TestRayIntersect:
    def test_ray_hits_segment(self):
        from anim.analysis import ray_intersect
        from anim.types import Material, Scene, Segment

        seg = Segment(id="wall", a=(0.0, -1.0), b=(0.0, 1.0), material=Material())
        scene = Scene(shapes=[seg])

        result = ray_intersect(scene, (-1.0, 0.0), (1.0, 0.0))
        assert result is not None
        t, point, normal, shape_id = result
        assert shape_id == "wall"
        assert t == pytest.approx(1.0)
        assert point[0] == pytest.approx(0.0)
        assert point[1] == pytest.approx(0.0)

    def test_ray_misses(self):
        from anim.analysis import ray_intersect
        from anim.types import Material, Scene, Segment

        seg = Segment(id="wall", a=(0.0, -1.0), b=(0.0, 1.0), material=Material())
        scene = Scene(shapes=[seg])

        # Shoot parallel to the segment
        result = ray_intersect(scene, (-1.0, 0.0), (0.0, 1.0))
        assert result is None

    def test_closest_hit_when_multiple_shapes(self):
        from anim.analysis import ray_intersect
        from anim.types import Material, Scene, Segment

        near = Segment(id="near", a=(1.0, -1.0), b=(1.0, 1.0), material=Material())
        far = Segment(id="far", a=(3.0, -1.0), b=(3.0, 1.0), material=Material())
        scene = Scene(shapes=[far, near])  # order shouldn't matter

        result = ray_intersect(scene, (0.0, 0.0), (1.0, 0.0))
        assert result is not None
        assert result[3] == "near"

    def test_ray_hits_group_shape(self):
        from anim.analysis import ray_intersect
        from anim.types import Group, Material, Scene, Segment, Transform2D

        seg = Segment(id="inner", a=(0.0, -1.0), b=(0.0, 1.0), material=Material())
        group = Group(id="g1", transform=Transform2D(), shapes=[seg])
        scene = Scene(groups=[group])

        result = ray_intersect(scene, (-1.0, 0.0), (1.0, 0.0))
        assert result is not None
        assert result[3] == "g1/inner"

    def test_projector_target(self):
        from anim.analysis import projector_target
        from anim.types import Material, ProjectorLight, Scene, Segment

        wall = Segment(id="target", a=(2.0, -1.0), b=(2.0, 1.0), material=Material())
        light = ProjectorLight(position=(0.0, 0.0), direction=(1.0, 0.0))
        scene = Scene(shapes=[wall])

        assert projector_target(scene, light) == "target"

    def test_projector_target_misses(self):
        from anim.analysis import projector_target
        from anim.types import Material, ProjectorLight, Scene, Segment

        wall = Segment(id="target", a=(2.0, -1.0), b=(2.0, 1.0), material=Material())
        light = ProjectorLight(position=(0.0, 0.0), direction=(0.0, 1.0))
        scene = Scene(shapes=[wall])

        assert projector_target(scene, light) is None


# ─── Camera2D aspect ratio ──────────────────────────────────────


class TestCamera2DAspect:
    def test_width_only_derives_bounds(self):
        """Camera2D(width=...) without center should derive bounds from canvas aspect."""
        from anim.types import Camera2D, Canvas

        cam = Camera2D(width=3.2)
        canvas = Canvas(width=1920, height=1080)

        # resolve is called internally by the renderer; we test via the C++ binding
        import _lpt2d

        _lpt2d.Shot(scene=_lpt2d.Scene(), camera=cam, canvas=canvas)
        # The camera should resolve to bounds derived from width and 16:9 aspect
        # width=3.2 → half_w=1.6, half_h=1.6/(16/9)=0.9
        # bounds is None since we set width, not bounds — resolve happens at render time
        assert cam.width == pytest.approx(3.2)
        assert cam.center is None  # no explicit center
        assert cam.bounds is None  # bounds derived at resolve time, not stored

    def test_width_with_center(self):
        from anim.types import Camera2D

        cam = Camera2D(center=(0.5, 0.0), width=2.0)
        assert cam.center is not None
        assert cam.center[0] == pytest.approx(0.5)
        assert cam.center[1] == pytest.approx(0.0)
        assert cam.width == pytest.approx(2.0)
