"""`/capabilities`' `install` block: the serving process reports its own
install shape (plan 034 T073; #1144 13.4a; RULED R1Q16 (i), `5850003126`).

13.4a: the entry point's served `/capabilities` payload gains an `install`
block, holding `mode` and `database_bundle` (`data_dir`, `socket_dir`, `pid`),
read from the settings THAT PROCESS loaded. F13.1's `caps.json` block is the
falsifier, and it needs the LOCAL install's bundled server, so it runs in
`tests_runtime/test_bundled_postgres.py` beside T072's blocks. This module
holds the rest, none of which starts a database:

1. A HOSTED `generate-and-open`, a child with every setting a hosted install
   needs: the served block says `hosted`, with no bundled server
   (`database_bundle` null), as `runtime status` reports a hosted install.
2. `build_server` publishes exactly what its entry point hands it, asked on
   EACH request, so a pid that changes is reported as it is now; and with
   nothing handed in, the payload carries no `install` block at all.
3. `cli._install_report` reads the settings the verb loaded and the bundled
   server it started, and answers None where nothing was resolved.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import argparse
import http.client
import json
import re
import threading
import types
from pathlib import Path

import pytest

from opendox import cli as cli_mod
from opendox import serve as serve_mod
from opendox.runtime import config as runtime_config
from standalone_child import Child, fresh_repository, run_module

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
WEB = ROOT / "src" / "opendox" / "web"
PREFIX = runtime_config.PREFIX

#: Every setting a HOSTED install needs, none of them reached by this run: the
#: document surface reads nothing from the store in release 1 (R1Q16 (ii)).
HOSTED = {
    PREFIX + "DATABASE_URL": "postgresql://serve@127.0.0.1:1/opendox",
    PREFIX + "MIGRATION_DATABASE_URL": "postgresql://migrate@127.0.0.1:1/opendox",
    PREFIX + "OIDC_AUDIENCE": "fixture",
    PREFIX + "OIDC_ISSUER": "https://issuer.example.invalid/realms/fixture",
}

_URL = re.compile(r"^(http://([0-9.]+):([0-9]+))/index\.html$")


def _get(base: tuple[str, int], path: str) -> tuple[int, dict]:
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 1 — a hosted entry point reports a hosted install, and no bundled server
# ---------------------------------------------------------------------------

def test_a_hosted_entry_point_reports_its_hosted_shape(tmp_path) -> None:
    """The child inherits no runtime setting from the runner
    (`standalone_child.Child`), and is given a hosted install's, on purpose."""
    repo = fresh_repository(PLAIN, tmp_path)
    child = Child(tmp_path, "opendox.cli", "generate-and-open",
                  "--repo-root", str(repo), "--repository", "fixture",
                  "--no-open", "--port", "0", "--run-dir", str(tmp_path / "run"),
                  extra_env={**HOSTED, PREFIX + "INSTALL_MODE":
                             runtime_config.INSTALL_MODE_HOSTED})
    try:
        match = child.wait_for_line(_URL)
        base = (match.group(2), int(match.group(3)))
        status, caps = _get(base, "/capabilities")
        assert status == 200, status
        assert caps.get("install") == {
            "mode": runtime_config.INSTALL_MODE_HOSTED, "database_bundle": None}, caps
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()


# ---------------------------------------------------------------------------
# 2 — build_server publishes what its entry point hands it, per request
# ---------------------------------------------------------------------------

@pytest.fixture()
def served(tmp_path):
    """`serve(install_report=...)`: a server built in process over a fresh
    repository's snapshot, on a thread, and the base it answers on."""
    repo = fresh_repository(PLAIN, tmp_path)
    snapshot = tmp_path / "snapshot.json"
    child, status = run_module(tmp_path, "opendox.cli", "generate",
                               "--repo-root", str(repo), "--repository",
                               "fixture", "--output", str(snapshot),
                               "--no-validate")
    assert status == 0, child.stderr_text()
    servers = []

    def serve(**kwargs):
        httpd = serve_mod.build_server(WEB, snapshot, repo, port=0, **kwargs)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        servers.append((httpd, worker))
        return httpd.server_address[:2]

    try:
        yield serve
    finally:
        for httpd, worker in servers:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=10)


def test_with_no_install_shape_the_payload_carries_no_install_block(served) -> None:
    """A process that resolved no install shape publishes none: an absent
    block, never an invented one."""
    status, caps = _get(served(), "/capabilities")
    assert status == 200 and "install" not in caps, caps


def test_the_block_is_the_entry_points_and_is_asked_on_each_request(served) -> None:
    pids = iter([4242, None])

    def report():
        return {"mode": "local", "database_bundle": {
            "data_dir": "/state/postgres/data", "socket_dir": "/state/postgres/run",
            "pid": next(pids)}}

    base = served(install_report=report)
    first = _get(base, "/capabilities")[1]["install"]
    second = _get(base, "/capabilities")[1]["install"]
    assert first["mode"] == "local" and first["database_bundle"]["pid"] == 4242
    # the server's child has gone: the next request says so
    assert second["database_bundle"]["pid"] is None


# ---------------------------------------------------------------------------
# 3 — the entry point reads its own settings and its own bundled server
# ---------------------------------------------------------------------------

def test_no_resolved_settings_is_no_install_report() -> None:
    assert cli_mod._install_report(argparse.Namespace()) is None


def test_a_hosted_run_reports_no_bundled_server() -> None:
    settings = types.SimpleNamespace(install_mode=runtime_config.INSTALL_MODE_HOSTED)
    report = cli_mod._install_report(argparse.Namespace(runtime_settings=settings))
    assert report() == {"mode": "hosted", "database_bundle": None}


def test_a_local_run_reports_the_server_it_started() -> None:
    class _Server:
        def __init__(self):
            self.pid = 7

        def report(self):
            return {"data_dir": "/s/d", "socket_dir": "/s/r", "pid": self.pid}

    server = _Server()
    settings = types.SimpleNamespace(install_mode=runtime_config.INSTALL_MODE_LOCAL)
    report = cli_mod._install_report(argparse.Namespace(
        runtime_settings=settings, database_bundle=server))
    assert report() == {"mode": "local", "database_bundle": {
        "data_dir": "/s/d", "socket_dir": "/s/r", "pid": 7}}
    server.pid = None                   # it stopped: asked again, it says so
    assert report()["database_bundle"]["pid"] is None
