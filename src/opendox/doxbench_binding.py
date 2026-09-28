"""The MODEL-PROVIDER BINDING: what this dashboard holds instead of a secret
(add-model-provider-broker tasks 1.1/1.2).

A binding is the whole of what settings store for a model provider: an id, a
label, the credential REFERENCE the broker resolves, the authentication kind,
and the broker invocation. It is safe to read, safe to log and safe to commit,
which is precisely why it is the only thing kept here — the standing rule for
this workspace is that machinery holds grant and binding templates only, and
`credential-contracts` already owns the shape this applies
(`xfactory_credential_binding_template`: a consumer holds a binding and never a
secret).

NO SECRET FIELD EXISTS IN THIS SHAPE. Not optional, ABSENT. `ModelProviderBinding`
is a frozen, slotted dataclass, so there is no attribute a code path could
populate with a key or a token and no keyword a caller could pass to try: an
extra keyword is a `TypeError` at construction, and an extra attribute is an
`AttributeError` at assignment. That is the enforcement — not a convention, and
not a validator that a later edit could soften.

WHAT IS NOT IN THIS MODULE, deliberately: the broker itself, the credential
hand-off, the minted token, the built-in resolver, and every provider
TRANSPORT. All five live in `doxbench_provider`, the ONE module this repository
permits to hold them, and the structural boundary test names that module by
name. This one holds records and a file, reaches no network, spawns no process,
and never sees a credential.

THE CREDENTIAL STAYS A REFERENCE, AND A KEY IS REFUSED WHEN IT IS DECLARED
(#1144 box 16.3; plan 034 T080). A key inside the endpoint URL is refused by the
product's own detector, `runtime/local_git_adapter.carries_a_credential`, and
the refusal never repeats the URL it refused. An endpoint longer than the
product's URL bound is refused before the detector is asked. A key in an extra
field is refused as an unknown key, as it always was.

EACH RECORD HAS ONE RESOLVER, and the record says which:

  * the BROKER the record names, for any other reference (as before);
  * the BUILT-IN RESOLVER, for an `env:NAME` or `keyring:SERVICE/USERNAME`
    reference. It reads the reference at call time, inside `doxbench_provider`
    only (RULED R1Q17 (b)). Such a record needs no broker, and one given
    beside it is refused, so no record has two resolvers. What it reads is a
    LONG-LIVED key, so its endpoint must be a PRIVATE ROUTE: `https://`, or
    `http://` to 127.0.0.1, ::1 or localhost (Brett Heap's ruling of
    2026-09-28, "Refuse unless loopback"; `is_a_private_route`);
  * NONE, for an endpoint that takes no credential. It declares the auth kind
    `none` rather than leaving a field out, and `credential_ref` and
    `broker_argv` are forbidden under it (RULED R1Q18 (a)).

This module classifies a reference's FORM when a binding is declared. It never
reads what a reference names.

IT DOES NOW DECLARE THE PROVIDER ROUTE, and that is a reconciliation rather than
a widening (task 2.6, 0.2 FINDING 3). The binding carries `endpoint` and
`dialect` because openProfiler's landed declaration
(`docs/broker-cli.md`, § "mint") emits NEITHER: the broker is deliberately
provider-agnostic about the request grammar and refuses to name an endpoint it
would then be accountable for. So provider routing is the CONSUMER's fact, and
the consumer's declared record is where a fact the consumer owns belongs.
Declaring a route is not holding a transport: nothing here opens a socket, and
the module still names no provider host of its own. #1144 box 16.2 gave the
route a third fact, `model`: the model name the provider receives. It is the
consumer's fact for the same reason.

THE BROKER INVOCATION IS DECLARED, NOT WRITTEN INTO CODE — the program and its
fixed leading arguments. `broker_argv` is the BASE invocation and names no
operation: openProfiler takes the operation as an argv SUBCOMMAND
(`intake`/`mint`/`revoke`/`list`), and that subcommand-and-flag vocabulary is
the DECLARATION's, so `doxbench_provider` appends it from its own record of
`docs/broker-cli.md` § "CLI surface" rather than each operator respelling four
argv templates in a settings file they could get subtly wrong. What stays with
the operator is the part only they can know: which program, where it lives, and
any fixed leading arguments it needs.

STDLIB AT IMPORT TIME, and `yaml` only when a document is actually parsed or
written. That is not tidiness: the LEAN HOSTED IMAGE HAS NO PyYAML, and
`tests/ideation-dashboard/test_repo_selector.py`'s hosted-plane test proves it
by poisoning the module and serving anyway. Both entrypoints resolve their
model port through this store at startup, so a module-scope `import yaml` here
would have made every hosted serve die before it printed its URL — measured,
not theorised. A store with no document reads as empty without touching the
parser at all, so an install with no bindings never needs the dependency.
`doxbench_scope` takes the same lazy import for the same class of reason.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# the record's identity (the workspace rule: every YAML carries both)
# ---------------------------------------------------------------------------

#: The stored document's `schema_version`. The DOCUMENT's version governs every
#: record in it; a per-record version would be a second thing to keep in step.
SCHEMA_VERSION = 1

#: The stored document's `kind` — a list of bindings.
BINDINGS_KIND = "model-provider-bindings"

#: One record's own `kind`, stamped on each entry so a binding lifted out of the
#: document still says what it is. This is the `model-provider-binding` record
#: task 1.1 names.
BINDING_KIND = "model-provider-binding"

# ---------------------------------------------------------------------------
# the closed vocabularies
# ---------------------------------------------------------------------------

#: A long-lived API key. The broker the binding names takes custody of it, or,
#: for an `env:` or `keyring:` reference, the built-in resolver reads it at call
#: time (#1144 box 16.3, RULED R1Q17 (b)).
AUTH_KIND_API_KEY = "api_key"

#: An OAuth grant the broker holds and refreshes.
AUTH_KIND_OAUTH = "oauth"

#: An endpoint that takes NO credential, which is the usual local server (#1144
#: box 16.3; RULED R1Q18 (a), openxFactory#656 comment 5850003126). It says so
#: EXPLICITLY, as a kind, and never by a field left out. Under it
#: `credential_ref` and `broker_argv` are FORBIDDEN: there is no credential to
#: refer to and no broker to hold one.
AUTH_KIND_NONE = "none"

#: The CLOSED authentication-kind vocabulary. Closed because a free-text kind
#: riding a record that neither declares nor forbids it is unenforceable and
#: invisible to every consumer — the same argument `credential-contracts` makes
#: for its own `issuance_preconditions` vocabulary.
#:
#: THREE MEMBERS, and the ORDER IS PINNED: `none` joins AFTER the two kinds that
#: take a credential (R1Q18 (a)), so `AUTH_KINDS[0]`, which #1144's F16.1 reads,
#: still names a kind that takes one.
AUTH_KINDS: tuple[str, ...] = (AUTH_KIND_API_KEY, AUTH_KIND_OAUTH,
                               AUTH_KIND_NONE)

#: THE BUILT-IN RESOLVER'S REFERENCE FORMS (#1144 box 16.3; RULED R1Q17 (b)). A
#: standalone install has no broker to resolve a reference, so a reference in
#: one of these forms is resolved by a resolver built into `doxbench_provider`,
#: at call time, in that module only. This module holds the FORMS, as it holds
#: the dialects: it classifies a reference when a binding is declared, and
#: never reads what the reference names.
#:
#:   * `env:NAME` — the environment variable NAME of the serving process. NAME
#:     is a portable variable name: a letter or `_`, then letters, digits or
#:     `_`;
#:   * `keyring:SERVICE/USERNAME` — the OS keyring's entry for that service and
#:     user name. The split is at the LAST `/`, so a service name may contain
#:     one, and a user name may not.
#:
#: Any other reference is a BROKER's, as every reference was before 16.3.
CREDENTIAL_REF_ENV = "env:"
CREDENTIAL_REF_KEYRING = "keyring:"
BUILT_IN_REFERENCE_FORMS: tuple[str, ...] = (CREDENTIAL_REF_ENV,
                                             CREDENTIAL_REF_KEYRING)

#: A portable variable name. `re.ASCII` keeps `\w` to letters, digits and `_`
#: of ASCII alone, so a name no other shell could export is refused.
_ENV_NAME = re.compile(r"[A-Za-z_]\w*", re.ASCII)


class BuiltInReference(NamedTuple):
    """A reference the built-in resolver takes, split into what it looks up.

    One shape for both forms. `form` is one of `BUILT_IN_REFERENCE_FORMS`.
    For `env:NAME`, `name` is the variable and `user` is None. For
    `keyring:SERVICE/USERNAME`, `name` is the service and `user` is the user
    name."""

    form: str
    name: str
    user: str | None


#: The three answers to "what resolves this record's credential", one per
#: record (see the module docstring). `ModelProviderBinding.credential_source`
#: returns one of them.
CREDENTIAL_FROM_BROKER = "broker"
CREDENTIAL_FROM_BUILT_IN_RESOLVER = "built-in-resolver"
NO_CREDENTIAL = "no-credential"
CREDENTIAL_SOURCES: tuple[str, ...] = (
    CREDENTIAL_FROM_BROKER, CREDENTIAL_FROM_BUILT_IN_RESOLVER, NO_CREDENTIAL)

#: The CLOSED dialect vocabulary a binding may declare — the request grammar the
#: provider client speaks at the declared endpoint. CLOSED rather than open
#: because an UNKNOWN dialect must REFUSE rather than be guessed at: sending an
#: assembled prompt to an endpoint whose grammar this client does not know is a
#: paid call that cannot succeed. A member joins here and an arm joins beside the
#: others in `doxbench_provider`; the check is never loosened.
#:
#: TWO MEMBERS, and the second joined exactly that way (#1144 box 16.1; plan 034
#: T078):
#:
#:   * `xfactory-prompt-v1` — this repository's own already-declared turn shape,
#:     a POST of a model and a prompt answered by an `assistant_prose`, which is
#:     the shape `doxbench_model.dispatch_turn` validates on the way back. It
#:     stays FIRST, and it is unchanged byte for byte;
#:   * `openai-chat-v1` — the OpenAI-compatible chat-completions grammar: a
#:     request of a model and a list of messages, answered by the content of
#:     the first choice's message. It is what a hosted API and the usual local
#:     server both speak, which the first member does not. Its arm is in
#:     `doxbench_provider` alone, beside the first one's.
#:
#: THE VOCABULARY LIVES HERE, on the record that declares it, and
#: `doxbench_provider` reads it from this module — so an unknown dialect is
#: refused when an operator DECLARES the binding rather than when a turn fails.
DIALECT_XFACTORY_PROMPT_V1 = "xfactory-prompt-v1"
DIALECT_OPENAI_CHAT_V1 = "openai-chat-v1"
DIALECTS: tuple[str, ...] = (DIALECT_XFACTORY_PROMPT_V1, DIALECT_OPENAI_CHAT_V1)

#: The URL schemes a declared endpoint may carry. `http://` is permitted for the
#: on-this-host proxy posture an operator may legitimately run; a scheme this
#: tuple does not name is refused at declaration, because `file://` or a bare
#: host is not something a provider client should discover at dispatch time.
#: For a credential the built-in resolver reads, "on this host" is ENFORCED
#: (`is_a_private_route`). A broker's minted token and the auth kind `none`
#: keep the posture this tuple gives them, as the 2026-09-28 ruling leaves it.
ENDPOINT_SCHEMES: tuple[str, ...] = ("https://", "http://")

#: The hosts a credential the built-in resolver reads may reach over plain
#: `http://`: this host, spelled exactly as Brett Heap's ruling of 2026-09-28
#: names it ("Refuse unless loopback"). No other spelling of these addresses,
#: and no other address of the loopback range, is one of them.
LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1", "::1", "localhost")


def _authority(host: str) -> str:
    """`host` as a URL's authority spells it: an IPv6 literal is bracketed."""
    return f"[{host}]" if ":" in host else host


#: A PRIVATE ROUTE: `https://` to any host, or `http://` to one of
#: `LOOPBACK_HOSTS`, with an optional port, then the path, the query, the
#: fragment or nothing at all. It is matched against the endpoint AS WRITTEN,
#: not against a parser's reading of it. A URL parser and the HTTP client read
#: `http://evil.example\@localhost/` as two different hosts, and only the
#: client's reading decides where the key would go. It is case-blind, because
#: a scheme and a host name are: `HTTP://` is `http://`.
_PRIVATE_ROUTE = re.compile(
    r"https://|http://(?:"
    + "|".join(re.escape(_authority(host)) for host in LOOPBACK_HOSTS)
    + r")(?::[0-9]{1,5})?(?:[/?#]|\Z)",
    re.IGNORECASE | re.ASCII)


def is_a_private_route(endpoint: object) -> bool:
    """Whether `endpoint` keeps a credential from crossing a network in
    cleartext: `https://`, or `http://` to this host (`LOOPBACK_HOSTS`).

    ONE PREDICATE. The record asks it when a binding is declared, and
    `doxbench_provider`'s built-in resolver asks it again before it reads
    anything."""
    return (isinstance(endpoint, str)
            and _PRIVATE_ROUTE.match(endpoint) is not None)


#: The refusal a credential the built-in resolver reads earns on a route that
#: is not private (Brett Heap's ruling of 2026-09-28, "Refuse unless
#: loopback"). That resolver reads a LONG-LIVED key, where a broker mints a
#: short-lived token, so plain `http://` carries one only to this host. A
#: fixed sentence, and it repeats nothing of the endpoint.
ENDPOINT_NOT_PRIVATE = (
    "a credential the built-in resolver reads (an env: or keyring: reference) "
    "is sent only over https://, or over http:// to this host (127.0.0.1, ::1 "
    "or localhost), and this endpoint is neither; declare an https:// "
    "endpoint, or a loopback one")

#: The refusal a key inside the endpoint URL earns (#1144 box 16.3). Measured
#: before 16.3: this record checked the endpoint's scheme and nothing else, so
#: `https://user:<key>@…` and `…?api_key=<key>` were both ACCEPTED, into a file
#: this module calls safe to commit. A FIXED sentence, composed from nothing
#: the operator typed: the URL it refuses carries the key, and a refusal that
#: repeated the URL would print the key to a terminal, a log, or, through the
#: console's intake route, a browser.
ENDPOINT_CARRIES_A_CREDENTIAL = (
    "the endpoint carries a credential (a user name or password in the URL, or "
    "a credential-shaped query or fragment parameter), and a binding is safe to "
    "commit only because it holds none; declare the endpoint without it, and "
    "name the credential by its reference in credential_ref")

#: The refusal an endpoint longer than the product's URL bound earns (#1144 box
#: 16.3; Copilot's overview of openDox-code#63). The detector below is
#: quadratic in a parameter name's length, and an endpoint reaches it from an
#: operator's command line or from the console's intake route, so the
#: endpoint's length is checked before the detector is asked. The bound is the
#: product's own, `runtime/config.MAX_REMOTE_URL_CHARS`, which the repository
#: act applies to a remote for the same reason. Like the refusal above, this
#: one never repeats the endpoint. The only number in it is the product's
#: bound.
ENDPOINT_TOO_LONG = (
    "the endpoint is longer than {bound} characters and is refused unread: "
    "the credential check is quadratic in what it is given, and no provider "
    "endpoint is this long")


def _endpoint_bound() -> int:
    """`runtime/config.MAX_REMOTE_URL_CHARS`, read where it is asked. It is
    imported there for the same reason as the detector below, so this module
    stays light at import time. `runtime/config` is stdlib-only by the runtime
    package's import-weight contract."""
    from opendox.runtime import config

    return config.MAX_REMOTE_URL_CHARS


def _carries_a_credential(text: str) -> bool:
    """The product's ONE detector, `runtime/local_git_adapter.
    carries_a_credential`, which #1144 box 16.3 names: it flags a URL with
    userinfo and a URL with a credential-shaped parameter, and passes a clean
    one.

    Asked here rather than re-derived, so the record and the repository act
    cannot disagree about the same bytes. Imported where it is asked, as
    `authoring.py` imports from the same module, so this module stays light at
    import time. `local_git_adapter` is stdlib-only by the runtime package's
    own import-weight contract, so the lean hosted image imports it too."""
    from opendox.runtime.local_git_adapter import carries_a_credential

    return carries_a_credential(text)

#: The exact, ordered field list a binding declares. Nothing else may appear in
#: a stored record, and nothing else appears in a read-back.
#:
#: WIDENED BY THE RECONCILIATION (task 2.6) from five to nine, and every one of
#: the four is a fact openProfiler's declaration says the CONSUMER owns:
#: `provider` and `approved_by` are REQUIRED flags of the declared `intake`
#: (`--provider`, `--approved-by`; the second because `credential-contracts`
#: holds that a grant without an approver is invalid), and `endpoint`/`dialect`
#: are the provider route the mint answer deliberately does not carry.
#:
#: AND FROM NINE TO TEN BY #1144 box 16.2 (plan 034 T079): `model`, the model
#: name the provider receives as the request's model. It sits with the route
#: it belongs to, after `dialect`. Before it, the request named the catalog
#: handle, which is this binding's `id`, so no provider model could be named.
#: STILL NO SECRET FIELD: ten fields, and the absence of an eleventh is the
#: same point the absence of a sixth was.
BINDING_FIELDS: tuple[str, ...] = (
    "id",
    "label",
    "provider",
    "credential_ref",
    "auth_kind",
    "approved_by",
    "endpoint",
    "dialect",
    "model",
    "broker_argv",
)

#: The one field EVERY stored record may leave out. A record without `model` was
#: declared before the field existed, and it keeps the meaning it had: the
#: request names the catalog handle, this binding's `id`. A record may also
#: leave out the fields its own resolver forbids or does not need (#1144 box
#: 16.3; `_fields_its_resolver_leaves_out`). Every other field is required, as
#: it always was.
OPTIONAL_BINDING_FIELDS: tuple[str, ...] = ("model",)

#: The CLOSED placeholder vocabulary an argv template may name. Every member is
#: a field of the binding itself, which is the property that matters: a template
#: can only ever be filled with facts the binding already discloses, so no
#: substitution can smuggle a value the record does not carry. A template naming
#: anything outside this set is refused at construction rather than at
#: execution — an operator finds out when they declare the binding, not when a
#: turn fails. `model` is not a member: a broker's invocation is about custody,
#: never about which model a turn asks for, and an undeclared model has no
#: value to fill a placeholder with.
ARGV_PLACEHOLDERS: tuple[str, ...] = (
    "binding_id", "label", "provider", "credential_ref", "auth_kind",
    "approved_by", "endpoint", "dialect")

#: The fixed sentence a read-back states about custody (task 1.2: "read-back
#: discloses the binding and states plainly that the credential lives in the
#: broker"). A MODULE CONSTANT, composed from nothing an operator supplied, so
#: every surface that discloses a binding says the same thing.
CUSTODY_NOTICE = (
    "the credential itself is held by the broker this binding names; this "
    "dashboard stores only the reference above and can disclose nothing more")

#: The same sentence for a record the BUILT-IN RESOLVER answers (#1144 box
#: 16.3). The broker sentence would be false there, and a read-back states
#: custody PLAINLY, so each resolver has its own sentence.
BUILT_IN_CUSTODY_NOTICE = (
    "the credential itself stays where the reference above names, in this "
    "process's environment or the OS keyring; it is read at call time for each "
    "request and never stored, and this dashboard stores only the reference")

#: ...and for a record whose endpoint takes no credential (the auth kind
#: `none`).
NO_CREDENTIAL_NOTICE = (
    "this endpoint takes no credential (auth kind none), so there is nothing "
    "to hold and nothing to disclose")

#: Where a checkout's bindings live when nothing said otherwise. Beside the gate
#: records, under the served checkout, because a binding IS safe to commit and
#: an operator reading their repository should be able to see what their install
#: is bound to. Never a home directory and never a hidden state dir: an install
#: whose model provider is invisible to its own repository is the posture this
#: record exists to end.
DEFAULT_BINDINGS_RELPATH = "ideation/dashboard/model-provider-bindings.yaml"


class BindingRefused(ValueError):
    """A binding, a store document, or an argv substitution is not
    well-formed. ONE exception class for every refusal this module raises, so a
    caller declaring a binding has exactly one thing to catch."""


def _require_non_blank_str(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise BindingRefused(
            f"{field} must be a str, got {type(value).__name__}")
    if not value.strip():
        raise BindingRefused(f"{field} must not be blank")
    return value


def names_a_built_in_form(credential_ref: object) -> bool:
    """Whether a reference is in one of `BUILT_IN_REFERENCE_FORMS`, by its
    prefix alone (#1144 box 16.3). A reference that is not is a broker's."""
    return (isinstance(credential_ref, str)
            and credential_ref.startswith(BUILT_IN_REFERENCE_FORMS))


def built_in_reference_parts(credential_ref: str) -> BuiltInReference | None:
    """A reference the built-in resolver takes, split into what it looks up:
    `BuiltInReference("env:", NAME, None)` or
    `BuiltInReference("keyring:", SERVICE, USERNAME)`. None for a broker's
    reference.

    ONE PARSER, which the record calls when a binding is declared and
    `doxbench_provider`'s resolver calls at call time, so the two cannot
    disagree about a reference's form. A reference that names a built-in form
    but is malformed is REFUSED, at declaration. The refusal does not repeat
    the reference: a key pasted where its reference belongs would otherwise be
    printed by the very check that refused it."""
    if credential_ref.startswith(CREDENTIAL_REF_ENV):
        name = credential_ref[len(CREDENTIAL_REF_ENV):]
        if not _ENV_NAME.fullmatch(name):
            raise BindingRefused(
                "credential_ref uses the env: form, and what follows env: is "
                "not an environment variable name (a letter or _, then "
                "letters, digits or _)")
        return BuiltInReference(CREDENTIAL_REF_ENV, name, None)
    if credential_ref.startswith(CREDENTIAL_REF_KEYRING):
        service, separator, username = (
            credential_ref[len(CREDENTIAL_REF_KEYRING):].rpartition("/"))
        if not separator or not service.strip() or not username.strip():
            raise BindingRefused(
                "credential_ref uses the keyring: form, and it does not read "
                "keyring:SERVICE/USERNAME with both parts present")
        return BuiltInReference(CREDENTIAL_REF_KEYRING, service, username)
    return None


def _fields_its_resolver_leaves_out(record: Mapping) -> set[str]:
    """The fields a stored record may leave out because its own resolver
    forbids or does not need them (#1144 box 16.3). Under the auth kind `none`
    these are `credential_ref` and `broker_argv`. Beside a reference the
    built-in resolver takes, it is `broker_argv`.

    Leaving a field out is not declaring it, which is why a record may. A
    record that DECLARES one is refused by the binding itself, which is the
    rule. This only says which absences are lawful."""
    if record.get("auth_kind") == AUTH_KIND_NONE:
        return {"credential_ref", "broker_argv"}
    if names_a_built_in_form(record.get("credential_ref")):
        return {"broker_argv"}
    return set()


@dataclasses.dataclass(frozen=True, slots=True)
class ModelProviderBinding:
    """ONE model provider, as settings hold it.

    Ten fields, and the absence of an eleventh is the point (see the module
    docstring). `broker_argv` is the DECLARED BASE invocation as a tuple of argv
    members — argv, never a shell string, so no operator's label and no
    credential reference can ever be read as shell syntax. It names the program
    and its fixed leading arguments and NOT the operation: the operation is a
    declared subcommand `doxbench_provider` appends.

    `model` (#1144 box 16.2) is the model name the provider receives as the
    request's model. It is KEYWORD-ONLY and defaults to None, so every
    construction written before it existed still builds the binding it built.
    That binding keeps its old meaning: with no model declared, the request
    names the catalog handle, which is the binding's `id`, exactly as before.
    A declared model is a non-blank string.

    ONE RESOLVER PER RECORD (#1144 box 16.3; see the module docstring). Under
    the auth kind `none`, `credential_ref` is None and `broker_argv` is empty,
    and giving either is refused. A reference the built-in resolver takes
    needs no broker, so `broker_argv` is empty there, and a broker given
    beside it is refused. Any other reference is a broker's, and it needs its
    `broker_argv`, as it always did.
    """

    id: str
    label: str
    provider: str
    credential_ref: str | None
    auth_kind: str
    approved_by: str
    endpoint: str
    dialect: str
    model: str | None = dataclasses.field(default=None, kw_only=True)
    broker_argv: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("id", "label", "provider", "auth_kind", "approved_by",
                      "endpoint", "dialect"):
            _require_non_blank_str(field, getattr(self, field))
        if self.model is not None:
            _require_non_blank_str("model", self.model)
        if self.auth_kind not in AUTH_KINDS:
            raise BindingRefused(
                f"auth_kind {self.auth_kind!r} is outside the closed "
                f"vocabulary {AUTH_KINDS}")
        if self.dialect not in DIALECTS:
            raise BindingRefused(
                f"dialect {self.dialect!r} is outside the closed vocabulary "
                f"{DIALECTS}; an unknown request grammar is refused at "
                "DECLARATION rather than guessed at on a paid call")
        # A KEY INSIDE THE URL IS REFUSED FIRST (#1144 box 16.3), so no later
        # refusal, the scheme's among them, can repeat a URL that carries one.
        # The length is checked before that, because the detector's work grows
        # with the square of what it is given.
        if len(self.endpoint) > _endpoint_bound():
            raise BindingRefused(ENDPOINT_TOO_LONG.format(
                bound=_endpoint_bound()))
        if _carries_a_credential(self.endpoint):
            raise BindingRefused(ENDPOINT_CARRIES_A_CREDENTIAL)
        if not self.endpoint.startswith(ENDPOINT_SCHEMES):
            raise BindingRefused(
                f"endpoint {self.endpoint!r} does not name one of "
                f"{ENDPOINT_SCHEMES}")
        if isinstance(self.broker_argv, (str, bytes)):
            raise BindingRefused(
                "broker_argv must be a sequence of argv members, not a single "
                f"{type(self.broker_argv).__name__} — a shell string would let "
                "a declared value be read as shell syntax")
        try:
            argv = tuple(str(member) for member in self.broker_argv)
        except TypeError as error:
            raise BindingRefused(
                "broker_argv must be an iterable of argv members, got "
                f"{type(self.broker_argv).__name__}") from error
        object.__setattr__(self, "broker_argv", argv)
        for member in argv:
            _require_non_blank_str("broker_argv member", member)
            for name in _placeholder_names(member):
                if name not in ARGV_PLACEHOLDERS:
                    raise BindingRefused(
                        f"broker_argv names the placeholder {{{name}}}, which "
                        f"is outside the closed vocabulary {ARGV_PLACEHOLDERS}")
        self._require_one_resolver(argv)
        # A CREDENTIAL THE BUILT-IN RESOLVER READS TRAVELS ONLY BY A PRIVATE
        # ROUTE (the 2026-09-28 ruling). A broker's minted token and the auth
        # kind `none` keep the route they had.
        if (self.credential_source() == CREDENTIAL_FROM_BUILT_IN_RESOLVER
                and not is_a_private_route(self.endpoint)):
            raise BindingRefused(ENDPOINT_NOT_PRIVATE)

    def _require_one_resolver(self, argv: tuple[str, ...]) -> None:
        """#1144 box 16.3: exactly one thing answers this record's credential.

        THE `none` HALF IS RULED (R1Q18 (a)): an endpoint that takes no
        credential declares `none`, and under it the reference and the broker
        are both forbidden. THE BUILT-IN HALF is RULED in part: R1Q17 (b) says
        a record whose reference the built-in resolver takes needs no broker.
        Refusing a broker given BESIDE such a reference is plan 034's own
        fail-closed reading, which no answer rules (its analyze round 2,
        V2-21), and openxFactory#656 comment 5851950767 records it as standing,
        not overruled. A record with two resolvers would leave which one
        answers to whoever reads it next."""
        if self.auth_kind == AUTH_KIND_NONE:
            if self.credential_ref is not None:
                raise BindingRefused(
                    f"auth_kind {AUTH_KIND_NONE!r} declares an endpoint that "
                    "takes no credential, so credential_ref is forbidden "
                    "under it")
            if argv:
                raise BindingRefused(
                    f"auth_kind {AUTH_KIND_NONE!r} declares an endpoint that "
                    "takes no credential, so broker_argv is forbidden under "
                    "it: there is no credential for a broker to hold")
            return
        if self.credential_ref is None:
            raise BindingRefused(
                f"auth_kind {self.auth_kind!r} takes a credential, so "
                "credential_ref must name its reference; an endpoint that "
                f"takes no credential declares the auth kind "
                f"{AUTH_KIND_NONE!r} instead")
        _require_non_blank_str("credential_ref", self.credential_ref)
        if built_in_reference_parts(self.credential_ref) is not None:
            if argv:
                raise BindingRefused(
                    "credential_ref is a reference the built-in resolver "
                    "takes, so this binding needs no broker; a broker_argv "
                    "beside it would give one record two resolvers")
            return
        if not argv:
            raise BindingRefused(
                "broker_argv must name the broker command; an empty invocation "
                "is a binding that can never mint")

    def credential_source(self) -> str:
        """Which of `CREDENTIAL_SOURCES` answers this record's credential: the
        broker it names, the built-in resolver, or nothing (the auth kind
        `none`). `doxbench_provider` routes a turn by it, and the read-back
        states custody by it."""
        if self.auth_kind == AUTH_KIND_NONE:
            return NO_CREDENTIAL
        if names_a_built_in_form(self.credential_ref):
            return CREDENTIAL_FROM_BUILT_IN_RESOLVER
        return CREDENTIAL_FROM_BROKER

    def custody_notice(self) -> str:
        """The fixed custody sentence that is TRUE of this record."""
        return {CREDENTIAL_FROM_BROKER: CUSTODY_NOTICE,
                CREDENTIAL_FROM_BUILT_IN_RESOLVER: BUILT_IN_CUSTODY_NOTICE,
                NO_CREDENTIAL: NO_CREDENTIAL_NOTICE}[self.credential_source()]

    def removal_notice(self) -> str:
        """The fixed sentence a removal of this record states."""
        return {CREDENTIAL_FROM_BROKER: REMOVAL_NOTICE,
                CREDENTIAL_FROM_BUILT_IN_RESOLVER: BUILT_IN_REMOVAL_NOTICE,
                NO_CREDENTIAL: NO_CREDENTIAL_REMOVAL_NOTICE,
                }[self.credential_source()]

    # -- projections --------------------------------------------------------

    def as_record(self) -> dict:
        """The STORED record: the record kind, then exactly ``BINDING_FIELDS``
        in order. `broker_argv` becomes a list because that is what YAML round
        trips. An undeclared `model` is written as null, as is the absent
        `credential_ref` of an auth-kind-`none` record, and a record that
        names no broker writes an empty `broker_argv`. So every stored record
        carries all ten keys; nothing else changes shape."""
        return {
            "kind": BINDING_KIND,
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "credential_ref": self.credential_ref,
            "auth_kind": self.auth_kind,
            "approved_by": self.approved_by,
            "endpoint": self.endpoint,
            "dialect": self.dialect,
            "model": self.model,
            "broker_argv": list(self.broker_argv),
        }

    def as_read_back(self) -> dict:
        """The DISCLOSED binding (task 1.2): the stored record plus the fixed
        custody sentence, and nothing else.

        There is no credential material to redact here, which is the whole
        claim: a read-back cannot leak a secret it was never able to hold. The
        sentence says so in words rather than leaving the absence to be
        inferred from a missing key. It is the sentence that is true of THIS
        record's resolver (#1144 box 16.3): the broker's, the built-in
        resolver's, or none."""
        disclosed = self.as_record()
        disclosed["credential_custody"] = self.custody_notice()
        return disclosed

    def substituted_argv(self) -> tuple[str, ...]:
        """The declared BASE invocation with its placeholders filled from this
        binding's own fields.

        PURE, and it is here rather than in the executing module on purpose:
        substitution is a fact about the record, so it can be asserted without
        spawning anything.

        THIS IS A PREFIX, NOT A WHOLE COMMAND (task 2.6). `doxbench_provider`
        appends the DECLARED subcommand and its declared flags —
        openProfiler `docs/broker-cli.md` § "CLI surface" — and executes the
        result. The operator declares the program; the declaration declares the
        verbs."""
        values = {
            "binding_id": self.id,
            "label": self.label,
            "provider": self.provider,
            "credential_ref": self.credential_ref,
            "auth_kind": self.auth_kind,
            "approved_by": self.approved_by,
            "endpoint": self.endpoint,
            "dialect": self.dialect,
        }
        return tuple(_substitute(member, values) for member in self.broker_argv)

    @classmethod
    def from_record(cls, record: object) -> "ModelProviderBinding":
        """Build a binding from a stored mapping, refusing an unknown key.

        Refusing rather than ignoring: a record carrying a key this shape does
        not know is a record written against a different contract, and silently
        dropping it would let a field an operator believed they had declared
        (a secret, most dangerously) vanish without a word."""
        if not isinstance(record, Mapping):
            raise BindingRefused(
                f"a binding record must be a mapping, got "
                f"{type(record).__name__}")
        permitted = {"kind", *BINDING_FIELDS}
        unknown = sorted(set(record) - permitted)
        if unknown:
            raise BindingRefused(
                f"a binding record declares unknown keys {unknown}; this shape "
                f"holds exactly {list(BINDING_FIELDS)} and no credential field "
                "exists in it")
        declared_kind = record.get("kind", BINDING_KIND)
        if declared_kind != BINDING_KIND:
            raise BindingRefused(
                f"a binding record declares kind {declared_kind!r}, not "
                f"{BINDING_KIND!r}")
        may_leave_out = {*OPTIONAL_BINDING_FIELDS,
                         *_fields_its_resolver_leaves_out(record)}
        missing = [field for field in BINDING_FIELDS
                   if field not in record and field not in may_leave_out]
        if missing:
            raise BindingRefused(
                f"a binding record is missing {missing}")
        broker_argv = record.get("broker_argv")
        return cls(
            id=record["id"],
            label=record["label"],
            provider=record["provider"],
            credential_ref=record.get("credential_ref"),
            auth_kind=record["auth_kind"],
            approved_by=record["approved_by"],
            endpoint=record["endpoint"],
            dialect=record["dialect"],
            model=record.get("model"),
            # an absent or null `broker_argv` names no broker. Whether that is
            # lawful is the binding's own rule (`_require_one_resolver`)
            broker_argv=() if broker_argv is None else broker_argv,
        )


def _placeholder_names(member: str) -> tuple[str, ...]:
    """Every `{name}` in one argv member, without importing a formatter.

    Hand-scanned rather than delegated to `string.Formatter` because the doubled
    braces `{{`/`}}` a formatter treats as escapes have no meaning in an argv
    member an operator wrote: `{{x}}` there is a literal the broker would
    receive with braces on it, and reading it as an escaped `{x}` would silently
    accept a template this vocabulary refuses."""
    names: list[str] = []
    rest = member
    while True:
        opened = rest.find("{")
        if opened < 0:
            return tuple(names)
        closed = rest.find("}", opened + 1)
        if closed < 0:
            raise BindingRefused(
                f"broker_argv member {member!r} opens a placeholder it never "
                "closes")
        names.append(rest[opened + 1:closed])
        rest = rest[closed + 1:]


def _substitute(member: str, values: Mapping[str, str]) -> str:
    out = member
    for name in ARGV_PLACEHOLDERS:
        out = out.replace("{" + name + "}", values[name])
    return out


#: What a store says when the interpreter running it has no YAML parser. A
#: FIXED sentence, because the caller that catches it is an entrypoint choosing
#: a posture and not a human debugging an import.
NO_YAML_NOTICE = (
    "this install has no YAML parser (PyYAML), so a bindings document cannot "
    "be read or written; the install serves its declared posture without one")


def _yaml_or_refused():
    """The YAML parser, or a `BindingRefused` — never a `ModuleNotFoundError`.

    THE LEAN HOSTED IMAGE HAS NO PyYAML (see the module docstring), and both
    entrypoints resolve their model port through this store at startup. A store
    with no document already answers without the parser; a store WITH one used
    to raise `ModuleNotFoundError` straight through
    `declared_model_port_factory`, which catches `BindingRefused` and nothing
    else — so a hosted image that had ever written a binding would have died at
    startup instead of falling back to its harness declaration. Raising the
    module's ONE refusal class is what makes that graceful fallback hold, and it
    is asserted."""
    try:
        import yaml
    except ModuleNotFoundError as error:
        raise BindingRefused(NO_YAML_NOTICE) from error
    return yaml


# ---------------------------------------------------------------------------
# the store (task 1.2: list, add, edit, remove)
# ---------------------------------------------------------------------------


class BindingStore:
    """The bindings a checkout declares, as a file of records.

    Read-through and write-through: every verb reads the document, acts, and
    writes it back, so two operator doors (a CLI verb here, a future surface
    there) cannot hold divergent in-memory copies. There is no cache to go
    stale, and a store nobody has written yet reads as an empty list rather
    than as an error — an install with no model provider is a posture, not a
    fault.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    # -- reading ------------------------------------------------------------

    def list(self) -> tuple[ModelProviderBinding, ...]:
        """Every declared binding, in declaration order."""
        return tuple(self._load())

    def get(self, binding_id: str) -> ModelProviderBinding | None:
        """One binding by id, or None. Exact match; no case folding."""
        for binding in self._load():
            if binding.id == binding_id:
                return binding
        return None

    def read_back(self) -> dict:
        """The whole store as a DISCLOSURE (task 1.2): the document's own
        identity, every binding's read-back, and the fixed custody sentence on
        each. Safe to print, safe to log, safe to paste into a review."""
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": BINDINGS_KIND,
            "bindings": [binding.as_read_back() for binding in self._load()],
        }

    # -- writing ------------------------------------------------------------

    def add(self, binding: ModelProviderBinding) -> ModelProviderBinding:
        """Declare a NEW binding. A repeated id refuses rather than replacing:
        an operator who meant to change one has `edit`, and a silent overwrite
        would retire a declaration nobody asked to retire."""
        current = list(self._load())
        if any(existing.id == binding.id for existing in current):
            raise BindingRefused(
                f"a binding with id {binding.id!r} is already declared; use "
                "edit to change it")
        current.append(binding)
        self._save(current)
        return binding

    def edit(self, binding: ModelProviderBinding) -> ModelProviderBinding:
        """Replace an EXISTING binding, in place, keeping its position. An
        unknown id refuses rather than adding: `add` is the verb for that, and
        an edit that quietly creates hides a mistyped id."""
        current = list(self._load())
        for index, existing in enumerate(current):
            if existing.id == binding.id:
                current[index] = binding
                self._save(current)
                return binding
        raise BindingRefused(
            f"no binding with id {binding.id!r} is declared; use add to "
            "declare one")

    def remove(self, binding_id: str) -> ModelProviderBinding:
        """Retire a binding. Returns the record that was removed, so a caller
        can report exactly what it retired.

        REMOVING A BINDING REMOVES NO CREDENTIAL. The credential lives in the
        broker; forgetting the reference here leaves it exactly where it was.
        That is stated by `REMOVAL_NOTICE` rather than implied, because an
        operator who believes a removal revoked something is worse off than one
        who knows it did not."""
        current = list(self._load())
        for index, existing in enumerate(current):
            if existing.id == binding_id:
                del current[index]
                self._save(current)
                return existing
        raise BindingRefused(f"no binding with id {binding_id!r} is declared")

    # -- the document ------------------------------------------------------

    def _load(self) -> list[ModelProviderBinding]:
        if not self.path.is_file():
            # THE HOSTED PATH, and the reason the import below is lazy: an
            # install with no bindings document answers here and never needs a
            # YAML parser at all.
            return []
        yaml = _yaml_or_refused()
        try:
            document = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise BindingRefused(
                f"the bindings document at {self.path} is not readable YAML"
            ) from error
        if document is None:
            return []
        if not isinstance(document, Mapping):
            raise BindingRefused(
                f"the bindings document at {self.path} is not a mapping")
        if document.get("kind") != BINDINGS_KIND:
            raise BindingRefused(
                f"the bindings document at {self.path} declares kind "
                f"{document.get('kind')!r}, not {BINDINGS_KIND!r}")
        if document.get("schema_version") != SCHEMA_VERSION:
            raise BindingRefused(
                f"the bindings document at {self.path} declares "
                f"schema_version {document.get('schema_version')!r}, not "
                f"{SCHEMA_VERSION}")
        records = document.get("bindings") or []
        if not isinstance(records, list):
            raise BindingRefused(
                f"the bindings document at {self.path} declares a non-list "
                "bindings key")
        bindings = [ModelProviderBinding.from_record(record)
                    for record in records]
        seen: set[str] = set()
        for binding in bindings:
            if binding.id in seen:
                raise BindingRefused(
                    f"the bindings document at {self.path} declares the id "
                    f"{binding.id!r} twice")
            seen.add(binding.id)
        return bindings

    def _save(self, bindings: Iterable[ModelProviderBinding]) -> None:
        yaml = _yaml_or_refused()
        document = {
            "schema_version": SCHEMA_VERSION,
            "kind": BINDINGS_KIND,
            "bindings": [binding.as_record() for binding in bindings],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
            encoding="utf-8")


#: What a removal does and does not do, stated once so no surface invents its
#: own weaker sentence.
REMOVAL_NOTICE = (
    "the binding is retired from this checkout; the credential it referenced "
    "remains in the broker's custody and is not revoked by this act")

#: The removal sentence for a record the built-in resolver answers, and for one
#: that takes no credential (#1144 box 16.3). As with custody, each resolver has
#: its own sentence, so no removal says something that is not so.
BUILT_IN_REMOVAL_NOTICE = (
    "the binding is retired from this checkout; the credential its reference "
    "named stays where it is, in the environment or the OS keyring, and is not "
    "removed by this act")
NO_CREDENTIAL_REMOVAL_NOTICE = (
    "the binding is retired from this checkout; it referred to no credential, "
    "so there is nothing to revoke")


def bindings_path(checkout_root: Path | str) -> Path:
    """The default store path for a checkout. ONE rule, so two entrypoints
    cannot drift into reading two different files."""
    return Path(checkout_root) / DEFAULT_BINDINGS_RELPATH
