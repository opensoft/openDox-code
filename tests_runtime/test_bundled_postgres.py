"""The LOCAL install's bundled PostgreSQL server (plan 034 T072; #1144 13.1, as
T007 batch H's addendum reads; RULED R1Q16 (i)-(iv), `5850003126`).

T072's falsifier is F13.1's TCP-listener block, which reads the kernel's
socket table at run time, and its `runtime status` block. Both are run here
against a server the REAL entry point started: `python -m opendox.cli
generate-and-open --local` over a fresh repository copied from T050's
`tests/fixtures/plain-documents`, launched in the background as F13.1 launches
it, reached over HTTP, asked about by a second process, and stopped with a
signal. Nothing is stood in: the corpus root check, the generation, the
validator and the serve loop are phase 2's own, landed on this stack's base
(T054 to T058), so the stand-in driver this module once launched is gone. Where F13.1 reads the
server's pid from `caps.json`, these cases read the same pid from
`runtime status`'s `database_bundle`. `/capabilities`' `install` block is
T073's, and nothing here pretends it exists.

R1Q16, each part asserted:
  (i)   the server is a CHILD of the entry point's process (its `PPid`);
  (ii)  it is started AND migrated, the ledger holding every migration;
  (iii) the `local` extra carries it, and the `test` extra joins the extra;
  (iv)  it stops with the entry point: on SIGTERM, which the serve loop reads
        as Ctrl-C, and — the backstop — on SIGKILL, through the parent-death
        signal.

And the migrations gap the holder assigned to T072: a WHEEL install, run from
a directory that is not a checkout, migrates its bundled server from the copy
the wheel carries.

NOT SKIPPED IN CI. These cases need the `local` extra's server, which the
`test` extra installs; under `CI` its absence is a FAILURE, as a missing
`postgres:16` service is for the DB-backed suites (`conftest._skip_or_fail`'s
rule, restated below), because `validate.yml` pins the skip count exactly.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

import pytest

from opendox.runtime import bundle as bundle_mod
from opendox.runtime import config
from opendox.runtime.config import PREFIX

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
#: T050's fixture, which F13.1's preamble copies into a fresh repository.
PLAIN_DOCUMENTS = ROOT / "tests" / "fixtures" / "plain-documents"
MODE = PREFIX + "INSTALL_MODE"
STATE = PREFIX + "STATE_DIR"


def _in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(scope="module", autouse=True)
def _the_server_is_installed() -> None:
    """The `local` extra's binaries, or this module's refusal to pass silently."""
    try:
        bundle_mod.server_binaries()
    except bundle_mod.BundleRefused as exc:
        if _in_ci():
            pytest.fail(f"CI is set, so the bundled-server suite must RUN: {exc}",
                        pytrace=False)
        pytest.skip(str(exc))
    if hasattr(os, "geteuid") and os.geteuid() == 0:   # pragma: no cover
        pytest.fail("the bundled server refuses root; run the suite as a user")


@pytest.fixture()
def state_dir():
    """A state directory nothing else has touched, with a SHORT path.

    Short because the socket's whole path is bounded by the kernel, and
    pytest's own `tmp_path` grows with the test's name. Removed afterwards,
    once any server on it has been checked stopped.
    """
    base = "/tmp" if os.path.isdir("/tmp") else None
    path = Path(tempfile.mkdtemp(prefix="odx-", dir=base))
    yield path
    pid = bundle_mod.running_pid(config.DatabaseBundle(path))
    if pid is not None:                                  # pragma: no cover
        os.kill(pid, signal.SIGKILL)
    shutil.rmtree(path, ignore_errors=True)


def _clean_env(**extra: str) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items()
           if name not in config.SETTING_NAMES and not name.startswith("PG")}
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env.update(extra)
    return env


def _parent_of(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("PPid:"):
            return int(line.split()[1])
    raise AssertionError(f"no PPid for {pid}")         # pragma: no cover


def _tcp_listeners(pid: int) -> list[tuple[str, str]]:
    """F13.1's TCP-listener block, verbatim in substance: every socket the
    process holds, looked up in the KERNEL's TCP tables, never self-report."""
    inodes = set()
    for fd in os.listdir(f"/proc/{pid}/fd"):
        try:
            m = re.match(r"socket:\[(\d+)\]", os.readlink(f"/proc/{pid}/fd/{fd}"))
        except OSError:
            continue
        if m:
            inodes.add(m.group(1))
    return [(tbl, row.split()[1]) for tbl in ("/proc/net/tcp", "/proc/net/tcp6")
            for row in open(tbl).read().splitlines()[1:]
            if row.split()[3] == "0A" and row.split()[9] in inodes]


def _wait_gone(pid: int, seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        # a zombie is gone as a server: reaped by init once its parent is
        try:
            if "State:\tZ" in Path(f"/proc/{pid}/status").read_text():
                return True
        except OSError:
            return True
        time.sleep(0.1)
    return False


def _first_url(child: subprocess.Popen, seconds: float) -> str | None:
    """The first `http://` line `child` prints within `seconds`, or `None`.

    BOUNDED BY THE DEADLINE, not by the child: a blocking `readline()` waits
    for as long as a child that is alive and silent stays so, which is exactly
    the startup failure this has to diagnose (Copilot review of
    openDox-code#69). So the pipe is polled with a selector, only up to the
    time left, and read in whatever pieces arrive.
    """
    deadline = time.monotonic() + seconds
    pending = b""
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        while (remaining := deadline - time.monotonic()) > 0:
            if not selector.select(timeout=remaining):
                return None                                  # the deadline
            chunk = os.read(child.stdout.fileno(), 65536)
            if not chunk:
                return None                                  # the child closed it
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for line in lines:
                if line.startswith(b"http://"):
                    return line.strip().decode()
    return None


def _launch(corpus: Path, state: Path, run_dir: Path,
            **extra: str) -> tuple[subprocess.Popen, str]:
    """`generate-and-open --local` in the BACKGROUND, and the URL it serves."""
    child = subprocess.Popen(
        [sys.executable, "-m", "opendox.cli", "generate-and-open",
         config.LOCAL_FLAG, "--repo-root", str(corpus), "--repository",
         "fixture", "--run-dir", str(run_dir), "--no-open", "--port", "0"],
        env=_clean_env(**{STATE: str(state)}, **extra), cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    url = _first_url(child, 90)
    if url is None:
        child.kill()
        _out, err = child.communicate(timeout=30)
        raise AssertionError(
            f"the entry point never served: {err.decode(errors='replace')[-2000:]}")
    return child, url


def test_the_launch_helper_is_bounded_by_its_deadline_not_by_the_child() -> None:
    """A child that is alive and silent does not hold the helper past its
    deadline; one that prints the URL is read, however the pieces arrive."""
    silent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                              stdout=subprocess.PIPE)
    try:
        began = time.monotonic()
        assert _first_url(silent, 1.0) is None
        assert time.monotonic() - began < 10
    finally:
        silent.kill()
        silent.communicate(timeout=10)
    talker = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; sys.stdout.write('  serving '); "
         "sys.stdout.flush(); time.sleep(0.2); print('x'); "
         "print('http://127.0.0.1:1/index.html', flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE)
    try:
        assert _first_url(talker, 30) == "http://127.0.0.1:1/index.html"
    finally:
        talker.kill()
        talker.communicate(timeout=10)


def _status(state: Path, **extra: str) -> tuple[int, dict]:
    """`OPENDOX_INSTALL_MODE=local opendox-runtime runtime status`, a SECOND process."""
    done = subprocess.run(
        [sys.executable, "-m", "opendox.runtime.cli", "runtime", "status",
         "--probe-timeout", "10"],
        env=_clean_env(**{MODE: "local", STATE: str(state)}, **extra), cwd=ROOT,
        capture_output=True, text=True, timeout=60)
    return done.returncode, json.loads(done.stdout)


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """F13.1's preamble: T050's `plain-documents` copied into a FRESH git
    repository, committed under the fixture's own identity and none of the
    user's git configuration."""
    root = tmp_path / PLAIN_DOCUMENTS.name
    shutil.copytree(PLAIN_DOCUMENTS, root)
    env = {name: value for name, value in os.environ.items()
           if not name.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})
    for argv in (["git", "-c", "init.defaultBranch=main", "init", "-q"],
                 ["git", "add", "-A"], ["git", "commit", "-qm", "fixture"]):
        subprocess.run(argv, cwd=root, env=env, check=True, capture_output=True)
    return root


# -- (iii): the packaging ----------------------------------------------------


def test_the_local_extra_carries_the_runtime_and_the_server_and_test_joins_it(
) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = project["project"]["optional-dependencies"]
    assert "opendox[runtime]" in extras["local"]
    # the carrier RULED on openxFactory#656 `5916000030` item 2
    assert any(req.startswith("pixeltable-pgserver") for req in extras["local"])
    assert not any(req.startswith("pgserver") for req in extras["local"])
    assert "opendox[local]" in extras["test"], (
        "F9.1 installs `.[test]` alone; without the local extra there, this "
        "suite could not start the server it tests")
    lock = (ROOT / "constraints-cpython312-linux.txt").read_text()
    assert re.search(r"(?m)^pixeltable-pgserver==", lock), \
        "the lock does not pin pixeltable-pgserver"
    assert not re.search(r"(?m)^pgserver==", lock), "the lock still pins pgserver"
    files = project["tool"]["setuptools"]["data-files"]
    assert files == {"share/opendox/migrations": ["migrations/*.sql"]}
    # and the packaging notes name functions that exist (Copilot review of #69)
    for name in re.findall(r"opendox\.runtime\.config\.(\w+)",
                           (ROOT / "pyproject.toml").read_text()):
        assert hasattr(config, name), (
            f"pyproject.toml points readers at config.{name}, which does not exist")


# -- the layout, before anything starts ----------------------------------------


def test_the_two_dsns_are_two_users_over_the_one_socket(state_dir: Path) -> None:
    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    bundle = config.database_bundle(state_dir)
    assert settings.database_url == bundle.served_dsn
    assert settings.migration_database_url == bundle.migration_dsn
    assert settings.database_url != settings.migration_database_url      # 13.3
    for dsn in (settings.database_url, settings.migration_database_url):
        assert dsn.startswith("postgresql://")                           # 13.2
        assert f"host={bundle.socket_dir}" in dsn and "port=5432" in dsn
    assert config.user_named_by(settings.database_url) == config.BUNDLE_SERVED_ROLE
    assert config.user_named_by(settings.migration_database_url) == \
        config.BUNDLE_OWNER_ROLE
    assert bundle.data_dir.parent == bundle.socket_dir.parent
    assert bundle.data_dir.is_relative_to(state_dir)
    assert bundle.socket_dir.is_relative_to(state_dir)


def test_a_state_dir_too_long_for_a_unix_socket_is_refused_naming_it() -> None:
    long = "/tmp/" + "x" * 120
    with pytest.raises(config.ConfigurationError) as caught:
        config.load_settings({MODE: "local", STATE: long})
    assert STATE in str(caught.value) and "socket" in str(caught.value)


def test_a_relative_state_dir_is_refused_naming_it() -> None:
    with pytest.raises(config.ConfigurationError) as caught:
        config.load_settings({MODE: "local", STATE: "var/state"})
    assert STATE in str(caught.value)


def test_the_default_state_dir_is_the_users_own(monkeypatch) -> None:
    home = config.state_dir({"HOME": "/ignored"})
    assert home.name == "opendox" and home.is_absolute()
    assert config.state_dir({"XDG_STATE_HOME": "/srv/state"}) == \
        Path("/srv/state/opendox")
    # the XDG rule: a relative value is ignored, never joined onto the cwd
    assert config.state_dir({"XDG_STATE_HOME": "relative"}) == \
        Path.home() / ".local" / "state" / "opendox"


# -- 13.1 and R1Q16 (i), (ii), (iv): F13.1's two blocks, on the real entry point


def test_the_entry_point_owns_a_migrated_server_with_no_tcp_listener(
        corpus: Path, state_dir: Path, tmp_path: Path) -> None:
    """F13.1's `runtime status` block and its TCP-listener block, against the
    server `generate-and-open --local` started in the background; then
    `kill "$SERVER"; wait`, and the server is gone with it."""
    server, url = _launch(corpus, state_dir, tmp_path / "run")
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:       # ready
            assert answer.status == 200
        # -- F13.1's `runtime status` block --------------------------------
        code, status = _status(state_dir)
        assert status.get("database") == "reachable", \
            f"no bundled database answered: {status}"
        assert status.get("applied_migrations") and \
            not status.get("pending_migrations"), f"not migrated: {status}"
        state = os.path.realpath(state_dir)
        bundle = status.get("database_bundle") or {}
        for key in ("data_dir", "socket_dir"):
            got = os.path.realpath(bundle.get(key, ""))
            assert got.startswith(state + os.sep), \
                f"{key} {got!r} is not under the install's state dir {state!r}"
        # a local install has no broker, and that is not a fault (T070)
        assert status["broker_keys"] == "not configured (local mode)"
        assert code == 0 and status["ok"] is True, status
        # -- F13.1's TCP-listener block, the pid from `database_bundle` -----
        pid = bundle.get("pid")
        assert isinstance(pid, int), f"the bundle reports no server pid: {pid!r}"
        assert not _tcp_listeners(pid), \
            f"the bundled server listens on TCP: {_tcp_listeners(pid)}"
        # -- R1Q16 (i): the server is the document server's own child ------
        assert _parent_of(pid) == server.pid, (
            "the bundled server is not a child of the process serving the "
            "document surface")
        mode = os.stat(bundle["socket_dir"]).st_mode & 0o777
        assert mode == 0o700, f"the socket directory is {mode:o}"
    finally:
        server.send_signal(signal.SIGTERM)                # `kill "$SERVER"`
        server.communicate(timeout=60)                    # `wait "$SERVER"`
    # -- R1Q16 (iv): it stopped with the entry point, and cleanly ----------
    assert server.returncode == 0, server.returncode
    assert _wait_gone(pid), "the bundled server outlived its entry point"
    assert config.DatabaseBundle(state_dir).data_dir.joinpath("PG_VERSION").is_file(), \
        "the data directory must survive a stop: it is the install's database"


#: libpq defaults that, READ, would move the bundle's connections: to an
#: unroutable TCP address (TEST-NET-1, RFC 5737), through a service that does
#: not exist, and into a schema that does not either.
HOSTILE_LIBPQ = {"PGHOSTADDR": "192.0.2.1", "PGSERVICE": "no-such-service-odx",
                 "PGOPTIONS": "-c search_path=nowhere"}


def test_libpq_defaults_in_the_environment_never_reach_the_bundle(
        corpus: Path, state_dir: Path, tmp_path: Path) -> None:
    """`PGHOSTADDR` outranks a DSN's socket `host`, `PGSERVICE` fills
    parameters from a service file, and `PGOPTIONS` sets the session's
    parameters. With all three set, the entry point still starts, migrates
    and serves ITS OWN server, and `runtime status` in a second process still
    finds it (Copilot review of openDox-code#69)."""
    server, url = _launch(corpus, state_dir, tmp_path / "run", **HOSTILE_LIBPQ)
    try:
        code, status = _status(state_dir, **HOSTILE_LIBPQ)
        assert status.get("database") == "reachable", status
        assert status.get("applied_migrations") and \
            not status.get("pending_migrations"), status
        assert code == 0 and status["ok"] is True, status
    finally:
        server.send_signal(signal.SIGTERM)
        server.communicate(timeout=60)
    assert server.returncode == 0, server.returncode


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="PR_SET_PDEATHSIG is Linux's")
def test_the_server_stops_even_when_the_entry_point_is_killed_outright(
        corpus: Path, state_dir: Path, tmp_path: Path) -> None:
    """(iv)'s backstop: SIGKILL gives the entry point no chance to stop
    anything, and the parent-death signal stops the server all the same."""
    server, _url = _launch(corpus, state_dir, tmp_path / "run")
    pid = bundle_mod.running_pid(config.DatabaseBundle(state_dir))
    assert isinstance(pid, int)
    server.kill()
    server.communicate(timeout=30)
    assert _wait_gone(pid), "the bundled server outlived a SIGKILLed entry point"


def test_a_second_entry_point_on_the_same_state_dir_is_refused(
        state_dir: Path) -> None:
    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    first = bundle_mod.BundledServer(settings).start()
    try:
        with pytest.raises(bundle_mod.BundleRefused) as caught:
            bundle_mod.BundledServer(settings).start()
        assert str(first.report()["pid"]) in str(caught.value)
        # and a restart of the one that owns it re-migrates nothing
        assert first.applied == ["0001", "0002"]
    finally:
        first.stop()
    again = bundle_mod.BundledServer(settings).start()
    try:
        assert again.applied == []
    finally:
        again.stop()


@pytest.mark.skipif(not Path("/proc/self").exists(), reason="asks /proc")
def test_a_stale_lock_naming_a_recycled_pid_does_not_hold_the_bundle(
        state_dir: Path) -> None:
    """A server that did not stop cleanly leaves its `postmaster.pid`, and the
    kernel gives its pid to something else, here a process with `postgres` in
    its argv. `status` does not report that process, and the next start
    starts, with the proven-stale lock removed (Copilot review of
    openDox-code#69)."""
    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    bundle_mod.BundledServer(settings).start().stop()          # a real cluster
    bundle = config.DatabaseBundle(state_dir)
    decoy = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)", "postgres"],
        cwd=bundle.data_dir, stdout=subprocess.DEVNULL)
    try:
        (bundle.data_dir / "postmaster.pid").write_text(
            f"{decoy.pid}\n{bundle.data_dir}\n", encoding="utf-8")
        assert bundle_mod.report(bundle)["pid"] is None
        server = bundle_mod.BundledServer(settings).start()
        try:
            assert bundle_mod.running_pid(bundle) == server.report()["pid"]
        finally:
            server.stop()
    finally:
        decoy.kill()
        decoy.wait(timeout=10)


def test_readiness_is_this_childs_server_not_a_winners_socket(
        state_dir: Path) -> None:
    """Two entry points racing from an idle state both launch. The loser's
    `postgres` lives a moment before it refuses the winner's lock, while the
    winner's socket already answers. The loser must wait for ITS child, and
    be refused when that child exits, not connect to the winner and carry on
    as if it owned a database (Copilot review of openDox-code#69). The
    loser's child is stood in by a process that lives three seconds."""
    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    with bundle_mod.BundledServer(settings):
        loser = bundle_mod.BundledServer(settings)
        loser.process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(3)"])
        began = time.monotonic()
        try:
            with pytest.raises(bundle_mod.BundleRefused) as caught:
                loser._wait_until_ready()
        finally:
            loser.process.kill()
            loser.process.wait(timeout=10)
    assert "exited during start" in str(caught.value), caught.value
    assert time.monotonic() - began < bundle_mod.START_TIMEOUT_SECONDS


# -- peer authentication (RULED openxFactory#656 `5916000030` item 3) ----------


def _owner(server) -> "object":
    import psycopg

    return psycopg.connect(server.bundle.migration_dsn, autocommit=True)


def test_the_bundle_authenticates_by_peer_through_the_one_map(
        state_dir: Path) -> None:
    """The server's OWN reading of its two files, from `pg_hba_file_rules`
    and `pg_ident_file_mappings`, and the method each connection really
    used, from `system_user`. There is one local rule, peer through the
    `opendox` map. Host is rejected. There is no `trust` anywhere. The map
    admits this OS user as the two roles and names no other OS user."""
    user = bundle_mod.os_user()
    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    with bundle_mod.BundledServer(settings) as server:
        with _owner(server) as conn:
            rules = conn.execute(
                "select type, database, user_name, auth_method, options, error "
                "from pg_hba_file_rules order by rule_number").fetchall()
            mappings = conn.execute(
                "select map_name, sys_name, pg_username, error "
                "from pg_ident_file_mappings order by map_number").fetchall()
        for dsn, role in ((server.bundle.migration_dsn, config.BUNDLE_OWNER_ROLE),
                          (server.bundle.served_dsn, config.BUNDLE_SERVED_ROLE)):
            import psycopg

            with psycopg.connect(dsn) as conn:
                assert conn.execute("select current_user, system_user").fetchone() \
                    == (role, f"peer:{user}")
    assert rules == [
        ("local", ["all"], ["all"], "peer", [f"map={bundle_mod.IDENT_MAP}"], None),
        ("host", ["all"], ["all"], "reject", None, None),
        ("host", ["all"], ["all"], "reject", None, None)], rules
    assert mappings == [
        (bundle_mod.IDENT_MAP, user, config.BUNDLE_OWNER_ROLE, None),
        (bundle_mod.IDENT_MAP, user, config.BUNDLE_SERVED_ROLE, None)], mappings


def test_a_role_outside_the_map_is_refused_even_for_this_os_user(
        state_dir: Path) -> None:
    """The MAP decides, not the socket. The same OS user, over the same
    0700 socket, asking for a role the map does not name, is refused by
    peer authentication. A suite that does not run as root cannot connect
    as a second OS user. What stands for that case is the map itself, read
    back above, which names this user and no other."""
    import psycopg
    from psycopg import sql

    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    with bundle_mod.BundledServer(settings) as server:
        with _owner(server) as conn:
            conn.execute(sql.SQL("create role {} login").format(
                sql.Identifier("odx_stranger")))
        with pytest.raises(psycopg.OperationalError) as caught:
            psycopg.connect(server.bundle.dsn("odx_stranger")).close()
    assert "peer authentication failed" in str(caught.value).lower(), caught.value


def test_an_older_trust_cluster_is_brought_back_to_peer_on_start(
        state_dir: Path) -> None:
    """A data directory an earlier build initialized with `trust` (or a file
    edited by hand) is put back to the one configuration before the next
    launch, so it never serves as trust."""
    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    bundle_mod.BundledServer(settings).start().stop()
    data = config.DatabaseBundle(state_dir).data_dir
    (data / "pg_hba.conf").write_text("local all all trust\n", encoding="utf-8")
    (data / "pg_ident.conf").write_text("", encoding="utf-8")
    with bundle_mod.BundledServer(settings) as server:
        import psycopg

        with psycopg.connect(server.bundle.served_dsn) as conn:
            method = conn.execute("select system_user").fetchone()[0]
    expected = bundle_mod.authentication_files(bundle_mod.os_user())
    for name, content in expected.items():
        assert (data / name).read_text(encoding="utf-8") == content, name
        assert stat.S_IMODE((data / name).stat().st_mode) == 0o600, name
    assert method == f"peer:{bundle_mod.os_user()}", method


def test_migrate_under_the_local_mode_uses_the_bundle_and_refuses_a_dsn(
        state_dir: Path) -> None:
    """`runtime migrate` is part of the same install: it reads the bundle's
    owner DSN, and an operator's migration DSN beside `local` is refused."""
    settings = config.load_settings({MODE: "local", STATE: str(state_dir)})
    with bundle_mod.BundledServer(settings):
        done = subprocess.run(
            [sys.executable, "-m", "opendox.runtime.cli", "runtime", "migrate"],
            env=_clean_env(**{MODE: "local", STATE: str(state_dir)}), cwd=ROOT,
            capture_output=True, text=True, timeout=60)
        evidence = json.loads(done.stdout)
        assert done.returncode == 0 and evidence["applied"] == [], evidence
        done = subprocess.run(
            [sys.executable, "-m", "opendox.runtime.cli", "runtime", "migrate"],
            env=_clean_env(**{MODE: "local", STATE: str(state_dir),
                              PREFIX + "MIGRATION_DATABASE_URL":
                                  "postgresql://m:hunter2@db.invalid/x"}),
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        evidence = json.loads(done.stdout)
        assert evidence["refusal"] == "configuration", evidence
        assert PREFIX + "MIGRATION_DATABASE_URL" in evidence["message"]
        assert "hunter2" not in done.stdout


# -- the migrations gap: a wheel, outside any checkout --------------------------


def test_a_wheel_install_migrates_its_bundled_server_outside_a_checkout(
        state_dir: Path, tmp_path: Path) -> None:
    """Build this package's wheel, install it OUTSIDE the checkout, run it from
    a directory with no `migrations/`, and migrate the bundled server from the
    copy the wheel carries (the holder's assignment to T072)."""
    source = tmp_path / "source"
    source.mkdir()
    for name in ("pyproject.toml", "src", "migrations"):
        item = ROOT / name
        (shutil.copytree if item.is_dir() else shutil.copy2)(
            item, source / name, **({"ignore": shutil.ignore_patterns(
                "__pycache__", "*.egg-info")} if item.is_dir() else {}))
    wheels = tmp_path / "wheels"
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-index",
         "--no-build-isolation", "-q", "-w", str(wheels), str(source)],
        capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stderr[-3000:]
    (wheel,) = wheels.glob("opendox-*.whl")
    prefix = tmp_path / "prefix"
    # `--ignore-installed` IS LOAD-BEARING: without it pip treats the suite's
    # own (editable) `opendox` as the installed copy of the same project and
    # UNINSTALLS it before writing the new one under `--prefix` — measured, it
    # emptied the environment this very suite runs in.
    installed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
         "--ignore-installed", "-q", "--prefix", str(prefix), str(wheel)],
        capture_output=True, text=True, timeout=300)
    assert installed.returncode == 0, installed.stderr[-3000:]
    assert "uninstall" not in (installed.stdout + installed.stderr).lower()
    # ...and the environment this suite runs in still has its own install
    still = subprocess.run(
        [sys.executable, "-c", "import importlib.metadata as m; "
         "print(m.distribution('opendox').version)"],
        env=_clean_env(PYTHONPATH=""), capture_output=True, text=True, timeout=60)
    assert still.returncode == 0, "installing the wheel removed the suite's opendox"
    site = Path(sysconfig.get_path("purelib", vars={"base": str(prefix),
                                                     "platbase": str(prefix)}))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    program = f"""
import json, sys
from pathlib import Path
import opendox
from opendox.runtime import bundle, config
prefix = Path({str(prefix)!r}).resolve()
assert Path(opendox.__file__).resolve().is_relative_to(prefix), opendox.__file__
assert not Path("migrations").exists()
settings = config.load_settings()
found = Path(settings.migrations_dir).resolve()
assert found.is_relative_to(prefix / "share" / "opendox"), found
with bundle.BundledServer(settings) as server:
    print(json.dumps({{"applied": server.applied, "dir": str(found)}}))
"""
    env = _clean_env(**{MODE: "local", STATE: str(state_dir)})
    env["PYTHONPATH"] = str(site)
    done = subprocess.run([sys.executable, "-c", program], cwd=elsewhere,
                          env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-3000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["applied"] == ["0001", "0002"], result
