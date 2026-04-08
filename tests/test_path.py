"""Tests for the Path shape type: construction, fitting, serialization, render."""

from __future__ import annotations

import json
import math
import tempfile

import pytest

import _lpt2d
from anim.builders import function_curve, path, path_from_samples
from anim.types import Material, Path

MAT = Material(transmission=1.0, ior=1.5)
MAT_ID = "glass"


# ─── Construction ────────────────────────────────────────────────


def test_path_explicit_3_points():
    p = path([[0, 0], [0.5, 1], [1, 0]], MAT_ID)
    assert isinstance(p, Path)
    assert len(p.points) == 3
    assert p.closed is False


def test_path_explicit_5_points():
    pts = [[0, 0], [0.25, 0.5], [0.5, 0], [0.75, -0.5], [1, 0]]
    p = path(pts, MAT_ID)
    assert len(p.points) == 5  # 2 Bezier segments


def test_path_explicit_closed():
    p = path([[0, 0], [0.5, 1], [1, 0]], MAT_ID, closed=True)
    assert p.closed is True


def test_path_rejects_even_length():
    with pytest.raises(ValueError):
        path([[0, 0], [1, 1]], MAT_ID)


def test_path_rejects_too_short():
    with pytest.raises(ValueError):
        path([[0, 0]], MAT_ID)


def test_path_id_prefix():
    p = path([[0, 0], [0.5, 1], [1, 0]], MAT_ID, id_prefix="wave")
    assert p.id == "wave_body"


# ─── Fitting ─────────────────────────────────────────────────────


def test_path_from_samples_2_points():
    p = path_from_samples([[0.0, 0.0], [1.0, 0.0]], MAT_ID)
    assert isinstance(p, Path)
    assert len(p.points) == 3  # 1 segment


def test_path_from_samples_4_points():
    pts = [[0.0, 0.0], [1.0, 1.0], [2.0, 0.0], [3.0, 1.0]]
    p = path_from_samples(pts, MAT_ID)
    # N=4 samples → N-2=2 Bezier segments → 2*2+1=5 points
    assert len(p.points) == 5
    assert len(p.points) % 2 == 1  # always odd


def test_path_from_samples_chain_is_odd():
    for n in range(3, 10):
        pts = [[float(i), 0.0] for i in range(n)]
        p = path_from_samples(pts, MAT_ID)
        assert len(p.points) % 2 == 1, f"n={n}: points={len(p.points)}"


def test_path_from_samples_endpoints_match():
    pts = [[0.0, 0.0], [1.0, 2.0], [3.0, 1.0], [4.0, 0.0]]
    p = path_from_samples(pts, MAT_ID)
    assert p.points[0] == pytest.approx([0, 0], abs=1e-6)
    assert p.points[-1] == pytest.approx([4, 0], abs=1e-6)


# ─── Function curve ──────────────────────────────────────────────


def test_function_curve_sine():
    p = function_curve(math.sin, (0, math.pi), MAT_ID, samples=16)
    assert isinstance(p, Path)
    assert len(p.points) >= 3
    assert len(p.points) % 2 == 1


# ─── Serialization round-trip ────────────────────────────────────


def test_path_json_round_trip():
    """Create a Shot with a Path, save to JSON, reload, verify."""
    pts = [[0, 0], [0.5, 1], [1, 0], [1.5, -1], [2, 0]]
    p = path(pts, MAT_ID, closed=True, id_prefix="test")

    scene = _lpt2d.Scene()
    scene.shapes = [p]
    scene.materials = {MAT_ID: MAT}

    shot = _lpt2d.Shot()
    shot.name = "path_test"
    shot.scene = scene
    shot.camera = _lpt2d.Camera2D()
    shot.camera = _lpt2d.Camera2D(bounds=_lpt2d.Bounds(min=[-1, -1], max=[3, 1]))
    shot.canvas = _lpt2d.Canvas()
    shot.canvas.width = 100
    shot.canvas.height = 100
    shot.look = _lpt2d.Look()
    shot.trace = _lpt2d.TraceDefaults()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        _lpt2d.save_shot(shot, f.name)
        loaded = _lpt2d.load_shot(f.name)

    loaded_path = loaded.scene.shapes[0]
    assert isinstance(loaded_path, Path)
    assert len(loaded_path.points) == 5
    assert loaded_path.closed is True
    assert loaded_path.id == "test_body"


def test_path_json_format():
    """Verify the JSON structure of a saved Path."""
    p = Path(id="p1", points=[[0, 0], [1, 1], [2, 0]], material_id=MAT_ID, closed=True)

    scene = _lpt2d.Scene()
    scene.shapes = [p]
    scene.materials = {MAT_ID: MAT}

    shot = _lpt2d.Shot()
    shot.name = "json_test"
    shot.scene = scene
    shot.camera = _lpt2d.Camera2D()
    shot.camera = _lpt2d.Camera2D(bounds=_lpt2d.Bounds(min=[-1, -1], max=[3, 1]))
    shot.canvas = _lpt2d.Canvas()
    shot.canvas.width = 100
    shot.canvas.height = 100
    shot.look = _lpt2d.Look()
    shot.trace = _lpt2d.TraceDefaults()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        _lpt2d.save_shot(shot, f.name)
        with open(f.name) as fh:
            data = json.load(fh)

    shapes = data["shapes"]
    assert len(shapes) == 1
    assert shapes[0]["type"] == "path"
    assert shapes[0]["closed"] is True
    assert len(shapes[0]["points"]) == 3
    assert shapes[0]["material_id"] == MAT_ID


# ─── Material binding ────────────────────────────────────────────


def test_path_material_id_round_trip_property():
    p = Path(id="p1", points=[[0, 0], [1, 1], [2, 0]], material_id=MAT_ID)
    assert p.material_id == MAT_ID


def test_path_material_id():
    p = Path(id="p1", points=[[0, 0], [1, 1], [2, 0]], material_id=MAT_ID)
    assert p.material_id == MAT_ID
