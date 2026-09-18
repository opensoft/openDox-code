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


def _commands(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    actions = [a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction)]
    assert len(actions) == 1
    return actions[0]


def _verbs_of(command: argparse.ArgumentParser) -> tuple[str, ...]:
    verbs = [a for a in command._actions
             if isinstance(a, argparse._SubParsersAction)]
    assert len(verbs) == 1
    return tuple(verbs[0].choices)


def test_the_standalone_parser_declares_the_two_commands_and_no_third() -> None:
    assert list(_commands(cli.build_parser()).choices) == ["runtime", "project"]


def test_the_runtime_verb_set_is_closed_and_the_parser_declares_exactly_it() -> None:
    commands = _commands(cli.build_parser())
    assert _verbs_of(commands.choices["runtime"]) == cli.VERBS
    assert cli.VERBS == ("init", "migrate", "serve", "status", "reset")


def test_the_project_verb_set_is_closed_and_is_section_3_6s_act_and_successors(
) -> None:
    commands = _commands(cli.build_parser())
    assert _verbs_of(commands.choices["project"]) == cli.PROJECT_VERBS
    assert cli.PROJECT_VERBS == ("create-repository", "attach-remote", "push")


def test_the_project_command_collides_with_no_core_subcommand() -> None:
    """Measured against `src/opendox/cli.py`, not assumed.

    `opendox.cli` cannot be IMPORTED at this leg (its `opendox.serve` reach is
    what `tests/test_consumer_reach.py::STILL_REACHING` records), so its
    subcommand names are read out of its source — which is the only way to
    measure them here, and it is a measurement rather than a claim.
    """
    import re

    source = (Path(__file__).resolve().parents[1] / "src" / "opendox" /
              "cli.py").read_text(encoding="utf-8")
    core = set(re.findall(r'sub\.add_parser\(\s*"([a-z-]+)"', source))
    assert core, "no core subcommands found; the regex has drifted from cli.py"
    assert "project" not in core, (
        f"`opendox.cli` already declares a `project` command ({sorted(core)}); "
        "contributing this name would be a collision")


def test_the_project_registration_object_conforms_to_the_subcommand_seam() -> None:
    assert isinstance(cli.ProjectSubcommand(),
                      subcommand_extension.SubcommandExtension)


def test_registering_the_project_command_through_the_seam_gives_the_same_verbs(
) -> None:
    parser = argparse.ArgumentParser(prog="opendox")
    sub = parser.add_subparsers(dest="command", required=True)
    subcommand_extension.register_all(
        (cli.RuntimeSubcommand(), cli.ProjectSubcommand()), sub)
    contributed = [a for a in parser._actions
                   if isinstance(a, argparse._SubParsersAction)][0]
    assert list(contributed.choices) == ["runtime", "project"]
    assert _verbs_of(contributed.choices["project"]) == cli.PROJECT_VERBS


def test_every_project_verb_sets_a_dispatch_function_and_its_own_name() -> None:
    arguments = {
        "create-repository": ["--project-id", "p", "--actor", "a"],
        "attach-remote": ["--project-id", "p", "--remote-url", "u"],
        "push": ["--project-id", "p"],
    }
    for verb in cli.PROJECT_VERBS:
        args = cli.build_parser().parse_args(["project", verb, *arguments[verb]])
        assert callable(args.func)
        assert args.verb == verb
        assert args.project_id == "p"


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

@pytest.mark.parametrize(
    ("verb", "arguments"),
    [("create-repository", ["--project-id", "p", "--actor", "a"]),
     ("attach-remote", ["--project-id", "p", "--remote-url",
                        "https://example.invalid/x.git"]),
     ("push", ["--project-id", "p"])])
def test_a_project_verb_never_prints_a_dsn_it_caught_itself(
        monkeypatch: pytest.MonkeyPatch, verb: str,
        arguments: list[str]) -> None:
    """These three verbs catch before `main()`'s boundary, so they must redact.

    Each wraps its own body in `except Exception` so the evidence object can
    name the verb — and catching there means `main()`'s redaction never runs.
    With `str(exc)` a psycopg connection failure put the configured DSN,
    password included, straight into the JSON (Copilot review of
    openDox-code#26: one thread and two suppressed comments, the same shape in
    three handlers).

    THE DATABASE IS A STUB MODULE, so this runs in the REQUIRED `validate` job
    rather than only where psycopg is installed. `cli` imports
    `opendox.runtime.db` inside the function, which is the whole seam.
    """
    import sys
    import types

    dsn = "postgresql://opendox:hunter2@db.internal:5432/opendox"

    class _Exploding:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_Exploding":
            raise RuntimeError(f"connection to {dsn} failed: no password "
                               "supplied")

        def __exit__(self, *exc: object) -> None:
            pass

    db_stub = types.ModuleType("opendox.runtime.db")
    db_stub.Database = _Exploding                      # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opendox.runtime.db", db_stub)
    monkeypatch.setenv(PREFIX + "DATABASE_URL", dsn)
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")

    code, evidence = _run(cli.build_parser().parse_args(
        ["project", verb, *arguments]))
    assert code == 1, evidence
    assert evidence["ok"] is False
    assert evidence["refusal"] == "RuntimeError"
    assert "hunter2" not in evidence["message"], evidence["message"]
    # EITHER MARKER. Round 15 put the general credential rule FIRST, so a DSN
    # that carries userinfo is replaced whole as `<redacted-url>` and
    # `_DSN_SHAPED`'s `<redacted>` is the fallback for one that does not. What
    # this case is about is that the secret does not survive either way.
    assert "<redacted" in evidence["message"], evidence["message"]


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


def test_a_repository_refusal_is_redacted_like_every_other_message(
        monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """`RepositoryActRefused` was trusted to be secret-free, and it is not.

    `repository_act.repository_location` refuses a project id it cannot use as
    a directory name and ECHOES it, before any database is touched — so a
    caller-supplied id shaped like a DSN came back with its password in the
    evidence object, and in whatever collects that (Copilot review of
    openDox-code#26, round 10). A message built from caller-supplied text is
    redacted like any other this CLI emits — and, since round 19, the
    identifier is not put into that message in the first place, because
    redaction that is shaped for URLs is not a guarantee about arbitrary text.
    """
    import sys
    import types

    class _Cursor:
        def fetchone(self) -> None:
            return None

        def fetchall(self) -> list:
            return []

    class _Connection:
        def execute(self, sql: str, params: tuple | None = None) -> "_Cursor":
            # THE MAP IS ASKED FIRST, and only the map: round 14 moved the
            # authoritative row ahead of `repository_location`, so a project
            # that is already mapped is told so rather than being told about a
            # filesystem. Nothing else may run before the refusal, which is
            # what this assertion is now for.
            assert "project_repositories" in sql, sql
            assert sql.strip().lower().startswith("select"), sql
            return _Cursor()

    class _Database:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_Database":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        @contextmanager
        def transaction(self):
            yield _Connection()

    db_stub = types.ModuleType("opendox.runtime.db")
    db_stub.Database = _Database                       # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opendox.runtime.db", db_stub)
    monkeypatch.setenv(PREFIX + "DATABASE_URL",
                       "postgresql://runtime@127.0.0.1:5432/opendox")
    monkeypatch.setenv(PREFIX + "OIDC_ISSUER", "https://broker/realms/x")
    monkeypatch.setenv(PREFIX + "OIDC_AUDIENCE", "opendox-runtime")
    monkeypatch.setenv(PREFIX + "PROJECT_REPOSITORY_ROOT", str(tmp_path))

    code, evidence = _run(cli.build_parser().parse_args(
        ["project", "create-repository",
         "--project-id", "postgresql://someone:hunter2@db.internal/opendox",
         "--actor", "Student One"]))
    assert code == 1, evidence
    assert evidence["refusal"] == "repository"
    printed = json.dumps(evidence)
    assert "hunter2" not in printed, printed
    # ROUND 19 REPLACED THE REMEDY, so this assertion changed with it. The
    # round-10 fix routed this message through the redactors and asserted the
    # marker; round 19 found that those redactors are shaped for URLs and for
    # libpq conninfo and do not cover arbitrary caller text — measured, both
    # `user:secret@host/path` and `//user:pw@h/x` reach this refusal and come
    # back verbatim. So the act does not echo the identifier at all, and the
    # marker is no longer there to find. The claim is the stronger one: the
    # WHOLE value is absent, not just the part a pattern recognized.
    assert "postgresql://someone" not in printed, printed
    assert "db.internal" not in printed, printed
    assert "holds a '/'" in printed, printed


def test_the_evidence_boundary_redacts_a_credential_parameter_too() -> None:
    """`_DSN_SHAPED` is half the credential rule, and this helper is the other
    half's only boundary.

    The repository verbs route caller-controlled text — a project id, a remote
    URL from a row written before the attach rule — through `_safe_message`,
    and that helper applied the DSN pattern alone: `?token=…` is not a DSN and
    is every bit as much a credential, so a token in that shape reached the
    evidence object despite this CLI's no-token contract (Copilot review of
    openDox-code#26, round 12). Both halves now, in the one place every message
    passes.
    """
    message = _safe_carrier(
        "'https://example.invalid/x.git?token=ghp_supersecret' is not a usable "
        "project id for a directory name")
    assert "ghp_supersecret" not in message, message
    assert "example.invalid" in message, message

    # The DSN half is unchanged, and a message with nothing secret in it is
    # returned as it was.
    assert "hunter2" not in _safe_carrier(
        "could not connect to postgresql://someone:hunter2@127.0.0.1/db")
    plain = "the directory /srv/projects/p1 is not empty"
    assert _safe_carrier(plain) == plain


def _safe_carrier(text: str) -> str:
    return cli._safe_message(RuntimeError(text))


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


def test_a_credential_holding_a_space_is_not_cut_in_half_by_the_dsn_pattern(
) -> None:
    """Two redactions in the wrong order printed half the password.

    `_DSN_SHAPED` ends its match at whitespace, so applied FIRST it cut
    `postgresql://u:secret value@host/db` at the space and left
    `<redacted> value@host/db` — the remainder of the credential beside the
    marker, in the one place this runtime promises there is none. It is the
    same shape round 12 widened the adapter's userinfo class for: a stored
    value may hold a space (Copilot review of openDox-code#26, round 15).

    The general rule matches the whole authority, so it goes first; the DSN
    pattern is the fallback for a DSN with no userinfo at all.
    """
    carried = "could not connect to postgresql://u:secret value@host/db"
    redacted = cli._safe_message(RuntimeError(carried))
    assert "secret" not in redacted, redacted
    assert "value@host" not in redacted, redacted
    assert "<redacted-url>" in redacted
    # And the fallback still covers what the general rule does not.
    plain = cli._safe_message(RuntimeError("postgresql://host:5432/db is down"))
    assert "<redacted>" in plain, plain


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


def test_a_caller_supplied_identifier_is_removed_from_evidence_by_identity(
) -> None:
    """A pattern cannot recognise an identifier, and the store echoes one.

    `_safe_message` knows two shapes, a URL and a libpq conninfo. A project id
    is neither — and `CoordinationStore.repository_for_project` puts the id it
    was given into `NotFoundError`, so `project attach-remote --project-id
    'user:secret@host/path'` printed `secret` through the generic handler
    (Copilot review of openDox-code#26, round 21).

    The repair is not a wider pattern. The CLI KNOWS what it passed, so it
    removes that value by identity before any rule is asked — the same
    technique the push refusal already uses for the destination it knows.
    """
    from opendox.runtime.identity import NotFoundError

    sent = "user:secret@host/path"
    echoed = NotFoundError(
        f"no project_repositories row (project_id={sent!r})")

    # Against the previous head this is what the evidence carried.
    assert "secret" in cli._safe_message(echoed)
    # Given the value, it goes — in the repr form the store used and plain.
    removed = cli._safe_message(echoed, sent)
    assert sent not in removed and "secret" not in removed, removed
    assert "<caller value>" in removed, removed

    # The patterns still run, and a short or empty value is not a wildcard
    # that blanks the message.
    assert "<redacted-url>" in cli._safe_message(
        RuntimeError("could not reach postgresql://u:p@h/db"), "ab")
    assert cli._safe_message(RuntimeError("a plain failure"), None, "", "x") \
        == "a plain failure"


def test_every_repository_verb_hands_the_id_it_was_given_to_the_redactor(
) -> None:
    """One boundary, and it is asserted rather than remembered.

    The three repository verbs are the ones that take a caller-controlled
    identifier and hand it to a store; each of them has two handlers, the named
    refusal and the generic one. All six must pass that identifier, or the one
    that does not is the leak (Copilot review of openDox-code#26, round 21).
    """
    import inspect

    for verb in (cli.cmd_create_repository, cli.cmd_attach_remote,
                 cli.cmd_push):
        source = inspect.getsource(verb)
        handlers = source.count("_safe_message(exc")
        guarded = source.count("_safe_message(exc, args.project_id)")
        assert handlers == guarded, (
            f"{verb.__name__} formats {handlers - guarded} message(s) without "
            "the identifier it was given")
        assert guarded >= 2, (verb.__name__, guarded)


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


def test_no_handler_in_the_cli_emits_an_exception_without_the_redactor() -> None:
    """The redaction contract is asked of the SHAPE, not of five known lines.

    Copilot's round 35 named five `except migrations.MigrationError as exc`
    handlers that formatted `str(exc)` directly — `discover_migrations()` puts
    the configured `OPENDOX_MIGRATIONS_DIR` in its text, so a directory path
    holding a DSN or `password=…` was printed by `init`, `migrate --plan`,
    `migrate` and `status` while the CLI's docstring promised redacted
    evidence. Reading the file for the five would have left the other eight
    this scan found, and would go stale at the next handler somebody adds.

    SO THE TEST ASKS THE PARSE TREE: inside every `except … as exc`, the name
    `exc` may be reached only by `_safe_message(exc)` or `type(exc)` — which
    reads a class name and cannot reach the message. Any other use is a raw
    exception on its way to an operator's terminal.
    """
    import ast

    source = Path(cli.__file__).read_text(encoding="utf-8")
    body = source.splitlines()
    unredacted: list[str] = []
    for handler in [n for n in ast.walk(ast.parse(source))
                    if isinstance(n, ast.ExceptHandler) and n.name]:
        allowed = set()
        for call in [n for n in ast.walk(handler) if isinstance(n, ast.Call)]:
            if (isinstance(call.func, ast.Name)
                    and call.func.id in {"_safe_message", "type"}):
                allowed.update(id(a) for a in call.args
                               if isinstance(a, ast.Name)
                               and a.id == handler.name)
        unredacted += [f"line {n.lineno}: {body[n.lineno - 1].strip()}"
                       for n in ast.walk(handler)
                       if isinstance(n, ast.Name) and n.id == handler.name
                       and id(n) not in allowed]
    assert unredacted == [], (
        "these handlers put an exception's own text into evidence without "
        f"`_safe_message`: {unredacted}")

    # AND THE SCAN IS RUN AGAINST THE SHAPE IT FORBIDS, so a rewrite that
    # quietly stopped finding anything is not mistaken for a clean file: the
    # very same walk over the pre-fix spelling reports it.
    forbidden = ast.parse(
        "try:\n"
        "    pass\n"
        "except ValueError as exc:\n"
        '    _emit({"message": str(exc)})\n')
    found = []
    for handler in [n for n in ast.walk(forbidden)
                    if isinstance(n, ast.ExceptHandler) and n.name]:
        allowed = set()
        for call in [n for n in ast.walk(handler) if isinstance(n, ast.Call)]:
            if (isinstance(call.func, ast.Name)
                    and call.func.id in {"_safe_message", "type"}):
                allowed.update(id(a) for a in call.args
                               if isinstance(a, ast.Name)
                               and a.id == handler.name)
        found += [n for n in ast.walk(handler)
                  if isinstance(n, ast.Name) and n.id == handler.name
                  and id(n) not in allowed]
    assert len(found) == 1


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
