"""The console token travels in the opened URL, not `/capabilities` (plan 034
T104; RULED openxFactory#656 comment `5963851934`, adversarial review 2's M5).

A standalone openDox served its per-serve console token from `/capabilities`
to any loopback caller, other OS users of the machine included. The token
lets a page edit documents and run chat turns that spend the operator's model
credential. Only the DELIVERY changes, and this file holds each part of it:

1. A STANDALONE plane (openDox's own default profile) carries no token on
   `/capabilities`, and no route a second local user can ask serves it. A
   HOST's plane (this suite's own `_SuiteProfile`, as openxFactory's) keeps
   the `/capabilities` delivery it reads today.
2. The token travels in the opened URL's FRAGMENT and never in its query: the
   URL, the private copy's forwarding targets, and what the entry point hands
   the browser (a `file://` path) and prints (never the token).
3. The private copy is 0600 in a 0700 directory, this user's, and a copy that
   is PLANTED, LINKED, hard-linked or loosened is refused, never followed.
   Its record cannot break out of its `<script>` element.
4. Every route that requires the token still requires it.
5. The documented command, as a user runs it, end to end.

The page's half (`web/views/notebook.js`) is `tests/test_console_token_view.py`.

A CREATED FILE, with no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import html.parser
import http.client
import json
import os
import re
import signal
import socket
import socketserver
import stat
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

from standalone_child import Child, fresh_repository, git

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
WEB = ROOT / "src" / "opendox" / "web"

#: `generate-and-open`'s bare URL line, as `test_standalone_generate_path`
#: reads it, and its console line.
_URL = re.compile(r"^(http://([0-9.]+):([0-9]+))/index\.html$")
_CONSOLE = re.compile(r"^  console (file://\S+) ")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def standalone_profile():
    """openDox's OWN default profile for one case, as an entry point registers
    it where no host has, and this suite's host profile put back afterwards
    exactly as it was (a host's registration, or a default)."""
    from opendox import default_profile, domain_profile as dp

    saved = (dp._registered, dp._is_default, dp._built_from_default)
    dp.unregister()
    dp.register_default(default_profile)
    try:
        yield default_profile
    finally:
        dp._registered, dp._is_default, dp._built_from_default = saved


def _clean_git(monkeypatch) -> None:
    for name in list(os.environ):
        if name.startswith(("GIT_", "XF_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def _repository(tmp_path: Path) -> Path:
    """T050's fixture, with the identity a served actor is read from, so the
    plane has a session capability and mints a token at all."""
    repo = fresh_repository(PLAIN, tmp_path)
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    return repo


@contextlib.contextmanager
def _serving(tmp_path: Path, monkeypatch):
    """`serve.build_server` over a fresh repository, on loopback, serving."""
    from opendox import serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(WEB, snapshot, repo, port=0, quiet=True)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield httpd, httpd.server_address[:2], repo
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


def _call(base, method: str, path: str, *, body: bytes | None = None,
          token: str | None = None) -> tuple[int, dict, bytes]:
    """One same-origin JSON request: the status, the headers and the raw body."""
    from opendox import serve

    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers[serve.CONSOLE_TOKEN_HEADER] = token
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return (response.status, dict(response.getheaders()), response.read())
    finally:
        connection.close()


def _state(tmp_path: Path) -> Path:
    """A fresh state directory, this user's alone, as the bundle wants one."""
    state = tmp_path / "state"
    state.mkdir(mode=0o700, parents=True)
    state.chmod(0o700)
    return state


def _token() -> str:
    from opendox import serve
    return serve.mint_console_token()


def _write(state: Path, port: int = 8080, token: str | None = None,
           page_url: str | None = None):
    from opendox import console_access
    return console_access.write_private_copy(
        state, page_url=page_url or f"http://127.0.0.1:{port}/index.html",
        port=port, token=token or _token(), served_roots=())


class _Targets(html.parser.HTMLParser):
    """Every URL the copy forwards to, and its record's text."""

    def __init__(self) -> None:
        super().__init__()
        self.refresh: list[str] = []
        self.links: list[str] = []
        self.scripts: list[tuple[dict, str]] = []
        self._script: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and (attrs.get("http-equiv") or "").lower() == "refresh":
            delay, _, rest = (attrs.get("content") or "").partition(";")
            assert rest.strip().lower().startswith("url="), attrs
            self.refresh.append(rest.strip()[len("url="):])
        elif tag == "a":
            self.links.append(attrs.get("href") or "")
        elif tag == "script":
            self._script = attrs

    def handle_data(self, data):
        if self._script is not None:
            self.scripts.append((self._script, data))

    def handle_endtag(self, tag):
        if tag == "script":
            self._script = None


def _targets(copy_path: Path) -> _Targets:
    parser = _Targets()
    parser.feed(copy_path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def _assert_fragment_only(url: str, token: str) -> None:
    parts = urllib.parse.urlsplit(url)
    assert parts.query == "", f"the token's URL has a query: {url!r}"
    assert token not in parts.path and token not in parts.netloc, url
    assert urllib.parse.parse_qs(parts.fragment) == {"console_token": [token]}, url


# ---------------------------------------------------------------------------
# 1 — not on /capabilities, and no route serves it
# ---------------------------------------------------------------------------

def test_a_standalone_plane_carries_no_console_token_on_capabilities(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """The ruling's first clause. The token IS minted (the plane has its
    session capability, so the case is not vacuous), and `/capabilities`
    carries it under no key and in no byte of the body."""
    from opendox import console_access

    with _serving(tmp_path, monkeypatch) as (httpd, base, _repo):
        token = httpd.console_token
        assert token and httpd.console_token_delivery == console_access.DELIVERY_OPENED_URL
        status, headers, raw = _call(base, "GET", "/capabilities")
        assert status == 200, raw
        caps = json.loads(raw)
        assert caps["actions"]["session"] is True, caps
        assert "console_token" not in caps, caps
        assert token.encode() not in raw
        assert all(token not in str(value) for value in headers.values())


def test_a_hosts_plane_keeps_its_token_on_capabilities(
        tmp_path, monkeypatch) -> None:
    """The governed path, unchanged: a HOST's profile (this suite registers
    one, as openxFactory's `opendox_host.register_openxfactory()` does)
    publishes the token on `/capabilities` as its page and its suites read it,
    and the entry point writes no private copy for it."""
    from opendox import console_access, domain_profile

    assert domain_profile.current() is not None
    with _serving(tmp_path, monkeypatch) as (httpd, base, _repo):
        assert httpd.console_token_delivery == console_access.DELIVERY_CAPABILITIES
        status, _headers, raw = _call(base, "GET", "/capabilities")
        assert status == 200
        assert json.loads(raw)["console_token"] == httpd.console_token
        state = tmp_path / "host-state"
        assert console_access.publish(
            httpd, page_url="http://127.0.0.1:1/index.html",
            env={"OPENDOX_STATE_DIR": str(state)}) is None
        assert not state.exists(), "a host's plane wrote a private copy"


def _get_routes(repo: Path) -> list[str]:
    """Every GET a page, a script or another local user can send this plane:
    the whole served bundle, the core JSON routes, the document pass-through,
    and the guarded reads asked without the token."""
    bundle = sorted("/" + path.relative_to(WEB).as_posix()
                    for path in WEB.rglob("*") if path.is_file())
    document = next(path.name for path in sorted(repo.glob("*.md")))
    return ["/", *bundle, "/capabilities", "/snapshot.json",
            "/snapshot-index.json", "/project-register.json",
            f"/source/{document}", "/workbench/model-catalog",
            "/workbench/model-intake",
            "/workbench/thread?repository=fixture&ref=main&tile_kind=cluster"
            "&tile_id=x&document=" + document]


#: Every POST route a standalone plane serves, asked without the token.
_POST_ROUTES = ("/actions/workbench/chat-turn", "/actions/edit",
                "/actions/workbench/document-abstract",
                "/actions/workbench/model-approval",
                "/actions/workbench/model-intake", "/actions/session/submit",
                "/actions/notebook", "/actions/refresh")


def test_no_route_serves_the_token_to_another_local_user(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """"A second OS user cannot obtain the token", simulated twice over.
    FIRST, by asking: every GET and HEAD the plane answers, and every POST it
    serves without the token, and no response carries the token in its body or
    in any header. SECOND, by the copy: the one place the token is written is
    a regular file with no group or other permission bit, in a directory with
    none either, both this user's, so the kernel refuses any other non-root
    user's open of it, and this module's reader refuses a copy another user
    owns."""
    from opendox import console_access, serve

    with _serving(tmp_path, monkeypatch) as (httpd, base, repo):
        token = httpd.console_token
        assert token
        needle = token.encode()
        asked = 0
        for path in _get_routes(repo):
            for method in ("GET", "HEAD"):
                status, headers, raw = _call(base, method, path)
                asked += 1
                assert needle not in raw, f"{method} {path} served the token"
                assert all(token not in str(v) for v in headers.values()), path
        for path in _POST_ROUTES:
            status, headers, raw = _call(base, "POST", path, body=b"{}")
            asked += 1
            assert needle not in raw, f"POST {path} served the token"
            assert all(token not in str(v) for v in headers.values()), path
        assert asked > 80, asked
        # ...and the copy the entry point writes is this user's alone
        state = _state(tmp_path)
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
    for path, mode in ((copy.path, 0o600), (copy.path.parent, 0o700),
                       (state, 0o700)):
        info = os.lstat(path)
        assert stat.S_IMODE(info.st_mode) == mode, (path, oct(info.st_mode))
        assert info.st_uid == os.getuid(), path
    assert stat.S_ISREG(os.lstat(copy.path).st_mode)
    # A copy ANOTHER user owns, as this module's reader sees one: refused, at
    # the first directory of this user's that its walk passes through.
    real = os.getuid()
    monkeypatch.setattr(console_access.os, "getuid", lambda: real + 1)
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="not by this user|neither this user nor root"):
        console_access.read_private_copy(copy.path)


# ---------------------------------------------------------------------------
# 2 — the fragment, and only the fragment
# ---------------------------------------------------------------------------

def test_the_opened_url_carries_the_token_in_its_fragment_only(tmp_path) -> None:
    """The URL the page is opened at, and both of the copy's forwarding
    targets (the meta refresh a browser follows, and the link a person
    clicks): the token is the fragment's one value, and the query is empty,
    so no request line, server log or `Referer` can carry it."""
    from opendox import console_access

    token = _token()
    page = "http://127.0.0.1:8080/index.html"
    _assert_fragment_only(console_access.opened_url(page, token), token)
    copy = _write(_state(tmp_path), token=token, page_url=page)
    _assert_fragment_only(copy.opened_url, token)
    targets = _targets(copy.path)
    assert len(targets.refresh) == 1 and targets.links, targets.__dict__
    for url in (*targets.refresh, *targets.links):
        _assert_fragment_only(url, token)
    assert copy.file_url.startswith("file://") and token not in copy.file_url
    # a page URL that already has a query or a fragment is refused, so the
    # token's fragment is always the URL's only one
    for bad in (page + "?x=1", page + "#x", "https://127.0.0.1:8080/",
                "http://example.invalid:8080/index.html"):
        with pytest.raises(console_access.ConsoleAccessRefused):
            console_access.opened_url(bad, token)


def test_the_record_cannot_break_out_of_its_script_element(tmp_path) -> None:
    """The copy embeds a JSON record for a harness. A value that spells
    `</script>` or a tag is escaped, so the record ends where its element
    does, every attribute is quoted, and it reads back as written."""
    from opendox import console_access

    hostile = ("http://127.0.0.1:8080/</script><img src=x onerror=alert(1)>"
               "/'\"&amp;/index.html")
    token = _token()
    copy = _write(_state(tmp_path), token=token, page_url=hostile)
    text = copy.path.read_text(encoding="utf-8")
    assert text.count("</script>") == 1, text
    assert "<img" not in text and "onerror=alert(1)>" not in text, text
    targets = _targets(copy.path)
    (attrs, data), = targets.scripts
    assert attrs == {"type": "application/json", "id": console_access.RECORD_ELEMENT_ID}
    record = json.loads(data)
    assert record["page_url"] == hostile and record["console_token"] == token
    assert console_access.read_private_copy(copy.path) == record
    for url in (*targets.refresh, *targets.links):
        assert url == console_access.opened_url(hostile, token), url


def _generate_and_open_args(tmp_path: Path, repo: Path, *extra: str) -> argparse.Namespace:
    """A run that SERVES: a `--no-serve` run publishes no copy (adversarial
    review of openDox-code#84, B8), so every case built from these takes
    `stopped_once_serving` too, and never blocks in a serve loop."""
    from opendox import cli
    return cli.build_parser().parse_args([
        "generate-and-open", "--repo-root", str(repo), "--repository", "fixture",
        "--run-dir", str(tmp_path / "run"), "--port", "0", "--no-validate",
        *extra])


@pytest.fixture()
def stopped_once_serving(monkeypatch):
    """The serve loop, stopped as Ctrl-C stops it the moment it starts: what
    it lists is every server that reached it, so a refused start can show it
    never served."""
    reached: list[object] = []

    def serve_forever(self, *args, **kwargs):
        reached.append(self)
        raise KeyboardInterrupt

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", serve_forever)
    return reached


def test_generate_and_open_hands_the_browser_a_file_and_prints_no_token(
        tmp_path, monkeypatch, capsys, standalone_profile,
        stopped_once_serving) -> None:
    """What the entry point gives the browser is the copy's `file://` path:
    a URL handed to `webbrowser.open` sits on a command line every user can
    read. The copy it names opens the page with the token in the fragment.
    Nothing it prints carries the token. The copy goes when the run does."""
    from opendox import cli, console_access

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    opened: list[tuple[str, dict]] = []

    def opener(url):
        path = Path(urllib.parse.urlsplit(url).path)
        opened.append((url, console_access.read_private_copy(path)))

    assert cli._generate_and_open(_generate_and_open_args(tmp_path, repo),
                                  opener=opener) == 0
    out = capsys.readouterr().out
    (url, record), = opened
    token = record["console_token"]
    assert url.startswith("file://") and token not in url, url
    _assert_fragment_only(record["opened_url"], token)
    assert token not in out, "the token was printed"
    console_line = next(line for line in out.splitlines()
                        if line.startswith("  console "))
    assert url in console_line, console_line
    assert record["page_url"] in out.splitlines(), out
    assert not list((state / console_access.CONSOLE_DIRNAME).iterdir()), \
        "the copy outlived the run"
    assert len(stopped_once_serving) == 1, "the run never served"


def test_no_open_prints_the_copy_path_and_opens_nothing(
        tmp_path, monkeypatch, capsys, standalone_profile,
        stopped_once_serving) -> None:
    """`--no-open`: no browser, and the way back to the page is still printed,
    the copy's path, while the token is still never printed."""
    from opendox import cli

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(_state(tmp_path)))
    opened: list[str] = []
    assert cli._generate_and_open(
        _generate_and_open_args(tmp_path, repo, "--no-open"),
        opener=opened.append) == 0
    out = capsys.readouterr().out
    assert opened == []
    match = next(_CONSOLE.match(line) for line in out.splitlines()
                 if _CONSOLE.match(line))
    assert match.group(1).startswith("file://"), out
    assert "console_token=" not in out, out
    assert len(stopped_once_serving) == 1, "the run never served"


def test_generate_and_open_refuses_where_no_safe_copy_can_be_written(
        tmp_path, monkeypatch, capsys, standalone_profile,
        stopped_once_serving) -> None:
    """A state directory another user could change refuses the run before it
    serves, naming the directory; a console nobody can safely be handed is
    not served as if it could be."""
    from opendox import cli

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    state.chmod(0o770)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    opened: list[str] = []
    assert cli._generate_and_open(_generate_and_open_args(tmp_path, repo),
                                  opener=opened.append) == 1
    captured = capsys.readouterr()
    assert opened == []
    assert "generate-and-open refused:" in captured.err
    assert stopped_once_serving == [], "the refused run served"
    assert str(state) in captured.err and "writable by its group" in captured.err


# ---------------------------------------------------------------------------
# 3 — the private copy: planted, linked, loosened
# ---------------------------------------------------------------------------

def test_the_copy_is_born_0600_in_a_0700_tree_whatever_the_umask(tmp_path) -> None:
    from opendox import console_access

    state = tmp_path / "fresh" / "state"          # nothing exists yet
    previous = os.umask(0)
    try:
        copy = _write(state)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(os.lstat(copy.path).st_mode) == console_access.PRIVATE_MODE == 0o600
    for directory in (state, copy.path.parent):
        assert stat.S_IMODE(os.lstat(directory).st_mode) == 0o700, directory
    assert console_access.read_private_copy(copy.path)["port"] == 8080


def test_a_link_planted_at_the_copy_is_refused_and_never_followed(tmp_path) -> None:
    """Another user, or anyone, puts a link where the copy goes, pointing at a
    file they can read: the write refuses, the token goes nowhere, and a read
    through the link refuses too."""
    from opendox import console_access

    state = _state(tmp_path)
    console = state / console_access.CONSOLE_DIRNAME
    console.mkdir(mode=0o700)
    leak = tmp_path / "leak.html"
    leak.write_text("nothing yet\n", encoding="utf-8")
    planted = console_access.private_copy_path(state, 8080)
    planted.symlink_to(leak)
    token = _token()
    with pytest.raises(console_access.ConsoleAccessRefused, match="symbolic link"):
        _write(state, token=token)
    assert leak.read_text(encoding="utf-8") == "nothing yet\n"
    assert planted.is_symlink(), "the planted link was replaced, not refused"
    # a real copy elsewhere, linked in: a read refuses the link itself
    other = _write(_state(tmp_path / "other"))
    planted.unlink()
    planted.symlink_to(other.path)
    with pytest.raises(console_access.ConsoleAccessRefused, match="symbolic link"):
        console_access.read_private_copy(planted)


def test_a_dangling_link_planted_at_the_copy_creates_nothing(tmp_path) -> None:
    from opendox import console_access

    state = _state(tmp_path)
    (state / console_access.CONSOLE_DIRNAME).mkdir(mode=0o700)
    target = tmp_path / "would-be-created.html"
    console_access.private_copy_path(state, 8080).symlink_to(target)
    with pytest.raises(console_access.ConsoleAccessRefused):
        _write(state)
    assert not target.exists()


def test_a_hard_linked_copy_is_refused(tmp_path) -> None:
    from opendox import console_access

    state = _state(tmp_path)
    copy = _write(state)
    os.link(copy.path, tmp_path / "second-name.html")
    with pytest.raises(console_access.ConsoleAccessRefused, match="2 hard links"):
        console_access.read_private_copy(copy.path)
    with pytest.raises(console_access.ConsoleAccessRefused, match="2 hard links"):
        _write(state)


def test_a_loosened_copy_is_refused(tmp_path) -> None:
    from opendox import console_access

    copy = _write(_state(tmp_path))
    copy.path.chmod(0o644)
    with pytest.raises(console_access.ConsoleAccessRefused, match="mode 644"):
        console_access.read_private_copy(copy.path)


def test_a_planted_directory_or_file_at_the_copy_is_refused(tmp_path) -> None:
    from opendox import console_access

    state = _state(tmp_path)
    (state / console_access.CONSOLE_DIRNAME).mkdir(mode=0o700)
    console_access.private_copy_path(state, 8080).mkdir()
    with pytest.raises(console_access.ConsoleAccessRefused, match="not a regular file"):
        _write(state)


def test_a_linked_console_directory_is_refused(tmp_path) -> None:
    from opendox import console_access

    state = _state(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (state / console_access.CONSOLE_DIRNAME).symlink_to(elsewhere)
    with pytest.raises(console_access.ConsoleAccessRefused, match="symbolic link"):
        _write(state)
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("mode, reason", [(0o770, "writable by its group"),
                                          (0o707, "writable by every user")])
def test_a_state_directory_others_can_write_is_refused(tmp_path, mode, reason) -> None:
    from opendox import console_access

    state = _state(tmp_path)
    state.chmod(mode)
    with pytest.raises(console_access.ConsoleAccessRefused, match=reason):
        _write(state)
    assert not (state / console_access.CONSOLE_DIRNAME).exists()


def test_a_state_directory_below_a_non_sticky_shared_directory_is_refused(tmp_path) -> None:
    from opendox import console_access

    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    try:
        with pytest.raises(console_access.ConsoleAccessRefused, match="not sticky"):
            _write(shared / "state")
        shared.chmod(0o1777)                         # sticky, as /tmp is: accepted
        assert _write(shared / "state").path.exists()
    finally:
        shared.chmod(0o755)


def test_a_later_copy_replaces_this_users_earlier_one_and_removal_is_exact(
        tmp_path) -> None:
    """A server restarted on the same port, after the first ended without
    removing its copy, replaces that copy. The first server's removal, had it
    still run, leaves the later copy in place."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
    _abandon(first)                          # the first serve is gone
    second_token = _token()
    second = _write(state, token=second_token)
    assert first.path == second.path
    console_access.remove_private_copy(first)
    assert console_access.read_private_copy(second.path)["console_token"] == second_token
    console_access.remove_private_copy(second)
    assert not second.path.exists()
    console_access.remove_private_copy(second)      # already gone: no error
    console_access.remove_private_copy(None)


# ---------------------------------------------------------------------------
# 4 — the guarded routes still require it
# ---------------------------------------------------------------------------

def test_every_route_that_requires_the_token_still_requires_it(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """Only the delivery changed. Without the token, each guarded route
    refuses with its console refusal; with the token read from the private
    copy, the same request passes the console check."""
    from opendox import console_access, serve
    from opendox.serve_wire import DOXBENCH_ERR_CONSOLE_REQUIRED

    with _serving(tmp_path, monkeypatch) as (httpd, base, _repo):
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(_state(tmp_path))})
        token = console_access.read_private_copy(copy.path)["console_token"]
        assert token == httpd.console_token
        catalog = "/workbench/model-catalog"
        status, _h, raw = _call(base, "GET", catalog)
        assert json.loads(raw).get("error") == DOXBENCH_ERR_CONSOLE_REQUIRED, raw
        status, _h, raw = _call(base, "GET", catalog, token="x" * 43)
        assert json.loads(raw).get("error") == DOXBENCH_ERR_CONSOLE_REQUIRED, raw
        status, _h, raw = _call(base, "GET", catalog, token=token)
        assert json.loads(raw).get("error") != DOXBENCH_ERR_CONSOLE_REQUIRED, raw
        turn = "/actions/workbench/chat-turn"
        status, _h, raw = _call(base, "POST", turn, body=b"{}")
        assert json.loads(raw).get("error") == DOXBENCH_ERR_CONSOLE_REQUIRED, raw
        status, _h, raw = _call(base, "POST", turn, body=b"{}", token=token)
        assert json.loads(raw).get("error") != DOXBENCH_ERR_CONSOLE_REQUIRED, raw


def _stop(child: Child, signum: int) -> int:
    """Signal the child and wait for it, WITHOUT `Child.interrupt()`, whose
    `kill()` deletes the child's state directory and would hide a copy the
    child failed to remove (Copilot at openDox-code#84, r4173806621). The
    case's own `finally: child.kill()` cleans up afterwards."""
    import standalone_child

    child.process.send_signal(signum)
    return child.process.wait(timeout=standalone_child.STOP_DEADLINE_SECONDS)


# ---------------------------------------------------------------------------
# 5 — the documented command, as a user runs it
# ---------------------------------------------------------------------------

def test_the_documented_command_delivers_the_token_only_through_its_copy(
        tmp_path, monkeypatch) -> None:
    """`python -m opendox.cli generate-and-open --local --no-open`, in a
    process of its own (openDox's default profile, no host, no sibling): the
    console line names the copy, `/capabilities` carries no token, the copy's
    token opens the catalog, nothing printed carries it, and the copy goes
    when the server stops."""
    from opendox import console_access

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    child = Child(tmp_path, "opendox.cli", "generate-and-open", "--local",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--port", "0", "--run-dir", str(tmp_path / "run"))
    try:
        console = child.wait_for_line(_CONSOLE)
        match = child.wait_for_line(_URL)
        base, port = (match.group(2), int(match.group(3))), int(match.group(3))
        copy_path = console_access.private_copy_path(child.state_dir, port)
        assert console.group(1) == copy_path.as_uri(), console.group(0)
        token = child.console_token(port)
        status, _h, raw = _call(base, "GET", "/capabilities")
        assert status == 200 and "console_token" not in json.loads(raw)
        assert token.encode() not in raw
        status, _h, raw = _call(base, "GET", "/workbench/model-catalog", token=token)
        assert status == 200, raw
        # STOPPED, and looked at BEFORE `Child.kill()` deletes the state dir
        assert _stop(child, signal.SIGINT) == 0, child.stderr_text()
        assert not copy_path.exists(), "the copy outlived the server"
    finally:
        child.kill()
    assert token not in child.stdout_text() + child.stderr_text()
    assert child.refused() == [], child.refused()


_SERVE_URL = re.compile(r"^serving ideation dashboard at "
                        r"(http://([0-9.]+):([0-9]+))/index\.html$")
_SERVE_CONSOLE = re.compile(r"^console (file://\S+) ")


def test_the_servers_own_entry_point_delivers_the_token_the_same_way(
        tmp_path, monkeypatch) -> None:
    """`python -m opendox.serve`, the standalone secondary entry point: the
    same private copy, the same printed path, no token on `/capabilities` or
    on the output, and the copy gone when the server stops."""
    from opendox import console_access

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    child = Child(tmp_path, "opendox.serve", "--snapshot", str(snapshot),
                  "--checkout-root", str(repo), "--port", "0")
    try:
        console = child.wait_for_line(_SERVE_CONSOLE)
        match = child.wait_for_line(_SERVE_URL)
        base, port = (match.group(2), int(match.group(3))), int(match.group(3))
        copy_path = console_access.private_copy_path(child.state_dir, port)
        assert console.group(1) == copy_path.as_uri()
        token = child.console_token(port)
        status, _h, raw = _call(base, "GET", "/capabilities")
        assert status == 200 and token.encode() not in raw
        status, _h, raw = _call(base, "GET", "/workbench/model-catalog", token=token)
        assert json.loads(raw).get("error") != "console_required", raw
        assert _stop(child, signal.SIGINT) == 0, child.stderr_text()
        assert not copy_path.exists(), "the copy outlived the server"
    finally:
        child.kill()
    assert token not in child.stdout_text() + child.stderr_text()


def test_the_servers_own_entry_point_refuses_where_no_safe_copy_can_be_written(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
    from opendox import serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    state = _state(tmp_path)
    state.chmod(0o707)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)
    assert serve.main(["--snapshot", str(snapshot), "--checkout-root", str(repo),
                       "--port", "0"]) == 1
    err = capsys.readouterr().err
    assert "serve refused:" in err and "writable by every user" in err, err


# ---------------------------------------------------------------------------
# 6 — never inside what the plane serves
# ---------------------------------------------------------------------------

def _tree(path: Path) -> list[str]:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


@pytest.mark.parametrize("where", ["the served root", "under the served root"])
def test_a_state_directory_in_the_served_root_is_refused_before_any_write(
        tmp_path, where) -> None:
    """The holder's ruling on openxFactory#1220's review (Copilot
    `r4171166321`), mirroring T100's served-repository boundary: the token's
    copy must never sit inside what `/source` can serve. A state directory
    that IS a served root, or lies inside one (a declared source root
    included), is refused by name, and nothing is created or written."""
    from opendox import console_access

    served = tmp_path / "served"
    served.mkdir(mode=0o700)
    other = tmp_path / "other-source-root"
    other.mkdir(mode=0o700)
    before = (_tree(served), _tree(other))
    for root in (served, other):
        state = root if where == "the served root" else root / "nested" / "state"
        with pytest.raises(console_access.ConsoleAccessRefused) as refused:
            console_access.write_private_copy(
                state, page_url="http://127.0.0.1:8080/index.html", port=8080,
                token=_token(), served_roots=(served, other))
        message = str(refused.value)
        assert "OPENDOX_STATE_DIR" in message and str(root.resolve()) in message
        assert (("is the served repository" if where == "the served root"
                 else "lies inside the served repository") in message), message
    assert (_tree(served), _tree(other)) == before, "something was written"


def test_a_state_directory_reached_through_a_link_into_the_served_root_is_refused(
        tmp_path) -> None:
    """Judged on the RESOLVED path, so a link from outside that lands inside
    the served root is the served root."""
    from opendox import console_access

    served = tmp_path / "served"
    (served / "inside").mkdir(parents=True, mode=0o700)
    link = tmp_path / "looks-outside"
    link.symlink_to(served / "inside")
    with pytest.raises(console_access.ConsoleAccessRefused, match="inside the served"):
        console_access.write_private_copy(
            link / "state", page_url="http://127.0.0.1:8080/index.html",
            port=8080, token=_token(), served_roots=(served,))
    assert _tree(served / "inside") == []


def test_generate_and_open_refuses_a_state_directory_inside_the_served_repository(
        tmp_path, monkeypatch, capsys, standalone_profile,
        stopped_once_serving) -> None:
    """Through the entry point: `OPENDOX_STATE_DIR` inside the repository it
    serves refuses the run, naming the setting, and the repository gains no
    file."""
    from opendox import cli

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(repo / ".opendox-state"))
    before = _tree(repo)
    opened: list[str] = []
    assert cli._generate_and_open(_generate_and_open_args(tmp_path, repo),
                                  opener=opened.append) == 1
    err = capsys.readouterr().err
    assert opened == []
    assert "generate-and-open refused:" in err and "OPENDOX_STATE_DIR" in err
    assert stopped_once_serving == [], "the refused run served"
    assert "lies inside the served repository" in err, err
    assert _tree(repo) == before


def test_the_plane_reports_every_root_it_serves(tmp_path, monkeypatch,
                                                standalone_profile) -> None:
    """`publish` reads every root the plane serves files from (Copilot at
    openDox-code#84, r4173806506): the checkout, the static bundle's
    directory, each declared source root, each registry entry's root, and the
    sessions container every session worktree is made in."""
    from opendox import branch_session, serve

    with _serving(tmp_path, monkeypatch) as (httpd, _base, repo):
        sessions = branch_session.sessions_root(repo)
        assert httpd.served_roots[:2] == (repo.resolve(), WEB.resolve())
        assert sessions in httpd.served_roots
        entries = httpd.RequestHandlerClass.func.source.registry.entries()
        assert entries and all(Path(e.source_root).resolve() in httpd.served_roots
                               for e in entries if e.source_root)
        other = tmp_path / "other-source-root"
        other.mkdir()
        snapshot = tmp_path / "snapshot.json"
        declared = serve.build_server(WEB, snapshot, repo, port=0, quiet=True,
                                      source_roots={"other": str(other)})
        try:
            assert other.resolve() in declared.served_roots
            assert repo.resolve() in declared.served_roots
        finally:
            declared.server_close()


@pytest.mark.parametrize("inside", ["the static bundle", "the sessions container"])
def test_a_state_directory_in_another_served_root_is_refused_by_the_entry_point(
        tmp_path, monkeypatch, standalone_profile, inside) -> None:
    """The static handler serves every file under `--web-dir`, and `/source`
    serves every session worktree, so a copy there would be served to anyone
    who asks, its 0600 notwithstanding: the server reads it as its owner.
    `publish` refuses both, before anything is written."""
    import shutil as _shutil

    from opendox import branch_session, console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(web, snapshot, repo, port=0, quiet=True)
    try:
        assert httpd.console_token
        state = (web / "state" if inside == "the static bundle"
                 else branch_session.sessions_root(repo) / "state")
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="lies inside the served repository"):
            console_access.publish(
                httpd, page_url=serve.server_url(httpd, "/index.html"),
                env={"OPENDOX_STATE_DIR": str(state)})
        assert not state.exists(), "something was written"
    finally:
        httpd.server_close()


# ---------------------------------------------------------------------------
# 7 — the copy's removal: exact under a race, and on a plain kill
# ---------------------------------------------------------------------------

def test_a_replacement_written_while_the_old_copy_is_removed_survives(
        tmp_path, monkeypatch) -> None:
    """Copilot at openDox-code#84, r4173806552. A replacement serve publishes
    its copy for the same port at the instant the old serve removes its own:
    the old serve takes the NAME first (an atomic rename), finds a file that
    is not its own, and puts it back. The replacement's copy stands, whole."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
    second_token = _token()
    real_rename = os.rename
    raced: list = []

    def racing(src, dst, *args, **kwargs):
        if src == first.path.name and not raced:
            raced.append(_publish_concurrently(state, second_token))
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(console_access.os, "rename", racing)
    console_access.remove_private_copy(first)
    monkeypatch.undo()
    assert raced, "the race was never staged"
    second = _settle(raced[0])
    record = console_access.read_private_copy(first.path)
    assert record["console_token"] == second_token
    assert sorted(p.name for p in first.path.parent.iterdir()) == [first.path.name]
    console_access.remove_private_copy(second)
    assert not first.path.exists()


def test_terminate_as_interrupt_reads_sigterm_as_ctrl_c_and_restores_the_handler(
        ) -> None:
    from opendox import console_access

    def sentinel(signum, frame):
        raise AssertionError("the previous handler ran")

    previous = signal.signal(signal.SIGTERM, sentinel)
    try:
        with pytest.raises(KeyboardInterrupt):
            with console_access.terminate_as_interrupt(True):
                os.kill(os.getpid(), signal.SIGTERM)
                signal.pthread_sigmask(signal.SIG_BLOCK, [])   # deliver now
        assert signal.getsignal(signal.SIGTERM) is sentinel
        with console_access.terminate_as_interrupt(False):
            assert signal.getsignal(signal.SIGTERM) is sentinel
    finally:
        signal.signal(signal.SIGTERM, previous)


_HOSTED = {
    "OPENDOX_INSTALL_MODE": "hosted",
    "OPENDOX_DATABASE_URL": "postgresql://serve@127.0.0.1:1/opendox",
    "OPENDOX_MIGRATION_DATABASE_URL": "postgresql://migrate@127.0.0.1:1/opendox",
    "OPENDOX_OIDC_AUDIENCE": "fixture",
    "OPENDOX_OIDC_ISSUER": "https://issuer.example.invalid/realms/fixture",
}


@pytest.mark.parametrize("entry", ["serve", "generate-and-open --local",
                                   "generate-and-open, hosted"])
def test_a_plain_kill_removes_the_copy(tmp_path, monkeypatch, entry) -> None:
    """Copilot at openDox-code#84, r4173806590. SIGTERM, which `kill` sends,
    stops every standalone entry point through the code that removes its
    copy, and the copy is looked for BEFORE the helper deletes the state
    directory. Each exits 0, as Ctrl-C does."""
    from opendox import console_access

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    if entry == "serve":
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
        child = Child(tmp_path, "opendox.serve", "--snapshot", str(snapshot),
                      "--checkout-root", str(repo), "--port", "0")
        url = _SERVE_URL
    else:
        local = ["--local"] if entry.endswith("--local") else []
        child = Child(tmp_path, "opendox.cli", "generate-and-open", *local,
                      "--repo-root", str(repo), "--repository", "fixture",
                      "--no-open", "--port", "0", "--run-dir", str(tmp_path / "run"),
                      extra_env=None if local else _HOSTED)
        url = _URL
    try:
        match = child.wait_for_line(url)
        port = int(match.group(3))
        copy_path = console_access.private_copy_path(child.state_dir, port)
        assert copy_path.exists(), child.stdout_text() + child.stderr_text()
        assert _stop(child, signal.SIGTERM) == 0, child.stderr_text()
        assert not copy_path.exists(), "a plain kill left the token's copy behind"
        assert "Traceback" not in child.stderr_text(), child.stderr_text()
    finally:
        child.kill()


# ---------------------------------------------------------------------------
# 8 — the static handler never serves a private copy (Copilot review 2)
# ---------------------------------------------------------------------------

def test_a_served_root_equal_to_the_console_directory_is_refused(tmp_path) -> None:
    """Copilot at openDox-code#84, r4173889265. The state directory is outside
    every served root, but the static bundle IS its `console/` directory, so
    the copy would be `GET /<port>.html`. The copy's own path is judged
    against the served roots, so this is refused by name before anything is
    written."""
    from opendox import console_access

    state = _state(tmp_path)
    console = state / console_access.CONSOLE_DIRNAME
    console.mkdir(mode=0o700)
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="OPENDOX_STATE_DIR") as refused:
        console_access.write_private_copy(
            state, page_url="http://127.0.0.1:8080/index.html", port=8080,
            token=_token(), served_roots=(console,))
    assert str(console.resolve()) in str(refused.value)
    assert list(console.iterdir()) == [], "something was written"


def test_a_static_link_out_of_the_bundle_never_serves_a_private_copy(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """Copilot at openDox-code#84, r4173889294. The static handler follows a
    link inside `--web-dir` (a governed host's composed web root is MADE of
    such links, so they cannot be refused wholesale). A link that leads into
    the state directory must still never serve a copy: every static request
    whose resolved target is the private-copy directory, or inside it, is
    answered 404, for GET and HEAD, the copy, the directory listing, and
    another port's copy alike. The bundle itself still answers."""
    import shutil as _shutil

    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state = _state(tmp_path)
    (web / "state-alias").symlink_to(state)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(web, snapshot, repo, port=0, quiet=True)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        other = _write(state, port=9, token=_token())    # another serve's copy
        token = httpd.console_token
        for path in (f"/state-alias/console/{copy.path.name}",
                     f"/state-alias/console/{other.path.name}",
                     "/state-alias/console/", "/state-alias/console"):
            for method in ("GET", "HEAD"):
                status, headers, raw = _call(base, method, path)
                assert status == 404, (method, path, status)
                assert token.encode() not in raw and copy.path.name.encode() not in raw
                assert all(token not in str(v) for v in headers.values())
        status, _headers, raw = _call(base, "GET", "/index.html")
        assert status == 200 and b"<html" in raw.lower()
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


# ---------------------------------------------------------------------------
# 9 — no overlap in EITHER direction (the holder's ruling on batch N's
#     Copilot r4174345203)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("inside", ["console", "postgres/run", "anything/else/deep",
                                    "."])
def test_a_served_root_inside_the_state_directory_is_refused(tmp_path, inside) -> None:
    """The REVERSE nesting. A served root that IS, or lies inside, the state
    directory (`<state>/console` itself, the bundle's socket tree, anything)
    would let the plane serve the state directory's contents, the copy among
    them. The state directory and every served root may not overlap in either
    direction: refused by name, before anything is written."""
    from opendox import console_access

    state = _state(tmp_path)
    served = (state / inside).resolve() if inside != "." else state.resolve()
    served.mkdir(parents=True, exist_ok=True, mode=0o700)
    before = _tree(state)
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="OPENDOX_STATE_DIR") as refused:
        console_access.write_private_copy(
            state, page_url="http://127.0.0.1:8080/index.html", port=8080,
            token=_token(), served_roots=(served,))
    assert str(served) in str(refused.value), str(refused.value)
    assert _tree(state) == before, "something was written"


def test_a_source_link_into_the_state_directory_never_serves_the_copy(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """Pinned: `/source` confines every path to its root AFTER resolving links
    (`default_registry.resolve_within`), so a link inside the served checkout
    that points at the state directory reaches nothing in it. The copy, its
    directory and the state directory itself answer 404, unkeyed and keyed,
    for GET and HEAD, and no answer carries the token."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    (repo / "state-link").symlink_to(state)
    (repo / "copy-link.md").symlink_to(
        console_access.private_copy_path(state, 1))      # dangling until written
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(WEB, snapshot, repo, port=0, quiet=True)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        _write(state, port=1)                              # copy-link.md now resolves
        token = httpd.console_token
        name = copy.path.name
        for tail in (f"state-link/console/{name}", "state-link/console/1.html",
                     "copy-link.md", "state-link/console/", "state-link/"):
            for prefix in ("/source/", "/source/fixture@main/"):
                for method in ("GET", "HEAD"):
                    status, headers, raw = _call(base, method, prefix + tail)
                    assert status == 404, (method, prefix + tail, status, raw[:200])
                    assert token.encode() not in raw
                    assert all(token not in str(v) for v in headers.values())
        document = next(p.name for p in sorted(repo.glob("*.md")) if not p.is_symlink())
        status, _headers, raw = _call(base, "GET", f"/source/{document}")
        assert status == 200 and raw == (repo / document).read_bytes()
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


# ---------------------------------------------------------------------------
# 10 — Copilot review 4: a directory's index page, and a FIFO at the copy
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("index", ["index.html", "index.htm"])
def test_a_directory_index_linked_to_a_private_copy_is_never_served(
        tmp_path, monkeypatch, standalone_profile, index) -> None:
    """Copilot at openDox-code#84, r4174674625. For a directory request the
    stdlib handler serves the directory's first index page that exists
    (`index.html`, then `index.htm`), so judging only the directory let
    `GET /sub/` serve `web/sub/<index>`, a link to the console token's copy,
    while `/sub/<index>` itself answered 404. The index page the handler
    would serve is judged too: GET and HEAD of the directory answer 404, the
    redirect of the bare name carries nothing, and no answer carries the
    token. A directory whose index page is the bundle's own still serves it."""
    import shutil as _shutil

    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    (web / "sub").mkdir()
    (web / "plain").mkdir()
    (web / "plain" / index).write_text("<html>plain index</html>", encoding="utf-8")
    state = _state(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(web, snapshot, repo, port=0, quiet=True)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        (web / "sub" / index).symlink_to(copy.path)
        token = httpd.console_token
        for path in ("/sub/", f"/sub/{index}", "/sub/?x=1"):
            for method in ("GET", "HEAD"):
                status, headers, raw = _call(base, method, path)
                assert status == 404, (method, path, status)
                assert token.encode() not in raw
                assert all(token not in str(v) for v in headers.values())
        status, headers, raw = _call(base, "GET", "/sub")
        assert status != 200, status
        assert token.encode() not in raw
        assert all(token not in str(v) for v in headers.values())
        for method in ("GET", "HEAD"):
            status, _headers, raw = _call(base, method, "/plain/")
            assert status == 200, (method, status)
        assert b"plain index" in _call(base, "GET", "/plain/")[2]
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_a_fifo_at_the_copy_is_refused_without_blocking(tmp_path) -> None:
    """Copilot at openDox-code#84, r4174674702. A FIFO planted at
    `console/<port>.html`, with no writer, blocked a read in its `open`
    before the descriptor's regular-file check could run, so the reader
    hung instead of refusing. The read opens without blocking and refuses it
    as not a regular file. A write refuses it too, by its name, and neither
    ever waits on it."""
    from opendox import console_access

    state = _state(tmp_path)
    (state / console_access.CONSOLE_DIRNAME).mkdir(mode=0o700)
    fifo = console_access.private_copy_path(state, 8080)
    os.mkfifo(fifo, 0o600)
    outcome: dict = {}

    def attempt(name, call) -> None:
        try:
            call()
        except BaseException as exc:  # noqa: BLE001 — judged below
            outcome[name] = exc
        else:
            outcome[name] = None

    for name, call in (("read", lambda: console_access.read_private_copy(fifo)),
                       ("write", lambda: _write(state))):
        worker = threading.Thread(target=attempt, args=(name, call), daemon=True)
        worker.start()
        worker.join(timeout=10)
        if worker.is_alive():
            # Release the blocked open, so the case fails rather than hangs.
            with contextlib.suppress(OSError):
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
            worker.join(timeout=10)
            pytest.fail(f"the {name} blocked on a FIFO at {fifo}")
        assert isinstance(outcome[name], console_access.ConsoleAccessRefused), (
            name, outcome[name])
        assert "not a regular file" in str(outcome[name]), str(outcome[name])
    assert stat.S_ISFIFO(os.lstat(fifo).st_mode), "the FIFO was replaced"


# ---------------------------------------------------------------------------
# 11 — #1144 12.4a as amended by T007 batch N (openxFactory#1222, landed
#      bdd0f586), clause by clause, and the opener file's lifecycle
# ---------------------------------------------------------------------------

def _publish_concurrently(state: Path, token: str, port: int = 8080) -> dict:
    """Publish a copy from ANOTHER thread, as another serve would, and give it
    time to finish or to wait on the console directory's lock."""
    import time

    outcome: dict = {}

    def publish() -> None:
        try:
            outcome["copy"] = _write(state, port=port, token=token)
        except BaseException as exc:  # noqa: BLE001 — judged by `_settle`
            outcome["error"] = exc

    outcome["thread"] = threading.Thread(target=publish, daemon=True)
    outcome["thread"].start()
    time.sleep(0.5)
    return outcome


def _settle(outcome: dict):
    outcome["thread"].join(timeout=30)
    assert not outcome["thread"].is_alive(), "the concurrent publication never finished"
    assert "error" not in outcome, outcome.get("error")
    return outcome["copy"]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


#: What 12.4a says may be at the copy's path, other than an earlier copy of
#: this user's, and the reason each is refused by.
_PLANTED = {
    "a symbolic link": "is a symbolic link",
    "a directory": "is not a regular file",
    "a FIFO": "is not a regular file",
    "a hard-linked copy": "has 2 hard links",
    "a loosened copy": "has mode 644, not 600",
}


def _plant(state: Path, port: int, kind: str, tmp_path: Path) -> Path:
    from opendox import console_access

    (state / console_access.CONSOLE_DIRNAME).mkdir(mode=0o700, exist_ok=True)
    path = console_access.private_copy_path(state, port)
    if kind == "a symbolic link":
        bait = tmp_path / "bait.html"
        bait.write_text("bait\n", encoding="utf-8")
        path.symlink_to(bait)
    elif kind == "a directory":
        path.mkdir()
    elif kind == "a FIFO":
        os.mkfifo(path, 0o600)
    else:
        written = _write(state, port=port)
        if kind == "a hard-linked copy":
            os.link(written.path, tmp_path / "second-name.html")
        else:
            written.path.chmod(0o644)
    return path


def _fingerprint(path: Path) -> tuple:
    info = os.lstat(path)
    return (stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_ino,
            info.st_nlink, os.readlink(path) if stat.S_ISLNK(info.st_mode) else None)


def _port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def test_a_loosened_own_copy_is_refused_by_the_writer_and_left_as_it_is(
        tmp_path) -> None:
    """12.4a: a file at the copy's path is replaced ONLY when it is this
    user's own regular file of mode 0600 with one link. A loosened one is
    refused by name, never replaced (batch N's gap (a) at `c979747a`: the
    writer asked for the type, the owner and the link count, not the mode)."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
    first.path.chmod(0o644)
    before = (first.path.read_bytes(), _fingerprint(first.path))
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="has mode 644, not 600") as refused:
        _write(state)
    assert str(first.path) in str(refused.value)
    assert (first.path.read_bytes(), _fingerprint(first.path)) == before


def test_another_users_file_at_the_copy_is_refused_by_the_writer(
        tmp_path, monkeypatch) -> None:
    """12.4a: another user's file at the copy's path refuses the write by
    name and is never replaced. Simulated through the writer's own `stat` of
    that name, so the tree above it is still this user's."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
    before = (first.path.read_bytes(), _fingerprint(first.path))
    real_stat = os.stat

    def foreign(path, *args, **kwargs):
        info = real_stat(path, *args, **kwargs)
        if path == first.path.name and kwargs.get("dir_fd") is not None:
            values = list(info[:10])
            values[4] = info.st_uid + 1                    # st_uid
            return os.stat_result(values)
        return info

    monkeypatch.setattr(console_access.os, "stat", foreign)
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="not by this user"):
        _write(state)
    monkeypatch.undo()
    assert (first.path.read_bytes(), _fingerprint(first.path)) == before


@pytest.mark.parametrize("kind", sorted(_PLANTED))
def test_generate_and_open_refuses_by_name_what_was_planted_at_the_copy(
        tmp_path, monkeypatch, capsys, standalone_profile,
        stopped_once_serving, kind) -> None:
    """12.4a, through the entry point: anything at the copy's path but an
    earlier copy of this user's refuses the START by name. Nothing is printed
    that serves, no browser is opened, the planted thing is untouched, and the
    listening socket is closed, so the server never serves."""
    from opendox import cli

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    port = _free_port()
    planted = _plant(state, port, kind, tmp_path)
    before = _fingerprint(planted)
    opened: list[str] = []
    assert cli._generate_and_open(
        _generate_and_open_args(tmp_path, repo, "--port", str(port)),
        opener=opened.append) == 1
    out, err = capsys.readouterr()
    assert opened == []
    assert "generate-and-open refused:" in err, err
    assert stopped_once_serving == [], "the refused run served"
    assert str(planted) in err and _PLANTED[kind] in err, err
    assert "  console " not in out and f":{port}/" not in out, out
    assert _fingerprint(planted) == before
    assert _port_is_free(port), "the refused start kept its socket"


@pytest.mark.parametrize("kind", sorted(_PLANTED))
def test_the_servers_own_entry_point_refuses_by_name_what_was_planted_at_the_copy(
        tmp_path, monkeypatch, capsys, standalone_profile, kind) -> None:
    """The same, through `python -m opendox.serve`'s `main`. A start that
    did not refuse would serve: the serve loop here fails the case instead of
    blocking it."""
    from opendox import serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)

    def served(self, *args, **kwargs):
        raise AssertionError("the server served")

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    port = _free_port()
    planted = _plant(state, port, kind, tmp_path)
    before = _fingerprint(planted)
    assert serve.main(["--snapshot", str(snapshot), "--checkout-root", str(repo),
                       "--port", str(port)]) == 1
    out, err = capsys.readouterr()
    assert "serve refused:" in err and str(planted) in err, err
    assert _PLANTED[kind] in err, err
    assert "serving ideation dashboard at" not in out, out
    assert _fingerprint(planted) == before
    assert _port_is_free(port), "the refused start kept its socket"


@pytest.mark.parametrize("inside", ["console", "postgres/run", "."])
def test_a_served_root_that_is_a_link_into_the_state_directory_is_refused(
        tmp_path, inside) -> None:
    """Batch N's gap (e): a served root named through a SYMBOLIC LINK that
    leads to the state directory, or into it, is judged where it leads. It
    is refused by name, and nothing is written."""
    from opendox import console_access

    state = _state(tmp_path)
    target = state if inside == "." else state / inside
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    alias = tmp_path / "served-alias"
    alias.symlink_to(target)
    before = _tree(state)
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="OPENDOX_STATE_DIR") as refused:
        console_access.write_private_copy(
            state, page_url="http://127.0.0.1:8080/index.html", port=8080,
            token=_token(), served_roots=(alias,))
    assert str(target.resolve()) in str(refused.value), str(refused.value)
    assert _tree(state) == before, "something was written"


def test_the_servers_own_entry_point_refuses_a_bundle_linked_into_the_state_directory(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
    """The same, through the entry point: `--web-dir` names a link that leads
    to `<state_dir>/console`. The start is refused by name, and the static
    handler never serves the directory the copies live in."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    state = _state(tmp_path)
    console = state / console_access.CONSOLE_DIRNAME
    console.mkdir(mode=0o700)
    alias = tmp_path / "web-alias"
    alias.symlink_to(console)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)

    def served(self, *args, **kwargs):
        raise AssertionError("the server served")

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    assert serve.main(["--web-dir", str(alias), "--snapshot", str(snapshot),
                       "--checkout-root", str(repo), "--port", "0"]) == 1
    err = capsys.readouterr().err
    assert "serve refused:" in err and str(console.resolve()) in err, err
    assert list(console.iterdir()) == []


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o711])
def test_a_console_directory_that_is_not_0700_is_refused(tmp_path, mode) -> None:
    """12.4a: the copy is mode 0600 "in a directory of mode 0700". A
    `console/` directory loosened after it was made, even where no one else
    can write it, is refused by name by the reader and by the writer, and the
    copy in it is left as it is."""
    from opendox import console_access

    state = _state(tmp_path)
    copy = _write(state)
    copy.path.parent.chmod(mode)
    try:
        expected = f"has mode {mode:o}, not 700"
        with pytest.raises(console_access.ConsoleAccessRefused, match=expected):
            console_access.read_private_copy(copy.path)
        with pytest.raises(console_access.ConsoleAccessRefused, match=expected):
            _write(state)
        assert copy.path.exists()
    finally:
        copy.path.parent.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write any directory")
def test_a_copy_that_cannot_be_written_refuses_the_start_by_name(
        tmp_path, monkeypatch, capsys, standalone_profile,
        stopped_once_serving) -> None:
    """The lifecycle self-pass: a state directory its parent will not let
    this user make (an operating-system refusal, not a rule of this module)
    used to escape as a raw `PermissionError`, a traceback and no refusal.
    It refuses by name, through the writer and through the entry point."""
    from opendox import cli, console_access

    locked = tmp_path / "locked"
    locked.mkdir(mode=0o700)
    locked.chmod(0o500)
    try:
        state = locked / "state"
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="cannot be written") as refused:
            _write(state)
        assert str(console_access.private_copy_path(state, 8080)) in str(refused.value)
        _clean_git(monkeypatch)
        repo = _repository(tmp_path)
        monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
        opened: list[str] = []
        assert cli._generate_and_open(_generate_and_open_args(tmp_path, repo),
                                      opener=opened.append) == 1
        err = capsys.readouterr().err
        assert opened == []
        assert "generate-and-open refused:" in err and "cannot be written" in err, err
        assert stopped_once_serving == [], "the refused run served"
        assert not state.exists()
    finally:
        locked.chmod(0o700)


def test_a_copy_that_fails_its_own_read_back_is_not_left_behind(
        tmp_path, monkeypatch) -> None:
    """The lifecycle self-pass: the writer reads back what it wrote, as any
    reader would, and refuses on a failure. The copy it wrote then goes with
    the refusal, rather than outliving a start that never served."""
    from opendox import console_access

    state = _state(tmp_path)

    def refusing(path):
        raise console_access.ConsoleAccessRefused("staged: the read-back refused")

    monkeypatch.setattr(console_access, "read_private_copy", refusing)
    with pytest.raises(console_access.ConsoleAccessRefused, match="staged"):
        _write(state)
    monkeypatch.undo()
    assert list((state / console_access.CONSOLE_DIRNAME).iterdir()) == []


def test_another_serves_copy_survives_a_removal_where_hard_links_fail(
        tmp_path, monkeypatch) -> None:
    """The lifecycle self-pass, on removal: the name is taken and judged, and
    another serve's copy is put back. Putting it back by a hard link fails on
    a filesystem without them (EPERM), and that used to DELETE the other
    serve's copy. It is put back by renaming it, where the name is free."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
    _abandon(first)                          # its reservation lost
    second_token = _token()
    second = _write(state, token=second_token)   # another serve's, over the first

    def no_hard_links(*args, **kwargs):
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(console_access.os, "link", no_hard_links)
    console_access.remove_private_copy(first)
    monkeypatch.undo()
    assert console_access.read_private_copy(first.path)["console_token"] == second_token
    assert sorted(p.name for p in first.path.parent.iterdir()) == [first.path.name]


def test_terminate_as_interrupt_reads_a_hangup_as_ctrl_c_unless_it_is_ignored(
        ) -> None:
    """The lifecycle self-pass, on stopping: closing the terminal sends
    SIGHUP, whose default action ends the process without removing the copy.
    While a copy exists, SIGHUP is read as Ctrl-C, as SIGTERM is. A SIGHUP
    the process was started ignoring (`nohup`) stays ignored."""
    from opendox import console_access

    previous = signal.signal(signal.SIGHUP, signal.SIG_DFL)
    try:
        with pytest.raises(KeyboardInterrupt):
            with console_access.terminate_as_interrupt(True):
                # never deliver a hangup that would END this test process
                assert signal.getsignal(signal.SIGHUP) not in (
                    signal.SIG_DFL, signal.SIG_IGN), "no hangup handler"
                os.kill(os.getpid(), signal.SIGHUP)
                signal.pthread_sigmask(signal.SIG_BLOCK, [])   # deliver now
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_DFL
        signal.signal(signal.SIGHUP, signal.SIG_IGN)            # as `nohup` starts it
        with console_access.terminate_as_interrupt(True):
            assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
        assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
    finally:
        signal.signal(signal.SIGHUP, previous)


@pytest.mark.parametrize("entry", ["serve", "generate-and-open --local",
                                   "generate-and-open, hosted"])
def test_a_hangup_removes_the_copy(tmp_path, monkeypatch, entry) -> None:
    """SIGHUP, as a closed terminal sends it, stops every standalone entry
    point through the code that removes its copy, and each exits 0.

    The child is started with SIGHUP at its DEFAULT action, whatever this
    runner inherited: an ignored signal stays ignored across `exec`, so a
    suite run under `nohup` would hand every child an ignored SIGHUP, which
    the entry points rightly keep ignoring."""
    from opendox import console_access

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    inherited = signal.signal(signal.SIGHUP, signal.SIG_DFL)
    try:
        if entry == "serve":
            snapshot = tmp_path / "snapshot.json"
            snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
            child = Child(tmp_path, "opendox.serve", "--snapshot", str(snapshot),
                          "--checkout-root", str(repo), "--port", "0")
            url = _SERVE_URL
        else:
            local = ["--local"] if entry.endswith("--local") else []
            child = Child(tmp_path, "opendox.cli", "generate-and-open", *local,
                          "--repo-root", str(repo), "--repository", "fixture",
                          "--no-open", "--port", "0",
                          "--run-dir", str(tmp_path / "run"),
                          extra_env=None if local else _HOSTED)
            url = _URL
    finally:
        signal.signal(signal.SIGHUP, inherited)
    try:
        match = child.wait_for_line(url)
        copy_path = console_access.private_copy_path(child.state_dir,
                                                     int(match.group(3)))
        assert copy_path.exists(), child.stdout_text() + child.stderr_text()
        assert _stop(child, signal.SIGHUP) == 0, child.stderr_text()
        assert not copy_path.exists(), "a hangup left the token's copy behind"
        assert "Traceback" not in child.stderr_text(), child.stderr_text()
    finally:
        child.kill()


@pytest.mark.parametrize("local", [False, True], ids=["hosted", "--local"])
def test_a_kill_while_the_browser_opens_removes_the_copy(
        tmp_path, monkeypatch, local) -> None:
    """The lifecycle self-pass: the copy exists from the moment it is
    written, and the browser opener can take seconds. A SIGTERM then, before
    the serve loop, used to take SIGTERM's default action on a hosted
    standalone plane, ending the process with the copy left behind. The
    window from the write to the stop is covered whole. Here the browser
    (`BROWSER`, a script) kills its own parent while it opens."""
    import standalone_child
    from opendox import console_access

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    browser = tmp_path / "kill-the-opener"
    browser.write_text('#!/bin/sh\nkill -TERM "$PPID"\n', encoding="utf-8")
    browser.chmod(0o700)
    env = {"BROWSER": str(browser), **({} if local else _HOSTED)}
    child = Child(tmp_path, "opendox.cli", "generate-and-open",
                  *(["--local"] if local else []),
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--port", "0", "--run-dir", str(tmp_path / "run"), extra_env=env)
    try:
        match = child.wait_for_line(_URL)
        copy_path = console_access.private_copy_path(child.state_dir,
                                                     int(match.group(3)))
        code = child.process.wait(timeout=standalone_child.STOP_DEADLINE_SECONDS)
        assert code == 0, (code, child.stderr_text())
        assert not copy_path.exists(), "a kill while the browser opened left the copy"
        assert "Traceback" not in child.stderr_text(), child.stderr_text()
    finally:
        child.kill()


def test_a_console_directory_with_a_setgid_bit_is_still_0700(tmp_path) -> None:
    """Only the permission bits are judged: a directory made under a setgid
    parent inherits the setgid bit, which grants no one access, so a
    `console/` of mode 2700 is accepted by the writer and the reader alike."""
    from opendox import console_access

    state = _state(tmp_path)
    copy = _write(state)
    copy.path.parent.chmod(0o2700)
    if not os.lstat(copy.path.parent).st_mode & stat.S_ISGID:
        pytest.skip("this filesystem keeps no setgid bit on a directory")
    assert console_access.read_private_copy(copy.path)["port"] == 8080
    _abandon(copy)
    assert _write(state).path == copy.path


def test_a_write_that_fails_part_way_leaves_no_partial_copy(
        tmp_path, monkeypatch) -> None:
    """The lifecycle self-pass, on writing: the copy is written under a
    temporary name and renamed into place. A failure part way (here the
    disk is full at the `fsync`) refuses by name and removes the temporary
    file, so nothing partial is left beside the name."""
    from opendox import console_access

    state = _state(tmp_path)

    def full(handle):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(console_access.os, "fsync", full)
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="cannot be written.*No space left on device"):
        _write(state)
    monkeypatch.undo()
    assert list((state / console_access.CONSOLE_DIRNAME).iterdir()) == []


# ---------------------------------------------------------------------------
# 12 — the state directory is walked ONCE, every link and directory on the
#      way judged, and the write is anchored to that walk (Copilot at
#      openDox-code#84, r4174785933)
# ---------------------------------------------------------------------------

def _hop_layout(tmp_path: Path, shared_mode: int) -> dict:
    """Copilot's layout: `OPENDOX_STATE_DIR=alias/state`, `alias ->
    shared/hop`, `hop -> private`. Only `alias` is on the configured path;
    `shared` is passed through by way of a link's target."""
    shared = tmp_path / "shared"
    shared.mkdir()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    served = tmp_path / "served"
    served.mkdir(mode=0o700)
    (shared / "hop").symlink_to(private)
    (tmp_path / "alias").symlink_to(shared / "hop")
    shared.chmod(shared_mode)
    return {"shared": shared, "private": private, "served": served,
            "hop": shared / "hop", "state": tmp_path / "alias" / "state"}


def test_a_directory_passed_through_by_an_intermediate_link_is_judged(
        tmp_path) -> None:
    """`shared` is neither on the configured path nor above the resolved
    one, and it was never judged: mode 0777 and not sticky, so another user
    could replace `hop`. It is judged now, as every directory the walk passes
    through is, and the write and the read are both refused by name."""
    from opendox import console_access

    layout = _hop_layout(tmp_path, 0o777)
    try:
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="writable by every user and is not sticky") as refused:
            _write(layout["state"])
        assert str(layout["shared"]) in str(refused.value), str(refused.value)
        assert _tree(layout["private"]) == [], "something was written"
        # a copy that is there already is refused when read through that way
        written = _write(layout["private"] / "state")
        through = layout["state"] / console_access.CONSOLE_DIRNAME / written.path.name
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="writable by every user and is not sticky"):
            console_access.read_private_copy(through)
    finally:
        layout["shared"].chmod(0o755)


def test_a_link_swapped_after_the_checks_never_redirects_the_write(
        tmp_path, monkeypatch) -> None:
    """The race: `hop` is pointed at a served root after the served-root
    check, and the write used to walk the configured path AGAIN, so the
    token's copy landed in the served root, where `/source` serves it. The
    path is walked once, and the write is anchored to that walk: the copy
    is where the checks saw the state directory, and the served root gains
    nothing."""
    from opendox import console_access

    layout = _hop_layout(tmp_path, 0o755)
    real = console_access._refuse_a_served_state_dir

    def then_swap(*args, **kwargs):
        real(*args, **kwargs)
        layout["hop"].unlink()
        layout["hop"].symlink_to(layout["served"])

    monkeypatch.setattr(console_access, "_refuse_a_served_state_dir", then_swap)
    copy = console_access.write_private_copy(
        layout["state"], page_url="http://127.0.0.1:8080/index.html", port=8080,
        token=_token(), served_roots=(layout["served"],))
    monkeypatch.undo()
    assert _tree(layout["served"]) == [], "the swapped link redirected the write"
    expected = (layout["private"] / "state").resolve()
    assert copy.path == console_access.private_copy_path(expected, 8080)
    assert console_access.read_private_copy(copy.path)["port"] == 8080


# ---------------------------------------------------------------------------
# 13 — Copilot's review at 182cac76: the snapshot files are served roots;
#      publication and removal are serialized; a stop during publication
# ---------------------------------------------------------------------------

def test_a_snapshot_inside_the_state_directory_refuses_the_start(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
    """Copilot at openDox-code#84, r4175213798. `/snapshot.json` reads its
    file directly, not through the static handler, so a `--snapshot` named
    at an earlier copy, `<state>/console/<port>.html`, would have been
    replaced by the new copy and served to anyone. The snapshot file, each
    registered entry's snapshot and the session snapshots' container are
    served roots, so the start is refused by name, through a link to it as
    well, and the earlier copy is left as it was."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)

    def served(self, *args, **kwargs):
        raise AssertionError("the server served")

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    port = _free_port()
    earlier = _write(state, port=port)
    alias = tmp_path / "snapshot-alias.json"
    alias.symlink_to(earlier.path)
    for named in (earlier.path, alias):
        before = (earlier.path.read_bytes(), _fingerprint(earlier.path))
        assert serve.main(["--snapshot", str(named), "--checkout-root", str(repo),
                           "--port", str(port)]) == 1
        err = capsys.readouterr().err
        assert "serve refused:" in err and "OPENDOX_STATE_DIR" in err, err
        assert str(earlier.path.resolve()) in err, err
        assert (earlier.path.read_bytes(), _fingerprint(earlier.path)) == before
        assert _port_is_free(port)


def test_the_plane_reports_its_snapshot_files_as_served_roots(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """The roots `/snapshot.json` serves from: the configured snapshot, each
    registered entry's snapshot file, and, on a loopback plane, the container
    each session's snapshot is written in."""
    from opendox import branch_session

    with _serving(tmp_path, monkeypatch) as (httpd, _base, repo):
        snapshot = (tmp_path / "snapshot.json").resolve()
        assert snapshot in httpd.served_roots
        assert branch_session.snapshots_root(repo) in httpd.served_roots
        entries = httpd.RequestHandlerClass.func.source.registry.entries()
        for entry in entries:
            if getattr(entry, "snapshot_path", None):
                assert Path(entry.snapshot_path).resolve() in httpd.served_roots
        # ...and a registered entry whose snapshot is ANOTHER file
        from opendox import default_registry, serve

        other = tmp_path / "elsewhere" / "other.snapshot.json"
        other.parent.mkdir()
        other.write_text(json.dumps({"generation": {}}), encoding="utf-8")
        source = default_registry.SnapshotSource(
            baked_snapshot=tmp_path / "snapshot.json", checkout_root=repo)
        source.registry.register(default_registry.entry_from_snapshot_file(
            other, repository="other", ref="main"))
        declared = serve.build_server(WEB, tmp_path / "snapshot.json", repo,
                                      port=0, quiet=True, snapshot_source=source)
        try:
            assert other.resolve() in declared.served_roots
        finally:
            declared.server_close()


def test_a_copy_published_during_a_rename_back_is_never_overwritten(
        tmp_path, monkeypatch) -> None:
    """Copilot at openDox-code#84, r4175213842. Where a hard link cannot be
    made, another serve's copy is put back by a rename where the name is
    free, and a still newer copy published between that check and the
    rename would have been overwritten by the older one. Publication and
    removal are serialized on the console directory's lock, so the newer
    copy, published at exactly that moment, waits and then stands."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
    _abandon(first)                          # its reservation lost
    second_token, third_token = _token(), _token()
    second = _write(state, token=second_token)   # another serve's, over the first
    _abandon(second)                         # ...whose serve is gone too
    real_exists = console_access._name_exists
    raced: list = []

    def then_publish(name, directory):
        free = real_exists(name, directory)
        if not raced:
            raced.append(_publish_concurrently(state, third_token))
        return free

    def no_hard_links(*args, **kwargs):
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(console_access, "_name_exists", then_publish)
    monkeypatch.setattr(console_access.os, "link", no_hard_links)
    console_access.remove_private_copy(first)
    monkeypatch.undo()
    assert raced, "the race was never staged"
    _settle(raced[0])
    record = console_access.read_private_copy(first.path)
    assert record["console_token"] == third_token, "an older copy overwrote the newest"
    assert sorted(p.name for p in first.path.parent.iterdir()) == [first.path.name]


def test_deferred_termination_holds_a_stop_until_the_block_ends() -> None:
    """While a copy is being published or removed, SIGTERM is held and not
    raised in the middle of it: publication raises it once the copy is
    in hand, and removal, already a stop, lets it go."""
    from opendox import console_access

    # Every interrupt is CAUGHT here and judged, so a stop raised where it
    # should have been held fails this case instead of ending the session.
    reached = []
    with console_access.terminate_as_interrupt(True):
        assert signal.getsignal(signal.SIGTERM) not in (signal.SIG_DFL, signal.SIG_IGN)
        try:
            with console_access.deferred_termination():
                try:
                    os.kill(os.getpid(), signal.SIGTERM)
                    signal.pthread_sigmask(signal.SIG_BLOCK, [])   # deliver now
                except KeyboardInterrupt:
                    pytest.fail("the stop was raised inside the block, not held")
                reached.append("held")
        except KeyboardInterrupt:
            reached.append("raised once the block was done")
        assert reached == ["held", "raised once the block was done"], reached
        try:
            with console_access.deferred_termination(raise_pending=False):
                os.kill(os.getpid(), signal.SIGTERM)
                signal.pthread_sigmask(signal.SIG_BLOCK, [])
        except KeyboardInterrupt:
            pytest.fail("a stop held during a removal was raised")
        try:
            with console_access.deferred_termination():
                pass                                            # nothing left over
        except KeyboardInterrupt:
            pytest.fail("a stop that was let go came back")


@pytest.mark.parametrize("entry", ["serve", "generate-and-open"])
def test_a_stop_during_publication_removes_the_copy(
        tmp_path, monkeypatch, capsys, standalone_profile, entry) -> None:
    """Copilot at openDox-code#84, r4175213864. SIGTERM's handling began
    only after the copy was published, so a SIGTERM during publication (here
    in the copy's read-back, after its rename into place) took its default
    action and left the token's copy behind. It is installed BEFORE
    publication on a plane that writes a copy, and held through it, so the
    stop ends the start cleanly, before the startup line, with no copy left."""
    from opendox import cli, console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)
    real_read = console_access.read_private_copy
    stopped: list = []

    def read_back(path):
        if not stopped:
            stopped.append(path)
            # never deliver a SIGTERM that would END this test process
            assert signal.getsignal(signal.SIGTERM) not in (
                signal.SIG_DFL, signal.SIG_IGN), "no handler during publication"
            os.kill(os.getpid(), signal.SIGTERM)
        return real_read(path)

    def served(self, *args, **kwargs):
        raise AssertionError("the server served after a stop")

    monkeypatch.setattr(console_access, "read_private_copy", read_back)
    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    if entry == "serve":
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
        assert serve.main(["--snapshot", str(snapshot), "--checkout-root", str(repo),
                           "--port", "0"]) == 0
        startup = "serving ideation dashboard at"
    else:
        args = cli.build_parser().parse_args([
            "generate-and-open", "--repo-root", str(repo), "--repository", "fixture",
            "--run-dir", str(tmp_path / "run"), "--port", "0", "--no-validate",
            "--no-open"])
        assert cli._generate_and_open(args, opener=lambda url: None) == 0
        startup = "  serving "
    out = capsys.readouterr().out
    assert stopped, "the stop was never staged"
    assert startup not in out and "console " not in out, out
    assert list((state / console_access.CONSOLE_DIRNAME).iterdir()) == []


def test_a_stop_during_removal_lets_the_removal_finish(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
    """The handler stays installed through removal, and a SIGTERM that
    arrives while the copy is being removed is held, not raised in the middle
    of it: the removal finishes, nothing is left, and the stop is clean."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)

    def stopped_at_once(self, *args, **kwargs):
        raise KeyboardInterrupt                       # Ctrl-C, at once

    real_rename = os.rename
    taken: list = []

    def take(src, dst, *args, **kwargs):
        if not taken and ".removing-" in str(dst):
            taken.append(dst)
            assert signal.getsignal(signal.SIGTERM) not in (
                signal.SIG_DFL, signal.SIG_IGN), "no handler during removal"
            os.kill(os.getpid(), signal.SIGTERM)
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", stopped_at_once)
    monkeypatch.setattr(console_access.os, "rename", take)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    assert serve.main(["--snapshot", str(snapshot), "--checkout-root", str(repo),
                       "--port", "0"]) == 0
    monkeypatch.undo()
    assert taken, "the stop was never staged"
    assert list((state / console_access.CONSOLE_DIRNAME).iterdir()) == []


# ---------------------------------------------------------------------------
# 14 — Copilot's review at ddb26c34: every operating-system refusal on the
#      way to the copy is a refusal by name, the walk's included
# ---------------------------------------------------------------------------

def _overlong(tmp_path: Path) -> Path:
    return tmp_path / ("x" * 300) / "state"          # ENAMETOOLONG (errno 36)


def _unsearchable(tmp_path: Path) -> Path:
    locked = tmp_path / "unsearchable"
    locked.mkdir(mode=0o700)
    locked.chmod(0o600)                               # no search (x) bit
    return locked / "state"


@pytest.mark.parametrize("make", [_overlong, _unsearchable],
                         ids=["an overlong component", "an unsearchable parent"])
def test_a_state_path_the_walk_cannot_take_is_refused_by_name(tmp_path, make) -> None:
    """Copilot at openDox-code#84, r4177975898. The walk and the served-root
    check ran outside the writer's conversion of operating-system errors, so
    an overlong component (ENAMETOOLONG) or an unsearchable parent (EACCES)
    escaped as a raw `OSError`, a traceback and no refusal by name. Each is
    a `ConsoleAccessRefused` naming the copy, for the writer and the reader."""
    from opendox import console_access

    if make is _unsearchable and os.geteuid() == 0:
        pytest.skip("root searches any directory")
    state = make(tmp_path)
    try:
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="cannot be written") as refused:
            _write(state)
        assert str(console_access.private_copy_path(state, 8080)) in str(refused.value)
        with pytest.raises(console_access.ConsoleAccessRefused, match="cannot be read"):
            console_access.read_private_copy(
                console_access.private_copy_path(state, 8080))
    finally:
        if make is _unsearchable:
            state.parent.chmod(0o700)


@pytest.mark.parametrize("make", [_overlong, _unsearchable],
                         ids=["an overlong component", "an unsearchable parent"])
@pytest.mark.parametrize("entry", ["serve", "generate-and-open"])
def test_a_state_path_the_walk_cannot_take_refuses_the_start(
        tmp_path, monkeypatch, capsys, standalone_profile, make, entry) -> None:
    """The same, through both entry points: exit 1 with the refusal named,
    nothing printed that serves, and the listening socket closed."""
    from opendox import cli, serve

    if make is _unsearchable and os.geteuid() == 0:
        pytest.skip("root searches any directory")
    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = make(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)

    def served(self, *args, **kwargs):
        raise AssertionError("the server served")

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    port = _free_port()
    try:
        if entry == "serve":
            snapshot = tmp_path / "snapshot.json"
            snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
            assert serve.main(["--snapshot", str(snapshot), "--checkout-root",
                               str(repo), "--port", str(port)]) == 1
            refused, startup = "serve refused:", "serving ideation dashboard at"
        else:
            assert cli._generate_and_open(
                _generate_and_open_args(tmp_path, repo, "--port", str(port)),
                opener=lambda url: None) == 1
            refused, startup = "generate-and-open refused:", "  serving "
        out, err = capsys.readouterr()
        assert refused in err and "cannot be written" in err, err
        assert startup not in out, out
        assert _port_is_free(port), "the refused start kept its socket"
    finally:
        if make is _unsearchable:
            state.parent.chmod(0o700)


# ---------------------------------------------------------------------------
# 15 — Copilot's review at 9f328892: Ctrl-C is held like SIGTERM while a copy
#      is written or removed (r4178041022)
# ---------------------------------------------------------------------------

def _ctrl_c_is_held() -> None:
    """Never send a SIGINT that Python's own handler would raise at once: a
    raw KeyboardInterrupt aborts the whole pytest session, not one case."""
    assert signal.getsignal(signal.SIGINT) is not signal.default_int_handler, (
        "Ctrl-C still has Python's immediate handler")


def test_terminate_as_interrupt_takes_ctrl_c_only_from_its_default() -> None:
    """Ctrl-C is held like SIGTERM, where it still has Python's own handler;
    an ignored one, or a host's own handler, is left exactly as it was."""
    from opendox import console_access

    previous = signal.getsignal(signal.SIGINT)
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
        with console_access.terminate_as_interrupt(True):
            _ctrl_c_is_held()
        assert signal.getsignal(signal.SIGINT) is signal.default_int_handler

        def host(signum, frame):                   # a host's own handler
            raise AssertionError("never sent")

        for kept in (signal.SIG_IGN, host):
            signal.signal(signal.SIGINT, kept)
            with console_access.terminate_as_interrupt(True):
                assert signal.getsignal(signal.SIGINT) is kept
            assert signal.getsignal(signal.SIGINT) is kept
    finally:
        signal.signal(signal.SIGINT, previous)


@pytest.mark.parametrize("entry", ["serve", "generate-and-open"])
def test_ctrl_c_just_after_the_copys_rename_leaves_no_copy(
        tmp_path, monkeypatch, capsys, standalone_profile, entry) -> None:
    """The publication window: Ctrl-C right after the copy is renamed into
    place, before the caller holds it, used to raise at once, and the
    caller's cleanup, holding nothing, left the copy behind. It is held until
    the copy is in hand, then the start stops cleanly with no copy left."""
    from opendox import cli, console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    real_replace = os.replace
    sent: list = []

    def then_ctrl_c(src, dst, *args, **kwargs):
        real_replace(src, dst, *args, **kwargs)
        if not sent and str(dst).endswith(".html"):
            sent.append(dst)
            _ctrl_c_is_held()
            os.kill(os.getpid(), signal.SIGINT)
            signal.pthread_sigmask(signal.SIG_BLOCK, [])   # deliver now

    def served(self, *args, **kwargs):
        raise AssertionError("the server served after a stop")

    monkeypatch.setattr(console_access.os, "replace", then_ctrl_c)
    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    try:
        if entry == "serve":
            snapshot = tmp_path / "snapshot.json"
            snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
            assert serve.main(["--snapshot", str(snapshot), "--checkout-root",
                               str(repo), "--port", "0"]) == 0
        else:
            args = cli.build_parser().parse_args([
                "generate-and-open", "--repo-root", str(repo), "--repository",
                "fixture", "--run-dir", str(tmp_path / "run"), "--port", "0",
                "--no-validate", "--no-open"])
            assert cli._generate_and_open(args, opener=lambda url: None) == 0
    finally:
        signal.signal(signal.SIGINT, previous)
    out = capsys.readouterr().out
    assert sent, "the Ctrl-C was never staged"
    assert "console " not in out, out
    assert list((state / console_access.CONSOLE_DIRNAME).iterdir()) == []


def test_a_second_ctrl_c_after_the_removal_rename_leaves_nothing(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
    """The removal window: a second Ctrl-C right after the removal renamed
    the copy to its temporary name used to raise there and leave a
    `.removing-*` file holding the token. It is held, the removal finishes,
    and `console/` is left empty."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    real_rename = os.rename
    sent: list = []

    def stopped_at_once(self, *args, **kwargs):
        raise KeyboardInterrupt                       # the first Ctrl-C

    def then_ctrl_c(src, dst, *args, **kwargs):
        real_rename(src, dst, *args, **kwargs)
        if not sent and ".removing-" in str(dst):
            sent.append(dst)
            _ctrl_c_is_held()
            os.kill(os.getpid(), signal.SIGINT)       # the second
            signal.pthread_sigmask(signal.SIG_BLOCK, [])

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", stopped_at_once)
    monkeypatch.setattr(console_access.os, "rename", then_ctrl_c)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    try:
        assert serve.main(["--snapshot", str(snapshot), "--checkout-root",
                           str(repo), "--port", "0"]) == 0
    finally:
        signal.signal(signal.SIGINT, previous)
    monkeypatch.undo()
    assert sent, "the second Ctrl-C was never staged"
    assert list((state / console_access.CONSOLE_DIRNAME).iterdir()) == []


# ---------------------------------------------------------------------------
# 16 — Copilot's review at fb8a1cc4: a live console's copy is reserved for
#      its server's life (r4178133814); every unguarded file read refuses a
#      private copy by the file's own identity (r4178133842)
# ---------------------------------------------------------------------------

def _abandon(copy) -> None:
    """The serve that wrote `copy` is gone without removing it (a crash, a
    SIGKILL): its reservation is released, as the kernel releases it."""
    reservation = getattr(copy, "reservation", None)
    if reservation is not None:
        reservation.close()


def test_a_running_consoles_copy_is_never_replaced(tmp_path) -> None:
    """Two consoles can share a port number (127.0.0.1 and ::1) and a state
    directory. The first's copy is reserved while it runs: a second
    publication on that port is refused by name, and the first's copy is left
    exactly as it was, still opening the first console. Once the first stops
    and removes its copy, the port's copy can be written again."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
    before = (first.path.read_bytes(), _fingerprint(first.path))
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="still running") as refused:
        _write(state)
    assert str(first.path) in str(refused.value)
    assert (first.path.read_bytes(), _fingerprint(first.path)) == before
    console_access.remove_private_copy(first)
    assert _write(state).path == first.path


def test_a_copy_whose_console_died_is_replaced(tmp_path) -> None:
    """A copy whose writer died without removing it (here a process that
    writes one and exits at once) holds no reservation, since the kernel
    released it with the process. It is a stale copy, and is replaced."""
    import subprocess
    import sys

    from opendox import console_access

    state = _state(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "XF_"))}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), env.get("PYTHONPATH", "")])
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys; from opendox import console_access, serve\n"
         "console_access.write_private_copy(sys.argv[1], "
         "page_url='http://127.0.0.1:8080/index.html', port=8080, "
         "token=serve.mint_console_token(), served_roots=())\n",
         str(state)], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    stale = console_access.private_copy_path(state, 8080)
    old = console_access.read_private_copy(stale)["console_token"]
    token = _token()
    assert _write(state, token=token).path == stale
    assert console_access.read_private_copy(stale)["console_token"] == token != old


@pytest.mark.skipif(not socket.has_ipv6, reason="no IPv6 on this platform")
def test_two_consoles_on_one_port_number_never_share_a_copy(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """Copilot's layout, as two real planes: one bound to 127.0.0.1 and one
    to ::1, on the same port number and the same state directory. The second
    is refused by name, and the first's copy still opens the first."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    v4 = serve.build_server(WEB, snapshot, repo, host="127.0.0.1", port=0, quiet=True)
    port = v4.server_address[1]
    try:
        v6 = serve.build_server(WEB, snapshot, repo, host="::1", port=port, quiet=True)
    except OSError as exc:
        v4.server_close()
        pytest.skip(f"no IPv6 loopback here: {exc}")
    try:
        env = {"OPENDOX_STATE_DIR": str(state)}
        first = console_access.publish(
            v4, page_url=serve.server_url(v4, "/index.html"), env=env)
        with pytest.raises(console_access.ConsoleAccessRefused, match="still running"):
            console_access.publish(
                v6, page_url=serve.server_url(v6, "/index.html"), env=env)
        record = console_access.read_private_copy(first.path)
        assert record["console_token"] == v4.console_token
        assert "127.0.0.1" in record["page_url"]
        console_access.remove_private_copy(first)
    finally:
        v4.server_close()
        v6.server_close()


def _guarded_plane(tmp_path, monkeypatch, **build):
    from opendox import serve

    _clean_git(monkeypatch)
    repo = build.pop("repo", None) or _repository(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    web = build.pop("web", WEB)
    httpd = serve.build_server(web, snapshot, repo, port=0, quiet=True, **build)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    return httpd, repo, worker


def _stop_plane(httpd, worker) -> None:
    httpd.shutdown()
    httpd.server_close()
    worker.join(timeout=10)


def _assert_never_served(base, token: str, paths) -> None:
    for path in paths:
        for method in ("GET", "HEAD"):
            status, headers, raw = _call(base, method, path)
            assert status == 404, (method, path, status)
            assert token.encode() not in raw, (method, path)
            assert all(token not in str(v) for v in headers.values()), path


def test_a_source_root_retargeted_after_publication_never_serves_the_copy(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """Copilot at openDox-code#84, r4178133842. A declared source root named
    through a link is judged where the link leads when the copy is
    published, but `/source` resolves it again on every request. Re-pointed
    at the state directory afterwards, it used to serve the copy to anyone.
    Every `/source` read is judged by the identity of the file it opened, so
    the copy is never served, whatever the root leads to now."""
    from opendox import console_access, serve

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "note.md").write_text("# a note\n", encoding="utf-8")
    alias = tmp_path / "root-alias"
    alias.symlink_to(elsewhere)
    state = _state(tmp_path)
    httpd, _repo, worker = _guarded_plane(
        tmp_path, monkeypatch, repository="other", source_roots={"other": str(alias)})
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        assert _call(base, "GET", "/source/note.md")[0] == 200
        alias.unlink()
        alias.symlink_to(state)                       # retargeted after the check
        name = copy.path.name
        _assert_never_served(base, httpd.console_token,
                             (f"/source/console/{name}",
                              f"/source/other@main/console/{name}"))
    finally:
        _stop_plane(httpd, worker)


def test_a_snapshot_retargeted_after_publication_never_serves_the_copy(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """The same for `/snapshot.json`, which reads a registered entry's file
    directly: an entry whose snapshot is named through a link re-pointed at
    the copy after publication is a 404, never the copy."""
    from opendox import console_access, default_registry, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    real = tmp_path / "other.snapshot.json"
    real.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    alias = tmp_path / "snapshot-alias.json"
    alias.symlink_to(real)
    source = default_registry.SnapshotSource(
        baked_snapshot=tmp_path / "snapshot.json", checkout_root=repo)
    source.registry.register(default_registry.entry_from_snapshot_file(
        alias, repository="other", ref="main"))
    state = _state(tmp_path)
    httpd, _repo, worker = _guarded_plane(tmp_path, monkeypatch, repo=repo,
                                          snapshot_source=source)
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        path = "/snapshot.json?repository=other&ref=main"
        assert _call(base, "GET", path)[0] == 200
        alias.unlink()
        alias.symlink_to(copy.path)                   # retargeted after the check
        _assert_never_served(base, httpd.console_token, (path,))
    finally:
        _stop_plane(httpd, worker)


@pytest.mark.parametrize("where", ["the static bundle", "the served checkout"])
def test_a_hard_link_to_the_copy_is_never_served(
        tmp_path, monkeypatch, standalone_profile, where) -> None:
    """A path cannot tell a hard link from the file itself: `web/x.html`, or
    `checkout/x.md`, hard-linked to the copy, resolves to a name outside the
    state directory. The file's own identity tells, so the static handler
    and `/source` answer 404 and never send the copy."""
    import shutil as _shutil

    from opendox import console_access, serve

    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state = _state(tmp_path)
    httpd, repo, worker = _guarded_plane(tmp_path, monkeypatch, web=web)
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        if where == "the static bundle":
            os.link(copy.path, web / "hard.html")
            paths = ("/hard.html",)
        else:
            os.link(copy.path, repo / "hard.md")
            paths = ("/source/hard.md",)
        _assert_never_served(base, httpd.console_token, paths)
        assert _call(base, "GET", "/index.html")[0] == 200
    finally:
        _stop_plane(httpd, worker)


def _raw_get(base, path: str) -> bytes:
    """Every byte the server sends for `GET path`, read until it closes:
    a response cut short is read as far as it went, never raised."""
    with socket.create_connection(base, timeout=30) as conn:
        conn.sendall(f"GET {path} HTTP/1.0\r\nHost: {base[0]}:{base[1]}\r\n\r\n"
                     .encode("ascii"))
        received = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                return received
            received += chunk


def test_the_static_backstop_never_sends_a_copy_swapped_in_after_the_check(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """The file the stdlib handler opens is judged after it opens, against a
    link swapped in between the handler's own check and that open. Staged by
    blinding the first check: the copy's bytes are still never sent."""
    import shutil as _shutil

    from opendox import console_access, serve

    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state = _state(tmp_path)
    httpd, _repo, worker = _guarded_plane(tmp_path, monkeypatch, web=web)
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        os.link(copy.path, web / "swapped.html")
        monkeypatch.setattr(console_access, "opens_a_private_file",
                            lambda path, roots: False)        # the race, won
        received = _raw_get(base, "/swapped.html")
        assert httpd.console_token.encode() not in received, received[:300]
        assert b"opendox-console" not in received
        assert b"index" in _raw_get(base, "/index.html").lower()
    finally:
        _stop_plane(httpd, worker)


def test_a_snapshot_named_at_a_copy_not_yet_written_refuses_the_start(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
    """The configured snapshot is a served root even when its file does not
    exist yet, and so is registered as no entry: `/snapshot.json` falls back
    to reading that path. Named at the copy this start is about to write,
    `<state>/console/<port>.html`, it refuses the start by name, and no copy
    is written."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)

    def served(self, *args, **kwargs):
        raise AssertionError("the server served")

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    port = _free_port()
    future = console_access.private_copy_path(state, port)
    assert serve.main(["--snapshot", str(future), "--checkout-root", str(repo),
                       "--port", str(port)]) == 1
    err = capsys.readouterr().err
    assert "serve refused:" in err and "OPENDOX_STATE_DIR" in err, err
    assert not future.exists()
    assert _port_is_free(port)


# ---------------------------------------------------------------------------
# 17 — the holder's adversarial review of fb8a1cc4 and 73df8bac
#      (openDox-code#84; B1, B2, B4, B5, B6, B8, B9). The cases named
#      `test_b*` are the reviewer's own, kept as they were written.
# ---------------------------------------------------------------------------

def _adv_env(state: Path | None = None) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "XF_", "OPENDOX_"))}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull,
               LANG="C.UTF-8", PYTHONUNBUFFERED="1", PYTHONPATH=str(ROOT / "src"))
    if state is not None:
        env["OPENDOX_STATE_DIR"] = str(state)
    return env


def _adv_repo(where: Path, *, identity: bool = True) -> Path:
    """A checkout; with no `identity`, its plane resolves no actor, so it has
    no session verbs and mints no token."""
    import subprocess

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=where, env=_adv_env(), check=True,
                       capture_output=True)

    where.mkdir(parents=True, exist_ok=True)
    run("init", "-q", "-b", "main")
    if identity:
        run("config", "user.name", "fixture")
        run("config", "user.email", "fixture@example.invalid")
    (where / "README.md").write_text("# fixture\n")
    run("add", ".")
    run("-c", "user.name=x", "-c", "user.email=x@example.invalid",
        "commit", "-qm", "init")
    return where


def _adv_serve(tmp: Path, repo: Path, state: Path, port: int, name: str,
               code: str | None = None):
    """`python -m opendox.serve` as a user starts it, or `code` and then
    `serve.main`, waited for until it serves or ends."""
    import subprocess
    import sys
    import time

    snapshot = tmp / f"{name}.json"
    snapshot.write_text(json.dumps({"generation": {}}))
    out = tmp / f"{name}.out"
    argv = ["--snapshot", str(snapshot), "--checkout-root", str(repo),
            "--port", str(port)]
    if code is None:
        cmd = [sys.executable, "-m", "opendox.serve", *argv]
    else:
        cmd = [sys.executable, "-c", code + f"\nsys.exit(serve.main({argv!r}))"]
    parent = os.getpid()
    proc = subprocess.Popen(cmd, cwd=tmp, env=_adv_env(state),
                            stdout=out.open("w"), stderr=subprocess.STDOUT,
                            start_new_session=True,
                            preexec_fn=lambda: _child_setup(parent))
    _SPAWNED.append(proc)
    for _ in range(300):
        if "serving ideation dashboard" in out.read_text() or proc.poll() is not None:
            break
        time.sleep(0.1)
    return proc, out


#: Every server child `_adv_serve` started, reaped after each case
#: (`_reap_spawned_servers`), whether the case passed, failed or raised.
_SPAWNED: list = []
#: `prctl(2)`, loaded in the test process, before any fork, on Linux only.
_PRCTL = None
if sys.platform.startswith("linux"):
    import ctypes as _ctypes

    with contextlib.suppress(OSError, AttributeError):
        _PRCTL = _ctypes.CDLL(None, use_errno=True).prctl
_PR_SET_PDEATHSIG = 1


def _child_setup(parent: int) -> None:
    """In the child, before it runs. A child started from a background job
    inherits SIGINT ignored, and one under `nohup` SIGHUP: give it a
    terminal's, so its stops are read. And on Linux, have the kernel send it
    SIGTERM if the test process dies first (a killed run runs no teardown),
    so no server outlives the run that started it."""
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
    if _PRCTL is not None:
        _PRCTL(_PR_SET_PDEATHSIG, int(signal.SIGTERM), 0, 0, 0)
        if os.getppid() != parent:          # the parent died before prctl
            os._exit(1)


def _adv_stop(proc) -> int:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
    return proc.wait(30)


def _reap(proc, wait: float = 15) -> None:
    """Stop `proc` and its process group (its own session, so nothing else
    is in it): SIGTERM, a bounded wait, then SIGKILL. A child that already
    ended is only collected."""
    import subprocess

    if proc.poll() is not None:
        return
    for sent in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, sent)
        try:
            proc.wait(wait)
            return
        except subprocess.TimeoutExpired:
            continue


@pytest.fixture(autouse=True)
def _reap_spawned_servers():
    """No server child outlives its case: every one `_adv_serve` started is
    stopped with its process group at teardown, the failing cases' included
    (a refusal that did not come, say, leaves a plane serving)."""
    yield
    while _SPAWNED:
        _reap(_SPAWNED.pop())


def test_b1_a_tokenless_sibling_plane_never_serves_another_planes_copy(
        tmp_path) -> None:
    """B1, as the reviewer staged it, with two real planes. Plane A (a git
    identity, so a token) publishes into the shared state directory. Plane B
    (no identity, so no token) serves a checkout that HOLDS that directory.
    B used to ask no boundary and mark no private root, so its `/source`
    served A's copy, token and all. It is the same plane's boundary now,
    token or not: B refuses its start by name, and serves nothing."""
    from opendox import console_access

    repo_a = _adv_repo(tmp_path / "a")
    outer = _adv_repo(tmp_path / "outer", identity=False)
    state = _state(outer)
    port_a, port_b = _free_port(), _free_port()
    a, _out_a = _adv_serve(tmp_path, repo_a, state, port_a, "a")
    try:
        assert a.poll() is None, _out_a.read_text()
        token = console_access.read_private_copy(
            console_access.private_copy_path(state, port_a))["console_token"]
        b, out_b = _adv_serve(tmp_path, outer, state, port_b, "b")
        rc = b.wait(60)
        text = out_b.read_text()
        assert rc == 1 and "serve refused:" in text, text
        assert "OPENDOX_STATE_DIR" in text and str(outer.resolve()) in text, text
        assert "Traceback" not in text and token not in text, text
        assert _port_is_free(port_b), "the refused plane kept its socket"
        assert a.poll() is None, "plane A went down with B's refusal"
    finally:
        _adv_stop(a)          # B, if it never refused, is reaped at teardown


def test_a_tokenless_standalone_plane_keeps_the_boundary(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """B1 in the process: a standalone plane that minted no token is still a
    standalone plane (its delivery does not depend on the token), and its
    publication still asks the boundary, refusing by name a state directory
    inside its checkout. It writes nothing, and the sibling's copy there is
    left as it was."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    outer = fresh_repository(PLAIN, tmp_path / "b")
    state = _state(outer)
    other = _write(state, port=9)                 # a sibling plane's copy
    before = (other.path.read_bytes(), _fingerprint(other.path))
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(WEB, snapshot, outer, port=0, quiet=True)
    try:
        assert httpd.console_token is None, "the case is vacuous: a token was minted"
        assert httpd.console_token_delivery == console_access.DELIVERY_OPENED_URL
        assert not console_access.needs_copy(httpd)
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="OPENDOX_STATE_DIR") as refused:
            console_access.publish(
                httpd, page_url=serve.server_url(httpd, "/index.html"),
                env={"OPENDOX_STATE_DIR": str(state)})
        assert "lies inside the served repository" in str(refused.value)
        assert str(outer.resolve()) in str(refused.value)
    finally:
        httpd.server_close()
    assert sorted(p.name for p in (state / console_access.CONSOLE_DIRNAME).iterdir()) \
        == [other.path.name]
    assert (other.path.read_bytes(), _fingerprint(other.path)) == before
    console_access.remove_private_copy(other)


def test_a_tokenless_standalone_plane_never_serves_a_siblings_copy(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """B1, the reviewer's `--web-dir` link variant: no root of the tokenless
    plane holds the state directory, but a link inside its static bundle
    leads there, and a hard link in its checkout is the copy by another name.
    The copies' directory is marked private on this plane too, so the
    sibling's copy and the directory's listing are 404, through the static
    handler and `/source` alike, and the bundle still answers."""
    import shutil as _shutil

    from opendox import console_access, serve

    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state = _state(tmp_path)
    (web / "state-alias").symlink_to(state)
    outer = fresh_repository(PLAIN, tmp_path / "b")
    httpd, _repo, worker = _guarded_plane(tmp_path, monkeypatch, repo=outer, web=web)
    try:
        base = httpd.server_address[:2]
        assert httpd.console_token is None, "the case is vacuous: a token was minted"
        other = _write(state, port=9)             # a sibling plane's copy
        token = console_access.read_private_copy(other.path)["console_token"]
        assert console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)}) is None
        assert sorted(p.name for p in other.path.parent.iterdir()) == [other.path.name]
        os.link(other.path, outer / "hard.md")
        _assert_never_served(base, token, (
            f"/state-alias/console/{other.path.name}", "/state-alias/console/",
            "/source/hard.md"))
        status, _headers, raw = _call(base, "GET", "/state-alias/console/")
        assert other.path.name.encode() not in raw
        assert _call(base, "GET", "/index.html")[0] == 200
    finally:
        _stop_plane(httpd, worker)


def test_b2_a_platform_without_the_posix_primitives_refuses_by_name(
        tmp_path) -> None:
    """B2, as the reviewer staged it: on Windows `os.getuid`, `O_NOFOLLOW` and
    `O_DIRECTORY` do not exist. The standalone start is a refusal by name, as
    `bundle.unsupported_platform` names the same gap, and never an
    `AttributeError` traceback."""
    import textwrap

    repo = _adv_repo(tmp_path / "r")
    state = _state(tmp_path)
    code = textwrap.dedent("""
        import os, sys
        from opendox import serve
        for name in ('getuid', 'O_NOFOLLOW', 'O_DIRECTORY'):
            delattr(os, name)
    """)
    proc, out = _adv_serve(tmp_path, repo, state, _free_port(), "w", code=code)
    rc = proc.wait(60)
    text = out.read_text()
    assert "Traceback" not in text, text
    assert rc == 1 and "serve refused:" in text, text
    assert "needs a POSIX platform" in text and "os.getuid" in text, text
    assert not (state / "console").exists()


@pytest.mark.parametrize("gap", ["os.O_NOFOLLOW", "a directory descriptor"])
def test_the_writer_and_the_reader_refuse_a_platform_without_the_primitives(
        tmp_path, monkeypatch, gap) -> None:
    """B2, by part: the writer refuses before it writes anything, the reader
    before it reads, each naming the gap (`unsupported_platform`)."""
    from opendox import console_access

    state = _state(tmp_path)
    copy = _write(state)                          # while the primitives exist
    if gap == "os.O_NOFOLLOW":
        monkeypatch.delattr(os, "O_NOFOLLOW")
        named = "os.O_NOFOLLOW"
    else:
        monkeypatch.setattr(console_access, "_DIR_FD_CALLS", False)
        named = "calls relative to a directory's descriptor"
    try:
        assert named in (console_access.unsupported_platform() or "")
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="needs a POSIX platform") as refused:
            _write(state, port=9)
        assert named in str(refused.value)
        assert not console_access.private_copy_path(state, 9).exists()
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="needs a POSIX platform"):
            console_access.read_private_copy(copy.path)
    finally:
        monkeypatch.undo()
    assert console_access.unsupported_platform() is None
    console_access.remove_private_copy(copy)


def _two_spellings(monkeypatch, real: Path, alias: Path) -> None:
    """A case-insensitive filesystem, as far as `os.stat` and `os.listdir`
    can tell: `alias`, and every name under it, is `real`. Linux cannot spell
    one directory two ways (a bind mount needs root), so the two calls a
    second spelling reaches are told so; `os.lstat`, and so resolving, still
    sees `alias` as a name that does not exist, as macOS's resolving keeps
    the case it was given."""
    real_stat, real_listdir = os.stat, os.listdir

    def mapped(path):
        if isinstance(path, (str, os.PathLike)):
            text = os.fspath(path)
            if isinstance(text, str) and (text == str(alias)
                                          or text.startswith(str(alias) + os.sep)):
                return str(real) + text[len(str(alias)):]
        return path

    monkeypatch.setattr(os, "stat", lambda path, *a, **k: real_stat(mapped(path), *a, **k))
    monkeypatch.setattr(os, "listdir",
                        lambda path=".", *a, **k: real_listdir(mapped(path), *a, **k))


@pytest.mark.parametrize("served", ["the state directory", "a root inside it",
                                    "a root holding it"])
def test_the_boundary_knows_a_second_spelling_by_its_identity(
        tmp_path, monkeypatch, served) -> None:
    """B4, the overlap: on a case-insensitive filesystem `<tmp>/OUTER/state`
    IS `<tmp>/outer/state`, though no name says so. The boundary compares the
    directories' identities too, so the second spelling of the state
    directory, of a root inside it, or of a root holding it, refuses by name
    before anything is written."""
    from opendox import console_access

    outer = tmp_path / "outer"
    outer.mkdir()
    state = _state(outer)
    alias = tmp_path / "OUTER"
    _two_spellings(monkeypatch, outer, alias)
    root = {"the state directory": alias / "state",
            "a root inside it": alias / "state" / "inner",
            "a root holding it": alias}[served]
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="OPENDOX_STATE_DIR") as refused:
        console_access.write_private_copy(
            state, page_url="http://127.0.0.1:8080/index.html", port=8080,
            token=_token(), served_roots=(root,))
    assert str(root) in str(refused.value)
    assert not (state / console_access.CONSOLE_DIRNAME).exists()


def test_a_second_spelling_of_the_copies_directory_is_never_listed(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """B4, the static guard, in the reviewer's r9 layout: `web/state-alias`
    leads to the state directory, and on a case-insensitive filesystem
    `/state-alias/CONSOLE/` lists the copies' directory under a name no
    private root spells. The guard knows the directory by its identity, so
    that listing is a 404 like the plain spelling's."""
    import shutil as _shutil

    from opendox import console_access, serve

    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state = _state(tmp_path)
    (web / "state-alias").symlink_to(state)
    httpd, _repo, worker = _guarded_plane(tmp_path, monkeypatch, web=web)
    try:
        base = httpd.server_address[:2]
        copy = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state)})
        _two_spellings(monkeypatch, copy.path.parent, state / "CONSOLE")
        assert console_access.within_private_roots(
            web / "state-alias" / "CONSOLE", httpd.private_roots)
        for path in ("/state-alias/CONSOLE/", "/state-alias/console/"):
            for method in ("GET", "HEAD"):
                status, _headers, raw = _call(base, method, path)
                assert status == 404, (method, path, status)
                assert copy.path.name.encode() not in raw, (method, path)
        assert _call(base, "GET", "/index.html")[0] == 200
    finally:
        _stop_plane(httpd, worker)


def test_b3_a_second_stop_before_the_cleanup_hold_leaves_no_copy(tmp_path) -> None:
    """B5 (the reviewer's `test_b3`): a double Ctrl-C, or SIGTERM and then the
    SIGHUP of a closing terminal. The second stop lands after the first
    unwound the serve loop and before the cleanup's
    `deferred_termination(raise_pending=False)` holds anything; it is
    delivered here at exactly that point. Only the first stop is raised, so
    the cleanup runs to its end: no copy, no traceback, exit 0."""
    import textwrap

    repo = _adv_repo(tmp_path / "r")
    state = _state(tmp_path)
    port = _free_port()
    code = textwrap.dedent("""
        import os, signal, sys
        from opendox import console_access as ca, serve
        real = ca.deferred_termination
        def window(*, raise_pending=True):
            if not raise_pending:
                os.kill(os.getpid(), signal.SIGINT)
                for _ in range(1000):
                    pass
            return real(raise_pending=raise_pending)
        ca.deferred_termination = window
    """)
    proc, out = _adv_serve(tmp_path, repo, state, port, "s", code=code)
    copy = state / "console" / f"{port}.html"
    assert copy.exists(), out.read_text()
    rc = _adv_stop(proc)
    assert not copy.exists(), "the copy outlived the stop"
    assert "Traceback" not in out.read_text() and rc == 0, out.read_text()


def test_only_the_first_stop_is_raised() -> None:
    """B5 in the process: once a stop has been raised, a later one is only
    recorded, held or not; and a console that starts again raises its own
    first stop."""
    from opendox import console_access

    def stop() -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        signal.pthread_sigmask(signal.SIG_BLOCK, [])   # deliver now

    for _attempt in range(2):
        raised: list[str] = []
        with console_access.terminate_as_interrupt(True):
            try:
                stop()
            except KeyboardInterrupt:
                raised.append("first")
            try:
                stop()
                for _ in range(1000):
                    pass
            except KeyboardInterrupt:
                pytest.fail("a second stop was raised")
            try:
                with console_access.deferred_termination():
                    stop()
            except KeyboardInterrupt:
                pytest.fail("a stop held after the first was raised")
        assert raised == ["first"], raised


def test_b6a_a_link_another_user_owns_on_the_state_path_is_refused(
        tmp_path, monkeypatch) -> None:
    """B6(a): `_walked`'s link-owner rule, the only guard against a link
    another user owns (and can re-point) on OPENDOX_STATE_DIR. Simulated by
    reporting the link's owner as another uid."""
    from opendox import console_access

    private = _state(tmp_path / "private")
    alias = tmp_path / "alias"
    alias.symlink_to(private)
    real_lstat = os.lstat

    def lstat(path, *a, **k):
        info = real_lstat(path, *a, **k)
        if Path(path) == alias:
            fields = list(info)
            fields[stat.ST_UID] = os.getuid() + 1
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(console_access.os, "lstat", lstat)
    with pytest.raises(console_access.ConsoleAccessRefused,
                       match="symbolic link owned by uid"):
        console_access.write_private_copy(
            alias, page_url="http://127.0.0.1:8080/index.html", port=8080,
            token="t" * 43, served_roots=())
    assert not (private / "console").exists()


def test_b6b_the_reader_judges_the_state_directory_again(tmp_path) -> None:
    """B6(b): `read_private_copy` asks all of it again: a state directory
    loosened to 1777 after the copy was written (sticky, so the walk's rule
    for the directories above lets it pass) is refused by the reader."""
    from opendox import console_access

    state = _state(tmp_path / "state")
    copy = console_access.write_private_copy(
        state, page_url="http://127.0.0.1:8080/index.html", port=8080,
        token="t" * 43, served_roots=())
    state.chmod(0o1777)
    try:
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="writable by every user"):
            console_access.read_private_copy(copy.path)
    finally:
        state.chmod(0o700)
        console_access.remove_private_copy(copy)


def test_b6c_the_copy_is_0600_under_a_umask_that_strips_owner_write(tmp_path) -> None:
    """B6(c): `os.fchmod(handle, 0o600)` is what makes the copy 0600 where the
    umask removes an owner bit. The umask case of section 3 uses umask 0,
    where `os.open`'s mode alone gives 0600."""
    from opendox import console_access

    state = _state(tmp_path / "state")
    previous = os.umask(0o277)
    try:
        copy = console_access.write_private_copy(
            state, page_url="http://127.0.0.1:8080/index.html", port=8080,
            token="t" * 43, served_roots=())
    finally:
        os.umask(previous)
    assert stat.S_IMODE(os.lstat(copy.path).st_mode) == 0o600
    console_access.remove_private_copy(copy)


def test_a_no_serve_run_publishes_opens_and_prints_no_copy(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
    """B8: `--no-serve` closes the server once it has printed the URL, so a
    copy written for it opened a console page nothing answered, and was gone
    as the run returned. No copy is written, none is opened, and no console
    line is printed; the page's URL is still printed and opened, as it was
    before T104, and carries no token."""
    from opendox import cli, console_access

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    written: list[object] = []
    real = console_access.write_private_copy

    def recording(*args, **kwargs):
        written.append(args)
        return real(*args, **kwargs)

    def served(self, *args, **kwargs):
        raise AssertionError("a --no-serve run served")

    monkeypatch.setattr(console_access, "write_private_copy", recording)
    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", served)
    opened: list[str] = []
    assert cli._generate_and_open(
        _generate_and_open_args(tmp_path, repo, "--no-serve"),
        opener=opened.append) == 0
    out = capsys.readouterr().out
    assert written == [], "a --no-serve run wrote a copy"
    assert not (state / console_access.CONSOLE_DIRNAME).exists()
    assert "  console " not in out and "console_token" not in out, out
    assert console_access.UNOPENABLE_HINT not in out, out
    (url,), = [opened]
    assert url.startswith("http://") and url.endswith("/index.html"), url
    assert url in out.splitlines(), out


def _own_file(directory: Path, name: str, mode: int = 0o600) -> Path:
    path = directory / name
    path.write_text("left behind\n", encoding="utf-8")
    path.chmod(mode)
    return path


def test_a_publication_sweeps_the_copies_whose_consoles_died(tmp_path) -> None:
    """B9: a serve that died (SIGKILL, an out-of-memory kill) left its copy,
    a token in it, until a later serve took the same port. A publication now
    sweeps every copy whose reservation is free, and the temporary and
    taken names a writer or a remover left mid-way. A running console's copy
    is never swept, and neither is anything that is not this user's own
    copy-shaped file of mode 0600: a loosened copy (refused by name, never
    replaced), a link, a file of another name."""
    from opendox import console_access

    state = _state(tmp_path)
    dead = _write(state, port=9)
    _abandon(dead)                                 # its server died
    alive = _write(state, port=10)                 # its server still runs
    console = alive.path.parent
    left = [_own_file(console, ".11.html.opendox-424242"),
            _own_file(console, ".12.html.removing-1-0123456789ab")]
    kept = [_own_file(console, "13.html", mode=0o644),
            _own_file(console, "notes.txt")]
    (console / "14.html").symlink_to(tmp_path / "elsewhere.html")
    fresh = _write(state, port=8080)
    names = sorted(p.name for p in console.iterdir())
    assert dead.path.name not in names, "a dead console's copy was not swept"
    assert not any(p.name in names for p in left), names
    assert sorted([alive.path.name, fresh.path.name, "13.html", "14.html",
                   "notes.txt"]) == names
    assert console_access.read_private_copy(alive.path)["console_token"]
    for copy in (alive, fresh):
        console_access.remove_private_copy(copy)


def test_a_sigkilled_serves_copy_is_swept_by_the_next_serve(tmp_path) -> None:
    """B9, as the reviewer staged it: one serve is killed with SIGKILL, which
    runs no cleanup, and another starts on another port. The killed serve's
    copy is swept when the second publishes, and the second's goes when it
    stops: nothing is left."""
    repo = _adv_repo(tmp_path / "r")
    state = _state(tmp_path)
    first_port = _free_port()
    first, _out = _adv_serve(tmp_path, repo, state, first_port, "first")
    assert (state / "console" / f"{first_port}.html").exists(), _out.read_text()
    first.send_signal(signal.SIGKILL)
    first.wait(20)
    assert (state / "console" / f"{first_port}.html").exists()
    second, out = _adv_serve(tmp_path, repo, state, _free_port(), "second")
    try:
        assert second.poll() is None, out.read_text()
        assert not (state / "console" / f"{first_port}.html").exists(), \
            "the killed serve's copy was not swept"
    finally:
        assert _adv_stop(second) == 0
    assert list((state / "console").iterdir()) == []


@pytest.mark.parametrize("entry", ["serve", "generate-and-open"])
def test_the_start_prints_the_unopenable_hint_and_never_the_token(
        tmp_path, monkeypatch, capsys, standalone_profile, entry) -> None:
    """B3, RULED by Brett ("Hint line, accepted limit", 2026-10-04): a snap
    or Flatpak browser cannot open a file under a hidden directory such as
    `~/.local/state`, and a Windows browser under WSL may not open a Linux
    path at all. The token is never printed, so beside the copy's path the
    start prints ONE line saying how to move the state directory, and no
    line it prints, that one included, carries the token."""
    from opendox import cli, console_access, serve

    _clean_git(monkeypatch)
    repo = _repository(tmp_path)
    state = _state(tmp_path)
    monkeypatch.setenv("OPENDOX_STATE_DIR", str(state))
    monkeypatch.setattr(serve, "real_notebook_adapter", lambda *a, **k: None)
    tokens: list[str] = []

    def serve_forever(self, *args, **kwargs):
        copy = console_access.private_copy_path(state, self.server_address[1])
        tokens.append(console_access.read_private_copy(copy)["console_token"])
        raise KeyboardInterrupt

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", serve_forever)
    if entry == "serve":
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
        assert serve.main(["--snapshot", str(snapshot), "--checkout-root", str(repo),
                           "--port", "0"]) == 0
        prefix = "console file://"
    else:
        assert cli._generate_and_open(
            _generate_and_open_args(tmp_path, repo, "--no-open"),
            opener=lambda url: None) == 0
        prefix = "  console file://"
    out, err = capsys.readouterr()
    (token,) = tokens
    lines = out.splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    hint = lines[at + 1]
    assert hint.strip() == console_access.UNOPENABLE_HINT, lines
    assert "OPENDOX_STATE_DIR" in hint and "not hidden" in hint, hint
    assert sum(console_access.UNOPENABLE_HINT in line for line in lines) == 1, lines
    assert all(token not in line for line in (out + err).splitlines()), \
        "a line the start printed carries the token"


def _held_open(copy) -> int:
    """The descriptor that reserves `copy`, checked to be the copy's own."""
    fd = copy.reservation._fd
    assert fd is not None, "the copy was written unreserved"
    info = os.fstat(fd)
    assert (info.st_dev, info.st_ino) == copy.identity
    return fd


def _assert_released(fd: int, identity: tuple[int, int]) -> None:
    """No descriptor `fd` of this process is still the copy's file: it is
    closed, or the number has gone to another file since."""
    try:
        info = os.fstat(fd)
    except OSError as exc:
        assert exc.errno == errno.EBADF, exc
        return
    assert (info.st_dev, info.st_ino) != identity, \
        "the removal kept the copy's reservation open"


@pytest.mark.parametrize("how", ["removed", "its directory gone"])
def test_a_removal_releases_the_copys_reservation(tmp_path, how) -> None:
    """The reservation goes with the copy (mutant run 18's M36c). Removing a
    copy closes the descriptor that reserved it, so a stopped console holds
    no file of its own open, and the token's file, unlinked, is not kept
    alive by it. The same holds where the directory is gone already and there
    is nothing to remove. A second release is harmless."""
    from opendox import console_access

    state = _state(tmp_path)
    copy = _write(state)
    fd = _held_open(copy)
    if how == "its directory gone":
        os.rename(state, tmp_path / "moved")
    console_access.remove_private_copy(copy)
    _assert_released(fd, copy.identity)
    copy.reservation.close()
    console_access.remove_private_copy(copy)
    if how == "removed":
        assert not copy.path.exists()


def test_a_copys_repr_never_carries_its_token(tmp_path) -> None:
    """A log line, a traceback or a failed assertion that prints a
    `PrivateCopy` prints its path, its page and its identity, and never the
    token: the opened URL is kept out of its `repr`."""
    from opendox import console_access

    token = _token()
    copy = _write(_state(tmp_path), token=token)
    try:
        assert token in copy.opened_url
        assert token not in repr(copy) and token not in str(copy)
        assert str(copy.path) in repr(copy)
    finally:
        console_access.remove_private_copy(copy)


# ---------------------------------------------------------------------------
# 18 — Copilot's review at 0539f8c0: the tokenless plane walks the state
#      directory once (r4179091592) and refuses an unsupported platform
#      first (r4179091624)
# ---------------------------------------------------------------------------

def test_a_tokenless_planes_state_link_retargeted_mid_guard_marks_the_real_directory(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """r4179091592, Copilot's layout. `OPENDOX_STATE_DIR` names a link to the
    real state directory, and the tokenless plane's `--web-dir` holds an
    outward link to it, where a sibling plane's copy lies. The link is
    re-pointed at a decoy between the boundary check and the marking. The
    guard walks once and marks what that walk reached, so the sibling's copy
    stays a 404; the marking used to resolve the link again and name the
    decoy, and the copy was served."""
    import shutil as _shutil

    from opendox import console_access, serve

    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    real = _state(tmp_path)
    decoy = tmp_path / "decoy"
    decoy.mkdir(mode=0o700)
    alias = tmp_path / "state-link"
    alias.symlink_to(real)
    (web / "state-alias").symlink_to(real)
    outer = fresh_repository(PLAIN, tmp_path / "b")
    httpd, _repo, worker = _guarded_plane(tmp_path, monkeypatch, repo=outer, web=web)
    real_boundary = console_access._refuse_a_served_state_dir

    def then_retarget(*args, **kwargs):
        real_boundary(*args, **kwargs)
        alias.unlink()
        alias.symlink_to(decoy)                    # re-pointed between the two

    try:
        base = httpd.server_address[:2]
        assert httpd.console_token is None, "the case is vacuous: a token was minted"
        other = _write(real, port=9)               # a sibling plane's copy
        token = console_access.read_private_copy(other.path)["console_token"]
        monkeypatch.setattr(console_access, "_refuse_a_served_state_dir", then_retarget)
        assert console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(alias)}) is None
        assert alias.resolve() == decoy.resolve(), "the retarget was never staged"
        (marked,) = httpd.private_roots
        assert marked.resolve() == (real / console_access.CONSOLE_DIRNAME).resolve()
        _assert_never_served(base, token, (
            f"/state-alias/console/{other.path.name}", "/state-alias/console/"))
        assert _call(base, "GET", "/index.html")[0] == 200
        console_access.remove_private_copy(other)
    finally:
        _stop_plane(httpd, worker)


def test_a_tokenless_planes_unsafe_state_path_refuses_its_start(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """r4179091592: the guard judges the state directory's path as the writer
    does, so a directory on the way that another user could change (here a
    world-writable, non-sticky one) refuses the tokenless start by name too,
    and nothing is marked."""
    from opendox import console_access, serve

    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    try:
        state = _state(shared / "inner")
        outer = fresh_repository(PLAIN, tmp_path / "b")
        _clean_git(monkeypatch)
        snapshot = tmp_path / "snapshot.json"
        snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
        httpd = serve.build_server(WEB, snapshot, outer, port=0, quiet=True)
        try:
            assert httpd.console_token is None, "the case is vacuous: a token was minted"
            with pytest.raises(console_access.ConsoleAccessRefused,
                               match="not sticky") as refused:
                console_access.publish(
                    httpd, page_url=serve.server_url(httpd, "/index.html"),
                    env={"OPENDOX_STATE_DIR": str(state)})
            assert str(shared) in str(refused.value)
            assert not getattr(httpd, "private_roots", ())
        finally:
            httpd.server_close()
    finally:
        shared.chmod(0o700)


def test_a_tokenless_plane_refuses_a_platform_without_the_primitives(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """r4179091624, in the process: a tokenless standalone plane used to skip
    the platform check, start, and mark a private root its handlers then
    judged with the missing `O_NONBLOCK`, dropping every static request. It
    refuses by name now, before it marks anything."""
    from opendox import console_access, serve

    _clean_git(monkeypatch)
    outer = fresh_repository(PLAIN, tmp_path / "b")
    state = _state(tmp_path)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(WEB, snapshot, outer, port=0, quiet=True)
    try:
        assert httpd.console_token is None, "the case is vacuous: a token was minted"
        monkeypatch.delattr(os, "O_NONBLOCK")
        with pytest.raises(console_access.ConsoleAccessRefused,
                           match="needs a POSIX platform") as refused:
            console_access.publish(
                httpd, page_url=serve.server_url(httpd, "/index.html"),
                env={"OPENDOX_STATE_DIR": str(state)})
        assert "os.O_NONBLOCK" in str(refused.value)
        assert not getattr(httpd, "private_roots", ())
    finally:
        monkeypatch.undo()
        httpd.server_close()


def test_a_tokenless_start_without_the_posix_primitives_refuses_by_name(
        tmp_path) -> None:
    """r4179091624, as a user starts it: the no-identity variant of the
    reviewer's B2 child. With `os.getuid`, `O_NOFOLLOW`, `O_DIRECTORY` and
    `O_NONBLOCK` gone, as on Windows, a checkout with no git identity (so no
    token) refuses its start by name, and never serves."""
    import textwrap

    repo = _adv_repo(tmp_path / "r", identity=False)
    state = _state(tmp_path)
    code = textwrap.dedent("""
        import os, sys
        from opendox import serve
        for name in ('getuid', 'O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'):
            delattr(os, name)
    """)
    proc, out = _adv_serve(tmp_path, repo, state, _free_port(), "w", code=code)
    if proc.poll() is None:
        _adv_stop(proc)
        pytest.fail("the tokenless plane started serving: " + out.read_text())
    rc = proc.wait(60)
    text = out.read_text()
    assert "Traceback" not in text, text
    assert rc == 1 and "serve refused:" in text, text
    assert "needs a POSIX platform" in text and "os.O_NONBLOCK" in text, text


# ---------------------------------------------------------------------------
# 19 — Copilot's review at af2a2efb: a copy is known by what it holds, in any
#      state directory (r4179239380) and mid-removal (r4179239411); a scan
#      that fails denies (r4179239424); an entry's payload comes first
# ---------------------------------------------------------------------------

def test_another_state_directorys_copy_is_never_served(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """r4179239380, Copilot's layout: two standalone planes of one user with
    DIFFERENT state directories. Plane A's `--web-dir` links to plane B's
    state directory, and A's checkout holds a hard link to B's copy. B's
    copy lies in no directory A marked, but it holds a console record, so A
    answers 404 for it through the static handler and `/source`, for GET and
    HEAD, while its bundle still answers."""
    import shutil as _shutil

    from opendox import console_access, serve

    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state_a = _state(tmp_path / "a")
    state_b = _state(tmp_path / "b")
    (web / "state-b").symlink_to(state_b)
    httpd, repo, worker = _guarded_plane(tmp_path, monkeypatch, web=web)
    try:
        base = httpd.server_address[:2]
        own = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state_a)})
        assert own is not None
        theirs = _write(state_b, port=9)           # plane B's copy
        token = console_access.read_private_copy(theirs.path)["console_token"]
        os.link(theirs.path, repo / "theirs.md")
        _assert_never_served(base, token, (
            f"/state-b/console/{theirs.path.name}", "/source/theirs.md"))
        assert _call(base, "GET", "/index.html")[0] == 200
        console_access.remove_private_copy(theirs)
        console_access.remove_private_copy(own)
    finally:
        _stop_plane(httpd, worker)


def test_a_copy_removed_during_the_scan_is_never_served(
        tmp_path, monkeypatch) -> None:
    """r4179239411, the interleaving: a read opens the copy, and the copy is
    removed (taken under another name, then unlinked) before the private
    directory's scan can stat its name. Nothing in the directory matches
    then, but the file already open is still the copy, and is judged by what
    it holds: the read is refused."""
    from opendox import console_access, serve

    state = _state(tmp_path)
    copy = _write(state)
    roots = (copy.path.parent,)
    real_open = open
    staged: list[str] = []

    def opened_then_removed(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if not staged:                      # removed after the open
            staged.append(str(path))
            console_access.remove_private_copy(copy)
        return stream

    monkeypatch.setattr("builtins.open", opened_then_removed)
    try:
        assert serve.read_unless_private(copy.path, roots) is None
    finally:
        monkeypatch.undo()
    assert staged, "the removal was never staged"
    assert not copy.path.exists()
    assert list(copy.path.parent.iterdir()) == [], "the removal left a name"


@pytest.mark.parametrize("failure", [errno.EMFILE, errno.EACCES], ids=["EMFILE", "EACCES"])
def test_a_private_directory_that_cannot_be_scanned_denies_the_read(
        tmp_path, monkeypatch, failure) -> None:
    """r4179239424: a private directory that exists and cannot be listed
    (out of descriptors, EMFILE, simulated here; or refused) cannot clear the
    file being read, so the read is denied, an ordinary file's as well as a
    copy's. A private directory that does not exist holds no copy, and the
    ordinary file is read as before."""
    from opendox import console_access, serve

    state = _state(tmp_path)
    copy = _write(state)
    ordinary = tmp_path / "ordinary.md"
    ordinary.write_text("# plain\n", encoding="utf-8")
    roots = (copy.path.parent,)

    def cannot_list(path):
        raise OSError(failure, os.strerror(failure), str(path))

    monkeypatch.setattr(console_access.os, "scandir", cannot_list)
    assert serve.read_unless_private(ordinary, roots) is None
    assert serve.read_unless_private(copy.path, roots) is None
    monkeypatch.undo()
    absent = (tmp_path / "no-such-state" / console_access.CONSOLE_DIRNAME,)
    assert serve.read_unless_private(ordinary, absent) == b"# plain\n"
    assert serve.read_unless_private(ordinary, roots) == b"# plain\n"
    console_access.remove_private_copy(copy)


def test_a_name_whose_status_cannot_be_read_denies_the_read(
        tmp_path, monkeypatch) -> None:
    """r4179239424, per name: a name in the private directory whose status
    cannot be read, for any reason but its removal, cannot be told apart
    from the file being read, so the read is denied. A name removed
    meanwhile is skipped."""
    from opendox import console_access, serve

    state = _state(tmp_path)
    copy = _write(state)
    ordinary = tmp_path / "ordinary.md"
    ordinary.write_text("# plain\n", encoding="utf-8")
    roots = (copy.path.parent,)
    real_scandir = os.scandir

    class _Entry:
        def __init__(self, raised):
            self.raised = raised

        def stat(self, follow_symlinks=True):
            raise self.raised

    def entries_failing(raised):
        def scandir(path):
            listing = [*real_scandir(path), _Entry(raised)]
            return contextlib.nullcontext(iter(listing))
        return scandir

    monkeypatch.setattr(console_access.os, "scandir",
                        entries_failing(PermissionError(errno.EACCES, "denied")))
    assert serve.read_unless_private(ordinary, roots) is None
    monkeypatch.setattr(console_access.os, "scandir",
                        entries_failing(FileNotFoundError(errno.ENOENT, "gone")))
    assert serve.read_unless_private(ordinary, roots) == b"# plain\n"
    monkeypatch.undo()
    console_access.remove_private_copy(copy)


@pytest.mark.parametrize("file", ["missing", "present", "a copy"])
def test_an_entrys_payload_comes_before_its_guarded_file(
        tmp_path, file) -> None:
    """Copilot's review at af2a2efb ("previously missed"): an entry with an
    in-memory payload serves that payload first, as `SnapshotEntry.
    read_bytes` does, whether its file is missing, present, or even a
    private copy; only the file fallback is guarded. An entry with no
    payload reads its file through the guard."""
    import types

    from opendox import console_access, default_registry, serve

    state = _state(tmp_path)
    copy = _write(state)
    path = {"missing": tmp_path / "missing.json",
            "present": tmp_path / "present.json",
            "a copy": copy.path}[file]
    if file == "present":
        path.write_bytes(b'{"from": "file"}')
    handler = types.SimpleNamespace(
        server=types.SimpleNamespace(private_roots=(copy.path.parent,)))
    with_payload = default_registry.SnapshotEntry(
        repository="fixture", snapshot_path=path, payload=b'{"from": "payload"}')
    assert serve.DashboardHandler._entry_bytes(handler, with_payload) == \
        b'{"from": "payload"}'
    without = default_registry.SnapshotEntry(repository="fixture", snapshot_path=path)
    expected = {"missing": None, "present": b'{"from": "file"}', "a copy": None}[file]
    assert serve.DashboardHandler._entry_bytes(handler, without) == expected
    console_access.remove_private_copy(copy)


def test_a_file_whose_head_cannot_be_read_is_denied(tmp_path, monkeypatch) -> None:
    """r4179239424, by content: a regular file whose head cannot be read
    cannot be cleared of holding a console record, so the read is denied.
    A file that holds none is read as before."""
    from opendox import console_access, serve

    state = _state(tmp_path)
    copy = _write(state)
    ordinary = tmp_path / "ordinary.md"
    ordinary.write_text("# plain\n", encoding="utf-8")
    roots = (copy.path.parent,)
    assert serve.read_unless_private(ordinary, roots) == b"# plain\n"

    def unreadable(*args, **kwargs):
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr(console_access.os, "pread", unreadable)
    assert serve.read_unless_private(ordinary, roots) is None
    monkeypatch.undo()
    console_access.remove_private_copy(copy)


# ---------------------------------------------------------------------------
# 20 — no test server outlives its case, or its run
# ---------------------------------------------------------------------------

def test_a_server_left_running_is_reaped_with_its_group(tmp_path) -> None:
    """The teardown's reaper: a server child still serving is stopped by
    its process group, SIGTERM first, so it removes its copy and frees its
    port. A child that ignores SIGTERM is killed after the bounded wait."""
    import subprocess

    repo = _adv_repo(tmp_path / "r")
    state = _state(tmp_path)
    port = _free_port()
    proc, out = _adv_serve(tmp_path, repo, state, port, "left")
    assert proc.poll() is None, out.read_text()
    assert os.getpgid(proc.pid) == proc.pid, "the server is not in its own group"
    assert (state / "console" / f"{port}.html").exists()
    _reap(proc)
    assert proc.returncode == 0, out.read_text()
    assert not (state / "console" / f"{port}.html").exists()
    assert _port_is_free(port)
    stubborn = subprocess.Popen(
        [sys.executable, "-c",
         "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
         "print('ready', flush=True); time.sleep(120)"],
        stdout=subprocess.PIPE, start_new_session=True)
    try:
        assert stubborn.stdout.readline().strip() == b"ready"
        _reap(stubborn, wait=2)
        assert stubborn.returncode == -signal.SIGKILL
    finally:
        if stubborn.poll() is None:
            stubborn.kill()
            stubborn.wait(10)
        stubborn.stdout.close()


def test_a_server_outlives_no_killed_run(tmp_path) -> None:
    """A run that is killed runs no teardown. On Linux the kernel stops a
    server child when the process that started it dies (`_child_setup`'s
    parent-death signal): here an intermediate process starts a child the
    way `_adv_serve` does and is SIGKILLed, and the child ends with it.
    Elsewhere the teardown alone answers for it."""
    import subprocess
    import time

    if _PRCTL is None:
        return                          # no parent-death signal on this platform
    script = (
        "import os, subprocess, sys, time\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "import test_console_token_delivery as t\n"
        "parent = os.getpid()\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],\n"
        "    start_new_session=True, preexec_fn=lambda: t._child_setup(parent))\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(120)\n")
    middle = subprocess.Popen([sys.executable, "-c", script],
                              stdout=subprocess.PIPE, cwd=tmp_path,
                              env=_adv_env())
    try:
        child = int(middle.stdout.readline())
        middle.kill()
        middle.wait(10)
        for _ in range(150):
            try:
                state = Path(f"/proc/{child}/stat").read_text().rsplit(")", 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(0.1)
        else:
            os.kill(child, signal.SIGKILL)
            pytest.fail("the child outlived the killed run that started it")
    finally:
        if middle.poll() is None:
            middle.kill()
            middle.wait(10)
        middle.stdout.close()


def test_a_file_in_the_copies_directory_is_refused_by_its_place(tmp_path) -> None:
    """Defence in depth: a file in the copies' directory is refused by its
    identity whatever it holds, even where its bytes are not recognized as a
    copy's (here a token-bearing line with no marker and no record).
    Hard-linked under a served root, it is still never read out."""
    from opendox import console_access, serve

    state = _state(tmp_path)
    copy = _write(state)
    token = console_access.read_private_copy(copy.path)["console_token"]
    stray = copy.path.parent / f".{copy.path.name}.opendox-424242"
    stray.write_text(f"<a href=\"{copy.opened_url}\">\n", encoding="utf-8")
    stray.chmod(0o600)
    assert token in stray.read_text(encoding="utf-8")
    served = tmp_path / "served"
    served.mkdir()
    os.link(stray, served / "stray.md")
    with open(served / "stray.md", "rb") as stream:
        assert not console_access.is_copy_bytes(stream.read()), "the case is vacuous"
    assert serve.read_unless_private(served / "stray.md", (copy.path.parent,)) is None
    console_access.remove_private_copy(copy)


# ---------------------------------------------------------------------------
# 21 — Copilot's review at 1e114a19 (r4179793524): a copy caught part way
#      through its write, in another state directory, and a file that grows
#      after it was judged
# ---------------------------------------------------------------------------

def _partial_copy_bytes(tmp_path: Path) -> tuple[bytes, str]:
    """A real copy's bytes, cut just after the token's first appearance (the
    meta refresh), before the record's element is written: what another
    plane's writer leaves for a moment in its temporary file."""
    from opendox import console_access

    scratch = _state(tmp_path / "scratch")
    copy = _write(scratch, port=7)
    data = copy.path.read_bytes()
    token = console_access.read_private_copy(copy.path)["console_token"]
    console_access.remove_private_copy(copy)
    cut = data.index(token.encode()) + len(token)
    assert b"</script>" not in data[:cut], "the cut is not part way"
    return data[:cut], token


def test_a_copy_starts_with_its_marker_before_any_token_byte(tmp_path) -> None:
    """r4179793524: every copy is written from `COPY_MARKER`, so any part of
    one that holds a byte of the token holds the whole marker first, and is
    known for a copy (`is_copy_bytes`); fewer bytes than the marker hold no
    token and are not."""
    from opendox import console_access

    copy = _write(_state(tmp_path))
    data = copy.path.read_bytes()
    token = console_access.read_private_copy(copy.path)["console_token"].encode()
    assert data.startswith(console_access.COPY_MARKER)
    assert data.index(token) >= len(console_access.COPY_MARKER)
    for cut in range(len(console_access.COPY_MARKER), len(data) + 1, 37):
        assert console_access.is_copy_bytes(data[:cut]), cut
    for cut in range(len(console_access.COPY_MARKER)):
        assert token not in data[:cut]
        assert not console_access.is_copy_bytes(data[:cut]), cut
    assert not console_access.is_copy_bytes(b"# a document\n")
    console_access.remove_private_copy(copy)


def test_another_state_directorys_partial_copy_is_never_served(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """r4179793524, Copilot's layout: plane B's writer has its temporary file
    part written, the token in its meta refresh and no record yet, in B's own
    state directory. Plane A's `--web-dir` links there, A's checkout holds a
    hard link to it, and A's snapshot file is one too. The static handler,
    `/source` and `/snapshot.json` all refuse it, for GET and HEAD."""
    import shutil as _shutil

    from opendox import console_access, serve

    partial, token = _partial_copy_bytes(tmp_path)
    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state_a = _state(tmp_path / "a")
    state_b = _state(tmp_path / "b")
    console_b = state_b / console_access.CONSOLE_DIRNAME
    console_b.mkdir(mode=0o700)
    temporary = console_b / ".9.html.opendox-4242"
    temporary.write_bytes(partial)
    temporary.chmod(0o600)
    (web / "state-b").symlink_to(state_b)
    httpd, repo, worker = _guarded_plane(tmp_path, monkeypatch, web=web)
    try:
        base = httpd.server_address[:2]
        own = console_access.publish(
            httpd, page_url=serve.server_url(httpd, "/index.html"),
            env={"OPENDOX_STATE_DIR": str(state_a)})
        os.link(temporary, repo / "partial.md")
        snapshot = tmp_path / "snapshot.json"
        snapshot.unlink()
        os.link(temporary, snapshot)
        for path in (f"/state-b/console/{temporary.name}", "/source/partial.md",
                     "/snapshot.json"):
            for method in ("GET", "HEAD"):
                status, headers, raw = _call(base, method, path)
                assert token.encode() not in raw, (method, path, status)
                assert all(token not in str(v) for v in headers.values()), path
                assert status != 200, (method, path, status)
        assert token.encode() not in _raw_get(base, f"/state-b/console/{temporary.name}")
        assert _call(base, "GET", "/index.html")[0] == 200
        console_access.remove_private_copy(own)
    finally:
        _stop_plane(httpd, worker)


def test_a_file_that_grows_after_its_static_check_never_sends_a_token(
        tmp_path, monkeypatch, standalone_profile) -> None:
    """r4179793524, a file that grows: when the static handler judges it, both
    before the stdlib opens it and after, the other plane's temporary file
    holds only the start of the marker, and no token; it grows to hold one
    right after the second judgment, before the body is copied. The body
    sent is judged again as it is read, and never carries the token, whatever
    reaches the wire."""
    import shutil as _shutil

    from opendox import console_access

    partial, token = _partial_copy_bytes(tmp_path)
    first = partial[:10]
    web = tmp_path / "web"
    _shutil.copytree(WEB, web)
    state_b = _state(tmp_path / "b")
    console_b = state_b / console_access.CONSOLE_DIRNAME
    console_b.mkdir(mode=0o700)
    growing = console_b / ".9.html.opendox-4242"
    growing.write_bytes(first)
    growing.chmod(0o600)
    (web / "state-b").symlink_to(state_b)
    real = console_access.is_private_file
    judged: list[bool] = []
    grown: list[int] = []

    def then_grow(handle, roots):
        answer = real(handle, roots)
        info = os.fstat(handle)
        if (info.st_dev, info.st_ino) == (growing.stat().st_dev,
                                          growing.stat().st_ino):
            judged.append(answer)
            if len(judged) == 2 and not grown:      # after the backstop
                grown.append(1)
                with open(growing, "ab") as more:
                    more.write(partial[len(first):])
        return answer

    httpd, _repo, worker = _guarded_plane(tmp_path, monkeypatch, web=web)
    try:
        base = httpd.server_address[:2]
        own = console_access.publish(
            httpd, page_url="http://127.0.0.1:%d/index.html" % base[1],
            env={"OPENDOX_STATE_DIR": str(_state(tmp_path / "a"))})
        monkeypatch.setattr(console_access, "is_private_file", then_grow)
        raw = _raw_get(base, f"/state-b/console/{growing.name}")
        assert grown and judged == [False, False], ("the growth was never "
                                                    "staged after both checks", judged)
        assert token.encode() not in raw
        console_access.remove_private_copy(own)
    finally:
        _stop_plane(httpd, worker)


def test_a_copy_replaced_after_its_read_is_never_returned(
        tmp_path, monkeypatch) -> None:
    """r4179793524, the other way round: the bytes read are a copy's, and the
    file is emptied right after the read, before anything judges it by its
    descriptor. What was read is judged too, so the copy's bytes are never
    returned."""
    from opendox import console_access, serve

    own = _write(_state(tmp_path / "a"))
    other = _write(_state(tmp_path / "b"), port=9)
    token = console_access.read_private_copy(other.path)["console_token"]
    served = tmp_path / "served.json"
    os.link(other.path, served)
    real_open = open
    emptied: list[int] = []

    class _EmptiedAfterRead:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, *args):
            data = self.stream.read(*args)
            os.truncate(served, 0)          # emptied right after the read
            emptied.append(1)
            return data

    def opening(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        return _EmptiedAfterRead(stream) if str(path) == str(served) else stream

    monkeypatch.setattr("builtins.open", opening)
    try:
        data = serve.read_unless_private(served, (own.path.parent,))
    finally:
        monkeypatch.undo()
    assert emptied, "the replacement was never staged"
    assert data is None or token.encode() not in data
    console_access.remove_private_copy(own)
    console_access.remove_private_copy(other)


def test_a_file_that_grows_after_its_read_check_never_returns_a_token(
        tmp_path, monkeypatch) -> None:
    """r4179793524, for `/source` and `/snapshot.json`'s reader: the file is
    read first and the bytes read are judged, so a file that holds no token
    when it is judged cannot hand one out after."""
    from opendox import console_access, serve

    partial, token = _partial_copy_bytes(tmp_path)
    own = _write(_state(tmp_path / "a"))
    growing = tmp_path / "growing.json"
    growing.write_bytes(partial[:10])
    real = console_access.is_private_file
    grown: list[int] = []

    def then_grow(handle, roots):
        answer = real(handle, roots)
        if not grown:
            grown.append(1)
            with open(growing, "ab") as more:
                more.write(partial[10:])
        return answer

    monkeypatch.setattr(console_access, "is_private_file", then_grow)
    data = serve.read_unless_private(growing, (own.path.parent,))
    assert grown, "the growth was never staged"
    assert data is None or token.encode() not in data
    monkeypatch.undo()
    assert serve.read_unless_private(growing, (own.path.parent,)) is None
    console_access.remove_private_copy(own)


# ---------------------------------------------------------------------------
# 22 — Copilot's review at a2e36652 (r4180089809): the page URL is judged
#      as a browser reads it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "http://evil.example\\@127.0.0.1:8080/index.html",
    "http://127.0.0.1:8080\\@evil.example/index.html",
    "http://evil.example@127.0.0.1:8080/index.html",
    "http://user:pass@127.0.0.1:8080/index.html",
    "http://127.0.0.1:8080/\\\\evil.example/index.html",
    "http://127.0.0.1:8080/\tindex.html",
    "http://127.0.0.1:99999/index.html",
    "http://127.0.0.1:8080:9/index.html",
], ids=["backslash-userinfo", "backslash-after-port", "userinfo", "user-and-password",
        "backslash-in-path", "control-character", "port-out-of-range", "two-ports"])
def test_a_page_url_a_browser_reads_as_another_host_is_refused(
        tmp_path, bad) -> None:
    """r4180089809, Copilot's case first: `urlsplit` reads
    `http://evil.example\\@127.0.0.1:8080/` as user information at
    `127.0.0.1`, and a browser, taking the backslash for a slash, navigates
    to `evil.example`, whose page could read the token's fragment. The
    authority must be a loopback host and an optional port, exactly, and a
    backslash or a control character anywhere is refused. Nothing is
    written."""
    from opendox import console_access

    token = _token()
    with pytest.raises(console_access.ConsoleAccessRefused):
        console_access.opened_url(bad, token)
    state = _state(tmp_path)
    with pytest.raises(console_access.ConsoleAccessRefused) as refused:
        console_access.write_private_copy(
            state, page_url=bad, port=8080, token=token, served_roots=())
    assert token not in str(refused.value)
    assert not (state / console_access.CONSOLE_DIRNAME).exists()


@pytest.mark.parametrize("good", [
    "http://127.0.0.1:8080/index.html", "http://[::1]:8080/index.html",
    "http://localhost:8080/index.html", "http://127.0.0.1/index.html"])
def test_every_loopback_page_url_a_plane_announces_is_accepted(good) -> None:
    """The spellings `serve.server_url` announces a plane at, with and
    without a port, are still accepted."""
    from opendox import console_access

    token = _token()
    assert console_access.opened_url(good, token).startswith(good + "#")
