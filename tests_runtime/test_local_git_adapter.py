"""RULING C3's plain local git repository, held to the adapter Protocol.

`split-opendox-two-layer-product` § 3.7's neutral conformance corpus needs
exactly this object at exactly this import path, so the conformance is asserted
here rather than described: `isinstance` against the `runtime_checkable`
Protocol, the closed six-member surface, each operation's declared refusal
kinds, and the one property the interface is emphatic about — that `write_back`
"never touches the corpus tree".

HERMETIC: the standard library, `opendox.corpus_adapter` (stdlib-only by its
own declaration) and `opendox.runtime.local_git_adapter` /
`repository_act.initialize_repository`, which are stdlib-only by this package's
import-weight contract. It therefore runs in the REQUIRED `validate` job, which
is the strongest place § 3.6's proof can sit.

It does shell out to `git`, and skips with the reason printed where there is
none.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import random
import subprocess
from pathlib import Path

import pytest

from opendox import corpus_adapter as ca
from opendox.runtime import local_git_adapter as lga
from opendox.runtime.repository_act import initialize_repository

pytestmark = pytest.mark.skipif(
    not lga.git_available(),
    reason="`git` is not on PATH, so RULING C3's plain local git repository "
           "cannot be created; these suites are skipped rather than failed")

ACTOR = "Student One"


#: The environment EVERY `git` this module runs gets, and it is not a
#: convenience.
#:
#: `git commit-tree` needs a committer, and this module's one direct use of it
#: (the gitlink listing case, round 10) took it from the developer's GLOBAL
#: config — which every workstation here has and NO CI runner does. The case
#: therefore passed for its author and exited 128 in both jobs, which is the
#: third instance on this act of one rule: a result measured under an
#: environment the job does not have is not that job's result (the first was
#: `importorskip` in a job that installs `.[test]` alone; the second was a
#: hermetic figure measured with the `runtime` extra present).
#:
#: So the global and system config files are taken OUT of the picture as well
#: as an identity put in: with `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` pointed
#: at nothing, a workstation and a runner see the same git, and a case that
#: depends on ambient configuration fails in both places instead of one.
_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "openDox tests",
    "GIT_AUTHOR_EMAIL": "tests@opendox.invalid",
    "GIT_COMMITTER_NAME": "openDox tests",
    "GIT_COMMITTER_EMAIL": "tests@opendox.invalid",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True,
                          check=True, env=_GIT_ENV).stdout.strip()


#: THE PROCESS'S OWN ENVIRONMENT, and not only `_git`'s. The mapping above is
#: passed to the `subprocess.run` in `_git`, which is this file's DIRECT use of
#: git — but the code under test runs git through `GitRunner`, which inherits
#: `os.environ` and builds its own environment from it. So the hermetic claim
#: was true of the assertions and false of the act they assert about: a
#: developer's global `url.<base>.insteadOf`, `init.templateDir` or
#: `protocol.*.allow` still reached every repository this suite creates,
#: configures and pushes (Copilot review of openDox-code#26, round 14,
#: suppressed). `monkeypatch.setenv` puts the same settings where the runner
#: will find them, and `GitRunner`'s sanitizer keeps them: it strips the
#: repository-SELECTING variables (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_CONFIG`…)
#: and never `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM`, which are the two that
#: make a workstation and a runner see one git.
@pytest.fixture(autouse=True)
def _hermetic_git_for_the_whole_process(
        monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _GIT_ENV.items():
        if name.startswith("GIT_"):
            monkeypatch.setenv(name, value)


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    """A repository created by the product's own act, not by hand."""
    location = tmp_path / "project-1"
    initialize_repository(location, project_id="project-1", actor=ACTOR)
    return location


@pytest.fixture()
def adapter() -> lga.LocalGitCorpus:
    return lga.LocalGitCorpus()


def _resolve(adapter: lga.LocalGitCorpus, repository: Path,
             revision: str | None = None) -> ca.ResolvedCorpus:
    return adapter.resolve(ca.CorpusRef(name=repository.name,
                                        location=str(repository),
                                        revision=revision))


# -- conformance -------------------------------------------------------------


def test_the_adapter_conforms_to_the_corpus_adapter_protocol(adapter) -> None:
    """The § 3.7 assertion, and it is structural.

    `corpus_adapter.py`'s own header: "STRUCTURAL conformance lets an
    implementation authored elsewhere conform without importing anything from
    this repository". This implementation imports the interface's DATA TYPES
    and inherits nothing, which is the conformance that Protocol exists for.
    """
    assert isinstance(adapter, ca.CorpusAdapter)
    assert ca.CorpusAdapter not in lga.LocalGitCorpus.__mro__, (
        "the adapter INHERITS from the Protocol; conformance here must be "
        "structural, or the seam becomes exactly the dependency it was drawn "
        "to remove")


def test_the_surface_is_the_closed_six_and_no_seventh(adapter) -> None:
    assert sorted(ca.CorpusAdapter.__protocol_attrs__) == sorted(ca.OPERATIONS)
    for operation in ca.OPERATIONS:
        assert callable(getattr(adapter, operation)), operation
    public = {name for name in dir(adapter)
              if not name.startswith("_") and callable(getattr(adapter, name))}
    assert public == set(ca.OPERATIONS), (
        f"the adapter exposes {sorted(public - set(ca.OPERATIONS))} beyond the "
        "closed operation set; a seventh member is a seam that leaks")


def test_the_import_path_is_the_one_section_3_7_will_use() -> None:
    assert lga.__name__ == "opendox.runtime.local_git_adapter"
    assert lga.LocalGitCorpus.__module__ == "opendox.runtime.local_git_adapter"
    assert lga.ADAPTER_NAME == "local-git"
    assert lga.WRITE_PATH == "local-git-commit"


# -- the act's product -------------------------------------------------------


def test_a_created_repository_is_a_valid_git_repository_with_one_commit(
        repository: Path) -> None:
    assert _git(repository, "rev-parse", "--git-dir") == "."
    assert _git(repository, "cat-file", "-t", "HEAD") == "commit"
    assert _git(repository, "rev-list", "--count", "HEAD") == "1"
    # EMPTY on purpose: the repository's whole content is what its owner writes.
    assert _git(repository, "ls-tree", "-r", "--name-only", "HEAD") == ""
    assert _git(repository, "symbolic-ref", "--short", "HEAD") == "main"


def test_a_created_repository_is_bare_so_there_is_one_answer_to_its_content(
        repository: Path) -> None:
    """The decision `local_git_adapter`'s header argues, asserted.

    A checkout beside the history would be a second answer to "what does this
    project contain" that the adapter is forbidden to keep up to date.
    """
    assert _git(repository, "rev-parse", "--is-bare-repository") == "true"
    assert not (repository / ".git").exists()


def test_the_first_commit_records_the_act_and_its_ruling(repository: Path) -> None:
    message = _git(repository, "log", "-1", "--format=%B")
    assert "first-class act" in message
    assert "5544381563" in message, "the commit does not cite RULING C3"
    assert f"Created-By: {ACTOR}" in message


def test_the_committer_address_is_reserved_and_cannot_route(
        repository: Path) -> None:
    """A display name must never become a plausible, wrong address in history."""
    email = _git(repository, "log", "-1", "--format=%ae")
    assert email.endswith("@opendox.invalid")


# -- resolve -----------------------------------------------------------------


def test_resolve_answers_the_write_path_before_the_first_write(
        adapter, repository: Path) -> None:
    corpus = _resolve(adapter, repository)
    assert corpus.write_path == lga.WRITE_PATH
    assert corpus.write_path_available is True
    assert corpus.scopes == (ca.SCOPE_ALL,)
    assert corpus.revision == _git(repository, "rev-parse", "HEAD")
    assert corpus.location == str(repository.resolve())


def test_an_absent_location_refuses_and_never_returns_an_empty_corpus(
        adapter, tmp_path: Path) -> None:
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="gone",
                                     location=str(tmp_path / "nowhere")))
    assert caught.value.refusal.kind == ca.CORPUS_ABSENT
    assert "nowhere" in caught.value.refusal.subject


def test_a_directory_that_is_not_a_repository_refuses(adapter,
                                                      tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="plain", location=str(plain)))
    assert caught.value.refusal.kind == ca.CORPUS_UNCLASSIFIABLE


def test_an_unserveable_revision_refuses_rather_than_falling_back(
        adapter, repository: Path) -> None:
    with pytest.raises(ca.CorpusRefused) as caught:
        _resolve(adapter, repository, revision="0" * 40)
    assert caught.value.refusal.kind == ca.REVISION_UNKNOWN


# -- list --------------------------------------------------------------------


def test_an_empty_corpus_lists_as_a_legal_empty_tuple(adapter,
                                                      repository: Path) -> None:
    assert adapter.list_documents(_resolve(adapter, repository)) == ()


def test_an_undeclared_scope_refuses_rather_than_widening(adapter,
                                                          repository: Path) -> None:
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.list_documents(_resolve(adapter, repository), scope="everything")
    assert caught.value.refusal.kind == ca.SCOPE_UNKNOWN


# -- write back --------------------------------------------------------------


def _write(adapter, repository: Path, key: str, content: bytes,
           reason: str = "") -> tuple[ca.WriteReceipt, ca.ResolvedCorpus]:
    corpus = _resolve(adapter, repository)
    receipt = adapter.write_back(corpus, ca.DocumentId(repository.name, key),
                                 content, actor=ACTOR,
                                 basis_revision=corpus.revision or "",
                                 reason=reason)
    return receipt, corpus


def test_a_write_is_a_commit_and_the_receipt_names_the_declared_path(
        adapter, repository: Path) -> None:
    receipt, before = _write(adapter, repository, "ideation/first.md", b"# one\n")
    assert receipt.dispatched_to == lga.WRITE_PATH
    assert _git(repository, "cat-file", "-t", receipt.correlation_id) == "commit"
    assert _git(repository, "rev-parse", "HEAD") == receipt.correlation_id
    assert _git(repository, "rev-parse", "HEAD^") == before.revision


def test_a_write_materializes_no_file_on_disk(adapter, repository: Path) -> None:
    """`corpus_adapter.write_back`'s emphatic rule, measured.

    "It never touches the corpus tree — an implementation that does is refused
    even where the bytes would be identical, because the gate is the act of
    passing through the path and not the shape of the result."

    So after a write the document is IN THE HISTORY and nowhere on disk as a
    file: no `ideation/` directory appears, and the repository's entries are
    still git's own.
    """
    before = sorted(p.name for p in repository.iterdir())
    receipt, _ = _write(adapter, repository, "ideation/first.md", b"# one\n")
    after = sorted(p.name for p in repository.iterdir())
    assert before == after, (
        f"write_back created {sorted(set(after) - set(before))} on disk")
    assert not (repository / "ideation").exists()
    assert _git(repository, "ls-tree", "-r", "--name-only",
                receipt.correlation_id) == "ideation/first.md"
    # And the temporary index left nothing behind.
    assert not list(repository.glob("opendox-index-*"))


def test_the_written_bytes_are_readable_at_the_new_revision(
        adapter, repository: Path) -> None:
    receipt, _ = _write(adapter, repository, "ideation/first.md", b"# one\n")
    corpus = _resolve(adapter, repository)
    assert corpus.revision == receipt.correlation_id
    document = ca.DocumentId("project-1", "ideation/first.md")
    assert adapter.list_documents(corpus) == (document,)
    assert adapter.read(corpus, document).content == b"# one\n"


def test_an_earlier_revision_still_reads_the_earlier_bytes(
        adapter, repository: Path) -> None:
    first, _ = _write(adapter, repository, "ideation/first.md", b"# one\n")
    second, _ = _write(adapter, repository, "ideation/first.md", b"# two\n")
    corpus = _resolve(adapter, repository)
    document = ca.DocumentId("project-1", "ideation/first.md")
    assert adapter.read(corpus, document, revision=first.correlation_id
                        ).content == b"# one\n"
    assert adapter.read(corpus, document, revision=second.correlation_id
                        ).content == b"# two\n"


def test_the_commit_records_the_basis_revision_it_was_proposed_against(
        adapter, repository: Path) -> None:
    receipt, before = _write(adapter, repository, "ideation/first.md",
                             b"# one\n", reason="the first save")
    message = _git(repository, "log", "-1", "--format=%B", receipt.correlation_id)
    assert f"Basis-Revision: {before.revision}" in message
    assert f"Dispatched-By: {ACTOR}" in message
    assert f"Write-Path: {lga.WRITE_PATH}" in message
    assert "the first save" in message


def test_a_stale_corpus_loses_its_dispatch_rather_than_overwriting(
        adapter, repository: Path) -> None:
    """The ref moves by COMPARE-AND-SWAP, so a second writer cannot clobber."""
    stale = _resolve(adapter, repository)
    _write(adapter, repository, "ideation/first.md", b"# one\n")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(stale, ca.DocumentId("project-1", "ideation/first.md"),
                           b"# clobber\n", actor=ACTOR,
                           basis_revision=stale.revision or "")
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    corpus = _resolve(adapter, repository)
    assert adapter.read(corpus, ca.DocumentId("project-1", "ideation/first.md")
                        ).content == b"# one\n"


def test_a_read_only_corpus_refuses_the_declared_kind(adapter,
                                                      repository: Path) -> None:
    """`resolve` already said so, so `write_back` says the same thing."""
    corpus = dataclasses.replace(_resolve(adapter, repository), write_path=None)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus, ca.DocumentId("project-1", "x.md"), b"x",
                           actor=ACTOR, basis_revision=corpus.revision or "")
    assert caught.value.refusal.kind == ca.CORPUS_READ_ONLY


def test_an_unreachable_write_path_leaves_the_document_unsaved(
        adapter, repository: Path) -> None:
    corpus = dataclasses.replace(_resolve(adapter, repository),
                                 write_path_available=False)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus, ca.DocumentId("project-1", "x.md"), b"x",
                           actor=ACTOR, basis_revision=corpus.revision or "")
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert adapter.list_documents(_resolve(adapter, repository)) == ()


# -- read --------------------------------------------------------------------


def test_an_unknown_document_refuses_and_is_never_an_empty_read(
        adapter, repository: Path) -> None:
    _write(adapter, repository, "ideation/first.md", b"# one\n")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(_resolve(adapter, repository),
                     ca.DocumentId("project-1", "ideation/never-written.md"))
    assert caught.value.refusal.kind == ca.DOCUMENT_UNKNOWN


def test_an_unknown_revision_on_read_refuses(adapter, repository: Path) -> None:
    _write(adapter, repository, "ideation/first.md", b"# one\n")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(_resolve(adapter, repository),
                     ca.DocumentId("project-1", "ideation/first.md"),
                     revision="0" * 40)
    assert caught.value.refusal.kind == ca.REVISION_UNKNOWN


# -- classify ----------------------------------------------------------------


def test_a_recognized_shape_classifies_and_obliges_no_field(
        adapter, repository: Path) -> None:
    _write(adapter, repository, "ideation/first.md", b"# one\n")
    corpus = _resolve(adapter, repository)
    classification = adapter.classify(
        corpus, ca.DocumentId("project-1", "ideation/first.md"))
    assert classification.kind == "text"
    assert classification.required_fields == ()
    assert classification.missing_fields == ()
    assert classification.unclassifiable is None


def test_an_unrecognized_document_is_reported_and_still_listed(
        adapter, repository: Path) -> None:
    """Corpus -> refusal; DOCUMENT -> report. The interface's own rule."""
    _write(adapter, repository, "notes/scratch.bin", b"\x00\x01")
    corpus = _resolve(adapter, repository)
    document = ca.DocumentId("project-1", "notes/scratch.bin")
    classification = adapter.classify(corpus, document)
    assert classification.kind is None
    assert classification.unclassifiable is not None
    assert "notes/scratch.bin" in classification.unclassifiable
    assert document in adapter.list_documents(corpus), (
        "an unclassifiable document must stay in the listing")
    assert adapter.read(corpus, document).content == b"\x00\x01"


def test_no_home_vocabulary_appears_in_the_adapters_source() -> None:
    """RULING C2, over this implementation's own text.

    "a clinician using a descendant of this interface must never meet an
    engineering noun that arrived by way of the reader" — and the adapter is
    part of the reader.
    """
    source = Path(lga.__file__).read_text(encoding="utf-8").lower()
    for noun in ("openspec", "proposal", "ratified", "brainstorm",
                 "doc-health", "gate console", "feat-spec"):
        assert noun not in source, (
            f"{noun!r} is home vocabulary and must not appear in the adapter")


# -- check -------------------------------------------------------------------


def test_a_repository_the_act_created_has_no_divergence_to_report(
        adapter, repository: Path) -> None:
    """It is bare, so there is no second copy — `()` every time, honestly."""
    _write(adapter, repository, "ideation/first.md", b"# one\n")
    assert adapter.check(_resolve(adapter, repository)) == ()


@pytest.fixture()
def repository_with_a_checkout(tmp_path: Path) -> Path:
    """A repository openDox did NOT create: an ordinary one with a work tree."""
    location = tmp_path / "somebody-elses"
    location.mkdir()
    _git(location, "init", "--initial-branch=main", ".")
    _git(location, "config", "user.name", "Somebody")
    _git(location, "config", "user.email", "somebody@example.invalid")
    (location / "a.md").write_text("a\n", encoding="utf-8")
    (location / "b.md").write_text("b\n", encoding="utf-8")
    _git(location, "add", "a.md", "b.md")
    _git(location, "commit", "-m", "first")
    return location


def test_the_corpus_reports_its_one_verdict_and_claims_no_other(
        adapter, repository_with_a_checkout: Path) -> None:
    """RULING C3: "documents are always git-backed".

    A repository with a checkout is exactly where that can stop being true, so
    it is where the verdict has a meaning.
    """
    corpus = _resolve(adapter, repository_with_a_checkout)
    assert adapter.check(corpus) == ()

    (repository_with_a_checkout / "a.md").write_text("edited by hand\n",
                                                     encoding="utf-8")
    findings = adapter.check(corpus)
    assert [f.code for f in findings] == [lga.UNCOMMITTED_CHANGE]
    assert findings[0].subject == "a.md"
    assert findings[0].severity in ca.SEVERITIES


def test_check_narrows_to_the_subjects_it_is_given(
        adapter, repository_with_a_checkout: Path) -> None:
    corpus = _resolve(adapter, repository_with_a_checkout)
    (repository_with_a_checkout / "a.md").write_text("changed\n", encoding="utf-8")
    (repository_with_a_checkout / "b.md").write_text("changed\n", encoding="utf-8")
    assert [f.subject for f in adapter.check(corpus)] == ["a.md", "b.md"]
    only_a = adapter.check(corpus, (ca.DocumentId("somebody-elses", "a.md"),))
    assert [f.subject for f in only_a] == ["a.md"]


def test_a_repository_opendox_did_not_create_still_reads(
        adapter, repository_with_a_checkout: Path) -> None:
    corpus = _resolve(adapter, repository_with_a_checkout)
    keys = [document.key for document in adapter.list_documents(corpus)]
    assert keys == ["a.md", "b.md"]


# -- the review round's own assertions (Copilot review of openDox-code#26) ---


def test_a_missing_git_executable_is_a_named_refusal_and_not_an_oserror(
        repository: Path) -> None:
    """`subprocess.run` RAISES when the program cannot be started.

    It does not return a non-zero `CompletedProcess`, so every caller that
    translated only `GitCommandFailed` leaked a `FileNotFoundError` — an API
    500 and a CLI traceback in place of the act's named refusal.
    """
    adapter = lga.LocalGitCorpus(executable="git-that-is-not-installed")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="project-1",
                                     location=str(repository)))
    assert caught.value.refusal.kind == ca.CORPUS_UNCLASSIFIABLE
    assert "git-that-is-not-installed" in str(caught.value)


def test_a_repository_on_another_branch_gets_its_commit_on_that_branch(
        adapter, tmp_path: Path) -> None:
    """`resolve` accepts any repository, so `write_back` must not assume `main`.

    A repository whose HEAD is `master` used to receive the commit on
    `refs/heads/main` — a ref HEAD does not point at — so the receipt came back
    successful and the document was not readable through the resolved corpus.
    """
    location = tmp_path / "on-master"
    initialize_repository(location, project_id="on-master", actor=ACTOR,
                          branch="master")
    assert _git(location, "symbolic-ref", "--short", "HEAD") == "master"
    corpus = adapter.resolve(ca.CorpusRef(name="on-master",
                                          location=str(location)))
    receipt = adapter.write_back(
        corpus, ca.DocumentId("on-master", "a.md"), b"a\n", actor=ACTOR,
        basis_revision=corpus.revision or "")
    assert _git(location, "rev-parse", "refs/heads/master") == (
        receipt.correlation_id)
    assert _git(location, "rev-parse", "HEAD") == receipt.correlation_id
    after = adapter.resolve(ca.CorpusRef(name="on-master",
                                         location=str(location)))
    assert adapter.read(after, ca.DocumentId("on-master", "a.md")
                        ).content == b"a\n", (
        "the receipt was successful and the document is not readable through "
        "the resolved corpus")


def test_a_detached_head_is_refused_rather_than_guessed_at(
        adapter, repository: Path) -> None:
    corpus = _resolve(adapter, repository)
    # Detach by writing the commit id into HEAD directly, which is what a
    # `git checkout <sha>` leaves behind; `symbolic-ref --delete HEAD` is
    # refused by git on a bare repository.
    (repository / "HEAD").write_text(f"{corpus.revision}\n", encoding="utf-8")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus, ca.DocumentId("project-1", "a.md"), b"a\n",
                           actor=ACTOR, basis_revision=corpus.revision or "")
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert "detached" in str(caught.value)


def test_an_unreadable_head_refuses_rather_than_reading_as_an_empty_corpus(
        adapter, tmp_path: Path) -> None:
    """An unborn branch and a broken HEAD are different answers.

    Both made `rev-parse --verify HEAD` exit non-zero; treating them alike
    resolved a broken repository with `revision=None`, and `list_documents`
    then answered `()` — "an absent corpus and an empty corpus are different
    answers", which the interface is emphatic about.
    """
    location = tmp_path / "broken"
    initialize_repository(location, project_id="broken", actor=ACTOR)
    (location / "HEAD").write_text("this is not a ref\n", encoding="utf-8")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="broken", location=str(location)))
    assert caught.value.refusal.kind in {ca.CORPUS_UNREADABLE,
                                         ca.CORPUS_UNCLASSIFIABLE}


def test_an_unborn_branch_is_a_legal_empty_corpus(adapter,
                                                  tmp_path: Path) -> None:
    """The other half of the same distinction, and it must keep working."""
    location = tmp_path / "unborn"
    location.mkdir()
    _git(location, "init", "--bare", "--initial-branch=main", ".")
    corpus = adapter.resolve(ca.CorpusRef(name="unborn",
                                          location=str(location)))
    assert corpus.revision is None
    assert adapter.list_documents(corpus) == ()


def test_two_writes_in_one_process_do_not_share_a_temporary_index(
        adapter, tmp_path: Path) -> None:
    """The ref compare-and-swap protects the REF; the index needed its own name.

    Keyed on the process id alone, two concurrent writes to the same repository
    in ONE process shared `GIT_INDEX_FILE` and could interleave into a wrong
    tree — or one cleanup could unlink the other's index.
    """
    import threading

    location = tmp_path / "concurrent"
    initialize_repository(location, project_id="concurrent", actor=ACTOR)
    ref = ca.CorpusRef(name="concurrent", location=str(location))
    results: list[object] = []
    barrier = threading.Barrier(4)

    def _write_one(index: int) -> None:
        try:
            corpus = adapter.resolve(ref)
            barrier.wait(timeout=10)
            results.append(adapter.write_back(
                corpus, ca.DocumentId("concurrent", f"doc-{index}.md"),
                f"# {index}\n".encode(), actor=ACTOR,
                basis_revision=corpus.revision or ""))
        except Exception as exc:  # noqa: BLE001 - collected and read below
            results.append(exc)

    threads = [threading.Thread(target=_write_one, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    receipts = [r for r in results if isinstance(r, ca.WriteReceipt)]
    refusals = [r for r in results if isinstance(r, ca.CorpusRefused)]
    assert len(results) == 4
    # EXACTLY ONE WINS. All four resolved the same revision, so the
    # compare-and-swap lets one commit through and refuses the other three —
    # which is the documented behaviour, and none of them may fail any OTHER
    # way (a wrong tree, an unlinked index, an OSError).
    assert len(receipts) == 1, results
    assert len(refusals) == 3, results
    for refusal in refusals:
        assert refusal.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert not list(Path(location).glob("opendox-index-*"))
    corpus = adapter.resolve(ref)
    assert len(adapter.list_documents(corpus)) == 1


# -- Copilot's fourth round on #26 -------------------------------------------


def test_redaction_covers_the_query_and_fragment_forms_too() -> None:
    """Userinfo is not the only place a credential rides.

    `repository_act.refuse_credential_bearing_remote` REFUSES
    `https://host/r.git?token=…` for a new attachment, and this module's
    redaction saw straight through it — so a row written before that rule
    existed could still put its token into a `GitCommandFailed` message, a push
    refusal and the CLI's evidence (Copilot review of openDox-code#26).
    """
    for url in ("https://example.invalid/r.git?token=ghp_supersecret",
                "https://example.invalid/r.git?a=1&access_token=ghp_supersecret",
                "https://example.invalid/r.git#private_key=ghp_supersecret",
                "https://example.invalid/r.git?AUTH=ghp_supersecret&b=2"):
        redacted = lga.redact_credentials(f"fatal: could not read from {url}")
        assert "ghp_supersecret" not in redacted, url
        # The HOST survives: a push failure an operator cannot locate is a
        # refusal that costs more than it protects.
        assert "example.invalid" in redacted, url

    # The userinfo form is still replaced whole.
    assert lga.redact_credentials(
        "https://someone:ghp_supersecret@example.invalid/r.git"
    ) == "<redacted-url>"

    # A URL with nothing secret in it is returned unchanged.
    plain = "https://example.invalid/r.git?depth=1"
    assert lga.redact_credentials(plain) == plain


def test_the_two_halves_of_the_credential_rule_share_one_key_list() -> None:
    """What may not be STORED and what must not be PRINTED are one rule.

    They drifted apart once already, in exactly the direction that matters: the
    refusal rejected `?token=…` while the redaction did not see it. The key
    vocabulary is imported rather than retyped, and this is the assertion that
    the import is the one in use.
    """
    from opendox.runtime import repository_act

    # ONE PREDICATE NOW, not only one key list: the halves drifted a second
    # time over PERCENT-ENCODING — the refusal read raw text and the redactor
    # read raw text, each with its own regex, so `?%74oken=…` walked past both
    # (Copilot review of openDox-code#26, round 5).
    #
    # AND THE PREDICATE THIS ASSERTED WAS THE WRONG ONE, which is why the
    # halves drifted a THIRD time while this case stayed green.
    # `names_a_secret_parameter` is ONE of the redactor's three patterns and it
    # is positionally anchored, so `host=db password=hunter2 dbname=x` was
    # stored verbatim and redacted on every read-back (independent adversarial
    # review of openDox-code#26, A26-3). The importing half now asks the
    # REDACTOR, and `test_what_this_act_refuses_to_store_is_what_it_refuses_to_
    # print` states that as the biconditional over a corpus — which is the
    # assertion this one could not make.
    assert (repository_act.carries_a_credential
            is lga.carries_a_credential)
    for key in lga.SECRET_PARAMETER_KEYS.split("|"):
        for spelling in (key, key[0].upper() + key[1:],
                         # the same name with its first character
                         # percent-encoded, and then double-encoded
                         f"%{ord(key[0]):02x}{key[1:]}",
                         f"%25{ord(key[0]):02x}{key[1:]}"):
            url = f"https://example.invalid/r.git?{spelling}=ghp_supersecret"
            with pytest.raises(repository_act.RepositoryActRefused):
                repository_act.refuse_credential_bearing_remote(url)
            assert "ghp_supersecret" not in lga.redact_credentials(url), spelling
    # A parameter that is not a credential keeps its value, encoded or not.
    for plain in ("https://example.invalid/r.git?depth=1",
                  "https://example.invalid/r.git?%64epth=1"):
        assert lga.redact_credentials(plain) == plain
        repository_act.refuse_credential_bearing_remote(plain)


def test_a_corpus_that_becomes_unreadable_is_refused_and_not_reported_clean(
        adapter, tmp_path: Path) -> None:
    """`check` swallowed every git failure into `()`.

    `()` is this corpus's "no divergence and no further opinion" — a VERDICT —
    and a caller could not tell it from a repository that stopped being
    readable after it resolved (Copilot review of openDox-code#26). The
    interface is emphatic that a corpus failure is refused.
    """
    working = tmp_path / "checkout"
    working.mkdir()
    _git(working, "init", "--quiet", "--initial-branch=main", ".")
    _git(working, "config", "user.email", "s@opendox.invalid")
    _git(working, "config", "user.name", "Student")
    (working / "a.md").write_text("one\n", encoding="utf-8")
    _git(working, "add", "a.md")
    _git(working, "commit", "--quiet", "-m", "first")
    resolved = adapter.resolve(ca.CorpusRef(name="checkout",
                                            location=str(working)))
    assert adapter.check(resolved) == ()

    # The repository stops being readable AFTER it resolved.
    import shutil
    shutil.rmtree(working / ".git")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.check(resolved)
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE


def test_an_unborn_branch_and_a_broken_ref_are_different_answers(
        adapter, tmp_path: Path) -> None:
    """`show-ref` exits non-zero for both, so it cannot be the discriminator.

    Treating every non-zero as "unborn" resolved a BROKEN repository with
    `revision=None`, after which `list_documents` answered `()` — an empty
    corpus — for a repository whose refs cannot be read (Copilot review of
    openDox-code#26). `for-each-ref` tells them apart: git says nothing at all
    about an absent ref and warns about a broken one.
    """
    unborn = tmp_path / "unborn"
    initialize_repository(unborn, project_id="unborn", actor=ACTOR)
    # Remove the only commit's ref, leaving HEAD naming a branch that is absent.
    (unborn / "refs" / "heads" / "main").unlink()
    resolved = _resolve(adapter, unborn)
    assert resolved.revision is None
    assert adapter.list_documents(resolved) == ()

    broken = tmp_path / "broken"
    initialize_repository(broken, project_id="broken", actor=ACTOR)
    (broken / "refs" / "heads" / "main").write_text("not-a-sha\n",
                                                    encoding="utf-8")
    with pytest.raises(ca.CorpusRefused) as caught:
        _resolve(adapter, broken)
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE


def test_a_document_key_containing_a_comma_is_written_and_read_back(
        adapter, repository: Path) -> None:
    """`--cacheinfo mode,object,path` is parsed on the COMMAS.

    Git permits a comma in a path, and `DocumentId.key` is opaque to this
    adapter, so `notes,2026.md` was rejected or split into the wrong path
    (Copilot review of openDox-code#26). The three-argument form has no
    delimiter to collide with.
    """
    resolved = _resolve(adapter, repository)
    key = "notes,2026.md"
    document = ca.DocumentId(corpus=repository.name, key=key)
    receipt = adapter.write_back(resolved, document, b"a comma is a path\n",
                                 actor=ACTOR,
                                 basis_revision=resolved.revision or "")
    assert receipt.dispatched_to == lga.WRITE_PATH
    after = _resolve(adapter, repository)
    assert key in {d.key for d in adapter.list_documents(after)}
    assert adapter.read(after, document).content == b"a comma is a path\n"


def test_the_adapter_advertises_no_branch_it_does_not_use() -> None:
    """A parameter that cannot change an outcome is removed, not wired up.

    `__init__` took `branch=` and stored it; nothing read it, because the ref
    `write_back` moves is the one HEAD points at. `LocalGitCorpus(branch=
    "master")` therefore behaved exactly like the default while advertising a
    selection it did not make (Copilot review of openDox-code#26).
    """
    import inspect

    parameters = inspect.signature(lga.LocalGitCorpus.__init__).parameters
    assert "branch" not in parameters, (
        "the adapter takes a `branch` again; either it controls the served ref "
        "— which `_served_ref` argues it must not — or it must not be offered")
    # AND THE SURFACE IS CLOSED. It was `{self, executable}`; RULED
    # openxFactory#656 comment 5714365086 (Q-F2 (a)) added the THREE per-corpus
    # construction data, and no fourth — the list is here so a later parameter
    # is a decision somebody makes rather than one that accumulates.
    assert set(parameters) == {"self", "executable", "write_path",
                               "kind_field", "required_fields"}
    # EVERY ONE OF THEM DEFAULTS TO WHAT THIS CLASS ALREADY DID.
    assert parameters["write_path"].default == lga.WRITE_PATH
    assert parameters["kind_field"].default is None
    assert parameters["required_fields"].default == ()


# -- Copilot's sixth round on #26 --------------------------------------------


def test_the_parameter_name_is_decoded_to_a_true_fixed_point() -> None:
    """A PASS LIMIT made the docstring's own word false.

    `_decoded_parameter_name` stopped after four passes, so
    `?%2525252574oken=…` was still `%74oken` when the rule looked at it and
    both halves missed it again (Copilot review of openDox-code#26, round 6).
    The loop is unbounded and terminates because every pass that changes the
    name SHORTENS it — a decoded `%XX` is one character where three were.
    """
    from opendox.runtime import repository_act

    for layers in range(1, 9):
        # `token` with its first character encoded `layers` times over.
        name = "%74oken"
        for _ in range(layers - 1):
            name = name.replace("%", "%25", 1)
        url = f"https://example.invalid/r.git?{name}=ghp_supersecret"
        assert lga.names_a_secret_parameter(url), layers
        assert "ghp_supersecret" not in lga.redact_credentials(url), layers
        with pytest.raises(repository_act.RepositoryActRefused):
            repository_act.refuse_credential_bearing_remote(url)


def test_resolve_refuses_a_head_whose_commit_object_is_gone(
        adapter, repository: Path) -> None:
    """`rev-parse --verify HEAD` answers out of the REF STORE.

    A commit pruned or deleted after it was written still produced a
    `ResolvedCorpus` carrying a revision nothing can serve, and the refusal
    arrived later — from `list_documents` or `read` — although `resolve`'s one
    promise is that it does not hand back an unreadable corpus (Copilot review
    of openDox-code#26, round 6).
    """
    head = _git(repository, "rev-parse", "HEAD")
    loose = repository / "objects" / head[:2] / head[2:]
    assert loose.exists(), "the initial commit is not a loose object here"
    loose.unlink()

    with pytest.raises(ca.CorpusRefused) as caught:
        _resolve(adapter, repository)
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE


def test_a_head_that_names_something_other_than_a_branch_refuses_the_write(
        adapter, repository: Path) -> None:
    """`symbolic-ref HEAD` can legally name a tag or a tracking ref.

    `write_back` would then have advanced THAT with `update-ref` — a write
    moving a tag instead of a branch (Copilot review of openDox-code#26,
    round 6). `repository_act._pushable_branch` already refused the shape; the
    write path is where it costs more.
    """
    corpus = _resolve(adapter, repository)
    subprocess.run(["git", "-C", str(repository), "symbolic-ref", "HEAD",
                    "refs/tags/not-a-branch"], check=True, capture_output=True)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus,
                           ca.DocumentId(corpus=corpus.ref.name, key="a.md"),
                           b"# a\n", actor=ACTOR, basis_revision=corpus.revision)
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert "not a branch" in str(caught.value)


def test_an_unborn_corpus_whose_repository_went_away_refuses_and_is_not_empty(
        adapter, tmp_path: Path) -> None:
    """The one path that answered without asking git at all.

    An unborn repository's empty listing was returned out of the
    `ResolvedCorpus`, so a repository deleted after `resolve` gave the caller
    the answer a healthy empty repository gives — a corpus failure wearing an
    empty corpus's clothes, which this interface is emphatic about (Copilot
    review of openDox-code#26, round 6).
    """
    import shutil

    location = tmp_path / "unborn"
    location.mkdir()
    subprocess.run(["git", "init", "--quiet", "--bare", str(location)],
                   check=True)
    corpus = adapter.resolve(ca.CorpusRef(name="unborn",
                                          location=str(location)))
    assert corpus.revision is None
    assert adapter.list_documents(corpus) == ()

    shutil.rmtree(location)
    for call in (lambda: adapter.list_documents(corpus),
                 lambda: adapter.read(
                     corpus, ca.DocumentId(corpus="unborn", key="a.md"))):
        with pytest.raises(ca.CorpusRefused) as caught:
            call()
        assert caught.value.refusal.kind == ca.CORPUS_ABSENT


def test_a_key_that_looks_like_an_option_is_written_and_read_back(
        adapter, repository: Path) -> None:
    """`update-index` took the path as a positional argument.

    A valid tracked key such as `-notes.md` was therefore parsed as an OPTION,
    so `write_back` refused a path `list_documents` and `read` both serve
    (Copilot review of openDox-code#26, round 6). The path goes in on stdin
    now — `--index-info -z` — where git does no option parsing at all, which
    also keeps the comma fix by construction.
    """
    for key in ("-notes.md", "--force.md", "notes,2026.md"):
        # RE-RESOLVED each time: the write path is a compare-and-swap on the
        # branch ref, so a corpus resolved before the previous write is stale
        # by design.
        corpus = _resolve(adapter, repository)
        receipt = adapter.write_back(
            corpus, ca.DocumentId(corpus=corpus.ref.name, key=key),
            f"# {key}\n".encode(), actor=ACTOR,
            basis_revision=corpus.revision)
        assert receipt.dispatched_to
        fresh = _resolve(adapter, repository)
        assert key in [d.key for d in adapter.list_documents(fresh)], key
        assert adapter.read(
            fresh, ca.DocumentId(corpus=fresh.ref.name, key=key)
        ).content == f"# {key}\n".encode()


def test_a_tracked_path_that_is_not_utf8_is_listed_rather_than_raising(
        adapter, repository: Path) -> None:
    """git permits a pathname that is not UTF-8; a strict decode raised.

    `ls-tree -z` and `diff -z` both return raw pathname BYTES, so a repository
    holding such a file made `list_documents` and `check` raise
    `UnicodeDecodeError` instead of answering — against this module's own
    promise that a repository openDox did not create stays readable (Copilot
    review of openDox-code#26, round 6).
    """
    # Written through git's own plumbing, because the key is opaque to this
    # adapter and a bare repository has no working tree to write a file in.
    blob = subprocess.run(["git", "-C", str(repository), "hash-object", "-w",
                           "--stdin"], input=b"latin\n", capture_output=True,
                          check=True).stdout.decode().strip()
    entry = b"100644 " + blob.encode() + b"\tcaf\xe9.md\x00"
    index = repository / "opendox-test-index"
    environment = {"GIT_INDEX_FILE": str(index)}
    import os

    merged = {**os.environ, **environment}
    subprocess.run(["git", "-C", str(repository), "read-tree", "HEAD"],
                   env=merged, check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repository), "update-index", "--add",
                    "-z", "--index-info"], input=entry, env=merged, check=True,
                   capture_output=True)
    tree = subprocess.run(["git", "-C", str(repository), "write-tree"],
                          env=merged, capture_output=True,
                          check=True).stdout.decode().strip()
    commit = subprocess.run(
        ["git", "-C", str(repository), "commit-tree", tree, "-p", "HEAD",
         "-m", "a path that is not utf-8"],
        capture_output=True, check=True,
        env={**os.environ, **lga.git_identity(ACTOR)}).stdout.decode().strip()
    subprocess.run(["git", "-C", str(repository), "update-ref",
                    "refs/heads/main", commit], check=True, capture_output=True)
    index.unlink(missing_ok=True)

    corpus = _resolve(adapter, repository)
    keys = [d.key for d in adapter.list_documents(corpus)]
    assert any("caf" in key for key in keys), keys
    # And the same corpus reports findings rather than raising.
    assert adapter.check(corpus) == ()


def test_an_embedded_nul_in_a_caller_value_is_a_refusal_and_not_a_valueerror(
        adapter, repository: Path) -> None:
    """`subprocess.run` raises BEFORE any process exists.

    `DocumentId.key`, `actor` and `reason` are caller-controlled and reach
    `subprocess.run`, and a NUL in any of them makes Python raise `ValueError`
    — which the runner's normalization did not catch, so the API returned a
    500 and the CLI printed a traceback in place of `write_back`'s declared
    refusal (Copilot review of openDox-code#26, round 6).
    """
    corpus = _resolve(adapter, repository)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus,
                           ca.DocumentId(corpus=corpus.ref.name, key="a.md"),
                           b"# a\n", actor="Student\x00One",
                           basis_revision=corpus.revision)
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE


# -- Copilot's eighth round on #26 -------------------------------------------


def test_a_plus_in_a_parameter_name_is_not_a_five_hundred() -> None:
    """`unquote_plus` turns `+` into a SPACE, which changes nothing's length.

    The decode loop asserted that every changing pass SHORTENS the name, so a
    perfectly ordinary `...?a+b=1` raised `AssertionError` out of both halves
    of the credential rule — a 500 where the answer was "this is not a
    credential" (Copilot review of openDox-code#26, round 8).
    """
    from opendox.runtime import repository_act

    harmless = "https://example.invalid/r.git?a+b=1&depth=1#frag+ment=2"
    assert lga.names_a_secret_parameter(harmless) is False
    assert lga.redact_credentials(harmless) == harmless
    repository_act.refuse_credential_bearing_remote(harmless)

    # And the fixed point is still reached where it matters.
    hidden = "https://example.invalid/r.git?%2525252574oken=ghp_supersecret"
    assert lga.names_a_secret_parameter(hidden)
    assert "ghp_supersecret" not in lga.redact_credentials(hidden)


def test_an_option_shaped_revision_cannot_become_a_git_option(
        adapter, repository: Path) -> None:
    """`revision` is opaque and caller-controlled.

    An argument beginning with `--` is read by `rev-parse` as an OPTION, so
    resolving "a revision" could perform an unintended git operation (Copilot
    review of openDox-code#26, round 8). `--end-of-options` is git's own
    answer, and this is the assertion that it stays there.
    """
    corpus = _resolve(adapter, repository)
    for revision in ("--version", "--output=/tmp/opendox-should-not-exist",
                     "--all"):
        with pytest.raises(ca.CorpusRefused) as caught:
            adapter.read(corpus,
                         ca.DocumentId(corpus=corpus.ref.name, key="a.md"),
                         revision=revision)
        assert caught.value.refusal.kind == ca.REVISION_UNKNOWN, revision
    assert not Path("/tmp/opendox-should-not-exist").exists()


def test_a_symlink_swapped_in_after_the_check_cannot_be_written_through(
        tmp_path: Path) -> None:
    """The check and the create were two acts, with a window between them.

    `refuse_unusable_location` refuses a symlink, and `mkdir(exist_ok=True)`
    then FOLLOWED one that appeared afterwards — `git init --bare .` writing
    the project's history into whatever the link pointed at, which is the
    adoption the refusal exists to prevent (Copilot review of openDox-code#26,
    round 8). The leaf is created EXCLUSIVELY now (an exclusive `mkdir` cannot
    follow a link) and the directory git is handed is re-opened NO-FOLLOW.

    The race is made deterministic by doing what the racing process would do,
    at the only moment it could: after the check, before the create.
    """
    import os

    from opendox.runtime import repository_act as act

    elsewhere = tmp_path / "somebody-elses-tree"
    elsewhere.mkdir()
    location = tmp_path / "project-raced"

    real_refuse = act.refuse_unusable_location

    def _check_then_swap(path) -> None:
        real_refuse(path)
        # The window: the path was absent and legal a moment ago.
        os.symlink(elsewhere, path)

    act.refuse_unusable_location = _check_then_swap
    try:
        with pytest.raises(act.RepositoryActRefused):
            act.initialize_repository(location, project_id="raced", actor=ACTOR)
    finally:
        act.refuse_unusable_location = real_refuse

    assert list(elsewhere.iterdir()) == [], (
        "the act wrote the repository through the symlink")


# -- Copilot's ninth round on #26 --------------------------------------------


def test_a_nul_in_a_document_key_is_refused_and_not_truncated(
        adapter, repository: Path) -> None:
    """The index protocol's record terminator is NUL, and the key is opaque.

    `a.md\\0b` would have been truncated to `a.md` — or read as two records —
    and the receipt would have named a path the write did not make (Copilot
    review of openDox-code#26, round 9).
    """
    corpus = _resolve(adapter, repository)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus,
                           ca.DocumentId(corpus=corpus.ref.name, key="a.md\0b"),
                           b"# a\n", actor=ACTOR,
                           basis_revision=corpus.revision)
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    # And nothing of either spelling arrived.
    fresh = _resolve(adapter, repository)
    assert [d.key for d in adapter.list_documents(fresh)] == []


def test_a_corpus_that_went_away_is_not_reported_as_a_missing_document(
        adapter, repository: Path) -> None:
    """`cat-file` fails the same way for both, and they are different answers.

    A repository deleted after it resolved, or a commit pruned out from under
    the resolved revision, was reported as `DOCUMENT_UNKNOWN` — "this document
    is not here" for a corpus that cannot answer for any document at all
    (Copilot review of openDox-code#26, round 9).
    """
    import shutil

    corpus = _resolve(adapter, repository)
    document = ca.DocumentId(corpus=corpus.ref.name, key="never-written.md")
    # A readable corpus really does say the document is unknown.
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(corpus, document)
    assert caught.value.refusal.kind == ca.DOCUMENT_UNKNOWN

    shutil.rmtree(repository)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(corpus, document)
    assert caught.value.refusal.kind == ca.CORPUS_ABSENT


# -- Copilot's tenth round on #26 --------------------------------------------


def test_a_bracketed_ipv6_scp_remote_is_redacted_like_any_other_userinfo(
) -> None:
    r"""A PIN, not a fix: Copilot's round-10 finding here is measurably wrong.

    The review reports that `user@[::1]:repo` "is not replaced by
    `<redacted-url>`" because the host class excludes `:`. Measured on the
    landed pattern, it IS replaced, and by that very exclusion: the host class
    matches the `[`, the next character is the `:` the SCP form requires, and
    the trailing `[^\s]*` takes the rest of the run — so the whole remote goes,
    exactly as `git@host:repo` does. The refusing half
    (`repository_act._SCP_USERINFO`) matches for the same reason, and every
    bracketed IPv6 literal begins with a hex group or a colon, so no shape of
    it can avoid the pattern.

    No code changed for that finding. This test exists because a property a
    pattern holds BY LUCK is a property the next edit to it can lose, and
    because the next reader deserves the measurement rather than the review's
    sentence.
    """
    for url in ("someone@[::1]:repo.git",
                "git@[2001:db8::1]:opensoft/openDox.git",
                "someone@[fe80::1%25eth0]:r.git".replace("%25", ".")):
        redacted = lga.redact_credentials(f"fatal: could not read from {url}")
        assert "someone@" not in redacted and "git@[" not in redacted, url
        assert "<redacted-url>" in redacted, url

    # The ordinary SCP form and a plain URL are unchanged in their treatment.
    assert lga.redact_credentials("git@example.invalid:r.git") == "<redacted-url>"
    plain = "https://example.invalid/r.git?depth=1"
    assert lga.redact_credentials(plain) == plain


def test_whitespace_around_a_parameter_name_does_not_hide_it() -> None:
    """`urlsplit` accepts a raw space INSIDE a URL; the name class did not.

    `https://host/x? token=ghp_secret` parses as a query carrying `token`, and
    both halves of the credential rule saw no parameter at all — so the value
    went into `project_repositories.remote_url` and back out to every
    authenticated caller (Copilot review of openDox-code#26, round 10). Spaces
    and tabs are stepped over now rather than admitted into the name.
    """
    for url in ("https://example.invalid/r.git? token=ghp_supersecret",
                "https://example.invalid/r.git?token =ghp_supersecret",
                "https://example.invalid/r.git?a=1& access_token=ghp_supersecret",
                "https://example.invalid/r.git#\tprivate_key=ghp_supersecret"):
        assert lga.names_a_secret_parameter(url), url
        redacted = lga.redact_credentials(f"fatal: could not read from {url}")
        assert "ghp_supersecret" not in redacted, url
        assert "example.invalid" in redacted, url

    # AND THE ROUND-8 CASE STILL HOLDS: `+` is a space in a parameter name and
    # is not a credential, and asking the question must not raise.
    assert not lga.names_a_secret_parameter("https://example.invalid/r.git?a+b=1")
    assert not lga.names_a_secret_parameter("https://example.invalid/r.git?depth=1")


def test_a_listing_omits_a_gitlink_because_read_cannot_serve_one(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """`ls-tree -r` lists submodule gitlinks, and `read` asks `cat-file blob`.

    So a repository containing a submodule advertised a document this adapter
    then refused as `DOCUMENT_UNKNOWN` — a listing that contradicts the read
    beside it, which the interface's contract does not permit (Copilot review
    of openDox-code#26, round 10, suppressed twice). The listing is filtered to
    BLOBS; a submodule's content belongs to another repository and inventing a
    representation for it here would be this adapter answering for a corpus it
    does not manage.
    """
    head = _git(repository, "rev-parse", "HEAD")
    blob = subprocess.run(["git", "-C", str(repository), "hash-object", "-w",
                           "--stdin"], input=b"# notes\n", capture_output=True,
                          check=True).stdout.decode().strip()
    tree = subprocess.run(["git", "-C", str(repository), "mktree"],
                          input=(f"100644 blob {blob}\tnotes.md\n"
                                 f"160000 commit {head}\tsub\n").encode(),
                          capture_output=True, check=True).stdout.decode().strip()
    commit = _git(repository, "commit-tree", tree, "-p", head, "-m",
                  "a tree with a gitlink in it")
    _git(repository, "update-ref", "refs/heads/main", commit)

    corpus = _resolve(adapter, repository)
    keys = [document.key for document in adapter.list_documents(corpus)]
    assert "notes.md" in keys
    assert "sub" not in keys, (
        "a gitlink was advertised as a document this adapter cannot read")
    # And the contract the filter keeps: what the listing omits, the read
    # refuses — rather than the listing promising what the read denies.
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(corpus, ca.DocumentId(corpus=corpus.ref.name,
                                           key="sub"))
    assert caught.value.refusal.kind == ca.DOCUMENT_UNKNOWN


def test_a_revision_carrying_a_nul_is_the_protocols_own_refusal(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """An embedded NUL makes `subprocess.run` raise before any process exists.

    `GitRunner.run` turns that into `GitCommandFailed` by design, and
    `_resolve_revision` read a returncode — so a caller-supplied revision with
    a NUL in it leaked an internal exception in place of `REVISION_UNKNOWN`
    (Copilot review of openDox-code#26, round 10, suppressed). The same guard
    round 9 gave a document key.
    """
    corpus = _resolve(adapter, repository)
    document = ca.DocumentId(corpus=corpus.ref.name, key="anything.md")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(corpus, document, revision="main\0extra")
    assert caught.value.refusal.kind == ca.REVISION_UNKNOWN


def test_a_git_that_becomes_unusable_after_resolve_is_a_named_refusal(
        adapter: lga.LocalGitCorpus, repository: Path, tmp_path: Path) -> None:
    """`resolve` probes git ONCE, and every later call read a returncode.

    `GitRunner.run` raises `GitCommandFailed` when the executable cannot be
    started, so a `git` removed, replaced or made unexecutable after resolution
    leaked that internal signal out of `list_documents`, `read` and `check` —
    the API's 500 in place of the interface's `CORPUS_UNREADABLE` (Copilot
    review of openDox-code#26, round 10, suppressed on five call sites). A
    second adapter over the SAME resolved corpus is that race, made
    deterministic.
    """
    corpus = _resolve(adapter, repository)
    gone = lga.LocalGitCorpus(executable=str(tmp_path / "git-that-was-removed"))
    document = ca.DocumentId(corpus=corpus.ref.name, key="anything.md")

    for call in (lambda: gone.list_documents(corpus),
                 lambda: gone.read(corpus, document),
                 lambda: gone.check(corpus),
                 lambda: gone.read(corpus, document, revision="main")):
        with pytest.raises(ca.CorpusRefused) as caught:
            call()
        assert caught.value.refusal.kind in (
            ca.CORPUS_UNREADABLE, ca.REVISION_UNKNOWN), caught.value.refusal


def test_an_unborn_corpus_whose_git_went_away_refuses_rather_than_answering(
        adapter: lga.LocalGitCorpus, tmp_path: Path) -> None:
    """The path that answers `()` without asking git anything.

    An unborn corpus's empty listing is the answer a HEALTHY empty repository
    gives, so it is the one place an unreadable corpus is hardest to tell from
    a legal one — and `_revalidate`'s own probe could leak the runner's failure
    instead of refusing (Copilot review of openDox-code#26, round 10).
    """
    location = tmp_path / "unborn"
    location.mkdir()
    _git(location, "init", "--bare", "--initial-branch=main", ".")
    corpus = adapter.resolve(ca.CorpusRef(name="unborn", location=str(location)))
    assert corpus.revision is None
    assert adapter.list_documents(corpus) == ()

    gone = lga.LocalGitCorpus(executable=str(tmp_path / "git-that-was-removed"))
    with pytest.raises(ca.CorpusRefused) as caught:
        gone.list_documents(corpus)
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(),
                    reason="this platform has no /proc/self/fd, so git cannot "
                           "be handed an open directory; the pathname "
                           "fallback and its inode check are what run there")
def test_the_initialization_is_bound_to_the_directory_it_verified(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check and the use are the same object, not the same NAME.

    `initialize_repository` opened the directory `O_NOFOLLOW`, compared inodes
    and then CLOSED the handle before handing git the pathname — so a final
    component replaced between those two steps sent `git init --bare` and the
    first commit into whatever was put there (Copilot review of
    openDox-code#26, round 10). git is given `/proc/self/fd/<n>` for the
    verified descriptor now, and the descriptor is inherited by the child, so
    the swap below lands nowhere.

    The race is made deterministic by performing the swap at the only moment it
    could happen: after the handle is verified and before the first git call.

    AND THE ACT NOW REFUSES, which round 13 added and this case had to take on:
    the descriptor decides where the history goes, but `create_repository`
    records a NAME in the map row, so an act that SUCCEEDED here left the row
    pointing at the decoy and the next `resolve(corpus_ref_for(row))` served it
    (Copilot review of openDox-code#26, round 13). Both halves are asserted:
    the history is in the directory this act verified, the decoy is untouched,
    and nothing is recorded.

    ROUND 14 MOVED WHICH HALF ANSWERS, and the assertion follows it rather than
    being loosened: the swapped-in name is a SYMLINK, and the identity check is
    now made through a no-follow walk (`_directory_by_name`), which refuses a
    linked component outright instead of reaching the inode comparison behind
    it. Same `try`, same moment, same act refused — a different sentence, and
    the stronger one.
    """
    from opendox.runtime import repository_act

    location = tmp_path / "project-raced"
    decoy = tmp_path / "attackers-tree"
    decoy.mkdir()
    real = repository_act._initialize_with

    def _swap_then_initialize(git, where, **kwargs):
        moved = tmp_path / "the-real-directory"
        where.rename(moved)                       # the verified directory
        where.symlink_to(decoy)                   # the name now points at the decoy
        _swap_then_initialize.moved = moved
        return real(git, where, **kwargs)

    monkeypatch.setattr(repository_act, "_initialize_with", _swap_then_initialize)
    with pytest.raises(repository_act.RepositoryActRefused) as caught:
        repository_act.initialize_repository(
            location, project_id="project-raced", actor=ACTOR)
    assert "could not be re-examined after the repository was initialized" in \
        str(caught.value), str(caught.value)

    moved = _swap_then_initialize.moved
    assert (moved / "HEAD").is_file(), (
        "the history was not written into the directory this act verified")
    assert not any(decoy.iterdir()), (
        f"git wrote into the swapped-in path: {sorted(decoy.iterdir())}")


# -- Copilot's twelfth round on #26 ------------------------------------------


not_root = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root ignores the permission bits these cases set, so they are "
           "skipped with the reason printed rather than passing vacuously")


def test_a_pinned_revision_resolves_without_asking_head(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """`CorpusRef.revision` is the PINNED form; HEAD is not its business.

    `resolve` asked `_head` first in every case, so a repository with a
    malformed or unreadable HEAD was refused before the revision the caller
    actually named was looked up — a corpus this adapter can serve, refused for
    a fact about a ref the request does not use (Copilot review of
    openDox-code#26, round 12, suppressed).
    """
    commit = _git(repository, "rev-parse", "HEAD")
    # A ref store HEAD cannot read: the branch file is junk, which `_head`
    # refuses as CORPUS_UNREADABLE (round 6's own distinction).
    (repository / "refs" / "heads" / "main").write_text("not a sha\n",
                                                        encoding="utf-8")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="pinned", location=str(repository)))
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE

    pinned = adapter.resolve(ca.CorpusRef(name="pinned",
                                          location=str(repository),
                                          revision=commit))
    assert pinned.revision == commit
    assert adapter.list_documents(pinned) == ()


@not_root
def test_a_location_that_cannot_be_read_is_a_refusal_and_not_an_oserror(
        adapter: lga.LocalGitCorpus, tmp_path: Path) -> None:
    """`exists()`, `is_dir()` and `resolve()` raise for an unsearchable parent.

    So a location this adapter could not READ left a `PermissionError` where
    the protocol promises a refusal, and the API turned it into a 500 (Copilot
    review of openDox-code#26, round 12, suppressed). A missing path and an
    unreadable one are still different answers.
    """
    parent = tmp_path / "sealed"
    parent.mkdir()
    location = parent / "project"
    location.mkdir()
    parent.chmod(0o000)
    try:
        with pytest.raises(ca.CorpusRefused) as caught:
            adapter.resolve(ca.CorpusRef(name="sealed", location=str(location)))
        assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE
    finally:
        parent.chmod(0o755)


@not_root
def test_the_write_path_is_available_only_where_a_write_would_land(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """A commit writes an OBJECT and moves a REF, not just "the git dir".

    `write_path_available` asked `os.access(git_dir, W_OK)` alone, so a
    repository whose root was writable and whose `objects/` was read-only
    advertised an available write path and then failed inside the commit —
    the discovery order this interface's rule forbids: "a read-only corpus is
    a fact about the corpus, and discovering it by attempting a write is how a
    caller ends up with a half-built edit and nowhere to put it" (Copilot
    review of openDox-code#26, round 12, suppressed).
    """
    assert adapter.resolve(
        ca.CorpusRef(name="writable", location=str(repository))
    ).write_path_available is True

    objects = repository / "objects"
    objects.chmod(0o500)
    try:
        corpus = adapter.resolve(ca.CorpusRef(name="read-only-objects",
                                              location=str(repository)))
        assert corpus.write_path_available is False, (
            "an unwritable object store was advertised as a usable write path")
    finally:
        objects.chmod(0o755)


def test_the_directory_the_emptiness_check_saw_is_the_one_initialized(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The check and the use have to be the same OBJECT, not the same name.

    The first cut verified emptiness through a no-follow handle, CLOSED it, and
    opened the path again for the run: a directory removed and replaced between
    those two opens was described by both `fstat` and `stat`, so the inode
    comparison compared the replacement with itself and passed (Copilot review
    of openDox-code#26, round 12). One descriptor is opened now, emptiness is
    asked of IT (`os.listdir` takes a file descriptor), and git is given that
    same descriptor.

    The swap is made deterministic by performing it the instant the act opens
    the leaf: the name then leads to an empty directory while the descriptor
    holds the one that is not.
    """
    from opendox.runtime import repository_act

    location = tmp_path / "project-swapped"
    location.mkdir()                      # empty: the preflight accepts it
    decoy = tmp_path / "an-empty-directory"
    decoy.mkdir()
    moved = tmp_path / "moved-aside"

    real_open = os.open
    swapped = {"done": False}

    def _swap_on_the_acts_open(path, flags, *args, **kwargs):
        handle = real_open(path, flags, *args, **kwargs)
        if not swapped["done"] and path == location.name and kwargs.get("dir_fd"):
            swapped["done"] = True
            # The directory the descriptor holds acquires content, and the
            # NAME is re-pointed at an empty one — which is the whole window:
            # a check by name would see the decoy and say "empty".
            (location / "somebody-elses-history").write_text("x",
                                                             encoding="utf-8")
            location.rename(moved)
            decoy.rename(location)
        return handle

    monkeypatch.setattr(os, "open", _swap_on_the_acts_open)
    with pytest.raises(repository_act.RepositoryActRefused) as caught:
        repository_act.initialize_repository(location, project_id="swapped",
                                             actor=ACTOR)
    assert swapped["done"], "the race this test drives did not happen"
    assert "not empty" in str(caught.value), caught.value
    # Nothing was initialized ANYWHERE: not in the directory the descriptor
    # held, and not in the one the name was re-pointed at.
    assert not (moved / "HEAD").exists()
    assert not (location / "HEAD").exists()


# -- RULED openxFactory#656 comment 5714365086 (Q-F2 / Q-F3) ------------------


def _repository_at(location: Path, name: str) -> Path:
    initialize_repository(location, project_id=name, actor=ACTOR)
    return location


def test_a_directory_inside_another_repository_is_refused_and_not_adopted(
        adapter, tmp_path: Path) -> None:
    """`rev-parse --git-dir` WALKS UP, and this reader followed it out.

    Pointed at an ordinary directory inside somebody else's checkout, `resolve`
    answered for THAT repository at ITS head: `list_documents` served keys
    relative to the prefix, `read` resolved them from the repository root and
    refused them as `DOCUMENT_UNKNOWN`, and `write_back` committed into the
    enclosing repository and moved its branch — a write into a repository the
    caller never named, at a path the caller never named (helper `floor37`,
    2026-09-17, measured end to end; RULED openxFactory#656 comment
    5714365086, Q-F3 (a)).

    It is reachable in this product: `OPENDOX_PROJECT_REPOSITORY_ROOT` defaults
    to the RELATIVE `var/projects`, so a `var/projects/<id>` that exists and is
    not a repository sits inside whatever checkout the process started in.

    Measured against the old shape before this was written: `resolve` returned
    a corpus whose revision was the ENCLOSING repository's HEAD.
    """
    enclosing = tmp_path / "somebody-elses"
    enclosing.mkdir()
    _git(enclosing, "init", "--initial-branch=main", ".")
    (enclosing / "a.md").write_text("a\n", encoding="utf-8")
    _git(enclosing, "add", "a.md")
    _git(enclosing, "commit", "-m", "first")
    before = _git(enclosing, "rev-parse", "HEAD")

    inside = enclosing / "sub"
    inside.mkdir()
    (inside / "alpha.md").write_text("# alpha\n", encoding="utf-8")

    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="inside", location=str(inside)))
    assert caught.value.refusal.kind == ca.CORPUS_UNCLASSIFIABLE
    assert str(enclosing.resolve()) in caught.value.refusal.detail, (
        "the refusal does not name the repository this location is inside, "
        "which is the one thing that tells an operator what happened")
    # AND NOTHING MOVED, which is the half of the defect that mattered.
    assert _git(enclosing, "rev-parse", "HEAD") == before


def test_a_repository_root_passed_explicitly_still_resolves(
        adapter, tmp_path: Path) -> None:
    """The other half of the ruling: pinning the root refuses nothing legal.

    The repository this act creates is BARE and its location IS its root; a
    repository openDox did not create has a work tree and `--show-toplevel` is
    its root. Both are served, and a repository nested inside another one — a
    legal thing to have on disk — is served when it is named itself.
    """
    outer = tmp_path / "outer"
    outer.mkdir()
    _git(outer, "init", "--initial-branch=main", ".")
    (outer / "a.md").write_text("a\n", encoding="utf-8")
    _git(outer, "add", "a.md")
    _git(outer, "commit", "-m", "first")
    # A repository of its own, INSIDE the outer one's working tree.
    nested = _repository_at(outer / "nested", "nested")

    for location in (outer, nested):
        corpus = adapter.resolve(ca.CorpusRef(name=location.name,
                                              location=str(location)))
        assert corpus.location == str(location.resolve())
        assert corpus.revision is not None
    # And the nested one serves ITS history, not the outer one's.
    outer_corpus = adapter.resolve(
        ca.CorpusRef(name="outer", location=str(outer)))
    nested_corpus = adapter.resolve(
        ca.CorpusRef(name="nested", location=str(nested)))
    assert outer_corpus.revision != nested_corpus.revision


def test_a_write_back_will_not_commit_into_an_enclosing_repository(
        adapter, tmp_path: Path) -> None:
    """The guard is asked again on the one operation that writes.

    A `ResolvedCorpus` comes from `resolve`, which now refuses this — but this
    is the call that can put a commit in somebody else's history, and the cost
    of being sure is one `rev-parse`.
    """
    enclosing = tmp_path / "enclosing"
    enclosing.mkdir()
    _git(enclosing, "init", "--initial-branch=main", ".")
    (enclosing / "a.md").write_text("a\n", encoding="utf-8")
    _git(enclosing, "add", "a.md")
    _git(enclosing, "commit", "-m", "first")
    head = _git(enclosing, "rev-parse", "HEAD")
    inside = enclosing / "sub"
    inside.mkdir()

    # Hand-built, exactly as a caller holding a stale row would have one.
    corpus = ca.ResolvedCorpus(
        ref=ca.CorpusRef(name="inside", location=str(inside)),
        location=str(inside), revision=head, scopes=(ca.SCOPE_ALL,),
        write_path=lga.WRITE_PATH, write_path_available=True)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus,
                           ca.DocumentId(corpus="inside", key="alpha.md"),
                           b"# alpha\n", actor=ACTOR, basis_revision=head)
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert _git(enclosing, "rev-parse", "HEAD") == head, (
        "the commit landed in the enclosing repository anyway")


def test_a_location_that_is_a_file_is_unreadable_and_not_unclassifiable(
        adapter, tmp_path: Path) -> None:
    """A one-word vocabulary defect, and the interface's own comments settle it.

    `CORPUS_UNREADABLE` is "it is there and cannot be read";
    `CORPUS_UNCLASSIFIABLE` is "the CORPUS's shape, not a document's". A
    regular file at the location is the first, the neutral conformance corpus
    holds every reader to it, and openxFactory's own adapter answers it — this
    one answered the other and failed that check (RULED 5714365086, Q-F2 (a)).
    A DIRECTORY that is not a repository keeps `CORPUS_UNCLASSIFIABLE`.
    """
    a_file = tmp_path / "a-file"
    a_file.write_text("not a repository\n", encoding="utf-8")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="f", location=str(a_file)))
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE

    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(ca.CorpusRefused) as second:
        adapter.resolve(ca.CorpusRef(name="d", location=str(plain)))
    assert second.value.refusal.kind == ca.CORPUS_UNCLASSIFIABLE


def test_a_corpus_that_declares_no_write_path_is_read_only_and_stays_still(
        repository: Path) -> None:
    """`write_back`'s `CORPUS_READ_ONLY` branch was correct and unreachable.

    Every resolution advertised `local-git-commit`, so a corpus that declares
    NO governed write path could not be expressed — and a write at one
    RETURNED A RECEIPT and moved a ref. Degrading a refusal to a result is the
    one thing a reader over a corpus it does not own must never do (RULED
    5714365086, Q-F2 (a); measured by helper `floor37` as conformance checks
    `read-only-declared-at-resolution`, `write-back-refuses-read-only` and
    `write-back-leaves-the-tree`).
    """
    reader = lga.LocalGitCorpus(write_path=None)
    corpus = reader.resolve(ca.CorpusRef(name="project-1",
                                         location=str(repository)))
    assert corpus.write_path is None
    assert corpus.write_path_available is False
    head = _git(repository, "rev-parse", "HEAD")

    with pytest.raises(ca.CorpusRefused) as caught:
        reader.write_back(corpus, ca.DocumentId(corpus="project-1",
                                                key="notes.md"),
                          b"# notes\n", actor=ACTOR, basis_revision=head)
    assert caught.value.refusal.kind == ca.CORPUS_READ_ONLY
    assert _git(repository, "rev-parse", "HEAD") == head, (
        "the tree moved under a write that was refused")
    # Reading it is unaffected: read-only is a write fact.
    assert reader.list_documents(corpus) == ()


def test_a_corpus_that_declares_its_kind_in_a_header_is_classified_by_it(
        adapter, repository: Path) -> None:
    """Three documents, three answers — and by suffix there was only one.

    A corpus that declares its shape in a header (`Type:`, which is how the
    neutral conformance corpus is written) was classified by FILE SUFFIX, so
    one complete document, one missing a required field and one with no
    recognizable shape at all came back as three `text` documents with nothing
    missing and nothing unrecognizable (RULED 5714365086, Q-F2 (a)).
    """
    head = _git(repository, "rev-parse", "HEAD")
    written = {
        "complete.md": b"Type: note\nTitle: A note\n\nbody\n",
        "field-absent.md": b"Type: note\n\nbody\n",
        "unrecognizable.md": b"just a body, no header\n",
    }
    revision = head
    for key, content in written.items():
        corpus = adapter.resolve(ca.CorpusRef(name="project-1",
                                              location=str(repository)))
        receipt = adapter.write_back(corpus,
                                     ca.DocumentId(corpus="project-1", key=key),
                                     content, actor=ACTOR,
                                     basis_revision=revision)
        revision = receipt.correlation_id

    reader = lga.LocalGitCorpus(kind_field="Type",
                                required_fields=("Type", "Title"))
    corpus = reader.resolve(ca.CorpusRef(name="project-1",
                                         location=str(repository)))
    answers = {document.key: reader.classify(corpus, document)
               for document in reader.list_documents(corpus)}

    complete = answers["complete.md"]
    assert (complete.kind, complete.missing_fields) == ("note", ())
    assert complete.unclassifiable is None
    absent = answers["field-absent.md"]
    assert (absent.kind, absent.missing_fields) == ("note", ("Title",))
    assert absent.unclassifiable is None
    unrecognizable = answers["unrecognizable.md"]
    assert unrecognizable.kind is None
    assert "Type" in (unrecognizable.unclassifiable or "")

    # AND THE DEFAULT READER STILL ANSWERS BY SUFFIX, for the same three.
    by_suffix = {document.key: adapter.classify(corpus, document)
                 for document in adapter.list_documents(corpus)}
    assert {answer.kind for answer in by_suffix.values()} == {"text"}
    assert all(answer.missing_fields == () for answer in by_suffix.values())


# -- Copilot's twelfth round on #26, continued -------------------------------


def test_a_credential_is_redacted_whole_even_with_a_space_in_it() -> None:
    """A redaction that stops at a space is one a secret can be walked past.

    `[^&#\\s]*` ended a parameter's value at the first whitespace, so
    `?token= ghp_secret` had its EMPTY value replaced and the secret printed
    beside the marker, and `?token=secret with more` kept everything after the
    first word. And the userinfo form's `[^\\s/@]*` did not match at all where
    the password held a space, so a legacy row's credential was returned
    unchanged — while `repository_act._URL_USERINFO` (`[^/@]*@`) REFUSES that
    very shape for a new attachment: the two halves of one rule disagreed about
    one character (Copilot review of openDox-code#26, round 12).

    Each of these is unchanged or partly visible against the old shape.
    """
    assert lga.redact_credentials(
        "https://host/r.git?token= ghp_secret") == (
        "https://host/r.git?token=<redacted>")
    assert lga.redact_credentials(
        "https://host/r.git?token=secret with space") == (
        "https://host/r.git?token=<redacted>")
    assert lga.redact_credentials(
        "https://user:secret value@host/repo.git") == "<redacted-url>"
    # AND A MULTI-LINE MESSAGE KEEPS ITS OTHER LINES: a credential on one line
    # must not take the diagnostic on the next with it.
    redacted = lga.redact_credentials(
        "fatal: could not read from https://host/r.git?token=abc\n"
        "hint: check the remote and try again")
    assert redacted.endswith("hint: check the remote and try again")
    assert "abc" not in redacted
    # AND ORDINARY TEXT IS STILL ORDINARY TEXT.
    assert lga.redact_credentials(
        "a sentence about ?a+b=1 and nothing else") == (
        "a sentence about ?a+b=1 and nothing else")


@not_root
def test_the_write_path_is_unavailable_where_the_served_ref_cannot_be_written(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """`update-ref` writes `refs/heads/<branch>`, not `refs/`.

    A `refs/` that is writable while `refs/heads/` is not advertised a usable
    write path, and the refusal arrived after the blob, the tree and the commit
    had been created — unreachable objects, and the forbidden discovery order
    one level down (Copilot review of openDox-code#26, round 12, suppressed).
    """
    heads = repository / "refs" / "heads"
    assert heads.is_dir()
    heads.chmod(0o500)
    try:
        corpus = adapter.resolve(ca.CorpusRef(name="ref-home",
                                              location=str(repository)))
        assert corpus.write_path_available is False, (
            "an unwritable `refs/heads` was advertised as a usable write path")
    finally:
        heads.chmod(0o755)


@not_root
def test_a_directory_that_cannot_be_searched_is_not_a_write_path(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """Creating a file needs WRITE and SEARCH; the check asked for one of them.

    `os.access(d, os.W_OK)` is true for a directory git can create nothing in,
    so the predicate did not say what its own comment said (Copilot review of
    openDox-code#26, round 12). It asks for both bits now.

    NOT A REGRESSION TEST, AND IT SAYS SO: this passes against the old shape
    too, because the missing SEARCH bit is not reachable through `resolve` —
    git cannot read a repository with such a directory in it, so the corpus is
    refused `corpus-unreadable` BEFORE the write path is ever computed. The
    table below is the measurement that establishes that, on git 2.43.0, and
    it is pinned here so a later change that makes the shape reachable finds a
    predicate already asking the right question.
    """
    heads = repository / "refs" / "heads"
    measured = {}
    for mode in (0o200, 0o300, 0o500):
        heads.chmod(mode)
        try:
            corpus = adapter.resolve(ca.CorpusRef(name="perm",
                                                  location=str(repository)))
            measured[mode] = corpus.write_path_available
        except ca.CorpusRefused as refused:
            measured[mode] = refused.refusal.kind
        finally:
            heads.chmod(0o755)
    assert measured == {
        0o200: ca.CORPUS_UNREADABLE,   # writable, NOT searchable: unreadable
        0o300: True,                   # writable and searchable
        0o500: False,                  # searchable, NOT writable
    }, measured


def test_a_head_that_cannot_be_written_says_so_at_resolution(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """A detached HEAD is a corpus that can be READ and not written.

    `write_path_available` measured filesystem permissions alone, so `resolve`
    advertised a usable write path and `write_back` then hashed the blob, wrote
    the tree and created the commit before `_served_ref` refused — leaving
    unreachable objects behind for a refusal the corpus could have made at
    resolution (Copilot review of openDox-code#26, round 12, suppressed).
    """
    head = _git(repository, "rev-parse", "HEAD")
    (repository / "HEAD").write_text(f"{head}\n", encoding="utf-8")
    corpus = adapter.resolve(ca.CorpusRef(name="detached",
                                          location=str(repository)))
    assert corpus.revision == head, "a detached HEAD is still readable"
    assert corpus.write_path_available is False, (
        "a detached HEAD has no branch for a commit to advance, and resolution "
        "is where a corpus says it cannot be written")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus,
                           ca.DocumentId(corpus="detached", key="notes.md"),
                           b"# notes\n", actor=ACTOR, basis_revision=head)
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE


def test_only_a_branch_can_be_unborn(adapter: lga.LocalGitCorpus,
                                     tmp_path: Path) -> None:
    """An absent ref under `refs/tags` is a BROKEN HEAD, not an empty corpus.

    `for-each-ref` is silent for an absent ref wherever it lives, so a HEAD
    pointing at `refs/tags/whatever` resolved with `revision=None` and
    `list_documents` answered `()` — the empty corpus a healthy repository
    gives (Copilot review of openDox-code#26, round 12, suppressed). "The first
    commit has not been made yet" is a statement about a branch.
    """
    location = tmp_path / "head-at-a-tag"
    location.mkdir()
    _git(location, "init", "--bare", "--initial-branch=main", ".")
    (location / "HEAD").write_text("ref: refs/tags/nothing\n", encoding="utf-8")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="tagged", location=str(location)))
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE

    # The real unborn case still resolves as a legal empty corpus.
    unborn = tmp_path / "unborn"
    unborn.mkdir()
    _git(unborn, "init", "--bare", "--initial-branch=main", ".")
    corpus = adapter.resolve(ca.CorpusRef(name="unborn", location=str(unborn)))
    assert corpus.revision is None
    assert adapter.list_documents(corpus) == ()


def test_a_location_that_cannot_be_probed_refuses_rather_than_raising(
        adapter: lga.LocalGitCorpus, repository: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`_revalidate`'s `Path.exists()` raises for an unsearchable parent.

    It sat outside every handler, so a repository that became INACCESSIBLE
    after it resolved leaked an OS exception out of `list_documents`, `read`
    and `check`, where this adapter promises `CORPUS_UNREADABLE` (Copilot
    review of openDox-code#26, round 12, suppressed twice). Absent and
    unreadable stay different answers.
    """
    corpus = adapter.resolve(ca.CorpusRef(name="project-1",
                                          location=str(repository)))
    real_exists = Path.exists

    def _unsearchable(self, *args, **kwargs):
        if str(self) == corpus.location:
            raise PermissionError(13, "Permission denied")
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", _unsearchable)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(corpus, ca.DocumentId(corpus="project-1", key="no.md"))
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE


def test_a_temporary_index_that_cannot_be_removed_refuses_by_name(
        adapter: lga.LocalGitCorpus, repository: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The cleanup is inside the write path's own promise.

    `index.unlink(missing_ok=True)` can raise `OSError`, and the handler around
    it translated only `GitCommandFailed` — so a git directory whose
    permissions changed under the write escaped `write_back` as an OS exception
    where the adapter owes `WRITE_PATH_UNREACHABLE` (Copilot review of
    openDox-code#26, round 12, suppressed). It is recorded and raised AFTER the
    `finally`, so an exception already on its way still wins.
    """
    corpus = adapter.resolve(ca.CorpusRef(name="project-1",
                                          location=str(repository)))
    real_unlink = Path.unlink

    def _refuses(self, *args, **kwargs):
        if self.name.startswith("opendox-index-"):
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _refuses)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus,
                           ca.DocumentId(corpus="project-1", key="notes.md"),
                           b"# notes\n", actor=ACTOR,
                           basis_revision=str(corpus.revision))
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert "index" in caught.value.refusal.detail


def test_a_parent_replaced_by_a_symlink_cannot_move_the_repository(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The leaf was created relative to a parent opened BY PATHNAME.

    Which follows every symlink in it. A concurrent replacement of
    `location.parent` — or of any ancestor — with a link therefore made the
    held descriptor, `git init` and the later `stat(location)` all name a
    directory outside the canonical repository root, and the inode comparison
    compared that place with itself and passed (Copilot review of
    openDox-code#26, round 12, twice). The parent chain is opened component by
    component with `O_NOFOLLOW` now, so the substitution is refused instead of
    followed.

    The race is made deterministic by performing the swap in
    `refuse_unusable_location`, which the act calls immediately before the
    open. Against the old shape this test fails: the act SUCCEEDS and the
    repository is initialized inside the decoy.
    """
    from opendox.runtime import repository_act

    root = tmp_path / "canonical"
    root.mkdir()
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    location = root / "project-1"
    real_preflight = repository_act.refuse_unusable_location
    swapped = {"done": False}

    def _swap_the_parent(path: Path) -> None:
        real_preflight(path)
        if not swapped["done"]:
            swapped["done"] = True
            root.rename(tmp_path / "canonical-moved")
            root.symlink_to(decoy, target_is_directory=True)

    monkeypatch.setattr(repository_act, "refuse_unusable_location",
                        _swap_the_parent)
    with pytest.raises(repository_act.RepositoryActRefused):
        repository_act.initialize_repository(location, project_id="project-1",
                                             actor=ACTOR)
    assert swapped["done"], "the race this test drives did not happen"
    assert list(decoy.iterdir()) == [], (
        "the repository was initialized through the link, in a directory "
        "nobody named")


def test_a_root_that_cannot_be_resolved_is_a_named_refusal(
        tmp_path: Path) -> None:
    """`expanduser()`/`resolve()` raise, and this is the act's FIRST line.

    A misconfigured `OPENDOX_PROJECT_REPOSITORY_ROOT` — a symlink loop, an
    ancestor that is not searchable — reached the API as a 500 rather than the
    named refusal this act promises for every reason it will not create a
    repository (Copilot review of openDox-code#26, round 12, suppressed).
    """
    from opendox.runtime import repository_act

    loop = tmp_path / "loop"
    loop.symlink_to(tmp_path / "loop-2")
    (tmp_path / "loop-2").symlink_to(loop)
    with pytest.raises(repository_act.RepositoryActRefused) as caught:
        repository_act.repository_location(loop, "project-1")
    assert "could not be resolved" in str(caught.value)


@not_root
def test_a_location_that_cannot_be_inspected_is_a_named_refusal(
        tmp_path: Path) -> None:
    """The preflight's own probes sat outside every handler.

    `is_symlink()`, `lexists()` and `exists()` all raise `PermissionError` for
    a path whose parent is not searchable, and both callers translate only
    `RepositoryActRefused` — so a location this act could not inspect escaped
    as a raw filesystem error (Copilot review of openDox-code#26, round 12,
    suppressed twice).
    """
    from opendox.runtime import repository_act

    parent = tmp_path / "unsearchable"
    parent.mkdir()
    location = parent / "project-1"
    parent.chmod(0o000)
    try:
        with pytest.raises(repository_act.RepositoryActRefused) as caught:
            repository_act.refuse_unusable_location(location)
        assert "could not be inspected" in str(caught.value)
    finally:
        parent.chmod(0o755)


def test_the_served_ref_is_the_one_head_names_at_the_moment_of_the_write(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """The behaviour this act DECLARES, pinned rather than argued.

    Copilot's twelfth round asked for the served ref to be bound at RESOLUTION:
    a corpus resolved on `main` at commit A, with HEAD then switched to another
    branch also at A, has its write advance that other branch. That is what
    happens, and it is what `_served_ref` says in terms — "the ref `write_back`
    moves: the one HEAD points at" — because this corpus resolves a REVISION,
    not a branch: `list_documents` and `read` are revision-addressed, so
    nothing the caller read depends on which branch served it.

    IT IS NOT FIXED HERE, AND THE REASON IS THE INTERFACE. Binding the ref at
    resolution means carrying it on `ResolvedCorpus`, which is
    `opendox.corpus_adapter`'s — the NEUTRAL contract openxFactory pins by
    commit and digest, and which this act may not widen. The alternative, an
    adapter-side memo keyed on a value object, would make the guarantee true
    only when one instance both resolves and writes: a claim this act would be
    making and not keeping. Registered as residue for the act that governs
    branch selection.

    WHAT IS GUARANTEED IS UNCHANGED, and its own case is
    `test_a_stale_corpus_loses_its_dispatch_rather_than_overwriting`: the
    commit lands only where the corpus resolved, so no concurrent writer's work
    is overwritten and nothing is lost. That is asserted here too, on the
    branch that did advance.
    """
    corpus = adapter.resolve(ca.CorpusRef(name="project-1",
                                          location=str(repository)))
    head = corpus.revision
    assert head is not None
    _git(repository, "update-ref", "refs/heads/other", head)
    _git(repository, "symbolic-ref", "HEAD", "refs/heads/other")

    receipt = adapter.write_back(
        corpus, ca.DocumentId(corpus="project-1", key="notes.md"),
        b"# notes\n", actor=ACTOR, basis_revision=head)

    assert _git(repository, "rev-parse", "refs/heads/other") == (
        receipt.correlation_id), "the ref HEAD names did not advance"
    assert _git(repository, "rev-parse", "refs/heads/main") == head, (
        "a branch the write did not name was moved")
    # AND THE DOCUMENT IS SERVED BY THE CORPUS AS IT NOW STANDS.
    served = adapter.resolve(ca.CorpusRef(name="project-1",
                                          location=str(repository)))
    assert ca.DocumentId(corpus="project-1", key="notes.md") in (
        adapter.list_documents(served))


# -- Copilot's thirteenth round on #26 ---------------------------------------


def test_an_ambient_git_dir_cannot_redirect_this_runtimes_git(
        adapter: lga.LocalGitCorpus, repository: Path,
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`GIT_DIR` OUTRANKS `-C`, and every invocation inherited the environment.

    A runtime started with one of these set — a unit file that inherited it, a
    process started from inside a git hook, which is exactly where they are set
    — resolved, initialized or pushed a DIFFERENT repository than the one the
    map row names, silently (Copilot review of openDox-code#26, round 13). The
    repository-selection variables are stripped from every `git` this package
    runs, and the call's own (`GIT_INDEX_FILE`, the commit identity) are
    layered on top of the sanitized copy.
    """
    elsewhere = tmp_path / "elsewhere"
    initialize_repository(elsewhere, project_id="elsewhere", actor=ACTOR)
    mine = adapter.resolve(ca.CorpusRef(name="project-1",
                                        location=str(repository))).revision
    theirs = adapter.resolve(ca.CorpusRef(name="elsewhere",
                                          location=str(elsewhere))).revision
    assert mine != theirs, "the two repositories share a commit; pick another"

    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
                 "GIT_OBJECT_DIRECTORY"):
        monkeypatch.setenv(name, str(elsewhere))
    corpus = adapter.resolve(ca.CorpusRef(name="project-1",
                                          location=str(repository)))
    assert corpus.revision == mine, (
        "an ambient GIT_* variable redirected the adapter to another "
        "repository than the one it was given")
    assert corpus.location == str(repository.resolve())
    # AND A WRITE STILL LANDS IN THE MAPPED ONE.
    receipt = adapter.write_back(
        corpus, ca.DocumentId(corpus="project-1", key="notes.md"),
        b"# notes\n", actor=ACTOR, basis_revision=str(corpus.revision))
    assert _git(repository, "rev-parse", "HEAD") == receipt.correlation_id
    assert _git(elsewhere, "rev-parse", "HEAD") == theirs


def test_a_pass_parameter_is_a_credential_in_both_halves_of_the_rule() -> None:
    """`password` does not cover `pass`, and the match is a SEARCH.

    So `?password=` and `?my_password=` were caught by the needle `password`
    while `?pass=secret` — a name a great many services use — was accepted by
    the refusal and returned unchanged by the redaction (Copilot review of
    openDox-code#26, round 13). `pass` is the shorter needle and matches all
    three.
    """
    from opendox.runtime import repository_act

    assert lga.names_a_secret_parameter("https://host/r.git?pass=secret")
    assert lga.redact_credentials("https://host/r.git?pass=secret") == (
        "https://host/r.git?pass=<redacted>")
    with pytest.raises(repository_act.RepositoryActRefused):
        repository_act.refuse_credential_bearing_remote(
            "https://host/r.git?pass=secret")
    # The longer spellings still match, through the same needle.
    for name in ("password", "my_password", "passwd"):
        assert lga.names_a_secret_parameter(f"https://host/r.git?{name}=x"), name


def test_a_control_character_is_refused_even_when_it_is_not_whitespace(
) -> None:
    """`isspace()` is not "is a control character".

    ESC, DEL and the rest of the C0/C1 sets are not whitespace, so they passed
    and were stored in `remote_url` and written into `.git/config` — after
    which a terminal reading the map's response interprets them, and an ESC
    sequence can rewrite what an operator sees (Copilot review of
    openDox-code#26, round 13).
    """
    from opendox.runtime import repository_act

    for control in ("\x1b[2J", "\x7f", "\x01", "\u200e", "\u202e"):
        with pytest.raises(repository_act.RepositoryActRefused) as caught:
            repository_act.refuse_credential_bearing_remote(
                f"https://host/x{control}.git")
        assert "control character" in str(caught.value), repr(control)
        # AND THE VALUE IS NOT ECHOED, which is the other half of this refusal.
        assert control not in str(caught.value)
    # A PLAIN SPACE STAYS LEGAL: a local path may contain one.
    repository_act.refuse_credential_bearing_remote("/srv/my repos/x.git")


def test_the_helper_transport_predicate_is_what_git_actually_does() -> None:
    """Measured on git 2.43.0, because the grammar and the behaviour differ.

    The review reported `evil_helper::anything` as a bypass (Copilot review of
    openDox-code#26, round 13). It is not: git parses that as SSH to a host
    named `evil_helper`, because `_` is not a scheme character. What IS a
    bypass is a name beginning with a DIGIT — and the empty name — both of
    which git resolves as helpers and this predicate required to start with a
    letter.

        evil::anything   -> git: 'remote-evil' is not a git command
        9evil::anything  -> git: 'remote-9evil' is not a git command   <- MISSED
        ::anything       -> git: 'remote-' is not a git command        <- MISSED
        evil_helper::x, +evil::x, .evil::x, ev~il::x  -> ssh, not a helper
    """
    from opendox.runtime import repository_act

    for refused in ("evil::anything", "9evil::anything", "::anything",
                    "ev-il::x", "ev.il::x", "ev+il::x", "EVIL::x"):
        with pytest.raises(repository_act.RepositoryActRefused) as caught:
            repository_act.refuse_command_executing_remote(refused)
        assert "runs a command" in str(caught.value), refused
    # NOT the helper form, on this git — and not refused here either, because a
    # refusal that does not match git's behaviour refuses legal destinations.
    for allowed in ("evil_helper::anything", "+evil::x", ".evil::x",
                    "ev~il::x", "https://example.invalid/x.git",
                    "git@example.invalid:x.git", "/srv/projects/x.git",
                    "/srv/a::b.git", "C:\\repo"):
        repository_act.refuse_command_executing_remote(allowed)


def test_an_explicit_revision_on_a_vanished_corpus_names_the_corpus(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """A deleted repository fails `rev-parse` too.

    `_resolve_revision` translates that into `REVISION_UNKNOWN`, so an
    explicit-revision read reported "this repository cannot serve that
    revision" for a repository that could no longer serve any (Copilot review
    of openDox-code#26, round 13). The corpus is asked first, as it is
    everywhere else in this module.
    """
    import shutil

    corpus = adapter.resolve(ca.CorpusRef(name="project-1",
                                          location=str(repository)))
    head = str(corpus.revision)
    shutil.rmtree(repository)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.read(corpus, ca.DocumentId(corpus="project-1", key="a.md"),
                     revision=head)
    assert caught.value.refusal.kind == ca.CORPUS_ABSENT, (
        "a vanished repository was reported as an unserveable revision")


def test_a_path_repointed_during_initialization_records_no_map_row(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The descriptor decides where the history goes; the ROW records a NAME.

    `create_repository` commits `location` in the map row, so a path re-pointed
    while the repository was being initialized left the row naming a directory
    the history is not in — and the next
    `LocalGitCorpus.resolve(corpus_ref_for(row))` serves the decoy (Copilot
    review of openDox-code#26, round 13). The act asks once more at the last
    moment it can still refuse.
    """
    from opendox.runtime import repository_act

    location = tmp_path / "project-1"
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    real_initialize = repository_act._initialize_with
    swapped = {"done": False}

    def _repoint_after_the_history(git, where, **kw):
        commit = real_initialize(git, where, **kw)
        if not swapped["done"]:
            swapped["done"] = True
            location.rename(tmp_path / "moved-aside")
            decoy.rename(location)
        return commit

    monkeypatch.setattr(repository_act, "_initialize_with",
                        _repoint_after_the_history)
    with pytest.raises(repository_act.RepositoryActRefused) as caught:
        repository_act.initialize_repository(location, project_id="project-1",
                                             actor=ACTOR)
    assert swapped["done"], "the race this test drives did not happen"
    assert "no longer names the directory" in str(caught.value)


def test_a_write_back_refuses_with_the_kind_write_back_declares(
        adapter, repository: Path) -> None:
    """The root re-check is right and its REFUSAL KIND was somebody else's.

    `_repository_root` is `resolve`'s helper and refuses `CORPUS_UNREADABLE`;
    `write_back` declares exactly two kinds, and `CORPUS_UNREADABLE` is not one
    of them (`corpus_adapter.py`: "raises `CORPUS_READ_ONLY` and
    `WRITE_PATH_UNREACHABLE` and NO other kind"). A corpus that became
    unreadable between `resolve` and the write therefore reached a caller
    branching on `err.refusal.kind` as a kind this operation never promised
    (Copilot review of openDox-code#26, round 13, suppressed). The failure is
    still refused — as the kind this operation owes.

    Drives it the only way a caller can: the repository goes away after it was
    resolved, which is precisely the window the re-check exists for.
    """
    import shutil

    corpus = _resolve(adapter, repository)
    assert corpus.write_path_available
    shutil.rmtree(repository)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus, ca.DocumentId("project-1", "a.md"),
                           b"# a\n", actor=ACTOR,
                           basis_revision=corpus.revision or "")
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE, (
        "the write refused with a kind `write_back` does not declare")
    # And it names the write path, which is what `WRITE_PATH_UNREACHABLE`'s
    # subject means everywhere else in this adapter.
    assert caught.value.refusal.subject == corpus.write_path


def test_the_commit_trailer_names_the_write_path_this_corpus_declares(
        tmp_path: Path) -> None:
    """RULED 5714365086 Q-F2 made `write_path` a per-corpus datum; the commit
    kept spelling the module default.

    `WriteReceipt.dispatched_to` already carried the constructed value, so a
    corpus built with another write path produced a receipt and a commit that
    disagreed about where the write went — and the commit is the durable
    record (Copilot review of openDox-code#26, round 13, suppressed).
    """
    repository = _repository_at(tmp_path / "project-1", "project-1")
    adapter = lga.LocalGitCorpus(write_path="governed-commit")
    receipt, _ = _write(adapter, repository, "a.md", b"# a\n")
    message = _git(repository, "log", "-1", "--format=%B",
                   receipt.correlation_id)

    assert receipt.dispatched_to == "governed-commit"
    assert "Write-Path: governed-commit" in message, message
    assert lga.WRITE_PATH not in message, (
        "the commit trailer spelled the module default rather than the write "
        "path this corpus was constructed with")
    # The default is unchanged for a default corpus: this is a new parameter,
    # not a new behaviour.
    plain = _repository_at(tmp_path / "project-2", "project-2")
    plain_receipt, _ = _write(lga.LocalGitCorpus(), plain, "a.md", b"# a\n")
    assert f"Write-Path: {lga.WRITE_PATH}" in _git(
        plain, "log", "-1", "--format=%B", plain_receipt.correlation_id)


def test_a_linked_worktree_can_reach_its_write_path(
        adapter, tmp_path: Path) -> None:
    """`--absolute-git-dir` is NOT where a worktree's objects and refs are.

    Measured on git 2.43.0, `git worktree add ../wt -b side`: the worktree's
    git dir is `<main>/.git/worktrees/wt`, which holds the INDEX and neither
    `objects/` nor `refs/`; those are the COMMON directory's, which
    `--path-format=absolute --git-common-dir` names. `os.access` on a path
    that does not exist is `False`, so every linked worktree resolved
    `write_path_available=False` however writable it was, and this adapter's
    own rule — "a read-only corpus is a fact about the corpus" — reported a
    fact that was not true (Copilot review of openDox-code#26, round 13,
    suppressed).

    Run against the shape it forbids, the probe answers `False` here and the
    write below never happens.
    """
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "--initial-branch=main", ".")
    (main / "a.md").write_text("a\n", encoding="utf-8")
    _git(main, "add", "a.md")
    _git(main, "commit", "-m", "first")
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-b", "side", str(worktree))
    # The premise, measured rather than assumed.
    git_dir = Path(_git(worktree, "rev-parse", "--absolute-git-dir"))
    common = Path(_git(worktree, "rev-parse", "--path-format=absolute",
                       "--git-common-dir"))
    assert git_dir != common
    assert not (git_dir / "objects").exists()
    assert (common / "objects").is_dir()

    corpus = adapter.resolve(ca.CorpusRef(name="wt", location=str(worktree)))
    assert corpus.location == str(worktree.resolve())
    assert corpus.write_path_available, (
        "a writable linked worktree was resolved read-only")

    # And the write it advertised actually lands, on the worktree's own branch.
    receipt = adapter.write_back(corpus, ca.DocumentId("wt", "b.md"),
                                 b"# b\n", actor=ACTOR,
                                 basis_revision=corpus.revision or "")
    assert _git(worktree, "rev-parse", "refs/heads/side") == \
        receipt.correlation_id
    assert _git(main, "rev-parse", "refs/heads/main") != receipt.correlation_id


# -- Copilot's fourteenth round on #26 ---------------------------------------


def test_the_bounded_line_scan_is_splitlines_exactly() -> None:
    """`_leading_lines` replaces `splitlines()[:n]`, so it must BE it.

    The replacement exists because `splitlines` materializes every line before
    the slice takes sixty-four; a header scan that allocates the whole document
    first is not the bounded scan its comment promises (Copilot review of
    openDox-code#26, round 14, suppressed). Equivalence is the whole claim, so
    it is measured over every shape that distinguishes the two: a trailing
    terminator, an empty document, consecutive terminators, `\r\n` against `\r`
    then `\n`, and each of the exotic boundaries `str.splitlines` splits on and
    a `\n`-only reader would miss.
    """
    boundaries = ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e",
                  "\x85", " ", " "]
    cases = ["", "a", "a\n", "a\n\nb", "\n", "\r\n", "\n\r", "a\rb\nc"]
    for boundary in boundaries:
        cases += [boundary, f"a{boundary}", f"{boundary}a",
                  f"a{boundary}b{boundary}c"]
    random.seed(20260917)
    alphabet = ["a", "b", " ", *boundaries]
    cases += ["".join(random.choice(alphabet)
                      for _ in range(random.randint(0, 12)))
              for _ in range(2000)]
    for text in cases:
        for limit in (0, 1, 2, 3, lga.MAX_HEADER_LINES):
            assert list(lga._leading_lines(text, limit)) == \
                text.splitlines()[:limit], (text, limit)


def test_a_location_whose_home_cannot_be_determined_is_refused(adapter) -> None:
    """`expanduser()` raises, and it sat above the translation.

    MEASURED on python 3.12.3: `Path("~nosuchuser12345/x").expanduser()` raises
    `RuntimeError: Could not determine home directory.` — and `ref.location` is
    a caller's string, so that one construction was the last way a location
    could reach the API as a 500 rather than this interface's refusal (Copilot
    review of openDox-code#26, round 14, suppressed).
    """
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.resolve(ca.CorpusRef(name="x",
                                     location="~nosuchuser12345/corpus"))
    assert caught.value.refusal.kind == ca.CORPUS_UNREADABLE


def test_a_legacy_remote_whose_credential_spans_a_line_is_not_printed() -> None:
    """The half of the credential rule that a PATTERN cannot close.

    `_CREDENTIAL_SHAPED`'s userinfo class excludes a newline so that the
    redactor applied to git's stderr cannot join a `scheme://` on one line to
    an unrelated `user@host` on another — and the price was that a LEGACY row
    holding `https://user:secret\n@host/repo` came back unredacted through the
    map endpoints, the CLI and push refusals (Copilot review of
    openDox-code#26, round 14). Widening the class would trade a rare leak for
    a routine loss of evidence; the distinction is the CALLER's, and
    `redact_remote_url` is the caller that holds one URL rather than a page of
    diagnostics.
    """
    legacy = "https://user:secret\n@host/repo.git"
    assert lga.redact_remote_url(legacy) == "<redacted-url>"
    assert "secret" not in lga.redact_remote_url(legacy)
    # A remote with no control character is unchanged in kind: the same
    # redaction it always had, host and all.
    assert lga.redact_remote_url("https://host/repo.git") == \
        "https://host/repo.git"
    assert lga.redact_remote_url("https://user:pw@host/repo.git") == \
        "<redacted-url>"

    # AND THE DIAGNOSTIC REDACTOR IS STILL NARROW — this half is a PINNING
    # assertion and NOT a regression test: it passes against the shape before
    # this round too, and it is here so that a later widening of the pattern
    # cannot pass unnoticed.
    diagnostic = ("fatal: unable to access 'https://docs.example.com'\n"
                  "error: key for git@host rejected\n")
    assert "https://docs.example.com" in lga.redact_credentials(diagnostic)


def test_the_control_character_rule_is_one_predicate_in_both_halves() -> None:
    """The refusing half and the printing half ask the same question."""
    from opendox.runtime import repository_act

    for value in ("https://host/r\n.git", "https://host/r\t.git",
                  "https://host/r‮.git"):
        assert lga.carries_a_control_character(value), value
        with pytest.raises(repository_act.RepositoryActRefused):
            repository_act.refuse_credential_bearing_remote(value)
        assert lga.redact_remote_url(value) == "<redacted-url>"
    # A PLAIN SPACE IS NOT ONE. A local path may contain one, and both halves
    # have to agree about that too.
    assert not lga.carries_a_control_character("/srv/my projects/repo.git")


def test_a_refused_parent_chain_creates_nothing_in_the_linked_tree(
        tmp_path: Path) -> None:
    """A refused act that had already written directories is a mutation.

    `location.parent.mkdir(parents=True, exist_ok=True)` resolves the chain BY
    PATHNAME, which follows every link in it. For `<root>/link/new/<id>` where
    `link` points outside the configured root, it created `<outside>/new` and
    only THEN did the no-follow walk refuse (Copilot review of openDox-code#26,
    round 14, suppressed). The parents are created component by component now,
    inside the directory the walk has already opened `O_NOFOLLOW`.
    """
    from opendox.runtime import repository_act

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(repository_act.RepositoryActRefused):
        repository_act.initialize_repository(
            root / "link" / "new" / "project-1", project_id="project-1",
            actor=ACTOR)
    assert not (outside / "new").exists(), (
        "the refused act created directories inside the linked tree")
    assert not any(outside.iterdir()), sorted(outside.iterdir())


@pytest.mark.skipif(os.open not in os.supports_dir_fd,
                    reason="this platform has no `dir_fd`, where the act "
                           "documents `lstat` as the weaker guarantee")
def test_a_name_relinked_to_the_same_directory_is_still_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The identity check compared DESTINATIONS, and a symlink has the same one.

    Round 13 added the post-initialization check so the map row cannot name a
    directory the history is not in — but it asked `os.stat(location)`, which
    FOLLOWS the link. Move the verified directory aside and point `location` at
    it: the device and inode match, the act succeeds, and the durable map now
    holds a name somebody can re-target afterwards to serve another repository
    (Copilot review of openDox-code#26, round 14, suppressed).
    """
    from opendox.runtime import repository_act

    location = tmp_path / "project-relinked"
    real = repository_act._initialize_with

    def _relink_then_initialize(git, where, **kwargs):
        commit = real(git, where, **kwargs)
        moved = tmp_path / "the-real-directory"
        where.rename(moved)
        where.symlink_to(moved, target_is_directory=True)
        _relink_then_initialize.moved = moved
        return commit

    monkeypatch.setattr(repository_act, "_initialize_with",
                        _relink_then_initialize)
    with pytest.raises(repository_act.RepositoryActRefused) as caught:
        repository_act.initialize_repository(
            location, project_id="project-relinked", actor=ACTOR)
    assert "re-examined" in str(caught.value) or \
        "no longer names" in str(caught.value), str(caught.value)
    # The history is where the act put it; the map row is not written.
    assert (_relink_then_initialize.moved / "HEAD").is_file()


# -- Copilot's fifteenth and sixteenth rounds on #26 --------------------------


def test_an_ambient_config_parameters_channel_cannot_reconfigure_this_git(
        adapter, repository: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`GIT_CONFIG_PARAMETERS` IS the `-c` channel, and it was not stripped.

    It is how git hands its own `-c` settings to the commands it runs, and it
    is read on the way IN as well — so a runtime started from inside a git
    invocation (a hook, an alias, a `filter-branch`) inherited whatever that
    process had set. Round 13 stripped `GIT_DIR`, `GIT_CONFIG` and the
    count/key/value form and left this one, which reaches the same settings by
    another name (Copilot review of openDox-code#26, rounds 15 and 16).

    Driven with `core.hooksPath`, because it is the one this package sets on
    every invocation and therefore the one whose subversion is measurable.
    """
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS",
                       f"'core.hooksPath={hooks}' 'protocol.ext.allow=always'")
    # The premise, measured: git DOES read this channel.
    ambient = subprocess.run(
        ["git", "-C", str(repository), "config", "--get", "core.hooksPath"],
        capture_output=True, text=True, env={**_GIT_ENV,
                                             "GIT_CONFIG_PARAMETERS":
                                             f"'core.hooksPath={hooks}'"})
    assert ambient.stdout.strip() == str(hooks), ambient

    # And this package's runner does not.
    git = lga.GitRunner(repository)
    assert git.run("config", "--get", "core.hooksPath").stdout.decode().strip() \
        == os.devnull, "an ambient GIT_CONFIG_PARAMETERS reached this runner"
    assert git.run("config", "--get", "protocol.ext.allow").returncode != 0
    assert "GIT_CONFIG_PARAMETERS" in lga._GIT_ENVIRONMENT_OVERRIDES
    # The corpus still resolves and still writes, with the channel set.
    corpus = _resolve(adapter, repository)
    assert adapter.write_back(corpus, ca.DocumentId("project-1", "a.md"),
                              b"# a\n", actor=ACTOR,
                              basis_revision=corpus.revision or "")


def test_a_write_is_bound_to_the_repository_the_root_check_verified(
        adapter, repository: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The re-check proved a fact about a NAME, and the write used the name.

    Every call after it — `hash-object`, `read-tree`, `commit-tree`,
    `update-ref` — went through `self._git(corpus)`, which resolves
    `corpus.location` again, so a location renamed or re-linked between the
    check and the commit put the write in a different repository after this
    function had proved it would not (Copilot review of openDox-code#26, round
    16). The directory is opened `O_NOFOLLOW` and git is handed
    `/proc/self/fd/<n>` for that descriptor, which is the binding
    `repository_act.initialize_repository` already uses.

    The race is made deterministic by performing the swap at the only moment it
    could happen: after the descriptor is open and before the first git call.
    """
    if not Path("/proc/self/fd").is_dir():        # the ladder's lower rung
        pytest.skip("no /proc/self/fd on this platform, where the act "
                    "documents the pathname fallback as the weaker guarantee")
    # A CLONE, deliberately: it holds the resolved commit, so the write that
    # follows the swapped name can SUCCEED there. MEASURED against the previous
    # head with exactly this shape — the swap driven from inside the root
    # re-check — `write_back` returned a receipt and the decoy came out with
    # two commits and `a.md` in its tree while the real corpus was untouched.
    # (With an unrelated repository as the decoy the old code failed at
    # `read-tree` instead: a confusing refusal rather than a write into the
    # wrong history. The clone is the case that loses data.)
    decoy = tmp_path / "decoy"
    subprocess.run(["git", "clone", "--bare", "-q", str(repository),
                    str(decoy)], check=True, env=_GIT_ENV)
    corpus = _resolve(adapter, repository)
    real = lga.LocalGitCorpus._write_back_bound
    swapped = {"done": False}

    def _swap_then_write(self, git, *args, **kwargs):
        if not swapped["done"]:
            swapped["done"] = True
            repository.rename(tmp_path / "moved-aside")
            decoy.rename(repository)
        return real(self, git, *args, **kwargs)

    monkeypatch.setattr(lga.LocalGitCorpus, "_write_back_bound",
                        _swap_then_write)
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus, ca.DocumentId("project-1", "a.md"),
                           b"# a\n", actor=ACTOR,
                           basis_revision=corpus.revision or "")
    assert swapped["done"], "the race this test drives did not happen"
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert "re-pointed" in caught.value.refusal.detail

    # NEITHER repository received the commit. Against the previous head the
    # DECOY did: `self._git(corpus)` resolved the name again, the decoy's own
    # root matched it, and the write landed in a repository the caller never
    # named.
    for where in (tmp_path / "moved-aside", repository):
        assert _git(where, "rev-list", "--count", "HEAD") == "1", where
        assert _git(where, "ls-tree", "-r", "--name-only", "HEAD") == "", where


# -- Copilot's seventeenth round on #26 --------------------------------------


def test_asking_a_repository_what_changed_runs_no_program_of_its_own(
        adapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """NOT A REGRESSION TEST — it passes against the previous head, and the
    measurement is why.

    The review reported that `check` can execute an arbitrary program, because
    `git diff` honours `diff.external` and the runner preserved
    `GIT_EXTERNAL_DIFF` (Copilot review of openDox-code#26, round 17). The
    mechanism is real; this call site does not reach it. MEASURED on git
    2.43.0, with `diff.external` set in the repository and `GIT_EXTERNAL_DIFF`
    set in the environment:

        git diff                       external driver RAN
        git diff HEAD                  external driver RAN
        git diff --name-only           did NOT run
        git diff --name-only -z HEAD   did NOT run

    An external driver renders a diff BODY, and `--name-only` renders none, so
    `check`'s question never reaches it either way.

    The guard is kept and the case is labelled, which is this act's rule for a
    premise that turned out to be false: `--no-ext-diff --no-textconv` on the
    command and `GIT_EXTERNAL_DIFF` in the sanitizer cost nothing, and they are
    what makes the ABSENCE above a property of this call rather than a property
    of the flag set it happens to use.
    """
    working = tmp_path / "checkout"
    working.mkdir()
    _git(working, "init", "--initial-branch=main", ".")
    (working / "a.md").write_text("one\n", encoding="utf-8")
    _git(working, "add", "a.md")
    _git(working, "commit", "-m", "first")
    (working / "a.md").write_text("two\n", encoding="utf-8")   # a divergence

    marker = tmp_path / "external-diff-ran"
    planted = tmp_path / "evil-diff"
    planted.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n", encoding="utf-8")
    planted.chmod(0o755)
    _git(working, "config", "diff.external", str(planted))
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", str(planted))

    corpus = adapter.resolve(ca.CorpusRef(name="checkout",
                                          location=str(working)))
    findings = adapter.check(corpus)
    assert [finding.subject for finding in findings] == ["a.md"]
    assert not marker.exists(), (
        "`check` executed the program the repository's own config named")
    assert "GIT_EXTERNAL_DIFF" in lga._GIT_ENVIRONMENT_OVERRIDES

    # THE MECHANISM IS REAL, and this is the half of the measurement that says
    # so: the same repository, the same planted program, a diff that renders a
    # BODY.
    subprocess.run(["git", "-C", str(working), "diff"],
                   capture_output=True, env={**_GIT_ENV,
                                             "GIT_EXTERNAL_DIFF": str(planted)})
    assert marker.exists(), (
        "this git honours neither `diff.external` nor `GIT_EXTERNAL_DIFF`, so "
        "the absence above says nothing")


def test_a_branch_name_that_is_not_utf_8_is_served_and_not_raised(
        adapter, tmp_path: Path) -> None:
    """A ref name is BYTES; git forbids only a short list of characters.

    The strict `.decode()` on `symbolic-ref` raised `UnicodeDecodeError` out of
    `resolve` for an otherwise valid repository — an exception where this
    interface owes a corpus or a refusal (Copilot review of openDox-code#26,
    round 17). `surrogateescape` is the same round trip the pathnames get.
    """
    location = tmp_path / "odd-branch"
    location.mkdir()
    _git(location, "init", "--initial-branch=main", ".")
    # A branch whose name is a non-UTF-8 byte. `subprocess` encodes arguments
    # with the filesystem encoding and `surrogateescape`, so this is the same
    # round trip in both directions.
    odd = b"br-\xff".decode("utf-8", "surrogateescape")
    _git(location, "symbolic-ref", "HEAD", f"refs/heads/{odd}")

    corpus = adapter.resolve(ca.CorpusRef(name="odd", location=str(location)))
    assert corpus.revision is None            # unborn, and legal
    assert adapter.list_documents(corpus) == ()
    # And the write path is answered for the ref that name refers to.
    assert corpus.write_path_available


def test_the_output_of_a_network_operation_is_bounded_as_well_as_its_clock(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`out_bounded` capped the wall clock and not the bytes.

    `run()` captures both pipes to EOF with no limit, so a remote that answers
    — a hostile one, or a broken one in a loop — could stream for the whole
    timeout and have every byte held in this process while the request holds
    the caller's database transaction and the map row's lock (Copilot review of
    openDox-code#26, round 17).

    Driven with a `git` that is a script writing more than the cap: the runner
    kills it and refuses, rather than returning what it sent.
    """
    noisy = tmp_path / "git"
    noisy.write_text(
        "#!/bin/sh\n"
        f"exec dd if=/dev/zero bs=65536 count={(lga.MAX_REMOTE_OUTPUT_BYTES // 65536) + 32}"
        " 2>/dev/null\n",
        encoding="utf-8")
    noisy.chmod(0o755)
    runner = lga.GitRunner(tmp_path, str(noisy))
    with pytest.raises(lga.GitCommandFailed) as caught:
        runner.out_bounded("push", timeout=30)
    assert "more than" in str(caught.value)
    assert str(lga.MAX_REMOTE_OUTPUT_BYTES) in str(caught.value)

    # A short answer is unaffected: the cap is a cap, not a filter.
    quiet = tmp_path / "quiet-git"
    quiet.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    quiet.chmod(0o755)
    assert lga.GitRunner(tmp_path, str(quiet)).out_bounded(
        "push", timeout=30) == b"ok\n"


def test_the_push_acts_branch_name_is_the_one_head_points_at_byte_for_byte(
        tmp_path: Path) -> None:
    """`replace` is not a decode, it is a rewrite.

    `_pushable_branch` decoded `symbolic-ref` with `errors="replace"`, so a
    branch whose name is not UTF-8 came back with U+FFFD in it — and the push
    that followed named a ref that does not exist. (The review reported a
    STRICT decode raising `UnicodeDecodeError` into a 500; this decode was
    never strict. What it did was quieter and wrong in a way a 500 is not —
    Copilot review of openDox-code#26, round 17.) `surrogateescape` round-trips
    through `subprocess`, which encodes arguments the same way.
    """
    from opendox.runtime import repository_act

    location = tmp_path / "odd"
    location.mkdir()
    _git(location, "init", "--initial-branch=main", ".")
    odd = b"br-\xff".decode("utf-8", "surrogateescape")
    _git(location, "symbolic-ref", "HEAD", f"refs/heads/{odd}")

    branch = repository_act._pushable_branch(
        lga.GitRunner(location), str(location))
    assert branch == odd, repr(branch)
    assert "�" not in branch
    # And the name round-trips back INTO git, which is the whole point. Read
    # as BYTES here, because this file's own `_git` helper decodes strictly.
    head = subprocess.run(["git", "-C", str(location), "symbolic-ref", "HEAD"],
                          capture_output=True, check=True, env=_GIT_ENV)
    assert head.stdout.decode("utf-8", "surrogateescape").strip() == \
        f"refs/heads/{branch}"


def test_every_operation_goes_through_the_bound_runner() -> None:
    """A guard, and it is labelled: it pins a SHAPE, not a behaviour.

    Round 16 bound `write_back` to an open directory and round 17 extended that
    to the operations that read, because each of them made several git calls
    through a runner that re-resolved the PATHNAME every time (Copilot review
    of openDox-code#26). The behaviour is measured by
    `test_a_write_is_bound_to_the_repository_the_root_check_verified`; what
    cannot be measured from outside is that a LATER operation still goes
    through `_bound`, so it is asserted here instead of being assumed.
    """
    import inspect

    for name in ("list_documents", "read", "check", "write_back"):
        source = inspect.getsource(getattr(lga.LocalGitCorpus, name))
        assert "self._bound(" in source, (
            f"{name} takes a runner on a pathname rather than on the "
            "directory it opened")
    # `classify` reads through `read`, and `resolve` is the operation that
    # establishes the location in the first place: neither takes one of its
    # own, which is why they are not in the list.
    assert "self._bound(" not in inspect.getsource(lga.LocalGitCorpus.resolve)


def test_a_project_id_holding_a_nul_is_refused_by_name(tmp_path: Path) -> None:
    """`ValueError` is not `OSError`, and this act translates the second.

    `Path`, `os.open` and `os.mkdir` all raise `ValueError` for an embedded
    NUL, so a malformed project id walked past every handler in this module and
    reached the API as a 500 in place of the named refusal the act promises for
    every reason it will not create a repository (Copilot review of
    openDox-code#26, round 17, suppressed). It is the same guard `write_back`
    puts on `DocumentId.key`, one module over.
    """
    from opendox.runtime import repository_act

    with pytest.raises(repository_act.RepositoryActRefused) as caught:
        repository_act.repository_location(tmp_path, "project\x00one")
    assert "usable project id" in str(caught.value)
    # And nothing was created on the way to finding out.
    assert sorted(tmp_path.iterdir()) == []
    # The premise, measured: the value this guard stops would have raised
    # `ValueError`, which this act does not catch.
    with pytest.raises(ValueError):
        (tmp_path / "project\x00one").mkdir()


def test_a_known_destination_is_removed_from_gits_own_diagnostic() -> None:
    """The pattern half of the credential rule cannot match across a line.

    Deliberately: `redact_credentials` runs over git's multi-line stderr, and a
    userinfo class that admitted a newline would join a `scheme://` on one line
    to an unrelated `user@host` on another. So a LEGACY row whose credential
    spans a line could still ride the failure text git echoes back (Copilot
    review of openDox-code#26, round 17, suppressed). A caller that HOLDS the
    value does not need a pattern.
    """
    from opendox.runtime import repository_act

    legacy = "https://user:secret\npassword@host/repo.git"
    echoed = (f"fatal: unable to access '{legacy}': Could not resolve host\n"
              "hint: check the remote and try again")
    cleaned = repository_act._without(echoed, legacy)
    assert "secret" not in cleaned
    assert "password@host" not in cleaned
    assert "<redacted-url>" in cleaned
    # The rest of the diagnostic survives, which is the whole reason the
    # pattern is not widened instead.
    assert "Could not resolve host" in cleaned
    assert "hint: check the remote and try again" in cleaned
    # And the pattern alone does NOT catch it, which is the measurement that
    # makes this helper necessary rather than redundant.
    assert "secret" in lga.redact_credentials(echoed)


# -- Copilot's eighteenth round on #26 ---------------------------------------


def test_an_alias_cannot_shadow_a_command_this_runner_invokes(
        adapter, repository: Path) -> None:
    """NOT A REGRESSION TEST, and the measurement is why.

    The review reports that a mapped repository can define `[alias] remote =
    !…` and have this runner execute it (Copilot review of openDox-code#26,
    round 18). MEASURED on git 2.43.0: an alias that shadows a BUILT-IN command
    is IGNORED —

        [alias] remote = !touch MARKER   `git remote` ran the built-in
        [alias] status = !touch MARKER   `git status` ran the built-in
        [alias] revparse = !touch MARKER `git revparse` RAN THE ALIAS

    — and every command this runner invokes is a built-in, so the channel is
    closed by git itself. `-c alias.<subcommand>=` is added anyway, because it
    makes that a property of THIS call rather than of a rule a later git could
    relax, and it costs one option.
    """
    marker = repository / "ALIAS-RAN"
    for name in ("remote", "rev-parse", "ls-tree", "config"):
        _git(repository, "config", f"alias.{name}", f"!touch {marker}; echo x")

    corpus = _resolve(adapter, repository)
    assert adapter.list_documents(corpus) == ()
    assert not marker.exists(), "a repository's own alias ran in this runtime"
    assert "-c" in lga.GitRunner(repository)._argv(("rev-parse", "--git-dir"))
    assert "alias.rev-parse=" in lga.GitRunner(repository)._argv(
        ("rev-parse", "--git-dir"))

    # THE MECHANISM IS REAL under a name git does not own, which is the half
    # that says the absence above means something.
    subprocess.run(["git", "-C", str(repository), "config", "alias.notabuiltin",
                    f"!touch {marker}; echo x"], check=True, env=_GIT_ENV)
    subprocess.run(["git", "-C", str(repository), "notabuiltin"],
                   capture_output=True, env=_GIT_ENV)
    assert marker.exists(), "this git does not run `!` aliases at all"


def test_a_bounded_push_keeps_the_environment_every_other_call_gets(
        tmp_path: Path) -> None:
    """`out_bounded` handed `Popen` four variables and no `PATH`.

    `run()` builds its environment from `_sanitized_git_environment()` and
    layers the call's own on top; this round's output cap passed the call's own
    STRAIGHT to `Popen`, so the push ran without `PATH` and without
    `GIT_CONFIG_GLOBAL`/`GIT_CONFIG_SYSTEM` — which this package keeps on
    purpose, because they are the operator's own git: a credential helper, a
    proxy, a CA bundle. Inspection worked and the push it was inspecting for
    could not (Copilot review of openDox-code#26, round 18; a regression this
    round's own cap introduced).
    """
    reporter = tmp_path / "git"
    reporter.write_text("#!/bin/sh\nenv\n", encoding="utf-8")
    reporter.chmod(0o755)
    seen = lga.GitRunner(tmp_path, str(reporter)).out_bounded(
        "push", timeout=30).decode()
    variables = dict(line.split("=", 1) for line in seen.splitlines()
                     if "=" in line)
    assert "PATH" in variables, sorted(variables)
    assert variables.get("GIT_TERMINAL_PROMPT") == "0"
    assert "GIT_SSH_COMMAND" in variables
    # And the repository-SELECTING overrides are still stripped, which is the
    # property the sanitizer exists for.
    assert "GIT_DIR" not in variables


def test_a_read_cannot_be_served_from_an_enclosing_repository(
        adapter, tmp_path: Path) -> None:
    """`git -C` WALKS UP, and a descriptor does not stop that.

    The binding stops a pathname SWAP; it does not stop DISCOVERY. A location
    that stops being a repository while sitting inside another checkout was
    served from the enclosing one — the defect RULED 5714365086 Q-F3 closed at
    resolution, reachable again through every operation that reopens the
    location (Copilot review of openDox-code#26, round 18). `_bound` applies
    the same root rule the write path and the repository acts already applied.

    Driven the way it is reachable in this product: `create_repository` is
    interrupted, or a repository is removed, leaving an ordinary directory
    where the map row still points — and the root above it is somebody's
    checkout.
    """
    import shutil

    outer = tmp_path / "outer"
    outer.mkdir()
    location = _repository_at(outer / "corpus", "corpus")
    corpus = _resolve(adapter, location)

    # The corpus stops being a repository, and its parent becomes one.
    shutil.rmtree(location)
    location.mkdir()
    _git(outer, "init", "--initial-branch=main", ".")
    (outer / "a.md").write_text("a\n", encoding="utf-8")
    _git(outer, "add", "a.md")
    _git(outer, "commit", "-m", "first")

    # Against the previous head `git -C <location>` finds the OUTER repository
    # and every one of these answers for it — and refuses only BY ACCIDENT,
    # because this outer repository does not happen to contain the resolved
    # revision. That is the same accident round 16 measured on the write path:
    # with a CLONE in the way, the operation succeeds against the wrong
    # history. So the assertion is on WHICH refusal arrives — one that names
    # the repository that was found — and not merely that one does.
    for operation in (lambda: adapter.list_documents(corpus),
                      lambda: adapter.read(
                          corpus, ca.DocumentId("corpus", "a.md")),
                      lambda: adapter.check(corpus)):
        with pytest.raises(ca.CorpusRefused) as caught:
            operation()
        assert caught.value.refusal.kind in {ca.CORPUS_UNREADABLE,
                                             ca.CORPUS_ABSENT}, caught.value
        assert str(outer.resolve()) in caught.value.refusal.detail or \
            "no longer" in caught.value.refusal.detail, caught.value


def test_a_refused_project_id_is_not_echoed_back_in_the_refusal() -> None:
    """The one identifier in this act that NOTHING has validated.

    Every other message here names a project id the map already holds; this
    branch is reached by whatever the caller sent, and it put that value
    straight into a refusal the CLI prints and the API returns. The redactors
    are shaped for URLs and for libpq conninfo, not for arbitrary text, and
    they do not cover it (Copilot review of openDox-code#26, round 19).

    MEASURED against the previous head, through `redact_credentials` — the
    strongest redactor either surface applies:

        'user:secret@host/path'  ->  "'user:secret@host/path' is not a usable
                                      project id for a directory name"
        '//user:pw@h/x'          ->  "'//user:pw@h/x' is not a usable …"

    Both hold a `/`, so both reach this branch, and both come back verbatim.
    (The report named `https://user:secret\\n@host`, which `repr` happens to
    rescue by escaping the newline into a form the URL pattern then matches.
    The class is real where that one example is not, which is why the case
    below drives the two shapes that survive.)

    A path-component rule has nothing to say that needs the value: it says
    WHICH rule was broken, and the caller already holds what it sent.
    """
    from opendox.runtime.local_git_adapter import redact_credentials
    from opendox.runtime.repository_act import (RepositoryActRefused,
                                                repository_location)

    for sent, secret, reason in (
            ("user:secret@host/path", "secret", "holds a '/'"),
            ("//user:pw@h/x", "pw", "holds a '/'"),
            ("https://user:hunter2\n@host", "hunter2", "holds a '/'"),
            ("a\x00b", "a\x00b", "holds a NUL"),
            ("", "", "is empty"),      # nothing to leak; the reason is the point
    ):
        with pytest.raises(RepositoryActRefused) as caught:
            repository_location("/nonexistent-root-for-this-case", sent)
        message = str(caught.value)
        assert reason in message, (sent, message)
        assert "usable project id" in message, message
        # The value is absent from the refusal AND from what a surface would
        # print after redacting it — the second is the claim that matters,
        # because redaction is what used to be relied on here.
        for rendered in (message, redact_credentials(message)):
            # (The empty id has nothing to look for; it is here for the reason
            # the refusal names, not for the containment check.)
            if sent:
                assert sent not in rendered, (sent, rendered)
                assert secret not in rendered, (secret, rendered)

    # `.` and `..` are their own case: the refusal NAMES that rule, and the
    # rule's name is the value, which is not a secret and is the only way to
    # say which rule it was. They are checked for the reason, not for absence.
    for traversal in (".", ".."):
        with pytest.raises(RepositoryActRefused) as caught:
            repository_location("/nonexistent-root-for-this-case", traversal)
        assert "is '.' or '..'" in str(caught.value)

    # NOT an over-refusal: an id this act can use is still returned, and the
    # path is still the root joined with it.
    usable = repository_location("/srv/projects", "9f2c-a-real-id")
    assert usable == Path("/srv/projects/9f2c-a-real-id")


def test_the_subcommand_is_the_same_answer_for_the_guard_and_the_message(
        tmp_path: Path) -> None:
    """`-c <name>=<value>` opens the push, and both readers of it were wrong.

    `repository_act` pushes with `("-c", "protocol.ext.allow=never", "push",
    …)`. Two places ask which of those is the subcommand, and each asked a
    different question:

    * `GitCommandFailed` took `args[0]`, so a failed push reported itself as
      `git -c exited 128` — a refusal that names no operation (Copilot review
      of openDox-code#26, round 19).
    * `_argv` took the first argument not starting with `-`, which for this
      vector is the `-c` VALUE, `protocol.ext.allow=never`. It is not an
      identifier, so `-c alias.<subcommand>=` was silently NOT added, and round
      18's guard was absent on precisely the call that reaches a remote. The
      review found the first; the second was under it.

    MEASURED against the previous head, on this exact vector:

        _argv(push)  ->  no `alias.` option at all
        str(failed)  ->  "git -c exited 128: fatal: remote gone"

    `subcommand_of` is the one rule now, and this pins both readers to it.
    """
    import inspect
    import subprocess as _subprocess

    from opendox.runtime import repository_act as act

    vector = ("-c", "protocol.ext.allow=never", "push",
              "--receive-pack=git-receive-pack", "origin", "main")
    assert lga.subcommand_of(vector) == "push"

    argv = lga.GitRunner(tmp_path)._argv(vector)
    assert "alias.push=" in argv, argv

    failed = lga.GitCommandFailed(vector, _subprocess.CompletedProcess(
        args=[], returncode=128, stdout=b"", stderr=b"fatal: remote gone"))
    assert str(failed).startswith("git push exited 128"), str(failed)

    # THE VECTOR IS THE ACT'S OWN, not one invented here: if the push stops
    # opening with `-c`, this case is measuring a shape that no longer exists.
    source = inspect.getsource(act._push_to_remote_with)
    assert 'out_bounded("-c", "protocol.ext.allow=never",' in source, (
        "the push no longer opens with a `-c` pair; re-derive this case")

    # And an ordinary vector is unchanged by the new rule.
    assert lga.subcommand_of(("rev-parse", "--git-dir")) == "rev-parse"
    assert lga.subcommand_of(("--literal-pathspecs", "status")) == "status"
    assert lga.subcommand_of(()) == ""


def test_a_branch_name_ending_in_non_ascii_whitespace_is_not_trimmed(
        adapter, tmp_path: Path) -> None:
    """`.strip()` removed more than git wrote, in all three places that decode.

    A ref name is bytes; `git check-ref-format` forbids ASCII control
    characters, which is `\\n` and `\\r` — and nothing else `str.strip()`
    removes. `"\\xa0".isspace()` is True in python, so a branch legally named
    `feature\\xa0` was trimmed to `feature`: the write path would advance a
    DIFFERENT ref and the push would target one that does not exist (Copilot
    review of openDox-code#26, round 19, which named the act; the adapter had
    it twice).

    MEASURED: git 2.43.0 accepts the name (`check-ref-format --branch` exits 0)
    and `symbolic-ref HEAD` writes `refs/heads/feature\\302\\240\\n`.
    Against the previous head `_pushable_branch` answered `'feature'` for
    that repository — a branch that does not exist.
    """
    from opendox.runtime.repository_act import _pushable_branch

    branch = "feature "
    location = _repository_at(tmp_path / "corpus", "corpus")
    _git(location, "branch", "-m", branch)

    assert lga.decoded_ref_name(b"refs/heads/" + branch.encode() + b"\n") == \
        "refs/heads/" + branch
    assert _pushable_branch(lga.GitRunner(location), str(location)) == branch

    # The adapter agrees, through the path that decides what a write advances.
    corpus = _resolve(adapter, location)
    receipt = adapter.write_back(
        corpus, ca.DocumentId("corpus", "n.md"), b"n\n", actor="Writer",
        basis_revision=corpus.revision,
        reason="a branch with a non-breaking space")
    assert receipt.correlation_id
    head = subprocess.run(["git", "-C", str(location), "symbolic-ref", "HEAD"],
                          capture_output=True, env=_GIT_ENV).stdout
    assert head.decode("utf-8", "surrogateescape").rstrip("\r\n") == \
        "refs/heads/" + branch, head
    # And the write landed on THAT branch, not on a trimmed neighbour: the
    # commit it made is the one `refs/heads/feature\xa0` now points at, and
    # the trimmed name does not exist at all.
    assert subprocess.run(
        ["git", "-C", str(location), "rev-parse", "--verify", "--quiet",
         "refs/heads/" + branch], capture_output=True,
        env=_GIT_ENV).returncode == 0
    assert subprocess.run(
        ["git", "-C", str(location), "rev-parse", "--verify", "--quiet",
         "refs/heads/feature"], capture_output=True,
        env=_GIT_ENV).returncode != 0, (
        "a branch this write invented by trimming the name it was given")
    listed = adapter.list_documents(_resolve(adapter, location))
    assert "n.md" in {document.key for document in listed}, listed


def test_the_environment_sanitizer_strips_every_command_naming_variable(
        tmp_path: Path) -> None:
    """`GIT_PROXY_COMMAND` names a program and git executes it.

    It is `core.gitProxy`'s environment half, honoured for a `git://` remote —
    and the transport guard says nothing about it: `protocol.ext.allow=never`
    refuses the `ext::` transport, and this is the `git://` one running an
    ambient command instead (Copilot review of openDox-code#26, round 21). It
    joins `GIT_EXTERNAL_DIFF` and `GIT_CONFIG_PARAMETERS`, which are on this
    list for exactly the same reason.

    The assertion is on the LIST as a rule rather than on one name: every
    variable this module strips must be one git reads, and every variable that
    names a COMMAND must be stripped.
    """
    for named in ("GIT_EXTERNAL_DIFF", "GIT_CONFIG_PARAMETERS",
                  "GIT_PROXY_COMMAND"):
        assert named in lga._GIT_ENVIRONMENT_OVERRIDES, named

    # And it really is removed from what a child gets, through the same
    # builder the bounded path uses.
    reporter = tmp_path / "git"
    reporter.write_text("#!/bin/sh\nenv\n", encoding="utf-8")
    reporter.chmod(0o755)
    seen = lga.GitRunner(tmp_path, str(reporter)).out_bounded(
        "push", timeout=30).decode()
    variables = {line.split("=", 1)[0] for line in seen.splitlines()
                 if "=" in line}
    assert "GIT_PROXY_COMMAND" not in variables, sorted(variables)
    assert "PATH" in variables


def test_a_refusal_raised_while_binding_takes_the_operations_own_kind(
        adapter, tmp_path: Path) -> None:
    """`_repository_root` says CORPUS_UNREADABLE, which `write_back` never declares.

    Round 18 put the root re-check inside `_bound`, BEFORE the yield —
    and `_write_back_bound`'s own remap of that kind is after it, so it is
    never reached. A checkout whose `.git` is removed after `resolve` therefore
    sent a caller branching on `err.refusal.kind` a kind this operation does
    not promise: the interface gives `write_back` exactly two (Copilot review
    of openDox-code#26, round 21).

    MEASURED both ways on that shape:

        previous head   corpus-unreadable      (not declared)
        here            write-path-unreachable (declared), with the original
                        kind kept in the detail
    """
    import shutil

    location = _repository_at(tmp_path / "corpus", "corpus")
    corpus = _resolve(adapter, location)
    # A DIRECTORY THAT IS NO LONGER A REPOSITORY, in whichever shape this
    # helper builds: a work tree's `.git`, or a bare repository's own files.
    if (location / ".git").exists():
        shutil.rmtree(location / ".git")
    else:
        for entry in ("HEAD", "objects", "refs", "config"):
            target = location / entry
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
    assert location.is_dir()

    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus, ca.DocumentId("corpus", "a.md"), b"x\n",
                           actor="W", basis_revision=corpus.revision or "",
                           reason="r")
    assert caught.value.refusal.kind in {ca.CORPUS_READ_ONLY,
                                         ca.WRITE_PATH_UNREACHABLE}, \
        caught.value.refusal
    # Nothing is hidden: the kind the probe itself used is in the detail.
    assert ca.CORPUS_UNREADABLE in caught.value.refusal.detail

    # And a READ, whose declared kinds include that one, is unchanged.
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.list_documents(corpus)
    assert caught.value.refusal.kind in {ca.CORPUS_UNREADABLE,
                                         ca.CORPUS_ABSENT}, caught.value.refusal


def test_a_libpq_password_in_a_stored_remote_is_redacted() -> None:
    """A remote is an arbitrary string, and the two rules read URLs.

    `redact_remote_url` delegates to `redact_credentials`, whose two shapes are
    userinfo and a query/fragment parameter. `host=db password=hunter2` is
    neither, so the attach response, the map endpoints and the CLI returned it
    verbatim (Copilot review of openDox-code#26, round 21).

    Only the password field goes — `host=db` stays, for the same reason the
    query form keeps its host: a destination an operator cannot locate is a
    refusal that costs more than it protects.
    """
    for carried, gone in (
            ("host=db password=hunter2", "hunter2"),
            ("host=db password='two words' port=5432", "two words"),
            ('host=db password="quoted here"', "quoted here"),
            ("sslpassword=keypass host=db", "keypass"),
    ):
        redacted = lga.redact_remote_url(carried)
        assert gone not in redacted, (carried, redacted)
        assert "<redacted" in redacted, redacted
    assert "host=db" in lga.redact_remote_url("host=db password=hunter2")

    # NOT an over-match: an ordinary remote is untouched, and the two shapes
    # that were already covered still answer as they did.
    assert lga.redact_remote_url("https://host/repo.git") == \
        "https://host/repo.git"
    assert lga.redact_remote_url("postgresql://u:p@h/db") == "<redacted-url>"
    assert lga.redact_remote_url("https://host/r.git?token=ghp_x") == \
        "https://host/r.git?token=<redacted>"


def test_a_repository_whose_name_ends_in_a_space_is_read_back_whole(
        adapter, tmp_path: Path) -> None:
    """`.strip()` truncated the ROOT git named, so the root check refused itself.

    A project id is refused for `/`, a NUL, `.`/`..`, a control character and
    for not being one path component — so `"project "` is a LEGAL id, and this
    act creates a repository at a location ending in a space. Reading the root
    back with `.strip()` named the TRIMMED directory, and the comparison that
    proves "this is the repository the caller named" therefore refused a
    repository this act had just created (Copilot review of openDox-code#26,
    round 22, on the adapter AND on the act; both read a path that way).

    MEASURED against the previous head, on a repository this act had just
    created at `<tmp>/project `:

        adapter.resolve  ->  REFUSED corpus-unclassifiable, "this
                             directory is not a git repository; it is
                             INSIDE one, whose root is <tmp>/project"
        the act's root check -> REFUSED, naming the same trimmed path

    — a path that does not exist, invented by the reader.

    `decoded_path` removes the ONE newline git wrote and nothing else. It
    cannot do better than that — `rev-parse` has no `-z`, so a pathname really
    is terminated by a byte it could contain — and the other half of that
    ambiguity is closed where the name is chosen: `repository_location` refuses
    a control character now.
    """
    from opendox.runtime.repository_act import _refuse_unless_repository_root

    assert lga.decoded_path(b"/srv/projects/project \n") == \
        "/srv/projects/project "
    assert lga.decoded_path(b"/srv/x") == "/srv/x"          # no terminator
    assert lga.decoded_path(b"/srv/x\n\n") == "/srv/x\n"    # exactly one

    location = _repository_at(tmp_path / "project ", "project ")
    assert str(location).endswith(" ")

    # The adapter reads it back, and every operation on it answers.
    corpus = _resolve(adapter, location)
    assert corpus.location == str(location)
    assert adapter.list_documents(corpus) == ()      # a fresh repository
    assert adapter.check(corpus) is not None
    receipt = adapter.write_back(
        corpus, ca.DocumentId("project ", "n.md"), b"n\n", actor="W",
        basis_revision=corpus.revision or "", reason="a trailing space")
    assert receipt.correlation_id
    # and the write is visible through a fresh resolve of the same name.
    assert {document.key for document in
            adapter.list_documents(_resolve(adapter, location))} == {"n.md"}

    # And the ACT's own root check agrees, which is the other reported site.
    _refuse_unless_repository_root(lga.GitRunner(location), location)


def test_check_does_not_run_a_filter_the_corpus_names(
        adapter, tmp_path: Path) -> None:
    """`--no-ext-diff` and `--no-textconv` say nothing about `filter.<name>`.

    A tracked file carrying a `filter=` attribute makes `git diff --name-only`
    run that driver's `clean` command, because deciding whether the file
    DIFFERS means normalizing it first. So merely ASKING a project repository
    what changed executed a program the repository chose — the same class round
    17 closed for `diff.external`, through a door it did not cover (Copilot
    review of openDox-code#26, round 23).

    MEASURED on git 2.43.0, on exactly the invocation `check` makes:

        git diff --no-ext-diff --no-textconv --name-only     clean RAN
        + `-c filter.evil.clean=`                            did NOT run
        + `-c core.attributesfile=/dev/null`                 clean RAN

    — the last because the ATTRIBUTE is in the repository's own
    `.gitattributes`, so only the driver can be emptied.
    """
    # A CHECKOUT, not the bare repository this act creates: a clean filter is
    # about a WORKTREE file, and `check` returns early for a bare corpus.
    location = tmp_path / "corpus"
    location.mkdir()
    _git(location, "init", "--initial-branch=main", ".")
    marker = tmp_path / "CLEAN_RAN"
    (location / "a.md").write_text("hello\n", encoding="utf-8")
    (location / ".gitattributes").write_text("*.md filter=evil\n",
                                             encoding="utf-8")
    _git(location, "add", "-A")
    _git(location, "commit", "-m", "with an attribute")
    _git(location, "config", "filter.evil.clean",
         f"sh -c 'touch {marker}; cat'")
    _git(location, "config", "filter.evil.smudge", "cat")
    (location / "a.md").write_text("changed\n", encoding="utf-8")

    corpus = _resolve(adapter, location)
    findings = adapter.check(corpus)
    assert not marker.exists(), (
        "a filter the corpus named ran in this process during `check`")
    # AND THE ANSWER IS STILL AN ANSWER: the changed file is reported.
    assert any(finding.subject == "a.md" for finding in findings), findings

    # THE PREMISE, measured rather than assumed: that driver really does run
    # under the plain invocation.
    subprocess.run(["git", "-C", str(location), "diff", "--no-ext-diff",
                    "--no-textconv", "--name-only"],
                   capture_output=True, env=_GIT_ENV)
    assert marker.exists(), (
        "this git does not run a clean filter for `diff --name-only`, so the "
        "case above proves nothing on this platform")


def test_a_worktree_scoped_clean_filter_is_emptied_like_a_local_one(
        adapter: lga.LocalGitCorpus, tmp_path: Path) -> None:
    """`--local` is not all of a repository's own config.

    THE FINDING (Copilot review of openDox-code#26, round 29): with
    `extensions.worktreeConfig` set, a LINKED WORKTREE keeps its own
    `config.worktree`, and a `filter.<name>.clean` defined there is invisible
    to `git config --local` and is still run by `git diff --name-only` — so
    `check` executed repository-controlled code despite round 23's overrides.

    MEASURED on git 2.43.0, which is what makes this a defect and not a
    hypothesis:

        git config extensions.worktreeConfig true
        git config --worktree filter.evil.clean 'sh -c "echo PWNED >&2; cat"'
        git config --local --get-regexp '^filter\\.'    -- exit 1, nothing
        git config --worktree --get-regexp '^filter\\.'  -- filter.evil.clean …
        git diff --name-only                           -- PWNED

    The override already worked (`-c filter.evil.clean=` silenced it); what did
    not was FINDING the name to override. Both scopes are read now.
    """
    location = tmp_path / "worktree-config"
    location.mkdir()
    _git(location, "init", "--initial-branch=main", ".")
    marker = tmp_path / "WORKTREE_CLEAN_RAN"
    (location / "a.md").write_text("hello\n", encoding="utf-8")
    (location / ".gitattributes").write_text("*.md filter=evil\n",
                                             encoding="utf-8")
    _git(location, "add", "-A")
    _git(location, "commit", "-m", "with an attribute")
    # THE WORKTREE SCOPE, which `--local` does not report.
    _git(location, "config", "extensions.worktreeConfig", "true")
    _git(location, "config", "--worktree", "filter.evil.clean",
         f"sh -c 'touch {marker}; cat'")
    (location / "a.md").write_text("changed\n", encoding="utf-8")

    listed = subprocess.run(
        ["git", "-C", str(location), "config", "--local", "--name-only",
         "--get-regexp", r"^filter\..*\.(clean|smudge|process)$"],
        capture_output=True, env=_GIT_ENV)
    assert listed.returncode != 0 and not listed.stdout.strip(), (
        "`--local` reports the worktree-scoped driver on this git, so this "
        "case measures nothing")

    corpus = _resolve(adapter, location)
    findings = adapter.check(corpus)
    assert not marker.exists(), (
        "`check` ran a clean filter defined in the worktree scope")
    assert any(finding.subject == "a.md" for finding in findings), findings

    # THE PREMISE, measured rather than assumed: that driver really does run
    # under the plain invocation.
    subprocess.run(["git", "-C", str(location), "diff", "--no-ext-diff",
                    "--no-textconv", "--name-only"],
                   capture_output=True, env=_GIT_ENV)
    assert marker.exists(), (
        "this git does not run a worktree-scoped clean filter for `diff "
        "--name-only`, so the case above proves nothing on this platform")


def test_no_signing_program_the_repository_names_is_ever_run(
        tmp_path: Path) -> None:
    """`gpg.program` is a program, and signing is what invites it.

    THE FINDING (Copilot review of openDox-code#26, round 29): a repository can
    set `commit.gpgSign=true` and `gpg.program` to an executable, "so both
    `initialize_repository` and `write_back` can run repository-controlled code
    through `commit-tree`".

    MEASURED FALSE FOR `commit-tree`, and TRUE for the push, which is the more
    interesting half. With `gpg.program` pointing at a script on git 2.43.0:

      * `git commit-tree` produced a commit and did NOT run it — `commit.gpgSign`
        is `git commit`'s, and `commit-tree` signs only for `-S`;
      * `git commit` DID run it, the control: `PWNED ran with: --status-fd=2
        -bsau …`. This act makes no `git commit`, only `commit-tree`;
      * `push.gpgSign=true` DID reach the push, which this act performs, and
        failed it with `the receiving end does not support --signed push`
        before any receiver had agreed to anything. Against a receiver that
        does support it, that is the repository choosing which program this
        process runs.

    All three switches are pinned off in the common argv rather than the one
    that is reachable today: they cost one option each, and which of them is
    reachable is git's to change. This case asserts the argv AND drives the
    reachable one end to end.
    """
    runner = lga.GitRunner(root=tmp_path)
    argv = runner._argv(("status",))
    for key in ("commit.gpgSign=false", "tag.gpgSign=false",
                "push.gpgSign=false"):
        assert key in argv, (key, argv)
        assert argv.index("-c") < argv.index(key), "an option after the verb"

    # AND THE REACHABLE ONE, end to end. A repository that turns on signed
    # pushes and names a program cannot make this runner do either.
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--initial-branch=main", ".")
    (source / "a.md").write_text("hello\n", encoding="utf-8")
    _git(source, "add", "-A")
    _git(source, "commit", "-m", "one")
    destination = tmp_path / "governed.git"
    subprocess.run(["git", "init", "-q", "--bare", str(destination)],
                   check=True, capture_output=True, env=_GIT_ENV)
    marker = tmp_path / "GPG_RAN"
    program = tmp_path / "gpg.sh"
    program.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    program.chmod(0o755)
    _git(source, "config", "push.gpgSign", "true")
    _git(source, "config", "gpg.program", str(program))
    _git(source, "remote", "add", "origin", str(destination))

    # THE PREMISE: plain git fails this push because the repository asked for a
    # signed one.
    plain = subprocess.run(
        ["git", "-C", str(source), "push", "origin", "main:main"],
        capture_output=True, env=_GIT_ENV)
    assert plain.returncode != 0, (
        "this git does not honour `push.gpgSign` from the repository's own "
        "config, so the case below proves nothing on this platform")

    lga.GitRunner(root=source).out_bounded(
        "push", "origin", "main:main", timeout=30)
    assert not marker.exists(), "a program the repository named was run"
    assert subprocess.run(
        ["git", "-C", str(destination), "rev-parse", "--verify", "--quiet",
         "refs/heads/main"], capture_output=True,
        env=_GIT_ENV).returncode == 0, "the push did not land"


def test_the_capability_names_every_primitive_the_walk_actually_uses(
        monkeypatch, tmp_path: Path) -> None:
    """A guard that can be absent without anybody being told is not a guard.

    TWO FINDINGS (Copilot review of openDox-code#26, round 30), both about
    `NO_FOLLOW_WALK_IS_AVAILABLE` claiming more than it checked:

    * **`O_NOFOLLOW` was not in it.** The walk opens each component with
      `getattr(os, "O_NOFOLLOW", 0)`, so on a platform holding `O_DIRECTORY`
      and `dir_fd` but not `O_NOFOLLOW` the flag is silently ZERO — every
      component open follows links — and the constant still reported the safe
      walk as available.
    * **A nameable descriptor was not in it.** `runner_bound_to` is what turns
      the verified handle into the thing git opens; without `/proc/self/fd` or
      `/dev/fd` it fell back to the PATHNAME, and the adapter and both acts
      then re-resolve that name for their root checks and their writes. The
      same-object guarantee this module documents was false there.

    Both are in the constant now, and `runner_bound_to` raises rather than
    falling back — the raise being the one that fires if the directory goes
    away between the capability check and the bind.
    """
    assert lga.NO_FOLLOW_WALK_IS_AVAILABLE, (
        "this platform cannot run the suite this case is written for")

    # EACH PRIMITIVE, REMOVED IN TURN: the constant is recomputed from `os`, so
    # the case measures the expression rather than restating it.
    source = (Path(lga.__file__).read_text(encoding="utf-8")
              .split("NO_FOLLOW_WALK_IS_AVAILABLE = ", 1)[1]
              .split("\n\n", 1)[0])
    for primitive in ('hasattr(os, "O_DIRECTORY")', 'hasattr(os, "O_NOFOLLOW")',
                      "os.mkdir in os.supports_dir_fd",
                      "os.open in os.supports_dir_fd",
                      '"/proc/self/fd"'):
        assert primitive in source, (
            f"{primitive} is not part of the capability, so a platform "
            f"without it would be told the safe walk is available")

    # AND THE BIND REFUSES RATHER THAN NAMING A PATH.
    monkeypatch.setattr(lga.os.path, "isdir", lambda _p: False)
    handle = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(lga.PlatformCannotGuardPaths) as caught:
            lga.runner_bound_to(handle, tmp_path, "git")
        assert "open descriptor" in str(caught.value)
    finally:
        os.close(handle)


# -- a commit message is a durable record, so nothing may forge a line in it --


def test_a_value_that_would_forge_a_commit_trailer_is_refused(
        adapter, repository: Path) -> None:
    """`Basis-Revision:` and `Dispatched-By:` are the write's own account of itself.

    Both values are caller-controlled and were interpolated into the trailer
    block unencoded, so `A\\nWrite-Path: forged` produced a SECOND, fabricated
    trailer — and a reader of the durable history cannot tell it from a real
    one. The same newline in `actor` went into the author and committer names,
    which git records exactly as given (Copilot review of openDox-code#26,
    round 32).

    Refused rather than encoded, which is this module's rule wherever a value
    cannot be recorded unambiguously — the NUL in a document key is refused one
    line up in the same function. An encoded trailer would still be recorded;
    it would just be recorded wrong, and permanently.
    """
    corpus = _resolve(adapter, repository)
    document = ca.DocumentId(repository.name, "ideation/first.md")

    for field, kwargs in (
            ("basis revision",
             {"basis_revision": "A\nWrite-Path: forged", "actor": ACTOR}),
            ("actor",
             {"basis_revision": corpus.revision or "",
              "actor": "Ann\nDispatched-By: somebody-else"}),
            ("actor (a bidirectional override, not a newline)",
             {"basis_revision": corpus.revision or "",
              "actor": "Ann‮Auditor"})):
        with pytest.raises(ca.CorpusRefused) as caught:
            adapter.write_back(corpus, document, b"# one\n", **kwargs)
        assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE, field
        assert "control character" in caught.value.refusal.detail, field
        # THE VALUE IS NOT ECHOED BACK: the refusal describes the shape.
        assert "forged" not in caught.value.refusal.detail, field

    # AND NOTHING WAS WRITTEN. The refusal is before the object database is
    # touched, so the branch is where it was.
    assert _resolve(adapter, repository).revision == corpus.revision

    # THE ORDINARY WRITE IS UNAFFECTED, including a reason holding newlines —
    # that is prose in the message BODY, above the trailer block, and it is not
    # what forges a trailer.
    receipt, _ = _write(adapter, repository, "ideation/first.md", b"# one\n",
                        reason="because\nthe reason has two lines")
    assert receipt.correlation_id


def test_git_identity_never_records_a_control_character_in_a_name(
) -> None:
    """The refusal above is the rule; this is what covers every other caller.

    `git_identity` sanitized only the derived email slug and put the RAW actor
    in `GIT_AUTHOR_NAME` / `GIT_COMMITTER_NAME`, which git writes into the
    commit object verbatim — and `repository_act.initialize_repository` writes
    the repository's first commit through this same function, where no protocol
    refusal stands (Copilot review of openDox-code#26, round 32).
    """
    for actor in ("Ann\nDispatched-By: somebody-else",
                  "Ann Auditor <ann\ninjected@example.invalid>",
                  "a‮b", "  \t x \r\n y  ", "\n\n", ""):
        identity = lga.git_identity(actor)
        assert set(identity) == {"GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
                                 "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"}
        for field, value in identity.items():
            assert not lga.carries_a_control_character(value), (field, actor)
        assert identity["GIT_AUTHOR_NAME"], actor

    # AND THE SHAPE IT FORBIDS IS EXERCISED: the previous spelling put the
    # actor in unchanged, which this asserts by running that spelling.
    assert lga.carries_a_control_character("Ann\nDispatched-By: x")
    assert lga.on_one_line("Ann\nDispatched-By: x") == "Ann Dispatched-By: x"
    # An ordinary name is untouched, so the sanitiser is not a rename.
    assert lga.git_identity(ACTOR)["GIT_AUTHOR_NAME"] == ACTOR


def test_the_corpus_name_and_the_document_key_are_trailer_values_too(
        adapter, repository: Path) -> None:
    """Round 32's list left out the one value that is not a keyword argument.

    `document.corpus` is caller-controlled through `CorpusRef.name` and
    `_message` writes it as the `Corpus:` trailer, so it could still inject the
    line the other three no longer can. The document KEY is the message's
    SUBJECT, where a newline ends the subject and starts a body nobody wrote
    (Copilot review of openDox-code#26, round 33).
    """
    corpus = _resolve(adapter, repository)
    for document in (ca.DocumentId("p\nCorpus: forged", "ideation/first.md"),
                     ca.DocumentId(repository.name, "a\n\nDispatched-By: x")):
        with pytest.raises(ca.CorpusRefused) as caught:
            adapter.write_back(corpus, document, b"# one\n", actor=ACTOR,
                               basis_revision=corpus.revision or "")
        assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
        assert "control character" in caught.value.refusal.detail
    assert _resolve(adapter, repository).revision == corpus.revision

    # AND THE ORDINARY WRITE IS UNAFFECTED, so the guard is not a narrowing of
    # what a corpus or a key may be called.
    receipt, _ = _write(adapter, repository, "ideation/first.md", b"# one\n")
    assert receipt.correlation_id


# -- the independent adversarial review: A26-2 and A26-4 ---------------------


def test_a_filter_behind_an_include_path_is_found_and_emptied(
        adapter: lga.LocalGitCorpus, tmp_path: Path) -> None:
    """`git config --local` does not follow `include.path`; git's reader does.

    `--includes` DEFAULTS TO OFF when a config FILE is named and ON only when
    git searches all of them — the same default as A26-1, in the one method
    whose whole job is to make `check` conservative rather than EXECUTABLE. So
    a `filter.evil.clean` defined in an included file was invisible to
    `_emptied_filters`, which returned `()`, and `git diff --name-only` then
    ran the driver in this process (independent adversarial review of
    openDox-code#26, A26-2).

    MEASURED, git 2.43.0:

        git config --local --name-only --get-regexp '^filter\\..*\\.(clean|…)$'
          -- exit 1, nothing
        git config --local --includes --name-only --get-regexp '^filter\\.…'
          -- filter.evil.clean
        GIT_TRACE=1 git diff --name-only
          -- trace: run_command: 'sh -c echo PWNED-CLEAN >&2; cat'

    Round 29 widened this probe from `--local` to `--local` + `--worktree` for
    exactly this reason; an include is the third place the name can hide, and
    the fix is the same word.
    """
    location = tmp_path / "corpus"
    location.mkdir()
    _git(location, "init", "--initial-branch=main", ".")
    marker = tmp_path / "CLEAN_RAN"
    (location / "a.md").write_text("hello\n", encoding="utf-8")
    (location / ".gitattributes").write_text("*.md filter=evil\n",
                                             encoding="utf-8")
    _git(location, "add", "-A")
    _git(location, "commit", "-m", "with an attribute")
    # THE DRIVER IS IN AN INCLUDED FILE AND NOWHERE ELSE.
    included = location / ".git" / "extra.cfg"
    # DOUBLE-QUOTED IN THE FILE, because git's config parser ends a value at
    # an unquoted `;` — the driver would be truncated and fail rather than
    # run, which would make this case pass for the wrong reason.
    included.write_text(
        f'[filter "evil"]\n\tclean = "sh -c \'touch {marker}; cat\'"\n'
        "\tsmudge = cat\n", encoding="utf-8")
    config = location / ".git" / "config"
    config.write_text(config.read_text(encoding="utf-8")
                      + "[include]\n\tpath = extra.cfg\n", encoding="utf-8")
    (location / "a.md").write_text("changed\n", encoding="utf-8")

    # THE PREMISE, measured rather than assumed, in both halves: the probe
    # without `--includes` finds nothing, and the one with it finds the name.
    plain = subprocess.run(
        ["git", "-C", str(location), "config", "--local", "--name-only",
         "--get-regexp", r"^filter\..*\.(clean|smudge|process)$"],
        capture_output=True, text=True, env=_GIT_ENV)
    assert plain.returncode != 0 and not plain.stdout.strip(), (
        "this git follows an include without being asked, so the case below "
        "proves nothing on this platform")
    with_includes = subprocess.run(
        ["git", "-C", str(location), "config", "--local", "--includes",
         "--name-only", "--get-regexp",
         r"^filter\..*\.(clean|smudge|process)$"],
        capture_output=True, text=True, env=_GIT_ENV)
    assert "filter.evil.clean" in with_includes.stdout

    # THE DRIVER REALLY DOES RUN under the plain invocation — measured FIRST,
    # because `git diff` refreshes the index's stat cache and a second diff
    # over an unchanged file runs no filter at all. That ordering is the
    # difference between a premise and an artefact.
    subprocess.run(["git", "-C", str(location), "diff", "--no-ext-diff",
                    "--no-textconv", "--name-only"],
                   capture_output=True, env=_GIT_ENV)
    assert marker.exists(), (
        "this git does not run a clean filter hidden behind `include.path` "
        "for `diff --name-only`, so the case below proves nothing here")
    marker.unlink()
    (location / "a.md").write_text("changed again\n", encoding="utf-8")

    corpus = _resolve(adapter, location)
    findings = adapter.check(corpus)
    assert not marker.exists(), (
        "a filter hidden behind `include.path` ran in this process during "
        "`check`")
    # AND THE ANSWER IS STILL AN ANSWER.
    assert any(finding.subject == "a.md" for finding in findings), findings


def test_the_scp_redaction_keeps_no_prefix_of_the_userinfo() -> None:
    """The match began at the LAST run that fitted, and the rest survived.

    The scp userinfo class excluded `:` and `/`, so
    `user:secret@host:path/r.git` redacted to `user:<redacted-url>` and a value
    holding a `/` or a second `@` left a longer prefix (`user:sec/`,
    `user:sec@`) — the username, and a prefix of whatever precedes the final
    `@`, in map responses, push failures and CLI evidence for a legacy row
    (independent adversarial review of openDox-code#26, A26-4).

    AND COPILOT'S REPORT ON THIS LINE IS REJECTED ON THE LANDED TEXT. It read
    the same line as echoing a PASSWORD; it does not, and did not before this
    change: the scp branch matched from `secret@host:` onward, so the password
    was already redacted and the username was not. git's scp grammar is
    `[user@]host:path` with no password field at all — git splits at the FIRST
    `:`, so in `user:secret@host:path` git reads the host as `user` and the
    path as `secret@host:path`, a remote that cannot authenticate with
    `secret`. The residue was disclosure of a username, which is this case.
    """
    redact = lga.redact_credentials

    # WHAT WAS DISCLOSED, and is not any more.
    assert redact("user:secret@host:path/r.git") == "<redacted-url>"
    assert redact("user:sec/ret@host:path/r.git") == "<redacted-url>"
    assert redact("user:sec@ret@host:path/r.git") == "<redacted-url>"

    # AND THE CASES THE NARROW CLASS EXISTED FOR, unchanged — `[^\\s]+` cannot
    # cross whitespace, so an ordinary sentence keeps everything but the one
    # token that really is a remote.
    assert redact("please tell bob a@b:c") == "please tell bob <redacted-url>"
    assert redact("user@[::1]:repo.git") == "<redacted-url>"
    assert redact("reached user@[::1]:repo but not later text"
                  ) == "reached <redacted-url> but not later text"
    assert redact("a@b:c and d@e:f") == "<redacted-url> and <redacted-url>"
    # A newline is still never crossed: a credential on one line must not take
    # the diagnostic on the next with it.
    assert redact("line one u@h:p\nline two kept"
                  ) == "line one <redacted-url>\nline two kept"
    # And a value that is not a remote at all is untouched.
    assert redact("no credential here /srv/x.git") == "no credential here /srv/x.git"


def test_a_ref_whose_parent_is_a_FILE_has_no_write_path(
        adapter: lga.LocalGitCorpus, repository: Path) -> None:
    """`refs/heads/foo` is a valid ref, and `refs/heads/foo/bar` cannot exist.

    `_writable_ref_home` walked up "to the nearest ancestor that exists",
    testing `is_dir()` — so an existing ref FILE at `refs/heads/foo` was walked
    STRAIGHT PAST to `refs/heads`, which is a directory and is writable, and
    resolution advertised `write_path_available=True` for a ref git cannot
    create at all: `update-ref refs/heads/foo/bar` fails because a file is in
    the way, and it fails only AFTER `write_back` has hashed the blob, written
    the tree and created the commit — unreachable objects for a refusal the
    corpus could have made at resolution (Copilot review of openDox-code#26,
    at `cec91c08`). It is the round-12 finding's own shape, one level down.

    THE PREMISE IS MEASURED FIRST: git really does refuse the nested ref while
    the file is there, so this is a corpus that cannot be written and not one
    this adapter is merely pessimistic about.
    """
    head = _git(repository, "rev-parse", "HEAD")
    _git(repository, "update-ref", "refs/heads/foo", head)
    assert (repository / "refs" / "heads" / "foo").is_file(), (
        "the ref was packed rather than written loose; the premise is gone")
    refused = subprocess.run(
        ["git", "-C", str(repository), "update-ref", "refs/heads/foo/bar",
         head], capture_output=True, env=_GIT_ENV)
    assert refused.returncode != 0, (
        "git created a ref beneath an existing ref file; the premise of this "
        "case is gone and the walk would be right to pass it")

    (repository / "HEAD").write_text("ref: refs/heads/foo/bar\n",
                                     encoding="utf-8")
    corpus = adapter.resolve(
        ca.CorpusRef(name="blocked", location=str(repository)))
    assert corpus.write_path_available is False, (
        "resolution advertised a write path for a ref whose parent is a file")

    # AND THE WRITE IS REFUSED BEFORE ANY OBJECT IS MADE, which is what the
    # advertisement is for. The object count is the evidence.
    before = _git(repository, "count-objects", "-v")
    with pytest.raises(ca.CorpusRefused) as caught:
        adapter.write_back(corpus,
                           ca.DocumentId(corpus="blocked", key="notes.md"),
                           b"# later\n", actor=ACTOR, basis_revision=None)
    assert caught.value.refusal.kind == ca.WRITE_PATH_UNREACHABLE
    assert _git(repository, "count-objects", "-v") == before, (
        "objects were written for a ref that can never be created")

    # AND THE SAME NESTING WITH NO FILE IN THE WAY IS STILL WRITABLE, so what
    # this refuses is the wall and not the nesting.
    (repository / "HEAD").write_text("ref: refs/heads/topic/bar\n",
                                     encoding="utf-8")
    assert adapter.resolve(
        ca.CorpusRef(name="free", location=str(repository))
    ).write_path_available is True


def test_the_walk_modes_only_what_it_made_itself(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The comment said "ONLY WHAT THIS WALK JUST MADE" and the code did not.

    A26-5 gave the created components an explicit `0o700`, because `os.mkdir`'s
    default is the ambient umask and at `umask 000` the repository root and
    everything under it was world-writable. The `fchmod` that settles the mode
    sat AFTER the `except FileExistsError: pass` — the branch for "another
    process got there first" — so a directory this walk did NOT create was
    re-moded to `0o700` anyway: a concurrent owner's directory (an operator's
    own mount point among them) silently narrowed by a service that only meant
    to make its own (Copilot review of openDox-code#26, at `cec91c08`).

    DRIVEN AND NOT ARGUED: `os.mkdir` is replaced by one that really creates
    the directory — as the concurrent process would — with a mode of its own,
    and then raises `FileExistsError` exactly as the kernel would for the loser
    of that race. The window is otherwise unreachable from a test.
    """
    import errno
    import stat

    made_by_somebody_else = 0o755
    real_mkdir = os.mkdir

    def _lost_the_race(path, mode=0o777, *, dir_fd=None):
        real_mkdir(path, made_by_somebody_else, dir_fd=dir_fd)
        raise FileExistsError(errno.EEXIST, "File exists", str(path))

    previous = os.umask(0)                # so the mode asked for is the mode set
    try:
        target = tmp_path / "theirs" / "deeper"
        monkeypatch.setattr(os, "mkdir", _lost_the_race)
        handle = lga.open_no_follow_chain(target, create=True)
        os.close(handle)
        for made in (tmp_path / "theirs", target):
            assert stat.S_IMODE(os.stat(made).st_mode) == made_by_somebody_else, (
                f"{made} was re-moded by a walk that did not create it")

        # AND THE HALF A26-5 ADDED IS UNCHANGED: what this walk really does
        # create is still 0o700, whatever the umask is.
        monkeypatch.undo()
        ours = tmp_path / "ours" / "deeper"
        handle = lga.open_no_follow_chain(ours, create=True)
        os.close(handle)
        for made in (tmp_path / "ours", ours):
            assert stat.S_IMODE(os.stat(made).st_mode) == \
                lga.CREATED_DIRECTORY_MODE, made
    finally:
        os.umask(previous)


def test_a_bounded_push_leaves_no_descendant_running_behind_its_refusal(
        tmp_path: Path) -> None:
    """`child.kill()` signalled `git` and left its children finishing the job.

    A push's real work is in its DESCENDANTS — `ssh` for a network
    destination, `git-receive-pack` for a local one — and they hold the pipes
    this reader is draining. They kept running after the parent was killed, so
    a timed-out push could go on to COMPLETE THE REMOTE WRITE after this act
    had refused, told its caller nothing was sent and rolled the map row back
    (Copilot review of openDox-code#26, at `ebad9d65`). For a local
    destination that write lands in a real repository on this machine.

    DRIVEN WITH A PLANTED SLOW DESCENDANT, which is the only honest way to
    measure it: a stub `git` spawns a child that waits and then WRITES A
    MARKER — the stand-in for the remote write — and then stalls past the
    bound. The refusal must arrive AND the marker must never appear.

    AND THE MEASUREMENT AT `555a03c8` IS WORSE THAN THE FINDING SAID: this
    case does not merely leak a descendant there, it takes **30.0 seconds for
    a 0.6-second bound** — the surviving group holds the pipes this method
    drains, so the wall clock `out_bounded` exists to enforce is itself
    defeated, and with it the promise that a stalled remote cannot hold the
    request, the repository and the caller's database transaction. That is why
    the assertion below is on the ELAPSED time as well as on the marker.
    """
    import time

    marker = tmp_path / "the-remote-write-landed"
    stub = tmp_path / "slow-git"
    pid_file = tmp_path / "descendant.pid"
    stub.write_text(
        "#!/bin/sh\n"
        # The descendant: it outlives its parent unless the GROUP is signalled.
        f"( echo $$ > {pid_file}; sleep 2; echo landed > {marker} ) &\n"
        "sleep 30\n", encoding="utf-8")
    stub.chmod(0o755)

    runner = lga.GitRunner(root=tmp_path, executable=str(stub))
    started = time.monotonic()
    with pytest.raises(lga.GitCommandFailed) as refused:
        runner.out_bounded("push", timeout=0.6)
    assert time.monotonic() - started < 10, "the bound did not bound"
    assert "timed out" in str(refused.value)

    # THE DESCENDANT IS DEAD BEFORE THE CALL RETURNED. `kill(pid, 0)` asks
    # whether the process exists without signalling it.
    descendant = int(pid_file.read_text().strip())
    try:
        os.kill(descendant, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    except PermissionError:                  # pragma: no cover - not ours
        alive = True
    assert not alive, (
        f"the descendant {descendant} outlived the refusal; it is the process "
        "that would have finished the remote write")

    # AND IT NEVER DID THE WRITE. Waited out past its own delay, because a
    # process that is merely slow would pass an assertion made too early.
    deadline = time.monotonic() + 3.5
    while time.monotonic() < deadline:
        assert not marker.exists(), (
            "the descendant completed the remote write after this act had "
            "refused and its caller had rolled back")
        time.sleep(0.2)


def test_the_bounded_runner_gives_the_child_its_own_process_group(
        tmp_path: Path) -> None:
    """The group is what makes the kill above reach anything, so it is pinned.

    A later edit that drops `start_new_session=True` would leave the signal
    landing on THIS process's group — or on nothing — and the case above would
    still pass on a stub whose descendant happens to die with its parent. This
    asserts the mechanism directly: the child's process group is its own and is
    not this test runner's.
    """
    reported = tmp_path / "group"
    stub = tmp_path / "report-git"
    stub.write_text("#!/bin/sh\nps -o pgid= -p $$ > %s\n" % reported,
                    encoding="utf-8")
    stub.chmod(0o755)
    runner = lga.GitRunner(root=tmp_path, executable=str(stub))
    runner.out_bounded("push", timeout=10)
    child_group = int(reported.read_text().strip())
    assert child_group != os.getpgrp(), (
        "the child shares this process's group, so killing the group would "
        "signal the test runner instead of the push")


def test_the_two_readings_of_the_one_list_never_disagree_about_hiding() -> None:
    """Two lists drifted, and the API returned what the adapter would hide.

    `config` and this module each declared the credential-parameter names, and
    `config`'s lacked `pass` — so when § 3.5's merge pointed
    `app._repository_json` at `config.redacted_remote_url`, a legacy row
    spelled `https://host/r.git?pass=hunter2` was handed to every member of the
    project while this module's redactor hid it perfectly well. The same gap
    covered `sslpassword=` and the whole libpq keyword/value form (Copilot
    review of openDox-code#26, at `555a03c8`).

    THE SHARED LIST WAS NOT ENOUGH. Two implementations reading one list still
    disagreed about three shapes — `?%2574oken=` (`config` decoded a parameter
    name once, this module to a fixed point), a newline inside an scp-form
    userinfo (`config` declines to judge a value holding whitespace), and
    `;token=` — a delimiter to `config` and NOT to this module, which is the
    one of the three that ran in THIS module's leaking direction: it printed
    the shape `config` hid, and `carries_a_credential` (this redactor asked as
    a predicate) answered False with it, so `repository_act.attach_remote`
    accepted a value `identity.CoordinationStore` then refused with an error
    the route does not catch — a 500 rather than a 409. This very case asserted
    that the two never disagreed AND PASSED, because its corpus held none of
    the three: a property test that under-samples its property is the weaker
    half of the pair it guards (Copilot review of openDox-code#26, at
    `fe421882`; all three measured against a full checkout of that head).

    SO THERE IS ONE REDACTOR NOW: `config.redacted_remote_url` is a call into
    `redact_remote_url`, agreement is true by construction, and this case is
    the regression guard that it STAYS a call. The three shapes join the corpus
    anyway — they are what the next narrowing would break.

    THE TWO READINGS THAT REMAIN are the store's REFUSAL and the redaction.
    `config.credential_in_a_remote_url` asks the tuple whole-word with a
    substring rule for the needles too long to collide; the redactor asks it as
    a plain alternation (so `monkey` matches `key`). The difference is legal in
    exactly ONE direction, and that is the property below: whatever the refusal
    names as a credential, the redactor hides. The reverse — a value the store
    will not store and the API prints — is the leak.
    """

    from opendox.runtime import config

    # ONE DECLARATION, asserted structurally rather than by eye.
    assert lga.SECRET_PARAMETER_KEYS == "|".join(config.SECRET_PARAMETER_KEYS)
    assert lga._LIBPQ_PASSWORD is config.LIBPQ_PASSWORD
    # AND ONE REDACTOR. This case used to assert that two implementations
    # agreed, and it passed while they disagreed about three shapes its corpus
    # did not hold — a property test that names a property and under-samples it
    # is the weaker half of the pair it is guarding (Copilot review of
    # openDox-code#26, at `fe421882`). `config.redacted_remote_url` is a call
    # into `redact_remote_url` now, so the agreement is true by construction
    # and this case is the guard that it STAYS a call.
    assert config.redacted_remote_url("https://host/x?token=t") == \
        lga.redact_remote_url("https://host/x?token=t")

    secret = "hunter2"
    carriers = [
        # the four shapes the review measured through the API boundary
        f"host=db password={secret} dbname=x",
        f"https://github.com/o/r.git?pass={secret}",
        f"https://github.com/o/r.git?sslpassword={secret}",
        f"host=db sslpassword={secret}",
        # and the ones that were already covered, so a narrowing shows up here
        f"https://ci:{secret}@github.com/o/r.git",
        f"ci:{secret}@github.com:o/r.git",
        f"https://github.com/o/r.git?token={secret}",
        f"https://github.com/o/r.git?access_token={secret}",
        f"https://github.com/o/r.git?%74oken={secret}",
        f"https://github.com/o/r.git?api_key={secret}",
        f"https://github.com/o/r.git?X-Api-Key={secret}",
        f"https://github.com/o/r.git?sessionToken={secret}",
        f"host=db password='{secret} two' dbname=x",
        # THE THREE THE TWO IMPLEMENTATIONS DISAGREED ABOUT, each measured
        # leaking through the map endpoints or through a push refusal before
        # the redactors became one.
        f"https://github.com/o/r.git?%2574oken={secret}",     # double-encoded
        f"user:{secret[:3]}\n{secret[3:]}@github.com:o/r.git",  # newline
        f"https://github.com/o/r.git?mode=1;{'token'}={secret}",  # `;`
    ]
    innocent = [
        "ssh://git@github.com/o/r.git",
        "git@github.com:o/r.git",
        "https://github.com/o/r.git",
        "https://github.com/o/r.git?depth=1",
        "/srv/repos/project.git",
        "file:///srv/repos/project.git",
    ]

    for value in carriers:
        assert secret not in config.redacted_remote_url(value), value
        assert secret not in lga.redact_credentials(value), value

    # THE PROPERTY, over both halves of the corpus: whatever the STORE'S
    # REFUSAL names as a credential, the redactor hides. Stated as an
    # implication and not as equality, because the redactor deliberately hides
    # more — an scp-form USERNAME among them, which the store rightly stores.
    for value in carriers + innocent:
        named = config.credential_in_a_remote_url(value)
        if named is not None:
            assert lga.redact_credentials(value) != value, (
                f"{value!r} is {named} to the store and plain text to the "
                "redactor, which is the direction that leaks")
            assert secret not in lga.redact_remote_url(value), value

    # AND THE OTHER DIRECTION IS MEASURED RATHER THAN ASSUMED, because it is
    # where the remaining hole is: the redactor hides two shapes the refusal
    # does not name — `?%2574oken=` (defensible: a server decodes a parameter
    # name ONCE, so the single-encoded `?%74oken=` is the one that arrives as
    # `token`, and THAT the refusal does name) and a whitespace-bearing
    # scp-form userinfo, which `_scp_like_userinfo` declines to judge. The
    # second is a REFUSAL GAP IN LANDED § 3.5 CODE, registered on
    # openDox-code#26 rather than taken here: the store accepts such a row,
    # and only this redactor keeps it off the API. The case below in
    # `tests_runtime/test_api_endpoints.py` holds that second layer.
    hidden_but_not_refused = [
        value for value in carriers
        if config.credential_in_a_remote_url(value) is None]
    # ONE, NOW, AND IT USED TO BE TWO. The whitespace-bearing scp authority was
    # the other, and the follow-up act closed it at the store as well — the
    # refusal names the shape rather than the value it cannot read. What is
    # left is the double-encoded parameter NAME, which stays a deliberate
    # difference: a server decodes a name ONCE, so `?%74oken=` is the one that
    # arrives as `token` and IS refused, while `?%2574oken=` arrives as
    # `%74oken` and is a parameter this runtime has no reason to refuse — and
    # over-redacting its value costs nothing.
    assert len(hidden_but_not_refused) == 1, hidden_but_not_refused
    for value in hidden_but_not_refused:
        assert secret not in lga.redact_remote_url(value), value

    # AND THE INNOCENT ONES ARE UNTOUCHED BY THE NARROW READING, so the fix
    # did not buy its safety by refusing everything. (The adapter is allowed
    # to redact some of these: `git@host:path` is its scp form.)
    for value in innocent:
        assert config.redacted_remote_url(value) == value, value

    # EVERY DECLARED NAME IS A SECRET TO BOTH, so the list cannot grow an
    # entry that only one of the two readings honours.
    for key in config.SECRET_PARAMETER_KEYS:
        url = f"https://github.com/o/r.git?{key}={secret}"
        assert secret not in config.redacted_remote_url(url), key
        assert secret not in lga.redact_credentials(url), key


def test_a_legacy_remote_too_long_to_judge_is_replaced_before_it_is_decoded(
        monkeypatch) -> None:
    """The quadratic decoder was bounded by a refusal its new caller skips.

    `_decoded_parameter_name` decodes to a fixed point, which is quadratic in
    the name, and it said so — naming
    `repository_act.refuse_credential_bearing_remote`'s length refusal as what
    keeps that safe. True while every path here came through that refusal.
    Pointing `config.redacted_remote_url` at `redact_remote_url` added a path
    that does NOT: a legacy `project_repositories.remote_url` row — a restore,
    an older build, `psql` — passed no refusal at any time, so a nested
    `%2525…` chain of any length made EVERY read of the map endpoints do that
    work, once per row, for as long as the row exists (Copilot review of
    openDox-code#26, at `4156f233`, suppressed — and correct).

    THE BOUND IS ASSERTED BY SUBSTITUTION, NOT BY A CLOCK. A timing assertion
    on a decoder measures the runner's load as much as the code; this case
    makes `_decoded_parameter_name` RAISE, so reaching it at all is a failure
    and short-circuiting is the only way to pass. The value at the cap still
    goes through it, which is the other half: a remote the act ACCEPTS must
    never be over-redacted by the boundary that prints it.
    """
    from opendox.runtime import config, repository_act

    # ONE DECLARATION, held by identity across all three readers.
    assert repository_act.MAX_REMOTE_URL_CHARS is config.MAX_REMOTE_URL_CHARS

    def _never(name: str) -> str:
        raise AssertionError(
            "the decoder was reached with a value longer than the cap")

    monkeypatch.setattr(lga, "_decoded_parameter_name", _never)
    oversized = ("https://github.com/o/r.git?"
                 + "%25" * 3000 + "74oken=hunter2")
    assert len(oversized) > config.MAX_REMOTE_URL_CHARS
    assert lga.redact_remote_url(oversized) == "<redacted-url>"
    assert "hunter2" not in lga.redact_remote_url(oversized)
    # AND THE BOUNDARY THE API CALLS IS THE SAME ONE.
    assert config.redacted_remote_url(oversized) == "<redacted-url>"

    # AT THE CAP, the decoder is reached — so the bound cannot be widened into
    # refusing to read every remote, and a value the act accepts is answered in
    # part. (The substitute is removed for this half, because reaching the real
    # decoder is the assertion.)
    monkeypatch.undo()
    at_the_cap = ("https://github.com/o/r.git?token=hunter2&pad="
                  + "a" * (config.MAX_REMOTE_URL_CHARS
                           - len("https://github.com/o/r.git?token=hunter2&pad=")))
    assert len(at_the_cap) == config.MAX_REMOTE_URL_CHARS
    redacted = lga.redact_remote_url(at_the_cap)
    assert redacted != "<redacted-url>"
    assert "hunter2" not in redacted
    assert "github.com" in redacted


def test_the_group_is_signalled_from_the_id_saved_at_popen_not_looked_up_later(
        tmp_path: Path) -> None:
    """The lookup happened at KILL time, and by then the child can be reaped.

    `_stop_the_whole_group` asked `os.getpgid(child.pid)` itself. On the output
    overflow path a reader thread reaches it while the main thread may already
    have returned from `child.wait`, and MEASURED on CPython 3.12
    `os.getpgid` on a reaped pid raises `ProcessLookupError` — which that
    method swallowed, so the group was never signalled and a descendant
    survived the refusal. That is the whole defect the group kill exists to
    close, reintroduced inside its own repair (Copilot review of
    openDox-code#26, at `fe421882`). The reaped pid is also RECYCLABLE, so the
    late lookup could have named an unrelated process's group.

    THE RACE IS NOT RACED — it is arranged: the child is reaped FIRST, and the
    group is then signalled from the id captured at `Popen`. A descendant that
    dies proves the saved id was used, because the lookup is impossible by
    then and this case asserts that too.
    """
    import subprocess
    import time

    marker = tmp_path / "the-remote-write-landed"
    pid_file = tmp_path / "descendant.pid"
    stub = tmp_path / "exits-leaving-a-child"
    stub.write_text(
        "#!/bin/sh\n"
        f"( echo $$ > {pid_file}; sleep 2; echo landed > {marker} ) &\n"
        # THE PARENT EXITS AT ONCE, so it can be reaped while its descendant
        # is still working — which is the shape of the race.
        "exit 0\n", encoding="utf-8")
    stub.chmod(0o755)

    child = subprocess.Popen([str(stub)], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             start_new_session=True)
    pgid = lga.GitRunner._process_group_of(child)
    assert pgid is not None and pgid != os.getpgrp()
    child.wait()                          # REAPED FIRST, on purpose
    while not pid_file.exists():          # the descendant has announced itself
        time.sleep(0.05)

    # THE PREMISE: the id can no longer be looked up, so a method that asks for
    # it here has nothing to signal.
    with pytest.raises(ProcessLookupError):
        os.getpgid(child.pid)

    lga.GitRunner._stop_the_whole_group(child, pgid)

    descendant = int(pid_file.read_text().strip())
    try:
        os.kill(descendant, 0)
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, (
        f"the descendant {descendant} survived a kill of the saved group")

    # AND IT NEVER DID THE WRITE, waited out past its own delay.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        assert not marker.exists(), "the descendant finished its work anyway"
        time.sleep(0.2)


# -- the registered follow-ups, from #26's last two rounds --------------------


def test_the_temporary_index_is_written_through_the_held_descriptor(
        adapter, repository: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """One call in `write_back` used a PATHNAME, and it was the one that wrote.

    Every other call goes through `-C /proc/self/fd/<n>`, which is what makes
    this method's "the check and the use are one object" true. The temporary
    index did not: `rev-parse --absolute-git-dir` was turned back into a path
    and handed to `GIT_INDEX_FILE`, so a rename or replacement of the location
    AFTER the root re-check put the index — and the `unlink` that cleans it up
    — in whatever now answered to that name (Copilot review of
    openDox-code#26, at `4156f233`, registered there and built here).

    MEASURED on git 2.43.0 before the repair, with the directory renamed away
    and a symlink to a second repository put in its place after the probe: the
    absolute form wrote `opendox-index-…` into the DECOY and the descriptor-
    relative form wrote it into the real repository. The same measurement
    stands behind the shape of the fix: `--git-dir` asked through `-C` answers
    RELATIVE — `.` for the bare repository this act creates, `.git` for a
    checkout — so joining it onto the runner's own root keeps the whole path
    inside the descriptor.

    THE RACE IS ARRANGED, NOT RACED: the swap is driven from the probe itself,
    which is the only moment it could happen. It is after the root re-check, so
    this is not that check's case — that one refuses; this one proceeds, and
    the question is only WHERE the index lands.
    """
    if not Path("/proc/self/fd").is_dir():
        pytest.skip("no /proc/self/fd on this platform, where the adapter "
                    "refuses rather than falling back to a pathname")
    decoy = tmp_path / "decoy.git"
    subprocess.run(["git", "init", "--bare", "-q", str(decoy)], check=True,
                   env=_GIT_ENV)
    corpus = _resolve(adapter, repository)

    real_out = lga.GitRunner.out
    seen: dict[str, object] = {"index": None, "swapped": False}

    def _swap_after_the_probe(self, *args, **kwargs):
        answer = real_out(self, *args, **kwargs)
        # EITHER SPELLING OF THE PROBE, so this case drives the same race
        # against the head that asked `--absolute-git-dir` — otherwise it would
        # "fail" there by never swapping at all, which proves nothing.
        if (args[:1] == ("rev-parse",)
                and args[1] in ("--git-dir", "--absolute-git-dir")
                and not seen["swapped"]):
            seen["swapped"] = True
            # The name is re-pointed at a DIFFERENT repository, exactly as a
            # concurrent actor would: the descriptor this runner holds still
            # refers to the real directory.
            repository.rename(tmp_path / "moved-aside")
            repository.symlink_to(decoy)
        if args[:1] == ("read-tree",):
            seen["index"] = kwargs.get("env", {}).get("GIT_INDEX_FILE")
        return answer

    monkeypatch.setattr(lga.GitRunner, "out", _swap_after_the_probe)
    try:
        adapter.write_back(corpus, ca.DocumentId("project-1", "a.md"),
                           b"# a\n", actor=ACTOR,
                           basis_revision=corpus.revision or "")
    finally:
        monkeypatch.undo()
        if repository.is_symlink():
            repository.unlink()
        if (tmp_path / "moved-aside").exists():
            (tmp_path / "moved-aside").rename(repository)
    assert seen["swapped"], "the race this test drives did not happen"

    # THE MECHANISM, so a later edit that goes back to a pathname cannot pass
    # on a platform where the race did not fire: the index git was told to use
    # is INSIDE the descriptor the runner holds.
    index = str(seen["index"])
    assert index.startswith("/proc/self/fd/"), index

    # AND THE CONSEQUENCE. Before the repair the decoy came out holding the
    # temporary index; it has nothing in it now, and the real repository has
    # the commit.
    assert not [name for name in os.listdir(decoy)
                if name.startswith("opendox-index-")], os.listdir(decoy)
    assert _git(decoy, "rev-list", "--count", "--all") == "0"
    assert _git(repository, "ls-tree", "-r", "--name-only", "HEAD") == "a.md"
    assert not [name for name in os.listdir(repository)
                if name.startswith("opendox-index-")]


def test_a_parameter_name_is_judged_by_its_words_and_its_declared_compounds(
) -> None:
    """The substring rule that caught `sslpassword` refused ordinary names.

    Whole-word matching answered `sslpassword` — libpq's own keyword — as
    innocent, so every declared needle of six characters or more became a
    SUBSTRING. That bought one true name at the price of every compound of
    those words: MEASURED at `db5197d0`, `passwordless`, `secretary` and
    `credentials_version` were all refused as credential-bearing (Copilot
    review of openDox-code#26, suppressed, and registered there).

    A FALSE REFUSAL AT A CONFIGURATION BOUNDARY IS NOT A SAFE DIRECTION, which
    is the whole reason the whole-word rule exists: this predicate decides
    whether an install starts, and refusing a legal name costs an install that
    will not run for a reason that is not true. The compound is DECLARED now —
    there is exactly one this runtime meets — so a name joins the list because
    somebody established that a real protocol spells a secret that way.
    """
    from opendox.runtime import config

    for name in ("password", "token", "sslpassword", "access_token",
                 "X-Api-Key", "sessionToken", "apikey", "pass", "pwd",
                 # AND THE ONE THAT STAYS REFUSED ON PURPOSE: `credentials` is
                 # one of its WORDS, and the same reading is what catches the
                 # three above. Narrowing past it would mean comparing the
                 # whole NAME, which `X-Api-Key` walks straight through.
                 "credentials_version"):
        assert config.names_a_secret_parameter(name), name

    for name in ("passwordless", "secretary", "monkey", "sigma", "tokenizer",
                 "authority", "keyspace", "passage", "depth", "mode"):
        assert not config.names_a_secret_parameter(name), name

    # THE DECLARATION IS A LIST SOMEBODY OWNS, not a length rule.
    assert config.SECRET_PARAMETER_COMPOUNDS == ("sslpassword",)
    for compound in config.SECRET_PARAMETER_COMPOUNDS:
        assert config.names_a_secret_parameter(compound), compound
        # AND EVERY COMPOUND IS STILL HIDDEN BY THE REDACTOR, which is the
        # one-direction property the pair has to keep.
        assert "hunter2" not in lga.redact_credentials(
            f"https://h/r.git?{compound}=hunter2")


def test_an_authority_this_runtime_cannot_read_is_refused_by_name() -> None:
    """Both classes excluded whitespace, and a credential sat in the gap.

    `_scp_like_userinfo` declines a head holding whitespace so the refusal
    cannot start judging prose, and the redactor's `_CREDENTIAL_SHAPED`
    excludes it so an unrelated `user@host` further down git's stderr is not
    joined to the URL above it — and `user:pa ss@host:path` fell between them:
    the URL form of that value was refused and the scp form was not (Copilot
    review of openDox-code#26, at `db5197d0`). The redaction half was closed
    there; this is the STORE's own guard, registered then and built here.

    IT IS REFUSED BY SHAPE AND NEVER BY VALUE, which is what the refusal text
    has promised since § 3.5: a message that quotes the credential writes it
    into the log that reports the refusal.
    """
    from opendox.runtime import config

    for carrier in ("user:hun ter2@github.com:o/r.git",
                    "user:hun\nter2@github.com:o/r.git",
                    "user:hun\tter2@github.com:o/r.git"):
        named = config.credential_in_a_remote_url(carrier)
        assert named == "an authority this runtime cannot read as one word"
        assert "hunter2" not in named and "ter2" not in named
        # AND THE REDACTOR AGREES, which is the direction that must not open.
        assert "ter2" not in lga.redact_remote_url(carrier)

    # AND NOTHING ORDINARY IS CAUGHT BY IT. A head without `:` is a username, a
    # value without `@` has no authority, and a local path with a space in it
    # is neither.
    for ordinary in ("git@github.com:o/r.git", "ssh://git@github.com/o/r.git",
                     "/srv/my repos/x.git", "/srv/a@b/my repos/x.git",
                     "https://github.com/o/r.git"):
        assert config.credential_in_a_remote_url(ordinary) is None, ordinary


# -- openDox-code#30's follow-up #1, ruled --------------------------------


def test_a_linked_worktree_writes_through_held_metadata_descriptors(
        adapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The third shape, which the index binding did not reach.

    `-C /proc/self/fd/<n>` binds the working directory, and for the two shapes
    this act creates that IS the repository: a bare repository is its own git
    directory and a checkout's is `.git` inside it, so `rev-parse --git-dir`
    answers a RELATIVE name and the index joins onto the held root. A LINKED
    WORKTREE is neither. Measured on git 2.43.0: `<worktree>/.git` is a FILE
    naming an absolute path, `--git-dir` answers
    `<main>/.git/worktrees/<name>` — which holds the INDEX and neither
    `objects/` nor `refs/` — and those live in the COMMON directory. `resolve`
    serves that shape WRITABLE (`test_a_linked_worktree_can_reach_its_write_
    path`, landed with § 3.6), so the pathname branch was live for a supported
    corpus and its `GIT_INDEX_FILE` sat outside every descriptor this module
    holds (Copilot review of openDox-code#30).

    RULED THERE: bind both directories by descriptor and keep linked worktrees
    writable — taking the write away would reverse what § 3.6 landed with its
    own case. So `GIT_DIR` and `GIT_COMMON_DIR` name `/proc/self/fd/<n>`.

    WHAT THIS CASE DOES NOT DO IS RENAME THE GIT DIRECTORY UNDER A RUNNING
    WRITE, and that is worth recording rather than leaving as an absence.
    MEASURED: git enumerates worktrees through `<common>/worktrees/<name>` and
    compares that with the git directory in hand to decide whether a branch is
    checked out ELSEWHERE, so re-pointing that name mid-write makes `update-ref`
    refuse with `cannot lock ref … unable to resolve reference` — git's own
    bookkeeping, through a name no descriptor of ours binds, and nothing to do
    with this finding. The binding property is therefore asserted where it
    lives: on the descriptors, after the write.
    """
    if not Path("/proc/self/fd").is_dir():
        pytest.skip("no /proc/self/fd on this platform, where the adapter "
                    "refuses rather than falling back to a pathname")
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "--initial-branch=main", ".")
    (main / "a.md").write_text("a\n", encoding="utf-8")
    _git(main, "add", "a.md")
    _git(main, "commit", "-m", "first")
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-b", "side", str(worktree))
    corpus = adapter.resolve(ca.CorpusRef(name="wt", location=str(worktree)))
    assert corpus.write_path_available, "§ 3.6 serves this shape writable"

    git_dir = Path(_git(worktree, "rev-parse", "--absolute-git-dir"))
    common = Path(_git(worktree, "rev-parse", "--path-format=absolute",
                       "--git-common-dir"))
    assert git_dir.is_absolute(), "the premise: this shape names a path"
    assert git_dir != common, "and two directories, not one"

    real_out = lga.GitRunner.out
    seen: dict[str, object] = {"index": None, "env": None, "resolved": None}

    def _watch(self, *args, **kwargs):
        if args[:1] == ("read-tree",):
            seen["index"] = kwargs.get("env", {}).get("GIT_INDEX_FILE")
            seen["env"] = dict(self.held_environment)
            # WHERE THE INDEX ACTUALLY IS while git holds it open, not where
            # its name says: the descriptor is resolved at the moment of use.
            seen["resolved"] = str(Path(str(seen["index"])).parent.resolve())
        return real_out(self, *args, **kwargs)

    monkeypatch.setattr(lga.GitRunner, "out", _watch)
    receipt = adapter.write_back(corpus, ca.DocumentId("wt", "b.md"),
                                 b"# b\n", actor=ACTOR,
                                 basis_revision=corpus.revision or "")
    monkeypatch.undo()

    # THE MECHANISM: two variables, two descriptors, and the index inside the
    # worktree's own git directory rather than the common one.
    environment = seen["env"] or {}
    assert environment.get("GIT_DIR", "").startswith("/proc/self/fd/"), environment
    assert environment.get("GIT_COMMON_DIR", "").startswith("/proc/self/fd/")
    assert environment["GIT_DIR"] != environment["GIT_COMMON_DIR"], (
        "a linked worktree's own git directory and the common one are two "
        "places; one descriptor for both would put the index in the wrong half")
    assert str(seen["index"]).startswith("/proc/self/fd/"), seen["index"]
    assert seen["resolved"] == str(git_dir.resolve()), seen["resolved"]

    # THE WRITE LANDS WHERE IT SAYS, which is what "keep them writable" means.
    assert _git(worktree, "rev-parse", "refs/heads/side") == \
        receipt.correlation_id
    assert _git(worktree, "ls-tree", "-r", "--name-only", "refs/heads/side") \
        == "a.md\nb.md"
    assert _git(main, "rev-parse", "refs/heads/main") != receipt.correlation_id
    assert not [name for name in os.listdir(git_dir)
                if name.startswith("opendox-index-")], "the index is cleaned up"

    # AND THE PROPERTY THE DESCRIPTORS BUY, measured on this platform rather
    # than assumed: once the directory is open, re-pointing its NAME at another
    # valid git directory moves the name and not the descriptor. That is the
    # whole difference between this and the pathname the old code used.
    decoy = tmp_path / "decoy-gitdir"
    shutil.copytree(git_dir, decoy)
    handle = os.open(git_dir, os.O_RDONLY)
    try:
        held = lga.descriptor_path(handle)
        git_dir.rename(tmp_path / "gitdir-moved-aside")
        git_dir.symlink_to(decoy)
        assert Path(held).resolve() == (tmp_path / "gitdir-moved-aside").resolve()
        assert git_dir.resolve() == decoy.resolve(), "the NAME did move"
    finally:
        os.close(handle)
        if git_dir.is_symlink():
            git_dir.unlink()
        (tmp_path / "gitdir-moved-aside").rename(git_dir)


def test_a_local_path_that_holds_a_colon_and_an_at_sign_is_not_an_authority(
) -> None:
    """The whitespace fallback could not tell a path from an authority.

    `_an_authority_this_runtime_cannot_read` was added so a whitespace-bearing
    `user:pa ss@host:path` — invisible to both the refusal's class and the
    redactor's — could not be stored in the clear. It read the whole head
    before the last `@`, so `/srv/my repos/a:b@c.git`, a DIRECTORY whose name
    holds a colon and an at-sign and a legal `git push` destination, was
    refused as credential-bearing (Copilot review of openDox-code#30).

    GIT'S OWN RULE IS THE TEST, and it is about the FIRST colon: the
    `[user@]host:path` form is recognised only when nothing before that colon
    is a `/`. It separates the two cases exactly, which is why it is this rule
    and not "a head holding any slash" — `ci:hun/ter2@github.com:o/r.git` is a
    password containing a slash, the hole openDox-code#25 closed at `0968ff8b`,
    and its head before the first colon is `ci`.
    """
    from opendox.runtime import config

    authorities = {
        "user:pa ss@h:p": "whitespace in the password",
        "ci:hun/ter 2@github.com:o/r.git": "a slash AND a space in it",
        "user:hun\nter2@github.com:o/r.git": "a newline in it",
    }
    for carrier, why in authorities.items():
        assert config.credential_in_a_remote_url(carrier) == \
            "an authority this runtime cannot read as one word", why
        assert "ter2" not in str(config.credential_in_a_remote_url(carrier))
        assert "ss@" not in str(config.credential_in_a_remote_url(carrier))

    paths = ("/srv/my repos/a:b@c.git",
             "/srv/my repos/x.git",
             "/srv/a@b/my repos/x.git",
             "/srv/repos/2026-09-18 10:00 backup@main.git")
    for path in paths:
        assert config.credential_in_a_remote_url(path) is None, path

    # AND THE PASSWORD-WITH-A-SLASH STAYS REFUSED, by the branch it has always
    # been refused by: this rule may not buy its accuracy back from #25.
    assert config.credential_in_a_remote_url(
        "ci:hun/ter2@github.com:o/r.git") == "a password in the URL's authority"
