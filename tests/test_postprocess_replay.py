from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import _lpt2d
from anim import (
    Camera2D,
    Canvas,
    Frame,
    Look,
    Material,
    PointLight,
    Scene,
    Shot,
    Timeline,
    TraceDefaults,
    render_frame_variants,
)
from anim import renderer as renderer_mod


W = 96
H = 64
RAYS = 30_000


def _scene(offset: float = 0.0) -> _lpt2d.Scene:
    return _lpt2d.Scene(
        materials={
            "glass": _lpt2d.Material(
                ior=1.45,
                transmission=1.0,
                absorption=0.1,
                cauchy_b=500.0,
                fill=0.04,
            )
        },
        shapes=[
            _lpt2d.Circle(
                material_id="glass",
                id="lens",
                center=[offset, 0.0],
                radius=0.24,
            )
        ],
        lights=[
            _lpt2d.PointLight(
                id="light_0",
                position=[-0.75, 0.12],
                intensity=1.0,
                wavelength_min=500.0,
                wavelength_max=660.0,
            )
        ],
    )


def _look(**overrides) -> _lpt2d.Look:
    look = _lpt2d.Look(
        exposure=-3.5,
        contrast=1.02,
        gamma=1.8,
        tonemap="reinhardx",
        white_point=0.55,
        normalize="rays",
        saturation=1.0,
        temperature=0.0,
        vignette=0.0,
    )
    for key, value in overrides.items():
        setattr(look, key, value)
    return look


def _shot(look: _lpt2d.Look, scene: _lpt2d.Scene | None = None) -> _lpt2d.Shot:
    return _lpt2d.Shot(
        scene=scene or _scene(),
        camera=_lpt2d.Camera2D(center=[0.0, 0.0], width=2.0),
        canvas=_lpt2d.Canvas(W, H),
        look=look,
        trace=_lpt2d.TraceDefaults(
            rays=RAYS,
            batch=RAYS,
            depth=5,
            intensity=1.0,
            seed_mode="deterministic",
        ),
    )


def _render_full(
    look: _lpt2d.Look,
    *,
    scene: _lpt2d.Scene | None = None,
    analyze: bool = False,
    half_float: bool = False,
) -> _lpt2d.RenderResult:
    session = _lpt2d.RenderSession(W, H, half_float)
    try:
        return session.render_shot(_shot(look, scene), 0, analyze)
    finally:
        session.close()


def _render_replay(
    first_look: _lpt2d.Look,
    replay_look: _lpt2d.Look,
    *,
    scene: _lpt2d.Scene | None = None,
    analyze: bool = False,
    half_float: bool = False,
) -> _lpt2d.RenderResult:
    session = _lpt2d.RenderSession(W, H, half_float)
    try:
        session.render_shot(_shot(first_look, scene), 0, False)
        return session.postprocess(replay_look.to_post_process(), analyze)
    finally:
        session.close()


def _assert_metrics_equal(a: _lpt2d.ImageStats, b: _lpt2d.ImageStats) -> None:
    for name in (
        "width",
        "height",
        "mean_luma",
        "median_luma",
        "p05_luma",
        "p95_luma",
        "near_black_fraction",
        "near_white_fraction",
        "clipped_channel_fraction",
        "rms_contrast",
        "interdecile_luma_range",
        "interdecile_luma_contrast",
        "local_contrast",
        "mean_saturation",
        "p95_saturation",
        "colorfulness",
        "bright_neutral_fraction",
    ):
        assert getattr(a, name) == pytest.approx(getattr(b, name))


def _assert_metrics_equivalent(
    a: _lpt2d.ImageStats,
    b: _lpt2d.ImageStats,
) -> None:
    assert a.width == b.width
    assert a.height == b.height
    assert a.mean_luma == pytest.approx(b.mean_luma, abs=0.01 / 255.0)
    assert a.median_luma == pytest.approx(b.median_luma, abs=1.0 / 255.0)
    assert a.rms_contrast == pytest.approx(b.rms_contrast, abs=0.05 / 255.0)
    assert a.interdecile_luma_range == pytest.approx(
        b.interdecile_luma_range, abs=1.0 / 255.0
    )
    assert a.near_black_fraction == pytest.approx(b.near_black_fraction, abs=0.001)
    assert a.near_white_fraction == pytest.approx(b.near_white_fraction, abs=0.001)
    assert a.clipped_channel_fraction == pytest.approx(b.clipped_channel_fraction, abs=0.001)
    assert a.mean_saturation == pytest.approx(b.mean_saturation, abs=0.01)
    assert a.colorfulness == pytest.approx(b.colorfulness, abs=0.01)


def _pixel_delta(a: bytes, b: bytes) -> tuple[int, int, float]:
    aa = np.frombuffer(a, dtype=np.uint8)
    bb = np.frombuffer(b, dtype=np.uint8)
    diff = np.abs(aa.astype(np.int16) - bb.astype(np.int16))
    changed = int(np.count_nonzero(diff))
    max_diff = int(diff.max()) if diff.size else 0
    changed_fraction = changed / float(diff.size) if diff.size else 0.0
    return changed, max_diff, changed_fraction


def _assert_pixels_equivalent(
    a: bytes,
    b: bytes,
    *,
    max_diff: int = 1,
    max_changed_fraction: float = 0.001,
) -> None:
    if a == b:
        return
    changed, observed_max_diff, changed_fraction = _pixel_delta(a, b)
    assert observed_max_diff <= max_diff
    assert changed_fraction <= max_changed_fraction, (
        f"{changed} channels changed ({changed_fraction:.3%})"
    )


@pytest.mark.parametrize(
    "replay_look",
    [
        _look(exposure=-2.8),
        _look(gamma=0.7),
        _look(tonemap="none", gamma=1.0, normalize="fixed", normalize_ref=15_000.0),
        _look(tonemap="aces", temperature=0.2, saturation=0.8),
        _look(vignette=0.35, vignette_radius=0.65),
        _look(normalize="max", normalize_pct=1.0),
        _look(normalize="max", normalize_pct=0.99),
    ],
)
def test_postprocess_matches_full_render_sweep(replay_look: _lpt2d.Look):
    full = _render_full(replay_look)
    replay = _render_replay(_look(exposure=-4.5), replay_look)

    # On this EGL/NVIDIA stack, independent deterministic full renders can
    # differ by one display code in isolated channels. Replay should stay
    # within that existing cross-session floor.
    _assert_pixels_equivalent(replay.pixels, full.pixels)
    _assert_metrics_equivalent(replay.metrics, full.metrics)
    assert replay.total_rays == full.total_rays
    assert replay.max_hdr == pytest.approx(full.max_hdr, abs=0.1)


def test_postprocess_analyze_true_matches_full_render_analysis():
    replay_look = _look(gamma=0.8, exposure=-3.0, temperature=0.1)

    full = _render_full(replay_look, analyze=True)
    replay = _render_replay(_look(exposure=-4.5), replay_look, analyze=True)

    _assert_pixels_equivalent(replay.pixels, full.pixels)
    _assert_metrics_equal(replay.metrics, full.metrics)
    _assert_metrics_equal(replay.analysis.image, full.analysis.image)
    _assert_metrics_equal(replay.metrics, replay.analysis.image)
    assert len(list(replay.analysis.lights)) == len(list(full.analysis.lights))


def test_postprocess_half_float_matches_full_render():
    replay_look = _look(gamma=1.2, contrast=1.05)

    full = _render_full(replay_look, half_float=True)
    replay = _render_replay(_look(exposure=-4.5), replay_look, half_float=True)

    _assert_pixels_equivalent(
        replay.pixels,
        full.pixels,
        max_diff=3,
        max_changed_fraction=0.08,
    )
    assert replay.metrics.mean_luma == pytest.approx(full.metrics.mean_luma, abs=0.1 / 255.0)
    assert replay.metrics.median_luma == pytest.approx(
        full.metrics.median_luma, abs=1.0 / 255.0
    )
    assert replay.metrics.width == full.metrics.width
    assert replay.metrics.height == full.metrics.height


def test_postprocess_before_render_raises():
    session = _lpt2d.RenderSession(W, H)
    try:
        with pytest.raises(RuntimeError, match="no frame"):
            session.postprocess(_look().to_post_process())
    finally:
        session.close()


def test_postprocess_after_resize_raises():
    session = _lpt2d.RenderSession(W, H)
    try:
        session.render_shot(_shot(_look()), 0, False)
        session.resize(W + 8, H + 8)
        with pytest.raises(RuntimeError, match="no frame"):
            session.postprocess(_look(gamma=1.1).to_post_process())
    finally:
        session.close()


def test_postprocess_after_noop_resize_preserves_replay():
    replay_look = _look(gamma=0.9, exposure=-3.0)
    full = _render_full(replay_look)

    session = _lpt2d.RenderSession(W, H)
    try:
        session.render_shot(_shot(_look()), 0, False)
        session.resize(W, H)
        replay = session.postprocess(replay_look.to_post_process())
    finally:
        session.close()

    _assert_pixels_equivalent(replay.pixels, full.pixels)
    _assert_metrics_equivalent(replay.metrics, full.metrics)


def test_postprocess_after_close_raises():
    session = _lpt2d.RenderSession(W, H)
    session.render_shot(_shot(_look()), 0, False)
    session.close()
    with pytest.raises(RuntimeError, match="closed"):
        session.postprocess(_look(gamma=1.1).to_post_process())


def test_postprocess_tracks_latest_trace():
    look = _look(gamma=1.1, exposure=-3.1)
    scene_a = _scene(offset=-0.15)
    scene_b = _scene(offset=0.18)

    session = _lpt2d.RenderSession(W, H)
    try:
        session.render_shot(_shot(_look(), scene_a), 0, False)
        session.render_shot(_shot(_look(), scene_b), 0, False)
        replay = session.postprocess(look.to_post_process())
    finally:
        session.close()

    full_b = _render_full(look, scene=scene_b)
    full_a = _render_full(look, scene=scene_a)

    _assert_pixels_equivalent(replay.pixels, full_b.pixels)
    changed, max_diff, changed_fraction = _pixel_delta(replay.pixels, full_a.pixels)
    assert changed_fraction > 0.10
    assert max_diff > 10


def test_render_frame_variants_uses_named_dict_overrides():
    scene = Scene(
        materials={"glass": Material(ior=1.45, transmission=1.0, fill=0.04)},
        shapes=[_lpt2d.Circle(material_id="glass", id="lens", center=[0.0, 0.0], radius=0.24)],
        lights=[
            PointLight(
                id="light_0",
                position=[-0.75, 0.12],
                intensity=1.0,
                wavelength_min=500.0,
                wavelength_max=660.0,
            )
        ],
    )

    def animate(_ctx):
        return scene

    settings = Shot(
        camera=Camera2D(center=[0.0, 0.0], width=2.0),
        canvas=Canvas(W, H),
        look=Look(exposure=-3.5, gamma=1.8, tonemap="reinhardx", normalize="rays"),
        trace=TraceDefaults(rays=RAYS, batch=RAYS, depth=5, seed_mode="deterministic"),
    )
    variants = render_frame_variants(
        animate,
        Timeline(1.0, fps=1),
        settings=settings,
        variants={
            "base": {},
            "low_gamma": {"gamma": 0.8, "exposure": -3.0},
        },
        analyze=True,
    )

    assert list(variants) == ["base", "low_gamma"]
    assert variants["low_gamma"].look.gamma == pytest.approx(0.8)
    assert variants["low_gamma"].result.metrics.mean_luma == pytest.approx(
        variants["low_gamma"].result.analysis.image.mean_luma
    )

    full = _render_full(variants["low_gamma"].look, scene=scene, analyze=True)
    _assert_pixels_equivalent(variants["low_gamma"].result.pixels, full.pixels)


def test_iter_frame_variants_auto_names_and_closes_on_early_break(monkeypatch):
    closed: list[bool] = []
    calls: list[str] = []

    class FakeSession:
        def __init__(self, width: int, height: int, fast: bool = False) -> None:
            self.width = width
            self.height = height
            self.fast = fast

        def render_shot(self, shot, frame: int = 0, analyze: bool = False):
            calls.append(f"render:{shot.look.exposure:.1f}:{shot.look.gamma:.1f}:{analyze}")
            return SimpleNamespace(pixels=b"first")

        def postprocess(self, pp, analyze: bool = False):
            calls.append(f"post:{pp.exposure:.1f}:{pp.gamma:.1f}:{analyze}")
            return SimpleNamespace(pixels=b"next")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(renderer_mod, "RenderSession", FakeSession)

    def animate(_ctx):
        return Frame(scene=Scene(), look={"gamma": 1.5})

    gen = renderer_mod.iter_frame_variants(
        animate,
        Timeline(1.0, fps=1),
        settings=Shot(canvas=Canvas(10, 8), look=Look(exposure=-4.0, gamma=2.0)),
        variants=[{"exposure": -1.0}, ("warm", {"gamma": 0.9})],
        analyze=True,
    )

    first = next(gen)
    assert first.name == "variant_000"
    assert first.look.gamma == pytest.approx(1.5)
    assert first.look.exposure == pytest.approx(-1.0)

    second = next(gen)
    assert second.name == "warm"
    assert second.look.gamma == pytest.approx(0.9)
    assert second.look.exposure == pytest.approx(-4.0)

    gen.close()
    assert closed == [True]
    assert calls == ["render:-1.0:1.5:True", "post:-4.0:0.9:True"]
