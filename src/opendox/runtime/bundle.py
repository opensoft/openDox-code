"""A LOCAL install's bundled PostgreSQL server (plan 034 T072; #1144 13.1).

WHAT #1144 FIXES AND WHAT IT LEAVES. 13.1 fixes the server's IDENTITY: its data
directory and its Unix socket live under the install's own `OPENDOX_STATE_DIR`,
it listens on that socket and on NO TCP port, the product supplies BOTH DSNs
itself, and `runtime status` reports a `database_bundle` naming `data_dir`,
`socket_dir` and the server's `pid`. It leaves the PACKAGING to the realization,
and R1Q16's answer (openxFactory#656 `5850003126`, as T007 batch H's 13.1
addendum records it) names it:

  (i)   the document server starts the bundled server as ITS OWN CHILD and
        reports it, so the process a user reaches is the one that owns it;
  (ii)  starting and migrating the store is all release 1 asks of it, since
        the document surface reads nothing from it yet;
  (iii) it ships as the `opendox[local]` extra, which carries the runtime's
        packages and the server's own;
  (iv)  it stops with the entry point.

THE SERVER'S OWN PACKAGE IS `pgserver` (pyproject.toml's `local` extra), and
only its BINARIES are used: `initdb` and `postgres` from the wheel's
`pginstall/bin`, found by `importlib.util.find_spec` without importing
`pgserver` at all. Its Python manager is deliberately not used — it daemonizes
the server through `pg_ctl`, which re-parents it away from this process
(against (i)), shares one server between processes by reference count and
stops it from `atexit` (which a SIGTERM never runs, against (iv)), and may put
the socket under the user's runtime directory instead of the state directory
(against 13.1). The binaries themselves link only libc and libz, so they run on
any manylinux2014 host, which a wheel that links the system's ICU does not.

THE LIFECYCLE, IN FULL:

  * `initdb` once per data directory, into an attempt directory that is
    renamed into place only when it has succeeded, so an interrupted first
    start never leaves a half-built cluster: the MIGRATION identity
    (`config.BUNDLE_OWNER_ROLE`) is the bootstrap superuser, local connections
    are `trust` and host connections are `reject`, UTF-8 in the `C` locale.
    Trust is safe BECAUSE of the socket: its directory is 0700, owned by the
    user running the install, and the server opens no TCP port at all, so
    reaching the socket is the credential and nothing else can.
  * `postgres` started as a DIRECT CHILD of this process (`subprocess.Popen`,
    never `pg_ctl`), with `listen_addresses` empty and the socket directory
    given. On Linux it also carries `PR_SET_PDEATHSIG`, so an entry point
    killed without any chance to clean up (SIGKILL) still takes its server
    with it; an ordinary stop is `stop()`, a fast shutdown.
  * a bootstrap, idempotent: the database, the SERVED role with no password
    and the grants `deploy/compose/init-runtime-role.sh` makes for the compose
    stack's role of the same name, narrowed to what this install's owner
    creates.
  * the ordered-SQL migrations, through `migrations.MigrationRunner`, as the
    owner, with the served role and the database declared, so the run narrows
    the ledger and verifies the served role's access exactly as a hosted
    `runtime migrate` does.

IMPORT WEIGHT: standard library and `opendox.runtime.{config,migrations}` at
module level. `psycopg` and `opendox.runtime.db` are imported at CALL time,
inside the functions that connect, like every other module the
`tests_runtime/test_runtime_surface.py` contract names.
"""

from __future__ import annotations

import contextlib
import ctypes
import importlib.util
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from opendox.runtime import migrations
from opendox.runtime.config import (
    BUNDLE_DATABASE,
    BUNDLE_OWNER_ROLE,
    BUNDLE_PORT,
    BUNDLE_SERVED_ROLE,
    LOCAL_FLAG,
    PREFIX,
    DatabaseBundle,
    RuntimeSettings,
    database_bundle,
)

#: The distribution the `local` extra installs for the server's binaries.
SERVER_DISTRIBUTION = "pgserver"

#: How long a start may take before it is a failure: `initdb` on a slow disk,
#: plus the server's own recovery on a data directory an earlier run did not
#: stop cleanly.
START_TIMEOUT_SECONDS = 60.0

#: How long a fast shutdown may take before the server is told to stop NOW.
STOP_TIMEOUT_SECONDS = 30.0

#: `prctl(2)`'s option number for the parent-death signal (linux/prctl.h).
_PR_SET_PDEATHSIG = 1


class BundleRefused(Exception):
    """The bundled server could not be started, named. Carries no credential.

    One exception, because the caller does nothing different for any of them:
    the local install does not start.
    """


def server_binaries() -> Path:
    """The directory holding the bundled `initdb` and `postgres`, or a refusal.

    Found WITHOUT importing `pgserver`: its package initializer imports its
    manager, which this module does not use and whose import creates a lock
    object under the user's runtime directory as a side effect.
    """
    spec = importlib.util.find_spec(SERVER_DISTRIBUTION)
    # THE FIRST LOCATION, OR NONE, read without an index, so no path reaches
    # a subscript that could raise (SonarCloud S6466 on openDox-code#69).
    location = next(iter(spec.submodule_search_locations or ()), None) \
        if spec else None
    if location is None:
        raise BundleRefused(
            "the local install's PostgreSQL server is not installed: it "
            "arrives with the `local` extra, `pip install \"opendox[local]\"` "
            "(R1Q16 (iii)). A local install brings its own database and never "
            "borrows one")
    binaries = Path(location) / "pginstall" / "bin"
    missing = [name for name in ("initdb", "postgres")
               if not os.access(binaries / name, os.X_OK)]
    if missing:
        raise BundleRefused(
            f"the `{SERVER_DISTRIBUTION}` package is installed but carries no "
            f"executable {' or '.join(missing)} under {binaries}; reinstall "
            "the `local` extra")
    return binaries


def _lock_file_pid(bundle: DatabaseBundle) -> int | None:
    """The pid on the first line of the server's `postmaster.pid`, or `None`."""
    try:
        first = (bundle.data_dir / "postmaster.pid").read_text(
            encoding="utf-8").splitlines()[0]
        return int(first.strip())
    except (OSError, IndexError, ValueError):
        return None


#: Where the kernel answers what a pid is, on Linux. A module constant so a
#: case can take it away and exercise a platform without it.
PROC = Path("/proc")


def _identity(pid: int) -> tuple[str, str] | None:
    """`(executable, working directory)` of `pid`, from the kernel's `/proc`.

    `None` where the process is gone or is not this user's to inspect. A
    process that exits between the lock file's read and this one is GONE,
    never proof of anything (Copilot review of openDox-code#69). Raises
    `LookupError` where there is no `/proc` at all (macOS, the BSDs): the
    standard library has no portable way to ask, and `running_pid` then
    believes nothing it cannot prove.
    """
    if not PROC.joinpath("self").exists():
        raise LookupError("no /proc to ask")
    try:
        return (os.readlink(PROC / str(pid) / "exe"),
                os.readlink(PROC / str(pid) / "cwd"))
    except OSError:                  # gone, or another user's: not inspectable
        return None


def _serves(pid: int, bundle: DatabaseBundle) -> bool | None:
    """Whether `pid` is the postmaster of `bundle`'s data directory.

    Asked of the platform, as the pair this module launches: an executable
    named `postgres` whose working directory IS the data directory. The
    postmaster changes into its data directory at startup, and neither of the
    two can be rewritten by its process title. So a recycled pid given to
    anything else is not it, even another `postgres` serving another directory
    (Copilot review of openDox-code#69).

    `False` also for a process that is gone, or that the platform will not
    describe: another user's process cannot be this bundle's server, because
    the server runs as the owner of a 0700 data directory, which is the user
    this runs as. `None` only where nothing can be asked at all.
    """
    try:
        identity = _identity(pid)
    except LookupError:
        return None
    if identity is None:
        return False
    executable, cwd = identity
    if Path(executable.removesuffix(" (deleted)")).name not in {"postgres",
                                                                 "postgres.exe"}:
        return False
    try:
        return Path(cwd).resolve() == bundle.data_dir.resolve()
    except OSError:
        return False


def running_pid(bundle: DatabaseBundle) -> int | None:
    """The pid of a live server on `bundle`'s data directory, or `None`.

    Read from the server's own `postmaster.pid` (its first line), and only
    believed while that process exists and IS this bundle's server: a file
    left by a server that did not stop cleanly names a pid that is gone, or
    that the kernel has since given to something else (`_serves`).
    """
    pid = _lock_file_pid(bundle)
    if pid is None:
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        # gone; or alive and another user's, which cannot be this server
        return None
    # BELIEVED ONLY WHEN PROVEN. Where nothing can say what the pid is (no
    # `/proc`), it is not reported as this server, and this module does not
    # refuse a start over it. PostgreSQL's own interlocks, the lock file's
    # live-pid check and the shared-memory check, still refuse a second
    # postmaster on one data directory. So an unverifiable pid never yields
    # two servers, and never a refusal over a process that is not one. The
    # price on such a platform is a `status` that reports no pid.
    return pid if _serves(pid, bundle) is True else None


def _remove_a_proven_stale_lock(bundle: DatabaseBundle) -> None:
    """Remove a `postmaster.pid` the kernel PROVES is not this server's.

    PostgreSQL removes a lock file whose pid is gone. It refuses to start,
    however, over one whose pid the kernel has given to another live process
    of the same user, and that refusal would last as long as the unrelated
    process does. Where `/proc` shows that process is not this data
    directory's postmaster, the lock is stale by proof and is removed. Where
    nothing can be proven, it is left for PostgreSQL to judge.
    """
    pid = _lock_file_pid(bundle)
    if pid is None:
        return
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return                      # PostgreSQL's own rule covers both
    if _serves(pid, bundle) is False:
        (bundle.data_dir / "postmaster.pid").unlink(missing_ok=True)


def report(bundle: DatabaseBundle) -> dict[str, Any]:
    """The `database_bundle` block `runtime status` prints (#1144 13.1)."""
    return {"data_dir": str(bundle.data_dir),
            "socket_dir": str(bundle.socket_dir),
            "pid": running_pid(bundle)}


def _child_environment() -> dict[str, str]:
    """This process's environment, less libpq's and PostgreSQL's own variables.

    `PGDATA`, `PGPORT`, `PGHOST`, `PGOPTIONS` and the rest would otherwise
    steer `initdb` and the server somewhere other than the paths given on
    their command lines; the command line is the configuration, stated once.
    """
    return {name: value for name, value in os.environ.items()
            if not name.startswith("PG")}


@contextlib.contextmanager
def isolated_from_libpq_environment() -> Iterator[None]:
    """Run a LOCAL install's client side with libpq's `PG*` defaults out of reach.

    libpq fills every connection parameter a DSN leaves unset from the
    process environment. Some of those parameters move the connection
    somewhere else. `PGHOSTADDR` outranks the DSN's socket `host` and sends
    it to a TCP server. `PGSERVICE` fills parameters from a service file.
    `PGOPTIONS` sets session parameters, a `search_path` among them. The
    bundle's DSNs name their socket, port, user and database, but they
    cannot name every parameter libpq has, and an explicitly empty `service`
    is itself an error. So a local install's process reads NONE of them while
    it runs its database: they are lifted out of `os.environ` for the
    duration and put back afterwards (Copilot review of openDox-code#69).
    `_child_environment` already does the same for `initdb` and the server.

    For the process's own entry points only: `generate-and-open --local`
    around its whole lifecycle, and the runtime CLI's verbs under `local`.
    Nothing else in those processes speaks libpq.
    """
    lifted = {name: os.environ.pop(name) for name in
              [name for name in os.environ if name.startswith("PG")]}
    try:
        yield
    finally:
        for name, value in lifted.items():
            os.environ.setdefault(name, value)


def _die_with_parent():
    """A `preexec_fn` that signals the server when its parent goes away (iv).

    `PR_SET_PDEATHSIG` with SIGINT, PostgreSQL's FAST shutdown, so an entry
    point killed outright (SIGKILL, an OOM kill) still stops its server
    instead of leaving it running with the socket held. Linux only, and `None`
    elsewhere, where the ordinary `stop()` is the whole of (iv).

    `prctl` is RESOLVED HERE, in the parent, so the forked child only calls
    it; and the child re-checks its parent afterwards, because a parent that
    died between the fork and the `prctl` would never deliver the signal.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):  # pragma: no cover - a libc without it
        return None
    parent = os.getpid()

    def _preexec() -> None:  # pragma: no cover - runs in the child
        prctl(_PR_SET_PDEATHSIG, int(signal.SIGINT))
        if os.getppid() != parent:
            os._exit(1)

    return _preexec


def _unsafe_because(info: os.stat_result, *, uid: int, gid: int,
                    own: bool) -> str | None:
    """Why one directory of the socket's path is unsafe, or `None`."""
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        return "is a symbolic link"
    if not stat.S_ISDIR(mode):
        return "is not a directory"
    if own:
        if info.st_uid != uid:
            return f"is owned by uid {info.st_uid}, not by this user"
        if mode & 0o022:
            return (f"is writable by {'every user' if mode & 0o002 else 'its group'}"
                    f" (mode {stat.S_IMODE(mode):o})")
        return None
    if info.st_uid not in (uid, 0):
        return f"is owned by uid {info.st_uid}, neither this user nor root"
    sticky = bool(mode & stat.S_ISVTX)
    if mode & 0o002 and not sticky:
        return (f"is writable by every user and is not sticky "
                f"(mode {stat.S_IMODE(mode):o})")
    if mode & 0o020 and info.st_gid != gid and not sticky:
        return (f"is writable by group {info.st_gid}, which is not this "
                f"user's own, and is not sticky (mode {stat.S_IMODE(mode):o})")
    return None


class BundledServer:
    """One local install's PostgreSQL server: started as this process's child.

    Built from the settings a LOCAL `load_settings` returned, so the DSNs it
    serves are the ones every other verb of the same install derives. `start`
    initializes, launches, bootstraps and migrates; `stop` shuts it down; both
    are safe to call more than once, and it is a context manager.
    """

    def __init__(self, settings: RuntimeSettings) -> None:
        self.settings = settings
        self.bundle = database_bundle(settings.state_dir)
        self.process: subprocess.Popen[bytes] | None = None
        self.applied: list[str] = []

    @property
    def log_path(self) -> Path:
        return self.bundle.data_dir.parent / "postgres.log"

    def report(self) -> dict[str, Any]:
        live = self.process is not None and self.process.poll() is None
        return {"data_dir": str(self.bundle.data_dir),
                "socket_dir": str(self.bundle.socket_dir),
                "pid": self.process.pid if live else None}

    # -- start -------------------------------------------------------------

    def start(self) -> BundledServer:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise BundleRefused(
                "the bundled PostgreSQL server refuses to run as root, and so "
                "does this local install: run it as the ordinary user whose "
                "documents it serves")
        binaries = server_binaries()
        already = running_pid(self.bundle)
        if already is not None:
            raise BundleRefused(
                f"a server is already running on {self.bundle.data_dir} "
                f"(pid {already}). One local install's database belongs to one "
                "entry point at a time: stop the other `generate-and-open "
                f"{LOCAL_FLAG}`, or give this one its own {PREFIX}STATE_DIR")
        # THE WHOLE START IS ONE GUARDED OPERATION (Copilot review of
        # openDox-code#69). The directories, `initdb` and the launch fail as
        # plainly as the connection does: a timeout, a permission, a missing
        # file. Each one comes out as the one named refusal the entry point
        # prints, with whatever was started stopped, never as a traceback.
        phase = "preparing its directories"
        try:
            self._prepare_directories()
            phase = "initializing its data directory"
            self._initialize(binaries)
            phase = "launching it"
            _remove_a_proven_stale_lock(self.bundle)
            self._launch(binaries)
            phase = "waiting for it to accept a connection"
            self._wait_until_ready()
            phase = "bootstrapping its database and served role"
            self._bootstrap()
            phase = "migrating it"
            self._migrate()
        except (BundleRefused, migrations.MigrationError):
            self.stop()
            raise
        except Exception as exc:  # noqa: BLE001 - named, never quoted
            # THE DRIVER'S TEXT IS NOT REPEATED, for the reason `runtime/cli.py`
            # gives: it quotes the connection string it was handed. The phase
            # and the class name say what went wrong, and the server's own log
            # says the rest.
            self.stop()
            raise BundleRefused(
                f"the bundled PostgreSQL server could not be started "
                f"({phase}: {type(exc).__name__}); its log is "
                f"{self.log_path}") from None
        except BaseException:
            self.stop()
            raise
        return self

    def _prepare_directories(self) -> None:
        """The state, data and socket directories, each 0700 where this makes it.

        A directory that already exists is NOT re-moded, on the rule the
        runtime's `init` keeps for an operator's own path — except the socket
        directory, whose mode IS the access control of a `trust` server: it is
        this install's own, under its own state directory, and it is narrowed
        to 0700 whatever it was.
        """
        for directory in (self.bundle.state_dir, self.bundle.data_dir.parent):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.bundle.socket_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        # CHECKED BEFORE THE CHMOD, which follows a symbolic link: a `run`
        # placed there as a link would otherwise have its TARGET re-moded.
        self._refuse_an_unsafe_tree()
        os.chmod(self.bundle.socket_dir, 0o700)

    def _refuse_an_unsafe_tree(self) -> None:
        """The socket's whole path is this user's to change, or it is refused.

        `trust` makes reaching the socket the credential, so the 0700 on the
        socket directory is worth only what the directories above it are
        worth. A directory entry is controlled by its PARENT. A parent that
        another user can write lets them rename `run` away, or put a symbolic
        link in its place, after the mode is set (Copilot review of
        openDox-code#69). So, over the RESOLVED path, which a user's own
        symbolic link in `OPENDOX_STATE_DIR` may lead to:

          * this install's own tree, the state directory, `postgres/` and
            `run/`, must be real directories, owned by this user and writable
            by no one else;
          * every directory above it must be owned by this user or by root.
            One that every user can write must be sticky, as `/tmp` is, so
            nobody can rename what is not theirs. One that its group can
            write must be sticky too, unless the group is this user's own,
            which is how a umask-002 system creates the user's directories.
        """
        uid, gid = os.getuid(), os.getgid()
        state = self.bundle.state_dir.resolve()
        own = [state, state / self.bundle.socket_dir.parent.name,
               state / self.bundle.socket_dir.parent.name / self.bundle.socket_dir.name]
        for directory, mine in [(path, True) for path in own] + \
                [(path, False) for path in state.parents]:
            info = os.lstat(directory)
            reason = _unsafe_because(info, uid=uid, gid=gid, own=mine)
            if reason is not None:
                raise BundleRefused(
                    f"{directory} {reason}, so another user could replace the "
                    "bundled server's socket directory, and reaching that "
                    "socket is the only credential the server asks for. Use a "
                    f"state directory only this user can change ({PREFIX}"
                    "STATE_DIR)")

    #: The prefix an initialization attempt's directory carries, beside the
    #: data directory, followed by the pid of the process making it.
    ATTEMPT_PREFIX = "data.initdb-"

    def _initialize(self, binaries: Path) -> None:
        """A complete cluster at `data_dir`, or a refusal. Never a partial one.

        `initdb` runs into an ATTEMPT directory beside the data directory, and
        the attempt is renamed into place only once `initdb` has succeeded. So
        a data directory exists only as a finished cluster, and a first start
        that dies midway (a kill, a full disk, a power cut) leaves an attempt
        and not a half-built data directory that the next start would either
        launch or fail to re-initialize for ever (Copilot review of
        openDox-code#69). The next start removes an attempt whose process is
        gone, and starts again.

        A data directory that exists and holds no cluster is NOT this
        install's to remove, unless it is empty: it is refused, named, and
        left as it is.
        """
        data = self.bundle.data_dir
        if (data / "PG_VERSION").is_file():
            return
        if data.exists():
            try:
                data.rmdir()                    # an empty directory holds nothing
            except OSError:
                raise BundleRefused(
                    f"{data} exists and holds no PostgreSQL cluster, so it is "
                    "not this install's database, and it is left untouched: "
                    "move it aside, or give this install its own "
                    f"{PREFIX}STATE_DIR") from None
        self._remove_abandoned_attempts()
        attempt = Path(tempfile.mkdtemp(
            prefix=f"{self.ATTEMPT_PREFIX}{os.getpid()}-", dir=data.parent))
        try:
            self._initdb(binaries, attempt)
            try:
                os.rename(attempt, data)
            except OSError:
                if not (data / "PG_VERSION").is_file():
                    raise
                # another start finished first; its cluster is the one used
                shutil.rmtree(attempt, ignore_errors=True)
        except BaseException:
            shutil.rmtree(attempt, ignore_errors=True)
            raise

    def _remove_abandoned_attempts(self) -> None:
        """Every initialization attempt whose process no longer exists."""
        for candidate in self.bundle.data_dir.parent.glob(
                f"{self.ATTEMPT_PREFIX}*"):
            owner = candidate.name[len(self.ATTEMPT_PREFIX):].split("-", 1)[0]
            try:
                os.kill(int(owner), 0)
            except ProcessLookupError:
                shutil.rmtree(candidate, ignore_errors=True)
            except (ValueError, OSError):
                continue                        # alive, or not ours to judge

    def _initdb(self, binaries: Path, target: Path) -> None:
        done = subprocess.run(
            [str(binaries / "initdb"), "-D", str(target),
             "-U", BUNDLE_OWNER_ROLE, "--auth-local=trust", "--auth-host=reject",
             "--encoding=UTF8", "--locale=C", "--no-instructions"],
            env=_child_environment(), capture_output=True, text=True,
            timeout=START_TIMEOUT_SECONDS)
        if done.returncode != 0:
            detail = (done.stderr or done.stdout).strip().splitlines()[-5:]
            raise BundleRefused(
                f"initdb could not initialize {self.bundle.data_dir} "
                f"(exit {done.returncode}): {' | '.join(detail)}")

    def _launch(self, binaries: Path) -> None:
        log = open(self.log_path, "ab")          # noqa: SIM115 - the child keeps it
        try:
            self.process = subprocess.Popen(
                [str(binaries / "postgres"), "-D", str(self.bundle.data_dir),
                 "-k", str(self.bundle.socket_dir), "-p", str(BUNDLE_PORT),
                 # NO TCP LISTENER (13.1): an empty `listen_addresses` opens
                 # no TCP socket at all, so no pre-existing service on any
                 # port can stand in for this server, and nothing off this
                 # machine can reach it.
                 "-c", "listen_addresses=",
                 "-c", "unix_socket_permissions=0700"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env=_child_environment(),
                # ITS OWN SESSION, so a terminal's Ctrl-C reaches this process
                # and not the server behind its back: the stop is `stop()`'s,
                # in order, after the document server has closed.
                start_new_session=True,
                preexec_fn=_die_with_parent())
        finally:
            log.close()

    def _wait_until_ready(self) -> None:
        import psycopg

        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        last = "no attempt"
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise BundleRefused(
                    f"the bundled PostgreSQL server exited during start "
                    f"(exit {self.process.returncode}); its log is "
                    f"{self.log_path}: {self._log_tail()}")
            try:
                with psycopg.connect(self._dsn(BUNDLE_OWNER_ROLE, "postgres"),
                                     connect_timeout=2, autocommit=True) as conn:
                    conn.execute("select 1")
                return
            except psycopg.OperationalError as exc:
                # THE CLASS NAME ONLY: a driver's message quotes the DSN it
                # could not reach, and this package never repeats one
                # (`runtime/cli.py`'s redaction contract).
                last = type(exc).__name__
                time.sleep(0.1)
        raise BundleRefused(
            f"the bundled PostgreSQL server did not accept a connection within "
            f"{START_TIMEOUT_SECONDS:.0f}s ({last}); its log is "
            f"{self.log_path}")

    def _dsn(self, role: str, database: str) -> str:
        """`DatabaseBundle.dsn`, aimed at a database other than the served one."""
        return self.bundle.dsn(role).replace(
            f"@/{BUNDLE_DATABASE}?", f"@/{database}?", 1)

    def _bootstrap(self) -> None:
        """The database, the served role and its grants — idempotent.

        The grants are the compose stack's (`init-runtime-role.sh`), narrowed
        the same way: CONNECT on the database, USAGE on `public`, and DML on
        every table the OWNER creates from here on, by default privileges —
        which on this install's own fresh database is the six coordination
        tables and the ledger, and nothing else. The migration then narrows
        the served role's rights on the ledger to SELECT.
        """
        import psycopg
        from psycopg import sql

        with psycopg.connect(self._dsn(BUNDLE_OWNER_ROLE, "postgres"),
                             autocommit=True) as conn:
            if conn.execute("select 1 from pg_database where datname = %s",
                            (BUNDLE_DATABASE,)).fetchone() is None:
                conn.execute(sql.SQL("create database {} owner {}").format(
                    sql.Identifier(BUNDLE_DATABASE),
                    sql.Identifier(BUNDLE_OWNER_ROLE)))
            if conn.execute("select 1 from pg_roles where rolname = %s",
                            (BUNDLE_SERVED_ROLE,)).fetchone() is None:
                conn.execute(sql.SQL("create role {} login").format(
                    sql.Identifier(BUNDLE_SERVED_ROLE)))
        with psycopg.connect(self.bundle.migration_dsn, autocommit=True) as conn:
            served, owner = (sql.Identifier(BUNDLE_SERVED_ROLE),
                             sql.Identifier(BUNDLE_OWNER_ROLE))
            conn.execute(sql.SQL("grant connect on database {} to {}").format(
                sql.Identifier(BUNDLE_DATABASE), served))
            conn.execute(sql.SQL("grant usage on schema public to {}").format(
                served))
            conn.execute(sql.SQL(
                "alter default privileges for role {} in schema public grant "
                "select, insert, update, delete on tables to {}").format(
                    owner, served))

    def _migrate(self) -> None:
        """Starting AND MIGRATING is all release 1 asks of the store (R1Q16 (ii))."""
        from opendox.runtime.db import Database

        database = Database(self.bundle.migration_dsn,
                            application_name="opendox-local-migrate")
        with database:
            self.applied = migrations.MigrationRunner(
                database, migrations_dir=self.settings.migrations_dir,
                runtime_role=self.settings.runtime_pg_role,
                served_schema=self.settings.served_schema,
                served_database=self.settings.served_database).apply()

    def _log_tail(self) -> str:
        try:
            lines = self.log_path.read_text(encoding="utf-8",
                                            errors="replace").splitlines()
        except OSError:
            return "(no log)"
        return " | ".join(lines[-5:])

    # -- stop --------------------------------------------------------------

    def stop(self) -> None:
        """A FAST shutdown (SIGINT), then an immediate one, then a kill.

        FAST, and not PostgreSQL's default "smart" shutdown, because the
        document server that is its only client has already closed: waiting
        for sessions to end would wait for nothing, or for a leaked
        connection. Safe to call twice, and on a server that never started.
        """
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        for sig, wait in ((signal.SIGINT, STOP_TIMEOUT_SECONDS),
                          (signal.SIGQUIT, 5.0), (signal.SIGKILL, 5.0)):
            try:
                process.send_signal(sig)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=wait)
                return
            except subprocess.TimeoutExpired:
                continue

    def __enter__(self) -> BundledServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()


__all__ = ["BUNDLE_PORT", "BundleRefused", "BundledServer",
           "isolated_from_libpq_environment", "report", "running_pid",
           "server_binaries"]
