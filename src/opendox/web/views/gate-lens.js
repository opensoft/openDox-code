// THE LENS'S TWO GATE VERBS — class B, and the first half of slice S4's answer
// to RULED Q3 (openxFactory#656 comment `5642758731`, Brett Heap, 2026-09-12):
// **"a route constant travels with the binding that calls it, never with the
// model that happens to declare it."**
//
// WHAT MOVED, AND FROM WHERE. `views/lens-model.js` is the census's purest
// class-A file — "pure and import-free", a geometry/matching derivation unit-
// tested from Python through node — and it carried two `/actions/gate/*`
// constants at :1036 and :1037 (openDox-spec `docs/front-end-package-boundary.md`
// § 1.2(c)'s table, § 3.2's `lens-model.js` row, § 4.5 assertion 2's "gate
// prefix, 10 sites, cleared by S4"). It declared them and never called them:
// `views/lens.js` did, from the execute affordance of its plan panel. Under Q3
// that makes the model the wrong home twice over — it neither calls them nor
// belongs to the column that serves them — so the two constants, the POST that
// uses them, the organizer-evidence form that feeds one of them and the outcome
// panel that renders either one's answer are all HERE now, in one class-B
// module the gate column owns.
//
// WHY A WHOLE MODULE AND NOT TWO CONSTANTS IN `lens.js`. `views/lens.js` is the
// census's one remaining `"?"` row (§ 3.2; none of Q1–Q5 rules on its two
// openxFactory-lane routes, so it stays `"?"` under assertion 1's declared,
// ruled-later exception). Moving a gate constant into it would relocate the
// § 2.2 rule 1 breach rather than clear it — assertion 2's scope is "every
// census row whose class is not B", and `"?"` is squarely in it. Class B is the
// only home that is not a relocation, and § 2.1's own test says why this file
// is one: delete the gate column and it has nothing left to render.
//
// HOW THE LENS REACHES IT: through the S3 VIEW REGISTRY, never an import.
// `views/lens.js` receives `mountLensGate` as an already-resolved closure from
// the shell (`app.js` resolves the `gate.lens` binding once per render, exactly
// as it resolves `gate.bar` for the viewer) and treats its absence as "no gate
// column here" — which is what a student install is (RULING C2 one tier out,
// § 4.1). That is `consumer_reach`'s posture in the browser: LATE, NAMED and
// REFUSABLE instead of an import-time dependency on a column that may not be
// installed (§ 4.2).
//
// AT S5 THIS FILE LEAVES THE BUNDLE. Its binding is declared in `app.js`'s
// CORE arm today and moves behind a contribution openXdox supplies (§ 5 S5);
// nothing in `lens.js` changes when it does, which is the test of whether the
// seam was drawn in the right place.
//
// WHAT IT DOES NOT OWN. The REQUEST BODIES are pure derivations over a plan the
// panel already confirmed (`recipeRequest` / `clusterRequest`), and a pure
// derivation over the snapshot is class-A substance that stays with the model
// — Q3 moves the ROUTE, not the arithmetic. They are imported from there, which
// is the legal direction (a class-B file may read class A; § 4.5 assertion 3
// forbids only the reverse).
//
// DOM-SAFETY, unchanged from the code's previous home: every dynamic value —
// including the engine's refusal text — binds through `textContent` (helpers'
// `el`), never `innerHTML`; the only `innerHTML` assignments are literal ""
// clears.
//
// A CREATED file: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
// (RULED OQ-C), admitted by path in `docs/opendox-carve-admissions.yaml`.

import { el } from "./helpers.js";
import { clusterRequest, recipeRequest } from "./lens-model.js";

// The two gate routes the lens verbs post to (add-lens-gate-verbs). They sit
// under `openxdox/serve_gate.py`'s `ACTIONS_GATE_PREFIX` and are declared by
// the gate column, so they live in the binding that calls them — the deployed
// static image never serves them, and the plan panel probes the gate
// capability before revealing execute.
export const LENS_SAVE_ROUTE = "/actions/gate/lens-save-recipe";
export const LENS_CLUSTER_ROUTE = "/actions/gate/lens-add-as-cluster";

// The routes this binding declares to the registry, in one place so the
// `gate.lens` entry and this module cannot drift apart.
export const LENS_GATE_ROUTES = [LENS_SAVE_ROUTE, LENS_CLUSTER_ROUTE];

async function postPlan(route, body, fetcher) {
  const doFetch = fetcher || fetch;
  const response = await doFetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  try {
    return await response.json();
  } catch {
    return { ok: false, message: "malformed response (HTTP " + response.status + ")" };
  }
}

// Render the landing confirmation (success) or the engine's refusal verbatim.
// textContent-bound like every other value here.
function renderOutcome(container, result) {
  container.innerHTML = "";
  if (result && result.ok) {
    const ok = el("div", "dc-landed");
    ok.appendChild(el("div", "dc-h", "landed ✓ — recorded gate dispatch"));
    ok.appendChild(el("div", "dc-line", "manifest: " + result.manifest));
    if (result.pending_entry) {
      ok.appendChild(el("div", "dc-line", "pending entry: " + result.pending_entry));
    }
    ok.appendChild(el("div", "dc-line", "gate-action record: " + result.record));
    if (result.note) ok.appendChild(el("div", "dc-note", result.note));
    container.appendChild(ok);
  } else {
    const refused = el("div", "dc-refused");
    refused.appendChild(el("div", "dc-h", "refused ✕"));
    refused.appendChild(el("div", "dc-line", (result && result.message) || "gate action failed"));
    container.appendChild(refused);
  }
}

// The human-seen organizer evidence form (add-as-cluster only). Collects the
// full contract the engine requires; a blank/short field is NOT pre-validated —
// the engine refuses and the reason renders verbatim (single source of truth).
function renderEvidenceForm(container, actor, onSubmit) {
  function clear() {
    container.innerHTML = "";
  }
  clear();
  const form = el("div", "reason-form evidence-form");
  form.appendChild(el("span", "rf-label",
    "human-seen evidence (organizer contract — the engine refuses an incomplete one):"));
  const fields = [
    ["proposer", "proposer", actor],
    ["revision", "committed revision (40/64-hex)", ""],
    ["path", "source path", ""],
    ["section", "section", ""],
    ["passage_sha256", "passage sha256 (64-hex)", ""],
    ["rationale", "rationale", ""],
    ["confidence", "confidence 0–1", ""],
    ["alternatives", "alternatives (comma-separated; may be empty)", ""],
  ];
  const inputs = {};
  for (const [key, label, value] of fields) {
    const input = document.createElement("input");
    input.type = "text";
    input.value = value || "";
    input.setAttribute("aria-label", label);
    input.setAttribute("placeholder", label);
    inputs[key] = input;
    form.appendChild(input);
  }
  const submit = el("button", "cbtn", "execute");
  submit.type = "button";
  const cancel = el("button", "cbtn", "cancel");
  cancel.type = "button";
  submit.addEventListener("click", () => {
    const alts = inputs.alternatives.value.split(",").map((s) => s.trim()).filter((s) => s);
    const conf = parseFloat(inputs.confidence.value);
    onSubmit({
      proposer: inputs.proposer.value.trim(),
      revision: inputs.revision.value.trim(),
      path: inputs.path.value.trim(),
      section: inputs.section.value.trim(),
      passage_sha256: inputs.passage_sha256.value.trim(),
      rationale: inputs.rationale.value.trim(),
      confidence: Number.isNaN(conf) ? inputs.confidence.value.trim() : conf,
      alternatives: alts,
    });
  });
  cancel.addEventListener("click", clear);
  form.appendChild(submit);
  form.appendChild(cancel);
  container.appendChild(form);
}

// THE BINDING'S ENTRY. `host` is the plan panel's own box — a `"shell"` region
// (`lens-gate`), which by § 4.1's own definition is a mount point the shell
// builds at mount time and hands over, exactly like `viewer-gatebar`. `ctx`
// carries the confirmed plan, the capability probe's payload and the
// injectable fetcher (the test seam every transport in this bundle keeps).
//
// A save-recipe plan posts immediately; an add-as-cluster plan first collects
// the human-seen organizer evidence, and the engine's refusal for an incomplete
// submission renders here.
export function mountLensGate(host, ctx) {
  const o = ctx || {};
  const plan = o.plan;
  if (!host || !plan) return null;
  const result = el("div", "dc-result");
  result.setAttribute("aria-live", "polite");
  const bar = el("div", "dc-exec");
  const run = el("button", "cbtn",
    plan.kind === "add-as-cluster" ? "execute → add as cluster" : "execute → save recipe");
  run.type = "button";
  run.title = "EXECUTES via the local gate route (actor: " + ((o.caps && o.caps.actor) || "local") + ")";

  async function dispatch(body, route) {
    run.disabled = true;
    const payload = await postPlan(route, body, o.fetcher);
    renderOutcome(result, payload);
    if (!(payload && payload.ok)) run.disabled = false;  // let a refused plan be retried
  }

  run.addEventListener("click", () => {
    if (plan.kind === "add-as-cluster") {
      renderEvidenceForm(result, (o.caps && o.caps.actor) || "", (evidence) => {
        dispatch(clusterRequest(plan, evidence), LENS_CLUSTER_ROUTE);
      });
    } else {
      dispatch(recipeRequest(plan), LENS_SAVE_ROUTE);
    }
  });
  bar.appendChild(run);
  host.appendChild(bar);
  host.appendChild(result);
  return { element: bar, result };
}
