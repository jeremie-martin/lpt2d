"""Material definitions and per-object assignment."""

from __future__ import annotations

from anim import Material, glass, diffuse, mirror

from .params import MaterialConfig, WALL, WALL_ID


def build_materials(cfg: MaterialConfig) -> dict[str, Material]:
    mats: dict[str, Material] = {WALL_ID: WALL}

    if cfg.style == "glass":
        mats["crystal"] = glass(
            cfg.ior, cauchy_b=cfg.cauchy_b, absorption=cfg.absorption, fill=cfg.fill
        )
        for i, cname in enumerate(cfg.color_names):
            mats[f"crystal_c{i}"] = glass(
                cfg.ior,
                cauchy_b=cfg.cauchy_b,
                absorption=cfg.absorption,
                color=cname,
                fill=cfg.fill,
            )

    elif cfg.style == "diffuse":
        if cfg.diffuse_style == "dark":
            # Low albedo, no fill — black silhouettes that absorb most light.
            # Colors are irrelevant for dark style — all objects look the same.
            mats["crystal"] = Material(albedo=0.15, transmission=0.0)
        elif cfg.diffuse_style == "colored_fill":
            # Visible colored interior via fill
            mats["crystal"] = diffuse(0.7, fill=cfg.fill)
            for i, cname in enumerate(cfg.color_names):
                mats[f"crystal_c{i}"] = diffuse(0.7, color=cname, fill=max(cfg.fill, 0.10))
        elif cfg.diffuse_style == "metallic_rough":
            # Brushed metal look — reflects light softly
            mats["crystal"] = Material(
                metallic=1.0, roughness=0.6, albedo=0.8, transmission=0.0, fill=cfg.fill
            )
            for i, cname in enumerate(cfg.color_names):
                mats[f"crystal_c{i}"] = mirror(0.8, roughness=0.6, color=cname, fill=cfg.fill)

    return mats


def assign_material_ids(
    n_objects: int,
    cfg: MaterialConfig,
) -> list[str]:
    n_colors = len(cfg.color_names)
    ids: list[str] = []
    for i in range(n_objects):
        if n_colors > 0:
            ids.append(f"crystal_c{i % n_colors}")
        else:
            ids.append("crystal")
    return ids
