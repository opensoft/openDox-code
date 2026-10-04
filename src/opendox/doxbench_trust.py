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
from typing import NamedTuple
from typing import Any

from opendox import doxbench_binding as binding_mod
from opendox import doxbench_model

try:                    # POSIX; where it is absent, nothing is recorded
    import fcntl
except ImportError:     # pragma: no cover - exercised through _lock_exclusively
    fcntl = None

__all__ = [
    "APPROVED_UNTRUSTABLE_NOTICE",
    "APPROVED_UNSERVABLE_NOTICE",
    "APPROVED_UNTRUSTED_NOTICE",
    "BASIS_CATALOG",
    "BASIS_HOST",
    "BASIS_MACHINE_TRUST",
    "BASIS_REPOSITORY",
    "BROKER_WORKING_DIRECTORY",
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
    "INTAKE_HOST_NOT_ADMITTED",
    "INTAKE_BROKER_REFUSED",
    "INTAKE_NOT_ADMISSIBLE",
    "REASON_INLINE_SCRIPT",
    "REASON_UNREADABLE_COMMAND",
    "REASON_IN_REPOSITORY",
    "REASON_RECORD_FORM",
    "REMEDY_INLINE_SCRIPT",
    "REMEDY_IN_REPOSITORY",
    "REMEDY_NOT_BY_TRUST",
    "UNTRUSTABLE_TURN_MESSAGE",
    "REASON_UNSERVABLE",
    "REASON_NO_WITHDRAWAL",
    "REMEDY_UNSERVABLE",
    "binding_digest",
    "command_safe_id",
    "broker_command_refused",
    "broker_refusal",
    "in_repository_argv",
    "inline_script",
    "in_repository_program",
    "names_a_path_inside",
    "intake_admissible",
    "intake_refusal_reason",
    "restored_for",
    "trust_can_repair",
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

#: The digest's SCHEME, spelled on every digest so a stored one says how it
#: was computed: the algorithm, and the form of the canonical record it was
#: computed over (T100 follow-on, A16). Scheme 1 is `sha256:` over
#: `as_record()` with exactly `DIGEST_SCHEME_FIELDS`. A change to the record's
#: fields changes every digest, so it MUST change this prefix too (for
#: instance to `sha256/2:`): a digest stored under another prefix is then read
#: as trusted under another form of the record (`REASON_RECORD_FORM`), and
#: never as a binding that "has changed", which it has not.
DIGEST_PREFIX = "sha256:"

#: The binding fields scheme 1's canonical record holds. Pinned equal to
#: `doxbench_binding.BINDING_FIELDS` by a test, so adding a field cannot go
#: unnoticed by the digest's scheme.
DIGEST_SCHEME_FIELDS: tuple[str, ...] = (
    "id", "label", "provider", "credential_ref", "auth_kind", "approved_by",
    "endpoint", "dialect", "model", "broker_argv")

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

#: The verdict on a binding whose broker command names a file inside the
#: served repository, given before any policy is asked
#: (`in_repository_program`).
BASIS_REPOSITORY = "repository"

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

#: Why a binding the store trusted under another digest SCHEME is untrusted
#: (T100 follow-on, A16): another openDox computed that digest over another
#: form of the binding record, so it says nothing about whether this binding
#: changed. It is reviewed and trusted again, as a changed one is.
REASON_RECORD_FORM = (
    "it was trusted under another form of the binding record, by another "
    "openDox version, so it is reviewed and trusted again")

#: Why a binding whose broker command names a file inside the served
#: repository is never trusted (T100 follow-on, A2; RULED by Brett Heap,
#: openxFactory#656 comment 5982436447, item 2, "Refuse in-repo programs").
#: Trust is of the binding's record, and a pull can change such a program
#: after the record was trusted, so the broker must live outside the
#: repository.
REASON_IN_REPOSITORY = (
    "its broker command names a file inside the served repository, which a "
    "pull could change after the binding was trusted")

#: What an operator is told to do about such a binding.
REMEDY_IN_REPOSITORY = (
    "Trusting it cannot make it usable: install the broker outside the "
    "repository, then declare the binding with that command with \"opendox "
    "model-binding edit\", which records trust for what it writes")

#: Why a binding whose broker command gives a shell or an interpreter an
#: INLINE script is never trusted (T100 follow-on, A2 extended; RULED by
#: Brett Heap, openxFactory#656 comment 5983805990, "Refuse inline scripts
#: (Recommended)"). The script is text, not a file a review can pin, and it
#: can run whatever the repository holds (`/bin/sh -c "exec
#: ./tools/broker.py"`), so the program must be a real file outside the
#: served repository. A launcher (`env`, `nice`, `timeout`, ...) is unwrapped
#: to the program it starts, and that program is judged (the holder's
#: ruling, openxFactory#656 comment 5984069416). THE ACCEPTED LIMIT (same
#: ruling, item 4): a general program that runs code from its own arguments
#: (`awk`, `sed`, `find -exec`, and the like) is not judged as an inline
#: script. An `env -S` string env would not split as a shell does (one
#: holding a backslash, a `$` or a `#`, or quotes that do not close) is
#: refused as one too: what it runs cannot be read (F16.1 as T007 batch P
#: amends it; the holder's ruling, openxFactory#656 comment 5985046107, C1).
REASON_INLINE_SCRIPT = (
    "its broker command gives a shell or an interpreter an inline script, "
    "which is no file a review can pin and can run whatever the repository "
    "holds")

#: Why a binding whose broker command cannot be read to the program it runs
#: is never trusted (T100 follow-on, A2 and its rulings; Copilot at
#: openDox-code#86, r4179366319; the holder's ruling, openxFactory#656
#: comment 5985046107, C1): an option its launcher does not have, or has by
#: more than one name; an option after which what runs cannot be judged
#: from its words (`env --argv0`, `sudo --chroot`, `sudo -i`); or launchers
#: nested past what is unwrapped. What it runs cannot be judged, so it is
#: refused FAIL-CLOSED, with the inline-script remedy. (An `env -S` string
#: env would not split as a shell does is an inline script:
#: `REASON_INLINE_SCRIPT`.)
REASON_UNREADABLE_COMMAND = (
    "its broker command cannot be read to the program it runs (a launcher "
    "option it does not have, or has by more than one name, an option after "
    "which what runs cannot be judged, or launchers nested too deeply), so "
    "what it runs cannot be judged")

#: What an operator is told to do about such a binding.
REMEDY_INLINE_SCRIPT = (
    "Trusting it cannot make it usable: name the broker program itself, for "
    "example [\"pass\", \"show\", \"key\"], or a script kept outside the "
    "repository, then declare the binding with that command with \"opendox "
    "model-binding edit\", which records trust for what it writes")

#: What every refusal says, in place of a command, where `trust` itself would
#: be refused for the same reason (T100 follow-on, A1): the store cannot be
#: used, the platform cannot keep it, or a host's policy declines. No command
#: is printed that could not succeed. Its last sentence holds under every
#: policy (the holder's ruling, openxFactory#656 comment 5985490378, D2): a
#: host whose approval trusts the binding lists it trusted, with no command.
REMEDY_NOT_BY_TRUST = (
    "Resolve the cause above first: until it is resolved, trusting this "
    "binding would be refused for the same reason. Then list its bindings "
    "again: it is shown trusted, or with the command that trusts it")

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

#: What a refused chat turn says when the binding is untrusted for a reason
#: `trust` cannot repair (T100 follow-on, A1): the trust store cannot be
#: used, the platform cannot keep it, a host's policy declines, or its broker
#: lies inside the repository. Like `UNSERVABLE_TURN_MESSAGE`, it names no
#: command that trusts. A FIXED sentence, within the released failure
#: envelope's `message` bound.
UNTRUSTABLE_TURN_MESSAGE = (
    "the model binding this install declares is not usable on this machine, "
    "and trusting it cannot help yet: the trust store, the platform or the "
    "host's trust policy refuses it, or its broker command runs a program "
    "inside the repository or an inline script. Nothing was sent and "
    "nothing was contacted. Run \"opendox model-binding list --repo-root "
    "<repository>\" to see why and what to do, and restart this console")


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
    "this machine and, where trusting it can help, \"opendox model-binding "
    "trust --repo-root <repository> <id>\" trusts one after showing what it "
    "would run and where it would connect; then restart this console. A "
    "binding already trusted is unavailable for the reason this console "
    "printed when its provider refused.")

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

#: What the console's model approval answers when the binding it approved is
#: untrusted for a reason `trust` cannot repair (T100 follow-on, A1): the
#: trust store cannot be used, the platform cannot keep it, the host's
#: policy declines, or its broker lies inside the repository. A FIXED
#: sentence, which names no command that trusts.
APPROVED_UNTRUSTABLE_NOTICE = (
    "the model is approved for this console, but its binding is not usable "
    "on this machine, and trusting it cannot help yet: the trust store, the "
    "platform or the host's trust policy refuses it, or its broker command "
    "runs a program inside the repository or an inline script. \"opendox "
    "model-binding list --repo-root "
    "<repository>\" shows why and what to do; then restart this console. The "
    "credential remains in the broker's custody and this act neither mints "
    "nor reads one")

#: Why the console intake is not offered where the broker command the
#: served repository's declarations document names runs a program inside
#: the repository, or an inline script (T100 follow-on, A2 and its
#: extension; Copilot at openDox-code#86, r4179077029): every hand-off to it
#: is refused before any policy is asked. A FIXED sentence.
INTAKE_BROKER_REFUSED = (
    "the console intake is not offered: the broker command the served "
    "repository's declarations document names runs a program inside the "
    "repository, or an inline script, which no review can pin, so no "
    "hand-off to it is ever admitted. Name a broker program installed "
    "outside the repository")

#: Why the console intake is not offered where the trust policy registered
#: now could not admit its hand-off (T100 follow-on, A5). openDox's own
#: per-machine store admits no intake, so an intake offered under it would
#: open a surface every submission of which is refused. A FIXED sentence.
INTAKE_NOT_ADMISSIBLE = (
    "the console intake is not offered: its hand-off runs the broker the "
    "served repository's declarations document names, and no registered "
    "trust policy admits such a broker. openDox's own per-machine trust "
    "admits none; a host's own trust policy (opendox.doxbench_trust."
    "register) may, by answering intake_verdict")

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

#: What the console intake's hand-off is refused with when the HOST's own
#: trust policy, registered here, is what does not admit it (a pending
#: binding, say): `INTAKE_BROKER_UNTRUSTED`'s "a host's own trust policy may
#: admit it" would send the operator to the very policy that refused (the
#: holder's ruling, openxFactory#656 comment 5985490378, D3). A FIXED
#: sentence, as that one is.
INTAKE_HOST_NOT_ADMITTED = (
    "the host's trust policy does not admit this hand-off; model-binding "
    "list shows why")


def intake_refusal_reason(verdict: TrustVerdict) -> str:
    """The FIXED sentence the console intake's hand-off is refused with for
    `verdict`, which does not admit it: the host's own where the host's
    policy refused (`BASIS_HOST`, D3), and `INTAKE_BROKER_UNTRUSTED`
    otherwise."""
    if verdict.basis == BASIS_HOST:
        return INTAKE_HOST_NOT_ADMITTED
    return INTAKE_BROKER_UNTRUSTED


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


#: The reasons `trust` repairs (T100 follow-on, A1): openDox's own "never
#: trusted here", "changed since", "trusted under another form of the
#: record", and no verdict at all. Every other reason is one `trust` would
#: be refused for as well. A verdict that covers another binding
#: (`REASON_NOT_COVERED`) is a policy's invalid answer, which the same
#: policy gives when asked to record, so it is not one (Copilot at
#: openDox-code#86, r4179077004).
TRUST_REPAIRS: frozenset[str] = frozenset({
    REASON_NEVER_TRUSTED, REASON_CHANGED, REASON_RECORD_FORM,
    REASON_NO_VERDICT})


def trust_can_repair(reason: str | None) -> bool:
    """Whether `opendox model-binding trust` can repair a binding untrusted
    for `reason` (T100 follow-on, A1). No reason is the store's plain "never
    trusted"."""
    return reason is None or reason in TRUST_REPAIRS


def trust_remedy(binding_id: str, root: str | None,
                 reason: str | None = None, *,
                 bindings: str | None = None) -> str:
    """What a refusal, or `list`, tells the operator to do about a binding
    that is not trusted: one sentence that ENDS with the command that trusts
    it, where a command can be printed safely (`trust_command`).

    A binding the catalog refuses gets no command, since trust cannot make it
    usable (`REMEDY_UNSERVABLE`), and neither does one whose broker lies
    inside the repository (`REMEDY_IN_REPOSITORY`). NOR DOES ANY BINDING
    UNTRUSTED FOR A REASON `trust` WOULD REFUSE TOO (T100 follow-on, A1): a
    store that cannot be used, a platform that cannot keep one, a host
    policy's own refusal. That remedy is `REMEDY_NOT_BY_TRUST`, and a
    command is printed only where `trust_can_repair` says trust repairs the
    reason. Where the root is unknown, or a path cannot be printed, the
    command names the repository `.` and says to run it from that
    repository's root. Where even that cannot be printed, the sentence says
    what to give the verb instead."""
    if reason == REASON_UNSERVABLE or not command_safe_id(binding_id):
        return REMEDY_UNSERVABLE
    if reason == REASON_IN_REPOSITORY:
        return REMEDY_IN_REPOSITORY
    if reason in (REASON_INLINE_SCRIPT, REASON_UNREADABLE_COMMAND):
        return REMEDY_INLINE_SCRIPT
    if reason is not None and not trust_can_repair(reason):
        return REMEDY_NOT_BY_TRUST
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
    trust. A verdict is a `TrustVerdict` EXACTLY: a subclass could answer
    `admits` as it liked (T100 follow-on, A12).

    A BROKER COMMAND THE RULES REFUSE IS REFUSED HERE TOO (a program inside
    the repository, by the verdict's own root, or an inline script), so the
    defence beneath the factory holds even for a verdict a policy gave
    before the rule existed (T100 follow-on, A2 and its extension;
    `broker_refusal`)."""
    if type(trust) is TrustVerdict and trust.admits(binding):
        refused = broker_refusal(binding, root=trust.root)
        if refused is not None:
            raise BindingUntrusted(refusal_message(
                trust.binding_id, trust.root, refused))
        return
    binding_id = getattr(binding, "id", "<not a binding>")
    if type(trust) is not TrustVerdict:
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
    and something that is not a verdict, a subclass of one included, whose
    `admits` could answer anything (T100 follow-on, A12)."""
    if type(verdict) is TrustVerdict and verdict.root == resolved_root(
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
    and write nothing, the console's start passes over one (T100 follow-on,
    A3), and the trust gate beneath it declares a refusing port for one
    rather than fail on what a repository wrote."""
    from opendox import doxbench_install

    try:
        doxbench_install.brokered_catalog(binding)
    except doxbench_model.ModelCatalogError:
        return REASON_UNSERVABLE
    return None


#: The working directory every broker starts in (T100 follow-on, A2
#: extended; RULED by Brett Heap, openxFactory#656 comment 5983805990,
#: "Refuse inline scripts (Recommended)", item 2): the file system's root,
#: which lies outside every served repository. `doxbench_provider` starts
#: every broker here, and the rules below judge a broker command from here,
#: as it runs (Copilot at openDox-code#86, r4179241532, r4179366288).
BROKER_WORKING_DIRECTORY = os.path.abspath(os.sep)


class _Context(NamedTuple):
    """Where a broker command runs: its working directory, and the search
    path its program is found on (None: the platform's default,
    `os.defpath`), as the child process sees them (Copilot at
    openDox-code#86, r4179241532, r4179366288). A launcher can change both
    for the command it starts (`env -C`, `env PATH=...`, `env -i`)."""

    cwd: str
    path: str | None


def _broker_context() -> _Context:
    """The context every broker command starts in: `BROKER_WORKING_DIRECTORY`,
    and the search path the broker inherits from this process."""
    return _Context(BROKER_WORKING_DIRECTORY, os.environ.get("PATH"))


def _which(name: str, context: _Context) -> str | None:
    """`name` as the child finds it on its search path: the first executable
    file among the path's directories, a relative directory (or an empty
    entry) taken from the context's working directory, as the child takes
    it, never from this process's (r4179366288)."""
    search = context.path if context.path is not None else os.defpath
    for entry in search.split(os.pathsep):
        candidate = os.path.join(context.cwd, entry, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _resolved_path(path: str) -> str:
    """`path` with every link followed and `..` taken as the system takes it,
    or, where it cannot be resolved (an embedded NUL, which no program can
    be run with anyway; r4179077018), normalized as written."""
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return os.path.normpath(path)


def _traversed(path: str) -> list[Path]:
    """Every name the system looks up on the way to the absolute `path`,
    each in the directory it is looked up in, that directory resolved
    (links followed, `..` taken as the system takes it), and last `path`
    itself, resolved (Copilot at openDox-code#86, r4179241566). A link
    inside the repository is a name the repository controls, which a pull
    can point elsewhere, whether it points inside or out; a link outside it
    that points in reaches the repository's file."""
    names: list[Path] = []
    real = Path(os.sep)
    for part in Path(path).parts[1:]:
        if part == os.pardir:
            real = real.parent
            continue
        names.append(real / part)
        real = Path(_resolved_path(str(real / part)))
    names.append(real)
    return names


def _has_a_separator(candidate: str) -> bool:
    """Whether `candidate` is a path rather than a bare word."""
    return candidate in (".", "..") or os.sep in candidate or bool(
        os.altsep and os.altsep in candidate)


def _located(candidate: str, *, first: bool, context: _Context) -> list[str]:
    """The file one argv member could name, as an absolute path, or
    nothing: a path (with a separator) joined to the context's working
    directory, whether or not a file is there yet (a pull could add one); a
    bare word as the program the context's search path finds (`_which`),
    for the command's program; and any other bare word that names an
    existing file in the working directory."""
    if _has_a_separator(candidate):
        return [os.path.join(context.cwd, candidate)]
    if first:
        located = _which(candidate, context)
        return [located] if located is not None else []
    here = os.path.join(context.cwd, candidate)
    return [here] if os.path.lexists(here) else []


def _candidates(member: str, *, option: bool) -> list[str]:
    """What one member could name a file by, fail-closed: the member itself
    or, for an option, its value, after `=` and, for a single-dash option,
    the rest after its letter (`-I<dir>`, `-a<file>`; the holder's ruling,
    openxFactory#656 comment 5985046107, C4); and, in either, every absolute
    path it holds (`-vI/r/lib`, `PERL5OPT=-I/r/lib -Mx`)."""
    found = [] if option else [member]
    if option:
        if "=" in member:
            found.append(member.split("=", 1)[1])
        if not member.startswith("--"):
            found.append(member[2:])
    found += [member[at:] for at in range(1, len(member))
              if member[at] in (os.sep, os.altsep)]
    return [candidate for candidate in found if candidate]


def _module_paths(name: str, *, context: _Context) -> list[str]:
    """The files a module named after `-m` could be imported from: its
    whole dotted name as a path under the context's working directory,
    which `python -m` imports from first, as a package (`a/b/c`) and as a
    module (`a/b/c.py`), whether or not a file is there yet (Copilot at
    openDox-code#86, r4179241555). A namespace package needs no
    `__init__`, so a dotted name can reach any directory under the working
    directory; every package on the way is a name `_traversed` judges."""
    base = os.path.join(context.cwd, *name.split("."))
    return [base, base + ".py"]


def in_repository_program(binding, *, root: Path | str) -> str | None:
    """The member of `binding`'s broker command that names a file inside the
    served repository, or None (T100 follow-on, A2; RULED by Brett Heap,
    openxFactory#656 comment 5982436447, item 2, "Refuse in-repo programs").

    Trust is of the binding's RECORD (`binding_digest`). A program inside the
    repository is not in that record, and a pull can change it after the
    record was trusted, so a binding whose command names one is never
    trusted: it is refused by name where trust is recorded (`recorded_for`)
    and wherever it is judged (`verdict_for`, `intake_verdict_for`,
    `require_admitted`), with the remedy "install the broker outside the
    repository" (`REMEDY_IN_REPOSITORY`).

    Every member of the base invocation is asked, placeholders filled; of a
    member that is an option (`-v`, `--config=VALUE`), only its value is. The
    program itself is never an option, whatever its name, and nothing after
    a `--` member is one (Copilot at openDox-code#86, r4179076944). A
    member names a file inside the repository where, as the broker runs it
    (`in_repository_argv`), any name on the way to what it names is the
    served root or lies under it (`_traversed`), and so does a module named
    after `-m` that could be imported from there (`_module_paths`). A
    binding no broker answers has no command."""
    if binding.credential_source() != binding_mod.CREDENTIAL_FROM_BROKER:
        return None
    return in_repository_argv(binding.substituted_argv(), root=root)


def _from_the_root(candidate: str, *, program: bool, served: Path) -> bool:
    """Whether a relative `candidate` is judged from the served root as
    well: where it reads as a path the repository's author wrote, its first
    name being one the root holds (`tools/broker.py`, `tools`) or `.` or
    `..`. Not an absolute path, which names one place; not the program's
    own bare name, which the search path finds; and not a word whose first
    name the root does not hold: a URL (`https:`), or the rest of an option
    cluster (`I/usr/lib` of `-wI/usr/lib`)."""
    if os.path.isabs(candidate):
        return False
    if program and not _has_a_separator(candidate):
        return False
    head = candidate.replace(os.altsep or os.sep, os.sep).split(os.sep)[0]
    return head in (os.curdir, os.pardir) or os.path.lexists(
        os.path.join(served, head))


def in_repository_argv(members, *, root: Path | str) -> str | None:
    """The member of a broker command `members` that names a file inside
    the served repository, or None: `in_repository_program`'s rule, for a
    command no binding carries yet (the console intake's broker).

    It is judged as it runs (`_Context`; Copilot at openDox-code#86,
    r4179241532, r4179366288): from `BROKER_WORKING_DIRECTORY`, on the
    search path the broker inherits. A relative path whose first name the
    served root holds is judged from the root as well, FAIL-CLOSED, as the
    repository's author would have written it (F16.1 as T007 batch P amends
    it; `_from_the_root`), and so is a bare word, other than the program's
    own, that names a file there. A member names a file inside the
    repository where any name on the way to it (`_traversed`) is the
    served root or lies under it, for every file the member could name
    (`_candidates`): an option's value, attached or after `=`, and every
    absolute path it holds (the holder's ruling, openxFactory#656 comment
    5985046107, C4). Its launchers are unwrapped first (`_unwrapped`; the
    holder's ruling, openxFactory#656 comment 5984069416): each launcher's
    own program, and each value and operand of its (`env -C DIR`, `env
    NAME=VALUE`, `xargs -a FILE`, `time -o FILE`), are judged in the
    context they are read in, and the command it starts is judged as a
    command of its own, in the context the launchers left it. A file a
    launcher writes inside the repository is refused too, an accepted
    strictness."""
    served = Path(resolved_root(root))

    def inside(found: list[str]) -> bool:
        # A name on the way counts where it lies INSIDE the root (a link the
        # repository holds); the root itself is passed through by every path
        # joined to it, so only the end may be the root itself.
        for path in found:
            *on_the_way, end = _traversed(path)
            if end == served or served in end.parents:
                return True
            if any(served in name.parents for name in on_the_way):
                return True
        return False

    from_the_root = _Context(str(served), None)

    def named(member: str, *, option: bool, first: bool,
              context: _Context) -> list[str]:
        found: list[str] = []
        for candidate in _candidates(member, option=option):
            program = first and candidate == member
            found += _located(candidate, first=program, context=context)
            if _from_the_root(candidate, program=program, served=served):
                # FAIL-CLOSED: also as the repository's author wrote it,
                # from the served root (F16.1 as T007 batch P amends it:
                # `["python3", "tools/broker.py"]` is refused)
                found += _located(candidate, first=False,
                                  context=from_the_root)
        return found

    unwrapped = _unwrapped(members)
    for launcher, context in unwrapped.launchers:
        if inside(_located(launcher, first=True, context=context)):
            return launcher
    for value, context in unwrapped.values:
        if inside(named(value, option=value.startswith("-"), first=False,
                        context=context)):
            return value
    members = unwrapped.command
    context = unwrapped.context
    positional = False
    for index, member in enumerate(members):
        if index and member == "--" and not positional:
            positional = True
            continue
        found = named(member, option=bool(index) and member.startswith("-")
                      and not positional, first=index == 0, context=context)
        if index and members[index - 1] == "-m" and not positional:
            found += _module_paths(member, context=context)
        if inside(found):
            return member
    return None


def names_a_path_inside(value: str, *, root: Path | str) -> bool:
    """Whether `value`, or any entry of it as a path list, names a path
    inside the served repository at `root`, by `in_repository_argv`'s rule
    for an option's value: from `BROKER_WORKING_DIRECTORY` and from the
    served root, every name on the way, links followed. A broker's
    environment carries no such value (F16.1 as T007 batch P amends it)."""
    return any(part and in_repository_argv(
        ["opendox-environment", f"--value={part}"], root=root) is not None
        for part in value.split(os.pathsep))


#: Shells: an option cluster holding `c` gives one an inline script.
_SHELLS = frozenset({"sh", "bash", "rbash", "zsh", "dash", "ksh", "mksh",
                     "pdksh", "ash", "yash", "posh", "fish", "csh", "tcsh"})


class _Interpreter(NamedTuple):
    """How a shell or an interpreter reads its own options, as far as the
    inline-script rule needs (Copilot at openDox-code#86, r4179241583,
    r4179241614): the short letters that give it an inline script, those
    that take a value (attached, or the next member), those whose value is
    only ever attached (the rest of the cluster), and those after which only
    the program's own operands follow (`python -m`); any other letter, or a
    digit (`perl -l0e`), is read past; the long options that give an inline script, take
    a value, or end its options (`pwsh -File`); how many operands it reads
    before its script (`flock FILE`; None reads every member, as `su` and
    `pwsh` do); whether `+o` is an option (a shell's); and whether option
    names are compared without regard to case (PowerShell's)."""

    inline: str = ""
    takes: str = ""
    attached: str = ""
    ends: str = ""
    longs: frozenset[str] = frozenset()
    long_values: frozenset[str] = frozenset()
    long_ends: frozenset[str] = frozenset()
    operands: int | None = 0
    plus: bool = False
    folded: bool = False


_SHELL = _Interpreter(inline="c", takes="oO",
                      long_values=frozenset({"--rcfile", "--init-file"}),
                      plus=True)
_NODE = _Interpreter(
    inline="ep", takes="rC", longs=frozenset({"--eval", "--print"}),
    long_values=frozenset({
        "--require", "--import", "--loader", "--experimental-loader",
        "--conditions", "--input-type", "--env-file", "--title",
        "--inspect-port", "--redirect-warnings", "--report-dir",
        "--report-filename", "--stack-trace-limit", "--disable-warning",
        "--watch-path", "--test-reporter", "--test-reporter-destination",
        "--openssl-config", "--icu-data-dir", "--dns-result-order",
        "--unhandled-rejections", "--run"}))
_PWSH = _Interpreter(
    longs=frozenset({"-c", "-command", "--command", "-e", "-ec",
                     "-encodedcommand", "--encodedcommand", "-cwa",
                     "-commandwithargs"}),
    long_ends=frozenset({"-f", "-file", "--file"}), operands=None,
    folded=True)
_SU = _Interpreter(inline="c", takes="gGswu",
                   longs=frozenset({"--command", "--session-command"}),
                   long_values=frozenset({"--shell", "--group", "--supp-group",
                                          "--whitelist-environment", "--user"}),
                   operands=None)

#: Each shell and interpreter, by its file name without a version suffix.
_INTERPRETERS: dict[str, _Interpreter] = {
    **{shell: _SHELL for shell in _SHELLS},
    "fish": _Interpreter(
        inline="cC", longs=frozenset({"--command", "--init-command"}),
        long_values=frozenset({"--features", "--debug", "--debug-output",
                               "--profile", "--profile-startup"})),
    "python": _Interpreter(inline="c", takes="WX", ends="m",
                           long_values=frozenset(
                               {"--check-hash-based-pycs"})),
    "pypy": _Interpreter(inline="c", takes="WX", ends="m"),
    "jython": _Interpreter(inline="c", takes="WX", ends="m"),
    "perl": _Interpreter(inline="eE", takes="IMm", attached="ixdDC"),
    "ruby": _Interpreter(inline="e", takes="IrCE", attached="FKTxW"),
    "php": _Interpreter(inline="rRBE", takes="cdzt", ends="f"),
    "lua": _Interpreter(inline="e", takes="l"),
    "luajit": _Interpreter(inline="e", takes="lj", attached="O", ends="b"),
    "node": _NODE, "nodejs": _NODE, "bun": _NODE,
    "osascript": _Interpreter(inline="e", takes="ls"),
    "flock": _Interpreter(inline="c", takes="wE",
                          longs=frozenset({"--command"}),
                          long_values=frozenset({"--timeout", "--wait",
                                                 "--conflict-exit-code"}),
                          operands=1),
    "su": _SU, "runuser": _SU,
    "pwsh": _PWSH, "powershell": _PWSH,
}


class _Option(NamedTuple):
    """One option of a launcher: the option it is another name for (its
    short letter, or its own long name), and what it takes, in getopt's own
    spelling: "" nothing, ":" a value (attached, or the next member), "::"
    a value only where attached (after `=` for a long option)."""

    key: str
    takes: str


class _Launcher(NamedTuple):
    """How one launcher reads its own arguments before the command it
    starts, as its getopt does (the holder's ruling, openxFactory#656
    comment 5985046107, C1): its short options and its long options, how
    many operands precede the command (`timeout`'s duration), and whether a
    dash and a number is an option (`nice -5`)."""

    short: dict[str, str]
    long: dict[str, _Option]
    operands: int = 0
    numeric: bool = False


def _launcher(short: str, longs: str = "", *, operands: int = 0,
              numeric: bool = False) -> _Launcher:
    """A launcher's grammar from getopt's own spellings: `short` as getopt's
    option string (`C:` takes a value, `e::` one only attached), and
    `longs` as its long options, each suffixed as `short` is and followed by
    `/x` where it is short option x's other name. `--help` and `--version`
    run no command, so every launcher reads them."""
    letters: dict[str, str] = {}
    at = 0
    while at < len(short):
        letter = short[at]
        at += 1
        takes = ""
        while at < len(short) and short[at] == ":":
            takes += ":"
            at += 1
        letters[letter] = takes
    named: dict[str, _Option] = {}
    for word in ("help version " + longs).split():
        name, _slash, key = word.partition("/")
        bare = name.rstrip(":")
        named[bare] = _Option(key or bare, name[len(bare):])
    return _Launcher(letters, named, operands, numeric)


#: THE COMMON LAUNCHERS (the holder's ruling, openxFactory#656 comment
#: 5984069416, items 1 and 3), each unwrapped to the program it starts so
#: the rules judge that program: `env` (with `-S` and `NAME=value`),
#: `nice`, `nohup`, `timeout`, `stdbuf`, `setsid`, `chrt`, `ionice`,
#: `taskset`, and wrappers of the same class: `time`, `xargs`, `busybox`
#: (whose first operand is the applet it runs), `flock`, `sudo`, `doas`.
#: Each is read by its own getopt grammar, the GNU coreutils, findutils
#: and util-linux ones where there are several (C1).
_LAUNCHERS: dict[str, _Launcher] = {
    "env": _launcher(
        "a:C:iS:u:v0",
        "argv0:/a chdir:/C debug/v ignore-environment/i null/0 "
        "split-string:/S unset:/u block-signal:: default-signal:: "
        "ignore-signal:: list-signal-handling"),
    "nice": _launcher("n:", "adjustment:/n", numeric=True),
    "nohup": _launcher(""),
    "timeout": _launcher(
        "fk:ps:v", "foreground/f kill-after:/k preserve-status/p signal:/s "
        "verbose/v", operands=1),
    "stdbuf": _launcher("i:o:e:", "input:/i output:/o error:/e"),
    "setsid": _launcher("cfhVw", "ctty/c fork/f help/h version/V wait/w"),
    "chrt": _launcher(
        "abdD:efhimoP:pRrT:vV",
        "all/a batch/b deadline/d ext/e fifo/f help/h idle/i max/m other/o "
        "pid/p reset-on-fork/R rr/r sched-deadline:/D sched-period:/P "
        "sched-runtime:/T verbose/v version/V", operands=1),
    "ionice": _launcher(
        "c:hn:p:P:tu:V", "class:/c classdata:/n help/h ignore/t pid:/p "
        "pgid:/P uid:/u version/V"),
    "taskset": _launcher("achpV", "all-tasks/a cpu-list/c help/h pid/p "
                         "version/V", operands=1),
    "time": _launcher("af:o:pqvV", "append/a format:/f output:/o "
                      "portability/p quiet/q verbose/v version/V"),
    "xargs": _launcher(
        "0a:d:E:e::hI:i::L:l::n:oprs:txP:",
        "null/0 arg-file:/a delimiter:/d eof::/e replace::/I max-lines::/l "
        "max-args:/n open-tty/o interactive/p no-run-if-empty/r "
        "max-chars:/s verbose/t show-limits exit/x max-procs:/P "
        "process-slot-var: help/h"),
    "busybox": _launcher(""),
    "flock": _launcher(
        "eE:Fhnosuw:xV",
        "shared/s exclusive/x unlock/u nonblocking/n nb/n timeout:/w "
        "wait:/w conflict-exit-code:/E close/o no-fork/F verbose help/h "
        "version/V", operands=1),
    "sudo": _launcher(
        "Aa:BbC:c:D:Eeg:Hh::iKklNnPp:R:r:SsT:t:U:u:Vv",
        "askpass/A auth-type:/a background/b bell/B close-from:/C "
        "login-class:/c chdir:/D preserve-env:: edit/e group:/g set-home/H "
        "help/h host: login/i remove-timestamp/K reset-timestamp/k list/l "
        "non-interactive/n no-update/N preserve-groups/P prompt:/p "
        "chroot:/R role:/r stdin/S shell/s type:/t command-timeout:/T "
        "other-user:/U user:/u version/V validate/v"),
    "doas": _launcher("a:C:Lnsu:"),
}

#: The options after which what a command names can no longer be judged
#: from its words (C1, fail-closed): a program told another name to run as
#: (`env --argv0`), a new root every path is read in (`sudo --chroot`), and
#: a login shell's working directory, the target user's home (`sudo -i`).
#: Each makes the command unreadable.
_UNREADABLE_OPTIONS = frozenset({("env", "a"), ("sudo", "R"), ("sudo", "i")})

#: How deep launchers are unwrapped. A command that still starts with one
#: past this is refused (`REASON_UNREADABLE_COMMAND`; Copilot at
#: openDox-code#86, r4179366319).
_LAUNCHER_DEPTH = 32

#: `env NAME=value`: an assignment, whose value is judged as a path.
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

#: `nice -5`, `nice --5`, `nice -+5`: an adjustment, nice's own option.
_NUMERIC_OPTION = re.compile(r"-[-+]?[0-9]+")

#: What `env -S` splits only where its string holds none of them (C1): a
#: backslash escape (`\_` is a space to env and not to a shell's split), a
#: `${VAR}` env expands, and a `#` that begins env's comment.
_UNSPLITTABLE = frozenset("\\$#")


class _Unwrapped(NamedTuple):
    """A broker command with its launchers unwrapped: each launcher's
    program, and each value and operand of theirs (which could name a file:
    `env -C DIR`, `env NAME=VALUE`, `xargs -a FILE`), with the context each
    is read in; the command they start, and the context it runs in.
    `unreadable` is a member that cannot be read to the program it runs: an
    option its launcher does not have, or has by more than one name, an
    option after which a name cannot be judged, an `env -S` string env would
    not split as a shell does, or a launcher still left at
    `_LAUNCHER_DEPTH`."""

    launchers: tuple[tuple[str, _Context], ...]
    values: tuple[tuple[str, _Context], ...]
    command: tuple[str, ...]
    context: _Context
    unreadable: str | None = None
    unreadable_because: str = ""


class _Unreadable(Exception):
    """A launcher's argument that cannot be read (`_Unwrapped.unreadable`),
    and the reason it is refused for: `REASON_UNREADABLE_COMMAND`, or, for
    an `env -S` string env would not split as a shell does,
    `REASON_INLINE_SCRIPT` (F16.1 as T007 batch P amends it, for the
    holder's ruling, openxFactory#656 comment 5985046107, C1)."""

    def __init__(self, member: str, reason: str | None = None):
        super().__init__(member)
        self.member = member
        self.reason = reason or REASON_UNREADABLE_COMMAND


def _long_option(grammar: _Launcher, spelled: str) -> _Option | None:
    """The long option `--spelled` names, as GNU getopt_long reads it: its
    exact name, or the one option it is an unambiguous beginning of (`--chd`
    is `--chdir`). None where it names none, or more than one (`--d` may be
    `--debug` or `--default-signal`)."""
    exact = grammar.long.get(spelled)
    if exact is not None:
        return exact
    matches = {option for name, option in grammar.long.items()
               if name.startswith(spelled)}
    return matches.pop() if len(matches) == 1 else None


def _launcher_name(member: str, *, context: _Context) -> str | None:
    """The launcher `member` runs, by the name it is called by or the file
    it resolves to, or None."""
    for name in _program_names(member, first=True, context=context):
        if name in _LAUNCHERS:
            return name
    return None


def _launcher_options(name: str, rest: tuple[str, ...], context: _Context,
                      values: list[tuple[str, _Context]]):
    """Read launcher `name`'s options from `rest`, as its getopt does:
    returns how many members they took, the context they leave, and, for
    `env -S`, the words its string splits into (else None). Each value is
    added to `values` in the context it is read in. Raises `_Unreadable`."""
    grammar = _LAUNCHERS[name]

    def given(key: str, value: str | None) -> list[str] | None:
        nonlocal context
        if (name, key) in _UNREADABLE_OPTIONS:
            raise _Unreadable(value if value is not None else key)
        if name == "env" and key == "i":
            context = context._replace(path=None)
        if value is None:
            return None
        if name == "env" and key == "S":
            if _UNSPLITTABLE & set(value):
                raise _Unreadable(value, REASON_INLINE_SCRIPT)
            try:
                return shlex.split(value)
            except ValueError:
                raise _Unreadable(value, REASON_INLINE_SCRIPT) from None
        values.append((value, context))
        if (name, key) in (("env", "C"), ("sudo", "D")):
            # the directory as the system enters it, links followed
            context = context._replace(cwd=_resolved_path(
                os.path.join(context.cwd, value)))
        elif name == "env" and key == "u" and value == "PATH":
            context = context._replace(path=None)
        return None

    index = 0
    while index < len(rest):
        member = rest[index]
        if member == "--":
            return index + 1, context, None
        if name == "env" and member == "-":         # `env -`: `-i`
            context = context._replace(path=None)
            return index + 1, context, None
        if not member.startswith("-") or member == "-":
            break
        index += 1
        if grammar.numeric and _NUMERIC_OPTION.fullmatch(member):
            continue
        if member.startswith("--"):
            spelled, equals, value = member[2:].partition("=")
            option = _long_option(grammar, spelled)
            if option is None or (equals and not option.takes):
                raise _Unreadable(member)
            if not equals:
                value = None
                if option.takes == ":":
                    if index == len(rest):
                        raise _Unreadable(member)
                    value = rest[index]
                    index += 1
            split = given(option.key, value)
            if split is not None:
                return index, context, split
            continue
        at = 1
        while at < len(member):
            letter = member[at]
            at += 1
            takes = grammar.short.get(letter)
            if takes is None:
                raise _Unreadable(member)
            if not takes:
                given(letter, None)
                continue
            value = member[at:] or None
            if value is None and takes == ":":
                if index == len(rest):
                    raise _Unreadable(member)
                value = rest[index]
                index += 1
            split = given(letter, value)
            if split is not None:
                return index, context, split
            break
    return index, context, None


def _unwrapped(members) -> _Unwrapped:
    """`members` with every leading launcher unwrapped (at most
    `_LAUNCHER_DEPTH` deep), each read by its own grammar (`_LAUNCHERS`),
    from the context every broker starts in, as each changes it: `env -C`
    and `sudo -D`/`--chdir` move the working directory, and `env PATH=...`,
    `env -i` and `env -u PATH` change the search path. Each launcher's
    operands are judged as its values are."""
    command = tuple(members)
    context = _broker_context()
    launchers: list[tuple[str, _Context]] = []
    values: list[tuple[str, _Context]] = []
    for _depth in range(_LAUNCHER_DEPTH):
        if not command:
            break
        name = _launcher_name(command[0], context=context)
        if name is None:
            break
        launchers.append((command[0], context))
        rest = command[1:]
        try:
            index, context, split = _launcher_options(name, rest, context,
                                                      values)
        except _Unreadable as unreadable:
            return _Unwrapped(tuple(launchers), tuple(values), (), context,
                              unreadable=unreadable.member,
                              unreadable_because=unreadable.reason)
        if split is not None:
            # `env -S STRING`: STRING's words are env's own arguments, read
            # again by env's grammar, before what followed them.
            launchers.pop()
            command = (command[0],) + tuple(split) + rest[index:]
            continue
        if name == "env":
            while index < len(rest) and _ASSIGNMENT.match(rest[index]):
                variable, assigned = rest[index].split("=", 1)
                # A search path's every directory is judged (`PATH=a:b`).
                values.extend((part, context)
                              for part in assigned.split(os.pathsep))
                if variable == "PATH":
                    context = context._replace(path=assigned)
                index += 1
        operands = rest[index:index + _LAUNCHERS[name].operands]
        values.extend((operand, context) for operand in operands)
        command = rest[index + len(operands):]
    else:
        if command and _launcher_name(command[0],
                                      context=context) is not None:
            return _Unwrapped(tuple(launchers), tuple(values), command,
                              context, unreadable=command[0],
                              unreadable_because=REASON_UNREADABLE_COMMAND)
    return _Unwrapped(tuple(launchers), tuple(values), command, context)


def _unversioned(name: str) -> str:
    """A program's file name without a version suffix: `python3.12` and
    `python3` are `python`, `perl5.36` is `perl`."""
    return re.sub(r"[-.\d]+$", "", name) or name


def _program_names(member: str, *, first: bool,
                   context: _Context) -> set[str]:
    """The names `member` could run as: its own file name and, where it
    names a file (`_located`), that file's, links followed (`/bin/sh` may be
    `dash`, and a link named `broker` may be `python3`), each without a
    version suffix."""
    names = {Path(member).name}
    names.update(Path(_resolved_path(path)).name for path in _located(
        member, first=first, context=context))
    return {_unversioned(name) for name in names if name}


def _gives_an_inline_script(name: str, rest: tuple[str, ...]) -> bool:
    """Whether a program named `name`, followed by `rest`, is given an inline
    script, read by its own grammar (`_INTERPRETERS`): a short cluster
    letter by letter, so an attached script (`-cprint(1)`) and a cluster
    (`-Sc`, `-nle`) are read, and an option's value is skipped; and only
    until its script's operand, so an option given to the script itself
    (`python /opt/broker.py -c profile`) is the script's (Copilot at
    openDox-code#86, r4179241583, r4179241614)."""
    if name == "deno":
        return bool(rest) and rest[0] == "eval"
    spec = _INTERPRETERS.get(name)
    if spec is None:
        return False
    operands = 0
    index = 0
    while index < len(rest):
        member = rest[index]
        index += 1
        if member == "--":
            return False
        spelled = member.lower() if spec.folded else member
        if spelled.startswith("--") or (spec.folded and spelled.startswith(
                "-") and len(spelled) > 1):
            option, equals, _given = spelled.partition("=")
            if option in spec.longs:
                return True
            if option in spec.long_ends:
                return False
            if option in spec.long_values and not equals:
                index += 1
            continue
        if len(member) > 1 and (member[0] == "-" or (
                spec.plus and member[0] == "+")):
            letters = member[1:]
            at = 0
            while at < len(letters):
                letter = letters[at]
                if letter in spec.inline:
                    return True
                if letter in spec.ends:
                    return False
                if letter in spec.takes:
                    if at + 1 == len(letters):
                        index += 1          # its value is the next member
                    break
                if letter in spec.attached:
                    break
                at += 1
            continue
        if spec.operands is None:
            continue
        if operands < spec.operands:
            operands += 1
            continue
        return False                        # the script's own operand
    return False


def inline_script(members, *, root: Path | str | None = None) -> str | None:
    """The member of a broker command `members` that is a shell or an
    interpreter given an INLINE script, or None (T100 follow-on, A2
    extended; RULED by Brett Heap, openxFactory#656 comment 5983805990,
    "Refuse inline scripts (Recommended)").

    The command is asked with its launchers unwrapped (`_unwrapped`; the
    holder's ruling, openxFactory#656 comment 5984069416), so an `env -S`
    string is split and read as the command it is. Every member of the
    command as written is asked too, not the program alone, so a wrapper of
    the same class that is not in `_LAUNCHERS` (`busybox sh -c`, `xargs sh
    -c`, `sudo bash -c`) hides none. A member's name is its own file name
    and, where it resolves to a file, that file's, each without a version
    suffix (`_program_names`). `root` is not needed: the rule is the same
    for every repository.

    THE ACCEPTED LIMIT (the same ruling, item 4): a general program that
    runs code from its own arguments, such as `awk 'PROGRAM'`, `sed` or
    `find -exec`, is not judged as an inline script."""
    unwrapped = _unwrapped(members)
    for command, context in ((tuple(members), _broker_context()),
                             (unwrapped.command, unwrapped.context)):
        for index, member in enumerate(command):
            if not member or (index and member.startswith("-")):
                continue
            for name in _program_names(member, first=index == 0,
                                       context=context):
                if _gives_an_inline_script(name, command[index + 1:]):
                    return member
    return None


def broker_command_refused(members, *,
                           root: Path | str | None) -> str | None:
    """Why the broker command `members` may never be trusted, or None: it
    cannot be read to the program it runs (`REASON_UNREADABLE_COMMAND`; an
    `env -S` string env would not split as a shell does is
    `REASON_INLINE_SCRIPT`), it gives a shell or an interpreter an inline
    script (`REASON_INLINE_SCRIPT`), or, at a known `root`, it names a file inside
    the served repository (`REASON_IN_REPOSITORY`). Asked where trust is
    recorded and wherever it is judged, and of the console intake's
    broker."""
    unwrapped = _unwrapped(members)
    if unwrapped.unreadable is not None:
        return unwrapped.unreadable_because
    if inline_script(members, root=root) is not None:
        return REASON_INLINE_SCRIPT
    if root is not None and in_repository_argv(members,
                                               root=root) is not None:
        return REASON_IN_REPOSITORY
    return None


def broker_refusal(binding, *, root: Path | str | None) -> str | None:
    """`broker_command_refused` for `binding`'s broker command, placeholders
    filled, or None for a binding no broker answers."""
    if binding.credential_source() != binding_mod.CREDENTIAL_FROM_BROKER:
        return None
    return broker_command_refused(binding.substituted_argv(), root=root)


def _judged(policy_of, binding, *, root: Path | str) -> TrustVerdict:
    """The verdict of the policy `policy_of()` answers, on `binding` at
    `root`, held to it. A binding the catalog refuses, and one whose broker
    lies inside the repository, are untrusted before any policy is asked
    (`unservable_because`, `in_repository_program`). A policy that raises
    trusts nothing, and its words are not repeated
    (`reason_policy_failed`)."""
    unservable = unservable_because(binding)
    if unservable is not None:
        return TrustVerdict.untrusted_for(binding, root=root,
                                          basis=BASIS_CATALOG,
                                          reason=unservable)
    refused = broker_refusal(binding, root=root)
    if refused is not None:
        return TrustVerdict.untrusted_for(binding, root=root,
                                          basis=BASIS_REPOSITORY,
                                          reason=refused)
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


def registered_verdict_for(binding, *, root: Path | str) -> TrustVerdict:
    """The verdict on `binding` at `root`, held to it, of the policy
    registered NOW, or, where nothing is registered, of openDox's own
    default (`MachineTrust()`), asked WITHOUT REGISTERING it. For an act that
    is not one of the consumers that register the default (the console's
    model approval).

    WHERE NOTHING IS REGISTERED, THE DEFAULT'S ANSWER IS THE TRUE ONE (T100
    follow-on, A19). A host registers its policy at process start, before
    any consumer asks, so a process that has registered nothing is one whose
    next start reads this machine's store: saying the binding is untrusted
    there, when the store trusts it, would be false. The store is read, and
    nothing is registered, so a host's registration after this still wins.

    ONE READ OF THE SEAM (Copilot at openDox-code#82, r4177946288). The
    registration is read once, under the seam's lock, and the verdict is
    that policy's alone. Asking `is_registered()` and then `verdict_for()`
    would read the seam twice: a host that unregistered between the two
    would have the default installed by an act that promised not to, and
    its answer given in the host's place."""
    registered = _registered_now()
    if registered is None:
        registered = MachineTrust()
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
    refused = broker_refusal(binding, root=root)
    if refused is not None:
        raise TrustNotRecorded(
            f"model binding {shown(binding.id)} is not trusted on this "
            f"machine, and no trust was recorded for it: {refused}. "
            f"{trust_remedy(binding.id, str(root), refused)}")
    registered = None
    try:
        # INSIDE the refusal net (T100 follow-on, A13): whatever the seam
        # answers, a refusal by name follows, never a raw error.
        registered = policy()
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


#: Why a host's policy cannot take back a trust it recorded: the trust
#: policy interface records and judges trust, and withdraws none.
REASON_NO_WITHDRAWAL = (
    "the trust policy registered here records trust but offers no way to "
    "withdraw it")


def restored_for(binding, *, replacing, root: Path | str) -> None:
    """After a write that failed, take back the trust recorded for
    `replacing` (the form that write would have declared): trust `binding`,
    the earlier form the document still holds, again in its place where it
    was trusted before (T100 follow-on, A11), and, where `binding` is None
    (none was trusted, or the binding is new), withdraw it (the holder's
    ruling, openxFactory#656 comment 5985046107, C2), so a failed write
    leaves no trust for a form no document declares.

    openDox's own store does it only while it still holds `replacing`'s
    digest, under its lock (`MachineTrust.restore`), so a trust another
    process recorded meanwhile is never overwritten (Copilot at
    openDox-code#86, r4179076901). A host's policy is asked to record the
    earlier form again, as `recorded_for` asks; one cannot be asked to
    withdraw a trust (`REASON_NO_WITHDRAWAL`). Refused BY NAME where it
    cannot be done."""
    registered = _registered_now()
    if type(registered) is MachineTrust:
        registered.restore(binding, root=root, replacing=replacing)
        return
    if binding is None:
        raise TrustNotRecorded(REASON_NO_WITHDRAWAL)
    recorded_for(binding, root=root)


def intake_admissible() -> bool:
    """Whether the policy registered NOW could admit a console intake at all
    (T100 follow-on, A5): one that answers `intake_verdict` with something
    other than openDox's own per-machine "no". Read ONCE, under the seam's
    lock, and nothing is registered: where nothing is registered, the
    default a hand-off would register admits no intake, so the answer is no.

    The console intake surface offers enrolment only where this is so, so an
    install never opens a form every submission of which is refused."""
    registered = _registered_now()
    if registered is None:
        return False
    ask = getattr(registered, "intake_verdict", None)
    if not callable(ask):
        return False
    return getattr(ask, "__func__", None) is not MachineTrust.intake_verdict


def intake_verdict_for(binding, *, root: Path | str) -> TrustVerdict:
    """The console intake's OWN question (#1144 16.3a, T007 batch M; Copilot
    at openDox-code#82, r4173513782): may the intake hand a credential to the
    broker the served repository's declarations document names, for the
    binding it is declaring?

    It is a DISTINCT purpose. No binding's trust answers it, so a repository
    that declares a binding with the intake's very fields, and has it
    trusted, admits nothing here. A policy answers it only through its own
    `intake_verdict`. `MachineTrust` always answers no; a policy without one
    admits no intake; one that raises admits nothing. A broker inside the
    repository, or an inline script, is refused before any policy is asked
    (T100 follow-on, A2 and its extension)."""
    refused = broker_refusal(binding, root=root)
    if refused is not None:
        return TrustVerdict.untrusted_for(binding, root=root,
                                          basis=BASIS_REPOSITORY,
                                          reason=refused)
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


#: Why a path of the store's tree is the wrong kind of thing for its place,
#: where it is no link: what it IS, not what another user could do with it
#: (the holder's ruling, openxFactory#656 comment 5985046107, C5).
KIND_NOT_A_DIRECTORY = "is not a directory"
KIND_NOT_A_REGULAR_FILE = "is not a regular file"


def _unsafe_kind(mode: int, *, directory: bool) -> str | None:
    """Why a path is the wrong KIND of thing for its place, or None. A link
    is refused outright."""
    if stat.S_ISLNK(mode):
        return "is a symbolic link"
    if directory and not stat.S_ISDIR(mode):
        return KIND_NOT_A_DIRECTORY
    if not directory and not stat.S_ISREG(mode):
        return KIND_NOT_A_REGULAR_FILE
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
    """A store refused for what ANOTHER USER could do with it: a link, an
    owner or a mode (the tree checks). Only those say so (T100 follow-on,
    A7); every other refusal names its own cause (`_store_unusable`). So a
    path that is the wrong kind of thing for its place and no link (a
    directory, a FIFO or a socket where the store belongs) names what it is,
    with the move-aside recovery (the holder's ruling, openxFactory#656
    comment 5985046107, C5)."""
    if reason in (KIND_NOT_A_DIRECTORY, KIND_NOT_A_REGULAR_FILE):
        return _store_unusable(path, reason, RECOVER_MOVE_ASIDE)
    return TrustStoreRefused(
        f"the model-binding trust store refuses {shown(str(path))}: it "
        f"{reason}, so "
        "another user could change what this machine trusts. Keep openDox's "
        "state directory (OPENDOX_STATE_DIR) where only this user can change "
        "it")


#: The recovery for a store this install cannot read as one of its own: a
#: torn copy, another kind of document, an entry it does not write, a size it
#: never writes.
RECOVER_MOVE_ASIDE = (
    "Move it aside, then trust each binding again: listing a repository's "
    "bindings prints the command for each")

#: The recovery for a store a newer openDox wrote.
RECOVER_NEWER = (
    "Use the openDox that wrote it, or move it aside and trust each binding "
    "again: listing a repository's bindings prints the command for each")

#: The recovery for a store, or its directory, that this user cannot open or
#: write.
RECOVER_PERMISSIONS = (
    f"Make openDox's state directory ({STATE_DIR_SETTING}) and what it holds "
    "readable and writable by this user")


def _store_unusable(path: Path | str, cause: str,
                    recovery: str) -> TrustStoreRefused:
    """A store refused for what it IS, not for what another user could do
    with it (T100 follow-on, A7): its own cause, and how to recover."""
    return TrustStoreRefused(
        f"the model-binding trust store refuses {shown(str(path))}: it "
        f"{cause}, so nothing is trusted through it. {recovery}")


def _store_cannot_open(path: Path | str, error: OSError) -> TrustStoreRefused:
    """A store, or its lock file, the system will not open for this user,
    named by the system's own short word for why."""
    word = error.strerror or type(error).__name__
    return _store_unusable(path, f"cannot be opened ({word})",
                           RECOVER_PERMISSIONS)


def _store_refused_state_link(path: Path | str) -> TrustStoreRefused:
    """A state directory that is itself a symbolic link (T100 follow-on, A8;
    F16.1's ratified text, the holder's ruling on openxFactory#656 comment
    5982436447)."""
    return TrustStoreRefused(
        f"the model-binding trust store refuses {shown(str(path))}: the "
        "directory that holds the store is a symbolic link, and the store is "
        "never reached through one, so nothing is trusted through it. Set "
        f"openDox's state directory ({STATE_DIR_SETTING}) to the directory "
        "itself")


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
    would be made or read through it.

    THE STATE DIRECTORY ITSELF IS NEVER A LINK, whoever owns it (T100
    follow-on, A8). F16.1's ratified text: "With the trust file, or a
    directory that holds it, replaced by a symbolic link ... every binding
    reads untrusted". A directory ABOVE it may be one, as `/var` is on some
    systems, under the owner rule above."""
    for component in (state, *state.parents):
        if existing_only and not os.path.lexists(component):
            continue
        info = os.lstat(component)
        if not stat.S_ISLNK(info.st_mode):
            continue
        if component == state:
            raise _store_refused_state_link(component)
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
    and the tree check judges it.

    THE DIRECTORY IT STARTS FROM IS JUDGED BY ITS DESCRIPTOR before the
    first `mkdir` (T100 follow-on, A18; #69's `runtime.bundle`, which asks
    the same): an ancestor of the store, so this user's or root's, with any
    write by others only behind the sticky bit. The path-wise check before
    it asks the same question; this one asks it of the very directory that
    is written into."""
    uid = os.getuid()
    missing: list[str] = []
    base = leaf
    while not os.path.lexists(base):
        missing.append(base.name)
        base = base.parent
    if not missing:
        return
    descriptor = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    reason = _unsafe_because(os.fstat(descriptor), uid=uid, own=False)
    if reason is not None:
        os.close(descriptor)
        raise _store_refused(base, reason)
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
    except OSError as error:
        if os.path.lexists(path):
            reason = _unsafe_because(os.lstat(path), uid=os.getuid(),
                                     own=True, directory=False)
            if reason is not None:
                raise _store_refused(path, reason) from None
        raise _store_cannot_open(path, error) from None
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
            # A digest of ANOTHER SCHEME says nothing of whether this binding
            # changed: another openDox computed it over another form of the
            # record (T100 follow-on, A16).
            return TrustVerdict.untrusted_for(
                binding, root=key_root, basis=BASIS_MACHINE_TRUST,
                reason=(REASON_CHANGED if held.startswith(DIGEST_PREFIX)
                        else REASON_RECORD_FORM))
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

    def restore(self, binding, *, root: Path | str, replacing) -> bool:
        """Trust `binding` at `root` again IN PLACE OF `replacing`, or, where
        `binding` is None, withdraw `replacing`'s trust (C2), and only while
        the store still holds `replacing`'s digest for its id: one read,
        comparison and write under the store's lock (Copilot at
        openDox-code#86, r4179076901). A failed add or edit asks this, so a
        trust another process recorded meanwhile stands. Returns whether
        the store was changed."""
        key_root = resolved_root(root)
        held_for = (key_root, replacing.id)
        with self._lock:
            state = self._state_dir_outside(key_root)
            try:
                _refuse_an_unsafe_tree(state, existing_only=True)
                _make_private_directories(state)
                _refuse_an_unsafe_tree(state, existing_only=False)
                with _store_locked(state):
                    entries = self._read(state)
                    if entries.get(held_for) != binding_digest(replacing):
                        return False
                    del entries[held_for]
                    if binding is not None:
                        entries[(key_root, binding.id)] = binding_digest(
                            binding)
                    self._write(state, entries)
            except OSError as error:
                raise _store_failed(state, error, writing=True) from None
        return True

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
        except OSError as error:
            if os.path.lexists(path):
                info = os.lstat(path)
                reason = _unsafe_because(info, uid=os.getuid(), own=True,
                                         directory=False)
                if reason is not None:
                    raise _store_refused(path, reason) from None
            raise _store_cannot_open(path, error) from None
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
            raise _store_unusable(path, "is larger than any store this "
                                  "install writes", RECOVER_MOVE_ASIDE)
        return self._entries(path, b"".join(chunks))

    @staticmethod
    def _entries(path: Path, raw: bytes) -> dict[tuple[str, str], str]:
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            raise _store_unusable(path, "does not read as JSON (a torn or "
                                  "hand-edited copy)",
                                  RECOVER_MOVE_ASIDE) from None
        entries = (document.get("entries")
                   if isinstance(document, dict) else None)
        version = (document.get("schema_version")
                   if isinstance(document, dict) else None)
        if (isinstance(document, dict)
                and document.get("kind") == TRUST_KIND
                and isinstance(version, int) and not isinstance(version, bool)
                and version > SCHEMA_VERSION):
            raise _store_unusable(
                path, f"is a trust store of schema_version {version}, which "
                f"a newer openDox writes and this one ({SCHEMA_VERSION}) does "
                "not read", RECOVER_NEWER)
        if (not isinstance(document, dict)
                or version != SCHEMA_VERSION
                or document.get("kind") != TRUST_KIND
                or not isinstance(entries, list)):
            raise _store_unusable(path, "is not a trust store this install "
                                  "writes", RECOVER_MOVE_ASIDE)
        held: dict[tuple[str, str], str] = {}
        for entry in entries:
            if (not isinstance(entry, dict)
                    or set(entry) != {"root", "binding_id", "digest"}
                    or not all(isinstance(entry[k], str) for k in entry)):
                raise _store_unusable(path, "holds an entry this install "
                                      "does not write", RECOVER_MOVE_ASIDE)
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
        except OSError as error:
            if error.errno in (errno.EEXIST, errno.ELOOP):
                # Something took the name between the unlink and this open:
                # a link, or a file, someone else put there. It is never
                # followed or written through, and nothing is trusted.
                raise _store_refused(temporary, "could not be created by this "
                                     "process alone") from None
            # A directory this user cannot write, a full disk: named by the
            # system's own word (T100 follow-on, A7).
            raise _store_unusable(
                temporary, "could not be created "
                f"({error.strerror or type(error).__name__})",
                RECOVER_PERMISSIONS) from None
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
        _sync_directory(state)


def _sync_directory(state: Path) -> None:
    """Flush the state directory's entry for the replaced store (T100
    follow-on, A17), so a crash after `record` returns cannot bring back the
    store it replaced. The replace has happened by now, so a file system that
    cannot sync a directory (`EINVAL`), or any failure here, leaves the trust
    recorded, as it is: it is never reported as unrecorded."""
    try:
        descriptor = os.open(state, os.O_RDONLY | os.O_DIRECTORY
                             | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


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
    which names its remedy; one untrusted for a reason `trust` cannot repair
    (the store, the platform, the host's policy, a broker inside the
    repository) gets `UNTRUSTABLE_TURN_MESSAGE` (T100 follow-on, A1); and
    every other untrusted binding `UNTRUSTED_TURN_MESSAGE`, which names the
    command that trusts it. Telling the operator to trust a binding
    `recorded_for` will never record would send them to a command that
    cannot help (Copilot at openDox-code#82, r4175203889)."""
    if not isinstance(port, UntrustedBindingPort):
        return None
    if port.verdict.reason == REASON_UNSERVABLE:
        return UNSERVABLE_TURN_MESSAGE
    if not trust_can_repair(port.verdict.reason):
        # A reason `trust` would be refused for too (T100 follow-on, A1).
        return UNTRUSTABLE_TURN_MESSAGE
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
    host has registered one, then the registered policy.

    ONE OPERATION UNDER THE SEAM'S LOCK (T100 follow-on, A13). Registering
    the default and then reading the seam in two steps would let a host that
    unregisters between them leave the second step nothing, and a consumer
    would fail on `TrustPolicyNotRegistered`."""
    global _registered, _is_default, _default_read
    with _lock:
        if _registered is None:
            _registered, _is_default, _default_read = (MachineTrust(), True,
                                                       False)
        if _is_default:
            _default_read = True
        return _registered


def unregister() -> None:
    """Drop the registration and its records. For test isolation, and for a
    host tearing down."""
    global _registered, _is_default, _default_read
    with _lock:
        _registered, _is_default, _default_read = None, False, False


def is_registered() -> bool:
    """Is anything registered? Answers without reading or refusing."""
    return _registered is not None
