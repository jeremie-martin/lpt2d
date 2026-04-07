from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

from anim import Frame, FrameContext, Scene, Shot, Timeline

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_DIR = REPO_ROOT / "examples" / "python"
SECONDARY_DIR = REPO_ROOT / "anim" / "examples" / "secondary"
BINARY = REPO_ROOT / "build" / "lpt2d-cli"
EXPECTED_CANONICAL = {
    "beam_chamber_starter.py",
    "prism_crown_builder.py",
    "solid_surface_gallery.py",
    "three_spheres_center_zoom.py",
    "twin_prisms_scene_patch.py",
}
EXPECTED_SECONDARY = {
    "chromatic_kaleidoscope.py",
    "clean_scanning_reflective_field.py",
    "layered_orbiting_beam.py",
    "orbiting_beam.py",
    "twin_prisms_vertical_swap.py",
}
EXPECTED_BENCHMARK_SCENES = [
    "three_spheres",
    "prism",
    "diamond",
    "lens",
    "fiber",
    "mirror_box",
    "ring",
    "double_slit",
    "crystal_field",
    "mirrors",
]


@cache
def _load_module(path: Path):
    module_name = "_test_example_" + "_".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_pack_has_expected_entries():
    actual = {path.name for path in CANONICAL_DIR.glob("*.py")}
    assert actual == EXPECTED_CANONICAL


def test_secondary_examples_remain_importable():
    actual = {path.name for path in SECONDARY_DIR.glob("*.py")}
    assert actual == EXPECTED_SECONDARY
    for filename in sorted(EXPECTED_SECONDARY):
        _load_module(SECONDARY_DIR / filename)


def test_canonical_modules_follow_contract():
    for filename in sorted(EXPECTED_CANONICAL):
        module = _load_module(CANONICAL_DIR / filename)
        assert isinstance(module.NAME, str) and module.NAME
        assert isinstance(module.SUMMARY, str) and module.SUMMARY
        assert isinstance(module.WORKFLOW, str) and module.WORKFLOW
        assert isinstance(module.DURATION, float | int) and module.DURATION > 0
        assert callable(module.make_settings)
        assert callable(module.frame)
        assert callable(module.main)


def test_canonical_modules_build_frame_zero():
    for filename in sorted(EXPECTED_CANONICAL):
        module = _load_module(CANONICAL_DIR / filename)
        settings = module.make_settings()
        assert isinstance(settings, Shot)
        ctx = Timeline(float(module.DURATION)).context_at(0)
        assert isinstance(ctx, FrameContext)
        result = module.frame(ctx)
        assert isinstance(result, (Scene, Frame))
        if isinstance(result, Frame):
            assert isinstance(result.scene, Scene)


def test_examples_readme_lists_the_canonical_pack():
    readme = (REPO_ROOT / "examples" / "README.md").read_text()
    for filename in EXPECTED_CANONICAL:
        assert filename in readme
    assert "anim/examples/secondary" in readme


def test_benchmark_scene_set_stays_stable():
    script = (REPO_ROOT / "benchmark.sh").read_text()
    match = re.search(r"SCENES=\((.*?)\)", script, re.MULTILINE | re.DOTALL)
    assert match is not None
    actual = match.group(1).split()
    assert actual == EXPECTED_BENCHMARK_SCENES


def test_root_readme_points_to_canonical_examples_surface():
    readme = (REPO_ROOT / "README.md").read_text()
    assert "examples/" in readme
    assert "python examples/python/beam_chamber_starter.py" in readme


@pytest.mark.parametrize("filename", sorted(EXPECTED_CANONICAL))
def test_canonical_examples_render_frame_zero(tmp_path: Path, filename: str):
    script = CANONICAL_DIR / filename
    output = tmp_path / f"{script.stem}_frame0.png"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--frame",
            "0",
            "--output",
            str(output),
            "--binary",
            str(BINARY),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"{filename} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert output.exists(), f"{filename} did not produce {output.name}"
    assert output.stat().st_size > 0, f"{filename} produced an empty PNG"


@pytest.mark.parametrize(
    "filename",
    [
        "beam_chamber_starter.py",
        "prism_crown_builder.py",
        "solid_surface_gallery.py",
    ],
)
def test_canonical_examples_save_json_builds_authored_scene(tmp_path: Path, filename: str):
    script = CANONICAL_DIR / filename
    output = tmp_path / f"{script.stem}.json"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--save-json",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"{filename} failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert output.exists(), f"{filename} did not produce {output.name}"

    shot = Shot.load(output)
    assert (
        len(shot.scene.shapes) > 0
        or len(shot.scene.lights) > 0
        or len(shot.scene.groups) > 0
    ), f"{filename} saved an empty scene"
