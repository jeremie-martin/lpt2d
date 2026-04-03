"""Beam light orbiting three glass spheres."""

import math
from anim import (
    Scene, Circle, Segment, BeamLight, RenderConfig,
    glass, mirror, absorber, keyframe, render,
)


def animate(t):
    scene = Scene(name="orbiting_beam")

    # Three glass spheres (same as three_spheres scene)
    for x in (-0.5, 0.0, 0.5):
        scene.shapes.append(Circle(center=[x, 0], radius=0.2, material=glass(1.5, cauchy_b=20000, absorption=0.5)))

    # Mirror box walls
    wall = mirror(0.95)
    scene.shapes.append(Segment(a=[-1.2, -1.2], b=[1.2, -1.2], material=wall))
    scene.shapes.append(Segment(a=[1.2, 1.2], b=[-1.2, 1.2], material=wall))
    scene.shapes.append(Segment(a=[-1.2, 1.2], b=[-1.2, -1.2], material=wall))
    scene.shapes.append(Segment(a=[1.2, -1.2], b=[1.2, 1.2], material=wall))

    # Beam orbiting on a circle, always aimed at center
    orbit_radius = 1.0
    period = 10.0  # seconds for full orbit
    angle = t * 2 * (math.pi) / period

    ox = math.cos(angle) * orbit_radius
    oy = math.sin(angle) * orbit_radius

    # Direction: from origin toward center (0,0)
    dx, dy = -ox, -oy
    length = math.sqrt(dx * dx + dy * dy)
    dx /= length
    dy /= length

    scene.lights.append(BeamLight(
        origin=[ox, oy], direction=[dx, dy],
        angular_width=0.08, intensity=1.5,
    ))

    # Fix camera so it doesn't jump around
    scene.render = RenderConfig(bounds=[-1.3, -0.9, 1.3, 0.9])

    return scene


if __name__ == "__main__":
    import sys

    # Quick preview: low res, few rays
    if "--hq" in sys.argv:
        render(animate, duration=10.0, output="orbiting_beam_hq.mp4", fps=60,
               width=1920, height=1920, rays=10_000_000, binary="./build/lpt2d-cli")
    else:
        render(animate, duration=10.0, output="orbiting_beam.mp4", fps=30,
               width=640, height=640, rays=100_000, binary="./build/lpt2d-cli")
