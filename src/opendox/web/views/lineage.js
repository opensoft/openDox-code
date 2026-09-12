// Stats strip + cluster lineage / readiness-heat / health-overlay view (T010).
// Snapshot-only. Readiness and conflict flags are rendered VERBATIM from the
// cluster fields the cross-ref index supplies — never re-scored — and degrade
// to absent (not error) when those optional fields are missing.
//
// v3 sweep: the stats strip's first tile no longer mislabels a handful of
// brainstorm-stage docs as "active ideation docs" — it reports the whole
// document count with the real stage distribution (#18).
//
// DOM-SAFETY: every dynamic value binds through helpers.el's textContent;
// innerHTML is only ever assigned a literal empty string to clear.

import { el, readinessHeat } from "./helpers.js";
import {
  STAGE_ROLES, STATUS_ROLE, VOCABULARY, neutralDisplay,
} from "./display.js";

const [SOURCE, GROUPING, CANDIDATE, SELECTION, SUBMISSION, COMPLETION] =
  STAGE_ROLES;

// The three lineage chips keep their landed style hooks (RULED Q7: the `--st-*`
// family is the one stable styling surface, and a chip class is not part of it).
const CHIP_CLASS = {
  [SELECTION]: "lchip-selection",
  [SUBMISSION]: "lchip-submission",
  [COMPLETION]: "lchip-completion",
};

// The per-render vocabulary (§ 3.4 slice S7).
let vocab = neutralDisplay();

// A tile heading is sentence-cased; the facet declares words, not capitals.
const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

// ---- stats strip (always-visible tiles) ----
function tile(root, k, v, unit, s) {
  const t = el("div", "tile");
  t.appendChild(el("div", "k", k));
  const val = el("div", "v", String(v));
  if (unit) val.appendChild(el("span", "unit", unit));
  t.appendChild(val);
  if (s) t.appendChild(el("div", "s", s));
  root.appendChild(t);
}

// The DOCUMENTS tile's sub-line, DERIVED from the corpus's own distribution
// (T092 acceptance sweep, defect 15). It used to name exactly three stages —
// "draft 65 · staged 32 · brainstorm 39" under a headline of 177 — dropping 41
// documents (record 20, ratified 12, standard 6, superseded 2, retired 1) with
// nothing on screen saying so, while the pipeline board's footer did the same
// arithmetic completely one tab away.
//
// The RULE is the sub-line sums to the headline. It names the biggest stages by
// count (the same descending order board.js's footer uses, tie-broken by name so
// two equal stages order deterministically) and carries everything it did not
// name in an explicit "+N other" remainder rather than dropping it. A corpus
// with few stages is fully enumerated and grows no remainder; the eight-stage
// real corpus reads "draft 65 · brainstorm 39 · staged 32 · +41 other".
const STAT_STAGES_NAMED = 3;

export function stageSubline(docs, named = STAT_STAGES_NAMED) {
  const byStage = new Map();
  for (const d of docs) byStage.set(d.stage || "—", (byStage.get(d.stage || "—") || 0) + 1);
  const ordered = [...byStage.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const shown = ordered.length <= named + 1 ? ordered : ordered.slice(0, named);
  const rest = ordered.slice(shown.length).reduce((sum, [, n]) => sum + n, 0);
  const parts = shown.map(([s, n]) => s + " " + n);
  if (rest) parts.push("+" + rest + " other");
  return parts.join(" · ");
}

export function renderStats(root, snapshot) {
  const docs = snapshot.documents || [];
  const clusters = snapshot.clusters || [];
  const possibles = snapshot.possibles || [];
  const staged = snapshot.staged_topics || [];
  const changes = snapshot.changes || [];
  root.innerHTML = "";
  // real lifecycle-stage distribution over the whole corpus (#18): the old
  // "Brainstorms / active ideation docs" tile counted only the two
  // brainstorm-stage docs and mislabelled the rest out of existence.
  const active = vocab.items(snapshot, SUBMISSION).length;
  const archived = vocab.items(snapshot, COMPLETION).length;
  const picked = possibles.filter(
    (p) => p.state === vocab.registerState(STATUS_ROLE.PROPOSED)).length;
  const latent = possibles.filter(
    (p) => p.state === vocab.registerState(STATUS_ROLE.CAPTURED)).length;
  // The tile row is the PIPELINE in order — corpus, clusters, possibles,
  // staged, proposals, archived, the SAME order and the same six stages the
  // wheel's columns and the funnel's lanes use — and it sits above the view it
  // heads (Brett's 2026-08-08 annotations: the tabs move up, "then this
  // becomes the header to the other screens that need a header like wheel
  // and funnel", with staged added to the list). Staged was a subline under
  // Topic clusters, which hid a pipeline STAGE inside another stage's
  // caption; it is a stage of its own.
  const ready = staged.filter(
    (s) => (s.health || {}).status === "ready").length;
  tile(root, cap(vocab.label(SOURCE)), docs.length, "", stageSubline(docs));
  tile(root, cap(vocab.label(GROUPING)), clusters.length, "",
    vocab.count(GROUPING, clusters.length) + " derived");
  tile(root, cap(vocab.label(CANDIDATE)), possibles.length, "",
    picked + " " + vocab.status(VOCABULARY.CANDIDATE, STATUS_ROLE.PROPOSED)
    + " · " + latent + " " + vocab.status(VOCABULARY.CANDIDATE, STATUS_ROLE.CAPTURED));
  tile(root, cap(vocab.label(SELECTION)), staged.length, "",
    ready + " ready to " + (vocab.gate(SELECTION) || "advance"));
  tile(root, cap(vocab.label(SUBMISSION)), active, "", "in flight");
  tile(root, cap(vocab.label(COMPLETION)), archived, "", vocab.short(COMPLETION));
}

// ---- cluster lineage strips ----

function lineageRow(label, ids, chipClass) {
  if (!ids?.length) return null;
  const row = el("div", "lineage-row");
  row.appendChild(el("span", "lk", label));
  for (const id of ids) row.appendChild(el("span", "lchip " + chipClass, id));
  return row;
}

// one cluster's block: name, link tallies, readiness heat, conflict flags, and
// the downstream lineage rows (extracted so renderLineage stays a simple loop).
function clusterBlock(c) {
  const block = el("div", "lineage-cluster");
  block.appendChild(el("div", "cname", c.name || c.id));
  const t = c.tallies || {};
  block.appendChild(el("div", "meta",
    (t.document_links != null ? t.document_links : (c.document_edges || []).length) + " doc links · " +
    (t.possible_links != null ? t.possible_links : 0) + " "
    + vocab.one(CANDIDATE) + " links"));

  const heat = readinessHeat(c.readiness);
  if (heat) block.appendChild(heat);
  // health overlay: verbatim conflict flags (degrade to absent)
  for (const flag of c.conflict_flags || []) {
    block.appendChild(el("span", "pill blocked", typeof flag === "string" ? flag : (flag.label || "conflict")));
  }

  const lin = c.lineage || {};
  const rows = [
    lineageRow(vocab.label(SELECTION), lin.staged_picks, CHIP_CLASS[SELECTION]),
    lineageRow(vocab.label(SUBMISSION), lin.proposals, CHIP_CLASS[SUBMISSION]),
    lineageRow(vocab.label(COMPLETION), lin.realized, CHIP_CLASS[COMPLETION]),
  ].filter(Boolean);
  if (rows.length) rows.forEach((r) => block.appendChild(r));
  else block.appendChild(el("div", "meta", "no downstream lineage yet"));
  return block;
}

export function renderLineage(root, snapshot, opts) {
  vocab = opts?.display || neutralDisplay();
  const clusters = snapshot.clusters || [];
  root.innerHTML = "";
  const legend = el("div", "legend");
  legend.appendChild(el("span", "g",
    "downstream progression per " + vocab.one(GROUPING) + " — "
    + [SELECTION, SUBMISSION, COMPLETION].map((r) => vocab.label(r)).join(" → ")
    + " — with readiness and conflict flags rendered verbatim from the "
    + "cross-reference index when present"));
  root.appendChild(legend);

  // The cluster blocks live in a single scroll region (the v4 layout contract:
  // one scroll context per view, bounded by the fixed-viewport shell) so the
  // legend stays put while the list scrolls instead of the whole page.
  const list = el("div", "lineage-list");
  for (const c of clusters) list.appendChild(clusterBlock(c));
  if (!clusters.length) {
    list.appendChild(el("div", "empty",
      "no " + vocab.many(GROUPING) + " in the snapshot"));
  }
  root.appendChild(list);
}
