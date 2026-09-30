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

`VALIDATORS`, THE VALIDATOR LOOKUP'S DEFAULT, ONE PER OWN KIND (plan 034's
T058). Each is an adapter over openDox's own validator, `opendox.validator`
(T057), bound to one of `OWN_KINDS`, and it keeps the lookup's protocol:
`validate(path, *, strict, search_from)` answers a
`projection_seams.ValidationResult`. The seam registers one validator per
kind and hands it only a path, so the adapter is what knows the kind: the one
it is registered under.

* IT READS THE DOCUMENT AS ITS KIND IS WRITTEN. The neutral snapshot is JSON,
  as this module's writer writes it, and it is parsed as JSON alone: NaN, the
  infinities and a key given twice are not JSON, and are refused. The
  workbench manifest is YAML, parsed with PyYAML's safe loader, as
  `workbench.py` reads it. Then `opendox.validator.validator_for(kind)` judges
  it against openDox's packaged copy of that kind's schema, which is proved
  against its recorded digest on every call.
* THREE OUTCOMES, as `cli._validate` gives them their consequences. No
  violation is `VALIDATED`. Any violation is `NOT_CONFORMANT`, return code 1,
  and the standard output names each one as `[<rule>] <where>: <detail>`, so
  the rule's identifier reaches the verb's report (F7.2 asserts T051's
  `EXPECTED_RULE` there). A document that cannot be read as JSON, or as
  YAML, breaks `SYNTAX_RULE`, and so does one holding a number that cannot
  be read as written: an infinity, a NaN, or one binary64 would round.
  `ValidatorUnavailable`, a packaged copy that failed its
  identity check or cannot be evaluated, is `VALIDATOR_UNAVAILABLE`, with the
  validator's own reason, and so is a document that could not be read. That
  is "the check could not be performed", never a pass, and `--strict` makes it
  fatal.
* `strict` CHANGES NOTHING HERE: openDox's validator has no warnings to
  harden. `search_from` IS NOT READ: the schemas are package data, so nothing
  is searched for, and no path can make the validator reachable or not. No
  subprocess runs, so there is no dependency remedy (`dependency_remedy` is
  None).
* THE WORKBENCH MANIFEST'S TWO VALIDATOR RULES. Its schema says of two rules
  that it cannot state them, and leaves them to the validator. The consumer's
  script checked them in single-file mode, and they are carried here, under
  its identifiers, so routing `validate_manifest` to openDox's validator drops
  neither (the holder's decision, 2026-09-28). `workbench-pinned-not-checked`:
  every `recipe.pinned` keyword is also in `recipe.checked`.
  `workbench-candidate-overlap`: no `recipe.new_candidates` document is
  already a member or excluded.

IMPORT WEIGHT. `opendox.generator_seam`, `opendox.projection_seams` and the
standard library. So this module imports with no extra installed and no
sibling present. `opendox.validator` (the standard library and
`opendox.contracts`) and PyYAML are imported when a validation runs.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import stat
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from opendox import generator_seam, projection_seams

__all__ = ["CORPUS_ROOT", "CorpusRoot", "OWN_KINDS", "OwnValidator",
           "SYNTAX_RULE", "SnapshotNotWritable", "VALIDATORS", "WORKBENCH_RULES",
           "WRITER", "Writer"]

#: The workbench manifest's kind, `opendox.workbench.KIND`, restated because
#: `workbench` imports PyYAML and this module must import with nothing extra.
#: `tests/test_projection_seams.py` holds the two spellings together.
WORKBENCH_KIND = "ideation-workbench"

#: The kinds openDox's own validator answers for at the validator lookup,
#: which the entry points register it under: the neutral snapshot every
#: generate verb writes with openDox's own generator, and the workbench
#: manifest `workbench.save()` validates. `opendox.validator` validates the
#: doxBench wire kinds too, and they reach it through their own seam
#: (`serve_wire.register_doxbench_validators`, T085), not through this one.
OWN_KINDS: tuple[str, ...] = (generator_seam.NEUTRAL_SNAPSHOT_KIND, WORKBENCH_KIND)

#: How each own kind is written, and so how its document is read.
_SYNTAX: dict[str, str] = {generator_seam.NEUTRAL_SNAPSHOT_KIND: "JSON",
                           WORKBENCH_KIND: "YAML"}

#: The rule a document breaks when it cannot be read as JSON, or as YAML, as
#: its kind is written, numbers included (`_exact`). It is the adapter's, and no contract's: a contract's rules are
#: about a document that could be read.
SYNTAX_RULE = "document-syntax"

#: The workbench manifest's two validator rules, which its schema leaves to
#: the validator, under the identifiers the consumer's script gave them.
WORKBENCH_RULES: tuple[str, ...] = ("workbench-pinned-not-checked",
                                    "workbench-candidate-overlap")


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


class _NotJSON(ValueError):
    """A JSON text holds what JSON does not: a key given twice, NaN or an
    infinity."""


def _refuse_constant(name: str) -> Any:
    raise _NotJSON(f"{name} is not JSON")


def _exact(text: str, value: float) -> float:
    """`value`, the float a number literal `text` was read as, once it is
    proved to be the number written: finite, and not rounded.

    * FINITE. `1e999` is a valid JSON number that Python reads as an infinity
      without calling `parse_constant`, and JSON carries no infinity (Copilot
      at openDox-code#68 21e4723f, r4139840593).
    * NOT ROUNDED. A float holds what binary64 holds, the precision JSON
      readers share (RFC 8259 section 6), so `1.0000000000000001` reads as
      `1.0`, and would then meet `const: 1` (Copilot at openDox-code#68
      69ca0e27, r4139937566). A literal whose value differs from the
      shortest spelling of the float read from it is refused, since no
      verdict over the float would be a verdict over the number written.
      `0.1`, `2.50` and `1E2` read as written, and so does every float
      openDox's own writer writes, which is the float's own shortest
      spelling. A literal this cannot compare (a YAML sexagesimal) keeps its
      float."""
    if not math.isfinite(value):
        raise _NotJSON(f"the number {text[:40]} reads as {value}, and JSON "
                       "carries no infinity or NaN")
    try:
        written = Decimal(text.replace("_", ""))
    except InvalidOperation:
        return value
    if Decimal(repr(value)) != written:
        raise _NotJSON(f"the number {text[:40]} cannot be read as written: "
                       f"the precision JSON readers share holds it as {value!r}")
    return value


def _json_float(text: str) -> float:
    """A JSON number with a fraction or an exponent (`parse_float`)."""
    return _exact(text, float(text))


def _refuse_repeated_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise _NotJSON(f"the key {key!r} is given twice in one object")
        document[key] = value
    return document


def _names(value: Any) -> list[str]:
    """A list's string entries, once each, in order. Anything else answers
    none: its shape is the schema's to judge, and these rules only compare.

    Linear: the schema bounds none of the three lists, so membership is a
    set's, and the list only keeps the order (Copilot at openDox-code#68
    09cd1e8a, r4139734444)."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str) and item not in seen:
            seen.add(item)
            names.append(item)
    return names


#: How many names a rule's detail quotes before it says how many more, and
#: how much of each name it quotes.
_QUOTED = 10
_NAME_CHARS = 80


def _quoted(names: list[str]) -> str:
    """`names` as a detail quotes them: the first few, each cut to a readable
    length, and a count of the rest, so one violation stays one readable line.
    The schema bounds neither the lists nor their strings (Copilot at
    openDox-code#68 21e4723f, r4139769791)."""
    shown = repr([name if len(name) <= _NAME_CHARS else name[:_NAME_CHARS - 1] + "…"
                  for name in names[:_QUOTED]])
    return shown if len(names) <= _QUOTED else f"{shown[:-1]}, and {len(names) - _QUOTED} more]"


def _documents(entries: Any) -> set[str]:
    """The `document` of each entry of a members or excluded list."""
    if not isinstance(entries, list):
        return set()
    return {entry["document"] for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("document"), str)}


class OwnValidator:
    """openDox's own validator for ONE of its kinds, behind the validator
    lookup's protocol (plan 034's T058; this module's docstring)."""

    #: No subprocess runs, so no dependency to install would make it run.
    dependency_remedy = None

    def __init__(self, kind: str) -> None:
        if kind not in _SYNTAX:
            raise ValueError(
                f"openDox's own validator is bound only to openDox's own kinds "
                f"{list(_SYNTAX)}, each read as it is written, not {kind!r}")
        self.kind = kind
        self.syntax = _SYNTAX[kind]

    def __repr__(self) -> str:
        return f"<openDox's own validator for {self.kind!r}>"

    def _unavailable(self, reason: str) -> projection_seams.ValidationResult:
        return projection_seams.ValidationResult(
            False, -1, "", "", "opendox.validator",
            projection_seams.VALIDATOR_UNAVAILABLE, reason)

    def _read(self, text: str) -> Any:
        """The document, parsed as its kind is written. Raises `ValueError`
        (a YAML error included) where it is not."""
        if self.syntax == "JSON":
            return json.loads(text, parse_constant=_refuse_constant,
                              parse_float=_json_float,
                              object_pairs_hook=_refuse_repeated_keys)
        import yaml

        class _Loader(yaml.SafeLoader):
            """PyYAML's safe loader, whose floats are proved as the snapshot's
            JSON numbers are (`_exact`): finite, and not rounded."""

        def construct_float(loader, node):
            return _exact(str(node.value),
                          yaml.SafeLoader.construct_yaml_float(loader, node))

        _Loader.add_constructor("tag:yaml.org,2002:float", construct_float)
        try:
            return yaml.load(text, Loader=_Loader)  # noqa: S506 - a SafeLoader subclass
        except yaml.YAMLError as exc:
            raise ValueError(" ".join(str(exc).split())) from exc

    @staticmethod
    def _workbench_rules(document: Any) -> list:
        """The manifest's two validator rules (this module's docstring)."""
        from opendox.validator import Violation

        if not isinstance(document, dict) or not isinstance(document.get("recipe"), dict):
            return []
        recipe = document["recipe"]
        found = []
        checked = set(_names(recipe.get("checked")))
        stray = [name for name in _names(recipe.get("pinned")) if name not in checked]
        if stray:
            found.append(Violation(
                WORKBENCH_RULES[0], ("recipe", "pinned"), "workbench-rule",
                f"pinned keyword(s) {_quoted(stray)} are not in checked: every pinned "
                "keyword MUST also be checked"))
        placed = _documents(document.get("members")) | _documents(document.get("excluded"))
        overlap = [name for name in _names(recipe.get("new_candidates")) if name in placed]
        if overlap:
            found.append(Violation(
                WORKBENCH_RULES[1], ("recipe", "new_candidates"), "workbench-rule",
                f"new_candidates {_quoted(overlap)} already appear in members or "
                "excluded: a new candidate is a document the set has not "
                "placed yet"))
        return found

    def validate(self, path: Path | str, *, strict: bool = False,
                 search_from: tuple = ()) -> projection_seams.ValidationResult:
        """Validate the document at `path` as this validator's kind. `strict`
        and `search_from` are the protocol's, and change nothing here."""
        from opendox import validator as own

        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            return self._unavailable(
                f"the document could not be read ({exc.strerror or exc}), so "
                "nothing was judged")
        try:
            kind_validator = own.validator_for(self.kind)
        except (own.ValidatorUnavailable, own.UnknownKind) as exc:
            return self._unavailable(" ".join(str(exc).split()))
        except OSError as exc:
            # A packaged file that is present but cannot be read (its
            # permissions, say). `opendox.contracts` refuses a MISSING copy
            # as `CopyRefused`, and any other read failure reaches here as
            # itself. It is still "the check could not be performed", so the
            # verb reports it, and `--strict` fails, without a traceback
            # (Copilot at openDox-code#68 09cd1e8a, r4139734412).
            return self._unavailable(
                f"openDox's packaged contracts could not be read "
                f"({type(exc).__name__}: {exc.strerror or exc}), so nothing "
                "was judged")
        ran = (f"opendox.validator, over its packaged copy {kind_validator.copy_id} "
               f"(sha256 {kind_validator.digest[:12]})")
        try:
            document = self._read(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            violations = [own.Violation(
                SYNTAX_RULE, (), "syntax",
                f"the document cannot be read as {self.syntax}, which is how "
                f"a {self.kind!r} document is written: "
                f"{' '.join(str(exc).split()) or type(exc).__name__}")]
        else:
            violations = kind_validator.violations(document)
            if self.kind == WORKBENCH_KIND:
                violations += self._workbench_rules(document)
        if not violations:
            return projection_seams.ValidationResult(
                True, 0, f"{self.kind}: 0 violations, by {ran}\n", "", ran)
        lines = own.report(violations)
        lines.append(f"{len(violations)} violation(s) of the {self.kind} "
                     f"contract, by {ran}")
        return projection_seams.ValidationResult(
            False, 1, "\n".join(lines) + "\n", "", ran)


CORPUS_ROOT = CorpusRoot()
WRITER = Writer()
VALIDATORS: dict[str, OwnValidator] = {kind: OwnValidator(kind) for kind in OWN_KINDS}
