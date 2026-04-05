"""Unit tests for the 3.2 workflow helpers: Scene/Group/Shot/Look mutation methods."""

from __future__ import annotations

import json

from anim.types import (
    Camera2D,
    Canvas,
    Circle,
    Frame,
    FrameReport,
    Group,
    Look,
    Material,
    Scene,
    Shot,
    TraceDefaults,
)
from anim import renderer as renderer_mod


def _install_capturing_renderer(monkeypatch):
    captured: list[dict] = []

    class DummyRenderer:
        def __init__(self, shot=None, binary=renderer_mod.DEFAULT_BINARY, fast=False, histogram=False):
            assert shot is not None
            self.width = shot.canvas.width
            self.height = shot.canvas.height
            self.last_report = None

        def render_frame(self, wire_json: str) -> bytes:
            captured.append(json.loads(wire_json))
            histogram = [self.width * self.height] + [0] * 255
            self.last_report = FrameReport(
                frame=0,
                rays=1,
                time_ms=1,
                max_hdr=123.0,
                total_rays=1,
                mean=0.0,
                pct_black=1.0,
                pct_clipped=0.0,
                p50=0.0,
                p95=0.0,
                histogram=histogram,
            )
            return bytes(self.width * self.height * 3)

        def close(self):
            pass

    monkeypatch.setattr(renderer_mod, "Renderer", DummyRenderer)
    return captured


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


def test_shot_preset_returns_isolated_mutable_state():
    first = Shot.preset("draft", width=123, rays=654_321)
    second = Shot.preset("draft")

    assert first.canvas.width == 123
    assert first.trace.rays == 654_321
    assert second.canvas == Canvas(480, 480)
    assert second.trace == TraceDefaults(rays=200_000, batch=100_000, depth=6)

    first.canvas.height = 999
    first.trace.depth = 42
    third = Shot.preset("draft")
    assert third.canvas == Canvas(480, 480)
    assert third.trace == TraceDefaults(rays=200_000, batch=100_000, depth=6)


def test_look_with_overrides():
    look = Look(exposure=-5.0, gamma=2.0)
    new_look = look.with_overrides(exposure=4.0)
    assert look.exposure == -5.0
    assert new_look.exposure == 4.0
    assert new_look.gamma == 2.0


def test_render_stats_uses_shot_camera_when_no_override(monkeypatch):
    captured = _install_capturing_renderer(monkeypatch)
    shot = Shot(camera=Camera2D(bounds=[1.0, 2.0, 3.0, 4.0]), canvas=Canvas(width=2, height=2))

    renderer_mod.render_stats(lambda ctx: Scene(), 1.0, frames=0, settings=shot)

    assert captured[-1]["render"]["bounds"] == [1.0, 2.0, 3.0, 4.0]


def test_render_stats_explicit_camera_overrides_shot_camera(monkeypatch):
    captured = _install_capturing_renderer(monkeypatch)
    shot = Shot(camera=Camera2D(bounds=[1.0, 2.0, 3.0, 4.0]), canvas=Canvas(width=2, height=2))
    explicit = Camera2D(bounds=[5.0, 6.0, 7.0, 8.0])

    renderer_mod.render_stats(lambda ctx: Scene(), 1.0, frames=0, settings=shot, camera=explicit)

    assert captured[-1]["render"]["bounds"] == [5.0, 6.0, 7.0, 8.0]


def test_render_stats_frame_camera_overrides_explicit_and_shot_camera(monkeypatch):
    captured = _install_capturing_renderer(monkeypatch)
    shot = Shot(camera=Camera2D(bounds=[1.0, 2.0, 3.0, 4.0]), canvas=Canvas(width=2, height=2))
    explicit = Camera2D(bounds=[5.0, 6.0, 7.0, 8.0])
    frame_camera = Camera2D(bounds=[9.0, 10.0, 11.0, 12.0])

    renderer_mod.render_stats(
        lambda ctx: Frame(scene=Scene(), camera=frame_camera),
        1.0,
        frames=0,
        settings=shot,
        camera=explicit,
    )

    assert captured[-1]["render"]["bounds"] == [9.0, 10.0, 11.0, 12.0]


def test_render_stats_resolves_center_width_camera_with_canvas_aspect(monkeypatch):
    captured = _install_capturing_renderer(monkeypatch)
    shot = Shot(
        camera=Camera2D(center=[1.0, 2.0], width=4.0),
        canvas=Canvas(width=300, height=150),
    )

    renderer_mod.render_stats(lambda ctx: Scene(), 1.0, frames=0, settings=shot)

    assert captured[-1]["render"]["bounds"] == [-1.0, 1.0, 3.0, 3.0]


def test_calibrate_normalize_ref_uses_shot_camera_when_no_override(monkeypatch):
    captured = _install_capturing_renderer(monkeypatch)
    shot = Shot(camera=Camera2D(bounds=[-2.0, -1.0, 2.0, 1.0]), canvas=Canvas(width=2, height=2))

    max_hdr = renderer_mod.calibrate_normalize_ref(
        lambda ctx: Scene(),
        1.0,
        settings=shot,
        frame=0,
    )

    assert max_hdr == 123.0
    assert captured[-1]["render"]["bounds"] == [-2.0, -1.0, 2.0, 1.0]


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
