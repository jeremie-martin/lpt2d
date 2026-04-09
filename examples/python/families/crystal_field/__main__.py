"""Allow ``python -m examples.python.families.crystal_field`` to run the CLI.

Supports the standard Family subcommands (search, survey, render) plus
``stats`` for parameter distribution analysis and ``catalog`` for
systematic parameter space exploration.
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
else:
    from . import FAMILY

    FAMILY.main()
