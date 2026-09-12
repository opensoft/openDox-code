// THE DISPLAY FACET, CLIENT HALF — the registered domain's words, BY ROLE.
//
// `docs/front-end-package-boundary.md` § 4.3 step 3: "`app.js` puts that facet
// in the context object every binding already receives", and step 4: "a class-C
// module resolves BY ROLE, NOT BY STRING — the openXdox-spec note's own rule."
// This module is what a class-C file resolves THROUGH. `display_profile.py` is
// the server half that publishes the facet on `/capabilities`; the two are held
// together by `tests/test_display_facet.py`, which reads both files, exactly as
// `tests/test_view_registry.py` holds the two REGIONS tables together.
//
// RESOLVE BY ROLE, NEVER BY WORD. A role names a POSITION — "the raw material
// this domain works from", "the status a document carries while ORGANIZED" —
// and the word is the registered domain's spelling of it. openXdox-spec
// `docs/domain-profile-design-note.md` § 6 states the rule and the reason: "a
// profile whose organized status is spelled `triaged` must work with no engine
// change, which a `profile.statuses['staged']` lookup would not deliver."
//
// AN UNKNOWN ROLE IS A REFUSAL, NOT `undefined`. `DisplayRoleError` names the
// role and the declared set, because a typo that answered `undefined` would
// render a blank label in one corner of one view and be found by a human, once,
// much later. That is `ViewBindingError`'s stance and this module holds it for
// the same reason.
//
// ABSENT IS NEUTRAL. `NEUTRAL_DISPLAY` below is openDox's OWN vocabulary — the
// neutral product's plain words for its own shape — rendered when no host
// declares a `DISPLAY` facet, when `/capabilities` 404s (the static served
// image), or when a field is missing from a partial declaration. It is NOT
// openxFactory's words, which is the whole distinction § 4.3 point 5 is
// protecting: "a fallback to TODAY'S WORDS is how the literals survive the
// refactor invisibly." A funnel labelled `sources → groups → candidates` is
// visibly un-domained; one labelled `docs → clusters → possibles` is invisibly
// re-domained.
//
// IMPORT-FREE BY DESIGN, like `views/helpers.js` and `views/view_extension.js`:
// every class-C module in the bundle imports this one, so an import of its own
// would put a second module on that path and make the vocabulary's own
// availability depend on it.
//
// A CREATED FILE: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
// (RULED OQ-C — the manifest declares what LEAVES openxFactory, never what a
// destination assembles). Its census row is class A: it carries ROLE names and
// openDox's own neutral words, and the one domain-shaped thing in it —
// `SNAPSHOT_FIELDS` — is a declared § 2.2 rule 3 exemption, below.

// ---------------------------------------------------------------------------
// The declared roles. Mirrored in `src/opendox/display_profile.py`; the drift
// test reads both files rather than trusting this comment.
// ---------------------------------------------------------------------------

// THE SIX STAGE ROLES, in spine order. `views/model.js` renders six columns
// left to right and `views/wheel-model.js` six reels in the same order, so the
// ORDER is part of the declaration: a renderer that had to invent the axis
// would be inventing domain knowledge.
export const STAGE_ROLES = ["source", "grouping", "candidate",
                            "selection", "submission", "completion"];

// THE CORPUS AREAS, by role (RULED Q1: `views/docs.js`'s area map is
// parameterized). `reference` is the terminal bucket — everything the declared
// areas do not claim — and never carries a prefix.
export const AREA_ROLES = ["captured", "organized", "proposed", "reference"];

// THE FOUR DESIGN TOKENS, by role — `styles.css`'s `--st-*` family, which RULED
// Q7 (openxFactory#656 comment `5648049748`) calls "the one stable styling
// surface". The NAMES become `--st-<role>`; the values come from the facet.
export const TOKEN_ROLES = ["captured", "organized", "proposed", "completion"];

// The status vocabularies the shell renders, one per artifact-kind role. A
// profile declares one closed word list per kind, and collapsing them would
// make `proposed` mean two different words at once.
export const STATUS_VOCABULARIES = ["document", "change", "candidate"];

// THE NEUTRAL ROLE VOCABULARY FOR A STATUS — the lifecycle-state column
// openXdox-spec's design note § 6 names as "the neutral role vocabulary that
// makes this possible".
export const STATUS_ROLES = ["captured", "organized", "proposed", "ratified",
                            "promoted", "superseded", "retired", "out-of-band"];

// ---------------------------------------------------------------------------
// SNAPSHOT_FIELDS — § 2.2 rule 3's OTHER half, and a DECLARED exemption from
// the governance-literal sweep (`declared_exemptions` in the census fixture).
//
//   "A SNAPSHOT SCHEMA KEY is not a stage name; a RENDERED WORD or a CORPUS
//    PATH is. … A class-A file MAY read a schema key; it may NOT carry a word
//    it renders or a corpus path it walks."   (note § 2.2 rule 3)
//
// These are the field names of `snapshot.json`, the document this leg's own
// generator contract fixes and this bundle exists to render. They are openDox's
// SCHEMA, not a domain's vocabulary: a descendant that renamed `clusters` would
// be shipping a different snapshot, not a different domain. They are declared
// HERE, once, in a class-A module, so that the fourteen class-C files can read
// the snapshot through a role and carry none of them.
//
// `status` is the closed VALUE the two change stations split on
// (`changes[].status`) — a schema enum, never a rendered word; `null` where a
// station reads a whole collection.
export const SNAPSHOT_FIELDS = {
  source: { field: "documents", status: null },
  grouping: { field: "clusters", status: null },
  candidate: { field: "possibles", status: null },
  selection: { field: "staged_topics", status: null },
  submission: { field: "changes", status: "active" },
  completion: { field: "changes", status: "archived" },
};

// openDox's OWN words. Kept BYTE-FOR-BYTE in step with
// `display_profile.NEUTRAL_DISPLAY`; `tests/test_display_facet.py` parses both
// and refuses a difference.
export const NEUTRAL_DISPLAY = {
  stages: {
    source: { one: "source item", many: "source items",
              short: "sources", label: "source items", gate: null },
    grouping: { one: "group", many: "groups",
                short: "groups", label: "groups", gate: null },
    candidate: { one: "candidate", many: "candidates",
                 short: "candidates", label: "candidates",
                 gate: "→ select gate" },
    selection: { one: "selection", many: "selections",
                 short: "selections", label: "selections",
                 gate: "→ submit gate" },
    submission: { one: "submission", many: "submissions",
                  short: "submissions", label: "open submissions",
                  gate: "→ complete gate" },
    completion: { one: "completed item", many: "completed items",
                  short: "completed", label: "completed", gate: null },
  },
  statuses: {
    document: { captured: "captured", organized: "organized",
                proposed: "proposed" },
    change: { proposed: "open", ratified: "accepted",
              promoted: "completed", superseded: "replaced" },
    candidate: { captured: "unselected", proposed: "selected",
                 retired: "declined", superseded: "replaced" },
  },
  areas: {
    captured: { prefix: null, label: "captured material" },
    organized: { prefix: null, label: "organized material" },
    proposed: { prefix: null, label: "submissions" },
    reference: { prefix: null, label: "other (read-only reference)" },
  },
  tokens: {
    captured: "#7A5AD0", organized: "#0D9488",
    proposed: "#B96A1B", completion: "#3B6FD4",
  },
  acts: {
    derive: "derive candidates", brief: "research brief",
    promote: "promote to selection",
  },
};

export const DISPLAY_KIND = "opendox.display-facet";
export const DISPLAY_SCHEMA_VERSION = 1;

export class DisplayRoleError extends Error {
  constructor(message) {
    super(message);
    this.name = "DisplayRoleError";
  }
}

function refuseRole(kind, role, declared) {
  throw new DisplayRoleError(
    "no " + kind + " role " + JSON.stringify(role) + " is declared; the "
    + "declared roles are " + JSON.stringify(declared) + ". A view resolves "
    + "its vocabulary BY ROLE (docs/front-end-package-boundary.md § 4.3 step "
    + "4), and a role this shell does not declare renders nowhere — so it is "
    + "refused here rather than answered `undefined` and found as a blank "
    + "label much later.");
}

function pick(table, fallback, role) {
  const declared = table && typeof table === "object" ? table[role] : null;
  const base = fallback[role];
  if (!declared || typeof declared !== "object") return base;
  return Object.assign({}, base, declared);
}

// THE VOCABULARY, as a view reads it. One object per render, built from the
// `/capabilities` payload the shell already fetched; nothing here fetches.
export class Display {
  constructor(payload) {
    const facet = payload && typeof payload === "object" ? payload : {};
    this.hostFacet = facet.host_facet === "declared" ? "declared" : "absent";
    this.hostProfile = typeof facet.host_profile === "string"
      ? facet.host_profile : null;
    this.stageOrder = Array.isArray(facet.stage_order) && facet.stage_order.length
      ? facet.stage_order.filter((role) => STAGE_ROLES.indexOf(role) !== -1)
      : STAGE_ROLES.slice();
    this.areaOrder = Array.isArray(facet.area_order) && facet.area_order.length
      ? facet.area_order.filter((role) => AREA_ROLES.indexOf(role) !== -1)
      : AREA_ROLES.slice();
    this.fields = {};
    for (const role of STAGE_ROLES) {
      const declared = facet.fields && facet.fields[role];
      this.fields[role] = declared && typeof declared.field === "string"
        ? { field: declared.field,
            status: typeof declared.status === "string" ? declared.status : null }
        : SNAPSHOT_FIELDS[role];
    }
    this._stages = {};
    for (const role of STAGE_ROLES) {
      this._stages[role] = Object.assign(
        { role: role },
        pick(facet.stages, NEUTRAL_DISPLAY.stages, role),
        this.fields[role]);
    }
    this._statuses = {};
    for (const vocabulary of STATUS_VOCABULARIES) {
      const declared = facet.statuses && facet.statuses[vocabulary];
      this._statuses[vocabulary] = Object.assign(
        {}, NEUTRAL_DISPLAY.statuses[vocabulary],
        declared && typeof declared === "object" ? declared : null);
    }
    this._areas = {};
    for (const role of AREA_ROLES) {
      this._areas[role] = Object.assign(
        { role: role }, pick(facet.areas, NEUTRAL_DISPLAY.areas, role));
    }
    this._tokens = Object.assign({}, NEUTRAL_DISPLAY.tokens,
      facet.tokens && typeof facet.tokens === "object" ? facet.tokens : null);
    this._acts = Object.assign({}, NEUTRAL_DISPLAY.acts,
      facet.acts && typeof facet.acts === "object" ? facet.acts : null);
  }

  // ---- stages ----
  stage(role) {
    const entry = this._stages[role];
    if (!entry) refuseRole("stage", role, STAGE_ROLES);
    return entry;
  }

  // The six stations in declared order — what a column strip, a wheel deck and
  // a station list all iterate.
  stages() { return this.stageOrder.map((role) => this.stage(role)); }

  // The singular noun, the plural noun, the axis-label short form, the station
  // label, and the gate caption between this station and the next.
  one(role) { return this.stage(role).one; }
  many(role) { return this.stage(role).many; }
  short(role) { return this.stage(role).short; }
  label(role) { return this.stage(role).label; }
  gate(role) { return this.stage(role).gate; }

  // `n` of them, spelled for `n` — the shape "3 possibles" / "1 possible" takes
  // everywhere in this bundle, with the domain's own two words.
  count(role, n) { return n === 1 ? this.one(role) : this.many(role); }

  // ---- the snapshot, through a role (§ 2.2 rule 3) ----
  field(role) { return this.stage(role).field; }
  statusValue(role) { return this.stage(role).status; }

  // The items of one station, read out of the snapshot by the declared field
  // and filtered by the declared status where the station has one.
  items(snapshot, role) {
    const stage = this.stage(role);
    const all = (snapshot && snapshot[stage.field]) || [];
    if (!Array.isArray(all)) return [];
    if (!stage.status) return all;
    return all.filter((item) => item && item.status === stage.status);
  }

  // ---- statuses ----
  status(vocabulary, role) {
    const words = this._statuses[vocabulary];
    if (!words) refuseRole("status vocabulary", vocabulary, STATUS_VOCABULARIES);
    const word = words[role];
    if (word === undefined) refuseRole(vocabulary + " status", role,
                                       Object.keys(words));
    return word;
  }

  // ---- corpus areas ----
  area(role) {
    const entry = this._areas[role];
    if (!entry) refuseRole("area", role, AREA_ROLES);
    return entry;
  }

  areas() { return this.areaOrder.map((role) => this.area(role)); }

  // Which declared area a corpus path falls in — the first whose prefix claims
  // it, else the terminal `reference` bucket. A neutral install declares no
  // prefix at all, so every document lands in `reference`, which is the honest
  // answer for a product that has not been told a corpus layout.
  areaOf(path) {
    const text = String(path || "");
    for (const role of this.areaOrder) {
      const entry = this.area(role);
      if (entry.prefix && text.startsWith(entry.prefix)) return entry;
    }
    return this.area("reference");
  }

  // ---- design tokens ----
  token(role) {
    const value = this._tokens[role];
    if (value === undefined) refuseRole("token", role, TOKEN_ROLES);
    return value;
  }

  // `var(--st-<role>)`, the one styling surface RULED Q7 keeps stable.
  tokenVar(role) {
    this.token(role);
    return "var(--st-" + role + ")";
  }

  // Set the four tokens as custom properties on the given element (`:root` at
  // boot). § 4.3 point 4's own words: "`styles.css`'s four `--st-*` tokens
  // become profile-keyed custom properties set on `:root` at boot."
  applyTokens(element) {
    if (!element || !element.style) return;
    for (const role of TOKEN_ROLES) {
      element.style.setProperty("--st-" + role, this.token(role));
    }
  }

  // ---- acts ----
  act(role) {
    const word = this._acts[role];
    if (word === undefined) refuseRole("act", role, Object.keys(this._acts));
    return word;
  }
}

// The ONE reader. `capabilities` is the payload `probeCapabilities()` already
// fetched; a static served image 404s that route and hands `null`, which is
// exactly the neutral install.
//
// REFUSES A PAYLOAD IT CANNOT DESCRIBE, on `contributedViewBindings`' own
// grounds: a shell that guessed at an unknown facet version would be rendering
// a vocabulary it cannot name.
export function readDisplay(capabilities) {
  const payload = capabilities && capabilities.display;
  if (payload === undefined || payload === null) return new Display(null);
  if (typeof payload !== "object" || Array.isArray(payload)) {
    throw new DisplayRoleError(
      "the /capabilities payload carries a `display` that is not a display "
      + "facet object");
  }
  if (payload.kind !== DISPLAY_KIND) {
    throw new DisplayRoleError(
      "the /capabilities `display` payload declares kind "
      + JSON.stringify(payload.kind) + ", not " + JSON.stringify(DISPLAY_KIND));
  }
  if (payload.schema_version !== DISPLAY_SCHEMA_VERSION) {
    throw new DisplayRoleError(
      "the /capabilities `display` payload declares schema_version "
      + JSON.stringify(payload.schema_version) + ", and this shell reads "
      + DISPLAY_SCHEMA_VERSION + ". A shell that guessed at an unknown facet "
      + "version would be rendering a vocabulary it cannot describe.");
  }
  return new Display(payload);
}

// The neutral vocabulary, without a payload — for a module that renders before
// the probe resolves, and for a node test.
export function neutralDisplay() { return new Display(null); }
