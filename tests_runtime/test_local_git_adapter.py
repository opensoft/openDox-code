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
