"""The ONE lifecycle CLI: its verb set, its seam conformance, its refusals.

HERMETIC: standard library plus the package's stdlib-only modules and
`subcommand_extension`, which is itself stdlib-only by its own declaration.
"""

from __future__ import annotations

import argparse
import io
import json
import re
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

import pytest
import subcommand_extension

from opendox.runtime import cli, identity, migrations
from opendox.runtime.config import PREFIX, SECRET_NAMES

# THIS FILE READS `argparse`'s PRIVATE ATTRIBUTES (`parser._actions`,
# `argparse._SubParsersAction`) ON PURPOSE. argparse publishes no way to ask a
# built parser which subcommands it declares, and the alternative — asserting
# against the help text — would pin formatting rather than structure and would
# go red on a Python release that rewraps a line. The closure these tests keep
# is over the VERB SET, so it has to read the verbs.


def test_the_verb_set_is_closed_and_the_parser_declares_exactly_it() -> None:
    parser = cli.build_parser()
    actions = [a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction)]
    assert len(actions) == 1
    assert list(actions[0].choices) == ["runtime"]
    runtime_parser = actions[0].choices["runtime"]
    verbs = [a for a in runtime_parser._actions
             if isinstance(a, argparse._SubParsersAction)]
    assert len(verbs) == 1
    assert tuple(verbs[0].choices) == cli.VERBS
    assert cli.VERBS == ("init", "migrate", "serve", "status", "reset")


def test_the_registration_object_conforms_to_the_subcommand_seam() -> None:
    """RULED Q-L1's seam, satisfied STRUCTURALLY and with no import of it.

    `subcommand_extension.py`'s own header: "STRUCTURAL conformance lets an
    implementation authored elsewhere conform without importing anything from
    this repository". `opendox/runtime/cli.py` imports nothing from that
    module, and this is the assertion that the conformance is real rather than
    claimed — the same `isinstance` closure `corpus_adapter` uses.
    """
    assert isinstance(cli.RuntimeSubcommand(),
                      subcommand_extension.SubcommandExtension)
    assert subcommand_extension.MEMBERS == ("register",)
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert "import subcommand_extension" not in source, (
        "the runtime CLI must not import the seam it conforms to; structural "
        "conformance is the whole reason the seam is a Protocol")


def test_registering_through_the_seam_produces_the_same_verbs() -> None:
    """The two spellings are one registration function, proved by running both."""
    parser = argparse.ArgumentParser(prog="opendox")
    sub = parser.add_subparsers(dest="command", required=True)
    subcommand_extension.register_all((cli.RuntimeSubcommand(),), sub)
    contributed = [a for a in parser._actions
                   if isinstance(a, argparse._SubParsersAction)][0]
    assert list(contributed.choices) == ["runtime"]
    verbs = [a for a in contributed.choices["runtime"]._actions
             if isinstance(a, argparse._SubParsersAction)][0]
    assert tuple(verbs.choices) == cli.VERBS


def test_every_verb_sets_a_dispatch_function_and_its_own_name() -> None:
    for verb in cli.VERBS:
        args = cli.build_parser().parse_args(
            ["runtime", verb] + (["--confirm", "no"] if verb == "reset" else []))
        assert callable(args.func)
        assert args.verb == verb


def test_the_parser_refuses_a_verb_it_does_not_declare() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["runtime", "drop-everything"])


def _run(args: argparse.Namespace) -> tuple[int, dict]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = args.func(args)
    return code, json.loads(buffer.getvalue())


def test_a_verb_with_no_configuration_refuses_and_names_the_variable(
        monkeypatch: pytest.MonkeyPatch) -> None:
    for setting in (PREFIX + "DATABASE_URL", PREFIX + "OIDC_ISSUER",
                    PREFIX + "OIDC_AUDIENCE"):
        monkeypatch.delenv(setting, raising=False)
    code, evidence = _run(cli.build_parser().parse_args(["runtime", "status"]))
    assert code == 1
    assert evidence["ok"] is False
    assert evidence["refusal"] == "configuration"
    assert PREFIX + "DATABASE_URL" in evidence["message"]


def test_reset_refuses_without_the_spelled_confirmation(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A phrase and not a `--force`, because a shell history repeats a flag."""
    monkeypatch.setenv(PREFIX + "DATABASE_URL", "postgresql://x/y")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    code, evidence = _run(cli.build_parser().parse_args(
        ["runtime", "reset", "--confirm", "yes"]))
    assert code == 1
    assert evidence["refusal"] == "unconfirmed"
    assert cli.RESET_CONFIRMATION in evidence["message"]


def test_migrate_refuses_rather_than_borrowing_the_served_identity(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The separation the compose package declares, enforced in code.

    A silent fallback from `OPENDOX_MIGRATION_DATABASE_URL` to
    `OPENDOX_DATABASE_URL` would undo the two-identity split in the one place
    nobody looks.
    """
    monkeypatch.setenv(PREFIX + "DATABASE_URL", "postgresql://runtime@host/db")
    monkeypatch.delenv(PREFIX + "MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    code, evidence = _run(cli.build_parser().parse_args(
        ["runtime", "migrate"]))
    assert code == 1
    assert evidence["refusal"] == "configuration"
    assert PREFIX + "MIGRATION_DATABASE_URL" in evidence["message"]


def test_init_creates_the_project_repository_root_and_touches_no_database(
        monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root = tmp_path / "projects"
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    monkeypatch.setenv(PREFIX + "PROJECT_REPOSITORY_ROOT", str(root))
    code, evidence = _run(cli.build_parser().parse_args(["runtime", "init"]))
    assert code == 0, evidence
    assert root.is_dir()
    assert evidence["directories_created"] == [str(root)]
    assert evidence["canonical_sha256"] == migrations.CANONICAL_MIGRATION_SHA256
    assert evidence["migrations_on_disk"] == ["0001", "0002"]


def test_status_redacts_every_secret_setting(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://u:hunter2@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "MIGRATION_DATABASE_URL",
                       "postgresql://m:hunter3@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    buffer = io.StringIO()
    args = cli.build_parser().parse_args(
        ["runtime", "status", "--probe-timeout", "0.2"])
    with redirect_stdout(buffer):
        args.func(args)
    printed = buffer.getvalue()
    assert "hunter2" not in printed
    assert "hunter3" not in printed
    evidence = json.loads(printed)
    for name in SECRET_NAMES:
        assert evidence["settings"][name] == "<redacted>"
    # And the non-secret half is really there, so the redaction is not a blank
    # report that would pass this test by saying nothing.
    assert evidence["settings"][PREFIX + "OIDC_ISSUER"] == "https://broker/realms/x"
    assert evidence["coordination_tables"] == list(identity.TABLES)


def test_the_settings_repr_never_carries_a_dsn() -> None:
    from opendox.runtime.config import load_settings

    settings = load_settings({
        PREFIX + "DATABASE_URL": "postgresql://u:hunter2@h/db",
        PREFIX + "MIGRATION_DATABASE_URL": "postgresql://m:hunter3@h/db",
        PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
        PREFIX + "OIDC_AUDIENCE": "opendox-runtime",
    })
    assert "hunter2" not in repr(settings)
    assert "hunter3" not in repr(settings)
    assert "<redacted>" in repr(settings)


# ---------------------------------------------------------------------------
# the review round's own assertions (Copilot review of openDox-code#25)
# ---------------------------------------------------------------------------


def test_the_drop_order_is_topological_and_not_reversed_declaration_order() -> None:
    """`reversed(identity.TABLES)` drops `projects` before `memberships`.

    `memberships.project_id` references `projects.id`, so the first install
    with one membership in it failed the whole transaction on a foreign key and
    cleared nothing. The order is written out now, and this asserts the
    property rather than the list: every table appears after each table that
    references it.
    """
    references = {
        "drafts": {"sessions", "projects"},
        "sessions": {"users", "projects"},
        "project_repositories": {"projects"},
        "memberships": {"users", "projects"},
        "projects": {"users"},
        "users": set(),
        migrations.LEDGER_TABLE: set(),
    }
    assert set(cli.DROP_ORDER) == set(identity.TABLES) | {migrations.LEDGER_TABLE}
    position = {table: index for index, table in enumerate(cli.DROP_ORDER)}
    for table, referenced in references.items():
        for target in referenced:
            assert position[table] < position[target], (
                f"{table} references {target} and is dropped after it; "
                "`drop table` without `cascade` refuses that order")


def test_reset_names_the_whole_drop_order_in_its_refusal(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PREFIX + "MIGRATION_DATABASE_URL", "postgresql://m/db")
    code, evidence = _run(cli.build_parser().parse_args(
        ["runtime", "reset", "--confirm", "no"]))
    assert code == 1
    for table in cli.DROP_ORDER:
        assert table in evidence["message"]


def test_migrate_and_reset_need_no_served_identity_and_no_broker(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The separation the compose file and the Job declare, enforced in code.

    Both verbs used to go through `load_settings`, which requires the served
    DSN and the broker, so both deployments handed the migration container the
    PRIVILEGED DSN in `OPENDOX_DATABASE_URL` purely to satisfy the loader — and
    any path in that container reading `settings.database_url` was then
    schema-privileged. They read `load_migration_settings` now, and this is the
    assertion that they do: with only the migration DSN set, neither refuses
    for configuration.
    """
    for name in ("DATABASE_URL", "OIDC_ISSUER", "OIDC_AUDIENCE"):
        monkeypatch.delenv(PREFIX + name, raising=False)
    monkeypatch.setenv(PREFIX + "MIGRATION_DATABASE_URL",
                       "postgresql://nobody@127.0.0.1:1/none")
    code, evidence = _run(cli.build_parser().parse_args(
        ["runtime", "reset", "--confirm", "no"]))
    assert evidence["refusal"] == "unconfirmed", evidence
    code, evidence = _run(cli.build_parser().parse_args(
        ["runtime", "migrate", "--connect-timeout", "0.2"]))
    # It gets past configuration and fails on the unreachable server, which is
    # the point: the refusal is operational, and it is EVIDENCE, not a traceback.
    assert code == 1
    assert evidence["refusal"] != "configuration", evidence
    assert evidence["ok"] is False


def test_the_entrypoint_turns_an_escaped_exception_into_evidence(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Every outcome is one redacted JSON object; none is a traceback."""
    def _boom(_args: argparse.Namespace) -> int:
        raise RuntimeError("a pool timeout, say")

    monkeypatch.setattr(cli, "cmd_status", _boom)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(["runtime", "status"])
    assert code == 1
    evidence = json.loads(buffer.getvalue())
    assert evidence["ok"] is False
    assert evidence["refusal"] == "RuntimeError"
    assert "a pool timeout" in evidence["message"]


def test_an_argparse_usage_error_still_exits_the_way_argparse_means_it() -> None:
    with pytest.raises(SystemExit):
        cli.main(["runtime", "no-such-verb"])


def test_status_reports_every_declared_setting_and_none_as_null(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`OPENDOX_RUNTIME_PG_ROLE` and `OPENDOX_PUBLISH_OPENAPI` were declared in
    `SETTINGS` and missing from the verb's own value map, so a
    machine-readable report described a different process than the one running.
    """
    from opendox.runtime.config import SETTING_NAMES

    monkeypatch.setenv(PREFIX + "DATABASE_URL", "postgresql://u:pw@127.0.0.1:1/x")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    monkeypatch.setenv(PREFIX + "RUNTIME_PG_ROLE", "opendox_runtime")
    monkeypatch.setenv(PREFIX + "PUBLISH_OPENAPI", "true")
    # AND THE OTHER OPTIONAL NON-SECRET ONE: `SERVED_SCHEMA` is declared and
    # defaults to unset, so this census sets it for the same reason it sets
    # `RUNTIME_PG_ROLE` — the assertion below is that a DECLARED setting is
    # reported with its value, not that every default is non-null.
    monkeypatch.setenv(PREFIX + "SERVED_SCHEMA", "public")
    args = cli.build_parser().parse_args(
        ["runtime", "status", "--probe-timeout", "0.2"])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        args.func(args)
    reported = json.loads(buffer.getvalue())["settings"]
    assert set(reported) == set(SETTING_NAMES), (
        "the status map and `config.SETTINGS` disagree")
    assert reported[PREFIX + "RUNTIME_PG_ROLE"] == "opendox_runtime"
    assert reported[PREFIX + "PUBLISH_OPENAPI"] is True
    for name, value in reported.items():
        if name in SECRET_NAMES:
            continue
        assert value is not None, f"{name} reported as null"


def test_an_operational_failure_never_prints_the_dsn(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A driver's connection error quotes the DSN it could not reach."""
    monkeypatch.setenv(PREFIX + "MIGRATION_DATABASE_URL",
                       "postgresql://someone:hunter2@127.0.0.1:1/none")
    buffer = io.StringIO()
    args = cli.build_parser().parse_args(
        ["runtime", "migrate", "--connect-timeout", "0.2"])
    with redirect_stdout(buffer):
        code = args.func(args)
    printed = buffer.getvalue()
    assert code == 1
    assert "hunter2" not in printed, printed
    assert "postgresql://" not in printed, printed
    assert json.loads(printed)["ok"] is False


def test_reset_takes_the_same_advisory_lock_a_migration_run_does() -> None:
    """`reset` drops the very tables `apply()` creates."""
    import inspect

    source = inspect.getsource(cli.cmd_reset)
    assert "pg_advisory_lock" in source
    assert "MIGRATION_LOCK_KEY" in source
    assert "pg_advisory_unlock" in source


def test_init_refuses_a_repository_root_that_is_not_a_directory(
        monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A regular file at the root was reported as a valid install.

    `init` only asked `exists()`, so a path that existed as a FILE skipped the
    `mkdir` and emitted a successful evidence object, leaving § 3.6's
    repository creation with no directory to create anything under (Copilot
    review of openDox-code#25, suppressed comment). It is a named, nonzero
    refusal now.
    """
    root = tmp_path / "projects"
    root.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    monkeypatch.setenv(PREFIX + "PROJECT_REPOSITORY_ROOT", str(root))
    code, evidence = _run(cli.build_parser().parse_args(["runtime", "init"]))
    assert code == 1, evidence
    assert evidence["ok"] is False
    assert evidence["refusal"] == "root-not-a-directory"
    assert str(root) in evidence["message"]


def test_serve_emits_evidence_on_an_ordinary_shutdown(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Every lifecycle verb emits a JSON evidence object — `serve` too.

    It was the one verb that returned 0 and printed nothing when `uvicorn.run`
    returned normally, which made the CLI's own contract false for the verb an
    operator runs longest (Copilot review of openDox-code#25, suppressed
    comment). `uvicorn` and the application are stubbed here because the point
    is the RETURN path, not a listening socket.
    """
    import sys
    import types

    # STUBBED, NOT SKIPPED. `uvicorn` and `opendox.runtime.app` belong to the
    # `runtime` extra, which the REQUIRED `validate` job does not install, and
    # a test that skips there would leave this contract measured only in the
    # advisory job — and would make the required job's recorded figure depend
    # on which extras the measuring environment happened to have, which is the
    # very mismatch Copilot's review of openDox-code#26 caught in this file's
    # sibling block. `cmd_serve` imports both INSIDE the function, so two
    # entries in `sys.modules` are the whole seam; the subject here is the
    # RETURN path, never a listening socket.
    served: dict[str, object] = {}

    uvicorn_stub = types.ModuleType("uvicorn")

    class _Config:
        def __init__(self, app: object, **kwargs: object) -> None:
            served.update(kwargs)

    class _Server:
        """uvicorn's own shape: `Server(Config(...)).run()`, and `started`.

        `uvicorn.run` SWALLOWS a startup failure — a lifespan that raises is
        logged and the loop returns — so the verb could not tell "served and
        stopped" from "never started" (Copilot review of openDox-code#25,
        round 8). `started` is the flag uvicorn itself sets.
        """

        def __init__(self, config: object) -> None:
            self.config = config
            self.started = False

        def run(self) -> None:
            self.started = served.pop("_startup_fails", True) is not False

    uvicorn_stub.Config = _Config                      # type: ignore[attr-defined]
    uvicorn_stub.Server = _Server                      # type: ignore[attr-defined]
    app_stub = types.ModuleType("opendox.runtime.app")
    app_stub.create_app = lambda **kwargs: object()    # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_stub)
    monkeypatch.setitem(sys.modules, "opendox.runtime.app", app_stub)
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    code, evidence = _run(cli.build_parser().parse_args(["runtime", "serve"]))
    assert code == 0, evidence
    assert evidence["ok"] is True
    assert evidence["verb"] == "serve"
    assert evidence["state"] == "stopped"
    assert evidence["bind_port"] == served["port"]


def test_serve_refuses_when_the_applications_startup_never_completed(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`uvicorn.run` returns NORMALLY when the lifespan raises.

    An unreachable database or a broker that will not answer is logged by
    uvicorn and the server loop simply returns, so `serve` emitted `ok: true`
    and exited 0 for a process that never served a request — the lifecycle
    contract says a failed verb prints a refusal and exits nonzero, and this
    was the one verb that could not (Copilot review of openDox-code#25,
    round 8). `Server.started` is uvicorn's own answer.
    """
    import sys
    import types

    uvicorn_stub = types.ModuleType("uvicorn")

    class _Config:
        def __init__(self, app: object, **kwargs: object) -> None:
            pass

    class _NeverStarted:
        def __init__(self, config: object) -> None:
            self.started = False        # what uvicorn leaves it as

        def run(self) -> None:
            return None                 # logged the failure, returned normally

    uvicorn_stub.Config = _Config                      # type: ignore[attr-defined]
    uvicorn_stub.Server = _NeverStarted                # type: ignore[attr-defined]
    app_stub = types.ModuleType("opendox.runtime.app")
    app_stub.create_app = lambda **kwargs: object()    # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_stub)
    monkeypatch.setitem(sys.modules, "opendox.runtime.app", app_stub)
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    code, evidence = _run(cli.build_parser().parse_args(["runtime", "serve"]))
    assert code == 1, evidence
    assert evidence["ok"] is False
    assert evidence["refusal"] == "startup-failed"
    assert "nothing was served" in evidence["message"]


# -- Copilot's seventh round on #25 ------------------------------------------


def test_the_migrate_preview_runs_the_same_canonical_gate_the_run_does(
        monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A preview must not approve a tree the next command refuses.

    `apply()` verifies the pinned `0001` FIRST and `--plan` skipped it, so an
    operator could be shown a plan (or an empty one) for a directory whose
    canonical migration is absent or changed — and then watch `migrate` refuse
    it (Copilot review of openDox-code#25, round 7, suppressed).
    """
    empty = tmp_path / "no-migrations"
    empty.mkdir()
    monkeypatch.setenv(PREFIX + "MIGRATION_DATABASE_URL",
                       "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "MIGRATIONS_DIR", str(empty))
    code, evidence = _run(cli.build_parser().parse_args(
        ["runtime", "migrate", "--plan", "--connect-timeout", "0.2"]))
    assert code == 1, evidence
    assert evidence["ok"] is False
    assert "planned" not in evidence
    # AND THE GATE IS REACHED WITHOUT THE `runtime` EXTRA. This first asserted
    # `MigrationError` and went red in the REQUIRED job, which installs
    # `.[test]` alone: the gate sat behind the deferred `psycopg` import, so
    # the refusal there was `runtime-extra-missing` and the preview's own
    # promise was untestable in the one job that matters. The gate now runs
    # before the driver is imported — asking about the TREE needs neither —
    # and this assertion is what keeps it there.
    assert evidence["refusal"] == "MigrationError", evidence
    assert str(empty) in evidence["message"]


# -- Copilot's tenth round on #25 --------------------------------------------


def _stub_uvicorn(monkeypatch: pytest.MonkeyPatch, run) -> None:
    """uvicorn and the application, stubbed the way this file already does.

    STUBBED, NOT SKIPPED, for the reason the ordinary-shutdown test above
    states: both belong to the `runtime` extra, and a test that skipped in the
    REQUIRED job would make that job's recorded figure depend on the extras the
    measuring environment happened to have.
    """
    import sys
    import types

    uvicorn_stub = types.ModuleType("uvicorn")

    class _Config:
        def __init__(self, app: object, **kwargs: object) -> None:
            pass

    class _Server:
        def __init__(self, config: object) -> None:
            self.started = False

    # ASSIGNED AFTER THE CLASS BODY, not inside it: a class body resolves a
    # name it also assigns through the local/global path and never through the
    # enclosing function, so `run = run` in the body is a `NameError`.
    _Server.run = run                                  # type: ignore[method-assign]

    uvicorn_stub.Config = _Config                      # type: ignore[attr-defined]
    uvicorn_stub.Server = _Server                      # type: ignore[attr-defined]
    app_stub = types.ModuleType("opendox.runtime.app")
    app_stub.create_app = lambda **kwargs: object()    # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", uvicorn_stub)
    monkeypatch.setitem(sys.modules, "opendox.runtime.app", app_stub)
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://nobody:hunter2@127.0.0.1:1/none")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")


def test_serve_reports_a_bind_failure_as_evidence_and_not_a_traceback(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure an operator meets first: the port is already in use.

    `Server.run()` RAISES for an address it cannot use, and that call sat
    outside every exception-to-evidence handler — so the one verb an operator
    runs longest answered a misconfigured port with a traceback and no JSON at
    all (Copilot review of openDox-code#25, round 10, suppressed). Round 8
    closed the SILENT half of the same hole (a lifespan failure uvicorn
    swallows); this is the loud half.
    """
    def _run(self) -> None:
        raise OSError(98, "Address already in use")

    _stub_uvicorn(monkeypatch, _run)
    code, evidence = _run_serve()
    assert code == 1, evidence
    assert evidence["ok"] is False
    assert evidence["refusal"] == "serve-failed"
    assert "Address already in use" in evidence["message"]
    # AND IT NAMES THE ADDRESS IT TRIED, which is the fact an operator needs
    # first when the port is the problem.
    from opendox.runtime.config import load_settings

    settings = load_settings()
    assert evidence["bind_port"] == settings.bind_port
    assert evidence["bind_host"] == settings.bind_host


def test_serve_reports_uvicorns_own_sys_exit_as_evidence_too(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`SystemExit` is a `BaseException`, and `except Exception` misses it.

    uvicorn's own answer to a socket it cannot bind is `sys.exit(1)` from
    inside `Server.run()`, so a handler that named `Exception` alone would have
    left exactly the reported case — an occupied port — printing nothing.
    """
    def _run(self) -> None:
        raise SystemExit(1)

    _stub_uvicorn(monkeypatch, _run)
    code, evidence = _run_serve()
    assert code == 1, evidence
    assert evidence["refusal"] == "serve-failed"
    assert "SystemExit" in evidence["message"]


def test_a_serve_failure_message_carries_no_dsn(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Redacted, like every other operational message this CLI emits."""
    def _run(self) -> None:
        raise RuntimeError(
            "could not start: postgresql://nobody:hunter2@127.0.0.1:1/none")

    _stub_uvicorn(monkeypatch, _run)
    code, evidence = _run_serve()
    assert code == 1
    printed = json.dumps(evidence)
    assert "hunter2" not in printed, printed
    assert "postgresql://" not in printed, printed


def _run_serve() -> tuple[int, dict]:
    return _run(cli.build_parser().parse_args(["runtime", "serve"]))


def test_status_keeps_the_connectivity_answer_when_a_later_query_fails(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`select 1` answered, so the database IS reachable — say so.

    A served role without `select` on the ledger, a search path that does not
    reach the schema, any query error after the connectivity probe: all of them
    were reported as `database: unreachable`, which points an operator at the
    network for a privilege problem. Round 7 made that distinction for the
    runner's own `MigrationError` and left it unmade in the handler one line
    down (Copilot review of openDox-code#25, round 10, suppressed).
    """
    import sys
    import types

    class _Cursor:
        def fetchone(self) -> tuple:
            return (1,)

        def fetchall(self) -> list:
            return []

    class _Connection:
        def execute(self, sql: str, params: tuple | None = None) -> _Cursor:
            if " ".join(sql.split()).startswith("select 1"):
                return _Cursor()
            raise RuntimeError(
                "permission denied for table opendox_schema_migrations")

    class _Database:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> _Database:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        @contextmanager
        def connection(self):
            yield _Connection()

    db_stub = types.ModuleType("opendox.runtime.db")
    db_stub.Database = _Database                       # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opendox.runtime.db", db_stub)
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://runtime:hunter2@127.0.0.1:5432/opendox")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    monkeypatch.setenv(PREFIX + "MIGRATIONS_DIR",
                       str(Path(__file__).resolve().parents[1] / "migrations"))
    code, evidence = _run(cli.build_parser().parse_args(
        ["runtime", "status", "--probe-timeout", "0.2"]))

    assert code == 1, evidence
    assert evidence["database"] == "reachable", evidence
    assert evidence["schema_queries"].startswith("failed: RuntimeError"), evidence
    assert "permission denied" in evidence["schema_queries"]
    printed = json.dumps(evidence)
    assert "hunter2" not in printed, printed


#: Everything this repository's text is scanned for the console script in.
#: Source, runbook, deploy files and the suites themselves, because a test that
#: PINS an unrunnable command is how the defect below survived a round.
_SCANNED = ("src", "docs", "deploy", "tests_runtime")
_SCANNED_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".sh", ".example", ".sql",
                     ".toml", ".cfg", ""}
_CONSOLE_SCRIPT = "opendox-runtime"


def _scanned_files() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    found: list[Path] = []
    for directory in _SCANNED:
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and path.suffix in _SCANNED_SUFFIXES:
                found.append(path)
    return found


def test_every_printed_invocation_names_the_command_group() -> None:
    """A command this runtime PRINTS must be a command this parser accepts.

    `register()` nests every verb under `runtime`, so the shortened spelling —
    the console script followed straight by a verb — exits 2 with argparse's
    usage error. It was what `runtime init`'s evidence emitted as its `next`,
    what `/readyz` told an operator to run when migrations are pending, what
    the runbook's transcript showed, and what a case in
    `test_api_endpoints.py` PINNED — so an operator who copied the answer the
    service gave them could not make the service ready (Copilot review of
    openDox-code#25, round 14, suppressed, four places). Measured through the
    parser below, then swept, so the next one cannot be written silently.
    """
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as refused:
        parser.parse_args([cli.VERBS[1]])          # the bare verb, no group
    assert refused.value.code == 2
    assert parser.parse_args(["runtime", cli.VERBS[1]]).func is cli.cmd_migrate

    pattern = re.compile(_CONSOLE_SCRIPT + r"\s+([a-z][a-z-]*)")
    offenders: list[str] = []
    for path in _scanned_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in pattern.finditer(line):
                if match.group(1) in cli.VERBS:
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "these name the console script followed straight by a verb, which "
        "this parser refuses with exit 2; every verb lives under the "
        "`runtime` command group:\n" + "\n".join(offenders))


def test_a_libpq_password_holding_a_space_is_redacted_whole() -> None:
    """libpq QUOTES a value containing spaces, and the pattern stopped at one.

    The keyword/value shape, which has no authority for a URL rule to
    match, so `_DSN_SHAPED` is the only redactor that sees it — and `password\\s*=\\s*\\S+`
    ends at whitespace, while libpq documents that a value containing spaces is
    written in single quotes with `\\'` and `\\\\` escaped inside. So the VALID
    conninfo `password='secret value'` was redacted as `<redacted> value'`,
    half the password printed beside the marker that says it was removed
    (Copilot review of openDox-code#25, round 19). psycopg accepts an arbitrary
    conninfo and its driver errors quote it back, which is how a real failure
    arrives here.

    Every case below fails against the previous head; the last three are the
    ones that say the widening did not become an over-match.
    """
    for carried, gone in (
            ("connection failed: host=db user=opendox "
             "password='secret value' dbname=opendox", ("secret", "value")),
            ('connection to server failed: password="two words here" host=db',
             ("two", "words", "here")),
            (r"password='it\'s quoted' host=db", ("quoted",)),
            # A private key's passphrase is the same secret by another keyword,
            # and `\b` before `password` does not reach it.
            ("sslpassword='key phrase' host=db", ("key", "phrase")),
            # A TRUNCATED message redacts MORE, not less.
            ("truncated: password='unterminated secret", ("secret",)),
    ):
        redacted = cli._safe_message(RuntimeError(carried))
        assert "<redacted>" in redacted, redacted
        for word in gone:
            assert word not in redacted, (word, redacted)

    # NOT an over-match: the unquoted form still ends at whitespace, a quoted
    # value does not swallow the next line of a multi-line error, and a keyword
    # that merely starts with `password` is not a password.
    plain = cli._safe_message(RuntimeError("password=simple host=db.internal"))
    assert plain == "<redacted> host=db.internal", plain
    lines = cli._safe_message(RuntimeError("password='a b'\nhost=db is up"))
    assert lines.endswith("\nhost=db is up"), lines
    assert cli._safe_message(RuntimeError("passwordless=fine host=db")) == \
        "passwordless=fine host=db"


def test_no_broker_url_this_runtime_prints_can_carry_a_credential() -> None:
    """The issuer and the key set are PUBLIC endpoints, and were unchecked.

    `load_settings` accepted any string for `OPENDOX_OIDC_ISSUER` and for an
    explicit `OPENDOX_OIDC_JWKS_URL`, so `https://svc:pw@broker/realms/x` was a
    legal configuration — and then `repr(settings)` printed it, `status`
    printed the DERIVED JWKS URL and the discovery URL built from it, and this
    runtime's promise that a credential never reaches a log was false for a
    value that had never been a DSN (Copilot review of openDox-code#25, round
    22, reported in both places).

    MEASURED against the previous head with that issuer:

        load_settings          ACCEPTED it
        repr(settings)         oidc_issuer='https://svc:pw@broker/realms/x'
        status OIDC_JWKS_URL   https://svc:pw@broker/realms/x/protocol/…
        status broker_discovery https://svc:pw@broker/realms/x/.well-known/…

    Refused at the door, because redaction alone would leave the configuration
    wrong: `jwks_url()` is also what the verifier FETCHES. And redacted at the
    two printing boundaries anyway, because a `RuntimeSettings` built by hand —
    in a test, or by a future caller — does not go through that door.
    """
    import dataclasses

    from opendox.runtime.config import (ConfigurationError, load_settings,
                                        redacted_url)

    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime"}
    for name in ("OIDC_ISSUER", "OIDC_JWKS_URL"):
        env = dict(base, **{PREFIX + "OIDC_ISSUER": "https://broker/realms/x"})
        env[PREFIX + name] = "https://svc:pw@broker/realms/x"
        with pytest.raises(ConfigurationError) as caught:
            load_settings(env)
        assert PREFIX + name in str(caught.value), caught.value
        assert "credential" in str(caught.value)

    settings = load_settings(
        dict(base, **{PREFIX + "OIDC_ISSUER": "https://broker/realms/x"}))
    assert settings.jwks_url() == \
        "https://broker/realms/x/protocol/openid-connect/certs"

    # AND THE PRINTING BOUNDARIES DO NOT ASSUME THE LOADING ONE.
    by_hand = dataclasses.replace(
        settings, oidc_issuer="https://svc:pw@broker/realms/x")
    assert "pw" not in repr(by_hand), repr(by_hand)
    assert "<redacted>@broker" in repr(by_hand), repr(by_hand)
    printed = cli._redacted_settings(by_hand)
    assert "pw" not in json.dumps(printed), printed
    assert "broker" in json.dumps(printed), (
        "the host went with the credential; an operator cannot check a URL "
        "that is not there")

    # NOT an over-redaction: an ordinary URL is printed as it is.
    assert redacted_url("https://broker/realms/x") == "https://broker/realms/x"
    assert cli._redacted_settings(settings)["OPENDOX_OIDC_JWKS_URL"] == \
        "https://broker/realms/x/protocol/openid-connect/certs"


def test_a_credential_in_a_broker_urls_query_is_refused_like_one_in_its_userinfo(
) -> None:
    """Round 22's guard looked only at the authority.

    `https://broker/certs?token=…` carries a credential as surely as
    `https://svc:pw@broker/…`, and `redacted_url` preserved the query — so both
    `repr(settings)` and `status` printed it (Copilot review of
    openDox-code#25, round 24). And `urlsplit` RAISES for a malformed URL, from
    inside a function whose whole contract is a `ConfigurationError` naming the
    variable: MEASURED on python 3.12, `urlsplit("https://[::1/x")` raises
    `ValueError("Invalid IPv6 URL")`, which escaped as a traceback.
    """
    from opendox.runtime.config import (ConfigurationError, load_settings,
                                        redacted_url)

    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime",
            PREFIX + "OIDC_ISSUER": "https://broker/realms/x"}
    for name, value, why in (
            ("OIDC_JWKS_URL", "https://broker/certs?token=ghp_secret",
             "query parameter"),
            ("OIDC_JWKS_URL", "https://broker/certs#access_token=abc",
             "query parameter"),
            ("OIDC_ISSUER", "https://svc:pw@broker/realms/x", "userinfo"),
    ):
        env = dict(base)
        env[PREFIX + name] = value
        with pytest.raises(ConfigurationError) as caught:
            load_settings(env)
        assert PREFIX + name in str(caught.value)
        assert why in str(caught.value), (value, caught.value)

    # A malformed URL is a REFUSAL naming the variable, not a traceback.
    env = dict(base)
    env[PREFIX + "OIDC_ISSUER"] = "https://[::1/x"
    with pytest.raises(ConfigurationError) as caught:
        load_settings(env)
    assert PREFIX + "OIDC_ISSUER" in str(caught.value)
    assert "parse" in str(caught.value)

    # AND THE REDACTOR COVERS WHAT THE GUARD REFUSES, for a settings object
    # built by hand: the secret parameter goes, the rest of the URL stays.
    assert redacted_url("https://broker/certs?token=ghp_x&format=jwk") == \
        "https://broker/certs?token=<redacted>&format=jwk"
    assert redacted_url("https://broker/realms/x") == "https://broker/realms/x"
    assert redacted_url("https://[::1/x") == "<redacted-url>"


def test_the_broker_url_must_be_https_because_it_is_the_trust_anchor() -> None:
    """The key set fetched from it is what every token is verified against.

    So over `http://` a network attacker replaces the key set and mints tokens
    whose `iss` and `aud` still pass — the whole verification reduced to
    whoever controls the path. Round 22 refused a credential IN the URL and
    said nothing about the scheme (Copilot review of openDox-code#25, round
    25).

    A LOOPBACK host is the one exception, and it is exact rather than
    name-shaped: `ipaddress` judges a literal, so `127.5.5.5` and `[::1]` are
    the same answer and `127.0.0.1.evil.test` is not one at all.
    """
    from opendox.runtime.config import ConfigurationError, load_settings

    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime"}
    for issuer in ("https://broker/realms/x", "http://localhost:8080/realms/x",
                   "http://127.0.0.1:8080/realms/x", "http://[::1]:8080/x"):
        assert load_settings(dict(base, **{PREFIX + "OIDC_ISSUER": issuer}))

    for issuer in ("http://broker/realms/x",
                   "http://127.0.0.1.evil.test/realms/x",
                   "ftp://broker/x"):
        with pytest.raises(ConfigurationError) as caught:
            load_settings(dict(base, **{PREFIX + "OIDC_ISSUER": issuer}))
        assert "TRUST ANCHOR" in str(caught.value), (issuer, caught.value)

    # `broker/realms/x` USED TO BE ASSERTED HERE, and it is refused by the
    # rule below instead: it has no scheme AND no host, and "names no HOST" is
    # the more accurate of the two diagnoses for a value that is not a URL.

    # The explicit key-set URL is judged by the same rule, since it is the one
    # actually fetched.
    with pytest.raises(ConfigurationError) as caught:
        load_settings(dict(base, **{
            PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_JWKS_URL": "http://broker/certs"}))
    assert PREFIX + "OIDC_JWKS_URL" in str(caught.value)


def _conftest_module():
    """`tests_runtime/conftest.py`, loaded BY PATH.

    The `validate` job runs pytest with `--noconftest`, so this file cannot
    reach that module as a fixture provider and must not depend on it being on
    `sys.path` either. Loading it by path is the one form that works in both
    jobs — and the module is definitions only, so importing it starts nothing.
    """
    import importlib.util

    path = Path(__file__).resolve().parent / "conftest.py"
    spec = importlib.util.spec_from_file_location("_opendox_conftest", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_probe_never_interpolates_the_exception_text(monkeypatch) -> None:
    """THE CONTRACT ITSELF, and it does not depend on psycopg's wording.

    The test below is the live reproducer and needs the driver installed; the
    `validate` job installs `.[test]` alone and does not have it. This one
    hands the probe a driver whose `connect` raises an exception carrying the
    whole DSN — which is the only property of the real failure that matters —
    and asserts the reason does not carry it. It runs in BOTH jobs, and it is
    the assertion that would have caught the finding when it was written.
    """
    conftest = _conftest_module()
    dsn = "postgresql://opendox:hunter2@db.internal:5432/opendox"
    monkeypatch.setenv(conftest.TEST_DSN_ENV, dsn)

    class _Driver:
        @staticmethod
        def connect(conninfo, **kwargs):
            raise RuntimeError(f'could not parse "{conninfo}"')

    monkeypatch.setattr(conftest, "_import_psycopg", lambda: _Driver)

    with pytest.raises(BaseException) as caught:
        conftest.postgres_dsn.__wrapped__()
    reason = getattr(caught.value, "msg", None) or str(caught.value)

    assert "hunter2" not in reason and "opendox:" not in reason, (
        f"the exception's text reached the reason: {reason!r}")
    assert "RuntimeError" in reason, (
        f"the reason must name the exception type: {reason!r}")
    assert "postgresql://db.internal:5432/<redacted>" in reason, (
        f"the reason must still name the server that did not answer: {reason!r}")


def test_an_unparsable_test_dsn_does_not_print_its_password(monkeypatch) -> None:
    """The DB probe's skip reason carries no credential — measured, not hoped.

    THE FINDING (Copilot review of openDox-code#25, round 26): the probe copied
    `str(exc)` into the reason `_skip_or_fail` prints, "psycopg connection
    errors can include the full `OPENDOX_TEST_DATABASE_URL`", and pytest prints
    that reason in the CI log of a job whose DSN carries a password.

    FACT, WITH ONE REPRODUCER, and this test IS the reproducer. Five DSN shapes
    were measured against psycopg 3: a refused connection, an unknown URI
    parameter, an unknown keyword/value option and the refused keyword/value
    form all report without the password, because libpq's message is about the
    connection. The fifth — a URI libpq cannot PARSE — quotes the whole string
    back, and an unbracketed IPv6 host is the ordinary way to mis-set this
    variable:

        ProgrammingError: end of string reached when looking for matching "]"
        in IPv6 host address in URI: "postgresql://opendox:hunter2@[::1/x"

    So the case below is the leaking one, and against the previous shape
    (`f"{type(exc).__name__}: {exc}"`) this test fails on its first assertion.

    NOT A DATABASE TEST. Nothing here connects: the DSN is unparsable, which is
    why psycopg raises before any socket exists, and that is what lets a
    hermetic module measure the harness the DB-backed ones depend on.
    """
    pytest.importorskip(
        "psycopg",
        reason="the live reproducer needs the driver; the `validate` job "
               "installs `.[test]` alone, and the contract itself is measured "
               "by the hermetic test above")
    conftest = _conftest_module()
    password = "hunter2"                      # NOT a credential: a test string
    monkeypatch.setenv(conftest.TEST_DSN_ENV,
                       f"postgresql://opendox:{password}@[::1/opendox")

    with pytest.raises(BaseException) as caught:   # Skipped or Failed
        conftest.postgres_dsn.__wrapped__()
    reason = getattr(caught.value, "msg", None) or str(caught.value)

    assert password not in reason, (
        f"the probe's reason carries the DSN password: {reason!r}")
    assert "opendox:" not in reason, (
        f"the probe's reason carries the DSN userinfo: {reason!r}")
    assert "ProgrammingError" in reason, (
        "the reason must still name the exception TYPE, which is what makes "
        f"the skip diagnosable: {reason!r}")
    assert "<the configured DSN>" in reason, (
        "an unparsable DSN has no destination to name, and the reason must "
        f"say which DSN it means rather than falling silent: {reason!r}")


@pytest.mark.parametrize("dsn, expected", [
    # A URI: scheme, host and port survive; userinfo, database and every
    # parameter do not.
    ("postgresql://opendox:hunter2@db.internal:5432/opendox?sslmode=require",
     "postgresql://db.internal:5432/<redacted>"),
    # NO PORT, no invented one.
    ("postgresql://opendox:hunter2@db.internal/opendox",
     "postgresql://db.internal/<redacted>"),
    # AN IPv6 LITERAL KEEPS ITS BRACKETS: `::1` unbracketed is not the host it
    # names, and this act has been wrong about that before.
    ("postgresql://opendox:hunter2@[::1]:5432/opendox",
     "postgresql://[::1]:5432/<redacted>"),
    # The keyword/value form: only the three destination keywords are kept, and
    # `password` is dropped even holding a quoted space.
    ("host=db.internal port=5432 user=opendox password='a b' dbname=opendox",
     "host=db.internal port=5432"),
    # An unparsable string names no destination and is not echoed.
    ("postgresql://opendox:hunter2@[::1/opendox", "<the configured DSN>"),
    ("garbage", "<the configured DSN>"),
    # A PORT THAT IS NOT A NUMBER: `urlsplit` succeeds and `.port` raises on
    # read, so the redaction itself used to crash (round 27).
    ("postgresql://opendox:hunter2@host:not-a-port/db", "<the configured DSN>"),
    ("postgresql://opendox:hunter2@host:99999/db", "<the configured DSN>"),
])
def test_the_probes_redaction_keeps_the_destination_and_nothing_else(
        dsn: str, expected: str) -> None:
    """Each case is a shape the harness is handed, not a shape it invents."""
    assert _conftest_module()._redacted_dsn(dsn) == expected
    assert "hunter2" not in _conftest_module()._redacted_dsn(dsn)


def test_a_broker_url_that_names_no_host_is_refused_at_the_door() -> None:
    """A trust anchor nothing can be fetched from must not reach serve time.

    THE FINDING (Copilot review of openDox-code#25, round 26, suppressed):
    `urlsplit("https:///realms/x")` yields the scheme `https` and NO hostname,
    so the scheme check above accepted it, `load_settings` succeeded, and the
    install discovered the bad configuration when the JWKS fetch made
    `/readyz` and `status` fail. Measured before the fix: `load_settings` with
    `OPENDOX_OIDC_ISSUER=https:///realms/x` returned settings carrying that
    issuer.

    AND THE REFUSAL DOES NOT ECHO THE VALUE, which is not fastidiousness:
    `urlsplit("https://user:hunter2@/realms/x").hostname` is `None` too, so the
    hostless shape and the credential-carrying shape overlap exactly, and a
    message that quoted the value would print the password this function
    exists to keep out of `status` and the logs.
    """
    from opendox.runtime.config import ConfigurationError, load_settings

    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime"}
    for issuer in ("https:///realms/x", "https://", "https:///",
                   "broker/realms/x", "https://user:hunter2@/realms/x"):
        with pytest.raises(ConfigurationError) as caught:
            load_settings(dict(base, **{PREFIX + "OIDC_ISSUER": issuer}))
        message = str(caught.value)
        assert "names no HOST" in message, (issuer, message)
        assert PREFIX + "OIDC_ISSUER" in message, (issuer, message)
        assert "hunter2" not in message, (
            f"the refusal echoed a credential from a hostless URL: {message}")

    # The same rule on the URL that is actually fetched, and a host that IS
    # named still passes.
    with pytest.raises(ConfigurationError) as caught:
        load_settings(dict(base, **{
            PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_JWKS_URL": "https:///certs"}))
    assert "names no HOST" in str(caught.value)
    assert PREFIX + "OIDC_JWKS_URL" in str(caught.value)
    assert load_settings(dict(base, **{
        PREFIX + "OIDC_ISSUER": "https://broker.example/realms/opendox"}))


def test_a_probe_failure_leaves_no_traceback_that_could_carry_the_dsn(
        monkeypatch) -> None:
    """The redaction is TOTAL, and the reason is raised outside the handler.

    TWO FINDINGS IN ONE SHAPE (Copilot review of openDox-code#25, round 27).
    `urlsplit("postgresql://u:pw@host:not-a-port/db")` SUCCEEDS and defers the
    error to `.port`, which is a property that parses on read — so
    `_redacted_dsn` raised `ValueError` from inside the handler that was
    reporting a connection failure, and pytest printed a chained traceback
    instead of the redacted reason the module promises. Measured before the
    fix: `ValueError: Port could not be cast to integer value as 'not-a-port'`,
    raised at `port = f":{split.port}"`.

    And the chain is the second half: `pytest.skip` raised inside `except`
    carries the psycopg error as `__context__`, and libpq quotes a conninfo it
    cannot parse — so a traceback pytest chose to print would have carried the
    password even though the reason did not. Measured before the fix, on
    `postgresql://opendox:hunter2@[::1:not-a-port/db`: the password was in the
    formatted traceback and not in the reason. The probe now raises OUTSIDE the
    handler, so there is no context to print.
    """
    conftest = _conftest_module()
    for dsn in ("postgresql://opendox:hunter2@host:not-a-port/db",
                "postgresql://opendox:hunter2@[::1:not-a-port/db",
                "postgresql://opendox:hunter2@host:99999/db"):
        monkeypatch.setenv(conftest.TEST_DSN_ENV, dsn)

        class _Driver:
            @staticmethod
            def connect(conninfo, **kwargs):
                raise RuntimeError(f'could not parse "{conninfo}"')

        monkeypatch.setattr(conftest, "_import_psycopg", lambda: _Driver)
        with pytest.raises(BaseException) as caught:
            conftest.postgres_dsn.__wrapped__()

        import traceback as _tb
        rendered = "".join(_tb.format_exception(caught.value))
        reason = getattr(caught.value, "msg", None) or str(caught.value)
        assert "<the configured DSN>" in reason, (dsn, reason)
        assert "hunter2" not in reason, (dsn, reason)
        assert caught.value.__context__ is None, (
            f"the outcome is chained to the connection failure, so a printed "
            f"traceback would carry what libpq quoted back: {dsn}")
        assert "hunter2" not in rendered, (
            f"the rendered traceback carries the password: {rendered}")


def test_a_broker_url_whose_port_is_not_a_number_is_refused_at_the_door(
) -> None:
    """`urlsplit` succeeds for it; `.port` is where it fails, and that is late.

    THE FINDING (Copilot review of openDox-code#25, round 27, suppressed):
    `https://broker:not-a-port/realm` passed this boundary, because the checks
    read the scheme and the hostname and never evaluated the port — so `serve`
    started and the `ValueError` surfaced inside the JWKS fetch, which is
    neither a `ConfigurationError` nor a named setting. Measured: `.port`
    raises `ValueError` for a non-numeric port and for one out of 0-65535.
    """
    from opendox.runtime.config import ConfigurationError, load_settings

    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime"}
    for issuer in ("https://broker:not-a-port/realm",
                   "https://broker:99999/realm",
                   "https://user:hunter2@broker:not-a-port/realm"):
        with pytest.raises(ConfigurationError) as caught:
            load_settings(dict(base, **{PREFIX + "OIDC_ISSUER": issuer}))
        message = str(caught.value)
        assert "PORT that is not a number" in message, (issuer, message)
        assert PREFIX + "OIDC_ISSUER" in message, (issuer, message)
        assert "hunter2" not in message, (issuer, message)

    # A real port still passes, and the key-set URL is judged by the same rule.
    assert load_settings(dict(base, **{
        PREFIX + "OIDC_ISSUER": "https://broker:8443/realm"}))
    with pytest.raises(ConfigurationError) as caught:
        load_settings(dict(base, **{
            PREFIX + "OIDC_ISSUER": "https://broker/realm",
            PREFIX + "OIDC_JWKS_URL": "https://broker:not-a-port/certs"}))
    assert PREFIX + "OIDC_JWKS_URL" in str(caught.value)


def test_the_issuer_carries_no_query_or_fragment_because_paths_are_appended(
) -> None:
    """A base URL's derived paths land after its query, addressing nothing.

    THE FINDING (Copilot review of openDox-code#25, round 29, previously
    missed): `jwks_url()` and `discovery_url()` APPEND a path to the issuer,
    and a URL's query and fragment come after its path. Measured before the
    fix, both components accepted:

        OPENDOX_OIDC_ISSUER=https://broker/realms/x?tenant=a
        jwks_url()      -> https://broker/realms/x?tenant=a/protocol/openid-connect/certs
        discovery_url() -> https://broker/realms/x?tenant=a/.well-known/openid-configuration

    Nothing serves either, so readiness failed at the fetch — configuration
    discovered at serve time, which is the boundary `load_settings` holds.

    THE RULE IS THE ISSUER'S ALONE, and the second half of this test is why
    that matters: an explicit `OPENDOX_OIDC_JWKS_URL` is fetched exactly as
    given, and a broker behind a rewriting proxy may need a query on it. That
    is the whole reason the variable exists.
    """
    from opendox.runtime.config import ConfigurationError, load_settings

    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime"}
    for issuer, component in (("https://broker/realms/x?tenant=a", "query"),
                              ("https://broker/realms/x#frag", "fragment"),
                              ("https://broker/realms/x?a=1#b", "query")):
        with pytest.raises(ConfigurationError) as caught:
            load_settings(dict(base, **{PREFIX + "OIDC_ISSUER": issuer}))
        message = str(caught.value)
        assert f"carries a {component} component" in message, (issuer, message)
        assert PREFIX + "OIDC_ISSUER" in message, (issuer, message)

    # THE DERIVATION IS WHAT THIS PROTECTS, so measure it on the value that
    # passes: a trailing slash and no query, and the derived URLs are the two
    # Keycloak publishes.
    settings = load_settings(dict(base, **{
        PREFIX + "OIDC_ISSUER": "https://broker/realms/x/"}))
    assert settings.jwks_url() == \
        "https://broker/realms/x/protocol/openid-connect/certs"
    assert settings.discovery_url() == \
        "https://broker/realms/x/.well-known/openid-configuration"

    # AND AN EXPLICIT KEY-SET URL KEEPS ITS QUERY, fetched as given.
    settings = load_settings(dict(base, **{
        PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
        PREFIX + "OIDC_JWKS_URL": "https://proxy/certs?realm=x"}))
    assert settings.jwks_url() == "https://proxy/certs?realm=x"


def test_the_loopback_exception_is_for_http_and_not_for_every_other_scheme(
) -> None:
    """`ftp://localhost/…` is not a broker URL, and it used to be accepted.

    THE FINDING (Copilot review of openDox-code#25, round 29, suppressed): the
    exception was written as "not https AND not loopback", which accepts EVERY
    non-https scheme on a loopback host. `HttpJwksSource` fetches with
    `httpx.get`, which cannot use `ftp://` or `file://`, so the process started
    with an unusable trust anchor and failed at readiness. Measured before the
    fix: `ftp://localhost/realms/x` and `file://127.0.0.1/realms/x` both
    ACCEPTED.

    The exception exists for a developer running a broker over plain HTTP on
    the loopback, and that is the whole of what it allows now.
    """
    from opendox.runtime.config import ConfigurationError, load_settings

    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_AUDIENCE": "opendox-runtime"}
    for issuer in ("ftp://localhost/realms/x", "file://127.0.0.1/realms/x",
                   "ws://localhost:8080/realms/x", "ftp://[::1]/realms/x"):
        with pytest.raises(ConfigurationError) as caught:
            load_settings(dict(base, **{PREFIX + "OIDC_ISSUER": issuer}))
        assert "TRUST ANCHOR" in str(caught.value), (issuer, caught.value)

    # The two that must still pass: https anywhere, http on the loopback.
    for issuer in ("https://broker/realms/x", "http://localhost:8080/realms/x",
                   "http://127.0.0.1:8080/realms/x", "http://[::1]:8080/x"):
        assert load_settings(dict(base, **{PREFIX + "OIDC_ISSUER": issuer}))


def test_a_uri_password_holding_a_space_is_redacted_whole() -> None:
    """Round 19's finding in its URI form: `\\S*` stops at the space.

    THE FINDING (Copilot review of openDox-code#25, round 29, suppressed): a
    driver quoting back a URI whose password was never percent-encoded — which
    is exactly the conninfo an operator mistypes — was redacted only to the
    first whitespace. Measured before the fix:

        'invalid dsn: postgresql://opendox:hunter 2@db.internal:5432/opendox'
        -> 'invalid dsn: <redacted> 2@db.internal:5432/opendox'

    The tail of the password and the whole host, printed beside the marker that
    says the credential was removed.

    USERINFO ENDS AT THE FIRST `@` AND CANNOT CONTAIN `/`, which is what lets
    the pattern absorb the space without running away down the line — the last
    two cases are that bound, and they are why this is not simply "redact to
    end of line".
    """
    redact = cli._DSN_SHAPED.sub

    assert redact("<redacted>",
                  "invalid dsn: postgresql://opendox:hunter 2@db.internal/x"
                  ) == "invalid dsn: <redacted>"
    assert redact("<redacted>",
                  'invalid dsn: "postgresql://opendox:my pass word@host/db"'
                  ) == 'invalid dsn: "<redacted>'
    assert redact("<redacted>", "amqps://svc:my pass@broker/vhost failed"
                  ) == "<redacted> failed"

    # A PASSWORD HOLDING BOTH `/` AND A SPACE, which is round 33's case and
    # what retired round 29's `/`-excluding bound: that form fell through to
    # the plain branch, which stops at the space, and left
    # `word@db.internal/opendox` visible.
    assert redact("<redacted>",
                  "invalid dsn: postgresql://opendox:pa/ss word@db.internal/x"
                  ) == "invalid dsn: <redacted>"

    # THE PRICE, stated rather than hidden: the DSN branch now runs to the LAST
    # `@` ON THE LINE, so a line holding a DSN and a later unrelated `@` loses
    # the text between them. There is no pattern that both absorbs arbitrary
    # userinfo and stops before that `@`, and this act's own rule is that a
    # truncated message redacts MORE rather than less.
    assert redact("<redacted>", "postgresql://host/db for user a@b"
                  ) == "<redacted>"
    # A line with no `@` at all is untouched past the URI, and a newline is
    # never crossed.
    assert redact("<redacted>", "reached postgresql://host:5432/db fine"
                  ) == "reached <redacted> fine"
    assert redact("<redacted>", "first postgresql://u:p@h/db\nsecond kept"
                  ) == "first <redacted>\nsecond kept"


#: Attributes of an exception that are a DATUM rather than the driver's own
#: message, and may therefore be formatted into evidence. Each is a fact about
#: WHERE or WHAT KIND, and none of them is the text a library composed out of
#: the caller's value: `reason`/`start` (`UnicodeDecodeError`), `code` (this
#: package's own machine code), `sqlstate` (psycopg), `errno`/`filename`/
#: `lineno`. `args`, `msg`, `message`, `strerror`, `detail`, `stderr` and
#: `stdout` are deliberately NOT here — they are the message.
BENIGN_EXCEPTION_ATTRIBUTES = frozenset({
    "reason", "start", "end", "code", "sqlstate", "errno", "filename",
    "lineno", "returncode", "__class__", "__name__",
})

#: Calls that turn an exception into TEXT. Every other call may be handed the
#: exception itself — `store.close(exc)` passes an object, `getattr(exc,
#: "sqlstate", None)` reads a datum, and neither composes a message.
STRINGIFIERS = frozenset({"str", "repr", "format", "ascii"})


def _exception_classes_this_package_defines() -> frozenset[str]:
    """Every exception class name declared under `src/opendox/`.

    An exception THIS PACKAGE raises carries text this package wrote, so
    formatting it into evidence is safe by construction — that is what makes
    `str(exc)` legitimate in `app._found` (an `identity.NotFoundError`) and a
    leak in `config._split_url` (a `ValueError` from CPython, whose
    `_checknetloc` message quotes the whole netloc, password included).
    """
    import ast

    owned: set[str] = set()
    for module in sorted((Path(cli.__file__).parents[1]).rglob("*.py")):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef) and any(
                    "Error" in ast.unparse(base) or "Refused" in ast.unparse(base)
                    or "Exception" in ast.unparse(base)
                    for base in node.bases):
                owned.add(node.name)
    return frozenset(owned)


def _unredacted_exception_uses(source: str) -> list[str]:
    """Every use of a bound exception that could put a library's text in evidence.

    THE RULE, and it is the one A25-1 escaped by living in another file: inside
    `except … as exc`, the name may be reached by `type(exc)`, by
    `_safe_message(exc)`, as the `from` of a `raise`, by one of the benign
    attributes above, or as an argument to a call that is not a stringifier.
    Formatting it as TEXT — `str(exc)`, or an f-string — is allowed only where
    every type the handler catches is one this package defines, because then
    the text is this package's own.
    """
    import ast

    owned = _exception_classes_this_package_defines()
    tree = ast.parse(source)
    body = source.splitlines()
    findings: list[str] = []

    def caught_is_all_ours(handler: ast.ExceptHandler) -> bool:
        if handler.type is None:
            return False
        node = handler.type
        parts = node.elts if isinstance(node, ast.Tuple) else [node]
        return all(ast.unparse(part).rsplit(".", 1)[-1] in owned
                   for part in parts)

    for handler in [n for n in ast.walk(tree)
                    if isinstance(n, ast.ExceptHandler) and n.name]:
        ours = caught_is_all_ours(handler)
        allowed: set[int] = set()
        formatted: set[int] = set()
        for node in ast.walk(handler):
            if isinstance(node, ast.Call):
                # The called NAME, whether it is `str(...)` or `x.format(...)`
                # — a stringifier reached through an attribute composes text
                # exactly as the builtin does.
                called = (node.func.id if isinstance(node.func, ast.Name)
                          else getattr(node.func, "attr", ""))
                arguments = [a for a in node.args
                             if isinstance(a, ast.Name)
                             and a.id == handler.name]
                if called in {"_safe_message", "type"}:
                    allowed.update(id(a) for a in arguments)
                elif called in STRINGIFIERS:
                    formatted.update(id(a) for a in arguments)
                else:                        # an object passed, not composed
                    allowed.update(id(a) for a in arguments)
            if isinstance(node, ast.Raise) and isinstance(node.cause, ast.Name):
                if node.cause.id == handler.name:
                    allowed.add(id(node.cause))
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == handler.name
                    and node.attr in BENIGN_EXCEPTION_ATTRIBUTES):
                allowed.add(id(node.value))
            if isinstance(node, ast.FormattedValue):
                for inner in ast.walk(node.value):
                    if (isinstance(inner, ast.Name)
                            and inner.id == handler.name):
                        formatted.add(id(inner))
        for node in ast.walk(handler):
            if not (isinstance(node, ast.Name) and node.id == handler.name):
                continue
            if id(node) in allowed:
                continue
            if id(node) in formatted and ours:
                continue
            findings.append(
                f"line {node.lineno}: {body[node.lineno - 1].strip()}")
        # AND THE TWO SHAPES THAT REACH THE TEXT WITHOUT NAMING IT.
        for node in ast.walk(handler):
            if isinstance(node, ast.Call):
                called = ast.unparse(node.func)
                if called in {"traceback.format_exc", "sys.exc_info",
                              "traceback.print_exc"}:
                    findings.append(
                        f"line {node.lineno}: {body[node.lineno - 1].strip()}")
    return sorted(set(findings))


@pytest.mark.parametrize("module", sorted(
    path.name for path in Path(cli.__file__).parent.glob("*.py")))
def test_no_handler_in_this_package_emits_an_exception_without_the_redactor(
        module: str) -> None:
    """The redaction contract is asked of the SHAPE — and of EVERY module.

    Round 35 named five handlers in `cli.py` that formatted `str(exc)`; the
    answer was an AST walk, and the walk was scoped to `Path(cli.__file__)`
    alone. `config.py`, `oidc.py`, `migrations.py`, `identity.py`, `app.py` and
    `db.py` all compose messages an operator reads, and A25-1 — a malformed
    `OPENDOX_OIDC_ISSUER` printing its own password out of `runtime status` —
    lived in exactly that gap for thirty-six review rounds (independent
    adversarial review of openDox-code#25, A25-1 and A25-4).

    So the scan runs over every module in the package, and the rule is stated
    rather than allow-listed by line: a library's exception text may not be
    formatted into evidence, and this package's own may, because this package
    wrote it.

    NOT FLAGGED, AND ON PURPOSE: a bare `raise` inside a handler. It re-raises
    the SAME exception to a caller that must still handle it — `_LazyStore`
    and `CachingJwks._refresh_locked` both need that — and every escape route
    out of this package converts it. What IS flagged is reaching for the text
    without naming the exception at all: `traceback.format_exc()`,
    `traceback.print_exc()` and `sys.exc_info()` inside a handler.
    """
    source = (Path(cli.__file__).parent / module).read_text(encoding="utf-8")
    assert _unredacted_exception_uses(source) == [], (
        f"{module} puts a library's exception text into evidence without "
        "`_safe_message`")


def test_that_scan_is_run_against_every_shape_it_forbids() -> None:
    """A scan that quietly stopped finding anything is not a clean tree.

    Each case below is a real defect this package has actually shipped: the
    round-35 `str(exc)` in a `MigrationError` handler, A25-1's `{exc}` for a
    `ValueError` from CPython, and a handler reaching for the traceback.
    """
    forbidden = (
        'try:\n    pass\nexcept ValueError as exc:\n'
        '    _emit({"message": str(exc)})\n',
        'try:\n    pass\nexcept ValueError as exc:\n'
        '    raise ConfigurationError(f"not a URL ({exc})") from exc\n',
        'import traceback\ntry:\n    pass\nexcept ValueError as exc:\n'
        '    print(exc.args)\n',
        'import traceback\ntry:\n    pass\nexcept ValueError as exc:\n'
        '    print(traceback.format_exc())\n',
    )
    for source in forbidden:
        assert _unredacted_exception_uses(source), source

    # AND THE THREE SHAPES IT MUST NOT FLAG, or it would forbid the package's
    # own correct code: the redactor, the class name, a benign attribute, a
    # chained cause, an object passed on, and this package's own message.
    allowed = (
        'try:\n    pass\nexcept ValueError as exc:\n'
        '    _emit({"message": _safe_message(exc)})\n',
        'try:\n    pass\nexcept ValueError as exc:\n'
        '    _emit({"refusal": type(exc).__name__})\n',
        'try:\n    pass\nexcept UnicodeDecodeError as exc:\n'
        '    raise MigrationError(f"at byte {exc.start}: {exc.reason}")\n',
        'try:\n    pass\nexcept OSError as exc:\n'
        '    raise RuntimeError("could not read") from exc\n',
        'try:\n    pass\nexcept OSError as exc:\n    store.close(exc)\n',
        'class ConfigurationError(Exception):\n    pass\n'
        'try:\n    pass\nexcept ConfigurationError as exc:\n'
        '    _emit({"message": str(exc)})\n',
    )
    for source in allowed:
        assert _unredacted_exception_uses(source) == [], source


def test_a_malformed_broker_url_never_prints_its_own_password() -> None:
    """The defect the widened scan exists to have caught.

    `_split_url` interpolated the driver's message, and CPython's
    `_checknetloc` raises `ValueError("netloc '<the whole netloc>' contains
    invalid characters under NFKC normalization")` — userinfo and password
    included. A hostname that is not ASCII is the ordinary case for an IDN
    broker, and `_split_url` runs BEFORE the userinfo refusal, so the guard
    written to keep a password out of this very message never ran. `runtime
    status` and `runtime init` printed `hunter2` on stdout, in the JSON the
    lifecycle contract calls redacted evidence, and `_safe_message` did not
    catch it either: the leaked run is `netloc 'svc:hunter2@…'`, which has no
    `://` and no `password=` (independent adversarial review of
    openDox-code#25, A25-1).

    U+2100 (ACCOUNT OF) is one of the characters that NFKC-expand to one of
    `/?#@:`; any of them reaches the same branch.
    """
    import io
    import json
    from contextlib import redirect_stdout

    from opendox.runtime.config import ConfigurationError, load_settings

    issuer = "https://svc:hunter2@broker\u2100evil.example/realms/x"
    env = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
           PREFIX + "OIDC_AUDIENCE": "opendox",
           PREFIX + "OIDC_ISSUER": issuer}

    with pytest.raises(ConfigurationError) as caught:
        load_settings(env)
    message = str(caught.value)
    assert "hunter2" not in message, message
    assert "svc:" not in message
    # THE SETTING IS STILL NAMED, and the reader is still told what is wrong.
    assert PREFIX + "OIDC_ISSUER" in message
    assert "ValueError" in message

    # AND THE EXCEPTION CHAIN IS CLEAN TOO, because a traceback printed by
    # anything at all would carry the cause with it.
    import traceback
    chain = "".join(traceback.format_exception(
        type(caught.value), caught.value, caught.value.__traceback__))
    assert "hunter2" not in chain
    assert caught.value.__cause__ is None
    assert "hunter2" not in cli._safe_message(caught.value)

    # AND THROUGH THE SHIPPED VERB, on stdout, which is where it was printed.
    printed = io.StringIO()
    with redirect_stdout(printed):
        code = cli.main(["runtime", "status"], env=env) if _status_takes_env() \
            else _status_with(env)
    assert code != 0
    evidence = json.loads(printed.getvalue())
    assert evidence["ok"] is False
    assert "hunter2" not in printed.getvalue()
    assert "hunter2" not in json.dumps(evidence)


def _status_takes_env() -> bool:
    import inspect
    return "env" in inspect.signature(cli.main).parameters


def _status_with(env: dict[str, str]) -> int:
    """`runtime status` with exactly this environment and nothing inherited."""
    import os

    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        return cli.main(["runtime", "status"])
    finally:
        os.environ.clear()
        os.environ.update(previous)


def test_the_serve_boundary_redacts_a_traceback_uvicorn_would_log() -> None:
    """`_safe_message` covers what this module prints; `serve` lends the process.

    Uvicorn logs a failed lifespan itself, with `exc_info`, before `cmd_serve`
    reaches its own handler, and psycopg names the whole conninfo in the text
    of an exception raised for an unparsable DSN — so the password went to
    stderr in a traceback while the JSON beside it was redacted (Copilot review
    of openDox-code#25, round 34).

    THE CASE IS MEASURED BOTH WAYS. The same record is formatted with the
    boundary down and with it up: the first is the leak, the second is the
    fix, and a boundary that stopped working could not pass both halves.
    """
    import logging

    secret = "postgresql://opendox:hunter2@db.internal:5432/opendox"

    def one_record() -> logging.LogRecord:
        try:
            raise RuntimeError(f"could not connect: {secret}")
        except RuntimeError:
            import sys
            return logging.getLogRecordFactory()(
                "uvicorn.error", logging.ERROR, __file__, 1,
                "Application startup failed. Exiting.", (), sys.exc_info())

    formatter = logging.Formatter("%(message)s")

    leaked = formatter.format(one_record())
    assert "hunter2" in leaked and "Traceback" in leaked

    with cli.redacting_every_log_record():
        guarded = formatter.format(one_record())
    assert "hunter2" not in guarded
    assert "opendox:hunter2@db.internal" not in guarded
    assert "<redacted>" in guarded
    # THE REST OF THE TRACEBACK SURVIVES: a redaction that dropped the
    # exception entirely would take the operator's only clue with it.
    assert "RuntimeError" in guarded and "could not connect" in guarded

    # THE MESSAGE, ITS `%`-ARGUMENTS AND THE STACK TEXT ARE COVERED TOO —
    # a DSN reaches a log line three ways, and a number must stay a number.
    with cli.redacting_every_log_record():
        # `sinfo` IS THE FACTORY'S NINTH ARGUMENT, which is how
        # `Logger.makeRecord` passes a `stack_info=True` call's stack — setting
        # the attribute after construction would test a shape logging never
        # produces.
        record = logging.getLogRecordFactory()(
            "uvicorn.error", logging.ERROR, __file__, 1,
            "dsn %s port %d", (secret, 5432), None, None,
            f"  File x, in y\n    connect({secret})")
        rendered = formatter.format(record)
    assert "hunter2" not in rendered and "port 5432" in rendered
    assert "hunter2" not in record.stack_info

    # AND THE GLOBAL IS PUT BACK on the way out, including after an exception,
    # because `cmd_serve` is importable and the tests call it in-process.
    before = logging.getLogRecordFactory()
    with pytest.raises(ZeroDivisionError):
        with cli.redacting_every_log_record():
            assert logging.getLogRecordFactory() is not before
            1 / 0
    assert logging.getLogRecordFactory() is before


def test_the_serve_verb_installs_that_boundary_around_uvicorn() -> None:
    """The boundary is worth nothing if `serve` does not stand inside it.

    It is installed BEFORE `uvicorn.Config`, which is where uvicorn runs its
    own `dictConfig`, and it is still up inside `run()`, which is where the
    lifespan fails.
    """
    import ast

    source = Path(cli.__file__).read_text(encoding="utf-8")
    serve = next(n for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.FunctionDef) and n.name == "cmd_serve")
    withs = [n for n in ast.walk(serve) if isinstance(n, ast.With)
             and any(isinstance(i.context_expr, ast.Call)
                     and isinstance(i.context_expr.func, ast.Name)
                     and i.context_expr.func.id == "redacting_every_log_record"
                     for i in n.items)]
    assert len(withs) == 1, "serve must stand inside exactly one boundary"
    inside = ast.dump(withs[0])
    assert "uvicorn" in inside and "'Config'" in inside
    assert "'run'" in inside


def test_two_dsns_that_select_different_schemas_are_refused() -> None:
    """Migrations must land where the API reads, or neither answer means anything.

    `OPENDOX_DATABASE_URL` and `OPENDOX_MIGRATION_DATABASE_URL` are
    independently configurable and nothing tied them together: the runner
    derives its schema from the second and the served `Database` from the
    first, so two DSNs at one database with different `search_path` options let
    a run apply and VERIFY schema A while `/readyz` and the API read schema B —
    including a pre-existing fully migrated schema, which is another install's
    coordination data (Copilot review of openDox-code#25, round 34).

    THE REFUSAL IS AT CONFIGURATION TIME, before anything connects, because
    the alternative is discovering it from a migrated-looking database.
    """
    from opendox.runtime.config import (
        ConfigurationError,
        load_settings,
        schema_selected_by,
    )

    # WHAT THE STRING CAN BE ASKED, in every form libpq accepts: the URI query
    # (percent-encoded, which is the only way `-c search_path=x` survives a
    # query string), the attached `-csearch_path=x` spelling, and the
    # keyword/value conninfo — where the value holds a space and libpq
    # therefore quotes it, which a `str.split()` read of the string missed.
    assert schema_selected_by(
        "postgresql://u:p@h/db?options=-c%20search_path%3Dtenant%2Cpublic"
    ) == "tenant"
    assert schema_selected_by(
        "postgresql://u:p@h/db?options=-csearch_path%3Dtenant") == "tenant"
    assert schema_selected_by(
        "host=h dbname=db options='-c search_path=tenant'") == "tenant"
    assert schema_selected_by(
        'host=h dbname=db options="-c search_path=tenant,public"') == "tenant"
    # THE FIRST ENTRY IS THE ANSWER, because that is where an unqualified
    # `create table` lands — which is the question `selected_schema` asks of a
    # live connection.
    # A SPACE IN A SCHEMA NAME IS BACKSLASH-ESCAPED, because that is what
    # libpq's `options` takes: whitespace separates arguments there and there
    # is no quote processing, so `search_path="a b"` reaches the backend as
    # two arguments and not as one quoted name. This reports what the backend
    # would select, which is the whole point of reading the string.
    assert schema_selected_by(
        "postgresql://u:p@h/db?options=-c%20search_path%3D%22a%5C%20b%22%2Cc"
    ) == "a b"
    # AND A DSN THAT SELECTS NOTHING SELECTS NOTHING: the server's own default
    # for the role is not in the string and is not guessed at here.
    assert schema_selected_by("postgresql://u:p@h/db") is None
    assert schema_selected_by("host=h dbname=db") is None
    assert schema_selected_by("postgresql://u:p@h/db?options=-c%20work_mem%3D1"
                             ) is None

    base = {PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_AUDIENCE": "opendox"}
    served = "postgresql://u:p@h/db?options=-c%20search_path%3Dserved"
    migration = "postgresql://m:p@h/db?options=-c%20search_path%3Dmigrated"

    with pytest.raises(ConfigurationError) as refused:
        load_settings({**base, PREFIX + "DATABASE_URL": served,
                       PREFIX + "MIGRATION_DATABASE_URL": migration})
    message = str(refused.value)
    assert "served" in message and "migrated" in message
    assert PREFIX + "DATABASE_URL" in message
    assert PREFIX + "MIGRATION_DATABASE_URL" in message
    # THE REFUSAL NAMES THE SCHEMAS AND NOTHING ELSE — a DSN carries a
    # password, and this is the one refusal that has two of them in hand.
    assert "p@h" not in message and "://" not in message

    # ONE SCHEMA, OR NONE NAMED IN EITHER, IS ACCEPTED.
    same = "postgresql://m:p@h/db?options=-c%20search_path%3Dserved"
    assert load_settings({**base, PREFIX + "DATABASE_URL": served,
                          PREFIX + "MIGRATION_DATABASE_URL": same})
    assert load_settings({**base,
                          PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
                          PREFIX + "MIGRATION_DATABASE_URL":
                              "postgresql://m:p@h/db"})
    # AND A MIGRATION DSN THAT IS SIMPLY ABSENT is the documented single-role
    # deployment, not a mismatch.
    assert load_settings({**base, PREFIX + "DATABASE_URL": served})

    # THE OTHER DIRECTION IS REFUSED TOO: a served DSN that names no schema
    # beside a migration DSN that names one is the same split, and the
    # connection default is what the message calls the unnamed side.
    with pytest.raises(ConfigurationError) as either_way:
        load_settings({**base,
                       PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
                       PREFIX + "MIGRATION_DATABASE_URL": migration})
    assert "the connection default" in str(either_way.value)


def test_two_dsns_naming_different_databases_are_refused_too() -> None:
    """The schema comparison means nothing across two databases.

    `public` in one database and `public` in another are two different sets of
    tables, so two DSNs that agree about the schema and disagree about the
    database passed the round-34 check — and migrations applied and VERIFIED
    one while `/readyz` and the API read the other (Copilot review of
    openDox-code#25, round 36).

    AND THE COMMA-QUOTING BUG IN THE SAME PREFLIGHT: it reduced `search_path`
    with `.split(",")[0]`, so the legal, distinct schema names `"tenant,blue"`
    and `"tenant,red"` both became `tenant` and two DSNs selecting genuinely
    different schemas compared equal — which is exactly the defect
    `migrations._path_entries` exists to prevent, one layer earlier.
    """
    from opendox.runtime import migrations
    from opendox.runtime.config import (
        ConfigurationError,
        database_named_by,
        load_settings,
        schema_selected_by,
        search_path_entries,
        unquoted_identifier,
    )

    # ONE PARSER, NOT TWO SPELLINGS OF IT. The migration runner reads a live
    # connection's path with the same two functions; a second, simpler
    # spelling is how the two came to disagree in the first place.
    assert migrations._path_entries is search_path_entries
    assert migrations._unquoted is unquoted_identifier

    quoted = ("postgresql://u:p@h/db?options="
              "-c%20search_path%3D%22tenant%2Cblue%22%2Cpublic")
    other = ("postgresql://u:p@h/db?options="
             "-c%20search_path%3D%22tenant%2Cred%22")
    assert schema_selected_by(quoted) == "tenant,blue"
    assert schema_selected_by(other) == "tenant,red"
    # libpq's `options` has NO quote processing — whitespace separates and a
    # backslash escapes — so the double quotes belong to PostgreSQL's
    # identifier syntax and must survive the split that finds `-c`.
    assert schema_selected_by(
        r"postgresql://u:p@h/db?options=-c%20search_path%3D%22a%5C%20b%22"
    ) == "a b"
    # AND AN UNESCAPED SPACE IS NOT ONE ARGUMENT TO LIBPQ EITHER, so reading
    # it as one would be a different answer from the one the server gets:
    # `options=-c search_path="a b"` reaches the backend as `-c` and
    # `search_path="a`, and this reports what the backend would select.
    assert schema_selected_by(
        "host=h dbname=db options='-c search_path=\"a b\",public'") == '"a'

    base = {PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_AUDIENCE": "opendox"}
    with pytest.raises(ConfigurationError) as split_schema:
        load_settings({**base, PREFIX + "DATABASE_URL": quoted,
                       PREFIX + "MIGRATION_DATABASE_URL": other})
    assert "tenant,blue" in str(split_schema.value)
    assert "tenant,red" in str(split_schema.value)

    # THE DATABASE IS COMPARED FIRST, in both DSN forms, and no credential is
    # read to do it.
    assert database_named_by("postgresql://u:p@h:5432/opendox?x=1") == "opendox"
    assert database_named_by("host=h dbname=coord user=u") == "coord"
    assert database_named_by("postgresql://u:p@h/") is None
    assert database_named_by("host=h") is None

    with pytest.raises(ConfigurationError) as split_database:
        load_settings({**base,
                       PREFIX + "DATABASE_URL": "postgresql://u:p@h/one",
                       PREFIX + "MIGRATION_DATABASE_URL":
                           "postgresql://m:p@h/two"})
    message = str(split_database.value)
    assert "one" in message and "two" in message
    assert "://" not in message and "p@h" not in message

    # AND A POOLER IS NOT A SECOND SERVER. A served DSN through a connection
    # pooler beside a migration DSN direct to the database is the ordinary
    # secure shape, and nothing in either string tells the two apart — so the
    # host and port are deliberately not compared, and this pins that.
    assert load_settings({**base,
                          PREFIX + "DATABASE_URL":
                              "postgresql://u:p@pooler:6432/one",
                          PREFIX + "MIGRATION_DATABASE_URL":
                              "postgresql://m:p@db.internal:5432/one"})


def test_the_two_dsn_reader_answers_what_libpq_answers_for_a_REPEATED_key() -> None:
    """A KEY GIVEN TWICE — and both readers took the FIRST, which libpq does not.

    The preflight compares two DSNs by the database each names and the schema
    each selects. Both readers stopped at the first match, so a DSN that says
    a thing twice was read as saying the FIRST thing, and the two ways of
    saying it twice are exactly the two ways an operator ends up with one:
    an `options` string assembled by appending (`-csearch_path=old
    -csearch_path=new`, from a base DSN plus an override) and a URI that names
    the database in the path AND in the query (`postgresql://h/frompath?
    dbname=fromquery`, from a template plus a parameter). The preflight then
    passes on a comparison of values the server will never use, which is worse
    than not comparing: it reports agreement that is not there.

    BOTH ANSWERS ARE MEASURED AGAINST THE REAL THING, not reasoned out. On
    postgres 16, `psql "…?options=-csearch_path%3Dold -csearch_path%3Dnew"`
    followed by `show search_path` prints `new`; and
    `psycopg.conninfo.conninfo_to_dict`, which is `PQconninfoParse`, resolves
    `postgresql://h/frompath?dbname=fromquery` to `dbname=fromquery` and
    `…?dbname=one&dbname=two` to `dbname=two`. Last assignment wins in both,
    and the query beats the path.
    """
    from opendox.runtime.config import database_named_by, schema_selected_by

    # (1) THE LAST `-c search_path=` IS THE ONE THE BACKEND GETS.
    assert schema_selected_by(
        "postgresql://u:p@h/db?options=-csearch_path%3Dold%20-csearch_path%3Dnew"
    ) == "new"
    assert schema_selected_by(
        "postgresql://u:p@h/db?options="
        "-c%20search_path%3Done%20-c%20search_path%3Dtwo") == "two"
    assert schema_selected_by(
        "host=h dbname=db options='-c search_path=one -c search_path=two'"
    ) == "two"
    # AND THE FIRST ENTRY OF THE LAST ASSIGNMENT, since both reductions apply.
    assert schema_selected_by(
        "host=h dbname=db options='-c search_path=a,b -c search_path=c,d'"
    ) == "c"
    # A LATER `-c` FOR A DIFFERENT SETTING IS NOT AN OVERRIDE, which is the
    # error the fix could have made in the other direction.
    assert schema_selected_by(
        "host=h dbname=db options='-c search_path=kept -c work_mem=1'"
    ) == "kept"

    # (2) THE QUERY NAMES THE DATABASE TOO, and beats the path when both do.
    assert database_named_by("postgresql://h/frompath") == "frompath"
    assert database_named_by("postgresql://h/?dbname=fromquery") == "fromquery"
    assert database_named_by(
        "postgresql://h/frompath?dbname=fromquery") == "fromquery"
    assert database_named_by("postgresql://h/?dbname=one&dbname=two") == "two"
    assert database_named_by("host=h dbname=one dbname=two") == "two"

    # AND THE PREFLIGHT THEREFORE REFUSES THE PAIR IT USED TO PASS: two URIs
    # that agree in the path and disagree in the query are two databases.
    base = {PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_AUDIENCE": "opendox"}
    from opendox.runtime.config import ConfigurationError, load_settings
    with pytest.raises(ConfigurationError) as refused:
        load_settings({**base,
                       PREFIX + "DATABASE_URL":
                           "postgresql://u:p@h/same?dbname=served",
                       PREFIX + "MIGRATION_DATABASE_URL":
                           "postgresql://m:p@h/same?dbname=migrated"})
    message = str(refused.value)
    assert "served" in message and "migrated" in message
    assert "u:p@" not in message and "m:p@" not in message
    # AND THE APPENDED-OPTIONS PAIR, which is the `search_path` half of it.
    with pytest.raises(ConfigurationError) as schemas:
        load_settings({**base,
                       PREFIX + "DATABASE_URL":
                           "postgresql://u:p@h/db?options="
                           "-csearch_path%3Dbase%20-csearch_path%3Dserved",
                       PREFIX + "MIGRATION_DATABASE_URL":
                           "postgresql://m:p@h/db?options="
                           "-csearch_path%3Dbase%20-csearch_path%3Dmigrated"})
    assert "served" in str(schemas.value) and "migrated" in str(schemas.value)


def test_a_credential_shaped_parameter_name_is_a_WORD_and_not_a_substring() -> None:
    """`monkey` contains `key`, and the first cut refused it.

    `SECRET_PARAMETER_KEYS` was compiled into an alternation and asked with
    `.search()`, so any parameter whose name merely CONTAINED one of the words
    matched: `monkey`, `sigma`, `tokenizer`, `authority`, `keyspace`. A broker
    URL or a git remote carrying `?monkey=1` was then refused as
    credential-bearing — a false refusal at the configuration boundary, where
    the cost is an install that will not start for a reason that is not true
    (Copilot review of openDox-code#25, at `056d1597`).

    THE COMPOUND NAMES MUST STILL MATCH, which is why this is a word split and
    not an equality test: `access_token`, `X-Api-Key` and `sessionToken` are
    how these parameters are really spelled.
    """
    from opendox.runtime.config import (
        SECRET_PARAMETER_KEYS,
        ConfigurationError,
        credential_in_a_remote_url,
        load_settings,
        names_a_secret_parameter,
        redacted_url,
    )

    for benign in ("monkey", "sigma", "tokenizer", "authority", "keyspace",
                   "format", "realm", "keyboard", "passage"):
        assert not names_a_secret_parameter(benign), benign
    for carrier in ("token", "access_token", "X-Api-Key", "sessionToken",
                    "api_key", "apikey", "pwd", "PASSWORD", "x-credentials"):
        assert names_a_secret_parameter(carrier), carrier
    # EVERY DECLARED WORD IS ITSELF A MATCH, so the list cannot drift away
    # from the predicate that reads it.
    for word in SECRET_PARAMETER_KEYS:
        assert names_a_secret_parameter(word), word

    # AND THROUGH THE THREE CALLERS, which is where the refusal is felt.
    assert credential_in_a_remote_url(
        "https://github.com/o/r.git?monkey=1") is None
    assert credential_in_a_remote_url(
        "https://github.com/o/r.git?access_token=x") is not None
    assert redacted_url("https://broker/certs?monkey=1"
                        ) == "https://broker/certs?monkey=1"
    assert redacted_url("https://broker/certs?token=x"
                        ) == "https://broker/certs?token=<redacted>"
    base = {PREFIX + "DATABASE_URL": "postgresql://u:p@h/db",
            PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_AUDIENCE": "opendox"}
    settings = load_settings({**base,
                              PREFIX + "OIDC_JWKS_URL":
                                  "https://broker/certs?monkey=1&format=jwk"})
    assert settings.oidc_jwks_url == "https://broker/certs?monkey=1&format=jwk"
    with pytest.raises(ConfigurationError):
        load_settings({**base, PREFIX + "OIDC_JWKS_URL":
                       "https://broker/certs?api_key=hunter2"})


def test_a_dsn_that_names_no_database_still_reaches_one() -> None:
    """Two `None`s were read as agreement, and they are two DIFFERENT defaults.

    `database_named_by` reports what the STRING says, so two DSNs that both
    leave the database out both answered `None` and the preflight passed the
    pair. libpq then defaults `dbname` to the CONNECTION USER — and this
    deployment's two DSNs carry deliberately different users, the privileged
    migration identity and the least-privileged served one, which is the whole
    point of the split. So the guard passed exactly the configuration it
    exists to refuse (Copilot review of openDox-code#25, at `0968ff8b`).

    MEASURED on postgres 16 rather than argued:
    `postgresql://opendox:…@host:5432/` — no database in the path and no
    `dbname` anywhere — connects, and `select current_database()` answers
    `opendox`, the user's name. `PQconninfoParse` does not fill that default
    in, so it is invisible in the parse and applied at connect.

    AND NEITHER-NOR IS UNRESOLVED, not a shared default: with no database and
    no user in the string libpq falls back to the OPERATING SYSTEM user of
    whichever process connects, and the two DSNs are used by two different
    containers. A comparison that cannot be made is a refusal — the rule this
    module already applies to a broker URL it cannot parse.
    """
    from opendox.runtime.config import (
        ConfigurationError,
        database_named_by,
        effective_database,
        load_settings,
        user_named_by,
    )

    # THE USER IS READ THE WAY LIBPQ READS IT, measured through
    # `PQconninfoParse` (`psycopg.conninfo.conninfo_to_dict`): the query beats
    # the userinfo, the last repeat wins, and the userinfo is percent-decoded.
    assert user_named_by("postgresql://my%20user@h/db") == "my user"
    assert user_named_by("postgresql://userinfo@h/db?user=fromquery") == "fromquery"
    assert user_named_by("postgresql://h/db?user=one&user=two") == "two"
    assert user_named_by("host=h user=one user=two dbname=x") == "two"
    assert user_named_by("postgresql://h/db") is None
    assert user_named_by("host=h dbname=x") is None

    # THE DEFAULT IS A NAME. The string says nothing; the connection does.
    assert database_named_by("postgresql://served:p@h:5432/") is None
    assert effective_database("postgresql://served:p@h:5432/") == "served"
    assert effective_database("host=h user=served") == "served"
    # An explicit database still wins over the user, which is libpq's order.
    assert effective_database("postgresql://served:p@h/opendox") == "opendox"
    # And with neither, nothing here can say.
    assert effective_database("postgresql://h:5432/") is None

    base = {PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_AUDIENCE": "opendox"}

    def _load(served: str, migration: str):
        return load_settings({**base, PREFIX + "DATABASE_URL": served,
                              PREFIX + "MIGRATION_DATABASE_URL": migration})

    # THE PAIR THE GUARD USED TO PASS: two users, no database in either.
    with pytest.raises(ConfigurationError) as split:
        _load("postgresql://served:p@h/", "postgresql://migrator:p@h/")
    message = str(split.value)
    assert "served" in message and "migrator" in message
    assert "named after" in message, (
        "the refusal must say WHERE the database name came from, because it "
        "is nowhere in the operator's own DSN")
    assert ":p@" not in message, "the refusal repeated a password"

    # AND THE PAIR NOTHING CAN ANSWER FOR.
    with pytest.raises(ConfigurationError) as unresolved:
        _load("postgresql://h/", "postgresql://h/")
    assert "neither a database nor a user" in str(unresolved.value)
    assert "operating system user" in str(unresolved.value).lower()

    # ONE SIDE RESOLVED AND ONE NOT IS STILL UNRESOLVED, and the refusal names
    # the side that cannot answer rather than both.
    with pytest.raises(ConfigurationError) as lopsided:
        _load("postgresql://h/", "postgresql://migrator:p@h/opendox")
    assert PREFIX + "DATABASE_URL" in str(lopsided.value)
    assert PREFIX + "MIGRATION_DATABASE_URL" not in str(lopsided.value)

    # AND THE ORDINARY SHAPE IS UNTOUCHED: two identities, one database, named.
    assert _load("postgresql://served:p@h/opendox",
                 "postgresql://migrator:p@h/opendox")
    # Including two users whose DSNs omit the database but agree on it, which
    # is a single-role install and not a split.
    assert _load("postgresql://opendox:p@h/", "postgresql://opendox:p2@h/")


def test_the_dollar_user_search_path_token_is_expanded_before_it_is_compared() -> None:
    """`"$user"` is a TOKEN, and two roles' `"$user"` are two schemas.

    The preflight compared the string, so two DSNs for different roles both
    selecting `"$user",public` agreed on `$user` while PostgreSQL resolved
    them to different schemas — the split this guard exists to refuse, wearing
    the agreement it was looking for (Copilot review of openDox-code#25, at
    `0968ff8b`).

    MEASURED on postgres 16, and the middle measurement is the one that
    settles how to treat it:

      set search_path = "$user", public      -> current_schema() = public
      … with a schema LITERALLY NAMED `$user` -> current_schema() = public
      … with a schema named for the session user -> current_schema() = <user>

    PostgreSQL never reads `"$user"` as the name of a schema, even when such a
    schema exists, so substituting it here matches the server — and the
    quoted-versus-literal distinction does not change the answer. (`set
    search_path = $user` unquoted is a syntax error: the token is always
    written quoted.)
    """
    import urllib.parse

    from opendox.runtime.config import (
        ConfigurationError,
        effective_schema,
        load_settings,
        schema_selected_by,
    )

    def _dsn(user: str | None, path: str) -> str:
        authority = f"{user}:p@" if user else ""
        return (f"postgresql://{authority}h/db?options=-csearch_path%3D"
                + urllib.parse.quote(path, safe=""))

    # THE STRING STILL REPORTS THE TOKEN — that is what the DSN says — and the
    # resolved answer is the user's name.
    assert schema_selected_by(_dsn("alice", '"$user",public')) == "$user"
    assert effective_schema(_dsn("alice", '"$user",public')) == "alice"
    assert effective_schema(_dsn("bob", '"$user",public')) == "bob"
    # A schema named by hand is untouched by the substitution.
    assert effective_schema(_dsn("alice", "tenant,public")) == "tenant"
    # And with no user in the string there is nothing to substitute.
    assert effective_schema(_dsn(None, '"$user",public')) is None

    base = {PREFIX + "OIDC_ISSUER": "https://broker/realms/x",
            PREFIX + "OIDC_AUDIENCE": "opendox"}

    def _load(served: str, migration: str):
        return load_settings({**base, PREFIX + "DATABASE_URL": served,
                              PREFIX + "MIGRATION_DATABASE_URL": migration})

    # THE PAIR THE GUARD USED TO PASS.
    with pytest.raises(ConfigurationError) as split:
        _load(_dsn("alice", '"$user",public'), _dsn("bob", '"$user",public'))
    message = str(split.value)
    assert "alice" in message and "bob" in message
    assert ":p@" not in message, "the refusal repeated a password"

    # THE SAME ROLE IS THE SAME SCHEMA, so this refuses a mismatch and not the
    # `"$user"` idiom itself.
    assert _load(_dsn("alice", '"$user",public'), _dsn("alice", '"$user"'))

    # AND THE TOKEN WITH NO USER TO SUBSTITUTE IS UNRESOLVED, not "no schema":
    # reading it as "names none" would have compared equal to a DSN that
    # really names none, which is the same false agreement one step along.
    with pytest.raises(ConfigurationError) as unresolved:
        _load(_dsn(None, '"$user",public'), "postgresql://m:p@h/db")
    assert '"$user"' in str(unresolved.value)
    assert "names no user" in str(unresolved.value)
