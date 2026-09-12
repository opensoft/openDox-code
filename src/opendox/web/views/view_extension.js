// THE VIEW REGISTRY — the front end's `route_extension.py`, in the language the
// shell is written in (openDox-spec `docs/front-end-package-boundary.md` § 4.1,
// slice S3; RULED openxFactory#656 comment 5642758731).
//
// THE FILE NAME IS THE NOTE'S, not this folder's convention. Every other module
// here is kebab-case (`repo-selector.js`, `wheel-model.js`); the note's S3 row
// names `views/view_extension.js` and it is named that, because the whole point
// of the file is that it MIRRORS `src/route_extension.py` and
// `src/opendox/view_extension.py` — three files, one seam, one spelling.
//
// WHAT IT IS FOR. The bundle is 42 files in one flat folder with one import
// graph, "no subdirectory, no manifest, no naming convention, no lint rule and
// no test that says which module may import which" (§ 1.2(a)). The Python side
// answered the same question three times — a contributed ROUTE
// (`route_extension`), a late REACH into the consumer (`consumer_reach`), and a
// registered PROFILE (`domain_profile` + `profile_proxy`) — and § 4.1 says to
// reuse those shapes rather than invent a fourth. So:
//
//   `route_extension.RouteBinding`      ->  a ViewBinding
//   `route_extension.collect_bindings`  ->  collectViewBindings
//   `consumer_reach.route_column`       ->  resolveView / requireView, which
//                                           make a reach into a column that may
//                                           not be installed LATE, NAMED and
//                                           REFUSABLE instead of an import
//
// THE ONE RULE, and the reason the shell stops importing class-B modules: a
// contributed panel is the profile; a second copy of the shell is the fork. A
// binding declares WHERE it mounts, WHAT module mounts it, WHICH routes it
// calls (RULED Q3: "a route constant travels with the binding that calls it,
// never with the model that happens to declare it") and WHETHER the shell is
// correct without it. The shell then renders whatever it collected — so an
// install with no gate column comes up with no gate bar, no dispose tray and no
// 404, which is RULING C2 one tier out and the thing § 3.4 exists to protect.
//
// THE AUTHORITY IS `src/opendox/view_extension.py`, NOT THIS FILE. That module
// collects the host's contributions server-side, refuses the same four things,
// and renders the JSON manifest this file reads back out of `/capabilities`
// (`contributedViewBindings`). The two halves are held to one vocabulary by
// `tests/test_view_registry.py`, which parses the constants below and compares
// them with the Python ones — a drift test, on the pattern openxFactory's
// `carved_reach.py` scrub list already uses.
//
// A CREATED FILE: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
// (RULED OQ-C).

// § 2.1's three destination classes: A openDox core, B the gate loop, C a
// stage-named region. Kept in step with `view_extension.py`'s `VIEW_CLASSES`.
// `"?"` is the TRANSITIONAL class § 4.5 assertion 1 declares — "a class the
// census may carry only until S4" — carried because the five SPLIT files each
// hold class-A or class-C substance AND a class-B tail. It is IN SCOPE for the
// route-ownership refusal, as § 4.5 assertion 2 says: "class A, class C AND the
// transitional `?`, which is where most of the breaches actually sit."
export const VIEW_CLASSES = ["A", "B", "C", "?"];

// THE SHELL'S DECLARED MOUNT POINTS, and the whole of them. A `"dom"` region is
// declared by `index.html` itself, as an element whose `id` IS the region name
// — the seven `view-*` tab panels and the two overlay roots. A `"shell"` region
// has no standing element: the shell builds the host at mount time and hands it
// to the binding. `tests/test_view_registry.py` holds this table against
// `index.html` and against the Python half, so the three never drift apart.
//
// `viewer-gatebar` is the viewer's own gate-bar host (`viewer.js` builds the
// div and calls `mountGate`). `lens-gate` and `repo-projects` are slice S4's,
// added when the two new class-B bindings that mount into them arrived:
// `lens-gate` is the lens plan panel's execute box (`views/gate-lens.js`) and
// `repo-projects` is the selector's project-commission slot
// (`views/gate-projects.js`). Both are "shell" for the same reason
// `viewer-gatebar` is — the host is built by the view at mount time and handed
// over, so `index.html` has no element to declare. `wheel-intent` and
// `dispose-intent` are slice S2's, declared NOW so S2's optional intent-chip
// bindings fold in without re-opening this file: § 6 Q5 rules that "the chips become an OPTIONAL
// contributed binding — absent, the wheel and the tray render without them",
// and `optional: true` plus `lookupView()` is exactly that shape. Declaring a
// region costs nothing; an undeclared one costs a slice.
export const REGIONS = {
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
  // SLICE S5's THREE. `page-overlay` is RULED Q8 (openxFactory#656 comment
  // 5648049748): "a fourth `shell` region, `page-overlay`, is the declared host
  // for page-level panels (dispose.js's refusal panel); `document.body` is never
  // a contract surface." The SHELL builds this host — `app.js` does, because
  // `index.html` is a `moved_verbatim` carve row and an added element is in none
  // of its declared edit classes — and hands it to the binding, which is exactly
  // what "shell" means here. `workbench-create` and `workbench-session` are the
  // staging workbench's two caller-built hosts, added with the bindings that
  // mount into them on slice S4's own precedent (`lens-gate`, `repo-projects`).
  "page-overlay": "shell",
  "workbench-create": "shell",
  "workbench-session": "shell",
};

// THE CONTEXT OBJECT'S DECLARED KEYS — what a binding mounted at a region may
// read off the third argument of `mount(host, snapshot, ctx)` (RULED Q3,
// openxFactory#656 comment `5648044785`). Declared for the same reason REGIONS
// is: the counterpart note's § 3 asks what a contributed binding "may assume
// about the shell … the context object's shape", and a shape that is only ever
// an object literal in `app.js` is an assumption rather than a contract.
//
// `display` is SLICE S7's ONE ADDITION (§ 4.3 step 3: "`app.js` puts that facet
// in the context object every binding already receives"). It is the vocabulary
// reader of `views/display.js`, built from `/capabilities`' `display` block:
// `ctx.display.label(role)`, `.one(role)`, `.many(role)`, `.status(vocabulary,
// role)`, `.area(role)`, `.token(role)`, `.items(snapshot, role)` — every one
// of them resolved BY ROLE and never by a word. A contributed column renders
// the registered domain's vocabulary by reading it, exactly as openDox's own
// class-C views do, and inherits the neutral words when no host declares any.
//
// The Python half carries the same table (`view_extension.CTX_KEYS`) and
// `tests/test_display_facet.py` holds the two against each other, as
// `tests/test_view_registry.py` already does for REGIONS.
export const CTX_KEYS = {
  caps: "the capability probe, composed-stripped where the render is composed",
  views: "the collected view registry — `lookupView(ctx.views, id)`",
  nav: "the shell's cross-view navigation verbs, or null outside a tab",
  display: "the registered domain's vocabulary, resolved BY ROLE (slice S7)",
  signal: "the render's AbortSignal, for any listener bound outside own root",
};

export const MANIFEST_KIND = "opendox.view-manifest";
export const MANIFEST_SCHEMA_VERSION = 1;

// Narrow on purpose, and identical to the Python `_ID`: the id travels into
// JSON, into a refusal message and into a DOM attribute.
const ID = /^[a-z0-9]+(?:[-.][a-z0-9]+)*$/;
// A bundle-relative ES module specifier and nothing else. No root-relative path
// (it breaks a served sub-path), no absolute URL — § 4.4's vendor policy is "no
// CDN, no external font, no remote script", and a contributed binding is
// exactly the hole that policy would leak through if this seam did not close
// it.
const MODULE = /^\.\/[A-Za-z0-9_./-]+\.js$/;

// One error for every declaration defect, for `RouteBindingError`'s reason: a
// caller does nothing different for any of them — they are all "this shell must
// not be assembled this way".
export class ViewBindingError extends Error {
  constructor(message) {
    super(message);
    this.name = "ViewBindingError";
  }
}

function refuse(message) {
  throw new ViewBindingError(message);
}

// One contributed panel, validated where it is DECLARED rather than where it is
// mounted — `RouteBinding.__post_init__`'s discipline, for the same reason: a
// binding is declared once at assembly time and consulted on every render.
//
// `mount` and `control` are the two fields the MANIFEST does not carry and the
// core arm does. `mount` is a function the shell already imported (the core arm
// holds its own view modules statically, and always will — they are the
// product); `control` is the id of the tab button that activates the panel, so
// the tab strip is derived from the registry instead of duplicated beside it.
// A CONTRIBUTED binding has neither: it arrives as JSON and is loaded through
// `resolveView`.
export function viewBinding(spec) {
  const b = spec || {};
  if (typeof b.id !== "string" || !ID.test(b.id)) {
    refuse("view binding id " + JSON.stringify(b.id) + " must be a dotted "
      + "lowercase slug (e.g. 'gate.bar')");
  }
  if (!Object.prototype.hasOwnProperty.call(REGIONS, b.region)) {
    refuse("view binding " + JSON.stringify(b.id) + " names region "
      + JSON.stringify(b.region) + ", which the shell does not declare "
      + "(declared: " + Object.keys(REGIONS).join(", ") + "). A panel bound to "
      + "a region that does not exist is silently unmounted.");
  }
  if (typeof b.module !== "string" || !MODULE.test(b.module)
      || b.module.split("/").includes("..")) {
    refuse("view binding " + JSON.stringify(b.id) + " names module "
      + JSON.stringify(b.module) + ": a contributed module must be a "
      + "bundle-relative './…js' specifier that does not climb out of the "
      + "bundle. An absolute URL is a remote script, which § 4.4's vendor "
      + "policy forbids outright.");
  }
  if (typeof b.entry !== "string" || !/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(b.entry)
      || b.entry.startsWith("__")) {
    refuse("view binding " + JSON.stringify(b.id) + " names entry "
      + JSON.stringify(b.entry) + ": an entry is the NAME of an export on the "
      + "binding's module, never a callable — the manifest crosses a process "
      + "boundary as JSON.");
  }
  if (!VIEW_CLASSES.includes(b.view_class)) {
    refuse("view binding " + JSON.stringify(b.id) + " declares class "
      + JSON.stringify(b.view_class) + ", not one of " + VIEW_CLASSES.join("/")
      + " (§ 2.1: A openDox core, B the gate loop, C a stage-named region)");
  }
  // RULED Q2 (openxFactory#656 comment 5648049748): "a binding's contract is
  // its module NAMESPACE, DECLARED as an `exports` tuple: every export the
  // shell may reach is listed on the binding and validated the way `entry` is;
  // an undeclared reach (today `isGateBearing`, app.js:939) is a refusal."
  // Empty means `entry` alone — the pre-Q2 contract every core-arm binding
  // still declares. Non-empty must CONTAIN `entry`: the mount is the first
  // member of the namespace, and a tuple that omitted it would declare a
  // contract its own entry breaks.
  const exported = b.exports === undefined ? [] : b.exports;
  if (!Array.isArray(exported)
      || exported.some((name) => typeof name !== "string"
        || !/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name) || name.startsWith("__"))) {
    refuse("view binding " + JSON.stringify(b.id) + " declares exports "
      + JSON.stringify(exported) + ": every entry is the NAME of an export on "
      + "the binding's module, held to the same grammar `entry` is");
  }
  if (exported.length && !exported.includes(b.entry)) {
    refuse("view binding " + JSON.stringify(b.id) + " declares exports "
      + JSON.stringify(exported) + " that do not include its own entry "
      + JSON.stringify(b.entry) + ": RULED Q2 makes the tuple the WHOLE "
      + "namespace the shell may reach, and the mount is the first member of it.");
  }
  const routes = b.routes === undefined ? [] : b.routes;
  if (!Array.isArray(routes) || routes.some((r) => typeof r !== "string" || !r.startsWith("/"))) {
    refuse("view binding " + JSON.stringify(b.id) + " declares routes "
      + JSON.stringify(routes) + ": every declared route is a path rooted at '/'");
  }
  const requires = b.requires === undefined ? [] : b.requires;
  if (!Array.isArray(requires) || requires.some((r) => typeof r !== "string" || !r)) {
    refuse("view binding " + JSON.stringify(b.id) + " declares requires "
      + JSON.stringify(requires) + ": every entry is a capability or facet name");
  }
  const optional = b.optional === undefined ? false : b.optional;
  if (typeof optional !== "boolean") {
    refuse("view binding " + JSON.stringify(b.id) + " declares optional "
      + JSON.stringify(optional) + ", which is not a boolean");
  }
  if (b.mount !== undefined && typeof b.mount !== "function") {
    refuse("view binding " + JSON.stringify(b.id) + " declares a mount that is "
      + "not a function; a contributed binding declares no mount at all and is "
      + "loaded through resolveView()");
  }
  if (b.control !== undefined && typeof b.control !== "string") {
    refuse("view binding " + JSON.stringify(b.id) + " declares a control that "
      + "is not an element id");
  }
  return Object.freeze({
    id: b.id,
    region: b.region,
    module: b.module,
    entry: b.entry,
    view_class: b.view_class,
    exports: Object.freeze(exported.slice()),
    routes: Object.freeze(routes.slice()),
    requires: Object.freeze(requires.slice()),
    optional,
    mount: b.mount,
    control: b.control,
    // What makes two bindings the SAME panel — never the module. Two bindings
    // claiming one (region, id) are a collision whichever modules they name.
    slot: b.region + "\u0000" + b.id,
  });
}

// § 2.2 RULE 1 — "a class-A or class-C file may not name a route ANOTHER COLUMN
// declares" — with § 4.5 assertion 2's scope verbatim: every binding whose class
// is not B. Class B is exempt BY CONSTRUCTION; a gate-loop binding naming a gate
// route is the boundary working.
//
// "Another column declares" is not a hardcoded table here for the reason the
// Python half gives at length: the contributed `RouteBinding`s ARE the routing,
// and a table beside them would be a second copy that drifts. The client reads
// them out of the manifest (`contributed_routes`), which is the same list
// `route_extension.collect_bindings` returned server-side.
//
// ONE SHAPE CHECK, used here AND where the manifest is first read
// (`manifestRoutes`, below), so a malformed entry refuses at whichever point
// sees it first rather than only once some binding's route happens to reach
// it — a binding with no routes, or routes that never collide with THIS
// entry, would otherwise let it ride through unexamined. Mirrors
// `view_extension.py`'s `_route_ownership_breach` on `pattern` ("carries no
// string pattern"); goes one further on `is_prefix`, which that function
// reads as `bool(getattr(contributed, "is_prefix", False))` — safe there only
// because `RouteBinding.__post_init__` already refused a non-bool `is_prefix`
// at CONSTRUCTION, before `_route_ownership_breach` ever runs. JSON off
// `/capabilities` has no constructor to have refused it first, so a
// non-boolean here (Copilot, PR #16, `view_extension.js:358`) must refuse
// rather than fall through a truthy check (`claimed.is_prefix && …`), which
// silently reads a missing or malformed field as "not a prefix" — the wrong
// answer for a payload nobody has vetted yet.
function requireRouteShape(claimed) {
  const pattern = claimed && claimed.pattern;
  if (typeof pattern !== "string") {
    refuse("contributed route " + JSON.stringify(claimed) + " carries no "
      + "string pattern, so no view binding can be checked against it");
  }
  const isPrefix = claimed && claimed.is_prefix;
  if (typeof isPrefix !== "boolean") {
    refuse("contributed route " + JSON.stringify(claimed) + " declares "
      + "is_prefix " + JSON.stringify(isPrefix) + ", not a boolean: a "
      + "contributed route this seam cannot classify as exact-or-prefix must "
      + "not be silently read as neither");
  }
  return { pattern, isPrefix };
}

function ownershipBreach(binding, contributedRoutes) {
  if (binding.view_class === "B") return null;
  for (const route of binding.routes) {
    for (const claimed of contributedRoutes) {
      const { pattern, isPrefix } = requireRouteShape(claimed);
      if (route === pattern || (isPrefix && route.startsWith(pattern))) {
        return pattern;
      }
    }
  }
  return null;
}

// Flatten the extensions into ONE mount order, refusing what cannot mount —
// `collect_bindings`' contract, one tier out.
//
// An extension is anything with a `views()` returning an array of binding specs;
// structural conformance, never nominal, for `RouteExtension`'s reason: a
// binding authored in the column that PINS openDox must conform without
// importing anything from here.
//
// ORDER IS DECLARATION ORDER, FLAT. `collect_bindings` re-orders exact before
// prefix because an HTTP dispatcher consults its table until something matches;
// nothing here is consulted that way — a panel mounts into the ONE region it
// names, and two panels in one region are a refused collision rather than a
// race. So declaration order is kept, and it is the order panels appear in a
// region.
export function collectViewBindings(extensions, options) {
  const contributedRoutes = (options && options.contributedRoutes) || [];
  const collected = [];
  const seen = new Map();
  for (const extension of extensions || []) {
    if (!extension || typeof extension.views !== "function") {
      refuse(JSON.stringify(String(extension)) + " does not conform to a view "
        + "extension: it must declare views()");
    }
    const declared = extension.views();
    if (!Array.isArray(declared)) {
      refuse("a view extension's views() must return an array of bindings, got "
        + JSON.stringify(String(declared)));
    }
    for (const spec of declared) {
      const binding = viewBinding(spec);
      const previous = seen.get(binding.slot);
      if (previous) {
        refuse("two view bindings claim region " + JSON.stringify(binding.region)
          + " slot " + JSON.stringify(binding.id) + ": "
          + JSON.stringify(previous.module) + " and "
          + JSON.stringify(binding.module) + ". The second could never mount, "
          + "and a panel that looks declared and never renders is worse than "
          + "one that refuses.");
      }
      const breach = ownershipBreach(binding, contributedRoutes);
      if (breach) {
        refuse("view binding " + JSON.stringify(binding.id) + " is class "
          + binding.view_class + " and declares route " + JSON.stringify(breach)
          + ", which another column contributed. RULED Q3 "
          + "(openxFactory#656 comment 5642758731): a route constant travels "
          + "with the BINDING THAT CALLS IT, never with the model that happens "
          + "to declare it.");
      }
      seen.set(binding.slot, binding);
      collected.push(binding);
    }
  }
  return collected;
}

// THE CONSUMER COLUMN, read out of the payload the shell already fetches once at
// load. § 4.3's rule for the profile's display facet applies here unchanged —
// "no new route and no second fetch" — so the view manifest rides on
// `/capabilities` beside the capability verdict.
//
// ABSENT MEANS AN EMPTY COLUMN, NOT A REFUSAL, and that is the honest reading in
// three different situations that all look the same from here: a static served
// image (no `/capabilities` at all), a host whose profile carries no
// `VIEW_EXTENSIONS` facet, and — today — every host, because the server-side
// line that publishes the manifest is slice S5's (see `view_extension.py`'s own
// note on why). MALFORMED, by contrast, REFUSES: a payload that claims to be a
// view manifest and is not is a contribution nobody can reason about, and
// failing closed is the only safe answer for something that decides which code
// the shell imports.
export function contributedViewBindings(capabilities) {
  const manifest = capabilities && capabilities.views;
  if (manifest === undefined || manifest === null) return [];
  if (typeof manifest !== "object" || Array.isArray(manifest)) {
    refuse("the /capabilities payload carries a `views` that is not a view "
      + "manifest object");
  }
  if (manifest.kind !== MANIFEST_KIND) {
    refuse("the /capabilities `views` payload declares kind "
      + JSON.stringify(manifest.kind) + ", not " + JSON.stringify(MANIFEST_KIND));
  }
  if (manifest.schema_version !== MANIFEST_SCHEMA_VERSION) {
    refuse("the /capabilities `views` payload declares schema_version "
      + JSON.stringify(manifest.schema_version) + ", and this shell reads "
      + MANIFEST_SCHEMA_VERSION + ". A shell that guessed at an unknown "
      + "manifest version would be importing code it cannot describe.");
  }
  const views = manifest.views;
  if (!Array.isArray(views)) {
    refuse("the /capabilities `views` payload carries no views array");
  }
  // `mount` AND `control` ARE THE CORE ARM'S AND A CONTRIBUTED ENTRY MAY NOT
  // CARRY THEM — refused here rather than ignored, because ignoring them is a
  // crash with a delay on it. `control` is what makes a binding a TAB, and a
  // contributed entry cannot have the `mount` FUNCTION the tab router calls
  // (it arrived as JSON, and `view_manifest()` emits neither field), so a
  // manifest naming a control would put an entry in the tab strip whose
  // `mount` is `undefined` and crash on the click that selects it. A binding
  // this seam cannot mount must not look registered — `resolveView`'s own rule,
  // applied one step earlier, where the payload is read.
  for (const spec of views) {
    const named = ["mount", "control"].find(
      (field) => spec && spec[field] !== undefined);
    if (named) {
      refuse("the /capabilities `views` payload declares " + named + " on "
        + JSON.stringify(spec && spec.id) + ": `mount` and `control` belong to "
        + "the shell's own core arm and cannot cross the process boundary. A "
        + "contributed binding names a module and an entry and is loaded "
        + "through resolveView().");
    }
  }
  return views.map(viewBinding);
}

// The contributed routes the manifest travelled with — what `collectViewBindings`
// checks § 2.2 rule 1 against, so both halves of the seam check the same thing
// against the same facts.
export function manifestRoutes(capabilities) {
  const manifest = capabilities && capabilities.views;
  // ABSENT MEANS AN EMPTY COLUMN, exactly `contributedViewBindings`' own
  // reading of no manifest at all. MALFORMED DOES NOT: `view_manifest()`
  // always emits `contributed_routes` as an array (Copilot, PR #14), so a
  // manifest that is PRESENT but carries anything else there is not making a
  // true claim of "no contributed routes" — it is malformed, and reading it
  // as `[]` would silently disable every binding's § 2.2 rule 1 check rather
  // than fail closed the way this seam promises for anything it cannot
  // reason about.
  if (manifest === undefined || manifest === null) return [];
  const routes = manifest.contributed_routes;
  if (!Array.isArray(routes)) {
    refuse("the /capabilities `views` payload declares contributed_routes "
      + JSON.stringify(routes) + ", not an array: view_manifest() always "
      + "emits this field as one, and a manifest that cannot be trusted for "
      + "contributed_routes cannot be trusted for the ownership check that "
      + "field exists to carry.");
  }
  // EVERY ENTRY, NOT JUST THE ARRAY ITSELF (Copilot, PR #16,
  // `view_extension.js:358`): the array check alone let an entry missing
  // `pattern` or `is_prefix` — or carrying either as the wrong type — ride
  // through as "valid" contributed_routes, because `ownershipBreach()` only
  // ever inspected an entry when some binding's route reached it. Validating
  // every entry here, at the one place the whole manifest is read, means a
  // malformed entry refuses whether or not any binding's routes would have
  // exposed it.
  routes.forEach(requireRouteShape);
  return routes;
}

// ---- RULED Q4: `requires` NAMES DOTTED PATHS INTO THE /capabilities PAYLOAD --
//
// openxFactory#656 comment 5648049748, Brett Heap, 2026-09-12: "`requires`
// names DOTTED PATHS into the `/capabilities` payload; unmet + `optional: true`
// renders the region empty with a NAMED reason; unmet + required REFUSES,
// naming the binding, the path and the probed value."
//
// THIS IS THE OBLIGATION openDox-spec § 5.1 NAMES MOST DIRECTLY, and until this
// slice it was the one with no code behind it: the field was declared
// (`view_extension.py`:248-251), validated, carried into the manifest and
// mirrored here, and NO LINE OF EITHER HALF READ IT — so "a binding declaring
// `requires` is declaring an intention the shell does not act on"
// (openXdox-spec `docs/gate-loop-view-contract.md` § 4.4 @ d73767b7). These
// three functions are the act.
//
// A MISSING PAYLOAD IS AN UNMET REQUIREMENT, NOT AN ERROR. `probeCapabilities()`
// degrades a failed probe to `{ actions: { notebook: false } }`, and a static
// served image 404s the route entirely — so `undefined` at the end of the path
// is the honest answer "this plane does not offer it", which is exactly what an
// unmet requirement is. Only a TRUTHY value meets one; `false`, `null`, `0` and
// `""` are all "off", because every capability this payload carries is a
// verdict and a falsy verdict is a no.
//
// AN OWN PROPERTY OR NOTHING (Copilot review, round 2). An ordinary property
// read walks the prototype chain, so `requires: ["toString"]` resolved to a
// function, answered truthy, and MET a requirement no `/capabilities` payload
// ever carried — as would `constructor`, `valueOf` and every other
// `Object.prototype` member. The payload is JSON this shell did not write and a
// requirement is a gate, so the probe reads only what the object itself
// carries: a malformed or hostile manifest fails CLOSED, which is the posture
// every other refusal in this file takes.
export function probeCapabilityPath(capabilities, path) {
  let cursor = capabilities;
  for (const segment of String(path).split(".")) {
    if (cursor === null || cursor === undefined || typeof cursor !== "object") {
      return undefined;
    }
    if (!Object.prototype.hasOwnProperty.call(cursor, segment)) return undefined;
    cursor = cursor[segment];
  }
  return cursor;
}

// The FIRST unmet requirement of a binding, or null. First and not all, for
// `_route_ownership_breach`'s reason: the caller does nothing different for a
// second one, and naming one path a human can go and look at beats naming
// three.
export function unmetRequirement(binding, capabilities) {
  for (const path of (binding && binding.requires) || []) {
    const value = probeCapabilityPath(capabilities, path);
    if (!value) return { path, value };
  }
  return null;
}

// The sentence a human reads when a binding's `requires` is unmet — the refusal
// text openDox-spec § 5.1 asks this seam for and § 5 of the contract note
// records as "there is none". It names the binding, the path and the PROBED
// VALUE, because "unmet" and "the payload does not carry that key at all" are
// different facts for the column debugging its own contribution.
export function requirementRefusal(binding, unmet) {
  return "view binding " + JSON.stringify(binding.id) + " requires "
    + JSON.stringify(unmet.path) + ", which this plane's /capabilities payload "
    + "answers as " + JSON.stringify(unmet.value === undefined ? null : unmet.value)
    + (unmet.value === undefined ? " (the path is not carried at all)" : "")
    + ". A binding that is correct to be absent declares `optional: true`; a "
    + "required one refuses here rather than mounting a panel whose verbs can "
    + "only be refused.";
}

// An OPTIONAL reach: the binding, or null. This is `consumer_reach`'s posture
// in the browser — a reach into a column that may not be installed is LATE and
// NAMED, and the caller decides what absence means. § 6 Q5's intent chips and
// the gate bar are both read this way.
export function lookupView(bindings, id) {
  for (const binding of bindings || []) {
    if (binding.id === id) return binding;
  }
  return null;
}

// A REQUIRED reach: the binding, or a refusal that names the layering rather
// than a blank panel. `consumer_reach`'s "refuses with the layering spelled out
// instead of raising ModuleNotFoundError from an import line a thousand lines
// away from the call", and `build_server()`'s "refusal, not a default".
export function requireView(bindings, id) {
  const found = lookupView(bindings, id);
  if (found) return found;
  refuse("no view binding " + JSON.stringify(id) + " is registered. This shell "
    + "was assembled without the column that contributes it; a binding that is "
    + "correct to be absent must declare `optional: true` and be read with "
    + "lookupView().");
}

// Load a binding's module and hand back its namespace — the front end's
// `route_extension.resolve_handlers`, deferred to first use rather than done at
// wiring time, because a browser pays for an import and a process does not.
//
// Returns null for an absent OPTIONAL binding, so a caller can write
//   const gate = await resolveView(views, "gate.bar");
// and then treat `gate` being null as "no gate column here" — which is exactly
// what a student install is. An absent REQUIRED binding refuses through
// `requireView`.
//
// The specifier is resolved against the BUNDLE ROOT (`./views/gate.js` is what
// `app.js` would have written), not against this module's own folder.
export async function resolveView(bindings, id, options) {
  const binding = lookupView(bindings, id);
  if (!binding) return null;
  return resolveBinding(binding, options);
}

// The same resolution, given the BINDING ITSELF rather than an id to look one
// up by — the form a caller that is already holding a binding must use.
//
// WHY IT IS SEPARATE (Copilot review, round 2). Bindings are unique by SLOT,
// `region + id` (`viewBinding()`), so the registry deliberately permits one id
// in two regions — two columns may each contribute a `gate.bar` into their own
// region and neither is a collision. `lookupView()` answers by id alone and
// returns the FIRST match, so the generic mount pass, iterating the bindings
// and re-resolving each by `binding.id`, would have mounted the FIRST
// binding's module and entry into the SECOND binding's region: a panel
// rendering another column's module, with nothing refused and nothing logged.
// The pass holds the binding already; it resolves THAT one.
export async function resolveBinding(binding, options) {
  if (!binding) return null;
  // RULED Q4, at the ONE place every named reader already goes through. A
  // caller that passes `capabilities` gets the requirement evaluated here:
  // an unmet requirement on an OPTIONAL binding answers `null`, which every
  // reader in this shell already reads as "the column that supplies it is not
  // installed"; on a REQUIRED one it refuses, naming the binding, the path and
  // the probed value. A caller that passes none is asking for the binding and
  // not for the verdict — `collectViewBindings`' own tests do exactly that.
  if (options && "capabilities" in options) {
    const unmet = unmetRequirement(binding, options.capabilities);
    if (unmet) {
      if (!binding.optional) refuse(requirementRefusal(binding, unmet));
      return null;
    }
  }
  const bundleRoot = new URL("../", import.meta.url);
  // A REJECTED IMPORT IS A REFUSAL TOO, and one this seam names rather than
  // lets pass through raw (Copilot, PR #14): a missing file, a syntax error
  // or a circular import all reject `import()` with a native error carrying
  // no binding or module context, and the app would report a generic
  // snapshot failure instead of the "which binding, which module" every
  // other defect in this function states. `viewBinding()` already bounds
  // `module` to a bundle-relative './…js' specifier that cannot climb out of
  // the bundle, so what fails here is the file not being THERE, not the path
  // being unsafe.
  let exports;
  try {
    exports = await import(new URL(binding.module, bundleRoot).href);
  } catch (e) {
    refuse("view binding " + JSON.stringify(binding.id) + " names module "
      + JSON.stringify(binding.module) + ", which failed to load: "
      + (e && e.message ? e.message : String(e)) + ". A binding that cannot "
      + "be mounted must not look registered.");
  }
  // PRESENT IS NOT MOUNTABLE. Checking only that the name exists lets a module
  // export a string, an object or a `null` under it and still hand back a
  // binding that looks resolved; the mount call then throws a raw `TypeError`
  // from inside whatever tried to use it, which is precisely the "dangling
  // import a thousand lines from the call" this seam exists to replace. The
  // refusal says which of the two it is, because "not exported" and "exported
  // as something that cannot be called" are different defects in the
  // contributing column.
  if (!(binding.entry in exports)) {
    refuse("view binding " + JSON.stringify(binding.id) + " names entry "
      + JSON.stringify(binding.entry) + ", which "
      + JSON.stringify(binding.module) + " does not export. A binding that "
      + "cannot be mounted must not look registered.");
  }
  if (typeof exports[binding.entry] !== "function") {
    refuse("view binding " + JSON.stringify(binding.id) + " names entry "
      + JSON.stringify(binding.entry) + ", which " + JSON.stringify(binding.module)
      + " exports as " + typeof exports[binding.entry] + " rather than a "
      + "function. An entry is the export that MOUNTS the panel; a binding "
      + "that cannot be mounted must not look registered.");
  }
  // EVERY DECLARED EXPORT IS CHECKED THE WAY THE ENTRY IS (RULED Q2). A binding
  // that names an export its module does not have is a binding the shell would
  // reach for and find `undefined` in — the "dangling import a thousand lines
  // from the call" this seam replaces, one field over.
  for (const name of binding.exports) {
    if (!(name in exports)) {
      refuse("view binding " + JSON.stringify(binding.id) + " declares export "
        + JSON.stringify(name) + ", which " + JSON.stringify(binding.module)
        + " does not export. A binding whose declared namespace is not the "
        + "module's namespace must not look registered.");
    }
    // PRESENT IS NOT USABLE, one field over (Copilot review, round 2). RULED Q2
    // is "validated the way `entry` is", and `entry` is checked PRESENT and
    // CALLABLE two statements above — so a declared export is held to both.
    // Checking only the name let a module export `firstEditTransport` as a
    // string and still resolve: `app.js` reaches it through the registry and
    // calls it, and the defect would surface as a raw `TypeError` inside a
    // click handler, which is the "dangling import a thousand lines from the
    // call" this whole seam exists to replace.
    //
    // A DECLARED EXPORT IS A CALL, and that is what the tuple means: every name
    // the six gate bindings declare is a mounter, a transport or a predicate.
    // Data a contributed column must publish travels on the BINDING (`routes`,
    // `requires`) or out of a mount, both of which are declared surfaces this
    // seam already validates; a constant smuggled through the namespace would
    // be a third, undeclared one.
    if (typeof exports[name] !== "function") {
      refuse("view binding " + JSON.stringify(binding.id) + " declares export "
        + JSON.stringify(name) + ", which " + JSON.stringify(binding.module)
        + " exports as " + typeof exports[name] + " rather than a function. "
        + "RULED Q2 (openxFactory#656 comment 5648049748) validates a declared "
        + "export the way `entry` is validated, and the shell REACHES a "
        + "declared export in order to call it.");
    }
  }
  return { binding, exports: declaredNamespace(binding, exports) };
}

// THE DECLARED NAMESPACE — RULED Q2's refusal half. `resolveView` used to hand
// back the module's WHOLE namespace, and `app.js` read `isGateBearing` off it,
// an export the binding never declared and this seam never validated. The
// namespace a caller receives is now bounded by the declaration: a reach for a
// name the binding did not declare REFUSES, naming both, instead of answering
// `undefined` and failing inside whatever tried to call it.
//
// A binding with an EMPTY `exports` keeps the pre-Q2 contract — `entry` alone —
// which is what every core-arm binding declares, because the core arm's modules
// are imported statically by the shell that owns them.
//
// SYMBOLS AND `then` PASS THROUGH rather than refusing: a Proxy is probed for
// `Symbol.toStringTag` by `String()`, and any object returned from an async
// function is probed for `then` by the await that receives it. A refusal from
// either would be this seam refusing the language rather than a caller.
//
// ONE TRAP, `get`, AND THAT IS A LANGUAGE CONSTRAINT RATHER THAN A CHOICE. A
// module namespace object's exports are NON-CONFIGURABLE own properties, so the
// Proxy invariants forbid `has`, `ownKeys` and `getOwnPropertyDescriptor` from
// hiding one: a `has` trap answering false for a name the target really carries
// throws `TypeError: trap returned falsish for property … which exists in the
// proxy target as non-configurable`, which would be this seam breaking the
// caller instead of refusing it. `in` and `Object.keys()` therefore still see
// the module's whole namespace, and REACHING for an undeclared name is what
// refuses — which is exactly what RULED Q2 says is the defect: "an undeclared
// reach (today `isGateBearing`, app.js:939) is a refusal". An export is
// writable on a namespace object, so the `get` invariant does not bind and the
// refusal is lawful.
function declaredNamespace(binding, exports) {
  const allowed = new Set(binding.exports.length
    ? binding.exports : [binding.entry]);
  return new Proxy(exports, {
    get(target, property, receiver) {
      if (typeof property === "symbol" || property === "then") {
        return Reflect.get(target, property, receiver);
      }
      if (!allowed.has(property)) {
        refuse("view binding " + JSON.stringify(binding.id) + " does not "
          + "declare an export named " + JSON.stringify(String(property))
          + "; it declares " + JSON.stringify([...allowed]) + ". RULED Q2 "
          + "(openxFactory#656 comment 5648049748): a binding's contract is its "
          + "module NAMESPACE, DECLARED — an undeclared reach is a refusal.");
      }
      return Reflect.get(target, property, receiver);
    },
  });
}

// The element a "dom" region mounts into: the shell element whose `id` is the
// region's name. A "shell" region has no standing element by definition, so
// asking for one is a caller error rather than an absence — and saying so is
// worth a refusal, because the alternative is a null the caller reads as "the
// column is not installed".
export function regionHost(binding, doc) {
  if (REGIONS[binding.region] !== "dom") {
    refuse("region " + JSON.stringify(binding.region) + " is a shell region: "
      + "it has no standing element, and the shell hands its host to the "
      + "binding at mount time");
  }
  return (doc || document).getElementById(binding.region);
}


// ---- RULED Q1: THE SHELL MOUNTS CONTRIBUTED BINDINGS GENERICALLY -----------
//
// openxFactory#656 comment 5648044785, Brett Heap, 2026-09-12: "the shell
// MOUNTS contributed bindings generically: one mount pass over every
// contributed binding whose region is a `dom` region; the three `shell` regions
// stay caller-driven (the gate bar's pattern)."
//
// WHAT IT REPLACES. Nothing generic mounted a contributed binding: the tab
// router mounts only bindings that declared a `control`, a contributed entry
// declaring one is refused where the payload is read, and the one
// contributed-shaped mount was `resolveView(views, "gate.bar")` BY ID at a
// single openDox call site. So "a column can contribute a binding today and
// have nothing ever call it" — and every contributed panel needed an openDox
// edit to become reachable, "which is the fork the seam was drawn to prevent".
//
// WHY `shell` REGIONS ARE NOT IN THE PASS, and it is not an omission: a `shell`
// region has NO STANDING ELEMENT (`regionHost` refuses to look for one), so the
// host does not exist until the caller that builds it builds it. The viewer
// builds the gate bar's host per artifact; the workbench builds its two. A pass
// that tried to mount them would be mounting into nothing, which is the defect
// this seam names as "a declared panel silently unmounted".
//
// THE SIGNATURE IS RULED Q3's — `mount(host, snapshot, ctx)` — and it is the
// only one this pass knows. A contributed binding that took anything else would
// be teaching the shell a second shape, which is the coupling the registry
// exists to end.
//
// WHEN IT RUNS IS PART OF THE CONTRACT, and `regions` is how the caller says
// so (Copilot review of openDox-code#20, round 2). Every `dom` region is a root
// a CORE renderer owns and CLEARS on its own render — `renderWheel` and
// `renderFunnel` assign `root.innerHTML = ""`, `mountExplorer` clears its
// container, and the tab router renders a non-initial tab LAZILY, on first
// activation, long after page load. One pass before the core mounts therefore
// mounted contributed panels into roots that were about to be emptied, and a
// panel in a tab the human had not opened yet was erased the moment they
// opened it. So the pass is run PER REGION, by the caller that just rendered
// that region: `regions` bounds it to those, and a caller that passes none
// gets every `dom`-region binding, which is what a probe wants.
//
// WHAT IT RETURNS: one record per contributed binding it considered, so a
// caller can assert what mounted, what was skipped and why. `mounted` is the
// entry's own return value (a controller, an element, or undefined) — the pass
// does not interpret it.
export async function mountContributedViews(bindings, snapshot, ctx, options) {
  const o = options || {};
  const doc = o.document || (typeof document === "undefined" ? null : document);
  const capabilities = o.capabilities;
  const only = o.regions ? new Set(o.regions) : null;
  const results = [];
  for (const binding of bindings || []) {
    if (only && !only.has(binding.region)) continue;
    // The CORE arm is the shell's own and mounts through the tab router; a core
    // binding is the one that carries a `mount` function, which a contributed
    // one can never have (`contributedViewBindings` refuses the field where the
    // payload is read).
    if (typeof binding.mount === "function" || binding.control) continue;
    if (REGIONS[binding.region] !== "dom") continue;
    const unmet = capabilities === undefined
      ? null : unmetRequirement(binding, capabilities);
    if (unmet) {
      // RULED Q4: "unmet + `optional: true` renders the region empty with a
      // NAMED reason; unmet + required REFUSES." The reason is written INTO the
      // region, because a human looking at an empty panel is the person who
      // needs it — not the console.
      if (!binding.optional) refuse(requirementRefusal(binding, unmet));
      const host = doc ? regionHost(binding, doc) : null;
      if (host) host.appendChild(regionReason(binding, unmet, doc));
      results.push({ binding, mounted: null, skipped: "requires", unmet });
      continue;
    }
    const host = doc ? regionHost(binding, doc) : null;
    if (!host) {
      // A `dom` region the shell declares and this document does not carry —
      // an older served `index.html`, or a probe with a partial document. Named,
      // never silent, and never a throw: the shell renders without the panel.
      results.push({ binding, mounted: null, skipped: "no-host" });
      continue;
    }
    // THE EXACT BINDING, never a re-lookup by id (Copilot review, round 2):
    // ids are unique per REGION, not globally, so `resolveView(bindings, id)`
    // could answer a different region's binding.
    const resolved = await resolveBinding(binding);
    if (!resolved) {
      results.push({ binding, mounted: null, skipped: "absent" });
      continue;
    }
    results.push({
      binding,
      mounted: resolved.exports[binding.entry](host, snapshot, ctx),
      skipped: null,
    });
  }
  return results;
}

// The NAMED REASON an unmet optional binding leaves in its region (RULED Q4).
// `textContent` only — the value came off a payload this shell did not write.
export function regionReason(binding, unmet, doc) {
  const node = (doc || document).createElement("p");
  node.className = "viewrefusal";
  node.setAttribute("data-view", binding.id);
  node.textContent = requirementRefusal(binding, unmet);
  return node;
}
