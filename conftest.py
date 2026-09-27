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
# `collect_ignore` IS EMPTY, AND REQUIREMENT 9 IS WHY (plan 034 T035; #1144
# requirement 9, FR-006: "openDox-code: the whole suite ... No exclusion is
# declared").
#
# This list held seven test modules under RULED Q-L3 (b) (openxFactory#656,
# Brett Heap, 2026-09-10), each one a module the carve delivered and that could
# not import at this leg's place in the runbook, because it reached across the
# carve for something not carved yet. The BUILD arc and plan 034's phase 1 have
# removed those reaches, and T035 emptied the list: each module was rewritten
# in place as a neutral openDox test, and each case that needs another
# repository left this suite for the repository that holds what it needs. That
# pull request's body lists every such case with its destination.
#
# So an entry here is now an UNDECLARED EXCLUSION. It would shrink the suite
# the required check reports on, and requirement 9 asks this leg for none. A
# module that cannot run in a lone checkout is fixed, or it moves to where its
# composition is declared (openXdox-code's `tests/integration/`). It is not
# listed here.
#
# Paths would be relative to this file's directory, because pytest resolves a
# conftest's `collect_ignore` against the conftest's own parent. This is the
# ROOT conftest, so an entry would be repository-relative. `tests/conftest.py`
# and `tests_runtime/conftest.py` define no `collect_ignore` of their own.
collect_ignore: list[str] = []


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
