"""THE CONFIRMATION CAPABILITY that `land` requires (#1144 12.6a; plan 038
T012, decision N-11).

WHAT IT IS. `LandingPort.land(branch, *, confirmation)` takes a CAPABILITY, not a
value a caller builds: an opaque, single-use token bound to ONE branch and ONE
head sha. 12.6a's words: *"It is an opaque, single-use token that only two
issuers mint."* This module holds the token, the two issuers, and the one act
that spends a token (`redeem`).

THE TWO ISSUERS, and there is no third:

* `confirm_at_terminal(branch, head)`: the `land` verb's prompt. It asks at the
  CONTROLLING TERMINAL (`/dev/tty`, never stdin), shows the branch and its head,
  and mints only when the human types the branch's name there. It refuses when
  standard input is not a terminal and when there is no controlling terminal at
  all: 12.6a's "refuses when there is none". There is no bypass flag (N-11).
* `LandingNonces`: the loopback server's per-branch nonce (OQ-12-13). The
  `land-nonce` route calls `issue_nonce(branch, head)` and hands the nonce to
  the view; the view's confirm control posts it back, and the `land` route
  calls `confirm_nonce(branch, nonce)`, which mints. One live nonce per branch,
  spent by the first attempt to confirm with it.

WHO MAY CALL THEM. Only the two interactive layers, `INTERACTIVE_LAYERS`: the
CLI module that holds the `land` prompt and the server module that holds the
confirm route. A STATIC check (`tests/test_landing_guardrails.py::
test_only_the_interactive_layers_call_an_issuer`) reads every module of the
package and fails if any other one names an issuer, or names `_mint`, the one
function that builds a token. It also proves, inside this module, that `_mint`
is reached from exactly the two issuers. That is how "no other issuer exists" is
a test and not a sentence.

ITS LIMIT, STATED RATHER THAN HIDDEN (12.6a). An in-process boundary cannot stop
code the user runs on purpose: a test, or a script, can import this module and
call an issuer, exactly as it could type into the terminal. What it stops is
the PRODUCT's own paths (the fix loop, scheduling, automation): none of them
may name an issuer, so none of them can land without a human. Packs run out of
process (15.1b) and cannot reach this module at all.

HOW A TOKEN IS CHECKED. A token carries a random key and nothing a caller can
forge. The key is recorded in a process-wide registry when an issuer mints it,
and `redeem` removes it there, atomically, under a lock: so a token built any
other way (constructed directly, built with `object.__new__`, copied) has no
live key and is refused, and a token presented twice finds its key already
spent. The branch and head a token is bound to are the REGISTRY's record, not
the token's attributes, so editing a token's attributes changes nothing.

IMPORT WEIGHT. The standard library only.
"""

from __future__ import annotations

import io
import os
import re
import secrets
import sys
import threading
import weakref
from dataclasses import dataclass

from .session_git import shown

__all__ = [
    "Confirmation",
    "ConfirmationRefused",
    "INTERACTIVE_LAYERS",
    "ISSUERS",
    "ISSUER_NAMES",
    "ISSUER_TTY",
    "ISSUER_VIEW",
    "LandingNonces",
    "TERMINAL",
    "confirm_at_terminal",
    "redeem",
]

#: The two issuers' names, as a token reports which one minted it (data-model.md
#: § "Confirmation capability": `tty` or `view`).
ISSUER_TTY = "tty"
ISSUER_VIEW = "view"
ISSUERS: tuple[str, ...] = (ISSUER_TTY, ISSUER_VIEW)

#: The controlling terminal. Never stdin: a stdin can be a pipe a script fills.
TERMINAL = "/dev/tty"

#: The ONLY modules that may call an issuer, relative to the package's parent:
#: the CLI module holding the `land` prompt and the server module holding the
#: confirm route (T015, T016; contracts/cli-http-submit-land.md). The static
#: check holds the package to this list, and holds this list to its own copy.
INTERACTIVE_LAYERS: tuple[str, ...] = (
    "opendox/cli_branch_actions.py",
    "opendox/serve_branch_actions.py",
)

#: The names a module uses to reach an issuer. The static check looks for each
#: as an identifier, an attribute, an imported name and a string literal.
ISSUER_NAMES: tuple[str, ...] = (
    "confirm_at_terminal", "LandingNonces", "issue_nonce", "confirm_nonce",
)

#: The longest answer the prompt reads. A branch name is far shorter.
_ANSWER_LIMIT = 4096

#: A full object id: SHA-1 (40) or SHA-256 (64) hex. A token binds the exact
#: commit, never a name that could move.
_OBJECT_ID = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class ConfirmationRefused(Exception):
    """No human confirmed this landing, so nothing lands.

    `code` names the case for a caller that answers in a protocol (the routes):
    `no-terminal`, `stdin-not-a-terminal`, `answer-mismatch`, `no-nonce`,
    `nonce-mismatch`, `not-a-confirmation`, `constructed-directly`, `spent`,
    `another-branch`, `another-head`, `bad-binding`."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Grant:
    """What an issuer recorded for one token: the registry's truth about it."""

    branch: str
    head: str
    issuer: str


# The live keys, and the spent ones. Process-wide on purpose: a token is a
# capability within ONE process, and both of its issuers run in the process
# that also lands (the CLI's own; the server's own).
_LOCK = threading.Lock()
_LIVE: dict[str, _Grant] = {}
_SPENT: set[str] = set()


class Confirmation:
    """An opaque, single-use capability for ONE landing of ONE branch at ONE head.

    It cannot be built by a caller: constructing it raises, and a token made any
    other way has no live key, so `redeem` refuses it. It cannot be copied or
    pickled either, because a copy would be a second token for one human act.
    Its `branch`, `head` and `issuer` are for display; `redeem` checks the
    registry's record of them, never these attributes."""

    # `__weakref__`: the registry forgets a token's key when the token itself
    # is gone (`_forget`), so a long-running server keeps no record per
    # confirmation it ever minted.
    __slots__ = ("_branch", "_head", "_issuer", "_key", "__weakref__")

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise ConfirmationRefused(
            "a confirmation is a capability that only the `land` prompt at the "
            "controlling terminal and the view's confirm control mint (#1144 "
            "12.6a); it cannot be constructed directly", code="constructed-directly")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("a confirmation is immutable")

    def __copy__(self) -> "Confirmation":
        raise TypeError("a confirmation is single-use and cannot be copied")

    def __deepcopy__(self, memo: object) -> "Confirmation":
        raise TypeError("a confirmation is single-use and cannot be copied")

    def __reduce_ex__(self, protocol: object) -> object:
        raise TypeError("a confirmation is single-use and cannot be pickled")

    def _field(self, name: str) -> str:
        try:
            return str(object.__getattribute__(self, name))
        except AttributeError:
            return ""

    @property
    def branch(self) -> str:
        return self._field("_branch")

    @property
    def head(self) -> str:
        return self._field("_head")

    @property
    def issuer(self) -> str:
        return self._field("_issuer")

    @property
    def spent(self) -> bool:
        """Whether this token can no longer be redeemed (spent, or never minted)."""
        key = self._field("_key")
        with _LOCK:
            return key not in _LIVE

    def __repr__(self) -> str:
        # The key never appears: a token printed in a log must not be one a
        # reader of the log could rebuild.
        return (f"<Confirmation {self.issuer or '?'} for {self.branch!r} at "
                f"{self.head[:12] or '?'}>")


def _require_binding(branch: str, head: str) -> None:
    # Not EMPTY, and nothing more: git decides what a branch name is, and a
    # legal one may end in a no-break space (`sess-1\u00a0`), which a strip
    # would have refused (Copilot's sixth review of openDox-code#90).
    if not isinstance(branch, str) or not branch:
        raise ConfirmationRefused(
            f"a confirmation is bound to a branch by name, and {branch!r} is not "
            "one", code="bad-binding")
    if not isinstance(head, str) or not _OBJECT_ID.match(head):
        raise ConfirmationRefused(
            f"a confirmation is bound to the branch's head as a full commit id, "
            f"and {head!r} is not one", code="bad-binding")


def _mint(branch: str, head: str, issuer: str) -> Confirmation:
    """Build ONE token and record its key. Reached from the two issuers only:
    the static check proves it, and proves nothing outside this module names it."""
    _require_binding(branch, head)
    token = object.__new__(Confirmation)
    key = secrets.token_hex(32)
    object.__setattr__(token, "_branch", branch)
    object.__setattr__(token, "_head", head)
    object.__setattr__(token, "_issuer", issuer)
    object.__setattr__(token, "_key", key)
    with _LOCK:
        _LIVE[key] = _Grant(branch=branch, head=head, issuer=issuer)
    weakref.finalize(token, _forget, key)
    return token


def _forget(key: str) -> None:
    """Drop a key once its token is gone (Copilot's third review of
    openDox-code#90). Safe: the key lives only in that token, which cannot be
    copied, pickled or rebuilt, so once it is collected the key can never be
    presented again. A token still held keeps its record, so a spent one is
    still refused as spent. No lock: a collection can run this inside a
    section that holds `_LOCK`, and one `pop` and one `discard` are each
    atomic."""
    _LIVE.pop(key, None)
    _SPENT.discard(key)


def redeem(confirmation: object, *, branch: str, head: str) -> str:
    """SPEND `confirmation` for landing `branch` at `head`; return its issuer.

    Refused, with the case named, when it is not a token at all (a flag, a
    string, a boolean: none of those is a human act), when no issuer minted it,
    when it was already presented, and when it was minted for another branch or
    another head. A token found in the registry is spent by this call whatever
    follows: a confirmation for a head the branch has since left is stale for
    good, and the human confirms the new head."""
    if not isinstance(confirmation, Confirmation):
        raise ConfirmationRefused(
            f"`land` takes a confirmation minted by a human act, and got "
            f"{type(confirmation).__name__}: no flag, setting or value stands in "
            "for one (#1144 12.6a). Run `land` at a terminal and type the branch "
            "name, or confirm it in the view", code="not-a-confirmation")
    try:
        key = object.__getattribute__(confirmation, "_key")
    except AttributeError:
        key = None
    with _LOCK:
        grant = _LIVE.pop(key, None) if isinstance(key, str) else None
        if grant is None:
            if isinstance(key, str) and key in _SPENT:
                raise ConfirmationRefused(
                    f"this confirmation for {confirmation.branch!r} was already "
                    "presented once, and a confirmation is single-use: confirm "
                    "again to land again", code="spent")
            raise ConfirmationRefused(
                "this confirmation was not minted by either issuer (the `land` "
                "prompt at the controlling terminal, or the view's confirm "
                "control), so it is refused: a confirmation cannot be "
                "constructed directly", code="constructed-directly")
        _SPENT.add(key)
    if grant.branch != branch:
        raise ConfirmationRefused(
            f"this confirmation was minted for branch {grant.branch!r}, not "
            f"{branch!r}: a confirmation lands only the branch it names",
            code="another-branch")
    if grant.head != head:
        raise ConfirmationRefused(
            f"this confirmation was minted for {branch!r} at {grant.head[:12]}, and "
            f"the branch is at {head[:12]} now: it moved after the human "
            "confirmed it, so confirm the new head", code="another-head")
    return grant.issuer


# --------------------------------------------------------------------------
# the first issuer: the `land` prompt at the controlling terminal
# --------------------------------------------------------------------------

def _stdin_is_a_terminal() -> bool:
    try:
        return os.isatty(sys.stdin.fileno())
    except (AttributeError, ValueError, OSError):
        return False


def _open_controlling_terminal() -> io.TextIOWrapper:
    """The controlling terminal, read and written as `getpass` does: one
    descriptor, `O_NOCTTY` so opening it never acquires a terminal."""
    fd = os.open(TERMINAL, os.O_RDWR | os.O_NOCTTY)
    try:
        raw = io.FileIO(fd, "w+")
    except BaseException:
        os.close(fd)
        raise
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace",
                            write_through=True)


def confirm_at_terminal(branch: str, head: str) -> Confirmation:
    """THE FIRST ISSUER: ask at the controlling terminal; mint on the typed name.

    Shows the branch and its head, reads ONE line from `/dev/tty`, and mints a
    token bound to that branch and head only when the line is exactly the
    branch's name. Refuses, minting nothing, when standard input is not a
    terminal (12.6a: "a `land` whose stdin is not a terminal" is refused), when
    there is no controlling terminal, and on any other answer."""
    _require_binding(branch, head)
    if not _stdin_is_a_terminal():
        raise ConfirmationRefused(
            "`land` confirms at the controlling terminal, and standard input is "
            "not a terminal: a landing is a human act, so a piped or scripted "
            "`land` is refused and there is no flag that skips the question "
            "(#1144 12.6a; plan 038 N-11)", code="stdin-not-a-terminal")
    try:
        terminal = _open_controlling_terminal()
    except OSError as missing:
        raise ConfirmationRefused(
            f"`land` confirms at the controlling terminal, and there is none "
            f"({TERMINAL}: {missing.strerror or missing}): it refuses rather than "
            "land unconfirmed (#1144 12.6a)", code="no-terminal") from None
    with terminal:
        # The name is SHOWN escaped where it holds a character a terminal acts
        # on (a bidi override reorders what the human reads); the answer must
        # still be the exact name (Copilot's fourth review of openDox-code#90).
        terminal.write(
            f"Land branch {shown(branch)} at {head} onto main with a merge commit?\n"
            f"Type the branch name to confirm: ")
        terminal.flush()
        answer = terminal.readline(_ANSWER_LIMIT)
    if answer.rstrip("\r\n") != branch:
        raise ConfirmationRefused(
            f"the answer at the terminal was not the branch name {branch!r}, so "
            "nothing was confirmed and nothing lands", code="answer-mismatch")
    return _mint(branch, head, ISSUER_TTY)


# --------------------------------------------------------------------------
# the second issuer: the loopback server's per-branch nonce
# --------------------------------------------------------------------------

class LandingNonces:
    """THE SECOND ISSUER: the server's per-branch nonce for the confirm control.

    One instance per server. `issue_nonce(branch, head)` answers the `land-nonce`
    route and replaces any nonce already live for that branch; the view shows the
    branch and head it is bound to. `confirm_nonce(branch, nonce)` answers the
    `land` route: the first attempt for a branch spends its nonce, matching or
    not, and only a matching one mints."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, tuple[str, str]] = {}

    def issue_nonce(self, branch: str, head: str) -> str:
        _require_binding(branch, head)
        nonce = secrets.token_urlsafe(32)
        with self._lock:
            self._live[branch] = (nonce, head)
        return nonce

    def confirm_nonce(self, branch: str, nonce: str) -> Confirmation:
        with self._lock:
            entry = self._live.pop(branch, None) if isinstance(branch, str) else None
        if entry is None:
            raise ConfirmationRefused(
                f"no landing nonce is live for {branch!r}: the confirm control "
                "fetches one for the branch it shows, and each is single-use",
                code="no-nonce")
        live, head = entry
        # An issued nonce is ASCII, so anything else is refused before it is
        # encoded: a lone surrogate (`"\\ud800"` in a JSON body) would otherwise
        # raise `UnicodeEncodeError` here (Copilot review of openDox-code#90).
        if not isinstance(nonce, str) or not nonce.isascii() or \
                not secrets.compare_digest(live.encode(), nonce.encode()):
            raise ConfirmationRefused(
                f"the nonce does not match the one issued for {branch!r}; it is "
                "spent now, so fetch a new one and confirm again",
                code="nonce-mismatch")
        return _mint(branch, head, ISSUER_VIEW)
