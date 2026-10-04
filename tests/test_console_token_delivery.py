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
    from opendox import cli
    return cli.build_parser().parse_args([
        "generate-and-open", "--repo-root", str(repo), "--repository", "fixture",
        "--run-dir", str(tmp_path / "run"), "--port", "0", "--no-validate",
        "--no-serve", *extra])


def test_generate_and_open_hands_the_browser_a_file_and_prints_no_token(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
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


def test_no_open_prints_the_copy_path_and_opens_nothing(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
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


def test_generate_and_open_refuses_where_no_safe_copy_can_be_written(
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
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
    """A server restarted on the same port replaces its own earlier copy. The
    first server's removal at shutdown leaves the later copy in place."""
    from opendox import console_access

    state = _state(tmp_path)
    first = _write(state)
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
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
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
        tmp_path, monkeypatch, capsys, standalone_profile, kind) -> None:
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
        tmp_path, monkeypatch, capsys, standalone_profile) -> None:
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
    second_token = _token()
    _write(state, token=second_token)        # another serve's, over the first

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
    second_token, third_token = _token(), _token()
    _write(state, token=second_token)        # another serve's, over the first
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

    with console_access.terminate_as_interrupt(True):
        assert signal.getsignal(signal.SIGTERM) not in (signal.SIG_DFL, signal.SIG_IGN)
        with pytest.raises(KeyboardInterrupt):
            with console_access.deferred_termination():
                os.kill(os.getpid(), signal.SIGTERM)
                signal.pthread_sigmask(signal.SIG_BLOCK, [])   # deliver now
                reached = True                                  # not raised here
        assert reached
        with console_access.deferred_termination(raise_pending=False):
            os.kill(os.getpid(), signal.SIGTERM)
            signal.pthread_sigmask(signal.SIG_BLOCK, [])
        with console_access.deferred_termination():
            pass                                                # nothing left over


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
