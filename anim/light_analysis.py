"""Light source contribution analysis and structure diagnostics."""

from __future__ import annotations

import _lpt2d

from . import analysis as analysis_mod
from .stats import (
    FrameStats,
    LightContribution,
    StatsDiff,
    StructureReport,
    _copy_shape,
)
from .types import (
    Camera2D,
    Canvas,
    Frame,
    FrameContext,
    Look,
    Material,
    Scene,
    Shot,
    _apply_look_override,
)


def _neutral_contribution_look(normalize_ref: float) -> Look:
    return _apply_look_override(
        Look(),
        {
            "exposure": 0.0,
            "gamma": 1.0,
            "tonemap": "none",
            "normalize": "fixed",
            "normalize_ref": normalize_ref,
        },
    )


def _collect_light_sources(scene: Scene) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for i, light in enumerate(scene.lights):
        sources.append((light.id or f"light_{i}", f"light:{i}"))
    for gi, group in enumerate(scene.groups):
        for li, light in enumerate(group.lights):
            label = (group.id or f"group_{gi}") + "/" + (light.id or f"light_{li}")
            sources.append((label, f"group:{gi}:{li}"))
    for si, shape in enumerate(scene.shapes):
        if _lpt2d.resolve_material(shape, scene).emission > 0:
            sources.append((shape.id or f"emissive_shape_{si}", f"emissive:{si}"))
    for gi, group in enumerate(scene.groups):
        for si, shape in enumerate(group.shapes):
            if _lpt2d.resolve_material(shape, scene).emission > 0:
                label = (group.id or f"group_{gi}") + "/" + (shape.id or f"emissive_{si}")
                sources.append((label, f"emissive_group:{gi}:{si}"))
    return sources


def _zero_emission_material(mat: Material) -> Material:
    if mat.emission <= 0:
        return mat
    return Material(
        ior=mat.ior,
        roughness=mat.roughness,
        metallic=mat.metallic,
        transmission=mat.transmission,
        absorption=mat.absorption,
        cauchy_b=mat.cauchy_b,
        albedo=mat.albedo,
        emission=0.0,
    )


def _next_material_id(materials: dict[str, Material], base: str = "Material") -> str:
    if base not in materials:
        return base
    n = 1
    while True:
        candidate = f"{base}.{n:03d}"
        if candidate not in materials:
            return candidate
        n += 1


def _copy_shape_with_material_id(shape, material_id: str):
    return _copy_shape(shape, material_id=material_id)


def _zero_emission(shape, scene: Scene, materials: dict[str, Material]):
    mat = _lpt2d.resolve_material(shape, scene)
    if mat.emission <= 0:
        return shape
    material_id = _next_material_id(materials)
    materials[material_id] = _zero_emission_material(mat)
    return _copy_shape_with_material_id(shape, material_id)


def _scene_with_solo_source(scene: Scene, key: str) -> Scene:
    kind, _, detail = key.partition(":")
    materials = dict(scene.materials)

    ze_shapes = [_zero_emission(s, scene, materials) for s in scene.shapes]
    ze_groups = [
        _lpt2d.Group(
            id=g.id,
            transform=g.transform,
            shapes=[_zero_emission(s, scene, materials) for s in g.shapes],
            lights=[],
        )
        for g in scene.groups
    ]

    if kind == "light":
        idx = int(detail)
        return Scene(
            lights=[scene.lights[idx]],
            shapes=ze_shapes,
            groups=ze_groups,
            materials=materials,
        )

    if kind == "group":
        parts = detail.split(":")
        gi, li = int(parts[0]), int(parts[1])
        new_groups = []
        for i, g in enumerate(scene.groups):
            kept_lights = [g.lights[li]] if i == gi else []
            new_groups.append(
                _lpt2d.Group(
                    id=g.id,
                    transform=g.transform,
                    shapes=[_zero_emission(s, scene, materials) for s in g.shapes],
                    lights=kept_lights,
                )
            )
        return Scene(
            lights=[], shapes=ze_shapes, groups=new_groups, materials=materials
        )

    if kind in ("emissive", "emissive_group"):
        target_gi = -1
        target_si = int(detail)
        if kind == "emissive_group":
            group_part, shape_part = detail.split(":")
            target_gi = int(group_part)
            target_si = int(shape_part)
        new_shapes = []
        for si, s in enumerate(scene.shapes):
            if target_gi < 0 and si == target_si:
                new_shapes.append(s)
            else:
                new_shapes.append(_zero_emission(s, scene, materials))
        new_groups = []
        for gi, g in enumerate(scene.groups):
            gs = []
            for si, s in enumerate(g.shapes):
                if gi == target_gi and si == target_si:
                    gs.append(s)
                else:
                    gs.append(_zero_emission(s, scene, materials))
            new_groups.append(_lpt2d.Group(id=g.id, transform=g.transform, shapes=gs, lights=[]))
        return Scene(
            lights=[], shapes=new_shapes, groups=new_groups, materials=materials
        )

    return scene


def _contribution_reference_shot(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays_per_light: int = 500_000,
) -> tuple[Scene, Shot]:
    scene, shot = analysis_mod._resolve_static_scene_subject(subject, camera=camera, canvas=canvas)
    _lpt2d.normalize_scene(scene)
    analysis_shot = Shot(
        scene=scene,
        camera=shot.camera,
        canvas=analysis_mod._analysis_canvas(shot.canvas),
        trace=analysis_mod._analysis_trace(shot.trace, rays=rays_per_light),
    )
    normalize_ref = analysis_mod.calibrate_normalize_ref(
        lambda _ctx, _scene=scene: Frame(scene=_scene),
        1.0,
        settings=analysis_shot,
        camera=analysis_shot.camera,
        fast=True,
        frame=[0],
    )
    return scene, Shot(
        name=analysis_shot.name,
        scene=analysis_shot.scene,
        camera=analysis_shot.camera,
        canvas=analysis_shot.canvas,
        look=_neutral_contribution_look(normalize_ref),
        trace=analysis_shot.trace,
    )


def light_contributions(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays_per_light: int = 500_000,
) -> list[LightContribution]:
    """Render each source solo and measure its linear frame contribution."""
    scene, analysis_shot = _contribution_reference_shot(
        subject,
        camera=camera,
        canvas=canvas,
        rays_per_light=rays_per_light,
    )
    all_sources = _collect_light_sources(scene)
    if not all_sources:
        return []

    results: list[tuple[str, int, float, float]] = []
    total_mean = 0.0

    for idx, (label, key) in enumerate(all_sources):
        solo_scene = _scene_with_solo_source(scene, key)

        def animate_solo(_ctx: FrameContext, _s: Scene = solo_scene) -> Frame:
            return Frame(scene=_s)

        solo_shot = Shot(
            scene=solo_scene,
            camera=analysis_shot.camera,
            canvas=analysis_shot.canvas,
            look=analysis_shot.look,
            trace=analysis_shot.trace,
        )
        s = analysis_mod._measure_single_frame(
            animate_solo, solo_shot, analysis_shot.camera
        )
        if s is not None:
            results.append((label, idx, s.mean, 1.0 - s.pct_black))
            total_mean += s.mean
        else:
            results.append((label, idx, 0.0, 0.0))

    contributions = []
    for label, idx, mean, coverage in results:
        frac = mean / total_mean if total_mean > 0 else 0.0
        contributions.append(
            LightContribution(
                source_id=label,
                source_index=idx,
                mean_linear_luma=mean,
                coverage_fraction=coverage,
                share=frac,
            )
        )
    contributions.sort(key=lambda c: c.share, reverse=True)
    return contributions


def structure_contribution(
    subject: Scene | Shot,
    shape_id: str,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays: int = 5_000_000,
) -> StructureReport:
    """Measure one shape's effect on the rendered frame."""
    scene, analysis_shot = _contribution_reference_shot(
        subject,
        camera=camera,
        canvas=canvas,
        rays_per_light=rays,
    )

    scene_without = Scene(
        shapes=[s for s in scene.shapes if s.id != shape_id],
        lights=list(scene.lights),
        groups=[
            _lpt2d.Group(
                id=g.id,
                transform=g.transform,
                shapes=[s for s in g.shapes if s.id != shape_id],
                lights=list(g.lights),
            )
            for g in scene.groups
        ],
        materials=dict(scene.materials),
    )

    shot_with = Shot(
        scene=scene,
        camera=analysis_shot.camera,
        canvas=analysis_shot.canvas,
        look=analysis_shot.look,
        trace=analysis_shot.trace,
    )
    shot_without = Shot(
        scene=scene_without,
        camera=analysis_shot.camera,
        canvas=analysis_shot.canvas,
        look=analysis_shot.look,
        trace=analysis_shot.trace,
    )

    _empty = FrameStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 480, 480)
    s_with = analysis_mod._measure_single_frame(
        lambda _ctx, _s=scene: Frame(scene=_s),
        shot_with,
        analysis_shot.camera,
    ) or _empty
    s_without = analysis_mod._measure_single_frame(
        lambda _ctx, _s=scene_without: Frame(scene=_s),
        shot_without,
        analysis_shot.camera,
    ) or _empty

    diff = StatsDiff(
        mean=s_without.mean - s_with.mean,
        pct_black=s_without.pct_black - s_with.pct_black,
        pct_clipped=s_without.pct_clipped - s_with.pct_clipped,
        p50=s_without.p50 - s_with.p50,
        p95=s_without.p95 - s_with.p95,
    )

    if diff.mean > 5.0:
        role = "dimmer"
    elif diff.mean < -5.0:
        role = "brightener"
    else:
        role = "neutral"

    return StructureReport(
        shape_id=shape_id,
        stats_with=s_with,
        stats_without=s_without,
        diff=diff,
        role=role,
    )


def scene_light_report(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
) -> str:
    """Human-readable contribution report for authored light sources."""
    contribs = light_contributions(subject, camera=camera, canvas=canvas)

    if not contribs:
        return "No lights in scene."

    lines = ["Light contribution report:"]
    lines.append(f"  {'ID':<20} {'Share%':>8} {'Coverage%':>10} {'Mean':>8}")
    for c in contribs:
        lines.append(
            f"  {c.source_id:<20} {c.share:>7.1%} {c.coverage_fraction:>9.1%} {c.mean_linear_luma:>8.1f}"
        )

    warnings = []
    for c in contribs:
        if c.share < 0.01 and c.mean_linear_luma > 0:
            warnings.append(f"  {c.source_id}: contributes <1% of linear frame share")
        if c.share > 0.70:
            warnings.append(f"  {c.source_id}: dominates the frame (>70% share)")
        if c.coverage_fraction > 0.50 and c.share < 0.10:
            warnings.append(f"  {c.source_id}: wide coverage but low share (potential clutter)")

    if warnings:
        lines.append("Warnings:")
        lines.extend(warnings)

    return "\n".join(lines)
