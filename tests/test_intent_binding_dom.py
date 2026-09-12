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
# settings.js are import-free leaves; dispose.js imports only helpers.js and
# (after this slice) intent-binding.js. A file added to this set by a future
# slice without updating this constant fails loudly (`_write_tree` copies
# exactly this list, so a newly-added import the closure omits is a
# `MODULE_NOT_FOUND` in the harness, not a silent gap).
WHEEL_CLOSURE = (
    "wheel.js", "wheel-model.js", "helpers.js", "dispose.js",
    "intent-binding.js", "notebook.js", "settings.js",
)

# A minimal FAKE intent-feed.js — standing in for openxFactory's real
# contributed module, which this leg never carries. Its only job is to prove
# intent-binding.js forwards to whatever IS contributed; it is not a claim
# about the real module's own behaviour, which lives at openxFactory.
_FAKE_INTENT_FEED = """\
export function intentCapable(caps) {
  return !!(caps && caps.actions && caps.actions.intent);
}
export function feedActor() { return "fake-actor"; }
export function refusalLine(rec) { return "fake-refusal:" + rec.state; }
export function startIntentFeed() { return { subscribe() {}, stop() {} }; }
export function statesByTarget() { return new Map(); }
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

_GRAPH_PROBE = """
import * as W from "./wheel.js";
import * as D from "./dispose.js";
console.log(JSON.stringify({
  renderWheel: typeof W.renderWheel,
  mountDisposeTray: typeof D.mountDisposeTray,
}));
"""


def test_wheel_module_graph_resolves_with_intent_feed_absent(tmp_path):
    """`app.js` -> `wheel.js` -> (formerly) the absent `intent-feed.js` used
    to fail the WHOLE static module graph at this leg (note § 1.2(b)): a
    dangling `import … from` on an ABSENT file is a load-time failure, not a
    missing render. This is that failure, gone: the entire closure loads and
    evaluates with intent-feed.js absent, exactly as this leg ships today."""
    r = _run(tmp_path, _GRAPH_PROBE, contribute_intent_feed=False)
    assert r == {"renderWheel": "function", "mountDisposeTray": "function"}


def test_wheel_module_graph_also_resolves_with_intent_feed_contributed(tmp_path):
    """The forward path: a deployment that DOES drop intent-feed.js beside
    the others (openxFactory's composed column) still loads cleanly."""
    r = _run(tmp_path, _GRAPH_PROBE, contribute_intent_feed=True)
    assert r == {"renderWheel": "function", "mountDisposeTray": "function"}


# ---- dispose.js's tray, gated the way wheel.js actually gates it -----------
#
# `mountDisposeTray` itself does not consult `intentCapable` — it trusts its
# caller (`wheel.js`) to pass `opts.intent` only once `intentCapable(caps)`
# has already said yes (`wheel.js`'s own `hosted` local). So the realistic
# probe reproduces THAT gate rather than handing `opts.intent` to the tray
# unconditionally, which would prove nothing about the binding.

_TRAY_PROBE = _DOM_SHIM + """
import { mountDisposeTray } from "./dispose.js";
import { intentCapable } from "./intent-binding.js";

const caps = { actions: { intent: true } };
const hosted = intentCapable(caps);
const row = new Node("div");
mountDisposeTray(row, { id: "p1" },
  hosted ? { intent: { snapshotRev: "r", rows: [], error: null } } : {});
const tray = byClass(row, "disposetray")[0];
const chips = row.walk().find((n) => String(n.className).includes("intentchips"));
console.log(JSON.stringify({
  hosted,
  verdictButtons: tray ? tray.children.length : -1,
  chipsMounted: !!chips,
  chipsCarryRealForward: !!(chips && chips.__fakeRendered),
}));
"""


def test_dispose_tray_renders_with_no_chips_when_intent_feed_absent(tmp_path):
    r = _run(tmp_path, _TRAY_PROBE, contribute_intent_feed=False)
    assert r["hosted"] is False
    assert r["verdictButtons"] == 3          # accept / reject / defer, unchanged
    assert r["chipsMounted"] is False        # no chips element at all — not
                                              # merely an empty one: wheel.js
                                              # never passed opts.intent
    assert r["chipsCarryRealForward"] is False


def test_dispose_tray_renders_real_chips_when_intent_feed_contributed(tmp_path):
    r = _run(tmp_path, _TRAY_PROBE, contribute_intent_feed=True)
    assert r["hosted"] is True
    assert r["verdictButtons"] == 3
    assert r["chipsMounted"] is True
    assert r["chipsCarryRealForward"] is True   # not just present — actually
                                                 # rendered BY the contributed
                                                 # module, not a same-named
                                                 # look-alike


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
