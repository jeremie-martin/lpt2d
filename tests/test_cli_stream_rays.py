from __future__ import annotations

import json
import subprocess

CLI = "./build/lpt2d-cli"


def test_stream_respects_requested_ray_count():
    scene = {
        "name": "ray-budget",
        "shapes": [],
        "lights": [
            {
                "id": "projector_0",
                "type": "projector",
                "position": [0.0, 0.0],
                "direction": [1.0, 0.0],
                "source_radius": 0.0,
                "spread": 0.02,
                "profile": "uniform",
                "softness": 0.0,
                "intensity": 1.0,
                "wavelength_min": 500.0,
                "wavelength_max": 500.0,
            }
        ],
        "groups": [],
    }

    width = 32
    height = 32
    rays = 1003
    cmd = [
        CLI,
        "--stream",
        "--width",
        str(width),
        "--height",
        str(height),
        "--rays",
        str(rays),
        "--batch",
        "10000",
        "--normalize",
        "off",
        "--depth",
        "1",
    ]
    completed = subprocess.run(
        cmd,
        input=(json.dumps(scene) + "\n").encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode()
    assert len(completed.stdout) == width * height * 3

    meta = {}
    for line in completed.stderr.decode().splitlines():
        if "total_rays" not in line:
            continue
        idx = line.find(": {")
        if idx >= 0:
            meta = json.loads(line[idx + 2 :])
            break

    assert meta["rays"] == rays
    assert meta["total_rays"] == rays
