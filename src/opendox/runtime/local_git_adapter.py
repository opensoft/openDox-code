"""RULING C3's plain local git repository, as the TRIVIAL CONFORMANT
implementation of `opendox.corpus_adapter.CorpusAdapter`.

RULING C3 (opensoft/openxFactory#656 comment 5544381563, Brett Heap,
2026-09-04T17:48Z), verbatim: "standalone openDox creates and manages a plain
local git repository per project. Documents are always git-backed; commits are
the write path; a remote can be attached later. Q1 holds unchanged (the
database never holds documents), and moving a student or lab-assistant project
into a governed factory is a push, not a migration."

Design § D5 says what that makes this file: "That is the trivial conformant
implementation of the adapter's write-back operation — a corpus whose declared
governed write path is 'commit to this local repository' — so the standalone
case is NOT A MODE, it is one adapter implementation."

    THE IMPORT PATH IS `opendox.runtime.local_git_adapter` AND THE CLASS IS
    `LocalGitCorpus`. `split-opendox-two-layer-product` § 3.7's neutral
    conformance corpus needs exactly this object, so the path is stated here
    and in `docs/runtime.md`, and it costs the STANDARD LIBRARY ONLY to
    import — no FastAPI, no psycopg, no web framework — because a conformance
    suite over three destinations' adapters should not have to install a
    runtime to check one of them.

## What conformance means here, operation by operation

`corpus_adapter.CorpusAdapter` is a `runtime_checkable` Protocol with a CLOSED
six-member set, and conformance is STRUCTURAL: this module imports
`corpus_adapter` for its data types and its refusal vocabulary and does not
subclass anything, which is the property that interface's own header says the
Protocol exists for.

THE CORPUS IS THE HISTORY, NOT THE WORKING TREE, and that is the decision this
whole file turns on. `list_documents` and `read` answer from the commit the
corpus was resolved at (`git ls-tree`, `git cat-file`), and `write_back` builds
a blob, a tree and a commit with plumbing against a TEMPORARY INDEX and moves
the branch ref — so no operation writes a byte into a checkout. That is not
fastidiousness: `corpus_adapter.write_back`'s contract is "It never touches the
corpus tree — an implementation that does is refused even where the bytes would
be identical, because the gate is the act of passing through the path and not
the shape of the result." A `git add` + `git commit` implementation would
produce identical bytes and would not be conformant.

AND THAT IS WHY THE REPOSITORY THE ACT CREATES IS BARE
(`repository_act.initialize_repository`, `git init --bare`). A repository with
a checkout that this adapter writes to would have TWO answers to "what does
this project contain" — the history, which is the corpus, and a working tree
this adapter is forbidden to update — and the second would drift from the first
on every save. openDox MANAGES this repository (RULING C3's own verb): it is
storage, and a human who wants a checkout clones it. A repository openDox did
not create is still readable and writable here, and `check` is where its
divergence is REPORTED rather than silently tolerated.

The two failure modes stay the interface's, deliberately different:

  * an unresolvable CORPUS refuses (`CORPUS_ABSENT` for a path that is not
    there, `CORPUS_UNCLASSIFIABLE` for a directory that is not a repository,
    `REVISION_UNKNOWN` for a revision this repository cannot serve) and never
    degrades to an empty listing;
  * an unrecognizable DOCUMENT is REPORTED — `classify` returns `kind=None`
    with an `unclassifiable` reason naming it, and the document stays in
    `list_documents`.

`write_back` raises `CORPUS_READ_ONLY` and `WRITE_PATH_UNREACHABLE` and NO
OTHER KIND, which is the interface's own per-method row ("an implementation
raising a kind outside its row is a defect the conformance suite is entitled to
catch"). There is therefore no "stale" refusal: `basis_revision` is RECORDED in
the commit's trailers rather than adjudicated here, because the closed refusal
vocabulary has no kind for staleness and inventing one would be a seventh
member by another name. A governed corpus whose write path is a pull request
refuses a stale basis at that path; this corpus's path is a commit, and git's
own machinery is where two commits are reconciled. RULED: RULED openxFactory#656 comment 5701772032 (Brett Heap, 2026-09-16, by interactive multi-choice)
answers Q-R2 — `basis_revision` is a COMMIT TRAILER and the compare-and-swap
ref move is what decides staleness. So the trailer below is the recorded
answer, not an interim one.

NO HOME VOCABULARY. This module names no governance noun, no lifecycle word and
no header of openxFactory's corpus (RULING C2, and `corpus_adapter.py`'s own
closing paragraph). A plain local git repository knows about files, blobs and
commits; it obliges no fields, and `classify` says so by returning an empty
`required_fields` for every kind it recognizes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path

from opendox.corpus_adapter import (
    CORPUS_ABSENT,
    CORPUS_READ_ONLY,
    CORPUS_UNCLASSIFIABLE,
    CORPUS_UNREADABLE,
    DOCUMENT_UNKNOWN,
    REVISION_UNKNOWN,
    SCOPE_ALL,
    SCOPE_UNKNOWN,
    WRITE_PATH_UNREACHABLE,
    Classification,
    CorpusRef,
    CorpusRefused,
    Document,
    DocumentId,
    Finding,
    Refusal,
    ResolvedCorpus,
    WriteReceipt,
)

#: The name this adapter answers to in `project_repositories.adapter`. One
#: string, so a row written by the act and a row read by a consumer are
#: compared against the same literal.
ADAPTER_NAME = "local-git"

#: The DECLARED GOVERNED WRITE PATH, and it is RULING C3's own sentence made
#: machine-readable: "commits are the write path". `ResolvedCorpus.write_path`
#: carries it, `WriteReceipt.dispatched_to` repeats it, and a corpus that
#: cannot reach it is read-only rather than silently direct-writing.
WRITE_PATH = "local-git-commit"

#: The default branch a created repository is initialized on.
DEFAULT_BRANCH = "main"

#: What this corpus can say about a document's SHAPE, which is all a plain git
#: repository knows. Every kind obliges NO fields: obligations are governance,
#: and a pre-governed repository has none — that is the whole of what makes
#: this the trivial implementation rather than a small governed one.
KINDS_BY_SUFFIX: dict[str, str] = {
    ".md": "text",
    ".markdown": "text",
    ".txt": "text",
    ".rst": "text",
    ".yaml": "structured",
    ".yml": "structured",
    ".json": "structured",
    ".toml": "structured",
}

#: How far into a document a HEADER is looked for, where a corpus declares one
#: (`kind_field`; see `LocalGitCorpus.__init__`). The block ends at the first
#: blank line — this is only the bound for a document that has no blank line
#: near its top, so classifying one is never a scan of its whole body.
MAX_HEADER_LINES = 64

#: The corpus's ONE verdict of its own, and it is a fact about git rather than
#: a rule about documents: RULING C3 says "documents are always git-backed", so
#: a tracked file whose checkout differs from the resolved commit is a document
#: whose current bytes are not in the corpus. `check` reports it and nothing
#: else; this corpus has no other verdict machinery and does not pretend to.
UNCOMMITTED_CHANGE = "local-git/uncommitted-change"

_SAFE_ACTOR = re.compile(r"[^A-Za-z0-9._-]+")


def _refuse(kind: str, subject: str, detail: str) -> CorpusRefused:
    return CorpusRefused(Refusal(kind=kind, subject=subject, detail=detail))


@dataclass(frozen=True)
class GitRunner:
    """Every `git` invocation this package makes, in one place.

    PUBLIC because `opendox.runtime.repository_act` is a second caller: the
    repository-creation act initializes a repository and writes its first
    commit with the same plumbing, and a second module reaching into this one's
    underscore names would be a seam nobody declared.

    A FIXED ARGUMENT LIST, never a shell string: the repository path and the
    document key both come from outside and a shell would make either of them
    executable. `-C <root>` rather than `cwd=` so the call is readable in a
    traceback, and `--literal-pathspecs` so a key that begins with `:` or `*`
    is a path and not a magic pathspec.
    """

    root: Path
    executable: str = "git"
    #: A DIRECTORY FILE DESCRIPTOR THE CHILD INHERITS, for the one caller that
    #: needs `root` to name an OPEN HANDLE rather than a path a concurrent
    #: actor can re-point: `repository_act.initialize_repository` verifies the
    #: directory it created with `O_NOFOLLOW` and then hands git
    #: `/proc/self/fd/<n>` for that same descriptor, so the check and the use
    #: are the same object (Copilot review of openDox-code#26, round 10).
    #: `subprocess` closes inherited descriptors by default, so passing it is
    #: what makes `/proc/self/fd/<n>` mean anything in the child. `None` — every
    #: other caller — behaves exactly as before.
    inherit_fd: int | None = None

    def run(self, *args: str, stdin: bytes | None = None,
            env: dict[str, str] | None = None,
            timeout: float | None = None) -> subprocess.CompletedProcess[bytes]:
        argv = [self.executable, "-C", str(self.root), "--literal-pathspecs",
                *args]
        merged = {**os.environ, **(env or {})}
        try:
            return subprocess.run(argv, input=stdin, capture_output=True,
                                  check=False, env=merged, timeout=timeout,
                                  pass_fds=() if self.inherit_fd is None
                                  else (self.inherit_fd,))
        except (OSError, ValueError) as exc:
            # `ValueError` TOO, and for a caller-controlled reason: a
            # `DocumentId.key`, an `actor` or a `reason` carrying an embedded
            # NUL makes `subprocess.run` raise BEFORE any process exists, so
            # those inputs leaked a raw exception in place of `write_back`'s
            # declared refusal (Copilot review of openDox-code#26, round 6).
            #
            # A MISSING OR UNUSABLE EXECUTABLE IS A `GitCommandFailed` LIKE ANY
            # OTHER. `subprocess.run` does not return a non-zero
            # `CompletedProcess` when the program cannot be started — it raises
            # `FileNotFoundError` or `PermissionError` — so every caller that
            # translated only `GitCommandFailed` leaked an OS exception: the
            # API returned 500 and the CLI printed a traceback, in place of the
            # named refusal the act promises (Copilot review of
            # openDox-code#26). `create_repository` preflighted `git_available`
            # and the other paths did not; normalizing here covers all of them,
            # including the race where git disappears between the preflight and
            # the call.
            raise GitCommandFailed(
                args, subprocess.CompletedProcess(
                    argv, returncode=127, stdout=b"",
                    stderr=(f"{self.executable}: {exc}").encode())) from exc

    def out_bounded(self, *args: str, timeout: float,
                    env: dict[str, str] | None = None) -> bytes:
        """`out`, with a wall-clock bound and NO interactive prompting.

        For the one operation that touches a network. A stalled remote used to
        hold the request, the repository and the caller's database transaction
        indefinitely, and a remote that wanted a password would wait for one
        that is never coming (Copilot review of openDox-code#26). The
        environment below is git's own non-interactive contract:
        `GIT_TERMINAL_PROMPT=0` refuses the terminal, an empty `GIT_ASKPASS`
        and `SSH_ASKPASS` refuse the graphical one, and `BatchMode=yes` refuses
        ssh's.
        """
        merged = {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
            **(env or {}),
        }
        try:
            completed = self.run(*args, env=merged, timeout=timeout)
        except subprocess.TimeoutExpired as expired:
            raise GitCommandFailed(
                args, subprocess.CompletedProcess(
                    [], returncode=124, stdout=b"",
                    stderr=(f"timed out after {timeout:g}s with no answer from "
                            "the remote").encode())) from expired
        if completed.returncode != 0:
            raise GitCommandFailed(args, completed)
        return completed.stdout

    def out(self, *args: str, stdin: bytes | None = None,
            env: dict[str, str] | None = None) -> bytes:
        completed = self.run(*args, stdin=stdin, env=env)
        if completed.returncode != 0:
            raise GitCommandFailed(args, completed)
        return completed.stdout


#: Anything shaped like `scheme://…@…` or `user@host:path`. Used to REDACT, not
#: to validate: a git argument or a git error line can carry a remote URL, and a
#: remote URL can carry a credential.
#: A BRACKETED IPv6 HOST NEEDS NO SPECIAL CASE HERE, and that was measured
#: rather than assumed (Copilot review of openDox-code#26, round 10, which
#: reported the opposite): the host class excludes `:` so the pattern cannot
#: swallow a `scheme://`, and in `user@[::1]:repo` it matches the `[` and the
#: very next character is the `:` the form requires — so the whole run is
#: replaced, exactly as `git@host:repo` is. `test_a_bracketed_ipv6_scp_remote_
#: is_redacted_like_any_other_userinfo` pins that for every IPv6 shape, because
#: a property this pattern holds by luck is a property a later edit can lose.
#: AND THE SCHEME FORM'S USERINFO MAY CONTAIN A SPACE. `[^\s/@]*` stopped at
#: one, so `https://user:secret value@host/repo.git` — a legacy row, which this
#: act deliberately keeps readable and pushable — did not match the scheme
#: branch at all and the password was returned unchanged through map responses,
#: push failures and the CLI's evidence (Copilot review of openDox-code#26,
#: round 12). `repository_act._URL_USERINFO` (`[^/@]*@`) already REFUSES that
#: shape for a new attachment; the two halves of the rule disagreed about the
#: same character.
#:
#: THE SCP BRANCH IS DELIBERATELY NOT WIDENED, and this is the reason rather
#: than an omission. It is anchored by nothing but a lookbehind, so admitting a
#: space into `[^\s/:@]+` would let the match START at an earlier word and a
#: sentence such as "please tell bob a@b:c" would be redacted whole. It also
#: cannot carry a password: scp form is `user@host:path` with no password
#: field, and the class excludes `:` for exactly that reason. The scheme branch
#: is anchored by `scheme://` and the class still excludes `/` and a newline,
#: so widening it cannot reach past the authority it is already inside.
_CREDENTIAL_SHAPED = re.compile(
    r"[A-Za-z][A-Za-z0-9+.\-]*://[^/@\n]*@[^\s]*|(?<![\w.])[^\s/:@]+@[^\s/:@]+:[^\s]*")

#: A CREDENTIAL-SHAPED QUERY OR FRAGMENT PARAMETER, whose VALUE is replaced.
#: Userinfo is not the only place a secret rides: `https://host/r.git?token=…`
#: keeps the token out of the `@` form entirely, and this module's redaction
#: saw straight through it — which mattered because
#: `repository_act.refuse_credential_bearing_remote` REFUSES that shape for new
#: attachments while rows written before it exist and still reach a
#: `GitCommandFailed` message, a push refusal and the CLI's evidence (Copilot
#: review of openDox-code#26). The key list is the same one that refusal uses;
#: they are two halves of one rule and are kept in step by
#: `test_the_two_halves_of_the_credential_rule_name_the_same_keys`.
SECRET_PARAMETER_KEYS = (
    "token|secret|password|passwd|pwd|key|credential|auth|sig|signature")
_SECRET_KEY = re.compile(SECRET_PARAMETER_KEYS, re.IGNORECASE)

#: EVERY query or fragment parameter, whose NAME is then DECODED and tested —
#: rather than a regex over the raw text that only ever saw a literal key.
#: `https://host/x.git?%74oken=ghp_secret` contains no literal `token`, so the
#: matching half saw nothing to redact and the refusing half saw nothing to
#: refuse, while the value was every bit as much a credential (Copilot review
#: of openDox-code#26, round 5). The decode is REPEATED until it is stable
#: (bounded), because `%2574oken` is the same trick applied twice.
#: AND WHITESPACE AROUND THE NAME IS SKIPPED, in both patterns. The name class
#: excludes whitespace so that a sentence quoting a URL does not become a
#: parameter — but `urlsplit` ACCEPTS a raw space inside a URL, so
#: `https://host/x? token=ghp_secret` and `https://host/x?token =ghp_secret`
#: parsed as a query carrying `token` while this pattern saw no parameter at
#: all: neither half of the rule fired, and the value went into
#: `project_repositories.remote_url` and back out to every authenticated caller
#: (Copilot review of openDox-code#26, round 10). Spaces and tabs are stepped
#: over rather than admitted into the name, so the name that is decoded and
#: judged is the one git would use.
#: AND THE VALUE RUNS TO THE NEXT DELIMITER, NOT TO THE NEXT SPACE. `[^&#\s]*`
#: stopped a credential at the first whitespace, so `?token= ghp_secret` had its
#: EMPTY value replaced and the secret printed beside the marker, and
#: `?token=secret with more` kept everything after `secret` (Copilot review of
#: openDox-code#26, round 12). A query parameter's value ends at `&` or `#` —
#: nothing else ends it — and this module deliberately permits whitespace inside
#: a remote string, so a space is part of the value and a redaction that stops
#: there is one a secret can be walked past by putting a space in it. The
#: newline is the one boundary kept: `redact_credentials` runs over git's own
#: multi-line stderr, and a credential on one line must not take the diagnostic
#: on the next with it.
_ANY_PARAMETER = re.compile(
    r"(?P<lead>[?&#][ \t]*(?P<name>[^=&#\s]*)[ \t]*=)(?P<value>[^&#\n]*)")
_ANY_PARAMETER_ANCHORED = re.compile(
    r"(?:^|[?&#])[ \t]*(?P<name>[^=&#\s]*)[ \t]*=")
def _decoded_parameter_name(name: str) -> str:
    """A parameter name with its percent-encoding removed, decoded to a fixed
    point under a bound the NAME'S OWN LENGTH gives.

    The first cut stopped after four passes, which made the docstring's word
    false: `?%2525252574oken=…` is still `%74oken` after four and walked past
    both halves of the rule again (Copilot review of openDox-code#26, round 6).
    The second cut called the loop unbounded and asserted that every pass
    shortens the string, which `+` → space falsifies (round 8). THIS
    PARAGRAPH IS THE THIRD AND IT DESCRIBES THE CODE (round 10): the loop runs
    at most `len(name) + 1` times and stops at the first pass that changes
    nothing. That bound cannot cut a decode short, because each pass either
    removes a `%XX` escape — three characters becoming one — or turns a `+`
    into a space, and neither can be undone by a later pass, so a name of
    length n reaches its fixed point in at most n passes.

    WORST-CASE WORK IS QUADRATIC IN THE NAME, and that is bounded where the
    value enters: `repository_act.refuse_credential_bearing_remote` refuses a
    remote URL longer than `MAX_REMOTE_URL_CHARS` before this is ever reached,
    so a nested `%2525…` chain cannot be made long enough to matter (Copilot
    review of openDox-code#26, round 10). The other caller is
    `redact_credentials` over git's own stderr, which this process bounds by
    reading a finished command's output.
    """
    # BOUNDED BY THE NAME'S OWN LENGTH, and not by an assertion that every
    # pass shortens it: `unquote_plus` also turns `+` into a SPACE, which
    # changes the string without shortening it — so a harmless `...?a+b=1`
    # tripped that assertion and made both the refusal and the redaction raise,
    # a 500 where the answer was "this is not a credential" (Copilot review of
    # openDox-code#26, round 8). The docstring above argues the termination.
    for _ in range(len(name) + 1):
        once = urllib.parse.unquote_plus(name)
        if once == name:
            return name
        name = once
    return name


def names_a_secret_parameter(text: str) -> bool:
    """Whether `text` carries a credential-shaped query or fragment parameter.

    THE ONE PLACE THE QUESTION IS ASKED, by both halves of the rule: what may
    not be STORED (`repository_act.refuse_credential_bearing_remote`) and what
    must not be PRINTED (`redact_credentials`). They drifted apart once over
    the key list and once over percent-encoding; sharing the predicate is what
    stops a third drift.
    """
    return any(_SECRET_KEY.search(_decoded_parameter_name(match.group("name")))
               for match in _ANY_PARAMETER_ANCHORED.finditer(text))


def redact_credentials(text: str) -> str:
    """Replace anything shaped like a credential-bearing URL with a marker.

    WHY AN ERROR MESSAGE NEEDS THIS. `GitCommandFailed` used to format its
    whole argv, so a failed `git remote add <url>` put the caller's URL — and
    any credential in it — into `str(exc)`, which the API and the CLI return
    verbatim. That defeated the credential-free guarantee `attach_remote`
    makes, in the one path where the value is most likely to be wrong and
    therefore most likely to be logged (Copilot review of openDox-code#26).
    git's own stderr gets the same treatment, because it echoes the remote it
    could not reach.

    AND THE PARAMETER NAME IS DECODED BEFORE IT IS JUDGED, which the first cut
    did not do: `?%74oken=ghp_secret` carries no literal `token`, so an error
    or a legacy remote in that shape was returned unchanged (Copilot review of
    openDox-code#26, round 5). `names_a_secret_parameter` is the shared
    predicate, so the refusing half cannot answer this question differently.

    TWO SHAPES, NOT ONE. The userinfo form is replaced whole; a credential in a
    QUERY OR FRAGMENT parameter has only its VALUE replaced, so the refusal can
    still say which host would not answer — the host is not the secret, and a
    push failure an operator cannot locate is a refusal that costs more than it
    protects.
    """
    def _redact_value(match: re.Match[str]) -> str:
        if _SECRET_KEY.search(_decoded_parameter_name(match.group("name"))):
            return match.group("lead") + "<redacted>"
        return match.group(0)

    return _ANY_PARAMETER.sub(
        _redact_value, _CREDENTIAL_SHAPED.sub("<redacted-url>", text))


class GitCommandFailed(Exception):
    """An internal signal. Never escapes: every caller converts it to a Refusal.

    `str()` carries the SUBCOMMAND, the exit code and a redacted stderr — never
    the full argument vector. The vector is on `args_run` for a debugger that
    already has the process's own confidence; it is not in the message that
    reaches an API response.
    """

    def __init__(self, args: tuple[str, ...],
                 completed: subprocess.CompletedProcess[bytes]) -> None:
        self.args_run = args
        self.completed = completed
        subcommand = args[0] if args else "(none)"
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        super().__init__(
            f"git {subcommand} exited {completed.returncode}: "
            f"{redact_credentials(stderr)}")


def git_identity(actor: str) -> dict[str, str]:
    """The `GIT_AUTHOR_*` / `GIT_COMMITTER_*` environment for one actor.

    Git needs a name AND an address. The address is under the reserved
    `.invalid` top-level domain (RFC 2606), so a commit carries a
    syntactically valid address that cannot route anywhere and cannot be
    mistaken for a real one — inventing `first.last@some-company.com` from a
    display name would put a plausible, wrong address in permanent history. A
    caller that has a real address supplies `actor` as `Name <address>`, which
    git parses itself.

    Module level, and public, because `opendox.runtime.repository_act` writes
    the repository's first commit with the same identity.
    """
    if "<" in actor and actor.rstrip().endswith(">"):
        name, _, address = actor.partition("<")
        name = name.strip() or "opendox"
        address = address.rstrip(">").strip()
        return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": address,
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": address}
    slug = _SAFE_ACTOR.sub("-", actor).strip("-") or "opendox"
    address = f"{slug}@opendox.invalid"
    return {"GIT_AUTHOR_NAME": actor or "opendox", "GIT_AUTHOR_EMAIL": address,
            "GIT_COMMITTER_NAME": actor or "opendox",
            "GIT_COMMITTER_EMAIL": address}


def git_available(executable: str = "git") -> bool:
    """Whether the `git` this adapter shells out to is on PATH.

    Answered here so a caller can refuse at the act — or a suite can skip with
    a reason — rather than discovering it inside a commit.
    """
    return shutil.which(executable) is not None


class LocalGitCorpus:
    """A plain local git repository, read and written through its own history.

    Structurally conformant with `corpus_adapter.CorpusAdapter`: six methods,
    no seventh, and nothing inherited.
    """

    #: THE THREE PER-CORPUS CONSTRUCTION DATA, and why they are parameters.
    #: RULED openxFactory#656 comment 5714365086 (Brett Heap, 2026-09-17, by
    #: interactive multi-choice), Q-F2 (a). `split-opendox-two-layer-product`
    #: § 3.7's neutral conformance corpus is READ by this class, and a read-only
    #: measurement of it (helper `floor37`, 2026-09-17) put this reader at
    #: **11 of 17** checks: five of the six failures had one cause, and it was
    #: architectural rather than sloppy — what openxFactory's own adapter takes
    #: as per-corpus construction data, this class asserted as module
    #: constants. A reader that hard-codes a corpus's terms can only answer for
    #: corpora that happen to share them.
    #:
    #:   * `write_path` — the DECLARED governed write path. `WRITE_PATH` is
    #:     RULING C3's "commits are the write path" and stays the DEFAULT, but
    #:     a corpus that declares NO governed write path is a legal corpus this
    #:     reader may be pointed at, and it was impossible to express: every
    #:     resolution advertised `local-git-commit`, so `write_back`'s own
    #:     `CORPUS_READ_ONLY` branch — correct, and three lines long — was
    #:     unreachable, and a write at a read-only corpus RETURNED A RECEIPT and
    #:     moved a ref. Degrading a refusal to a result is the one thing a
    #:     reader over a corpus it does not own must never do.
    #:   * `kind_field` / `required_fields` — the classification vocabulary.
    #:     `KINDS_BY_SUFFIX` is what a plain local git repository knows and
    #:     stays the default; a corpus that declares its kind in a header (the
    #:     neutral corpus does, as `Type:`) was classified by file suffix
    #:     instead, so three documents holding one complete, one
    #:     field-absent and one unrecognizable came back as three `text`
    #:     documents with nothing missing and nothing unrecognizable.
    #:
    #: The defaults ARE today's behaviour, exactly: nothing in this leg passes
    #: any of the three, and `test_the_defaults_are_the_behaviour_this_class_had`
    #: holds them to it. What changes is that the reader can now be HANDED a
    #: corpus's terms instead of asserting its own — which is the pattern
    #: `corpus_adapter`'s own header endorses ("a module of plain functions has
    #: nowhere to carry per-corpus construction data").
    #:
    #: THERE IS NO `branch` PARAMETER, and its absence is the decision.
    #: `__init__` took one and stored it, and nothing ever read it: the ref
    #: `write_back` moves is the one HEAD points at (see `_served_ref`, which
    #: argues why), so `LocalGitCorpus(branch="master")` behaved exactly like
    #: the default while advertising a branch selection it did not make
    #: (Copilot review of openDox-code#26). A parameter that cannot change an
    #: outcome is removed rather than wired up, because wiring it up would
    #: reintroduce the assumption `_served_ref` exists to refuse.
    def __init__(self, *, executable: str = "git",
                 write_path: str | None = WRITE_PATH,
                 kind_field: str | None = None,
                 required_fields: tuple[str, ...] = ()) -> None:
        self._executable = executable
        self._write_path = write_path
        self._kind_field = kind_field
        self._required_fields = tuple(required_fields)

    # -- resolve ----------------------------------------------------------

    def resolve(self, ref: CorpusRef) -> ResolvedCorpus:
        """Which checkout, which revision, which scopes, which write path."""
        location = Path(ref.location).expanduser()
        # THE FILESYSTEM PROBES ARE TRANSLATED TOO. `exists()`, `is_dir()` and
        # `resolve()` all raise `PermissionError` for a path whose parent is
        # present and not searchable, and `resolve()` can raise `OSError` for a
        # symlink loop — so a location this adapter could not READ left an OS
        # exception where the protocol promises a refusal, and the API turned
        # it into a 500 (Copilot review of openDox-code#26, round 12,
        # suppressed). A missing path and an unreadable one are still different
        # answers.
        try:
            if not location.exists():
                raise _refuse(CORPUS_ABSENT, ref.location,
                              "no such path; a plain local git repository is "
                              "created by the repository act before it is "
                              "resolved")
            if not location.is_dir():
                # `CORPUS_UNREADABLE`, NOT `CORPUS_UNCLASSIFIABLE`, and the
                # interface's own comments are the argument: `CORPUS_UNREADABLE`
                # is "it is there and cannot be read", `CORPUS_UNCLASSIFIABLE`
                # is "the CORPUS's shape, not a document's". A regular file at
                # the location is the first: there is something there and no
                # corpus can be read out of it. The neutral conformance
                # corpus's own `not-a-directory` case holds every reader to
                # `corpus-unreadable`, openxFactory's adapter answers that, and
                # this one answered the other — a one-word vocabulary defect
                # that made an otherwise conformant reader fail a check
                # (RULED openxFactory#656 comment 5714365086, Q-F2 (a);
                # measured by helper `floor37`, 2026-09-17).
                # `CORPUS_UNCLASSIFIABLE` keeps the case it is for: a DIRECTORY
                # that is not a git repository, below.
                raise _refuse(CORPUS_UNREADABLE, ref.location,
                              "the location is a file, not a repository "
                              "directory")
            resolved_location = location.resolve()
        except OSError as exc:
            raise _refuse(CORPUS_UNREADABLE, ref.location,
                          f"the location could not be read ({exc.__class__.__name__})"
                          ) from exc
        git = GitRunner(resolved_location, self._executable)
        try:
            git.out("rev-parse", "--git-dir")
        except GitCommandFailed as failed:
            raise _refuse(CORPUS_UNCLASSIFIABLE, str(location),
                          f"the directory is not a git repository ({failed})"
                          ) from failed
        # THE REPOSITORY THIS LOCATION *IS*, NEVER THE ONE IT IS INSIDE.
        # `rev-parse --git-dir` WALKS UP: an ordinary directory inside somebody
        # else's checkout answers it, so this resolved that checkout — at the
        # ENCLOSING repository's HEAD — instead of refusing. Three things then
        # went wrong together, measured end to end by helper `floor37`
        # (2026-09-17) on one ordinary repository and one ordinary
        # subdirectory: `list_documents` ran `ls-tree` with `-C <location>` and
        # returned keys relative to that PREFIX, while `read` asked `cat-file
        # blob <rev>:<key>`, which git resolves from the repository ROOT — so a
        # document the listing served was refused `DOCUMENT_UNKNOWN`, the
        # listing/read contract this module fixed for gitlinks broken again by
        # another route — and `write_back` COMMITTED INTO THAT REPOSITORY and
        # moved its branch, writing at the root a path the caller never named.
        # It is reachable inside this product: `OPENDOX_PROJECT_REPOSITORY_ROOT`
        # defaults to the RELATIVE `var/projects`, so a `var/projects/<id>`
        # directory that exists and is not a repository — a create interrupted,
        # a repository removed, a directory restored from a backup — sits
        # inside whatever checkout the process was started in.
        # `refuse_unusable_location` guards the CREATE path; nothing guarded
        # this one.
        # RULED openxFactory#656 comment 5714365086, Q-F3 (a): fixed here, now.
        root = self._repository_root(git, str(location))
        if root != resolved_location:
            raise _refuse(
                CORPUS_UNCLASSIFIABLE, str(location),
                f"this directory is not a git repository; it is INSIDE one, "
                f"whose root is {root}. A corpus is a repository, not a path "
                "within one: resolving it here would serve keys relative to "
                "this prefix, read them from the repository root, and write "
                "back into a repository nobody named. Point the corpus at "
                f"{root}, or create a repository here.")

        # A PINNED REVISION DOES NOT NEED HEAD. `CorpusRef.revision` is the
        # pinned form of this interface, and asking `_head` first meant a
        # repository with a detached, malformed or unreadable HEAD was refused
        # before the revision the caller actually named was ever looked up —
        # a corpus this adapter can serve, refused for a fact about a ref the
        # request does not use (Copilot review of openDox-code#26, round 12,
        # suppressed).
        if ref.revision is not None:
            revision = self._resolve_revision(git, ref.revision, str(location))
        else:
            revision = self._head(git, str(location))

        # THE WRITE PATH IS ANSWERED HERE AND NOT AT THE FIRST WRITE, which is
        # the interface's rule: "a read-only corpus is a fact about the corpus,
        # and discovering it by attempting a write is how a caller ends up with
        # a half-built edit and nowhere to put it."
        #
        # AND A CORPUS THAT DECLARES NONE IS ANSWERED WITHOUT ASKING THE
        # FILESYSTEM ANYTHING: `write_path=None` is read-only by declaration,
        # not by reachability, and probing for a write path a corpus does not
        # have would be this reader inventing one (RULED 5714365086, Q-F2).
        if self._write_path is None:
            return ResolvedCorpus(
                ref=ref, location=str(resolved_location), revision=revision,
                scopes=(SCOPE_ALL,), write_path=None,
                write_path_available=False)
        try:
            git_dir = Path(git.out("rev-parse", "--absolute-git-dir")
                           .decode().strip())
            # THE PLACES A WRITE ACTUALLY TOUCHES, not the directory that
            # contains them. `write_back` hashes an object (`objects/`), writes
            # a temporary index (the git dir itself) and moves a ref
            # (`refs/heads/<branch>`), so a repository whose root is writable
            # and whose `objects/` is read-only advertised an available write
            # path and then failed inside the commit — which is exactly the
            # discovery order this interface's own rule forbids: "a read-only
            # corpus is a fact about the corpus" (Copilot review of
            # openDox-code#26, round 12, suppressed).
            #
            # THE SERVED REF'S OWN PARENT, not `refs/`. `update-ref` writes and
            # locks `refs/heads/<branch>`, so a `refs/` that is writable while
            # `refs/heads/` is not advertised a usable write path and the
            # refusal arrived after the blob, the tree and the commit had been
            # created — unreachable objects, and the same forbidden discovery
            # order one level down (round 12, suppressed). A directory that
            # does not exist yet is answered by the nearest ancestor that does,
            # since that is where it would be created — a repository using only
            # packed refs has no `refs/heads/` until the first write.
            #
            # AND EXECUTE AS WELL AS WRITE. `os.access(d, W_OK)` is true for a
            # directory with no SEARCH permission, in which git can create
            # nothing at all (round 12): both bits are what "a write can land
            # here" means for a directory.
            served = self._writable_ref_home(git, git_dir, str(location))
            reachable = all(
                os.access(path, os.W_OK | os.X_OK)
                for path in (git_dir, git_dir / "objects", served))
        except (GitCommandFailed, OSError, CorpusRefused):
            reachable = False

        return ResolvedCorpus(
            ref=ref,
            # THE RESOLUTION COMPUTED ABOVE, inside the translation, and not a
            # second `resolve()` here: the same `PermissionError`/`OSError`
            # this function now refuses for the probes could be raised by this
            # call, two lines from the fix for it.
            location=str(resolved_location),
            revision=revision,
            scopes=(SCOPE_ALL,),
            write_path=self._write_path,
            write_path_available=reachable,
        )

    # -- list -------------------------------------------------------------

    def list_documents(self, corpus: ResolvedCorpus,
                       scope: str = SCOPE_ALL) -> tuple[DocumentId, ...]:
        """Sorted, stable, no duplicates; an empty corpus is `()` and not a refusal."""
        if scope not in corpus.scopes:
            raise _refuse(SCOPE_UNKNOWN, scope,
                          f"this corpus declares {list(corpus.scopes)}; a "
                          "silent widening is indistinguishable from a correct "
                          "answer")
        git = self._git(corpus)
        if corpus.revision is None:
            # A repository with no commits yet. LEGAL, and empty — not absent.
            # REVALIDATED FIRST, because this path touched git at all only by
            # accident of there being nothing to ask it: a repository deleted
            # or made unreadable after `resolve` answered the caller with the
            # same legal empty listing, hiding a corpus failure as an empty
            # corpus — the one confusion this interface is emphatic about
            # (Copilot review of openDox-code#26, round 6).
            self._revalidate(git, corpus)
            return ()
        try:
            # THE FULL FORMAT, NOT `--name-only`, BECAUSE A LISTING AND A READ
            # HAVE TO AGREE. `ls-tree -r` also returns GITLINK entries (mode
            # 160000, type `commit`) for a repository that contains a
            # submodule, and `read` always asks `cat-file blob` — so this
            # advertised a document that this adapter then refused as
            # `DOCUMENT_UNKNOWN`, which is a listing the interface's own
            # contract does not permit (Copilot review of openDox-code#26,
            # round 10, suppressed twice). Gitlinks are EXCLUDED rather than
            # given a representation: a submodule's content is another
            # repository's, and inventing bytes for it here would be this
            # adapter answering for a corpus it does not manage.
            raw = git.out("ls-tree", "-r", "-z", corpus.revision)
        except GitCommandFailed as failed:
            raise _refuse(CORPUS_UNREADABLE, corpus.location, str(failed)) from failed
        # `surrogateescape`, NOT strict. `ls-tree -z` returns raw pathname
        # BYTES and git permits a path that is not UTF-8, so a strict decode
        # raised `UnicodeDecodeError` for a repository this adapter promises to
        # keep readable — "a repository openDox did not create stays readable"
        # is the sentence, and a key is opaque to this module anyway (Copilot
        # review of openDox-code#26, round 6). The round-trip is exact: the
        # same bytes go back out through `os.fsencode`-style encoding when the
        # key is handed to git.
        # `<mode> SP <type> SP <object> TAB <path>` per NUL-terminated entry —
        # git's documented `ls-tree` format, so the split is on the TAB and the
        # type is the second field.
        keys = sorted({entry.split("\t", 1)[1] for entry
                       in raw.decode("utf-8", "surrogateescape").split("\0")
                       if "\t" in entry
                       and entry.split("\t", 1)[0].split(" ")[1] == "blob"})
        return tuple(DocumentId(corpus=corpus.ref.name, key=key) for key in keys)

    # -- read -------------------------------------------------------------

    def read(self, corpus: ResolvedCorpus, document: DocumentId,
             revision: str | None = None) -> Document:
        """The bytes at a declared revision; NEVER a silent fallback."""
        git = self._git(corpus)
        at = corpus.revision if revision is None else self._resolve_revision(
            git, revision, corpus.location)
        if at is None:
            # The same revalidation `list_documents` does, for the same
            # reason: an unborn corpus whose repository has since gone answered
            # DOCUMENT_UNKNOWN, which says the corpus is fine and the document
            # is not (Copilot review of openDox-code#26, round 6).
            self._revalidate(git, corpus)
            raise _refuse(DOCUMENT_UNKNOWN, document.key,
                          "this repository has no commits, so it holds no "
                          "documents at any revision")
        try:
            content = git.out("cat-file", "blob", f"{at}:{document.key}")
        except GitCommandFailed as failed:
            # A MISSING DOCUMENT AND A MISSING CORPUS ARE DIFFERENT ANSWERS,
            # and `cat-file` fails the same way for both: a repository deleted
            # after it resolved, a `.git` that went away, or a commit object
            # pruned out from under `at` were all reported as "this document is
            # not here" (Copilot review of openDox-code#26, round 9). The
            # corpus is asked first, and only a corpus that is still readable
            # gets to say the document is unknown.
            self._revalidate(git, corpus)
            if self._probe(git, "cat-file", "-e", f"{at}^{{commit}}",
                           kind=CORPUS_UNREADABLE,
                           subject=corpus.location).returncode != 0:
                raise _refuse(
                    CORPUS_UNREADABLE, corpus.location,
                    f"revision {at} is no longer in the object store, so this "
                    "corpus cannot answer for any document at it") from failed
            raise _refuse(DOCUMENT_UNKNOWN, document.key,
                          f"not present at revision {at} ({failed})") from failed
        return Document(id=document, content=content, revision=at)

    # -- classify ---------------------------------------------------------

    def classify(self, corpus: ResolvedCorpus,
                 document: DocumentId) -> Classification:
        """Never omits: an unrecognized shape is REPORTED, naming the document.

        TWO VOCABULARIES, and which one is in force is a CONSTRUCTION DATUM
        (RULED openxFactory#656 comment 5714365086, Q-F2 (a) — see `__init__`).

        WITHOUT `kind_field` — the default, and what this class has always done
        — the shape is the file SUFFIX and `required_fields` is empty for every
        kind. That is the honest answer for a plain local git repository rather
        than an unfinished one: obligations are governance, and a pre-governed
        repository has none.

        WITH `kind_field` the corpus declares its own shape in a document
        HEADER, which is how the neutral conformance corpus is written
        (`Type:`), and this reader was classifying such a corpus by file
        suffix: three documents holding one complete, one field-absent and one
        unrecognizable came back as three `text` documents with nothing missing
        and nothing unrecognizable — a listing of shapes the corpus does not
        have. The header is the leading run of `Name: value` lines up to the
        first blank line, which is the corpus's own convention and no more
        parsing than that.
        """
        if self._kind_field is not None:
            return self._classify_by_header(corpus, document)
        del corpus
        suffix = Path(document.key).suffix.lower()
        kind = KINDS_BY_SUFFIX.get(suffix)
        if kind is None:
            return Classification(
                id=document, kind=None, required_fields=(), missing_fields=(),
                unclassifiable=(
                    f"{document.key!r} has no shape this corpus recognizes "
                    f"(suffix {suffix or '(none)'!r}); it is still listed and "
                    "still readable"))
        return Classification(id=document, kind=kind, required_fields=(),
                              missing_fields=())

    def _classify_by_header(self, corpus: ResolvedCorpus,
                            document: DocumentId) -> Classification:
        """`classify` where the corpus declares its kind in a header."""
        header = self._header_of(corpus, document)
        kind = header.get(self._kind_field or "")
        if kind is None:
            return Classification(
                id=document, kind=None, required_fields=(), missing_fields=(),
                unclassifiable=(
                    f"{document.key!r} carries no {self._kind_field!r} header; "
                    "it is still listed and still readable"))
        return Classification(
            id=document, kind=kind, required_fields=self._required_fields,
            missing_fields=tuple(field for field in self._required_fields
                                 if field not in header))

    def _header_of(self, corpus: ResolvedCorpus,
                   document: DocumentId) -> dict[str, str]:
        """The leading `Name: value` block, read THROUGH THIS ADAPTER'S `read`.

        Through `read` and not through the filesystem, so a classification is
        made of the same bytes a consumer would be served — at the corpus's
        resolved revision, never the working tree — and so a corpus that has
        become unreadable refuses here too instead of classifying out of
        nothing.

        BOUNDED: at most `MAX_HEADER_LINES` lines are examined and the block
        ends at the first blank line, so a document with no header costs one
        read and a few string operations rather than a scan of its whole body.
        """
        text = self.read(corpus, document).content.decode("utf-8", "replace")
        header: dict[str, str] = {}
        for line in text.splitlines()[:MAX_HEADER_LINES]:
            if not line.strip():
                break
            name, separator, value = line.partition(":")
            if separator:
                header[name.strip()] = value.strip()
        return header

    # -- check ------------------------------------------------------------

    def check(self, corpus: ResolvedCorpus,
              subjects: tuple[DocumentId, ...] | None = None) -> tuple[Finding, ...]:
        """This corpus's ONE verdict: a document whose checkout is not committed.

        RULING C3 says "documents are always git-backed", so a tracked file
        whose working-tree bytes differ from the resolved commit is a document
        whose current content is NOT in the corpus. That is a fact about git
        and the only verdict this adapter has; everything else it could say
        would be governance it does not carry.

        THE REPOSITORY THE ACT CREATES IS BARE, so for those this returns `()`
        every time — there is no second copy to diverge. The verdict is for a
        repository openDox did NOT create, which a caller may point this
        adapter at and which may well have a checkout somebody edits by hand.

        A consumer "must not read it as 'clean' without asking whether the
        corpus judges at all" — the interface's own warning, and it applies
        here with force: `()` from this corpus means "no divergence and no
        further opinion", never "reviewed and approved".
        """
        # A GIT FAILURE HERE IS A REFUSAL, NEVER AN EMPTY VERDICT. Both of
        # these used to answer `()`, which is this corpus's "no divergence and
        # no further opinion" — indistinguishable, to a caller, from a corpus
        # that became unreadable after it resolved (Copilot review of
        # openDox-code#26). The interface is emphatic that a corpus failure is
        # refused; `()` is a verdict and a verdict must not be manufactured out
        # of an error.
        git = self._git(corpus)
        try:
            bare = git.out("rev-parse", "--is-bare-repository").decode().strip()
        except GitCommandFailed as failed:
            raise _refuse(CORPUS_UNREADABLE, corpus.location,
                          f"the repository could not be classified after it "
                          f"resolved ({failed}); an unreadable corpus is "
                          "refused rather than reported as having no "
                          "findings") from failed
        if bare == "true" or corpus.revision is None:
            # AND THE RESOLVED COMMIT IS STILL THERE. This returned `()` — a
            # verdict — out of the `ResolvedCorpus` alone, so a commit pruned
            # after resolution made `check` report a clean corpus that
            # `list_documents` could not read: exactly the manufactured
            # no-finding answer the paragraph above forbids (Copilot review of
            # openDox-code#26, round 6).
            self._revalidate(git, corpus)
            if corpus.revision is not None and self._probe(
                    git, "cat-file", "-e", f"{corpus.revision}^{{commit}}",
                    kind=CORPUS_UNREADABLE,
                    subject=corpus.location).returncode != 0:
                raise _refuse(
                    CORPUS_UNREADABLE, corpus.location,
                    f"the resolved revision {corpus.revision} is no longer in "
                    "the object store; a corpus that cannot be read is refused "
                    "rather than reported as clean")
            return ()
        try:
            raw = git.out("diff", "--name-only", "-z", corpus.revision)
        except GitCommandFailed as failed:
            raise _refuse(CORPUS_UNREADABLE, corpus.location,
                          f"the checkout could not be compared with "
                          f"{corpus.revision} ({failed}); an unreadable corpus "
                          "is refused rather than reported as clean"
                          ) from failed
        # The same raw-byte pathname contract `ls-tree` has: a tracked file
        # whose name is not UTF-8 made `check` raise instead of reporting the
        # changed subject (Copilot review of openDox-code#26, round 6).
        changed = {name for name
                   in raw.decode("utf-8", "surrogateescape").split("\0")
                   if name}
        if subjects is not None:
            changed &= {document.key for document in subjects}
        return tuple(
            Finding(severity="warning", subject=key, code=UNCOMMITTED_CHANGE,
                    message=(f"{key} differs in the checkout from "
                             f"{corpus.revision}; documents are git-backed and "
                             "commits are the write path (RULING C3)"))
            for key in sorted(changed))

    # -- write back -------------------------------------------------------

    def write_back(self, corpus: ResolvedCorpus, document: DocumentId,
                   content: bytes, *, actor: str, basis_revision: str,
                   reason: str = "") -> WriteReceipt:
        """DISPATCH through the declared path — a commit — touching no file.

        The whole operation is plumbing against a TEMPORARY INDEX: the blob is
        written to the object database, the new tree is written from a copy of
        the resolved commit's tree, the commit is created with `commit-tree`
        and the branch ref is moved with a compare-and-swap. The checkout is
        never read and never written, which is what
        `corpus_adapter.write_back`'s "It never touches the corpus tree" means
        for a corpus whose write path happens to live in the same directory.

        `basis_revision` and `reason` become COMMIT TRAILERS. See the module
        header for why they are recorded rather than adjudicated.
        """
        if corpus.write_path is None:
            raise _refuse(CORPUS_READ_ONLY, corpus.location,
                          "this corpus declares no governed write path")
        if not corpus.write_path_available:
            raise _refuse(WRITE_PATH_UNREACHABLE, corpus.write_path,
                          f"the object database under {corpus.location} is not "
                          "writable; the document remains unsaved rather than "
                          "being written by a fallback")
        # A NUL IN THE KEY IS REFUSED BEFORE THE PROTOCOL SEES IT. The index
        # is fed `--index-info -z`, whose record terminator is NUL, and
        # `DocumentId.key` is opaque — so `a.md\0b` would have been truncated
        # to `a.md`, or read as two records, and the receipt would have named a
        # path the write did not make (Copilot review of openDox-code#26, round
        # 9). The option-safety the stdin form buys is exactly this one
        # delimiter's worth of care.
        if "\0" in document.key:
            raise _refuse(
                WRITE_PATH_UNREACHABLE, document.key,
                "the document key contains a NUL byte, which is the record "
                "terminator git's index protocol uses; a path that cannot be "
                "written unambiguously is not written at all")
        git = self._git(corpus)
        # AND THE ROOT IS ASKED AGAIN, ON THE ONE OPERATION THAT WRITES.
        # `resolve` refuses a location that is inside another repository
        # (see it for the defect and the ruling), and a `ResolvedCorpus` comes
        # from `resolve` — but this is the call that can commit into somebody
        # else's history, and the cost of being sure is one `rev-parse`.
        root = self._repository_root(git, corpus.location)
        if root != Path(corpus.location).resolve():
            raise _refuse(
                WRITE_PATH_UNREACHABLE, corpus.location,
                f"this location is inside the repository at {root} rather than "
                "being one; nothing is written, because the commit would land "
                "in a repository nobody named")
        try:
            blob = git.out("hash-object", "-w", "--stdin",
                           stdin=content).decode().strip()
            # The temporary index lives inside the REAL git directory, which is
            # `<location>/.git` for a checkout and `<location>` itself for the
            # BARE repository the act creates — so it is asked for rather than
            # assumed.
            git_dir = Path(git.out("rev-parse", "--absolute-git-dir")
                           .decode().strip())
            # A UNIQUE NAME PER CALL. Keyed on the process id alone, two
            # concurrent writes to the same repository in ONE process shared
            # `GIT_INDEX_FILE`: their `read-tree`/`update-index`/`write-tree`
            # steps could interleave into a wrong tree, and one cleanup could
            # unlink the other's index. The ref compare-and-swap protects the
            # REF and not the index (Copilot review of openDox-code#26).
            index = git_dir / f"opendox-index-{os.getpid()}-{uuid.uuid4().hex}"
            index_env = {"GIT_INDEX_FILE": str(index)}
            uncleaned: OSError | None = None
            try:
                if corpus.revision is not None:
                    git.out("read-tree", corpus.revision, env=index_env)
                else:
                    git.out("read-tree", "--empty", env=index_env)
                # THE THREE-ARGUMENT FORM. The single comma-delimited
                # argument is parsed as `mode,object,path`, and git permits a
                # comma IN A PATH — so a perfectly valid `DocumentId.key` such
                # as `notes,2026.md` was rejected or, worse, split into the
                # wrong path (Copilot review of openDox-code#26). `key` is
                # opaque to this adapter and must not have to avoid a
                # delimiter this call chose.
                # `--index-info` ON STDIN, so the path is DATA. The
                # three-argument `--cacheinfo` form fixed the comma, and left
                # the path as a positional argument with nothing terminating
                # git's option parsing — so a valid tracked key such as
                # `-notes.md` was read as an option and `write_back` refused a
                # path `list_documents` and `read` both serve (Copilot review
                # of openDox-code#26, round 6). The stdin form has no option
                # parsing at all: `<mode> SP <object> TAB <path> NUL`, with
                # `-z` so a path may contain anything but NUL — which is the
                # comma fix kept, by construction.
                git.out("update-index", "--add", "-z", "--index-info",
                        stdin=(f"100644 {blob}\t"
                               + document.key).encode(
                                   "utf-8", "surrogateescape") + b"\0",
                        env=index_env)
                tree = git.out("write-tree", env=index_env).decode().strip()
            finally:
                # THE CLEANUP IS TRANSLATED TOO, AND NOT FROM INSIDE THE
                # `finally`. `unlink` can raise `OSError` — a git directory
                # whose permissions changed under the write, a temporary path
                # replaced — and the outer handler translates only
                # `GitCommandFailed`, so that escaped `write_back` as an OS
                # exception where the adapter owes `WRITE_PATH_UNREACHABLE`
                # (Copilot review of openDox-code#26, round 12, suppressed).
                # Raising from a `finally` would REPLACE an in-flight failure
                # with a cleanup one, so it is recorded here and raised below,
                # where an exception already on its way still wins.
                try:
                    index.unlink(missing_ok=True)
                except OSError as exc:
                    uncleaned = exc
            if uncleaned is not None:
                raise _refuse(
                    WRITE_PATH_UNREACHABLE, corpus.write_path,
                    f"the temporary index {index.name} could not be removed "
                    f"({uncleaned.__class__.__name__}); this write path has "
                    "become unreachable and the document remains unsaved"
                ) from uncleaned

            message = self._message(document, actor, basis_revision, reason)
            parents: list[str] = []
            if corpus.revision is not None:
                parents = ["-p", corpus.revision]
            commit = git.out("commit-tree", tree, *parents, "-m", message,
                             env=git_identity(actor)).decode().strip()
            ref = self._served_ref(git, corpus.location)
            if corpus.revision is None:
                git.out("update-ref", ref, commit, "")
            else:
                # COMPARE-AND-SWAP: the ref moves only if it is still where
                # this corpus was resolved. A concurrent writer therefore loses
                # its dispatch rather than silently overwriting the other one.
                git.out("update-ref", ref, commit, corpus.revision)
        except GitCommandFailed as failed:
            raise _refuse(WRITE_PATH_UNREACHABLE, corpus.write_path,
                          f"the commit could not be made ({failed}); the "
                          "document remains unsaved") from failed
        return WriteReceipt(correlation_id=commit,
                            dispatched_to=corpus.write_path)

    # -- internals --------------------------------------------------------

    def _git(self, corpus: ResolvedCorpus) -> GitRunner:
        return GitRunner(Path(corpus.location), self._executable)

    def _writable_ref_home(self, git: GitRunner, git_dir: Path,
                           subject: str) -> Path:
        """The directory `update-ref` would write the SERVED ref into.

        `refs/heads/<branch>`'s parent where HEAD names a branch, walked up to
        the nearest ancestor that exists (a repository using only packed refs
        has no `refs/heads/` until the first write, and git creates it).

        A HEAD that `_served_ref` REFUSES — detached, or naming a tag or a
        remote-tracking ref — has no ref home at all, and the whole point of
        answering the write path at resolution is that such a corpus must say
        so THEN: `resolve` advertised an available write path, and `write_back`
        hashed the blob, wrote the tree and created the commit before refusing
        at `_served_ref`, leaving unreachable objects behind (Copilot review of
        openDox-code#26, round 12, suppressed). `_served_ref` raises, the
        caller's `except` turns it into `write_path_available=False`, and the
        commit is never started.
        """
        ref = self._served_ref(git, subject)
        home = git_dir / Path(ref).parent
        while not home.is_dir() and home != git_dir:
            home = home.parent
        return home

    def _repository_root(self, git: GitRunner, subject: str) -> Path:
        """The repository this runner's `-C` directory IS, resolved.

        A BARE repository's root is its git directory — the shape this act
        creates — and a repository with a work tree has `--show-toplevel`.
        Asked in that order because inside a bare repository (and inside a
        `.git` directory) `--show-toplevel` is a fatal error, not an answer.

        Both are resolved before they are compared, so a symlinked path and the
        directory it names are one answer rather than two.
        """
        bare = self._probe(git, "rev-parse", "--is-bare-repository",
                           kind=CORPUS_UNREADABLE, subject=subject)
        if bare.returncode != 0:
            raise _refuse(CORPUS_UNREADABLE, subject,
                          "the repository would not say whether it is bare: "
                          + bare.stderr.decode("utf-8", "replace").strip())
        question = ("--absolute-git-dir"
                    if bare.stdout.decode().strip() == "true"
                    else "--show-toplevel")
        answer = self._probe(git, "rev-parse", question,
                             kind=CORPUS_UNREADABLE, subject=subject)
        if answer.returncode != 0:
            raise _refuse(CORPUS_UNREADABLE, subject,
                          f"the repository would not name its root ({question}): "
                          + answer.stderr.decode("utf-8", "replace").strip())
        named = answer.stdout.decode("utf-8", "surrogateescape").strip()
        try:
            return Path(named).resolve()
        except OSError as exc:
            raise _refuse(CORPUS_UNREADABLE, subject,
                          f"the repository root {named} could not be read "
                          f"({exc.__class__.__name__})") from exc

    @staticmethod
    def _probe(git: GitRunner, *args: str, kind: str,
               subject: str) -> subprocess.CompletedProcess[bytes]:
        """`git.run`, with the RUNNER's own failure translated to a refusal.

        `GitRunner.run` does not return a failed process when the executable
        cannot be started — it raises `GitCommandFailed`, deliberately, so that
        a git which disappears mid-operation is one kind of failure everywhere.
        Every call below that only read `.returncode` was therefore a path on
        which that internal exception could escape the adapter: `resolve`
        probes git once, and a `git` removed, replaced or made unexecutable
        between that probe and `_head`, `_revalidate`, `_served_ref`,
        `_resolve_revision` or `check`'s bare-repository question leaked it to
        the API as a 500 in place of the interface's own refusal (Copilot
        review of openDox-code#26, round 10, suppressed, five times over).
        One helper, so a later call cannot forget.
        """
        try:
            return git.run(*args)
        except GitCommandFailed as failed:
            raise _refuse(kind, subject, str(failed)) from failed

    def _revalidate(self, git: GitRunner, corpus: ResolvedCorpus) -> None:
        """Refuse unless this repository is STILL a readable git repository.

        Every path that answers without asking git — an unborn corpus's empty
        listing, an unborn corpus's `DOCUMENT_UNKNOWN`, a bare repository's
        clean `check` — used to answer out of the `ResolvedCorpus` alone, so a
        repository deleted, unmounted or corrupted after `resolve` returned the
        answer a HEALTHY empty repository gives (Copilot review of
        openDox-code#26, round 6). One question, asked in each of them.
        """
        # THE PROBE IS TRANSLATED, like `resolve`'s. `Path.exists()` raises
        # `PermissionError` for a path whose parent has stopped being
        # searchable and `OSError` for a symlink loop, and this call sat
        # outside every handler — so a repository that became INACCESSIBLE
        # after it resolved leaked an OS exception out of `list_documents`,
        # `read` and `check`, where the adapter promises `CORPUS_UNREADABLE`
        # (Copilot review of openDox-code#26, round 12, suppressed twice).
        # Absent and unreadable stay different answers.
        try:
            present = Path(corpus.location).exists()
        except OSError as exc:
            raise _refuse(
                CORPUS_UNREADABLE, corpus.location,
                f"the location could not be read ({exc.__class__.__name__})"
            ) from exc
        if not present:
            raise _refuse(CORPUS_ABSENT, corpus.location,
                          "the repository is no longer at this location")
        if self._probe(git, "rev-parse", "--git-dir",
                       kind=CORPUS_UNREADABLE,
                       subject=corpus.location).returncode != 0:
            raise _refuse(CORPUS_UNREADABLE, corpus.location,
                          "the location is no longer a readable git "
                          "repository")

    def _head(self, git: GitRunner, subject: str) -> str | None:
        """The current commit, or None for an UNBORN branch — and only that.

        An unborn branch (a repository whose first commit has not been made)
        and an unreadable HEAD both made `rev-parse --verify HEAD` exit
        non-zero, and treating them alike resolved a broken repository with
        `revision=None`, after which `list_documents` answered `()` — an empty
        corpus — instead of refusing (Copilot review of openDox-code#26, and
        the interface is emphatic that "an absent corpus and an empty corpus
        are different answers"). They are told apart by asking whether HEAD is
        a symbolic ref that simply has no commit yet.
        """
        completed = self._probe(git, "rev-parse", "--verify", "HEAD",
                                kind=CORPUS_UNREADABLE, subject=subject)
        if completed.returncode == 0:
            revision = completed.stdout.decode().strip() or None
            if revision is not None:
                # THE REF'S SHA IS NOT THE OBJECT. `rev-parse --verify HEAD`
                # answers out of the ref store, so a commit that has been
                # pruned or deleted still produced a `ResolvedCorpus` carrying
                # a revision nothing can serve — `resolve`'s one promise is
                # that it does not hand back an unreadable corpus, and the
                # refusal arrived later, from `list_documents` or `read`
                # (Copilot review of openDox-code#26, round 6). `cat-file -e`
                # asks the object store.
                if self._probe(git, "cat-file", "-e", f"{revision}^{{commit}}",
                               kind=CORPUS_UNREADABLE,
                               subject=subject).returncode != 0:
                    raise _refuse(
                        CORPUS_UNREADABLE, subject,
                        f"HEAD names {revision}, which the object store cannot "
                        "read; the ref survived the commit it points at")
            return revision
        symbolic = self._probe(git, "symbolic-ref", "--quiet", "HEAD",
                               kind=CORPUS_UNREADABLE, subject=subject)
        if symbolic.returncode == 0:
            ref = symbolic.stdout.decode().strip()
            if self._probe(git, "show-ref", "--verify", "--quiet", ref,
                           kind=CORPUS_UNREADABLE,
                           subject=subject).returncode != 0:
                # `show-ref` IS NOT THE DISCRIMINATOR — it exits non-zero for a
                # branch that has no commit yet AND for one whose ref file is
                # malformed or whose target object is gone, so treating every
                # non-zero as "unborn" resolved a BROKEN repository with
                # `revision=None` and `list_documents` then answered `()`
                # (Copilot review of openDox-code#26). `for-each-ref` tells
                # them apart, measured on git 2.43.0 against a bare repository
                # whose `refs/heads/main` was overwritten with junk:
                #   absent  -> rc 0, no stdout, NO STDERR
                #   broken  -> rc 0, no stdout, "warning: ignoring broken ref"
                # so git saying nothing at all about the ref is what "the
                # branch simply has no commit yet" looks like.
                listed = self._probe(git, "for-each-ref",
                                     "--format=%(objectname)", ref,
                                     kind=CORPUS_UNREADABLE, subject=subject)
                # AND ONLY A BRANCH CAN BE UNBORN. `symbolic-ref HEAD` can
                # legally name a tag or a remote-tracking ref, and an absent
                # ref under `refs/tags/` or `refs/remotes/` produces exactly
                # the same silence — so a malformed HEAD pointing outside
                # `refs/heads/` resolved as a legal EMPTY corpus, and
                # `list_documents` and `check` answered for it instead of
                # refusing (Copilot review of openDox-code#26, round 12,
                # suppressed). "The first commit has not been made yet" is a
                # statement about a branch; anywhere else it is a broken HEAD.
                if (ref.startswith("refs/heads/")
                        and listed.returncode == 0
                        and not listed.stdout.decode().strip()
                        and not listed.stderr.decode().strip()):
                    return None      # unborn: the ref is named, and is absent
                raise _refuse(
                    CORPUS_UNREADABLE, subject,
                    f"HEAD names {ref}, which the ref store cannot read: "
                    + (listed.stderr.decode("utf-8", "replace").strip()
                       or "the ref exists and does not resolve to a commit"))
        raise _refuse(
            CORPUS_UNREADABLE, subject,
            "HEAD could not be read and is not an unborn branch: "
            + completed.stderr.decode("utf-8", "replace").strip())

    def _served_ref(self, git: GitRunner, subject: str) -> str:
        """The ref `write_back` moves: the one HEAD points at.

        NOT `refs/heads/<self._branch>`. `resolve` accepts any git repository
        and this module says in terms that a repository openDox did not create
        stays writable, so assuming `main` meant that a repository on `master`
        got its commit on a ref HEAD does not point at: the receipt came back
        successful and the document was not readable through the resolved
        corpus (Copilot review of openDox-code#26). A DETACHED HEAD has no ref
        to move and is refused rather than guessed at.
        """
        symbolic = self._probe(git, "symbolic-ref", "--quiet", "HEAD",
                               kind=WRITE_PATH_UNREACHABLE, subject=subject)
        if symbolic.returncode == 0:
            ref = symbolic.stdout.decode().strip()
            # A BRANCH, and not merely a symbolic ref. `symbolic-ref HEAD` can
            # legally name a tag or a remote-tracking ref, and `update-ref`
            # would then have advanced THAT — a write moving a tag instead of a
            # branch (Copilot review of openDox-code#26, round 6).
            # `repository_act._pushable_branch` already refused this shape; the
            # write path is where it matters more.
            if not ref.startswith("refs/heads/"):
                raise _refuse(
                    WRITE_PATH_UNREACHABLE, subject,
                    f"HEAD names {ref}, which is not a branch; a write back "
                    "advances a branch and will not move a tag or a "
                    "remote-tracking ref")
            return ref
        raise _refuse(
            WRITE_PATH_UNREACHABLE, subject,
            "HEAD is detached, so there is no branch for a commit to advance; "
            "check out a branch before writing back")

    def _resolve_revision(self, git: GitRunner, revision: str,
                          subject: str) -> str:
        # `--end-of-options` BEFORE THE CALLER'S VALUE. `revision` is opaque
        # and caller-controlled, and an argument beginning with `--` is read
        # by `rev-parse` as an OPTION — including options that change what the
        # command does — so resolving "a revision" could perform an unintended
        # git operation (Copilot review of openDox-code#26, round 8). The
        # marker is git's own answer to this, available since 2.24.
        # AND A NUL IS REFUSED BEFORE THE CALL, like a document key's. An
        # embedded NUL makes `subprocess.run` raise before any process exists,
        # which `GitRunner.run` turns into `GitCommandFailed` — and this
        # function read a returncode, so that exception escaped as an internal
        # error in place of the protocol's `REVISION_UNKNOWN` (Copilot review
        # of openDox-code#26, round 10, suppressed). `_probe` would translate
        # it now, but the named refusal is the better answer and it costs one
        # line.
        if "\0" in revision:
            raise _refuse(REVISION_UNKNOWN, subject,
                          "a revision cannot contain a NUL byte; this "
                          "repository serves no such revision")
        completed = self._probe(git, "rev-parse", "--verify",
                                "--end-of-options", f"{revision}^{{commit}}",
                                kind=REVISION_UNKNOWN, subject=subject)
        if completed.returncode != 0:
            raise _refuse(REVISION_UNKNOWN, subject,
                          f"this repository cannot serve revision {revision!r}; "
                          "it is never silently replaced with another one")
        return completed.stdout.decode().strip()

    @staticmethod
    def _message(document: DocumentId, actor: str, basis_revision: str,
                 reason: str) -> str:
        subject = f"Write {document.key}"
        body = [subject, ""]
        if reason:
            body.extend([reason, ""])
        body.append(f"Corpus: {document.corpus}")
        body.append(f"Basis-Revision: {basis_revision}")
        body.append(f"Dispatched-By: {actor}")
        body.append(f"Write-Path: {WRITE_PATH}")
        return "\n".join(body) + "\n"
