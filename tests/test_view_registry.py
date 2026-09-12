"""The VIEW REGISTRY — § 3.4 slice S3, both halves of it.

The boundary note (openDox-spec `docs/front-end-package-boundary.md` § 4.1,
landed at `a44ac06d`) asks slice S3 for `ViewBinding` + `collectViewBindings`
"on the § 2.4 / § 4.3 seams", with "collision + empty-tuple refusal tests". This
suite is those tests and four more, because a seam that is only described is the
thing the note's own § 1.2(d) is about: 48 test files across two repositories
that do not run.

WHAT IT HOLDS, and why each is here rather than implied:

1. A BINDING IS REFUSED WHERE IT IS DECLARED. `RouteBinding.__post_init__`'s
   discipline: a binding is declared once at assembly time and consulted on
   every render, so the cheap place to find a malformed one is the first. Each
   refusal is asserted on its MESSAGE as well as its type — a refusal whose text
   does not name the fix is a stack trace with extra steps
   (`test_profile_registration.py`'s own rule).
2. TWO BINDINGS IN ONE SLOT REFUSE. The note's exact analogue of
   `collect_bindings`' collision: *"a declared route silently unreachable"*
   becomes *"a declared panel silently unmounted"*.
3. THE EMPTY CONSUMER COLUMN RENDERS THE CORE ALONE. The note's S3 row in its
   own words — "nothing is contributed yet, so the shell renders exactly as
   today with an empty extension tuple" — and it is a POSITIVE assertion, not an
   absence: the core arm must come through the collection unchanged.
4. A CLASS-A BINDING DECLARING A GATE ROUTE IS REFUSED, AND A CLASS-B ONE IS
   NOT. RULED Q3 (openxFactory#656 comment `5642758731`): "a route constant
   travels with the binding that calls it, never with the model that happens to
   declare it", with § 4.5 assertion 2's scope — class B is exempt by
   construction, the transitional `?` is in scope.
5. THE PROFILE FACET IS THE SAME COMPOSITE PROFILE'S. `VIEW_EXTENSIONS` comes
   off the ONE registration through the SAME lazy proxy as `ROUTE_EXTENSIONS`
   and `SUBCOMMAND_EXTENSIONS` (RULED ASK-2 option (2), comment `5628886636`),
   with the two absences answered differently and both on the record: NO HOST
   refuses, NO FACET yields an empty column that the manifest NAMES.
6. THE THREE DECLARATIONS OF THE REGION SET AGREE. `view_extension.py`'s
   `REGIONS`, `views/view_extension.js`'s `REGIONS`, and `index.html`'s
   `data-region` attributes are one fact written three times, so a drift test is
   the only thing that keeps them one fact. The shape openxFactory's
   `carved_reach.py` scrub-list drift test already uses.
7. THE SHELL NO LONGER IMPORTS A CLASS-B MODULE. § 4.1's own sentence — "app.js
   stops importing class-B modules directly" — asserted against the file rather
   than promised in a commit message.
8. THE CLIENT HALF ACTUALLY RUNS. The JavaScript assertions drive the REAL
   `views/view_extension.js` under node, against the REAL `views/docs.js` for the
   class-A view this slice wires end to end, and against a fixture panel in a
   temp bundle for the contributed-and-mounted path. Nothing here reads a
   module's source and calls that a behaviour test — `test_wheel_verbs_dom.py`'s
   rule, and the reason it is worth the subprocess.

`--noconftest` SAFE, deliberately: `validate` runs this file in the explicit
list with conftest collection off (RULED Q-L5 (b')), so nothing here may need a
fixture, a path insertion or an installed consumer. `ROOT` is computed from
`__file__` for that reason and the package is importable because the workflow
installs it (`pip install -e ".[test]"`).

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from opendox import domain_profile, profile_proxy, view_extension
from opendox.view_extension import (
    MANIFEST_KIND,
    MANIFEST_SCHEMA_VERSION,
    REGIONS,
    VIEW_CLASSES,
    ViewBinding,
    ViewBindingError,
    collect_view_bindings,
    dom_regions,
    host_view_extensions,
    view_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
REGISTRY_JS = WEB / "views" / "view_extension.js"
APP_JS = WEB / "app.js"
INDEX_HTML = WEB / "index.html"
NODE = shutil.which("node")


# --------------------------------------------------------------------------
# helpers


class _Extension:
    """A view extension, structurally. Never a subclass of anything here — the
    whole point of `runtime_checkable` is that the column which PINS openDox
    conforms without importing from it."""

    def __init__(self, *bindings: ViewBinding) -> None:
        self._bindings = bindings

    def views(self) -> tuple[ViewBinding, ...]:
        return self._bindings


class _Route:
    """A contributed `RouteBinding`, at the three fields the ownership check
    reads. Deliberately not `route_extension.RouteBinding`: the client half
    reads these same three fields out of JSON, and holding both halves to one
    structural rule is the point."""

    def __init__(self, pattern: str, is_prefix: bool = False,
                 method: str = "POST") -> None:
        self.pattern = pattern
        self.is_prefix = is_prefix
        self.method = method


def _binding(**over) -> ViewBinding:
    spec = dict(id="docs.list", region="view-docs", module="./views/docs.js",
                entry="renderDocs", view_class="A")
    spec.update(over)
    return ViewBinding(**spec)


def _run_node(source: str, cwd: Path) -> dict:
    """Run an ES-module harness and return the ONE JSON object it prints."""
    script = cwd / "harness.mjs"
    script.write_text(source, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _temp_bundle(tmp_path: Path) -> Path:
    """A throwaway `web/` carrying a byte-identical copy of the registry.

    The registry resolves a binding's module against the BUNDLE ROOT, so a
    fixture panel has to live in a bundle. Copying rather than writing a fixture
    module into `src/opendox/web/views/` keeps the real bundle exactly the set
    of files the census counts — § 4.5 assertion 1 fails an unrowed file, and a
    test fixture would be one.
    """
    web = tmp_path / "web"
    (web / "views").mkdir(parents=True)
    copied = web / "views" / "view_extension.js"
    copied.write_bytes(REGISTRY_JS.read_bytes())
    assert copied.read_bytes() == REGISTRY_JS.read_bytes()
    return web


# --------------------------------------------------------------------------
# 1. a binding is refused where it is DECLARED


@pytest.mark.parametrize("over,fragment", [
    ({"id": "Docs List"}, "dotted lowercase slug"),
    ({"id": ""}, "dotted lowercase slug"),
    ({"region": "view-nowhere"}, "which the shell does not declare"),
    ({"module": "https://cdn.example/panel.js"}, "vendor"),
    ({"module": "/views/docs.js"}, "bundle-relative"),
    ({"module": "./../../etc/passwd.js"}, "climbs out of the bundle"),
    ({"entry": "not an identifier"}, "the NAME of an export"),
    ({"entry": "__proto__"}, "dunder"),
    ({"view_class": "D"}, "not one of"),
    ({"routes": ("actions/gate/ratify",)}, "rooted at '/'"),
    ({"routes": ["/actions/gate/ratify"]}, "not a tuple"),
    ({"requires": ("",)}, "not a capability or facet name"),
    ({"optional": "yes"}, "not a bool"),
])
def test_a_malformed_binding_refuses_and_the_message_says_why(over, fragment):
    with pytest.raises(ViewBindingError) as excinfo:
        _binding(**over)
    assert fragment in str(excinfo.value)


@pytest.mark.parametrize("field,value", [
    ("region", ["view-docs"]),          # a list: unhashable
    ("region", {"view-docs": 1}),       # a dict: unhashable
    ("view_class", ["A"]),
])
def test_a_declaration_defect_refuses_even_when_the_value_is_unhashable(
        field, value):
    # THE REFUSAL MUST NOT DEPEND ON THE TYPE OF WHAT IT REFUSES. `REGIONS` is a
    # dict, so `<unhashable> not in REGIONS` raises `TypeError` out of the hash
    # BEFORE the `ViewBindingError` this module promises for every declaration
    # defect — a caller written to catch the one refusal class would see an
    # exception it never agreed to handle. Copilot found this on PR #14; the
    # guard is an `isinstance` before every membership test, and this is the
    # test that keeps it there.
    with pytest.raises(ViewBindingError):
        _binding(**{field: value})


def test_a_well_formed_binding_is_frozen_and_carries_its_slot():
    binding = _binding()
    assert binding.slot == ("view-docs", "docs.list")
    with pytest.raises(Exception):
        binding.id = "other"          # frozen dataclass


@pytest.mark.parametrize("entry", ["$mount", "_mount", "mount$panel"])
def test_the_entry_grammar_accepts_what_the_js_client_accepts(entry):
    # Copilot, PR #14: `str.isidentifier()` accepts Unicode names the browser's
    # ASCII-only regex refuses, and rejects `$`-bearing ASCII names
    # `views/view_extension.js`'s `viewBinding()` accepts — so a binding could
    # be published here and refused there, or refused here and never published
    # at all for a name the client would have happily loaded. `$mount` is
    # accepted by JS `[A-Za-z_$][A-Za-z0-9_$]*` and rejected by
    # `"$mount".isidentifier()`; this asserts the PYTHON side now agrees.
    assert _binding(entry=entry).entry == entry


def test_the_entry_grammar_refuses_what_the_js_client_refuses():
    # `"café"` IS a valid Python identifier (accented Unicode letters are
    # allowed) and is NOT matched by the client's ASCII-only
    # `/^[A-Za-z_$][A-Za-z0-9_$]*$/` — the other half of the same drift.
    assert "café".isidentifier()
    with pytest.raises(ViewBindingError) as excinfo:
        _binding(entry="café")
    assert "the NAME of an export" in str(excinfo.value)


def test_the_manifest_entry_is_json_and_drops_nothing():
    entry = _binding(routes=("/actions/gate/ratify",), optional=True,
                     view_class="B", region="viewer-gatebar",
                     id="gate.bar", module="./views/gate.js",
                     entry="mountGateBar").as_manifest_entry()
    assert json.loads(json.dumps(entry)) == entry
    assert entry["routes"] == ["/actions/gate/ratify"]
    assert entry["optional"] is True


# --------------------------------------------------------------------------
# 2. collection: conformance, collision, and the empty consumer column


def test_a_non_conforming_extension_refuses_and_names_the_member():
    class NotAnExtension:
        pass

    with pytest.raises(ViewBindingError) as excinfo:
        collect_view_bindings([NotAnExtension()])
    assert "does not conform to ViewExtension" in str(excinfo.value)
    assert "views" in str(excinfo.value)


def test_an_extension_contributing_something_else_refuses():
    class Wrong:
        def views(self):
            return ({"id": "docs.list"},)

    with pytest.raises(ViewBindingError) as excinfo:
        collect_view_bindings([Wrong()])
    assert "not a ViewBinding" in str(excinfo.value)


def test_a_views_member_that_is_not_callable_refuses_rather_than_raising_typeerror():
    # `isinstance(extension, ViewExtension)` is a `runtime_checkable` Protocol
    # check, which verifies only that the NAME `views` exists — never that it
    # is callable (Copilot, PR #14). Before this test's fix, `views = 1` passed
    # that check and then raised a raw `'int' object is not callable`
    # `TypeError` two lines later, never the `ViewBindingError` this module
    # promises for every declaration defect.
    class NotCallable:
        views = 1

    with pytest.raises(ViewBindingError) as excinfo:
        collect_view_bindings([NotCallable()])
    assert "not callable" in str(excinfo.value)


@pytest.mark.parametrize("returned", [None, 42, iter(())])
def test_a_views_call_that_returns_something_unusable_refuses(returned):
    # The Protocol promises `tuple[ViewBinding, ...]`; before this test's fix,
    # `views()` returning `None` raised a raw `'NoneType' object is not
    # iterable` `TypeError` at the `for binding in declared:` loop (Copilot,
    # PR #14, same finding as the callable check above — a member existing is
    # not a member behaving). A bare iterator is refused too, not accepted:
    # this module walks it once for validation, and an extension consulted
    # again later would see it already exhausted.
    class Unusable:
        def views(self):
            return returned

    with pytest.raises(ViewBindingError) as excinfo:
        collect_view_bindings([Unusable()])
    assert "views()" in str(excinfo.value)


def test_two_bindings_in_one_slot_refuse_and_name_both_modules():
    core = _Extension(_binding())
    rival = _Extension(_binding(module="./views/doc-wheel.js",
                                entry="renderDocWheel"))
    with pytest.raises(ViewBindingError) as excinfo:
        collect_view_bindings([core, rival])
    message = str(excinfo.value)
    assert "two view bindings claim region" in message
    assert "./views/docs.js" in message and "./views/doc-wheel.js" in message
    assert "never renders" in message


def test_one_id_in_two_different_regions_is_not_a_collision():
    # The slot is (region, id), exactly as `RouteBinding.key` is
    # (method, pattern, is_prefix) and never the handler. Two regions showing
    # the same panel is a layout, not a defect.
    both = _Extension(_binding(), _binding(region="view-lineage"))
    assert len(collect_view_bindings([both])) == 2


def test_the_core_arm_comes_through_an_empty_consumer_column_unchanged():
    core = (_binding(), _binding(id="lineage.readiness", region="view-lineage",
                                 module="./views/lineage.js",
                                 entry="renderLineage", view_class="C"))
    collected = collect_view_bindings(
        [_Extension(*core), _Extension()], contributed_routes=())
    assert collected == core           # order AND identity, not just a count


def test_collecting_nothing_at_all_is_an_empty_tuple_not_a_refusal():
    # The static served image's case, and every host before slice S5.
    assert collect_view_bindings([]) == ()
    assert collect_view_bindings([_Extension()]) == ()


# --------------------------------------------------------------------------
# 4. RULED Q3 — a route travels with the binding that calls it


GATE_PREFIX = _Route("/actions/gate/", is_prefix=True)


def test_a_class_a_binding_declaring_a_gate_route_is_refused():
    binding = _binding(routes=("/actions/gate/ratify",))
    with pytest.raises(ViewBindingError) as excinfo:
        collect_view_bindings([_Extension(binding)],
                              contributed_routes=(GATE_PREFIX,))
    message = str(excinfo.value)
    assert "/actions/gate/" in message
    assert "5642758731" in message                      # the ruling, cited
    assert "BINDING THAT CALLS IT" in message


@pytest.mark.parametrize("view_class", ["C", "?"])
def test_class_c_and_the_transitional_class_are_in_scope_too(view_class):
    # § 4.5 assertion 2: "class A, class C AND the transitional `?`, which is
    # where most of the breaches actually sit".
    binding = _binding(view_class=view_class,
                       routes=("/actions/gate/ratify",))
    with pytest.raises(ViewBindingError):
        collect_view_bindings([_Extension(binding)],
                              contributed_routes=(GATE_PREFIX,))


def test_a_class_b_binding_declaring_the_same_route_is_allowed():
    # "Class B is exempt by construction: a gate-loop file naming a gate route
    # is the boundary working."
    binding = _binding(id="gate.bar", region="viewer-gatebar",
                       module="./views/gate.js", entry="mountGateBar",
                       view_class="B", routes=("/actions/gate/ratify",),
                       optional=True)
    assert collect_view_bindings([_Extension(binding)],
                                 contributed_routes=(GATE_PREFIX,)) == (binding,)


def test_an_exact_contributed_route_is_matched_exactly():
    index = _Route("/snapshot-index.json", is_prefix=False, method="GET")
    ok = _binding(routes=("/snapshot-index.jsonl",))
    assert collect_view_bindings([_Extension(ok)], contributed_routes=(index,))
    breach = _binding(routes=("/snapshot-index.json",))
    with pytest.raises(ViewBindingError):
        collect_view_bindings([_Extension(breach)], contributed_routes=(index,))


def test_with_no_contributed_routes_nothing_can_breach():
    # Slice S3's own case: no column has claimed a route, so the check is a
    # no-op because there is nothing to breach — not because it passed.
    binding = _binding(routes=("/actions/gate/ratify",))
    assert collect_view_bindings([_Extension(binding)]) == (binding,)


def test_a_contributed_route_without_a_pattern_refuses():
    class Malformed:
        is_prefix = False

    with pytest.raises(ViewBindingError) as excinfo:
        collect_view_bindings([_Extension(_binding(routes=("/x",)))],
                              contributed_routes=(Malformed(),))
    assert "carries no string pattern" in str(excinfo.value)


# --------------------------------------------------------------------------
# 5. the profile facet — one registration, one proxy, three facets


class _HostProfile:
    """What a host registers. Not a `DomainProfile` and not typed: openDox
    type-checks nothing and names only the attributes it reads."""

    SUBCOMMAND_EXTENSIONS = ("the host's subcommands",)
    ROUTE_EXTENSIONS = ("the host's routes",)
    VIEW_EXTENSIONS = ("the host's views",)


class _ProfileWithoutTheFacet:
    SUBCOMMAND_EXTENSIONS = ("the host's subcommands",)
    ROUTE_EXTENSIONS = ("the host's routes",)


@pytest.fixture
def registered():
    """Register, yield the proxy, and ALWAYS unregister.

    `domain_profile` holds ONE registration for the process and refuses a
    second, so a test that left one behind would fail its neighbours rather
    than itself.
    """
    def _register(profile):
        domain_profile.register(profile)
        return profile_proxy.profile_openxfactory

    try:
        yield _register
    finally:
        if domain_profile.is_registered():
            domain_profile.unregister()


def test_the_facet_comes_off_the_one_registered_profile(registered):
    proxy = registered(_HostProfile())
    assert host_view_extensions(proxy) == ("the host's views",)
    # ...and it is the SAME object the other two facets come off: one
    # registration, three facets (RULED ASK-2 option (2)).
    assert proxy.ROUTE_EXTENSIONS == ("the host's routes",)
    assert proxy.SUBCOMMAND_EXTENSIONS == ("the host's subcommands",)


def test_a_host_without_the_facet_contributes_an_empty_column(registered):
    proxy = registered(_ProfileWithoutTheFacet())
    assert host_view_extensions(proxy) == ()


def test_no_host_at_all_refuses_rather_than_answering_empty():
    assert not domain_profile.is_registered()
    with pytest.raises(domain_profile.ProfileNotRegistered) as excinfo:
        host_view_extensions(profile_proxy.profile_openxfactory)
    assert domain_profile.REGISTRATION_CALL in str(excinfo.value)


def test_importing_the_registry_resolves_no_profile():
    # The lazy proxy's whole value: importing cannot fail for want of a host.
    # A SUBPROCESS, because this process may have registered one.
    proc = subprocess.run(
        [sys.executable, "-c",
         "import opendox.view_extension as v;"
         "from opendox import domain_profile as d;"
         "print(d.is_registered())"],
        capture_output=True, text=True, timeout=120,
        cwd=str(ROOT), env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


# --------------------------------------------------------------------------
# the manifest — the one crossing of the process boundary


def test_the_manifest_declares_its_schema_and_names_the_absence():
    manifest = view_manifest([_binding()], contributed_routes=(GATE_PREFIX,),
                             host_facet="absent", host_profile="a host")
    assert manifest["kind"] == MANIFEST_KIND
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["facet"] == view_extension.PROFILE_FACET
    assert manifest["host_facet"] == "absent"
    assert manifest["host_profile"] == "a host"
    assert manifest["contributed_routes"] == [
        {"method": "POST", "pattern": "/actions/gate/", "is_prefix": True}]
    assert [v["id"] for v in manifest["views"]] == ["docs.list"]
    assert json.loads(json.dumps(manifest)) == manifest


def test_a_third_answer_about_the_absence_refuses():
    with pytest.raises(ViewBindingError) as excinfo:
        view_manifest([], host_facet="maybe")
    assert "'declared' or 'absent'" in str(excinfo.value)


# --------------------------------------------------------------------------
# 6. one region set, written three times


def _js_object_keys(name: str) -> list[str]:
    source = REGISTRY_JS.read_text(encoding="utf-8")
    match = re.search(r"export const " + name + r" = \{(.*?)\n\};",
                      source, re.S)
    assert match, f"{name} not found in {REGISTRY_JS}"
    return re.findall(r'"([^"]+)":', match.group(1))


def _js_array(name: str) -> list[str]:
    source = REGISTRY_JS.read_text(encoding="utf-8")
    match = re.search(r"export const " + name + r" = \[(.*?)\];", source, re.S)
    assert match, f"{name} not found in {REGISTRY_JS}"
    return re.findall(r'"([^"]*)"', match.group(1))


def test_the_two_halves_declare_the_same_regions_in_the_same_order():
    assert _js_object_keys("REGIONS") == list(REGIONS)


def test_the_two_halves_declare_the_same_classes():
    assert _js_array("VIEW_CLASSES") == list(VIEW_CLASSES)


def test_neither_half_carries_a_control_character_a_separator_needs_escaped():
    # A REAL DEFECT, caught in review of this slice and kept as a test rather
    # than a memory: the client's slot key is `region + "\u0000" + id`, and the
    # separator was first typed as a LITERAL NUL byte into the source. The file
    # still parsed and every assertion here still passed — but `git`, `grep`,
    # `file(1)` and every diff viewer classify a file with a NUL as BINARY, so
    # the module would have arrived in review as an unreadable blob and stayed
    # that way. A separator that cannot appear in a region or an id is right;
    # spelling it as a raw byte is not. The check is over BYTES, because reading
    # the file as text is exactly what hides this.
    for path in (REGISTRY_JS, APP_JS):
        data = path.read_bytes()
        data.decode("utf-8")  # a decode error IS the finding
        stray = sorted({b for b in data if b < 0x20 and b not in (0x09, 0x0A)})
        assert stray == [], (
            f"{path.name} carries control byte(s) {stray} inline; a control "
            "character a string needs is written as an escape (\\u0000), never "
            "as the byte itself")


def test_every_dom_region_is_an_element_the_shell_declares():
    # A "dom" region is an element of `index.html` whose id IS the region name.
    # The id is the shell's declaration and this is what makes it a contract;
    # `index.html` itself is not edited to repeat it (see `REGIONS`' own note on
    # why an added attribute has no declared edit class).
    html = INDEX_HTML.read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "an element id declared twice"
    missing = [name for name in dom_regions() if name not in ids]
    assert missing == [], f"regions with no element in index.html: {missing}"


def test_no_shell_region_pretends_to_have_an_element():
    html = INDEX_HTML.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    for name, kind in REGIONS.items():
        if kind == "shell":
            assert name not in ids, (
                f"{name} is declared a shell region but the shell carries an "
                "element of that id; one of the two declarations is wrong")


def test_every_core_tab_binding_names_a_dom_region():
    # The tab router calls `document.getElementById(binding.region)`, so a core
    # tab binding whose region is not a shell element would be a blank tab.
    source = APP_JS.read_text(encoding="utf-8")
    regions = re.findall(r'control: "tab-[a-z]+", region: "([^"]+)"', source)
    assert regions == [r for r in dom_regions() if r.startswith("view-")]


# --------------------------------------------------------------------------
# 7. the shell no longer imports a class-B module


def test_app_js_no_longer_imports_the_gate_module():
    # § 4.1: "app.js stops importing class-B modules directly."
    source = APP_JS.read_text(encoding="utf-8")
    # `[^;]*?` keeps the match inside ONE statement, so a multi-line named
    # import is read and two adjacent statements are never spliced into one.
    imports = re.findall(r'^import\s[^;]*?from\s+"([^"]+)";', source,
                         re.M | re.S)
    assert "./views/gate.js" not in imports
    assert "./views/view_extension.js" in imports


def test_app_js_declares_the_gate_bar_as_an_optional_class_b_binding():
    source = APP_JS.read_text(encoding="utf-8")
    assert 'id: "gate.bar"' in source
    assert 'module: "./views/gate.js", entry: "mountGateBar", view_class: "B"' in source
    assert 'routes: ["/actions/gate/ratify"]' in source
    assert "optional: true" in source


def test_app_js_wires_the_doc_list_through_the_registry():
    # The ONE view this slice wires end to end: the class-A doc list.
    source = APP_JS.read_text(encoding="utf-8")
    assert ('{ id: "docs.list", control: "tab-docs", region: "view-docs",'
            in source)
    assert 'module: "./views/docs.js", entry: "renderDocs", view_class: "A",' in source


# --------------------------------------------------------------------------
# 8. the client half, executed


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_collects_the_core_arm_with_an_empty_consumer_column(tmp_path):
    result = _run_node(f"""
import {{ collectViewBindings, contributedViewBindings }}
  from {json.dumps(REGISTRY_JS.as_uri())};
const core = {{ views: () => [
  {{ id: "docs.list", control: "tab-docs", region: "view-docs",
     module: "./views/docs.js", entry: "renderDocs", view_class: "A",
     mount: () => null }},
] }};
const views = collectViewBindings(
  [core, {{ views: () => contributedViewBindings({{}}) }}]);
console.log(JSON.stringify({{ ids: views.map((v) => v.id),
                              tabs: views.filter((v) => v.control).length }}));
""", tmp_path)
    assert result == {"ids": ["docs.list"], "tabs": 1}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_refuses_a_slot_collision_and_a_contributed_gate_route(tmp_path):
    result = _run_node(f"""
import {{ collectViewBindings }} from {json.dumps(REGISTRY_JS.as_uri())};
const spec = {{ id: "docs.list", region: "view-docs",
                module: "./views/docs.js", entry: "renderDocs",
                view_class: "A" }};
const out = {{}};
try {{
  collectViewBindings([{{ views: () => [spec] }},
                       {{ views: () => [{{ ...spec, module: "./views/x.js" }}] }}]);
  out.collision = "not refused";
}} catch (e) {{ out.collision = e.name; out.collisionMessage = e.message; }}
try {{
  collectViewBindings([{{ views: () => [{{ ...spec,
    routes: ["/actions/gate/ratify"] }}] }}],
    {{ contributedRoutes: [{{ pattern: "/actions/gate/", is_prefix: true }}] }});
  out.q3 = "not refused";
}} catch (e) {{ out.q3 = e.name; out.q3Message = e.message; }}
try {{
  collectViewBindings([{{ views: () => [{{ ...spec, view_class: "B",
    routes: ["/actions/gate/ratify"] }}] }}],
    {{ contributedRoutes: [{{ pattern: "/actions/gate/", is_prefix: true }}] }});
  out.classB = "allowed";
}} catch (e) {{ out.classB = e.name; }}
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["collision"] == "ViewBindingError"
    assert "never renders" in result["collisionMessage"]
    assert result["q3"] == "ViewBindingError"
    assert "5642758731" in result["q3Message"]
    assert result["classB"] == "allowed"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_refuses_a_malformed_capabilities_manifest(tmp_path):
    result = _run_node(f"""
import {{ contributedViewBindings }} from {json.dumps(REGISTRY_JS.as_uri())};
const out = {{}};
out.absent = contributedViewBindings({{}}).length;
out.nullCaps = contributedViewBindings(null).length;
for (const [name, payload] of [
  ["wrongKind", {{ kind: "something-else", schema_version: 1, views: [] }}],
  ["wrongVersion", {{ kind: "opendox.view-manifest", schema_version: 99,
                      views: [] }}],
  ["noViews", {{ kind: "opendox.view-manifest", schema_version: 1 }}],
]) {{
  try {{ contributedViewBindings({{ views: payload }}); out[name] = "not refused"; }}
  catch (e) {{ out[name] = e.name; }}
}}
console.log(JSON.stringify(out));
""", tmp_path)
    assert result == {"absent": 0, "nullCaps": 0, "wrongKind": "ViewBindingError",
                      "wrongVersion": "ViewBindingError",
                      "noViews": "ViewBindingError"}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_manifest_routes_refuses_a_malformed_contributed_routes_field(tmp_path):
    # `view_manifest()` always emits `contributed_routes` as an array
    # (`view_extension.py::view_manifest`); before this test's fix, a PRESENT
    # manifest carrying anything else there was read back as `[]` here --
    # silently disabling every binding's § 2.2 rule 1 ownership check rather
    # than refusing a payload this seam cannot reason about (Copilot, PR #14).
    # ABSENCE of the whole manifest still means an empty column, not a
    # refusal -- `contributedViewBindings`'s own rule, held here too.
    result = _run_node(f"""
import {{ manifestRoutes }} from {json.dumps(REGISTRY_JS.as_uri())};
const out = {{}};
out.absent = manifestRoutes({{}}).length;
out.nullCaps = manifestRoutes(null).length;
out.valid = manifestRoutes(
  {{ views: {{ contributed_routes: [{{ pattern: "/x", is_prefix: false }}] }} }}
).length;
for (const [name, routes] of [
  ["string", "/actions/gate/"],
  ["object", {{ pattern: "/x" }}],
  ["missing", undefined],
]) {{
  try {{
    manifestRoutes({{ views: {{ contributed_routes: routes }} }});
    out[name] = "not refused";
  }} catch (e) {{ out[name] = e.name; out[name + "Message"] = e.message; }}
}}
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["absent"] == 0
    assert result["nullCaps"] == 0
    assert result["valid"] == 1
    assert result["string"] == "ViewBindingError"
    assert result["object"] == "ViewBindingError"
    assert result["missing"] == "ViewBindingError"
    assert "contributed_routes" in result["stringMessage"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_refuses_a_contributed_entry_carrying_the_core_arms_own_fields(
        tmp_path):
    # `mount` and `control` ARE THE CORE ARM'S. A contributed entry arrives as
    # JSON and cannot carry a function, so a manifest declaring `control` would
    # put an entry in the TAB STRIP whose `mount` is `undefined` — the tab
    # renders, and the click that selects it throws. Copilot found this on
    # PR #14. `view_manifest()` emits neither field, so no honest payload is
    # refused by this; a payload that carries one is malformed, and malformed
    # REFUSES while absent is an empty column.
    entry = _binding().as_manifest_entry()
    result = _run_node(f"""
import {{ contributedViewBindings }} from {json.dumps(REGISTRY_JS.as_uri())};
const base = {json.dumps(entry)};
const out = {{}};
out.clean = contributedViewBindings({{ views: {{
  schema_version: {MANIFEST_SCHEMA_VERSION}, kind: {json.dumps(MANIFEST_KIND)},
  views: [base] }} }}).length;
for (const [name, extra] of [
  ["control", {{ control: "tab-docs" }}],
  ["mount", {{ mount: "renderDocs" }}],
]) {{
  try {{
    contributedViewBindings({{ views: {{
      schema_version: {MANIFEST_SCHEMA_VERSION},
      kind: {json.dumps(MANIFEST_KIND)},
      views: [{{ ...base, ...extra }}] }} }});
    out[name] = "not refused";
  }} catch (e) {{ out[name] = e.name; out[name + "Message"] = e.message; }}
}}
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["clean"] == 1
    assert result["control"] == "ViewBindingError"
    assert result["mount"] == "ViewBindingError"
    assert "core arm" in result["controlMessage"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_refuses_an_entry_exported_as_something_that_cannot_be_called(
        tmp_path):
    # PRESENT IS NOT MOUNTABLE. A module may export the named entry as a string,
    # an object or a `null`; checking only that the NAME exists hands back a
    # binding that looks resolved and throws a raw `TypeError` from inside
    # whatever tried to mount it — the dangling-import failure mode this seam
    # exists to replace. Copilot found this on PR #14.
    web = _temp_bundle(tmp_path)
    (web / "views" / "panel.js").write_text(
        'export const mountPanel = "not a function";\n', encoding="utf-8")
    registry = (web / "views" / "view_extension.js").as_uri()
    result = _run_node(f"""
import {{ collectViewBindings, resolveView }} from {json.dumps(registry)};
const spec = {{ id: "panel.one", region: "view-docs",
  module: "./views/panel.js", entry: "mountPanel", view_class: "A" }};
const views = collectViewBindings([{{ views: () => [spec] }}]);
const out = {{}};
try {{ await resolveView(views, "panel.one"); out.resolved = "not refused"; }}
catch (e) {{ out.resolved = e.name; out.message = e.message; }}
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["resolved"] == "ViewBindingError"
    assert "rather than a function" in result["message"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_resolves_the_real_doc_list_module_from_its_binding(tmp_path):
    # THE VIEW THIS SLICE WIRES END TO END, proven against the real module: a
    # binding read out of a `/capabilities` manifest, collected, and resolved to
    # the export it names. No stub anywhere on the path.
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "contributed_routes": [],
        "views": [_binding().as_manifest_entry()],
    }
    result = _run_node(f"""
import {{ collectViewBindings, contributedViewBindings, resolveView }}
  from {json.dumps(REGISTRY_JS.as_uri())};
const caps = {{ views: {json.dumps(manifest)} }};
const views = collectViewBindings(
  [{{ views: () => contributedViewBindings(caps) }}]);
const resolved = await resolveView(views, "docs.list");
console.log(JSON.stringify({{
  id: resolved.binding.id,
  region: resolved.binding.region,
  entry: typeof resolved.exports[resolved.binding.entry],
}}));
""", tmp_path)
    assert result == {"id": "docs.list", "region": "view-docs",
                      "entry": "function"}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_resolve_view_refuses_a_binding_whose_module_fails_to_load(tmp_path):
    # A REJECTED `import()` IS A REFUSAL TOO. Before this test's fix, a binding
    # naming a module that is not there rejected with a native error carrying
    # no binding or module context -- the app reports a generic snapshot
    # failure instead of the "which binding, which module" every other defect
    # in this function states (Copilot, PR #14).
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "contributed_routes": [],
        "views": [{"id": "fixture.missing", "region": "view-docs",
                   "module": "./views/does-not-exist.js", "entry": "mountPanel",
                   "view_class": "A", "routes": [], "requires": [],
                   "optional": False}],
    }
    result = _run_node(f"""
import {{ collectViewBindings, contributedViewBindings, resolveView }}
  from {json.dumps(REGISTRY_JS.as_uri())};
const views = collectViewBindings(
  [{{ views: () => contributedViewBindings({{ views: {json.dumps(manifest)} }}) }}]);
const out = {{}};
try {{
  await resolveView(views, "fixture.missing");
  out.result = "not refused";
}} catch (e) {{ out.result = e.name; out.message = e.message; }}
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["result"] == "ViewBindingError"
    assert "fixture.missing" in result["message"]
    assert "./views/does-not-exist.js" in result["message"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_mounts_a_contributed_panel_into_its_region(tmp_path):
    # The CONTRIBUTED path end to end: a binding that arrived as JSON, loaded
    # from a module the core arm never imported, mounted into the region it
    # named — which is exactly what slice S5's gate loop will be.
    web = _temp_bundle(tmp_path)
    (web / "views" / "panel-fixture.js").write_text(
        "export function mountPanel(host, ctx) {\n"
        "  const node = host.ownerDocument.createElement('div');\n"
        "  node.textContent = 'contributed: ' + ctx.label;\n"
        "  host.appendChild(node);\n"
        "  return { mounted: true };\n"
        "}\n", encoding="utf-8")
    registry = (web / "views" / "view_extension.js").as_uri()
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "contributed_routes": [],
        "views": [{"id": "fixture.panel", "region": "view-docs",
                   "module": "./views/panel-fixture.js", "entry": "mountPanel",
                   "view_class": "A", "routes": [], "requires": [],
                   "optional": False}],
    }
    result = _run_node(f"""
import {{ collectViewBindings, contributedViewBindings, resolveView, regionHost }}
  from {json.dumps(registry)};

// The smallest DOM that answers what a mount does: create, append, read back.
class Node {{
  constructor(tag, doc) {{ this.tag = tag; this.children = []; this.text = "";
    this.id = ""; this.ownerDocument = doc; }}
  set textContent(v) {{ this.text = String(v); }}
  get textContent() {{ return this.text
    + this.children.map((c) => c.textContent).join(""); }}
  appendChild(child) {{ this.children.push(child); return child; }}
}}
const doc = {{
  nodes: [],
  createElement(tag) {{ const n = new Node(tag, doc); doc.nodes.push(n); return n; }},
  getElementById(id) {{ return doc.nodes.find((n) => n.id === id) || null; }},
}};
const host = doc.createElement("section");
host.id = "view-docs";

const views = collectViewBindings(
  [{{ views: () => contributedViewBindings({{ views: {json.dumps(manifest)} }}) }}]);
const resolved = await resolveView(views, "fixture.panel");
const target = regionHost(resolved.binding, doc);
const controller = resolved.exports[resolved.binding.entry](
  target, {{ label: "the consumer column" }});
console.log(JSON.stringify({{
  mounted: controller.mounted,
  rendered: target.textContent,
  sameHost: target === host,
}}));
""", tmp_path)
    assert result == {"mounted": True,
                      "rendered": "contributed: the consumer column",
                      "sameHost": True}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_an_absent_optional_binding_is_null_and_a_required_one_refuses(tmp_path):
    # § 6 Q5's shape, and the gate bar's: absent-and-optional is an outcome the
    # caller handles, absent-and-required is a refusal that names the layering.
    result = _run_node(f"""
import {{ collectViewBindings, lookupView, requireView, resolveView }}
  from {json.dumps(REGISTRY_JS.as_uri())};
const views = collectViewBindings([]);
const out = {{ lookup: lookupView(views, "gate.bar"),
               resolve: await resolveView(views, "gate.bar") }};
try {{ requireView(views, "gate.bar"); out.require = "not refused"; }}
catch (e) {{ out.require = e.name; out.requireMessage = e.message; }}
console.log(JSON.stringify(out));
""", tmp_path)
    assert result["lookup"] is None
    assert result["resolve"] is None
    assert result["require"] == "ViewBindingError"
    assert "optional: true" in result["requireMessage"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_js_refuses_a_shell_region_asked_for_a_standing_element(tmp_path):
    result = _run_node(f"""
import {{ collectViewBindings, regionHost }}
  from {json.dumps(REGISTRY_JS.as_uri())};
const views = collectViewBindings([{{ views: () => [{{
  id: "gate.bar", region: "viewer-gatebar", module: "./views/gate.js",
  entry: "mountGateBar", view_class: "B", optional: true }}] }}]);
let name = "not refused";
try {{ regionHost(views[0], {{ getElementById: () => null }}); }}
catch (e) {{ name = e.name; }}
console.log(JSON.stringify({{ refused: name }}));
""", tmp_path)
    assert result == {"refused": "ViewBindingError"}
