"""The gate loop CONTRIBUTED — § 3.4 slice S5, leg B (the shell).

`docs/front-end-package-boundary.md` § 5 row S5 (openDox-spec `7d12428c`): *"The
four class-B files and all 13 route constants — now all declared in class-B
files — move behind a binding openXdox supplies; a student install comes up with
no gate bar, no dispose tray, no session verbs, and no 404."* The contract is
openXdox-spec `docs/gate-loop-view-contract.md` @ `d73767b7`, whose § 8 Q1–Q12
were RULED by Brett Heap on 2026-09-12 at `opensoft/openxFactory#656` comments
`5648044785` (Q5, Q1, Q3), `5648049748` (Q2, Q4, Q7, Q8) and `5648065587` (Q9,
Q10, Q11, Q12).

WHAT THIS FILE MEASURES AND ITS NEIGHBOURS DO NOT. `tests/test_web_boundary.py`
asserts the BOUNDARY — no file outside class B names another column's route, and
every relative import resolves and stays in its class — and both of its relevant
assertions would be just as green if the gate loop had been DELETED. This file
asserts the other half, which is the half a slice called "contribute" has to
earn: that the seam the modules left through actually works, that what the shell
keeps of them is reached through the registry and bounded by the declaration,
and — the slice's own success test — that a shell assembled without the column
comes up.

THE STUDENT-INSTALL PROOF is
`test_a_student_install_comes_up_with_no_gate_loop_and_no_404`, and it is
deliberately made of four separate facts rather than one: no gate bar, no
dispose tray, no session verbs, no 404. Each is proven against the real bundle
— the module graph with the six files absent, the registry answering `null` for
every gate binding id, no gate route literal anywhere to be requested, and the
shell's own null columns making each affordance unoffered.

`--noconftest` SAFE, like its seven neighbours on `validate`'s explicit list: it
imports `opendox.view_extension` alone, reads bundle files as text, and drives
the real `views/view_extension.js` under the `node` the runner already has
(skipped, never failed, where node is absent).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from opendox.view_extension import (
    REGIONS, ViewBinding, ViewBindingError, collect_view_bindings, dom_regions,
    view_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
VIEWS = WEB / "views"
APP_JS = WEB / "app.js"
REGISTRY_JS = VIEWS / "view_extension.js"
CENSUS_PATH = Path(__file__).resolve().parent / "fixtures" / "web_boundary_census.yaml"
NODE = shutil.which("node")

#: The six modules that left, and the binding id each arrives as. Six and not
#: four: slice S4 split four of the thirteen gate route constants into two NEW
#: class-B modules, and `views/gate-lens.js`'s own header said "AT S5 THIS FILE
#: LEAVES THE BUNDLE".
CONTRIBUTED = {
    "gate.bar": "gate.js",
    "gate.lens": "gate-lens.js",
    "gate.projects": "gate-projects.js",
    "gate.dispose": "dispose.js",
    "gate.workbench.create": "swb-create.js",
    "gate.workbench.session": "swb-session.js",
}

#: The regions slice S5 adds. `page-overlay` is RULED Q8's; the workbench's two
#: arrive with the bindings that mount into them, on slice S4's own precedent.
NEW_REGIONS = ("page-overlay", "workbench-create", "workbench-session")


def _app() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _run_node(source: str, cwd: Path) -> dict:
    """Run an ES-module harness and return the ONE JSON object it prints."""
    script = cwd / "harness.mjs"
    script.write_text(source, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _temp_bundle(tmp_path: Path, panels: dict[str, str] | None = None) -> Path:
    """A throwaway `web/` carrying a byte-identical copy of the registry.

    The registry resolves a binding's module against the BUNDLE ROOT, so a
    fixture panel has to live in a bundle. Copying rather than writing fixtures
    into `src/opendox/web/views/` keeps the real bundle exactly the set of files
    the census counts — § 4.5 assertion 1 fails an unrowed file, and a fixture
    would be one. It also stands in for the ASSEMBLY that RULED Q5 describes:
    openXdox's module bytes placed beside openDox's in one served directory.
    """
    web = tmp_path / "web"
    (web / "views").mkdir(parents=True)
    (web / "package.json").write_text(
        '{"private": true, "type": "module"}\n', encoding="utf-8")
    (web / "views" / "view_extension.js").write_bytes(REGISTRY_JS.read_bytes())
    for name, source in (panels or {}).items():
        (web / "views" / name).write_text(source, encoding="utf-8")
    return web


# ---------------------------------------------------------------------------
# THE SLICE'S OWN SUCCESS TEST
# ---------------------------------------------------------------------------

def test_a_student_install_comes_up_with_no_gate_loop_and_no_404() -> None:
    """§ 5's S5 row, sentence for sentence, against the real bundle.

    *"a student install comes up with no gate bar, no dispose tray, no session
    verbs, and no 404."* A student install is this bundle served with no
    openXdox registered: the `/capabilities` payload carries no view manifest
    (or none at all, on a static image), so the consumer column is empty.

    FOUR FACTS, EACH MEASURED SEPARATELY, because a single assertion would hide
    which one had broken.
    """
    app = _app()
    census = yaml.safe_load(CENSUS_PATH.read_text(encoding="utf-8"))
    rowed = {row["path"] for row in census["files"]}

    # (1) NO GATE BAR, NO DISPOSE TRAY, NO SESSION VERBS — because none of the
    #     six modules is in the bundle at all, and no census row claims one.
    for binding_id, module in CONTRIBUTED.items():
        assert not (VIEWS / module).is_file(), (
            f"views/{module} is still in this bundle; slice S5 moves it to "
            "openXdox-code's package data (RULED Q5)")
        assert f"views/{module}" not in rowed, (
            f"the census still carries a row for views/{module}")
        assert f'id: "{binding_id}"' not in app, (
            f"app.js still declares {binding_id} in its CORE arm, so this shell "
            "supplies the gate loop instead of receiving it")

    # (2) NOTHING IMPORTS THEM, so the module graph resolves without them. This
    #     is the § 1.2(b) failure mode the note names: a dangling static import
    #     fails the WHOLE module graph, which is a blank page rather than a
    #     missing panel — "the shell's own module graph does not resolve".
    importers = []
    for path in sorted(p for p in WEB.rglob("*.js") if p.is_file()):
        text = path.read_text(encoding="utf-8")
        for specifier in re.findall(r'from\s*["\'](\.\.?/[^"\']+)["\']', text):
            if specifier.rsplit("/", 1)[-1] in CONTRIBUTED.values():
                importers.append(f"{path.relative_to(WEB).as_posix()} -> {specifier}")
    assert importers == [], (
        f"{len(importers)} module(s) still import a contributed module: "
        f"{importers}. A student install would fail to LOAD rather than render "
        "without the gate loop")

    # (3) NO 404 — there is no gate route left in this bundle for anything to
    #     request. RULED Q12 made the last one (a concatenation the grep could
    #     not see) into four literals, and they travelled with their module.
    requests = []
    for path in sorted(p for p in WEB.rglob("*") if p.is_file()
                       and p.suffix in (".js", ".html", ".css")):
        text = path.read_text(encoding="utf-8", errors="replace")
        requests += [f"{path.relative_to(WEB).as_posix()}: {m}"
                     for m in re.findall(r'"(/actions/gate/[^"]*)"', text)]
    assert requests == [], (
        f"{len(requests)} gate route literal(s) survive in this bundle: "
        f"{requests}")

    # (4) AND EACH AFFORDANCE IS UNOFFERED RATHER THAN UNDEFINED. The two class-C
    #     files that used to import the column now read a NULL COLUMN whose
    #     capability predicates answer false, so every gate control this shell
    #     can draw is simply not drawn.
    wheel = (VIEWS / "wheel.js").read_text(encoding="utf-8")
    workbench = (VIEWS / "staging-workbench.js").read_text(encoding="utf-8")
    assert "NO_DISPOSE_COLUMN" in wheel and "gateCapable: () => false" in wheel
    assert "NO_CREATE_COLUMN" in workbench and "createGateLive: () => false" in workbench
    assert "NO_SESSION_COLUMN" in workbench


def test_the_shell_falls_back_to_a_refusal_transport_rather_than_a_blank() -> None:
    """RULED Q10 (`5648065587`): the workbench transport travels as a declared
    non-mount export "with a refusal-shaped fallback when the binding is absent
    — never a blank". A Save on a shell with no gate column must SAY so."""
    app = _app()
    assert "function refusalTransport()" in app
    assert "no_gate_column" in app
    assert 'from "./views/swb-session.js"' not in app, (
        "app.js still statically imports the workbench module; RULED Q10 sends "
        "`firstEditTransport` through the registry")
    assert "workbenchGate.session.firstEditTransport(" in app
    assert ": refusalTransport()" in app


# ---------------------------------------------------------------------------
# RULED Q2 — the module NAMESPACE, declared
# ---------------------------------------------------------------------------

def test_a_binding_declares_its_namespace_and_the_entry_is_in_it() -> None:
    ok = ViewBinding(id="gate.bar", region="viewer-gatebar",
                     module="./views/gate.js", entry="mountGateBar",
                     view_class="B", exports=("mountGateBar", "isGateBearing"))
    assert ok.as_manifest_entry()["exports"] == ["mountGateBar", "isGateBearing"]
    # EMPTY IS THE PRE-Q2 CONTRACT — `entry` alone — which is what every core-arm
    # binding still declares.
    assert ViewBinding(id="docs.list", region="view-docs",
                       module="./views/docs.js", entry="renderDocs",
                       view_class="A").exports == ()


@pytest.mark.parametrize("over,fragment", [
    ({"exports": ["mountGateBar"]}, "not a tuple"),
    ({"exports": ("not an identifier",)}, "the NAME of an export"),
    ({"exports": ("__proto__",)}, "dunder"),
    ({"exports": ("isGateBearing",)}, "do not include its own entry"),
])
def test_a_malformed_exports_tuple_refuses_where_it_is_declared(over, fragment):
    spec = dict(id="gate.bar", region="viewer-gatebar",
                module="./views/gate.js", entry="mountGateBar", view_class="B")
    spec.update(over)
    with pytest.raises(ViewBindingError) as excinfo:
        ViewBinding(**spec)
    assert fragment in str(excinfo.value)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_an_undeclared_reach_past_the_declaration_refuses(tmp_path) -> None:
    """RULED Q2's refusal half, driven against the real registry: "an undeclared
    reach (today `isGateBearing`, app.js:939) is a refusal"."""
    web = _temp_bundle(tmp_path, {"panel.js": (
        "export function mount() { return 'mounted'; }\n"
        "export function declared() { return 'yes'; }\n"
        "export function undeclared() { return 'no'; }\n")})
    result = _run_node(f"""
import {{ collectViewBindings, resolveView, ViewBindingError }}
  from {json.dumps((web / "views" / "view_extension.js").as_uri())};
const bindings = collectViewBindings([{{ views: () => [{{
  id: "panel.one", region: "page-overlay", module: "./views/panel.js",
  entry: "mount", view_class: "B", exports: ["mount", "declared"],
  optional: true }}] }}]);
const resolved = await resolveView(bindings, "panel.one");
const out = {{ mounted: resolved.exports.mount(),
               declared: resolved.exports.declared() }};
try {{ resolved.exports.undeclared(); out.refused = null; }}
catch (e) {{ out.refused = e.name + ": " + e.message; }}
// `in` STILL SEES THE WHOLE NAMESPACE and that is a language constraint,
// not a gap: a module namespace's exports are non-configurable, so a Proxy
// `has` trap may not hide one. The REACH is what refuses, which is what the
// ruling says the defect is.
out.has = ["mount", "declared", "undeclared"].map((k) => k in resolved.exports);
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["mounted"] == "mounted" and result["declared"] == "yes"
    assert result["refused"].startswith("ViewBindingError: ")
    assert "does not declare an export named \"undeclared\"" in result["refused"]
    assert result["has"] == [True, True, True]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_a_declared_export_the_module_lacks_refuses_at_resolve(tmp_path) -> None:
    web = _temp_bundle(tmp_path, {"panel.js": "export function mount() {}\n"})
    result = _run_node(f"""
import {{ collectViewBindings, resolveView }}
  from {json.dumps((web / "views" / "view_extension.js").as_uri())};
const bindings = collectViewBindings([{{ views: () => [{{
  id: "panel.one", region: "page-overlay", module: "./views/panel.js",
  entry: "mount", view_class: "B", exports: ["mount", "missingOne"],
  optional: true }}] }}]);
let refused = null;
try {{ await resolveView(bindings, "panel.one"); }}
catch (e) {{ refused = e.message; }}
console.log(JSON.stringify({{ refused }}));
""", tmp_path)
    assert "declares export \"missingOne\"" in result["refused"]
    assert "must not look registered" in result["refused"]


# ---------------------------------------------------------------------------
# RULED Q4 — `requires`, evaluated
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_an_unmet_requirement_is_an_absence_or_a_refusal(tmp_path) -> None:
    """RULED Q4 (`5648049748`): "`requires` names DOTTED PATHS into the
    `/capabilities` payload; unmet + `optional: true` renders the region empty
    with a NAMED reason; unmet + required REFUSES, naming the binding, the path
    and the probed value"."""
    web = _temp_bundle(tmp_path, {"panel.js": "export function mount() { return 1; }\n"})
    result = _run_node(f"""
import {{ collectViewBindings, resolveView, probeCapabilityPath,
          unmetRequirement }}
  from {json.dumps((web / "views" / "view_extension.js").as_uri())};
const spec = (over) => ({{
  id: "panel.one", region: "page-overlay", module: "./views/panel.js",
  entry: "mount", view_class: "B", requires: ["actions.gate"],
  optional: true, ...over }});
const optional = collectViewBindings([{{ views: () => [spec({{}})] }}]);
const required = collectViewBindings([
  {{ views: () => [spec({{ optional: false }})] }}]);
const live = {{ actions: {{ gate: true }} }};
const off = {{ actions: {{ gate: false }} }};
const out = {{
  path_live: probeCapabilityPath(live, "actions.gate"),
  path_missing: probeCapabilityPath({{ actions: {{}} }}, "actions.gate") ?? null,
  path_through_nothing: probeCapabilityPath(null, "actions.gate") ?? null,
  unmet_off: unmetRequirement(optional[0], off),
  unmet_live: unmetRequirement(optional[0], live),
  optional_off: await resolveView(optional, "panel.one", {{ capabilities: off }}),
}};
out.optional_live = !!(await resolveView(optional, "panel.one",
                                         {{ capabilities: live }}));
try {{
  await resolveView(required, "panel.one", {{ capabilities: off }});
  out.required_off = null;
}} catch (e) {{ out.required_off = e.message; }}
out.required_live = !!(await resolveView(required, "panel.one",
                                         {{ capabilities: live }}));
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["path_live"] is True
    assert result["path_missing"] is None and result["path_through_nothing"] is None
    assert result["unmet_off"] == {"path": "actions.gate", "value": False}
    assert result["unmet_live"] is None
    # OPTIONAL + UNMET: an absence the caller already knows how to read.
    assert result["optional_off"] is None
    assert result["optional_live"] is True
    # REQUIRED + UNMET: a refusal naming the binding, the path and the value.
    assert "panel.one" in result["required_off"]
    assert "actions.gate" in result["required_off"]
    assert result["required_live"] is True


# ---------------------------------------------------------------------------
# RULED Q1 — the generic mount pass
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_the_shell_mounts_contributed_dom_bindings_generically(tmp_path) -> None:
    """RULED Q1 (`5648044785`): "one mount pass over every contributed binding
    whose region is a `dom` region; the three `shell` regions stay
    caller-driven". Before this, a column could contribute a binding and have
    nothing ever call it."""
    web = _temp_bundle(tmp_path, {
        "panel.js": ("export function mount(host, snapshot, ctx) {\n"
                     "  host.mounted = { snapshot, caps: ctx.caps };\n"
                     "  return 'ok';\n}\n"),
    })
    result = _run_node(f"""
import {{ collectViewBindings, mountContributedViews }}
  from {json.dumps((web / "views" / "view_extension.js").as_uri())};
const hosts = {{}};
const made = [];
const doc = {{
  getElementById: (id) => hosts[id] || null,
  createElement: (tag) => {{
    const node = {{ tag, children: [], attrs: {{}}, textContent: "",
                    className: "",
                    setAttribute(k, v) {{ this.attrs[k] = v; }},
                    appendChild(c) {{ this.children.push(c); return c; }} }};
    made.push(node);
    return node;
  }},
}};
for (const id of ["view-docs", "explorer-root"]) {{
  hosts[id] = {{ id, children: [], appendChild(c) {{ this.children.push(c); }} }};
}}
const bindings = collectViewBindings([{{ views: () => [
  // a dom region: the pass mounts it
  {{ id: "panel.one", region: "view-docs", module: "./views/panel.js",
     entry: "mount", view_class: "B", optional: true }},
  // a SHELL region: caller-driven, never touched by the pass
  {{ id: "panel.shell", region: "page-overlay", module: "./views/panel.js",
     entry: "mount", view_class: "B", optional: true }},
  // a dom region with an UNMET optional requirement: empty, with a NAMED reason
  {{ id: "panel.unmet", region: "explorer-root", module: "./views/panel.js",
     entry: "mount", view_class: "B", requires: ["actions.gate"],
     optional: true }},
]}}]);
const results = await mountContributedViews(
  bindings, {{ repository: "r" }}, {{ caps: {{ actions: {{ gate: false }} }} }},
  {{ document: doc, capabilities: {{ actions: {{ gate: false }} }} }});
console.log(JSON.stringify({{
  seen: results.map((r) => [r.binding.id, r.mounted, r.skipped]),
  mounted: hosts["view-docs"].mounted,
  reason: made.map((n) => [n.className, n.attrs["data-view"], n.textContent]),
}}));
""", tmp_path)
    seen = {row[0]: row for row in result["seen"]}
    # the `dom`-region binding mounted, with RULED Q3's signature
    assert seen["panel.one"][1] == "ok" and seen["panel.one"][2] is None
    assert result["mounted"] == {"snapshot": {"repository": "r"},
                                 "caps": {"actions": {"gate": False}}}
    # the `shell`-region binding is not in the pass at all
    assert "panel.shell" not in seen
    # the unmet optional: skipped, with the reason written INTO its region
    assert seen["panel.unmet"][2] == "requires"
    assert result["reason"] == [["viewrefusal", "panel.unmet",
                                 result["reason"][0][2]]]
    assert "panel.unmet" in result["reason"][0][2]
    assert "actions.gate" in result["reason"][0][2]


# ---------------------------------------------------------------------------
# RULED Q8 / Q9 — the regions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("region", NEW_REGIONS)
def test_the_new_regions_are_declared_shell_regions_in_both_halves(region) -> None:
    assert REGIONS.get(region) == "shell", (
        f"{region} is not declared a `shell` region in the Python half")
    assert region not in dom_regions()
    js = REGISTRY_JS.read_text(encoding="utf-8")
    assert f'"{region}": "shell",' in js, (
        f"{region} is missing from the client mirror's REGIONS table; the two "
        "halves are one vocabulary or they are two seams")


def test_the_page_overlay_host_is_built_by_the_shell_not_by_index_html() -> None:
    """RULED Q8 (`5648049748`): "a fourth `shell` region, `page-overlay`, is the
    declared host for page-level panels (dispose.js's refusal panel);
    `document.body` is never a contract surface."

    It is a `shell` region rather than a `dom` one for a floor reason, and the
    reason is worth a test: `src/opendox/web/index.html` is a `moved_verbatim`
    row of openxFactory's carve manifest, whose declared-edit vocabulary is the
    RULED closed list `import rewrites | path constants | adapter calls`, and an
    added element is in none of them. So the shell builds the host.
    """
    app = _app()
    assert 'PAGE_OVERLAY_REGION = "page-overlay"' in app
    assert "function ensurePageOverlayHost(" in app
    assert "ensurePageOverlayHost();" in app
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="page-overlay"' not in index, (
        "index.html grew a `page-overlay` element: that file is a "
        "`moved_verbatim` carve row and an added element is in none of its "
        "declared edit classes")


@pytest.mark.parametrize("region", ["wheel-intent", "dispose-intent"])
def test_the_two_unhosted_regions_stand_declared_and_unread(region) -> None:
    """RULED Q9 (`5648065587`): they "stay DECLARED in both REGIONS tables,
    recorded as unhosted and unread today (S2 landed as
    `views/intent-binding.js`); a future intent panel has its slot."

    S5 is not the slice that retires S2's provision — and a binding naming one
    today would mount into nothing, which is why "unread" is measured rather
    than assumed.
    """
    assert REGIONS.get(region) == "shell"
    assert f'"{region}": "shell",' in REGISTRY_JS.read_text(encoding="utf-8")
    index = (WEB / "index.html").read_text(encoding="utf-8")
    assert f'id="{region}"' not in index, f"{region} grew a host element"
    readers = []
    for path in sorted(p for p in WEB.rglob("*.js") if p.is_file()):
        if path.name == "view_extension.js":
            continue      # the declaration itself
        # CODE, NOT PROSE. `app.js`'s own comment explains why slice S2's chips
        # fold into this registry without re-opening it, and naming a region in
        # a sentence is not reading it.
        code = "\n".join(line for line in
                         path.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("//"))
        if region in code:
            readers.append(path.relative_to(WEB).as_posix())
    assert readers == [], (
        f"{region} is read by {readers}; RULED Q9 records it as unhosted AND "
        "unread, and a reader would make that record false")


# ---------------------------------------------------------------------------
# RULED Q11 — what a human sees when the registry refuses
# ---------------------------------------------------------------------------

def test_a_registry_refusal_is_not_framed_as_a_snapshot_defect() -> None:
    """RULED Q11 (`5648065587`). The seam already composed the right sentence;
    only the frame around it was wrong — every `ViewBindingError` was reported
    as "Could not load the snapshot (…) regenerate it and reload", so a column
    debugging its own contribution was told to regenerate a snapshot that is
    fine."""
    app = _app()
    assert "err instanceof ViewBindingError" in app
    assert 'err.name === "ViewBindingError"' in app, (
        "the name check is the cross-realm half: a refusal raised in a worker "
        "or a harness does not satisfy `instanceof`")
    assert "The snapshot is fine — the assembly is not" in app
    # the snapshot frame SURVIVES for everything that is not a registry refusal
    assert "Could not load the snapshot (" in app
    assert "ViewBindingError" in re.search(
        r"\} catch \(err\) \{(.*?)\n  \}", app, re.S).group(1)


# ---------------------------------------------------------------------------
# The seam, assembled — the Python half
# ---------------------------------------------------------------------------

def test_the_manifest_carries_the_declared_namespace_across_the_boundary() -> None:
    binding = ViewBinding(
        id="gate.dispose", region="page-overlay", module="./views/dispose.js",
        entry="mountRefusalPanel", view_class="B",
        routes=("/actions/gate/dispose-possible", "/actions/gate/demote"),
        exports=("mountRefusalPanel", "panelEntry"),
        requires=("actions.gate",), optional=True)
    manifest = view_manifest(collect_view_bindings([type("X", (), {
        "views": lambda self: (binding,)})()]), host_facet="declared",
        host_profile="openxdox")
    entry = manifest["views"][0]
    assert entry["exports"] == ["mountRefusalPanel", "panelEntry"]
    assert entry["requires"] == ["actions.gate"]
    assert entry["routes"] == ["/actions/gate/dispose-possible",
                               "/actions/gate/demote"]
    assert manifest["regions"]["page-overlay"] == "shell"


def test_the_serve_publishes_the_manifest_on_capabilities() -> None:
    """The ONE line slice S3 built both ends of and deliberately did not write:
    `opendox/view_extension.py` — "The ONE line that puts it there
    (`capabilities["views"] = view_manifest(...)` in `serve.build_server`) is
    NOT written by slice S3 ... S5, the slice at which a contribution first
    EXISTS to deliver, joins them."""
    serve = (ROOT / "src" / "opendox" / "serve.py").read_text(encoding="utf-8")
    assert 'capabilities["views"] = view_extension.view_manifest(' in serve
    assert "view_extension.host_view_extensions(profile_openxfactory)" in serve
    assert "view_extension.collect_view_bindings(" in serve
    # the SAME contributed routes the server was assembled with, so both halves
    # of the seam check § 2.2 rule 1 against the same facts
    assert "contributed_routes=route_bindings" in serve


def test_the_census_totals_and_the_class_b_remainder() -> None:
    """After S5 exactly ONE class-B file is left in this bundle, and it is not
    the gate loop's: `views/projection-index.js` is openXdox's PROJECTION
    column's one read, which slice S6 re-homes."""
    census = yaml.safe_load(CENSUS_PATH.read_text(encoding="utf-8"))
    class_b = sorted(row["path"] for row in census["files"]
                     if row["class"] == "B")
    assert class_b == ["views/projection-index.js"], class_b
    assert census["totals"]["B"]["files"] == 1


# ---------------------------------------------------------------------------
# RULED counterpart Q6 — the SHELL's half: what a contributed module may not
# import, the shell hands it.
#
# RULED counterpart Q6 (opensoft/openxFactory#656 comment `5649094228`, Brett
# Heap, 2026-09-12): "what a CONTRIBUTED view module may IMPORT from openDox's
# bundle: `./views/helpers.js` and NOTHING ELSE. Every other need reaches the
# binding through its `ctx` (Q1-Q4) or its own package (Q5)."
#
# The bindings enforce the rule on openXdox's side. THIS side has the other
# obligation: every name the four modules used to import statically has to
# arrive on the ctx the shell composes, or the rule turns a working affordance
# into a refusal. Each assertion below names the site that supplies it.
# ---------------------------------------------------------------------------

def test_the_shell_hands_the_lens_gate_the_model_it_no_longer_imports() -> None:
    """`views/gate-lens.js` imported `{ clusterRequest, recipeRequest }` from
    `views/lens-model.js`. It is openXdox's package data now, so the adapter
    that composes its context supplies the model namespace instead — in
    `app.js`, where the binding's context is already being built, so
    `views/lens.js` (which builds `lctx`) needs no change at all."""
    app = _app()
    assert 'import * as lensModel from "./views/lens-model.js";' in app
    assert re.search(
        r"mountLensGate: lensGateView\s*\n\s*\? \(host, lctx\) =>\s*\n\s*"
        r"lensGateView\.exports\[lensGateView\.binding\.entry\]\(\s*\n\s*"
        r"host, snapshot, \{ \.\.\.lctx, model: lensModel \}\)", app), app


def test_the_shell_hands_the_workbench_column_the_model_it_no_longer_imports() -> None:
    """`views/swb-create.js` and `views/swb-session.js` took five and nine names
    from `views/staging-workbench-model.js`. The overlay that mounts them hands
    the namespace down at every call site that carries a ctx, and `app.js` hands
    it to `firstEditTransport` — RULED Q10's non-mount export, reached through
    the registry, whose ctx is the options object it already takes."""
    workbench = (VIEWS / "staging-workbench.js").read_text(encoding="utf-8")
    assert ('import * as workbenchModel from "./staging-workbench-model.js";'
            in workbench)
    # the create column's shared options builder, the session mount, and the
    # doxBench create dialog's own literal context
    assert workbench.count("model: workbenchModel,") == 3, workbench.count(
        "model: workbenchModel,")
    app = _app()
    assert ('import * as workbenchModel from "./views/staging-workbench-model.js";'
            in app)
    assert "{ caps, repair: consoleRepair, model: workbenchModel }" in app


def test_the_shell_hands_the_dispose_tray_the_intent_transport() -> None:
    """`views/dispose.js` imported `{ emitIntent, renderIntentChips }` from
    `views/intent-binding.js` and fell back to `emitIntent` when the hosted
    context carried no emitter. A fallback into a module a contributed binding
    may not import is a refusal, not a default, so `views/wheel.js` — which
    starts the feed and builds the hosted context — supplies both."""
    wheel = (VIEWS / "wheel.js").read_text(encoding="utf-8")
    assert re.search(r"import \{ emitIntent, feedActor, intentCapable, "
                     r"refusalLine, renderIntentChips,\s*\n\s*startIntentFeed, "
                     r'statesByTarget \}\s*\n\s*from "\./intent-binding\.js";',
                     wheel), wheel
    assert "emit: emitIntent," in wheel
    assert "renderChips: renderIntentChips," in wheel


def test_no_shell_file_reaches_into_the_contributed_column_to_supply_it() -> None:
    """The shell supplies the contributed column through ctx and NEVER by
    importing one of the six modules back — that would be § 4.5 assertion 3's
    breach reopened from the other side, one slice after it closed."""
    gone = ("gate.js", "dispose.js", "swb-create.js", "swb-session.js",
            "gate-lens.js", "gate-projects.js")
    for path in [APP_JS, *sorted(VIEWS.glob("*.js"))]:
        text = path.read_text(encoding="utf-8")
        for module in gone:
            assert not re.search(rf'^import .*from "\./(?:views/)?{re.escape(module)}"',
                                 text, re.M), (path.name, module)


def test_the_shell_mounts_the_page_overlay_binding_it_builds_the_host_for() -> None:
    """RULED Q8's region is a `shell` region, so RULED Q1's generic pass SKIPS
    it and the caller that builds the host must mount into it. Building the host
    and never calling the binding's entry left the contributed `views/dispose.js`
    with no `panelHost`, and its `ensurePanel()` REFUSES rather than falling back
    to `document.body` (which Q8 forbids) — so the first refused gate verb on a
    composed install would have THROWN instead of showing its refusal. Copilot
    review round 1 found it; this holds it."""
    app = _app()
    assert "const pageOverlayHost = ensurePageOverlayHost();" in app
    assert re.search(
        r"if \(disposeView\) \{\s*\n\s*disposeView\.exports\[disposeView\.binding\.entry\]\(\s*\n"
        r"\s*pageOverlayHost, snapshot, \{ caps \}\);", app), app
