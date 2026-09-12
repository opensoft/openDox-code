// THE SNAPSHOT-INDEX READ — the third of slice S4's route tails, and the one
// that is not a gate act.
//
// WHAT MOVED, AND WHY IT HAD TO. `views/repo-selector.js`:33 declared
// `SNAPSHOT_INDEX_ROUTE = "/snapshot-index.json"` and fetched it. That route is
// openXdox's: `openxdox/serve_projection.py`:56 declares it and contributes it
// through `route_extension`, and openDox-spec
// `docs/front-end-package-boundary.md` § 3.3's ownership table lists it beside
// `/source`, `/source/` and the three `/projections/*` as the PROJECTION
// column's own. § 2.2 rule 1 is stated over OWNERSHIP and not over class B
// alone precisely so this case is a breach and not a layout choice — "§ 3.3
// measures three route owners, so the rule has to be stated over ownership or
// it misses two of the three kinds of breach the census actually found" — and
// § 4.5 assertion 2's table names this exact site as one of the twelve that
// clear at S4.
//
// WHY THIS FILE IS CLASS B IN THE CENSUS, AND WHAT THAT DOES AND DOES NOT
// CLAIM. § 2.1 names class B "the gate loop", and this is not a gate act: it is
// a GET of a projection. What assertion 2 actually exempts, though, is not
// "gate-ness" but the last clause of class B's own definition — "its BINDING
// belongs to `openXdox-code` through the seam § 4 describes" — because a file
// naming a route the column that supplies it declares is the boundary working,
// not breaking. That is exactly true here, by the same § 3.3 table that makes
// the old site a breach. The census has no fourth letter for "belongs to the
// projection column", so this row takes the one class whose exemption it
// actually earns, and says so here rather than by silence. REGISTERED for the
// note's owner: § 2.1's class-B headline is narrower than the property § 4.5
// assertion 2 exempts on, and either the class should be stated over the
// contributed column or the projection column should get a letter of its own.
//
// WHY A LATE, NAMED, REFUSABLE REACH AND NOT A ViewBinding. § 4.2 settles this
// for the intent chips and the reasoning is the same one line over: "§ 4.1
// binds at the region grain — a whole tab or overlay — not a fragment a view
// renders internally". An index FETCH mounts no panel and occupies no region,
// so a `ViewBinding` is the wrong instrument; what S2 established instead is
// "a small, local, late-and-refusable guard directly against the module's own
// presence — an optional resolve in place of the import-time `from`". That is
// how `views/repo-selector.js` reads this file: a dynamic `import()` inside its
// own `fetchIndex`, resolved once and cached, answering null when the module is
// not there. `fetchIndex` ALREADY promised exactly that shape — "ANY failure (a
// static image 404s this route, an old server does not know it, `file://`
// throws) resolves to null — the caller then renders exactly today's
// single-snapshot dashboard" — so an absent projection column joins a list the
// selector has always degraded against, and nothing downstream changes.
//
// AT S5 THIS FILE LEAVES THE BUNDLE with the other class-B files (§ 5 S5), at
// which point the reach above starts answering null on a student install and
// the selector renders the single baked snapshot, which is what the static
// image already does today.
//
// A CREATED file: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
// (RULED OQ-C), admitted by path in `docs/opendox-carve-admissions.yaml`.

// The roster + per-entry freshness projection. `openxdox/serve_projection.py`
// declares it; a static image 404s it, and that is a first-class outcome here
// rather than an error.
export const SNAPSHOT_INDEX_ROUTE = "/snapshot-index.json";

// Fetch the snapshot index. ANY failure resolves to null — the caller then
// renders exactly today's single-snapshot dashboard. Never throws. The
// injectable fetcher is the same test seam every transport in this bundle
// keeps.
export async function fetchSnapshotIndex(injectedFetch) {
  try {
    const response = injectedFetch
      ? await injectedFetch(SNAPSHOT_INDEX_ROUTE, { cache: "no-store" })
      : await fetch(SNAPSHOT_INDEX_ROUTE, { cache: "no-store" });
    if (!response?.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}
