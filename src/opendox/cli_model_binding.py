"""The MODEL-PROVIDER SETTINGS command line: the `model-binding` verbs
(`split-opendox-two-layer-product` § 2.4, PR 4 of 4).

FIXED CORE, NOT AN EXTENSION. Design § D3 files "provider and broker" in the
openDox column, so `build_parser` calls `_add_model_binding_parser` directly and
this surface keeps its position in the parser exactly.

The cleanest of the three moves: nothing here reaches back into the core at all
— the verbs are a closed loop over `doxbench_binding` — so this module needs no
`_core()` accessor and holds no reference to `cli` in either direction.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_trust as trust_mod


# ===========================================================================
# THE MODEL-PROVIDER SETTINGS SURFACE (add-model-provider-broker task 1.2)
#
# List, add, edit, remove — and a credential hand-off that retains nothing.
#
# WHY THE OPERATOR DOOR IS A CLI VERB AND NOT A BROWSER PANE, stated plainly
# because it is a decision and not an oversight (see tasks.md 1.2). Every other
# install-time declaration this console makes — the notebook adapter, the
# retrieval backend, the model session root — is made at the entrypoint, and
# this is the same kind of fact. It is also the stronger place for a credential
# to be typed: a key entered here travels from a terminal handle to the
# broker's standard input and crosses no HTTP wire at all, so the "no
# credential reaches the browser" property is not something the surface has to
# be careful about — it is structural.
# ===========================================================================


def _binding_store(args: argparse.Namespace) -> "binding_mod.BindingStore":
    """The store this invocation acts on. `--bindings` when given, else the
    checkout's own declared path — ONE rule, shared with the entrypoints."""
    path = (Path(args.bindings).resolve() if getattr(args, "bindings", None)
            else binding_mod.bindings_path(Path(args.repo_root).resolve()))
    return binding_mod.BindingStore(path)


def _repo_root(args: argparse.Namespace) -> Path:
    """The repository whose bindings this invocation acts on, resolved: the
    root a binding's trust is keyed to (#1144 16.3a)."""
    return Path(args.repo_root).resolve()


def _record_trust(binding: "binding_mod.ModelProviderBinding",
                  args: argparse.Namespace):
    """Record trust for the binding this act writes (#1144 16.3a; RULED
    openxFactory#656 comment 5962785556, item 2): the operator declares it
    here, so the operator trusts it. Returns the verdict, which admits
    exactly this binding. A store that cannot record, a policy that DECLINES
    (as a governed host's does for a pending declaration) or answers for
    another binding, and a policy that raises, are each refused by name, as
    a `BindingRefused` (`doxbench_trust.recorded_for`). `add`, `edit` and
    `trust` ask BEFORE they write anything, so a refusal leaves nothing
    written (T007 batch M)."""
    return trust_mod.recorded_for(binding, root=_repo_root(args))


def _trusted_line(binding: "binding_mod.ModelProviderBinding", verdict) -> str:
    return (f"  trusted {trust_mod.shown(binding.id)} on this machine for "
            f"{trust_mod.shown(verdict.root)}")


def _declared_binding(args: argparse.Namespace) -> "binding_mod.ModelProviderBinding":
    return binding_mod.ModelProviderBinding(
        id=args.id, label=args.label, provider=args.provider,
        credential_ref=args.credential_ref, auth_kind=args.auth_kind,
        approved_by=args.approved_by, endpoint=args.endpoint,
        dialect=args.dialect, model=args.model,
        broker_argv=tuple(args.broker_argv or ()))


#: What `list` prints for a binding that declares no model (#1144 box 16.2).
#: The request then names the binding's id, as every request did before the
#: field existed, and the operator reading the list should see that.
NO_MODEL_DECLARED = "(none declared: the request names this binding's id)"

#: What `list` prints for a field the record's resolver forbids or does not
#: need (#1144 box 16.3): the reference under the auth kind `none`, and the
#: broker invocation of a record no broker answers. The custody line beside it
#: says which resolver answers instead.
NOT_DECLARED = "(none)"

#: What `set-credential` says of a binding no broker answers (#1144 box 16.3).
#: There is no broker to hand a credential to: the built-in resolver reads the
#: reference at call time, or the endpoint takes none.
NO_BROKER_TO_HAND_TO = (
    "binding {binding_id!r} names no broker, so there is nothing to hand a "
    "credential to: {custody}")


def cmd_model_binding_list(args: argparse.Namespace) -> int:
    """DISCLOSE every declared binding (task 1.2's read-back).

    Prints the binding's own fields and the fixed custody sentence. There is no
    credential material to redact, which is the claim: a read-back cannot leak a
    secret it was never able to hold."""
    store = _binding_store(args)
    try:
        disclosure = store.read_back()
    except binding_mod.BindingRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"  bindings {store.path}")
    if not disclosure["bindings"]:
        print("  (none declared — this install talks to no brokered provider)")
        return 0
    verdicts = _trust_lines(store, args)
    # EVERY VALUE A REPOSITORY WROTE IS PRINTED ESCAPED, in a JSON string's
    # form (#1144 16.3a, T007 batch M): a newline or a terminal control
    # sequence in a field cannot forge or hide a line of this listing.
    shown = trust_mod.shown
    for record in disclosure["bindings"]:
        print(f"  {shown(record['id'])}  {shown(record['label'])}")
        print(f"    provider         {shown(record['provider'])}")
        print(f"    auth kind        {shown(record['auth_kind'])}")
        print(f"    approved by      {shown(record['approved_by'])}")
        reference = record["credential_ref"]
        print(f"    credential ref   "
              f"{shown(reference) if reference is not None else NOT_DECLARED}")
        print(f"    endpoint         {shown(record['endpoint'])}")
        print(f"    dialect          {shown(record['dialect'])}")
        model = record["model"]
        print(f"    model            "
              f"{shown(model) if model is not None else NO_MODEL_DECLARED}")
        argv = record["broker_argv"]
        print(f"    broker argv      {shown(argv) if argv else NOT_DECLARED}")
        print(f"    custody          {record['credential_custody']}")
        print(f"    trust            {verdicts.get(record['id'], '')}")
    return 0


def _trust_lines(store: "binding_mod.BindingStore",
                 args: argparse.Namespace) -> dict[str, str]:
    """`list`'s trust line for each binding (#1144 16.3a): trusted on this
    machine, or why not and the command that trusts it. Asked only when a
    binding is declared, so an empty store never touches the state
    directory."""
    root = _repo_root(args)
    lines: dict[str, str] = {}
    for binding in store.list():
        verdict = trust_mod.verdict_for(binding, root=root)
        if verdict.admits(binding):
            lines[binding.id] = "trusted on this machine"
        else:
            reason = verdict.reason or trust_mod.REASON_NEVER_TRUSTED
            lines[binding.id] = (
                f"NOT trusted on this machine ({reason}); trust it with: "
                f"{trust_mod.trust_command(binding.id, str(root))}")
    return lines


def cmd_model_binding_add(args: argparse.Namespace) -> int:
    """Declare a binding, and trust it on this machine (#1144 16.3a).

    THE TRUST IS RECORDED FIRST, once the binding is known to be new, so a
    store that refuses (a state directory inside the served repository, a
    link, a writable file) leaves NOTHING written (T007 batch M). A write
    that fails after it leaves a trust for a binding never declared, which
    trusts nothing that exists."""
    store = _binding_store(args)
    try:
        binding = _declared_binding(args)
        if store.get(binding.id) is not None:
            store.add(binding)      # refuses the repeated id, in its own words
        verdict = _record_trust(binding, args)
        store.add(binding)
    except binding_mod.BindingRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"  declared {trust_mod.shown(binding.id)} in {store.path}")
    print(f"  {binding.custody_notice()}")
    print(_trusted_line(binding, verdict))
    return 0


def cmd_model_binding_edit(args: argparse.Namespace) -> int:
    """Replace a binding, and trust it on this machine in the form written
    (#1144 16.3a). As `add`, the trust is recorded first, once the binding is
    known to exist, so a store that refuses leaves nothing written."""
    store = _binding_store(args)
    try:
        binding = _declared_binding(args)
        if store.get(binding.id) is None:
            store.edit(binding)     # refuses the unknown id, in its own words
        verdict = _record_trust(binding, args)
        store.edit(binding)
    except binding_mod.BindingRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"  updated {trust_mod.shown(binding.id)} in {store.path}")
    print(_trusted_line(binding, verdict))
    return 0


def cmd_model_binding_remove(args: argparse.Namespace) -> int:
    store = _binding_store(args)
    try:
        binding = store.remove(args.id)
    except binding_mod.BindingRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"  retired {binding.id} from {store.path}")
    print(f"  {binding.removal_notice()}")
    return 0


def cmd_model_binding_set_credential(args: argparse.Namespace, *,
                                     source=None) -> int:
    """Hand a credential to the broker and keep only the reference (task 1.3).

    THE VALUE IS NEVER READ HERE. `source` is the open handle — `sys.stdin` by
    default — and it is passed straight through to
    `doxbench_provider.hand_off_credential`, which streams it into the broker's
    standard input. No variable in this function ever holds the credential, so
    none can outlive the call, be echoed in a message, or reach an exception.
    It is deliberately NOT a command-line argument: an argv is visible in the
    process table and lands in a shell history.

    A BINDING NO BROKER ANSWERS IS REFUSED, and its standard input is left
    unread (#1144 box 16.3). Its credential is where its `env:` or `keyring:`
    reference names, or it takes none, so there is no custodian to hand a
    value to, and reading one here would be holding it for nothing.

    A BINDING NOT TRUSTED ON THIS MACHINE IS REFUSED BY NAME BEFORE ITS
    BROKER IS SPAWNED, and its standard input is left unread (#1144 16.3a;
    RULED openxFactory#656 comment 5962785556, item 2). The broker it would
    run, and the credential it would be handed, are both what a repository
    chose. A TRUSTED binding is re-trusted in its new form once the reference
    is rewritten, because that edit is this act's own. An untrusted one is
    never trusted by this act."""
    from opendox import doxbench_provider as provider_mod

    store = _binding_store(args)
    try:
        binding = store.get(args.id)
        if binding is None:
            raise binding_mod.BindingRefused(
                f"no binding with id {args.id!r} is declared")
        if (binding.credential_source()
                != binding_mod.CREDENTIAL_FROM_BROKER):
            raise binding_mod.BindingRefused(NO_BROKER_TO_HAND_TO.format(
                binding_id=binding.id, custody=binding.custody_notice()))
        verdict = trust_mod.verdict_for(binding, root=_repo_root(args))
        trust_mod.require_admitted(binding, verdict)
        reference = provider_mod.hand_off_credential(
            binding, source if source is not None else sys.stdin,
            trust=verdict)
        rewritten = store.edit(dataclasses.replace(binding,
                                                   credential_ref=reference))
    except (binding_mod.BindingRefused, provider_mod.BrokerRefused) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"  the broker took custody and returned the reference {reference}")
    print(f"  {binding_mod.CUSTODY_NOTICE}")
    # RE-TRUSTED IN ITS NEW FORM, because the binding was trusted and this
    # act made the change (T007 batch M). The reference is already the
    # broker's, so a store that refuses now leaves the binding written and
    # untrusted, which refuses it at use, and says so.
    try:
        verdict = _record_trust(rewritten, args)
    except binding_mod.BindingRefused as exc:
        print(f"{trust_mod.shown(rewritten.id)} holds the new reference, but "
              f"it is NOT trusted on this machine: {exc}", file=sys.stderr)
        return 1
    print(_trusted_line(rewritten, verdict))
    return 0


def _trust_disclosure(binding: "binding_mod.ModelProviderBinding",
                      store: "binding_mod.BindingStore",
                      root: Path) -> list[str]:
    """What `trust` prints BEFORE it records anything (#1144 16.3a; T007 batch
    M): what will run (the broker argv) and where the credential goes (the
    endpoint, the auth kind and the credential REFERENCE), never the
    credential itself. Nothing is resolved here. EVERY VALUE IS PRINTED IN A
    JSON STRING'S FORM (`doxbench_trust.shown`), because each comes from a
    repository someone else may have written."""
    from opendox import doxbench_provider as provider_mod

    shown = trust_mod.shown
    source = binding.credential_source()
    if source == binding_mod.CREDENTIAL_FROM_BROKER:
        resolved_by = "the broker below, which holds the credential"
        runs = [shown(list(provider_mod.broker_operation_argv(
                    binding, operation)))
                for operation in (provider_mod.OPERATION_INTAKE,
                                  provider_mod.OPERATION_MINT)]
    elif source == binding_mod.CREDENTIAL_FROM_BUILT_IN_RESOLVER:
        parts = binding_mod.built_in_reference_parts(binding.credential_ref)
        resolved_by = (
            "the built-in resolver, from the serving process's environment "
            f"variable {shown(parts.name)}"
            if parts.form == binding_mod.CREDENTIAL_REF_ENV else
            "the built-in resolver, from the OS keyring entry for service "
            f"{shown(parts.name)} and user {shown(parts.user)}")
        runs = []
    else:
        resolved_by = "nothing: this endpoint takes no credential"
        runs = []
    goes = (f"to {shown(binding.endpoint)} alone, in each request's "
            "authorization header, never through a redirect, and through no "
            "proxy where the endpoint is plain HTTP"
            if source != binding_mod.NO_CREDENTIAL
            else "nowhere: the auth kind none presents no credential")
    reference = (shown(binding.credential_ref)
                 if binding.credential_ref is not None else NOT_DECLARED)
    model = binding.model if binding.model is not None else binding.id
    lines = [f"  binding          {shown(binding.id)}  {shown(binding.label)}",
             f"    read from      {shown(str(store.path))}",
             f"    repository     {shown(str(root))}",
             f"    provider       {shown(binding.provider)}",
             f"    auth kind      {shown(binding.auth_kind)}",
             f"    credential ref {reference}",
             f"    resolved by    {resolved_by}"]
    if runs:
        lines += [f"    will run       {run}" for run in runs]
    else:
        lines.append("    will run       no program: no broker is declared")
    lines += [f"    credential     goes {goes}",
              f"    chat goes      to {shown(binding.endpoint)} "
              f"(dialect {shown(binding.dialect)}, model {shown(model)})"]
    return lines


def cmd_model_binding_trust(args: argparse.Namespace) -> int:
    """TRUST one binding of this repository ON THIS MACHINE (#1144 16.3a;
    RULED openxFactory#656 comment 5962785556, item 2).

    A binding read from a repository is used only once the operator has
    trusted that exact binding here. This prints what is being trusted first,
    what it would run and where its credential would go, and then records the
    trust. It resolves no reference and spawns nothing. There is no `--yes`:
    running the verb is the act."""
    store = _binding_store(args)
    root = _repo_root(args)
    try:
        binding = store.get(args.binding_id)
        if binding is None:
            raise binding_mod.BindingRefused(
                f"no binding with id {trust_mod.shown(args.binding_id)} is "
                f"declared in {store.path}")
    except binding_mod.BindingRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for line in _trust_disclosure(binding, store, root):
        print(line)
    try:
        verdict = _record_trust(binding, args)
    except binding_mod.BindingRefused as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(_trusted_line(binding, verdict))
    return 0


def _add_binding_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", required=True,
                        help="the checkout whose bindings are being read")
    parser.add_argument(
        "--bindings", default=None,
        help="the bindings document (default: "
             f"<repo-root>/{binding_mod.DEFAULT_BINDINGS_RELPATH})")


def _add_binding_declaration_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--id", required=True, help="the binding's id")
    parser.add_argument("--label", required=True,
                        help="the label the model menu shows")
    parser.add_argument("--provider", required=True,
                        help="the provider's name; where a broker holds the "
                             "credential, the one it takes custody for (the "
                             "broker's declared `--provider`)")
    # A REFERENCE, NEVER THE CREDENTIAL (#1144 box 16.3). NOT REQUIRED by the
    # parser, because the auth kind `none` forbids it. The binding itself
    # refuses a missing reference for every kind that takes a credential, and
    # says why.
    parser.add_argument("--credential-ref", default=None,
                        dest="credential_ref",
                        help="the credential's REFERENCE, NEVER the credential "
                             "itself: env:NAME or keyring:SERVICE/USERNAME, "
                             "which the built-in resolver reads at call time, "
                             "or a reference the broker resolves; omitted "
                             f"for --auth-kind {binding_mod.AUTH_KIND_NONE}")
    parser.add_argument("--auth-kind", required=True, dest="auth_kind",
                        choices=list(binding_mod.AUTH_KINDS),
                        help="the authentication kind of the credential; "
                             f"{binding_mod.AUTH_KIND_NONE} for an endpoint "
                             "that takes none")
    # REQUIRED because the broker requires it: `credential-contracts` holds
    # that a grant without an approver is invalid, and the broker's `intake`
    # refuses without an approver flag. A binding that could not name one could
    # never enrol.
    #
    # SPELLED `--credential-approver` AND NOT AFTER THE BROKER'S OWN FLAG, and
    # that is deliberate rather than careless — MEASURED, in fact: the obvious
    # mirrored spelling turned the suite red.
    # `test_session_verbs.py`'s `test_the_save_cli_offers_no_token_and_no_
    # bypass_flag` scans THIS FILE'S SOURCE for a family of forbidden flag
    # spellings, one of which is the approving verb with two leading dashes,
    # because `contracts/cli.md` + D22 hold that no CLI flag may approve, merge
    # or bypass a record. A substring scan cannot tell a flag that APPROVES
    # from one that NAMES AN APPROVER, and the invariant it protects is worth
    # more than a mirrored spelling — so the flag is renamed rather than the
    # guard loosened, and this comment states the collision without restating
    # the spelling that trips it. The BINDING's field and the broker's own flag
    # keep the declaration's spelling; only this operator-facing name differs,
    # and `dest` carries it back.
    parser.add_argument("--credential-approver", required=True,
                        dest="approved_by",
                        help="the human principal who approved this "
                             "credential; the broker requires one at intake "
                             "and records it on every grant")
    # THE PROVIDER ROUTE IS THE CONSUMER'S. openProfiler's declaration emits
    # neither an endpoint nor a dialect from a mint, deliberately, so both are
    # declared here — see doxbench_binding's module docstring.
    parser.add_argument("--endpoint", required=True,
                        help="the provider endpoint this binding's requests "
                             "are sent to; a URL carrying a credential is "
                             "refused, so name the credential by its reference "
                             "instead")
    parser.add_argument("--dialect", required=True,
                        choices=list(binding_mod.DIALECTS),
                        help="the request grammar that endpoint speaks")
    # THE MODEL THE PROVIDER RECEIVES (#1144 box 16.2), the route's third fact.
    # OPTIONAL, and that keeps a binding declared without it meaning what it
    # always meant: the request names the binding's id. `edit` replaces the
    # whole binding, as it always has, so an edit that omits `--model` declares
    # none.
    parser.add_argument("--model", default=None,
                        help="the model name the provider receives in each "
                             "request (default: none declared, and the "
                             "request names this binding's id)")
    # A POSITIONAL, taken after a bare `--`, and that is the fix for a real
    # trap rather than a style choice: a broker invocation is full of
    # option-shaped members (`--binding`, `--ref`), and as a flag's value they
    # are consumed by THIS parser instead — `--binding` was measured being
    # matched to `--bindings` by argparse's prefix abbreviation, silently
    # rewriting the operator's store path and truncating their template. The
    # subparsers below also set `allow_abbrev=False`, so the two defences are
    # independent.
    #
    # ZERO OR MORE since #1144 box 16.3: a binding the built-in resolver or the
    # auth kind `none` answers names no broker, and one given beside either is
    # refused by the binding itself. A broker's reference still needs its
    # invocation, and the binding still refuses one without it.
    parser.add_argument(
        "broker_argv", nargs="*", metavar="-- BROKER ARGV",
        help="the broker invocation, as argv members, after a bare `--`. "
             f"Placeholders {binding_mod.ARGV_PLACEHOLDERS} are filled from "
             "this binding's own fields. Omitted for an env: or keyring: "
             f"reference and for --auth-kind {binding_mod.AUTH_KIND_NONE}")


def _add_model_binding_parser(sub) -> None:
    group = sub.add_parser(
        "model-binding",
        help="model-provider settings: list / add / edit / remove / trust "
             "bindings, and hand a credential to the broker")
    verbs = group.add_subparsers(dest="model_binding_command", required=True)

    listing = verbs.add_parser("list", help="disclose every declared binding",
                               allow_abbrev=False)
    _add_binding_store_args(listing)
    listing.set_defaults(func=cmd_model_binding_list)

    adding = verbs.add_parser("add", help="declare a new binding",
                              allow_abbrev=False)
    _add_binding_store_args(adding)
    _add_binding_declaration_args(adding)
    adding.set_defaults(func=cmd_model_binding_add)

    editing = verbs.add_parser("edit", help="replace an existing binding",
                               allow_abbrev=False)
    _add_binding_store_args(editing)
    _add_binding_declaration_args(editing)
    editing.set_defaults(func=cmd_model_binding_edit)

    removing = verbs.add_parser("remove", help="retire a binding",
                                allow_abbrev=False)
    _add_binding_store_args(removing)
    removing.add_argument("--id", required=True, help="the binding to retire")
    removing.set_defaults(func=cmd_model_binding_remove)

    handing = verbs.add_parser(
        "set-credential",
        help="read a credential from STANDARD INPUT, hand it to the broker, "
             "and keep only the reference it returns",
        allow_abbrev=False)
    _add_binding_store_args(handing)
    handing.add_argument("--id", required=True,
                         help="the binding whose credential is being set")
    handing.set_defaults(func=cmd_model_binding_set_credential)

    # TRUST (#1144 16.3a; RULED openxFactory#656 comment 5962785556, item
    # 2). The id is a POSITIONAL, as the ruling spells the verb:
    # `opendox model-binding trust <id>`.
    trusting = verbs.add_parser(
        "trust",
        help="trust one binding of this repository on this machine, after "
             "printing what it would run and where its credential would go",
        allow_abbrev=False)
    _add_binding_store_args(trusting)
    trusting.add_argument("binding_id", metavar="ID",
                          help="the binding to trust")
    trusting.set_defaults(func=cmd_model_binding_trust)
