"""The plain-documents fixture: spread across the six stations, and clean of
the publishing repository's own vocabulary (plan 034, T050).

`tests/fixtures/plain-documents/` is 5.0's fixture (plan 034 tasks.md § Phase
2, slice P2-F): a handful of `.md` documents a plain, ungoverned git
repository could contain, read by AT-R1 (spec.md § "AT-R1 — the release-1
acceptance test", step 3(a)) and by F5.3, F7.2, F10.1 and F13.1 once those
falsifiers exist. None of it is wired to any `opendox` code yet — T052 and
T054 (the generator seam and the neutral projection) have not landed — so
this suite tests the fixture's own two guarantees rather than a projection
over it.

THE TWO GUARANTEES, AND WHY.

1. NEUTRAL VOCABULARY (T050's task line: *"It carries none of the declared
   vocabulary: the eight `Status:` words and the change/spec/delta
   nouns."*). A neutral product shipping its own publisher's governance
   words in ITS TEST DATA is the same defect requirement 3's second scenario
   refuses in RENDERED words and names
   (`tests/test_default_profile.py`); this is the shipped-fixture half of
   that same property, swept on its own footing because a fixture is prose
   no engine renders and the rendering sweep never sees it.
2. SIX STATIONS, ONE GROUP (RULED R1Q13 (a) with (c), `openxFactory#656`
   comment `5850003126`; spec.md line ~170, ~454-463). A neutral
   front-matter key, `stage: <role>`, names a document's station; a
   document that declares no `stage:` line at all is a SOURCE. This fixture
   carries one document per explicit station (`grouping`, `candidate`,
   `selection`, `submission`, `completion`) and three sources, two of which
   share the phrase "rain barrel" verbatim so a future topic-based grouping
   pass (T054) has a pair to find — the fixture must yield at least one
   group, so AT-R1 can open the chat pane from a grouping tile (spec.md
   § AT-R1 steps 6-7).

Every document also carries the small neutral field set the default adapter
will require regardless of station — `title` and `summary` — per T050's task
line and the answer's own example.

COLLECTED BY THE REQUIRED CHECK. Since T036, `validate` runs the whole suite
(`python -m pytest -q` over the configured testpaths) instead of an explicit
list of files, so this suite is collected like every other and needs no entry
anywhere.

A CREATED file: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
(RULED OQ-C: the manifest declares what LEAVES openxFactory, never what a
destination assembles).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "plain-documents"

sys.path.insert(0, str(ROOT / "src"))
from opendox.display_profile import STAGE_ROLES  # noqa: E402

#: Its STATUS TAXONOMY: the eight controlled `Status:` words this project's
#: own root `CLAUDE.md` names verbatim (*"brainstorm | staged | draft |
#: ratified | standard | superseded | retired | record"*), identical to the
#: eight `tests/test_default_profile.py`'s `STATUS_TAXONOMY`,
#: `tests/test_web_boundary.py`'s `_STATUS_WORDS` and
#: `tests/test_display_facet.py`'s `OPENXFACTORY_WORDS` all open with, at
#: openxFactory `133e37d9`. T050's own task line says "the eight", so this
#: suite does not also carry `test_default_profile.py`'s ninth,
#: `projection` — that word is `openxfactory-engineering.yaml`'s own
#: lifecycle addition, a different sweep than this one.
STATUS_WORDS = (
    "brainstorm", "staged", "draft", "ratified", "standard",
    "superseded", "retired", "record",
)

#: Its CHANGE/SPEC/DELTA NOUNS: the same family `tests/test_default_profile.py`
#: carries as `CHANGE_SPEC_DELTA_NOUNS` — the OpenSpec artifact a governed
#: change is, and the proposal that opens one. Copied rather than imported,
#: on the same footing as `STATUS_WORDS`: this fixture must be readable as
#: plain prose by something that never imports `opendox` at all (the
#: acceptance harness copies it into a bare `git init`), so the word list a
#: reader would check it against has to stand on its own too.
CHANGE_SPEC_DELTA_NOUNS = (
    "change", "changes", "spec", "specs", "delta", "deltas",
    "openspec", "proposal", "proposals",
)

DECLARED_VOCABULARY = frozenset(STATUS_WORDS + CHANGE_SPEC_DELTA_NOUNS)

_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in DECLARED_VOCABULARY) + r")\b",
    re.IGNORECASE,
)

#: The neutral field set the default adapter will require of every document
#: regardless of station (T050's task line: *"e.g. title, summary"*).
REQUIRED_FIELDS = ("title", "summary")

#: The phrase at least two SOURCE documents (no `stage:` header) share
#: verbatim, so a topic-based grouping pass has a pair to find (R1Q13 (a)
#: with (c)).
SHARED_SOURCE_TOPIC = "rain barrel"

FIXTURE_FILES = sorted(FIXTURE_DIR.glob("*.md")) if FIXTURE_DIR.is_dir() else []


def _header_and_body(text: str) -> tuple[dict[str, str], str]:
    """The same convention `LocalGitCorpus._header_of` reads (`runtime/
    local_git_adapter.py`): the leading run of `Name: value` lines up to the
    first blank line is the header, and everything after is the body.
    Re-implemented rather than imported — this fixture must be readable as
    plain text by something that never builds a corpus at all, exactly as
    the acceptance harness (T095) and a human skimming the directory would
    read it.
    """
    lines = text.splitlines()
    header: dict[str, str] = {}
    body_start = len(lines)
    for i, line in enumerate(lines):
        if not line.strip():
            body_start = i + 1
            break
        name, separator, value = line.partition(":")
        if separator:
            header[name.strip()] = value.strip()
    return header, "\n".join(lines[body_start:])


def _documents() -> dict[Path, tuple[dict[str, str], str]]:
    return {path: _header_and_body(path.read_text(encoding="utf-8"))
            for path in FIXTURE_FILES}


def test_fixture_directory_exists_and_is_not_empty() -> None:
    assert FIXTURE_DIR.is_dir(), f"expected {FIXTURE_DIR} to exist"
    assert FIXTURE_FILES, f"no .md fixture files found under {FIXTURE_DIR}"


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_no_declared_vocabulary_word(path: Path) -> None:
    """Neither the header nor the body of any fixture document carries one
    of the eight `Status:` words or a change/spec/delta noun."""
    text = path.read_text(encoding="utf-8")
    hits = sorted({m.group(1).lower() for m in _WORD_PATTERN.finditer(text)})
    assert not hits, (
        f"{path.name} carries declared vocabulary word(s) {hits}; a neutral "
        "fixture must not spell its publisher's governance words"
    )


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_required_fields_present(path: Path) -> None:
    header, _ = _header_and_body(path.read_text(encoding="utf-8"))
    missing = [field for field in REQUIRED_FIELDS if field not in header]
    assert not missing, f"{path.name} is missing required field(s) {missing}"


def test_spread_across_the_six_stations() -> None:
    """One document per explicit station, and every undeclared document is
    a source (R1Q13 (a) with (c))."""
    by_role: dict[str, list[Path]] = {role: [] for role in STAGE_ROLES}
    for path, (header, _) in _documents().items():
        stage = header.get("stage")
        if stage is None:
            by_role["source"].append(path)
            continue
        assert stage in STAGE_ROLES, (
            f"{path.name} declares stage {stage!r}, not one of {STAGE_ROLES}"
        )
        by_role[stage].append(path)

    empty = [role for role, paths in by_role.items() if not paths]
    assert not empty, f"no fixture document occupies station(s) {empty}"

    # "source" is where every undeclared document lands, so it alone may
    # hold more than one; the five explicit stations carry exactly one each.
    for role in STAGE_ROLES:
        if role == "source":
            continue
        assert len(by_role[role]) == 1, (
            f"station {role!r} has {len(by_role[role])} document(s), want 1"
        )


def test_at_least_two_sources_share_a_topic() -> None:
    """R1Q13 (a) with (c): groups derive from the topics sources share, and
    the fixture must yield at least one group."""
    sharing = [
        path for path, (header, body) in _documents().items()
        if "stage" not in header
        and SHARED_SOURCE_TOPIC in " ".join(
            (header.get("title", ""), header.get("summary", ""), body)
        ).lower()
    ]
    assert len(sharing) >= 2, (
        f"expected >= 2 source documents sharing {SHARED_SOURCE_TOPIC!r}, "
        f"found {[p.name for p in sharing]}"
    )


#: The two words this fixture's titles use that carry no topic under any
#: reading of a name: an article and a conjunction. They are dropped before
#: two names are compared, and nothing else is.
FUNCTION_WORDS = frozenset({"the", "and"})

_LETTER_RUN = re.compile(r"[^\W\d_]+")


def _tokens(text: str) -> list[str]:
    """The runs of letters in `text`, case-folded, in order."""
    return [run.casefold() for run in _LETTER_RUN.findall(text)]


def _name_words(header: dict[str, str]) -> set[str]:
    """The words of a document's name: its `title:` (every document here
    declares one, `test_required_fields_present`), as runs of three or more
    letters, without `FUNCTION_WORDS`."""
    return {word for word in _tokens(header.get("title", ""))
            if len(word) >= 3} - FUNCTION_WORDS


def _names(text: str, path: Path, header: dict[str, str]) -> bool:
    """Whether `text` names the document at `path`: whether it holds that
    document's title, or its file name, as a run of whole words."""
    words = _tokens(text)
    for name in (header.get("title", ""), path.stem):
        run = _tokens(name)
        if run and any(words[i:i + len(run)] == run
                       for i in range(len(words) - len(run) + 1)):
            return True
    return False


def test_at_least_one_source_shares_no_topic() -> None:
    """At least one source shares no topic with the rain-barrel pair.
    Without it, a fixture where every source shared one topic would not
    exercise topic-based grouping at all.

    NO TOPIC, not just not the phrase. The phrase check alone would pass a
    fixture edit that gave the sources some other topic in common, so this
    compares the two things a topic that sources share can be derived from
    when nobody declares one (R1Q13 (a) with (c)):
    - the words of each document's name;
    - the other documents each one names.

    So each rain-barrel note's name carries the pair's topic. A source
    outside the pair shares no name word with either note, and it and the
    notes never name each other, in either direction. Words elsewhere in
    the body are not compared. That the projection then forms exactly this
    group is proved over this fixture by T054's projection test.
    """
    sources = {path: parts for path, parts in _documents().items()
               if "stage" not in parts[0]}
    pair = [path for path, (header, body) in sources.items()
            if SHARED_SOURCE_TOPIC in " ".join(
                (header.get("title", ""), header.get("summary", ""), body)
            ).lower()]
    others = [path for path in sources if path not in pair]
    assert others, "every source shares the same topic phrase"

    topic = set(SHARED_SOURCE_TOPIC.split())
    for member in pair:
        assert topic <= _name_words(sources[member][0]), (
            f"{member.name}'s name does not carry {SHARED_SOURCE_TOPIC!r}")

    for other in others:
        other_header = sources[other][0]
        for member in pair:
            member_header = sources[member][0]
            shared = _name_words(other_header) & _name_words(member_header)
            assert not shared, (
                f"{other.name} and {member.name} share the name word(s) "
                f"{sorted(shared)}, so a topic rule could group them")
            for writer, named, named_header in (
                    (other, member, member_header),
                    (member, other, other_header)):
                assert not _names(writer.read_text(encoding="utf-8"),
                                  named, named_header), (
                    f"{writer.name} names {named.name}, so its topics "
                    "could reach across the pair")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
