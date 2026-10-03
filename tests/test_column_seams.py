"""The consumer columns' seams and openDox's defaults for them (plan 034 T084;
#1144 4.3 as T007 batch G's addendum reads; RULED R1Q10 (a), `5850003126`).

`opendox.column_seams` declares four seams, the gate primitives, the doxBench
scope, kickoff and the cross-reference register, in `projection_seams`'
discipline, and `opendox.default_columns` is openDox's own default for each.
These cases hold:

1. A BARE PROCESS, in which no entry point ran, meets `SeamNotRegistered` at
   each seam, naming the seam and the call that registers one (4.2). A default
   is a registration an entry point makes, never a fallback inside the seam.
2. EACH ENTRY POINT registers the four defaults where no host has
   (`cli.build_parser()`, `cli.main()`, `serve.build_server()`, `serve.main()`
   read with `ast`, and `cli.build_parser()` run in a child). A host's
   registration made before a default is read replaces it, one made after is
   refused, and a registration that lacks a name is refused naming it.
3. THE GATE DEFAULT carries the vocabulary-free primitives as real code, and
   refuses the governed record functions and `GateConsole` by name, as
   `GateRecordsNotRegistered` (a `GateRefused`). `gate_records_writable()` is
   true only with a host's gate.
4. THE SCOPE DEFAULT projects each kind of tile with ITS OWN documents
   editable and nothing else (RULED `5961651355`, "Tile's own documents
   editable"), confines every path, and answers no session-created path; the
   kickoff and register defaults answer nothing dispatched and no possibles.
5. A REGISTRATION THAT HAS THE NAMES BUT NOT THEIR SHAPE is refused at
   registration: a gate whose `GateRefused` is not an exception class, and a
   register whose adapter carries no callable `discover`.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from opendox import column_seams as cs
from opendox import default_columns as dc
from opendox import projection_seams as ps
from opendox.boundary import BoundaryViolation, HumanGate, OutputBoundary
from opendox.doxbench_scope_types import ScopeConfinementError, ScopeKey

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "opendox"
SEAMS = (cs.gate, cs.scope, cs.kickoff, cs.register)


@pytest.fixture()
def isolated():
    """Each column seam empty, and put back whole afterwards."""
    held = [(seam._registered, seam._is_default, seam._default_read) for seam in SEAMS]
    for seam in SEAMS:
        seam.unregister()
    try:
        yield
    finally:
        for seam, (registered, is_default, read) in zip(SEAMS, held):
            seam._registered, seam._is_default, seam._default_read = (
                registered, is_default, read)


def _child(program: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(program)],
                          capture_output=True, text=True, cwd=str(ROOT))


# ---------------------------------------------------------------------------
# 1 — a bare process refuses at each seam, naming it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["gate", "scope", "kickoff", "register"])
def test_a_bare_process_refuses_naming_the_seam_and_the_call(name) -> None:
    done = _child(f"""
        from opendox import column_seams as cs
        try:
            cs.{name}.current()
        except cs.SeamNotRegistered as e:
            print("REFUSED", e)
        else:
            print("ANSWERED")
        """)
    assert done.returncode == 0, done.stderr
    out = done.stdout
    assert out.startswith("REFUSED"), out
    assert f"opendox.column_seams.{name}" in out, out
    assert f"opendox.column_seams.{name}.register(" in out, out
    assert "opendox.default_columns" in out, out


# ---------------------------------------------------------------------------
# 2 — the entry points register the defaults; hosts replace or are refused
# ---------------------------------------------------------------------------

def _calls_register_defaults(function: ast.FunctionDef) -> bool:
    return any(isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "register_defaults"
               and isinstance(node.func.value, ast.Name)
               and node.func.value.id == "column_seams"
               for node in ast.walk(function))


@pytest.mark.parametrize("module,function", [
    ("cli.py", "build_parser"), ("cli.py", "main"),
    ("serve.py", "build_server"), ("serve.py", "main")])
def test_each_entry_point_registers_the_column_defaults(module, function) -> None:
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    [found] = [node for node in tree.body
               if isinstance(node, ast.FunctionDef) and node.name == function]
    assert _calls_register_defaults(found), (
        f"{module}:{function}() does not call column_seams.register_defaults()")


def test_building_the_parser_registers_openDoxs_own_defaults() -> None:
    done = _child("""
        from opendox import cli, column_seams as cs, default_columns as dc
        cli.build_parser()
        print(cs.gate.current() is dc.GATE, cs.scope.current() is dc.SCOPE,
              cs.kickoff.current() is dc.KICKOFF,
              cs.register.current() is dc.REGISTER,
              cs.gate_records_writable())
        """)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["True", "True", "True", "True", "False"]


class _HostGate:
    """A host's gate: openDox's default's names, with a record writer."""

    def __init__(self) -> None:
        for name in (*cs.GATE_CALLABLES, *cs.GATE_VALUES):
            setattr(self, name, getattr(dc.GATE, name))
        self.written = []
        self.write_gate_action_record = lambda gate, records_dir, record: (
            self.written.append(record) or Path(records_dir) / "record.yaml")


def test_a_host_gate_before_a_read_replaces_the_default(isolated) -> None:
    cs.register_defaults()
    host = _HostGate()
    assert cs.gate.register(host) is host
    assert cs.gate.current() is host
    assert cs.gate_records_writable() is True


def test_a_host_gate_after_the_default_was_read_is_refused(isolated) -> None:
    cs.register_defaults()
    assert cs.gate.current() is dc.GATE
    with pytest.raises(cs.SeamAlreadyRegistered,
                       match="opendox.column_seams.gate.unregister"):
        cs.gate.register(_HostGate())
    assert cs.gate_records_writable() is False


def test_a_registration_lacking_a_name_is_refused_naming_it(isolated) -> None:
    class _Partial:
        resolve_scope = staticmethod(dc.resolve_scope)

    with pytest.raises(TypeError, match="is_live_session_ref") as caught:
        cs.scope.register(_Partial())
    assert "column_seams.scope.register()" in str(caught.value)


def test_a_gate_verb_on_the_default_gate_is_refused_not_a_traceback(
        isolated, tmp_path, capsys) -> None:
    """`cli._commission_cli`, the shared half a contributed gate verb runs,
    over openDox's own gate default: the governed `GateConsole` refuses at
    construction, inside the verb's refusal boundary, so the verb answers
    `<verb> refused: ...` and exit status 1 (Copilot review of
    openDox-code#77, r4170914922)."""
    import argparse
    from opendox import cli
    cs.register_defaults()
    args = argparse.Namespace(repo_root=str(tmp_path), records_dir="records/",
                              actor="brett", outline=None, workflow=None,
                              note=None)
    assert cli._commission_cli("propose", args, "some-topic") == 1
    err = capsys.readouterr().err
    assert err.startswith("propose refused: "), err
    assert "opendox.column_seams.gate.register(" in err, err


def test_a_gate_whose_refusal_is_not_an_exception_class_is_refused(
        isolated) -> None:
    """`except gate.GateRefused` needs a class: a function would pass the name
    probe and raise `TypeError` at the first refusal a verb catches."""
    host = _HostGate()
    host.GateRefused = lambda *args: None
    with pytest.raises(TypeError, match="GateRefused must be an exception class"):
        cs.gate.register(host)
    assert cs.gate.is_registered() is False


def test_a_register_whose_adapter_cannot_discover_is_refused(isolated) -> None:
    class _NoDiscover:
        CrossReferenceIndexAdapter = staticmethod(lambda *args: None)

    with pytest.raises(TypeError, match="callable `discover`") as caught:
        cs.register.register(_NoDiscover())
    assert "column_seams.register.register()" in str(caught.value)
    assert cs.register.is_registered() is False


def test_gate_records_are_writable_only_with_a_hosts_gate(isolated) -> None:
    assert cs.gate_records_writable() is False          # nothing at all
    cs.register_defaults()
    assert cs.gate_records_writable() is False          # openDox's default
    cs.gate.unregister()
    cs.gate.register(_HostGate())
    assert cs.gate_records_writable() is True


def test_the_defaults_carry_every_name_their_seams_require() -> None:
    for default, names in ((dc.GATE, (*cs.GATE_CALLABLES, *cs.GATE_VALUES)),
                           (dc.SCOPE, cs.SCOPE_CALLABLES),
                           (dc.KICKOFF, cs.KICKOFF_CALLABLES),
                           (dc.REGISTER, cs.REGISTER_CALLABLES)):
        missing = [name for name in names if not hasattr(default, name)]
        assert missing == [], (default, missing)


# ---------------------------------------------------------------------------
# 3 — the gate default: real primitives, governed functions refused by name
# ---------------------------------------------------------------------------

def test_the_human_gate_guard_passes_a_human_and_reports_anything_else(tmp_path) -> None:
    human = HumanGate(tmp_path, ["records/"], human_actor="fixture")
    assert dc.GATE.require_human_gate(human) is human
    machinery = OutputBoundary(tmp_path, ["records/"], actor="agent")
    with pytest.raises(BoundaryViolation):
        dc.GATE.require_human_gate(machinery)
    assert machinery.refusals, "the refusal was not reported on its own ledger"


def test_the_stamp_the_clock_the_prefix_and_the_ref_target() -> None:
    assert dc.GATE._stamp("2026-10-02T20:00:00Z") == "20261002T200000Z"
    assert dc.GATE._prefix("records") == "records/"
    assert dc.GATE._prefix("records/") == "records/"
    assert dc.GATE.ref_target_id("cluster/cl-a") == "cluster-cl-a"
    assert len(dc.GATE._utcnow()) == len("2026-10-02T20:00:00Z")


def test_a_provenance_is_a_validated_type() -> None:
    assert dc.GATE.HTTP_CONSOLE_TOKEN.as_record() == {
        "surface": "http", "console_presence": "console-token"}
    cli_tty = dc.GATE.Provenance(dc.GATE.SURFACE_CLI, dc.GATE.PRESENCE_TTY)
    assert cli_tty.as_record() == {"surface": "cli", "console_presence": "tty"}
    with pytest.raises(dc.GATE.GateRefused):
        dc.GATE.Provenance("smoke-signal", dc.GATE.PRESENCE_TTY)


def test_the_first_edit_gate_declares_the_records_and_thread_trees(tmp_path) -> None:
    from opendox.doxbench_threads import THREAD_PREFIX

    gate = dc.GATE.first_edit_gate_factory("fixture", "records/")(tmp_path)
    assert isinstance(gate, HumanGate)
    assert set(gate.output.allowlist) >= {"records/", THREAD_PREFIX}
    assert gate.output.session_root == tmp_path.resolve()


@pytest.mark.parametrize("name", [
    "build_gate_action_record", "validate_gate_action_record",
    "write_gate_action_record", "validate_demotion_execution_receipt",
    "GateConsole"])
def test_the_governed_functions_refuse_naming_the_seam(name) -> None:
    with pytest.raises(dc.GateRecordsNotRegistered) as caught:
        getattr(dc.GATE, name)(object(), "records/", {})
    assert isinstance(caught.value, dc.GATE.GateRefused)
    text = str(caught.value)
    assert "opendox.column_seams.gate" in text, text
    assert "opendox.column_seams.gate.register(" in text, text
    assert "model-binding add" in text, text


# ---------------------------------------------------------------------------
# 4 — the scope, kickoff and register defaults
# ---------------------------------------------------------------------------

def _snapshot() -> dict:
    return {
        "generation": {"source_revision": "abc123"},
        "documents": [{"id": p, "path": p} for p in
                      ("a.md", "b.md", "c.md", "sel.md", "gone.md")],
        "clusters": [
            {"id": "g1", "name": "Group one", "topics": ["barrel"],
             "document_edges": [{"document": "a.md"}, {"document": "b.md"}]},
            {"id": "g2", "name": "Group two", "topics": ["shed"],
             "document_edges": [{"document": "c.md"}, {"document": "gone.md"}]}],
        "possibles": [{"id": "p1", "title": "A candidate",
                       "claiming_clusters": ["g1", "g2"]}],
        "staged_topics": [{"staging_id": "s1", "files": ["sel.md"]}],
    }


@pytest.fixture()
def corpus(tmp_path):
    for name in ("a.md", "b.md", "c.md", "sel.md"):
        (tmp_path / name).write_text("# x\n", encoding="utf-8")
    ps.register_defaults()          # the registry seam's containment rule
    return tmp_path


def _key(kind: str, tile: str) -> ScopeKey:
    return ScopeKey(repository="fixture", ref="main", tile_kind=kind, tile_id=tile)


@pytest.mark.parametrize("kind,tile,context,title", [
    ("cluster", "g1", ("a.md", "b.md"), "Group one"),
    ("staged", "s1", ("sel.md",), "s1"),
    ("possible", "p1", ("a.md", "b.md", "c.md"), "A candidate"),
])
def test_each_tile_projects_its_own_documents_editable(
        corpus, kind, tile, context, title) -> None:
    """RULED `5961651355` ("Tile's own documents editable"): every section a
    tile projects is its own, so its resolved documents are both readable and
    editable, and the candidates are what the turn guard would accept."""
    projection = dc.resolve_scope(_snapshot(), _key(kind, tile), source_root=corpus)
    assert projection.title == title
    assert projection.context_paths == context
    assert projection.editable_paths == context
    assert projection.active_document_candidates == context
    assert projection.outline_path is None
    assert projection.source_revision == "abc123"
    assert all(section.owned for section in projection.sections)


def test_nothing_outside_the_tile_is_editable(corpus) -> None:
    """The group's own two, never the corpus's other documents."""
    projection = dc.resolve_scope(_snapshot(), _key("cluster", "g1"), source_root=corpus)
    assert set(projection.editable_paths) == {"a.md", "b.md"}
    for other in ("c.md", "sel.md"):
        assert other not in projection.editable_paths
        assert other not in projection.context_paths


def test_a_listed_document_missing_from_the_tree_is_not_resolved(corpus) -> None:
    projection = dc.resolve_scope(_snapshot(), _key("cluster", "g2"), source_root=corpus)
    rows = {row.path: row.resolved for row in projection.sections[0].documents}
    assert rows == {"c.md": True, "gone.md": False}
    assert projection.context_paths == ("c.md",)
    assert projection.editable_paths == ("c.md",), "an unresolved row is not editable"


def test_a_created_path_is_readable_and_never_editable(corpus) -> None:
    projection = dc.resolve_scope(_snapshot(), _key("cluster", "g1"),
                                  source_root=corpus, created_paths=["new.md"])
    assert projection.context_paths == ("a.md", "b.md", "new.md")
    assert projection.editable_paths == ("a.md", "b.md")


@pytest.mark.parametrize("settings", [
    "ideation/dashboard/model-provider-bindings.yaml",
    "ideation/dashboard/model-declarations.yaml",
])
def test_opendoxs_own_settings_documents_are_never_editable(
        corpus, settings) -> None:
    """Adversarial review 2, M1: a group whose members include one of
    openDox's own settings documents does not make it editable or owned. It
    stays readable, in a section nothing owns."""
    from opendox import doxbench_binding, doxbench_intake
    assert dc.SETTINGS_DOCUMENTS == {doxbench_binding.DEFAULT_BINDINGS_RELPATH,
                                     doxbench_intake.DEFAULT_DECLARATIONS_RELPATH}
    target = corpus / settings
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("schema_version: 1\n", encoding="utf-8")
    snapshot = _snapshot()
    snapshot["documents"].append({"id": settings, "path": settings})
    snapshot["clusters"][0]["document_edges"].append({"document": settings})
    projection = dc.resolve_scope(snapshot, _key("cluster", "g1"), source_root=corpus)
    assert projection.editable_paths == ("a.md", "b.md")
    assert settings not in projection.active_document_candidates
    assert settings in projection.context_paths, "readable, never editable"
    owned = {row.path for section in projection.sections if section.owned
             for row in section.documents}
    assert settings not in owned
    (holder,) = [section for section in projection.sections
                 if settings in {row.path for row in section.documents}]
    assert holder.key == "settings" and holder.owned is False


def test_the_editable_set_refuses_a_settings_document_in_any_section() -> None:
    """`editable_paths` itself, over an owned section that carries one."""
    from opendox.doxbench_scope_types import ScopeDocument, ScopeSection
    section = ScopeSection(
        key="k", label="l", note="n", inherited=False, owned=True,
        documents=tuple(ScopeDocument(id=p, path=p, resolved=True) for p in
                        ("a.md", *sorted(dc.SETTINGS_DOCUMENTS))))
    assert dc.editable_paths([section]) == ("a.md",)


def test_the_editable_set_is_the_owned_sections_resolved_rows() -> None:
    """`editable_paths` itself: owned sections only, resolved rows only, once
    each and in order."""
    from opendox.doxbench_scope_types import ScopeDocument, ScopeSection

    def section(owned, *rows):
        return ScopeSection(
            key="k", label="l", note="n", inherited=False, owned=owned,
            documents=tuple(ScopeDocument(id=p, path=p, resolved=r)
                            for p, r in rows))

    assert dc.editable_paths([section(False, ("a.md", True))]) == ()
    assert dc.editable_paths([
        section(True, ("a.md", True), ("gone.md", False)),
        section(False, ("b.md", True)),
        section(True, ("c.md", True), ("a.md", True)),
    ]) == ("a.md", "c.md")


def test_an_unknown_tile_is_none(corpus) -> None:
    assert dc.resolve_scope(_snapshot(), _key("cluster", "nope"), source_root=corpus) is None


@pytest.mark.parametrize("path", ["../escape.md", "/etc/passwd", "a/../b.md", "a\\b.md", ""])
def test_a_path_the_scope_cannot_name_safely_is_refused(corpus, path) -> None:
    snapshot = _snapshot()
    snapshot["clusters"][0]["document_edges"].append({"document": path})
    with pytest.raises(ScopeConfinementError):
        dc.resolve_scope(snapshot, _key("cluster", "g1"), source_root=corpus)


def test_a_symlink_out_of_the_root_is_not_resolved(corpus, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "secret.md"
    outside.write_text("secret\n", encoding="utf-8")
    (corpus / "link.md").symlink_to(outside)
    snapshot = _snapshot()
    snapshot["documents"].append({"id": "link.md", "path": "link.md"})
    snapshot["clusters"][0]["document_edges"].append({"document": "link.md"})
    projection = dc.resolve_scope(snapshot, _key("cluster", "g1"), source_root=corpus)
    assert "link.md" not in projection.context_paths


def test_no_session_created_path_and_no_live_session_without_a_registry() -> None:
    key = _key("cluster", "g1")
    assert dc.session_created_paths_for_scope(
        None, key, repository="fixture", ref="cluster/g1", source_root=".") == ()
    assert dc.is_live_session_ref(None, key, repository="fixture",
                                  ref="cluster/g1") is False


def test_kickoff_and_register_answer_nothing(tmp_path) -> None:
    assert dc.KICKOFF.dispatched_commissions(tmp_path, "create-project") == {}
    assert dc.KICKOFF.dispatched_commission_rows(tmp_path, "edit-project") == []
    assert dc.KICKOFF.dispatched_propose_topics(tmp_path) == set()
    assert dc.KICKOFF.discover_project_register(tmp_path) is None
    assert tuple(dc.REGISTER.CrossReferenceIndexAdapter.discover(tmp_path).possibles()) == ()
