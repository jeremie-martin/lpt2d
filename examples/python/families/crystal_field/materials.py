"""Material definitions and per-object assignment.

One function per outcome — no umbrella dispatcher, no shared constants.
See ``params.py`` for the outcome definitions and ``analysis.md`` for
the visual reasoning.
"""

from __future__ import annotations

from anim import Material, diffuse, glass, opaque_mirror

from .params import WALL, WALL_ID, MaterialConfig


def build_materials(cfg: MaterialConfig) -> dict[str, Material]:
    mats: dict[str, Material] = {WALL_ID: WALL}

    if cfg.outcome == "glass":
        # Refractive sphere.  Albedo is drawn in sampling for per-branch
        # uniformity but is visually irrelevant here — transmission=1.
        # Dispersion + IOR drive the caustic size (see analysis.md).
        mats["crystal"] = glass(
            cfg.ior,
            cauchy_b=cfg.cauchy_b,
            absorption=cfg.absorption,
            fill=cfg.fill,
        )
        return mats

    if cfg.outcome == "black_diffuse":
        # High albedo + fill=0 → dark silhouettes, smoother under moving lights
        # than low-albedo materials (which tend to look like wet wood).
        mats["crystal"] = diffuse(cfg.albedo, fill=cfg.fill)
        return mats

    if cfg.outcome == "gray_diffuse":
        # High albedo + fill ∈ [0.12, 0.22] (drawn by sampling) + no color →
        # a neutral shade of gray.
        mats["crystal"] = diffuse(cfg.albedo, fill=cfg.fill)
        return mats

    if cfg.outcome == "colored_diffuse":
        # Exactly one palette color, high albedo, fill ∈ [0.12, 0.22].
        # Strictly one color for now — see analysis.md.
        assert len(cfg.color_names) == 1 and cfg.color_names[0] is not None
        mats["crystal_c0"] = diffuse(cfg.albedo, color=cfg.color_names[0], fill=cfg.fill)
        return mats

    if cfg.outcome == "brushed_metal":
        # Solid metallic (metallic=1, roughness=0.6, transmission=0), high
        # albedo, fill ∈ [0.066, 0.15].  Four color sub-cases, driven by the
        # shape of ``color_names``:
        #   []              no color at all — single uncolored material
        #   [name]          one color — single colored material
        #   [name, None]    mixed — half colored, half uncolored, same fill
        #   [name_a, name_b] two actual colors — half/half, same fill
        # A ``None`` slot means "no color for this group, still brushed metal
        # with the same fill".  See analysis.md and sampling.py.
        if not cfg.color_names:
            mats["crystal"] = opaque_mirror(cfg.albedo, roughness=0.6, fill=cfg.fill)
            return mats
        for i, name in enumerate(cfg.color_names):
            # opaque_mirror(color=None, ...) resolves to neutral spectral
            # coefficients, giving an uncolored brushed metal material with
            # the same fill as its colored neighbour.
            mats[f"crystal_c{i}"] = opaque_mirror(
                cfg.albedo, roughness=0.6, color=name, fill=cfg.fill
            )
        return mats

    raise ValueError(f"Unknown material outcome: {cfg.outcome}")


def assign_material_ids(
    n_objects: int,
    cfg: MaterialConfig,
) -> list[str]:
    """Round-robin assign objects to the material ids built by ``build_materials``.

    - 0 color entries → every object uses ``"crystal"``.
    - 1 or more       → objects alternate between ``"crystal_c0"``, ``"crystal_c1"``, ...
    """
    n_colors = len(cfg.color_names)
    ids: list[str] = []
    for i in range(n_objects):
        if n_colors > 0:
            ids.append(f"crystal_c{i % n_colors}")
        else:
            ids.append("crystal")
    return ids
