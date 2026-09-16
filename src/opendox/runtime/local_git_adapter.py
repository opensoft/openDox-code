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
own machinery is where two commits are reconciled.

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

    def run(self, *args: str, stdin: bytes | None = None,
            env: dict[str, str] | None = None,
            timeout: float | None = None) -> subprocess.CompletedProcess[bytes]:
        argv = [self.executable, "-C", str(self.root), "--literal-pathspecs",
                *args]
        merged = {**os.environ, **(env or {})}
        try:
            return subprocess.run(argv, input=stdin, capture_output=True,
                                  check=False, env=merged, timeout=timeout)
        except OSError as exc:
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
_CREDENTIAL_SHAPED = re.compile(
    r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s/@]*@[^\s]*|(?<![\w.])[^\s/:@]+@[^\s/:@]+:[^\s]*")

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
_ANY_PARAMETER = re.compile(
    r"(?P<lead>[?&#](?P<name>[^=&#\s]*)=)(?P<value>[^&#\s]*)")
_ANY_PARAMETER_ANCHORED = re.compile(r"(?:^|[?&#])(?P<name>[^=&#\s]*)=")
_MAX_DECODE_PASSES = 4


def _decoded_parameter_name(name: str) -> str:
    """A parameter name with its percent-encoding removed, decoded to a fixed
    point so one layer of encoding cannot hide another."""
    for _ in range(_MAX_DECODE_PASSES):
        once = urllib.parse.unquote_plus(name)
        if once == name:
            break
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

    #: THERE IS NO `branch` PARAMETER, and its absence is the decision.
    #: `__init__` took one and stored it, and nothing ever read it: the ref
    #: `write_back` moves is the one HEAD points at (see `_served_ref`, which
    #: argues why), so `LocalGitCorpus(branch="master")` behaved exactly like
    #: the default while advertising a branch selection it did not make
    #: (Copilot review of openDox-code#26). A parameter that cannot change an
    #: outcome is removed rather than wired up, because wiring it up would
    #: reintroduce the assumption `_served_ref` exists to refuse.
    def __init__(self, *, executable: str = "git") -> None:
        self._executable = executable

    # -- resolve ----------------------------------------------------------

    def resolve(self, ref: CorpusRef) -> ResolvedCorpus:
        """Which checkout, which revision, which scopes, which write path."""
        location = Path(ref.location).expanduser()
        if not location.exists():
            raise _refuse(CORPUS_ABSENT, ref.location,
                          "no such path; a plain local git repository is "
                          "created by the repository act before it is resolved")
        if not location.is_dir():
            raise _refuse(CORPUS_UNCLASSIFIABLE, ref.location,
                          "the location is a file, not a repository directory")
        git = GitRunner(location.resolve(), self._executable)
        try:
            git.out("rev-parse", "--git-dir")
        except GitCommandFailed as failed:
            raise _refuse(CORPUS_UNCLASSIFIABLE, str(location),
                          f"the directory is not a git repository ({failed})"
                          ) from failed

        revision = self._head(git, str(location))
        if ref.revision is not None:
            revision = self._resolve_revision(git, ref.revision, str(location))

        # THE WRITE PATH IS ANSWERED HERE AND NOT AT THE FIRST WRITE, which is
        # the interface's rule: "a read-only corpus is a fact about the corpus,
        # and discovering it by attempting a write is how a caller ends up with
        # a half-built edit and nowhere to put it."
        try:
            git_dir = Path(git.out("rev-parse", "--absolute-git-dir")
                           .decode().strip())
            reachable = os.access(git_dir, os.W_OK)
        except GitCommandFailed:
            reachable = False

        return ResolvedCorpus(
            ref=ref,
            location=str(location.resolve()),
            revision=revision,
            scopes=(SCOPE_ALL,),
            write_path=WRITE_PATH,
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
        if corpus.revision is None:
            # A repository with no commits yet. LEGAL, and empty — not absent.
            return ()
        git = self._git(corpus)
        try:
            raw = git.out("ls-tree", "-r", "--name-only", "-z", corpus.revision)
        except GitCommandFailed as failed:
            raise _refuse(CORPUS_UNREADABLE, corpus.location, str(failed)) from failed
        keys = sorted({name for name in raw.decode("utf-8").split("\0") if name})
        return tuple(DocumentId(corpus=corpus.ref.name, key=key) for key in keys)

    # -- read -------------------------------------------------------------

    def read(self, corpus: ResolvedCorpus, document: DocumentId,
             revision: str | None = None) -> Document:
        """The bytes at a declared revision; NEVER a silent fallback."""
        git = self._git(corpus)
        at = corpus.revision if revision is None else self._resolve_revision(
            git, revision, corpus.location)
        if at is None:
            raise _refuse(DOCUMENT_UNKNOWN, document.key,
                          "this repository has no commits, so it holds no "
                          "documents at any revision")
        try:
            content = git.out("cat-file", "blob", f"{at}:{document.key}")
        except GitCommandFailed as failed:
            raise _refuse(DOCUMENT_UNKNOWN, document.key,
                          f"not present at revision {at} ({failed})") from failed
        return Document(id=document, content=content, revision=at)

    # -- classify ---------------------------------------------------------

    def classify(self, corpus: ResolvedCorpus,
                 document: DocumentId) -> Classification:
        """Never omits: an unrecognized shape is REPORTED, naming the document.

        `required_fields` is empty for every kind, and that is the honest
        answer rather than an unfinished one: obligations are governance, and a
        plain local git repository has none. A descendant that governs its
        corpus declares them; this one would be inventing them.
        """
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
            return ()
        try:
            raw = git.out("diff", "--name-only", "-z", corpus.revision)
        except GitCommandFailed as failed:
            raise _refuse(CORPUS_UNREADABLE, corpus.location,
                          f"the checkout could not be compared with "
                          f"{corpus.revision} ({failed}); an unreadable corpus "
                          "is refused rather than reported as clean"
                          ) from failed
        changed = {name for name in raw.decode("utf-8").split("\0") if name}
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
        git = self._git(corpus)
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
                git.out("update-index", "--add", "--cacheinfo",
                        "100644", blob, document.key, env=index_env)
                tree = git.out("write-tree", env=index_env).decode().strip()
            finally:
                index.unlink(missing_ok=True)

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
        return WriteReceipt(correlation_id=commit, dispatched_to=WRITE_PATH)

    # -- internals --------------------------------------------------------

    def _git(self, corpus: ResolvedCorpus) -> GitRunner:
        return GitRunner(Path(corpus.location), self._executable)

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
        completed = git.run("rev-parse", "--verify", "HEAD")
        if completed.returncode == 0:
            return completed.stdout.decode().strip() or None
        symbolic = git.run("symbolic-ref", "--quiet", "HEAD")
        if symbolic.returncode == 0:
            ref = symbolic.stdout.decode().strip()
            if git.run("show-ref", "--verify", "--quiet", ref).returncode != 0:
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
                listed = git.run("for-each-ref", "--format=%(objectname)", ref)
                if (listed.returncode == 0
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
        symbolic = git.run("symbolic-ref", "--quiet", "HEAD")
        if symbolic.returncode == 0:
            return symbolic.stdout.decode().strip()
        raise _refuse(
            WRITE_PATH_UNREACHABLE, subject,
            "HEAD is detached, so there is no branch for a commit to advance; "
            "check out a branch before writing back")

    def _resolve_revision(self, git: GitRunner, revision: str,
                          subject: str) -> str:
        completed = git.run("rev-parse", "--verify", f"{revision}^{{commit}}")
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
