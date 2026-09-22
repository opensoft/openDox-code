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
#: THE SHIPPED SEED'S OWN BYTES, and that is the point of this block rather
#: than a convenience. The first cut gave all three documents BOTH header
#: fields, and the real seed does not: `notes/beta.md` carries no `Title` and
#: `papers/gamma.md` carries no `Type`, which are the classification
#: vocabulary's missing-field and unclassifiable cases — the awkward parts the
#: seventeen checks exist for. A fixture derived from simplified values, with a
#: `_fingerprint` derived from the same values, proves byte fidelity over a
#: corpus shaped like the seed and never over the seed (Copilot review of
#: PR #31 at `tests/test_conformance_corpus.py:45`, measured and registered by
#: the lander in comment 5738108117, taken here).
#:
#: COPIED AND NOT IMPORTED, which is the constraint: openxFactory is not a
#: dependency of this leg and must not become one to satisfy a test. The bytes
#: below are `tests/corpus-adapter/fixtures/neutral/**` verbatim — 165, 171 and
#: 175 bytes, the sizes the lander measured — so the fixture is the seed rather
#: than a description of it.
_DOCUMENTS = {
    "notes/alpha.md": (
        b"Type: note\nTitle: Alpha\n\n# Alpha\n\nA complete document in a "
        b"corpus that has never heard of a factory. It carries\nthis corpus's "
        b"own two-field header and nothing else.\n"),
    "notes/beta.md": (
        b"Type: note\n\n# Beta\n\nA classified document that is missing one "
        b"of the fields its kind obliges, so\nthe reader has something to "
        b"report without anything being unrecognizable.\n"),
    "papers/gamma.md": (
        b"Title: Gamma\n\n# Gamma\n\nA document this corpus cannot classify: "
        b"it carries no kind header at all. It\nmust still be LISTED, and "
        b"classifying it must name it rather than omit it.\n"),
}

#: The sizes the shipped seed has, asserted rather than trusted: a fixture that
#: drifts from the corpus it mirrors is the defect this block closes, and the
#: byte count is the cheapest thing that would notice.
_SHIPPED_SIZES = {"notes/alpha.md": 165, "notes/beta.md": 171,
                  "papers/gamma.md": 175}

#: AND THE DIGESTS, because a length is not an identity. `_SHIPPED_SIZES` plus
#: the header-shape assertions let any SAME-LENGTH substitution inside a body
#: through, and `_DOCUMENTS` is also what `shipped` is built from and what
#: `_fingerprint` is computed over — so a drifted fixture would agree with
#: itself all the way down and the suite would still be green (Copilot review
#: of PR #33 at `tests/test_conformance_corpus.py:77`).
#:
#: These three are sha256 of `tests/corpus-adapter/fixtures/neutral/**` in
#: openxFactory, measured against the files on disk at
#: `openxFactory-worktrees/pin-f5a41d18`. Recording them here is the only way
#: to detect drift WITHOUT making openxFactory a dependency of this leg, which
#: is the constraint that produced the copied bytes in the first place: the
#: seed is not reachable from this repository, so the digest has to be.
_SHIPPED_DIGESTS = {
    "notes/alpha.md":
        "5a8c06574b3240ad38f2a7b861d5fa1b15572f36adf261701facff55cbbc24ff",
    "notes/beta.md":
        "971e78fb9fda1fe75012b455fe209344b8adb144169d7af15905712c2a00737b",
    "papers/gamma.md":
        "0473352024f384327694dc19cae4d465f8ddbeb50c1781e655cec72f99951e31",
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


@requires_git
def test_a_hostile_init_template_cannot_rewrite_the_committed_bytes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`init.templateDir` is the channel that survives the other defences.

    `git init` copies the template into the new `$GIT_DIR`, and a template
    carrying `info/attributes` installs REPOSITORY-LOCAL attributes that
    `core.attributesFile` does not override. Measured before the fix: a
    template saying `* filter=evil` plus a global `filter.evil.clean` rewrote
    a document's bytes straight through `core.attributesFile=/dev/null`.
    """
    template = tmp_path / "template" / "info"
    template.mkdir(parents=True)
    (template / "attributes").write_text("* filter=evil\n", encoding="utf-8")
    hostile = tmp_path / "hostile.gitconfig"
    hostile.write_text(
        f"[init]\n\ttemplateDir = {template.parent}\n"
        '[filter "evil"]\n\tclean = sed s/Alpha/TAMPERED/\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))

    fixtures = tmp_path / "fixtures"
    body = b"Type: note\nTitle: Alpha\n\n# Alpha\n\nThe word Alpha must survive.\n"
    (fixtures / POPULATED / "notes").mkdir(parents=True)
    (fixtures / POPULATED / "notes" / "alpha.md").write_bytes(body)
    (fixtures / EMPTY).mkdir(parents=True)
    (fixtures / UNREADABLE).write_text("not a directory\n", encoding="utf-8")

    built = transpose(fixtures, tmp_path / "transposition")
    blob = subprocess.run(
        ("git", "cat-file", "blob", "HEAD:notes/alpha.md"),
        cwd=built / POPULATED, check=True, capture_output=True).stdout
    assert blob == body


# -- the residue openDox-code#31 registered ----------------------------------


def test_the_fixture_is_the_shipped_seed_and_not_a_description_of_it(
) -> None:
    """A fixture derived from simplified values proves nothing about the seed.

    NOT MARKED `@requires_git`, and that is the fix rather than an oversight:
    every assertion below is `hashlib.sha256` over the module-level
    `_DOCUMENTS`/`_SHIPPED_SIZES`/`_SHIPPED_DIGESTS` dicts, and none of it
    shells out to git. The marker sat on this test anyway, which drops the
    digest guard — the one check standing between this whole file and a
    fixture that has quietly drifted from the seed it claims to mirror — on
    any runner without git, and moves `EXPECT_SKIPPED` there for a reason
    that is not this test's own. Removing it does not move the pinned triple
    on a runner that HAS git (this one always has, so the skipif condition
    was already false and the test already ran) — it only makes the skip
    count honest on one that does not.

    The first cut gave all three documents BOTH header fields and computed the
    fidelity table off those same values, so the suite proved byte fidelity
    over a corpus SHAPED LIKE the seed and never over the seed — and the seed's
    awkward parts are exactly what the seventeen checks are for (Copilot review
    of PR #31, measured and registered in comment 5738108117).

    THE BYTES ARE COPIED, NOT IMPORTED, because openxFactory is not a
    dependency of this leg and must not become one to satisfy a test. What is
    asserted here without that dependency is the seed's own sha256 PER KEY,
    recorded in `_SHIPPED_DIGESTS` — a length and a header shape let a
    same-length substitution through, and `_DOCUMENTS` is also what `shipped`
    and `_fingerprint` are built from, so a drifted fixture agrees with itself
    everywhere else in this file (Copilot review of PR #33). The sizes stay
    beside the digests: when a digest fails, the size says whether the drift
    was an edit or a replacement.
    """
    assert set(_DOCUMENTS) == set(_SHIPPED_SIZES) == set(_SHIPPED_DIGESTS)
    for key, digest in _SHIPPED_DIGESTS.items():
        served = hashlib.sha256(_DOCUMENTS[key]).hexdigest()
        assert served == digest, (
            f"{key} hashes {served} and the shipped seed hashes {digest}; "
            f"this fixture has drifted from the corpus it mirrors, and every "
            f"other assertion in this file would follow it")
    for key, size in _SHIPPED_SIZES.items():
        assert len(_DOCUMENTS[key]) == size, (
            f"{key} is {len(_DOCUMENTS[key])} bytes and the shipped seed is "
            f"{size}; this fixture has drifted from the corpus it mirrors")

    def _header(body: bytes) -> set[str]:
        fields = set()
        for line in body.split(b"\n\n", 1)[0].splitlines():
            name, sep, _ = line.partition(b":")
            if sep:
                fields.add(name.decode())
        return fields

    assert _header(_DOCUMENTS["notes/alpha.md"]) == {"Type", "Title"}
    assert _header(_DOCUMENTS["notes/beta.md"]) == {"Type"}, (
        "beta is the MISSING-FIELD case: classified, and short one field its "
        "kind obliges")
    assert _header(_DOCUMENTS["papers/gamma.md"]) == {"Title"}, (
        "gamma is the UNCLASSIFIABLE case: no kind header at all")


@requires_git
def test_the_seed_s_awkward_documents_are_reported_and_never_omitted(
        shipped: Path, tmp_path: Path) -> None:
    """The two cases the simplified fixture could not exercise.

    `classify` "never omits": a document whose kind this vocabulary does not
    recognize comes back with `kind=None` and a reason NAMING it, and it still
    appears in `list_documents`. A corpus that quietly dropped its
    unclassifiable document would pass a suite whose fixture has none.
    """
    built = transpose(shipped, tmp_path / "transposition")
    served = reader("populated", str(built / POPULATED))
    corpus = served.resolve(CorpusRef(name="populated",
                                      location=str(built / POPULATED)))
    listed = {d.key: d for d in served.list_documents(corpus)}
    assert set(listed) == set(_DOCUMENTS), "every document is listed, all three"

    complete = served.classify(corpus, listed["notes/alpha.md"])
    assert complete.kind == "note"
    assert complete.missing_fields == ()
    assert complete.unclassifiable is None

    # THE MISSING-FIELD CASE: classified, and short one field its kind obliges.
    short = served.classify(corpus, listed["notes/beta.md"])
    assert short.kind == "note"
    assert short.required_fields == NEUTRAL_REQUIRED_FIELDS
    assert short.missing_fields == ("Title",)
    assert short.unclassifiable is None, (
        "a document missing a field is still classified; only a missing KIND "
        "makes it unclassifiable")

    # THE UNCLASSIFIABLE CASE: no kind header at all, reported by name.
    unknown = served.classify(corpus, listed["papers/gamma.md"])
    assert unknown.kind is None
    assert unknown.unclassifiable, "the reason is the whole obligation here"
    assert "papers/gamma.md" in unknown.unclassifiable, (
        "the reason must NAME the document, so a human can go look at it")
    # AND IT IS STILL SERVED, byte for byte, which is what "never omits" costs
    # if it is not true.
    assert served.read(corpus, listed["papers/gamma.md"]).content == \
        _DOCUMENTS["papers/gamma.md"]


@requires_git
def test_a_global_excludes_file_cannot_take_documents_out_of_the_corpus(
        shipped: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fourth channel, in both of its shapes.

    `GIT_CONFIG_GLOBAL` is retained deliberately — it names the operator's own
    git — so a global `core.excludesFile` reached the `git add`. MEASURED at
    `776d2a80`, both shapes failed CLOSED and both failed UNHELPFULLY: a
    `*.md` excludes file staged nothing, so `commit` exited non-zero and a
    `CalledProcessError` came out; an excludes file naming only `beta.md` let
    the commit succeed with a SHORT TREE and the byte read-back then died on
    `cat-file`, again as a `CalledProcessError` (Copilot review of PR #31,
    registered by the lander in its comment on `conformance_corpus.py:107`).

    BOTH SHAPES ARE DRIVEN THROUGH THE REAL HOSTILE CONFIGURATION, and both
    must now TRANSPOSE — the channel is closed, not reported. The refusal text
    is asserted separately below, with the switch taken away, because a
    sentence nobody can reach is a sentence nobody has read.
    """
    for rule in ("*.md", "beta.md"):
        hostile = tmp_path / f"excludes-{rule.replace('*', 'star')}"
        hostile.write_text(rule + "\n", encoding="utf-8")
        config = tmp_path / f"gitconfig-{rule.replace('*', 'star')}"
        config.write_text(
            f"[core]\n\texcludesFile = {hostile}\n", encoding="utf-8")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

        built = transpose(shipped, tmp_path / f"transposition-{rule}")
        served = reader("populated", str(built / POPULATED))
        corpus = served.resolve(CorpusRef(name="populated",
                                          location=str(built / POPULATED)))
        listed = {d.key for d in served.list_documents(corpus)}
        assert listed == set(_DOCUMENTS), (
            f"a global excludes file of {rule!r} took documents out of the "
            f"transposition: {sorted(set(_DOCUMENTS) - listed)}")
        reference = _fingerprint(shipped / POPULATED)
        for document_id in served.list_documents(corpus):
            assert hashlib.sha256(
                served.read(corpus, document_id).content).hexdigest() \
                == reference[document_id.key]


@requires_git
def test_an_exclusion_this_act_cannot_reach_is_named_and_not_a_git_error(
        shipped: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """And if some entrance nobody thought of opens, a sentence comes out.

    The switch and `--force` close the two shapes above, and the refusal they
    leave behind has to be readable anyway: an exclusion is a property of the
    MACHINE, so the reader who meets it is the one who can fix it, and an exit
    status tells them nothing. Both shapes are driven with the switch taken
    out of `_HARDENING`, which is the only honest way to reach the text — it
    is what the code did at `776d2a80` and what it would do again if the
    switch were dropped.
    """
    import opendox.conformance_corpus as module

    without = tuple(part for index, part in enumerate(module._HARDENING)
                    if part != "core.excludesFile=" + os.devnull
                    and not (part == "-c"
                             and module._HARDENING[index + 1]
                             == "core.excludesFile=" + os.devnull))
    assert len(without) == len(module._HARDENING) - 2, "the switch is there"
    monkeypatch.setattr(module, "_HARDENING", without)

    for rule, expected in (("*.md", "staged NOTHING"),
                           ("beta.md", "does not hold 'notes/beta.md'")):
        hostile = tmp_path / f"ex-{rule.replace('*', 'star')}"
        hostile.write_text(rule + "\n", encoding="utf-8")
        config = tmp_path / f"cfg-{rule.replace('*', 'star')}"
        config.write_text(
            f"[core]\n\texcludesFile = {hostile}\n", encoding="utf-8")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))

        # `--force` ALSO HAS TO GO for the total shape, because forcing the add
        # defeats the excludes file on its own: what is being measured here is
        # the SENTENCE, and reaching it means removing both halves of the
        # repair rather than only the one the comment names.
        real_git = module._git

        def _unforced(repo, *args, _real=real_git):
            return _real(repo, *(a for a in args if a != "--force"))

        monkeypatch.setattr(module, "_git", _unforced)
        with pytest.raises(ValueError) as refused:
            transpose(shipped, tmp_path / f"raw-{rule.replace('*', 'star')}")
        monkeypatch.setattr(module, "_git", real_git)
        assert expected in str(refused.value), str(refused.value)
        # A SENTENCE AND NOT AN EXIT STATUS: the class name of the underlying
        # failure is chained for a debugger, and the message is what a reader
        # meets.
        assert isinstance(refused.value.__cause__, subprocess.CalledProcessError)
        assert "ignore rule" in str(refused.value)
        # AND GIT'S OWN WORDS ARE IN IT, which is the half a chained exception
        # does not carry: `CalledProcessError.__str__` is `Command … returned
        # non-zero exit status N` and the captured streams are dropped.
        assert "git said" in str(refused.value)
        assert "nothing at all" not in str(refused.value), (
            "git was quoted as having said nothing — the total shape writes "
            "its sentence to STDOUT, so a refusal that reads only stderr "
            "quotes an empty string in exactly this case")


@requires_git
def test_a_magic_looking_key_is_named_absent_and_not_a_repository_problem(
        shipped: Path, tmp_path: Path) -> None:
    """A key that merely LOOKS like pathspec magic is not a repository fault.

    `git ls-tree` parses a leading `:` as PATHSPEC MAGIC before it ever asks
    the tree: MEASURED on git 2.43.0, a probe of `':!doomed.md'` exits 128
    with `pathspec magic not supported by this command: 'exclude'`, for a key
    that is otherwise ordinary and simply was never committed — `cat-file`
    fails it exactly like any absent key (`does not exist in 'HEAD'`).
    WITHOUT `--literal-pathspecs` on the probe, that 128 reads as "HEAD or
    the repository itself is the problem" (Copilot review of PR #33, comment
    5738611955, finding F6); the transposition below is real and undamaged,
    so a key merely SHAPED like magic must still be named an ordinary absent
    document, the same as any other key nobody committed.
    """
    import opendox.conformance_corpus as module

    built = transpose(shipped, tmp_path / "transposition")
    target = built / POPULATED
    key = ":!doomed.md"

    with pytest.raises(ValueError) as refused:
        module._committed_blob(target, key)

    said = str(refused.value)
    assert f"does not hold {key!r} at all" in said, said
    assert "ignore rule" in said, said
    assert "cannot even ask its tree" not in said, (
        "a magic-looking key was reported as a repository/HEAD problem "
        f"instead of an ordinary absent document: {said}")


@requires_git
def test_a_blob_git_holds_but_cannot_read_is_not_named_an_exclusion(
        shipped: Path, tmp_path: Path) -> None:
    """The other way `cat-file` fails, and it is not the corpus's fault.

    `cat-file blob HEAD:<key>` exits non-zero for a key that was never
    committed AND for a key whose object the database can no longer produce,
    and the first cut of the translation told both operators that an ignore
    rule was the usual cause — a diagnosis of something that did not happen,
    on a machine whose real problem is a damaged repository (Copilot review of
    PR #33).

    THE SHAPE IS BUILT, not simulated: a real transposition, and then the
    loose object behind one document is removed. `ls-tree` still lists the key
    — it reads the TREE — which is exactly the discrimination the repair makes
    (MEASURED on git 2.43.0: `fatal: git cat-file HEAD:notes/beta.md: bad
    file`, with `ls-tree` rc 0 naming the path).
    """
    import opendox.conformance_corpus as module

    built = transpose(shipped, tmp_path / "transposition")
    target = built / POPULATED
    key = "notes/beta.md"
    oid = subprocess.run(("git", "rev-parse", f"HEAD:{key}"), cwd=target,
                         check=True, capture_output=True,
                         text=True).stdout.strip()
    loose = target / ".git" / "objects" / oid[:2] / oid[2:]
    assert loose.is_file(), "the object is loose in a one-commit repository"
    loose.unlink()

    with pytest.raises(ValueError) as refused:
        module._committed_blob(target, key)

    said = str(refused.value)
    assert "NOT an exclusion" in said, said
    assert key in said
    assert "ignore rule" not in said, (
        "an unreadable object is not an exclusion, and saying so sends the "
        "reader looking for a `.gitignore` that does not exist")
    assert "git said" in said and "bad file" in said, (
        "git named the real failure and the refusal must carry it: "
        f"{said}")
    assert isinstance(refused.value.__cause__, subprocess.CalledProcessError)


@requires_git
def test_a_commit_failure_that_is_not_an_exclusion_is_not_reported_as_one(
        shipped: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A held `index.lock`: a real commit failure with the index full.

    The first cut answered EVERY `git commit` failure with "every file copied
    into it was excluded" — an absolute, and false for a full disk, an
    unwritable object database, or a lock left behind by a crashed process
    (Copilot review of PR #33). This drives the last of those, because it is
    the one shape a test can create on any platform and as any user: the
    others need a full filesystem or a permission this process can hold.

    THE LOCK IS REAL AND SO IS THE FAILURE — git refuses on its own
    bookkeeping (MEASURED: exit 128, `fatal: Unable to create '…index.lock':
    File exists.` on STDERR), and `git diff --cached --name-only` still lists
    the three staged paths, which is what the repair reads.
    """
    import opendox.conformance_corpus as module

    real_git = module._git

    def _locked(repo: Path, *args: str, _real=real_git) -> None:
        if args[:1] == ("commit",) and repo.name == POPULATED:
            (repo / ".git" / "index.lock").write_bytes(b"")
        return _real(repo, *args)

    monkeypatch.setattr(module, "_git", _locked)
    with pytest.raises(ValueError) as refused:
        transpose(shipped, tmp_path / "transposition")

    said = str(refused.value)
    assert "NOT an exclusion" in said, said
    assert "3 path(s) are staged" in said, (
        "the index is what rules the exclusion out, and the count is the "
        f"evidence a reader can check: {said}")
    assert "no space left on the device" in said and "permission" in said, (
        f"the causes are enumerated rather than asserted: {said}")
    assert "index.lock" in said, (
        f"git named the real failure and the refusal must carry it: {said}")
    assert isinstance(refused.value.__cause__, subprocess.CalledProcessError)


@requires_git
def test_a_populated_state_with_no_files_says_the_index_was_empty(
        tmp_path: Path) -> None:
    """The other side of the same fork, reached without breaking anything.

    A shipped root whose populated state is a directory with nothing in it is
    a malformed corpus, and it is the one way to reach the nothing-staged
    branch now that the switch and `--force` close the ignore-rule routes. The
    refusal must say the index was empty — and it must NOT be the sentence the
    case above gets, which is the whole point of reading `diff --cached`
    (MEASURED: exit 1, `nothing to commit …` on STDOUT with stderr EMPTY).
    """
    shipped = tmp_path / "fixtures"
    (shipped / POPULATED).mkdir(parents=True)

    with pytest.raises(ValueError) as refused:
        transpose(shipped, tmp_path / "transposition")

    said = str(refused.value)
    assert "staged NOTHING" in said, said
    assert "a populated state with no files in it" in said, said
    assert "nothing to commit" in said, (
        "the total shape writes its sentence to STDOUT, so a refusal reading "
        f"only stderr would quote an empty string here: {said}")
    assert isinstance(refused.value.__cause__, subprocess.CalledProcessError)
# -- the residue openDox-code#33 registered (F5) -----------------------------
#
# `--force`'s SUCCESS PATH was asserted NOWHERE: every exclusion case above
# reaches a CONFIGURED ignore file through `GIT_CONFIG_GLOBAL`, which is what
# `core.excludesFile=` disables — none of them ever lays a `.gitignore` down
# INSIDE the populated state, or writes to `$GIT_DIR/info/exclude`, which are
# the two entrances `--force` exists for (Copilot review of PR #33, comment
# 5738550542, finding F5). Commit `521abb7c`'s own message additionally
# MISDESCRIBED `test_an_exclusion_this_act_cannot_reach_is_named_and_not_a_git_error`
# above as driving `$GIT_DIR/info/exclude` — it does not: both its cases are
# the same `GIT_CONFIG_GLOBAL` excludes file as the test before it, with the
# switch and `--force` monkeypatched out. That commit is already pushed and
# its message cannot be corrected; the two cases below are the ones that were
# actually missing, and this comment is the correction.


@requires_git
def test_a_gitignore_copied_in_with_the_corpus_does_not_shrink_it(
        shipped: Path, tmp_path: Path) -> None:
    """`--force`'s OWN entrance: a `.gitignore` the corpus carries in itself.

    The shipped corpus is arbitrary files, and one of them may be exactly
    this — nothing upstream of `transpose` promises otherwise. `core.
    excludesFile=` disables the OPERATOR's ignore file and says nothing about
    one the corpus brought with it; `--force` is what still adds it. This is
    driven as a real `.gitignore` on disk, inside `shipped / POPULATED`
    itself, rather than through `GIT_CONFIG_GLOBAL` — the channel none of the
    cases above exercise.
    """
    (shipped / POPULATED / ".gitignore").write_text("*.md\n", encoding="utf-8")
    built = transpose(shipped, tmp_path / "transposition")
    served = reader("populated", str(built / POPULATED))
    corpus = served.resolve(CorpusRef(name="populated",
                                      location=str(built / POPULATED)))
    listed = tuple(served.list_documents(corpus))
    reference = _fingerprint(shipped / POPULATED)
    assert sorted(d.key for d in listed) == sorted(reference), (
        "a .gitignore copied in with the corpus took documents out of the "
        f"transposition: {sorted(set(reference) - {d.key for d in listed})}")
    for document_id in listed:
        document = served.read(corpus, document_id)
        assert hashlib.sha256(document.content).hexdigest() \
            == reference[document_id.key], f"bytes differ at {document_id.key}"


@requires_git
def test_an_info_exclude_written_after_init_does_not_shrink_the_corpus(
        shipped: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--force`'s OTHER entrance: `$GIT_DIR/info/exclude`.

    No corpus file and no `GIT_CONFIG_GLOBAL` reaches this one — it lives
    inside the repository `transpose` itself just created, so it is written
    straight there, right after `init` and before `add`, which is exactly
    where a real one would appear (a template, a hook, an operator poking the
    fresh `.git` between the two calls this function makes back to back).
    Driven with `_git` monkeypatched to seed it at that exact point, on the
    populated repository only — the empty state's `.git` gets one too and it
    is inert there, since nothing is ever added to it.
    """
    import opendox.conformance_corpus as module

    real_git = module._git

    def _seeded(repo: Path, *args: str, _real=real_git) -> None:
        _real(repo, *args)
        if args[:1] == ("init",) and repo.name == POPULATED:
            exclude = repo / ".git" / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text("*.md\n", encoding="utf-8")

    monkeypatch.setattr(module, "_git", _seeded)
    built = transpose(shipped, tmp_path / "transposition")
    served = reader("populated", str(built / POPULATED))
    corpus = served.resolve(CorpusRef(name="populated",
                                      location=str(built / POPULATED)))
    listed = tuple(served.list_documents(corpus))
    reference = _fingerprint(shipped / POPULATED)
    assert sorted(d.key for d in listed) == sorted(reference), (
        "an info/exclude written after init took documents out of the "
        f"transposition: {sorted(set(reference) - {d.key for d in listed})}")
    for document_id in listed:
        document = served.read(corpus, document_id)
        assert hashlib.sha256(document.content).hexdigest() \
            == reference[document_id.key], f"bytes differ at {document_id.key}"
