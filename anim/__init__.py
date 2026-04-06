"""lpt2d animation library — f(ctx) -> Scene -> video."""

from .analysis import auto_look as auto_look
from .analysis import calibrate_normalize_ref as calibrate_normalize_ref
from .analysis import compare_looks as compare_looks
from .analysis import look_report as look_report
from .builders import ball_lens as ball_lens
from .builders import biconvex_lens as biconvex_lens
from .builders import double_slit as double_slit
from .builders import elliptical_lens as elliptical_lens
from .builders import grating as grating
from .builders import hemispherical_lens as hemispherical_lens
from .builders import mirror_block as mirror_block
from .builders import mirror_box as mirror_box
from .builders import plano_convex_lens as plano_convex_lens
from .builders import polygon as polygon
from .builders import prism as prism
from .builders import rectangle as rectangle
from .builders import regular_polygon as regular_polygon
from .builders import slit as slit
from .builders import thick_arc as thick_arc
from .builders import thick_segment as thick_segment
from .builders import waveguide as waveguide
from .easing import EASINGS as EASINGS
from .easing import smoothstep as smoothstep
from .light_analysis import light_contributions as light_contributions
from .light_analysis import scene_light_report as scene_light_report
from .light_analysis import structure_contribution as structure_contribution
from .renderer import FFmpegOutput as FFmpegOutput
from .renderer import Renderer as Renderer
from .renderer import render as render
from .renderer import render_contact_sheet as render_contact_sheet
from .renderer import render_stats as render_stats
from .renderer import render_still as render_still
from .stats import FrameStats as FrameStats
from .stats import LightContribution as LightContribution
from .stats import LookComparison as LookComparison
from .stats import LookProfile as LookProfile
from .stats import LookReport as LookReport
from .stats import QualityGate as QualityGate
from .stats import StatsDiff as StatsDiff
from .stats import StructureReport as StructureReport
from .stats import check_quality as check_quality
from .stats import compare_stats as compare_stats
from .stats import compare_summary as compare_summary
from .stats import diagnose_scene as diagnose_scene
from .stats import frame_stats as frame_stats
from .track import Key as Key
from .track import Track as Track
from .track import Wrap as Wrap
from .track import sample_scalar as sample_scalar
from .track import sample_vec2 as sample_vec2
from .types import Arc as Arc
from .types import BeamLight as BeamLight
from .types import Bezier as Bezier
from .types import Camera2D as Camera2D
from .types import Canvas as Canvas
from .types import Circle as Circle
from .types import Ellipse as Ellipse
from .types import Frame as Frame
from .types import FrameContext as FrameContext
from .types import FrameReport as FrameReport
from .types import Group as Group
from .types import Look as Look
from .types import Material as Material
from .types import ParallelBeamLight as ParallelBeamLight
from .types import PointLight as PointLight
from .types import Polygon as Polygon
from .types import Quality as Quality
from .types import Scene as Scene
from .types import Segment as Segment
from .types import SegmentLight as SegmentLight
from .types import Shot as Shot
from .types import SpotLight as SpotLight
from .types import Timeline as Timeline
from .types import TraceDefaults as TraceDefaults
from .types import Transform2D as Transform2D
from .types import absorber as absorber
from .types import beam_splitter as beam_splitter
from .types import diffuse as diffuse
from .types import emissive as emissive
from .types import glass as glass
from .types import mirror as mirror
from .types import opaque_mirror as opaque_mirror

__all__ = [
    "Arc",
    "BeamLight",
    "ParallelBeamLight",
    "SpotLight",
    "Bezier",
    "Camera2D",
    "Canvas",
    "Circle",
    "Ellipse",
    "EASINGS",
    "FFmpegOutput",
    "Frame",
    "FrameContext",
    "FrameReport",
    "FrameStats",
    "Group",
    "Key",
    "Look",
    "Material",
    "PointLight",
    "Polygon",
    "Quality",
    "Renderer",
    "Scene",
    "Segment",
    "SegmentLight",
    "Shot",
    "Timeline",
    "Track",
    "TraceDefaults",
    "Transform2D",
    "Wrap",
    "sample_scalar",
    "sample_vec2",
    "QualityGate",
    "StatsDiff",
    "auto_look",
    "compare_looks",
    "look_report",
    "LookComparison",
    "LookProfile",
    "LookReport",
    "absorber",
    "ball_lens",
    "beam_splitter",
    "biconvex_lens",
    "calibrate_normalize_ref",
    "diagnose_scene",
    "light_contributions",
    "LightContribution",
    "StructureReport",
    "scene_light_report",
    "structure_contribution",
    "diffuse",
    "emissive",
    "check_quality",
    "compare_stats",
    "compare_summary",
    "frame_stats",
    "glass",
    "hemispherical_lens",
    "mirror",
    "mirror_block",
    "mirror_box",
    "opaque_mirror",
    "plano_convex_lens",
    "polygon",
    "rectangle",
    "regular_polygon",
    "render",
    "render_contact_sheet",
    "render_stats",
    "render_still",
    "smoothstep",
    "double_slit",
    "elliptical_lens",
    "grating",
    "prism",
    "slit",
    "thick_arc",
    "thick_segment",
    "waveguide",
]
