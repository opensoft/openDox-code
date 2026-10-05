"""T100 follow-on 2 (plan 034): openDox-code#86's deferred items in
`doxbench_trust`, each as #86's "Deferred to a follow-on (not release 1)"
names its fix (the holder's ruling, openxFactory#656 comment 5992038800;
Brett Heap's word, comment 6000582654, "openDox-code follow-ons first").

- D1 (Copilot at openDox-code#86, r4182645599): a bytecode cache directory
  whose listing fails for any reason but its absence refuses the command
  as unreadable, FAIL-CLOSED, once nothing it names lies inside the
  repository.
- D6 (r4182645836): a cache directory is read as it is listed
  (`os.scandir`), a step of the judgment's budget spent before each entry
  is kept, and never sorted, so a directory of any size costs no more than
  the budget.

Each case marked "red at 389e5a4a" fails there for its item's own reason;
the others pin a rule a mutant of the fix would break.
"""

from __future__ import annotations

import errno
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from opendox import doxbench_trust as trust_mod

UNREADABLE = trust_mod.REASON_UNREADABLE_COMMAND
IN_REPOSITORY = trust_mod.REASON_IN_REPOSITORY

#: Another interpreter's cache tag: the next CPython's, as Copilot's case
#: has it (openDox on 3.12, the broker on 3.13).
OTHER_TAG = f"cpython-{sys.version_info.major}{sys.version_info.minor + 1}"


class _World:
    """One case's served repository, and a directory outside it holding the
    broker's module, `broker.py`, which a command imports by `-m` from
    there."""

    def __init__(self, tmp_path: Path) -> None:
        self.repo = tmp_path / "r"
        self.repo.mkdir()
        self.elsewhere = tmp_path / "elsewhere"
        self.elsewhere.mkdir()
        self.source = self.elsewhere / "broker.py"
        self.source.write_text("", encoding="utf-8")
        self.pycache = self.elsewhere / "__pycache__"
        self.compiled = self.repo / "broker.pyc"
        self.compiled.write_bytes(b"")

    def command(self, module: str = "-m", *after: str) -> list[str]:
        """`python -m broker`, started in the module's directory; `-mbroker`
        where `module` is that cluster."""
        named = [module] if module != "-m" else ["-m", "broker"]
        return ["env", "-C", str(self.elsewhere), sys.executable, *named,
                *after]

    def refused(self, argv: list[str]) -> str | None:
        return trust_mod.broker_command_refused(argv, root=self.repo)

    def own_cache_name(self, optimization="") -> str:
        return Path(importlib.util.cache_from_source(
            str(self.source), optimization=optimization)).name


@pytest.fixture
def world(tmp_path):
    return _World(tmp_path)


@pytest.fixture
def unlistable(world):
    """The broker's `__pycache__`, searchable but not listable, as only the
    operator can make it; listable again after the case."""
    world.pycache.mkdir()
    yield world.pycache
    os.chmod(world.pycache, 0o700)


def _unlist(pycache: Path) -> None:
    os.chmod(pycache, 0o300)
    with pytest.raises(OSError):
        os.listdir(pycache)


class _Entry:
    def __init__(self, name: str) -> None:
        self.name = name


class _Listing:
    """What `os.scandir` gives for one directory, as a case makes it: the
    entries `names` yields, drawn one at a time, the count kept; past
    `fails_after` of them, the listing fails as an I/O error does."""

    def __init__(self, names, fails_after: int | None = None) -> None:
        self.names = names
        self.fails_after = fails_after
        self.drawn = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def close(self) -> None:
        return None

    def __iter__(self):
        for name in self.names:
            if self.fails_after is not None and self.drawn == self.fails_after:
                raise OSError(errno.EIO, "Input/output error")
            self.drawn += 1
            yield _Entry(name)


def _listing_of(monkeypatch, directory: Path, listing: _Listing) -> list:
    """`os.scandir(directory)` gives `listing`; every other directory lists
    as it is. Returns the directories `os.listdir` was asked for."""
    real_scandir, real_listdir = os.scandir, os.listdir
    listed: list[str] = []

    def scandir(path="."):
        if os.fspath(path) == str(directory):
            return listing
        return real_scandir(path)

    def listdir(path="."):
        listed.append(os.fspath(path))
        return real_listdir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "listdir", listdir)
    return listed


# ---------------------------------------------------------------------------
# D1: a cache directory that cannot be listed is refused as unreadable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["-m", "-mbroker"])
@pytest.mark.parametrize("holding", ["another-tags-cache-linked-in",
                                     "nothing-to-see"])
def test_D1_a_cache_directory_that_cannot_be_listed_is_refused_as_unreadable(
        world, unlistable, module, holding):
    """Red at 389e5a4a. r4182645599: a `__pycache__` beside the module that
    the operator made searchable but not listable. Copilot's case holds
    another interpreter's cache (the broker's Python, not this one) linked
    into the repository, which only a listing finds; but whatever it holds,
    what it holds cannot be judged, so the command is refused as
    unreadable, FAIL-CLOSED, and `in_repository_argv` returns the member
    that names the module."""
    if holding == "another-tags-cache-linked-in":
        (unlistable / f"broker.{OTHER_TAG}.pyc").symlink_to(world.compiled)
    _unlist(unlistable)
    argv = world.command(module)
    assert world.refused(argv) == UNREADABLE
    assert trust_mod.in_repository_argv(argv, root=world.repo) == (
        "broker" if module == "-m" else module)


def test_D1_a_packages_cache_directory_that_cannot_be_listed_is_refused(
        world):
    """Red at 389e5a4a. The same of the cache directory a package of the
    module's name would have, where its `__init__` and its `__main__` are
    cached (`broker/__pycache__`)."""
    package = world.elsewhere / "broker"
    package.mkdir()
    pycache = package / "__pycache__"
    pycache.mkdir()
    try:
        _unlist(pycache)
        assert world.refused(world.command()) == UNREADABLE
    finally:
        os.chmod(pycache, 0o700)


def test_D1_a_cache_named_inside_keeps_its_name(world, unlistable):
    """Pin. Asked only once nothing the command names lies inside the
    repository, as xargs is (5988818366), so each keeps its name: this
    interpreter's own cache name linked into the repository, which is
    judged by name, and a member after the module naming a file inside,
    are each refused as in the repository."""
    (unlistable / world.own_cache_name()).symlink_to(world.compiled)
    _unlist(unlistable)
    assert world.refused(world.command()) == IN_REPOSITORY
    os.chmod(unlistable, 0o700)
    (unlistable / world.own_cache_name()).unlink()
    _unlist(unlistable)
    inside = str(world.repo / "settings")
    argv = world.command("-m", inside)
    assert world.refused(argv) == IN_REPOSITORY
    assert trust_mod.in_repository_argv(argv, root=world.repo) == inside


@pytest.mark.parametrize("absence", ["no-directory", "a-file-in-its-place",
                                     "a-name-holding-a-nul"])
def test_D1_a_cache_directory_that_is_not_there_is_no_refusal(
        world, absence):
    """Pin. Only a listing that fails for its directory's absence holds no
    cache: no `__pycache__` (`FileNotFoundError`), a file in its place
    (`NotADirectoryError`), and a module name holding a NUL, which names
    nothing a file system can hold and is judged as written (r4179077018)."""
    argv = world.command()
    if absence == "a-file-in-its-place":
        world.pycache.write_text("", encoding="utf-8")
    elif absence == "a-name-holding-a-nul":
        argv = world.command("-mbro\x00ker")
    assert world.refused(argv) is None
    assert trust_mod.in_repository_argv(argv, root=world.repo) is None


def test_D1_a_listing_that_fails_part_way_is_refused_as_unreadable(
        world, monkeypatch):
    """Red at 389e5a4a. A listing that fails after it began (an I/O
    error) has not shown what the directory holds: refused as unreadable."""
    world.pycache.mkdir()
    listing = _Listing([f"broker.{OTHER_TAG}.pyc", "other.pyc"],
                       fails_after=1)
    _listing_of(monkeypatch, world.pycache, listing)
    assert world.refused(world.command()) == UNREADABLE
    assert listing.drawn == 1


# ---------------------------------------------------------------------------
# D6: a cache directory is charged as it is listed
# ---------------------------------------------------------------------------


def test_D6_a_cache_directory_is_charged_as_it_is_listed(world, monkeypatch):
    """Red at 389e5a4a. r4182645836: a cache directory of a million
    entries. It is read as it is listed, one step of the command's budget
    spent before each entry is kept, so the judgment stops at the budget,
    refused as unreadable, having drawn no more entries than the budget
    holds, and in under a second; it is never listed whole
    (`os.listdir`) nor sorted."""
    world.pycache.mkdir()
    listing = _Listing(f"broker.{index}.pyc" for index in range(1_000_000))
    listed = _listing_of(monkeypatch, world.pycache, listing)
    argv = world.command()
    started = time.monotonic()
    assert world.refused(argv) == UNREADABLE
    assert time.monotonic() - started < 1
    assert 0 < listing.drawn <= trust_mod._WORK_PER_MEMBER * len(argv)
    assert str(world.pycache) not in listed


def test_D6_the_listing_and_each_entry_are_a_step_each(world, unlistable):
    """Pin. The listing costs a step, and each entry one more, kept or not;
    what is kept is this interpreter's cache name at every optimization
    level, and every `<stem>.*.pyc` already there, whatever its tag. A
    directory that cannot be listed costs its step and is reported; one
    that is not there costs its step and is not."""
    kept = [f"broker.{OTHER_TAG}.pyc", f"broker.{OTHER_TAG}.opt-1.pyc",
            "broker.pyc"]
    passed = ["brokers.cpython-399.pyc", "broker.txt", "other.pyc",
              f"broker.{OTHER_TAG}.pyc.tmp"]
    for name in kept + passed:
        (unlistable / name).write_bytes(b"")
    own = [str(unlistable / world.own_cache_name(level))
           for level in ("", 1, 2)]

    def judged(source: Path):
        unlisted: list[str] = []
        token = trust_mod._STEPS_LEFT.set([100])
        try:
            caches = trust_mod._bytecode_caches(str(source),
                                                unlisted=unlisted)
            spent = 100 - trust_mod._STEPS_LEFT.get()[0]
        finally:
            trust_mod._STEPS_LEFT.reset(token)
        return caches, spent, unlisted

    caches, spent, unlisted = judged(world.source)
    assert spent == 1 + len(kept) + len(passed)
    assert sorted(caches) == sorted(
        own + [str(unlistable / name) for name in kept])
    assert unlisted == []
    _unlist(unlistable)
    caches, spent, unlisted = judged(world.source)
    assert (sorted(caches), spent, unlisted) == (
        sorted(own), 1, [str(unlistable)])
    caches, spent, unlisted = judged(world.elsewhere / "absent" / "broker.py")
    assert (spent, unlisted) == (1, [])
