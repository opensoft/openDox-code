"""AT-R1's HTTP harness, its DECISIONS tested in process (plan 034 T095).

`acceptance/at_r1_http.py` is not a member of this suite: it installs the
product into a fresh venv and drives it from outside, in its own `acceptance`
job, and `testpaths` never collects it. That is right for the harness, and it
left its verdict logic with no collected test. On this branch the acceptance
job stops at the missing `local` extra, before the module-graph walk ever
runs (Copilot review of openDox-code#75 at b440d12b, "previously missed").

So the decisions are tested here, as `tests/test_smoke_signals.py` tests the
browser half's oracle without a browser. The harness module is loaded from
its file, and an in-process server on loopback (the pattern
`test_model_provider_broker.py` uses) stands in for the product, so nothing
is installed or started:

  * the lexer finds a module's strings, and not the ones inside a comment or
    a regular expression;
  * an import specifier is told from a route literal, and a route is resolved
    against the page;
  * the module graph terminates on an import cycle and counts each module once;
  * a module refused as a DYNAMIC import is still judged where another module
    imports it STATICALLY (Copilot review of #75 at 1c064bb3, r4170450448);
  * a module the server serves must be served as JavaScript, and a linked
    stylesheet as `text/css`, a `charset` parameter aside (Copilot review of
    #75 at f29b4ddd, r4173769822 and r4173769844);
  * a malformed 200 catalog is a named failure, never an exception
    (r4170450491), and so is a catalog whose envelope the chat rail would
    not adopt (Copilot review of #75 at f0e0ffe1), and so is a catalog that
    answers a caller without the console token;
  * the console token is read as a standalone plane delivers it (plan 034
    T104; RULED openxFactory#656 `5963851934`): never from `/capabilities`,
    and only from the 0600 opener file the start names, whose meta-refresh
    carries it in the URL's FRAGMENT. Every way that delivery can be wrong
    is a named failure: no opener named, one somewhere else, one inside the
    served repository, one another user could read or replace, a token in
    the query, a forward to another plane, an opener left after the stop,
    and a token printed;
  * only a LIVE refresh forwards, as a browser that runs scripts parses the
    page: none inside a `<template>`, a `<noscript>` or a raw-text element,
    the first of a repeated attribute, `http-equiv` read exactly (Copilot
    review of #75 at 4809b3d2, r4174671390);
  * the opener's whole path is judged as T104 holds its own tree: the state
    directory is this user's and no one else can write it, and every
    directory above it is this user's or root's, sticky where others can
    write it; the harness refuses a TMPDIR that is not (r4174671426);
  * no line the harness prints quotes a console token, from the opener, its
    record or `/capabilities`, or the entry point's output (r4174621486,
    carried to every diagnostic), or a `/capabilities` payload (r4175016672);
    a payload nested past the JSON parser's depth is a named failure
    (r4175016692);
  * the raw `/capabilities` payload carries the token neither by name, at
    any depth, nor by value (T007 batch N);
  * the chat rail's thread read is never asked with a query, as a standalone
    plane's rail sends none, and the plane must contribute no branch-session
    column (openDox-code#85, the T102 follow-on);
  * the opener is read whole or refused, never judged by a truncated prefix
    (Copilot review of #75 at 82869769, r4177924060); no reason quotes the
    server's own bytes: a catalog body, a peer's error text, a `Content-Type`
    that is no plain MIME type (r4177924097); and the module graph resolves
    against the running server's origin, so an absolute same-origin URL is a
    path of this plane (r4177924129).
"""

from __future__ import annotations

import collections
import contextlib
import http.server
import importlib.util
import json
import os
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "acceptance" / "at_r1_http.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("at_r1_http_harness", HARNESS)
    module = importlib.util.module_from_spec(spec)
    # `dataclasses` resolves a class's module through `sys.modules`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


@contextlib.contextmanager
def served(files: dict[str, tuple[str, str]], guarded: frozenset = frozenset()):
    """A loopback server answering `files` (`path -> (content type, body)`,
    or `(content type, body, status)`, where a tuple of content types sends
    the header once for each), and 404 for anything else. A path in
    `guarded` answers 403 to a request without the console header, as the
    product's console check does. Yields its port."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            entry = files.get(self.path)
            if self.path in guarded and not self.headers.get(
                    harness.CONSOLE_TOKEN_HEADER):
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if entry is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = entry[1].encode("utf-8")
            self.send_response(entry[2] if len(entry) > 2 else 200)
            for value in ((entry[0],) if isinstance(entry[0], str)
                          else entry[0]):
                if value:
                    self.send_header("Content-Type", value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _page(*modules: str) -> str:
    scripts = "".join(f'<script type="module" src="{m}"></script>'
                      for m in modules)
    return f"<html><head>{scripts}</head></html>"


JS = "text/javascript"


def _failures(verdict) -> list[str]:
    return [failure.ident for failure in verdict.failures]


def test_the_lexer_skips_comments_and_regular_expressions() -> None:
    source = (
        '// const A = "/in-a-line-comment";\n'
        '/* const B = "/in-a-block-comment"; */\n'
        "const quote = /[\"']/g;\n"
        'const C = "/a-real-route";\n'
        "const D = `/source/${key}/${path}`;\n"
        "const E = 'single';\n"
    )
    values = [value for _quote, value, _before in
              harness.JsStrings(source).scan()]
    assert values == ["/a-real-route", "/source/", "single"], values


@pytest.mark.parametrize("source, value", [
    (r'"a\tb"', "a\tb"),
    (r'"\x41"', "A"),
    (r'"B"', "B"),
    (r'"\u{43}"', "C"),
    (r'"\u{1F600}"', "\U0001F600"),
    ('"line\\\ncontinued"', "linecontinued"),
    (r'"back\\slash"', "back\\slash"),
    (r'"\d\/"', "d/"),
    (r'"\0"', "\0"),
    (r'`./child.js`', "./child.js"),
    (r'"\uD83D\uDE00"', "\U0001F600"),
    (r'"\uD83D"', "\ufffd"),
    (r'"\uDE00\uD83D"', "\ufffd\ufffd"),
    (r'"\u{0000000041}"', "A"),
], ids=["tab", "hex", "unicode", "code-point", "astral", "continuation",
        "backslash", "identity", "nul", "template", "surrogate-pair",
        "lone-surrogate", "reversed-surrogates", "long-code-point"])
def test_the_lexer_reads_escapes_as_javascript_does(source: str,
                                                   value: str) -> None:
    """A specifier is read as the browser reads it (found while answering
    Copilot's review of #75 at 2dcb98d3, r4178069374)."""
    values = [found for _quote, found, _before in
              harness.JsStrings(f"const s = {source};\n").scan()]
    assert values == [value]


def test_an_import_specifier_is_told_from_a_route_literal() -> None:
    source = (
        'import { a } from "./a.js";\n'
        'export * from "./b.js";\n'
        'import "./c.js";\n'
        'const later = () => import("./d.js");\n'
        'const SNAPSHOT = "./snapshot.json";\n'
        'const READ = "/workbench/thread";\n'
        'const SHEET = "/styles.css";\n'
        'const PROSE = "/not a route";\n'
    )
    pending: collections.deque = collections.deque()
    routes: set[str] = set()
    harness._scan_module("/views/x.js", source.encode("utf-8"), pending, routes)
    assert list(pending) == [
        ("/views/a.js", True, "/views/x.js"),
        ("/views/b.js", True, "/views/x.js"),
        ("/views/c.js", True, "/views/x.js"),
        ("/views/d.js", False, "/views/x.js"),
    ]
    # A route is resolved against the PAGE (`/`), not the module that names it,
    # as `fetch` resolves it; a stylesheet and a sentence are not routes.
    assert routes == {"/snapshot.json", "/workbench/thread"}


def test_the_module_graph_terminates_on_a_cycle_and_counts_each_module_once() -> None:
    files = {
        "/app.js": (JS, 'import "./a.js";\nconst R = "/capabilities";\n'),
        "/a.js": (JS, 'import "./b.js";\nconst S = "/workbench/model-catalog";\n'),
        "/b.js": (JS, 'import "./a.js";\nimport "./app.js";\n'
                      'const KIND = "workbench-model-catalog";\n'),
    }
    verdict = harness.Verdict(keep_going=True)
    literals: set[str] = set()
    with served(files) as port:
        routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t", literals)
    assert _failures(verdict) == []
    assert modules == 3
    assert routes == ["/capabilities", "/workbench/model-catalog"]
    # every string literal of the graph is collected, the kind among them
    assert harness.CATALOG_KIND in literals


def test_a_dynamic_refusal_does_not_hide_a_static_import_of_the_same_path() -> None:
    files = {
        "/app.js": (JS, 'import("./missing.js").catch(() => null);\n'
                        'import { x } from "./child.js";\n'),
        "/child.js": (JS, 'import "./missing.js";\nexport const x = 1;\n'),
    }
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == ["t.bundle.module /missing.js"]
    assert modules == 2


@pytest.mark.parametrize("static", [True, False], ids=["static", "dynamic"])
@pytest.mark.parametrize("content_type", ["text/plain", "text/html",
                                          "application/json", ""])
def test_a_module_served_as_anything_but_javascript_is_a_named_failure(
        static: bool, content_type: str) -> None:
    importer = ('import "./child.js";\n' if static
                else 'import("./child.js").catch(() => null);\n')
    files = {"/app.js": (JS, importer),
             "/child.js": (content_type, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == ["t.bundle.module-type /child.js"]


@pytest.mark.parametrize("content_type", [
    "text/javascript", "text/javascript; charset=utf-8",
    "Application/JavaScript;charset=UTF-8", "text/ecmascript",
])
def test_every_javascript_type_essence_passes(content_type: str) -> None:
    files = {"/app.js": (content_type, 'import("./child.js");\n'),
             "/child.js": (content_type, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == []
    assert modules == 2


@pytest.mark.parametrize("content_type, expected", [
    ("text/css", []),
    ("text/css; charset=utf-8", []),
    ("text/plain", ["t.bundle.sheet-type /styles.css"]),
    ("text/html", ["t.bundle.sheet-type /styles.css"]),
    ("", ["t.bundle.sheet-type /styles.css"]),
])
def test_a_stylesheet_served_as_anything_but_css_is_a_named_failure(
        content_type: str, expected: list[str]) -> None:
    files = {"/app.js": (JS, "export const x = 1;\n"),
             "/styles.css": (content_type, "body { margin: 0; }\n")}
    page = ('<html><head><link rel="stylesheet" href="./styles.css">'
            '<script type="module" src="./app.js"></script></head></html>')
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, page, {}, verdict, "t")
    assert _failures(verdict) == expected


@pytest.mark.parametrize("importer, expected", [
    ('import "https://unreachable.invalid/app.js";\n',
     "t.bundle.external https://unreachable.invalid/app.js"),
    ('import("//unreachable.invalid/app.js").catch(() => null);\n',
     "t.bundle.external http://unreachable.invalid/app.js"),
    ('export { x } from "data:text/javascript,export const x = 1";\n',
     "t.bundle.external data:text/javascript,export const x = 1"),
], ids=["static-https", "dynamic-protocol-relative", "data-url"])
def test_an_import_from_outside_the_plane_is_a_named_failure(
        importer: str, expected: str) -> None:
    """Never fetched from loopback by its path, where the local `/app.js`
    would answer for it (Copilot review of #75 at 142d1352, previously
    missed)."""
    files = {"/app.js": (JS, importer)}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == [expected]


def test_a_page_link_from_outside_the_plane_is_a_named_failure() -> None:
    files = {"/app.js": (JS, "export const x = 1;\n"),
             "/styles.css": ("text/css", "body { margin: 0; }\n")}
    page = ('<html><head>'
            '<link rel="stylesheet" href="https://cdn.invalid/styles.css">'
            '<script type="module" src="https://cdn.invalid/app.js"></script>'
            '</head></html>')
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(port, page, {}, verdict, "t")
    assert _failures(verdict) == ["t.bundle.external https://cdn.invalid/styles.css",
                                  "t.bundle.external https://cdn.invalid/app.js"]
    assert modules == 0


@pytest.mark.parametrize("importer, expected", [
    ('import "child.js";\n', "t.bundle.bare child.js"),
    ('import("child.js").catch(() => null);\n', "t.bundle.bare child.js"),
    ('export { x } from "lib/child.js";\n', "t.bundle.bare lib/child.js"),
    ('import { x } from "child";\n', "t.bundle.bare child"),
], ids=["static", "dynamic", "export-from", "package-name"])
def test_a_bare_specifier_is_a_named_failure(importer: str,
                                             expected: str) -> None:
    """With no import map, a browser refuses a specifier that is neither a
    URL nor `/`, `./` or `../`-led, though `/child.js` is served (Copilot
    review of #75 at 27479495, r4174411680)."""
    files = {"/app.js": (JS, importer),
             "/child.js": (JS, "export const x = 1;\n"),
             "/lib/child.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == [expected]
    assert modules == 1                 # never fetched by its path


@pytest.mark.parametrize("specifier", ["./child.js", "../views/child.js",
                                       "/views/child.js"],
                         ids=["dot-slash", "dot-dot-slash", "absolute-path"])
def test_every_relative_specifier_resolves(specifier: str) -> None:
    files = {"/views/app.js": (JS, f'import "{specifier}";\n'),
             "/views/child.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(
            port, _page("/views/app.js"), {}, verdict, "t")
    assert _failures(verdict) == []
    assert modules == 2


def test_a_dynamic_refusal_alone_is_not_a_failure() -> None:
    """10.2a's case: `intent-feed.js` is not owed, its importer degrades."""
    files = {"/app.js": (JS, 'import("./intent-feed.js").catch(() => null);\n')}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == []


class _Server:
    """The two attributes `check_catalog` reads off a launched server."""

    label = "t"

    def __init__(self, port: int) -> None:
        self.port = port


_ENVELOPE = '"schema_version": 1, "kind": "workbench-model-catalog"'
_NOT_A_CATALOG = ["t.catalog is a catalog",
                  "t.catalog envelope is the one the chat rail adopts"]
_WRONG_ENVELOPE = ["t.catalog envelope is the one the chat rail adopts"]


@pytest.mark.parametrize("body, expected", [
    ("[]", _NOT_A_CATALOG),
    ("null", _NOT_A_CATALOG),
    ('{"models": 1}', _NOT_A_CATALOG),
    ("not json", _NOT_A_CATALOG),
    ('{%s, "models": [1, {"model_id": "m", "available": true}]}' % _ENVELOPE,
     ["t.catalog offers no available entry"]),
    ('{%s, "models": [{"model_id": "m", "available": false}]}' % _ENVELOPE, []),
    ('{%s, "models": []}' % _ENVELOPE, []),
    # every JSON number equal to 1 is the one `=== 1` adopts (Copilot review
    # of #75 at 1c0ff975, r4173473346)
    ('{"schema_version": 1.0, "kind": "workbench-model-catalog", "models": []}',
     []),
    ('{"schema_version": 1e0, "kind": "workbench-model-catalog", "models": []}',
     []),
    ('{"schema_version": 10E-1, "kind": "workbench-model-catalog", "models": []}',
     []),
    # the envelopes `adoptCatalog` refuses (Copilot review of #75 at f0e0ffe1)
    ('{"models": []}', _WRONG_ENVELOPE),
    ('{"schema_version": 1, "models": []}', _WRONG_ENVELOPE),
    ('{"kind": "workbench-model-catalog", "models": []}', _WRONG_ENVELOPE),
    ('{"schema_version": 2, "kind": "workbench-model-catalog", "models": []}',
     _WRONG_ENVELOPE),
    ('{"schema_version": true, "kind": "workbench-model-catalog", "models": []}',
     _WRONG_ENVELOPE),
    ('{"schema_version": "1", "kind": "workbench-model-catalog", "models": []}',
     _WRONG_ENVELOPE),
    ('{"schema_version": 1.5, "kind": "workbench-model-catalog", "models": []}',
     _WRONG_ENVELOPE),
    ('{"schema_version": null, "kind": "workbench-model-catalog", "models": []}',
     _WRONG_ENVELOPE),
    ('{"schema_version": 1, "kind": "workbench-model-catalog-v2", "models": []}',
     _WRONG_ENVELOPE),
])
def test_a_malformed_catalog_is_a_named_failure_never_an_exception(
        body: str, expected: list[str]) -> None:
    files = {harness.CATALOG_ROUTE: ("application/json", body)}
    verdict = harness.Verdict(keep_going=True)
    with served(files, guarded=frozenset({harness.CATALOG_ROUTE})) as port:
        harness.check_catalog(_Server(port), "token", verdict)
    assert _failures(verdict) == expected


def test_a_catalog_that_answers_without_the_token_is_a_named_failure() -> None:
    """The token the opener carries must be the thing that opens the
    catalog, or reading it proves nothing."""
    files = {harness.CATALOG_ROUTE: ("application/json",
                                     '{%s, "models": []}' % _ENVELOPE)}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.check_catalog(_Server(port), "token", verdict)
    assert _failures(verdict) == [
        "t.catalog refuses a caller without the console token"]


# ---------------------------------------------------------------------------
# The console token's delivery on a standalone plane (plan 034 T104).
# ---------------------------------------------------------------------------

PORT = 43123
TOKEN = "Zq3_token-of-a-standalone-console-0123456789"
#: The token with every character percent-encoded.
ENCODED = "".join(f"%{ord(c):02X}" for c in TOKEN)
FORWARD = f"http://127.0.0.1:{PORT}/index.html#console_token={TOKEN}"


def _record(target: str = FORWARD, **changes) -> dict:
    """The record T104's opener carries for a forward to `target`."""
    record = {"schema_version": 1, "kind": "opendox-console-access",
              "page_url": target.split("#", 1)[0], "opened_url": target,
              "port": PORT, "pid": 4242, "console_token": TOKEN}
    record.update(changes)
    return record


def _record_script(record) -> str:
    """As T104 embeds it: `<`, `>` and `&` escaped as JSON `\\u` escapes."""
    text = json.dumps(record, sort_keys=True)
    text = (text.replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))
    return ('<script type="application/json" id="opendox-console">'
            f"{text}</script>\n")


def _opener_page(*targets: str, records: list | None = None,
                 delay: str = "0;url=") -> str:
    """An opener as T104 writes one: a meta-refresh to each target, and the
    record of the first (or `records`, as given)."""
    metas = "".join(f'<meta http-equiv="refresh" content="{delay}{t}">\n'
                    for t in targets)
    if records is None:
        records = [_record(targets[0].replace("&amp;", "&"))] if targets else []
    scripts = "".join(_record_script(r) for r in records)
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">\n"
            f"{metas}<title>Opening openDox</title>\n{scripts}</head>"
            "<body></body></html>\n")


def _opener(tmp_path: Path, page: str | None = None, *, mode: int = 0o600,
            dir_mode: int = 0o700) -> tuple[Path, Path]:
    """`(state_dir, opener)`: `<state_dir>/console/<PORT>.html`.

    The opener's whole path is judged, to `/`, so every directory made here
    is set private whatever the umask, and a case changes only what it
    names."""
    state = tmp_path / "state"
    console = state / harness.CONSOLE_DIRNAME
    console.mkdir(parents=True)
    tmp_path.chmod(0o700)
    state.chmod(0o700)
    opener = console / f"{PORT}.html"
    opener.write_text(_opener_page(FORWARD) if page is None else page,
                      encoding="utf-8")
    opener.chmod(mode)
    console.chmod(dir_mode)
    return state, opener


def _printed(opener: Path) -> str:
    return (f"  serving http://127.0.0.1:{PORT}/index.html\n"
            f"  console {opener.as_uri()} (this user's private copy, mode "
            "0600: open it to open the console page again)\n"
            f"http://127.0.0.1:{PORT}/index.html\n")


#: What a plane launched as the harness launches it answers on: 127.0.0.1
#: alone, and `localhost`, which a browser resolves to it.
SERVED = ("127.0.0.1", "localhost")


def _read(state: Path, printed: str, served_root: Path | None = None,
          hosts: tuple[str, ...] = SERVED):
    verdict = harness.Verdict(keep_going=True)
    root = served_root if served_root is not None else state.parent / "repo"
    path, token = harness.check_console_opener(
        "t", PORT, printed, state, root, verdict, hosts=hosts)
    return _failures(verdict), path, token


PRIVATE = "t.console opener is private"
FRAGMENT = "t.console opener forwards with the token in its fragment"


@pytest.mark.parametrize("token", ["a" * 16, "Z_-9" * 128],
                         ids=["shortest", "longest"])
def test_a_token_at_the_page_s_bounds_is_delivered(tmp_path: Path,
                                                   token: str) -> None:
    target = f"http://127.0.0.1:{PORT}/index.html#console_token={token}"
    state, opener = _opener(tmp_path, _opener_page(
        target, records=[_record(target, console_token=token)]))
    failures, _path, delivered = _read(state, _printed(opener))
    assert failures == []
    assert delivered == token


def test_a_forward_to_a_host_the_plane_answers_on_is_delivered(
        tmp_path: Path) -> None:
    """`[::1]` is refused where the plane answers on 127.0.0.1 alone, and
    accepted where it answers there too."""
    target = f"http://[::1]:{PORT}/index.html#console_token={TOKEN}"
    state, opener = _opener(tmp_path, _opener_page(target))
    assert _read(state, _printed(opener))[0] == [FRAGMENT]
    failures, _path, token = _read(state, _printed(opener),
                                   hosts=("127.0.0.1", "::1", "localhost"))
    assert failures == []
    assert token == TOKEN


def test_the_hosts_a_plane_answers_on_are_probed() -> None:
    """`served_loopback_hosts` asks the socket, as the browser will."""
    with served({}) as port:
        assert harness.served_loopback_hosts(port) == ("127.0.0.1",
                                                       "localhost")
    assert harness.served_loopback_hosts(port) == ()


def test_the_opener_t104_writes_delivers_its_token(tmp_path: Path) -> None:
    state, opener = _opener(tmp_path)
    failures, path, token = _read(state, _printed(opener))
    assert failures == []
    assert path == opener
    assert token == TOKEN


@pytest.mark.parametrize("page", [
    # the forms a meta refresh may take, and an escaped `&` after the token
    _opener_page(FORWARD).replace("0;url=", "0; URL="),
    _opener_page(FORWARD).replace(f"url={FORWARD}", f"url='{FORWARD}'"),
    _opener_page(FORWARD + "&amp;then=1"),
    # the refresh forms a browser follows (the HTML standard's shared
    # declarative refresh steps)
    _opener_page(FORWARD, delay=" 0 , url = "),
    _opener_page(FORWARD, delay=".5;url="),
    _opener_page(FORWARD, delay="0; "),
    _opener_page(FORWARD).replace(f"url={FORWARD}",
                                  f"url=\'{FORWARD}\' trailing"),
    # the console page at `/` as well as `/index.html`
    _opener_page(f"http://127.0.0.1:{PORT}/#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}#console_token={TOKEN}"),
], ids=["spaced-upper-URL", "quoted", "escaped-ampersand", "comma-spaced",
        "fractional", "no-url-keyword", "quote-truncates", "root-page",
        "empty-path"])
def test_the_opener_is_read_as_a_browser_reads_its_refresh(
        tmp_path: Path, page: str) -> None:
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == []
    assert token == TOKEN


RECORD = "t.console opener record agrees with its forward"


@pytest.mark.parametrize("records", [
    [],
    [_record(), _record()],
    ["not json"],
    [["a", "list"]],
    [_record(kind="opendox-console")],
    [_record(schema_version=2)],
    [_record(schema_version="1")],
    [_record(port=PORT + 1)],
    [_record(port=str(PORT))],
    [_record(console_token=TOKEN[::-1])],
    [_record(opened_url=FORWARD.replace("index.html", "other.html"))],
    [_record(page_url=f"http://127.0.0.1:{PORT}/other.html")],
], ids=["none", "two", "not-json", "not-an-object", "kind", "version",
        "version-string", "port", "port-string", "token", "opened-url",
        "page-url"])
def test_a_record_that_disagrees_with_the_forward_is_a_named_failure(
        tmp_path: Path, records: list) -> None:
    page = _opener_page(FORWARD, records=records).replace(
        '"not json"', "not json")
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [RECORD]
    assert token == TOKEN


def test_a_record_escaped_as_t104_writes_it_agrees(tmp_path: Path) -> None:
    """A token-free `page_url` with every character T104 escapes in it."""
    target = f"http://127.0.0.1:{PORT}/index.html#console_token={TOKEN}"
    page = _opener_page(target, records=[_record(target, note="<&>")])
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == []
    assert token == TOKEN


#: The token with every character written as a JSON `\u` escape: the
#: parsed payload holds it, and the raw text never spells it.
_ESCAPED = "".join(f"\\u{ord(c):04x}" for c in TOKEN)
BY_NAME = "t.capabilities carries no console token"
BY_VALUE = "t.capabilities carries the opener's token nowhere"


@pytest.mark.parametrize("raw, named", [
    ('{"install": {"mode": "local"}}', False),
    ('{"console_token": "%s"}' % TOKEN, True),
    ('{"install": {"mode": "local", "console_token": "x"}}', True),
    ('{"views": {"views": [{"console_token": "x"}]}}', True),
    ('{"console\\u005ftoken": "x"}', True),
    ('{"fields": ["console_token"]}', True),
    ('{"console_token_hint": "x"}', True),
], ids=["absent", "top-level", "nested", "in-a-list", "escaped-key",
        "as-a-value", "in-a-longer-key"])
def test_a_published_token_name_anywhere_in_the_raw_payload_is_a_named_failure(
        raw: str, named: bool) -> None:
    """By name, at any depth, as quickstart.md § 3 asserts it on the RAW
    payload (T007 batch N), and in every parsed key, however escaped."""
    verdict = harness.Verdict(keep_going=True)
    harness.check_no_published_token("t", json.loads(raw), raw, verdict)
    assert _failures(verdict) == ([BY_NAME] if named else [])


@pytest.mark.parametrize("raw, carried", [
    ('{"install": {"mode": "local"}}', False),
    ('{"session": "%s"}' % TOKEN, True),
    ('{"install": {"note": "the token is %s"}}' % TOKEN, True),
    ('{"%s": 1}' % TOKEN, True),
    ('{"views": ["%s"]}' % TOKEN, True),
    ('{"session": "%s"}' % _ESCAPED, True),
    ('{"%s": 1}' % _ESCAPED, True),
    ('{"session": "%s"}' % TOKEN[::-1], False),
], ids=["absent", "another-key", "inside-a-value", "as-a-key", "in-a-list",
        "escaped-value", "escaped-key", "another-token"])
def test_the_opener_s_token_anywhere_in_the_raw_payload_is_a_named_failure(
        raw: str, carried: bool, capsys) -> None:
    """By value, under whatever name: neither the token nor the payload is
    quoted."""
    verdict = harness.Verdict(keep_going=True)
    verdict.keep_secret(TOKEN)
    harness.check_no_token_value("t", json.loads(raw), raw, TOKEN, verdict)
    assert _failures(verdict) == ([BY_VALUE] if carried else [])
    assert TOKEN not in capsys.readouterr().out


def test_no_opener_named_is_a_named_failure(tmp_path: Path) -> None:
    state, _opener_path = _opener(tmp_path)
    failures, path, token = _read(state, f"http://127.0.0.1:{PORT}/\n")
    assert failures == ["t.console opener printed"]
    assert (path, token) == (None, None)


def test_an_opener_somewhere_else_is_a_named_failure(tmp_path: Path) -> None:
    state, _ = _opener(tmp_path)
    _elsewhere, opener = _opener(tmp_path / "other")
    failures, _path, _token = _read(state, _printed(opener))
    assert failures == [
        "t.console opener is OPENDOX_STATE_DIR/console/<port>.html"]


def test_an_opener_inside_the_served_repository_is_a_named_failure(
        tmp_path: Path) -> None:
    state, opener = _opener(tmp_path)
    failures, _path, _token = _read(state, _printed(opener),
                                    served_root=tmp_path)
    assert failures == ["t.console opener is outside the served repository"]


@pytest.mark.parametrize("mode, dir_mode", [
    (0o644, 0o700),     # any user can read the token
    (0o640, 0o700),     # its group can
    (0o400, 0o700),     # not exactly 0600
    (0o600, 0o755),     # in a directory others can enter
    (0o600, 0o750),
    (0o600, 0o500),     # quickstart.md § 3 checks 0700 exactly
], ids=["file-0644", "file-0640", "file-0400", "dir-0755", "dir-0750",
        "dir-0500"])
def test_an_opener_others_can_reach_is_a_named_failure(
        tmp_path: Path, mode: int, dir_mode: int) -> None:
    state, opener = _opener(tmp_path, mode=mode, dir_mode=dir_mode)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [PRIVATE]
    assert token == TOKEN


def test_a_linked_opener_is_a_named_failure(tmp_path: Path) -> None:
    state, opener = _opener(tmp_path)
    real = tmp_path / "planted.html"
    opener.rename(real)
    opener.symlink_to(real)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [PRIVATE, FRAGMENT]     # and never followed to read
    assert token is None


def test_a_fifo_opener_is_a_named_failure_and_never_hangs(
        tmp_path: Path) -> None:
    """A FIFO with no writer would block a plain `open` for ever, before the
    verdict and the cleanup (Copilot review of #75 at 27479495, previously
    missed). It is refused as not private, and is not read."""
    state, opener = _opener(tmp_path)
    opener.unlink()
    os.mkfifo(opener, 0o600)
    outcome: dict = {}

    def read() -> None:
        outcome["result"] = _read(state, _printed(opener))

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout=10)
    if reader.is_alive():
        # Release the blocked reader so the run can end, then fail.
        with open(os.open(opener, os.O_WRONLY | os.O_NONBLOCK), "wb"):
            pass
        reader.join(timeout=5)
        pytest.fail("reading a FIFO opener blocked")
    failures, _path, token = outcome["result"]
    assert failures == [PRIVATE, FRAGMENT]
    assert token is None


def test_a_fifo_with_a_writer_is_never_read(tmp_path: Path) -> None:
    """Only a regular file is read: a FIFO that a writer has filled is
    refused by its descriptor, not read as the opener's page."""
    fifo = tmp_path / "opener.html"
    os.mkfifo(fifo, 0o600)
    holder = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)   # lets a writer open
    try:
        # A whole page waits in the pipe, and its writer has gone, so a
        # reader would get the page and then an end of file.
        writer = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
        os.write(writer, _opener_page(FORWARD).encode("utf-8"))
        os.close(writer)
        with pytest.raises(OSError):
            harness._read_without_following(fifo)
    finally:
        os.close(holder)


def test_a_hard_linked_opener_is_a_named_failure(tmp_path: Path) -> None:
    state, opener = _opener(tmp_path)
    os.link(opener, tmp_path / "second-name.html")
    failures, _path, _token = _read(state, _printed(opener))
    assert failures == [PRIVATE]


@pytest.mark.parametrize("page", [
    # the token in the QUERY, which a request line, a log and a Referer carry
    _opener_page(f"http://127.0.0.1:{PORT}/index.html?console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}/index.html?console_token={TOKEN}"
                 f"#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}/{TOKEN}/index.html"
                 f"#console_token={TOKEN}"),
    # a forward to another plane, or off loopback
    _opener_page(FORWARD.replace(str(PORT), str(PORT + 1))),
    _opener_page(FORWARD.replace("127.0.0.1", "example.com")),
    _opener_page(FORWARD.replace("http:", "https:")),
    # no token, an empty one, two of them, two forwards, or none
    _opener_page(f"http://127.0.0.1:{PORT}/index.html"),
    _opener_page(f"http://127.0.0.1:{PORT}/index.html#console_token="),
    _opener_page(FORWARD + f"&amp;console_token={TOKEN}"),
    _opener_page(FORWARD, FORWARD),
    _opener_page(),
    # what a browser reads differently from urllib.parse (Copilot review of
    # #75 at d53a7378, r4173842763 and r4173842811)
    _opener_page(f"http://example.invalid\\@127.0.0.1:{PORT}/index.html"
                 f"#console_token={TOKEN}"),
    _opener_page(f"http://{TOKEN}@127.0.0.1:{PORT}/index.html"
                 f"#console_token={TOKEN}"),
    _opener_page(f"http://user:{TOKEN}@127.0.0.1:{PORT}/index.html"
                 f"#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}/index.html\t#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}/ index.html#console_token={TOKEN}"),
    _opener_page(f"http://[broken:{PORT}/index.html#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:99999/index.html#console_token={TOKEN}"),
    # a delay that aborts the browser's refresh (Copilot review of #75 at
    # 5636eb8d, r4173894317)
    _opener_page(FORWARD, delay="invalid;url="),
    _opener_page(FORWARD, delay="-1;url="),
    _opener_page(FORWARD, delay="; url="),
    _opener_page(FORWARD, delay="url="),
    # a token the page's `takeDeliveredConsoleToken` discards (r4173894352)
    _opener_page(f"http://127.0.0.1:{PORT}/index.html#console_token=short"),
    _opener_page(f"http://127.0.0.1:{PORT}/index.html#console_token="
                 + "a" * 513),
    _opener_page(f"http://127.0.0.1:{PORT}/index.html#console_token="
                 "token.with.dots.0123456789"),
    _opener_page(f"http://127.0.0.1:{PORT}/index.html#console_token="
                 "token%2Bplus%2B0123456789"),
    # a page of this plane that is not the console, its record agreeing
    # (Copilot review of #75 at 486e426e, previously missed)
    _opener_page(f"http://127.0.0.1:{PORT}/missing.html#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}/snapshot.json#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}//index.html#console_token={TOKEN}"),
    # a percent-encoded copy of the token in the query or the path, which
    # the request line still carries (Copilot review of #75 at 142d1352,
    # r4174355680)
    _opener_page(f"http://127.0.0.1:{PORT}/index.html?extra={ENCODED}"
                 f"#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}/index.html?extra="
                 f"{ENCODED.replace('%', '%25')}#console_token={TOKEN}"),
    _opener_page(f"http://127.0.0.1:{PORT}/{ENCODED}/../index.html"
                 f"#console_token={TOKEN}"),
    # a loopback host the launched plane does not answer on (previously
    # missed at 142d1352)
    _opener_page(f"http://[::1]:{PORT}/index.html#console_token={TOKEN}"),
], ids=["query", "query-and-fragment", "path", "other-port", "off-loopback",
        "https", "no-token", "empty-token", "two-tokens", "two-forwards",
        "no-forward", "backslash", "userinfo-token", "userinfo-password",
        "tab", "space", "malformed-host", "port-out-of-range",
        "delay-word", "delay-negative", "delay-empty", "delay-absent",
        "token-short", "token-oversized", "token-dots", "token-plus",
        "page-missing", "page-snapshot", "page-double-slash",
        "query-encoded", "query-double-encoded", "path-encoded", "ipv6-unserved"])
def test_a_forward_that_leaks_or_misses_the_token_is_a_named_failure(
        tmp_path: Path, page: str) -> None:
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [FRAGMENT]
    assert token is None


@pytest.mark.parametrize("target", [
    f"http://example.invalid:{PORT}/{TOKEN}/index.html#console_token={TOKEN}",
    f"https://127.0.0.1:{PORT}/{TOKEN}#console_token={TOKEN}",
    f"http://{TOKEN}.example:{PORT}/#console_token={TOKEN}",
    f"http://[{TOKEN}:{PORT}/#console_token={TOKEN}",
    f"http://x\\{TOKEN}@127.0.0.1:{PORT}/#console_token={TOKEN}",
], ids=["path-elsewhere", "path-https", "host", "malformed", "backslash"])
def test_a_refused_forward_never_quotes_its_url(tmp_path: Path,
                                                target: str) -> None:
    """A refused destination is not quoted, because it may hold the token
    (Copilot review of #75 at d53a7378, r4173842794)."""
    state, opener = _opener(tmp_path, _opener_page(target))
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert [failure.ident for failure in verdict.failures] == [FRAGMENT]
    assert not any(TOKEN in str(failure) for failure in verdict.failures)


def test_an_unparseable_printed_location_is_a_named_failure(
        tmp_path: Path) -> None:
    """The product's output, so a named failure and never a harness error
    (Copilot review of #75 at d53a7378, r4173842805)."""
    state, _opener_path = _opener(tmp_path)
    failures, path, token = _read(
        state, "  console file://[broken/opener.html (this user's copy)\n")
    assert failures == ["t.console opener printed"]
    assert (path, token) == (None, None)


def test_a_record_reason_never_quotes_the_token(tmp_path: Path) -> None:
    page = _opener_page(FORWARD, records=[_record(kind=TOKEN, port=TOKEN)])
    state, opener = _opener(tmp_path, page)
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert [failure.ident for failure in verdict.failures] == [RECORD]
    assert not any(TOKEN in str(failure) for failure in verdict.failures)


def test_a_token_in_the_query_is_named_and_never_quoted(tmp_path: Path) -> None:
    state, opener = _opener(tmp_path, _opener_page(
        f"http://127.0.0.1:{PORT}/index.html?console_token={TOKEN}"
        f"#console_token={TOKEN}"))
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert [failure.ident for failure in verdict.failures] == [FRAGMENT]
    assert "QUERY" in verdict.failures[0].why
    assert not any(TOKEN in str(failure) for failure in verdict.failures)


def test_after_the_stop_the_opener_is_gone_and_the_token_was_never_printed(
        tmp_path: Path) -> None:
    state, opener = _opener(tmp_path)
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_gone("t", opener, TOKEN, _printed(opener), verdict)
    harness.check_console_gone("u", opener, TOKEN,
                               _printed(opener) + f"token {TOKEN}\n", verdict)
    opener.unlink()
    harness.check_console_gone("v", opener, TOKEN, _printed(opener), verdict)
    assert _failures(verdict) == ["t.stop removes the console opener",
                                  "u.stop removes the console opener",
                                  "u.console token never printed"]


def test_the_documented_start_is_the_readme_line_less_its_ellipsis() -> None:
    """The one command the openDox root README documents (T007 batch H's
    10.3 addendum): the harness runs these tokens, then fills the `…`."""
    assert harness.DOCUMENTED_START == "opendox generate-and-open --local …"
    assert harness.documented_prefix() == ["opendox", "generate-and-open",
                                           "--local"]
    assert json.dumps(harness.DOCUMENTED_INSTALL) == '"pip install \\"opendox[local]\\""'


# ---------------------------------------------------------------------------
# The stop's exit status (Copilot review of #75 at 142d1352, previously
# missed): 0, as `tests_runtime/test_bundled_postgres.py` requires.
# ---------------------------------------------------------------------------

class _StoppedProc:
    def __init__(self, rc) -> None:
        self.rc = rc

    def send_signal(self, _signal) -> None:
        pass

    def wait(self, timeout=None):
        if self.rc is None:
            raise harness.subprocess.TimeoutExpired("opendox", timeout)
        return self.rc


@pytest.mark.parametrize("rc, expected", [
    (0, []),
    (1, ["t.stop exits 0"]),
    (-15, ["t.stop exits 0"]),
    (None, ["t.stop exits 0"]),
], ids=["zero", "one", "sigterm", "timeout"])
def test_the_stop_must_exit_zero(tmp_path: Path, rc, expected) -> None:
    out, err = tmp_path / "out", tmp_path / "err"
    out.write_text("", encoding="utf-8")
    err.write_text("", encoding="utf-8")
    server = harness.Server("t", _StoppedProc(rc), PORT, out, err)
    ctx = types.SimpleNamespace(server_package=None,
                                state_dir=tmp_path / "state-of-no-server")
    ctx.state_dir.mkdir()
    verdict = harness.Verdict(keep_going=True)
    harness.stop_and_look(server, ctx, verdict)
    assert _failures(verdict) == expected


# ---------------------------------------------------------------------------
# Every document names its path (Copilot review of #75 at 33841d4a,
# r4174621535), and a diagnostic never echoes the entry point's output
# (r4174621486).
# ---------------------------------------------------------------------------

_HTML_INDEX = harness.Answer(200, {"content-type": "text/html; charset=utf-8"},
                             b"<html><body></body></html>", None)
_CAPS = json.dumps({"install": {"mode": "local"}})


def _snapshot_server(documents) -> dict:
    return {"/snapshot.json": ("application/json",
                               json.dumps({"kind": "opendox-snapshot",
                                           "documents": documents})),
            "/capabilities": ("application/json", _CAPS)}


@pytest.mark.parametrize("documents, expected", [
    ([{"path": "a.md"}, {"path": "b/c.md"}], []),
    ([{}], ["t.snapshot documents each name a path"]),
    ([{"path": ""}], ["t.snapshot documents each name a path"]),
    ([{"path": 1}], ["t.snapshot documents each name a path"]),
    (["a.md"], ["t.snapshot documents each name a path"]),
    ([{"path": "a.md"}, {"title": "no path"}],
     ["t.snapshot documents each name a path"]),
], ids=["named", "empty-object", "empty-path", "number-path", "string-entry",
        "one-of-two"])
def test_a_document_without_a_path_is_a_named_failure(
        tmp_path: Path, documents, expected) -> None:
    out, err = tmp_path / "out", tmp_path / "err"
    out.write_text("", encoding="utf-8")
    err.write_text("", encoding="utf-8")
    verdict = harness.Verdict(keep_going=True)
    with served(_snapshot_server(documents)) as port:
        server = harness.Server("t", None, port, out, err)
        harness.check_pages(server, _HTML_INDEX, verdict)
    assert _failures(verdict) == expected


def test_a_diagnostic_names_where_the_output_is_and_never_echoes_it(
        tmp_path: Path) -> None:
    out, err = tmp_path / "t-server.out", tmp_path / "t-server.err"
    out.write_text(f"  console file:///x\n  token {TOKEN}\n", encoding="utf-8")
    err.write_text(f"Traceback: {TOKEN}\n", encoding="utf-8")
    server = harness.Server("t", None, PORT, out, err)
    said = server.said()
    assert TOKEN not in said
    assert str(out) in said and str(err) in said
    # the after-stop check still reads all of it
    assert TOKEN in server.printed()


# ---------------------------------------------------------------------------
# Only a LIVE refresh forwards (Copilot review of #75 at 4809b3d2,
# r4174671390): a browser that runs scripts never acts on one inside a
# `<template>`, a `<noscript>` or a raw-text element, keeps the first of a
# repeated attribute, and reads `http-equiv` exactly.
# ---------------------------------------------------------------------------

_LIVE_META = f'<meta http-equiv="refresh" content="0;url={FORWARD}">'
_ELSEWHERE_META = ('<meta http-equiv="refresh" '
                   'content="0;url=http://example.invalid/">')


def _page_with(head: str, body: str = "") -> str:
    """An opener page whose refreshes are `head` and `body`, with T104's
    live record of `FORWARD`."""
    return ("<!doctype html>\n<html><head><meta charset=\"utf-8\">\n"
            f"{head}\n{_record_script(_record())}</head>"
            f"<body>{body}</body></html>\n")


@pytest.mark.parametrize("head, body", [
    (f"<template>{_LIVE_META}</template>", ""),
    (f"<noscript>{_LIVE_META}</noscript>", ""),
    ("", f"<noscript>{_LIVE_META}</noscript>"),
    ("", f"<template><div>{_LIVE_META}</div></template>"),
    ("", f"<template><template></template>{_LIVE_META}</template>"),
    (f"<template/>{_LIVE_META}", ""),
    (f"<title>{_LIVE_META}</title>", ""),
    (f"<style>{_LIVE_META}</style>", ""),
    (f'<script type="text/plain">{_LIVE_META}</script>', ""),
    ("", f"<textarea>{_LIVE_META}</textarea>"),
    ("", f"<xmp>{_LIVE_META}</xmp>"),
    ("", f"<iframe>{_LIVE_META}</iframe>"),
    ("", f"<noembed>{_LIVE_META}</noembed>"),
    ("", f"<noframes>{_LIVE_META}</noframes>"),
    ("", f"<select>{_LIVE_META}</select>"),
    ("", f"<plaintext></plaintext>{_LIVE_META}"),
    ("<frameset></frameset>", _LIVE_META),
], ids=["template", "noscript-head", "noscript-body", "template-nested-div",
        "template-in-template", "template-self-closed", "title", "style",
        "script", "textarea", "xmp", "iframe", "noembed", "noframes",
        "select", "plaintext", "frameset"])
def test_an_inert_refresh_forwards_nothing(tmp_path: Path, head: str,
                                          body: str) -> None:
    """The opener's one refresh sits where a browser never acts on it, so
    the user never reaches the console, and the run must say so."""
    state, opener = _opener(tmp_path, _page_with(head, body))
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [FRAGMENT]
    assert token is None


@pytest.mark.parametrize("head", [
    f"<template>{_ELSEWHERE_META}</template>{_LIVE_META}",
    f"<noscript>{_ELSEWHERE_META}</noscript>{_LIVE_META}",
    f"<title>Opening</title>{_LIVE_META}",
    # a tag inside text content opens nothing, so its own end tag closes it
    f"<noscript><template></noscript>{_LIVE_META}",
    f"<iframe><template></iframe>{_LIVE_META}",
    f"<textarea><template></textarea>{_LIVE_META}",
    _LIVE_META.replace(">", "/>"),
    _LIVE_META.replace('"refresh"', '"REFRESH"'),
], ids=["after-template", "after-noscript", "after-title",
        "noscript-holds-tags", "iframe-holds-tags", "textarea-holds-tags",
        "void-self-closed", "upper-case"])
def test_a_live_refresh_beside_inert_markup_is_delivered(tmp_path: Path,
                                                         head: str) -> None:
    state, opener = _opener(tmp_path, _page_with(head))
    failures, _path, token = _read(state, _printed(opener))
    assert failures == []
    assert token == TOKEN


@pytest.mark.parametrize("meta, delivered", [
    ('<meta http-equiv="refresh" content="0;url=http://example.invalid/" '
     f'content="0;url={FORWARD}">', False),
    (f'<meta http-equiv="refresh" content="0;url={FORWARD}" '
     'content="0;url=http://example.invalid/">', True),
    (f'<meta http-equiv="x" http-equiv="refresh" content="0;url={FORWARD}">',
     False),
    (f'<meta http-equiv=" refresh" content="0;url={FORWARD}">', False),
    (f'<meta http-equiv="refresh " content="0;url={FORWARD}">', False),
], ids=["first-content-elsewhere", "first-content-here", "first-equiv-other",
        "equiv-leading-space", "equiv-trailing-space"])
def test_a_refresh_is_read_by_its_first_attributes_exactly(
        tmp_path: Path, meta: str, delivered: bool) -> None:
    state, opener = _opener(tmp_path, _page_with(meta))
    failures, _path, token = _read(state, _printed(opener))
    assert failures == ([] if delivered else [FRAGMENT])
    assert token == (TOKEN if delivered else None)


@pytest.mark.parametrize("wrapper", ["template", "noscript"])
def test_an_inert_record_is_no_record(tmp_path: Path, wrapper: str) -> None:
    page = ("<!doctype html>\n<html><head>\n"
            f"{_LIVE_META}\n<{wrapper}>{_record_script(_record())}</{wrapper}>"
            "</head><body></body></html>\n")
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [RECORD]
    assert token == TOKEN


# ---------------------------------------------------------------------------
# The opener's whole path, as T104 holds its own tree (Copilot review of #75
# at 4809b3d2, r4174671426): the state directory is this user's and no one
# else can write it, and every directory above it is this user's or root's,
# sticky where others can write it.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state_mode, private", [
    (0o700, True),
    (0o755, True),
    (0o711, True),
    (0o777, False),
    (0o757, False),
    (0o775, False),
    (0o1777, False),
], ids=["0700", "0755", "0711", "0777", "other-writable", "group-writable",
        "sticky-0777"])
def test_a_state_directory_others_can_write_is_a_named_failure(
        tmp_path: Path, state_mode: int, private: bool) -> None:
    state, opener = _opener(tmp_path)
    state.chmod(state_mode)
    verdict = harness.Verdict(keep_going=True)
    path, token = harness.check_console_opener(
        "t", PORT, _printed(opener), state, tmp_path / "repo", verdict,
        hosts=SERVED)
    assert _failures(verdict) == ([] if private else [PRIVATE])
    assert token == TOKEN
    if not private:
        assert f"{state} is writable by" in verdict.failures[0].why


@pytest.mark.parametrize("above_mode, private", [
    (0o755, True),
    (0o700, True),
    (0o1777, True),
    (0o1770, True),
    (0o777, False),
    (0o775, False),
    (0o757, False),
], ids=["0755", "0700", "sticky-0777", "sticky-group", "0777",
        "group-writable", "other-writable"])
def test_a_directory_above_the_state_others_can_change_is_a_named_failure(
        tmp_path: Path, above_mode: int, private: bool) -> None:
    above = tmp_path / "above"
    state, opener = _opener(above)
    above.chmod(above_mode)
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert _failures(verdict) == ([] if private else [PRIVATE])
    if not private:
        assert verdict.failures[0].why.startswith(f"{above} is writable by")
        assert "not sticky" in verdict.failures[0].why


def test_a_symbolic_link_above_the_state_this_user_owns_is_followed(
        tmp_path: Path) -> None:
    """A link on the way that this user owns is this user's to point; the
    directories it leads to are judged as well."""
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    state, opener = _opener(tmp_path / "link")
    failures, _path, token = _read(state, _printed(opener))
    assert failures == []
    assert token == TOKEN
    real.chmod(0o777)
    assert _read(state, _printed(opener))[0] == [PRIVATE]


def test_a_link_s_target_is_judged_by_its_own_ancestors(tmp_path: Path) -> None:
    """A link this user owns may lead below a directory others can change;
    the resolved path's ancestors are judged as well as the written ones."""
    open_dir = tmp_path / "open"
    real = open_dir / "real"
    real.mkdir(parents=True)
    (tmp_path / "link").symlink_to(real)
    state, opener = _opener(tmp_path / "link")
    assert _read(state, _printed(opener))[0] == []
    open_dir.chmod(0o777)
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert _failures(verdict) == [PRIVATE]
    assert verdict.failures[0].why.startswith(f"{open_dir} is writable by")


def _owned_by(real, faked: Path, uid: int):
    """`real` (`os.lstat` or `os.stat`), answering `faked` as owned by
    `uid`: no test can chown, so another user's link or directory is told."""
    def answer(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        if Path(path) != faked:
            return info
        fields = list(info[:10])
        fields[4] = uid
        return os.stat_result(fields)
    return answer


def test_a_link_another_user_owns_above_the_state_is_a_named_failure(
        tmp_path: Path, monkeypatch) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    state, opener = _opener(link)
    stranger = os.getuid() + 4242
    monkeypatch.setattr(harness.os, "lstat",
                        _owned_by(os.lstat, link, stranger))
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert _failures(verdict) == [PRIVATE]
    assert verdict.failures[0].why == (
        f"{link} is a symbolic link owned by uid {stranger}, neither this "
        "user nor root, who could point it elsewhere")


@pytest.mark.parametrize("owner, private", [("root", True),
                                            ("stranger", False)])
def test_a_directory_above_the_state_another_user_owns_is_a_named_failure(
        tmp_path: Path, monkeypatch, owner: str, private: bool) -> None:
    above = tmp_path / "above"
    state, opener = _opener(above)
    uid = 0 if owner == "root" else os.getuid() + 4242
    monkeypatch.setattr(harness.os, "stat", _owned_by(os.stat, above, uid))
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert _failures(verdict) == ([] if private else [PRIVATE])
    if not private:
        assert verdict.failures[0].why == (
            f"{above} is owned by uid {uid}, neither this user nor root")


def test_a_state_directory_that_is_a_link_is_a_named_failure(
        tmp_path: Path) -> None:
    elsewhere, _opener_path = _opener(tmp_path / "elsewhere")
    state = tmp_path / "state"
    state.symlink_to(elsewhere)
    opener = state / harness.CONSOLE_DIRNAME / f"{PORT}.html"
    verdict = harness.Verdict(keep_going=True)
    harness.check_console_opener("t", PORT, _printed(opener), state,
                                 tmp_path / "repo", verdict, hosts=SERVED)
    assert _failures(verdict) == [PRIVATE]
    assert verdict.failures[0].why == f"{state} is a symbolic link"


@pytest.mark.parametrize("mode, refused", [(0o700, False), (0o1777, False),
                                           (0o777, True), (0o775, True)],
                         ids=["0700", "sticky", "0777", "group-writable"])
def test_the_harness_refuses_a_tmpdir_others_can_change(
        tmp_path_factory, monkeypatch, mode: int, refused: bool) -> None:
    """Before anything is installed, so the verdict on the opener's tree
    judges what the product made, never where TMPDIR pointed (exit 2)."""
    base = tmp_path_factory.mktemp("t")
    base.chmod(mode)
    monkeypatch.setattr(harness.tempfile, "tempdir", str(base))
    if refused:
        with pytest.raises(harness.HarnessError, match="set TMPDIR"):
            harness.prepare()
        assert list(base.iterdir()) == []      # nothing left behind
        return
    ctx = harness.prepare()
    try:
        assert ctx.state_dir.parent == base.resolve()
    finally:
        harness.shutil.rmtree(ctx.scratch, ignore_errors=True)
        harness.shutil.rmtree(ctx.state_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# No line the harness prints quotes a console token, or the entry point's
# output (Copilot review of #75 at 33841d4a, r4174621486, carried to every
# diagnostic).
# ---------------------------------------------------------------------------

def test_a_catalog_answer_that_echoes_the_token_never_prints_it(
        tmp_path: Path, capsys) -> None:
    """The catalog is asked with the token, so its answer may echo it, and
    no line quotes any of the answer's content (Copilot review of #75 at
    82869769, r4177924097)."""
    state, opener = _opener(tmp_path)
    echo = json.dumps({"error": f"unknown token {TOKEN}"})
    files = {harness.CATALOG_ROUTE: ("application/json", echo)}
    verdict = harness.Verdict(keep_going=True)
    _path, token = harness.check_console_opener(
        "t", PORT, _printed(opener), state, tmp_path / "repo", verdict,
        hosts=SERVED)
    with served(files, guarded=frozenset({harness.CATALOG_ROUTE})) as port:
        harness.check_catalog(_Server(port), token, verdict)
    verdict.report()
    out = capsys.readouterr().out
    assert "t.catalog is a catalog" in _failures(verdict)
    assert not any("unknown token" in str(failure)
                   for failure in verdict.failures)
    assert "unknown token" not in out and TOKEN not in out


#: The token with every character a JSON `\u` escape, which no literal
#: redaction finds and any reader decodes (r4177924097).
_ESCAPED_ECHO = '{"error": "unknown token %s"}' % "".join(
    f"\\u{ord(c):04x}" for c in TOKEN)


@pytest.mark.parametrize("status, failure", [
    (200, "t.catalog is a catalog"),
    (403, "t.catalog answers"),
], ids=["malformed-200", "refused-403"])
def test_a_catalog_answer_s_body_is_never_quoted(capsys, status: int,
                                                 failure: str) -> None:
    files = {harness.CATALOG_ROUTE: ("application/json", _ESCAPED_ECHO,
                                     status)}
    verdict = harness.Verdict(keep_going=True)
    verdict.keep_secret(TOKEN)
    with served(files) as port:
        harness.check_catalog(_Server(port), TOKEN, verdict)
    verdict.report()
    out = capsys.readouterr().out
    assert failure in _failures(verdict)
    assert not any("\\u00" in str(failed) or "unknown token" in str(failed)
                   for failed in verdict.failures)
    assert "\\u00" not in out and "unknown token" not in out


def test_every_token_the_opener_carries_is_kept_secret(tmp_path: Path) -> None:
    """A refused forward's token, and its record's, though none is delivered."""
    other = "Other_token-0123456789abcdef"
    page = _opener_page(
        f"http://127.0.0.1:{PORT}/index.html?console_token={TOKEN}"
        f"#console_token={TOKEN}",
        records=[_record(console_token=other)])
    state, opener = _opener(tmp_path, page)
    verdict = harness.Verdict(keep_going=True)
    _path, token = harness.check_console_opener(
        "t", PORT, _printed(opener), state, tmp_path / "repo", verdict,
        hosts=SERVED)
    assert token is None
    assert {TOKEN, other} <= verdict.secrets
    verdict.check("t.later", False, f"an answer echoed {TOKEN} and {other}")
    assert verdict.failures[-1].why == (
        f"an answer echoed {harness.REDACTED} and {harness.REDACTED}")


def _quiet_server(tmp_path: Path, port: int):
    out, err = tmp_path / "out", tmp_path / "err"
    out.write_text("", encoding="utf-8")
    err.write_text("", encoding="utf-8")
    return harness.Server("t", None, port, out, err)


def _pages(caps_payload: str) -> dict:
    return {"/snapshot.json": ("application/json",
                               json.dumps({"documents": [{"path": "a.md"}]})),
            "/capabilities": ("application/json", caps_payload)}


@pytest.mark.parametrize("caps", [
    {"console_token": TOKEN, "install": {"mode": "local"}},
    # Copilot review of #75 at ec95f451, r4175016672's example
    {"install": {"mode": "hosted", "console_token": TOKEN}},
    {"install": {"mode": "local"}, "a": [{"b": {"console_token": [TOKEN]}}]},
], ids=["top-level", "nested-in-install", "nested-in-a-list"])
def test_a_published_token_is_never_printed(tmp_path: Path, capsys,
                                            caps: dict) -> None:
    """Under its name at any depth, the token `/capabilities` publishes is
    kept out of every later line: here a view module the payload names by
    it, which step 8's walk reports."""
    payload = dict(caps, views={"views": [{"module": f"/views/{TOKEN}.js"}]})
    verdict = harness.Verdict(keep_going=True)
    with served(_pages(json.dumps(payload))) as port:
        _snapshot, got, _raw = harness.check_pages(
            _quiet_server(tmp_path, port), _HTML_INDEX, verdict)
        harness.derive_bundle(port, "<html></html>", got, verdict, "t")
    verdict.report()
    assert BY_NAME in _failures(verdict)
    assert f"t.bundle.module /views/{harness.REDACTED}.js" in _failures(verdict)
    assert TOKEN not in capsys.readouterr().out


@pytest.mark.parametrize("payload, failure", [
    (json.dumps({"install": {"mode": "hosted", "session": TOKEN}}),
     "t.capabilities install.mode == local"),
    (json.dumps([{"session": TOKEN}]), "t./capabilities is a JSON object"),
    (json.dumps(f"session {TOKEN}"), "t./capabilities is a JSON object"),
], ids=["install-block", "a-list", "a-string"])
def test_no_failure_quotes_a_capabilities_payload(tmp_path: Path, capsys,
                                                  payload: str,
                                                  failure: str) -> None:
    """A token under another name is unknown until step 6 reads the opener,
    so no step-5 reason quotes the payload at all (Copilot review of #75 at
    ec95f451, r4175016672: "use a fixed message")."""
    verdict = harness.Verdict(keep_going=True)
    with served(_pages(payload)) as port:
        with contextlib.suppress(harness.Failed):
            harness.check_pages(_quiet_server(tmp_path, port), _HTML_INDEX,
                                verdict)
    verdict.report()
    assert failure in _failures(verdict)
    assert not any(TOKEN in str(failed) for failed in verdict.failures)
    assert TOKEN not in capsys.readouterr().out


#: JSON nested past the parser's depth (Copilot review of #75 at ec95f451,
#: r4175016692): the product's answer, so a named failure, never exit 2.
_DEEP = "[" * 30000 + "]" * 30000


@pytest.mark.parametrize("route", ["/snapshot.json", "/capabilities"])
def test_a_page_nested_past_the_parser_s_depth_is_a_named_failure(
        tmp_path: Path, route: str) -> None:
    files = _pages(json.dumps({"install": {"mode": "local"}}))
    files[route] = ("application/json", _DEEP)
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        with pytest.raises(harness.Failed) as failed:
            harness.check_pages(_quiet_server(tmp_path, port), _HTML_INDEX,
                                verdict)
    assert failed.value.ident == f"t.{route} is a JSON object"
    assert failed.value.why.endswith("it is not JSON")


def test_a_catalog_nested_past_the_parser_s_depth_is_a_named_failure() -> None:
    files = {harness.CATALOG_ROUTE: ("application/json", _DEEP)}
    verdict = harness.Verdict(keep_going=True)
    with served(files, guarded=frozenset({harness.CATALOG_ROUTE})) as port:
        harness.check_catalog(_Server(port), "token", verdict)
    assert _failures(verdict) == _NOT_A_CATALOG


def test_one_serve_learns_the_opener_s_token_before_it_quotes_a_page(
        tmp_path: Path, monkeypatch, capsys) -> None:
    """`serve_one` reads the opener's tokens as soon as the start answers,
    so a payload carrying the token under another name (here the grouping
    field `/capabilities` names) prints none of it in step 5, and step 6
    still fails it by value. The start and the stop are stood in for."""
    caps = {"install": {"mode": "local"},
            "display": {"fields": {"grouping": {"field": TOKEN}}}}
    files = _pages(json.dumps(caps))
    files[harness.CATALOG_ROUTE] = ("application/json",
                                    '{%s, "models": []}' % _ENVELOPE)
    with served(files, guarded=frozenset({harness.CATALOG_ROUTE})) as port:
        target = f"http://127.0.0.1:{port}/index.html#console_token={TOKEN}"
        state = tmp_path / "state"
        console = state / harness.CONSOLE_DIRNAME
        console.mkdir(parents=True)
        tmp_path.chmod(0o700)
        state.chmod(0o700)
        console.chmod(0o700)
        opener = console / f"{port}.html"
        opener.write_text(_opener_page(target, records=[
            _record(target, port=port)]), encoding="utf-8")
        opener.chmod(0o600)
        server = _quiet_server(tmp_path, port)
        server.out.write_text(f"  console {opener.as_uri()}\n",
                              encoding="utf-8")
        monkeypatch.setattr(harness, "launch",
                            lambda *_args: (server, _HTML_INDEX))
        monkeypatch.setattr(harness, "stop_and_look", lambda *_a, **_k: None)
        verdict = harness.Verdict(keep_going=True)
        harness.serve_one("t", tmp_path / "repo",
                          types.SimpleNamespace(state_dir=state), verdict)
    verdict.report()
    failures = _failures(verdict)
    assert "t.snapshot fills the grouping station" in failures
    assert BY_VALUE in failures
    assert not any(TOKEN in str(failed) for failed in verdict.failures)
    assert TOKEN not in capsys.readouterr().out


def test_a_printed_path_other_than_the_expected_one_is_never_quoted(
        tmp_path: Path, capsys) -> None:
    """The printed path is the entry point's output: it may carry the token,
    so no reason quotes it, or a directory on it."""
    state, _opener_path = _opener(tmp_path)
    printed = f"  console /run/{TOKEN}/opener.html (this user's copy)\n"
    verdict = harness.Verdict(keep_going=True)
    path, token = harness.check_console_opener(
        "t", PORT, printed, state, tmp_path / "repo", verdict, hosts=SERVED)
    assert path == Path(f"/run/{TOKEN}/opener.html") and token is None
    assert _failures(verdict) == [
        "t.console opener is OPENDOX_STATE_DIR/console/<port>.html",
        PRIVATE, FRAGMENT]
    assert verdict.failures[1].why.startswith("the printed opener ")
    harness.check_console_gone("t", path, None, printed, verdict)
    assert not any(TOKEN in str(failure) for failure in verdict.failures)
    assert TOKEN not in capsys.readouterr().out


def test_a_printed_opener_elsewhere_is_judged_but_never_quoted(
        tmp_path: Path, capsys) -> None:
    """An opener that exists at a path the harness did not expect is still
    judged, and its path, which holds a value the harness does not know,
    is quoted by no reason, the stop's included."""
    other = "Path_token-0123456789abcdef"
    state, _expected = _opener(tmp_path / "expected")
    _elsewhere, printed_opener = _opener(tmp_path / other, mode=0o644)
    printed = _printed(printed_opener)
    verdict = harness.Verdict(keep_going=True)
    path, token = harness.check_console_opener(
        "t", PORT, printed, state, tmp_path / "repo", verdict, hosts=SERVED)
    assert (path, token) == (printed_opener, TOKEN)
    assert _failures(verdict) == [
        "t.console opener is OPENDOX_STATE_DIR/console/<port>.html", PRIVATE]
    assert verdict.failures[1].why == "the printed opener has mode 644, not 600"
    harness.check_console_gone("t", path, token, printed, verdict)
    assert _failures(verdict)[-1] == "t.stop removes the console opener"
    assert not any(other in str(failure) for failure in verdict.failures)
    assert other not in capsys.readouterr().out


def test_notes_and_the_report_are_redacted(capsys) -> None:
    verdict = harness.Verdict(keep_going=True)
    verdict.check("t.early", False, f"an early line with {TOKEN} in it")
    verdict.keep_secret(TOKEN)          # learned after the failure was kept
    verdict.note(f"GET /x?{TOKEN}")
    assert verdict.report() == 1
    out = capsys.readouterr().out
    assert f"GET /x?{harness.REDACTED}" in out
    report = out[out.index("AT-R1 HTTP half: FAIL"):]
    assert TOKEN not in report and harness.REDACTED in report


@pytest.mark.parametrize("value", [None, "", "short", 12345678901234567890,
                                   "a" * 15])
def test_a_short_or_non_string_value_is_never_kept(value) -> None:
    """A short value would blank words out of unrelated lines."""
    verdict = harness.Verdict(keep_going=True)
    verdict.keep_secret(value)
    assert verdict.secrets == set()
    assert verdict.redact("a short line") == "a short line"


def test_a_record_nested_past_the_parser_s_depth_is_a_named_failure(
        tmp_path: Path) -> None:
    """The product's output, so a named failure, never a harness error."""
    deep = "[" * 30000 + "]" * 30000
    page = _opener_page(FORWARD, records=[]).replace(
        "</head>", f'<script type="application/json" id="opendox-console">'
                   f"{deep}</script></head>")
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [RECORD]
    assert token == TOKEN


# ---------------------------------------------------------------------------
# The chat rail's thread read (openDox-code#85, the T102 follow-on; holder
# ruling F1 (i)): a standalone plane's rail sends none, so the harness asks
# none with a query, and asserts the plane contributes no branch-session
# column, the one condition under which the rail would.
# ---------------------------------------------------------------------------

_SNAPSHOT = {"repository": "fixture", "documents": [{"path": "a.md"}],
             "clusters": [{"id": "g1", "document_edges": [{"document": "a.md"}]}]}


def test_the_rail_s_thread_read_is_never_asked_with_a_query() -> None:
    """Only the bare literal, as every literal is asked; the `/`-ended
    prefix is still completed with each document."""
    targets = harness.requests_for(
        ["/source/", harness.THREAD_ROUTE, "/snapshot.json"], _SNAPSHOT)
    assert targets == ["/source/", "/source/a.md", "/source/fixture%40main/a.md",
                       harness.THREAD_ROUTE, "/snapshot.json"]


@pytest.mark.parametrize("caps, reads", [
    ({}, False),
    ({"views": {"views": []}}, False),
    ({"views": {"views": [{"id": "gate.bar", "module": "./g.js"}]}}, False),
    ({"views": [{"id": "gate.workbench.session"}]}, False),
    ({"views": {"views": [{"id": "gate.workbench.session",
                           "module": "./session.js"}]}}, True),
    ({"views": {"views": [{"id": "gate.bar"},
                          {"id": "gate.workbench.session"}]}}, True),
], ids=["no-views", "no-bindings", "another-column", "not-a-manifest",
        "session-column", "session-among-others"])
def test_a_contributed_session_column_is_a_named_failure(caps: dict,
                                                         reads: bool) -> None:
    verdict = harness.Verdict(keep_going=True)
    harness.check_no_thread_read("t", caps, verdict)
    assert _failures(verdict) == (
        ["t.chat rail reads no thread (no branch session)"] if reads else [])


def test_step_8_asserts_the_rail_reads_no_thread(tmp_path: Path) -> None:
    caps = {"views": {"views": [{"id": "gate.workbench.session"}]}}
    verdict = harness.Verdict(keep_going=True)
    with served({}) as port:
        harness.check_routes(_quiet_server(tmp_path, port), _HTML_INDEX,
                             _SNAPSHOT, caps, None, verdict)
    assert "t.chat rail reads no thread (no branch session)" in _failures(verdict)


# ---------------------------------------------------------------------------
# Copilot review of #75 at 82869769: the opener is read whole or refused
# (r4177924060); no reason quotes the server's own bytes (r4177924097); the
# module graph resolves against the running server's origin (r4177924129).
# ---------------------------------------------------------------------------

def _padded_to(page: str, size: int) -> str:
    """`page` with an HTML comment before its end, making it `size` bytes."""
    pad = size - len(page.encode("utf-8")) - len("<!---->")
    assert pad >= 0
    return page.replace("</html>", f"<!--{'x' * pad}--></html>")


def test_an_opener_past_the_read_limit_is_refused_never_truncated(
        tmp_path: Path) -> None:
    """A valid page within the limit, and a second record past it: read
    whole, the opener holds two records; truncated, it held one."""
    limit = harness.OPENER_READ_LIMIT
    page = _opener_page(FORWARD)
    head = _padded_to(page, limit).replace("</html>\n", "")
    oversized = head + "</html>\n" + _record_script(_record())
    assert len(head.encode("utf-8")) < limit < len(oversized.encode("utf-8"))
    state, opener = _opener(tmp_path, oversized)
    verdict = harness.Verdict(keep_going=True)
    _path, token = harness.check_console_opener(
        "t", PORT, _printed(opener), state, tmp_path / "repo", verdict,
        hosts=SERVED)
    assert _failures(verdict) == [FRAGMENT]
    assert token is None
    assert f"larger than the {limit} bytes" in verdict.failures[0].why


def test_an_opener_of_exactly_the_read_limit_is_read(tmp_path: Path) -> None:
    page = _padded_to(_opener_page(FORWARD), harness.OPENER_READ_LIMIT)
    assert len(page.encode("utf-8")) == harness.OPENER_READ_LIMIT
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == []
    assert token == TOKEN


def test_a_failed_request_is_named_without_the_server_s_bytes() -> None:
    import http.client
    line = f"HTTP/1.1 999 {TOKEN}"
    assert harness.error_name(http.client.BadStatusLine(line)) == "BadStatusLine"
    assert harness.error_name(
        ConnectionRefusedError(111, "Connection refused")) == (
        "ConnectionRefusedError: Connection refused")
    assert harness.error_name(TimeoutError()) == "TimeoutError"


@pytest.mark.parametrize("value, shown", [
    ("text/javascript; charset=utf-8", "'text/javascript'"),
    ("Text/HTML", "'text/html'"),
    (None, "no Content-Type"),
    ('text/x-\\u0041"; x=1', "a Content-Type that is no plain MIME type "
                            "(not quoted)"),
    ("text/" + "%41" * 3, "a Content-Type that is no plain MIME type "
                          "(not quoted)"),
], ids=["with-charset", "upper-case", "absent", "escaped", "percent"])
def test_a_content_type_is_quoted_only_as_a_plain_mime_type(value,
                                                           shown: str) -> None:
    headers = {} if value is None else {"content-type": value}
    assert harness.shown_type(harness.Answer(200, headers, b"", None)) == shown


@pytest.mark.parametrize("make", [
    lambda port: f'import "http://127.0.0.1:{port}/child.js";\n',
    lambda port: f'import("http://127.0.0.1:{port}/child.js");\n',
    lambda port: f'import "//127.0.0.1:{port}/child.js";\n',
], ids=["static-absolute", "dynamic-absolute", "protocol-relative"])
def test_an_absolute_same_origin_import_is_a_path_of_this_plane(make) -> None:
    files = {"/child.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        files["/app.js"] = (JS, make(port))
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == []
    assert modules == 2


def test_an_absolute_same_origin_stylesheet_is_a_path_of_this_plane() -> None:
    files = {"/app.js": (JS, "export const x = 1;\n"),
             "/styles.css": ("text/plain", "body { margin: 0; }\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        page = ('<html><head><link rel="stylesheet" '
                f'href="http://127.0.0.1:{port}/styles.css">'
                '<script type="module" src="./app.js"></script></head></html>')
        harness.derive_bundle(port, page, {}, verdict, "t")
    # fetched and judged as this plane's own sheet, never as external
    assert _failures(verdict) == ["t.bundle.sheet-type /styles.css"]


@pytest.mark.parametrize("make, expected", [
    (lambda port: f'import "http://localhost:{port}/child.js";\n',
     lambda port: f"t.bundle.external http://localhost:{port}/child.js"),
    (lambda port: f'import "http://127.0.0.1:{port + 1}/child.js";\n',
     lambda port: f"t.bundle.external http://127.0.0.1:{port + 1}/child.js"),
    (lambda port: f'import "https://127.0.0.1:{port}/child.js";\n',
     lambda port: f"t.bundle.external https://127.0.0.1:{port}/child.js"),
    (lambda port: 'import "http://[broken/child.js";\n',
     lambda port: "t.bundle.external unparseable:http://[broken/child.js"),
], ids=["another-host", "another-port", "another-scheme", "unparseable"])
def test_an_import_from_another_origin_is_still_external(make,
                                                         expected) -> None:
    files = {"/child.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        files["/app.js"] = (JS, make(port))
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
        wanted = expected(port)
    assert _failures(verdict) == [wanted]
    assert modules == 1


# ---------------------------------------------------------------------------
# Copilot review of #75 at 2dcb98d3: JSON as a browser parses it
# (r4178069345), and a reference a browser reads differently is refused,
# never resolved (r4178069374).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_catalog_with_a_non_json_constant_is_a_named_failure(
        constant: str) -> None:
    """`response.json()` refuses it, so the chat rail reads the catalog as
    unreadable, though `json.loads` admits it."""
    body = '{%s, "models": [], "extra": %s}' % (_ENVELOPE, constant)
    files = {harness.CATALOG_ROUTE: ("application/json", body)}
    verdict = harness.Verdict(keep_going=True)
    with served(files, guarded=frozenset({harness.CATALOG_ROUTE})) as port:
        harness.check_catalog(_Server(port), "token", verdict)
    assert _failures(verdict) == _NOT_A_CATALOG


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_page_with_a_non_json_constant_is_a_named_failure(
        tmp_path: Path, constant: str) -> None:
    files = _pages(json.dumps({"install": {"mode": "local"}}))
    files["/snapshot.json"] = (
        "application/json",
        '{"documents": [{"path": "a.md", "weight": %s}]}' % constant)
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        with pytest.raises(harness.Failed) as failed:
            harness.check_pages(_quiet_server(tmp_path, port), _HTML_INDEX,
                                verdict)
    assert failed.value.ident == "t./snapshot.json is a JSON object"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_record_with_a_non_json_constant_is_no_record(tmp_path: Path,
                                                        constant: str) -> None:
    record = json.dumps(_record(), sort_keys=True).replace(
        '"pid": 4242', f'"pid": {constant}')
    page = _opener_page(FORWARD, records=[]).replace(
        "</head>", '<script type="application/json" id="opendox-console">'
                   f"{record}</script></head>")
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    assert failures == [RECORD]
    assert token == TOKEN


@pytest.mark.parametrize("where", [
    "page-script", "stylesheet", "static", "dynamic", "view-module",
    "slash-backslash", "tab"])
def test_a_reference_a_browser_reads_differently_is_refused(where: str) -> None:
    """`external.invalid\\@127.0.0.1` goes to `external.invalid` in a
    browser, and `/\\host` to `host`; urllib.parse resolves both to this
    plane's own `/child.js`, which is served. Each is refused by name and
    never fetched."""
    files = {"/child.js": (JS, "export const x = 1;\n"),
             "/app.js": (JS, "export const x = 1;\n"),
             "/styles.css": ("text/css", "body { margin: 0; }\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        divergent = f"http://external.invalid\\@127.0.0.1:{port}/child.js"
        page, caps = _page("./app.js"), {}
        if where == "page-script":
            page = _page(divergent)
        elif where == "stylesheet":
            divergent = divergent.replace("child.js", "styles.css")
            page = page.replace(
                "<head>", f'<head><link rel="stylesheet" href="{divergent}">')
        elif where == "view-module":
            caps = {"views": {"views": [{"id": "x", "module": divergent}]}}
        else:
            if where == "slash-backslash":
                divergent = "/\\external.invalid/child.js"
            elif where == "tab":
                divergent = "./ch\tild.js"
            escaped = divergent.replace("\\", "\\\\").replace("\t", "\\t")
            files["/app.js"] = (JS, f'import("{escaped}");\n'
                                if where == "dynamic"
                                else f'import "{escaped}";\n')
        _routes, modules = harness.derive_bundle(port, page, caps, verdict,
                                                 "t")
    assert _failures(verdict) == [f"t.bundle.divergent {divergent!r}"]
    assert modules == (0 if where == "page-script" else 1)


# ---------------------------------------------------------------------------
# The self-pass after Copilot's review of #75 at 2dcb98d3: every parser
# reads as the browser reads, or refuses by name what it does not model.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body, expected", [
    (b"\xef\xbb\xbf" + ('{%s, "models": []}' % _ENVELOPE).encode(), []),
    (('{%s, "models": [], "note": "' % _ENVELOPE).encode() + b"\xff\"}", []),
    (b"\xef\xbb\xbf" + b"NaN", _NOT_A_CATALOG),
], ids=["leading-bom", "invalid-utf8-in-a-string", "bom-then-nan"])
def test_json_is_decoded_as_a_browser_decodes_it(body: bytes,
                                                 expected: list) -> None:
    """UTF-8 as the Encoding standard decodes it: a BOM dropped, an invalid
    byte read as U+FFFD, as `response.json()` does."""
    answer = harness.Answer(200, {"content-type": "application/json"}, body,
                            None)
    verdict = harness.Verdict(keep_going=True)

    class _Fixed:
        label, port = "t", 0
    original = harness.get
    try:
        harness.get = lambda _port, target, token=None: (
            answer if token else harness.Answer(403, {}, b"", None))
        harness.check_catalog(_Fixed(), "token", verdict)
    finally:
        harness.get = original
    assert _failures(verdict) == expected


@pytest.mark.parametrize("models, offered", [
    ('[{"model_id": "m", "available": true}]', ["m"]),
    ('[{"model_id": "m", "available": 1}]', []),
    ('[{"model_id": "m", "available": "true"}]', []),
    ('[{"model_id": "m", "available": [1]}]', []),
], ids=["true", "one", "a-string", "a-list"])
def test_an_entry_is_available_only_as_the_rail_reads_it(models: str,
                                                         offered: list) -> None:
    """`m.available === true` (`views/doxbench-chat-model.js`)."""
    body = '{%s, "models": %s}' % (_ENVELOPE, models)
    files = {harness.CATALOG_ROUTE: ("application/json", body)}
    verdict = harness.Verdict(keep_going=True)
    with served(files, guarded=frozenset({harness.CATALOG_ROUTE})) as port:
        harness.check_catalog(_Server(port), "token", verdict)
    assert _failures(verdict) == (
        ["t.catalog offers no available entry"] if offered else [])


@pytest.mark.parametrize("content_type, html", [
    ("text/html; charset=utf-8", True),
    ("TEXT/HTML", True),
    ("text/htmlx", False),
    ("application/xhtml+xml; profile=text/html", False),
    ("text/plain", False),
], ids=["html", "upper-case", "longer-type", "html-in-a-parameter", "plain"])
def test_the_page_is_html_by_its_type_s_essence(tmp_path: Path,
                                               content_type: str,
                                               html: bool) -> None:
    index = harness.Answer(200, {"content-type": content_type},
                           b"<html><body></body></html>", None)
    verdict = harness.Verdict(keep_going=True)
    with served(_snapshot_server([{"path": "a.md"}])) as port:
        harness.check_pages(_quiet_server(tmp_path, port), index, verdict)
    assert ("t.http / is HTML" in _failures(verdict)) is not html


@pytest.mark.parametrize("page, expected", [
    ('<script type="module" src="./ok.js" src="./missing.js"></script>', []),
    ('<script type="module" src="./missing.js" src="./ok.js"></script>',
     ["t.bundle.module /missing.js"]),
    ('<link rel="Stylesheet" href="./missing.css">',
     ["t.bundle.sheet /missing.css"]),
    ('<link rel="preload stylesheet" href="./missing.css">',
     ["t.bundle.sheet /missing.css"]),
    ('<link rel="nostylesheet" href="./missing.css">', []),
    ('<link rel="icon" href="data:,">', []),
], ids=["first-src-served", "first-src-missing", "rel-upper-case",
        "rel-among-tokens", "rel-not-a-token", "icon"])
def test_the_page_s_links_are_read_as_a_browser_reads_them(
        page: str, expected: list) -> None:
    files = {"/ok.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(
            port, f'<html><head>{page}<script type="module" src="./ok.js">'
                  "</script></head></html>", {}, verdict, "t")
    assert _failures(verdict) == expected


@pytest.mark.parametrize("head, expected", [
    ('<base href="/">', []),
    ('<base href="https://cdn.invalid/">', ["t.bundle.base"]),
    ('<base href="/elsewhere/">', ["t.bundle.base"]),
    ('<script type="importmap">{"imports": {}}</script>', ["t.bundle.importmap"]),
    ('<script type=" ImportMap ">{"imports": {}}</script>',
     ["t.bundle.importmap"]),
], ids=["own-root", "another-origin", "another-path", "import-map",
        "import-map-type-spaced"])
def test_a_page_that_resolves_its_links_elsewhere_is_a_named_failure(
        head: str, expected: list) -> None:
    files = {"/app.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(
            port, f'<html><head>{head}<script type="module" src="./app.js">'
                  "</script></head></html>", {}, verdict, "t")
    assert _failures(verdict) == expected


@pytest.mark.parametrize("make", [
    lambda port: f"http://user@127.0.0.1:{port}/child.js",
    lambda port: f"http://user:pass@127.0.0.1:{port}/child.js",
    lambda port: "./%2e%2e/child.js",
    lambda port: "./%2E/child.js",
    lambda port: "./sub/%2e%2E/child.js",
], ids=["user", "user-and-password", "encoded-dot-dot", "encoded-dot",
        "encoded-mixed-case"])
def test_a_reference_a_browser_refuses_or_reads_elsewhere_is_refused(
        make) -> None:
    files = {"/child.js": (JS, "export const x = 1;\n"),
             "/sub/child.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        ref = make(port)
        files["/app.js"] = (JS, f'import "{ref}";\n')
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == [f"t.bundle.divergent {ref!r}"]
    assert modules == 1


def test_an_encoded_dot_in_a_query_is_no_divergence() -> None:
    files = {"/child.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        files["/app.js"] = (JS, 'import "./child.js?v=%2e";\n')
        files["/child.js?v=%2e"] = files["/child.js"]
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == []
    assert modules == 2


@pytest.mark.parametrize("target, sent", [
    ("/café.js", "/caf%C3%A9.js"),
    ("/my file.js", "/my%20file.js"),
    ("/a.js?q=a b&c='d'", "/a.js?q=a%20b&c=%27d%27"),
    ("/a%20b.js", "/a%20b.js"),
    ("/{x}`.js", "/%7Bx%7D%60.js"),
    ("/\ud83d\ude00.js", "/%F0%9F%98%80.js"),
    ("/\ud83d.js?q=\ude00", "/%EF%BF%BD.js?q=%EF%BF%BD"),
], ids=["non-ascii", "space", "query", "already-encoded", "path-set",
        "surrogate-pair", "lone-surrogates"])
def test_a_request_target_is_encoded_as_a_browser_encodes_it(
        target: str, sent: str) -> None:
    assert harness.browser_target(target) == sent


def test_a_non_ascii_import_is_fetched_as_the_browser_fetches_it() -> None:
    """`http.client` raised on it before (exit 2); a browser sends it
    percent-encoded."""
    files = {"/caf%C3%A9.js": (JS, "export const x = 1;\n"),
             "/app.js": (JS, 'import "./café.js";\n')}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == []
    assert modules == 2


@pytest.mark.parametrize("content, delivered", [
    (f"0;url=http://127.0.0.1:{PORT}/index.html#x=1&amp;console_token={TOKEN}",
     True),
    (f"0;url=http://127.0.0.1:{PORT}/index.html#x=1&ampconsole_token={TOKEN}",
     False),
    (f"0;url=http://127.0.0.1:{PORT}/index.html#console_token={TOKEN}&copy=1",
     False),
], ids=["terminated", "unterminated-before-a-letter",
        "unterminated-before-equals"])
def test_a_refresh_with_an_unterminated_reference_is_not_followed(
        tmp_path: Path, content: str, delivered: bool) -> None:
    """`html.unescape` decodes `&amp` before a letter; a browser leaves it,
    so the page would get no `console_token` where the harness found one."""
    page = _page_with(f'<meta http-equiv="refresh" content="{content}">')
    state, opener = _opener(tmp_path, page)
    failures, _path, token = _read(state, _printed(opener))
    if delivered:
        assert token == TOKEN and FRAGMENT not in failures
    else:
        assert token is None and FRAGMENT in failures


# ---------------------------------------------------------------------------
# Copilot review of #75 at 4bdb41fb: only a live module script is an entry
# (r4178395669), and a reference is read in Unicode scalar values
# (r4178395690); and the self-pass that closed each class: what the page
# runs, the markup and encodings this harness does not model, a string
# escape a module refuses, a redirect, a `Content-Type` a browser parses
# otherwise, and a printed line a server could forge.
# ---------------------------------------------------------------------------

_ENTRY = '<script type="module" src="./app.js"></script>'
_CLASSIC = ["t.bundle.classic-script './app.js'", "t.bundle.entry"]


@pytest.mark.parametrize("head, expected", [
    ('<script src="./app.js"></script>', _CLASSIC),
    ('<script type="text/javascript" src="./app.js"></script>', _CLASSIC),
    ('<script type="" src="./app.js"></script>', _CLASSIC),
    ('<script language="javascript" src="./app.js"></script>', _CLASSIC),
    ('<script language="json" src="./app.js"></script>', ["t.bundle.entry"]),
    ('<script type="application/json" src="./app.js"></script>',
     ["t.bundle.entry"]),
    ('<script type="  " src="./app.js"></script>', ["t.bundle.entry"]),
    ('<script type="module; x" src="./app.js"></script>', ["t.bundle.entry"]),
    (f"<template>{_ENTRY}</template>", ["t.bundle.entry"]),
    (f"<noscript>{_ENTRY}</noscript>", ["t.bundle.entry"]),
    ('<script type="module" src=""></script>', ["t.bundle.entry"]),
    ('<script type="module">import "./app.js";</script>',
     ["t.bundle.inline-module", "t.bundle.entry"]),
    (f"<script>document.title = 1;</script>{_ENTRY}",
     ["t.bundle.classic-script (inline)"]),
    (f'<script nomodule src="./legacy.js"></script>{_ENTRY}', []),
    ('<script type="module" nomodule src="./app.js"></script>', []),
    ('<script type=" MODULE " src="./app.js"></script>', []),
    ('<script type="module" src="./app.js">import "./gone.js";</script>', []),
], ids=["no-type", "javascript-type", "empty-type", "language",
        "language-of-a-data-block", "data-block",
        "blank-type", "module-with-a-parameter", "in-a-template",
        "in-a-noscript", "empty-src", "inline-module", "inline-classic",
        "classic-nomodule", "module-nomodule", "module-type-spaced",
        "src-over-inline-code"])
def test_only_a_live_module_script_is_an_entry(head: str,
                                              expected: list) -> None:
    """A browser runs a module only from a live `<script type="module">`
    with a `src`: one without a type, or of a JavaScript type, is a classic
    script, whose imports are a SyntaxError; a data block and a template's
    script run nothing (Copilot review of #75 at 4bdb41fb, r4178395669)."""
    files = {"/app.js": (JS, "export const x = 1;\n"),
             "/legacy.js": (JS, "var legacy = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, f"<html><head>{head}</head></html>", {},
                              verdict, "t")
    assert _failures(verdict) == expected


def test_a_view_module_is_no_entry() -> None:
    """A module `/capabilities` declares is walked, but it stands in for no
    application entry the page lacks."""
    caps = {"views": {"views": [{"id": "x", "module": "./app.js"}]}}
    files = {"/app.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(port, "<html></html>", caps,
                                                 verdict, "t")
    assert _failures(verdict) == ["t.bundle.entry"]
    assert modules == 1


@pytest.mark.parametrize("body, unmodeled", [
    ('<svg><script type="module" src="./app.js"></script></svg>', True),
    ("<math><mi>x</mi></math>", True),
    ('<select><script type="module" src="./other.js"></script></select>',
     True),
    ('<select><link rel="stylesheet" href="./a.css"></select>', True),
    ("<frameset></frameset>", True),
    ("<select><option>x</option></select>", False),
    ("<template><svg></svg></template>", False),
    ('<template><select><script type="module" src="./other.js"></script>'
     "</select></template>", False),
    ('<select><template><script type="module" src="./other.js"></script>'
     "</template></select>", False),
], ids=["svg", "math", "script-in-select", "link-in-select", "frameset",
        "plain-select", "svg-in-a-template", "select-in-a-template",
        "template-in-a-select"])
def test_markup_this_harness_does_not_model_is_refused_by_name(
        body: str, unmodeled: bool) -> None:
    files = {"/app.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(
            port, f"<html><head>{_ENTRY}</head><body>{body}</body></html>",
            {}, verdict, "t")
    assert _failures(verdict) == (["t.bundle.unmodeled"] if unmodeled
                                  else [])


@pytest.mark.parametrize("content_type, body, utf8", [
    ("text/html", b'<html><head><meta charset="utf-8"></head></html>', True),
    ("text/html; charset=UTF-8", b"<html></html>", True),
    ("text/html", b'<html><head><meta charset="UTF8"></head></html>', True),
    ("text/html; charset=iso-2022-kr", b"<html></html>", False),
    ("text/html", b'<html><head><meta charset="windows-1252"></head></html>',
     False),
    ("text/html", b'<html><head><meta http-equiv="Content-Type" '
                  b'content="text/html; charset=shift_jis"></head></html>',
     False),
    ("text/html", b"\xff\xfe<\x00h\x00t\x00m\x00l\x00>\x00", False),
    ("text/html; charset=iso-2022-kr", b"\xef\xbb\xbf<html></html>", True),
], ids=["meta-utf-8", "header-utf-8", "meta-utf8-label", "header-other",
        "meta-other", "http-equiv-other", "utf-16-bom", "utf-8-bom-outranks"])
def test_the_page_must_be_utf_8_as_the_harness_reads_it(
        tmp_path: Path, content_type: str, body: bytes, utf8: bool) -> None:
    index = harness.Answer(200, {"content-type": content_type}, body, None)
    verdict = harness.Verdict(keep_going=True)
    with served(_snapshot_server([{"path": "a.md"}])) as port:
        harness.check_pages(_quiet_server(tmp_path, port), index, verdict)
    assert ("t.http / is UTF-8" in _failures(verdict)) is not utf8


@pytest.mark.parametrize("head, delivered", [
    (f"{_LIVE_META}<svg></svg>", False),
    (f"<math></math>{_LIVE_META}", False),
    (f'<meta charset="iso-2022-kr">{_LIVE_META}', False),
    ('<meta http-equiv="content-type" content="text/html; '
     f'charset=windows-1252">{_LIVE_META}', False),
    (f'<meta charset="UTF8">{_LIVE_META}', True),
], ids=["svg", "math", "replacement-encoding", "another-encoding",
        "utf8-label"])
def test_an_opener_this_harness_cannot_read_forwards_nothing(
        tmp_path: Path, head: str, delivered: bool) -> None:
    state, opener = _opener(tmp_path, _page_with(head))
    failures, _path, token = _read(state, _printed(opener))
    if delivered:
        assert token == TOKEN and failures == []
    else:
        assert token is None and failures == [FRAGMENT]


def test_an_opener_in_utf_16_forwards_nothing(tmp_path: Path) -> None:
    state, opener = _opener(tmp_path)
    opener.write_bytes(b"\xff\xfe" + _opener_page(FORWARD).encode("utf-16-le"))
    failures, _path, token = _read(state, _printed(opener))
    assert token is None and failures == [FRAGMENT]


@pytest.mark.parametrize("escape, served_as", [
    (r"\uD83D\uDE00", "%F0%9F%98%80"),
    (r"\u{1F600}", "%F0%9F%98%80"),
    (r"\uD83D", "%EF%BF%BD"),
], ids=["surrogate-pair", "code-point", "lone-surrogate"])
def test_a_surrogate_import_is_fetched_as_the_browser_fetches_it(
        escape: str, served_as: str) -> None:
    """Copilot's example: `\\uD83D\\uDE00` is one code point to the browser,
    and `browser_target` raised on it before (r4178395690)."""
    files = {f"/{served_as}.js": (JS, "export const x = 1;\n"),
             "/app.js": (JS, f'import "./{escape}.js";\n')}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(
            port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == []
    assert modules == 2


def test_a_lone_surrogate_from_json_is_read_as_the_browser_reads_it() -> None:
    """JSON keeps a lone `\\ud83d` too: as a view module, and as a document
    path that `requests_for` completes a source read with."""
    caps = json.loads('{"views": {"views": [{"id": "x", '
                      '"module": "./\\ud83d.js"}]}}')
    # ... and the module the page imports as U+FFFD is the same one, judged
    # once, as the browser loads it once.
    files = {"/%EF%BF%BD.js": (JS, "export const x = 1;\n"),
             "/app.js": (JS, 'import "./\\uFFFD.js";\n')}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        _routes, modules = harness.derive_bundle(port, _page("./app.js"),
                                                 caps, verdict, "t")
    assert _failures(verdict) == []
    assert modules == 2
    snapshot = json.loads('{"repository": "r\\udc80", '
                          '"documents": [{"path": "\\ud83d.md"}]}')
    assert harness.requests_for(["/source/"], snapshot) == [
        "/source/", "/source/%EF%BF%BD.md",
        "/source/r%EF%BF%BD%40main/%EF%BF%BD.md"]


@pytest.mark.parametrize("source, malformed", [
    (r'"\1"', True), (r'"\00"', True), (r'"\08"', True), (r'"\8"', True),
    (r'"\9"', True), (r'"\x4"', True), (r'"\xZZ"', True), (r'"\u12"', True),
    (r'"\u{110000}"', True), (r'"\u{}"', True), (r"`\1`", True),
    (r"() => { return `\8`; }", True),
    (r"String.raw`\1`", False), (r"tag`\u{zz}`", False), (r'"\0"', False),
    (r'"\u{0000000041}"', False), (r'"\d"', False), (r'"\x41\u0041"', False),
], ids=["octal", "octal-zero", "zero-then-eight", "eight", "nine",
        "short-hex", "bad-hex", "short-unicode", "past-u10ffff",
        "empty-code-point", "untagged-template", "returned-template",
        "tagged-raw", "tagged", "nul", "long-code-point", "identity",
        "well-formed"])
def test_an_escape_a_module_refuses_is_malformed(source: str,
                                                malformed: bool) -> None:
    strings = harness.JsStrings(f"const s = {source};\n")
    strings.scan()
    assert strings.malformed is malformed


def test_a_module_with_a_malformed_escape_is_a_named_failure() -> None:
    """A module is strict code, so a legacy octal escape is a SyntaxError
    and the browser loads none of it."""
    files = {"/app.js": (JS, 'import "./child.js";\n'),
             "/child.js": (JS, 'export const s = "\\1";\n')}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, _page("./app.js"), {}, verdict, "t")
    assert _failures(verdict) == ["t.bundle.syntax /child.js"]


def test_the_lexer_reads_u_feff_as_whitespace() -> None:
    """JavaScript's whitespace includes U+FEFF, so a regular expression
    after `=` and a U+FEFF is still one, and the string inside it is no
    route."""
    pending: collections.deque = collections.deque()
    routes: set[str] = set()
    source = ('const ok =\ufeff/"\\/hidden"/.test(s);\n'
              'const R = "/route";\n')
    harness._scan_module("/app.js", source.encode("utf-8"), pending, routes)
    assert routes == {"/route"}


@pytest.mark.parametrize("static", [True, False], ids=["static", "dynamic"])
def test_a_redirected_module_is_a_named_failure(static: bool) -> None:
    """A browser follows a redirect to a module this harness would have to
    judge in its place: refused by name, never judged as its status."""
    importer = ('import "./child.js";\n' if static
                else 'import("./child.js").catch(() => null);\n')
    files = {"/app.js": (JS, importer), "/child.js": ("", "", 302)}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, _page("./app.js"), {}, verdict, "t")
        answer = harness.get(port, "/child.js")
    assert _failures(verdict) == [
        f"t.bundle.{'module' if static else 'dynamic'} /child.js"]
    assert answer.status is None
    assert answer.error == f"HTTP 302, {harness.REDIRECTED}"


@pytest.mark.parametrize("value, essence", [
    (" text/javascript ; charset=utf-8", "text/javascript"),
    ("TEXT/JAVASCRIPT", "text/javascript"),
    ("text/javascript\xa0", ""),
    ("text /javascript", ""),
    ("text/ javascript", ""),
    ("text/javascript, text/html", ""),
    ("text/javascript;x=1, text/html", ""),
    ("/javascript", ""),
    ("text/", ""),
    ("text", ""),
], ids=["whitespace", "upper-case", "nbsp", "space-before-slash",
        "space-after-slash", "two-values", "parameter-then-value",
        "no-type", "no-subtype", "no-slash"])
def test_a_content_type_is_parsed_as_a_browser_parses_it(
        value: str, essence: str) -> None:
    answer = harness.Answer(200, {"content-type": value}, b"", None)
    assert harness.media_type(answer) == essence


def test_a_repeated_content_type_is_read_as_one() -> None:
    """A browser joins a repeated header's values, then takes the last that
    parses; this harness joins them and does not split them, so a module
    sent with two types is refused by name, never judged by one of them."""
    files = {"/app.js": (JS, 'import "./child.js";\n'),
             "/child.js": ((JS, "text/html"), "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, _page("./app.js"), {}, verdict, "t")
        answer = harness.get(port, "/child.js")
    assert answer.headers["content-type"] == f"{JS}, text/html"
    assert _failures(verdict) == ["t.bundle.module-type /child.js"]


def test_no_line_the_harness_prints_can_be_forged_or_raise(capsys) -> None:
    """A name or a reason may hold what a server sent: a newline, an ANSI
    escape, a bidirectional override, a lone surrogate. None of it reaches
    the log as itself, so no line can be forged and none raises."""
    verdict = harness.Verdict(keep_going=True)
    verdict.check("t.bundle.bare x\ud83d\nAT-R1 HTTP half: PASS", False,
                  "a\x1b[32m\u202eb\nAT-R1 HTTP half: PASS (1 assertions held)")
    verdict.note("GET /\ud83d\r\nAT-R1 HTTP half: PASS")
    verdict.report()
    out = capsys.readouterr().out
    out.encode("utf-8")                 # no lone surrogate reached the stream
    assert "\x1b" not in out and "\u202e" not in out and "\r" not in out
    assert not [line for line in out.splitlines()
                if line.startswith("AT-R1 HTTP half: PASS")]
    assert "      | AT-R1 HTTP half: PASS (1 assertions held)" in out


def test_a_redirected_route_is_named_as_a_redirect(tmp_path: Path) -> None:
    """Never as a dropped connection, which names a handler that raised."""
    index = harness.Answer(200, {"content-type": "text/html"},
                           _page("./app.js").encode("utf-8"), None)
    files = {"/app.js": (JS, 'const R = "/moved";\n'),
             "/moved": ("", "", 302)}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.check_routes(_quiet_server(tmp_path, port), index,
                             {"documents": []}, {}, None, verdict)
    moved = [failure for failure in verdict.failures
             if failure.ident == "t.route /moved"]
    assert len(moved) == 1
    assert harness.REDIRECTED in moved[0].why
    assert "dropped connection" not in moved[0].why


@pytest.mark.parametrize("body, expected", [
    (f"<frameset></frameset>{_ENTRY}", ["t.bundle.unmodeled", "t.bundle.entry"]),
    (f"<plaintext></plaintext>{_ENTRY}", ["t.bundle.entry"]),
], ids=["after-a-frameset", "after-a-plaintext"])
def test_a_module_script_nothing_closes_the_way_to_is_no_entry(
        body: str, expected: list) -> None:
    """Nothing closes a `<frameset>` or a `<plaintext>`: a browser ignores
    a script after `</frameset>`, and reads one after `<plaintext>` as text."""
    files = {"/app.js": (JS, "export const x = 1;\n")}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.derive_bundle(port, f"<html><body>{body}</body></html>", {},
                              verdict, "t")
    assert _failures(verdict) == expected
