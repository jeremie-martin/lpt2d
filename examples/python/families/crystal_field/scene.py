"""Scene assembly — build the animate callback from Params."""

from __future__ import annotations

import random

from anim import (
    Circle,
    Frame,
    FrameContext,
    Look,
    PointLight,
    Polygon,
    Scene,
    Track,
    mirror_box,
)

from .channels import build_channel_graph
from .grid import build_grid, remove_holes
from .materials import assign_material_ids, build_materials
from .params import DURATION, WALL_ID, Params
from .paths import build_light_path, path_to_tracks
from .shapes import build_object


def grid_bounds(
    positions: list[tuple[float, float]], margin: float
) -> tuple[float, float, float, float]:
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


def build(p: Params):
    """Build an animate(ctx) -> Frame callable from params."""
    rng = random.Random(p.build_seed)
    materials = build_materials(p.material)

    # Grid
    positions = build_grid(p.grid)
    if p.grid.hole_fraction > 0:
        positions = remove_holes(positions, p.grid.hole_fraction, rng)

    # Materials per object
    mat_ids = assign_material_ids(len(positions), p.material)

    # Shapes
    shapes: list[Circle | Polygon] = []
    for i, pos in enumerate(positions):
        shapes.append(build_object(i, pos, p.shape, mat_ids[i], rng))

    wall_shapes = mirror_box(1.6, 0.9, WALL_ID, id_prefix="wall")

    # Channel graph (built once, shared by all channel-mode lights)
    ch_graph = build_channel_graph(p.grid) if p.light.path_style == "channel" else None

    # Light tracks
    # Tight margin keeps moving lights inside the grid rather than
    # wandering to the mirror-box edges where they overlap with ambient.
    gb = grid_bounds(positions, p.grid.spacing * 0.3) if positions else (-0.8, -0.5, 0.8, 0.5)
    light_x_tracks: list[Track] = []
    light_y_tracks: list[Track] = []
    for li in range(p.light.n_lights):
        wps = build_light_path(p.light, li, gb, p.grid.spacing, rng, ch_graph)
        xt, yt = path_to_tracks(wps, DURATION)
        light_x_tracks.append(xt)
        light_y_tracks.append(yt)

    # Fixed ambient lights
    ambient_lights: list[PointLight] = []
    amb = p.light.ambient
    if amb.style == "corners":
        for i, (ax, ay) in enumerate([(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]):
            ambient_lights.append(
                PointLight(id=f"amb_{i}", position=[ax, ay], intensity=amb.intensity)
            )
    elif amb.style == "sides":
        for i, (ax, ay) in enumerate([(-1.4, 0.0), (1.4, 0.0)]):
            ambient_lights.append(
                PointLight(id=f"amb_{i}", position=[ax, ay], intensity=amb.intensity)
            )

    # Moving light intensity: base from params, boosted for narrow-band spectra.
    spectrum_width = p.light.wavelength_max - p.light.wavelength_min
    spectral_boost = min(400.0 / max(spectrum_width, 50.0), 3.0) if spectrum_width < 300 else 1.0
    intensity = p.light.moving_intensity * spectral_boost

    def animate(ctx: FrameContext) -> Frame:
        lights = list(ambient_lights)
        for li in range(p.light.n_lights):
            lx = light_x_tracks[li].s(ctx.time)
            ly = light_y_tracks[li].s(ctx.time)
            lights.append(PointLight(
                id=f"light_{li}", position=[lx, ly], intensity=intensity,
                wavelength_min=p.light.wavelength_min,
                wavelength_max=p.light.wavelength_max,
            ))

        scene = Scene(
            materials=materials,
            shapes=[*wall_shapes, *shapes],
            lights=lights,
        )
        return Frame(scene=scene, look=Look(exposure=p.exposure))

    return animate
