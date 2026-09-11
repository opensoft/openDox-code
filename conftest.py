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
# NOTHING THIS LIST NAMES EXISTS ON THIS BRANCH YET, AND THAT IS THE POINT.
# Every path below arrives with the carve (leg 1, `split-opendox` § 3.2), and
# this file has to be carrying the list already when they do: the arrival
# verifier admits a scaffold file only when its bytes equal `main`'s copy, so
# `conftest.py` cannot be edited during or after the re-cut. The list is
# therefore written ahead of the tree it describes, and was computed against
# that tree — the leg's own (opensoft/openDox-code#4, head `cfabe3c4`) — rather
# than guessed. A `collect_ignore` entry naming an absent file is inert, so this
# list is a no-op on this branch and takes effect the moment the rows land.
#
# Paths are relative to this file's directory (pytest resolves a conftest's
# `collect_ignore` against the conftest's own parent), and this is the ROOT
# conftest, so each entry is repository-relative. `tests/conftest.py` — which
# also arrives with the carve, as a declared replica — defines no
# `collect_ignore` of its own, so this list stays the one pytest reads.
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


# ---------------------------------------------------------------------------
# THE HOST CONTRACT, EXERCISED — § 4.3 (RULED ASK-2 option (2),
# openxFactory#656 comment 5628886636).
#
# `cli.build_parser()` composes its contributed subcommands from a profile the
# HOST registers at process start; with nothing registered it REFUSES rather
# than composing from an empty profile (`opendox.domain_profile
# .ProfileNotRegistered`). A test process is a host like any other, so it
# registers one HERE — in the root of the conftest chain, which is this suite's
# process start — rather than in a fixture each suite would have to remember.
# That is the contract being exercised, not worked around: a suite that built a
# parser without this block would be a suite proving the refusal, and
# `tests/test_profile_registration.py` already proves it, in isolation and with
# the registry emptied around every case.
#
# THE PROFILE IS THE TEST HARNESS'S OWN, and it is deliberately EMPTY. openDox
# ships no profile (the § 3 carve deleted the in-tree one) and this file must
# not invent openxFactory's: an empty pair of tuples composes the CORE parser
# and the CORE server — which is exactly the surface this leg's suites assert
# against, and byte-identical help text is what several of them pin.
#
# Guarded, because this scaffold file also runs where the package is not yet
# importable, and a conftest that raises collects nothing at all.
#
# THE GUARD IS NARROW ON PURPOSE (Copilot review thread on openDox-code#11).
# It was `except Exception`, which would have swallowed a `SyntaxError` or any
# other import-time breakage inside `opendox/domain_profile.py`, left
# `_domain_profile` as `None`, and SKIPPED the registration in silence — after
# which every suite that reached a composition point would fail, or pass,
# according to what happened to be collected. The registry would be broken and
# this file would be the reason nobody could tell. Only two things are
# scaffolding: the package is not importable yet, AND it is the PACKAGE that is
# missing rather than something the registry itself imports. Everything else is
# a regression and is re-raised, loudly, here.
try:                                           # pragma: no cover - scaffolding
    from opendox import domain_profile as _domain_profile
except ModuleNotFoundError as _missing:        # pragma: no cover - scaffolding
    if (_missing.name or "").split(".")[0] != "opendox":
        raise
    _domain_profile = None


class _SuiteProfile:
    """The empty host profile this test process registers. See the block above."""

    SUBCOMMAND_EXTENSIONS: tuple = ()
    ROUTE_EXTENSIONS: tuple = ()


if _domain_profile is not None and not _domain_profile.is_registered():
    _domain_profile.register(_SuiteProfile())
