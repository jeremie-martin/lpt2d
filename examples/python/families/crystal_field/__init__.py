"""Crystal Field — point lights drifting through a grid of small objects."""

from __future__ import annotations

from anim.family import Family

from .check import check
from .describe import describe
from .params import DURATION, Params
from .sampling import sample
from .scene import build

FAMILY = Family(
    "crystal_field",
    DURATION,
    Params,
    sample,
    build,
    check=check,
    describe=describe,
)
