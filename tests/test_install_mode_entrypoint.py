"""`generate-and-open`'s install shape: F13.1's refusals, run the way F13.1
runs them (plan 034 T070; #1144 13.4, 13.5, 13.6).

F13.1's refusal probes take the SAME `generate-and-open` path its local probe
takes, under `timeout 30`, and each must exit nonzero, must not be the bound's
124, and must name its rule on stderr. These cases run that path in a child
process for the same reason: a regression that silently STARTED a server
would block in-process forever, where a child is killed by the bound and the
case fails on `TimeoutExpired` instead of hanging the suite. The child is
`python -m opendox.cli`, which `cli.py`'s `__main__` block hands to the
package's `main()`, so it is the same `main()` the `opendox` console script
runs.

Each probe gives a well-formed `--repo-root` (a fresh git repository) and every
other setting its case needs, so the install shape is the only fault; and the
install shape is resolved BEFORE the repo root is scanned, so the refusal is
the install's, whatever the tree holds. No child reaches a database, a broker
or a socket.

The disagreeing flag and setting are plan 034's fail-closed reading (T070),
not a line of #1144; the rest is #1144's.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from opendox import cli as cli_mod
from opendox import serve as serve_mod
from opendox.runtime import config as runtime_config

SRC = Path(__file__).resolve().parents[1] / "src"
PREFIX = runtime_config.PREFIX
MODE = PREFIX + "INSTALL_MODE"

#: F13.1's hosted probes' environment: every setting a hosted install needs
#: EXCEPT the issuer, so the issuer is the only fault.
HOSTED_WITHOUT_ISSUER = {
    PREFIX + "DATABASE_URL": "postgresql://serve@127.0.0.1:1/opendox",
    PREFIX + "MIGRATION_DATABASE_URL": "postgresql://migrate@127.0.0.1:1/opendox",
    PREFIX + "OIDC_AUDIENCE": "fixture",
}


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """A fresh repository, as F13.1's preamble makes one.

    Made APART FROM the user's own git configuration (`GIT_CONFIG_GLOBAL`,
    `GIT_CONFIG_NOSYSTEM`), as `tests/test_checkout_head.py` makes its
    repositories, so a global signing rule or hook cannot fail the setup
    before the install-mode probe it exists for ever runs (Copilot review of
    this PR).
    """
    root = tmp_path / "plain-documents"
    root.mkdir()
    (root / "note.md").write_text("# A note\n\nPlain text.\n", encoding="utf-8")
    env = {**os.environ,
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "fixture",
           "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "commit", "-qm", "fixture"]):
        subprocess.run(argv, cwd=root, env=env, check=True)
    return root


def _probe(corpus: Path, tmp_path: Path, *extra: str,
           env: dict[str, str] | None = None) -> tuple[int, str]:
    """One bounded `generate-and-open` child: `(returncode, stderr)`."""
    child_env = {name: value for name, value in os.environ.items()
                 if name not in runtime_config.SETTING_NAMES}
    child_env.update(env or {})
    child_env["PYTHONPATH"] = os.pathsep.join(
        [str(SRC), child_env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    try:
        done = subprocess.run(
            [sys.executable, "-m", "opendox.cli", "generate-and-open",
             "--repo-root", str(corpus), "--repository", "fixture",
             "--run-dir", str(tmp_path / "run"), "--no-open", *extra],
            env=child_env, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:          # F13.1's rc 124
        raise AssertionError(
            "generate-and-open did not refuse: it was still running when the "
            "30-second bound killed it, which is a server that STARTED") from exc
    return done.returncode, done.stderr


def test_local_mode_refuses_a_non_loopback_bind_naming_the_rule(
        corpus: Path, tmp_path: Path) -> None:
    """F13.1: `OPENDOX_INSTALL_MODE=local … --host 0.0.0.0` is refused, BOUNDED,
    and stderr names loopback (13.4)."""
    rc, err = _probe(corpus, tmp_path, "--host", "0.0.0.0", "--port", "0",
                     env={MODE: "local"})
    assert rc != 0, err
    assert "loopback" in err.lower(), err
    assert "--host" in err, err


def test_the_flag_refuses_a_non_loopback_bind_exactly_as_the_setting_does(
        corpus: Path, tmp_path: Path) -> None:
    rc, err = _probe(corpus, tmp_path, runtime_config.LOCAL_FLAG,
                     "--host", "0.0.0.0")
    assert rc != 0, err
    assert "loopback" in err.lower(), err


@pytest.mark.parametrize("mode", ["hosted", None])
def test_a_hosted_or_unset_install_with_no_issuer_refuses_naming_it(
        corpus: Path, tmp_path: Path, mode) -> None:
    """F13.1's last two probes: hosted, and then the selector UNSET, each with
    every hosted setting except the issuer; each refuses, BOUNDED, naming
    `OPENDOX_OIDC_ISSUER` (13.5). The second is what proves the unset DEFAULT
    refuses exactly as `hosted` does."""
    env = dict(HOSTED_WITHOUT_ISSUER)
    if mode is not None:
        env[MODE] = mode
    rc, err = _probe(corpus, tmp_path, "--port", "0", env=env)
    assert rc != 0, err
    assert PREFIX + "OIDC_ISSUER" in err, err


def test_with_nothing_configured_the_refusal_names_the_issuer_and_the_flag(
        corpus: Path, tmp_path: Path) -> None:
    """Plan 034's requirement-13 scenario 2: with no setting at all the
    install is hosted, and the refusal is about the ISSUER and names how to
    select local — not `OPENDOX_DATABASE_URL`, which `load_settings` would
    have asked for first."""
    rc, err = _probe(corpus, tmp_path, "--port", "0")
    assert rc != 0, err
    assert PREFIX + "OIDC_ISSUER" in err, err
    assert runtime_config.LOCAL_FLAG in err, err
    assert PREFIX + "DATABASE_URL" not in err, err


def test_a_flag_and_a_setting_that_disagree_are_refused_naming_both(
        corpus: Path, tmp_path: Path) -> None:
    """T070's own case (plan 034's fail-closed reading): `--local` beside
    `OPENDOX_INSTALL_MODE=hosted`, with a COMPLETE hosted configuration, so
    either selection alone would have been accepted."""
    env = {**HOSTED_WITHOUT_ISSUER,
           PREFIX + "OIDC_ISSUER": "https://issuer.example.invalid/realms/x",
           MODE: "hosted"}
    rc, err = _probe(corpus, tmp_path, runtime_config.LOCAL_FLAG, env=env)
    assert rc != 0, err
    assert runtime_config.LOCAL_FLAG in err, err
    assert f"{MODE}=hosted" in err, err


def test_a_broker_setting_beside_the_local_flag_is_refused_by_name(
        corpus: Path, tmp_path: Path) -> None:
    rc, err = _probe(corpus, tmp_path, runtime_config.LOCAL_FLAG,
                     env={PREFIX + "OIDC_ISSUER":
                          "https://issuer.example.invalid/realms/x"})
    assert rc != 0, err
    assert PREFIX + "OIDC_ISSUER" in err, err


# -- in process: what each shape resolves to ----------------------------------


def _args(*extra: str):
    return cli_mod.build_parser().parse_args(
        ["generate-and-open", "--repo-root", "/nonexistent",
         "--repository", "fixture", *extra])


def test_the_local_shape_needs_no_broker_and_no_setting_at_all() -> None:
    """13.4: `local` needs no broker. Resolved with an EMPTY environment."""
    assert cli_mod._resolve_install_shape(
        _args(runtime_config.LOCAL_FLAG), env={}) == \
        runtime_config.INSTALL_MODE_LOCAL
    assert cli_mod._resolve_install_shape(
        _args(), env={MODE: "local"}) == runtime_config.INSTALL_MODE_LOCAL


@pytest.mark.parametrize("host", sorted(serve_mod.LOOPBACK_HOSTS))
def test_the_local_shape_accepts_each_loopback_host(host: str) -> None:
    assert cli_mod._resolve_install_shape(
        _args(runtime_config.LOCAL_FLAG, "--host", host), env={}) == \
        runtime_config.INSTALL_MODE_LOCAL


def test_a_complete_hosted_configuration_resolves_hosted_unchanged() -> None:
    """13.6: a hosted install with its broker configured serves as before."""
    env = {**HOSTED_WITHOUT_ISSUER,
           PREFIX + "OIDC_ISSUER": "https://issuer.example.invalid/realms/x"}
    assert cli_mod._resolve_install_shape(_args(), env=env) == \
        runtime_config.INSTALL_MODE_HOSTED
    # a hosted document server may still bind beyond loopback, as it always
    # could: the loopback rule is the LOCAL mode's
    assert cli_mod._resolve_install_shape(
        _args("--host", "0.0.0.0"), env=env) == \
        runtime_config.INSTALL_MODE_HOSTED


def test_the_local_bind_rule_is_the_document_servers_own_loopback_set() -> None:
    """13.4: "the same judgement at the mode's own boundary". `config` cannot
    import `serve`, so it spells the set; this holds the two equal."""
    assert runtime_config.LOCAL_BIND_HOSTS == serve_mod.LOOPBACK_HOSTS


def test_the_flag_is_declared_on_generate_and_open_and_follows_the_verb() -> None:
    """10.1: every option follows its verb; `--local` is `generate-and-open`'s."""
    assert _args(runtime_config.LOCAL_FLAG).local is True
    assert _args().local is False
    with pytest.raises(SystemExit):
        cli_mod.build_parser().parse_args(
            [runtime_config.LOCAL_FLAG, "generate-and-open", "--repo-root",
             "/x", "--repository", "fixture"])
