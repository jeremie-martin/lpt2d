"""Factory helpers for the second wave of clean-room animations."""

from __future__ import annotations

import math
from collections.abc import Sequence

from anim import (
    Bezier,
    Frame,
    FrameContext,
    Group,
    Segment,
    Transform2D,
    ball_lens,
    biconvex_lens,
    plano_convex_lens,
    regular_polygon,
    thick_arc,
)
from anim.examples._clean_room_shared import (
    FACET_MIRROR,
    GLASS_BOLD,
    GLASS_FOCUS,
    GLASS_MEDIUM,
    GLASS_SOFT,
    SOFT_MIRROR,
    SPLITTER,
    SceneSpec,
    angle_between,
    beam_group,
    blade,
    fill_group,
    frame_for,
    room_group,
    tau,
)

GLASS_CYCLE = (GLASS_SOFT, GLASS_MEDIUM, GLASS_BOLD, GLASS_MEDIUM, GLASS_SOFT)


def _ellipse(rx: float, ry: float, angle: float) -> tuple[float, float]:
    return (rx * math.cos(angle), ry * math.sin(angle))


def _wobble(
    phase: float,
    center: tuple[float, float],
    *,
    ax: float,
    ay: float,
    rate: float,
    offset: float,
) -> tuple[float, float]:
    return (
        center[0] + ax * math.sin(rate * phase + offset),
        center[1] + ay * math.sin(rate * phase + offset + 0.8),
    )


def _beam_stack(
    phase: float,
    *,
    layout: str,
    warm_target: tuple[float, float],
    white_target: tuple[float, float] | None = None,
    top_target: tuple[float, float] | None = None,
    bottom_target: tuple[float, float] | None = None,
    warm_intensity: float = 0.78,
    white_intensity: float = 0.72,
    support_intensity: float = 0.46,
    warm_width: float = 0.036,
    white_width: float = 0.036,
    support_width: float = 0.042,
) -> list[Group]:
    groups: list[Group] = []

    if layout in {"left", "dual_side", "left_top", "triad", "exchange", "warm_white"}:
        warm_origin = (-1.54, 0.16 * math.sin(phase))
        groups.append(
            beam_group(
                "warm_beam",
                warm_origin,
                angle_between(warm_origin, warm_target),
                intensity=warm_intensity,
                width=warm_width,
                wavelength_min=555.0,
                wavelength_max=780.0,
            )
        )

    if layout in {"dual_side", "triad", "exchange", "warm_white"}:
        target = white_target or warm_target
        white_origin = (1.54, 0.14 * math.sin(1.09 * phase + 0.7))
        groups.append(
            beam_group(
                "white_beam",
                white_origin,
                angle_between(white_origin, target),
                intensity=white_intensity,
                width=white_width,
                wavelength_min=390.0,
                wavelength_max=780.0,
            )
        )

    if layout in {"left_top", "triad", "top"}:
        target = top_target or warm_target
        top_origin = (0.38 * math.sin(0.6 * phase + 0.2), 0.84)
        groups.append(
            beam_group(
                "top_beam",
                top_origin,
                angle_between(top_origin, target),
                intensity=support_intensity,
                width=support_width,
                wavelength_min=420.0,
                wavelength_max=780.0,
            )
        )

    if layout == "trident":
        right_target = white_target or warm_target
        top_origin = (0.28 * math.sin(0.7 * phase + 0.4), 0.84)
        left_origin = (-1.54, 0.14 * math.sin(phase))
        right_origin = (1.54, 0.14 * math.sin(1.13 * phase + 0.8))
        groups.extend(
            [
                beam_group(
                    "left_beam",
                    left_origin,
                    angle_between(left_origin, warm_target),
                    intensity=warm_intensity,
                    width=warm_width,
                    wavelength_min=555.0,
                    wavelength_max=780.0,
                ),
                beam_group(
                    "top_beam",
                    top_origin,
                    angle_between(top_origin, top_target or warm_target),
                    intensity=support_intensity,
                    width=support_width,
                    wavelength_min=420.0,
                    wavelength_max=780.0,
                ),
                beam_group(
                    "right_beam",
                    right_origin,
                    angle_between(right_origin, right_target),
                    intensity=white_intensity,
                    width=white_width,
                    wavelength_min=390.0,
                    wavelength_max=780.0,
                ),
            ]
        )

    if layout == "bottom":
        origin = (0.36 * math.sin(0.55 * phase), -0.84)
        groups.append(
            beam_group(
                "bottom_beam",
                origin,
                angle_between(origin, bottom_target or warm_target),
                intensity=support_intensity,
                width=support_width,
                wavelength_min=420.0,
                wavelength_max=780.0,
            )
        )

    return groups


def make_arc_cluster_spec(
    name: str,
    description: str,
    *,
    ring_count: int,
    orbit_rx: float,
    orbit_ry: float,
    arc_radius: float,
    local_start: float,
    local_sweep: float,
    beam_layout: str,
    base_exposure: float,
    spin_rate: float = 0.16,
    wobble: float = 0.14,
    core_radius: float = 0.07,
    support_fill: float = 0.0,
) -> SceneSpec:
    def build(ctx: FrameContext) -> Frame:
        phase = tau(ctx.progress)
        groups = [room_group()]
        for index in range(ring_count):
            orbit = spin_rate * phase + index * math.tau / ring_count
            center = _ellipse(orbit_rx, orbit_ry, orbit)
            tx, ty = _wobble(phase, center, ax=0.03, ay=0.03, rate=0.7, offset=index * 0.6)
            groups.append(
                Group(
                    name=f"arc_{index}",
                    transform=Transform2D.uniform(
                        translate=(tx, ty),
                        rotate=orbit + wobble * math.sin(phase + index * 0.7),
                    ),
                    shapes=thick_arc(
                        (0.0, 0.0),
                        arc_radius,
                        0.09,
                        local_start,
                        local_sweep,
                        FACET_MIRROR if index % 2 == 0 else SOFT_MIRROR,
                    ),
                )
            )

        groups.append(Group(name="core", shapes=ball_lens((0.0, 0.0), core_radius, GLASS_SOFT)))
        groups.extend(
            _beam_stack(
                phase,
                layout=beam_layout,
                warm_target=(0.06 * math.sin(phase + 0.2), 0.05 * math.sin(phase)),
                white_target=(-0.06 * math.sin(phase + 0.8), -0.04 * math.sin(phase + 0.4)),
                top_target=(0.0, -0.08),
            )
        )
        if support_fill > 0.0:
            groups.append(fill_group("fill", -0.78, intensity=support_fill, width=1.2))
        return frame_for(groups)

    return SceneSpec(
        name=name,
        duration=6.0,
        build=build,
        base_exposure=base_exposure,
        description=description,
    )


def make_prism_field_spec(
    name: str,
    description: str,
    *,
    layout: str,
    count: int,
    prism_radius: float,
    beam_layout: str,
    base_exposure: float,
    core_radius: float = 0.07,
    support_fill: float = 0.0,
) -> SceneSpec:
    def build(ctx: FrameContext) -> Frame:
        phase = tau(ctx.progress)
        groups = [room_group()]
        centers: list[tuple[float, float]] = []

        if layout == "ring":
            for index in range(count):
                angle = 0.28 * phase + index * math.tau / count
                centers.append(_ellipse(0.72, 0.38, angle))
        elif layout == "bridge":
            xs = [(-0.84 + 1.68 * index / max(count - 1, 1)) for index in range(count)]
            centers = [(x, 0.18 * math.sin(phase + index * 0.6)) for index, x in enumerate(xs)]
        elif layout == "sweep":
            xs = [(-0.9 + 1.8 * index / max(count - 1, 1)) for index in range(count)]
            centers = [(x, -0.38 + 0.18 * index + 0.08 * math.sin(phase + index)) for index, x in enumerate(xs)]
        elif layout == "constellation":
            base = [(-0.64, -0.24), (-0.26, 0.3), (0.1, -0.08), (0.54, 0.22), (0.72, -0.28), (-0.04, -0.42)]
            centers = base[:count]
        else:
            xs = [(-0.92 + 1.84 * index / max(count - 1, 1)) for index in range(count)]
            centers = [(x, 0.0) for x in xs]

        for index, center in enumerate(centers):
            cx, cy = _wobble(phase, center, ax=0.03, ay=0.04, rate=0.8, offset=index * 0.7)
            groups.append(
                Group(
                    name=f"prism_{index}",
                    transform=Transform2D.uniform(
                        translate=(cx, cy),
                        rotate=0.24 * phase + index * 0.28 + 0.12 * math.sin(phase + index),
                        scale=0.95 + 0.08 * math.sin(phase + index * 0.5),
                    ),
                    shapes=regular_polygon(
                        center=(0.0, 0.0),
                        radius=prism_radius,
                        n=3,
                        material=GLASS_CYCLE[index % len(GLASS_CYCLE)],
                        rotation=math.pi / 2,
                    ),
                )
            )

        groups.append(Group(name="core", shapes=ball_lens((0.0, 0.0), core_radius, GLASS_FOCUS)))
        groups.extend(
            _beam_stack(
                phase,
                layout=beam_layout,
                warm_target=(0.0, 0.0),
                white_target=(0.08 * math.sin(phase), 0.08 * math.sin(phase + 0.6)),
                top_target=(0.0, -0.1),
            )
        )
        if support_fill > 0.0:
            groups.append(fill_group("fill", -0.74, intensity=support_fill, width=1.16))
        return frame_for(groups)

    return SceneSpec(
        name=name,
        duration=6.0,
        build=build,
        base_exposure=base_exposure,
        description=description,
    )


def make_rotor_spec(
    name: str,
    description: str,
    *,
    pivots: Sequence[tuple[float, float]],
    blade_count: int,
    blade_length: float,
    spread: float,
    radial: bool,
    beam_layout: str,
    base_exposure: float,
    hub_kind: str = "prism",
    spin_rate: float = 0.18,
    support_fill: float = 0.0,
) -> SceneSpec:
    def build(ctx: FrameContext) -> Frame:
        phase = tau(ctx.progress)
        groups = [room_group()]

        for pivot_index, pivot in enumerate(pivots):
            for blade_index in range(blade_count):
                if radial:
                    base_angle = blade_index * math.tau / blade_count
                else:
                    base_angle = -spread * 0.5 + spread * blade_index / max(blade_count - 1, 1)
                direction = -1.0 if pivot_index % 2 else 1.0
                groups.append(
                    Group(
                        name=f"rotor_{pivot_index}_{blade_index}",
                        transform=Transform2D.uniform(
                            translate=pivot,
                            rotate=base_angle
                            + direction * spin_rate * phase
                            + 0.18 * math.sin(phase + blade_index * 0.35 + pivot_index * 0.6),
                        ),
                        shapes=blade(blade_length, FACET_MIRROR),
                    )
                )

            if hub_kind == "prism":
                shapes = regular_polygon(
                    center=(0.0, 0.0),
                    radius=0.12,
                    n=3,
                    material=GLASS_MEDIUM if pivot_index % 2 == 0 else GLASS_BOLD,
                    rotation=math.pi / 2,
                )
            else:
                shapes = ball_lens((0.0, 0.0), 0.1, GLASS_FOCUS if pivot_index % 2 == 0 else GLASS_SOFT)
            groups.append(Group(name=f"hub_{pivot_index}", transform=Transform2D.uniform(translate=pivot), shapes=shapes))

        groups.extend(
            _beam_stack(
                phase,
                layout=beam_layout,
                warm_target=(0.18 * math.sin(phase), 0.0),
                white_target=(-0.12 * math.sin(phase + 0.5), 0.06 * math.sin(phase)),
                top_target=(0.0, -0.1),
            )
        )
        if support_fill > 0.0:
            groups.append(fill_group("fill", -0.8, intensity=support_fill, width=1.08))
        return frame_for(groups)

    return SceneSpec(
        name=name,
        duration=6.0,
        build=build,
        base_exposure=base_exposure,
        description=description,
    )


def make_ribbon_spec(
    name: str,
    description: str,
    *,
    count: int,
    spacing: float,
    cross_bias: float,
    beam_layout: str,
    base_exposure: float,
    support_fill: float = 0.0,
) -> SceneSpec:
    def build(ctx: FrameContext) -> Frame:
        phase = tau(ctx.progress)
        shapes: list[Bezier | Segment] = []
        mid_y = 0.0
        for index in range(count):
            lane = index - (count - 1) * 0.5
            y0 = spacing * lane
            bend = 0.1 * math.sin(phase + index * 0.7)
            cross = cross_bias * (1 if index % 2 == 0 else -1)
            material = GLASS_CYCLE[index % len(GLASS_CYCLE)]
            shapes.append(
                Bezier(
                    p0=[-1.0, y0 + bend],
                    p1=[0.0, cross],
                    p2=[1.0, -y0 - 0.7 * bend],
                    material=material,
                )
            )
            mid_y += y0

        entrance = max(0.22, spacing * (count - 1) * 0.5 + 0.12)
        shapes.extend(
            [
                Segment(a=[-1.12, entrance], b=[-1.12, -entrance], material=FACET_MIRROR),
                Segment(a=[1.12, -entrance], b=[1.12, entrance], material=FACET_MIRROR),
            ]
        )
        groups = [room_group(), Group(name="ribbons", shapes=shapes)]
        groups.extend(
            _beam_stack(
                phase,
                layout=beam_layout,
                warm_target=(-0.82, 0.05 * math.sin(phase)),
                white_target=(0.82, -0.05 * math.sin(phase + 0.7)),
                top_target=(0.0, 0.0),
                warm_width=0.038,
                white_width=0.034,
            )
        )
        if support_fill > 0.0:
            groups.append(fill_group("fill", -0.76, intensity=support_fill, width=1.12))
        return frame_for(groups)

    return SceneSpec(
        name=name,
        duration=6.0,
        build=build,
        base_exposure=base_exposure,
        description=description,
    )


def _lens_shapes(kind: str, material):
    if kind == "ball":
        return ball_lens((0.0, 0.0), 0.1, material)
    if kind == "biconvex":
        return biconvex_lens(
            center=(0.0, 0.0),
            aperture=0.62,
            center_thickness=0.18,
            left_radius=1.02,
            right_radius=1.02,
            material=material,
        )
    return plano_convex_lens(
        center=(0.0, 0.0),
        aperture=0.62,
        center_thickness=0.18,
        radius=0.96,
        curved_side="left",
        material=material,
    )


def make_lens_field_spec(
    name: str,
    description: str,
    *,
    layout: str,
    count: int,
    beam_layout: str,
    base_exposure: float,
    support_fill: float = 0.0,
) -> SceneSpec:
    def build(ctx: FrameContext) -> Frame:
        phase = tau(ctx.progress)
        groups = [room_group()]

        if layout == "columns":
            centers = [(-0.42, -0.42), (-0.42, 0.42), (0.42, -0.42), (0.42, 0.42)]
        elif layout == "stair":
            centers = [(-0.82, -0.4), (-0.42, -0.12), (0.0, 0.16), (0.44, 0.4), (0.82, 0.58)][:count]
        elif layout == "diamond":
            centers = [(0.0, -0.54), (-0.54, 0.0), (0.54, 0.0), (0.0, 0.54)]
        elif layout == "grid":
            xs = (-0.58, 0.0, 0.58)
            ys = (-0.34, 0.34)
            centers = [(x, y) for y in ys for x in xs][:count]
        else:
            centers = [_ellipse(0.62, 0.34, index * math.tau / count) for index in range(count)]

        kinds = ("ball", "biconvex", "plano")
        for index, center in enumerate(centers):
            cx, cy = _wobble(phase, center, ax=0.035, ay=0.05, rate=0.85, offset=index * 0.7)
            groups.append(
                Group(
                    name=f"lens_{index}",
                    transform=Transform2D.uniform(
                        translate=(cx, cy),
                        rotate=0.18 * math.sin(phase + index * 0.55),
                        scale=0.96 + 0.06 * math.sin(phase + index * 0.3),
                    ),
                    shapes=_lens_shapes(kinds[index % len(kinds)], GLASS_CYCLE[index % len(GLASS_CYCLE)]),
                )
            )

        groups.extend(
            _beam_stack(
                phase,
                layout=beam_layout,
                warm_target=(0.1 * math.sin(phase), 0.08 * math.sin(phase + 0.6)),
                white_target=(-0.1 * math.sin(phase + 0.4), -0.08 * math.sin(phase)),
                top_target=(0.0, -0.1),
                warm_width=0.04,
            )
        )
        if support_fill > 0.0:
            groups.append(fill_group("fill", -0.78, intensity=support_fill, width=1.18))
        return frame_for(groups)

    return SceneSpec(
        name=name,
        duration=6.0,
        build=build,
        base_exposure=base_exposure,
        description=description,
    )


def make_splitter_web_spec(
    name: str,
    description: str,
    *,
    layout: str,
    beam_layout: str,
    base_exposure: float,
    core_radius: float = 0.07,
    support_fill: float = 0.0,
) -> SceneSpec:
    def build(ctx: FrameContext) -> Frame:
        phase = tau(ctx.progress)
        groups = [room_group()]

        if layout == "corridor":
            segments = [(-0.78, 0.0, 0.18, 0.6), (0.0, 0.0, -0.18, 0.7), (0.78, 0.0, 0.18, 0.6)]
        elif layout == "compass":
            segments = [(0.0, 0.0, angle, 0.84) for angle in (0.0, 0.5 * math.pi, 0.25 * math.pi, -0.25 * math.pi)]
        elif layout == "trident":
            segments = [(-0.42, 0.18, 0.2, 0.66), (0.0, 0.0, 0.0, 0.72), (0.42, -0.18, -0.2, 0.66)]
        elif layout == "exchange":
            segments = [(-0.36, 0.12, 0.46, 0.78), (0.36, -0.12, -0.46, 0.78)]
        else:
            segments = [(0.0, 0.0, angle, 0.62) for angle in (0.0, math.pi / 3, 2 * math.pi / 3)]

        for index, (tx, ty, angle, length) in enumerate(segments):
            groups.append(
                Group(
                    name=f"splitter_{index}",
                    transform=Transform2D.uniform(
                        translate=(tx, ty),
                        rotate=angle + 0.08 * math.sin(phase + index * 0.7),
                    ),
                    shapes=[Segment(a=[-length * 0.5, 0.0], b=[length * 0.5, 0.0], material=SPLITTER)],
                )
            )

        groups.append(Group(name="core", shapes=ball_lens((0.0, 0.0), core_radius, GLASS_FOCUS)))
        groups.extend(
            _beam_stack(
                phase,
                layout=beam_layout,
                warm_target=(0.0, 0.0),
                white_target=(0.1 * math.sin(phase), 0.06 * math.sin(phase + 0.3)),
                top_target=(0.0, -0.08),
                warm_width=0.034,
                white_width=0.034,
            )
        )
        if support_fill > 0.0:
            groups.append(fill_group("fill", -0.8, intensity=support_fill, width=1.04))
        return frame_for(groups)

    return SceneSpec(
        name=name,
        duration=6.0,
        build=build,
        base_exposure=base_exposure,
        description=description,
    )
