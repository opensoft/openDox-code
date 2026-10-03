"""Every loopback route checks the `Host` (plan 034 T103; adversarial review 2,
M4 and L2).

THE DEFECT, as measured at openDox-code#77 `b1db1965`. DNS rebinding could read
the whole corpus: on a loopback serve, `GET /source/<doc>.md` with
`Host: evil.example:<port>` answered 200 with the document's text, and so did
`/snapshot.json` and the static bundle. Only `/capabilities` and the console
routes asked whether the `Host` named this serve, and `/capabilities` asked
only when a console token had been minted (L2): with no git identity a local
serve mints none, so its install block (the data directory, the socket
directory and the bundled server's pid, which name the OS user) went to any
`Host`.

THE RULE these cases hold (`serve.host_names_this_loopback_serve`, applied in
`DashboardHandler.parse_request`): on a loopback plane every request, whatever
its route or method, is refused unless it carries exactly ONE `Host` line
naming one of the plane's own loopback authorities at the BOUND port:
`127.0.0.1:<port>`, `localhost:<port>` in any case, and `[::1]:<port>` only
where the socket is bound to `::1`. The refusal is one fixed status and body
(`serve.FOREIGN_HOST_STATUS`, `serve.FOREIGN_HOST_BODY`) that never echoes the
`Host`. A hosted plane keeps its own rules.

1. The table of crafted `Host`s, on the pure predicate: every refused row is
   refused and every accepted row accepted, on an IPv4 bind, an IPv6 bind and
   port 80.
2. The same table across every route class of an IN-PROCESS server (the static
   bundle, `/snapshot.json`, `/source/*`, `/capabilities`, `/workbench/*`,
   every `/actions/*` route, a route a host contributes, HEAD, OPTIONS and
   other methods), with no console token minted (L2's configuration) and with
   one. A large refused body is drained, so the refusal arrives whole.
3. The table across every route class of a REAL standalone
   `python -m opendox.cli generate-and-open --local` serve, a child with
   neither sibling importable, with no identity and with one.
4. The browser path still works: every file the bundle ships, the JSON routes
   and a console request carrying the token and the page's own `Origin`, under
   both `Host` spellings a browser sends.
5. The mutants the table must kill, run against a LIVE server: a route class
   exempted from the gate (one per class), the port ignored, a suffix match, a
   prefix match, only the first `Host` line read, and a missing `Host`
   trusted. Each must produce at least one table violation, so a table that
   passed would have caught it.
6. A hosted plane (`--host 0.0.0.0`) is unchanged: a `Host` the loopback gate
   refuses is served there as before.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import http.server
import json
import os
import re
import socket
import threading
from pathlib import Path

import pytest

from opendox import serve
from route_extension import RouteBinding
from standalone_child import Child, fresh_repository, git, run_module

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
WEB = ROOT / "src" / "opendox" / "web"
DOCUMENT = "notes-rain-barrel-leak.md"

_URL = re.compile(r"^(http://([0-9.]+):([0-9]+))/index\.html$")


# ---------------------------------------------------------------------------
# the table of crafted Hosts
# ---------------------------------------------------------------------------

def _other_port(port: int) -> int:
    return port + 1 if port < 65535 else port - 1


def accepted_hosts(port: int) -> list[tuple[str, tuple[str, ...]]]:
    """`(id, Host lines)` a loopback serve on an IPv4 bind ACCEPTS."""
    return [
        ("ipv4-literal", (f"127.0.0.1:{port}",)),
        ("localhost", (f"localhost:{port}",)),
        ("LOCALHOST", (f"LOCALHOST:{port}",)),
        ("LocalHost", (f"LocalHost:{port}",)),
        # optional whitespace around a field value (RFC 9110 § 5.5)
        ("surrounding-whitespace", (f" 127.0.0.1:{port}\t",)),
    ]


def refused_hosts(port: int) -> list[tuple[str, tuple[str, ...]]]:
    """`(id, Host lines)` a loopback serve on an IPv4 bind REFUSES. `()` is a
    request with no `Host` line at all."""
    good = f"127.0.0.1:{port}"
    evil = f"evil.example:{port}"
    other = _other_port(port)
    return [
        ("evil.example", (evil,)),
        ("loopback-literal-prefix", (f"127.0.0.1.evil.example:{port}",)),
        ("localhost-prefix", (f"localhost.evil:{port}",)),
        ("localhost-suffix", (f"evil.localhost:{port}",)),
        ("loopback-literal-suffix", (f"evil127.0.0.1:{port}",)),
        ("userinfo-suffix", (f"evil.example@127.0.0.1:{port}",)),
        ("other-port", (f"127.0.0.1:{other}",)),
        ("localhost-other-port", (f"localhost:{other}",)),
        ("port-extended", (f"127.0.0.1:{port}0",)),
        ("port-zero-padded", (f"127.0.0.1:0{port}",)),
        ("no-port", ("127.0.0.1",)),
        ("localhost-no-port", ("localhost",)),
        ("empty", ("",)),
        ("missing", ()),
        ("duplicate-good-then-evil", (good, evil)),
        ("duplicate-evil-then-good", (evil, good)),
        ("duplicate-good-twice", (good, good)),
        ("ipv6-loopback-on-an-ipv4-bind", (f"[::1]:{port}",)),
        ("ipv6-mapped-ipv4", (f"[::ffff:127.0.0.1]:{port}",)),
        ("ipv6-long-form", (f"[0:0:0:0:0:0:0:1]:{port}",)),
        ("ipv6-unbracketed", (f"::1:{port}",)),
        ("trailing-dot", (f"localhost.:{port}",)),
        ("other-loopback-address", (f"127.0.0.2:{port}",)),
        ("short-ipv4", (f"127.1:{port}",)),
        ("any-address", (f"0.0.0.0:{port}",)),
    ]


# ---------------------------------------------------------------------------
# 1 — the predicate
# ---------------------------------------------------------------------------

PORT = 18772


@pytest.mark.parametrize("label,lines", accepted_hosts(PORT),
                         ids=[row[0] for row in accepted_hosts(PORT)])
def test_the_predicate_accepts_the_bound_authorities(label, lines) -> None:
    assert serve.host_names_this_loopback_serve(lines, PORT, "127.0.0.1"), label


@pytest.mark.parametrize("label,lines", refused_hosts(PORT),
                         ids=[row[0] for row in refused_hosts(PORT)])
def test_the_predicate_refuses_every_crafted_host(label, lines) -> None:
    assert not serve.host_names_this_loopback_serve(
        lines, PORT, "127.0.0.1"), label


def test_a_missing_host_line_is_refused_whichever_way_it_is_spelled() -> None:
    """`headers.get_all("Host")` answers None for a request with no `Host`."""
    assert not serve.host_names_this_loopback_serve(None, PORT, "127.0.0.1")
    assert not serve.host_names_this_loopback_serve((), PORT, "127.0.0.1")


def test_ipv6_loopback_is_an_authority_only_where_it_is_bound() -> None:
    v6 = (f"[::1]:{PORT}",)
    assert serve.host_names_this_loopback_serve(v6, PORT, "::1")
    assert not serve.host_names_this_loopback_serve(v6, PORT, "127.0.0.1")
    for _label, lines in accepted_hosts(PORT):
        assert serve.host_names_this_loopback_serve(lines, PORT, "::1")
    assert not serve.host_names_this_loopback_serve(
        (f"[::1]:{_other_port(PORT)}",), PORT, "::1")
    assert not serve.host_names_this_loopback_serve(
        (f"[::ffff:127.0.0.1]:{PORT}",), PORT, "::1")


def test_port_80_also_accepts_the_bare_names() -> None:
    """A browser omits the default port, so on port 80 the bare names are the
    authorities too (unchanged from before T103)."""
    for value in ("127.0.0.1", "localhost", "LOCALHOST", "127.0.0.1:80"):
        assert serve.host_names_this_loopback_serve((value,), 80, "127.0.0.1")
    assert not serve.host_names_this_loopback_serve(("[::1]",), 80, "127.0.0.1")
    assert serve.host_names_this_loopback_serve(("[::1]",), 80, "::1")
    assert not serve.host_names_this_loopback_serve(("evil.example",), 80,
                                                    "127.0.0.1")


def test_loopback_authorities_without_a_bound_host_is_unchanged() -> None:
    """The one-argument form every existing caller uses still answers every
    loopback spelling."""
    assert serve.loopback_authorities(PORT) == frozenset(
        {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"})
    assert serve.loopback_authorities(PORT, "127.0.0.1") == frozenset(
        {f"127.0.0.1:{PORT}", f"localhost:{PORT}"})


def test_the_refusal_is_fixed_and_names_no_host() -> None:
    body = json.loads(serve.FOREIGN_HOST_BODY)
    assert serve.FOREIGN_HOST_STATUS == 403
    assert body == {"ok": False, "error": "invalid_host",
                    "message": serve.FOREIGN_HOST_MESSAGE}


# ---------------------------------------------------------------------------
# the route classes, and one raw request
# ---------------------------------------------------------------------------

def _a_view_module() -> str:
    return "/views/" + sorted(p.name for p in (WEB / "views").glob("*.js"))[0]


def route_classes(*, contributed: bool) -> list[tuple[str, str, str]]:
    """`(id, method, target)`: one request per route class a loopback serve
    answers. The contributed rows exist only where the server was built with
    `_ProbeRoutes`."""
    rows = [
        ("static-root", "GET", "/"),
        ("static-index", "GET", "/index.html"),
        ("static-module", "GET", "/app.js"),
        ("static-view", "GET", _a_view_module()),
        ("static-stylesheet", "GET", "/styles.css"),
        ("static-missing", "GET", "/no-such-file.txt"),
        ("snapshot", "GET", "/snapshot.json"),
        ("snapshot-keyed", "GET", "/snapshot.json?repository=fixture&ref=main"),
        ("source", "GET", f"/source/{DOCUMENT}"),
        ("source-keyed", "GET", f"/source/fixture@main/{DOCUMENT}"),
        ("source-bare", "GET", "/source"),
        ("source-traversal", "GET", "/source/../../etc/passwd"),
        ("capabilities", "GET", "/capabilities"),
        ("project-register", "GET", "/project-register.json"),
        ("workbench-model-catalog", "GET", "/workbench/model-catalog"),
        ("workbench-model-intake", "GET", "/workbench/model-intake"),
        ("workbench-thread", "GET", "/workbench/thread"),
        ("head-static", "HEAD", "/index.html"),
        ("head-snapshot", "HEAD", "/snapshot.json"),
        ("head-source", "HEAD", f"/source/{DOCUMENT}"),
        ("head-capabilities", "HEAD", "/capabilities"),
        ("options", "OPTIONS", f"/source/{DOCUMENT}"),
        ("options-asterisk", "OPTIONS", "*"),
        ("put", "PUT", "/snapshot.json"),
        ("delete", "DELETE", "/snapshot.json"),
        ("post-notebook", "POST", serve.ACTIONS_NOTEBOOK_ROUTE),
        ("post-edit", "POST", serve.ACTIONS_EDIT_ROUTE),
        ("post-chat-turn", "POST", serve.ACTIONS_WORKBENCH_CHAT_TURN_ROUTE),
        ("post-document-abstract", "POST",
         serve.ACTIONS_WORKBENCH_DOCUMENT_ABSTRACT_ROUTE),
        ("post-model-intake", "POST", serve.ACTIONS_WORKBENCH_MODEL_INTAKE_ROUTE),
        ("post-model-approval", "POST",
         serve.ACTIONS_WORKBENCH_MODEL_APPROVAL_ROUTE),
        ("post-unknown-action", "POST", "/actions/no-such-action"),
        ("post-gate-verb", "POST", serve.ACTIONS_GATE_PREFIX + "promote"),
        ("post-refresh", "POST", serve.ACTIONS_REFRESH_ROUTE),
    ]
    if contributed:
        rows += [
            ("contributed-get", "GET", "/t103-probe.json"),
            ("contributed-get-prefix", "GET", "/t103-prefix/anything"),
            ("contributed-head", "HEAD", "/t103-probe.json"),
            ("contributed-post", "POST", "/actions/t103-probe"),
        ]
    return rows


#: The route classes whose answer to an ACCEPTED `Host` is a 200 with a body
#: from this serve, so the browser path is asserted to be intact on each.
READABLE = {"static-root", "static-index", "static-module", "static-view",
            "static-stylesheet", "snapshot", "snapshot-keyed", "source",
            "capabilities", "contributed-get", "contributed-get-prefix"}


def _raw(base: tuple[str, int], method: str, target: str,
         host_lines: tuple[str, ...], *, body: bytes | None = None,
         version: str = "HTTP/1.1") -> tuple[int, dict, bytes, bytes]:
    """One request written byte for byte, so a missing, empty or duplicated
    `Host` is exactly what the server receives. Answers `(status, headers,
    body, raw response)`; the connection is read to its close."""
    if body is None:
        body = b"{}" if method == "POST" else b""
    lines = [f"{method} {target} {version}"]
    lines += [f"Host: {value}" for value in host_lines]
    if body:
        lines += ["Content-Type: application/json",
                  f"Content-Length: {len(body)}"]
    lines.append("Connection: close")
    data = ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body
    with socket.create_connection(base, timeout=30) as connection:
        connection.sendall(data)
        chunks = []
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    response = b"".join(chunks)
    head, _sep, payload = response.partition(b"\r\n\r\n")
    status_line, *header_lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in header_lines:
        name, _colon, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return int(status_line.split(" ")[1]), headers, payload, response


def table_violations(base: tuple[str, int], routes, *, accepted=None,
                     refused=None) -> list[str]:
    """Every way the served answers break the rule, over `routes` and the
    crafted `Host`s (all of them unless narrowed). Empty means the table
    holds."""
    port = base[1]
    accepted = accepted_hosts(port) if accepted is None else accepted
    refused = refused_hosts(port) if refused is None else refused
    found = []
    for route, method, target in routes:
        for label, lines in refused:
            status, headers, payload, response = _raw(base, method, target, lines)
            expected = b"" if method == "HEAD" else serve.FOREIGN_HOST_BODY
            if status != serve.FOREIGN_HOST_STATUS or payload != expected:
                found.append(f"{route} with Host {label}: {status} "
                             f"{payload[:80]!r}")
                continue
            if headers.get("connection", "").lower() != "close":
                found.append(f"{route} with Host {label}: the refusal kept "
                             "the connection open")
            text = response.decode("latin-1")
            for value in lines:
                if value.strip() and value.strip() in text:
                    found.append(f"{route} with Host {label}: the refusal "
                                 f"echoes {value!r}")
        for label, lines in accepted:
            status, _headers, payload, _response = _raw(base, method, target,
                                                        lines)
            if payload == serve.FOREIGN_HOST_BODY:
                found.append(f"{route} with Host {label}: refused as foreign")
            elif route in READABLE and (status != 200 or not payload):
                found.append(f"{route} with Host {label}: {status}, "
                             f"{len(payload)} bytes")
    return found


# ---------------------------------------------------------------------------
# an in-process server, with a contributed route beside the core ones
# ---------------------------------------------------------------------------

class _ProbeColumn:
    """A host's contributed column: one exact GET, one prefix GET, one POST."""

    def _t103_probe(self, head_only):
        self._serve_bytes(b'{"probe": "contributed"}', serve.JSON_CTYPE,
                          head_only)

    def _t103_prefix(self, remainder, head_only):
        self._serve_bytes(json.dumps({"rest": remainder}).encode("utf-8"),
                          serve.JSON_CTYPE, head_only)

    def _t103_post(self):
        self._send_json(200, {"probe": "posted"})


class _ProbeRoutes:
    HANDLER_CONTRIBUTIONS = (_ProbeColumn,)

    def routes(self):
        return (RouteBinding("GET", "/t103-probe.json", False, "_t103_probe"),
                RouteBinding("GET", "/t103-prefix/", True, "_t103_prefix"),
                RouteBinding("POST", "/actions/t103-probe", False, "_t103_post"))


def _clean_environment(monkeypatch) -> None:
    """No `GIT_*` and no `XF_*` reaches the server or a child, and no user or
    system git configuration: the only identity is the repository's own."""
    for name in list(os.environ):
        if name.startswith(("GIT_", "XF_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.fixture(scope="module")
def corpora(tmp_path_factory):
    """Two fresh repositories over T050's fixture, one carrying a git identity
    and one carrying none, each with the snapshot `generate` writes."""
    made = {}
    for identity in (False, True):
        where = tmp_path_factory.mktemp("identity" if identity else "no-identity")
        repo = fresh_repository(PLAIN, where)
        if identity:
            git(repo, "config", "user.name", "fixture")
            git(repo, "config", "user.email", "fixture@example.invalid")
        out = where / "out" / "snapshot.json"
        child, status = run_module(
            where, "opendox.cli", "generate", "--repo-root", str(repo),
            "--repository", "fixture", "--output", str(out), "--no-validate")
        assert status == 0, child.stderr_text()
        made[identity] = (repo, out)
    return made


@pytest.fixture()
def in_process(corpora, monkeypatch):
    """`build(identity=..., host=...)`: a server built in process over one of
    the two repositories, with `_ProbeRoutes` contributed, served on a
    thread. Answers `(base, capabilities)`."""
    _clean_environment(monkeypatch)
    servers = []

    def build(*, identity: bool, host: str = serve.DEFAULT_HOST):
        repo, out = corpora[identity]
        httpd = serve.build_server(WEB, out, repo, host=host, port=0,
                                   route_extensions=(_ProbeRoutes(),))
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        servers.append((httpd, worker))
        base = ("127.0.0.1", httpd.server_address[1])
        status, _headers, payload, _raw_response = _raw(
            base, "GET", "/capabilities", (f"127.0.0.1:{base[1]}",))
        assert status == 200, (status, payload[:200])
        return base, json.loads(payload)

    try:
        yield build
    finally:
        for httpd, worker in servers:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=10)


# ---------------------------------------------------------------------------
# 2 — every route class of an in-process server
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("identity", [False, True],
                         ids=["no-token", "console-token"])
def test_every_route_class_refuses_a_foreign_host_in_process(
        in_process, identity) -> None:
    """With no identity no console token is minted, which is the
    configuration in which `/capabilities` used to skip its own check (L2)."""
    base, caps = in_process(identity=identity)
    assert ("console_token" in caps) is identity, sorted(caps)
    violations = table_violations(base, route_classes(contributed=True))
    assert violations == [], "\n".join(violations)


def test_a_refused_body_is_drained_so_the_refusal_arrives_whole(
        in_process) -> None:
    """A large declared body behind a foreign `Host`: the refusal is read in
    full, never lost to a reset of a socket closed with bytes unread."""
    base, _caps = in_process(identity=False)
    body = b'{"pad": "' + b"x" * (1024 * 1024) + b'"}'
    for _attempt in range(5):
        status, _headers, payload, _response = _raw(
            base, "POST", serve.ACTIONS_WORKBENCH_CHAT_TURN_ROUTE,
            (f"evil.example:{base[1]}",), body=body)
        assert (status, payload) == (serve.FOREIGN_HOST_STATUS,
                                     serve.FOREIGN_HOST_BODY)


def test_an_http_1_0_request_with_no_host_is_refused(in_process) -> None:
    """HTTP/1.0 lets a client omit `Host`. A loopback serve still answers
    only a request that names it."""
    base, _caps = in_process(identity=False)
    status, _headers, payload, _response = _raw(
        base, "GET", f"/source/{DOCUMENT}", (), version="HTTP/1.0")
    assert (status, payload) == (serve.FOREIGN_HOST_STATUS,
                                 serve.FOREIGN_HOST_BODY)
    status, _headers, payload, _response = _raw(
        base, "GET", f"/source/{DOCUMENT}", (f"127.0.0.1:{base[1]}",),
        version="HTTP/1.0")
    assert status == 200 and payload == (PLAIN / DOCUMENT).read_bytes()


# ---------------------------------------------------------------------------
# 3 — a real standalone `generate-and-open --local` serve
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("identity", [False, True],
                         ids=["no-identity", "identity"])
def test_every_route_class_refuses_a_foreign_host_on_a_real_local_serve(
        tmp_path, monkeypatch, identity) -> None:
    """`python -m opendox.cli generate-and-open --local --no-open`, a child
    with neither sibling importable (`standalone_child.Child`), its own state
    directory and its own bundled PostgreSQL server, which stops with it."""
    _clean_environment(monkeypatch)
    repo = fresh_repository(PLAIN, tmp_path)
    if identity:
        git(repo, "config", "user.name", "fixture")
        git(repo, "config", "user.email", "fixture@example.invalid")
    child = Child(tmp_path, "opendox.cli", "generate-and-open", "--local",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--port", "0", "--run-dir", str(tmp_path / "run"))
    try:
        match = child.wait_for_line(_URL)
        base = (match.group(2), int(match.group(3)))
        good = (f"127.0.0.1:{base[1]}",)
        status, _headers, payload, _response = _raw(base, "GET",
                                                    "/capabilities", good)
        assert status == 200, payload[:200]
        caps = json.loads(payload)
        # A STANDALONE plane never publishes its token on `/capabilities`
        # (plan 034 T104): with an identity one is minted and delivered
        # through the private copy the entry point wrote, and with none
        # there is no token and no copy.
        assert "console_token" not in caps, sorted(caps)
        from opendox import console_access
        copy = console_access.private_copy_path(child.state_dir, base[1])
        assert copy.exists() is identity, copy
        if identity:
            assert child.console_token(base[1])
        # L2's block, served to its own Host and to no other
        assert caps["install"]["mode"] == "local", caps.get("install")
        violations = table_violations(base, route_classes(contributed=False))
        assert violations == [], "\n".join(violations)
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()
    assert not child.state_dir.exists(), "the child's state dir outlived it"


# ---------------------------------------------------------------------------
# 4 — the browser path still works
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spelling", ["127.0.0.1", "localhost"])
def test_the_browser_path_still_works(in_process, spelling) -> None:
    """What a browser opened at `http://<spelling>:<port>/` sends: `http.client`
    writes `Host` from the address it connects to, exactly as a browser writes
    it from the URL. Every file the bundle ships answers 200, the JSON routes
    answer, and a console request with the token and the page's own `Origin`
    reaches its route rather than the gate."""
    base, _caps = in_process(identity=True)
    connect = (spelling, base[1])

    def get(path, headers=None):
        connection = http.client.HTTPConnection(*connect, timeout=30)
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    shipped = sorted(p.relative_to(WEB).as_posix()
                     for p in WEB.rglob("*") if p.is_file())
    assert len(shipped) > 30, shipped
    for name in shipped:
        status, payload = get("/" + name)
        assert status == 200 and payload == (WEB / name).read_bytes(), name
    status, payload = get("/")
    assert status == 200 and b"<html" in payload.lower()
    status, payload = get("/capabilities")
    assert status == 200
    caps = json.loads(payload)
    token = caps["console_token"]
    status, payload = get("/snapshot.json")
    assert status == 200 and json.loads(payload)["repository"] == "fixture"
    status, payload = get(f"/source/{DOCUMENT}")
    assert status == 200 and payload == (PLAIN / DOCUMENT).read_bytes()
    status, payload = get(serve.WORKBENCH_MODEL_CATALOG_ROUTE, {
        serve.CONSOLE_TOKEN_HEADER: token,
        "Origin": f"http://{spelling}:{base[1]}"})
    assert payload != serve.FOREIGN_HOST_BODY
    assert status == 200, payload[:300]


# ---------------------------------------------------------------------------
# 5 — the mutants the table kills, against a live server
# ---------------------------------------------------------------------------

def _gate_exempting(exempt):
    """A `parse_request` that skips the gate where `exempt(command, path)`."""

    def parse_request(self):
        if not http.server.BaseHTTPRequestHandler.parse_request(self):
            return False
        if (self.loopback and not exempt(self.command, self.path)
                and not self._trusted_console_host()):
            self._refuse_foreign_host()
            return False
        return True

    return parse_request


def _static(command, path):
    return (command in ("GET", "HEAD")
            and not path.startswith(("/source", "/snapshot", "/capabilities",
                                     "/workbench", "/project-register",
                                     "/t103-")))


ROUTE_CLASS_MUTANTS = {
    "static-exempted": _static,
    "source-exempted": lambda command, path: path.startswith("/source"),
    "snapshot-exempted": lambda command, path: path.startswith("/snapshot.json"),
    "capabilities-exempted": lambda command, path: path == "/capabilities",
    "workbench-exempted": lambda command, path: path.startswith("/workbench/"),
    "post-exempted": lambda command, path: command == "POST",
    "head-exempted": lambda command, path: command == "HEAD",
    "other-methods-exempted": lambda command, path: command not in (
        "GET", "HEAD", "POST"),
    "contributed-exempted": lambda command, path: "t103-" in path,
}


def _authority_split(value: str) -> tuple[str, str]:
    host, _colon, port = value.rpartition(":")
    return (host, port) if _colon else (value, "")


def _port_ignored(lines, port, bound_host=None):
    lines = list(lines or ())
    if len(lines) != 1:
        return False
    host, _port = _authority_split(lines[0].strip(" \t").lower())
    return host in {"127.0.0.1", "localhost"}


def _suffix_match(lines, port, bound_host=None):
    lines = list(lines or ())
    if len(lines) != 1:
        return False
    value = lines[0].strip(" \t").lower()
    return any(value.endswith(authority) for authority in
               serve.loopback_authorities(port, bound_host))


def _prefix_match(lines, port, bound_host=None):
    lines = list(lines or ())
    if len(lines) != 1:
        return False
    host, value_port = _authority_split(lines[0].strip(" \t").lower())
    return (value_port == str(port)
            and host.startswith(("127.0.0.1", "localhost")))


def _first_line_only(lines, port, bound_host=None):
    lines = list(lines or ())
    return bool(lines) and lines[0].strip(" \t").lower() in \
        serve.loopback_authorities(port, bound_host)


def _missing_trusted(lines, port, bound_host=None):
    lines = list(lines or ())
    if not lines:
        return True
    return len(lines) == 1 and lines[0].strip(" \t").lower() in \
        serve.loopback_authorities(port, bound_host)


PREDICATE_MUTANTS = {
    "port-ignored": _port_ignored,
    "suffix-match": _suffix_match,
    "prefix-match": _prefix_match,
    "first-host-line-only": _first_line_only,
    "missing-host-trusted": _missing_trusted,
}


@pytest.mark.parametrize("mutant", sorted(ROUTE_CLASS_MUTANTS))
def test_the_table_kills_a_route_class_exempted_from_the_gate(
        in_process, monkeypatch, mutant) -> None:
    monkeypatch.setattr(serve.DashboardHandler, "parse_request",
                        _gate_exempting(ROUTE_CLASS_MUTANTS[mutant]))
    base, _caps = in_process(identity=False)
    port = base[1]
    narrowed = [row for row in refused_hosts(port)
                if row[0] in ("evil.example", "missing")]
    violations = table_violations(base, route_classes(contributed=True),
                                  accepted=[], refused=narrowed)
    assert violations, f"the table did not notice {mutant}"


@pytest.mark.parametrize("mutant", sorted(PREDICATE_MUTANTS))
def test_the_table_kills_a_loosened_host_test(in_process, monkeypatch,
                                              mutant) -> None:
    """Each mutant still accepts every accepted row, so it is a plausible
    loosening and not a broken server; the refused rows must catch it, on the
    predicate and on a live server alike."""
    loosened = PREDICATE_MUTANTS[mutant]
    for _label, lines in accepted_hosts(PORT):
        assert loosened(lines, PORT, "127.0.0.1"), (mutant, lines)
    caught = [label for label, lines in refused_hosts(PORT)
              if loosened(lines, PORT, "127.0.0.1")]
    assert caught, f"no refused row tells {mutant} apart from the rule"
    monkeypatch.setattr(serve, "host_names_this_loopback_serve", loosened)
    base, _caps = in_process(identity=False)
    violations = table_violations(
        base, [("source", "GET", f"/source/{DOCUMENT}")], accepted=[])
    assert violations, f"a live server did not show {mutant}"


# ---------------------------------------------------------------------------
# 6 — a hosted plane keeps its own rules
# ---------------------------------------------------------------------------

def test_a_hosted_plane_is_unchanged(in_process) -> None:
    """Off loopback the bind is `0.0.0.0` behind an ingress whose `Host` is
    the public name, so the loopback gate does not apply: a `Host` it would
    refuse is answered as before."""
    base, caps = in_process(identity=True, host="0.0.0.0")
    assert "console_token" not in caps and caps["actions"]["intent"] is True
    for host in (f"dashboard.example:{base[1]}", "dashboard.example"):
        for target in ("/index.html", "/snapshot.json", f"/source/{DOCUMENT}",
                       "/capabilities"):
            status, _headers, payload, _response = _raw(base, "GET", target,
                                                        (host,))
            assert status == 200 and payload != serve.FOREIGN_HOST_BODY, (
                host, target, status)
