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
import threading
import unicodedata
import urllib.parse
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO

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

#: The most output this runtime will hold from ONE network operation, on each
#: of the child's two streams. A push's real output is a few hundred bytes; a
#: remote that sends four orders of magnitude more is not talking to us.
MAX_REMOTE_OUTPUT_BYTES = 4 * 1024 * 1024

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


#: Every boundary `str.splitlines()` splits on, as one pattern: the three
#: ordinary endings plus the vertical tab, form feed, the three ASCII
#: separators, NEL and the two unicode separators. Written out because
#: `_leading_lines` must yield exactly what `splitlines` would, and a smaller
#: set would silently reclassify a document that uses one of them.
_LINE_BOUNDARY = re.compile("\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]")


def _leading_lines(text: str, limit: int) -> Iterator[str]:
    """`text.splitlines()[:limit]`, WITHOUT building the list of every line.

    The slice is the point: a bounded header scan that allocates the whole
    document first is not bounded. `test_the_bounded_line_scan_is_splitlines_
    exactly` holds this to `str.splitlines` over every shape that distinguishes
    them — trailing terminator, empty text, consecutive terminators, `\r\n`
    against `\r` then `\n`, and each exotic boundary on its own.
    """
    start = 0
    for _ in range(limit):
        boundary = _LINE_BOUNDARY.search(text, start)
        if boundary is None:
            if start < len(text):
                yield text[start:]
            return
        yield text[start:boundary.start()]
        start = boundary.end()


#: Environment variables that SELECT A REPOSITORY or inject configuration, and
#: which are therefore stripped from every `git` this package runs.
#:
#: `-C <root>` names the repository; `GIT_DIR`, `GIT_WORK_TREE` and their
#: relatives OUTRANK IT, so a runtime started with one of them set — a unit
#: file that inherited it, a process started from inside a git hook, which is
#: exactly where these are set — would have resolved, initialized or pushed a
#: DIFFERENT repository than the one the map row names, silently (Copilot
#: review of openDox-code#26, round 13). `GIT_CONFIG` and the
#: `GIT_CONFIG_COUNT`/`KEY`/`VALUE` triple are the same hazard for settings:
#: they are pure override channels with no legitimate use for this service.
#:
#: `GIT_INDEX_FILE` is on the list and is still SET PER CALL by `write_back`,
#: which is the point of the order: the ambient value is removed and the call's
#: own is layered on top.
#:
#: `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` are deliberately NOT stripped.
#: They name the operator's own git configuration, which a push may legitimately
#: need (a CA bundle, a credential helper, a proxy), and an actor who can set
#: the service's environment can do more than redirect its git. What is removed
#: is the set that silently changes WHICH REPOSITORY a command means.
_GIT_ENVIRONMENT_OVERRIDES = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_CONFIG", "GIT_CONFIG_COUNT",
    "GIT_INDEX_VERSION", "GIT_PREFIX",
    # `GIT_EXTERNAL_DIFF` NAMES A PROGRAM, and `git diff` runs it. `check`
    # asks a project repository what changed, so an ambient value made that
    # question arbitrary code execution in this runtime — the environment half
    # of the `diff.external` finding (Copilot review of openDox-code#26, round
    # 17). The command-line half is `--no-ext-diff --no-textconv` on the diff.
    "GIT_EXTERNAL_DIFF",
    # `GIT_CONFIG_PARAMETERS` IS THE `-c` CHANNEL ITSELF. It is how git hands
    # its own `-c` settings to the commands it runs, and it is read on the way
    # IN as well: an ambient value set the same settings a command line would,
    # so a runtime started from inside a git invocation — a hook, an alias, a
    # `filter-branch` — inherited `core.hooksPath` or `protocol.*.allow` from
    # whatever set it, which is exactly the redirection the rest of this list
    # exists to refuse (Copilot review of openDox-code#26, rounds 15 and 16).
    # MEASURED on git 2.43.0 and pinned by a case.
    "GIT_CONFIG_PARAMETERS",
    # `GIT_PROXY_COMMAND` NAMES A PROGRAM TOO, and git executes it for a
    # `git://` remote — the environment's half of `core.gitProxy`. The
    # transport guard says nothing about it: `protocol.ext.allow=never` refuses
    # the `ext::` transport, and this is the `git://` one running an ambient
    # command instead (Copilot review of openDox-code#26, round 21). It joins
    # the two other command-naming variables on this list.
    "GIT_PROXY_COMMAND",
})


def subcommand_of(args: tuple[str, ...] | list[str]) -> str:
    """The git SUBCOMMAND in a vector that may open with `-c <name>=<value>`.

    ONE RULE, IN THE TWO PLACES THAT ASK. The first cut asked two different
    questions and both were wrong for the same vector, `("-c",
    "protocol.ext.allow=never", "push", …)`, which is how this act pushes:

    * `GitCommandFailed` took `args[0]`, so every failed push reported itself
      as `git -c exited 128` and the refusal an operator reads named no
      operation at all (Copilot review of openDox-code#26, round 19).
    * `GitRunner._argv` took the first argument not starting with `-`, which is
      the `-c` VALUE — `protocol.ext.allow=never`, not a subcommand — so the
      alias guard round 18 added was silently dropped on exactly the call that
      reaches a remote. The reviewer found the first; the second was under it.

    A `-c` consumes the argument after it, and every other option is skipped.
    """
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg == "-c":
            skip = True
        elif not arg.startswith("-"):
            return arg
    return ""


def decoded_path(stdout: bytes) -> str:
    """A PATHNAME git printed, with git's one line ending taken off and no more.

    `.strip()` REMOVED MORE THAN GIT WROTE, again — the same defect round 19
    found on a ref name, at the sites that read a path. A project id is refused
    for `/`, a NUL, `.`/`..` and for not being one path component, so
    `"project "` is a LEGAL id: a repository created at a location ending in a
    space had its root read back as the trimmed name, and the comparison that
    is supposed to prove "this is the repository the caller named" refused it
    (Copilot review of openDox-code#26, round 22).

    EXACTLY ONE TRAILING NEWLINE, and nothing else. `rev-parse` has no `-z`, so
    a pathname really is terminated by a `\n` it could itself contain; what
    this can do is refuse to guess — it removes the terminator git wrote and
    leaves every other byte alone. The other half of that ambiguity is closed
    where the name is chosen: `repository_act.repository_location` refuses a
    project id carrying a control character, so no location this act creates
    can contain one.
    """
    text = stdout.decode("utf-8", "surrogateescape")
    return text[:-1] if text.endswith("\n") else text


def decoded_ref_name(stdout: bytes) -> str:
    """`symbolic-ref`'s answer as a ref NAME: the bytes, minus the newline.

    `.strip()` REMOVED MORE THAN GIT WROTE. A ref name is bytes with only a
    short list of forbidden characters, and `git check-ref-format` forbids
    ASCII control characters — which is `\n` and `\r`, and nothing else that
    `str.strip()` removes. `"\xa0".isspace()` is True in python, so a branch
    legally named `feature\xa0` was trimmed to `feature`: the write path then
    advanced a DIFFERENT ref, and the push targeted a ref that does not exist
    (Copilot review of openDox-code#26, round 19). git writes exactly one
    trailing newline, so exactly that is what comes off.
    """
    return stdout.decode("utf-8", "surrogateescape").rstrip("\r\n")


def _sanitized_git_environment() -> dict[str, str]:
    """`os.environ` without the repository-selection and config overrides."""
    return {name: value for name, value in os.environ.items()
            if name not in _GIT_ENVIRONMENT_OVERRIDES
            and not name.startswith("GIT_CONFIG_KEY_")
            and not name.startswith("GIT_CONFIG_VALUE_")}


#: Whether this platform offers the primitives every path guard here needs.
#:
#: `O_DIRECTORY` and a `dir_fd`-capable `mkdir`/`open` are what make the
#: component-by-component walk a walk and not a pathname resolution. Windows
#: has neither: `os.O_DIRECTORY` is not defined there at all, and
#: `os.supports_dir_fd` excludes both calls — so `open_no_follow_chain` raised
#: `AttributeError` before any caller's refusal translation, and every read,
#: write, attach and push failed with a traceback rather than an answer
#: (Copilot review of openDox-code#26, round 29).
#:
#: THE ACT REFUSES THERE RATHER THAN DEGRADING. The alternative that was in the
#: tree — create the parents by pathname, then check the leaf — is not a weaker
#: race window, it is no guard at all: an EXISTING `<root>/link` pointing
#: elsewhere is followed on every platform taking that branch, every time, and
#: the act would have written a repository outside the root it owns while
#: reporting success. A named refusal is the honest answer for a platform this
#: act has never run on: both `deploy/` shapes and every CI runner are Linux.
NO_FOLLOW_WALK_IS_AVAILABLE = (
    hasattr(os, "O_DIRECTORY")
    # `O_NOFOLLOW` IS THE GUARD ITSELF, not an optimization. The walk opened
    # each component with `getattr(os, "O_NOFOLLOW", 0)`, so on a platform
    # holding `O_DIRECTORY` and `dir_fd` but not `O_NOFOLLOW` the flag was
    # silently ZERO — every component open followed links, and this constant
    # still reported the safe walk as available (Copilot review of
    # openDox-code#26, round 30). A guard that can be absent without anybody
    # being told is the shape this act refuses everywhere else.
    and hasattr(os, "O_NOFOLLOW")
    and os.mkdir in os.supports_dir_fd
    and os.open in os.supports_dir_fd
    # AND A DESCRIPTOR MUST BE NAMEABLE, because `runner_bound_to` is what
    # turns the verified handle into the thing git opens. Without
    # `/proc/self/fd` or `/dev/fd` it fell back to the PATHNAME, and the
    # adapter and both acts then re-resolved that name for the root checks and
    # the writes — the same-object guarantee this module documents was simply
    # false there (round 30). Refused rather than quietly weaker.
    and any(os.path.isdir(base) for base in ("/proc/self/fd", "/dev/fd")))


class PlatformCannotGuardPaths(OSError):
    """This platform cannot open a directory chain without following links."""


def refuse_without_the_no_follow_walk() -> None:
    """Raise unless this platform offers the walk every path guard needs.

    An `OSError` subclass on purpose: every caller in this package already
    translates `OSError` into its own named refusal, so a platform without the
    primitives produces the act's answer and not a traceback.
    """
    if not NO_FOLLOW_WALK_IS_AVAILABLE:
        raise PlatformCannotGuardPaths(
            "this platform offers no O_DIRECTORY or no dir_fd-capable "
            "mkdir/open, so a repository path cannot be opened without "
            "following links; this act refuses rather than writing through "
            "one. Run the runtime on a platform that has them (every "
            "deploy/ shape and every CI runner is Linux)")


def open_no_follow_chain(directory: Path, *, create: bool = False) -> int:
    """A descriptor for `directory`, opened COMPONENT BY COMPONENT, no-follow.

    `create=True` also MAKES a missing component, in the directory this walk is
    already holding open, so the parents of a new repository are created under
    the same rule they are opened under; see `initialize_repository` for the
    tree that a pathname `mkdir(parents=True)` wrote into before refusing.

    The leaf was created relative to a held parent descriptor, and that
    descriptor was obtained by opening `location.parent` BY PATHNAME — which
    follows every symlink in it. A concurrent replacement of the parent (or of
    any ancestor) with a link therefore made the descriptor, `git init`, and
    the later `stat(location)` all name a directory outside the canonical
    repository root, and the inode comparison compared that place with itself
    and passed (Copilot review of openDox-code#26, round 12, twice). Opening
    each component with `O_NOFOLLOW` refuses the substitution instead: a
    component that has become a link fails with `ELOOP`, which the caller's
    handler turns into the act's named refusal.

    THIS REFUSES NO LEGITIMATE SETUP, and that is a fact about where the path
    comes from rather than an assumption: `repository_location` already returns
    a `resolve()`d path, so an operator's symlinked root — `/var` on a BSD, a
    symlinked mount — is already collapsed before this is reached, and a link
    appearing in the chain afterwards is exactly the race this refuses. A
    caller that passes an unresolved path of its own (this function is public)
    gets the same rule applied to what it asked for.

    The descriptor returned is the DIRECTORY ITSELF and not its name, so every
    lookup the caller then makes with `dir_fd=` happens in the object this walk
    verified.
    """
    refuse_without_the_no_follow_walk()
    walked = Path(os.path.abspath(directory))
    handle = os.open(walked.anchor or os.sep, os.O_RDONLY | os.O_DIRECTORY)
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        for component in walked.relative_to(walked.anchor or os.sep).parts:
            try:
                nxt = os.open(component, flags, dir_fd=handle)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(component, dir_fd=handle)
                except FileExistsError:
                    # Another process got there first. The open below is the
                    # check that what it made is a real directory and not a
                    # link, so the race needs no second decision here.
                    pass
                nxt = os.open(component, flags, dir_fd=handle)
            os.close(handle)
            handle = nxt
    except BaseException:
        os.close(handle)
        raise
    return handle


def runner_bound_to(handle: int, location: Path,
                     executable: str) -> GitRunner:
    """A runner whose `-C` is the OPEN DIRECTORY, where the OS offers one.

    `/proc/self/fd/<n>` — and `/dev/fd/<n>`, which is the same thing on Linux
    and the BSD spelling elsewhere — resolves, IN THE CHILD, to the directory
    the descriptor refers to, whatever has happened to the name since. The
    descriptor has to be inherited for that to mean anything, which is what
    `GitRunner.inherit_fd` does; `subprocess` closes inherited descriptors by
    default. Measured on this container (Linux 6.18, git 2.43.0): with the
    directory renamed away and a symlink put in its place after the handle was
    opened, `git -C /proc/self/fd/<n>` still wrote into the real directory and
    wrote nothing through the link.

    WHERE NEITHER PATH EXISTS THIS REFUSES. It used to fall back to the
    pathname, described as "the strongest the platform offers" — but the
    fallback closes the verified handle's only connection to git, and the
    adapter and both acts then re-resolve that NAME for their root checks and
    their writes, so a repository can be swapped in after the check and this
    module's documented same-object guarantee is false (Copilot review of
    openDox-code#26, round 30). `NO_FOLLOW_WALK_IS_AVAILABLE` carries the same
    condition, so a platform without a descriptor path is refused at the first
    guard rather than here; this raise is the one that would fire if the
    directory went away between the two.
    """
    for base in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(base):
            return GitRunner(Path(base) / str(handle), executable,
                             inherit_fd=handle)
    raise PlatformCannotGuardPaths(
        "this platform names no open descriptor (`/proc/self/fd`, `/dev/fd`), "
        "so the directory this act verified cannot be the directory git "
        "opens; it refuses rather than re-resolving the path")


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
    #: A SECOND DESCRIPTOR THE CHILD INHERITS, for the push that names its
    #: DESTINATION by open handle as well as its source (`repository_act.
    #: _push_to_remote_with`). Same rule as `inherit_fd`: `subprocess` closes
    #: inherited descriptors, so passing it is what makes `/proc/self/fd/<n>`
    #: mean anything in the child.
    extra_fd: int | None = None

    def _inherited(self) -> tuple[int, ...]:
        """The descriptors this runner's children keep, in a stable order."""
        return tuple(fd for fd in (self.inherit_fd, self.extra_fd)
                     if fd is not None)

    def _argv(self, args: tuple[str, ...]) -> list[str]:
        """The command line, with this package's two policy options on it.

        `core.hooksPath` POINTED AT NOTHING, ON EVERY INVOCATION. A repository
        this service manages is WRITABLE by it, and `git push` runs the LOCAL
        `pre-push` hook before it contacts the remote — so a `hooks/pre-push`
        in a project repository executed arbitrary code in the runtime's own
        process, which `protocol.ext.allow=never` says nothing about because a
        hook is not a transport (Copilot review of openDox-code#26, round 13).
        MEASURED on git 2.43.0 both ways: a planted `hooks/pre-push` RAN on an
        ordinary push and did not run with this option, and the push succeeded
        either way. It is set here rather than on the push because no act of
        this runtime wants a repository's hooks to run in its process, and one
        place cannot be forgotten by a later call.

        AND THE SUBCOMMAND'S OWN ALIAS IS EMPTIED, which is defence in depth
        and is labelled as such: MEASURED on git 2.43.0, an alias that shadows
        a BUILT-IN command is IGNORED — `[alias] remote = !touch …` did not run
        for `git remote`, nor `[alias] status` for `git status`, while an alias
        under a non-built-in name (`revparse`) did run. Every command this
        runner invokes is a built-in, so the reported channel is closed by git
        itself here (Copilot review of openDox-code#26, round 18). `-c
        alias.<subcommand>=` makes that a property of THIS call rather than of
        a rule a later git could relax, and costs one option.
        """
        subcommand = subcommand_of(args)
        alias = ([] if not subcommand.replace("-", "").isalnum()
                 else ["-c", f"alias.{subcommand}="])
        return [self.executable, "-C", str(self.root),
                "-c", "core.hooksPath=" + os.devnull, *alias,
                # AND NO SIGNING, which names a PROGRAM the repository chooses.
                # `gpg.program` is run by whatever signs, and a repository can
                # turn signing on in its own config. MEASURED on git 2.43.0
                # with `gpg.program` pointing at a script: `commit.gpgSign`
                # does NOT reach `commit-tree`, which is the only commit this
                # act makes (`git commit` DOES run it — the control) — but
                # `push.gpgSign=true` DID reach the push, which this act
                # performs, and failed it with `the receiving end does not
                # support --signed push` before any receiver had agreed to
                # anything. Against a receiver that does support it, that is
                # the repository choosing which program this process runs
                # (Copilot review of openDox-code#26, round 29, which reported
                # the `commit-tree` half). All three switches are pinned off
                # here rather than the one that is reachable today: they cost
                # one option each and the reachable set is git's to change.
                "-c", "commit.gpgSign=false",
                "-c", "tag.gpgSign=false",
                "-c", "push.gpgSign=false",
                "--literal-pathspecs", *args]

    def run(self, *args: str, stdin: bytes | None = None,
            env: dict[str, str] | None = None,
            timeout: float | None = None) -> subprocess.CompletedProcess[bytes]:
        argv = self._argv(args)          # see `_argv` for the two options
        merged = {**_sanitized_git_environment(), **(env or {})}
        try:
            return subprocess.run(argv, input=stdin, capture_output=True,
                                  check=False, env=merged, timeout=timeout,
                                  pass_fds=self._inherited())
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

    def _run_bounded(self, args: tuple[str, ...], env: dict[str, str],
                     timeout: float) -> subprocess.CompletedProcess[bytes]:
        """`run`, with the child's OUTPUT capped as well as its clock.

        `subprocess.run(capture_output=True)` reads both pipes to EOF with no
        limit. This reads them on two threads, stops at
        `MAX_REMOTE_OUTPUT_BYTES` each, and kills the child when either passes
        it — so the memory a remote can make this process hold is a constant
        and not a function of how long the remote is willing to talk.
        """
        argv = self._argv(args)
        try:
            child = subprocess.Popen(                    # noqa: S603 - fixed argv
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=env,
                pass_fds=self._inherited())
        except (OSError, ValueError) as exc:
            raise GitCommandFailed(
                args, subprocess.CompletedProcess(
                    argv, returncode=127, stdout=b"",
                    stderr=(f"{self.executable}: {exc}").encode())) from exc
        captured: dict[str, bytes] = {}
        overflowed: set[str] = set()

        def _drain(name: str, stream: IO[bytes]) -> None:
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_REMOTE_OUTPUT_BYTES:
                    overflowed.add(name)
                    child.kill()
                    break
                chunks.append(chunk)
            captured[name] = b"".join(chunks)

        readers = [threading.Thread(target=_drain, args=(name, stream),
                                    daemon=True)
                   for name, stream in (("stdout", child.stdout),
                                        ("stderr", child.stderr))]
        for reader in readers:
            reader.start()
        try:
            returncode = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            raise
        finally:
            for reader in readers:
                reader.join(5)
            for stream in (child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
        if overflowed:
            raise GitCommandFailed(
                args, subprocess.CompletedProcess(
                    argv, returncode=returncode, stdout=b"",
                    stderr=(f"the remote sent more than "
                            f"{MAX_REMOTE_OUTPUT_BYTES} bytes on "
                            f"{'/'.join(sorted(overflowed))} and was stopped; "
                            "no output from it is reported, because a stream "
                            "this size is not a message").encode()))
        return subprocess.CompletedProcess(
            argv, returncode=returncode,
            stdout=captured.get("stdout", b""),
            stderr=captured.get("stderr", b""))

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

        AND THE OUTPUT IS BOUNDED TOO, which the wall clock is not. `run()`
        captures with a pipe and no limit, so a remote that answers — a hostile
        one, or a broken one in a loop — could stream gigabytes of stderr for
        the whole timeout and have every byte held in this process's memory
        while the request holds the caller's database transaction and the map
        row's lock (Copilot review of openDox-code#26, round 17). A push's real
        output is a few hundred bytes; `MAX_REMOTE_OUTPUT_BYTES` is four orders
        of magnitude above that, and a stream that passes it is killed and
        refused rather than believed.
        """
        merged = {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=yes",
            **(env or {}),
        }
        try:
            # THE SANITIZED INHERITED ENVIRONMENT IS THE BASE, as it is for
            # `run`. `_run_bounded` took the mapping it was handed and passed
            # it straight to `Popen`, so the push ran with four variables and
            # no `PATH` — and without `GIT_CONFIG_GLOBAL`/`SYSTEM`, which this
            # package keeps on purpose because they are the operator's own git
            # (a credential helper, a proxy, a CA bundle). Inspection worked
            # and the push it was inspecting for could not (Copilot review of
            # openDox-code#26, round 18, and it is a regression this round's
            # own output cap introduced).
            completed = self._run_bounded(
                args, {**_sanitized_git_environment(), **merged}, timeout)
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
#: `pass` IS ON THE LIST AND `password` DOES NOT COVER IT. The match is a
#: SEARCH for one of these inside the decoded parameter name, so `password`
#: matches `?password=` and `?my_password=` — and not `?pass=`, which is a
#: name a great many services use (Copilot review of openDox-code#26, round
#: 13). `pass` is the shorter needle and matches all three.
SECRET_PARAMETER_KEYS = (
    "token|secret|pass|pwd|key|credential|auth|sig|signature")
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


#: A LIBPQ KEYWORD/VALUE PASSWORD, in the forms libpq itself accepts. A remote
#: is an arbitrary string, and a value such as `host=db password=hunter2` is
#: neither a URL with userinfo nor a query parameter, so both halves of the
#: rule above looked straight through it and the attach response, the map
#: endpoints and the CLI returned it verbatim (Copilot review of
#: openDox-code#26, round 21). libpq documents that a value containing spaces
#: is single-quoted with `\'` and `\\` escaped inside; the closing quote is
#: OPTIONAL here and neither quoted form crosses a newline, because a truncated
#: value must redact MORE rather than less and must not swallow the next line
#: of a diagnostic. `sslpassword` is named because `\b` before `password` does
#: not reach it. `opendox.runtime.cli._DSN_SHAPED` spells the same rule for the
#: CLI's own fallback, and
#: `test_the_two_libpq_password_patterns_agree` keeps them in step.
_LIBPQ_PASSWORD = re.compile(
    r"(?i)\b(?:ssl)?password\s*=\s*"
    r"""(?:'(?:[^'\\\n]|\\.)*'?|"(?:[^"\\\n]|\\.)*"?|\S+)""")


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

    THREE, SINCE ROUND 21: a libpq KEYWORD/VALUE password is neither, and a
    remote is an arbitrary string — `host=db password=hunter2` was stored and
    returned by the attach response, the map endpoints and the CLI with the
    password in it. Only the password field goes; `host=db` stays, for the same
    reason the query form keeps its host.
    """
    def _redact_value(match: re.Match[str]) -> str:
        if _SECRET_KEY.search(_decoded_parameter_name(match.group("name"))):
            return match.group("lead") + "<redacted>"
        return match.group(0)

    return _LIBPQ_PASSWORD.sub("<redacted>", _ANY_PARAMETER.sub(
        _redact_value, _CREDENTIAL_SHAPED.sub("<redacted-url>", text)))


def carries_a_control_character(value: str) -> bool:
    """A C0/C1 control, a unicode FORMAT character, or whitespace but a space.

    One predicate for the two halves of one rule.
    `repository_act.refuse_command_executing_remote` REFUSES a new remote that
    answers this — a newline or a `\r` splits a value across what an operator
    reads as two lines, and the bidirectional overrides (category `Cf`) reorder
    a URL on screen without changing it — and `redact_remote_url` below refuses
    to PRINT a legacy one that does. A plain space stays legal: a local path may
    contain one, and the credential rule's own userinfo class admits it.
    """
    return any(_is_a_control_character(character) for character in value)


def _is_a_control_character(character: str) -> bool:
    """One character's half of the rule above, so `on_one_line` shares it."""
    return character != " " and (
        unicodedata.category(character) in {"Cc", "Cf"} or character.isspace())


def redact_remote_url(url: str) -> str:
    """`redact_credentials` for a value that is ONE URL rather than a diagnostic.

    `_CREDENTIAL_SHAPED`'s userinfo class EXCLUDES A NEWLINE, deliberately: the
    pattern is applied to git's stderr and to exception text, where a
    `scheme://…` on one line and an unrelated `user@host` three lines later
    would otherwise be joined into one match and both lines of evidence
    destroyed. The cost is that a LEGACY row holding
    `https://user:secret\n@host/repo` — written before
    `refuse_credential_bearing_remote` existed — was returned unredacted by the
    map endpoints, the CLI and push refusals (Copilot review of
    openDox-code#26, round 14).

    Widening the class is the wrong repair, and this is why it is written down
    rather than tried: the two cases are not distinguishable by pattern (an
    unrelated `@` on a later line is inside the same `/`-free run as the URL
    above it), so the pattern would trade a rare leak for a routine loss of
    diagnostics.

    The DISTINCTION IS THE CALLER'S, and it is decisive: these call sites pass
    a stored `remote_url` — one value, not a page of text — and a stored remote
    may not contain a control character at all, because
    `refuse_command_executing_remote` refuses one. A value that carries one is
    therefore legacy and cannot be shown in part, so it is replaced WHOLE,
    which is what the userinfo form already gets from `redact_credentials`.
    """
    if carries_a_control_character(url):
        return "<redacted-url>"
    return redact_credentials(url)


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
        subcommand = subcommand_of(args) or "(none)"
        stderr = completed.stderr.decode("utf-8", "replace").strip()
        super().__init__(
            f"git {subcommand} exited {completed.returncode}: "
            f"{redact_credentials(stderr)}")


def on_one_line(value: str) -> str:
    """`value` with every control, format and non-space whitespace collapsed.

    A single space replaces each run, and the result is stripped. This is the
    SECOND line of defence and not the rule: `LocalGitCorpus.write_back`
    REFUSES such a value outright (see
    `refuse_a_value_that_would_forge_a_commit_trailer`). What this covers is
    every other path that writes durable history through `git_identity` — the
    repository's first commit among them — so that no caller can put a
    newline into an author or committer name, which git records verbatim.
    """
    # THE PREDICATE'S OWN RULE, CHARACTER BY CHARACTER, rather than a second
    # spelling of it as a pattern: a sanitiser and a refusal that disagreed
    # about one character would be worse than either alone.
    flattened = "".join(
        " " if _is_a_control_character(character) else character
        for character in value)
    return " ".join(part for part in flattened.split(" ") if part).strip()


def refuse_a_value_that_would_forge_a_commit_trailer(
        field: str, value: str, subject: str) -> None:
    """Refuse a value that would add or fake a line in the commit message.

    `Basis-Revision:` and `Dispatched-By:` are COMMIT TRAILERS — the durable
    record of what a write claimed, and the thing a reader of the history is
    invited to believe. Both values arrive from the caller and were
    interpolated into the message unencoded, so `A\nWrite-Path: forged`
    produced a second, fabricated trailer and made the commit's own account of
    the dispatch ambiguous — and the same newline in `actor` went into the
    author and committer NAMES, which git records exactly as given (Copilot
    review of openDox-code#26, round 32).

    REFUSED RATHER THAN ENCODED, which is this module's rule everywhere a value
    cannot be recorded unambiguously: the document key with a NUL is refused
    for the same reason one line up in the same function. An encoded trailer
    would be recorded — it would just be recorded WRONG, and permanently.
    """
    if carries_a_control_character(value):
        raise _refuse(
            WRITE_PATH_UNREACHABLE, subject,
            f"the {field} contains a control character, and it is written "
            "into this commit's message and identity, where a newline forges "
            "a trailer that a reader of the durable history cannot tell from "
            "a real one; the write is refused rather than recorded "
            "ambiguously")


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
    # THE NAME IS PUT ON ONE LINE, and the address was already a slug. Only
    # the derived email was sanitized, so the raw actor reached
    # `GIT_AUTHOR_NAME` — which git writes into the commit object verbatim,
    # where a newline is a header boundary (Copilot review of
    # openDox-code#26, round 32). `write_back` refuses such an actor outright;
    # this is what keeps every OTHER caller — the repository's first commit
    # among them — from recording one.
    if "<" in actor and actor.rstrip().endswith(">"):
        name, _, address = actor.partition("<")
        name = on_one_line(name) or "opendox"
        address = on_one_line(address.rstrip(">"))
        return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": address,
                "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": address}
    slug = _SAFE_ACTOR.sub("-", actor).strip("-") or "opendox"
    address = f"{slug}@opendox.invalid"
    name = on_one_line(actor) or "opendox"
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": address,
            "GIT_COMMITTER_NAME": name,
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
        # THE FILESYSTEM PROBES ARE TRANSLATED TOO. `exists()`, `is_dir()` and
        # `resolve()` all raise `PermissionError` for a path whose parent is
        # present and not searchable, and `resolve()` can raise `OSError` for a
        # symlink loop — so a location this adapter could not READ left an OS
        # exception where the protocol promises a refusal, and the API turned
        # it into a 500 (Copilot review of openDox-code#26, round 12,
        # suppressed). A missing path and an unreadable one are still different
        # answers.
        #
        # AND `RuntimeError`, WHICH IS THE LOOP CASE ITSELF. MEASURED on python
        # 3.12: `Path.resolve()` does not let `ELOOP` through — it raises
        # `RuntimeError("Symlink loop from …")` — so the handler this comment
        # describes did not catch the example it names. Found by writing the
        # test for the sibling fix in `repository_act.repository_location`.
        try:
            # `expanduser()` IS INSIDE THE TRANSLATION, not above it. MEASURED
            # on python 3.12.3: `Path("~nosuchuser12345/x").expanduser()`
            # raises `RuntimeError: Could not determine home directory.` — and
            # `ref.location` is a caller's string. That one construction above
            # the `try` was the last way a caller's location could still reach
            # the API as a 500 instead of this function's refusal (Copilot
            # review of openDox-code#26, round 14, suppressed).
            location = Path(ref.location).expanduser()
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
        except (OSError, RuntimeError) as exc:
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
            # DECODED THE WAY EVERY OTHER PATH OUT OF GIT IS, and for the
            # same reason: a filesystem path is bytes, not UTF-8, so a
            # repository whose location holds a non-UTF-8 byte raised
            # `UnicodeDecodeError` out of `resolve` — an exception where this
            # interface promises a corpus or a refusal (Copilot review of
            # openDox-code#26, round 16, suppressed). `surrogateescape` is the
            # same round trip `ls-tree`'s pathnames already get.
            git_dir = Path(decoded_path(
                git.out("rev-parse", "--absolute-git-dir")))
            # AND THE SHARED HALF OF IT, WHICH IS WHERE TWO OF THE THREE LIVE.
            # In a LINKED WORKTREE `--absolute-git-dir` is
            # `<main>/.git/worktrees/<name>`, which holds no `objects/` and no
            # `refs/` at all — those belong to the COMMON directory, and
            # `os.access` on a path that does not exist is `False`, so every
            # linked worktree resolved read-only however writable it was
            # (Copilot review of openDox-code#26, round 13, suppressed).
            # Measured on git 2.43.0, `git worktree add ../wt -b side`:
            #
            #     --absolute-git-dir             <main>/.git/worktrees/wt
            #     --path-format=absolute
            #                 --git-common-dir   <main>/.git
            #     objects/ under the git dir     ABSENT
            #     objects/ under the common dir  present
            #     refs/heads/ under the common   present
            #     index under the git dir        present
            #
            # For an ordinary checkout and for the BARE repository this act
            # creates the two answers are the same directory, so this is the
            # same probe there. `--path-format=absolute` is required: on its
            # own `--git-common-dir` answers the relative `.git`, which would
            # then be probed against THIS PROCESS's working directory.
            common_dir = Path(
                decoded_path(git.out("rev-parse", "--path-format=absolute",
                                     "--git-common-dir")))
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
            # The git dir stays in the list on its own account: `write_back`
            # writes its TEMPORARY INDEX there, and a worktree's index is its
            # own rather than the common directory's.
            served = self._writable_ref_home(git, common_dir, str(location))
            reachable = all(
                os.access(path, os.W_OK | os.X_OK)
                for path in (git_dir, common_dir / "objects", served))
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
        with self._bound(corpus, CORPUS_UNREADABLE, corpus.location,
                         absent=CORPUS_ABSENT) as git:
            return self._list_documents_bound(git, corpus, scope)


    def _list_documents_bound(self, git: GitRunner, corpus: ResolvedCorpus,
                              scope: str) -> tuple[DocumentId, ...]:
        """`list_documents`'s git half, on a runner bound to an open directory."""
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
        with self._bound(corpus, CORPUS_UNREADABLE, corpus.location,
                         absent=CORPUS_ABSENT) as git:
            return self._read_bound(git, corpus, document, revision)


    def _read_bound(self, git: GitRunner, corpus: ResolvedCorpus,
                    document: DocumentId, revision: str | None) -> Document:
        """`read`'s git half, on a runner bound to an open directory."""
        if revision is None:
            at = corpus.revision
        else:
            # THE CORPUS IS ASKED FIRST, as it is everywhere else in this
            # module. `_resolve_revision` translates a `rev-parse` failure into
            # `REVISION_UNKNOWN`, and a repository DELETED or made unreadable
            # after it resolved fails `rev-parse` too — so an explicit-revision
            # read reported "this repository cannot serve that revision" for a
            # repository that could no longer serve any (Copilot review of
            # openDox-code#26, round 13). The same check the document lookup
            # below already makes, one branch earlier.
            self._revalidate(git, corpus)
            at = self._resolve_revision(git, revision, corpus.location)
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

        BOUNDED IN THE SCAN AS WELL AS IN THE LOOP. This read
        `text.splitlines()[:MAX_HEADER_LINES]`, and `splitlines` builds the
        list of EVERY line before the slice takes sixty-four of them — so
        classifying one document in a corpus of large ones allocated each whole
        body a second time, under a comment promising it did not (Copilot
        review of openDox-code#26, round 14, suppressed). `_leading_lines`
        yields the same lines and stops.
        """
        text = self.read(corpus, document).content.decode("utf-8", "replace")
        header: dict[str, str] = {}
        for line in _leading_lines(text, MAX_HEADER_LINES):
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
        with self._bound(corpus, CORPUS_UNREADABLE, corpus.location,
                         absent=CORPUS_ABSENT) as git:
            return self._check_bound(git, corpus, subjects)


    def _check_bound(self, git: GitRunner, corpus: ResolvedCorpus,
                     subjects: tuple[DocumentId, ...] | None) -> tuple[Finding, ...]:
        """`check`'s git half, on a runner bound to an open directory."""
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
            # `--no-ext-diff` AND `--no-textconv`, because a repository can
            # name a PROGRAM. `diff.external` and a `diff.<driver>.textconv`
            # are ordinary config in the repository this adapter was pointed
            # at, and `git diff` runs them — so merely ASKING a project
            # repository what changed executed code in this runtime's process,
            # which is the same class as the `pre-push` hook and the `ext::`
            # transport and was covered by neither (Copilot review of
            # openDox-code#26, round 17). The environment channel
            # `GIT_EXTERNAL_DIFF` is stripped by `_sanitized_git_environment`
            # for the same reason.
            # AND EVERY CLEAN/SMUDGE FILTER THE REPOSITORY DEFINES IS
            # EMPTIED. `--no-ext-diff` and `--no-textconv` cover the two
            # drivers round 17 found and say nothing about `filter.<name>`: a
            # tracked file carrying a `filter=` attribute makes `git diff
            # --name-only` run that driver's `clean` command, because deciding
            # whether the file DIFFERS means normalizing it first. MEASURED on
            # git 2.43.0 — a planted `filter.evil.clean` RAN under exactly the
            # invocation below, and did not run with `-c filter.evil.clean=`
            # (Copilot review of openDox-code#26, round 23).
            #
            # THE NAMES COME FROM THE REPOSITORY'S OWN CONFIG, which is the
            # channel that matters: a driver defined in the OPERATOR's global
            # git is the operator's program, the same trust boundary that keeps
            # `GIT_CONFIG_GLOBAL`. `core.attributesFile` cannot help — MEASURED,
            # the filter still ran with it emptied — because the attribute is
            # in the repository's own `.gitattributes`.
            raw = git.out(*self._emptied_filters(git, corpus.location),
                          "diff", "--no-ext-diff", "--no-textconv",
                          "--name-only", "-z", corpus.revision)
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
        # AND NEITHER TRAILER VALUE MAY FORGE A LINE. `basis_revision` and
        # `actor` are caller-controlled and go into the commit message's
        # trailer block and the author/committer identity unencoded, so
        # `A\nWrite-Path: forged` wrote a second trailer that a reader of the
        # durable history could not tell from a real one (Copilot review of
        # openDox-code#26, round 32).
        # AND THE CORPUS NAME IS ONE OF THEM. `document.corpus` is
        # caller-controlled through `CorpusRef.name` and `_message` writes it
        # as the `Corpus:` trailer, and round 32's list left it out — so the
        # one trailer value that was still unchecked could inject the line the
        # other three can no longer (Copilot review of openDox-code#26, round
        # 33). The document KEY is checked too: it is the message's SUBJECT
        # line, where a newline ends the subject and starts a body nobody
        # wrote.
        for field, value in (("basis revision", basis_revision),
                             ("actor", actor),
                             ("corpus name", document.corpus),
                             ("document key", document.key),
                             ("write path", corpus.write_path)):
            refuse_a_value_that_would_forge_a_commit_trailer(
                field, value, document.key)
        # AND THE CHECK AND THE USE ARE ONE OBJECT — see `_bound`, which every
        # operation now goes through: the re-check below asked about a
        # PATHNAME, and every call after it (`hash-object`, `read-tree`,
        # `commit-tree`, `update-ref`) resolved that pathname again, so a
        # location renamed or re-linked in between put the commit in a
        # different repository after this function had proved it would not
        # (Copilot review of openDox-code#26, round 16).
        with self._bound(corpus, WRITE_PATH_UNREACHABLE,
                         corpus.write_path) as git:
            return self._write_back_bound(
                git, corpus, document, content, actor=actor,
                basis_revision=basis_revision, reason=reason)

    def _write_back_bound(self, git: GitRunner, corpus: ResolvedCorpus,
                          document: DocumentId, content: bytes, *, actor: str,
                          basis_revision: str, reason: str) -> WriteReceipt:
        """`write_back`'s git half, on a runner bound to an open directory.

        AND THE ROOT IS ASKED AGAIN, ON THE ONE OPERATION THAT WRITES.
        `resolve` refuses a location that is inside another repository (see it
        for the defect and the ruling), and a `ResolvedCorpus` comes from
        `resolve` — but this is the call that can commit into somebody else's
        history, and the cost of being sure is one `rev-parse`. It is asked of
        the DESCRIPTOR the caller opened, so the repository this proves is the
        repository every call below writes to.

        AND EVERY WAY THAT QUESTION CAN FAIL IS `WRITE_PATH_UNREACHABLE`.
        `_repository_root` is `resolve`'s helper and refuses with
        `CORPUS_UNREADABLE`, which is a kind `write_back` does not declare (the
        interface gives it exactly two: `CORPUS_READ_ONLY` and
        `WRITE_PATH_UNREACHABLE`), so a git that vanished between `resolve` and
        this call sent a caller branching on `err.refusal.kind` a kind this
        operation never promised (Copilot review of openDox-code#26, round 13,
        suppressed). The failure is real and is still refused — it is reported
        as the kind this operation owes. `Path.resolve` is inside the same
        guard for the same reason, and because a symlink loop under the
        location raises `RuntimeError`, not `OSError`.
        """
        try:
            root = self._repository_root(git, corpus.location)
            named = Path(corpus.location).resolve()
        except CorpusRefused as refused:
            raise _refuse(
                WRITE_PATH_UNREACHABLE, corpus.write_path,
                f"the repository holding {corpus.location} could not be "
                f"identified ({refused.refusal.detail}); nothing is written, "
                "because a commit can only be made into the repository this "
                "corpus IS") from refused
        except (OSError, RuntimeError) as exc:
            raise _refuse(
                WRITE_PATH_UNREACHABLE, corpus.write_path,
                f"{corpus.location} could not be resolved "
                f"({exc.__class__.__name__}); nothing is written, because the "
                "repository the commit would land in cannot be named"
            ) from exc
        if root != named:
            # TWO FACTS, ONE COMPARISON, and the message says both because the
            # write refuses either way: the location may be INSIDE another
            # repository (the defect RULED 5714365086 Q-F3 closed), or the NAME
            # may have been re-pointed since the descriptor was opened — which
            # this comparison can now see precisely because `root` comes from
            # the held directory and `named` from the path (round 16).
            raise _refuse(
                WRITE_PATH_UNREACHABLE, corpus.location,
                f"this write is bound to the repository at {root}, and "
                f"{corpus.location} no longer resolves to it: either the "
                "location is inside that repository rather than being it, or "
                "the name was re-pointed after the corpus resolved. Nothing "
                "is written, because a commit must land in the repository the "
                "caller named and nowhere else")
        try:
            blob = git.out("hash-object", "-w", "--stdin",
                           stdin=content).decode().strip()
            # The temporary index lives inside the REAL git directory, which is
            # `<location>/.git` for a checkout and `<location>` itself for the
            # BARE repository the act creates — so it is asked for rather than
            # assumed.
            git_dir = Path(decoded_path(
                git.out("rev-parse", "--absolute-git-dir")))
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

            message = self._message(document, actor, basis_revision, reason,
                                    corpus.write_path)
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

    @contextmanager
    def _bound(self, corpus: ResolvedCorpus, kind: str, subject: str,
               absent: str | None = None) -> Iterator[GitRunner]:
        """A runner whose `-C` is an OPEN DIRECTORY, for the whole operation.

        Every operation used to take `self._git(corpus)` and then make several
        git calls through it, each of which re-resolved the PATHNAME — so a
        location renamed or re-linked part way through an operation was a
        different repository for the rest of it: `read` could revalidate one
        directory and serve bytes from another, and `check` could compare a
        replacement's working tree (Copilot review of openDox-code#26, round
        17). The directory is opened `O_NOFOLLOW` component by component and
        git is handed `/proc/self/fd/<n>`, which is the binding
        `repository_act.initialize_repository` uses and `runner_bound_to`
        states the platform ladder for.

        WHAT THIS DOES NOT CLOSE, and it is registered rather than implied: an
        operation binds what `corpus.location` names AT ITS OWN START, not what
        `resolve` named. A repository replaced by another VALID repository
        between the two is served, because proving otherwise means carrying a
        resolution-time identity on `ResolvedCorpus` — which belongs to
        `opendox.corpus_adapter`, the NEUTRAL contract openxFactory pins by
        commit and digest and this act may not widen. Same reason, and the same
        residue, as binding the served ref at resolution (round 12).
        """
        try:
            handle = open_no_follow_chain(Path(corpus.location))
        except FileNotFoundError as gone:
            # A CORPUS THAT WENT AWAY IS ABSENT, NOT UNREADABLE, wherever the
            # caller says so: `_revalidate` has always drawn that line and this
            # helper now runs before it, so it has to draw the same one.
            # `write_back` passes no `absent` kind, because the two it may
            # raise do not include `CORPUS_ABSENT`.
            raise _refuse(
                absent or kind, subject,
                f"{corpus.location} is no longer there") from gone
        except (OSError, RuntimeError) as exc:
            raise _refuse(
                kind, subject,
                f"{corpus.location} could not be opened without following a "
                f"link ({exc.__class__.__name__}); this corpus is refused "
                "rather than read through a name that may lead elsewhere"
            ) from exc
        try:
            git = runner_bound_to(handle, Path(corpus.location),
                                  self._executable)
            # AND THE ROOT RULE IS THE SAME ONE `resolve` APPLIES. `git -C`
            # discovers a repository by WALKING UP, and the descriptor stops a
            # pathname swap without stopping that: a location replaced by an
            # ordinary subdirectory of another checkout was served from the
            # ENCLOSING repository — the very defect RULED 5714365086 Q-F3
            # closed at resolution, reachable again through every operation
            # that reopens the location (Copilot review of openDox-code#26,
            # round 18). `write_back` and the repository acts already re-check
            # it; this is where the reads get it.
            root = self._repository_root(git, corpus.location)
            if root != Path(corpus.location).resolve():
                raise _refuse(
                    kind, subject,
                    f"this operation is bound to the repository at {root}, and "
                    f"{corpus.location} no longer resolves to it: either the "
                    "location is inside that repository rather than being it, "
                    "or the name was re-pointed after the corpus resolved")
        except (OSError, RuntimeError) as exc:
            os.close(handle)
            raise _refuse(
                kind, subject,
                f"{corpus.location} could not be re-examined "
                f"({exc.__class__.__name__})") from exc
        except CorpusRefused as refused:
            # AND A REFUSAL RAISED IN HERE TAKES THIS OPERATION'S KIND.
            # `_repository_root` is `resolve`'s helper and says
            # `CORPUS_UNREADABLE` — a kind `write_back` does not declare, the
            # interface giving it exactly two — so removing a checkout's `.git`
            # after `resolve` made the probe above refuse with a kind the
            # operation never promised, and `_write_back_bound`'s own remap is
            # AFTER the yield and never reached (Copilot review of
            # openDox-code#26, round 21). The refusal is real and is still
            # made; what changes is that it arrives in this operation's
            # vocabulary, with the original kind kept in the detail so nothing
            # is hidden from whoever reads it.
            os.close(handle)
            if refused.refusal.kind == kind:
                raise
            raise _refuse(
                kind, subject,
                f"{refused.refusal.detail} [{refused.refusal.kind}]"
            ) from refused
        except BaseException:
            os.close(handle)
            raise
        # THE YIELD IS OUTSIDE THE TRANSLATION and inside a `finally`: an
        # exception from the CALLER's body is the caller's, and the handle is
        # released whatever it is.
        try:
            yield git
        finally:
            os.close(handle)

    def _emptied_filters(self, git: GitRunner, subject: str) -> tuple[str, ...]:
        """`-c filter.<name>.clean=` … for every driver this repository names.

        One `git config` read, and a `-c` pair per driver and per verb. A
        repository that defines none — which is every repository this act
        creates — pays one probe and adds no options.

        It is the READ path's version of the rule `repository_act` applies to
        the push: a program named by the repository this service was pointed at
        is not a program this service runs. The read cannot refuse the way the
        push does, because `check` owes an answer about a corpus somebody else
        may legitimately have filtered — so the driver is EMPTIED for this
        call, which makes the answer conservative (a filtered file reads as
        changed) rather than executable.
        """
        # BOTH SCOPES, because `--local` is not all of a repository's own
        # config. With `extensions.worktreeConfig` set, a LINKED WORKTREE keeps
        # its own `config.worktree`, and a `filter.<name>.clean` defined there
        # is invisible to `--local` and is still run. MEASURED on git 2.43.0:
        #
        #   git config extensions.worktreeConfig true
        #   git config --worktree filter.evil.clean 'sh -c "echo PWNED >&2; cat"'
        #   git config --local --get-regexp '^filter\.'   -- exit 1, nothing
        #   git config --worktree --get-regexp '^filter\.' -- filter.evil.clean …
        #   git diff --name-only                          -- PWNED
        #
        # The override itself already worked (`-c filter.evil.clean=` silenced
        # it); what did not was FINDING the name to override (Copilot review of
        # openDox-code#26, round 29). `--worktree` is an error where the
        # extension is off, which is the usual case, so its failure is as
        # ordinary as `--local` returning nothing.
        keys: list[str] = []
        for scope in ("--local", "--worktree"):
            listed = self._probe(git, "config", scope, "--name-only",
                                 "--get-regexp",
                                 r"^filter\..*\.(clean|smudge|process)$",
                                 kind=CORPUS_UNREADABLE, subject=subject)
            if listed.returncode != 0:
                continue                  # "none set", or no worktree config
            keys += listed.stdout.decode("utf-8", "replace").split()
        options: list[str] = []
        for key in dict.fromkeys(keys):   # DEDUPLICATED, order kept
            if key.startswith("filter.") and key.count(".") >= 2:
                options += ["-c", key + "="]
        return tuple(options)

    def _writable_ref_home(self, git: GitRunner, common_dir: Path,
                           subject: str) -> Path:
        """The directory `update-ref` would write the SERVED ref into.

        `refs/heads/<branch>`'s parent where HEAD names a branch, walked up to
        the nearest ancestor that exists (a repository using only packed refs
        has no `refs/heads/` until the first write, and git creates it).

        Resolved against the COMMON directory, which is where `refs/heads`
        lives for every worktree of a repository; see `resolve` for the
        measurement.

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
        home = common_dir / Path(ref).parent
        while not home.is_dir() and home != common_dir:
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
        named = decoded_path(answer.stdout)
        try:
            return Path(named).resolve()
        except (OSError, RuntimeError) as exc:
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
        except (OSError, RuntimeError) as exc:
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
            # A REF NAME IS BYTES. git permits anything but a short list of
            # characters, so a branch whose name is not UTF-8 raised
            # `UnicodeDecodeError` out of a function that owes a refusal
            # (Copilot review of openDox-code#26, round 17). Same round trip
            # the pathnames get.
            ref = decoded_ref_name(symbolic.stdout)
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
            # A REF NAME IS BYTES. git permits anything but a short list of
            # characters, so a branch whose name is not UTF-8 raised
            # `UnicodeDecodeError` out of a function that owes a refusal
            # (Copilot review of openDox-code#26, round 17). Same round trip
            # the pathnames get.
            ref = decoded_ref_name(symbolic.stdout)
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
                 reason: str, write_path: str) -> str:
        """The trailer names THIS CORPUS's write path, not the default.

        `write_path` became a per-corpus construction datum (RULED 5714365086
        Q-F2) and `WriteReceipt.dispatched_to` already carries the constructed
        value — but the commit trailer still spelled the module default, so a
        corpus constructed with another write path produced a receipt and a
        commit that disagreed about where the write went (Copilot review of
        openDox-code#26, round 13, suppressed). The commit is the durable
        record; it has to be the one that is right.
        """
        subject = f"Write {document.key}"
        body = [subject, ""]
        if reason:
            body.extend([reason, ""])
        body.append(f"Corpus: {document.corpus}")
        body.append(f"Basis-Revision: {basis_revision}")
        body.append(f"Dispatched-By: {actor}")
        body.append(f"Write-Path: {write_path}")
        return "\n".join(body) + "\n"
