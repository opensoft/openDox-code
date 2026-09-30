"""The select-to-edit route reads ONE registry entry, start to finish: plan
034's T055, the follow-up to its `/source` arm's fix (Copilot at
openDox-code#59 0c946f4e, "previously missed", `default_registry.py`'s
`resolve_source`).

THE FINDING. `serve_project._resolved_listed_edit_entry` resolved an entry,
and then asked the registry for the path by that entry's `(repository, ref)`
pair, which is a SECOND lookup. A refresh on another thread that re-registers
the key between the two puts another entry's `source_root` behind the path the
route confines. The route then decides with one entry's root, and acts on
another's: the listed-path check reads the first entry's snapshot, and the
editor is launched over the first entry's root. `serve.py`'s `/source` arm had
the same hole and was fixed in #59 by confining the entry in hand, with no
second lookup. This file holds the same rule for the one caller left.

THE RULE. The lookup, the listed-path check and the confinement all use the
entry the ONE resolution returned. The path is confined to THAT entry's own
root, through the registry SEAM's declared containment rule
(`projection_seams.registry`'s `resolve_within`), so a contributed registry is
never asked for a method the seam does not declare.

1. ONE LOOKUP. The registry is asked once, and never for a path by a pair.
2. THE RACE, BOTH WAYS, at the route: a refresh that replaces the key right
   after the route's one resolution moves neither the file the route accepts
   nor the file it refuses, and the editor opens the entry the route checked.
3. CONFINEMENT IS KEPT: no escape of the root, no dot-directory, no symlink out,
   and an entry with no root serves nothing.
4. A host registry needs only what the seam declares.

Every case starts with nothing registered at the four seams or the generator
seam, and puts back every registry it found (`test_projection_seams.py`'s own
isolation, imported).

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import dataclasses
import http.client
import json
import shutil
import threading
import types
from pathlib import Path


from opendox import cli
from opendox import default_registry
from opendox import projection_seams as ps
from opendox import serve
from opendox import serve_project
# THE SAME ISOLATION AND THE SAME `git` HELPER `test_projection_seams.py` HOLDS,
# imported rather than copied: a copy of the fixture's thirty lines is a second
# place for the private state it puts back to go stale in, and it is what the
# quality gate's duplication check read as new code. `_isolated_registries` is
# autouse, so importing it is what applies it to this module's cases.
from test_projection_seams import _git, _isolated_registries  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "opendox"
PLAIN_DOCUMENTS = ROOT / "tests" / "fixtures" / "plain-documents"
LISTED = "notes-toolshed-inventory.md"


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _own_payload(*paths: str) -> bytes:
    """A snapshot's bytes that list exactly `paths` as documents."""
    return json.dumps({"documents": [{"path": path} for path in paths]}).encode()


def _lone_entry(root: Path | None, *paths: str, repository: str = "garden",
                ref: str = "main") -> default_registry.SnapshotEntry:
    return default_registry.SnapshotEntry(
        repository, ref, source_root=root, payload=_own_payload(*paths))


def _source_over(registry) -> types.SimpleNamespace:
    """What `_resolved_listed_edit_entry` reads off a server's `source`."""
    return types.SimpleNamespace(registry=registry)


# ---------------------------------------------------------------------------
# 1 — ONE LOOKUP
# ---------------------------------------------------------------------------

def test_the_edit_arm_asks_the_registry_once_and_never_for_a_path_by_a_pair(
        tmp_path) -> None:
    """Every read of an entry by its key goes through `get`. The route's
    lookup, its listed-path check and its confinement are ONE resolution, so
    the registry's `get` runs once; twice means a second lookup by the pair,
    and `resolve_source` is that second lookup by name."""
    ps.register_defaults()
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")

    class _Counting(default_registry.SnapshotRegistry):
        gets = 0
        asked_for_a_path = 0

        def get(self, repository, ref=None):
            type(self).gets += 1
            return super().get(repository, ref)

        def resolve_source(self, repository, ref, tail):
            type(self).asked_for_a_path += 1
            return super().resolve_source(repository, ref, tail)

    registry = _Counting()
    entry = registry.register(_lone_entry(tmp_path, "doc.md"))
    _Counting.gets = 0
    found = serve_project._resolved_listed_edit_entry(
        _source_over(registry), "doc.md", "garden", "main")
    assert found is entry
    assert _Counting.asked_for_a_path == 0, (
        "the route asked the registry for the path by the entry's pair")
    assert _Counting.gets == 1, (
        "the registry was looked up more than once for one request")


def test_no_module_asks_a_registry_for_a_path_by_a_pair() -> None:
    """EVERY caller of the two-step path, not only the one the finding named.
    `SnapshotRegistry.resolve_source` is for a caller that holds only a pair,
    and none in openDox does. A module that now does must say why its entry
    is not already in hand: the list of those callers is empty, and adding one
    is a decision for a reviewer, not an accident."""
    permitted: dict[str, str] = {}
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "resolve_source"):
                where = f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
                if path.relative_to(ROOT).as_posix() not in permitted:
                    offenders.append(where)
    assert offenders == [], (
        "a caller asked a registry for a path by a pair; confine the entry in "
        "hand with the seam's `resolve_within(entry.source_root, tail)` "
        f"instead: {offenders}")


def test_a_host_registry_needs_only_what_the_seam_declares(tmp_path) -> None:
    """The seam declares `resolve_within`, and a registry's own `resolve` is
    what the route has always asked. `resolve_source` is on neither list, so a
    contributed registry without one must still serve the route."""
    ps.register_defaults()
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    entry = _lone_entry(tmp_path, "doc.md")

    class _Host:
        def resolve(self, repository, ref=None):
            return entry if (repository, ref) == ("garden", "main") else None

    assert not hasattr(_Host, "resolve_source")
    found = serve_project._resolved_listed_edit_entry(
        _source_over(_Host()), "doc.md", "garden", "main")
    assert found is entry
    assert serve_project._resolved_listed_edit_entry(
        _source_over(_Host()), "doc.md", "stranger", "main") is None


# ---------------------------------------------------------------------------
# 3 — CONFINEMENT IS KEPT, AND AN ENTRY WITH NO ROOT SERVES NOTHING
# ---------------------------------------------------------------------------

def test_the_entrys_own_root_still_confines_what_the_route_accepts(
        tmp_path) -> None:
    """Every path below but the last is LISTED by the entry's snapshot, so only
    the confinement can refuse it. The last is inside the root and never
    listed, so only the listing can: the two halves of the route's check."""
    ps.register_defaults()
    root = tmp_path / "root"
    (root / ".secret").mkdir(parents=True)
    (root / "ok.md").write_text("ok", encoding="utf-8")
    (root / ".secret" / "notes.md").write_text("no", encoding="utf-8")
    (root / ".hidden.bin").write_text("no", encoding="utf-8")
    (root / "unlisted.md").write_text("fine, but never listed", encoding="utf-8")
    (tmp_path / "outside.md").write_text("outside", encoding="utf-8")
    (root / "link.md").symlink_to(tmp_path / "outside.md")
    listed = ("ok.md", "../outside.md", ".secret/notes.md", ".hidden.bin",
              "link.md", str(tmp_path / "outside.md"), "missing.md", "")
    registry = default_registry.SnapshotRegistry()
    entry = registry.register(_lone_entry(root, *listed))
    source = _source_over(registry)

    def edit(path: str):
        return serve_project._resolved_listed_edit_entry(
            source, path, "garden", "main")

    assert edit("ok.md") is entry
    for refused in listed[1:]:
        assert edit(refused) is None, f"{refused!r} was accepted"
    assert edit("unlisted.md") is None, (
        "a file the snapshot never listed was accepted: root confinement "
        "alone is not enough for select-to-edit")


def test_an_entry_with_no_root_serves_nothing_and_an_unknown_pair_neither(
        tmp_path) -> None:
    ps.register_defaults()
    (tmp_path / "doc.md").write_text("x", encoding="utf-8")
    registry = default_registry.SnapshotRegistry()
    registry.register(_lone_entry(None, "doc.md"))
    registry.register(_lone_entry(tmp_path, "doc.md", repository="orchard"))
    source = _source_over(registry)
    assert serve_project._resolved_listed_edit_entry(
        source, "doc.md", "garden", "main") is None, (
        "an entry with no root served a path from somewhere else")
    assert serve_project._resolved_listed_edit_entry(
        source, "doc.md", "stranger", "main") is None
    assert serve_project._resolved_listed_edit_entry(
        _source_over(None), "doc.md", "garden", "main") is None
    assert serve_project._resolved_listed_edit_entry(
        None, "doc.md", "garden", "main") is None
    assert serve_project._resolved_listed_edit_entry(
        source, "doc.md", "orchard", "main") is not None


# ---------------------------------------------------------------------------
# 2 — THE RACE, AT THE ROUTE
# ---------------------------------------------------------------------------

def _served_for_edit(tmp_path: Path, monkeypatch):
    """A real server over a generated snapshot of a real git checkout whose
    human identity resolves, so select-to-edit is on, with an editor the test
    records instead of starting."""
    repo = tmp_path / "repository"
    shutil.copytree(PLAIN_DOCUMENTS, repo)
    _git(repo, "-c", "init.defaultBranch=main", "init", "-q")
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "fixture")
    out = tmp_path / "run" / "snapshot.json"
    assert cli.main(["generate", "--repo-root", str(repo), "--repository",
                     "garden", "--output", str(out), "--no-validate"]) == 0
    (tmp_path / "web").mkdir(exist_ok=True)
    # the actor is a CLAIM the checkout's own git identity must bear out, and
    # the name is what `git config user.name` holds above: a checkout whose
    # identity names both a name and an email is ambiguous with no claim
    httpd = serve.build_server(tmp_path / "web", out, repo, port=0,
                               actor="Tester")
    bound = httpd.RequestHandlerClass.func
    assert bound.capabilities["actions"]["edit"] and bound.console_token, (
        "the fixture no longer turns select-to-edit on")
    monkeypatch.setenv("EDITOR", "recorded-editor")
    launched: list[list[str]] = []
    httpd.editor_launcher = launched.append
    return repo, httpd, bound, launched


def _post_edit(httpd, bound, *, path: str = LISTED,
               repository: str = "garden", ref: str = "main"):
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        host, port = httpd.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=10)
        connection.request(
            "POST", serve.ACTIONS_EDIT_ROUTE,
            body=json.dumps({"path": path, "repository": repository,
                             "ref": ref}),
            headers={"Content-Type": "application/json",
                     serve.CONSOLE_TOKEN_HEADER: bound.console_token})
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


class _RefreshAfterTheFirstResolution(default_registry.SnapshotRegistry):
    """A registry whose key is REPLACED, as a refresh on another thread would,
    right after the first `resolve` returns and before any later lookup. With
    no replacement it is an ordinary registry, which is the control."""

    def __init__(self, replacement=None):
        super().__init__()
        self._replacement = replacement
        self.landed: list[bool] = []

    def resolve(self, repository, ref=None):
        entry = super().resolve(repository, ref)
        if entry is not None and self._replacement is not None:
            replacement, self._replacement = self._replacement, None
            self.register(replacement)
            self.landed.append(self.get(*entry.key) is replacement)
        return entry


def test_a_route_with_no_refresh_opens_the_entrys_file(
        tmp_path, monkeypatch) -> None:
    """The control: the harness accepts a listed file and starts the editor
    over the entry's root, so the two refusals and the acceptance below are
    the race's doing and not the fixture's."""
    repo, httpd, bound, launched = _served_for_edit(tmp_path, monkeypatch)
    registry = _RefreshAfterTheFirstResolution()
    registry.register(bound.source.registry.active)
    bound.source.registry = registry
    status, body = _post_edit(httpd, bound)
    assert (status, body) == (200, {"ok": True, "path": LISTED})
    assert launched == [["recorded-editor", str((repo / LISTED).resolve())]]


def test_a_refresh_that_replaces_the_key_cannot_take_the_file_the_route_refuses(
        tmp_path, monkeypatch) -> None:
    """The entry the route resolved has a root WITHOUT the listed file. A
    refresh then re-registers the key with a root that HAS it. Confined by the
    pair again, the path was found in the replacement's root, the listed-path
    check passed on the first entry's snapshot, and the editor was started over
    the first entry's root, for a file that is not there. Confined to the
    entry in hand, the route refuses, and starts nothing."""
    repo, httpd, bound, launched = _served_for_edit(tmp_path, monkeypatch)
    base = bound.source.registry.active
    bare = tmp_path / "bare-root"
    bare.mkdir()
    first = dataclasses.replace(base, source_root=bare)
    replacement = dataclasses.replace(base, source_root=repo,
                                      source_revision="replaced")
    registry = _RefreshAfterTheFirstResolution(replacement)
    registry.register(first)
    bound.source.registry = registry
    status, body = _post_edit(httpd, bound)
    assert registry.landed == [True], (
        "the refresh did not land between the route's resolution and its "
        "confinement, so this case proved nothing")
    assert launched == [], (
        "the editor was started over a root that does not hold the file")
    assert status == 404 and body["error"] == "document_unavailable"


def test_a_refresh_that_replaces_the_key_cannot_take_the_file_the_route_accepts(
        tmp_path, monkeypatch) -> None:
    """The other way round. The entry the route resolved holds the file, and a
    refresh re-registers the key with a root that does not. Confined by the
    pair again, the route refused a file the entry it was serving does hold.
    Confined to the entry in hand, the listed file opens, from that entry's
    own root, and the refresh lands as it would."""
    repo, httpd, bound, launched = _served_for_edit(tmp_path, monkeypatch)
    base = bound.source.registry.active
    bare = tmp_path / "bare-root"
    bare.mkdir()
    replacement = dataclasses.replace(base, source_root=bare,
                                      source_revision="replaced")
    registry = _RefreshAfterTheFirstResolution(replacement)
    registry.register(base)
    bound.source.registry = registry
    status, body = _post_edit(httpd, bound)
    assert registry.landed == [True], (
        "the refresh did not land between the route's resolution and its "
        "confinement, so this case proved nothing")
    assert (status, body) == (200, {"ok": True, "path": LISTED}), (
        "the route refused a file its own entry holds")
    assert launched == [["recorded-editor", str((repo / LISTED).resolve())]], (
        "the editor was not started over the entry the route checked")
    assert registry.get("garden", "main") is replacement, (
        "the refresh was undone, not merely ignored by this request")
