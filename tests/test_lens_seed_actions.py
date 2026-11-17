"""THE LENS'S TWO SEED ACTIONS ARE OFFERED ONLY WHERE A BINDING ANSWERS THEM.

Plan 034 T088 (slice P3-L). RULED R1Q19 (a), Brett Heap, openxFactory#656
comment `5850003126`: *"The two seed actions are offered only where a binding
answers them. A standalone install offers neither, and `lens.js` stays the
census's `?` row."* Moving the two controls into a view extension that
openxFactory contributes is (b): later, and outside release 1.

WHAT "A BINDING ANSWERS IT" MEANS, and where it is read from. `/capabilities`
already carries `views.contributed_routes`: the routes a host contributed.
`serve.build_server()` builds that list from the very `route_bindings` table its
POST dispatch consults, so a route in the list is a route the server will
dispatch, and a route not in it is one the server will not. The lens reads its
answer from the payload it has already fetched. There is no second fetch and no
new server field, so nothing here can drift from the dispatcher (the last case
in this file holds that).

WHAT IT GATES. Two controls, and everything that exists only to feed them:

  * `draft seed`, the drill row's register seed, posts to the DTN route;
  * `draft staging seed`, the pick bar's button, posts to the staging route.
    The matrix's checkbox column, the clickable dots and the pick bar itself
    exist "to feed ONE action" (`test_bullseye_widget.py::
    test_the_matrix_selection_is_the_seeds_only_input`), so they are offered
    with it and go with it. A standalone lens that kept "tick documents to
    draft from them" would be telling a reader to use a control it does not
    have.

THE FALSIFIER, AT-R1 step 6: *"`#tab-lens` renders the bullseye with the corpus's
documents as dots, and not the text 'nothing on the radar'. Neither of its two
openxFactory seed actions is offered, since no binding answers them."* The full
step runs in a browser (T096). This file drives the REAL `views/lens.js` under
node with the payload a standalone serve publishes and reads the page it
produces, and asserts the same things: the documents are dots, the empty-radar
text is absent, and neither seed action is offered. Each case then asserts the
other half, so that "never offer them" cannot pass: a host that contributes the
routes gets the controls.

FAIL CLOSED. A payload the lens cannot read, a probe that failed, a static image
whose `/capabilities` 404s, and a manifest that is malformed all read as "no
binding answers it". That is `view_extension.js`'s own posture for `requires`
("a missing payload is an unmet requirement, not an error").

`--noconftest` SAFE. Drives node the way `test_display_facet.py` does (SKIPPED,
never failed, where node is absent).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

import route_extension
from opendox import view_extension

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
VIEWS = WEB / "views"
SERVE = ROOT / "src" / "opendox" / "serve.py"
PLAIN_DOCUMENTS = ROOT / "tests" / "fixtures" / "plain-documents"
NODE = shutil.which("node")

DTN_SEED_ROUTE = "/actions/dtn-seed"
STAGING_SEED_ROUTE = "/actions/staging-seed"

RouteBinding = route_extension.RouteBinding

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


# ---------------------------------------------------------------------------
# The payload, built the way the server builds it.
# ---------------------------------------------------------------------------

class _HostRoutes:
    """A host's route extension: the shape openxFactory's lanes module has."""

    def __init__(self, *bindings: RouteBinding) -> None:
        self._bindings = bindings

    def routes(self) -> tuple[RouteBinding, ...]:
        return self._bindings


def _payload(*bindings: RouteBinding, gate: bool = True) -> dict:
    """The `/capabilities` payload a serve publishes, with `bindings` contributed.

    `serve.build_server()` collects the contributed routes, hands the same
    collection to `view_manifest()`, and publishes the result under `views`
    beside the probe's `actions`. This does the same three things, with the
    real functions, so a change to how the manifest carries routes reaches
    these cases and not only the server. (The case that reads a REAL serve's
    payload is `test_the_lens_of_a_real_standalone_serve_...`, below.)

    `gate` is the probe's gate verdict, which the lens does not read for its seed
    actions. A local serve of a checkout with a resolved actor says it true. A
    standalone serve says it false once T084 (batch L) turns `actions.gate` off
    where no gate route answers, and so does a read-only project view (D10). The
    cases below run both ways so that neither verdict decides the answer.
    """
    routes = route_extension.collect_bindings(
        (_HostRoutes(*bindings),) if bindings else ())
    payload = {
        # the shape `compute_capabilities()` returns. Not CALLED: it reads the
        # snapshot registry seam, which a bare process has not registered, and
        # these cases are about the `views` block beside it.
        "actions": {"notebook": False, "gate": gate, "refresh": False,
                    "session": gate, "edit": gate, "intent": False},
        "actor": "Ada" if gate else None,
        "refresh": {"binding": None, "loopback_only": True},
    }
    payload["views"] = view_extension.view_manifest(
        view_extension.collect_view_bindings((), contributed_routes=routes),
        contributed_routes=routes, host_facet="absent", host_profile=None)
    return payload


def _dtn() -> RouteBinding:
    return RouteBinding("POST", DTN_SEED_ROUTE, False, "_handle_dtn_seed")


def _staging() -> RouteBinding:
    return RouteBinding("POST", STAGING_SEED_ROUTE, False, "_handle_staging_seed")


#: A plain repository's snapshot: three documents, and a topic two of them share,
#: so that with `alpha` checked the radar has dots to draw.
_KEYWORD_SNAPSHOT = {
    "documents": [
        {"id": "a.md", "path": "a.md", "topics": ["alpha", "beta"], "summary": "s"},
        {"id": "b.md", "path": "b.md", "topics": ["alpha"], "summary": "t"},
        {"id": "c.md", "path": "c.md", "topics": ["gamma"], "summary": "u"},
    ],
    "keyword_index": [
        {"keyword": "alpha", "documents": ["a.md", "b.md"]},
        {"keyword": "beta", "documents": ["a.md"]},
        {"keyword": "gamma", "documents": ["c.md"]},
    ],
    "clusters": [], "possibles": [], "staged_topics": [], "changes": [],
}

#: A project view over two repositories that carry one document identity in
#: common, which is the only shape the register seed is offered on (a set two or
#: more repositories share).
_COMPOSED_SNAPSHOT = {
    "repository": "project-x",
    "generation": {"composed_from": [
        {"repository": "repo-a", "ref": "main"},
        {"repository": "repo-b", "ref": "main"},
    ]},
    "documents": [
        {"id": "repo-a::shared.md", "path": "shared.md", "repository": "repo-a",
         "summary": "s"},
        {"id": "repo-b::shared.md", "path": "shared.md", "repository": "repo-b",
         "summary": "s"},
        {"id": "repo-a::only-a.md", "path": "only-a.md", "repository": "repo-a",
         "summary": "t"},
    ],
    "keyword_index": [], "clusters": [], "possibles": [],
    "staged_topics": [], "changes": [],
}


# ---------------------------------------------------------------------------
# The node harness: a DOM just large enough for `views/lens.js`.
# ---------------------------------------------------------------------------

_DOM = r"""
class Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.className = ""; this._text = ""; this.type = ""; this.title = "";
    this.value = ""; this.checked = false; this.disabled = false;
    this.hidden = false; this.placeholder = ""; this.id = ""; this.dataset = {};
    this.style = { setProperty() {}, removeProperty() {}, getPropertyValue: () => "" };
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); this.children = []; }
  set innerHTML(v) { this._text = String(v); this.children = []; }
  get innerHTML() { return this._text; }
  get childElementCount() { return this.children.length; }
  get classList() {
    const self = this;
    return { add(...c) { self.className = (self.className + " " + c.join(" ")).trim(); },
             remove() {}, toggle() {},
             contains: (c) => String(self.className).split(" ").includes(c) };
  }
  appendChild(c) { this.children.push(c); return c; }
  append(...nodes) {
    for (const c of nodes) this.appendChild(
      typeof c === "string" ? globalThis.document.createTextNode(c) : c);
  }
  remove() {}
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  removeEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() {}
}
globalThis.document = {
  createElement: (tag) => new Node(tag),
  createTextNode: (text) => Object.assign(new Node("#text"), { _text: String(text) }),
  createElementNS: (_ns, tag) => new Node(tag),
  getElementById: () => null,
  addEventListener() {}, removeEventListener() {}, activeElement: null,
};
function flatten(node, out = []) {
  out.push(node);
  for (const c of node.children) flatten(c, out);
  return out;
}
"""

#: What one render is read as. Everything is read off the tree the view built,
#: never off its source: which controls exist, what the page says, how many
#: dots the radar drew.
_READ = r"""
const base = __VIEWS__ + "/";
const L = await import(base + "lens.js");
const C = await import(base + "composed-model.js");

// A seed control is found by what it SAYS, so that the absence check does not
// depend on a hook the code under test may not carry, and by the `data-seed-action`
// hook the browser half (T096) reads it by. The two must agree wherever one is.
const LABELS = { "draft seed": "dtn-seed", "draft staging seed": "staging-seed",
                 "re-draft": "staging-seed" };
function read(root) {
  const nodes = flatten(root);
  const words = [];
  for (const n of nodes) {
    for (const w of [n._text, n.title, n.attrs["aria-label"], n.placeholder]) {
      if (w) words.push(String(w));
    }
  }
  return {
    // the radar: one `lensdot` group per document it drew
    dots: nodes.filter((n) => n.attrs.class === "lensdot" && "data-doc" in n.attrs).length,
    seedControls: nodes.map((n) => n.dataset.seedAction
      ?? (n.tag === "button" ? LABELS[n._text] : undefined))
      .filter((kind) => kind !== undefined).sort(),
    hooked: nodes.filter((n) => n.dataset.seedAction !== undefined)
      .map((n) => n.dataset.seedAction).sort(),
    // the selection that exists only to feed the staging seed
    pickBars: nodes.filter((n) => n.className === "pickbar").length,
    pickBoxes: nodes.filter((n) => n.tag === "input" && n.type === "checkbox"
      && /^select /.test(n.attrs["aria-label"] || "")).length,
    clickableDots: nodes.filter((n) => n.attrs.class === "lensdot"
      && (n.listeners.click || []).length > 0).length,
    pickColumns: nodes.filter((n) => n.className === "pickcol").length,
    emptyRadar: words.some((w) => /nothing on the radar/i.test(w)),
    seedWords: words.filter((w) => /seed/i.test(w)),
    hasDrillPane: nodes.some((n) => n.className === "pane pane-drill"),
  };
}

function renderKeywords(payload, snapshot, checked) {
  const root = new Node("div");
  L.renderLens(root, snapshot, { caps: payload, checked });
  return read(root);
}

function render(payload, vocabulary) {
  const root = new Node("div");
  if (vocabulary === "repositories") {
    // exactly what app.js hands the lens on a project view: the D10 read-only
    // projection of the probe as `caps`
    L.renderLens(root, __COMPOSED__, {
      caps: C.readOnlyCaps(payload), composedSnapshot: __COMPOSED__,
      vocabulary: "repositories",
    });
  } else {
    L.renderLens(root, __KEYWORD__, { caps: payload, checked: ["alpha"] });
  }
  return read(root);
}
"""


def _run(body: str, tmp_path: Path) -> Any:
    prelude = (_DOM + _READ
               .replace("__VIEWS__", json.dumps(str(VIEWS)))
               .replace("__COMPOSED__", json.dumps(_COMPOSED_SNAPSHOT))
               .replace("__KEYWORD__", json.dumps(_KEYWORD_SNAPSHOT)))
    script = tmp_path / "harness.mjs"
    script.write_text(prelude + body, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# AT-R1 step 6, and the other half of it.
# ---------------------------------------------------------------------------

def _assert_standalone_page(label, page):
    """What AT-R1 step 6 asks of the lens a standalone serve renders."""
    assert page["dots"] > 0, (label, "the radar drew no document")
    assert not page["emptyRadar"], (label, "the radar reads as empty")
    assert page["seedControls"] == [], (
        label, "a seed action is offered where no binding answers it")
    # nothing that exists only to feed a seed survives it: no pick bar, no
    # checkbox column, no clickable dot, and no sentence sending the reader to a
    # control that is not there
    assert page["pickBars"] == 0, label
    assert page["pickBoxes"] == 0, label
    assert page["clickableDots"] == 0, label
    assert page["pickColumns"] == 0, label
    assert page["seedWords"] == [], (label, page["seedWords"])


@needs_node
@pytest.mark.parametrize("gate", [True, False], ids=["gate-on", "gate-off"])
def test_a_standalone_lens_draws_its_radar_and_offers_neither_seed_action(
        tmp_path, gate):
    """AT-R1 step 6, driven through the real `views/lens.js`.

    The payload is the one a standalone serve publishes: no host has registered,
    so no route is contributed. Both vocabularies are read, because the two
    controls live in different ones (the register seed only on a project view,
    the staging seed on either). On each, the radar has its dots, the empty-radar
    text is absent, and no seed control is offered, nor anything that exists only
    to feed one.

    BOTH GATE VERDICTS. The lens reads which routes a binding answers, not
    `actions.gate`: T084 (batch L) turns `actions.gate` off on a standalone serve
    where no gate route answers, and the answer here must not move with it.
    """
    standalone = _payload(gate=gate)
    assert standalone["views"]["contributed_routes"] == [], (
        "the premise of the case: a serve with no host contributes no route")
    out = _run(f"""
const payload = {json.dumps(standalone)};
console.log(JSON.stringify({{
  keywords: render(payload, "keywords"),
  repositories: render(payload, "repositories"),
}}));
""", tmp_path)
    for vocabulary, page in out.items():
        _assert_standalone_page(vocabulary, page)
    # the project view is the one whose drill rows would carry the register seed
    assert out["repositories"]["hasDrillPane"] is True


_STANDALONE_SERVE = r"""
import http.client, json, sys, threading
from pathlib import Path
from opendox import cli, serve

repo, out, web, dump = (Path(a) for a in sys.argv[1:5])
assert cli.main(["generate", "--repo-root", str(repo), "--repository", "garden",
                 "--output", str(out)]) == 0
httpd = serve.build_server(web, out, repo, port=0)
worker = threading.Thread(target=httpd.serve_forever, daemon=True)
worker.start()
host, port = httpd.server_address[:2]


def get(path):
    connection = http.client.HTTPConnection(host, port, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    assert response.status == 200, (path, response.status)
    return json.loads(response.read())


dump.write_text(json.dumps({"capabilities": get("/capabilities"),
                            "snapshot": get("/snapshot.json")}), encoding="utf-8")
httpd.shutdown()
httpd.server_close()
"""


def _standalone_serve(tmp_path: Path, *, actor: bool) -> dict:
    """Serve a plain git repository with NOTHING registered and read it over HTTP.

    A fresh process, so no registration made by another case is inherited, and
    no git identity but the repository's own: with one configured the serve
    resolves an actor and says `actions.gate` true, with none it says false.
    Both are the standalone serve's real answers today.
    """
    repo = tmp_path / "repository"
    shutil.copytree(PLAIN_DOCUMENTS, repo)
    # Neither GIT_* nor XF_*: the suite itself exports a gate roster and a human
    # console flag (XF_GATE_PRINCIPALS, XF_HUMAN_CONSOLE), and a roster of several
    # names with no claim is ambiguous, which would resolve no actor whatever the
    # repository's own identity says. The standalone serve's only identity here
    # is the one the repository carries.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "XF_"))}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "src"), *filter(None, [os.environ.get("PYTHONPATH")])]),
    })

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, env=env)

    git("-c", "init.defaultBranch=main", "init", "-q")
    if actor:
        git("config", "user.name", "Ada Lovelace")
        git("config", "user.email", "ada@example.invalid")
    git("add", "-A")
    git("commit", "-q", "-m", "fixture")
    dump = tmp_path / "served.json"
    proc = subprocess.run(
        [sys.executable, "-c", _STANDALONE_SERVE, str(repo),
         str(tmp_path / "run" / "snapshot.json"), str(WEB), str(dump)],
        capture_output=True, text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(dump.read_text(encoding="utf-8"))


@needs_node
@pytest.mark.parametrize("actor", [True, False], ids=["actor", "no-actor"])
def test_the_lens_of_a_real_standalone_serve_offers_neither_seed_action(
        tmp_path, actor):
    """AT-R1 step 6 on the real thing: a served plain repository, over HTTP.

    The `plain-documents` fixture (AT-R1 step 3 (a)) is generated and served by
    a fresh process with nothing registered, and its `/capabilities` and
    `/snapshot.json` are what the lens is handed. The radar draws that
    repository's own documents as dots, and no seed action is offered. The same
    run with and without a git identity covers both of `actions.gate`'s answers,
    because the serve itself gives each.
    """
    served = _standalone_serve(tmp_path, actor=actor)
    capabilities, snapshot = served["capabilities"], served["snapshot"]
    assert capabilities["views"]["contributed_routes"] == [
        {"method": "POST", "pattern": "/actions/session/submit",
         "is_prefix": False},
        {"method": "POST", "pattern": "/actions/session/land-nonce",
         "is_prefix": False},
        {"method": "POST", "pattern": "/actions/session/land",
         "is_prefix": False}], (
        "a serve with no host contributes only openDox's own submit route "
        "(plan 038 T015) and its two land routes (T016), and no seed route")
    # SINCE T084 (plan 034; RULED openxFactory#656 `5920216845`, item 1) the
    # gate flag is true only where a contributed binding answers a gate verb,
    # and a serve with no host contributes none. So it reads false in both
    # runs, and the identity is asserted where it lands, on the resolved
    # actor.
    assert capabilities["actions"]["gate"] is False, (
        "a serve with no gate route offers no gate action")
    assert (capabilities["actor"] is not None) is actor, (
        "the serve's actor follows the identity it can resolve")
    # the keyword the most documents declare, so the radar has dots to draw
    carriers = Counter(topic for doc in snapshot["documents"]
                       for topic in doc.get("topics", []))
    keyword, carried = carriers.most_common(1)[0]
    assert carried >= 2, "the fixture must give the radar something to draw"
    out = _run(f"""
const payload = {json.dumps(capabilities)};
const snapshot = {json.dumps(snapshot)};
console.log(JSON.stringify(renderKeywords(payload, snapshot, [{json.dumps(keyword)}])));
""", tmp_path)
    _assert_standalone_page("real serve", out)
    assert out["dots"] == carried, (
        "one dot per document that declares the checked keyword")


@needs_node
@pytest.mark.parametrize("gate", [True, False], ids=["gate-on", "gate-off"])
def test_the_same_lens_offers_both_where_a_host_contributes_both_routes(
        tmp_path, gate):
    """The other half, so that "never offer them" cannot pass this file.

    A host that contributes the two lane routes, as openxFactory does, gets the
    register seed on a set two repositories share, the staging seed, and the
    selection that feeds it. Whatever the gate verdict: the seeds write nothing,
    and a read-only project view, which has no gate, offers them (D10).
    """
    bound = _payload(_dtn(), _staging(), gate=gate)
    out = _run(f"""
const payload = {json.dumps(bound)};
console.log(JSON.stringify({{
  keywords: render(payload, "keywords"),
  repositories: render(payload, "repositories"),
}}));
""", tmp_path)
    keywords, repositories = out["keywords"], out["repositories"]
    # a plain repository has no project view, so only the staging seed
    assert keywords["seedControls"] == ["staging-seed"]
    assert keywords["hooked"] == keywords["seedControls"]
    assert keywords["pickBars"] == 1
    assert keywords["pickBoxes"] > 0 and keywords["clickableDots"] > 0
    # the project view carries both, and the register seed only on the row two
    # repositories share (the centre), never on a single-carrier row
    assert repositories["seedControls"] == ["dtn-seed", "staging-seed"]
    assert repositories["hooked"] == repositories["seedControls"]
    assert repositories["pickBars"] == 1 and repositories["pickBoxes"] > 0
    for page in out.values():
        assert page["dots"] > 0 and not page["emptyRadar"]


@needs_node
@pytest.mark.parametrize("contributed, dtn, staging", [
    ((_dtn,), True, False),
    ((_staging,), False, True),
])
def test_each_seed_action_is_offered_on_its_own_route_alone(
        tmp_path, contributed, dtn, staging):
    """The two are independent: a host that answers one does not offer the other.

    Offering the staging seed because the register seed is answered would put a
    button on the page whose POST the server refuses with a 404.
    """
    payload = _payload(*(make() for make in contributed))
    out = _run(f"""
const payload = {json.dumps(payload)};
console.log(JSON.stringify(render(payload, "repositories")));
""", tmp_path)
    assert ("dtn-seed" in out["seedControls"]) is dtn
    assert ("staging-seed" in out["seedControls"]) is staging
    assert (out["pickBars"] == 1) is staging
    assert (out["pickBoxes"] > 0) is staging
    assert (out["clickableDots"] > 0) is staging


# ---------------------------------------------------------------------------
# The answer, asked directly: `bindingAnswers(capabilities, method, path)`.
# ---------------------------------------------------------------------------

def _answers(cases: list[tuple], tmp_path: Path) -> list[bool]:
    """`bindingAnswers` over `(capabilities, method, path)` triples."""
    out = _run(f"""
const cases = {json.dumps(cases)};
console.log(JSON.stringify(cases.map(([caps, method, path]) =>
  L.bindingAnswers(caps, method, path))));
""", tmp_path)
    return out


def _routes(*routes) -> dict:
    return {"views": {"contributed_routes": list(routes)}}


def _route(method, pattern, is_prefix=False):
    return {"method": method, "pattern": pattern, "is_prefix": is_prefix}


@needs_node
def test_a_payload_that_cannot_say_a_binding_answers_reads_as_none_answering(tmp_path):
    """FAIL CLOSED, on every shape a payload can fail to be.

    Each of these is a page that must not offer a control whose POST the server
    may not dispatch: no payload, the probe's own fallback when `/capabilities`
    fails or 404s (a static image), a payload with no `views`, and a manifest
    that is malformed in each way `manifestRoutes()` refuses it.
    """
    good = _route("POST", DTN_SEED_ROUTE)
    cases = [
        (None, "POST", DTN_SEED_ROUTE),
        ({}, "POST", DTN_SEED_ROUTE),
        ({"actions": {"notebook": False}}, "POST", DTN_SEED_ROUTE),
        ({"views": None}, "POST", DTN_SEED_ROUTE),
        ({"views": {}}, "POST", DTN_SEED_ROUTE),
        ({"views": {"contributed_routes": None}}, "POST", DTN_SEED_ROUTE),
        ({"views": {"contributed_routes": {"0": good}}}, "POST", DTN_SEED_ROUTE),
        ({"views": {"contributed_routes": "POST /actions/dtn-seed"}}, "POST",
         DTN_SEED_ROUTE),
        # malformed entries: a null, a non-object, no pattern, no method, and
        # `is_prefix` that is not a boolean
        (_routes(None), "POST", DTN_SEED_ROUTE),
        (_routes("POST"), "POST", DTN_SEED_ROUTE),
        (_routes({"method": "POST", "is_prefix": False}), "POST", DTN_SEED_ROUTE),
        (_routes({"pattern": DTN_SEED_ROUTE, "is_prefix": False}), "POST",
         DTN_SEED_ROUTE),
        (_routes({"method": "POST", "pattern": DTN_SEED_ROUTE}), "POST",
         DTN_SEED_ROUTE),
        (_routes({"method": "POST", "pattern": DTN_SEED_ROUTE,
                  "is_prefix": "false"}), "POST", DTN_SEED_ROUTE),
        (_routes({"method": "POST", "pattern": 7, "is_prefix": False}), "POST",
         DTN_SEED_ROUTE),
        # ONE bad entry beside a good one poisons the whole list (Copilot, #65):
        # a manifest this cannot vouch for is not taken on trust route by route,
        # as `manifestRoutes()` refuses the whole payload for one bad entry
        (_routes(good, None), "POST", DTN_SEED_ROUTE),
        (_routes(None, good), "POST", DTN_SEED_ROUTE),
        (_routes(good, {"method": "POST", "pattern": "", "is_prefix": True}),
         "POST", DTN_SEED_ROUTE),
        (_routes(good, {"method": "POST", "pattern": "/x"}), "POST",
         DTN_SEED_ROUTE),
        # and the controls: the same route, well formed, alone and with company
        (_routes(good), "POST", DTN_SEED_ROUTE),
        (_routes(_route("GET", "/a.json"), good), "POST", DTN_SEED_ROUTE),
    ]
    assert _answers(cases, tmp_path) == [False] * (len(cases) - 2) + [True] * 2


#: Candidate manifest entries, each as `(method, pattern, is_prefix)`, chosen to
#: sit on both sides of every clause of `RouteBinding.__post_init__`.
_CANDIDATE_ENTRIES = [
    ("POST", "/x", False), ("POST", "/x/", True), ("GET", "/", True),
    ("HEAD", "/h", False), ("GET", "/x/y.json", False),
    ("PUT", "/x", False), ("post", "/x", False), ("", "/x", False),
    ("POST", "x", False), ("POST", "", False), ("POST", "", True),
    ("POST", "/x?y", False), ("POST", "/x#y", False), ("POST", "/x/?y", True),
    ("POST", "/x", True), ("POST", "/x/y", True),
    ("POST", "/x", "false"), ("POST", "/x", 0), ("POST", "/x", None),
    ("POST", 7, False), ("POST", None, False),
]


def _the_server_accepts(method, pattern, is_prefix) -> bool:
    try:
        RouteBinding(method, pattern, is_prefix, "_h")
    except route_extension.RouteBindingError:
        return False
    return True


@needs_node
def test_a_manifest_entry_is_trusted_only_if_the_server_would_have_accepted_it(
        tmp_path):
    """The lens's notion of a well-formed route is `RouteBinding`'s own.

    A manifest is taken on trust whole or not at all, so what counts as a
    malformed entry decides when the controls disappear. That must not be a
    second opinion. For each candidate, a list holding it beside one good seed
    route answers yes exactly when `RouteBinding` accepts the candidate, and it
    says so for the shapes that reach the client as JSON and were never
    constructed: `is_prefix` as a string, a number or null, a pattern that is
    not text.
    """
    good = _route("POST", DTN_SEED_ROUTE)
    cases = [
        (_routes(good, {"method": m, "pattern": p, "is_prefix": ip}), "POST",
         DTN_SEED_ROUTE)
        for m, p, ip in _CANDIDATE_ENTRIES
    ]
    expected = [_the_server_accepts(*entry) for entry in _CANDIDATE_ENTRIES]
    assert any(expected) and not all(expected), (
        "the candidates must sit on both sides or they prove nothing")
    assert _answers(cases, tmp_path) == expected


@needs_node
def test_a_binding_answers_only_the_method_and_the_path_it_declared(tmp_path):
    """The route table's own rule, `RouteBinding.matches`: method AND path.

    A GET at the seed's path does not answer a POST (the lens POSTs), a near
    miss is no answer (`/actions/dtn-seed/` is not `/actions/dtn-seed`), and a
    prefix answers what sits under it and nothing beside it.
    """
    cases = [
        (_routes(_route("GET", DTN_SEED_ROUTE)), "POST", DTN_SEED_ROUTE),
        (_routes(_route("POST", DTN_SEED_ROUTE)), "POST", DTN_SEED_ROUTE + "/"),
        (_routes(_route("POST", DTN_SEED_ROUTE)), "POST", DTN_SEED_ROUTE + "s"),
        (_routes(_route("POST", STAGING_SEED_ROUTE)), "POST", DTN_SEED_ROUTE),
        (_routes(_route("POST", "/actions/", True)), "POST", "/action"),
        (_routes(_route("POST", "/other/", True)), "POST", DTN_SEED_ROUTE),
        (_routes(_route("GET", "/actions/", True)), "POST", DTN_SEED_ROUTE),
        # the answers: the exact route, one of several, and a covering prefix
        (_routes(_route("POST", DTN_SEED_ROUTE)), "POST", DTN_SEED_ROUTE),
        (_routes(_route("GET", "/a.json"), _route("POST", STAGING_SEED_ROUTE),
                 _route("POST", DTN_SEED_ROUTE)), "POST", DTN_SEED_ROUTE),
        (_routes(_route("POST", "/actions/", True)), "POST", DTN_SEED_ROUTE),
    ]
    assert _answers(cases, tmp_path) == [False] * 7 + [True] * 3


# ---------------------------------------------------------------------------
# One source of truth with the dispatcher.
# ---------------------------------------------------------------------------

@needs_node
def test_the_lens_answers_exactly_what_the_servers_dispatcher_answers(tmp_path):
    """`bindingAnswers` over the published manifest agrees with `match()`.

    `route_extension.match()` is the ONE rule the server's read and write arms
    both use. Its answer for a method and a path is whether the server will
    dispatch it. This asks the lens's mirror of that rule the same question over
    a manifest built from the same table, across every method the dispatcher
    knows, exact and prefix bindings, and paths that sit on, beside and under
    them. Any disagreement is a control offered where the server refuses, or
    withheld where it answers.
    """
    bindings = (
        _dtn(), _staging(),
        RouteBinding("GET", "/committed-intents.json", False, "_a"),
        RouteBinding("POST", "/actions/lane/", True, "_b"),
        RouteBinding("GET", "/lane/", True, "_c"),
        RouteBinding("HEAD", "/head-only", False, "_d"),
    )
    paths = [
        DTN_SEED_ROUTE, STAGING_SEED_ROUTE, DTN_SEED_ROUTE + "/",
        DTN_SEED_ROUTE + "s", "/committed-intents.json", "/actions/lane",
        "/actions/lane/", "/actions/lane/x", "/lane/", "/lane/x", "/lane",
        "/head-only", "/", "",
    ]
    methods = list(route_extension.METHODS)
    table = route_extension.collect_bindings((_HostRoutes(*bindings),))
    payload = _payload(*bindings)
    expected = {
        f"{m} {p}": route_extension.match(table, m, p) is not None
        for m in methods for p in paths
    }
    assert any(expected.values()) and not all(expected.values()), (
        "the probe matrix must contain both answers or it proves nothing")
    out = _run(f"""
const payload = {json.dumps(payload)};
const probes = {json.dumps(list(expected))};
const answers = {{}};
for (const probe of probes) {{
  const at = probe.indexOf(" ");
  answers[probe] = L.bindingAnswers(payload, probe.slice(0, at), probe.slice(at + 1));
}}
console.log(JSON.stringify(answers));
""", tmp_path)
    assert out == expected


def test_the_manifest_the_lens_reads_is_built_from_the_table_the_server_dispatches():
    """The premise the gate rests on, held on the server's own source.

    `serve.build_server()` cannot yet run in a lone checkout, so the two
    statements that make "in the manifest" mean "the server dispatches it" are
    read as text. Both must name the SAME table: the manifest's routes, the
    POST arm's match, and the handler class the table is bound to. If the
    manifest were ever built from anything else, the lens would gate on a fact
    the dispatcher does not share.
    """
    source = SERVE.read_text(encoding="utf-8")
    assert re.search(r"route_bindings = route_extension\.collect_bindings\(", source)
    # the manifest is published FROM that collection
    manifest = re.search(
        r'capabilities\["views"\] = view_extension\.view_manifest\('
        r"(.*?)\n    \)\n", source, re.S)
    assert manifest, "serve.py no longer publishes capabilities[\"views\"]"
    assert "contributed_routes=route_bindings" in manifest.group(1)
    # the POST arm consults the same table, through the same matcher
    assert 'route_extension.match(self.route_bindings, "POST", path)' in source
    assert '"route_bindings": route_bindings,' in source
