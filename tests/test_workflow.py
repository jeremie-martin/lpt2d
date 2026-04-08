"""Unit tests for workflow helpers: Scene/Group/Shot/Look mutation methods."""

from __future__ import annotations

import pytest

from anim import analysis as analysis_mod
from anim import renderer as renderer_mod
from anim.stats import FrameStats
from anim.types import (
    Camera2D,
    Canvas,
    Circle,
    Group,
    Look,
    Material,
    Scene,
    Shot,
    TraceDefaults,
)

# ── Pure API tests ────────────────────────────────────────────────


def test_scene_find_group():
    g1 = Group(id="prism")
    g2 = Group(id="mirror")
    scene = Scene(groups=[g1, g2])
    prism = scene.find_group("prism")
    assert prism is not None and prism.id == "prism"
    mirror = scene.find_group("mirror")
    assert mirror is not None and mirror.id == "mirror"
    assert scene.find_group("nonexistent") is None


def test_scene_find_group_empty():
    scene = Scene()
    assert scene.find_group("anything") is None


def test_scene_clone():
    mat = Material(ior=1.5)
    scene = Scene(shapes=[Circle(center=[0, 0], radius=1.0, material=mat)])
    cloned = scene.clone()
    c0 = cloned.shapes[0]
    assert isinstance(c0, Circle)
    assert c0.center == (0, 0)
    c0.center = [1, 1]
    o0 = scene.shapes[0]
    assert isinstance(o0, Circle)
    assert o0.center == (0, 0)


def test_shot_with_look():
    shot = Shot(look=Look(exposure=-5.0, tonemap="reinhardx"))
    new_shot = shot.with_look(exposure=5.0, tonemap="reinhard")
    assert shot.look.exposure == -5.0
    assert shot.look.tonemap == "reinhardx"
    assert new_shot.look.exposure == 5.0
    assert new_shot.look.tonemap == "reinhard"
    assert new_shot.look.gamma == 2.0


def test_shot_with_trace():
    shot = Shot(trace=TraceDefaults(rays=10_000_000, seed_mode="decorrelated"))
    new_shot = shot.with_trace(rays=50_000_000, depth=16)
    assert shot.trace.rays == 10_000_000
    assert shot.trace.seed_mode == "decorrelated"
    assert new_shot.trace.rays == 50_000_000
    assert new_shot.trace.depth == 16
    assert new_shot.trace.seed_mode == "decorrelated"


def test_shot_with_trace_can_override_seed_mode():
    shot = Shot(trace=TraceDefaults(seed_mode="deterministic"))
    new_shot = shot.with_trace(seed_mode="decorrelated")

    assert shot.trace.seed_mode == "deterministic"
    assert new_shot.trace.seed_mode == "decorrelated"


def test_trace_defaults_to_trace_config_accepts_runtime_frame():
    trace = TraceDefaults(batch=1234, depth=9, intensity=2.5, seed_mode="decorrelated")

    default_cfg = trace.to_trace_config()
    cfg = trace.to_trace_config(7)

    assert default_cfg.frame == 0
    assert cfg.batch_size == 1234
    assert cfg.depth == 9
    assert cfg.intensity == pytest.approx(2.5)
    assert cfg.seed_mode == "decorrelated"
    assert cfg.frame == 7


def test_shot_preset_returns_isolated_mutable_state():
    first = Shot.preset("draft", width=123, rays=654_321)
    second = Shot.preset("draft")

    assert first.canvas.width == 123
    assert first.trace.rays == 654_321
    assert second.canvas.width == 480
    assert second.canvas.height == 480
    assert second.trace.rays == 200_000

    first.canvas.height = 999
    first.trace.depth = 42
    third = Shot.preset("draft")
    assert third.canvas.width == 480
    assert third.trace.rays == 200_000


def test_look_with_overrides():
    look = Look(exposure=-5.0, gamma=2.0)
    new_look = look.with_overrides(exposure=4.0)
    assert look.exposure == -5.0
    assert new_look.exposure == 4.0
    assert new_look.gamma == 2.0


# ── Render stats mocking tests ───────────────────────────────────
# These mock render_stats at the function level (not the old Renderer class).


def test_auto_look_defaults_to_rays_normalization(monkeypatch):
    sample = FrameStats(
        mean=64.0,
        max=200,
        min=0,
        std=10.0,
        pct_black=0.2,
        pct_clipped=0.0,
        p05=1.0,
        p50=40.0,
        p95=120.0,
        width=100,
        height=100,
    )

    def fake_render_stats(*args, **kwargs):
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    look = analysis_mod.auto_look(Scene(), 1.0)

    assert look.normalize == "rays"
    assert look.tonemap == "reinhardx"


def test_auto_look_respects_explicit_normalize(monkeypatch):
    sample = FrameStats(
        mean=64.0,
        max=200,
        min=0,
        std=10.0,
        pct_black=0.2,
        pct_clipped=0.0,
        p05=1.0,
        p50=40.0,
        p95=120.0,
        width=100,
        height=100,
    )

    called = {"count": 0}

    def fake_render_stats(*args, **kwargs):
        return [(0, 0.0, sample)]

    def fake_calibrate(*args, **kwargs):
        called["count"] += 1
        return 123.0

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)
    monkeypatch.setattr(analysis_mod, "calibrate_normalize_ref", fake_calibrate)

    look = analysis_mod.auto_look(Scene(), 1.0, normalize="rays")

    assert look.normalize == "rays"
    assert look.normalize_ref == 0.0
    assert called["count"] == 0


def test_auto_look_shot_subject_uses_authored_settings(monkeypatch):
    sample = FrameStats(
        mean=64.0,
        max=200,
        min=0,
        std=10.0,
        pct_black=0.2,
        pct_clipped=0.0,
        p05=1.0,
        p50=40.0,
        p95=120.0,
        width=480,
        height=270,
    )
    captured: dict = {}
    shot = Shot(
        camera=Camera2D(bounds=[-2.0, -1.0, 2.0, 1.0]),
        canvas=Canvas(width=960, height=540),
        trace=TraceDefaults(rays=900_000, batch=150_000, depth=9),
    )

    def fake_render_stats(*args, **kwargs):
        captured["frames"] = kwargs["frames"]
        captured["camera"] = kwargs["camera"]
        captured["settings"] = kwargs["settings"]
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    analysis_mod.auto_look(shot)

    assert captured["camera"].bounds is not None
    assert captured["frames"] == [0]
    assert captured["settings"].canvas.width == 480
    assert captured["settings"].canvas.height == 270
    assert captured["settings"].trace.batch == 100_000
    assert captured["settings"].trace.depth == 9


def test_auto_look_preserves_authored_look_fields(monkeypatch):
    sample = FrameStats(
        mean=64.0,
        max=200,
        min=0,
        std=10.0,
        pct_black=0.2,
        pct_clipped=0.0,
        p05=1.0,
        p50=40.0,
        p95=120.0,
        width=480,
        height=270,
    )
    captured: dict = {}
    shot = Shot(
        canvas=Canvas(width=960, height=540),
        trace=TraceDefaults(rays=900_000, batch=150_000, depth=9),
        look=Look(
            white_point=1.7,
            ambient=0.12,
            background=[0.1, 0.2, 0.3],
            opacity=0.8,
            saturation=1.4,
            vignette=0.25,
            vignette_radius=1.1,
        ),
    )

    def fake_render_stats(*args, **kwargs):
        captured["look"] = kwargs["settings"].look
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    look = analysis_mod.auto_look(shot)

    assert captured["look"].white_point == pytest.approx(1.7)
    assert captured["look"].ambient == pytest.approx(0.12)
    assert captured["look"].opacity == pytest.approx(0.8)
    assert captured["look"].saturation == pytest.approx(1.4)
    assert captured["look"].vignette == pytest.approx(0.25)
    assert captured["look"].vignette_radius == pytest.approx(1.1)
    # Result should preserve these authored fields
    assert look.white_point == pytest.approx(1.7)
    assert look.ambient == pytest.approx(0.12)
