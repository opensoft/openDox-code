"""The LOCAL install's lifecycle, hardened (plan 034 T072; Copilot review of
openDox-code#69).

Hermetic: nothing here starts a real PostgreSQL server. The bundle's binaries
are stood in by small scripts where a phase must fail, and the entry point's
bundle is stood in where the case is the entry point's own handling. The real
server's cases are `test_bundled_postgres.py`'s.

  * which migrations a local install runs: this installation's own, never the
    working directory's, and never another installation's found by name;
  * a stale `postmaster.pid` is believed only for this data directory's
    postmaster, asked of the kernel;
  * `initdb` never leaves a half-built data directory;
  * every phase of a start fails as the one named refusal, never a traceback;
  * an interrupt anywhere in the local lifecycle is a clean stop.
"""

from __future__ import annotations

import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from opendox import cli as cli_mod
from opendox.runtime import bundle as bundle_mod
from opendox.runtime import config
from opendox.runtime.config import PREFIX

ROOT = Path(__file__).resolve().parents[1]
MODE = PREFIX + "INSTALL_MODE"
STATE = PREFIX + "STATE_DIR"
MIGRATIONS = PREFIX + "MIGRATIONS_DIR"


@pytest.fixture()
def scrubbed(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in config.SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture()
def short_state():
    """A state directory with a SHORT path (the socket's path is bounded)."""
    path = Path(tempfile.mkdtemp(prefix="odx-l-", dir="/tmp"))
    yield path
    for directory in path.rglob("*"):
        if directory.is_dir():
            directory.chmod(0o700)
    shutil.rmtree(path, ignore_errors=True)


def _local(state: Path) -> config.RuntimeSettings:
    return config.load_settings({MODE: "local", STATE: str(state)})


# -- which migrations a local install runs ------------------------------------


@pytest.fixture()
def hostile_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory whose `migrations/` holds the pinned `0001` AND SQL
    of its own: what a checkout of somebody else's repository can hold."""
    here = tmp_path / "somebody-elses-checkout"
    (here / "migrations").mkdir(parents=True)
    for sql in (ROOT / "migrations").glob("0001*.sql"):
        shutil.copy2(sql, here / "migrations" / sql.name)
    (here / "migrations" / "0099_not_this_products.sql").write_text(
        "create table stolen (secret text);\n", encoding="utf-8")
    monkeypatch.chdir(here)
    return here


def test_a_local_install_never_runs_the_working_directorys_migrations(
        hostile_cwd: Path, short_state: Path) -> None:
    settings = _local(short_state)
    found = Path(settings.migrations_dir).resolve()
    assert not found.is_relative_to(hostile_cwd.resolve()), found
    assert found == (ROOT / "migrations").resolve(), found
    migrate = config.load_migration_settings({MODE: "local", STATE: str(short_state)})
    assert Path(migrate.migrations_dir).resolve() == found


def test_a_hosted_install_keeps_its_working_directory_default(
        hostile_cwd: Path) -> None:
    """13.6: the hosted default is unchanged, and the deploy files set the
    variable explicitly."""
    assert config.migrations_dir({}) == Path("migrations")


def test_an_explicit_migrations_dir_is_used_as_given_in_either_shape(
        tmp_path: Path) -> None:
    chosen = str(tmp_path / "chosen")
    assert config.migrations_dir({MIGRATIONS: chosen}, local=True) == Path(chosen)
    assert config.migrations_dir({MIGRATIONS: chosen}) == Path(chosen)


def test_a_local_installation_that_carries_none_is_refused_naming_the_setting(
        monkeypatch: pytest.MonkeyPatch, hostile_cwd: Path) -> None:
    monkeypatch.setattr(config, "installation_migrations_dir", lambda: None)
    with pytest.raises(config.ConfigurationError) as caught:
        config.migrations_dir({}, local=True)
    assert MIGRATIONS in str(caught.value), caught.value


class _FakeFile:
    """One `importlib.metadata` RECORD entry, located under `base`."""

    def __init__(self, base: Path, relative: str) -> None:
        self.base, self.relative = base, relative
        self.name = Path(relative).name
        self.parts = Path(relative).parts

    def __fspath__(self) -> str:
        return self.relative

    def locate(self) -> Path:
        return self.base / self.relative


class _FakeDistribution:
    def __init__(self, base: Path) -> None:
        site = "lib/python3/site-packages"
        self.files = [
            _FakeFile(base, f"{site}/opendox/runtime/config.py"),
            _FakeFile(base, "share/opendox/migrations/0001_older.sql"),
        ]


def test_another_installations_record_is_not_this_ones(tmp_path: Path) -> None:
    """A distribution found by NAME whose RECORD does not hold the running
    module (an older wheel beside a checkout) is not this installation."""
    older = _FakeDistribution(tmp_path / "older-wheel")
    assert config._distribution_migrations(Path(config.__file__), older) is None


def test_the_record_of_the_distribution_that_holds_the_module_is_used(
        tmp_path: Path) -> None:
    base = tmp_path / "wheel"
    dist = _FakeDistribution(base)
    module = dist.files[0].locate()
    module.parent.mkdir(parents=True)
    module.write_text("# stand-in\n", encoding="utf-8")
    assert config._distribution_migrations(module, dist) == \
        (base / "share/opendox/migrations").resolve()


def test_the_source_tree_wins_over_a_wheel_found_by_name(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A checkout run with `src/` on the path, beside an older wheel: the
    checkout's own migrations, not the wheel's (Copilot review of
    openDox-code#69)."""
    older = _FakeDistribution(tmp_path / "older-wheel")
    monkeypatch.setattr(config.importlib.metadata, "distribution",
                        lambda name: older)
    assert config.installation_migrations_dir() == ROOT / "migrations"


def test_the_source_tree_is_asked_before_any_record(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented ORDER, pinned: even a RECORD that does hold the running
    module is asked only after the source tree it was imported from."""
    class _Holding:
        files = [_FakeFile(ROOT / "src", "opendox/runtime/config.py"),
                 _FakeFile(tmp_path, "share/opendox/migrations/0001_other.sql")]

    assert config._distribution_migrations(Path(config.__file__), _Holding()) == \
        (tmp_path / "share/opendox/migrations").resolve()
    monkeypatch.setattr(config.importlib.metadata, "distribution",
                        lambda name: _Holding())
    assert config.installation_migrations_dir() == ROOT / "migrations"


def test_a_package_outside_src_is_not_a_source_tree(tmp_path: Path) -> None:
    """A `--target` install inside some other checkout: its parent has a
    `pyproject.toml` and a `migrations/`, and it is still not this tree."""
    target = tmp_path / "checkout" / "vendor" / "opendox" / "runtime"
    target.mkdir(parents=True)
    (tmp_path / "checkout" / "pyproject.toml").write_text(
        '[project]\nname = "opendox"\n', encoding="utf-8")
    (tmp_path / "checkout" / "migrations").mkdir()
    assert config._source_tree_migrations(target / "config.py") is None


# -- a stale postmaster.pid ---------------------------------------------------


def _decoy(executable: str, cwd: Path, *argv: str) -> subprocess.Popen:
    return subprocess.Popen([executable, *argv], cwd=cwd,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _lock(bundle: config.DatabaseBundle, pid: int) -> None:
    bundle.data_dir.mkdir(parents=True, exist_ok=True)
    (bundle.data_dir / "postmaster.pid").write_text(
        f"{pid}\n{bundle.data_dir}\n", encoding="utf-8")


needs_proc = pytest.mark.skipif(not bundle_mod.PROC.joinpath("self").exists(),
                                reason="asks /proc")


@needs_proc
def test_a_recycled_pid_is_not_believed_even_with_postgres_in_its_argv(
        short_state: Path) -> None:
    """Even IN the data directory, and with `postgres -D <data dir>` in its
    argv: the executable is not `postgres`, so it is not this server."""
    bundle = config.DatabaseBundle(short_state)
    bundle.data_dir.mkdir(parents=True)
    decoy = _decoy(sys.executable, bundle.data_dir, "-c",
                   "import time; time.sleep(60)", "postgres", "-D",
                   str(bundle.data_dir))
    try:
        _lock(bundle, decoy.pid)
        assert bundle_mod.running_pid(bundle) is None
        assert bundle_mod.report(bundle)["pid"] is None
        # and the start is not refused over it: the stale lock is removed
        bundle_mod._remove_a_proven_stale_lock(bundle)
        assert not (bundle.data_dir / "postmaster.pid").exists()
    finally:
        decoy.kill()
        decoy.wait(timeout=10)


@needs_proc
def test_a_postgres_serving_another_directory_is_not_this_server(
        short_state: Path, tmp_path: Path) -> None:
    """The exact pair: an executable NAMED `postgres` is not enough, it must
    be running in THIS data directory. And the positive control: the same
    decoy, run in the data directory, is believed."""
    sleeper = shutil.which("sleep")
    assert sleeper
    named = tmp_path / "bin" / "postgres"
    named.parent.mkdir()
    shutil.copy2(sleeper, named)
    bundle = config.DatabaseBundle(short_state)
    bundle.data_dir.mkdir(parents=True)
    elsewhere = tmp_path / "another-data-dir"
    elsewhere.mkdir()
    for cwd, believed in ((elsewhere, False), (bundle.data_dir, True)):
        decoy = _decoy(str(named), cwd, "60")
        try:
            _lock(bundle, decoy.pid)
            got = bundle_mod.running_pid(bundle)
            assert got == (decoy.pid if believed else None), (cwd, got)
        finally:
            decoy.kill()
            decoy.wait(timeout=10)


def test_a_pid_nothing_can_describe_is_not_believed_and_its_lock_is_kept(
        short_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No `/proc` (macOS, the BSDs): nothing can say what the pid is, so it
    is not reported as this server, and its lock is NOT removed, since
    nothing proved it stale. PostgreSQL's own interlock is left to judge a
    start. The decoy would be believed if it could be described (the case
    above, where it is)."""
    monkeypatch.setattr(bundle_mod, "PROC", tmp_path / "no-proc")
    sleeper = shutil.which("sleep")
    assert sleeper
    named = tmp_path / "bin" / "postgres"
    named.parent.mkdir()
    shutil.copy2(sleeper, named)
    bundle = config.DatabaseBundle(short_state)
    bundle.data_dir.mkdir(parents=True)
    decoy = _decoy(str(named), bundle.data_dir, "60")
    try:
        _lock(bundle, decoy.pid)
        assert bundle_mod.running_pid(bundle) is None
        bundle_mod._remove_a_proven_stale_lock(bundle)
        assert (bundle.data_dir / "postmaster.pid").exists()
    finally:
        decoy.kill()
        decoy.wait(timeout=10)


@needs_proc
def test_a_process_that_exits_before_it_is_described_is_not_believed(
        short_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Alive at the signal check, gone by the time it is described: that is
    a stale lock, never proof of a server."""
    bundle = config.DatabaseBundle(short_state)
    gone = subprocess.Popen(["true"])
    gone.wait(timeout=10)
    _lock(bundle, gone.pid)
    monkeypatch.setattr(bundle_mod.os, "kill", lambda pid, sig: None)
    assert bundle_mod.running_pid(bundle) is None


def test_another_users_process_is_not_this_server(short_state: Path) -> None:
    """A pid the kernel will not let this user signal belongs to another user,
    and this bundle's server runs as the owner of its 0700 data directory.
    Pid 1 is another user's on an ordinary host and in CI. Where the suite
    runs as pid 1's owner, the pid is still not a postgres in this directory.
    Either way it is not believed."""
    bundle = config.DatabaseBundle(short_state)
    _lock(bundle, 1)
    assert bundle_mod.running_pid(bundle) is None


# -- the state directory, refused by name --------------------------------------


def test_a_state_dir_naming_an_unknown_user_is_refused_by_name() -> None:
    raw = "~no-such-user-odx-8f3a/state"
    with pytest.raises(config.ConfigurationError) as caught:
        config.state_dir({STATE: raw})
    assert STATE in str(caught.value), caught.value
    with pytest.raises(config.ConfigurationError):
        config.load_settings({MODE: "local", STATE: raw})
    # a HOSTED install never reads it, and is not refused over it (13.6)
    hosted = config.load_settings({
        STATE: raw, PREFIX + "DATABASE_URL": "postgresql://s@127.0.0.1:1/x",
        PREFIX + "OIDC_ISSUER": "https://issuer.example.invalid/realms/x",
        PREFIX + "OIDC_AUDIENCE": "fixture"})
    assert hosted.install_mode == config.INSTALL_MODE_HOSTED


def test_no_home_for_the_default_state_dir_is_refused_by_name(
        monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_home():
        raise RuntimeError("Could not determine home directory.")

    monkeypatch.setattr(config.Path, "home", staticmethod(_no_home))
    with pytest.raises(config.ConfigurationError) as caught:
        config.state_dir({})
    assert STATE in str(caught.value), caught.value


def test_a_relative_home_for_the_default_state_dir_is_refused_by_name(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`Path.home()` returns HOME as given; a relative one would put the
    socket wherever each process happens to run (Copilot review of #69)."""
    monkeypatch.setenv("HOME", "relative-home")
    with pytest.raises(config.ConfigurationError) as caught:
        config.state_dir({})
    assert STATE in str(caught.value) and "HOME" in str(caught.value)
    # an absolute XDG_STATE_HOME still answers without HOME at all
    assert config.state_dir({"XDG_STATE_HOME": "/srv/state"}) == \
        Path("/srv/state/opendox")


# -- libpq's environment, out of reach ---------------------------------------


def test_libpq_defaults_are_lifted_for_the_duration_and_put_back(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    monkeypatch.setenv("PGSERVICE", "no-such-service-odx")
    monkeypatch.setenv("OPENDOX_NOT_LIBPQ", "kept")
    with bundle_mod.isolated_from_libpq_environment():
        assert not [name for name in os.environ if name.startswith("PG")]
        assert os.environ["OPENDOX_NOT_LIBPQ"] == "kept"
    assert os.environ["PGHOSTADDR"] == "192.0.2.1"
    assert os.environ["PGSERVICE"] == "no-such-service-odx"


def test_the_runtime_cli_isolates_only_a_local_install(
        monkeypatch: pytest.MonkeyPatch, scrubbed) -> None:
    from opendox.runtime import cli as runtime_cli

    seen: dict = {}

    def _verb(args) -> int:
        seen["PGHOSTADDR"] = os.environ.get("PGHOSTADDR")
        return 0

    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    parser = runtime_cli.build_parser()
    monkeypatch.setattr(runtime_cli, "build_parser", lambda: parser)
    real_parse = parser.parse_args

    def _parse(argv=None):
        args = real_parse(argv)
        args.func = _verb
        return args

    monkeypatch.setattr(parser, "parse_args", _parse)
    scrubbed.setenv(MODE, "local")
    assert runtime_cli.main(["runtime", "status"]) == 0
    assert seen["PGHOSTADDR"] is None, "a local verb saw PGHOSTADDR"
    scrubbed.setenv(MODE, "hosted")
    assert runtime_cli.main(["runtime", "status"]) == 0
    assert seen["PGHOSTADDR"] == "192.0.2.1", "a hosted verb lost its libpq setting"
    assert os.environ["PGHOSTADDR"] == "192.0.2.1"


# -- the socket's path, this user's to change -----------------------------------


def _prepared(monkeypatch, tmp_path: Path, state: Path) -> bundle_mod.BundledServer:
    binaries = _binaries(tmp_path, initdb='echo "initdb reached" >&2; exit 1')
    monkeypatch.setattr(bundle_mod, "server_binaries", lambda: binaries)
    return bundle_mod.BundledServer(_local(state))


def test_a_state_dir_others_can_write_is_refused(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    short_state.chmod(0o777)
    server = _prepared(monkeypatch, tmp_path, short_state)
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "writable by every user" in str(caught.value), caught.value
    assert str(short_state) in str(caught.value)


@pytest.mark.parametrize("which", ["postgres", "run"])
def test_a_symlink_inside_the_state_tree_is_refused_and_its_target_untouched(
        monkeypatch, tmp_path: Path, short_state: Path, which: str) -> None:
    target = tmp_path / "somewhere-else"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    if which == "postgres":
        (short_state / "postgres").symlink_to(target)
    else:
        (short_state / "postgres").mkdir(mode=0o700)
        (short_state / "postgres" / "run").symlink_to(target)
    server = _prepared(monkeypatch, tmp_path, short_state)
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "symbolic link" in str(caught.value), caught.value
    assert stat.S_IMODE(target.stat().st_mode) == 0o755, "the link's target was re-moded"


def test_an_ancestor_every_user_can_write_without_the_sticky_bit_is_refused(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    open_dir = short_state / "open"
    open_dir.mkdir()
    open_dir.chmod(0o777)
    server = _prepared(monkeypatch, tmp_path, open_dir / "state")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert str(open_dir) in str(caught.value) and "not sticky" in str(caught.value)


def test_a_sticky_ancestor_is_accepted(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    """The positive control, `/tmp`'s shape: every user can write it, and it
    is sticky. The start gets past the tree and reaches `initdb`, which the
    stand-in fails on purpose."""
    sticky = short_state / "sticky"
    sticky.mkdir()
    sticky.chmod(0o1777)
    server = _prepared(monkeypatch, tmp_path, sticky / "state")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "initdb" in str(caught.value), caught.value


def test_a_group_writable_ancestor_is_refused_even_for_this_users_group(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    """A group is other users, the user's own primary group included (Copilot
    review of #69): a 0775 ancestor is refused whatever its group."""
    group = short_state / "group"
    group.mkdir()
    group.chmod(0o775)
    assert group.stat().st_gid == os.getgid()          # this user's own group
    server = _prepared(monkeypatch, tmp_path, group / "state")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert str(group) in str(caught.value) and "its group" in str(caught.value)


def test_a_link_in_a_directory_others_can_write_is_refused(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    """The configured path goes through a symbolic link, and the link sits
    in a directory every user can write. The link's TARGET is private, and
    it is still refused, because anyone could replace the link (Copilot
    review of #69)."""
    private = short_state / "private"
    private.mkdir(mode=0o700)
    open_dir = short_state / "open"
    open_dir.mkdir()
    open_dir.chmod(0o777)
    (open_dir / "link").symlink_to(private)
    server = _prepared(monkeypatch, tmp_path, open_dir / "link" / "state")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert str(open_dir) in str(caught.value) and "not sticky" in str(caught.value)


def test_this_users_own_link_to_a_private_directory_is_accepted(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    private = short_state / "private"
    private.mkdir(mode=0o700)
    (short_state / "link").symlink_to(private)
    server = _prepared(monkeypatch, tmp_path, short_state / "link" / "state")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "initdb" in str(caught.value), caught.value


def _foreign_lstat(monkeypatch, *links: Path) -> None:
    """`os.lstat` answers that each of `links` belongs to another user. A
    non-root suite cannot create another user's link, so it is stood in for
    those paths only."""
    real_lstat = os.lstat

    def _lstat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        if Path(path) in links:
            fields = list(info)
            fields[4] = os.getuid() + 4242                     # st_uid
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(bundle_mod.os, "lstat", _lstat)


def test_a_link_another_user_owns_is_refused(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    """Another user's link could be pointed elsewhere after the check. A
    non-root suite cannot create one, so its `lstat` is stood in, for that
    one path only."""
    private = short_state / "private"
    private.mkdir(mode=0o700)
    link = short_state / "link"
    link.symlink_to(private)
    _foreign_lstat(monkeypatch, link)
    server = _prepared(monkeypatch, tmp_path, link / "state")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert str(link) in str(caught.value) and "symbolic link owned by" in str(caught.value)


@pytest.mark.parametrize("umask", [0o002, 0o200])
def test_missing_directories_are_created_0700_whatever_the_umask(
        monkeypatch, tmp_path: Path, short_state: Path, umask: int) -> None:
    """A fresh default path creates the directories above the state tree
    too. Under umask 0002 `mkdir(parents=True)` would make them 0775, and
    the tree check would then refuse what this install had just made
    (Copilot review of #69). A umask that takes the owner's own bits would
    leave them unusable. Each is created exactly 0700, and the start reaches
    `initdb`, which the stand-in fails on purpose."""
    state = short_state / "a" / "b" / "state"
    server = _prepared(monkeypatch, tmp_path, state)
    previous = os.umask(umask)
    try:
        with pytest.raises(bundle_mod.BundleRefused) as caught:
            server.start()
        # The narrowed umask is the start's alone: the user's is put back.
        assert os.umask(umask) == umask, "the start left its own umask in place"
    finally:
        os.umask(previous)
    assert "initdb" in str(caught.value), caught.value
    for directory in (short_state / "a", short_state / "a" / "b", state,
                      state / "postgres", state / "postgres" / "run"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory


@pytest.mark.parametrize("shape", ["foreign-link", "foreign-broken-link",
                                   "open-ancestor", "link-in-open-dir"])
def test_nothing_is_made_through_a_path_the_tree_check_refuses(
        monkeypatch, tmp_path: Path, short_state: Path, shape: str) -> None:
    """What exists is judged BEFORE anything is created (Copilot review of
    #69). Before, the missing `postgres/run` was made through the path first
    and refused only after, so it was created in a foreign link's target, or
    beneath a directory every user can write."""
    private = short_state / "private"
    private.mkdir(mode=0o700)
    open_dir = short_state / "open"
    open_dir.mkdir()
    open_dir.chmod(0o777)
    if shape in {"foreign-link", "foreign-broken-link"}:
        target = private if shape == "foreign-link" else private / "gone"
        state = short_state / "link"
        state.symlink_to(target)
        _foreign_lstat(monkeypatch, state)
        expected, made = "symbolic link owned by", target / "postgres"
    elif shape == "open-ancestor":
        state = open_dir / "state"
        expected, made = "not sticky", state
    else:
        (open_dir / "link").symlink_to(private)
        state = open_dir / "link" / "state"
        expected, made = "not sticky", private / "state"
    server = _prepared(monkeypatch, tmp_path, state)
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert expected in str(caught.value), caught.value
    assert not os.path.lexists(made), f"{made} was made before the refusal"


@pytest.mark.parametrize("shape", ["link", "foreign-directory"])
def test_a_name_put_in_the_way_first_is_refused_never_followed(
        monkeypatch, tmp_path: Path, short_state: Path, shape: str) -> None:
    """The race in a sticky directory, `/tmp`'s shape (Copilot review of
    #69): every user can create a name there, so another user can put the
    state directory's name in place between the check and the `mkdir`. The
    stand-in `mkdir` plays that user, once. The name is refused, and nothing
    is made through it or beneath it, nor is it re-moded."""
    sticky = short_state / "sticky"
    sticky.mkdir()
    sticky.chmod(0o1777)
    state = sticky / "state"
    target = tmp_path / "somewhere-else"
    target.mkdir(mode=0o755)
    target.chmod(0o755)
    real_mkdir, real_fstat = os.mkdir, os.fstat
    planted: dict = {}

    def _mkdir(path, mode=0o777, *, dir_fd=None):
        if dir_fd is not None and path == state.name and not planted:
            if shape == "link":
                os.symlink(target, path, dir_fd=dir_fd)
            else:
                real_mkdir(path, 0o755, dir_fd=dir_fd)
                os.chmod(state, 0o755)
            planted["inode"] = os.lstat(state).st_ino
            raise FileExistsError(path)
        return real_mkdir(path, mode, dir_fd=dir_fd)

    def _fstat(descriptor):
        info = real_fstat(descriptor)
        if info.st_ino == planted.get("inode"):
            fields = list(info)
            fields[4] = os.getuid() + 4242                     # st_uid
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(bundle_mod.os, "mkdir", _mkdir)
    monkeypatch.setattr(bundle_mod.os, "fstat", _fstat)
    server = _prepared(monkeypatch, tmp_path, state)
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert planted, "the stand-in never ran: the state directory was not made by descriptor"
    message = str(caught.value)
    assert str(state) in message, message
    assert ("is a symbolic link" if shape == "link"
            else "is owned by uid") in message, message
    beneath = target if shape == "link" else state
    assert not (beneath / "postgres").exists(), "made beneath the planted name"
    assert stat.S_IMODE(os.stat(beneath).st_mode) == 0o755, "the planted name was re-moded"


@pytest.mark.parametrize("shape", ["link", "broken-link", "open"])
def test_a_data_directory_that_is_not_this_installs_own_is_refused(
        monkeypatch, tmp_path: Path, short_state: Path, shape: str) -> None:
    """An existing `data` joins the tree check (Copilot review of #69): as a
    link to a cluster elsewhere, as a broken link, or as a directory others
    can write. It is refused before anything is written into it or launched
    on it."""
    elsewhere = tmp_path / "cluster-elsewhere"
    (short_state / "postgres").mkdir(mode=0o700)
    data = short_state / "postgres" / "data"
    if shape in {"link", "open"}:
        target = elsewhere if shape == "link" else data
        target.mkdir(mode=0o700)
        (target / "PG_VERSION").write_text("16\n", encoding="utf-8")
    if shape in {"link", "broken-link"}:
        data.symlink_to(elsewhere)
    if shape == "open":
        data.chmod(0o777)
    server = _prepared(monkeypatch, tmp_path, short_state)
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    message = str(caught.value)
    assert str(data) in message, message
    assert ("symbolic link" if shape != "open" else "writable by every user") \
        in message, message
    if shape == "link":
        assert not (elsewhere / "pg_hba.conf").exists(), "wrote into the link's target"


@pytest.mark.parametrize("variable", [STATE, "XDG_STATE_HOME"])
def test_parent_traversal_in_the_state_path_is_refused(variable: str) -> None:
    value = "/tmp/odx-a/../odx-b"
    with pytest.raises(config.ConfigurationError) as caught:
        config.state_dir({variable: value})
    assert "`..`" in str(caught.value), caught.value


# -- the two refusal classes, each with its own reason --------------------------


def test_a_dsn_beside_local_is_refused_for_the_database_not_a_broker() -> None:
    with pytest.raises(config.ConfigurationError) as caught:
        config.load_settings({MODE: "local",
                              PREFIX + "DATABASE_URL": "postgresql://s@h.invalid/x"})
    message = str(caught.value)
    assert PREFIX + "DATABASE_URL" in message and "bundles" in message, message
    assert "broker" not in message and "authentication" not in message, message


def test_a_broker_setting_beside_local_is_refused_for_the_broker() -> None:
    with pytest.raises(config.ConfigurationError) as caught:
        config.load_settings({MODE: "local",
                              PREFIX + "OIDC_AUDIENCE": "fixture"})
    message = str(caught.value)
    assert PREFIX + "OIDC_AUDIENCE" in message, message
    assert "broker" in message and "authentication" in message, message
    assert "bundles" not in message, message


def test_both_classes_together_name_both_reasons() -> None:
    with pytest.raises(config.ConfigurationError) as caught:
        config.load_settings({
            MODE: "local", PREFIX + "OIDC_ISSUER": "https://i.invalid/r/x",
            PREFIX + "MIGRATION_DATABASE_URL": "postgresql://m:hunter2@h.invalid/x"})
    message = str(caught.value)
    for fragment in (PREFIX + "OIDC_ISSUER", PREFIX + "MIGRATION_DATABASE_URL",
                     "authentication", "bundles"):
        assert fragment in message, (fragment, message)
    assert "hunter2" not in message


@pytest.mark.parametrize("found", ["absent", "no-locations"])
def test_a_missing_server_package_is_the_named_refusal(
        monkeypatch: pytest.MonkeyPatch, found: str) -> None:
    """No `pixeltable_pgserver` at all, or a spec with no location: both are
    the one refusal naming the `local` extra, never an `IndexError`."""
    import importlib.machinery

    spec = None
    if found == "no-locations":
        spec = importlib.machinery.ModuleSpec(bundle_mod.SERVER_PACKAGE, None,
                                              is_package=True)
        spec.submodule_search_locations = []
    monkeypatch.setattr(bundle_mod.importlib.util, "find_spec",
                        lambda name: spec)
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        bundle_mod.server_binaries()
    assert 'opendox[local]' in str(caught.value), caught.value


# -- peer authentication, hermetic ----------------------------------------------


def test_the_authentication_files_admit_one_os_user_as_the_two_roles() -> None:
    files = bundle_mod.authentication_files("alice")
    active = {name: [line.split() for line in text.splitlines()
                     if line.strip() and not line.startswith("#")]
              for name, text in files.items()}
    assert active["pg_hba.conf"] == [
        ["local", "all", "all", "peer", f"map={bundle_mod.IDENT_MAP}"],
        ["host", "all", "all", "0.0.0.0/0", "reject"],
        ["host", "all", "all", "::/0", "reject"]]
    assert active["pg_ident.conf"] == [
        [bundle_mod.IDENT_MAP, '"alice"', config.BUNDLE_OWNER_ROLE],
        [bundle_mod.IDENT_MAP, '"alice"', config.BUNDLE_SERVED_ROLE]]
    assert "trust" not in " ".join(" ".join(r) for rows in active.values() for r in rows)


def test_the_files_are_written_0600_and_replace_what_was_there(
        tmp_path: Path) -> None:
    (tmp_path / "pg_hba.conf").write_text("local all all trust\n")
    bundle_mod.write_authentication(tmp_path, "alice")
    for name, content in bundle_mod.authentication_files("alice").items():
        assert (tmp_path / name).read_text(encoding="utf-8") == content
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pg_hba.conf", "pg_ident.conf"]


@pytest.mark.parametrize("name", ["/regex", 'quo"te', "has space", "hash#tag", ""])
def test_an_os_user_name_the_map_cannot_hold_plainly_is_refused(
        monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    import pwd

    class _Entry:
        pw_name = name

    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _Entry())
    with pytest.raises(bundle_mod.BundleRefused):
        bundle_mod.os_user()


def test_a_uid_with_no_password_entry_is_refused_by_name(
        monkeypatch: pytest.MonkeyPatch) -> None:
    import pwd

    def _missing(uid):
        raise KeyError(uid)

    monkeypatch.setattr(pwd, "getpwuid", _missing)
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        bundle_mod.os_user()
    assert "password database" in str(caught.value)


def test_initdb_is_asked_for_peer_and_host_reject(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    """The flags `initdb` receives, recorded by a stand-in: local is `peer`,
    host is `reject`, and `trust` is not asked for anywhere."""
    record = tmp_path / "initdb-argv"
    server = _server(monkeypatch, tmp_path, short_state, initdb=(
        f'echo "$@" > "{record}"\nexit 1'))
    with pytest.raises(bundle_mod.BundleRefused):
        server.start()
    argv = record.read_text(encoding="utf-8").split()
    assert "--auth-local=peer" in argv and "--auth-host=reject" in argv, argv
    assert not [a for a in argv if "trust" in a], argv


# -- initdb, and every phase of a start ---------------------------------------


def _binaries(tmp_path: Path, *, initdb: str, postgres: str = "exit 0") -> Path:
    """Stand-in `initdb` and `postgres` scripts, executable."""
    directory = tmp_path / "fake-bin"
    directory.mkdir()
    for name, body in (("initdb", initdb), ("postgres", postgres)):
        script = directory / name
        script.write_text(body if body.startswith("#!") else
                          f"#!/bin/sh\n{body}\n", encoding="utf-8")
        script.chmod(0o755)
    return directory


def _server(monkeypatch, tmp_path: Path, state: Path, **scripts) -> bundle_mod.BundledServer:
    binaries = _binaries(tmp_path, **scripts)
    monkeypatch.setattr(bundle_mod, "server_binaries", lambda: binaries)
    return bundle_mod.BundledServer(_local(state))


def _target_of_initdb() -> str:
    """Shell: the directory `initdb -D <dir>` was told to initialize."""
    return 'while [ "$1" != "-D" ]; do shift; done; T="$2"'


def test_an_initdb_that_dies_midway_leaves_no_data_directory(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    """The half-built cluster: `PG_VERSION` written, then the run fails. The
    data directory must not exist afterwards, so the next start initializes
    again instead of launching the remains (Copilot review of #69)."""
    server = _server(monkeypatch, tmp_path, short_state, initdb=(
        f'{_target_of_initdb()}\necho 16 > "$T/PG_VERSION"\n'
        'mkdir -p "$T/base"\necho "initdb: killed" >&2\nexit 1'))
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "initdb" in str(caught.value)
    data = server.bundle.data_dir
    assert not data.exists(), sorted(p.name for p in data.iterdir())
    leftovers = list(data.parent.glob(f"{bundle_mod.BundledServer.ATTEMPT_PREFIX}*"))
    assert leftovers == [], leftovers


def test_an_abandoned_attempt_is_removed_and_a_live_ones_is_kept(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    server = _server(monkeypatch, tmp_path, short_state, initdb="exit 1")
    parent = server.bundle.data_dir.parent
    parent.mkdir(parents=True)
    dead = subprocess.Popen(["true"])
    dead.wait(timeout=10)
    abandoned = parent / f"{server.ATTEMPT_PREFIX}{dead.pid}-x"
    live = parent / f"{server.ATTEMPT_PREFIX}{os.getpid()}-y"
    for attempt in (abandoned, live):
        attempt.mkdir()
        (attempt / "PG_VERSION").write_text("16\n", encoding="utf-8")
    with pytest.raises(bundle_mod.BundleRefused):
        server.start()
    assert not abandoned.exists()
    assert live.exists(), "a concurrent start's attempt was removed"


def test_a_data_directory_that_is_not_a_cluster_is_refused_and_left_alone(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    server = _server(monkeypatch, tmp_path, short_state, initdb="exit 0")
    data = server.bundle.data_dir
    data.mkdir(parents=True)
    (data / "somebody-elses-file").write_text("keep me\n", encoding="utf-8")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert str(data) in str(caught.value) and STATE in str(caught.value)
    assert (data / "somebody-elses-file").read_text(encoding="utf-8") == "keep me\n"


def test_an_initdb_that_hangs_is_the_named_refusal_not_a_traceback(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    monkeypatch.setattr(bundle_mod, "START_TIMEOUT_SECONDS", 0.5)
    server = _server(monkeypatch, tmp_path, short_state, initdb="exec sleep 30")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "initializing its data directory: TimeoutExpired" in str(caught.value)
    assert not server.bundle.data_dir.exists()


def test_a_launch_that_cannot_exec_is_the_named_refusal(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    server = _server(monkeypatch, tmp_path, short_state,
                     initdb=f'{_target_of_initdb()}\necho 16 > "$T/PG_VERSION"',
                     postgres="#!/nonexistent/interpreter\n")
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "launching it: FileNotFoundError" in str(caught.value), caught.value
    assert server.process is None


def test_directories_it_cannot_make_are_the_named_refusal(
        monkeypatch, tmp_path: Path, short_state: Path) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:        # pragma: no cover
        pytest.skip("root ignores directory modes")
    locked = short_state / "locked"
    locked.mkdir(mode=0o500)
    binaries = _binaries(tmp_path, initdb="exit 0")
    monkeypatch.setattr(bundle_mod, "server_binaries", lambda: binaries)
    server = bundle_mod.BundledServer(_local(locked / "state"))
    with pytest.raises(bundle_mod.BundleRefused) as caught:
        server.start()
    assert "preparing its directories: PermissionError" in str(caught.value)


# -- an interrupt anywhere in the local lifecycle -------------------------------


@pytest.fixture()
def local_entry(scrubbed, monkeypatch, tmp_path: Path):
    """`cmd_generate_and_open --local` with its bundle stood in. The corpus
    checks are not under test here and pass whatever the root."""
    scrubbed.setenv(MODE, "local")
    scrubbed.setenv(STATE, "/tmp/odx-never-created")
    monkeypatch.setattr(cli_mod, "_refuse_non_corpus_repo_root", lambda args: None)
    monkeypatch.setattr(cli_mod, "_refuse_malformed_generated_at", lambda args: None)
    stopped: list[int] = []
    behaviour: dict = {}

    class _StandIn:
        applied: list = []

        def __init__(self, settings) -> None:
            pass

        def start(self):
            behaviour.get("start", lambda: None)()
            return self

        def stop(self) -> None:
            stopped.append(1)

        def report(self) -> dict:
            return {"data_dir": None, "socket_dir": "(stood in)", "pid": None}

    monkeypatch.setattr(cli_mod.bundle_mod, "BundledServer", _StandIn)
    args = cli_mod.build_parser().parse_args(
        ["generate-and-open", config.LOCAL_FLAG, "--repo-root", str(tmp_path),
         "--repository", "fixture", "--no-open", "--no-serve"])
    return args, behaviour, stopped


def _entry(args) -> int:
    """The entry point, with an ESCAPING interrupt turned into a failure: one
    that reached pytest would abort the whole session, not fail this case."""
    try:
        return cli_mod.cmd_generate_and_open(args, opener=lambda url: None)
    except KeyboardInterrupt as escaped:
        raise AssertionError(
            f"the interrupt escaped the entry point ({type(escaped).__name__}), "
            "which is a traceback and not a clean stop") from None


def _sigterm_to_self() -> None:
    os.kill(os.getpid(), signal.SIGTERM)
    for _ in range(500):             # the handler runs between two bytecodes
        time.sleep(0.01)
    raise AssertionError("SIGTERM was not delivered")   # pragma: no cover


def test_a_sigterm_while_the_bundle_starts_is_a_clean_stop(
        local_entry, capsys) -> None:
    args, behaviour, stopped = local_entry
    before = signal.getsignal(signal.SIGTERM)
    behaviour["start"] = _sigterm_to_self
    rc = _entry(args)
    assert rc == 128 + signal.SIGTERM
    assert "interrupted (SIGTERM)" in capsys.readouterr().err
    assert stopped == [1], "the bundle was not stopped"
    assert signal.getsignal(signal.SIGTERM) == before, "the handler was not restored"


def test_a_ctrl_c_while_the_snapshot_is_generated_is_a_clean_stop(
        local_entry, monkeypatch, capsys) -> None:
    args, _behaviour, stopped = local_entry

    def _interrupted(args, *, opener):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_mod, "_generate_and_open", _interrupted)
    rc = _entry(args)
    assert rc == 128 + signal.SIGINT
    assert "interrupted (SIGINT)" in capsys.readouterr().err
    assert stopped == [1]
