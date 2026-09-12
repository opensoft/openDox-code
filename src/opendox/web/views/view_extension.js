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
function ownershipBreach(binding, contributedRoutes) {
  if (binding.view_class === "B") return null;
  for (const route of binding.routes) {
    for (const claimed of contributedRoutes) {
      const pattern = claimed && claimed.pattern;
      if (typeof pattern !== "string") {
        refuse("contributed route " + JSON.stringify(claimed) + " carries no "
          + "string pattern, so no view binding can be checked against it");
      }
      if (route === pattern
          || (claimed.is_prefix && route.startsWith(pattern))) {
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
  return routes;
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
export async function resolveView(bindings, id) {
  const binding = lookupView(bindings, id);
  if (!binding) return null;
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
  return { binding, exports };
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
