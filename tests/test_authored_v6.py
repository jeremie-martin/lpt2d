from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import _lpt2d
from anim.types import (
    Camera2D,
    Canvas,
    Circle,
    Group,
    Look,
    Material,
    ProjectorLight,
    RenderSession,
    Scene,
    Segment,
    Shot,
    TraceDefaults,
)

CLI_BINARY = Path(__file__).resolve().parents[1] / "build" / "lpt2d-cli"


def _make_bound_scene() -> Scene:
    return Scene(
        materials={"glass": Material(ior=1.5, transmission=1.0)},
        shapes=[
            Circle(id="lens_a", center=[-0.5, 0.0], radius=0.2, material_id="glass"),
            Circle(id="lens_b", center=[0.5, 0.0], radius=0.2, material_id="glass"),
        ],
        lights=[
            ProjectorLight(
                id="beam_main",
                position=[-1.0, 0.0],
                direction=[1.0, 0.0],
                source_radius=0.0,
                spread=0.02,
                intensity=1.0,
            )
        ],
        groups=[
            Group(
                id="cluster",
                shapes=[
                    Segment(
                        id="cluster_edge",
                        a=[-0.1, -0.2],
                        b=[0.1, -0.2],
                        material=Material(albedo=0.0),
                    )
                ],
            )
        ],
    )


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def _make_valid_shot_json(**overrides) -> dict:
    """Return a minimal valid v6 shot JSON dict."""
    base = {
        "version": 8,
        "name": "test",
        "camera": {},
        "canvas": {"width": 1920, "height": 1080},
        "look": {
            "exposure": -5.0,
            "contrast": 1.0,
            "gamma": 2.0,
            "tonemap": "reinhardx",
            "white_point": 0.5,
            "normalize": "rays",
            "normalize_ref": 0.0,
            "normalize_pct": 1.0,
            "ambient": 0.0,
            "background": [0.0, 0.0, 0.0],
            "opacity": 1.0,
            "saturation": 1.0,
            "vignette": 0.0,
            "vignette_radius": 0.7,
            "temperature": 0.0,
            "highlights": 0.0,
            "shadows": 0.0,
            "hue_shift": 0.0,
            "grain": 0.0,
            "grain_seed": 0,
            "chromatic_aberration": 0.0,
        },
        "trace": {
            "rays": 10000000,
            "batch": 200000,
            "depth": 12,
            "intensity": 1.0,
            "seed_mode": "deterministic",
        },
        "materials": {},
        "shapes": [],
        "lights": [],
        "groups": [],
    }
    base.update(overrides)
    return base


def _make_seed_behavior_shot(seed_mode: str) -> Shot:
    return Shot(
        name=f"seed_{seed_mode}",
        scene=Scene(
            shapes=[
                Circle(
                    id="lens",
                    center=[0.0, 0.0],
                    radius=0.25,
                    material=Material(ior=1.5, transmission=1.0),
                )
            ],
            lights=[
                ProjectorLight(
                    id="beam",
                    position=[-0.8, 0.05],
                    direction=[1.0, 0.0],
                    source_radius=0.0,
                    spread=0.08,
                    intensity=1.0,
                )
            ],
        ),
        canvas=Canvas(64, 64),
        look=Look(exposure=8.0, gamma=1.0, tonemap="none", normalize="off"),
        trace=TraceDefaults(rays=64, batch=64, depth=8, seed_mode=seed_mode),
    )


def _render_pixels(shot: Shot, frame_index: int) -> bytes:
    session = RenderSession(shot.canvas.width, shot.canvas.height, False)
    return session.render_shot(shot.to_cpp(), frame_index).pixels


# ─── Round-trip serialization via C++ ──────────────────────────────────


def test_v6_round_trip_preserves_ids_and_material_bindings(tmp_path):
    path = tmp_path / "roundtrip.json"
    shot = Shot(name="authored_v6", scene=_make_bound_scene())
    shot.save(path)

    loaded = Shot.load(path)

    assert loaded.scene.require_shape("lens_a").material_id == "glass"
    assert loaded.scene.require_shape("lens_b").material_id == "glass"
    assert loaded.scene.require_light("beam_main").id == "beam_main"
    assert loaded.scene.require_group("cluster").id == "cluster"
    assert loaded.scene.require_shape("cluster_edge").id == "cluster_edge"


# ─── Scene validation via C++ ──────────────────────────────────────────


def test_v6_rejects_duplicate_entity_ids():
    scene = Scene(
        shapes=[
            Circle(id="dup", radius=0.2),
            Circle(id="dup", center=[1.0, 0.0], radius=0.3),
        ]
    )

    with pytest.raises(RuntimeError, match="duplicate entity id: dup"):
        _lpt2d.validate_scene(scene)


def test_v6_rejects_unknown_material_id():
    scene = Scene(shapes=[Circle(id="lens", radius=0.2, material_id="missing")])

    with pytest.raises(RuntimeError, match="unknown material_id: missing"):
        _lpt2d.validate_scene(scene)


def test_v6_rejects_shape_without_material_payload(tmp_path):
    path = tmp_path / "bad.json"
    data = _make_valid_shot_json(
        name="bad",
        shapes=[{"id": "lens", "type": "circle", "center": [0.0, 0.0], "radius": 0.2}],
    )
    _write_json(path, data)

    with pytest.raises(RuntimeError, match="shape entries must declare exactly one of material and material_id"):
        Shot.load(path)


# ─── Scene ID lookup helpers ───────────────────────────────────────────


def test_scene_id_lookup_helpers_cover_shapes_lights_and_groups():
    scene = _make_bound_scene()

    assert scene.find_shape("lens_a") is scene.shapes[0]
    assert scene.find_light("beam_main") is scene.lights[0]
    assert scene.find_group("cluster") is scene.groups[0]
    assert scene.find_shape("missing") is None
    assert scene.find_light("missing") is None
    assert scene.find_group("missing") is None

    with pytest.raises(ValueError, match="shape not found: missing"):
        scene.require_shape("missing")
    with pytest.raises(ValueError, match="light not found: missing"):
        scene.require_light("missing")
    with pytest.raises(ValueError, match="group not found: missing"):
        scene.require_group("missing")


# ─── Material bindings via round-trip ──────────────────────────────────


def test_material_binding_round_trip_preserves_shared_and_inline(tmp_path):
    """Shapes with material_id keep the binding; shapes with inline material keep the inline."""
    path = tmp_path / "bindings.json"
    scene = Scene(
        materials={"glass": Material(ior=1.5, transmission=1.0)},
        shapes=[
            Circle(id="bound", center=[-0.5, 0.0], radius=0.2, material_id="glass"),
            Circle(id="inline", center=[0.5, 0.0], radius=0.2, material=Material(ior=1.8, transmission=1.0)),
        ],
        lights=[ProjectorLight(id="beam", position=[-1, 0], direction=[1, 0], source_radius=0.0)],
    )
    shot = Shot(name="bindings", scene=scene)
    shot.save(path)

    loaded = Shot.load(path)
    assert loaded.scene.require_shape("bound").material_id == "glass"
    assert loaded.scene.require_shape("inline").material_id == ""
    assert loaded.scene.require_shape("inline").material.ior == pytest.approx(1.8)


# ─── Authored JSON format validation ──────────────────────────────────


def test_v6_rejects_older_shot_version(tmp_path):
    path = tmp_path / "outdated.json"
    data = _make_valid_shot_json(version=4)
    _write_json(path, data)

    with pytest.raises(RuntimeError, match=r"Unsupported shot version"):
        Shot.load(path)


def test_v6_rejects_sparse_authored_json_missing_explicit_blocks(tmp_path):
    path = tmp_path / "sparse.json"
    sparse = {
        "version": 8,
        "name": "sparse",
        "materials": {},
        "shapes": [],
        "lights": [],
        "groups": [],
    }
    _write_json(path, sparse)

    with pytest.raises(RuntimeError, match="requires key: camera"):
        Shot.load(path)


def test_v6_authored_json_is_fully_explicit_for_defaults(tmp_path):
    path = tmp_path / "defaults.json"
    shot = Shot(name="explicit_defaults")
    shot.save(path)

    data = json.loads(path.read_text())

    assert data["camera"] == {}
    assert set(data["look"]) == {
        "exposure",
        "contrast",
        "gamma",
        "tonemap",
        "white_point",
        "normalize",
        "normalize_ref",
        "normalize_pct",
        "ambient",
        "background",
        "opacity",
        "saturation",
        "vignette",
        "vignette_radius",
        "temperature",
        "highlights",
        "shadows",
        "hue_shift",
        "grain",
        "grain_seed",
        "chromatic_aberration",
    }
    assert set(data["trace"]) == {"rays", "batch", "depth", "intensity", "seed_mode"}
    assert data["materials"] == {}
    assert data["groups"] == []


def test_v6_round_trip_preserves_seed_mode(tmp_path):
    path = tmp_path / "seed_mode.json"
    shot = Shot(name="seed_mode", trace=TraceDefaults(seed_mode="decorrelated"), scene=_make_bound_scene())
    shot.save(path)

    data = json.loads(path.read_text())
    loaded = Shot.load(path)

    assert data["trace"]["seed_mode"] == "decorrelated"
    assert loaded.trace.seed_mode == "decorrelated"


def test_render_session_seed_mode_uses_repeatable_frame_index():
    deterministic = _make_seed_behavior_shot("deterministic")
    decorrelated = _make_seed_behavior_shot("decorrelated")

    det_frame0 = _render_pixels(deterministic, 0)
    det_frame1 = _render_pixels(deterministic, 1)
    dec_frame0_a = _render_pixels(decorrelated, 0)
    dec_frame0_b = _render_pixels(decorrelated, 0)
    dec_frame1 = _render_pixels(decorrelated, 1)

    assert det_frame0 == det_frame1
    assert dec_frame0_a == dec_frame0_b
    assert dec_frame0_a != dec_frame1


# ─── CLI rejection tests ──────────────────────────────────────────────


def test_cpp_cli_rejects_older_shot_version(tmp_path):
    outdated_path = tmp_path / "outdated_v4.json"
    output = tmp_path / "outdated_v4.png"
    _write_json(outdated_path, _make_valid_shot_json(version=4))

    result = subprocess.run(
        [str(CLI_BINARY), "--scene", str(outdated_path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode != 0
    assert "Unsupported shot version (expected 8)" in result.stderr
    assert not output.exists()


def test_cpp_cli_rejects_trailing_garbage_json(tmp_path):
    bad_path = tmp_path / "trailing_garbage.json"
    output = tmp_path / "trailing_garbage.png"
    bad_path.write_text('{"version":6,"shapes":[],"lights":[],"groups":[]} trailing')

    result = subprocess.run(
        [str(CLI_BINARY), "--scene", str(bad_path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode != 0
    assert "Invalid JSON" in result.stderr
    assert not output.exists()


def test_cpp_cli_missing_version_reports_unsupported_shot_version(tmp_path):
    bad = _make_valid_shot_json()
    bad.pop("version")
    bad_path = tmp_path / "missing_version.json"
    output = tmp_path / "missing_version.png"
    _write_json(bad_path, bad)

    result = subprocess.run(
        [str(CLI_BINARY), "--scene", str(bad_path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode != 0
    assert "Unsupported shot version" in result.stderr
    assert not output.exists()


def test_cpp_cli_rejects_noncanonical_tonemap_alias():
    result = subprocess.run(
        [
            str(CLI_BINARY),
            "--scene",
            "diamond",
            "--output",
            "/tmp/alias.png",
            "--tonemap",
            "reinhard_extended",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode != 0
    assert "Invalid tonemap: reinhard_extended" in result.stderr


# ─── CLI save-shot round-trip ──────────────────────────────────────────


def test_cpp_save_shot_round_trip_preserves_v6_ids_and_material_bindings(tmp_path):
    source_path = tmp_path / "source.json"
    saved_path = tmp_path / "saved.json"

    shot = Shot(name="cpp_save", scene=_make_bound_scene())
    shot.save(source_path)

    result = subprocess.run(
        [
            str(CLI_BINARY),
            "--scene",
            str(source_path),
            "--save-shot",
            str(saved_path),
            "--width",
            "640",
            "--exposure",
            "2.5",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert saved_path.exists()

    saved = Shot.load(saved_path)
    assert saved.canvas.width == 640
    assert saved.look.exposure == pytest.approx(2.5)
    assert saved.scene.require_shape("lens_a").material_id == "glass"
    assert saved.scene.require_shape("lens_b").material_id == "glass"
    assert saved.scene.require_light("beam_main").id == "beam_main"
    assert saved.scene.require_group("cluster").id == "cluster"
    assert saved.scene.require_shape("cluster_edge").material_id == ""


def test_cpp_save_shot_round_trip_preserves_phase2_look_fields(tmp_path):
    source_path = tmp_path / "source_phase2.json"
    saved_path = tmp_path / "saved_phase2.json"

    shot = Shot(
        name="cpp_save_phase2",
        look=Look(saturation=1.7, vignette=0.3, vignette_radius=0.9),
        scene=_make_bound_scene(),
    )
    shot.save(source_path)

    result = subprocess.run(
        [
            str(CLI_BINARY),
            "--scene",
            str(source_path),
            "--save-shot",
            str(saved_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    saved = Shot.load(saved_path)
    assert saved.look.saturation == pytest.approx(1.7)
    assert saved.look.vignette == pytest.approx(0.3)
    assert saved.look.vignette_radius == pytest.approx(0.9)


def test_cpp_save_shot_round_trip_preserves_seed_mode(tmp_path):
    source_path = tmp_path / "source_seed.json"
    saved_path = tmp_path / "saved_seed.json"

    shot = Shot(
        name="cpp_save_seed",
        trace=TraceDefaults(seed_mode="deterministic"),
        scene=_make_bound_scene(),
    )
    shot.save(source_path)

    result = subprocess.run(
        [
            str(CLI_BINARY),
            "--scene",
            str(source_path),
            "--save-shot",
            str(saved_path),
            "--seed-mode",
            "decorrelated",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    saved = Shot.load(saved_path)
    assert saved.trace.seed_mode == "decorrelated"


# ─── Save/load/modify round-trip ──────────────────────────────────────


def test_save_load_modify_by_id_preserves_shared_material_meaning(tmp_path):
    path = tmp_path / "authored_scene.json"
    shot = Shot(name="roundtrip", scene=_make_bound_scene())
    shot.save(path)

    loaded = Shot.load(path)
    beam = loaded.scene.require_light("beam_main")
    assert isinstance(beam, ProjectorLight)
    beam.position = [-1.0, 0.15]

    lens = loaded.scene.require_shape("lens_a")
    lens.radius = 0.35

    loaded.scene.require_group("cluster").transform.translate = [0.25, -0.1]
    loaded.save(path)

    reloaded = Shot.load(path)
    lens_reloaded = reloaded.scene.require_shape("lens_a")
    beam_reloaded = reloaded.scene.require_light("beam_main")

    assert lens_reloaded.radius == pytest.approx(0.35)
    assert lens_reloaded.material_id == "glass"
    assert isinstance(beam_reloaded, ProjectorLight)
    assert beam_reloaded.position[0] == pytest.approx(-1.0)
    assert beam_reloaded.position[1] == pytest.approx(0.15)


# ─── C++ validate_scene and normalize_scene ────────────────────────────


def test_validate_scene_accepts_valid_scene():
    scene = _make_bound_scene()
    _lpt2d.validate_scene(scene)


def test_normalize_scene_assigns_ids_and_syncs_materials():
    scene = Scene(
        materials={"glass": Material(ior=1.5, transmission=1.0)},
        shapes=[
            Circle(radius=0.2, material_id="glass"),
        ],
        lights=[ProjectorLight(position=[-1, 0], direction=[1, 0], source_radius=0.0)],
    )

    _lpt2d.normalize_scene(scene)

    assert scene.shapes[0].id != ""
    assert scene.lights[0].id != ""


def test_normalize_scene_rejects_invalid_after_normalization():
    scene = Scene(
        shapes=[
            Circle(id="ok", radius=0.2, material_id="nonexistent"),
        ],
    )

    with pytest.raises(RuntimeError, match="unknown material_id: nonexistent"):
        _lpt2d.normalize_scene(scene)
