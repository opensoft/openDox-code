"""openDox's own small neutral projection, held to plan 034's T054.

T054 realizes #1144's 5.1, 5.2 and 5.3: `opendox.neutral_projection`, new code
over `CorpusAdapter`, bound to `LocalGitCorpus` through the home-corpus seam,
writing T053's neutral snapshot. Its falsifier, from plan 034's tasks.md:

    an in-process test that the projection over T050's fixture, with neither
    sibling importable, validates against T053's schema and carries none of
    F5.3's declared words; the topic-rule test over a copy of repository (b);
    and a test that a `stage:` value outside the six is reported and read as a
    source.

Those are the first three cases below, in that order. F5.3 itself runs
`python -m opendox.cli generate`, whose verb reaches the consumer's generator
until T055 routes it, so T056 and T063 quote it.

THE SCHEMA. `tests/fixtures/opendox-snapshot.schema.yaml` is openDox-spec's
neutral snapshot contract, copied byte for byte from openDox-spec#16 at
`cd49eb25` (T053), and held here to that file's sha256. T057 ships the packaged
copy, and that copy replaces this one when it lands. The evaluator below is a
port of openDox-spec's own (`tests/test_opendox_snapshot_contract.py` there):
the JSON Schema keywords the contract uses, as draft 2020-12 defines them, and
its seven reference rules. The leg's test extra installs no `jsonschema`, so
none is imported.

WHAT ELSE IT HOLDS.

1. THE HOLDER'S RULE ON T051: the projection copies `title` and `summary`
   without coercing or excluding them, so T051's malformed fixture reaches the
   snapshot and breaks exactly its `EXPECTED_RULE`.
2. WHAT A DOCUMENT IS: an entry the adapter classifies. One it cannot classify
   is left out (the holder's ruling on T054), and so is a path the schema
   cannot carry, which is reported.
3. THE STATIONS: a declared group gathers the sources that share its topics,
   one edge per document; candidates are claimed by the groups they share a
   topic with; ids are unique within each section.
4. THE ANCHORS: `source_revision` is the corpus HEAD unless pinned,
   `generated_at` is that commit's own date unless given, and the same tree
   answers the same bytes.
5. THE FIELD SET: openDox's default adapter obliges `title` and `summary`
   (R1Q13 (a)), so `authoring.required_header_fields()` answers them through
   the entry point, and a document without them is still read.
   (5a) THE SCAFFOLD. Following the holder's decision, what openDox's own
   `create` writes carries that field set where the adapter reads it, so
   `agent_capture` accepts it and the projection keeps its title and summary.
   Where the corpus obliges neither field, the governed layout is unchanged.
6. THE VALUES: `SNAPSHOT_VALUES`' defaults, in Python and in `display.js`, are
   the neutral schema's values, so openDox's views match openDox's snapshot.
   And the wheel's grouping tile counts a group's edges where the group carries
   no tally, as the neutral snapshot's groups do not (the holder's ruling:
   the schema is not widened).
7. NO REACH: the projection imports with every sibling blocked and pulls in no
   third-party module.

`--noconftest` SAFE. The autouse fixture saves and restores the three
registries an entry point writes, so no case leaves a registration behind.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple

import pytest

from opendox import (
    authoring,
    corpus_adapter,
    default_generator,
    display_profile,
    domain_profile,
)
from opendox import generator_seam as gs
from opendox import neutral_projection as projection
from opendox.boundary import HUMAN, OutputBoundary
from opendox.runtime import local_git_adapter as lga

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = ROOT / "tests" / "fixtures"
PLAIN = FIXTURES / "plain-documents"      # T050, openDox-code#53
MALFORMED = FIXTURES / "malformed"        # T051, openDox-code#56
SCHEMA_PATH = FIXTURES / "opendox-snapshot.schema.yaml"
DISPLAY_JS = SRC / "opendox" / "web" / "views" / "display.js"
WHEEL_MODEL_JS = SRC / "opendox" / "web" / "views" / "wheel-model.js"
NODE = shutil.which("node")

#: The sha256 of `contracts/schemas/opendox-snapshot.schema.yaml` at
#: openDox-spec#16's head, `cd49eb25` (T053; its PR records the same digest).
SCHEMA_SHA256 = "f9e3e111af1d4bd4c377c933027d81b582ae2b0a395b66f4e4621992454a584a"

#: The four packages a neutral openDox must import without (#1144's F2.1).
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: F5.3's declared vocabulary, verbatim from #1144's `tasks.md`.
F5_3_WORDS = ("brainstorm", "staged", "draft", "ratified", "standard",
              "superseded", "retired", "record", "openspec", "proposal.md",
              "tasks.md", "design.md", "added requirements",
              "modified requirements")

#: AT-R1's repository (b), byte for byte as plan 034's quickstart.md § 2
#: writes it with `printf`: ordinary Markdown with no front matter at all.
REPOSITORY_B = {
    "roadmap.md": "# Roadmap\n\nThe roadmap links to the [budget](budget.md) "
                  "and the [notes](notes.md).\n",
    "budget.md": "# Budget\n\nBudget figures for the roadmap.\n",
    "notes.md": "# Meeting notes\n\nWe discussed the roadmap and the budget.\n",
}

#: Every fixture commit is made at this date, so `generated_at` is known.
ANCHOR_DATE = "2026-09-27T12:00:00+00:00"


# ---------------------------------------------------------------------------
# the registries, and plain git repositories to project
# ---------------------------------------------------------------------------

def _home(root: str):
    """The entry points' default home factory, in its own shape (T022)."""
    return (lga.WorkingTreeCorpus(),
            corpus_adapter.CorpusRef(name="home", location=str(root)))


@pytest.fixture(autouse=True)
def _isolated_registries():
    """Each case starts with no generator registered and openDox's default
    home corpus registered, and PUTS BACK the three registries it found."""
    seam = (gs._registered, gs._is_default, gs._generated_from_default,
            gs._default_generations_under_way)
    profile = (domain_profile._registered, domain_profile._is_default,
               domain_profile._built_from_default)
    home = corpus_adapter._home_factory
    gs.unregister()
    corpus_adapter.register_home(_home)
    yield
    (gs._registered, gs._is_default, gs._generated_from_default,
     gs._default_generations_under_way) = seam
    (domain_profile._registered, domain_profile._is_default,
     domain_profile._built_from_default) = profile
    corpus_adapter._home_factory = home


def _git(root: Path, *args: str) -> str:
    """`git` in `root`, with no inherited `GIT_*` variable and no user or
    system configuration, as the fixture's own identity at a fixed date."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": ANCHOR_DATE, "GIT_COMMITTER_DATE": ANCHOR_DATE,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, env=env).stdout.decode()


def _repository(tmp_path: Path, *, copy: Path | None = None,
                files: dict[str, str | bytes] | None = None,
                commit: bool = True, name: str = "repository") -> Path:
    """A FRESH plain git repository: `copy`'s files and then `files`, added,
    and committed unless `commit` is false."""
    root = tmp_path / name
    if copy is not None:
        shutil.copytree(copy, root)
    else:
        root.mkdir(parents=True)
    for relative, body in (files or {}).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body if isinstance(body, bytes) else body.encode())
    _git(root, "-c", "init.defaultBranch=main", "init", "-q")
    _git(root, "add", "-A")
    if commit:
        _git(root, "commit", "-qm", "fixture")
    return root


def _generate(root: Path, **anchors: Any) -> dict[str, Any]:
    """openDox's own generator over `root`, exactly as the seam calls it."""
    return default_generator.generate(root, "fixture", **anchors)


def _by_path(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {document["path"]: document for document in snapshot["documents"]}


def _values(node: Any) -> Iterator[str]:
    """Every string VALUE, as F5.3 reads them: keys are the product's own."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _values(value)
    elif isinstance(node, str):
        yield node


_F5_3 = re.compile(r"\b(" + "|".join(re.escape(w) for w in F5_3_WORDS) + r")\b")


def _leaks(snapshot: dict[str, Any]) -> list[str]:
    return sorted({m.group(1) for value in _values(snapshot)
                   for m in _F5_3.finditer(value.lower())})


# ---------------------------------------------------------------------------
# the neutral contract, and an evaluator for it (openDox-spec's own, ported)
# ---------------------------------------------------------------------------

def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"the key {key!r} appears twice in one object")
        out[key] = value
    return out


def _no_constants(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _read_schema(path: Path) -> Any:
    """The schema file's body: one JSON object after its `#` comment lines."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        lines.pop(0)
    return json.loads("".join(lines), object_pairs_hook=_no_duplicate_keys,
                      parse_constant=_no_constants)


SCHEMA = _read_schema(SCHEMA_PATH)


class Violation(NamedTuple):
    rule: str       # the broken rule's id, from `x-rule` or a reference check
    where: str      # a JSON pointer into the snapshot ("" is the root)
    keyword: str    # the schema keyword that failed, or "reference"
    detail: str


def _pointer(parts: Any) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1")
                   for p in parts)


def _is_type(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):          # JSON true is not the number 1
        return False
    if name == "integer":
        return isinstance(value, int) or (
            isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, (int, float))
    raise AssertionError(f"the contract names an unknown type: {name!r}")


def _canon(value: Any) -> Any:
    """JSON equality: `true` is not `1`, `1` is `1.0`, and key order is noise."""
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if value is None:
        return ("null",)
    if isinstance(value, list):
        return ("array", tuple(_canon(v) for v in value))
    return ("object", tuple(sorted((k, _canon(v)) for k, v in value.items())))


def _resolve(ref: str) -> dict[str, Any]:
    assert ref.startswith("#/"), f"only local references are in the contract: {ref!r}"
    node: Any = SCHEMA
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _check(value: Any, schema: dict[str, Any], where: str) -> Iterator[Violation]:
    if "$ref" in schema:
        yield from _check(value, _resolve(schema["$ref"]), where)
    rule = schema.get("x-rule", "<no rule named>")

    def broken(keyword: str, detail: str) -> Violation:
        return Violation(rule, where, keyword, detail)

    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            yield broken("type", f"{value!r} is not of type {names}")
    if "const" in schema and _canon(value) != _canon(schema["const"]):
        yield broken("const", f"{value!r} is not {schema['const']!r}")
    if "enum" in schema and _canon(value) not in {_canon(v) for v in schema["enum"]}:
        yield broken("enum", f"{value!r} is not one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            yield broken("minLength", f"{value!r} is shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            yield broken("pattern", f"{value!r} does not match the rule's pattern")
    if _is_type(value, "number") and "minimum" in schema and value < schema["minimum"]:
        yield broken("minimum", f"{value!r} is less than {schema['minimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            yield broken("minItems", f"{len(value)} items, fewer than {schema['minItems']}")
        if schema.get("uniqueItems") and len({_canon(v) for v in value}) != len(value):
            yield broken("uniqueItems", f"{value!r} repeats an item")
        if "items" in schema:
            for i, item in enumerate(value):
                yield from _check(item, schema["items"], f"{where}/{i}")
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                yield broken("required", f"{key!r} is required")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                yield from _check(value[key], sub, where + _pointer([key]))
    for sub in schema.get("allOf", ()):
        yield from _check(value, sub, where)
    if "if" in schema and "then" in schema:   # `if` is a test, never a failure
        if not any(True for _ in _check(value, schema["if"], where)):
            yield from _check(value, schema["then"], where)


def _entries(snap: Any, section: str) -> list[tuple[int, dict[str, Any]]]:
    items = snap.get(section) if isinstance(snap, dict) else None
    if not isinstance(items, list):
        return []
    return [(i, e) for i, e in enumerate(items) if isinstance(e, dict)]


def _ids(snap: Any, section: str, key: str = "id") -> set[str]:
    return {e[key] for _i, e in _entries(snap, section) if isinstance(e.get(key), str)}


def _ids_are_unique(snap: Any) -> Iterator[Violation]:
    for section, key in (("documents", "id"), ("clusters", "id"),
                         ("possibles", "id"), ("staged_topics", "staging_id"),
                         ("changes", "id")):
        seen: set[str] = set()
        for i, entry in _entries(snap, section):
            value = entry.get(key)
            if isinstance(value, str):
                if value in seen:
                    yield Violation("ids-are-unique", f"/{section}/{i}/{key}",
                                    "reference", f"{value!r} is already an id")
                seen.add(value)


def _edges(group: dict[str, Any]) -> list[tuple[int, Any]]:
    edges = group.get("document_edges")
    return list(enumerate(edges if isinstance(edges, list) else []))


def _edge_names_a_document(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "documents")
    for gi, group in _entries(snap, "clusters"):
        for ei, edge in _edges(group):
            ref = edge.get("document") if isinstance(edge, dict) else None
            if isinstance(ref, str) and ref not in known:
                yield Violation("edge-names-a-document",
                                f"/clusters/{gi}/document_edges/{ei}/document",
                                "reference", f"no document has the id {ref!r}")


def _one_edge_per_document(snap: Any) -> Iterator[Violation]:
    for gi, group in _entries(snap, "clusters"):
        seen: set[str] = set()
        for ei, edge in _edges(group):
            ref = edge.get("document") if isinstance(edge, dict) else None
            if isinstance(ref, str):
                if ref in seen:
                    yield Violation("one-edge-per-document",
                                    f"/clusters/{gi}/document_edges/{ei}/document",
                                    "reference", f"{ref!r} already has an edge")
                seen.add(ref)


def _keyword_index_matches_topics(snap: Any) -> Iterator[Violation]:
    index = snap.get("keyword_index") if isinstance(snap, dict) else None
    if not isinstance(index, list):
        return
    carried: dict[str, int] = {}
    for _i, document in _entries(snap, "documents"):
        topics = document.get("topics")
        for topic in ({t for t in topics if isinstance(t, str)}
                      if isinstance(topics, list) else ()):
            carried[topic] = carried.get(topic, 0) + 1
    listed: set[str] = set()
    rule = "keyword-index-matches-topics"
    for ki, entry in enumerate(index):
        keyword = entry.get("keyword") if isinstance(entry, dict) else None
        if not isinstance(keyword, str):
            continue
        if keyword in listed:
            yield Violation(rule, f"/keyword_index/{ki}/keyword", "reference",
                            f"{keyword!r} already has an entry")
            continue
        listed.add(keyword)
        count = entry.get("declared_doc_count")
        if _is_type(count, "integer") and count != carried.get(keyword, 0):
            yield Violation(rule, f"/keyword_index/{ki}/declared_doc_count",
                            "reference", f"{count} documents, but "
                            f"{carried.get(keyword, 0)} carry {keyword!r}")
    unlisted = sorted(set(carried) - listed)
    if unlisted:
        yield Violation(rule, "/keyword_index", "reference",
                        f"topics the documents carry and the index lacks: {unlisted}")


def _candidate_names_a_group(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "clusters")
    for pi, candidate in _entries(snap, "possibles"):
        refs = candidate.get("claiming_clusters")
        for ri, ref in enumerate(refs if isinstance(refs, list) else []):
            if isinstance(ref, str) and ref not in known:
                yield Violation("candidate-names-a-group",
                                f"/possibles/{pi}/claiming_clusters/{ri}",
                                "reference", f"no group has the id {ref!r}")


def _pick_names_a_selection(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "staged_topics", "staging_id")
    for pi, candidate in _entries(snap, "possibles"):
        pick = candidate.get("pick")
        ref = pick.get("staging_id") if isinstance(pick, dict) else None
        if isinstance(ref, str) and ref not in known:
            yield Violation("pick-names-a-selection",
                            f"/possibles/{pi}/pick/staging_id", "reference",
                            f"no selection has the staging_id {ref!r}")


def _target_names_a_submission(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "changes")
    for ti, selection in _entries(snap, "staged_topics"):
        ref = selection.get("target_change")
        if isinstance(ref, str) and ref not in known:
            yield Violation("target-names-a-submission",
                            f"/staged_topics/{ti}/target_change", "reference",
                            f"no changes entry has the id {ref!r}")


REFERENCE_CHECKS: dict[str, Callable[[Any], Iterator[Violation]]] = {
    "ids-are-unique": _ids_are_unique,
    "edge-names-a-document": _edge_names_a_document,
    "one-edge-per-document": _one_edge_per_document,
    "candidate-names-a-group": _candidate_names_a_group,
    "pick-names-a-selection": _pick_names_a_selection,
    "target-names-a-submission": _target_names_a_submission,
    "keyword-index-matches-topics": _keyword_index_matches_topics,
}


def violations(snapshot: Any) -> list[Violation]:
    """Every rule of the neutral contract that `snapshot` breaks."""
    found = list(_check(snapshot, SCHEMA, ""))
    for check in REFERENCE_CHECKS.values():
        found.extend(check(snapshot))
    return found


def test_the_schema_copy_is_openDox_specs_contract_and_matches_the_product() -> None:
    """The copy is T053's file, and the product's own declarations are the
    contract's closed values (T053's writer asked for this cross-check)."""
    digest = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()
    assert digest == SCHEMA_SHA256, (
        f"tests/fixtures/opendox-snapshot.schema.yaml is {digest}, not "
        "openDox-spec#16's contract at cd49eb25. Copy the spec leg's file "
        "again and update SCHEMA_SHA256 with it, in one commit")
    defs = SCHEMA["$defs"]
    assert SCHEMA["properties"]["kind"]["const"] == gs.NEUTRAL_SNAPSHOT_KIND
    assert SCHEMA["properties"]["schema_version"]["const"] == projection.SCHEMA_VERSION
    assert defs["stage_role"]["enum"] == list(display_profile.STAGE_ROLES)
    sections = {section for _role, section, _status in display_profile.STAGE_FIELDS}
    assert sections <= set(SCHEMA["required"])
    assert set(defs["submission_status"]["enum"]) == set(
        projection.CHANGE_STATUS.values())
    assert sorted(REFERENCE_CHECKS) == sorted(
        rule["id"] for rule in SCHEMA["x-rules"] if rule["class"] == "reference")


# ---------------------------------------------------------------------------
# the falsifier, part 1: T050's fixture, with neither sibling importable
# ---------------------------------------------------------------------------

_FALSIFIER = """
import importlib, json, sys
from pathlib import Path
blocked = []
for name in SIBLINGS:
    sys.modules[name] = None
    try:
        importlib.import_module(name)
    except ImportError:
        blocked.append(name)
from opendox import cli, generator_seam
cli.build_parser()          # the entry point registers openDox's own defaults
snapshot = generator_seam.generate(Path(ROOT_OF_REPOSITORY), "fixture")
print(json.dumps({"blocked": blocked, "snapshot": snapshot}))
"""


def test_the_projection_over_the_plain_documents_fixture_is_a_neutral_snapshot(
        tmp_path: Path) -> None:
    """T054's falsifier, first part. A fresh process blocks every sibling,
    lets the CLI entry point register openDox's own defaults (the default
    profile, `WorkingTreeCorpus` as the home corpus, openDox's own generator),
    and generates through the seam over a fresh repository of T050's fixture.
    The snapshot validates against T053's schema, carries none of F5.3's
    declared words, and fills the station each document names."""
    root = _repository(tmp_path, copy=PLAIN)
    program = (f"import sys; sys.path.insert(0, {str(SRC)!r})\n"
               f"SIBLINGS = {SIBLINGS!r}\nROOT_OF_REPOSITORY = {str(root)!r}\n"
               + textwrap.dedent(_FALSIFIER))
    done = subprocess.run([sys.executable, "-c", program], capture_output=True,
                          text=True, cwd=str(ROOT), timeout=300)
    assert done.returncode == 0, done.stderr
    assert "notice:" not in done.stderr, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["blocked"] == list(SIBLINGS), out["blocked"]
    snapshot = out["snapshot"]

    assert violations(snapshot) == []
    assert _leaks(snapshot) == [], (
        f"openxFactory's vocabulary leaked into the neutral projection: "
        f"{_leaks(snapshot)}")
    assert snapshot["kind"] == gs.NEUTRAL_SNAPSHOT_KIND
    assert snapshot["documents"], "the snapshot is empty"

    # EVERY DOCUMENT IN THE STATION IT NAMES, read here off the fixture's own
    # `stage:` lines rather than through the projection's reader.
    expected = {}
    for path in sorted(PLAIN.glob("*.md")):
        declared = re.search(r"^stage: (\S+)$",
                             path.read_text(encoding="utf-8"), re.M)
        expected[path.name] = declared.group(1) if declared else "source"
    assert {p: d["stage"] for p, d in _by_path(snapshot).items()} == expected
    assert len(set(expected.values())) == 6, "T050 spreads over six stations"
    assert snapshot["possibles"] and snapshot["staged_topics"]
    assert {c["status"] for c in snapshot["changes"]} == {"active", "archived"}

    # AT LEAST ONE GROUP FORMS FROM SOURCES ALONE, which is what lets AT-R1
    # open the chat pane: the two rain-barrel notes share their name's words.
    sources = {p for p, stage in expected.items() if stage == "source"}
    derived = [c for c in snapshot["clusters"]
               if {e["document"] for e in c["document_edges"]} <= sources]
    assert derived, snapshot["clusters"]
    assert any(set(c["topics"]) >= {"rain", "barrel"} for c in derived), derived

    # AND THE SOURCE OUTSIDE THAT PAIR LANDS IN NO GROUP. T050's own fixture
    # test pins what the topics are derived from, the names and what each
    # document names (openDox-code#53, Copilot r4135803935 and r4135883800).
    # This pins the projection's own reading of them.
    grouped = {e["document"] for c in snapshot["clusters"]
               for e in c["document_edges"]}
    assert "notes-toolshed-inventory.md" in sources
    assert "notes-toolshed-inventory.md" not in grouped, snapshot["clusters"]


# ---------------------------------------------------------------------------
# the falsifier, part 2: the topic rule over repository (b), no front matter
# ---------------------------------------------------------------------------

def test_the_topic_rule_groups_repository_b_which_has_no_front_matter(
        tmp_path: Path) -> None:
    """T054's falsifier, second part. THE TOPIC RULE: a document that declares
    no `topics:` carries the words of its name (its `title:`, else its first
    `#` heading, else its file name) and the name words of every other
    document it mentions by name or file name. Repository (b)'s three notes
    have no header at all, and they name each other, so they group."""
    for body in REPOSITORY_B.values():
        assert lga.leading_header(body) == {}, "repository (b) has front matter"
    root = _repository(tmp_path, files=REPOSITORY_B, name="plain-notes")
    snapshot = _generate(root)
    assert violations(snapshot) == []
    assert _leaks(snapshot) == []

    documents = _by_path(snapshot)
    assert set(documents) == set(REPOSITORY_B)
    for document in documents.values():
        assert document["stage"] == "source"
        assert document["title"] is None and document["summary"] is None
    assert documents["budget.md"]["topics"] == ["budget", "roadmap"]
    assert documents["notes.md"]["topics"] == ["budget", "meeting", "notes", "roadmap"]

    assert snapshot["clusters"], "repository (b) yields no grouping tile (AT-R1 FAILS)"
    shared = {tuple(c["topics"]): sorted(e["document"] for e in c["document_edges"])
              for c in snapshot["clusters"]}
    assert shared[("budget", "roadmap")] == sorted(REPOSITORY_B)
    for cluster in snapshot["clusters"]:
        assert len(cluster["document_edges"]) >= 2, cluster


# ---------------------------------------------------------------------------
# the falsifier, part 3: a `stage:` value outside the six
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["shelved", "Grouping", ""])
def test_a_stage_value_outside_the_six_is_reported_and_read_as_a_source(
        value: str, tmp_path: Path, capsys) -> None:
    """T054's falsifier, third part (spec.md's edge case, the projection's
    half; T056 holds the verb's). A value outside the six role keys, the empty
    value and another casing included, is no declaration: the generator
    reports it, naming the document, the value and the six keys, and the
    snapshot reads the document as a source, so no other value reaches it."""
    target = "grouping-compost-corner.md"
    root = _repository(tmp_path, copy=PLAIN)
    path = root / target
    path.write_text(path.read_text(encoding="utf-8").replace(
        "stage: grouping\n", f"stage: {value}\n" if value else "stage:\n", 1),
        encoding="utf-8")
    _git(root, "commit", "-qam", "an undeclared stage")

    snapshot = _generate(root)
    notices = [line for line in capsys.readouterr().err.splitlines()
               if line.startswith("notice: ")]
    assert len(notices) == 1, notices
    assert notices[0].startswith(f"notice: {target}: "), notices[0]
    assert repr(value) in notices[0]
    for role in display_profile.STAGE_ROLES:
        assert role in notices[0], f"the report does not name {role!r}"

    assert _by_path(snapshot)[target]["stage"] == "source"
    assert "grouping-compost-corner" not in {c["id"] for c in snapshot["clusters"]}
    assert violations(snapshot) == []


# ---------------------------------------------------------------------------
# 1 — title and summary, exactly as the document gives them (the holder rule)
# ---------------------------------------------------------------------------

def test_the_malformed_fixture_keeps_its_one_violation(tmp_path: Path) -> None:
    """The holder's ruling on T051: the projection neither coerces nor drops
    an empty `title:`, so T051's fixture breaks exactly its EXPECTED_RULE, at
    that document's title. EXPECTED_RULE itself has no shape the adapter
    recognizes, so it is not a document."""
    expected_rule = (MALFORMED / "EXPECTED_RULE").read_text(encoding="utf-8").strip()
    snapshot = _generate(_repository(tmp_path, copy=MALFORMED))
    paths = [d["path"] for d in snapshot["documents"]]
    assert paths == ["notes-bee-boxes.md", "notes-empty-title.md"]
    found = violations(snapshot)
    assert [(v.rule, v.where) for v in found] == [
        (expected_rule, f"/documents/{paths.index('notes-empty-title.md')}/title")]
    assert _by_path(snapshot)["notes-empty-title.md"]["title"] == ""


def test_title_and_summary_are_copied_exactly_and_null_only_when_absent(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, files={
        "both.md": "title: Both fields\nsummary:   kept   as written  \n\n# Other\n",
        "none.md": "# Only a heading\n\nNo header here.\n",
        "empty.md": "title:\nsummary:\n\nBody.\n",
        "quoted.md": 'title: "Quoted"\n\nBody.\n',
    })
    documents = _by_path(_generate(root))
    assert (documents["both.md"]["title"], documents["both.md"]["summary"]) == (
        "Both fields", "kept   as written")
    assert (documents["none.md"]["title"], documents["none.md"]["summary"]) == (None, None)
    assert (documents["empty.md"]["title"], documents["empty.md"]["summary"]) == ("", "")
    assert (documents["quoted.md"]["title"], documents["quoted.md"]["summary"]) == (
        '"Quoted"', None)


# ---------------------------------------------------------------------------
# 2 — what a document is
# ---------------------------------------------------------------------------

def test_an_entry_the_adapter_cannot_classify_is_not_a_document(tmp_path: Path) -> None:
    """The holder's ruling: a `Makefile` or an image is left out, and is never
    read, so nothing mentions it either."""
    root = _repository(tmp_path, files={
        "Makefile": "all:\n\techo build\n",
        "garden-layout.png": b"\x89PNG\r\n\x1a\n\x00binary",
        "notes.md": "# Notes\n\nSee the Makefile and the garden layout png.\n",
    })
    snapshot = _generate(root)
    assert [d["path"] for d in snapshot["documents"]] == ["notes.md"]
    assert _by_path(snapshot)["notes.md"]["topics"] == ["notes"]
    assert violations(snapshot) == []


@pytest.mark.parametrize(("name", "reason"), [
    ("back\\slash.md", "backslash"), ("tab\tin-name.md", "control character")])
def test_a_path_the_schema_cannot_carry_is_left_out_and_reported(
        name: str, reason: str, tmp_path: Path, capsys) -> None:
    root = _repository(tmp_path, files={name: "# Odd\n", "plain.md": "# Plain\n"})
    snapshot = _generate(root)
    assert [d["path"] for d in snapshot["documents"]] == ["plain.md"]
    notices = [line for line in capsys.readouterr().err.splitlines()
               if line.startswith("notice: ")]
    assert len(notices) == 1 and repr(name) in notices[0] and reason in notices[0], notices
    assert violations(snapshot) == []


# ---------------------------------------------------------------------------
# 3 — topics, groups and the other stations
# ---------------------------------------------------------------------------

def test_declared_topics_replace_the_derived_ones(tmp_path: Path) -> None:
    root = _repository(tmp_path, files={
        "a.md": "title: Rain notes\ntopics: Rain, rain barrel ,  COMPOST, , "
                "tab\there, bell\x07\n\nText.\n",
    })
    snapshot = _generate(root)
    assert _by_path(snapshot)["a.md"]["topics"] == [
        "compost", "rain", "rain barrel", "tab here"]
    assert violations(snapshot) == []


def test_an_empty_topics_header_declares_no_topic(tmp_path: Path) -> None:
    """A `topics:` header is a declaration even when it lists nothing: the
    document carries no topic, and none is derived for it, so it joins no
    group although its name shares words with two sources that do group."""
    root = _repository(tmp_path, files={
        "a.md": "title: Rain barrel\ntopics:\n\n.\n",
        "b.md": "title: Rain barrel notes\n\n.\n",
        "c.md": "title: Rain barrel log\n\n.\n",
    })
    snapshot = _generate(root)
    assert _by_path(snapshot)["a.md"]["topics"] == []
    [group] = snapshot["clusters"]
    assert [e["document"] for e in group["document_edges"]] == ["b.md", "c.md"]
    assert violations(snapshot) == []


def test_a_word_is_a_run_of_letters_even_beside_digits(tmp_path: Path) -> None:
    """A word is a run of three or more letters: `Q3planning` holds `planning`,
    so it groups with a source whose name spells the word on its own."""
    snapshot = _generate(_repository(tmp_path, files={
        "a.md": "title: Q3planning review\n\n.\n",
        "b.md": "title: planning review\n\n.\n",
    }))
    assert _by_path(snapshot)["a.md"]["topics"] == ["planning", "review"]
    [group] = snapshot["clusters"]
    assert group["topics"] == ["planning", "review"]
    assert violations(snapshot) == []


def test_a_declared_group_gathers_the_sources_that_share_its_topics(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, files={
        "g.md": "stage: grouping\ntitle: Water, gathered\ntopics: water\n\n.\n",
        "a.md": "topics: water, soil\n\n.\n",
        "b.md": "topics: soil\n\n.\n",
        "c.md": "stage: candidate\ntitle: Harvest the rain\nsummary: Gutters "
                "to barrels.\ntopics: water\n\n.\n",
        "d.md": "stage: selection\ntopics: water\n\n.\n",
    })
    snapshot = _generate(root)
    assert violations(snapshot) == []
    clusters = {c["id"]: c for c in snapshot["clusters"]}
    assert list(clusters) == ["g", "soil"], "declared groups first, then derived"
    assert clusters["g"]["name"] == "Water, gathered"
    assert clusters["g"]["document_edges"] == [
        {"document": "a.md", "matched_topics": ["water"]},
        {"document": "g.md", "matched_topics": ["water"]}]
    assert [e["document"] for e in clusters["soil"]["document_edges"]] == ["a.md", "b.md"]
    [candidate] = snapshot["possibles"]
    assert candidate == {"id": "c", "title": "Harvest the rain",
                         "claim": "Gutters to barrels.", "state": "unselected",
                         "claiming_clusters": ["g"]}
    assert snapshot["staged_topics"] == [{"staging_id": "d", "files": ["d.md"]}]


def test_a_declared_group_with_no_topic_forms_no_group_and_is_reported(
        tmp_path: Path, capsys) -> None:
    snapshot = _generate(_repository(tmp_path, files={"g.md": "stage: grouping\ntitle: 2026\n"}))
    assert snapshot["clusters"] == []
    assert _by_path(snapshot)["g.md"]["stage"] == "grouping"
    assert "notice: g.md: declares stage grouping but carries no topic" in \
        capsys.readouterr().err


def test_station_ids_are_unique_within_a_section(tmp_path: Path) -> None:
    snapshot = _generate(_repository(tmp_path, files={
        "a/plan.md": "stage: selection\n", "b/plan.md": "stage: selection\n",
        "x/ship.md": "stage: submission\n", "y/ship.md": "stage: completion\n",
    }))
    assert [t["staging_id"] for t in snapshot["staged_topics"]] == ["plan", "plan-2"]
    assert [(c["id"], c["status"]) for c in snapshot["changes"]] == [
        ("ship", "active"), ("ship-2", "archived")]
    assert violations(snapshot) == []


# ---------------------------------------------------------------------------
# 4 — the anchors, and determinism
# ---------------------------------------------------------------------------

def test_the_anchors_come_from_the_source_revision_and_the_bytes_repeat(
        tmp_path: Path) -> None:
    root = _repository(tmp_path, copy=PLAIN)
    first, second = _generate(root), _generate(root)
    assert json.dumps(first) == json.dumps(second)
    head = _git(root, "rev-parse", "HEAD").strip()
    assert first["generation"] == {
        "source_revision": head,
        "generated_at": _git(root, "show", "-s", "--format=%cI", "HEAD").strip(),
        "generator_version": projection.GENERATOR_VERSION}
    # The same instant as the commit's date. git spells a zero offset `Z` or
    # `+00:00` depending on its version, and the stamp is recorded as git
    # spells it, so the two are compared as times, not as strings.
    assert datetime.fromisoformat(first["generation"]["generated_at"]) == \
        datetime.fromisoformat(ANCHOR_DATE)

    pinned = _generate(root, source_revision="release-candidate",
                       generated_at="2026-01-02T03:04:05Z")["generation"]
    assert (pinned["source_revision"], pinned["generated_at"]) == (
        "release-candidate", "2026-01-02T03:04:05Z")
    unknown = _generate(root, source_revision="0" * 40)["generation"]
    assert "generated_at" not in unknown


def test_an_adapter_whose_keys_are_not_declared_paths_is_refused(tmp_path: Path) -> None:
    """`DocumentId.key` is opaque to the `CorpusAdapter` interface, so the
    projection reads keys as repository paths only for an adapter that
    declares `PATH_KEYS`. One that does not is refused, naming the
    declaration, rather than having an object id or a row key written as a
    path (Copilot at openDox-code#57 50b0d42b, r4139607560)."""
    root = _repository(tmp_path, files={"a.md": "title: A\nsummary: S\n"})
    assert projection.PATH_KEYS == "document_keys_are_paths"
    assert lga.LocalGitCorpus.document_keys_are_paths is True

    class _Opaque:
        """Delegates everything to a path adapter, and declares nothing."""
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            if name == projection.PATH_KEYS:
                raise AttributeError(name)
            return getattr(self._inner, name)

    inner = lga.WorkingTreeCorpus()
    corpus = inner.resolve(corpus_adapter.CorpusRef(name="home", location=str(root)))
    with pytest.raises(projection.ProjectionRefused) as caught:
        projection.project(_Opaque(inner), corpus, "garden")
    assert "document_keys_are_paths = True" in str(caught.value)
    assert isinstance(caught.value, gs.GeneratorSeamError)
    declared = _Opaque(inner)
    declared.document_keys_are_paths = True
    paths = [d["path"] for d in
             projection.project(declared, corpus, "garden").snapshot["documents"]]
    assert paths == ["a.md"]


def test_a_repository_with_no_commit_needs_a_pinned_revision(tmp_path: Path) -> None:
    root = _repository(tmp_path, files={"a.md": "# A\n"}, commit=False)
    with pytest.raises(projection.ProjectionRefused) as caught:
        _generate(root)
    assert isinstance(caught.value, gs.GeneratorSeamError)
    assert "source revision" in str(caught.value)
    snapshot = _generate(root, source_revision="pinned-by-hand")
    assert snapshot["generation"]["source_revision"] == "pinned-by-hand"
    assert "generated_at" not in snapshot["generation"]
    assert violations(snapshot) == []


# ---------------------------------------------------------------------------
# 5 — the small neutral field set on openDox's default adapter
# ---------------------------------------------------------------------------

def test_the_default_adapter_obliges_the_small_neutral_field_set(tmp_path: Path) -> None:
    assert lga.NEUTRAL_FIELDS == ("title", "summary")
    assert lga.WorkingTreeCorpus()._required_fields == lga.NEUTRAL_FIELDS
    assert lga.LocalGitCorpus()._required_fields == ()
    root = _repository(tmp_path, files={
        "both.md": "title: T\nsummary: S\n", "none.md": "# N\n",
        "empty.md": "title:\nsummary: S\n", "Makefile": "all:\n"})
    adapter, ref = _home(str(root))
    corpus = adapter.resolve(ref)
    missing = {d.key: adapter.classify(corpus, d).missing_fields
               for d in adapter.list_documents(corpus)}
    assert missing == {"both.md": (), "none.md": ("title", "summary"),
                       "empty.md": ("title",), "Makefile": ()}
    # a document without the fields is still read, as a source
    assert _by_path(_generate(root))["none.md"]["stage"] == "source"


def test_an_empty_field_is_missing_whichever_vocabulary_is_in_force(
        tmp_path: Path) -> None:
    """The suffix vocabulary and the `kind_field` one read a field given with
    nothing after its colon the same way: as no field. The `kind_field` path
    counted it present by its key alone (Copilot at openDox-code#57
    03e06ccd, r4139523226)."""
    root = _repository(tmp_path, files={
        "both.md": "kind: note\ntitle: T\nsummary: S\n",
        "empty.md": "kind: note\ntitle:\nsummary: S\n",
        "none.md": "kind: note\n"})
    ref = corpus_adapter.CorpusRef(name="home", location=str(root))
    by_suffix = lga.LocalGitCorpus(required_fields=lga.NEUTRAL_FIELDS)
    by_header = lga.LocalGitCorpus(kind_field="kind",
                                   required_fields=lga.NEUTRAL_FIELDS)
    for adapter in (by_suffix, by_header):
        corpus = adapter.resolve(ref)
        missing = {d.key: adapter.classify(corpus, d).missing_fields
                   for d in adapter.list_documents(corpus)}
        assert missing == {"both.md": (), "empty.md": ("title",),
                           "none.md": ("title", "summary")}, adapter._kind_field


def test_the_commit_date_is_read_by_the_home_corpus_s_own_git(tmp_path: Path) -> None:
    """`generated_at` is read with the git the home corpus runs, not a bare
    `git` from PATH, so the date and the revision it stamps come from one
    git (Copilot at openDox-code#57 03e06ccd, r4139523258)."""
    from opendox import default_generator

    root = _repository(tmp_path, files={"a.md": "title: A\nsummary: S\n"})
    real = shutil.which("git")
    log = tmp_path / "calls.log"
    wrapper = tmp_path / "logging-git"
    wrapper.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexec "{real}" "$@"\n',
                       encoding="utf-8")
    wrapper.chmod(0o755)
    corpus_adapter.register_home(lambda location: (
        lga.WorkingTreeCorpus(executable=str(wrapper)),
        corpus_adapter.CorpusRef(name="home", location=str(location))))
    snapshot = default_generator.generate(root, "garden")
    assert snapshot["generation"].get("generated_at"), "a date was read"
    assert "--format=%cI" in log.read_text(encoding="utf-8"), (
        "the commit date was read by the home corpus's own git")


def test_required_header_fields_answers_the_neutral_set_through_the_entry_point() -> None:
    from opendox import cli

    corpus_adapter._home_factory = corpus_adapter._UNSET
    cli.build_parser()
    assert authoring.required_header_fields() == ("title", "summary")
    assert authoring.missing_required_headers("title: A note\n") == ["summary"]


def test_the_header_reader_keeps_an_empty_value_and_stops_at_a_blank_line() -> None:
    assert lga.leading_header("a: 1\nno colon here\nb:\na: 2\n\nc: 3\n") == {
        "a": "2", "b": ""}


# ---------------------------------------------------------------------------
# 5a — openDox's own scaffold carries the small neutral field set
# ---------------------------------------------------------------------------

#: One create's input, with its date pinned, so two scaffolds compare as bytes.
_CREATE: dict[str, Any] = {
    "title": "Shed roof", "summary": "Where the water gets in after a storm.",
    "topics": ["shed"], "repository_context": "garden",
    "now": "2026-09-29T12:00:00Z"}


def test_openDoxs_own_scaffold_carries_the_small_neutral_field_set(
        tmp_path: Path) -> None:
    """The holder's decision of 2026-09-28 on this PR: what `create` writes
    must satisfy `NEUTRAL_FIELDS` under openDox's own default adapter.

    It read there as missing both fields, because its H1 comes first and its
    `Summary:` is capitalized. So standalone `agent_capture` refused what
    `create` had written, and the projection lost the supplied summary
    (Copilot r4126022820, reproduced on openDox-code#59). The scaffold now
    leads with `title:` and `summary:`, and its governed block follows it
    unchanged."""
    root = _repository(tmp_path, files={"notes-first.md": "title: F\nsummary: S\n"})
    assert authoring.scaffold_lead_fields() == lga.NEUTRAL_FIELDS
    written = authoring.create_scaffold(OutputBoundary(root, actor=HUMAN),
                                        **_CREATE)
    text = written.read_text(encoding="utf-8")

    assert lga.leading_header(text) == {"title": "Shed roof",
                                        "summary": _CREATE["summary"]}
    assert authoring.missing_required_headers(text) == []
    assert text == (f"title: Shed roof\nsummary: {_CREATE['summary']}\n\n"
                    + authoring.render_scaffold(**_CREATE))

    # AN AGENT'S CAPTURE OF THE SAME TEXT is not refused as header-incomplete.
    captured = authoring.agent_capture(
        authoring.agent_boundary(root),
        path="ideation/brainstorm/shed-roof-again.md", text=text)
    assert captured.read_text(encoding="utf-8") == text

    # AND THE PROJECTION KEEPS the title and summary the create was given.
    documents = _by_path(_generate(root))
    for path in (written, captured):
        document = documents[path.relative_to(root).as_posix()]
        assert (document["title"], document["summary"]) == (
            "Shed roof", _CREATE["summary"])


def test_a_scaffold_keeps_the_governed_layout_where_the_corpus_obliges_neither(
        tmp_path: Path) -> None:
    """Under a corpus that obliges neither neutral field, the scaffold is
    byte-identical to `render_scaffold`'s default, H1 first. openxFactory's
    adapter is one such, since its fields are the governed block's own.
    openxFactory's gated create (`tests/ideation-dashboard/test_gate_routes.py`)
    and openXdox's authoring suite (`tests/test_authoring_agent.py`) pin that
    layout."""
    governed = ("Status", "Kind", "Summary", "Topics", "Repository context",
                "Captured")
    corpus_adapter.register_home(lambda root: (
        lga.WorkingTreeCorpus(required_fields=governed),
        corpus_adapter.CorpusRef(name="home", location=str(root))))
    assert authoring.required_header_fields() == governed
    assert authoring.scaffold_lead_fields() == ()
    root = _repository(tmp_path, files={"notes-first.md": "title: F\nsummary: S\n"})
    written = authoring.create_scaffold(OutputBoundary(root, actor=HUMAN),
                                        **_CREATE)
    text = written.read_text(encoding="utf-8")
    assert text == authoring.render_scaffold(**_CREATE)
    assert text.startswith("# Shed roof — Brainstorm\n")


def test_the_lead_block_is_the_neutral_fields_in_order_then_a_blank_line() -> None:
    """The lead is `SCAFFOLD_LEAD_FIELDS`' order whatever order it is asked
    in. The neutral title is the title without the family suffix, which
    stays on the H1. A field the scaffold has no value for is refused. And
    every field openDox's own default obliges is one a scaffold can lead
    with, so a created document always satisfies it."""
    suffixed = {**_CREATE, "title": "Shed roof — Brainstorm"}
    plain = authoring.render_scaffold(**suffixed)
    assert plain.startswith("# Shed roof — Brainstorm\n")
    assert authoring.render_scaffold(**suffixed, lead_fields=("summary", "title")) == (
        f"title: Shed roof\nsummary: {_CREATE['summary']}\n\n" + plain)
    assert authoring.render_scaffold(**suffixed, lead_fields=("summary",)) == (
        f"summary: {_CREATE['summary']}\n\n" + plain)
    with pytest.raises(ValueError, match=r"no value for \['author'\]"):
        authoring.render_scaffold(**suffixed, lead_fields=("title", "author"))
    assert set(lga.NEUTRAL_FIELDS) <= set(authoring.SCAFFOLD_LEAD_FIELDS)


@pytest.mark.parametrize("field", ["title", "summary"])
@pytest.mark.parametrize("breaker", ["\n", "\r", "\r\n", "\x0b", "\x1e", "\x85",
                                     " ", " ", "\t", "\x00"])
def test_a_lead_value_that_is_not_one_header_line_is_refused(
        field: str, breaker: str, tmp_path: Path) -> None:
    """A leading `title:` or `summary:` is ONE header line. A value that
    breaks it would put a line of the caller's choosing into the block the
    default adapter reads: `summary="ok\\nstage: completion"` read as the
    document's own `stage:` (Copilot at openDox-code#57 1a603677,
    r4139383472). So it is refused before anything is rendered or written.
    A value with no lead block to break keeps the governed layout as before,
    and an ordinary value with inner spaces and dashes still leads."""
    value = f"ok{breaker}stage: completion"
    asked = {**_CREATE, field: value}
    with pytest.raises(ValueError, match=f"leading {field}: must be one header line"):
        authoring.render_scaffold(**asked, lead_fields=("title", "summary"))
    assert authoring.render_scaffold(**asked).startswith("# "), (
        "with no lead block, nothing new is refused")
    with pytest.raises(ValueError):
        authoring.create_scaffold(OutputBoundary(tmp_path, actor=HUMAN), **asked)
    assert not any(tmp_path.rglob("*.md")), "a refused create writes nothing"
    fine = {**_CREATE, field: "A shed roof — pitched, not flat"}
    assert authoring.render_scaffold(**fine, lead_fields=(field,)).startswith(
        f"{field}: A shed roof — pitched, not flat\n")


def test_a_scaffold_with_no_corpus_registered_refuses_and_writes_nothing(
        tmp_path: Path) -> None:
    """`create_scaffold` asks the corpus which fields to lead with, as
    `agent_capture` asks it which to require. So with no home registered it
    refuses as that does (4.2), naming the seam, and it writes nothing."""
    corpus_adapter._home_factory = corpus_adapter._UNSET
    with pytest.raises(corpus_adapter.CorpusRefused) as refused:
        authoring.create_scaffold(OutputBoundary(tmp_path, actor=HUMAN), **_CREATE)
    assert refused.value.refusal.kind == corpus_adapter.ADAPTER_NOT_REGISTERED
    assert list(tmp_path.rglob("*")) == []


# ---------------------------------------------------------------------------
# 6 — the product's views match the product's snapshot
# ---------------------------------------------------------------------------

def _js_snapshot_values() -> dict[str, dict[str, str]]:
    text = DISPLAY_JS.read_text(encoding="utf-8")
    body = re.search(r"export const SNAPSHOT_VALUES = \{(.*?)\n\};", text, re.S).group(1)
    return {name: dict(re.findall(r'(\w+): "([^"]*)"', table))
            for name, table in re.findall(r"(\w+): \{([^}]*)\}", body)}


def test_the_display_defaults_are_the_neutral_snapshots_values() -> None:
    """R1Q11 (a), batch G's 5.3: the defaults are what openDox's own generator
    writes, role for role, on both sides of the process boundary. The
    candidate's four are NEUTRAL_DISPLAY's own words: no word is re-authored."""
    values = display_profile.SNAPSHOT_VALUES
    assert values == {
        "document_stage": {"captured": "source", "organized": "grouping"},
        "register_state": display_profile.NEUTRAL_DISPLAY["statuses"]["candidate"],
    }
    assert _js_snapshot_values() == values
    defs = SCHEMA["$defs"]
    assert set(values["document_stage"].values()) <= set(defs["stage_role"]["enum"])
    assert set(values["register_state"].values()) == set(defs["candidate_state"]["enum"])
    assert projection.SOURCE == values["document_stage"]["captured"]
    assert projection.GROUPING == values["document_stage"]["organized"]
    assert projection.UNSELECTED == values["register_state"]["captured"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_wheel_counts_a_groups_edges_where_it_carries_no_tally(tmp_path: Path) -> None:
    """The holder's ruling: the neutral schema is not widened with a tally, so
    the wheel's grouping tile counts the group's edges. A group that carries a
    tally, as the governed snapshot's do, still shows the tally."""
    snapshot = _generate(_repository(tmp_path, files=REPOSITORY_B))
    snapshot["clusters"].append({"id": "tallied", "name": "tallied", "topics": ["t"],
                                 "document_edges": [], "tallies": {"document_links": 7}})
    script = tmp_path / "wheel.mjs"
    script.write_text(textwrap.dedent(f"""
        const W = await import({json.dumps(str(WHEEL_MODEL_JS))});
        const snap = {json.dumps(snapshot)};
        const model = W.buildWheelModel(snap);
        const reel = model.wheels.find((w) => w.key === "grouping");
        console.log(JSON.stringify(reel.items.map((i) => [i.id, i.sub])));
    """), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    subs = dict(json.loads(done.stdout.strip().splitlines()[-1]))
    for cluster in snapshot["clusters"][:-1]:
        assert subs[cluster["id"]].startswith(f"{len(cluster['document_edges'])} "), subs
    assert subs["tallied"].startswith("7 "), subs


# ---------------------------------------------------------------------------
# 7 — no reach
# ---------------------------------------------------------------------------

def test_the_projection_imports_with_no_sibling_and_no_third_party_module() -> None:
    block = "".join(f"sys.modules[{name!r}] = None\n" for name in SIBLINGS)
    program = (f"import sys; sys.path.insert(0, {str(SRC)!r})\n" + block
               + textwrap.dedent("""
        before = set(sys.modules)
        import opendox.neutral_projection, opendox.default_generator
        added = {name.split(".")[0] for name in set(sys.modules) - before}
        print(sorted(added - set(sys.stdlib_module_names) - {"opendox"}))
    """))
    done = subprocess.run([sys.executable, "-c", program], capture_output=True,
                          text=True, cwd=str(ROOT), timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout
    assert not hasattr(default_generator, "NeutralProjectionNotBuilt"), (
        "T052's refusal outlived the projection that retires it")
