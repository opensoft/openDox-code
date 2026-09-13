// Pipeline board view (T010). Four lifecycle columns — brainstorm, staged,
// active proposals, realized/archived — grown from the mockup's board. Reads
// only the in-memory snapshot: brainstorm cards carry a possibles badge derived
// purely by walking the snapshot's cluster membership + claiming links (layout
// aggregation, never a re-scan). Staged cards surface exit-readiness verbatim.
//
// v3 sweep: documents that fit no column are surfaced in an "everything else"
// footer with a jump to the doc list instead of being silently hidden (#18);
// a column-scope filter and the global `search(term)` hook filter what shows
// (#13). Each column is built by its own small builder so no function carries
// the whole board's branching.
//
// DOM-SAFETY: every dynamic value binds through helpers.el's textContent (or a
// text node); innerHTML is only ever assigned a literal empty string to clear.

import { el, txt, basename } from "./helpers.js";
import {
  DRILL_KINDS, STAGE_ROLES, STATUS_ROLE, TILE_KINDS, VOCABULARY,
  neutralDisplay,
} from "./display.js";

const [SOURCE, GROUPING, CANDIDATE, SELECTION, SUBMISSION, COMPLETION] =
  STAGE_ROLES;

// THE FOUR LIFECYCLE COLUMNS, AS ROLES (§ 3.4 slice S7). § 4.3 point 4 names
// this file directly — "`board.js`'s four columns become the profile's board
// roles" — and § 3.2 measured it at "25 governance literals". The first column
// is the SOURCE station filtered to documents at the CAPTURED status; the other
// three are the selection, submission and completion stations themselves.
const COLUMN_KEYS = [SOURCE, SELECTION, SUBMISSION, COMPLETION];

// THE PER-RENDER VOCABULARY, on `views/funnel.js`'s own footing: `renderBoard`
// is the entry point and every helper runs inside it.
let vocab = neutralDisplay();

// A board column's heading: the SOURCE station's first column is its CAPTURED
// documents, so it is labelled by the status rather than by the station.
function columnLabel(role) {
  return role === SOURCE
    ? vocab.status(VOCABULARY.DOCUMENT, STATUS_ROLE.CAPTURED)
    : vocab.label(role);
}

function emptyNote(role) {
  return "no " + columnLabel(role);
}

// The drill-down affordance (T017/FR-008): only staged/proposal/realized
// cards are backed by a real artifact folder in the snapshot.
function openButton(kind, id, onOpenTile) {
  const btn = el("button", "openbtn", "▸ open folder");
  btn.type = "button";
  btn.addEventListener("click", (ev) => {
    ev.stopPropagation();
    onOpenTile(kind, id);
  });
  return btn;
}

// doc -> clusters it belongs to (from Topics-derived document_edges) and
// cluster -> claiming possibles, both from snapshot fields verbatim.
function buildIndexes(clusters, possibles) {
  const clustersByDoc = new Map();
  const possiblesByCluster = new Map();
  for (const c of clusters) {
    for (const e of c.document_edges || []) {
      if (!clustersByDoc.has(e.document)) clustersByDoc.set(e.document, []);
      clustersByDoc.get(e.document).push(c.id);
    }
  }
  for (const p of possibles) {
    for (const cid of p.claiming_clusters || []) {
      if (!possiblesByCluster.has(cid)) possiblesByCluster.set(cid, []);
      possiblesByCluster.get(cid).push(p);
    }
  }
  return { clustersByDoc, possiblesByCluster };
}

// possibles reachable from a document, via the clusters it is a member of.
function possiblesForDoc(docId, indexes) {
  const seen = new Map();
  for (const clusterId of indexes.clustersByDoc.get(docId) || []) {
    for (const p of indexes.possiblesByCluster.get(clusterId) || []) seen.set(p.id, p);
  }
  const all = [...seen.values()];
  // THE REGISTER STATE BY ROLE (Copilot review). The badge LABEL reads the
  // domain's proposed-candidate word; the count behind it compared a literal
  // `"picked"`, so a profile that renamed `possibles[].state` would have shown
  // the right word beside a permanent zero.
  const proposed = vocab.registerState(STATUS_ROLE.PROPOSED);
  return { total: all.length, picked: all.filter((p) => p.state === proposed).length };
}

function hay(parts) {
  return parts.filter(Boolean).join(" ").toLowerCase();
}

// column header: coloured stage bar + label + count, composed of nodes
function colHead(color, label, count) {
  const head = el("div", "colhead");
  const bar = el("span", "stagebar");
  bar.style.background = color;
  head.appendChild(bar);
  head.appendChild(txt(" " + label + " "));
  head.appendChild(el("span", "n", String(count)));
  return head;
}

// ---- per-column card builders ----

function brainstormCard(d, indexes) {
  const card = el("div", "card stage-brainstorm");
  card.appendChild(el("div", "title", d.summary || basename(d.path)));
  const captured = d.dates?.captured ? "captured " + d.dates.captured : null;
  const topics = (d.topics || []).length ? "topics: " + d.topics.join(", ") : null;
  card.appendChild(el("div", "meta", [d.kind, captured, topics].filter(Boolean).join(" · ")));
  const badge = possiblesForDoc(d.id, indexes);
  card.appendChild(el("span", "pill stage",
    badge.total + " " + vocab.count(CANDIDATE, badge.total) + " · "
    + badge.picked + " " + vocab.status(VOCABULARY.CANDIDATE, STATUS_ROLE.PROPOSED)));
  return card;
}

function maybeNotebookButton(card, notebook, kind, id) {
  if (!notebook) return;
  const btn = notebook.button(kind, id);
  if (btn) card.appendChild(btn);
}

function stagedTopicCard(t, onOpenTile, notebook) {
  const card = el("div", "card stage-staged");
  card.appendChild(el("div", "title", t.staging_id));
  const n = (t.files || []).length;
  card.appendChild(el("div", "meta", n + " file" + (n === 1 ? "" : "s")));
  if (t.readiness_state) card.appendChild(el("span", "pill neutral", t.readiness_state));
  if (t.target_change) card.appendChild(el("span", "pill good", "→ " + t.target_change));
  else card.appendChild(el("span", "pill neutral", "no pick yet"));
  if (onOpenTile) {
    card.appendChild(openButton(DRILL_KINDS[SELECTION], t.staging_id, onOpenTile));
  }
  maybeNotebookButton(card, notebook, TILE_KINDS[SELECTION], t.staging_id);
  return card;
}

function proposalCard(c, onOpenTile, notebook) {
  const card = el("div", "card stage-proposal");
  card.appendChild(el("div", "id", c.id));
  const bits = [];
  if (c.task_progress?.total) bits.push((c.task_progress.completed || 0) + "/" + c.task_progress.total + " tasks");
  if (c.origin_staging_id) bits.push("from " + c.origin_staging_id);
  if (bits.length) card.appendChild(el("div", "meta", bits.join(" · ")));
  if (onOpenTile) {
    card.appendChild(openButton(DRILL_KINDS[SUBMISSION], c.id, onOpenTile));
  }
  maybeNotebookButton(card, notebook, TILE_KINDS[SUBMISSION], c.id);
  return card;
}

function realizedCard(c, onOpenTile) {
  const card = el("div", "card stage-realized");
  card.appendChild(el("div", "id", c.id));
  if (c.ratification) {
    card.appendChild(el("div", "meta",
      vocab.status(VOCABULARY.CHANGE, STATUS_ROLE.RATIFIED) + " "
      + c.ratification.date + " · " + c.ratification.ratifier));
  }
  if (onOpenTile) {
    card.appendChild(openButton(DRILL_KINDS[COMPLETION], c.id, onOpenTile));
  }
  return card;
}

// generic column assembly: header + one tracked card per item (or the empty note)
function buildColumn(colKey, head, items, makeCard, makeHay, emptyText, track) {
  const col = el("div", "col");
  col.appendChild(head);
  for (const item of items) col.appendChild(track(makeCard(item), colKey, makeHay(item)));
  if (!items.length) col.appendChild(el("div", "empty", emptyText));
  return col;
}

// --- #18: documents that are not pipeline cards are COUNTED, never silently
// hidden. Everything but a brainstorm-stage doc lives only in the doc list. ---
function elseFooter(documents, onOpenDocList) {
  const elsewhere = documents.filter(
    (d) => d.stage !== vocab.documentStage(STATUS_ROLE.CAPTURED));
  if (!elsewhere.length) return null;
  const byStage = new Map();
  for (const d of elsewhere) byStage.set(d.stage || "—", (byStage.get(d.stage || "—") || 0) + 1);
  const breakdown = [...byStage.entries()].sort((a, b) => b[1] - a[1])
    .map(([s, n]) => s + " " + n).join(" · ");
  const foot = el("div", "board-else");
  foot.appendChild(el("b", null, String(elsewhere.length)));
  foot.appendChild(txt(" document" + (elsewhere.length === 1 ? "" : "s")
    + " aren't pipeline cards (" + breakdown + ") — "));
  const jump = el("button", "openbtn", "open the doc list");
  jump.type = "button";
  // THE SHELL OWNS EVERY CROSS-VIEW JUMP (§ 3.4 slice S7). This used to reach
  // `document.getElementById("tab-docs")` and click it — a view reaching into
  // another view's tab control by its DOM id, which is the coupling `app.js`'s
  // `nav` exists to hold. The view declares the verb; the shell performs it.
  jump.disabled = !onOpenDocList;
  if (onOpenDocList) jump.addEventListener("click", () => onOpenDocList());
  foot.appendChild(jump);
  return foot;
}

// --- #13: the column-scope filter control ---
function columnFilterBar(onChange) {
  const bar = el("div", "filterbar");
  const wrap = el("label");
  wrap.appendChild(txt("column "));
  const sel = document.createElement("select");
  for (const [value, text] of [["", "all"],
    ...COLUMN_KEYS.map((role) => [role, columnLabel(role)])]) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    sel.appendChild(opt);
  }
  sel.addEventListener("change", () => onChange(sel.value));
  wrap.appendChild(sel);
  bar.appendChild(wrap);
  return bar;
}

function applyBoardFilters(cards, columns, filterState) {
  for (const card of cards) {
    const okCol = !filterState.col || card.colKey === filterState.col;
    const okSearch = !filterState.search || card.haystack.includes(filterState.search);
    card.node.hidden = !(okCol && okSearch);
  }
  columns.forEach((col, i) => {
    col.style.display = (!filterState.col || filterState.col === COLUMN_KEYS[i]) ? "" : "none";
  });
}

// ---- view assembly (orchestrator) ----

export function renderBoard(root, snapshot, opts) {
  vocab = opts?.display || neutralDisplay();
  const onOpenTile = opts?.onOpenTile || null;
  const notebook = opts?.notebook || null;
  const documents = snapshot.documents || [];
  const changes = snapshot.changes || [];
  const staged = snapshot.staged_topics || [];
  const indexes = buildIndexes(snapshot.clusters || [], snapshot.possibles || []);

  const brainstorms = documents.filter(
    (d) => d.stage === vocab.documentStage(STATUS_ROLE.CAPTURED));
  const active = vocab.items(snapshot, SUBMISSION);
  const archived = vocab.items(snapshot, COMPLETION);

  root.innerHTML = "";

  // every card, tagged with its column key and a lower-cased search haystack —
  // the column-scope filter and the global search toggle `hidden` on these.
  const cards = [];
  const track = (node, colKey, parts) => {
    cards.push({ node, colKey, haystack: hay(parts) });
    return node;
  };

  const columns = [
    buildColumn(SOURCE,
      colHead(vocab.tokenVar(STATUS_ROLE.CAPTURED), columnLabel(SOURCE), brainstorms.length),
      brainstorms, (d) => brainstormCard(d, indexes),
      (d) => [d.summary, d.path, d.kind, ...(d.topics || [])],
      emptyNote(SOURCE), track),
    buildColumn(SELECTION,
      colHead(vocab.tokenVar(STATUS_ROLE.ORGANIZED), columnLabel(SELECTION), staged.length),
      staged, (t) => stagedTopicCard(t, onOpenTile, notebook),
      (t) => [t.staging_id, t.target_change, t.readiness_state],
      emptyNote(SELECTION), track),
    buildColumn(SUBMISSION,
      colHead(vocab.tokenVar(STATUS_ROLE.PROPOSED), columnLabel(SUBMISSION), active.length),
      active, (c) => proposalCard(c, onOpenTile, notebook),
      (c) => [c.id, c.origin_staging_id], emptyNote(SUBMISSION), track),
    buildColumn(COMPLETION,
      colHead(vocab.tokenVar("completion"), columnLabel(COMPLETION), archived.length),
      archived, (c) => realizedCard(c, onOpenTile),
      (c) => [c.id, c.ratification?.ratifier], emptyNote(COMPLETION), track),
  ];

  const scroller = el("div", "scroller");
  const board = el("div", "board");
  for (const col of columns) board.appendChild(col);
  const foot = elseFooter(documents, opts?.onOpenDocList);
  if (foot) board.appendChild(foot);
  scroller.appendChild(board);

  const filterState = { col: "", search: "" };
  const refresh = () => applyBoardFilters(cards, columns, filterState);
  root.appendChild(columnFilterBar((value) => { filterState.col = value; refresh(); }));
  root.appendChild(scroller);

  return {
    redraw: refresh,
    search(term) { filterState.search = String(term || "").trim().toLowerCase(); refresh(); },
  };
}
