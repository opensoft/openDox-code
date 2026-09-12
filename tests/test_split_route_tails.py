"""The thirteen route tails, where they landed and what they do there --
slice S4.

`docs/front-end-package-boundary.md` § 5's S4 row is the PRECONDITION for S5:
"Only 3 of the 13 gate-route constants are declared in class-B files
(`dispose.js`:28/:29, `gate.js`:120); the other 10 are declared in
`lens-model.js`, `repo-selector.js` and `staging-workbench-model.js`, and both
`swb-create.js` and `swb-session.js` IMPORT theirs from the last of those. The
gate loop cannot be contributed until its route table stops living outside
class B." RULED Q3 (opensoft/openxFactory#656 comment `5642758731`, Brett Heap,
2026-09-12) states the rule the move obeys: **"a route constant travels with
the binding that calls it, never with the model that happens to declare it."**

WHAT THIS FILE MEASURES AND `tests/test_web_boundary.py` DOES NOT. The census
test asserts the BOUNDARY -- that no file outside class B names a route another
column declares -- and it would stay just as green if all thirteen constants
had been deleted outright and the three surfaces silently stopped working. This
file asserts the OTHER half: that each constant is declared in the class-B file
that calls it, that the binding entries in `app.js` and the modules they name
declare the SAME routes, that no class-A or class-C file reaches the new
modules through a static import, and -- under `node`, against the real bundle
files -- that the three new modules still DO what the code that moved out of
`lens.js` and `repo-selector.js` did. A move that passed the census and broke
the verb would be the worst possible outcome of this slice.

`--noconftest` SAFE, like its five neighbours on `validate`'s explicit list: it
reads bundle files as text and drives the real ones under the `node` the runner
already has (skipped, never failed, where node is absent). It imports no
`opendox` submodule and needs no installed consumer. The bundle's own
`package.json` (`"type": "module"`, added by slice S3) is what makes `node` read
these `.js` files as the ES modules they are; the harnesses below import them
BY ABSOLUTE PATH out of the real `src/opendox/web/views/`, never a copy, so a
passing test is a statement about the shipped file and not about a fixture that
resembles it.

A CREATED file: no carve-manifest row (RULED OQ-C), admitted by path in
openxFactory's `docs/opendox-carve-admissions.yaml`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
VIEWS = WEB / "views"
APP_JS = WEB / "app.js"
CENSUS_PATH = Path(__file__).resolve().parent / "fixtures" / "web_boundary_census.yaml"
NODE = shutil.which("node")

# The three files § 3.2 RULED SPLIT, and the routes each one declared at the
# census tree. `where` is the file that declares it now -- always the one that
# CALLS it, which is the whole of Q3.
MOVED_TAILS = [
    # (constant, route, from, to)
    ("LENS_SAVE_ROUTE", "/actions/gate/lens-save-recipe",
     "lens-model.js", "gate-lens.js"),
    ("LENS_CLUSTER_ROUTE", "/actions/gate/lens-add-as-cluster",
     "lens-model.js", "gate-lens.js"),
    ("SNAPSHOT_INDEX_ROUTE", "/snapshot-index.json",
     "repo-selector.js", "projection-index.js"),
    ("ACTIONS_CREATE_PROJECT_ROUTE", "/actions/gate/create-project",
     "repo-selector.js", "gate-projects.js"),
    ("ACTIONS_EDIT_PROJECT_ROUTE", "/actions/gate/edit-project",
     "repo-selector.js", "gate-projects.js"),
    ("CREATE_ROUTE", "/actions/gate/create-document",
     "staging-workbench-model.js", "swb-create.js"),
    ("EDIT_DOCUMENT_ROUTE", "/actions/gate/edit-document",
     "staging-workbench-model.js", "swb-session.js"),
    ("OPEN_PR_ROUTE", "/actions/gate/open-pr",
     "staging-workbench-model.js", "swb-session.js"),
    ("FIRST_EDIT_ROUTE", "/actions/gate/first-edit",
     "staging-workbench-model.js", "swb-session.js"),
    ("ABANDON_SESSION_ROUTE", "/actions/gate/abandon-session",
     "staging-workbench-model.js", "swb-session.js"),
    ("SHARE_SESSION_ROUTE", "/actions/gate/share-session",
     "staging-workbench-model.js", "swb-session.js"),
]

# The two tails that did NOT move to a class: one stays where it is because
# openDox itself answers it, and one leaves the bundle because no class here can
# ever own it (§ 2.2 rule 1: "openxFactory's adapter lanes -- the last of which
# no class can ever own, because RULING DQ-1 keeps that column at
# openxFactory").
STAYS_CLASS_A = ("ACTIONS_REFRESH_ROUTE", "/actions/refresh", "repo-selector.js")
LEFT_THE_BUNDLE = ("ACTIONS_APPLY_REGISTER_EDITS_ROUTE",
                   "/actions/apply-register-edits", "repo-selector.js")

SPLIT_FILES = ("lens-model.js", "repo-selector.js", "staging-workbench-model.js")
NEW_MODULES = ("gate-lens.js", "gate-projects.js", "projection-index.js")


def _read(name: str) -> str:
    return (VIEWS / name).read_text(encoding="utf-8")


def _declares(source: str, constant: str, route: str) -> bool:
    return f'export const {constant} = "{route}";' in source


# ---------------------------------------------------------------------------
# 1. the move itself: out of the model, into the caller
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("constant,route,origin,destination", MOVED_TAILS,
                         ids=[t[0] for t in MOVED_TAILS])
def test_each_route_tail_is_declared_in_the_file_that_calls_it(
        constant, route, origin, destination) -> None:
    """RULED Q3, one row at a time. The constant is declared in its
    destination and the route literal is gone from its origin."""
    assert _declares(_read(destination), constant, route), (
        f"{destination} does not declare {constant} = {route!r} -- RULED Q3 "
        f"sends a route constant to the binding that calls it, and this one "
        f"was called from there while {origin} merely declared it"
    )
    assert f'"{route}"' not in _read(origin), (
        f"{origin} still carries the literal {route!r}: the tail did not move, "
        f"it was copied"
    )


def test_the_three_split_files_declare_no_route_constant_that_left() -> None:
    """The stronger statement the per-row test cannot make on its own: not one
    of the eleven names survives as an `export const` in the file it left, so a
    re-export shim cannot quietly keep the old import working and leave the
    boundary exactly where it was."""
    for origin in SPLIT_FILES:
        source = _read(origin)
        lingering = sorted(
            constant for constant, _route, o, _d in MOVED_TAILS
            if o == origin and re.search(rf"\bexport const {constant}\b", source)
        )
        assert not lingering, f"{origin} still exports {lingering}"


def test_the_refresh_route_stayed_class_a() -> None:
    """§ 3.3's table lists `/actions/refresh` under openDox, and § 3.2's Q3 row
    says "picker + refresh stay class A" -- so this one is measured to have NOT
    moved. A slice that swept every route out of the selector would pass every
    other assertion here."""
    constant, route, origin = STAYS_CLASS_A
    assert _declares(_read(origin), constant, route)


def test_the_openxfactory_lane_left_the_bundle_entirely() -> None:
    """RULED Q3 for `repo-selector.js`:46: "`/actions/apply-register-edits` is
    openxFactory's lane and leaves the bundle entirely" -- not to a class, not
    to an optional binding, OUT. Measured over the whole bundle, because
    "leaves the bundle" is a statement about every file in it."""
    constant, route, _origin = LEFT_THE_BUNDLE
    carriers = sorted(
        p.relative_to(WEB).as_posix() for p in WEB.rglob("*")
        if p.is_file() and p.suffix in (".js", ".html")
        and f'"{route}"' in p.read_text(encoding="utf-8", errors="replace")
    )
    assert not carriers, f"{route} still addressed by: {carriers}"
    assert constant not in _read("repo-selector.js")
    # and the control that reached it
    assert "applybtn" not in _read("repo-selector.js")


# ---------------------------------------------------------------------------
# 2. the bindings: declared once, and the same in both places
# ---------------------------------------------------------------------------

def _js_route_array(source: str, name: str) -> list[str]:
    """The routes of `export const <name> = [ ... ];`, which is how each
    class-B module states what it owns. Members are the module's own route
    CONSTANTS -- the whole point of the file is that the literal is written
    once -- so each identifier is resolved back to the string it was declared
    with, in the same file."""
    match = re.search(rf"export const {name} = \[(.*?)\];", source, re.S)
    assert match, f"{name} not found"
    literals = dict(re.findall(r'export const (\w+) = "([^"]+)";', source))
    routes = []
    for member in (m.strip() for m in match.group(1).split(",")):
        if not member:
            continue
        if member.startswith('"'):
            routes.append(member.strip('"'))
            continue
        assert member in literals, (
            f"{name} names {member!r}, which {name}'s own module does not "
            f"declare as a route constant"
        )
        routes.append(literals[member])
    return routes


def _app_binding(binding_id: str) -> dict:
    """The CORE_VIEWS entry for one binding id, as `{field: value}` over the
    fields this test reads. A regex and not a parser for the same reason
    `tests/test_view_registry.py` uses one: there is no JS parser in this leg's
    dependency set, and the note's own § 4.5 test is written to that
    constraint."""
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(rf'\{{ id: "{re.escape(binding_id)}", region: "([^"]+)",'
                      r'\s*\n\s*module: "([^"]+)", entry: "([^"]+)",?'
                      r'(?:\s*\n\s*view_class: "([^"]+)",)?'
                      r'(?:\s*view_class: "([^"]+)",)?'
                      r'(.*?)optional: (true|false)',
                      source, re.S)
    assert match, f"no CORE_VIEWS entry for {binding_id!r} in app.js"
    body = match.group(0)
    routes = re.search(r"routes: \[(.*?)\]", body, re.S)
    return {
        "region": match.group(1),
        "module": match.group(2),
        "entry": match.group(3),
        "view_class": match.group(4) or match.group(5),
        "routes": re.findall(r'"([^"]+)"', routes.group(1)) if routes else [],
        "optional": match.group(7) == "true",
    }


@pytest.mark.parametrize("binding_id,module,entry,region,declared_in,constant", [
    ("gate.lens", "./views/gate-lens.js", "mountLensGate", "lens-gate",
     "gate-lens.js", "LENS_GATE_ROUTES"),
    ("gate.projects", "./views/gate-projects.js", "mountProjectCommissions",
     "repo-projects", "gate-projects.js", "PROJECT_GATE_ROUTES"),
])
def test_the_binding_entry_and_its_module_declare_the_same_routes(
        binding_id, module, entry, region, declared_in, constant) -> None:
    """`view_extension.py`: "a binding that declares the routes it calls is
    what makes that ruling checkable instead of aspirational". The declaration
    is necessarily written twice -- once in the manifest entry and once as the
    constants the module POSTs -- because `app.js` is class A and may not
    import a class-B module to read them. THIS is what keeps the two copies
    honest, and it is what S5 will carry over when the entry moves from the
    core arm into `contributedViewBindings()`."""
    binding = _app_binding(binding_id)
    assert binding["module"] == module
    assert binding["entry"] == entry
    assert binding["region"] == region
    assert binding["view_class"] == "B", (
        f"{binding_id} is not declared class B; class B is the ONLY class "
        f"exempt from the route-ownership refusal, and a gate binding that "
        f"declares itself anything else refuses its own assembly"
    )
    assert binding["optional"] is True, (
        f"{binding_id} must be optional: a shell assembled without the gate "
        f"column has to come up, which is RULING C2 one tier out"
    )
    assert binding["routes"] == _js_route_array(_read(declared_in), constant), (
        f"{binding_id}'s declared routes and {declared_in}'s {constant} have "
        f"drifted apart"
    )


def test_every_moved_gate_route_is_declared_by_some_class_b_module() -> None:
    """The ten gate-prefix constants § 5's S4 row counts, checked as a SET:
    each is declared in a class-B file, so the gate loop's route table no
    longer lives outside class B and S5 can contribute it."""
    census = yaml.safe_load(CENSUS_PATH.read_text(encoding="utf-8"))
    class_b = [row["path"] for row in census["files"] if row["class"] == "B"]
    declared: set[str] = set()
    for path in class_b:
        for match in re.finditer(r'export const \w+ = "(/actions/gate/[^"]+)";',
                                 (WEB / path).read_text(encoding="utf-8")):
            declared.add(match.group(1))
    moved = {route for _c, route, _o, _d in MOVED_TAILS
             if route.startswith("/actions/gate/")}
    assert moved <= declared, f"not declared in any class-B file: {sorted(moved - declared)}"
    # plus the three that were already there (§ 4.5 point 2: "the three gate
    # constants declared in class-B files are NOT in the count")
    assert {"/actions/gate/dispose-possible", "/actions/gate/propose",
            "/actions/gate/ratify"} <= declared


@pytest.mark.parametrize("importer", ["app.js", "views/lens.js",
                                      "views/repo-selector.js"])
def test_no_class_a_or_c_file_statically_imports_a_new_class_b_module(
        importer) -> None:
    """§ 4.5 assertion 3 measures this over the census; measured HERE over the
    three files this slice actually rewired, because a static import added by
    S4 would be a NEW breach of the very rule S4 exists to serve, and the
    census assertion is `xfail` today so it could not tell anyone."""
    source = (WEB / importer).read_text(encoding="utf-8")
    specifiers = re.findall(r'^import\s[^;]*?from\s+"([^"]+)";', source,
                            re.M | re.S)
    specifiers += re.findall(r'^\s*import\s+"([^"]+)";', source, re.M)
    forbidden = sorted(s for s in specifiers
                       if s.rsplit("/", 1)[-1] in NEW_MODULES)
    assert not forbidden, (
        f"{importer} statically imports {forbidden}: the new modules are "
        f"reached through the shell's resolved mounts (gate.lens, "
        f"gate.projects) or a late dynamic import (projection-index.js), "
        f"never a `from` clause"
    )


def test_the_selector_reaches_the_projection_column_late() -> None:
    """§ 4.2's own guard, in the shape S2 established: "an optional resolve in
    place of the import-time `from`". A dynamic `import()`, and a `try` around
    it, or an absent projection column is a module nothing can resolve rather
    than a null."""
    source = _read("repo-selector.js")
    assert 'await import("./projection-index.js")' in source
    assert "PROJECTION_COLUMN = null" in source


def test_the_census_carries_the_three_new_modules_as_class_b() -> None:
    census = yaml.safe_load(CENSUS_PATH.read_text(encoding="utf-8"))
    rows = {row["path"]: row for row in census["files"]}
    for name in NEW_MODULES:
        row = rows.get(f"views/{name}")
        assert row is not None, f"views/{name} carries no census row"
        assert row["class"] == "B", f"views/{name} is class {row['class']!r}"


# ---------------------------------------------------------------------------
# 3. the three new modules, driven under node against the REAL bundle files
# ---------------------------------------------------------------------------

# A minimal DOM: enough for `helpers.el` and the two mounts, and nothing more.
# Every node records its tag, class, text, attributes, wired listeners and
# children, so a harness can report the tree as JSON and fire a click.
_DOM_STUB = r"""
class Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {};
    this.className = ""; this._text = ""; this.type = ""; this.title = "";
    this.value = ""; this.checked = false; this.disabled = false;
    this.hidden = false; this.focused = false;
  }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); this.children = []; }
  set innerHTML(v) { if (v !== "") throw new Error("innerHTML assigned " + v); this.children = []; this._text = ""; }
  appendChild(c) { this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  focus() { this.focused = true; }
  click() { for (const fn of this.listeners.click || []) fn({}); }
}
globalThis.document = { createElement: (tag) => new Node(tag) };
function flatten(node, out = []) {
  out.push(node);
  for (const c of node.children) flatten(c, out);
  return out;
}
function texts(node) { return flatten(node).map((n) => n.textContent).filter(Boolean); }
function buttons(node) { return flatten(node).filter((n) => n.tag === "button"); }
function inputs(node) { return flatten(node).filter((n) => n.tag === "input"); }
globalThis.flatten = flatten; globalThis.texts = texts;
globalThis.buttons = buttons; globalThis.inputs = inputs;
// The injected fetcher every transport in this bundle takes, recording what it
// was asked for. `body` comes back parsed so a harness asserts on the REQUEST.
function recorder(response) {
  const calls = [];
  return [calls, async (route, opts) => {
    calls.push({ route, method: opts?.method || "GET",
                 body: opts?.body ? JSON.parse(opts.body) : null });
    return { ok: response.ok !== false, status: response.status || 200,
             json: async () => response.payload };
  }];
}
globalThis.recorder = recorder;
const settle = () => new Promise((r) => setTimeout(r, 0));
globalThis.settle = settle;
"""


def _run_node(body: str, tmp_path: Path) -> dict:
    """Run an ES-module harness against the REAL bundle and return the ONE JSON
    object it prints. The modules are imported by absolute `file://` URL out of
    `src/opendox/web/views/`, so what is measured is the shipped file."""
    source = (
        _DOM_STUB
        + f'\nconst VIEWS = {json.dumps(VIEWS.resolve().as_uri() + "/")};\n'
        + body
    )
    script = tmp_path / "harness.mjs"
    script.write_text(source, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("kind,expected", [
    ("save-recipe", "/actions/gate/lens-save-recipe"),
    ("add-as-cluster", "/actions/gate/lens-add-as-cluster"),
])
def test_js_the_lens_gate_posts_the_route_its_plan_kind_names(
        kind, expected, tmp_path) -> None:
    """The verb still works after the move, and it posts the route the plan
    kind names -- the behaviour that used to live in `views/lens.js`'s
    `mountExecute`, now in the binding that owns both routes."""
    result = _run_node(f"""
const {{ mountLensGate }} = await import(VIEWS + "gate-lens.js");
const [calls, fetcher] = recorder({{ payload: {{ ok: true, manifest: "m.yaml",
                                                record: "r.yaml" }} }});
const host = document.createElement("div");
const plan = {{ kind: {json.dumps(kind)}, repository: "openxFactory", name: "lens set",
               checked: ["a"], pinned: [], members: [], excluded: [] }};
mountLensGate(host, {{ plan, caps: {{ actor: "brett" }}, fetcher }});
buttons(host)[0].click();
await settle();
// add-as-cluster collects the organizer evidence first: fill it and submit.
if (calls.length === 0) {{
  const form = flatten(host).find((n) => n.className
    && n.className.includes("evidence-form"));
  for (const input of inputs(form)) input.value = "x";
  buttons(form).find((b) => b.textContent === "execute").click();
  await settle();
}}
console.log(JSON.stringify({{ calls, texts: texts(host) }}));
""", tmp_path)
    assert [c["route"] for c in result["calls"]] == [expected]
    call = result["calls"][0]
    assert call["method"] == "POST"
    assert call["body"]["repository"] == "openxFactory"
    if kind == "add-as-cluster":
        assert call["body"]["evidence"]["proposer"] == "x"
    else:
        assert "evidence" not in call["body"]
    assert any("landed" in t for t in result["texts"])


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_the_lens_gate_renders_the_engines_refusal_and_re_arms(tmp_path) -> None:
    """"the engine refuses and the reason renders verbatim (single source of
    truth)" -- and a refused plan stays retryable, which is what the disabled
    flag coming back off means."""
    result = _run_node("""
const { mountLensGate } = await import(VIEWS + "gate-lens.js");
const [calls, fetcher] = recorder({ ok: false, status: 409,
  payload: { ok: false, message: "recipe already recorded" } });
const host = document.createElement("div");
mountLensGate(host, { plan: { kind: "save-recipe", repository: "r", name: "n",
                              members: [], excluded: [] },
                      caps: {}, fetcher });
const run = buttons(host)[0];
run.click();
await settle();
console.log(JSON.stringify({ calls, texts: texts(host), disabled: run.disabled }));
""", tmp_path)
    assert len(result["calls"]) == 1
    assert "recipe already recorded" in result["texts"]
    assert result["disabled"] is False


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_the_project_commissions_post_both_gate_routes(tmp_path) -> None:
    """One binding, two routes: the create form POSTs the create-project
    commission and `commissionEdit` POSTs the membership one, carrying the
    project id the selector holds. The controller's shape is the seam
    `views/repo-selector.js` reaches through, so it is measured here rather
    than assumed."""
    result = _run_node("""
const { mountProjectCommissions } = await import(VIEWS + "gate-projects.js");
const [calls, fetcher] = recorder({ payload: { ok: true, job: "J-1",
                                               add: ["b"], remove: [] } });
const host = document.createElement("div");
const status = document.createElement("span");
const pending = [];
const gate = mountProjectCommissions(host, {
  roster: [{ kind: "repository", repository: "openxFactory" },
           { kind: "repository", repository: "openDox" }],
  status, fetcher, addPendingOption: (name) => pending.push(name),
});
// the create form: opened by the dropdown's "New Project..." line
const form = flatten(host).find((n) => n.className
  && n.className.includes("projectform"));
const hiddenBeforeOpen = form.hidden;
gate.openCreateForm();
inputs(form).find((i) => i.tag === "input" && i.type === "text").value = "Field Pilots";
inputs(form).filter((i) => i.type === "checkbox")[0].checked = true;
buttons(form).find((b) => b.textContent === "commission project").click();
await settle();
// the membership edit: raised by the filter's add row / trash control
let restored = false;
await gate.commissionEdit("proj-1", { add: ["openDox"] },
                          { restore: () => { restored = true; } });
console.log(JSON.stringify({ calls, pending, hiddenBeforeOpen,
                             retired: form.hidden, restored,
                             status: status.textContent }));
""", tmp_path)
    assert [c["route"] for c in result["calls"]] == [
        "/actions/gate/create-project", "/actions/gate/edit-project"]
    create, edit = result["calls"]
    assert create["body"] == {"name": "Field Pilots",
                              "repositories": ["openxFactory"]}
    assert edit["body"] == {"project_id": "proj-1", "add": ["openDox"]}
    assert result["hiddenBeforeOpen"] is True    # the form is opened, never shown
    assert result["retired"] is True             # a landed commission retires it
    assert result["restored"] is False           # nothing to restore on success
    assert "membership edit recorded (J-1)" == result["status"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_a_refused_membership_edit_restores_the_control(tmp_path) -> None:
    """The two-click trash re-arms and the add row's select restores its
    placeholder -- `restore` is the selector's half of the act, and the
    binding has to call it on a refusal or a control is left dead."""
    result = _run_node("""
const { mountProjectCommissions } = await import(VIEWS + "gate-projects.js");
const [calls, fetcher] = recorder({ ok: false, status: 403,
  payload: { ok: false, message: "not a gate actor" } });
const status = document.createElement("span");
const gate = mountProjectCommissions(document.createElement("div"),
                                     { roster: [], status, fetcher });
let restored = false;
await gate.commissionEdit("proj-1", { remove: ["openDox"] },
                          { restore: () => { restored = true; } });
console.log(JSON.stringify({ calls, restored, status: status.textContent }));
""", tmp_path)
    assert result["restored"] is True
    assert "not a gate actor" in result["status"]
    assert result["status"].startswith("edit-project refused: ")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_the_snapshot_index_read_degrades_to_null(tmp_path) -> None:
    """The projection read's whole contract: "ANY failure resolves to null --
    the caller then renders exactly today's single-snapshot dashboard. Never
    throws." Measured for a 404 (the static image), a thrown fetch (`file://`)
    and the happy path."""
    result = _run_node("""
const { SNAPSHOT_INDEX_ROUTE, fetchSnapshotIndex } =
  await import(VIEWS + "projection-index.js");
const routes = [];
const ok = await fetchSnapshotIndex(async (route) => {
  routes.push(route);
  return { ok: true, status: 200, json: async () => ({ entries: [1] }) };
});
const missing = await fetchSnapshotIndex(async () => ({ ok: false, status: 404 }));
const thrown = await fetchSnapshotIndex(async () => { throw new Error("file://"); });
console.log(JSON.stringify({ route: SNAPSHOT_INDEX_ROUTE, routes, ok,
                             missing, thrown }));
""", tmp_path)
    assert result["route"] == "/snapshot-index.json"
    assert result["routes"] == ["/snapshot-index.json"]
    assert result["ok"] == {"entries": [1]}
    assert result["missing"] is None
    assert result["thrown"] is None


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_the_selectors_index_fetch_forwards_to_the_projection_column(
        tmp_path) -> None:
    """The selector's own `fetchIndex` still reaches the route it no longer
    names -- through the late `import()` rather than a literal. Driven against
    the real `views/repo-selector.js`, so the seam is measured end to end."""
    result = _run_node("""
const { fetchIndex } = await import(VIEWS + "repo-selector.js");
const routes = [];
const index = await fetchIndex(async (route) => {
  routes.push(route);
  return { ok: true, status: 200, json: async () => ({ entries: ["e"] }) };
});
// the column is resolved ONCE and remembered: a second call must not re-import
await fetchIndex(async (route) => {
  routes.push(route);
  return { ok: true, status: 200, json: async () => ({ entries: ["e"] }) };
});
console.log(JSON.stringify({ routes, index }));
""", tmp_path)
    assert result["routes"] == ["/snapshot-index.json", "/snapshot-index.json"]
    assert result["index"] == {"entries": ["e"]}
