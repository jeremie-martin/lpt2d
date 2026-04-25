"""Family framework — reusable scene-variant generation and filtering.

A *family* is a visual concept that can produce many animation variants
from one definition.  The framework owns workflow plumbing (CLI, search
loop, output layout, JSON persistence, rendering).  The family owns
creative judgment (what to generate, what to keep, what to reject).

Typical usage in a family script::

    from anim.family import Family, Verdict, probe

    FAMILY = Family("my_family", 8.0, Params, sample, build, check=check)

    if __name__ == "__main__":
        FAMILY.main()
"""

from __future__ import annotations

import argparse
import inspect
import json
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import _lpt2d  # for FrameAnalysis type reference only

from .params import params_from_dict
from .renderer import RenderSession, _resolve_frame_shot, render, save_image
from .types import AnimateFn, Camera2D, Shot, Timeline


def _default_interest_score(pf: "ProbeFrame") -> float:
    """Blend colorfulness, P90 luminance, and a clipping penalty.

    Frames that have a strong colored/bright feature rank high; frames that
    blow out a large fraction of pixels are demoted."""
    p90 = pf.analysis.debug.p90_luma
    clipped = pf.analysis.image.clipped_channel_fraction
    return pf.colorfulness + 0.35 * p90 - 0.4 * clipped

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """Result of checking one candidate variant."""

    ok: bool
    summary: str


@dataclass(frozen=True)
class ProbeFrame:
    """Per-frame statistics from a probe render.

    Wraps the C++ FrameAnalysis for the probe frame and exposes convenience
    accessors for the image-stat fields the filter loop reads in
    tight inner expressions.
    """

    time: float
    analysis: Any  # _lpt2d.FrameAnalysis

    # Convenience accessors — all of these forward to rr.analysis.
    @property
    def mean_luma(self) -> float:
        return self.analysis.image.mean_luma

    @property
    def rms_contrast(self) -> float:
        return self.analysis.image.rms_contrast

    @property
    def near_black_fraction(self) -> float:
        return self.analysis.image.near_black_fraction

    @property
    def clipped_channel_fraction(self) -> float:
        return self.analysis.image.clipped_channel_fraction

    @property
    def colorfulness(self) -> float:
        return self.analysis.image.colorfulness

    @property
    def colored_fraction(self) -> float:
        return self.analysis.debug.colored_fraction

    @property
    def mean_saturation(self) -> float:
        return self.analysis.image.mean_saturation

    @property
    def hue_entropy(self) -> float:
        return self.analysis.debug.hue_entropy


# ---------------------------------------------------------------------------
# Shared defaults
# ---------------------------------------------------------------------------

_DEFAULT_CAMERA = Camera2D(center=[0, 0], width=3.2)

_STANDARD_LOOK = dict(
    gamma=2.0,
    tonemap="reinhardx",
    white_point=0.5,
    normalize="rays",
    temperature=0.1,
)


# ---------------------------------------------------------------------------
# Shot helpers
# ---------------------------------------------------------------------------


def _make_probe_shot(
    *,
    width: int = 640,
    height: int = 360,
    rays: int = 200_000,
    depth: int = 10,
    camera: Camera2D | None = None,
) -> Shot:
    """Build the low-res Shot used by probe() and survey()."""
    shot = Shot.preset("draft", width=width, height=height, rays=rays, depth=depth)
    shot.camera = camera or _DEFAULT_CAMERA
    shot.look = shot.look.with_overrides(**_STANDARD_LOOK)
    return shot


RENDER_PRESETS: dict[str, tuple[int, int, int, str]] = {
    # name → (width, height, rays, base_quality)
    "tiny":    (320, 180, 2_000_000, "preview"),
    "240p":    (426, 240, 400_000, "preview"),
    "480p":    (854, 480, 1_400_000, "preview"),
    "720p":    (1280, 720, 4_000_000, "preview"),
    "hq":      (1920, 1080, 6_000_000, "production"),
}
DEFAULT_RENDER_PRESET = "tiny"


def _make_render_shot(
    *,
    preset: str = DEFAULT_RENDER_PRESET,
    depth: int = 12,
    camera: Camera2D | None = None,
) -> Shot:
    """Build the Shot used for final output rendering."""
    if preset not in RENDER_PRESETS:
        raise ValueError(
            f"Unknown render preset {preset!r}. Choices: {sorted(RENDER_PRESETS)}"
        )
    width, height, rays, base = RENDER_PRESETS[preset]
    shot = Shot.preset(base, width=width, height=height, rays=rays, depth=depth)
    shot.camera = camera or _DEFAULT_CAMERA
    shot.look = shot.look.with_overrides(**_STANDARD_LOOK)
    return shot


# ---------------------------------------------------------------------------
# Probe rendering
# ---------------------------------------------------------------------------


def probe(
    animate: AnimateFn,
    duration: float,
    *,
    fps: int = 4,
    width: int = 640,
    height: int = 360,
    rays: int = 200_000,
    depth: int = 10,
    camera: Camera2D | None = None,
) -> list[ProbeFrame]:
    """Render probe frames and return per-frame stats.

    This is the primary tool for render-based checking inside a family's
    ``check`` function.  It renders every frame at low resolution and
    computes both luminance and color statistics.

    Parameters
    ----------
    animate : AnimateFn
        The animation callback ``(FrameContext) -> Frame``.
    duration : float
        Animation duration in seconds.
    fps : int
        Probe frame rate (default 4).
    width, height : int
        Probe resolution (default 640x360).
    rays : int
        Rays per frame (default 200K).
    depth : int
        Max ray depth (default 10).
    camera : Camera2D | None
        Override camera.  Defaults to center=[0,0] width=3.2.
    """
    shot = _make_probe_shot(width=width, height=height, rays=rays, depth=depth, camera=camera)

    timeline = Timeline(duration, fps=fps)
    session = RenderSession(width, height, False)

    frames: list[ProbeFrame] = []
    for fi in range(timeline.total_frames):
        ctx = timeline.context_at(fi)
        result = animate(ctx)
        cpp_shot = _resolve_frame_shot(shot, result, None)
        rr = session.render_shot(cpp_shot, fi, True)
        frames.append(ProbeFrame(time=ctx.time, analysis=rr.analysis))

    session.close()
    return frames


def pick_best_frame(
    animate: AnimateFn,
    duration: float,
    *,
    fps: int = 4,
    width: int = 640,
    height: int = 360,
    rays: int = 200_000,
    depth: int = 10,
    camera: Camera2D | None = None,
    score: Callable[[ProbeFrame], float] | None = None,
) -> tuple[int, "FrameContextType", float]:
    """Probe the animation and return the most interesting ``(idx, ctx, score)``.

    ``score`` defaults to colorfulness + 0.35·P90_luma − 0.4·clipped. The
    caller can pass a custom callable when a family has a specific definition
    of "the good moment" (e.g., peak beam intensity, widest spectrum).
    """
    scorer = score or _default_interest_score
    frames = probe(
        animate,
        duration,
        fps=fps,
        width=width,
        height=height,
        rays=rays,
        depth=depth,
        camera=camera,
    )
    if not frames:
        raise ValueError("probe returned no frames")
    timeline = Timeline(duration, fps=fps)
    best_i = max(range(len(frames)), key=lambda i: scorer(frames[i]))
    return best_i, timeline.context_at(best_i), scorer(frames[best_i])


def save_frame_shot(
    animate: AnimateFn,
    shot: Shot,
    ctx: "FrameContextType",
    out_path: Path | str,
    *,
    camera: Camera2D | None = None,
    name: str | None = None,
) -> None:
    """Resolve ``animate(ctx)`` and save a GUI-loadable Shot JSON.

    The saved shot inherits the look/trace/canvas of ``shot`` (usually the
    final render shot) so opening it in the GUI reproduces what was rendered.
    If ``name`` is given it overrides the shot's name in the saved JSON.
    """
    result = animate(ctx)
    cpp_shot = _resolve_frame_shot(shot, result, camera)
    if name is not None:
        cpp_shot.name = name
    _lpt2d.save_shot(cpp_shot, str(out_path))


# Forward reference so the signatures above stay readable before FrameContext
# is imported at runtime in the helpers that need it.
FrameContextType = Any


# ---------------------------------------------------------------------------
# Family
# ---------------------------------------------------------------------------


class Family:
    """Reusable definition of a visual concept and its variant-generation workflow.

    A Family encapsulates how to propose candidates (``sample``), build
    deterministic animations (``build``), and optionally reject bad
    candidates (``check``).  The framework runs the search loop, CLI,
    output layout, JSON persistence, and rendering.

    Parameters
    ----------
    name : str
        Family identifier, used for output directories and CLI.
    duration : float
        Animation duration in seconds.
    params_type : type
        The dataclass type returned by ``sample``, used for JSON round-tripping.
    sample : (Random) -> Params | None
        Propose a candidate.  Return None if construction fails.
    build : (Params) -> AnimateFn
        Build a deterministic animation from params.
    check : (Params, AnimateFn) -> Verdict | (AnimateFn) -> Verdict | None
        Optional filter. Either signature is accepted; arity is detected
        once at construction time. Use ``(animate)`` for render-stat-only
        gates; use ``(p, animate)`` when the gate needs params (e.g. to
        adjust thresholds based on material or layout).
    describe : (Params) -> str | None
        Optional one-line summary for progress output.
    tag : (Params) -> str | None
        Optional slug appended to the per-variant output dir
        (``001`` becomes ``001_<slug>``) and used as the saved shot's name.
    final_look : (Params) -> dict | None
        Optional Look-field overrides applied to the *render* shot only
        (e.g. vignette). The probe shot stays clean so gate stats reflect
        the underlying scene rather than a darkened lens.
    camera : Camera2D | None
        Override default camera.  Defaults to center=[0,0] width=3.2.
    depth : int
        Max ray depth for final renders (default 12).
    """

    def __init__(
        self,
        name: str,
        duration: float,
        params_type: type,
        sample: Callable[[random.Random], Any],
        build: Callable[[Any], AnimateFn],
        *,
        # check accepts either (animate) or (params, animate)
        check: Callable[..., Verdict] | None = None,
        describe: Callable[[Any], str] | None = None,
        tag: Callable[[Any], str | None] | None = None,
        final_look: Callable[[Any], dict | None] | None = None,
        camera: Camera2D | None = None,
        depth: int = 12,
    ):
        self.name = name
        self.duration = duration
        self.params_type = params_type
        self._sample = sample
        self._build = build
        self._check = check
        self._check_takes_params = (
            len(inspect.signature(check).parameters) >= 2 if check is not None else False
        )
        self._describe = describe
        self._tag = tag
        self._final_look = final_look
        self.camera = camera
        self.depth = depth

    # ── Search ────────────────────────────────────────────────────────

    def search(
        self,
        *,
        n: int = 1,
        seed: int | None = None,
        preset: str = DEFAULT_RENDER_PRESET,
        duration: float | None = None,
        max_attempts: int = 500,
        out: str | None = None,
    ) -> list:
        """Search for valid variants and render them.

        ``duration`` overrides the family's default if given.
        ``preset`` picks a render-resolution preset (see ``RENDER_PRESETS``).
        Returns list of accepted params for programmatic use.
        """
        if seed is None:
            seed = int(time.time())
        rng = random.Random(seed)
        base_dir = Path(out or f"renders/families/{self.name}")
        original_duration = self.duration
        if duration is not None:
            self.duration = duration

        print(f"seed={seed} target={n} preset={preset} duration={self.duration}s")

        accepted: list = []
        found = 0

        for attempt in range(1, max_attempts + 1):
            params = self._sample(rng)
            if params is None:
                continue

            desc = self._describe(params) if self._describe else ""
            animate = self._build(params)

            if self._check is not None:
                print(f"[{attempt}] {desc} -- checking...", flush=True)
                verdict = (
                    self._check(params, animate) if self._check_takes_params
                    else self._check(animate)
                )
                print(f"  {verdict.summary}", flush=True)
                if not verdict.ok:
                    continue
            else:
                print(f"[{attempt}] {desc}", flush=True)

            found += 1
            slug = f"{found:03d}"
            tag = self._tag(params) if self._tag else None
            if tag:
                slug = f"{slug}_{tag}"
            out_dir = base_dir / slug
            print(f"  FOUND #{found} -- rendering...")

            self._render_variant(
                params, animate, out_dir,
                preset=preset, name=f"{self.name}_{slug}",
            )
            accepted.append(params)
            print("  done.\n")

            if found >= n:
                break

        if found == 0:
            print(f"No valid animation found in {max_attempts} attempts.")

        self.duration = original_duration
        return accepted

    # ── Survey ────────────────────────────────────────────────────────

    def survey(
        self,
        *,
        n: int = 32,
        seed: int | None = None,
        out: str | None = None,
    ) -> None:
        """Sample without checking, render mid-frame stills for browsing."""
        if seed is None:
            seed = int(time.time())
        rng = random.Random(seed)
        out_dir = Path(out or f"renders/families/{self.name}/survey")
        out_dir.mkdir(parents=True, exist_ok=True)

        shot = _make_probe_shot(camera=self.camera)
        w, h = shot.canvas.width, shot.canvas.height
        session = RenderSession(w, h, False)
        timeline = Timeline(self.duration, fps=1)
        mid_frame = timeline.total_frames // 2

        print(f"survey: {n} variants, seed={seed}")

        all_params: list[dict] = []
        generated = 0

        for _ in range(n * 10):
            params = self._sample(rng)
            if params is None:
                continue

            generated += 1
            animate = self._build(params)

            ctx = timeline.context_at(mid_frame)
            result = animate(ctx)
            cpp_shot = _resolve_frame_shot(shot, result, None)
            rr = session.render_shot(cpp_shot, mid_frame)

            img_path = out_dir / f"{generated:03d}.png"
            save_image(str(img_path), rr.pixels, w, h)
            all_params.append(asdict(params))

            desc = self._describe(params) if self._describe else ""
            print(f"  [{generated}/{n}] {desc} -> {img_path.name}", flush=True)

            if generated >= n:
                break

        if generated < n:
            print(
                f"  WARNING: only generated {generated}/{n} variants (sample returned None too often)"
            )

        params_path = out_dir / "params.json"
        params_path.write_text(json.dumps(all_params, indent=2))
        print(f"  params -> {params_path}")
        print(f"survey: {generated} variants rendered")

    # ── Render ────────────────────────────────────────────────────────

    def render(
        self,
        params_path: str,
        *,
        preset: str = DEFAULT_RENDER_PRESET,
        duration: float | None = None,
        out: str | None = None,
    ) -> None:
        """Re-render a previously saved variant from its params.json."""
        path = Path(params_path)
        d = json.loads(path.read_text())
        if isinstance(d, list):
            raise ValueError(
                f"{path} contains {len(d)} variants (from survey). Use a single-variant params.json from search."
            )
        params = params_from_dict(self.params_type, d)
        animate = self._build(params)

        original_duration = self.duration
        if duration is not None:
            self.duration = duration
        try:
            out_dir = Path(out) if out else path.parent
            # Reuse the dir's basename for the shot name on re-render.
            self._render_variant(
                params, animate, out_dir,
                preset=preset, name=f"{self.name}_{out_dir.name}",
            )
        finally:
            self.duration = original_duration

    # ── CLI ───────────────────────────────────────────────────────────

    def main(self) -> None:
        """CLI entry point with subcommands: search, survey, render."""
        parser = argparse.ArgumentParser(prog=self.name, description=f"Family: {self.name}")
        sub = parser.add_subparsers(dest="command")

        preset_help = f"Render resolution preset. Choices: {sorted(RENDER_PRESETS)}"

        sp_search = sub.add_parser("search", help="Search for valid variants and render them")
        sp_search.add_argument("-n", type=int, default=1, help="Number of variants to find")
        sp_search.add_argument("--seed", type=int, default=None)
        sp_search.add_argument("--preset", choices=sorted(RENDER_PRESETS),
                               default=DEFAULT_RENDER_PRESET, help=preset_help)
        sp_search.add_argument("--duration", type=float, default=None,
                               help="Override the family's default duration (seconds)")
        sp_search.add_argument("--max-attempts", type=int, default=500)
        sp_search.add_argument("--out", type=str, default=None)

        sp_survey = sub.add_parser("survey", help="Sample without checking, render stills")
        sp_survey.add_argument("-n", type=int, default=32)
        sp_survey.add_argument("--seed", type=int, default=None)
        sp_survey.add_argument("--out", type=str, default=None)

        sp_render = sub.add_parser("render", help="Re-render from saved params.json")
        sp_render.add_argument("params_path", type=str)
        sp_render.add_argument("--preset", choices=sorted(RENDER_PRESETS),
                               default=DEFAULT_RENDER_PRESET, help=preset_help)
        sp_render.add_argument("--duration", type=float, default=None)
        sp_render.add_argument("--out", type=str, default=None)

        args = parser.parse_args()

        if args.command is None:
            # Default to search when no subcommand given
            args = sp_search.parse_args(sys.argv[1:])
            args.command = "search"

        if args.command == "search":
            self.search(
                n=args.n, seed=args.seed, preset=args.preset,
                duration=args.duration,
                max_attempts=args.max_attempts, out=args.out,
            )
        elif args.command == "survey":
            self.survey(n=args.n, seed=args.seed, out=args.out)
        elif args.command == "render":
            self.render(
                args.params_path, preset=args.preset,
                duration=args.duration, out=args.out,
            )
        else:
            parser.print_help()
            sys.exit(1)

    # ── Internal ──────────────────────────────────────────────────────

    def _render_variant(
        self,
        params: Any,
        animate: AnimateFn,
        out_dir: Path,
        *,
        preset: str = DEFAULT_RENDER_PRESET,
        name: str | None = None,
    ) -> None:
        """Save params, export the most interesting frame, and render the video."""
        out_dir.mkdir(parents=True, exist_ok=True)

        params_path = out_dir / "params.json"
        params_path.write_text(json.dumps(asdict(params), indent=2))
        print(f"  params -> {params_path}")

        shot = _make_render_shot(preset=preset, depth=self.depth, camera=self.camera)
        if name:
            shot.name = name
        if self._final_look is not None:
            extra = self._final_look(params)
            if extra:
                shot.look = shot.look.with_overrides(**extra)

        # Pick the most interesting frame from a probe and save it as a
        # GUI-loadable Shot JSON next to the video.
        try:
            _, ctx, score = pick_best_frame(
                animate, self.duration, camera=self.camera, depth=self.depth
            )
            shot_json_path = out_dir / "frame.shot.json"
            save_frame_shot(
                animate, shot, ctx, shot_json_path, camera=self.camera, name=name
            )
            print(f"  frame  -> {shot_json_path}  (t={ctx.time:.2f}s, score={score:.3f})")
        except Exception as e:  # noqa: BLE001 — best-effort; don't block video on it
            print(f"  frame-export skipped ({type(e).__name__}: {e})")

        timeline = Timeline(self.duration, fps=60)
        video_path = out_dir / "video.mp4"
        render(animate, timeline, str(video_path), settings=shot, crf=16)
        print(f"  video  -> {video_path}")
