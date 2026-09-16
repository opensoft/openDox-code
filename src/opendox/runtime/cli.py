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
  * And they cannot go there in THIS act, for two measured reasons.
    `src/opendox/cli.py` is a CARVED file with a row in openxFactory's
    `docs/opendox-carve-manifest.yaml`, so a line added to it is a DECLARED
    EDIT that has to land as a row annotation at openxFactory first — a
    different act with a different claim. And `opendox.cli` cannot be imported
    at this leg at all: it reaches `opendox.serve`, whose line 192
    (`from ideation_dashboard import serve_openxfactory_lanes`) exists at
    neither carve destination — `tests/test_consumer_reach.py`'s
    `STILL_REACHING` records exactly that, and RULED Q-L5 (b′) says the
    remaining narrowing lifts with the BUILD arc. A lifecycle CLI that could
    only be invoked once an unrelated import was repaired would be a runtime
    nobody could operate.

SO THIS ACT SHIPS BOTH SPELLINGS AND NEITHER IS A FORK. :func:`build_parser`
below builds the `runtime` command; `[project.scripts] opendox-runtime` runs it
directly and works today; and :class:`RuntimeSubcommand` wraps the SAME
registration function in an object that structurally conforms to
`subcommand_extension.SubcommandExtension`, asserted with `isinstance` in
`tests_runtime/test_runtime_cli.py`. The day the BUILD arc makes `opendox.cli`
importable, wiring the verbs into the core parser is one line at the assembly
point — `build_parser(subcommand_extensions=(RuntimeSubcommand(),))` — and no
verb is re-authored. That is the seam used for what it is for, without
pretending the runtime is a layer above.

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
import json
import re
import sys
from pathlib import Path
from typing import Any

from opendox.runtime import identity, migrations
from opendox.runtime.config import (
    SECRET_NAMES,
    SETTINGS,
    ConfigurationError,
    RuntimeSettings,
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

#: What `reset` will not do without being told twice.
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
    "drafts",                 # references sessions, projects
    "sessions",               # references users, projects
    "project_repositories",   # references projects
    "memberships",            # references users, projects
    "projects",               # references users
    "users",
    "opendox_schema_migrations",
)


#: Anything shaped like a connection string or a credential-bearing URL. A
#: driver's error message quotes the DSN it could not reach — "connection to
#: server at ... failed", "invalid dsn: ..." — and an evidence object that
#: printed it would put the database password in a log, which is exactly what
#: the lifecycle contract's "redacted" forbids (Copilot review of
#: openDox-code#25).
_DSN_SHAPED = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|postgresql\+\w+)://\S*"
    r"|[A-Za-z][A-Za-z0-9+.\-]*://[^\s/@]*@\S*"
    r"|\bpassword\s*=\s*\S+")


def _safe_message(exc: BaseException) -> str:
    """An exception's text with every DSN- or credential-shaped run removed.

    Applied to EVERY operational message this CLI emits, rather than to the
    ones somebody remembered: the contract is that evidence is redacted.
    """
    return _DSN_SHAPED.sub("<redacted>", str(exc))


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
        "OPENDOX_OIDC_ISSUER": settings.oidc_issuer,
        "OPENDOX_OIDC_AUDIENCE": settings.oidc_audience,
        "OPENDOX_OIDC_JWKS_URL": settings.jwks_url(),
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
                      "message": str(exc)}, ok=False)


# -- verbs ------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    """Prepare an install's LOCAL state: directories, and a coherent config.

    Touches no database on purpose — schema is `migrate`'s act, applied with a
    privileged DSN this verb never reads. What `init` does own is the one piece
    of local state the runtime cannot create later without a race: the
    directory RULING C3's per-project repositories are created under.
    """
    settings = _settings_or_refusal(args)
    if isinstance(settings, int):
        return settings
    created: list[str] = []
    root = Path(settings.project_repository_root)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        created.append(str(root))
    try:
        digest = migrations.verify_canonical_digest(settings.migrations_dir)
    except migrations.MigrationError as exc:
        return _emit({"verb": "init", "refusal": "canonical-schema",
                      "message": str(exc)}, ok=False)
    pending = [m.version for m in migrations.discover_migrations(settings.migrations_dir)]
    return _emit({"verb": "init",
                  "project_repository_root": str(root),
                  "directories_created": created,
                  "canonical_sha256": digest,
                  "migrations_on_disk": pending,
                  "next": "opendox-runtime migrate"}, ok=True)


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
                      "message": str(exc)}, ok=False)
    try:
        from opendox.runtime.db import Database
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": "migrate", "refusal": "runtime-extra-missing",
                      "message": f"{exc}; install this package with the "
                                 "`runtime` extra: pip install '.[runtime]'"},
                     ok=False)
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
                runtime_role=settings.runtime_pg_role)
            if args.plan:
                evidence = {"verb": "migrate",
                            "planned": [m.version for m in runner.plan()],
                            "applied": []}
            else:
                evidence = {"verb": "migrate", "planned": [],
                            "applied": runner.apply()}
    except migrations.MigrationError as exc:
        return _emit({"verb": "migrate", "refusal": type(exc).__name__,
                      "message": str(exc)}, ok=False)
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
    """Run the API. The pool is opened by the application's lifespan."""
    settings = _settings_or_refusal(args)
    if isinstance(settings, int):
        return settings
    try:
        import uvicorn

        from opendox.runtime.app import create_app
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": "serve", "refusal": "runtime-extra-missing",
                      "message": f"{exc}; install this package with the "
                                 "`runtime` extra: pip install '.[runtime]'"},
                     ok=False)
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port,
                log_level=args.log_level)
    return 0


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
                      "message": str(exc)}, ok=False)
    report["settings"] = _redacted_settings(settings)

    try:
        report["canonical_sha256"] = migrations.verify_canonical_digest(
            settings.migrations_dir)
        report["canonical_schema"] = "pinned"
    except migrations.MigrationError as exc:
        report["canonical_schema"] = f"refused: {exc}"
        ok = False

    report["coordination_tables"] = list(identity.TABLES)

    try:
        from opendox.runtime.db import Database
    except ImportError as exc:  # pragma: no cover - the extra is absent
        report["runtime_extra"] = f"absent: {exc}"
        report["database"] = "not probed"
        report["broker_keys"] = "not probed"
        return _emit(report, ok=False)
    report["runtime_extra"] = "present"

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
        if drifted:
            ok = False
    # a status verb reports, never raises
    except Exception as exc:  # noqa: BLE001
        report["database"] = (
            f"unreachable: {type(exc).__name__}: {_safe_message(exc)}")
        ok = False

    try:
        from opendox.runtime.oidc import build_verifier

        build_verifier(settings).probe_keys()
        report["broker_keys"] = "reachable"
        report["broker_discovery"] = settings.discovery_url()
    # same
    except Exception as exc:  # noqa: BLE001
        report["broker_keys"] = f"unreachable: {type(exc).__name__}"
        report["broker_discovery"] = settings.discovery_url()
        ok = False

    return _emit(report, ok=ok)


def cmd_reset(args: argparse.Namespace) -> int:
    """DROP the coordination schema. Refuses without the spelled confirmation.

    THIS VERB CAN EXIST AT ALL BECAUSE OF RULING Q1's LAST SENTENCE: "the
    database is disposable relative to the corpus" — "lose it and you lose
    coordination state, not a governed artifact" (design § D5). It drops the
    six coordination tables and the migration ledger and nothing else; every
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
                      "message": str(exc)}, ok=False)
    try:
        from opendox.runtime.db import Database
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": "reset", "refusal": "runtime-extra-missing",
                      "message": str(exc)}, ok=False)
    try:
        with Database(dsn, application_name="opendox-runtime-reset",
                      checkout_timeout=args.connect_timeout) as db:
            # THE SAME ADVISORY LOCK A MIGRATION RUN TAKES. `reset` drops the
            # very tables `apply()` creates, so a confirmed reset running
            # beside a migration retry could interleave DDL and leave either
            # one failed or the schema in a state neither intended (Copilot
            # review of openDox-code#25). One key, both acts.
            with db.connection() as lock:
                lock.execute("select pg_advisory_lock(%s)",
                             (migrations.MIGRATION_LOCK_KEY,))
                try:
                    with db.transaction() as conn:
                        for table in DROP_ORDER:
                            conn.execute(f"drop table if exists {table}")
                finally:
                    lock.execute("select pg_advisory_unlock(%s)",
                                 (migrations.MIGRATION_LOCK_KEY,))
    except Exception as exc:  # noqa: BLE001
        return _emit({"verb": "reset", "refusal": type(exc).__name__,
                      "message": _safe_message(exc)}, ok=False)
    return _emit({"verb": "reset", "dropped": list(DROP_ORDER),
                  "note": "coordination state only; every document is in a "
                          "repository (RULING Q1)"}, ok=True)


# -- § 3.6, the repository-creation act, as CLI verbs ------------------------


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
                      "message": f"{exc}; install this package with the "
                                 "`runtime` extra: pip install '.[runtime]'"},
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
                      "message": str(exc)}, ok=False)
    except Exception as exc:  # noqa: BLE001 - reported as evidence, not a traceback
        return _emit({"verb": "create-repository",
                      "refusal": type(exc).__name__,
                      "message": str(exc)}, ok=False)
    return _emit(evidence, ok=True)


def cmd_attach_remote(args: argparse.Namespace) -> int:
    """RULING C3: "a remote can be attached later"."""
    from opendox.runtime import repository_act
    from opendox.runtime.identity import CoordinationStore
    from opendox.runtime.local_git_adapter import redact_credentials

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
                        "remote_url": redact_credentials(row.remote_url),
                        "note": "no local content changed; the move is a "
                                "push, not a migration"}
    except repository_act.RepositoryActRefused as exc:
        return _emit({"verb": "attach-remote", "refusal": "repository",
                      "message": str(exc)}, ok=False)
    except Exception as exc:  # noqa: BLE001 - same
        return _emit({"verb": "attach-remote", "refusal": type(exc).__name__,
                      "message": str(exc)}, ok=False)
    return _emit(evidence, ok=True)


def cmd_push(args: argparse.Namespace) -> int:
    """Move the project into a governed factory. RULING C3: this is a PUSH."""
    from opendox.runtime import repository_act
    from opendox.runtime.identity import CoordinationStore
    from opendox.runtime.local_git_adapter import redact_credentials

    settings, database = _store_and_settings(args)
    if database is None:
        return int(settings)
    try:
        with database, database.transaction() as conn:
            remote_url = repository_act.push_to_remote(
                CoordinationStore(conn), project_id=args.project_id)
            evidence = {"verb": "push", "project_id": args.project_id,
                        "pushed_to": redact_credentials(remote_url),
                        "note": "a push, not a migration (RULING C3)"}
    except repository_act.RepositoryActRefused as exc:
        return _emit({"verb": "push", "refusal": "repository",
                      "message": str(exc)}, ok=False)
    except Exception as exc:  # noqa: BLE001 - same
        return _emit({"verb": "push", "refusal": type(exc).__name__,
                      "message": str(exc)}, ok=False)
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
        help="the identity and coordination runtime (split-opendox § 3.5)",
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
        return int(args.func(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        return _emit({"verb": getattr(args, "verb", "unknown"),
                      "refusal": type(exc).__name__,
                      "message": _safe_message(exc)}, ok=False)


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
