"""openDox's OWN line rule and HEAD read, `opendox.lines` (plan 038 T072; the
OpenSpec change `realize-doc-health-direction-arc`, design.md § 3, tasks.md
2.1).

WHAT IT ASSERTS

1. ONLY CR, LF AND CRLF END A ROW. Each splits `a<ending>b` into two rows.
   CRLF is ONE ending, never a CR row and then an LF row, and LF then CR is
   two endings. Every other separator `str.splitlines()` breaks on is named
   here: VT (`\\v`), FF (`\\f`), FS (`\\x1c`), GS (`\\x1d`), RS (`\\x1e`), NEL
   (`\\x85`), U+2028 and U+2029. Each leaves `a<sep>b` ONE row. The named
   list is checked against what `str.splitlines()` really breaks on, over
   every code point, and one text holding every code point but CR and LF is
   one row.
2. THE ROUND TRIP. `join_rows(split_keepends(t)) == t` over a corpus of row
   shapes: CR, LF, CRLF, no ending, a final ending and none, mixed endings,
   empty lines and the exotic separators. The round trip alone cannot tell
   this rule from `str.splitlines(keepends=True)`, which round-trips the same
   texts while splitting on the exotic separators. A test below shows that,
   so it is 1, not 2, that fails a `splitlines` rule (design.md § 3).
3. THE REAL-LINE RULE, as a property. Every text of up to six characters
   drawn from {`a`, CR, LF, FF, U+2028} reads as an independent
   character-by-character reading of the rule reads it, round-trips, and has
   the rows' shape: a body holds no CR or LF, an ending is CR, LF, CRLF or
   empty, only the last row may have none, and empty text is no rows.
4. `head_sha` ON A REAL TEMPORARY REPOSITORY. It reads HEAD: a new commit
   moves it, and a detached HEAD is read too. It answers `None` exactly where
   `RealGit.head_sha` does: not a repository, an unborn HEAD, a path that is
   not there, no `git`, a timeout, a non-zero exit, an empty answer. Its
   command and its bound are `RealGit`'s, and any other error propagates, as
   it does there.
5. PARITY WITH `serve._head_of`, openDox's other reader of the same read
   (holder ruling, openxFactory#656 comment 6023517122). The two agree on a
   repository, an unborn HEAD and a non-repository. This is the drift guard
   while two copies exist.
6. IMPORT WEIGHT. `import opendox.lines` in a fresh interpreter, with
   openXdox and openxFactory's packages blocked, loads the standard library
   and no other module of openDox.

`--noconftest` SAFE. A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from opendox import lines, serve
from opendox.lines import head_sha, join_rows, split_keepends

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

#: The three real line endings.
REAL_ENDINGS = ("\r", "\n", "\r\n")

#: Every separator `str.splitlines()` breaks on besides CR and LF, by name.
#: None of them ends a row here.
EXOTIC = {
    "\v": "VT",
    "\f": "FF",
    "\x1c": "FS",
    "\x1d": "GS",
    "\x1e": "RS",
    "\x85": "NEL",
    " ": "LINE SEPARATOR",
    " ": "PARAGRAPH SEPARATOR",
}

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


def _head(repo: Path) -> str:
    """HEAD as git itself prints it: the expected answer."""
    return _git("-C", str(repo), "rev-parse", "HEAD")


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n", encoding="utf-8")
    _git("-C", str(repo), "add", name)
    _git("-C", str(repo), "commit", "-q", "-m", name)
    return _head(repo)


@pytest.fixture
def outside_any_repository(tmp_path, monkeypatch):
    """`tmp_path`, with git forbidden to look above it for a repository."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    return tmp_path


def _new_checkout(base: Path) -> Path:
    """A repository under `base` with one commit."""
    repo = base / "checkout"
    repo.mkdir()
    _git("init", "-q", str(repo))
    _commit(repo, "a.txt")
    return repo


def _new_unborn(base: Path) -> Path:
    """A repository under `base` with no commit, so its HEAD is unborn."""
    repo = base / "unborn"
    _git("init", "-q", str(repo))
    return repo


@pytest.fixture
def checkout(outside_any_repository):
    return _new_checkout(outside_any_repository)


@pytest.fixture
def unborn(outside_any_repository):
    return _new_unborn(outside_any_repository)


# ---------------------------------------------------------------------------
# 1. only CR, LF and CRLF end a row
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ending", REAL_ENDINGS, ids=["CR", "LF", "CRLF"])
def test_each_real_line_ending_splits_a_row(ending: str) -> None:
    assert split_keepends(f"a{ending}b") == [("a", ending), ("b", "")]


def test_crlf_is_one_ending_never_a_cr_row_then_an_lf_row() -> None:
    rows = split_keepends("a\r\nb")
    assert rows == [("a", "\r\n"), ("b", "")]
    assert rows[0][1] == "\r\n", "the CRLF text's first row ends in ONE ending"
    assert split_keepends("a\r\n") == [("a", "\r\n")]
    assert split_keepends("\r\n\r\n") == [("", "\r\n"), ("", "\r\n")]


def test_lf_then_cr_is_two_endings() -> None:
    """Only CR followed by LF is one ending. The reverse is two."""
    assert split_keepends("a\n\rb") == [("a", "\n"), ("", "\r"), ("b", "")]


@pytest.mark.parametrize("sep", list(EXOTIC), ids=list(EXOTIC.values()))
def test_no_other_separator_splits_a_row(sep: str) -> None:
    text = f"a{sep}b"
    assert len(text.splitlines()) == 2, "str.splitlines() breaks on it"
    assert split_keepends(text) == [(text, "")]
    assert split_keepends(text + "\n") == [(text, "\n")]
    assert split_keepends(f"{sep}\r\n{sep}") == [(sep, "\r\n"), (sep, "")]


def test_the_named_separators_are_every_one_splitlines_breaks_on() -> None:
    """So the list above is complete, measured over every code point rather
    than taken from documentation."""
    breaks = {chr(point) for point in range(sys.maxunicode + 1)
              if len(f"a{chr(point)}b".splitlines()) != 1}
    assert breaks == {"\r", "\n", *EXOTIC}


def test_no_code_point_but_cr_and_lf_ends_a_row() -> None:
    text = "".join(chr(point) for point in range(sys.maxunicode + 1)
                   if chr(point) not in "\r\n")
    assert split_keepends(text) == [(text, "")]


# ---------------------------------------------------------------------------
# 2. the round trip, over a corpus of row shapes
# ---------------------------------------------------------------------------

#: Each text with the rows it must read as.
ROW_SHAPES = [
    ("", []),
    ("a", [("a", "")]),
    ("a\n", [("a", "\n")]),
    ("a\r", [("a", "\r")]),
    ("a\r\n", [("a", "\r\n")]),
    ("\n", [("", "\n")]),
    ("\n\n", [("", "\n"), ("", "\n")]),
    ("a\nb\n", [("a", "\n"), ("b", "\n")]),
    ("a\rb\r\nc\nd", [("a", "\r"), ("b", "\r\n"), ("c", "\n"), ("d", "")]),
    ("\r\r\n\n", [("", "\r"), ("", "\r\n"), ("", "\n")]),
    ("a\fb c\n", [("a\fb c", "\n")]),
    # The damage openxFactory's `lines.py` records: a splitlines reader saw
    # TWO lines here, and a header flip glued the second onto the new value.
    ("Status: draft\frest of the line\nKind: x\n",
     [("Status: draft\frest of the line", "\n"), ("Kind: x", "\n")]),
]


@pytest.mark.parametrize("text, rows", ROW_SHAPES)
def test_each_shape_reads_as_its_rows(text: str, rows: list) -> None:
    assert split_keepends(text) == rows


#: Texts the round trip runs over, each once: every shape, every ending and
#: separator alone, inside a row, at either end and between real endings, and
#: every ending and separator together.
ROUND_TRIP_CORPUS = list(dict.fromkeys([text for text, _rows in ROW_SHAPES] + [
    variant
    for sep in [*REAL_ENDINGS, *EXOTIC]
    for variant in (sep, f"a{sep}b", f"a{sep}", f"{sep}b", f"\r\n{sep}\r",
                    f"x{sep}\n{sep}y")
] + ["".join([*REAL_ENDINGS, *EXOTIC]) * 3, "no ending at all"]))


@pytest.mark.parametrize("text", ROUND_TRIP_CORPUS)
def test_the_round_trip_returns_the_text(text: str) -> None:
    assert join_rows(split_keepends(text)) == text


def test_join_rows_writes_each_body_then_its_own_ending() -> None:
    assert join_rows([("a", "\r\n"), ("b", "\r"), ("c", "")]) == "a\r\nb\rc"
    assert join_rows([("a", ""), ("b", "")]) == "ab"
    assert join_rows([]) == ""


def test_the_round_trip_alone_cannot_tell_splitlines_from_this_rule() -> None:
    """design.md § 3: `str.splitlines(keepends=True)` round-trips the same
    texts while splitting on the exotic separators. So a test of the round
    trip alone passes a `splitlines` rule, and the boundary tests in 1 are
    what fail one."""
    for sep in EXOTIC:
        text = f"a{sep}b\n"
        assert "".join(text.splitlines(keepends=True)) == text
        assert len(text.splitlines(keepends=True)) == 2
        assert len(split_keepends(text)) == 1


# ---------------------------------------------------------------------------
# 3. the real-line rule, as a property over every short text
# ---------------------------------------------------------------------------

#: A plain character, the two real line-ending characters, and two separators
#: `str.splitlines()` breaks on.
ALPHABET = ("a", "\r", "\n", "\f", " ")


def _reference_rows(text: str) -> list[tuple[str, str]]:
    """The rule read one character at a time, independently of the module:
    CR then LF is one ending, CR or LF alone is one, nothing else is."""
    rows: list[tuple[str, str]] = []
    body: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\r" and text[i + 1:i + 2] == "\n":
            rows.append(("".join(body), "\r\n"))
            body, i = [], i + 2
        elif char in ("\r", "\n"):
            rows.append(("".join(body), char))
            body, i = [], i + 1
        else:
            body.append(char)
            i += 1
    if body:
        rows.append(("".join(body), ""))
    return rows


def _shape_breaks(rows: list[tuple[str, str]]) -> list[str]:
    broken = []
    for index, (body, ending) in enumerate(rows):
        if "\r" in body or "\n" in body:
            broken.append(f"row {index}'s body holds a line-ending character")
        if ending not in ("\r", "\n", "\r\n", ""):
            broken.append(f"row {index} ends in {ending!r}")
        if ending == "" and index != len(rows) - 1:
            broken.append(f"row {index} has no ending and is not the last")
        if ending == "" and body == "":
            broken.append(f"row {index} is empty with no ending")
    return broken


def test_every_short_text_reads_as_the_rule_reads_it() -> None:
    failures = []
    checked = 0
    for size in range(7):
        for chars in itertools.product(ALPHABET, repeat=size):
            text = "".join(chars)
            rows = split_keepends(text)
            checked += 1
            if rows != _reference_rows(text):
                failures.append(f"{text!r}: {rows!r} != {_reference_rows(text)!r}")
            elif join_rows(rows) != text:
                failures.append(f"{text!r}: the round trip gave {join_rows(rows)!r}")
            else:
                failures += [f"{text!r}: {why}" for why in _shape_breaks(rows)]
    assert checked == sum(len(ALPHABET) ** size for size in range(7))
    assert not failures, f"{len(failures)} of {checked}: {failures[:5]}"


# ---------------------------------------------------------------------------
# 4. head_sha on a real temporary repository, and every way it degrades
# ---------------------------------------------------------------------------

def test_the_head_of_a_real_repository_is_read(checkout) -> None:
    expected = _head(checkout)
    assert len(expected) == 40
    assert set(expected) <= set("0123456789abcdef")
    assert head_sha(checkout) == expected
    assert head_sha(str(checkout)) == expected


def test_the_head_moves_with_a_new_commit_and_a_detached_head_is_read(
        checkout) -> None:
    first = _head(checkout)
    second = _commit(checkout, "b.txt")
    assert second != first
    assert head_sha(checkout) == second
    _git("-C", str(checkout), "checkout", "-q", "--detach", first)
    assert head_sha(checkout) == first


def test_a_directory_that_is_not_a_repository_has_no_head(
        outside_any_repository) -> None:
    assert head_sha(outside_any_repository) is None


def test_an_unborn_head_is_no_head(unborn) -> None:
    """git prints `HEAD` on stdout here, and exits 128."""
    assert head_sha(unborn) is None


def test_a_path_that_is_not_there_has_no_head(outside_any_repository) -> None:
    assert head_sha(outside_any_repository / "absent") is None


def test_no_git_on_the_path_is_no_head(checkout, tmp_path, monkeypatch) -> None:
    empty = tmp_path / "no-binaries-here"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert head_sha(checkout) is None


class _Run:
    """A stand-in for `subprocess.run` that records what it was asked."""

    def __init__(self, *, returncode: int = 0, stdout: str = "",
                 raises: BaseException | None = None) -> None:
        self.returncode, self.stdout, self.raises = returncode, stdout, raises
        self.argv: list[str] | None = None
        self.kwargs: dict | None = None

    def __call__(self, argv, **kwargs):
        self.argv, self.kwargs = argv, kwargs
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode,
                                           stdout=self.stdout, stderr="")


def test_the_read_is_realgits_command_and_bound(tmp_path, monkeypatch) -> None:
    """`RealGit._run`'s call, exactly: `git -C <repo> rev-parse HEAD`, with
    output captured as text and a 30-second bound."""
    run = _Run(stdout="0123abcd\n")
    monkeypatch.setattr(lines.subprocess, "run", run)
    assert head_sha(tmp_path) == "0123abcd"
    assert run.argv == ["git", "-C", str(tmp_path), "rev-parse", "HEAD"]
    assert run.kwargs == {"capture_output": True, "text": True, "timeout": 30}


def test_a_git_that_does_not_answer_in_time_is_no_head(tmp_path,
                                                         monkeypatch) -> None:
    run = _Run(raises=subprocess.TimeoutExpired(["git"], 30))
    monkeypatch.setattr(lines.subprocess, "run", run)
    assert head_sha(tmp_path) is None
    assert run.kwargs["timeout"] == 30


def test_a_git_that_cannot_start_is_no_head(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lines.subprocess, "run",
                        _Run(raises=PermissionError("not executable")))
    assert head_sha(tmp_path) is None


def test_a_failed_read_is_no_head_whatever_it_printed(tmp_path,
                                                      monkeypatch) -> None:
    monkeypatch.setattr(lines.subprocess, "run",
                        _Run(returncode=128, stdout="HEAD\n"))
    assert head_sha(tmp_path) is None


def test_an_empty_answer_is_no_head(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lines.subprocess, "run", _Run(stdout=""))
    assert head_sha(tmp_path) is None


def test_a_blank_answer_is_read_as_realgit_reads_it(tmp_path,
                                                    monkeypatch) -> None:
    """`RealGit.head_sha` strips an answer only when there is one, so a blank
    answer reads as `""`, not `None`. No git prints one for `rev-parse HEAD`.
    It is pinned so moving the generator onto this read (T074) changes
    nothing, even here. `serve._CheckoutHead` answers `None` for it, which is
    why the parity test in 5 does not include it."""
    monkeypatch.setattr(lines.subprocess, "run", _Run(stdout="\n"))
    assert head_sha(tmp_path) == ""


def test_any_other_error_propagates_as_realgits_does(tmp_path,
                                                     monkeypatch) -> None:
    """Only a timeout and an error starting git are `None` there. Anything
    else is a defect, and swallowing it would hide one."""
    monkeypatch.setattr(lines.subprocess, "run",
                        _Run(raises=ValueError("a defect, not an answer")))
    with pytest.raises(ValueError, match="a defect, not an answer"):
        head_sha(tmp_path)


# ---------------------------------------------------------------------------
# 5. parity with serve._head_of, the other reader of the same read
# ---------------------------------------------------------------------------

#: Each case's path, built under the test's own directory.
_PARITY_CASES = {
    "repository": _new_checkout,
    "unborn HEAD": _new_unborn,
    "not a repository": lambda base: base,
}


@pytest.mark.parametrize("case", list(_PARITY_CASES))
def test_head_sha_and_serves_reader_agree(case: str, outside_any_repository) -> None:
    path = _PARITY_CASES[case](outside_any_repository)
    ours, serves = head_sha(path), serve._head_of(path)
    assert ours == serves, f"{case}: lines.head_sha {ours!r}, serve._head_of {serves!r}"
    if case == "repository":
        assert ours is not None, "the two agreed only by both failing to read"
        assert len(ours) == 40


# ---------------------------------------------------------------------------
# 6. import weight
# ---------------------------------------------------------------------------

#: openXdox, and openxFactory's packages, blocked at the finder so neither an
#: installed copy nor a developer's path can satisfy an import of them.
_BLOCKED = ("openxdox", "doc_health", "ideation_dashboard",
            "corpus_adapter_openxfactory", "scripts")

_IMPORT_WEIGHT = """
import json, sys
for name in {blocked!r}:
    sys.modules[name] = None
before = set(sys.modules)
import opendox.lines
added = set(sys.modules) - before
print(json.dumps({{
    "foreign": sorted(m for m in added
                      if m.split(".")[0] not in sys.stdlib_module_names
                      and m.split(".")[0] != "opendox"),
    "own": sorted(m for m in added if m.split(".")[0] == "opendox"),
    "names": list(opendox.lines.__all__),
}}))
"""


def test_the_module_loads_the_standard_library_and_nothing_else_of_opendox() -> None:
    """THIS tree's module, by its `src/` first on the path, in a fresh
    interpreter."""
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])}
    done = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_IMPORT_WEIGHT.format(blocked=_BLOCKED))],
        capture_output=True, text=True, cwd=str(SRC), env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout.strip().splitlines()[-1])
    assert found == {"foreign": [], "own": ["opendox", "opendox.lines"],
                     "names": ["split_keepends", "join_rows", "head_sha"]}, found
