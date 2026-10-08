"""The ONE lifecycle CLI: `runtime init | migrate | serve | status | reset`.

WHERE THESE VERBS ARE REGISTERED, AND WHY IT IS NOT `opendox.cli.build_parser`.
The tree carries two seams and a recorded rule, and they point three different
ways, so the decision is written down rather than implied.

  * `src/subcommand_extension.py` is the extension point "how a layer ABOVE the
    command line CONTRIBUTES a subcommand instead of forking the parser"
    (§ 2.4, design § D2). It is for the layer that PINS openDox — openXdox —
    and the runtime is not that layer.
  * `src/opendox/cli_project.py` states the counter-rule for openDox's own
    verbs, in terms: "FIXED CORE, NOT AN EXTENSION. Design § D2 files the
    project cluster in the openDox column … so these verbs are registered by
    `build_parser` directly". By that rule the runtime verbs belong in
    `opendox.cli.build_parser`.
  * And they could not go there in THAT act, for two measured reasons, and
    NEITHER holds any longer (RULED R1Q22 (a), openxFactory#656 comment
    `5817152735`; plan 034 T011). `src/opendox/cli.py` is a CARVED file with a
    row in openxFactory's `docs/opendox-carve-manifest.yaml`; at the time, a
    line added to it needed a DECLARED EDIT landed as a row annotation at
    openxFactory first, and R1Q22 (a) has since settled that no per-slice
    declared-edit act precedes an arc edit to a carved file. And `opendox.cli`
    could not be imported at this leg at all: it reached `opendox.serve`,
    whose line 192 (`from ideation_dashboard import serve_openxfactory_lanes`)
    existed at neither carve destination — `tests/test_consumer_reach.py`'s
    `STILL_REACHING` recorded exactly that, and RULED Q-L5 (b′) said the
    remaining narrowing would lift with the BUILD arc. Plan 034 T011 was that
    act: the reach is gone, and `opendox.cli` imports standalone. A lifecycle
    CLI that could only be invoked once an unrelated import was repaired would
    have been a runtime nobody could operate, which is why this act shipped
    both spellings rather than wait for that repair.

SO THIS ACT SHIPS BOTH SPELLINGS AND NEITHER IS A FORK. :func:`build_parser`
below builds the `runtime` command; `[project.scripts] opendox-runtime` runs it
directly and works today; and :class:`RuntimeSubcommand` wraps the SAME
registration function in an object that structurally conforms to
`subcommand_extension.SubcommandExtension`, asserted with `isinstance` in
`tests_runtime/test_runtime_cli.py`. `opendox.cli` is importable now (plan 034
T011), and the verbs ARE wired into it, through openDox's OWN default profile
(`opendox.default_profile`, plan 034 T015), which carries `RuntimeSubcommand`
in its `SUBCOMMAND_EXTENSIONS` and which `opendox.cli.build_parser()` and
`main()` register automatically wherever no host has (plan 034 T016) — the
exact assembly-point call this paragraph once said a future act would make,
`build_parser(subcommand_extensions=(RuntimeSubcommand(),))`, now made for
every standalone build instead of by a caller. No verb is re-authored either
way. That is the seam used for what it is for, without pretending the runtime
is a layer above.

AND THAT IS THE RULED SHAPE, not this act's preference. RULED openxFactory#656
comment `5701772032` (Brett Heap, 2026-09-16, by interactive multi-choice)
answered Q-R4: the verbs would be wired into `opendox.cli` once the BUILD arc
repaired `opendox.serve`, and `opendox-runtime` would be the spelling until
then. Plan 034 carried that out, though not by editing `opendox.cli` itself:
`opendox.default_profile` (T015) puts `RuntimeSubcommand` in its own
`SUBCOMMAND_EXTENSIONS`, `opendox.cli.build_parser()` and `main()` register
that default wherever no host has registered its own (T016), and `opendox`
(T038, the `[project.scripts]` entry in `pyproject.toml`) is the console
script that reaches it. So the seam above stays a seam, and both spellings now
start the runtime — `opendox runtime …` through the default profile, and
`opendox-runtime` directly and unconditionally, exactly as it always has;
neither is provisional and neither is a fork.

EVERY VERB PRINTS MACHINE-READABLE, REDACTED EVIDENCE and exits nonzero on a
refusal, which is the Hermes install's lifecycle contract ("Each verb prints
its redacted machine-readable evidence (JSON) and exits nonzero on a
refused/failed outcome"). No DSN, no token and no password is ever printed:
`config.SECRET_NAMES` is the list and `_redacted_settings` is the only place
settings become output.

IMPORT WEIGHT. This module imports the standard library and
`opendox.runtime.{config,migrations}` only. `db`, `app` and `oidc` are imported
INSIDE the verbs that need them, so `opendox runtime status` can tell a reader
that the `runtime` extra is not installed instead of failing with the same
ImportError it was about to explain.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import stat
import sys
import traceback
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from opendox.runtime import identity, migrations
from opendox.runtime.config import (
    INSTALL_MODE_LOCAL,
    LOCAL_FLAG,
    SECRET_NAMES,
    SETTINGS,
    ConfigurationError,
    redacted_url,
    RuntimeSettings,
    install_mode,
    load_migration_settings,
    load_settings,
    migration_database_url,
)

#: The `runtime` verb set, closed and in lifecycle order. Read by
#: `tests_runtime/test_runtime_cli.py` against the parser the module builds.
VERBS: tuple[str, ...] = ("init", "migrate", "serve", "status", "reset")

#: The `project` verb set — `split-opendox-two-layer-product` § 3.6's
#: first-class act and the two verbs RULING C3 puts after it. Closed for the
#: same reason and read by the same test.
PROJECT_VERBS: tuple[str, ...] = ("create-repository", "attach-remote", "push")

#: What `reset` will not do without being told twice. BYTE-IDENTICAL whatever
#: the verb drops: #1144's F14.1 spells this phrase in its ratified command, so
#: the health tables joining `DROP_ORDER` (plan 038 T042) changed the notes
#: around it and never the phrase.
RESET_CONFIRMATION = "yes-drop-the-coordination-database"

#: THE DROP ORDER, TOPOLOGICAL AND WRITTEN OUT. `reversed(identity.TABLES)`
#: looks like a dependency-safe order and is not: it drops `projects` before
#: `memberships`, and `memberships.project_id` references `projects.id`, so the
#: first install with a single membership in it failed the whole transaction on
#: a foreign key and cleared nothing (Copilot review of openDox-code#25).
#:
#: `cascade` is deliberately still NOT used. A `drop table … cascade` would
#: succeed in any order and would also silently take anything ELSE that
#: referenced these tables with it; the point of an explicit order is that a
#: table this list does not know about keeps the drop honest by failing it.
DROP_ORDER: tuple[str, ...] = (
    # THE HEALTH STORE FIRST (`0003_`; R2Q13 (a): DOMAIN, and as disposable as
    # the six, #1144 box 14.3). A finding references its run and nothing else
    # references either.
    "health_findings",        # references health_runs
    "health_runs",
    "drafts",                 # references sessions, projects
    "sessions",               # references users, projects
    "project_repositories",   # references projects
    "memberships",            # references users, projects
    "projects",               # references users
    "users",
    # THE LEDGER'S NAME FROM ITS OWN MODULE, not a second spelling of it. The
    # literal here and `migrations.LEDGER_TABLE` were one name written twice,
    # and the one place they would ever disagree is a rename — after which
    # `reset` would drop six of seven tables and report all seven (Copilot
    # review of openDox-code#25, round 9).
    migrations.LEDGER_TABLE,
)


#: Anything shaped like a connection string or a credential-bearing URL. A
#: driver's error message quotes the DSN it could not reach — "connection to
#: server at ... failed", "invalid dsn: ..." — and an evidence object that
#: printed it would put the database password in a log, which is exactly what
#: the lifecycle contract's "redacted" forbids (Copilot review of
#: openDox-code#25).
_DSN_SHAPED = re.compile(
    # USERINFO ENDS AT THE FIRST `@` AND CANNOT CONTAIN `/`, which is what lets
    # these two branches absorb a SPACE inside it. `\S*` stopped at the first
    # whitespace, so a driver quoting back a URI whose password was never
    # percent-encoded — `postgresql://opendox:hunter 2@db.internal/opendox`,
    # which is exactly the conninfo an operator mistypes — was redacted to
    # `<redacted> 2@db.internal/opendox`: the tail of the password and the
    # whole host, printed beside the marker that says the credential was
    # removed (Copilot review of openDox-code#25, round 29, suppressed). It is
    # the URI form of round 19's `password='secret value'`.
    #
    # AND THE DSN BRANCH RUNS TO THE LAST `@` ON THE LINE, which is a
    # deliberate trade and not an oversight. Round 29 excluded `/` from the
    # userinfo to bound the match, and round 33 showed what that bound leaks:
    # a password holding BOTH a `/` and a space —
    # `postgresql://opendox:pa/ss word@db.internal/opendox` — fell to the
    # plain branch, which stops at the space, and the message kept
    # `word@db.internal/opendox`: the tail of the password and the whole
    # destination. Two spaces did the same to the round-29 form
    # (`my pass word@host`). There is no pattern that both absorbs arbitrary
    # userinfo and stops before an unrelated later `@`, so this takes the
    # act's own stated rule — "a truncated message must redact MORE rather
    # than less" — and over-redacts: a line holding a DSN and a later `@`
    # loses the text between them. `[^\n]*` never crosses a newline, so a
    # multi-line error keeps every other line.
    r"(?i)\b(?:postgres(?:ql)?|postgresql\+\w+)://[^\n]*@\S*"
    r"|\b(?:postgres(?:ql)?|postgresql\+\w+)://\S*"
    r"|[A-Za-z][A-Za-z0-9+.\-]*://[^/@\n]*@\S*"
    # A LIBPQ KEYWORD/VALUE PASSWORD, IN THE FORMS LIBPQ ITSELF ACCEPTS. The
    # first cut was `password\s*=\s*\S+`, which ends at whitespace — and libpq
    # documents that a value CONTAINING SPACES is written in single quotes,
    # with `\'` and `\\` escaped inside. So the valid conninfo
    # `password='secret value'` matched only `password='secret`, and this
    # module printed `<redacted> value'` — half the password in the evidence,
    # beside the marker that says it was removed (Copilot review of
    # openDox-code#25, round 19). psycopg passes an arbitrary conninfo through
    # and its driver errors quote it back, so this is the shape a real failure
    # takes.
    #
    # THE CLOSING QUOTE IS OPTIONAL and neither quoted form crosses a newline:
    # a truncated message must redact MORE rather than less, and must not
    # swallow the next line of a multi-line error. The double-quoted form is
    # not libpq quoting at all — it is here because a value that opens with `"`
    # is as likely to be a password somebody quoted by hand, and redacting it
    # costs nothing.
    #
    # `sslpassword` IS NAMED, because `\b` before `password` does not reach it
    # (`l` and `p` are both word characters) and a private key's passphrase is
    # the same secret by another keyword.
    r"|\b(?:ssl)?password\s*=\s*"
    r"""(?:'(?:[^'\\\n]|\\.)*'?|"(?:[^"\\\n]|\\.)*"?|\S+)""")


def _safe_message(exc: BaseException, *caller_values: str | None) -> str:
    """An exception's text with every DSN- or credential-shaped run removed.

    Applied to EVERY operational message this CLI emits, rather than to the
    ones somebody remembered: the contract is that evidence is redacted.

    THREE PASSES SINCE ROUND 21, and the first is not a pattern at all: a
    value this CALL was given is removed by identity before any rule is asked,
    because an identifier is not a shape a rule can recognise.

    TWO PASSES, BECAUSE A CREDENTIAL IS NOT ONLY A DSN. `_DSN_SHAPED` covers a
    connection string and a `scheme://user:secret@host` run; it says nothing
    about `?token=…`, which is the other half of the rule
    `local_git_adapter.redact_credentials` holds — and the repository verbs
    route caller-controlled text (a project id, a remote URL from a legacy row)
    through this one helper, so a token in that shape reached the evidence
    object despite the contract above (Copilot review of openDox-code#26,
    round 12). One boundary, both halves; `local_git_adapter` is stdlib-only,
    so this costs the CLI no import weight, and it is imported here rather than
    at module scope so `opendox.runtime.cli`'s own import graph is what
    `tests_runtime/test_runtime_surface.py` already measures.
    """
    from opendox.runtime.local_git_adapter import redact_credentials

    # THE FULL REDACTION RUNS FIRST, AND THE DSN PATTERN IS THE FALLBACK.
    # `_DSN_SHAPED` ends its match at whitespace, so with it applied first a
    # credential holding a space — `postgresql://u:secret value@host`, the very
    # shape round 12 widened the userinfo class to catch — was CUT at the
    # space: `<redacted> value@host`, with half the password printed beside the
    # marker (Copilot review of openDox-code#26, round 15). The general rule
    # matches the whole authority, so it goes first and this only has to cover
    # what it leaves: a DSN with no userinfo at all.
    text = str(exc)
    # AND ANY VALUE THIS CALL WAS GIVEN IS REMOVED BEFORE THE PATTERNS RUN.
    # The patterns recognise URLs and libpq conninfo; a caller-controlled
    # IDENTIFIER is neither, and the repository verbs hand one to a store whose
    # `NotFoundError` echoes it — `project attach-remote --project-id
    # 'user:secret@host/path'` printed `secret` through the generic handler,
    # because that shape matches no rule here (Copilot review of
    # openDox-code#26, round 21). This is the same technique the push refusal
    # already uses for the destination it KNOWS: a value does not have to be
    # recognised when it is known.
    for value in caller_values:
        if value and len(value) >= 2:
            text = text.replace(repr(value), "<caller value>")
            text = text.replace(value, "<caller value>")
    return _DSN_SHAPED.sub("<redacted>", redact_credentials(text))


@contextlib.contextmanager
def redacting_every_log_record() -> Iterator[None]:
    """Run the block with the process's log records passed through the redactor.

    `_safe_message` only reaches what THIS module prints, and `serve` is the
    one verb that hands control to somebody else's logger. Uvicorn logs a
    failed lifespan itself — `logger.error("Application startup failed…",
    exc_info=…)` — BEFORE `cmd_serve` ever reaches its own handler, and psycopg
    puts the whole conninfo in the text of an exception raised for an
    unparsable DSN, so a malformed `OPENDOX_DATABASE_URL` printed its password
    to stderr in a traceback while the JSON beside it was scrupulously redacted
    (Copilot review of openDox-code#25, round 34).

    THE BOUNDARY IS THE RECORD FACTORY, not a filter on the handlers uvicorn
    happens to install. A filter attached to a logger runs only for records
    created ON that logger, a filter attached to a handler covers only that
    handler, and uvicorn's own `dictConfig` replaces the handlers on
    `uvicorn.error` and `uvicorn.access` when `Config` is constructed — so
    every per-handler answer is a list of the loggers somebody remembered.
    `logging.setLogRecordFactory` is the stdlib's one hook that every record
    in the process goes through, whoever creates it and whatever handler later
    emits it, including a handler installed after this point.

    EACH RECORD IS REDACTED IN THREE PLACES, because a formatter can reach the
    exception three ways: the message (and its arguments, which is where a `%s`
    DSN would sit), the stack text, and the traceback. The traceback is
    rendered HERE, redacted, and cached in `exc_text` — where
    `logging.Formatter` uses it instead of formatting `exc_info` again — and
    `exc_info` is then dropped, so a formatter that ignores `exc_text` prints
    nothing rather than the raw exception. The exception object itself is not
    mutated; only this record's rendering of it is.

    RESIDUE, stated rather than implied: a traceback printed by something that
    does not use `logging` is not covered here. The one such path in this verb
    is an exception escaping `server.run()`, which the handler below turns into
    redacted JSON, and `_safe_message` is what renders it.
    """
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.msg = _DSN_SHAPED.sub("<redacted>", str(record.msg))
        if isinstance(record.args, dict):
            record.args = {key: _redacted_arg(value)
                           for key, value in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(_redacted_arg(value) for value in record.args)
        if record.stack_info:
            record.stack_info = _DSN_SHAPED.sub("<redacted>",
                                                record.stack_info)
        if record.exc_info:
            record.exc_text = _DSN_SHAPED.sub("<redacted>", "".join(
                traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return record

    logging.setLogRecordFactory(factory)
    try:
        yield
    finally:
        # A GLOBAL RESTORED ON EVERY PATH. `cmd_serve` is importable and is
        # called in-process by the tests; a factory left installed would
        # redact an unrelated caller's logs for the life of the interpreter.
        logging.setLogRecordFactory(previous)


def _redacted_arg(value: Any) -> Any:
    """One `%`-argument, redacted where it is text and untouched where it is not.

    A number stays a number: `"%d" % "<redacted>"` would raise inside the
    logging machinery, which is a worse failure than the one being prevented.
    """
    if isinstance(value, str):
        return _DSN_SHAPED.sub("<redacted>", value)
    if isinstance(value, BaseException):
        return _safe_message(value)
    return value


def _emit(payload: dict[str, Any], *, ok: bool) -> int:
    """Print one evidence object and return the process exit code."""
    payload = {"ok": ok, **payload}
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0 if ok else 1


def _redacted_settings(settings: RuntimeSettings) -> dict[str, Any]:
    """Every setting's NAME and a value that is safe to print.

    Driven by `config.SETTINGS` rather than by a hand-kept list here, so a new
    setting is redacted by the declaration that introduces it.
    """
    values = {
        "OPENDOX_DATABASE_URL": settings.database_url,
        "OPENDOX_MIGRATION_DATABASE_URL": settings.migration_database_url,
        # THE INSTALL SHAPE this process loaded (plan 034 T070): a name and
        # never a credential, and the first thing an operator reading `status`
        # needs to know, because it decides whether the broker lines below
        # mean anything at all.
        "OPENDOX_INSTALL_MODE": settings.install_mode,
        # WHERE A LOCAL INSTALL'S BUNDLED SERVER LIVES (plan 034 T072): a path
        # and never a credential. Reported for a hosted install too, which
        # never reads it, so the report covers the whole declared list.
        "OPENDOX_STATE_DIR": str(settings.state_dir),
        # THE BROKER URLS ARE REDACTED HERE TOO. `load_settings` refuses
        # userinfo in the issuer and in an explicit JWKS URL — but this report
        # prints a DERIVED value, and a settings object can also be built by
        # hand, so the boundary that prints does not assume the boundary that
        # loads (Copilot review of openDox-code#25, round 22).
        "OPENDOX_OIDC_ISSUER": redacted_url(settings.oidc_issuer),
        "OPENDOX_OIDC_AUDIENCE": settings.oidc_audience,
        "OPENDOX_OIDC_JWKS_URL": redacted_url(settings.jwks_url()),
        "OPENDOX_OIDC_ALGORITHMS": ",".join(settings.oidc_algorithms),
        "OPENDOX_OIDC_JWKS_TTL_SECONDS": settings.oidc_jwks_ttl_seconds,
        "OPENDOX_OIDC_LEEWAY_SECONDS": settings.oidc_leeway_seconds,
        "OPENDOX_BIND_HOST": settings.bind_host,
        "OPENDOX_BIND_PORT": settings.bind_port,
        # Both of these were declared in `SETTINGS` and missing from this map,
        # so `status` reported them as `null` whatever the process was actually
        # configured with — a machine-readable report that described a
        # different process (Copilot review of openDox-code#25). The test below
        # now drives the map from `SETTINGS` so a new setting cannot be added
        # to one and forgotten in the other.
        "OPENDOX_RUNTIME_PG_ROLE": settings.runtime_pg_role,
        # A SCHEMA NAME AND NOT A CREDENTIAL, which is the whole reason the
        # migration workload may be told it — and it is reported, because an
        # operator reading `status` needs to see the declaration the run will
        # be refused against (independent adversarial review of
        # openDox-code#25, A25-3). The test below caught its absence from this
        # map the moment it was declared, which is what that test is for.
        "OPENDOX_SERVED_SCHEMA": settings.served_schema,
        # AND THE DATABASE, for the same reason and reported for the same
        # reason: an operator reading `status` needs to see BOTH declarations
        # the run will be refused against. A25-3 gave the migration workload
        # the served schema and not the served database, which is the wider of
        # the two (openDox-code#26's registered item 4).
        "OPENDOX_SERVED_DATABASE": settings.served_database,
        "OPENDOX_PUBLISH_OPENAPI": settings.publish_openapi,
        "OPENDOX_MIGRATIONS_DIR": str(settings.migrations_dir),
        "OPENDOX_PROJECT_REPOSITORY_ROOT": str(settings.project_repository_root),
    }
    out: dict[str, Any] = {}
    for setting in SETTINGS:
        value = values.get(setting.name)
        if setting.name in SECRET_NAMES:
            out[setting.name] = "<redacted>" if value else None
        else:
            out[setting.name] = value
    return out


def _settings_or_refusal(args: argparse.Namespace) -> RuntimeSettings | int:
    try:
        return load_settings()
    except ConfigurationError as exc:
        return _emit({"verb": args.verb, "refusal": "configuration",
                      "message": _safe_message(exc)}, ok=False)


# -- verbs ------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Prepare an install's LOCAL state: directories, and a coherent config.

    Touches no database on purpose — schema is `migrate`'s act, applied with a
    privileged DSN this verb never reads. What `init` does own is the one piece
    of local state the runtime cannot create later without a race: the
    directory RULING C3's per-project repositories are created under.
    """
    from opendox.runtime import repository_act

    settings = _settings_or_refusal(args)
    if isinstance(settings, int):
        return settings
    created: list[str] = []
    root = Path(settings.project_repository_root)
    # A ROOT THAT IS NOT A DIRECTORY IS A REFUSAL, not a silent success. The
    # first cut only asked `exists()`, so a regular file (or a symlink to one)
    # at `OPENDOX_PROJECT_REPOSITORY_ROOT` skipped the `mkdir` and `init`
    # reported a valid install that repository creation would later have no
    # directory to use (Copilot review of openDox-code#25). `exists()` follows
    # symlinks, which is the right question here: what matters is what the
    # path RESOLVES to when § 3.6 creates a repository under it.
    if root.exists() and not root.is_dir():
        return _emit({"verb": "init", "refusal": "root-not-a-directory",
                      "project_repository_root": str(root),
                      "message": f"{root} exists and is not a directory; "
                                 "OPENDOX_PROJECT_REPOSITORY_ROOT names the "
                                 "directory per-project repositories are "
                                 "created under (RULING C3)"}, ok=False)
    if not root.exists():
        try:
            # 0700, NOT THE AMBIENT UMASK. This directory holds every project's
            # bare repository, and each of those is created
            # `REPOSITORY_DIRECTORY_MODE` — but the ROOT above them took
            # `mkdir`'s default, which is `0o777 & ~umask`: MEASURED under the
            # container's own umask (0o022) `runtime init` left it **0755**, so
            # every project name under it was listable, and traversable, by any
            # local account (Copilot review of openDox-code#26 registered this
            # as `local_git_adapter.py:465`; the holder ruled "measure first,
            # fix only if a reachable path leaves it wider than 0700", and this
            # is that path). A mode of 0o700 is umask-SAFE, because a umask can
            # only remove bits.
            #
            # THE LEAF ONLY, WHICH IS WHAT `Path.mkdir` DOES: parents are
            # created by a recursive call that does not carry `mode`, and they
            # are the operator's own path components — `/srv`, `/var/lib` —
            # not this runtime's directory to narrow.
            root.mkdir(parents=True, exist_ok=True,
                       mode=repository_act.REPOSITORY_DIRECTORY_MODE)
        except OSError as exc:
            return _emit({"verb": "init", "refusal": "root-uncreatable",
                          "project_repository_root": str(root),
                          "message": _safe_message(exc)}, ok=False)
        created.append(str(root))
    try:
        digest = migrations.verify_canonical_digest(settings.migrations_dir)
    except migrations.MigrationError as exc:
        return _emit({"verb": "init", "refusal": "canonical-schema",
                      "message": _safe_message(exc)}, ok=False)
    pending = [m.version for m in migrations.discover_migrations(settings.migrations_dir)]
    # AND AN EXISTING ROOT IS REPORTED, NOT RE-MODED. `runtime init` is
    # idempotent and a root that is already there belongs to whoever made it —
    # an operator's own mount point among them — so this act says what it found
    # rather than changing it, on `_directory_by_name`'s rule that a walk
    # narrows only what it made itself. An operator upgrading from a build that
    # created the root 0755 sees the number here and decides.
    try:
        mode = f"{stat.S_IMODE(root.stat().st_mode):04o}"
    except OSError:                      # pragma: no cover - raced away
        mode = None
    return _emit({"verb": "init",
                  "project_repository_root": str(root),
                  "project_repository_root_mode": mode,
                  "directories_created": created,
                  "canonical_sha256": digest,
                  "migrations_on_disk": pending,
                  "next": "opendox-runtime runtime migrate"}, ok=True)


def _local_bundle_refusal(settings) -> str | None:
    """For a LOCAL install, why its socket must not be connected to, or `None`.

    `bundle.refusal_before_connecting`: the tree check a start asks, and a
    live server of THIS data directory behind the socket, both before any
    client connection (adversarial review of openDox-code#69). A hosted
    install's DSN is the operator's, and is not judged here.
    """
    if settings.install_mode != INSTALL_MODE_LOCAL:
        return None
    from opendox.runtime import bundle as bundle_mod
    from opendox.runtime.config import database_bundle

    reason = bundle_mod.refusal_before_connecting(
        database_bundle(settings.state_dir))
    return None if reason is None else _safe_message(reason)


def cmd_migrate(args: argparse.Namespace) -> int:
    """Apply the ordered SQL, or with `--plan` report what would be applied.

    `--plan` needs the database (the ledger says what is already applied) and
    changes nothing.
    """
    try:
        settings = load_migration_settings()
        dsn = migration_database_url(settings)
    except ConfigurationError as exc:
        return _emit({"verb": "migrate", "refusal": "configuration",
                      "message": _safe_message(exc)}, ok=False)
    # THE CANONICAL GATE RUNS BEFORE THE DATABASE IS EVEN IMPORTED, for both
    # `--plan` and a real run. `apply()` runs it first "so a tree carrying the
    # wrong `0001` changes nothing at all", and `--plan` skipped it entirely —
    # an operator could be shown a plan for a tree the very next command
    # refuses (Copilot review of openDox-code#25, round 7). Asking about the
    # TREE needs no driver and no server, so it is asked where the answer
    # costs nothing and is the same in every environment. An install without
    # the `runtime` extra reaches it too, as the required `validate` job did
    # until plan 034 T036, and a gate behind the extra would have been a gate
    # such an install could not reach.
    try:
        migrations.verify_canonical_digest(settings.migrations_dir)
    except migrations.MigrationError as exc:
        return _emit({"verb": "migrate", "refusal": type(exc).__name__,
                      "message": _safe_message(exc)}, ok=False)
    try:
        from opendox.runtime.db import Database
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": "migrate", "refusal": "runtime-extra-missing",
                      "message": f"{_safe_message(exc)}; install this "
                                 "package with the `runtime` extra: "
                                 "pip install '.[runtime]'"},
                     ok=False)
    refusal = _local_bundle_refusal(settings)
    if refusal is not None:
        return _emit({"verb": "migrate", "refusal": "local-bundle-unverified",
                      "message": refusal}, ok=False)
    runner_db = Database(dsn, application_name="opendox-runtime-migrate",
                         checkout_timeout=args.connect_timeout)
    # THE OUTCOME IS COMPUTED INSIDE THE CONTEXT AND EMITTED OUTSIDE IT. A
    # `return _emit(...)` inside `with runner_db:` reports success before the
    # context has closed, so a failure in the close would print a second,
    # contradicting record (Copilot review of openDox-code#26 made the same
    # point about the § 3.6 verbs, and it applies here).
    try:
        with runner_db:
            runner = migrations.MigrationRunner(
                runner_db, migrations_dir=settings.migrations_dir,
                runtime_role=settings.runtime_pg_role,
                served_schema=settings.served_schema,
                served_database=settings.served_database)
            if args.plan:
                # The canonical gate has already run, above, for this path and
                # for the real one.
                #
                # AND THE SERVED-SCHEMA GUARD RUNS HERE TOO. It lived in
                # `apply()` alone, so `--plan` printed a plan for a run that
                # would refuse — a preview that does not describe an
                # executable run is worse than no preview, because it is the
                # answer an operator checks BEFORE committing to the real one
                # (Copilot review of openDox-code#25, at `056d1597`). One
                # connection for the guard and the plan, so the answer and the
                # thing it was asked of are the same session.
                with runner_db.connection() as conn:
                    runner.refuse_a_database_the_api_will_not_read(conn)
                    runner.refuse_a_schema_the_api_will_not_read(conn)
                    planned = [m.version for m in runner.plan(conn)]
                evidence = {"verb": "migrate", "planned": planned,
                            "applied": []}
            else:
                evidence = {"verb": "migrate", "planned": [],
                            "applied": runner.apply()}
    except migrations.MigrationError as exc:
        return _emit({"verb": "migrate", "refusal": type(exc).__name__,
                      "message": _safe_message(exc)}, ok=False)
    # EVERY OPERATIONAL FAILURE IS EVIDENCE TOO, not a traceback: a pool
    # timeout, a refused connection, a permission error and a SQL error all
    # reach an operator through the same one redacted object the lifecycle
    # contract promises — and REDACTED is the operative word. A driver's
    # connection error quotes the DSN it could not reach, which is the one
    # string in this process that must never be printed (Copilot review of
    # openDox-code#25).
    except Exception as exc:  # noqa: BLE001
        return _emit({"verb": "migrate", "refusal": type(exc).__name__,
                      "message": _safe_message(exc)}, ok=False)
    return _emit(evidence, ok=True)


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the API. The pool is opened by the application's lifespan.

    NOT IN A LOCAL INSTALL (plan 034 T070; a holder reading on
    openxFactory#656 that Brett may overrule). Every `/api/v1` route verifies
    a token the BROKER signed (`oidc.build_verifier`), and the local mode has
    no broker (#1144 13.4), so there is no identity this API could serve
    with: started anyway, it would either refuse every request or, worse,
    stand a local principal up that no task text defines. A local install is
    served by `opendox generate-and-open --local`, and in release 1 its
    document surface reads nothing from the store (R1Q16 (ii)). Refused
    BEFORE anything is imported or bound, as evidence like every refusal.
    """
    settings = _settings_or_refusal(args)
    if isinstance(settings, int):
        return settings
    if settings.install_mode == INSTALL_MODE_LOCAL:
        return _emit({"verb": "serve", "refusal": "local-mode-has-no-broker",
                      "message": "the runtime API authenticates every request "
                                 "with a token its identity broker signed, "
                                 "and a LOCAL install has no broker, so this "
                                 "API has no identity to serve with. A local "
                                 "install is served by `opendox "
                                 f"generate-and-open {LOCAL_FLAG}`; the "
                                 "runtime API is a HOSTED install's surface "
                                 "(13.4)"}, ok=False)
    try:
        import uvicorn

        from opendox.runtime.app import create_app
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": "serve", "refusal": "runtime-extra-missing",
                      "message": f"{_safe_message(exc)}; install this "
                                 "package with the `runtime` extra: "
                                 "pip install '.[runtime]'"},
                     ok=False)
    app = create_app(settings=settings)
    # AN EXPLICIT `Server`, BECAUSE `uvicorn.run` SWALLOWS A STARTUP FAILURE.
    # A lifespan that raises — an unreachable database, a broker that will not
    # answer — is LOGGED by uvicorn and the server loop simply returns, so the
    # branch below emitted `ok: true` and exited 0 for a process that never
    # served a request: the lifecycle contract says a failed verb prints a
    # refusal and exits nonzero, and this was the one verb that could not
    # (Copilot review of openDox-code#25, round 8). `Server.started` is
    # uvicorn's own answer to "did startup complete", and it is False in
    # exactly that case.
    # THE BOUNDARY IS INSTALLED BEFORE `Config`, WHICH IS WHERE UVICORN
    # CONFIGURES LOGGING, and it stays up for the whole of `run()` — the
    # failed lifespan whose traceback carried the conninfo is logged from
    # inside that call (Copilot review of openDox-code#25, round 34).
    with redacting_every_log_record():
        server = uvicorn.Server(uvicorn.Config(
            app, host=settings.bind_host, port=settings.bind_port,
            log_level=args.log_level))
        # A BIND FAILURE IS EVIDENCE TOO — and it is the failure an operator meets
        # first. `Server.run()` RAISES for an address it cannot use: `SystemExit`
        # from uvicorn's own `sys.exit(1)` on an occupied port, `OSError` for an
        # address that is not this host's. This call sat outside every
        # exception-to-evidence handler, so the verb an operator runs longest
        # answered a misconfigured port with a traceback and no JSON at all, which
        # is the same lifecycle-contract hole round 8 closed for the SILENT startup
        # failure beside it (Copilot review of openDox-code#25, round 10,
        # suppressed). `SystemExit` is named explicitly because it is a
        # `BaseException` and `except Exception` does not reach it.
        try:
            server.run()
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            detail = _safe_message(exc)
            return _emit({"verb": "serve", "refusal": "serve-failed",
                          "bind_host": settings.bind_host,
                          "bind_port": settings.bind_port,
                          "message": (f"{type(exc).__name__}: {detail}" if detail
                                      else type(exc).__name__)}, ok=False)
    if not getattr(server, "started", False):
        return _emit({"verb": "serve", "refusal": "startup-failed",
                      "bind_host": settings.bind_host,
                      "bind_port": settings.bind_port,
                      "message": "the application's startup did not complete, "
                                 "so nothing was served; uvicorn's log carries "
                                 "the reason (a dependency the lifespan could "
                                 "not reach is the usual one)"}, ok=False)
    # EVERY LIFECYCLE VERB EMITS A JSON EVIDENCE OBJECT, INCLUDING THIS ONE.
    # `serve` was the single verb that returned 0 and printed nothing after a
    # normal shutdown, which made the CLI's own contract false for the one verb
    # an operator runs longest (Copilot review of openDox-code#25). This is the
    # ORDINARY exit, and it says what was served and that it stopped.
    return _emit({"verb": "serve", "state": "stopped",
                  "bind_host": settings.bind_host,
                  "bind_port": settings.bind_port,
                  "message": "the server returned from uvicorn; the process is "
                             "exiting normally"}, ok=True)


def _report_the_local_broker(report: dict[str, Any]) -> None:
    """What `status` says of a LOCAL install's broker, on every path.

    Its broker is NOT CONFIGURED (plan 034 T070; #1144 13.4): a statement
    about the install's configuration rather than a probe's result, so there
    is no discovery URL to report and nothing counts against `ok`. `status`
    returns from two places, and both write it here, so the two answers
    cannot drift apart (Copilot review of openDox-code#67).
    """
    report["broker_keys"] = "not configured (local mode)"
    report["broker_discovery"] = None


def cmd_status(args: argparse.Namespace) -> int:
    """Report, never change: configuration, the schema pin, the ledger, the broker.

    Every dependency is probed SEPARATELY and reported by name. A status verb
    that failed on the first missing thing would tell an operator about the
    database and nothing about the broker, which is the one moment both answers
    are wanted at once.
    """
    report: dict[str, Any] = {"verb": "status"}
    ok = True
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        return _emit({"verb": "status", "refusal": "configuration",
                      "message": _safe_message(exc)}, ok=False)
    report["settings"] = _redacted_settings(settings)
    # THE BUNDLED SERVER THIS INSTALL OWNS (plan 034 T072; #1144 13.1): where
    # its data directory and socket are, and the pid of the server running on
    # them, read from the server's own `postmaster.pid`. `null` for a hosted
    # install, which brings no server. Reported, never started: `status`
    # changes nothing, and the process that owns the server is the document
    # server that started it (R1Q16 (i)).
    if settings.install_mode == INSTALL_MODE_LOCAL:
        from opendox.runtime import bundle as bundle_mod
        from opendox.runtime.config import database_bundle

        report["database_bundle"] = bundle_mod.report(
            database_bundle(settings.state_dir))
    else:
        report["database_bundle"] = None

    try:
        report["canonical_sha256"] = migrations.verify_canonical_digest(
            settings.migrations_dir)
        report["canonical_schema"] = "pinned"
    except migrations.MigrationError as exc:
        report["canonical_schema"] = f"refused: {_safe_message(exc)}"
        ok = False

    report["coordination_tables"] = list(identity.TABLES)

    try:
        from opendox.runtime.db import Database
    except ImportError as exc:
        report["runtime_extra"] = f"absent: {_safe_message(exc)}"
        report["database"] = "not probed"
        # A LOCAL INSTALL'S BROKER IS NOT CONFIGURED WHETHER OR NOT THE EXTRA
        # IS PRESENT (plan 034 T070; Copilot review of openDox-code#67). That
        # answer comes from its configuration, not from a probe, so this early
        # return gives the same one the full report gives below. A hosted
        # install's broker was never probed, and says so, as before.
        if settings.install_mode == INSTALL_MODE_LOCAL:
            _report_the_local_broker(report)
        else:
            report["broker_keys"] = "not probed"
        return _emit(report, ok=False)
    report["runtime_extra"] = "present"

    connected = False
    # A LOCAL INSTALL'S SOCKET IS JUDGED BEFORE IT IS CONNECTED TO
    # (adversarial review of openDox-code#69): the tree a start checks, and a
    # live server of this data directory behind it. Otherwise `status` asks
    # whatever answers at that path, as the served role.
    refusal = _local_bundle_refusal(settings)
    if refusal is not None:
        report["database"] = f"not probed: {refusal}"
        ok = False
    else:
        try:
            # INSIDE the context, all of it. `runner.applied()` and `runner.plan()`
            # each check a connection out of the pool, so calling them after the
            # `with` had closed it raised `PoolClosed` and this verb reported a
            # perfectly reachable database as unreachable (Copilot review of
            # openDox-code#25, and it is the kind of defect only a live database
            # shows — every unreachable-database test passed).
            with Database(settings.database_url,
                          checkout_timeout=args.probe_timeout) as db:
                with db.connection() as conn:
                    conn.execute("select 1")
                # THE CONNECTIVITY ANSWER IS RECORDED THE MOMENT IT IS TRUE, so a
                # failure in the queries BELOW cannot rewrite it — see the generic
                # handler at the end of this block.
                connected = True
                # THE SAME CANONICAL GATE `apply()` AND `/readyz` RUN. Without
                # it an EMPTY migrations directory reports `pending: []` on a
                # fresh database — nothing pending, nothing drifted, everything
                # fine — for an install with no coordination schema at all
                # (Copilot review of openDox-code#25, round 7). `status` is the
                # verb an operator believes.
                migrations.verify_canonical_digest(settings.migrations_dir)
                runner = migrations.MigrationRunner(
                    db, migrations_dir=settings.migrations_dir)
                applied = [row.version for row in runner.applied()]
                pending = [m.version for m in runner.plan()]
                drifted = runner.drift()
            report["database"] = "reachable"
            report["applied_migrations"] = applied
            report["pending_migrations"] = pending
            # NOTHING PENDING IS NOT THE SAME AS MATCHING THIS TREE: a migration
            # whose file changed, or vanished, is invisible to `plan()` and is
            # refused by `apply()`. See `MigrationRunner.drift`.
            report["migration_drift"] = drifted
            # PENDING IS UNHEALTHY, exactly as `/readyz` treats it. This reported
            # the versions and left `ok` true, so a reachable but UNMIGRATED
            # database exited 0 while the readiness probe on the same install
            # refuses traffic — two answers to one question, and the CLI's was the
            # comforting one (Copilot review of openDox-code#25, round 7).
            if drifted or pending:
                ok = False
        # a status verb reports, never raises
        except migrations.MigrationError as exc:
            # THE DATABASE ANSWERED; THE TREE DID NOT. `select 1` has already
            # succeeded by the time the runner is asked anything, so reporting
            # `database: unreachable` for a missing or malformed migrations
            # directory pointed the operator at the wrong dependency entirely
            # (Copilot review of openDox-code#25, round 7).
            report.setdefault("database", "reachable")
            report["migrations"] = (
                f"unreadable: {type(exc).__name__}: {_safe_message(exc)}")
            ok = False
        except Exception as exc:  # noqa: BLE001
            # THE SAME DISTINCTION THE BRANCH ABOVE MAKES, for the failures that
            # are not the runner's own. Once `select 1` has answered, the database
            # IS reachable, and a later failure — the served role without `select`
            # on the ledger, a schema the search path does not reach, a query that
            # errors — is a privilege or schema problem reported as one. Reporting
            # `database: unreachable` for it pointed the operator at the network
            # and hid the real fault, which is the defect round 7 fixed for
            # `MigrationError` and left in place one handler down (Copilot review
            # of openDox-code#25, round 10, suppressed).
            if connected:
                report["database"] = "reachable"
                report["schema_queries"] = (
                    f"failed: {type(exc).__name__}: {_safe_message(exc)}")
            else:
                report["database"] = (
                    f"unreachable: {type(exc).__name__}: {_safe_message(exc)}")
            ok = False

    # A LOCAL INSTALL HAS NO BROKER TO PROBE (plan 034 T070; #1144 13.4),
    # and that is its configuration rather than a fault: reported by name, and
    # NOT counted against `ok`, so a healthy local install's `status` exits 0
    # — F13.1 runs it under `set -e`, and a verdict of "unhealthy" for a
    # broker the install was never meant to have would be false.
    if settings.install_mode == INSTALL_MODE_LOCAL:
        _report_the_local_broker(report)
        return _emit(report, ok=ok)
    try:
        from opendox.runtime.oidc import build_verifier

        build_verifier(settings).probe_keys()
        report["broker_keys"] = "reachable"
        report["broker_discovery"] = redacted_url(settings.discovery_url())
    # same
    except Exception as exc:  # noqa: BLE001
        report["broker_keys"] = f"unreachable: {type(exc).__name__}"
        report["broker_discovery"] = redacted_url(settings.discovery_url())
        ok = False

    return _emit(report, ok=ok)


def cmd_reset(args: argparse.Namespace) -> int:
    """DROP the coordination schema. Refuses without the spelled confirmation.

    THIS VERB CAN EXIST AT ALL BECAUSE OF RULING Q1's LAST SENTENCE: "the
    database is disposable relative to the corpus" — "lose it and you lose
    coordination state, not a governed artifact" (design § D5). It drops the
    six coordination tables, the two health tables (`0003_`; R2Q13 (a) makes
    them DOMAIN, and #1144 box 14.3 keeps them as disposable: every result is
    recomputable from git) and the migration ledger, and nothing else; every
    document ever written is in a repository and is not reachable from here.

    The confirmation is a SPELLED PHRASE and not a `--force` flag, because a
    flag is something a shell history repeats by accident.
    """
    if args.confirm != RESET_CONFIRMATION:
        return _emit({"verb": "reset", "refusal": "unconfirmed",
                      "message": f"pass --confirm {RESET_CONFIRMATION} to drop "
                                 f"{list(DROP_ORDER)}"}, ok=False)
    try:
        settings = load_migration_settings()
        dsn = migration_database_url(settings)
    except ConfigurationError as exc:
        return _emit({"verb": "reset", "refusal": "configuration",
                      "message": _safe_message(exc)}, ok=False)
    try:
        from psycopg import sql

        from opendox.runtime.db import Database
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": "reset", "refusal": "runtime-extra-missing",
                      "message": _safe_message(exc)}, ok=False)
    refusal = _local_bundle_refusal(settings)
    if refusal is not None:
        return _emit({"verb": "reset", "refusal": "local-bundle-unverified",
                      "message": refusal}, ok=False)
    try:
        with Database(dsn, application_name="opendox-runtime-reset",
                      checkout_timeout=args.connect_timeout) as db:
            # THE SAME ADVISORY LOCK A MIGRATION RUN TAKES. `reset` drops the
            # very tables `apply()` creates, so a confirmed reset running
            # beside a migration retry could interleave DDL and leave either
            # one failed or the schema in a state neither intended (Copilot
            # review of openDox-code#25). One key, both acts.
            # THE DROPS RUN ON THE CONNECTION THAT HOLDS THE LOCK. They used
            # to run in `db.transaction()`, which checks out a DIFFERENT pool
            # connection — and a session-level advisory lock protects only the
            # session that took it, so a migration run could proceed beside a
            # confirmed reset while this comment claimed both shared one lock
            # (Copilot review of openDox-code#25). `MigrationRunner.apply` had
            # the same shape and was repaired in the same commit.
            with db.connection() as lock:
                lock.execute("select pg_advisory_lock(%s)",
                             (migrations.MIGRATION_LOCK_KEY,))
                lock.commit()
                try:
                    # QUALIFIED WITH THE SELECTED SCHEMA, for the reason
                    # `MigrationRunner.applied` is: a connection's
                    # `search_path` is `<schema>,public`, so an UNQUALIFIED
                    # `drop table if exists users` in a schema that has no
                    # `users` resolves through the fallback and drops
                    # `public.users` — a verb whose whole promise is "this
                    # schema's coordination state and nothing else" quietly
                    # dropping another tenant's table (Copilot review of
                    # openDox-code#25). The identifiers go through
                    # `psycopg.sql`, which is the only safe way to put a name
                    # into DDL, and the schema is reported in the evidence so
                    # an operator can see WHERE the drop landed.
                    #
                    # AND THE SCHEMA IS ASKED OF `selected_schema`, BECAUSE
                    # `current_schema()` IS ITSELF THE FALLBACK: it answers the
                    # first EXISTING schema on the path, so a DSN selecting a
                    # `tenant` that no longer exists qualified every drop as
                    # `public.*` and this verb deleted another install's
                    # coordination tables under a promise that it would not
                    # (Copilot review of openDox-code#25, round 14). Measured
                    # on postgres 16.15; the refusal names both schemas.
                    #
                    # AND THE SERVED-SCHEMA DECLARATION IS ASKED BEFORE THE
                    # FIRST DROP. This verb DELETES the coordination and health
                    # tables in the schema its own DSN selects, and it never
                    # asked: a mispointed migration DSN plus a confirmed
                    # `reset` dropped another schema's coordination state
                    # while `OPENDOX_SERVED_SCHEMA` said in terms that the API
                    # reads a different one — the same invariant `migrate` has
                    # had since A25-3, on the one verb that cannot be undone
                    # (Copilot review of openDox-code#25, at `056d1597`).
                    # AND THE DATABASE DECLARATION BEFORE THE SCHEMA'S, on
                    # the verb that cannot be undone: a schema comparison made
                    # in the wrong DATABASE compares two names that happen to
                    # agree, and this is the act that DROPS the domain's tables.
                    migrations.refuse_a_database_the_api_will_not_read(
                        lock, settings.served_database)
                    migrations.refuse_a_schema_the_api_will_not_read(
                        lock, settings.served_schema)
                    schema = migrations.selected_schema(lock)
                    with lock.transaction():
                        for table in DROP_ORDER:
                            lock.execute(
                                sql.SQL("drop table if exists {}.{}").format(
                                    sql.Identifier(schema),
                                    sql.Identifier(table)))
                    lock.commit()
                finally:
                    lock.rollback()
                    lock.execute("select pg_advisory_unlock(%s)",
                                 (migrations.MIGRATION_LOCK_KEY,))
                    lock.commit()
    except Exception as exc:  # noqa: BLE001
        return _emit({"verb": "reset", "refusal": type(exc).__name__,
                      "message": _safe_message(exc)}, ok=False)
    return _emit({"verb": "reset", "schema": schema,
                  "dropped": list(DROP_ORDER),
                  "note": "coordination state and health results only, in "
                          "this schema alone; every document is in a "
                          "repository (RULING Q1), and every health result is "
                          "recomputable from it (#1144 box 14.3)"},
                 ok=True)


# -- § 3.6, the repository-creation act, as CLI verbs ------------------------
#
# EVERY `except Exception` BELOW REPORTS THROUGH `_safe_message`. These three
# verbs catch their own failures so the evidence object can name the verb, and
# catching before `main()`'s boundary means `main()`'s redaction never runs —
# so a `str(exc)` here put whatever the driver said straight into the JSON, and
# a psycopg connection failure says the DSN, password included (Copilot review
# of openDox-code#26, three times: one thread and two suppressed comments for
# the same shape in three handlers).
#
# AND `RepositoryActRefused` GOES THROUGH IT TOO, which it did not. That
# message is this act's own and was called secret-free by construction — but it
# is not: `repository_location` refuses a project id it cannot use as a
# directory name and ECHOES it, before any database is touched, so
# `opendox-runtime project create-repository --project-id
# 'postgresql://u:p@host/x'` printed the password back in the evidence object
# and into whatever collects it (Copilot review of openDox-code#26, round 10).
# A message built from caller-supplied text is redacted like any other.


def _store_and_settings(args: argparse.Namespace):
    """The settings, a `Database`, and the transaction the act runs in.

    Returns `(settings, Database)` or an exit code already emitted.
    """
    settings = _settings_or_refusal(args)
    if isinstance(settings, int):
        return settings, None
    try:
        from opendox.runtime.db import Database
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": args.verb, "refusal": "runtime-extra-missing",
                      "message": f"{_safe_message(exc)}; install this "
                                 "package with the `runtime` extra: "
                                 "pip install '.[runtime]'"},
                     ok=False), None
    return settings, Database(settings.database_url)


def cmd_create_repository(args: argparse.Namespace) -> int:
    """Create this project's plain local git repository (RULING C3)."""
    from opendox.runtime import repository_act
    from opendox.runtime.identity import CoordinationStore

    settings, database = _store_and_settings(args)
    if database is None:
        return int(settings)
    try:
        with database, database.transaction() as conn:
            created = repository_act.create_repository(
                CoordinationStore(conn), project_id=args.project_id,
                root=settings.project_repository_root, actor=args.actor)
            evidence = {"verb": "create-repository",
                        "project_id": args.project_id,
                        "adapter": repository_act.ADAPTER_NAME,
                        "location": str(created.location),
                        "initial_commit": created.initial_commit}
    except repository_act.RepositoryActRefused as exc:
        return _emit({"verb": "create-repository", "refusal": "repository",
                      "message": _safe_message(exc, args.project_id)},
                     ok=False)
    except Exception as exc:  # noqa: BLE001 - reported as evidence, not a traceback
        return _emit({"verb": "create-repository",
                      "refusal": type(exc).__name__,
                      "message": _safe_message(exc, args.project_id)}, ok=False)
    return _emit(evidence, ok=True)


def cmd_attach_remote(args: argparse.Namespace) -> int:
    """RULING C3: "a remote can be attached later"."""
    from opendox.runtime import repository_act
    from opendox.runtime.identity import CoordinationStore
    from opendox.runtime.local_git_adapter import redact_remote_url

    settings, database = _store_and_settings(args)
    if database is None:
        return int(settings)
    try:
        with database, database.transaction() as conn:
            row = repository_act.attach_remote(
                CoordinationStore(conn), project_id=args.project_id,
                remote_url=args.remote_url)
            # REDACTED, like every other value this CLI prints. The act
            # refuses a credential-bearing URL, so a row written by THIS
            # runtime carries none — but a row written before that rule
            # existed can, and the lifecycle contract is that evidence is
            # redacted, not that it is redacted where we remembered.
            evidence = {"verb": "attach-remote",
                        "project_id": args.project_id,
                        "remote_url": redact_remote_url(row.remote_url),
                        "note": "no local content changed; the move is a "
                                "push, not a migration"}
    except repository_act.RepositoryActRefused as exc:
        return _emit({"verb": "attach-remote", "refusal": "repository",
                      "message": _safe_message(exc, args.project_id)},
                     ok=False)
    except Exception as exc:  # noqa: BLE001 - same
        return _emit({"verb": "attach-remote", "refusal": type(exc).__name__,
                      "message": _safe_message(exc, args.project_id)}, ok=False)
    return _emit(evidence, ok=True)


def cmd_push(args: argparse.Namespace) -> int:
    """Move the project into a governed factory. RULING C3: this is a PUSH."""
    from opendox.runtime import repository_act
    from opendox.runtime.identity import CoordinationStore
    from opendox.runtime.local_git_adapter import redact_remote_url

    settings, database = _store_and_settings(args)
    if database is None:
        return int(settings)
    try:
        with database, database.transaction() as conn:
            remote_url = repository_act.push_to_remote(
                CoordinationStore(conn), project_id=args.project_id)
            evidence = {"verb": "push", "project_id": args.project_id,
                        "pushed_to": redact_remote_url(remote_url),
                        "note": "a push, not a migration (RULING C3)"}
    except repository_act.RepositoryActRefused as exc:
        return _emit({"verb": "push", "refusal": "repository",
                      "message": _safe_message(exc, args.project_id)},
                     ok=False)
    except Exception as exc:  # noqa: BLE001 - same
        return _emit({"verb": "push", "refusal": type(exc).__name__,
                      "message": _safe_message(exc, args.project_id)}, ok=False)
    return _emit(evidence, ok=True)


# -- parser -----------------------------------------------------------------


def _add_connect_timeout(parser: argparse.ArgumentParser) -> None:
    """Bound how long a verb waits for the database before it reports.

    The same argument `status --probe-timeout` makes: a lifecycle verb that
    hangs for the driver's default is a verb an operator interrupts, and an
    interrupted verb emits no evidence at all.
    """
    parser.add_argument(
        "--connect-timeout", type=float, default=10.0,
        help="seconds to wait for a database connection before reporting the "
             "failure as evidence (default: 10)")


def register(subparsers: Any) -> None:
    """Attach the `runtime` command to an argparse subparsers action.

    The signature `subcommand_extension.SubcommandExtension.register` declares:
    the caller hands over the SAME subparsers action every core subcommand is
    added through, and this function attaches with `add_parser` and
    `set_defaults(func=…)` exactly as the core does. Nothing is wrapped.
    """
    runtime = subparsers.add_parser(
        "runtime",
        help="the identity and coordination runtime",
        description="Lifecycle verbs for the openDox runtime: FastAPI + "
                    "Postgres holding identity and coordination (RULING Q1), "
                    "OIDC through the Keycloak broker (RULING Q2).")
    verbs = runtime.add_subparsers(dest="verb", required=True)

    init = verbs.add_parser("init", help="prepare local state; touches no database")
    init.set_defaults(func=cmd_init, verb="init")

    migrate = verbs.add_parser("migrate", help="apply the ordered SQL migrations")
    migrate.add_argument("--plan", action="store_true",
                         help="report what would be applied and change nothing")
    _add_connect_timeout(migrate)
    migrate.set_defaults(func=cmd_migrate, verb="migrate")

    serve = verbs.add_parser("serve", help="run the API")
    serve.add_argument("--log-level", default="info",
                       choices=("critical", "error", "warning", "info", "debug",
                                "trace"))
    serve.set_defaults(func=cmd_serve, verb="serve")

    status = verbs.add_parser("status", help="report configuration and dependencies")
    status.add_argument(
        "--probe-timeout", type=float, default=5.0,
        help="seconds to wait for the database before reporting it "
             "unreachable; a status verb that hangs is a diagnostic nobody "
             "runs twice (default: 5)")
    status.set_defaults(func=cmd_status, verb="status")

    reset = verbs.add_parser(
        "reset", help="drop the coordination schema (RULING Q1: disposable)")
    reset.add_argument("--confirm", default="",
                       help=f"must be exactly {RESET_CONFIRMATION}")
    _add_connect_timeout(reset)
    reset.set_defaults(func=cmd_reset, verb="reset")


def register_project(subparsers: Any) -> None:
    """Attach the `project` command — § 3.6's act and its two successors.

    A SEPARATE COMMAND from `runtime`, because the two are different kinds of
    thing: `runtime` verbs operate an install (migrate it, serve it, reset it)
    and `project` verbs act on one project's repository. `opendox.cli` declares
    no `project` command today (its subcommands are `generate`,
    `generate-and-open`, `create`, `edit`, `model-binding` and the contributed
    `gate`), so contributing this name collides with nothing — measured at
    `src/opendox/cli.py` rather than assumed.
    """
    project = subparsers.add_parser(
        "project",
        help="acts on one project's repository (split-opendox § 3.6)",
        description="openDox creates a repository as a first-class act "
                    "(split-opendox-two-layer-product § 3.6): a PLAIN LOCAL "
                    "GIT REPOSITORY per project, commits as the write path, a "
                    "remote attachable later (RULING C3, "
                    "opensoft/openxFactory#656 comment 5544381563).")
    verbs = project.add_subparsers(dest="verb", required=True)

    create = verbs.add_parser(
        "create-repository",
        help="create this project's repository and write the map row")
    create.add_argument("--project-id", required=True)
    create.add_argument("--actor", required=True,
                        help="who is performing the act; becomes the first "
                             "commit's author (`Name <address>` is honoured)")
    create.set_defaults(func=cmd_create_repository, verb="create-repository")

    attach = verbs.add_parser(
        "attach-remote", help="attach a remote to an existing repository")
    attach.add_argument("--project-id", required=True)
    attach.add_argument("--remote-url", required=True)
    attach.set_defaults(func=cmd_attach_remote, verb="attach-remote")

    push = verbs.add_parser(
        "push", help="move the project into a governed factory (a push)")
    push.add_argument("--project-id", required=True)
    push.set_defaults(func=cmd_push, verb="push")


class RuntimeSubcommand:
    """`register`, in an object that conforms to `SubcommandExtension`.

    One method, structurally conformant, importing nothing from
    `subcommand_extension` — which is the whole point of a `runtime_checkable`
    Protocol: "STRUCTURAL conformance lets an implementation authored elsewhere
    conform without importing anything from this repository"
    (`subcommand_extension.py`'s own header, and `corpus_adapter.py`'s before
    it). `tests_runtime/test_runtime_cli.py` asserts the `isinstance`.
    """

    def register(self, subparsers: Any) -> None:
        register(subparsers)


class ProjectSubcommand:
    """`register_project`, in an object that conforms to `SubcommandExtension`.

    Same argument as `RuntimeSubcommand`'s, and the same one line at the
    eventual assembly point: `build_parser(subcommand_extensions=(
    RuntimeSubcommand(), ProjectSubcommand()))` gives `opendox project
    create-repository` the spelling § 3.6 names, without this act editing a
    carved file.
    """

    def register(self, subparsers: Any) -> None:
        register_project(subparsers)


def build_parser() -> argparse.ArgumentParser:
    """The standalone parser `[project.scripts] opendox-runtime` runs.

    It creates a subparsers action and hands it to the same `register` an
    eventual core `build_parser` would, so the two spellings cannot diverge:
    there is one registration function and this is a second caller of it.
    """
    parser = argparse.ArgumentParser(
        prog="opendox-runtime",
        description="The openDox runtime's lifecycle CLI "
                    "(split-opendox-two-layer-product § 3.5) and the "
                    "repository-creation act (§ 3.6).")
    sub = parser.add_subparsers(dest="command", required=True)
    register(sub)
    register_project(sub)
    return parser


def _isolated_when_local() -> contextlib.AbstractContextManager[None]:
    """A LOCAL install's verbs run with libpq's `PG*` defaults out of reach.

    The bundle's DSNs name their socket, but libpq fills everything else from
    the environment, and `PGHOSTADDR` alone would send `status` or `migrate`
    to a TCP server instead (Copilot review of openDox-code#69; see
    `bundle.isolated_from_libpq_environment`). A hosted install's operator
    configures libpq as they please, as before (13.6). A selector that cannot
    be read isolates nothing; the verb refuses it by name.
    """
    try:
        local = install_mode(os.environ) == INSTALL_MODE_LOCAL
    except ConfigurationError:
        local = False
    if not local:
        return contextlib.nullcontext()
    from opendox.runtime import bundle as bundle_mod

    return bundle_mod.isolated_from_libpq_environment()


def main(argv: list[str] | None = None) -> int:
    """Parse and dispatch, and NEVER let a traceback be the whole answer.

    `args.func(args)` is the core's own dispatch line, wrapped in the last
    error boundary the lifecycle contract needs: "each verb prints its redacted
    machine-readable evidence (JSON) and exits nonzero on a refused/failed
    outcome" is a promise about EVERY outcome, and a pool timeout or a
    filesystem permission error that escaped a verb used to print a traceback
    and no evidence at all (Copilot review of openDox-code#25).

    `SystemExit` passes through untouched: that is argparse's own usage error,
    which has already printed the usage a human needs.
    """
    args = build_parser().parse_args(argv)
    try:
        with _isolated_when_local():
            return int(args.func(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        return _emit({"verb": getattr(args, "verb", "unknown"),
                      "refusal": type(exc).__name__,
                      "message": _safe_message(exc)}, ok=False)


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
