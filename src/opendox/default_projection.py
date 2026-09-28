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
anything is written.

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

import json
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
        """Render canonically and write through the interactivity boundary,
        which writes only under its declared output allowlist."""
        return boundary.write_output(path, self.canonical_json(snapshot))


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
