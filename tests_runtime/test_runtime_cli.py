"""The ONE lifecycle CLI: its verb set, its seam conformance, its refusals.

HERMETIC: standard library plus the package's stdlib-only modules and
`subcommand_extension`, which is itself stdlib-only by its own declaration.
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
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
