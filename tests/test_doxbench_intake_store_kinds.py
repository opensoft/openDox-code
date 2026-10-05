"""F1: a path in the declarations document's place that is no regular file
is UNREADABLE, not absent (Copilot r4184739661 on openxFactory#1236, rated
High; release 1's follow-on slice B, openxFactory#656 comment 6000630835).

THE DEFECT, at openDox-code `389e5a4a`. `DeclarationStore` asked
`doxbench_binding.document_present`, which answers false for anything but a
regular file, so a directory, a FIFO or a socket at
`ideation/dashboard/model-declarations.yaml` read as "no document": nothing
pending. A host whose policy is keyed on the pending set (openxFactory's
governed one, `scripts/opendox_host.py`'s `GovernedBindingTrust` at T094)
then trusted every binding of the served checkout, where a document that
cannot be read admits nothing.

THE FIX, in the store's read path (`DeclarationStore._open`): only "no such
file", or a file where a directory belongs on the way, is absence; anything
else in the document's place is refused by name with the refusal an
unreadable document gets, naming what it is. A link is judged as itself,
never by what it names, so a DANGLING LINK IS UNREADABLE, NOT ABSENT: the
path exists, and what it names cannot be read. That is the fail-closed
reading F1 asks for, and it is the reading the store's link rule (T100
follow-on, N1) already gives a link a clone carries. The read is judged on
what was opened, as `doxbench_trust.MachineTrust` reads its own store
(r4178064601): a look that never opens what is no regular file, an open
that waits on nothing and follows no link at the document's name, and the
descriptor's own type, so a FIFO is never opened and whatever replaces the
file after the look is refused for what it is.

Each case marked RED AT MAIN fails at `389e5a4a` (the evidence is in the
pull request). The others are controls, or pins of what the link rule
already refused.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import os
import socket
import stat
import threading
import time
from pathlib import Path

import pytest

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_intake as intake_mod
from opendox import doxbench_trust as trust_mod

BINDING_ID = "m1"

#: What each kind of path is called in the refusal, by the fix.
KIND_WORDS = {"directory": "a directory", "fifo": "a FIFO",
              "socket": "a socket"}


def _binding(binding_id: str = BINDING_ID):
    """A binding no broker answers, so only the policy decides its trust."""
    return binding_mod.ModelProviderBinding(
        id=binding_id, label="Model one", provider="anyone",
        credential_ref="env:F1_UNUSED_REFERENCE", auth_kind="api_key",
        approved_by="operator", dialect="openai-chat-v1",
        endpoint="http://127.0.0.1:9/v1/chat/completions", broker_argv=())


def _document(repo: Path) -> Path:
    document = intake_mod.declarations_path(repo)
    document.parent.mkdir(parents=True, exist_ok=True)
    return document


def _pending_document(repo: Path, binding_id: str = BINDING_ID) -> Path:
    """A regular declarations document declaring `binding_id` PENDING."""
    document = _document(repo)
    store = intake_mod.DeclarationStore(document)
    store.propose(intake_mod.ModelDeclaration(
        binding_id=binding_id, status=intake_mod.STATUS_PENDING,
        install_posture=intake_mod.POSTURE_SINGLE_OPERATOR,
        proposed_by="operator", proposed_at=intake_mod.stamp()))
    return document


def _refusal(document: Path, kind: str) -> str:
    """The refusal of `kind` in the document's place, in full: the words
    `doxbench_binding.cannot_read` gives a document that cannot be read."""
    return (f"the declarations document at {json.dumps(str(document))} "
            f"cannot be read ({kind}, not a regular file)")


def _answered(ask, *, fifo: Path | None = None) -> dict:
    """What `ask()` answered or raised, asked on a thread, so a store that
    waited on a FIFO fails the case rather than hang the suite (as
    `test_model_binding_trust.py`'s FIFO case asks)."""
    answers: dict = {}

    def run():
        try:
            answers["value"] = ask()
        except BaseException as error:  # noqa: BLE001 - the case reads it
            answers["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=20)
    if worker.is_alive():
        if fifo is not None and stat.S_ISFIFO(os.lstat(fifo).st_mode):
            # Release whatever the store left waiting on the FIFO, a reader
            # or a writer, so the case ends (Linux opens a FIFO for both).
            os.close(os.open(fifo, os.O_RDWR | os.O_NONBLOCK))
        worker.join(timeout=5)
        pytest.fail("the declarations store waited on a FIFO")
    return answers


class _GovernedPolicy:
    """openxFactory's governed policy, as a test-local stand-in
    (`scripts/opendox_host.py`'s `GovernedBindingTrust`, as T094 landed it
    in openxFactory `36908480`): the pending set of the served checkout's
    declarations document decides; a binding declared PENDING is refused,
    every other is trusted, and a document that cannot be read admits
    nothing, naming the store's refusal. It records nothing."""

    def verdict(self, binding, *, root):
        store = intake_mod.DeclarationStore(intake_mod.declarations_path(root))
        try:
            pending = store.pending_binding_ids()
        except intake_mod.IntakeRefused as refused:
            return trust_mod.TrustVerdict.untrusted_for(
                binding, root=root, basis=trust_mod.BASIS_HOST,
                reason=f"its declarations document cannot be read ({refused})")
        if binding.id in pending:
            return trust_mod.TrustVerdict.untrusted_for(
                binding, root=root, basis=trust_mod.BASIS_HOST,
                reason="its model declaration is pending")
        return trust_mod.TrustVerdict.trusted_for(
            binding, root=root, basis=trust_mod.BASIS_HOST)

    def record(self, binding, *, root):
        return None

    def intake_verdict(self, binding, *, root):
        return self.verdict(binding, root=root)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    return root


@pytest.fixture
def governed():
    trust_mod.unregister()
    policy = trust_mod.register(_GovernedPolicy())
    try:
        yield policy
    finally:
        trust_mod.unregister()


@pytest.fixture
def placed(repo, monkeypatch, request):
    """The declarations document's place holding `request.param`: a
    directory, a FIFO, or a listening socket (bound by its short relative
    name, since a socket's path is short)."""
    kind = request.param
    document = _document(repo)
    listening = None
    if kind == "directory":
        document.mkdir()
    elif kind == "fifo":
        os.mkfifo(document, 0o600)
    else:
        monkeypatch.chdir(document.parent)
        listening = socket.socket(socket.AF_UNIX)
        listening.bind(document.name)
    try:
        yield kind, document
    finally:
        if listening is not None:
            listening.close()


KINDS = sorted(KIND_WORDS)


# ===========================================================================
# 1. a directory, a FIFO or a socket in the document's place (RED AT MAIN)
# ===========================================================================


READS = {
    "pending_binding_ids": lambda store: store.pending_binding_ids(),
    "get": lambda store: store.get(BINDING_ID),
    "list": lambda store: store.list(),
    "broker": lambda store: store.broker(),
    "read_back": lambda store: store.read_back(),
}


@pytest.mark.parametrize("placed", KINDS, indirect=True)
@pytest.mark.parametrize("read", sorted(READS))
def test_F1_a_non_regular_path_is_refused_by_every_read(placed, read):
    """RED AT MAIN (each read answered as if no document were there). Each
    of the store's reads refuses it BY NAME, as `IntakeRefused`, in the
    words a document that cannot be read gets, naming what the path is; and
    nothing waits on a FIFO."""
    kind, document = placed
    store = intake_mod.DeclarationStore(document)
    answers = _answered(lambda: READS[read](store), fifo=document)
    assert "value" not in answers, (
        f"{read} read {KIND_WORDS[kind]} as no document: "
        f"{answers.get('value')!r}")
    assert isinstance(answers["error"], intake_mod.IntakeRefused), answers
    assert str(answers["error"]) == _refusal(document, KIND_WORDS[kind])


@pytest.mark.parametrize("placed", KINDS, indirect=True)
def test_F1_the_governed_hosts_policy_admits_nothing_over_it(
        placed, governed):
    """RED AT MAIN (the binding was trusted). The governed host's policy,
    asked for a binding's trust and for the console intake, admits nothing
    over a non-regular path, naming the store's refusal, as it admits
    nothing over a document that cannot be read."""
    kind, document = placed
    root = document.parent.parent.parent
    for ask in (trust_mod.verdict_for, trust_mod.intake_verdict_for):
        answers = _answered(lambda: ask(_binding(), root=root), fifo=document)
        verdict = answers["value"]
        assert not verdict.trusted, (ask.__name__, verdict)
        assert verdict.reason == (
            "its declarations document cannot be read "
            f"({_refusal(document, KIND_WORDS[kind])})"), verdict.reason


@pytest.mark.parametrize("placed", KINDS, indirect=True)
@pytest.mark.parametrize("act", ["propose", "declare_broker"])
def test_F1_no_write_lands_over_it(placed, act):
    """RED AT MAIN (a directory raised a raw `IsADirectoryError` from the
    write, and a FIFO or a socket was replaced by a new document). An
    intake's write reads first, so it is refused by name and nothing is
    written: the path is what it was."""
    kind, document = placed
    store = intake_mod.DeclarationStore(document)
    if act == "propose":
        write = lambda: store.propose(intake_mod.ModelDeclaration(  # noqa: E731
            binding_id=BINDING_ID, status=intake_mod.STATUS_PENDING,
            install_posture=intake_mod.POSTURE_SINGLE_OPERATOR,
            proposed_by="operator", proposed_at=intake_mod.stamp()))
    else:
        write = lambda: store.declare_broker(  # noqa: E731
            intake_mod.BrokerDeclaration(argv=("/opt/broker",)))
    answers = _answered(write, fifo=document)
    assert isinstance(answers.get("error"), intake_mod.IntakeRefused), answers
    assert str(answers["error"]) == _refusal(document, KIND_WORDS[kind])
    test = {"directory": stat.S_ISDIR, "fifo": stat.S_ISFIFO,
            "socket": stat.S_ISSOCK}[kind]
    assert test(os.lstat(document).st_mode)
    if kind == "directory":
        assert list(document.iterdir()) == []


def test_F1_a_fifo_in_the_documents_place_is_never_opened(repo):
    """RED AT MAIN (the FIFO read as no document). The look before the open
    refuses a FIFO without opening it, so a writer waiting on the FIFO is
    never let through: a reader's open would release it."""
    document = _document(repo)
    os.mkfifo(document, 0o600)
    released = threading.Event()

    def writer():
        os.close(os.open(document, os.O_WRONLY))   # waits for a reader
        released.set()

    waiting = threading.Thread(target=writer, daemon=True)
    waiting.start()
    time.sleep(0.5)                 # the writer is waiting in its open
    answers = _answered(
        lambda: intake_mod.DeclarationStore(document).pending_binding_ids(),
        fifo=document)
    opened = released.wait(timeout=1)
    if not opened:
        # Release the writer this case left waiting, so the case ends.
        os.close(os.open(document, os.O_RDONLY | os.O_NONBLOCK))
        waiting.join(timeout=5)
    assert not opened, "the declarations store opened the FIFO"
    assert str(answers["error"]) == _refusal(document, "a FIFO")


# ===========================================================================
# 2. a link: judged as itself, so a dangling one is unreadable, not absent
# ===========================================================================


@pytest.mark.parametrize("target", ["dangling", "a-directory", "a-fifo"])
def test_F1_a_link_in_the_documents_place_is_unreadable_not_absent(
        repo, governed, target):
    """A PIN, green at main too: the link rule (T100 follow-on, N1) refuses
    a link at the document's name before anything is read, whatever it
    names, a missing target included. The governed host's policy admits
    nothing over it."""
    document = _document(repo)
    elsewhere = repo.parent / "elsewhere"
    if target == "a-directory":
        elsewhere.mkdir()
    elif target == "a-fifo":
        os.mkfifo(elsewhere, 0o600)
    document.symlink_to(elsewhere)
    answers = _answered(
        lambda: intake_mod.DeclarationStore(document).pending_binding_ids(),
        fifo=elsewhere if target == "a-fifo" else None)
    assert isinstance(answers.get("error"), intake_mod.IntakeRefused), answers
    assert "symbolic link" in str(answers["error"])
    verdict = trust_mod.verdict_for(_binding(), root=repo)
    assert not verdict.trusted
    assert verdict.reason.startswith(
        "its declarations document cannot be read ("), verdict.reason


@pytest.mark.parametrize("target", ["dangling", "a-file-outside"])
def test_F1_a_link_that_appears_after_the_link_rule_looked_is_never_read(
        repo, monkeypatch, governed, target):
    """RED AT MAIN. A link put in the document's place after the link rule
    looked (a racing process) is still judged as itself by the read: a
    dangling one is unreadable, not absent, and one naming a file outside
    the repository is never read through. At main, the dangling one read as
    no document and its binding was trusted, and the outside file was read
    as the declarations."""
    document = _document(repo)
    outside = repo.parent / "outside.yaml"
    if target == "a-file-outside":
        _pending_document(repo.parent / "o")
        os.replace(intake_mod.declarations_path(repo.parent / "o"), outside)
    real = binding_mod.linked_component

    def look_then_link(path, relpath):
        found = real(path, relpath)         # nothing there yet: no link
        if Path(path) == document and not os.path.lexists(document):
            document.symlink_to(outside)    # a link appears after the look
        return found

    monkeypatch.setattr(binding_mod, "linked_component", look_then_link)
    with pytest.raises(intake_mod.IntakeRefused) as refused:
        intake_mod.DeclarationStore(document).pending_binding_ids()
    assert str(refused.value) == _refusal(document, "a symbolic link")
    document.unlink()               # the same race, asked by the host
    verdict = trust_mod.verdict_for(_binding("another"), root=repo)
    assert not verdict.trusted, verdict
    assert verdict.reason == (
        "its declarations document cannot be read "
        f"({_refusal(document, 'a symbolic link')})"), verdict.reason


# ===========================================================================
# 3. judged on what was opened: a file replaced after the look
# ===========================================================================


class _OsThatSwaps:
    """`os` as the declarations store sees it, whose look at the document
    (`lstat`) sees the regular file there and then replaces it (`swap`): what
    a racing process could do between the store's look and its open.
    Everything else is the real `os`."""

    def __init__(self, document: Path, swap) -> None:
        self.document = document
        self.swap = swap

    def lstat(self, path, *args, **kwargs):
        looked = os.lstat(path, *args, **kwargs)
        if Path(path) == self.document:
            self.swap(self.document)
        return looked

    def __getattr__(self, name):
        return getattr(os, name)


def _into_fifo(document: Path) -> None:
    document.unlink()
    os.mkfifo(document, 0o600)


def _into_directory(document: Path) -> None:
    document.unlink()
    document.mkdir()


SWAPS = {"fifo": (_into_fifo, "a FIFO"),
         "directory": (_into_directory, "a directory")}


@pytest.mark.parametrize("swap", sorted(SWAPS))
def test_F1_a_file_replaced_after_the_look_is_judged_by_its_descriptor(
        repo, monkeypatch, swap):
    """RED AT MAIN, where the store took no look of its own to race (it read
    the regular file). A regular document replaced by a FIFO or a directory
    between the store's look and its open is refused for what was opened,
    never read, and the open does not wait on the FIFO."""
    document = _pending_document(repo)
    into, words = SWAPS[swap]
    monkeypatch.setattr(intake_mod, "os", _OsThatSwaps(document, into),
                        raising=False)
    answers = _answered(
        lambda: intake_mod.DeclarationStore(document).pending_binding_ids(),
        fifo=document)
    assert "value" not in answers, answers
    assert str(answers["error"]) == _refusal(document, words)


def test_F1_a_file_replaced_by_a_link_after_the_look_is_never_read_through(
        repo, monkeypatch):
    """RED AT MAIN, as above. A regular document replaced by a link to a
    file outside the repository between the look and the open: the open
    follows no link at the document's name, so the outside file is never
    read as the declarations, and the read is refused by name."""
    document = _pending_document(repo)
    outside = _pending_document(repo.parent / "o", "outside-only")

    def into_link(path: Path) -> None:
        path.unlink()
        path.symlink_to(outside)

    monkeypatch.setattr(intake_mod, "os", _OsThatSwaps(document, into_link),
                        raising=False)
    with pytest.raises(intake_mod.IntakeRefused) as refused:
        intake_mod.DeclarationStore(document).pending_binding_ids()
    assert "cannot be read" in str(refused.value)


# ===========================================================================
# 4. controls: nothing there is still nothing, and a document still reads
# ===========================================================================


def test_F1_no_document_is_still_no_document(repo, governed):
    """Green at main too. The hosted path: nothing in the document's place,
    or a file where a directory belongs on the way to it, declares nothing,
    and the governed host trusts an undeclared binding."""
    document = intake_mod.declarations_path(repo)
    assert intake_mod.DeclarationStore(document).pending_binding_ids() == \
        frozenset()
    assert trust_mod.verdict_for(_binding(), root=repo).trusted
    blocker = repo / "a-file"
    blocker.write_text("", encoding="utf-8")
    beneath = intake_mod.DeclarationStore(blocker / "model-declarations.yaml")
    assert beneath.pending_binding_ids() == frozenset()
    assert beneath.read_back()["declarations"] == []


def test_F1_a_regular_document_still_reads(repo, governed):
    """Green at main too. A regular document is read as before: its pending
    binding is refused by the governed host, another is trusted."""
    _pending_document(repo)
    store = intake_mod.DeclarationStore(intake_mod.declarations_path(repo))
    assert store.pending_binding_ids() == frozenset({BINDING_ID})
    assert not trust_mod.verdict_for(_binding(), root=repo).trusted
    assert trust_mod.verdict_for(_binding("another"), root=repo).trusted


@pytest.mark.parametrize("placed", KINDS, indirect=True)
def test_F1_the_port_factorys_pending_set_still_reads_a_refusal_as_empty(
        placed):
    """Green at main too, deliberately. The port factory's own question
    (`doxbench_intake.pending_binding_ids`, which SUPPRESSES bindings) reads
    a document that cannot be read as declaring nothing pending, as its
    docstring says why, so F1 changes nothing for it."""
    _kind, document = placed
    root = document.parent.parent.parent
    answers = _answered(lambda: intake_mod.pending_binding_ids(root),
                        fifo=document)
    assert answers["value"] == frozenset()


# ===========================================================================
# 5. the parse refuses in the bindings store's words (a pin)
# ===========================================================================


UNPARSEABLE = {
    "not-utf-8": b"\xff\xfe\x00schema_version: 1\n",
    "nested": b"[" * 1000 + b"]" * 1000,
    "not-yaml": b"schema_version: [1\n",
    # the holder's ruling, openxFactory#656 comment 5985046107, C3
    "unconstructable": b"schema_version: 1\nnote: 2024-13-01\n",
}


@pytest.mark.parametrize("case", sorted(UNPARSEABLE))
def test_F1_the_declarations_parse_refuses_in_the_bindings_stores_words(
        repo, case):
    """Green at main too: the declarations store read through
    `doxbench_binding.read_settings_document` there. It now reads through
    the descriptor it judged and parses what it read itself, and this pins
    its refusals to that function's words, document for document."""
    raw = UNPARSEABLE[case]
    bindings = binding_mod.bindings_path(repo)
    bindings.parent.mkdir(parents=True, exist_ok=True)
    bindings.write_bytes(raw)
    declarations = intake_mod.declarations_path(repo)
    declarations.write_bytes(raw)
    with pytest.raises(binding_mod.BindingRefused) as said_of_bindings:
        binding_mod.BindingStore(bindings).list()
    with pytest.raises(intake_mod.IntakeRefused) as said_of_declarations:
        intake_mod.DeclarationStore(declarations).list()
    expected = str(said_of_bindings.value).replace(
        f"bindings document at {json.dumps(str(bindings))}",
        f"declarations document at {json.dumps(str(declarations))}")
    assert str(said_of_declarations.value) == expected
