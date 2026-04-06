"""Light source contribution analysis and structure diagnostics."""

from __future__ import annotations

from dataclasses import replace as dc_replace

from . import analysis as analysis_mod
from . import renderer as renderer_mod
from .stats import (
    FrameStats,
    LightContribution,
    StatsDiff,
    StructureReport,
)
from .types import (
    Camera2D,
    Canvas,
    Frame,
    FrameContext,
    Look,
    Scene,
    Shot,
)


def _neutral_contribution_look(normalize_ref: float) -> Look:
    """Neutral linear look for additive source-comparison work."""
    return Look(
        exposure=0.0,
        contrast=1.0,
        gamma=1.0,
        tonemap="none",
        normalize="fixed",
        normalize_ref=normalize_ref,
        ambient=0.0,
        background=[0.0, 0.0, 0.0],
        opacity=1.0,
        saturation=1.0,
        vignette=0.0,
        vignette_radius=0.7,
    )


def _collect_light_sources(scene: Scene) -> list[tuple[str, str]]:
    """Collect (display_label, kind:key) for all authored light sources.

    Includes explicit lights and emissive shapes (which auto-generate lights
    during C++ upload_scene).  The second element encodes the source type:
    ``"light:0"``, ``"group:1:0"``, ``"emissive:3"``, ``"emissive_group:1:2"``.
    """
    from .types import Material

    sources: list[tuple[str, str]] = []
    for i, light in enumerate(scene.lights):
        sources.append((light.id or f"light_{i}", f"light:{i}"))
    for gi, group in enumerate(scene.groups):
        for li, light in enumerate(group.lights):
            label = (group.id or f"group_{gi}") + "/" + (light.id or f"light_{li}")
            sources.append((label, f"group:{gi}:{li}"))
    # Emissive shapes act as light sources via auto-generated synthetic lights
    for si, shape in enumerate(scene.shapes):
        mat: Material = shape.material  # type: ignore[union-attr]
        if mat.emission > 0:
            sources.append((shape.id or f"emissive_shape_{si}", f"emissive:{si}"))  # type: ignore[union-attr]
    for gi, group in enumerate(scene.groups):
        for si, shape in enumerate(group.shapes):
            mat = shape.material  # type: ignore[union-attr]
            if mat.emission > 0:
                label = (group.id or f"group_{gi}") + "/" + (shape.id or f"emissive_{si}")  # type: ignore[union-attr]
                sources.append((label, f"emissive_group:{gi}:{si}"))
    return sources


def _zero_emission(shape: object) -> object:
    """Return a copy of *shape* with emission zeroed out."""
    mat = shape.material  # type: ignore[union-attr]
    if mat.emission > 0:
        new_mat = dc_replace(mat, emission=0.0)
        return dc_replace(shape, material=new_mat)  # type: ignore[type-var]
    return shape


def _scene_with_solo_source(scene: Scene, key: str) -> Scene:
    """Build a scene with only one light source active.

    *key* is a ``kind:detail`` string from ``_collect_lights``.
    """
    kind, _, detail = key.partition(":")

    if kind == "light":
        idx = int(detail)
        return dc_replace(
            scene,
            lights=[scene.lights[idx]],
            shapes=[_zero_emission(s) for s in scene.shapes],  # type: ignore[misc]
            groups=[
                dc_replace(g, lights=[], shapes=[_zero_emission(s) for s in g.shapes])  # type: ignore[misc]
                for g in scene.groups
            ],
        )

    if kind == "group":
        parts = detail.split(":")
        gi, li = int(parts[0]), int(parts[1])
        new_groups = []
        for i, g in enumerate(scene.groups):
            kept_lights = [g.lights[li]] if i == gi else []
            new_groups.append(
                dc_replace(g, lights=kept_lights, shapes=[_zero_emission(s) for s in g.shapes])  # type: ignore[misc]
            )
        return dc_replace(
            scene,
            lights=[],
            shapes=[_zero_emission(s) for s in scene.shapes],  # type: ignore[misc]
            groups=new_groups,
        )

    if kind in ("emissive", "emissive_group"):
        # Keep this one emissive shape, zero all others, remove explicit lights.
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
                new_shapes.append(_zero_emission(s))  # type: ignore[misc]
        new_groups = []
        for gi, g in enumerate(scene.groups):
            gs = []
            for si, s in enumerate(g.shapes):
                if gi == target_gi and si == target_si:
                    gs.append(s)
                else:
                    gs.append(_zero_emission(s))  # type: ignore[misc]
            new_groups.append(dc_replace(g, lights=[], shapes=gs))
        return dc_replace(scene, lights=[], shapes=new_shapes, groups=new_groups)

    return scene  # fallback


def _contribution_reference_shot(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays_per_light: int = 500_000,
    binary: str = renderer_mod.DEFAULT_BINARY,
) -> tuple[Scene, Shot]:
    scene, shot = analysis_mod._resolve_static_scene_subject(
        subject, camera=camera, canvas=canvas
    )
    scene = scene.clone()
    scene.ensure_ids()
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
        binary=binary,
        fast=True,
        frame=[0],
    )
    return scene, dc_replace(analysis_shot, look=_neutral_contribution_look(normalize_ref))


def light_contributions(
    subject: Scene | Shot,
    *,
    camera: Camera2D | None = None,
    canvas: Canvas | None = None,
    rays_per_light: int = 500_000,
    binary: str = renderer_mod.DEFAULT_BINARY,
) -> list[LightContribution]:
    """Render each source solo and measure its linear frame contribution.

    Includes explicit lights and emissive shapes. The measurement uses a shared
    fixed normalization reference captured from the full scene plus a neutral
    linear look, so source shares remain additive and comparable.
    """
    scene, analysis_shot = _contribution_reference_shot(
        subject,
        camera=camera,
        canvas=canvas,
        rays_per_light=rays_per_light,
        binary=binary,
    )
    all_sources = _collect_light_sources(scene)
    if not all_sources:
        return []

    results: list[tuple[str, int, float, float]] = []  # (label, idx, mean, coverage)
    total_mean = 0.0

    for idx, (label, key) in enumerate(all_sources):
        solo_scene = _scene_with_solo_source(scene, key)

        def animate_solo(_ctx: FrameContext, _s: Scene = solo_scene) -> Frame:
            return Frame(scene=_s)

        stats_list = renderer_mod.render_stats(
            animate_solo,
            1.0,
            frames=[0],
            settings=dc_replace(analysis_shot, scene=solo_scene),
            camera=analysis_shot.camera,
            binary=binary,
            fast=True,
        )
        if stats_list:
            s = stats_list[0][2]
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
    binary: str = renderer_mod.DEFAULT_BINARY,
) -> StructureReport:
    """Measure one shape's effect with the same neutral reference on both runs."""
    if isinstance(subject, Shot):
        subject.scene.require_shape(shape_id)
    else:
        subject.require_shape(shape_id)

    scene, analysis_shot = _contribution_reference_shot(
        subject,
        camera=camera,
        canvas=canvas,
        rays_per_light=rays,
        binary=binary,
    )

    # Build scene without the shape
    scene_without = dc_replace(
        scene,
        shapes=[s for s in scene.shapes if s.id != shape_id],
        groups=[
            dc_replace(
                g,
                shapes=[s for s in g.shapes if s.id != shape_id],
            )
            for g in scene.groups
        ],
    )

    stats_with = renderer_mod.render_stats(
        lambda _ctx, _s=scene: Frame(scene=_s),
        1.0,
        frames=[0],
        settings=dc_replace(analysis_shot, scene=scene),
        camera=analysis_shot.camera,
        binary=binary,
        fast=True,
    )
    stats_without = renderer_mod.render_stats(
        lambda _ctx, _s=scene_without: Frame(scene=_s),
        1.0,
        frames=[0],
        settings=dc_replace(analysis_shot, scene=scene_without),
        camera=analysis_shot.camera,
        binary=binary,
        fast=True,
    )

    s_with = stats_with[0][2] if stats_with else FrameStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 480, 480)
    s_without = (
        stats_without[0][2] if stats_without else FrameStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 480, 480)
    )

    diff = StatsDiff(
        mean=s_without.mean - s_with.mean,
        pct_black=s_without.pct_black - s_with.pct_black,
        pct_clipped=s_without.pct_clipped - s_with.pct_clipped,
        p50=s_without.p50 - s_with.p50,
        p95=s_without.p95 - s_with.p95,
    )

    # Infer the role from the neutral linear delta.
    if diff.mean > 5.0:
        role = "dimmer"  # removing the shape makes it brighter
    elif diff.mean < -5.0:
        role = "brightener"  # removing the shape makes it dimmer
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
    binary: str = renderer_mod.DEFAULT_BINARY,
) -> str:
    """Human-readable contribution report for authored light sources."""
    contribs = light_contributions(subject, camera=camera, canvas=canvas, binary=binary)

    if not contribs:
        return "No lights in scene."

    lines = ["Light contribution report:"]
    lines.append(f"  {'ID':<20} {'Share%':>8} {'Coverage%':>10} {'Mean':>8}")
    for c in contribs:
        lines.append(
            f"  {c.source_id:<20} {c.share:>7.1%} {c.coverage_fraction:>9.1%} {c.mean_linear_luma:>8.1f}"
        )

    # Warnings
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
