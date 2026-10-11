"""HA-2, THE NEUTRAL FAMILIES: openDox's own document-health checks, DETECTION
only (plan 038 T044; #1144 14.4 part, 6.2 part; FR-010, FR-012; R2Q10 (a),
R2Q11 (a), R2Q14 (a); OQ-H-8, -10, -11, -15, -16, -20, -21; N-13).

THE SEVEN FAMILIES, each a named function that runs alone (`CHECKS`):

| kind                      | finds                                         | class      |
|---------------------------|-----------------------------------------------|------------|
| `broken-link`             | a link whose target is not in the corpus      | `auto-fix` when exactly one corpus file has the target's name (a moved target, OQ-H-10); else `human-only` |
| `orphan`                  | a document no other document links to         | `human-only` (OQ-H-8); README and index exempt (OQ-H-16) |
| `near-duplicate`          | a document that nearly repeats another        | `assisted` (14.6) |
| `derivable-front-matter`  | a missing or empty `title` with a level-1 heading | `auto-fix` (14.6) |
| `stage-location-mismatch` | a declared `stage:` that disagrees with its top-level role directory | `auto-fix` (R2Q11 (a)) |
| `empty-stub`              | `EMPTY_STUB_CRITERION`                         | `assisted` (14.6; ADV-17) |
| `stale-stub`              | `STALE_STUB_CRITERION`                         | `human-only` (OQ-H-8; ADV-40) |

Every finding is `warning` (the holder's `openxFactory#656` `6069507373`, T044
item 9: data-model.md § Families states no severity).

THE ENTRY POINT, for T046 and T052:

    run_families(adapter, corpus, *, families=None, documents=None)
        -> list[dict]

`adapter` is a corpus adapter, `default_adapter()` for openDox's own standalone
corpus, and `corpus` what its `resolve()` returned: pinned to a commit for a
run over a commit, unpinned for a working-state run (data-model.md § Health
run). `families` names the families to run, all of `FAMILIES` when None; a
name it does not carry raises `UnknownFamily`. `documents` names the
corpus-relative paths to judge, all when None; `orphan` and `near-duplicate`
still read the whole corpus. The result holds each finding's FAMILY-OWNED
fields only (contracts/health-finding.md:24-25): `kind`, `path`, `identity`,
`locator` where one helps, `severity`, `resolution_class`, `message` and
`evidence`, sorted by path, kind and identity. The engine stamps `id`,
`pack_id`, `pack_version` and `baseline_class` with T041's `make_finding()`;
this module sets none of them and prints nothing. A refused corpus raises the
adapter's `CorpusRefused`, a failed git query too, so the run fails closed.

HOW A DOCUMENT IS READ: as openDox's own projection reads it
(`opendox.neutral_projection`), so "document" keeps one meaning across the
product. The adapter lists the corpus, `classify` says what it is (an entry it
cannot classify is not a document), `read` gives its bytes, decoded as UTF-8
with replacement, and `local_git_adapter.leading_header` gives its header. Only
`text`-kind documents are judged (`JUDGED_SUFFIXES`; the holder's `6069507373`
item 1), and only those whose path the finding contract admits (a path the
contract refuses could never be stored; the projection leaves such a path out
too). A link's target is checked against every corpus FILE, the engine files,
the settings documents and structured files included (`EXCLUDED_PATHS`).

GIT, READ ONLY. The facts the adapter does not give (when a file was last
touched, which commit first added it, which commit descends from which) are
read through `local_git_adapter.GitRunner`, with `GIT_OPTIONAL_LOCKS=0`, by
`rev-list` and `merge-base` alone: plumbing that reads commits, never the
working tree, and runs no program a repository names. Nothing is written under
`.git/` (data-model.md:177). Whether a working-copy file differs from HEAD is
read through the adapter, bytes against bytes, so a file a filter or an
end-of-line rule rewrites reads as changed: conservative, as the adapter's own
`check` is.

MODEL-FREE (OQ-H-20). `near-duplicate` scores with `doxbench_knowledge`'s
`tokenize()` and `embed()`, which run with no binding (OQ-H-21, measured; see
`NEAR_DUPLICATE_THRESHOLD`). This module imports no model, binding, provider
or bridge module and no database driver.

STRINGS (the holder's `6069507373` item 7 and `6072086385` item 4). An identity
or evidence string over `STRING_MAX` characters, or holding U+0000 or a lone
surrogate, is replaced by its SHA-256 hex under a distinct key
(`target_sha256`, `other_sha256`, `candidate_sha256`), never truncated and
never silently replaced.

STATED LIMITS: links are read per line (a link split across lines is not one);
indented code blocks are read as text; setext headings count as body lines;
only `README.md` and `index.md` are entry documents (`ENTRY_DOCUMENT_NAMES`);
`near-duplicate` compares every pair, quadratic in the corpus's documents; a
missing `title` with no level-1 heading, and a missing `summary`, raise
nothing (data-model.md § Families names no finding for them).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import urllib.parse
from dataclasses import dataclass, field
from itertools import combinations
from operator import mul
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from opendox.corpus_adapter import (
    CORPUS_UNREADABLE,
    DOCUMENT_UNKNOWN,
    CorpusRefused,
    DocumentId,
    Refusal,
    ResolvedCorpus,
)
from opendox.display_profile import NEUTRAL_DISPLAY, STAGE_ROLES
from opendox.doxbench_intake import SETTINGS_DOCUMENTS
from opendox.doxbench_knowledge import embed, tokenize
from opendox.health_contract import (
    ASSISTED,
    AUTO_FIX,
    HUMAN_ONLY,
    OPENDOX,
    STRING_MAX,
    finding_id,
)
from opendox.runtime.local_git_adapter import (
    KINDS_BY_SUFFIX,
    MAX_HEADER_LINES,
    GitCommandFailed,
    GitRunner,
    WorkingTreeCorpus,
    leading_header,
)

__all__ = [
    "BROKEN_LINK", "CHECKS", "DERIVABLE_FRONT_MATTER", "EMPTY_STUB",
    "EMPTY_STUB_CRITERION", "ENGINE_FILES", "ENTRY_DOCUMENT_NAMES",
    "EXCLUDED_PATHS", "FAMILIES", "FAMILY_VERSION", "JUDGED_SUFFIXES",
    "LINK_SUFFIXES", "NEAR_DUPLICATE", "NEAR_DUPLICATE_MEASURED",
    "NEAR_DUPLICATE_THRESHOLD", "ORPHAN", "SEVERITY", "STAGE_LOCATION_MISMATCH",
    "STAGE_WORDS", "STALE_DAYS", "STALE_STUB", "STALE_STUB_CRITERION",
    "STUB_MAX_LINES", "CorpusReading", "UnknownFamily", "broken_links",
    "default_adapter", "derivable_front_matter", "empty_stubs", "near_duplicates",
    "orphans", "read_corpus", "run_families", "similarity",
    "stage_location_mismatches", "stale_stubs",
]

# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------

#: The kinds, each a family's name (FR-010's six, the stubs split in two). None
#: is an engine kind (T041's `ENGINE_KINDS`; the holder's `6069024023` item 1).
BROKEN_LINK = "broken-link"
ORPHAN = "orphan"
NEAR_DUPLICATE = "near-duplicate"
DERIVABLE_FRONT_MATTER = "derivable-front-matter"
STAGE_LOCATION_MISMATCH = "stage-location-mismatch"
EMPTY_STUB = "empty-stub"
STALE_STUB = "stale-stub"

#: Every family's severity (the holder's `6069507373` item 9).
SEVERITY = "warning"

#: A family's own version, riding in `evidence` (OQ-H15-18;
#: contracts/health-finding.md's example).
FAMILY_VERSION = "1"

#: The engine's own files, excluded from the families (OQ-H-15; the holder's
#: `6069507373` item 8): the exceptions file (T054) and the pack manifest
#: (T047).
ENGINE_FILES: tuple[str, ...] = ("health/dispositions.yaml", "health/packs.yaml")

#: What `default_adapter()` leaves out of its listing: openDox's settings
#: documents (`doxbench_intake.SETTINGS_DOCUMENTS`, plan 034 T082) and the
#: engine's files. A link to one is still a link to a corpus file.
EXCLUDED_PATHS: tuple[str, ...] = (*SETTINGS_DOCUMENTS, *ENGINE_FILES)

#: The suffixes of the documents the families judge: the adapter's `text` kind
#: (`local_git_adapter.KINDS_BY_SUFFIX`; the holder's `6069507373` item 1).
#: Configuration (`structured`) draws no family finding.
JUDGED_SUFFIXES: tuple[str, ...] = tuple(sorted(
    suffix for suffix, kind in KINDS_BY_SUFFIX.items() if kind == "text"))

#: The documents whose links are read: Markdown (ruling 4).
LINK_SUFFIXES: tuple[str, ...] = (".markdown", ".md")

#: The entry documents `orphan` exempts, at any depth, by their casefolded
#: name (OQ-H-16; the holder's `6069507373` item 4).
ENTRY_DOCUMENT_NAMES: tuple[str, ...] = ("index.md", "readme.md")

#: The stub criteria, verbatim from data-model.md § Families (ADV-17, ADV-40).
EMPTY_STUB_CRITERION = ("after front matter, the body holds no line that is "
                        "neither blank nor a heading")
STALE_STUB_CRITERION = ("after front matter, the body holds 1 to 3 such lines, "
                        "and the last commit that touched the file is older "
                        "than 180 days at the run's commit")
#: The most body lines a stale stub holds.
STUB_MAX_LINES = 3
#: How old, strictly, a stale stub's last commit is, by committer timestamps
#: (the holder's `6069507373` item 6).
STALE_DAYS = 180
_STALE_SECONDS = STALE_DAYS * 86400

#: THE NEAR-DUPLICATE THRESHOLD (OQ-H-21, measured by T044). `doxbench_knowledge`
#: runs with no binding: in a fresh `-I` interpreter with an empty
#: `OPENDOX_STATE_DIR`, an audit hook saw no file opened and no socket or
#: process event, and `embed()` returned a unit vector. So the score is its
#: cosine, over each document's BODY (the text after its front matter).
#: Every pair of the 20 documents of `health-corpus` and `plain-documents`
#: (190 pairs), scored:
#:
#:   | compared   | planted pair | highest other pair                       |
#:   |------------|--------------|------------------------------------------|
#:   | body       | 0.9933       | 0.7566 (broken-link.md, garden/index.md) |
#:   | whole text | 0.9962       | 0.8749 (broken-link.md, the checklist)   |
#:
#: The body has the wider margin, so the body is compared, and the threshold
#: sits at its midpoint: 0.875, 0.118 from each side.
#: `tests/test_health_families.py` re-measures the table.
NEAR_DUPLICATE_THRESHOLD = 0.875
NEAR_DUPLICATE_MEASURED = (0.9933, 0.7566)


def _stage_words() -> dict[str, str]:
    """Each role directory's name, to its role (R2Q11 (a), as FR-010 words it
    at `spec.md:819-821`; the holder's `6069507373` item 3): the six role keys,
    and each role's `one`, `many` and `short` words in openDox's default
    display table, compared exactly. Never the `label` word, and never a
    host's words."""
    words: dict[str, str] = {}
    for role in STAGE_ROLES:
        declared = NEUTRAL_DISPLAY["stages"][role]
        for word in (role, declared["one"], declared["many"], declared["short"]):
            if words.setdefault(word, role) != role:  # pragma: no cover - table
                raise ValueError(f"the stage word {word!r} names two roles")
    return words


#: A top-level directory's name, to the role it locates.
STAGE_WORDS: Mapping[str, str] = _stage_words()

# The product's own heading and fence patterns (`neutral_projection`'s
# `_ATX_HEADING` and `_FENCE`), with the level captured.
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_SURROGATE = re.compile("[\ud800-\udfff]")
_BACKTICKS = re.compile(r"`+")
_DEFINITION = re.compile(r"^ {0,3}\[([^\]]+)\]:[ \t]*(.*)$")
_TITLE = re.compile(r'(?:"[^"]*"|\'[^\']*\'|\([^()]*\))')


class UnknownFamily(ValueError):
    """A family this module does not carry was asked for, by name."""

    def __init__(self, name: Any) -> None:
        self.family = name
        super().__init__(f"openDox carries no health family named {name!r}; its "
                         f"families are {', '.join(FAMILIES)}")


# ---------------------------------------------------------------------------
# reading the corpus
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Link:
    written: str     # the destination as written
    line: int        # 1-based


@dataclass
class _Document:
    path: str
    raw: bytes
    text: str
    lines: list[str]
    header: dict[str, str]
    body_start: int
    missing: tuple[str, ...]
    links: list[_Link] = field(default_factory=list)


class CorpusReading:
    """One reading of a corpus, shared by the families of one run."""

    def __init__(self, adapter: Any, corpus: ResolvedCorpus) -> None:
        self.adapter = adapter
        self.corpus = corpus
        self.pinned = corpus.ref.revision is not None
        listed = sorted(adapter.list_documents(corpus), key=lambda d: d.key)
        files = {document.key for document in listed}
        files |= {path for path in EXCLUDED_PATHS
                  if path not in files and self._present(path)}
        self.files = frozenset(files)
        self.directories = frozenset(
            posixpath.dirname(path) for path in self._prefixes(files))
        self.documents: dict[str, _Document] = {}
        for identity in listed:
            if identity.key in EXCLUDED_PATHS or _suffix(identity.key) not in JUDGED_SUFFIXES:
                continue
            classification = adapter.classify(corpus, identity)
            if classification.kind is None:
                continue                  # not a document (the projection's rule)
            raw = adapter.read(corpus, identity).content
            self.documents[identity.key] = _read_document(
                identity.key, raw, classification.missing_fields)
        self.judged = tuple(path for path in self.documents if _admitted(path))
        self._git = GitRunner(Path(corpus.location),
                              held_environment=(("GIT_OPTIONAL_LOCKS", "0"),))
        self._inbound: frozenset[str] | None = None
        self._added: dict[str, str | None] = {}

    @staticmethod
    def _prefixes(files: Iterable[str]) -> set[str]:
        out = set()
        for path in files:
            parts = path.split("/")
            out |= {"/".join(parts[:i]) + "/x" for i in range(1, len(parts))}
        return out

    def _present(self, path: str) -> bool:
        try:
            self.adapter.read(self.corpus, DocumentId(corpus=self.corpus.ref.name,
                                                      key=path))
        except CorpusRefused as refused:
            if refused.refusal.kind == DOCUMENT_UNKNOWN:
                return False
            raise
        return True

    def subjects(self, documents: Iterable[str] | None) -> list[_Document]:
        """The judged documents, or those of them `documents` names."""
        if documents is None:
            return [self.documents[path] for path in self.judged]
        named = set(documents)
        return [self.documents[path] for path in self.judged if path in named]

    def exists(self, path: str) -> bool:
        return path == "." or path in self.files or path in self.directories

    # -- git, read only ---------------------------------------------------

    def _out(self, *args: str) -> str:
        try:
            return self._git.out(*args).decode("utf-8", "surrogateescape")
        except GitCommandFailed as failed:
            raise CorpusRefused(Refusal(
                kind=CORPUS_UNREADABLE, subject=self.corpus.location,
                detail=f"a health family's git query failed ({failed})")) from failed

    def _time(self, *args: str) -> int | None:
        """The committer timestamp of the first commit `rev-list` names."""
        for line in self._out("rev-list", "-1", "--format=%H %ct", *args).splitlines():
            if not line.startswith("commit "):
                return int(line.split()[1])
        return None

    def run_time(self) -> int | None:
        if self.corpus.revision is None:
            return None
        return self._time(self.corpus.revision, "--")

    def last_touched(self, path: str) -> int | None:
        if self.corpus.revision is None:
            return None
        return self._time(self.corpus.revision, "--", path)

    def differs_from_head(self, document: _Document) -> bool:
        """Whether the working copy's bytes are not HEAD's: modified, or not
        committed at all (the holder's `6069507373` item 6)."""
        if self.corpus.revision is None:
            return True
        try:
            committed = self.adapter.read(
                self.corpus, DocumentId(corpus=self.corpus.ref.name, key=document.path),
                revision=self.corpus.revision).content
        except CorpusRefused as refused:
            if refused.refusal.kind == DOCUMENT_UNKNOWN:
                return True
            raise
        return committed != document.raw

    def added_by(self, path: str) -> str | None:
        """The commit that first added `path`, at the run's commit, or None
        for a path no commit there holds."""
        if path not in self._added:
            found = None
            if self.corpus.revision is not None:
                listed = self._out("rev-list", "--topo-order", "--reverse",
                                   self.corpus.revision, "--", path).split()
                found = listed[0] if listed else None
            self._added[path] = found
        return self._added[path]

    def descends(self, ancestor: str, descendant: str) -> bool:
        done = self._git.run("merge-base", "--is-ancestor", ancestor, descendant)
        if done.returncode not in (0, 1):
            raise CorpusRefused(Refusal(
                kind=CORPUS_UNREADABLE, subject=self.corpus.location,
                detail=f"a health family's ancestry query failed "
                       f"(merge-base exited {done.returncode})"))
        return done.returncode == 0

    def later(self, left: str, right: str) -> str:
        """The later-committed of two documents (OQ-H-11; the holder's
        `6069507373` item 5): by the commits that first added them, ordered
        by ancestry, a descendant being later; an uncommitted document is
        later than a committed one; a tie, one commit or unrelated commits
        fall to T043's pin, the greater path."""
        a, b = self.added_by(left), self.added_by(right)
        if a is None or b is None or a == b:
            if (a is None) != (b is None):
                return left if a is None else right
            return max(left, right)
        if self.descends(a, b):
            return right
        if self.descends(b, a):
            return left
        return max(left, right)

    def inbound(self) -> frozenset[str]:
        """Every corpus file another document's link resolves to."""
        if self._inbound is None:
            reached = set()
            for document in self.documents.values():
                for link in document.links:
                    for path in _resolutions(document.path, link.written):
                        if path != document.path and path in self.files:
                            reached.add(path)
            self._inbound = frozenset(reached)
        return self._inbound


def read_corpus(adapter: Any, corpus: ResolvedCorpus) -> CorpusReading:
    """The reading the families share, made once per run."""
    return CorpusReading(adapter, corpus)


def default_adapter() -> WorkingTreeCorpus:
    """openDox's standalone corpus as the families read it: read only, with the
    settings documents and the engine files left out of its listing
    (`EXCLUDED_PATHS`; OQ-H-15 through the adapter's `excluded=`)."""
    return WorkingTreeCorpus(write_path=None, excluded=EXCLUDED_PATHS)


def _suffix(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def _admitted(path: str) -> bool:
    """Whether the finding contract admits `path` as a finding's path."""
    try:
        finding_id(identity={}, kind=ORPHAN, pack_id=OPENDOX, path=path)
    except ValueError:
        return False
    return True


def _read_document(path: str, raw: bytes, missing: tuple[str, ...]) -> _Document:
    text = raw.decode("utf-8", "replace")
    lines = text.splitlines()
    header = leading_header(text)
    body_start = 0
    if header:                    # front matter only when it yields a name
        body_start = min(len(lines), MAX_HEADER_LINES)
        for index, line in enumerate(lines[:MAX_HEADER_LINES]):
            if not line.strip():
                body_start = index + 1
                break
    document = _Document(path=path, raw=raw, text=text, lines=lines, header=header,
                         body_start=body_start, missing=tuple(missing))
    if _suffix(path) in LINK_SUFFIXES:
        document.links = _links(lines)
    return document


def _body_lines(document: _Document) -> list[tuple[int, str, bool]]:
    """Each body line with its 1-based number and whether it is code."""
    out = []
    fence: str | None = None
    for index in range(document.body_start, len(document.lines)):
        line = document.lines[index]
        marker = _FENCE.match(line)
        if fence is not None:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            out.append((index + 1, line, True))
            continue
        if marker:
            fence = marker.group(1)
            out.append((index + 1, line, True))
            continue
        out.append((index + 1, line, False))
    return out


def _content_lines(document: _Document) -> int:
    """The body's lines that are neither blank nor a heading (a `#` line in a
    fenced block is code, not a heading)."""
    return sum(1 for _, line, code in _body_lines(document)
               if line.strip() and (code or not _HEADING.match(line)))


def _body(document: _Document) -> str:
    return "\n".join(document.lines[document.body_start:])


# ---------------------------------------------------------------------------
# links (the holder's `6069507373` item 4)
# ---------------------------------------------------------------------------

def _blank_code_spans(line: str) -> str:
    """`line` with each inline code span blanked out."""
    out = list(line)
    position = 0
    while True:
        opening = _BACKTICKS.search(line, position)
        if opening is None:
            return "".join(out)
        width = len(opening.group())
        closing = opening.end()
        while True:
            run = _BACKTICKS.search(line, closing)
            if run is None or len(run.group()) == width:
                break
            closing = run.end()
        if run is None:
            position = opening.end()
            continue
        out[opening.start():run.end()] = " " * (run.end() - opening.start())
        position = run.end()


def _destination(rest: str, *, inline: bool) -> tuple[str, str] | None:
    """A link destination at the start of `rest`, and what follows it: one in
    angle brackets, or a run without spaces or control characters (balanced
    parentheses, for an inline link)."""
    if rest.startswith("<"):
        end = rest.find(">", 1)
        if end < 0 or "<" in rest[1:end]:
            return None
        return rest[1:end], rest[end + 1:]
    depth = 0
    for index, char in enumerate(rest):
        if char in " \t" or ord(char) < 0x20 or ord(char) == 0x7f:
            return rest[:index], rest[index:]
        if inline and char == "(":
            depth += 1
        elif inline and char == ")":
            if depth == 0:
                return rest[:index], rest[index:]
            depth -= 1
    return (rest, "") if not inline else None


def _inline_links(line: str) -> list[str]:
    found = []
    index = 0
    while True:
        start = line.find("[", index)
        if start < 0:
            return found
        index = start + 1
        if start and line[start - 1] == "\\":
            continue
        depth, close = 0, -1
        for position in range(start + 1, len(line)):
            if line[position] == "\\":
                continue
            if line[position] == "[":
                depth += 1
            elif line[position] == "]":
                if depth == 0:
                    close = position
                    break
                depth -= 1
        if close < 0 or line[close + 1:close + 2] != "(":
            continue
        parsed = _destination(line[close + 2:].lstrip(" \t"), inline=True)
        if parsed is None:
            continue
        written, after = parsed
        after = after.lstrip(" \t")
        title = _TITLE.match(after)
        if title:
            after = after[title.end():].lstrip(" \t")
        if not after.startswith(")"):
            continue
        found.append(written)
        index = close + 1


def _definition(line: str) -> str | None:
    """A reference definition's destination (`[label]: target "title"`), or
    None. A footnote (`[^1]: ...`) is no link."""
    match = _DEFINITION.match(line)
    if match is None or match.group(1).startswith("^") or not match.group(1).strip():
        return None
    parsed = _destination(match.group(2), inline=False)
    if parsed is None or not parsed[0]:
        return None
    written, after = parsed
    after = after.strip(" \t")
    if after and not _TITLE.fullmatch(after):
        return None
    return written


def _links(lines: list[str]) -> list[_Link]:
    """Every inline link and reference definition outside fenced code and
    inline code, in order. A definition counts only where a definition may
    stand: after a blank line, a heading or another definition, or first."""
    found: list[_Link] = []
    fence: str | None = None
    previous_open = True          # a definition may stand on the next line
    for index, line in enumerate(lines):
        marker = _FENCE.match(line)
        if fence is not None:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            previous_open = False
            continue
        if marker:
            fence = marker.group(1)
            previous_open = False
            continue
        visible = _blank_code_spans(line)
        definition = _definition(visible) if previous_open else None
        if definition is not None:
            found.append(_Link(definition, index + 1))
            previous_open = True
            continue
        found += [_Link(written, index + 1) for written in _inline_links(visible)]
        previous_open = not line.strip() or bool(_HEADING.match(line))
    return found


def _judged_target(written: str) -> str | None:
    """The path part of a target the families judge, or None: a target with a
    URI scheme, one starting `//`, a fragment alone, or nothing, is not
    judged. A `#fragment` and a `?query` are stripped."""
    if not written or written.startswith(("#", "//")) or _SCHEME.match(written):
        return None
    cut = min((i for i in (written.find("#"), written.find("?")) if i >= 0),
              default=len(written))
    return written[:cut] or None


def _resolve(base_document: str, target: str) -> str:
    """`target` against the linking document's directory, or the corpus root
    for a leading `/`, normalized. A result starting `..` left the corpus."""
    base = "" if target.startswith("/") else posixpath.dirname(base_document)
    return posixpath.normpath(posixpath.join(base, target.lstrip("/")))


def _resolutions(base_document: str, written: str) -> list[str]:
    """The paths a target may name: as written and, percent-decoded, as a
    renderer would read it."""
    target = _judged_target(written)
    if target is None:
        return []
    forms = [target]
    decoded = urllib.parse.unquote(target)
    if decoded != target:
        forms.append(decoded)
    return [_resolve(base_document, form) for form in forms]


def _outside(path: str) -> bool:
    return path == ".." or path.startswith("../")


# ---------------------------------------------------------------------------
# the findings' strings (the holder's `6069507373` item 7, `6072086385` item 4)
# ---------------------------------------------------------------------------

def _unsafe(value: str) -> bool:
    return (len(value) > STRING_MAX or "\x00" in value
            or _SURROGATE.search(value) is not None)


def _bounded(key: str, value: str) -> dict[str, str]:
    """`{key: value}`, or `{key_sha256: <its SHA-256 hex>}` for a value over
    `STRING_MAX` characters or holding U+0000 or a lone surrogate. Never
    truncated."""
    if _unsafe(value):
        digest = hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()
        return {f"{key}_sha256": digest}
    return {key: value}


def _finding(kind: str, path: str, resolution_class: str, message: str, *,
             identity: dict[str, str] | None = None,
             evidence: dict[str, Any] | None = None,
             locator: dict[str, Any] | None = None) -> dict[str, Any]:
    finding: dict[str, Any] = {"kind": kind, "path": path, "identity": identity or {}}
    if locator:
        finding["locator"] = locator
    finding.update(severity=SEVERITY, resolution_class=resolution_class,
                   message=message,
                   evidence={"family_version": FAMILY_VERSION, **(evidence or {})})
    return finding


def _line(number: int) -> dict[str, int]:
    return {"line_start": number, "line_end": number}


# ---------------------------------------------------------------------------
# the families
# ---------------------------------------------------------------------------

def broken_links(reading: CorpusReading,
                 documents: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """`broken-link`: a link whose target is in no corpus file or folder. ONE
    finding per target as written in a document, its identity that target
    (N-13), its locator the first such link's line. A target exactly one
    corpus file's name answers moved (`auto-fix`, OQ-H-10); an ambiguous or
    absent one, or one outside the corpus, is `human-only`."""
    out = []
    for document in reading.subjects(documents):
        seen: set[str] = set()
        for link in document.links:
            if link.written in seen:
                continue
            seen.add(link.written)
            paths = _resolutions(document.path, link.written)
            if not paths or any(reading.exists(p) for p in paths if not _outside(p)):
                continue
            evidence: dict[str, Any]
            if all(_outside(p) for p in paths):
                cls, evidence = HUMAN_ONLY, {"cause": "outside-corpus"}
                message = "link target lies outside the corpus"
            else:
                names = {posixpath.basename(p) for p in paths if not _outside(p)}
                candidates = sorted(f for f in reading.files
                                    if posixpath.basename(f) in names)
                if len(candidates) == 1:
                    cls = AUTO_FIX
                    evidence = {"cause": "moved", **_bounded("candidate", candidates[0])}
                    message = ("link target does not exist; a unique file of that "
                               "name exists elsewhere")
                elif candidates:
                    cls = HUMAN_ONLY
                    evidence = {"cause": "ambiguous", "candidate_count": len(candidates)}
                    message = ("link target does not exist; several files of that "
                               "name exist elsewhere")
                else:
                    cls, evidence = HUMAN_ONLY, {"cause": "absent"}
                    message = "link target does not exist anywhere in the corpus"
            locator: dict[str, Any] = _line(link.line)
            if not _unsafe(link.written):
                locator["target"] = link.written
            out.append(_finding(BROKEN_LINK, document.path, cls, message,
                                identity=_bounded("target", link.written),
                                evidence=evidence, locator=locator))
    return out


def orphans(reading: CorpusReading,
            documents: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """`orphan`: a document no OTHER document links to, README and index
    documents exempt at any depth, by casefolded name (OQ-H-16). One per
    document, identity `{}`, `human-only` (OQ-H-8)."""
    inbound = reading.inbound()
    return [_finding(ORPHAN, document.path, HUMAN_ONLY,
                     "no other document links to this document")
            for document in reading.subjects(documents)
            if posixpath.basename(document.path).casefold() not in ENTRY_DOCUMENT_NAMES
            and document.path not in inbound]


def empty_stubs(reading: CorpusReading,
                documents: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """`empty-stub`: `EMPTY_STUB_CRITERION`. One per document, identity `{}`,
    `assisted` (14.6; ADV-17)."""
    return [_finding(EMPTY_STUB, document.path, ASSISTED,
                     "the document has no body after its front matter")
            for document in reading.subjects(documents)
            if _content_lines(document) == 0]


def stale_stubs(reading: CorpusReading,
                documents: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """`stale-stub`: `STALE_STUB_CRITERION`, by committer timestamps: the
    file's last-touching commit against the run's commit, HEAD in a
    working-state run, where a modified or uncommitted file is never stale.
    One per document, identity `{}`, `human-only` (OQ-H-8)."""
    out = []
    run_time = None
    for document in reading.subjects(documents):
        lines = _content_lines(document)
        if not 1 <= lines <= STUB_MAX_LINES:
            continue
        if not reading.pinned and reading.differs_from_head(document):
            continue
        run_time = reading.run_time() if run_time is None else run_time
        touched = reading.last_touched(document.path)
        if run_time is None or touched is None:
            continue
        if run_time - touched > _STALE_SECONDS:
            out.append(_finding(
                STALE_STUB, document.path, HUMAN_ONLY,
                f"the document is a stub untouched for more than {STALE_DAYS} days",
                evidence={"body_lines": lines}))
    return out


def derivable_front_matter(reading: CorpusReading, documents: Iterable[str] | None = None
                           ) -> list[dict[str, Any]]:
    """`derivable-front-matter`: a `title` the adapter reports missing or
    empty, with a level-1 heading in the body to take it from (the holder's
    `6069507373` item 2). One per document, identity `{}`, `auto-fix`, the
    heading's line as its locator. A missing `title` with no such heading, and
    a missing `summary`, raise nothing."""
    out = []
    for document in reading.subjects(documents):
        if "title" not in document.missing:
            continue
        for number, line, code in _body_lines(document):
            heading = None if code else _HEADING.match(line)
            if heading and len(heading.group(1)) == 1 and (heading.group(2) or "").strip():
                out.append(_finding(
                    DERIVABLE_FRONT_MATTER, document.path, AUTO_FIX,
                    "the document has no title; one can be taken from its first "
                    "level-1 heading",
                    evidence={"field": "title"}, locator=_line(number)))
                break
    return out


def stage_location_mismatches(reading: CorpusReading, documents: Iterable[str] | None = None
                              ) -> list[dict[str, Any]]:
    """`stage-location-mismatch`: a document in a top-level role directory
    (`STAGE_WORDS`) whose `stage:` names another of the six role keys (R2Q11
    (a)). A document outside such a directory, or whose `stage:` is missing or
    outside the six, is never flagged. One per document, identity `{}`,
    `auto-fix`, the `stage:` line as its locator."""
    out = []
    for document in reading.subjects(documents):
        top, separator, _ = document.path.partition("/")
        role = STAGE_WORDS.get(top) if separator else None
        declared = document.header.get("stage")
        if role is None or declared not in STAGE_ROLES or declared == role:
            continue
        number = max(index + 1 for index, line in enumerate(document.lines[:MAX_HEADER_LINES])
                     if line.partition(":")[0].strip() == "stage")
        out.append(_finding(
            STAGE_LOCATION_MISMATCH, document.path, AUTO_FIX,
            "the declared stage disagrees with the role of the top-level "
            "directory the document sits in",
            evidence={"declared_stage": declared, "directory_role": role},
            locator=_line(number)))
    return out


def _vector(text: str) -> tuple[float, ...]:
    return embed(tokenize(text))


def similarity(left: str, right: str) -> float:
    """The near-duplicate score of two documents' texts: the cosine of
    `doxbench_knowledge`'s embedding of each one's body."""
    a = _vector(_body(_read_document("a", left.encode("utf-8"), ())))
    b = _vector(_body(_read_document("b", right.encode("utf-8"), ())))
    return sum(map(mul, a, b))


def near_duplicates(reading: CorpusReading,
                    documents: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """`near-duplicate`: a pair whose bodies score at least
    `NEAR_DUPLICATE_THRESHOLD`, raised ONCE, on the later-committed document
    (`CorpusReading.later`), its identity the other document's path (N-13),
    `assisted` (14.6)."""
    vectors = {}
    for path in reading.judged:
        vector = _vector(_body(reading.documents[path]))
        if any(vector):
            vectors[path] = vector
    named = None if documents is None else set(documents)
    out = []
    for left, right in combinations(sorted(vectors), 2):
        if named is not None and left not in named and right not in named:
            continue
        if sum(map(mul, vectors[left], vectors[right])) < NEAR_DUPLICATE_THRESHOLD:
            continue
        path = reading.later(left, right)
        if named is not None and path not in named:
            continue
        other = right if path == left else left
        out.append(_finding(NEAR_DUPLICATE, path, ASSISTED,
                            "the document nearly repeats another document of the corpus",
                            identity=_bounded("other", other),
                            evidence=_bounded("other", other)))
    return out


#: Each family's check, by its kind, in FR-010's order.
CHECKS: Mapping[str, Callable[..., list[dict[str, Any]]]] = {
    BROKEN_LINK: broken_links,
    ORPHAN: orphans,
    NEAR_DUPLICATE: near_duplicates,
    DERIVABLE_FRONT_MATTER: derivable_front_matter,
    STAGE_LOCATION_MISMATCH: stage_location_mismatches,
    EMPTY_STUB: empty_stubs,
    STALE_STUB: stale_stubs,
}

#: The families' kind names, a tuple (for T052's seam and T046's run).
FAMILIES: tuple[str, ...] = tuple(CHECKS)


def run_families(adapter: Any, corpus: ResolvedCorpus, *,
                 families: Iterable[str] | None = None,
                 documents: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Run the selected families over `corpus` (this module's docstring)."""
    if isinstance(documents, (str, bytes)):
        raise TypeError("documents names corpus-relative paths, not one string")
    selected = list(FAMILIES) if families is None else list(dict.fromkeys(families))
    for name in selected:
        if name not in CHECKS:
            raise UnknownFamily(name)
    named = None if documents is None else tuple(documents)
    reading = read_corpus(adapter, corpus)
    found: list[dict[str, Any]] = []
    for name in selected:
        found += CHECKS[name](reading, named)
    return sorted(found, key=lambda f: (f["path"], f["kind"],
                                        json.dumps(f["identity"], sort_keys=True)))
