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
import html.parser
import http.client
import json
import os
import re
import signal
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
    # A copy ANOTHER user owns, as this module's reader sees one: refused.
    real = os.getuid()
    monkeypatch.setattr(console_access.os, "getuid", lambda: real + 1)
    with pytest.raises(console_access.ConsoleAccessRefused, match="not by this user"):
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
            raced.append(_write(state, token=second_token))   # the replacement
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(console_access.os, "rename", racing)
    console_access.remove_private_copy(first)
    monkeypatch.undo()
    assert raced, "the race was never staged"
    record = console_access.read_private_copy(first.path)
    assert record["console_token"] == second_token
    assert sorted(p.name for p in first.path.parent.iterdir()) == [first.path.name]
    console_access.remove_private_copy(raced[0])
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
