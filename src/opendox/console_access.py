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
page while the server runs. The copy is removed when the server stops.

THE COPY IS CHECKED THE WAY openDox-code#69's BUNDLE CHECKS ITS TREE
(`opendox.runtime.bundle`: `refuse_an_unsafe_tree`, `_make_private_directories`,
`write_authentication`). The rules are copied here, not imported, because they
are that module's private helpers and its refusal names a socket:

  * the state directory and `console/` must be real directories, this user's,
    writable by no one else; every directory above them must be this user's or
    root's, and one that others can write must be sticky; every symbolic link
    on the configured path must be this user's or root's;
  * a missing directory is made relative to its parent's DESCRIPTOR, born
    0700, and opened without following a link before anything is made under
    it;
  * the file is created exclusively, without following a link, set to exactly
    0600 by its descriptor, and renamed into place. A name already at the
    target that is not this user's own regular file (a link, a directory, a
    file another user owns, a file with a second hard link) is REFUSED, never
    followed or replaced;
  * a READ asks all of it again of what exists, and of the file by its
    descriptor: a regular file, this user's, exactly 0600, one link;
  * and the state directory may not BE, or lie inside, a root the plane
    serves (its checkout and any declared source root), by name and before
    any write, as T100's served-repository boundary refuses its own: the
    token must never sit inside what `/source` can serve (holder's ruling on
    openxFactory#1220's review, Copilot `r4171166321`).

A CREATED FILE, with no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import contextlib
import dataclasses
import html
import json
import os
import re
import stat
import urllib.parse
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from opendox.runtime import config as runtime_config

__all__ = [
    "CONSOLE_DIRNAME", "ConsoleAccessRefused", "DELIVERY_CAPABILITIES",
    "DELIVERY_OPENED_URL", "FRAGMENT_KEY", "PrivateCopy", "RECORD_ELEMENT_ID",
    "RECORD_KIND", "delivery_for", "opened_url", "private_copy_path", "publish",
    "read_private_copy", "remove_private_copy", "write_private_copy",
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
#: A copy is a few hundred bytes; a read stops well past that.
_READ_LIMIT = 64 * 1024
#: `secrets.token_urlsafe` spells a token in these characters only, so a token
#: needs no escaping in a fragment and a value outside them is not one.
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{16,512}")
_RECORD_PATTERN = re.compile(
    r'<script type="application/json" id="' + RECORD_ELEMENT_ID
    + r'">(?P<record>[^<]*)</script>')
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ConsoleAccessRefused(Exception):
    """The private copy cannot be written or read safely, and why."""


@dataclasses.dataclass(frozen=True)
class PrivateCopy:
    """One written copy: where it is, what it opens, and which file it is."""

    path: Path
    page_url: str
    opened_url: str
    #: `(st_dev, st_ino)` of the file this process wrote, so a removal at
    #: shutdown removes that file and never one written after it.
    identity: tuple[int, int]

    @property
    def file_url(self) -> str:
        """The `file://` URL a browser is given: a path, never the token."""
        return self.path.as_uri()


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


def _unsafe(path: Path, reason: str) -> ConsoleAccessRefused:
    return ConsoleAccessRefused(
        f"{path} {reason}, so another user could replace or read the console "
        "token's private copy. Use a state directory only this user can change "
        f"({runtime_config.PREFIX}STATE_DIR)")


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
        reason = _unsafe_because(info, uid=uid, own=mine)
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


def _refuse_a_served_state_dir(state_dir: Path,
                               served_roots: Iterable[Path | str]) -> None:
    """The state directory may not BE, or lie inside, a root this plane serves.

    RULED by the holder on openxFactory#1220's review (Copilot
    `r4171166321`), mirroring T100's served-repository boundary
    (`doxbench_trust`'s state directory): the token's copy must never sit
    inside what `/source` can serve, nor where a clone or an accidental commit
    could carry it. Asked of the RESOLVED paths, before anything is written."""
    resolved = Path(state_dir).resolve()
    for root in served_roots:
        served = Path(root).resolve()
        if resolved == served or served in resolved.parents:
            where = ("is the served repository" if resolved == served
                     else "lies inside the served repository")
            raise ConsoleAccessRefused(
                f"{runtime_config.PREFIX}STATE_DIR ({state_dir}) {where} "
                f"({served}), which this plane serves through `/source` and a "
                "clone or a commit could carry, so the console token's private "
                "copy is refused there and nothing is written. Set "
                f"{runtime_config.PREFIX}STATE_DIR to a directory outside the "
                "repositories this machine serves")


def write_private_copy(state_dir: Path | str, *, page_url: str, port: int,
                       token: str,
                       served_roots: Iterable[Path | str]) -> PrivateCopy:
    """Write the copy for the plane on `port`, mode 0600, or refuse.

    `served_roots` are the roots this plane serves (`/source`'s checkout and
    any declared source root): a state directory that is one of them, or lies
    inside one, is refused before anything is written. Replaces this user's
    own earlier copy for the same port (a server restarted there), and refuses
    anything else already at that name."""
    state = Path(state_dir)
    _refuse_a_served_state_dir(state, tuple(served_roots))
    record = {
        "schema_version": RECORD_SCHEMA_VERSION,
        "kind": RECORD_KIND,
        "page_url": page_url,
        "opened_url": opened_url(page_url, token),
        "port": int(port),
        "pid": os.getpid(),
        FRAGMENT_KEY: token,
    }
    _refuse_an_unsafe_tree(state, existing_only=True)
    target = private_copy_path(state, port)
    directory = _open_private_directory(target.parent, state=state)
    uid = os.getuid()
    temporary = f".{target.name}.opendox-{os.getpid()}"
    try:
        # Judged only after the directories exist: what `existing_only` could
        # not see before they were made, it sees now.
        _refuse_an_unsafe_tree(state, existing_only=False)
        try:
            present = os.stat(target.name, dir_fd=directory,
                              follow_symlinks=False)
        except FileNotFoundError:
            present = None
        # THIS USER'S OWN regular file, with one link, is an earlier serve's
        # copy for this port, and is replaced. Anything else was PLANTED or
        # LINKED there, and is refused, never followed or replaced.
        if present is not None and not (
                stat.S_ISREG(present.st_mode) and present.st_uid == uid
                and present.st_nlink == 1):
            reason = (_file_unsafe_because(present, uid=uid)
                      or "is not this user's own file")
            raise ConsoleAccessRefused(
                f"{target} {reason}: something other than this user's own "
                "private copy is at that name, so it is refused, never "
                "followed or replaced")
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)   # an interrupted start's; a link itself, never its target
        handle = os.open(temporary,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         PRIVATE_MODE, dir_fd=directory)
        try:
            os.fchmod(handle, PRIVATE_MODE)
            data = _opener_html(record).encode("utf-8")
            view = memoryview(data)
            while view:
                view = view[os.write(handle, view):]
            os.fsync(handle)
            written = os.fstat(handle)
        finally:
            os.close(handle)
        try:
            os.replace(temporary, target.name, src_dir_fd=directory,
                       dst_dir_fd=directory)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory)
            raise
    finally:
        os.close(directory)
    copy = PrivateCopy(path=target, page_url=page_url,
                       opened_url=record["opened_url"],
                       identity=(written.st_dev, written.st_ino))
    read_private_copy(target)       # what was written is what a reader accepts
    return copy


def read_private_copy(path: Path | str) -> dict:
    """The record in the copy at `path`, or a refusal naming why.

    The tree is judged again, and the file by its own descriptor, opened
    without following a link: a regular file, this user's, exactly 0600, with
    one link. A planted, linked or loosened copy is refused."""
    target = Path(path)
    state = target.parent.parent
    if target.parent.name != CONSOLE_DIRNAME:
        raise ConsoleAccessRefused(f"{target} is not in a `{CONSOLE_DIRNAME}/` "
                                   "directory of a state directory")
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
        reason = _unsafe_because(os.fstat(directory), uid=uid, own=True)
        if reason is not None:
            raise _unsafe(target.parent, reason)
        try:
            handle = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW,
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
    left alone. Never raises: a copy already gone is the goal reached."""
    if copy is None:
        return
    with contextlib.suppress(OSError):
        info = os.lstat(copy.path)
        if (info.st_dev, info.st_ino) == copy.identity:
            os.unlink(copy.path)


def publish(httpd: Any, *, page_url: str,
            env: Mapping[str, str] | None = None) -> PrivateCopy | None:
    """What an ENTRY POINT does after `serve.build_server`: on a standalone
    plane that minted a token, write the private copy into the install's
    state directory and return it; otherwise `None`, and nothing is written.

    A state directory that cannot be named, or a tree that is not this user's
    alone, refuses (`ConsoleAccessRefused`), and the entry point refuses with
    it: a console nobody can open is not served as if it could be."""
    token = getattr(httpd, "console_token", None)
    if not token or getattr(httpd, "console_token_delivery",
                            None) != DELIVERY_OPENED_URL:
        return None
    try:
        state = runtime_config.state_dir(env)
    except runtime_config.ConfigurationError as exc:
        raise ConsoleAccessRefused(
            f"the console token's private copy has no state directory: {exc}"
        ) from None
    return write_private_copy(state, page_url=page_url,
                              port=int(httpd.server_address[1]), token=token,
                              served_roots=getattr(httpd, "served_roots", ()))
