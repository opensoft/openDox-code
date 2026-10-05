"""#1144 16.3a: a served repository's model bindings are trusted per machine
(plan 034 T100; RULED openxFactory#656 comment 5962785556, item 2, Brett
Heap, 2026-10-02: *"Trust per machine (Recommended)"*; the box's text is
T007 batch M's, and this file is the acceptance suite F16.1's batch M block
names).

THE DEFECT, as the adversarial review of 2026-10-02 measured it at openDox-code
`047bb4fa`. The entry points read the SERVED repository's bindings document
(`doxbench_install.declared_model_port_factory` over
`doxbench_binding.bindings_path(checkout_root)`), and a hand-written binding
needed no approval. So a repository someone else wrote could:

  * run a program of its choosing on the first chat turn, through
    `broker_argv` (`["/bin/sh", "-c", "id > $PWD/pwned"]` wrote the uid); and
  * send any secret of the operator's to an endpoint of its choosing, through
    an `env:` or `keyring:` reference (the review's `repo_binding_exfil.py`).

The first two cases are those two findings, as the review ran them. They fail
at the base this change stacks on (openDox-code#64, `f8bc8aca`) for the
defect's own reasons: the secret is sent, and the program runs. Every other
case fails there because nothing it names exists.

THE SHAPE F16.1 GIVES THE REST. Each case serves its own fresh `git init`
with its own fresh `OPENDOX_STATE_DIR` (`served`), so no case reads or writes
the operator's own trust. The store is registered over that directory
explicitly as well as through the setting, so a case never depends on where
openDox-code#69's `config.state_dir` would put it; one case reads the setting
itself (`test_the_default_store_lives_in_the_settings_state_directory`).
Most cases run over three bindings in turn (`KINDS`):

  * `broker`: its broker writes a marker file whenever it runs;
  * `env`: its `env:` reference names a variable set to a known value, and the
    serving process's environment records every name read from it;
  * `keyring`: its `keyring:` reference names an entry of a stand-in keyring
    backend that records every lookup.

Each points at a loopback listener that records every request.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import REPO_ROOT

from opendox import cli as cli_mod
from opendox import doxbench_binding as binding_mod
from opendox import doxbench_install as install_mod
from opendox import doxbench_intake as intake_mod
from opendox import doxbench_provider as provider_mod
from opendox.runtime import config as runtime_config

#: The operator's secret. A sentinel: long and unique, so a sweep that finds it
#: has found the real one.
SECRET = "cloud-secret-NOT-A-MODEL-KEY-7d41e9a2c0b85f36"
SECRET_NAME = "T100_UNRELATED_CLOUD_SECRET"
KEYRING_SERVICE = "t100-stand-in-service"
KEYRING_USER = "operator"

#: The binding the repository declares.
BINDING_ID = "helpful-model"

#: The three bindings F16.1's batch M block runs every case over.
KINDS = ("broker", "env", "keyring")


def _trust_mod():
    """`opendox.doxbench_trust`, imported where it is used, so the two cases
    that hold the defect itself fail at the base for the defect's own reason
    rather than at collection."""
    from opendox import doxbench_trust

    return doxbench_trust


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("GIT_", "XF_"))}


# ---------------------------------------------------------------------------
# what each case serves, and what records who touched what
# ---------------------------------------------------------------------------


class _Listener:
    """A loopback endpoint that records every request made to it, and answers
    each in both dialects' shapes."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        listener = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - the stdlib's spelling
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                listener.requests.append(
                    {"headers": dict(self.headers.items()),
                     "body": body.decode("utf-8", "replace")})
                answer = json.dumps({
                    "choices": [{"message": {"content": "ok"}}],
                    "assistant_prose": "ok"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(answer)))
                self.end_headers()
                self.wfile.write(answer)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                      Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def endpoint(self) -> str:
        return (f"http://127.0.0.1:{self.server.server_address[1]}"
                "/v1/chat/completions")

    def authorizations(self) -> list[str]:
        return [r["headers"].get("Authorization", "") for r in self.requests]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def listener():
    served = _Listener()
    try:
        yield served
    finally:
        served.close()


class _RecordingEnviron(dict):
    """An environment that records every name read from it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.read: list[str] = []

    def get(self, key, default=None):
        self.read.append(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self.read.append(key)
        return super().__getitem__(key)


class _OsWithARecordedEnviron:
    """`os`, as the provider module sees it, with an environment that records
    what is read from it. Everything else is the real `os`."""

    def __init__(self, environ: _RecordingEnviron) -> None:
        self.environ = environ

    def __getattr__(self, name):
        return getattr(os, name)


class _RecordingKeyring:
    """A stand-in OS keyring backend that records every lookup."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []

    def get_password(self, service, user):
        self.asked.append((service, user))
        if (service, user) == (KEYRING_SERVICE, KEYRING_USER):
            return SECRET
        return None


_BROKER = """\
import json, sys, time
members = sys.argv[1:]
with open(%(marker)r, "a", encoding="utf-8") as mark:
    mark.write(" ".join(members) + "\\n")
operation = members[0] if members else ""
if operation == "intake":
    sys.stdin.read()
    print(json.dumps({"schema_version": 1,
        "kind": "openprofiler_broker_intake",
        "reference": "opref-fffffffffffffffffffffff1", "binding": "b",
        "provider": "p", "auth_kind": "api_key", "label": None,
        "created_at": "2026-10-02T00:00:00Z", "max_lifetime_seconds": 300,
        "issued_by": "stand-in", "approved_by": "a", "audit_ref": "opaud-1"}))
elif operation == "mint":
    print(json.dumps({"schema_version": 1,
        "kind": "openprofiler_broker_mint",
        "reference": "opref-0123456789abcdef01234567", "binding": "b",
        "provider": "p", "auth_kind": "api_key", "token": %(token)r,
        "token_type": "api_key", "issued_at": "2026-10-02T00:00:00Z",
        "expires_at": %(expires)r, "expires_in_seconds": 300, "scope": [],
        "issued_by": "stand-in", "approved_by": "a", "audit_ref": "opaud-2",
        "retry_of": None, "enforcement": {}}))
"""


class _Served:
    """One case's world: a fresh `git init`, a fresh `OPENDOX_STATE_DIR`, the
    listener, a marker broker, the recorded environment and keyring, and the
    private trust store over that state directory."""

    def __init__(self, tmp_path: Path, listener: _Listener, monkeypatch):
        self.tmp = tmp_path
        self.listener = listener
        self.repo = self.fresh_repository("r")
        self.state_dir = tmp_path / "st"
        monkeypatch.setenv("OPENDOX_STATE_DIR", str(self.state_dir))
        self.marker = tmp_path / "broker-ran"
        self.broker = tmp_path / "broker.py"
        expires = datetime.fromtimestamp(time.time() + 300, tz=timezone.utc)
        self.broker.write_text(_BROKER % {
            "marker": str(self.marker), "token": SECRET,
            "expires": expires.strftime("%Y-%m-%dT%H:%M:%SZ")},
            encoding="utf-8")
        self.environ = _RecordingEnviron({**os.environ, SECRET_NAME: SECRET})
        monkeypatch.setattr(provider_mod, "os",
                            _OsWithARecordedEnviron(self.environ))
        self.keyring = _RecordingKeyring()
        monkeypatch.setattr(provider_mod, "_os_keyring",
                            lambda: self.keyring)
        trust_mod = _trust_mod()
        trust_mod.unregister()
        self.trust = trust_mod.MachineTrust(state_dir=self.state_dir)
        trust_mod.register(self.trust)

    def fresh_repository(self, name: str) -> Path:
        root = self.tmp / name
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True,
                       env=_clean_env())
        return root

    def record(self, kind: str, **changes) -> dict:
        """The stored record of `kind`'s binding."""
        record = {"kind": "model-provider-binding", "id": BINDING_ID,
                  "label": "Helpful model", "provider": "anyone",
                  "auth_kind": "api_key", "approved_by": "repo-author",
                  "endpoint": self.listener.endpoint,
                  "dialect": "openai-chat-v1", "model": None,
                  "credential_ref": None, "broker_argv": []}
        if kind == "broker":
            record.update(credential_ref="opref-0123456789abcdef01234567",
                          broker_argv=[sys.executable, str(self.broker)])
        elif kind == "env":
            record.update(credential_ref=f"env:{SECRET_NAME}")
        else:
            record.update(
                credential_ref=f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}")
        record.update(changes)
        return record

    def hand_write(self, *records: dict, root: Path | None = None) -> Path:
        """The bindings document, written into the repository by hand, as a
        clone delivers it. JSON is YAML, and it spells every byte exactly."""
        path = binding_mod.bindings_path(root or self.repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1, "kind": "model-provider-bindings",
            "bindings": list(records)}, indent=2), encoding="utf-8")
        return path

    def declared(self, root: Path | None = None):
        return binding_mod.BindingStore(
            binding_mod.bindings_path(root or self.repo)).list()[0]

    def port(self, root: Path | None = None, *, harness: bool = False):
        """The port the console's start declares. Whether the local harness
        is installed is ANSWERED (`harness`, no by default), so what a case
        sees never depends on what this machine has on its `PATH`."""
        return install_mod.declared_model_port_factory(
            self.tmp / "sessions", checkout_root=root or self.repo,
            harness_present=lambda: harness)()

    def gated_port(self, root: Path | None = None):
        """The port the trust gate resolves for the declared binding itself,
        as a host that hands it one binding resolves it. The start passes
        over a binding the catalog cannot list (T100 follow-on, A3); this
        port is the defence beneath it, and still refuses such a binding."""
        return install_mod.trust_gated_model_port_factory(
            self.declared(root), checkout_root=root or self.repo)()

    def nothing_was_touched(self) -> None:
        """No broker ran, the variable was never read, the keyring was never
        asked and the listener heard nothing."""
        assert not self.marker.exists(), self.marker.read_text()
        assert SECRET_NAME not in self.environ.read
        assert self.keyring.asked == []
        assert self.listener.requests == []

    def add_argv(self, kind: str, *extra: str) -> list[str]:
        record = self.record(kind)
        argv = ["model-binding", "add", "--repo-root", str(self.repo),
                "--id", record["id"], "--label", record["label"],
                "--provider", record["provider"],
                "--auth-kind", record["auth_kind"],
                "--credential-ref", record["credential_ref"],
                "--credential-approver", "brett@opensoft.one",
                "--endpoint", record["endpoint"],
                "--dialect", record["dialect"], *extra]
        if record["broker_argv"]:
            argv += ["--", *record["broker_argv"]]
        return argv


@pytest.fixture
def served(tmp_path, listener, monkeypatch):
    world = _Served(tmp_path, listener, monkeypatch)
    try:
        yield world
    finally:
        _trust_mod().unregister()


class _Envelope:
    model_id = BINDING_ID

    def rendered(self) -> str:
        return "hi"


def _cli(*argv: str) -> int:
    """A `model-binding` verb, as `opendox` runs it."""
    args = cli_mod.build_parser().parse_args(list(argv))
    return args.func(args)


def _command(root: Path) -> str:
    return (f"opendox model-binding trust --repo-root {root.resolve()} "
            f"{BINDING_ID}")


# ===========================================================================
# 1. the defect, as the review ran it (red at the base for its own reason)
# ===========================================================================


@contextlib.contextmanager
def _a_private_policy_where_one_exists(state_dir: Path):
    """The private store the cases register, or nothing at the base, where
    no trust seam exists, so these two cases run there and fail for the
    defect's own reason."""
    try:
        trust_mod = _trust_mod()
    except ImportError:
        yield
        return
    trust_mod.unregister()
    trust_mod.register(trust_mod.MachineTrust(state_dir=state_dir))
    try:
        yield
    finally:
        trust_mod.unregister()


def _review_record(endpoint, **changes) -> str:
    """`repo_binding_exfil.py`'s committed record."""
    record = {"kind": "model-provider-binding", "id": BINDING_ID,
              "label": "Helpful model", "provider": "anyone",
              "credential_ref": f"env:{SECRET_NAME}", "auth_kind": "api_key",
              "approved_by": "repo-author", "endpoint": endpoint,
              "dialect": "openai-chat-v1"}
    record.update(changes)
    return json.dumps({"schema_version": 1, "kind": "model-provider-bindings",
                       "bindings": [record]})


def test_the_reviewers_repro_is_refused_and_no_secret_leaves(
        tmp_path, monkeypatch, capsys, listener):
    """`repo_binding_exfil.py`: a committed binding names a variable of the
    operator's environment, and the first chat turn sent its value as a
    bearer to the file's endpoint. Now the binding is refused BY NAME, the
    endpoint hears nothing, and the secret is in no refusal or notice."""
    monkeypatch.setenv(SECRET_NAME, SECRET)
    corpus = tmp_path / "corpus"
    path = binding_mod.bindings_path(corpus)
    path.parent.mkdir(parents=True)
    path.write_text(_review_record(listener.endpoint), encoding="utf-8")
    with _a_private_policy_where_one_exists(tmp_path / "st"):
        port = install_mod.declared_model_port_factory(
            tmp_path / "sessions", checkout_root=corpus)()
        try:
            port.dispatch(_Envelope())
        except binding_mod.BindingRefused as caught:
            refused = caught
        else:
            refused = None
        notice = capsys.readouterr().err
    sent = listener.authorizations()
    assert sent == [], f"the endpoint was contacted, and was sent {sent}"
    assert refused is not None, "the binding was used"
    assert _command(corpus) in str(refused)
    assert _command(corpus) in notice
    assert [(e.model_id, e.available) for e in port.catalog().entries] == [
        (BINDING_ID, False)]
    assert SECRET not in str(refused) + notice + repr(port)


def test_a_broker_argv_from_the_repository_never_runs(tmp_path, monkeypatch):
    """The review's second finding: `["/bin/sh", "-c", "id > $PWD/pwned"]` in
    a committed binding ran on the first chat turn."""
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    corpus = tmp_path / "corpus"
    path = binding_mod.bindings_path(corpus)
    path.parent.mkdir(parents=True)
    path.write_text(_review_record(
        "https://provider.invalid/v1",
        credential_ref="opref-0123456789abcdef01234567",
        broker_argv=["/bin/sh", "-c", "id > $PWD/pwned"]), encoding="utf-8")
    with _a_private_policy_where_one_exists(tmp_path / "st"):
        port = install_mod.declared_model_port_factory(
            tmp_path / "sessions", checkout_root=corpus)()
        try:
            port.dispatch(_Envelope())
        except Exception as caught:  # noqa: BLE001 - at the base, a broker refusal after the run
            refused = caught
    assert not (work / "pwned").exists(), (
        "the repository's program ran: "
        + (work / "pwned").read_text(encoding="utf-8"))
    assert isinstance(refused, binding_mod.BindingRefused)


# ===========================================================================
# 2. F16.1's batch M block, case by case
# ===========================================================================


@pytest.mark.parametrize("kind", KINDS)
def test_an_untrusted_binding_is_refused_by_name_with_nothing_spawned_or_read(
        served, capsys, kind):
    """A binding written into the bindings document by hand, as a clone
    delivers it, is listed `available: false`; a turn naming it is refused,
    naming its id and the command that trusts it; the factory's notice and
    `list` name the same; and nothing is spawned, read or contacted."""
    served.hand_write(served.record(kind))
    port = served.port()
    notice = capsys.readouterr().err
    assert [(e.model_id, e.available) for e in port.catalog().entries] == [
        (BINDING_ID, False)]
    with pytest.raises(_trust_mod().BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    listed = capsys.readouterr().out
    for text in (str(refused.value), notice, listed):
        assert json.dumps(BINDING_ID) in text or BINDING_ID in text
        assert _command(served.repo) in text
        assert SECRET not in text
    served.nothing_was_touched()


@pytest.mark.parametrize("kind", KINDS)
def test_set_credential_refuses_an_untrusted_binding_and_leaves_it_untrusted(
        served, capsys, kind):
    served.hand_write(served.record(kind))
    args = cli_mod.build_parser().parse_args([
        "model-binding", "set-credential", "--repo-root", str(served.repo),
        "--id", BINDING_ID])

    class _MustNotBeRead:
        def read(self, *_args):
            raise AssertionError("set-credential read a credential for a "
                                 "binding it may not hand one to")

    assert cli_mod.cmd_model_binding_set_credential(
        args, source=_MustNotBeRead()) == 1
    err = capsys.readouterr().err
    if kind == "broker":
        assert _command(served.repo) in err
    else:
        assert "names no broker" in err
    assert not served.trust.verdict(served.declared(), root=served.repo).trusted
    served.nothing_was_touched()


@pytest.mark.parametrize("kind", KINDS)
def test_add_records_trust_and_a_turn_uses_the_binding(served, capsys, kind):
    """The same binding declared through `opendox model-binding add` is
    offered as available, and a turn runs its broker, or reaches the
    listener with the known value."""
    assert _cli(*served.add_argv(kind)) == 0
    assert f"trusted {json.dumps(BINDING_ID)} on this machine" in \
        capsys.readouterr().out
    port = served.port()
    assert isinstance(port, provider_mod.BrokeredProviderPort)
    assert [e.available for e in port.catalog().entries] == [True]
    assert port.dispatch(_Envelope())["assistant_prose"] == "ok"
    if kind == "broker":
        assert served.marker.read_text().startswith("mint ")
    assert served.listener.authorizations() == [f"Bearer {SECRET}"]


#: One valid replacement for each field of the record. Together they are the
#: digest's whole field set.
EDITS = {
    "id": "helpful-model2",
    "label": "Helpful modem",
    "provider": "anyonf",
    "credential_ref": "opref-0123456789abcdef01234568",
    "auth_kind": "oauth",
    "approved_by": "repo-authos",
    "endpoint": None,           # the listener's, with another path
    "dialect": "xfactory-prompt-v1",
    "model": "stand-in-7b",
    "broker_argv": None,        # the broker's, with one more member
}


def test_the_edits_cover_every_field_of_the_record():
    assert sorted(EDITS) == sorted(binding_mod.BINDING_FIELDS)


@pytest.mark.parametrize("field", sorted(EDITS))
def test_a_hand_edit_of_any_field_untrusts_the_binding(served, capsys, field):
    """The binding as trusted, then the same document with ONE field changed
    by hand: the digest differs, and the binding is refused by name."""
    served.hand_write(served.record("broker"))
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 0
    trusted = served.declared()
    capsys.readouterr()
    assert isinstance(served.port(), provider_mod.BrokeredProviderPort)
    value = EDITS[field]
    if field == "endpoint":
        value = served.listener.endpoint + "x"
    if field == "broker_argv":
        value = [*served.record("broker")["broker_argv"], "--extra"]
    served.hand_write(served.record("broker", **{field: value}))
    edited = served.declared()
    assert (_trust_mod().binding_digest(edited)
            != _trust_mod().binding_digest(trusted))
    capsys.readouterr()
    port = served.port()
    assert isinstance(port, _trust_mod().UntrustedBindingPort)
    with pytest.raises(_trust_mod().BindingUntrusted):
        port.dispatch(_Envelope())
    served.nothing_was_touched()


def test_a_one_byte_edit_to_the_committed_file_untrusts(served, capsys):
    path = served.hand_write(served.record("env"))
    served.trust.record(served.declared(), root=served.repo)
    assert isinstance(served.port(), provider_mod.BrokeredProviderPort)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("Helpful model", "Helpful modem"),
                    encoding="utf-8")
    assert len(path.read_bytes()) == len(text.encode("utf-8"))
    port = served.port()
    assert isinstance(port, _trust_mod().UntrustedBindingPort)
    assert _trust_mod().REASON_CHANGED in capsys.readouterr().err


def test_edit_and_set_credential_keep_a_trusted_binding_trusted(served,
                                                                capsys):
    """A binding rewritten through `opendox model-binding edit` is trusted in
    its new form, and its old form is not; a trusted binding whose reference
    `set-credential` rewrote from the stand-in broker's answer is trusted."""
    assert _cli(*served.add_argv("broker")) == 0
    before = served.declared()
    edit = served.add_argv("broker")
    edit[1] = "edit"
    edit[edit.index("--label") + 1] = "Renamed"
    assert _cli(*edit) == 0
    after = served.declared()
    assert after.label == "Renamed"
    assert served.trust.verdict(after, root=served.repo).trusted
    assert not served.trust.verdict(before, root=served.repo).trusted
    args = cli_mod.build_parser().parse_args([
        "model-binding", "set-credential", "--repo-root", str(served.repo),
        "--id", BINDING_ID])
    assert cli_mod.cmd_model_binding_set_credential(
        args, source=io.StringIO("sk-stand-in-NOT-A-KEY")) == 0
    rewritten = served.declared()
    assert rewritten.credential_ref == "opref-fffffffffffffffffffffff1"
    assert served.trust.verdict(rewritten, root=served.repo).trusted
    assert served.marker.read_text().startswith("intake ")


@pytest.mark.parametrize("kind", KINDS)
def test_trust_prints_what_it_trusts_then_trusts_it(served, capsys, kind):
    """`opendox model-binding trust <id>` prints the broker argv, the
    endpoint, the auth kind and the credential reference, each escaped, and
    never the credential. It runs, reads and contacts nothing. Then the
    binding is offered as available."""
    record = served.record(kind)
    served.hand_write(record)
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 0
    out = capsys.readouterr().out
    disclosure = out.split(f"  trusted {json.dumps(BINDING_ID)}", 1)[0]
    assert json.dumps(record["endpoint"]) in disclosure
    assert f'auth kind      "{record["auth_kind"]}"' in disclosure
    assert json.dumps(record["credential_ref"]) in disclosure
    if kind == "broker":
        assert json.dumps(record["broker_argv"])[:-1] in disclosure
    else:
        assert "will run       no program" in disclosure
    assert SECRET not in out
    served.nothing_was_touched()
    port = served.port()
    assert [e.available for e in port.catalog().entries] == [True]


def test_trust_takes_no_yes_and_refuses_an_unknown_id(served, capsys):
    served.hand_write(served.record("env"))
    with pytest.raises(SystemExit):
        _cli("model-binding", "trust", "--repo-root", str(served.repo),
             "--yes", BINDING_ID)
    capsys.readouterr()
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                "no-such-binding") == 1
    assert 'no binding with id "no-such-binding"' in capsys.readouterr().err
    assert not served.trust.verdict(served.declared(),
                                    root=served.repo).trusted


def test_a_binding_carrying_control_characters_is_shown_escaped(served,
                                                                capsys):
    """A hand-written binding whose id, label and one broker argv member carry
    a newline and a terminal escape is printed with both escaped, by `trust`,
    by `list` and in the refusal, and no raw control byte reaches the
    output. The catalog refuses such an id, so `trust` shows it and then
    refuses it (Copilot at openDox-code#82, r4174783280)."""
    from opendox import doxbench_model

    hostile = "evil\n\x1b[2J"
    served.hand_write(served.record(
        "broker", id=hostile, label=f"Label{hostile}",
        broker_argv=[sys.executable, str(served.broker), f"--x{hostile}"]))
    # the start passes it over, saying so (T100 follow-on, A3) ...
    assert served.port() is doxbench_model.NO_MODEL_CONFIGURED
    # ... and the gate beneath still refuses it
    port = served.gated_port()
    with pytest.raises(_trust_mod().BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                hostile) == 1
    captured = capsys.readouterr()
    for text in (captured.out, captured.err, str(refused.value)):
        assert "\x1b" not in text
        assert "evil\n" not in text
        assert "\\u001b[2J" in text
    served.nothing_was_touched()


def test_a_binding_moved_to_another_root_is_untrusted(served, capsys):
    """A trusted bindings document, copied byte for byte into a second fresh
    repository, reads untrusted there."""
    path = served.hand_write(served.record("env"))
    served.trust.record(served.declared(), root=served.repo)
    second = served.fresh_repository("r2")
    copy = binding_mod.bindings_path(second)
    copy.parent.mkdir(parents=True)
    shutil.copyfile(path, copy)
    capsys.readouterr()
    port = served.port(second)
    assert isinstance(port, _trust_mod().UntrustedBindingPort)
    assert _command(second) in capsys.readouterr().err
    with pytest.raises(_trust_mod().BindingUntrusted):
        port.dispatch(_Envelope())
    assert isinstance(served.port(), provider_mod.BrokeredProviderPort)
    served.nothing_was_touched()


def test_a_root_reached_through_a_link_is_the_root_it_reaches(served):
    served.hand_write(served.record("env"))
    served.trust.record(served.declared(), root=served.repo)
    link = served.tmp / "link"
    link.symlink_to(served.repo, target_is_directory=True)
    assert served.trust.verdict(served.declared(link), root=link).trusted


# --- the trust file is checked ----------------------------------------------


def _planted(served) -> str:
    """A store that WOULD trust the case's binding at its root: what an
    attacker wants this machine to read."""
    return json.dumps({"schema_version": 1,
                       "kind": "opendox-model-binding-trust",
                       "entries": [{"root": str(served.repo.resolve()),
                                    "binding_id": BINDING_ID,
                                    "digest": _trust_mod().binding_digest(
                                        served.declared())}]})


def _plant_link_to_the_file(served):
    elsewhere = served.tmp / "elsewhere.json"
    elsewhere.write_text(_planted(served), encoding="utf-8")
    os.chmod(elsewhere, 0o600)
    served.state_dir.mkdir(mode=0o700)
    (served.state_dir / _trust_mod().TRUST_FILENAME).symlink_to(elsewhere)
    return "is a symbolic link"


def _plant_link_to_the_directory(served):
    """The state directory replaced by a link of this user's own, to a
    private directory of this user's own holding a private store: F16.1's
    ratified text refuses even this one (T100 follow-on, A8; the holder's
    ruling on openxFactory#656 comment 5982436447). Before A8 the case
    passed only because the target was made writable by every user."""
    real = served.tmp / "real-state"
    real.mkdir(mode=0o700)
    (real / _trust_mod().TRUST_FILENAME).write_text(_planted(served),
                                                    encoding="utf-8")
    os.chmod(real / _trust_mod().TRUST_FILENAME, 0o600)
    os.chmod(served.tmp, 0o700)
    served.state_dir.symlink_to(real, target_is_directory=True)
    return "the directory that holds the store is a symbolic link"


def _plant_a_writable_file(served, mode=0o666):
    served.state_dir.mkdir(mode=0o700)
    path = served.state_dir / _trust_mod().TRUST_FILENAME
    path.write_text(_planted(served), encoding="utf-8")
    os.chmod(path, mode)
    return "is writable by"


def _plant_a_writable_directory(served):
    served.state_dir.mkdir()
    path = served.state_dir / _trust_mod().TRUST_FILENAME
    path.write_text(_planted(served), encoding="utf-8")
    os.chmod(path, 0o600)
    os.chmod(served.state_dir, 0o770)
    return "is writable by its group"


PLANTS = {"file-link": _plant_link_to_the_file,
          "directory-link": _plant_link_to_the_directory,
          "file-0666": _plant_a_writable_file,
          "file-0620": lambda served: _plant_a_writable_file(served, 0o620),
          "directory-0770": _plant_a_writable_directory}


@pytest.mark.parametrize("plant", sorted(PLANTS))
def test_a_trust_file_another_user_could_change_trusts_nothing(served,
                                                               capsys, plant):
    served.hand_write(served.record("env"))
    reason = PLANTS[plant](served)
    verdict = served.trust.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted
    assert reason in verdict.reason
    assert "model-binding trust store refuses" in verdict.reason
    capsys.readouterr()
    port = served.port()
    assert isinstance(port, _trust_mod().UntrustedBindingPort)
    assert reason in capsys.readouterr().err
    with pytest.raises(_trust_mod().TrustStoreRefused):
        served.trust.record(served.declared(), root=served.repo)
    served.nothing_was_touched()


def test_a_trust_file_that_does_not_read_trusts_nothing(served):
    served.hand_write(served.record("env"))
    served.state_dir.mkdir(mode=0o700)
    path = served.state_dir / _trust_mod().TRUST_FILENAME
    for text in ("not json", json.dumps({"kind": "something-else"}),
                 json.dumps({"schema_version": 1,
                             "kind": "opendox-model-binding-trust",
                             "entries": [{"root": "/", "extra": 1}]})):
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
        assert not served.trust.verdict(served.declared(),
                                        root=served.repo).trusted


@pytest.mark.parametrize("where", ["equal", "nested"])
def test_a_state_directory_at_or_inside_the_served_root_is_refused(
        served, capsys, monkeypatch, where):
    """`OPENDOX_STATE_DIR` equal to the served root, and nested under it:
    `add`, `edit` and `trust` are refused naming the setting before anything
    is written, and every binding reads untrusted."""
    trust_mod = _trust_mod()
    state = served.repo if where == "equal" else served.repo / "dot" / "st"
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    trust_mod.unregister()
    nested = trust_mod.MachineTrust(state_dir=state)
    trust_mod.register(nested)
    before = sorted(p.relative_to(served.repo).as_posix()
                    for p in served.repo.rglob("*") if ".git" not in p.parts)
    assert _cli(*served.add_argv("env")) == 1
    assert "OPENDOX_STATE_DIR" in capsys.readouterr().err
    assert not binding_mod.bindings_path(served.repo).exists()
    path = served.hand_write(served.record("env"))
    written = path.read_bytes()
    edit = served.add_argv("env")
    edit[1] = "edit"
    edit[edit.index("--label") + 1] = "Renamed"
    assert _cli(*edit) == 1
    assert "OPENDOX_STATE_DIR" in capsys.readouterr().err
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    assert "OPENDOX_STATE_DIR" in capsys.readouterr().err
    assert path.read_bytes() == written
    after = sorted(p.relative_to(served.repo).as_posix()
                   for p in served.repo.rglob("*") if ".git" not in p.parts)
    assert after == sorted([*before, *_bindings_document_and_parents()])
    assert not nested.verdict(served.declared(), root=served.repo).trusted
    assert isinstance(served.port(), trust_mod.UntrustedBindingPort)


def _bindings_document_and_parents() -> list[str]:
    parts = Path(binding_mod.DEFAULT_BINDINGS_RELPATH).parts
    return ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]


def test_add_edit_and_trust_write_nothing_in_the_repository_but_the_document(
        served):
    assert _cli(*served.add_argv("env")) == 0
    edit = served.add_argv("env")
    edit[1] = "edit"
    assert _cli(*edit) == 0
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 0
    written = sorted(p.relative_to(served.repo).as_posix()
                     for p in served.repo.rglob("*")
                     if ".git" not in p.parts)
    assert written == sorted(_bindings_document_and_parents())


def test_the_store_is_one_private_file_created_by_descriptor(served):
    served.hand_write(served.record("env"))
    victim = served.tmp / "victim"
    victim.write_text("untouched", encoding="utf-8")
    served.state_dir.mkdir(mode=0o700)
    planted = (served.state_dir
               / f".{_trust_mod().TRUST_FILENAME}.opendox-{os.getpid()}")
    planted.symlink_to(victim)
    previous = os.umask(0o000)
    try:
        served.trust.record(served.declared(), root=served.repo)
    finally:
        os.umask(previous)
    assert victim.read_text(encoding="utf-8") == "untouched"
    path = served.state_dir / _trust_mod().TRUST_FILENAME
    assert stat.S_IMODE(os.lstat(path).st_mode) == 0o600
    lock = served.state_dir / _trust_mod().TRUST_LOCK_FILENAME
    assert stat.S_IMODE(os.lstat(lock).st_mode) == 0o600
    assert sorted(p.name for p in served.state_dir.iterdir()) == sorted(
        [path.name, lock.name])
    assert json.loads(path.read_text(encoding="utf-8"))["entries"] == [{
        "root": str(served.repo.resolve()), "binding_id": BINDING_ID,
        "digest": _trust_mod().binding_digest(served.declared())}]


def test_a_link_planted_between_the_unlink_and_the_create_is_never_followed(
        served, monkeypatch):
    """The race the exclusive, no-follow create exists for."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    served.state_dir.mkdir(mode=0o700)
    victim = served.tmp / "victim"
    victim.write_text("untouched", encoding="utf-8")
    temporary = str(served.state_dir / f".{trust_mod.TRUST_FILENAME}.opendox-"
                                       f"{os.getpid()}")
    real_unlink = os.unlink

    def racing_unlink(path, *args, **kwargs):
        try:
            real_unlink(path, *args, **kwargs)
        finally:
            if str(path) == temporary and not os.path.lexists(temporary):
                os.symlink(victim, temporary)

    monkeypatch.setattr(trust_mod.os, "unlink", racing_unlink)
    with pytest.raises(trust_mod.TrustStoreRefused):
        served.trust.record(served.declared(), root=served.repo)
    monkeypatch.undo()
    assert victim.read_text(encoding="utf-8") == "untouched"
    assert not served.trust.verdict(served.declared(),
                                    root=served.repo).trusted


_RACING_WRITER = r"""
import json, os, sys, time
from pathlib import Path
from opendox import doxbench_binding as binding_mod
from opendox import doxbench_trust as trust_mod

state, root, binding_id, role, flags = sys.argv[1:6]
flags = Path(flags)
binding = binding_mod.ModelProviderBinding(
    id=binding_id, label="Racing", provider="anyone",
    credential_ref="env:T100_RACE", auth_kind="api_key",
    approved_by="repo-author", endpoint="http://127.0.0.1:9/v1",
    dialect="openai-chat-v1", broker_argv=())
store = trust_mod.MachineTrust(state_dir=state)
if role == "first":
    real = trust_mod.MachineTrust._read

    def held(self, where):
        entries = real(self, where)
        (flags / "first-read").write_text("1")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if (flags / "second-done").exists():
                break
            time.sleep(0.02)
        return entries

    trust_mod.MachineTrust._read = held
    store.record(binding, root=root)
else:
    deadline = time.monotonic() + 20
    while not (flags / "first-read").exists():
        if time.monotonic() > deadline:
            sys.exit("the first writer never read the store")
        time.sleep(0.02)
    store.record(binding, root=root)
    (flags / "second-done").write_text("1")
"""


def test_two_processes_recording_at_once_lose_neither_trust(served):
    """Copilot at openDox-code#82 (r4173513761). The first process reads
    the store and then pauses inside its record; a second process records
    another binding meanwhile. Without a lock held across the read, the
    change and the replace, the first writes its stale snapshot and the
    second's trust is lost. With it, the second waits, and both are kept."""
    flags = served.tmp / "flags"
    flags.mkdir()
    env = {**_clean_env(), "PYTHONPATH": str(REPO_ROOT / "src")}
    common = [str(served.state_dir), str(served.repo)]
    first = subprocess.Popen(
        [sys.executable, "-c", _RACING_WRITER, *common, "first-binding",
         "first", str(flags)], env=env)
    second = subprocess.Popen(
        [sys.executable, "-c", _RACING_WRITER, *common, "second-binding",
         "second", str(flags)], env=env)
    assert first.wait(timeout=60) == 0
    assert second.wait(timeout=60) == 0
    path = served.state_dir / _trust_mod().TRUST_FILENAME
    kept = sorted(entry["binding_id"] for entry in json.loads(
        path.read_text(encoding="utf-8"))["entries"])
    assert kept == ["first-binding", "second-binding"], kept


@pytest.mark.parametrize("plant", ["link", "0666"])
def test_a_lock_file_another_user_could_change_records_nothing(served,
                                                               plant):
    """The lock file is held to the store's own rules: a link in its place
    is never followed, and one another user could write is refused by
    name, with nothing recorded."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    served.state_dir.mkdir(mode=0o700)
    lock = served.state_dir / trust_mod.TRUST_LOCK_FILENAME
    victim = served.tmp / "victim"
    victim.write_text("untouched", encoding="utf-8")
    os.chmod(victim, 0o600)
    if plant == "link":
        lock.symlink_to(victim)
    else:
        lock.write_text("", encoding="utf-8")
        os.chmod(lock, 0o666)
    with pytest.raises(trust_mod.TrustStoreRefused) as refused:
        served.trust.record(served.declared(), root=served.repo)
    assert json.dumps(str(lock)) in str(refused.value)
    assert victim.read_text(encoding="utf-8") == "untouched"
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()


class _OsWithout:
    """`os`, as the trust module sees it, lacking one name, as a platform
    without that POSIX primitive does. Everything else is the real `os`."""

    def __init__(self, missing: str) -> None:
        self._missing = missing

    def __getattr__(self, name):
        if name == self._missing:
            raise AttributeError(name)
        return getattr(os, name)


@pytest.mark.parametrize("missing", ["getuid", "O_NOFOLLOW", "O_DIRECTORY",
                                     "O_NONBLOCK", "fchmod", "fcntl"])
def test_a_platform_without_the_stores_primitives_trusts_nothing(
        served, capsys, monkeypatch, missing):
    """Copilot at openDox-code#82 (r4173876800). Where the platform lacks a
    POSIX primitive the store's guarantees rest on (as Windows lacks
    `os.getuid`, `O_NOFOLLOW` and `fcntl`), the store is refused by name,
    up front: every binding reads untrusted, `record` writes nothing, and
    `list` and the factory answer rather than raise."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    if missing == "fcntl":
        monkeypatch.setattr(trust_mod, "fcntl", None)
    else:
        monkeypatch.setattr(trust_mod, "os", _OsWithout(missing))
    verdict = served.trust.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted
    assert "POSIX" in verdict.reason
    with pytest.raises(trust_mod.TrustStoreRefused):
        served.trust.record(served.declared(), root=served.repo)
    assert not served.state_dir.exists()
    assert isinstance(served.port(), trust_mod.UntrustedBindingPort)
    assert "POSIX" in capsys.readouterr().err
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    assert "POSIX" in capsys.readouterr().out
    served.nothing_was_touched()


def test_a_state_directory_that_cannot_resolve_trusts_nothing(served,
                                                             capsys):
    """Copilot at openDox-code#82 (r4173876823). A state directory that is
    a link loop cannot be resolved; the store is refused by name, every
    binding reads untrusted, `record` writes nothing, and `list` and the
    factory answer rather than raise."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    loop = served.tmp / "loop"
    loop.symlink_to(served.tmp / "pool")
    (served.tmp / "pool").symlink_to(loop)
    trust_mod.unregister()
    looped = trust_mod.MachineTrust(state_dir=loop / "st")
    trust_mod.register(looped)
    verdict = looped.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted
    assert "cannot be resolved" in verdict.reason
    with pytest.raises(trust_mod.TrustStoreRefused):
        looped.record(served.declared(), root=served.repo)
    assert isinstance(served.port(), trust_mod.UntrustedBindingPort)
    assert "cannot be resolved" in capsys.readouterr().err
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    assert "cannot be resolved" in capsys.readouterr().out
    served.nothing_was_touched()


def test_a_record_that_would_outgrow_the_read_bound_is_refused(
        served, monkeypatch):
    """Copilot at openDox-code#82 (r4174632086). The store reads nothing
    larger than `MAX_TRUST_STORE_BYTES`, so it writes nothing larger either:
    a record that would outgrow the bound is refused by name, before the
    store is replaced, and every trust already recorded still holds."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    first = served.declared()
    served.trust.record(first, root=served.repo)
    path = served.state_dir / trust_mod.TRUST_FILENAME
    held = path.read_bytes()
    monkeypatch.setattr(trust_mod, "MAX_TRUST_STORE_BYTES", len(held) + 16)
    second = served.fresh_repository("r2")
    with pytest.raises(trust_mod.TrustStoreRefused) as refused:
        served.trust.record(first, root=second)
    assert "larger" in str(refused.value)
    assert path.read_bytes() == held
    assert served.trust.verdict(first, root=served.repo).trusted
    assert not served.trust.verdict(first, root=second).trusted


@pytest.mark.parametrize("binding_id", [BINDING_ID, "0.dotted_id-9",
                                        "M" * 128])
def test_the_printed_trust_command_trusts_the_binding_it_names(
        served, capsys, binding_id):
    """Copilot at openDox-code#82 (r4174632060, r4174783197). The command a
    refusal prints, run as printed, trusts exactly that binding, for every
    shape of id the catalog accepts, up to its bound. An id that begins with
    `-` is one the catalog refuses, and no command is printed for it
    (`test_an_id_the_catalog_refuses_prints_no_command_and_is_never_trusted`)."""
    import shlex as shlex_mod

    trust_mod = _trust_mod()
    served.hand_write(served.record("env", id=binding_id))
    port = served.port()
    capsys.readouterr()
    with pytest.raises(trust_mod.BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    command = str(refused.value).rsplit("trust it with: ", 1)[1]
    argv = shlex_mod.split(command)
    assert argv[:3] == ["opendox", "model-binding", "trust"]
    assert _cli(*argv[1:]) == 0
    assert served.trust.verdict(served.declared(), root=served.repo).trusted
    served.nothing_was_touched()


def test_a_store_that_cannot_be_locked_records_nothing(served, monkeypatch):
    """Where the platform or the file system offers no lock, `record` is
    refused by name and writes nothing, rather than risk losing a trust."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))

    def no_lock(*_args, **_kwargs):
        raise OSError(37, "No locks available")

    monkeypatch.setattr(trust_mod, "_lock_exclusively", no_lock)
    with pytest.raises(trust_mod.TrustStoreRefused) as refused:
        served.trust.record(served.declared(), root=served.repo)
    assert "lock" in str(refused.value)
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()


@pytest.mark.parametrize("which", ["store", "lock"])
def test_a_fifo_in_the_stores_place_is_refused_without_waiting(served,
                                                               which):
    """Copilot at openDox-code#82 (r4178064601). A FIFO where the store or
    its lock file belongs is refused by name, as not a regular file, and
    nothing waits on it: a read-only open of a FIFO otherwise blocks until a
    writer comes, holding `list`, the start and every verdict with it. Asked
    on a thread, so a store that waited fails this case rather than hang the
    suite."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    binding = served.declared()
    served.state_dir.mkdir(mode=0o700)
    fifo = served.state_dir / (trust_mod.TRUST_FILENAME if which == "store"
                               else trust_mod.TRUST_LOCK_FILENAME)
    os.mkfifo(fifo, 0o600)
    answers: dict = {}

    def ask():
        answers["verdict"] = served.trust.verdict(binding, root=served.repo)
        try:
            served.trust.record(binding, root=served.repo)
        except trust_mod.TrustStoreRefused as refusal:
            answers["record"] = refusal

    worker = threading.Thread(target=ask, daemon=True)
    worker.start()
    worker.join(timeout=20)
    waited = worker.is_alive()
    if waited:
        # Release the reader a waiting store left behind, so the case ends.
        os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
    assert not waited, "the trust store waited on a FIFO"
    if which == "store":
        assert not answers["verdict"].trusted
        assert "is not a regular file" in answers["verdict"].reason
    assert "is not a regular file" in str(answers["record"])
    assert stat.S_ISFIFO(fifo.lstat().st_mode)


def test_a_restrictive_umask_leaves_the_store_usable(served):
    """Copilot at openDox-code#82 (r4177946237). `os.open`'s mode is
    filtered by the umask: under 0777 the lock file was born 000, the first
    record went through the descriptor it had open, and every later one was
    refused ("cannot be opened"). The lock file and the store are each
    exactly 0600 whatever the umask, and every record after the first
    succeeds."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    binding = served.declared()
    second = served.fresh_repository("r2")
    previous = os.umask(0o777)
    try:
        served.trust.record(binding, root=served.repo)
        served.trust.record(binding, root=second)
    finally:
        os.umask(previous)
    for name in (trust_mod.TRUST_FILENAME, trust_mod.TRUST_LOCK_FILENAME):
        assert stat.S_IMODE((served.state_dir / name).stat().st_mode) == (
            0o600), name
    assert served.trust.verdict(binding, root=served.repo).trusted
    assert served.trust.verdict(binding, root=second).trusted


# --- every command printed for an operator to paste (r4174783197) -----------

#: Repository directory names, each holding what a shell acts on: a command
#: substitution in both spellings, a command separator, both quotes, a
#: newline, a terminal escape, and a printable non-ASCII name with a space.
#: A shell that ran any of them would make `CANARY` where it runs.
HOSTILE_ROOTS = {
    "dollar-paren": "r$(touch CANARY)",
    "backtick": "r`touch CANARY`",
    "semicolon": "r; touch CANARY",
    "quotes": "r'b\"c $(touch CANARY)",
    "newline": "r\n$(touch CANARY)",
    "escape": "r\x1b[2J$(touch CANARY)",
    "non-ascii": "r é $(touch CANARY)",
}

#: Every POSIX shell on this machine (`sh` always is one), each with the flag
#: that keeps it from reading the user's own start-up files.
SHELLS = tuple((shell, *flags) for shell, *flags in (("sh",), ("bash",),
                                                     ("zsh", "-f"))
               if shutil.which(shell))


def _as_each_shell_reads(command: str, where: Path) -> dict[str, list[str]]:
    """`command`, as each shell here reads it, with `opendox` stubbed by a
    shell function that writes the arguments it was given, NUL-separated:
    exactly what that shell would hand the real verb. Run in `where`, so
    whatever the command ran would land there."""
    env = {k: v for k, v in _clean_env().items()
           if k not in ("BASH_ENV", "ENV")}
    stub = 'opendox() { printf "%s\\0" "$@" > "$OPENDOX_ARGV"; }\n'
    read: dict[str, list[str]] = {}
    for shell, *flags in SHELLS:
        argv_file = where / f"argv-{shell}"
        subprocess.run([shell, *flags, "-c", stub + command + "\n"],
                       cwd=where, env={**env, "OPENDOX_ARGV": str(argv_file)},
                       check=True, timeout=60)
        read[shell] = [part.decode("utf-8", "surrogateescape") for part
                       in argv_file.read_bytes().split(b"\0")[:-1]]
    return read


def _printed_commands(text: str) -> list[str]:
    """Every command `text` prints for an operator to paste: what follows
    "trust it with: " on its line."""
    return [line.rsplit("trust it with: ", 1)[1]
            for line in text.splitlines() if "trust it with: " in line]


@pytest.mark.parametrize("name", sorted(HOSTILE_ROOTS))
def test_every_printed_trust_command_reads_back_exactly_in_each_shell(
        served, capsys, monkeypatch, name):
    """Copilot at openDox-code#82 (r4174783197). A repository's path can hold
    anything a directory name can. Every command printed to trust its binding
    (the factory's notice, a refused turn, `list`, and `list --bindings`) is
    ONE line that `sh`, `bash` and `zsh` each read back as exactly the verb's
    arguments, and it runs nothing: no `CANARY` is made. A path that is not
    printable is never printed in a command: the command names the
    repository `.`, to be run from its root. Where the factory or `list` was
    given the bindings document, the command names it too. Run as printed,
    from there, the command trusts the binding it names."""
    trust_mod = _trust_mod()
    root = served.fresh_repository(HOSTILE_ROOTS[name])
    document = served.hand_write(served.record("env"), root=root)
    port = served.port(root)
    notice = capsys.readouterr().err
    with pytest.raises(trust_mod.BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    port = install_mod.declared_model_port_factory(
        served.tmp / "sessions", checkout_root=root,
        bindings_path=document)()
    notice_naming_the_document = capsys.readouterr().err
    with pytest.raises(trust_mod.BindingUntrusted) as refused_naming:
        port.dispatch(_Envelope())
    assert _cli("model-binding", "list", "--repo-root", str(root)) == 0
    listed = capsys.readouterr().out
    assert _cli("model-binding", "list", "--repo-root", str(root),
                "--bindings", str(document)) == 0
    listed_naming_the_document = capsys.readouterr().out
    printable = str(root.resolve()).isprintable()
    place = str(root.resolve()) if printable else "."
    named = (str(document.resolve()) if printable
             else os.path.join(".", str(document.relative_to(root))))
    plain = ["model-binding", "trust", "--repo-root", place, BINDING_ID]
    naming = ["model-binding", "trust", "--repo-root", place, "--bindings",
              named, BINDING_ID]
    expected = {"notice": plain, "refused turn": plain, "list": plain,
                "notice --bindings": naming,
                "refused turn --bindings": naming,
                "list --bindings": naming}
    printed = {"notice": notice, "refused turn": str(refused.value),
               "list": listed,
               "notice --bindings": notice_naming_the_document,
               "refused turn --bindings": str(refused_naming.value),
               "list --bindings": listed_naming_the_document}
    shells_run_in = served.tmp / "shells"
    shells_run_in.mkdir()
    for source, text in printed.items():
        commands = _printed_commands(text)
        assert len(commands) == 1, (source, text)
        assert commands[0].isprintable(), (source, commands[0])
        for shell, argv in _as_each_shell_reads(commands[0],
                                                shells_run_in).items():
            assert argv == expected[source], (source, shell, commands[0])
    assert not list(served.tmp.rglob("CANARY"))
    monkeypatch.chdir(root)
    assert _cli(*expected["list --bindings"]) == 0
    capsys.readouterr()
    assert served.trust.verdict(served.declared(root), root=root).trusted
    assert not list(served.tmp.rglob("CANARY"))
    served.nothing_was_touched()


#: Ids a repository may write that the model catalog refuses, each holding
#: what a shell or an option parser would act on, or past the catalog's
#: bound, or outside its ASCII vocabulary.
HOSTILE_IDS = {
    "dollar-paren": "$(touch CANARY)",
    "backtick": "`touch CANARY`",
    "semicolon": "m; touch CANARY",
    "quotes": "m'b\"c",
    "newline": "m\n$(touch CANARY)",
    "dash": "-dash-model",
    "option": "--repo-root",
    "overlong": "M" * 129,
    "non-ascii": "mé",
}


@pytest.mark.parametrize("name", sorted(HOSTILE_IDS))
def test_an_id_the_catalog_refuses_prints_no_command_and_is_never_trusted(
        served, capsys, name):
    """Copilot at openDox-code#82 (r4174783197, r4174783280). An id the
    model catalog refuses belongs to a binding no turn could use, so no
    command that trusts it is printed anywhere (the factory's notice, a
    refused turn, `list`), each says why instead, and `trust` refuses it with
    nothing recorded. The catalog lists nothing, and the start does not
    fail."""
    from opendox import doxbench_model

    trust_mod = _trust_mod()
    binding_id = HOSTILE_IDS[name]
    served.hand_write(served.record("env", id=binding_id))
    # The start passes it over, saying why (T100 follow-on, A3), and the
    # gate beneath refuses it.
    assert served.port() is doxbench_model.NO_MODEL_CONFIGURED
    port = served.gated_port()
    notice = capsys.readouterr().err
    with pytest.raises(trust_mod.BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    listed = capsys.readouterr().out
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                "--", binding_id) == 1
    trusting = capsys.readouterr()
    shown = (notice, str(refused.value), listed, trusting.err)
    for text in shown:
        assert "opendox model-binding trust" not in text, text
    for text in shown:
        assert trust_mod.REASON_UNSERVABLE in text, text
        assert trust_mod.REMEDY_UNSERVABLE in text, text
    assert list(port.catalog().entries) == []
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()
    assert not trust_mod.verdict_for(served.declared(),
                                     root=served.repo).trusted
    # Every other refusal path holds the same line, whatever its reason: the
    # provider's own refusal of a binding no verdict covers, or one covering
    # another binding, prints no command for such an id either.
    assert trust_mod.trust_command(binding_id, str(served.repo)) is None
    other = trust_mod.TrustVerdict.trusted_for(
        _a_binding(), root=served.repo, basis=trust_mod.BASIS_HOST)
    for verdict in (None, other):
        with pytest.raises(trust_mod.BindingUntrusted) as refused:
            trust_mod.require_admitted(served.declared(), verdict)
        assert "opendox model-binding trust" not in str(refused.value)
        assert trust_mod.REMEDY_UNSERVABLE in str(refused.value)
    assert not list(served.tmp.rglob("CANARY"))
    served.nothing_was_touched()


@pytest.mark.parametrize("field", ["id", "label"])
def test_a_binding_the_catalog_refuses_is_never_trusted_nor_fails_the_start(
        served, capsys, field):
    """Copilot at openDox-code#82 (r4174783280). `ModelProviderBinding`
    takes an id or a label the model catalog refuses (here, one past the
    catalog's bound). Such a binding is refused before any policy is asked:
    a trust the store recorded for it before, or a host policy that trusts
    every binding, still leaves the start declaring a refusing port, never
    failing on `brokered_catalog`; and `trust`, `add` and `edit` record
    nothing and write nothing for one."""
    trust_mod = _trust_mod()
    record = served.record(
        "env", **({"id": "M" * 129} if field == "id" else {"label": "L" * 201}))
    document = served.hand_write(record)
    # recorded straight into the store, as a store written before this check
    served.trust.record(served.declared(), root=served.repo)
    from opendox import doxbench_model

    for policy in (served.trust, _TrustsEveryBinding()):
        trust_mod.unregister()
        trust_mod.register(policy)
        # passed over at the start (T100 follow-on, A3); refused beneath it
        assert served.port() is doxbench_model.NO_MODEL_CONFIGURED
        port = served.gated_port()
        assert list(port.catalog().entries) == []
        with pytest.raises(trust_mod.BindingUntrusted) as refused:
            port.dispatch(_Envelope())
        notice = capsys.readouterr().err
        assert _cli("model-binding", "list", "--repo-root",
                    str(served.repo)) == 0
        listed = capsys.readouterr().out
        # trust cannot repair it, so no command that trusts it is printed,
        # whatever its id looks like (here, for the label, a valid one)
        for text in (str(refused.value), notice, listed):
            assert trust_mod.REASON_UNSERVABLE in text, text
            assert trust_mod.REMEDY_UNSERVABLE in text, text
            assert "opendox model-binding trust" not in text, text
    trust_mod.unregister()
    trust_mod.register(served.trust)
    store = served.state_dir / trust_mod.TRUST_FILENAME
    held = store.read_bytes()
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                "--", record["id"]) == 1
    assert trust_mod.REASON_UNSERVABLE in capsys.readouterr().err
    assert store.read_bytes() == held
    document.unlink()
    adding = served.add_argv("env")
    adding[adding.index(f"--{field}") + 1] = record[field]
    assert _cli(*adding) == 1
    assert trust_mod.REASON_UNSERVABLE in capsys.readouterr().err
    assert not document.exists()
    assert store.read_bytes() == held
    assert _cli(*served.add_argv("env")) == 0
    capsys.readouterr()
    before = document.read_bytes()
    editing = served.add_argv("env")
    editing[1] = "edit"
    editing[editing.index("--label") + 1] = "L" * 201
    assert _cli(*editing) == 1
    assert trust_mod.REASON_UNSERVABLE in capsys.readouterr().err
    assert document.read_bytes() == before
    served.nothing_was_touched()


@pytest.mark.parametrize("second", ["another-form", "unreadable"])
def test_list_discloses_and_judges_one_reading_of_the_bindings(
        served, capsys, monkeypatch, second):
    """Copilot at openDox-code#82 (r4174783250). `list` reads the bindings
    document ONCE, and the fields it discloses and the trust it reports are
    both of that reading: a document that changes after it, or stops
    reading, cannot pair one form's fields with another form's verdict, or
    end the listing in a traceback."""
    record = served.record("env")
    served.hand_write(record)
    served.trust.record(served.declared(), root=served.repo)
    read = binding_mod.BindingStore._load
    readings = []

    def load(store):
        readings.append(store.path)
        if len(readings) == 1:
            return read(store)
        if second == "unreadable":
            raise binding_mod.BindingRefused(
                "the bindings document changed between two readings")
        return [binding_mod.ModelProviderBinding.from_record(
            {**record, "label": "Another form"})]

    monkeypatch.setattr(binding_mod.BindingStore, "_load", load)
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    listed = capsys.readouterr().out
    assert json.dumps(record["label"]) in listed
    assert "Another form" not in listed
    assert "    trust            trusted on this machine\n" in listed
    assert len(readings) == 1


@pytest.mark.parametrize("where", ["state-directory", "above-it"])
def test_a_link_to_nothing_on_the_way_to_the_store_is_refused_by_name(
        served, capsys, where):
    """Copilot at openDox-code#82 (r4174783301). A link this user owns that
    points at nothing, as the state directory or above it, is refused BY
    NAME, by `record` (which went through it and failed raw) and by
    `verdict`, and `trust` prints that refusal rather than call it a policy
    failure. Nothing is made where it points."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    link = served.tmp / "dangling"
    link.symlink_to(served.tmp / "nowhere")
    policy = trust_mod.MachineTrust(
        state_dir=link if where == "state-directory" else link / "st")
    trust_mod.unregister()
    trust_mod.register(policy)
    with pytest.raises(trust_mod.TrustStoreRefused) as refused:
        policy.record(served.declared(), root=served.repo)
    # The state directory itself is never a link, whatever it reaches (T100
    # follow-on, A8), so that is its refusal; above it, a link to nothing.
    said = ("the directory that holds the store is a symbolic link"
            if where == "state-directory" else
            "it is a symbolic link to nothing")
    assert f"refuses {json.dumps(str(link))}: {said}" in str(refused.value)
    verdict = policy.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted and verdict.reason == str(refused.value)
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    assert str(refused.value) in capsys.readouterr().err
    assert not (served.tmp / "nowhere").exists()


def test_a_store_the_system_refuses_to_make_is_refused_by_name(
        served, capsys, monkeypatch):
    """Copilot at openDox-code#82 (r4174783301). Whatever the system refuses
    on the store's tree that no check named (here, a permission) is refused
    BY NAME, as a `TrustStoreRefused` naming the store and the system's word
    for it, never a raw `OSError` that `trust` could only call a policy
    failure. A verdict says the same of a store it cannot read, and `list`
    prints it."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))

    def refused_by_the_system(_leaf):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(trust_mod, "_make_private_directories",
                        refused_by_the_system)
    with pytest.raises(trust_mod.TrustStoreRefused) as refused:
        served.trust.record(served.declared(), root=served.repo)
    assert json.dumps(str(served.state_dir)) in str(refused.value)
    assert "(Permission denied)" in str(refused.value)
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    err = capsys.readouterr().err
    assert str(refused.value) in err
    assert "trust policy failed" not in err
    monkeypatch.setattr(trust_mod, "_refuse_an_unsafe_tree",
                        lambda *_args, **_kwargs: refused_by_the_system(None))
    verdict = served.trust.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted
    assert verdict.reason == (
        f"the model-binding trust store in {json.dumps(str(served.state_dir))}"
        " could not be read (Permission denied), so nothing is trusted "
        "through it")
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    assert verdict.reason in capsys.readouterr().out


# --- the console intake ------------------------------------------------------


class _HostGate:
    """A host's gate, registered at openDox's gate seam, as a host that
    offers the console intake registers one (openDox-code#77, T084: standalone,
    with no gate-record writer, the intake is refused; `5961364221` item 1).
    openDox's default's names, with a record writer of its own."""

    def __init__(self) -> None:
        from opendox import column_seams as cs
        from opendox import default_columns as dc

        for name in (*cs.GATE_CALLABLES, *cs.GATE_VALUES):
            setattr(self, name, getattr(dc.GATE, name))
        self.written = []
        self.write_gate_action_record = lambda gate, records_dir, record: (
            self.written.append(record) or Path(records_dir) / "record.yaml")


def _served_intake(served, *, host_policy=None):
    """A stand-in host that offers the console intake: a host's gate
    registered (#77), a plane with a session, the served repository's
    declarations document naming the marker broker, and an intake act posted
    from the console. Returns the answer. The host registers a TRUST policy
    only where `host_policy` names one."""
    import http.client

    from opendox import column_seams, serve

    intake_mod.DeclarationStore(intake_mod.declarations_path(
        served.repo)).declare_broker(intake_mod.BrokerDeclaration(
            argv=(sys.executable, str(served.broker))))
    snapshot = served.tmp / "out" / "snapshot.json"
    snapshot.parent.mkdir()
    snapshot.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    if host_policy is not None:
        trust_mod = _trust_mod()
        trust_mod.unregister()
        trust_mod.register(host_policy)
    column_seams.gate.unregister()
    column_seams.gate.register(_HostGate())
    try:
        return _post_an_intake(served, snapshot, http.client, serve)
    finally:
        column_seams.gate.unregister()


def _post_an_intake(served, snapshot, client, serve):
    httpd = serve.build_server(
        REPO_ROOT / "src" / "opendox" / "web", snapshot, served.repo, port=0,
        actor="brett", model_port_factory=lambda: None)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        connection = client.HTTPConnection(*base, timeout=30)
        connection.request("GET", "/capabilities")
        caps = json.loads(connection.getresponse().read().decode("utf-8"))
        connection.close()
        query = "&".join(f"{k}={v}" for k, v in {
            "binding": BINDING_ID, "label": "Helpful", "provider": "anyone",
            "kind": "api_key", "endpoint": "https://provider.invalid/v1",
            "dialect": "openai-chat-v1"}.items())
        connection = client.HTTPConnection(*base, timeout=30)
        connection.request(
            "POST", f"/actions/workbench/model-intake?{query}",
            body=b"sk-stand-in-NOT-A-KEY",
            headers={"Content-Type": "application/octet-stream",
                     serve.CONSOLE_TOKEN_HEADER: caps.get("console_token",
                                                          "")})
        answer = json.loads(connection.getresponse().read().decode("utf-8")
                            or "{}")
        connection.close()
        return caps, answer
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


def test_the_console_intake_refuses_a_broker_the_repository_declares(served):
    """With a stand-in host that offers the console intake and registers no
    policy of its own, the intake's hand-off refuses by name a broker that
    the served repository's `model-declarations.yaml` names, and no marker
    file exists."""
    caps, answer = _served_intake(served)
    if not caps.get("actions", {}).get("session"):
        pytest.fail(f"the stand-in host offers no session: {caps}")
    assert answer.get("error") == "intake_refused", answer
    assert answer.get("reason") == _trust_mod().INTAKE_BROKER_UNTRUSTED
    assert not served.marker.exists()
    assert not binding_mod.bindings_path(served.repo).exists()


class _TrustsEveryBinding:
    """A host policy that trusts every BINDING, and says nothing of the
    console intake: it has no `intake_verdict`."""

    def verdict(self, binding, *, root):
        return _trust_mod().TrustVerdict.trusted_for(
            binding, root=root, basis=_trust_mod().BASIS_HOST)

    def record(self, binding, *, root):
        return self.verdict(binding, root=root)


class _AdmitsTheIntake(_TrustsEveryBinding):
    """A host policy that also admits the console intake, explicitly."""

    def intake_verdict(self, binding, *, root):
        return self.verdict(binding, root=root)


def test_a_hosts_own_policy_may_admit_the_console_intake(served):
    """Only by answering the intake's OWN question (`intake_verdict`): the
    intake is a distinct purpose, so a host that trusts every binding still
    does not admit it unless it says so."""
    _caps, answer = _served_intake(served, host_policy=_TrustsEveryBinding())
    assert answer.get("error") == "intake_refused", answer
    # the host's own policy refused it, so it says so (5985490378, D3)
    assert answer.get("reason") == _trust_mod().INTAKE_HOST_NOT_ADMITTED
    assert not served.marker.exists()
    served.marker.unlink(missing_ok=True)
    shutil.rmtree(served.tmp / "out")
    intake_mod.declarations_path(served.repo).unlink()
    _caps, answer = _served_intake(served, host_policy=_AdmitsTheIntake())
    assert answer.get("error") is None, answer
    assert served.marker.read_text().startswith("intake ")


def test_trusting_a_lookalike_binding_never_admits_the_console_intake(
        served):
    """Copilot at openDox-code#82 (r4173513782). A repository can declare a
    NORMAL binding with exactly the fields the intake's hand-off is judged
    by: its id, label, provider and endpoint, the placeholder reference, the
    serving actor as approver, and the declarations document's broker. Once
    the operator trusts that binding, the strict default must still refuse
    the intake, because no binding's trust is the intake's."""
    lookalike = served.record(
        "broker", label="Helpful", credential_ref="pending-broker-intake",
        approved_by="brett", endpoint="https://provider.invalid/v1",
        broker_argv=[sys.executable, str(served.broker)])
    path = served.hand_write(lookalike)
    trusted = served.trust.record(served.declared(), root=served.repo)
    assert trusted.trusted
    # The repository then drops the binding (a later commit): the trust
    # stays recorded for that root, id and digest, as direnv's does.
    path.unlink()
    _caps, answer = _served_intake(served)
    assert answer.get("error") == "intake_refused", answer
    assert answer.get("reason") == _trust_mod().INTAKE_BROKER_UNTRUSTED
    assert not served.marker.exists()


# --- what a policy answers is held to the binding asked about ---------------


@pytest.mark.parametrize("basis", ["default", "host"])
def test_D3_the_intakes_refusal_names_the_policy_that_refused(served, basis):
    """The holder's ruling, openxFactory#656 comment 5985490378, D3: where
    the host's own registered policy refuses the hand-off (here, as for a
    pending binding), the refusal says so in its own FIXED sentence, not
    "a host's own trust policy may admit it"; under openDox's own trust the
    sentence is unchanged. No broker runs either way."""
    trust_mod = _trust_mod()

    class _DeclinesTheIntake(_Declines):
        def intake_verdict(self, binding, *, root):
            return self.verdict(binding, root=root)

    if basis == "default":
        _caps, answer = _served_intake(served)
        said = trust_mod.INTAKE_BROKER_UNTRUSTED
    else:
        _caps, answer = _served_intake(served,
                                       host_policy=_DeclinesTheIntake())
        said = trust_mod.INTAKE_HOST_NOT_ADMITTED
    assert answer.get("error") == "intake_refused", answer
    assert answer.get("reason") == said
    assert not served.marker.exists()
    assert trust_mod.INTAKE_HOST_NOT_ADMITTED == (
        "the host's trust policy does not admit this hand-off; "
        "model-binding list shows why")


def test_D3_each_basis_has_its_sentence():
    trust_mod = _trust_mod()
    binding = _a_binding()
    for basis, said in ((trust_mod.BASIS_HOST,
                         trust_mod.INTAKE_HOST_NOT_ADMITTED),
                        (trust_mod.BASIS_MACHINE_TRUST,
                         trust_mod.INTAKE_BROKER_UNTRUSTED),
                        (trust_mod.BASIS_REPOSITORY,
                         trust_mod.INTAKE_BROKER_UNTRUSTED)):
        verdict = trust_mod.TrustVerdict.untrusted_for(
            binding, root="/srv/opendox-test", basis=basis, reason="no")
        assert trust_mod.intake_refusal_reason(verdict) == said, basis


def test_D2_the_remedy_where_trust_cannot_help_holds_under_every_policy():
    """The holder's ruling, openxFactory#656 comment 5985490378, D2: the
    remedy's last sentence is true under a host whose approval trusts the
    binding, which lists it trusted and prints no command."""
    remedy = _trust_mod().REMEDY_NOT_BY_TRUST
    assert remedy.endswith(
        "Then list its bindings again: it is shown trusted, or with the "
        "command that trusts it")
    assert "which prints the command" not in remedy


class _Declines:
    """A host policy whose `record` DECLINES, by answering an untrusted
    verdict, as openxFactory's governed policy does for a binding whose
    declaration is pending."""

    def verdict(self, binding, *, root):
        return _trust_mod().TrustVerdict.untrusted_for(
            binding, root=root, basis=_trust_mod().BASIS_HOST,
            reason="its declaration is pending")

    def record(self, binding, *, root):
        return self.verdict(binding, root=root)


class _RecordsAnother(_Declines):
    """A host policy whose `record` answers a TRUSTED verdict for another
    binding."""

    def record(self, binding, *, root):
        return _trust_mod().TrustVerdict.trusted_for(
            _a_binding(id="other-binding"), root=root,
            basis=_trust_mod().BASIS_HOST)


class _RecordRaises(_Declines):
    def record(self, binding, *, root):
        raise RuntimeError(SECRET)


class _RecordRefuses(_Declines):
    """A host policy whose `record` raises a `BindingRefused` carrying text
    of its own (Copilot at openDox-code#82, review 5402101086, previously
    missed): its words never reach the output, only its class does."""

    def record(self, binding, *, root):
        raise binding_mod.BindingRefused(SECRET)


class _RecordStoreRefuses(_Declines):
    """A host policy whose `record` raises the store's own refusal class
    with text of its own: only openDox's own store's refusal passes as it
    is."""

    def record(self, binding, *, root):
        raise _trust_mod().TrustStoreRefused(SECRET)


class _SubclassStoreRefuses:
    """A HOST policy built on `MachineTrust` whose `record` raises the store's
    refusal class with text of its own (Copilot at openDox-code#82,
    r4174632006): a subclass is not openDox's own store, so its words never
    pass through."""

    def __new__(cls):
        trust_mod = _trust_mod()

        class _Sub(trust_mod.MachineTrust):
            def record(self, binding, *, root):
                raise trust_mod.TrustStoreRefused(SECRET)

        return _Sub(state_dir="/nonexistent-t100-subclass")


RECORDING_POLICIES = {"declines": _Declines, "records-another": _RecordsAnother,
                      "raises": _RecordRaises, "refuses": _RecordRefuses,
                      "store-refuses": _RecordStoreRefuses,
                      "subclass-store-refuses": _SubclassStoreRefuses}


@pytest.mark.parametrize("policy", sorted(RECORDING_POLICIES))
def test_add_edit_and_trust_refuse_when_the_policy_does_not_record_trust(
        served, capsys, policy):
    """Copilot at openDox-code#82 (r4173513738). A policy may decline to
    record trust; then `add`, `edit` and `trust` are refused by name, write
    nothing, and never print that the binding is trusted. A policy that
    raises is refused the same way, naming what it raised and never its
    words."""
    trust_mod = _trust_mod()
    trust_mod.unregister()
    trust_mod.register(RECORDING_POLICIES[policy]())
    assert _cli(*served.add_argv("env")) == 1
    captured = capsys.readouterr()
    assert not binding_mod.bindings_path(served.repo).exists()
    assert "trusted " not in captured.out
    assert json.dumps(BINDING_ID) in captured.err
    assert SECRET not in captured.out + captured.err
    path = served.hand_write(served.record("env"))
    written = path.read_bytes()
    edit = served.add_argv("env")
    edit[1] = "edit"
    edit[edit.index("--label") + 1] = "Renamed"
    assert _cli(*edit) == 1
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    captured = capsys.readouterr()
    assert path.read_bytes() == written
    assert "  trusted " not in captured.out
    assert SECRET not in captured.out + captured.err
    if policy == "raises":
        assert "RuntimeError" in captured.err
    if policy == "refuses":
        assert "BindingRefused" in captured.err
    if policy in ("store-refuses", "subclass-store-refuses"):
        assert "TrustStoreRefused" in captured.err


@pytest.mark.parametrize("question", ["binding", "intake"])
def test_a_verdict_for_another_root_covers_nothing_here(served, capsys,
                                                        question):
    """Copilot at openDox-code#82 (r4174310794). A policy that answers a
    TRUSTED verdict minted for another repository root covers nothing at
    this one: the per-repository key holds, the binding is refused naming
    this root, and the intake runs no broker."""
    trust_mod = _trust_mod()
    elsewhere = served.fresh_repository("elsewhere")

    class _AnswersForAnotherRoot(_Declines):
        def verdict(self, binding, *, root):
            return trust_mod.TrustVerdict.trusted_for(
                binding, root=elsewhere, basis=trust_mod.BASIS_HOST)

        def intake_verdict(self, binding, *, root):
            return self.verdict(binding, root=root)

    if question == "intake":
        _caps, answer = _served_intake(served,
                                       host_policy=_AnswersForAnotherRoot())
        assert answer.get("reason") == trust_mod.INTAKE_HOST_NOT_ADMITTED
        assert not served.marker.exists()
        return
    trust_mod.unregister()
    trust_mod.register(_AnswersForAnotherRoot())
    served.hand_write(served.record("env"))
    port = served.port()
    notice = capsys.readouterr().err
    assert isinstance(port, trust_mod.UntrustedBindingPort)
    # an invalid answer, which the same policy gives when asked to record,
    # so no command that trusts is printed (Copilot at openDox-code#86,
    # r4179077004)
    _no_trust_command_in(notice)
    assert trust_mod.REASON_NOT_COVERED in notice
    assert trust_mod.REMEDY_NOT_BY_TRUST in notice
    served.nothing_was_touched()


@pytest.mark.parametrize("other", ["untrusted", "trusted"])
def test_a_verdict_for_another_binding_is_refused_naming_this_one(
        served, capsys, other):
    """Copilot at openDox-code#82 (r4173513795). A policy that answers a
    verdict for ANOTHER binding, untrusted or trusted, covers nothing here,
    and the refusal, the notice and `list` name the binding that was asked
    about, never the other one. The answer is the policy's own invalid one,
    which it gives when asked to record too, so none of them prints a
    command that trusts (Copilot at openDox-code#86, r4179077004)."""
    trust_mod = _trust_mod()

    class _AnswersAnother(_Declines):
        def verdict(self, binding, *, root):
            if other == "trusted":
                return trust_mod.TrustVerdict.trusted_for(
                    _a_binding(id="other-binding"), root=root,
                    basis=trust_mod.BASIS_HOST)
            return trust_mod.TrustVerdict.untrusted_for(
                _a_binding(id="other-binding"), root=root,
                basis=trust_mod.BASIS_HOST, reason="it is another binding")

    trust_mod.unregister()
    trust_mod.register(_AnswersAnother())
    served.hand_write(served.record("env"))
    port = served.port()
    notice = capsys.readouterr().err
    assert isinstance(port, trust_mod.UntrustedBindingPort)
    with pytest.raises(trust_mod.BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    listed = capsys.readouterr().out
    for text in (notice, str(refused.value), listed):
        assert BINDING_ID in text
        assert "other-binding" not in text
        _no_trust_command_in(text)
        assert trust_mod.REMEDY_NOT_BY_TRUST in text
    assert trust_mod.REASON_NOT_COVERED in notice
    served.nothing_was_touched()


# --- the policy seam ---------------------------------------------------------


def test_a_bare_process_registers_the_strict_default_at_first_use(served,
                                                                  capsys):
    """In a bare process that registers nothing, the first consumer to ask
    registers the strict default, and a hand-written binding is refused."""
    trust_mod = _trust_mod()
    trust_mod.unregister()
    with pytest.raises(trust_mod.TrustPolicyNotRegistered) as bare:
        trust_mod.current()
    assert "opendox.doxbench_trust.register(" in str(bare.value)
    served.hand_write(served.record("env"))
    port = served.port()
    assert type(trust_mod.current()) is trust_mod.MachineTrust
    assert isinstance(port, trust_mod.UntrustedBindingPort)
    assert _command(served.repo) in capsys.readouterr().err
    served.nothing_was_touched()


def test_a_host_policy_registered_before_first_use_is_the_one_consulted(
        served):
    trust_mod = _trust_mod()
    asked = []

    class _Host:
        def verdict(self, binding, *, root):
            asked.append(binding.id)
            return trust_mod.TrustVerdict.trusted_for(
                binding, root=root, basis=trust_mod.BASIS_HOST)

        def record(self, binding, *, root):
            return self.verdict(binding, root=root)

    host = _Host()
    trust_mod.unregister()
    trust_mod.register(host)
    served.hand_write(served.record("env"))
    assert isinstance(served.port(), provider_mod.BrokeredProviderPort)
    assert asked == [BINDING_ID]
    assert trust_mod.register_default() is host
    assert trust_mod.policy() is host


def test_the_default_is_replaced_by_a_host_only_until_it_is_read():
    trust_mod = _trust_mod()
    trust_mod.unregister()
    host = trust_mod.MachineTrust(state_dir="/host-state")
    try:
        trust_mod.register_default()
        assert trust_mod.register(host) is host
        assert trust_mod.register(host) is host, "the same again is a no-op"
        assert trust_mod.policy() is host
        with pytest.raises(trust_mod.TrustPolicyAlreadyRegistered):
            trust_mod.register(trust_mod.MachineTrust(state_dir="/other"))
        trust_mod.unregister()
        trust_mod.policy()
        with pytest.raises(trust_mod.TrustPolicyAlreadyRegistered):
            trust_mod.register(host)
        with pytest.raises(TypeError):
            trust_mod.unregister()
            trust_mod.register(object())
    finally:
        trust_mod.unregister()


def test_a_checkout_with_no_bindings_never_asks_the_policy(tmp_path,
                                                           monkeypatch):
    """A checkout that declares no binding resolves what it resolved before,
    and never touches the state directory: the policy is not even
    registered, let alone read."""
    trust_mod = _trust_mod()
    trust_mod.unregister()
    asked = []
    monkeypatch.setattr(trust_mod, "policy", lambda: asked.append(1))
    checkout = tmp_path / "empty"
    checkout.mkdir()
    port = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout)()
    assert asked == []
    assert not trust_mod.is_registered()
    assert not isinstance(port, trust_mod.UntrustedBindingPort)


# ===========================================================================
# 3. in depth: the provider refuses what no verdict covers
# ===========================================================================


def _a_binding(**changes):
    fields = dict(id=BINDING_ID, label="Helpful model", provider="anyone",
                  credential_ref="opref-0123456789abcdef01234567",
                  auth_kind="api_key", approved_by="brett@opensoft.one",
                  endpoint="https://provider.invalid/v1",
                  dialect="openai-chat-v1", broker_argv=("broker",))
    fields.update(changes)
    return binding_mod.ModelProviderBinding(**fields)


def _built_in(endpoint: str):
    return binding_mod.ModelProviderBinding(
        id=BINDING_ID, label="Helpful model", provider="anyone",
        credential_ref=f"env:{SECRET_NAME}", auth_kind="api_key",
        approved_by="repo-author", endpoint=endpoint,
        dialect="openai-chat-v1", broker_argv=())


def _verdict_for(binding):
    return _trust_mod().TrustVerdict.trusted_for(binding, root=None,
                                                  basis="test")


def test_the_resolver_reads_nothing_without_a_verdict_covering_the_binding(
        listener):
    binding = _built_in(listener.endpoint)
    other = _built_in(listener.endpoint + "x")
    untrusted = _trust_mod().TrustVerdict.untrusted_for(
        binding, root=None, basis="test", reason="it was never trusted")
    for verdict in (None, _verdict_for(other), untrusted):
        environ = _RecordingEnviron({SECRET_NAME: SECRET})
        with pytest.raises(_trust_mod().BindingUntrusted) as refused:
            provider_mod.resolve_credential_reference(
                binding, trust=verdict, environ=environ)
        assert environ.read == [], "the environment was read"
        assert SECRET not in str(refused.value)
    environ = _RecordingEnviron({SECRET_NAME: SECRET})
    assert provider_mod.resolve_credential_reference(
        binding, trust=_verdict_for(binding), environ=environ) == SECRET


def _script_broker(tmp_path):
    """A binding whose broker, if it ever runs, leaves a mark."""
    script = tmp_path / "marking-broker.py"
    mark = tmp_path / "broker-ran"
    script.write_text(f"open({str(mark)!r}, 'a').write('ran')\n",
                      encoding="utf-8")
    return _a_binding(broker_argv=(sys.executable, str(script))), mark


@pytest.mark.parametrize("operation", ["mint", "hand_off_credential",
                                       "revoke", "list_references"])
def test_no_broker_runs_without_a_verdict_covering_the_binding(
        tmp_path, operation):
    binding, mark = _script_broker(tmp_path)
    act = getattr(provider_mod, operation)

    class _MustNotBeRead:
        def read(self, *_args):
            raise AssertionError("the hand-off read its source")

    for verdict in (None, _verdict_for(_a_binding(label="another"))):
        with pytest.raises(_trust_mod().BindingUntrusted):
            if operation == "hand_off_credential":
                act(binding, _MustNotBeRead(), trust=verdict)
            else:
                act(binding, trust=verdict)
        assert not mark.exists(), f"{operation} ran the broker"


def test_the_broker_operation_runs_once_the_verdict_covers_it(tmp_path):
    binding, mark = _script_broker(tmp_path)
    with pytest.raises(provider_mod.BrokerRefused):
        provider_mod.mint(binding, trust=_verdict_for(binding))
    assert mark.read_text() == "ran"


def test_the_port_contacts_nothing_without_a_verdict(listener, monkeypatch):
    """The auth kind `none` too: it presents no credential, but it would
    still send chat content to the endpoint the binding chose."""
    monkeypatch.setenv(SECRET_NAME, SECRET)
    none = binding_mod.ModelProviderBinding(
        id=BINDING_ID, label="Helpful model", provider="anyone",
        credential_ref=None, auth_kind="none", approved_by="repo-author",
        endpoint=listener.endpoint, dialect="openai-chat-v1", broker_argv=())
    for heard, binding in enumerate((none, _built_in(listener.endpoint))):
        catalog = install_mod.brokered_catalog(binding)
        port = provider_mod.BrokeredProviderPort(binding, catalog)
        assert not any(e.available for e in port.catalog().entries)
        with pytest.raises(_trust_mod().BindingUntrusted):
            port.dispatch(_Envelope())
        assert len(listener.requests) == heard, "an untrusted port called"
        trusted = provider_mod.BrokeredProviderPort(
            binding, catalog, trust=_verdict_for(binding))
        assert all(e.available for e in trusted.catalog().entries)
        assert trusted.dispatch(_Envelope())["assistant_prose"] == "ok"
    assert len(listener.requests) == 2


def test_a_policy_that_fails_or_answers_another_binding_trusts_nothing(
        served, capsys):
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))

    class Failing:
        def verdict(self, binding, *, root):
            raise RuntimeError(SECRET)

        def record(self, binding, *, root):
            raise RuntimeError(SECRET)

    class Elsewhere:
        def verdict(self, binding, *, root):
            return trust_mod.TrustVerdict.trusted_for(
                _a_binding(label="another"), root=root, basis="host")

        def record(self, binding, *, root):
            raise AssertionError

    for policy in (Failing(), Elsewhere()):
        trust_mod.unregister()
        trust_mod.register(policy)
        port = served.port()
        assert isinstance(port, trust_mod.UntrustedBindingPort)
        assert SECRET not in capsys.readouterr().err
    served.nothing_was_touched()


# ===========================================================================
# 4. the governed host keeps its flow, under its own policy
# ===========================================================================


class _GovernedHostPolicy:
    """WHAT T094 REGISTERS AS openxFactory's OWN POLICY (RULED by Brett Heap,
    openxFactory#656 comment 5970369724, "Governance approval
    (Recommended)"), as a test-local stand-in, so the governed flow is
    unchanged in release 1:

    - a binding whose declaration the governance flow APPROVED is trusted;
    - a binding whose declaration is still PENDING is refused;
    - a binding with NO declaration is trusted: the operator's own, or the
      console intake's new binding while its broker runs;
    - where the declarations document cannot be read, nothing is admitted;
    - `record` writes nothing.

    The console intake asks its own question (`intake_verdict`), so the
    policy answers it too, as it answers for a binding with no declaration.
    Without it, the governed host's intake would be refused."""

    def verdict(self, binding, *, root):
        from opendox import doxbench_trust

        try:
            declaration = intake_mod.DeclarationStore(
                intake_mod.declarations_path(root)).get(binding.id)
        except Exception:  # noqa: BLE001 - an unreadable document admits nothing
            return doxbench_trust.TrustVerdict.untrusted_for(
                binding, root=root, basis=doxbench_trust.BASIS_HOST,
                reason="the declarations document cannot be read")
        if declaration is None or declaration.status == \
                intake_mod.STATUS_APPROVED:
            return doxbench_trust.TrustVerdict.trusted_for(
                binding, root=root, basis=doxbench_trust.BASIS_HOST)
        return doxbench_trust.TrustVerdict.untrusted_for(
            binding, root=root, basis=doxbench_trust.BASIS_HOST,
            reason="its declaration is not approved")

    def record(self, binding, *, root):
        return self.verdict(binding, root=root)

    def intake_verdict(self, binding, *, root):
        return self.verdict(binding, root=root)


def _propose(root: Path, binding_id: str):
    """A PENDING declaration of `binding_id` in `root`'s declarations
    document, as the console intake proposes one. Returns the store."""
    store = intake_mod.DeclarationStore(intake_mod.declarations_path(root))
    store.propose(intake_mod.ModelDeclaration(
        binding_id=binding_id, status=intake_mod.STATUS_PENDING,
        install_posture=intake_mod.POSTURE_SINGLE_OPERATOR,
        proposed_by="brett@opensoft.one", proposed_at=intake_mod.stamp()))
    return store


def _approve(root: Path, binding_id: str) -> None:
    _propose(root, binding_id).approve(
        binding_id, issued_by="console", approved_by="brett",
        expires_at=intake_mod.approval_expiry(),
        audit_ref="opaud-approved-1")


@pytest.mark.parametrize("declared", ["approved", "undeclared"])
def test_a_governed_host_policy_keeps_the_governed_flow(served, declared):
    """A composed host: openxFactory's policy, registered at process start,
    resolves the brokered port exactly as the install did before this change,
    for a binding the gate approved and for an undeclared one. The strict
    default, in the same checkout, refuses both until `trust`."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    if declared == "approved":
        _approve(served.repo, BINDING_ID)
    trust_mod.unregister()
    trust_mod.register(_GovernedHostPolicy())
    port = served.port()
    assert isinstance(port, provider_mod.BrokeredProviderPort)
    assert port.dispatch(_Envelope())["assistant_prose"] == "ok"
    trust_mod.unregister()
    trust_mod.register(served.trust)
    assert isinstance(served.port(), trust_mod.UntrustedBindingPort)


def test_a_governed_host_policy_keeps_the_console_intake(served):
    """5970369724: under openxFactory's policy the console intake stays as it
    is today. Its new binding has no declaration while its broker runs, and
    the policy answers the intake's own question as it answers for such a
    binding, so the hand-off runs the declared broker. The strict default
    refuses the same intake (above)."""
    _caps, answer = _served_intake(served, host_policy=_GovernedHostPolicy())
    assert answer.get("error") is None, answer
    assert served.marker.read_text().startswith("intake ")


def test_a_governed_host_policy_refuses_a_pending_declaration(served):
    """5970369724: a binding a repository declared that is still PENDING is
    refused, and an unreadable declarations document admits nothing."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    store = intake_mod.DeclarationStore(intake_mod.declarations_path(
        served.repo))
    store.propose(intake_mod.ModelDeclaration(
        binding_id=BINDING_ID, status=intake_mod.STATUS_PENDING,
        install_posture=intake_mod.POSTURE_SINGLE_OPERATOR,
        proposed_by="brett@opensoft.one", proposed_at=intake_mod.stamp()))
    policy = _GovernedHostPolicy()
    assert not policy.verdict(served.declared(), root=served.repo).trusted
    intake_mod.declarations_path(served.repo).write_text(
        "{not: [a, document", encoding="utf-8")
    refused = policy.verdict(served.declared(), root=served.repo)
    assert not refused.trusted
    assert "cannot be read" in refused.reason
    trust_mod.unregister()
    trust_mod.register(policy)
    with pytest.raises(trust_mod.TrustNotRecorded):
        trust_mod.recorded_for(served.declared(), root=served.repo)


# --- the trust-state walk: what is printed, stored and enforced agree -------


def _listed(out: str) -> dict[str, dict[str, str]]:
    """`list`'s output as {binding id: {field: value}}: each binding's line
    opens with its id in JSON's spelling, and each field's line is indented
    four, its name padded to seventeen."""
    blocks: dict[str, dict[str, str]] = {}
    fields: dict[str, str] = {}
    for line in out.splitlines():
        if line.startswith('  "'):
            fields = blocks.setdefault(
                json.JSONDecoder().raw_decode(line[2:])[0], {})
        elif line.startswith("    ") and not line.startswith("     "):
            fields[line[4:21].strip()] = line[21:]
    return blocks


@pytest.mark.parametrize("declarations", ["none", "first-pending",
                                          "unreadable"])
def test_list_names_the_one_binding_a_console_declares(served, capsys,
                                                       declarations):
    """The trust-state walk: pending, approved, undeclared and unreadable
    declarations. `list` names the binding a console serving this repository
    declares, by its factory's own rule, so a binding listed as trusted is
    never taken for the one in use: a pending declaration is passed over, an
    undeclared binding is the operator's own and counts as approved, an
    unreadable declarations document declares nothing pending, and the
    console declares the FIRST of the rest. Listing another document says
    the console does not read it."""
    from opendox import cli_model_binding as cmb

    served.hand_write(served.record("env", id="first-model"),
                      served.record("env", id="second-model"))
    if declarations == "first-pending":
        _propose(served.repo, "first-model")
    elif declarations == "unreadable":
        path = intake_mod.declarations_path(served.repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not: [a, document", encoding="utf-8")
    for binding in binding_mod.BindingStore(
            binding_mod.bindings_path(served.repo)).list():
        served.trust.record(binding, root=served.repo)
    port = served.port()
    capsys.readouterr()
    declared = "second-model" if declarations == "first-pending" else (
        "first-model")
    assert [(e.model_id, e.available) for e in port.catalog().entries] == [
        (declared, True)]
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    blocks = _listed(capsys.readouterr().out)
    assert {block["trust"] for block in blocks.values()} == {
        "trusted on this machine"}
    assert blocks[declared]["console"] == cmb.CONSOLE_DECLARES_THIS
    if declarations == "first-pending":
        assert blocks["first-model"]["console"] == (
            cmb.CONSOLE_PASSES_OVER_PENDING)
    else:
        assert blocks["second-model"]["console"] == (
            cmb.CONSOLE_DECLARES_ANOTHER.format(
                binding_id=json.dumps("first-model")))
    elsewhere = served.tmp / "elsewhere.yaml"
    shutil.copy(binding_mod.bindings_path(served.repo), elsewhere)
    assert _cli("model-binding", "list", "--repo-root", str(served.repo),
                "--bindings", str(elsewhere)) == 0
    blocks = _listed(capsys.readouterr().out)
    assert {block["console"] for block in blocks.values()} == {
        cmb.CONSOLE_READS_ANOTHER_DOCUMENT.format(path=json.dumps(str(
            binding_mod.bindings_path(served.repo.resolve()))))}


class _ApprovingHostGate(_HostGate):
    """A host's gate that also builds, validates and writes the approval's
    record, which openDox's own default refuses to build, as
    `tests/test_capability_honesty.py`'s host gate does."""

    def __init__(self) -> None:
        super().__init__()
        self.build_gate_action_record = lambda **fields: dict(fields)
        self.validate_gate_action_record = lambda record: None
        self.HumanGate = lambda root, prefixes, *, human_actor: (
            root, tuple(prefixes), human_actor)
        self.write_gate_action_record = lambda human, records_dir, record: (
            self.written.append(record)
            or Path(human[0]) / records_dir / "record.yaml")


def _post_an_approval(served, binding_id: str) -> dict:
    """The console's model approval of `binding_id`, posted to a stand-in
    host that registers its gate (#77), as `_served_intake`'s host does.
    Returns the answer."""
    import http.client

    from opendox import column_seams, serve

    column_seams.gate.unregister()
    column_seams.gate.register(_ApprovingHostGate())
    httpd = serve.build_server(
        REPO_ROOT / "src" / "opendox" / "web",
        served.tmp / "out" / "snapshot.json", served.repo, port=0,
        actor="brett", model_port_factory=lambda: None)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        connection = http.client.HTTPConnection(*base, timeout=30)
        connection.request("GET", "/capabilities")
        caps = json.loads(connection.getresponse().read().decode("utf-8"))
        connection.close()
        connection = http.client.HTTPConnection(*base, timeout=30)
        connection.request(
            "POST", "/actions/workbench/model-approval",
            body=json.dumps({"binding": binding_id}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     serve.CONSOLE_TOKEN_HEADER: caps.get("console_token",
                                                          "")})
        answer = json.loads(connection.getresponse().read().decode("utf-8")
                            or "{}")
        connection.close()
        return answer
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)
        column_seams.gate.unregister()


@pytest.mark.parametrize("judged_by", ["strict-default", "strict-default-trusted",
                                       "host", "nothing-registered",
                                       "unservable-strict-default",
                                       "unservable-host"])
def test_an_approval_says_available_only_where_the_binding_is_trusted(
        served, judged_by):
    """The trust-state walk, at the console's approval. Approval is a
    governance record, and trust is this machine's: under openDox's strict
    default an approved binding is still refused until it is trusted, so the
    result says so rather than that it is now an available catalog entry. A
    host whose policy admits the binding (a governed host's approval) and a
    binding this machine trusts read as before. Where nothing is registered,
    the act registers nothing and reads no store: no binding has been judged
    trusted in that process.

    A binding the catalog cannot list (its label past the catalog's bound,
    written after the intake) is approved and still unusable under ANY
    policy, and trust cannot repair it, so the result names the remedy and
    no command that trusts (Copilot at openDox-code#82, r4175203889)."""
    trust_mod = _trust_mod()
    _caps, answer = _served_intake(served, host_policy=_AdmitsTheIntake())
    assert answer.get("error") is None, answer
    if judged_by.startswith("unservable-"):
        store = binding_mod.BindingStore(binding_mod.bindings_path(
            served.repo))
        store.edit(dataclasses.replace(served.declared(), label="L" * 201))
    trust_mod.unregister()
    if judged_by.endswith("host"):
        trust_mod.register(_AdmitsTheIntake())
    elif judged_by != "nothing-registered":
        trust_mod.register(served.trust)
        if judged_by == "strict-default-trusted":
            served.trust.record(served.declared(), root=served.repo)
    approval = _post_an_approval(served, BINDING_ID)
    assert approval.get("ok") is True, approval
    if judged_by.startswith("unservable-"):
        assert "model-binding trust" not in approval["availability"]
        assert approval["availability"] == (
            trust_mod.APPROVED_UNSERVABLE_NOTICE)
    elif judged_by in ("strict-default", "nothing-registered"):
        assert approval["availability"] != intake_mod.APPROVAL_NOTICE
        assert approval["availability"] == (
            trust_mod.APPROVED_UNTRUSTED_NOTICE)
    else:
        assert approval["availability"] == intake_mod.APPROVAL_NOTICE
    assert trust_mod.is_registered() == (judged_by != "nothing-registered")


#: Each fixed sentence that quotes a `model-binding` command, with the verbs
#: it quotes in full (with their arguments) and those it only names.
FIXED_SENTENCES = {
    "UNTRUSTED_TURN_MESSAGE": (["list", "trust"], []),
    "UNTRUSTED_BINDING_REMEDY": (["list", "trust"], []),
    "APPROVED_UNTRUSTED_NOTICE": (["list", "trust"], []),
    "UNSERVABLE_TURN_MESSAGE": (["list"], ["edit"]),
    "APPROVED_UNSERVABLE_NOTICE": (["list"], ["edit", "remove"]),
    "REMEDY_UNSERVABLE": ([], ["edit", "remove"]),
    # T100 follow-on, A1 and A2: where trusting cannot help, none quotes it
    "UNTRUSTABLE_TURN_MESSAGE": (["list"], []),
    "APPROVED_UNTRUSTABLE_NOTICE": (["list"], []),
    "REMEDY_NOT_BY_TRUST": ([], []),
    "REMEDY_IN_REPOSITORY": ([], ["edit"]),
}


@pytest.mark.parametrize("sentence", sorted(FIXED_SENTENCES))
def test_each_command_a_fixed_sentence_quotes_is_one_the_verb_takes(
        served, sentence):
    """The trust-state walk. A fixed sentence (a refused turn's, the rail's,
    an approval's) names no repository and no binding, so it quotes each
    command with placeholders. Filled in, each is one `opendox` parses:
    `--repo-root` is required by every `model-binding` verb, and a sentence
    that left it out would send the operator to a usage error. A sentence for
    a binding the catalog cannot list quotes no `trust` (r4175203889): it only
    names the verbs that correct a binding."""
    import re
    import shlex

    text = getattr(_trust_mod(), sentence)
    in_full, named = FIXED_SENTENCES[sentence]
    quoted = re.findall(r'"(opendox [^"]*)"', text)
    assert sorted(command.split()[2] for command in quoted) == sorted(
        in_full + named)
    for command in quoted:
        if command.split()[2] in named:
            assert command == f"opendox model-binding {command.split()[2]}"
            continue
        argv = shlex.split(command.replace(
            "<repository>", str(served.repo)).replace("<id>", BINDING_ID))
        args = cli_mod.build_parser().parse_args(argv[1:])
        assert Path(args.repo_root) == served.repo


def test_an_approval_reads_the_trust_seam_once(served, monkeypatch):
    """Copilot at openDox-code#82 (r4177946288). The approval's verdict is
    the policy registered when it reads the seam, read ONCE. A host that
    unregisters between two reads (here, a registration check that answers
    yes and tears the host down) must not have openDox's default installed
    in its place by the approval, nor that store's answer given as the
    host's: the store trusts the binding, and the host does not.

    The host declines for a reason of its own, which `trust` cannot repair,
    so the approval names no command that trusts (T100 follow-on, A1)."""
    trust_mod = _trust_mod()
    _caps, answer = _served_intake(served, host_policy=_AdmitsTheIntake())
    assert answer.get("error") is None, answer
    served.trust.record(served.declared(), root=served.repo)
    host = _Declines()
    trust_mod.unregister()
    trust_mod.register(host)

    def registered_then_torn_down():
        trust_mod.unregister()
        return True

    monkeypatch.setattr(trust_mod, "is_registered", registered_then_torn_down)
    approval = _post_an_approval(served, BINDING_ID)
    assert approval.get("ok") is True, approval
    assert approval["availability"] == trust_mod.APPROVED_UNTRUSTABLE_NOTICE
    assert trust_mod.current() is host


@pytest.mark.parametrize("sentence", ["UNTRUSTED_TURN_MESSAGE",
                                      "UNSERVABLE_TURN_MESSAGE",
                                      "UNTRUSTABLE_TURN_MESSAGE"])
def test_each_turn_sentence_fits_the_released_failure_envelope(sentence):
    """A refused turn's sentence rides the RELEASED failure envelope, whose
    `message` the schema bounds; one past it would fail the envelope's own
    validation and lose its cause. Read from the released schema."""
    import yaml

    schema = yaml.safe_load((REPO_ROOT / "src" / "opendox" / "contracts"
                             / "schemas"
                             / "xfactory-workbench-chat-turn.schema.yaml"
                             ).read_text(encoding="utf-8"))
    bound = schema["$defs"]["failure_v2"]["properties"]["message"]
    assert 1 <= len(getattr(_trust_mod(), sentence)) <= bound["maxLength"]


# ===========================================================================
# 5. the store's default home, the rail, and a served turn (each waited on
#    another draft, #69, #74 and #77, now all on `main`)
# ===========================================================================

def test_the_default_store_lives_in_the_settings_state_directory(tmp_path,
                                                                 monkeypatch):
    trust_mod = _trust_mod()
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(tmp_path / "st"))
    policy = trust_mod.MachineTrust()
    assert policy.store_path() == tmp_path / "st" / trust_mod.TRUST_FILENAME
    root = tmp_path / "corpus"
    root.mkdir()
    policy.record(_a_binding(), root=root)
    assert policy.verdict(_a_binding(), root=root).trusted
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(root))
    refused = policy.verdict(_a_binding(), root=root)
    assert not refused.trusted and "OPENDOX_STATE_DIR" in refused.reason


def test_with_no_state_directory_nothing_is_trusted(tmp_path, monkeypatch):
    """Fail-closed: where the runtime defines no state directory (this
    change's base, before #69), the strict default trusts nothing."""
    trust_mod = _trust_mod()
    monkeypatch.delattr(runtime_config, "state_dir", raising=False)
    policy = trust_mod.MachineTrust()
    verdict = policy.verdict(_a_binding(), root=tmp_path)
    assert not verdict.trusted
    assert verdict.reason == trust_mod.NO_STATE_DIR
    with pytest.raises(trust_mod.TrustStoreRefused):
        policy.record(_a_binding(), root=tmp_path)


_VIEWS = REPO_ROOT / "src" / "opendox" / "web" / "views"
_RAIL = _VIEWS / "doxbench-chat.js"

#: The rail, mounted under node over a minimal DOM (the shim
#: openDox-code#74's tests/test_chat_model_configuration.py mounts it with),
#: once per catalog posture.
_TRUST_RAIL_HARNESS = r"""
class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.attributes = {}; this.listeners = {};
    this.className = ''; this._text = ''; this.hidden = false;
    this.disabled = false; this.value = ''; this.writes = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(value) {
    this.children = []; this._text = String(value); this.writes.push(this._text);
  }
  appendChild(child) { child.parentNode = this; this.children.push(child); return child; }
  append(...kids) { for (const k of kids) this.appendChild(k); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  focus() {}
  walk() { return this.children.reduce((a, c) => a.concat(c.walk()), [this]); }
}
const doc = { createElement: (tag) => new Node(tag), activeElement: null };
const byClass = (root, cls) => root.walk().filter(
  (n) => String(n.className).split(' ').includes(cls));

import { mountDoxBenchChatRail, UNTRUSTED_BINDING_REMEDY,
         untrustedBindingRemedy } from "./doxbench-chat.mjs";

const KEY = { repository: "fixture", ref: "main", tile_kind: "staged",
              tile_id: "a-topic" };
const ENTRY = { model_id: "helpful-model", label: "Helpful model",
  provider_class: "brokered", available: true, input_limit_bytes: 800000,
  output_limit_bytes: 900000, data_handling: "sent to the provider" };
const OFF = { ...ENTRY, available: false };
const bufferOf = (kind, path) => ({ kind, path, base_ref: "main",
  base_revision: "r1", base_hash: { algorithm: "sha256", hex: "c".repeat(64) },
  current_hash: { algorithm: "sha256", hex: "d".repeat(64) },
  hash_pending: false, content: "# " + kind, dirty: false });
const editorState = () => ({ active_buffer: "document", buffers: {
  outline: bufferOf("outline", "docs/outline.md"),
  document: bufferOf("document", "docs/detail.md") } });
const catalogOf = (models) => () => (models === null ? null
  : { schema_version: 1, kind: "workbench-model-catalog", models });

async function mount(catalog, { intake = null } = {}) {
  const host = new Node("div"); host.ownerDocument = doc;
  let turns = 0;
  let release;
  const gate = new Promise((res) => { release = res; });
  const rail = mountDoxBenchChatRail(host, {
    scopeKey: KEY,
    transports: { catalog: async () => { await gate; return catalog(); },
                  chatTurn: async () => { turns += 1; return null; } },
    editorState });
  // a host offering intake offers it before the catalog answers
  if (intake !== null) rail.intakeOffer(intake);
  release();
  await rail.ready;
  const shownBy = (cls) => {
    const line = byClass(host, cls)[0] || null;
    return (line && !line.hidden) ? line.textContent : null;
  };
  const announce = byClass(host, "doxchat-announce")[0];
  const composer = byClass(host, "doxchat-composer")[0];
  for (const value of ["w", "wh"]) {
    composer.value = value;
    for (const fn of composer.listeners.input || []) fn({ target: composer });
  }
  return { shown: shownBy("doxchat-untrusted"),
           noModel: shownBy("doxchat-no-model"), turns,
           announced: announce.writes.filter(
             (text) => text === UNTRUSTED_BINDING_REMEDY).length,
           sendDisabled: byClass(host, "doxchat-send")[0].disabled === true };
}

const out = {
  remedy: UNTRUSTED_BINDING_REMEDY,
  onlyUnavailable: await mount(catalogOf([OFF])),
  empty: await mount(catalogOf([])),
  available: await mount(catalogOf([ENTRY])),
  oneOfTwoAvailable: await mount(catalogOf([OFF, { ...ENTRY,
    model_id: "another-model" }])),
  unreadable: await mount(catalogOf(null)),
  intakeOffered: await mount(catalogOf([OFF]), { intake: true }),
  pure: {
    loading: untrustedBindingRemedy({ models: null, catalogFailure: null }),
    staleToken: untrustedBindingRemedy(
      { models: [OFF], catalogFailure: "console_required" }),
  },
};
process.stdout.write(JSON.stringify(out));
"""


def test_the_rail_says_how_to_trust_a_declared_binding(tmp_path):
    """RULED "make the rail say how to trust" (5962785556, item 2). With a
    declared model in the catalog and none available, the rail shows its own
    visible line, announced once, naming `model-binding list` (which says why
    for each binding) and `model-binding trust`; and 16.4's "no model
    configured" line stays hidden, because a model IS configured. Not while
    loading, not with any model available, not on a catalog failure (each has
    its own remedy), and not where a host offers intake (its own remedy's
    home, as for 16.4's line)."""
    import re
    import shutil as shutil_mod

    source = _RAIL.read_text(encoding="utf-8")
    match = re.search(
        r'export const UNTRUSTED_BINDING_REMEDY =\s*("(?:[^"\\]|\\.)*");',
        source)
    assert match, "the rail declares UNTRUSTED_BINDING_REMEDY as one literal"
    assert json.loads(match.group(1)) == _trust_mod().UNTRUSTED_BINDING_REMEDY
    node = shutil_mod.which("node")
    if node is None:
        pytest.skip("node not available for the chat rail's trust probe")
    (tmp_path / "doxbench-chat.mjs").write_text(source.replace(
        "./doxbench-chat-model.js", "./doxbench-chat-model.mjs"),
        encoding="utf-8")
    shutil_mod.copy(_VIEWS / "doxbench-chat-model.js",
                    tmp_path / "doxbench-chat-model.mjs")
    (tmp_path / "harness.mjs").write_text(_TRUST_RAIL_HARNESS,
                                          encoding="utf-8")
    done = subprocess.run([node, str(tmp_path / "harness.mjs")],
                          capture_output=True, text=True, timeout=60,
                          env=_clean_env())
    assert done.returncode == 0, done.stderr
    rail = json.loads(done.stdout)
    remedy = _trust_mod().UNTRUSTED_BINDING_REMEDY
    assert rail["remedy"] == remedy
    # Copilot at openDox-code#82 (r4173876849): a TRUSTED binding is also
    # unavailable after its provider refused, and `list` then says only that
    # it is trusted. The line says what `list` shows, and where the reason
    # is for a binding already trusted.
    assert "shows whether each binding is trusted" in remedy
    assert "says why" not in remedy
    assert "already trusted" in remedy
    shown = rail["onlyUnavailable"]
    assert shown["shown"] == remedy
    assert shown["noModel"] is None, "a declared model is not 'no model'"
    assert shown["announced"] == 1, "announced once, not on every keystroke"
    assert shown["sendDisabled"] is True and shown["turns"] == 0
    for case in ("empty", "available", "oneOfTwoAvailable", "unreadable",
                 "intakeOffered"):
        assert rail[case]["shown"] is None, case
        assert rail[case]["announced"] == 0, case
    assert rail["pure"] == {"loading": None, "staleToken": None}


class _Conforms:
    @staticmethod
    def iter_errors(_instance):
        return iter(())


class _EveryKind(dict):
    """The released validators, as a plane that can read its contract has
    them (openDox-code#77's `tests/test_neutral_turn_scope.py`)."""

    def get(self, _kind, _default=None):
        return _Conforms()


@pytest.mark.parametrize("binding", ["untrusted", "unservable"])
def test_a_served_turn_on_an_untrusted_binding_says_how_to_trust_it(served,
                                                                   binding):
    """A served turn naming the untrusted binding is refused
    `model_unavailable` with the fixed sentence that says how to trust it,
    and nothing is contacted. Where the catalog cannot list the binding (a
    label past its bound), trust cannot help, so the sentence names the
    remedy and no command that trusts (Copilot at openDox-code#82,
    r4175203889).

    SINCE THE T100 FOLLOW-ON (A3) the start passes such a binding over, as
    it does a pending one, so the console serves no model: the turn is
    refused as a plane with no model capability refuses it, and the start
    said why on stderr. Whether the local harness is installed is answered
    (no), so the case never depends on this machine's `PATH`."""
    import http.client

    from opendox import doxbench_hash, serve
    from opendox.serve_wire import (DOXBENCH_CHAT_TURN_V2_KIND,
                                    DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE,
                                    DOXBENCH_ERR_MODEL_UNAVAILABLE)
    from standalone_child import fresh_repository, git, run_module

    repo = fresh_repository(REPO_ROOT / "tests" / "fixtures"
                            / "plain-documents", served.tmp / "turn")
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    served.hand_write(served.record(
        "env", **({"label": "L" * 201} if binding == "unservable" else {})),
        root=repo)
    out = served.tmp / "turn-out" / "snapshot.json"
    generated, status = run_module(
        served.tmp, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--no-validate")
    assert status == 0, generated.stderr_text()
    httpd = serve.build_server(
        REPO_ROOT / "src" / "opendox" / "web", out, repo, port=0,
        actor="brett", schema_validator_factory=_EveryKind,
        model_port_factory=install_mod.declared_model_port_factory(
            install_mod.session_root_beside(out), checkout_root=repo,
            harness_present=lambda: False))
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        connection = http.client.HTTPConnection(*base, timeout=30)
        connection.request("GET", "/capabilities")
        caps = json.loads(connection.getresponse().read().decode("utf-8"))
        connection.close()
        document = "notes-rain-barrel-leak.md"
        text = (repo / document).read_text(encoding="utf-8")

        def buffer(kind, path, content):
            identity = doxbench_hash.content_identity(
                content, max_bytes=None).hex
            return {"kind": kind, "repository": "fixture", "path": path,
                    "base_ref": "main", "base_revision": "0" * 40,
                    "base_hash": identity, "content_hash": identity,
                    "content": content, "dirty": False}

        connection = http.client.HTTPConnection(*base, timeout=30)
        connection.request("POST", "/actions/workbench/chat-turn",
                           body=json.dumps({
                               "schema_version": 1,
                               "kind": DOXBENCH_CHAT_TURN_V2_KIND,
                               "client_turn_id": "t100-untrusted",
                               "scope": {"repository": "fixture",
                                         "ref": "main",
                                         "tile_kind": "cluster",
                                         "tile_id": "barrel-rain"},
                               "working_subject": "",
                               "message": "What does this claim?",
                               "model_id": BINDING_ID, "transcript": [],
                               "bound_buffer": document,
                               "buffers": [
                                   buffer("outline", None, "# outline\n"),
                                   buffer("document", document, text)],
                           }).encode("utf-8"),
                           headers={"Content-Type": "application/json",
                                    serve.CONSOLE_TOKEN_HEADER:
                                        caps["console_token"]})
        body = json.loads(connection.getresponse().read().decode("utf-8"))
        connection.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)
    if binding == "unservable":
        assert body.get("error") == (
            DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE), body
        assert "model-binding trust" not in body.get("message", ""), body
    else:
        assert body.get("error") == DOXBENCH_ERR_MODEL_UNAVAILABLE, body
        assert body.get("message") == _trust_mod().UNTRUSTED_TURN_MESSAGE, (
            body)
    served.nothing_was_touched()


# ===========================================================================
# 6. THE T100 FOLLOW-ON: the holder's adversarial review of openDox-code#82
#    (findings A1 to A19, N1 and N2; rulings on openxFactory#656 comment
#    5982436447: A2 and A14 Brett Heap's, A8 the holder's). Each case fails at
#    openDox-code `38d3350e`, where #82 landed, for its finding's reason.
#    A14 is RULED "Served repo only, limit": no case, no change.
# ===========================================================================


class _OsWith:
    """`os`, as the trust module sees it, with some names replaced (a spy, or
    a system that answers otherwise). Everything else is the real `os`."""

    def __init__(self, **replaced) -> None:
        self._replaced = replaced

    def __getattr__(self, name):
        if name in self._replaced:
            return self._replaced[name]
        return getattr(os, name)


def _no_trust_command_in(*texts: str) -> None:
    for text in texts:
        assert _printed_commands(text) == [], text
        assert "opendox model-binding trust" not in text, text


def _store_holding(served, document) -> Path:
    served.state_dir.mkdir(mode=0o700, exist_ok=True)
    store = served.state_dir / _trust_mod().TRUST_FILENAME
    store.write_text(document if isinstance(document, str)
                     else json.dumps(document), encoding="utf-8")
    os.chmod(store, 0o600)
    return store


# --- A1: no `trust` command where `trust` cannot repair the refusal --------


def test_A1_an_unsupported_platform_is_told_no_trust_command(
        served, capsys, monkeypatch):
    """On a platform that cannot keep the store, `trust` is refused too, so
    no command that trusts is printed: not by `list`, the start's notice, a
    refused turn, nor the turn's fixed sentence (`UNTRUSTABLE_TURN_MESSAGE`).
    Each names the cause and says to resolve it first."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    monkeypatch.setattr(trust_mod, "fcntl", None)         # as on Windows
    port = served.port()
    assert isinstance(port, trust_mod.UntrustedBindingPort)
    with pytest.raises(trust_mod.BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    assert trust_mod.turn_message_for(port) == (
        trust_mod.UNTRUSTABLE_TURN_MESSAGE)
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    captured = capsys.readouterr()
    _no_trust_command_in(captured.out, captured.err, str(refused.value))
    for text in (captured.out, captured.err, str(refused.value)):
        assert "POSIX" in text, text
        assert trust_mod.REMEDY_NOT_BY_TRUST in text, text
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    served.nothing_was_touched()


def test_A1_a_policys_answer_for_another_binding_is_told_no_trust_command(
        served, capsys):
    """Copilot at openDox-code#86 (r4179077004). A host whose `verdict` and
    `record` both answer with a verdict that does not cover the binding (a
    subclass, as in A12) is refused `REASON_NOT_COVERED`; `trust` would ask
    the same host and be refused, so no command is printed."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))

    class Lax(trust_mod.TrustVerdict):
        def admits(self, binding):
            return True

    class Host:
        def verdict(self, binding, *, root):
            exact = trust_mod.TrustVerdict.trusted_for(
                binding, root=root, basis=trust_mod.BASIS_HOST)
            return Lax(**{field.name: getattr(exact, field.name)
                          for field in dataclasses.fields(exact)})

        record = verdict

    trust_mod.unregister()
    trust_mod.register(Host())
    assert not trust_mod.trust_can_repair(trust_mod.REASON_NOT_COVERED)
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    listed = capsys.readouterr().out
    assert trust_mod.REASON_NOT_COVERED in listed
    _no_trust_command_in(listed)
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1


def test_A1_a_hosts_own_refusal_is_told_no_trust_command(served, capsys):
    """A host's policy that declines (a governed host, for a pending
    declaration) declines `trust` too, so `list` prints the host's reason
    and no command, and the approval names none either."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    _propose(served.repo, BINDING_ID)
    trust_mod.unregister()
    trust_mod.register(_GovernedHostPolicy())
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    listed = capsys.readouterr().out
    _no_trust_command_in(listed)
    assert "its declaration is not approved" in listed
    assert trust_mod.REMEDY_NOT_BY_TRUST in listed
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    class _Fails:
        def verdict(self, binding, *, root):
            raise RuntimeError(SECRET)

        record = verdict

    # the turn's sentence, for a host's refusal and for a host that fails
    for policy in (_GovernedHostPolicy(), _Fails()):
        trust_mod.unregister()
        trust_mod.register(policy)
        port = served.gated_port()
        assert isinstance(port, trust_mod.UntrustedBindingPort)
        assert trust_mod.turn_message_for(port) == (
            trust_mod.UNTRUSTABLE_TURN_MESSAGE)
    assert SECRET not in capsys.readouterr().err


def test_A1_an_unusable_store_is_told_no_trust_command(served, capsys):
    """A torn store refuses `trust` as it refuses the verdict, so the
    start's notice prints its cause and recovery, and no command."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    _store_holding(served, "{")                      # a torn copy
    served.port()
    notice = capsys.readouterr().err
    _no_trust_command_in(notice)
    assert "does not read as JSON" in notice
    assert trust_mod.RECOVER_MOVE_ASIDE in notice
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1


@pytest.mark.parametrize("reason", ["never", "changed", "record-form",
                                    "no-verdict"])
def test_A1_each_reason_trust_repairs_prints_the_command_that_repairs_it(
        served, capsys, reason):
    """The other side of A1: where `trust` CAN repair the refusal, the
    command is printed, and, run as printed, it trusts the binding."""
    import shlex

    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    words = {"never": trust_mod.REASON_NEVER_TRUSTED,
             "changed": trust_mod.REASON_CHANGED,
             "record-form": trust_mod.REASON_RECORD_FORM,
             "no-verdict": trust_mod.REASON_NO_VERDICT}[reason]
    assert trust_mod.trust_can_repair(words)
    remedy = trust_mod.trust_remedy(BINDING_ID, str(served.repo), words)
    [command] = _printed_commands(remedy)
    assert _cli(*shlex.split(command)[1:]) == 0
    capsys.readouterr()
    assert trust_mod.verdict_for(served.declared(), root=served.repo).trusted


# --- A2: a broker program inside the served repository is never trusted ----


def _in_repository_argv(served, where, monkeypatch):
    """A broker command naming a file inside the served repository, `where`
    each way a command can name one, as the broker runs it: from
    `BROKER_WORKING_DIRECTORY`, whatever directory the console was started
    in (here, an empty one outside the repository), unless a launcher moves
    it. The repository holds a copy of the marker broker at
    `tools/broker.py`."""
    tool = served.repo / "tools" / "broker.py"
    tool.parent.mkdir(exist_ok=True)
    shutil.copy(served.broker, tool)
    console = served.tmp / "console"
    console.mkdir()
    monkeypatch.chdir(console)
    broker_cwd = provider_mod.BROKER_WORKING_DIRECTORY
    beside = served.repo.parent              # the repository's own parent
    if where == "absolute":
        return [sys.executable, str(tool)]
    if where == "relative-to-the-broker-directory":
        return [sys.executable, os.path.relpath(tool, broker_cwd)]
    if where == "relative-climbing-from-the-broker-directory":
        # Copilot at openDox-code#86, r4179241532: `..` from the file
        # system's root is the root, so this names the repository's file
        # there, and from neither the console's directory nor the root's.
        return [sys.executable,
                os.path.join(os.pardir, os.path.relpath(tool, broker_cwd))]
    if where == "relative-after-env-changes-directory":
        # r4179366288: `env -C` moves the directory the rest is read from.
        deeper = beside / "a" / "b"
        deeper.mkdir(parents=True)
        return ["env", "-C", str(deeper), sys.executable,
                f"../../{served.repo.name}/tools/broker.py"]
    if where == "relative-after-env-chdir-abbreviated":
        # C1: `--chd` is `--chdir` to GNU getopt_long
        deeper = beside / "a" / "b"
        deeper.mkdir(parents=True)
        return ["env", f"--chd={deeper}", sys.executable,
                f"../../{served.repo.name}/tools/broker.py"]
    if where == "relative-after-env-chdir-in-a-cluster":
        # C1: `-vC/dir` is `-v -C /dir`
        deeper = beside / "a" / "b"
        deeper.mkdir(parents=True)
        return ["env", f"-vC{deeper}", sys.executable,
                f"../../{served.repo.name}/tools/broker.py"]
    if where == "relative-after-sudo-changes-directory":
        deeper = beside / "a" / "b"
        deeper.mkdir(parents=True)
        return ["sudo", "-D", str(deeper), sys.executable,
                f"../../{served.repo.name}/tools/broker.py"]
    if where == "bare-word-after-env-changes-directory":
        elsewhere = served.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "broker.py").symlink_to(tool)
        return ["env", "-C", str(elsewhere), sys.executable, "broker.py"]
    if where == "dotted-module-after-env-changes-directory":
        # r4179241555: a dotted name reaches the repository through
        # namespace packages from the directory `-m` imports from first.
        return ["env", "-C", str(beside), sys.executable, "-m",
                f"{served.repo.name}.tools.broker"]
    if where == "dotted-module-through-a-package-link":
        # r4179241555: the top-level package lies outside, and the module
        # the whole name reaches lies inside.
        package = served.tmp / "pkg"
        package.mkdir()
        (package / "inner").symlink_to(tool.parent)
        return ["env", "-C", str(served.tmp), sys.executable, "-m",
                "pkg.inner.broker"]
    if where == "dotted-module-linked-at-its-last-name":
        # r4179241555: every package on the way lies outside, and the file
        # the whole dotted name reaches is a link into the repository.
        elsewhere = served.tmp / "elsewhere"
        (elsewhere / "pkg").mkdir(parents=True)
        (elsewhere / "pkg" / "broker.py").symlink_to(tool)
        return ["env", "-C", str(elsewhere), sys.executable, "-m",
                "pkg.broker"]
    if where == "a-link-inside-in-the-middle-of-a-chain":
        # r4180041184: outside -> repository -> outside, as the script
        return [sys.executable, str(_chain(served, tool, relative=False))]
    if where == "a-relative-chain-through-the-repository":
        return [sys.executable, str(_chain(served, tool, relative=True))]
    if where == "a-chain-through-the-repository-as-the-program":
        return [str(_chain(served, tool, relative=False, program=True))]
    if where == "sourceless-bytecode-module":
        # r4180041203: `-m` imports a sourceless `.pyc`
        compiled = tool.parent / "bytecode.pyc"
        compiled.write_bytes(b"")
        elsewhere = served.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "bytecode.pyc").symlink_to(compiled)
        return ["env", "-C", str(elsewhere), sys.executable, "-m",
                "bytecode"]
    if where == "extension-module":
        suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
        extension = tool.parent / f"native{suffix}"
        extension.write_bytes(b"")
        elsewhere = served.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / f"native{suffix}").symlink_to(extension)
        return ["env", "-C", str(elsewhere), sys.executable, "-m", "native"]
    if where == "package-main-linked-into-the-repository":
        # r4180717725: `-m pkg` runs `pkg/__main__.py`
        elsewhere = served.tmp / "elsewhere"
        (elsewhere / "pkg").mkdir(parents=True)
        (elsewhere / "pkg" / "__main__.py").symlink_to(tool)
        return ["env", "-C", str(elsewhere), sys.executable, "-m", "pkg"]
    if where == "package-init-linked-into-the-repository":
        # r4180717725: `-m pkg.mod` runs `pkg/__init__.py` first
        elsewhere = served.tmp / "elsewhere"
        (elsewhere / "pkg").mkdir(parents=True)
        (elsewhere / "pkg" / "__init__.py").symlink_to(tool)
        (elsewhere / "pkg" / "mod.py").write_text("", encoding="utf-8")
        return ["env", "-C", str(elsewhere), sys.executable, "-m",
                "pkg.mod"]
    if where == "module-on-an-assigned-pythonpath":
        # r4180717772: the module is found through `PYTHONPATH`
        library = served.tmp / "library"
        library.mkdir()
        (library / "broker.py").symlink_to(tool)
        return ["env", f"PYTHONPATH={library}", sys.executable, "-m",
                "broker"]
    if where == "module-on-a-relative-pythonpath-entry":
        library = beside / "library"
        library.mkdir()
        (library / "broker.py").symlink_to(tool)
        return ["env", "-C", str(beside), "PYTHONPATH=library",
                sys.executable, "-m", "broker"]
    if where == "module-on-the-inherited-pythonpath":
        library = served.tmp / "library"
        library.mkdir()
        (library / "broker.py").symlink_to(tool)
        from opendox import doxbench_bridge

        monkeypatch.setattr(doxbench_bridge, "INHERITED_ENVIRONMENT",
                            (*doxbench_bridge.INHERITED_ENVIRONMENT,
                             "PYTHONPATH"))
        monkeypatch.setenv("PYTHONPATH", str(library))
        return [sys.executable, "-m", "broker"]
    if where == "module-attached-to-its-option":
        # r4180041213: `-mX`
        return ["env", "-C", str(beside), sys.executable,
                f"-m{served.repo.name}.tools.broker"]
    if where == "module-in-an-option-cluster":
        # r4180041213: `-BmX`
        return ["env", "-C", str(beside), sys.executable,
                f"-Bm{served.repo.name}.tools.broker"]
    if where == "symlink-in-the-repository-to-outside":
        # r4179241566: the repository owns the link, and a pull can point it
        # at another program without changing the binding.
        link = served.repo / "tools" / "outside-broker.py"
        link.symlink_to(served.broker)
        return [sys.executable, str(link)]
    if where == "climbing-out-of-a-link":
        # `..` is taken as the system takes it: from where the link leads.
        (served.tmp / "up").symlink_to(tool.parent)
        return [sys.executable,
                str(served.tmp / "up" / os.pardir / "tools" / "broker.py")]
    if where == "first-word-past-a-file-that-cannot-run":
        # a search path's file that cannot be run is passed over, as the
        # system passes it over
        program = served.repo / "bin" / "opref-runnable"
        program.parent.mkdir()
        program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
        os.chmod(program, 0o755)
        inert = served.tmp / "inert"
        inert.mkdir()
        (inert / program.name).write_text("", encoding="utf-8")
        monkeypatch.setenv("PATH", f"{inert}{os.pathsep}{program.parent}"
                           f"{os.pathsep}{os.environ.get('PATH', '')}")
        return [program.name]
    if where == "relative-search-path-entry":
        # r4179366288: a relative `PATH` entry is read from the broker's
        # directory, not the console's.
        program = served.repo / "bin" / "opref-relative"
        program.parent.mkdir()
        program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
        os.chmod(program, 0o755)
        monkeypatch.setenv("PATH", os.path.relpath(program.parent, broker_cwd)
                           + os.pathsep + os.environ.get("PATH", ""))
        return [program.name]
    if where.endswith("bytecode-cache-linked-into-the-repository"):
        # r4181465499; the holder's ruling, #656 5989835334: Python imports
        # a source's bytecode cache from `__pycache__` in its place
        compiled = tool.parent / "broker.pyc"
        compiled.write_bytes(b"")
        elsewhere = served.tmp / "elsewhere"
        package = elsewhere / "pkg"
        package.mkdir(parents=True)
        source, module = {
            "module-bytecode-cache-linked-into-the-repository": (
                elsewhere / "broker.py", "broker"),
            "initializer-bytecode-cache-linked-into-the-repository": (
                package / "__init__.py", "pkg.mod"),
            "main-bytecode-cache-linked-into-the-repository": (
                package / "__main__.py", "pkg"),
            "another-interpreters-bytecode-cache-linked-into-the-repository": (
                elsewhere / "broker.py", "broker"),
            "prefixed-process-bytecode-cache-linked-into-the-repository": (
                elsewhere / "broker.py", "broker"),
        }[where]
        source.write_text("", encoding="utf-8")
        (package / "mod.py").write_text("", encoding="utf-8")
        name = Path(importlib.util.cache_from_source(str(source))).name
        if where.startswith("another-interpreters"):
            name = f"{source.stem}.cpython-399.pyc"
        if where.startswith("prefixed-process"):
            # a cache prefix this process has is not where a broker's own
            # interpreter reads the cache from
            monkeypatch.setattr(sys, "pycache_prefix",
                                str(served.tmp / "prefix"))
        cache = source.parent / "__pycache__" / name
        cache.parent.mkdir()
        cache.symlink_to(compiled)
        return ["env", "-C", str(elsewhere), sys.executable, "-m", module]
    if where == "bytecode-cache-directory-linked-into-the-repository":
        # no cache is there yet, and the directory it would be read from is
        # a link into the repository
        caches = tool.parent / "caches"
        caches.mkdir()
        elsewhere = served.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "broker.py").write_text("", encoding="utf-8")
        (elsewhere / "__pycache__").symlink_to(caches)
        return ["env", "-C", str(elsewhere), sys.executable, "-m", "broker"]
    if where == "parent-module-on-an-assigned-pythonpath":
        # r4181006328: `-m parent.child` runs `parent.py` before it finds
        # `parent` is no package
        library = served.tmp / "library"
        library.mkdir()
        (library / "parent.py").symlink_to(tool)
        return ["env", f"PYTHONPATH={library}", sys.executable, "-m",
                "parent.child"]
    if where == "parent-module-in-the-start-directory":
        elsewhere = served.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "parent.py").symlink_to(tool)
        return ["env", "-C", str(elsewhere), sys.executable, "-m",
                "parent.child"]
    if where == "dotted-package-main-linked-into-the-repository":
        # `-m pkg.sub` runs `pkg/sub/__main__.py`, under packages outside
        elsewhere = served.tmp / "elsewhere"
        (elsewhere / "pkg" / "sub").mkdir(parents=True)
        (elsewhere / "pkg" / "sub" / "__main__.py").symlink_to(tool)
        return ["env", "-C", str(elsewhere), sys.executable, "-m",
                "pkg.sub"]
    if where == "program-past-an-assignment-whose-name-is-no-identifier":
        # r4181006390: GNU env reads `A-B=x` as an assignment, so the
        # program is the next member, found on the assigned `PATH`
        os.chmod(tool, 0o755)
        links = served.tmp / "links"
        links.mkdir()
        (links / "broker").symlink_to(tool)
        return ["env", f"PATH={links}", "A-B=x", "broker"]
    if where == "value-of-an-assignment-whose-name-is-no-identifier":
        return ["env", f"A-B={tool}", sys.executable, str(served.broker)]
    if where == "member-an-unknown-option-may-take":
        # 5988818366: a member read as an unknown option's value is still
        # judged as a path
        return ["node", "--frobnicate", str(tool)]
    if where == "search-path-assigned-through-a-link":
        # r4179366288: `env PATH=...` is the path the program is found on.
        program = served.repo / "bin" / "opref-linked"
        program.parent.mkdir()
        program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
        os.chmod(program, 0o755)
        links = served.tmp / "links"
        links.mkdir()
        (links / program.name).symlink_to(program)
        return ["env", f"PATH={links}", program.name]
    if where == "flag-value":
        return [sys.executable, str(served.broker), f"--config={tool}"]
    if where == "relative-flag-value-after-env-changes-directory":
        return ["env", "-C", str(beside), sys.executable, str(served.broker),
                f"--config={served.repo.name}/tools/broker.py"]
    if where == "link-from-outside":
        link = served.tmp / "outside-link.py"
        link.symlink_to(tool)
        return [sys.executable, str(link)]
    if where == "dash-named-program-on-path":
        program = served.repo / "bin" / "-broker"
        program.parent.mkdir()
        program.write_text(f"#!{sys.executable}\n"
                           + tool.read_text(encoding="utf-8"),
                           encoding="utf-8")
        os.chmod(program, 0o755)
        monkeypatch.setenv("PATH", f"{program.parent}{os.pathsep}"
                           f"{os.environ.get('PATH', '')}")
        return ["-broker"]
    if where == "positional-after-double-dash":
        elsewhere = served.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "-broker.py").symlink_to(tool)
        return ["env", "-C", str(elsewhere), sys.executable, "--",
                "-broker.py"]
    if where == "first-word-on-path":
        program = served.repo / "bin" / "opref-broker"
        program.parent.mkdir()
        program.write_text(f"#!{sys.executable}\n"
                           + tool.read_text(encoding="utf-8"),
                           encoding="utf-8")
        os.chmod(program, 0o755)
        monkeypatch.setenv("PATH", f"{program.parent}{os.pathsep}"
                           f"{os.environ.get('PATH', '')}")
        return ["opref-broker"]
    raise AssertionError(where)


def _chain(served, tool: Path, *, relative: bool,
           program: bool = False) -> Path:
    """`outside/entry -> <repo>/tools/selected -> outside/real`: a link
    outside the repository whose target is a link inside it, whose own
    target is a real file outside it (Copilot at openDox-code#86,
    r4180041184). Each target is relative to its link's directory where
    `relative`."""
    outside = served.tmp / "chain"
    outside.mkdir(exist_ok=True)
    real = outside / ("real-program" if program else "real.py")
    real.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    os.chmod(real, 0o755)
    selected = tool.parent / ("selected" if program else "selected.py")
    entry = outside / ("entry" if program else "entry.py")
    if relative:
        selected.symlink_to(os.path.relpath(real, selected.parent))
        entry.symlink_to(os.path.relpath(selected, entry.parent))
    else:
        selected.symlink_to(real)
        entry.symlink_to(selected)
    return entry


IN_REPOSITORY = ("absolute", "relative-to-the-broker-directory",
                 "relative-climbing-from-the-broker-directory",
                 "relative-after-env-changes-directory",
                 "relative-after-sudo-changes-directory",
                 "relative-after-env-chdir-abbreviated",
                 "relative-after-env-chdir-in-a-cluster",
                 "bare-word-after-env-changes-directory",
                 "dotted-module-after-env-changes-directory",
                 "dotted-module-through-a-package-link",
                 "dotted-module-linked-at-its-last-name",
                 "a-link-inside-in-the-middle-of-a-chain",
                 "a-relative-chain-through-the-repository",
                 "a-chain-through-the-repository-as-the-program",
                 "sourceless-bytecode-module", "extension-module",
                 "module-attached-to-its-option",
                 "module-in-an-option-cluster",
                 "package-main-linked-into-the-repository",
                 "package-init-linked-into-the-repository",
                 "module-on-an-assigned-pythonpath",
                 "module-on-a-relative-pythonpath-entry",
                 "module-on-the-inherited-pythonpath",
                 "parent-module-on-an-assigned-pythonpath",
                 "parent-module-in-the-start-directory",
                 "dotted-package-main-linked-into-the-repository",
                 "program-past-an-assignment-whose-name-is-no-identifier",
                 "value-of-an-assignment-whose-name-is-no-identifier",
                 "member-an-unknown-option-may-take",
                 "module-bytecode-cache-linked-into-the-repository",
                 "initializer-bytecode-cache-linked-into-the-repository",
                 "main-bytecode-cache-linked-into-the-repository",
                 "another-interpreters-bytecode-cache-linked-into-the-repository",
                 "prefixed-process-bytecode-cache-linked-into-the-repository",
                 "bytecode-cache-directory-linked-into-the-repository",
                 "symlink-in-the-repository-to-outside",
                 "relative-search-path-entry",
                 "climbing-out-of-a-link",
                 "first-word-past-a-file-that-cannot-run",
                 "search-path-assigned-through-a-link",
                 "flag-value",
                 "relative-flag-value-after-env-changes-directory",
                 "link-from-outside", "first-word-on-path",
                 "dash-named-program-on-path", "positional-after-double-dash")


@pytest.mark.parametrize("where", IN_REPOSITORY)
def test_A2_a_broker_inside_the_repository_is_refused_by_name(
        served, capsys, monkeypatch, where):
    """RULED by Brett Heap, openxFactory#656 comment 5982436447, item 2,
    "Refuse in-repo programs". Trust is of the binding's record, and a pull
    can change a program inside the repository after the record was
    trusted, so a binding whose broker command names one is refused BY NAME
    where trust is recorded (`trust`, `add`) and where it is checked (the
    verdict, under any policy, a host's that trusts everything included),
    with the remedy "install the broker outside the repository"."""
    trust_mod = _trust_mod()
    argv = _in_repository_argv(served, where, monkeypatch)
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.in_repository_program(binding, root=served.repo)
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    err = capsys.readouterr().err
    assert trust_mod.REASON_IN_REPOSITORY in err
    assert "install the broker outside the repository" in err
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()
    for policy in (served.trust, _TrustsEveryBinding()):
        trust_mod.unregister()
        trust_mod.register(policy)
        verdict = trust_mod.verdict_for(binding, root=served.repo)
        assert not verdict.trusted
        assert verdict.reason == trust_mod.REASON_IN_REPOSITORY
    served.nothing_was_touched()


def test_N2_deno_whose_leading_option_cannot_be_read_is_named(served):
    """Lane openXfactory-3 D7 early findings N2, holder ruled fix now: a
    leading option deno's global grammar does not hold is refused as
    unreadable, fail-closed, and `inline_script` names it rather than pass
    it; a known one is read past, to the subcommand."""
    trust_mod = _trust_mod()
    unknown = ["deno", "--frobnicate", "eval", "x"]
    assert trust_mod.inline_script(unknown) == "--frobnicate"
    assert trust_mod.broker_command_refused(unknown, root=served.repo) == (
        trust_mod.REASON_UNREADABLE_COMMAND)
    for argv in (["deno", "--quiet", "eval", "x"],
                 ["deno", "-q", "eval", "x"],
                 ["deno", "--log-level=info", "eval", "x"],
                 ["deno", "-Linfo", "eval", "x"],
                 ["deno", "--unstable-kv", "eval", "x"]):
        assert trust_mod.inline_script(argv) == "deno", argv
    assert trust_mod.inline_script(
        ["deno", "--quiet", "run", str(served.broker)]) is None


def test_R4_one_working_directory_per_launcher_is_judged(served):
    """The other side of r4180717752: one `-C` per launcher keeps its
    judgment, nested launchers each with their own included, and one given
    only inside an `env -S` string."""
    trust_mod = _trust_mod()
    program = [sys.executable, str(served.broker)]
    for argv in (["env", "-C", "/tmp", *program],
                 ["env", "-C", "/tmp", "env", "-C", "usr", *program],
                 ["env", "-S", f"-C /tmp {sys.executable} {served.broker}"],
                 ["sudo", "-D", "/tmp", *program]):
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) is None, argv


@pytest.mark.parametrize("optimization", ["", 1, 2])
def test_R6_a_cache_is_judged_by_name_where_its_directory_cannot_be_listed(
        served, optimization):
    """r4181465499; the holder's ruling, #656 5989835334: this
    interpreter's cache name, at every optimization level, is judged
    whether or not the directory it is in can be listed."""
    trust_mod = _trust_mod()
    compiled = served.repo / "broker.pyc"
    compiled.write_bytes(b"")
    elsewhere = served.tmp / "elsewhere"
    elsewhere.mkdir()
    source = elsewhere / "broker.py"
    source.write_text("", encoding="utf-8")
    name = Path(importlib.util.cache_from_source(
        str(source), optimization=optimization)).name
    pycache = elsewhere / "__pycache__"
    pycache.mkdir()
    (pycache / name).symlink_to(compiled)
    os.chmod(pycache, 0o300)                # searchable, not listable
    try:
        with pytest.raises(OSError):
            os.listdir(pycache)
        assert trust_mod.broker_command_refused(
            ["env", "-C", str(elsewhere), sys.executable, "-m", "broker"],
            root=served.repo) == trust_mod.REASON_IN_REPOSITORY
    finally:
        os.chmod(pycache, 0o700)


def test_R6_a_member_past_the_bounds_is_refused_as_unreadable(served):
    """The summary of review 5411026353; the holder's ruling, #656
    5989835334: a member longer than PATH_MAX (4096), or holding more than
    32 absolute paths, is refused as unreadable before it is judged, and
    `in_repository_argv` returns it unjudged, FAIL-CLOSED, so an
    environment value past the bounds is no value a broker gets; a member
    at each bound is judged."""
    trust_mod = _trust_mod()
    outside = "/opt/opendox-test/broker"
    for member in ("a" * 4097, "/a" * 33):
        for argv in ([outside, member], [member]):
            assert trust_mod.broker_command_refused(
                argv, root=served.repo) == (
                    trust_mod.REASON_UNREADABLE_COMMAND), len(member)
        assert trust_mod.in_repository_argv(
            [outside, member], root=served.repo) == member
        assert trust_mod.names_a_path_inside(member, root=served.repo)
    for member in ("a" * 4096, "/a" * 32):
        assert trust_mod.broker_command_refused(
            [outside, member], root=served.repo) is None, len(member)
        assert not trust_mod.names_a_path_inside(member, root=served.repo)


def test_R6_the_old_worst_cases_are_judged_in_under_a_second(served):
    """The summary of review 5411026353 ("quadratic memory allocation
    before trust approval"); the holder's ruling, #656 5989835334: a pull
    that delivers a bindings document must not hang the judgment. One
    member of 400 absolute paths took 29 s at fe56c0c4, and 4000 options
    node does not know took seconds, growing with their square; each is
    judged now in under a second."""
    trust_mod = _trust_mod()
    for argv, reason in (
            (["/opt/opendox-test/broker", "/x" * 400],
             trust_mod.REASON_UNREADABLE_COMMAND),
            (["/opt/opendox-test/broker", "/x" * 2048],
             trust_mod.REASON_UNREADABLE_COMMAND),
            (["node", *(["--a"] * 4000)], None),
            (["node", *(["--a"] * 4000), "-e", "x"],
             trust_mod.REASON_INLINE_SCRIPT)):
        started = time.monotonic()
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) == reason, argv[:2]
        assert time.monotonic() - started < 1, argv[:2]


def test_R5_xargs_is_refused_after_the_other_two_judgments(served):
    """r4181006365; the holder's ruling, #656 5988818366: every xargs is
    refused as unreadable, but only after the in-repository and
    inline-script judgments, so each keeps its name (F16.1 as T007 batch P
    amends it); an xargs a launcher starts, or an `env -S` string names, is
    one too, and so is one judged with no root."""
    trust_mod = _trust_mod()
    arguments = served.repo / "args"
    arguments.write_text("x\n", encoding="utf-8")
    outside = "/opt/opendox-test/broker"
    for argv, reason in (
            (["xargs", "-a", str(arguments), outside],
             trust_mod.REASON_IN_REPOSITORY),
            (["xargs", "-n", "1", "python3", "-c", "x"],
             trust_mod.REASON_INLINE_SCRIPT),
            (["xargs", outside], trust_mod.REASON_UNREADABLE_COMMAND),
            (["nice", "xargs", outside],
             trust_mod.REASON_UNREADABLE_COMMAND),
            (["env", "-S", f"xargs {outside}"],
             trust_mod.REASON_UNREADABLE_COMMAND)):
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) == reason, argv
    assert trust_mod.broker_command_refused(["xargs", outside], root=None) == (
        trust_mod.REASON_UNREADABLE_COMMAND)
    assert trust_mod.broker_command_refused(["nice", outside],
                                            root=served.repo) is None


def test_R4_the_effective_pythonpath_is_what_the_broker_has(
        served, monkeypatch):
    """r4180717772; the holder's ruling, #656 5988088910: an inherited
    `PYTHONPATH` entry inside the repository, which the broker's environment
    drops, is no root a module is judged under; `env -i` and `env -u
    PYTHONPATH` clear the inherited entries, as they clear the broker's."""
    from opendox import doxbench_bridge

    trust_mod = _trust_mod()
    tools = served.repo / "tools"
    tools.mkdir()
    library = served.tmp / "library"
    library.mkdir()
    (library / "broker.py").symlink_to(tools / "broker.py")
    monkeypatch.setattr(doxbench_bridge, "INHERITED_ENVIRONMENT",
                        (*doxbench_bridge.INHERITED_ENVIRONMENT,
                         "PYTHONPATH"))
    monkeypatch.setenv("PYTHONPATH", str(tools))       # dropped: inside
    assert trust_mod.broker_command_refused(
        [sys.executable, "-m", "json.tool"], root=served.repo) is None
    monkeypatch.setenv("PYTHONPATH", str(library))     # reaches inside
    assert trust_mod.broker_command_refused(
        [sys.executable, "-m", "broker"], root=served.repo) == (
            trust_mod.REASON_IN_REPOSITORY)
    for cleared in (["env", "-i"], ["env", "-"], ["env", "-u", "PYTHONPATH"],
                    ["env", "--ignore-environment"]):
        argv = [*cleared, sys.executable, "-m", "broker"]
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) is None, argv


def test_R3_a_value_python_reads_is_no_module(served):
    """The other side of reading `-m` by Python's grammar (r4180041213): a
    letter that takes a value ends the cluster, so `-Wm...` is a warning
    filter, and an option of another letter is no module."""
    trust_mod = _trust_mod()
    (served.repo / "tools").mkdir()
    beside = served.repo.parent
    for argv in (["env", "-C", str(beside), sys.executable,
                  f"-Wm{served.repo.name}.tools.broker", str(served.broker)],
                 ["env", "-C", str(beside), sys.executable,
                  f"-Xm{served.repo.name}.tools.broker", str(served.broker)],
                 ["env", "-C", str(beside), sys.executable, "-B",
                  str(served.broker)]):
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) is None, argv


def test_A2_a_broker_outside_the_repository_is_trusted_as_before(
        served, capsys):
    """The rule names files, so what names none is not refused: an option's
    absolute value outside the repository, a URL, a bare word that names no
    file, and options with no value. A member holding a NUL, which no path
    can, is judged without failing (Copilot at openDox-code#86,
    r4179077018). `trust` records it, and the start declares it."""
    trust_mod = _trust_mod()
    argv = [sys.executable, str(served.broker), "--config=/etc/opref.conf",
            "--issuer=https://auth.example/v1", "-v", "--quiet", "plain-word",
            "--profile=/etc/opref\x00.conf", "/etc/opref\x00.conf"]
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.in_repository_program(binding, root=served.repo) is None
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 0
    capsys.readouterr()
    assert trust_mod.verdict_for(binding, root=served.repo).trusted
    assert isinstance(served.port(), provider_mod.BrokeredProviderPort)


def test_A2_a_trusted_broker_edited_in_the_repository_never_runs(
        served, capsys, monkeypatch):
    """The review's case: the binding trusted (here, straight into the
    store, as a store written before the rule), then a pull edits the
    program it runs. Nothing runs: the start refuses it, the gate beneath
    refuses even a verdict that admits it, and so does the console intake's
    own question."""
    trust_mod = _trust_mod()
    argv = _in_repository_argv(served, "absolute", monkeypatch)
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    served.trust.record(binding, root=served.repo)
    canary = served.tmp / "CANARY"
    tool = Path(argv[1])
    tool.write_text(f"open({str(canary)!r}, 'w').close()\n"
                    + tool.read_text(encoding="utf-8"), encoding="utf-8")
    port = served.port()
    assert isinstance(port, trust_mod.UntrustedBindingPort)
    with pytest.raises(trust_mod.BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    assert "install the broker outside the repository" in str(refused.value)
    _no_trust_command_in(str(refused.value), capsys.readouterr().err)
    admitted = trust_mod.TrustVerdict.trusted_for(
        binding, root=served.repo, basis=trust_mod.BASIS_HOST)
    with pytest.raises(trust_mod.BindingUntrusted) as beneath:
        trust_mod.require_admitted(binding, admitted)
    assert trust_mod.REASON_IN_REPOSITORY in str(beneath.value)
    with pytest.raises(binding_mod.BindingRefused):
        provider_mod.mint(binding, trust=admitted)
    trust_mod.unregister()
    trust_mod.register(_AdmitsTheIntake())
    intake = trust_mod.intake_verdict_for(binding, root=served.repo)
    assert not intake.trusted
    assert intake.reason == trust_mod.REASON_IN_REPOSITORY
    assert not canary.exists()
    served.nothing_was_touched()


def test_A2_add_refuses_a_broker_inside_the_repository_and_writes_nothing(
        served, capsys, monkeypatch):
    trust_mod = _trust_mod()
    argv = _in_repository_argv(served, "absolute", monkeypatch)
    adding = served.add_argv("broker")
    adding = adding[:adding.index("--") + 1] + argv
    assert _cli(*adding) == 1
    assert trust_mod.REMEDY_IN_REPOSITORY in capsys.readouterr().err
    assert not binding_mod.bindings_path(served.repo).exists()
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()


# --- A3: an unservable binding is passed over, so 16.4's remedies work -----


def test_A3_the_start_passes_over_a_binding_the_catalog_cannot_list(
        served, capsys):
    """The rail's "No model configured" line offers two remedies, the local
    harness on PATH and another binding. With a binding the catalog cannot
    list declared first, the start declared a refusing port for it and
    neither remedy could take effect. It is passed over, as a pending one
    is, and the start says so by name."""
    from opendox import doxbench_model

    trust_mod = _trust_mod()
    served.hand_write(served.record("env", label="L" * 201))
    assert served.port() is doxbench_model.NO_MODEL_CONFIGURED
    notice = capsys.readouterr().err
    assert (f"[model-provider] model binding {trust_mod.shown(BINDING_ID)} "
            f"is passed over: {trust_mod.REASON_UNSERVABLE}. "
            f"{trust_mod.REMEDY_UNSERVABLE}") in notice
    # remedy (1): the local harness, installed, is what the start declares
    harness = served.port(harness=True)
    assert not isinstance(harness, trust_mod.UntrustedBindingPort)
    assert [entry.model_id for entry in harness.catalog().entries] == [
        "omp-local"]
    # remedy (2): another binding, added, is what the start declares
    second = served.add_argv("env")
    second[second.index("--id") + 1] = "second-model"
    assert _cli(*second) == 0
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    listed = capsys.readouterr().out
    assert "passes over it: the model catalog cannot list" in listed
    port = served.port()
    assert isinstance(port, provider_mod.BrokeredProviderPort)
    assert [entry.model_id for entry in port.catalog().entries] == [
        "second-model"]


# --- A4: a trusted binding's refusal is printed where the rail says --------


@pytest.mark.parametrize("kind", ["env", "broker"])
def test_A4_a_trusted_bindings_refusal_is_printed_once_by_name(
        served, capsys, kind):
    """`UNTRUSTED_BINDING_REMEDY` says a trusted binding is unavailable "for
    the reason this console printed when its provider refused". The broker's
    stderr is not read and the turn's refusal is not printed, so the port
    prints it: one fixed line naming the binding and its fixed diagnostic,
    as it turns unavailable, and not again while it stays so. Here the
    `env:` reference resolves to nothing, or the broker exits without an
    answer."""
    from opendox import doxbench_model

    adding = served.add_argv(kind)
    if kind == "env":
        served.environ.pop(SECRET_NAME)   # the reference resolves to nothing
    else:
        failing = served.tmp / "failing-broker.py"
        failing.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        adding[-1] = str(failing)
    assert _cli(*adding) == 0
    capsys.readouterr()
    port = served.port()
    entry = port.catalog().entries[0]
    for _ in range(2):
        outcome = doxbench_model.dispatch_turn(port, _Envelope(), entry=entry,
                                               clock=time.monotonic)
        assert isinstance(outcome, doxbench_model.TurnDispatchFailure)
    printed = capsys.readouterr().err.splitlines()
    lead = (f"[model-provider] model binding "
            f"{_trust_mod().shown(BINDING_ID)} is unavailable: ")
    said = [line for line in printed if line.startswith(lead)]
    assert len(said) == 1, printed
    assert said[0][len(lead):] in provider_mod.FIXED_DIAGNOSTICS
    assert all(not e.available for e in port.catalog().entries)
    assert SECRET not in "\n".join(printed)


# --- A5: the intake is not offered where no policy could admit it ----------


def _intake_surface(served) -> dict:
    import http.client

    from opendox import serve

    snapshot = served.tmp / "out" / "snapshot.json"
    httpd = serve.build_server(
        REPO_ROOT / "src" / "opendox" / "web", snapshot, served.repo,
        port=0, actor="brett", model_port_factory=lambda: None)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        connection = http.client.HTTPConnection(*base, timeout=30)
        connection.request("GET", "/capabilities")
        own = json.loads(connection.getresponse().read())
        connection.close()
        connection = http.client.HTTPConnection(*base, timeout=30)
        connection.request("GET", "/workbench/model-intake", headers={
            serve.CONSOLE_TOKEN_HEADER: own.get("console_token", "")})
        surface = json.loads(connection.getresponse().read())
        connection.close()
        return surface
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


@pytest.mark.parametrize("policy", ["none-registered", "strict-default",
                                    "no-intake-verdict", "admits"])
def test_A5_the_intake_is_offered_only_where_a_policy_could_admit_it(
        served, policy):
    """A host registers a gate (#77) and a broker is declared. Under
    openDox's own trust (registered or not), or a host policy with no
    `intake_verdict`, every hand-off is refused, so the surface is NOT
    offered and says why; a host policy that answers `intake_verdict` is
    offered it. Asking registers nothing."""
    from opendox import column_seams

    trust_mod = _trust_mod()
    intake_mod.DeclarationStore(intake_mod.declarations_path(
        served.repo)).declare_broker(intake_mod.BrokerDeclaration(
            argv=(sys.executable, str(served.broker))))
    snapshot = served.tmp / "out" / "snapshot.json"
    snapshot.parent.mkdir()
    snapshot.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    trust_mod.unregister()
    if policy == "strict-default":
        trust_mod.register(served.trust)
    elif policy == "no-intake-verdict":
        trust_mod.register(_TrustsEveryBinding())
    elif policy == "admits":
        trust_mod.register(_AdmitsTheIntake())
    column_seams.gate.unregister()
    column_seams.gate.register(_HostGate())
    try:
        surface = _intake_surface(served)
    finally:
        column_seams.gate.unregister()
    if policy == "admits":
        assert surface.get("offered") is True and "reason" not in surface, (
            surface)
    else:
        assert surface.get("offered") is False, surface
        assert surface.get("reason") == trust_mod.INTAKE_NOT_ADMISSIBLE
    assert trust_mod.is_registered() == (policy != "none-registered")
    assert not served.marker.exists()


# --- A6: set-credential's refusal names the document it read --------------


def test_A6_set_credential_prints_the_command_for_the_document_it_read(
        served, capsys):
    import shlex

    trust_mod = _trust_mod()
    record = served.record("broker")
    elsewhere = served.tmp / "elsewhere.yaml"
    elsewhere.write_text(json.dumps({
        "schema_version": 1, "kind": "model-provider-bindings",
        "bindings": [record]}), encoding="utf-8")
    served.hand_write({**record, "label": "Another form"})
    assert _cli("model-binding", "set-credential", "--repo-root",
                str(served.repo), "--bindings", str(elsewhere),
                "--id", BINDING_ID) == 1
    [command] = _printed_commands(capsys.readouterr().err)
    assert "--bindings" in command, command
    assert _cli(*shlex.split(command)[1:]) == 0
    capsys.readouterr()
    refused_for = binding_mod.BindingStore(elsewhere).list()[0]
    assert trust_mod.verdict_for(refused_for, root=served.repo).trusted
    assert not trust_mod.verdict_for(served.declared(),
                                     root=served.repo).trusted


# --- A7: a store refusal names its actual cause ----------------------------


@pytest.mark.parametrize("case", ["torn-json", "newer-schema", "older-schema",
                                  "another-kind", "state-dir-0500",
                                  "state-dir-0500-once-locked"])
def test_A7_a_store_refusal_names_its_cause_and_recovery(served, case):
    """Only a link, an owner or a mode is blamed on another user. A torn
    copy, a newer store, another kind of document and a directory this user
    cannot write each name their own cause, and how to recover. Each is
    refused, by `record` and by the verdict (A9: the kind and the version
    are both checked)."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    planted = json.loads(_planted(served))
    if case == "torn-json":
        _store_holding(served, '{"schema_version": 1, "kind"')
        cause, recovery = "does not read as JSON", trust_mod.RECOVER_MOVE_ASIDE
    elif case == "newer-schema":
        _store_holding(served, {**planted, "schema_version": 2})
        cause, recovery = "schema_version 2", trust_mod.RECOVER_NEWER
    elif case == "older-schema":
        _store_holding(served, {**planted, "schema_version": 0})
        cause = "is not a trust store this install writes"
        recovery = trust_mod.RECOVER_MOVE_ASIDE
    elif case == "another-kind":
        _store_holding(served, {**planted, "kind": "something-else"})
        cause = "is not a trust store this install writes"
        recovery = trust_mod.RECOVER_MOVE_ASIDE
    elif case == "state-dir-0500":
        served.state_dir.mkdir(mode=0o700)
        os.chmod(served.state_dir, 0o500)
        cause, recovery = "cannot be opened", trust_mod.RECOVER_PERMISSIONS
    else:
        # the lock file exists, so it opens; the store's new copy cannot be
        # created beside it
        served.trust.record(_a_binding(id="another-model"), root=served.repo)
        os.chmod(served.state_dir, 0o500)
        cause = "could not be created"
        recovery = trust_mod.RECOVER_PERMISSIONS
    try:
        with pytest.raises(trust_mod.TrustStoreRefused) as refused:
            served.trust.record(served.declared(), root=served.repo)
        verdict = served.trust.verdict(served.declared(), root=served.repo)
    finally:
        os.chmod(served.state_dir, 0o700)
    words = str(refused.value)
    assert "another user could change" not in words, words
    assert cause in words and recovery in words, words
    if not case.startswith("state-dir-0500"):
        assert not verdict.trusted and cause in verdict.reason, verdict


# --- A8: a state directory that is a link trusts nothing -------------------


def test_A8_a_state_directory_that_is_a_link_trusts_nothing(served):
    """F16.1's ratified text (the holder's ruling, openxFactory#656 comment
    5982436447): "With the trust file, or a directory that holds it,
    replaced by a symbolic link ... every binding reads untrusted". Here
    the link is this user's own and reaches a private directory of this
    user's own holding a store that would trust the binding."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    real = served.tmp / "real-state"
    real.mkdir(mode=0o700)
    planted = real / trust_mod.TRUST_FILENAME
    planted.write_text(_planted(served), encoding="utf-8")
    os.chmod(planted, 0o600)
    served.state_dir.symlink_to(real, target_is_directory=True)
    verdict = served.trust.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted
    assert "the directory that holds the store is a symbolic link" in (
        verdict.reason)
    held = planted.read_bytes()
    with pytest.raises(trust_mod.TrustStoreRefused):
        served.trust.record(served.declared(), root=served.repo)
    assert planted.read_bytes() == held


# --- A9: the store rules the suite did not pin ------------------------------


def test_A9_an_ancestor_others_could_write_trusts_nothing_unless_sticky(
        served):
    """G1. A directory above the store that another user could write, and
    that is not sticky, could have the store's directory renamed away and
    replaced; with the sticky bit set, it could not."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    shared = served.tmp / "shared"
    shared.mkdir()
    os.chmod(shared, 0o777)
    (shared / "st").mkdir(mode=0o700)
    store = shared / "st" / trust_mod.TRUST_FILENAME
    store.write_text(_planted(served), encoding="utf-8")
    os.chmod(store, 0o600)
    policy = trust_mod.MachineTrust(state_dir=shared / "st")
    verdict = policy.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted and "is not sticky" in verdict.reason, verdict
    os.chmod(shared, 0o1777)
    assert policy.verdict(served.declared(), root=served.repo).trusted


def test_A9_a_link_above_the_store_in_a_directory_others_could_write(served):
    """G2. The directories judged include those the state directory is
    SPELLED under, not only those it resolves under: a link above it, in a
    directory another user could write, could be repointed."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    real = served.tmp / "real"
    (real / "st").mkdir(mode=0o700, parents=True)
    os.chmod(real, 0o700)
    store = real / "st" / trust_mod.TRUST_FILENAME
    store.write_text(_planted(served), encoding="utf-8")
    os.chmod(store, 0o600)
    shared = served.tmp / "shared"
    shared.mkdir()
    os.chmod(shared, 0o777)
    (shared / "link").symlink_to(real, target_is_directory=True)
    policy = trust_mod.MachineTrust(state_dir=shared / "link" / "st")
    verdict = policy.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted and "is not sticky" in verdict.reason, verdict
    os.chmod(shared, 0o755)
    assert policy.verdict(served.declared(), root=served.repo).trusted


def test_A9_a_link_above_the_store_owned_by_another_user_trusts_nothing(
        served, monkeypatch):
    """A link above the state directory that another user owns could be
    pointed elsewhere by them. The other owner is the system's answer, so
    `lstat` answers it here."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    real = served.tmp / "real"
    (real / "st").mkdir(mode=0o700, parents=True)
    store = real / "st" / trust_mod.TRUST_FILENAME
    store.write_text(_planted(served), encoding="utf-8")
    os.chmod(store, 0o600)
    link = served.tmp / "link"
    link.symlink_to(real, target_is_directory=True)
    policy = trust_mod.MachineTrust(state_dir=link / "st")
    assert policy.verdict(served.declared(), root=served.repo).trusted

    def lstat(path, *args, **kwargs):
        info = os.lstat(path, *args, **kwargs)
        if os.fspath(path) != str(link):
            return info
        fields = list(info[:10])
        fields[4] = os.getuid() + 4242
        return os.stat_result(fields)

    monkeypatch.setattr(trust_mod, "os", _OsWith(lstat=lstat))
    verdict = policy.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted, verdict
    assert f"owned by uid {os.getuid() + 4242}" in verdict.reason


def test_A9_the_lock_and_the_store_are_opened_without_waiting(
        served, monkeypatch):
    """Round 8 (r4178064601): both are opened non-blocking, so a FIFO in
    either's place is refused by its type rather than waited on. Opening a
    FIFO for reading and writing never waits on Linux, so the flag itself is
    what is held."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    opened: dict[str, int] = {}

    def spy(path, flags, *args, **kwargs):
        opened[os.path.basename(os.fspath(path))] = flags
        return os.open(path, flags, *args, **kwargs)

    monkeypatch.setattr(trust_mod, "os", _OsWith(open=spy))
    served.trust.record(served.declared(), root=served.repo)
    assert served.trust.verdict(served.declared(), root=served.repo).trusted
    for name in (trust_mod.TRUST_LOCK_FILENAME, trust_mod.TRUST_FILENAME):
        assert opened[name] & os.O_NONBLOCK, (name, opened)


def test_A9_a_refused_intake_body_is_drained_unread(served, monkeypatch):
    """The console intake refused at its hand-off drains the body it was
    sent, unread, so the connection answers rather than stalls."""
    from opendox import serve_workbench

    drained = []
    real = serve_workbench._drain_refused_body

    def spy(rfile, length):
        drained.append(length)
        return real(rfile, length)

    monkeypatch.setattr(serve_workbench, "_drain_refused_body", spy)
    _caps, answer = _served_intake(served)
    assert answer.get("reason") == _trust_mod().INTAKE_BROKER_UNTRUSTED
    assert drained == [len(b"sk-stand-in-NOT-A-KEY")]
    assert not served.marker.exists()


def test_A9_a_directory_made_for_the_store_is_judged_once_made(
        served, monkeypatch):
    """`_make_private_directories` judges each directory it makes by its
    own descriptor once made. A system that leaves one writable by others
    (here, a chmod between the make and the open) has it refused."""
    trust_mod = _trust_mod()

    def mkdir(name, mode=0o777, *, dir_fd=None):
        os.mkdir(name, mode, dir_fd=dir_fd)
        os.chmod(name, 0o770, dir_fd=dir_fd)

    monkeypatch.setattr(trust_mod, "os", _OsWith(mkdir=mkdir))
    with pytest.raises(trust_mod.TrustStoreRefused) as refused:
        trust_mod._make_private_directories(served.tmp / "made" / "st")
    assert "is writable by its group" in str(refused.value)


def test_A9_and_A17_the_store_and_its_directory_are_synced(
        served, monkeypatch):
    """The store's bytes are synced before the replace (A9), and the state
    directory after it (A17), so a crash after `record` returns can neither
    lose the new store's bytes nor bring back the store it replaced."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    served.trust.record(_a_binding(id="another-model"), root=served.repo)
    events: list[tuple] = []

    def fsync(descriptor):
        info = os.fstat(descriptor)
        events.append(("fsync", stat.S_ISDIR(info.st_mode), info.st_ino))
        return os.fsync(descriptor)

    def replace(source, target, *args, **kwargs):
        events.append(("replace", os.path.basename(os.fspath(target))))
        return os.replace(source, target, *args, **kwargs)

    monkeypatch.setattr(trust_mod, "os", _OsWith(fsync=fsync,
                                                 replace=replace))
    served.trust.record(served.declared(), root=served.repo)
    at = events.index(("replace", trust_mod.TRUST_FILENAME))
    assert any(event[0] == "fsync" and not event[1]
               for event in events[:at]), events
    directory = os.stat(served.state_dir).st_ino
    assert ("fsync", True, directory) in events[at + 1:], events


# --- A10: no raw path reaches the terminal ---------------------------------


def test_A10_a_repositorys_path_is_printed_escaped(served, capsys):
    root = served.fresh_repository("r\x1b[8m\n  forged line")
    served.hand_write(served.record("env"), root=root)
    assert _cli("model-binding", "list", "--repo-root", str(root)) == 0
    assert _cli("model-binding", "trust", "--repo-root", str(root),
                "no-such-binding") == 1
    adding = served.add_argv("env")
    adding[adding.index("--repo-root") + 1] = str(root)
    adding[adding.index("--id") + 1] = "second-model"
    assert _cli(*adding) == 0
    captured = capsys.readouterr()
    for text in (captured.out, captured.err):
        assert "\x1b" not in text and "\n  forged line" not in text, (
            repr(text[:300]))
        assert "\\u001b[8m" in text


# --- A11: a failed edit leaves the trusted form trusted ---------------------


def test_A11_an_edit_whose_write_fails_keeps_the_trusted_form_trusted(
        served, capsys):
    trust_mod = _trust_mod()
    assert _cli(*served.add_argv("env")) == 0
    capsys.readouterr()
    before = served.declared()
    document = binding_mod.bindings_path(served.repo)
    editing = served.add_argv("env")
    editing[1] = "edit"
    editing[editing.index("--label") + 1] = "Renamed"
    os.chmod(document, 0o444)
    os.chmod(document.parent, 0o555)
    try:
        rc = _cli(*editing)
    finally:
        os.chmod(document.parent, 0o755)
        os.chmod(document, 0o644)
    err = capsys.readouterr().err
    assert rc == 1
    assert "could not be written" in err and "nothing in it changed" in err
    assert served.declared() == before
    assert trust_mod.verdict_for(before, root=served.repo).trusted


# --- A12: a verdict subclass admits nothing --------------------------------


def test_A12_a_verdict_subclass_cannot_admit_another_binding(served):
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))

    class Lax(trust_mod.TrustVerdict):
        def admits(self, binding):
            return True

    lax = Lax(binding_id="some-other-binding", digest="sha256:0",
              root=trust_mod.resolved_root(served.repo), trusted=True,
              basis=trust_mod.BASIS_HOST)

    class Host:
        def verdict(self, binding, *, root):
            return lax

        def record(self, binding, *, root):
            return lax

    trust_mod.unregister()
    trust_mod.register(Host())
    port = served.port()
    assert isinstance(port, trust_mod.UntrustedBindingPort), port
    with pytest.raises(trust_mod.BindingUntrusted):
        trust_mod.require_admitted(served.declared(), lax)
    # beneath both: the provider's port lists nothing available for one,
    # even a subclass that names this very binding
    exact = trust_mod.TrustVerdict.trusted_for(
        served.declared(), root=served.repo, basis=trust_mod.BASIS_HOST)
    lookalike = Lax(**{field.name: getattr(exact, field.name)
                       for field in dataclasses.fields(exact)})
    brokered = provider_mod.BrokeredProviderPort(
        served.declared(), install_mod.brokered_catalog(served.declared()),
        trust=lookalike)
    assert not any(entry.available for entry in brokered.catalog().entries)
    served.nothing_was_touched()


# --- A13: the seam is read once, inside the refusal net ---------------------


def test_A13_a_host_torn_down_while_the_default_registers_records_anyway(
        served, monkeypatch):
    """`policy()` registered the default, then read the seam: a host that
    unregistered between the two left the read nothing, and `recorded_for`
    raised a `RuntimeError` no verb catches. It is one operation now."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    real = trust_mod.register_default

    def then_torn_down():
        held = real()
        trust_mod.unregister()
        return held

    monkeypatch.setattr(trust_mod, "register_default", then_torn_down)
    trust_mod.unregister()
    verdict = trust_mod.recorded_for(served.declared(), root=served.repo)
    assert verdict.admits(served.declared())


def test_A13_a_seam_that_fails_is_refused_by_name(served, monkeypatch):
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))

    def fails():
        raise RuntimeError(SECRET)

    monkeypatch.setattr(trust_mod, "policy", fails)
    with pytest.raises(trust_mod.TrustNotRecorded) as refused:
        trust_mod.recorded_for(served.declared(), root=served.repo)
    assert SECRET not in str(refused.value)


# --- A15: no case reads this machine's own trust ----------------------------


_A15_SEEN: list[str] = []


@pytest.fixture(scope="module")
def _a15_module_setting():
    """`OPENDOX_STATE_DIR` as a module-scoped fixture sees it: set up before
    any case's own fixtures, so it is the session's."""
    return os.environ.get("OPENDOX_STATE_DIR")


def test_A15_a_case_has_a_scratch_state_directory_of_its_own(
        tmp_path_factory, _a15_module_setting):
    """The root conftest gives the session, and every case, a scratch
    `OPENDOX_STATE_DIR` under this run's own temporary directory, so no
    case and no wider fixture reads or writes the operator's trust. This
    case also leaves a policy registered, which the next one proves was
    dropped."""
    trust_mod = _trust_mod()
    trust_mod.unregister()
    trust_mod.register(_TrustsEveryBinding())
    setting = os.environ.get("OPENDOX_STATE_DIR")
    assert setting, "no scratch state directory: the operator's is read"
    assert _a15_module_setting, "a module fixture reads the operator's"
    base = tmp_path_factory.getbasetemp().resolve()
    for each in (setting, _a15_module_setting):
        assert base in Path(each).resolve().parents, each
    assert setting != _a15_module_setting
    assert trust_mod.MachineTrust().state_dir() == Path(setting)
    _A15_SEEN.append(setting)


def test_A15_the_seam_is_emptied_after_every_case():
    """Runs after the case above, which left a policy registered, and has a
    state directory of its own."""
    assert not _trust_mod().is_registered()
    assert os.environ.get("OPENDOX_STATE_DIR") not in _A15_SEEN


# --- A16: a digest of another scheme is not a "changed" binding -------------


def test_A16_a_digest_of_another_scheme_reads_as_another_record_form(
        served, capsys):
    import shlex

    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    planted = json.loads(_planted(served))
    digest = planted["entries"][0]["digest"]
    assert digest.startswith(trust_mod.DIGEST_PREFIX)
    planted["entries"][0]["digest"] = "sha256/2:" + digest.split(":", 1)[1]
    _store_holding(served, planted)
    verdict = served.trust.verdict(served.declared(), root=served.repo)
    assert not verdict.trusted
    assert verdict.reason == trust_mod.REASON_RECORD_FORM
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 0
    [command] = _printed_commands(capsys.readouterr().out)
    assert _cli(*shlex.split(command)[1:]) == 0
    assert served.trust.verdict(served.declared(), root=served.repo).trusted


def test_A16_the_digest_scheme_names_every_field_of_the_record():
    """Adding a field to the binding record changes every digest, so it
    must change the digest's scheme too: the scheme's field list is pinned to
    the record's."""
    trust_mod = _trust_mod()
    assert trust_mod.DIGEST_SCHEME_FIELDS == binding_mod.BINDING_FIELDS
    assert set(_a_binding().as_record()) == {
        "kind", *trust_mod.DIGEST_SCHEME_FIELDS}


# --- A18: the directory the store's tree is made from is judged ------------


def test_A18_the_directory_the_store_is_made_in_is_judged_first(served):
    trust_mod = _trust_mod()
    shared = served.tmp / "shared"
    shared.mkdir()
    os.chmod(shared, 0o777)
    with pytest.raises(trust_mod.TrustStoreRefused) as refused:
        trust_mod._make_private_directories(shared / "st")
    assert "is not sticky" in str(refused.value)
    assert not (shared / "st").exists()


# --- A19: an approval never calls a trusted binding untrusted --------------


def test_A19_an_approval_reads_this_machines_store_where_nothing_registered(
        served):
    """Nothing registered in the serving process yet (its console started
    with only the pending binding, so the factory never asked), and this
    machine's store trusts the approved binding: the approval says it is
    available, and registers nothing."""
    trust_mod = _trust_mod()
    _caps, answer = _served_intake(served, host_policy=_AdmitsTheIntake())
    assert answer.get("error") is None, answer
    served.trust.record(served.declared(), root=served.repo)
    trust_mod.unregister()
    approval = _post_an_approval(served, BINDING_ID)
    assert approval.get("ok") is True, approval
    assert approval["availability"] == intake_mod.APPROVAL_NOTICE
    assert not trust_mod.is_registered()


# --- N1: a settings document reached through a link is refused -------------


@pytest.mark.parametrize("link", ["document", "its-directory"])
def test_N1_add_never_writes_through_a_link_a_clone_carries(
        served, capsys, link):
    """A clone carries a link as readily as a file. One at the bindings
    document's path, or at a directory of its default path, would have
    `add` create or overwrite a file wherever it points."""
    outside = served.tmp / "outside"
    outside.mkdir()
    document = binding_mod.bindings_path(served.repo)
    if link == "document":
        document.parent.mkdir(parents=True)
        document.symlink_to(outside / "created-by-add")
        named = document
    else:
        document.parent.parent.mkdir(parents=True)
        document.parent.symlink_to(outside, target_is_directory=True)
        named = document.parent
    assert _cli(*served.add_argv("env")) == 1
    err = capsys.readouterr().err
    assert "symbolic link" in err and str(named) in err, err
    assert list(outside.iterdir()) == []
    assert _cli("model-binding", "list", "--repo-root", str(served.repo)) == 1
    assert "symbolic link" in capsys.readouterr().err


def test_N1_each_stores_write_refuses_a_link_by_itself(served):
    """The read refuses a link first, so the write's own refusal is asked
    directly: a link planted after a read is never written through."""
    outside = served.tmp / "outside"
    outside.mkdir()
    for path, store, refused, write in (
            (binding_mod.bindings_path(served.repo), binding_mod.BindingStore,
             binding_mod.BindingRefused,
             lambda store: store._save([_a_binding()])),
            (intake_mod.declarations_path(served.repo),
             intake_mod.DeclarationStore, intake_mod.IntakeRefused,
             lambda store: store._save(None, []))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(outside / path.name)
        with pytest.raises(refused) as said:
            write(store(path))
        assert "symbolic link" in str(said.value)
    assert list(outside.iterdir()) == []


def test_N1_the_declarations_document_is_never_written_through_a_link(
        served):
    outside = served.tmp / "outside"
    outside.mkdir()
    document = intake_mod.declarations_path(served.repo)
    document.parent.mkdir(parents=True)
    document.symlink_to(outside / "created-by-intake")
    with pytest.raises(intake_mod.IntakeRefused) as refused:
        _propose(served.repo, BINDING_ID)
    assert "symbolic link" in str(refused.value)
    assert list(outside.iterdir()) == []


# --- N2: an unreadable settings document is refused by name ---------------


UNREADABLE = {"not-utf-8": (b"\xff\xfe\x00schema_version: 1\n", "not UTF-8"),
              "nested": (b"[" * 1000 + b"]" * 1000, "nests too deeply"),
              "no-permission": (b"schema_version: 1\n", "cannot be read"),
              # the holder's ruling, openxFactory#656 comment 5985046107, C3:
              # valid YAML whose timestamp cannot be constructed
              "unconstructable": (
                  b"schema_version: 1\nkind: model-provider-bindings\n"
                  b"bindings: []\nnote: 2024-13-01\n",
                  "is not readable YAML")}


@contextlib.contextmanager
def _unreadable(document: Path, case: str):
    """`document` holding `case`'s bytes, and, for "no-permission", a mode
    this user cannot read, restored afterwards."""
    raw, _said = UNREADABLE[case]
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(raw)
    if case == "no-permission":
        os.chmod(document, 0)
    try:
        yield
    finally:
        os.chmod(document, 0o644)


@pytest.mark.parametrize("case", sorted(UNREADABLE))
def test_N2_an_unreadable_bindings_document_is_refused_by_name(
        served, capsys, case):
    """Not UTF-8, or nested past what the parser can descend: refused BY
    NAME, never a raw error, and the console's start reads it as declaring
    no binding and says why."""
    from opendox import doxbench_model

    _raw, said = UNREADABLE[case]
    document = binding_mod.bindings_path(served.repo)
    with _unreadable(document, case):
        with pytest.raises(binding_mod.BindingRefused) as refused:
            binding_mod.BindingStore(document).list()
        assert said in str(refused.value)
        assert served.port() is doxbench_model.NO_MODEL_CONFIGURED
        assert said in capsys.readouterr().err
        assert _cli("model-binding", "list", "--repo-root",
                    str(served.repo)) == 1
        assert said in capsys.readouterr().err


@pytest.mark.parametrize("case", sorted(UNREADABLE))
def test_N2_an_unreadable_declarations_document_is_refused_by_name(
        served, case):
    _raw, said = UNREADABLE[case]
    document = intake_mod.declarations_path(served.repo)
    with _unreadable(document, case):
        with pytest.raises(intake_mod.IntakeRefused) as refused:
            intake_mod.DeclarationStore(document).get(BINDING_ID)
        assert said in str(refused.value)
        # the console's start reads it as declaring nothing pending
        assert not intake_mod.pending_binding_ids(served.repo)


@contextlib.contextmanager
def _unsearchable(directory: Path):
    """`directory` with a mode this user cannot search, restored after."""
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0)
    try:
        yield
    finally:
        os.chmod(directory, 0o755)


def test_N2_a_bindings_document_behind_an_unsearchable_directory_is_refused(
        served, capsys):
    """The look before the read refuses BY NAME too (Copilot at
    openDox-code#86, r4179241603): a directory on the way to the bindings
    document that this user cannot search fails the link check and the
    presence check themselves, and the console's start still reads it as
    declaring no binding and says why."""
    from opendox import doxbench_model

    document = binding_mod.bindings_path(served.repo)
    with _unsearchable(document.parent):
        # The presence check raises rather than read it as absent, so a
        # Python whose `Path.is_symlink` swallows the error refuses it too.
        with pytest.raises(PermissionError):
            binding_mod.document_present(document)
        with pytest.raises(binding_mod.BindingRefused) as refused:
            binding_mod.BindingStore(document).list()
        assert "cannot be read" in str(refused.value)
        assert served.port() is doxbench_model.NO_MODEL_CONFIGURED
        assert "cannot be read" in capsys.readouterr().err
        assert _cli("model-binding", "list", "--repo-root",
                    str(served.repo)) == 1
        assert "cannot be read" in capsys.readouterr().err


def test_N2_a_declarations_document_behind_an_unsearchable_directory_is_refused(
        served):
    document = intake_mod.declarations_path(served.repo)
    with _unsearchable(document.parent):
        with pytest.raises(intake_mod.IntakeRefused) as refused:
            intake_mod.DeclarationStore(document).get(BINDING_ID)
        assert "cannot be read" in str(refused.value)
        # the console's start reads it as declaring nothing pending
        assert not intake_mod.pending_binding_ids(served.repo)


def test_N2_a_missing_settings_document_still_declares_nothing(served):
    """The hosted path is kept: a document that is not there, or a file
    where a directory belongs on the way to it, is absent, not refused."""
    for document in (binding_mod.bindings_path(served.repo),
                     intake_mod.declarations_path(served.repo)):
        assert not binding_mod.document_present(document)
    blocker = served.tmp / "a-file"
    blocker.write_text("", encoding="utf-8")
    assert not binding_mod.document_present(blocker / "bindings.yaml")
    assert not binding_mod.BindingStore(blocker / "bindings.yaml").list()


# ===========================================================================
# 7. Copilot's first review of openDox-code#86 (review 5407887563), and A2
#    EXTENDED (RULED by Brett Heap, openxFactory#656 comment 5983805990,
#    "Refuse inline scripts (Recommended)"). Each fails at `3e4958ab`.
# ===========================================================================


def test_A11_a_failed_edit_never_overwrites_a_trust_recorded_meanwhile(
        served, capsys, monkeypatch):
    """r4179076901. Edit A records its form, edit B records and writes
    another, and A's write then fails: A's undoing must not trust its stale
    form over B's. It is undone only while the store still holds A's
    form, under the store's lock."""
    assert _cli(*served.add_argv("env")) == 0
    capsys.readouterr()
    before = served.declared()
    meanwhile = dataclasses.replace(before, label="Recorded meanwhile")

    def edit(store, binding):
        served.trust.record(meanwhile, root=served.repo)  # edit B, recorded
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(binding_mod.BindingStore, "edit", edit)
    editing = served.add_argv("env")
    editing[1] = "edit"
    editing[editing.index("--label") + 1] = "Renamed"
    assert _cli(*editing) == 1
    assert "could not be written" in capsys.readouterr().err
    assert served.trust.verdict(meanwhile, root=served.repo).trusted
    assert not served.trust.verdict(before, root=served.repo).trusted


def test_A11_a_write_that_fails_part_way_leaves_the_document_as_it_was(
        served, capsys, monkeypatch):
    """r4179076956. A full disk part way through the write: the document
    is replaced atomically, so it reads as it did, no partial copy is left
    beside it, and the refusal's "nothing in it changed" is true. Both
    stores write so."""
    trust_mod = _trust_mod()
    assert _cli(*served.add_argv("env")) == 0
    capsys.readouterr()
    _propose(served.repo, "first-model")
    document = binding_mod.bindings_path(served.repo)
    declarations = intake_mod.declarations_path(served.repo)
    held, kept = document.read_bytes(), declarations.read_bytes()
    before = served.declared()

    def half_then_full(handle, text):
        handle.write(text[:len(text) // 2])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(binding_mod, "_write_all", half_then_full)
    editing = served.add_argv("env")
    editing[1] = "edit"
    editing[editing.index("--label") + 1] = "Renamed"
    assert _cli(*editing) == 1
    err = capsys.readouterr().err
    assert "could not be written" in err and "nothing in it changed" in err
    assert document.read_bytes() == held
    assert trust_mod.verdict_for(before, root=served.repo).trusted
    with pytest.raises(OSError):
        _propose(served.repo, "second-model")
    assert declarations.read_bytes() == kept
    assert sorted(path.name for path in document.parent.iterdir()) == sorted(
        [declarations.name, document.name])


def _umask_mode() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return 0o666 & ~mask


@pytest.mark.parametrize("document", ["bindings", "declarations"])
def test_R3_a_new_document_is_never_seen_in_part(served, capsys, monkeypatch,
                                                 document):
    """Copilot at openDox-code#86, r4180041167; the holder's ruling,
    openxFactory#656 comment 5986391296: a document that does not exist yet
    is written whole beside its place and published with a hard link, so
    while it is written its place holds nothing, and after it holds all of
    it, with the mode a new file takes here and nothing left beside it. The
    first `add`, and the first intake write."""
    path = (binding_mod.bindings_path(served.repo) if document == "bindings"
            else intake_mod.declarations_path(served.repo))
    seen = []
    real = binding_mod._write_all

    def watching(handle, text):
        seen.append(path.exists())
        real(handle, text)

    monkeypatch.setattr(binding_mod, "_write_all", watching)
    if document == "bindings":
        assert _cli(*served.add_argv("env")) == 0
        capsys.readouterr()
        assert served.declared().id == BINDING_ID
    else:
        _propose(served.repo, "first-model")
        assert intake_mod.pending_binding_ids(served.repo) == {"first-model"}
    assert seen == [False]
    assert stat.S_IMODE(path.stat().st_mode) == _umask_mode()
    assert path.stat().st_nlink == 1
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


@pytest.mark.parametrize("document", ["bindings", "declarations"])
def test_R3_a_document_made_meanwhile_is_never_overwritten(
        served, capsys, monkeypatch, document):
    """A document another process makes while this one writes its first is
    never overwritten: the hard link refuses (`File exists`), this write is
    refused by name, the other document stands as it was written, and
    nothing is left beside it. An `add` refused so withdraws the trust it
    recorded (C2)."""
    path = (binding_mod.bindings_path(served.repo) if document == "bindings"
            else intake_mod.declarations_path(served.repo))
    theirs = b"# another process's document\n"
    real = binding_mod._write_all

    def meanwhile(handle, text):
        real(handle, text)
        path.write_bytes(theirs)

    monkeypatch.setattr(binding_mod, "_write_all", meanwhile)
    if document == "bindings":
        assert _cli(*served.add_argv("env")) == 1
        err = capsys.readouterr().err
        assert "could not be written (File exists)" in err, err
        assert not _held_entries(served)
    else:
        with pytest.raises(FileExistsError):
            _propose(served.repo, "first-model")
    assert path.read_bytes() == theirs
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def test_N1_a_relative_path_that_is_the_default_is_judged_whole(
        served, monkeypatch):
    """r4179076919. Run from the repository's root, the default path is
    exactly as long as the default relative path, and a link at a directory
    of it is refused all the same, by both stores."""
    outside = served.tmp / "outside"
    outside.mkdir()
    (served.repo / "ideation").mkdir()
    (served.repo / "ideation" / "dashboard").symlink_to(
        outside, target_is_directory=True)
    monkeypatch.chdir(served.repo)
    with pytest.raises(binding_mod.BindingRefused) as refused:
        binding_mod.BindingStore(binding_mod.bindings_path(".")).add(
            _a_binding())
    assert "symbolic link" in str(refused.value)
    with pytest.raises(intake_mod.IntakeRefused):
        _propose(Path("."), BINDING_ID)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("link", ["document", "its-directory"])
def test_N1_bindings_named_on_the_command_line_are_never_written_through_a_link(
        served, capsys, link):
    """r4179076934. `--bindings` was resolved before the store saw it, which
    erased the link. It is made absolute instead, so the store refuses it."""
    outside = served.tmp / "outside"
    outside.mkdir()
    document = binding_mod.bindings_path(served.tmp / "named")
    document.parent.parent.mkdir(parents=True)
    if link == "document":
        document.parent.mkdir()
        document.symlink_to(outside / "created-by-add")
    else:
        document.parent.symlink_to(outside, target_is_directory=True)
    adding = served.add_argv("env")
    adding[adding.index("--repo-root") + 2:adding.index("--repo-root") + 2] = [
        "--bindings", str(document)]
    assert _cli(*adding) == 1
    assert "symbolic link" in capsys.readouterr().err
    assert list(outside.iterdir()) == []


def test_N2_every_refusal_of_a_document_prints_its_path_escaped(
        served, capsys):
    """r4179076973, r4179076986. A checkout whose path holds a terminal
    control and a newline: a linked document, and an unreadable one, are
    each refused with the path escaped, by the start and by `list`."""
    root = served.fresh_repository("r\x1b[8m\n  forged line")
    outside = served.tmp / "outside"
    outside.mkdir()
    document = binding_mod.bindings_path(root)
    document.parent.mkdir(parents=True)
    for plant in ("link", "not-utf-8"):
        if plant == "link":
            document.symlink_to(outside / "x.yaml")
        else:
            document.unlink()
            document.write_bytes(b"\xff\xfe")
        served.port(root)
        assert _cli("model-binding", "list", "--repo-root", str(root)) == 1
        captured = capsys.readouterr()
        for text in (captured.out, captured.err):
            assert "\x1b" not in text and "\n  forged line" not in text, (
                repr(text[:300]))
        assert "\\u001b[8m" in captured.err


def test_A5_an_intake_broker_the_rules_refuse_is_not_offered(served):
    """r4179077029. A host that admits the intake, and a declarations
    document naming a broker inside the served repository, or an inline
    script: every hand-off is refused before the host is asked, so the
    surface is not offered, and says why."""
    from opendox import column_seams

    trust_mod = _trust_mod()
    tool = served.repo / "tools" / "broker.py"
    tool.parent.mkdir()
    shutil.copy(served.broker, tool)
    store = intake_mod.DeclarationStore(intake_mod.declarations_path(
        served.repo))
    snapshot = served.tmp / "out" / "snapshot.json"
    snapshot.parent.mkdir()
    snapshot.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    trust_mod.unregister()
    trust_mod.register(_AdmitsTheIntake())
    column_seams.gate.unregister()
    column_seams.gate.register(_HostGate())
    try:
        for argv in ((sys.executable, str(tool)),
                     ("/bin/sh", "-c", "exec ./tools/broker.py")):
            store.declare_broker(intake_mod.BrokerDeclaration(argv=argv))
            surface = _intake_surface(served)
            assert surface.get("offered") is False, surface
            assert surface.get("reason") == trust_mod.INTAKE_BROKER_REFUSED
        store.declare_broker(intake_mod.BrokerDeclaration(
            argv=(sys.executable, str(served.broker))))
        assert _intake_surface(served).get("offered") is True
    finally:
        column_seams.gate.unregister()


INLINE = {
    "sh-c": ["/bin/sh", "-c", "exec ./tools/broker.py"],
    "bash-lc": ["bash", "-lc", "exec ./tools/broker.py"],
    "sh-ec": ["sh", "-ec", "exec ./tools/broker.py"],
    "zsh-c": ["zsh", "-c", "x"],
    "dash-c": ["dash", "-c", "x"],
    "python-c": [sys.executable, "-c", "import runpy"],
    "python3-Sc": ["python3", "-Sc", "x"],
    "node-e": ["node", "-e", "x"],
    "node-eval": ["node", "--eval=x"],
    "node-p": ["node", "-p", "x"],
    "perl-e": ["perl", "-e", "x"],
    "perl-ne": ["perl", "-ne", "x"],
    "ruby-e": ["ruby", "-e", "x"],
    "php-r": ["php", "-r", "x"],
    "pwsh-command": ["pwsh", "-Command", "x"],
    "env-wrapped": ["/usr/bin/env", "sh", "-c", "x"],
    "env-split-string": ["env", "-S", "sh -c x"],
    "timeout-wrapped": ["timeout", "5", "bash", "-c", "x"],
    "busybox-wrapped": ["busybox", "sh", "-c", "x"],
    "unknown-wrapper": ["/opt/opendox-test/wrap", "sh", "-c", "x"],
    "xargs-wrapped": ["xargs", "-0", "sh", "-c", "x"],
    "sudo-wrapped": ["sudo", "-u", "bob", "bash", "-c", "x"],
    "env-python": ["/usr/bin/env", "python3", "-c", "x"],
    "env-split-python": ["env", "-S", "python3 -c x"],
    # Copilot at openDox-code#86, r4179241583: an attached script, and an
    # inline option after options that take values, read by grammar.
    "python-attached": [sys.executable, "-cprint(1)"],
    "python-cluster-attached": ["python3", "-Bcprint(1)"],
    "python-value-then-c": ["python3", "-W", "ignore", "-c", "x"],
    "ruby-attached": ["ruby", "-eputs(1)"],
    "perl-digits-then-e": ["perl", "-l0e", "x"],
    "php-B": ["php", "-B", "x"],
    "lua-e": ["lua", "-e", "x"],
    "osascript-e": ["osascript", "-e", "x"],
    "node-require-then-e": ["node", "--require", "mod", "-e", "x"],
    "su-c": ["su", "bob", "-c", "x"],
    "runuser-command": ["runuser", "-u", "bob", "--command=x"],
    "pwsh-policy-then-command": ["pwsh", "-ExecutionPolicy", "Bypass",
                                 "-Command", "x"],
    # r4181006345; the holder's ruling, #656 5988818366: a long option the
    # table does not know is read as a flag and as taking the next member
    "node-unknown-value-option-then-e": ["node", "--v8-pool-size", "1",
                                         "-e", "x", "--"],
    "node-flag-then-e": ["node", "--no-warnings", "-e", "x"],
    "pwsh-flag-then-command": ["pwsh", "-NoProfile", "-Command", "x"],
    # pwsh reads every member before its command (`operands=None`),
    # fail-closed: a word before `-Command` hides none
    "pwsh-a-word-then-command": ["pwsh", "x", "-Command", "y"],
    "node-flag-a-file-then-e": ["node", "--no-warnings", "/opt/x.js", "-e",
                                "x"],
    "pwsh-encoded": ["powershell", "-EncodedCommand", "eAA="],
    "fish-C": ["fish", "-C", "x"],
    "bash-plus-o-then-c": ["bash", "+o", "posix", "-c", "x"],
    # Lane openXfactory-3 D7 early findings N1 and N2, holder ruled fix now
    "julia-e": ["julia", "-e", "x"],
    "julia-eval": ["julia", "--eval=x"],
    "julia-E": ["julia", "--threads", "2", "-E", "x"],
    "Rscript-e": ["Rscript", "-e", "x"],
    "R-e": ["R", "--no-echo", "-e", "x"],
    "R-file-then-e": ["R", "-f", "/opt/opendox-test/x.R", "-e", "x"],
    # Lane openXfactory-3 D7 F1, holder ruled fix now (#656 5988369111)
    "raku-e": ["raku", "-e", "x"],
    "deno-quiet-eval": ["deno", "--quiet", "eval", "x"],
    "deno-q-eval": ["deno", "-q", "eval", "x"],
    "deno-log-level-eval": ["deno", "--log-level", "info", "eval", "x"],
    # The holder's ruling, openxFactory#656 comment 5985046107, C1: env's
    # long options by any unambiguous beginning, and its clusters.
    "env-split-string-abbreviated": ["env", "--split=sh -c x"],
    "env-split-string-abbreviated-next": ["env", "--spl", "sh -c x"],
    "env-split-string-bundled": ["env", "-iS", "sh -c x"],
    "env-split-string-bundled-attached": ["env", "-iSsh -c x"],
    "env-unset-bundled": ["env", "-0u", "NAME", "sh", "-c", "x"],
    # A string env would not split as a shell does is refused as an inline
    # script (F16.1 as T007 batch P amends it; 5985046107, C1): a backslash
    # (env reads `\\_` as a space), a `$`, a `#`, or a quote left open.
    "split-string-escape": ["env", "-S", "sh\\_-c\\_id"],
    "split-string-variable": ["env", "-S", "$BROKER"],
    "split-string-comment": ["env", "-S", "sh #", "-c", "x"],
    "split-string-that-does-not-split": ["env", "-S", "a 'b"],
    "flock-command": ["flock", "/tmp/opendox-lock", "-c", "x"],
    "deno-eval": ["deno", "eval", "x"],
}


@pytest.mark.parametrize("case", sorted(INLINE))
def test_A2_a_shell_or_interpreter_given_an_inline_script_is_refused(
        served, capsys, case):
    """RULED by Brett Heap, openxFactory#656 comment 5983805990, "Refuse
    inline scripts (Recommended)". The script is text, not a file a review
    can pin, and it can run whatever the repository holds, so it is refused
    BY NAME where trust is recorded (`trust`, `add`) and where it is
    checked (the verdict under any policy, and the gate beneath), with the
    remedy: the program itself, or a script kept outside the repository."""
    trust_mod = _trust_mod()
    argv = INLINE[case]
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.broker_refusal(binding, root=served.repo) == (
        trust_mod.REASON_INLINE_SCRIPT)
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    err = capsys.readouterr().err
    assert trust_mod.REASON_INLINE_SCRIPT in err
    assert trust_mod.REMEDY_INLINE_SCRIPT in err
    _no_trust_command_in(err)
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()
    for policy in (served.trust, _TrustsEveryBinding()):
        trust_mod.unregister()
        trust_mod.register(policy)
        verdict = trust_mod.verdict_for(binding, root=served.repo)
        assert not verdict.trusted
        assert verdict.reason == trust_mod.REASON_INLINE_SCRIPT
    admitted = trust_mod.TrustVerdict.trusted_for(
        binding, root=served.repo, basis=trust_mod.BASIS_HOST)
    with pytest.raises(trust_mod.BindingUntrusted) as beneath:
        trust_mod.require_admitted(binding, admitted)
    assert trust_mod.REASON_INLINE_SCRIPT in str(beneath.value)
    document = binding_mod.bindings_path(served.repo)
    document.unlink()
    adding = served.add_argv("broker")
    adding = adding[:adding.index("--") + 1] + argv
    assert _cli(*adding) == 1
    assert trust_mod.REMEDY_INLINE_SCRIPT in capsys.readouterr().err
    assert not document.exists()
    served.nothing_was_touched()


def test_A2_an_inline_script_trusted_before_the_rule_never_runs(
        served, capsys, monkeypatch):
    """The ruling's own case, `["/bin/sh", "-c", "exec ./tools/broker.py"]`,
    from a console started in the repository, with its trust recorded
    straight into the store, as a store written before the rule: the start
    refuses it, the gate refuses even a verdict that admits it, and the
    repository's script never runs."""
    trust_mod = _trust_mod()
    tool = served.repo / "tools" / "broker.py"
    tool.parent.mkdir()
    canary = served.tmp / "CANARY"
    tool.write_text(f"#!{sys.executable}\nopen({str(canary)!r}, 'w')"
                    ".close()\n", encoding="utf-8")
    os.chmod(tool, 0o755)
    monkeypatch.chdir(served.repo)
    argv = ["/bin/sh", "-c", "exec ./tools/broker.py"]
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    served.trust.record(binding, root=served.repo)
    port = served.port()
    assert isinstance(port, trust_mod.UntrustedBindingPort)
    with pytest.raises(trust_mod.BindingUntrusted) as refused:
        port.dispatch(_Envelope())
    assert trust_mod.REMEDY_INLINE_SCRIPT in str(refused.value)
    _no_trust_command_in(str(refused.value), capsys.readouterr().err)
    admitted = trust_mod.TrustVerdict.trusted_for(
        binding, root=served.repo, basis=trust_mod.BASIS_HOST)
    with pytest.raises(binding_mod.BindingRefused):
        provider_mod.mint(binding, trust=admitted)
    assert not canary.exists()
    served.nothing_was_touched()


INLINE_CONTROLS = {
    "a-shell-script-file": lambda served: ["/bin/sh", str(served.broker)],
    "the-program-itself": lambda served: ["pass", "show", "key"],
    "an-interpreter-and-a-file": lambda served: [
        sys.executable, "-B", str(served.broker)],
    "env-and-a-file": lambda served: ["env", "OPREF_PROFILE=work",
                                      sys.executable, str(served.broker)],
    "a-file-named-after-double-dash": lambda served: [
        "/bin/sh", "--", str(served.broker)],
    "awk-given-a-file": lambda served: ["awk", "-f", str(served.broker)],
    "env-split-a-program": lambda served: [
        "env", "-S", f"{sys.executable} {served.broker}"],
    "timeout-and-a-program": lambda served: [
        "timeout", "-s", "KILL", "30", sys.executable, str(served.broker)],
    "an-option-after-the-scripts-double-dash": lambda served: [
        "/bin/sh", str(served.broker), "--", "-c"],
    # Copilot at openDox-code#86, r4179241614: an interpreter's options end
    # at its script or module, so what follows is the script's own.
    "an-option-given-to-the-script": lambda served: [
        sys.executable, str(served.broker), "-c", "profile"],
    "a-value-then-the-script": lambda served: [
        sys.executable, "-W", "ignore", str(served.broker), "-c", "x"],
    "a-module-then-its-own-option": lambda served: [
        sys.executable, "-m", "json.tool", "-c", "x"],
    "a-shell-given-a-file-then-c": lambda served: [
        "/bin/sh", str(served.broker), "-c", "x"],
    "perl-include-then-the-script": lambda served: [
        "perl", "-I", "/opt/opendox-test/lib", str(served.broker), "-e",
        "x"],
    "pwsh-file-then-command": lambda served: [
        "pwsh", "-File", str(served.broker), "-Command", "x"],
    "flock-given-a-program": lambda served: [
        "flock", "/tmp/opendox-lock", sys.executable, str(served.broker),
        "-c", "x"],
    "su-given-a-shell-file": lambda served: [
        "su", "bob", "-s", str(served.broker)],
    "julia-given-a-file": lambda served: [
        "julia", "-t", "2", str(served.broker), "-e", "x"],
    "julia-attached-target-then-a-file": lambda served: [
        "julia", "-Ccore-avx2", str(served.broker)],
    "raku-given-a-file": lambda served: ["raku", "/opt/x.raku"],
    "node-flag-then-a-file": lambda served: [
        "node", "--no-warnings", str(served.broker)],
    "node-flag-a-file-and-its-own-options": lambda served: [
        "node", "--no-warnings", str(served.broker), "--flag", "x"],
    "flock-unknown-option-then-a-program": lambda served: [
        "flock", "/tmp/opendox-lock", "--verbose", sys.executable,
        str(served.broker), "-c", "x"],
    "R-given-a-file": lambda served: [
        "R", "-f", str(served.broker), "--args", "-e", "x"],
    "deno-quiet-run": lambda served: [
        "deno", "--quiet", "run", str(served.broker)],
    "a-module-attached-then-its-own-option": lambda served: [
        sys.executable, "-mjson.tool", "-c", "x"],
    "an-option-like-file-after-double-dash": lambda served: [
        "/bin/sh", "--", "-c"],
    "perl-module-attached": lambda served: [
        "perl", "-MExporter", str(served.broker)],
    "perl-in-place-extension": lambda served: [
        "perl", "-ie", str(served.broker)],
    "perl-unicode-features-attached": lambda served: [
        "perl", "-CE", str(served.broker)],
}


@pytest.mark.parametrize("case", sorted(INLINE_CONTROLS))
def test_A2_a_program_given_a_file_is_not_an_inline_script(served, case):
    """The other side of the ruling: a shell or an interpreter given a FILE
    outside the repository, the program itself, and a wrapper of one, are
    not refused."""
    trust_mod = _trust_mod()
    argv = INLINE_CONTROLS[case](served)
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.broker_refusal(binding, root=served.repo) is None
    trust_mod.recorded_for(binding, root=served.repo)
    assert trust_mod.verdict_for(binding, root=served.repo).trusted


def test_A2_an_interpreter_behind_a_name_of_its_own_is_refused(served):
    """A program is judged by the file it resolves to as well as by the name
    it is called by, so a link named like a broker that reaches an
    interpreter is an interpreter given an inline script."""
    trust_mod = _trust_mod()
    disguise = served.tmp / "bin" / "opref-broker"
    disguise.parent.mkdir()
    disguise.symlink_to(Path(sys.executable).resolve())
    served.hand_write(served.record(
        "broker", broker_argv=[str(disguise), "-c", "import runpy"]))
    verdict = trust_mod.verdict_for(served.declared(), root=served.repo)
    assert verdict.reason == trust_mod.REASON_INLINE_SCRIPT


def test_A2_every_broker_starts_outside_the_served_repository(
        served, capsys, monkeypatch):
    """RULED, openxFactory#656 comment 5983805990, item 2: defence in depth.
    A console started inside the served repository starts its broker in a
    working directory outside it (`BROKER_WORKING_DIRECTORY`), so nothing
    the broker finds relative to it is a file a pull changes."""
    where = served.tmp / "broker-cwd"
    recording = served.tmp / "recording-broker.py"
    recording.write_text(
        f"import os\nopen({str(where)!r}, 'w').write(os.getcwd())\n"
        + served.broker.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(served.repo)
    adding = served.add_argv("broker")
    adding[-1] = str(recording)
    assert _cli(*adding) == 0
    capsys.readouterr()
    port = served.port()
    assert isinstance(port, provider_mod.BrokeredProviderPort)
    with contextlib.suppress(Exception):
        port.dispatch(_Envelope())
    ran_in = Path(where.read_text(encoding="utf-8"))
    # the file system's root, which lies outside every served repository,
    # and the one directory the rules judge a command from
    assert provider_mod.BROKER_WORKING_DIRECTORY == os.path.abspath(os.sep)
    assert provider_mod.BROKER_WORKING_DIRECTORY is (
        _trust_mod().BROKER_WORKING_DIRECTORY)
    assert ran_in == Path(provider_mod.BROKER_WORKING_DIRECTORY)
    assert served.repo.resolve() not in (ran_in.resolve(),
                                         *ran_in.resolve().parents)


# ===========================================================================
# 8. LAUNCHERS (the holder's ruling, openxFactory#656 comment 5984069416,
#    implementing Brett Heap's 5983805990). Each fails at `46ac0a0f`.
# ===========================================================================

#: Each launcher, starting `PROG`: a broker program on a `PATH` entry inside
#: the served repository, which the launched command names by a bare word.
LAUNCHED = {
    "env": ["env", "PROG"],
    "env-ignore-and-assign": ["env", "-i", "OPREF_PROFILE=work",
                              "PATH=BIN", "PROG"],
    "env-split-string": ["env", "-S", "OPREF_PROFILE=work PROG --flag"],
    "nice": ["nice", "-n", "5", "PROG"],
    "nice-adjustment": ["nice", "--adjustment=5", "PROG"],
    "nohup": ["nohup", "PROG"],
    "timeout": ["timeout", "-s", "KILL", "5", "PROG"],
    "timeout-long-option": ["timeout", "--signal", "KILL", "5", "PROG"],
    "timeout-abbreviated": ["timeout", "--sig", "KILL", "5", "PROG"],
    "stdbuf-abbreviated": ["stdbuf", "--out", "L", "PROG"],
    "stdbuf": ["stdbuf", "-oL", "PROG"],
    "setsid": ["setsid", "-w", "PROG"],
    "chrt": ["chrt", "-o", "0", "PROG"],
    "ionice": ["ionice", "-c", "3", "PROG"],
    "taskset": ["taskset", "0x1", "PROG"],
    "time": ["time", "-f", "%e", "PROG"],
    "xargs": ["xargs", "-0", "PROG"],
    "busybox": ["busybox", "env", "PROG"],
    "flock": ["flock", "-w", "5", "/tmp/opendox-lock", "PROG"],
    "sudo": ["sudo", "-u", "bob", "PROG"],
    "doas": ["doas", "-u", "bob", "PROG"],
    "nested": ["env", "nice", "-n", "1", "timeout", "5", "PROG"],
}


@pytest.mark.parametrize("case", sorted(LAUNCHED))
def test_A2_a_launcher_is_unwrapped_to_the_program_it_starts(
        served, capsys, monkeypatch, case):
    """Item 1 and 3 of the ruling: a launcher is unwrapped, with its own
    options and operands, to the program it starts, and that program is
    judged as a command's program is, so it is found as `PATH` finds it,
    here inside the repository."""
    trust_mod = _trust_mod()
    program = served.repo / "bin" / "opref-in-repository"
    program.parent.mkdir()
    program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    os.chmod(program, 0o755)
    monkeypatch.setenv("PATH", f"{program.parent}{os.pathsep}"
                       f"{os.environ.get('PATH', '')}")
    argv = [member.replace("BIN", str(program.parent)).replace(
        "PROG", program.name) for member in LAUNCHED[case]]
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.broker_refusal(binding, root=served.repo) == (
        trust_mod.REASON_IN_REPOSITORY), argv
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    assert trust_mod.REMEDY_IN_REPOSITORY in capsys.readouterr().err
    served.nothing_was_touched()


def _launcher_values(served):
    tool = served.repo / "tools" / "broker.py"
    tool.parent.mkdir(exist_ok=True)
    shutil.copy(served.broker, tool)
    launcher = served.repo / "tools" / "env"
    launcher.write_text("#!/bin/sh\nexec \"$@\"\n", encoding="utf-8")
    os.chmod(launcher, 0o755)
    return {
        "env-assigns-a-module-path": [
            "env", f"PYTHONPATH={tool.parent}", sys.executable, "-m",
            "broker"],
        "env-assigns-a-relative-module-path": [
            "env", "PYTHONPATH=" + os.path.relpath(
                tool.parent, provider_mod.BROKER_WORKING_DIRECTORY),
            sys.executable, "-m", "broker"],
        "env-assigns-a-search-path": [
            "env", f"PATH=/usr/bin{os.pathsep}{tool.parent}", "opref-broker"],
        "env-assigns-a-relative-search-path-entry": [
            "env", "-C", str(served.repo.parent),
            f"PATH=/usr/bin{os.pathsep}{served.repo.name}/tools",
            "opref-broker"],
        "env-changes-directory": [
            "env", "-C", str(served.repo), sys.executable, str(served.broker)],
        "env-changes-directory-long": [
            "env", f"--chdir={served.repo}", sys.executable,
            str(served.broker)],
        "a-launcher-inside-the-repository": [
            str(launcher), sys.executable, str(served.broker)],
    }


@pytest.mark.parametrize("case", ["env-assigns-a-module-path",
                                  "env-assigns-a-relative-module-path",
                                  "env-assigns-a-search-path",
                                  "env-assigns-a-relative-search-path-entry",
                                  "env-changes-directory",
                                  "env-changes-directory-long",
                                  "a-launcher-inside-the-repository"])
def test_A2_what_a_launcher_is_given_is_judged_too(served, case):
    """A launcher's own program, and each of its values that could name a
    file (`env NAME=VALUE`, every directory of a search path, `env -C DIR`),
    are judged, so none of them may lie inside the repository."""
    trust_mod = _trust_mod()
    argv = _launcher_values(served)[case]
    served.hand_write(served.record("broker", broker_argv=argv))
    assert trust_mod.broker_refusal(served.declared(), root=served.repo) == (
        trust_mod.REASON_IN_REPOSITORY), argv


def test_A2_a_cleared_search_path_is_the_default_one(served, monkeypatch):
    """`env -i`, `env -`, `env --ignore-environment` and `env -u PATH` leave
    the program they start to be found on the platform's default search
    path, as the launched child finds it (Copilot at openDox-code#86,
    r4179366288), not on the console's: a program only the console's `PATH`
    reaches is not the one that runs. Where `PATH` is assigned again, that
    is the path."""
    trust_mod = _trust_mod()
    program = served.repo / "bin" / "opref-console-only"
    program.parent.mkdir()
    program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    os.chmod(program, 0o755)
    monkeypatch.setenv("PATH", f"{program.parent}{os.pathsep}"
                       f"{os.environ.get('PATH', '')}")
    for launcher in (["env", "-i"], ["env", "-"],
                     ["env", "--ignore-environment"], ["env", "-u", "PATH"],
                     ["env", "--unset=PATH"], ["env", "-iv"]):
        argv = [*launcher, program.name]
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) is None, argv
    links = served.tmp / "links"
    links.mkdir()
    (links / program.name).symlink_to(program)
    argv = ["env", "-i", f"PATH={links}", program.name]
    assert trust_mod.broker_command_refused(argv, root=served.repo) == (
        trust_mod.REASON_IN_REPOSITORY)
    # and a console whose `PATH` reaches it, with no launcher, still is
    assert trust_mod.broker_command_refused(
        [program.name], root=served.repo) == trust_mod.REASON_IN_REPOSITORY


def _unreadable_command(served, monkeypatch, case):
    program = served.repo / "bin" / "opref-broker"
    program.parent.mkdir()
    program.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    os.chmod(program, 0o755)
    monkeypatch.setenv("PATH", f"{program.parent}{os.pathsep}"
                       f"{os.environ.get('PATH', '')}")
    if case == "launchers-nested-past-the-depth":
        return ["env"] * 33 + [program.name]
    return UNREADABLE_COMMANDS[case]


#: The holder's ruling, openxFactory#656 comment 5985046107, C1: what a
#: launcher's getopt would read otherwise than its words say is refused
#: FAIL-CLOSED: an ambiguous or an unknown option, a flag given a value, a
#: value that is missing, and an option after which what runs cannot be
#: judged.
UNREADABLE_COMMANDS = {
    "ambiguous-d": ["env", "--d", "sh"],
    "ambiguous-i": ["env", "--i", "sh"],
    "unknown-long-option": ["env", "--frobnicate", "sh"],
    "unknown-short-option": ["nice", "-z", "/bin/true"],
    "a-flag-given-a-value": ["env", "--debug=1", "/bin/true"],
    "a-value-missing": ["env", "-C"],
    "a-long-value-missing": ["env", "--chdir"],
    "env-argv0": ["env", "--argv0=sh", "/opt/opendox-test/multi-call",
                  "-c", "x"],
    "sudo-chroot": ["sudo", "--chroot=/srv", "/bin/true"],
    "sudo-login": ["sudo", "-i", "/bin/true"],
    # N2: a leading option deno's global grammar does not hold
    "deno-unknown-leading-option": ["deno", "--frobnicate", "eval", "x"],
    # r4180717752; the holder's ruling, #656 5988088910: a second working
    # directory for one launcher, counting one an `env -S` string gives
    "env-chdir-twice": ["env", "-C", "/tmp", "-C", "usr", "/bin/true"],
    "env-chdir-twice-long": ["env", "--chdir=/tmp", "--chd", "usr",
                             "/bin/true"],
    "env-chdir-again-in-a-split-string": ["env", "-C", "/tmp", "-S",
                                          "-C usr /bin/true"],
    "sudo-chdir-twice": ["sudo", "-D", "/tmp", "--chdir=/usr", "/bin/true"],
    # r4181006365; the holder's ruling, #656 5988818366: what xargs runs is
    # built from its input, so every xargs is unreadable, after the
    # in-repository and inline-script judgments
    "xargs-building-its-command": ["xargs", "-a", "/opt/opendox-test/args",
                                   "-I", "SCRIPT", "python3", "SCRIPT"],
    "xargs-and-a-program-outside": ["xargs", "/opt/opendox-test/broker"],
    "xargs-abbreviated-option": ["xargs", "--max-a", "1",
                                 "/opt/opendox-test/broker"],
    # the writer's sibling, 5988818366: any assignment given to sudo
    "sudo-assignment": ["sudo", "A=b", "/bin/true"],
    "sudo-path-assignment": ["sudo", "PATH=/opt/opendox-test/bin", "true"],
    "sudo-option-then-assignment": ["sudo", "-u", "bob", "A=b",
                                    "/bin/true"],
    # the summary of review 5411026353; the holder's ruling, #656
    # 5989835334: a member past the bounds of what is judged
    "member-past-the-length-bound": ["/opt/opendox-test/broker",
                                     "a" * 4097],
    "member-past-the-path-bound": ["/opt/opendox-test/broker", "/a" * 33],
}


@pytest.mark.parametrize("case", ["launchers-nested-past-the-depth",
                                  *sorted(UNREADABLE_COMMANDS)])
def test_A2_a_command_that_cannot_be_read_is_refused_by_name(
        served, capsys, monkeypatch, case):
    """A broker command that cannot be read to the program it runs (Copilot
    at openDox-code#86, r4179366319): launchers nested past what is
    unwrapped, where the program the last one starts was never judged, or
    a launcher option its getopt would read otherwise (C1). What it runs
    cannot be judged, so it is refused BY NAME where trust is recorded and
    where it is checked, with the inline-script remedy."""
    trust_mod = _trust_mod()
    argv = _unreadable_command(served, monkeypatch, case)
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    refused = trust_mod.broker_refusal(binding, root=served.repo)
    assert refused is not None and refused != (
        trust_mod.REASON_INLINE_SCRIPT), refused
    assert refused == trust_mod.REASON_UNREADABLE_COMMAND
    assert not trust_mod.trust_can_repair(refused)
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 1
    err = capsys.readouterr().err
    assert trust_mod.REASON_UNREADABLE_COMMAND in err
    assert trust_mod.REMEDY_INLINE_SCRIPT in err
    _no_trust_command_in(err)
    for policy in (served.trust, _TrustsEveryBinding()):
        trust_mod.unregister()
        trust_mod.register(policy)
        verdict = trust_mod.verdict_for(binding, root=served.repo)
        assert verdict.reason == trust_mod.REASON_UNREADABLE_COMMAND
    admitted = trust_mod.TrustVerdict.trusted_for(
        binding, root=served.repo, basis=trust_mod.BASIS_HOST)
    with pytest.raises(trust_mod.BindingUntrusted) as beneath:
        trust_mod.require_admitted(binding, admitted)
    assert trust_mod.REASON_UNREADABLE_COMMAND in str(beneath.value)
    served.nothing_was_touched()


@pytest.mark.parametrize("case", ["past-the-bound", "a-loop"])
def test_R3_links_past_the_bound_are_unreadable(served, case):
    """The holder's ruling, openxFactory#656 comment 5986391296: a path
    whose symbolic links pass the kernel's own bound (40), or loop, is
    refused BY NAME as unreadable, wherever it is judged; a chain within
    the bound is followed to its end."""
    trust_mod = _trust_mod()
    links = served.tmp / "links"
    links.mkdir()
    real = links / "real.py"
    real.write_text("", encoding="utf-8")
    if case == "past-the-bound":
        target = real
        for hop in range(41):
            link = links / f"hop-{hop}"
            link.symlink_to(target)
            target = link
        named = target
    else:
        (links / "a").symlink_to(links / "b")
        (links / "b").symlink_to(links / "a")
        named = links / "a"
    argv = [sys.executable, str(named)]
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.broker_refusal(binding, root=served.repo) == (
        trust_mod.REASON_UNREADABLE_COMMAND)
    assert trust_mod.in_repository_argv(argv, root=served.repo) == str(
        named)
    assert trust_mod.names_a_path_inside(str(named), root=served.repo)
    trust_mod.unregister()
    trust_mod.register(_TrustsEveryBinding())
    assert trust_mod.verdict_for(binding, root=served.repo).reason == (
        trust_mod.REASON_UNREADABLE_COMMAND)


def test_R3_a_path_that_leaves_the_root_by_dot_dot_is_outside(served):
    """The walk ends where the path does: `<root>/..` passes through the
    served root and names its parent, which lies outside it."""
    trust_mod = _trust_mod()
    leaving = os.path.join(str(served.repo), os.pardir)
    for argv in (["env", "-C", leaving, sys.executable, str(served.broker)],
                 [sys.executable, str(served.broker), f"--cache={leaving}"]):
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) is None, argv


def test_R3_a_chain_within_the_bound_is_followed_to_its_end(served):
    trust_mod = _trust_mod()
    links = served.tmp / "links"
    links.mkdir()
    target = served.broker
    for hop in range(40):
        link = links / f"hop-{hop}"
        link.symlink_to(target)
        target = link
    assert trust_mod.broker_command_refused(
        [sys.executable, str(target)], root=served.repo) is None


def test_A2_launchers_within_the_depth_are_unwrapped_whole(served):
    """The control: launchers nested within the depth are unwrapped to the
    program they start, which is judged, and admitted where it is a file
    outside the repository."""
    trust_mod = _trust_mod()
    argv = ["env"] * 31 + [sys.executable, str(served.broker)]
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.broker_refusal(binding, root=served.repo) is None
    trust_mod.recorded_for(binding, root=served.repo)
    assert trust_mod.verdict_for(binding, root=served.repo).trusted


def test_C1_a_split_string_env_would_expand_is_refused():
    """`${VAR}`, which env -S expands and a shell's split does not: refused
    as an inline script. A binding cannot declare it at all (a placeholder
    outside its vocabulary), so the console intake's broker is where it is
    asked."""
    trust_mod = _trust_mod()
    assert trust_mod.broker_command_refused(
        ["env", "-S", "sh -c ${OPREF_SCRIPT}"], root=None) == (
            trust_mod.REASON_INLINE_SCRIPT)


def test_C1_a_launchers_own_options_are_read_as_its_getopt_reads_them(
        served):
    """The controls: an unambiguous beginning of a long option, a cluster,
    nice's own `-5`, `--help`, and an option taking its value after `=`,
    each unwrapped to the program it starts, here a file outside the
    repository, so nothing is refused."""
    trust_mod = _trust_mod()
    program = [sys.executable, str(served.broker)]
    for argv in (["env", "--ignore-env", *program],
                 ["env", "-iv", *program],
                 ["env", f"--chd={served.tmp}", *program],
                 ["env", "-0u", "OPREF_PROFILE", *program],
                 ["nice", "-5", *program],
                 ["nice", "--adj=5", *program],
                 ["timeout", "--sig=KILL", "5", *program],
                 ["stdbuf", "--out", "L", *program],
                 ["env", "A-B=x", *program],
                 ["env", "1A=x", "A.B=y", *program],
                 ["sudo", "--user=bob", *program],
                 ["env", "--default-signal", *program],
                 ["env", "--help"]):
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) is None, argv


# --- C4: every file a launcher or an option could name ---------------------


def _launcher_files(served):
    arguments = served.repo / "ideation" / "arguments"
    arguments.parent.mkdir(parents=True, exist_ok=True)
    arguments.write_text("x\n", encoding="utf-8")
    library = served.repo / "lib"
    library.mkdir()
    script = "/opt/opendox-test/broker.pl"
    return {
        "xargs-arg-file": ["xargs", "-a", str(arguments), "printf"],
        "xargs-arg-file-attached": ["xargs", f"-a{arguments}", "printf"],
        "xargs-arg-file-long": ["xargs", f"--arg-file={arguments}",
                                "printf"],
        "xargs-arg-file-abbreviated": ["xargs", "--arg", str(arguments),
                                       "printf"],
        "xargs-arg-file-in-a-cluster": ["xargs", f"-0a{arguments}",
                                        "printf"],
        "an-option-with-an-attached-path": ["perl", f"-I{library}", script],
        "an-attached-path-in-a-cluster": ["perl", f"-wI{library}", script],
        "a-relative-path-attached-to-an-option": [
            "env", "-C", str(served.repo.parent), "perl",
            f"-I{served.repo.name}/lib", script],
        "an-option-in-an-assignment": ["env", f"PERL5OPT=-I{library}",
                                       "perl", script],
        "a-path-inside-an-assignment": [
            "env", f"PERL5OPT=-Mstrict -I{library}", "perl", script],
        "an-output-file": ["time", "-o", str(served.repo / "timing"),
                           "/bin/true"],
        "a-launchers-operand": ["flock", str(served.repo / ".lock"),
                                "/bin/true"],
    }


@pytest.mark.parametrize("case", ["xargs-arg-file", "xargs-arg-file-attached",
                                  "xargs-arg-file-long",
                                  "xargs-arg-file-abbreviated",
                                  "xargs-arg-file-in-a-cluster",
                                  "an-option-with-an-attached-path",
                                  "an-attached-path-in-a-cluster",
                                  "a-relative-path-attached-to-an-option",
                                  "an-option-in-an-assignment",
                                  "a-path-inside-an-assignment",
                                  "an-output-file", "a-launchers-operand"])
def test_C4_every_file_a_launcher_or_an_option_names_is_judged(served, case):
    """The holder's ruling, openxFactory#656 comment 5985046107, C4: xargs's
    argument file in every spelling, a path attached to a single-dash
    option, a path inside an assignment's value, and a launcher's operands,
    each judged where the broker reads it. Inside the repository is refused,
    fail-closed, and so is a file a launcher writes there (`time -o`), an
    accepted strictness."""
    trust_mod = _trust_mod()
    argv = _launcher_files(served)[case]
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert trust_mod.broker_refusal(binding, root=served.repo) == (
        trust_mod.REASON_IN_REPOSITORY), argv
    trust_mod.unregister()
    trust_mod.register(_TrustsEveryBinding())
    assert trust_mod.verdict_for(binding, root=served.repo).reason == (
        trust_mod.REASON_IN_REPOSITORY)


# --- C5: a wrong kind in the store's place names what it is ----------------


@pytest.mark.parametrize("kind", ["directory", "fifo", "socket"])
def test_C5_a_wrong_kind_in_the_stores_place_names_what_it_is(
        served, monkeypatch, kind):
    """The holder's ruling, openxFactory#656 comment 5985046107, C5: a
    directory, a FIFO or a socket where the store belongs is no link, owner
    or mode, so it is not blamed on another user (A7): it is refused for
    what it is, with the move-aside recovery, by the verdict and by
    `record`."""
    import socket

    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    served.state_dir.mkdir(mode=0o700)
    store = served.state_dir / trust_mod.TRUST_FILENAME
    listening = None
    if kind == "directory":
        store.mkdir(mode=0o700)
    elif kind == "fifo":
        os.mkfifo(store, 0o600)
    else:
        monkeypatch.chdir(served.state_dir)  # a socket's path is short
        listening = socket.socket(socket.AF_UNIX)
        listening.bind(store.name)
    try:
        verdict = served.trust.verdict(served.declared(), root=served.repo)
        with pytest.raises(trust_mod.TrustStoreRefused) as refused:
            served.trust.record(served.declared(), root=served.repo)
    finally:
        if listening is not None:
            listening.close()
    assert not verdict.trusted
    for words in (verdict.reason, str(refused.value)):
        assert "is not a regular file" in words, words
        assert "another user could change" not in words, words
        assert trust_mod.RECOVER_MOVE_ASIDE in words, words


# --- C2: a failed write takes back the trust it recorded -------------------


def _held_entries(served) -> list:
    """The trust store's entries for the binding, as the store holds them."""
    store = served.state_dir / _trust_mod().TRUST_FILENAME
    if not store.exists():
        return []
    return [entry for entry in json.loads(store.read_text(
        encoding="utf-8"))["entries"] if entry["binding_id"] == BINDING_ID]


def _failing(monkeypatch, verb, error=None):
    def fails(store, binding):
        raise error or OSError(28, "No space left on device")

    monkeypatch.setattr(binding_mod.BindingStore, verb, fails)


@pytest.mark.parametrize("failure", ["the-system", "the-store"])
def test_C2_an_add_whose_write_fails_withdraws_the_trust_it_recorded(
        served, capsys, monkeypatch, failure):
    """The holder's ruling, openxFactory#656 comment 5985046107, C2: the
    trust `add` records first is withdrawn when the document's write fails,
    by the system (a full disk) or by the store's own refusal, so this
    machine trusts no form no document declares, and "nothing in it
    changed" is true of both."""
    if failure == "the-system":
        _failing(monkeypatch, "add")
        said = "nothing in it changed"
    else:
        said = "the store refused the write"
        _failing(monkeypatch, "add", binding_mod.BindingRefused(said))
    assert _cli(*served.add_argv("env")) == 1
    err = capsys.readouterr().err
    assert said in err
    assert "could not be withdrawn" not in err
    assert not binding_mod.bindings_path(served.repo).exists()
    assert not _held_entries(served), "a trust stayed for no declared form"


def test_C2_an_edit_of_an_untrusted_binding_whose_write_fails_trusts_nothing(
        served, capsys, monkeypatch):
    """The review's case: an edit of a binding never trusted records trust
    for its new form, the write fails, and that trust is withdrawn, so the
    earlier form still reads "never trusted", not "changed"."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    before = served.declared()
    assert not served.trust.verdict(before, root=served.repo).trusted
    _failing(monkeypatch, "edit")
    editing = served.add_argv("env")
    editing[1] = "edit"
    editing[editing.index("--label") + 1] = "Renamed"
    assert _cli(*editing) == 1
    err = capsys.readouterr().err
    assert "could not be written" in err and "nothing in it changed" in err
    assert served.declared() == before
    assert served.trust.verdict(before, root=served.repo).reason == (
        trust_mod.REASON_NEVER_TRUSTED)
    assert not _held_entries(served), "a trust stayed for no declared form"


@pytest.mark.parametrize("trusted", [False, True],
                         ids=["untrusted", "trusted"])
def test_C2_an_undoing_that_fails_says_so_and_how_to_recover(
        served, capsys, monkeypatch, trusted):
    """Where the trust cannot be taken back (the store refuses), the refusal
    says so, after the write's own cause, and how to recover: run the same
    command again once the document can be written."""
    from opendox import cli_model_binding

    trust_mod = _trust_mod()
    if trusted:
        assert _cli(*served.add_argv("env")) == 0
        capsys.readouterr()
    else:
        served.hand_write(served.record("env"))

    def refuses(self, binding, *, root, replacing):
        raise trust_mod.TrustStoreRefused("the store refused the undoing")

    monkeypatch.setattr(trust_mod.MachineTrust, "restore", refuses)
    _failing(monkeypatch, "edit")
    editing = served.add_argv("env")
    editing[1] = "edit"
    editing[editing.index("--label") + 1] = "Renamed"
    assert _cli(*editing) == 1
    err = capsys.readouterr().err
    assert "could not be written" in err
    said = ("the trust its earlier form held could not be restored"
            if trusted else
            "the trust just recorded for it could not be withdrawn")
    assert said in err and "the store refused the undoing" in err, err
    assert cli_model_binding.RECOVER_FAILED_UNDOING in err


def test_R3_an_add_racing_one_of_the_same_form_keeps_its_trust(
        served, capsys, monkeypatch):
    """Copilot at openDox-code#86, r4180041219; the holder's ruling,
    openxFactory#656 comment 5986391296, (a): two `add`s of the same form
    both record its trust, the other writes the document first, and this
    one's write is refused for the repeated id. Its undoing is skipped,
    because the document now declares exactly the form recorded, so the
    declared binding stays trusted."""
    from opendox import cli_model_binding

    trust_mod = _trust_mod()
    real = cli_model_binding._record_trust
    document = binding_mod.bindings_path(served.repo)

    def and_the_other_add_lands(binding, args):
        recording = real(binding, args)
        binding_mod.BindingStore(document).add(binding)
        return recording

    monkeypatch.setattr(cli_model_binding, "_record_trust",
                        and_the_other_add_lands)
    assert _cli(*served.add_argv("env")) == 1
    capsys.readouterr()
    assert trust_mod.verdict_for(served.declared(), root=served.repo).trusted


def test_R3_an_edit_racing_one_of_the_same_form_keeps_its_trust(
        served, capsys, monkeypatch):
    """The same for `edit`: the other edit writes the same form, and this
    one's write fails; the document declares exactly the form recorded, so
    its trust stands."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("env"))
    document = binding_mod.bindings_path(served.repo)
    real = binding_mod.BindingStore.edit

    def the_other_lands_then_this_fails(store, binding):
        real(binding_mod.BindingStore(document), binding)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(binding_mod.BindingStore, "edit",
                        the_other_lands_then_this_fails)
    editing = served.add_argv("env")
    editing[1] = "edit"
    editing[editing.index("--label") + 1] = "Renamed"
    assert _cli(*editing) == 1
    capsys.readouterr()
    assert served.declared().label == "Renamed"
    assert trust_mod.verdict_for(served.declared(), root=served.repo).trusted


class _RecordsNothing(_TrustsEveryBinding):
    """A host policy whose `record()` writes nothing and answers nothing,
    as openxFactory's governed policy does (T094): its `verdict` decides."""

    def record(self, binding, *, root):
        return None


class _RecordsNothingAndDeclines(_RecordsNothing):
    def verdict(self, binding, *, root):
        return _trust_mod().TrustVerdict.untrusted_for(
            binding, root=root, basis=_trust_mod().BASIS_HOST,
            reason="its declaration is pending")


@pytest.mark.parametrize("verb", ["add", "edit"])
def test_R3_a_host_that_recorded_nothing_has_nothing_withdrawn(
        served, capsys, monkeypatch, verb):
    """The holder's ruling, openxFactory#656 comment 5986391296: openDox
    withdraws only what a policy recorded. A host policy whose `record()`
    answers something falsy recorded nothing; its `verdict` admits the
    binding, so the act writes, and where the write fails the refusal says
    truthfully that nothing changed, and nothing is withdrawn."""
    from opendox import cli_model_binding

    trust_mod = _trust_mod()
    if verb == "edit":
        served.hand_write(served.record("env"))
    trust_mod.unregister()
    trust_mod.register(_RecordsNothing())
    _failing(monkeypatch, verb)
    argv = served.add_argv("env")
    if verb == "edit":
        argv[1] = "edit"
        argv[argv.index("--label") + 1] = "Renamed"
    assert _cli(*argv) == 1
    err = capsys.readouterr().err
    assert "could not be written" in err and "nothing in it changed" in err
    assert "could not be withdrawn" not in err
    assert "could not be restored" not in err
    assert trust_mod.REASON_NO_WITHDRAWAL not in err
    assert cli_model_binding.RECOVER_FAILED_UNDOING not in err
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()


def test_R3_a_host_that_records_nothing_is_asked_its_verdict(served, capsys):
    """Recording under such a host asks its `verdict`: one that admits the
    binding lets `add` write it, with nothing written to this machine's
    store, and one that declines refuses `add` by name before it writes."""
    trust_mod = _trust_mod()
    trust_mod.unregister()
    trust_mod.register(_RecordsNothing())
    recording = trust_mod.recording_for(
        binding_mod.ModelProviderBinding.from_record(served.record("env")),
        root=served.repo)
    assert recording.verdict.trusted and recording.recorded is False
    assert _cli(*served.add_argv("env")) == 0
    capsys.readouterr()
    assert served.declared().id == BINDING_ID
    assert not (served.state_dir / trust_mod.TRUST_FILENAME).exists()
    binding_mod.bindings_path(served.repo).unlink()
    trust_mod.unregister()
    trust_mod.register(_RecordsNothingAndDeclines())
    assert _cli(*served.add_argv("env")) == 1
    assert "its declaration is pending" in capsys.readouterr().err
    assert not binding_mod.bindings_path(served.repo).exists()
    trust_mod.unregister()
    trust_mod.register(_TrustsEveryBinding())
    recording = trust_mod.recording_for(
        binding_mod.ModelProviderBinding.from_record(served.record("env")),
        root=served.repo)
    assert recording.verdict.trusted and recording.recorded is True


def test_C2_a_host_policy_cannot_be_asked_to_withdraw_and_says_so(
        served, capsys, monkeypatch):
    """A host's policy records and judges trust and withdraws none, so a
    failed add under one whose `record()` answered a record (truthy) says
    the trust could not be withdrawn, and why (the holder's ruling,
    openxFactory#656 comment 5986391296)."""
    from opendox import cli_model_binding

    trust_mod = _trust_mod()
    trust_mod.unregister()
    trust_mod.register(_TrustsEveryBinding())
    _failing(monkeypatch, "add")
    assert _cli(*served.add_argv("env")) == 1
    err = capsys.readouterr().err
    assert "the trust just recorded for it could not be withdrawn" in err
    assert trust_mod.REASON_NO_WITHDRAWAL in err
    assert cli_model_binding.RECOVER_FAILED_UNDOING in err


@pytest.mark.parametrize("argv", [["awk", "NR == 1"],
                                  ["sed", "-n", "1p"],
                                  ["find", "/nonexistent", "-exec", "true",
                                   ";"]],
                         ids=["awk", "sed", "find-exec"])
def test_A2_a_general_program_running_its_arguments_is_the_accepted_limit(
        served, argv):
    """Item 4 of the ruling: a general program that runs code from its own
    arguments (`awk`, `sed`, `find -exec`) is the recorded ACCEPTED limit.
    It is not judged as an inline script, so its binding is trusted as any
    program outside the repository is. This case records the limit; it
    asks for nothing more."""
    trust_mod = _trust_mod()
    served.hand_write(served.record("broker", broker_argv=argv))
    assert trust_mod.broker_refusal(served.declared(),
                                    root=served.repo) is None


def test_A2_a_broker_never_inherits_a_working_directory_variable(
        served, capsys, monkeypatch):
    """Item 2 of the ruling: `PWD` and `OLDPWD` never reach a broker, even
    where the harness's allowlist, which a broker's environment starts from,
    came to hold them, so nothing that trusts `$PWD` over its real working
    directory reads the directory the console was started in."""
    from opendox import doxbench_bridge

    monkeypatch.setattr(doxbench_bridge, "INHERITED_ENVIRONMENT",
                        (*doxbench_bridge.INHERITED_ENVIRONMENT, "PWD",
                         "OLDPWD"))
    # the serving process's environment, as the provider reads it
    served.environ["PWD"] = str(served.repo)
    served.environ["OLDPWD"] = str(served.repo)
    seen = served.tmp / "broker-environment.json"
    recording = served.tmp / "recording-broker.py"
    recording.write_text(
        "import json, os\n"
        f"open({str(seen)!r}, 'w').write(json.dumps(sorted(os.environ)))\n"
        + served.broker.read_text(encoding="utf-8"), encoding="utf-8")
    adding = served.add_argv("broker")
    adding[-1] = str(recording)
    assert _cli(*adding) == 0
    capsys.readouterr()
    port = served.port()
    with contextlib.suppress(Exception):
        port.dispatch(_Envelope())
    names = json.loads(seen.read_text(encoding="utf-8"))
    assert "PWD" not in names and "OLDPWD" not in names, names
    assert "PATH" in names
    assert provider_mod.broker_environment(
        {"PATH": "/usr/bin", "PWD": "/x", "OLDPWD": "/y"}) == {
            "PATH": "/usr/bin"}



# ===========================================================================
# 9. F16.1 AS T007 BATCH P AMENDS IT (openxFactory#1230; the holder's
#    rulings on openxFactory#656, comments 5982436447 item 2, 5983805990,
#    5984069416, 5985046107 and 5985553609). One case per command: each is
#    refused BY NAME by `add`, `edit`, `trust` and `set-credential`, and
#    before any spawn, with no marker file written.
# ===========================================================================

_MARKING_PYTHON = "import sys\nopen({marker!r}, 'a').write('ran\\n')\n"


def _batch_p_world(served, monkeypatch) -> dict:
    """The served repository's own programs and links, and the case's own
    scratch directory outside it (`outside`), each of which writes the
    marker file when it runs."""
    root = served.repo
    marking = _MARKING_PYTHON.format(marker=str(served.marker))
    tools = root / "tools"
    tools.mkdir()
    for name in ("broker.py", "sitecustomize.py"):
        (tools / name).write_text(f"#!{sys.executable}\n" + marking,
                                  encoding="utf-8")
    (tools / "broker.sh").write_text(
        f"#!/bin/sh\necho ran >> {shlex_quote(str(served.marker))}\n",
        encoding="utf-8")
    for name in ("broker.py", "broker.sh"):
        os.chmod(tools / name, 0o755)
    outside = served.tmp / "outside"
    outside.mkdir()
    broker = outside / "broker"
    broker.write_text(f"#!{sys.executable}\n" + marking, encoding="utf-8")
    os.chmod(broker, 0o755)
    (outside / "broker.py").write_text(marking, encoding="utf-8")
    (outside / "broker.pl").write_text(
        f"open(my $m, '>>', {json.dumps(str(served.marker))}); "
        "print $m \"ran\\n\";\n", encoding="utf-8")
    (outside / "alias").symlink_to(tools, target_is_directory=True)
    (outside / "link").symlink_to(tools / "broker.py")
    (outside / "link.py").symlink_to(tools / "broker.py")
    real_out = served.tmp / "real-out"
    real_out.mkdir()
    (tools / "out").symlink_to(real_out, target_is_directory=True)
    (tools / "out-broker").symlink_to(broker)
    (tools / "out-broker.py").symlink_to(outside / "broker.py")
    bin_ = root / "bin"
    bin_.mkdir()
    (bin_ / "opref-broker").write_text(f"#!{sys.executable}\n" + marking,
                                       encoding="utf-8")
    os.chmod(bin_ / "opref-broker", 0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}"
                       f"{os.environ.get('PATH', '')}")
    monkeypatch.chdir(root)     # opendox started at the served root
    return {"root": str(root), "outside": str(outside)}


def shlex_quote(text: str) -> str:
    import shlex

    return shlex.quote(text)


P_IN_REPO, P_INLINE, P_UNREADABLE = "in-repo", "inline", "unreadable"

#: Each case of the amended F16.1, as `(argv, reason)`; `{root}` is the
#: served root and `{outside}` the case's scratch directory outside it.
BATCH_P = {
    # an in-repository program or script, absolute and relative to the root
    "program-absolute": (["{root}/tools/broker.py"], P_IN_REPO),
    "program-relative": (["tools/broker.py"], P_IN_REPO),
    "python-script-absolute": (["python3", "{root}/tools/broker.py"],
                               P_IN_REPO),
    "python-script-relative": (["python3", "tools/broker.py"], P_IN_REPO),
    "sh-script-absolute": (["sh", "{root}/tools/broker.sh"], P_IN_REPO),
    "sh-script-relative": (["sh", "tools/broker.sh"], P_IN_REPO),
    # an inline script, and one reached through each launcher
    "sh-c": (["sh", "-c", "exec ./tools/broker.py"], P_INLINE),
    "python-c": (["python3", "-c", "import runpy"], P_INLINE),
    "env-i": (["env", "-i", "python3", "-c", "import runpy"], P_INLINE),
    "nice": (["nice", "-n", "5", "python3", "-c", "import runpy"],
             P_INLINE),
    "nohup": (["nohup", "python3", "-c", "import runpy"], P_INLINE),
    "timeout": (["timeout", "-s", "KILL", "5", "python3", "-c",
                 "import runpy"], P_INLINE),
    "stdbuf": (["stdbuf", "-oL", "python3", "-c", "import runpy"],
               P_INLINE),
    "setsid": (["setsid", "-w", "python3", "-c", "import runpy"],
               P_INLINE),
    "xargs": (["xargs", "-n", "1", "python3", "-c", "import runpy"],
              P_INLINE),
    "nested": (["env", "nice", "-n", "5", "timeout", "5", "python3", "-c",
                "import runpy"], P_INLINE),
    "env-split-string": (["env", "-S", "python3 -c 'import runpy'"],
                         P_INLINE),
    # an alias, judged as named and as it resolves
    "link-outside-to-inside": (["{outside}/link"], P_IN_REPO),
    "link-outside-to-inside-as-script": (["python3", "{outside}/link.py"],
                                         P_IN_REPO),
    "bare-name-on-a-path-entry-under-the-root": (["opref-broker"], P_IN_REPO),
    "link-inside-to-outside": (["{root}/tools/out-broker"], P_IN_REPO),
    "link-inside-to-outside-as-script": (
        ["python3", "{root}/tools/out-broker.py"], P_IN_REPO),
    # a launcher's own assignment, and its working-directory option
    "env-module-path-relative": (
        ["env", "PYTHONPATH=tools", "python3", "{outside}/broker.py"],
        P_IN_REPO),
    "env-module-path-through-an-outside-alias": (
        ["env", "PYTHONPATH={outside}/alias", "python3",
         "{outside}/broker.py"], P_IN_REPO),
    "env-scalar-through-an-outside-alias": (
        ["env", "OPENDOX_TEST_HOME={outside}/alias", "python3",
         "{outside}/broker.py"], P_IN_REPO),
    "env-module-path-through-an-inside-link": (
        ["env", "PYTHONPATH=tools/out", "python3", "{outside}/broker.py"],
        P_IN_REPO),
    "env-scalar-through-an-inside-link": (
        ["env", "OPENDOX_TEST_HOME=tools/out", "python3",
         "{outside}/broker.py"], P_IN_REPO),
    "env-chdir-root": (["env", "--chdir={root}", "python3",
                        "{outside}/broker.py"], P_IN_REPO),
    "env-C-root": (["env", "-C", "{root}", "python3", "{outside}/broker.py"],
                   P_IN_REPO),
    "env-chdir-outside-alias": (["env", "--chdir={outside}/alias", "python3",
                                 "{outside}/broker.py"], P_IN_REPO),
    "env-chdir-inside-link": (["env", "--chdir=tools/out", "python3",
                               "{outside}/broker.py"], P_IN_REPO),
    # 5985046107, C1 and C4: a path an option carries, an unreadable split
    # string, and a launcher option that cannot be read
    "perl-attached-library": (["perl", "-I{root}/lib", "{outside}/broker.pl"],
                              P_IN_REPO),
    "xargs-argument-file": (["xargs", "-a", "{root}/args",
                             "{outside}/broker"], P_IN_REPO),
    "env-chdir-abbreviated": (["env", "--chd={root}", "{outside}/broker"],
                              P_IN_REPO),
    "env-split-string-escape": (["env", "-S", "sh\\_-c\\_id"], P_INLINE),
    "option-value": (["{outside}/broker", "--config={root}/conf"], P_IN_REPO),
    "output-path": (["{outside}/broker", "-o{root}/out"], P_IN_REPO),
    "env-ambiguous-i": (["env", "--i", "{outside}/broker"], P_UNREADABLE),
    "env-unknown-option": (["env", "--no-such-option", "{outside}/broker"],
                           P_UNREADABLE),
    "env-ambiguous-d": (["env", "--d", "{outside}/broker"], P_UNREADABLE),
    "env-bundled-split-string": (["env", "-iS", "python3 -c 'import runpy'"],
                                 P_INLINE),
    "timeout-abbreviated": (["timeout", "--sig", "KILL", "5", "python3",
                             "-c", "import runpy"], P_INLINE),
    "stdbuf-abbreviated": (["stdbuf", "--out=L", "python3", "-c",
                            "import runpy"], P_INLINE),
    "env-split-string-variable": (["env", "-S", "$BROKER"], P_INLINE),
}


@pytest.mark.parametrize("case", sorted(BATCH_P))
def test_F16_1_batch_p_each_command_is_refused_by_name_everywhere(
        served, capsys, monkeypatch, case):
    """F16.1 as T007 batch P amends it: each command is refused BY NAME by
    `add` (nothing written), `edit` (the document as it was), `trust`
    (nothing recorded) and `set-credential` (no credential read), each
    naming its remedy; with a trust recorded for it before the rule, it
    reads untrusted, the catalog lists it `available: false`, a turn naming
    it is refused by name before any process is spawned, and so is a
    verdict that admits it, at the gate beneath; no marker file exists."""
    trust_mod = _trust_mod()
    where = _batch_p_world(served, monkeypatch)
    template, kind = BATCH_P[case]
    argv = [member.replace("{root}", where["root"]).replace(
        "{outside}", where["outside"]) for member in template]
    reason, remedy = {
        P_IN_REPO: (trust_mod.REASON_IN_REPOSITORY,
                  trust_mod.REMEDY_IN_REPOSITORY),
        P_INLINE: (trust_mod.REASON_INLINE_SCRIPT,
                        trust_mod.REMEDY_INLINE_SCRIPT),
        P_UNREADABLE: (trust_mod.REASON_UNREADABLE_COMMAND,
                     trust_mod.REMEDY_INLINE_SCRIPT)}[kind]
    document = binding_mod.bindings_path(served.repo)

    def refused_by_name(rc: int) -> None:
        assert rc == 1, argv
        err = capsys.readouterr().err
        assert reason in err and remedy in err, err
        _no_trust_command_in(err)

    # add: refused, and nothing is written
    adding = served.add_argv("broker")
    adding = adding[:adding.index("--") + 1] + argv
    refused_by_name(_cli(*adding))
    assert not document.exists()
    # edit: a binding declared outside the repository, edited to this
    # command, is refused, and the document is as it was
    served.hand_write(served.record("broker"))
    held = document.read_bytes()
    editing = list(adding)
    editing[1] = "edit"
    refused_by_name(_cli(*editing))
    assert document.read_bytes() == held
    # trust: declared by hand, as a clone delivers it; nothing is recorded
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    refused_by_name(_cli("model-binding", "trust", "--repo-root",
                         str(served.repo), BINDING_ID))
    assert not _held_entries(served)

    # set-credential: refused, and the credential is never read
    class _MustNotBeRead:
        def read(self, *_args):
            raise AssertionError("set-credential read a credential for a "
                                 "binding it may not hand one to")

    args = cli_mod.build_parser().parse_args([
        "model-binding", "set-credential", "--repo-root", str(served.repo),
        "--id", BINDING_ID])
    rc = cli_mod.cmd_model_binding_set_credential(args,
                                                  source=_MustNotBeRead())
    assert rc == 1
    assert reason in capsys.readouterr().err
    # a trust recorded before the rule admits nothing: no process spawns
    served.trust.record(binding, root=served.repo)
    verdict = trust_mod.verdict_for(binding, root=served.repo)
    assert not verdict.trusted and verdict.reason == reason, verdict
    port = served.port()
    assert isinstance(port, trust_mod.UntrustedBindingPort), port
    assert [entry.available for entry in port.catalog().entries] == [False]
    with pytest.raises(trust_mod.BindingUntrusted) as turned:
        port.dispatch(_Envelope())
    assert remedy in str(turned.value)
    admitted = trust_mod.TrustVerdict.trusted_for(
        binding, root=served.repo, basis=trust_mod.BASIS_HOST)
    with pytest.raises(binding_mod.BindingRefused):
        provider_mod.mint(binding, trust=admitted)
    served.nothing_was_touched()


def _names_a_place_inside(value: str, root: Path) -> bool:
    """Whether any entry of `value` names a place inside `root`, read from
    the file system's root and from the served root, as written and with
    its links followed: the test's own reading, not the rule's. A bare word
    (`C.UTF-8`) is a path only where a file of that name is there."""
    served_root = root.resolve()
    for part in value.split(os.pathsep):
        if not part:
            continue
        for base in (os.sep, str(root)):
            if os.sep not in part and not os.path.lexists(
                    os.path.join(base, part)):
                continue
            path = os.path.join(base, part)
            for spelled in (Path(os.path.normpath(path)),
                            Path(os.path.realpath(path))):
                if spelled == served_root or served_root in spelled.parents:
                    return True
                if spelled == root or root in spelled.parents:
                    return True
    return False


def test_F16_1_batch_p_an_outside_broker_runs_with_nothing_inside_the_root(
        served, capsys, monkeypatch):
    """F16.1 as T007 batch P amends it: a broker outside the served root,
    once trusted, runs, and does so in a working directory outside the root
    (opendox itself started AT the root), with neither `PWD` nor `OLDPWD`,
    no variable whose value is a path inside the root, and no entry inside
    the root in a path list: `PATH`, `PYTHONPATH` and `NODE_PATH` each
    carry an entry inside it, a scalar variable names a directory inside
    it, and each is tried again through an alias outside the root that
    leads in, and through a link inside the root that leads out."""
    trust_mod = _trust_mod()
    root = served.repo
    tools = root / "tools"
    tools.mkdir()
    outside = served.tmp / "outside"
    outside.mkdir()
    (outside / "alias").symlink_to(tools, target_is_directory=True)
    real_out = served.tmp / "real-out"
    real_out.mkdir()
    (tools / "out").symlink_to(real_out, target_is_directory=True)
    seen = served.tmp / "broker-saw.json"
    recording = served.tmp / "recording-broker.py"
    recording.write_text(
        "import json, os\n"
        f"open({str(seen)!r}, 'w').write(json.dumps("
        "{'cwd': os.getcwd(), 'env': dict(os.environ)}))\n"
        + served.broker.read_text(encoding="utf-8"), encoding="utf-8")
    from opendox import doxbench_bridge

    # every variable below reaches the broker unless the rule drops it
    monkeypatch.setattr(doxbench_bridge, "INHERITED_ENVIRONMENT",
                        (*doxbench_bridge.INHERITED_ENVIRONMENT, "PWD",
                         "OLDPWD", "PYTHONPATH", "NODE_PATH",
                         "OPENDOX_TEST_HOME", "OPENDOX_TEST_ALIAS",
                         "OPENDOX_TEST_OUT"))
    inside_entries = [str(tools), str(outside / "alias"), str(tools / "out"),
                      "tools"]
    served.environ["PATH"] = os.pathsep.join(
        [*inside_entries, served.environ.get("PATH", "")])
    served.environ["PYTHONPATH"] = os.pathsep.join(inside_entries)
    served.environ["NODE_PATH"] = os.pathsep.join(inside_entries)
    served.environ["OPENDOX_TEST_HOME"] = str(tools)
    served.environ["OPENDOX_TEST_ALIAS"] = str(outside / "alias")
    served.environ["OPENDOX_TEST_OUT"] = str(tools / "out")
    served.environ["PWD"] = str(root)
    served.environ["OLDPWD"] = str(root)
    monkeypatch.chdir(root)
    adding = served.add_argv("broker")
    adding[-1] = str(recording)
    assert _cli(*adding) == 0
    capsys.readouterr()
    port = served.port()
    assert isinstance(port, provider_mod.BrokeredProviderPort)
    with contextlib.suppress(Exception):
        port.dispatch(_Envelope())
    saw = json.loads(seen.read_text(encoding="utf-8"))
    assert Path(saw["cwd"]) == Path(provider_mod.BROKER_WORKING_DIRECTORY)
    assert root.resolve() not in Path(saw["cwd"]).resolve().parents
    environment = saw["env"]
    assert "PWD" not in environment and "OLDPWD" not in environment
    for name, value in environment.items():
        assert not _names_a_place_inside(value, root), (name, value)
    for name in ("PYTHONPATH", "NODE_PATH", "OPENDOX_TEST_HOME",
                 "OPENDOX_TEST_ALIAS", "OPENDOX_TEST_OUT"):
        assert name not in environment, (name, environment.get(name))
    # what the console's PATH held outside the root is kept
    assert environment["PATH"].split(os.pathsep)[-1:] == (
        served.environ["PATH"].split(os.pathsep)[-1:])
    assert trust_mod.verdict_for(served.declared(), root=root).trusted


def test_F16_1_batch_p_a_programs_bare_name_is_found_where_it_runs(
        served, monkeypatch):
    """The other side of judging a relative path from the served root as
    well: the PROGRAM's bare name is found on the search path, as the child
    finds it, so a file of that name at the root does not make a program
    found outside the repository one inside it. A bare ARGUMENT that names
    a file at the root is judged, fail-closed."""
    trust_mod = _trust_mod()
    tool = served.tmp / "bin" / "opref-tool"
    tool.parent.mkdir()
    tool.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    os.chmod(tool, 0o755)
    (served.repo / "opref-tool").write_text("", encoding="utf-8")
    (served.repo / "opref-config").write_text("", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{tool.parent}{os.pathsep}"
                       f"{os.environ.get('PATH', '')}")
    assert trust_mod.broker_command_refused(
        ["opref-tool", "show"], root=served.repo) is None
    assert trust_mod.broker_command_refused(
        ["opref-tool", "opref-config"], root=served.repo) == (
            trust_mod.REASON_IN_REPOSITORY)


def test_F16_1_batch_p_a_relative_word_is_judged_from_the_root_where_it_names_a_place_there(
        served):
    """Judging a relative path from the served root as well reads it as the
    repository's author wrote it: where its first name is one the root
    holds, or `..`, it is judged there, and refused where it reaches inside
    (`../r/tools/broker.py` from the root is the repository's own file).
    A word whose first name the root does not hold is judged where the
    broker runs alone: the rest of an option cluster, a format, a URL, a
    sibling of the root."""
    trust_mod = _trust_mod()
    (served.repo / "tools").mkdir()
    for argv in (["perl", "-wI/usr/lib/perl5", "/opt/opendox-test/x.pl"],
                 ["date", "--format=%Y/%m"],
                 ["python3", "../sibling/broker.py"],
                 ["python3", "conf/broker.yaml"],
                 ["opref-tool", "-o/tmp/opendox-test-out"],
                 ["opref-tool", "--issuer=https://auth.example/v1"]):
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) is None, argv
    for argv in (["python3", "tools/broker.py"],
                 ["python3", f"../{served.repo.name}/tools/broker.py"],
                 ["python3", "./tools/broker.py"]):
        assert trust_mod.broker_command_refused(
            argv, root=served.repo) == trust_mod.REASON_IN_REPOSITORY, argv


def test_R3_a_variable_off_the_path_list_is_kept_whole_or_dropped_whole(
        served, monkeypatch):
    """The holder's ruling, openxFactory#656 comment 5986391296, on Copilot
    at openDox-code#86, r4180041233: only the CLOSED list of path-list
    variables loses its entries inside the served repository; any other
    variable is never edited, and is dropped WHOLE where any part of it
    names a path inside, so a `HOME` or a `TMPDIR` is never emptied or
    cut."""
    from opendox import doxbench_bridge

    monkeypatch.setattr(doxbench_bridge, "INHERITED_ENVIRONMENT",
                        (*doxbench_bridge.INHERITED_ENVIRONMENT,
                         *sorted(provider_mod.PATH_LIST_VARIABLES),
                         "OPENDOX_TEST_LIST"))
    inside = served.repo / "tools"
    inside.mkdir()
    outside = served.tmp / "outside"
    outside.mkdir()
    colon = served.tmp / "a:scratch"
    colon.mkdir()
    sep = os.pathsep
    base = {"HOME": str(colon), "TMPDIR": f"{outside}{sep}{inside}",
            "LANG": "C.UTF-8", "OPENDOX_TEST_LIST": f"{outside}{sep}{inside}"}
    for name in provider_mod.PATH_LIST_VARIABLES:
        base[name] = f"{inside}{sep}{outside}{sep}tools"
    environment = provider_mod.broker_environment(base, root=served.repo)
    assert environment["HOME"] == str(colon)        # never cut at its `:`
    assert "TMPDIR" not in environment              # dropped whole
    assert "OPENDOX_TEST_LIST" not in environment   # off the list: whole
    assert environment["LANG"] == "C.UTF-8"
    for name in provider_mod.PATH_LIST_VARIABLES:
        assert environment[name] == str(outside), name
    assert provider_mod.PATH_LIST_VARIABLES == frozenset({
        "PATH", "PYTHONPATH", "NODE_PATH", "LD_LIBRARY_PATH", "PERL5LIB",
        "PERLLIB", "RUBYLIB", "CLASSPATH", "GEM_PATH", "MANPATH"})


def test_F16_1_batch_p_an_environment_value_is_judged_entry_by_entry(served):
    """`names_a_path_inside` reads a value as a path list, so an entry
    inside the served root is found wherever it stands in the list."""
    trust_mod = _trust_mod()
    (served.repo / "tools").mkdir()
    inside = str(served.repo / "tools")
    for value in (inside, f"/usr/bin{os.pathsep}{inside}",
                  f"/usr/bin{os.pathsep}/bin{os.pathsep}tools"):
        assert trust_mod.names_a_path_inside(value, root=served.repo), value
    for value in ("/usr/bin", f"/usr/bin{os.pathsep}/bin", "C.UTF-8", ""):
        assert not trust_mod.names_a_path_inside(value,
                                                 root=served.repo), value


@pytest.mark.parametrize("alias", ["program-link", "script-link",
                                   "path-entry"])
def test_F16_1_batch_p_a_trust_recorded_outside_admits_nothing_once_it_leads_in(
        served, capsys, monkeypatch, alias):
    """F16.1 as T007 batch P amends it: a trust recorded, by `trust`, while
    the binding's paths resolved outside the served root does not admit it
    once a link, or the `PATH` entry, leads inside: it reads untrusted, the
    catalog lists it `available: false`, a turn is refused by name before
    any spawn, and no marker file exists."""
    trust_mod = _trust_mod()
    marking = _MARKING_PYTHON.format(marker=str(served.marker))
    outside = served.tmp / "outside"
    outside.mkdir()
    real = outside / "broker"
    real.write_text(f"#!{sys.executable}\n" + marking, encoding="utf-8")
    os.chmod(real, 0o755)
    tools = served.repo / "tools"
    tools.mkdir()
    inside = tools / "broker"
    inside.write_text(f"#!{sys.executable}\n" + marking, encoding="utf-8")
    os.chmod(inside, 0o755)
    link = outside / "link"
    if alias == "path-entry":
        first = served.tmp / "first"
        first.mkdir()
        (first / "opref-broker").symlink_to(real)
        monkeypatch.setenv("PATH", f"{first}{os.pathsep}"
                           f"{os.environ.get('PATH', '')}")
        argv = ["opref-broker"]
    else:
        link.symlink_to(real)
        argv = ([str(link)] if alias == "program-link"
                else ["python3", str(link)])
    served.hand_write(served.record("broker", broker_argv=argv))
    binding = served.declared()
    assert _cli("model-binding", "trust", "--repo-root", str(served.repo),
                BINDING_ID) == 0
    capsys.readouterr()
    assert trust_mod.verdict_for(binding, root=served.repo).trusted
    # it now leads inside: the link retargeted, or a PATH entry under the
    # root put first
    if alias == "path-entry":
        (tools / "opref-broker").symlink_to(inside)
        monkeypatch.setenv("PATH", f"{tools}{os.pathsep}"
                           f"{os.environ['PATH']}")
    else:
        link.unlink()
        link.symlink_to(inside)
    verdict = trust_mod.verdict_for(binding, root=served.repo)
    assert not verdict.trusted
    assert verdict.reason == trust_mod.REASON_IN_REPOSITORY
    port = served.port()
    assert isinstance(port, trust_mod.UntrustedBindingPort), port
    assert [entry.available for entry in port.catalog().entries] == [False]
    with pytest.raises(trust_mod.BindingUntrusted):
        port.dispatch(_Envelope())
    served.nothing_was_touched()
