"""The read-only `/source` pass-through as openDox's OWN core arm — § 3.4 S6.

RULED Q4 (Brett Heap, 2026-09-12, `opensoft/openxFactory#656` comment
`5642758731`, by interactive multi-choice): *"`/source/` is openDox's, and
openXdox's projection binding keeps only `/snapshot-index.json` and the three
`/projections/*` routes."* Reading a file out of the pinned checkout is the
NEUTRAL product's own read-only pass-through; it predates the gate loop and
nothing about it is a gate act, and under RULING OQ-2 a student runs openDox
alone — so a read-only Markdown viewer that cannot load a file without the
consumer layer was a route-ownership defect, not a layering one.

WHAT THIS FILE IS FOR. The boundary note (openDox-spec
`docs/front-end-package-boundary.md` § 5 row S6) asks the slice for
"`serve_projection.py`, `serve.py` (+ their tests)". The assertions the route
already had live in SIX suites at openXdox-code — `test_source_dot_directories.py`
whole, plus thirteen functions across `test_renderer.py`,
`test_explorer_viewer.py`, `test_session_snapshot.py`,
`test_doxbench_transport.py` and `test_repo_selector.py` — and NONE of them
runs, at that leg or this one: § 1.2(d)'s finding, RULED Q-L5 (b′) / Q-L8 (b′)
the narrowing that records it, and § 5 row S8 the slice that lifts it.

THEY STAY THERE, and not for want of trying. Each has a carve-manifest row
naming `openxdox_code`, so moving one is a RE-DESTINATION of the row rather
than a declared edit to an arrived file, which Q-L1's annotation form
(`edits: [{class, lines[], note}]`) cannot express — openXdox-code `657c821`
records the attempt and its withdrawal on the floor's own remediation rule.
Every one of them already reads `from opendox import serve as serve_mod`, so
none is orphaned by the route moving; S8 re-homes all 48 with the manifest act
that pass will need.

A slice that moved a route and left its only proof in the non-running half
would be a slice whose claim rests on a commit message. This module is that
proof.

So this module is the RUNNABLE half, in the shape its four neighbours on
`validate`'s explicit list already use (`test_leg_shape.py`,
`test_consumer_reach.py`, `test_web_boundary.py`, `test_view_registry.py`): it
PARSES `src/opendox/serve.py` and reads the live `opendox.consumer_reach`, and
it imports `opendox.serve` nowhere, because `opendox.serve` cannot be imported
at either leg — `from ideation_dashboard import serve_openxfactory_lanes` names
openxFactory's PRE-CARVE package, a `stays_openxfactory_adapter` row (RULING
DQ-1) present at neither destination, and `tests/test_consumer_reach.py`'s
`STILL_REACHING` records exactly that. A source-level assertion is what is
available until the BUILD arc (§ 3.5/3.6) closes it, and it is not nothing: a
route's ownership, its dispatch order, its containment authority, its content
types and its refusal shapes are all properties of the text.

WHAT IT HOLDS, and why each is here rather than implied:

1. THE ROUTE IS DECLARED HERE, with the pre-carve strings. Two constants and
   three methods, defined in `serve.py` rather than forwarded — the difference
   between "openDox owns this route" and "openDox can reach a leg that does".
2. THE COLUMN NO LONGER CARRIES THEM. Asserted on the LIVE
   `consumer_reach.LateProjectionRoutes`, as an absence: a forwarder left behind
   would be invisible, because the route would go on working wherever openXdox
   happens to be installed — which is every developer machine, and neither claim
   this slice makes.
3. THE ORDER IS THE ONE THE BINDINGS HAD. `collect_bindings` groups every EXACT
   binding ahead of every PREFIX one, so `/source` refused with a message and
   `/source/` (empty tail) 404'd with divergence headers and a zero-length body.
   `_route` reproduces that by putting the exact arm above the prefix arm.
   Written the other way round the bare route is unreachable and the answer
   silently becomes an HTML error page — the exact regression the paragraph in
   `serve_projection.py`'s docstring was written to prevent, now that the
   paragraph is gone.
4. THE ARMS ARE FIXED, NOT CONTRIBUTED. They sit ABOVE `route_extension.match`,
   which is what makes them unshadowable: a contributed binding for `/source/`
   can no longer take the route back by arriving first.
5. THE CONTAINMENT AUTHORITY IS SINGLE AND UNMOVED. `resolve_source_path` is a
   real `def` here now, and its body is one call to
   `snapshot_registry.resolve_within` — the SAME rule, still the projection
   column's, reached through the late seam `serve_workbench.py` already uses at
   five sites. A second copy of the check beside it is the fork
   `route_extension.py`:89 names; that is what this asserts against, and it is
   also what carries openXdox-code's `tests/test_source_dot_directories.py`
   (T092 defect 10: `/source/.git/config` answering 200 with a remote's
   embedded PAT) across the move without re-stating it at a leg that cannot
   run it. Those refusals are `resolve_within`'s, and the arm inherits every
   one of them by calling that one authority and nothing else.
6. READ-ONLY, AND THE REFUSALS ARE THE ONES IT HAD. Three distinct answers, each
   asserted on its own text: `send_error(404, "no source path")` for the bare
   route, a bare `send_response(404)` + divergence headers + `Content-Length: 0`
   for an unresolved target (never `send_error`, whose HTML body is what the
   original move was careful not to introduce), and
   `send_error(404, "unreadable source")` for an OSError. Plus the two content
   types, and the absence of any write arm naming the route.
7. FR-048 IS STILL ASKED. The hosted-plane confinement is the PROJECTION
   column's rule, not this core's: the route moved and the rule did not, so both
   `hosted_ref_refused` and `_hosted_entry_refused` must still be consulted.
8. THE FRONT END DID NOT CHANGE. § 5 row S6 says `views/viewer.js` and
   `views/wheel.js`:97 "become clean" — and they do it WITHOUT AN EDIT, because
   the route moved to them rather than them to it. Asserted as a positive: the
   four `/source/` literals are still there, in files this slice never opened.

`--noconftest` SAFE, deliberately, like its neighbours on the explicit list:
nothing here needs a fixture, a path insertion or an installed consumer, and the
one import (`opendox.consumer_reach`) is the module whose whole point is that
importing it resolves nothing.

A CREATED file: no carve-manifest row (RULED OQ-C) — it declares what a
destination assembles, which the manifest never carries.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVE = ROOT / "src" / "opendox" / "serve.py"
WEB = ROOT / "src" / "opendox" / "web"

SERVE_TEXT = SERVE.read_text(encoding="utf-8")
SERVE_TREE = ast.parse(SERVE_TEXT)

#: The three methods that answer the route. A unit: the arm, the optional
#: `<repository>@<ref>/` split it starts with, and the bare route's answer.
SOURCE_METHODS = ("_keyed_source", "_serve_source", "_refuse_bare_source")


def _module_assign(name: str) -> ast.AST | None:
    """The module-level assignment of `name`, or None."""
    for node in SERVE_TREE.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == name:
            return node
    return None


def _module_function(name: str) -> ast.FunctionDef | None:
    for node in SERVE_TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _handler_class() -> ast.ClassDef:
    for node in SERVE_TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == "DashboardHandler":
            return node
    raise AssertionError("serve.py declares no DashboardHandler")


def _method(name: str) -> ast.FunctionDef | None:
    for node in _handler_class().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _source_of(node: ast.AST) -> str:
    return ast.get_source_segment(SERVE_TEXT, node) or ""


# ---------------------------------------------------------------------------
# 1 — the route is declared HERE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,value", [
    ("SOURCE_PREFIX", "/source/"),
    ("BARE_SOURCE_ROUTE", "/source"),
])
def test_serve_declares_the_route_constants_with_the_pre_carve_strings(name, value):
    node = _module_assign(name)
    assert node is not None, (
        f"src/opendox/serve.py declares no {name}. RULED Q4 makes the /source "
        "pair this product's own route, so its patterns are declared here, not "
        "read off openxdox.serve_projection")
    assert isinstance(node.value, ast.Constant) and node.value.value == value, (
        f"{name} must be exactly {value!r} — the string the route answered "
        "before it moved. A route-ownership correction that changes the URL is "
        "not a correction, it is a break")


@pytest.mark.parametrize("name", SOURCE_METHODS)
def test_the_three_handlers_are_defined_on_this_handler(name):
    assert _method(name) is not None, (
        f"DashboardHandler does not define {name}. Since RULED Q4 the /source "
        "pass-through is a FIXED CORE ARM of the neutral product: the method "
        "is defined here, not inherited from a late column standing in for the "
        "layer that PINS openDox")


@pytest.mark.parametrize("name", SOURCE_METHODS)
def test_the_consumer_column_no_longer_forwards_them(name):
    """The absence, on the LIVE seam — see this module's point 2."""
    from opendox import consumer_reach

    _module, _cls, methods = consumer_reach.LateProjectionRoutes.LATE_COLUMN
    assert name not in methods, (
        f"consumer_reach.LateProjectionRoutes still forwards {name} into "
        "openxdox.serve_projection. A forwarder left behind keeps the route "
        "working on any machine that happens to have openXdox installed, which "
        "is how a move looks complete and is not")


def test_the_column_keeps_the_rules_the_ruling_did_not_move():
    """`_serve_index` and `_serve_snapshot` stay the projection column's, and so
    does `_hosted_entry_refused` — FR-048's per-entry hosted refusal, which
    `_serve_snapshot` calls too. Q4 ruled on route OWNERSHIP, not on the rules a
    route consults."""
    from opendox import consumer_reach

    _module, _cls, methods = consumer_reach.LateProjectionRoutes.LATE_COLUMN
    for kept in ("_serve_index", "_serve_snapshot", "_hosted_entry_refused"):
        assert kept in methods, (
            f"{kept} is still openXdox's and must still be forwarded; S6 moved "
            "the /source pair and nothing else")


# ---------------------------------------------------------------------------
# 2 — the dispatch: order, and unshadowability
# ---------------------------------------------------------------------------

def test_route_dispatches_the_exact_arm_before_the_prefix_arm():
    route = _method("_route")
    assert route is not None
    body = _source_of(route)
    bare = body.index("path == BARE_SOURCE_ROUTE")
    prefix = body.index("path.startswith(SOURCE_PREFIX)")
    assert bare < prefix, (
        "the exact /source arm must be consulted BEFORE the /source/ prefix "
        "arm. `collect_bindings` gave that order for free by grouping every "
        "exact binding ahead of every prefix one; a fixed arm has to be written "
        "in it. The other way round, `/source` never reaches "
        "_refuse_bare_source and its 404 quietly becomes the prefix arm's")
    assert "self._refuse_bare_source(head_only)" in body
    assert "self._serve_source(path[len(SOURCE_PREFIX):], head_only)" in body, (
        "the prefix arm passes the TAIL, which is what RouteBinding.remainder "
        "computed for the contributed form: path[len(pattern):]")


def test_the_arms_are_fixed_and_cannot_be_shadowed_by_a_contribution():
    body = _source_of(_method("_route"))
    prefix = body.index("path.startswith(SOURCE_PREFIX)")
    contributed = body.index("route_extension.match(")
    assert prefix < contributed, (
        "both /source arms must sit ABOVE the § 2.4 contributed-route consult. "
        "That placement is the whole difference between a core arm and a "
        "binding: a contributed /source/ binding must not be able to take the "
        "route back by arriving first")


def test_a_head_request_reaches_the_same_arms():
    """`do_HEAD` routes through `_route` exactly as `do_GET` does, so the pair
    answers HEAD the way the "GET" bindings did (`RouteBinding.matches`: a GET
    binding answers a HEAD request too)."""
    body = _source_of(_method("do_HEAD"))
    assert "self._route(head_only=True)" in body


# ---------------------------------------------------------------------------
# 3 — containment: one authority, unmoved
# ---------------------------------------------------------------------------

def test_resolve_source_path_is_a_real_definition_here():
    node = _module_function("resolve_source_path")
    assert node is not None, (
        "resolve_source_path must be a real `def` in serve.py: it is the "
        "single-root entry point to the containment of a route this product "
        "now owns, and notebook_action.py:52 imports the name `from .serve`")


def test_the_containment_rule_is_the_one_authority_and_is_not_re_implemented():
    body = _source_of(_module_function("resolve_source_path"))
    statements = [line for line in body.splitlines()
                  if line.strip() and not line.strip().startswith(("#", '"', "'"))]
    assert "registry_mod.resolve_within(" in body, (
        "the containment rule is snapshot_registry.resolve_within and it did "
        "NOT move: it is the projection column's, it is the same rule applied "
        "per registry entry (task 2.2), and openDox reaches it through the "
        "late consumer_reach seam serve_workbench.py already uses")
    assert len([s for s in statements if s.startswith("    return ")]) == 1, (
        "resolve_source_path is a delegation and must stay one. A second copy "
        "of the containment rule here is the fork route_extension.py:89 names "
        "— and it is what would silently drop the dot-directory refusals "
        "(openXdox-code tests/test_source_dot_directories.py, T092 defect "
        "10), which are "
        "resolve_within's and are inherited only by calling it")


def test_the_arm_resolves_through_that_entry_point_and_the_registry_only():
    body = _source_of(_method("_serve_source"))
    assert "resolve_source_path(Path(self.checkout_root), rest)" in body, (
        "the no-registry path resolves through the single-root entry point")
    assert "self.source.registry.resolve_source(repository, ref, rest)" in body, (
        "the registry path resolves through the entry's OWN root (per-entry "
        "confinement, task 2.2) — not through the served checkout with a key "
        "stripped off, which is the silent-wrong-data failure the seam exists "
        "to prevent")
    assert "resolve_within(" not in body, (
        "the arm must not call the containment rule directly: one entry point, "
        "so a change to the rule cannot reach the route by one path and miss "
        "it by the other")


# ---------------------------------------------------------------------------
# 4 — read-only, and the three refusals
# ---------------------------------------------------------------------------

def test_the_bare_route_refuses_with_its_own_message():
    body = _source_of(_method("_refuse_bare_source"))
    assert 'self.send_error(404, "no source path")' in body


def test_an_unresolved_target_404s_with_divergence_headers_and_no_body():
    body = _source_of(_method("_serve_source"))
    block = body.split("if target is None:", 1)[1].split("return", 1)[0]
    assert "self.send_response(404)" in block
    assert "self._divergence_headers(entry)" in block, (
        "the 404 carries the snapshot↔checkout divergence, so a viewer can "
        "tell a missing file from a stale reference")
    assert 'self.send_header("Content-Length", "0")' in block
    assert "send_error" not in block, (
        "this answer is deliberately NOT send_error: send_error writes an HTML "
        "error body, and the pre-carve behaviour here was a zero-length one. "
        "Changing it was the specific regression the /source pair was moved "
        "together to avoid")


def test_an_unreadable_target_refuses_without_leaking_the_reason():
    body = _source_of(_method("_serve_source"))
    assert "except OSError:" in body
    assert 'self.send_error(404, "unreadable source")' in body


def test_the_two_content_types_are_the_ones_it_served():
    body = _source_of(_method("_serve_source"))
    assert ('ctype = "text/markdown; charset=utf-8" if target.suffix == ".md" '
            'else "text/plain; charset=utf-8"') in body, (
        "markdown for .md and text/plain for everything else — never a guessed "
        "type, and never text/html, which on the CSP-free local origin would "
        "make a served document executable")


def test_the_route_is_read_only():
    post = _source_of(_method("do_POST"))
    assert "SOURCE_PREFIX" not in post and "BARE_SOURCE_ROUTE" not in post, (
        "no write arm may name the source route: it is a read-only "
        "pass-through (D15) and the whole security posture depends on it")
    body = _source_of(_method("_serve_source"))
    for writer in ("write_bytes", "write_text", "unlink", "mkdir", "rename"):
        assert writer not in body, f"_serve_source calls {writer}"
    assert "read_bytes()" in body


# ---------------------------------------------------------------------------
# 5 — FR-048 is still asked
# ---------------------------------------------------------------------------

def test_the_arm_still_asks_the_hosted_plane_refusal():
    body = _source_of(_method("_serve_source"))
    assert "hosted_ref_refused(self.loopback, ref)" in body, (
        "the KEYED form is the other route that names a ref (FR-048): a hosted "
        "plane serves no session worktree's bytes, keyed or not")
    assert "self._hosted_entry_refused(entry)" in body, (
        "and the UNKEYED form resolves to the ACTIVE entry, which the request "
        "never named — the ref-less hole _serve_snapshot closes the same way")
    assert "HOSTED_SESSION_REFUSAL" in body


def test_hosted_ref_refused_is_still_reached_through_the_late_seam():
    """The route moved; FR-048 did not. `hosted_ref_refused` stays bound to the
    consumer stand-in, and `tests/test_consumer_reach.py` holds it to being read
    only from inside a function body."""
    node = _module_assign("hosted_ref_refused")
    assert node is not None and "consumer_reach.hosted_ref_refused" in _source_of(node)


# ---------------------------------------------------------------------------
# 6 — the front end did not change
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative,pattern", [
    ("views/viewer.js", r'o\.sourceBase \|\| "/source/"'),
    ("views/wheel.js", r'const SOURCE_ROUTE = "/source/";'),
    ("app.js", r'return "/source/";'),
])
def test_the_bundle_still_addresses_the_route_and_was_not_edited(relative, pattern):
    """§ 5 row S6: "`views/viewer.js` and `views/wheel.js`:97 become clean" —
    and they do it without an edit. The note's own § 2.2 rule 1 remedy for the
    census's one class-A breach was to move the ROUTE, not the file, so the
    literals must still be here. If a later slice "fixes" the viewer by editing
    it, this is what says the fix was aimed at the wrong thing."""
    text = (WEB / relative).read_text(encoding="utf-8")
    assert re.search(pattern, text), (
        f"{relative} no longer addresses /source/ the way it did at S6. The "
        "ruling made that literal correct; it did not make it optional")
