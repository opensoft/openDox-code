"""DOM/module-graph behaviour of the intent-feed OPTIONAL contributed binding
(RULED Q5, `docs/front-end-package-boundary.md` § 6 Q5 / § 4.2,
opensoft/openxFactory#656 comment 5642758731; split-opendox-two-layer-product
§ 3.4, slice S2).

Drives the REAL `dispose.js`, `wheel.js` and `intent-binding.js` under node,
mirroring `tests/test_intent_tray_dom.py`'s and `tests/test_wheel_verbs_dom.py`'s
own DOM-shim harness for this exact pair of views. Nothing here reads a
module's SOURCE (that is `tests/test_intent_binding_shape.py`'s job); every
claim below is made by actually loading the module graph and, where useful,
mounting and inspecting the resulting tree — so a passing test means the
behaviour exists, not that the code looks right.

NOT PART OF `.github/workflows/validate.yml`'s explicit list. Every existing
DOM probe of `web/` — including `test_intent_tray_dom.py`, the carried-over
test of this SAME pair of views — is narrowed out of the required check
(RULED Q-L5 (b′)) until the BUILD arc inverts the openDox -> openXdox
dependency; un-narrowing that class of test is slice S8's job, not S2's. This
file is deliberately on the same footing as its narrowed siblings: present in
the tree, runnable by hand or by a future un-narrowed `validate`, and skipped
outright where `node` is not on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# Computed locally rather than imported from `conftest.REPO_ROOT`
# (`tests/conftest.py`'s own `HERE.parent.parent`, a formula this leg
# inherited byte-identical from `tests/ideation-dashboard/conftest.py` at
# one directory level deeper than it now sits, so it resolves ONE LEVEL
# ABOVE this repository today — latent and, so far, harmless, because
# nothing that depends on it currently loads outside `--noconftest` either,
# for the unrelated reason `.github/workflows/validate.yml` narrows around
# (RULED Q-L5 (b′): `session_fixtures.py` -> `opendox.session_pr` ->
# `opendox.serve` -> the still-present `ideation_dashboard` back-import).
# `tests/test_leg_shape.py`'s own `Path(__file__).resolve().parents[1]` is
# the correct, self-contained pattern this file mirrors instead.
ROOT = Path(__file__).resolve().parents[1]

NODE = shutil.which("node")
WEB = ROOT / "src" / "opendox" / "web"

# The complete static dependency closure of wheel.js at this leg, MINUS
# intent-feed.js (RULED `not_moved`, never carried here) and PLUS
# intent-binding.js (the seam this slice adds). Measured by reading each
# file's own `^import` lines: wheel-model.js, helpers.js, notebook.js and
# settings.js are import-free leaves. A file added to this set by a future
# slice without updating this constant fails loudly (`_write_tree` copies
# exactly this list, so a newly-added import the closure omits is a
# `MODULE_NOT_FOUND` in the harness, not a silent gap).
#
# `dispose.js` LEFT THE CLOSURE AT SLICE S5, and it left twice over: it is no
# longer in this bundle at all (openXdox-code's package data, RULED Q5,
# openxFactory#656 comment `5648044785`), and `wheel.js` no longer imports it —
# the shell resolves the `gate.dispose` binding and hands its declared namespace
# down as `ctx.dispose`, which is the class-C -> class-B breach § 4.5 assertion
# 3 measured, closed. Copying it here would be copying a file this repository
# does not ship.
WHEEL_CLOSURE = (
    "wheel.js", "wheel-model.js", "helpers.js",
    "intent-binding.js", "notebook.js", "settings.js",
    # § 3.4 slice S7: the wheel and its model read the registered domain's
    # vocabulary through `display.js`, which is import-free by design -- the
    # closure gains a leaf, not a branch.
    "display.js",
)

# A minimal FAKE intent-feed.js — standing in for openxFactory's real
# contributed module, which this leg never carries. Its only job is to prove
# intent-binding.js forwards to whatever IS contributed; it is not a claim
# about the real module's own behaviour, which lives at openxFactory.
_FAKE_INTENT_FEED = """\
export function intentCapable(caps) {
  return !!(caps && caps.actions && caps.actions.intent);
}
export function feedActor(caps) {
  return "fake-actor:" + ((caps && caps.marker) || "no-marker");
}
export function refusalLine(rec) { return "fake-refusal:" + rec.state; }
export function startIntentFeed(opts) {
  return { subscribe() {}, stop() {}, marker: (opts && opts.marker) || "no-marker" };
}
export function statesByTarget(rows) {
  return new Map((rows || []).map((r) => [r.id, "fake:" + r.id]));
}
export function renderIntentChips(container, targetId, rows, error) {
  container.__fakeRendered = { targetId, rows, error };
  return container;
}
export async function emitIntent(opts) {
  return { state: "pending", message: "fake-queued:" + opts.verb };
}
"""

_DOM_SHIM = r"""
class Node {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.attributes = {}; this.listeners = {};
    this.className = ''; this._text = ''; this.disabled = false;
    this.value = ''; this.hidden = false; this.type = ''; this.title = '';
    this.dataset = {};
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }
  set textContent(value) { this.children = []; this._text = String(value); }
  set innerHTML(value) {
    if (String(value) !== '') throw new Error('only literal "" clears are allowed');
    this.children = []; this._text = '';
  }
  appendChild(child) { child.parent = this; this.children.push(child); return child; }
  append(...kids) { for (const k of kids) this.appendChild(k); }
  remove() {
    if (!this.parent) return;
    const at = this.parent.children.indexOf(this);
    if (at >= 0) this.parent.children.splice(at, 1);
  }
  classList = { add: () => {}, remove: () => {}, toggle: () => {} };
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  focus() {}
  walk() {
    return this.children.reduce((all, c) => all.concat(c.walk()), [this]);
  }
}
globalThis.document = {
  createElement: (tag) => new Node(tag),
  createTextNode: (text) => { const n = new Node('#text'); n._text = String(text);
    return n; },
  body: new Node('body'),
};
globalThis.window = { prompt: () => { throw new Error('unused on this probe'); } };
function byClass(root, cls) {
  return root.walk().filter((n) => String(n.className).split(' ').includes(cls));
}
"""


def _write_tree(tmp_path, *, contribute_intent_feed: bool):
    """A tmp copy of the real views, with or without a contributed
    intent-feed.js — the two deployment shapes RULED Q5 distinguishes."""
    views = tmp_path / "views"
    views.mkdir()
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    for name in WHEEL_CLOSURE:
        shutil.copy(WEB / "views" / name, views / name)
    if contribute_intent_feed:
        (views / "intent-feed.js").write_text(_FAKE_INTENT_FEED, encoding="utf-8")
    return views


def _run(tmp_path, script: str, *, contribute_intent_feed: bool):
    if NODE is None:
        pytest.skip("node not available for the intent-binding DOM probe")
    views = _write_tree(tmp_path, contribute_intent_feed=contribute_intent_feed)
    harness = views / "probe.mjs"
    harness.write_text(script, encoding="utf-8")
    proc = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, f"node harness failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# ---- the module graph itself (the note's § 1.2(b) defect) ------------------

# `import * as D from "./dispose.js"` WAS THE SECOND HALF OF THIS PROBE, and it
# went with the module at slice S5. The graph statement it made — that BOTH
# halves load in one tree — can only be made where both halves exist, which is
# the COMPOSED bundle, so it is made at openXdox-code
# (`tests/test_gate_loop_probes.py`,
# `test_js_the_composed_graph_resolves_with_or_without_a_contributed_feed`)
# against openDox's own `web/` with this column's modules assembled into it.
# What stays here is the half this bundle can still answer, and it is the half
# the note's § 1.2(b) defect was actually about: `wheel.js`'s OWN closure loads
# and evaluates with the never-carved `intent-feed.js` absent.
_GRAPH_PROBE = """
import * as W from "./wheel.js";
console.log(JSON.stringify({
  renderWheel: typeof W.renderWheel,
}));
"""


def test_wheel_module_graph_resolves_with_intent_feed_absent(tmp_path):
    """`app.js` -> `wheel.js` -> (formerly) the absent `intent-feed.js` used
    to fail the WHOLE static module graph at this leg (note § 1.2(b)): a
    dangling `import … from` on an ABSENT file is a load-time failure, not a
    missing render. This is that failure, gone: the entire closure loads and
    evaluates with intent-feed.js absent, exactly as this leg ships today."""
    r = _run(tmp_path, _GRAPH_PROBE, contribute_intent_feed=False)
    assert r == {"renderWheel": "function"}


def test_wheel_module_graph_also_resolves_with_intent_feed_contributed(tmp_path):
    """The forward path: a deployment that DOES drop intent-feed.js beside
    the others (openxFactory's composed column) still loads cleanly."""
    r = _run(tmp_path, _GRAPH_PROBE, contribute_intent_feed=True)
    assert r == {"renderWheel": "function"}


# ---- dispose.js's TRAY MOVED WITH dispose.js (slice S5) ---------------------
#
# TWO PROBES STOOD HERE: the tray rendering its three verdict buttons and NO
# chips element when no intent feed is contributed, and the same tray rendering
# chips that the CONTRIBUTED module actually wrote when one is. Both mounted the
# real `views/dispose.js`, and that module is openXdox-code's package data as of
# this slice (RULED Q5, openxFactory#656 comment `5648044785`). A probe that
# imported it from `src/opendox/web/views/` would be asserting against a file
# this bundle no longer ships.
#
# THEY WERE PORTED, NOT DELETED, on the precedent slice S4's five node probes
# set one slice ago: deleting behavioural coverage in a refactor slice is how a
# move that passes every shape assertion silently breaks a verb. They run at
# openXdox-code, in `tests/test_gate_loop_probes.py`, with slice S2's own DOM
# shim carried across unchanged and against an ASSEMBLED bundle — openDox's
# `web/` with that column's modules placed into it by RULED Q5's assembly hook —
# so the byte measured is the shipped byte in the shipped position.
#
# ONE FACT MOVED WITH THEM, RULED counterpart Q6 (`#656` comment `5649094228`):
# the tray reached `renderIntentChips` by importing this bundle's
# `intent-binding.js`, and a contributed module may now import
# `./views/helpers.js` and nothing else — so the chip renderer travels in
# `opts.intent` beside the emitter, supplied by the shell that starts the feed
# (`views/wheel.js`'s mount in this leg).
#
# What stays below is everything about `views/intent-binding.js`, which is this
# bundle's own file and the seam slice S2 actually added.


# ---- intentCapable's AND semantics ------------------------------------------

_CAPABLE_PROBE = _DOM_SHIM + """
import { intentCapable } from "./intent-binding.js";
console.log(JSON.stringify({
  capsTrue: intentCapable({ actions: { intent: true } }),
  capsFalse: intentCapable({ actions: { intent: false } }),
  capsMissing: intentCapable({}),
}));
"""


def test_intent_capable_is_false_whenever_the_binding_is_absent(tmp_path):
    """However `caps` reads, an absent binding is never capable — the
    backend and the front-end binding must both be present."""
    r = _run(tmp_path, _CAPABLE_PROBE, contribute_intent_feed=False)
    assert r == {"capsTrue": False, "capsFalse": False, "capsMissing": False}


def test_intent_capable_follows_caps_once_the_binding_is_contributed(tmp_path):
    r = _run(tmp_path, _CAPABLE_PROBE, contribute_intent_feed=True)
    assert r == {"capsTrue": True, "capsFalse": False, "capsMissing": False}


# ---- the other five forwards -----------------------------------------------
#
# PR REVIEW FIX (opensoft/openDox-code#15, Copilot): the two probes above only
# ever exercise `intentCapable` and `renderIntentChips` (the tray render tests
# call it indirectly through `mountDisposeTray`) — a wrapper could forward
# either of those correctly while getting `feedActor`, `refusalLine`,
# `startIntentFeed`, `statesByTarget` or `emitIntent` wrong (an argument
# dropped, the wrong fallback value) and every existing test here would still
# pass. This probe calls all five directly, both absent and contributed, so
# each one's OWN forward (or safe fallback) is what the assertion checks —
# not merely that the tray happens to still render. `statesByTarget`'s fake
# is made to depend on `rows` (`"fake:" + r.id`, not an unconditional empty
# Map) specifically so the contributed case is distinguishable from the
# absent one's own empty-Map fallback; an unconditional empty Map on both
# sides would let this probe pass without proving the forward happened at
# all.

_FORWARDS_PROBE = _DOM_SHIM + """
import {
  feedActor, refusalLine, startIntentFeed, statesByTarget, emitIntent,
} from "./intent-binding.js";

const rec = { state: "accepted" };
const rows = [{ id: "t1" }, { id: "t2" }];
const caps = { actions: { intent: true }, marker: "caps-m1" };
const opts = { some: "opts", marker: "opts-m2" };
const started = startIntentFeed(opts);
const emitted = await emitIntent({ verb: "propose" });
console.log(JSON.stringify({
  feedActor: feedActor(caps),
  refusalLine: refusalLine(rec),
  startedIsNull: started === null,
  startedHasSubscribe: !!(started && typeof started.subscribe === "function"),
  startedMarker: started ? started.marker : null,
  states: Array.from(statesByTarget(rows).entries()),
  emitted,
}));
"""


def test_the_remaining_forwards_answer_safely_when_intent_feed_is_absent(tmp_path):
    """Every one of the five, absent a contributed module: `feedActor` and
    `startIntentFeed` null, `refusalLine` empty, `statesByTarget` an empty
    Map, `emitIntent` an honestly-refusing error record — never a thrown
    exception, the same "no chips, no thrown error" contract the tray probes
    above already prove for `intentCapable`/`renderIntentChips`."""
    r = _run(tmp_path, _FORWARDS_PROBE, contribute_intent_feed=False)
    assert r["feedActor"] is None
    assert r["refusalLine"] == ""
    assert r["startedIsNull"] is True
    assert r["states"] == []
    assert r["emitted"] == {
        "state": "error",
        "message": "the intent-feed binding is not contributed in this deployment",
    }


def test_the_remaining_forwards_reach_the_contributed_module(tmp_path):
    """The same five, with the fake `intent-feed.js` contributed: each
    answer comes from the FAKE module, not from intent-binding.js's own
    fallback — `states` in particular is keyed from `rows`, which only the
    contributed `statesByTarget` (not the absent-case empty Map) can produce.

    PR REVIEW FIX (opensoft/openDox-code#15, Copilot): the fakes for
    `feedActor` and `startIntentFeed` also carry their OWN caller-supplied
    marker (`caps.marker` / `opts.marker`) into their answer, so this
    assertion fails if intent-binding.js ever forwarded either call with the
    wrong argument, or none at all — the earlier constant-valued fakes could
    not have caught a dropped or substituted `caps`/`opts` no matter what
    intent-binding.js actually passed through."""
    r = _run(tmp_path, _FORWARDS_PROBE, contribute_intent_feed=True)
    assert r["feedActor"] == "fake-actor:caps-m1"
    assert r["refusalLine"] == "fake-refusal:accepted"
    assert r["startedIsNull"] is False
    assert r["startedHasSubscribe"] is True
    assert r["startedMarker"] == "opts-m2"
    assert r["states"] == [["t1", "fake:t1"], ["t2", "fake:t2"]]
    assert r["emitted"] == {"state": "pending", "message": "fake-queued:propose"}
