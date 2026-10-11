"""T044's falsifier: openDox's neutral health families, over T043's corpus
(plan 038 T044, HA-2; #1144 14.4 part, 6.2 part; FR-010, FR-012, FR-015).

The families are `opendox.health.families`. They DETECT; the engine (T046)
stamps the id, the pack and the baseline class, and the fix loop (T053) writes
the repair. So every case here reads the family-owned fields a run returns and
derives what the engine would, through T041's public `finding_id()` and
`make_finding()`.

THE CORPUS IS T043'S. `tests/fixtures/health-corpus` is copied into a fresh
repository on `main` with `standalone_child.fresh_repository`, as F14.1 does,
and every expectation is read from T043's own module (`PLANTED`, `INTENDED`,
`CLEAN`, `ENTRY_DOCUMENTS`, the link pins and the near-duplicate pin), never
re-typed. The edge cases each build a small repository of their own, with
committer and author dates set in this test's own child environment.

BOTH READINGS. A run reads a pinned commit (a default-tip or branch run) or the
working copy (a working-state run), and the two agree on a clean tree.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from opendox.health import families as F
from opendox.corpus_adapter import CorpusRef
from opendox.doxbench_intake import SETTINGS_DOCUMENTS
from opendox.health_contract import (
    ASSISTED,
    AUTO_FIX,
    CATEGORIES,
    ENGINE_KINDS,
    FORBIDDEN_KEYS,
    HUMAN_ONLY,
    IDENTITY_COLLISION,
    OPENDOX,
    SEVERITIES,
    STRING_MAX,
    finding_id,
    make_finding,
)
from opendox.runtime.local_git_adapter import KINDS_BY_SUFFIX
from import_scan import names_imported_by
from standalone_child import fresh_repository
from test_health_corpus_fixture import (
    ABSENT_LINK,
    CLEAN,
    CORPUS,
    EMPTY_STUB,
    ENTRY_DOCUMENTS,
    INTENDED,
    MOVED_LINK,
    NEAR_DUPLICATE_PAIR,
    NEAR_DUPLICATE_REPORTED,
    PLAIN,
    PLANTED,
)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
FAMILIES_PY = SRC / "opendox" / "health" / "families.py"
HEALTH_INIT = SRC / "opendox" / "health" / "__init__.py"

#: The fields a family owns (contracts/health-finding.md:24-25). The engine's
#: (`id`, `pack_id`, `pack_version`, `baseline_class`) never appear.
FAMILY_FIELDS = {"kind", "path", "identity", "locator", "severity",
                 "resolution_class", "message", "evidence"}
ENGINE_FIELDS = {"id", "pack_id", "pack_version", "baseline_class"}

#: Fixed instants, so an age is exact to the second.
DAY = 86400
T0 = 1_700_000_000

#: Modules the families' import closure may not hold (brief, item 17).
MODEL_MODULES = ("opendox.doxbench_model", "opendox.doxbench_provider",
                 "opendox.doxbench_bridge")
DIRECT_FORBIDDEN = (*MODEL_MODULES, "opendox.doxbench_binding")
DRIVERS = ("psycopg", "psycopg2", "psycopg_pool", "asyncpg", "pg8000",
           "sqlalchemy", "sqlite3")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _git(root: Path, *args: str, when: int | None = None,
         author: int | None = None) -> str:
    """`git` in `root` as the fixture identity, with no inherited `GIT_*`
    variable and no user or system configuration. `when` sets both dates,
    `author` overrides the author date alone."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    if when is not None:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"@{when} +0000"
    if author is not None:
        env["GIT_AUTHOR_DATE"] = f"@{author} +0000"
    done = subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, env=env)
    return done.stdout.decode("utf-8", "replace")


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _repository(parent: Path, files: dict[str, str], *, name: str = "corpus",
                when: int = T0, author: int | None = None) -> Path:
    root = parent / name
    root.mkdir()
    _write(root, files)
    _git(root, "-c", "init.defaultBranch=main", "init", "-q")
    _commit(root, when=when, author=author)
    return root


def _commit(root: Path, *, when: int = T0, author: int | None = None,
            message: str = "fixture") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", message, when=when, author=author)


def _run(root: Path, *, pinned: bool = True, families=None, documents=None):
    adapter = F.default_adapter()
    head = _git(root, "rev-parse", "HEAD").strip() if pinned else None
    corpus = adapter.resolve(CorpusRef(name="fixture", location=str(root),
                                       revision=head))
    return F.run_families(adapter, corpus, families=families,
                          documents=documents)


def _on(found, path: str, kind: str | None = None):
    return [f for f in found if f["path"] == path
            and (kind is None or f["kind"] == kind)]


def _id(finding) -> str:
    return finding_id(identity=finding["identity"], kind=finding["kind"],
                      pack_id=OPENDOX, path=finding["path"])


def _document(old_id: str) -> str:
    return EMPTY_STUB if old_id == "empty-stub" else PLANTED[old_id]


def _header(title: str = "A note", summary: str = "A short note.",
            **more: str) -> str:
    lines = [f"{k}: {v}" for k, v in more.items()]
    if title is not None:
        lines.append(f"title: {title}")
    if summary is not None:
        lines.append(f"summary: {summary}")
    return "\n".join(lines) + "\n\n"


PROSE = ("One line of plain prose about the garden.\n"
         "A second line about the beds.\n"
         "A third line about the path.\n"
         "A fourth line about the shed.\n")


@pytest.fixture(scope="module")
def corpus_repo(tmp_path_factory) -> Path:
    return fresh_repository(CORPUS, tmp_path_factory.mktemp("health"))


@pytest.fixture(scope="module", params=["pinned", "working-copy"])
def corpus_run(request, corpus_repo):
    return _run(corpus_repo, pinned=request.param == "pinned")


# --------------------------------------------------------------------------
# T043's corpus: one finding per planted document, nothing else
# --------------------------------------------------------------------------

@pytest.mark.parametrize("old_id", sorted(INTENDED))
def test_each_intended_document_raises_exactly_one_finding_of_its_kind_and_class(
        corpus_run, old_id) -> None:
    kind, cls = INTENDED[old_id]
    on = _on(corpus_run, _document(old_id))
    assert [(f["kind"], f["resolution_class"]) for f in on] == [(kind, cls)], on


@pytest.mark.parametrize("document", sorted({*CLEAN, *ENTRY_DOCUMENTS}))
def test_every_clean_document_and_entry_document_raises_none(corpus_run,
                                                             document) -> None:
    assert _on(corpus_run, document) == []


def test_the_corpus_raises_the_intended_findings_and_nothing_else(corpus_run
                                                                  ) -> None:
    want = sorted((_document(o), k, c) for o, (k, c) in INTENDED.items())
    got = sorted((f["path"], f["kind"], f["resolution_class"]) for f in corpus_run)
    assert got == want


def test_the_planted_links_carry_their_written_targets(corpus_run) -> None:
    moved = _on(corpus_run, MOVED_LINK[0], F.BROKEN_LINK)[0]
    assert moved["identity"] == {"target": MOVED_LINK[1]}
    assert moved["evidence"]["candidate"] == MOVED_LINK[2]
    assert moved["locator"]["target"] == MOVED_LINK[1]
    absent = _on(corpus_run, ABSENT_LINK[0], F.BROKEN_LINK)[0]
    assert absent["identity"] == {"target": ABSENT_LINK[1]}
    assert "candidate" not in absent["evidence"]


def test_the_near_duplicate_is_on_the_reported_document(corpus_run) -> None:
    first, _ = NEAR_DUPLICATE_PAIR
    found = [f for f in corpus_run if f["kind"] == F.NEAR_DUPLICATE]
    assert [(f["path"], f["identity"]) for f in found] == [
        (NEAR_DUPLICATE_REPORTED, {"other": first})]


def test_the_empty_stub_is_assisted(corpus_run) -> None:
    stub = _on(corpus_run, EMPTY_STUB)
    assert [(f["kind"], f["resolution_class"]) for f in stub] == [
        (F.EMPTY_STUB, ASSISTED)]


def test_pinned_and_working_copy_readings_agree_on_a_clean_tree(corpus_repo
                                                                ) -> None:
    assert _run(corpus_repo, pinned=True) == _run(corpus_repo, pinned=False)


# --------------------------------------------------------------------------
# the contract: what a family supplies, and what it never does
# --------------------------------------------------------------------------

def _admit(found) -> None:
    for f in found:
        assert set(f) <= FAMILY_FIELDS, f
        assert not set(f) & ENGINE_FIELDS, f
        made = make_finding(pack_id=OPENDOX, pack_version="0.0.0-test", **f)
        assert made["id"] == _id(f)
        assert f["severity"] == F.SEVERITY


def _walk_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
    elif isinstance(value, str):
        yield value


def test_every_corpus_finding_is_admitted_whole_by_make_finding(corpus_run
                                                                ) -> None:
    _admit(corpus_run)
    for f in corpus_run:
        identity = f["identity"]
        assert not any(isinstance(v, (int, float)) for v in identity.values())
        assert all(len(s) <= STRING_MAX for s in _walk_strings(identity))
        assert all(len(s) <= STRING_MAX for s in _walk_strings(f["evidence"]))
        keys = set()
        for field in ("identity", "evidence"):
            stack = [f[field]]
            while stack:
                v = stack.pop()
                if isinstance(v, dict):
                    keys |= set(v)
                    stack += list(v.values())
        assert not keys & set(FORBIDDEN_KEYS), f


def test_no_two_findings_share_an_id(corpus_run) -> None:
    ids = [_id(f) for f in corpus_run]
    assert len(ids) == len(set(ids))


def test_no_family_kind_is_an_engine_kind() -> None:
    engine = {*CATEGORIES, IDENTITY_COLLISION, "uncited-disappearance",
              *ENGINE_KINDS}
    assert not set(F.FAMILIES) & engine
    assert len(F.FAMILIES) == 7 == len(set(F.FAMILIES))
    assert set(F.FAMILIES) == set(F.CHECKS)
    assert F.SEVERITY == "warning" and F.SEVERITY in SEVERITIES


def test_each_family_runs_alone_and_an_unknown_family_is_refused(corpus_repo
                                                                 ) -> None:
    whole = _run(corpus_repo)
    for kind in F.FAMILIES:
        alone = _run(corpus_repo, families=(kind,))
        assert alone == [f for f in whole if f["kind"] == kind], kind
    with pytest.raises(F.UnknownFamily):
        _run(corpus_repo, families=("broken-link", "no-such-family"))
    with pytest.raises(TypeError):
        _run(corpus_repo, documents="README.md")


def test_a_named_subset_is_judged_while_orphans_and_pairs_read_the_corpus(
        corpus_repo) -> None:
    subset = (NEAR_DUPLICATE_REPORTED, "garden/rain-barrel-checklist.md")
    found = _run(corpus_repo, documents=subset)
    assert sorted((f["path"], f["kind"]) for f in found) == [
        (NEAR_DUPLICATE_REPORTED, F.NEAR_DUPLICATE)]
    orphan = _run(corpus_repo, documents=(PLANTED["human-only-finding"],))
    assert [(f["path"], f["kind"]) for f in orphan] == [
        (PLANTED["human-only-finding"], F.ORPHAN)]


# --------------------------------------------------------------------------
# the id: position-independent (N-13)
# --------------------------------------------------------------------------

def _insert_above_body(text: str, extra: str) -> str:
    head, _, body = text.partition("\n\n")
    return f"{head}\n\n{extra}{body}"


@pytest.mark.parametrize("pinned", [True, False])
def test_an_edit_above_the_broken_link_moves_its_locator_and_keeps_its_id(
        tmp_path, pinned) -> None:
    repo = fresh_repository(CORPUS, tmp_path)
    before = _on(_run(repo, pinned=pinned), MOVED_LINK[0], F.BROKEN_LINK)[0]
    path = repo / MOVED_LINK[0]
    path.write_text(_insert_above_body(
        path.read_text(encoding="utf-8"),
        "A first inserted line.\nA second inserted line.\n\n"), encoding="utf-8")
    if pinned:
        _commit(repo, when=T0 + DAY)
    after = _on(_run(repo, pinned=pinned), MOVED_LINK[0], F.BROKEN_LINK)[0]
    assert after["locator"]["line_start"] == before["locator"]["line_start"] + 3
    assert _id(after) == _id(before)
    assert after["identity"] == before["identity"]


def test_two_links_to_one_target_are_one_finding(tmp_path) -> None:
    repo = _repository(tmp_path, {
        "README.md": _header() + "[a](gone.md) and [b](gone.md)\n\n[c](gone.md)\n"})
    found = _on(_run(repo), "README.md", F.BROKEN_LINK)
    assert [(f["identity"], f["locator"]["line_start"]) for f in found] == [
        ({"target": "gone.md"}, 4)]


# --------------------------------------------------------------------------
# links (ruling 4; OQ-H-10)
# --------------------------------------------------------------------------

LINKS = {
    "README.md": _header() + PROSE + (
        "[fenced is code, never judged] below:\n\n"
        "```\n[a](in-a-fence.md)\n```\n\n"
        "~~~~\n[b](in-a-tilde-fence.md)\n~~~~\n\n"
        "Inline code `[c](in-a-span.md)` is code too.\n"
        "[external](https://example.invalid/missing.md) and "
        "[mail](mailto:someone@example.invalid) and "
        "[scheme-relative](//example.invalid/missing.md) and "
        "[fragment only](#a-section) and [empty]().\n"
        "[fragment stripped](notes/kept.md#a-section) and "
        "[query stripped](notes/kept.md?view=1).\n"
        "[root relative](/notes/kept.md) and [a folder](notes/) "
        "and [percent](notes/two%20words.md).\n"
        "[engine file](health/packs.yaml) and "
        "[settings](ideation/dashboard/model-declarations.yaml) and "
        "[config](.opendox/governance.yaml).\n"
        "[outside](../outside.md) and [ambiguous](gone/twin.md) and "
        "[broken with fragment](gone.md#part).\n"
        "![an image](pictures/missing.png)\n\n"
        "[ref]: gone-by-reference.md \"a title\"\n"
        "[^note]: a footnote, never a link.\n"),
    "notes/kept.md": _header() + PROSE,
    "notes/two words.md": _header() + PROSE,
    "a/twin.md": _header() + PROSE + "[up](../README.md)\n",
    "b/twin.md": _header() + PROSE + "[up](../README.md)\n",
    "health/packs.yaml": "schema_version: 1\n",
    "health/dispositions.yaml": "schema_version: 1\n",
    ".opendox/governance.yaml": "schema_version: 1\n",
    "ideation/dashboard/model-declarations.yaml": "schema_version: 1\n",
}


@pytest.fixture(scope="module")
def links_run(tmp_path_factory):
    repo = _repository(tmp_path_factory.mktemp("links"), LINKS)
    return _on(_run(repo), "README.md", F.BROKEN_LINK)


def test_only_the_judged_broken_targets_are_findings(links_run) -> None:
    got = sorted(f["identity"].get("target") for f in links_run)
    assert got == sorted(["../outside.md", "gone/twin.md", "gone.md#part",
                          "pictures/missing.png", "gone-by-reference.md"])


def test_code_external_fragment_only_and_empty_targets_are_not_judged(
        links_run) -> None:
    targets = {f["identity"].get("target") for f in links_run}
    for skipped in ("in-a-fence.md", "in-a-tilde-fence.md", "in-a-span.md",
                    "https://example.invalid/missing.md",
                    "//example.invalid/missing.md", "#a-section", ""):
        assert skipped not in targets


def test_a_fragment_or_query_is_stripped_before_resolving(links_run) -> None:
    targets = {f["identity"].get("target") for f in links_run}
    assert "notes/kept.md#a-section" not in targets
    assert "notes/kept.md?view=1" not in targets


def test_a_link_to_an_engine_settings_or_structured_file_is_not_broken(
        links_run) -> None:
    targets = {f["identity"].get("target") for f in links_run}
    assert not targets & {"health/packs.yaml", ".opendox/governance.yaml",
                          "ideation/dashboard/model-declarations.yaml"}


def test_classes_moved_ambiguous_absent_and_outside(links_run) -> None:
    by = {f["identity"]["target"]: f for f in links_run}
    assert by["gone/twin.md"]["resolution_class"] == HUMAN_ONLY
    assert by["gone/twin.md"]["evidence"]["cause"] == "ambiguous"
    assert by["../outside.md"]["resolution_class"] == HUMAN_ONLY
    assert by["../outside.md"]["evidence"]["cause"] == "outside-corpus"
    assert by["gone.md#part"]["resolution_class"] == HUMAN_ONLY
    assert by["gone.md#part"]["evidence"]["cause"] == "absent"


def test_an_over_long_or_nul_target_becomes_its_digest(tmp_path) -> None:
    long_target = "missing/" + "a" * 240 + ".md"
    nul_target = "a\x00b.md"
    repo = _repository(tmp_path, {"README.md": _header() + PROSE + (
        f"[long]({long_target})\n[nul](<{nul_target}>)\n")})
    found = _on(_run(repo), "README.md", F.BROKEN_LINK)
    want = sorted(hashlib.sha256(t.encode("utf-8")).hexdigest()
                  for t in (long_target, nul_target))
    assert sorted(f["identity"]["target_sha256"] for f in found) == want
    for f in found:
        assert set(f["identity"]) == {"target_sha256"}
        assert "target" not in f["locator"]
        assert not any("\x00" in s for s in _walk_strings(f))
    _admit(found)


# --------------------------------------------------------------------------
# orphans (ruling 4; OQ-H-16)
# --------------------------------------------------------------------------

def test_entry_documents_are_exempt_at_any_depth_case_insensitively(
        tmp_path) -> None:
    repo = _repository(tmp_path, {
        "docs/README.MD": _header() + PROSE,
        "notes/Index.md": _header() + PROSE,
        "notes/readme-notes.md": _header() + PROSE,
        "self.md": _header() + PROSE + "[me](self.md)\n",
    })
    orphans = sorted(f["path"] for f in _run(repo, families=(F.ORPHAN,)))
    assert orphans == ["notes/readme-notes.md", "self.md"]


# --------------------------------------------------------------------------
# front matter (ruling 2)
# --------------------------------------------------------------------------

def test_front_matter_derivable_and_underivable(tmp_path) -> None:
    repo = _repository(tmp_path, {
        "README.md": _header() + PROSE + "".join(
            f"[{n}]({n})\n" for n in ("empty-title.md", "no-summary.md",
                                      "no-heading.md", "only-h2.md")),
        "empty-title.md": "title:\nsummary: s.\n\n# The heading\n\n" + PROSE,
        "no-summary.md": _header(summary=None) + "# A heading\n\n" + PROSE,
        "no-heading.md": _header(title=None) + PROSE,
        "only-h2.md": _header(title=None) + "## Second level\n\n" + PROSE,
    })
    found = _run(repo)
    assert [(f["path"], f["kind"], f["resolution_class"], f["identity"],
             f["evidence"]["field"]) for f in found] == [
        ("empty-title.md", F.DERIVABLE_FRONT_MATTER, AUTO_FIX, {}, "title")]
    assert found[0]["locator"] == {"line_start": 4, "line_end": 4}


# --------------------------------------------------------------------------
# stubs (data-model.md § Families; ruling 6)
# --------------------------------------------------------------------------

def test_a_headerless_prose_document_is_not_an_empty_stub(tmp_path) -> None:
    repo = _repository(tmp_path, {
        "prose.md": "Plain prose, with no header at all\nand a second line\n",
        "heading-only.md": _header() + "# Only a heading\n\n## And another\n",
    })
    stubs = [(f["path"], f["kind"]) for f in _run(
        repo, families=(F.EMPTY_STUB, F.STALE_STUB))]
    assert stubs == [("heading-only.md", F.EMPTY_STUB)]


def _stale(tmp_path, *, files, age_days, author_age_days=None,
           pinned=True, edit=None):
    run_at = T0 + 400 * DAY
    stub_at = run_at - age_days * DAY
    author = None if author_age_days is None else run_at - author_age_days * DAY
    repo = _repository(tmp_path, files, when=stub_at, author=author)
    (repo / "later.txt").write_text("a later commit\n", encoding="utf-8")
    _commit(repo, when=run_at)
    if edit:
        _write(repo, edit)
    return sorted(f["path"] for f in _run(repo, pinned=pinned,
                                          families=(F.STALE_STUB,)))


STUBS = {
    "one.md": _header() + "One line.\n",
    "three.md": _header() + "# H\n\nOne.\nTwo.\nThree.\n",
    "four.md": _header() + "One.\nTwo.\nThree.\nFour.\n",
}


@pytest.mark.parametrize("age,flagged", [(179, False), (180, False),
                                         (181, True)])
def test_a_stale_stub_is_older_than_180_days_strictly(tmp_path, age,
                                                      flagged) -> None:
    want = ["one.md", "three.md"] if flagged else []
    assert _stale(tmp_path, files=STUBS, age_days=age) == want


def test_stale_reads_committer_dates_not_author_dates(tmp_path) -> None:
    assert _stale(tmp_path / "a", files=STUBS, age_days=10,
                  author_age_days=300) == []
    assert _stale(tmp_path / "b", files=STUBS, age_days=300,
                  author_age_days=10) == ["one.md", "three.md"]


def test_a_working_copy_edit_or_an_untracked_stub_is_never_stale(tmp_path
                                                                  ) -> None:
    assert _stale(tmp_path / "a", files=STUBS, age_days=300,
                  pinned=False) == ["one.md", "three.md"]
    assert _stale(tmp_path / "b", files=STUBS, age_days=300, pinned=False,
                  edit={"one.md": _header() + "One edited line.\n",
                        "new.md": _header() + "New.\n"}) == ["three.md"]


# --------------------------------------------------------------------------
# stage-location-mismatch (R2Q11 (a); ruling 3)
# --------------------------------------------------------------------------

def test_a_role_directory_locates_by_its_key_and_words_only(tmp_path) -> None:
    files = {
        "candidates/many-word.md": _header(stage="selection") + PROSE,
        "sources/short-word.md": _header(stage="candidate") + PROSE,
        "candidate/agrees.md": _header(stage="candidate") + PROSE,
        "candidate/out-of-set.md": _header(stage="draft") + PROSE,
        "candidate/no-stage.md": _header() + PROSE,
        "open submissions/label-only.md": _header(stage="candidate") + PROSE,
        "notes/candidate/too-deep.md": _header(stage="selection") + PROSE,
        "notes/outside.md": _header(stage="selection") + PROSE,
        "top-level.md": _header(stage="selection") + PROSE,
    }
    repo = _repository(tmp_path, files)
    found = _run(repo, families=(F.STAGE_LOCATION_MISMATCH,))
    assert sorted((f["path"], f["evidence"]["declared_stage"],
                   f["evidence"]["directory_role"]) for f in found) == [
        ("candidates/many-word.md", "selection", "candidate"),
        ("sources/short-word.md", "candidate", "source")]
    assert {f["resolution_class"] for f in found} == {AUTO_FIX}
    assert {f["locator"]["line_start"] for f in found} == {1}


# --------------------------------------------------------------------------
# near-duplicates (OQ-H-11, OQ-H-21; ruling 5)
# --------------------------------------------------------------------------

def _corpus_files(skip=()) -> dict[str, str]:
    return {p.relative_to(CORPUS).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(CORPUS.rglob("*")) if p.is_file()
            and p.relative_to(CORPUS).as_posix() not in skip}


def _near(found):
    return [(f["path"], f["identity"]) for f in found
            if f["kind"] == F.NEAR_DUPLICATE]


def test_ancestry_before_the_tiebreak_moves_the_finding(tmp_path) -> None:
    first, last = NEAR_DUPLICATE_PAIR
    repo = _repository(tmp_path, _corpus_files(skip={first}))
    _write(repo, {first: (CORPUS / first).read_text(encoding="utf-8")})
    _commit(repo, when=T0 + DAY)
    for pinned in (True, False):
        assert _near(_run(repo, pinned=pinned)) == [(first, {"other": last})]


def test_unrelated_adding_commits_fall_to_the_greater_path(tmp_path) -> None:
    first, last = NEAR_DUPLICATE_PAIR
    repo = _repository(tmp_path, _corpus_files(skip={first, last}))
    _git(repo, "switch", "-q", "-c", "side")
    _write(repo, {first: (CORPUS / first).read_text(encoding="utf-8")})
    _commit(repo, when=T0 + 2 * DAY)
    _git(repo, "switch", "-q", "main")
    _write(repo, {last: (CORPUS / last).read_text(encoding="utf-8")})
    _commit(repo, when=T0 + DAY)
    _git(repo, "merge", "-q", "--no-ff", "-m", "join", "side", when=T0 + 3 * DAY)
    assert _near(_run(repo)) == [(last, {"other": first})]


def test_an_uncommitted_document_is_later_than_a_committed_one(tmp_path
                                                               ) -> None:
    first, last = NEAR_DUPLICATE_PAIR
    repo = _repository(tmp_path, _corpus_files(skip={first}))
    _write(repo, {first: (CORPUS / first).read_text(encoding="utf-8")})
    assert _near(_run(repo, pinned=False)) == [(first, {"other": last})]


def test_an_over_long_other_path_becomes_its_digest(tmp_path) -> None:
    first, last = NEAR_DUPLICATE_PAIR
    long_path = "a" * 100 + "/" + "b" * 100 + ".md"
    repo = _repository(tmp_path, {
        long_path: (CORPUS / first).read_text(encoding="utf-8"),
        "README.md": _header() + PROSE + f"[x]({long_path})\n"})
    _write(repo, {last: (CORPUS / last).read_text(encoding="utf-8")})
    _commit(repo, when=T0 + DAY)
    found = [f for f in _run(repo) if f["kind"] == F.NEAR_DUPLICATE]
    digest = hashlib.sha256(long_path.encode("utf-8")).hexdigest()
    assert [(f["path"], f["identity"]) for f in found] == [
        (last, {"other_sha256": digest})]
    _admit(found)


def _bodies(base: Path) -> dict[str, str]:
    return {f"{base.name}/{p.relative_to(base).as_posix()}":
            p.read_text(encoding="utf-8")
            for p in sorted(base.rglob("*")) if p.is_file()}


def test_the_threshold_sits_inside_the_measured_margin() -> None:
    """OQ-H-21: every pair over health-corpus and plain-documents, scored as
    the family scores it. The planted pair is above the threshold and every
    other pair below it, each by at least the declared margin."""
    texts = {**_bodies(CORPUS), **_bodies(PLAIN)}
    planted = {f"{CORPUS.name}/{name}" for name in NEAR_DUPLICATE_PAIR}
    scores = {(a, b): F.similarity(texts[a], texts[b])
              for a, b in itertools.combinations(sorted(texts), 2)}
    pair = scores.pop(tuple(sorted(planted)))
    highest = max(scores.values())
    assert len(scores) + 1 == 190
    assert pair - F.NEAR_DUPLICATE_THRESHOLD >= 0.1
    assert F.NEAR_DUPLICATE_THRESHOLD - highest >= 0.1
    assert (round(pair, 4), round(highest, 4)) == F.NEAR_DUPLICATE_MEASURED


# --------------------------------------------------------------------------
# the engine files and configuration (OQ-H-15; ruling 1, ruling 8)
# --------------------------------------------------------------------------

def test_the_excluded_paths_are_the_settings_and_the_engine_files() -> None:
    assert F.EXCLUDED_PATHS == (*SETTINGS_DOCUMENTS, "health/dispositions.yaml",
                                "health/packs.yaml")
    assert F.JUDGED_SUFFIXES == tuple(sorted(
        s for s, k in KINDS_BY_SUFFIX.items() if k == "text"))


def test_engine_files_and_configuration_are_neither_listed_nor_judged(
        tmp_path) -> None:
    repo = _repository(tmp_path, {
        "README.md": _header() + PROSE,
        "health/dispositions.yaml": "schema_version: 1\n",
        "health/packs.yaml": "schema_version: 1\n",
        ".opendox/governance.yaml": "schema_version: 1\n",
        "notes/settings.json": "{}\n",
    })
    adapter = F.default_adapter()
    for revision in (_git(repo, "rev-parse", "HEAD").strip(), None):
        corpus = adapter.resolve(CorpusRef(name="fixture", location=str(repo),
                                           revision=revision))
        listed = {d.key for d in adapter.list_documents(corpus)}
        assert not listed & set(F.EXCLUDED_PATHS), listed
    assert _run(repo) == [] and _run(repo, pinned=False) == []


# --------------------------------------------------------------------------
# nothing written, and nothing heavy imported
# --------------------------------------------------------------------------

def _digest_tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_run_writes_nothing_under_git_or_the_working_tree(tmp_path) -> None:
    repo = fresh_repository(CORPUS, tmp_path)
    _git(repo, "update-index", "--refresh")
    edited = repo / PLANTED["human-only-finding"]
    edited.write_text(edited.read_text(encoding="utf-8") + "One more line.\n",
                      encoding="utf-8")
    (repo / "untracked.md").write_text(_header() + "New.\n", encoding="utf-8")
    git_before, tree_before = _digest_tree(repo / ".git"), _digest_tree(repo)
    _run(repo, pinned=True)
    _run(repo, pinned=False)
    assert _digest_tree(repo / ".git") == git_before
    assert _digest_tree(repo) == tree_before


def _module_file(module: str) -> Path | None:
    base = SRC.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _closure(start: str) -> tuple[set[str], set[str]]:
    """Every `opendox` module `start` reaches, lazy imports included, read
    with `import_scan.names_imported_by`, and every other top-level name."""
    seen: set[str] = set()
    outside: set[str] = set()
    todo = [start]
    while todo:
        module = todo.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_file(module)
        if path is None:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            for name in names_imported_by(node, members=True):
                if not name.startswith("opendox"):
                    outside.add(name.split(".")[0])
                    continue
                parts = name.split(".")
                todo += [".".join(parts[:i]) for i in range(1, len(parts) + 1)
                         if _module_file(".".join(parts[:i]))]
    return {m for m in seen if _module_file(m)}, outside


def test_the_import_closure_holds_no_model_or_driver_module() -> None:
    reached, outside = _closure("opendox.health.families")
    assert "opendox.health.families" in reached
    assert not reached & set(MODEL_MODULES), sorted(reached)
    assert not outside & set(DRIVERS), sorted(outside)
    direct = {n for node in ast.walk(ast.parse(FAMILIES_PY.read_text(encoding="utf-8")))
              for n in names_imported_by(node, members=True)}
    assert not {n for n in direct for f in (*DIRECT_FORBIDDEN, *DRIVERS)
                if n == f or n.startswith(f + ".")}, sorted(direct)


def test_a_fresh_interpreter_loads_no_model_or_driver_module() -> None:
    probe = ("import sys, opendox.health.families; "
             "print('\\n'.join(sorted(sys.modules)))")
    done = subprocess.run([sys.executable, "-I", "-c", probe], check=True,
                          capture_output=True, text=True)
    loaded = set(done.stdout.split())
    assert not loaded & {*MODEL_MODULES, *DRIVERS}, sorted(loaded)


def test_the_health_package_init_imports_nothing() -> None:
    tree = ast.parse(HEALTH_INIT.read_text(encoding="utf-8"))
    assert len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)
    assert isinstance(tree.body[0].value, ast.Constant)
    assert isinstance(tree.body[0].value.value, str)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
