"""The static bundle is served with its own content types, whatever the
host's `mimetypes` table says (plan 034 T084, the holder's addition for #1144
10.2, "reachable in a browser from an openDox-only install"; T075's finding on
openDox-code#73).

`SimpleHTTPRequestHandler.guess_type` reads the handler's `extensions_map`
first and the platform's `mimetypes` table only for an extension that map
lacks. A host whose table maps `.js` to `text/plain` would serve every ES
module of the console as text, and a browser refuses to run a module served
so. Windows reads its table from the registry, which is how such a host
arises. `serve.STATIC_CONTENT_TYPES` pins the bundle's extensions.

1. With a HOSTILE table (every guess `text/plain`), every file of the bundle
   is served with its pinned type, the same type a sound table gives.
2. An extension the pin does not carry still falls back to the platform's
   table: the pin narrows nothing else.
3. Every extension the shipped bundle carries is pinned, so a file of a new
   kind added to `src/opendox/web/` fails here until it is.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import mimetypes
import shutil
import threading
from pathlib import Path

import pytest

from standalone_child import fresh_repository, run_module

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
WEB = ROOT / "src" / "opendox" / "web"

#: Files of the tree that the wheel does not ship (`pyproject.toml`'s
#: package data ships `web/**`, and setuptools leaves dotfiles out).
UNSHIPPED = {".gitkeep"}


def _bundle() -> list[Path]:
    return sorted(p for p in WEB.rglob("*")
                  if p.is_file() and p.name not in UNSHIPPED)


def _hostile(monkeypatch) -> None:
    """A platform table that answers `text/plain` for everything."""
    monkeypatch.setattr(mimetypes, "guess_type",
                        lambda *_a, **_k: ("text/plain", None))


def _content_type(base, path: str) -> tuple[int, str]:
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        return response.status, response.getheader("Content-Type") or ""
    finally:
        connection.close()


@pytest.fixture()
def serve_dir(tmp_path):
    """`serve(web_dir)`: a server over `web_dir` and the plain fixture's
    snapshot, on a thread. Yields the callable; returns `(host, port)`."""
    from opendox import serve

    repo = fresh_repository(PLAIN, tmp_path)
    out = tmp_path / "out" / "snapshot.json"
    child, status = run_module(
        tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--no-validate")
    assert status == 0, child.stderr_text()
    servers = []

    def start(web_dir: Path):
        httpd = serve.build_server(web_dir, out, repo, port=0)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        servers.append((httpd, worker))
        return httpd.server_address[:2]

    try:
        yield start
    finally:
        for httpd, worker in servers:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=10)


def test_the_bundle_keeps_its_types_under_a_hostile_table(
        serve_dir, monkeypatch) -> None:
    from opendox import serve
    _hostile(monkeypatch)
    assert mimetypes.guess_type("app.js")[0] == "text/plain"   # it is hostile
    base = serve_dir(WEB)
    served = {}
    for path in _bundle():
        status, ctype = _content_type(base, "/" + path.relative_to(WEB).as_posix())
        assert status == 200, path
        served[path.relative_to(WEB).as_posix()] = ctype
    expected = {name: serve.STATIC_CONTENT_TYPES[Path(name).suffix]
                for name in served}
    assert served == expected
    assert served["index.html"] == "text/html"
    assert {served[n] for n in served if n.endswith(".js")} == {"text/javascript"}


#: The one pinned extension the standard library's built-in table lacks,
#: with its registered type (RFC 8081).
NOT_BUILT_IN = {".woff2": "font/woff2"}


def test_the_pinned_types_are_the_standard_librarys_own() -> None:
    """Pinning moves nothing on a host whose table was already right: each
    pinned type is the one the standard library's BUILT-IN table gives (a
    fresh `MimeTypes()`, which reads no system file and no registry)."""
    from opendox import serve
    built_in = mimetypes.MimeTypes()
    for ext, ctype in serve.STATIC_CONTENT_TYPES.items():
        expected = NOT_BUILT_IN.get(ext) or built_in.guess_type("file" + ext)[0]
        assert ctype == expected, ext


def test_an_extension_outside_the_pin_still_reads_the_platform_table(
        serve_dir, monkeypatch, tmp_path) -> None:
    web = tmp_path / "web"
    shutil.copytree(WEB, web)
    (web / "notes.txt").write_text("plain\n", encoding="utf-8")
    _hostile(monkeypatch)
    base = serve_dir(web)
    assert _content_type(base, "/notes.txt") == (200, "text/plain")
    monkeypatch.setattr(mimetypes, "guess_type",
                        lambda *_a, **_k: ("text/x-from-the-table", None))
    assert _content_type(base, "/notes.txt") == (200, "text/x-from-the-table")
    assert _content_type(base, "/index.html") == (200, "text/html")


def test_every_extension_the_bundle_ships_is_pinned() -> None:
    from opendox import serve
    shipped = {path.suffix for path in _bundle()}
    assert shipped, "the bundle is empty"
    assert shipped <= set(serve.STATIC_CONTENT_TYPES), (
        f"the bundle ships {sorted(shipped - set(serve.STATIC_CONTENT_TYPES))}, "
        "which serve.STATIC_CONTENT_TYPES does not pin")
