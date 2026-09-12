"""The VIEW extension point: how a layer above the app server contributes a
PANEL instead of forking the front-end bundle (§ 3.4's view registry, openDox-spec
`docs/front-end-package-boundary.md` § 4.1, slice S3).

WHAT THIS EXISTS TO PREVENT, in the boundary note's own words: `src/opendox/web/`
is "42 blobs, 30,585 lines, and NO package boundary at all", so "the web tier's
cross-column edges exist, they are load-bearing, and the front end has no
vocabulary for them while the Python side has three
(`route_extension.RouteBinding`, `consumer_reach`, `domain_profile.register`).
The boundary this note invents is that vocabulary." This module is the first
third of it. Three measured defects are the reason:

  (b) `views/dispose.js`:26 and `views/wheel.js`:75-76 import a module RULED to
      stay at openxFactory, so the shell's own module graph does not resolve —
      "the defect is that nothing in the front end could express the edge".
  (c) thirteen route constants in five openDox view files address a prefix
      `openxdox/serve_gate.py` owns.
  (d) 48 test files across two repositories disagree about which leg owns the
      bundle.

THE SHAPE IS `route_extension.py`'s, DELIBERATELY AND ALMOST LINE FOR LINE.
That module's own sentence is the rule this one inherits: *"A contributed route
is the profile; a second copy of the dispatch is the fork."* Its front-end twin:
a contributed PANEL is the profile; a second copy of the shell is the fork. So
`ViewBinding` is `RouteBinding` (frozen, validated where it is CONSTRUCTED
rather than where it is mounted), `ViewExtension` is `RouteExtension` (a
`runtime_checkable` `Protocol`, so a binding authored in the repository that
PINS this one conforms without importing anything from here), and
`collect_view_bindings` is `collect_bindings` (one consult order, refusing what
cannot mount). Where the two differ, the difference is argued in place.

WHY IT SITS INSIDE `opendox/` AND NOT BESIDE `route_extension.py`.
`route_extension.py` lives at the top of `src/` because BOTH sides of the carve
consume it and it travels to a repository where neither package exists — a
replica at each destination, declared by openxFactory's manifest. Nothing about
this module is symmetrical in that way: openDox DECLARES the view seam and
openXdox CONSUMES it, and openXdox already pins openDox
(`openXdox-code` `af15f712`'s `opendox` pin -> `a99eba03`). A consumer importing
the product it pins is the direction the split is FOR; it is the reverse — the
product reaching its consumer — that `consumer_reach.py` exists to make late,
named and refusable. So `from opendox import view_extension` is a legal downward
import for a contributing column, and no replica is needed.

THE THREE THINGS A CONTRIBUTED VIEW BRINGS WITH IT, and why each is a field
rather than a convention:

* ITS MOUNT POINT (`region`). The shell already declares them — `index.html`'s
  seven `view-*` sections and its two overlay roots are exactly mount points,
  each an element whose `id` is the region's name — and slice S3 makes that
  declaration a CONTRACT (`REGIONS` below, held against the file by a drift
  test). A binding naming a region the shell does not declare is refused here,
  because
  the front-end analogue of `collect_bindings`' refusal is precise: *"a declared
  route silently unreachable"* becomes *"a declared panel silently unmounted"*.
* ITS ROUTES (`routes`). RULED Q3 (openxFactory#656 comment `5642758731`,
  Brett Heap, 2026-09-12): **"a route constant travels with the binding that
  calls it, never with the model that happens to declare it."** A binding that
  declares the routes it calls is what makes that ruling checkable instead of
  aspirational, and `collect_view_bindings` checks it — see
  `_route_ownership_breach`.
* ITS CLASS (`view_class`). § 2.1's three destination classes: A openDox core,
  B the gate loop, C a stage-named region. The class is not decoration: it is
  the SCOPE of the route-ownership refusal (§ 4.5 assertion 2 — "Class B is
  exempt by construction: a gate-loop file naming a gate route is the boundary
  working"), and it is what a later slice reads to know what may move.

WHAT THIS MODULE DOES NOT DO, and where it is done instead:

* IT DOES NOT MOUNT ANYTHING. Mounting is the browser's, and the client mirror
  is `src/opendox/web/views/view_extension.js` — the same vocabulary, the same
  refusals, in the language the shell is written in. This half is the AUTHORITY:
  it is where a host's contribution is collected and refused, and it renders the
  JSON manifest the client consumes (`view_manifest`).
* IT DOES NOT ADD A ROUTE OR A FETCH. The manifest rides on the payload the
  shell already fetches once at load — `/capabilities`, read by
  `views/notebook.js`'s `probeCapabilities()` — exactly as the note's § 4.3
  puts the profile's display facet there: "no new route and no second fetch".
  The ONE line that puts it there (`capabilities["views"] = view_manifest(...)`
  in `serve.build_server`) is NOT written by slice S3: `serve.py` is a
  `moved_with_declared_edit` row of openxFactory's carve manifest whose declared
  lines do not cover it, and the ASK-7 declared-edit window (openxFactory#656
  comment `5642614423`) holds that row this hour. S3 builds and tests BOTH ENDS
  of the seam — this module against a stub profile facet, the client against a
  stub payload — and S5, the slice at which a contribution first EXISTS to
  deliver, joins them in its own declared-edit window. Until then the consumer
  column is empty and the core renders alone, which is what the note's S3 row
  asks for in its own words: *"nothing is contributed yet, so the shell renders
  exactly as today with an empty extension tuple."*

A CREATED FILE: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
(RULED OQ-C — the manifest declares what LEAVES openxFactory, never what a
destination assembles).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Protocol, runtime_checkable

__all__ = [
    "CTX_KEYS",
    "MANIFEST_KIND",
    "MANIFEST_SCHEMA_VERSION",
    "REGIONS",
    "VIEW_CLASSES",
    "ViewBinding",
    "ViewBindingError",
    "ViewExtension",
    "collect_view_bindings",
    "dom_regions",
    "host_view_extensions",
    "view_manifest",
]


#: § 2.1's three destination classes, in the note's own letters. A binding says
#: which side of the boundary its module is on, and the answer is checkable
#: rather than editorial: class B is the ONLY class exempt from the
#: route-ownership refusal below (§ 4.5 assertion 2).
VIEW_CLASSES: tuple[str, ...] = ("A", "B", "C", "?")

#: `"?"` IS THE TRANSITIONAL CLASS AND IT IS THE NOTE'S OWN, not a loophole:
#: § 4.5 assertion 1 declares it a class "the census may carry only until S4",
#: because the five SPLIT files (`explorer.js`, `lens-model.js`, `lens.js`,
#: `repo-selector.js`, `staging-workbench-model.js`, 5,711 lines) each carry
#: class-A or class-C substance AND a class-B or openxFactory-adapter tail, and
#: naming that honestly is worth more than forcing a letter. It is IN SCOPE for
#: the route-ownership refusal, exactly as § 4.5 assertion 2 says it is —
#: "class A, class C AND the transitional `?`, which is where most of the
#: breaches actually sit". Slice S4 splits the five and this entry goes.

#: THE SHELL'S DECLARED MOUNT POINTS — the contract a contributed binding may
#: name, and the whole of it. Two kinds, and the distinction is load-bearing:
#:
#:  "dom"    a mount point `index.html` itself declares, as an element whose
#:           `id` IS the region name — the seven `view-*` tab panels and the two
#:           overlay roots, which is what the note means by "`index.html`'s
#:           `view-*` sections and the two overlay roots are already exactly
#:           that". `tests/test_view_registry.py` holds this tuple and that file
#:           to each other, so neither can drift: a region named here with no
#:           element there is a panel with nowhere to mount.
#:
#:           THE SHELL IS NOT EDITED TO SAY SO, and that is deliberate rather
#:           than lazy. A `data-region` attribute would be a second spelling of
#:           an id the shell already carries, and `index.html` is a
#:           `moved_verbatim` row of openxFactory's carve manifest
#:           (`docs/opendox-carve-manifest.yaml`) whose declared-edit vocabulary
#:           is the RULED closed list `import rewrites | path constants |
#:           adapter calls` — an added attribute is in none of them, so
#:           declaring the edit would mean inventing an edit class rather than
#:           using one. The id is the declaration; the drift test is what makes
#:           it a contract.
#:  "shell"  a mount point the SHELL creates at mount time and hands to the
#:           binding — it has no standing element, so `index.html` cannot
#:           declare it. `viewer-gatebar` is the viewer's own gate-bar host
#:           (`views/viewer.js`:342 builds the `div` and calls `mountGate`);
#:           `lens-gate` and `repo-projects` are slice S4's, added with the two
#:           class-B bindings that mount into them — the lens plan panel's
#:           execute box (`views/gate-lens.js`) and the selector's
#:           project-commission slot (`views/gate-projects.js`), each a host the
#:           view builds and hands over exactly as the viewer does;
#:           the two `*-intent` regions are slice S2's, declared HERE and now so
#:           that S2's optional intent-chip bindings fold into this registry
#:           without re-opening it (§ 6 Q5: "S2 makes the chips an OPTIONAL
#:           contributed binding — absent, the wheel and the tray render without
#:           them"). Declaring a region costs nothing and refuses nothing; an
#:           undeclared one is what costs a slice.
REGIONS: dict[str, str] = {
    "view-funnel": "dom",
    "view-wheel": "dom",
    "view-board": "dom",
    "view-canvas": "dom",
    "view-lens": "dom",
    "view-docs": "dom",
    "view-lineage": "dom",
    "explorer-root": "dom",
    "staging-workbench-root": "dom",
    "viewer-gatebar": "shell",
    "wheel-intent": "shell",
    "dispose-intent": "shell",
    "lens-gate": "shell",
    "repo-projects": "shell",
    "page-overlay": "shell",
    "workbench-create": "shell",
    "workbench-session": "shell",
}
#: THE THREE REGIONS SLICE S5 ADDS, and why each is a `shell` one.
#:
#: `page-overlay` is RULED Q8 (openxFactory#656 comment `5648049748`, Brett
#: Heap, 2026-09-12): "a fourth `shell` region, `page-overlay`, is the declared
#: host for page-level panels (dispose.js's refusal panel); `document.body` is
#: never a contract surface." The gate column's refusal panel appended a
#: singleton `aside.refusalpanel` straight to the body — a mount point no region
#: declared, which is "exactly the silence the REGIONS table exists to end, and
#: a contributed column appending to the body is a collision nothing can
#: refuse". The SHELL builds this host and hands it over, which is what makes it
#: `shell` rather than an `index.html` element: `index.html` is a
#: `moved_verbatim` row of openxFactory's carve manifest and an added element is
#: in none of its declared edit classes, so the host is built by `app.js` — and
#: the region's kind says so honestly rather than declaring a `dom` region whose
#: element the shell creates at run time.
#:
#: `workbench-create` and `workbench-session` are the staging workbench's two
#: caller-built hosts — the create affordance's slot and the session bar's row,
#: both built by `views/staging-workbench.js` at mount time and handed over,
#: exactly as `views/viewer.js` builds `div.viewer-gate` for `viewer-gatebar`.
#: They are added HERE, with the bindings that mount into them, on slice S4's
#: own precedent (`lens-gate` and `repo-projects` arrived the same way one slice
#: ago) and on this table's own argument: "Declaring a region costs nothing and
#: refuses nothing; an undeclared one is what costs a slice."

#: THE CONTEXT OBJECT'S DECLARED KEYS — what a binding mounted at a region may
#: read off the third argument of `mount(host, snapshot, ctx)` (RULED Q3,
#: openxFactory#656 comment `5648044785`). Mirrored in
#: `web/views/view_extension.js` and held against it by
#: `tests/test_display_facet.py`, exactly as REGIONS is.
#:
#: `display` is SLICE S7's ONE ADDITION — § 4.3 step 3, "`app.js` puts that
#: facet in the context object every binding already receives". It is the
#: vocabulary reader of `web/views/display.js`, built from the `display` block
#: `serve.build_server()` publishes on `/capabilities`, and every read on it is
#: BY ROLE: `.label(role)`, `.one(role)`, `.many(role)`, `.status(vocabulary,
#: role)`, `.area(role)`, `.token(role)`, `.items(snapshot, role)`. A
#: contributed column reads the registered domain's words the same way openDox's
#: own class-C views do, and inherits openDox's neutral words when no host
#: declares any.
CTX_KEYS: dict[str, str] = {
    "caps": "the capability probe, composed-stripped where the render is composed",
    "views": "the collected view registry — `lookupView(ctx.views, id)`",
    "nav": "the shell's cross-view navigation verbs, or null outside a tab",
    "display": "the registered domain's vocabulary, resolved BY ROLE (slice S7)",
    "signal": "the render's AbortSignal, for any listener bound outside own root",
}

#: The facet name a host's profile carries, beside `ROUTE_EXTENSIONS` and
#: `SUBCOMMAND_EXTENSIONS` — ONE composite profile, one registration, three
#: facets, all resolved through the SAME lazy proxy (RULED ASK-2 option (2),
#: openxFactory#656 comment `5628886636`).
PROFILE_FACET = "VIEW_EXTENSIONS"

MANIFEST_KIND = "opendox.view-manifest"
MANIFEST_SCHEMA_VERSION = 1

#: A binding id: dotted, lowercase, no leading or trailing separator. Narrow on
#: purpose — the id travels into JSON, into a DOM `data-view` attribute and into
#: a refusal message, and a permissive id is how one of those three ends up
#: quoting something it must escape.
_ID = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")

#: A bundle-relative ES module specifier, the only kind the shell may import.
#: `./views/gate.js`, never `/views/gate.js` (root-relative breaks a served
#: sub-path), never `https://…` and never `//…` — § 4.4's vendor policy is
#: "vendored, MIT, `html` disabled, no CDN, no external font, no remote script",
#: and a contributed binding is exactly the hole that policy would leak through
#: if the seam did not close it here. openXdox-code's
#: `test_renderer.py::test_no_external_urls_anywhere_in_bundle` greps the
#: BUNDLE; a contributed module specifier is not in the bundle, so it needs its
#: own refusal rather than that test's coverage.
_MODULE = re.compile(r"^\./[A-Za-z0-9_./-]+\.js$")

#: An export name, held to the SAME grammar `views/view_extension.js`'s
#: `viewBinding()` checks (Copilot, PR #14): `str.isidentifier()` and this
#: bundle's client both claimed to validate "a JS export name" and actually
#: validated two different things — Python's accepts Unicode names (`café`)
#: the browser's ASCII-only check then refuses, and rejects ASCII names the
#: browser accepts (`$mount`, `$` is not a Python identifier character at
#: all). A binding this module publishes and the client then refuses is
#: § 4.1's seam failing at the one place a shared vocabulary was the entire
#: point, so both halves compile the one pattern below rather than each
#: half asking its own language what an identifier is.
_ENTRY = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


class ViewBindingError(ValueError):
    """A binding that cannot be mounted, refused where it is DECLARED.

    One exception for every declaration defect in this module — a malformed
    binding, a slot collision, an extension that does not conform, a route a
    binding may not name — because a caller does nothing different for any of
    them: they are all "this shell must not be assembled this way".
    `route_extension.RouteBindingError`'s reasoning, unchanged.
    """


@dataclass(frozen=True)
class ViewBinding:
    """One contributed panel: where it mounts, what module mounts it, and the
    routes it calls.

    Frozen and validated in `__post_init__`, for `RouteBinding`'s reason: a
    binding is declared once at assembly time and consulted on every render, so
    the cheap place to find a malformed one is the first.
    """

    id: str               #: unique within a region; see `_ID`
    region: str           #: a key of `REGIONS`
    module: str           #: the bundle-relative ES module that mounts it
    entry: str            #: the NAME of that module's export — never a callable
    view_class: str       #: one of `VIEW_CLASSES`
    #: Every route this binding's module CALLS — RULED Q3's "a route constant
    #: travels with the binding that calls it". Declared, not inferred: a
    #: binding's own author knows, and the alternative is grepping a module this
    #: process may not even be able to read.
    routes: tuple[str, ...] = ()
    #: EVERY EXPORT THE SHELL MAY REACH — RULED Q2 (openxFactory#656 comment
    #: `5648049748`, Brett Heap, 2026-09-12): "a binding's contract is its
    #: module NAMESPACE, DECLARED as an `exports` tuple: every export the shell
    #: may reach is listed on the binding and validated the way `entry` is; an
    #: undeclared reach (today `isGateBearing`, app.js:939) is a refusal."
    #:
    #: WHY A TUPLE AND NOT THE NAMESPACE ITSELF. `resolveView` hands back the
    #: whole module namespace, and the shell read `gateView.exports.isGateBearing`
    #: — an export the binding never declared and this seam never validated. A
    #: contributed column could therefore withdraw an export the shell depends
    #: on and learn about it from a `TypeError` in a click handler. Declared,
    #: it is refused where every other declaration defect is refused.
    #:
    #: EMPTY MEANS `entry` ALONE, which is the pre-Q2 contract and is what every
    #: core-arm binding still declares: the core arm's modules are imported
    #: statically by the shell that owns them, so there is no namespace crossing
    #: a process boundary to declare. A NON-EMPTY tuple must CONTAIN `entry` —
    #: the mount is the first member of the namespace the shell may reach, and a
    #: tuple that omitted it would be declaring a contract its own entry breaks.
    exports: tuple[str, ...] = ()
    #: Capability keys (`/capabilities`' `actions`) or profile facets the
    #: binding needs. Consulted by the CLIENT at mount; carried here because the
    #: manifest is what the client reads.
    requires: tuple[str, ...] = ()
    #: Whether the shell renders correctly WITHOUT this binding. The § 6 Q5
    #: answer made a field: an optional binding absent is a region that renders
    #: without it, a required binding absent is a refusal. Slice S2's intent
    #: chips are the first optional one; `gate.bar` is the second.
    optional: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID.match(self.id):
            raise ViewBindingError(
                f"view binding id {self.id!r} must be a dotted lowercase slug "
                "(e.g. 'gate.bar'): the id travels into JSON, into a DOM "
                "attribute and into a refusal message")
        # THE TYPE IS CHECKED BEFORE THE MEMBERSHIP, and the order is the
        # finding: `REGIONS` is a dict, so `<unhashable> not in REGIONS` raises
        # `TypeError` from the hash and the caller never sees the refusal this
        # module promises for every declaration defect. A seam whose refusal
        # depends on the TYPE of what it is refusing is not a seam.
        if not isinstance(self.region, str) or self.region not in REGIONS:
            raise ViewBindingError(
                f"view binding {self.id!r} names region {self.region!r}, which "
                f"the shell does not declare (declared: {sorted(REGIONS)}). A "
                "panel bound to a region that does not exist is silently "
                "unmounted, which is this seam's own version of a declared "
                "route that never fires")
        if not isinstance(self.module, str) or not _MODULE.match(self.module):
            raise ViewBindingError(
                f"view binding {self.id!r} names module {self.module!r}: a "
                "contributed module must be a bundle-relative './…js' "
                "specifier. A root-relative path breaks a served sub-path and "
                "an absolute URL is a remote script, which the vendor policy "
                "(§ 4.4) forbids outright")
        if ".." in self.module.split("/"):
            raise ViewBindingError(
                f"view binding {self.id!r} names module {self.module!r}, which "
                "climbs out of the bundle with '..'")
        if not isinstance(self.entry, str) or not _ENTRY.match(self.entry):
            raise ViewBindingError(
                f"view binding {self.id!r} names entry {self.entry!r}: an entry "
                "is the NAME of an export on the binding's module, never a "
                "callable — the same discipline `RouteBinding.handler` keeps, "
                "and for the same reason: the manifest crosses a process "
                "boundary as JSON. Held to the JS-compatible identifier "
                "grammar `views/view_extension.js` checks, not Python's own "
                "`str.isidentifier()` (§ 4.1: one vocabulary, both halves)")
        if self.entry.startswith("__"):
            raise ViewBindingError(
                f"view binding {self.id!r} names entry {self.entry!r}: a dunder "
                "reaches the object protocol rather than the module's own "
                "surface")
        # Guarded for the region's reason above. A tuple membership test does
        # not hash and so cannot raise today — but the guard states the rule
        # rather than relying on `VIEW_CLASSES` staying a tuple, which is
        # exactly the kind of quiet dependency the boundary work exists to end.
        if not isinstance(self.view_class, str) \
                or self.view_class not in VIEW_CLASSES:
            raise ViewBindingError(
                f"view binding {self.id!r} declares class {self.view_class!r}, "
                f"not one of {list(VIEW_CLASSES)} (§ 2.1: A openDox core, "
                "B the gate loop, C a stage-named region)")
        if not isinstance(self.exports, tuple):
            raise ViewBindingError(
                f"view binding {self.id!r} declares exports {self.exports!r}, "
                "which is not a tuple — a binding's declared namespace is "
                "frozen with it")
        for name in self.exports:
            # HELD TO `entry`'s OWN GRAMMAR, which is RULED Q2 in one line:
            # "validated the way `entry` is". Same pattern, same dunder guard,
            # same reason — the names cross a process boundary as JSON and are
            # then used to index a module namespace.
            if not isinstance(name, str) or not _ENTRY.match(name):
                raise ViewBindingError(
                    f"view binding {self.id!r} declares export {name!r}: an "
                    "export is the NAME of an export on the binding's module, "
                    "held to the same JS-compatible identifier grammar `entry` "
                    "is (RULED Q2, openxFactory#656 comment 5648049748)")
            if name.startswith("__"):
                raise ViewBindingError(
                    f"view binding {self.id!r} declares export {name!r}: a "
                    "dunder reaches the object protocol rather than the "
                    "module's own surface")
        if self.exports and self.entry not in self.exports:
            raise ViewBindingError(
                f"view binding {self.id!r} declares exports {list(self.exports)} "
                f"that do not include its own entry {self.entry!r}: RULED Q2 "
                "makes the tuple the WHOLE namespace the shell may reach, and "
                "the mount is the first member of it")
        if not isinstance(self.routes, tuple):
            raise ViewBindingError(
                f"view binding {self.id!r} declares routes {self.routes!r}, "
                "which is not a tuple — a binding's declared routes are frozen "
                "with it")
        for route in self.routes:
            if not isinstance(route, str) or not route.startswith("/"):
                raise ViewBindingError(
                    f"view binding {self.id!r} declares route {route!r}, which "
                    "must be a path rooted at '/'")
        if not isinstance(self.requires, tuple):
            raise ViewBindingError(
                f"view binding {self.id!r} declares requires {self.requires!r}, "
                "which is not a tuple")
        for name in self.requires:
            if not isinstance(name, str) or not name:
                raise ViewBindingError(
                    f"view binding {self.id!r} requires {name!r}, which is not "
                    "a capability or facet name")
        if not isinstance(self.optional, bool):
            raise ViewBindingError(
                f"view binding {self.id!r} declares optional "
                f"{self.optional!r}, which is not a bool")

    @property
    def slot(self) -> tuple[str, str]:
        """What makes two bindings the SAME panel — never the module.

        Two bindings claiming one (region, id) are a collision whichever modules
        they name: the second is unmounted, and an unmounted panel that looks
        declared is the defect `collect_view_bindings` refuses.
        `RouteBinding.key`'s reasoning, one tier out.
        """
        return (self.region, self.id)

    def as_manifest_entry(self) -> dict[str, Any]:
        """The JSON the client reads. Lists, not tuples — this is a payload."""
        return {
            "id": self.id,
            "region": self.region,
            "module": self.module,
            "entry": self.entry,
            "view_class": self.view_class,
            "exports": list(self.exports),
            "routes": list(self.routes),
            "requires": list(self.requires),
            "optional": self.optional,
        }


#: The one method a view extension declares. Named here rather than derived
#: from the Protocol, so a refusal can quote it — `route_extension.MEMBERS`'
#: reason, unchanged.
MEMBERS: tuple[str, ...] = ("views",)


@runtime_checkable
class ViewExtension(Protocol):
    """One method. Nothing else, ever.

    A `runtime_checkable` `Protocol` and NOT an ABC, for exactly
    `route_extension.RouteExtension`'s reason: an extension authored in the
    repository that PINS this one must be able to conform WITHOUT inheriting
    from anything here. Structural conformance is the property the seam exists
    for; nominal conformance would make the seam the dependency it was drawn to
    remove.
    """

    def views(self) -> tuple[ViewBinding, ...]:
        """Every panel this extension contributes, in its own declared order.

        Called ONCE at assembly time, never per render: the set of contributed
        panels is a property of how the shell was assembled, and an extension
        that answered differently on a later call would make the mount table
        unreadable.
        """


def _route_ownership_breach(binding: ViewBinding,
                            contributed_routes: Iterable[Any]) -> Any | None:
    """The first contributed route this binding may not name, or `None`.

    § 2.2 RULE 1 — *"A class-A or class-C file may not name a route ANOTHER
    COLUMN declares"* — and § 4.5 assertion 2's scope, verbatim: every binding
    whose class is not B. **Class B is exempt BY CONSTRUCTION: a gate-loop
    binding naming a gate route is the boundary working.**

    WHAT COUNTS AS "ANOTHER COLUMN DECLARES" IS NOT A LITERAL TABLE HERE, and
    that is the point. The note's § 3.3 writes the ownership table out by hand
    because a design note has nothing else to write it against; this seam has
    something better — the `RouteBinding`s another column actually CONTRIBUTED
    through `route_extension.collect_bindings`. A table would be a second copy
    of the routing, drifting the moment a column adds a route; the contributed
    bindings ARE the routing. So the caller passes what it collected, and the
    refusal is derived from the assembly rather than asserted about it.

    Matching is `RouteBinding.matches`' own semantics without its method
    argument: a view binding declares the PATH it calls, and which HTTP method
    it uses is the binding's own business — a path under a contributed POST
    prefix is that column's whether the view GETs it or POSTs it.

    Deliberately takes the contributed bindings STRUCTURALLY (`pattern`,
    `is_prefix`) rather than by `isinstance(RouteBinding)`: the client mirror
    reads the same three fields out of JSON, and holding the two halves to one
    matching rule is worth more than a type check this module cannot make of a
    payload anyway.
    """
    if binding.view_class == "B":
        return None
    for route in binding.routes:
        for contributed in contributed_routes:
            pattern = getattr(contributed, "pattern", None)
            if not isinstance(pattern, str):
                raise ViewBindingError(
                    f"contributed route {contributed!r} carries no string "
                    "pattern, so no view binding can be checked against it")
            is_prefix = bool(getattr(contributed, "is_prefix", False))
            if route == pattern or (is_prefix and route.startswith(pattern)):
                return contributed
    return None


def _ownership_message(binding: ViewBinding, contributed: Any) -> str:
    pattern = getattr(contributed, "pattern", "?")
    return (
        f"view binding {binding.id!r} is class {binding.view_class} and "
        f"declares route {pattern!r}, which another column contributed. RULED "
        "Q3 (openxFactory#656 comment 5642758731): a route constant travels "
        "with the BINDING THAT CALLS IT, never with the model that happens to "
        "declare it — so this route belongs to a class-B binding that column "
        "supplies, and this binding asks the registry for it. § 2.2 rule 1: a "
        "class-A or class-C file may not name a route another column declares; "
        "class B is exempt by construction.")


def collect_view_bindings(extensions, *,
                          contributed_routes: Iterable[Any] = ()) -> tuple[ViewBinding, ...]:
    """Flatten the extensions into ONE mount order, refusing what cannot mount.

    `collect_bindings`' contract, one tier out. Refuses an object that does not
    conform, a `views()` that yields anything but `ViewBinding`s, two bindings
    claiming one (region, id) slot, and — the refusal this seam adds — a
    non-class-B binding declaring a route another column contributed
    (`_route_ownership_breach`).

    ORDER IS DECLARATION ORDER, FLAT. `collect_bindings` re-orders (every exact
    binding before every prefix one) because an HTTP dispatcher consults its
    table until something matches and a prefix must not swallow a sibling's
    exact route. Nothing here is consulted that way: a panel mounts into the ONE
    region it names, and two panels in one region are a refused collision rather
    than a race. Re-ordering would therefore only take away the one thing
    declaration order is good for — the order panels appear in a region — so it
    is kept, and the CORE arm is first because the caller passes it first.

    `contributed_routes` is what `route_extension.collect_bindings` returned for
    this same assembly, or the equivalent read out of a manifest. Empty — slice
    S3's own case, and every static image's — means no column has claimed a
    route, so no view binding can breach rule 1 and the check is a no-op rather
    than a silent pass: there is nothing to breach.
    """
    collected: list[ViewBinding] = []
    #: The FULL previous binding, not just its module — so a collision message
    #: names what the previous binding was actually declared as.
    seen: dict[tuple[str, str], ViewBinding] = {}
    routes = tuple(contributed_routes)
    for extension in extensions:
        if not isinstance(extension, ViewExtension):
            raise ViewBindingError(
                f"{extension!r} does not conform to ViewExtension: it must "
                f"declare {list(MEMBERS)}")
        # `isinstance(extension, ViewExtension)` ONLY CHECKS THAT `views`
        # EXISTS — `runtime_checkable` verifies membership, never callability
        # or a method's return shape (Copilot, PR #14: `views = 1` and
        # `views()` returning `None` both pass the check above and then raise
        # a raw `TypeError` two lines down, never the `ViewBindingError` every
        # other declaration defect in this module promises). Checked here,
        # explicitly, rather than trusted to the Protocol.
        views_member = getattr(extension, "views", None)
        if not callable(views_member):
            raise ViewBindingError(
                f"{extension!r} does not conform to ViewExtension: views is "
                f"{views_member!r}, which is not callable")
        declared = views_member()
        if not isinstance(declared, (list, tuple)):
            raise ViewBindingError(
                f"{extension!r}.views() returned {declared!r}: the protocol "
                "promises tuple[ViewBinding, ...], and a value this module "
                "cannot iterate more than once safely is not that")
        for binding in declared:
            if not isinstance(binding, ViewBinding):
                raise ViewBindingError(
                    f"{extension!r} contributed {binding!r}, which is not a "
                    "ViewBinding")
            previous = seen.get(binding.slot)
            if previous is not None:
                raise ViewBindingError(
                    f"two view bindings claim region {binding.region!r} slot "
                    f"{binding.id!r}: {previous.module!r} and "
                    f"{binding.module!r}. The second could never mount, and a "
                    "panel that looks declared and never renders is worse than "
                    "one that refuses.")
            breach = _route_ownership_breach(binding, routes)
            if breach is not None:
                raise ViewBindingError(_ownership_message(binding, breach))
            seen[binding.slot] = binding
            collected.append(binding)
    return tuple(collected)


def dom_regions() -> tuple[str, ...]:
    """The regions `index.html` itself declares, in `REGIONS`' declared order.

    The subset a contributed binding can mount into without the shell building a
    host for it — each one an element of the shell whose `id` is the region's
    name. `tests/test_view_registry.py` holds this against the file.
    """
    return tuple(name for name, kind in REGIONS.items() if kind == "dom")


def host_view_extensions(profile: Any = None) -> tuple[Any, ...]:
    """The host's contributed view extensions — ONE more facet of the ONE
    registered profile, resolved through the SAME lazy proxy.

    TWO ABSENCES, TWO ANSWERS, and the asymmetry with `ROUTE_EXTENSIONS` is
    deliberate and argued:

    * **NO HOST REGISTERED -> REFUSES.** `domain_profile.current()` raises
      `ProfileNotRegistered` naming the registration call and the runbook, and
      this function lets it through untouched. That is ASK-2's "REFUSAL, NOT A
      DEFAULT" and it needs no help from here: `build_server()` already refuses
      at its own read of `ROUTE_EXTENSIONS`, three statements before anything
      could ask for a view.
    * **HOST REGISTERED, NO `VIEW_EXTENSIONS` FACET -> AN EMPTY CONSUMER
      COLUMN.** `profile_proxy.ProfileFacetMissing` subclasses `AttributeError`
      precisely so that `getattr(profile, name, default)` answers, and its own
      docstring blesses the spelling. The empty answer is CORRECT here where an
      empty `ROUTE_EXTENSIONS` would be a defect, because the two absences mean
      different things: a server missing its contributed ROUTES looks exactly
      like a working one until someone requests a path that 404s, whereas a
      shell with no contributed PANELS is the shell this leg ships today and the
      state the note's S3 row describes in its own words — *"nothing is
      contributed yet, so the shell renders exactly as today with an empty
      extension tuple."* Refusing here would make every host that has not yet
      grown the facet — which is every host, today — unable to serve at all: a
      flag day imposed by the seam that was added to avoid one.

      **AND THE ABSENCE IS NAMED, NEVER SILENT.** `view_manifest` carries
      `host_facet` = "declared" or "absent" with the facet name and the
      registered profile's name, so a host debugging a panel that never appeared
      reads the reason out of the payload the page already fetches instead of
      inferring it. That is the honest middle the note's own § 4.3 point 5 asks
      for — "a class-C module with no profile registered renders its region
      empty WITH A NAMED REASON" — applied to a facet rather than to a profile.

    `profile` is the seam a test injects through; absent, the module resolves the
    real proxy at CALL time (never at import time — the whole value of the lazy
    proxy is that importing it cannot fail for want of a host).
    """
    if profile is None:
        from opendox.profile_proxy import profile_openxfactory
        profile = profile_openxfactory
    declared = getattr(profile, PROFILE_FACET, None)
    if declared is None:
        return ()
    return tuple(declared)


def view_manifest(bindings: Iterable[ViewBinding], *,
                  contributed_routes: Iterable[Any] = (),
                  host_facet: str = "absent",
                  host_profile: str | None = None) -> dict[str, Any]:
    """The payload the client reads — the ONE crossing of the process boundary.

    Carries `schema_version` and `kind` because every declared document in this
    estate does (openxFactory `CLAUDE.md` working rule 4), and because a payload
    the shell must be able to REFUSE needs to be identifiable before it is
    trusted.

    `contributed_routes` travels with the views so the CLIENT can apply the same
    § 2.2 rule 1 refusal to a binding it reads out of this payload — the two
    halves check the same thing against the same facts, which is what keeps a
    seam from becoming two seams.

    `host_facet` / `host_profile` are the NAMED ABSENCE `host_view_extensions`
    argues for: "absent" plus the profile's name says a host IS registered and
    simply does not contribute panels, which is a different fact from no host at
    all and a different fact again from a host that contributes none.
    """
    if host_facet not in ("declared", "absent"):
        raise ViewBindingError(
            f"host_facet {host_facet!r} must be 'declared' or 'absent': the "
            "manifest states WHY the consumer column is empty, and a third "
            "answer would say nothing")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "kind": MANIFEST_KIND,
        "facet": PROFILE_FACET,
        "host_facet": host_facet,
        "host_profile": host_profile,
        "regions": {name: kind for name, kind in REGIONS.items()},
        "contributed_routes": [
            {
                "method": getattr(route, "method", None),
                "pattern": getattr(route, "pattern", None),
                "is_prefix": bool(getattr(route, "is_prefix", False)),
            }
            for route in contributed_routes
        ],
        "views": [binding.as_manifest_entry() for binding in bindings],
    }
