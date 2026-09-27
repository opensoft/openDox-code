"""openDox's OWN reader of a checkout's HEAD. Plan 034 T012, #1144 task 4.3,
R1Q22 (a).

`serve._head_of` used to read the HEAD through openxFactory's
`doc_health.corpus.RealGit`. That was a deferred reach into a package a
standalone openDox never has, so a lone checkout's HEAD was always unknown.
openDox now reads the HEAD itself, the way `RealGit.head_sha` did, and it
still degrades to `None` rather than blocking the serve.

WHAT IT ASSERTS

1. A git checkout's HEAD is read with `doc_health` unimportable.
2. Every failure degrades to `None`: not a repository, an unborn HEAD, no
   `git` on the path, a timeout, and an injected reader that raises.
3. The injectable seam is unchanged. A `git=` reader answers instead of git.
   It needs only `head_sha(repo)`, which the suite's `FakeGit` has.
4. `serve.py` imports `doc_health` nowhere, at module level or deferred, which
   is F4.1's scan no longer listing `_head_of`.

`--noconftest` SAFE. A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from import_scan import imported_modules  # noqa: E402
from opendox import serve  # noqa: E402

SERVE = ROOT / "src" / "opendox" / "serve.py"

#: The repository-setup commands run apart from the user's own git
#: configuration, so a global hook or a signing rule cannot fail the setup.
#: The reader under test runs in the ordinary environment.
_ISOLATED = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True, env={**os.environ, **_ISOLATED})
    return done.stdout.strip()


@pytest.fixture
def outside_any_repository(tmp_path, monkeypatch):
    """`tmp_path`, with git forbidden to look above it for a repository."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    return tmp_path


@pytest.fixture
def checkout(outside_any_repository):
    repo = outside_any_repository / "checkout"
    repo.mkdir()
    _git("init", "-q", str(repo))
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git("-C", str(repo), "add", "a.txt")
    _git("-C", str(repo), "commit", "-q", "-m", "one")
    return repo


# ---------------------------------------------------------------------------
# 1. the HEAD is read, by openDox itself
# ---------------------------------------------------------------------------

def test_the_head_of_a_checkout_is_read_with_doc_health_unimportable(
        checkout, monkeypatch):
    """`sys.modules[name] = None` makes `import name` raise, so this holds in
    an environment that has openxFactory's package installed as well."""
    monkeypatch.setitem(sys.modules, "doc_health", None)
    monkeypatch.setitem(sys.modules, "doc_health.corpus", None)
    expected = _git("-C", str(checkout), "rev-parse", "HEAD")
    assert len(expected) == 40
    assert serve._head_of(checkout) == expected
    assert serve._head_of(str(checkout)) == expected


# ---------------------------------------------------------------------------
# 2. every failure degrades to None
# ---------------------------------------------------------------------------

def test_a_directory_that_is_not_a_repository_has_no_head(
        outside_any_repository):
    assert serve._head_of(outside_any_repository) is None


def test_an_unborn_head_is_no_head(outside_any_repository):
    repo = outside_any_repository / "empty"
    _git("init", "-q", str(repo))
    assert serve._head_of(repo) is None


def test_no_git_on_the_path_is_no_head(checkout, tmp_path, monkeypatch):
    empty = tmp_path / "no-binaries-here"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert serve._head_of(checkout) is None


def test_a_git_that_does_not_answer_in_time_is_no_head(checkout, monkeypatch):
    """The read is bounded, so a stuck `git` degrades rather than blocking the
    serve. The bound is `RealGit`'s own 30 seconds."""
    asked = {}

    def stuck(argv, **kwargs):
        asked.update(kwargs, argv=argv)
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(serve.subprocess, "run", stuck)
    assert serve._head_of(checkout) is None
    assert asked["timeout"] == 30
    assert asked["argv"] == ["git", "-C", str(checkout), "rev-parse", "HEAD"]


def test_an_injected_reader_that_raises_is_no_head(checkout):
    class _Raising:
        def head_sha(self, repo):
            raise RuntimeError("this reader refuses")

    assert serve._head_of(checkout, _Raising()) is None


# ---------------------------------------------------------------------------
# 3. the injectable seam is unchanged
# ---------------------------------------------------------------------------

def test_an_injected_reader_answers_instead_of_git(outside_any_repository):
    """Anything with `head_sha(repo)`, which the suite's `FakeGit` has. It is
    called with the checkout as a `Path`."""
    seen = []

    class _Fake:
        def head_sha(self, repo):
            seen.append(repo)
            return "f" * 40

    assert serve._head_of(str(outside_any_repository), _Fake()) == "f" * 40
    assert seen == [outside_any_repository]


# ---------------------------------------------------------------------------
# 4. no reach into openxFactory's package remains
# ---------------------------------------------------------------------------

def test_serve_imports_doc_health_nowhere():
    """Every import statement `serve.py` has, function-local ones included:
    `imported_modules` walks the whole syntax tree."""
    reaches = sorted((module, line) for module, line in imported_modules(SERVE)
                     if module.split(".")[0] == "doc_health")
    assert reaches == [], reaches
