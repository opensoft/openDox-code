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


def _committed_blob(repo: Path, key: str) -> bytes:
    """The bytes git actually holds for `key` at HEAD.

    A KEY THAT WAS NEVER COMMITTED IS NAMED, not left as a git error. git
    answers `fatal: path … exists on disk, but not in 'HEAD'` and exits
    non-zero, and `check=True` turned that into a `CalledProcessError` whose
    reader learns that a subprocess failed rather than that their corpus is
    short one document. The failure is real and still refuses — this only
    decides what the refusal SAYS (Copilot review of PR #31, registered by the
    lander and taken here).
    """
    try:
        return subprocess.run(
            ("git", *_HARDENING, "cat-file", "blob", f"HEAD:{key}"),
            cwd=repo, check=True, capture_output=True,
            env={**_sanitized_git_environment(),
                 "GIT_NO_REPLACE_OBJECTS": "1"},
        ).stdout
    except subprocess.CalledProcessError as failed:
        raise ValueError(
            f"the transposition does not hold {key!r} at all: it was copied "
            f"into the working tree and git has no blob for it at HEAD, so "
            f"something kept it out of the commit. An ignore rule is the "
            f"usual cause — a `.gitignore` carried in with the corpus, or an "
            f"`info/exclude` — and a transposition missing a document is not "
            f"a transposition of this corpus") from failed


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
        raise ValueError(
            "the transposition committed nothing: every file copied into it "
            "was excluded before `git commit` saw it. An ignore rule is the "
            "usual cause, and this act disables the configured one and forces "
            "the add, so the rule is somewhere this act does not reach — and "
            "a corpus with no documents in it is not a transposition of this "
            "corpus") from failed

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
