"""THE PACKAGED COPIES of openDox's spec-leg contracts, and their identity.

WHY THIS PACKAGE EXISTS. Plan 034's T057 realizes #1144's 7.1, which T007's
batch G amends on R1Q11 (a) and R1Q12 (a) (`openxFactory#656` comment
`5850003126`): *"openDox's validator validates its spec leg's FOUR kinds ...
The code leg carries digest-checked copies of the four, which a test holds to
the spec-leg commit the openDox root pins."* 7.1 also settles how the four
reach an install. They ship as PACKAGE DATA, *"so `pip install openDox-code`
puts them on disk beside the validator and the assembly root remains their
source of truth for editing"*. So a code-leg checkout with no assembly root
around it still has them, and so does an install. `opendox.validator` reads
them from here, and T085's doxBench validators will read the same copies.

WHAT IS HERE.

* `schemas/`: the four copies. Each one is byte for byte the spec leg's file
  of the same name, `contracts/schemas/<id>.schema.yaml` in
  opensoft/openDox-spec.
* `copies.yaml`: the record. It names the spec-leg commit the copies were taken
  at, and each copy's id, spec-leg path and sha256.

PRESENCE IS NOT IDENTITY. A copy is read only through `verified_bytes()`. It
recomputes the copy's sha256 and compares it with the record BEFORE a byte of
the copy is parsed, and it refuses, with `CopyRefused`, a copy that differs
from its digest, a copy that is absent, and a copy whose digest the record
leaves empty. That is `neutral-product-pin`'s rule for a vendored contract
(*"A vendored foreign contract is digest-verified before it is read"*): a
recomputed digest can never equal an empty recorded one, so an empty digest is
drift, and a file that merely exists proves nothing.

CONSUMED, NOT OWNED. openDox-spec owns these four schemas. The code leg
releases none of them, and a copy is changed in the spec leg and then copied
here again, never edited here. The copies, the record, and the `commit` it
names move together, in one commit.

IMPORT WEIGHT. The standard library, and PyYAML (the package's one runtime
dependency) when the record is read. Importing this package reads no file and
names no sibling.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import PurePosixPath
from typing import Any

__all__ = [
    "COPY_IDS",
    "COPY_KIND",
    "CopyRefused",
    "PackagedCopy",
    "Record",
    "RECORD_NAME",
    "SPEC_LEG",
    "load",
    "record",
    "verified_bytes",
]

#: The record's file name, beside this module.
RECORD_NAME = "copies.yaml"

#: The record's `kind`.
COPY_KIND = "packaged-contract-copies"

#: The repository every copy comes from: openDox's own spec leg.
SPEC_LEG = "opensoft/openDox-spec"

#: Where a copy sits under this package: `schemas/<the spec leg's file name>`.
SCHEMA_DIR = "schemas"

#: THE INPUT SET, as a record must hold it: openDox's own spec leg's four
#: schemas (7.1, as T007's batch G amends it). A record that names any other
#: copy, or leaves one of these out, is refused, like a record naming another
#: leg. So no edit to the record lets a copy of `gate-intent` or of the
#: possibles register (7.1b) be served, even with its file beside the others.
COPY_IDS = frozenset({"ideation-workbench", "opendox-snapshot",
                      "xfactory-workbench-chat-turn", "xfactory-workbench-model-catalog"})

_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class CopyRefused(RuntimeError):
    """A packaged copy, or the record that pins the copies, cannot be trusted.

    Raised before any byte of the copy is parsed. The message names the copy,
    what was found, and the one remedy: copy the spec leg's file again at the
    recorded commit, and record its digest in the same commit."""


@dataclass(frozen=True)
class PackagedCopy:
    """One copy, as the record declares it."""

    id: str
    path: str       # its path in the spec leg: contracts/schemas/<id>.schema.yaml
    sha256: str     # its digest at the recorded commit

    @property
    def resource(self) -> str:
        """Where the copy sits under this package."""
        return f"{SCHEMA_DIR}/{PurePosixPath(self.path).name}"


@dataclass(frozen=True)
class Record:
    """`copies.yaml`, read and checked."""

    spec_leg: str
    commit: str
    copies: tuple[PackagedCopy, ...]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(copy.id for copy in self.copies)

    def copy(self, copy_id: str) -> PackagedCopy:
        for copy in self.copies:
            if copy.id == copy_id:
                return copy
        raise CopyRefused(
            f"{copy_id!r} is not one of the packaged copies {list(self.ids)} "
            f"({RECORD_NAME} records no such copy, so none is read)")


def _refuse(detail: str) -> CopyRefused:
    return CopyRefused(
        f"{RECORD_NAME} cannot be trusted: {detail}. The record is written "
        f"with the copies it pins, in one commit, from {SPEC_LEG} at the "
        "commit the openDox root pins")


def _read_package_file(name: str) -> bytes:
    try:
        return resources.files(__name__).joinpath(name).read_bytes()
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as exc:
        raise CopyRefused(
            f"opendox.contracts has no {name}: the package was built or "
            f"installed without it ({type(exc).__name__})") from exc


def record() -> Record:
    """The record, read from the package and checked field by field.

    Refuses, with `CopyRefused`, a record it cannot hold every copy to: a
    missing or malformed field, an unknown field, a repeated id, a path that
    is not the id's schema path in the spec leg, and an empty or malformed
    digest."""
    import yaml

    try:
        data = yaml.safe_load(_read_package_file(RECORD_NAME))
    except (yaml.YAMLError, RecursionError, ValueError) as exc:
        # RecursionError: YAML nested past Python's limit, which no read ends.
        # ValueError: a literal PyYAML cannot construct (an integer past
        # Python's 4300 digits, or an impossible date).
        raise _refuse(f"it is not YAML this module can read "
                      f"({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise _refuse(f"it is a {type(data).__name__}, not a mapping")
    expected = {"schema_version", "kind", "spec_leg", "commit", "copies"}
    if set(data) != expected:
        # A YAML key need not be text, so the keys are ordered by their repr.
        raise _refuse(f"its keys are {sorted(data, key=repr)}, not {sorted(expected)}")
    if data["schema_version"] != 1 or isinstance(data["schema_version"], bool):
        raise _refuse(f"schema_version is {data['schema_version']!r}, not 1")
    if data["kind"] != COPY_KIND:
        raise _refuse(f"kind is {data['kind']!r}, not {COPY_KIND!r}")
    if data["spec_leg"] != SPEC_LEG:
        raise _refuse(f"spec_leg is {data['spec_leg']!r}, not {SPEC_LEG!r}")
    commit = data["commit"]
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise _refuse(f"commit is {commit!r}, not a full 40-hex commit id")
    entries = data["copies"]
    if not isinstance(entries, list) or not entries:
        raise _refuse("copies is not a non-empty list")
    copies: list[PackagedCopy] = []
    for index, entry in enumerate(entries):
        where = f"copies[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"id", "path", "sha256"}:
            raise _refuse(f"{where} is not a mapping of exactly id, path and sha256")
        copy_id, path, digest = entry["id"], entry["path"], entry["sha256"]
        if not isinstance(copy_id, str) or not _ID.fullmatch(copy_id):
            raise _refuse(f"{where}.id is {copy_id!r}, not a lowercase hyphenated id")
        if path != f"contracts/schemas/{copy_id}.schema.yaml":
            raise _refuse(f"{where}.path is {path!r}, not "
                          f"'contracts/schemas/{copy_id}.schema.yaml'")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            # An EMPTY digest lands here too: it is drift, never a pass.
            raise _refuse(f"{where}.sha256 is {digest!r}, not a 64-hex sha256")
        if any(copy.id == copy_id for copy in copies):
            raise _refuse(f"{where}.id {copy_id!r} is recorded twice")
        copies.append(PackagedCopy(copy_id, path, digest))
    recorded = {copy.id for copy in copies}
    if recorded != COPY_IDS:
        raise _refuse(f"it records {sorted(recorded)}, not openDox's four, "
                      f"{sorted(COPY_IDS)} (7.1; 7.1b keeps every other schema out)")
    return Record(SPEC_LEG, commit, tuple(copies))


def verified_bytes(copy_id: str) -> bytes:
    """The copy's bytes, once they are proved to be the recorded ones.

    Reads the copy, recomputes its sha256, and refuses with `CopyRefused`
    unless it equals the record's digest. Nothing is parsed before that
    comparison, so a caller never reads a copy whose identity is unproved."""
    pins = record()
    pinned = pins.copy(copy_id)
    data = _read_package_file(pinned.resource)
    actual = hashlib.sha256(data).hexdigest()
    if actual != pinned.sha256:
        raise CopyRefused(
            f"the packaged copy of {copy_id} ({pinned.resource}) is not the "
            f"file the record pins: its sha256 is {actual}, and {RECORD_NAME} "
            f"records {pinned.sha256} for {pinned.path} in {SPEC_LEG} at "
            f"{pins.commit}. A copy is never edited in place: copy the spec "
            "leg's file again, and record its digest in the same commit")
    return data


def load(copy_id: str) -> Any:
    """The copy, parsed, after `verified_bytes()` has proved its identity."""
    import yaml

    data = verified_bytes(copy_id)
    try:
        return yaml.safe_load(data)
    except (yaml.YAMLError, RecursionError, ValueError) as exc:
        raise CopyRefused(
            f"the packaged copy of {copy_id} matches its digest but is not "
            f"YAML ({exc.__class__.__name__})") from exc
