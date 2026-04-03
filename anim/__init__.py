"""lpt2d animation library — f(t) -> Scene -> video."""

from .types import (
    Scene, Material, Circle, Segment, Arc, Bezier,
    PointLight, SegmentLight, BeamLight,
    Group, Transform2D, RenderConfig,
    glass, mirror, diffuse, absorber,
)
from .easing import keyframe, keyframe2
from .renderer import render, Renderer, FFmpegOutput
