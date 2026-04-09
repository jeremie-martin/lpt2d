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
    mat_desc = p.material.style
    if p.material.style == "diffuse":
        mat_desc = f"diffuse/{p.material.diffuse_style}"
    amb = p.light.ambient.style if p.light.ambient.style != "none" else ""
    light_desc = f"lights={p.light.n_lights}({p.light.path_style})"
    if p.light.path_style in ("drift", "channel"):
        light_desc += f" v={p.light.speed:.2f}"
    if p.light.wavelength_max - p.light.wavelength_min < 300:
        light_desc += f" wl={p.light.wavelength_min:.0f}-{p.light.wavelength_max:.0f}"
    return (
        f"grid={p.grid.rows}x{p.grid.cols} {shape_desc} "
        f"mat={mat_desc} "
        f"{light_desc} "
        f"colors={p.material.n_color_groups}" + (f" amb={amb}" if amb else "")
    )
