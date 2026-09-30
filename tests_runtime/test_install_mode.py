"""`OPENDOX_INSTALL_MODE`: the local single-user install, and the hosted one
it cannot be reached from by omission (plan 034 T070; #1144 13.4, 13.5, 13.6).

HERMETIC: standard library plus `opendox.runtime.config` and the runtime CLI,
both stdlib-only at import. No database is reached: every DSN below is a
well-formed PostgreSQL URI aimed at port 1 of the loopback, so a refusal here
is always a CONFIGURATION refusal, which is the whole of what 13.4-13.6 ask of
`load_settings`.

WHAT IS RULED AND WHAT IS READ, so a reviewer can tell them apart:

  * RULED: the selector, its two values and its hosted default (#1144 13.4);
    a hosted install with no issuer refuses naming it (13.5); the hosted mode
    unchanged (13.6); local binds loopback only with no opt-in (13.4);
    `generate-and-open --local` is the same selection (R1Q15 (b), T007 batch
    H's 13.4 addendum).
  * PLAN 034's FAIL-CLOSED READING, not in #1144: a `--local` flag and an
    `OPENDOX_INSTALL_MODE` setting that disagree are refused, naming both
    (T070; `evidence/analyze-round-2.md` U2-1, V2-6).
  * HOLDER READINGS on openxFactory#656 that Brett may overrule (T070): an
    unrecognised value is refused, case-sensitively; a broker setting given
    beside `local` is refused by name; `runtime serve` refuses under `local`;
    `runtime status` under `local` reports the broker as not configured and
    does not count it as a fault.
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout

import pytest

from opendox.runtime import cli
from opendox.runtime.config import (
    HOSTED_ONLY_SETTINGS,
    INSTALL_MODE_HOSTED,
    INSTALL_MODE_LOCAL,
    INSTALL_MODES,
    LOCAL_BIND_HOSTS,
    LOCAL_FLAG,
    PREFIX,
    SETTING_NAMES,
    ConfigurationError,
    install_mode,
    load_migration_settings,
    load_settings,
    require_the_hosted_issuer,
)

MODE = PREFIX + "INSTALL_MODE"

#: Two DSNs that pass T071's three refusals — one dialect, one database, two
#: different values — so the install shape is the only thing under test.
DSNS = {
    PREFIX + "DATABASE_URL": "postgresql://serve@127.0.0.1:1/opendox",
    PREFIX + "MIGRATION_DATABASE_URL": "postgresql://migrate@127.0.0.1:1/opendox",
}
#: Every setting a HOSTED install needs, well-formed.
HOSTED = {**DSNS,
          PREFIX + "OIDC_ISSUER": "https://issuer.example.invalid/realms/fixture",
          PREFIX + "OIDC_AUDIENCE": "fixture"}


def _refusal(env: dict, **kwargs) -> str:
    try:
        load_settings(env, **kwargs)
    except ConfigurationError as exc:
        return str(exc)
    raise AssertionError(f"accepted: {env} {kwargs}")


@pytest.fixture()
def scrubbed(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """No runtime setting inherited from the shell reaches a CLI verb."""
    for name in SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _run(argv: list[str]) -> tuple[int, dict]:
    args: argparse.Namespace = cli.build_parser().parse_args(argv)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = args.func(args)
    return code, json.loads(buffer.getvalue())


# -- the selector -------------------------------------------------------------


def test_the_selector_has_two_values_and_its_default_is_hosted() -> None:
    """13.4: `local` and `hosted`, defaulting to `hosted`; UNSET is the safe one."""
    assert set(INSTALL_MODES) == {"local", "hosted"}
    assert install_mode({}) == INSTALL_MODE_HOSTED
    assert install_mode({MODE: ""}) == INSTALL_MODE_HOSTED
    assert install_mode({MODE: "   "}) == INSTALL_MODE_HOSTED
    assert install_mode({MODE: "hosted"}) == INSTALL_MODE_HOSTED
    assert install_mode({MODE: "local"}) == INSTALL_MODE_LOCAL


def test_the_flag_selects_local_exactly_as_the_setting_does() -> None:
    """R1Q15 (b), as T007 batch H's 13.4 addendum reads."""
    assert LOCAL_FLAG == "--local"
    assert install_mode({}, local_flag=True) == INSTALL_MODE_LOCAL
    assert install_mode({MODE: "local"}, local_flag=True) == INSTALL_MODE_LOCAL
    assert install_mode({MODE: "local"}) == install_mode({}, local_flag=True)


def test_a_flag_and_a_setting_that_disagree_are_refused_naming_both() -> None:
    """T070's falsifier's second half: the disagreeing pair (plan 034's reading).

    Neither explicit selection may silently override the other, in either
    direction the loader can see: the flag cannot win over a hosted setting,
    and the setting cannot win over the flag.
    """
    with pytest.raises(ConfigurationError) as caught:
        install_mode({MODE: "hosted"}, local_flag=True)
    message = str(caught.value)
    assert LOCAL_FLAG in message, message
    assert f"{MODE}=hosted" in message, message
    # ...and the same refusal on the loader every served verb goes through,
    # so the pair cannot be resolved one way here and another way there.
    assert f"{MODE}=hosted" in _refusal({**HOSTED, MODE: "hosted"},
                                        local_flag=True)


@pytest.mark.parametrize("value", ["Local", "LOCAL", "Hosted", "single-user",
                                   "locals", "loc al"])
def test_an_unrecognised_value_is_refused_naming_the_two(value: str) -> None:
    """A holder reading (#656, T070): matched case-sensitively, never guessed."""
    with pytest.raises(ConfigurationError) as caught:
        install_mode({MODE: value})
    message = str(caught.value)
    assert MODE in message and "`local`" in message and "`hosted`" in message
    # every loader reads the one selector, so every loader refuses it
    assert MODE in _refusal({**HOSTED, MODE: value})
    with pytest.raises(ConfigurationError):
        load_migration_settings({**DSNS, MODE: value})


# -- 13.5 and 13.6: the hosted install ---------------------------------------


@pytest.mark.parametrize("mode", [None, "hosted", ""])
def test_a_hosted_install_with_no_issuer_refuses_naming_it(mode) -> None:
    """13.5, set or by default, with every other hosted setting well-formed."""
    env = {k: v for k, v in HOSTED.items() if k != PREFIX + "OIDC_ISSUER"}
    if mode is not None:
        env[MODE] = mode
    assert PREFIX + "OIDC_ISSUER" in _refusal(env)
    with pytest.raises(ConfigurationError) as caught:
        require_the_hosted_issuer(env)
    assert PREFIX + "OIDC_ISSUER" in str(caught.value)
    assert LOCAL_FLAG in str(caught.value), (
        "the refusal must say how a single-user install selects local")


def test_the_hosted_issuer_is_asked_first_by_the_entry_point_check() -> None:
    """With NOTHING set, the entry point's refusal names the issuer (13.5),
    not the served DSN `load_settings` happens to ask for first."""
    with pytest.raises(ConfigurationError) as caught:
        require_the_hosted_issuer({})
    assert PREFIX + "OIDC_ISSUER" in str(caught.value)
    assert "unset" in str(caught.value)
    require_the_hosted_issuer(HOSTED)          # and a present issuer passes


def test_the_hosted_mode_is_unchanged() -> None:
    """13.6: same broker, same pinned issuer, loaded exactly as before."""
    for env in (HOSTED, {**HOSTED, MODE: "hosted"}):
        settings = load_settings(env)
        assert settings.install_mode == INSTALL_MODE_HOSTED
        assert settings.oidc_issuer == HOSTED[PREFIX + "OIDC_ISSUER"]
        assert settings.oidc_audience == "fixture"
        assert settings.jwks_url() == (HOSTED[PREFIX + "OIDC_ISSUER"]
                                       + "/protocol/openid-connect/certs")
    # and a hosted install may still bind wherever its operator says
    assert load_settings({**HOSTED, PREFIX + "BIND_HOST": "0.0.0.0"}
                         ).bind_host == "0.0.0.0"
    # and it still refuses a missing audience, as it always did
    env = {k: v for k, v in HOSTED.items() if k != PREFIX + "OIDC_AUDIENCE"}
    assert PREFIX + "OIDC_AUDIENCE" in _refusal(env)


# -- 13.4: the local install -------------------------------------------------


@pytest.mark.parametrize("selection", ["setting", "flag"])
def test_a_local_install_needs_no_broker(selection: str) -> None:
    env = dict(DSNS)
    kwargs = {}
    if selection == "setting":
        env[MODE] = "local"
    else:
        kwargs["local_flag"] = True
    settings = load_settings(env, **kwargs)
    assert settings.install_mode == INSTALL_MODE_LOCAL
    assert settings.oidc_issuer == ""
    assert settings.oidc_audience == ""
    assert settings.oidc_jwks_url is None
    # no endpoint is derived from an issuer that does not exist
    assert settings.jwks_url() == ""
    assert settings.discovery_url() == ""
    assert "install_mode='local'" in repr(settings)


@pytest.mark.parametrize("name", HOSTED_ONLY_SETTINGS)
def test_a_broker_setting_beside_the_local_mode_is_refused_by_name(
        name: str) -> None:
    """A holder reading (#656, T070): a broker setting says hosted was meant."""
    assert set(HOSTED_ONLY_SETTINGS) == {PREFIX + "OIDC_ISSUER",
                                         PREFIX + "OIDC_AUDIENCE",
                                         PREFIX + "OIDC_JWKS_URL"}
    secret = "https://svc:hunter2@broker.example.invalid/realms/x"
    message = _refusal({**DSNS, MODE: "local", name: secret})
    assert name in message, message
    assert "hunter2" not in message, "the value must not be repeated"
    # and the flag spelling of the same selection refuses it the same way
    assert name in _refusal({**DSNS, name: secret}, local_flag=True)


def test_every_broker_setting_given_is_named_at_once() -> None:
    env = {**HOSTED, MODE: "local"}
    message = _refusal(env)
    for name in (PREFIX + "OIDC_ISSUER", PREFIX + "OIDC_AUDIENCE"):
        assert name in message, message


@pytest.mark.parametrize("host", sorted(LOCAL_BIND_HOSTS))
def test_a_local_install_binds_each_loopback_spelling(host: str) -> None:
    settings = load_settings({**DSNS, MODE: "local",
                              PREFIX + "BIND_HOST": host})
    assert settings.bind_host == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.10",
                                  "127.0.0.2", "example.invalid"])
def test_a_local_install_refuses_a_non_loopback_bind_naming_the_rule(
        host: str) -> None:
    """13.4: loopback ONLY, and no opt-in. `127.0.0.2` is refused too: the
    document server does not treat it as loopback (`serve.LOOPBACK_HOSTS`),
    and the mode makes the SAME judgement at its own boundary."""
    message = _refusal({**DSNS, MODE: "local", PREFIX + "BIND_HOST": host})
    assert PREFIX + "BIND_HOST" in message, message
    assert "loopback" in message.lower(), message
    assert "no opt-in" in message.lower(), message


# -- the runtime CLI under the two modes --------------------------------------


def test_runtime_serve_refuses_under_the_local_mode(scrubbed) -> None:
    """A holder reading (#656, T070): the API's identity is the broker's.

    uvicorn and the application are STUBBED, so that a regression which
    served anyway returns at once — and fails the assertions below — instead
    of binding a real listener and blocking the suite forever (measured: the
    un-stubbed form of this case hung under exactly that mutant).
    """
    import sys
    import types

    from opendox.runtime import app as app_module

    served = []

    class _Config:
        def __init__(self, app: object, **kwargs: object) -> None:
            pass

    class _Server:
        def __init__(self, config: object) -> None:
            self.started = False

        def run(self) -> None:
            served.append(True)
            self.started = True

    stub = types.ModuleType("uvicorn")
    stub.Config, stub.Server = _Config, _Server
    scrubbed.setitem(sys.modules, "uvicorn", stub)
    scrubbed.setattr(app_module, "create_app", lambda **kwargs: object())
    for name, value in DSNS.items():
        scrubbed.setenv(name, value)
    scrubbed.setenv(MODE, "local")
    code, evidence = _run(["runtime", "serve"])
    assert served == [], "the API was started for a LOCAL install"
    assert code == 1
    assert evidence["ok"] is False
    assert evidence["refusal"] == "local-mode-has-no-broker", evidence
    assert f"generate-and-open {LOCAL_FLAG}" in evidence["message"]


def test_runtime_status_under_the_local_mode_probes_no_broker(
        scrubbed, monkeypatch: pytest.MonkeyPatch) -> None:
    """`broker_keys` is reported as not configured, and the verifier is never
    built: a local install has no broker to reach, and a status verb that
    called that a fault would exit nonzero for a healthy install."""
    from opendox.runtime import oidc

    def _no_broker(_settings):
        raise AssertionError("status built a broker verifier for a LOCAL "
                             "install, which has no broker")

    monkeypatch.setattr(oidc, "build_verifier", _no_broker)
    for name, value in DSNS.items():
        scrubbed.setenv(name, value)
    scrubbed.setenv(MODE, "local")
    code, evidence = _run(["runtime", "status", "--probe-timeout", "0.2"])
    assert evidence.get("refusal") is None, evidence
    assert evidence["broker_keys"] == "not configured (local mode)"
    assert evidence["broker_discovery"] is None
    assert evidence["settings"][MODE] == INSTALL_MODE_LOCAL
    assert evidence["settings"][PREFIX + "OIDC_ISSUER"] == ""
    assert evidence["settings"][PREFIX + "OIDC_JWKS_URL"] == ""
    # the database half (port 1, unreachable) is the ONLY reason `ok` is false
    assert evidence["database"].startswith("unreachable"), evidence
    assert code == 1


def test_runtime_status_reports_the_hosted_mode_it_loaded(scrubbed) -> None:
    for name, value in HOSTED.items():
        scrubbed.setenv(name, value)
    _code, evidence = _run(["runtime", "status", "--probe-timeout", "0.2"])
    assert evidence["settings"][MODE] == INSTALL_MODE_HOSTED
    assert evidence["broker_keys"].startswith("unreachable"), evidence
