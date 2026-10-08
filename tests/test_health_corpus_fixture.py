"""The health-corpus fixture: ONE planted finding per kind, and nothing else a
neutral family would flag (plan 038 T043, HA-3; #1144 box 14.9; FR-015).

`tests/fixtures/health-corpus/` is 14.9's corpus. F14.1 copies it into a FRESH
git repository, commits it in ONE commit, starts the document server over it,
and then drives `health run`, `health list`, `health fix` and `health accept`
against it. Every assertion F14.1 makes is about a finding this directory put
there on purpose.

WHAT THIS SUITE HOLDS. T044's families do not exist when T043 lands, so this
suite asserts the LAYOUT and the DOCUMENTS only, and the one end-to-end fact the
fixture owes its reader: the corpus generates through the pinned validator.
That the families then raise ONE finding per planted document, of the intended
kind and class, is T044's proof (`tests/test_health_families.py`), over this
corpus. The `INTENDED` table below is what T044 reads its expectations from.

THE DOCUMENTS (batch Q's selection lines find each by its `path`, and its
`kind` where the old id names a family):

| old id                    | path                                    | kind                      | class      |
|---------------------------|-----------------------------------------|---------------------------|------------|
| `broken-link`             | `broken-link.md`                        | `broken-link`             | auto-fix   |
| `derivable-front-matter`  | `derivable-front-matter.md`             | `derivable-front-matter`  | auto-fix   |
| `stage-location-mismatch` | `candidate/stage-location-mismatch.md`  | `stage-location-mismatch` | auto-fix   |
| `near-duplicate`          | `near-duplicate.md`                     | `near-duplicate`          | assisted   |
| (the empty stub)          | `empty-stub.md`                         | `empty-stub`              | assisted   |
| `human-only-finding`      | `human-only-finding.md`                 | `orphan`                  | human-only |
| `accepted-finding`        | `accepted-finding.md`                   | `broken-link` (absent)    | human-only |

SIX DECISIONS THIS FIXTURE MAKES, each one a pin T044 and T065 must honor.

1. THE DERIVABLE FRONT MATTER HAS NO `title:` KEY AT ALL. It carries a `# `
   heading the title can be taken from, and a `summary:`. An EMPTY `title:` is
   never planted: the pinned validator rejects a snapshot that holds one
   (`title-and-summary-are-text`, "'' is shorter than 1"), `generate-and-open`
   then returns non-zero and serves nothing, and F14.1 stops before its first
   `health run`. A document that gives no `title:` key reaches the snapshot as
   `null`, which the contract accepts
   (`test_an_empty_title_is_rejected_by_the_check_that_the_corpus_passes`).
2. THE NEAR-DUPLICATE TIE. F14.1 commits the corpus in ONE commit, so OQ-H-11's
   "the later-committed one" is a tie. The tie is broken by PATH ORDER, the
   greater path being the later one. The pair is `compost-bin-sizing.md` (the
   original, which sorts first) and `near-duplicate.md` (which sorts last), and
   `near-duplicate.md` is the document the finding is raised on. The sibling's
   name does not contain `near-duplicate`, so no match by substring selects it
   too. T044's tiebreak MUST report `near-duplicate.md`.
3. THE EMPTY STUB KEEPS ITS HEADER. `empty-stub.md` carries `title:` and
   `summary:` and has no body at all. A zero-byte file would also have no
   title, and (it having no heading) none that could be derived, so a second
   family would flag the same document, and the stub would not be a document
   with ONE finding. Its body is blank, which meets data-model.md's criterion
   ("after front matter, the body holds no line that is neither blank nor a
   heading") on any reading of it.
4. THE HUMAN-ONLY FINDING IS AN ORPHAN, and the accepted finding is a link to a
   file that exists nowhere (an "unmovable" broken link). OQ-H-8 leaves both
   unplaced; both are `human-only` by that ruling. `broken-link` therefore
   names two documents in the corpus, which differ in `path` and in class.
5. THE INBOUND-LINK EXEMPTION (OQ-H-16): README and index documents are exempt
   from "nothing links to it". The corpus holds exactly two entry documents,
   `README.md` and `garden/index.md`, and neither has a link pointing at it,
   so both exercise the exemption. Besides those two, the ONLY document with
   no inbound link is the planted orphan. MEASURED: `plain-documents/` holds 8
   files and 0 links (`grep -cE '\\]\\(|\\[\\['` reads 0 in each), so it could
   not be this corpus's base: its eight documents would be eight orphans, and
   the exemption covers an entry document, not a document that merely has no
   link. This corpus therefore reuses none of its files
   (`test_the_plain_documents_measurement_is_why_it_is_not_the_base`).
6. NO LOCATION IS INVENTED. A document's location is a top-level directory named
   by one of the six role keys (R2Q11 (a)). Exactly two documents sit in one,
   both in `candidate/`: one agrees with its folder (a control) and one does
   not (the planted mismatch). Every other document is outside any such
   directory and has no location.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import posixpath
import re
from itertools import combinations
from pathlib import Path

import pytest

from opendox.display_profile import STAGE_ROLES
from standalone_child import fresh_repository, run_module

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
CORPUS = FIXTURES / "health-corpus"
PLAIN = FIXTURES / "plain-documents"

#: Each planted finding's document, by the old literal id it was first written
#: under. A selection takes the ONE finding whose `path` is that document.
PLANTED: dict[str, str] = {
    "broken-link": "broken-link.md",
    "derivable-front-matter": "derivable-front-matter.md",
    "stage-location-mismatch": "candidate/stage-location-mismatch.md",
    "near-duplicate": "near-duplicate.md",
    "human-only-finding": "human-only-finding.md",
    "accepted-finding": "accepted-finding.md",
}

#: The ONE empty stub, which requirement 14's third scenario classes `assisted`
#: though 14.9's own list omits it (ADV-17).
EMPTY_STUB = "empty-stub.md"

#: What each planted document is meant to raise: `(kind, class)`. T044's tests
#: read this and prove it; this suite does not, because the families do not
#: exist yet.
INTENDED: dict[str, tuple[str, str]] = {
    "broken-link": ("broken-link", "auto-fix"),
    "derivable-front-matter": ("derivable-front-matter", "auto-fix"),
    "stage-location-mismatch": ("stage-location-mismatch", "auto-fix"),
    "near-duplicate": ("near-duplicate", "assisted"),
    "empty-stub": ("empty-stub", "assisted"),
    "human-only-finding": ("orphan", "human-only"),
    "accepted-finding": ("broken-link", "human-only"),
}

#: The pair a near-duplicate finding is raised from, ordered by path, and the
#: document the finding is raised on: the LATER one, by path order.
NEAR_DUPLICATE_PAIR = ("compost-bin-sizing.md", "near-duplicate.md")
NEAR_DUPLICATE_REPORTED = "near-duplicate.md"

#: The corpus's non-planted documents, each a clean document or a control.
CLEAN = (
    "README.md",
    "compost-bin-sizing.md",
    "candidate/path-edging-options.md",
    "garden/index.md",
    "garden/rain-barrel-checklist.md",
)

#: The two entry documents (OQ-H-16), neither with a link pointing at it.
ENTRY_DOCUMENTS = ("README.md", "garden/index.md")

EXPECTED_FILES = sorted({*PLANTED.values(), EMPTY_STUB, *CLEAN})

#: The target of each planted broken link, as written in its document. The
#: first exists once elsewhere (a moved target); the second exists nowhere.
MOVED_LINK = ("broken-link.md", "reference/rain-barrel-checklist.md",
              "garden/rain-barrel-checklist.md")
ABSENT_LINK = ("accepted-finding.md", "archive/shed-plans-2019.md")

#: The word-shingle Jaccard of the near-duplicate pair, over each document's
#: whole text, is MEASURED at 0.953 (0.943 over the bodies alone), and no other
#: pair of the twelve reaches 0.06. The bounds sit between, so any reasonable
#: similarity threshold a family sets separates the pair from the rest.
NEAR_DUPLICATE_FLOOR = 0.9
OTHER_PAIRS_CEILING = 0.2

#: A body of this many lines or fewer, in a file old enough, is a stale stub
#: (data-model.md § Families). Every document that is not the planted empty
#: stub carries more, so no clean document is one at any age.
STALE_STUB_MAX_LINES = 3

#: The declared vocabulary a neutral fixture must not spell, as
#: `tests/test_plain_documents_fixture.py` declares it (the eight `Status:`
#: words and the change/spec/delta nouns), copied for the same reason: this
#: corpus is read as plain prose by a reader that never imports `opendox`.
DECLARED_VOCABULARY = (
    "brainstorm", "staged", "draft", "ratified", "standard", "superseded",
    "retired", "record",
    "change", "changes", "spec", "specs", "delta", "deltas", "openspec",
    "proposal", "proposals",
)
_VOCABULARY = re.compile(
    r"\b(" + "|".join(map(re.escape, DECLARED_VOCABULARY)) + r")\b",
    re.IGNORECASE)

_INLINE_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_LINK_MARKUP = re.compile(r"\]\(|\[\[")      # the measurement's own pattern
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_EXTERNAL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _files(base: Path) -> list[str]:
    return sorted(p.relative_to(base).as_posix()
                  for p in base.rglob("*") if p.is_file() or p.is_symlink())


def _text(relative: str) -> str:
    return (CORPUS / relative).read_text(encoding="utf-8")


def _header_and_body(text: str) -> tuple[dict[str, str], str]:
    """The convention `LocalGitCorpus._header_of` reads: the leading run of
    `Name: value` lines up to the first blank line is the header, and what
    follows is the body. Re-implemented, not imported, as the plain-documents
    suite does: the fixture must read as plain text to a reader that builds no
    corpus."""
    lines = text.splitlines()
    header: dict[str, str] = {}
    body_start = len(lines)
    for index, line in enumerate(lines):
        if not line.strip():
            body_start = index + 1
            break
        name, separator, value = line.partition(":")
        if separator:
            header[name.strip()] = value.strip()
    return header, "\n".join(lines[body_start:])


def _content_lines(body: str) -> list[str]:
    """The lines that are neither blank nor a heading."""
    return [line for line in body.splitlines()
            if line.strip() and not _HEADING.match(line)]


def _links(relative: str) -> list[str]:
    """The internal link targets of one document, fragment dropped, resolved
    against the document's own directory to a corpus-relative path."""
    out = []
    for target in _INLINE_LINK.findall(_text(relative)):
        if _EXTERNAL.match(target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        base = "" if path.startswith("/") else posixpath.dirname(relative)
        out.append(posixpath.normpath(posixpath.join(base, path.lstrip("/"))))
    return out


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def _jaccard(a: str, b: str) -> float:
    left, right = _shingles(a), _shingles(b)
    return len(left & right) / len(left | right)


# --------------------------------------------------------------------------
# the layout
# --------------------------------------------------------------------------

def test_the_corpus_holds_exactly_the_declared_files() -> None:
    """A missing document, an extra one, a symlink, an engine file or a stray
    `conftest.py` all fail here, by name."""
    assert CORPUS.is_dir(), f"expected {CORPUS} to exist"
    found = _files(CORPUS)
    assert found == EXPECTED_FILES, (
        f"missing {sorted(set(EXPECTED_FILES) - set(found))}, "
        f"unexpected {sorted(set(found) - set(EXPECTED_FILES))}")
    assert not [p for p in CORPUS.rglob("*") if p.is_symlink()]


@pytest.mark.parametrize("old_id", sorted(PLANTED))
def test_each_planted_document_exists_under_its_old_id(old_id: str) -> None:
    document = CORPUS / PLANTED[old_id]
    assert document.is_file(), PLANTED[old_id]
    assert not document.is_symlink(), PLANTED[old_id]
    assert document.stem == old_id, (
        f"{PLANTED[old_id]} must be named after its old id {old_id!r}")


@pytest.mark.parametrize("name", sorted([*PLANTED, "empty-stub"]))
def test_exactly_one_document_answers_to_each_planted_name(name: str) -> None:
    """A second document under a planted name (a copy in another folder, or a
    sibling whose name contains it) would let a selection by `path` or by name
    find two."""
    answering = [p for p in _files(CORPUS) if name in posixpath.basename(p)]
    assert len(answering) == 1, f"{name!r} is carried by {answering}"


def test_every_corpus_file_is_a_markdown_document_outside_the_engine_files() -> None:
    for relative in _files(CORPUS):
        assert relative.endswith(".md"), relative
    assert not [p for p in _files(CORPUS) if p.startswith("health/")]


# --------------------------------------------------------------------------
# the planted documents
# --------------------------------------------------------------------------

def test_derivable_front_matter_has_no_title_key_and_a_heading() -> None:
    text = _text(PLANTED["derivable-front-matter"])
    header, body = _header_and_body(text)
    assert "title" not in header, (
        "an EMPTY `title:` is rejected by the pinned validator and stops "
        "F14.1 before its first run; plant NO title key")
    assert not [line for line in text.splitlines()[:len(header) + 1]
                if line.partition(":")[0].strip() == "title"]
    assert header.get("summary"), "only the title is missing here"
    assert any(_HEADING.match(line) for line in body.splitlines()), (
        "the title must be derivable from a heading")
    assert header.get("stage") is None, "a document with no stage is a source"


def test_the_empty_stub_is_empty() -> None:
    text = _text(EMPTY_STUB)
    header, body = _header_and_body(text)
    assert text.strip(), "a zero-byte stub would also lack its neutral fields"
    assert header.get("title"), f"{EMPTY_STUB} keeps its title"
    assert header.get("summary"), f"{EMPTY_STUB} keeps its summary"
    assert body.strip() == "", f"{EMPTY_STUB} must carry no body at all"
    assert _content_lines(body) == []


def test_every_other_document_has_a_body_longer_than_a_stub() -> None:
    for relative in EXPECTED_FILES:
        if relative == EMPTY_STUB:
            continue
        _, body = _header_and_body(_text(relative))
        assert len(_content_lines(body)) > STALE_STUB_MAX_LINES, relative


def test_the_neutral_fields_are_missing_from_exactly_one_document() -> None:
    missing = {}
    for relative in EXPECTED_FILES:
        header, _ = _header_and_body(_text(relative))
        gone = [f for f in ("title", "summary") if not header.get(f)]
        if gone:
            missing[relative] = gone
    assert missing == {PLANTED["derivable-front-matter"]: ["title"]}, missing


def test_the_stage_mismatch_is_one_document_and_its_control_agrees() -> None:
    """R2Q11 (a): a location is a top-level directory named by a role key; a
    document outside one has none and is never flagged."""
    mismatched, agreeing = [], []
    for relative in EXPECTED_FILES:
        top = relative.split("/", 1)[0] if "/" in relative else None
        if top not in STAGE_ROLES:
            continue
        stage = _header_and_body(_text(relative))[0].get("stage")
        assert stage in STAGE_ROLES, f"{relative} declares {stage!r}"
        (agreeing if stage == top else mismatched).append(relative)
    assert mismatched == [PLANTED["stage-location-mismatch"]]
    assert agreeing == ["candidate/path-edging-options.md"]
    for relative in set(EXPECTED_FILES) - {*mismatched, *agreeing}:
        assert _header_and_body(_text(relative))[0].get("stage") is None, (
            f"{relative} is outside a role directory and declares no stage")


def test_the_broken_links_are_the_moved_one_and_the_absent_one() -> None:
    """Two links resolve to nothing, and only two. The first target exists
    once elsewhere under the same file name (OQ-H-10: a moved target,
    `auto-fix`); the second exists nowhere (`human-only`)."""
    existing = set(EXPECTED_FILES)
    unresolved = sorted((relative, target) for relative in EXPECTED_FILES
                        for target in _links(relative)
                        if target not in existing)
    assert unresolved == sorted([MOVED_LINK[:2], ABSENT_LINK]), unresolved
    moved_name = posixpath.basename(MOVED_LINK[1])
    elsewhere = [p for p in existing if posixpath.basename(p) == moved_name]
    assert elsewhere == [MOVED_LINK[2]], "the moved target is unique"
    absent_name = posixpath.basename(ABSENT_LINK[1])
    assert not [p for p in existing if posixpath.basename(p) == absent_name]
    assert not any("[[" in _text(r) for r in EXPECTED_FILES), (
        "the corpus uses inline links only")


def test_the_near_duplicate_pair_ties_and_path_order_picks_the_document() -> None:
    """THE PIN T044 MUST HONOR: ONE finding, raised on `near-duplicate.md`.
    F14.1's single commit leaves no commit order, so the greater path is the
    later document."""
    first, last = NEAR_DUPLICATE_PAIR
    assert sorted(NEAR_DUPLICATE_PAIR) == [first, last]
    assert max(NEAR_DUPLICATE_PAIR) == NEAR_DUPLICATE_REPORTED
    assert PLANTED["near-duplicate"] == NEAR_DUPLICATE_REPORTED
    assert first not in {*PLANTED.values(), EMPTY_STUB}
    assert "near-duplicate" not in first, "no substring match may find both"
    similarity = _jaccard(_text(first), _text(last))
    assert similarity >= NEAR_DUPLICATE_FLOOR, similarity
    for a, b in combinations(EXPECTED_FILES, 2):
        if {a, b} == set(NEAR_DUPLICATE_PAIR):
            continue
        assert _jaccard(_text(a), _text(b)) < OTHER_PAIRS_CEILING, (a, b)
    notes = _text("README.md")
    for name in NEAR_DUPLICATE_PAIR:
        assert name in notes, f"the fixture's own notes must name {name}"


def test_the_fixtures_own_notes_declare_the_pin_and_the_exemption() -> None:
    notes = _text("README.md")
    for phrase in ("greater path is the later one", "README and index"):
        assert phrase in notes, phrase


# --------------------------------------------------------------------------
# the inbound-link exemption (OQ-H-16) and its measurement
# --------------------------------------------------------------------------

def test_only_the_entry_documents_and_the_planted_orphan_have_no_inbound_link(
) -> None:
    inbound = {relative: 0 for relative in EXPECTED_FILES}
    for relative in EXPECTED_FILES:
        for target in _links(relative):
            if target in inbound and target != relative:
                inbound[target] += 1
    orphans = sorted(r for r, count in inbound.items() if count == 0)
    assert orphans == sorted([*ENTRY_DOCUMENTS, PLANTED["human-only-finding"]])
    for entry in ENTRY_DOCUMENTS:
        stem = posixpath.splitext(posixpath.basename(entry))[0].lower()
        assert stem in ("readme", "index"), f"{entry} is not an entry document"
        assert entry not in PLANTED.values(), entry
        assert entry != EMPTY_STUB, entry


def test_the_plain_documents_measurement_is_why_it_is_not_the_base() -> None:
    """MEASURED: 8 files, 0 links. Under "nothing links to it" they would be
    eight orphans, and OQ-H-16 exempts only README and index documents. So the
    corpus does not take them as its base, and reuses none of their files."""
    files = sorted(PLAIN.glob("*.md"))
    links = {p.name: len(_LINK_MARKUP.findall(p.read_text(encoding="utf-8")))
             for p in files}
    assert (len(files), sum(links.values())) == (8, 0), (
        f"plain-documents was measured at 8 files and 0 links; now {links}. "
        "Re-measure, and re-declare why health-corpus does not reuse it")
    assert not {p.name for p in files} & {Path(r).name for r in EXPECTED_FILES}


@pytest.mark.parametrize("relative", EXPECTED_FILES)
def test_no_document_spells_the_declared_vocabulary(relative: str) -> None:
    hits = sorted({m.group(1).lower()
                   for m in _VOCABULARY.finditer(_text(relative))})
    assert not hits, f"{relative} carries declared vocabulary word(s) {hits}"


def test_the_intended_table_covers_every_planted_document() -> None:
    assert sorted(INTENDED) == sorted([*PLANTED, "empty-stub"])
    classes = {"auto-fix", "assisted", "human-only"}
    assert {cls for _, cls in INTENDED.values()} == classes


# --------------------------------------------------------------------------
# the corpus generates through the pinned validator
# --------------------------------------------------------------------------

def _generate(tmp_path: Path, edits: dict[str, str] | None = None):
    """`python -m opendox.cli generate --strict` over a FRESH repository of the
    corpus, committed in one commit, as #1144's F14.1 preamble builds it."""
    repo = fresh_repository(CORPUS, tmp_path, edits=edits)
    out = tmp_path / "snapshot.json"
    child, status = run_module(
        tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--strict")
    return child, status, out


def test_the_corpus_generates_through_the_pinned_validator(tmp_path) -> None:
    child, status, out = _generate(tmp_path)
    assert status == 0, child.stderr_text()
    assert child.refused() == [], child.refused()
    assert "0 violations" in child.stdout_text(), child.stdout_text()
    snapshot = json.loads(out.read_text(encoding="utf-8"))
    paths = sorted(document["path"] for document in snapshot["documents"])
    assert paths == EXPECTED_FILES
    by_path = {d["path"]: d for d in snapshot["documents"]}
    derivable = by_path[PLANTED["derivable-front-matter"]]
    assert derivable["title"] is None, (
        "no title key reaches the snapshot as null, never as an empty text")
    assert by_path[EMPTY_STUB]["title"], "the stub keeps its title"


def test_an_empty_title_is_rejected_by_the_check_that_the_corpus_passes(
        tmp_path) -> None:
    """The reason the derivable document plants NO `title:` key: the same
    corpus with an EMPTY `title:` line on it is REJECTED, and `generate`
    exits 1. This is the check above, shown capable of failing."""
    relative = PLANTED["derivable-front-matter"]
    child, status, _ = _generate(
        tmp_path, edits={relative: "title:\n" + _text(relative)})
    err = child.stderr_text()
    assert status == 1, err
    assert "title-and-summary-are-text" in err, err
    assert "REJECTED" in err, err


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
