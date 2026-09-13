// Shared DOM/text helpers for the dashboard views (hygiene #20).
//
// SAFE-BY-CONSTRUCTION: el() binds its text argument via textContent — never
// innerHTML — so no dynamic string can reach an HTML-parsing sink through this
// module. Views compose structure with el()/txt() + appendChild instead of
// interpolating markup strings; the only innerHTML assignments left in the
// importing views are literal `""` clears. The shared helper thus ENFORCES the
// textContent-first discipline the newer views (canvas/lens/gate/viewer)
// already follow, rather than centralizing an innerHTML habit.
//
// Scope note — why not literally every view imports this:
//   * The node-standalone view-model modules (model.js, grouping.js,
//     explorer.js, canvas-model.js, lens-model.js) are each copied ALONE into a
//     node test harness and run in isolation, so they cannot import a sibling
//     (explorer.js was additionally asserted to have ZERO imports). They keep
//     local equivalents.
//
//     AMENDED AT § 3.4 SLICE S7. Four of those five are class-C or carry a
//     declared class-C tail, and a class-C module's vocabulary comes from the
//     registered domain profile rather than from a literal (the note's § 2.1,
//     § 4.3) — so it has to reach the facet, and a module that imports NOTHING
//     cannot. They now import EXACTLY ONE sibling, `./display.js`, which is
//     itself import-free by design: a harness that copies one of them copies
//     display.js beside it, which is a two-file harness rather than a one-file
//     one. They still do not import THIS module. Recorded here rather than
//     discovered: the harnesses are at openXdox-code, their suites are narrowed
//     off (RULED Q-L8 (b')), and slice S8 is the slice that re-homes them.
//   * The textContent-family views (lens.js, canvas.js, gate.js, viewer.js)
//     keep their own el() with the identical textContent binding discipline.

// Element builder. `text`, when supplied, is assigned via textContent.
export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

// Text-node builder for mixed element/text composition.
export function txt(s) {
  return document.createTextNode(String(s == null ? "" : s));
}

export function basename(path) {
  return String(path).split("/").at(-1) || path;
}

// Readiness heat band for a numeric tier score (shared by funnel + lineage).
export function heatBand(score) {
  if (score >= 8) return "hot";
  if (score >= 5) return "warm";
  return "cold";
}

// Readiness heat strip — rendered VERBATIM from cluster.readiness when the
// cross-ref index supplies it; absent means absent (no synthetic score).
export function readinessHeat(readiness) {
  if (!readiness || typeof readiness !== "object") return null;
  const entries = Object.entries(readiness).filter(([, v]) => typeof v === "number");
  if (!entries.length) return null;
  const heat = el("div", "heat");
  heat.appendChild(el("span", null, "readiness"));
  for (const [tier, score] of entries) {
    const cell = el("span", "cell " + heatBand(score));
    cell.title = tier + ": " + score;
    heat.appendChild(cell);
  }
  return heat;
}
