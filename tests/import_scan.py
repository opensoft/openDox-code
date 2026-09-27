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
import importlib.util

#: The two calls that import a module named by a STRING, as #1144's F4.1 scan
#: reads them, each mapped to itself: `importlib.import_module` and the
#: builtin `__import__`, reached through a module (`importlib.import_module`)
#: or by a bare name. `importing_calls` adds the names an import gives them.
IMPORTING_CALLS = {"import_module": "import_module", "__import__": "__import__"}


def _called_name(expr):
    """The name a call site reaches its callable by: `f` for `f(...)` and for
    `m.f(...)`, and None for anything else."""
    if isinstance(expr, ast.Attribute):
        return expr.attr
    if isinstance(expr, ast.Name):
        return expr.id
    return None


#: What `names_imported_by` names for an importing call whose module it cannot
#: locate, because a `*` or `**` it cannot spell out stands where the name, or
#: the package a relative name needs, would be. No module is spelled this way,
#: so a caller that forbids packages refuses it as a reach it cannot read.
UNREADABLE = "<an importing call's spread arguments>"


def _positional(elements):
    """The positions a run of arguments fills, with every literal `*[...]` or
    `*(...)` spelled out, however deep, and whether every position is known.
    Past a `*` of anything else, positions are unknown."""
    known = []
    for element in elements:
        if not isinstance(element, ast.Starred):
            known.append(element)
            continue
        if not isinstance(element.value, (ast.List, ast.Tuple)):
            return known, False
        inner, complete = _positional(element.value.elts)
        known += inner
        if not complete:
            return known, False
    return known, True


def _literal_keywords(mapping):
    """A literal `{...}`'s string keys and their values, with every nested
    `**{...}` spelled out, and whether every key is known.

    An entry that cannot be spelled out, a key that is not a literal string or
    a `**` of anything else, could overwrite any key before it. So the keys
    before it are forgotten, and only a literal key after it still counts."""
    found, complete = {}, True
    for key, value in zip(mapping.keys, mapping.values):
        if key is None and isinstance(value, ast.Dict):
            inner, inner_complete = _literal_keywords(value)
            if not inner_complete:
                found.clear()
                complete = False
            found.update(inner)
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            found[key.value] = value
        else:
            found.clear()
            complete = False
    return found, complete


def _arguments(call):
    """A call's positional arguments and keywords, with every literal `*[...]`,
    `*(...)` and `**{...}` spelled out, however deep, and whether all of them
    are known. Past a `*` of anything else, positions are unknown."""
    positional, complete = _positional(call.args)
    keywords = {}
    for keyword in call.keywords:
        if keyword.arg is not None:
            keywords[keyword.arg] = keyword.value
        elif isinstance(keyword.value, ast.Dict):
            inner, inner_complete = _literal_keywords(keyword.value)
            keywords.update(inner)
            complete = complete and inner_complete
        else:
            complete = False
    return positional, keywords, complete


def importing_calls(tree):
    """`IMPORTING_CALLS`, and each name an import gives one of them:
    `from importlib import import_module as load`, or `from builtins import
    __import__ as imp`. The result maps each name to the call it is.

    A call is matched by the name it SPELLS, not by what the name is bound to
    when it runs, so a parameter or another object's attribute spelled
    `import_module` is read as the importer too. That is the stricter reading,
    the one the sweep takes wherever it cannot tell (`tests/test_reach_sweep.py`):
    it can only refuse a module, never pass one.
    """
    calls = dict(IMPORTING_CALLS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 \
                and node.module in ("importlib", "builtins"):
            for alias in node.names:
                if alias.name in IMPORTING_CALLS and alias.asname:
                    calls[alias.asname] = alias.name
    return calls


def importer_escapes(tree, calls):
    """Whether `tree` handles an importer as a VALUE, not only by calling it.

    That is any mention of a name in `calls` other than as the callable of a
    call: an assignment (`load = importlib.import_module`), a tuple, a
    container, an argument, a default value, a `:=`, a rebinding. It is also
    the name of an importer or of an alias of one, as a string outside
    documentation (`getattr(importlib, "import_module")`, `globals()["load"]`). Once the importer is a value, it can travel under any
    name by any binding, and no source read follows every one. So a module
    where this holds is read strictly, with `names_imported_by(...,
    any_call=True)`.
    """
    callables = {id(node.func) for node in ast.walk(tree)
                 if isinstance(node, ast.Call)}
    documentation = {id(node.value) for node in ast.walk(tree)
                     if isinstance(node, ast.Expr)
                     and isinstance(node.value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)) \
                and id(node) not in callables and _called_name(node) in calls:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and node.value in calls and id(node) not in documentation:
            return True
    return False


def names_imported_by(node, *, calls=None, any_call=False):
    """The absolute module names ONE syntax node imports.

    `import a.b, c` names `a.b` and `c`; `from a.b import c` names `a.b`; a
    relative import names nothing, for the reason `imported_modules` gives.

    With `calls`, a mapping from callable names to the importing call each is
    (`IMPORTING_CALLS`, or `importing_calls(tree)`), a call to one of them
    names its module too, when the name is a string LITERAL, passed by
    position or as `name=`. With `any_call`, EVERY call does, whatever it
    calls: the reading for a module where `importer_escapes` holds.

    Arguments spelled out with a literal `*[...]` or `**{...}`, however
    deep, count where they land. Where a `*` or `**` of anything else hides
    the name, or the package a relative name needs, the call names
    `UNREADABLE`. A relative name is resolved where the call itself says what it
    is relative to, a literal `package`, by keyword or as the second argument. So
    `import_module(".corpus", package="doc_health")` names
    `doc_health.corpus`. Otherwise it is relative to the calling module's own
    package, and names nothing here. That covers a `package` that is not a
    literal (`__package__`, say), and `__import__` with a nonzero literal
    `level`, whose second argument is `globals`. A name computed at run time
    cannot be read off the source.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if not isinstance(node, ast.Call) or not (calls or any_call):
        return []
    called = (calls or {}).get(_called_name(node.func))
    if called is None and not any_call:
        return []
    args, keywords, complete = _arguments(node)
    name = args[0] if args else keywords.get("name")
    if name is None and not complete:
        return [UNREADABLE]
    if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
        return []
    if called == "__import__":
        level = args[4] if len(args) > 4 else keywords.get("level")
        if isinstance(level, ast.Constant) and level.value:
            return []
        return [name.value]
    if not name.value.startswith("."):
        return [name.value]
    package = args[1] if len(args) > 1 else keywords.get("package")
    if package is None and not complete:
        return [UNREADABLE]
    if not (isinstance(package, ast.Constant) and isinstance(package.value, str)):
        return []
    try:
        return [importlib.util.resolve_name(name.value, package.value)]
    except ImportError:
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
