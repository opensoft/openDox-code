"""Put this leg's ``src/`` layout on ``sys.path`` for pytest.

Created by the OQ-O scaffold-levelling pass (openxFactory#656) before any
carved content arrives; ``pyproject.toml`` records why the import root has to
exist at all. That file's ``[tool.pytest.ini_options] pythonpath = ["src"]``
does this same job whenever pytest reads that table; this module is the belt
to that pair of braces — it also runs under a runner invoked against a
different ini, and it is the root of the conftest chain that the suites
arriving under ``tests/`` are collected beneath.

A CREATED file: no manifest row (RULED OQ-C).
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"

if SRC.is_dir():
    _src = str(SRC)
    if _src not in sys.path:
        sys.path.insert(0, _src)


# ---------------------------------------------------------------------------
# THE DISCLOSED `collect_ignore` LIST — RULED Q-L3 (b) (openxFactory#656,
# Brett Heap, 2026-09-10: "rule Q-L1 approve, Q-L2 approve, Q-L3 (b),
# Q-L4 re-cut").
#
# TEMPORARY, AND IT SAYS SO. Every entry is a test module the carve delivers
# correctly and that CANNOT import at this leg's position in the runbook § 5.1
# order, because it reaches across the carve for something that has not been
# carved yet. Each is removed by the BUILD arc
# (`split-opendox-two-layer-product` § 3.5/3.6) — the arc that inverts the
# openDox -> openXdox import direction through § 2.4's extension points — or by
# the openXdox-code leg landing, whichever reaches it first. Deleting an entry
# is the whole of the removal: nothing else in this repository refers to it.
#
# Two reasons qualify for this list AND NOTHING ELSE:
#
#   awaits openXdox-code leg  the module imports `openxdox.*`, directly or
#                             through `opendox.workbench` /
#                             `opendox.branch_session` / `opendox.cli`. The
#                             ruled § 5.5 carve rewrite points these at
#                             `openxdox`, which is the NEXT-but-one leg; under
#                             the hard order (`opendox_code` first) leg 1
#                             cannot wait for it.
#   awaits BUILD arc          the module reaches an openxFactory-only file that
#                             never travels, so no leg can ever satisfy it and
#                             only the BUILD arc's rework can.
#
# A test that fails for any OTHER reason is a FINDING, reported on the pull
# request that adds it here, never quietly added to this list. One such finding
# stands as this list is written: `tests/test_boundary.py` fails to import on a
# bare `import output_boundary` at its line 14 — an UNDECLARED line, so the leg
# could not rewrite it. That is cause 3 of #656, and RULED Q-L1 has the manifest
# amendment declare exactly that line, after which the row rewrites to
# `from opendox import output_boundary` and the module imports. It is therefore
# deliberately ABSENT here: it is fixed upstream, not ignored. If the Q-L1
# amendment lands WITHOUT declaring `tests/test_boundary.py:14`, this list is
# one entry short and the re-cut leg's `validate` will be red on it.
#
# Paths are relative to this file's directory (pytest resolves a conftest's
# `collect_ignore` against the conftest's own parent), and this is the ROOT
# conftest, so each entry is repository-relative. The arrived `tests/conftest.py`
# defines no `collect_ignore` of its own, so this list is the one pytest reads.
collect_ignore = [
    # --- awaits openXdox-code leg (imports openxdox.*) ---
    "tests/test_doxbench_chat_view.py",
    "tests/test_doxbench_entrypoint.py",
    "tests/test_hermeticity.py",
    "tests/test_model_provider_broker.py",
    "tests/test_subcommand_extension.py",
    "tests/test_workbench.py",
    # --- awaits BUILD arc (execs openxFactory-only script) ---
    "tests/test_session_harness.py",
]
