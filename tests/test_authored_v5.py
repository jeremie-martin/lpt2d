from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from anim import renderer as renderer_mod
from anim.types import Camera2D, Canvas, BeamLight, Circle, Frame, Group, Look, Material, Scene, Segment, Shot, TraceDefaults

CLI_BINARY = Path(__file__).resolve().parents[1] / "build" / "lpt2d-cli"


def _make_bound_scene() -> Scene:
    return Scene(
        materials={"glass": Material(ior=1.5, transmission=1.0)},
        shapes=[
            Circle(id="lens_a", center=[-0.5, 0.0], radius=0.2, material_id="glass"),
            Circle(id="lens_b", center=[0.5, 0.0], radius=0.2, material_id="glass"),
        ],
        lights=[
            BeamLight(
                id="beam_main",
                origin=[-1.0, 0.0],
                direction=[1.0, 0.0],
                angular_width=0.02,
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


def _run_stream(line: str, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [str(CLI_BINARY), "--stream", *args],
        input=(line + "\n").encode(),
        capture_output=True,
        check=False,
        timeout=180,
    )


def test_v5_round_trip_preserves_ids_and_material_bindings():
    shot = Shot(name="authored_v5", scene=_make_bound_scene())

    loaded = Shot.from_json(shot.to_json())

    assert loaded.scene.require_shape("lens_a").material_id == "glass"
    assert loaded.scene.require_shape("lens_b").material_id == "glass"
    assert loaded.scene.require_light("beam_main").id == "beam_main"
    assert loaded.scene.require_group("cluster").id == "cluster"
    assert loaded.scene.require_shape("cluster_edge").id == "cluster_edge"


def test_v5_rejects_duplicate_entity_ids():
    scene = Scene(
        shapes=[
            Circle(id="dup", radius=0.2),
            Circle(id="dup", center=[1.0, 0.0], radius=0.3),
        ]
    )

    with pytest.raises(ValueError, match="duplicate entity id: dup"):
        scene.validate()


def test_v5_rejects_unknown_material_id():
    scene = Scene(shapes=[Circle(id="lens", radius=0.2, material_id="missing")])

    with pytest.raises(ValueError, match="unknown material_id: missing"):
        scene.validate()


def test_v5_rejects_shape_without_material_payload():
    bad = {
        "version": 5,
        "name": "bad",
        "shapes": [{"id": "lens", "type": "circle", "center": [0.0, 0.0], "radius": 0.2}],
        "lights": [],
        "groups": [],
    }

    with pytest.raises(
        ValueError, match="shape entries must declare exactly one of material and material_id"
    ):
        Shot.from_json(json.dumps(bad))


def test_scene_id_lookup_helpers_cover_shapes_lights_and_groups():
    scene = _make_bound_scene()

    assert scene.find_shape("lens_a") is scene.shapes[0]
    assert scene.find_light("beam_main") is scene.lights[0]
    assert scene.find_group("cluster") is scene.groups[0]
    assert scene.find_shape("missing") is None
    assert scene.find_light("missing") is None
    assert scene.find_group("missing") is None

    with pytest.raises(ValueError, match="unknown shape id: missing"):
        scene.require_shape("missing")
    with pytest.raises(ValueError, match="unknown light id: missing"):
        scene.require_light("missing")
    with pytest.raises(ValueError, match="unknown group id: missing"):
        scene.require_group("missing")


def test_shared_material_edits_propagate_and_detach_to_inline():
    scene = _make_bound_scene()
    lens_a = scene.require_shape("lens_a")
    lens_b = scene.require_shape("lens_b")

    scene.require_material("glass").ior = 1.7

    assert lens_a.material.ior == pytest.approx(1.7)
    assert lens_b.material.ior == pytest.approx(1.7)

    scene.detach_material("lens_a")
    scene.require_material("glass").ior = 1.9

    assert lens_a.material_id is None
    assert lens_a.material.ior == pytest.approx(1.7)
    assert lens_b.material_id == "glass"
    assert lens_b.material.ior == pytest.approx(1.9)

    scene.bind_material("lens_a", "glass")
    assert lens_a.material_id == "glass"
    assert lens_a.material.ior == pytest.approx(1.9)


def test_set_material_rebinds_existing_shared_shapes():
    scene = _make_bound_scene()

    replacement = scene.set_material("glass", Material(ior=1.8, transmission=1.0, absorption=0.2))

    lens = scene.require_shape("lens_a")
    assert lens.material is replacement
    assert lens.material_id == "glass"
    assert lens.material.absorption == pytest.approx(0.2)


def test_delete_material_detaches_bound_shapes():
    scene = _make_bound_scene()
    scene.require_material("glass").ior = 1.7

    removed = scene.delete_material("glass")

    lens = scene.require_shape("lens_a")
    assert removed.ior == pytest.approx(1.7)
    assert lens.material_id is None
    assert lens.material.ior == pytest.approx(1.7)
    assert scene.find_material("glass") is None


def test_rename_material_rebinds_shapes_after_library_replacement():
    scene = Scene(shapes=[Circle(id="lens", radius=0.2, material_id="glass")])
    scene.materials["glass"] = Material(ior=1.8, transmission=1.0)

    scene.rename_material("glass", "glass_hot")

    lens = scene.require_shape("lens")
    rebound = scene.require_material("glass_hot")
    assert lens.material_id == "glass_hot"
    assert lens.material is rebound
    assert lens.material.ior == pytest.approx(1.8)


def test_shot_to_json_does_not_mutate_shared_scene_ids():
    shot = Shot(scene=Scene(shapes=[Circle(center=[0.0, 0.0], radius=0.2, material=Material())]))
    derived = shot.with_look(exposure=1.0)

    derived.to_json()

    assert shot.scene.shapes[0].id == ""
    assert derived.scene.shapes[0].id == ""


def test_wire_json_does_not_mutate_scene_or_force_material_sync():
    scene = Scene(
        materials={"glass": Material(ior=1.7, transmission=1.0)},
        shapes=[Circle(center=[0.0, 0.0], radius=0.2, material_id="glass")],
    )

    wire = json.loads(
        renderer_mod._build_wire_json(
            Frame(scene=scene),
            camera=None,
            shot_camera=None,
            aspect=16.0 / 9.0,
        )
    )

    assert scene.shapes[0].id == ""
    assert scene.shapes[0].material.ior == pytest.approx(1.7)
    assert wire["shapes"][0]["material_id"] == "glass"
    assert "material" not in wire["shapes"][0]


def test_v5_rejects_older_shot_version():
    outdated = {
        "version": 4,
        "name": "outdated",
        "shapes": [],
        "lights": [],
        "groups": [],
    }

    with pytest.raises(ValueError, match=r"unsupported shot version: 4 \(expected 5\)"):
        Shot.from_json(json.dumps(outdated))


def test_cpp_cli_rejects_older_shot_version(tmp_path):
    outdated_path = tmp_path / "outdated_v4.json"
    output = tmp_path / "outdated_v4.png"
    outdated_path.write_text(
        json.dumps(
            {
                "version": 4,
                "name": "outdated",
                "shapes": [],
                "lights": [],
                "groups": [],
            }
        )
    )

    result = subprocess.run(
        [str(CLI_BINARY), "--scene", str(outdated_path), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode != 0
    assert "Unsupported shot version (expected 5)" in result.stderr
    assert not output.exists()


def test_cpp_stream_rejects_older_shot_version():
    result = subprocess.run(
        [str(CLI_BINARY), "--stream", "--width", "8", "--height", "8"],
        input=json.dumps({"version": 4, "shapes": [], "lights": [], "groups": []}) + "\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode != 0
    assert "frame 0: Unsupported shot version (expected 5)" in result.stderr


def test_cpp_cli_rejects_trailing_garbage_json(tmp_path):
    bad_path = tmp_path / "trailing_garbage.json"
    output = tmp_path / "trailing_garbage.png"
    bad_path.write_text('{"version":5,"shapes":[],"lights":[],"groups":[]} trailing')

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


def test_cpp_stream_rejects_truncated_json():
    result = subprocess.run(
        [str(CLI_BINARY), "--stream", "--width", "8", "--height", "8"],
        input='{"version":5,"shapes":[],"lights":[],"groups":[]\n',
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert result.returncode != 0
    assert "frame 0: Invalid JSON" in result.stderr


def test_cpp_stream_full_shot_json_ignores_session_look_defaults():
    shot = Shot(
        name="stream_full_default_look",
        scene=_make_bound_scene(),
        canvas=Canvas(width=8, height=8),
        trace=TraceDefaults(rays=50_000, batch=50_000, depth=2),
    )
    line = shot.to_json()

    result_dark = _run_stream(line, "--width", "16", "--height", "16", "--exposure", "-5")
    result_bright = _run_stream(line, "--width", "16", "--height", "16", "--exposure", "5")

    assert result_dark.returncode == 0, result_dark.stderr.decode()
    assert result_bright.returncode == 0, result_bright.stderr.decode()
    assert len(result_dark.stdout) == 8 * 8 * 3
    assert result_dark.stdout == result_bright.stdout


def test_cpp_stream_wire_frame_still_uses_session_look_defaults():
    wire = renderer_mod._build_wire_json(
        Frame(scene=_make_bound_scene()),
        camera=None,
        shot_camera=None,
        aspect=1.0,
    )

    result_dark = _run_stream(wire, "--width", "8", "--height", "8", "--rays", "50000", "--exposure", "-5")
    result_bright = _run_stream(wire, "--width", "8", "--height", "8", "--rays", "50000", "--exposure", "5")

    assert result_dark.returncode == 0, result_dark.stderr.decode()
    assert result_bright.returncode == 0, result_bright.stderr.decode()
    assert result_dark.stdout != result_bright.stdout


def test_cpp_stream_full_shot_json_respects_top_level_canvas_and_trace():
    shot = Shot(
        name="stream_canvas_trace",
        scene=_make_bound_scene(),
        canvas=Canvas(width=7, height=5),
        trace=TraceDefaults(rays=1234, batch=1234, depth=1),
    )

    result = _run_stream(
        shot.to_json(),
        "--width",
        "16",
        "--height",
        "16",
        "--rays",
        "999",
    )

    assert result.returncode == 0, result.stderr.decode()
    assert len(result.stdout) == 7 * 5 * 3
    assert '"rays": 1234' in result.stderr.decode()


def test_cpp_stream_full_shot_json_respects_top_level_camera():
    base = _make_bound_scene()
    wide = Shot(
        name="camera_wide",
        scene=base,
        camera=Camera2D(bounds=[-1.5, -1.0, 1.5, 1.0]),
        canvas=Canvas(width=8, height=8),
        trace=TraceDefaults(rays=50_000, batch=50_000, depth=2),
    )
    tight = Shot(
        name="camera_tight",
        scene=base,
        camera=Camera2D(bounds=[-0.35, -0.35, 0.35, 0.35]),
        canvas=Canvas(width=8, height=8),
        trace=TraceDefaults(rays=50_000, batch=50_000, depth=2),
    )

    result_wide = _run_stream(wide.to_json(), "--width", "16", "--height", "16")
    result_tight = _run_stream(tight.to_json(), "--width", "16", "--height", "16")

    assert result_wide.returncode == 0, result_wide.stderr.decode()
    assert result_tight.returncode == 0, result_tight.stderr.decode()
    assert result_wide.stdout != result_tight.stdout


def test_cpp_save_shot_round_trip_preserves_v5_ids_and_material_bindings(tmp_path):
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
    assert saved.scene.require_shape("cluster_edge").material_id is None


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


def test_save_load_modify_by_id_preserves_shared_material_meaning(tmp_path):
    path = tmp_path / "authored_scene.json"
    shot = Shot(name="roundtrip", scene=_make_bound_scene())
    shot.save(path)

    loaded = Shot.load(path)
    beam = loaded.scene.require_light("beam_main")
    assert isinstance(beam, BeamLight)
    beam.origin[1] = 0.15

    lens = loaded.scene.require_shape("lens_a")
    lens.radius = 0.35

    loaded.scene.require_group("cluster").transform.translate = [0.25, -0.1]
    loaded.save(path)

    reloaded = Shot.load(path)
    lens_reloaded = reloaded.scene.require_shape("lens_a")
    beam_reloaded = reloaded.scene.require_light("beam_main")

    assert lens_reloaded.radius == pytest.approx(0.35)
    assert lens_reloaded.material_id == "glass"
    assert isinstance(beam_reloaded, BeamLight)
    assert beam_reloaded.origin == [-1.0, 0.15]

    wire = json.loads(
        renderer_mod._build_wire_json(
            Frame(scene=reloaded.scene),
            camera=None,
            shot_camera=None,
            aspect=16.0 / 9.0,
        )
    )
    assert wire["version"] == 5
    lens_wire = next(shape for shape in wire["shapes"] if shape["id"] == "lens_a")
    assert lens_wire["material_id"] == "glass"
