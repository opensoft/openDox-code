"""A tile's OWN documents are editable in openDox's default scope, and nothing
else is (plan 034 T084; RULED by Brett Heap, openxFactory#656 comment
`5961651355`, "Tile's own documents editable (Recommended)", which supersedes
the holder's read-only reading of R1Q10 (a)).

WHY IT MATTERS. openDox's turn guard (`doxbench_turns._require_in_scope_and_
editable`, FR-015) refuses a turn whose buffer names a path that is in scope
but not editable. Under a read-only default, every turn a lone openDox ran was
refused "readable but not editable", so its chat could never answer. The
default now marks the tile's own sections editable, which are a group's
members, a selection's files and a candidate's claiming groups' members, as
openXdox's authority marks its owned sections. The set is ONE named function,
`default_columns.editable_paths`.

THE CASES run over a composed host in process: the plain fixture in a fresh
repository, a loopback bind, an authenticated actor, the binding
`opendox model-binding add` declares, and the port the entry points declare
over it (`doxbench_install.declared_model_port_factory`). The host also has
the released validators, as a plane with a readable contract has them. Case
4 runs the same turn on a standalone `python -m opendox.serve`, which has
openDox's own validators since T085 (openDox-code#71).

1. A turn whose buffer names a document of the tile passes the guard and
   reaches the model step. It asks for a model the catalog does not carry, so
   step 7 answers `model_unavailable`, and nothing is spawned or contacted.
2. A turn naming a corpus document OUTSIDE the tile is still refused at the
   guard (`turn_scope_refused`).
3. Save is still refused. "Editable" is the scope's word, and it grants no
   write. Writing is the Save gate's, a host's gate route: this host
   contributes none, so `POST /actions/gate/first-edit` answers
   `unknown_action`. And the record a Save writes is a governed gate-action
   record, which the gate seam's default refuses by name.

4. STANDALONE, `python -m opendox.serve` as a child with neither sibling
   importable, over the same checkout and binding: a turn over the tile's own
   document passes the guard and reaches the model step (`model_unavailable`)
   as case 1 does, with openDox's own validators (T085) and no stand-in.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
from pathlib import Path

import pytest

from standalone_child import Child, fresh_repository, git, run_module

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"
WEB = ROOT / "src" / "opendox" / "web"

#: The plain fixture's group of two, and a corpus document outside it.
TILE = {"repository": "fixture", "ref": "main", "tile_kind": "cluster",
        "tile_id": "barrel-rain"}
OWN = "notes-rain-barrel-leak.md"
OUTSIDE = "notes-toolshed-inventory.md"

#: The binding `opendox model-binding add` declares. Its broker is never run.
BINDING = ["--id", "scope-binding", "--label", "Scope binding",
           "--provider", "scope-provider",
           "--credential-ref", "opref-4f2a91c07be3d5a8140b6e77",
           "--auth-kind", "api_key",
           "--credential-approver", "fixture@example.invalid",
           "--endpoint", "https://provider.invalid/turn",
           "--dialect", "xfactory-prompt-v1",
           "--", "scope-broker", "--home", "/srv/{binding_id}"]


class _Conforms:
    @staticmethod
    def iter_errors(_instance):
        return iter(())


class _EveryKind(dict):
    """The released validators, as a plane that can read its contract has
    them: one for every kind, and every instance conforms."""

    def get(self, _kind, _default=None):
        return _Conforms()


def _call(base, method, path, *, body=None, token=None):
    from opendox import serve
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers[serve.CONSOLE_TOKEN_HEADER] = token
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {}
        return response.status, parsed if isinstance(parsed, dict) else {}, raw
    finally:
        connection.close()


def _turn(repo: Path, document: str) -> bytes:
    """A well-formed v2 turn over `TILE`, bound to `document`, whose buffer
    carries the document's committed text with its true content identity."""
    from opendox import doxbench_hash
    from opendox.serve_wire import DOXBENCH_CHAT_TURN_V2_KIND

    def buffer(kind, path, content):
        identity = doxbench_hash.content_identity(content, max_bytes=None).hex
        return {"kind": kind, "repository": "fixture", "path": path,
                "base_ref": "main", "base_revision": "0" * 40,
                "base_hash": identity, "content_hash": identity,
                "content": content, "dirty": False}

    text = (repo / document).read_text(encoding="utf-8")
    return json.dumps({
        "schema_version": 1, "kind": DOXBENCH_CHAT_TURN_V2_KIND,
        "client_turn_id": f"scope-{document}", "scope": TILE,
        "working_subject": "", "message": "What does this note claim?",
        "model_id": "a-model-the-catalog-does-not-carry", "transcript": [],
        "last_assistant_turn_id": None,
        "bound_buffer": document,
        "buffers": [buffer("outline", None, "# outline\n"),
                    buffer("document", document, text)],
    }).encode("utf-8")


@pytest.fixture()
def host(tmp_path):
    """The composed host the module docstring describes, its actor `brett`
    one of the suite's declared principals
    (`session_fixtures.declared_gate_principals`). Yields
    `(base, capabilities, repo)`."""
    from opendox import doxbench_install, serve

    repo = fresh_repository(PLAIN, tmp_path)
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    added, status = run_module(tmp_path, "opendox.cli", "model-binding", "add",
                               "--repo-root", str(repo), *BINDING)
    assert status == 0, added.stderr_text()
    out = tmp_path / "out" / "snapshot.json"
    generated, status = run_module(
        tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--no-validate")
    assert status == 0, generated.stderr_text()
    httpd = serve.build_server(
        WEB, out, repo, port=0, actor="brett",
        schema_validator_factory=_EveryKind,
        model_port_factory=doxbench_install.declared_model_port_factory(
            doxbench_install.session_root_beside(out), checkout_root=repo))
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        base = httpd.server_address[:2]
        status, caps, raw = _call(base, "GET", "/capabilities")
        assert status == 200, raw
        assert caps["actions"]["session"] is True, caps
        yield base, caps, repo
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


def test_a_turn_over_the_tiles_own_document_reaches_the_model_step(host) -> None:
    from opendox.serve_wire import DOXBENCH_ERR_MODEL_UNAVAILABLE
    base, caps, repo = host
    status, body, raw = _call(base, "POST", "/actions/workbench/chat-turn",
                              body=_turn(repo, OWN),
                              token=caps["console_token"])
    # past the guard (no "readable but not editable"), past identity, and
    # answered by the model step: the catalog carries no such model
    assert body.get("error") == DOXBENCH_ERR_MODEL_UNAVAILABLE, (status, raw)
    assert body.get("client_turn_id") == f"scope-{OWN}", body


def test_a_turn_over_a_document_outside_the_tile_is_refused(host) -> None:
    from opendox.serve_wire import DOXBENCH_ERR_TURN_SCOPE_REFUSED
    base, caps, repo = host
    assert (repo / OUTSIDE).is_file()
    status, body, raw = _call(base, "POST", "/actions/workbench/chat-turn",
                              body=_turn(repo, OUTSIDE),
                              token=caps["console_token"])
    assert body.get("error") == DOXBENCH_ERR_TURN_SCOPE_REFUSED, (status, raw)


def test_save_is_still_the_gates_and_refused_by_name(host) -> None:
    """Editable is not saveable: no Save route answers without a host's gate,
    and the governed record a Save writes is refused naming the seam."""
    from opendox import column_seams
    from opendox.default_columns import GateRecordsNotRegistered
    base, caps, _repo = host
    assert caps["actions"]["gate"] is False, caps
    status, body, raw = _call(base, "POST", "/actions/gate/first-edit",
                              body=b"{}", token=caps["console_token"])
    assert status == 404 and body.get("error") == "unknown_action", raw
    gate = column_seams.gate.current()
    with pytest.raises(GateRecordsNotRegistered) as refused:
        gate.build_gate_action_record(
            actor="brett", action=gate.ACTION_EDIT_DOCUMENT,
            at="2026-10-02T00:00:00Z", provenance=gate.HTTP_CONSOLE_TOKEN)
    assert "opendox.column_seams.gate" in str(refused.value)
    assert "opendox.column_seams.gate.register(" in str(refused.value)


def test_the_tiles_own_documents_are_exactly_the_editable_set(host) -> None:
    """The projection the guard reads, over the same snapshot: the group's
    two members, and nothing else of the corpus's eight."""
    from opendox import column_seams
    from opendox.doxbench_scope_types import ScopeKey
    base, _caps, repo = host
    snapshot = json.loads((repo.parent / "out" / "snapshot.json")
                          .read_text(encoding="utf-8"))
    projection = column_seams.scope.current().resolve_scope(
        snapshot, ScopeKey(**TILE), source_root=repo)
    own = ("notes-rain-barrel-leak.md", "notes-rain-barrel-overflow.md")
    assert projection.context_paths == own
    assert projection.editable_paths == own
    assert projection.active_document_candidates == own
    assert OUTSIDE not in projection.editable_paths


_SERVE_URL = re.compile(r"^serving ideation dashboard at "
                        r"(http://([0-9.]+):([0-9]+))/index\.html$")


def test_a_standalone_turn_over_the_tiles_own_document_is_answered(
        tmp_path, monkeypatch) -> None:
    """Case 4. The child's environment carries no `GIT_*` and no `XF_*`, so
    its actor is the one its repository's identity names (the suite's own
    roster of several principals would resolve none)."""
    from opendox.serve_wire import DOXBENCH_ERR_MODEL_UNAVAILABLE
    for name in list(os.environ):
        if name.startswith(("GIT_", "XF_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    repo = fresh_repository(PLAIN, tmp_path)
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    added, status = run_module(tmp_path, "opendox.cli", "model-binding", "add",
                               "--repo-root", str(repo), *BINDING)
    assert status == 0, added.stderr_text()
    out = tmp_path / "out" / "snapshot.json"
    generated, status = run_module(
        tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--no-validate")
    assert status == 0, generated.stderr_text()
    child = Child(tmp_path, "opendox.serve", "--snapshot", str(out),
                  "--checkout-root", str(repo), "--port", "0")
    try:
        match = child.wait_for_line(_SERVE_URL)
        base = (match.group(2), int(match.group(3)))
        status, caps, raw = _call(base, "GET", "/capabilities")
        assert status == 200 and caps["actions"]["session"] is True, raw
        # a standalone plane delivers its token in the opened URL, through
        # its private copy, and never on `/capabilities` (plan 034 T104)
        assert "console_token" not in caps, caps
        status, body, raw = _call(base, "POST", "/actions/workbench/chat-turn",
                                  body=_turn(repo, OWN),
                                  token=child.console_token(base[1]))
        # past the validators, the guard and identity, answered by the model
        # step: never `turn_scope_refused`, never a dropped connection
        assert body.get("error") == DOXBENCH_ERR_MODEL_UNAVAILABLE, (status, raw)
        assert body.get("client_turn_id") == f"scope-{OWN}", body
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    assert child.refused() == [], child.refused()
