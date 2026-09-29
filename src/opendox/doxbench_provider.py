"""THE ONE MODULE IN THIS REPOSITORY THAT MAY CONTACT A PROVIDER, HOLD A
MINTED TOKEN, OR HOLD A CREDENTIAL IN FLIGHT (add-model-provider-broker tasks
1.3/2.1/2.2/2.4/2.6).

Until this module existed, no provider was contacted from anywhere in this
repository, and a test read the source to keep it true. Minting means the
dashboard becomes a provider client, so the invariant NARROWS rather than
disappearing: exactly one module may hold those three things, this is that
module, it says so in its own `PROVIDER_CLIENT_MODULE` constant, and
`tests/ideation-dashboard/test_provider_boundary.py` sweeps every other module
in the package to keep the rest of the boundary exactly where it was. The views
clause stays ABSOLUTE — no browser module is exempt from anything, because a
token in a page is exfiltratable by anything able to run script there.

ONE PRECISION THE RECONCILIATION FORCED, stated rather than left to erode: the
binding RECORD now carries an `endpoint`, because openProfiler's declaration
will not name one (see below). That is a declared FACT in an operator's settings
document, validated by `doxbench_binding`, and it is not a transport: no module
but this one opens a socket, imports an HTTP client, or holds a token to put on
one, and the structural sweep is unchanged. "Holds a provider endpoint" as the
boundary test means it — a provider host or path written into source — remains
true of this module alone.

WHAT HAPPENS HERE, in the order a turn meets it:

  * the BROKER is invoked — the binding's declared BASE argv plus the DECLARED
    subcommand and flags, executed with a scrubbed environment. Four operations,
    exactly the four openProfiler declares: INTAKE hands a human's credential to
    the broker on standard input and keeps the `reference` it returns; MINT asks
    for a short-lived token and gets back the token, its `expires_at` and the
    `audit_ref` that names the issuance; REVOKE destroys custody; LIST reads the
    non-secret reference index;
  * the PROVIDER is called with that token, server-side, from the loopback
    console process. Brett's ruling of 2026-08-08: the broker mints, doxBench
    calls, because a broker in the request path adds a hop to every turn and to
    every chunk of a streamed one. WHERE to call and WHAT GRAMMAR to speak are
    the BINDING's — the broker's declaration emits neither, deliberately. Each
    grammar the binding may declare has one arm here (`_DIALECT_ARMS`): this
    repository's own prompt grammar, and the OpenAI-compatible chat-completions
    grammar (#1144 box 16.1);
  * OR NO BROKER AT ALL (#1144 box 16.3). A record whose reference is
    `env:NAME` or `keyring:SERVICE/USERNAME` is answered by the BUILT-IN
    RESOLVER below, at call time and in this module only (RULED R1Q17 (b)).
    The reference is read for the one request that presents it, and nothing
    is minted, cached or stored. A record with the auth kind `none` presents
    no credential at all (RULED R1Q18 (a));
  * EXPIRY is handled by the 2026-08-26 ruling: re-mint and retry ONCE, with the
    re-mint and the paid retry visibly recorded, and a second expiry inside one
    turn surfaces the standard refusal rather than buying a third call. The
    re-mint carries `--retry-of <audit_ref>`, so the correlation exists on the
    BROKER's side of the seam too and a retry never reads as an unrelated
    second issuance.

WHAT NEVER HAPPENS HERE:

  * a credential is never held beyond the one call that uses it.
    `hand_off_credential` streams the human's value from an open source
    straight into the broker's standard input and never materialises it as a
    value of its own — no variable that outlives the call, no file, no echo in
    a return value, and nothing in any exception. The built-in resolver's
    value, the one exception 16.3 makes, is read at call time, presented in
    that request's authorization header, and dropped with the call. It is
    never cached on the port, written, logged, returned, or put in an
    exception;
  * a minted token is never written to a file, never placed in a response,
    never logged, and never survives the process. `MintedToken` carries a
    redacting `__repr__`, so even a traceback frame or a debugger `print` of the
    object discloses nothing;
  * a broker's or a provider's own words never reach a caller. Every refusal
    this module raises carries one of the FIXED sentences below, composed from
    nothing the broker or the provider said, so `doxbench_model.dispatch_turn`
    maps it onto the same redacted `model_failed` every other adapter failure
    already maps onto.

THE PROGRAM IS DECLARED; THE VERBS ARE THE DECLARATION'S (task 2.6). This was
written while openProfiler was unbuilt, so it named the operation in a JSON
request document of its own invention and demanded an answer shape to match. The
declaration landed (`opensoft/openProfiler`, `docs/broker-cli.md`, main
`d0538c31`) and named six incompatibilities, recorded in tasks.md 0.2; this
module is now reconciled against it and proven against the real
`openprofiler-broker` binary.

What that means in practice, and where the line falls:

  * the BINDING still declares the program and its fixed leading arguments, so
    NO command path appears in this file and an operator who moves the broker
    changes a record rather than code;
  * the SUBCOMMANDS and FLAGS are the declaration's own closed vocabulary and
    are recorded here — `intake`/`mint`/`revoke`/`list`, `--binding`,
    `--provider`, `--auth-kind`, `--approved-by`, `--label`, `--reference`,
    `--retry-of`. They are not the operator's to respell: four argv templates in
    a settings file is four ways to get the declaration subtly wrong. Every
    constant below cites the section of `docs/broker-cli.md` it comes from;
  * the ANSWER shapes are the declaration's too, parsed EXACTLY (see
    `_answer_document`).
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime, timezone

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_bridge as bridge_mod
from opendox import doxbench_model as model_mod

#: THIS MODULE'S OWN NAME, declared so the structural boundary test and the
#: module cannot drift into naming two different files. The test asserts the
#: two are equal and that this file really is the one holding the transport, so
#: the exemption can never become vacuous.
PROVIDER_CLIENT_MODULE = "doxbench_provider.py"

# ---------------------------------------------------------------------------
# THE DECLARED BROKER SURFACE (task 2.6; openProfiler `docs/broker-cli.md`)
#
# Every constant in this block is a quotation, not a choice. The citation on
# each names the section of the declaration it was read from, at openProfiler
# main `d0538c31`, and each is asserted against the real binary by
# `tests/ideation-dashboard/test_openprofiler_broker_e2e.py`.
# ---------------------------------------------------------------------------

#: § "CLI surface" — the operation is an argv SUBCOMMAND. CLOSED: the
#: declaration names four and this seam expresses four.
OPERATION_INTAKE = "intake"
OPERATION_MINT = "mint"
OPERATION_REVOKE = "revoke"
OPERATION_LIST = "list"
OPERATIONS: tuple[str, ...] = (
    OPERATION_INTAKE, OPERATION_MINT, OPERATION_REVOKE, OPERATION_LIST)

#: § "intake" and § "mint" — the declared flag names. Spelled once, here.
FLAG_BINDING = "--binding"
FLAG_PROVIDER = "--provider"
FLAG_AUTH_KIND = "--auth-kind"
FLAG_APPROVED_BY = "--approved-by"
FLAG_LABEL = "--label"
FLAG_REFERENCE = "--reference"
FLAG_RETRY_OF = "--retry-of"

#: § "Output discipline" — every answer object carries this `schema_version`.
BROKER_ANSWER_SCHEMA_VERSION = 1

#: § "intake" / "mint" / "revoke" / "list" — the answer kinds.
BROKER_INTAKE_KIND = "openprofiler_broker_intake"
BROKER_MINT_KIND = "openprofiler_broker_mint"
BROKER_REVOCATION_KIND = "openprofiler_broker_revocation"
BROKER_REFERENCE_LIST_KIND = "openprofiler_broker_reference_list"

#: § "intake" — the intake answer's keys, EXACTLY. `label` is present and null
#: when none was given, so it is a key of every answer rather than an optional
#: one. The credential appears in none of them, which is the point of storing
#: exactly this.
INTAKE_FIELDS: tuple[str, ...] = (
    "schema_version", "kind", "reference", "binding", "provider", "auth_kind",
    "label", "created_at", "max_lifetime_seconds", "issued_by", "approved_by",
    "audit_ref")

#: § "mint" — the mint answer's keys, EXACTLY. NEITHER `endpoint` NOR `dialect`
#: is here, and that is the declaration's deliberate refusal to name a route it
#: would then be accountable for (0.2 FINDING 3): both facts come from the
#: BINDING. `retry_of` is present and null on a first mint.
MINT_FIELDS: tuple[str, ...] = (
    "schema_version", "kind", "reference", "binding", "provider", "auth_kind",
    "token", "token_type", "issued_at", "expires_at", "expires_in_seconds",
    "scope", "issued_by", "approved_by", "audit_ref", "retry_of",
    "enforcement")

#: § "revoke" — the revocation answer's keys, EXACTLY.
REVOCATION_FIELDS: tuple[str, ...] = (
    "schema_version", "kind", "reference", "binding", "provider", "auth_kind",
    "revoked", "revoked_at", "audit_ref")

#: § "list" — the reference-index answer's keys, EXACTLY.
REFERENCE_LIST_FIELDS: tuple[str, ...] = (
    "schema_version", "kind", "references")

#: The dialect vocabulary, READ FROM THE BINDING MODULE that now declares it
#: (0.2 FINDING 3: the route is the consumer's fact, so the record that carries
#: it is the record that validates it). Aliased rather than respelled so the two
#: modules cannot drift into two vocabularies. An unknown dialect is refused
#: when an operator DECLARES the binding — earlier than a mint, and earlier than
#: a paid call. Each member has exactly one ARM below (`_DIALECT_ARMS`).
DIALECT_XFACTORY_PROMPT_V1 = binding_mod.DIALECT_XFACTORY_PROMPT_V1
DIALECT_OPENAI_CHAT_V1 = binding_mod.DIALECT_OPENAI_CHAT_V1
DIALECTS: tuple[str, ...] = binding_mod.DIALECTS

#: How long a broker invocation may take. A mint is a local process doing local
#: custody work; a broker that cannot answer in this long is a broker that
#: cannot answer.
BROKER_TIMEOUT_SECONDS = 30.0

#: The largest answer a broker may write. A bound, not a policy: an unbounded
#: read of a child's stdout is a way to spend this process's memory by
#: misconfiguring a binding.
MAX_BROKER_ANSWER_BYTES = 65_536

#: The largest PROVIDER answer this client will read, bounding what was an
#: unbounded `response.read()` (PR #392 review note b). REUSED rather than
#: newly chosen: `doxbench_model.SERVER_MAX_OUTPUT_LIMIT_BYTES` is this server's
#: own declared output ceiling, and a body larger than the largest answer the
#: seam could ever accept is a body there is no reason to page into memory. An
#: overflow lands on the same fixed `DIAG_PROVIDER_MALFORMED` every other
#: unusable provider answer lands on — a body this client cannot use is
#: malformed for its purposes, and inventing a tenth sentence for it would tell
#: a caller something the redaction discipline says it must not.
MAX_PROVIDER_ANSWER_BYTES = model_mod.SERVER_MAX_OUTPUT_LIMIT_BYTES

# ---------------------------------------------------------------------------
# fixed, redacted refusals (the shape `dispatch_turn` already defines)
# ---------------------------------------------------------------------------

#: Every sentence this module may raise, composed from NOTHING the broker or
#: the provider said. A broker's stderr, a provider's error body and an
#: exception's text are all dropped unread at the boundary that observes them,
#: exactly as `dispatch_turn` drops a provider exception's text.
DIAG_BROKER_UNREACHABLE = (
    "the credential broker could not be started, so no token could be minted")
DIAG_BROKER_REFUSED = (
    "the credential broker refused, so no token could be minted")
DIAG_BROKER_MALFORMED = (
    "the credential broker's answer did not match the declared mint contract")
DIAG_BROKER_TIMEOUT = (
    "the credential broker did not answer within the declared timeout")
DIAG_PROVIDER_UNREACHABLE = (
    "the provider could not be reached and its details are withheld by design")
DIAG_PROVIDER_REFUSED = (
    "the provider refused and its details are withheld by design")
DIAG_PROVIDER_MALFORMED = (
    "the provider response did not match the expected shape")
DIAG_TOKEN_EXPIRED_TWICE = (
    "the minted token expired twice within one turn; a further paid call is "
    "not made on a turn that has already been retried once")

#: The built-in resolver's two refusals (#1144 box 16.3). Fixed, like every
#: other sentence here: they name no variable, no service and no user, so a
#: reference an operator mistyped is not repeated wherever the refusal goes.
DIAG_REFERENCE_UNRESOLVED = (
    "the credential reference resolved to no usable credential, so none was "
    "presented")
DIAG_KEYRING_UNAVAILABLE = (
    "the OS keyring could not be read by this process, so the keyring "
    "reference could not be resolved")

#: The answer to a redirect of a request that carried a credential: a broker's
#: minted token, or what the built-in resolver read. That request follows no
#: redirect (see `_DeclineRedirects`), so the credential went to the declared
#: endpoint and nowhere else, and the sentence says what to declare instead.
DIAG_PROVIDER_REDIRECTED = (
    "the provider answered with a redirect, which a request carrying a "
    "credential does not follow, so the credential was sent nowhere else; "
    "declare the endpoint the provider redirects to")

#: The closed set, so a test can assert no other sentence can be raised.
#: ELEVEN: the eight the reconciliation left, the built-in resolver's two
#: (#1144 box 16.3), and the redirect a request carrying a credential
#: declines. `DIAG_DIALECT_UNKNOWN` is gone because the fact it guarded
#: moved: the dialect is the BINDING's, validated against the closed vocabulary
#: when the operator declares it
#: (`doxbench_binding.ModelProviderBinding.__post_init__`), so an unknown
#: grammar can no longer reach a mint. Keeping a sentence here that no path can
#: raise would be a refusal nobody can trigger, asserted by a test that proves
#: nothing.
FIXED_DIAGNOSTICS: frozenset[str] = frozenset({
    DIAG_BROKER_UNREACHABLE, DIAG_BROKER_REFUSED, DIAG_BROKER_MALFORMED,
    DIAG_BROKER_TIMEOUT, DIAG_PROVIDER_UNREACHABLE,
    DIAG_PROVIDER_REFUSED, DIAG_PROVIDER_MALFORMED, DIAG_TOKEN_EXPIRED_TWICE,
    DIAG_REFERENCE_UNRESOLVED, DIAG_KEYRING_UNAVAILABLE,
    DIAG_PROVIDER_REDIRECTED,
})


class BrokerRefused(RuntimeError):
    """A broker or a provider could not answer, stated in one of
    ``FIXED_DIAGNOSTICS`` and nothing else.

    Deliberately carries no payload, no status code, no stderr and no response
    body: there is no attribute a caller could log that discloses provider or
    broker detail, which is the same discipline `TurnDispatchFailure` keeps."""

    def __init__(self, diagnostic: str) -> None:
        if diagnostic not in FIXED_DIAGNOSTICS:
            raise AssertionError(
                "a broker refusal carries a FIXED diagnostic; composing one "
                "from what the broker or the provider said is exactly what "
                "this class exists to prevent")
        super().__init__(diagnostic)
        self.diagnostic = diagnostic


class _TokenExpired(Exception):
    """The provider said the presented token is no longer valid.

    PRIVATE and never raised out of this module: it is the signal the
    expiry ruling turns on, and it becomes either a re-mint or a
    ``BrokerRefused`` before any caller sees anything."""


# ---------------------------------------------------------------------------
# the minted token (task 2.1: memory only, never written, never logged)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True, repr=False)
class MintedToken:
    """One short-lived, scoped token, as the broker issued it.

    IN PROCESS MEMORY ONLY. Nothing here writes it, returns it to a route, or
    puts it in a record; the port below holds at most one of these at a time and
    drops it at expiry, and the object dies with the process that minted it.

    ``__repr__`` REDACTS, and that is not decoration. A frozen dataclass's
    generated repr prints every field, so an exception chain, a debugger, a
    `print(port.__dict__)`, or a future `logging` call that formats an object
    would each have disclosed the token. Redacting at the type means every one
    of those routes discloses the same nothing.

    ``endpoint`` and ``dialect`` come from the BINDING and ``audit_ref`` from
    the mint answer. The audit reference is DISCLOSABLE by construction — the
    declaration records no token material against it, not the token, not a
    prefix, not a hash — and it is carried because the re-mint passes it as
    ``--retry-of`` so the broker's own trail shows one turn that needed two
    tokens rather than two unrelated issuances (0.2 FINDING 5)."""

    token: str
    expires_at: float
    endpoint: str
    dialect: str
    audit_ref: str

    def __repr__(self) -> str:
        return (f"MintedToken(token=<redacted>, expires_at={self.expires_at!r},"
                f" endpoint={self.endpoint!r}, dialect={self.dialect!r},"
                f" audit_ref={self.audit_ref!r})")

    __str__ = __repr__

    def expired(self, now: float) -> bool:
        """Whether this token has passed the expiry the broker DECLARED.

        Compared against the broker's own `expires_at` rather than against a
        lifetime this client assumed: the broker is the authority on how long
        what it issued is good for."""
        return now >= self.expires_at


def _parse_expires_at(value: object) -> float:
    """The broker's declared expiry, as epoch seconds.

    Accepts an ISO-8601 instant (the spelling `credential-contracts` uses for
    its own `expires_at`) or a plain number of epoch seconds. A naive instant is
    read as UTC — the alternative, reading it in the console host's local zone,
    would make a token's life depend on where the operator lives."""
    if isinstance(value, bool):
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise BrokerRefused(DIAG_BROKER_MALFORMED) from error
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


# ---------------------------------------------------------------------------
# the broker runner seam
# ---------------------------------------------------------------------------


def subprocess_broker_runner(argv, *, source=None,
                             timeout: float = BROKER_TIMEOUT_SECONDS) -> str:
    """Run one declared broker invocation and return its standard output.

    THE STDIN CONTRACT IS THE DECLARATION'S, and it is one thing rather than
    two (0.2 FINDING 2). `intake` reads standard input TO EOF and treats ALL of
    it as the secret, so an `intake` receives the credential and NOTHING ELSE —
    no request line, no framing, no trailing byte this module chose. Every other
    operation reads no standard input at all, and this function closes the pipe
    immediately for them, which is what the declaration says a caller may do.

    The credential is STREAMED, not read: `shutil.copyfileobj` moves it in
    chunks from the operator's handle to the child's pipe, so the whole value
    never becomes a string in this process and there is no variable holding it
    to outlive the call.

    A BROKEN PIPE IS A REFUSAL ARRIVING, NOT A BROKER THAT WOULD NOT START
    (0.2 FINDING 6). The declaration obliges a consumer to treat `EPIPE` on that
    write as "read the refusal": some invocations are refused BEFORE standard
    input is read at all — an `--auth-kind oauth` intake is refused that way on
    purpose, so a grant never enters a process that cannot store it correctly —
    and the child may have exited before the write completes. So the write error
    is swallowed and the ANSWER is taken from where the declaration says it
    lives: the exit code and what the child wrote. A broker that could not be
    STARTED is a different fact, raised from `Popen` itself, and keeps the
    different sentence.

    The child's environment is the same scrubbed allowlist the harness bridge
    already uses (`doxbench_bridge.INHERITED_ENVIRONMENT`), reused rather than
    respelled: a broker inherits a PATH and a HOME and nothing else, so no
    credential-shaped variable of this process's environment can reach it and
    no accident can turn an ambient variable into an implicit credential. HOME
    is how the declaration's own default custody root
    (`~/.openprofiler/broker`) resolves, so the allowlist already carries
    everything a broker needs and nothing it does not.

    Stderr is DISCARDED AT THE DESCRIPTOR (DEVNULL, PR #392 review note): a
    broker's own words must never reach a caller, inheriting this process's
    stderr would put them on the console, and capturing them into a pipe would
    make this process's memory a function of how noisy a declared program
    chooses to be. The kernel drops them instead, unread by construction."""
    try:
        child = subprocess.Popen(  # noqa: S603 - argv from a declared binding plus the declared subcommand, never a shell string
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=bridge_mod.child_environment(os.environ),
            text=True,
        )
    except (OSError, ValueError) as error:
        raise BrokerRefused(DIAG_BROKER_UNREACHABLE) from error
    try:
        try:
            if source is not None:
                # The credential's ONLY path through this process: handle to
                # pipe, in chunks, never assembled.
                shutil.copyfileobj(source, child.stdin)
            child.stdin.close()
        except BrokenPipeError:
            # THE REFUSAL ARRIVING. Nothing is raised here; the exit code and
            # the child's own answer are read below, exactly as the declaration
            # instructs. The close is still attempted so the descriptor is not
            # left to a garbage collector, and its own broken pipe is dropped
            # for the same reason the first one was.
            try:
                child.stdin.close()
            except OSError:
                pass
        # `communicate` flushes `child.stdin` before reading, which raises on a
        # handle this function has already closed — and closing it IS the
        # signal a streamed credential's end of file needs. Dropping the
        # reference is the documented way to say "stdin is finished with", and
        # it is also the last place in this process that could have held the
        # pipe the credential travelled down.
        child.stdin = None
        answer, _dropped_stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        child.kill()
        child.communicate()
        raise BrokerRefused(DIAG_BROKER_TIMEOUT) from error
    except OSError as error:
        child.kill()
        child.communicate()
        raise BrokerRefused(DIAG_BROKER_UNREACHABLE) from error
    if child.returncode != 0:
        raise BrokerRefused(DIAG_BROKER_REFUSED)
    if len(answer.encode("utf-8")) > MAX_BROKER_ANSWER_BYTES:
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    return answer


def broker_operation_argv(binding, operation: str, *,
                          retry_of: str | None = None) -> tuple[str, ...]:
    """The whole argv for one DECLARED operation: the binding's base invocation,
    then the subcommand and its declared flags.

    ONE function for all four, so the declaration's vocabulary is recorded in
    one readable place and a test can assert every operation against
    `docs/broker-cli.md` without spawning anything. It builds no command PATH —
    that is the binding's — and it names no flag the declaration does not.

    NO FLAG HERE CAN CARRY A SECRET, and that is structural rather than
    careful: every value comes from a field of the binding, the binding has no
    secret field to read, and the declaration refuses a credential-shaped flag
    on every command with its own `secret_in_argv` code. Two independent
    refusals, agreeing.

    A BINDING THAT NAMES NO BROKER HAS NO BROKER OPERATION (#1144 box 16.3).
    The built-in resolver or the auth kind `none` answers it, and its empty
    base invocation would otherwise run the SUBCOMMAND as a program. So that
    is a programming error here, like an undeclared operation. The operator
    door refuses it in words first (`cli_model_binding`)."""
    if operation not in OPERATIONS:
        raise AssertionError(
            f"{operation!r} is outside the broker's declared operation "
            f"vocabulary {OPERATIONS}")
    if binding.credential_source() != binding_mod.CREDENTIAL_FROM_BROKER:
        raise AssertionError(
            f"binding {binding.id!r} names no broker, so it has no broker "
            "operation: the built-in resolver or the auth kind "
            f"{binding_mod.AUTH_KIND_NONE!r} answers it")
    argv = list(binding.substituted_argv())
    if operation == OPERATION_INTAKE:
        argv += [OPERATION_INTAKE,
                 FLAG_BINDING, binding.id,
                 FLAG_PROVIDER, binding.provider,
                 FLAG_AUTH_KIND, binding.auth_kind,
                 FLAG_APPROVED_BY, binding.approved_by,
                 FLAG_LABEL, binding.label]
    elif operation == OPERATION_MINT:
        argv += [OPERATION_MINT, FLAG_REFERENCE, binding.credential_ref]
        if retry_of is not None:
            argv += [FLAG_RETRY_OF, retry_of]
    elif operation == OPERATION_REVOKE:
        argv += [OPERATION_REVOKE, FLAG_REFERENCE, binding.credential_ref]
    else:
        argv += [OPERATION_LIST]
    return tuple(argv)


def _answer_document(text: object, kind: str, fields) -> dict:
    """One broker answer, parsed against the declared shape EXACTLY.

    EXACTLY MEANS EXACTLY (PR #392 review note a). This used to demand that
    every named field be PRESENT and tolerate any others beside them, while its
    own comment claimed "the required keys, exactly" — the docstring was the
    stricter of the two, and the code was the one that mattered. The declaration
    says a successful command writes ONE JSON object whose fields it enumerates,
    so an object carrying a key the declaration does not name is not this
    broker's answer, and reading a token out of it would be reading a document
    written against a contract this parser has not been shown.

    THE COST IS STATED RATHER THAN HIDDEN: a future broker that adds a field
    without moving `schema_version` refuses here instead of being tolerated. That
    is the right way round for a document that carries a credential — an
    unrecognised answer shape is exactly when a consumer should stop — and the
    fix is this repository reading the newer declaration, which is a code change
    because the PARSER is what changed, not the operator's binding."""
    if not isinstance(text, str):
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    try:
        document = json.loads(text)
    except (ValueError, TypeError) as error:
        raise BrokerRefused(DIAG_BROKER_MALFORMED) from error
    if not isinstance(document, dict):
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    if document.get("schema_version") != BROKER_ANSWER_SCHEMA_VERSION:
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    if document.get("kind") != kind:
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    if set(document) != set(fields):
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    return document


def _declared_string(document: Mapping, field: str) -> str:
    value = document[field]
    if not isinstance(value, str) or not value.strip():
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    return value


# ---------------------------------------------------------------------------
# the credential hand-off (task 1.3)
# ---------------------------------------------------------------------------


def hand_off_credential(binding, source, *,
                        runner=subprocess_broker_runner) -> str:
    """Hand a human's credential to the broker's `intake` and keep only the
    reference.

    `source` is an OPEN HANDLE the caller supplies — `sys.stdin`, a pipe, a
    test's `io.StringIO` — and never a string. That signature is the enforcement
    rather than a convention: a caller cannot pass a credential VALUE to this
    function, so no caller can be holding one either, and the value's whole
    journey is handle to pipe to broker.

    THE HANDLE IS THE WHOLE OF STANDARD INPUT (0.2 FINDING 2). `intake` reads to
    EOF and treats everything it read as the secret, so nothing is written
    before the credential and nothing after it. Every fact the operation needs —
    the binding id, the provider, the auth kind, the approver, the label — rides
    the declared FLAGS, where a fact belongs and a secret may not.

    Returns the `reference` the broker gives back — the declaration's own field
    name (0.2 FINDING 4). That reference is the only thing that then lives in a
    binding, in a file, in a log or in a review.

    THE BUILT-IN FORMS ARE RESERVED (#1144 box 16.3; Copilot's overview of
    openDox-code#63 at `286655f3`). A broker's reference in the `env:` or
    `keyring:` form would make the record read it as the built-in resolver's,
    beside the broker that holds the credential, which is two resolvers. The
    record refuses that, and it would do so where neither entry point
    expects a refusal. So such an answer is malformed, and it is refused
    here, where both entry points already catch a broker's refusal."""
    answer = runner(broker_operation_argv(binding, OPERATION_INTAKE),
                    source=source)
    document = _answer_document(answer, BROKER_INTAKE_KIND, INTAKE_FIELDS)
    reference = _declared_string(document, "reference")
    if binding_mod.names_a_built_in_form(reference):
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    return reference


# ---------------------------------------------------------------------------
# minting (task 2.1)
# ---------------------------------------------------------------------------


def mint(binding, *, retry_of: str | None = None,
         runner=subprocess_broker_runner) -> MintedToken:
    """Ask the broker for a short-lived token.

    Returns the token IN MEMORY. Nothing in this function writes it, and its
    only caller is the port below, which holds at most one at a time.

    `retry_of` is the `audit_ref` of the mint this one REPLACES, passed as the
    declared `--retry-of` so the broker's audit trail correlates a mid-turn
    re-mint with the issuance it replaced (Brett's 0.3 ruling; 0.2 FINDING 5).
    It is `None` on a first mint, which is also what the broker records.

    WHERE the token is good and WHAT GRAMMAR that endpoint speaks come from the
    BINDING, not from this answer: the declaration emits neither and says why —
    the broker is provider-agnostic about the request grammar and will not name
    an endpoint it would then be accountable for (0.2 FINDING 3).

    NO TOKEN IS ASKED FOR ON A ROUTE THAT IS NOT PRIVATE (Brett Heap's word of
    2026-09-29: a broker's minted token keeps the rules a built-in credential
    keeps). The record refuses such a binding when it is declared
    (`doxbench_binding.ENDPOINT_NOT_PRIVATE`), so no declared binding reaches
    this check. It is repeated before the broker is asked all the same, as the
    built-in resolver repeats it before it reads, because this is the function
    that obtains the token. What reaches it is a programming error, and
    nothing has been minted when it is raised."""
    if not binding_mod.is_a_private_route(binding.endpoint):
        raise AssertionError(
            f"binding {binding.id!r} would present a minted token over a "
            "route that is not private, which the record refuses when it is "
            "declared; nothing was minted")
    answer = runner(broker_operation_argv(binding, OPERATION_MINT,
                                          retry_of=retry_of))
    document = _answer_document(answer, BROKER_MINT_KIND, MINT_FIELDS)
    return MintedToken(
        token=_declared_string(document, "token"),
        expires_at=_parse_expires_at(document["expires_at"]),
        endpoint=binding.endpoint,
        dialect=binding.dialect,
        audit_ref=_declared_string(document, "audit_ref"))


def revoke(binding, *, runner=subprocess_broker_runner) -> str:
    """Destroy the broker's custody of this binding's credential.

    Returns the revocation's own `audit_ref`. The declaration keeps the audit
    trail through a revocation and refuses an unknown reference rather than
    answering silently, so "there was nothing there" and "it is gone now" stay
    different answers — and both reach a caller here as the same fixed refusal
    or the same returned reference, never as the broker's own words."""
    answer = runner(broker_operation_argv(binding, OPERATION_REVOKE))
    document = _answer_document(answer, BROKER_REVOCATION_KIND,
                                REVOCATION_FIELDS)
    if document["revoked"] is not True:
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    return _declared_string(document, "audit_ref")


def list_references(binding, *, runner=subprocess_broker_runner) -> list:
    """The broker's NON-SECRET reference index, as the declaration returns it.

    Safe to read and safe to print: `list` never opens a custody file, and the
    index it reads carries no credential material. Returned as the declaration's
    own list of entries rather than reshaped, because a consumer that reshapes
    an index it does not own invents a second contract for it."""
    answer = runner(broker_operation_argv(binding, OPERATION_LIST))
    document = _answer_document(answer, BROKER_REFERENCE_LIST_KIND,
                                REFERENCE_LIST_FIELDS)
    references = document["references"]
    if not isinstance(references, list):
        raise BrokerRefused(DIAG_BROKER_MALFORMED)
    return references


# ---------------------------------------------------------------------------
# the built-in resolver (#1144 box 16.3; RULED R1Q17 (b), `5850003126`)
# ---------------------------------------------------------------------------

def _presentable(value: object) -> bool:
    """Whether a resolved value can be presented AS IT IS, as the bearer
    credential of the request's Authorization header.

    It must be a non-empty string of printable ASCII with no whitespace, which
    a bearer credential is by its grammar (RFC 6750's `b64token` is narrower
    still). Any other value is refused, before any provider is contacted
    (Copilot's overview of openDox-code#63). Measured against `urllib`:
      * a line break or a NUL cannot travel in a header at all;
      * a character outside latin-1 fails while the header is encoded. The
        refusal from there would read `DIAG_PROVIDER_UNREACHABLE`, which names
        the wrong party, and the `UnicodeEncodeError` it chains holds the
        whole header, credential included;
      * any other non-ASCII character, and an embedded space, is SENT, as a
        credential the grammar does not allow.
    Trimming or re-encoding the value would present a credential other than
    the one the reference names, so the value is refused instead."""
    return (isinstance(value, str) and value != ""
            and all("!" <= character <= "~" for character in value))


#: What a keyring backend's failure reads as, inside the resolver only. A
#: sentinel, not None, because None is what a backend answers for an absent
#: entry, which is a different refusal.
_UNREADABLE = object()


def _os_keyring():
    """The OS keyring, through the `keyring` package, imported at call time.

    NOT A DEPENDENCY OF THIS PACKAGE, and that is deliberate. An install that
    never names a keyring reference never needs it, and one that does installs
    it beside openDox. Without it, a keyring reference refuses with the fixed
    `DIAG_KEYRING_UNAVAILABLE` rather than raising an import error out of a
    turn."""
    try:
        import keyring
    except ImportError:
        raise BrokerRefused(DIAG_KEYRING_UNAVAILABLE) from None
    return keyring


def resolve_credential_reference(binding, *, environ=None,
                                 keyring_backend=None) -> str:
    """THE BUILT-IN RESOLVER: the credential an `env:NAME` or
    `keyring:SERVICE/USERNAME` reference names, read NOW.

    AT CALL TIME, IN THIS MODULE ONLY (R1Q17 (b)). The port calls it once per
    request and hands the answer straight to `_post_to_provider`, and nothing
    keeps it. So a key rotated in the keyring is the key the next request
    presents, and no credential lives on the port between turns. The
    reference's FORM is parsed by `doxbench_binding.built_in_reference_parts`,
    which the record already ran when the binding was declared, so the two
    cannot disagree about it.

    `environ` and `keyring_backend` are seams for tests. Production passes
    neither, and so reads this process's own environment and the OS keyring.

    Every failure is a FIXED refusal, raised before any provider is contacted.
    An unset variable, an absent keyring entry, or a value that cannot be
    presented as it is (`_presentable`) is `DIAG_REFERENCE_UNRESOLVED`. A
    keyring that cannot be read is `DIAG_KEYRING_UNAVAILABLE`. A keyring
    backend's own error is dropped unread, like a broker's or a provider's.

    NOTHING IS READ FOR A ROUTE THAT IS NOT PRIVATE (Brett Heap's ruling of
    2026-09-28, "Refuse unless loopback"). What this function reads is a
    long-lived key, sent only over `https://` or over `http://` to this host.
    The record refuses any other endpoint when the binding is declared
    (`doxbench_binding.ENDPOINT_NOT_PRIVATE`), so no declared binding reaches
    that check here. The check is repeated before the first read all the
    same, because this is the function that holds the key. What reaches it
    is a programming error, like a broker's reference, and nothing has been
    read when it is raised."""
    reference = binding_mod.built_in_reference_parts(binding.credential_ref)
    if reference is None:
        raise AssertionError(
            f"binding {binding.id!r} names a broker's reference, which the "
            "broker resolves; the built-in resolver takes only the "
            f"{binding_mod.BUILT_IN_REFERENCE_FORMS} forms")
    if not binding_mod.is_a_private_route(binding.endpoint):
        raise AssertionError(
            f"binding {binding.id!r} routes a credential the built-in "
            "resolver reads over a route that is not private, which the "
            "record refuses when it is declared; nothing was read")
    if reference.form == binding_mod.CREDENTIAL_REF_ENV:
        value = (os.environ if environ is None else environ).get(
            reference.name)
    else:
        backend = (keyring_backend if keyring_backend is not None
                   else _os_keyring())
        try:
            value = backend.get_password(reference.name, reference.user)
        # A keyring backend's own error, of any class, never reaches a caller.
        except Exception:  # noqa: BLE001
            value = _UNREADABLE
        if value is _UNREADABLE:
            # Raised outside the handler, so the refusal keeps no context
            # (Copilot's overview of openDox-code#63 at `286655f3`): the
            # backend's own frames may hold what it was decoding when it
            # failed.
            raise BrokerRefused(DIAG_KEYRING_UNAVAILABLE)
    if not _presentable(value):
        # The refusal's traceback keeps this frame, so what was read leaves
        # it first: a value that cannot be presented can still be most of a
        # key.
        del value
        raise BrokerRefused(DIAG_REFERENCE_UNRESOLVED)
    return value


# ---------------------------------------------------------------------------
# the provider transport
# ---------------------------------------------------------------------------

#: The provider request's own field names, per dialect. Named constants rather
#: than inline literals so the boundary test can assert they exist only here.
#: `model` is the one field both grammars share.
PROVIDER_REQUEST_MODEL_FIELD = "model"

#: `xfactory-prompt-v1`: a model and a prompt in, an `assistant_prose` out.
PROVIDER_REQUEST_PROMPT_FIELD = "prompt"
PROVIDER_RESPONSE_PROSE_FIELD = "assistant_prose"

#: `openai-chat-v1` (#1144 box 16.1; plan 034 T078): the chat-completions
#: request, a model and a list of messages, and its answer, the content of the
#: first choice's message. The assembled prompt travels as ONE message in the
#: user role. Prompt assembly is on the other side of the port (D14), so this
#: arm carries the text it was given and composes no message of its own.
PROVIDER_REQUEST_MESSAGES_FIELD = "messages"
CHAT_MESSAGE_ROLE_FIELD = "role"
CHAT_MESSAGE_CONTENT_FIELD = "content"
CHAT_ROLE_USER = "user"
CHAT_RESPONSE_CHOICES_FIELD = "choices"
CHAT_RESPONSE_MESSAGE_FIELD = "message"

#: The status a provider returns when the presented token is no longer good.
#: 401 only: a 403 is an authorization verdict about what the token may do,
#: which re-minting the same scope cannot change, and retrying it would buy a
#: second refusal.
PROVIDER_STATUS_TOKEN_EXPIRED = 401


def _prompt_request(model: str, prompt: str) -> dict:
    """`xfactory-prompt-v1`'s request, exactly as it has always been sent."""
    return {PROVIDER_REQUEST_MODEL_FIELD: model,
            PROVIDER_REQUEST_PROMPT_FIELD: prompt}


def _prompt_answer(document: dict) -> str:
    """`xfactory-prompt-v1`'s answer: its `assistant_prose`, a string."""
    prose = document.get(PROVIDER_RESPONSE_PROSE_FIELD)
    if not isinstance(prose, str):
        raise BrokerRefused(DIAG_PROVIDER_MALFORMED)
    return prose


def _chat_request(model: str, prompt: str) -> dict:
    """`openai-chat-v1`'s request: the model, and the prompt as one message in
    the user role."""
    return {PROVIDER_REQUEST_MODEL_FIELD: model,
            PROVIDER_REQUEST_MESSAGES_FIELD: [
                {CHAT_MESSAGE_ROLE_FIELD: CHAT_ROLE_USER,
                 CHAT_MESSAGE_CONTENT_FIELD: prompt}]}


def _chat_answer(document: dict) -> str:
    """`openai-chat-v1`'s answer: `choices[0].message.content`, a string.

    Read at exactly that path and nowhere else. A body with no first choice, a
    choice with no message, or a message whose content is not text (a tool-call
    answer carries null there) is not an answer this seam can hand back as
    prose. Each lands on the fixed `DIAG_PROVIDER_MALFORMED` that every other
    unusable answer lands on. Nothing past the first choice is read: the
    request asks for one."""
    choices = document.get(CHAT_RESPONSE_CHOICES_FIELD)
    if not isinstance(choices, list) or not choices:
        raise BrokerRefused(DIAG_PROVIDER_MALFORMED)
    first = choices[0]
    message = (first.get(CHAT_RESPONSE_MESSAGE_FIELD)
               if isinstance(first, dict) else None)
    content = (message.get(CHAT_MESSAGE_CONTENT_FIELD)
               if isinstance(message, dict) else None)
    if not isinstance(content, str):
        raise BrokerRefused(DIAG_PROVIDER_MALFORMED)
    return content


#: ONE ARM PER DECLARED DIALECT: the function that builds its request and the
#: function that reads its answer. The record's closed vocabulary
#: (`doxbench_binding.DIALECTS`) refuses any other member at declaration, and a
#: test holds this table's keys equal to that vocabulary, so a member cannot
#: join one without the other.
_DIALECT_ARMS: dict[str, tuple] = {
    DIALECT_XFACTORY_PROMPT_V1: (_prompt_request, _prompt_answer),
    DIALECT_OPENAI_CHAT_V1: (_chat_request, _chat_answer),
}


class _PresentedCredential:
    """A credential on its way into ONE request's authorization header.

    Its repr and its str say nothing, as `MintedToken`'s do (Copilot's review
    of openDox-code#63 at `d240fd50`). A traceback keeps the frames it passes
    through, and an error reporter that records a frame's locals records them
    by their repr. So in this module a raw credential is a local of no frame
    except the one that reads it: `resolve_credential_reference`, until it
    returns. Every frame that carries a credential to the provider carries
    this wrapper instead."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def __repr__(self) -> str:
        return "_PresentedCredential(<withheld>)"

    __str__ = __repr__

    def authorization(self) -> str:
        """The authorization header's value, built as the header is set."""
        return f"Bearer {self._value}"


class _Redirected(Exception):
    """A provider answered a request carrying a credential with a redirect,
    and the redirect was declined.

    PRIVATE and never raised out of this module: the port answers it with
    `DIAG_PROVIDER_REDIRECTED` before any caller sees anything."""


class _DeclineRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect handler that follows NO redirect (Copilot's review of
    openDox-code#63 at `4abc6d4d`).

    `urllib`'s own handler re-sends a request's headers, all but the content
    ones, to whatever `Location` the provider names, whatever its host and
    scheme. Measured: a POST answered 301, 302 or 303 reaches the redirect's
    target as a GET that still carries `Authorization: Bearer ...`, whether
    the bearer is a built-in credential or a broker's minted token. A
    credential travels only by a private route (the loopback ruling of
    2026-09-28, which Brett Heap's word of 2026-09-29 gave a minted token
    too), and a followed redirect would send it by any route. So a request
    that carries one declines every redirect, with the redirect's answer
    closed unread."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise _Redirected


def _open_with_a_credential(request, *, timeout):
    """`urllib.request.urlopen` for a request that carries a credential: a
    broker's minted token, or what the built-in resolver read. It changes two
    things, and nothing else.

    * EVERY REDIRECT IS DECLINED (`_DeclineRedirects`).
    * A PLAIN-`http://` REQUEST GOES DIRECT, whatever proxy the environment
      names (Copilot's review of openDox-code#63 at `1b0fb3f4`). Such a
      route is private only because it stays on this host, and a proxy
      would carry it, in cleartext, to wherever the proxy is. Measured: with
      `http_proxy` set, urllib's default opener sends a request addressed
      to `127.0.0.1` to the proxy, credential header and all. An `https://`
      request may still use the environment's proxy, because a proxy
      reaches it only by CONNECT, and the credential stays inside TLS.

    The opener is built per call, as `urlopen` builds its own on first use,
    so the proxy environment is read when a request is made."""
    handlers: list = [_DeclineRedirects]
    if request.type == "http":
        handlers.insert(0, urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(
        request, timeout=timeout)


def _post_to_provider(*, endpoint: str, dialect: str,
                      credential: _PresentedCredential | None,
                      model: str, prompt: str, timeout: float, opener) -> str:
    """The ONE place a provider is contacted. Returns the assistant prose.

    `endpoint` and `dialect` are the binding's route. `model` is the model
    name the request carries, which the port chose (the binding's declared
    `model`, or the catalog handle for a binding that declares none).
    `credential` is what this request presents (#1144 box 16.3): the token a
    broker minted (a `MintedToken`'s), the value the built-in resolver read for
    this call, or None under the auth kind `none`. With None the request
    carries no authorization header at all. A credential arrives wrapped in a
    `_PresentedCredential`, so this frame holds no raw value for a traceback
    to keep.

    The credential travels in the request's authorization header and nowhere
    else; it is not in the URL (which a proxy logs), not in the body (which an
    error handler might echo), and not in this function's return value.

    THE GRAMMAR IS THE BINDING'S DIALECT (#1144 box 16.1). Its arm in
    `_DIALECT_ARMS` builds the request body and reads the answer. The route,
    the header, the bound, the expiry status and every refusal below are the
    same for both dialects.

    THE ANSWER IS BOUNDED (PR #392 review note b). `response.read()` with no
    argument reads until the peer stops sending, which makes the memory of this
    process a function of what a declared endpoint chooses to send — and the
    endpoint is a binding's declaration, so a misdeclared one was enough. One
    byte over `MAX_PROVIDER_ANSWER_BYTES` is read deliberately, so an answer
    that is exactly at the bound is still honoured while one past it is
    detected rather than truncated into a shorter document that would parse."""
    arm = _DIALECT_ARMS.get(dialect)
    if arm is None:
        raise AssertionError(
            f"{dialect!r} is outside the declared dialect vocabulary "
            f"{DIALECTS}; the binding refuses it at declaration, so no turn "
            "can carry one")
    build_request, read_answer = arm
    body = json.dumps(build_request(model, prompt)).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - endpoint declared on the binding by its operator
        endpoint, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if credential is not None:
        request.add_header("Authorization", credential.authorization())
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read(MAX_PROVIDER_ANSWER_BYTES + 1)
    except urllib.error.HTTPError as error:
        # The error body is DROPPED UNREAD: a provider's own words must never
        # reach a caller, and a 401 is the only status whose MEANING this client
        # acts on.
        status = getattr(error, "code", None)
        error.close()
        if status == PROVIDER_STATUS_TOKEN_EXPIRED:
            raise _TokenExpired from None
        raise BrokerRefused(DIAG_PROVIDER_REFUSED) from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise BrokerRefused(DIAG_PROVIDER_UNREACHABLE) from error
    if not isinstance(payload, (bytes, bytearray)):
        raise BrokerRefused(DIAG_PROVIDER_MALFORMED)
    if len(payload) > MAX_PROVIDER_ANSWER_BYTES:
        # TRUNCATED IS NOT PARSED. The extra byte proves the overflow and the
        # document is dropped whole rather than decoded — a prefix of a JSON
        # body is not a smaller answer, it is a different one.
        raise BrokerRefused(DIAG_PROVIDER_MALFORMED)
    try:
        document = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise BrokerRefused(DIAG_PROVIDER_MALFORMED) from error
    if not isinstance(document, dict):
        raise BrokerRefused(DIAG_PROVIDER_MALFORMED)
    return read_answer(document)


# ---------------------------------------------------------------------------
# the mint ledger (the 2026-08-26 ruling's "visibly recorded")
# ---------------------------------------------------------------------------

REASON_FIRST_MINT = "first_mint"
REASON_EXPIRY_REMINT = "remint_after_expiry"
REASON_PAID_RETRY = "paid_retry"
MINT_REASONS: tuple[str, ...] = (
    REASON_FIRST_MINT, REASON_EXPIRY_REMINT, REASON_PAID_RETRY)

#: The most mint events one served process keeps. A bound, not a policy.
MAX_LEDGER_EVENTS = 256


@dataclasses.dataclass(frozen=True, slots=True)
class MintEvent:
    """ONE content-free record of a mint or a paid retry.

    Carries no token, no prompt, no document text and no provider detail: a
    binding id, a reason from the closed vocabulary above, when it happened, and
    the mint's `audit_ref`. That is what makes it safe to disclose, which is the
    whole point of recording it — Brett's 2026-08-26 ruling is that a re-mint
    and the paid retry it buys are VISIBLE, and a record nobody may show would
    not satisfy it.

    THE `audit_ref` IS DISCLOSABLE BY CONSTRUCTION and is carried since the
    reconciliation (task 2.6): the declaration records no token material against
    an audit reference — not the token, not a prefix, not a hash — and it is the
    identifier the broker's own trail is keyed by. So a reader of this ledger
    and a reader of `broker-audit.jsonl` can be shown to be reading about the
    same issuance, which is what makes "visibly recorded" mean something on both
    sides of the seam rather than only on this one. `None` on the
    `paid_retry` event, which records the CALL rather than an issuance."""

    binding_id: str
    reason: str
    at: float
    audit_ref: str | None = None

    def as_dict(self) -> dict:
        return {"binding_id": self.binding_id, "reason": self.reason,
                "at": self.at, "audit_ref": self.audit_ref}


#: The operator-visible sentence a re-mint prints. FIXED, and content-free.
REMINT_NOTICE = (
    "[model-provider] the minted token expired mid-turn: re-minted once and "
    "retried the turn (one further paid provider call). A second expiry in the "
    "same turn refuses instead.")


# ---------------------------------------------------------------------------
# the port
# ---------------------------------------------------------------------------


class BrokeredProviderPort:
    """A `doxbench_model.WorkbenchModelPort` backed by the binding's
    credential: a broker-minted token, or, since #1144 box 16.3, a reference
    the built-in resolver reads at call time, or no credential at all under
    the auth kind `none`. The record's `credential_source()` says which, and
    the name is kept because the entry points construct this class by it.

    THREE MEMBERS AND NO FOURTH, exactly like every other adapter this seam
    accepts: `timeout_seconds`, `catalog()`, `dispatch(envelope)`. Everything
    below them — minting, expiry, the retry ruling, the built-in resolver, the
    provider call — is this class's business and reaches the seam as one
    opaque dispatch.

    ONE INSTANCE PER PROCESS, for the same reason the harness bridge is:
    `_workbench_model_port` resolves per REQUEST, and a port constructed per
    call would mint a fresh token for every turn and throw away a perfectly
    live one. The token is guarded by a lock because the server is a
    `ThreadingHTTPServer`. A record no broker answers holds NO credential on
    the port: the resolver reads it for each request.

    `catalog()` NEVER MINTS AND NEVER RESOLVES. A menu is not a paid call, and
    a console that minted a token or read a key to render one would do so on
    every capabilities probe."""

    def __init__(self, binding, catalog, *,
                 timeout_seconds: float = 60.0,
                 runner=subprocess_broker_runner,
                 opener=urllib.request.urlopen,
                 clock=time.time,
                 notice=None,
                 environ=None,
                 keyring_backend=None) -> None:
        if not isinstance(binding, binding_mod.ModelProviderBinding):
            raise TypeError(
                "binding must be a ModelProviderBinding, got "
                f"{type(binding).__name__}")
        if not isinstance(catalog, model_mod.ModelCatalog):
            raise TypeError(
                f"catalog must be a ModelCatalog, got {type(catalog).__name__}")
        self._binding = binding
        self._declared_catalog = catalog
        self._timeout_seconds = model_mod.validated_timeout_seconds(
            timeout_seconds)
        self._runner = runner
        self._opener = opener
        self._clock = clock
        self._notice = notice if notice is not None else sys.stderr.write
        # The built-in resolver's seams (#1144 box 16.3). None reads this
        # process's own environment and the OS keyring, AT CALL TIME.
        self._environ = environ
        self._keyring_backend = keyring_backend
        self._lock = threading.Lock()
        self._token: MintedToken | None = None
        self._available = True
        self.ledger: list[MintEvent] = []

    # -- the three port members --------------------------------------------

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def catalog(self) -> model_mod.ModelCatalog:
        """The install's declared catalog, marked unavailable once this port
        knows it cannot present a credential: a broker that refused to mint,
        or a reference the built-in resolver could not resolve.

        The same honesty the harness bridge keeps: a declaration is available
        until something is measured, and a broker that has refused is measured.
        Nothing here contacts the broker, or reads a reference, to find out.
        A later turn that succeeds makes the entry available again."""
        if self._available:
            return self._declared_catalog
        return model_mod.ModelCatalog.from_entries([
            dataclasses.replace(entry, available=False)
            for entry in self._declared_catalog.entries])

    def dispatch(self, prompt_envelope: object) -> object:
        """ONE turn: mint (or reuse), call the provider, and honour the expiry
        ruling.

        Returns the shape `doxbench_model.dispatch_turn` validates — prose plus
        an empty proposal list — so typed proposals stay the route's injected
        validator's business, exactly as they are for the harness bridge.

        THE 2026-08-26 EXPIRY RULING, in full and in one place:

          * before the call, a token past its declared expiry is DISCARDED and a
            fresh one minted. That half is unconditional and is not the retry:
            it is simply never presenting a token known to be dead;
          * if the provider nevertheless says the token expired — the race the
            ruling is actually about, where a long generation outlives a short
            token — the port re-mints and retries the turn ONCE, recording both
            the re-mint and the paid retry in `ledger` and printing
            `REMINT_NOTICE`, because silently buying a second paid call is the
            decision this ruling refused to leave implicit. THE RE-MINT CARRIES
            `--retry-of <audit_ref>` (task 2.6, 0.2 FINDING 5), so the broker's
            audit trail shows one turn that needed two tokens instead of two
            unrelated issuances. The expired mint's reference is read off the
            token this turn is holding and lives no longer than the turn;
          * a SECOND expiry inside the same turn raises the standard refusal.
            No third call is bought.

        THE REQUEST'S MODEL IS THE BINDING'S DECLARED `model` (#1144 box
        16.2). A binding that declares none sends the catalog handle, which is
        what every request sent before the field existed, byte for byte.

        A RECORD NO BROKER ANSWERS takes `_dispatch_without_a_broker` instead
        (#1144 box 16.3): no mint, no ledger event, and no retry.

        EITHER WAY, THE PROVIDER IS CALLED THROUGH `_call_provider`, so a
        broker's minted token keeps every rule a built-in credential keeps: no
        redirect, no proxy over plain `http://`, and a refusal that chains
        nothing (Brett Heap's word of 2026-09-29). The re-mint and the retry
        above therefore happen outside every handler, so a refusal raised by
        either keeps no context either."""
        handle = getattr(prompt_envelope, "model_id", None)
        if not isinstance(handle, str) or not handle:
            entries = self._declared_catalog.entries
            handle = entries[0].model_id if entries else ""
        declared_model = self._binding.model
        model = declared_model if declared_model is not None else handle
        prompt = bridge_mod.render_prompt_message(prompt_envelope)
        if (self._binding.credential_source()
                != binding_mod.CREDENTIAL_FROM_BROKER):
            return {"assistant_prose": self._dispatch_without_a_broker(
                        model=model, prompt=prompt),
                    "proposals": []}
        token = self._current_token(REASON_FIRST_MINT)
        prose = self._call_provider(
            _PresentedCredential(token.token), endpoint=token.endpoint,
            dialect=token.dialect, model=model, prompt=prompt)
        if prose is None:
            # PER-TURN STATE, and no longer than the turn: the expired mint's
            # own audit reference, read before the token is dropped, so the
            # re-mint can name what it replaces.
            replaced = token.audit_ref
            self._forget_token()
            self._notice(REMINT_NOTICE + "\n")
            token = self._current_token(REASON_EXPIRY_REMINT,
                                        retry_of=replaced)
            self._record(REASON_PAID_RETRY)
            prose = self._call_provider(
                _PresentedCredential(token.token), endpoint=token.endpoint,
                dialect=token.dialect, model=model, prompt=prompt)
            if prose is None:
                self._forget_token()
                raise BrokerRefused(DIAG_TOKEN_EXPIRED_TWICE)
        return {"assistant_prose": prose, "proposals": []}

    def _dispatch_without_a_broker(self, *, model: str, prompt: str) -> str:
        """One turn for a record NO BROKER answers (#1144 box 16.3).

        NOTHING IS MINTED AND NOTHING IS KEPT. Under the built-in resolver the
        credential is read now, for this one request (RULED R1Q17 (b)), and it
        is dropped when this call returns. Under the auth kind `none` there is
        no credential, and the request carries no authorization header (RULED
        R1Q18 (a)). A resolution that fails refuses before any provider is
        contacted, and marks the catalog unavailable as a refused mint does.

        A 401 HERE IS A REFUSAL, NOT AN EXPIRY. The 2026-08-26 retry ruling is
        about a MINTED token outliving its turn, and here there is no mint to
        repeat: the reference names the same value on a second read, so a
        retry would buy a second paid call for the same refusal. It is raised
        outside every handler, so it keeps no context.

        The request itself is made through `_call_provider`, which keeps the
        rules for a request that carries a credential."""
        credential = None
        if (self._binding.credential_source()
                == binding_mod.CREDENTIAL_FROM_BUILT_IN_RESOLVER):
            try:
                credential = _PresentedCredential(resolve_credential_reference(
                    self._binding, environ=self._environ,
                    keyring_backend=self._keyring_backend))
            except BrokerRefused:
                with self._lock:
                    self._available = False
                raise
            with self._lock:
                self._available = True
        prose = self._call_provider(
            credential, endpoint=self._binding.endpoint,
            dialect=self._binding.dialect, model=model, prompt=prompt)
        if prose is None:
            raise BrokerRefused(DIAG_PROVIDER_REFUSED)
        return prose

    def _call_provider(self, credential: _PresentedCredential | None, *,
                       endpoint: str, dialect: str, model: str,
                       prompt: str) -> str | None:
        """ONE provider call, under the rules a request that carries a
        credential keeps, whichever resolver answered it: a broker's minted
        token, or what the built-in resolver read. Returns the prose, or None
        when the provider said the credential is no longer valid (a 401), which
        each path answers in its own way.

        A REQUEST THAT CARRIES A CREDENTIAL FOLLOWS NO REDIRECT AND, OVER
        PLAIN `http://`, USES NO PROXY. The default opener does both, and
        sends the credential header along each time, so such a request uses
        `_open_with_a_credential` in its place. An opener a caller injected is
        that caller's own seam, and it is used as given.

        A REFUSAL OF A REQUEST THAT CARRIED A CREDENTIAL CHAINS NOTHING. The
        credential stays wrapped in a `_PresentedCredential` in every frame
        here, and the refusal is raised afresh, with no cause and no context,
        so no traceback it carries reaches a frame inside `urllib` whose locals
        hold the request's headers (Copilot's review of openDox-code#63 at
        `d240fd50`).

        T080 gave these rules to the built-in resolver's key. Brett Heap's
        word of 2026-09-29 gave them to a broker's minted token too. The auth
        kind `none` presents nothing, so its request keeps the default opener,
        and its refusal is raised as `_post_to_provider` raised it."""
        opener = self._opener
        if credential is not None and opener is urllib.request.urlopen:
            opener = _open_with_a_credential
        try:
            return _post_to_provider(
                endpoint=endpoint, dialect=dialect, credential=credential,
                model=model, prompt=prompt, timeout=self._timeout_seconds,
                opener=opener)
        except _TokenExpired:
            return None
        except _Redirected:
            failure = DIAG_PROVIDER_REDIRECTED
        except BrokerRefused as refusal:
            if credential is None:
                raise
            failure = refusal.diagnostic
        # RAISED HERE, OUTSIDE EVERY HANDLER, so the refusal chains nothing. A
        # cause chained from inside `urllib` keeps frames whose locals hold the
        # request's headers, and so the credential.
        raise BrokerRefused(failure)

    # -- token custody ------------------------------------------------------

    def _current_token(self, reason: str, *,
                       retry_of: str | None = None) -> MintedToken:
        """The live token, minting one when there is none or the one held has
        passed the broker's declared expiry (discard-on-expiry, task 2.4).

        `retry_of` names the mint this one REPLACES and is passed to the broker
        as `--retry-of`. It is set only on the mid-turn re-mint the 0.3 ruling
        is about. DISCARD-ON-EXPIRY PASSES NOTHING, deliberately: a token
        dropped before it was ever presented bought no provider call, so there
        is no retry for the trail to correlate and claiming one would put a
        retry in the broker's audit record that never happened."""
        with self._lock:
            held = self._token
            if held is not None and not held.expired(self._clock()):
                return held
            self._token = None
            try:
                minted = mint(self._binding, retry_of=retry_of,
                              runner=self._runner)
            except BrokerRefused:
                self._available = False
                raise
            self._available = True
            self._token = minted
        self._record(reason, audit_ref=minted.audit_ref)
        return minted

    def _forget_token(self) -> None:
        with self._lock:
            self._token = None

    def _record(self, reason: str, *, audit_ref: str | None = None) -> None:
        event = MintEvent(binding_id=self._binding.id, reason=reason,
                          at=self._clock(), audit_ref=audit_ref)
        with self._lock:
            self.ledger.append(event)
            if len(self.ledger) > MAX_LEDGER_EVENTS:
                del self.ledger[:-MAX_LEDGER_EVENTS]

    def __repr__(self) -> str:
        return (f"BrokeredProviderPort(binding={self._binding.id!r}, "
                f"available={self._available}, "
                f"token={'held' if self._token is not None else 'none'})")
