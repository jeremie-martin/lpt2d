from __future__ import annotations

from pathlib import Path

from examples.python.families.crystal_field.catalog_videos import _collage_cmd, _collage_groups
from examples.python.families.crystal_field.params import DURATION


def test_collage_groups_keep_partial_final_batch():
    paths = [Path(f"clip_{idx}.mp4") for idx in range(6)]

    groups = _collage_groups(paths)

    assert [len(group) for group in groups] == [4, 2]
    assert groups[1] == paths[4:]


def test_collage_cmd_pads_short_groups_with_black_tiles():
    cmd = _collage_cmd([Path("a.mp4"), Path("b.mp4")], Path("out.mp4"))

    assert cmd.count("-i") == 4
    assert cmd.count("lavfi") == 2
    assert any(f"d={DURATION}" in arg for arg in cmd)
    assert cmd[-1] == "out.mp4"
    assert cmd[cmd.index("-filter_complex") + 1] == (
        "[0:v][1:v]hstack=inputs=2[top];"
        "[2:v][3:v]hstack=inputs=2[bot];"
        "[top][bot]vstack=inputs=2[out]"
    )
