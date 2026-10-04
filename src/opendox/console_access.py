"""How the console token reaches the page on a STANDALONE plane (plan 034 T104).

THE RULING. openxFactory#656 comment `5963851934` (Brett, 2026-10-03, "Token
via the opened URL (Recommended)"): adversarial review 2's M5 found that a
standalone openDox served its per-serve console token from `/capabilities` to
any loopback caller, other OS users on the same machine included, and nothing
checks which local user connects. The token lets a page edit documents and run
chat turns that spend the operator's model credential. Release 1 changes the
DELIVERY, as Jupyter does, and nothing else:

  * the server stops handing the token out from `/capabilities` on a
    standalone plane (`delivery_for`, read by `serve.build_server`);
  * the entry point writes a PRIVATE COPY, mode 0600, in openDox's state
    directory (`write_private_copy`), and the page is opened through it, so the
    token travels only in the opened URL's FRAGMENT (`opened_url`). A fragment
    is never sent to a server, so it never reaches a request line, a server
    log or a `Referer`;
  * the page reads it from `location.hash`, keeps it in `sessionStorage`, and
    strips it from the address bar (`web/views/notebook.js`);
  * every route that requires the token still requires it.

WHO IS "STANDALONE". A plane built from openDox's OWN default profile
(`opendox.default_profile`), which an entry point registers where no host has.
A HOST's plane, openxFactory's, keeps the `/capabilities` delivery its page and
its suites read today: the ruling changes the standalone plane, and the
governed one is unchanged by it.

WHY THE BROWSER IS GIVEN A FILE AND NOT THE URL. `webbrowser.open(url)` runs
`xdg-open url` or the browser with the URL on its command line, and a command
line is readable by every user of the machine (`/proc/<pid>/cmdline`), for as
long as that process lives. So the URL that carries the token is written into
the private copy, an HTML page that forwards to it, and the browser is handed
the copy's `file://` path. That is Jupyter's own redirect file, and for the
same reason. The start prints the copy's PATH, never the token, with or
without `--no-open`, and opening that file again is how a user re-opens the
page while the server runs. The copy is removed when the server stops. Beside
the path, one line with no token tells a user whose browser cannot open that
file (a snap or Flatpak browser, a Windows browser under WSL) to move the
state directory (`UNOPENABLE_HINT`, RULED as an accepted limit).

THE COPY IS CHECKED THE WAY openDox-code#69's BUNDLE CHECKS ITS TREE
(`opendox.runtime.bundle`: `refuse_an_unsafe_tree`, `_make_private_directories`,
`write_authentication`). The rules are copied here, not imported, because they
are that module's private helpers and its refusal names a socket:

  * the state directory and `console/` must be real directories, this user's,
    writable by no one else, and `console/` exactly 0700; every directory
    above them must be this user's or root's, and one that others can write
    must be sticky; every symbolic link on the configured path must be this
    user's or root's;
  * a missing directory is made relative to its parent's DESCRIPTOR, born
    0700, and opened without following a link before anything is made under
    it;
  * the file is created exclusively, without following a link, set to exactly
    0600 by its descriptor, and renamed into place. A name already at the
    target that is not this user's own regular file of mode 0600 with one
    link (a link, a directory, a FIFO, a file another user owns, a file with
    a second hard link, a loosened file) is REFUSED, never followed or
    replaced;
  * a READ asks all of it again of what exists, and of the file by its
    descriptor, opened without blocking: a regular file, this user's,
    exactly 0600, one link;
  * the state directory and every root the plane serves may not overlap in
    either direction, before any write, as T100's served-repository boundary
    refuses its own (holder's rulings on openxFactory#1220's review, Copilot
    `r4171166321`, and on batch N's, `r4174345203`), judged by name AND by
    the directories' own identities, so a second spelling of one directory
    (a case-insensitive filesystem's) is the same directory;
  * EVERY standalone plane keeps that boundary and never serves a copy, the
    planes that minted no token included (`publish`): a sibling plane of the
    same user shares the state directory, and serves what another plane
    wrote there unless it refuses it too;
  * a publication sweeps the copies their servers left when they died
    (`_sweep_stale_copies`): a copy whose reservation is free is no running
    console's;
  * every refusal names its path, an operating-system one included, so an
    entry point refuses its start by name; and the copy is removed when the
    server stops, by Ctrl-C, SIGTERM or SIGHUP, or when its start is refused
    after it was written. A stop is read as Ctrl-C from before the copy is
    written to after it is removed, and held while a copy is being written or
    removed (`deferred_termination`); the first stop is the only one raised
    (`_terminate_as_interrupt`), and every writer and remover of `console/`
    takes the directory's lock (`_lock`);
  * a platform without the POSIX primitives these rules rest on is named and
    refused before anything is written or read (`unsupported_platform`), as
    the bundle refuses its own.

#1144 12.4a, as T007 batch N amends it (openxFactory#1222), is the normative
text this module realizes.

A CREATED FILE, with no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import contextlib
import dataclasses
import html
import json
import os
import re
import signal
import stat
import sys
import urllib.parse
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from opendox.runtime import config as runtime_config

try:                                    # POSIX; the copy's rules are POSIX's
    import fcntl
except ImportError:                     # pragma: no cover
    fcntl = None

__all__ = [
    "CONSOLE_DIRNAME", "ConsoleAccessRefused", "ConsoleTerminated",
    "DELIVERY_CAPABILITIES",
    "DELIVERY_OPENED_URL", "FRAGMENT_KEY", "PrivateCopy", "RECORD_ELEMENT_ID",
    "RECORD_KIND", "UNOPENABLE_HINT", "deferred_termination", "delivery_for",
    "guard_private_roots",
    "is_private_file", "needs_copy", "opens_a_private_file",
    "opened_url", "private_copy_path", "publish", "read_private_copy",
    "remove_private_copy", "terminate_as_interrupt", "unsupported_platform",
    "within_private_roots", "write_private_copy",
]

#: The token rides on `/capabilities`, as a host's plane has always read it.
DELIVERY_CAPABILITIES = "capabilities"
#: The token rides only in the opened URL's fragment (the standalone plane).
DELIVERY_OPENED_URL = "opened-url"

#: The private copies' directory, under the state directory.
CONSOLE_DIRNAME = "console"
#: The fragment's one key: `…/index.html#console_token=<token>`. The page reads
#: the same key (`web/views/notebook.js`, `CONSOLE_TOKEN_FRAGMENT_KEY`).
FRAGMENT_KEY = "console_token"
#: The machine-readable record inside the copy, for a harness or a script.
RECORD_KIND = "opendox-console-access"
RECORD_SCHEMA_VERSION = 1
RECORD_ELEMENT_ID = "opendox-console"
#: The one mode a private copy may have.
PRIVATE_MODE = 0o600
#: The one mode the copies' directory, `console/`, may have (#1144 12.4a: the
#: copy is mode 0600 "in a directory of mode 0700").
CONSOLE_DIR_MODE = 0o700
#: The one line a start prints beside the copy's path, and it carries no token.
#: Some browsers cannot open the copy where it is: a snap or Flatpak browser
#: is kept out of a hidden directory such as `~/.local/state`, and a Windows
#: browser under WSL may not open a Linux path at all. The token is never
#: printed, so this line is the way past it (RULED by Brett on the adversarial
#: review of openDox-code#84, B3, 2026-10-04: "Hint line, accepted limit").
UNOPENABLE_HINT = (
    "if your browser cannot open this file (a snap or Flatpak browser, or a "
    "Windows browser under WSL), set "
    f"{runtime_config.PREFIX}STATE_DIR to a folder that is not hidden and "
    "start again")
#: A copy is a few hundred bytes; a read stops well past that.
_READ_LIMIT = 64 * 1024
#: `secrets.token_urlsafe` spells a token in these characters only, so a token
#: needs no escaping in a fragment and a value outside them is not one.
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{16,512}")
_RECORD_PATTERN = re.compile(
    r'<script type="application/json" id="' + RECORD_ELEMENT_ID
    + r'">(?P<record>[^<]*)</script>')
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
#: The names a publication may sweep when their servers are gone
#: (`_sweep_stale_copies`): a copy, a writer's temporary file, and a remover's
#: taken name. Each holds a token, and nothing else is ever touched.
_SWEEPABLE = re.compile(r"[0-9]+\.html|\.[0-9]+\.html\.opendox-[0-9]+"
                        r"|\.[0-9]+\.html\.removing-[0-9]+-[0-9a-f]{12}")

#: Whether every call the copy's rules make relative to a directory's
#: descriptor takes one here, read ONCE at import, as `opendox.runtime.bundle`
#: reads its own: a case that stands a wrapper in for one of them must not
#: read as another platform.
_DIR_FD_CALLS = all(call in os.supports_dir_fd for call in (
    os.open, os.mkdir, os.stat, os.rename, os.unlink, os.link))


def unsupported_platform() -> str | None:
    """Why this platform cannot keep a console token's private copy, or `None`.

    The copy is a POSIX design, as openDox-code#69's bundle is, and every one
    of its rules rests on a POSIX primitive: its directories and the file are
    judged by owner (`os.getuid`), made and opened without following a link
    (`O_DIRECTORY`, `O_NOFOLLOW`, calls relative to a directory's
    descriptor), set to 0600 by descriptor (`fchmod`), and read without
    blocking (`O_NONBLOCK`). Without them (Windows) the standalone start
    ended in an `AttributeError` traceback (adversarial review of
    openDox-code#84, B2). So the writer and the reader name the gap first,
    and refuse, as `opendox.runtime.bundle.unsupported_platform` names its
    own (holder's ruling)."""
    missing = [name for name, present in (
        ("os.getuid", hasattr(os, "getuid")),
        ("os.O_DIRECTORY", hasattr(os, "O_DIRECTORY")),
        ("os.O_NOFOLLOW", hasattr(os, "O_NOFOLLOW")),
        ("os.O_NONBLOCK", hasattr(os, "O_NONBLOCK")),
        ("os.fchmod", hasattr(os, "fchmod")),
        ("calls relative to a directory's descriptor", _DIR_FD_CALLS),
    ) if not present]
    if not missing:
        return None
    return (f"the console token's private copy needs a POSIX platform, and "
            f"this one ({sys.platform}) lacks {', '.join(missing)}: the copy "
            "and its directories are judged by owner and made without "
            "following a link, so a standalone console cannot hand its token "
            "to this user alone here, and is not started")


def _refuse_an_unsupported_platform() -> None:
    reason = unsupported_platform()
    if reason is not None:
        raise ConsoleAccessRefused(reason)


class ConsoleAccessRefused(Exception):
    """The private copy cannot be written or read safely, and why."""


@dataclasses.dataclass(frozen=True)
class PrivateCopy:
    """One written copy: where it is, what it opens, and which file it is."""

    path: Path
    page_url: str
    #: The URL with the token in its fragment. Kept out of the copy's `repr`,
    #: so a log line, a traceback or a failed assertion that prints a copy
    #: never prints its token.
    opened_url: str = dataclasses.field(repr=False)
    #: `(st_dev, st_ino)` of the file this process wrote, so a removal at
    #: shutdown removes that file and never one written after it.
    identity: tuple[int, int]
    #: The open descriptor that RESERVES the copy for its server's life
    #: (`_Reservation`), or None where no reservation could be taken.
    reservation: "_Reservation | None" = dataclasses.field(
        default=None, compare=False, repr=False)

    @property
    def file_url(self) -> str:
        """The `file://` URL a browser is given: a path, never the token."""
        return self.path.as_uri()


class _Reservation:
    """The open descriptor that holds a copy's lock while its server runs.

    A COPY IS RESERVED FOR ITS SERVER'S LIFE (Copilot at openDox-code#84,
    r4178133814). The copy's name is per PORT, and two consoles can share a
    port number and a state directory, one on 127.0.0.1 and one on ::1. So
    the writer takes an exclusive `flock` on the file it wrote, on its own
    descriptor, and keeps it until the copy is removed. A later publication
    on that port finds the lock held, and refuses rather than replace a
    RUNNING console's copy. A copy whose server died holds no lock, since the
    kernel drops it with the process, and is replaced as a stale one.
    `close` is idempotent, and so is dropping the reservation."""

    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    def close(self) -> None:
        fd, self._fd = self._fd, None
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)

    def __del__(self) -> None:
        self.close()


def delivery_for(profile: Any) -> str:
    """Which delivery a plane built from `profile` uses.

    openDox's OWN default profile is the standalone plane: the token travels in
    the opened URL. Any other profile is a host's, and keeps `/capabilities`."""
    from opendox import default_profile

    return (DELIVERY_OPENED_URL if profile is default_profile
            else DELIVERY_CAPABILITIES)


def _refuse_page_url(page_url: str) -> None:
    parts = urllib.parse.urlsplit(page_url)
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK_HOSTS:
        raise ConsoleAccessRefused(
            f"the console page {page_url!r} is not a loopback http URL, and a "
            "console token is only ever opened on this machine's own plane")
    if parts.query or parts.fragment or "#" in page_url or "?" in page_url:
        raise ConsoleAccessRefused(
            f"the console page {page_url!r} already carries a query or a "
            "fragment, so the token's fragment cannot be the only one")


def _refuse_token(token: Any) -> str:
    if not isinstance(token, str) or not _TOKEN_SHAPE.fullmatch(token):
        raise ConsoleAccessRefused("the console token is not a token this "
                                   "server mints")
    return token


def opened_url(page_url: str, token: str) -> str:
    """`page_url` with the token in its FRAGMENT and never in its query.

    A fragment stays in the browser: it is not part of the request line, so no
    server log and no `Referer` carries it."""
    _refuse_page_url(page_url)
    _refuse_token(token)
    return page_url + "#" + urllib.parse.urlencode({FRAGMENT_KEY: token})


def private_copy_path(state_dir: Path | str, port: int) -> Path:
    """Where the copy for the plane on `port` lives, under `state_dir`."""
    return Path(state_dir) / CONSOLE_DIRNAME / f"{int(port)}.html"


# --------------------------- the tree's rules (bundle.py's, copied) ---------------------------

def _unsafe_because(info: os.stat_result, *, uid: int, own: bool) -> str | None:
    """Why one directory on the copy's path is unsafe, or `None`.

    `opendox.runtime.bundle._unsafe_because`, rule for rule."""
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        return "is a symbolic link"
    if not stat.S_ISDIR(mode):
        return "is not a directory"
    if own:
        if info.st_uid != uid:
            return f"is owned by uid {info.st_uid}, not by this user"
        if mode & 0o022:
            return (f"is writable by {'every user' if mode & 0o002 else 'its group'}"
                    f" (mode {stat.S_IMODE(mode):o})")
        return None
    if info.st_uid not in (uid, 0):
        return f"is owned by uid {info.st_uid}, neither this user nor root"
    if mode & 0o022 and not mode & stat.S_ISVTX:
        return (f"is writable by {'every user' if mode & 0o002 else 'its group'}"
                f" and is not sticky (mode {stat.S_IMODE(mode):o})")
    return None


def _console_dir_unsafe_because(info: os.stat_result, *, uid: int) -> str | None:
    """Why the copies' own directory is unsafe, or `None`: the rules for
    every directory this user owns on the path, and exactly mode 0700 (#1144
    12.4a). A `console/` loosened after it was made is refused by name, as a
    loosened copy is, even where no one else can write it."""
    reason = _unsafe_because(info, uid=uid, own=True)
    # The PERMISSION bits only: a directory made under a setgid parent
    # inherits the setgid bit, which grants no one access.
    permissions = stat.S_IMODE(info.st_mode) & 0o777
    if reason is None and permissions != CONSOLE_DIR_MODE:
        reason = f"has mode {permissions:o}, not {CONSOLE_DIR_MODE:o}"
    return reason


def _lock(directory: int) -> None:
    """Hold the console directory's lock on its descriptor until it closes.

    PUBLICATION AND REMOVAL ARE SERIALIZED (Copilot at openDox-code#84,
    r4175213842). The copy's name is per PORT, and two serves can share one
    (127.0.0.1 and ::1), so one serve's removal can find another's copy at
    the name and must put it back. Where that takes a rename, a check that
    the name is free and the rename are two steps, and a third copy published
    between them would be overwritten by an older one. Every writer and
    remover of `console/` takes this exclusive lock, an advisory `flock` the
    kernel drops when the descriptor closes or the process dies. Where the
    filesystem keeps no such locks, nothing is held, as before."""
    if fcntl is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(directory, fcntl.LOCK_EX)


def _unsafe(path: Path, reason: str) -> ConsoleAccessRefused:
    return ConsoleAccessRefused(
        f"{path} {reason}, so another user could replace or read the console "
        "token's private copy. Use a state directory only this user can change "
        f"({runtime_config.PREFIX}STATE_DIR)")


#: How many symbolic links one walk of the state directory may follow, the
#: kernel's own `MAXSYMLINKS` on Linux.
_MAX_LINKS = 40


def _walked(configured: Path | str) -> Path:
    """The state directory, resolved ONCE, as the kernel walks it, with every
    directory it passes through and every symbolic link it follows judged on
    the way (Copilot at openDox-code#84, r4174785933).

    The tree rules below judge the configured path's own components and the
    directories above the RESOLVED path. A directory reached only through a
    link's target (`alias -> shared/hop`, `hop -> private`) is neither, so a
    `shared` that others could write went unjudged, and another user could
    re-point `hop` between the checks and the write, which walked the
    configured path again. So every directory passed through is judged by
    the rule for the directories above the state directory (this user's or
    root's, and sticky if others can write it), every link followed by the
    rule for a link (this user's or root's), and the caller works on the
    path returned, never on the configured one again. Nothing on that path
    can then be replaced by another user. A missing tail is appended as
    named, to be made by descriptor under the deepest directory that
    exists."""
    uid = os.getuid()
    configured = Path(configured)
    if not configured.is_absolute() or ".." in configured.parts:
        raise ConsoleAccessRefused(
            f"the state directory {str(configured)!r} is not an absolute path "
            "without `..`, so the copy's path is not the one the kernel walks")
    pending = list(reversed(configured.parts[1:]))
    current = Path(configured.anchor)
    links = 0
    while pending:
        name = pending.pop()
        if name in ("", "."):
            continue
        if name == "..":                    # only ever from a link's target
            current = current.parent
            continue
        candidate = current / name
        try:
            info = os.lstat(candidate)
        except FileNotFoundError:
            rest = [name, *reversed(pending)]
            if ".." in rest:
                raise ConsoleAccessRefused(
                    f"{candidate} does not exist, and the state directory "
                    f"{configured} would climb out of it with `..`") from None
            return current.joinpath(*rest)
        if stat.S_ISLNK(info.st_mode):
            if info.st_uid not in (uid, 0):
                raise _unsafe(candidate, f"is a symbolic link owned by uid "
                              f"{info.st_uid}, neither this user nor root, who "
                              "could point it elsewhere")
            links += 1
            if links > _MAX_LINKS:
                raise ConsoleAccessRefused(
                    f"the state directory {configured} passes through more "
                    f"than {_MAX_LINKS} symbolic links")
            target = Path(os.readlink(candidate))
            if target.is_absolute():
                current = Path(target.anchor)
                pending.extend(reversed(target.parts[1:]))
            else:
                pending.extend(reversed(target.parts))
            continue
        reason = _unsafe_because(info, uid=uid, own=False)
        if reason is not None:
            raise _unsafe(candidate, reason)
        current = candidate
    return current


def _refuse_an_unsafe_tree(state_dir: Path, *, existing_only: bool) -> None:
    """The copy's whole path is this user's to change, or it is refused.

    `opendox.runtime.bundle.refuse_an_unsafe_tree`'s three rules, over the
    state directory and `console/` instead of the socket's tree."""
    uid = os.getuid()
    configured = Path(state_dir)
    if not configured.is_absolute() or ".." in configured.parts:
        raise ConsoleAccessRefused(
            f"the state directory {str(configured)!r} is not an absolute path "
            "without `..`, so the copy's path is not the one the kernel walks")

    def present(path: Path) -> bool:
        return not existing_only or os.path.lexists(path)

    for component in (configured, *configured.parents):
        if not present(component):
            continue
        info = os.lstat(component)
        if stat.S_ISLNK(info.st_mode) and info.st_uid not in (uid, 0):
            raise _unsafe(component, f"is a symbolic link owned by uid "
                          f"{info.st_uid}, neither this user nor root, who "
                          "could point it elsewhere")
    state = configured.resolve()
    tree = [state, state / CONSOLE_DIRNAME]
    checks = [(path, True) for path in tree] + [
        (path, False) for path in dict.fromkeys(
            [*state.parents, *configured.parents])]
    for directory, mine in checks:
        if not present(directory):
            continue
        info = os.lstat(directory) if mine else os.stat(directory)
        reason = (_console_dir_unsafe_because(info, uid=uid)
                  if directory == tree[1]
                  else _unsafe_because(info, uid=uid, own=mine))
        if reason is not None:
            raise _unsafe(directory, reason)


def _open_private_directory(leaf: Path, *, state: Path) -> int:
    """A descriptor on `leaf`, every missing directory on the way born 0700.

    `opendox.runtime.bundle._make_private_directories`, which it copies: each
    missing component is made RELATIVE TO ITS PARENT'S DESCRIPTOR, under a
    umask of 077, and opened with `O_NOFOLLOW` before anything is made beneath
    it. The directory it starts from is judged by its descriptor first. The
    caller owns the descriptor returned."""
    uid = os.getuid()
    missing: list[str] = []
    base = leaf
    while not os.path.lexists(base):
        missing.append(base.name)
        base = base.parent
    flags = os.O_RDONLY | os.O_DIRECTORY
    if not missing:
        # It exists: open it without following a link, and judge what opened.
        try:
            descriptor = os.open(leaf, flags | os.O_NOFOLLOW)
        except OSError:
            info = os.lstat(leaf)
            reason = _unsafe_because(info, uid=uid, own=True)
            if reason is None:
                raise
            raise _unsafe(leaf, reason) from None
        reason = _unsafe_because(os.fstat(descriptor), uid=uid, own=True)
        if reason is not None:
            os.close(descriptor)
            raise _unsafe(leaf, reason)
        return descriptor
    descriptor = os.open(base, flags)
    own = base == state or state in base.parents
    reason = _unsafe_because(os.fstat(descriptor), uid=uid, own=own)
    if reason is not None:
        os.close(descriptor)
        raise _unsafe(base, reason)
    path = base
    previous = os.umask(0o077)
    try:
        for name in reversed(missing):
            path = path / name
            with contextlib.suppress(FileExistsError):
                os.mkdir(name, 0o700, dir_fd=descriptor)
            try:
                child = os.open(name, flags | os.O_NOFOLLOW, dir_fd=descriptor)
            except OSError:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                reason = _unsafe_because(info, uid=uid, own=True)
                if reason is None:
                    raise
                raise _unsafe(path, reason) from None
            os.close(descriptor)
            descriptor = child
            reason = _unsafe_because(os.fstat(descriptor), uid=uid, own=True)
            if reason is not None:
                raise _unsafe(path, reason)
    except BaseException:
        os.close(descriptor)
        raise
    finally:
        os.umask(previous)
    return descriptor


def _file_unsafe_because(info: os.stat_result, *, uid: int) -> str | None:
    """Why a private copy is not one, or `None`."""
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        return "is a symbolic link"
    if not stat.S_ISREG(mode):
        return "is not a regular file"
    if info.st_uid != uid:
        return f"is owned by uid {info.st_uid}, not by this user"
    if info.st_nlink != 1:
        return f"has {info.st_nlink} hard links, not one"
    if stat.S_IMODE(mode) != PRIVATE_MODE:
        return f"has mode {stat.S_IMODE(mode):o}, not {PRIVATE_MODE:o}"
    return None


# --------------------------- the copy ---------------------------

def _record_json(record: Mapping[str, Any]) -> str:
    """The record as JSON that cannot end its own `<script>` element.

    `<`, `>` and `&` are written as `\\u` escapes, which JSON reads back as
    the same characters, so no value can spell `</script>` or open a tag."""
    text = json.dumps(dict(record), sort_keys=True, ensure_ascii=True)
    return (text.replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


def _opener_html(record: Mapping[str, Any]) -> str:
    target = html.escape(str(record["opened_url"]), quote=True)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="referrer" content="no-referrer">\n'
        f'<meta http-equiv="refresh" content="0;url={target}">\n'
        "<title>Opening openDox</title>\n"
        f'<script type="application/json" id="{RECORD_ELEMENT_ID}">'
        f"{_record_json(record)}</script>\n"
        "</head>\n"
        "<body>\n"
        "<p>This private file opens this user's openDox console. If the page "
        f'does not open, <a href="{target}">open openDox</a>. Keep this file '
        "private: anyone who can read it can act as this console.</p>\n"
        "</body>\n"
        "</html>\n")


def _identity(path: Path | str) -> tuple[int, int] | None:
    """`(st_dev, st_ino)` of what `path` names, or `None` where nothing
    there can be asked."""
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return (info.st_dev, info.st_ino)


def _identities_above(path: Path) -> set[tuple[int, int]]:
    """The identities of every directory above `path` that exists."""
    return {key for key in map(_identity, Path(path).parents) if key is not None}


def _refuse_a_served_state_dir(state_dir: Path,
                               served_roots: Iterable[Path | str], *,
                               port: int | None) -> None:
    """The state directory and every root this plane serves may not overlap,
    in EITHER direction, or the copy is refused before anything is written.

    RULED by the holder on openxFactory#1220's review (Copilot
    `r4171166321`), mirroring T100's served-repository boundary
    (`doxbench_trust`'s state directory): the token's copy must never sit
    inside what the plane can serve, nor where a clone or an accidental
    commit could carry it. So the state directory may not BE a served root
    or lie inside one. And, by the holder's ruling on batch N's review
    (Copilot `r4174345203`), no served root may be or lie inside the state
    directory either: `<state>/console` itself, or the bundle's tree beside
    it, served as a root, would serve the copy (Copilot at openDox-code#84,
    `r4173889265`, found the first of these). Asked of the RESOLVED paths, so
    a link counts as where it leads. `port` names the copy the refusal is
    about, and `None`, on a plane that writes none, names every console's.

    AND OF THE DIRECTORIES' OWN IDENTITIES (adversarial review of
    openDox-code#84, B4). On a case-insensitive filesystem (macOS's default)
    `<root>/STATE` and `<root>/state` are one directory, and resolving a
    path keeps the case it was given, so names alone let the second
    spelling of the state directory, or of a root, through. Every directory
    that exists on either path is also compared by `(st_dev, st_ino)`
    (`_identity`): the same directory is the same, however it is spelled."""
    resolved = Path(state_dir).resolve()
    copy = (f"the copy {private_copy_path(resolved, port)}" if port is not None
            else f"every console's private copy in {resolved / CONSOLE_DIRNAME}")
    state_is = _identity(resolved)
    above_state = _identities_above(resolved)
    for root in served_roots:
        served = Path(root).resolve()
        served_is = _identity(served)
        if resolved == served or (state_is is not None and state_is == served_is):
            where = f"is the served repository ({served})"
        elif served in resolved.parents or (served_is is not None
                                             and served_is in above_state):
            where = f"lies inside the served repository ({served})"
        elif resolved in served.parents or (state_is is not None
                                             and state_is in _identities_above(served)):
            where = (f"holds {served}, a root this plane serves, so the plane "
                     f"would serve what the state directory keeps, {copy} "
                     "among it")
        else:
            continue
        raise ConsoleAccessRefused(
            f"{runtime_config.PREFIX}STATE_DIR ({state_dir}) {where}. The "
            "state directory and every root this plane serves (through "
            "`/source` or the static bundle) may not overlap, and a clone or a "
            "commit could carry what lies inside a repository, so the console "
            "token's private copy is refused there and nothing is written. Set "
            f"{runtime_config.PREFIX}STATE_DIR to a directory apart from the "
            "repositories and the bundle this machine serves")


def write_private_copy(state_dir: Path | str, *, page_url: str, port: int,
                       token: str,
                       served_roots: Iterable[Path | str]) -> PrivateCopy:
    """Write the copy for the plane on `port`, mode 0600, or refuse.

    `served_roots` are the roots this plane serves: the state directory and
    any of them may not overlap, in either direction, and that is asked
    before anything is written. A file already at the copy's path is replaced
    ONLY when it is this user's own regular file of mode 0600 with one link,
    an earlier serve's copy for this port (#1144 12.4a). Anything else there,
    a loosened copy included, is refused by name and never replaced.

    EVERY REFUSAL NAMES ITS PATH (the opener file's lifecycle, T104's
    self-pass). An operating-system refusal on the way (a parent that will
    not let this user make the state directory, a full disk) is a
    `ConsoleAccessRefused` naming the copy, so the entry point refuses its
    start by name instead of ending in a traceback. And a copy whose
    read-back fails is removed with the refusal, so a start that never served
    leaves no copy behind.

    THE STATE DIRECTORY IS WALKED ONCE (`_walked`, Copilot at
    openDox-code#84, r4174785933), and the served-root boundary, the tree's
    rules and the write all work on the path that walk returned. A link on
    the configured path that is re-pointed after the checks cannot redirect
    the write. The copy's `path` is that walked path.

    THE WALK IS INSIDE THE CONVERSION TOO (Copilot at openDox-code#84,
    r4177975898): an overlong component (ENAMETOOLONG) or an unsearchable
    parent (EACCES) on the way is a refusal by name, like any other.

    A PLATFORM WITHOUT THE POSIX PRIMITIVES is refused first, by name
    (`unsupported_platform`)."""
    _refuse_an_unsupported_platform()
    target = private_copy_path(state_dir, port)
    try:
        state = _walked(state_dir)
        _refuse_a_served_state_dir(state, tuple(served_roots), port=port)
        record = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "kind": RECORD_KIND,
            "page_url": page_url,
            "opened_url": opened_url(page_url, token),
            "port": int(port),
            "pid": os.getpid(),
            FRAGMENT_KEY: token,
        }
        target = private_copy_path(state, port)
        identity, reservation = _write_the_copy(state, target, record)
    except OSError as exc:
        raise ConsoleAccessRefused(
            f"{target} cannot be written ({exc}), so the console token has no "
            "private copy and the start is refused. Use a state directory this "
            f"user can write ({runtime_config.PREFIX}STATE_DIR)") from None
    copy = PrivateCopy(path=target, page_url=page_url,
                       opened_url=record["opened_url"], identity=identity,
                       reservation=reservation)
    try:
        read_private_copy(target)   # what was written is what a reader accepts
    except BaseException:
        remove_private_copy(copy)
        raise
    return copy


def _write_the_copy(state: Path, target: Path,
                    record: Mapping[str, Any]) -> tuple[int, int]:
    """`write_private_copy`'s writing half: the tree judged and made, the
    name judged, the file written beside it and renamed into place. Returns
    the written file's `(st_dev, st_ino)`."""
    _refuse_an_unsafe_tree(state, existing_only=True)
    directory = _open_private_directory(target.parent, state=state)
    uid = os.getuid()
    temporary = f".{target.name}.opendox-{os.getpid()}"
    try:
        # Judged only after the directories exist: what `existing_only` could
        # not see before they were made, it sees now. `console/` is judged by
        # its descriptor too, its exact mode included.
        _refuse_an_unsafe_tree(state, existing_only=False)
        reason = _console_dir_unsafe_because(os.fstat(directory), uid=uid)
        if reason is not None:
            raise _unsafe(target.parent, reason)
        _lock(directory)            # until the copy is in place (`_lock`)
        _sweep_stale_copies(directory, spare=target.name)
        try:
            present = os.stat(target.name, dir_fd=directory,
                              follow_symlinks=False)
        except FileNotFoundError:
            present = None
        # THIS USER'S OWN regular file, of mode 0600, with one link, is an
        # earlier serve's copy for this port, and is replaced. Anything else
        # was PLANTED, LINKED or LOOSENED there, and is refused, never
        # followed or replaced (#1144 12.4a).
        reason = (None if present is None
                  else _file_unsafe_because(present, uid=uid))
        if reason is not None:
            raise ConsoleAccessRefused(
                f"{target} {reason}: something other than this user's own "
                "private copy is at that name, so it is refused, never "
                "followed or replaced")
        if present is not None:
            _refuse_a_running_consoles_copy(target, directory, present)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)   # an interrupted start's; a link itself, never its target
        handle = os.open(temporary,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         PRIVATE_MODE, dir_fd=directory)
        # From here a failure (a full disk, an interrupt) removes the
        # temporary file it made, so no partial copy is left beside the name.
        # The descriptor stays open on success: it is the copy's RESERVATION
        # (`_Reservation`), locked before the copy takes its name, so no other
        # publication can find the name unreserved.
        reservation = _Reservation(handle)
        try:
            os.fchmod(handle, PRIVATE_MODE)
            data = _opener_html(record).encode("utf-8")
            view = memoryview(data)
            while view:
                view = view[os.write(handle, view):]
            os.fsync(handle)
            written = os.fstat(handle)
            if fcntl is not None:
                with contextlib.suppress(OSError):   # no locks here: unreserved
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.replace(temporary, target.name, src_dir_fd=directory,
                       dst_dir_fd=directory)
        except BaseException:
            reservation.close()
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
            raise
    finally:
        os.close(directory)
    return (written.st_dev, written.st_ino), reservation


def _refuse_a_running_consoles_copy(target: Path, directory: int,
                                    present: os.stat_result) -> None:
    """Refuse when the copy at `target` is RESERVED by a console that is still
    running (`_Reservation`); return where it is a stale copy, to be replaced.

    The copy is opened without following a link or blocking, checked to be
    the file judged a moment ago, and its lock asked for WITHOUT waiting: a
    lock that is held is a running console's, and one that is free is a
    stale copy's. Where the filesystem keeps no locks, nothing can be told,
    and the copy is replaced, as before. The console directory's lock
    (`_lock`) is held throughout, so no publication races this one."""
    try:
        held = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=directory)
    except FileNotFoundError:
        return
    try:
        info = os.fstat(held)
        if (info.st_dev, info.st_ino) != (present.st_dev, present.st_ino):
            raise ConsoleAccessRefused(
                f"{target} changed while it was judged, so it is refused, "
                "never replaced")
        if fcntl is None:
            return
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ConsoleAccessRefused(
                f"{target} belongs to a console that is still running"
                f"{_writer_of(held)}. Two serves on this port number share "
                f"this state directory (for example one on 127.0.0.1 and one "
                "on ::1), and a running console's copy is never replaced. "
                "Stop that console, or serve on another port or with another "
                f"{runtime_config.PREFIX}STATE_DIR") from None
        except OSError:
            return                          # no locks here: replace, as before
    finally:
        os.close(held)


def _sweep_stale_copies(directory: int, *, spare: str) -> None:
    """Remove every copy in `console/` whose console is gone, `spare` aside.

    A SERVER THAT DIED LEFT ITS COPY (adversarial review of openDox-code#84,
    B9). A SIGKILL, an out-of-memory kill or a power cut runs no cleanup, so
    its copy, a token in it, stayed until a later serve happened to take the
    same port. A publication now sweeps them. It runs with the console
    directory's lock held (`_lock`), so no publication or removal is under
    way: a copy whose lock is free belongs to no running console
    (`_Reservation`), and a writer's temporary file or a remover's taken name
    found then belongs to a process that died mid-way. Only this user's own
    regular files of mode 0600 with one link, named as those are named
    (`_SWEEPABLE`), are swept, each only while its name is still the file
    whose lock was taken. A lock still held, or a filesystem that keeps no
    locks, tells nothing, and the file stays. `spare` is the name this
    publication judges itself (`_refuse_a_running_consoles_copy`)."""
    if fcntl is None:
        return
    uid = os.getuid()
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if name == spare or not _SWEEPABLE.fullmatch(name):
            continue
        with contextlib.suppress(OSError):
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
            try:
                info = os.fstat(handle)
                if _file_unsafe_because(info, uid=uid) is not None:
                    continue
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # held: stays
                still = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (still.st_dev, still.st_ino) == (info.st_dev, info.st_ino):
                    os.unlink(name, dir_fd=directory)
            finally:
                os.close(handle)


def _writer_of(handle: int) -> str:
    """`" (pid N)"` from the copy's own record, or nothing."""
    with contextlib.suppress(OSError, ValueError, AttributeError):
        found = _RECORD_PATTERN.search(
            os.pread(handle, _READ_LIMIT, 0).decode("utf-8", "replace"))
        pid = json.loads(found.group("record")).get("pid")
        if isinstance(pid, int):
            return f" (pid {pid})"
    return ""


def read_private_copy(path: Path | str) -> dict:
    """The record in the copy at `path`, or a refusal naming why: an
    operating-system error on the way (an overlong component, an unsearchable
    parent) included (Copilot at openDox-code#84, r4177975898). A platform
    without the POSIX primitives is refused first, by name
    (`unsupported_platform`)."""
    _refuse_an_unsupported_platform()
    try:
        return _read_the_copy(path)
    except OSError as exc:
        raise ConsoleAccessRefused(
            f"{path} cannot be read ({exc}), so it is not a private copy this "
            "user can use") from None


def _read_the_copy(path: Path | str) -> dict:
    """The record in the copy at `path`, or a refusal naming why.

    The tree is judged again, and the file by its own descriptor, opened
    without following a link and without blocking: a regular file, this
    user's, exactly 0600, with one link. A planted, linked or loosened copy is
    refused, and so is a FIFO, without waiting on it."""
    given = Path(path)
    if given.parent.name != CONSOLE_DIRNAME:
        raise ConsoleAccessRefused(f"{given} is not in a `{CONSOLE_DIRNAME}/` "
                                   "directory of a state directory")
    # Walked once, as the writer walks it, and read from where the walk led.
    state = _walked(given.parent.parent)
    target = state / CONSOLE_DIRNAME / given.name
    try:
        _refuse_an_unsafe_tree(state, existing_only=False)
    except FileNotFoundError:
        raise ConsoleAccessRefused(f"{target} does not exist: no plane wrote a "
                                   "private copy there") from None
    uid = os.getuid()
    # NEVER MADE BY A READ: the directory is opened as it is, without
    # following a link, and judged by its descriptor.
    try:
        directory = os.open(target.parent,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        info = os.lstat(target.parent)
        raise _unsafe(target.parent, _unsafe_because(info, uid=uid, own=True)
                      or "cannot be opened") from None
    try:
        reason = _console_dir_unsafe_because(os.fstat(directory), uid=uid)
        if reason is not None:
            raise _unsafe(target.parent, reason)
        # `O_NONBLOCK` (Copilot at openDox-code#84, r4174674702): a FIFO
        # planted at the name, with no writer, would block a plain read-only
        # `open` forever, before the descriptor's regular-file check below
        # could refuse it. A regular file reads the same either way.
        try:
            handle = os.open(target.name,
                             os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        except FileNotFoundError:
            raise ConsoleAccessRefused(f"{target} does not exist: no plane on "
                                       "that port wrote a private copy") from None
        except OSError:
            info = os.stat(target.name, dir_fd=directory, follow_symlinks=False)
            reason = _file_unsafe_because(info, uid=uid) or "cannot be opened"
            raise ConsoleAccessRefused(f"{target} {reason}") from None
        try:
            reason = _file_unsafe_because(os.fstat(handle), uid=uid)
            if reason is not None:
                raise ConsoleAccessRefused(
                    f"{target} {reason}, so it is not this user's private copy")
            data = os.read(handle, _READ_LIMIT)
        finally:
            os.close(handle)
    finally:
        os.close(directory)
    match = _RECORD_PATTERN.search(data.decode("utf-8", "replace"))
    if match is None:
        raise ConsoleAccessRefused(f"{target} carries no console record")
    try:
        record = json.loads(match.group("record"))
    except ValueError:
        raise ConsoleAccessRefused(f"{target}'s console record is not JSON") from None
    if (not isinstance(record, dict) or record.get("kind") != RECORD_KIND
            or record.get("schema_version") != RECORD_SCHEMA_VERSION):
        raise ConsoleAccessRefused(f"{target}'s console record is not a "
                                   f"{RECORD_KIND} v{RECORD_SCHEMA_VERSION}")
    token = _refuse_token(record.get(FRAGMENT_KEY))
    page_url = record.get("page_url")
    if not isinstance(page_url, str) or record.get("opened_url") != opened_url(
            page_url, token):
        raise ConsoleAccessRefused(f"{target}'s console record does not open "
                                   "its own page with its own token")
    return record


def remove_private_copy(copy: PrivateCopy | None) -> None:
    """Remove `copy` when the server stops, if it is still the file written.

    A later serve on the same port writes a file of its own, and that one is
    left alone. Never raises: a copy already gone is the goal reached.

    THE NAME IS TAKEN BEFORE IT IS JUDGED (Copilot at openDox-code#84,
    r4173806552). Checking the name's identity and
    then unlinking it are two steps, and a replacement written between them
    would be the file unlinked. So the name is first RENAMED to a name only
    this process uses, atomically, and what was renamed is judged: this
    process's own file is removed, and anything else is linked back under the
    name (never over a still newer copy) and its temporary name removed. The
    entry points also remove the copy BEFORE they close the listening socket,
    so no later serve can bind the port, and write its own copy, until this
    one is gone.

    PUT BACK BY A RENAME WHERE A HARD LINK CANNOT BE MADE (T104's self-pass).
    A filesystem without hard links refuses the link (EPERM), and so does a
    directory, and the other serve's copy used to be deleted with the
    temporary name. It is renamed back instead, where the name is still
    free, and the console directory's lock (`_lock`) keeps any newer copy
    from being published between that check and the rename."""
    if copy is None:
        return
    try:
        directory = os.open(copy.path.parent,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        if copy.reservation is not None:   # nothing left to remove: unreserve
            copy.reservation.close()
        return
    name = copy.path.name
    taken = f".{name}.removing-{os.getpid()}-{os.urandom(6).hex()}"
    try:
        _lock(directory)            # no copy is published meanwhile (`_lock`)
        try:
            os.rename(name, taken, src_dir_fd=directory, dst_dir_fd=directory)
        except OSError:
            return                          # nothing there: already gone
        with contextlib.suppress(OSError):
            info = os.stat(taken, dir_fd=directory, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != copy.identity:
                # ANOTHER SERVE'S COPY: put it back under its name, unless a
                # still newer one has arrived there, which then stands.
                try:
                    os.link(taken, name, src_dir_fd=directory,
                            dst_dir_fd=directory, follow_symlinks=False)
                except FileExistsError:
                    pass
                except OSError:
                    if not _name_exists(name, directory):
                        os.rename(taken, name, src_dir_fd=directory,
                                  dst_dir_fd=directory)
        with contextlib.suppress(OSError):
            os.unlink(taken, dir_fd=directory)
    finally:
        # Its RESERVATION goes with it, the file gone and the console
        # directory still locked, so no publication sees it in between.
        if copy.reservation is not None:
            copy.reservation.close()
        os.close(directory)


def _name_exists(name: str, directory: int) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


class ConsoleTerminated(KeyboardInterrupt):
    """SIGTERM, SIGHUP or Ctrl-C, raised as the interrupt the serve loops
    already stop on."""


#: Whether a stop is being HELD (`deferred_termination`), the one that
#: arrived meanwhile, and whether a stop has already been RAISED. Python runs
#: signal handlers in the main thread only, as the entry points publish and
#: remove there, so plain module state serves.
_held = {"depth": 0, "pending": None, "stopping": False}


def _terminate_as_interrupt(signum, frame):
    """A stop, raised once.

    THE FIRST STOP IS THE ONLY ONE RAISED (adversarial review of
    openDox-code#84, B5). A double Ctrl-C, or a SIGTERM and then the SIGHUP
    of a closing terminal, could land its second signal after the first had
    unwound the serve loop and before the cleanup's `deferred_termination`
    held anything, and that second interrupt escaped the `finally` and left
    the copy. Once one stop is raised, every later one is only recorded, and
    the cleanup runs to its end."""
    if _held["depth"] or _held["stopping"]:
        _held["pending"] = signum
        return
    _held["stopping"] = True
    raise ConsoleTerminated


@contextlib.contextmanager
def deferred_termination(*, raise_pending: bool = True):
    """Hold a SIGTERM or SIGHUP that arrives inside the block, rather than
    raising it in the middle of publishing or removing a copy (Copilot at
    openDox-code#84, r4175213864): a copy half published, or half removed,
    is one nothing cleans up. On the way out, a held stop is raised as
    `ConsoleTerminated` once the block is done, when the copy is in the
    caller's hands, or dropped with `raise_pending=False`, for a removal,
    which is a stop already. Only the handler `terminate_as_interrupt`
    installs holds anything: SIGTERM, SIGHUP where it has its default, and
    Ctrl-C where it has Python's own."""
    _held["depth"] += 1
    try:
        yield
    finally:
        _held["depth"] -= 1
    if not _held["depth"]:
        pending, _held["pending"] = _held["pending"], None
        if pending is not None and raise_pending and not _held["stopping"]:
            _held["stopping"] = True        # raised once (`_terminate_as_interrupt`)
            raise ConsoleTerminated


@contextlib.contextmanager
def terminate_as_interrupt(enabled: bool):
    """While a standalone console's private copy exists, read SIGTERM as the
    Ctrl-C the serve loops already stop cleanly on, so a plain `kill <pid>`
    unwinds through the code that removes the copy (Copilot at
    openDox-code#84, r4173806590). The handler it replaces is put back on the
    way out. `enabled` is False wherever no copy was written, a host's plane
    or a plane with no token, and then nothing changes: those planes keep the
    signal's default action exactly as before. Off the main thread no handler
    can be installed, and nothing is.

    AND SIGHUP (T104's self-pass), which a closed terminal sends and whose
    default action ends the process with the copy left behind. It is read the
    same way, but only where it still has its default action: a process
    started ignoring it (`nohup`) keeps ignoring it.

    AND CTRL-C (Copilot at openDox-code#84, r4178041022). Python's own
    SIGINT handler raises at once, so a Ctrl-C just after the copy's rename
    into place, or just after a removal's take, bypassed
    `deferred_termination` and left a copy, or a `.removing-*` file, behind.
    It is taken the same way, still raised as a `KeyboardInterrupt`, but only
    where it still has Python's own handler: an ignored SIGINT, or a host's
    own handler, is left exactly as it was."""
    if not enabled:
        yield
        return
    signals = [signal.SIGTERM]
    hangup = getattr(signal, "SIGHUP", None)
    if hangup is not None and signal.getsignal(hangup) == signal.SIG_DFL:
        signals.append(hangup)
    if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
        signals.append(signal.SIGINT)
    previous: dict = {}
    try:
        for signum in signals:
            previous[signum] = signal.signal(signum, _terminate_as_interrupt)
    except ValueError:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        yield
        return
    _held.update(pending=None, stopping=False)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        _held.update(pending=None, stopping=False)


def _carries_a_console_record(handle: int, info: os.stat_result) -> bool:
    """Whether the regular file open on `handle` IS a console token's private
    copy by what it holds: a console record (`RECORD_KIND`) in the element a
    copy keeps it in, wherever the file lies and whatever its name.

    Read with `pread`, from the descriptor already open, so it needs no new
    descriptor and does not move the offset the caller then reads from. A
    regular file whose head cannot be read is judged to be a copy: a check
    that cannot be made denies, never allows."""
    if not stat.S_ISREG(info.st_mode):
        return False
    try:
        head = os.pread(handle, _READ_LIMIT, 0)
    except OSError:
        return True
    found = _RECORD_PATTERN.search(head.decode("utf-8", "replace"))
    if found is None:
        return False
    try:
        record = json.loads(found.group("record"))
    except ValueError:
        return False
    return isinstance(record, dict) and record.get("kind") == RECORD_KIND


def is_private_file(handle: int, private_roots: Iterable[Path | str]) -> bool:
    """Whether the file open on `handle` is a console token's private copy.

    Judged by the FILE'S OWN IDENTITY, `(st_dev, st_ino)`, against every name
    in each directory `publish` marked private (Copilot at openDox-code#84,
    r4178133842). A path cannot tell: a served root re-pointed at the state
    directory after publication, a link swapped after a check, or a hard link
    made anywhere under a served root all reach the copy by a name that looks
    like something else. The identity of what was OPENED cannot be swapped
    afterwards. Every name in the directory counts, every port's copy and a
    temporary name included.

    AND BY WHAT THE FILE HOLDS (Copilot at openDox-code#84, r4179239380 and
    r4179239411). A copy in ANOTHER state directory (a second standalone
    plane of the same user, with its own `OPENDOX_STATE_DIR`) is in no
    directory this plane marked, and a copy removed between this open and
    the directory's scan has no name left there to match. Both are still a
    file that holds a console record, so the file open on `handle` is judged
    by its own bytes first (`_carries_a_console_record`), and by its
    identity after.

    A SCAN THAT FAILS DENIES (Copilot at openDox-code#84, r4179239424). A
    private directory that does not exist holds no copy, and counts for
    nothing. One that exists and cannot be listed (out of descriptors, say)
    cannot clear the file, so the file is judged to be a copy; so is a name
    in it whose status cannot be read for any reason but its removal."""
    info = os.fstat(handle)
    if _carries_a_console_record(handle, info):
        return True
    key = (info.st_dev, info.st_ino)
    for root in private_roots:
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    try:
                        found = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue                # removed meanwhile
                    except OSError:
                        return True             # cannot be cleared: denied
                    if (found.st_dev, found.st_ino) == key:
                        return True
        except FileNotFoundError:
            continue                            # no directory: no copy in it
        except OSError:
            return True                         # cannot be listed: denied
    return False


def within_private_roots(path: Path | str,
                         private_roots: Iterable[Path | str]) -> bool:
    """Whether `path`, where it leads, IS a private-copy directory or lies
    inside one: by name, and by the identity of every directory on its way.

    A case-insensitive filesystem (macOS's default) has more than one
    spelling for each directory, and resolving a path keeps the case it was
    given, so `<web>/state-alias/CONSOLE/` named the copies' directory under
    a name no private root spells (adversarial review of openDox-code#84,
    B4). So the resolved path is also judged by `(st_dev, st_ino)`: where it,
    or any directory above it, is a private root by identity, it is that
    root, however it is spelled. A private root that does not exist yet is
    judged by name alone, as nothing can lie inside it."""
    target = Path(path).resolve()
    roots = [Path(root) for root in private_roots]
    if any(target == root or root in target.parents for root in roots):
        return True
    marked = {key for key in map(_identity, roots) if key is not None}
    if not marked:
        return False
    return bool(marked & ({_identity(target)} | _identities_above(target)))


def opens_a_private_file(path: Path | str,
                         private_roots: Iterable[Path | str]) -> bool:
    """Whether what opens at `path` is a file in a private-copy directory
    (`is_private_file`). Opened without blocking, so a FIFO cannot stall the
    check; a path that does not open is no private file, and is left to the
    caller to answer as it always has."""
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        return is_private_file(handle, private_roots)
    finally:
        os.close(handle)


def needs_copy(httpd: Any) -> bool:
    """Whether the plane `httpd` delivers its console token through a
    private copy: a standalone plane that minted one. The entry points ask it
    BEFORE `publish`, to read a stop as Ctrl-C from before the copy exists."""
    return bool(getattr(httpd, "console_token", None)) and _standalone(httpd)


def _standalone(httpd: Any) -> bool:
    return getattr(httpd, "console_token_delivery", None) == DELIVERY_OPENED_URL


def guard_private_roots(httpd: Any, state_dir: Path | str) -> None:
    """Keep a standalone plane that WRITES NO COPY from serving another's.

    A SIBLING PLANE SERVED ANOTHER PLANE'S COPY (adversarial review of
    openDox-code#84, B1). Two standalone planes of one user share the state
    directory. One that minted no token (no git identity, so no session
    verbs) wrote no copy, so it asked no boundary and marked no private
    root, and a root it served that held the state directory served the
    other plane's copy, token and all, to any local caller. The boundary is
    the PLANE's, not the copy's: this one is asked of the state directory as
    `write_private_copy` asks it, by name and by identity, and refuses the
    start by name, and the copies' directory is marked private
    (`httpd.private_roots`), so the static handler, `/source` and
    `/snapshot.json` refuse every console's copy here too.

    ONE WALK, AS THE WRITER WALKS (Copilot at openDox-code#84,
    r4179091592). The boundary and the marking each resolved the configured
    path for themselves, so a link on it re-pointed between the two left the
    boundary judging the real state directory and the marking naming a
    decoy. The state directory is walked once (`_walked`), every directory
    and link on the way judged as the writer judges them, and the boundary
    and the marking both use the path that walk returned. An operating-system
    refusal on the way is a refusal by name, as it is for the writer.

    AND THE PLATFORM FIRST (Copilot at openDox-code#84, r4179091624): this
    plane's handlers judge files by the same POSIX primitives, so a platform
    without them is refused by name here too (`unsupported_platform`)."""
    _refuse_an_unsupported_platform()
    try:
        state = _walked(state_dir)
        _refuse_a_served_state_dir(state, tuple(getattr(httpd, "served_roots", ())),
                                   port=None)
    except OSError as exc:
        raise ConsoleAccessRefused(
            f"{private_copy_path(state_dir, 0).parent} cannot be judged ({exc}), "
            "so this standalone plane cannot keep the console tokens' private "
            "copies unserved, and the start is refused. Use a state directory "
            f"this user can reach ({runtime_config.PREFIX}STATE_DIR)") from None
    httpd.private_roots = (state / CONSOLE_DIRNAME,)


def publish(httpd: Any, *, page_url: str,
            env: Mapping[str, str] | None = None) -> PrivateCopy | None:
    """What an ENTRY POINT does after `serve.build_server`. On a standalone
    plane that minted a token, write the private copy into the install's
    state directory and return it. On a standalone plane that minted none,
    write nothing, and still keep the boundary and mark every console's copy
    private (`guard_private_roots`), so the DELIVERY'S RULES do not depend on
    the token. Otherwise, a host's plane, `None`, and nothing changes.

    A state directory that cannot be named, or a tree that is not this user's
    alone, refuses (`ConsoleAccessRefused`), and the entry point refuses with
    it: a console nobody can open is not served as if it could be."""
    if not _standalone(httpd):
        return None
    _refuse_an_unsupported_platform()       # token or not (r4179091624)
    try:
        state = runtime_config.state_dir(env)
    except runtime_config.ConfigurationError as exc:
        raise ConsoleAccessRefused(
            "the console tokens' private copies have no state directory, so "
            f"this standalone plane cannot keep them unserved: {exc}") from None
    if not needs_copy(httpd):
        guard_private_roots(httpd, state)
        return None
    token = httpd.console_token
    copy = write_private_copy(state, page_url=page_url,
                              port=int(httpd.server_address[1]), token=token,
                              served_roots=getattr(httpd, "served_roots", ()))
    # THE STATIC HANDLER NEVER SERVES A COPY (Copilot at openDox-code#84,
    # r4173889294). It follows links inside `--web-dir` (a governed host's
    # composed web root is made of them), so a link out of the bundle into the
    # state directory would reach the copies. The handler refuses every static
    # request whose resolved target is this directory or lies inside it, by
    # name or by identity (`within_private_roots`), every port's copy included
    # (`serve.DashboardHandler.send_head`).
    httpd.private_roots = (copy.path.parent.resolve(),)
    return copy
