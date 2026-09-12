// THE PROJECT COMMISSIONS — class B, and the second half of slice S4's answer to
// RULED Q3 (openxFactory#656 comment `5642758731`, Brett Heap, 2026-09-12):
// **"a route constant travels with the binding that calls it, never with the
// model that happens to declare it."**
//
// WHAT MOVED, AND FROM WHERE. `views/repo-selector.js` is the file openDox-spec
// `docs/front-end-package-boundary.md` § 3.2 describes as addressing ALL THREE
// COLUMNS from one place: openDox's `/project-register.json` and
// `/actions/refresh`, openXdox's `/snapshot-index.json` and its two
// `/actions/gate/*` project commissions, and openxFactory's own
// `/actions/apply-register-edits` lane. Q3 RULES it SPLIT: "the picker and the
// refresh affordance are class A; the two `/actions/gate/*` project commissions
// become a contributed binding with S4; `/actions/apply-register-edits` is
// openxFactory's lane and leaves the bundle entirely."
//
// THIS FILE IS THAT CONTRIBUTED BINDING. It owns the two gate routes, the
// create-project form that commissions a new project, and the membership-edit
// commission the repo filter's add line and trash controls raise. The PICKER
// stays where it was: choosing what you are looking at is the student's own
// gesture (§ 6 Q3: "moving it whole puts the project picker — the student's way
// to choose what they are working on — behind the gate column"), so only the
// COMMISSIONING half travels.
//
// A COMMISSION IS NOT A WRITE, and that is the whole posture the two routes
// carry with them: the POST records a project-register-edit descriptor plus a
// gate record, and the aggregation-owned register is edited only by the
// fulfilment. Refusals render `textContent`-only; a successful create retires
// the form for the session (the engine's duplicate guard is the backstop).
//
// HOW THE SELECTOR REACHES IT: through the S3 VIEW REGISTRY, never an import.
// `app.js` resolves the `gate.projects` binding once per render — exactly as it
// resolves `gate.bar` for the viewer — and hands `mountRepoSelector` the
// resolved mount, or null. Null is what a student install is: no "New Project…"
// line that acts, no create form, no add row, no trash control, and NO 404
// (§ 4.1's own promise, RULING C2 one tier out). That is `consumer_reach`'s
// posture in the browser: LATE, NAMED and REFUSABLE instead of an import-time
// dependency on a column that may not be installed (§ 4.2).
//
// AT S5 THIS FILE LEAVES THE BUNDLE. Its binding is declared in `app.js`'s CORE
// arm today and moves behind a contribution openXdox supplies (§ 5 S5); nothing
// in `repo-selector.js` changes when it does, which is the test of whether the
// seam was drawn in the right place — the reason this module is shaped as a
// binding with a `mount` entry and a returned controller rather than as two
// exported helpers the selector calls.
//
// TWO DEAD PARAMETERS DID NOT TRAVEL. The previous `mountCreateProject(wrap,
// status, roster, projects, o, addPendingOption)` never read `projects`, and
// `commissionEdit(body, control, restore)` never read `control` — both callers
// passed a value that the body ignored. Carrying an unread parameter across a
// package boundary would freeze a mistake into the contributed contract, so
// neither is in the signatures below.
//
// DOM-SAFETY, unchanged from the code's previous home: every dynamic value
// binds through `textContent` (helpers' `el`); no `innerHTML` is assigned here
// at all.
//
// A CREATED file: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
// (RULED OQ-C), admitted by path in `docs/opendox-carve-admissions.yaml`.

import { el } from "./helpers.js";

// add-project-scoped-selection: the create-project commission route.
// add-opendox-project-header (D15/D16): the membership-edit commission route
// the filter popover's add line and trash controls POST to. Both sit under
// `openxdox/serve_gate.py`'s `ACTIONS_GATE_PREFIX`, and both degrade away
// exactly like the index: a static image 404s them and the selector renders
// without the affordance.
export const ACTIONS_CREATE_PROJECT_ROUTE = "/actions/gate/create-project";
export const ACTIONS_EDIT_PROJECT_ROUTE = "/actions/gate/edit-project";

// The routes this binding declares to the registry, in one place so the
// `gate.projects` entry and this module cannot drift apart.
export const PROJECT_GATE_ROUTES = [
  ACTIONS_CREATE_PROJECT_ROUTE, ACTIONS_EDIT_PROJECT_ROUTE,
];

// The create-project affordance (add-project-scoped-selection): a COMMISSION,
// never a write. Mounted only where this binding is contributed AND the probe
// reports the gate capability. Member candidates are ALL roster repositories:
// membership is multi-parent (Brett's 2026-08-06 ruling), so a repository
// already in a project is a legal member of a new one — projects are named
// views, not owners.
//
// REHOMED by add-opendox-project-header (D13): no standalone button — the
// project dropdown's "New Project" line opens the form through the returned
// opener.
function mountCreateProject(wrap, status, roster, o, addPendingOption) {
  const seen = new Set();
  const candidates = [];
  for (const option of roster || []) {
    if (option.kind !== "repository") continue;
    if (seen.has(option.repository)) continue;
    seen.add(option.repository);
    candidates.push(option.repository);
  }

  // A LABELED PANEL, not a bare strip (Brett's 2026-08-06 annotation: "which
  // is this? i do not know how to use this widget") — a heading names the
  // act, the field and the member list carry captions, and the buttons say
  // what happens (a recorded commission, not a direct write).
  const form = el("span", "projectform projectpanel");
  form.hidden = true;
  form.appendChild(el("span", "panelhead", "New Project"));
  form.appendChild(el("span", "panelnote",
    "records a project-register commission — the project appears as pending "
    + "until a session fulfils it"));

  const nameField = el("label", "panelfield");
  nameField.appendChild(el("span", "panellabel", "project name"));
  const name = el("input", "projectname");
  name.type = "text";
  name.placeholder = "e.g. Field Pilots";
  name.setAttribute("aria-label", "new project name");
  nameField.appendChild(name);
  form.appendChild(nameField);

  form.appendChild(el("span", "panellabel", "member repositories"));
  const memberList = el("span", "panelmembers");
  const boxes = [];
  for (const repo of candidates) {
    const label = el("label", "projectmember");
    const box = el("input");
    box.type = "checkbox";
    box.value = repo;
    label.appendChild(box);
    label.appendChild(el("span", null, repo));
    boxes.push(box);
    memberList.appendChild(label);
  }
  if (!candidates.length) {
    memberList.appendChild(el("span", "projectform-note",
      "no published repositories to choose from"));
  }
  memberList.appendChild(el("span", "projectform-note",
    "optional — an empty project is fine; add repositories later from the "
    + "filter"));
  form.appendChild(memberList);

  const buttonRow = el("span", "panelbuttons");
  const submit = el("button", "repobtn", "commission project");
  submit.type = "button";
  buttonRow.appendChild(submit);
  const cancel = el("button", "repobtn projectcancel", "cancel");
  cancel.type = "button";
  cancel.addEventListener("click", () => { form.hidden = true; });
  buttonRow.appendChild(cancel);
  form.appendChild(buttonRow);

  submit.addEventListener("click", async () => {
    const members = boxes.filter((b) => b.checked).map((b) => b.value);
    status.textContent = "";
    submit.disabled = true;
    try {
      const opts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.value, repositories: members }),
      };
      const response = o.fetcher
        ? await o.fetcher(ACTIONS_CREATE_PROJECT_ROUTE, opts)
        : await fetch(ACTIONS_CREATE_PROJECT_ROUTE, opts);
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data?.ok !== true) {
        submit.disabled = false;
        status.textContent = "create-project refused: "
          + (data?.message || data?.error || ("HTTP " + response.status));
        return;
      }
      form.hidden = true;                   // retired for the session
      status.textContent = "project-register edit recorded (" + data.job + ")";
      // the commission appears in the dropdown immediately as a pending entry
      // (D-e) — the register itself changes only when the fulfilment lands
      if (addPendingOption) addPendingOption(name.value || data.project_id);
    } catch (err) {
      submit.disabled = false;
      status.textContent = "create-project failed: " + (err?.message || "error");
    }
  });

  wrap.appendChild(form);
  return () => {                             // the "New Project…" opener (D13)
    form.hidden = false;
    name.focus();
  };
}

// THE BINDING'S ENTRY. `host` is the selector's own header slot — a `"shell"`
// region (`repo-projects`), which by § 4.1's definition is a mount point the
// shell builds at mount time and hands over, exactly like `viewer-gatebar`.
//
// `ctx` is `{ roster, status, fetcher, addPendingOption }`: the roster the
// member checklist is drawn from, the selector's one message span (a
// commission's refusal renders where every other selector message does), the
// injectable fetcher every transport in this bundle keeps as its test seam,
// and the dropdown's pending-entry appender.
//
// Returns the two acts the selector triggers and this column performs:
//
//   openCreateForm()                       the D13 "New Project…" line
//   commissionEdit(projectId, body, opts)  the filter's add row and trash
//
// `opts` for a membership edit is `{ restore, onRecorded }`: `restore` puts the
// control the human clicked back the way it was when the commission is refused
// (a two-click trash re-arms, a select restores its placeholder), and
// `onRecorded(data)` hands the accepted commission back so the selector can
// badge the pending edit (the D-e two-plane posture). Neither is required.
export function mountProjectCommissions(host, ctx) {
  const o = ctx || {};
  const status = o.status || el("span", "repopick-msg");
  const openCreateForm = mountCreateProject(host, status, o.roster, o,
                                            o.addPendingOption);

  async function commissionEdit(projectId, body, opts) {
    const { restore, onRecorded } = opts || {};
    status.textContent = "";
    try {
      const fetchOpts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: projectId, ...body }),
      };
      const response = o.fetcher
        ? await o.fetcher(ACTIONS_EDIT_PROJECT_ROUTE, fetchOpts)
        : await fetch(ACTIONS_EDIT_PROJECT_ROUTE, fetchOpts);
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data?.ok !== true) {
        if (restore) restore();
        status.textContent = "edit-project refused: "
          + (data?.message || data?.error || ("HTTP " + response.status));
        return;
      }
      status.textContent = "membership edit recorded (" + data.job + ")";
      if (onRecorded) onRecorded(data);
    } catch (err) {
      if (restore) restore();
      status.textContent = "edit-project failed: " + (err?.message || "error");
    }
  }

  return { openCreateForm, commissionEdit };
}
