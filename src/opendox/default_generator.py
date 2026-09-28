"""openDox's OWN snapshot generator, declared as the generator seam's default.

WHY THIS FILE EXISTS. openDox's entry points register openDox's own generator
where no host has contributed one (R1Q10 (a), `openxFactory#656` comment
`5850003126`, in R1Q3 (a)'s pattern). They do so beside the default profile and
the default home corpus, which they register the same way. This module is what
they register: `GENERATOR`, a `generator_seam.SnapshotGenerator` that writes
the neutral snapshot contract, `generator_seam.NEUTRAL_SNAPSHOT_KIND` (plan
034's T053; R1Q11 (a)), and takes no input beyond the operation's own four.

WHAT IT GENERATES. `generate()` reads the home corpus through the home-corpus
seam, `corpus_adapter.home()`, and projects it with openDox's own small
neutral projection, `opendox.neutral_projection` (plan 034's T054; #1144's
5.1-5.3). Standalone, the home corpus is the default the entry points register,
`local_git_adapter.WorkingTreeCorpus`, which is how the projection is bound to
`LocalGitCorpus` (5.2). With no home corpus registered, the seam's own refusal
names the call that is missing, and nothing is generated.

ITS TWO ANCHORS. `source_revision` is recorded as the caller pins it, and
otherwise it is the revision the corpus resolved at, its git HEAD. The
projection refuses where there is neither. `generated_at` is recorded as the
caller gives it, and otherwise it is the committer date of that revision,
which `git` reads from the checkout (`git show -s --format=%cI`, the stamp the
generate verbs have always used). It is looked up only for a revision spelled
as a hexadecimal object id, so a revision is never handed to `git` where it
could read as an option. It is left out where the lookup fails. Nothing reads
the clock, so the same tree at the same anchors answers the same snapshot.

A PIN LABELS THE SNAPSHOT; IT DOES NOT CHOOSE THE BYTES. The content is the
working tree's, on Brett's T022 ruling ("Working tree (Recommended)"), which the
holder confirmed for T054. A supplied `source_revision` is recorded as the
anchor the caller asserts, exactly as openXdox's governed generator records one
and scans the tree it is handed (its sealed-artifact lane pins a revision for a
tree that is not a checkout at all). So the pin never reaches the `CorpusRef`,
and a pin that names no commit here is still recorded rather than refused. A
caller that wants the tree at an older commit checks that commit out first.

WHAT IT REPORTS. The projection's notices go to standard error, one line each,
`notice: <document>: <what was read otherwise>`. A `stage:` value outside the
six role keys is one (R1Q13 (a)): the line names the document, the value and
the six keys, and the snapshot reads that document as a source.

THE VERBS REACH IT THROUGH THE SEAM. Since plan 034's T055 the generate verbs
and the local regenerate generate through `generator_seam.generate()`, so a
process where no host registered a generator of its own generates with this
one. A library caller reaches it the same way.

HOW IT IS REGISTERED: by the entry points, and never at import (R1Q3 (a)'s
pattern). `cli.build_parser()`, `cli.main()`, `serve.build_server()` and
`serve.main()` call `generator_seam.register_default(GENERATOR)`, which
registers it only where nothing is registered. Importing this module registers
nothing.

IMPORT WEIGHT. `opendox.generator_seam`, `opendox.corpus_adapter`,
`opendox.neutral_projection` (which adds `opendox.display_profile`,
`opendox.path_slug` and `opendox.runtime.local_git_adapter`), and the standard
library. So this module imports with no extra installed and no sibling
present.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from opendox import corpus_adapter, generator_seam, neutral_projection
from opendox.runtime.local_git_adapter import GitCommandFailed, GitRunner

__all__ = ["GENERATOR", "generate"]

#: A revision spelled as a hexadecimal object id, abbreviated or whole. Only
#: such a revision is handed to `git` to read its date.
_OBJECT_ID = re.compile(r"[0-9a-fA-F]{4,64}")

#: `git show -s --format=%cI`'s shape: a strict ISO 8601 date-time with an
#: explicit offset, as the neutral schema's `generated-at-is-rfc3339` rule
#: admits it.
_COMMIT_DATE = re.compile(
    r"(?!0000)[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-5][0-9]"
    r"(?:Z|[+-][0-9]{2}:[0-9]{2})")


def _commit_date(location: str, revision: str) -> str | None:
    """The committer date of `revision` in the checkout at `location`, or
    None where `git` cannot answer one."""
    if not _OBJECT_ID.fullmatch(revision):
        return None
    try:
        stamp = GitRunner(Path(location)).out(
            "show", "-s", "--format=%cI", f"{revision}^{{commit}}", "--")
    except (GitCommandFailed, OSError):
        return None
    text = stamp.decode("utf-8", "replace").strip()
    return text if _COMMIT_DATE.fullmatch(text) else None


def generate(repo_root: Path, repository: str, *,
             source_revision: str | None = None,
             generated_at: str | None = None) -> dict[str, Any]:
    """The operation the seam hands over, for openDox's own generator: the
    neutral snapshot of the home corpus at `repo_root`."""
    adapter, ref = corpus_adapter.home()(str(repo_root))
    corpus = adapter.resolve(ref)
    anchor = source_revision if source_revision is not None else corpus.revision
    if generated_at is None and anchor is not None:
        generated_at = _commit_date(corpus.location, anchor)
    projection = neutral_projection.project(
        adapter, corpus, repository,
        source_revision=anchor, generated_at=generated_at)
    for notice in projection.notices:
        print(f"notice: {notice}", file=sys.stderr)
    return projection.snapshot


#: openDox's OWN generator, as the entry points register it where no host has.
GENERATOR = generator_seam.SnapshotGenerator(
    contract=generator_seam.NEUTRAL_SNAPSHOT_KIND, generate=generate)
