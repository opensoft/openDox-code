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

AMENDED BY SLICE S5 -- "contribute the gate loop". S4 was S5's precondition and
S5 has happened: the six class-B modules S4's ten tails landed in
(`views/gate.js`, `views/dispose.js`, `views/swb-create.js`,
`views/swb-session.js`, `views/gate-lens.js`, `views/gate-projects.js`) have
LEFT this bundle for openXdox-code's package data, declared there as
`ViewBinding`s (RULED Q5, openxFactory#656 comment `5648044785`). Half of every
row in `MOVED_TAILS` is therefore no longer a file this leg can read, and this
suite now says so explicitly rather than failing to open a path: the rows split
into `IN_BUNDLE_TAILS` (the one projection read slice S6 owns) and
`CONTRIBUTED_TAILS` (the ten gate ones), and what is asserted about the latter
is the half that is still THIS leg's -- the origin carries no literal, the
module is gone, no file of this bundle declares a gate route at all, and no
binding entry survives in `app.js`'s core arm. The other half -- the binding
declaring the same routes the module POSTs, and the module still performing the
verb under `node` -- moved WITH the modules, to openXdox-code's
`tests/test_gate_loop_views.py`.

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

# AMENDED BY SLICE S5 -- "contribute the gate loop". S4 put the ten gate-prefix
# tails into class-B modules; S5 moved those modules OUT OF THIS BUNDLE, to
# openXdox-code's package data, where they are declared as `ViewBinding`s
# (RULED Q5, openxFactory#656 comment `5648044785`). So half of every row above
# is no longer a file this leg can read, and this suite splits accordingly:
#
#   IN_BUNDLE      the one tail whose destination stayed -- `projection-index.js`
#                  is openXdox's PROJECTION column's read, not the gate loop's,
#                  and slice S6 (not S5) is what re-homes that family.
#   CONTRIBUTED    the ten gate tails. What this leg can still assert about them
#                  is the half that matters HERE: the origin is clean, the
#                  module has left, and no file of this bundle names the route.
#                  The other half -- that the binding declares it and the module
#                  still performs the verb -- is openXdox-code's, at
#                  `tests/test_gate_loop_views.py`.
IN_BUNDLE_TAILS = [row for row in MOVED_TAILS
                   if row[3] in ("projection-index.js",)]
CONTRIBUTED_TAILS = [row for row in MOVED_TAILS
                     if row[3] not in ("projection-index.js",)]
#: The six modules slice S5 moved to openXdox-code (four the note's S5 row names
#: plus the two S4 created, whose own header says "AT S5 THIS FILE LEAVES THE
#: BUNDLE").
CONTRIBUTED_MODULES = ("gate.js", "dispose.js", "swb-create.js",
                       "swb-session.js", "gate-lens.js", "gate-projects.js")


def _read(name: str) -> str:
    return (VIEWS / name).read_text(encoding="utf-8")


def _declares(source: str, constant: str, route: str) -> bool:
    return f'export const {constant} = "{route}";' in source


# ---------------------------------------------------------------------------
# 1. the move itself: out of the model, into the caller
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("constant,route,origin,destination", IN_BUNDLE_TAILS,
                         ids=[t[0] for t in IN_BUNDLE_TAILS])
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


@pytest.mark.parametrize("constant,route,origin,destination", CONTRIBUTED_TAILS,
                         ids=[t[0] for t in CONTRIBUTED_TAILS])
def test_each_contributed_route_tail_left_with_its_module(
        constant, route, origin, destination) -> None:
    """The same row after slice S5, measured from the side that stayed.

    S4 sent the tail to the class-B module that CALLS it; S5 sent that module to
    openXdox. Both halves of the move are still checkable here, and they are the
    two that would tell a reader this bundle had kept a copy: the ORIGIN carries
    no literal, and the DESTINATION is not a file of this bundle at all.
    """
    assert f'"{route}"' not in _read(origin), (
        f"{origin} still carries the literal {route!r}: the tail did not move, "
        f"it was copied")
    assert not (VIEWS / destination).exists(), (
        f"views/{destination} is still in this bundle: slice S5 moves the gate "
        f"loop's six class-B modules to openXdox-code's package data, where "
        f"{constant} is declared on a contributed ViewBinding")


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


@pytest.mark.parametrize("binding_id", ["gate.bar", "gate.lens", "gate.projects"])
def test_no_gate_binding_is_declared_in_the_shells_core_arm(binding_id) -> None:
    """AMENDED BY SLICE S5, and the amendment is what S4's own comment predicted.

    S4 asserted that each of its two binding entries in `app.js`'s CORE arm
    named the same routes as the module it pointed at -- a declaration
    "necessarily written twice ... because `app.js` is class A and may not
    import a class-B module to read them" -- and said in as many words that this
    is "what S5 will carry over when the entry moves from the core arm into
    `contributedViewBindings()`". It has moved. Both copies now sit at
    openXdox-code, one in `src/openxdox/view_extensions.py`'s binding spec and
    one in the module's own constants, and they are held to each other THERE
    (`tests/test_gate_loop_views.py::test_every_binding_declares_the_routes_its_module_names`)
    -- which is a stronger place for the check than here, because both halves
    are finally in one repository.

    What this leg asserts is the half it owns: not one of the three gate
    bindings is declared in the shell's core arm any more.
    """
    source = APP_JS.read_text(encoding="utf-8")
    assert f'id: "{binding_id}"' not in source, (
        f"app.js still declares {binding_id} in CORE_VIEWS; slice S5 moves every "
        "gate binding to the contributed column")


def test_no_file_of_this_bundle_declares_a_gate_route() -> None:
    """The strongest single statement this slice can make, and the one that says
    the gate loop really left rather than being partly copied.

    S4's version of this test asked whether the ten moved constants were
    declared by SOME class-B file of this bundle -- the precondition for S5.
    S5 is the slice after which the answer must be NO for every one of them,
    from any class: `views/gate.js`, `views/dispose.js`, `views/swb-create.js`,
    `views/swb-session.js`, `views/gate-lens.js` and `views/gate-projects.js`
    are openXdox-code's package data now, and a gate route literal surviving
    anywhere here would be a copy left behind.
    """
    survivors = []
    for path in sorted(p for p in WEB.rglob("*") if p.is_file()
                       and p.suffix in (".js", ".html", ".css")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r'"(/actions/gate/[^"]*)"', text):
            survivors.append(f"{path.relative_to(WEB).as_posix()}: {match.group(1)}")
    assert survivors == [], (
        f"{len(survivors)} gate route literal(s) still in this bundle: "
        f"{survivors}. RULED Q3: a route constant travels with the binding that "
        "calls it, and every gate binding is contributed at slice S5")


@pytest.mark.parametrize("name", CONTRIBUTED_MODULES)
def test_every_contributed_module_left_this_bundle(name) -> None:
    """The six files § 5's S5 row moves, checked one at a time so the failure
    names which one came back."""
    assert not (VIEWS / name).exists(), (
        f"views/{name} is still here; slice S5 moves it to openXdox-code's "
        "`src/openxdox/web/views/`, shipped as package data and copied into this "
        "bundle at assembly (RULED Q5)")
    census = yaml.safe_load(CENSUS_PATH.read_text(encoding="utf-8"))
    rows = {row["path"] for row in census["files"]}
    assert f"views/{name}" not in rows, (
        f"the census still carries a row for views/{name}: a row naming a file "
        "that is not here fails assertion 1's own stale-row check")


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


def test_the_census_carries_the_one_new_module_that_stayed_as_class_b() -> None:
    """AMENDED BY SLICE S5. Two of S4's three new modules left this bundle with
    the gate loop; `views/projection-index.js` is openXdox's PROJECTION column's
    one read, which slice S6 re-homes and this slice does not touch."""
    census = yaml.safe_load(CENSUS_PATH.read_text(encoding="utf-8"))
    rows = {row["path"]: row for row in census["files"]}
    row = rows.get("views/projection-index.js")
    assert row is not None, "views/projection-index.js carries no census row"
    assert row["class"] == "B", f"it is class {row['class']!r}"
    for gone in ("gate-lens.js", "gate-projects.js"):
        assert f"views/{gone}" not in rows, (
            f"views/{gone} still carries a census row after slice S5 moved it")


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


# ---------------------------------------------------------------------------
# THE FIVE NODE PROBES OF `gate-lens.js` AND `gate-projects.js` MOVED WITH THEIR
# MODULES (slice S5). They drove the real bundle files -- the lens gate posting
# the route its plan kind names, its refusal render and re-arm, the two project
# commissions and a refused membership edit restoring its control -- and those
# files are openXdox-code's package data now (RULED Q5, openxFactory#656 comment
# `5648044785`). A probe that imported them from `src/opendox/web/views/` would
# be asserting against a file this bundle no longer ships.
#
# THEY WERE PORTED, NOT DELETED, and the port is the point: deleting behavioural
# coverage in a refactor slice is how a move that passes every shape assertion
# silently breaks a verb, which is the failure this suite's own header names as
# "the worst possible outcome of this slice". They run at openXdox-code, against
# the same real files, in `tests/test_gate_loop_probes.py` -- same harness, same
# DOM stub, same assertions, and one thing STRONGER: there each probe assembles
# a COMPOSED bundle first (openDox's own `web/` with that column's six modules
# placed into it by RULED Q5's assembly hook) and imports the module from there,
# so the byte measured is the shipped byte in the shipped position.
#
# What stays here is everything about the modules this bundle still ships, and
# the SHAPE assertions above, which are what this leg can still answer.
# ---------------------------------------------------------------------------

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
