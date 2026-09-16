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
#: § 3.6's two modules ARE IN THIS TUPLE even though the § 3.5 branch does not
#: carry them. They were left out of the first cut, and the omission was
#: silent in exactly the way that matters: `_stdlib_only_paths()` walks THIS
#: tuple, so on the § 3.6 branch — where both files exist and the contract is
#: the whole point of them — the AST check and the fresh-interpreter check
#: skipped them, while the assertion below that names them as the only
#: permitted absences passed vacuously (Copilot review of openDox-code#25,
#: suppressed comment). Listed here, `_stdlib_only_paths()` measures whichever
#: of them the branch carries.
STDLIB_ONLY_MODULES: tuple[str, ...] = (
    "opendox.runtime",
    "opendox.runtime.config",
    "opendox.runtime.migrations",
    "opendox.runtime.identity",
    "opendox.runtime.cli",
    # § 3.6's adapter and its act. These two carry the contract's SHARPEST
    # obligation: `split-opendox-two-layer-product` § 3.7's neutral
    # conformance corpus checks this adapter against
    # `opendox.corpus_adapter.CorpusAdapter` in a process that has installed
    # neither a web framework nor a database driver, and an import that needed
    # one would make openDox the only destination the corpus could not test.
    "opendox.runtime.local_git_adapter",
    "opendox.runtime.repository_act",
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


def _stdlib_only_paths() -> list[tuple[str, Path]]:
    """The declared modules THAT THIS TREE CARRIES.

    `local_git_adapter` and `repository_act` arrive with the § 3.6 act stacked
    on § 3.5's branch, so on the § 3.5 branch alone they are absent. The
    contract is declared for both in `opendox/runtime/__init__.py`; what is
    MEASURED is whichever of them is here, which is what keeps this suite
    honest on both branches instead of green on one by being skipped on the
    other.
    """
    found = []
    for dotted in STDLIB_ONLY_MODULES:
        tail = dotted.split(".")[-1]
        path = PACKAGE / ("__init__.py" if dotted == "opendox.runtime"
                          else f"{tail}.py")
        if path.is_file():
            found.append((dotted, path))
    return found


def test_every_declared_stdlib_only_module_that_exists_is_measured() -> None:
    present = [dotted for dotted, _ in _stdlib_only_paths()]
    assert "opendox.runtime" in present
    assert "opendox.runtime.config" in present
    missing = [d for d in STDLIB_ONLY_MODULES if d not in present]
    # The only modules allowed to be absent are § 3.6's two, and only on the
    # § 3.5 branch.
    assert set(missing) <= {"opendox.runtime.local_git_adapter",
                            "opendox.runtime.repository_act"}, missing


def test_the_stdlib_only_modules_name_no_extra_package_at_module_level() -> None:
    for dotted, path in _stdlib_only_paths():
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
        f"for name in {[d for d, _ in _stdlib_only_paths()]!r}:\n"
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


def test_only_asymmetric_algorithms_can_be_configured_and_they_keep_pyjwts_spelling(
) -> None:
    """`EdDSA` is mixed case, and PyJWT's comparison is case-sensitive.

    Upper-casing the configured value turned it into `EDDSA`, which a
    `startswith(("RS", "ES", "PS", "Ed"))` test then classified as symmetric —
    so the one EdDSA broker in the world would have been refused at startup,
    and had it got past that, no token would have matched (Copilot review of
    openDox-code#25).
    """
    from opendox.runtime.config import (
        ASYMMETRIC_ALGORITHMS,
        PREFIX,
        ConfigurationError,
        load_settings,
    )

    base = {PREFIX + "DATABASE_URL": "postgresql://x/y",
            PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime"}
    for name in ASYMMETRIC_ALGORITHMS:
        for spelling in (name, name.lower(), name.upper()):
            settings = load_settings({**base,
                                      PREFIX + "OIDC_ALGORITHMS": spelling})
            assert settings.oidc_algorithms == (name,), (
                f"{spelling!r} did not canonicalize to PyJWT's {name!r}")
    for refused in ("HS256", "HS512", "none", "RS255", "RS256,HS256"):
        with pytest.raises(ConfigurationError):
            load_settings({**base, PREFIX + "OIDC_ALGORITHMS": refused})
    assert "HS256" not in ASYMMETRIC_ALGORITHMS
    # An EMPTY value takes the declared default, exactly as every other
    # optional setting does — the refusal is for a value that NAMES something
    # unacceptable, not for one that names nothing.
    assert load_settings({**base, PREFIX + "OIDC_ALGORITHMS": ""}
                         ).oidc_algorithms == ("RS256",)
