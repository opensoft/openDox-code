// Optional contributed binding for the intent-feed chips — RULED Q5
// (`docs/front-end-package-boundary.md` § 6 Q5 and § 4.2 "Reaching the
// consumer late", opensoft/openxFactory#656 comment 5642758731; RULING OQ-F,
// `docs/opendox-carve-manifest.yaml`:1807-1810 stands UNCHANGED).
//
// `views/intent-feed.js` is RULED `not_moved / stays_openxfactory_adapter`:
// the committed-intent feed is one domain's own apply lane made visible, and
// its only reader outside this file's two importers is openxFactory's
// `serve_openxfactory_lanes.py:412`. It is therefore ABSENT from this leg's
// own tree BY CONSTRUCTION, not by accident — but `dispose.js`:26 and
// `wheel.js`:75-76 used to name a static `from` clause pointing at that
// same (absent) file directly and UNCONDITIONALLY, which made the whole
// static module graph fail to resolve the moment this leg carried no such
// file (the note's § 1.2(b): `app.js` imports `wheel.js`, so the shell's
// own module graph does not resolve at `openDox-code` `main`).
//
// (Deliberately not spelled out here as a quoted `from "..."` clause: this
// file's own text is itself scanned by `tests/test_web_boundary.py`'s
// assertion 3, whose regex does not distinguish a real import from one
// named inside a comment — spelling the old specifier out literally would
// make this file misreport itself as still carrying the very import it
// removes.)
//
// THE FIX IS THIS FILE, NOT A CHANGE TO WHAT IS ABSENT. `dispose.js` and
// `wheel.js` now import the seven names below FROM HERE instead of from
// "./intent-feed.js" directly — same names, same call sites, nothing else in
// either file changes (split-opendox-two-layer-product § 3.4, slice S2).
// This module makes the real `intent-feed.js` an OPTIONAL CONTRIBUTED
// BINDING: a dynamic `import()` — never a static `import` — so a missing
// file is a REJECTED PROMISE this module catches, never a module nothing can
// resolve. When openxFactory's composed deployment drops the real
// `intent-feed.js` beside this one (the file this leg never carries), the
// dynamic import resolves and every name below forwards to it; when it does
// not (this leg, alone, exactly as measured at `a99eba03`), every name below
// answers the way `dispose.js`'s own `opts.intent` branch and `wheel.js`'s
// own `hosted` branch already treat an unregistered hosted plane — no chips,
// no thrown error, no dead import.
//
// RESOLVED ONCE, BEFORE ANY IMPORTER'S OWN TOP-LEVEL CODE RUNS. The `await`
// below is a TOP-LEVEL await (legal in an ES module): the module spec does
// not let `dispose.js` or `wheel.js` finish evaluating until whatever THEY
// import has finished evaluating, so by the time either module's own body —
// and therefore any function either of them later calls — runs, `MODULE`
// here is already settled to the real namespace object or to `null`. Nobody
// awaits this file at a call site; the ordering is free, the same way `caps`
// being resolved once at boot (`app.js`'s `render()`, `probeCapabilities()`)
// is free, and no view is left polling for a late upgrade.
//
// WHAT THIS IS NOT. The note's slice S3 formalizes the real thing — a
// `ViewBinding` registry mirroring `route_extension.collect_bindings` (note
// § 4.1), with contributed bindings assembled by whoever composes the
// deployment, the way `build_server(route_extensions=…)` is assembled today.
// This is deliberately smaller and narrower: ONE late-lookup, for ONE
// already-named edge, so S2 does not invent the registry S3 owns. S3 may
// fold this file's seven names into a single contributed `ViewBinding` entry
// for `intent-feed`; nothing here should be read as that registry's shape.
//
// A present-but-BROKEN `intent-feed.js` (as opposed to an ABSENT one) is
// swallowed the same way an absent one is: a browser's dynamic-import
// rejection does not portably distinguish "no such module" from "the module
// threw while loading" the way `consumer_reach.py`'s Python-side
// `ModuleNotFoundError.name` check can on the server, and S2's job is the
// ABSENT case the ruling names. A future registry can reconsider surfacing
// the broken-but-present case distinctly; this file does not.

let MODULE = null;
try {
  MODULE = await import("./intent-feed.js");
} catch {
  MODULE = null;
}

// `caps` is the `/capabilities` probe's payload (see `dispose.js`'s
// `gateCapable`, the same shape). Capability is the AND of "the binding is
// contributed here" and "the backend says the hosted plane is live" — never
// either alone, so a backend that claims it with no contributed module (or a
// leg that carries the module with a backend that never registers it) both
// read as "not capable" rather than throwing.
export function intentCapable(caps) {
  return !!(MODULE && MODULE.intentCapable && MODULE.intentCapable(caps));
}

export function feedActor(caps) {
  return MODULE ? MODULE.feedActor(caps) : null;
}

export function refusalLine(rec) {
  return MODULE ? MODULE.refusalLine(rec) : "";
}

export function startIntentFeed(opts) {
  return MODULE ? MODULE.startIntentFeed(opts) : null;
}

export function statesByTarget(rows) {
  return MODULE ? MODULE.statesByTarget(rows) : new Map();
}

export function renderIntentChips(container, targetId, rows, error) {
  return MODULE
    ? MODULE.renderIntentChips(container, targetId, rows, error)
    : container;
}

export async function emitIntent(opts) {
  if (MODULE) return MODULE.emitIntent(opts);
  // Unreachable through dispose.js's own call site today (it sits behind
  // `opts.intent`, which wheel.js only ever sets once `intentCapable` above
  // has already answered true), kept honestly refusing rather than absent
  // for any future direct caller.
  return { state: "error",
           message: "the intent-feed binding is not contributed in this "
                     + "deployment" };
}
