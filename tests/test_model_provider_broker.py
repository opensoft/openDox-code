"""add-model-provider-broker: the binding, the hand-off, the mint, the expiry
ruling, and the refusals (tasks 1.1-1.3, 2.1-2.6, 3.1-3.3).

Five layers, each proving a different thing about the same machinery:

  (a) THE RECORD — a binding holds an id, a label, a provider, a credential
      reference, an auth kind, an approver, the provider route (endpoint and
      dialect) and a broker invocation, and NO secret field exists in the shape
      to hold anything else;
  (b) THE STORE — list, add, edit, remove, and a read-back that discloses the
      binding and states where the credential actually lives;
  (c) THE HAND-OFF — a real broker child process, a real credential streamed
      to its standard input, and then a grep of the WHOLE checkout and every
      string the surface produced, looking for the value. It is never there;
  (d) THE MINT AND THE TURN — the declared argv is assembled and executed, the
      token lives in memory and in no response, and Brett's 2026-08-26 expiry
      ruling (re-mint and retry ONCE, visibly recorded, correlated on the
      broker's side with `--retry-of`; a second expiry refuses) is exercised in
      both directions;
  (e) THE POSTURES — every broker and provider failure lands on the fixed,
      redacted refusal `doxbench_model.dispatch_turn` already defines, and the
      UNCONFIGURED posture is byte-for-byte what it was before this change.

A SIXTH LAYER, (f), holds #1144 Group 16's binding and provider boxes (plan
034 phase 3, slice P3-B). 16.1 is the OpenAI-compatible dialect (T078), 16.2
is the model name the provider receives (T079), and 16.3 is the credential
staying a reference: a key in the URL or an extra field refused, the built-in
`env:` and keyring resolver, and the auth kind `none` (T080). Its last section
holds a broker's minted token to the rules T080 gave a built-in credential
(the broker path's hardening, Brett Heap's word of 2026-09-29).

THE FAKE BROKER SPEAKS THE DECLARED CONTRACT (task 2.6). It was this
repository's own invented stdin/stdout protocol until the reconciliation, which
meant every test here agreed with a broker that does not exist. It now takes the
operation as an argv SUBCOMMAND, reads standard input to EOF as the secret for
`intake` and not at all otherwise, and answers in openProfiler's own declared
kinds and fields — so the fake and the REAL binary agree, and
`test_openprofiler_broker_e2e.py` proves the same seam against
`openprofiler-broker` itself whenever it is on PATH.

The broker in (c)/(d) is a REAL child process — a small Python script this file
writes — because the whole contract under test is a stdin/stdout contract with
a subprocess, and a mocked `subprocess` would prove nothing about it. The
provider is a real loopback HTTP server in one test (to prove the transport and
the authorization header) and an injected opener in the rest (so failure modes
are scriptable and no test depends on timing).
"""

from __future__ import annotations

import builtins
import contextlib
import dataclasses
import functools
import http.client
import http.server
import io
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import REPO_ROOT  # noqa: F401  (path setup)

from opendox import cli as cli_mod
from opendox import doxbench_binding as binding_mod
from opendox import doxbench_install as install_mod
from opendox import doxbench_intake as intake_mod
from opendox import doxbench_model as model_mod
from opendox import doxbench_provider as provider_mod
from opendox.runtime import config as runtime_config
from opendox.runtime import local_git_adapter as git_adapter_mod

# The credential a human types. A SENTINEL: long, unique, and impossible to
# produce by accident, so a sweep that finds it has found the real thing.
SENTINEL_CREDENTIAL = "sk-sentinel-DO-NOT-PERSIST-4f19a7c2e5b840d6"

# The token the fake broker mints. A second sentinel, for the same reason.
SENTINEL_TOKEN = "mint-sentinel-9d3b71ca0e6f4827-DO-NOT-DISCLOSE"

# A reference-shaped value, in the declaration's own spelling.
FAKE_REFERENCE = "opref-4f2a91c07be3d5a8140b6e77"
FAKE_INTAKE_AUDIT = "opaud-9c31e0b57af2648d0d13a5ce"

ENDPOINT = "https://provider.invalid/turn"

# The port's banned member spellings, CARRIED HERE (plan 034 T035). This test
# imported them from `test_doxbench_model`, a test module that stayed in
# openxFactory at the carve and never arrived at this leg, so the import failed
# and the case never ran. The set is copied verbatim from that module's
# `FORBIDDEN_PORT_MEMBERS` (openxFactory `tests/ideation-dashboard/
# test_doxbench_model.py`, where it pins `opendox.doxbench_model
# .WorkbenchModelPort`'s own member set). This is its only reader here, so it
# lives beside the one test that reads it, rather than in a new helper module.
FORBIDDEN_PORT_MEMBERS = frozenset({
    "generate", "complete", "chat", "send", "assemble_prompt", "prompt",
    "validate", "validate_response", "render", "save", "ensemble", "review",
    "credentials", "api_key", "endpoint", "client",
})


@pytest.fixture(autouse=True)
def _a_private_trust_store(tmp_path_factory):
    """THE TRUST SEAM, OVER A STORE OF EACH CASE'S OWN (#1144 16.3a; plan 034
    T100). `opendox model-binding add` and `edit` now record trust, and the
    entry points' factory asks for it, so every case here runs with openDox's
    own `MachineTrust` over a private state directory, never the operator's
    real one. Outside `tmp_path`, so a case that sweeps its own tree for a
    secret sweeps nothing this put there."""
    from opendox import doxbench_trust

    doxbench_trust.unregister()
    doxbench_trust.register(doxbench_trust.MachineTrust(
        state_dir=tmp_path_factory.mktemp("trust") / "st"))
    try:
        yield
    finally:
        doxbench_trust.unregister()


def _trusted(binding):
    """A verdict trusting exactly `binding` (#1144 16.3a): what the entry
    points' factory hands the provider for a binding the policy trusts. The
    provider refuses any act on a binding no verdict covers, which
    `tests/test_model_binding_trust.py` holds."""
    from opendox import doxbench_trust

    return doxbench_trust.TrustVerdict.trusted_for(binding, root=None,
                                                   basis="test")


def _trust_in_place(binding, checkout) -> None:
    """Trust `binding` at `checkout` in the case's private store, as `opendox
    model-binding trust` does, for a case that writes its bindings by hand."""
    from opendox import doxbench_trust

    doxbench_trust.policy().record(binding, root=checkout)


def _binding(**overrides):
    fields = dict(id="openprofiler-demo", label="Demo brokered provider",
                  provider="demo-provider", credential_ref=FAKE_REFERENCE,
                  auth_kind="api_key", approved_by="brett@opensoft.one",
                  endpoint=ENDPOINT,
                  dialect=binding_mod.DIALECT_XFACTORY_PROMPT_V1,
                  broker_argv=("openprofiler-broker",))
    fields.update(overrides)
    return binding_mod.ModelProviderBinding(**fields)


# ===========================================================================
# (a) THE RECORD (task 1.1)
# ===========================================================================


def test_the_binding_declares_exactly_the_fields_the_seam_needs():
    binding = _binding()
    assert [field.name for field in dataclasses.fields(binding)] == \
        list(binding_mod.BINDING_FIELDS)


@pytest.mark.parametrize("secret_field", [
    "secret", "api_key", "token", "credential", "value", "password"])
def test_no_secret_field_exists_in_the_shape_to_populate(secret_field):
    """NOT OPTIONAL — ABSENT. The dataclass is slotted and frozen, so a secret
    cannot be passed in and cannot be attached afterwards. Ten fields now
    rather than five (#1144 box 16.2 added `model`), and the absence of an
    eleventh is the same claim."""
    with pytest.raises(TypeError):
        _binding(**{secret_field: SENTINEL_CREDENTIAL})
    binding = _binding()
    # A frozen SLOTTED dataclass refuses the assignment with a `TypeError` out
    # of its regenerated `__setattr__` rather than the `FrozenInstanceError` an
    # unslotted one raises; both are refusals and the tuple names all three so
    # this test pins the REFUSAL rather than one interpreter's spelling of it.
    with pytest.raises((AttributeError, TypeError,
                        dataclasses.FrozenInstanceError)):
        setattr(binding, secret_field, SENTINEL_CREDENTIAL)


def test_the_auth_kind_vocabulary_is_closed():
    """THREE KINDS since #1144 box 16.3 (RULED R1Q18 (a)), in a pinned order:
    `none` joins after the two that take a credential. A `none` binding names
    no reference and no broker, which is why it is built apart here."""
    assert binding_mod.AUTH_KINDS == ("api_key", "oauth", "none")
    for kind in (binding_mod.AUTH_KIND_API_KEY, binding_mod.AUTH_KIND_OAUTH):
        assert _binding(auth_kind=kind).auth_kind == kind
    assert _binding(auth_kind=binding_mod.AUTH_KIND_NONE, credential_ref=None,
                    broker_argv=()).auth_kind == "none"
    with pytest.raises(binding_mod.BindingRefused):
        _binding(auth_kind="whatever_the_broker_likes")


def test_the_dialect_vocabulary_is_closed_and_refuses_at_declaration():
    """THE REFUSAL MOVED EARLIER (task 2.6, 0.2 FINDING 3).

    The dialect used to arrive in the broker's mint answer and be refused
    there; openProfiler's declaration emits no dialect at all, so the fact is
    the BINDING's and the refusal happens when an operator DECLARES one — before
    any broker is invoked and long before a paid call. Closed, still: an unknown
    grammar refuses rather than being guessed at.

    TWO MEMBERS since #1144 box 16.1 (plan 034 T078), and the order is pinned:
    the prompt grammar stays first, and the OpenAI-compatible chat grammar
    joins after it. The refusal below is the same refusal it always was."""
    assert binding_mod.DIALECTS == ("xfactory-prompt-v1", "openai-chat-v1")
    assert provider_mod.DIALECTS is binding_mod.DIALECTS, \
        "one vocabulary, read from the record that declares it"
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(dialect="some-vendor-native-v9")
    assert "closed vocabulary" in str(caught.value)


def test_the_declared_endpoint_must_name_a_scheme():
    assert _binding(endpoint="http://127.0.0.1:9/turn").endpoint.startswith(
        "http://")
    for bad in ("provider.invalid/turn", "file:///etc/passwd", "  "):
        with pytest.raises(binding_mod.BindingRefused):
            _binding(endpoint=bad)


def test_the_argv_placeholder_vocabulary_is_closed_and_binding_scoped():
    """A template can only ever be filled with facts the binding already
    discloses, which is why the vocabulary is closed to the binding's own
    fields: no substitution can smuggle a value the record does not carry."""
    assert binding_mod.ARGV_PLACEHOLDERS == (
        "binding_id", "label", "provider", "credential_ref", "auth_kind",
        "approved_by", "endpoint", "dialect")
    with pytest.raises(binding_mod.BindingRefused):
        _binding(broker_argv=("openprofiler-broker", "--secret", "{api_key}"))
    with pytest.raises(binding_mod.BindingRefused):
        _binding(broker_argv=("openprofiler-broker", "--x", "{unclosed"))


def test_the_declared_base_invocation_is_substituted_from_the_bindings_fields():
    binding = _binding(broker_argv=("openprofiler-broker", "--home",
                                    "/srv/{binding_id}"))
    assert binding.substituted_argv() == (
        "openprofiler-broker", "--home", "/srv/openprofiler-demo")


def test_an_argv_given_as_a_shell_string_is_refused():
    """argv, never a shell string — so no declared value can be read as shell
    syntax."""
    with pytest.raises(binding_mod.BindingRefused):
        _binding(broker_argv="openprofiler-broker mint --reference opref-x")


def test_an_empty_invocation_is_refused():
    with pytest.raises(binding_mod.BindingRefused):
        _binding(broker_argv=())


# ===========================================================================
# (a2) THE DECLARED OPERATION VOCABULARY (task 2.6, 0.2 FINDING 1)
# ===========================================================================


def test_the_operation_is_an_argv_subcommand_and_all_four_are_expressible():
    """0.2 FINDING 1, closed. The adapter names the operation the way
    openProfiler declares it — an argv SUBCOMMAND after the binding's own base
    invocation — and expresses every one of the declaration's four.

    The BASE argv is the operator's (a program this repository cannot verify);
    the SUBCOMMAND and its flags are the declaration's, so an operator cannot
    respell them wrong in a settings file."""
    assert provider_mod.OPERATIONS == ("intake", "mint", "revoke", "list")
    binding = _binding(broker_argv=("/opt/openprofiler-broker", "--quiet"))
    base = ("/opt/openprofiler-broker", "--quiet")

    assert provider_mod.broker_operation_argv(
        binding, provider_mod.OPERATION_INTAKE) == base + (
        "intake",
        "--binding", "openprofiler-demo",
        "--provider", "demo-provider",
        "--auth-kind", "api_key",
        "--approved-by", "brett@opensoft.one",
        "--label", "Demo brokered provider")

    assert provider_mod.broker_operation_argv(
        binding, provider_mod.OPERATION_MINT) == base + (
        "mint", "--reference", FAKE_REFERENCE)

    assert provider_mod.broker_operation_argv(
        binding, provider_mod.OPERATION_MINT,
        retry_of="opaud-1b6d24fe90c3a7550e2f8813") == base + (
        "mint", "--reference", FAKE_REFERENCE,
        "--retry-of", "opaud-1b6d24fe90c3a7550e2f8813")

    assert provider_mod.broker_operation_argv(
        binding, provider_mod.OPERATION_REVOKE) == base + (
        "revoke", "--reference", FAKE_REFERENCE)

    assert provider_mod.broker_operation_argv(
        binding, provider_mod.OPERATION_LIST) == base + ("list",)


def test_an_operation_outside_the_declared_vocabulary_is_a_programming_error():
    with pytest.raises(AssertionError):
        provider_mod.broker_operation_argv(_binding(), "authorize")


def test_no_declared_flag_can_carry_a_credential():
    """The declaration refuses a credential-shaped flag on every command with
    its own `secret_in_argv` code; this side cannot build one either, because
    every value comes from a binding that has no secret field. Two independent
    refusals, agreeing."""
    binding = _binding()
    for operation in provider_mod.OPERATIONS:
        argv = provider_mod.broker_operation_argv(binding, operation)
        for forbidden in ("--secret", "--api-key", "--apikey", "--key",
                          "--token", "--access-token", "--refresh-token",
                          "--credential", "--password", "--passphrase"):
            assert forbidden not in argv
        assert SENTINEL_CREDENTIAL not in " ".join(argv)


# ===========================================================================
# (b) THE STORE (task 1.2)
# ===========================================================================


def _store(tmp_path) -> binding_mod.BindingStore:
    return binding_mod.BindingStore(tmp_path / "bindings.yaml")


def test_an_undeclared_store_is_an_empty_posture_not_an_error(tmp_path):
    store = _store(tmp_path)
    assert store.list() == ()
    assert store.read_back()["bindings"] == []
    assert not store.path.exists()


def test_list_add_edit_remove(tmp_path):
    store = _store(tmp_path)
    store.add(_binding())
    store.add(_binding(id="second", label="Second"))
    assert [b.id for b in store.list()] == ["openprofiler-demo", "second"]

    store.edit(_binding(label="Renamed"))
    assert store.get("openprofiler-demo").label == "Renamed"
    assert [b.id for b in store.list()] == ["openprofiler-demo", "second"], \
        "an edit keeps the binding's position"

    retired = store.remove("second")
    assert retired.id == "second"
    assert [b.id for b in store.list()] == ["openprofiler-demo"]


def test_a_repeated_id_refuses_and_an_unknown_id_refuses(tmp_path):
    store = _store(tmp_path)
    store.add(_binding())
    with pytest.raises(binding_mod.BindingRefused):
        store.add(_binding())
    with pytest.raises(binding_mod.BindingRefused):
        store.edit(_binding(id="never-declared"))
    with pytest.raises(binding_mod.BindingRefused):
        store.remove("never-declared")


def test_the_binding_store_needs_no_yaml_parser_until_a_document_exists():
    """THE HOSTED-PLANE REGRESSION, pinned at the source.

    The lean hosted image has no PyYAML — `test_repo_selector.py`'s
    `test_hosted_posts_do_not_load_notebook_only_dependencies` proves it by
    poisoning the module and serving anyway. Both entrypoints resolve their
    model port through this store at startup, so a module-scope `import yaml`
    here kills every hosted serve before it prints its URL. That was MEASURED
    during this change, not theorised: the test above went red the moment the
    import was at module scope."""
    source = (REPO_ROOT / "src" / "opendox"
              / "doxbench_binding.py").read_text(encoding="utf-8")
    module_scope = [line for line in source.splitlines()
                    if line.startswith("import ") or line.startswith("from ")]
    assert not [line for line in module_scope if "yaml" in line], module_scope
    assert "    import yaml" in source, "the lazy import is still there"


def test_a_missing_yaml_parser_is_a_binding_refusal_not_an_import_error(
        tmp_path, monkeypatch):
    """PR #392 review note d. `_load` imported `yaml` bare, so an install
    without PyYAML that HAD written a bindings document raised
    `ModuleNotFoundError` straight through `declared_model_port_factory` —
    which catches `BindingRefused` and nothing else. The graceful fallback the
    entrypoints promise held only for installs that had never declared
    anything.

    Driven end to end rather than at the exception: the store is given a real
    document, the parser is made unimportable, and the ENTRYPOINT's fallback is
    asserted to still resolve the harness declaration and say so."""
    checkout = tmp_path / "checkout"
    path = binding_mod.bindings_path(checkout)
    path.parent.mkdir(parents=True)
    path.write_text("schema_version: 1\nkind: model-provider-bindings\n"
                    "bindings: []\n", encoding="utf-8")

    import builtins
    real_import = builtins.__import__

    def poisoned(name, *args, **kwargs):
        if name == "yaml":
            raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", poisoned)
    monkeypatch.delitem(sys.modules, "yaml", raising=False)

    with pytest.raises(binding_mod.BindingRefused) as caught:
        binding_mod.BindingStore(path).list()
    assert caught.value.__cause__.__class__ is ModuleNotFoundError
    assert binding_mod.NO_YAML_NOTICE in str(caught.value)

    with pytest.raises(binding_mod.BindingRefused):
        binding_mod.BindingStore(path)._save([])


def test_a_hosted_install_with_a_bindings_document_still_serves(tmp_path,
                                                                capsys,
                                                                monkeypatch):
    """The other half of note d, at the entrypoint: no parser plus a real
    document resolves the harness declaration and prints the reason, instead of
    taking the console down."""
    checkout = tmp_path / "checkout"
    path = binding_mod.bindings_path(checkout)
    path.parent.mkdir(parents=True)
    path.write_text("schema_version: 1\nkind: model-provider-bindings\n"
                    "bindings: []\n", encoding="utf-8")

    import builtins
    real_import = builtins.__import__

    def poisoned(name, *args, **kwargs):
        if name == "yaml":
            raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", poisoned)
    monkeypatch.delitem(sys.modules, "yaml", raising=False)

    # The harness is PRESENT here (plan 034 T081): with it absent, a document
    # read as declaring nothing resolves the no-model port instead, which
    # tests/test_chat_model_configuration.py holds.
    resolve = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout,
        harness_present=lambda: True)
    from opendox import doxbench_bridge as bridge_mod
    assert isinstance(resolve(), bridge_mod.OmpHarnessBridge)
    assert "bindings document could not be read" in capsys.readouterr().err


def test_the_stored_document_carries_schema_version_and_kind(tmp_path):
    store = _store(tmp_path)
    store.add(_binding())
    import yaml
    document = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    assert document["schema_version"] == binding_mod.SCHEMA_VERSION
    assert document["kind"] == binding_mod.BINDINGS_KIND
    assert document["bindings"][0]["kind"] == binding_mod.BINDING_KIND
    assert set(document["bindings"][0]) == {"kind", *binding_mod.BINDING_FIELDS}


def test_a_record_carrying_an_unknown_key_refuses_rather_than_dropping_it(
        tmp_path):
    """A dropped key is how a field an operator believed they declared — a
    secret, most dangerously — vanishes without a word."""
    path = tmp_path / "bindings.yaml"
    record = _binding().as_record()
    record["api_key"] = SENTINEL_CREDENTIAL
    path.write_text(json.dumps({
        "schema_version": 1, "kind": binding_mod.BINDINGS_KIND,
        "bindings": [record],
    }), encoding="utf-8")
    with pytest.raises(binding_mod.BindingRefused):
        binding_mod.BindingStore(path).list()


def test_the_read_back_discloses_the_binding_and_names_the_custodian(tmp_path):
    store = _store(tmp_path)
    store.add(_binding())
    disclosure = store.read_back()
    record = disclosure["bindings"][0]
    assert set(record) == {"kind", *binding_mod.BINDING_FIELDS,
                           "credential_custody"}
    assert record["credential_custody"] == binding_mod.CUSTODY_NOTICE
    assert "broker" in record["credential_custody"]
    # there is no credential material to redact, which is the claim
    assert SENTINEL_CREDENTIAL not in json.dumps(disclosure)


def test_removing_a_binding_says_it_revoked_nothing():
    assert "not revoked" in binding_mod.REMOVAL_NOTICE


def test_the_cli_verbs_list_add_edit_and_remove_a_binding(tmp_path, capsys):
    """TASK 1.2's OPERATOR DOOR, driven through the real parser.

    The store's four verbs are exercised above; what this adds is the surface
    an operator actually touches — that the verbs are registered on the
    entrypoint, that they reach the store, that a read-back names the
    custodian in words, and that a retirement says what it did not revoke.
    Without it, `model-binding` could be wired to nothing and every assertion
    above would still pass."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    parser = cli_mod.build_parser()

    def run(*argv) -> int:
        args = parser.parse_args(list(argv))
        return args.func(args)

    root = ["--repo-root", str(checkout)]
    # the invocation is a POSITIONAL after a bare `--`, because a broker's own
    # argv is full of option-shaped members
    declaration = ["--id", "openprofiler-demo",
                   "--label", "Demo brokered provider",
                   "--provider", "demo-provider",
                   "--credential-ref", FAKE_REFERENCE,
                   "--auth-kind", "api_key",
                   "--credential-approver", "brett@opensoft.one",
                   "--endpoint", ENDPOINT,
                   "--dialect", binding_mod.DIALECT_XFACTORY_PROMPT_V1,
                   "--", "openprofiler-broker", "--home", "/srv/{binding_id}"]

    assert run("model-binding", "list", *root) == 0
    assert "none declared" in capsys.readouterr().out

    assert run("model-binding", "add", *root, *declaration) == 0
    assert binding_mod.CUSTODY_NOTICE in capsys.readouterr().out

    assert run("model-binding", "list", *root) == 0
    listed = capsys.readouterr().out
    assert "openprofiler-demo" in listed
    assert "demo-provider" in listed
    assert ENDPOINT in listed
    assert binding_mod.CUSTODY_NOTICE in listed

    # a repeated id refuses THROUGH THE VERB, not only through the store
    assert run("model-binding", "add", *root, *declaration) == 1
    capsys.readouterr()

    renamed = list(declaration)
    renamed[renamed.index("--label") + 1] = "Renamed"
    assert run("model-binding", "edit", *root, *renamed) == 0
    capsys.readouterr()
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))
    assert store.get("openprofiler-demo").label == "Renamed"

    assert run("model-binding", "remove", *root, "--id",
               "openprofiler-demo") == 0
    assert binding_mod.REMOVAL_NOTICE in capsys.readouterr().out
    assert store.list() == ()


def test_the_cli_refuses_a_dialect_outside_the_closed_vocabulary(tmp_path,
                                                                 capsys):
    parser = cli_mod.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "model-binding", "add", "--repo-root", str(tmp_path),
            "--id", "x", "--label", "L", "--provider", "p",
            "--credential-ref", FAKE_REFERENCE, "--auth-kind", "api_key",
            "--credential-approver", "a@b", "--endpoint", ENDPOINT,
            "--dialect", "some-vendor-native-v9", "--", "openprofiler-broker"])


# ===========================================================================
# a FAKE BROKER THAT SPEAKS THE DECLARED CONTRACT, and a real provider
# ===========================================================================

#: A stand-in for `openprofiler-broker` that answers exactly as
#: `docs/broker-cli.md` declares: the operation is argv[1], `intake` reads
#: standard input to EOF as THE SECRET and every other operation reads none, and
#: each answer is one JSON object of the declared kind carrying exactly the
#: declared fields. It records every invocation, so a test can assert what the
#: adapter actually said to it.
_BROKER_SCRIPT = '''\
import json, sys

ISSUED_BY = "openprofiler-broker/0.1.4-fake"
BINDING = "openprofiler-demo"


def parsed(members):
    flags = {}
    index = 0
    while index < len(members):
        name = members[index]
        if name.startswith("--") and index + 1 < len(members):
            flags.setdefault(name, []).append(members[index + 1])
            index += 2
        else:
            index += 1
    return flags


members = sys.argv[1:]
operation = members[0] if members else ""
flags = parsed(members[1:])
# THE DECLARED STDIN RULE: `intake` reads to EOF and treats all of it as the
# secret; nothing else reads standard input at all.
secret = sys.stdin.read() if operation == "intake" else None

seen = {"argv": members, "operation": operation, "flags": flags,
        "stdin": secret}
with open(sys.argv[0] + ".seen.jsonl", "a", encoding="utf-8") as handle:
    handle.write(json.dumps(seen) + "\\n")
mints = sum(1 for line in open(sys.argv[0] + ".seen.jsonl",
                               encoding="utf-8")
            if json.loads(line)["operation"] == "mint")


def one(name, default=None):
    values = flags.get(name)
    return values[0] if values else default


if operation == "intake":
    print(json.dumps({
        "schema_version": 1, "kind": "openprofiler_broker_intake",
        "reference": %(reference)r, "binding": one("--binding"),
        "provider": one("--provider"), "auth_kind": one("--auth-kind"),
        "label": one("--label"), "created_at": "2026-08-26T14:03:11Z",
        "max_lifetime_seconds": 300, "issued_by": ISSUED_BY,
        "approved_by": one("--approved-by"), "audit_ref": %(intake_audit)r}))
elif operation == "mint":
    print(json.dumps({
        "schema_version": 1, "kind": "openprofiler_broker_mint",
        "reference": one("--reference"), "binding": BINDING,
        "provider": "demo-provider", "auth_kind": "api_key",
        "token": %(token)r, "token_type": "api_key",
        "issued_at": "2026-08-26T14:07:52Z", "expires_at": %(expires)r,
        "expires_in_seconds": 300, "scope": [], "issued_by": ISSUED_BY,
        "approved_by": "brett@opensoft.one",
        "audit_ref": "opaud-mint%%024d" %% mints,
        "retry_of": one("--retry-of"),
        "enforcement": {"expiry": "broker_bookkeeping",
                        "scope": "declared"}}))
elif operation == "revoke":
    print(json.dumps({
        "schema_version": 1, "kind": "openprofiler_broker_revocation",
        "reference": one("--reference"), "binding": BINDING,
        "provider": "demo-provider", "auth_kind": "api_key",
        "revoked": True, "revoked_at": "2026-08-26T14:20:03Z",
        "audit_ref": "opaud-77b0c4e91d3a5628ff0e1a42"}))
else:
    print(json.dumps({
        "schema_version": 1, "kind": "openprofiler_broker_reference_list",
        "references": []}))
'''


def _iso(moment: float) -> str:
    """The declaration's own `expires_at` spelling: ISO-8601 with a `Z`."""
    return datetime.fromtimestamp(moment, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _write_broker(tmp_path, *, token=SENTINEL_TOKEN, expires=None,
                  name="fake-broker.py") -> Path:
    script = tmp_path / name
    script.write_text(_BROKER_SCRIPT % {
        "token": token,
        "expires": _iso(expires if expires is not None else time.time() + 300),
        "reference": FAKE_REFERENCE,
        "intake_audit": FAKE_INTAKE_AUDIT,
    }, encoding="utf-8")
    return script


def _broker_binding(script: Path, **overrides):
    return _binding(broker_argv=(sys.executable, str(script)), **overrides)


def _seen_all(script: Path) -> list:
    path = Path(str(script) + ".seen.jsonl")
    if not path.is_file():
        return []
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines() if line]


def _seen(script: Path) -> dict:
    """The LAST invocation the fake broker recorded."""
    return _seen_all(script)[-1]


# ===========================================================================
# (c) THE HAND-OFF THAT RETAINS NOTHING (task 1.3, task 3.1's sweep)
# ===========================================================================


def test_the_credential_is_the_whole_of_the_brokers_standard_input(tmp_path):
    """0.2 FINDING 2, closed. `intake` reads standard input to EOF and treats
    ALL of it as the secret, so nothing may be written before the credential.
    This adapter used to write a JSON request line first, which would have
    enrolled the line PLUS the value as the credential."""
    script = _write_broker(tmp_path)
    binding = _broker_binding(script)
    reference = provider_mod.hand_off_credential(
        binding, io.StringIO(SENTINEL_CREDENTIAL), trust=_trusted(binding))
    assert reference == FAKE_REFERENCE

    seen = _seen(script)
    assert seen["stdin"] == SENTINEL_CREDENTIAL, \
        "the broker received the value and NOTHING ELSE"
    assert seen["operation"] == "intake"
    assert seen["argv"] == [
        "intake",
        "--binding", "openprofiler-demo",
        "--provider", "demo-provider",
        "--auth-kind", "api_key",
        "--approved-by", "brett@opensoft.one",
        "--label", "Demo brokered provider"]
    assert SENTINEL_CREDENTIAL not in json.dumps(seen["argv"]), \
        "every fact rides a declared FLAG; the secret rides standard input"


def test_a_mint_reads_no_standard_input(tmp_path):
    """The declaration: `mint` does not read standard input and the caller may
    close it. So the adapter closes it, and the broker sees nothing."""
    script = _write_broker(tmp_path)
    provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script)))
    assert _seen(script)["stdin"] is None


def test_the_credential_survives_nowhere_in_the_checkout_or_the_surface(
        tmp_path):
    """THE SWEEP. After a hand-off through the whole operator surface, grep
    every file in the checkout and every string the surface produced."""
    script = _write_broker(tmp_path)
    checkout = tmp_path / "checkout"
    (checkout / "ideation" / "dashboard").mkdir(parents=True)
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))
    store.add(_broker_binding(script, credential_ref="opref-" + "0" * 24))
    # set-credential runs the binding's broker, so it is gated on trust
    # (#1144 16.3a): a binding written by hand is trusted first.
    _trust_in_place(store.get("openprofiler-demo"), checkout)

    args = cli_mod.build_parser().parse_args([
        "model-binding", "set-credential", "--repo-root", str(checkout),
        "--id", "openprofiler-demo"])
    assert cli_mod.cmd_model_binding_set_credential(
        args, source=io.StringIO(SENTINEL_CREDENTIAL)) == 0

    # the reference came back and is what the store now holds
    assert store.get("openprofiler-demo").credential_ref == FAKE_REFERENCE

    # ...and the value is in NO file under the checkout
    offenders = [path for path in checkout.rglob("*")
                 if path.is_file()
                 and SENTINEL_CREDENTIAL in path.read_text(
                     encoding="utf-8", errors="replace")]
    assert not offenders, offenders

    # ...nor in any string the read-back surface produces
    assert SENTINEL_CREDENTIAL not in json.dumps(store.read_back())
    assert SENTINEL_CREDENTIAL not in repr(store.get("openprofiler-demo"))


def test_the_hand_off_takes_a_handle_and_never_a_value():
    """The signature IS the enforcement: a caller cannot pass a credential
    VALUE, so no caller can be holding one."""
    import inspect
    signature = inspect.signature(provider_mod.hand_off_credential)
    # `trust` (#1144 16.3a) is the verdict covering the binding: a fact about
    # the binding, never a value the credential could ride.
    assert list(signature.parameters) == ["binding", "source", "trust",
                                          "runner"]


# ===========================================================================
# (d) THE MINT AND THE TURN (tasks 2.1, 2.4, 2.6)
# ===========================================================================


class _Envelope:
    """The duck-typed prompt envelope every seam in this family accepts."""

    def __init__(self, model_id="openprofiler-demo", text="assembled prompt"):
        self.model_id = model_id
        self._text = text

    def rendered(self) -> str:
        return self._text


def test_a_mint_executes_the_declared_invocation_and_returns_a_token(tmp_path):
    script = _write_broker(tmp_path)
    binding = _broker_binding(script)
    minted = provider_mod.mint(binding, trust=_trusted(binding))
    assert minted.token == SENTINEL_TOKEN
    assert minted.audit_ref.startswith("opaud-")
    # 0.2 FINDING 3: the ROUTE is the binding's, because the declaration's mint
    # answer carries neither an endpoint nor a dialect.
    assert minted.endpoint == binding.endpoint
    assert minted.dialect == binding.dialect
    seen = _seen(script)
    assert seen["operation"] == "mint"
    assert seen["argv"] == ["mint", "--reference", FAKE_REFERENCE]


def test_a_mint_answer_that_named_a_route_would_still_not_supply_one(tmp_path):
    """The binding is the ONLY source of the route. An answer carrying an
    `endpoint` is not a route this client adopts — it is a document with a key
    the declaration does not name, which the exact parse refuses."""
    script = tmp_path / "routing-broker.py"
    script.write_text(
        "import json,sys\n"
        "print(json.dumps({'schema_version':1,"
        "'kind':'openprofiler_broker_mint','reference':'opref-x','binding':'b',"
        "'provider':'p','auth_kind':'api_key','token':'t',"
        "'token_type':'api_key','issued_at':'x','expires_at':99999999999,"
        "'expires_in_seconds':300,'scope':[],'issued_by':'i',"
        "'approved_by':'a','audit_ref':'opaud-x','retry_of':None,"
        "'enforcement':{},'endpoint':'https://elsewhere.invalid'}))\n",
        encoding="utf-8")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script)))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED


def test_an_answer_carrying_an_undeclared_key_is_malformed(tmp_path):
    """PR #392 review note a. `_answer_document` documented "the required keys,
    exactly" and enforced only presence. It enforces the set now: an object
    carrying a key the declaration does not name is not this broker's answer."""
    script = tmp_path / "chatty-broker.py"
    script.write_text(
        "import json,sys\n"
        "print(json.dumps({'schema_version':1,"
        "'kind':'openprofiler_broker_intake','reference':'opref-x',"
        "'binding':'b','provider':'p','auth_kind':'api_key','label':None,"
        "'created_at':'x','max_lifetime_seconds':300,'issued_by':'i',"
        "'approved_by':'a','audit_ref':'opaud-x','debug_note':'hello'}))\n",
        encoding="utf-8")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.hand_off_credential(_broker_binding(script),
                                         io.StringIO("x"), trust=_trusted(_broker_binding(script)))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED


def test_an_answer_missing_a_declared_key_is_malformed(tmp_path):
    script = tmp_path / "terse-broker.py"
    script.write_text(
        "import json,sys\nsys.stdin.read()\n"
        "print(json.dumps({'schema_version':1,"
        "'kind':'openprofiler_broker_intake','reference':'opref-x'}))\n",
        encoding="utf-8")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.hand_off_credential(_broker_binding(script),
                                         io.StringIO("x"), trust=_trusted(_broker_binding(script)))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED


def test_the_declared_answer_field_lists_match_the_declaration():
    """The four field tuples ARE quotations from `docs/broker-cli.md`. Pinned
    here so a future edit to them is a deliberate act rather than a drift, and
    measured against the real binary in `test_openprofiler_broker_e2e.py`."""
    assert provider_mod.INTAKE_FIELDS == (
        "schema_version", "kind", "reference", "binding", "provider",
        "auth_kind", "label", "created_at", "max_lifetime_seconds",
        "issued_by", "approved_by", "audit_ref")
    assert provider_mod.MINT_FIELDS == (
        "schema_version", "kind", "reference", "binding", "provider",
        "auth_kind", "token", "token_type", "issued_at", "expires_at",
        "expires_in_seconds", "scope", "issued_by", "approved_by",
        "audit_ref", "retry_of", "enforcement")
    assert "endpoint" not in provider_mod.MINT_FIELDS
    assert "dialect" not in provider_mod.MINT_FIELDS
    assert provider_mod.REVOCATION_FIELDS == (
        "schema_version", "kind", "reference", "binding", "provider",
        "auth_kind", "revoked", "revoked_at", "audit_ref")
    assert provider_mod.REFERENCE_LIST_FIELDS == (
        "schema_version", "kind", "references")


def test_revoke_and_list_speak_the_declared_surface(tmp_path):
    script = _write_broker(tmp_path)
    binding = _broker_binding(script)
    assert provider_mod.revoke(binding, trust=_trusted(binding)) == "opaud-77b0c4e91d3a5628ff0e1a42"
    assert _seen(script)["argv"] == ["revoke", "--reference", FAKE_REFERENCE]
    assert provider_mod.list_references(binding, trust=_trusted(binding)) == []
    assert _seen(script)["argv"] == ["list"]
    assert _seen(script)["stdin"] is None


def test_the_minted_token_redacts_itself_in_every_rendering(tmp_path):
    script = _write_broker(tmp_path)
    minted = provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script)))
    for rendering in (repr(minted), str(minted), f"{minted}", "%s" % (minted,)):
        assert SENTINEL_TOKEN not in rendering
        assert "<redacted>" in rendering


class _Opener:
    """A scripted stand-in for `urllib.request.urlopen`."""

    def __init__(self, *outcomes):
        self._outcomes = list(outcomes)
        self.requests: list[object] = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        outcome = self._outcomes.pop(0) if self._outcomes else {"assistant_prose": "ok"}
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, bytes):
            return _Response(outcome)
        return _Response(json.dumps(outcome).encode("utf-8"))


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def read(self, amount=None):
        """Honours a byte bound, as a real `http.client.HTTPResponse` does —
        which is what makes the bounded read testable at all."""
        if amount is None:
            return self._payload
        return self._payload[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _expired_error():
    return urllib.error.HTTPError(
        ENDPOINT, 401, "Unauthorized", {},
        io.BytesIO(b'{"provider":"leaky detail that must never surface"}'))


def _port(tmp_path, *outcomes, expires=None, notice=None, clock=time.time,
          endpoint=ENDPOINT, dialect=binding_mod.DIALECT_XFACTORY_PROMPT_V1,
          model=None, token=SENTINEL_TOKEN,
          runner=provider_mod.subprocess_broker_runner):
    script = _write_broker(tmp_path, expires=expires, token=token)
    binding = _broker_binding(script, endpoint=endpoint, dialect=dialect,
                              model=model)
    opener = _Opener(*outcomes)
    port = provider_mod.BrokeredProviderPort(
        binding, install_mod.brokered_catalog(binding),
        runner=runner, opener=opener, clock=clock,
        notice=notice if notice is not None else (lambda _text: None), trust=_trusted(binding))
    return port, opener


def test_a_turn_mints_and_calls_the_provider_with_the_token(tmp_path):
    port, opener = _port(tmp_path, {"assistant_prose": "the answer"})
    assert port.dispatch(_Envelope()) == {"assistant_prose": "the answer",
                                          "proposals": []}
    request = opener.requests[0]
    assert request.get_full_url() == ENDPOINT
    assert request.get_header("Authorization") == f"Bearer {SENTINEL_TOKEN}"
    assert SENTINEL_TOKEN not in request.get_full_url()
    assert SENTINEL_TOKEN not in request.data.decode("utf-8")


def test_the_catalog_never_mints(tmp_path):
    port, opener = _port(tmp_path)
    catalog = port.catalog()
    assert [entry.model_id for entry in catalog.entries] == \
        ["openprofiler-demo"]
    assert catalog.entries[0].available is True
    assert opener.requests == []
    assert _seen_all(tmp_path / "fake-broker.py") == [], \
        "rendering a menu is not a paid call and does not mint"


def test_a_live_token_is_reused_across_turns(tmp_path):
    port, _opener = _port(tmp_path, {"assistant_prose": "a"},
                          {"assistant_prose": "b"})
    port.dispatch(_Envelope())
    port.dispatch(_Envelope())
    assert [event.reason for event in port.ledger] == \
        [provider_mod.REASON_FIRST_MINT]


def test_a_token_past_its_declared_expiry_is_discarded_and_re_minted(tmp_path):
    """Discard-on-expiry, unconditional and independent of the retry ruling: a
    token known to be dead is never presented — and it carries NO `--retry-of`,
    because a token that bought no call replaced no issuance."""
    port, _opener = _port(tmp_path, {"assistant_prose": "a"},
                          {"assistant_prose": "b"},
                          expires=time.time() - 1)
    port.dispatch(_Envelope())
    port.dispatch(_Envelope())
    assert [event.reason for event in port.ledger] == \
        [provider_mod.REASON_FIRST_MINT, provider_mod.REASON_FIRST_MINT]
    for seen in _seen_all(tmp_path / "fake-broker.py"):
        assert "--retry-of" not in seen["argv"]


def test_a_mid_turn_expiry_re_mints_and_retries_once_visibly(tmp_path):
    """BRETT'S RULING, 2026-08-26. The retry happens, it is SEEN, and — since
    the reconciliation — the BROKER is told what it replaces."""
    printed: list[str] = []
    port, opener = _port(tmp_path, _expired_error(),
                         {"assistant_prose": "the retried answer"},
                         notice=printed.append)
    assert port.dispatch(_Envelope()) == {
        "assistant_prose": "the retried answer", "proposals": []}
    assert len(opener.requests) == 2, "exactly one paid retry"
    assert [event.reason for event in port.ledger] == [
        provider_mod.REASON_FIRST_MINT,
        provider_mod.REASON_EXPIRY_REMINT,
        provider_mod.REASON_PAID_RETRY,
    ]
    assert printed and "re-minted once and retried" in printed[0]

    # 0.2 FINDING 5: the re-mint names the mint it replaces, so the broker's
    # own trail shows one turn that needed two tokens.
    mints = [seen for seen in _seen_all(tmp_path / "fake-broker.py")
             if seen["operation"] == "mint"]
    assert len(mints) == 2
    assert "--retry-of" not in mints[0]["argv"]
    assert mints[1]["flags"]["--retry-of"] == [port.ledger[0].audit_ref]
    assert port.ledger[1].audit_ref != port.ledger[0].audit_ref

    # the visible record carries no token, no prompt and no provider detail
    for event in port.ledger:
        rendered = json.dumps(event.as_dict())
        assert SENTINEL_TOKEN not in rendered
        assert "assembled prompt" not in rendered


def test_a_second_expiry_in_one_turn_refuses_rather_than_buying_a_third_call(
        tmp_path):
    port, opener = _port(tmp_path, _expired_error(), _expired_error())
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
    assert caught.value.diagnostic == provider_mod.DIAG_TOKEN_EXPIRED_TWICE
    assert len(opener.requests) == 2, "no third paid call"


def test_the_retry_budget_is_per_turn_not_per_process(tmp_path):
    """A turn that used its retry does not spend the NEXT turn's."""
    printed: list[str] = []
    port, opener = _port(tmp_path, _expired_error(), {"assistant_prose": "a"},
                         _expired_error(), {"assistant_prose": "b"},
                         notice=printed.append)
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    assert port.dispatch(_Envelope())["assistant_prose"] == "b"
    assert len(opener.requests) == 4
    assert len(printed) == 2


# ===========================================================================
# (e) THE POSTURES (tasks 3.1, 3.2, 3.3)
# ===========================================================================


def test_the_token_never_reaches_a_response_a_log_or_the_disk(tmp_path):
    """Task 3.1, asserted rather than assumed."""
    printed: list[str] = []
    port, _opener = _port(tmp_path, {"assistant_prose": "the answer"},
                          notice=printed.append)
    answer = port.dispatch(_Envelope())
    assert SENTINEL_TOKEN not in json.dumps(answer)
    assert SENTINEL_TOKEN not in repr(port)
    assert SENTINEL_TOKEN not in "".join(printed)
    offenders = [path for path in tmp_path.rglob("*")
                 if path.is_file() and SENTINEL_TOKEN in path.read_text(
                     encoding="utf-8", errors="replace")
                 and path.suffix != ".py"]
    assert not offenders, offenders


def test_a_minted_token_does_not_survive_the_object_that_held_it(tmp_path):
    port, _opener = _port(tmp_path, {"assistant_prose": "a"})
    port.dispatch(_Envelope())
    port._forget_token()
    assert SENTINEL_TOKEN not in repr(port)
    assert SENTINEL_TOKEN not in repr(vars(port))


@pytest.mark.parametrize("outcome,expected", [
    (urllib.error.URLError("unreachable"),
     provider_mod.DIAG_PROVIDER_UNREACHABLE),
    (urllib.error.HTTPError("https://p.invalid", 500, "boom", {},
                            io.BytesIO(b"provider stack trace")),
     provider_mod.DIAG_PROVIDER_REFUSED),
    ({"something_else": 1}, provider_mod.DIAG_PROVIDER_MALFORMED),
])
def test_every_provider_failure_lands_on_a_fixed_redacted_sentence(
        tmp_path, outcome, expected):
    port, _opener = _port(tmp_path, outcome)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
    assert caught.value.diagnostic == expected
    assert caught.value.diagnostic in provider_mod.FIXED_DIAGNOSTICS
    for word in ("stack trace", "boom", "unreachable\n"):
        assert word not in str(caught.value)


def test_an_unbounded_provider_answer_is_refused_rather_than_read(tmp_path):
    """PR #392 review note b. `response.read()` took whatever a declared
    endpoint chose to send, so the memory of this process was a function of a
    binding an operator could misdeclare. One byte over the bound is a fixed
    refusal; the bound itself is honoured."""
    bound = provider_mod.MAX_PROVIDER_ANSWER_BYTES
    assert bound == model_mod.SERVER_MAX_OUTPUT_LIMIT_BYTES, \
        "the bound REUSES the server's own declared output ceiling"

    oversize = b'{"assistant_prose": "' + b"x" * bound + b'"}'
    port, _opener = _port(tmp_path, oversize)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_MALFORMED

    prose = "y" * (bound - 64)
    at_the_bound = json.dumps({"assistant_prose": prose}).encode("utf-8")
    assert len(at_the_bound) <= bound
    port, _opener = _port(tmp_path, at_the_bound)
    assert port.dispatch(_Envelope())["assistant_prose"] == prose


def test_a_broker_that_exits_non_zero_is_a_fixed_refusal(tmp_path):
    script = tmp_path / "angry-broker.py"
    script.write_text("import sys\nsys.stderr.write('broker internals')\n"
                      "sys.exit(3)\n", encoding="utf-8")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script)))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_REFUSED
    assert "broker internals" not in str(caught.value)


def test_a_broker_that_refuses_before_reading_stdin_reads_as_a_refusal(
        tmp_path):
    """0.2 FINDING 6, closed. The declaration obliges a consumer to treat
    `EPIPE` on the credential write as "read the refusal", because some
    invocations — an `--auth-kind oauth` intake, above all — are refused BEFORE
    standard input is read at all. This adapter caught the `OSError` and raised
    `DIAG_BROKER_UNREACHABLE`, so an honest refusal read as a broker that could
    not be started.

    Driven with a credential large enough to overflow the pipe buffer, which is
    what makes the write actually fail rather than land in the kernel's buffer
    and be discarded silently."""
    script = tmp_path / "early-refusing-broker.py"
    script.write_text(
        "import json,sys\n"
        "sys.stderr.write(json.dumps({'schema_version':1,"
        "'kind':'openprofiler_broker_error','code':'not_implemented',"
        "'message':'the OAuth path is declared but not built',"
        "'exit_code':5}))\n"
        "sys.exit(5)\n", encoding="utf-8")
    binding = _broker_binding(script, auth_kind="oauth")
    big = io.StringIO("x" * 4_000_000)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.hand_off_credential(binding, big, trust=_trusted(binding))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_REFUSED, \
        "the exit code is the answer, not the write error"
    assert caught.value.diagnostic != provider_mod.DIAG_BROKER_UNREACHABLE


def test_a_broker_that_cannot_be_started_is_still_unreachable(tmp_path):
    """The distinction the finding asked for cuts both ways: a program that
    does not exist is NOT a refusal, and keeps its own sentence."""
    binding = _binding(broker_argv=(str(tmp_path / "no-such-broker"),))
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(binding, trust=_trusted(binding))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_UNREACHABLE


def test_a_broker_that_answers_garbage_is_a_fixed_refusal(tmp_path):
    script = tmp_path / "garbled-broker.py"
    script.write_text("import sys\nprint('not json')\n", encoding="utf-8")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script)))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED


def test_a_refusal_cannot_be_composed_from_what_a_broker_said():
    with pytest.raises(AssertionError):
        provider_mod.BrokerRefused("the provider said: your key is bad")


def test_the_fixed_diagnostics_are_all_reachable_and_no_more():
    """The closed set shed the dialect sentence when the dialect became a
    declaration-time refusal; keeping an unraisable sentence would be a refusal
    nobody can trigger. ELEVEN since #1144 box 16.3: the built-in resolver's
    two joined, and so did the redirect a built-in credential declines.
    Section (f) below reaches each of the three. TWELVE since Brett Heap's
    word of 2026-09-29: a broker answer past the bound has its own sentence,
    and the last section reaches it."""
    assert len(provider_mod.FIXED_DIAGNOSTICS) == 12
    assert {provider_mod.DIAG_REFERENCE_UNRESOLVED,
            provider_mod.DIAG_KEYRING_UNAVAILABLE,
            provider_mod.DIAG_PROVIDER_REDIRECTED,
            provider_mod.DIAG_BROKER_OVERSIZE} <= \
        provider_mod.FIXED_DIAGNOSTICS
    assert provider_mod.BROKER_DIAGNOSTICS == {
        provider_mod.DIAG_BROKER_UNREACHABLE,
        provider_mod.DIAG_BROKER_REFUSED, provider_mod.DIAG_BROKER_MALFORMED,
        provider_mod.DIAG_BROKER_TIMEOUT, provider_mod.DIAG_BROKER_OVERSIZE}
    assert not hasattr(provider_mod, "DIAG_DIALECT_UNKNOWN")


def test_a_broker_failure_maps_onto_the_seams_own_fixed_model_failed(tmp_path):
    """Task 3.2's other half: the redacted refusal this module raises is the
    one `dispatch_turn` already maps to `model_failed`, so nothing new reaches
    the wire and a FAILED CALL stays distinguishable from a MISSING capability
    (which is `model_capability_unavailable`, a different code entirely)."""
    port, _opener = _port(tmp_path, urllib.error.URLError("down"))
    entry = install_mod.brokered_catalog(_binding()).entries[0]
    ticks = iter([0.0, 0.1])
    outcome = model_mod.dispatch_turn(port, _Envelope(), entry=entry,
                                      clock=lambda: next(ticks))
    assert isinstance(outcome, model_mod.TurnDispatchFailure)
    assert outcome.error == model_mod.DISPATCH_ERR_MODEL_FAILED
    assert outcome.diagnostic in model_mod.FIXED_DISPATCH_DIAGNOSTICS
    assert outcome.error != "model_capability_unavailable"


def test_a_broker_that_has_refused_marks_the_catalog_unavailable(tmp_path):
    """The honest posture the harness bridge already keeps: a declaration is
    available until something is measured, and a broker that refused is
    measured. A failure is never reported as an empty result."""
    port, _opener = _port(tmp_path)
    port._binding = _binding(broker_argv=(str(tmp_path / "absent"),))
    port._trust = _trusted(port._binding)
    with pytest.raises(provider_mod.BrokerRefused):
        port.dispatch(_Envelope())
    catalog = port.catalog()
    assert catalog.entries, "the entry is still disclosed, not dropped"
    assert catalog.entries[0].available is False


def test_the_port_satisfies_the_seam_without_growing_a_fourth_verb(tmp_path):
    port, _opener = _port(tmp_path)
    assert isinstance(port, model_mod.WorkbenchModelPort)
    declared = {name for name in dir(port) if not name.startswith("_")}
    assert not (declared & FORBIDDEN_PORT_MEMBERS), \
        declared & FORBIDDEN_PORT_MEMBERS


# --- the unconfigured posture (task 3.3) ----------------------------------


def test_a_checkout_with_no_bindings_resolves_exactly_the_harness_declaration(
        tmp_path):
    """TASK 3.3. Not "a port of the same kind" — the SAME construction the
    entrypoints have always made, WHERE THE HARNESS IS INSTALLED (plan 034
    T081, #1144's 16.4). With it absent, there is no model, and
    tests/test_chat_model_configuration.py holds that state."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    resolve = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout,
        harness_present=lambda: True)
    port = resolve()
    from opendox import doxbench_bridge as bridge_mod
    assert isinstance(port, bridge_mod.OmpHarnessBridge)
    assert [entry.model_id for entry in install_mod.HARNESS_CATALOG.entries] \
        == [install_mod.HARNESS_MODEL_ID]


def test_a_declared_binding_resolves_the_brokered_port_instead(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / "ideation" / "dashboard").mkdir(parents=True)
    script = _write_broker(tmp_path)
    binding_mod.BindingStore(binding_mod.bindings_path(checkout)).add(
        _broker_binding(script))
    # Trusted on this machine (#1144 16.3a): a binding written by hand is
    # refused until it is, which tests/test_model_binding_trust.py holds.
    _trust_in_place(_broker_binding(script), checkout)
    resolve = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout)
    port = resolve()
    assert isinstance(port, provider_mod.BrokeredProviderPort)
    assert resolve() is port, "ONE port for the life of the process"


def test_an_unreadable_bindings_document_falls_back_and_says_so(tmp_path,
                                                                capsys):
    checkout = tmp_path / "checkout"
    path = binding_mod.bindings_path(checkout)
    path.parent.mkdir(parents=True)
    path.write_text("schema_version: 9\nkind: something-else\n",
                    encoding="utf-8")
    # The harness is PRESENT here (plan 034 T081), as in the case above.
    resolve = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout,
        harness_present=lambda: True)
    from opendox import doxbench_bridge as bridge_mod
    assert isinstance(resolve(), bridge_mod.OmpHarnessBridge)
    assert "bindings document could not be read" in capsys.readouterr().err


def test_the_unconfigured_refusal_is_byte_identical_to_what_it_always_was():
    """The `model_capability_unavailable` posture, pinned at the bytes.

    Nothing in this change may move it: a plane with no model port refuses
    exactly as it did, with the same code, the same status and the same
    sentence."""
    from opendox import serve as serve_mod
    code = serve_mod.DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE
    assert code == "model_capability_unavailable"
    assert serve_mod.doxbench_error_status(code) == 403
    assert json.dumps(serve_mod.doxbench_error_body(code),
                      sort_keys=True) == json.dumps(
        {"ok": False, "error": code,
         "message": "this plane has no model capability"}, sort_keys=True)


# --- one real provider, over a real socket --------------------------------


class _RealProviderHandler(http.server.BaseHTTPRequestHandler):
    seen: dict = {}

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's own spelling
        length = int(self.headers.get("Content-Length", "0"))
        _RealProviderHandler.seen = {
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(length).decode("utf-8")),
        }
        payload = json.dumps({"assistant_prose": "answered over a socket"})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))

    def log_message(self, *_args):
        return


def test_the_transport_really_speaks_to_an_endpoint_over_a_socket(tmp_path):
    """The one test that exercises the REAL `urllib` path, against a loopback
    server standing in for a provider. Everything else injects an opener so a
    failure mode is scriptable; this proves the boundary is a real transport
    and that the token travels in the authorization header and nowhere else."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                             _RealProviderHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, prt = server.server_address[:2]
        endpoint = f"http://{host}:{prt}/turn"
        script = _write_broker(tmp_path)
        binding = _broker_binding(script, endpoint=endpoint)
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            notice=lambda _text: None, trust=_trusted(binding))
        assert port.dispatch(_Envelope()) == {
            "assistant_prose": "answered over a socket", "proposals": []}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    seen = _RealProviderHandler.seen
    assert seen["authorization"] == f"Bearer {SENTINEL_TOKEN}"
    assert seen["body"] == {"model": "openprofiler-demo",
                            "prompt": "assembled prompt"}
    assert SENTINEL_TOKEN not in json.dumps(seen["body"])


def test_the_broker_child_inherits_no_credential_shaped_environment(tmp_path,
                                                                    monkeypatch):
    """The child's environment is the same scrubbed allowlist the harness
    bridge uses, so no ambient variable can become an implicit credential."""
    monkeypatch.setenv("SENTINEL_PROVIDER_API_KEY", SENTINEL_CREDENTIAL)
    script = tmp_path / "env-broker.py"
    script.write_text(
        "import json,os,sys\n"
        "open(sys.argv[0]+'.env.json','w').write(json.dumps(sorted(os.environ)))\n"
        "print(json.dumps({'schema_version':1,"
        "'kind':'openprofiler_broker_mint','reference':'opref-x',"
        "'binding':'b','provider':'p','auth_kind':'api_key','token':'t',"
        "'token_type':'api_key','issued_at':'x','expires_at':99999999999,"
        "'expires_in_seconds':300,'scope':[],'issued_by':'i',"
        "'approved_by':'a','audit_ref':'opaud-x','retry_of':None,"
        "'enforcement':{}}))\n", encoding="utf-8")
    provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script)))
    inherited = json.loads(
        Path(str(script) + ".env.json").read_text(encoding="utf-8"))
    assert "SENTINEL_PROVIDER_API_KEY" not in inherited
    assert set(inherited) <= set(
        __import__("opendox.doxbench_bridge", fromlist=["x"])
        .INHERITED_ENVIRONMENT)


def test_the_scrubbed_environment_still_carries_what_a_broker_needs():
    """HOME is how the declaration's own default custody root
    (`~/.openprofiler/broker`) resolves, and PATH is how a binding naming a
    bare program name resolves. The allowlist already carries both, so the
    reconciliation needed no widening of it — which is worth asserting, because
    a broker that could not find its own store would have been a reason to."""
    from opendox import doxbench_bridge as bridge_mod
    assert "HOME" in bridge_mod.INHERITED_ENVIRONMENT
    assert "PATH" in bridge_mod.INHERITED_ENVIRONMENT


def test_a_broker_that_hangs_is_refused_at_the_declared_timeout(tmp_path):
    script = tmp_path / "slow-broker.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    binding = _broker_binding(script)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.subprocess_broker_runner(
            provider_mod.broker_operation_argv(
                binding, provider_mod.OPERATION_MINT),
            timeout=0.5)
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_TIMEOUT


def test_the_broker_answer_is_bounded(tmp_path):
    """One byte past the bound has its own sentence since Brett Heap's word
    of 2026-09-29. It was `DIAG_BROKER_MALFORMED`, beside every answer of
    the wrong shape. An answer at the bound is read, and refused only as
    what it is: here, not JSON."""
    bound = provider_mod.MAX_BROKER_ANSWER_BYTES
    for size, expected in ((bound + 1, provider_mod.DIAG_BROKER_OVERSIZE),
                           (bound, provider_mod.DIAG_BROKER_MALFORMED)):
        script = tmp_path / f"loud-broker-{size}.py"
        script.write_text(f"import sys\nsys.stdout.write('x' * {size})\n",
                          encoding="utf-8")
        with pytest.raises(provider_mod.BrokerRefused) as caught:
            provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script)))
        assert caught.value.diagnostic == expected


def test_the_subprocess_runner_never_uses_a_shell(tmp_path):
    """argv, never a shell string — asserted on the source, because a
    behavioural test cannot prove the absence of a `shell=True` on a path it
    did not take."""
    source = (REPO_ROOT / "src" / "opendox"
              / provider_mod.PROVIDER_CLIENT_MODULE).read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    assert subprocess.Popen is subprocess.Popen  # the module spawns, nothing else


# ===========================================================================
# (f) CHAT'S MODEL CONFIGURATION (#1144 Group 16; plan 034 phase 3, P3-B)
# ===========================================================================
#
# 16.1, the OpenAI-compatible dialect (T078). `openai-chat-v1` is the second
# `DIALECTS` member. Its request is the chat-completions grammar (`model`,
# `messages`), and its answer is read at `choices[0].message.content`. Both are
# spoken by one arm in `doxbench_provider`, beside the prompt grammar's arm.

OPENAI_CHAT = binding_mod.DIALECT_OPENAI_CHAT_V1


def _chat_completion(content="the chat answer"):
    """A chat-completions answer in that grammar's own shape. The keys around
    `choices` are what a real server sends, and nothing here reads them."""
    return {"id": "chatcmpl-stand-in", "object": "chat.completion",
            "model": "stand-in-model",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": content}}]}


def test_f16_1_the_openai_compatible_dialect_is_declared():
    """F16.1's dialect assertion, as #1144 writes it:
    `assert "openai-chat-v1" in b.DIALECTS`. A binding may declare it."""
    assert "openai-chat-v1" in binding_mod.DIALECTS, (
        f"no OpenAI-compatible dialect: {binding_mod.DIALECTS}")
    assert OPENAI_CHAT == "openai-chat-v1"
    assert _binding(dialect=OPENAI_CHAT).dialect == OPENAI_CHAT
    assert provider_mod.DIALECT_OPENAI_CHAT_V1 is OPENAI_CHAT, \
        "one spelling, read from the record that declares it"


def test_every_declared_dialect_has_exactly_one_arm_in_the_provider_module():
    """A member cannot join the vocabulary without an arm, or an arm exist
    for a member the record would refuse."""
    assert set(provider_mod._DIALECT_ARMS) == set(binding_mod.DIALECTS)


def test_a_chat_turn_speaks_the_chat_completions_grammar(tmp_path):
    port, opener = _port(tmp_path, _chat_completion("the answer"),
                         dialect=OPENAI_CHAT)
    assert port.dispatch(_Envelope()) == {"assistant_prose": "the answer",
                                          "proposals": []}
    request = opener.requests[0]
    assert request.get_method() == "POST"
    assert request.get_full_url() == ENDPOINT
    assert json.loads(request.data.decode("utf-8")) == {
        "model": "openprofiler-demo",
        "messages": [{"role": "user", "content": "assembled prompt"}]}
    assert request.get_header("Content-type") == "application/json"
    # the token travels in the header, exactly as it does for the prompt grammar
    assert request.get_header("Authorization") == f"Bearer {SENTINEL_TOKEN}"
    assert SENTINEL_TOKEN not in request.get_full_url()
    assert SENTINEL_TOKEN not in request.data.decode("utf-8")


def test_the_prompt_dialect_is_unchanged_byte_for_byte(tmp_path):
    """The first member's request is the bytes it always was: the arm table
    moved the code, and nothing it sends."""
    port, opener = _port(tmp_path, {"assistant_prose": "a"})
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    assert opener.requests[0].data == json.dumps(
        {"model": "openprofiler-demo", "prompt": "assembled prompt"}
    ).encode("utf-8")


@pytest.mark.parametrize("answer", [
    {},
    {"choices": []},
    {"choices": "not a list"},
    {"choices": ["not an object"]},
    {"choices": [{}]},
    {"choices": [{"message": "not an object"}]},
    {"choices": [{"message": {"role": "assistant"}}]},
    {"choices": [{"message": {"role": "assistant", "content": None}}]},
    {"choices": [{"message": {"role": "assistant", "content": 7}}]},
    {"assistant_prose": "the prompt grammar's answer, not this one's"},
], ids=["empty", "no-choice", "choices-not-a-list", "choice-not-an-object",
        "no-message", "message-not-an-object", "no-content", "null-content",
        "content-not-text", "the-other-grammar"])
def test_a_chat_answer_off_the_declared_path_is_malformed(tmp_path, answer):
    port, _opener = _port(tmp_path, answer, dialect=OPENAI_CHAT)
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_MALFORMED


def test_a_chat_shaped_answer_is_not_the_prompt_grammars_answer(tmp_path):
    """Each arm reads its own grammar and no other."""
    port, _opener = _port(tmp_path, _chat_completion())
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_MALFORMED


def test_only_the_first_choice_is_read(tmp_path):
    answer = _chat_completion("first")
    answer["choices"].append({"index": 1, "finish_reason": "stop",
                              "message": {"role": "assistant",
                                          "content": "second"}})
    port, _opener = _port(tmp_path, answer, dialect=OPENAI_CHAT)
    assert port.dispatch(_Envelope())["assistant_prose"] == "first"


def test_the_expiry_ruling_holds_for_the_chat_grammar(tmp_path):
    """The 2026-08-26 ruling is the port's, not a dialect's: a mid-turn expiry
    re-mints and retries once, visibly, in either grammar."""
    printed: list[str] = []
    port, opener = _port(tmp_path, _expired_error(),
                         _chat_completion("the retried answer"),
                         notice=printed.append, dialect=OPENAI_CHAT)
    assert port.dispatch(_Envelope())["assistant_prose"] == "the retried answer"
    assert len(opener.requests) == 2, "exactly one paid retry"
    assert [event.reason for event in port.ledger] == [
        provider_mod.REASON_FIRST_MINT,
        provider_mod.REASON_EXPIRY_REMINT,
        provider_mod.REASON_PAID_RETRY,
    ]
    assert printed
    assert "re-minted once and retried" in printed[0]


def test_the_answer_bound_holds_for_the_chat_grammar(tmp_path):
    bound = provider_mod.MAX_PROVIDER_ANSWER_BYTES
    oversize = json.dumps(_chat_completion("x" * bound)).encode("utf-8")
    port, _opener = _port(tmp_path, oversize, dialect=OPENAI_CHAT)
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_MALFORMED


def test_a_chat_provider_refusal_lands_on_the_fixed_sentence(tmp_path):
    port, _opener = _port(
        tmp_path,
        urllib.error.HTTPError(ENDPOINT, 400, "Bad Request", {},
                               io.BytesIO(b'{"error":{"message":"leaky"}}')),
        dialect=OPENAI_CHAT)
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_REFUSED
    assert "leaky" not in str(caught.value)


@contextlib.contextmanager
def _stand_in_provider(handler_class):
    """A stand-in provider on loopback for the length of one test. It yields
    the server's base URL, and it is shut down and joined however the test
    ends."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, prt = server.server_address[:2]
        yield f"http://{host}:{prt}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _answer_json(handler, document) -> None:
    """Answer one stand-in request with `document` as a JSON body."""
    payload = json.dumps(document).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class _ChatCompletionsHandler(http.server.BaseHTTPRequestHandler):
    """A stand-in OpenAI-compatible server on loopback. It records each
    request and answers in the chat-completions grammar."""

    seen: dict = {}

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's own spelling
        length = int(self.headers.get("Content-Length", "0"))
        _ChatCompletionsHandler.seen = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": json.loads(self.rfile.read(length).decode("utf-8")),
        }
        _answer_json(self, _chat_completion("answered in the chat grammar"))

    def log_message(self, *_args):
        return


def test_a_chat_turn_reaches_a_stand_in_chat_completions_server(tmp_path):
    """The real `urllib` path, in the chat grammar: a stand-in server on
    loopback receives the request at the binding's declared endpoint, in that
    grammar, with the token in the authorization header and nowhere else."""
    with _stand_in_provider(_ChatCompletionsHandler) as base:
        binding = _broker_binding(_write_broker(tmp_path),
                                  endpoint=f"{base}/v1/chat/completions",
                                  dialect=OPENAI_CHAT)
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            notice=lambda _text: None, trust=_trusted(binding))
        assert port.dispatch(_Envelope()) == {
            "assistant_prose": "answered in the chat grammar",
            "proposals": []}

    seen = _ChatCompletionsHandler.seen
    assert seen["path"] == "/v1/chat/completions"
    assert seen["authorization"] == f"Bearer {SENTINEL_TOKEN}"
    assert seen["content_type"] == "application/json"
    assert seen["body"] == {
        "model": "openprofiler-demo",
        "messages": [{"role": "user", "content": "assembled prompt"}]}
    assert SENTINEL_TOKEN not in json.dumps(seen["body"])


def test_the_cli_declares_a_chat_binding(tmp_path, capsys):
    """The operator door offers the dialect, because its choices are read from
    the record's vocabulary rather than respelled."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    args = cli_mod.build_parser().parse_args([
        "model-binding", "add", "--repo-root", str(checkout),
        "--id", "local-chat", "--label", "Local chat", "--provider", "local",
        "--credential-ref", FAKE_REFERENCE, "--auth-kind", "api_key",
        "--credential-approver", "brett@opensoft.one",
        "--endpoint", "http://127.0.0.1:9/v1/chat/completions",
        "--dialect", OPENAI_CHAT, "--", "openprofiler-broker"])
    assert args.func(args) == 0
    capsys.readouterr()
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))
    assert store.get("local-chat").dialect == OPENAI_CHAT


# 16.2, the model name the provider receives (T079). The record gains `model`,
# sent as the request's model and set by `model-binding add|edit --model`. The
# field list grows from nine to ten, and still no field can hold a secret. A
# binding that declares no model sends the catalog handle, its `id`, exactly as
# every request did before the field existed.

DECLARED_MODEL = "stand-in-model-7b"


def test_f16_1_the_record_names_a_model():
    """F16.1's field assertion, as #1144 writes it:
    `assert "model" in b.BINDING_FIELDS`. Ten fields, in their declared order,
    with `model` beside the route it belongs to."""
    assert "model" in binding_mod.BINDING_FIELDS, (
        f"the record names no model: {binding_mod.BINDING_FIELDS}")
    assert binding_mod.BINDING_FIELDS == (
        "id", "label", "provider", "credential_ref", "auth_kind",
        "approved_by", "endpoint", "dialect", "model", "broker_argv")
    assert binding_mod.OPTIONAL_BINDING_FIELDS == ("model",)


def test_the_model_is_keyword_only_and_undeclared_by_default():
    """Every construction written before the field existed builds the
    binding it built, which declares no model."""
    import inspect
    parameter = inspect.signature(
        binding_mod.ModelProviderBinding).parameters["model"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
    assert _binding().model is None
    assert _binding(model=DECLARED_MODEL).model == DECLARED_MODEL


@pytest.mark.parametrize("bad", ["", "   ", 7, ["a-model"]])
def test_a_declared_model_is_non_blank_text(bad):
    with pytest.raises(binding_mod.BindingRefused):
        _binding(model=bad)


@pytest.mark.parametrize("dialect,answer,grammar_key", [
    (binding_mod.DIALECT_XFACTORY_PROMPT_V1, {"assistant_prose": "a"}, "prompt"),
    (OPENAI_CHAT, _chat_completion("a"), "messages"),
])
def test_the_declared_model_is_what_the_provider_receives(tmp_path, dialect,
                                                         answer, grammar_key):
    port, opener = _port(tmp_path, answer, dialect=dialect,
                         model=DECLARED_MODEL)
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    body = json.loads(opener.requests[0].data.decode("utf-8"))
    assert body["model"] == DECLARED_MODEL
    assert set(body) == {"model", grammar_key}


@pytest.mark.parametrize("dialect,answer", [
    (binding_mod.DIALECT_XFACTORY_PROMPT_V1, {"assistant_prose": "a"}),
    (OPENAI_CHAT, _chat_completion("a")),
])
def test_a_binding_with_no_model_still_sends_the_catalog_handle(tmp_path,
                                                                dialect,
                                                                answer):
    """What every request sent before #1144 box 16.2, byte for byte."""
    port, opener = _port(tmp_path, answer, dialect=dialect)
    port.dispatch(_Envelope())
    assert json.loads(opener.requests[0].data.decode("utf-8"))["model"] == \
        "openprofiler-demo"


def test_the_catalog_handle_stays_the_bindings_id(tmp_path):
    """The model is what the PROVIDER receives. The menu's handle is still the
    binding's id, so a chosen entry still resolves back to its binding."""
    binding = _binding(model=DECLARED_MODEL)
    entries = install_mod.brokered_catalog(binding).entries
    assert [entry.model_id for entry in entries] == [binding.id]


def test_a_declared_model_survives_the_expiry_retry(tmp_path):
    port, opener = _port(tmp_path, _expired_error(), _chat_completion("b"),
                         dialect=OPENAI_CHAT, model=DECLARED_MODEL)
    assert port.dispatch(_Envelope())["assistant_prose"] == "b"
    assert [json.loads(request.data.decode("utf-8"))["model"]
            for request in opener.requests] == [DECLARED_MODEL] * 2


def test_the_model_is_not_an_argv_placeholder():
    """A broker's invocation is about custody, never about the model a turn
    asks for, so the closed placeholder vocabulary does not grow."""
    assert "model" not in binding_mod.ARGV_PLACEHOLDERS
    with pytest.raises(binding_mod.BindingRefused):
        _binding(model=DECLARED_MODEL,
                 broker_argv=("openprofiler-broker", "--for", "{model}"))


def test_a_stored_record_carries_its_model_and_round_trips(tmp_path):
    store = _store(tmp_path)
    store.add(_binding(model=DECLARED_MODEL))
    store.add(_binding(id="undeclared", label="No model"))
    import yaml
    document = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    first, second = document["bindings"]
    assert list(first) == ["kind", *binding_mod.BINDING_FIELDS]
    assert first["model"] == DECLARED_MODEL
    assert second["model"] is None, "an undeclared model is written as null"
    assert store.get("openprofiler-demo").model == DECLARED_MODEL
    assert store.get("undeclared").model is None
    assert store.read_back()["bindings"][0]["model"] == DECLARED_MODEL


def test_a_record_declared_before_the_field_existed_still_reads(tmp_path):
    """A nine-field record, as every stored document held until #1144 box
    16.2, reads as a binding that declares no model."""
    record = _binding().as_record()
    del record["model"]
    assert set(record) == {"kind", *binding_mod.BINDING_FIELDS} - {"model"}
    path = tmp_path / "bindings.yaml"
    path.write_text(json.dumps({"schema_version": 1,
                                "kind": binding_mod.BINDINGS_KIND,
                                "bindings": [record]}), encoding="utf-8")
    (binding,) = binding_mod.BindingStore(path).list()
    assert binding.model is None
    assert binding == _binding()


def test_a_record_missing_a_required_field_still_refuses():
    """`model` is the one field a record may leave out, and only that one."""
    for field in binding_mod.BINDING_FIELDS:
        if field in binding_mod.OPTIONAL_BINDING_FIELDS:
            continue
        record = _binding().as_record()
        del record[field]
        with pytest.raises(binding_mod.BindingRefused) as caught:
            binding_mod.ModelProviderBinding.from_record(record)
        assert field in str(caught.value)


def test_the_cli_sets_the_model_on_add_and_edit(tmp_path, capsys):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    parser = cli_mod.build_parser()

    def run(*argv) -> int:
        args = parser.parse_args(list(argv))
        return args.func(args)

    root = ["--repo-root", str(checkout)]
    declaration = ["--id", "local-chat", "--label", "Local chat",
                   "--provider", "local", "--credential-ref", FAKE_REFERENCE,
                   "--auth-kind", "api_key",
                   "--credential-approver", "brett@opensoft.one",
                   "--endpoint", "http://127.0.0.1:9/v1/chat/completions",
                   "--dialect", OPENAI_CHAT]
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))

    assert run("model-binding", "add", *root, *declaration,
               "--model", DECLARED_MODEL, "--", "openprofiler-broker") == 0
    capsys.readouterr()
    assert store.get("local-chat").model == DECLARED_MODEL
    assert run("model-binding", "list", *root) == 0
    # `list` prints each value in its JSON spelling (T100: escaped)
    assert f"model            {json.dumps(DECLARED_MODEL)}" in \
        capsys.readouterr().out

    assert run("model-binding", "edit", *root, *declaration,
               "--model", "another-model", "--", "openprofiler-broker") == 0
    capsys.readouterr()
    assert store.get("local-chat").model == "another-model"

    # `edit` replaces the whole binding, so an edit without `--model` declares
    # none, and the list says what the request then names
    assert run("model-binding", "edit", *root, *declaration,
               "--", "openprofiler-broker") == 0
    capsys.readouterr()
    assert store.get("local-chat").model is None
    assert run("model-binding", "list", *root) == 0
    from opendox import cli_model_binding as cmb
    assert cmb.NO_MODEL_DECLARED in capsys.readouterr().out

    # a blank model refuses THROUGH THE VERB, not only through the record
    assert run("model-binding", "edit", *root, *declaration,
               "--model", " ", "--", "openprofiler-broker") == 1
    capsys.readouterr()
    assert store.get("local-chat").model is None


def test_a_stand_in_chat_server_receives_the_declared_model(tmp_path):
    with _stand_in_provider(_ChatCompletionsHandler) as base:
        binding = _broker_binding(
            _write_broker(tmp_path), endpoint=f"{base}/v1/chat/completions",
            dialect=OPENAI_CHAT, model=DECLARED_MODEL)
        provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            notice=lambda _text: None, trust=_trusted(binding)).dispatch(_Envelope())
    assert _ChatCompletionsHandler.seen["body"] == {
        "model": DECLARED_MODEL,
        "messages": [{"role": "user", "content": "assembled prompt"}]}


# 16.3, the credential stays a reference (T080).
#
#   * A key in the endpoint URL or in an extra field is refused when the
#     binding is declared. The URL check is the product's own detector,
#     `runtime/local_git_adapter.carries_a_credential`.
#   * The built-in resolver takes `env:NAME` and OS-keyring references, at call
#     time and inside `doxbench_provider` only (RULED R1Q17 (b)). Such a record
#     needs no broker, and one given beside it is refused. That refusal is the
#     plan's fail-closed reading (analyze round 2, V2-21), which no answer
#     rules. The tests below hold both halves.
#   * An endpoint that takes no credential declares the auth kind `none`,
#     under which `broker_argv` and `credential_ref` are forbidden (RULED
#     R1Q18 (a)). It joins after the two kinds that exist.
#
# Every key here is an obvious fake.

KEY_SENTINEL = "sk-stand-in-7c1e5a90d3b24f68-NOT-A-KEY"
ENV_NAME = "STAND_IN_PROVIDER_KEY"
KEYRING_SERVICE = "https://api.example.invalid"
KEYRING_USER = "brett"


def _f16_1_record():
    """F16.1's clean control record, built as #1144's falsifier builds it."""
    rec = {f: "stand-in" for f in binding_mod.BINDING_FIELDS}
    rec.update(auth_kind=binding_mod.AUTH_KINDS[0], dialect="openai-chat-v1",
               endpoint="http://127.0.0.1:9/v1/chat/completions")
    if "broker_argv" in rec:
        rec["broker_argv"] = ["stand-in-broker"]
    return rec


def test_f16_1_a_raw_key_is_refused_in_a_field_and_in_the_url():
    """F16.1's refusal block, as #1144 writes it: the clean control record is
    accepted, and each of its three raw keys is refused."""
    rec = _f16_1_record()
    binding_mod.ModelProviderBinding.from_record(rec)   # the control
    for bad in (dict(rec, endpoint="https://user:sk-stand-in@api.example.invalid/v1"),
                dict(rec, endpoint="https://api.example.invalid/v1?api_key=sk-stand-in"),
                dict(rec, api_key="sk-stand-in")):
        with pytest.raises(binding_mod.BindingRefused):
            binding_mod.ModelProviderBinding.from_record(bad)


def test_f16_1_the_first_auth_kind_still_takes_a_credential():
    """`none` joined AFTER the two kinds that exist (R1Q18 (a)), so the
    `AUTH_KINDS[0]` F16.1 builds its control from is unchanged."""
    assert binding_mod.AUTH_KINDS[0] == binding_mod.AUTH_KIND_API_KEY
    assert binding_mod.AUTH_KINDS[-1] == binding_mod.AUTH_KIND_NONE == "none"


def test_the_console_flow_offers_every_kind_a_broker_enrols():
    """The console's intake flow hands a credential to a broker, so it offers
    every member of `AUTH_KINDS` but `none`, in the vocabulary's order. A
    `none` binding holds no credential and is declared at the operator door."""
    offered = [entry["kind"] for entry in intake_mod.auth_kind_disclosure()]
    assert offered == [kind for kind in binding_mod.AUTH_KINDS
                       if kind != binding_mod.AUTH_KIND_NONE]


@pytest.mark.parametrize("endpoint", [
    f"https://user:{KEY_SENTINEL}@api.example.invalid/v1",
    f"https://{KEY_SENTINEL}@api.example.invalid/v1",
    f"https://api.example.invalid/v1?api_key={KEY_SENTINEL}",
    f"https://api.example.invalid/v1?key={KEY_SENTINEL}",
    f"https://api.example.invalid/v1?token={KEY_SENTINEL}",
    f"https://api.example.invalid/v1?%61pi_key={KEY_SENTINEL}",
    f"https://api.example.invalid/v1#token={KEY_SENTINEL}",
    f"ftp://user:{KEY_SENTINEL}@api.example.invalid/v1",
], ids=["userinfo", "bare-userinfo", "query-api-key", "query-key",
        "query-token", "percent-encoded-name", "fragment", "keyed-bad-scheme"])
def test_a_key_in_the_endpoint_is_refused_and_never_repeated(endpoint):
    """The refusal is FIXED, so the URL it refused is repeated nowhere. The
    detector runs before the scheme check, which would have echoed it."""
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(endpoint=endpoint)
    assert str(caught.value) == binding_mod.ENDPOINT_CARRIES_A_CREDENTIAL
    assert KEY_SENTINEL not in str(caught.value)


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:9/v1/chat/completions",
    "http://localhost:11434/v1/chat/completions",
    "https://api.example.invalid/v1/chat/completions",
    "https://api.example.invalid/v1?model=stand-in&stream=false",
])
def test_a_clean_endpoint_is_accepted(endpoint):
    assert _binding(endpoint=endpoint, dialect=OPENAI_CHAT).endpoint == endpoint


def _endpoint_of_length(length: int, head: str) -> str:
    endpoint = head + "a" * (length - len(head))
    assert len(endpoint) == length
    return endpoint


def test_an_endpoint_past_the_url_bound_is_refused_before_the_detector(
        monkeypatch):
    """Copilot's overview of openDox-code#63. The detector is quadratic in a
    parameter name's length, so the endpoint's length is checked first,
    against the product's own bound, and the detector is not asked. The
    refusal repeats nothing of the endpoint, and so nothing of a key in it."""
    bound = runtime_config.MAX_REMOTE_URL_CHARS
    endpoint = _endpoint_of_length(
        bound + 1,
        f"https://api.example.invalid/v1?api_key={KEY_SENTINEL}&pad=")

    def _not_asked(_text):
        raise AssertionError("the detector was asked about an endpoint past "
                             "the bound")

    monkeypatch.setattr(git_adapter_mod, "carries_a_credential", _not_asked)
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(endpoint=endpoint)
    message = str(caught.value)
    assert message == binding_mod.ENDPOINT_TOO_LONG.format(bound=bound)
    assert KEY_SENTINEL not in message
    assert "api.example.invalid" not in message


def test_an_endpoint_at_the_url_bound_is_declared():
    bound = runtime_config.MAX_REMOTE_URL_CHARS
    endpoint = _endpoint_of_length(
        bound, "https://api.example.invalid/v1/chat/completions?pad=")
    binding = _binding(endpoint=endpoint, dialect=OPENAI_CHAT)
    assert binding.endpoint == endpoint


def test_the_url_bound_is_the_products_own_read_when_it_is_asked(
        monkeypatch):
    """The number is `runtime/config`'s, read at declaration, so the record
    and the repository act cannot come to hold different bounds."""
    monkeypatch.setattr(runtime_config, "MAX_REMOTE_URL_CHARS", 40)
    head = "https://api.example.invalid/"
    at_the_bound = _endpoint_of_length(40, head)
    past_the_bound = _endpoint_of_length(41, head)
    assert _binding(endpoint=at_the_bound).endpoint == at_the_bound
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(endpoint=past_the_bound)
    assert str(caught.value) == binding_mod.ENDPOINT_TOO_LONG.format(bound=40)


def test_a_key_in_an_extra_field_is_refused_as_it_always_was():
    for field in ("api_key", "secret", "token", "password", "key"):
        record = dict(_binding().as_record(), **{field: KEY_SENTINEL})
        with pytest.raises(binding_mod.BindingRefused) as caught:
            binding_mod.ModelProviderBinding.from_record(record)
        assert KEY_SENTINEL not in str(caught.value)


def test_a_stored_document_whose_endpoint_carries_a_key_does_not_read(
        tmp_path):
    """A record written before 16.3 with a key in its URL no longer reads,
    and the entry point's fallback still resolves the harness declaration.
    The key is not in the refusal it prints."""
    record = _binding().as_record()
    record["endpoint"] = f"https://user:{KEY_SENTINEL}@api.example.invalid/v1"
    path = tmp_path / "bindings.yaml"
    path.write_text(json.dumps({"schema_version": 1,
                                "kind": binding_mod.BINDINGS_KIND,
                                "bindings": [record]}), encoding="utf-8")
    store = binding_mod.BindingStore(path)
    with pytest.raises(binding_mod.BindingRefused) as caught:
        store.list()
    assert KEY_SENTINEL not in str(caught.value)


# --- a raw key's shape (the adversarial review of openDox-code#63) -------
#
# The adversarial review at `4948e6dd` found three ways a key still reached
# the record or a refusal. M2: a key given as a broker's reference was taken
# as one, stored, printed by `list`, and put in the broker's argv at each
# mint. M3: the scheme refusal repeated the endpoint, key and all. M5: a key
# in the endpoint's path or fragment passed the detector, which reads a URL's
# userinfo and its parameters' names. Every value below is an obvious fake,
# built from fragments, so no line of this file holds a key's format whole.

_STAND_IN_BASE62 = "StandIn0NotAKey0" * 2   # 32 characters, all three classes
_STAND_IN_HEX = "0123456789abcdef" * 2      # 32 characters, two classes

#: Each holds a raw key's shape by one rule of `has_a_raw_key_shape` alone,
#: so a rule that is dropped or narrowed is a case that fails.
RAW_KEY_SHAPES = {
    "base62-run-of-32": _STAND_IN_BASE62,
    "hex-run-of-40": _STAND_IN_HEX + "01234567",
    "prefix-and-hex": "sk" + "-" + _STAND_IN_HEX,
    "prefix-and-a-tail-of-16": "sk" + "-" + _STAND_IN_HEX[:16],
    "prefix-and-letters": "hf" + "_" + "StandInNotAKeyStandIn",
    "prefix-glued-to-a-word": "bot" + "sk" + "-" + "Stand-In-0000-NOT-A-KEY",
    "google-api-key": "AIza" + "-stand-in-NOT-a-KEY-0000-0000-00000",
    "aws-access-key-id": "AKIA" + "STANDIN0NOTAKEY0",
    "json-web-token": "eyJ" + "hbGciOiJub25lIn0" + "." + "e30" + ".",
}

#: The shapes references and endpoints are known to take, and each rule's
#: edge. None of them is refused.
NOT_RAW_KEY_SHAPES = {
    "opendox-reference": FAKE_REFERENCE,
    "zeroed-reference": "opref-" + "0" * 24,
    "console-placeholder": "pending-broker-intake",
    "uuid": "123e4567-e89b-12d3-a456-426614174000",
    "model-name-under-32": "GPT4oMiniProduction2024",
    "hex-run-of-32": _STAND_IN_HEX,
    "hex-run-of-39": (_STAND_IN_HEX + "01234567")[:39],
    "base62-run-of-31": _STAND_IN_BASE62[:31],
    "a-word-ending-in-a-prefix": "benchmark-runner-" + _STAND_IN_HEX[:16],
    "prefix-and-a-tail-of-15": "sk" + "-" + _STAND_IN_HEX[:15],
    "secret-manager-reference": "op://dev/5vtmcbtqbkxhvdl3ezm2l3lvsa/password",
}

#: A key as a provider issues one: a prefix, and a base62 body.
_STAND_IN_PROVIDER_KEY = "sk" + "-proj-" + _STAND_IN_BASE62


@pytest.mark.parametrize("shape", sorted(RAW_KEY_SHAPES))
def test_a_raw_keys_shape_is_read_by_each_rule(shape):
    assert binding_mod.has_a_raw_key_shape(RAW_KEY_SHAPES[shape]) is True
    assert binding_mod.carries_a_raw_key(RAW_KEY_SHAPES[shape]) is True


@pytest.mark.parametrize("shape", sorted(NOT_RAW_KEY_SHAPES))
def test_the_shapes_references_take_are_not_a_raw_keys(shape):
    """The other side, at each rule's edge: a run one character short, a
    tail one short, a prefix that only ends a word, and the ids gateways and
    secret managers use."""
    assert binding_mod.has_a_raw_key_shape(NOT_RAW_KEY_SHAPES[shape]) is False
    assert binding_mod.carries_a_raw_key(NOT_RAW_KEY_SHAPES[shape]) is False


def test_only_text_has_a_raw_keys_shape():
    for value in (None, 0, _STAND_IN_BASE62.encode("ascii"),
                  [_STAND_IN_BASE62]):
        assert binding_mod.has_a_raw_key_shape(value) is False
        assert binding_mod.carries_a_raw_key(value) is False


@pytest.mark.parametrize("shape", sorted(RAW_KEY_SHAPES))
def test_a_reference_with_a_raw_keys_shape_is_refused_and_never_repeated(
        shape):
    """M2. A reference is never a raw key (#1144 box 16.3), so a value with
    a raw key's shape is refused as a broker's reference and inside each
    built-in form, and the refusal is a fixed sentence."""
    key = RAW_KEY_SHAPES[shape]
    for declare in (lambda: _binding(credential_ref=key),
                    lambda: _built_in_binding(f"env:{key}"),
                    lambda: _built_in_binding(
                        f"keyring:{KEYRING_SERVICE}/{key}")):
        with pytest.raises(binding_mod.BindingRefused) as caught:
            declare()
        assert str(caught.value) == binding_mod.CREDENTIAL_REF_IS_A_RAW_KEY
        assert key not in str(caught.value)


@pytest.mark.parametrize("shape", sorted(
    name for name, value in NOT_RAW_KEY_SHAPES.items()
    if not binding_mod.names_a_built_in_form(value)))
def test_a_reference_shaped_value_is_still_a_brokers_reference(shape):
    reference = NOT_RAW_KEY_SHAPES[shape]
    assert _binding(credential_ref=reference).credential_ref == reference


def test_a_reference_past_the_url_bound_is_refused_before_the_detector(
        monkeypatch):
    """Asking the detector of a reference (M2) asks a quadratic check of a
    value that had no bound, so a reference is held to the endpoint's bound
    first, and the detector is never asked of a longer one. The refusal
    repeats nothing of it."""
    bound = runtime_config.MAX_REMOTE_URL_CHARS
    at_the_bound = "opref-" + "0" * (bound - len("opref-"))
    past_the_bound = at_the_bound + "0"
    asked = []
    detector = git_adapter_mod.carries_a_credential

    def _recording(text):
        asked.append(text)
        return detector(text)

    monkeypatch.setattr(git_adapter_mod, "carries_a_credential", _recording)
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(credential_ref=past_the_bound)
    assert str(caught.value) == binding_mod.CREDENTIAL_REF_TOO_LONG.format(
        bound=bound)
    assert past_the_bound not in asked
    assert _binding(credential_ref=at_the_bound).credential_ref == (
        at_the_bound)
    assert at_the_bound in asked


def test_a_text_past_the_url_bound_carries_a_key_unasked(monkeypatch):
    """The predicate's own floor, for a caller that does not bound what it
    asks about, as `doxbench_provider` asks of a broker's reference."""
    def _not_asked(_text):
        raise AssertionError("the detector was asked about a text past the "
                             "bound")

    monkeypatch.setattr(git_adapter_mod, "carries_a_credential", _not_asked)
    past_the_bound = "x" * (runtime_config.MAX_REMOTE_URL_CHARS + 1)
    assert binding_mod.has_a_raw_key_shape(past_the_bound) is False
    assert binding_mod.carries_a_raw_key(past_the_bound) is True


def test_a_stored_document_whose_reference_is_a_raw_key_does_not_read(
        tmp_path):
    """M2 for a record written before the rule: it no longer reads, as one
    whose endpoint carries a key does not, and the refusal does not repeat
    the key."""
    record = _binding().as_record()
    record["credential_ref"] = _STAND_IN_PROVIDER_KEY
    path = tmp_path / "bindings.yaml"
    path.write_text(json.dumps({"schema_version": 1,
                                "kind": binding_mod.BINDINGS_KIND,
                                "bindings": [record]}), encoding="utf-8")
    store = binding_mod.BindingStore(path)
    with pytest.raises(binding_mod.BindingRefused) as caught:
        store.list()
    assert str(caught.value) == binding_mod.CREDENTIAL_REF_IS_A_RAW_KEY
    assert _STAND_IN_PROVIDER_KEY not in str(caught.value)


@pytest.mark.parametrize("endpoint", [
    "provider.invalid/turn",
    "file:///etc/passwd",
    "ftp://provider.invalid/turn",
    " https://provider.invalid/turn",
    # a short key in the wrong field, which no shape rule knows
    "sk" + "-" + "stand-in",
])
def test_the_scheme_refusal_is_a_fixed_sentence_that_repeats_nothing(
        endpoint):
    """M3. The scheme refusal repeated the endpoint, and a value in the
    wrong field can be a key, a key no shape rule knows among them. It is a
    fixed sentence now, composed from `ENDPOINT_SCHEMES` alone."""
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(endpoint=endpoint)
    message = str(caught.value)
    assert message == binding_mod.ENDPOINT_SCHEME_REFUSED
    assert endpoint.strip() not in message
    for scheme in binding_mod.ENDPOINT_SCHEMES:
        assert scheme in message


def test_the_scheme_refusal_is_route_neutral():
    """Copilot's review of openDox-code#63 at `abbb05d4`. Every resolver
    meets the scheme refusal, and only a credential is held to a private
    route (`ENDPOINT_NOT_PRIVATE`): the built-in resolver's key and, on this
    branch, a broker's minted token. So the refusal names the schemes and
    nothing about hosts, and a `none` binding may still name an `http://`
    endpoint on another host."""
    for declare in (_binding, _built_in_binding, _none_binding):
        with pytest.raises(binding_mod.BindingRefused) as caught:
            declare(endpoint="ftp://provider.invalid/turn")
        assert str(caught.value) == binding_mod.ENDPOINT_SCHEME_REFUSED
    for word in ("host", "loopback", "localhost", "127.0.0.1"):
        assert word not in binding_mod.ENDPOINT_SCHEME_REFUSED
    endpoint = "http://api.example.invalid/v1/chat/completions"
    assert _none_binding(endpoint=endpoint).endpoint == endpoint


#: Where a key was carried past the detector (M5), and the reviewer's M3
#: examples, where a key in the endpoint field reached the scheme refusal.
_KEYED_ENDPOINTS = {
    "a-path-segment": "https://api.example.invalid/v1/{key}/chat/completions",
    "glued-to-a-path-word": "https://api.example.invalid/bot{key}/v1",
    "the-fragment": "https://api.example.invalid/v1/chat/completions#{key}",
    "a-query-value": "https://api.example.invalid/v1/chat/completions?q={key}",
    "the-whole-field": "{key}",
    "behind-another-scheme": "ftp://{key}",
    "behind-a-space": " https://api.example.invalid/v1?q={key}",
}


@pytest.mark.parametrize("key", [_STAND_IN_BASE62, _STAND_IN_PROVIDER_KEY],
                         ids=["base62-run", "provider-key"])
@pytest.mark.parametrize("place", sorted(_KEYED_ENDPOINTS))
def test_a_key_anywhere_in_the_endpoint_is_refused_and_never_repeated(
        place, key):
    """M5, and M3's examples. The shape is checked with the detector, before
    the scheme, so a key in the path, glued to a path word, in the fragment,
    in a parameter with an innocent name, or in place of the URL, is refused
    with the fixed sentence."""
    endpoint = _KEYED_ENDPOINTS[place].format(key=key)
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(endpoint=endpoint)
    assert str(caught.value) == binding_mod.ENDPOINT_CARRIES_A_CREDENTIAL
    assert key not in str(caught.value)


@pytest.mark.parametrize("endpoint", [
    "https://stand-in.openai.azure.invalid/openai/deployments/GPT4oMini2024"
    "/chat/completions?api-version=2024-02-01",
    "https://gateway.ai.cloudflare.invalid/v1/" + _STAND_IN_HEX
    + "/stand-in/openai/chat/completions",
    "https://api.example.invalid/v1/projects/"
    "123e4567-e89b-12d3-a456-426614174000/chat/completions",
    "https://api.example.invalid/v1/chat/completions#section-2",
], ids=["deployment-name", "gateway-account-id", "uuid", "fragment"])
def test_the_ids_an_endpoint_carries_are_not_keys(endpoint):
    binding = _binding(endpoint=endpoint, dialect=OPENAI_CHAT)
    assert binding.endpoint == endpoint


# --- one resolver per record ---------------------------------------------


def _none_binding(**overrides):
    fields = dict(auth_kind=binding_mod.AUTH_KIND_NONE, credential_ref=None,
                  broker_argv=(), endpoint="http://127.0.0.1:9/v1/chat/completions",
                  dialect=OPENAI_CHAT, model=DECLARED_MODEL)
    fields.update(overrides)
    return _binding(**fields)


def _built_in_binding(credential_ref=f"env:{ENV_NAME}", **overrides):
    fields = dict(credential_ref=credential_ref, broker_argv=(),
                  dialect=OPENAI_CHAT, model=DECLARED_MODEL)
    fields.update(overrides)
    return _binding(**fields)


def test_the_none_kind_forbids_the_reference_and_the_broker():
    """R1Q18 (a), both halves: declared explicitly, and both fields
    forbidden under it. A blank reference is still a reference given."""
    binding = _none_binding()
    assert binding.credential_ref is None
    assert binding.broker_argv == ()
    assert binding.credential_source() == binding_mod.NO_CREDENTIAL
    for given in (FAKE_REFERENCE, f"env:{ENV_NAME}", ""):
        with pytest.raises(binding_mod.BindingRefused) as caught:
            _none_binding(credential_ref=given)
        assert "credential_ref is forbidden" in str(caught.value)
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _none_binding(broker_argv=("openprofiler-broker",))
    assert "broker_argv is forbidden" in str(caught.value)


@pytest.mark.parametrize("kind", [binding_mod.AUTH_KIND_API_KEY,
                                  binding_mod.AUTH_KIND_OAUTH])
def test_a_kind_that_takes_a_credential_must_name_its_reference(kind):
    """Never "no credential" by a field left out: the kind says it."""
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(auth_kind=kind, credential_ref=None)
    assert "'none'" in str(caught.value)


@pytest.mark.parametrize("reference", [
    f"env:{ENV_NAME}", f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"])
def test_a_built_in_reference_needs_no_broker_and_refuses_one_beside_it(
        reference):
    """BOTH HALVES, in one test, as T080's text asks. R1Q17 (b): a record
    whose reference the built-in resolver takes needs no broker. The plan's
    fail-closed reading: a broker given beside it is refused, so the record
    has one resolver."""
    binding = _built_in_binding(reference)
    assert binding.broker_argv == ()
    assert binding.credential_source() == \
        binding_mod.CREDENTIAL_FROM_BUILT_IN_RESOLVER
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _built_in_binding(reference, broker_argv=("openprofiler-broker",))
    assert "two resolvers" in str(caught.value)


def test_a_brokers_reference_still_needs_its_broker():
    binding = _binding()
    assert binding.credential_source() == binding_mod.CREDENTIAL_FROM_BROKER
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(broker_argv=())
    assert "must name the broker command" in str(caught.value)


def test_the_reference_forms_are_parsed_once():
    """One parser and ONE SHAPE for both forms, so no caller has to count
    what it was given before it reads it."""
    parts = binding_mod.built_in_reference_parts
    env = parts(f"env:{ENV_NAME}")
    assert env == binding_mod.BuiltInReference("env:", ENV_NAME, None)
    keyring = parts(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}")
    # the split is at the LAST `/`, so a service may carry one
    assert keyring == binding_mod.BuiltInReference(
        "keyring:", KEYRING_SERVICE, KEYRING_USER)
    assert (keyring.form, keyring.name, keyring.user) == (
        "keyring:", KEYRING_SERVICE, KEYRING_USER)
    assert len(env) == len(keyring)
    assert parts(FAKE_REFERENCE) is None
    assert binding_mod.BUILT_IN_REFERENCE_FORMS == ("env:", "keyring:")


@pytest.mark.parametrize("reference", [
    "env:", "env:1BAD", "env:A-B", "env: SPACED", "env:NAME\n",
    # `\w` is held to ASCII: a letter or a digit of another script is not a
    # portable variable name
    "env:NAM\u00c9", "env:KEY\u0661",
    f"env:{KEY_SENTINEL}",
    "keyring:", "keyring:service-only", "keyring:/user", "keyring:service/",
    "keyring: /user", f"keyring:{KEY_SENTINEL}",
])
def test_a_malformed_built_in_reference_is_refused_and_never_repeated(
        reference):
    """Refused at declaration, and the refusal names the FORM, not the value:
    a key pasted where its reference belongs is not printed back."""
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _built_in_binding(reference)
    message = str(caught.value)
    after_the_form = reference.split(":", 1)[1]
    if after_the_form.strip():
        assert after_the_form not in message
    assert KEY_SENTINEL not in message


def test_a_none_record_round_trips_and_may_leave_its_forbidden_fields_out():
    binding = _none_binding()
    record = binding.as_record()
    assert list(record) == ["kind", *binding_mod.BINDING_FIELDS]
    assert record["credential_ref"] is None
    assert record["broker_argv"] == []
    assert binding_mod.ModelProviderBinding.from_record(record) == binding
    del record["credential_ref"], record["broker_argv"]
    assert binding_mod.ModelProviderBinding.from_record(record) == binding
    for key, given in (("credential_ref", FAKE_REFERENCE),
                       ("broker_argv", ["openprofiler-broker"])):
        with pytest.raises(binding_mod.BindingRefused):
            binding_mod.ModelProviderBinding.from_record(
                dict(record, **{key: given}))


def test_a_built_in_record_may_leave_out_its_broker_argv():
    binding = _built_in_binding()
    record = binding.as_record()
    assert record["broker_argv"] == []
    for absent in ("deleted", None):
        candidate = dict(record)
        if absent == "deleted":
            del candidate["broker_argv"]
        else:
            candidate["broker_argv"] = None
        assert binding_mod.ModelProviderBinding.from_record(candidate) == \
            binding
    with pytest.raises(binding_mod.BindingRefused):
        binding_mod.ModelProviderBinding.from_record(
            dict(record, broker_argv=["openprofiler-broker"]))


def test_each_read_back_states_the_custody_that_is_true_of_it(tmp_path):
    store = _store(tmp_path)
    store.add(_binding())
    store.add(_built_in_binding(id="env-bound", label="Env"))
    store.add(_none_binding(id="local", label="Local"))
    custody = {record["id"]: record["credential_custody"]
               for record in store.read_back()["bindings"]}
    assert custody == {
        "openprofiler-demo": binding_mod.CUSTODY_NOTICE,
        "env-bound": binding_mod.BUILT_IN_CUSTODY_NOTICE,
        "local": binding_mod.NO_CREDENTIAL_NOTICE,
    }
    assert [store.get(i).removal_notice()
            for i in ("openprofiler-demo", "env-bound", "local")] == [
        binding_mod.REMOVAL_NOTICE, binding_mod.BUILT_IN_REMOVAL_NOTICE,
        binding_mod.NO_CREDENTIAL_REMOVAL_NOTICE]


def test_the_consoles_intake_shaped_binding_still_builds():
    """`serve_workbench`'s intake route builds its binding by keyword, with a
    placeholder reference and the declared broker. That construction is
    unchanged and still valid. A `none` binding cannot be enrolled that way,
    because the placeholder is a reference and `none` forbids one."""
    shaped = dict(id="enrolled", label="Enrolled", provider="p",
                  credential_ref="pending-broker-intake",
                  approved_by="brett", endpoint=ENDPOINT,
                  dialect=binding_mod.DIALECT_XFACTORY_PROMPT_V1,
                  broker_argv=("openprofiler-broker",))
    for kind in (binding_mod.AUTH_KIND_API_KEY, binding_mod.AUTH_KIND_OAUTH):
        assert binding_mod.ModelProviderBinding(auth_kind=kind, **shaped)
    with pytest.raises(binding_mod.BindingRefused):
        binding_mod.ModelProviderBinding(auth_kind=binding_mod.AUTH_KIND_NONE,
                                         **shaped)


def test_a_binding_no_broker_answers_has_no_broker_operation():
    for binding in (_none_binding(), _built_in_binding()):
        for operation in provider_mod.OPERATIONS:
            with pytest.raises(AssertionError):
                provider_mod.broker_operation_argv(binding, operation)
        stdin = io.StringIO("x")
        with pytest.raises(AssertionError):
            provider_mod.hand_off_credential(binding, stdin, trust=_trusted(binding))


# --- a built-in credential travels by a private route --------------------
# Brett Heap's ruling of 2026-09-28 on this PR's question, "Refuse unless
# loopback": a credential the built-in resolver reads is sent only over
# https://, or over http:// to 127.0.0.1, ::1 or localhost.

BUILT_IN_REFERENCES = (f"env:{ENV_NAME}",
                       f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}")
BACKSLASH = chr(92)

#: The routes a credential may take, and the routes it may not. One list of
#: each, shared by the built-in resolver's cases here and the broker path's
#: cases below, because the rule is one rule.
ON_A_PRIVATE_ROUTE = pytest.mark.parametrize("endpoint", [
    "https://api.example.invalid/v1/chat/completions",
    "http://127.0.0.1:8080/v1/chat/completions",
    "http://[::1]:8080/v1/chat/completions",
    "http://localhost:11434/v1/chat/completions",
    "http://LOCALHOST:11434/v1/chat/completions",
    "http://localhost",
], ids=["https", "ipv4-loopback", "ipv6-loopback", "localhost",
        "localhost-in-capitals", "no-path"])
NOT_ON_A_PRIVATE_ROUTE = pytest.mark.parametrize("endpoint", [
    "http://api.example.invalid/v1/chat/completions",
    "http://localhost.evil.com/v1/chat/completions",
    "http://127.0.0.1.evil.com/v1/chat/completions",
    "http://evil.com/localhost",
    "http://127.0.0.2:8080/v1",
    "http://[0:0:0:0:0:0:0:1]:8080/v1",
    "http://localhost./v1",
    "http://localhost%2eevil.com/v1",
    "http://0.0.0.0:8080/v1",
], ids=["another-host", "resembles-localhost", "resembles-127",
        "localhost-only-in-the-path", "a-loopback-address-not-named",
        "another-spelling-of-ipv6-loopback", "trailing-dot",
        "percent-encoded-dot", "unspecified-address"])


@ON_A_PRIVATE_ROUTE
def test_a_built_in_credential_is_declared_on_a_private_route(endpoint):
    for reference in BUILT_IN_REFERENCES:
        binding = _built_in_binding(reference, endpoint=endpoint)
        assert binding.endpoint == endpoint
        assert binding.credential_source() == (
            binding_mod.CREDENTIAL_FROM_BUILT_IN_RESOLVER)


@NOT_ON_A_PRIVATE_ROUTE
def test_a_built_in_credential_over_http_to_another_host_is_refused(endpoint):
    """Refused when it is declared, by the constructor and from a stored
    record alike, with the one fixed sentence."""
    for reference in BUILT_IN_REFERENCES:
        with pytest.raises(binding_mod.BindingRefused) as caught:
            _built_in_binding(reference, endpoint=endpoint)
        assert str(caught.value) == binding_mod.ENDPOINT_NOT_PRIVATE
        record = dict(_built_in_binding(reference).as_record(),
                      endpoint=endpoint)
        with pytest.raises(binding_mod.BindingRefused) as caught:
            binding_mod.ModelProviderBinding.from_record(record)
        assert str(caught.value) == binding_mod.ENDPOINT_NOT_PRIVATE


@pytest.mark.parametrize("endpoint,private", [
    ("HTTP://api.example.invalid/v1", False),
    ("Http://localhost.evil.com/v1", False),
    ("hTTp://127.0.0.1:8080/v1", True),
    ("HTTP://[::1]:8080/v1", True),
    ("http://LocalHost:11434/v1", True),
    ("HTTPS://api.example.invalid/v1", True),
    ("hTtPs://api.example.invalid/v1", True),
    (f"http://evil.example{BACKSLASH}@localhost/v1", False),
    (" http://localhost/v1", False),
    ("ftp://localhost/v1", False),
], ids=["capital-http-to-another-host", "mixed-case-http-to-a-lookalike",
        "mixed-case-http-to-127", "capital-http-to-ipv6-loopback",
        "mixed-case-localhost", "capital-https", "mixed-case-https",
        "backslash-before-localhost", "leading-space", "another-scheme"])
def test_a_private_route_is_read_case_blind_and_as_written(endpoint,
                                                           private):
    """A scheme and a host name are case-blind, so `HTTP://` to another host
    is not private and `HTTP://` to this one is. The route is read AS
    WRITTEN: a URL parser reads the backslash case's host as `localhost`, and
    the HTTP client reads it as the whole authority."""
    assert binding_mod.is_a_private_route(endpoint) is private


class _RecordingEnviron(dict):
    """An environment that records every name read from it."""

    def __init__(self, *args):
        super().__init__(*args)
        self.read: list[str] = []

    def get(self, name, default=None):
        self.read.append(name)
        return super().get(name, default)


@pytest.mark.parametrize("endpoint", [
    "http://api.example.invalid/v1", "HTTP://api.example.invalid/v1",
    "http://localhost.evil.com/v1",
    f"http://evil.example{BACKSLASH}@localhost/v1",
], ids=["another-host", "mixed-case-scheme", "resembles-localhost",
        "backslash"])
def test_the_resolver_reads_nothing_for_a_route_that_is_not_private(
        endpoint):
    """BEFORE RESOLUTION, in the resolver itself. The record refuses such a
    binding when it is declared, so this is a binding-shaped object that was
    never declared, and it still cannot make the resolver read a key."""
    for reference in BUILT_IN_REFERENCES:
        shaped = types.SimpleNamespace(id="undeclared",
                                       credential_ref=reference,
                                       endpoint=endpoint)
        environ = _RecordingEnviron({ENV_NAME: KEY_SENTINEL})
        backend = _FakeKeyring({(KEYRING_SERVICE, KEYRING_USER): KEY_SENTINEL})
        with pytest.raises(AssertionError) as caught:
            provider_mod.resolve_credential_reference(
                shaped, environ=environ, keyring_backend=backend)
        assert "nothing was read" in str(caught.value)
        assert environ.read == []
        assert backend.asked == []


def test_the_resolver_reads_a_key_for_a_private_route():
    """The control for the case above: the same reference on IPv6 loopback
    is read. A declared binding since #1144 16.3a, because the resolver now
    also reads only for a binding a trust verdict covers, and a verdict
    covers a declared binding alone."""
    shaped = _built_in_binding(endpoint="http://[::1]:8080/v1")
    environ = _RecordingEnviron({ENV_NAME: KEY_SENTINEL})
    assert provider_mod.resolve_credential_reference(
        shaped, environ=environ, trust=_trusted(shaped)) == KEY_SENTINEL
    assert environ.read == [ENV_NAME]


def test_a_broker_reference_in_a_built_in_form_is_malformed(tmp_path):
    """The built-in forms are reserved. A broker's reference in one would
    make the record read it as the built-in resolver's, beside the broker
    that holds the credential: two resolvers, refused where neither entry
    point expects a refusal (Copilot's overview of openDox-code#63 at
    `286655f3`). So the broker's answer is malformed, and it is refused as
    one, which both entry points already catch."""
    for index, reserved in enumerate(BUILT_IN_REFERENCES):
        script = tmp_path / f"reserved-broker-{index}.py"
        script.write_text(
            "import json,sys\nsys.stdin.read()\n"
            "print(json.dumps({'schema_version':1,"
            "'kind':'openprofiler_broker_intake','reference':"
            + repr(reserved) + ","
            "'binding':'b','provider':'p','auth_kind':'api_key','label':None,"
            "'created_at':'x','max_lifetime_seconds':300,'issued_by':'i',"
            "'approved_by':'a','audit_ref':'opaud-x'}))\n",
            encoding="utf-8")
        binding = _broker_binding(script)
        stdin = io.StringIO("x")
        with pytest.raises(provider_mod.BrokerRefused) as caught:
            provider_mod.hand_off_credential(binding, stdin, trust=_trusted(binding))
        assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED

@pytest.mark.parametrize("which", ["raw-key-shape", "past-the-url-bound"])
def test_a_broker_reference_the_record_would_refuse_is_malformed(tmp_path,
                                                                 which):
    """M2 at the hand-off: the reference a broker hands back is held to the
    record's rule before anything stores it, a key's shape and the length
    bound alike, so one that breaks it is a malformed answer, which both
    entry points already catch. Nothing of it is repeated."""
    reference = (_STAND_IN_PROVIDER_KEY if which == "raw-key-shape"
                 else "opref-" + "0" * runtime_config.MAX_REMOTE_URL_CHARS)
    script = tmp_path / "keyed-reference-broker.py"
    script.write_text(
        "import json,sys\nsys.stdin.read()\n"
        "print(json.dumps({'schema_version':1,"
        "'kind':'openprofiler_broker_intake','reference':"
        + repr(reference) + ","
        "'binding':'b','provider':'p','auth_kind':'api_key','label':None,"
        "'created_at':'x','max_lifetime_seconds':300,'issued_by':'i',"
        "'approved_by':'a','audit_ref':'opaud-x'}))\n",
        encoding="utf-8")
    binding = _broker_binding(script)
    source = io.StringIO("x")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.hand_off_credential(binding, source,
                                         trust=_trusted(binding))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED
    assert reference not in str(caught.value)


@NOT_ON_A_PRIVATE_ROUTE
def test_a_none_binding_keeps_a_route_that_is_not_private(endpoint):
    """The auth kind `none` presents no credential, so it is the one kind
    that keeps such a route. Before the broker path's hardening (the last
    section of this file), T080 pinned its scope here by declaring a broker
    binding on two such routes as well. That half is now refused."""
    assert _none_binding(endpoint=endpoint).credential_source() == (
        binding_mod.NO_CREDENTIAL)


# --- the built-in resolver, at call time ---------------------------------


class _FakeKeyring:
    """A stand-in for the `keyring` package: the one call the resolver makes,
    recorded."""

    def __init__(self, entries=None, error=None):
        self.entries = dict(entries or {})
        self.error = error
        self.asked: list[tuple[str, str]] = []

    def get_password(self, service, username):
        self.asked.append((service, username))
        if self.error is not None:
            raise self.error
        return self.entries.get((service, username))


def _refusing_runner(argv, **_kwargs):
    raise AssertionError(f"a binding no broker answers spawned {argv!r}")


def _unbrokered_port(binding, *outcomes, environ=None, keyring_backend=None,
                     notice=None):
    opener = _Opener(*outcomes)
    port = provider_mod.BrokeredProviderPort(
        binding, install_mod.brokered_catalog(binding),
        runner=_refusing_runner, opener=opener,
        notice=notice if notice is not None else (lambda _text: None),
        environ=environ, keyring_backend=keyring_backend, trust=_trusted(binding))
    return port, opener


def test_an_env_reference_is_read_at_call_time_and_presented_as_the_bearer():
    """R1Q17 (b): no broker, no mint, and the value read for each request, so
    a rotated value is the one the next request presents."""
    environ = {ENV_NAME: KEY_SENTINEL}
    port, opener = _unbrokered_port(_built_in_binding(),
                                    _chat_completion("a"),
                                    _chat_completion("b"), environ=environ)
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    environ[ENV_NAME] = "sk-rotated-stand-in-NOT-A-KEY"
    assert port.dispatch(_Envelope())["assistant_prose"] == "b"
    assert [request.get_header("Authorization")
            for request in opener.requests] == [
        f"Bearer {KEY_SENTINEL}", "Bearer sk-rotated-stand-in-NOT-A-KEY"]
    for request in opener.requests:
        assert KEY_SENTINEL not in request.get_full_url()
        assert KEY_SENTINEL not in request.data.decode("utf-8")
    assert port.ledger == [], "nothing was minted"


def test_production_reads_the_serving_process_environment(monkeypatch):
    monkeypatch.setenv(ENV_NAME, KEY_SENTINEL)
    port, opener = _unbrokered_port(_built_in_binding(),
                                    _chat_completion("a"))
    port.dispatch(_Envelope())
    assert opener.requests[0].get_header("Authorization") == \
        f"Bearer {KEY_SENTINEL}"


@pytest.mark.parametrize("environ", [
    {}, {ENV_NAME: ""}, {ENV_NAME: "   "}, {ENV_NAME: "sk-stand-in\nX-Other: 1"},
    {ENV_NAME: "sk-stand-in\x00"},
    # a bearer credential is printable ASCII with no whitespace (Copilot's
    # overview of openDox-code#63), so nothing else is presented
    {ENV_NAME: f"{KEY_SENTINEL}\u20ac"}, {ENV_NAME: f"{KEY_SENTINEL}\u00e9"},
    {ENV_NAME: "sk-stand-in NOT-A-KEY"}, {ENV_NAME: "sk-stand-in\tNOT-A-KEY"},
    {ENV_NAME: f"{KEY_SENTINEL} "}, {ENV_NAME: f"{KEY_SENTINEL}\x7f"}],
    ids=["unset", "empty", "blank", "line-break", "nul", "outside-latin-1",
         "latin-1-not-ascii", "embedded-space", "tab", "trailing-space",
         "delete"])
def test_an_unusable_env_value_refuses_before_any_request(environ):
    port, opener = _unbrokered_port(_built_in_binding(), _chat_completion(),
                                    environ=environ)
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_REFERENCE_UNRESOLVED
    assert opener.requests == [], "no provider was contacted"
    assert port.catalog().entries[0].available is False


def test_a_value_outside_latin_1_is_refused_before_any_header_is_built(
        monkeypatch):
    """Over a real socket, because the failure was `urllib`'s. Before the
    check, such a value failed while the header was encoded: the refusal read
    `DIAG_PROVIDER_UNREACHABLE`, and it chained a `UnicodeEncodeError` whose
    `object` held the whole header, credential included (measured). Now it is
    the resolver's own fixed refusal, nothing is chained, and no request is
    sent."""
    monkeypatch.setattr(_ChatCompletionsHandler, "seen", {})
    with _stand_in_provider(_ChatCompletionsHandler) as base:
        binding = _built_in_binding(endpoint=f"{base}/v1/chat/completions")
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            runner=_refusing_runner, notice=lambda _text: None,
            environ={ENV_NAME: f"{KEY_SENTINEL}\u20ac"}, trust=_trusted(binding))
        envelope = _Envelope()
        with pytest.raises(provider_mod.BrokerRefused) as caught:
            port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_REFERENCE_UNRESOLVED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _ChatCompletionsHandler.seen == {}, "no request reached the server"


def test_a_value_of_printable_ascii_is_presented_as_it_is():
    """The check refuses what a bearer credential cannot be and nothing more:
    every printable ASCII character but the space is presented unchanged."""
    value = "sk-" + "".join(chr(code) for code in range(0x21, 0x7F))
    port, opener = _unbrokered_port(_built_in_binding(),
                                    _chat_completion("a"),
                                    environ={ENV_NAME: value})
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    assert opener.requests[0].get_header("Authorization") == f"Bearer {value}"


def test_a_reference_that_resolves_again_makes_the_entry_available_again():
    environ: dict[str, str] = {}
    port, _opener = _unbrokered_port(_built_in_binding(),
                                     _chat_completion("a"), environ=environ)
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused):
        port.dispatch(envelope)
    assert port.catalog().entries[0].available is False
    environ[ENV_NAME] = KEY_SENTINEL
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    assert port.catalog().entries[0].available is True


def test_a_keyring_reference_reads_the_os_keyring_at_call_time():
    backend = _FakeKeyring({(KEYRING_SERVICE, KEYRING_USER): KEY_SENTINEL})
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion("a"), _chat_completion("b"), keyring_backend=backend)
    port.dispatch(_Envelope())
    port.dispatch(_Envelope())
    assert backend.asked == [(KEYRING_SERVICE, KEYRING_USER)] * 2, \
        "read for each request, and nothing cached"
    assert opener.requests[0].get_header("Authorization") == \
        f"Bearer {KEY_SENTINEL}"


@pytest.mark.parametrize("stored", [
    None, b"sk-stand-in-NOT-A-KEY", "", f"{KEY_SENTINEL}\u20ac"],
    ids=["absent", "not-text", "empty", "outside-latin-1"])
def test_an_absent_or_unusable_keyring_entry_refuses_unresolved(stored):
    entries = ({} if stored is None
               else {(KEYRING_SERVICE, KEYRING_USER): stored})
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion(), keyring_backend=_FakeKeyring(entries))
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_REFERENCE_UNRESOLVED
    assert opener.requests == []


def test_a_keyring_that_cannot_be_read_refuses_and_says_nothing_of_its_own():
    backend = _FakeKeyring(error=RuntimeError("backend detail that leaks"))
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion(), keyring_backend=backend)
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_KEYRING_UNAVAILABLE
    assert "leaks" not in str(caught.value)
    assert caught.value.__cause__ is None
    # no context either: the backend's own frames are not kept (Copilot's
    # overview of openDox-code#63 at `286655f3`)
    assert caught.value.__context__ is None
    assert opener.requests == []


def test_without_the_keyring_package_a_keyring_reference_refuses(monkeypatch):
    """`keyring` is not a dependency of this package. Without it, the
    production path refuses with the fixed sentence, not an import error."""
    monkeypatch.setitem(sys.modules, "keyring", None)
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion())
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_KEYRING_UNAVAILABLE
    assert opener.requests == []


def test_a_keyring_package_that_fails_as_it_is_imported_refuses_the_same_way(
        monkeypatch):
    """Copilot's review of openDox-code#63 at `82ec9a20`. An import runs the
    package's own code, and a backend can fail there as it can when it is
    read. Whatever it raises, the reference refuses with the fixed sentence,
    before any request, and the refusal carries none of what was raised."""
    importing = builtins.__import__

    def _failing_import(name, *args, **kwargs):
        if name == "keyring":
            raise RuntimeError(f"a backend failed at import: {KEY_SENTINEL}")
        return importing(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion())
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_KEYRING_UNAVAILABLE
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert opener.requests == []
    assert _locals_holding(caught.value, KEY_SENTINEL) == []


def test_the_production_keyring_path_imports_the_package_at_call_time(
        monkeypatch):
    backend = _FakeKeyring({(KEYRING_SERVICE, KEYRING_USER): KEY_SENTINEL})
    monkeypatch.setitem(sys.modules, "keyring", backend)
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion("a"))
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    assert backend.asked == [(KEYRING_SERVICE, KEYRING_USER)]


def test_a_none_binding_presents_no_credential_and_spawns_no_broker():
    port, opener = _unbrokered_port(_none_binding(), _chat_completion("a"))
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    request = opener.requests[0]
    assert not request.has_header("Authorization")
    assert json.loads(request.data.decode("utf-8"))["model"] == DECLARED_MODEL
    assert port.ledger == []


@pytest.mark.parametrize("which", ["built-in", "none"])
def test_a_401_without_a_broker_is_a_refusal_not_a_retry(which):
    """The 2026-08-26 retry ruling is about a MINTED token. Here there is
    nothing to re-mint, so a retry would buy a second paid call for the same
    refusal."""
    binding = _built_in_binding() if which == "built-in" else _none_binding()
    port, opener = _unbrokered_port(binding, _expired_error(),
                                    _chat_completion("never reached"),
                                    environ={ENV_NAME: KEY_SENTINEL})
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_REFUSED
    assert len(opener.requests) == 1, "no second paid call"
    assert port.ledger == []


def test_the_resolved_credential_reaches_no_response_log_repr_or_disk(
        tmp_path):
    printed: list[str] = []
    port, _opener = _unbrokered_port(_built_in_binding(),
                                     _chat_completion("the answer"),
                                     environ={ENV_NAME: KEY_SENTINEL},
                                     notice=printed.append)
    answer = port.dispatch(_Envelope())
    assert KEY_SENTINEL not in json.dumps(answer)
    assert KEY_SENTINEL not in repr(port)
    assert KEY_SENTINEL not in "".join(printed)
    assert KEY_SENTINEL not in repr(port.ledger)
    port_state = {name: getattr(port, name) for name in dir(port)
                  if name.startswith("_") and not name.startswith("__")
                  and name != "_environ"}
    assert KEY_SENTINEL not in repr(port_state), \
        "the port keeps no credential between turns"
    assert not [path for path in tmp_path.rglob("*") if path.is_file()
                and KEY_SENTINEL in path.read_text(encoding="utf-8",
                                                   errors="replace")]


def test_an_unresolved_reference_maps_onto_the_seams_fixed_model_failed():
    port, _opener = _unbrokered_port(_built_in_binding(), environ={})
    entry = port.catalog().entries[0]
    ticks = iter([0.0, 0.1])
    outcome = model_mod.dispatch_turn(port, _Envelope(), entry=entry,
                                      clock=lambda: next(ticks))
    assert isinstance(outcome, model_mod.TurnDispatchFailure)
    assert outcome.error == model_mod.DISPATCH_ERR_MODEL_FAILED
    assert KEY_SENTINEL not in json.dumps(str(outcome))


@pytest.mark.parametrize("which,expected", [
    ("built-in", f"Bearer {KEY_SENTINEL}"), ("none", None)])
def test_a_stand_in_server_sees_the_resolved_bearer_or_no_header(which,
                                                                 expected):
    with _stand_in_provider(_ChatCompletionsHandler) as base:
        endpoint = f"{base}/v1/chat/completions"
        binding = (_built_in_binding(endpoint=endpoint) if which == "built-in"
                   else _none_binding(endpoint=endpoint))
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            runner=_refusing_runner, notice=lambda _text: None,
            environ={ENV_NAME: KEY_SENTINEL}, trust=_trusted(binding))
        assert port.dispatch(_Envelope())["assistant_prose"] == \
            "answered in the chat grammar"
    assert _ChatCompletionsHandler.seen["authorization"] == expected
    assert _ChatCompletionsHandler.seen["body"]["model"] == DECLARED_MODEL


class _ElsewhereHandler(http.server.BaseHTTPRequestHandler):
    """A second stand-in, where a redirect or a proxy would lead. It records
    every request it is sent, of any method."""

    seen: list = []

    def _record(self):
        _ElsewhereHandler.seen.append(
            (self.command, self.headers.get("Authorization")))
        _answer_json(self, _chat_completion("answered from elsewhere"))

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's own spelling
        self._record()

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's own spelling
        self._record()

    def log_message(self, *_args):
        return


class _RedirectingHandler(http.server.BaseHTTPRequestHandler):
    """A stand-in provider that answers every request with a redirect."""

    code = 302
    location = ""

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's own spelling
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(_RedirectingHandler.code)
        self.send_header("Location", _RedirectingHandler.location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args):
        return


@contextlib.contextmanager
def _a_provider_that_redirects(monkeypatch, code):
    """A stand-in provider that answers every request with a `code` redirect
    to a second stand-in, `_ElsewhereHandler`, which records whatever it is
    sent. It yields the first one's base URL."""
    monkeypatch.setattr(_ElsewhereHandler, "seen", [])
    monkeypatch.setattr(_RedirectingHandler, "code", code)
    with _stand_in_provider(_ElsewhereHandler) as elsewhere, \
            _stand_in_provider(_RedirectingHandler) as base:
        monkeypatch.setattr(_RedirectingHandler, "location",
                            f"{elsewhere}/v1/chat/completions")
        yield base


@contextlib.contextmanager
def _an_environment_proxy(monkeypatch):
    """A stand-in proxy that `http_proxy` names, recording into
    `_ElsewhereHandler.seen`, for the length of one test.

    `urlopen`'s global opener is dropped first. `urlopen` builds it on first
    use and reads the proxy environment then, so a request made through
    `urlopen` here reads this environment, as it would in a process started
    with the variable set. Without that, a proxy case would pass or fail by
    whichever earlier test built the opener."""
    monkeypatch.setattr(_ElsewhereHandler, "seen", [])
    monkeypatch.setattr(urllib.request, "_opener", None)
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    with _stand_in_provider(_ElsewhereHandler) as proxy:
        for name in ("http_proxy", "HTTP_PROXY"):
            monkeypatch.setenv(name, proxy)
        yield proxy


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_a_built_in_credential_follows_no_redirect(monkeypatch, code):
    """Copilot's review of openDox-code#63 at `4abc6d4d`, over real sockets.
    `urllib`'s default opener answers a POST's 301, 302 or 303 by sending a
    GET to the `Location`, with the credential header still on it (measured).
    A request that carries a built-in credential declines the redirect, and
    the second server hears nothing at all."""
    with _a_provider_that_redirects(monkeypatch, code) as base:
        binding = _built_in_binding(endpoint=f"{base}/v1/chat/completions")
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            runner=_refusing_runner, notice=lambda _text: None,
            environ={ENV_NAME: KEY_SENTINEL}, trust=_trusted(binding))
        envelope = _Envelope()
        with pytest.raises(provider_mod.BrokerRefused) as caught:
            port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_REDIRECTED
    assert _ElsewhereHandler.seen == [], "the credential went nowhere else"


def test_a_built_in_credential_over_http_to_this_host_uses_no_proxy(
        monkeypatch):
    """Copilot's review of openDox-code#63 at `1b0fb3f4`, over real sockets.
    A plain-http route is private only because it stays on this host. With
    `http_proxy` set, urllib's default opener sends a request addressed to
    `127.0.0.1` to the proxy, credential header and all (measured). This
    request goes direct, and the stand-in proxy hears nothing."""
    monkeypatch.setattr(_ChatCompletionsHandler, "seen", {})
    with _an_environment_proxy(monkeypatch), \
            _stand_in_provider(_ChatCompletionsHandler) as base:
        binding = _built_in_binding(endpoint=f"{base}/v1/chat/completions")
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            runner=_refusing_runner, notice=lambda _text: None,
            environ={ENV_NAME: KEY_SENTINEL}, trust=_trusted(binding))
        answer = port.dispatch(_Envelope())
    assert answer["assistant_prose"] == "answered in the chat grammar"
    assert _ChatCompletionsHandler.seen["authorization"] == (
        f"Bearer {KEY_SENTINEL}")
    assert _ElsewhereHandler.seen == [], "the proxy heard nothing"


def _safe_repr(value) -> str:
    try:
        return repr(value)
    # A repr that fails discloses nothing, whatever it raised.
    except Exception:  # noqa: BLE001
        return ""


def _frames_kept_by(exception):
    """Every frame a refusal's tracebacks keep, through its causes and its
    contexts, suppressed or not, except this test file's own frames."""
    seen: set[int] = set()
    pending = [exception]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        traceback = current.__traceback__
        while traceback is not None:
            if traceback.tb_frame.f_code.co_filename != __file__:
                yield traceback.tb_frame
            traceback = traceback.tb_next
        pending.extend((current.__cause__, current.__context__))


def _locals_holding(exception, secret: str) -> list[str]:
    """The frame locals, by their repr, that disclose `secret`, which is what
    an error reporter that records locals would send on."""
    return sorted({f"{frame.f_code.co_name}.{name}"
                   for frame in _frames_kept_by(exception)
                   for name, value in list(frame.f_locals.items())
                   if secret in _safe_repr(value)})


@contextlib.contextmanager
def _a_closed_loopback_port():
    """A loopback port that nothing listens on. It is held for the test, so
    no other process can take it."""
    holder = socket.socket()
    try:
        holder.bind(("127.0.0.1", 0))
        yield holder.getsockname()[1]
    finally:
        holder.close()


def test_a_refused_connection_keeps_no_frame_that_holds_the_key(monkeypatch):
    """Copilot's review of openDox-code#63 at `d240fd50`, over the real
    transport. A cause chained from inside `urllib` keeps frames whose locals
    hold the request's headers, and so the key. The refusal chains nothing,
    and no frame it keeps holds the key."""
    monkeypatch.setenv(ENV_NAME, KEY_SENTINEL)
    with _a_closed_loopback_port() as closed:
        binding = _built_in_binding(
            endpoint=f"http://127.0.0.1:{closed}/v1/chat/completions")
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            runner=_refusing_runner, notice=lambda _text: None, trust=_trusted(binding))
        envelope = _Envelope()
        with pytest.raises(provider_mod.BrokerRefused) as caught:
            port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_UNREACHABLE
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _locals_holding(caught.value, KEY_SENTINEL) == []


class _UnreadableAnswerHandler(http.server.BaseHTTPRequestHandler):
    """A stand-in provider that reads one whole request and answers it with
    `answer`, bytes `http.client` cannot read as a response."""

    answer = b""

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler's own spelling
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.wfile.write(self.answer)
        self.close_connection = True

    def log_message(self, *_args):
        return


#: The answers of the adversarial review of openDox-code#63 (L4), each under
#: the `http.client.HTTPException` it raises, with the path it is asked at.
#: `InvalidURL` needs no answer: `http.client` raises it for a path it cannot
#: send, a path the record accepts, before anything is sent.
UNREADABLE_ANSWERS = {
    "BadStatusLine": (b"GARBAGE\r\n\r\n", "/v1/chat/completions"),
    "UnknownProtocol": (b"HTTP/2.0 200 OK\r\nContent-Length: 2\r\n\r\n{}",
                        "/v1/chat/completions"),
    "LineTooLong": (b"HTTP/1.1 200 OK\r\nX-Stand-In: " + b"a" * 70_000
                    + b"\r\n\r\n", "/v1/chat/completions"),
    "HTTPException": (b"HTTP/1.1 200 OK\r\n"
                      + b"".join(b"X-Stand-In-%d: y\r\n" % number
                                 for number in range(120)) + b"\r\n",
                      "/v1/chat/completions"),
    "IncompleteRead": (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
                       b"\r\n10\r\n{\"choices\":", "/v1/chat/completions"),
    "InvalidURL": (b"", "/v1/chat completions"),
}


def _read_by_urllib_alone(url: str) -> None:
    request = urllib.request.Request(url, data=b"{}", method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        response.read()


@pytest.mark.parametrize("resolver", ["built-in", "none", "broker"])
@pytest.mark.parametrize("raised", sorted(UNREADABLE_ANSWERS))
def test_an_answer_http_client_cannot_read_is_unreachable_and_keeps_no_key(
        tmp_path, raised, resolver):
    """The adversarial review of openDox-code#63 at `4948e6dd`, L4. A status
    line, a protocol, a header, a body or a path that `http.client` cannot
    read or send raises an `http.client.HTTPException`, which is no
    `OSError`. So it escaped `dispatch`, with the request's headers, and the
    key, in `do_open`'s frame. Each is the fixed unreachable refusal now,
    raised afresh where a built-in credential was presented.

    THE TRANSPORT IS SHARED, so a broker's turn lands on the same sentence
    (Copilot's review of openDox-code#63 at `44582f8f`), where it escaped
    before. That is the one change this PR makes to the broker path's
    failure. Raising it afresh there is openDox-code#64's, as the ruling
    leaves that path to it."""
    answer, path = UNREADABLE_ANSWERS[raised]
    handler = type(f"_{raised}Answer", (_UnreadableAnswerHandler,),
                   {"answer": answer})
    with _stand_in_provider(handler) as base:
        # the case is what it is named for: urllib alone raises exactly it
        with pytest.raises(http.client.HTTPException) as unread:
            _read_by_urllib_alone(base + path)
        assert type(unread.value) is getattr(http.client, raised)
        runner = _refusing_runner
        if resolver == "built-in":
            binding = _built_in_binding(endpoint=base + path)
        elif resolver == "none":
            binding = _none_binding(endpoint=base + path)
        else:
            binding = _broker_binding(_write_broker(tmp_path),
                                      endpoint=base + path)
            runner = provider_mod.subprocess_broker_runner
        port = provider_mod.BrokeredProviderPort(
            binding, install_mod.brokered_catalog(binding),
            runner=runner, notice=lambda _text: None,
            environ={ENV_NAME: KEY_SENTINEL}, trust=_trusted(binding))
        envelope = _Envelope()
        with pytest.raises(provider_mod.BrokerRefused) as caught:
            port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_UNREACHABLE
    if resolver == "built-in":
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert _locals_holding(caught.value, KEY_SENTINEL) == []


def test_an_unpresentable_value_leaves_no_frame_that_holds_it(monkeypatch):
    """A value refused as unpresentable can still be most of a key, such as
    a key with a line break after it. The frame that read it lets it go
    before the refusal is raised."""
    monkeypatch.setenv(ENV_NAME, KEY_SENTINEL + "\n")
    port, opener = _unbrokered_port(_built_in_binding(), _chat_completion())
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_REFERENCE_UNRESOLVED
    assert opener.requests == []
    assert _locals_holding(caught.value, KEY_SENTINEL) == []


def test_a_broker_refusal_keeps_no_frame_that_holds_the_token(tmp_path):
    """The minted token travels as the same wrapper, so the provider-call
    frame holds no raw token, as it held none when that frame took a
    `MintedToken`."""
    port, _opener = _port(tmp_path, OSError("unreachable"))
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_UNREACHABLE
    assert _locals_holding(caught.value, SENTINEL_TOKEN) == []


def test_the_resolver_lives_in_the_provider_module_alone():
    """R1Q17 (b): "inside `doxbench_provider.py` only". The record parses a
    reference's FORM and reads no environment and no keyring. No other module
    of the package reads the OS keyring."""
    package = REPO_ROOT / "src" / "opendox"
    binding_source = (package / "doxbench_binding.py").read_text(
        encoding="utf-8")
    for reach in ("os.environ", "getenv", "get_password", "import keyring",
                  "import os"):
        assert reach not in binding_source, reach
    holders = sorted(path.relative_to(package).as_posix()
                     for path in package.rglob("*.py")
                     if "get_password" in path.read_text(encoding="utf-8")
                     or "import keyring" in path.read_text(encoding="utf-8"))
    assert holders == [provider_mod.PROVIDER_CLIENT_MODULE], holders


# --- the operator door ----------------------------------------------------


def test_the_cli_declares_a_binding_for_each_resolver(tmp_path, capsys):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    parser = cli_mod.build_parser()

    def run(*argv) -> int:
        args = parser.parse_args(list(argv))
        return args.func(args)

    root = ["--repo-root", str(checkout)]
    route = ["--label", "L", "--provider", "local",
             "--credential-approver", "brett@opensoft.one",
             "--endpoint", "http://127.0.0.1:9/v1/chat/completions",
             "--dialect", OPENAI_CHAT, "--model", DECLARED_MODEL]
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))

    # an endpoint that takes no credential: no reference, and no broker
    assert run("model-binding", "add", *root, "--id", "local", *route,
               "--auth-kind", "none") == 0
    assert binding_mod.NO_CREDENTIAL_NOTICE in capsys.readouterr().out
    assert store.get("local").credential_source() == binding_mod.NO_CREDENTIAL

    # a reference the built-in resolver takes: no broker
    assert run("model-binding", "add", *root, "--id", "env-bound", *route,
               "--auth-kind", "api_key",
               "--credential-ref", f"env:{ENV_NAME}") == 0
    assert binding_mod.BUILT_IN_CUSTODY_NOTICE in capsys.readouterr().out

    # ...and one given a broker beside it is refused, through the verb
    assert run("model-binding", "add", *root, "--id", "two-resolvers", *route,
               "--auth-kind", "api_key", "--credential-ref", f"env:{ENV_NAME}",
               "--", "openprofiler-broker") == 1
    assert "two resolvers" in capsys.readouterr().err

    # a kind that takes a credential, with no reference, is refused
    assert run("model-binding", "add", *root, "--id", "no-ref", *route,
               "--auth-kind", "api_key") == 1
    assert "'none'" in capsys.readouterr().err

    # a key inside the URL is refused, and the refusal does not repeat it
    keyed = list(route)
    keyed[keyed.index("--endpoint") + 1] = (
        f"https://user:{KEY_SENTINEL}@api.example.invalid/v1")
    assert run("model-binding", "add", *root, "--id", "keyed", *keyed,
               "--auth-kind", "none") == 1
    captured = capsys.readouterr()
    assert binding_mod.ENDPOINT_CARRIES_A_CREDENTIAL in captured.err
    assert KEY_SENTINEL not in captured.err + captured.out
    assert store.get("keyed") is None, "nothing is stored"

    # a built-in credential over http:// to another host is refused (the
    # 2026-09-28 loopback ruling), and a `none` binding to it is declared
    cleartext = list(route)
    cleartext[cleartext.index("--endpoint") + 1] = (
        "http://api.example.invalid/v1/chat/completions")
    assert run("model-binding", "add", *root, "--id", "cleartext",
               *cleartext, "--auth-kind", "api_key",
               "--credential-ref", f"env:{ENV_NAME}") == 1
    assert binding_mod.ENDPOINT_NOT_PRIVATE in capsys.readouterr().err
    assert store.get("cleartext") is None, "nothing is stored"
    assert run("model-binding", "add", *root, "--id", "cleartext-none",
               *cleartext, "--auth-kind", "none") == 0
    capsys.readouterr()

    assert run("model-binding", "list", *root) == 0
    listed = capsys.readouterr().out
    from opendox import cli_model_binding as cmb
    assert f"credential ref   {cmb.NOT_DECLARED}" in listed
    assert f"broker argv      {cmb.NOT_DECLARED}" in listed
    assert f"credential ref   {json.dumps(f'env:{ENV_NAME}')}" in listed

    assert run("model-binding", "remove", *root, "--id", "env-bound") == 0
    assert binding_mod.BUILT_IN_REMOVAL_NOTICE in capsys.readouterr().out


def test_the_cli_refuses_a_raw_key_as_a_reference_and_repeats_nothing(
        tmp_path, capsys):
    """M2 at the operator door: `model-binding add --credential-ref <key>`
    stores nothing, so `list` has nothing of it to print, and neither stream
    repeats it."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    parser = cli_mod.build_parser()

    def run(*argv) -> int:
        args = parser.parse_args(list(argv))
        return args.func(args)

    root = ["--repo-root", str(checkout)]
    assert run("model-binding", "add", *root, "--id", "keyed", "--label", "L",
               "--provider", "p", "--credential-approver",
               "brett@opensoft.one",
               "--endpoint", "https://api.example.invalid/v1/chat/completions",
               "--dialect", OPENAI_CHAT, "--auth-kind", "api_key",
               "--credential-ref", _STAND_IN_PROVIDER_KEY,
               "--", "openprofiler-broker") == 1
    captured = capsys.readouterr()
    assert binding_mod.CREDENTIAL_REF_IS_A_RAW_KEY in captured.err
    assert _STAND_IN_PROVIDER_KEY not in captured.err + captured.out
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))
    assert store.list() == ()
    assert run("model-binding", "list", *root) == 0
    assert _STAND_IN_PROVIDER_KEY not in capsys.readouterr().out


class _UnreadableSource:
    """A standard input that must never be read."""

    def read(self, *_args):
        raise AssertionError("set-credential read a credential it had no "
                             "custodian for")

    readline = read


@pytest.mark.parametrize("binding_factory", [_none_binding, _built_in_binding],
                         ids=["none", "built-in"])
def test_set_credential_refuses_a_binding_no_broker_answers(tmp_path, capsys,
                                                            binding_factory):
    checkout = tmp_path / "checkout"
    (checkout / "ideation" / "dashboard").mkdir(parents=True)
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))
    binding = binding_factory()
    store.add(binding)
    args = cli_mod.build_parser().parse_args([
        "model-binding", "set-credential", "--repo-root", str(checkout),
        "--id", binding.id])
    assert cli_mod.cmd_model_binding_set_credential(
        args, source=_UnreadableSource()) == 1
    assert "names no broker" in capsys.readouterr().err
    assert store.get(binding.id) == binding, "nothing changed"


# --- the broker path keeps the same rules (follows T080) -----------------
# Brett Heap's word of 2026-09-29, answering openDox-code#63's closing
# question ("Should the broker path follow it?"): "Yes, separate phase-3
# draft". A broker's minted token keeps every rule T080 gave a credential the
# built-in resolver reads. At `main`, and at T080's head, the broker path had
# four gaps, each measured over real sockets and a real broker child:
#
#   1. the token could be declared over plain http:// to any host;
#   2. a redirect, or an environment proxy, carried it elsewhere;
#   3. a provider-unreachable refusal chained urllib's error, whose frames
#      held the token in their locals;
#   4. a token that cannot be presented went to urllib as it was, so one
#      outside latin-1 failed there as DIAG_PROVIDER_UNREACHABLE.
#
# Each gap's cases below fail at T080's head, and the controls beside them
# (a private route declared, a presentable token presented) pass there too.
# Every token here is an obvious fake.


@ON_A_PRIVATE_ROUTE
def test_a_broker_token_is_declared_on_a_private_route(endpoint):
    """The control for gap 1: every route a built-in credential may take."""
    binding = _binding(endpoint=endpoint, dialect=OPENAI_CHAT)
    assert binding.endpoint == endpoint
    assert binding.credential_source() == binding_mod.CREDENTIAL_FROM_BROKER


@NOT_ON_A_PRIVATE_ROUTE
def test_a_broker_token_over_http_to_another_host_is_refused(endpoint):
    """Gap 1. Refused when it is declared, by the constructor and from a
    stored record alike, with the fixed sentence a built-in credential
    earns on the same route."""
    with pytest.raises(binding_mod.BindingRefused) as caught:
        _binding(endpoint=endpoint, dialect=OPENAI_CHAT)
    assert str(caught.value) == binding_mod.ENDPOINT_NOT_PRIVATE
    record = dict(_binding().as_record(), endpoint=endpoint)
    with pytest.raises(binding_mod.BindingRefused) as caught:
        binding_mod.ModelProviderBinding.from_record(record)
    assert str(caught.value) == binding_mod.ENDPOINT_NOT_PRIVATE


def test_mint_asks_no_broker_for_a_token_on_a_route_that_is_not_private(
        tmp_path):
    """Gap 1, in `mint` itself, as the built-in resolver checks before it
    reads. The record refuses such a binding when it is declared, so this
    one is forced past that check, as no declaration can do. It still
    cannot make a broker mint."""
    script = _write_broker(tmp_path)
    binding = _broker_binding(script)
    object.__setattr__(binding, "endpoint", "http://api.example.invalid/v1")
    with pytest.raises(AssertionError) as caught:
        provider_mod.mint(binding, trust=_trusted(binding))
    assert "nothing was minted" in str(caught.value)
    assert _seen_all(script) == [], "the broker was never asked"


def test_the_cli_refuses_a_broker_binding_over_http_to_another_host(
        tmp_path, capsys):
    """Gap 1, through the operator door: refused, and nothing is stored."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    args = cli_mod.build_parser().parse_args([
        "model-binding", "add", "--repo-root", str(checkout),
        "--id", "cleartext-broker", "--label", "L", "--provider", "local",
        "--credential-ref", FAKE_REFERENCE, "--auth-kind", "api_key",
        "--credential-approver", "brett@opensoft.one",
        "--endpoint", "http://api.example.invalid/v1/chat/completions",
        "--dialect", OPENAI_CHAT, "--", "openprofiler-broker"])
    assert args.func(args) == 1
    assert binding_mod.ENDPOINT_NOT_PRIVATE in capsys.readouterr().err
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))
    assert store.list() == (), "nothing is stored"


def _minting_port(tmp_path, endpoint, *, token=SENTINEL_TOKEN):
    """A port as a served install builds one, for a binding at `endpoint`
    whose broker, a real child, mints `token`. It keeps the default opener,
    so nothing stands between the port and the socket."""
    binding = _broker_binding(_write_broker(tmp_path, token=token),
                              endpoint=endpoint, dialect=OPENAI_CHAT)
    return provider_mod.BrokeredProviderPort(
        binding, install_mod.brokered_catalog(binding),
        notice=lambda _text: None, trust=_trusted(binding))


def _refused_turn(port) -> provider_mod.BrokerRefused:
    """The refusal one turn on `port` ends in."""
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    return caught.value


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_a_broker_token_follows_no_redirect(tmp_path, monkeypatch, code):
    """Gap 2, over real sockets, for each redirect code.

    At T080's head, urllib followed only the 301, 302 and 303 codes. For
    those it sent a GET that still carried the minted token to the
    redirect's target, and the turn was answered from there. It did not
    follow a 307 or a 308, and the turn refused with
    `DIAG_PROVIDER_REFUSED`, as though the provider had refused. Now every
    redirect is declined, the second server hears nothing, and the refusal
    chains nothing."""
    with _a_provider_that_redirects(monkeypatch, code) as base:
        refusal = _refused_turn(
            _minting_port(tmp_path, f"{base}/v1/chat/completions"))
    assert refusal.diagnostic == provider_mod.DIAG_PROVIDER_REDIRECTED
    assert _ElsewhereHandler.seen == [], "the token went nowhere else"
    assert refusal.__cause__ is None
    assert refusal.__context__ is None


def test_a_broker_token_over_http_to_this_host_uses_no_proxy(tmp_path,
                                                             monkeypatch):
    """Gap 2, over real sockets. With `http_proxy` set, T080's head sent a
    request that carried a minted token to the proxy, even one addressed to
    `127.0.0.1` (measured with a fresh global opener, as in a process
    started with the variable set). The request goes direct, and the
    stand-in proxy hears nothing."""
    monkeypatch.setattr(_ChatCompletionsHandler, "seen", {})
    with _an_environment_proxy(monkeypatch), \
            _stand_in_provider(_ChatCompletionsHandler) as base:
        answer = _minting_port(
            tmp_path, f"{base}/v1/chat/completions").dispatch(_Envelope())
    assert answer["assistant_prose"] == "answered in the chat grammar"
    assert _ChatCompletionsHandler.seen["authorization"] == (
        f"Bearer {SENTINEL_TOKEN}")
    assert _ElsewhereHandler.seen == [], "the proxy heard nothing"


def test_a_refused_connection_keeps_no_frame_that_holds_the_token(tmp_path):
    """Gap 3, over the real transport. At T080's head this refusal chained
    urllib's `URLError`, and five frames it kept held the token in their
    locals (measured: `do_open.headers`, `_send_request.headers`,
    `_send_output.msg`, `send.data` and `request.headers`). The refusal
    chains nothing, and no frame it keeps holds the token."""
    with _a_closed_loopback_port() as closed:
        refusal = _refused_turn(_minting_port(
            tmp_path, f"http://127.0.0.1:{closed}/v1/chat/completions"))
    assert refusal.diagnostic == provider_mod.DIAG_PROVIDER_UNREACHABLE
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    assert _locals_holding(refusal, SENTINEL_TOKEN) == []


@pytest.mark.parametrize("outcomes,expected", [
    ((urllib.error.URLError("down"),),
     provider_mod.DIAG_PROVIDER_UNREACHABLE),
    ((urllib.error.HTTPError(ENDPOINT, 500, "boom", {},
                             io.BytesIO(b"provider detail")),),
     provider_mod.DIAG_PROVIDER_REFUSED),
    ((b"not json",), provider_mod.DIAG_PROVIDER_MALFORMED),
    ((_expired_error(), _expired_error()),
     provider_mod.DIAG_TOKEN_EXPIRED_TWICE),
], ids=["unreachable", "refused", "malformed", "expired-twice"])
def test_a_refusal_of_a_turn_that_presented_a_token_chains_nothing(
        tmp_path, outcomes, expected):
    """Gap 3, for each refusal a presented token can meet. At T080's head
    each of them kept urllib's error, or the expiry, as its cause or its
    context."""
    port, _opener = _port(tmp_path, *outcomes)
    refusal = _refused_turn(port)
    assert refusal.diagnostic == expected
    assert refusal.__cause__ is None
    assert refusal.__context__ is None


def test_a_re_mint_the_broker_refuses_after_an_expiry_keeps_no_context(
        tmp_path):
    """The one re-mint the 2026-08-26 ruling allows happens outside every
    handler, so the broker's refusal of it keeps no context. At T080's head
    it kept the expiry, which kept urllib's error."""
    asked: list = []

    def refuses_a_second_mint(argv, **kwargs):
        asked.append(argv)
        if len(asked) > 1:
            raise provider_mod.BrokerRefused(provider_mod.DIAG_BROKER_REFUSED)
        return provider_mod.subprocess_broker_runner(argv, **kwargs)

    port, opener = _port(tmp_path, _expired_error(),
                         runner=refuses_a_second_mint)
    refusal = _refused_turn(port)
    assert refusal.diagnostic == provider_mod.DIAG_BROKER_REFUSED
    assert len(opener.requests) == 1, "no paid retry without a token"
    assert refusal.__context__ is None


@pytest.mark.parametrize("token", [
    f"{SENTINEL_TOKEN}\u20ac", f"{SENTINEL_TOKEN}\u00e9",
    "mint-stand-in NOT-A-TOKEN", "mint-stand-in\tNOT-A-TOKEN",
    f"{SENTINEL_TOKEN}\n", f"{SENTINEL_TOKEN}\x00", f"{SENTINEL_TOKEN}\x7f",
    f"{SENTINEL_TOKEN} ",
], ids=["outside-latin-1", "latin-1-not-ascii", "embedded-space", "tab",
        "line-break", "nul", "delete", "trailing-space"])
def test_an_unpresentable_token_is_refused_before_any_request(tmp_path,
                                                            token):
    """Gap 4. A bearer credential is printable ASCII with no whitespace, and
    the minted token is held to the test the built-in resolver's value
    meets. At T080's head each of these reached the opener as it was. A
    refused answer is no mint: nothing is held, and nothing is recorded."""
    port, opener = _port(tmp_path, _chat_completion(), dialect=OPENAI_CHAT,
                         token=token)
    refusal = _refused_turn(port)
    assert refusal.diagnostic == provider_mod.DIAG_BROKER_MALFORMED
    assert opener.requests == [], "no provider was contacted"
    assert port.catalog().entries[0].available is False
    assert port.ledger == []


def test_a_token_outside_latin_1_is_refused_before_any_header_is_built(
        tmp_path, monkeypatch):
    """Gap 4, over a real socket, because the failure was `urllib`'s. At
    T080's head such a token failed while the header was encoded, and the
    turn read `DIAG_PROVIDER_UNREACHABLE`, which names the wrong party. It
    is now the broker's answer that is refused, nothing is chained, and no
    request is sent."""
    monkeypatch.setattr(_ChatCompletionsHandler, "seen", {})
    with _stand_in_provider(_ChatCompletionsHandler) as base:
        refusal = _refused_turn(_minting_port(
            tmp_path, f"{base}/v1/chat/completions",
            token=f"{SENTINEL_TOKEN}\u20ac"))
    assert refusal.diagnostic == provider_mod.DIAG_BROKER_MALFORMED
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    assert _ChatCompletionsHandler.seen == {}, "no request reached the server"


def test_a_token_of_printable_ascii_is_presented_as_it_is(tmp_path):
    """The control for gap 4: the check refuses what a bearer credential
    cannot be and nothing more, so every printable ASCII character but the
    space is presented unchanged."""
    token = "mint-" + "".join(chr(code) for code in range(0x21, 0x7F))
    port, opener = _port(tmp_path, _chat_completion("a"), dialect=OPENAI_CHAT,
                         token=token)
    assert port.dispatch(_Envelope())["assistant_prose"] == "a"
    assert opener.requests[0].get_header("Authorization") == f"Bearer {token}"


def test_an_unpresentable_token_leaves_no_frame_that_holds_it(tmp_path):
    """A token refused as unpresentable can still be most of a token, such
    as one with a line break after it. The refusal keeps no frame that holds
    it, as the built-in resolver's refusal of an unpresentable value keeps
    none."""
    port, _opener = _port(tmp_path, _chat_completion(), dialect=OPENAI_CHAT,
                          token=f"{SENTINEL_TOKEN}\n")
    refusal = _refused_turn(port)
    assert refusal.diagnostic == provider_mod.DIAG_BROKER_MALFORMED
    assert _locals_holding(refusal, SENTINEL_TOKEN) == []


def _mint_answer(**changes) -> dict:
    """A mint answer in the declared shape, carrying `SENTINEL_TOKEN`, with
    `changes` applied."""
    answer = {
        "schema_version": 1, "kind": "openprofiler_broker_mint",
        "reference": FAKE_REFERENCE, "binding": "openprofiler-demo",
        "provider": "demo-provider", "auth_kind": "api_key",
        "token": SENTINEL_TOKEN, "token_type": "api_key",
        "issued_at": "2026-08-26T14:07:52Z",
        "expires_at": _iso(time.time() + 300), "expires_in_seconds": 300,
        "scope": [], "issued_by": "openprofiler-broker/0.1.4-fake",
        "approved_by": "brett@opensoft.one",
        "audit_ref": "opaud-" + "0" * 24, "retry_of": None,
        "enforcement": {"expiry": "broker_bookkeeping", "scope": "declared"}}
    answer.update(changes)
    return answer


def _broker_answering(tmp_path, text: str) -> Path:
    """A broker that answers every operation with `text`, verbatim."""
    script = tmp_path / "answering-broker.py"
    script.write_text(f"import sys\nsys.stdout.write({text!r})\n",
                      encoding="utf-8")
    return script


def test_the_declared_mint_answer_mints(tmp_path):
    """The control for the case below: this answer, unchanged, mints."""
    script = _broker_answering(tmp_path, json.dumps(_mint_answer()))
    assert provider_mod.mint(_broker_binding(script), trust=_trusted(_broker_binding(script))).token == SENTINEL_TOKEN


#: A mint answer nested past the interpreter's recursion limit, and still well
#: inside the broker's answer bound.
_NESTED_PAST_THE_LIMIT = (json.dumps(_mint_answer())[:-1] + ', "deep": '
                          + "[" * 30_000 + "]" * 30_000 + "}")


@pytest.mark.parametrize("text", [
    json.dumps(_mint_answer(expires_at="not-an-instant")),
    json.dumps(_mint_answer(debug_note="a key the declaration does not name")),
    json.dumps(_mint_answer())[:-1],
    json.dumps(_mint_answer(expires_at=10 ** 400)),
    json.dumps(_mint_answer(expires_at=float("nan"))),
    json.dumps(_mint_answer(expires_at=float("inf"))),
    json.dumps(_mint_answer(expires_at=float("-inf"))),
    _NESTED_PAST_THE_LIMIT,
], ids=["expiry-malformed", "undeclared-key", "not-json",
        "expiry-past-a-float", "expiry-nan", "expiry-infinite",
        "expiry-minus-infinite", "nested-past-the-recursion-limit"])
def test_a_malformed_mint_answer_keeps_no_frame_that_holds_its_token(
        tmp_path, text):
    """The same rule for every refusal of the answer that carried the token.
    At T080's head the answer stayed in the refusal's frames (measured:
    `mint.answer`, `mint.document`, `_answer_document.text` and
    `_answer_document.document`).

    Some answers escaped `mint` outright (Copilot's review of
    openDox-code#64 at `a2c838a0`): an expiry past a float's range, as an
    `OverflowError`, and an answer nested past the recursion limit, as a
    `RecursionError`. An expiry of `NaN` or an infinity minted a token that
    would never expire, or would always have expired. Each is now a
    malformed answer, and its refusal keeps no frame, cause or context that
    holds the token."""
    assert len(text.encode("utf-8")) <= provider_mod.MAX_BROKER_ANSWER_BYTES, \
        "a case for the answer's parser, not for the runner's bound"
    binding = _broker_binding(_broker_answering(tmp_path, text))
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(binding, trust=_trusted(binding))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _locals_holding(caught.value, SENTINEL_TOKEN) == []


#: A provider answer nested past the interpreter's recursion limit, and still
#: well inside the provider's answer bound.
_PROVIDER_ANSWER_NESTED_PAST_THE_LIMIT = (
    b'{"choices": ' + b"[" * 30_000 + b"]" * 30_000 + b"}")


@pytest.mark.parametrize("source", ["broker", "built-in", "none"])
def test_a_provider_answer_nested_past_the_recursion_limit_is_malformed(
        tmp_path, source):
    """Copilot's review of openDox-code#64 at `e1a6cb0f`. The provider's
    answer is parsed in `_post_to_provider`, whose frame holds the request,
    and so its authorization header. An answer nested past the recursion
    limit fits well inside the answer's bound. Its parse escaped as a
    `RecursionError`, with that frame in its traceback, on every path. It
    is now a malformed answer. A refusal of a request that carried a
    credential chains nothing, and keeps no frame of the call that held it.
    Under the auth kind `none` nothing was presented, so its refusal is held
    to the fixed sentence alone."""
    payload = _PROVIDER_ANSWER_NESTED_PAST_THE_LIMIT
    assert len(payload) <= provider_mod.MAX_PROVIDER_ANSWER_BYTES, \
        "a case for the answer's parser, not for its bound"
    secret = None
    if source == "broker":
        port, _opener = _port(tmp_path, payload)
        secret = SENTINEL_TOKEN
    elif source == "built-in":
        port, _opener = _unbrokered_port(
            _built_in_binding(), payload, environ={ENV_NAME: KEY_SENTINEL})
        secret = KEY_SENTINEL
    else:
        port, _opener = _unbrokered_port(_none_binding(), payload)
    envelope = _Envelope()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(envelope)
    assert caught.value.diagnostic == provider_mod.DIAG_PROVIDER_MALFORMED
    if secret is not None:
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        kept = {frame.f_code.co_name
                for frame in _frames_kept_by(caught.value)}
        assert "_post_to_provider" not in kept, kept
        assert _locals_holding(caught.value, secret) == []


# --- a broker that misbehaves is refused with nothing it wrote -----------
# Brett Heap's word of 2026-09-29 (openxFactory#656, the lane's latest RULED
# comment): "Yes, add to #64". When a broker misbehaves, the shared runner's
# refusal carries no broker output, no cause and no context, for all four
# operations. So that it stays useful, it names the operation and the failure
# class, and never the bytes. Measured at #64's `788d764b`, with a broker that
# wrote the token before it misbehaved:
#
#   * exits non-zero: the runner's frame held the token, in `answer` and in
#     the child's `_fileobj2output`;
#   * answers past the bound: the same, and the refusal read as MALFORMED;
#   * times out, with its output open or closed: the refusal chained the
#     `TimeoutExpired`, whose `output` and whose frames inside `subprocess`
#     held the token;
#   * answers in bytes that are not UTF-8: a `UnicodeDecodeError` escaped
#     holding the token in `object`, and no refusal was raised at all.
#
# No refusal named its operation, and two of the sentences said no token
# could be minted, whichever operation had failed. Every case below fails at
# `788d764b`. Every token here is an obvious fake.

#: Long enough for a Python child to start and write, well before it expires.
_MISBEHAVING_TIMEOUT = 1.0

#: What each broker below does once it has written `SENTINEL_TOKEN`, and the
#: failure class its refusal names. The sentence is named here, and read
#: only once the refusal has been checked for what it keeps.
_MISBEHAVIOURS = {
    "exits-non-zero": (
        "sys.stdout.write(TOKEN)\nwrote()\nsys.exit(3)\n",
        "DIAG_BROKER_REFUSED"),
    "answers-past-the-bound": (
        "sys.stdout.write(TOKEN)\nwrote()\nsys.stdout.write('x' * BOUND)\n",
        "DIAG_BROKER_OVERSIZE"),
    "times-out": (
        "sys.stdout.write(TOKEN)\nwrote()\ntime.sleep(30)\n",
        "DIAG_BROKER_TIMEOUT"),
    "closes-its-output-and-times-out": (
        "sys.stdout.write(TOKEN)\nwrote()\nos.close(1)\ntime.sleep(30)\n",
        "DIAG_BROKER_TIMEOUT"),
    "answers-in-no-utf-8": (
        "sys.stdout.buffer.write(TOKEN.encode() + b'\\xff')\nwrote()\n",
        "DIAG_BROKER_MALFORMED"),
    "answers-in-no-utf-8-and-times-out": (
        "sys.stdout.buffer.write(TOKEN.encode() + b'\\xff')\nwrote()\n"
        "time.sleep(30)\n",
        "DIAG_BROKER_TIMEOUT"),
}

#: The broker's preamble. `wrote()` flushes, then leaves a mark beside the
#: script, so a test can show the token was written before the misbehaviour.
_MISBEHAVING_PREAMBLE = (
    "import os, pathlib, sys, time\n"
    "TOKEN = {token!r}\n"
    "BOUND = {bound!r}\n"
    "def wrote():\n"
    "    sys.stdout.flush()\n"
    "    pathlib.Path(sys.argv[0] + '.wrote').touch()\n")


def _misbehaving_broker(tmp_path, misbehaviour: str) -> Path:
    body, _sentence = _MISBEHAVIOURS[misbehaviour]
    script = tmp_path / f"{misbehaviour}-broker.py"
    script.write_text(_MISBEHAVING_PREAMBLE.format(
        token=SENTINEL_TOKEN, bound=provider_mod.MAX_BROKER_ANSWER_BYTES)
        + body, encoding="utf-8")
    return script


def _sentence_for(misbehaviour: str) -> str:
    return getattr(provider_mod, _MISBEHAVIOURS[misbehaviour][1])


def _wrote(script: Path) -> bool:
    return Path(str(script) + ".wrote").is_file()


def _kept_anywhere(exception, secret: str) -> list[str]:
    """`_locals_holding`, and one level deeper. The attributes of each local
    are searched too, since that is where a `Popen` keeps what its child
    wrote (`_fileobj2output`). So are the refusal's own arguments and
    attributes."""
    found = set(_locals_holding(exception, secret))
    for frame in _frames_kept_by(exception):
        for name, value in list(frame.f_locals.items()):
            attributes = getattr(value, "__dict__", None)
            if (isinstance(attributes, dict)
                    and secret in _safe_repr(attributes)):
                found.add(f"{frame.f_code.co_name}.{name}.__dict__")
    if (secret in _safe_repr(exception.args)
            or secret in _safe_repr(vars(exception))):
        found.add("the refusal itself")
    return sorted(found)


def _children_kept_by(exception) -> list[str]:
    """The frame locals that hold a broker child (`subprocess.Popen`). A
    child holds the pipe its answer came down, and whatever that pipe's
    buffers still hold, so no refusal keeps one."""
    return sorted({f"{frame.f_code.co_name}.{name}"
                   for frame in _frames_kept_by(exception)
                   for name, value in list(frame.f_locals.items())
                   if isinstance(value, subprocess.Popen)})


#: Each operation, asked through its own function, with the real runner.
_OPERATIONS_ASKED = {
    provider_mod.OPERATION_INTAKE: lambda binding, runner: (
        provider_mod.hand_off_credential(
            binding, io.StringIO("sk-stand-in-intake-NOT-A-KEY"),
            runner=runner, trust=_trusted(binding))),
    provider_mod.OPERATION_MINT: lambda binding, runner: (
        provider_mod.mint(binding, runner=runner, trust=_trusted(binding))),
    provider_mod.OPERATION_REVOKE: lambda binding, runner: (
        provider_mod.revoke(binding, runner=runner, trust=_trusted(binding))),
    provider_mod.OPERATION_LIST: lambda binding, runner: (
        provider_mod.list_references(binding, runner=runner, trust=_trusted(binding))),
}


def test_every_operation_is_asked_here():
    assert tuple(_OPERATIONS_ASKED) == provider_mod.OPERATIONS


@pytest.mark.parametrize("misbehaviour", sorted(_MISBEHAVIOURS))
def test_the_shared_runner_refuses_a_misbehaving_broker_keeping_nothing(
        tmp_path, misbehaviour):
    """The runner itself, called directly. Its refusal keeps no cause, no
    context, no frame or attribute that holds what the broker wrote, and no
    frame that holds the child. It names the failure class. It is not told
    the operation, so it names none."""
    script = _misbehaving_broker(tmp_path, misbehaviour)
    argv = provider_mod.broker_operation_argv(
        _broker_binding(script), provider_mod.OPERATION_MINT)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.subprocess_broker_runner(
            argv, timeout=_MISBEHAVING_TIMEOUT)
    refusal = caught.value
    assert _wrote(script), "the broker wrote the token before it misbehaved"
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    assert _kept_anywhere(refusal, SENTINEL_TOKEN) == []
    assert _children_kept_by(refusal) == []
    expected = _sentence_for(misbehaviour)
    assert refusal.diagnostic == expected
    assert refusal.operation is None
    assert str(refusal) == expected


def test_a_broker_that_writes_without_end_is_refused_at_the_bound(tmp_path):
    """Copilot's review of openDox-code#64 at `25788f91`: the bound was
    checked only once the whole answer had been read, so it bounded nothing
    in memory. A broker that writes without end is now refused as soon as it
    passes the bound, well inside the timeout, and it is killed there. At
    `25788f91`, and at `788d764b`, the runner read it until the timeout and
    refused it as a timeout."""
    script = tmp_path / "endless-broker.py"
    script.write_text(
        "import sys, time\n"
        f"sys.stdout.write({SENTINEL_TOKEN!r})\n"
        "while True:\n"
        "    sys.stdout.write('x' * 65536)\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(0.01)\n", encoding="utf-8")
    argv = provider_mod.broker_operation_argv(
        _broker_binding(script), provider_mod.OPERATION_MINT)
    started = time.monotonic()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.subprocess_broker_runner(argv, timeout=5.0)
    assert time.monotonic() - started < 2.5, "refused at the bound"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert _kept_anywhere(caught.value, SENTINEL_TOKEN) == []
    assert _children_kept_by(caught.value) == []
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_OVERSIZE


@pytest.mark.parametrize("operation", provider_mod.OPERATIONS)
@pytest.mark.parametrize("misbehaviour", sorted(_MISBEHAVIOURS))
def test_a_misbehaving_broker_is_refused_naming_the_operation(
        tmp_path, misbehaviour, operation):
    """Each of the four operations, through the real runner. The refusal
    names the operation and the failure class, and keeps nothing the broker
    wrote."""
    script = _misbehaving_broker(tmp_path, misbehaviour)
    runner = functools.partial(provider_mod.subprocess_broker_runner,
                               timeout=_MISBEHAVING_TIMEOUT)
    ask, binding = _OPERATIONS_ASKED[operation], _broker_binding(script)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        ask(binding, runner)
    refusal = caught.value
    assert _wrote(script), "the broker wrote the token before it misbehaved"
    assert refusal.__cause__ is None
    assert refusal.__context__ is None
    assert _kept_anywhere(refusal, SENTINEL_TOKEN) == []
    assert _children_kept_by(refusal) == []
    expected = _sentence_for(misbehaviour)
    assert refusal.diagnostic == expected
    assert refusal.operation == operation
    assert str(refusal) == f"broker {operation}: {expected}"


@pytest.mark.parametrize("operation", provider_mod.OPERATIONS)
def test_a_broker_that_cannot_be_started_chains_nothing(tmp_path, operation):
    """A program that does not exist wrote nothing, and its refusal chains
    nothing either. At `788d764b` it chained the `FileNotFoundError`, by the
    runner and by the operation alike."""
    binding = _binding(broker_argv=(str(tmp_path / "no-such-broker"),))
    argv = provider_mod.broker_operation_argv(binding, operation)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.subprocess_broker_runner(argv)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_UNREACHABLE
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        _OPERATIONS_ASKED[operation](binding,
                                     provider_mod.subprocess_broker_runner)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert caught.value.operation == operation
    assert str(caught.value) == (
        f"broker {operation}: {provider_mod.DIAG_BROKER_UNREACHABLE}")


def test_a_credential_source_that_fails_leaves_no_broker_running(tmp_path):
    """The credential's own source is the operator's input, not the
    broker's output, so the ruling does not reach it. A source that fails
    while it is copied still escapes as it did. But the broker must not be
    left running with its reader blocked on it, which aborted the
    interpreter at exit at `b847ef3d` ("Fatal Python error:
    _enter_buffered_busy"). A child interpreter runs it, so that its exit
    is what is measured."""
    binding = _broker_binding(_write_broker(tmp_path))
    fields = {field.name: getattr(binding, field.name)
              for field in dataclasses.fields(binding)}
    program = (
        "from opendox import doxbench_binding as b\n"
        "from opendox import doxbench_provider as p\n"
        "class Failing:\n"
        "    parts = ['sk-stand-in-input-side-NOT-A-KEY']\n"
        "    def read(self, _size=-1):\n"
        "        if self.parts:\n"
        "            return self.parts.pop()\n"
        "        raise UnicodeDecodeError('utf-8', b'x', 0, 1, 'stand-in')\n"
        f"binding = b.ModelProviderBinding(**{fields!r})\n"
        "from opendox import doxbench_trust as t\n"
        "p.hand_off_credential(binding, Failing(), "
        "trust=t.TrustVerdict.trusted_for(binding, root=None, basis='test'))\n")
    run = subprocess.run([sys.executable, "-c", program], cwd=tmp_path,
                         capture_output=True, text=True, timeout=60,
                         check=False)
    assert "Fatal Python error" not in run.stderr
    assert run.returncode == 1
    assert "UnicodeDecodeError" in run.stderr
    assert "sk-stand-in-input-side-NOT-A-KEY" not in run.stderr


def _still_running(pid: int, *, within: float = 2.0) -> bool:
    """Whether `pid` is still running after `within` seconds. A zombie,
    which a container's first process may never reap, has stopped."""
    deadline = time.monotonic() + within
    while True:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1]
        except OSError:
            return False
        if state.split()[0] in ("Z", "X"):
            return False
        if time.monotonic() > deadline:
            return True
        time.sleep(0.05)


@pytest.mark.parametrize("leaves_the_group", [False, True],
                         ids=["descendant-in-its-group",
                              "descendant-that-left-it"])
def test_a_broker_whose_descendant_holds_its_output_is_still_refused_in_time(
        tmp_path, leaves_the_group):
    """Copilot's reviews of openDox-code#64 at `b847ef3d` and `a603a032`.
    A descendant that inherits the broker's standard output kept the pipe
    open after the broker was killed. At `e3eec6b1` the refusal waited on it
    forever. At `a603a032` a descendant that left the group left a reader
    thread blocked, and its descriptor open, behind every refusal. The
    broker now has its own process group, which a refusal kills whole, and
    one loop in the calling thread reads the answer. So the refusal comes
    at the timeout, and leaves no thread and no descriptor behind."""
    script = tmp_path / "forking-broker.py"
    script.write_text(
        "import os, subprocess, sys, time\n"
        "descendant = subprocess.Popen([sys.executable, '-c', "
        f"'import os, time\\n{'os.setsid()' if leaves_the_group else 'pass'}"
        "\\ntime.sleep(10)'])\n"
        "open(sys.argv[0] + '.pid', 'w').write(str(descendant.pid))\n"
        f"sys.stdout.write({SENTINEL_TOKEN!r})\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n", encoding="utf-8")
    argv = provider_mod.broker_operation_argv(
        _broker_binding(script), provider_mod.OPERATION_MINT)
    caught: list = []

    def run():
        try:
            provider_mod.subprocess_broker_runner(argv, timeout=0.5)
        except provider_mod.BrokerRefused as refusal:
            caught.append(refusal)

    threads = threading.active_count()
    descriptors = len(os.listdir("/proc/self/fd"))
    runner = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    runner.start()
    runner.join(10)
    assert not runner.is_alive(), "the refusal waited on the descendant"
    elapsed = time.monotonic() - started
    [refusal] = caught
    assert elapsed < 0.5 + 2, "refused at the timeout"
    assert threading.active_count() == threads, "no thread is left behind"
    assert len(os.listdir("/proc/self/fd")) == descriptors, \
        "no descriptor is left behind"
    descendant = int(Path(str(script) + ".pid").read_text(encoding="utf-8"))
    if not leaves_the_group:
        assert not _still_running(descendant), \
            "the broker's whole process group is killed"
    assert refusal.diagnostic == provider_mod.DIAG_BROKER_TIMEOUT
    assert _kept_anywhere(refusal, SENTINEL_TOKEN) == []


def _process_state(pid: int) -> str | None:
    """The state letter `/proc` gives `pid` (`Z` for a zombie, which has
    exited and is not yet reaped), or None once it is gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rsplit(")", 1)[1].split()[0]


@pytest.mark.parametrize("misbehaviour", ["exits-non-zero",
                                          "answers-in-no-utf-8"])
def test_a_refusal_after_the_broker_exits_kills_what_is_left_of_its_group(
        tmp_path, monkeypatch, misbehaviour):
    """Copilot's review of openDox-code#64 at `a271d307`, a note it had
    missed before. A broker left a descendant in its group, holding none of
    its pipes, and then exited non-zero or answered in bytes that are not
    UTF-8. It was refused at once, but the descendant went on running, and
    each such call left one more. Every refusal of the runner now kills
    what is left of the broker's group, as the timeout and the bound
    already did.

    Copilot's review at `bbcb565e`: the group's id is the broker's pid,
    which can be reused once the broker is reaped. At `bbcb565e` the broker
    was reaped first and its group signalled after. Now the group is
    signalled while the broker is a zombie, exited and not yet reaped."""
    signalled: list = []
    killpg = os.killpg

    def recording_killpg(pgid, sig):
        signalled.append(_process_state(pgid))
        return killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", recording_killpg)
    if misbehaviour == "exits-non-zero":
        last, expected = "sys.exit(3)\n", provider_mod.DIAG_BROKER_REFUSED
    else:
        last = "sys.stdout.buffer.write(b'\\xff')\n"
        expected = provider_mod.DIAG_BROKER_MALFORMED
    script = tmp_path / "descendant-leaving-broker.py"
    script.write_text(
        "import subprocess, sys\n"
        "descendant = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(20)'],\n"
        "    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
        "    stderr=subprocess.DEVNULL)\n"
        "open(sys.argv[0] + '.pid', 'w').write(str(descendant.pid))\n"
        f"sys.stdout.write({SENTINEL_TOKEN!r})\n"
        "sys.stdout.flush()\n" + last, encoding="utf-8")
    argv = provider_mod.broker_operation_argv(
        _broker_binding(script), provider_mod.OPERATION_MINT)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.subprocess_broker_runner(argv, timeout=5)
    descendant = int(Path(str(script) + ".pid").read_text(encoding="utf-8"))
    try:
        assert caught.value.diagnostic == expected
        assert signalled == ["Z"], \
            "the group is signalled once, before the broker is reaped"
        assert not _still_running(descendant), \
            "the descendant was left running"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(descendant, signal.SIGKILL)


def test_where_an_exit_cannot_be_read_unreaped_no_group_is_signalled(
        tmp_path, monkeypatch):
    """Where `os.waitid` does not exist, the broker is reaped as its exit
    is read, so its pid, which is its group's id, may already be reused.
    Its refusal then signals no group at all. A descendant still in that
    group is not reached there, which is the one cost."""
    monkeypatch.delattr(os, "waitid")
    signalled: list = []
    killpg = os.killpg

    def recording_killpg(pgid, sig):
        signalled.append(pgid)
        return killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", recording_killpg)
    script = tmp_path / "descendant-leaving-broker.py"
    script.write_text(
        "import subprocess, sys\n"
        "descendant = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(20)'],\n"
        "    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
        "    stderr=subprocess.DEVNULL)\n"
        "open(sys.argv[0] + '.pid', 'w').write(str(descendant.pid))\n"
        "sys.exit(3)\n", encoding="utf-8")
    argv = provider_mod.broker_operation_argv(
        _broker_binding(script), provider_mod.OPERATION_MINT)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.subprocess_broker_runner(argv, timeout=5)
    descendant = int(Path(str(script) + ".pid").read_text(encoding="utf-8"))
    try:
        assert caught.value.diagnostic == provider_mod.DIAG_BROKER_REFUSED
        assert signalled == [], "no group is signalled after the reap"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(descendant, signal.SIGKILL)


def test_a_refusal_waits_on_a_killed_broker_only_so_long(monkeypatch):
    """Copilot's review of openDox-code#64 at `bbcb565e`. SIGKILL ends a
    broker at once unless it is stuck in uninterruptible I/O. Then the
    refusal's wait, unbounded at `bbcb565e`, never returned, and this
    process's ends of the pipes stayed open. The wait is bounded, and the
    pipes are closed past it. The stand-in here is a real broker whose
    `wait` behaves as that one's would."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, process_group=0)
    reap = child.wait
    asked: list = []

    def a_wait_sigkill_cannot_end(timeout=None):
        asked.append(timeout)
        if timeout is None:
            raise AssertionError("an unbounded wait")
        raise subprocess.TimeoutExpired(child.args, timeout)

    monkeypatch.setattr(child, "wait", a_wait_sigkill_cannot_end)
    try:
        provider_mod._reap(child)
        assert asked == [provider_mod._REAP_GRACE_SECONDS]
        assert child.stdin is None
        assert child.stdout.closed
    finally:
        monkeypatch.undo()
        child.kill()
        reap(timeout=10)


def test_a_broker_that_never_reads_the_credential_is_refused_in_time(
        tmp_path):
    """The timeout covers the credential's streaming too. At `a603a032` the
    credential was written before the timeout began, so a broker that never
    read a credential larger than its pipe held the refusal until the broker
    itself exited."""
    script = tmp_path / "deaf-broker.py"
    # It reads a little and then stops, so the pipe has room for some of
    # the credential but not for all of it.
    script.write_text("import os, time\nos.read(0, 5000)\ntime.sleep(30)\n",
                      encoding="utf-8")
    binding = _broker_binding(script)
    runner = functools.partial(provider_mod.subprocess_broker_runner,
                               timeout=0.5)
    caught: list = []

    def run():
        try:
            provider_mod.hand_off_credential(
                binding, io.StringIO("k" * 1_000_000), runner=runner, trust=_trusted(binding))
        except provider_mod.BrokerRefused as refusal:
            caught.append(refusal)

    thread = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(10)
    assert not thread.is_alive(), "the refusal waited on the broker"
    assert time.monotonic() - started < 0.5 + 2
    [refusal] = caught
    assert refusal.diagnostic == provider_mod.DIAG_BROKER_TIMEOUT
    assert refusal.operation == provider_mod.OPERATION_INTAKE


class _SourceFailingOnceMarked:
    """A credential source that gives a small part at each read, and fails
    a few reads after `mark` exists. So the broker has written, and its
    answer has been read, before the source fails."""

    def __init__(self, mark: Path) -> None:
        self.mark = mark
        self.reads_since_marked = 0

    def read(self, _size=-1):
        time.sleep(0.02)
        if self.mark.exists():
            self.reads_since_marked += 1
        if self.reads_since_marked > 5:
            raise UnicodeDecodeError("utf-8", b"x", 0, 1, "stand-in")
        return "sk-stand-in-input-side-NOT-A-KEY"


def test_a_failing_credential_source_escapes_with_no_broker_output(tmp_path):
    """The same escape, in this process, from a broker that wrote the
    token while the credential was still streaming. What escapes keeps
    nothing the broker wrote, as a refusal would not. The broker is not
    left running, where it would read the end of its input and store
    whatever part of the credential had reached it."""
    script = tmp_path / "early-writing-broker.py"
    script.write_text(_MISBEHAVING_PREAMBLE.format(
        token=SENTINEL_TOKEN, bound=provider_mod.MAX_BROKER_ANSWER_BYTES)
        + "pathlib.Path(sys.argv[0] + '.pid').write_text(str(os.getpid()))\n"
        "sys.stdout.write(TOKEN)\nwrote()\ntime.sleep(30)\n",
        encoding="utf-8")
    source = _SourceFailingOnceMarked(Path(str(script) + ".wrote"))
    binding = _broker_binding(script)
    with pytest.raises(UnicodeDecodeError) as caught:
        provider_mod.hand_off_credential(binding, source, trust=_trusted(binding))
    assert _wrote(script), "the broker wrote before the source failed"
    assert _kept_anywhere(caught.value, SENTINEL_TOKEN) == []
    pid = int(Path(str(script) + ".pid").read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize("operation", provider_mod.OPERATIONS)
def test_an_injected_runners_refusal_is_named_too(tmp_path, operation):
    """The operation is named by the function that asked, so a runner that
    was injected is covered as the default one is."""
    def refusing(argv, **_kwargs):
        raise provider_mod.BrokerRefused(provider_mod.DIAG_BROKER_REFUSED)

    ask, binding = _OPERATIONS_ASKED[operation], _binding()
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        ask(binding, refusing)
    assert caught.value.operation == operation
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_REFUSED
    assert caught.value.__context__ is None


def test_only_a_broker_sentence_names_a_declared_operation():
    refusal = provider_mod.BrokerRefused(
        provider_mod.DIAG_BROKER_TIMEOUT,
        operation=provider_mod.OPERATION_REVOKE)
    assert str(refusal) == f"broker revoke: {provider_mod.DIAG_BROKER_TIMEOUT}"
    assert refusal.diagnostic == provider_mod.DIAG_BROKER_TIMEOUT
    assert refusal.operation == provider_mod.OPERATION_REVOKE
    with pytest.raises(AssertionError):
        provider_mod.BrokerRefused(provider_mod.DIAG_BROKER_REFUSED,
                                   operation="exfiltrate")
    with pytest.raises(AssertionError):
        provider_mod.BrokerRefused(provider_mod.DIAG_PROVIDER_REFUSED,
                                   operation=provider_mod.OPERATION_MINT)
    provider_refusal = provider_mod.BrokerRefused(
        provider_mod.DIAG_PROVIDER_REFUSED)
    assert provider_refusal.operation is None
    assert str(provider_refusal) == provider_mod.DIAG_PROVIDER_REFUSED


def test_the_operator_door_names_the_operation_and_withholds_the_answer(
        tmp_path, capsys):
    """What an operator reads when `set-credential` meets a broker that wrote
    and then exited non-zero: the operation and the failure class, and none
    of what it wrote."""
    script = _misbehaving_broker(tmp_path, "exits-non-zero")
    checkout = tmp_path / "checkout"
    (checkout / "ideation" / "dashboard").mkdir(parents=True)
    store = binding_mod.BindingStore(binding_mod.bindings_path(checkout))
    store.add(_broker_binding(script, credential_ref="opref-" + "0" * 24))
    _trust_in_place(store.get("openprofiler-demo"), checkout)
    args = cli_mod.build_parser().parse_args([
        "model-binding", "set-credential", "--repo-root", str(checkout),
        "--id", "openprofiler-demo"])
    assert cli_mod.cmd_model_binding_set_credential(
        args, source=io.StringIO("sk-stand-in-intake-NOT-A-KEY")) == 1
    captured = capsys.readouterr()
    assert captured.err == (
        f"broker intake: {provider_mod.DIAG_BROKER_REFUSED}\n")
    assert SENTINEL_TOKEN not in captured.out + captured.err
