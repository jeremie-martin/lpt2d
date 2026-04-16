"""Human-readable one-line description of a variant."""

from __future__ import annotations

import math

from .params import Params


def describe(p: Params) -> str:
    s = p.shape
    shape_desc = "circle" if s.kind == "circle" else f"{s.n_sides}-gon"
    if s.rotation:
        shape_desc += f" rot={math.degrees(s.rotation.base_angle):.0f}\u00b0"
        if s.rotation.jitter > 0:
            shape_desc += f"\u00b1{math.degrees(s.rotation.jitter):.0f}\u00b0"
    mat_desc = p.material.outcome
    amb = p.light.ambient.style if p.light.ambient.style != "none" else ""
    light_desc = f"lights={p.light.n_lights}({p.light.path_style})"
    if p.light.path_style in ("drift", "channel"):
        light_desc += f" v={p.light.speed:.2f}"
    if p.light.spectrum.type == "range":
        wl_min = p.light.spectrum.wavelength_min
        wl_max = p.light.spectrum.wavelength_max
        if wl_max - wl_min < 300:
            light_desc += f" wl={wl_min:.0f}-{wl_max:.0f}"
    else:
        rgb = p.light.spectrum.linear_rgb
        light_desc += f" rgb={rgb[0]:.2f},{rgb[1]:.2f},{rgb[2]:.2f}"
    # Count only non-None entries: brushed-metal's "mixed" sub-case has
    # color_names=[name, None] and semantically carries one color, not two.
    n_colors = sum(1 for c in p.material.color_names if c is not None)
    if amb and p.light.ambient.spectrum.type == "color":
        amb_rgb = p.light.ambient.spectrum.linear_rgb
        amb += (
            f" rgb={amb_rgb[0]:.2f},{amb_rgb[1]:.2f},{amb_rgb[2]:.2f}"
            f" wm={p.light.ambient.spectrum.white_mix:.2f}"
        )
    return (
        f"grid={p.grid.rows}x{p.grid.cols} {shape_desc} "
        f"mat={mat_desc} "
        f"{light_desc} "
        f"colors={n_colors}" + (f" amb={amb}" if amb else "")
    )
