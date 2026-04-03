"""Batch runner for the clean-room animation examples."""

from anim.examples._clean_room_registry import SCENES
from anim.examples._clean_room_shared import run_gallery_cli

if __name__ == "__main__":
    run_gallery_cli(SCENES, __doc__ or "Batch runner for the clean-room animation examples.")
