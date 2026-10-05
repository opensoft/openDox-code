"""D5: the declared broker is held to `doxbench_binding.MAX_JUDGED_MEMBERS`
(openDox-code#86's deferred r4182645796; release 1's follow-on slice B,
openxFactory#656 comment 6000630835).

THE DEFECT, at openDox-code `389e5a4a`. A bindings document may declare at
most `MAX_JUDGED_MEMBERS` broker command members (Copilot at
openDox-code#86, r4182002696; the holder's ruling 5990845570), but the
declarations document's broker had no ceiling. The console intake hands
that broker's argv, which the served repository wrote, to
`doxbench_trust.broker_command_refused`, whose bounds scan reads every
member before the work budget starts, so the scan was linear in the
document's size on every surface request.

THE FIX. `BrokerDeclaration` refuses more members than the ceiling, by
name, which it imports from `doxbench_binding` and never restates. It is
held at construction, so the read (`from_record`) and the write
(`DeclarationStore.declare_broker`) both refuse, and no write can cross it.

Each case marked RED AT MAIN fails at `389e5a4a`; the others are controls.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json

import pytest

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_intake as intake_mod

CEILING = binding_mod.MAX_JUDGED_MEMBERS


def _argv(members: int) -> list[str]:
    """A broker command of `members` members, each a fixed leading argument
    of a program outside any repository."""
    return ["/opt/broker/bin/broker", *(f"--fixed-{n}" for n in range(
        members - 1))]


def _past_the_ceiling(members: int, ceiling: int = CEILING) -> str:
    return (f"a broker declaration declares {members} broker command "
            f"members, more than the {ceiling} judged in one document; name "
            "the broker program and its fixed leading arguments only")


def _write_declarations(repo, argv: list[str]):
    """A declarations document in `repo` whose broker is `argv`, written by
    hand, as a clone delivers it. JSON is YAML."""
    document = intake_mod.declarations_path(repo)
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(json.dumps({
        "schema_version": intake_mod.SCHEMA_VERSION,
        "kind": intake_mod.DECLARATIONS_KIND,
        "broker": {"kind": intake_mod.BROKER_KIND, "argv": argv},
        "declarations": []}), encoding="utf-8")
    return document


def test_D5_a_broker_at_the_ceiling_is_read():
    """A control, green at main too: a broker of exactly the ceiling's
    members is read, member for member."""
    argv = _argv(CEILING)
    declared = intake_mod.BrokerDeclaration.from_record(
        {"kind": intake_mod.BROKER_KIND, "argv": argv})
    assert declared.argv == tuple(argv)


def test_D5_a_broker_past_the_ceiling_is_refused_by_name():
    """RED AT MAIN. One member past the ceiling is refused by name, naming
    how many there are and the ceiling."""
    with pytest.raises(intake_mod.IntakeRefused) as refused:
        intake_mod.BrokerDeclaration.from_record(
            {"kind": intake_mod.BROKER_KIND, "argv": _argv(CEILING + 1)})
    assert str(refused.value) == _past_the_ceiling(CEILING + 1)


def test_D5_the_ceiling_is_imported_never_restated(monkeypatch):
    """RED AT MAIN. The ceiling is read from `doxbench_binding` when a
    broker is declared, so a broker moves with it: at a ceiling of three,
    three members are read and four refused."""
    monkeypatch.setattr(binding_mod, "MAX_JUDGED_MEMBERS", 3)
    assert len(intake_mod.BrokerDeclaration(argv=_argv(3)).argv) == 3
    with pytest.raises(intake_mod.IntakeRefused) as refused:
        intake_mod.BrokerDeclaration(argv=_argv(4))
    assert str(refused.value) == _past_the_ceiling(4, 3)


READS = {
    "broker": lambda store: store.broker(),
    "read_back": lambda store: store.read_back(),
    "pending_binding_ids": lambda store: store.pending_binding_ids(),
    "get": lambda store: store.get("m1"),
}


@pytest.mark.parametrize("read", sorted(READS))
def test_D5_a_document_whose_broker_passes_the_ceiling_is_refused(
        tmp_path, read):
    """RED AT MAIN. A declarations document whose broker passes the ceiling
    is refused by name by every read of the store, so the console intake's
    surface, which reads the broker through `read_back`, offers nothing to
    judge; at the ceiling it reads."""
    store = intake_mod.DeclarationStore(
        _write_declarations(tmp_path, _argv(CEILING + 1)))
    with pytest.raises(intake_mod.IntakeRefused) as refused:
        READS[read](store)
    assert str(refused.value) == _past_the_ceiling(CEILING + 1)
    _write_declarations(tmp_path, _argv(CEILING))
    READS[read](store)              # the control: at the ceiling it reads
    assert len(store.broker().argv) == CEILING


def test_D5_no_write_crosses_the_ceiling(tmp_path):
    """RED AT MAIN (the broker was declared and written). A broker past the
    ceiling cannot be built to be declared, so no document is written that
    every read would then refuse; the document is as it was."""
    document = _write_declarations(tmp_path, _argv(1))
    before = document.read_bytes()
    store = intake_mod.DeclarationStore(document)
    with pytest.raises(intake_mod.IntakeRefused) as refused:
        store.declare_broker(intake_mod.BrokerDeclaration(
            argv=_argv(CEILING + 1)))
    assert str(refused.value) == _past_the_ceiling(CEILING + 1)
    assert document.read_bytes() == before
    store.declare_broker(intake_mod.BrokerDeclaration(argv=_argv(CEILING)))
    assert len(store.broker().argv) == CEILING
