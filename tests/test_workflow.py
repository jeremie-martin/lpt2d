"""Unit tests for the 3.2 workflow helpers: Scene/Group/Shot/Look mutation methods."""

from __future__ import annotations

from anim.types import (
    Circle,
    Group,
    Look,
    Material,
    Scene,
    Shot,
    TraceDefaults,
)
from anim import renderer as renderer_mod


def test_scene_find_group():
    g1 = Group(name="prism")
    g2 = Group(name="mirror")
    scene = Scene(groups=[g1, g2])
    assert scene.find_group("prism") is g1
    assert scene.find_group("mirror") is g2
    assert scene.find_group("nonexistent") is None


def test_scene_find_group_empty():
    scene = Scene()
    assert scene.find_group("anything") is None


def test_scene_clone():
    mat = Material(ior=1.5)
    scene = Scene(shapes=[Circle(center=[0, 0], radius=1.0, material=mat)])
    cloned = scene.clone()
    assert cloned.shapes[0].center == [0, 0]
    # Mutating the clone should not affect the original
    cloned.shapes[0].center = [1, 1]
    assert scene.shapes[0].center == [0, 0]


def test_group_clone():
    g = Group(name="test", shapes=[Circle(center=[0, 0], radius=0.5, material=Material())])
    cloned = g.clone()
    cloned.shapes[0].center = [2, 2]
    assert g.shapes[0].center == [0, 0]


def test_shot_with_look():
    shot = Shot(look=Look(exposure=-5.0, tonemap="reinhardx"))
    new_shot = shot.with_look(exposure=5.0, tonemap="reinhard")
    # Original unchanged
    assert shot.look.exposure == -5.0
    assert shot.look.tonemap == "reinhardx"
    # New shot has overrides
    assert new_shot.look.exposure == 5.0
    assert new_shot.look.tonemap == "reinhard"
    # Other fields preserved
    assert new_shot.look.gamma == 2.0


def test_shot_with_trace():
    shot = Shot(trace=TraceDefaults(rays=10_000_000))
    new_shot = shot.with_trace(rays=50_000_000, depth=16)
    assert shot.trace.rays == 10_000_000
    assert new_shot.trace.rays == 50_000_000
    assert new_shot.trace.depth == 16


def test_look_with_overrides():
    look = Look(exposure=-5.0, gamma=2.0)
    new_look = look.with_overrides(exposure=4.0)
    assert look.exposure == -5.0
    assert new_look.exposure == 4.0
    assert new_look.gamma == 2.0


def test_auto_look_infers_fixed_normalization(monkeypatch):
    sample = renderer_mod.FrameStats(
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
    monkeypatch.setattr(renderer_mod, "calibrate_normalize_ref", lambda *args, **kwargs: 321.0)

    look = renderer_mod.auto_look(Scene(), 1.0)

    assert look.normalize == "fixed"
    assert look.normalize_ref == 321.0


def test_auto_look_respects_explicit_normalize(monkeypatch):
    sample = renderer_mod.FrameStats(
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

    called = {"count": 0}

    def fake_calibrate(*args, **kwargs):
        called["count"] += 1
        return 123.0

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)
    monkeypatch.setattr(renderer_mod, "calibrate_normalize_ref", fake_calibrate)

    look = renderer_mod.auto_look(Scene(), 1.0, normalize="rays")

    assert look.normalize == "rays"
    assert look.normalize_ref == 0.0
    assert called["count"] == 0
