"""The staging workbench offers the editors and the chat rail BY SCOPE (plan 034
T102).

RULED by Brett Heap, opensoft/openxFactory#656 comment `5963618568`, "Edit and
chat by scope (Recommended)": the editors and the chat rail appear wherever the
scope lets the document be edited, and only creating documents and Save stay
behind the gate, so Save is refused by name. It builds on `5961651355`, "Tile's
own documents editable (Recommended)": openDox's own neutral scope default
(`opendox.default_columns.resolve_scope`, T084) marks a tile's OWN documents
editable.

The defect this measures. A standalone install registers no
`gate.workbench.create` column, so `createColumn.createGateLive(caps)` was the
null column's `false`, and every workbench it opened was read-only: no editor,
no rail, and a disabled `edit` verb, though its `/capabilities` reads
`edit: true` and its own scope makes the tile's documents editable (the T096
prep run, AT-R1 step 7).

Three layers, each against the code the browser runs:

1. THE POSTURE MATRIX, pure (`editingPosture`, `documentEditable`,
   `presentationPosture`): gate on/off x edit on/off x document editable/not,
   with the governed column as the fourth fact.
2. PARITY with the server: the browser's `tileOwnEditablePaths` against
   `default_columns.resolve_scope(...).editable_paths`, tile by tile.
3. THE REAL SHELL, mounted in node over the shared DOM instrument, standalone
   (the null columns, exactly as `app.js` hands them down) and governed (the
   contributed column the other shell harnesses mount).

Two mutants this module kills, recorded in the PR: the old gate-only posture
(the standalone cases fail: no canvas), and an editable-everything posture (the
nothing-editable, per-document and parity cases fail).
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT
from opendox import default_columns as dc
from opendox import projection_seams as ps
from opendox.doxbench_scope_types import ScopeConfinementError, ScopeKey
# The SAME DOM instrument and the SAME contributed column every other shell
# harness mounts with, imported rather than copied so they cannot drift.
from test_doxbench_view import _CONTRIBUTED_GATE, _EDITOR_DOM_SHIM

NODE = shutil.which("node")
WEB = REPO_ROOT / "src" / "opendox" / "web"
VIEWS = WEB / "views"
VENDOR = WEB / "vendor"

# ONE snapshot for every layer. Each tile is chosen for a reason:
#   g1     a group whose two members are both catalogued and on disk
#   g2     a group with an uncatalogued member (`gone.md`) and one (`both.md`)
#          that a candidate also CITES
#   g3     a group with no members at all
#   gbad   a group carrying a path the scope cannot name safely
#   p1     a candidate citing `cited.md` and `both.md`, claimed by g1 and g2
#   p2     a candidate that only cites: nothing of its own to edit
#   p3     a candidate claimed by a group that does not exist
#   s1     a selection naming one catalogued file and one that is not
SNAPSHOT = {
    "repository": "fixture",
    "generation": {"source_revision": "1" * 40},
    "documents": [
        {"id": p, "path": p, "topics": ["barrel"]}
        for p in ("a.md", "b.md", "c.md", "sel.md", "cited.md", "both.md")
    ] + [{"id": "decl.md", "path": "decl.md", "topics": ["barrel"],
          "destinations": {"staged_topics": ["s1"]}}],
    "clusters": [
        {"id": "g1", "name": "Group one", "topics": ["barrel"],
         "document_edges": [{"document": "a.md"}, {"document": "b.md"}]},
        {"id": "g2", "name": "Group two", "topics": ["barrel"],
         "document_edges": [{"document": "c.md"}, {"document": "gone.md"},
                            {"document": "both.md"}]},
        {"id": "g3", "name": "Group three", "topics": [], "document_edges": []},
        {"id": "gbad", "name": "Group bad", "topics": [],
         "document_edges": [{"document": "a.md"}, {"document": "../escape.md"}]},
    ],
    "possibles": [
        {"id": "p1", "title": "Candidate one",
         "supporting_evidence": [{"document": "cited.md"}, {"document": "both.md"}],
         "claiming_clusters": ["g1", "g2"]},
        {"id": "p2", "title": "Candidate two",
         "supporting_evidence": [{"document": "cited.md"}],
         "claiming_clusters": []},
        {"id": "p3", "title": "Candidate three",
         "supporting_evidence": [], "claiming_clusters": ["nope"]},
    ],
    "staged_topics": [{"staging_id": "s1", "files": ["sel.md", "notes.yaml"]}],
}

# Every file the scope resolves inside the checkout. `gone.md` is listed by g2
# and catalogued by nothing, so it is neither here nor in `documents`.
ON_DISK = ("a.md", "b.md", "c.md", "sel.md", "cited.md", "both.md", "decl.md")

PARITY_TILES = [
    ("cluster", "g1"), ("cluster", "g2"), ("cluster", "g3"),
    ("cluster", "gbad"), ("cluster", "nope"),
    ("possible", "p1"), ("possible", "p2"), ("possible", "p3"),
    ("possible", "nope"),
    ("staged", "s1"), ("staged", "nope"),
]


def _stage(tmp_path_factory, name: str, harness: str) -> dict:
    """Copy the bundle's views and vendor next to `harness`, run it under node
    over the shared snapshot, and return the one JSON object it prints."""
    if NODE is None:
        pytest.skip("node not available for the workbench edit-by-scope probe")
    root = tmp_path_factory.mktemp(name)
    shutil.copytree(VIEWS, root / "views")
    shutil.copytree(VENDOR, root / "vendor")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (root / "vendor" / "package.json").write_text('{"type": "commonjs"}',
                                                  encoding="utf-8")
    snapshot = root / "snapshot.json"
    snapshot.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    script = root / "views" / (name + ".mjs")
    script.write_text(harness, encoding="utf-8")
    done = subprocess.run([NODE, str(script), str(snapshot)],
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ===========================================================================
# 1. THE POSTURE MATRIX, pure
# ===========================================================================

_MODEL_HARNESS = r"""
import { readFileSync } from 'node:fs';
const m = await import('./staging-workbench-model.js');
const SNAP = JSON.parse(readFileSync(process.argv[2], 'utf-8'));
const out = {};

out.modes = m.EDITING_MODES;
out.matrix = [];
for (const governed of [true, false]) {
  for (const gate of [true, false]) {
    // a gate is a HOST's column: openDox's null column always answers false
    if (gate && !governed) continue;
    for (const edit of [true, false]) {
      for (const editable of [true, false]) {
        const p = m.editingPosture({
          governed, gateLive: gate, editLive: edit, surfaceHidden: false,
          editablePaths: editable ? ['a.md'] : [] });
        out.matrix.push({ governed, gate, edit, editable,
          mode: p.mode, editors: p.editors, create: p.create, save: p.save,
          editablePaths: p.editablePaths, frozen: Object.isFrozen(p),
          docEditable: m.documentEditable(p, 'a.md'),
          otherEditable: m.documentEditable(p, 'z.md') });
      }
    }
  }
}
out.hidden = [true, false].map((governed) => m.editingPosture({
  governed, gateLive: governed, editLive: true, surfaceHidden: true,
  editablePaths: ['a.md'] }));
// `edit` must be TRUE, not merely present: an older serve reports none
out.editAbsent = m.editingPosture({ governed: false, gateLive: false,
  editablePaths: ['a.md'] }).mode;

const plane = (extra) => ({ repository: 'fixture', ref: 'main',
  sourceAvailable: true, approvedModelCount: 0, ...extra });
out.posture = {
  // a governed host, which never passes the by-scope mode: as before T102
  governedGateOffBare: m.presentationPosture(plane({ gateLive: false })),
  governedGateOff: m.presentationPosture(plane({ gateLive: false,
    editing: m.EDITING_MODES.readOnly })),
  governedGateOnBare: m.presentationPosture(plane({ gateLive: true })),
  governedGateOn: m.presentationPosture(plane({ gateLive: true,
    editing: m.EDITING_MODES.gate })),
  // standalone
  scopeNoModel: m.presentationPosture(plane({ gateLive: false,
    editing: m.EDITING_MODES.scope })),
  scopeWithModel: m.presentationPosture(plane({ gateLive: false,
    editing: m.EDITING_MODES.scope, approvedModelCount: 1 })),
  scopeUnkeyed: m.presentationPosture(plane({ gateLive: false,
    editing: m.EDITING_MODES.scope, ref: '' })),
  nothingEditable: m.presentationPosture(plane({ gateLive: false,
    editing: m.EDITING_MODES.nothing })),
  hiddenScope: m.presentationPosture(plane({ gateLive: false,
    editing: m.EDITING_MODES.scope, surfaceHidden: true })),
};
out.notes = { scope: m.scopeEditingNote(), nothing: m.nothingEditableNote(),
              gateless: m.GATELESS_SAVE_REFUSAL };

// the projection the canvas mounts over, both authorities
const outlinePathFor = () => null;
out.projection = {
  tile: m.doxbenchScopeProjection(SNAP, 'possible', 'p1',
    { repository: 'fixture', ref: 'main', outlinePathFor, editableBy: 'tile' }),
  host: m.doxbenchScopeProjection(SNAP, 'possible', 'p1',
    { repository: 'fixture', ref: 'main', outlinePathFor }),
};
const scope = m.workbenchScope(SNAP, 'possible', 'p1');
out.entries = {
  byScope: m.docWheelEntries(scope, { editable: m.tileOwnEditablePaths(SNAP, 'possible', 'p1') })
    .map((e) => ({ path: e.path, editable: e.editable, owned: e.owned })),
  byGate: m.docWheelEntries(scope)
    .map((e) => ({ path: e.path, keys: Object.keys(e).sort() })),
};
out.parity = {};
for (const [kind, id] of JSON.parse(process.argv[3] || '[]')) {
  out.parity[kind + '/' + id] = m.tileOwnEditablePaths(SNAP, kind, id);
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    if NODE is None:
        pytest.skip("node not available for the workbench edit-by-scope probe")
    root = tmp_path_factory.mktemp("edit-by-scope-model")
    shutil.copytree(VIEWS, root / "views")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    snapshot = root / "snapshot.json"
    snapshot.write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    script = root / "views" / "model-harness.mjs"
    script.write_text(_MODEL_HARNESS, encoding="utf-8")
    done = subprocess.run(
        [NODE, str(script), str(snapshot), json.dumps(PARITY_TILES)],
        capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# (governed, gate, edit, editable) -> (mode, editors, create, save,
# this document editable, a document outside the scope editable)
MATRIX = {
    # A GOVERNED HOST: its gate decides, exactly as before T102.
    (True, True, True, True): ("gate", True, True, "gate", True, True),
    (True, True, True, False): ("gate", True, True, "gate", True, True),
    (True, True, False, True): ("gate", True, True, "gate", True, True),
    (True, True, False, False): ("gate", True, True, "gate", True, True),
    (True, False, True, True): ("read-only", False, False, "absent", False, False),
    (True, False, True, False): ("read-only", False, False, "absent", False, False),
    (True, False, False, True): ("read-only", False, False, "absent", False, False),
    (True, False, False, False): ("read-only", False, False, "absent", False, False),
    # STANDALONE: no column, so no gate; editing by scope.
    (False, False, True, True): ("scope", True, False, "refused", True, False),
    (False, False, True, False): ("nothing-editable", False, False, "absent", False, False),
    (False, False, False, True): ("read-only", False, False, "absent", False, False),
    (False, False, False, False): ("read-only", False, False, "absent", False, False),
}


def test_the_posture_matrix_gate_by_edit_by_editable(model) -> None:
    """Every cell, against the table above. Under the gate the editors are
    offered and every document loads, as before; by scope the editors are
    offered only where the scope makes a document editable, create is absent,
    Save is present and refused, and only the scope's documents load."""
    seen = {}
    for row in model["matrix"]:
        key = (row["governed"], row["gate"], row["edit"], row["editable"])
        seen[key] = (row["mode"], row["editors"], row["create"], row["save"],
                     row["docEditable"], row["otherEditable"])
        assert row["frozen"] is True, key
    assert seen == MATRIX


def test_the_by_scope_posture_carries_exactly_the_scopes_set(model) -> None:
    by_scope = [r for r in model["matrix"] if r["mode"] == "scope"]
    assert [r["editablePaths"] for r in by_scope] == [["a.md"]]
    # under the gate there is no set: every document stays loadable
    assert all(r["editablePaths"] is None for r in model["matrix"]
               if r["mode"] == "gate")


def test_the_hosted_plane_offers_no_editing_whatever_else_it_claims(model) -> None:
    for posture in model["hidden"]:
        assert posture["mode"] == "hidden"
        assert posture["editors"] is False and posture["create"] is False


def test_edit_must_be_stated_true_not_merely_absent(model) -> None:
    """An older serve reports no `edit` key; that is not a licence to edit."""
    assert model["editAbsent"] == "read-only"


GATE_OFF = {
    "kind": "gate-off", "canvas": False,
    "note": ("read-only: the create/edit gate is off here, so editing, chat, "
             "and Save are not offered — retained context stays readable."),
}
EDITOR_ONLY = {
    "kind": "editor-only", "canvas": True, "chat": True, "intakeOffered": False,
    "note": ("chat is unavailable — no approved model is configured; both "
             "editors remain fully usable."),
}


def test_a_governed_hosts_presentation_posture_is_unchanged(model) -> None:
    """The ladder reads exactly what it read before T102 for every caller that
    does not pass the by-scope mode, with or without the new fact."""
    posture = model["posture"]
    assert posture["governedGateOffBare"] == GATE_OFF
    assert posture["governedGateOff"] == GATE_OFF
    assert posture["governedGateOnBare"] == EDITOR_ONLY
    assert posture["governedGateOn"] == EDITOR_ONLY


def test_the_by_scope_posture_offers_the_canvas_and_states_save_by_name(model) -> None:
    posture = model["posture"]
    scoped = posture["scopeNoModel"]
    # the chat rung is unchanged (its sentence is the send button's)…
    assert {k: scoped[k] for k in EDITOR_ONLY} == EDITOR_ONLY
    # …and the plane fact rides beside it
    assert scoped["editing"] == "scope"
    assert scoped["scopeNote"] == model["notes"]["scope"]
    assert "Save is refused by name" in scoped["scopeNote"]
    assert "source items" in scoped["scopeNote"], "the facet's word, not a literal"
    capable = posture["scopeWithModel"]
    assert capable["kind"] == "capable-local" and capable["canvas"] is True
    assert capable["scopeNote"] == model["notes"]["scope"]
    # a posture that withholds the canvas states no editing it does not offer
    assert posture["scopeUnkeyed"]["kind"] == "unkeyed"
    assert "scopeNote" not in posture["scopeUnkeyed"]
    assert posture["hiddenScope"]["kind"] == "hosted-hidden"
    assert "scopeNote" not in posture["hiddenScope"]


def test_nothing_editable_in_scope_says_so_rather_than_blaming_a_gate(model) -> None:
    nothing = model["posture"]["nothingEditable"]
    assert nothing == {"kind": "nothing-editable", "canvas": False,
                       "note": model["notes"]["nothing"]}
    assert "gate" not in nothing["note"]


def test_the_tile_projection_mirrors_the_neutral_scope(model) -> None:
    """`editableBy: "tile"` is what a standalone server answers: the tile's own
    documents, editable, and nothing else in context. The host projection is
    unchanged, and on this candidate owns nothing."""
    tile = model["projection"]["tile"]
    assert tile["editable_paths"] == ["a.md", "b.md", "c.md", "both.md"]
    assert tile["context_paths"] == ["a.md", "b.md", "c.md", "both.md"]
    assert "cited.md" not in tile["context_paths"]
    assert tile["active_document_candidates"] == ["a.md", "b.md", "c.md", "both.md"]
    assert tile["outline_path"] is None
    host = model["projection"]["host"]
    assert host["editable_paths"] == []
    assert host["context_paths"] == ["cited.md", "both.md", "a.md", "b.md", "c.md"]
    assert host["active_document_candidates"] == []


def test_each_docs_tile_says_whether_it_is_the_tiles_own(model) -> None:
    by_scope = {e["path"]: (e["editable"], e["owned"])
                for e in model["entries"]["byScope"]}
    assert by_scope == {
        "cited.md": (False, False),
        "both.md": (True, True),   # cited AND claimed: the scope's answer wins
        "a.md": (True, True), "b.md": (True, True), "c.md": (True, True),
        "gone.md": (False, False),
    }
    # under the gate the entries carry neither key, as before
    assert all("editable" not in e["keys"] and "owned" not in e["keys"]
               for e in model["entries"]["byGate"])


# ===========================================================================
# 2. PARITY with the server's neutral scope
# ===========================================================================

@pytest.fixture()
def corpus(tmp_path):
    for name in ON_DISK:
        (tmp_path / name).write_text("# x\n", encoding="utf-8")
    ps.register_defaults()          # the registry seam's containment rule
    return tmp_path


@pytest.mark.parametrize("kind,tile", PARITY_TILES,
                         ids=[f"{k}-{t}" for k, t in PARITY_TILES])
def test_the_browser_set_is_the_servers_set(model, corpus, kind, tile) -> None:
    """`tileOwnEditablePaths` against `default_columns.resolve_scope`, tile by
    tile: the same paths in the same order. Where the server cannot project a
    tile at all (an unknown one answers None, a path it cannot name raises),
    the browser offers nothing."""
    key = ScopeKey(repository="fixture", ref="main", tile_kind=kind, tile_id=tile)
    try:
        projection = dc.resolve_scope(SNAPSHOT, key, source_root=corpus)
    except ScopeConfinementError:
        server = ()
    else:
        server = () if projection is None else projection.editable_paths
    assert tuple(model["parity"][f"{kind}/{tile}"]) == tuple(server)


def test_the_parity_fixture_reaches_every_branch(model, corpus) -> None:
    """A parity table of empty answers would agree vacuously, so the fixture's
    interesting tiles are held to their shapes too."""
    parity = model["parity"]
    assert parity["cluster/g1"] == ["a.md", "b.md"]
    assert parity["cluster/g2"] == ["c.md", "both.md"], "gone.md is uncatalogued"
    assert parity["possible/p1"] == ["a.md", "b.md", "c.md", "both.md"]
    assert parity["staged/s1"] == ["sel.md"]
    assert parity["cluster/gbad"] == [], "one unnameable path refuses the tile"
    with pytest.raises(ScopeConfinementError):
        dc.resolve_scope(SNAPSHOT, ScopeKey(repository="fixture", ref="main",
                                            tile_kind="cluster", tile_id="gbad"),
                         source_root=corpus)


# ===========================================================================
# 3. THE REAL SHELL, standalone and governed
# ===========================================================================

_SHELL_HARNESS = _EDITOR_DOM_SHIM + _CONTRIBUTED_GATE + r"""
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

globalThis.markdownit = createRequire(import.meta.url)('../vendor/markdown-it.min.js');
globalThis.window = { location: { href: 'http://localhost/' } };

const { mountStagingWorkbench } = await import('./staging-workbench.js');
const { runSave, savePlanState } = await import('./doxbench-save.js');
const model = await import('./staging-workbench-model.js');
const SNAP = JSON.parse(readFileSync(process.argv[2], 'utf-8'));

const settle = () => new Promise((r) => setTimeout(r, 0));
async function quiesce(n = 30) { for (let i = 0; i < n; i += 1) await settle(); }
async function until(predicate, label) {
  for (let i = 0; i < 600; i += 1) {
    if (predicate()) return;
    await settle();
  }
  throw new Error('timed out waiting for ' + label);
}
function fire(node, type, ev = {}) {
  const listeners = (node.listeners && node.listeners[type]) || [];
  return Promise.all(listeners.map(
    (fn) => fn({ target: node, stopPropagation() {}, preventDefault() {}, ...ev })));
}
class FakeStorage {
  constructor() { this.values = new Map(); }
  getItem(k) { return this.values.has(k) ? this.values.get(k) : null; }
  setItem(k, v) { this.values.set(k, String(v)); }
  removeItem(k) { this.values.delete(k); }
}

// THE STANDALONE SAVE, composed exactly as `app.js` composes it where no host
// contributes `gate.workbench.session`: `runSave` over `refusalTransport()`,
// whose message is the model's one sentence (pinned at app.js below).
const gatelessSave = (request) => runSave(savePlanState(request), {
  transport: async () => ({ ok: false, error: 'no_gate_column',
                            message: model.GATELESS_SAVE_REFUSAL }),
  ...(request && request.only !== undefined ? { only: request.only } : {}) });

// What a standalone `/capabilities` reads (the T096 prep run's caps.json):
// gate false, edit true, session true.
const STANDALONE = { actions: { notebook: false, gate: false, refresh: false,
  session: true, edit: true, intent: false }, actor: 'fixture',
  console_token: 'token' };
const GOVERNED = { actions: { gate: true, session: true, edit: true },
  actor: 'brett' };

async function mount({ caps, gate, kind, id }) {
  const container = document.createElement('div');
  const log = { turns: [], abstracts: [] };
  const doxbench = {
    loadSource: async (path) => ({ content: '# ' + path + '\n\nbody\n', ref: 'main' }),
    storage: new FakeStorage(),
    // no model is configured anywhere in this module
    catalog: async () => ({ schema_version: 1, kind: 'workbench-model-catalog',
                            models: [] }),
    chatTurn: async (request) => { log.turns.push(request);
      return { ok: false, status: 403,
               payload: { error: 'model_capability_unavailable' } }; },
    save: gatelessSave,
    documentAbstract: async (request) => { log.abstracts.push(request);
      return { ok: false, payload: { error: 'model_capability_unavailable' } }; },
  };
  const workbench = mountStagingWorkbench(container, SNAP, {
    caps, gate, onOpenDoc: () => null, fetcher: async () => ({ ok: false }),
    active: { repository: 'fixture', ref: 'main' }, index: { entries: [] },
    doxbench, sourceBase: '/source/', edit: null,
    onSessionRekey: async () => null, onSessionEnded: async () => null,
    onScopeOpened: () => null,
  });
  workbench.open(kind, id);
  const byClass = (cls) => container.walk().filter(
    (n) => String(n.className).split(' ').includes(cls));
  const one = (cls) => byClass(cls)[0] || null;
  await quiesce(80);
  return { container, workbench, log, byClass, one };
}

function survey(ctx) {
  const head = ctx.one('swb-head');
  const pill = head ? head.children.find(
    (n) => String(n.className).split(' ').includes('pill')) : null;
  const canvas = ctx.one('doxbench-canvas');
  const rail = ctx.one('doxbench-rail');
  const note = ctx.one('swb-posture-note');
  const actions = ctx.byClass('swb-actions');
  return {
    pill: pill ? pill.textContent : null,
    pillTitle: pill ? pill.title : null,
    canvasHidden: canvas ? canvas.hidden : null,
    textareas: ctx.byClass('doxbench-textarea').length,
    railHidden: rail ? rail.hidden : null,
    composer: ctx.byClass('doxchat-composer').length,
    send: ctx.byClass('doxchat-send').length,
    sendDisabled: (ctx.one('doxchat-send') || {}).disabled === true,
    note: note && !note.hidden ? note.textContent : '',
    createButtons: actions.reduce((n, a) =>
      n + a.walk().filter((x) => x.tagName === 'BUTTON').length, 0),
  };
}

// The docs wheel needs a measurable host before it lays tiles out, and only a
// laid-out expanded tile mounts its action row (the composition harness's way).
async function expand(ctx, path) {
  const pane = ctx.container.walk().find((n) => n.__docWheel);
  ctx.one('swb-docselector').clientHeight = 420;
  pane.__docWheelRefresh();
  await quiesce(5);
  const tiles = ctx.byClass('wheeltile');
  const index = tiles.findIndex((t) => t.title === path);
  if (index < 0) throw new Error('no tile for ' + path);
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (tiles[index].querySelector('.wheelactions')) break;
    await fire(tiles[index], 'click');
    await quiesce(5);
  }
  const row = tiles[index].querySelector('.wheelactions');
  if (!row) throw new Error('tile for ' + path + ' never expanded');
  const verb = (cls) => {
    const b = row.querySelector('.' + cls);
    return b ? { disabled: b.disabled === true, title: b.title, node: b } : null;
  };
  return { load: verb('swb-docload'), save: verb('swb-docsave') };
}

// Whether the docs pane offers the model-derived abstract's GENERATE control:
// switch the region to the model view, then look (ruling 7.7 keys it on the gate).
async function generateOffered(ctx) {
  const toggle = ctx.one('swb-abstracttoggle');
  if (!toggle) return null;
  await fire(toggle, 'click');
  await quiesce(5);
  return ctx.byClass('swb-abstractgenerate').length;
}

const plain = (verb) => (verb ? { disabled: verb.disabled, title: verb.title } : null);
const out = {};
// A scenario that cannot complete RECORDS why and the next one still runs, so
// a regression reads as a failed assertion naming the step, not as one fixture
// error swallowing every case below it.
async function scenario(name, body) {
  const o = (out[name] = {});
  try { await body(o); } catch (e) { o.error = String((e && e.message) || e); }
}

// ---- S1: STANDALONE, a group whose members are its own ---------------------
await scenario('s1', async (o) => {
  // the null columns, exactly as app.js hands them down with no binding
  const ctx = await mount({ caps: STANDALONE, gate: { create: null, session: null },
                            kind: 'cluster', id: 'g1' });
  await until(() => ctx.byClass('doxbench-textarea').length >= 2, 'the canvas');
  await until(() => ctx.byClass('doxchat-composer').length > 0, 'the rail');
  await quiesce(40);
  Object.assign(o, survey(ctx));
  o.generate = await generateOffered(ctx);
  const b = await expand(ctx, 'b.md');
  o.loadB = plain(b.load);
  await fire(b.load.node, 'click');
  await quiesce(60);
  o.verbNote = String((ctx.one('swb-docverbnote') || {}).textContent || '');
  o.textareasAfterLoad = ctx.byClass('doxbench-textarea').length;
  // type into the document the load selected, and Save from the canvas
  const areas = ctx.byClass('doxbench-textarea');
  const typed = areas[areas.length - 1];
  typed.value = typed.value + 'typed by a human\n';
  await fire(typed, 'input');
  await until(() => ctx.byClass('doxbench-save')[0].disabled !== true, 'a live Save');
  await fire(ctx.byClass('doxbench-save')[0], 'click');
  await quiesce(80);
  o.canvasSaveRefusedByName = ctx.container.textContent.includes(
    'Save refused -- ' + model.GATELESS_SAVE_REFUSAL);
  o.typedSurvives = typed.value.endsWith('typed by a human\n');
  // …and from the docs tile's own Save, the second entry point
  const again = await expand(ctx, 'b.md');
  o.tileSave = plain(again.save);
  if (again.save && !again.save.disabled) {
    await fire(again.save.node, 'click');
    await quiesce(80);
  }
  o.tileSaveNote = String((ctx.one('swb-docverbnote') || {}).textContent || '');
  o.turns = ctx.log.turns.length;
  o.abstracts = ctx.log.abstracts.length;
});

// ---- S2: STANDALONE, a candidate: its claiming groups' members, not its citations
await scenario('s2', async (o) => {
  const ctx = await mount({ caps: STANDALONE, gate: { create: null, session: null },
                            kind: 'possible', id: 'p1' });
  await until(() => ctx.byClass('doxbench-textarea').length >= 2, 'the canvas');
  await quiesce(40);
  Object.assign(o, survey(ctx));
  o.verbs = {};
  for (const path of ['cited.md', 'both.md', 'a.md']) {
    const v = await expand(ctx, path);
    o.verbs[path] = { load: plain(v.load), save: plain(v.save) };
  }
});

// ---- S3: STANDALONE, a candidate with nothing of its own ---------------------
await scenario('s3', async (o) => {
  const ctx = await mount({ caps: STANDALONE, gate: { create: null, session: null },
                            kind: 'possible', id: 'p2' });
  Object.assign(o, survey(ctx));
  const v = await expand(ctx, 'cited.md');
  o.load = plain(v.load);
});

// ---- S4: STANDALONE without the edit capability (no identity, say) -----------
await scenario('s4', async (o) => {
  const caps = { ...STANDALONE, actions: { ...STANDALONE.actions, edit: false } };
  const ctx = await mount({ caps, gate: { create: null, session: null },
                            kind: 'cluster', id: 'g1' });
  Object.assign(o, survey(ctx));
});

// ---- S5: GOVERNED, the gate live: exactly as before T102 ---------------------
await scenario('s5', async (o) => {
  const ctx = await mount({ caps: GOVERNED, gate: contributedGate().column,
                            kind: 'possible', id: 'p1' });
  await until(() => ctx.byClass('doxbench-textarea').length >= 2, 'the canvas');
  await quiesce(40);
  Object.assign(o, survey(ctx));
  o.generate = await generateOffered(ctx);
  const v = await expand(ctx, 'cited.md');
  o.loadCited = plain(v.load);
});

// ---- S6: GOVERNED, the gate off and `edit` true: read-only, as before --------
await scenario('s6', async (o) => {
  const caps = { actions: { gate: false, session: true, edit: true }, actor: 'brett' };
  const ctx = await mount({ caps, gate: contributedGate().column,
                            kind: 'cluster', id: 'g1' });
  Object.assign(o, survey(ctx));
});

out.notes = { scope: model.scopeEditingNote(), nothing: model.nothingEditableNote(),
              gateless: model.GATELESS_SAVE_REFUSAL };
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    return _stage(tmp_path_factory, "edit-by-scope-shell", _SHELL_HARNESS)


def _ran(shell: dict, name: str) -> dict:
    """One scenario's record, refusing loudly if it could not complete."""
    record = shell[name]
    assert "error" not in record, f"scenario {name} did not complete: {record['error']}"
    return record


GATE_OFF_NOTE = GATE_OFF["note"]


def test_a_standalone_workbench_offers_both_editors_and_the_rail(shell) -> None:
    """AT-R1 step 7's precondition: on a standalone install (no gate column,
    `edit: true`) a group's workbench mounts the canvas AND the chat rail."""
    s1 = _ran(shell, "s1")
    assert s1["canvasHidden"] is False
    assert s1["textareas"] == 2, "the outline buffer and the document buffer"
    assert s1["railHidden"] is False
    assert s1["composer"] == 1 and s1["send"] == 1
    assert s1["sendDisabled"] is True, "no model is configured, so no turn is sent"
    assert s1["turns"] == 0


def test_the_standalone_pill_and_note_state_the_by_scope_posture(shell) -> None:
    s1 = _ran(shell, "s1")
    assert s1["pill"] == "editing by scope"
    assert "Save is refused by name" in s1["pillTitle"]
    assert shell["notes"]["scope"] in s1["note"]
    assert "read-only" not in s1["note"]


def test_creating_a_document_and_generating_an_abstract_stay_behind_the_gate(
        shell) -> None:
    """Create mounts nothing without a column, as before; the abstract's
    GENERATE control is absent rather than present-and-refusing, because ruling
    7.7 keys it on the gate and the route refuses at its step 1 without it."""
    s1 = _ran(shell, "s1")
    assert s1["createButtons"] == 0
    assert s1["generate"] == 0
    assert s1["abstracts"] == 0


def test_the_tiles_own_document_loads_for_editing(shell) -> None:
    s1 = _ran(shell, "s1")
    assert s1["loadB"] == {"disabled": False,
                           "title": "load b.md into the chat context for editing"}
    assert s1["textareasAfterLoad"] == 3
    assert "loaded for editing" in s1["verbNote"]


def test_standalone_save_is_present_and_refused_by_name(shell) -> None:
    """RULED `5963618568`: "only creating documents and Save stay behind the
    gate, so Save is refused by name". Visible, pressed, and answered with the
    sentence that names the gate, from the canvas and from the docs tile, and
    the human's text stays in the buffer."""
    s1 = _ran(shell, "s1")
    assert s1["canvasSaveRefusedByName"] is True
    assert s1["typedSurvives"] is True
    assert s1["tileSave"]["disabled"] is False
    assert "the governed Save did not land" in s1["tileSaveNote"]
    assert shell["notes"]["gateless"] in s1["tileSaveNote"]
    assert "`gate.workbench.session`" in shell["notes"]["gateless"]


def test_the_edit_verb_is_offered_on_exactly_the_scopes_documents(shell) -> None:
    """A candidate's citations are context; its claiming groups' members are
    its own. `both.md` is both, and the scope's answer wins."""
    verbs = _ran(shell, "s2")["verbs"]
    assert verbs["cited.md"]["load"]["disabled"] is True
    assert verbs["cited.md"]["load"]["title"] == (
        "this document is context in the opened tile, not one of the tile's "
        "own, so it is not offered for editing here")
    assert verbs["cited.md"]["save"]["disabled"] is True
    assert "read-only context" in verbs["cited.md"]["save"]["title"]
    for own in ("both.md", "a.md"):
        assert verbs[own]["load"]["disabled"] is False, own


def test_a_tile_with_nothing_of_its_own_stays_read_only_and_says_why(shell) -> None:
    s3 = _ran(shell, "s3")
    assert s3["canvasHidden"] is True and s3["textareas"] == 0
    assert s3["railHidden"] is True and s3["composer"] == 0
    assert s3["pill"] == "read-only"
    assert s3["note"] == shell["notes"]["nothing"]
    assert s3["load"]["disabled"] is True
    assert "editing capability" in s3["load"]["title"]


def test_without_the_edit_capability_a_standalone_workbench_is_read_only(
        shell) -> None:
    s4 = _ran(shell, "s4")
    assert s4["canvasHidden"] is True and s4["textareas"] == 0
    assert s4["railHidden"] is True
    assert s4["pill"] == "read-only"
    assert s4["note"] == GATE_OFF_NOTE


def test_a_governed_host_with_the_gate_live_is_exactly_as_before(shell) -> None:
    """The gate decides: the gate pill, the canvas and the rail, the generate
    control, and EVERY document loadable, a citation included."""
    s5 = _ran(shell, "s5")
    assert s5["pill"] == "gate: create-document"
    assert s5["canvasHidden"] is False and s5["textareas"] >= 2
    assert s5["railHidden"] is False
    assert s5["generate"] == 1
    assert s5["loadCited"]["disabled"] is False
    assert shell["notes"]["scope"] not in s5["note"]


def test_a_governed_host_with_the_gate_off_stays_read_only(shell) -> None:
    """Even with `edit: true`: the by-scope arm is openDox's own default, never
    a host's, so a governed host whose gate is off reads exactly as before."""
    s6 = _ran(shell, "s6")
    assert s6["canvasHidden"] is True and s6["textareas"] == 0
    assert s6["railHidden"] is True
    assert s6["pill"] == "read-only"
    assert s6["note"] == GATE_OFF_NOTE


def test_app_composes_the_standalone_save_from_the_named_refusal() -> None:
    """The shell harness above composes the standalone Save as `app.js` does;
    this holds `app.js` to that composition."""
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert ('import { CONSOLE_TOKEN_FIELD, GATELESS_SAVE_REFUSAL } from '
            '"./views/staging-workbench-model.js";') in app
    transport = app.split("function refusalTransport() {", 1)[1].split("\n}\n", 1)[0]
    assert 'error: "no_gate_column",' in transport
    assert "message: GATELESS_SAVE_REFUSAL," in transport
    assert ": refusalTransport()," in app
    assert "pinned checkout" not in transport


# ===========================================================================
# G8: the display text no longer names a host's surfaces
# ===========================================================================

def test_the_lens_and_the_about_text_name_no_host_surface() -> None:
    lens = (VIEWS / "lens.js").read_text(encoding="utf-8")
    for gone in ('"The tested engine (lens.py) materialises',
                 '"Persisted through the interactivity boundary to "',
                 "Nothing enters the register or any queue from here."):
        assert gone not in lens, gone
    assert ('"Shown for confirmation only: this console cannot carry the plan '
            'out "') in lens
    assert ('"Each button shows its plan below before anything is written; this "'
            in lens)
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert "ideation governance state" not in index
    assert "A projection of one repository's Markdown files and how they group," in index
    wheel = (VIEWS / "wheel.js").read_text(encoding="utf-8")
    assert '" (read-only)",' not in wheel
    assert "? vocab.one(opts.wheelKey) : \"tile\")," in wheel
