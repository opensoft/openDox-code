"""`generate` + (later) `generate-and-open` action subcommands (plan "cli.py";
change task 3.3).

Path-agnostic argparse front-end: `--output`-style arguments, no baked-in
snapshot path (the aggregation nightly lane wires the committed path). The
`generate` subcommand (this wave, T006) regenerates the deterministic snapshot
from the working tree, writes it through the interactivity boundary, and
validates it against the pinned openxFactory validator. The `generate-and-open`
subcommand (T012, US2) will layer `serve.py` + browser open on top of the same
generation path.

Runnable both as a module (`python3 -m ideation_dashboard.cli`) and as a script
(`python3 scripts/ideation_dashboard/cli.py`); it self-inserts `scripts/` onto
the import path so the sibling `doc_health` package resolves either way.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import webbrowser
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

if __name__ == "__main__":
    # THE ENTRYPOINT RUNS THE PACKAGE'S COPY OF THIS MODULE, NEVER THIS ONE,
    # AND HANDS OVER BEFORE THE REST OF THIS FILE EXECUTES.
    #
    # Run as a script (`python3 scripts/ideation_dashboard/cli.py ...`) or with
    # `-m`, this file is loaded under the name `__main__` — a module object of
    # its own, with its own `RepoRootRefused` and `GeneratedAtRefused` classes,
    # while the column modules beside it reach the spine through `_core()`,
    # which resolves the core module of the PACKAGE they were imported under. A
    # refusal raised inside a moved verb would then be an instance of the other
    # copy's class, and the `except` clauses in `main` below could not catch it:
    # both documented invocations would degrade from the deliberate
    # operator-facing message on stderr to an unhandled traceback, which is
    # exactly the presentation `RepoRootRefused`'s own docstring exists to
    # guarantee.
    #
    # Dispatching into the package copy means only one module object ever runs
    # anything — one set of exception classes, one set of module-level names to
    # patch — so the split is invisible here too, as it is everywhere else.
    #
    # This block sits ABOVE the imports, not at the foot of the file, for a
    # second reason: run as a script there is no package at all (`__package__`
    # is empty), so this copy could not name its own columns relative to itself.
    # Handing over here means the body below only ever executes as a package
    # module — under whichever of the spellings imported it — which is what lets
    # every line beneath this one bind its siblings relatively.
    from opendox import cli as _package_cli

    sys.exit(_package_cli.main())

# The SUBCOMMAND EXTENSION POINT (`split-opendox-two-layer-product` § 2.4,
# design § D2). A neutral module at the top of `scripts/`, belonging to neither
# package and importing neither, for the same three reasons `output_boundary`
# and `corpus_adapter` sit there. Spelled as a bare top-level import, like
# `boundary.py` spells `output_boundary`.
import subcommand_extension  # noqa: E402

from opendox import actor_identity as actor_mod  # noqa: E402
from opendox import authoring as authoring_mod  # noqa: E402
from opendox import branch_session as branch_session_mod  # noqa: E402
from opendox import doxbench_install as install_mod  # noqa: E402
from opendox import doxbench_knowledge as knowledge_mod  # noqa: E402
# THE GATE PRIMITIVES, THROUGH THEIR SEAM (plan 034 T084; #1144 4.3, R1Q10
# (a)). This was `consumer_reach.gate_console`, a late stand-in over openXdox's
# `gate_console` that still raised where openXdox was absent. `gate_mod.X` now
# reads the registration current at `column_seams.gate` when it runs, a host's
# or openDox's own default, which `build_parser()` and `main()` register.
# Stdlib-only, so this adds no reach.
from opendox import column_seams  # noqa: E402
gate_mod = column_seams.gate.proxy  # noqa: E402
from opendox import serve as serve_mod  # noqa: E402
from opendox import workbench as workbench_mod  # noqa: E402
# THE HOME-CORPUS SEAM'S DEFAULT (4.1a; plan 034 T022) -- see
# `_default_home_factory` and `corpus_adapter.register_default_home(...)`
# below, beside `build_parser()`.
# Neither module names `openxdox` or `ideation_dashboard`, so this import adds
# no reach: `corpus_adapter` is stdlib-only (F4.1's own scan proves it), and
# `local_git_adapter` names only `opendox.runtime.config`,
# `opendox.corpus_adapter` and `opendox.doxbench_intake` (itself stdlib-only,
# with the `doxbench_binding` it reads; plan 034 T082) besides the stdlib.
from opendox import corpus_adapter  # noqa: E402
from opendox.runtime import local_git_adapter  # noqa: E402
# THE INSTALL SHAPE (plan 034 T070; #1144 13.4-13.6): `generate-and-open`
# resolves `--local` against `OPENDOX_INSTALL_MODE` here, before it generates
# or serves anything. Stdlib-only, like `local_git_adapter` above, which
# already imports it, so this adds no reach and no import weight.
from opendox.runtime import config as runtime_config  # noqa: E402
# THE LOCAL INSTALL'S BUNDLED POSTGRESQL SERVER (plan 034 T072; #1144 13.1,
# R1Q16 (i)-(iv)): started as THIS process's child by `generate-and-open
# --local`, and stopped with it. Stdlib-only at import, like `runtime_config`;
# the driver is imported when the server is started, never here.
from opendox.runtime import bundle as bundle_mod  # noqa: E402
from opendox.runtime import migrations as migrations_mod  # noqa: E402
# THE CONSOLE TOKEN'S PRIVATE COPY (plan 034 T104): on a standalone plane the
# token is not on `/capabilities`, and `generate-and-open` opens the page
# through a 0600 copy in the state directory instead. Stdlib-only.
from opendox import console_access  # noqa: E402
from opendox.boundary import (  # noqa: E402
    BoundaryViolation, HumanGate, OutputBoundary,
)
# THE CORPUS-ROOT PREDICATE, THE SNAPSHOT WRITER AND THE VALIDATOR LOOKUP, AS
# SEAMS (plan 034 T055; #1144 5.5 and 4.3 in part; R1Q10 (a), openxFactory#656
# comment 5850003126). BUILD slice 2b bound them, and the snapshot generator,
# to late `consumer_reach` stand-ins over openXdox's `corpus_root`, `snapshot`
# and `generator`, so a lone openDox refused at the first generate. Each is now
# read from a declared seam (`opendox.projection_seams`, and the generator seam
# for the generate operation), at the moment it is used, where either openDox's
# own default or a host's contribution is registered. The entry points below
# register the defaults where no host has. `is_rfc3339_datetime` is not a seam:
# it is the neutral contract's own date-time rule, and openDox owns it.
from opendox import projection_seams  # noqa: E402
# openDox's own defaults for the two doxBench seams (plan 034 T085), which
# the entry points below register the same way. Importing it registers
# nothing.
from opendox import doxbench_defaults  # noqa: E402
from opendox.rfc3339 import is_rfc3339_datetime  # noqa: E402

# THE COMPOSITION POINT, BOUND AT LAST (§ 4.3; RULED ASK-2 option (2),
# openxFactory#656 comment 5628886636). `build_parser()` below reads
# `profile_openxfactory.SUBCOMMAND_EXTENSIONS` and NOTHING bound that name: the
# § 3 carve files `profile_openxfactory.py` as `not_moved / deleted_at_carve`
# and its deferred import went with it, so `build_parser()` raised `NameError:
# profile_openxfactory` for every caller (the slice-2b finding, comment
# 5633826227). The name now binds to the LAZY PROXY beside this module: nothing
# resolves here, at import time; the FIRST attribute read resolves the profile
# the host registered at process start
# (`opendox.domain_profile.register(...)`, docs/profile-registration-runbook.md)
# or, where no host did, openDox's own default, which `build_parser()` and
# `main()` register first (R1Q3 (a), openxFactory#656 comment 5817152735). The
# read still refuses, naming that call, where nothing is registered at all. The
# READ at :927 is unchanged — this is a binding, not a rewrite of the
# composition point.
#
# THE `build_parser()` DOCSTRING BELOW NOW DESCRIBES THE CURRENT COMPOSITION
# POINT, not the in-tree profile the § 3 carve inherited. RULED R1Q22 (a)
# (openxFactory#656 comment `5817152735`) settled that no per-slice
# declared-edit act precedes an arc edit to a carved file, which is what held
# this correction back before (RULED OQ-1). Plan 034 T038 makes it: T038 is
# phase 1's last task to touch this file's own framing (`cli.py`'s
# single-writer order, tasks.md § "Phase 1 writer slices"), and it needs the
# docstring to say where the runtime verbs actually reach `opendox`, which is
# through the default profile below, not through a rewrite of this file.
from opendox.profile_proxy import profile_openxfactory  # noqa: E402
# openDox's OWN default profile, and the registry an entry point registers it
# in (R1Q3 (a)). Importing either registers nothing: `build_parser()` and
# `main()` below make the registration, and only where no host has made one.
from opendox import default_profile, domain_profile  # noqa: E402
# openDox's OWN snapshot generator, and the generator seam an entry point
# registers it at (5.4; plan 034 T052). Importing either registers nothing:
# `build_parser()` and `main()` below register it, only where no host has.
from opendox import default_generator, generator_seam  # noqa: E402

# THE MODULES THE § 2.4 SPLIT CREATED ARE NAMED RELATIVELY, and they are the
# only imports in this file that are.
#
# `scripts/__init__.py` exists, so this tree is importable BOTH as
# `ideation_dashboard.cli` and as `scripts.ideation_dashboard.cli`
# (`tests/import_scan.py`'s header states the rule in writing: both spellings
# are always the caller's job, and a rule that knows one of them is a rule with
# a hole in it). Each spelling is a module object of its own, with its own
# `RepoRootRefused` and `GeneratedAtRefused`. Naming the columns absolutely
# would mean a caller who imported this file under one spelling ran verbs bound
# to the other — and a refusal raised through THAT copy's exception classes
# would escape `main`'s `except` clauses uncaught, which is the same defect the
# `__main__` bootstrap above closes for the script and `-m` invocations.
#
# A relative import is resolved against the package THIS module was imported
# under, so the core, its three columns and the composition point are always one
# coherent set: whichever spelling reaches the CLI gets columns whose `_core()`
# resolves back to the very module object that is running.

WEB_DIR = Path(__file__).resolve().parent / "web"

# The shape a correct invocation has, shown in the `--repo-root` refusal below.
# PLACEHOLDERS only — nobody's home directory and no container path belongs in a
# message whose whole job is to end a path-namespace confusion — and only flags
# this parser really accepts.
_GENERATE_SHAPE = (
    "python3 src/opendox/cli.py generate-and-open \\\n"
    "  --repo-root <path to the corpus checkout> \\\n"
    "  --repository <that checkout's repository id>"
)


class RepoRootRefused(Exception):
    """`--repo-root` does not name a corpus checkout, as the REGISTERED
    corpus-root predicate decides (`projection_seams.corpus_root`).

    Raised from the ONE shared generation chokepoint, BEFORE any scan and before
    the `OutputBoundary` write, so no snapshot file exists to be mistaken for a
    result; `main` reports it on stderr and exits non-zero. Carries the whole
    operator-facing refusal as its message."""


def _refuse_non_corpus_repo_root(args: argparse.Namespace) -> None:
    """Raise `RepoRootRefused` unless `--repo-root` could be a corpus checkout."""
    refusal = projection_seams.corpus_root.current().corpus_root_refusal(
        args.repo_root, shape=_GENERATE_SHAPE)
    if refusal is not None:
        raise RepoRootRefused(refusal)


class GeneratedAtRefused(Exception):
    """`--generated-at` was given something that is not an RFC 3339 date-time.

    REFUSED, not degraded — deliberately unlike every other timestamp path in
    this package. `RealGitDates.commit_date` returns None on any failure and the
    stamp is simply omitted, which is right for a value the run tried to
    DISCOVER. This one was TYPED, and the only reason to type it is that the
    scanned tree cannot supply it (the sealed source artifact
    `add-nightly-dashboard-refresh` hands the child is not a git checkout). So
    degrading here would drop the anchor in silence and produce the very
    snapshot the flag exists to prevent: `generated_at` is OPTIONAL in the
    snapshot contracts (the neutral `opendox-snapshot` schema's and the
    governed one's alike), so even `--strict` would pass, the image would ship,
    and the served plane would lose its freshness stamp with nothing anywhere
    saying why."""


class SourceOptionRefused(Exception):
    """`--project-register` or `--possibles` was given an EMPTY path.

    REFUSED, fail closed, on the holder's decision of 2026-09-28 (plan 034
    T055). This used to be decided by testing the value for truth, which
    DROPPED an empty one: the option was silently not passed, and the run went
    on as if it had never been given. Resolving it instead, as
    `Path("").resolve()`, would name the CURRENT DIRECTORY as the register to
    read. Neither is what a caller who typed the option asked for, so an empty
    value ends the run, before anything is generated or written. An option
    that is not given at all is `None` and is still simply not passed."""


def _source_option(args: argparse.Namespace, attr: str, flag: str) -> Path | None:
    """The file a `--project-register`/`--possibles` option names, resolved;
    `None` when the option was not given; `SourceOptionRefused` when it was
    given an empty path (see that class)."""
    value = getattr(args, attr, None)
    if value is None:
        return None
    if value == "":
        raise SourceOptionRefused(
            f"{flag} was given an empty path. It is refused: dropping it would "
            f"ignore the option without a word, and resolving it would read "
            f"the current directory. Name the file to read, or leave {flag} out")
    return Path(value).resolve()


def _refuse_empty_source_options(args: argparse.Namespace) -> None:
    """Raise `SourceOptionRefused` if either source option is an empty path."""
    _source_option(args, "project_register", "--project-register")
    _source_option(args, "possibles", "--possibles")


def _refuse_malformed_generated_at(args: argparse.Namespace) -> None:
    """Raise `GeneratedAtRefused` unless `--generated-at`, when given, is an
    RFC 3339 date-time (`opendox.rfc3339.is_rfc3339_datetime`, the neutral
    snapshot contract's `generated-at-is-rfc3339` rule for
    `generation.generated_at`)."""
    value = getattr(args, "generated_at", None)
    if value is None or is_rfc3339_datetime(value):
        return
    raise GeneratedAtRefused(
        f"--generated-at is not an RFC 3339 date-time: {value!r}\n"
        f"  required: a full date, an explicit time and an explicit offset — "
        f"e.g. 2026-09-04T01:23:45Z or 2026-09-04T01:23:45+00:00\n"
        f"  the value is recorded in the snapshot EXACTLY as given (it is an "
        f"anchor copied from elsewhere, never normalised), which is why a "
        f"malformed one is refused here instead of repaired\n"
        f"  a sealed-source run passes its manifest's source committer "
        f"timestamp, the `git show -s --format=%cI` of the sealed revision")


def _generate_and_write(args: argparse.Namespace, output: Path) -> tuple[dict, Path]:
    """Generate the deterministic snapshot from the working tree and write it
    through the interactivity boundary (the output file is the whole declared
    allowlist, rooted at its own directory). Shared by `generate` and
    `generate-and-open`.

    A `--repo-root` that cannot be a corpus checkout is REFUSED here — the ONE
    guard both verbs pass through, ahead of the generation and the write, because
    an empty snapshot that exits 0 is indistinguishable from an honest one (T092;
    the registered corpus-root predicate decides). A malformed `--generated-at`
    is refused in the same place and for the same reason, one anchor over: both
    verbs, ahead of the write, so no snapshot file can survive a refused run.

    THE GENERATION AND THE WRITE GO THROUGH THE SEAMS (plan 034 T055). The
    snapshot is generated by whichever generator is registered NOW
    (`generator_seam.generate`, which looks it up on each call), and it is
    written by the registered writer. An option given as `None` is not passed,
    so an unset `--project-register` or `--possibles` asks nothing of a
    generator that declares no such input. An EMPTY one is refused as
    `SourceOptionRefused`, never dropped and never read as the current
    directory (the holder, 2026-09-28). A given one that the registered
    generator does not declare is refused as `GeneratorInputRefused`, before
    anything is generated or written, and `main` reports it."""
    _refuse_non_corpus_repo_root(args)
    _refuse_malformed_generated_at(args)
    _refuse_empty_source_options(args)
    repo_root = Path(args.repo_root).resolve()
    snapshot = generator_seam.generate(
        repo_root,
        args.repository,
        source_revision=args.source_revision,
        generated_at=args.generated_at,
        project_register_source=_source_option(args, "project_register", "--project-register"),
        possibles_source=_source_option(args, "possibles", "--possibles"),
    )
    boundary = OutputBoundary(output.parent, [output.name])
    written = projection_seams.writer.current().write_snapshot(
        snapshot, output, boundary)
    return snapshot, written


def _report(snapshot: dict, written: Path, repo_root: Path) -> None:
    """What a generate verb says it wrote.

    The neutral snapshot (`opendox-snapshot`) has no project and no project
    group, so its line names its kind instead, rather than reporting a grouping
    its contract does not carry. Every other kind's line is unchanged.

    A REGISTERED GENERATOR OWES THE SEAM ONLY ITS DECLARED `kind` AND AN INTEGER
    `schema_version` (`generator_seam`), so nothing else is indexed here as if
    every contract carried it (Copilot at openDox-code#59 96f18c45,
    r4136863311). A field the snapshot lacks, or carries in another shape, is
    reported `<absent>`. The snapshot is already written, and whether its own
    contract required the field is its validator's to say, which runs next."""
    stats = _stats(snapshot)
    generation = snapshot.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    repository = snapshot.get("repository", "<absent>")
    print(f"wrote {written}")
    if snapshot.get("kind") == generator_seam.NEUTRAL_SNAPSHOT_KIND:
        print(f"  repository={repository} kind={snapshot['kind']}")
    else:
        print(f"  repository={repository} "
              f"project={snapshot.get('project', '<ungrouped>')} "
              f"project_group={snapshot.get('project_group', '<none>')}")
    print(f"  source_revision={generation.get('source_revision', '<absent>')}")
    # Printed even when absent: a missing freshness stamp used to be invisible
    # (the schema makes it optional, so nothing downstream complains), and a run
    # that meant to pin one needs to see whether it landed.
    print(f"  generated_at={generation.get('generated_at', '<absent>')}")
    print(f"  documents={stats['documents']} clusters={stats['clusters']} "
          f"possibles={stats['possibles']} staged_topics={stats['staged_topics']} "
          f"changes={stats['changes']} keywords={stats['keyword_index']}")
    _warn_on_empty_projection(stats, repo_root)


def _warn_on_empty_projection(stats: dict[str, int], repo_root: Path) -> None:
    """A projection that produced ZERO documents WARNS loudly and does not fail.

    The decision, deliberately: an empty corpus is LEGAL — a fresh repository, a
    domain factory before its first document — and a hard failure here would make
    an honestly-empty tree unusable, which is a worse defect than the one being
    fixed. But the guard in `_generate_and_write` proves only that the tree COULD
    be scanned, not that it is the tree the human meant: a checkout whose
    `ideation/` exists but holds nothing passes it, and the dashboard then renders
    the same empty funnel it renders for an honest one, over copy that reads as a
    legitimate result. So the emptiness is stated on stderr, with the roots that
    let the path through, and the human decides.

    The roots are the REGISTERED corpus-root predicate's (`SCANNED_ROOTS`).
    openDox's own predicate names none, since its corpus is a whole repository,
    and then the line says what it did accept instead."""
    if stats["documents"]:
        return
    roots = tuple(projection_seams.corpus_root.current().SCANNED_ROOTS)
    present = ", ".join(f"{root}/" for root in roots
                        if (repo_root / root).is_dir())
    print(f"  WARNING: ZERO documents were projected from {repo_root} — this "
          f"snapshot is EMPTY", file=sys.stderr)
    if present:
        print(f"    it was accepted as a corpus checkout because it holds {present}, "
              f"but nothing under those roots produced a governed document",
              file=sys.stderr)
    else:
        print("    it was accepted as a corpus checkout, but nothing in it was "
              "read as a document", file=sys.stderr)
    print("    an empty corpus is legal, so this is a WARNING, not a failure — but "
          "the usual cause is a --repo-root naming the wrong tree, and the "
          "dashboard's empty funnel reads the same either way", file=sys.stderr)


class _RepeatedKey(ValueError):
    """A JSON object in the written snapshot gives one key twice."""


def _refuse_repeated_keys(pairs: list[tuple[str, object]]) -> dict:
    document: dict = {}
    for key, value in pairs:
        if key in document:
            raise _RepeatedKey(f"the key {key!r} twice in one object")
        document[key] = value
    return document


def _written_kind(written: Path) -> str | None:
    """The `kind` the written snapshot declares, which chooses its validator,
    or None where the file declares none it can be read by.

    A KEY GIVEN TWICE IS REFUSED, `_RepeatedKey` (plan 034 T058; Copilot at
    openDox-code#68 09cd1e8a, r4139769819). Python's `json` keeps the last
    of two, so `"kind": "opendox-snapshot", "kind": "unknown"` chose no
    registered validator, and an ordinary run then warned and exited 0,
    though no reader could say which contract the file meant. Such a
    document has no one meaning, whatever its kind, so no validator is chosen
    for it. Which constants or numbers a contract admits is the chosen
    validator's to judge, since none of them makes the kind ambiguous."""
    try:
        document = json.loads(written.read_text(encoding="utf-8"),
                              object_pairs_hook=_refuse_repeated_keys)
    except _RepeatedKey:
        raise
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    kind = document.get("kind") if isinstance(document, dict) else None
    return kind if isinstance(kind, str) and kind else None


def _validate_by_kind(written: Path, kind: str, *, strict: bool,
                      search_from: tuple[Path, ...]):
    """`(validator, result)` for the written snapshot, by its KIND
    (`projection_seams.validators`, plan 034 T055).

    The validator registered for the snapshot's own kind runs it, and none
    other: its generator's declared contract is that kind, so openDox's own
    validator checks openDox's neutral snapshot and a host's checks the host's.
    It is handed the two roots a search may start from, the OUTPUT path's
    directory first and the SERVED CHECKOUT second (T092 acceptance sweep,
    defect 8, which is why the order is kept). No validator registered for the
    kind is VALIDATOR UNAVAILABLE, sub-case "nothing to run", and the lookup's
    own refusal is the reason given, whole, on one line: it ends with the call
    that registers a validator, which is the remedy."""
    try:
        validator = projection_seams.validators.for_kind(kind)
    except projection_seams.ValidatorNotRegistered as exc:
        return None, projection_seams.ValidationResult(
            False, -1, "", "", None, projection_seams.VALIDATOR_UNAVAILABLE,
            " ".join(str(exc).split()))
    return validator, validator.validate(written, strict=strict,
                                         search_from=search_from)


def _warn_validator_not_found(written: Path, repo_root: Path, kind: str,
                              result, *, registered: bool) -> None:
    """VALIDATOR UNAVAILABLE, sub-case "nothing to run".

    NOT routine: the snapshot went unvalidated however good the corpus was.
    The old one-liner ("no reachable openxFactory checkout") read as routine
    while quietly meaning "unvalidated", and pointed at a checkout that was
    present and fine, which is exactly where it sent the T092 pass. So this
    says which of the two things happened, and then gives the reason:

    * NOTHING IS REGISTERED FOR THE KIND (`registered` false). The validator
      lookup is the process's own registry, so no path can make a validator
      reachable. Moving the output or the checkout would change nothing, and
      the message names neither. The lookup's refusal says what registers one.
    * THE VALIDATOR REGISTERED FOR THE KIND REACHED NO VERDICT. It was offered
      both roots to search from, the OUTPUT path's directory first and the
      served checkout second (T092 acceptance sweep, defect 8), so the message
      names BOTH and blames neither on its own. Its own reason follows."""
    print("  validation SKIPPED — this snapshot was NOT checked against the "
          "pinned schema", file=sys.stderr)
    if registered:
        print(f"    the validator registered for kind {kind!r} reached no "
              f"verdict. It was offered {written.parent} (the OUTPUT path) "
              f"first, then {repo_root} (--repo-root), to search from",
              file=sys.stderr)
    if result.unavailable_reason:
        print(f"    {result.unavailable_reason}", file=sys.stderr)


def _warn_validator_could_not_run(result, validator) -> None:
    """VALIDATOR UNAVAILABLE, sub-case "found it, could not run it".

    The validator's OWN words are relayed verbatim rather than paraphrased: it
    is the thing that knows which dependency it wanted, and quoting it keeps
    this warning correct when that message changes. What we add is the part it
    cannot know — WHICH interpreter it was run under (a separate `sys.executable`
    process, so the libraries have to exist wherever the dashboard runs), the
    remedy the registered validator declares (`dependency_remedy`), and the
    reassurance that the corpus is not the accused."""
    print("  validation SKIPPED — this snapshot was NOT checked against the "
          "pinned schema", file=sys.stderr)
    print(f"    the validator was found ({result.validator}) but could not run: "
          f"{result.unavailable_reason}", file=sys.stderr)
    for line in (result.stderr or result.stdout).strip().splitlines()[-10:]:
        print(f"      {line}", file=sys.stderr)
    remedy = getattr(validator, "dependency_remedy", None)
    if remedy:
        print(f"    it runs under {sys.executable} — a SEPARATE interpreter "
              f"from whatever installed the validator — and the usual cause is "
              f"that this one lacks its libraries. Remedy:", file=sys.stderr)
        print(f"      {sys.executable} -m {remedy}", file=sys.stderr)


#: One broken rule, as a validator's report names it: `[<rule>] <where>:
#: <detail>`, the line `opendox.validator.Violation.line()` prints.
_RULE_LINE = re.compile(r"^\[(?P<rule>[^\[\]\s]+)\] (?P<rest>.+)$")

#: How many of a report's other lines (its summary, or a validator's own
#: words where it names no rule) are printed.
_REPORT_TAIL = 20

#: How many places each broken rule is shown at: the first on the rule's own
#: line, and the next ones beneath it. A rule broken at more places than this
#: says how many more, so its count stays exact and the report stays short.
_PLACES_SHOWN = 5


def _report_non_conformance(written: Path, result) -> None:
    """NOT CONFORMANT — the validator ran, reached a verdict, and rejected the
    snapshot. The one thing this message must never be mistaken for is the
    warning above it, so it says whose fault it is out loud and prints the
    findings themselves; "1 error(s)" alone told a human nothing he could act
    on.

    EVERY BROKEN RULE, ONCE, WITH ITS COUNT (plan 034 T084; RULED
    openxFactory#656 `5920216845`, item 3, *"Show every rule, grouped
    (Recommended)"*). This printed the validator's LAST 20 LINES, so a
    snapshot that broke one rule a hundred times and a second rule once
    showed twenty copies of the first and never named the second. Now each
    rule id the report names is printed ONCE, on a line of its own,
    `<count> × [<rule>] <where>: <detail>`, in the order the validator found
    them, with where it is first broken. The next places it is broken follow
    beneath it, without the id, up to `_PLACES_SHOWN` in all, because one rule
    can be broken in different ways (a missing key, then another), and a
    count beside the first place alone would read as that place repeated.
    The report's other lines (the validator's summary) follow. A validator
    whose output names no rule id has nothing to group, so its own last lines
    are printed, as before."""
    print(f"  validation FAILED — the pinned validator REJECTED {written}. This "
          f"is the SNAPSHOT, not the environment: the validator ran fine and "
          f"found the data non-conformant.", file=sys.stderr)
    lines = (result.stdout or result.stderr).strip().splitlines()
    places: dict[str, list[str]] = {}
    others: list[str] = []
    for line in lines:
        named = _RULE_LINE.match(line.strip())
        if named is None:
            others.append(line)
            continue
        places.setdefault(named["rule"], []).append(named["rest"])
    if places:
        total = sum(len(where) for where in places.values())
        print(f"    {total} violation(s) of {len(places)} rule(s), each rule "
              f"once, with its count and where it is broken:", file=sys.stderr)
        for rule, where in places.items():
            print(f"    {len(where)} × [{rule}] {where[0]}", file=sys.stderr)
            for place in where[1:_PLACES_SHOWN]:
                print(f"          {place}", file=sys.stderr)
            if len(where) > _PLACES_SHOWN:
                print(f"          … and {len(where) - _PLACES_SHOWN} more of "
                      "this rule", file=sys.stderr)
    for line in others[-_REPORT_TAIL:]:
        print(f"    {line}", file=sys.stderr)


def _validate(written: Path, args: argparse.Namespace, *,
              continues: str = "this command continues and exits 0") -> int:
    """Post-render validation, with THREE outcomes
    (`projection_seams.VALIDATED`, `NOT_CONFORMANT`, `VALIDATOR_UNAVAILABLE`),
    by the validator registered for the written snapshot's own KIND.

    A snapshot the validator REJECTS still fails the command. A validator that
    could not RUN warns loudly and returns 0 — for `generate-and-open` because a
    human who cannot start his dashboard because his laptop lacks a python
    library has been handed a worse problem than the one the check guards
    against, and for plain `generate` for the same reason plus symmetry: the
    file is written either way, the environment is what failed, and one policy
    across both verbs is one thing to explain. `--strict` overrides that in both
    — asking for strictness and getting "we skipped the check" would make the
    flag a lie. A written snapshot that declares no kind cannot choose a
    validator, and it is not conformant either: every snapshot says which
    contract it is."""
    if args.no_validate:
        print("  validation skipped (--no-validate)")
        return 0
    repo_root = Path(args.repo_root).resolve()
    try:
        kind = _written_kind(written)
    except _RepeatedKey as exc:
        print(f"  validation FAILED — {written} gives {exc}, so it has no one "
              f"meaning: its kind cannot be read, and no validator can be "
              f"chosen for it.", file=sys.stderr)
        return 1
    if kind is None:
        print(f"  validation FAILED — {written} declares no kind, so no "
              f"validator can be chosen for it, and a snapshot that does not "
              f"say which contract it is conforms to none.", file=sys.stderr)
        return 1
    validator, result = _validate_by_kind(
        written, kind, strict=args.strict, search_from=(written.parent, repo_root))
    if not result.available:
        if result.validator is None:
            _warn_validator_not_found(written, repo_root, kind, result,
                                      registered=validator is not None)
        else:
            _warn_validator_could_not_run(result, validator)
        if args.strict:
            print("    --strict was given and it means what it says: a run that "
                  "COULD NOT be validated FAILS rather than continuing "
                  "unchecked", file=sys.stderr)
            return 1
        print(f"    this is the ENVIRONMENT, not the snapshot — nothing here "
              f"says the corpus is wrong, only that no one checked it, so "
              f"{continues}", file=sys.stderr)
        return 0
    if not result.ok:
        _report_non_conformance(written, result)
        return 1
    print(f"  validation: {result.summary()}")
    return 0


def _resolve_install_shape(args: argparse.Namespace,
                           env=None) -> runtime_config.RuntimeSettings:
    """The settings this run serves with, or `ConfigurationError` naming why.

    `--local` and `OPENDOX_INSTALL_MODE` are resolved by
    `runtime_config.install_mode`, the one reading of the selector, which
    refuses the two disagreeing (plan 034 T070's fail-closed reading) and
    defaults to HOSTED (#1144 13.4, 13.5). Then each shape asks what it needs:

      * LOCAL binds loopback only, with no opt-in: a non-loopback `--host` is
        refused naming the rule (13.4), and so is anything a local install
        cannot be (`refuse_what_a_local_install_cannot_be`: a broker setting
        beside it, a DSN beside it, or a non-loopback `OPENDOX_BIND_HOST`). It
        needs no broker, and it supplies BOTH DSNs itself, from the server it
        bundles under `OPENDOX_STATE_DIR` (13.1; plan 034 T072).
      * HOSTED, set or by default, refuses with no issuer, NAMING THE ISSUER
        (13.5), and then loads the runtime's whole configuration.
        Otherwise unchanged (13.6).

    Either way the result is the runtime's own `load_settings`, because the
    serving process is the one whose settings are the install's (13.4a;
    R1Q16 (i)).

    Asked before anything is scanned, minted or bound, so a refused run leaves
    nothing behind and exits at once rather than starting a server that a
    bound would have to kill (F13.1's `test "$rc" -ne 124`).
    """
    env = os.environ if env is None else env
    local_flag = bool(getattr(args, "local", False))
    mode = runtime_config.install_mode(env, local_flag=local_flag)
    if mode == runtime_config.INSTALL_MODE_LOCAL:
        runtime_config.refuse_a_non_loopback_local_bind("--host", args.host)
        runtime_config.refuse_what_a_local_install_cannot_be(env)
    else:
        runtime_config.require_the_hosted_issuer(env)
    return runtime_config.load_settings(env, local_flag=local_flag)


class _Terminated(KeyboardInterrupt):
    """SIGTERM, raised as the interrupt the serve loop already stops cleanly on.

    A subclass, so the serve loop's own `except KeyboardInterrupt` still ends
    a served run with 0 (F13.1's `kill "$SERVER"; wait "$SERVER"`). An
    interrupt that arrives BEFORE the serve loop can still say which signal
    it was.
    """


def _terminate_as_interrupt(signum, frame):
    """SIGTERM, read as the Ctrl-C the serve loop already stops cleanly on."""
    raise _Terminated


def cmd_generate_and_open(args: argparse.Namespace, *, opener=webbrowser.open) -> int:
    """Regenerate the snapshot from the working tree into a run dir, start the
    local server, print the URL (ALWAYS), and open the browser. `--no-open`
    suppresses the browser; `--no-serve` returns after printing the URL without
    blocking (used by tests). `opener` is injectable for testing.

    THE INSTALL SHAPE IS RESOLVED FIRST (plan 034 T070): `--local`, or
    `OPENDOX_INSTALL_MODE=local`, selects the local single-user install, and
    with neither the install is hosted — see `_resolve_install_shape`. A
    refusal there is printed on stderr and the command exits 1, before any
    other work.

    A LOCAL RUN OWNS ITS DATABASE (plan 034 T072; #1144 13.1, R1Q16 (i)-(iv)).
    Once the corpus root and the anchors are known good, the bundled
    PostgreSQL server is started as THIS process's child, bootstrapped and
    migrated — starting and migrating it is all release 1 asks of it — and it
    is stopped when this command returns, however it returns: a served run
    ended by Ctrl-C or by SIGTERM (read here as the same interrupt), a
    `--no-serve` run, or a failure. A refused start exits 1 on stderr, like
    every other refusal of this verb."""
    try:
        settings = _resolve_install_shape(args)
    except runtime_config.ConfigurationError as exc:
        print(f"generate-and-open refused: {exc}", file=sys.stderr)
        return 1
    args.install_mode = settings.install_mode
    args.runtime_settings = settings
    if settings.install_mode != runtime_config.INSTALL_MODE_LOCAL:
        return _generate_and_open(args, opener=opener)
    # THE CHEAP REFUSALS FIRST, so a mistyped root never costs a database
    # start: every one `_generate_and_open` asks before it mints its run
    # directory, main's empty-source-option refusal (T055) included.
    _refuse_non_corpus_repo_root(args)
    _refuse_malformed_generated_at(args)
    _refuse_empty_source_options(args)
    server = bundle_mod.BundledServer(settings)
    args.database_bundle = server
    # NO `PG*` DEFAULT REACHES THE BUNDLE'S CONNECTIONS while this process
    # runs its database (Copilot review of openDox-code#69): see
    # `bundle.isolated_from_libpq_environment`.
    with bundle_mod.isolated_from_libpq_environment():
        return _run_the_local_lifecycle(args, server, opener=opener)


def _run_the_local_lifecycle(args: argparse.Namespace, server, *, opener) -> int:
    """Start the bundled server, generate and serve, and stop it, however
    this ends: a served run ended by Ctrl-C or SIGTERM, a `--no-serve` run, a
    refusal, a failure, or an interrupt before anything was served."""
    try:
        previous = signal.signal(signal.SIGTERM, _terminate_as_interrupt)
    except ValueError:                  # not the main thread: no handler to own
        previous = None
    try:
        try:
            server.start()
        except (bundle_mod.BundleRefused, runtime_config.ConfigurationError,
                migrations_mod.MigrationError) as exc:
            print(f"generate-and-open refused: {exc}", file=sys.stderr)
            return 1
        report = server.report()
        print(f"  database {report['socket_dir']} (bundled, pid {report['pid']}, "
              f"migrations applied now: {server.applied or 'none pending'})")
        return _generate_and_open(args, opener=opener)
    except KeyboardInterrupt as interrupt:
        # AN INTERRUPT ANYWHERE IN THE LOCAL LIFECYCLE IS A CLEAN STOP (Copilot
        # review of openDox-code#69). SIGTERM, or Ctrl-C, can arrive while the
        # server is initializing or migrating, or while the snapshot is being
        # generated, all before the serve loop's own handler. It is a stop
        # that was asked for, so it is not a traceback: the `finally` below
        # stops the bundled server and restores the handler. Nothing was
        # served, so the exit is the signal's conventional status (128 + its
        # number) and not 0.
        signum = (signal.SIGTERM if isinstance(interrupt, _Terminated)
                  else signal.SIGINT)
        print(f"generate-and-open interrupted ({signum.name}) before it "
              "served; its bundled PostgreSQL server stops with it",
              file=sys.stderr)
        return 128 + int(signum)
    finally:
        # THE HANDLER FIRST, so a second SIGTERM during the stop takes the
        # default action at once; the parent-death signal still stops the
        # server if this process goes before `stop()` has finished.
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
        server.stop()


def _install_report(args: argparse.Namespace):
    """`/capabilities`' `install` block for THIS process, as a callable the
    server asks on each request, or None where no install shape was resolved
    (plan 034 T073; #1144 13.4a; RULED R1Q16 (i), `5850003126`).

    It is read from the settings `cmd_generate_and_open` resolved and loaded
    (`args.runtime_settings`) and from the bundled server it started as its
    own child (`args.database_bundle`), so the served process reports its own
    install shape: a status probe from a second process could be right about
    the settings while the server ignored them. `mode` is the install mode
    those settings carry. `database_bundle` is the bundled server's report,
    `data_dir`, `socket_dir` and its `pid` while it lives
    (`bundle.BundledServer.report`), and it is None for a hosted install,
    which bundles no server, as `runtime status` reports it."""
    settings = getattr(args, "runtime_settings", None)
    if settings is None:
        return None
    server = getattr(args, "database_bundle", None)

    def report() -> dict:
        return {"mode": settings.install_mode,
                "database_bundle": (server.report() if server is not None
                                    else None)}

    return report


#: The prefix of the temporary run directory `generate-and-open` mints when
#: no `--run-dir` is given: the installed command's own name (plan 034 T084,
#: adversarial review 2, G7), not openxFactory's pre-carve one.
RUN_DIR_PREFIX = "opendox-"


def _generate_and_open(args: argparse.Namespace, *, opener) -> int:
    """`generate-and-open`'s generate-then-serve half, once the install is known.

    A RUN DIRECTORY THIS PROCESS MINTED IS REMOVED WHEN IT IS DONE WITH IT
    (plan 034 T084, adversarial review 2, G7): when the server stops, on a
    `--no-serve` run, on a refusal and on a failure. It used to be left under
    the system's temporary directory on every run. A `--run-dir` the caller
    names is the caller's, and is left exactly as this run wrote it."""
    # Ahead of minting the run dir, so a refused root leaves not even an empty
    # temp directory behind. `_generate_and_write` is still the guard that MATTERS
    # (it is the one no caller can skip); these are the same checks, earlier.
    _refuse_non_corpus_repo_root(args)
    _refuse_malformed_generated_at(args)
    _refuse_empty_source_options(args)
    if args.run_dir:
        return _generate_and_serve(args, Path(args.run_dir).resolve(),
                                   opener=opener)
    minted = Path(tempfile.mkdtemp(prefix=RUN_DIR_PREFIX))
    try:
        return _generate_and_serve(args, minted, opener=opener)
    finally:
        shutil.rmtree(minted, ignore_errors=True)


def _generate_and_serve(args: argparse.Namespace, run_dir: Path, *,
                        opener) -> int:
    """Generate into `run_dir`, serve it, and stop, for `_generate_and_open`."""
    run_dir.mkdir(parents=True, exist_ok=True)
    output = run_dir / "snapshot.json"

    checkout_root = Path(args.repo_root).resolve()
    snapshot, written = _generate_and_write(args, output)
    _report(snapshot, written, checkout_root)
    # A validator that could not RUN warns and returns 0 here — the server
    # starts. Only a snapshot the validator actually REJECTED (or --strict)
    # returns non-zero and stops before `build_server`.
    rc = _validate(written, args,
                   continues="the dashboard SERVES this unchecked snapshot")
    if rc != 0:
        return rc

    # The model adapter's session root: the flag when given, else beside the
    # snapshot this run just wrote.
    model_session_root = (Path(args.model_session_root).resolve()
                          if getattr(args, "model_session_root", None)
                          else install_mod.session_root_beside(written))
    httpd = serve_mod.build_server(WEB_DIR, written, checkout_root,
                                   host=args.host, port=args.port,
                                   actor=getattr(args, "actor", None),
                                   # the ENTRYPOINT declares the real notebook
                                   # adapter; `build_server` never reaches for one
                                   # on a caller's behalf (PR #49 hardening item 1)
                                   adapter_factory=serve_mod.real_notebook_adapter,
                                   # and the MODEL PROVIDER, for the third time
                                   # in the same idiom and for the same reason:
                                   # an operator must be able to read what their
                                   # install talks to. Without a declaration HERE
                                   # no model consumer on this surface can reach
                                   # a provider at all — `_workbench_model_port`
                                   # returns None and every consumer's honest
                                   # posture is an absent capability
                                   # (add-doxbench-distilled-abstract D9).
                                   #
                                   # ONE bridge for the life of this process: the
                                   # adapter is stateful (it holds the per-thread
                                   # harness sessions), and `_workbench_model_port`
                                   # resolves per REQUEST. The factory takes no
                                   # arguments, so nothing about the adapter can
                                   # become a per-turn input; the three
                                   # install-time inputs it cannot supply itself
                                   # — catalog, session root, launch config — are
                                   # declared in `doxbench_install`.
                                   #
                                   # SINCE add-model-provider-broker (ratified
                                   # 2026-08-26) this is
                                   # `declared_model_port_factory`: it reads
                                   # the checkout's model-provider BINDINGS and
                                   # resolves the broker-backed port when one is
                                   # declared, and the harness factory this line
                                   # used to name when none is — so an install
                                   # that never heard of a broker is unchanged.
                                   model_port_factory=install_mod.declared_model_port_factory(
                                       model_session_root,
                                       checkout_root=checkout_root),
                                   # and the same discipline for the doxBench
                                   # knowledge service: the ENTRYPOINT makes the
                                   # install-time retrieval-backend declaration
                                   # (add-doxbench-editing-phase-b D11), which is
                                   # the self-hosted half of the ratified
                                   # two-case principle
                                   knowledge_declaration=(
                                       knowledge_mod.SELF_HOSTED_LOCAL_EMBEDDED),
                                   # and THIS process's own install shape, on
                                   # `/capabilities` (plan 034 T073; #1144
                                   # 13.4a): the settings it loaded, and the
                                   # bundled server it started as its child.
                                   install_report=_install_report(args),
                                   # and the LANDER, bound with the install
                                   # this run resolved (plan 038 T016; FR-007)
                                   landing_factory=_served_landing_factory(
                                       checkout_root, args))
    url = serve_mod.server_url(httpd, "/index.html")
    # THE CONSOLE TOKEN, ON A STANDALONE PLANE (plan 034 T104; RULED
    # openxFactory#656 `5963851934`). `/capabilities` no longer carries it, so
    # this entry point writes it into a 0600 private copy in the install's
    # state directory, an HTML page that forwards to `url` with the token in
    # the FRAGMENT. The browser is handed the copy's PATH, because a URL given
    # to `webbrowser.open` sits on a command line every user can read
    # (`/proc/<pid>/cmdline`). The path is printed with or without
    # `--no-open`, and the token never is: opening that file again re-opens
    # the page. `None` on a host's plane, where no token was minted (a
    # standalone plane still keeps every console's copy unserved then,
    # `console_access.guard_private_roots`), and under `--no-serve`. A copy
    # that cannot be written safely refuses the run before it serves.
    #
    # A plain `kill`, or a closed terminal, stops a standalone console the way
    # Ctrl-C does (`terminate_as_interrupt`), from BEFORE the copy is written
    # to after it is removed (Copilot at openDox-code#84, r4175213864), and a
    # stop that arrives while the copy is being written or removed is held
    # until that is done (`deferred_termination`), so no copy is ever left
    # half handled. A plane that writes no copy keeps the signals' defaults.
    #
    # `--no-serve` SERVES NOTHING, SO IT PUBLISHES NOTHING (adversarial review
    # of openDox-code#84, B8). It closes the server as soon as it has printed
    # the URL, so a copy written for it opened a console page nothing
    # answered, and was deleted as the run returned. No copy is written, none
    # is opened, and no console line is printed.
    console = None
    serving = not args.no_serve
    with console_access.terminate_as_interrupt(
            serving and console_access.needs_copy(httpd)):
        try:
            try:
                with console_access.deferred_termination():
                    if serving:
                        console = console_access.publish(httpd, page_url=url)
                print(f"  serving {url}")
                print(f"  snapshot {serve_mod.server_url(httpd, '/snapshot.json')}")
                if console is not None:
                    print(f"  console {console.file_url} (this user's private "
                          "copy, mode 0600: open it to open the console page "
                          "again)")
                    # A browser that cannot open it is told the way past it,
                    # in one line with no token (RULED, B3).
                    print(f"  {console_access.UNOPENABLE_HINT}")
                # The URL is ALWAYS printed on its own line, AND FLUSHED (plan
                # 034 T056). Where standard output is a pipe or a file, Python
                # buffers it by block, and the process is about to block in
                # `serve_forever()`. So without the flush, a wrapper reading
                # this line never sees it while the server runs, and it cannot
                # learn an ephemeral port or tell that the server started.
                # Measured at openDox-code#59 e3ef506a: zero lines in 20 s on
                # a pipe. It carries no token.
                print(url, flush=True)

                if not args.no_open:
                    try:
                        opener(console.file_url if console is not None else url)
                    except Exception as exc:  # a headless box has no browser — never fatal
                        print(f"  (could not open a browser: {exc}; open the "
                              f"{'console file' if console is not None else 'URL'} "
                              "above manually)")

                if args.no_serve:
                    return 0

                print("  serving until interrupted (Ctrl-C to stop)", flush=True)
                httpd.serve_forever()
            except console_access.ConsoleAccessRefused as exc:
                print(f"generate-and-open refused: {exc}", file=sys.stderr)
                return 1
            except KeyboardInterrupt:
                pass
            return 0
        finally:
            # The copy goes with the server: its token is this serve's, and
            # dies with it. It goes FIRST, while this process still holds the
            # port, so no later serve can bind it and write its own copy in
            # between. A stop that arrives meanwhile lets it finish.
            with console_access.deferred_termination(raise_pending=False):
                console_access.remove_private_copy(console)
                httpd.server_close()


# ---- gate console (US9): human-only executable gate actions ----------------
# Every action constructs a `HumanGate` (the distinct human-only entrypoint) —
# there is no machinery/agent code path to a gate action here.
#
# `--actor` USED TO BE FREE TEXT (the accepted v1 risk recorded at
# `ideation/brainstorm/ideation-dashboard.md` item 25, still present tense in
# `contracts/identity-brokering/README.md`): the flag NAMED the acting human and
# nothing anywhere asked whether the invocation was that human, so every
# authority-bearing record the console wrote was unattributable. It is now
# AUTHENTICATED at this boundary — the one place the untrusted claim enters —
# against whatever identity the deployment already proves
# (`actor_identity.authenticate_actor`), and the record carries the trusted
# source's CANONICAL spelling rather than the caller's. No principal, no gate
# action: `_gate_actor` raises and `main` turns it into a refusal + exit 1,
# before any HumanGate exists and therefore before any write.
#
# This does NOT close D22: an agent running AS the engineer, in the engineer's
# own checkout, still satisfies the local sources. It closes the strictly larger
# hole underneath — an invocation naming a human it has no relation to at all.


def _gate_actor(repo_root: Path, args: argparse.Namespace) -> str:
    """The AUTHENTICATED acting human for this invocation, or a refusal.

    Called by every gate-gate construction path in this module. Raises
    `actor_identity.ActorUnauthenticated`, which `main` renders as a refusal —
    deliberately an exception rather than a return code, so a call site cannot
    forget to check it and reach a HumanGate anyway."""
    authenticated = actor_mod.authenticate_actor(
        getattr(args, "actor", None), checkout_root=repo_root)
    # The canonical spelling is what everything downstream records and prints.
    args.actor = authenticated.actor
    return authenticated.actor

def _gate_snapshot(args: argparse.Namespace) -> tuple[Path, dict]:
    """Regenerate the snapshot the gate action plans against (the same
    deterministic generation the dashboard reads), through the generator seam
    as `_generate_and_write` does (plan 034 T055)."""
    repo_root = Path(args.repo_root).resolve()
    snapshot = generator_seam.generate(
        repo_root, args.repository, source_revision=args.source_revision,
        project_register_source=_source_option(args, "project_register", "--project-register"),
        possibles_source=_source_option(args, "possibles", "--possibles"))
    return repo_root, snapshot


def _human_gate(repo_root: Path, args: argparse.Namespace) -> HumanGate:
    return HumanGate(repo_root, [args.records_dir],
                     human_actor=_gate_actor(repo_root, args))


def _commission_cli(verb: str, args: argparse.Namespace, target: str,
                    **engine_kwargs) -> int:
    """The shared half of the three wheel-verb subcommands (011).

    Terminal parity with the executing routes: same console facade, same
    engine, same guards. The CLI adds nothing of its own except the printing —
    which is exactly what makes the two surfaces equivalent."""
    repo_root = Path(args.repo_root).resolve()
    human = _human_gate(repo_root, args)
    try:
        # INSIDE the refusal boundary (plan 034 T084): openDox's own gate
        # default refuses the governed `GateConsole` at construction
        # (`GateRecordsNotRegistered`, a `GateRefused`), so a contributed gate
        # verb that reaches it with no host's gate registered answers
        # "<verb> refused: ..." rather than a traceback.
        console = gate_mod.GateConsole(human, records_dir=args.records_dir)
        res = getattr(console, verb.replace("-", "_"))(
            target, outline=args.outline, workflow=args.workflow,
            note=args.note, provenance=cli_provenance(), **engine_kwargs)
    except gate_mod.GateRefused as exc:
        print(f"{verb} refused: {exc}", file=sys.stderr)
        return 1
    print(f"{verb} {target} \u2192 workflow {res.job['workflow']!r} "
          f"(status {res.job['status']}, by {args.actor})")
    print(f"  workflow-job:       {res.job_path.relative_to(repo_root)}")
    print(f"  gate-action record: {res.record_path.relative_to(repo_root)}")
    return 0


# ---- lens gate verbs (add-lens-gate-verbs): human-only recipe dispatches ----

def _parse_pairs(pairs: list[str], flag: str) -> dict[str, str]:
    """`document=reason` overrides from repeatable flags. Refuses a bare
    `document` (the reasoned-override guard's terminal reason lives in the
    engine, but a CLI include/exclude with no reason is a usage error)."""
    out: dict[str, str] = {}
    for raw in pairs or []:
        doc, sep, reason = raw.partition("=")
        if not sep or not doc.strip() or not reason.strip():
            raise SystemExit(f"{flag} expects document=reason (got {raw!r})")
        out[doc.strip()] = reason.strip()
    return out


def _lens_gate(repo_root: Path, args: argparse.Namespace) -> HumanGate:
    """A HumanGate whose allowlist admits BOTH the records dir and the gitignored
    workbench tree (manifest + cross-reference queue live under WORKBENCH_DIR)."""
    return HumanGate(repo_root, [args.records_dir, workbench_mod.WORKBENCH_DIR],
                     human_actor=_gate_actor(repo_root, args))


def _session_registry(checkout_root: Path, repository: str | None):
    """A registry for THIS process, with the live sessions RE-DERIVED
    (007-workbench-branch-sessions T033a; FR-008, D10, G13).

    Every CLI verb is its own process and `SnapshotRegistry._entries` is an
    in-process dict, so a verb starts with NO session entries at all. The
    BOOTSTRAP is what makes liveness survive that boundary: it re-registers every
    worktree under the sessions container WHOSE BRANCH STILL EXISTS, reading the
    two signals jointly, so a CLI create on a tile that already has a session JOINS
    it, `propose` cannot proceed over unmerged drafts, and the resume-or-new prompt
    cannot re-fire mid-session.

    Half-signals are REPORTED, never repaired: a worktree with no branch (crash
    residue) and a branch with no worktree (an abandoned session) each print their
    own remedy on stderr, and this function deletes nothing.

    This is the ONE place a CLI verb obtains a registry — every session-bearing
    verb this feature adds goes through it. The registry is the REGISTERED
    snapshot registry's (`projection_seams.registry`, plan 034 T055): openDox's
    own where no host has contributed one."""
    registry = projection_seams.registry.current().SnapshotRegistry()
    report = branch_session_mod.bootstrap_sessions(
        registry, repository=repository or "", checkout_root=Path(checkout_root))
    for note in report.stale:
        print(f"  session note ({note.kind}): {note.reason}", file=sys.stderr)
    for message in report.errors:
        print(f"  session note: {message}", file=sys.stderr)
    return registry


def _session_repository_key(repo_root: Path, args: argparse.Namespace) -> str:
    """The registry/notebook key's repository half, for EVERY session verb — one
    derivation, in one place (007-workbench-branch-sessions FR-005/R7).

    `--repository`, else the checkout directory's name: the `<repo>` beside
    `<repo>-worktrees/` convention `branch_session.container_root` already relies
    on. The registry is per-PROCESS, so within one verb any value at all is
    self-consistent — which is exactly what made the divergence invisible.

    THE NOTICE (PR #49 review finding 8, leg b, wave 2). Nothing on disk records
    which value a session was opened under: the worktree path comes from the
    CHECKOUT and the branch from the TILE, so the key survives only as long as the
    process. Its one cross-process artifact is the session's NotebookLM alias,
    which is derived from it — so `create-document --repository MedxFactory` in an
    `openxFactory` checkout, then an `abandon-session` with no flag, retires an
    alias that was never created and ORPHANS the real notebook on the shared
    account (reproduced; before wave 2 the ending also REPORTED it retired, which
    `workbench._delete_titled` no longer does). A flag whose value must be repeated
    to be correct must say so, and it says so HERE, where every verb derives it,
    rather than in five docstrings. Not a refusal: the flag's declared purpose is a
    checkout directory named something other than the repository, and refusing that
    would remove the use case instead of the silence."""
    named = str(getattr(args, "repository", None) or "").strip()
    derived = repo_root.name
    if named and named != derived:
        print(f"  session note:       --repository {named!r} is not this "
              f"checkout's directory name {derived!r}. The key is not recorded "
              "anywhere, so EVERY verb of this session must pass the same "
              f"--repository {named!r}; one that does not derives a different "
              "notebook alias and leaves this session's notebook orphaned "
              "(FR-037).", file=sys.stderr)
    return named or derived


def _notebook_port(repo_root: Path):
    """The session notebook adapter for a CLI verb (T074; FR-036, FR-021, D16).

    A CLI verb is unambiguously LOCAL — a human at a shell in their own checkout —
    so it declares the real `nlm`-backed adapter and does not consult a capability
    probe the way `serve.py` must. The adapter DEGRADES on its own when `nlm` is
    absent (`available()` False, every action `skipped`), so this is safe to
    declare unconditionally: the session opens either way, and the FR-042 notice
    carries the reason.

    A named seam purely so a test injects `FakeNotebookAdapter`: no test may create
    a real notebook (FR-043)."""
    from opendox import workbench as wb_mod

    return wb_mod.NotebookAdapter()


def _unwind_cli_session(verb: str, session, git, repo_root: Path,
                        message: str) -> int:
    """Print a CLI session refusal, having first undone a session THIS
    invocation opened (PR #49 review finding 3).

    The CLI half of the route's `_unwound`: same rule, same helper
    (`branch_session.unwind_opened_session`), so the two surfaces cannot diverge
    on what a refused first create leaves behind (FR-020). A JOIN is never
    unwound, a branch carrying gate-action commits is never deleted, and
    whatever the unwind could not remove is printed rather than swallowed."""
    notes = ()
    if session is not None and git is not None:
        notes = branch_session_mod.unwind_opened_session(
            git, session, checkout_root=repo_root)
    print(f"{verb} refused: {message}", file=sys.stderr)
    for note in notes:
        print(f"  session note:       {note}", file=sys.stderr)
    return 1


# FR-019's THIRD clause on the CLI (PR #49 review finding 2). `--actor` is free
# text the caller supplies, so a scripted `cli.main(["gate", "abandon-session",
# "--actor", "codex-agent-bot", …])` tore a session down with exit 0 and a record
# naming the bot — the clause had no runtime realization at all.
#
# The CLI's evidence of a human is the one it has always implicitly relied on and
# never checked: an INTERACTIVE TERMINAL. A person at a shell has one; a CI step,
# an agent harness, and a `subprocess.run` do not. A non-interactive HUMAN shell
# (a `nohup`, a remote exec) declares presence explicitly with the environment
# variable below, which makes the declaration auditable instead of assumed.
#
# The honest limit, same as the route's: an agent running AS the engineer can set
# the variable. Hardening that is the xForge host's concern (the ruling recorded
# at `_human_gate`, and D22), not this local CLI's. What the check removes is the
# invocation that never even claimed to be a human console.
HUMAN_CONSOLE_ENV = "XF_HUMAN_CONSOLE"
_TRUTHY = ("1", "true", "yes", "on")

AGENT_INVOCATION_REFUSAL = (
    "a session gate verb is human-only (FR-019) and this invocation is not an "
    f"interactive human console. Run it from a terminal, or set "
    f"{HUMAN_CONSOLE_ENV}=1 to declare human presence in a non-interactive shell")


def console_presence() -> str | None:
    """HOW this invocation shows it is a human at a console, or None when it
    cannot (design D23; Brett's 2026-07-27 ruling item 3).

    The same two proofs `human_console_present` has always accepted, now NAMED so
    the gate-action record can say which one was shown — the CLI is the only place
    that knows, and a record that says only "a human did this" hides the very
    difference between them.

    ORDER: the DECLARATION wins over the terminal. An operator who exports
    `XF_HUMAN_CONSOLE=1` and then types the verb at a real tty is recorded as
    `declared`, the WEAKEST of the three proofs — deliberately, because an audit
    consumer filtering for `declared` must not be able to miss one. It is also the
    order `human_console_present` already used, so nothing about WHO is admitted
    changes here."""
    declared = os.environ.get(HUMAN_CONSOLE_ENV, "")
    if str(declared).strip().lower() in _TRUTHY:
        return gate_mod.PRESENCE_DECLARED
    try:
        if sys.stdin.isatty():
            return gate_mod.PRESENCE_TTY
    except (AttributeError, OSError, ValueError):
        return None
    return None


def human_console_present() -> bool:
    """Whether this invocation can show it is a human at a console."""
    return console_presence() is not None


def cli_provenance():
    """This invocation's GATEWAY fact (D23): surface `cli`, plus the proof of
    console presence `console_presence` observed. None when presence was not
    shown at all — the session verbs never reach a record in that state
    (`_session_identity_gate` refuses first), and a pre-existing verb writes the
    pre-growth shape rather than a guessed one, because the vocabulary has no
    value meaning "not shown"."""
    presence = console_presence()
    if presence is None:
        return None
    return gate_mod.Provenance(gate_mod.SURFACE_CLI, presence)


def _session_identity_gate(verb: str, repo_root: Path,
                           args: argparse.Namespace) -> int | None:
    """FR-019, enforced PER VERB on the CLI: a session subcommand is a FRESH
    PROCESS with no `serve.py` handler in front of it, so it constructs its own
    `HumanGate` and requires it BEFORE any read, any resolution, and any write.
    Returns an exit code to propagate, or None when the identity is good.

    ALL THREE of FR-019's clauses are discharged here, in the order the route
    discharges them: locality is structural (a CLI verb runs in the human's own
    checkout), then the AGENT/AUTOMATION clause (`human_console_present`), then
    the unresolved-actor clause.

    A BLANK `--actor` must fail closed with a refusal rather than a traceback: a
    gate action with no identified human is structurally invalid, and the human who
    typed it needs to be told that, not shown a stack."""
    if not human_console_present():
        print(f"{verb} refused: {AGENT_INVOCATION_REFUSAL}", file=sys.stderr)
        return 1
    try:
        # AUTHENTICATE the claim before it can become a record. Deliberately
        # AFTER the console-presence test and before the HumanGate: presence is
        # the question "is a human here at all", identity is the question "which
        # human", and an invocation that fails the first must hear that first.
        _gate_actor(repo_root, args)
    except actor_mod.ActorUnauthenticated as exc:
        print(f"{verb} refused: {exc}", file=sys.stderr)
        return 1
    try:
        gate_mod.require_human_gate(
            HumanGate(repo_root, [args.records_dir], human_actor=args.actor))
    except ValueError as exc:                  # blank actor -> fail closed
        print(f"{verb} refused: {exc}", file=sys.stderr)
        return 1
    except BoundaryViolation as exc:           # structurally unreachable here
        print(f"{verb} refused: {exc.refusal.report()}", file=sys.stderr)
        return 1
    return None


def _pull_request_port(repo_root: Path):
    """The LOCAL plane's pull-request port (FR-034, D22).

    The identity is RULED: the INVOKING ENGINEER'S OWN `gh` authentication. This
    factory therefore constructs the real adapter with the checkout and NOTHING
    ELSE — no token argument is accepted anywhere on this path, nothing is stored,
    and no credential is synthesized. The hosted plane's openxfactory-App identity
    is normative but out of scope (FR-048), so there is no plane switch to make
    here either.

    It is a named seam purely so a test can inject `FakePullRequests`: no test may
    perform a real remote write (quickstart step 6)."""
    from opendox.session_pr import GhPullRequests

    return GhPullRequests(repo_root)


def _submission_port(repo_root: Path):
    """The product's OWN submission port (plan 038 T014; #1144 12.4, R2Q2 (a)).

    It NAMES NO PLATFORM: with nothing injected it is `LocalGitSubmissions` for
    the checkout, a plain `git push` of a named branch to the remote named
    `origin` (else the sole remote), with no `gh`. It is a NEW seam beside
    `_pull_request_port`, which keeps `GhPullRequests` and serves `gate open-pr`
    unchanged. The push runs as the invoking user, in that user's checkout,
    with that user's own git credentials; nothing is stored.

    A named seam, as `_pull_request_port` is, so a governed host may contribute
    its own `SubmissionPort` and a test may inject one."""
    from opendox.session_pr import LocalGitSubmissions

    return LocalGitSubmissions(repo_root)


def _landing_port(repo_root: Path, *, local: bool = False):
    """The CLI's LANDER (plan 038 T016; #1144 12.6a), or None.

    The neutral lander (`landing.NeutralLander`) where the repository is
    `standalone`: the explicit local install (`--local`, which `local` is, or
    `OPENDOX_INSTALL_MODE=local`) and `main`'s committed declaration. NOTHING
    otherwise: under `governed` no lander is bound and `land` submits through
    the host's instrument (R2Q4 (a)), and under `unknown` none is bound and
    `land` refuses (`landing.bound_lander`). The lander re-reads the
    governance at the moment it lands, so a lander bound here lands nothing in
    a repository that has stopped being standalone.

    A named seam, as `_submission_port` is, so a test may inject one."""
    from opendox.landing import bound_lander

    return bound_lander(repo_root, local=local)


def _served_landing_factory(checkout_root: Path, args: argparse.Namespace):
    """The served plane's `landing_factory` (plan 038 T016): `_landing_port`
    for the checkout, with the install THIS entry point resolved.

    `generate-and-open --local` selects the local install without setting
    `OPENDOX_INSTALL_MODE`, and `standalone` needs it (FR-007), so the
    entry point declares it to the server, as it declares the notebook
    adapter and the install report: the server never reads a flag it was not
    handed. Resolved per call, so a landing reads the repository as it is."""
    local = (getattr(args, "install_mode", None)
             == runtime_config.INSTALL_MODE_LOCAL)

    def landing_factory():
        return _landing_port(checkout_root, local=local)

    return landing_factory


def _stats(snapshot: dict) -> dict[str, int]:
    """How many of each collection the snapshot carries. One it lacks, or
    carries as something other than a list or a mapping, counts 0: a
    registered generator's contract need carry none of them (see `_report`)."""
    def count(value: object) -> int:
        return len(value) if isinstance(value, (list, dict)) else 0

    return {k: count(snapshot.get(k)) for k in (
        "documents", "clusters", "possibles", "staged_topics", "changes", "keyword_index")}


def _add_generate_args(sub: argparse.ArgumentParser) -> None:
    """Generation arguments shared by `generate` and `generate-and-open`."""
    sub.add_argument("--repo-root", required=True, help="repository to scan")
    sub.add_argument("--repository", required=True, help="canonical repository id for the snapshot")
    sub.add_argument("--source-revision", default=None,
                     help="pin the source_revision anchor (default: the repo's git HEAD)")
    # The SECOND generation anchor, at the same altitude as the first because
    # the two are pinned together or not at all. Without it the only source of
    # `generated_at` is `git show -s --format=%cI` run inside the scanned tree,
    # which yields nothing when that tree is not a checkout — a sealed source
    # artifact, an export, a copied context — and the snapshot then ships with
    # the stamp silently missing (add-nightly-dashboard-refresh task 3.6).
    sub.add_argument("--generated-at", default=None, metavar="RFC3339",
                     help="pin the generated_at anchor, recorded verbatim "
                          "(default: --source-revision's committer date read "
                          "from the scanned tree's git, omitted when that tree "
                          "is not a checkout)")
    sub.add_argument("--project-register", default=None,
                     help="override the project-register source (default: discovered under repo-root)")
    sub.add_argument("--possibles", default=None,
                     help="override the possibles-register source (default: discovered under repo-root)")
    sub.add_argument("--strict", action="store_true",
                     help="treat validator warnings as failures — and make a "
                          "validation that could not RUN AT ALL (the validator "
                          "is unreachable, or its python dependencies are "
                          "missing) fatal too, instead of the warning an "
                          "ordinary run gets")
    sub.add_argument("--no-validate", action="store_true", help="skip post-render validation")


def _default_home_factory(root):
    """`home_corpus`'s shape (`adapter, ref = factory(root)`), over
    `WorkingTreeCorpus` at its own defaults, whose `required_fields` is the
    small neutral field set R1Q13 (a) decides (`NEUTRAL_FIELDS`, `title` and
    `summary`, since plan 034 T054). Its `__init__` takes no root -- it is
    root-agnostic, and `resolve(ref)` reads `ref.location` -- so one
    `CorpusRef` per call carries the root this factory was given, and the
    adapter itself needs none.

    READS THE WORKING TREE, uncommitted edits included -- RULING, Brett Heap,
    2026-09-27, via the holder: "Working tree (Recommended)". A standalone
    user edits files in their own editor, and openxFactory's hosted adapter
    already shows worktree bytes, so the standalone default matches it rather
    than reading the session's git HEAD. `WorkingTreeCorpus`
    (`local_git_adapter.py`) is `LocalGitCorpus` with `list_documents`/`read`
    aimed at the filesystem instead of a resolved commit, and with openDox's
    own settings documents (`doxbench_intake.SETTINGS_DOCUMENTS`, plan 034
    T082) left out of its listing and out of a whole-corpus `check`; see its
    own docstring for what stays unchanged (`resolve`, `classify`,
    `write_back`, and a `check` of named subjects) and what does not.

    A FRESH ADAPTER EVERY CALL, ON PURPOSE: nothing here is held onto across
    calls, so there is no listing cache keyed on whatever HEAD was at an
    earlier call -- each call gets an instance that reads the CURRENT
    filesystem state, and `WorkingTreeCorpus` itself caches nothing further
    within a call either (its own docstring says so).

    Kept byte-for-byte identical to `serve.py`'s copy of the same function
    (one home corpus, one default, read by two entry points): neither module
    may import the other, and `corpus_adapter.py` cannot hold this one
    without importing `local_git_adapter` and creating the cycle that module
    already imports `corpus_adapter` the other way (4.1a, T022)."""
    return (local_git_adapter.WorkingTreeCorpus(),
            corpus_adapter.CorpusRef(name="home", location=str(root)))


#: THE INSTALLED COMMAND'S OWN NAME AND WORDS (plan 034 T084; found by T099's
#: PyPI writer). `opendox --help` is what a published install prints, so the
#: usage line names the console script `pyproject.toml` installs, `opendox`,
#: and the description and epilog name openDox only. They used to print
#: `usage: ideation-dashboard` and this module's docstring, which is
#: openxFactory's pre-carve history, not a user's help.
PROG = "opendox"
PARSER_DESCRIPTION = (
    "openDox, a document workbench over a corpus of documents: regenerate "
    "the corpus's deterministic snapshot, serve it locally and open it in a "
    "browser, create and edit its documents, declare the model providers a "
    "chat may use, and run the identity and coordination runtime.")
PARSER_EPILOG = "Run `opendox <command> --help` for a command's own options."


def build_parser(*, subcommand_extensions: tuple = ()) -> argparse.ArgumentParser:
    """The command line, plus whatever this invocation was ASSEMBLED with.

    `subcommand_extensions` is the SUBCOMMAND EXTENSION POINT
    (`split-opendox-two-layer-product` § 2.4, design § D2): a tuple of
    `subcommand_extension.SubcommandExtension`s, each attaching its own
    subcommands to the SAME subparsers action the core commands are added
    through. The default `()` is today's parser exactly — byte-identical help
    text for every entry point, which is the parity a golden snapshot asserts.

    An extension registers LAST, after every core subcommand, so the help text
    reads core-first and a contributed name can never displace a core one:
    `argparse` refuses a duplicate subcommand name outright, and refusing the
    contributed one is the right direction of that refusal.

    WHICHEVER PROFILE IS CURRENT (`profile_openxfactory.SUBCOMMAND_EXTENSIONS`)
    is registered here too, at the ordinal its column has always occupied, and
    NOT passed in by `main()`. That is a host's own profile, where one
    registered before this call; otherwise it is openDox's OWN default, which
    THIS function registers first if nothing else has (R1Q3 (a); requirement
    3, `add-neutral-product-standalone-operability`) — so the composition
    point stays open for a host, but is never empty. `build_parser()` names
    the whole of THIS assembly's command line — which is what every caller,
    every golden and every existing test already reads it as — so what this
    repository is built with belongs inside it, and `subcommand_extensions`
    stays the seam for whatever a caller adds on top. The default's own
    contribution is `RuntimeSubcommand` (`opendox.default_profile`,
    `opendox/runtime/cli.py`), which is how `[project.scripts] opendox`
    (plan 034 T038) reaches the runtime verbs with no separate wiring here.
    """
    # THE ENTRY POINT'S DEFAULT (R1Q3 (a), openxFactory#656 comment
    # 5817152735): where no host has registered a profile, register openDox's
    # own, so the `SUBCOMMAND_EXTENSIONS` read below builds on it instead of
    # refusing. A host registered before this line keeps its own; one that
    # registers after this parser is built is refused (R1Q3 (ii); RN-1 (a)).
    domain_profile.register_default(default_profile)
    # AND THE HOME CORPUS'S OWN DEFAULT (4.1a, T022, the SAME R1Q3 (a)
    # ruling -- "the default profile and the default adapter are both
    # entry-point registrations"): a bare process that only builds a parser
    # still needs the home corpus to resolve for `create`/`edit`
    # (`authoring.py`), and a host that DID register its own adapter must
    # see it left alone. `register_default_home` registers ONLY where
    # nothing already answers `corpus_adapter.home()`, exactly as
    # `domain_profile.register_default()` does for the profile, immediately
    # above. The two registries are independent -- neither call reads the
    # other's state -- so the order between them carries no meaning; this
    # one is placed second because, unlike the profile call, it has no
    # downstream read of its own inside THIS function (the profile's
    # `SUBCOMMAND_EXTENSIONS` is read a few lines below; the corpus
    # adapter's registration is read later, from `authoring.py`).
    corpus_adapter.register_default_home(_default_home_factory)
    # AND openDox's OWN snapshot generator (5.4, T052; R1Q10 (a), in the same
    # R1Q3 (a) pattern), registered only where no host has contributed one.
    generator_seam.register_default(default_generator.GENERATOR)
    # AND openDox's OWN snapshot registry and source, corpus-root predicate,
    # writer and validators (5.5, T055; the same ruling and pattern), each
    # only where no host has registered its own. Registering reads nothing, so
    # a host that registers after this parser is built still replaces them.
    projection_seams.register_defaults()
    # AND openDox's OWN doxBench validators and status-exemption rail (4.3,
    # T085; R1Q10 (a) and R1Q12 (a), the same pattern), each only where no
    # host has registered its own, and replaceable by a host until read.
    doxbench_defaults.register_defaults()
    # AND the consumer columns' defaults (plan 034 T084; #1144 4.3,
    # R1Q10 (a)): the gate primitives, the doxBench scope, kickoff and
    # the cross-reference register, the same way.
    column_seams.register_defaults()
    parser = argparse.ArgumentParser(prog=PROG, description=PARSER_DESCRIPTION,
                                     epilog=PARSER_EPILOG)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="regenerate the deterministic snapshot")
    _add_generate_args(gen)
    gen.add_argument("--output", required=True, help="snapshot output path (JSON)")
    gen.set_defaults(func=cmd_generate)

    gao = sub.add_parser("generate-and-open",
                         help="regenerate the snapshot, serve it locally, and open the browser")
    _add_generate_args(gao)
    gao.add_argument("--run-dir", default=None,
                     help="run-local output directory for the snapshot (default: a temp dir)")
    gao.add_argument("--actor", default=None,
                     help="human identity for loopback gate actions "
                          "(default: the checkout's git user.name)")
    # THE INSTALL SHAPE'S FLAG (plan 034 T070; R1Q15 (b), as T007 batch H's
    # 13.4 addendum reads): the documented command is
    # `opendox generate-and-open --local …`. The same selection as
    # `OPENDOX_INSTALL_MODE=local`; with neither the install is hosted, and the
    # flag beside `OPENDOX_INSTALL_MODE=hosted` is refused.
    gao.add_argument(runtime_config.LOCAL_FLAG, action="store_true",
                     dest="local",
                     help="the LOCAL single-user install: no identity broker, "
                          "loopback only (the same selection as "
                          "OPENDOX_INSTALL_MODE=local; with neither, the "
                          "install is hosted and needs its broker's issuer)")
    gao.add_argument("--host", default=serve_mod.DEFAULT_HOST,
                     help="bind host (default: 127.0.0.1, loopback only)")
    gao.add_argument("--port", type=int, default=0, help="bind port (default: ephemeral)")
    gao.add_argument("--no-open", action="store_true", help="do not launch a browser (print the URL only)")
    gao.add_argument("--no-serve", action="store_true",
                     help="generate + print the URL, then exit without serving (non-blocking)")
    # The model adapter's SESSION ROOT — the third install-time input the
    # entrypoint's `model_port_factory` declaration needs, beside its catalog
    # and its launch config (see the `build_server` call in
    # `cmd_generate_and_open`). A PATH ARGUMENT, defaulted like the others: with
    # no flag it sits beside the served snapshot, in the run directory this
    # process already owns, so a harness child writes into scratch space rather
    # than into the served checkout.
    gao.add_argument("--model-session-root", default=None,
                     help="where the model adapter's harness sessions live "
                          f"(default: <run-dir>/{install_mod.MODEL_SESSIONS_DIRNAME})")
    gao.set_defaults(func=cmd_generate_and_open)

    create = sub.add_parser(
        "create", help="scaffold a new header-compliant document and open it for editing")
    create.add_argument("--repo-root", required=True, help="repository to scaffold into")
    create.add_argument("--area", default=authoring_mod.DEFAULT_AREA,
                        help=f"target ideation area (default: {authoring_mod.DEFAULT_AREA})")
    create.add_argument("--title", required=True, help="document title (H1, without the — Brainstorm suffix)")
    create.add_argument("--summary", required=True, help="Summary: one sentence")
    create.add_argument("--topics", required=True, help="comma-separated Topics: list")
    create.add_argument("--repository-context", required=True, help="Repository context: value")
    create.add_argument("--kind", default=authoring_mod.DEFAULT_KIND, help="Kind: value")
    create.add_argument("--possible-feat", action="append", default=[],
                        help="a ## Possible feats bullet (repeatable)")
    create.add_argument("--editor", default=None, help="override $EDITOR / xdg-open")
    create.add_argument("--no-open", action="store_true", help="scaffold only; do not launch an editor")
    create.set_defaults(func=cmd_create)

    edit = sub.add_parser(
        "edit", help="select-to-edit: launch the human's editor over a listed document")
    edit.add_argument("--repo-root", required=True, help="the pinned checkout root")
    edit.add_argument("path", help="repo-relative path to the document")
    edit.add_argument("--editor", default=None, help="override $EDITOR / xdg-open")
    edit.add_argument("--no-open", action="store_true", help="print the resolved path only")
    edit.set_defaults(func=cmd_edit)

    # `model-binding` (openDox's provider column), at the position it has always
    # been registered in. It used to be the opening line of
    # `_add_gate_subcommands` — an accident of growth, not a coupling — so § 2.4
    # calls it from here rather than letting it travel into openXdox's column
    # with the gate verbs.
    _add_model_binding_parser(sub)

    # ...and then `gate` (openXdox's column), CONTRIBUTED. These were a call to
    # `_add_gate_subcommands(sub)` on this line; they now reach the parser
    # through the extension point like any other contribution — the same `sub`,
    # the same `add_parser`, the same `set_defaults(func=...)`, at the same
    # ordinal — which is why the help text is byte-identical to the one that
    # preceded the seam.
    subcommand_extension.register_all(
        profile_openxfactory.SUBCOMMAND_EXTENSIONS, sub)
    subcommand_extension.register_all(subcommand_extensions, sub)
    return parser


def _command_label(args: argparse.Namespace) -> str:
    """`gate ratify`-style label for a refusal line."""
    parts = [getattr(args, "command", None), getattr(args, "gate_command", None)]
    return " ".join(p for p in parts if p) or "command"


def main(argv: list[str] | None = None, *,
         subcommand_extensions: tuple = ()) -> int:
    """The entrypoint, unchanged except that it PASSES THROUGH what it was
    assembled with (§ 2.4).

    The dispatch below needs no clause of its own: a contributed subcommand set
    `func` on the same subparsers action every core one does, so `args.func(args)`
    dispatches both by the identical line. That is the point of handing the real
    parser to the extension rather than a wrapper."""
    # The process entry point registers openDox's own default where no host has
    # (R1Q3 (a)), exactly where a host would register its own.
    domain_profile.register_default(default_profile)
    # AND its own default home corpus (4.1a, T022, same ruling), exactly
    # where a host would register its own adapter. `build_parser()` below
    # makes the identical call as its own first statement, so this one is a
    # no-op once that runs; it is kept for the same reason T016 keeps its
    # own match here: the OUTERMOST entry point states the contract on its
    # own, independent of what `build_parser()` does inside.
    corpus_adapter.register_default_home(_default_home_factory)
    # AND openDox's own snapshot generator (5.4, T052), the same way.
    generator_seam.register_default(default_generator.GENERATOR)
    # AND openDox's own projection defaults (5.5, T055), the same way.
    projection_seams.register_defaults()
    # AND openDox's own doxBench defaults (4.3, T085), the same way.
    doxbench_defaults.register_defaults()
    # AND the consumer columns' defaults (plan 034 T084; #1144 4.3,
    # R1Q10 (a)): the gate primitives, the doxBench scope, kickoff and
    # the cross-reference register, the same way.
    column_seams.register_defaults()
    args = build_parser(
        subcommand_extensions=subcommand_extensions).parse_args(argv)
    try:
        return args.func(args)
    except actor_mod.ActorUnauthenticated as exc:
        # The unauthenticated-`--actor` gap, refused at the OUTERMOST edge: the
        # claim is checked where it enters and the command never reaches a write.
        # One catch site rather than a return code at nine gate constructions, so
        # no future gate verb can be added that forgets to check.
        print(f"{_command_label(args)} refused: {exc}", file=sys.stderr)
        return 1
    except GeneratedAtRefused as exc:
        # Same altitude and same exit status as the `--repo-root` refusal below:
        # a generation anchor that was TYPED and is malformed ends the run on
        # stderr, rather than degrading to a stamp that is quietly absent.
        print(str(exc), file=sys.stderr)
        return 1
    except SourceOptionRefused as exc:
        # An EMPTY `--project-register`/`--possibles`, refused before
        # anything is generated or written (the holder, 2026-09-28): the
        # option was typed, so it is neither dropped nor read as `.`.
        print(f"{_command_label(args)} refused: {exc}", file=sys.stderr)
        return 1
    except RepoRootRefused as exc:
        # The refusal is the whole message (the registered corpus-root
        # predicate's `corpus_root_refusal`); stderr and a non-zero status, so
        # a wrapper script cannot mistake a refused run for a generated
        # snapshot.
        print(str(exc), file=sys.stderr)
        return 1
    except (generator_seam.GeneratorSeamError,
            projection_seams.ProjectionSeamError,
            corpus_adapter.CorpusRefused) as exc:
        # A SEAM'S REFUSAL, reported like every refusal above (plan 034
        # T055): the generator seam's (an input the registered generator does
        # not declare, or a projection that cannot be made, such as a checkout
        # with neither a pinned nor a resolvable revision), the projection
        # seams', and the home corpus's own refusal of the tree it was handed.
        # Each is raised before anything is written, so the run leaves no
        # snapshot to be mistaken for a result.
        print(f"{_command_label(args)} refused: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# THE MOVED SURFACE, RE-EXPORTED (`split-opendox-two-layer-product` § 2.4,
# PR 4 of 4)
#
# The verbs below now live in the column modules beside this one, and are bound
# back onto `cli` because THIS module is the name every caller already holds:
# `build_parser` sets `func=cmd_create`, and the suite asserts `args.func is
# cli_mod.cmd_gate_edit_document`. A re-export keeps those identities exact —
# the same function object under both names — so the move is invisible to every
# caller, which is the whole claim this PR makes.
#
# At the BOTTOM of the file on purpose: the column modules resolve this module
# lazily (`_core()`), so the direction of the dependency is decided here, once,
# and neither import order can produce a half-initialised module. RELATIVELY,
# for the reason given above the `profile_openxfactory` import: the columns a
# core re-exports must be the columns of its OWN package spelling.
# ---------------------------------------------------------------------------

# THE NINETEEN GATE VERBS ARE NO LONGER RE-EXPORTED HERE (BUILD slice 2b). The
# block was `from openxdox.cli_gate import (...)` — nineteen names bound back
# onto this module at import time, which is the single largest reason
# `import opendox.cli` required the layer that PINS openDox.
#
# They are a CONTRIBUTION, not a core name, which is what makes deleting them
# right rather than merely convenient: `cli_gate.GateSubcommands.register()`
# attaches every one of them to the very `sub` action built above, through
# `subcommand_extension` (§ 2.4), so `args.func` already carries the function
# OBJECT and `openxdox.cli_gate.cmd_gate_*` is the name that holds it. A late
# stand-in was considered and refused: it would answer the call and break
# `args.func is cli_mod.cmd_gate_edit_document`, which is the identity the
# re-export existed to keep — a proxy here would look like it worked.
#
# Nothing under `src/opendox/` read any of the nineteen. OWED, and it is
# openXdox-code's to pay under a declared line of its own: four carved suites
# there still spell four verbs through this module — `test_session_verbs.py`
# :689, :784, :1174, :1252; `test_session_gates.py` :587, :652, :662, :2137;
# `test_readiness_gate.py` :239; `test_staging_workbench.py` :773, :1658-:1660
# — at lines that repository's manifest rows do not declare. None is collected
# today (its `validate` runs two shape suites `--noconftest`), so the
# respelling belongs to the act that un-ignores them.
from .cli_model_binding import (  # noqa: E402,F401
    _add_model_binding_parser, cmd_model_binding_add, cmd_model_binding_edit,
    cmd_model_binding_list, cmd_model_binding_remove,
    cmd_model_binding_set_credential,
)
from .cli_project import (  # noqa: E402,F401
    cmd_create, cmd_edit, cmd_generate,
)

