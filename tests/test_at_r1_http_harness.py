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
  * a malformed 200 catalog is a named failure, never an exception
    (r4170450491), and so is a catalog whose envelope the chat rail would
    not adopt (Copilot review of #75 at f0e0ffe1).
"""

from __future__ import annotations

import collections
import contextlib
import http.server
import importlib.util
import json
import sys
import threading
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
def served(files: dict[str, tuple[str, str]]):
    """A loopback server answering `files` (`path -> (content type, body)`),
    and 404 for anything else. Yields its port."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            entry = files.get(self.path)
            if entry is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = entry[1].encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", entry[0])
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
    ('{"schema_version": 1, "kind": "workbench-model-catalog-v2", "models": []}',
     _WRONG_ENVELOPE),
])
def test_a_malformed_catalog_is_a_named_failure_never_an_exception(
        body: str, expected: list[str]) -> None:
    files = {harness.CATALOG_ROUTE: ("application/json", body)}
    verdict = harness.Verdict(keep_going=True)
    with served(files) as port:
        harness.check_catalog(_Server(port), "token", verdict)
    assert _failures(verdict) == expected


def test_the_documented_start_is_the_readme_line_less_its_ellipsis() -> None:
    """The one command the openDox root README documents (T007 batch H's
    10.3 addendum): the harness runs these tokens, then fills the `…`."""
    assert harness.DOCUMENTED_START == "opendox generate-and-open --local …"
    assert harness.documented_prefix() == ["opendox", "generate-and-open",
                                           "--local"]
    assert json.dumps(harness.DOCUMENTED_INSTALL) == '"pip install \\"opendox[local]\\""'
