"""Allow ``python -m examples.python.families.crystal_field`` to run the CLI.

Supports the standard Family subcommands (search, survey, render) plus
``stats`` for parameter distribution analysis.
"""

from __future__ import annotations

import sys

if len(sys.argv) > 1 and sys.argv[1] == "stats":
    from .stats import run_stats

    run_stats(sys.argv[2:])
else:
    from . import FAMILY

    FAMILY.main()
