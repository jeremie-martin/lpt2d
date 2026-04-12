"""Scene assembly — build the animate callback from Params."""

from __future__ import annotations

import random
from dataclasses import asdict

from anim import (
    Circle,
    Frame,
    FrameContext,
    LightSpectrum,
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
from .params import DURATION, WALL_ID, LightSpectrumConfig, Params
from .paths import build_light_path, path_to_tracks
from .shapes import build_object


def grid_bounds(
    positions: list[tuple[float, float]], margin: float
) -> tuple[float, float, float, float]:
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


def resolve_light_spectrum(config: LightSpectrumConfig):
    if config.type == "color":
        rgb = config.linear_rgb
        return LightSpectrum.color(rgb[0], rgb[1], rgb[2], white_mix=config.white_mix)
    return LightSpectrum.range(config.wavelength_min, config.wavelength_max)


def _band_mean_luminance(wl_min: float, wl_max: float) -> float:
    """Mean perceived luminance per photon for a uniform spectral band."""
    from _lpt2d import wavelength_to_rgb

    total = 0.0
    n = 0
    for nm_i in range(int(wl_min), int(wl_max) + 1):
        r, g, b = wavelength_to_rgb(float(nm_i))
        total += 0.2126 * r + 0.7152 * g + 0.0722 * b
        n += 1
    return total / max(n, 1)


_WHITE_MEAN_LUMINANCE = _band_mean_luminance(380.0, 780.0)


def spectral_boost(wl_min: float, wl_max: float) -> float:
    """Luminance-weighted intensity boost for a narrow spectral band.

    Scales intensity so that a uniform [wl_min, wl_max] range produces the
    same perceived luminance as full-spectrum white at unit intensity.
    """
    band_lum = _band_mean_luminance(wl_min, wl_max)
    if band_lum < 1e-8:
        return 1.0
    return _WHITE_MEAN_LUMINANCE / band_lum


def ambient_intensity_multiplier(config: LightSpectrumConfig) -> float:
    if config.type != "color":
        return 1.0
    r, g, b = config.linear_rgb
    r = r + (1.0 - r) * config.white_mix
    g = g + (1.0 - g) * config.white_mix
    b = b + (1.0 - b) * config.white_mix
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    # Colored ambient lights are sampled as white-equivalent intent. We do not
    # cap this yet because white-mixed ambient lights are intentionally mild;
    # revisit a cap if custom very-dark ambient colors become unstable.
    return 1.0 / max(luminance, 1e-4)


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
    ambient_spectrum = resolve_light_spectrum(amb.spectrum)
    ambient_intensity = amb.intensity * ambient_intensity_multiplier(amb.spectrum)
    if amb.style == "corners":
        for i, (ax, ay) in enumerate([(-1.4, 0.75), (1.4, 0.75), (-1.4, -0.75), (1.4, -0.75)]):
            ambient_lights.append(
                PointLight(
                    id=f"amb_{i}",
                    position=[ax, ay],
                    intensity=ambient_intensity,
                    spectrum=ambient_spectrum,
                )
            )
    elif amb.style == "sides":
        for i, (ax, ay) in enumerate([(-1.4, 0.0), (1.4, 0.0)]):
            ambient_lights.append(
                PointLight(
                    id=f"amb_{i}",
                    position=[ax, ay],
                    intensity=ambient_intensity,
                    spectrum=ambient_spectrum,
                )
            )

    # Moving light intensity: base from params, boosted for narrow-band spectra.
    light_spectrum = resolve_light_spectrum(p.light.spectrum)
    if p.light.spectrum.type == "range":
        boost = spectral_boost(p.light.spectrum.wavelength_min, p.light.spectrum.wavelength_max)
    else:
        boost = 1.0
    intensity = p.light.moving_intensity * boost

    look_kwargs = asdict(p.look)
    frame_look = Look().with_overrides(**look_kwargs)

    def animate(ctx: FrameContext) -> Frame:
        lights = list(ambient_lights)
        for li in range(p.light.n_lights):
            lx = light_x_tracks[li].s(ctx.time)
            ly = light_y_tracks[li].s(ctx.time)
            lights.append(
                PointLight(
                    id=f"light_{li}",
                    position=[lx, ly],
                    intensity=intensity,
                    spectrum=light_spectrum,
                )
            )

        scene = Scene(
            materials=materials,
            shapes=[*wall_shapes, *shapes],
            lights=lights,
        )
        return Frame(scene=scene, look=frame_look)

    return animate
