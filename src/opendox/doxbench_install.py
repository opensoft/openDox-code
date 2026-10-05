"""The INSTALL-TIME model-provider declaration a doxBench entrypoint makes.

WHY A MODULE AND NOT A LINE IN `cli.py`. The entrypoint already makes two
install-time declarations in exactly this idiom — `adapter_factory=
serve_mod.real_notebook_adapter` and `knowledge_declaration=
knowledge_mod.SELF_HOSTED_LOCAL_EMBEDDED` — for the reason those call sites give
in as many words: *an operator must be able to read what their install talks
to*. The model provider is the same kind of fact and it is declared the same
way, so this module holds the three inputs `OmpHarnessBridge` cannot supply
itself, beside each other, in one readable place:

  * `HARNESS_CATALOG` — the approved model choices this install discloses. A
    DECLARATION CONSTANT, never a per-turn parameter. It matters that it is not
    the constructor's default: `OmpHarnessBridge`'s `catalog` defaults to
    `EMPTY_CATALOG` (`doxbench_model.EMPTY_CATALOG`), so a bare declaration would
    resolve, disclose nothing, and look to an operator exactly like a working
    install with nothing approved.
  * a SESSION ROOT — where the harness child's session files, its artifact
    directories and the bridge's own config overlay land. Supplied by the
    entrypoint (a CLI flag, defaulted beside the served snapshot), because
    `OmpHarnessBridge.__init__` has a keyword-only `session_root` with NO
    default: the adapter is unconstructible bare, deliberately, so nobody can
    declare one without saying where it writes.
  * a `LaunchConfig` — `provider_id` and `command`, the harness-side half of the
    declaration. `provider_id` lives on the launch and NOT on a catalog entry;
    that placement is a recorded ruling (`ModelCatalogEntry`'s own docstring, and
    `LaunchConfig`'s), and this module honours it rather than reopening it.

WHAT THIS MODULE IS NOT. It is not a provider adapter, it holds no credential,
reads no credential-shaped environment variable, and names no endpoint. The
harness child's environment is an allowlist (`doxbench_bridge.
INHERITED_ENVIRONMENT`) that no credential-shaped variable can pass, and an
API-backed provider's credential is provisioned into the `doxbench-bridge`
harness profile by the ratified broker lane — never held here.

WIDENED BY add-model-provider-broker (ratified 2026-08-26), and the four claims
above all survive the widening. This module now makes a SECOND declaration
beside the harness one: when the checkout declares a model-provider BINDING,
`declared_model_port_factory` resolves the broker-backed
`doxbench_provider.BrokeredProviderPort` instead of the harness bridge. It
still names no endpoint OF ITS OWN (the route is the BINDING's declaration
since the 2026-08-26 reconciliation — openProfiler's mint answer carries
neither an endpoint nor a dialect, deliberately — and the only module that
CONTACTS one is still `doxbench_provider`), still holds no credential and no
token
(both live in `doxbench_provider`, the one module permitted to hold them), and
still reads no credential-shaped environment variable. What it gained is a
CHOICE between two declarations, which is exactly the kind of install-time fact
this module exists to make readable in one place.

THE UNCONFIGURED POSTURE IS A STATE (#1144's 16.4; plan 034's T081). A checkout
with no approved binding resolves the SAME `model_port_factory(session_root)`
the entrypoints have always resolved WHERE THE HARNESS IS INSTALLED, so the
harness route stays for an install that has it. Where it is not (`omp`,
`doxbench_bridge.HARNESS_COMMAND`, is not on the PATH: `harness_installed()`),
there is no model, and the declaration says so: it resolves
`doxbench_model.NO_MODEL_CONFIGURED`, whose catalog offers no available entry,
and which `serve_workbench`'s accessor answers as no port at all. So the served
catalog is the editor-only posture before any turn, and a turn is refused
`model_capability_unavailable` before any process is spawned or any endpoint is
contacted. Until T081, the harness declaration answered here whether or not
`omp` existed, and its catalog offered `omp-local` as available: an install
with no model read as one with a model until a turn failed.

ONE INSTANCE PER PROCESS, and that is a requirement rather than an optimisation.
`_workbench_model_port` is called PER REQUEST, and `OmpHarnessBridge` is
STATEFUL: it holds the per-document-thread harness sessions and the selected
one. A factory that constructed a bridge per call would break the
one-session-per-document-thread correspondence BY CONSTRUCTION and would restart
a supervised child on every request. So `model_port_factory` returns a
ZERO-ARGUMENT callable — the shape `serve.py`'s accessor calls, with no
arguments — that closes over the declaration and hands back the SAME bridge for
the life of the served process.

CONSTRUCTION IS LAZY, resolution is not. The bridge is built on the first
resolution rather than at import or at parse time, so an entrypoint that is
never asked for a model builds nothing; and the bridge itself starts its child
only at the first TURN that needs one, so resolving a port — which every
capabilities probe does — spawns no harness process.
"""

from __future__ import annotations

import shutil
import sys
import threading
from pathlib import Path

from opendox import doxbench_bridge as bridge_mod
from opendox import doxbench_model
from opendox.doxbench_model import ModelCatalog, ModelCatalogEntry

# --------------------------------------------------------------------------
# the harness-side declaration
# --------------------------------------------------------------------------

# The harness provider the approved models are registered under, in the
# bridge's own `doxbench-bridge` profile. `local-proxy` is the keyless,
# on-this-host posture the catalog badge below states: a local OpenAI-shaped
# endpoint the operator runs, which is why no credential appears anywhere in
# this module.
HARNESS_PROVIDER_ID = "local-proxy"

# The one approved choice this install discloses. An OPAQUE UI handle, not a
# provider model name (the catalog contract says so in as many words), so
# changing which local model answers is an operator-side change to the harness
# profile and not a change to this id.
HARNESS_MODEL_ID = "omp-local"

# Limits NARROW the server ceilings, they never widen them: 1,048,576 request
# bytes and 900,000 output bytes are the released schema's maxima.
HARNESS_INPUT_LIMIT_BYTES = 200_000
HARNESS_OUTPUT_LIMIT_BYTES = 64_000

HARNESS_CATALOG = ModelCatalog.from_entries([
    ModelCatalogEntry(
        model_id=HARNESS_MODEL_ID,
        label="Local harness model",
        provider_class="self_hosted",
        available=True,
        input_limit_bytes=HARNESS_INPUT_LIMIT_BYTES,
        output_limit_bytes=HARNESS_OUTPUT_LIMIT_BYTES,
        data_handling="stays on this host: a local harness child, no hosted provider",
    ),
])
"""The install's approved model catalog — the declaration an operator reads.

AVAILABLE ON PURPOSE, and it is a claim about the DECLARATION, not a probe: the
bridge marks every entry unavailable the moment it knows itself dead or
unstartable (`OmpHarnessBridge.catalog`), which is the honest posture for a
harness that never started. Declaring the entry unavailable up front would say
the same thing about an install that works."""

# Where a serve's harness sessions live when the entrypoint was not told
# otherwise: beside the served snapshot, in the run directory this process
# already owns. NEVER inside the served checkout and never a corpus path — the
# child's cwd is its own session directory, so a harness tool that reaches for
# the filesystem lands in scratch space rather than in the corpus.
MODEL_SESSIONS_DIRNAME = "model-sessions"


def session_root_beside(snapshot_path: Path | str) -> Path:
    """The default session root for a serve of `snapshot_path`.

    One rule for both entrypoints — `cli.py`'s `generate-and-open` and
    `serve()` — so the two cannot drift into writing harness sessions in two
    different places."""
    return Path(snapshot_path).resolve().parent / MODEL_SESSIONS_DIRNAME


def harness_launch(session_root: Path | str) -> bridge_mod.LaunchConfig:
    """The launch this install declares: the harness command and the provider
    its approved models are registered under, rooted at `session_root`.

    `command` is named explicitly rather than left to the dataclass default so
    the declaration an operator reads is complete on its own."""
    root = Path(session_root)
    return bridge_mod.LaunchConfig(session_dir=root,
                                   command=bridge_mod.HARNESS_COMMAND,
                                   provider_id=HARNESS_PROVIDER_ID)


def model_port_factory(session_root: Path | str, *,
                       catalog: ModelCatalog = HARNESS_CATALOG,
                       launch: bridge_mod.LaunchConfig | None = None,
                       spawn=None):
    """The ZERO-ARGUMENT `model_port_factory` an entrypoint declares.

    Returns a callable taking NO arguments — the shape
    `serve.DashboardHandler._workbench_model_port` calls — which resolves to the
    SAME `OmpHarnessBridge` every time, for the life of this process. The lock
    is not decoration: the server is a `ThreadingHTTPServer`, so two requests
    really can resolve the port at once, and two bridges would be two disjoint
    session tables.

    `spawn` is the bridge's own child-process seam, passed through so a caller
    that must exercise a turn can inject a double; production declares none and
    the bridge uses its real spawn."""
    root = Path(session_root)
    declared_launch = launch if launch is not None else harness_launch(root)
    lock = threading.Lock()
    holder: dict[str, bridge_mod.OmpHarnessBridge] = {}

    def resolve() -> bridge_mod.OmpHarnessBridge:
        port = holder.get("port")
        if port is not None:
            return port
        with lock:
            port = holder.get("port")
            if port is None:
                port = bridge_mod.OmpHarnessBridge(
                    catalog, session_root=root, launch=declared_launch,
                    spawn=spawn)
                holder["port"] = port
            return port

    return resolve


def harness_installed() -> bool:
    """Is the harness installed: is `doxbench_bridge.HARNESS_COMMAND` on the
    PATH this process resolves commands from?

    The same question #1144's F16.1 asks as its precondition (`command -v omp`),
    asked without starting anything: it reads the PATH and spawns no process."""
    return shutil.which(bridge_mod.HARNESS_COMMAND) is not None


def no_model_port_factory() -> doxbench_model.NoModelConfigured:
    """The ZERO-ARGUMENT factory for an install with no model: it answers
    `doxbench_model.NO_MODEL_CONFIGURED`, the one no-model port, and builds,
    spawns and contacts nothing."""
    return doxbench_model.NO_MODEL_CONFIGURED


# --------------------------------------------------------------------------
# the BROKERED declaration (add-model-provider-broker tasks 2.2/2.5)
# --------------------------------------------------------------------------

# Limits for a brokered provider, narrowing the server ceilings exactly as the
# harness entry's do. Conservative on purpose: a binding names a provider this
# repository has never measured, so the declaration promises the smaller number
# rather than the schema's maximum.
BROKERED_INPUT_LIMIT_BYTES = 200_000
BROKERED_OUTPUT_LIMIT_BYTES = 64_000

# The handling badge a brokered entry carries. It states the posture PLAINLY
# and in the opposite direction from the harness entry's, because it is the
# opposite posture: this one leaves the host.
BROKERED_DATA_HANDLING = (
    "leaves this host: a hosted provider reached with a short-lived token the "
    "credential broker minted")

# The `provider_class` a brokered entry declares. Free-form by the catalog
# contract, and this is the honest word for it: the model is reached through a
# broker's credential rather than run on this host.
BROKERED_PROVIDER_CLASS = "brokered"


def brokered_catalog(binding) -> ModelCatalog:
    """The one-entry catalog a BINDING discloses.

    Built FROM the binding rather than declared beside it, so the menu an
    operator sees names the binding they declared — its id and its label — and
    cannot drift from it. The id is the binding's id for the same reason: a
    catalog handle that did not match the binding would make a turn's chosen
    model unresolvable back to the declaration that reached it.

    AVAILABLE ON PURPOSE, and it is a claim about the DECLARATION exactly as the
    harness catalog's is: `BrokeredProviderPort.catalog()` marks every entry
    unavailable the moment a mint has refused, which is the honest posture for a
    broker that cannot answer, while declaring it unavailable up front would say
    the same thing about a binding that works."""
    return ModelCatalog.from_entries([
        ModelCatalogEntry(
            model_id=binding.id,
            label=binding.label,
            provider_class=BROKERED_PROVIDER_CLASS,
            available=True,
            input_limit_bytes=BROKERED_INPUT_LIMIT_BYTES,
            output_limit_bytes=BROKERED_OUTPUT_LIMIT_BYTES,
            data_handling=BROKERED_DATA_HANDLING,
        ),
    ])


def brokered_model_port_factory(binding, *, trust=None, runner=None,
                                opener=None, clock=None, notice=None):
    """The ZERO-ARGUMENT factory for a BROKER-BACKED port, memoized per process.

    Same shape and same reason as `model_port_factory` above: the accessor is
    called per REQUEST, and a port built per call would mint a fresh token for
    every turn and discard a live one. The seams (`runner`, `opener`, `clock`,
    `notice`) pass through so a test can exercise a turn without a broker and
    without a provider; production declares none of them.

    `trust` is the verdict that covers this exact binding (#1144 16.3a;
    `doxbench_trust`). The port asks it again before every act, so a port
    built without one spawns, reads and contacts nothing."""
    from opendox import doxbench_provider as provider_mod

    seams = {name: value for name, value in (
        ("runner", runner), ("opener", opener), ("clock", clock),
        ("notice", notice)) if value is not None}
    seams["trust"] = trust
    catalog = brokered_catalog(binding)
    lock = threading.Lock()
    holder: dict[str, object] = {}

    def resolve():
        port = holder.get("port")
        if port is not None:
            return port
        with lock:
            port = holder.get("port")
            if port is None:
                port = provider_mod.BrokeredProviderPort(
                    binding, catalog, **seams)
                holder["port"] = port
            return port

    return resolve


def unavailable_catalog(binding) -> ModelCatalog:
    """The catalog a binding discloses when it may not be used: its one entry,
    exactly as `brokered_catalog` declares it, with `available: false`. The
    catalog's wire shape is closed, so no reason rides it (#1144 16.3a)."""
    import dataclasses

    return ModelCatalog.from_entries([
        dataclasses.replace(entry, available=False)
        for entry in brokered_catalog(binding).entries])


def trust_gated_model_port_factory(binding, *, checkout_root: Path | str,
                                   bindings_path: Path | str | None = None):
    """The factory for the first approved binding, ONCE THE TRUST POLICY HAS
    JUDGED IT (#1144 16.3a; plan 034 T100; RULED openxFactory#656 comment
    5962785556, item 2).

    THE ONE PLACE A BINDING BECOMES USABLE. The binding was read from the
    served repository, so it is used only if the registered trust policy
    (`doxbench_trust.policy()`: a host's, or openDox's strict per-machine
    store where no host registered one) trusts that exact binding at
    `checkout_root`. Trusted, it resolves the brokered port, handed the
    verdict. Untrusted, it resolves `doxbench_trust.UntrustedBindingPort`:
    the catalog lists the binding `available: false`, a turn is refused by
    name, and nothing is spawned, read or contacted. The refusal is said on
    stderr, naming the binding and the command that trusts it.

    The verdict is HELD TO THIS BINDING (`doxbench_trust.verdict_for`): a
    policy that raises trusts nothing, and its words are not repeated; one
    that answers for another binding, trusted or not, covers nothing, and the
    refusal names THIS binding and its command.

    A BINDING THE CATALOG REFUSES IS NEVER TRUSTED, whatever the policy or
    the store says (Copilot at openDox-code#82, r4174783280): its id or its
    label is not one `brokered_catalog` can list, so the verdict refuses it
    before any policy is asked (`doxbench_trust.unservable_because`), and
    this declares the refusing port over an empty catalog rather than fail
    on what a repository wrote. So `brokered_catalog` below is only ever
    built for a binding it accepts. The console's start never hands one
    here: `declared_model_port_factory` passes it over (T100 follow-on, A3),
    and this refusal is the defence beneath that, for any other caller.

    `bindings_path` is the document the binding was read from, where a
    caller named one, so the command the refusal prints reads that document
    too."""
    from opendox import doxbench_trust as trust_mod
    from opendox.doxbench_model import EMPTY_CATALOG, ModelCatalogError

    verdict = trust_mod.verdict_for(binding, root=checkout_root)
    if verdict.admits(binding):
        return brokered_model_port_factory(binding, trust=verdict)
    bindings = (None if bindings_path is None
                else str(Path(bindings_path).resolve()))
    sys.stderr.write("[model-provider] " + trust_mod.refusal_message(
        verdict.binding_id, verdict.root,
        verdict.reason or trust_mod.REASON_NEVER_TRUSTED,
        bindings=bindings) + "\n")
    try:
        catalog = unavailable_catalog(binding)
    except ModelCatalogError:
        # An id or a label the catalog's schema refuses (a newline, a
        # terminal escape, an id past its bound) is a binding no turn could
        # name. It is refused by name above, and the catalog lists nothing
        # rather than the start failing on what a repository wrote.
        catalog = EMPTY_CATALOG
    port = trust_mod.UntrustedBindingPort(catalog, verdict, bindings=bindings)

    def resolve():
        return port

    return resolve


def declared_model_port_factory(session_root: Path | str, *,
                                checkout_root: Path | str,
                                bindings_path: Path | str | None = None,
                                spawn=None,
                                harness_present=None):
    """THE declaration both entrypoints make (task 2.5).

    ONE rule, in one place, so `cli.cmd_generate_and_open` and `serve.serve()`
    cannot drift into two answers for "what does this install talk to":

      * a checkout declaring a model-provider BINDING resolves the brokered
        port for the FIRST declared binding, and every provider endpoint and
        every minted token it needs lives inside `doxbench_provider`;
      * a checkout declaring NONE resolves the harness bridge where the harness
        is installed, exactly as these entrypoints always have, and
        `doxbench_model.NO_MODEL_CONFIGURED` where it is not (#1144's 16.4;
        the module docstring). `harness_present` is that question, a
        zero-argument callable, `harness_installed` by default, so a caller
        that exercises a harness turn through `spawn` can say the harness is
        there;
      * a bindings document that will not READ (malformed YAML, a wrong kind, a
        record naming an unknown key) is read as declaring none, and says so
        on stderr. Refusing to serve at all would make one bad line in an
        operator's settings file take the whole console down, and silently
        serving a DIFFERENT provider than the one declared would be worse than
        either.

    THE FIRST DECLARED BINDING, and that is a stated limitation rather than a
    design: the model seam takes ONE port, so an install talks to one provider
    at a time. Choosing among several declared bindings needs a selection rule
    this change does not have and must not invent — see tasks.md 2.5.

    A BINDING THE MODEL CATALOG CANNOT LIST IS PASSED OVER as a pending one
    is (T100 follow-on, A3). It is no model at all: no turn could name it,
    and declaring it would leave the console with an empty catalog whose
    rail line ("No model configured") offers two remedies, a harness on PATH
    or another binding, neither of which could then take effect. Passed
    over, both do. It is said on stderr, by name, with its remedy.

    A PENDING DECLARATION IS SKIPPED (add-doxchat-model-intake task 3.1). A
    binding the intake flow wrote is DECLARED and not yet APPROVED, and "not yet
    approved" has to mean something at the one seam where availability is
    decided or it means nothing at all: a pending binding contributes no
    available catalog entry, so this factory passes over it exactly as if it were
    not declared. A binding the DECLARATIONS DOCUMENT SAYS NOTHING ABOUT is
    unaffected, byte for byte — it was declared by hand in the settings file by
    the operator, and the operator is who approval is a record of (see
    `doxbench_intake`'s module docstring for why the rule is not inverted).

    A DECLARED BINDING IS USED ONLY ONCE IT IS TRUSTED (#1144 16.3a; plan 034
    T100; RULED openxFactory#656 comment 5962785556, item 2). The binding was
    read from the repository this install serves, so the registered trust
    policy judges the first approved one (`trust_gated_model_port_factory`).
    A checkout declaring none never asks the policy, so it never touches
    openDox's state directory."""
    from opendox import doxbench_binding as binding_mod
    from opendox import doxbench_intake as intake_mod

    store = binding_mod.BindingStore(
        bindings_path if bindings_path is not None
        else binding_mod.bindings_path(checkout_root))
    try:
        declared = store.list()
    except binding_mod.BindingRefused as error:
        sys.stderr.write(
            f"[model-provider] the bindings document could not be read "
            f"({error}); reading it as declaring no binding\n")
        declared = ()
    from opendox import doxbench_trust as trust_mod

    pending = intake_mod.pending_binding_ids(checkout_root)
    unservable = tuple(binding for binding in declared
                       if binding.id not in pending
                       and trust_mod.unservable_because(binding) is not None)
    for binding in unservable:
        sys.stderr.write(
            f"[model-provider] model binding {trust_mod.shown(binding.id)} "
            f"is passed over: {trust_mod.REASON_UNSERVABLE}. "
            f"{trust_mod.REMEDY_UNSERVABLE}\n")
    approved = tuple(binding for binding in declared
                     if binding.id not in pending
                     and binding not in unservable)
    if len(approved) + len(unservable) != len(declared):
        # SAID OUT LOUD, on the same stderr channel the unreadable-document
        # fallback uses: an operator who declared a model through the wizard and
        # then wondered why the selector still has nothing in it deserves to
        # read the reason in their own console rather than infer it.
        sys.stderr.write(
            "[model-provider] "
            f"{len(declared) - len(approved) - len(unservable)} declared "
            "binding(s) are pending "
            "human approval and contribute no available model; approve them "
            "from the console's model intake flow\n")
    if not approved:
        if (harness_present or harness_installed)():
            return model_port_factory(Path(session_root), spawn=spawn)
        return no_model_port_factory
    return trust_gated_model_port_factory(approved[0],
                                          checkout_root=checkout_root,
                                          bindings_path=bindings_path)
