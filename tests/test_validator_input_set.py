"""openDox's validator's input set, held to plan 034's T057.

T057 realizes #1144's 7.1, 7.1a, 7.1b and 7.2, with 7.1 as T007's batch G
amends it (R1Q11 (a) and R1Q12 (a), `openxFactory#656` comment `5850003126`):

    Narrow it to openDox's own kinds: its spec leg's four, which are 7.1's
    three and T053's neutral snapshot schema ... Ship the four as package
    data. A test checks each copy's digest against the spec-leg commit the
    openDox root pins (R1Q12 (a)) ... A test asserts that `gate-intent` and
    `ideation-possibles-register` are NOT in the set (7.1b).

Its falsifier is *"the packaged-copy digest test and the 7.1b test"*. They are
the first two cases below:

* `test_each_packaged_copy_is_the_spec_legs_file_at_the_pinned_commit` is the
  digest test;
* `test_gate_intent_and_the_possibles_register_are_not_in_the_set` is 7.1b's.

WHAT ELSE IT HOLDS.

1. THE SET IS EXACTLY FOUR: the record, the validator's kinds and the files on
   disk all name the same four copies, and none of the six schemas outside
   the set is carried.
2. PRESENCE IS NOT IDENTITY: a copy that differs from its digest, is absent,
   or has no digest recorded is refused before a byte of it is parsed, and a
   validator is never built over it. A record that cannot hold every copy to a
   digest is refused as a whole.
3. THE KINDS ARE THE COPIES': each kind the validator maps is the `kind` const
   its entry declares, and `generator_seam.NEUTRAL_SNAPSHOT_KIND`, the
   contract openDox's own generator declares (T052), is the packaged neutral
   contract's `kind` (the holder's note to T057).
4. AN INSTALL CARRIES THEM: `pyproject.toml`'s package-data table ships,
   under `opendox.contracts`, exactly the record and every copy the record
   pins, and the bundle's own line beside it is unchanged.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import types
from pathlib import Path

import pytest
import yaml

from opendox import contracts
from opendox import default_generator
from opendox import generator_seam
from opendox import validator

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "opendox" / "contracts"

#: openDox's own spec leg's four schemas (7.1, as batch G amends it).
THE_FOUR = ("ideation-workbench", "opendox-snapshot", "xfactory-workbench-chat-turn",
            "xfactory-workbench-model-catalog")

#: The spec-leg commit the openDox root pins, which the copies are held to: T053
#: as landed, openDox-spec#16's squash (opensoft/openDox#14 moved the root's spec
#: pin to it). It is the one commit that carries all four. It moved from #16's
#: head, cd49eb25, with the record, in lockstep. The two commits have one tree.
SPEC_COMMIT = "f7ee3c763b3af4581daf1cd54406e5111e9358e6"

#: WHAT THE OPENDOX ROOT PINS, stated here apart from the record, so that a copy
#: and its recorded digest cannot move together unseen. All four are the
#: digests the root's `contracts/manifest.yaml` records for them at its spec
#: pin, `SPEC_COMMIT` (the root's `main` at 52005213, opensoft/openDox#14). The
#: first three are unchanged from the root's previous spec pin, 8fe8c4c7. The
#: fourth is T053's new `opendox-snapshot` entry.
PINNED_BY_THE_ROOT = {
    "ideation-workbench":
        "d30438491119c20928fbe4e85088fc33682829eeb6558d87dafce651000faafc",
    "opendox-snapshot":
        "f9e3e111af1d4bd4c377c933027d81b582ae2b0a395b66f4e4621992454a584a",
    "xfactory-workbench-chat-turn":
        "350bfedc02696e7281a42c0bdc9a25059bf7af14d16d89d9f07018d3e691dc1d",
    "xfactory-workbench-model-catalog":
        "e563cc9fc6ede03dfd62537935d0ae0842617d7de46702aee6ad9026aa021635",
}

#: The ten schemas of the family the consumer's script names
#: (`SCHEMA_FILENAMES`), by owner, as #1144's 7.1 tables them.
OPENXDOX_SPECS = ("ideation-dashboard-snapshot", "ideation-dashboard-snapshot-index",
                  "gate-action-record")
OPENXFACTORYS = ("ideation-possibles-register", "project-register",
                 "demotion-execution-receipt", "gate-intent")


# ---------------------------------------------------------------------------
# the falsifier
# ---------------------------------------------------------------------------

def test_each_packaged_copy_is_the_spec_legs_file_at_the_pinned_commit() -> None:
    """THE DIGEST TEST. Each copy on disk has the sha256 the record pins, the
    record pins each copy at the spec leg's own path and at one spec-leg
    commit, and each digest is the one the openDox root pins for that file."""
    record = contracts.record()
    assert record.spec_leg == "opensoft/openDox-spec"
    assert record.commit == SPEC_COMMIT, (
        f"the copies are recorded at {record.commit}, and this test holds them at "
        f"{SPEC_COMMIT}. They move together, in one commit: copy the spec leg's "
        "files at the commit the openDox root pins, and move both")
    assert record.ids == THE_FOUR
    for copy in record.copies:
        on_disk = PACKAGE / "schemas" / f"{copy.id}.schema.yaml"
        digest = hashlib.sha256(on_disk.read_bytes()).hexdigest()
        assert copy.path == f"contracts/schemas/{copy.id}.schema.yaml"
        assert copy.resource == f"schemas/{copy.id}.schema.yaml"
        assert digest == copy.sha256, (
            f"{on_disk.relative_to(ROOT)} is {digest}, and the record pins "
            f"{copy.sha256}. A copy is never edited in place")
        assert copy.sha256 == PINNED_BY_THE_ROOT[copy.id], (
            f"the record pins {copy.id} at {copy.sha256}, and the openDox root "
            f"pins {PINNED_BY_THE_ROOT[copy.id]}")
        # the package reads the same bytes, through its own identity check
        assert contracts.verified_bytes(copy.id) == on_disk.read_bytes()


def test_gate_intent_and_the_possibles_register_are_not_in_the_set() -> None:
    """7.1b. `gate-intent` is an intent-plane schema that requirement 1 keeps
    with openxFactory, and `ideation-possibles-register` is openxFactory's own
    candidate register. Neither is a kind openDox validates, neither is a
    packaged copy, neither is on disk, and no validator can be asked for
    either."""
    for name in ("gate-intent", "ideation-possibles-register"):
        assert name not in validator.KIND_ENTRIES, f"{name} is a kind openDox validates"
        assert name not in {copy for copy, _pointer in validator.KIND_ENTRIES.values()}, (
            f"a kind is validated against a copy of {name}")
        assert name not in contracts.record().ids, f"the record pins a copy of {name}"
        assert name not in contracts.COPY_IDS, f"a record may name a copy of {name}"
        assert not (PACKAGE / "schemas" / f"{name}.schema.yaml").exists(), (
            f"a copy of {name} is carried under src/opendox/contracts/schemas/, "
            "which 7.1b refuses: requirement 1 keeps it with openxFactory")
        with pytest.raises(validator.UnknownKind):
            validator.validator_for(name)
        with pytest.raises(contracts.CopyRefused):
            contracts.verified_bytes(name)


# ---------------------------------------------------------------------------
# the set is exactly four
# ---------------------------------------------------------------------------

def test_the_set_is_the_spec_legs_four_and_nothing_else() -> None:
    """7.1: openDox validates its own spec leg's kinds. The record, the kinds'
    entries and the files on disk name the same four copies. None of the
    consumer's three and none of openxFactory's four is carried."""
    entries = {copy for copy, _pointer in validator.KIND_ENTRIES.values()}
    on_disk = {path.name.removesuffix(".schema.yaml")
               for path in (PACKAGE / "schemas").iterdir()}
    assert set(THE_FOUR) == entries == on_disk == set(contracts.record().ids)
    assert contracts.COPY_IDS == set(THE_FOUR)
    assert not (set(OPENXDOX_SPECS) | set(OPENXFACTORYS)) & on_disk
    assert sorted(p.name for p in PACKAGE.iterdir() if p.name != "__pycache__") == [
        "__init__.py", "copies.yaml", "schemas"]


def test_each_kind_is_the_const_its_entry_declares() -> None:
    """The validator's map of kinds is the copies' own: each kind's entry
    declares that kind as its `kind` const. So a kind the map names and no
    copy declares, or a copy's kind the map leaves out, fails here."""
    derived = {}
    for copy_id in THE_FOUR:
        document = contracts.load(copy_id)
        envelopes = [document] if "oneOf" not in document else [
            validator._at_pointer(document, branch["$ref"][1:])
            for branch in document["oneOf"]]
        for envelope in envelopes:
            derived[envelope["properties"]["kind"]["const"]] = copy_id
    assert {kind: copy for kind, (copy, _pointer) in validator.KIND_ENTRIES.items()} == derived
    assert validator.KINDS == tuple(sorted(derived))
    for kind, (copy_id, pointer) in validator.KIND_ENTRIES.items():
        entry = validator._at_pointer(contracts.load(copy_id), pointer)
        assert entry["properties"]["kind"]["const"] == kind


def test_the_neutral_snapshot_kind_is_the_packaged_contracts_kind() -> None:
    """The contract openDox's own generator declares (T052's
    `NEUTRAL_SNAPSHOT_KIND`) is the packaged neutral contract's `kind` const,
    so what the generator writes is what this validator validates it
    against."""
    snapshot_contract = contracts.load("opendox-snapshot")
    kind = snapshot_contract["properties"]["kind"]["const"]
    assert generator_seam.NEUTRAL_SNAPSHOT_KIND == kind == "opendox-snapshot"
    assert default_generator.GENERATOR.contract == kind
    assert validator.KIND_ENTRIES[kind] == ("opendox-snapshot", "")
    assert validator.validator_for(kind).copy_id == "opendox-snapshot"


# ---------------------------------------------------------------------------
# presence is not identity
# ---------------------------------------------------------------------------

def _serve(monkeypatch: pytest.MonkeyPatch, replaced: dict[str, bytes | None]) -> None:
    """Answer the package's reads from `replaced` where it names the file
    (None is an absent file), and from the package itself otherwise."""
    real = contracts._read_package_file

    def read(name: str) -> bytes:
        if name in replaced:
            if replaced[name] is None:
                raise contracts.CopyRefused(f"opendox.contracts has no {name}")
            return replaced[name]
        return real(name)

    monkeypatch.setattr(contracts, "_read_package_file", read)


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root reads a file at mode 000")
@pytest.mark.parametrize("name", ["copies.yaml", "schemas/opendox-snapshot.schema.yaml"])
def test_a_present_file_that_cannot_be_read_is_refused_not_raised(
        name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged record or copy that is present but unreadable is refused as
    `CopyRefused`, so the validator reports itself unavailable, as for a
    missing one. It raised `PermissionError` out of `validator_for()`, and
    `generate --strict` ended in a traceback (the T058 writer's measurement,
    from Copilot at openDox-code#68, r4139734412)."""
    package = tmp_path / "contracts"
    shutil.copytree(PACKAGE, package)
    (package / name).chmod(0)
    monkeypatch.setattr(contracts, "resources",
                        types.SimpleNamespace(files=lambda _name: package))
    try:
        with pytest.raises(contracts.CopyRefused) as refused:
            contracts.load("opendox-snapshot")
        assert "cannot be read (PermissionError" in str(refused.value)
        with pytest.raises(validator.ValidatorUnavailable):
            validator.validator_for("opendox-snapshot")
    finally:
        (package / name).chmod(0o644)


def _record_with(**changes) -> bytes:
    data = yaml.safe_load((PACKAGE / "copies.yaml").read_text(encoding="utf-8"))
    data.update(changes)
    return yaml.safe_dump(data, sort_keys=False).encode()


def test_a_changed_copy_is_refused_before_a_byte_of_it_is_parsed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """One byte added to the neutral contract's copy is refused by the
    identity check, naming both digests, before YAML is asked to read it; and
    the validator reports itself unavailable rather than validating."""
    changed = (PACKAGE / "schemas" / "opendox-snapshot.schema.yaml").read_bytes() + b"\n"
    _serve(monkeypatch, {"schemas/opendox-snapshot.schema.yaml": changed})
    parsed: list = []
    real_load = yaml.safe_load

    def spy(stream, *args, **kwargs):
        parsed.append(stream)
        return real_load(stream, *args, **kwargs)

    monkeypatch.setattr(yaml, "safe_load", spy)
    with pytest.raises(contracts.CopyRefused) as refused:
        contracts.load("opendox-snapshot")
    assert PINNED_BY_THE_ROOT["opendox-snapshot"] in str(refused.value)
    assert hashlib.sha256(changed).hexdigest() in str(refused.value)
    assert parsed, "the record, which is read first, was not read through YAML"
    assert changed not in parsed, (
        "the changed copy was parsed before its identity was proved")


def test_a_changed_copy_leaves_the_validator_unavailable(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The validator proves the copy on every call, so a copy that changes
    after a validator was built and cached is refused on the next call, not
    answered from the cache."""
    assert validator.validator_for("opendox-snapshot").is_valid(
        yaml.safe_load((ROOT / "tests" / "fixtures" / "spec-examples" /
                        "opendox-snapshot-no-front-matter.example.yaml").read_text()))
    real = (PACKAGE / "schemas" / "opendox-snapshot.schema.yaml").read_bytes()
    _serve(monkeypatch, {"schemas/opendox-snapshot.schema.yaml": real.replace(
        b'"minLength": 1', b'"minLength": 0', 1)})
    with pytest.raises(validator.ValidatorUnavailable) as unavailable:
        validator.validator_for("opendox-snapshot")
    assert "is not the file the record pins" in str(unavailable.value)
    with pytest.raises(validator.ValidatorUnavailable):
        validator.validators()


def test_an_absent_copy_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, {"schemas/ideation-workbench.schema.yaml": None})
    with pytest.raises(contracts.CopyRefused):
        contracts.verified_bytes("ideation-workbench")
    with pytest.raises(validator.ValidatorUnavailable):
        validator.validator_for("ideation-workbench")


#: The shipped record's own entries, for the cases that add one or drop one.
_SHIPPED = yaml.safe_load((PACKAGE / "copies.yaml").read_text(encoding="utf-8"))["copies"]


@pytest.mark.parametrize("changes, says", [
    ({"copies": [{"id": "opendox-snapshot",
                  "path": "contracts/schemas/opendox-snapshot.schema.yaml",
                  "sha256": ""}]}, "not a 64-hex sha256"),
    ({"copies": [{"id": "opendox-snapshot",
                  "path": "contracts/schemas/opendox-snapshot.schema.yaml"}]},
     "exactly id, path and sha256"),
    ({"copies": [{"id": "opendox-snapshot", "path": "schemas/elsewhere.yaml",
                  "sha256": "0" * 64}]}, "not 'contracts/schemas/opendox-snapshot"),
    ({"copies": [{"id": "opendox-snapshot",
                  "path": "contracts/schemas/opendox-snapshot.schema.yaml",
                  "sha256": "f" * 64}] * 2}, "recorded twice"),
    ({"copies": []}, "not a non-empty list"),
    ({"commit": "cd49eb25"}, "not a full 40-hex commit id"),
    ({"spec_leg": "opensoft/openXdox-spec"}, "spec_leg is"),
    ({"kind": "pinned_contract_manifest"}, "kind is"),
    ({"schema_version": True}, "schema_version is"),
    ({"unread": 1}, "its keys are"),
    # 7.1b at run time: an edited record cannot let a fifth schema in, even a
    # well-formed entry whose file sits beside the four, nor leave one out.
    ({"copies": _SHIPPED + [{"id": "gate-intent",
                             "path": "contracts/schemas/gate-intent.schema.yaml",
                             "sha256": "0" * 64}]}, "not openDox's four"),
    ({"copies": _SHIPPED[:3]}, "not openDox's four"),
], ids=["empty digest", "no digest", "wrong path", "repeated id", "no copies",
        "short commit", "another leg", "another kind", "boolean version", "unknown key",
        "a fifth copy", "three copies"])
def test_a_record_that_cannot_hold_every_copy_is_refused(
        monkeypatch: pytest.MonkeyPatch, changes: dict, says: str) -> None:
    """An empty or absent digest is drift and never a pass, and so is a record
    whose shape leaves any copy unpinned."""
    _serve(monkeypatch, {contracts.RECORD_NAME: _record_with(**changes)})
    with pytest.raises(contracts.CopyRefused) as refused:
        contracts.record()
    assert says in str(refused.value)
    with pytest.raises(validator.ValidatorUnavailable):
        validator.validator_for("opendox-snapshot")


def test_a_record_whose_keys_are_not_all_text_is_refused(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A YAML key need not be text. The refusal names such a key rather than
    failing to order it against the others."""
    data = yaml.safe_load((PACKAGE / "copies.yaml").read_text(encoding="utf-8"))
    data[1] = "a number as a key"
    _serve(monkeypatch, {contracts.RECORD_NAME: yaml.safe_dump(data, sort_keys=False).encode()})
    with pytest.raises(contracts.CopyRefused) as refused:
        contracts.record()
    assert "its keys are ['commit', 'copies', 'kind', 'schema_version', 'spec_leg', 1]" in (
        str(refused.value))
    with pytest.raises(validator.ValidatorUnavailable):
        validator.validator_for("opendox-snapshot")


#: YAML nested past Python's recursion limit, which no read of it ends.
_TOO_DEEP = b"[" * 5000 + b"]" * 5000


def test_a_record_nested_past_the_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, {contracts.RECORD_NAME: _TOO_DEEP})
    with pytest.raises(contracts.CopyRefused) as refused:
        contracts.record()
    assert "not YAML this module can read (RecursionError)" in str(refused.value)


@pytest.mark.parametrize("copy, raised", [
    (_TOO_DEEP, "RecursionError"),
    (b"kind: 2026-02-30\n", "ValueError"),
], ids=["nested past the limit", "an impossible date"])
def test_an_unreadable_copy_is_refused_under_its_own_digest(
        monkeypatch: pytest.MonkeyPatch, copy: bytes, raised: str) -> None:
    """Recorded under its own digest, so it passes the identity check, the copy
    is still refused as unreadable, never a RecursionError or a ValueError to
    the caller."""
    entries = [dict(entry) for entry in _SHIPPED]
    for entry in entries:
        if entry["id"] == "opendox-snapshot":
            entry["sha256"] = hashlib.sha256(copy).hexdigest()
    _serve(monkeypatch, {contracts.RECORD_NAME: _record_with(copies=entries),
                         "schemas/opendox-snapshot.schema.yaml": copy})
    with pytest.raises(contracts.CopyRefused) as refused:
        contracts.load("opendox-snapshot")
    assert f"({raised})" in str(refused.value)
    with pytest.raises(validator.ValidatorUnavailable) as unavailable:
        validator.validator_for("opendox-snapshot")
    assert f"({raised})" in str(unavailable.value)


@pytest.mark.parametrize("record", [
    b"schema_version: " + b"9" * 5000 + b"\n",
    b"schema_version: 1\nkind: 2026-02-30\n",
], ids=["an integer past 4300 digits", "an impossible date"])
def test_a_record_pyyaml_cannot_construct_is_refused(
        monkeypatch: pytest.MonkeyPatch, record: bytes) -> None:
    """PyYAML raises ValueError, not a YAMLError, for a literal it cannot
    construct. The record is refused, never a ValueError to the caller."""
    _serve(monkeypatch, {contracts.RECORD_NAME: record})
    with pytest.raises(contracts.CopyRefused) as refused:
        contracts.record()
    assert "not YAML this module can read (ValueError)" in str(refused.value)
    with pytest.raises(validator.ValidatorUnavailable):
        validator.validator_for("opendox-snapshot")


def test_the_record_as_shipped_is_accepted() -> None:
    """The negative cases above change one field each of the shipped record,
    so this is their control."""
    record = contracts.record()
    assert (record.commit, record.ids) == (SPEC_COMMIT, THE_FOUR)


# ---------------------------------------------------------------------------
# package data (7.1): an install carries the copies
# ---------------------------------------------------------------------------

def test_the_package_data_ships_the_record_and_every_copy() -> None:
    """7.1 settles that the copies travel as PACKAGE DATA, so an install has
    them beside the validator. The package-data table names, under
    `opendox.contracts`, exactly the record and every schema copy the record
    pins, and the bundle's own line is unchanged. (A wheel built without it
    carries `opendox/contracts/__init__.py` alone, and its validator refuses,
    naming the absent record.)"""
    import fnmatch
    import tomllib

    table = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    data = table["tool"]["setuptools"]["package-data"]
    assert data["opendox"] == ["web/**"]
    patterns = data["opendox.contracts"]
    shipped = sorted(
        relative for relative in (p.relative_to(PACKAGE).as_posix()
                                  for p in PACKAGE.rglob("*") if p.is_file())
        if any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns))
    assert shipped == sorted([contracts.RECORD_NAME]
                             + [copy.resource for copy in contracts.record().copies])
