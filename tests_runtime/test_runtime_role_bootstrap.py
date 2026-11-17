"""`deploy/*/init-runtime-role.sh`, RUN against a real PostgreSQL (openDox-code#102).

WHY THIS MODULE EXISTS. The migration-owner guard in that script passed a psql
variable inside `psql -c`. psql 16 hands a `-c` string to the server as it is
written and interpolates `:'owner'` only in what it reads as INPUT (stdin or
`-f`), so the server received a literal colon and answered a syntax error. The
`if !` around the pipeline read the failed query as "no such role", and every
first start on a fresh data volume exited 1 with a refusal that blamed an owner
which existed. `restart: unless-stopped` then started the container again, the
entrypoint skipped initialization on a data directory that was no longer empty,
and PostgreSQL came up healthy WITHOUT the runtime role.

NOTHING IN THE SUITE COULD SEE IT. `test_deploy_shape.py` reads the script as
text (111 cases passed with the bug present), and the `validate` job's
`postgres:16` service container never mounts the script, so no psql ever
interpolated that line.

TWO KINDS OF TEST, and what each can and cannot do:

* THE DB-BACKED CASES RUN THE SCRIPT. They are the faithful regression: the
  script, unmodified, against a real server, then the catalogue asked whether
  the role is there. They need a PostgreSQL (`OPENDOX_TEST_DATABASE_URL`, the
  suite's own) and a `psql`. The `psql` is the one the `local` extra's bundled
  server ships (`pixeltable-pgserver`, PostgreSQL 16, which the `test` extra
  installs, so every `.[test]` install has it), and `PATH`'s `psql` only where
  that one is absent. It is not the container's own `psql`: what these cases
  prove is the script's behaviour under psql 16, which is where the bug lived.
  What they do not do is start the container, so the entrypoint's own
  mechanics (`docker-entrypoint-initdb.d`, the unix-socket temporary server)
  stay unexercised here. Missing pieces skip for a developer and FAIL under
  `CI`, the rule `conftest._skip_or_fail` states, because `validate.yml` pins
  the skipped count exactly and a case that quietly became a skip would move
  it.
* THE HERMETIC CASES READ THE SCRIPT and need no server, so a developer with
  no PostgreSQL still gets the guard against this class: no `psql -c` argument
  holds a psql variable reference, whatever the variable is called.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
#: The two copies the deployments mount. They are byte-identical
#: (`test_deploy_shape.py` holds that), and each is RUN here because each is
#: what one deployment shape actually executes.
SCRIPTS = {
    "compose": ROOT / "deploy" / "compose" / "init-runtime-role.sh",
    "kubernetes-base": ROOT / "deploy" / "kubernetes" / "base"
    / "init-runtime-role.sh",
}

#: A throwaway password for a role that lives for one test, on a server that is
#: reachable only from this job. Never a real credential.
ROLE_PASSWORD = "bootstrap-test-only"  # NOSONAR

#: Bounds the script's two `psql` runs, so a wedged server fails the case in
#: minutes and not at the job's own limit.
SCRIPT_TIMEOUT_SECONDS = 120


def _in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes", "on"}


def _skip_or_fail(reason: str) -> None:
    """A developer's skip is CI's failure (`conftest._skip_or_fail`'s rule)."""
    if _in_ci():
        pytest.fail("CI is set, so the role-bootstrap cases must RUN and not "
                    "skip: " + reason, pytrace=False)
    pytest.skip(reason)


# ---------------------------------------------------------------------------
# the hermetic half: no `psql -c` argument carries a psql variable
# ---------------------------------------------------------------------------

#: A psql variable reference as psql's lexer reads one: `:name`, `:'name'`,
#: `:"name"` and `:{?name}`. A `::` cast is not one, hence the look-behind.
_PSQL_VARIABLE = re.compile(
    r"""(?<!:):(?:'[A-Za-z_]\w*'|"[A-Za-z_]\w*"|\{\?[A-Za-z_]\w*\}|[A-Za-z_]\w*)""")

#: The value of a `psql` command-string option, in the spellings psql takes:
#: `-c X`, a cluster ending in it (`-tAc X`) and `--command=X` or `--command X`.
_COMMAND_STRING = re.compile(
    r"""(?<!\S)(?:-[A-Za-z]*c\s+|-c(?=\S)|--command(?:=|\s+))"""
    r"""("(?:[^"\\]|\\.)*"|'[^']*'|\S+)""")


def _shell_of(script: str) -> str:
    """The script's SHELL half as one string, for reading its `psql` options.

    Comment lines are dropped, because the paragraph that explains the fix
    quotes the shape it removed. The heredoc is dropped, because it is SQL
    handed to a psql that reads it as input, where `:'name'` IS interpolated.
    Backslash-newline continuations are joined, so an option that sits on a
    later line than its `psql` is still in the string.
    """
    shell = script.split("<<'SQL'", 1)[0]
    kept = [line for line in shell.splitlines()
            if not line.lstrip().startswith("#")]
    return "\n".join(kept).replace("\\\n", " ")


def _variables_in_command_strings(script: str) -> list[str]:
    """Every `psql -c` argument in `script` that holds a psql variable."""
    return [argument for argument in _COMMAND_STRING.findall(_shell_of(script))
            if _PSQL_VARIABLE.search(argument)]


#: The guard as it shipped through `v0.1.0`, the three lines #102 replaced.
_THE_FORM_THAT_SHIPPED = """\
if ! psql -tAqX --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \\
      -v owner="$migration_owner" \\
      -c "select 1 from pg_roles where rolname = :'owner'" | grep -q '^1$'; then
  exit 1
fi
"""


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_no_psql_command_string_in_the_bootstrap_holds_a_variable(
        name: str) -> None:
    """psql does not interpolate a `-c` string, so a variable in one is a bug.

    The server gets the text unchanged: `:'owner'` is a syntax error there, and
    `:owner` is the same. A variable belongs in what psql reads as input, which
    is how the guard and the heredoc below it now carry theirs.
    """
    script = SCRIPTS[name].read_text(encoding="utf-8")
    assert _variables_in_command_strings(script) == [], (
        f"{SCRIPTS[name].relative_to(ROOT)} passes a psql variable inside "
        "`psql -c`, which psql hands to the server uninterpolated: it is a "
        "syntax error there, and a guard built on it refuses a first start "
        "for the wrong reason (openDox-code#102). Pipe the query into psql's "
        "stdin instead.")


@pytest.mark.parametrize("script, flagged", [
    pytest.param(_THE_FORM_THAT_SHIPPED, True, id="the-shipped-guard"),
    pytest.param('psql -tAc "select :owner"', True, id="short-cluster"),
    pytest.param("psql --command='select :{?owner}'", True, id="long-option"),
    pytest.param('psql -c "select 1::int" -v owner="$o"', False,
                 id="a-cast-is-not-a-variable"),
    pytest.param('printf \'%s\\n\' "select :\'owner\'" | psql -v owner="$o"',
                 False, id="stdin-is-interpolated"),
])
def test_the_variable_check_sees_the_form_that_shipped(
        script: str, flagged: bool) -> None:
    """A check that cannot fail checks nothing, so it is held to the old text."""
    assert bool(_variables_in_command_strings(script)) is flagged


# ---------------------------------------------------------------------------
# the DB-backed half: the script, run, against a real server
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Bootstrap:
    """One scratch database, one role name, and what the script needs to run."""

    dsn: str
    database: str
    runtime_role: str
    psql_directory: Path | None
    home: Path


def _psql_directory() -> Path | None:
    """The directory holding the `psql` to run: the bundled server's, or none.

    `None` means "whatever `PATH` finds", and `PATH` is checked here so the
    absence is reported once, with its remedy, and not as a subprocess error.
    The bundled one is preferred because it is what `.[test]` pins (PostgreSQL
    16), where a developer's own `psql` can be any version.
    """
    from opendox.runtime import bundle

    try:
        directory = bundle.server_binaries()
    except bundle.BundleRefused:
        directory = None
    if directory is not None and os.access(directory / "psql", os.X_OK):
        return directory
    if shutil.which("psql") is None:
        _skip_or_fail(
            "no `psql` is available: the `local` extra's bundled server ships "
            "one (pip install -e '.[runtime,test]'), and none is on PATH")
    return None


@pytest.fixture
def bootstrap(postgres_dsn: str, tmp_path: Path) -> Iterator[Bootstrap]:
    """A scratch DATABASE for the script to initialize, dropped afterwards.

    A database and not a schema, because the script's `grant connect on
    database` and its default privileges are per-database, and a database is
    what a fresh volume is. The ROLE is cluster-wide, so its name is unique to
    the case and it is dropped with the database. Depending on `postgres_dsn`
    is what makes an absent server skip for a developer and fail under `CI`.
    """
    if shutil.which("sh") is None:
        _skip_or_fail("no `sh` is available to run the bootstrap script")
    psql_directory = _psql_directory()

    import psycopg
    from psycopg import sql

    token = uuid.uuid4().hex[:12]
    scratch = Bootstrap(dsn=postgres_dsn, database=f"t_boot_{token}",
                        runtime_role=f"t_rt_{token}",
                        psql_directory=psql_directory, home=tmp_path)
    with psycopg.connect(postgres_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(
            sql.Identifier(scratch.database)))
    try:
        yield scratch
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("drop database if exists {} with (force)")
                          .format(sql.Identifier(scratch.database)))
            admin.execute(sql.SQL("drop role if exists {}").format(
                sql.Identifier(scratch.runtime_role)))


def _run_script(scratch: Bootstrap, script: Path,
                **overrides: str) -> subprocess.CompletedProcess[str]:
    """Run the script as the image's entrypoint would, against `scratch`.

    The environment is BUILT, not inherited: a `PG*` variable or an
    `OPENDOX_*` setting on the runner would otherwise steer the script's psql
    somewhere this case did not choose. `HOME` is the case's own directory, so
    no `~/.psqlrc` of a developer's is read by the script's second psql, which
    does not pass `-X`. The connection comes from the suite's own DSN, and its
    password travels in `PGPASSWORD`, never in an argument.
    """
    from psycopg.conninfo import conninfo_to_dict

    target = conninfo_to_dict(scratch.dsn)
    path = os.environ.get("PATH", os.defpath)
    if scratch.psql_directory is not None:
        path = os.pathsep.join([str(scratch.psql_directory), path])
    env = {
        "PATH": path,
        "HOME": str(scratch.home),
        "PGCONNECT_TIMEOUT": "10",
        "POSTGRES_USER": str(target.get("user") or ""),
        "POSTGRES_DB": scratch.database,
        "OPENDOX_RUNTIME_PG_USER": scratch.runtime_role,
        "OPENDOX_RUNTIME_PG_PASSWORD": ROLE_PASSWORD,
        # EMPTY, as the compose file passes it (`${OPENDOX_MIGRATION_PG_USER:-}`):
        # the script's own default, `$POSTGRES_USER`, is what must apply.
        "OPENDOX_MIGRATION_PG_USER": "",
    }
    for setting, key in (("PGHOST", "host"), ("PGPORT", "port"),
                         ("PGPASSWORD", "password")):
        if target.get(key):
            env[setting] = str(target[key])
    env.update(overrides)
    return subprocess.run(["sh", str(script)], env=env, capture_output=True,
                          text=True, timeout=SCRIPT_TIMEOUT_SECONDS,
                          check=False)


def _role_row(scratch: Bootstrap, role: str) -> tuple[object, ...] | None:
    import psycopg

    with psycopg.connect(scratch.dsn, autocommit=True) as conn:
        return conn.execute(
            "select rolcanlogin, rolsuper from pg_roles where rolname = %s",
            (role,)).fetchone()


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_the_first_start_creates_the_runtime_role(
        bootstrap: Bootstrap, name: str) -> None:
    """The script completes on a fresh database and the role is THERE.

    This is #102's reproduction as a case: before the fix the script exited 1
    here, with a syntax error and a refusal naming an owner that existed, and
    the role was never created. What is asked afterwards is the catalogue's
    answer, not the exit code alone: a role that can log in and is not a
    superuser, CONNECT on the database, USAGE on the schema, and the default
    privileges that make every table the migration owner creates later
    readable and writable by it.
    """
    import psycopg

    result = _run_script(bootstrap, SCRIPTS[name])
    assert result.returncode == 0, (
        f"{name}'s init-runtime-role.sh exited {result.returncode} on a fresh "
        f"database. stderr:\n{result.stderr}")

    assert _role_row(bootstrap, bootstrap.runtime_role) == (True, False), (
        "the runtime role is missing, cannot log in, or is a superuser")

    with psycopg.connect(bootstrap.dsn, dbname=bootstrap.database,
                         autocommit=True) as conn:
        connect, usage = conn.execute(
            "select has_database_privilege(%(r)s, current_database(), "
            "'CONNECT'), has_schema_privilege(%(r)s, 'public', 'USAGE')",
            {"r": bootstrap.runtime_role}).fetchone()
        assert connect, "the runtime role was not granted CONNECT"
        assert usage, "the runtime role was not granted USAGE on the schema"

        granted = {row[0] for row in conn.execute(
            "select a.privilege_type "
            "  from pg_default_acl d "
            "  join pg_namespace n on n.oid = d.defaclnamespace "
            "  join pg_roles ro on ro.oid = d.defaclrole "
            "  cross join lateral aclexplode(d.defaclacl) a "
            " where d.defaclobjtype = 'r' and n.nspname = 'public' "
            "   and ro.rolname = current_user "
            "   and a.grantee = (select oid from pg_roles where rolname = %s)",
            (bootstrap.runtime_role,))}
        assert granted == {"SELECT", "INSERT", "UPDATE", "DELETE"}, (
            "the migration owner's default privileges for the runtime role "
            f"are {sorted(granted)}")


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_a_migration_owner_the_database_lacks_is_refused_by_name(
        bootstrap: Bootstrap, name: str) -> None:
    """The guard's refusal still fires, and now for the reason it states.

    An alternate migration owner is provisioned externally; one nobody created
    must stop the first start BEFORE the runtime role exists, with the message
    that names `OPENDOX_MIGRATION_PG_USER`. The old guard produced that same
    message for EVERY owner, behind a PostgreSQL syntax error, so the refusal
    is asserted to arrive without one.
    """
    missing = f"t_noowner_{uuid.uuid4().hex[:12]}"
    result = _run_script(bootstrap, SCRIPTS[name],
                         OPENDOX_MIGRATION_PG_USER=missing)

    assert result.returncode == 1, (
        f"expected the refusal's exit 1, got {result.returncode}. stderr:\n"
        f"{result.stderr}")
    assert (f"OPENDOX_MIGRATION_PG_USER names '{missing}', which this "
            "database does not have") in result.stderr
    assert "syntax error" not in result.stderr, (
        "the guard's query reached the server uninterpolated, so the refusal "
        "is PostgreSQL's failure read as 'no such role' (openDox-code#102)")
    assert _role_row(bootstrap, bootstrap.runtime_role) is None, (
        "the refusal must come before the runtime role is created")
