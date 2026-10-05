"""T100 follow-on 2 (plan 034): openDox-code#86's deferred items in
`doxbench_binding`, each as #86's "Deferred to a follow-on (not release 1)"
names its fix (the holder's ruling, openxFactory#656 comment 5992038800;
Brett Heap's word, comment 6000582654, "openDox-code follow-ons first").

- D2 (Copilot at openDox-code#86, r4182645661): `write_settings_document`'s
  staging cleanup is best-effort, so a name it cannot remove never masks a
  completed publish, nor an earlier error.
- D3 (r4182645700): the bindings document's member ceiling names the
  document escaped (`shown_path`).
- D4 (r4182645752): `BindingStore._save` holds a write to the ceiling
  BEFORE it publishes, so the document stays as it was and the CLI takes
  back the trust it recorded.

Each case marked "red at 389e5a4a" fails there for its item's own reason;
the others pin a rule a mutant of the fix would break.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from opendox import cli as cli_mod
from opendox import doxbench_binding as binding_mod
from opendox import doxbench_trust as trust_mod

#: The binding each CLI case declares, and the bindings already there.
BINDING_ID = "helpful-model"
OTHERS = "other-model"

#: An endpoint nothing is asked at: no case here serves a turn.
ENDPOINT = "http://127.0.0.1:9/v1/chat/completions"

#: A broker reference, in the form a broker's own reference takes.
REFERENCE = "opref-0123456789abcdef01234567"

#: Who approved each binding's credential.
APPROVER = "brett@opensoft.one"

#: The staging names `write_settings_document` writes beside a document.
STAGED = ".opendox-new"


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("GIT_", "XF_"))}


class _World:
    """One case's checkout, broker and trust store: a fresh `git init`, a
    broker program outside it, and this machine's trust over a scratch
    state directory, registered as the policy."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        self.repo = tmp_path / "r"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True,
                       env=_clean_env())
        self.broker = tmp_path / "broker.py"
        self.broker.write_text("", encoding="utf-8")
        self.state_dir = tmp_path / "st"
        monkeypatch.setenv("OPENDOX_STATE_DIR", str(self.state_dir))
        trust_mod.unregister()
        self.trust = trust_mod.MachineTrust(state_dir=self.state_dir)
        trust_mod.register(self.trust)
        self.document = binding_mod.bindings_path(self.repo)

    def argv(self, members: int) -> list[str]:
        """A broker command of `members` members, outside the checkout."""
        return [sys.executable, str(self.broker),
                *(["--flag"] * (members - 2))]

    def record(self, binding_id: str, members: int) -> dict:
        return {"kind": "model-provider-binding", "id": binding_id,
                "label": "Helpful model", "provider": "anyone",
                "auth_kind": "api_key", "approved_by": APPROVER,
                "endpoint": ENDPOINT, "dialect": "openai-chat-v1",
                "model": None, "credential_ref": REFERENCE,
                "broker_argv": self.argv(members)}

    def hand_write(self, *sizes: int, path: Path | None = None) -> Path:
        """A bindings document of one binding per size, each of that many
        broker command members, written by hand as a clone delivers it."""
        path = path or self.document
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1, "kind": "model-provider-bindings",
            "bindings": [self.record(f"{OTHERS}-{number}", size)
                         for number, size in enumerate(sizes)]},
            indent=2), encoding="utf-8")
        return path

    def binding(self, members: int, binding_id: str = BINDING_ID):
        return binding_mod.ModelProviderBinding.from_record(
            self.record(binding_id, members))

    def cli(self, verb: str, members: int) -> list[str]:
        """`opendox model-binding <verb>` for this case's binding, its
        broker command of `members` members."""
        return ["model-binding", verb, "--repo-root", str(self.repo),
                "--id", BINDING_ID, "--label", "Helpful model",
                "--provider", "anyone", "--auth-kind", "api_key",
                "--credential-ref", REFERENCE,
                "--credential-approver", APPROVER,
                "--endpoint", ENDPOINT, "--dialect", "openai-chat-v1",
                "--", *self.argv(members)]

    def held(self) -> list:
        """The trust store's entries for this case's binding."""
        store = self.state_dir / trust_mod.TRUST_FILENAME
        if not store.exists():
            return []
        return [entry for entry in json.loads(store.read_text(
            encoding="utf-8"))["entries"] if entry["binding_id"] == BINDING_ID]


@pytest.fixture
def world(tmp_path, monkeypatch):
    return _World(tmp_path, monkeypatch)


def _cli(*argv: str) -> int:
    """A `model-binding` verb, as `opendox` runs it."""
    args = cli_mod.build_parser().parse_args(list(argv))
    return args.func(args)


CEILING = binding_mod.MAX_JUDGED_MEMBERS


def test_the_ceiling_is_the_one_ruled():
    """5990845570 named the ceiling; slice B's broker ceiling imports it by
    this name."""
    assert CEILING == 256


# ---------------------------------------------------------------------------
# D2: the staging cleanup is best-effort
# ---------------------------------------------------------------------------


def _staging_cannot_be_removed(monkeypatch) -> list[str]:
    """Every removal of a staging name fails, as on a directory whose
    permissions changed under the write; other removals are as they were.
    Returns the names whose removal failed."""
    real = Path.unlink
    failed: list[str] = []

    def unlink(self, missing_ok=False):
        if self.name.endswith(STAGED):
            failed.append(self.name)
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    return failed


def _full_disk(monkeypatch) -> None:
    def half_then_full(handle, text):
        handle.write(text[:len(text) // 2])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(binding_mod, "_write_all", half_then_full)


def test_D2_a_staging_name_left_behind_never_fails_a_published_write(
        world, monkeypatch, capsys):
    """Red at 389e5a4a. r4182645661: the new document is published, then
    its staging name cannot be removed. The write succeeded, so it is not
    reported as failed: `add` declares and trusts the binding, and the
    staging name, a second name of the same file, is left beside it."""
    failed = _staging_cannot_be_removed(monkeypatch)
    path = world.repo / "settings" / "document.yaml"
    binding_mod.write_settings_document(path, "schema_version: 1\n")
    assert path.read_text(encoding="utf-8") == "schema_version: 1\n"
    assert len(failed) == 1
    assert _cli(*world.cli("add", 2)) == 0
    out = capsys.readouterr()
    assert "could not be written" not in out.err, out.err
    assert "declared" in out.out
    declared = binding_mod.BindingStore(world.document).get(BINDING_ID)
    assert declared == world.binding(2)
    assert trust_mod.verdict_for(declared, root=world.repo).trusted
    assert len(failed) == 2
    left = [p.name for p in world.document.parent.iterdir()
            if p.name.endswith(STAGED)]
    assert len(left) == 1
    assert (world.document.parent / left[0]).samefile(world.document)


@pytest.mark.parametrize("document", ["new", "existing"])
def test_D2_an_earlier_error_is_never_masked_by_the_cleanup(
        world, monkeypatch, document):
    """Red at 389e5a4a. r4182645661: a write that fails part way (a full
    disk) whose staging name then cannot be removed is refused by the
    write's own error, whether the document is new (the staging name) or
    already there (the temporary file it replaces it from), and the
    document is as it was."""
    path = world.repo / "settings" / "document.yaml"
    if document == "existing":
        binding_mod.write_settings_document(path, "schema_version: 1\n")
    failed = _staging_cannot_be_removed(monkeypatch)
    _full_disk(monkeypatch)
    with pytest.raises(OSError) as raised:
        binding_mod.write_settings_document(path, "schema_version: 2\n")
    assert raised.value.errno == errno.ENOSPC, raised.value
    assert len(failed) == 1
    if document == "new":
        assert not path.exists()
    else:
        assert path.read_text(encoding="utf-8") == "schema_version: 1\n"


def test_D2_a_staging_name_is_removed_where_it_can_be(world, monkeypatch):
    """The cleanup still runs: after a write that succeeds and one that
    fails part way, of a new document and of one already there, nothing is
    left beside the document."""
    path = world.repo / "settings" / "document.yaml"
    binding_mod.write_settings_document(path, "schema_version: 1\n")
    binding_mod.write_settings_document(path, "schema_version: 2\n")
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]
    _full_disk(monkeypatch)
    with pytest.raises(OSError):
        binding_mod.write_settings_document(path, "schema_version: 3\n")
    fresh = world.repo / "fresh" / "document.yaml"
    with pytest.raises(OSError):
        binding_mod.write_settings_document(fresh, "schema_version: 1\n")
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]
    assert list(fresh.parent.iterdir()) == []
    assert path.read_text(encoding="utf-8") == "schema_version: 2\n"


# ---------------------------------------------------------------------------
# D3: the ceiling's refusal names the document escaped
# ---------------------------------------------------------------------------


def test_D3_the_ceilings_refusal_prints_the_documents_path_escaped(
        world, tmp_path):
    """Red at 389e5a4a. r4182645700: a checkout whose path holds a newline
    and a terminal control sequence; the document past the ceiling is
    refused with its path escaped (`shown_path`), on read and on write, so
    the refusal cannot forge or hide output."""
    path = (tmp_path / "forged\nline\x1b[2J" / "ideation" / "dashboard"
            / "model-provider-bindings.yaml")

    def escaped(refused) -> None:
        said = str(refused.value)
        assert binding_mod.shown_path(path) in said, said
        assert "\n" not in said and "\x1b" not in said, said

    world.hand_write(64, 64, 64, 64, 2, path=path)
    with pytest.raises(binding_mod.BindingRefused) as read:
        binding_mod.BindingStore(path).list()
    escaped(read)
    world.hand_write(64, 64, 64, 64, path=path)
    with pytest.raises(binding_mod.BindingRefused) as written:
        binding_mod.BindingStore(path).add(world.binding(2))
    escaped(written)


# ---------------------------------------------------------------------------
# D4: a write is held to the ceiling before it publishes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["add", "edit"])
def test_D4_a_write_past_the_ceiling_is_refused_before_it_publishes(
        world, verb):
    """Red at 389e5a4a. r4182645752: a store write whose bindings would
    declare more broker command members than the ceiling is refused by
    name, and the document is as it was, so it still reads."""
    if verb == "add":
        world.hand_write(64, 64, 64, 64)
        written = world.binding(2)
    else:
        world.hand_write(64, 64, 64, 63)
        written = world.binding(65, f"{OTHERS}-3")
    held = world.document.read_bytes()
    store = binding_mod.BindingStore(world.document)
    with pytest.raises(binding_mod.BindingRefused) as refused:
        getattr(store, verb)(written)
    said = str(refused.value)
    judged = 258 if verb == "add" else 257
    assert f"would declare {judged} broker command members" in said, said
    assert f"more than the {CEILING} judged" in said
    assert "nothing in it changed" in said
    assert world.document.read_bytes() == held
    assert len(store.list()) == 4
    assert sorted(p.name for p in world.document.parent.iterdir()) == [
        world.document.name]


@pytest.mark.parametrize("verb", ["add", "edit"])
def test_D4_a_write_at_the_ceiling_is_written(world, verb):
    """The other side: a write that comes to exactly the ceiling is
    written, and the document reads."""
    if verb == "add":
        world.hand_write(64, 64, 64, 62)
        written = world.binding(2)
    else:
        world.hand_write(64, 64, 64, 63)
        written = world.binding(64, f"{OTHERS}-3")
    store = binding_mod.BindingStore(world.document)
    getattr(store, verb)(written)
    assert written in store.list()
    assert sum(len(b.broker_argv) for b in store.list()) == CEILING


def test_D4_a_new_document_past_the_ceiling_is_never_made(world):
    """Red at 389e5a4a. The first write, of a binding past the ceiling by
    itself, makes no document."""
    store = binding_mod.BindingStore(world.document)
    with pytest.raises(binding_mod.BindingRefused):
        store.add(world.binding(CEILING + 1))
    assert not world.document.exists()


def test_D4_an_add_past_the_ceiling_trusts_nothing(world, capsys):
    """Red at 389e5a4a. r4182645752: `add` records trust first, then its
    write is refused by the ceiling; the document is as it was and the
    trust is withdrawn (the holder's ruling, #656 5985046107, C2), so the
    refusal's "nothing in it changed" is true of both."""
    world.hand_write(64, 64, 64, 64)
    held = world.document.read_bytes()
    assert _cli(*world.cli("add", 2)) == 1
    err = capsys.readouterr().err
    assert f"more than the {CEILING} judged" in err, err
    assert "nothing in it changed" in err
    assert "could not be withdrawn" not in err
    assert world.document.read_bytes() == held
    assert not world.held(), "a trust stayed for no declared form"


@pytest.mark.parametrize("trusted", [True, False],
                         ids=["trusted", "untrusted"])
def test_D4_an_edit_past_the_ceiling_keeps_what_was_trusted(
        world, capsys, trusted):
    """Red at 389e5a4a. r4182645752: `edit` of a binding to a form past the
    ceiling is refused before anything is written; the earlier form is
    trusted again where it was trusted, and the new form's trust withdrawn
    where it was not (A11, C2)."""
    world.hand_write(64, 64, 64)
    if trusted:
        assert _cli(*world.cli("add", 2)) == 0
    else:
        binding_mod.BindingStore(world.document).add(world.binding(2))
    capsys.readouterr()
    before = binding_mod.BindingStore(world.document).get(BINDING_ID)
    held = world.document.read_bytes()
    assert _cli(*world.cli("edit", 65)) == 1
    err = capsys.readouterr().err
    assert "would declare 257 broker command members" in err, err
    assert "could not be restored" not in err
    assert "could not be withdrawn" not in err
    assert world.document.read_bytes() == held
    assert trust_mod.verdict_for(before, root=world.repo).trusted is trusted
    if not trusted:
        assert not world.held(), "a trust stayed for no declared form"


def test_D4_an_add_and_an_edit_at_the_ceiling_are_trusted(world, capsys):
    """The other side, through the CLI: an `add`, then an `edit`, that each
    come to exactly the ceiling are written and trusted."""
    world.hand_write(64, 64, 64, 62)
    assert _cli(*world.cli("add", 2)) == 0
    store = binding_mod.BindingStore(world.document)
    assert trust_mod.verdict_for(store.get(BINDING_ID),
                                 root=world.repo).trusted
    world.hand_write(64, 64, 64)
    assert _cli(*world.cli("add", 2)) == 0
    assert _cli(*world.cli("edit", 64)) == 0
    capsys.readouterr()
    edited = store.get(BINDING_ID)
    assert len(edited.broker_argv) == 64
    assert trust_mod.verdict_for(edited, root=world.repo).trusted
