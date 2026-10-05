"""F2: the line `add`, `edit`, `set-credential` and `trust` end with names
what trusts the binding (the pre-review of openxFactory#1236; release 1's
follow-on slice B, openxFactory#656 comment 6000630835).

THE DEFECT, at openDox-code `389e5a4a`. Under a host whose trust policy's
`record()` answers nothing (openxFactory's governed policy, T094), openDox
asks that policy's `verdict` instead and writes nothing to this machine's
store (the holder's ruling, openxFactory#656 comment 5986391296). Yet
`opendox model-binding trust` printed `trusted "m1" on this machine`:
`cli_model_binding._trusted_line` ignored `TrustRecording.recorded`.

THE FIX. Where the policy recorded nothing, the line names the host's trust
policy as what trusts the binding, and never says "on this machine". Where
a record WAS written (openDox's own store), the line is byte for byte what
it was; the standalone cases below hold it to that exact string, and pass
at main as on this branch.

Each case marked RED AT MAIN fails at `389e5a4a`; the standalone cases are
the byte-identity pins, green at both.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from opendox import cli as cli_mod
from opendox import doxbench_binding as binding_mod
from opendox import doxbench_trust as trust_mod

BINDING_ID = "m1"

#: A stand-in broker: it takes custody at `intake` and answers with a
#: reference, as the broker contract's intake answer reads.
_BROKER = """\
import json, sys
members = sys.argv[1:]
if members and members[0] == "intake":
    sys.stdin.read()
    print(json.dumps({"schema_version": 1,
        "kind": "openprofiler_broker_intake",
        "reference": "opref-fffffffffffffffffffffff1", "binding": "b",
        "provider": "p", "auth_kind": "api_key", "label": None,
        "created_at": "2026-10-02T00:00:00Z", "max_lifetime_seconds": 300,
        "issued_by": "stand-in", "approved_by": "a", "audit_ref": "opaud-1"}))
"""


class _RecordsNothing:
    """A host's policy whose `record()` writes nothing and answers nothing,
    as openxFactory's governed policy does (T094): its `verdict` decides,
    and it trusts every binding."""

    def verdict(self, binding, *, root):
        return trust_mod.TrustVerdict.trusted_for(
            binding, root=root, basis=trust_mod.BASIS_HOST)

    def record(self, binding, *, root):
        return None


class _World:
    """One case's served repository, its own state directory, and a broker
    outside the repository."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        self.repo = tmp_path / "r"
        self.repo.mkdir()
        self.state_dir = tmp_path / "st"
        monkeypatch.setenv("OPENDOX_STATE_DIR", str(self.state_dir))
        self.broker = tmp_path / "broker.py"
        self.broker.write_text(_BROKER, encoding="utf-8")

    def register(self, shape: str) -> None:
        trust_mod.unregister()
        trust_mod.register(
            trust_mod.MachineTrust(state_dir=self.state_dir)
            if shape == "standalone" else _RecordsNothing())

    def record(self) -> dict:
        return {"kind": "model-provider-binding", "id": BINDING_ID,
                "label": "Model one", "provider": "anyone",
                "credential_ref": "opref-0123456789abcdef01234567",
                "auth_kind": "api_key", "approved_by": "operator",
                "endpoint": "http://127.0.0.1:9/v1/chat/completions",
                "dialect": "openai-chat-v1", "model": None,
                "broker_argv": [sys.executable, str(self.broker)]}

    def hand_write(self) -> None:
        """The bindings document, as a clone delivers it. JSON is YAML."""
        path = binding_mod.bindings_path(self.repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1, "kind": "model-provider-bindings",
            "bindings": [self.record()]}), encoding="utf-8")

    def declaring(self, verb: str, label: str = "Model one") -> list[str]:
        record = self.record()
        return ["model-binding", verb, "--repo-root", str(self.repo),
                "--id", BINDING_ID, "--label", label,
                "--provider", record["provider"],
                "--auth-kind", record["auth_kind"],
                "--credential-ref", record["credential_ref"],
                "--credential-approver", record["approved_by"],
                "--endpoint", record["endpoint"],
                "--dialect", record["dialect"], "--",
                *record["broker_argv"]]


@pytest.fixture
def world(tmp_path, monkeypatch):
    served = _World(tmp_path, monkeypatch)
    try:
        yield served
    finally:
        trust_mod.unregister()


def _cli(*argv: str) -> int:
    """A `model-binding` verb, as `opendox` runs it."""
    args = cli_mod.build_parser().parse_args(list(argv))
    return args.func(args)


def _run(world: _World, verb: str) -> int:
    """`verb`, run over `world` as an operator runs it, after what it needs:
    `trust`, `edit` and `set-credential` act on a declared binding, and
    `set-credential` on one already trusted, whose broker takes custody."""
    if verb == "add":
        return _cli(*world.declaring("add"))
    world.hand_write()
    if verb == "trust":
        return _cli("model-binding", "trust", "--repo-root", str(world.repo),
                    BINDING_ID)
    if verb == "edit":
        return _cli(*world.declaring("edit", label="Renamed"))
    _cli("model-binding", "trust", "--repo-root", str(world.repo), BINDING_ID)
    args = cli_mod.build_parser().parse_args([
        "model-binding", "set-credential", "--repo-root", str(world.repo),
        "--id", BINDING_ID])
    return cli_mod.cmd_model_binding_set_credential(
        args, source=io.StringIO("sk-stand-in-NOT-A-KEY"))


def _trusted_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("  trusted ")]


VERBS = ["add", "edit", "set-credential", "trust"]


@pytest.mark.parametrize("verb", VERBS)
def test_F2_a_host_that_recorded_nothing_is_named_as_what_trusts_it(
        world, capsys, verb):
    """RED AT MAIN (`trusted "m1" on this machine for ...`). Under a host's
    policy that recorded nothing, each act's last line names the host's
    trust policy, and does not say "on this machine"; nothing is written to
    this machine's store."""
    world.register("host")
    assert _run(world, verb) == 0
    lines = _trusted_lines(capsys.readouterr().out)
    expected = (f"  trusted {json.dumps(BINDING_ID)} by the host's trust "
                f"policy for {json.dumps(str(world.repo.resolve()))}")
    assert lines[-1] == expected, lines
    assert all("on this machine" not in line for line in lines), lines
    assert not world.state_dir.exists()


@pytest.mark.parametrize("verb", VERBS)
def test_F2_a_record_written_on_this_machine_keeps_its_exact_line(
        world, capsys, verb):
    """A PIN, green at main too: the byte-identity proof. Where openDox's
    own store recorded the trust, each act's last line is exactly what it
    was before F2, character for character."""
    world.register("standalone")
    assert _run(world, verb) == 0
    lines = _trusted_lines(capsys.readouterr().out)
    expected = (f"  trusted {json.dumps(BINDING_ID)} on this machine for "
                f"{json.dumps(str(world.repo.resolve()))}")
    assert lines[-1] == expected, lines
    assert world.state_dir.is_dir()
