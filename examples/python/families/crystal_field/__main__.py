"""Allow ``python -m examples.python.families.crystal_field`` to run the CLI.

Supports the standard Family subcommands (search, survey, render) plus
``stats``, ``catalog``, ``catalog_videos``, ``catalog_shots``,
``characterize``, ``spectrum_compare``, and ``ambient_compare``.
"""

from __future__ import annotations

import sys

cmd = sys.argv[1] if len(sys.argv) > 1 else None

if cmd == "stats":
    from .stats import run_stats

    run_stats(sys.argv[2:])
elif cmd == "catalog":
    from .catalog import run_catalog

    run_catalog(sys.argv[2:])
elif cmd == "catalog_videos":
    from .catalog_videos import run_catalog_videos

    run_catalog_videos(sys.argv[2:])
elif cmd == "catalog_shots":
    from .catalog_shots import run_catalog_shots

    run_catalog_shots(sys.argv[2:])
elif cmd == "characterize":
    from .characterize import run_characterize

    run_characterize(sys.argv[2:])
elif cmd == "spectrum_compare":
    from .spectrum_compare import run_spectrum_compare

    run_spectrum_compare(sys.argv[2:])
elif cmd == "ambient_compare":
    from .ambient_compare import run_ambient_compare

    run_ambient_compare(sys.argv[2:])
else:
    from . import FAMILY

    FAMILY.main()
