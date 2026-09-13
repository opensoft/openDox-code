// Snapshot -> funnel view-model derivation. PURE: no DOM, no I/O — it is
// imported by funnel.js in the browser AND unit-tested from Python via node
// (tests/ideation-dashboard/test_renderer.py). The renderer reads ONLY the
// snapshot; this module NEVER re-derives tallies or readiness (those are
// carried through verbatim from the snapshot fields). It only lays out the six
// funnel columns and the per-hop edges between snapshot entities.
//
// PARAMETERIZED AT SLICE S7 (docs/front-end-package-boundary.md § 5, § 4.3).
// This file was the densest in the tree — "28 governance literals in 126
// lines", § 3.2's own reading — and every one of them was one domain's spelling
// of a position in a pipeline. The six columns are now the six STAGE ROLES, and
// the words come from the registered profile's display facet through `ctx`:
//
//   source -> grouping -> candidate -> selection -> submission -> completion
//
// A column KEY is a role, so a node's `column`, its DOM id prefix and the
// collapse set are all neutral; a column LABEL and its gate caption are the
// domain's, read by role. Edge kinds match the mockup's SVG classes and are
// structure rather than vocabulary, so they stay literal:
//   topic  source->grouping and grouping->candidate (many-to-many claims)
//   pick   candidate->selection (the select-gate edge)
//   flow   selection->submission/completion (the submit/complete gate flow)
//
// THE ONE IMPORT is `./display.js`, itself import-free: the vocabulary reader
// and the snapshot's declared field names. `buildFunnelModel` takes the live
// `Display` from `ctx` and falls back to openDox's neutral words when a caller
// (a node harness, a pre-probe render) has none — the fallback is NEUTRAL, not
// this file's old literals, which is the distinction § 4.3 point 5 protects.

import { STAGE_ROLES, neutralDisplay } from "./display.js";

// Kept as an export under its landed name because `funnel.js` and the node
// harness both read it: the six COLUMN KEYS, which are now the six roles.
export const COLUMN_KEYS = STAGE_ROLES;

function sanitize(id) {
  return String(id).replace(/[^a-zA-Z0-9_-]/g, "_");
}

// Deterministic, collision-free DOM ids. Column prefix rules out cross-column
// collisions; a numeric suffix disambiguates any within-column sanitize clash.
function domIdFactory() {
  const seen = new Set();
  return (columnKey, snapshotId) => {
    const base = columnKey + "-" + sanitize(snapshotId);
    let domId = base;
    let n = 2;
    while (seen.has(domId)) domId = base + "--" + n++;
    seen.add(domId);
    return domId;
  };
}

export function buildFunnelModel(snapshot, display) {
  const d = display || neutralDisplay();
  const s = snapshot || {};
  const [SOURCE, GROUPING, CANDIDATE, SELECTION, SUBMISSION, COMPLETION] =
    STAGE_ROLES;
  // Read through the declared snapshot fields, never through a literal key:
  // `d.items(s, role)` resolves the field name (and, for the two change
  // stations, the closed status value) out of the facet's schema half.
  const sources = d.items(s, SOURCE);
  const groups = d.items(s, GROUPING);
  const candidates = d.items(s, CANDIDATE);
  const selections = d.items(s, SELECTION);

  const makeDomId = domIdFactory();
  const registry = new Map(); // `${columnKey}::${snapshotId}` -> node

  function register(columnKey, snapshotId, extra) {
    const domId = makeDomId(columnKey, snapshotId);
    const node = Object.assign({ column: columnKey, id: snapshotId, domId }, extra);
    registry.set(columnKey + "::" + snapshotId, node);
    return node;
  }
  function resolve(columnKey, snapshotId) {
    return registry.get(columnKey + "::" + snapshotId) || null;
  }

  const sourceNodes = sources.map((x) => register(SOURCE, x.id, { document: x }));
  const groupNodes = groups.map((c) => register(GROUPING, c.id, { cluster: c }));
  const candidateNodes = candidates.map(
    (p) => register(CANDIDATE, p.id, { possible: p }));
  const selectionNodes = selections.map(
    (t) => register(SELECTION, t.staging_id, { staged: t }));

  // A change is exactly one node: the two change stations are declared on the
  // SAME snapshot field and split by the status value the facet names.
  const submissions = d.items(s, SUBMISSION);
  const completions = d.items(s, COMPLETION);
  const submissionNodes = submissions.map(
    (c) => register(SUBMISSION, c.id, { change: c }));
  const completionNodes = completions.map(
    (c) => register(COMPLETION, c.id, { change: c }));
  const changeColumn = new Map();
  submissions.forEach((c) => changeColumn.set(c.id, SUBMISSION));
  completions.forEach((c) => changeColumn.set(c.id, COMPLETION));

  const edges = [];
  function link(fromNode, toNode, kind) {
    if (fromNode && toNode) {
      edges.push({
        from: fromNode.domId, to: toNode.domId, kind,
        fromColumn: fromNode.column, toColumn: toNode.column,
      });
    }
  }

  // source -> grouping (topic): strictly the snapshot's own document_edges
  for (const c of groups) {
    for (const e of c.document_edges || []) {
      link(resolve(SOURCE, e.document), resolve(GROUPING, c.id), "topic");
    }
  }
  // grouping -> candidate (topic): the many-to-many claiming_clusters edges
  for (const p of candidates) {
    for (const cid of p.claiming_clusters || []) {
      link(resolve(GROUPING, cid), resolve(CANDIDATE, p.id), "topic");
    }
  }
  // candidate -> selection (pick): the select-gate edge
  for (const p of candidates) {
    const sid = p.pick && p.pick.staging_id;
    if (sid) link(resolve(CANDIDATE, p.id), resolve(SELECTION, sid), "pick");
  }
  // selection -> change (flow): the submit/complete gate flow
  for (const t of selections) {
    const cid = t.target_change;
    if (cid) link(resolve(SELECTION, t.staging_id), resolve(changeColumn.get(cid), cid), "flow");
  }

  const nodesByRole = {
    [SOURCE]: sourceNodes,
    [GROUPING]: groupNodes,
    [CANDIDATE]: candidateNodes,
    [SELECTION]: selectionNodes,
    [SUBMISSION]: submissionNodes,
    [COMPLETION]: completionNodes,
  };
  // ONLY the first station collapses (the five-column view) — structure, not
  // vocabulary, so it is derived from the spine's own order.
  const columns = d.stages().map((stage) => ({
    key: stage.role,
    label: stage.label,
    gate: stage.gate || undefined,
    collapsible: stage.role === SOURCE,
    nodes: nodesByRole[stage.role] || [],
  }));

  return { columns, edges, resolve, registry };
}

// The five-column collapse hides the FIRST station. Edges touching a hidden
// column vanish — the SAME rule the CSS collapse enacts (the funnel's
// offsetParent guard). Exposed purely so the collapse is testable without a DOM.
export function collapsedColumnKeys(collapsed) {
  return collapsed ? new Set([STAGE_ROLES[0]]) : new Set();
}

export function visibleEdges(model, opts) {
  const collapsed = !!(opts && opts.collapsed);
  const hidden = collapsedColumnKeys(collapsed);
  return model.edges.filter((e) => !hidden.has(e.fromColumn) && !hidden.has(e.toColumn));
}
