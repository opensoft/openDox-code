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
