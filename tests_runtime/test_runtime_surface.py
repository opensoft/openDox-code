"""The package's two closures — the collection set and the import weight.

Both are contracts stated in `src/opendox/runtime/__init__.py`, and both are
the kind that stays true for months and then stops being true in a commit
nobody meant it in. So each is MEASURED here rather than described there.

HERMETIC: standard library plus the stdlib-only modules of the package.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from opendox import runtime

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "opendox" / "runtime"

#: The modules whose import must cost STDLIB ONLY. `opendox.runtime.__init__`
#: is in the list because importing any of the others imports it first.
STDLIB_ONLY_MODULES: tuple[str, ...] = (
    "opendox.runtime",
    "opendox.runtime.config",
    "opendox.runtime.migrations",
    "opendox.runtime.identity",
    "opendox.runtime.cli",
)

#: The modules that legitimately need the `runtime` extra, and the only ones.
EXTRA_REQUIRING_MODULES: tuple[str, ...] = ("db", "oidc", "app")

#: The distributions the `runtime` extra brings. None of them may be reachable
#: from a stdlib-only module's import.
EXTRA_TOP_LEVEL_NAMES: frozenset[str] = frozenset(
    {"fastapi", "starlette", "pydantic", "uvicorn", "psycopg", "psycopg_pool",
     "jwt", "httpx", "cryptography"})


def _module_level_imports(path: Path) -> set[str]:
    """Top-level package names imported at MODULE level (not inside a def)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:               # module level only, by construction
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Try):  # a guarded module-level import
            for inner in node.body:
                if isinstance(inner, ast.Import):
                    names.update(a.name.split(".")[0] for a in inner.names)
                elif isinstance(inner, ast.ImportFrom) and inner.module:
                    names.add(inner.module.split(".")[0])
    return names


def test_the_stdlib_only_modules_name_no_extra_package_at_module_level() -> None:
    for dotted in STDLIB_ONLY_MODULES:
        tail = dotted.split(".")[-1]
        path = PACKAGE / ("__init__.py" if dotted == "opendox.runtime"
                          else f"{tail}.py")
        offenders = _module_level_imports(path) & EXTRA_TOP_LEVEL_NAMES
        assert offenders == set(), (
            f"{path.name} imports {sorted(offenders)} at module level. The "
            "package's import-weight contract (see "
            "src/opendox/runtime/__init__.py) is that these modules import "
            "under `.[test]` alone — which is what the leg's REQUIRED "
            "`validate` job installs, and what § 3.7's conformance corpus "
            "will have. Move the import inside the function that needs it.")


def test_the_stdlib_only_modules_really_import_without_the_extra() -> None:
    """The parse above is necessary and not sufficient — so also MEASURE it.

    A fresh interpreter imports each module and reports whether any extra
    distribution ended up in `sys.modules`. This catches a transitive reach the
    AST walk cannot see: a stdlib-only module importing another first-party
    module that imports psycopg.
    """
    program = (
        "import sys\n"
        f"for name in {list(STDLIB_ONLY_MODULES)!r}:\n"
        "    __import__(name)\n"
        f"leaked = sorted(set(sys.modules) & set({sorted(EXTRA_TOP_LEVEL_NAMES)!r}))\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True,
        cwd=str(ROOT), check=False,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    leaked = [name for name in result.stdout.strip().split(",") if name]
    assert leaked == [], (
        f"importing the stdlib-only modules pulled in {leaked}; see the "
        "import-weight contract in src/opendox/runtime/__init__.py")


def test_the_modules_that_need_the_extra_are_exactly_the_three_declared() -> None:
    """Nothing new may quietly join the heavy half."""
    heavy = sorted(
        path.stem for path in PACKAGE.glob("*.py")
        if path.stem != "__init__"
        and _module_level_imports(path) & EXTRA_TOP_LEVEL_NAMES)
    assert heavy == sorted(EXTRA_REQUIRING_MODULES), (
        f"modules needing the `runtime` extra are {heavy}; the declared set is "
        f"{sorted(EXTRA_REQUIRING_MODULES)}")


def test_the_collection_set_is_closed_and_is_what_the_app_mounts() -> None:
    """`COLLECTIONS` and `app.build_v1_router`'s routers are one list.

    Read by PARSING `app.py` rather than by importing it, because this test
    runs in the job that does not install FastAPI. What it reads is the
    `include_router` call list of `build_v1_router`, which is the function
    that decides the surface.
    """
    tree = ast.parse((PACKAGE / "app.py").read_text(encoding="utf-8"))
    builder = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef)
                   and node.name == "build_v1_router")
    mounted = [
        call.args[0].id
        for call in ast.walk(builder)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "include_router"
        and call.args and isinstance(call.args[0], ast.Name)
    ]
    expected = [name.replace("-", "_") for name in runtime.COLLECTIONS]
    assert mounted == expected, (
        f"`build_v1_router` mounts {mounted}; `runtime.COLLECTIONS` declares "
        f"{expected}. RULING Q1 names six things the database owns and the "
        "served surface is that same six: a seventh router is a claim about "
        "the boundary.")


def test_every_mounted_router_declares_its_collections_own_prefix() -> None:
    """A router named `drafts` must not be mounted at `/documents`.

    Read from the assignment's own AST: the symbol `build_v1_router` mounts
    and the prefix the path segment carries have to be the same collection, or
    the closure above is a closure over names and not over routes.
    """
    tree = ast.parse((PACKAGE / "app.py").read_text(encoding="utf-8"))
    prefixes: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            continue
        if not (isinstance(value.func, ast.Name) and value.func.id == "APIRouter"):
            continue
        for keyword in value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                prefixes[target.id] = str(keyword.value.value)
    for collection in runtime.COLLECTIONS:
        symbol = collection.replace("-", "_")
        assert prefixes.get(symbol) == f"/{collection}", (
            f"router {symbol} is declared with prefix {prefixes.get(symbol)!r}, "
            f"not '/{collection}'")


def test_the_api_prefix_is_declared_once() -> None:
    assert runtime.API_V1 == "/api/v1"
    app_source = (PACKAGE / "app.py").read_text(encoding="utf-8")
    assert '"/api/v1"' not in app_source, (
        "app.py spells the API prefix literally; it must read "
        "`opendox.runtime.API_V1`, which the Kubernetes manifests and the "
        "runbook also read — two spellings drift the day one of them moves")


@pytest.mark.parametrize("collection", list(runtime.COLLECTIONS))
def test_no_collection_names_a_governed_document(collection: str) -> None:
    """The served surface reads no document, by name.

    RULING Q1: "Specs, changes, ideation documents and contracts stay in git,
    read from repositories and written back only through the apply lane." A
    route called `/specs` or `/documents` would be that boundary crossed in
    the one place a client would believe it.
    """
    assert collection not in {"specs", "changes", "documents", "ideation",
                              "contracts"}
