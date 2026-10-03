"""The chat rail reads a thread only with a branch session (plan 034, T102
follow-on).

THE FINDING, F1 of the holder's T096 dry run: on a STANDALONE plane, switching
the chat rail's loaded document read `/workbench/thread`. The plane has no
branch session, so every read answered 403 `thread_capability_unavailable`, and
Chromium logged one console error per switch, which AT-R1's oracle counts as
undeclared.

HOLDER RULING F1 (i): fix the product, not the oracle. `app.js` wires the rail's
thread read only when `workbenchGate.session` exists, the same condition as
`refusalTransport`; a composed host, which has a branch session, keeps reading
threads exactly as today.

What is held here, each against the code the browser runs:

1. THE SEAM, `doxbenchThreadSeam` in `app.js`, run under node from `app.js`'s
   own text (the module cannot be imported whole: it boots the page at its
   last line). With no session column it answers "no readable thread" and
   sends nothing; with one, it is the thread loader, unchanged.
2. THE SWITCH, in the real shell: the rail's loaded-document selector is
   switched on a standalone plane (no thread request, the seam still asked,
   so the transcript still empties) and on a composed host (the read happens,
   with the query it always had).
3. `app.js` composes the seam from `workbenchGate.session`, the object
   `refusalTransport`'s choice reads.

Why the standalone seam is a FUNCTION and not absent: the rail treats an
absent `thread` as the pre-§11 rail, which keeps the previous document's
transcript across a switch (`switchThread` in views/doxbench-chat.js), and
carrying one document's turns into another's next request is the defect the
switch exists to close. The standalone answer is the same `null` the 403 gave,
without the request.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from conftest import REPO_ROOT
# The SAME shell harness T102's module mounts the workbench with: its helpers
# (the DOM instrument, `mount`, `expand`, the fake storage) are reused up to
# its first scenario, so the two modules cannot drift.
from test_workbench_edit_by_scope import _SHELL_HARNESS, _stage

NODE = shutil.which("node")
APP_JS = REPO_ROOT / "src" / "opendox" / "web" / "app.js"
CHAT_VIEW_JS = REPO_ROOT / "src" / "opendox" / "web" / "views" / "doxbench-chat.js"

_FIRST_SCENARIO = "// ---- S1: STANDALONE"


def _seam_module() -> str:
    """`app.js`'s thread transport and its seam, as an importable module: the
    two constants they read, then the text from the loader's declaration up to
    the next transport's."""
    app = APP_JS.read_text(encoding="utf-8")
    constants = []
    for name in ("THREAD_ROUTE", "CONSOLE_TOKEN_HEADER"):
        found = re.search(rf"^const {name} = [^\n]*;$", app, re.M)
        assert found, f"app.js no longer declares {name} on one line"
        constants.append(found.group(0))
    start = app.index("export function createDoxBenchThreadLoader(")
    end = app.index("export function createDoxBenchTurnSubmitter(")
    body = app[start:end]
    assert "export function doxbenchThreadSeam(" in body, (
        "the seam must sit beside the loader it chooses")
    return "\n".join(constants) + "\n\n" + body


# ===========================================================================
# 1. THE SEAM
# ===========================================================================

_SEAM_HARNESS = r"""
const { doxbenchThreadSeam } = await import('./app-thread-seam.mjs');
const out = {};
const QUERY = { repository: 'fixture', ref: 'main', tile_kind: 'cluster',
                tile_id: 'g1', document: 'b.md' };
function spy(answer) {
  const calls = [];
  const fetcher = async (url, options) => { calls.push({ url, options }); return answer; };
  return { calls, fetcher };
}

// NO SESSION COLUMN: the standalone plane
{
  const s = spy({ ok: false, status: 403, json: async () => ({}) });
  const seam = doxbenchThreadSeam(null, () => 'token', s.fetcher);
  const answer = await seam(QUERY);
  out.standalone = { kind: typeof seam, answer, calls: s.calls.length };
  const absent = doxbenchThreadSeam(undefined, () => 'token', s.fetcher);
  out.undefinedSession = { kind: typeof absent, answer: await absent(QUERY),
                           calls: s.calls.length };
}
// A SESSION COLUMN: the composed host
{
  const thread = { schema_version: 1, turns: [{ role: 'human', text: 'q' }] };
  const s = spy({ ok: true, status: 200, json: async () => thread });
  const seam = doxbenchThreadSeam({ firstEditTransport: () => null },
                                  () => 'token', s.fetcher);
  const answer = await seam(QUERY);
  out.composed = { kind: typeof seam, answer, calls: s.calls.length,
                   url: s.calls[0] && s.calls[0].url,
                   headers: s.calls[0] && s.calls[0].options.headers };
  // …and the host's own refusals still read as "no readable thread"
  const r = spy({ ok: false, status: 403, json: async () => ({}) });
  const refused = doxbenchThreadSeam({}, () => 'token', r.fetcher);
  out.composedRefused = { answer: await refused(QUERY), calls: r.calls.length };
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def seam(tmp_path_factory):
    if NODE is None:
        pytest.skip("node not available for the thread-seam probe")
    root = tmp_path_factory.mktemp("thread-seam")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (root / "app-thread-seam.mjs").write_text(_seam_module(), encoding="utf-8")
    script = root / "seam-harness.mjs"
    script.write_text(_SEAM_HARNESS, encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_without_a_session_column_the_seam_sends_nothing(seam) -> None:
    """F1: no request, so no 403 and no console error. The answer is the
    `null` the 403 produced, "this document has no readable thread"."""
    assert seam["standalone"] == {"kind": "function", "answer": None, "calls": 0}
    assert seam["undefinedSession"] == {"kind": "function", "answer": None,
                                        "calls": 0}


def test_without_a_session_column_the_seam_is_still_a_function(seam) -> None:
    """An ABSENT seam is the pre-§11 rail, which keeps the previous document's
    transcript across a switch; the standalone seam must still be there to
    answer, so the rail adopts the empty transcript."""
    assert seam["standalone"]["kind"] == "function"


def test_with_a_session_column_the_thread_is_read_as_before(seam) -> None:
    composed = seam["composed"]
    assert composed["kind"] == "function"
    assert composed["calls"] == 1
    assert composed["answer"] == {"schema_version": 1,
                                  "turns": [{"role": "human", "text": "q"}]}
    assert composed["url"] == ("/workbench/thread?repository=fixture&ref=main"
                               "&tile_kind=cluster&tile_id=g1&document=b.md")
    assert composed["headers"] == {"X-XF-Console-Token": "token"}
    assert seam["composedRefused"] == {"answer": None, "calls": 1}


# ===========================================================================
# 2. THE SWITCH, in the real shell
# ===========================================================================

_SWITCH_SCENARIOS = r"""
const { doxbenchThreadSeam } = await import('./app-thread-seam.mjs');

// Every request the page sends through the global fetch, the thread loader's
// own transport when it is handed no injected one (app.js hands it none).
const sent = [];
globalThis.fetch = async (url) => {
  sent.push(String(url));
  if (String(url).startsWith('/workbench/thread?')) {
    return { ok: true, status: 200, json: async () => ({ schema_version: 1, turns: [] }) };
  }
  return { ok: false, status: 404, headers: { get: () => null },
           json: async () => ({}), text: async () => '' };
};
const threadRequests = () => sent.filter((u) => u.startsWith('/workbench/thread'));

// The seam app.js composes, counted at the rail's side: how often the rail
// ASKED, whatever the seam then sent.
function counted(seam) {
  const asked = [];
  const wrapped = async (query) => { asked.push(query); return seam(query); };
  return { asked, wrapped };
}

// Load `path` through its docs tile, then switch the rail's loaded-document
// selector to every other entry once.
async function switchEach(ctx, path) {
  const v = await expand(ctx, path);
  if (!v.load || v.load.disabled) throw new Error('no live edit verb for ' + path);
  await fire(v.load.node, 'click');
  await quiesce(60);
  const select = ctx.one('doxchat-loaded');
  if (!select) throw new Error('the rail has no loaded-document selector');
  const keys = select.children.map((o) => String(o.value));
  const before = threadRequests().length;
  let switches = 0;
  for (const key of keys) {
    if (key === String(select.value)) continue;
    select.value = key;
    await fire(select, 'change');
    await quiesce(40);
    switches += 1;
  }
  return { keys, switches, requests: threadRequests().length - before };
}

// ---- T1: STANDALONE (no session column): no thread request on a switch ----
await scenario('t1', async (o) => {
  const gate = { create: null, session: null };
  const seam = counted(doxbenchThreadSeam(gate.session, () => 'token'));
  const ctx = await mount({ caps: STANDALONE, gate, kind: 'cluster', id: 'g1',
                            thread: seam.wrapped });
  await until(() => ctx.byClass('doxchat-composer').length > 0, 'the rail');
  await quiesce(40);
  Object.assign(o, await switchEach(ctx, 'b.md'));
  o.asked = seam.asked.length;
  o.pill = survey(ctx).pill;
});

// ---- T2: A COMPOSED HOST (a session column): the read still happens -------
await scenario('t2', async (o) => {
  const gate = contributedGate().column;
  const seam = counted(doxbenchThreadSeam(gate.session, () => 'token'));
  const ctx = await mount({ caps: GOVERNED, gate, kind: 'cluster', id: 'g1',
                            thread: seam.wrapped });
  await until(() => ctx.byClass('doxchat-composer').length > 0, 'the rail');
  await quiesce(40);
  Object.assign(o, await switchEach(ctx, 'b.md'));
  o.asked = seam.asked.length;
  o.urls = threadRequests();
  o.pill = survey(ctx).pill;
});

console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def switch(tmp_path_factory):
    head, marker, _ = _SHELL_HARNESS.partition(_FIRST_SCENARIO)
    assert marker, "the shared shell harness lost its first scenario's marker"
    return _stage(tmp_path_factory, "thread-switch-shell",
                  head + _SWITCH_SCENARIOS,
                  extra={"app-thread-seam.mjs": _seam_module()})


def _ran(record: dict, name: str) -> dict:
    scenario = record[name]
    assert "error" not in scenario, f"scenario {name}: {scenario['error']}"
    return scenario


def test_a_standalone_switch_sends_no_thread_request(switch) -> None:
    """AT-R1's oracle saw one undeclared console error per switch; a switch
    now sends nothing, though the rail still asks its seam each time (so the
    transcript still empties, as the 403's `null` made it)."""
    t1 = _ran(switch, "t1")
    assert t1["pill"] == "editing by scope"
    assert t1["switches"] >= 1, t1["keys"]
    assert t1["asked"] == t1["switches"], "the rail asks its seam on every switch"
    assert t1["requests"] == 0


def test_a_composed_hosts_switch_still_reads_the_thread(switch) -> None:
    t2 = _ran(switch, "t2")
    assert t2["pill"] != "editing by scope"
    assert t2["switches"] >= 1, t2["keys"]
    assert t2["asked"] == t2["switches"]
    assert t2["requests"] == t2["switches"]
    for url in t2["urls"]:
        assert url.startswith("/workbench/thread?repository=fixture&ref=main"
                              "&tile_kind=cluster&tile_id=g1&document="), url


# ===========================================================================
# 3. THE COMPOSITION
# ===========================================================================


def test_app_composes_the_thread_seam_from_the_session_column() -> None:
    """`app.js` hands the rail `doxbenchThreadSeam(workbenchGate.session, …)`,
    the same `workbenchGate.session` whose presence picks the Save transport
    over `refusalTransport()`; the bare loader is no longer wired directly."""
    app = APP_JS.read_text(encoding="utf-8")
    assert ("thread: doxbenchThreadSeam(workbenchGate.session,\n"
            "        () => caps?.console_token),") in app
    assert "thread: createDoxBenchThreadLoader(" not in app
    assert "{ transport: workbenchGate.session\n" in app
    assert app.count("createDoxBenchThreadLoader(") == 2, (
        "the declaration and the seam's one call")


def test_the_rail_still_empties_the_transcript_on_a_null_answer() -> None:
    """What the standalone seam relies on: a seam that answers `null` makes the
    rail adopt the EMPTY transcript, and an absent seam returns early."""
    view = CHAT_VIEW_JS.read_text(encoding="utf-8")
    body = view.split("async function switchThread(", 1)[1].split("\n  }", 1)[0]
    assert 'if (typeof load !== "function") return;' in body
    assert ("const turns = answer && Array.isArray(answer.turns) ? answer.turns : [];"
            in body)
    assert "adoptThreadTranscript(state, turns)" in body
