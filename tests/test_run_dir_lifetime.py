"""`generate-and-open`'s minted run directory is removed when the run is done
with it, and is named for openDox (plan 034 T084, adversarial review 2, G7).

With no `--run-dir`, the verb mints a temporary directory, writes the snapshot
there and serves it. It used to be minted as `ideation-dashboard-*`, which is
openxFactory's pre-carve name, and it was never removed: every run left one
under the system's temporary directory. Now it is minted as
`cli.RUN_DIR_PREFIX` (`opendox-`), and it is removed however the run ends: a
served run stopped by an interrupt, a `--no-serve` run, a refusal. A
`--run-dir` the caller names is the caller's, and is kept.

Each case is a child process, `python -m opendox.cli generate-and-open` over
the plain fixture, with its own TMPDIR so its temporary directories can be
counted. It is a HOSTED install, with a hosted install's settings given on
purpose (`Child(extra_env=)`), so no database is started: the run directory's
lifetime is the same in both install shapes.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import re
from pathlib import Path

from opendox.runtime import config as runtime_config
from standalone_child import Child, fresh_repository

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
PREFIX = runtime_config.PREFIX

#: A hosted install's settings, as `tests/test_served_install_block.py`
#: gives them. Nothing in these cases connects to either database.
HOSTED = {
    PREFIX + "INSTALL_MODE": runtime_config.INSTALL_MODE_HOSTED,
    PREFIX + "DATABASE_URL": "postgresql://serve@127.0.0.1:1/opendox",
    PREFIX + "MIGRATION_DATABASE_URL": "postgresql://migrate@127.0.0.1:1/opendox",
    PREFIX + "OIDC_AUDIENCE": "fixture",
    PREFIX + "OIDC_ISSUER": "https://issuer.example.invalid/realms/fixture",
}

_URL = re.compile(r"^(http://([0-9.]+):([0-9]+))/index\.html$")


def _setup(tmp_path: Path) -> tuple[Path, Path, dict]:
    repo = fresh_repository(PLAIN, tmp_path)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    return repo, scratch, {**HOSTED, "TMPDIR": str(scratch)}


def _minted(scratch: Path) -> list[Path]:
    return sorted(p for p in scratch.iterdir() if p.is_dir())


def test_a_served_run_names_its_run_dir_for_opendox_and_removes_it_at_stop(
        tmp_path) -> None:
    from opendox import cli
    repo, scratch, env = _setup(tmp_path)
    child = Child(tmp_path, "opendox.cli", "generate-and-open",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--port", "0", extra_env=env)
    try:
        child.wait_for_line(_URL)
        (minted,) = _minted(scratch)
        assert cli.RUN_DIR_PREFIX == "opendox-"
        assert minted.name.startswith("opendox-"), minted.name
        assert (minted / "snapshot.json").is_file(), "it is the run's own"
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert _minted(scratch) == [], "the minted run directory outlived the run"
    assert child.refused() == [], child.refused()


def test_a_no_serve_run_removes_its_minted_run_dir(tmp_path) -> None:
    repo, scratch, env = _setup(tmp_path)
    child = Child(tmp_path, "opendox.cli", "generate-and-open",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--no-serve", "--port", "0", extra_env=env)
    try:
        assert child.wait() == 0, child.stderr_text()
    finally:
        child.kill()
    assert _minted(scratch) == []


def test_a_run_dir_the_caller_names_is_kept(tmp_path) -> None:
    repo, scratch, env = _setup(tmp_path)
    run_dir = tmp_path / "kept"
    child = Child(tmp_path, "opendox.cli", "generate-and-open",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--no-serve", "--port", "0",
                  "--run-dir", str(run_dir), extra_env=env)
    try:
        assert child.wait() == 0, child.stderr_text()
    finally:
        child.kill()
    assert (run_dir / "snapshot.json").is_file()
    assert _minted(scratch) == []
