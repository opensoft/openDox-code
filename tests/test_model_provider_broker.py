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
`env:` and keyring resolver, and the auth kind `none` (T080).

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

import contextlib
import dataclasses
import http.server
import io
import json
import subprocess
import sys
import threading
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import REPO_ROOT  # noqa: F401  (path setup)

from opendox import cli as cli_mod
from opendox import doxbench_binding as binding_mod
from opendox import doxbench_install as install_mod
from opendox import doxbench_model as model_mod
from opendox import doxbench_provider as provider_mod

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

    resolve = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout)
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
        binding, io.StringIO(SENTINEL_CREDENTIAL))
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
    provider_mod.mint(_broker_binding(script))
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
    assert list(signature.parameters) == ["binding", "source", "runner"]


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
    minted = provider_mod.mint(binding)
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
        provider_mod.mint(_broker_binding(script))
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
                                         io.StringIO("x"))
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
                                         io.StringIO("x"))
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
    assert provider_mod.revoke(binding) == "opaud-77b0c4e91d3a5628ff0e1a42"
    assert _seen(script)["argv"] == ["revoke", "--reference", FAKE_REFERENCE]
    assert provider_mod.list_references(binding) == []
    assert _seen(script)["argv"] == ["list"]
    assert _seen(script)["stdin"] is None


def test_the_minted_token_redacts_itself_in_every_rendering(tmp_path):
    script = _write_broker(tmp_path)
    minted = provider_mod.mint(_broker_binding(script))
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
          model=None):
    script = _write_broker(tmp_path, expires=expires)
    binding = _broker_binding(script, endpoint=endpoint, dialect=dialect,
                              model=model)
    opener = _Opener(*outcomes)
    port = provider_mod.BrokeredProviderPort(
        binding, install_mod.brokered_catalog(binding),
        opener=opener, clock=clock,
        notice=notice if notice is not None else (lambda _text: None))
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
        provider_mod.mint(_broker_binding(script))
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
        provider_mod.hand_off_credential(binding, big)
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_REFUSED, \
        "the exit code is the answer, not the write error"
    assert caught.value.diagnostic != provider_mod.DIAG_BROKER_UNREACHABLE


def test_a_broker_that_cannot_be_started_is_still_unreachable(tmp_path):
    """The distinction the finding asked for cuts both ways: a program that
    does not exist is NOT a refusal, and keeps its own sentence."""
    binding = _binding(broker_argv=(str(tmp_path / "no-such-broker"),))
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(binding)
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_UNREACHABLE


def test_a_broker_that_answers_garbage_is_a_fixed_refusal(tmp_path):
    script = tmp_path / "garbled-broker.py"
    script.write_text("import sys\nprint('not json')\n", encoding="utf-8")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(_broker_binding(script))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED


def test_a_refusal_cannot_be_composed_from_what_a_broker_said():
    with pytest.raises(AssertionError):
        provider_mod.BrokerRefused("the provider said: your key is bad")


def test_the_fixed_diagnostics_are_all_reachable_and_no_more():
    """The closed set shed the dialect sentence when the dialect became a
    declaration-time refusal; keeping an unraisable sentence would be a refusal
    nobody can trigger. TEN since #1144 box 16.3: the built-in resolver's two
    joined, and section (f) below reaches each of them."""
    assert len(provider_mod.FIXED_DIAGNOSTICS) == 10
    assert {provider_mod.DIAG_REFERENCE_UNRESOLVED,
            provider_mod.DIAG_KEYRING_UNAVAILABLE} <= \
        provider_mod.FIXED_DIAGNOSTICS
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
    entrypoints have always made."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    resolve = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout)
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
    resolve = install_mod.declared_model_port_factory(
        tmp_path / "sessions", checkout_root=checkout)
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
            notice=lambda _text: None)
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
    provider_mod.mint(_broker_binding(script))
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
    script = tmp_path / "loud-broker.py"
    script.write_text(
        "import sys\n"
        f"sys.stdout.write('x' * {provider_mod.MAX_BROKER_ANSWER_BYTES + 1})\n",
        encoding="utf-8")
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        provider_mod.mint(_broker_binding(script))
    assert caught.value.diagnostic == provider_mod.DIAG_BROKER_MALFORMED


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
            notice=lambda _text: None)
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
    assert f"model            {DECLARED_MODEL}" in capsys.readouterr().out

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
            notice=lambda _text: None).dispatch(_Envelope())
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
    with pytest.raises(binding_mod.BindingRefused) as caught:
        binding_mod.BindingStore(path).list()
    assert KEY_SENTINEL not in str(caught.value)


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
    assert binding.credential_ref is None and binding.broker_argv == ()
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
    parts = binding_mod.built_in_reference_parts
    assert parts(f"env:{ENV_NAME}") == ("env:", ENV_NAME)
    # the split is at the LAST `/`, so a service may carry one
    assert parts(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}") == (
        "keyring:", KEYRING_SERVICE, KEYRING_USER)
    assert parts(FAKE_REFERENCE) is None
    assert binding_mod.BUILT_IN_REFERENCE_FORMS == ("env:", "keyring:")


@pytest.mark.parametrize("reference", [
    "env:", "env:1BAD", "env:A-B", "env: SPACED", "env:NAME\n",
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
    assert record["credential_ref"] is None and record["broker_argv"] == []
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
        with pytest.raises(AssertionError):
            provider_mod.hand_off_credential(binding, io.StringIO("x"))


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
        environ=environ, keyring_backend=keyring_backend)
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


def test_production_reads_this_processs_own_environment(monkeypatch):
    monkeypatch.setenv(ENV_NAME, KEY_SENTINEL)
    port, opener = _unbrokered_port(_built_in_binding(),
                                    _chat_completion("a"))
    port.dispatch(_Envelope())
    assert opener.requests[0].get_header("Authorization") == \
        f"Bearer {KEY_SENTINEL}"


@pytest.mark.parametrize("environ", [
    {}, {ENV_NAME: ""}, {ENV_NAME: "   "}, {ENV_NAME: "sk-stand-in\nX-Other: 1"},
    {ENV_NAME: "sk-stand-in\x00"}],
    ids=["unset", "empty", "blank", "line-break", "nul"])
def test_an_unusable_env_value_refuses_before_any_request(environ):
    port, opener = _unbrokered_port(_built_in_binding(), _chat_completion(),
                                    environ=environ)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
    assert caught.value.diagnostic == provider_mod.DIAG_REFERENCE_UNRESOLVED
    assert opener.requests == [], "no provider was contacted"
    assert port.catalog().entries[0].available is False


def test_a_reference_that_resolves_again_makes_the_entry_available_again():
    environ: dict[str, str] = {}
    port, _opener = _unbrokered_port(_built_in_binding(),
                                     _chat_completion("a"), environ=environ)
    with pytest.raises(provider_mod.BrokerRefused):
        port.dispatch(_Envelope())
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


def test_an_absent_keyring_entry_refuses_unresolved():
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion(), keyring_backend=_FakeKeyring())
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
    assert caught.value.diagnostic == provider_mod.DIAG_REFERENCE_UNRESOLVED
    assert opener.requests == []


def test_a_keyring_that_cannot_be_read_refuses_and_says_nothing_of_its_own():
    backend = _FakeKeyring(error=RuntimeError("backend detail that leaks"))
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion(), keyring_backend=backend)
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
    assert caught.value.diagnostic == provider_mod.DIAG_KEYRING_UNAVAILABLE
    assert "leaks" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert opener.requests == []


def test_without_the_keyring_package_a_keyring_reference_refuses(monkeypatch):
    """`keyring` is not a dependency of this package. Without it, the
    production path refuses with the fixed sentence, not an import error."""
    monkeypatch.setitem(sys.modules, "keyring", None)
    port, opener = _unbrokered_port(
        _built_in_binding(f"keyring:{KEYRING_SERVICE}/{KEYRING_USER}"),
        _chat_completion())
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
    assert caught.value.diagnostic == provider_mod.DIAG_KEYRING_UNAVAILABLE
    assert opener.requests == []


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
    with pytest.raises(provider_mod.BrokerRefused) as caught:
        port.dispatch(_Envelope())
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
            environ={ENV_NAME: KEY_SENTINEL})
        assert port.dispatch(_Envelope())["assistant_prose"] == \
            "answered in the chat grammar"
    assert _ChatCompletionsHandler.seen["authorization"] == expected
    assert _ChatCompletionsHandler.seen["body"]["model"] == DECLARED_MODEL


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

    assert run("model-binding", "list", *root) == 0
    listed = capsys.readouterr().out
    from opendox import cli_model_binding as cmb
    assert f"credential ref   {cmb.NOT_DECLARED}" in listed
    assert f"broker argv      {cmb.NOT_DECLARED}" in listed
    assert f"credential ref   env:{ENV_NAME}" in listed

    assert run("model-binding", "remove", *root, "--id", "env-bound") == 0
    assert binding_mod.BUILT_IN_REMOVAL_NOTICE in capsys.readouterr().out


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
