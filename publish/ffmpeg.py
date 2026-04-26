"""Tiny FFmpeg command builder."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FFmpegCommand:
    inputs: list[Path] = field(default_factory=list)
    output: Path | None = None
    pre_input_args: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    overwrite: bool = True
    loglevel: str = "warning"

    def pre(self, *parts: str) -> FFmpegCommand:
        self.pre_input_args.extend(parts)
        return self

    def input(self, path: Path | str) -> FFmpegCommand:
        self.inputs.append(Path(path))
        return self

    def arg(self, *parts: str) -> FFmpegCommand:
        self.args.extend(parts)
        return self

    def out(self, path: Path | str) -> FFmpegCommand:
        self.output = Path(path)
        return self

    def build(self) -> list[str]:
        cmd = ["ffmpeg", "-loglevel", self.loglevel]
        if self.overwrite:
            cmd.append("-y")
        cmd.extend(self.pre_input_args)
        for inp in self.inputs:
            cmd.extend(["-i", str(inp)])
        cmd.extend(self.args)
        if self.output is not None:
            cmd.append(str(self.output))
        return cmd

    def run(self) -> None:
        subprocess.run(self.build(), check=True)
