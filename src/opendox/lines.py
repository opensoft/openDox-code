"""openDox's OWN line rule and HEAD read: the generic slice of openxFactory's
`doc_health` that openXdox's modules use (plan 038 T072; the OpenSpec change
`realize-doc-health-direction-arc`, design.md § 3).

WHY IT IS HERE. openXdox-code's `completeness.py`, `round_trip.py` and
`generator.py` import `split_keepends` and `join_rows` from openxFactory's
`doc_health.lines` at load time, and the generator reads a checkout's HEAD
through `doc_health.corpus.RealGit`. Neither is governed: a line rule and one
git read belong to no domain. So openDox carries them, and moving openXdox off
`doc_health` for these names (T074) is an import change.

A RE-AUTHORING, NOT A RELOCATION. openxFactory's module stays where it is, and
so does every caller of it. Nothing here imports it, and this module is
written to its behaviour, not copied out of its package.

WHAT A LINE IS. Only the three real line endings end one: CR, LF and CRLF, and
CRLF is ONE ending. `str.splitlines()` also breaks on VT (`\\x0b`), FF
(`\\x0c`), `\\x1c` to `\\x1e`, NEL (`\\x85`), U+2028 and U+2029. A document
holding one of those would be read as more lines than it has, and a header
window counted that way covers fragments of the document rather than its
lines. So `join_rows(split_keepends(t)) == t` for every `t`, and no row ends
anywhere but at a real line ending.

THE HEAD READ. `head_sha(repo)` makes `RealGit.head_sha`'s read, argument for
argument: `git -C <repo> rev-parse HEAD`, bounded by 30 seconds. It answers
`None` where git cannot answer: not a repository, an unborn HEAD, no `git`, or
a timeout. openDox's `serve` has its own private reader of the same read
(`serve._CheckoutHead`). `tests/test_lines.py` holds the two to the same
answers while both exist (holder ruling, openxFactory#656 comment
6023517122).

IMPORT WEIGHT. The standard library only, and no other module of openDox, so
importing this module loads nothing else of the package.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import os
import re
import subprocess

__all__ = ["split_keepends", "join_rows", "head_sha"]

#: The three real line endings, CRLF FIRST. An alternation takes the first
#: branch that matches, so a CR branch ahead of CRLF would cut CRLF in two.
_EOL = re.compile(r"\r\n|\r|\n")

#: `RealGit`'s bound on a git read, in seconds. A git that does not answer in
#: time is no answer, never a hang.
_GIT_TIMEOUT_SECONDS = 30


def split_keepends(text: str) -> list[tuple[str, str]]:
    """`text` as `[(body, ending)]` rows, where `join_rows` of them IS `text`.

    An ending is CR, LF or CRLF, and the last row's ending is empty when the
    text does not end in one. A body never holds CR or LF. Empty text is no
    rows. NOT `str.splitlines(keepends=True)`, which also breaks on `\\x0b`,
    `\\x0c`, `\\x1c` to `\\x1e`, `\\x85`, U+2028 and U+2029."""
    rows: list[tuple[str, str]] = []
    at, size = 0, len(text)
    while at < size:
        match = _EOL.search(text, at)
        if match is None:
            rows.append((text[at:], ""))
            break
        rows.append((text[at:match.start()], match.group(0)))
        at = match.end()
    return rows


def join_rows(rows: list[tuple[str, str]]) -> str:
    """The text the rows came from: each body followed by its own ending."""
    return "".join(body + ending for body, ending in rows)


def head_sha(repo: str | os.PathLike[str]) -> str | None:
    """The commit `repo`'s HEAD names, or `None` where git cannot say.

    `RealGit.head_sha`'s read exactly: the same command, the same 30-second
    bound, and `None` on a timeout, on an error starting git, and on a
    non-zero exit. Any other error is a defect and propagates, as it does
    there."""
    try:
        proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              timeout=_GIT_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = proc.stdout if proc.returncode == 0 else None
    return out.strip() if out else None
