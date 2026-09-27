"""#1144 task 2.3, the sweep: no module under `src/` reaches a sibling at
import time, and none reaches openxFactory at all. Plan 034 T032.

WHAT 2.3 ASKS. *"Sweep every remaining module-level reach: grep `src/` for
`ideation_dashboard`, `corpus_adapter_openxfactory`, `doc_health` and
`openxdox` at import position, and close or defer each with a recorded
reason."* T032 ran that sweep where phase 1's lanes joined, and its pull
request records every hit with its reason. At that tree:

* No import under `src/` names any of the four where it runs at import time.
  The two there were, `serve.py:199` and `:206` at `1e4a57fb`, T011 closed.
* The eight deferred reaches into openxFactory that research R5 measured are
  closed, each by its own phase-1 task: `authoring.py:318` (T021),
  `serve.py:713` (T012), `workbench.py:746` (T025), `workbench.py:1407-1409`
  (T026), and `serve_wire.py:1369` and `doxbench_packet.py:177` (T027).
* Nineteen deferred reaches remain, every one of them into `openxdox` and
  inside a function body. The release map routes them in phases 2 and 3
  (T055, T084), and openXdox-code's `OPENDOX_BACK_IMPORTS` ratchet counts them
  module by module.

THIS FILE HOLDS THE FIRST TWO FACTS, AND DOES NOT PIN THE THIRD'S COUNT. A
deferred reach into `openxdox` is still lawful in release 1. Each one that a
later task routes through a seam simply stops being one, and the ratchet that
already counts them is where that count moves. So nothing here needs an edit
when a reach closes. What may not come back is a reach at import time, into
any of the four, or a reach of any kind into openxFactory, which a standalone
openDox can never have. This is the openDox -> openxFactory direction that no
instrument watched (#1144 task 9.2a). `tests/test_imports_standalone.py`
proves the import-time half by importing every module; this file reads it off
the source, so it also holds where a sibling happens to be installed.

PARSED, NOT GREPPED (`tests/import_scan.py`'s rule). These modules name the
four packages in prose on purpose: a docstring saying which reach a seam
replaced, or a comment saying why an import is lazy. So the sweep reads import
statements, and `importlib.import_module(...)` or `__import__(...)` calls with
a literal name, out of the syntax tree, as #1144's F4.1 scan does. A name in a
comment, a docstring or a string is not an import. Relative imports stay inside
this package and are not read.

WHEN A REACH RUNS decides its class. Only a function body defers. A module
body, a class body, an `if`/`try`/`with` at module level (a `TYPE_CHECKING`
block among them), and a `def`'s decorators, default values and annotations
all run when the module is imported.

It reads `src/` whole, so `src/route_extension.py` and
`src/subcommand_extension.py` are swept with the package. `--noconftest` safe.
A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

#: The consumer. Its deferred reaches are phase 2's and 3's to route.
CONSUMER = "openxdox"

#: openxFactory's packages, spelled as F2.1 and F4.1 spell them. openDox can
#: never install one, so no reach of any kind may name them.
OPENXFACTORY = ("ideation_dashboard", "doc_health", "corpus_adapter_openxfactory")

SIBLINGS = (CONSUMER, *OPENXFACTORY)

#: The two calls that import a module named by a string, as F4.1 reads them.
IMPORTING_CALLS = ("import_module", "__import__")


@dataclass(frozen=True, order=True)
class Reach:
    """One import-position name of a sibling, and when it runs."""

    path: str
    line: int
    name: str
    deferred: bool
    inside: str

    @property
    def target(self) -> str:
        return self.name.split(".")[0]

    def __str__(self) -> str:
        when = "deferred" if self.deferred else "AT IMPORT TIME"
        return f"{self.path}:{self.line}: {self.name} ({when}, in {self.inside})"


def _names(node: ast.AST) -> list[str]:
    """The module names one node imports, F4.1's way."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if isinstance(node, ast.Call) and node.args \
            and isinstance(node.args[0], ast.Constant) \
            and isinstance(node.args[0].value, str) \
            and getattr(node.func, "attr", getattr(node.func, "id", "")) in IMPORTING_CALLS:
        return [node.args[0].value]
    return []


def sweep(source: str, path: str = "<source>") -> list[Reach]:
    """Every reach of a sibling in `source`, classified by when it runs."""
    found: list[Reach] = []

    def visit(node: ast.AST, deferred: bool, inside: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Everything but the BODY is evaluated where the `def` sits.
            args = node.args
            for part in (*node.decorator_list, *args.defaults,
                         *[d for d in args.kw_defaults if d is not None],
                         *[a.annotation for a in (*args.posonlyargs, *args.args,
                                                  *args.kwonlyargs, args.vararg,
                                                  args.kwarg)
                           if a is not None and a.annotation is not None],
                         *([node.returns] if node.returns is not None else [])):
                visit(part, deferred, inside)
            for statement in node.body:
                visit(statement, True, node.name)
            return
        if isinstance(node, ast.Lambda):
            for default in (*node.args.defaults,
                            *[d for d in node.args.kw_defaults if d is not None]):
                visit(default, deferred, inside)
            visit(node.body, True, f"{inside}.<lambda>")
            return
        for name in _names(node):
            if any(name == s or name.startswith(s + ".") for s in SIBLINGS):
                found.append(Reach(path, node.lineno, name, deferred, inside))
        for child in ast.iter_child_nodes(node):
            visit(child, deferred, inside)

    visit(ast.parse(source, filename=path), False, "<module>")
    return sorted(found)


def _sweep_src() -> list[Reach]:
    reaches: list[Reach] = []
    for path in sorted(SRC.rglob("*.py")):
        reaches += sweep(path.read_text(encoding="utf-8"),
                         path.relative_to(ROOT).as_posix())
    return reaches


# ---------------------------------------------------------------------------
# the sweep, over `src/`
# ---------------------------------------------------------------------------


def test_no_module_under_src_reaches_a_sibling_at_import_time():
    """Task 2.3's first finding, held: an import-time reach into any of the
    four is a module that cannot be imported where openDox runs alone."""
    at_import = [str(r) for r in _sweep_src() if not r.deferred]
    assert not at_import, (
        f"{len(at_import)} reach(es) into a sibling run at IMPORT time, so the "
        "module cannot be imported without it (#1144 task 2.1's defect): "
        + "; ".join(at_import))


def test_no_module_under_src_reaches_openxfactory_at_all():
    """F4.1's scan lists only `openxdox` targets.

    Phase 1 closed the eight deferred reaches into openxFactory, each through a
    seam openDox declares. A new one is openDox needing, at the moment a verb
    runs, a package it can never install. Route it through a seam the product
    declares, as 4.2 does, and do not add it here."""
    into = [str(r) for r in _sweep_src() if r.target in OPENXFACTORY]
    assert not into, (
        f"{len(into)} reach(es) into openxFactory, which openDox can never "
        "install (#1144 task 4.3's phase-1 cut): " + "; ".join(into))


def test_every_reach_the_sweep_finds_is_deferred_into_the_consumer():
    """The positive form of the two above: what is left is phase 2's and 3's.

    Every reach names `openxdox` and sits in a function body. Their count is
    openXdox-code's ratchet's, and it is not pinned here."""
    others = [str(r) for r in _sweep_src()
              if not (r.deferred and r.target == CONSUMER)]
    assert not others, "; ".join(others)


# ---------------------------------------------------------------------------
# the scanner bites
# ---------------------------------------------------------------------------

#: One module that reaches every sibling from every position the scanner
#: tells apart, and names them where it must not be fooled: in prose, in a
#: string, in a relative import, and in a package that merely starts with a
#: sibling's letters.
_SPECIMEN = textwrap.dedent('''
    """Prose names openxdox, doc_health and ideation_dashboard; not a reach."""
    import importlib
    from typing import TYPE_CHECKING
    import openxdox_lookalike
    from . import doc_health
    from .ideation_dashboard import thing

    import doc_health.corpus
    if TYPE_CHECKING:
        from openxdox import gate_console
    try:
        import corpus_adapter_openxfactory
    except ImportError:
        pass
    NOTE = "from ideation_dashboard import lanes"

    class Column:
        from ideation_dashboard import serve_openxfactory_lanes

    @importlib.import_module("doc_health.runner").decorate
    def verb(default=__import__("openxdox.corpus_root")):
        from openxdox.snapshot_registry import SnapshotRegistry
        importlib.import_module("doc_health.families")

        def inner():
            import corpus_adapter_openxfactory

        return lambda: __import__("ideation_dashboard")
''')


def test_the_scanner_classifies_every_position_it_reads():
    found = {(r.line, r.name, r.deferred, r.inside)
             for r in sweep(_SPECIMEN, "specimen.py")}
    assert found == {
        (9, "doc_health.corpus", False, "<module>"),
        (11, "openxdox", False, "<module>"),
        (13, "corpus_adapter_openxfactory", False, "<module>"),
        (19, "ideation_dashboard", False, "<module>"),
        (21, "doc_health.runner", False, "<module>"),
        (22, "openxdox.corpus_root", False, "<module>"),
        (23, "openxdox.snapshot_registry", True, "verb"),
        (24, "doc_health.families", True, "verb"),
        (27, "corpus_adapter_openxfactory", True, "inner"),
        (29, "ideation_dashboard", True, "verb.<lambda>"),
    }, sorted(found)


@pytest.mark.parametrize("test", [
    test_no_module_under_src_reaches_a_sibling_at_import_time,
    test_no_module_under_src_reaches_openxfactory_at_all,
    test_every_reach_the_sweep_finds_is_deferred_into_the_consumer,
], ids=lambda t: t.__name__)
def test_each_assertion_fails_on_the_reach_it_forbids(test, monkeypatch, tmp_path):
    """Each sweep assertion, run over a `src/` that holds one reach it
    forbids, fails. So a green run of it is a finding about the tree, and not
    a scan that reads nothing."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "reaching.py").write_text(
        "import doc_health\n", encoding="utf-8")
    this_module = sys.modules[__name__]
    monkeypatch.setattr(this_module, "SRC", tmp_path / "src")
    monkeypatch.setattr(this_module, "ROOT", tmp_path)
    with pytest.raises(AssertionError):
        test()
