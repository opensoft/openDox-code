"""The direction, asserted from openDox's side — BUILD slice 2.

openDox is the NEUTRAL product. openXdox pins it (`split-opendox` § 4.2, RULED
OQ-2) and openDox pins nothing back, so **a neutral openDox with no `openxdox`
installed is the normal case**, and a module of this package that cannot be
imported without one is the wrong-direction edge `design.md`:243 forbids:
*"What must not survive is the direction, not the calls."*

WHY THE TEST IS "DOES IT IMPORT" AND NOT "COUNT THE IMPORT STATEMENTS."
openXdox-code's `tests/test_dependency_direction.py` keeps a per-module RATCHET
over this repository's `openxdox` imports (`OPENDOX_BACK_IMPORTS`), measured by
AST over `ast.Import` / `ast.ImportFrom` nodes. That census is the right shape
for a consumer measuring a repository it does not write — and it has a blind
spot this slice found the hard way:

    def _candidates(..., records_dir: str = gate_console.DEFAULT_RECORDS_DIR):

A DEFAULT ARGUMENT is evaluated when the `def` executes, which is at import
time. Rewrite `from openxdox import gate_console` into a late-bound stand-in and
the census falls by one while the module still cannot be imported without
openXdox — the reach simply stops being an `Import` node. `branch_session.py`
(NINE such sites) and `serve.py` (2) are exactly that case, and both were
reverted out of slice 2 rather than shipped as a census that reads better than
the tree. (Slice 2 wrote "7" here and openXdox-code's ratchet file repeats it;
both are counted and corrected in slice 2b, because a number a later audit
reads off a comment is worth no more than the count behind it.) **So this file asserts the thing the census is a proxy for**: the module
imports, in a subprocess, with `openxdox` made unimportable.

BUILD SLICE 2b is what that reversion was waiting for: `defaults.py` gives
openDox its own spelling of the three values those eleven default-argument
sites read — `DEFAULT_RECORDS_DIR` at `branch_session.py`'s nine,
`DEFAULT_INDEX_NAME` and `PEEK_TTL_SECONDS` at `serve.py`'s two — so the reach
can be removed at the site rather than renamed at the import line, and `branch_session` moves from the recorded half to the asserted half
below. That move is the point of the second test: it FAILED on the slice-2b
commit that made the module importable, and this act is the answer it asked
for.

`--noconftest` safe and dependency-free. `.github/workflows/validate.yml` ran
this file beside `tests/test_leg_shape.py`, with the repository's root
`conftest.py` loaded for neither, until plan 034 T036 made the required job
run the whole suite with it.

A CREATED FILE with no manifest row (RULED OQ-C); it sits under a declared root
and is named to the arrival verifier as
`--allow-created tests/test_consumer_reach.py`.
"""

from __future__ import annotations

import ast
import importlib.metadata
import json
import re
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

#: The package openDox must not require. Spelled once here rather than
#: imported from `opendox.consumer_reach`, because this file must hold even if
#: that module is the thing that broke.
CONSUMER_PACKAGE = "openxdox"

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PACKAGE = SRC / "opendox"

sys.path.insert(0, str(ROOT / "tests"))
from import_scan import imported_modules  # noqa: E402

#: Blocks `openxdox` at the finder, whatever the environment has installed, so
#: the proof holds on a developer machine with openXdox-code on the path and in
#: CI where it is simply absent. A `sys.modules[...] = None` entry is the
#: documented way to make an import raise `ModuleNotFoundError` for a name.
_BLOCK_CONSUMER = """
import sys
sys.modules["openxdox"] = None
"""


def _import_in_subprocess(module: str, *, consumer_blocked: bool,
                          siblings_blocked: bool = False) -> subprocess.CompletedProcess:
    """`import <module>` in a fresh interpreter, with `openxdox` absent or not,
    and with all four `SIBLINGS` absent when `siblings_blocked`."""
    prelude = (_BLOCK_SIBLINGS if siblings_blocked
               else _BLOCK_CONSUMER if consumer_blocked else "")
    program = prelude + f"import {module}\n"
    return subprocess.run([sys.executable, "-c", textwrap.dedent(program)],
                          capture_output=True, text=True, cwd=str(ROOT))


# --------------------------------------------------------------------------
# 1 — the claim this slice actually makes
# --------------------------------------------------------------------------

#: Every module this slice converted to the late seam, and which therefore MUST
#: import with no consumer present. Adding a module here is the whole of the
#: claim a future slice makes; removing one is a regression that has to be
#: argued for on a pull request.
NEUTRAL_MODULES = (
    "opendox.workbench",
    "opendox.serve_workbench",
    "opendox.consumer_reach",
    # BUILD slice 2b. NINE default-argument reads of
    # `gate_console.DEFAULT_RECORDS_DIR` (:1740, :1859, :1878, :4179, :4217,
    # :4254, :4287, :4504, :4991) — evaluated where the `def` sits, so no
    # stand-in could defer them — now read `opendox.defaults`, which is
    # openDox's own spelling of a value openDox owns. openXdox-code's drift
    # guard holds the two spellings together. It is ONE constant at nine sites,
    # not two constants: `DEFAULT_BRANCH_PREFIX` is not reached from this
    # module and `defaults.py` does not carry it.
    "opendox.branch_session",
    # § 4.3 (RULED ASK-2 option (2), openxFactory#656 comment 5628886636). The
    # host-profile registry and the `profile_openxfactory` lazy proxy over it.
    # They are listed here for the reason every other entry is — a module added
    # to this package's import surface is added to this census — and they are
    # the two modules for which the claim is least surprising and most worth
    # stating: a seam whose whole job is to let a HOST hand openDox a profile
    # is precisely where a reach into `openxdox` would look reasonable, and
    # neither of them makes one. openXdox reads this registry, not the reverse
    # (RULED ASK-4 Q5 `5634195861`; `openxdox.domain_profile._upstream()`
    # imports `opendox.domain_profile` late), which is the lawful direction
    # because openXdox PINS openDox (§ 4.2, RULED OQ-2).
    "opendox.domain_profile",
    "opendox.profile_proxy",
    # § 3.4 slice S3, the view registry. Listed here for the reason this list
    # gives itself — "a module added to this package's import surface is added
    # to this census" — and it belongs at the top of the list rather than in
    # `STILL_REACHING`: it reads the host's `VIEW_EXTENSIONS` facet through
    # `opendox.profile_proxy` and imports NOTHING from `openxdox`. The column
    # that CONTRIBUTES a view imports this module, not the other way round,
    # which is the lawful direction because openXdox pins openDox.
    "opendox.view_extension",
    # Plan 034 T011 (#1144 tasks 2.1 and 2.2). These two were the last entries
    # of `STILL_REACHING` below, blocked by `ideation_dashboard` alone.
    # `serve.py` no longer imports openxFactory's lane column, and composes it
    # at build time through the handler-contribution facet instead (R1Q1 (a),
    # openxFactory#656 comment 5817152735). `cli.py` imports `serve`, so it
    # moves with it. They move here IN THE SAME ACT, as the record test asks.
    "opendox.cli",
    "opendox.serve",
)

#: Modules that STILL require the consumer at import time, with the reason. They
#: are listed so the suite is a census of the whole surface rather than of its
#: good half, and each entry names what has to land for it to move up.
#:
#: Modules that still cannot be imported with the consumer blocked — with the
#: reason, and with the PACKAGE NAME whose absence is what actually stops them.
#:
#: THE SECOND FIELD IS SLICE 2b STEP 4's DOING, and it was the whole content
#: of this record until plan 034 T011. Its last two entries were blocked by
#: `ideation_dashboard`, NOT by `openxdox`: the consumer reaches that used to
#: stop them were gone, and what was left was the OTHER cross-column reach —
#: openxFactory's PRE-CARVE package name, a `stays_openxfactory_adapter` row
#: (RULING DQ-1) present at neither carve destination. Two lines down,
#: `test_no_module_under_src_names_the_pre_carve_package_at_import_time`
#: censuses it; it was owed to a later act. Recording only "still reaching"
#: would have let that substitution pass unread: the test would stay green on
#: a nonzero exit while the thing it was written to measure had actually been
#: fixed.
#:
#: So the test below now asserts the blocker BY NAME, and — for an entry whose
#: recorded blocker is not the consumer — asserts that `openxdox` is NOT what
#: the failure names. That turns each of these two rows from a placeholder into
#: a claim: *this module's consumer reach is gone; it waits on something else.*
#:
#: EMPTY SINCE PLAN 034 T011 (#1144 task 2.1). Its two entries, `opendox.cli`
#: and `opendox.serve`, were blocked by `ideation_dashboard` alone, and both
#: import now, so both moved into `NEUTRAL_MODULES` above in the same act. The
#: record is kept, empty, for the next module that needs it.
#:
#: RE-DERIVED BY PLAN 034 T034, OVER THE WHOLE PACKAGE, where phase 1's lanes
#: joined (T032's sweep: no import-time reach into any sibling, and every
#: deferred reach left is into `openxdox`, inside a function body). Every
#: module the package's files define was imported with the consumer blocked,
#: and none failed on a sibling. So empty is a MEASUREMENT, not the absence of
#: one, and `test_the_record_is_the_whole_packages_own` takes it again on
#: every run. The record is then a census of the whole surface, as the
#: paragraph above says it is, and not only of the modules somebody listed.
STILL_REACHING: dict[str, tuple[str, str]] = {}

#: The four packages a module of this one may not need at import time: the
#: consumer and publisher columns, and openxFactory's own two. The first is
#: `CONSUMER_PACKAGE`. A failure naming any of the four is a reach, and the
#: record's to hold. A failure naming anything else is not a reach, and it is
#: not let pass either: the derivation below reads past exactly one kind, the
#: runtime extra's absence inside `opendox.runtime`, and refuses every other.
SIBLINGS = (CONSUMER_PACKAGE, "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: `_BLOCK_CONSUMER` for all four. The record's two tests import with this,
#: so a sibling the environment happens to have installed (an openxFactory
#: checkout on a developer's path, say) cannot let a module that needs it
#: import, and drop out of the census.
_BLOCK_SIBLINGS = "import sys\n" + "".join(
    f"sys.modules[{name!r}] = None\n" for name in SIBLINGS)

#: The `runtime` extra (`pyproject.toml`, `split-opendox` § 3.5): each
#: distribution it lists, with the top-level modules that installing it puts
#: on the path and that `opendox.runtime` imports. `pydantic` arrives as
#: fastapi's own requirement, and `psycopg_pool` as psycopg's `pool` extra.
#: An install without the extra leaves them out (the required job's did,
#: until plan 034 T036 gave it the extra), so there `opendox.runtime.app`
#: fails on `fastapi`, `db` on `psycopg` and `oidc` on `httpx`, which are
#: packages that environment was never asked for. That is
#: the one failure the record's derivation lets pass, and only inside
#: `opendox.runtime`, only while the package really is absent.
#: `test_the_runtime_extra_is_the_one_pyproject_declares` holds the keys to
#: pyproject's own list. `test_the_runtime_extras_modules_are_the_runtimes_own`
#: holds the modules to what `opendox.runtime` imports, and, where the extra
#: is installed, to the installed metadata.
RUNTIME_EXTRA: dict[str, tuple[str, ...]] = {
    "fastapi": ("fastapi", "pydantic"),
    "uvicorn": ("uvicorn",),
    "psycopg": ("psycopg", "psycopg_pool"),
    "PyJWT": ("jwt",),
    "httpx": ("httpx",),
}
RUNTIME_PACKAGE = "opendox.runtime"


@pytest.mark.parametrize("module", NEUTRAL_MODULES)
def test_the_neutral_modules_import_with_no_consumer_installed(module: str) -> None:
    """openDox's own modules do not require the layer that pins openDox."""
    done = _import_in_subprocess(module, consumer_blocked=True)
    assert done.returncode == 0, (
        f"`import {module}` FAILED with `openxdox` unimportable, so openDox "
        f"still requires the layer that pins it:\n{done.stderr}\n"
        "openXdox pins openDox and openDox pins nothing back (split-opendox "
        "§ 4.2, RULED OQ-2): a neutral openDox must import with no consumer "
        "present. This is the assertion the openXdox-side per-module ratchet "
        "cannot make, because a default-argument reach is not an Import node")


def test_the_reaching_modules_are_recorded_as_reaching() -> None:
    """The other half, recorded rather than asserted away — and each entry
    MUST fail.

    A module that starts importing is not a failure of this repository, it is
    a slice landing; the test then tells the author to move it into
    `NEUTRAL_MODULES`, which is where the claim is made. Recording it this way
    is what stops the list above from silently becoming a list of two.

    ONE TEST THAT WALKS THE RECORD, not one case per entry. The record has been
    empty since plan 034 T011, and a parametrization over an empty record is
    not a passing case: pytest reports it as an "empty parameter set" SKIP.
    `validate.yml`'s `Pin the triple` pins SKIPPED exactly, so that would be a
    new skip standing for no test at all.
    """
    for module, (_reason, blocker) in sorted(STILL_REACHING.items()):
        _assert_still_reaching(module, blocker)


def _assert_still_reaching(module: str, blocker: str) -> None:
    """One record entry's claim: the import still fails, for its named blocker.

    With all four siblings blocked, as the record's derivation imports, so the
    two tests read the same failure."""
    done = _import_in_subprocess(module, consumer_blocked=True,
                                 siblings_blocked=True)
    assert done.returncode != 0, (
        f"`import {module}` now SUCCEEDS with no sibling importable — good, and the "
        f"record in this file is out of date. Move {module!r} from "
        "STILL_REACHING into NEUTRAL_MODULES in the same act, so the claim is "
        "asserted rather than merely no longer contradicted, and lower "
        "openXdox-code's OPENDOX_BACK_IMPORTS ratchet to the new census")
    # A NONZERO EXIT IS NOT THE CLAIM. A syntax error, a missing `yaml`, or
    # any other breakage would exit nonzero too and would sit here forever
    # being read as "still reaching" — a record that stays green by being
    # broken. So the failure must be the BLOCKED IMPORT and nothing else.
    last = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else ""
    assert last.startswith(("ModuleNotFoundError", "ImportError")), (
        f"`import {module}` failed for a reason that is NOT a blocked import, "
        f"so this record is masking a defect:\n{done.stderr}")
    assert blocker in last, (
        f"`import {module}` raised an import error naming something other "
        f"than {blocker!r}, which is what this record says blocks it — a real "
        f"missing dependency, or a moved blocker, not a layering edge:\n"
        f"{done.stderr}")
    if blocker != CONSUMER_PACKAGE:
        # THE HALF THAT MADE THE SECOND FIELD NECESSARY. This row claims the
        # module's CONSUMER reach is gone and that it waits on something else.
        # Without this line the claim is untested: an `openxdox` reach could
        # come back on a line after the one that raises, and the row would go
        # on reading "still reaching" — true, but no longer about openXdox.
        assert CONSUMER_PACKAGE not in last, (
            f"`import {module}` is recorded as blocked by {blocker!r} with its "
            f"consumer reach removed, but the failure names "
            f"{CONSUMER_PACKAGE!r}:\n{done.stderr}")


def _package_module_names() -> list[str]:
    """Every module the package's FILES define, as a dotted name.

    From the files and not from `pkgutil`, which skips the children of a
    subpackage whose `__init__` fails. Sorted, so a package precedes its own
    modules."""
    names = set()
    for path in PACKAGE.rglob("*.py"):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.add(".".join(parts))
    return sorted(names)


#: One interpreter, all four siblings blocked at the finder, and every module
#: imported in turn. For each module that failed it prints the exception's
#: type; the module the failure could not import, with that `ImportError`'s own
#: type; and whether that module's top-level package is installed here. The
#: missing module is read down the exception's CHAIN, because a late stand-in
#: resolved at import time raises `ConsumerReachUnavailable`, and the
#: `ModuleNotFoundError` naming `openxdox` is its cause.
_DERIVE_THE_RECORD = _BLOCK_SIBLINGS + """
import importlib, importlib.util, json

def missing(exc):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ImportError) and exc.name:
            return exc.name, type(exc).__name__
        exc = exc.__cause__ or exc.__context__
    return "", ""

def installed(name):
    try:
        return importlib.util.find_spec(name.split(".")[0]) is not None
    except (ImportError, ValueError):
        return False

failed = {}
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except Exception as exc:
        module, kind = missing(exc)
        failed[name] = [type(exc).__name__, module, kind,
                        bool(module) and installed(module)]
print(json.dumps(failed))
"""


def _an_absent_runtime_extra(module: str, missing: str, kind: str,
                             installed: bool) -> bool:
    """The one failure the derivation reads past: a module of the runtime
    subpackage that cannot find a package of the runtime extra, because this
    environment did not install the extra."""
    extra = {name for names in RUNTIME_EXTRA.values() for name in names}
    return (kind == "ModuleNotFoundError" and not installed
            and missing.split(".")[0] in extra
            and (module == RUNTIME_PACKAGE
                 or module.startswith(RUNTIME_PACKAGE + ".")))


def test_the_record_is_the_whole_packages_own() -> None:
    """`STILL_REACHING` is DERIVED over the whole package on every run, not
    kept by hand (plan 034 T034).

    Every module the package's files define is imported, with all four
    siblings blocked. The set that fails on a SIBLING, with the sibling it
    names, must be exactly the record. `NEUTRAL_MODULES` names nine of the
    package's modules, and before this a module that was in neither list could
    start needing `openxdox` at import time and pass this whole file. One that
    starts needing a sibling now fails here, naming it. One the record carries
    that imports again fails `test_the_reaching_modules_are_recorded_as_reaching`,
    as before.

    EVERY OTHER FAILURE IS CLASSIFIED, NOT DROPPED. A module that fails for
    any other reason says nothing about its reaches, so the census could pass
    over it. The one failure read past is `_an_absent_runtime_extra`'s. A
    syntax error, a broken module of openDox's own, a missing required
    dependency, or a runtime package a module outside `opendox.runtime` needs,
    fails here by name."""
    names = _package_module_names()
    assert len(names) > len(NEUTRAL_MODULES), names
    done = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_DERIVE_THE_RECORD),
         json.dumps(names)],
        capture_output=True, text=True, cwd=str(ROOT))
    assert done.returncode == 0, done.stderr
    failed = json.loads(done.stdout)
    derived, unexplained = {}, {}
    for module, (raised, missing, kind, installed) in failed.items():
        root = missing.split(".")[0]
        if root in SIBLINGS:
            derived[module] = root
        elif not _an_absent_runtime_extra(module, missing, kind, installed):
            unexplained[module] = (f"{raised}; the import it could not make: "
                                   f"{missing or 'none'} ({kind or 'no ImportError'})")
    assert not unexplained, (
        "these modules fail to import for a reason that is not a sibling, so "
        f"the census cannot say what they reach: {unexplained}. Only a module "
        f"of {RUNTIME_PACKAGE} missing a package of the runtime extra, where "
        "the extra is not installed, is read past. Anything else is a defect "
        "to fix, not a reach to record")
    recorded = {module: blocker
                for module, (_reason, blocker) in STILL_REACHING.items()}
    assert derived == recorded, (
        f"with the four siblings blocked, these modules fail on a sibling at "
        f"import time: {derived}; the record says {recorded}. A module that "
        "NEWLY needs a sibling to import is the wrong-direction edge design.md "
        "forbids: remove the reach. If it has to stand for now, record it in "
        "STILL_REACHING with its reason and its blocker, which is the argument "
        "its pull request has to make")


def _distribution(requirement: str) -> str:
    """A requirement's distribution name, normalized as PEP 503 compares them."""
    name = re.match(r"[A-Za-z0-9._-]+", requirement.strip()).group(0)
    return re.sub(r"[-_.]+", "-", name).lower()


def test_the_runtime_extra_is_the_one_pyproject_declares() -> None:
    """`RUNTIME_EXTRA` lists exactly the distributions of pyproject's `runtime`
    extra. So the one failure the derivation reads past cannot grow beyond the
    packages this package declares, or fall behind them."""
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = {_distribution(requirement)
                for requirement in project["optional-dependencies"]["runtime"]}
    tabled = {_distribution(name) for name in RUNTIME_EXTRA}
    assert tabled == declared, (
        f"pyproject's runtime extra lists {sorted(declared)}, and this file's "
        f"RUNTIME_EXTRA lists {sorted(tabled)}. Give each distribution of the "
        "extra its row, with the modules it puts on the path")


def _third_party_imports(directory: Path) -> set[str]:
    """The top-level packages the modules under `directory` import, other than
    the standard library's and openDox's own, read with the shared scanner."""
    names = {name.split(".")[0] for path in directory.rglob("*.py")
             for name, _line in imported_modules(path)}
    return names - set(sys.stdlib_module_names) - {"opendox"}


def _requirement_tree(distribution: str) -> set[str]:
    """`distribution` and every distribution its requirements name, however
    deep, among those installed here (PEP 503 names)."""
    seen: set[str] = set()
    queue = [distribution]
    while queue:
        name = _distribution(queue.pop())
        if name in seen:
            continue
        seen.add(name)
        try:
            queue += importlib.metadata.requires(name) or []
        except importlib.metadata.PackageNotFoundError:
            pass
    return seen


def test_the_runtime_extras_modules_are_the_runtimes_own() -> None:
    """The modules `RUNTIME_EXTRA` exempts are exactly what `opendox.runtime`
    needs from the extra.

    1. Each is imported by a module of `opendox.runtime`, so an invented entry
       exempts nothing.
    2. Every third-party package `opendox.runtime` imports is tabled, or comes
       from one of the package's REQUIRED dependencies, so an undeclared
       dependency cannot hide behind the exemption either.
    3. Where a tabled distribution is installed, each of its modules is
       installed by it or by a distribution it requires, as its metadata says.
       Where none is installed (a checkout without the `runtime` extra), 1
       and 2 hold the table.
    """
    imported = _third_party_imports(PACKAGE / "runtime")
    tabled = {name for names in RUNTIME_EXTRA.values() for name in names}
    provided = importlib.metadata.packages_distributions()
    required = {_distribution(requirement)
                for requirement in importlib.metadata.requires("opendox") or []
                if "extra ==" not in requirement}
    from_requirements = {name for name, sources in provided.items()
                         if any(_distribution(s) in required for s in sources)}
    assert tabled <= imported, (
        f"RUNTIME_EXTRA exempts {sorted(tabled - imported)}, which no module "
        f"of {RUNTIME_PACKAGE} imports")
    assert imported <= tabled | from_requirements, (
        f"{RUNTIME_PACKAGE} imports {sorted(imported - tabled - from_requirements)}, "
        "which neither the runtime extra nor the package's own requirements "
        "provide. Declare it, and give it its row")
    for distribution, names in RUNTIME_EXTRA.items():
        try:
            importlib.metadata.distribution(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
        tree = _requirement_tree(distribution)
        for name in names:
            sources = {_distribution(s) for s in provided.get(name, [])}
            assert sources & tree, (
                f"{name!r} is tabled under {distribution}, and here it is "
                f"installed by {sorted(sources)}, which is neither "
                f"{distribution} nor anything it requires")


# --------------------------------------------------------------------------
# 2 — the seam itself, exercised at run time
# --------------------------------------------------------------------------

def test_importing_the_seam_resolves_nothing() -> None:
    """Constructing a stand-in performs no import.

    The whole value of the module is that `import opendox.consumer_reach` is
    free; a stand-in that resolved eagerly would be an import statement wearing
    a different hat.
    """
    done = _import_in_subprocess("opendox.consumer_reach", consumer_blocked=True)
    assert done.returncode == 0, done.stderr


def test_first_attribute_access_refuses_naming_the_layering() -> None:
    from opendox import consumer_reach

    absent = consumer_reach.module("no_such_column", reason="a test's own")
    with pytest.raises(consumer_reach.ConsumerReachUnavailable) as caught:
        absent.anything
    message = str(caught.value)
    assert "openxdox.no_such_column" in message
    assert "RULED OQ-2" in message, (
        "the refusal must name the LAYERING — which way the pin runs — rather "
        "than reading as a missing-module accident")
    assert isinstance(caught.value.__cause__, ModuleNotFoundError), (
        "the original ModuleNotFoundError is chained, so a reader still gets "
        "the import machinery's own account beneath the layering one")


def test_a_consumer_module_that_exists_and_raises_is_re_raised_untouched() -> None:
    """`except ImportError` wholesale would blame the layering for a bug.

    A consumer module that IS present and fails while executing — because one
    of ITS dependencies is missing — must surface as that failure, not as
    `ConsumerReachUnavailable`, or the reader is sent to the wrong repository.
    """
    from opendox import consumer_reach

    reach = consumer_reach.module("cheerfully_broken", reason="a test's own")
    broken = ModuleNotFoundError("No module named 'jsonschema'", name="jsonschema")

    def _raise(_dotted: str):
        raise broken

    original = consumer_reach.importlib.import_module
    consumer_reach.importlib.import_module = _raise
    try:
        with pytest.raises(ModuleNotFoundError) as caught:
            reach.anything
    finally:
        consumer_reach.importlib.import_module = original
    assert caught.value is broken
    assert not isinstance(caught.value, consumer_reach.ConsumerReachUnavailable)


def test_resolution_forwards_to_the_real_module_and_caches(tmp_path: Path) -> None:
    from opendox import consumer_reach

    module_object = type(sys)("openxdox.pretend")
    module_object.ANSWER = 42
    module_object.verb = lambda x: x * 2
    reach = consumer_reach.module("pretend", reason="a test's own")
    sys.modules["openxdox.pretend"] = module_object
    # The fake PARENT is removed again below only if this test created it.
    # Leaving an empty `openxdox` package in `sys.modules` would make every
    # later test in the process see an importable-but-empty consumer instead
    # of normal import behaviour — including this file's own seam tests.
    parent_was_created = "openxdox" not in sys.modules
    if parent_was_created:
        sys.modules["openxdox"] = type(sys)("openxdox")
    try:
        assert reach.ANSWER == 42
        assert reach.resolve() is module_object
        assert reach.resolve() is module_object, "the resolved module is cached"
        assert consumer_reach.function(reach, "verb")(3) == 6, (
            "a late callable forwards arguments and the return value")
    finally:
        sys.modules.pop("openxdox.pretend", None)
        if parent_was_created:
            sys.modules.pop("openxdox", None)


def test_a_dunder_lookup_does_not_resolve_the_consumer() -> None:
    """`copy`, `pickle`, `inspect` and pytest all probe for dunders.

    Resolving openXdox because something asked for `__wrapped__` would fire the
    reach at a moment no verb chose — and, with the consumer absent, would turn
    an innocuous introspection into `ConsumerReachUnavailable`.
    """
    from opendox import consumer_reach

    reach = consumer_reach.module("never_resolved", reason="a test's own")
    with pytest.raises(AttributeError):
        reach.__wrapped__
    assert "unresolved" in repr(reach)


@pytest.fixture()
def pretend_corpus_root():
    """A stand-in for `openxdox.corpus_root` carrying a `SCANNED_ROOTS` tuple.

    Installed in `sys.modules` rather than imported, so the test holds on a
    machine with openXdox-code present and in CI where it is absent — and the
    fake PARENT is removed again only if this fixture created it, because
    leaving an empty `openxdox` package behind would make every later test in
    the process see an importable-but-empty consumer.
    """
    module_object = type(sys)("openxdox.corpus_root")
    module_object.SCANNED_ROOTS = ("contracts", "docs", "openspec")
    sys.modules["openxdox.corpus_root"] = module_object
    parent_was_created = "openxdox" not in sys.modules
    if parent_was_created:
        sys.modules["openxdox"] = type(sys)("openxdox")
    try:
        yield module_object
    finally:
        sys.modules.pop("openxdox.corpus_root", None)
        if parent_was_created:
            sys.modules.pop("openxdox", None)


def test_constructing_a_constant_resolves_nothing() -> None:
    """The laziness claim, made for the VALUE member of the family.

    `scanned_roots` is built at `consumer_reach` import time, in a package that
    must import with no consumer present. If construction resolved, the module
    that exists to remove import-time reaches would itself be one.
    """
    from opendox import consumer_reach

    absent = consumer_reach.constant(
        consumer_reach.module("no_such_column", reason="a test's own"), "ROOTS")
    assert "no_such_column.ROOTS" in repr(absent)
    assert "<late consumer value" in repr(absent), (
        "repr must not resolve either: a debugger, a logging call and pytest's "
        "own assertion rewriting all reach for it, and resolving there would "
        "fire the reach at a moment no verb chose")


def test_the_sequence_operations_a_re_exported_constant_meets(
        pretend_corpus_root) -> None:
    """Every operation `SCANNED_ROOTS` is actually subjected to, forwarded.

    `cli.py`:228 iterates it; the rest are what a re-exported sequence constant
    meets from a caller who believes it is still the tuple it was. The point of
    the assertions is that the stand-in is INDISTINGUISHABLE from the tuple at
    these operations — anything less and the name could not have been left in
    place on a line the carve manifest does not declare.
    """
    from opendox import consumer_reach

    roots = consumer_reach.constant(
        consumer_reach.module("corpus_root", reason="a test's own"),
        "SCANNED_ROOTS")
    real = pretend_corpus_root.SCANNED_ROOTS

    assert list(roots) == list(real), "iteration — cli.py:228's `for root in ...`"
    assert len(roots) == 3
    assert "docs" in roots
    assert "no-such-root" not in roots
    assert roots[0] == "contracts"
    assert roots[-1] == "openspec"
    assert list(roots[1:]) == ["docs", "openspec"], "slicing is indexing too"
    assert roots == real, "equality against the real tuple"
    assert not (roots != real)
    assert roots != ("something", "else")
    assert bool(roots) is True
    assert str(roots) == str(real)
    assert hash(roots) == hash(real), (
        "a constant re-exported into a set or a dict key must hash as its value")
    assert roots.resolve() is real


def test_a_constant_does_not_forward_attribute_reads(pretend_corpus_root) -> None:
    """`__getattr__` is deliberately absent — the refusal is part of the design.

    An attribute read on a constant is almost always a caller who wanted the
    MODULE, and answering it would turn the value stand-in into the general
    facade this module refuses to be. It must fail as an `AttributeError`, the
    way the tuple it stands for would.
    """
    from opendox import consumer_reach

    roots = consumer_reach.constant(
        consumer_reach.module("corpus_root", reason="a test's own"),
        "SCANNED_ROOTS")
    with pytest.raises(AttributeError):
        roots.corpus_root_refusal


def test_an_unavailable_consumer_refuses_at_the_operation_not_at_the_binding() -> None:
    """The error path, and WHERE it fires: at use, naming the layering.

    With no consumer installed the binding is still constructed — that is the
    whole point — so the refusal has to arrive at the first operation, and it
    has to name which way the pin runs rather than reading as a missing-module
    accident.
    """
    from opendox import consumer_reach

    absent = consumer_reach.constant(
        consumer_reach.module("no_such_column", reason="a test's own"), "ROOTS")

    for operation in (lambda: list(absent),
                      lambda: len(absent),
                      lambda: "x" in absent,
                      lambda: absent[0],
                      lambda: absent == ("x",),
                      lambda: absent != ("x",),
                      lambda: hash(absent),
                      lambda: bool(absent),
                      lambda: str(absent),
                      lambda: absent.resolve()):
        with pytest.raises(consumer_reach.ConsumerReachUnavailable) as caught:
            operation()
        message = str(caught.value)
        assert "openxdox.no_such_column" in message
        assert "RULED OQ-2" in message
        assert isinstance(caught.value.__cause__, ModuleNotFoundError)


@pytest.fixture()
def pretend_column():
    """A stand-in for a consumer module carrying one handler-method COLUMN.

    The methods are written the way the real columns are — plain functions on a
    class, called with the live request handler as `self` — so what the test
    exercises is the forwarding contract and not a mock's idea of it.
    """
    module_object = type(sys)("openxdox.pretend_routes")

    class PretendRoutes:
        def _serve_thing(self, path, *, keyed=False):
            # Reads state off `self`, which is the whole point: the forwarder
            # must pass the HANDLER, not the column, as `self`.
            return f"{self.marker}:{path}:{keyed}"

        def _refuse_thing(self):
            return f"{self.marker}:refused"

    module_object.PretendRoutes = PretendRoutes
    sys.modules["openxdox.pretend_routes"] = module_object
    parent_was_created = "openxdox" not in sys.modules
    if parent_was_created:
        sys.modules["openxdox"] = type(sys)("openxdox")
    try:
        yield module_object
    finally:
        sys.modules.pop("openxdox.pretend_routes", None)
        if parent_was_created:
            sys.modules.pop("openxdox", None)


def _late_handler(consumer_reach, methods=("_serve_thing", "_refuse_thing")):
    """A `DashboardHandler`-shaped class over a late column, as `serve.py` builds one."""
    column = consumer_reach.route_column(
        consumer_reach.module("pretend_routes", reason="a test's own"),
        "PretendRoutes", methods)

    class Handler(column):
        marker = "handler"

    return column, Handler


def test_a_late_column_is_built_without_resolving_the_consumer() -> None:
    """The class statement runs at IMPORT time — this is the whole reason the

    column member exists. A base that resolved while being built would defer
    nothing: `DashboardHandler`'s bases are evaluated when `serve.py` loads.
    """
    from opendox import consumer_reach

    column, Handler = _late_handler(consumer_reach)
    assert Handler.marker == "handler"
    assert column.LATE_COLUMN == ("openxdox.pretend_routes", "PretendRoutes",
                                  ("_serve_thing", "_refuse_thing")), (
        "the triple openXdox-code's drift guard reads to hold the two surfaces "
        "together must name the module, the class and the method list")
    assert column._serve_thing.__name__ == "_serve_thing", (
        "the forwarder keeps the method's NAME, because a contributed binding "
        "is resolved against the bound class BY NAME at wiring time")


def test_the_forwarders_call_the_consumer_with_the_handler_as_self(
        pretend_column) -> None:
    """The contract: same function object, same `self`, same arguments.

    `route_extension.resolve_handlers` refuses a route that cannot be served
    before a socket is opened, and it resolves the handler by name against the
    BOUND CLASS — so a wrong method list or a forwarding signature that dropped
    an argument would leave imports green and break requests, which is exactly
    what this test is here to stop.
    """
    from opendox import consumer_reach

    _column, Handler = _late_handler(consumer_reach)
    handler = Handler()

    assert handler._serve_thing("/a/b") == "handler:/a/b:False", (
        "positional arguments forward, and `self` is the HANDLER — the column's "
        "method reads `self.marker`, which only the handler has")
    assert handler._serve_thing("/a/b", keyed=True) == "handler:/a/b:True", (
        "keyword arguments forward too")
    assert handler._refuse_thing() == "handler:refused"
    assert handler._serve_thing.__func__ is not \
        pretend_column.PretendRoutes._serve_thing, (
        "the BOUND method is the forwarder, not the column's function")


def test_a_late_column_answers_only_the_names_it_was_given(pretend_column) -> None:
    """No `__getattr__`, deliberately, and the absence is asserted.

    A handler instance is probed for absent attributes constantly — `http.server`
    asks `hasattr(self, "do_PUT")`, and `copy`, `pickle` and pytest all probe —
    so a base that answered those by importing openXdox would fire the reach at
    a moment no verb chose, and would raise `ConsumerReachUnavailable` where the
    caller was testing for `AttributeError`.
    """
    from opendox import consumer_reach

    _column, Handler = _late_handler(consumer_reach, methods=("_serve_thing",))
    handler = Handler()

    assert handler._serve_thing("/x") == "handler:/x:False"
    with pytest.raises(AttributeError):
        handler.do_PUT
    with pytest.raises(AttributeError):
        # Present on the consumer's column, absent from the NAMED list: a name
        # left out of the list is left out of the class, not silently proxied.
        handler._refuse_thing
    assert not hasattr(handler, "_refuse_thing")


def test_a_late_column_with_no_consumer_refuses_at_the_call() -> None:
    """Construction succeeds, the call refuses, and the refusal names the layering."""
    from opendox import consumer_reach

    column = consumer_reach.route_column(
        consumer_reach.module("no_such_column", reason="a test's own"),
        "NoRoutes", ("_serve_thing",))

    class Handler(column):
        marker = "handler"

    with pytest.raises(consumer_reach.ConsumerReachUnavailable) as caught:
        Handler()._serve_thing("/x")
    message = str(caught.value)
    assert "openxdox.no_such_column" in message
    assert "RULED OQ-2" in message
    assert isinstance(caught.value.__cause__, ModuleNotFoundError)


def test_a_column_standing_in_for_nothing_is_refused() -> None:
    """An empty method list would build a base that inherits nothing and hides it."""
    from opendox import consumer_reach

    with pytest.raises(ValueError, match="name the methods"):
        consumer_reach.route_column(
            consumer_reach.module("pretend_routes", reason="a test's own"),
            "PretendRoutes", ())


def test_the_two_live_columns_name_the_methods_serve_dispatches() -> None:
    """The real bindings, held against the names `serve.py` and § 2.4 rely on.

    `_serve_snapshot` is the one to watch: `/snapshot.json`'s HANDLER travelled
    to the projection column while its dispatch ARM stayed core, so `serve.py`
    itself calls `self._serve_snapshot`. Dropping it from the list would leave
    every import green and `/snapshot.json` broken.
    """
    from opendox import consumer_reach

    gate_module, gate_class, gate_methods = \
        consumer_reach.LateGateRoutes.LATE_COLUMN
    assert (gate_module, gate_class) == ("openxdox.serve_gate", "GateRoutes")
    assert "_handle_gate_action" in gate_methods, (
        "the route the § 2.4 gate binding declares")

    proj_module, proj_class, proj_methods = \
        consumer_reach.LateProjectionRoutes.LATE_COLUMN
    assert (proj_module, proj_class) == ("openxdox.serve_projection",
                                        "ProjectionRoutes")
    for required in ("_serve_snapshot", "_serve_index"):
        assert required in proj_methods, (
            f"{required} is dispatched by name and must be on the column")
    # § 3.4 SLICE S6, RULED Q4 (openxFactory#656 comment 5642758731): the
    # `/source` pair is `serve.py`'s own FIXED CORE ARM now, so the three
    # methods that answer it must NOT be forwarded into the consumer. Asserted
    # as an ABSENCE and not left as silence: a forwarder left behind here would
    # be invisible — the route would keep working wherever openXdox happens to
    # be installed, which is every developer machine and neither claim this
    # slice makes.
    for departed in ("_keyed_source", "_serve_source", "_refuse_bare_source"):
        assert departed not in proj_methods, (
            f"{departed} answers /source, which RULED Q4 makes openDox's own "
            "core arm; it must be defined in serve.py, not forwarded to "
            "openxdox.serve_projection")


def test_the_prefix_is_refused_rather_than_doubled() -> None:
    from opendox import consumer_reach

    with pytest.raises(ValueError, match="WITHOUT"):
        consumer_reach.module("openxdox.gate_console", reason="a test's own")


# --------------------------------------------------------------------------
# 3 — the converted sites, and the blind spot that made this file necessary
# --------------------------------------------------------------------------

#: `module path -> the names this slice rebound to the late seam`. Each must be
#: reachable ONLY from a function body: a default argument, an annotation, a
#: decorator or a module-level expression would resolve the consumer at import
#: time and make the conversion a census trick.
CONVERTED_SITES = {
    # RE-DERIVED BY PLAN 034 T034 from the tree, where phase 1's lanes joined:
    # every module-level name bound to a `consumer_reach` stand-in, which
    # `test_every_name_bound_to_the_seam_is_guarded` below now derives on every
    # run. The table had fallen behind by five names in two files, and the
    # guard never read them:
    #   * `branch_session.py`'s `gate_console`. This is one of the two reverts
    #     the guard is named for (the NINE default-argument sites this file's
    #     docstring gives), and it was the one module the table left out;
    #   * `cli.py`'s other four aliases, the two late callables BUILD slice 2b
    #     bound for the generate verbs and the `--generated-at` check, and the
    #     one late constant. Calling a late callable, or iterating the late
    #     constant, at import time resolves the consumer as surely as reading
    #     `gate_mod` does.
    # None of the five is read at import time, so the tree was already right.
    "branch_session.py": ("gate_console",),
    "cli.py": ("gate_mod", "snapshot_mod", "corpus_root_refusal",
               "generate_snapshot", "is_rfc3339_datetime", "SCANNED_ROOTS"),
    "serve_workbench.py": ("registry_mod",),
    "workbench.py": ("find_validator",),
    # Slice 2b step 4. `consumer_reach` and `defaults` are deliberately NOT
    # listed: both ARE read at import time and must be. Constructing a stand-in
    # resolves nothing (`test_importing_the_seam_resolves_nothing`), and the two
    # late COLUMNS are mixin bases, which a class statement needs before its
    # first instance exists; `defaults` is openDox's own module, which is the
    # point of it. What must not be read at import time is a name BOUND to a
    # stand-in, and these are serve.py's two.
    #
    # § 3.4 SLICE S6, RULED Q4: `resolve_source_path` LEFT this tuple because it
    # stopped being a stand-in — it is a real `def` in `serve.py` now, reaching
    # `registry_mod.resolve_within` from inside a function body like every other
    # deferred use. Nothing is unguarded by the removal: `registry_mod` is still
    # listed, and that is the name the containment call actually reads.
    "serve.py": ("registry_mod", "hosted_ref_refused"),
}


def _import_time_uses(path: Path, names: frozenset[str]) -> list[tuple[int, str]]:
    """Every use of `names` that runs when the module is imported.

    The module body, module-level `if`/`try`/`with`, CLASS bodies, and — the
    case the openXdox-side census cannot see — a function's DEFAULTS,
    ANNOTATIONS and DECORATORS, which are evaluated where the `def` sits and
    not where it is called. Only a function BODY defers.
    """
    hits: list[tuple[int, str]] = []

    def used(node: ast.AST, why: str) -> None:
        for inner in ast.walk(node):
            # READS only. The one module-level STORE of each of these names is
            # the seam binding itself (`gate_mod = consumer_reach.gate_console`)
            # — the line this slice wrote, which resolves nothing.
            if isinstance(inner, ast.Name) and inner.id in names \
                    and isinstance(inner.ctx, ast.Load):
                hits.append((inner.lineno, f"{inner.id} ({why})"))

    def walk(body: list[ast.stmt], at_import_time: bool) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if at_import_time:
                    args = node.args
                    for default in [*args.defaults, *(d for d in args.kw_defaults if d)]:
                        used(default, "default argument")
                    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs,
                                args.vararg, args.kwarg]:
                        if arg is not None and arg.annotation is not None:
                            used(arg.annotation, "annotation")
                    for decorator in node.decorator_list:
                        used(decorator, "decorator")
                    if node.returns is not None:
                        used(node.returns, "return annotation")
                continue
            if not at_import_time:
                continue
            nested: list[ast.stmt] = []
            for _field, value in ast.iter_fields(node):
                items = value if isinstance(value, list) else [value]
                for item in items:
                    if isinstance(item, ast.stmt):
                        nested.append(item)
                    elif isinstance(item, ast.AST):
                        used(item, "module level")
            walk(nested, True)

    walk(ast.parse(path.read_text(encoding="utf-8")).body, True)
    return sorted(set(hits))


def _module_level_statements(body: list[ast.stmt]):
    """The statements a module runs when it is imported, in source order: its
    body, and the bodies of a module-level `if`, `try`, `with`, `for`,
    `while` or `match`, with their handlers and `else` blocks. A function's
    body and a class's are not the module's names."""
    for node in body:
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for _field, value in ast.iter_fields(node):
            for item in value if isinstance(value, list) else []:
                if isinstance(item, ast.stmt):
                    yield from _module_level_statements([item])
                elif isinstance(item, (ast.ExceptHandler, ast.match_case)):
                    yield from _module_level_statements(item.body)


def _names_bound_to_the_seam(path: Path) -> set[str]:
    """Every name a module binds, at its top level, to a `consumer_reach`
    stand-in.

    Every spelling of the seam counts. `from .consumer_reach import X` (`..`
    in a subpackage) and `from opendox.consumer_reach import X` bind one
    directly. Once the seam itself is reachable, so do `Y = <seam>.X`, its
    annotated form `Y: T = <seam>.X`, and `Y = <seam>.f(...)`, which mints one
    (`module`, `function`, `constant`). `<seam>` is a name bound to the
    module (`from . import consumer_reach`, `import opendox.consumer_reach as
    cr`, or `cr = consumer_reach` after either), or the package's attribute
    `opendox.consumer_reach`, once `import opendox` or `import
    opendox.consumer_reach` has bound `opendox`. Each is read wherever the
    module runs it at import time, a module-level `if` or `try` included."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # The leading dots from this file to the `opendox` package: one for a
    # module at the top of it, two in a subpackage, and so on.
    level = len(path.relative_to(PACKAGE).parts)
    seam_aliases: set[str] = set()
    package_aliases: set[str] = set()
    bound: set[str] = set()
    statements = list(_module_level_statements(tree.body))
    for node in statements:
        if isinstance(node, ast.ImportFrom):
            package = (node.level == level and node.module is None) or \
                (node.level == 0 and node.module == "opendox")
            seam = (node.level == level and node.module == "consumer_reach") or \
                (node.level == 0 and node.module == "opendox.consumer_reach")
            if package:
                seam_aliases |= {a.asname or a.name for a in node.names
                                 if a.name == "consumer_reach"}
            if seam:
                bound |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "opendox.consumer_reach" and alias.asname:
                    seam_aliases.add(alias.asname)
                elif alias.name == "opendox" or (
                        alias.name.startswith("opendox.") and not alias.asname):
                    package_aliases.add(alias.asname or "opendox")

    def is_the_seam(expr: ast.expr | None) -> bool:
        return (isinstance(expr, ast.Name) and expr.id in seam_aliases) or (
            isinstance(expr, ast.Attribute) and expr.attr == "consumer_reach"
            and isinstance(expr.value, ast.Name)
            and expr.value.id in package_aliases)

    for node in statements:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = {t.id for t in targets if isinstance(t, ast.Name)}
        if is_the_seam(node.value):
            seam_aliases |= names
            continue
        value = node.value.func if isinstance(node.value, ast.Call) else node.value
        if isinstance(value, ast.Attribute) and is_the_seam(value.value):
            bound |= names
    return bound


def test_every_name_bound_to_the_seam_is_guarded() -> None:
    """The guard's table is the tree's, name for name (plan 034 T034).

    A name bound to the seam and missing from `CONVERTED_SITES` is a name the
    import-time guard never reads. A name the table keeps and no module binds
    any more is a guard over nothing. The seam's own module is left out: it
    DEFINES the stand-ins."""
    derived = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "consumer_reach.py":
            continue
        bound = _names_bound_to_the_seam(path)
        if bound:
            derived[path.relative_to(PACKAGE).as_posix()] = bound
    starred = sorted(module for module, names in derived.items() if "*" in names)
    assert not starred, (
        f"{starred} import the seam's stand-ins with a wildcard. The guard "
        "reads each converted name by name, and a wildcard gives it none to "
        "read: import each stand-in by its name")
    declared = {module: set(names) for module, names in CONVERTED_SITES.items()}
    assert derived == declared, (
        f"the names each module binds to `consumer_reach` are {derived}, and "
        f"CONVERTED_SITES guards {declared}. Add a new binding to the table, so "
        "its import-time uses are refused, and take a retired one out")


@pytest.mark.parametrize("module_file", sorted(CONVERTED_SITES))
def test_a_converted_name_is_never_used_at_import_time(module_file: str) -> None:
    """The guard that would have caught the two reverts before they were made."""
    found = _import_time_uses(PACKAGE / module_file,
                              frozenset(CONVERTED_SITES[module_file]))
    assert found == [], (
        f"src/opendox/{module_file} uses a late-bound consumer name where it "
        f"runs AT IMPORT TIME: {found}. The stand-in would resolve `openxdox` "
        "there, so removing the import statement would lower openXdox-code's "
        "ratchet without removing the dependency — a census that reads better "
        "than the tree. Defer the use, or leave the import alone and ask for "
        "the declared-edit ruling")


def test_no_module_under_src_names_the_pre_carve_package_at_import_time() -> None:
    """`ideation_dashboard` is openxFactory's PRE-CARVE name, not a dependency.

    ZERO SINCE PLAN 034 T011 (#1144 task 2.1). `serve.py` reached
    `ideation_dashboard.serve_openxfactory_lanes` twice at import time. That is
    a `stays_openxfactory_adapter` row (RULING DQ-1) present at NEITHER carve
    destination, so the carve's `import rewrites` class had nothing lawful to
    rewrite it to. Both statements are gone: the lane column now arrives at
    build time through the handler-contribution facet (R1Q1 (a)). A new one is
    a regression.
    """
    known: dict[str, int] = {}
    seen: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and not node.level and \
                    (node.module or "").split(".")[0] == "ideation_dashboard":
                seen[rel] = seen.get(rel, 0) + 1
            elif isinstance(node, ast.Import) and any(
                    a.name.split(".")[0] == "ideation_dashboard" for a in node.names):
                seen[rel] = seen.get(rel, 0) + 1
    assert seen == known, (
        f"the pre-carve package name's import-time census moved: {seen} "
        f"(recorded {known}). A NEW one is an unapplied rewrite and must not "
        "be added to the record; a FALL is a slice landing and belongs in the "
        "same commit as this number")
