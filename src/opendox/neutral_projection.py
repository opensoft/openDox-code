"""openDox's OWN small neutral projection: a plain corpus, read through
`CorpusAdapter`, written as the neutral snapshot (plan 034 T054).

WHAT IT REALIZES. #1144's boxes 5.1, 5.2 and 5.3, as plan 034's T054 reads
them.

* 5.1. This is new code over the `CorpusAdapter` protocol, written to openDox's
  own needs. It is not openXdox's generator re-expressed, and it imports
  nothing of openXdox's or openxFactory's.
* 5.2. It reads whatever adapter the home-corpus seam hands it. Standalone,
  that is openDox's own default, `local_git_adapter.WorkingTreeCorpus`, a
  `LocalGitCorpus` (T022). `default_generator` makes that call.
* 5.3. It writes T053's neutral snapshot contract, `opendox-snapshot`
  (openDox-spec's `contracts/schemas/opendox-snapshot.schema.yaml`; R1Q11
  (a), openxFactory#656 comment `5850003126`). Its values are the six station
  role keys and the four candidate states, and `display_profile
  .SNAPSHOT_VALUES` defaults to those same values, so openDox's views place
  every card by them and render the six words.

WHERE A DOCUMENT LANDS (RULED R1Q13 (a) with (c), same comment). A document
names its station with the neutral `stage:` key of its leading `Name: value`
header, which is `local_git_adapter.leading_header`'s block. That is the same
reader the default adapter's `classify` uses. The value must be one of the six
station role keys, `display_profile.STAGE_ROLES`. A document that declares no
`stage:` is a source. A `stage:` value outside the six, the empty value
included, is not a declaration either. The document is read as a source, and
the projection reports it, naming the document, the value and the six keys. So
no other value can reach the snapshot, whose schema admits only the six.

THE TOPIC RULE. Every document carries `topics`. A document that declares a
`topics:` header carries the ones it lists, split on commas, with whitespace
collapsed and letters case-folded. A document that declares none carries the
words of its NAME, plus the words of the name of every other document it
MENTIONS. Its name is its `title:`, else its first `#` heading, else its file
name without the suffix. It mentions another document where its text holds
that document's name, or that document's file name, as a run of whole words.
A word is a run of three or more letters, case-folded, that is not one of
`STOPWORDS`. So the rule needs no front matter at all. AT-R1's repository (b)
(quickstart.md § 2) is three notes named by their headings, and a note that
mentions another shares that note's name as a topic. An entry the adapter
cannot classify is listed but never read, so it carries no topic and nothing
mentions it.

GROUPS (the grouping station). A group forms wherever two or more sources
share a topic. Topics that the same sources share form one group, named by
those topics. A document that declares `stage: grouping` is a group of its
own: it gathers itself and every source that shares one of its topics. Each
group holds one edge per member document, naming the topics that matched.

THE OTHER STATIONS. A declared candidate is a candidate. It is `unselected`,
because only an act selects, declines or replaces one, and it is claimed by
every group it shares a topic with. A declared selection is a selection, and
a declared submission or completion is a changes entry, `active` or
`archived` as `display_profile.STAGE_FIELDS` declares them. Each of the three
lists the document as its file. So a plain repository fills every station its
documents name, and no other.

TITLE AND SUMMARY are copied from the header EXACTLY as the header gives them,
an empty value included, and `null` only where the document does not give the
key. They are never coerced, and no document is left out for lacking them
(the holder's ruling on T051: the malformed fixture's empty `title:` reaches
the snapshot and fails `title-and-summary-are-text`).

DETERMINISTIC. The same tree at the same anchors answers the same snapshot.
Every list is ordered by path or sorted, and nothing reads the clock.
`generation.source_revision` is the revision the caller pins, else the one the
corpus resolved. `generation.generated_at` is recorded only as the caller
hands it, and `default_generator` hands the source revision's own commit date.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from opendox import generator_seam
from opendox.corpus_adapter import CorpusAdapter, ResolvedCorpus
from opendox.display_profile import STAGE_FIELDS, STAGE_ROLES
from opendox.path_slug import slug
from opendox.runtime.local_git_adapter import leading_header

__all__ = [
    "GENERATOR_VERSION",
    "Notice",
    "Projection",
    "ProjectionRefused",
    "SCHEMA_VERSION",
    "STOPWORDS",
    "project",
]

#: The neutral contract's version, which its schema holds at `const: 1`.
SCHEMA_VERSION = 1

#: This projection's own name and version, written to `generation`.
GENERATOR_VERSION = "opendox-neutral-1"

#: The neutral header keys this projection reads. `title` and `summary` are the
#: default adapter's small field set (`local_git_adapter.NEUTRAL_FIELDS`).
STAGE_KEY = "stage"
TOPICS_KEY = "topics"
TITLE_KEY = "title"
SUMMARY_KEY = "summary"

#: The station a document lands in when it declares none (R1Q13 (c)).
SOURCE = "source"
GROUPING = "grouping"
CANDIDATE = "candidate"
SELECTION = "selection"

#: A candidate's state until an act selects, declines or replaces it.
UNSELECTED = "unselected"

#: `changes[].status` for the two stations that share the `changes` section,
#: read off `display_profile.STAGE_FIELDS` rather than restated.
CHANGE_STATUS: dict[str, str] = {
    role: status for role, _section, status in STAGE_FIELDS if status}

#: Common English words the topic rule never takes as a topic. Words shorter
#: than three letters are never topics anyway, so none of those is listed.
STOPWORDS: frozenset[str] = frozenset("""
    about above across actually after again against all along already also
    always among and another any are around back been before behind being
    below beside between beyond both but can cannot could did does doing done
    down during each either else even ever every few for from further get
    gets got had has have having her here hers herself him himself his how
    inside into its itself just last less let like made make many may maybe
    might more most much must myself near neither never new next none nor
    not nothing now off often once one only onto other others ought our ours
    ourselves out outside over own per perhaps quite rather really same say
    see she should since some still such than that the their theirs them
    themselves then there these they this those though three through thus
    till too toward towards two under until upon use very via want was way
    well were what whatever when where whether which while who whom whose why
    will with within without would yet you your yours yourself yourselves
""".split())

#: A run of letters or digits: what the topic rule reads as one token.
_TOKEN = re.compile(r"[^\W_]+")

#: An ATX heading (`# Roadmap`, `## Budget ##`), its text in group 1.
_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")

#: A fenced code block's opening or closing line. A `#` line inside one is code.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

#: The characters the neutral schema refuses in a path or a topic
#: (`path-is-repo-relative`, `topic-is-trimmed-text`).
_CONTROL = re.compile("[\u0000-\u001f\u007f-\u009f]")


class ProjectionRefused(generator_seam.GeneratorSeamError):
    """The projection cannot write a snapshot the neutral contract admits.

    A subclass of the generator seam's own refusal, so a verb that reports the
    seam's refusals reports this one too."""


@dataclass(frozen=True)
class Notice:
    """One thing the projection read otherwise than the document declared it.

    `document` is the document's path as the adapter lists it. The generate
    verbs report each notice, and the snapshot never carries one."""

    document: str
    message: str

    def __str__(self) -> str:
        return f"{self.document}: {self.message}"


@dataclass(frozen=True)
class Projection:
    """The neutral snapshot, and what the projection had to report making it."""

    snapshot: dict[str, Any]
    notices: tuple[Notice, ...]


@dataclass
class _Document:
    """One listed document, as the projection reads it."""

    path: str
    stage: str = SOURCE
    title: str | None = None
    summary: str | None = None
    topics: tuple[str, ...] = ()
    read: bool = False
    name: str = ""
    tokens: tuple[str, ...] = ()
    declared_topics: tuple[str, ...] | None = None

    @property
    def stem(self) -> str:
        return PurePosixPath(self.path).stem or self.path


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN.findall(text))


def _is_word(token: str) -> bool:
    return len(token) >= 3 and token.isalpha() and token not in STOPWORDS


def _words(text: str) -> set[str]:
    return {token for token in _tokens(text) if _is_word(token)}


def _first_heading(text: str) -> str | None:
    """The text of the first ATX heading outside a fenced code block."""
    fence: str | None = None
    for line in text.splitlines():
        marker = _FENCE.match(line)
        if fence is not None:
            if (marker and marker.group(1)[0] == fence[0]
                    and len(marker.group(1)) >= len(fence)):
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            continue
        heading = _ATX_HEADING.match(line)
        if heading and (heading.group(1) or "").strip():
            return heading.group(1).strip()
    return None


def _declared_topics(value: str) -> tuple[str, ...]:
    """The topics a `topics:` header lists: comma-separated, each with its
    whitespace collapsed and its letters case-folded, each once, sorted. A
    topic holding a control character is dropped, since no snapshot can carry
    it (`topic-is-trimmed-text`)."""
    topics: set[str] = set()
    for part in value.split(","):
        topic = " ".join(part.replace("﻿", " ").split()).casefold()
        if topic and not _CONTROL.search(topic):
            topics.add(topic)
    return tuple(sorted(topics))


def _unwritable(path: str) -> str | None:
    """Why the neutral schema could not carry `path`, or None where it can.

    The schema's `path-is-repo-relative` rule, stated as reasons: git can list
    a path that holds any of these, and the snapshot must not."""
    if not path:
        return "it is empty"
    if path.startswith("/"):
        return "it starts with a slash"
    if re.match(r"[A-Za-z]:", path):
        return "it starts with a drive letter and a colon"
    if "\\" in path:
        return "it holds a backslash"
    if _CONTROL.search(path):
        return "it holds a control character"
    if ".." in path.split("/"):
        return "it has a .. segment"
    if any("\ud800" <= char <= "\udfff" for char in path):
        return "its name is not valid UTF-8"
    return None


def _unique(base: str, taken: set[str]) -> str:
    """`base`, or `base-2`, `base-3`, ... where an earlier entry holds it."""
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    taken.add(candidate)
    return candidate


def _read_documents(adapter: CorpusAdapter, corpus: ResolvedCorpus,
                    notices: list[Notice]) -> list[_Document]:
    """Every listed document the snapshot can carry, in path order, with its
    station, its two copied fields, its name and its tokens."""
    stations = set(STAGE_ROLES)
    documents: list[_Document] = []
    listed = sorted(adapter.list_documents(corpus), key=lambda d: d.key)
    for identity in listed:
        reason = _unwritable(identity.key)
        if reason is not None:
            # NAMED BY ITS repr: the path is one no snapshot can carry, and a
            # control character or a lone surrogate in it must not reach a
            # terminal raw either.
            notices.append(Notice(
                repr(identity.key),
                f"is listed, but the neutral snapshot cannot carry its path "
                f"({reason}), so it is left out"))
            continue
        document = _Document(path=identity.key)
        documents.append(document)
        if adapter.classify(corpus, identity).kind is None:
            # UNCLASSIFIABLE: listed, never read. It is a source with nothing
            # to copy, no topic, and no name another document can mention.
            continue
        text = adapter.read(corpus, identity).content.decode("utf-8", "replace")
        header = leading_header(text)
        document.read = True
        document.title = header.get(TITLE_KEY)
        document.summary = header.get(SUMMARY_KEY)
        declared = header.get(STAGE_KEY)
        if declared is not None:
            if declared in stations:
                document.stage = declared
            else:
                notices.append(Notice(
                    identity.key,
                    f"its stage: value {declared!r} is not one of the six "
                    f"station role keys ({', '.join(STAGE_ROLES)}), so it is "
                    "not a declaration; the document is read as a source"))
        listed_topics = _declared_topics(header.get(TOPICS_KEY) or "")
        document.declared_topics = listed_topics or None
        document.name = (document.title or _first_heading(text)
                         or document.stem)
        document.tokens = _tokens(text)
    return documents


def _assign_topics(documents: list[_Document]) -> None:
    """The topic rule (this module's docstring), over the documents read."""
    read = [document for document in documents if document.read]
    own = [_words(document.name) for document in read]
    # Each name is looked for by its first WORD, at that word's offset, so a
    # text is scanned once and a common short token ("the") costs nothing.
    by_first_word: dict[str, list[tuple[tuple[str, ...], int, int]]] = {}
    for index, document in enumerate(read):
        for alias in {_tokens(document.name), _tokens(document.stem)}:
            # A name with no word in it contributes no topic, so it is not
            # looked for: `a.md` would otherwise be mentioned by every "a".
            offset = next((at for at, token in enumerate(alias)
                           if _is_word(token)), None)
            if offset is not None:
                by_first_word.setdefault(alias[offset], []).append(
                    (alias, offset, index))
    for index, document in enumerate(read):
        if document.declared_topics is not None:
            document.topics = document.declared_topics
            continue
        mentioned: set[int] = set()
        tokens = document.tokens
        for position, token in enumerate(tokens):
            for alias, offset, other in by_first_word.get(token, ()):
                start = position - offset
                if (other != index and other not in mentioned and start >= 0
                        and tokens[start:start + len(alias)] == alias):
                    mentioned.add(other)
        topics = set(own[index])
        for other in mentioned:
            topics |= own[other]
        document.topics = tuple(sorted(topics))


def _groups(documents: list[_Document], notices: list[Notice]) -> list[dict]:
    """The grouping station: each declared group, then each derived one."""
    sources = [document for document in documents if document.stage == SOURCE]
    taken: set[str] = set()
    clusters: list[dict] = []
    for document in documents:
        if document.stage != GROUPING:
            continue
        if not document.topics:
            notices.append(Notice(
                document.path,
                "declares stage grouping but carries no topic, so no group "
                "forms around it"))
            continue
        mine = set(document.topics)
        members = [document] + [source for source in sources
                                if mine & set(source.topics)]
        members.sort(key=lambda member: member.path)
        clusters.append({
            "id": _unique(slug(document.stem), taken),
            "name": document.name,
            "topics": list(document.topics),
            "document_edges": [
                {"document": member.path,
                 "matched_topics": sorted(mine & set(member.topics))}
                for member in members],
        })
    carriers: dict[str, list[str]] = {}
    for source in sources:
        for topic in source.topics:
            carriers.setdefault(topic, []).append(source.path)
    shared: dict[tuple[str, ...], list[str]] = {}
    for topic, paths in carriers.items():
        if len(paths) >= 2:
            shared.setdefault(tuple(paths), []).append(topic)
    for topics, paths in sorted((tuple(sorted(topics)), paths)
                                for paths, topics in shared.items()):
        name = " · ".join(topics)
        clusters.append({
            "id": _unique(slug(name), taken),
            "name": name,
            "topics": list(topics),
            "document_edges": [
                {"document": path, "matched_topics": list(topics)}
                for path in sorted(paths)],
        })
    return clusters


def project(adapter: CorpusAdapter, corpus: ResolvedCorpus, repository: str,
            *, source_revision: str | None = None,
            generated_at: str | None = None) -> Projection:
    """The neutral snapshot of `corpus`, read through `adapter`.

    `source_revision`, where given, is recorded verbatim as the determinism
    anchor; otherwise the revision `corpus` was resolved at is. With neither,
    the projection refuses, since the contract requires an anchor.
    `generated_at`, where given, is recorded verbatim, and it is otherwise
    absent. `repository` is recorded as given."""
    revision = source_revision if source_revision is not None else corpus.revision
    if revision is None:
        raise ProjectionRefused(
            f"the neutral snapshot of {repository!r} needs a source revision, "
            f"and none was given, and the corpus at {corpus.location!r} "
            "resolved to none (a repository with no commit yet). Commit the "
            "documents, or pass the revision to anchor them to.")
    notices: list[Notice] = []
    documents = _read_documents(adapter, corpus, notices)
    _assign_topics(documents)
    clusters = _groups(documents, notices)

    possibles: list[dict] = []
    staged_topics: list[dict] = []
    changes: list[dict] = []
    taken: dict[str, set[str]] = {"possibles": set(), "staged_topics": set(),
                                  "changes": set()}
    for document in documents:
        if document.stage == CANDIDATE:
            mine = set(document.topics)
            candidate: dict[str, Any] = {
                "id": _unique(slug(document.stem), taken["possibles"]),
                "title": document.name,
            }
            if document.summary:
                candidate["claim"] = document.summary
            candidate["state"] = UNSELECTED
            candidate["claiming_clusters"] = [
                cluster["id"] for cluster in clusters
                if mine & set(cluster["topics"])]
            possibles.append(candidate)
        elif document.stage == SELECTION:
            staged_topics.append({
                "staging_id": _unique(slug(document.stem),
                                      taken["staged_topics"]),
                "files": [document.path],
            })
        elif document.stage in CHANGE_STATUS:
            changes.append({
                "id": _unique(slug(document.stem), taken["changes"]),
                "status": CHANGE_STATUS[document.stage],
                "files": [document.path],
            })

    counts = Counter(topic for document in documents
                     for topic in document.topics)
    generation: dict[str, Any] = {"source_revision": revision}
    if generated_at is not None:
        generation["generated_at"] = generated_at
    generation["generator_version"] = GENERATOR_VERSION
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": generator_seam.NEUTRAL_SNAPSHOT_KIND,
        "repository": repository,
        "generation": generation,
        "documents": [
            {"id": document.path, "path": document.path,
             "stage": document.stage, "title": document.title,
             "summary": document.summary, "topics": list(document.topics)}
            for document in documents],
        "clusters": clusters,
        "possibles": possibles,
        "staged_topics": staged_topics,
        "changes": changes,
        "keyword_index": [
            {"keyword": keyword, "declared_doc_count": counts[keyword]}
            for keyword in sorted(counts)],
    }
    return Projection(snapshot=snapshot, notices=tuple(notices))
