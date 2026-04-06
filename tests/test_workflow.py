"""Unit tests for the 3.2 workflow helpers: Scene/Group/Shot/Look mutation methods."""

from __future__ import annotations

import json

import pytest

from anim import analysis as analysis_mod
from anim import light_analysis as light_analysis_mod
from anim import renderer as renderer_mod
from anim.types import (
    Camera2D,
    Canvas,
    Circle,
    Frame,
    FrameReport,
    Group,
    Look,
    Material,
    PointLight,
    Scene,
    Shot,
    TraceDefaults,
)


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
    g1 = Group(id="prism")
    g2 = Group(id="mirror")
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
    g = Group(id="test", shapes=[Circle(center=[0, 0], radius=0.5, material=Material())])
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


def test_render_stats_frame_look_keeps_partial_override_semantics(monkeypatch):
    captured = _install_capturing_renderer(monkeypatch)
    shot = Shot(look=Look(vignette=0.35, vignette_radius=1.1), canvas=Canvas(width=2, height=2))

    renderer_mod.render_stats(
        lambda ctx: Frame(scene=Scene(), look=Look(exposure=1.25)),
        1.0,
        frames=0,
        settings=shot,
    )

    assert captured[-1]["render"]["exposure"] == 1.25
    assert "vignette" not in captured[-1]["render"]
    assert "vignette_radius" not in captured[-1]["render"]


def test_render_stats_frame_look_can_explicitly_reset_vignette(monkeypatch):
    captured = _install_capturing_renderer(monkeypatch)
    shot = Shot(look=Look(vignette=0.35, vignette_radius=1.1), canvas=Canvas(width=2, height=2))

    renderer_mod.render_stats(
        lambda ctx: Frame(scene=Scene(), look=Look(vignette=0.0, vignette_radius=0.7)),
        1.0,
        frames=0,
        settings=shot,
    )

    assert captured[-1]["render"]["vignette"] == 0.0
    assert captured[-1]["render"]["vignette_radius"] == 0.7


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

    max_hdr = analysis_mod.calibrate_normalize_ref(
        lambda ctx: Scene(),
        1.0,
        settings=shot,
        frame=0,
    )

    assert max_hdr == 123.0
    assert captured[-1]["render"]["bounds"] == [-2.0, -1.0, 2.0, 1.0]


def test_auto_look_defaults_to_rays_normalization(monkeypatch):
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

    look = analysis_mod.auto_look(Scene(), 1.0)

    assert look.normalize == "rays"
    assert look.tonemap == "reinhardx"


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
    monkeypatch.setattr(analysis_mod, "calibrate_normalize_ref", fake_calibrate)

    look = analysis_mod.auto_look(Scene(), 1.0, normalize="rays")

    assert look.normalize == "rays"
    assert look.normalize_ref == 0.0
    assert called["count"] == 0


def test_auto_look_shot_subject_uses_authored_camera_and_aspect(monkeypatch):
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

    assert captured["camera"] == shot.camera
    assert captured["frames"] == [0]
    assert captured["settings"].canvas == Canvas(width=480, height=270)
    assert captured["settings"].trace.batch == 100_000
    assert captured["settings"].trace.depth == 9


def test_auto_look_preserves_authored_look_fields(monkeypatch):
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
    assert captured["look"].background == [0.1, 0.2, 0.3]
    assert captured["look"].opacity == pytest.approx(0.8)
    assert captured["look"].saturation == pytest.approx(1.4)
    assert captured["look"].vignette == pytest.approx(0.25)
    assert captured["look"].vignette_radius == pytest.approx(1.1)
    assert look.white_point == pytest.approx(1.7)
    assert look.ambient == pytest.approx(0.12)
    assert look.background == [0.1, 0.2, 0.3]
    assert look.opacity == pytest.approx(0.8)
    assert look.saturation == pytest.approx(1.4)
    assert look.vignette == pytest.approx(0.25)
    assert look.vignette_radius == pytest.approx(1.1)


def test_auto_look_enforces_max_clipping(monkeypatch):
    calls: list[float] = []

    def fake_render_stats(*args, **kwargs):
        exposure = kwargs["settings"].look.exposure
        calls.append(exposure)
        clipping = 0.08 if exposure > 2.0 else (0.03 if exposure > 1.0 else 0.0)
        sample = renderer_mod.FrameStats(
            mean=0.3,
            max=200,
            min=0,
            std=10.0,
            pct_black=0.2,
            pct_clipped=clipping,
            p05=1.0,
            p50=40.0,
            p95=120.0,
            width=100,
            height=100,
        )
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    look = analysis_mod.auto_look(Scene(), 1.0, max_clipping=0.02)

    assert len(calls) > 2
    assert look.exposure <= 1.0


def test_compare_looks_uses_shot_subject_defaults(monkeypatch):
    sample = renderer_mod.FrameStats(
        mean=90.0,
        max=220,
        min=0,
        std=10.0,
        pct_black=0.1,
        pct_clipped=0.0,
        p05=2.0,
        p50=60.0,
        p95=180.0,
        width=480,
        height=270,
    )
    captured: list[dict] = []
    shot = Shot(
        camera=Camera2D(bounds=[-2.0, -1.0, 2.0, 1.0]),
        canvas=Canvas(width=960, height=540),
        trace=TraceDefaults(rays=800_000, batch=140_000, depth=8),
    )

    def fake_render_stats(*args, **kwargs):
        captured.append({"settings": kwargs["settings"], "frames": kwargs["frames"]})
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    analysis_mod.compare_looks(shot, looks=[Look(), Look(exposure=1.0)])

    assert len(captured) == 2
    assert all(entry["frames"] == [0] for entry in captured)
    assert all(entry["settings"].canvas == Canvas(width=480, height=270) for entry in captured)
    assert all(entry["settings"].trace.depth == 8 for entry in captured)


def test_look_report_shot_subject_samples_single_frame(monkeypatch):
    sample = renderer_mod.FrameStats(
        mean=90.0,
        max=220,
        min=0,
        std=10.0,
        pct_black=0.1,
        pct_clipped=0.0,
        p05=2.0,
        p50=60.0,
        p95=180.0,
        width=480,
        height=270,
    )
    captured: dict = {}
    shot = Shot(
        camera=Camera2D(bounds=[-2.0, -1.0, 2.0, 1.0]),
        canvas=Canvas(width=960, height=540),
        trace=TraceDefaults(rays=800_000, batch=140_000, depth=8),
    )

    def fake_render_stats(*args, **kwargs):
        captured["frames"] = kwargs["frames"]
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    report = analysis_mod.look_report(shot, shot.look)

    assert captured["frames"] == [0]
    assert len(report.profile.per_frame) == 1


def test_light_contributions_use_neutral_fixed_reference(monkeypatch):
    captured: list[Shot] = []
    sample = renderer_mod.FrameStats(
        mean=50.0,
        max=120,
        min=0,
        std=8.0,
        pct_black=0.25,
        pct_clipped=0.0,
        p05=1.0,
        p50=20.0,
        p95=90.0,
        width=480,
        height=270,
    )
    scene = Scene(lights=[PointLight(id="beam_main", pos=[0.0, 0.0], intensity=1.0)])

    def fake_calibrate(*args, **kwargs):
        return 250.0

    def fake_render_stats(*args, **kwargs):
        captured.append(kwargs["settings"])
        return [(0, 0.0, sample)]

    monkeypatch.setattr(analysis_mod, "calibrate_normalize_ref", fake_calibrate)
    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    contribs = light_analysis_mod.light_contributions(scene)

    assert len(contribs) == 1
    assert contribs[0].source_id == "beam_main"
    assert contribs[0].share == 1.0
    assert captured[0].look.tonemap == "none"
    assert captured[0].look.gamma == 1.0
    assert captured[0].look.normalize == "fixed"
    assert captured[0].look.normalize_ref == 250.0


def test_light_contributions_keep_unnamed_emissive_shapes_distinct(monkeypatch):
    captured_scenes: list[Scene] = []
    sample = renderer_mod.FrameStats(
        mean=40.0,
        max=100,
        min=0,
        std=5.0,
        pct_black=0.5,
        pct_clipped=0.0,
        p05=1.0,
        p50=10.0,
        p95=80.0,
        width=480,
        height=270,
    )
    scene = Scene(
        shapes=[
            Circle(center=[-0.5, 0.0], radius=0.1, material=Material(emission=1.0)),
            Circle(center=[0.5, 0.0], radius=0.1, material=Material(emission=2.0)),
        ]
    )

    def fake_calibrate(*args, **kwargs):
        return 125.0

    def fake_render_stats(*args, **kwargs):
        captured_scenes.append(kwargs["settings"].scene)
        return [(0, 0.0, sample)]

    monkeypatch.setattr(analysis_mod, "calibrate_normalize_ref", fake_calibrate)
    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    contribs = light_analysis_mod.light_contributions(scene)

    assert len(contribs) == 2
    assert len({c.source_id for c in contribs}) == 2
    assert scene.shapes[0].id == ""
    assert scene.shapes[1].id == ""
    assert captured_scenes[0].shapes[0].material.emission == 1.0
    assert captured_scenes[0].shapes[1].material.emission == 0.0
    assert captured_scenes[1].shapes[0].material.emission == 0.0
    assert captured_scenes[1].shapes[1].material.emission == 2.0


def test_light_contributions_normalize_unnamed_emissive_shapes_without_mutating_scene(monkeypatch):
    sample = renderer_mod.FrameStats(
        mean=25.0,
        max=90,
        min=0,
        std=4.0,
        pct_black=0.5,
        pct_clipped=0.0,
        p05=0.0,
        p50=10.0,
        p95=40.0,
        width=480,
        height=270,
    )
    scene = Scene(
        shapes=[
            Circle(center=[-0.5, 0.0], radius=0.1, material=Material(emission=1.0)),
            Circle(center=[0.5, 0.0], radius=0.1, material=Material(emission=1.0)),
        ]
    )

    monkeypatch.setattr(analysis_mod, "calibrate_normalize_ref", lambda *args, **kwargs: 100.0)
    monkeypatch.setattr(
        renderer_mod,
        "render_stats",
        lambda *args, **kwargs: [(0, 0.0, sample)],
    )

    contribs = light_analysis_mod.light_contributions(scene)

    assert len(contribs) == 2
    assert len({c.source_id for c in contribs}) == 2
    assert all(c.source_id for c in contribs)
    assert scene.shapes[0].id == ""
    assert scene.shapes[1].id == ""


def test_structure_contribution_rejects_unknown_shape_id():
    scene = Scene(shapes=[Circle(id="known", center=[0.0, 0.0], radius=0.5, material=Material())])

    with pytest.raises(ValueError, match="unknown shape id"):
        light_analysis_mod.structure_contribution(scene, "missing")


def test_structure_contribution_reports_dimmer_role(monkeypatch):
    scene = Scene(shapes=[Circle(id="known", center=[0.0, 0.0], radius=0.5, material=Material())])

    monkeypatch.setattr(
        light_analysis_mod,
        "_contribution_reference_shot",
        lambda *args, **kwargs: (scene, Shot(scene=scene)),
    )

    def fake_render_stats(*args, **kwargs):
        stats_scene = kwargs["settings"].scene
        mean = 20.0 if any(shape.id == "known" for shape in stats_scene.shapes) else 45.0
        sample = renderer_mod.FrameStats(
            mean=mean,
            max=100,
            min=0,
            std=5.0,
            pct_black=0.0,
            pct_clipped=0.0,
            p05=0.0,
            p50=10.0,
            p95=50.0,
            width=100,
            height=100,
        )
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    report = light_analysis_mod.structure_contribution(scene, "known")

    assert report.role == "dimmer"


def test_structure_contribution_reports_brightener_role(monkeypatch):
    scene = Scene(shapes=[Circle(id="known", center=[0.0, 0.0], radius=0.5, material=Material())])

    monkeypatch.setattr(
        light_analysis_mod,
        "_contribution_reference_shot",
        lambda *args, **kwargs: (scene, Shot(scene=scene)),
    )

    def fake_render_stats(*args, **kwargs):
        stats_scene = kwargs["settings"].scene
        mean = 45.0 if any(shape.id == "known" for shape in stats_scene.shapes) else 20.0
        sample = renderer_mod.FrameStats(
            mean=mean,
            max=100,
            min=0,
            std=5.0,
            pct_black=0.0,
            pct_clipped=0.0,
            p05=0.0,
            p50=10.0,
            p95=50.0,
            width=100,
            height=100,
        )
        return [(0, 0.0, sample)]

    monkeypatch.setattr(renderer_mod, "render_stats", fake_render_stats)

    report = light_analysis_mod.structure_contribution(scene, "known")

    assert report.role == "brightener"
