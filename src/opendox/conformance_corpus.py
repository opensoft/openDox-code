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

import shutil
import subprocess
from pathlib import Path

from .runtime.local_git_adapter import LocalGitCorpus

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


def _git(repo: Path, *args: str) -> None:
    """Run one git command in `repo`, with an identity that cannot be absent.

    The identity is supplied per-command rather than written into the new
    repository's config: a transposition is a throwaway and must not depend on
    the machine's global git identity being set, which on a CI runner it is
    not.
    """
    subprocess.run(
        ("git", "-c", "user.name=conformance", "-c",
         "user.email=conformance@openDox.invalid", *args),
        cwd=repo, check=True, capture_output=True)


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
