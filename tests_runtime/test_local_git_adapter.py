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


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


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
    # (Copilot review of openDox-code#26, round 5). `names_a_secret_parameter`
    # is the question, and this asserts the importing half asks that one.
    assert (repository_act.names_a_secret_parameter
            is lga.names_a_secret_parameter)
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
    assert set(parameters) == {"self", "executable"}


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
    commit = repository_act.initialize_repository(
        location, project_id="project-raced", actor=ACTOR)

    moved = _swap_then_initialize.moved
    assert (moved / "HEAD").is_file(), (
        "the history was not written into the directory this act verified")
    assert _git(moved, "rev-parse", "HEAD") == commit
    assert not any(decoy.iterdir()), (
        f"git wrote into the swapped-in path: {sorted(decoy.iterdir())}")
