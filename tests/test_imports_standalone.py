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
2. It imports EVERY module the package's `.py` files define, in sorted order,
   so a package precedes its own modules. The list is GENERATED from the
   files, so a module added later is covered with no edit here, and a
   subpackage whose `__init__` fails is imported, and reported, rather than
   skipped. `pkgutil.walk_packages` would skip it: it calls `onerror` and
   never visits the children.
3. It fails naming the FIRST module that did not import, and says what it
   needed. A sibling is the finding this test exists for. Any other failure is
   a finding too, as F2.1 treats it. A missing third-party package means the
   environment lacks a declared extra: the sweep runs where every extra the
   package declares is installed, as F2.1's `pip install ".[runtime,test]"`
   does.
4. Once every module imports, it holds the sweep COMPLETE: `pkgutil`'s own
   walk must visit exactly the modules the files define, so a list that
   silently found nothing, or a walk that disagrees with it, fails.

`--noconftest` safe, and also safe with the root conftest in play, which is
how F2.1 runs it. A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import opendox

#: The packages openDox must never need, spelled as F2.1 spells them.
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: The package directory this test session imports, and the directory above
#: it, which the fresh interpreter puts first on its path. Both processes then
#: import the SAME `opendox`, the editable checkout or the installed copy.
PACKAGE_DIR = Path(opendox.__file__).resolve().parent
IMPORT_ROOT = PACKAGE_DIR.parent

_SWEEP = """
import importlib, importlib.util, json, pkgutil, sys
sys.path.insert(0, {root!r})
siblings = {siblings!r}
present = [name for name in siblings if importlib.util.find_spec(name) is not None]
if present:
    print(json.dumps({{"present": present}}))
    raise SystemExit(0)
import opendox
failed = []
for name in {modules!r}:
    try:
        importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 - every failure is a finding here
        failed.append({{"module": name, "type": type(exc).__name__,
                        "message": str(exc),
                        "missing": getattr(exc, "name", None)}})
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


def _names_a_sibling(missing: str | None) -> bool:
    return bool(missing) and any(missing == s or missing.startswith(s + ".")
                                 for s in SIBLINGS)


def test_every_module_imports_with_no_sibling() -> None:
    result = _run_sweep()
    assert result["present"] == [], (
        f"a sibling is importable here: {result['present']}. This sweep "
        "proves that openDox imports with NO sibling installed, so it must "
        "run where none is, as F2.1 asserts before it runs")
    failed = result["failed"]
    if failed:
        first = failed[0]
        if _names_a_sibling(first["missing"]):
            why = f"it still needs the sibling {first['missing']!r}"
        elif first["type"] in ("ModuleNotFoundError", "ImportError"):
            why = (f"it needs {first['missing'] or 'a module'!r}, which is not "
                   "a sibling. This environment lacks a package openDox "
                   "declares: run the sweep where every extra is installed, as "
                   "F2.1's `pip install \".[runtime,test]\"` does")
        else:
            why = "it raised while importing, which is a defect, not a reach"
        others = ", ".join(f["module"] for f in failed[1:]) or "none"
        raise AssertionError(
            f"{first['module']} does not import with no sibling installed: "
            f"{why}.\n  {first['type']}: {first['message']}\n"
            f"  Every other module that failed: {others}")
    walked = set(result["walked"])
    on_disk = _modules_on_disk()
    assert on_disk, "the package's files define no module: the sweep swept nothing"
    assert walked == on_disk, (
        "pkgutil's walk did not visit exactly the modules the package's files "
        f"define. Never walked: {sorted(on_disk - walked)}; walked but not on "
        f"disk: {sorted(walked - on_disk)}")
