"""After a render, sanity-check that the light actually moved by comparing
frames at different timestamps.

Run after a batch:
    python tmp/iris/test_video_motion.py /path/to/batch_dir
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from io import BytesIO


def frame_at(video: Path, t: float) -> np.ndarray:
    """Extract frame at time t as an RGB ndarray via ffmpeg."""
    out = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(video),
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.array(Image.open(BytesIO(out)).convert("RGB"))


def check_one(video: Path) -> tuple[bool, str]:
    timestamps = [1.0, 5.0, 9.0, 13.0]
    frames = [frame_at(video, t) for t in timestamps]
    pairs = [(timestamps[i], timestamps[j], np.abs(frames[i].astype(np.int16) -
                                                    frames[j].astype(np.int16)).mean())
             for i in range(len(frames)) for j in range(i + 1, len(frames))]
    max_diff = max(d for _, _, d in pairs)
    avg_diff = sum(d for _, _, d in pairs) / len(pairs)
    moved = max_diff > 5.0  # > 5 mean abs RGB change between two frames = real motion
    summary = (f"max pairwise frame-Δ={max_diff:.2f}  "
                f"avg pairwise frame-Δ={avg_diff:.2f}")
    return moved, summary


def main(batch_dir: str) -> int:
    base = Path(batch_dir)
    videos = sorted(base.glob("*/video.mp4"))
    if not videos:
        print(f"No videos found in {batch_dir}")
        return 1
    all_moved = True
    for v in videos:
        try:
            moved, summary = check_one(v)
        except Exception as e:  # noqa: BLE001
            print(f"  {v.parent.name}: ERROR {type(e).__name__}: {e}")
            all_moved = False
            continue
        verdict = "MOVES" if moved else "FROZEN"
        if not moved:
            all_moved = False
        print(f"  {v.parent.name}: {verdict}  {summary}")
    return 0 if all_moved else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "renders"))
