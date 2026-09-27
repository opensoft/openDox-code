"""Every module of `opendox` imports with no sibling installed — #1144 task 2.4.

Plan 034 T030, which lands with T011 because it fails until task 2.1 lands.
The ratified text: *"Add a test in openDox-code's own suite that imports EVERY
module of the package in a checkout with no sibling installed, failing with the
name of the first module that still needs one."* Group 2's falsifier (F2.1)
runs the same sweep by hand and then runs this test by name, *"so the suite
keeps the sweep after the arc"*.

WHAT IT DOES, in a FRESH INTERPRETER, so nothing this test session imported or
stood in for can answer for the package:

1. It asserts that the four siblings are ABSENT, before anything is imported.
   They are the consumer, the publisher's two packages, and the publisher's
   corpus adapter. A sweep run beside an installed sibling proves nothing.
2. It imports the package itself, then EVERY module the package's `.py` files
   define, in sorted order, so a package precedes its own modules. The list is
   GENERATED from the files, so a module added later is covered with no edit
   here. A package whose `__init__` fails, the root included, is imported and
   reported rather than skipped. `pkgutil.walk_packages` would skip it: it
   calls `onerror` and never visits the children. This process only FINDS the
   package, so its `__init__` runs in the sweep alone.
3. It fails naming the FIRST module that did not import, and says what it
   needed. A sibling is the finding this test exists for. Any other failure is
   a finding too, as F2.1 treats it, and is told apart. A failure inside
   openDox's own package is a defect of openDox. A missing third-party package
   means the environment lacks a declared extra: the sweep runs where every
   extra the package declares is installed, as F2.1's
   `pip install ".[runtime,test]"` does. A third-party module that lacks a
   name openDox imports is the wrong version of it.
4. Once every module imports, it holds the sweep COMPLETE: `pkgutil`'s own
   walk must visit exactly the modules the files define, so a list that
   silently found nothing, or a walk that disagrees with it, fails.

`--noconftest` safe, and also safe with the root conftest in play, which is
how F2.1 runs it. A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

#: The packages openDox must never need, spelled as F2.1 spells them.
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: The package directory this test session would import, and the directory
#: above it, which the fresh interpreter puts first on its path. Both processes
#: then see the SAME `opendox`, the editable checkout or the installed copy.
#: It is FOUND, not imported, so the package's own `__init__` runs only in the
#: sweep, where a failure of it is recorded like any other module's.
PACKAGE_DIR = Path(importlib.util.find_spec("opendox")
                   .submodule_search_locations[0]).resolve()
IMPORT_ROOT = PACKAGE_DIR.parent

_SWEEP = """
import importlib, importlib.util, json, pkgutil, sys
sys.path.insert(0, {root!r})
siblings = {siblings!r}
present = [name for name in siblings if importlib.util.find_spec(name) is not None]
if present:
    print(json.dumps({{"present": present}}))
    raise SystemExit(0)
failed = []
for name in ["opendox", *{modules!r}]:
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - every failure is a finding here
        failed.append({{"module": name, "type": type(exc).__name__,
                        "message": str(exc),
                        "missing": getattr(exc, "name", None)}})
walked = []
if not failed or failed[0]["module"] != "opendox":
    opendox = sys.modules["opendox"]
    walked = [info.name for info in pkgutil.walk_packages(
        opendox.__path__, "opendox.", onerror=lambda name: None)]
print(json.dumps({{"present": [], "walked": walked, "failed": failed}}))
"""


def _run_sweep() -> dict:
    program = textwrap.dedent(_SWEEP.format(
        root=str(IMPORT_ROOT), siblings=SIBLINGS,
        modules=sorted(_modules_on_disk())))
    done = subprocess.run([sys.executable, "-c", program],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, (
        f"the sweep's interpreter itself failed:\n{done.stderr}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def _modules_on_disk() -> set[str]:
    """Every module the package directory holds, derived from its files."""
    names = set()
    for path in PACKAGE_DIR.rglob("*.py"):
        parts = path.relative_to(IMPORT_ROOT).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if len(parts) > 1:           # the package itself is not a walked module
            names.add(".".join(parts))
    return names


def _within(name: str | None, packages) -> bool:
    return bool(name) and any(name == p or name.startswith(p + ".")
                              for p in packages)


def _why(failure: dict) -> str:
    """What a failed import says, told apart in the order that matters. A
    sibling is the finding this test exists for. A failure inside openDox's
    own package is a defect of openDox. A third-party module that is missing,
    or lacks a name, is the environment's, not openDox's."""
    missing = failure["missing"]
    if _within(missing, SIBLINGS):
        return f"it still needs the sibling {missing!r}"
    if _within(missing, ("opendox",)):
        return (f"it imports {missing!r}, a module of openDox's own that does "
                "not import, which is a defect in openDox, not a reach")
    if failure["type"] == "ModuleNotFoundError" and missing:
        return (f"it needs {missing!r}, which is not a sibling. This "
                "environment lacks a package openDox declares: run the sweep "
                "where every extra is installed, as F2.1's "
                "`pip install \".[runtime,test]\"` does")
    if failure["type"] == "ImportError" and missing:
        return (f"the installed {missing!r} lacks what openDox imports from "
                "it, so this environment's version is not the one openDox "
                "declares")
    return "it raised while importing, which is a defect in openDox, not a reach"


def test_every_module_imports_with_no_sibling() -> None:
    result = _run_sweep()
    assert result["present"] == [], (
        f"a sibling is importable here: {result['present']}. This sweep "
        "proves that openDox imports with NO sibling installed, so it must "
        "run where none is, as F2.1 asserts before it runs")
    failed = result["failed"]
    if failed:
        first = failed[0]
        others = ", ".join(f["module"] for f in failed[1:]) or "none"
        raise AssertionError(
            f"{first['module']} does not import with no sibling installed: "
            f"{_why(first)}.\n  {first['type']}: {first['message']}\n"
            f"  Every other module that failed: {others}")
    walked = set(result["walked"])
    on_disk = _modules_on_disk()
    assert on_disk, "the package's files define no module: the sweep swept nothing"
    assert walked == on_disk, (
        "pkgutil's walk did not visit exactly the modules the package's files "
        f"define. Never walked: {sorted(on_disk - walked)}; walked but not on "
        f"disk: {sorted(walked - on_disk)}")
