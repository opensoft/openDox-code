"""The workbench's HEALTH-CHECK SEAM (`add-neutral-product-standalone-
operability` task 4.3; plan 034 task T026).

`workbench.run_scoped_doc_health` used to import openxFactory's `doc_health`
package inside its body (`workbench.py:1407-1409` at `1e4a57fb`): three of the
eight deferred reaches into the publisher that #1144's F4.1 scan names. It now
resolves the check a host REGISTERED, through a seam this module declares, and
with nothing registered it answers NOT-AVAILABLE, naming the seam and the
registration call (4.2's discipline, requirement 5's third scenario).

WHAT IT ASSERTS, AND WHY EACH IS HERE

1. NOTHING REGISTERED IS NOT-AVAILABLE, AND THE RESULT NAMES ITS REMEDY. The
   assertion is on the detail's CONTENT (the seam and the call), not only on
   the status, because the reach this replaced ALSO answered not-available where
   `doc_health` was absent. Only the named seam tells the two apart.
2. AN IMPORTABLE `doc_health` IS NOT REACHED. A booby-trapped `doc_health`
   package is put in `sys.modules`, and nothing touches it. That is the
   behavioural half of the scan below: the reach is gone, not merely unlucky.
3. A REGISTERED CHECK ANSWERS THROUGH THE SEAM, with the arguments the seam
   promises, and the seam still keeps only findings on the scoped documents.
4. THE REGISTRATION DISCIPLINE: one registration, idempotent for the same
   object, refused for a different one, and an answer the seam cannot read is
   refused rather than taken for a clean scope.
5. THE STATIC HALF: `run_scoped_doc_health` and the seam's own functions make
   no deferred reach into the publisher or the consumer, read by `ast` the way
   F4.1's scan reads the whole package.

`--noconftest` SAFE, like every file `validate` runs today. It imports
`opendox.workbench` alone, which imports with no sibling present, and neither
`opendox.serve` nor `opendox.cli` (plan 034, tasks.md § Phase 1: those two
modules do not import in a lone checkout until T011 lands).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import sys
import types
from datetime import date
from pathlib import Path

import pytest

from opendox import workbench as wb

WORKBENCH_SOURCE = Path(wb.__file__)

NOW = "2026-09-26T12:00:00Z"
AS_OF = date(2026, 9, 26)

#: #1144 task 4.3's F4.1 scan, word for word: the four packages no deferred
#: reach in openDox may name.
FOREIGN = ("openxdox", "ideation_dashboard", "corpus_adapter_openxfactory",
           "doc_health")

#: The seam's own functions, and the action that resolves through it.
SEAM_FUNCTIONS = ("register_health_check", "unregister_health_check",
                  "health_check_registered", "run_scoped_doc_health")


@pytest.fixture(autouse=True)
def _empty_seam():
    """Every test starts with NOTHING registered, and puts back what it found.

    The seam is process-global by design (ONE registration, for the process),
    so a teardown that only unregistered would strip a registration some
    other part of the process made at its start. Nothing registers one in this
    suite today, and the restore is what keeps that from mattering later.

    Read through `getattr` with a default, so that against a tree WITHOUT the
    seam each test fails on its own assertion rather than all of them erroring
    here, which is what makes this file's red run legible."""
    previous = getattr(wb, "_health_check", None)
    unregister = getattr(wb, "unregister_health_check", lambda: None)
    unregister()
    yield
    unregister()
    if previous is not None:
        wb.register_health_check(previous)


class _Finding:
    """A check's finding, at the one attribute the seam reads."""

    def __init__(self, path: str, rule: str) -> None:
        self.path = path
        self.rule = rule

    def __repr__(self) -> str:
        return f"_Finding({self.path!r}, {self.rule!r})"


class _RecordingCheck:
    """A stand-in host check that records every call it is given."""

    def __init__(self, run: object) -> None:
        self.calls: list[tuple] = []
        self.run = run

    def __call__(self, repo_root, documents, *, repository, as_of, families):
        self.calls.append((repo_root, documents, repository, as_of, families))
        return self.run


class _TrapModule(types.ModuleType):
    """A module that records every non-dunder attribute anybody asks it for."""

    def __init__(self, name: str, touched: list[str]) -> None:
        super().__init__(name)
        self.__dict__["_touched"] = touched
        self.__path__ = []          # a package, so its submodules can be imported

    def __getattr__(self, attr: str):
        if not attr.startswith("__"):
            self._touched.append(f"{self.__name__}.{attr}")
        raise AttributeError(attr)


# --------------------------------------------------------------------------
# 1 — nothing registered: not-available, naming the seam and its remedy
# --------------------------------------------------------------------------

def test_with_nothing_registered_the_action_is_not_available_naming_the_seam(tmp_path):
    assert wb.health_check_registered() is False
    result = wb.run_scoped_doc_health(tmp_path, ["docs/a.md"], as_of=AS_OF)

    assert isinstance(result, wb.ActionResult)
    assert result.action == wb.ACTION_DOC_HEALTH
    assert result.status == "not-available"
    assert result.completed is False
    assert result.findings == [], "a check that never ran reports no findings"
    assert result.reference is None
    # The CONTENT is the point: the seam, and the call that fills it.
    assert result.detail == wb.HEALTH_CHECK_NOT_REGISTERED
    assert "health-check seam" in result.detail
    assert "opendox.workbench.register_health_check(" in result.detail
    assert "nothing is reported as clean" in result.detail
    # ...and not the reach it replaced, which named a missing module instead.
    assert "doc_health" not in result.detail
    assert "No module named" not in result.detail


def test_the_not_available_run_is_recorded_on_the_manifest(tmp_path):
    manifest = wb.Workbench.create("fixture-repo", "DH scope", now=NOW)
    result = wb.run_scoped_doc_health(tmp_path, ["docs/a.md"], wb=manifest,
                                      now=NOW)
    assert result.status == "not-available"
    assert manifest.data["action_history"][-1] == {
        "action": wb.ACTION_DOC_HEALTH, "at": NOW,
        "reference": wb.HEALTH_NOT_AVAILABLE_REF}


# --------------------------------------------------------------------------
# 2 — an importable `doc_health` is not reached
# --------------------------------------------------------------------------

def test_an_importable_doc_health_is_never_reached(tmp_path, monkeypatch):
    """The reach this replaced imported `doc_health`, `doc_health.families` and
    `doc_health.runner`. All three are importable here, and all three are
    traps. With nothing registered the action must still answer the seam's
    not-available, and none of them may be asked for anything."""
    touched: list[str] = []
    for name in ("doc_health", "doc_health.corpus", "doc_health.families",
                 "doc_health.runner"):
        monkeypatch.setitem(sys.modules, name, _TrapModule(name, touched))

    result = wb.run_scoped_doc_health(tmp_path, ["docs/a.md"], as_of=AS_OF)

    assert touched == [], f"the action reached the publisher's package: {touched}"
    assert result.status == "not-available"
    assert result.detail == wb.HEALTH_CHECK_NOT_REGISTERED


# --------------------------------------------------------------------------
# 3 — a registered check answers through the seam
# --------------------------------------------------------------------------

def test_a_registered_check_answers_through_the_seam(tmp_path):
    scoped = _Finding("docs/a.md", "a finding on the scoped document")
    foreign = _Finding("docs/elsewhere.md", "a finding outside the scope")
    check = _RecordingCheck(wb.HealthCheckRun(findings=(scoped, foreign),
                                              documents_checked=1))
    assert wb.register_health_check(check) is check
    assert wb.health_check_registered() is True
    manifest = wb.Workbench.create("fixture-repo", "DH scope", now=NOW)

    result = wb.run_scoped_doc_health(tmp_path, ["docs/a.md"],
                                      repository="fixture-repo", as_of=AS_OF,
                                      wb=manifest, now=NOW)

    assert check.calls == [(tmp_path.resolve(), ("docs/a.md",), "fixture-repo",
                            AS_OF, wb.DEFAULT_SCOPED_FAMILIES)]
    assert result.status == "completed"
    assert result.completed is True
    # The defensive filter stayed on this side of the seam.
    assert result.findings == [scoped]
    assert result.reference == "health/scoped/fixture-repo-1docs"
    assert result.detail == ("1 finding(s) over 1 scoped doc(s) "
                             "(families: status-validity, tag-hygiene)")
    assert manifest.data["action_history"][-1] == {
        "action": wb.ACTION_DOC_HEALTH, "at": NOW,
        "reference": "health/scoped/fixture-repo-1docs"}


def test_the_seam_supplies_the_defaults_it_always_supplied(tmp_path):
    """The repository defaults to the checkout's own name, the date to today,
    and the families to the ones the action asks for, resolved BEFORE the
    check is called so that no check has to know them."""
    check = _RecordingCheck(wb.HealthCheckRun())
    wb.register_health_check(check)
    before = date.today()
    result = wb.run_scoped_doc_health(tmp_path, ["docs/a.md", "docs/b.md"],
                                      families=["tag-hygiene"],
                                      reference="health/explicit")
    after = date.today()

    ((repo_root, documents, repository, as_of, families),) = check.calls
    assert repo_root == tmp_path.resolve()
    assert documents == ("docs/a.md", "docs/b.md")
    assert repository == tmp_path.resolve().name
    assert before <= as_of <= after
    assert families == ("tag-hygiene",)
    assert result.reference == "health/explicit"
    assert result.detail == ("0 finding(s) over 0 scoped doc(s) "
                             "(families: tag-hygiene)")


def test_a_checks_own_refusal_reaches_the_caller_unchanged(tmp_path):
    """An unknown family is the check's to refuse, as it was this module's
    before the seam. The seam does not turn it into a result."""
    def check(repo_root, documents, *, repository, as_of, families):
        raise wb.WorkbenchError(f"unknown doc-health family {families[0]!r}")

    wb.register_health_check(check)
    with pytest.raises(wb.WorkbenchError, match="unknown doc-health family 'no-such'"):
        wb.run_scoped_doc_health(tmp_path, ["docs/a.md"], families=["no-such"],
                                 as_of=AS_OF)


@pytest.mark.parametrize("answer", [None, [], (), {"findings": []}, "clean"])
def test_an_answer_the_seam_cannot_read_is_refused(tmp_path, answer):
    manifest = wb.Workbench.create("fixture-repo", "DH scope", now=NOW)
    wb.register_health_check(_RecordingCheck(answer))
    with pytest.raises(wb.WorkbenchError, match="not a HealthCheckRun"):
        wb.run_scoped_doc_health(tmp_path, ["docs/a.md"], as_of=AS_OF,
                                 wb=manifest, now=NOW)
    assert "action_history" not in manifest.data, (
        "a refused answer must not be recorded as a completed action")


# --------------------------------------------------------------------------
# 4 — one registration
# --------------------------------------------------------------------------

@pytest.mark.parametrize("not_a_check", [None, "a check", 3])
def test_only_a_callable_can_be_registered(not_a_check):
    with pytest.raises(TypeError, match="takes the host's scoped health check"):
        wb.register_health_check(not_a_check)
    assert wb.health_check_registered() is False


def test_registering_the_same_check_again_is_a_no_op():
    check = _RecordingCheck(wb.HealthCheckRun())
    wb.register_health_check(check)
    assert wb.register_health_check(check) is check
    assert wb.health_check_registered() is True


def test_a_different_check_is_refused_and_the_first_stays(tmp_path):
    first = _RecordingCheck(wb.HealthCheckRun(documents_checked=1))
    second = _RecordingCheck(wb.HealthCheckRun(documents_checked=2))
    wb.register_health_check(first)
    with pytest.raises(wb.WorkbenchError) as refused:
        wb.register_health_check(second)
    assert "opendox.workbench.unregister_health_check()" in str(refused.value)

    wb.run_scoped_doc_health(tmp_path, ["docs/a.md"], as_of=AS_OF)
    assert len(first.calls) == 1 and second.calls == []


def test_unregistering_returns_the_seam_to_not_available(tmp_path):
    wb.register_health_check(_RecordingCheck(wb.HealthCheckRun()))
    wb.unregister_health_check()
    assert wb.health_check_registered() is False
    result = wb.run_scoped_doc_health(tmp_path, ["docs/a.md"], as_of=AS_OF)
    assert result.status == "not-available"
    assert result.detail == wb.HEALTH_CHECK_NOT_REGISTERED


# --------------------------------------------------------------------------
# 5 — the static half: no deferred reach in the seam or the action
# --------------------------------------------------------------------------

def _named(node: ast.AST) -> list[str]:
    """F4.1's `named()`, word for word: every import, and every
    `import_module`/`__import__` call with a literal name."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
            and getattr(node.func, "attr", getattr(node.func, "id", "")) in ("import_module", "__import__"):
        return [node.args[0].value] if isinstance(node.args[0].value, str) else []
    return []


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef)}


def test_neither_the_seam_nor_the_action_reaches_the_publisher_or_the_consumer():
    tree = ast.parse(WORKBENCH_SOURCE.read_text(encoding="utf-8"),
                     str(WORKBENCH_SOURCE))
    functions = _functions(tree)
    missing = [name for name in SEAM_FUNCTIONS if name not in functions]
    assert missing == [], f"the seam's functions are not in workbench.py: {missing}"

    hits = [f"{WORKBENCH_SOURCE.name}:{node.lineno}: {name}  [in {fn}]"
            for fn in SEAM_FUNCTIONS
            for node in ast.walk(functions[fn])
            for name in _named(node)
            if any(name == f or name.startswith(f + ".") for f in FOREIGN)]
    assert hits == [], "a deferred reach into the publisher or the consumer:\n  " \
        + "\n  ".join(hits)


def test_the_static_check_would_catch_the_reach_it_replaced():
    """The negative control, because the assertion above proves an ABSENCE.
    The body this seam replaced, parsed from its own words, is caught."""
    replaced = (
        "def run_scoped_doc_health(repo_root, documents):\n"
        "    from doc_health import DEFAULT_THRESHOLDS, corpus as dh_corpus\n"
        "    from doc_health.families import FAMILIES\n"
        "    from doc_health.runner import Context, run_suite\n"
    )
    (function,) = ast.parse(replaced).body
    caught = [name for node in ast.walk(function) for name in _named(node)
              if any(name == f or name.startswith(f + ".") for f in FOREIGN)]
    assert caught == ["doc_health", "doc_health.families", "doc_health.runner"]
