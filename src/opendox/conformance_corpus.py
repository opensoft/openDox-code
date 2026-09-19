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
#: `core.hooksPath` and the three signing switches name PROGRAMS the ambient
#: configuration chooses, which `local_git_adapter` already refuses for the
#: runtime and refuses here for the same reason.
_HARDENING = (
    "-c", "core.hooksPath=" + os.devnull,
    "-c", "core.autocrlf=false",
    "-c", "core.eol=lf",
    "-c", "core.safecrlf=false",
    "-c", "core.attributesFile=" + os.devnull,
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
    """The bytes git actually holds for `key` at HEAD."""
    return subprocess.run(
        ("git", *_HARDENING, "cat-file", "blob", f"HEAD:{key}"),
        cwd=repo, check=True, capture_output=True,
        env={**_sanitized_git_environment(), "GIT_NO_REPLACE_OBJECTS": "1"},
    ).stdout


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
    _git(target, "add", "-A")
    _git(target, "commit", "-q", "-m", "the neutral conformance corpus")

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
