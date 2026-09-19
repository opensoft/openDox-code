"""FLOOR PART 3's openDox side: the declared factory and the transposition.

`split-opendox-two-layer-product` § 3.7 wants openDox to PASS the neutral
conformance corpus openxFactory ships, and RULED Q-F1 (a) lets this leg get
there by TRANSPOSING that corpus into git — "documents, keys and bytes
unchanged". The pass itself is recorded by running openxFactory's runner, which
needs openxFactory's checkout and its fixtures and therefore cannot run here.

SO THIS SUITE PROVES THE PROPERTY THE RUNNER CHECKS, NOT THE RUN. The runner's
fidelity proof compares a `{key: sha256(bytes)}` table computed off the SHIPPED
FILES against what this reader SERVES; everything here holds `transpose` and
`reader` to that same comparison over a corpus built in a tmpdir with the
shipped one's shape. A suite that instead asserted "we called git" would pass
while the transposition quietly dropped a document.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opendox.corpus_adapter import (  # noqa: E402
    CORPUS_ABSENT, CORPUS_UNREADABLE, CorpusAdapter, CorpusRef, CorpusRefused,
    SCOPE_ALL,
)
from opendox.conformance_corpus import (  # noqa: E402
    EMPTY, POPULATED, UNREADABLE, NEUTRAL_KIND_FIELD, NEUTRAL_REQUIRED_FIELDS,
    reader, transpose,
)

#: The shipped corpus's own shape and its own two-field header vocabulary, in
#: the spelling openxFactory's seed uses. Rebuilt here rather than imported
#: because openxFactory is not a dependency of this leg and must not become
#: one to satisfy a test.
_DOCUMENTS = {
    "notes/alpha.md": b"Type: note\nTitle: Alpha\n\n# Alpha\n\nA complete document.\n",
    "notes/beta.md": b"Type: note\nTitle: Beta\n\n# Beta\n\nAnother one.\n",
    "papers/gamma.md": b"Type: paper\nTitle: Gamma\n\n# Gamma\n\nIn the second root.\n",
}


def _git_available() -> bool:
    try:
        subprocess.run(("git", "--version"), check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


requires_git = pytest.mark.skipif(not _git_available(), reason="git absent")


@pytest.fixture
def shipped(tmp_path: Path) -> Path:
    """A stand-in for openxFactory's `tests/corpus-adapter/fixtures`."""
    fixtures = tmp_path / "fixtures"
    for key, body in _DOCUMENTS.items():
        laid = fixtures / POPULATED / key
        laid.parent.mkdir(parents=True, exist_ok=True)
        laid.write_bytes(body)
    (fixtures / EMPTY / "notes").mkdir(parents=True)
    (fixtures / UNREADABLE).write_text("not a directory\n", encoding="utf-8")
    return fixtures


def _fingerprint(populated: Path) -> dict[str, str]:
    """The runner's own table: `{key: sha256(bytes)}` off the FILES.

    Deliberately the same rule the runner applies — every file under the
    populated state counts, and no reader is involved on this side.
    """
    return {path.relative_to(populated).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(populated.rglob("*")) if path.is_file()}


def test_the_factory_builds_a_reader_that_satisfies_the_interface() -> None:
    built = reader("populated", "/anywhere")
    assert isinstance(built, CorpusAdapter)


def test_the_factory_declares_no_write_path_and_the_corpus_vocabulary() -> None:
    """`read-only-declared-at-resolution` is decided here, before any corpus.

    openDox's own reader declares openDox's governed write path; this corpus
    declares none, and the check's own words for a reader that brings one
    anyway are "a reader is inventing one".
    """
    built = reader("populated", "/anywhere")
    assert built._write_path is None
    assert built._kind_field == NEUTRAL_KIND_FIELD
    assert built._required_fields == NEUTRAL_REQUIRED_FIELDS


@requires_git
def test_the_transposition_carries_every_key_and_byte(
        shipped: Path, tmp_path: Path) -> None:
    """The runner's asymmetric comparison, reproduced: files in, reader out."""
    built = transpose(shipped, tmp_path / "transposition")
    corpus = reader("populated", str(built / POPULATED)).resolve(
        CorpusRef(name="populated", location=str(built / POPULATED)))
    served = reader("populated", str(built / POPULATED))
    listed = tuple(served.list_documents(corpus))
    reference = _fingerprint(shipped / POPULATED)
    assert sorted(d.key for d in listed) == sorted(reference)
    for document_id in listed:
        # `read` returns `Document.content` as BYTES, and the comparison is
        # taken on those bytes rather than on any decoded form: a
        # transposition that re-encoded a document would round-trip through
        # `str` and compare equal while the bytes on disk had changed.
        document = served.read(corpus, document_id)
        assert isinstance(document.content, bytes)
        assert hashlib.sha256(document.content).hexdigest() \
            == reference[document_id.key], f"bytes differ at {document_id.key}"


@requires_git
def test_the_transposition_adds_no_document_of_its_own(
        shipped: Path, tmp_path: Path) -> None:
    """A `.gitkeep` or a README laid down here would be a key nobody shipped."""
    built = transpose(shipped, tmp_path / "transposition")
    tracked = subprocess.run(
        ("git", "ls-files"), cwd=built / POPULATED,
        check=True, capture_output=True, text=True).stdout.split()
    assert sorted(tracked) == sorted(_DOCUMENTS)


@requires_git
def test_the_empty_state_is_an_answer_and_not_a_refusal(
        shipped: Path, tmp_path: Path) -> None:
    """`empty-is-an-answer`: an empty corpus and an unreadable one differ."""
    built = transpose(shipped, tmp_path / "transposition")
    location = str(built / EMPTY)
    empty = reader("empty", location)
    corpus = empty.resolve(CorpusRef(name="empty", location=location))
    assert empty.list_documents(corpus, SCOPE_ALL) == ()


@requires_git
def test_the_non_directory_state_refuses_as_unreadable(
        shipped: Path, tmp_path: Path) -> None:
    built = transpose(shipped, tmp_path / "transposition")
    location = str(built / UNREADABLE)
    with pytest.raises(CorpusRefused) as caught:
        reader("unreadable", location).resolve(
            CorpusRef(name="unreadable", location=location))
    assert caught.value.refusal.kind == CORPUS_UNREADABLE


@requires_git
def test_the_absent_state_is_the_one_that_is_not_built(
        shipped: Path, tmp_path: Path) -> None:
    """Built by NOT creating it, which is the only honest way to build it."""
    built = transpose(shipped, tmp_path / "transposition")
    location = str(built / "no-corpus-was-ever-placed-here")
    assert not Path(location).exists()
    with pytest.raises(CorpusRefused) as caught:
        reader("absent", location).resolve(
            CorpusRef(name="absent", location=location))
    assert caught.value.refusal.kind == CORPUS_ABSENT


def test_transpose_refuses_a_shipped_root_with_no_populated_state(
        tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        transpose(tmp_path / "nothing-here", tmp_path / "out")


# ---------------------------------------------------------------------------
# THE AMBIENT MACHINE, which is the half a transposition cannot see going
# wrong. Both cases below are Copilot's findings on PR #31, turned into
# runnable ones: each sets a real hostile value in the environment this
# function actually reads, and asserts the bytes and the repository survive it.


@requires_git
def test_an_ambient_GIT_DIR_does_not_redirect_the_transposition(
        shipped: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`GIT_DIR` OUTRANKS `cwd`, so an unsanitized helper builds elsewhere.

    A CI job running inside another checkout, a git hook, an alias — all set
    it, and all are ordinary places for this to run.
    """
    decoy = tmp_path / "decoy.git"
    subprocess.run(("git", "init", "-q", "--bare", str(decoy)),
                   check=True, capture_output=True)
    monkeypatch.setenv("GIT_DIR", str(decoy))
    built = transpose(shipped, tmp_path / "transposition")

    # THE VERIFICATION HAS TO DROP `GIT_DIR` TOO, and the first version of
    # this test did not — it ran `git ls-files` with the decoy still in the
    # environment, read the decoy, and failed. That failure is the hazard
    # demonstrating itself: an unsanitized git in this file was redirected by
    # exactly the variable the code under test now strips, which is a better
    # argument for the fix than the assertion was.
    clean = {name: value for name, value in os.environ.items()
             if name != "GIT_DIR"}
    tracked = subprocess.run(
        ("git", "ls-files"), cwd=built / POPULATED, env=clean,
        check=True, capture_output=True, text=True).stdout.split()
    assert sorted(tracked) == sorted(_DOCUMENTS)
    # AND THE DECOY IS UNTOUCHED — the transposition went where it said.
    decoy_log = subprocess.run(
        ("git", "--git-dir", str(decoy), "log", "--oneline"),
        env=clean, capture_output=True, text=True)
    assert decoy_log.stdout.strip() == ""


@requires_git
def test_ambient_EOL_normalization_cannot_change_the_committed_bytes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`core.autocrlf=input` rewrites CRLF on the way INTO the object store.

    A document with CRLF in it is the case that catches it: `copyfile` is
    byte-for-byte and the commit is not, so the promise breaks between them
    and only a check on the COMMITTED blob sees it.
    """
    fixtures = tmp_path / "fixtures"
    crlf = b"Type: note\r\nTitle: Windows\r\n\r\n# Windows\r\n\r\nCRLF, deliberately.\r\n"
    (fixtures / POPULATED / "notes").mkdir(parents=True)
    (fixtures / POPULATED / "notes" / "crlf.md").write_bytes(crlf)
    (fixtures / EMPTY).mkdir(parents=True)
    (fixtures / UNREADABLE).write_text("not a directory\n", encoding="utf-8")

    hostile = tmp_path / "hostile.gitconfig"
    hostile.write_text("[core]\n\tautocrlf = input\n\tsafecrlf = false\n",
                       encoding="utf-8")
    # `GIT_CONFIG_GLOBAL` is deliberately NOT stripped by the runtime's
    # sanitizer — it names the operator's own configuration — so it is a LIVE
    # channel here and the right one to test with.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))

    built = transpose(fixtures, tmp_path / "transposition")
    blob = subprocess.run(
        ("git", "cat-file", "blob", "HEAD:notes/crlf.md"),
        cwd=built / POPULATED, check=True, capture_output=True).stdout
    assert blob == crlf, "the committed blob is not the file's bytes"
