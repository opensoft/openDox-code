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

THE SERVER'S OWN PACKAGE IS `pixeltable-pgserver` (pyproject.toml's `local`
extra; RULED openxFactory#656 `5916000030` item 2), and only its BINARIES are
used: PostgreSQL 16's `initdb` and `postgres` from the wheel's `pginstall/bin`,
found through the INSTALLED distribution's own file list
(`importlib.metadata`), never by import precedence, and without importing
`pixeltable_pgserver` at all (see `server_binaries`). Its Python manager is deliberately not used. It daemonizes the server
through `pg_ctl`, which re-parents it away from this process (against (i)). It
shares one server between processes by reference count and stops it from
`atexit`, which a SIGTERM never runs (against (iv)). And it may put the socket
under the user's runtime directory, opened to 0777, instead of the state
directory (against 13.1). The binaries link only the C library (libc, libm,
libpthread, librt, libdl) and libz from the system, plus the wheel's own
vendored libpq, so they need no system PostgreSQL and no ICU.

THE LIFECYCLE, IN FULL:

  * `initdb` once per data directory, into an attempt directory that is
    renamed into place only when it has succeeded, so an interrupted first
    start never leaves a half-built cluster: the MIGRATION identity
    (`config.BUNDLE_OWNER_ROLE`) is the bootstrap superuser, local connections
    are `peer` and host connections are `reject`, UTF-8 in the `C` locale.
  * PEER AUTHENTICATION, re-asserted before every launch (RULED
    openxFactory#656 `5916000030` item 3). `pg_hba.conf` admits Unix-socket
    connections through the `opendox` map only, and `pg_ident.conf`'s map
    admits THIS install's OS user as the two roles and nobody else. The kernel
    reports the connecting process's uid (`SO_PEERCRED`), so no password
    exists to leak or to store, and a process of any other user is refused
    even where it could reach the socket. The socket's directory is 0700
    besides, and the server opens no TCP port at all.
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
from importlib import metadata
import os
import re
import shutil
import signal
import socket
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
    BUNDLE_DATA_DIR,
    BUNDLE_OWNER_ROLE,
    BUNDLE_PORT,
    BUNDLE_SERVED_ROLE,
    BUNDLE_SOCKET_DIR,
    LOCAL_FLAG,
    PREFIX,
    DatabaseBundle,
    RuntimeSettings,
    database_bundle,
)

#: The distribution the `local` extra installs for the server's binaries, and
#: the package it installs them under.
SERVER_DISTRIBUTION = "pixeltable-pgserver"
SERVER_PACKAGE = "pixeltable_pgserver"

#: The `pg_ident.conf` map `pg_hba.conf`'s one local line authenticates through.
IDENT_MAP = "opendox"

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


#: Whether `os.mkdir` takes `dir_fd` here, read ONCE at import: a case that
#: stands a wrapper in for `os.mkdir` must not read as another platform.
MKDIR_TAKES_DIR_FD = os.mkdir in os.supports_dir_fd


def unsupported_platform() -> str | None:
    """Why this platform cannot run the local install's bundled server, or `None`.

    The bundle is a POSIX design, and every one of its guarantees rests on a
    POSIX primitive. The socket is a Unix socket, and authentication is peer,
    by the kernel's uid. The directories are judged by uid and made without
    following a link (`os.getuid`, `O_DIRECTORY`, `O_NOFOLLOW`, a `dir_fd`
    `mkdir`, `fchmod`). The carrier ships wheels for Windows too, and there
    a start failed as a generic `AttributeError` and `status` raised one
    (Copilot review of openDox-code#69). So the gap is named first, as
    `runtime/local_git_adapter.py`'s `refuse_without_the_no_follow_walk`
    names its own.
    """
    missing = [name for name, present in (
        ("os.getuid", hasattr(os, "getuid")),
        ("os.O_DIRECTORY", hasattr(os, "O_DIRECTORY")),
        ("os.O_NOFOLLOW", hasattr(os, "O_NOFOLLOW")),
        ("os.fchmod", hasattr(os, "fchmod")),
        ("mkdir with dir_fd", MKDIR_TAKES_DIR_FD),
        ("socket.AF_UNIX", hasattr(socket, "AF_UNIX")),
    ) if not present]
    if not missing:
        return None
    return (f"the local install's bundled PostgreSQL server needs a POSIX "
            f"platform, and this one ({sys.platform}) lacks "
            f"{', '.join(missing)}: its socket is a Unix socket authenticated "
            "by peer, and its directories are judged by owner and made "
            "without following a link. Use a hosted install here "
            f"({PREFIX}INSTALL_MODE=hosted, with an operator's database)")


def _distribution_search_path() -> list[str]:
    """`sys.path` without the working directory, which no install is.

    `python -m opendox.cli` and `python -c` put the directory they were
    started in at the front of `sys.path` (as `''`, or as its absolute
    path), and a corpus repository is exactly where a user runs them from.
    """
    try:
        here = Path.cwd().resolve()
    except OSError:                       # a working directory since removed
        here = None
    kept = []
    for entry in sys.path:
        if not entry:
            continue
        try:
            if here is not None and Path(entry).resolve() == here:
                continue
        except (OSError, RuntimeError):
            continue
        kept.append(entry)
    return kept


def server_binaries() -> Path:
    """The directory holding the bundled `initdb` and `postgres`, or a refusal.

    Found WITHOUT importing `pixeltable_pgserver`: its package initializer
    imports its manager, which this module does not use and which registers an
    `atexit` handler and reaches for the user's runtime directory.

    AND FOUND AS THE INSTALLED DISTRIBUTION'S OWN FILES, never by import
    precedence (Copilot review of openDox-code#69). `importlib.util.find_spec`
    follows `sys.path`, whose first entry under `python -m opendox.cli` is
    the working directory. So a checkout holding an executable
    `pixeltable_pgserver/pginstall/bin/postgres` was run as this install's
    database server. The distribution is now looked up by its name
    (`importlib.metadata`), on `sys.path` WITHOUT the working directory, and
    both binaries must be files its RECORD lists, located inside it.
    """
    candidates = list(metadata.distributions(
        name=SERVER_DISTRIBUTION, path=_distribution_search_path()))
    if not candidates:
        raise BundleRefused(
            "the local install's PostgreSQL server is not installed: it "
            "arrives with the `local` extra, `pip install \"opendox[local]\"` "
            "(R1Q16 (iii)). A local install brings its own database and never "
            "borrows one")
    distribution = candidates[0]
    suffix = ".exe" if os.name == "nt" else ""
    listed = {str(entry).replace("\\", "/"): entry
              for entry in (distribution.files or ())}
    root = Path(distribution.locate_file("")).resolve()
    binaries = Path(distribution.locate_file(f"{SERVER_PACKAGE}/pginstall/bin"))
    missing = []
    for name in ("initdb", "postgres"):
        entry = listed.get(f"{SERVER_PACKAGE}/pginstall/bin/{name}{suffix}")
        located = (Path(distribution.locate_file(entry)).resolve()
                   if entry is not None else None)
        if (located is None or not located.is_relative_to(root)
                or not os.access(located, os.X_OK)):
            missing.append(name)
    if missing:
        raise BundleRefused(
            f"the `{SERVER_DISTRIBUTION}` package is installed but its own "
            f"file list carries no executable {' or '.join(missing)} under "
            f"{binaries}; reinstall the `local` extra")
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


def refusal_before_connecting(bundle: DatabaseBundle) -> str | None:
    """Why a local verb must not connect to `bundle`'s socket, or `None`.

    `runtime status`, `migrate` and `reset` of a LOCAL install connect, as
    the served role or as the OWNER, to whatever answers at the bundle's
    socket path. A start judges that path, and these verbs did not: a state
    directory every user could write, whose `postgres/run` was a link to
    another bundle's socket directory, had `status` and `migrate` run as the
    owner role against that other server while a start refused the same
    tree (adversarial review of openDox-code#69). So before any client
    connection, two things are asked, and neither writes anything:

      * THE TREE CHECK a start asks, of what exists (`refuse_an_unsafe_tree`
        with `existing_only`): a socket directory that is a link, or that
        another user could replace, is refused here as it is there;
      * A LIVE SERVER OF THIS DATA DIRECTORY behind the socket. The lock
        file in this data directory, `postmaster.pid`, names a live process
        that, where the platform can say (`_serves`), is a `postgres` whose
        working directory is this data directory, and it names THIS socket
        directory as the one the server listens on (its fifth line). Where
        `/proc` cannot say what the pid is, the other answers still bind
        the socket to this tree.
    """
    gap = unsupported_platform()
    if gap is not None:
        return gap
    try:
        refuse_an_unsafe_tree(bundle, existing_only=True)
    except BundleRefused as exc:
        return str(exc)
    except (OSError, RuntimeError, ValueError) as exc:
        # A SYMBOLIC-LINK LOOP OR A NUL IS A REASON TOO (Copilot review of
        # openDox-code#69): `Path.resolve()` raises `RuntimeError` for a loop
        # (Python 3.12) and the `os` calls `ValueError` for an embedded NUL,
        # and either would otherwise escape as the CLI's generic failure.
        return (f"the bundled server's path under {bundle.state_dir} could "
                f"not be judged ({type(exc).__name__}): it is not a tree "
                "this install can verify")
    lock = bundle.data_dir / "postmaster.pid"
    try:
        lines = lock.read_text(encoding="utf-8").splitlines()
        pid = int(lines[0].strip())
    except (OSError, IndexError, ValueError):
        return (f"no bundled server is running on {bundle.data_dir}: it has no "
                "readable postmaster.pid. A local install's server is started "
                f"by `opendox generate-and-open {LOCAL_FLAG}`, which owns it")
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return (f"no bundled server is running on {bundle.data_dir}: its "
                f"postmaster.pid names pid {pid}, which is not a live process "
                "of this user")
    if _serves(pid, bundle) is False:
        return (f"pid {pid}, named by {lock}, is not the postgres serving "
                f"{bundle.data_dir}, so what answers at {bundle.socket_dir} "
                "is not this install's server")
    listens = lines[4].strip() if len(lines) > 4 else ""
    if listens != str(bundle.socket_dir):
        return (f"the server on {bundle.data_dir} listens at "
                f"{listens or 'no Unix socket'}, not at {bundle.socket_dir}, so "
                "what answers there is not this install's server")
    return None


def report(bundle: DatabaseBundle) -> dict[str, Any]:
    """The `database_bundle` block `runtime status` prints (#1144 13.1).

    THE PID ONLY BEHIND A VERIFIED TREE (Copilot review of openDox-code#69).
    `running_pid` reads the lock file through whatever `postgres/data` is,
    so a `data` linked to another live bundle answered with THAT server's
    pid, while the connection guard refused the same tree. A pid is
    reported only where `refusal_before_connecting` has nothing to say, so
    `status` never claims a server it would not connect to.
    """
    verified = refusal_before_connecting(bundle) is None
    return {"data_dir": str(bundle.data_dir),
            "socket_dir": str(bundle.socket_dir),
            "pid": running_pid(bundle) if verified else None}


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

    ON LINUX THE SIGNAL IS ARMED OR THE SERVER IS NOT STARTED (Copilot review
    of openDox-code#69). `ctypes` reports a failed `prctl` by its `-1`
    return, never by raising (a seccomp filter that denies it, say), and
    ignoring that left a server that outlives an entry point killed
    outright. So a nonzero return raises in the child, which `subprocess`
    raises in this process as `SubprocessError` (`_launch` names it), and a
    Linux C library with no `prctl` at all is the same refusal here.
    """
    if not sys.platform.startswith("linux"):
        return None
    try:
        prctl = ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):  # pragma: no cover - a libc without it
        raise BundleRefused(_UNARMED) from None
    parent = os.getpid()

    def _preexec() -> None:  # pragma: no cover - runs in the child
        if prctl(_PR_SET_PDEATHSIG, int(signal.SIGINT)) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
        if os.getppid() != parent:
            os._exit(1)

    return _preexec


#: The refusal when the parent-death signal cannot be armed on Linux.
_UNARMED = ("the bundled PostgreSQL server could not be given its "
            "parent-death signal (prctl PR_SET_PDEATHSIG failed), so it would "
            "outlive an entry point killed outright (R1Q16 (iv)); it is not "
            "started")


#: The install's own two directories under its state directory, the socket's
#: parent and the socket directory (`config.BUNDLE_SOCKET_DIR`).
BUNDLE_TREE = BUNDLE_SOCKET_DIR.parts


def _make_private_directories(leaf: Path, *, state: Path) -> None:
    """`leaf` and every missing directory above it, each born exactly 0700.

    `Path.mkdir(parents=True)` gives the directories it creates on the way
    the default mode less the umask, whatever mode the leaf is given. So
    under a common umask of 0002 a fresh `~/.local/state/opendox/...` would
    create `.local` and `state` group-writable, and the tree check would
    then refuse the directories this install had just made (Copilot review
    of openDox-code#69). Each missing component is created here, one at a
    time, under a umask of 077, so it is born 0700, whatever the user's
    umask is, with no `chmod` after it. A directory that already exists is
    left as it is, and the tree check judges it.

    NOTHING IS MADE THROUGH A PATH THAT WAS NOT JUDGED FIRST (Copilot review
    of openDox-code#69). The caller has refused an unsafe EXISTING prefix
    before this runs (`BundledServer._prepare_directories`), so the deepest
    directory that exists is safe to open. Each missing component is then
    made RELATIVE TO ITS PARENT'S DESCRIPTOR and opened with `O_NOFOLLOW`
    before anything is made beneath it. A name that another user put there
    first, in a sticky directory such as `/tmp`, is refused, never followed
    or written through: a symbolic link, something that is not a directory,
    or a directory that is not this user's alone.

    AND THE DIRECTORY IT STARTS FROM IS JUDGED BY ITS DESCRIPTOR, before
    the first `mkdir` (adversarial review of openDox-code#69). Opening it
    follows a link, which this install allows on the configured path, so
    what the descriptor names is asked the tree check's own question
    (`_unsafe_because`): this user's alone where it is the state directory
    or under it, and otherwise this user's or root's, with any write by
    others only behind the sticky bit. The path-wise check before it asks
    the same question; this one asks it of the very directory that is
    written into.

    THE UMASK IS PROCESS-WIDE, and it is narrowed only for these few
    `mkdir`s and then put back. A file another thread creates meanwhile can
    only come out more private than asked, never less.
    """
    uid = os.getuid()
    missing: list[str] = []
    base = leaf
    while not os.path.lexists(base):
        missing.append(base.name)
        base = base.parent
    if not missing:
        return
    descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    own = base == state or state in base.parents
    reason = _unsafe_because(os.fstat(descriptor), uid=uid, own=own)
    if reason is not None:
        os.close(descriptor)
        raise BundledServer._unsafe(base, reason)
    path = base
    previous = os.umask(0o077)
    try:
        for name in reversed(missing):
            path = path / name
            try:
                os.mkdir(name, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass            # made first, by a concurrent start or by someone else: judged next
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=descriptor)
            except OSError:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                reason = _unsafe_because(info, uid=uid, own=True)
                if reason is None:
                    raise
                raise BundledServer._unsafe(path, reason) from None
            os.close(descriptor)
            descriptor = child
            reason = _unsafe_because(os.fstat(descriptor), uid=uid, own=True)
            if reason is not None:
                raise BundledServer._unsafe(path, reason)
    finally:
        os.umask(previous)
        os.close(descriptor)


def os_user() -> str:
    """The name of the OS user this runs as, which peer authentication maps.

    The SERVER resolves a connecting uid to a name through the same password
    database, so a uid with no entry could not be authenticated at all, and is
    refused here, by name. So is a name that `pg_ident.conf` could read as more
    than a name: a regular expression (a leading `/`), a quote, a comment
    mark, or white space.
    """
    import pwd

    uid = os.getuid()
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        raise BundleRefused(
            f"uid {uid} has no entry in the password database, and the bundled "
            "server's peer authentication maps the connecting user BY NAME, so "
            "it could never admit this one. Run the local install as a user "
            "the system knows") from None
    if not name or name.startswith("/") or any(
            ch in name for ch in '"#') or any(ch.isspace() for ch in name):
        raise BundleRefused(
            f"the OS user name {name!r} cannot be written into the bundled "
            "server's pg_ident.conf as a plain name (it holds a quote, a `#`, "
            "white space, or starts with `/`)")
    return name


def authentication_files(user: str) -> dict[str, str]:
    """`pg_hba.conf` and `pg_ident.conf` for a local install run by `user`.

    RULED openxFactory#656 `5916000030` item 3 ("Peer auth + accept"):
      * ONE local line, PEER through the `opendox` map. The kernel reports the
        connecting process's uid, and the map admits `user` as the owner role
        and as the served role, and nobody else as anybody.
      * Every HOST connection is rejected. The server also listens on no TCP
        address at all (`listen_addresses` is empty), so these lines never
        match. They are written so that the file says what the install is.
      * No replication line, so a PHYSICAL replication connection matches
        no rule and is refused. A LOGICAL one (`replication=database`)
        names a database, so `pg_hba.conf` reads it as the ordinary local
        connection it resembles, and no rule here can tell the two apart:
        it was accepted as `peer:<user>` (adversarial review of
        openDox-code#69). So the launch sets `max_wal_senders=0`, and the
        server starts no WAL sender for either kind. A replication
        connection is refused by the server, whatever the files say.
    """
    header = ("# Written by opendox.runtime.bundle before every start of this local\n"
              "# install's bundled server (plan 034 T072). Changes here are replaced.\n")
    hba = (header +
           "# TYPE  DATABASE  USER  ADDRESS      METHOD\n"
           f"local   all       all                peer map={IDENT_MAP}\n"
           "host    all       all   0.0.0.0/0    reject\n"
           "host    all       all   ::/0         reject\n")
    ident = (header +
             "# MAPNAME  SYSTEM-USERNAME  PG-USERNAME\n"
             f'{IDENT_MAP}  "{user}"  {BUNDLE_OWNER_ROLE}\n'
             f'{IDENT_MAP}  "{user}"  {BUNDLE_SERVED_ROLE}\n')
    return {"pg_hba.conf": hba, "pg_ident.conf": ident}


def write_authentication(data_dir: Path, user: str) -> None:
    """Write both files into `data_dir`, each replaced atomically, mode 0600.

    Before EVERY launch, not only after `initdb`: a data directory an earlier
    build initialized, or a file edited by hand, is brought back to the one
    configuration this install runs with.

    THE 0600 IS SET, NOT ASKED FOR (Copilot review of openDox-code#69). An
    `open` mode is only a creation request: the umask filters it, and it
    changes nothing about a file that exists already. So a temporary file an
    interrupted start left at the same name (a 0644 one, or a symbolic link)
    is removed first. The new one is created EXCLUSIVELY and without following
    a link, and its descriptor is set to exactly 0600 before anything is
    written into it.
    """
    for name, content in authentication_files(user).items():
        target = data_dir / name
        temporary = data_dir / f".{name}.opendox-{os.getpid()}"
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)          # an interrupted start's; a link itself, never its target
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1           # the handle closes it now
                handle.write(content)
            os.replace(temporary, target)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
            raise


def _unsafe_because(info: os.stat_result, *, uid: int, own: bool) -> str | None:
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
    # A GROUP IS OTHER USERS, the user's own primary group included: it can
    # have other members (Copilot review of openDox-code#69).
    if mode & 0o022 and not mode & stat.S_ISVTX:
        return (f"is writable by {'every user' if mode & 0o002 else 'its group'}"
                f" and is not sticky (mode {stat.S_IMODE(mode):o})")
    return None


def refuse_an_unsafe_tree(bundle: DatabaseBundle, *,
                          existing_only: bool = False) -> None:
    """The socket's whole path is this user's to change, or it is refused.

    The socket's directory is how this install's clients find ITS
    server, so the 0700 on it is worth only what the path above it is
    worth. Peer authentication keeps other users out of the server, but
    not a substitute socket out of the path: whoever could replace `run`
    could stand up a server of their own for this install's clients to
    talk to. A directory entry is controlled by its PARENT: a parent that
    another user can write lets them rename `run` away, or put a symbolic
    link in its place, after the mode is set. A symbolic link on the way there
    can be pointed elsewhere by whoever owns it, or by whoever can write
    the directory it sits in (Copilot review of openDox-code#69). So:

      * THE INSTALL'S OWN TREE, as the configured path resolves: the
        state directory, `postgres/` and `run/` must be real directories,
        owned by this user and writable by no one else;
      * EVERY DIRECTORY ABOVE IT, on the configured path and on the path
        it resolves to, must be owned by this user or by root. One that
        anyone else can write, a group included, must be sticky, as
        `/tmp` is, so nobody can rename what is not theirs;
      * EVERY SYMBOLIC LINK on the configured path must be this user's or
        root's.

    `OPENDOX_STATE_DIR` never holds `..` (`config.state_dir` refuses it),
    so the configured path's components are the ones the kernel walks.

    With `existing_only`, the same rules are asked of only what exists
    yet. `_prepare_directories` asks that BEFORE it creates anything,
    so the links are checked first, a broken one included (Copilot
    review of openDox-code#69).
    """
    uid = os.getuid()
    configured = bundle.state_dir

    def present(path: Path) -> bool:
        return not existing_only or os.path.lexists(path)

    for component in (configured, *configured.parents):
        if not present(component):
            continue
        info = os.lstat(component)
        if stat.S_ISLNK(info.st_mode) and info.st_uid not in (uid, 0):
            raise BundledServer._unsafe(
                component, f"is a symbolic link owned by uid {info.st_uid}, "
                "neither this user nor root, who could point it elsewhere")
    state = configured.resolve()
    tree = [state, state / BUNDLE_TREE[0], state / BUNDLE_TREE[0] / BUNDLE_TREE[1]]
    # AND THE DATA DIRECTORY, where one exists already, a broken link
    # included (Copilot review of openDox-code#69). A `data` placed there
    # as a link to a cluster elsewhere would otherwise be launched, and
    # given this install's authentication files, outside the state tree.
    # A fresh one needs no check: `_initialize` renames it into place.
    data = state / BUNDLE_DATA_DIR
    if os.path.lexists(data):
        tree.append(data)
    checks = [(path, True) for path in tree] + [
        (path, False) for path in dict.fromkeys(
            [*state.parents, *configured.parents])]
    for directory, mine in checks:
        if not present(directory):
            continue
        info = os.lstat(directory) if mine else os.stat(directory)
        reason = _unsafe_because(info, uid=uid, own=mine)
        if reason is not None:
            raise BundledServer._unsafe(directory, reason)


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
        gap = unsupported_platform()
        if gap is not None:
            raise BundleRefused(gap)
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
            phase = "configuring its authentication"
            write_authentication(self.bundle.data_dir, os_user())
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
        directory, which guards the only way in: it is this install's own,
        under its own state directory, and it is narrowed to 0700 whatever it
        was.
        """
        # JUDGED BEFORE ANY WRITE, AND AGAIN AFTER (Copilot review of
        # openDox-code#69). What exists already is checked first, so no
        # directory is made through a link, or beneath a directory, that the
        # tree check would refuse, and `_make_private_directories` refuses a
        # name someone else put in its way. The whole tree is then checked
        # BEFORE THE CHMOD, which follows a symbolic link: a `run` placed
        # there as a link would otherwise have its TARGET re-moded.
        self._refuse_an_unsafe_tree(existing_only=True)
        _make_private_directories(self.bundle.socket_dir,
                                  state=self.bundle.state_dir)
        self._refuse_an_unsafe_tree()
        os.chmod(self.bundle.socket_dir, 0o700)

    def _refuse_an_unsafe_tree(self, *, existing_only: bool = False) -> None:
        """`refuse_an_unsafe_tree`, for this server's own bundle."""
        refuse_an_unsafe_tree(self.bundle, existing_only=existing_only)

    @staticmethod
    def _unsafe(directory: Path, reason: str) -> BundleRefused:
        return BundleRefused(
            f"{directory} {reason}, so another user could replace the bundled "
            "server's socket directory and put a server of their own where "
            "this install's clients look for it. Use a state directory only "
            f"this user can change ({PREFIX}STATE_DIR)")

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
            self._refuse_another_major(binaries)
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

    def _refuse_another_major(self, binaries: Path) -> None:
        """An existing cluster is opened only by the major that made it.

        PostgreSQL refuses another major's data directory itself, but only
        from inside a launch, where the reason reaches nobody but the log.
        The carrier's `pginstall/` is PostgreSQL 16 today, and upstream's
        default is already 18 (adversarial review of openDox-code#69). So
        the server's own `postgres --version` is asked first, against the
        cluster's `PG_VERSION`, and a disagreement is the named refusal,
        before anything is written into the data directory.
        """
        data = self.bundle.data_dir
        cluster = (data / "PG_VERSION").read_text(encoding="utf-8").strip()
        done = subprocess.run(
            [str(binaries / "postgres"), "--version"], env=_child_environment(),
            capture_output=True, text=True, timeout=START_TIMEOUT_SECONDS)
        found = re.search(r"\(PostgreSQL\) (\d+)", done.stdout or "")
        if found is None:
            raise BundleRefused(
                f"the bundled `postgres` under {binaries} does not say which "
                f"PostgreSQL it is (`postgres --version` exited "
                f"{done.returncode}), so it is not given {data}, a "
                f"PostgreSQL {cluster} cluster; reinstall the `local` extra")
        if found.group(1) != cluster:
            raise BundleRefused(
                f"{data} holds a PostgreSQL {cluster} cluster and the bundled "
                f"server is PostgreSQL {found.group(1)}: a cluster is opened "
                "only by the major version that made it. Reinstall the "
                f"`local` extra this install was made with (`{SERVER_DISTRIBUTION}` "
                "is pinned below 0.7 for this reason), or move the data "
                "directory aside, and lose its coordination state, to start "
                "a new one")

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
             "-U", BUNDLE_OWNER_ROLE, "--auth-local=peer", "--auth-host=reject",
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
                 "-c", "unix_socket_permissions=0700",
                 # THE CLUSTER'S OWN FILES, PINNED (Copilot review of
                 # openDox-code#69). An existing cluster's
                 # `postgresql.conf` can point `data_directory`, `hba_file`
                 # and `ident_file` elsewhere: at an outside `trust` file
                 # that the files just rewritten would never replace, or at
                 # a cluster outside the state directory. The command line
                 # outranks every configuration file, so these three are
                 # the data directory and the two files written above.
                 "-c", f"data_directory={self.bundle.data_dir}",
                 "-c", f"hba_file={self.bundle.data_dir / 'pg_hba.conf'}",
                 "-c", f"ident_file={self.bundle.data_dir / 'pg_ident.conf'}",
                 # NO REPLICATION, physical or logical: see
                 # `authentication_files`, whose rules cannot refuse a
                 # logical one (adversarial review of openDox-code#69).
                 "-c", "max_wal_senders=0"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                env=_child_environment(),
                # ITS OWN SESSION, so a terminal's Ctrl-C reaches this process
                # and not the server behind its back: the stop is `stop()`'s,
                # in order, after the document server has closed.
                start_new_session=True,
                preexec_fn=_die_with_parent())
        except subprocess.SubprocessError:
            # `_die_with_parent`'s child refused to run unarmed: nothing started
            raise BundleRefused(_UNARMED) from None
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
                # READY MEANS THIS CHILD IS SERVING, not merely that the socket
                # answered (Copilot review of openDox-code#69). Two entry points
                # racing from an idle state both launch. The loser's `postgres`
                # lives a moment before it refuses the winner's lock, and the
                # winner's socket already answers. So once a connection has
                # answered, the data directory's lock file must name THIS
                # child. Otherwise the wait goes on until this child exits and
                # is refused. One check, AFTER the connection, is enough. The
                # lock admits one postmaster per data directory, the socket
                # directory belongs to exactly one data directory, and a
                # lock naming this child therefore means the socket that
                # answered is this child's.
                if self._serving_is_this_child():
                    return
                last = "the socket answered, but not from this child"
                time.sleep(0.1)
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

    def _serving_is_this_child(self) -> bool:
        """Whether the data directory's lock file names the child just launched."""
        return (self.process is not None
                and _lock_file_pid(self.bundle) == self.process.pid)

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
           "authentication_files", "isolated_from_libpq_environment",
           "os_user", "refusal_before_connecting", "refuse_an_unsafe_tree",
           "report", "running_pid", "server_binaries", "unsupported_platform",
           "write_authentication"]
