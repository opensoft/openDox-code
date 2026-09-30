"""openDox's OWN defaults for three of the projection seams: the corpus-root
predicate, the snapshot writer and the validator lookup (plan 034's T055;
R1Q10 (a), `openxFactory#656` comment `5850003126`).

The entry points register them where no host has
(`projection_seams.register_defaults()`). Each is small, neutral and new code.
A host (openXdox, plan 034's T059) contributes its governed one through the
same seam.

`CORPUS_ROOT`, THE CORPUS-ROOT PREDICATE. openDox's own corpus is a plain git
repository, read through the home corpus (`local_git_adapter.LocalGitCorpus`,
T022), and that adapter resolves a repository's ROOT and refuses a directory
that is not one, or is only inside one. So the predicate asks the same
question, structurally and without running `git`: is this an existing
directory holding `.git`? A worktree's `.git` is a file, and it counts. A
tree that passes can still be refused by the adapter, which reads git itself,
and the generate verbs report that refusal too. The served image's empty
sentinel directory fails the predicate, so its checkout-bound affordances stay
off, as they do under the governed predicate. openDox's corpus is not scanned
from named roots, so `SCANNED_ROOTS` is empty. And it declares no change
folder with a staged origin, which is what `change_rows` enumerates for
`branch_session`'s proposal custody, so it answers no row.

`WRITER`, THE SNAPSHOT WRITER. Canonical JSON: keys sorted at every depth, two
spaces of indent, ASCII only, a trailing newline, and no clock. So the same
snapshot is the same bytes. It writes through the interactivity boundary it is
handed, and only there. A snapshot holding what JSON cannot carry (NaN, an
infinity, a value of no JSON type) is refused, `SnapshotNotWritable`, before
anything is written. The write is ATOMIC: a temporary sibling, then one
`os.replace`, so a request never reads a half-written snapshot.

`VALIDATOR`, THE VALIDATOR LOOKUP'S DEFAULT, FOR openDox's OWN KINDS. It is
openDox's own validator, plan 034's T057, which this tree does not carry yet.
Until it does, this stand-in answers every validation `VALIDATOR_UNAVAILABLE`,
naming T057, and never `VALIDATED`: nothing here has checked anything. So a
generate verb warns that its snapshot was not checked, and fails under
`--strict`, and a workbench manifest saved with `validate=True` is refused as
unvalidated, which is what a lone openDox answered before T055 whenever no
validator was reachable. T057's validator replaces it here, under the same
kinds.

IMPORT WEIGHT. `opendox.generator_seam`, `opendox.projection_seams` and the
standard library. So this module imports with no extra installed and no
sibling present.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

from opendox import generator_seam, projection_seams

__all__ = ["CORPUS_ROOT", "CorpusRoot", "OWN_KINDS", "OwnValidatorNotBuilt",
           "SnapshotNotWritable", "VALIDATOR", "WRITER", "Writer"]

#: The workbench manifest's kind, `opendox.workbench.KIND`, restated because
#: `workbench` imports PyYAML and this module must import with nothing extra.
#: `tests/test_projection_seams.py` holds the two spellings together.
WORKBENCH_KIND = "ideation-workbench"

#: The kinds openDox's own validator answers for, which the entry points
#: register it under: the neutral snapshot every generate verb writes with
#: openDox's own generator, and the workbench manifest `workbench.save()`
#: validates. T057 names its full input set, and registers under it.
OWN_KINDS: tuple[str, ...] = (generator_seam.NEUTRAL_SNAPSHOT_KIND, WORKBENCH_KIND)


class CorpusRoot:
    """openDox's own corpus-root predicate: a git repository's root."""

    #: openDox's corpus is not scanned from named roots.
    SCANNED_ROOTS: tuple[str, ...] = ()

    #: What the refusal says it looked for.
    LOOKED_FOR = "the root of a git repository: a directory holding .git"

    @staticmethod
    def corpus_scan_defect(repo_root: Path | str) -> str | None:
        """Why `repo_root` cannot be read as a corpus checkout, or None when
        it can be. Structural only: it answers "could this be read at all",
        and an honestly empty repository passes."""
        path = Path(repo_root)
        try:
            if not path.exists():
                return "the path does not exist"
            if not path.is_dir():
                return "the path is not a directory"
            if not (path / ".git").exists():
                return "the directory is not the root of a git repository"
        except OSError as exc:  # an unreadable path is not a corpus checkout
            return f"the path could not be read ({exc.strerror or exc})"
        return None

    @classmethod
    def corpus_root_refusal(cls, repo_root: Path | str, *,
                            flag: str = "--repo-root",
                            shape: str = "") -> str | None:
        """The operator-facing refusal for a `flag` value that is not a corpus
        checkout, or None when it is one. It names the RESOLVED path it
        checked and what it looked for, because the mistake it catches is a
        path that looks right and resolves somewhere else. `shape` is the
        caller's own correct invocation, appended verbatim."""
        defect = cls.corpus_scan_defect(repo_root)
        if defect is None:
            return None
        try:
            resolved: Path | str = Path(repo_root).resolve()
        except (OSError, RuntimeError):
            resolved = repo_root
        lines = [
            f"{flag} is not a corpus checkout: {defect}",
            f"  checked      {resolved}",
            f"  looked for   {cls.LOOKED_FOR}",
            f"  {flag} must name the SERVED CHECKOUT itself: the repository",
            "  whose documents the snapshot projects. It is not a directory",
            "  above that repository or inside it, and it is not the same path in",
            "  another filesystem namespace: a path that resolves inside a",
            "  container does not resolve on the host, or the reverse. Resolve it",
            "  where THIS command runs.",
        ]
        if shape:
            lines.append("  a correct invocation has this shape:")
            lines.extend(f"    {line}" for line in shape.strip().splitlines())
        return "\n".join(lines)

    @staticmethod
    def change_rows(checkout_root: Path | str) -> tuple:
        """The corpus's change rows, `(change id, status, folder, origin state,
        origin)`. openDox's corpus declares no change folder with a staged
        origin, so there is none."""
        return ()


class SnapshotNotWritable(projection_seams.ProjectionSeamError):
    """The snapshot holds a value JSON cannot carry, so the writer refuses it
    and writes nothing. A generate verb reports it as a refusal."""


class Writer:
    """openDox's own canonical snapshot writer."""

    @staticmethod
    def canonical_json(snapshot: dict[str, Any]) -> str:
        """Deterministic JSON: keys sorted at every depth, two spaces of
        indent, ASCII only, and a trailing newline.

        NOTHING JSON CANNOT CARRY. NaN and the infinities are refused
        (`allow_nan=False`) rather than written as the `NaN` and `Infinity`
        that Python's `json` would otherwise emit, which no JSON reader parses:
        not the server's, not a browser's, not a validator's. So is a value of
        no JSON type, and a structure that contains itself. A registered
        generator can answer any of them, and the seam checks only a
        snapshot's kind and version."""
        try:
            return json.dumps(snapshot, indent=2, sort_keys=True,
                              ensure_ascii=True, allow_nan=False) + "\n"
        except (TypeError, ValueError) as exc:
            raise SnapshotNotWritable(
                f"the snapshot holds a value JSON cannot carry ({exc}). NaN, "
                "the infinities and values of no JSON type have no JSON "
                "spelling, and a file carrying one would be one no JSON reader "
                "parses, so nothing was written") from exc

    def write_snapshot(self, snapshot: dict[str, Any], path: Path | str,
                       boundary) -> Path:
        """Render canonically and write where the interactivity boundary
        permits: its root, under its declared output allowlist.

        ATOMICALLY. `serve.py` answers `/snapshot.json` on threads of its own
        while a refresh rewrites the very snapshot it serves, and a write in
        place (truncate, then write) let a request read a truncated file. So
        the bytes go to a temporary sibling first, and one `os.replace` moves
        them over the target: a reader sees the whole old snapshot or the
        whole new one, never part of either.

        THE BOUNDARY STILL DECIDES THE DESTINATION. `permit_output` is the
        check `write_output` makes, root and allowlist, with its refusal and
        its ledger, and it runs first, so a refused target leaves nothing
        behind. The sibling is created exclusively beside the permitted
        target, with the mode an ordinary write would give it, or with the
        target's own permission bits where the target exists, so a refresh
        never widens a restricted snapshot. Its name is a dot-file with no
        document extension, so `/source` never serves it, and it is removed if
        the write or the move fails."""
        data = self.canonical_json(snapshot).encode("ascii")
        target = boundary.permit_output(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                # THE SNAPSHOT KEEPS ITS PERMISSIONS (Copilot at
                # openDox-code#59 d7aa9d8c, r4136439187). `os.replace` carries
                # the SIBLING's mode over the target, and the sibling is
                # created with a new file's ordinary mode, so a snapshot kept
                # restricted (0600, say) was widened by every refresh. Where
                # the target exists, its permission bits go onto the sibling
                # before a byte is written. A new target keeps the ordinary
                # mode. If they cannot be copied, the write fails: the stream
                # closes the descriptor, the sibling is removed below, and the
                # snapshot is never silently widened.
                with contextlib.suppress(FileNotFoundError):
                    os.fchmod(stream.fileno(), stat.S_IMODE(os.stat(target).st_mode))
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
        return target


class OwnValidatorNotBuilt:
    """The validator lookup's default until openDox's own validator (T057) is
    in this tree. It concludes nothing, and says so."""

    #: No dependency to install would make it run.
    dependency_remedy = None

    def validate(self, path: Path | str, *, strict: bool = False,
                 search_from: tuple = ()) -> projection_seams.ValidationResult:
        return projection_seams.ValidationResult(
            False, -1, "", "", None, projection_seams.VALIDATOR_UNAVAILABLE,
            "openDox's own validator is plan 034's T057, and this build does "
            "not carry it yet, so nothing of openDox's own kinds is checked")


CORPUS_ROOT = CorpusRoot()
WRITER = Writer()
VALIDATOR = OwnValidatorNotBuilt()
