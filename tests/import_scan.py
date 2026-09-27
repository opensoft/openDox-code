"""Shared AST scanners for the tests that police an import DIRECTION.

PARSED, NOT GREPPED, and the difference is load-bearing wherever these are
used. Modules in this corpus legitimately NAME other packages in prose — a
docstring recording that two readers must agree, a comment recording why an
import is lazy, a finding whose SUBJECT is another module. A substring grep
calls all of those violations, and the pressure to make it green is pressure to
delete true documentation. So the scan reads import STATEMENTS out of the syntax
tree; a name inside a comment, a docstring or a string literal is not an import
and is not flagged.

WHY THIS MODULE EXISTS RATHER THAN A SECOND COPY. `tests/doc-health/
test_import_direction.py` defined `_imported_modules` and
`_names_a_forbidden_package` for `split-opendox-two-layer-product` § 2.1;
§ 2.2/2.2a needs the same two scanners for a different direction. Hand-copying
an AST scanner is exactly the co-authoritative-constant pattern this repository
repairs everywhere else — and the copy that drifts is the one that stops
catching things, silently, while still passing. `tests/hermeticity.py` and
`tests/hermetic_unittest.py` are the precedent for a helper module at the
`tests/` root; both consumers reach it by inserting `TESTS_ROOT` on `sys.path`,
which their conftest or their own header already does.

ONE NODE READER, FOR THE CALLERS THAT WALK A TREE THEIR OWN WAY. Plan 034
T032's sweep (`tests/test_reach_sweep.py`) has to know WHEN each import runs, so
it cannot take `imported_modules`' flat walk. It reads each node with
`names_imported_by` instead, which is what `imported_modules` reads with too, so
the sweep is not a third copy of the extraction.

BOTH SPELLINGS ARE ALWAYS THE CALLER'S JOB. `scripts/__init__.py` exists, so
every package under `scripts/` is importable BOTH as a top-level name and as
`scripts.<name>`. A one-spelling forbidden list is a hole, so callers pass both
— see each caller's own constant.
"""

from __future__ import annotations

import ast

#: The two calls that import a module named by a STRING, as #1144's F4.1 scan
#: reads them, each mapped to itself: `importlib.import_module` and the
#: builtin `__import__`, reached through a module (`importlib.import_module`)
#: or by a bare name. `importing_calls` adds the other names a module gives them.
IMPORTING_CALLS = {"import_module": "import_module", "__import__": "__import__"}


def _called_name(expr):
    """The name a call site reaches its callable by: `f` for `f(...)` and for
    `m.f(...)`, and None for anything else."""
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Name):
        return expr.id
    return None


def importing_calls(tree):
    """`IMPORTING_CALLS`, and every other name `tree` gives one of them.

    A module can call the two under a name of its own: `from importlib import
    import_module as load`, `from builtins import __import__ as imp`, or an
    assignment, `load = importlib.import_module`, followed as far as it chains
    (`again = load`). The result maps each such name to the call it is. A
    callable reached any other way, through `getattr`, a `functools.partial` or
    a parameter, cannot be read off the source.
    """
    calls = dict(IMPORTING_CALLS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 \
                and node.module in ("importlib", "builtins"):
            for alias in node.names:
                if alias.name in IMPORTING_CALLS and alias.asname:
                    calls[alias.asname] = alias.name
    assignments = [node for node in ast.walk(tree)
                   if isinstance(node, (ast.Assign, ast.AnnAssign))
                   and node.value is not None]
    grew = True
    while grew:
        grew = False
        for node in assignments:
            call = calls.get(_called_name(node.value))
            if call is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in calls:
                    calls[target.id] = call
                    grew = True
    return calls


def names_imported_by(node, *, calls=None):
    """The absolute module names ONE syntax node imports.

    `import a.b, c` names `a.b` and `c`; `from a.b import c` names `a.b`; a
    relative import names nothing, for the reason `imported_modules` gives.

    With `calls`, a mapping from callable names to the importing call each is
    (`IMPORTING_CALLS`, or `importing_calls(tree)` for one module's own names),
    a call names its module too, when the name is a string LITERAL, passed by
    position or as `name=`. A literal that starts with a dot is relative, and
    so is `__import__` with a nonzero literal `level`. A name computed at run
    time cannot be read off the source.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if not calls or not isinstance(node, ast.Call):
        return []
    called = calls.get(_called_name(node.func))
    if called is None:
        return []
    keywords = {keyword.arg: keyword.value for keyword in node.keywords
                if keyword.arg is not None}
    name = node.args[0] if node.args else keywords.get("name")
    level = node.args[4] if len(node.args) > 4 else keywords.get("level")
    if called == "__import__" and isinstance(level, ast.Constant) and level.value:
        return []
    if isinstance(name, ast.Constant) and isinstance(name.value, str) \
            and not name.value.startswith("."):
        return [name.value]
    return []


def imported_modules(path):
    """Every module name a file IMPORTS, with the line it does it on.

    Walks the whole tree, so a lazy function-local import is reported exactly
    like a module-level one — a lazy import is still an import, and it is how
    a cycle survives review for a long time.

    Relative imports (`from .corpus import ...`, `level > 0`) are confined to
    their own package and can never name another top-level package, so they are
    skipped rather than resolved.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        for name in names_imported_by(node):
            yield name, node.lineno


def names_a_forbidden_package(module: str, forbidden) -> bool:
    """True when `module` IS one of `forbidden` or sits underneath one."""
    return any(module == f or module.startswith(f + ".") for f in forbidden)


def bound_names(source_path, packages):
    """What each import of one of `packages` BINDS, as (line, bound-name) pairs.

    A direction test sometimes has to allow a package to be imported at all
    while forbidding reaching past its declared public names. `from pkg import
    X` binds `X`; `from pkg.sub import X` binds nothing the package declared, so
    it is reported as the empty string, which no allowlist contains; `import
    pkg` binds the package itself and is reported as `"*"` for the same reason —
    it hands the caller every attribute the package has.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"),
                     filename=str(source_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if names_a_forbidden_package(alias.name, packages):
                    yield node.lineno, "*"
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            if node.module in packages:
                for alias in node.names:
                    yield node.lineno, alias.name
            elif names_a_forbidden_package(node.module, packages):
                # a SUBMODULE of the package: nothing it binds is one of the
                # package's own declared public names
                yield node.lineno, ""


def string_literals(path):
    """Every string literal in a file EXCEPT its documentation, as (value, line).

    Docstrings and bare string expression statements are excluded on purpose: a
    module that may not USE a word must still be free to explain why, and a
    vocabulary scan that flagged its own explanation would be an argument for
    deleting the explanation. Comments never reach the syntax tree at all.

    f-strings contribute only their literal segments; an interpolated
    expression is not a literal.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    documentation = {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in documentation:
            yield node.value, node.lineno
