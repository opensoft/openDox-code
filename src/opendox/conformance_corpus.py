"""openDox's reader for the NEUTRAL conformance corpus — FLOOR PART 3.

`split-opendox-two-layer-product` § 3.7 asks that EVERY destination pass the
neutral corpus openxFactory ships at `tests/corpus-adapter/fixtures`, and the
box says what that takes from this leg in its own words: a DECLARED factory,
and — because this destination's reader addresses git HISTORY rather than a
working tree — RULED Q-F1 (a)'s TRANSPOSITION, "the DESTINATION transposes the
same documents into the storage form its own reader addresses, bytes unchanged,
and says so".

    python3 scripts/verify-carve-conformance.py \
        --destination opendox_code \
        --dest-root   <this checkout> \
        --adapter     opendox.conformance_corpus:reader \
        --corpus      <the transposition>

TWO FUNCTIONS AND NO THIRD. `reader` is the factory the runner imports;
`transpose` lays the corpus down in git. Neither invents a document, a key or a
byte: the runner's fidelity proof compares what this reader SERVES against a
`{key: sha256(bytes)}` table computed off openxFactory's own files, so anything
this module decided for itself would be caught as `conformance-corpus-unfaithful`
rather than passed. That is the point of the ruling — the permission to transpose
comes with a proof, because narrowing the corpus to what a reader passes today
would be FLOOR PART 3 deleted to tick FLOOR PART 3.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

from .runtime.local_git_adapter import (
    LocalGitCorpus, _sanitized_git_environment,
)

#: The corpus's four states, by the names openxFactory's seed laid them down
#: under and the runner looks for. They are the CORPUS's vocabulary, not
#: openDox's, which is why they are literals here rather than anything derived
#: from this package.
POPULATED = "neutral"
EMPTY = "empty"
UNREADABLE = "not-a-directory"

#: The neutral corpus's own two-field header. `Type` and `Title` are ITS
#: vocabulary — a corpus that "has never heard of a factory", in the words of
#: its own first document — so they are stated here as values rather than taken
#: from any openDox default.
NEUTRAL_KIND_FIELD = "Type"
NEUTRAL_REQUIRED_FIELDS = ("Type", "Title")


def reader(name: str, location: str) -> LocalGitCorpus:
    """The factory FLOOR PART 3 asks for: a reader pointed at one location.

    NEITHER ARGUMENT IS USED, and that is the property being measured rather
    than an oversight. The location rides in the `CorpusRef` handed to
    `resolve`, and the name is the caller's word for the corpus, so one reader
    built from the corpus's terms alone can be pointed at all four of its
    states in a single run — which is exactly what the corpus's three
    resolution-time negative confirmations require.

    `write_path=None` IS LOAD-BEARING and is not a default taken lightly:
    `LocalGitCorpus` declares openDox's own governed write path, and the
    corpus's `read-only-declared-at-resolution` check asserts that resolution
    reports NO declared write path — "this corpus declares none, so a reader is
    inventing one". A reader that brought openDox's write path to somebody
    else's corpus would fail that check, and would deserve to.
    """
    del name, location
    return LocalGitCorpus(write_path=None,
                          kind_field=NEUTRAL_KIND_FIELD,
                          required_fields=NEUTRAL_REQUIRED_FIELDS)


#: Settings pinned OFF for every git this module runs, and each one is a way
#: the ambient machine could change the bytes or the repository under it.
#:
#: `core.autocrlf` / `core.eol` / `core.safecrlf` are the byte channel:
#: `git add` runs the clean filter and EOL normalization on the way IN, so a
#: machine configured for CRLF would commit bytes that are not the ones
#: `shutil.copyfile` laid down — and this function's entire promise is that
#: they are. `core.attributesFile` and `GIT_ATTR_NOSYSTEM` close the same
#: channel's other two entrances.
#:
#: `core.excludesFile` IS THE FOURTH CHANNEL AND IT IS NOT A BYTE ONE — it
#: decides which files exist in the transposition at all. `GIT_CONFIG_GLOBAL`
#: is retained deliberately (an operator's own git is this act's git), so a
#: global ignore file reaches the `git add` below. MEASURED at `776d2a80`, both
#: shapes: an excludes file of `*.md` staged NOTHING, so the commit refused and
#: `transpose` raised; one naming only `beta.md` let the commit SUCCEED with a
#: short tree, and the byte read-back then refused because git cannot answer
#: for a key it never committed (Copilot review of PR #31, and the lander's
#: measurement on it). Neither is a silent short transposition — that is what
#: the read-back is for — but both met a raw `CalledProcessError` instead of a
#: sentence, and both are closed here rather than reported: this switch, and
#: `--force` on the add for the entrances a config switch cannot reach (a
#: `.gitignore` COPIED IN with the corpus, and `$GIT_DIR/info/exclude`).
#:
#: `core.hooksPath` and the three signing switches name PROGRAMS the ambient
#: configuration chooses, which `local_git_adapter` already refuses for the
#: runtime and refuses here for the same reason.
#: `init.templateDir` IS THE ONE THAT SURVIVES THE REST, and it is disabled
#: here rather than argued about: `git init` copies the template into the new
#: `$GIT_DIR`, and a template carrying `info/attributes` installs REPOSITORY-
#: LOCAL attributes that `core.attributesFile` does not override. MEASURED on
#: this tree — a template whose `info/attributes` says `* filter=evil` and a
#: global `filter.evil.clean` rewrote a document's bytes straight through
#: `core.attributesFile=/dev/null`; the byte check below caught it and refused,
#: which is the right failure and still the wrong outcome, because the
#: transposition then cannot be built at all on that machine. Emptied, the same
#: run commits the file's own bytes. (Copilot review of PR #31, round 2.)
_HARDENING = (
    "-c", "init.templateDir=",
    "-c", "core.hooksPath=" + os.devnull,
    "-c", "core.autocrlf=false",
    "-c", "core.eol=lf",
    "-c", "core.safecrlf=false",
    "-c", "core.attributesFile=" + os.devnull,
    "-c", "core.excludesFile=" + os.devnull,
    "-c", "commit.gpgSign=false",
    "-c", "tag.gpgSign=false",
    "-c", "user.name=conformance",
    "-c", "user.email=conformance@openDox.invalid",
)


def _git(repo: Path, *args: str) -> None:
    """Run one git command in `repo`, with nothing ambient reaching it.

    THE ENVIRONMENT IS THE RUNTIME'S OWN SANITIZED ONE, not `os.environ`.
    `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY` and
    their relatives OUTRANK `cwd`, so a process started with one of them set —
    a CI job inside another checkout, a git hook, an alias — would have had
    `init`, `add` and `commit` operate on a DIFFERENT repository while this
    function reported building the transposition. `local_git_adapter` strips
    exactly that set for the runtime and the same list is the right one here;
    it is imported rather than restated so the two cannot drift apart.
    (Copilot review of PR #31.)

    `GIT_NO_REPLACE_OBJECTS` is set ON TOP: replacement objects can make git
    serve different content for an object than the one committed, which would
    put the transposition's bytes back in the ambient machine's gift after
    everything above took them out of it.

    The identity is supplied per-command rather than written into the new
    repository's config: a transposition is a throwaway and must not depend on
    the machine's git identity being set, which on a CI runner it is not.
    """
    environment = _sanitized_git_environment()
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    environment["GIT_ATTR_NOSYSTEM"] = "1"
    subprocess.run(("git", *_HARDENING, *args), cwd=repo, check=True,
                   capture_output=True, env=environment)


def _what_git_said(*streams: bytes | None) -> str:
    """git's own words for a failure, from WHICHEVER stream carried them.

    BOTH STREAMS, AND THAT IS MEASURED rather than defensive (git 2.43.0):
    `commit -q` with nothing staged writes `nothing to commit (create/copy
    files and use "git add" to track)` to STDOUT and leaves stderr EMPTY,
    while a `commit` blocked by an `index.lock` writes `fatal: Unable to
    create …` to STDERR and leaves stdout empty. A refusal that quoted only
    stderr would quote nothing in exactly the exclusion case these messages
    exist to name.

    QUOTING GIT IS SAFE HERE, and the asymmetry with `local_git_adapter` —
    which refuses to put git's stderr in a refusal — is deliberate and not an
    oversight. That module runs `push` against a REMOTE, and a remote URL can
    carry an authority and a credential in it. Nothing in this module touches
    a remote: the transposition is `init`, `add`, `commit`, `ls-tree` and
    `cat-file` inside a directory this process just made, so git's words here
    carry local paths and object ids and nothing that could be a secret.
    """
    said = b"\n".join(part for part in streams if part)
    return " ".join(said.decode("utf-8", "replace").split()) or "nothing at all"


def _committed_blob(repo: Path, key: str) -> bytes:
    """The bytes git actually holds for `key` at HEAD.

    A KEY THAT WAS NEVER COMMITTED IS NAMED, not left as a git error. git
    answers `fatal: path … does not exist in 'HEAD'` and exits non-zero, and
    `check=True` turned that into a `CalledProcessError` whose reader learns
    that a subprocess failed rather than that their corpus is short one
    document. The failure is real and still refuses — this only decides what
    the refusal SAYS (Copilot review of PR #31, registered by the lander and
    taken here).

    AND THE EXIT STATUS DOES NOT SAY WHICH FAILURE IT WAS, so this asks the
    TREE instead of inferring from it. A corrupt or pruned object database
    fails `cat-file` identically to a missing path, and the first cut of this
    translation told that operator an ignore rule was the usual cause, which
    is a diagnosis of something that did not happen (Copilot review of PR #33
    at `conformance_corpus.py:181`). `ls-tree` separates the two exactly
    (MEASURED on git 2.43.0, in a one-commit repository):

    ================================  =========================  ============
    state                             `cat-file blob HEAD:<key>`  `ls-tree`
    ================================  =========================  ============
    key absent from HEAD              `does not exist in 'HEAD'`  rc 0, EMPTY
    key present, object unreadable    `bad file`                  rc 0, names
    HEAD itself unreadable            non-zero                    non-zero
    ================================  =========================  ============

    So all three are answered, each in its own sentence, and each quotes what
    git actually said.

    THE PROBE'S OWN PATHSPEC MUST BE LITERAL, or the table above is not the
    whole story. A key beginning with `:` and a reserved short-magic mnemonic
    (`!`, `^`, `@`, `-`, among others) or with `:(` is not read as a path at
    all: git parses the leading `:` as PATHSPEC MAGIC and refuses the whole
    `ls-tree` before it ever asks the tree. MEASURED on git 2.43.0: a key of
    `:!doomed.md` — never committed, ordinary in every other way — makes
    `cat-file` fail exactly like any absent key (`does not exist in 'HEAD'`),
    and then makes THIS probe exit 128 with `pathspec magic not supported by
    this command: 'exclude'`, which the branch below reads as "HEAD or the
    repository itself is the problem" — true of the exit status and false of
    the key, which was simply never committed. `--literal-pathspecs` closes
    it: measured on the same key, the probe then reports rc 0 and an empty
    listing, indistinguishable from any other absent key.

    A key CONTAINING `*` was measured to need no such guard. `ls-tree` does
    not expand a bare pathspec as a glob at all — measured on a tree holding
    `alpha.md`, `beta.md` and a file literally named `a*.md`, `-- '*.md'`
    matched NONE of the three, and `-- 'a*.md'` matched only the one file
    actually named that — so `--literal-pathspecs` is added here for the `:`
    case alone, and not because a glob was found to misbehave.
    """
    reading = {**_sanitized_git_environment(), "GIT_NO_REPLACE_OBJECTS": "1"}
    try:
        return subprocess.run(
            ("git", *_HARDENING, "cat-file", "blob", f"HEAD:{key}"),
            cwd=repo, check=True, capture_output=True, env=reading,
        ).stdout
    except subprocess.CalledProcessError as failed:
        said = _what_git_said(failed.stderr, failed.stdout)
        listed = subprocess.run(
            ("git", *_HARDENING, "--literal-pathspecs", "ls-tree",
             "--name-only", "HEAD", "--", key),
            cwd=repo, capture_output=True, env=reading)
        if listed.returncode != 0:
            raise ValueError(
                f"the transposition would not give up {key!r}, and this act "
                f"cannot even ask its tree what it holds — `git ls-tree HEAD` "
                f"failed too, so HEAD or the repository itself is the "
                f"problem and no ignore rule is implicated. git said "
                f"{said!r} for the blob and "
                f"{_what_git_said(listed.stderr, listed.stdout)!r} for the "
                f"tree") from failed
        if listed.stdout.strip():
            raise ValueError(
                f"git HOLDS {key!r} at HEAD and would not give up its bytes, "
                f"so this is NOT an exclusion: the key is in the commit and "
                f"the object behind it did not come back. A corrupt or pruned "
                f"object database is the shape that does this. git said "
                f"{said!r}") from failed
        raise ValueError(
            f"the transposition does not hold {key!r} at all: it was copied "
            f"into the working tree, `git ls-tree HEAD` does not list it, and "
            f"git has no blob for it — so something kept it out of the "
            f"commit. An ignore rule is the usual cause — a `.gitignore` "
            f"carried in with the corpus, or an `info/exclude` — and a "
            f"transposition missing a document is not a transposition of "
            f"this corpus. git said {said!r}") from failed


def _fingerprint(populated: Path) -> dict[str, str]:
    """`{key: sha256(bytes)}` off the FILES — the runner's own table.

    The same rule the runner applies, deliberately: every file under the
    populated state counts, and no judgement about what a "document" is enters
    into it.
    """
    return {path.relative_to(populated).as_posix():
            hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(populated.rglob("*")) if path.is_file()}


def transpose(shipped: Path, destination: Path) -> Path:
    """Lay openxFactory's neutral corpus down in the form this reader reads.

    `shipped` is openxFactory's `tests/corpus-adapter/fixtures`; `destination`
    is an empty directory to build the transposition in. Returns `destination`,
    which is what `--corpus` takes.

    WHAT IS PRESERVED, AND WHY EACH ONE MATTERS TO THE PROOF:

    * BYTES — copied with `shutil.copyfile`, never rewritten, never
      re-encoded, never line-ending-normalised. The runner hashes the shipped
      files and compares against what this reader serves.
    * KEYS — the reader derives them from `git ls-tree -r`, so they are the
      paths as committed. Copying the populated state's tree verbatim makes
      them identical to the runner's `Path.relative_to(populated).as_posix()`
      spelling, which is the comparison's other side.
    * THE POPULATION — every file under the populated state is copied, and
      nothing else is added. A transposition that dropped a file by deciding
      it was not a document, or added a `.gitkeep` of its own, would change
      the key set; the runner's table has an entry for every file it finds and
      no reader's judgement in it.

    ALL FOUR STATES ARE BUILT, not just the populated one, because the
    seventeen checks resolve four locations and three of them are negative
    confirmations: an EMPTY corpus must be an answer rather than a refusal, a
    NON-DIRECTORY must refuse as unreadable, and an ABSENT one must refuse as
    absent. The absent state is built by NOT creating it, which is the only
    way to build it honestly.
    """
    populated = shipped / POPULATED
    if not populated.is_dir():
        raise FileNotFoundError(
            f"the shipped corpus's populated state is not at {populated}. "
            f"Point `shipped` at openxFactory's tests/corpus-adapter/fixtures")
    destination.mkdir(parents=True, exist_ok=True)

    # --- the populated state: a git repository holding exactly its files ----
    target = destination / POPULATED
    target.mkdir()
    _git(target, "init", "-q")
    for source in sorted(populated.rglob("*")):
        if not source.is_file():
            continue
        laid = target / source.relative_to(populated)
        laid.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, laid)
    # `--force` BESIDE THE SWITCH, because they close different doors.
    # `core.excludesFile=` disables the ambient ignore file; `--force` is what
    # answers the two entrances no config switch reaches — a `.gitignore`
    # COPIED IN with the corpus (the shipped corpus is arbitrary files and one
    # of them may be exactly that), and `$GIT_DIR/info/exclude`. Forcing is
    # right here and would be wrong in the runtime: this repository is built by
    # this function, one commit old, holding nothing a rule could sensibly
    # exclude.
    _git(target, "add", "-A", "--force")
    try:
        _git(target, "commit", "-q", "-m", "the neutral conformance corpus")
    except subprocess.CalledProcessError as failed:
        # NOTHING STAGED IS THE TOTAL-EXCLUSION SHAPE, and it used to arrive as
        # a `CalledProcessError` naming a git command (measured at `776d2a80`
        # with a global excludes file of `*.md`). The switch and `--force`
        # above close it; this names it if some entrance nobody has thought of
        # opens it again, because a reader meeting an exit status learns
        # nothing about their machine.
        #
        # AND IT IS THE INDEX THAT SAYS SO, not this act's confidence. The
        # first cut stated an ABSOLUTE — "every file copied into it was
        # excluded" — for a failure that a full disk, an unwritable object
        # database or a lock left by a crashed process produces identically
        # (Copilot review of PR #33 at `conformance_corpus.py:258`). That is
        # the same defect this act removes from the workflow's skip-pin
        # message one file over, so it is removed here too: the INDEX answers
        # whether anything was staged, and the two shapes get two sentences.
        # MEASURED on git 2.43.0 — nothing staged exits 1 with `nothing to
        # commit …` on STDOUT, a held `index.lock` exits 128 with `fatal:
        # Unable to create …` on STDERR, and the index reads correctly in both.
        #
        # `ls-files --cached -z` AND NOT `diff --cached --name-only`, for two
        # measured reasons (Copilot review of PR #33 at
        # `conformance_corpus.py:343`). First, `-z` is the only spelling that
        # survives a pathname with a SPACE in it: `.split()` reported `my
        # notes/a b.md` and `plain.md` as FOUR paths, and the count is the
        # evidence the refusal below offers its reader. Second, `ls-files` is
        # index-only plumbing with no diff machinery in it at all. The review
        # held that `diff --cached --name-only` could run a configured
        # `diff.external` or textconv; MEASURED, it does not — with a global
        # `diff.external`, a `textconv` and an in-tree `.gitattributes`, the
        # `--name-only` form ran NOTHING while a bare `git diff --cached` ran
        # the program once per path — so the claim is false and the objection
        # is still right: that safety came from a FLAG, and an edit dropping it
        # would open exactly that hole. This spelling has no such flag to drop.
        staged = subprocess.run(
            ("git", *_HARDENING, "ls-files", "--cached", "-z"),
            cwd=target, capture_output=True,
            env={**_sanitized_git_environment(),
                 "GIT_NO_REPLACE_OBJECTS": "1"})
        names = ([name for name in staged.stdout.split(b"\0") if name]
                 if staged.returncode == 0 else None)
        said = _what_git_said(failed.stderr, failed.stdout)
        if names == []:
            raise ValueError(
                f"the transposition staged NOTHING, so `git commit` had "
                f"nothing to make: every file copied in was kept out of the "
                f"index. An ignore rule this act cannot reach is the usual "
                f"cause — the configured one is disabled with "
                f"`core.excludesFile=` and the add is forced, so a rule that "
                f"still bites is somewhere neither reaches — and a populated "
                f"state with no files in it does the same thing. A corpus "
                f"with no documents in it is not a transposition of this "
                f"corpus. git said {said!r}") from failed
        counted = ("and the index could not be read either"
                   if names is None else
                   f"{len(names)} path(s) are staged and waiting")
        raise ValueError(
            f"`git commit` failed and it is NOT an exclusion: {counted}. The "
            f"causes, and this list is not closed: (1) an exclusion — ruled "
            f"out here by the index itself; (2) no space left on the device; "
            f"(3) a permission the object database or the index does not "
            f"grant this process; (4) another git failure entirely, a lock "
            f"left by a crashed process among them. git said "
            f"{said!r}") from failed

    # AND THE BYTES ARE VERIFIED OUT OF GIT, not trusted to the settings above.
    # Pinning the filters off is a defence; reading the committed blob back is
    # a PROOF, and this function's whole claim is byte preservation. A
    # transposition that differs by one byte must refuse here rather than be
    # handed to the runner, which would refuse it as
    # `conformance-corpus-unfaithful` after the fact — the same verdict, but
    # reported against the corpus instead of against the thing that changed
    # the bytes. (Copilot review of PR #31.)
    for key, expected in _fingerprint(populated).items():
        served = hashlib.sha256(_committed_blob(target, key)).hexdigest()
        if served != expected:
            raise ValueError(
                f"the transposition does not carry {key!r} byte for byte: "
                f"the file hashes {expected} and the committed blob hashes "
                f"{served}. Something between `copyfile` and `commit` changed "
                f"it — a clean filter or an EOL normalization is the usual "
                f"cause — and a transposition whose bytes are not the "
                f"corpus's is not a transposition of this corpus")

    # --- the empty state: a repository, and no documents in it --------------
    # `--allow-empty` rather than a placeholder file, deliberately. A
    # `.gitkeep` would be a tracked path, `ls-tree -r` would list it, and the
    # corpus's `empty-is-an-answer` check would see one document in a corpus
    # whose whole point is that it holds none.
    empty = destination / EMPTY
    empty.mkdir()
    _git(empty, "init", "-q")
    _git(empty, "commit", "-q", "--allow-empty", "-m", "an empty corpus")

    # --- the non-directory state --------------------------------------------
    (destination / UNREADABLE).write_text(
        "not a directory, and the corpus says so\n", encoding="utf-8")

    # --- the absent state is the one that is not created ---------------------
    return destination
