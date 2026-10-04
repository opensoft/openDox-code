"""PER-MACHINE TRUST OF A SERVED REPOSITORY'S MODEL BINDINGS (#1144 16.3a;
plan 034 T100; RULED openxFactory#656 comment 5962785556, item 2, Brett
Heap, 2026-10-02: *"Trust per machine (Recommended)"*).

THE DEFECT THIS CLOSES. A checkout's bindings live in the checkout
(`doxbench_binding.DEFAULT_BINDINGS_RELPATH`), because a binding is safe to
commit. So a repository someone else wrote can declare one. Measured at
openDox-code `047bb4fa` (the adversarial review of 2026-10-02): the entry
points read the SERVED repository's bindings document, a hand-written binding
needed no approval, a `broker_argv` of `["/bin/sh", "-c", "id > $PWD/pwned"]`
ran on the first chat turn, and an `env:` or `keyring:` reference sent any
secret of the operator's to an endpoint the file chose.

THE RULE, as the ruling states it, and it works like direnv. A binding read
from the served repository runs a broker, resolves a credential reference, or
contacts its endpoint ONLY after the operator has trusted that exact binding on
this machine. "Exact" is the binding's canonical content (`binding_digest`), so
any edit untrusts it. The auth kind `none` is no exception: it presents no
credential, but it still sends chat content to an endpoint the file chooses.

  * `opendox model-binding add` and `edit` record trust for the binding they
    write, and `set-credential` re-records it after it rewrites the reference
    of a binding that was trusted. None of them ever trusts a binding that was
    not.
  * A cloned or hand-edited binding is refused BY NAME, before any spawn,
    secret read or contact, until `opendox model-binding trust <id>`, which
    prints what it trusts first.
  * Bindings stay committable. The trust is recorded OUTSIDE the repository, in
    the operator's own state (`MachineTrust`).

THE KEY is `(resolved repository root, binding id, digest)`. A binding copied
to another root is untrusted there: the root is part of what was trusted.

EVERY PATH THAT RUNS A REPOSITORY'S BROKER ASKS. A chat turn and
`model-binding set-credential` ask about the binding they would use. The
console intake's hand-off asks too, about the binding it is declaring: its
broker is the one the served repository's
`ideation/dashboard/model-declarations.yaml` names, which is no binding the
operator trusted, so under this default it is refused by name
(`INTAKE_BROKER_UNTRUSTED`). No command trusts an intake declaration's broker,
and a host's own policy may admit it (#1144 16.3a, T007 batch M).

WHAT A REPOSITORY WROTE IS SHOWN ESCAPED. Every value a refusal, the
factory's notice, `model-binding list` or `model-binding trust` prints from a
binding is printed in a JSON string's form (`shown`), so a newline or a
terminal control sequence in a field cannot forge or hide what is shown.

A COMMAND PRINTED FOR AN OPERATOR TO PASTE IS READ BY A SHELL, and JSON's
quoting is not a shell's: inside double quotes, `$(...)` and a backtick still
run (Copilot at openDox-code#82, r4174783197). So a printed command carries
only operands a POSIX shell reads back exactly (`trust_command`): an id the
model catalog accepts, whose characters no shell expands and no option parser
reads as an option, and a path quoted by `shlex.quote` where every character
of it is printable. A path that is not printable is never printed in a
command: the command names the repository as `.`, to be run from its root. An
id the catalog refuses belongs to a binding no turn could use, so no policy
trusts it and no command is printed for it (`unservable_because`).

THE STORE is one private file in openDox's state directory, the one
`runtime.config.state_dir` names (`OPENDOX_STATE_DIR`, or its per-user
default; openDox-code#69). It is checked the way that change's bundle checks
its own tree: a symbolic link is refused, so is a file or a directory that
another user could write, and the file is created by descriptor, exactly 0600,
and replaced atomically. The checks are restated here rather than imported,
because this change does not stack on #69. A store that fails them is refused
by name, and nothing is trusted through it. So is a state directory that is
the served repository or lies inside it, which a clone could carry: no trust
is ever written into, or read from, the tree being served. The store holds no
secret: roots, ids and digests.

A SEAM, AND ITS DEFAULT IS THE STRICT ONE. What decides trust is a POLICY
registered here: `verdict(binding, *, root)` and `record(binding, *, root)`.
openDox's neutral default is `MachineTrust`, the per-machine store above. A
host registers its own at process start (`register`), so a governed host's
flow is its own to decide. The default is registered, where no host has
registered one, by the two consumers the entry points already call:
`doxbench_install.declared_model_port_factory` and the `model-binding` verbs.
That departs from R1Q10 (a)'s entry-point registration (`cli.build_parser()`,
`cli.main()`, `serve.build_server()`, `serve.main()`) on purpose: it keeps
this change out of those files' single-writer order, and it is fail-closed,
because what is registered lazily is the strictest policy there is. A
checkout with no bindings never asks the policy anything, so it never touches
the state directory. A process that asks `current()` with nothing registered
is refused, naming this seam (4.2's discipline).

ENFORCED IN DEPTH. The ONE place a binding becomes usable is
`declared_model_port_factory`, and it asks the policy. Every place that would
act on a binding asks again, of a `TrustVerdict` it is handed:
`doxbench_provider`'s port, its broker operations (all four run through one
function) and its built-in resolver each refuse a binding the verdict does not
cover, by id AND digest (`require_admitted`). No verdict is no trust.

IMPORT WEIGHT. The standard library, `opendox.doxbench_binding` and
`opendox.doxbench_model` (whose own imports are `dataclasses` and `typing`).
The runtime's `config` is imported when a state directory is first resolved,
and `doxbench_install` when a binding's catalog entry is first judged
(`unservable_because`). This module names no provider, holds no credential,
spawns nothing and reaches no network.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import contextlib
import dataclasses
import errno
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_model

try:                    # POSIX; where it is absent, nothing is recorded
    import fcntl
except ImportError:     # pragma: no cover - exercised through _lock_exclusively
    fcntl = None

__all__ = [
    "APPROVED_UNSERVABLE_NOTICE",
    "APPROVED_UNTRUSTED_NOTICE",
    "BASIS_CATALOG",
    "BASIS_HOST",
    "BASIS_MACHINE_TRUST",
    "BindingUntrusted",
    "MachineTrust",
    "TRUST_FILENAME",
    "TrustPolicyAlreadyRegistered",
    "TrustPolicyNotRegistered",
    "TrustStoreRefused",
    "TrustVerdict",
    "UNSERVABLE_TURN_MESSAGE",
    "UNTRUSTED_TURN_MESSAGE",
    "UntrustedBindingPort",
    "INTAKE_BROKER_UNTRUSTED",
    "REASON_UNSERVABLE",
    "REMEDY_UNSERVABLE",
    "binding_digest",
    "command_safe_id",
    "current",
    "is_registered",
    "policy",
    "refusal_message",
    "register",
    "register_default",
    "registered_verdict_for",
    "require_admitted",
    "resolved_root",
    "shown",
    "trust_command",
    "trust_remedy",
    "turn_message_for",
    "unregister",
    "unservable_because",
]

# ---------------------------------------------------------------------------
# the store's identity (the workspace rule: every document carries both)
# ---------------------------------------------------------------------------

#: The store document's `schema_version`.
SCHEMA_VERSION = 1

#: The store document's `kind`.
TRUST_KIND = "opendox-model-binding-trust"

#: The store's file name, directly under the state directory.
TRUST_FILENAME = "model-binding-trust.json"

#: The lock file beside the store. Every process that records trust holds an
#: exclusive lock on it across its read, its change and its replace of the
#: store, so two processes recording at once cannot lose either's trust, nor
#: restore a form another process replaced (Copilot at openDox-code#82,
#: r4173513761).
TRUST_LOCK_FILENAME = "model-binding-trust.lock"

#: The largest store this reads. A bound, not a policy: a store is a few
#: hundred bytes a binding, and an unbounded read of a file is a way to spend
#: this process's memory.
MAX_TRUST_STORE_BYTES = 1_048_576

#: The digest's algorithm, spelled on every digest so a stored one says how it
#: was computed.
DIGEST_PREFIX = "sha256:"

# ---------------------------------------------------------------------------
# what a verdict rests on
# ---------------------------------------------------------------------------

#: The verdict `MachineTrust` gives: the per-machine store says so.
BASIS_MACHINE_TRUST = "machine-trust"

#: A host policy's verdict (a governed host's own rule).
BASIS_HOST = "host"

#: The verdict on a binding the model catalog refuses, given before any
#: policy is asked (`unservable_because`).
BASIS_CATALOG = "catalog"

#: The setting that names openDox's state directory (openDox-code#69).
STATE_DIR_SETTING = "OPENDOX_STATE_DIR"

# ---------------------------------------------------------------------------
# the fixed sentences (composed from nothing a repository or a secret holds)
# ---------------------------------------------------------------------------

#: Why a binding the store has never seen at this root is untrusted.
REASON_NEVER_TRUSTED = (
    "it has not been trusted for this repository on this machine")

#: Why a binding the store trusted in another form is untrusted.
REASON_CHANGED = (
    "it has changed since it was trusted for this repository on this machine")

#: Why a binding handed to an act with no verdict at all is untrusted.
REASON_NO_VERDICT = "no trust verdict was given for it"

#: Why a verdict for another binding, or another form of it, does not cover it.
REASON_NOT_COVERED = (
    "the trust verdict given for it covers another binding, or another form "
    "of it")

#: Why `MachineTrust` never admits the console intake's broker (#1144 16.3a,
#: T007 batch M; Copilot at openDox-code#82, r4173513782). The intake asks its
#: own question (`intake_verdict_for`), and no binding's trust answers it, so
#: a repository that declares a binding with the intake's very fields gains
#: nothing by having it trusted.
REASON_INTAKE_NOT_ADMITTED = (
    "the console intake runs a broker the served repository's declarations "
    "document names, and openDox's per-machine trust admits no intake; only "
    "a host's own policy can, by answering intake_verdict")


#: Why a binding the model catalog refuses is never trusted (Copilot at
#: openDox-code#82, r4174783280). The catalog lists a binding by its id and
#: its label, so a binding whose id or label it refuses is one no chat turn
#: could ever use, and the factory could not declare it. The bounds are the
#: released catalog schema's, as `doxbench_model` restates them.
REASON_UNSERVABLE = (
    "the model catalog cannot list it: an id is 1 to "
    f"{doxbench_model.MODEL_REFERENCE_MAX_LENGTH} ASCII letters, digits, "
    "'.', '_' and '-', beginning with a letter or a digit, and a label is 1 "
    f"to {doxbench_model.LABEL_MAX_LENGTH} characters and not blank, so no "
    "chat turn could use it")

#: What an operator is told to do about such a binding: the ACTUAL remedy.
#: Trust cannot help (`recorded_for` refuses such a binding), so no command
#: that trusts it is printed. The binding is corrected instead, by the verbs
#: that declare one, and each records trust for what it writes (Copilot at
#: openDox-code#82, r4175203889).
REMEDY_UNSERVABLE = (
    "Trusting it cannot make it usable: correct it so the model catalog "
    "accepts its id and its label, with \"opendox model-binding edit\" "
    "(the same id) or \"opendox model-binding remove\" and then \"add\" (a "
    "new id), each of which records trust for what it writes")


def unsupported_platform() -> str | None:
    """Why this platform cannot keep the per-machine store, or None (Copilot
    at openDox-code#82, r4173876800; #69's `runtime.bundle.
    unsupported_platform` names its own gaps the same way). The store is
    judged by its owner's uid, opened and made without following a link and
    without waiting on what it opened (a FIFO, r4178064601), made relative
    to its parent's descriptor, written with `fchmod`, and recorded under a
    file lock. Where one of those is missing, nothing can be trusted, and
    the store says so by name rather than fail on the first missing name."""
    missing = [name for name, present in (
        ("os.getuid", hasattr(os, "getuid")),
        ("os.O_DIRECTORY", hasattr(os, "O_DIRECTORY")),
        ("os.O_NOFOLLOW", hasattr(os, "O_NOFOLLOW")),
        ("os.O_NONBLOCK", hasattr(os, "O_NONBLOCK")),
        ("os.fchmod", hasattr(os, "fchmod")),
        ("mkdir with dir_fd", os.mkdir in getattr(os, "supports_dir_fd", ())),
        ("fcntl.flock", fcntl is not None),
    ) if not present]
    if not missing:
        return None
    return (f"the model-binding trust store needs a POSIX platform, and this "
            f"one ({sys.platform}) lacks {', '.join(missing)}: the store is "
            "judged by its owner, opened without following a link and "
            "recorded under a file lock, so nothing can be trusted here")


def reason_policy_failed(error: BaseException) -> str:
    """Why a binding a policy failed to judge is untrusted. It names the class
    of what the policy raised and never its words, which may hold anything."""
    return f"the trust policy failed ({type(error).__name__})"


#: What the store refusal says when the runtime defines no state directory.
#: That is this change's base before openDox-code#69 lands. Nothing can be
#: trusted then, which is the fail-closed reading.
NO_STATE_DIR = (
    "this install defines no state directory for the trust store "
    "(OPENDOX_STATE_DIR, openDox-code#69), so nothing can be trusted on this "
    "machine")

#: What a refused chat turn says (`serve_workbench`'s model step). A FIXED
#: module-level constant, because a turn refusal's message never carries
#: anything a request or a repository chose: it names no binding and no path.
#: The factory's notice and `opendox model-binding list` name the binding.
UNTRUSTED_TURN_MESSAGE = (
    "the model binding this install declares is not trusted on this machine, "
    "so nothing was sent: no broker ran, no credential was read and no "
    "endpoint was contacted. Run \"opendox model-binding list --repo-root "
    "<repository>\" to see which binding and why, trust it with \"opendox "
    "model-binding trust --repo-root <repository> <id>\", and restart this "
    "console")

#: What a refused chat turn says when the binding this install declares is
#: one the model catalog cannot list (`REASON_UNSERVABLE`), so its port lists
#: nothing (Copilot at openDox-code#82, r4175203889). Trust cannot repair it,
#: so this sentence, unlike `UNTRUSTED_TURN_MESSAGE`, names no command that
#: trusts: it names the remedy. A FIXED sentence, as that one is, and held
#: within the released failure envelope's `message` bound (500 characters).
UNSERVABLE_TURN_MESSAGE = (
    "the model binding this install declares cannot be used, because the "
    "model catalog cannot list its id or its label, so nothing was sent and "
    "nothing was contacted. Trusting it cannot help. Run \"opendox "
    "model-binding list --repo-root <repository>\" to see which binding, "
    "correct it with \"opendox model-binding edit\" (the same id) or "
    "\"remove\" and \"add\" (a new id), each of which records trust for "
    "what it writes, and restart this console")


#: What the chat rail says when the catalog lists a declared model and none is
#: available (#1144 16.3a; RULED openxFactory#656 comment 5962785556, item 2,
#: "make the rail say how to trust"). The catalog's wire shape is closed, so
#: the rail cannot say WHICH binding or why: it sends the operator to
#: `model-binding list`, which shows whether each binding is trusted, names
#: the verb that trusts one, and says where the reason is for a binding
#: already trusted, which a provider's refusal also leaves unavailable
#: (Copilot at openDox-code#82, r4173876849). The rail's JavaScript
#: twin, `UNTRUSTED_BINDING_REMEDY` in `web/views/doxbench-chat.js`, beside
#: openDox-code#74's no-model line, is held to this spelling by
#: `tests/test_model_binding_trust.py`.
UNTRUSTED_BINDING_REMEDY = (
    "No declared model is available. \"opendox model-binding list "
    "--repo-root <repository>\" shows whether each binding is trusted on "
    "this machine, and \"opendox model-binding trust --repo-root <repository> "
    "<id>\" trusts one after showing what it would run and where it would "
    "connect; then restart this console. A binding already trusted is "
    "unavailable for the reason this console printed when its provider "
    "refused.")

#: What the console's model approval answers, as its `availability`, when
#: the trust policy does not admit the binding it approved (#1144 16.3a; the
#: trust-state walk). Approval is a governance record, and trust is this
#: machine's: under openDox's strict default an approved binding is still
#: refused until it is trusted, so the result does not say it is available.
#: A host whose policy admits it (a governed host's approval) answers
#: `doxbench_intake.APPROVAL_NOTICE`, as before. A FIXED sentence.
APPROVED_UNTRUSTED_NOTICE = (
    "the model is approved for this console, but its binding is not trusted "
    "on this machine, so it is not an available catalog entry: \"opendox "
    "model-binding list --repo-root <repository>\" shows why, and \"opendox "
    "model-binding trust --repo-root <repository> <id>\" trusts it after "
    "showing what it would run and where it would connect; then restart this "
    "console. The credential remains in the broker's custody and this act "
    "neither mints nor reads one")

#: What the console's model approval answers when the binding it approved is
#: one the model catalog cannot list (`REASON_UNSERVABLE`): approved, and
#: still unusable, and trust cannot repair it, so this names the remedy and
#: no command that trusts (Copilot at openDox-code#82, r4175203889). Whatever
#: policy is registered: a host's cannot make it usable either. A FIXED
#: sentence.
APPROVED_UNSERVABLE_NOTICE = (
    "the model is approved for this console, but the model catalog cannot "
    "list its binding's id or its label, so no chat turn can use it, and "
    "trusting it cannot help: \"opendox model-binding list --repo-root "
    "<repository>\" shows which binding and why; correct it with \"opendox "
    "model-binding edit\" (the same id) or \"opendox model-binding remove\" "
    "and then \"add\" (a new id), each of which records trust for what it "
    "writes, then restart this console. The credential remains in the "
    "broker's custody and this act neither mints nor reads one")

#: What the console intake's hand-off is refused with when the trust policy
#: does not admit the binding it is declaring (#1144 16.3a, T007 batch M). A
#: FIXED sentence: an intake refusal's reason never carries what the request
#: did. It names the document whose broker would run, and the seam that may
#: admit one.
INTAKE_BROKER_UNTRUSTED = (
    "the console intake would hand this credential to the broker the served "
    "repository's ideation/dashboard/model-declarations.yaml names, and that "
    "broker is not trusted on this machine, so nothing was run and nothing "
    "was read. No command trusts an intake declaration's broker; a host's own "
    "trust policy (opendox.doxbench_trust.register) may admit it")


class BindingUntrusted(binding_mod.BindingRefused):
    """A binding is not trusted on this machine, so it is not used.

    Its message names the binding's id and the command that trusts it, and
    never a secret: nothing has been resolved when it is raised. A
    `BindingRefused`, so every caller that already catches the binding's one
    refusal class catches this one too."""


class TrustStoreRefused(binding_mod.BindingRefused):
    """The trust store cannot be used: it is a link, another user could write
    it, it does not read, or there is no state directory to keep it in.
    Nothing is trusted through it."""


class TrustNotRecorded(binding_mod.BindingRefused):
    """Trust was not recorded for the binding asked about: the model catalog
    refuses it (`unservable_because`), or the registered policy declined,
    answered for another binding, or failed. `add`, `edit` and `trust`
    refuse with it before they write anything."""


class TrustPolicyNotRegistered(RuntimeError):
    """Nothing is registered at the trust seam. Raised instead of answering a
    default, which is a registration a consumer makes (`policy()`)."""


class TrustPolicyAlreadyRegistered(RuntimeError):
    """A second, different policy was registered over a host's, or over the
    default after a consumer had read it."""


# ---------------------------------------------------------------------------
# the key
# ---------------------------------------------------------------------------


def binding_digest(binding) -> str:
    """The digest of a binding's CANONICAL FULL CONTENT: its stored record
    (`ModelProviderBinding.as_record()`, the record kind and all of
    `BINDING_FIELDS`), as sorted, ASCII-escaped JSON, under SHA-256.

    Canonical, so a YAML spelling that reads as the same binding (key order, a
    comment, `model` left out or written null) is the same binding, and any
    change to any field is a different one."""
    if not isinstance(binding, binding_mod.ModelProviderBinding):
        raise TypeError(
            "a digest is of a ModelProviderBinding, got "
            f"{type(binding).__name__}")
    text = json.dumps(binding.as_record(), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=True)
    return DIGEST_PREFIX + hashlib.sha256(text.encode("ascii")).hexdigest()


def resolved_root(root: Path | str) -> str:
    """The repository root as the key holds it: absolute, every link
    resolved. A checkout reached through a link is the checkout it reaches,
    and a copy elsewhere is another root."""
    return str(Path(root).resolve())


def shown(value: object) -> str:
    """A value a repository wrote, as a refusal or a disclosure prints it: in
    a JSON string's form (a list in a JSON array's). A newline, a terminal
    control sequence or any byte outside printable ASCII is escaped, so what
    is shown cannot be forged or hidden by what it shows."""
    return json.dumps(value, ensure_ascii=True)


def command_safe_id(binding_id: object) -> bool:
    """Whether `binding_id` may stand bare in a printed command: an id the
    model catalog accepts (`doxbench_model.MODEL_REFERENCE_PATTERN`, at most
    `MODEL_REFERENCE_MAX_LENGTH` characters). Its characters are ASCII
    letters, digits, `.`, `_` and `-`, which no POSIX shell expands, splits or
    quotes, and it begins with a letter or a digit, so no option parser reads
    it as an option (Copilot at openDox-code#82, r4174632060). Every other id
    is one the catalog refuses, so its binding is one no turn could use
    (`unservable_because`), and no command is printed for it (r4174783197)."""
    return (isinstance(binding_id, str)
            and len(binding_id) <= doxbench_model.MODEL_REFERENCE_MAX_LENGTH
            and re.fullmatch(doxbench_model.MODEL_REFERENCE_PATTERN,
                             binding_id) is not None)


def _quoted_path(path: object) -> str | None:
    """A path as a POSIX shell reads it back exactly (`shlex.quote`: one
    single-quoted word, inside which no shell expands anything), or None
    where a character of it is not printable: a newline, a terminal control
    sequence, a bidirectional override, or a byte the file system's name did
    not decode. Such a path is never printed in a command, because printing
    it would hand a terminal what `shown` exists to escape (r4174783197)."""
    if not isinstance(path, str) or not path or not path.isprintable():
        return None
    return shlex.quote(path)


def trust_command(binding_id: str, root: str | None, *,
                  bindings: str | None = None) -> str | None:
    """The command that trusts `binding_id` at `root`, as one line a POSIX
    shell reads back as exactly the verb's arguments, or None where it cannot
    be printed so (Copilot at openDox-code#82, r4174783197).

    `--repo-root` is required by the verb, so there is no command without a
    root. `--bindings` is given where the binding was read from a document
    named by one. The id comes last, and only an id the catalog accepts is
    printed (`command_safe_id`); each path is quoted (`_quoted_path`). An
    absolute path begins with `/` and a relative one is given as `./...`, so
    no operand reads as an option."""
    if root is None or not command_safe_id(binding_id):
        return None
    command = "opendox model-binding trust"
    for option, value in (("--repo-root", root), ("--bindings", bindings)):
        if option == "--bindings" and value is None:
            continue
        quoted = _quoted_path(value)
        if quoted is None:
            return None
        command += f" {option} {quoted}"
    return f"{command} {binding_id}"


def _command_from_the_root(binding_id: str, root: str | None,
                           bindings: str | None) -> str | None:
    """The command with the repository named `.`, to be run from its root,
    for a binding whose root is unknown or cannot be printed. A bindings
    document is named relative to that root, and only where it lies inside
    it."""
    if bindings is None:
        return trust_command(binding_id, ".")
    if root is None:
        return None
    try:
        relative = Path(bindings).relative_to(root)
    except ValueError:
        return None
    return trust_command(binding_id, ".",
                         bindings=os.path.join(".", str(relative)))


def trust_remedy(binding_id: str, root: str | None,
                 reason: str | None = None, *,
                 bindings: str | None = None) -> str:
    """What a refusal, or `list`, tells the operator to do about a binding
    that is not trusted: one sentence that ENDS with the command that trusts
    it, where a command can be printed safely (`trust_command`).

    A binding the catalog refuses gets no command, since trust cannot make it
    usable (`REMEDY_UNSERVABLE`). Where the root is unknown, or a path cannot
    be printed, the command names the repository `.` and says to run it from
    that repository's root. Where even that cannot be printed, the sentence
    says what to give the verb instead."""
    if reason == REASON_UNSERVABLE or not command_safe_id(binding_id):
        return REMEDY_UNSERVABLE
    command = trust_command(binding_id, root, bindings=bindings)
    if command is not None:
        return f"Review it, then trust it with: {command}"
    command = _command_from_the_root(binding_id, root, bindings)
    lead = ("From the root directory of the repository that declares it"
            if root is None else
            "A path it is read from cannot be printed in a command safely, "
            "so, from its repository's own root directory")
    if command is not None:
        return f"{lead}, review it, then trust it with: {command}"
    return ("A path it is read from cannot be printed in a command safely, "
            "so none is printed: review it, then run \"opendox model-binding "
            "trust\" from its repository's own root directory, with "
            "--repo-root . and --bindings naming the document it is read "
            f"from, and the id {binding_id}")


# ---------------------------------------------------------------------------
# the verdict
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class TrustVerdict:
    """What a policy says of ONE binding, in ONE form, at ONE root.

    `admits` holds it to the exact binding it was given for: the same id and
    the same digest. So a verdict cannot be carried over to another binding,
    or to the same binding after an edit. `reason` says why an untrusted one
    is untrusted, in a fixed sentence or the store's own refusal, and never
    holds a secret."""

    binding_id: str
    digest: str
    root: str | None
    trusted: bool
    basis: str
    reason: str | None = None

    @classmethod
    def trusted_for(cls, binding, *, root: Path | str | None,
                    basis: str) -> "TrustVerdict":
        """A verdict TRUSTING this exact binding. For a policy to give."""
        return cls(binding_id=binding.id, digest=binding_digest(binding),
                   root=None if root is None else resolved_root(root),
                   trusted=True, basis=basis)

    @classmethod
    def untrusted_for(cls, binding, *, root: Path | str | None, basis: str,
                      reason: str) -> "TrustVerdict":
        """A verdict REFUSING this binding, with the reason."""
        return cls(binding_id=binding.id, digest=binding_digest(binding),
                   root=None if root is None else resolved_root(root),
                   trusted=False, basis=basis, reason=reason)

    def admits(self, binding) -> bool:
        """Whether this verdict trusts exactly `binding`."""
        return (self.trusted
                and isinstance(binding, binding_mod.ModelProviderBinding)
                and binding.id == self.binding_id
                and binding_digest(binding) == self.digest)


def refusal_message(binding_id: str, root: str | None, reason: str, *,
                    bindings: str | None = None) -> str:
    """The refusal of an untrusted binding, BY NAME: the id, the reason, and
    what to do, which ends with the command that trusts it where one can be
    printed safely (`trust_remedy`). It names no secret, and nothing has been
    resolved when it is composed."""
    where = (f" in the repository at {shown(root)}" if root is not None
             else "")
    return (f"model binding {shown(binding_id)}{where} is not trusted on this "
            f"machine ({reason}), so it is not used: no broker runs, no "
            "credential reference is resolved and no endpoint is contacted. "
            f"{trust_remedy(binding_id, root, reason, bindings=bindings)}")


def require_admitted(binding, trust: TrustVerdict | None) -> None:
    """Refuse, by name, a binding that `trust` does not cover.

    Asked by every act on a binding before it spawns, reads or contacts
    anything (`doxbench_provider`). `None` is no verdict, and no verdict is no
    trust."""
    if isinstance(trust, TrustVerdict) and trust.admits(binding):
        return
    binding_id = getattr(binding, "id", "<not a binding>")
    if not isinstance(trust, TrustVerdict):
        raise BindingUntrusted(refusal_message(
            str(binding_id), None, REASON_NO_VERDICT))
    if (trust.trusted or trust.binding_id != binding_id
            or not isinstance(binding, binding_mod.ModelProviderBinding)
            or binding_digest(binding) != trust.digest):
        raise BindingUntrusted(refusal_message(
            str(binding_id), trust.root, REASON_NOT_COVERED))
    raise BindingUntrusted(refusal_message(
        trust.binding_id, trust.root, trust.reason or REASON_NEVER_TRUSTED))


def _held_to(binding, verdict: Any, *, root: Path | str) -> TrustVerdict:
    """`verdict`, held to `binding` AT `root`. A verdict for this root that
    admits exactly `binding` is returned. So is an UNTRUSTED one for exactly
    this record at this root, which carries the policy's own reason.
    Anything else is replaced by an untrusted verdict for THIS binding at
    THIS root, so a refusal never names the wrong binding, root or command:
    a verdict for another binding, or another form of this one, trusted or
    not (Copilot at openDox-code#82, r4173513795); one minted for another
    repository root, which would defeat the per-repository key (r4174310794);
    and something that is not a verdict."""
    if isinstance(verdict, TrustVerdict) and verdict.root == resolved_root(
            root):
        if verdict.admits(binding):
            return verdict
        if (not verdict.trusted and verdict.binding_id == binding.id
                and verdict.digest == binding_digest(binding)):
            return verdict
    return TrustVerdict.untrusted_for(binding, root=root, basis=BASIS_HOST,
                                      reason=REASON_NOT_COVERED)


def unservable_because(binding) -> str | None:
    """Why no chat turn could use `binding`, or None: the model catalog
    refuses its id or its label (Copilot at openDox-code#82, r4174783280).

    Judged by building the very catalog the factory would declare for it
    (`doxbench_install.brokered_catalog`), so the two cannot disagree. Asked
    BEFORE any policy is: no policy, a host's included, trusts a binding that
    could never be served, `add`, `edit` and `trust` record nothing for one
    and write nothing, and the factory declares a refusing port for one
    rather than fail at start on what a repository wrote."""
    from opendox import doxbench_install

    try:
        doxbench_install.brokered_catalog(binding)
    except doxbench_model.ModelCatalogError:
        return REASON_UNSERVABLE
    return None


def _judged(policy_of, binding, *, root: Path | str) -> TrustVerdict:
    """The verdict of the policy `policy_of()` answers, on `binding` at
    `root`, held to it. A binding the catalog refuses is untrusted before any
    policy is asked (`unservable_because`). A policy that raises trusts
    nothing, and its words are not repeated (`reason_policy_failed`)."""
    unservable = unservable_because(binding)
    if unservable is not None:
        return TrustVerdict.untrusted_for(binding, root=root,
                                          basis=BASIS_CATALOG,
                                          reason=unservable)
    try:
        verdict = policy_of().verdict(binding, root=root)
    except Exception as error:  # noqa: BLE001 - a policy that fails trusts nothing
        return TrustVerdict.untrusted_for(binding, root=root, basis=BASIS_HOST,
                                          reason=reason_policy_failed(error))
    return _held_to(binding, verdict, root=root)


def verdict_for(binding, *, root: Path | str) -> TrustVerdict:
    """The registered policy's verdict on `binding` at `root`, held to it:
    openDox's strict default registered first where nothing is (`policy`).

    What every consumer asks before it uses a binding read from a repository.
    A binding the catalog refuses is untrusted before any policy is asked
    (`unservable_because`). A policy that raises trusts nothing, and its
    words are not repeated (`reason_policy_failed`)."""
    return _judged(policy, binding, root=root)


def registered_verdict_for(binding, *,
                           root: Path | str) -> TrustVerdict | None:
    """The verdict of the policy registered NOW on `binding` at `root`, held
    to it, or None where nothing is registered. It REGISTERS NOTHING, for an
    act that is not one of the consumers that register openDox's default
    (the console's model approval).

    ONE READ OF THE SEAM (Copilot at openDox-code#82, r4177946288). The
    registration is read once, under the seam's lock, and the verdict is
    that policy's alone. Asking `is_registered()` and then `verdict_for()`
    would read the seam twice: a host that unregistered between the two
    would have the default installed by an act that promised not to, and
    its answer given in the host's place."""
    registered = _registered_now()
    if registered is None:
        return None
    return _judged(lambda: registered, binding, root=root)


def recorded_for(binding, *, root: Path | str) -> TrustVerdict:
    """Ask the registered policy to RECORD trust for `binding` at `root`, and
    return the verdict, which admits exactly `binding`.

    A policy may decline, as a governed host's does for a binding whose
    declaration is pending. So an answer that does not admit exactly this
    binding at this root is refused BY NAME (`TrustNotRecorded`), and so is
    a policy that raises, a `BindingRefused` included, naming what it raised
    and never its words. Only openDox's own store's `TrustStoreRefused`
    passes through as it is. `add`, `edit` and
    `trust` ask this before they write anything (Copilot at
    openDox-code#82, r4173513738).

    A binding the catalog refuses is refused before any policy is asked, and
    nothing is recorded for it (`unservable_because`, r4174783280)."""
    unservable = unservable_because(binding)
    if unservable is not None:
        raise TrustNotRecorded(
            f"model binding {shown(binding.id)} is not trusted on this "
            f"machine, and no trust was recorded for it: {unservable}. "
            f"{REMEDY_UNSERVABLE}")
    registered = policy()
    try:
        verdict = registered.record(binding, root=root)
    except TrustStoreRefused:
        # openDox's own store's refusal is actionable and composed from
        # nothing a policy chose: it is raised as it is. Any other policy's
        # refusal is named by its class alone, since its words are whatever
        # that policy wrapped (Copilot at openDox-code#82, review 5402101086).
        # "openDox's own" is the exact class: a host's subclass may override
        # `record` with words of its own (r4174632006).
        if type(registered) is MachineTrust:
            raise
        verdict = TrustVerdict.untrusted_for(
            binding, root=root, basis=BASIS_HOST,
            reason=reason_policy_failed(TrustStoreRefused()))
    except Exception as error:  # noqa: BLE001 - a policy that fails records nothing
        verdict = TrustVerdict.untrusted_for(
            binding, root=root, basis=BASIS_HOST,
            reason=reason_policy_failed(error))
    verdict = _held_to(binding, verdict, root=root)
    if verdict.admits(binding):
        return verdict
    raise TrustNotRecorded(
        f"the trust policy did not record trust for model binding "
        f"{shown(binding.id)} in the repository at {shown(verdict.root)} "
        f"({verdict.reason or REASON_NEVER_TRUSTED}), so it is not trusted "
        "on this machine and nothing was written")


def intake_verdict_for(binding, *, root: Path | str) -> TrustVerdict:
    """The console intake's OWN question (#1144 16.3a, T007 batch M; Copilot
    at openDox-code#82, r4173513782): may the intake hand a credential to the
    broker the served repository's declarations document names, for the
    binding it is declaring?

    It is a DISTINCT purpose. No binding's trust answers it, so a repository
    that declares a binding with the intake's very fields, and has it
    trusted, admits nothing here. A policy answers it only through its own
    `intake_verdict`. `MachineTrust` always answers no; a policy without one
    admits no intake; one that raises admits nothing."""
    try:
        ask = getattr(policy(), "intake_verdict", None)
        if not callable(ask):
            return TrustVerdict.untrusted_for(
                binding, root=root, basis=BASIS_HOST,
                reason=REASON_INTAKE_NOT_ADMITTED)
        verdict = ask(binding, root=root)
    except Exception as error:  # noqa: BLE001 - a policy that fails admits nothing
        return TrustVerdict.untrusted_for(binding, root=root, basis=BASIS_HOST,
                                          reason=reason_policy_failed(error))
    return _held_to(binding, verdict, root=root)


# ---------------------------------------------------------------------------
# the store's tree (the discipline of openDox-code#69's bundle tree)
# ---------------------------------------------------------------------------


def _unsafe_kind(mode: int, *, directory: bool) -> str | None:
    """Why a path is the wrong KIND of thing for its place, or None. A link
    is refused outright."""
    if stat.S_ISLNK(mode):
        return "is a symbolic link"
    if directory and not stat.S_ISDIR(mode):
        return "is not a directory"
    if not directory and not stat.S_ISREG(mode):
        return "is not a regular file"
    return None


def _who_can_write(mode: int) -> str:
    return "every user" if mode & 0o002 else "its group"


def _unsafe_own(info: os.stat_result, *, uid: int) -> str | None:
    """The store's OWN file and directory: this user's alone, and writable
    by no one else."""
    mode = info.st_mode
    if info.st_uid != uid:
        return f"is owned by uid {info.st_uid}, not by this user"
    if mode & 0o022:
        return (f"is writable by "
                f"{_who_can_write(mode)}"
                f" (mode {stat.S_IMODE(mode):o})")
    return None


def _unsafe_ancestor(info: os.stat_result, *, uid: int) -> str | None:
    """A directory above the store: this user's or root's, and sticky where
    others can write it, so nobody can rename what is not theirs."""
    mode = info.st_mode
    if info.st_uid not in (uid, 0):
        return f"is owned by uid {info.st_uid}, neither this user nor root"
    if mode & 0o022 and not mode & stat.S_ISVTX:
        return (f"is writable by {_who_can_write(mode)} and is not sticky "
                f"(mode {stat.S_IMODE(mode):o})")
    return None


def _unsafe_because(info: os.stat_result, *, uid: int, own: bool,
                    directory: bool = True) -> str | None:
    """Why one path of the store's tree is unsafe, or None. The rules are
    #69's (`runtime/bundle._unsafe_because`)."""
    kind = _unsafe_kind(info.st_mode, directory=directory)
    if kind is not None:
        return kind
    return (_unsafe_own(info, uid=uid) if own
            else _unsafe_ancestor(info, uid=uid))


def _store_refused_whole(path: Path | str, size: int) -> TrustStoreRefused:
    return TrustStoreRefused(
        f"the model-binding trust store {shown(str(path))} would grow to "
        f"{size} bytes, larger than the {MAX_TRUST_STORE_BYTES} it reads, so "
        "this trust is not recorded and every trust already held stays held")


def _store_failed(state: Path | str, error: OSError, *,
                  writing: bool) -> TrustStoreRefused:
    """What the store says when the system refuses an act on its tree that
    no check above named (a permission, a full disk, a path that vanished),
    BY NAME and by the system's own short word for it (Copilot at
    openDox-code#82, r4174783301). Nothing is trusted through it."""
    word = error.strerror or type(error).__name__
    if writing:
        return TrustStoreRefused(
            f"the model-binding trust store in {shown(str(state))} could not "
            f"be written ({word}), so this trust is not recorded and every "
            "trust already held stays held")
    return TrustStoreRefused(
        f"the model-binding trust store in {shown(str(state))} could not be "
        f"read ({word}), so nothing is trusted through it")


def _store_refused(path: Path | str, reason: str) -> TrustStoreRefused:
    return TrustStoreRefused(
        f"the model-binding trust store refuses {shown(str(path))}: it "
        f"{reason}, so "
        "another user could change what this machine trusts. Keep openDox's "
        "state directory (OPENDOX_STATE_DIR) where only this user can change "
        "it")


def _store_refused_dangling(path: Path | str) -> TrustStoreRefused:
    return TrustStoreRefused(
        f"the model-binding trust store refuses {shown(str(path))}: it is a "
        "symbolic link to nothing, so the store would be made or read through "
        "a path no check has judged, and nothing is trusted through it. "
        "Create what it points to, or set openDox's state directory "
        f"({STATE_DIR_SETTING}) to a directory that exists")


def _refuse_foreign_links(state: Path, *, existing_only: bool,
                          uid: int) -> None:
    """No link on the way to the store belongs to anyone but this user or
    root, who alone could point it elsewhere. And none, whoever owns it,
    points at nothing (Copilot at openDox-code#82, r4174783301): a link to
    nothing resolves to a path the tree check never judged, and the store
    would be made or read through it."""
    for component in (state, *state.parents):
        if existing_only and not os.path.lexists(component):
            continue
        info = os.lstat(component)
        if not stat.S_ISLNK(info.st_mode):
            continue
        if info.st_uid not in (uid, 0):
            raise _store_refused(
                component, f"is a symbolic link owned by uid {info.st_uid}, "
                "neither this user nor root, who could point it elsewhere")
        if not os.path.exists(component):
            raise _store_refused_dangling(component)


def _tree_to_judge(state: Path, *,
                   existing_only: bool) -> list[tuple[Path, bool]]:
    """The directories to judge, each with whether it is the store's own:
    the state directory as it resolves, and every directory above it, by its
    resolved and its spelled path."""
    if existing_only and not os.path.lexists(state):
        return [(path, False) for path in state.parents
                if os.path.lexists(path)]
    real = state.resolve()
    return [(real, True)] + [
        (path, False) for path in dict.fromkeys([*real.parents,
                                                 *state.parents])]


def _refuse_an_unsafe_tree(state: Path, *, existing_only: bool) -> None:
    """The store's directory, and every directory above it, are this user's
    to change, or the store is refused (#69's `_refuse_an_unsafe_tree`).

    With `existing_only`, only what exists is judged, which is what is asked
    before anything is created."""
    uid = os.getuid()
    _refuse_foreign_links(state, existing_only=existing_only, uid=uid)
    for directory, mine in _tree_to_judge(state, existing_only=existing_only):
        if existing_only and not os.path.lexists(directory):
            continue
        info = os.lstat(directory) if mine else os.stat(directory)
        reason = _unsafe_because(info, uid=uid, own=mine)
        if reason is not None:
            raise _store_refused(directory, reason)


def _make_private_directories(leaf: Path) -> None:
    """`leaf` and every missing directory above it, each born exactly 0700,
    each made relative to its parent's descriptor and opened without
    following a link before anything is made beneath it (#69's
    `_make_private_directories`). A directory that exists is left as it is,
    and the tree check judges it."""
    uid = os.getuid()
    missing: list[str] = []
    base = leaf
    while not os.path.lexists(base):
        missing.append(base.name)
        base = base.parent
    if not missing:
        return
    descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    path = base
    previous = os.umask(0o077)
    try:
        for name in reversed(missing):
            path = path / name
            try:
                os.mkdir(name, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass            # made first by another process: judged next
            try:
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY
                                | os.O_NOFOLLOW, dir_fd=descriptor)
            except OSError:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                reason = _unsafe_because(info, uid=uid, own=True)
                if reason is None:
                    raise
                raise _store_refused(path, reason) from None
            os.close(descriptor)
            descriptor = child
            reason = _unsafe_because(os.fstat(descriptor), uid=uid, own=True)
            if reason is not None:
                raise _store_refused(path, reason)
    finally:
        os.umask(previous)
        os.close(descriptor)


def _lock_exclusively(descriptor: int) -> None:
    """Block until this process holds the exclusive lock on the open lock file.
    It is released when the descriptor is closed. Where the platform has no
    advisory lock, an `OSError` says so, and the caller refuses."""
    if fcntl is None:
        raise OSError(errno.ENOSYS, "this platform offers no file lock")
    fcntl.flock(descriptor, fcntl.LOCK_EX)


@contextlib.contextmanager
def _store_locked(state: Path):
    """Hold the store's lock file, exclusively, for the body. The file is
    opened without following a link, created owner-only, and held to the
    store's own rules; a lock that cannot be taken refuses BY NAME, and
    nothing is recorded."""
    path = state / TRUST_LOCK_FILENAME
    try:
        # NONBLOCKING, so a FIFO in the lock file's place is refused by the
        # descriptor's own type below rather than waited on (r4178064601).
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
                             | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
                             0o600)
    except OSError:
        if os.path.lexists(path):
            reason = _unsafe_because(os.lstat(path), uid=os.getuid(),
                                     own=True, directory=False)
            if reason is not None:
                raise _store_refused(path, reason) from None
        raise _store_refused(path, "cannot be opened") from None
    try:
        reason = _unsafe_because(os.fstat(descriptor), uid=os.getuid(),
                                 own=True, directory=False)
        if reason is not None:
            raise _store_refused(path, reason)
        # EXACTLY 0600, WHATEVER THE UMASK (Copilot at openDox-code#82,
        # r4177946237). `os.open`'s mode is filtered by the umask, so under
        # a restrictive one the file is born 000: this open succeeds, and
        # every later one fails, which would leave the store unusable. Set
        # through the descriptor already judged, as `_write` sets the store.
        os.fchmod(descriptor, 0o600)
        try:
            _lock_exclusively(descriptor)
        except OSError as error:
            raise TrustStoreRefused(
                f"the model-binding trust store cannot lock {shown(str(path))}"
                f" ({error.strerror or type(error).__name__}). Without that "
                "lock another openDox process recording at the same moment "
                "could lose a trust, or restore one it replaced, so nothing "
                "is recorded. Keep openDox's state directory "
                f"({STATE_DIR_SETTING}) on a file system that supports file "
                "locks") from None
        yield
    finally:
        os.close(descriptor)


# ---------------------------------------------------------------------------
# openDox's neutral default: the per-machine store
# ---------------------------------------------------------------------------


class MachineTrust:
    """openDox's NEUTRAL default policy: trust recorded per machine, outside
    the repository, keyed `(resolved root, binding id, digest)`.

    ONE DIGEST PER `(root, id)`. Trusting a binding again, or an edit that
    records trust, replaces the digest held, so the form trusted last is the
    only one trusted. Retiring a binding forgets nothing, as direnv's allow
    list does not: the same content declared again at the same root is the
    content that was trusted.

    `state_dir` names the directory the store lives in. Unset, it is
    `runtime.config.state_dir(env)`, which openDox-code#69 defines. Where the
    runtime defines none, nothing can be trusted (`NO_STATE_DIR`).

    EVERY RECORD HOLDS THE STORE'S LOCK across its read, its change and its
    replace (`TRUST_LOCK_FILENAME`), so two processes recording at once keep
    both trusts, and neither restores a form the other replaced. A reader
    takes no lock: the replace is atomic, so it reads one whole store or the
    other.

    IT NEVER ADMITS THE CONSOLE INTAKE (`intake_verdict`): no binding's trust
    is the intake's."""

    def __init__(self, *, state_dir: Path | str | None = None,
                 env: Mapping[str, str] | None = None) -> None:
        self._state_dir = None if state_dir is None else Path(state_dir)
        self._env = env
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        where = ("the runtime's state directory" if self._state_dir is None
                 else str(self._state_dir))
        return f"MachineTrust({where})"

    # -- where ---------------------------------------------------------------

    def state_dir(self) -> Path:
        """The directory the store lives in, or a `TrustStoreRefused`. On a
        platform that cannot keep the store, the refusal comes first."""
        unsupported = unsupported_platform()
        if unsupported is not None:
            raise TrustStoreRefused(unsupported)
        if self._state_dir is not None:
            path = self._state_dir
        else:
            from opendox.runtime import config

            resolver = getattr(config, "state_dir", None)
            if resolver is None:
                raise TrustStoreRefused(NO_STATE_DIR)
            try:
                path = resolver(self._env)
            except config.ConfigurationError as error:
                raise TrustStoreRefused(
                    "the model-binding trust store has no state directory: "
                    f"{error}") from None
        if not path.is_absolute() or ".." in path.parts:
            raise TrustStoreRefused(
                "the model-binding trust store's state directory "
                f"{shown(str(path))} is not an absolute path free of '..', so "
                "it is not the one another process would find")
        return path

    def store_path(self) -> Path:
        """Where the store file is, or a `TrustStoreRefused`."""
        return self.state_dir() / TRUST_FILENAME

    def _state_dir_outside(self, root: str) -> Path:
        """The state directory, refused when it IS the served repository or
        lies inside it (#1144 16.3a, T007 batch M). `config.state_dir` takes
        any absolute path free of `..`, and a store a clone could carry is a
        store the repository writes."""
        state = self.state_dir()
        try:
            resolved = state.resolve()
        except (OSError, RuntimeError) as error:
            # A link loop, or a path the system refuses to walk (Copilot at
            # openDox-code#82, r4173876823): the store is refused by name,
            # so a verdict reads untrusted rather than the caller failing.
            raise TrustStoreRefused(
                "the model-binding trust store's state directory "
                f"{shown(str(state))} cannot be resolved "
                f"({type(error).__name__}), so the store refuses it and "
                f"trusts nothing. Set {STATE_DIR_SETTING} to a directory "
                "that resolves") from None
        served = Path(root)
        if resolved == served or served in resolved.parents:
            setting = (STATE_DIR_SETTING if self._state_dir is None
                       else "the trust store's state directory")
            where = ("is the served repository" if resolved == served
                     else "lies inside the served repository")
            raise TrustStoreRefused(
                f"{setting} ({shown(str(state))}) {where} "
                f"({shown(root)}), where a clone could carry what this "
                "machine trusts, so the model-binding trust store refuses "
                f"it and trusts nothing. Set {STATE_DIR_SETTING} to a "
                "directory outside the repositories this machine serves")
        return state

    # -- the policy ----------------------------------------------------------

    def verdict(self, binding, *, root: Path | str) -> TrustVerdict:
        """Whether this exact binding is trusted at `root` on this machine.
        A store that cannot be used trusts nothing, and says why."""
        key_root = resolved_root(root)
        try:
            state = self._state_dir_outside(key_root)
            try:
                entries = self._read(state)
            except OSError as error:
                raise _store_failed(state, error, writing=False) from None
        except TrustStoreRefused as refusal:
            return TrustVerdict.untrusted_for(
                binding, root=key_root, basis=BASIS_MACHINE_TRUST,
                reason=str(refusal))
        held = entries.get((key_root, binding.id))
        if held is None:
            return TrustVerdict.untrusted_for(
                binding, root=key_root, basis=BASIS_MACHINE_TRUST,
                reason=REASON_NEVER_TRUSTED)
        if held != binding_digest(binding):
            return TrustVerdict.untrusted_for(
                binding, root=key_root, basis=BASIS_MACHINE_TRUST,
                reason=REASON_CHANGED)
        return TrustVerdict.trusted_for(binding, root=key_root,
                                        basis=BASIS_MACHINE_TRUST)

    def record(self, binding, *, root: Path | str) -> TrustVerdict:
        """Trust this exact binding at `root` on this machine, and return the
        verdict that says so. Refused, with nothing written, when the store
        cannot be used."""
        key_root = resolved_root(root)
        digest = binding_digest(binding)
        with self._lock:
            state = self._state_dir_outside(key_root)
            try:
                _refuse_an_unsafe_tree(state, existing_only=True)
                _make_private_directories(state)
                _refuse_an_unsafe_tree(state, existing_only=False)
                with _store_locked(state):
                    entries = self._read(state)
                    entries[(key_root, binding.id)] = digest
                    self._write(state, entries)
            except OSError as error:
                # Whatever the system refused that no check named: refused
                # BY NAME, never a raw error (r4174783301).
                raise _store_failed(state, error, writing=True) from None
        return TrustVerdict.trusted_for(binding, root=key_root,
                                        basis=BASIS_MACHINE_TRUST)

    def intake_verdict(self, binding, *, root: Path | str) -> TrustVerdict:
        """The console intake's own question, which this policy always
        answers NO (`REASON_INTAKE_NOT_ADMITTED`), whatever it trusts."""
        return TrustVerdict.untrusted_for(
            binding, root=root, basis=BASIS_MACHINE_TRUST,
            reason=REASON_INTAKE_NOT_ADMITTED)

    # -- the document --------------------------------------------------------

    def _read(self, state: Path) -> dict[tuple[str, str], str]:
        """The store's entries. A store that does not exist trusts nothing.
        One that is a link, is not this user's alone, does not read, or is
        not a store this install wrote, is refused."""
        _refuse_an_unsafe_tree(state, existing_only=True)
        path = state / TRUST_FILENAME
        try:
            # NONBLOCKING (Copilot at openDox-code#82, r4178064601): a FIFO
            # in the store's place would otherwise hold this open until some
            # writer came, and `list`, the start and every verdict with it.
            # Opened so, it is refused by the descriptor's own type below,
            # judged on what was opened and not on a second look at the
            # path. A regular file reads the same either way.
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW
                                 | os.O_NONBLOCK
                                 | getattr(os, "O_CLOEXEC", 0))
        except FileNotFoundError:
            return {}
        except OSError:
            if os.path.lexists(path):
                info = os.lstat(path)
                reason = _unsafe_because(info, uid=os.getuid(), own=True,
                                         directory=False)
                if reason is not None:
                    raise _store_refused(path, reason) from None
            raise _store_refused(path, "cannot be opened") from None
        try:
            reason = _unsafe_because(os.fstat(descriptor), uid=os.getuid(),
                                     own=True, directory=False)
            if reason is not None:
                raise _store_refused(path, reason)
            chunks: list[bytes] = []
            size = 0
            while size <= MAX_TRUST_STORE_BYTES:
                chunk = os.read(descriptor, MAX_TRUST_STORE_BYTES + 1 - size)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
        finally:
            os.close(descriptor)
        if size > MAX_TRUST_STORE_BYTES:
            raise _store_refused(path, "is larger than any store this "
                                 "install writes")
        return self._entries(path, b"".join(chunks))

    @staticmethod
    def _entries(path: Path, raw: bytes) -> dict[tuple[str, str], str]:
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            raise _store_refused(path, "does not read as JSON") from None
        entries = (document.get("entries")
                   if isinstance(document, dict) else None)
        if (not isinstance(document, dict)
                or document.get("schema_version") != SCHEMA_VERSION
                or document.get("kind") != TRUST_KIND
                or not isinstance(entries, list)):
            raise _store_refused(path, "is not a trust store this install "
                                 "writes")
        held: dict[tuple[str, str], str] = {}
        for entry in entries:
            if (not isinstance(entry, dict)
                    or set(entry) != {"root", "binding_id", "digest"}
                    or not all(isinstance(entry[k], str) for k in entry)):
                raise _store_refused(path, "holds an entry this install does "
                                     "not write")
            held[(entry["root"], entry["binding_id"])] = entry["digest"]
        return held

    @staticmethod
    def _write(state: Path, entries: dict[tuple[str, str], str]) -> None:
        """Replace the store atomically: a temporary file created
        exclusively, without following a link, set to exactly 0600 before
        anything is written to it (#69's `write_authentication`)."""
        document = {
            "schema_version": SCHEMA_VERSION,
            "kind": TRUST_KIND,
            "entries": [{"root": root, "binding_id": binding_id,
                         "digest": digest}
                        for (root, binding_id), digest in sorted(
                            entries.items())],
        }
        payload = (json.dumps(document, indent=2, sort_keys=True,
                              ensure_ascii=True) + "\n").encode("ascii")
        target = state / TRUST_FILENAME
        if len(payload) > MAX_TRUST_STORE_BYTES:
            # The read bound is the write bound: a store this writes is one
            # it can read again, so a record that would outgrow it is refused
            # before anything is replaced, and every trust held stays held
            # (Copilot at openDox-code#82, r4174632086).
            raise _store_refused_whole(target, len(payload))
        temporary = state / f".{TRUST_FILENAME}.opendox-{os.getpid()}"
        try:
            os.unlink(temporary)    # an interrupted write's; a link itself, never its target
        except FileNotFoundError:
            pass
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT
                                 | os.O_EXCL | os.O_NOFOLLOW
                                 | getattr(os, "O_CLOEXEC", 0), 0o600)
        except OSError:
            # Something took the name between the unlink and this open: a
            # link, or a file, someone else put there. It is never followed
            # or written through, and nothing is trusted.
            raise _store_refused(temporary, "could not be created by this "
                                 "process alone") from None
        try:
            os.fchmod(descriptor, 0o600)
            view = memoryview(payload)
            while view:
                view = view[os.write(descriptor, view):]
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        os.close(descriptor)
        os.replace(temporary, target)


# ---------------------------------------------------------------------------
# the port an install declares for a binding it may not use
# ---------------------------------------------------------------------------


class UntrustedBindingPort:
    """THE PORT AN INSTALL DECLARES WHEN ITS BINDING IS NOT TRUSTED.

    `doxbench_install.declared_model_port_factory` answers this one in place of
    the brokered port. Its catalog lists the binding with `available: false`,
    so no turn selects it, and its `dispatch` refuses the binding by name
    (`BindingUntrusted`) without spawning, reading or contacting anything. The
    catalog's wire shape is closed, so the reason is not in it: it is in the
    factory's notice, in `opendox model-binding list`, and in a refused turn's
    message (`UNTRUSTED_TURN_MESSAGE`)."""

    __slots__ = ("_bindings", "_catalog", "_verdict")

    def __init__(self, catalog, verdict: TrustVerdict, *,
                 bindings: str | None = None) -> None:
        from opendox import doxbench_model

        if not isinstance(catalog, doxbench_model.ModelCatalog):
            raise TypeError(
                f"catalog must be a ModelCatalog, got {type(catalog).__name__}")
        if any(entry.available for entry in catalog.entries):
            raise ValueError(
                "an untrusted binding's catalog offers no available entry")
        self._catalog = catalog
        self._verdict = verdict
        self._bindings = bindings

    @property
    def timeout_seconds(self) -> float:
        return 1.0

    @property
    def verdict(self) -> TrustVerdict:
        return self._verdict

    def catalog(self):
        return self._catalog

    def dispatch(self, prompt_envelope: object) -> object:
        raise BindingUntrusted(refusal_message(
            self._verdict.binding_id, self._verdict.root,
            self._verdict.reason or REASON_NEVER_TRUSTED,
            bindings=self._bindings))

    def __repr__(self) -> str:
        return f"<model binding {shown(self._verdict.binding_id)} not trusted>"


def turn_message_for(port: object) -> str | None:
    """The FIXED sentence a chat turn is refused with where `port` is the
    refusing port the factory declared, or None for any other port (#1144
    16.3a). A binding the catalog cannot list gets `UNSERVABLE_TURN_MESSAGE`,
    which names its remedy, and every other untrusted binding
    `UNTRUSTED_TURN_MESSAGE`, which names the command that trusts it. Telling
    the operator to trust a binding `recorded_for` will never record would
    send them to a command that cannot help (Copilot at openDox-code#82,
    r4175203889)."""
    if not isinstance(port, UntrustedBindingPort):
        return None
    if port.verdict.reason == REASON_UNSERVABLE:
        return UNSERVABLE_TURN_MESSAGE
    return UNTRUSTED_TURN_MESSAGE


# ---------------------------------------------------------------------------
# the seam
# ---------------------------------------------------------------------------

#: The two names a policy carries. A third, `intake_verdict`, is OPTIONAL: a
#: policy without it admits no console intake (`intake_verdict_for`).
POLICY_CALLABLES: tuple[str, ...] = ("verdict", "record")

#: The ONE call a host makes, quoted in every refusal.
REGISTRATION_CALL = "opendox.doxbench_trust.register(<the host's policy>)"

_lock = threading.Lock()
_registered: Any = None
_is_default = False
_default_read = False


def _probe(registration: Any) -> None:
    missing = [name for name in POLICY_CALLABLES
               if not callable(getattr(registration, name, None))]
    if registration is None or missing:
        raise TypeError(
            "doxbench_trust.register() takes a trust policy: an object "
            f"carrying {', '.join(POLICY_CALLABLES)}. It lacks "
            f"{', '.join(missing) or 'them'}.")


def register(registration: Any) -> Any:
    """A HOST's trust policy, registered once, at process start. Returns it.

    The same policy again is a no-op. A different one over a host's is
    refused. Over openDox's default it replaces the default until a consumer
    has read it, and is refused after (R1Q3 (ii)'s rule, as the projection
    seams keep it)."""
    global _registered, _is_default, _default_read
    _probe(registration)
    with _lock:
        held = _registered
        if held is registration:
            return registration
        if held is None or (_is_default and not _default_read):
            _registered, _is_default, _default_read = registration, False, False
            return registration
        over_a_host = not _is_default
    if over_a_host:
        raise TrustPolicyAlreadyRegistered(
            "a host's trust policy is already registered at openDox's "
            f"model-binding trust seam ({held!r}), and {registration!r} would "
            "replace it. Registration happens ONCE, at process start. Call "
            "opendox.doxbench_trust.unregister() first if the swap is "
            "deliberate.")
    raise TrustPolicyAlreadyRegistered(
        "openDox's own strict trust policy is registered, and a consumer has "
        f"already read it, so {registration!r} cannot replace it now. "
        "Register the host's own at process start, before the model port is "
        "declared or a model-binding verb runs.")


def register_default() -> Any:
    """Register openDox's STRICT default, `MachineTrust()`, where nothing is
    registered, and return whatever is registered afterwards. For the two
    consumers (`policy()`), and never over a host."""
    global _registered, _is_default, _default_read
    with _lock:
        if _registered is None:
            _registered, _is_default, _default_read = (MachineTrust(), True,
                                                       False)
        return _registered


def current() -> Any:
    """The registered policy, or a refusal naming this seam. Reading the
    default closes its window: a host's registration after it is refused."""
    global _default_read
    with _lock:
        registered = _registered
        if registered is not None and _is_default:
            _default_read = True
    if registered is None:
        raise TrustPolicyNotRegistered(
            "no trust policy is registered at openDox's model-binding trust "
            "seam (opendox.doxbench_trust), so no binding read from a "
            "repository can be judged. openDox's own, MachineTrust, is "
            "registered by the consumers that ask (doxbench_trust.policy()), "
            "never answered here. A host registers its own at process start "
            "with\n\n    " + REGISTRATION_CALL + "\n")
    return registered


def _registered_now() -> Any:
    """The registered policy, read ONCE under the seam's lock, or None. It
    registers nothing; reading the default closes its window, as `current`
    does."""
    global _default_read
    with _lock:
        registered = _registered
        if registered is not None and _is_default:
            _default_read = True
    return registered


def policy() -> Any:
    """What a consumer asks: openDox's strict default registered where no
    host has registered one, then the registered policy."""
    register_default()
    return current()


def unregister() -> None:
    """Drop the registration and its records. For test isolation, and for a
    host tearing down."""
    global _registered, _is_default, _default_read
    with _lock:
        _registered, _is_default, _default_read = None, False, False


def is_registered() -> bool:
    """Is anything registered? Answers without reading or refusing."""
    return _registered is not None
