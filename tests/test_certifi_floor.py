"""The `runtime` extra's `certifi` floor, held at the first fixed release.

WHY THIS MODULE EXISTS (0.1.1; RULED openxFactory#656 comment 6943000552, the
addendum to comment 6936600205). The dependency lock moved `certifi` to
2026.10.23 for GHSA-6q48-6c7w-9gw2, a critical advisory (affected
">= 2019.03.09, < 2026.10.18"). But the lock reaches only the image and CI,
which install with `-c constraints-cpython312-linux.txt`. The package's own
metadata named no `certifi` at all: it arrives through `httpx` and its
`httpcore`, which require it with no version. So `pip install -U` over a 0.1.0
environment kept the `certifi` that environment held, and the release
workflow's checks could not see it, because they install fresh and under the
lock. The `runtime` extra now names `certifi>=2026.10.18`.

WHAT IS HELD, and what each case would catch:
  * the floor is there, once, with no marker, and it admits no release the
    advisory names: removed, made unversioned, or lowered below
    2026.10.18 (including to a pre-release of it), the case fails; and it is
    a floor, not a ceiling or a pin, so a later fixed release satisfies it;
  * the extras that reach `certifi` reach it through `opendox[runtime]`, so the
    one floor covers `local` and `test`, and the base install does not reach
    it;
  * the lock's own pin satisfies the floor, so the lock and the metadata
    cannot disagree;
  * the INSTALLED metadata carries the same floor under `extra == "runtime"`:
    what pip reads, not only what the file says.

Raising the floor is not a failure: a later release that is still fixed is
admitted. Version ordering is `packaging`'s, which pip uses and which `pytest`
itself requires, so it is present wherever this suite runs.
"""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "constraints-cpython312-linux.txt"

#: The advisory, and its first fixed release, as the advisory states it
#: (GitHub's advisory database and certifi's own advisory both name it).
ADVISORY = "GHSA-6q48-6c7w-9gw2"
FIRST_FIXED = Version("2026.10.18")

#: Releases the advisory covers, which the floor must refuse: the range's own
#: first release, the version 0.1.0's lock pinned, and the versions that sort
#: just below the first fixed release, a pre-release of it included.
AFFECTED = ("2019.3.9", "2026.7.22", "2026.10.17", "2026.10.17.99999999",
            "2026.10.18rc1", "2026.10.18.dev0")

#: A release far past the first fixed one, which a floor admits and a ceiling
#: or a pin does not.
LATER = Version("2099.1.1")


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def _certifi(requirements: list[str]) -> list[Requirement]:
    return [r for r in map(Requirement, requirements)
            if canonicalize_name(r.name) == "certifi"]


def _refused_and_admitted(requirement: Requirement, where: str) -> None:
    admitted = [v for v in AFFECTED
                if requirement.specifier.contains(v, prereleases=True)]
    assert not admitted, (
        f"{where}'s `{requirement}` admits {admitted}, which {ADVISORY} covers "
        f"(affected below {FIRST_FIXED}). The floor exists so that an upgrade "
        f"from 0.1.0 cannot keep an affected `certifi`; it is the first fixed "
        "release, and only a higher one may replace it")
    assert requirement.specifier.contains(LATER), (
        f"{where}'s `{requirement}` refuses {LATER}: that is a ceiling or a "
        "pin, and this requirement is a floor, which a later fixed release "
        "must always satisfy")


def test_the_runtime_extra_names_a_certifi_floor_at_the_first_fixed_release(
) -> None:
    runtime = _project()["optional-dependencies"]["runtime"]
    found = _certifi(runtime)
    assert len(found) == 1, (
        f"the `runtime` extra names `certifi` {len(found)} time(s): {runtime}. "
        f"It names it ONCE, `certifi>={FIRST_FIXED}`, because `httpx` and "
        "`httpcore` require it with no version and an upgrade would otherwise "
        f"keep a `certifi` {ADVISORY} covers")
    (floor,) = found
    assert floor.marker is None and not floor.extras and floor.url is None, (
        f"`{floor}` carries a marker, an extra or a URL; the floor applies to "
        "every install of the extra, on every platform")
    _refused_and_admitted(floor, "pyproject.toml's runtime extra")


def test_the_extras_that_reach_certifi_reach_the_floor() -> None:
    project = _project()
    extras = project["optional-dependencies"]
    for name in ("local", "test"):
        assert "opendox[runtime]" in extras[name], (
            f"the `{name}` extra no longer names `opendox[runtime]`, so the "
            "runtime extra's `certifi` floor no longer covers it")
        assert not _certifi(extras[name]), (
            f"the `{name}` extra names `certifi` itself; the floor is declared "
            "once, in `runtime`, which this extra already carries")
    assert not _certifi(project.get("dependencies", [])), (
        "the base dependencies name `certifi`, which nothing in the base "
        "install requires")


def test_the_lock_pins_a_certifi_the_floor_admits() -> None:
    pins = re.findall(r"(?m)^certifi==(\S+)$",
                      LOCK.read_text(encoding="utf-8"))
    assert len(pins) == 1, f"the lock pins `certifi` {len(pins)} time(s)"
    floors = _certifi(_project()["optional-dependencies"]["runtime"])
    assert floors, "the runtime extra names no `certifi` floor for the lock to meet"
    assert all(floor.specifier.contains(pins[0]) for floor in floors), (
        f"the lock pins certifi=={pins[0]}, and the runtime extra requires "
        f"{[str(f) for f in floors]}: every install made under the lock would "
        "fail to resolve")


def test_the_installed_metadata_carries_the_floor() -> None:
    """What pip reads: the installed distribution's `Requires-Dist`, as the
    required job's editable install of `.[runtime,test]` generates it from
    this file."""
    requires = importlib.metadata.requires("opendox") or []
    found = [r for r in _certifi(requires)
             if r.marker is not None and r.marker.evaluate({"extra": "runtime"})]
    assert len(found) == 1, (
        f"the installed opendox requires `certifi` under the runtime extra "
        f"{len(found)} time(s): {[r for r in requires if 'certifi' in r]}. "
        "Reinstall the package if pyproject.toml changed after the install")
    _refused_and_admitted(found[0], "the installed metadata")
    unconditional = [str(r) for r in _certifi(requires) if r.marker is None]
    assert not unconditional, (
        f"the installed metadata requires {unconditional} for the base install, "
        "which nothing in the base install needs")
