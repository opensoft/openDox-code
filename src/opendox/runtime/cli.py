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
import sys
from pathlib import Path
from typing import Any

from opendox.runtime import identity, migrations
from opendox.runtime.config import (
    SECRET_NAMES,
    SETTINGS,
    ConfigurationError,
    RuntimeSettings,
    load_settings,
    migration_database_url,
)

#: The verb set, closed and in lifecycle order. Read by
#: `tests_runtime/test_runtime_cli.py` against the parser the module builds.
VERBS: tuple[str, ...] = ("init", "migrate", "serve", "status", "reset")

#: What `reset` will not do without being told twice.
RESET_CONFIRMATION = "yes-drop-the-coordination-database"


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
    settings = _settings_or_refusal(args)
    if isinstance(settings, int):
        return settings
    try:
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
    runner_db = Database(dsn, application_name="opendox-runtime-migrate")
    try:
        with runner_db:
            runner = migrations.MigrationRunner(
                runner_db, migrations_dir=settings.migrations_dir)
            if args.plan:
                plan = [m.version for m in runner.plan()]
                return _emit({"verb": "migrate", "planned": plan,
                              "applied": []}, ok=True)
            applied = runner.apply()
            return _emit({"verb": "migrate", "planned": [],
                          "applied": applied}, ok=True)
    except migrations.MigrationError as exc:
        return _emit({"verb": "migrate", "refusal": type(exc).__name__,
                      "message": str(exc)}, ok=False)


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
        with Database(settings.database_url,
                      checkout_timeout=args.probe_timeout) as db, \
                db.connection() as conn:
            conn.execute("select 1")
            runner = migrations.MigrationRunner(
                db, migrations_dir=settings.migrations_dir)
        report["database"] = "reachable"
        report["applied_migrations"] = [row.version for row in runner.applied()]
        report["pending_migrations"] = [m.version for m in runner.plan()]
    except Exception as exc:  # noqa: BLE001 - a status verb reports, never raises
        report["database"] = f"unreachable: {type(exc).__name__}: {exc}"
        ok = False

    try:
        from opendox.runtime.oidc import build_verifier

        build_verifier(settings).probe_keys()
        report["broker_keys"] = "reachable"
        report["broker_discovery"] = settings.discovery_url()
    except Exception as exc:  # noqa: BLE001 - same
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
    settings = _settings_or_refusal(args)
    if isinstance(settings, int):
        return settings
    if args.confirm != RESET_CONFIRMATION:
        return _emit({"verb": "reset", "refusal": "unconfirmed",
                      "message": f"pass --confirm {RESET_CONFIRMATION} to drop "
                                 f"{list(identity.TABLES)} and "
                                 f"{migrations.LEDGER_TABLE}"}, ok=False)
    try:
        dsn = migration_database_url(settings)
    except ConfigurationError as exc:
        return _emit({"verb": "reset", "refusal": "configuration",
                      "message": str(exc)}, ok=False)
    try:
        from opendox.runtime.db import Database
    except ImportError as exc:  # pragma: no cover - the extra is absent
        return _emit({"verb": "reset", "refusal": "runtime-extra-missing",
                      "message": str(exc)}, ok=False)
    dropped: list[str] = []
    with Database(dsn, application_name="opendox-runtime-reset") as db, \
            db.transaction() as conn:
        # Reverse declaration order so a dependent table goes before the table
        # it references; `cascade` is deliberately NOT used, so a table this
        # list does not know about keeps the drop honest by failing it.
        for table in (*reversed(identity.TABLES), migrations.LEDGER_TABLE):
            conn.execute(f"drop table if exists {table}")
            dropped.append(table)
    return _emit({"verb": "reset", "dropped": dropped,
                  "note": "coordination state only; every document is in a "
                          "repository (RULING Q1)"}, ok=True)


# -- parser -----------------------------------------------------------------


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
    reset.set_defaults(func=cmd_reset, verb="reset")


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


def build_parser() -> argparse.ArgumentParser:
    """The standalone parser `[project.scripts] opendox-runtime` runs.

    It creates a subparsers action and hands it to the same `register` an
    eventual core `build_parser` would, so the two spellings cannot diverge:
    there is one registration function and this is a second caller of it.
    """
    parser = argparse.ArgumentParser(
        prog="opendox-runtime",
        description="The openDox runtime's lifecycle CLI "
                    "(split-opendox-two-layer-product § 3.5).")
    sub = parser.add_subparsers(dest="command", required=True)
    register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse and dispatch. `args.func(args)` — the core's own dispatch line."""
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - process entry
    raise SystemExit(main())
