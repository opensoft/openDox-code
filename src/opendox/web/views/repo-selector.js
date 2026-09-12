// Repository selector + refresh affordance (add-dashboard-repo-selector tasks
// 3.2/3.6, and Brett's 2026-07-26 open-question rulings). The header control
// that switches the ACTIVE (repository, ref) snapshot and asks the serving side
// for fresher data.
//
// SPLIT AT § 3.4 SLICE S4 (RULED Q3, openxFactory#656 comment `5642758731`,
// Brett Heap, 2026-09-12: "a route constant travels with the binding that calls
// it, never with the model that happens to declare it"). This file used to
// address ALL THREE COLUMNS from one place — openDox's, openXdox's and
// openxFactory's own — which openDox-spec `docs/front-end-package-boundary.md`
// § 3.2 records as the reason it was RULED SPLIT. What is left here is class A:
//
//   GET  /project-register.json  — openDox's own register projection, read by
//                                  the project picker (`serve_project.py`)
//   POST /actions/refresh        — ONE affordance, the BINDING chosen by the
//                                  plane (served: re-fetch; local: regenerate),
//                                  declared by BOTH legs (§ 3.3's table)
//
// and both are absent from a static image, which is exactly how the whole
// control degrades away. What LEFT, and where to:
//
//   /snapshot-index.json         — openXdox's projection: `views/projection-index.js`,
//                                  reached LATE and REFUSABLY by `fetchIndex` below
//   the two /actions/gate/* project commissions
//                                — `views/gate-projects.js`, the class-B binding
//                                  the shell resolves and hands in as
//                                  `mountProjectGate`
//   /actions/apply-register-edits
//                                — openxFactory's own fulfilment lane, which
//                                  RULING DQ-1 keeps at openxFactory: it LEFT
//                                  THE BUNDLE ENTIRELY, with the "⟳ apply N
//                                  pending" button that reached it. See the note
//                                  at `mountRepoSelector` for what that means
//                                  for a commissioned-but-unfulfilled register.
// The bundle NEVER addresses the external data source: the serving side performs
// that fetch (design D5), so the grep-proven no-external-URL boundary in
// tests/ideation-dashboard/test_renderer.py survives this change unedited.
//
// PASSIVE FRESHNESS HINT (ruling on open question 2): a background poll of the
// THIN index every POLL_INTERVAL_MS shows a "newer data available" badge when
// the source advertises a newer snapshot than the one loaded. It NEVER reloads
// by itself — the viewer clicks refresh. The poll re-uses the same index fetch,
// so no new data path appears.
//
// DOM-SAFETY: every dynamic value binds through textContent; innerHTML is never
// assigned here.

import {
  addableRepositories, buildPendingEdits, buildPendingProjects, buildProjects,
  buildRoster, defaultProjectScope, freshnessLabel, hintLabel, keyId,
  KIND_REPOSITORY, netPendingEdit, newerAvailable, projectFilterRows,
  repositoryVisible, sameKey, staleNotice, toggleVisibility,
  visibleRepositories,
} from "./repo-selector-model.js";
import { VIEW_SHARED, VIEW_UNION } from "./composed-model.js";

export const ACTIONS_REFRESH_ROUTE = "/actions/refresh";
// add-project-scoped-selection: the register projection the project picker
// reads. openDox's own (`serve_project.py`), and it degrades away exactly like
// the index: a static image 404s it and the selector renders unscoped.
export const PROJECT_REGISTER_PROJECTION_ROUTE = "/project-register.json";
// The viewer's project scope survives the reload a selection triggers. It is
// THIRD-PARTY DATA on the way back in: it only ever filters client-side
// (membership-checked against the loaded projection) and never reaches a URL.
export const PROJECT_SCOPE_STORAGE_KEY = "xfDashProjectScope";
// D19: the per-project visible set + view mode (see `storedViewState`).
export const VIEW_STATE_STORAGE_KEY = "xfDashProjectView";
// ~5 minutes: the ruled cadence. Slow enough that the serving side's own peek
// cache absorbs N viewers, fast enough that "did my doc land?" answers itself
// while the tab is open.
export const POLL_INTERVAL_MS = 300000;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

// THE PROJECTION COLUMN, REACHED LATE (§ 3.4 slice S4, § 4.2). The snapshot
// index is `/snapshot-index.json`, which `openxdox/serve_projection.py` declares
// and contributes — another column's route, so § 2.2 rule 1 keeps it out of this
// class-A file. `views/projection-index.js` owns the constant and the fetch, and
// this is the "small, local, late-and-refusable guard directly against the
// module's own presence" § 4.2 establishes for exactly this shape: a dynamic
// import(), never a static one, resolved ONCE and remembered. An absent
// projection column answers null, which is the outcome `fetchIndex` has always
// promised for a route nothing serves.
//
// `undefined` means "not yet asked"; `null` means "asked, and there is no
// projection column here" — two states, so a leg without the module pays for
// one rejected import and not one per poll.
let PROJECTION_COLUMN;

async function projectionColumn() {
  if (PROJECTION_COLUMN === undefined) {
    try {
      PROJECTION_COLUMN = await import("./projection-index.js");
    } catch {
      PROJECTION_COLUMN = null;
    }
  }
  return PROJECTION_COLUMN;
}

// Fetch the snapshot index. ANY failure (a static image 404s this route, an old
// server does not know it, file:// throws, no projection column is installed)
// resolves to null — the caller then renders exactly today's single-snapshot
// dashboard. Never throws.
export async function fetchIndex(injectedFetch) {
  const column = await projectionColumn();
  if (!column) return null;
  return column.fetchSnapshotIndex(injectedFetch);
}

// POST the refresh. Resolves to the backend's freshness result, or throws an
// Error carrying the backend's fixed message — the caller reports it INLINE and
// keeps the currently rendered snapshot (spec scenario "A refresh fails").
export async function postRefresh(body, injectedFetch) {
  const opts = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  };
  const response = injectedFetch
    ? await injectedFetch(ACTIONS_REFRESH_ROUTE, opts)
    : await fetch(ACTIONS_REFRESH_ROUTE, opts);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data?.message || data?.error || ("HTTP " + response.status));
  return data;
}

// Fetch the register projection. Same degrade contract as `fetchIndex`: any
// failure resolves to null and the picker simply does not render.
export async function fetchProjects(injectedFetch) {
  try {
    const response = injectedFetch
      ? await injectedFetch(PROJECT_REGISTER_PROJECTION_ROUTE, { cache: "no-store" })
      : await fetch(PROJECT_REGISTER_PROJECTION_ROUTE, { cache: "no-store" });
    if (!response?.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

export function storedProjectScope(storage) {
  try {
    return (storage || window.sessionStorage).getItem(PROJECT_SCOPE_STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

export function storeProjectScope(id, storage) {
  try {
    const store = storage || window.sessionStorage;
    if (id) store.setItem(PROJECT_SCOPE_STORAGE_KEY, id);
    else store.removeItem(PROJECT_SCOPE_STORAGE_KEY);
  } catch { /* storage denied: the scope is simply session-transient */ }
}

// D19 — the per-project VISIBLE set and view mode, one stored document:
// `{ "<project>": { "visible": [...], "mode": "union" } }`. Read defensively:
// any malformed value degrades to "nothing stored", which means every member
// under union — the composition's own default.
export function storedViewState(storage) {
  try {
    const raw = (storage || window.sessionStorage)
      .getItem(VIEW_STATE_STORAGE_KEY);
    const doc = raw ? JSON.parse(raw) : null;
    return doc && typeof doc === "object" && !Array.isArray(doc) ? doc : {};
  } catch {
    return {};
  }
}

export function storeViewState(projectId, state, storage) {
  if (!projectId) return;
  try {
    const store = storage || window.sessionStorage;
    const doc = storedViewState(store);
    doc[String(projectId)] = state;
    store.setItem(VIEW_STATE_STORAGE_KEY, JSON.stringify(doc));
  } catch { /* storage denied: the view is simply session-transient */ }
}

// The stored set/mode for one project, resolved against its CURRENT members.
//
// `active` reconciles the set with what is ACTUALLY SERVED: whenever the
// served snapshot is a single member repository — a project switch, an
// "open in <repo>" jump, a first-ever load — the visible set IS that
// repository, whatever was stored. The ticks describe the view rather than
// contradicting it, and no reload is needed to make them agree. When the
// aggregate is served, the stored set governs.
export function projectViewState(project, storage, active) {
  const doc = storedViewState(storage);
  const visibility = {};
  for (const [id, entry] of Object.entries(doc)) {
    if (entry && Array.isArray(entry.visible)) visibility[id] = entry.visible;
  }
  const stored = doc[String(project?.id)] || {};
  const members = (project?.repositories || []).map(String);
  const served = active && String(active.repository);
  const single = served && served !== String(project?.id)
    && members.includes(served);
  return {
    visible: single ? [served] : visibleRepositories(project, visibility),
    mode: stored.mode === VIEW_SHARED ? VIEW_SHARED : VIEW_UNION,
  };
}

export function refreshCapable(caps) {
  return caps?.actions?.refresh === true;
}

export function gateCapable(caps) {
  return caps?.actions?.gate === true;
}

export function refreshBinding(caps) {
  return caps?.refresh?.binding || null;
}

// THE CREATE-PROJECT FORM IS `views/gate-projects.js`'S NOW (§ 3.4 slice S4).
// `mountCreateProject` stood here and POSTed the create-project commission
// route from a class-A file; RULED Q3 sends both the route and the form that
// raises it to the class-B binding the gate column owns. The shell resolves that
// binding and hands its mount in as `mountProjectGate`; the dropdown's "New
// Project…" line calls the opener it returns. Absent — a student install — the
// line is disabled and there is no form, no 404 and no dead control.

// The repo FILTER (add-opendox-project-header D14/D16): one icon, one
// popover scoped to the CURRENT project, working like the project dropdown
// (Brett's 2026-08-06 header annotation): the FIRST line adds a repository
// to the project, then the all-repos line, then one row per member — an
// EYEBALL on the left saying whether that repository is visible in the
// current view, the repository name (click = serve it), and a TRASH control
// on the right that commissions its removal (two-click, so a stray click
// arms rather than acts). Add and remove are edit-project COMMISSIONS —
// recorded, register untouched until fulfilment — and pending membership
// edits badge their rows (the D-e two-plane posture). Gate off, the add
// line and the trash controls are absent and the rows stay selectable.
// DOM-safety: textContent only, throughout.
function mountProjectFilter(project, roster, pendingEdits, opts) {
  const holder = el("span", "repofilter");
  if (!project) return holder;
  const o = opts || {};
  // Gated is the AND of "the backend says the gate capability is live" and "the
  // gate column is registered here" (§ 3.4 slice S4) — never either alone, the
  // same conjunction `views/intent-binding.js` states for its own optional
  // binding. `o.gate` is the shell-resolved `gate.projects` controller; absent,
  // the add line and the trash controls are not rendered at all and the rows
  // stay selectable, which is the gate-off posture D16 already described.
  const gated = gateCapable(o.caps) && !!o.gate;
  // reread per render: a same-page commission appends to `pendingEdits`,
  // and edits QUEUE (topic D18) — the overlay is the NET of every queued row
  const currentPendingEdit = () => netPendingEdit(pendingEdits, project);

  // D19 — the visible set drives the view: `applyView` is the ONE writer, and
  // it persists then reloads, exactly the ratified reload-per-switch posture
  // every other selector gesture already uses.
  const visible = (o.visible || []).map(String);
  const applyView = (nextVisible, nextMode) =>
    o.onView?.({ visible: nextVisible.map(String), mode: nextMode });
  // The project's DERIVED aggregate, when the plane can compose one: its
  // presence is what makes a multi-repository view possible at all, so it
  // decides whether the rows below are visibility toggles or the pre-D19
  // single-select list.
  const aggregateOption = (projectFilterRows(roster, project)
    .find((r) => r.kind === "all") || {}).option || null;

  // The box names its content (Brett's 2026-08-06 annotation): a
  // single-member project shows THAT repository's name; several show the
  // count — now the VISIBLE count against the total (D19), so the header
  // states the view without opening the popover.
  const members = project.repositories || [];
  const boxLabel = members.length === 1 ? members[0]
    : (visible.length === members.length
        ? members.length + " Repos"
        : visible.length + " of " + members.length + " Repos");
  const button = el("button", "repobtn filterbtn", "\u29e9 " + boxLabel);
  button.type = "button";
  button.title = "repositories in " + project.name;
  button.setAttribute("aria-label", "repository filter for " + project.name);
  button.setAttribute("aria-expanded", "false");
  const pop = el("span", "filterpop");
  pop.hidden = true;
  button.addEventListener("click", () => {
    pop.hidden = !pop.hidden;
    button.setAttribute("aria-expanded", pop.hidden ? "false" : "true");
  });

  // THE COMMISSION ITSELF IS THE GATE COLUMN'S (§ 3.4 slice S4). This view owns
  // the CONTROL — which row, which repository, armed or not — and hands the act
  // to the `gate.projects` binding, which owns the route, the POST and the
  // refusal text. What stays here is what the popover must do with the answer:
  // badge the accepted edit immediately (D-e) and re-render.
  function commissionEdit(body, restore) {
    if (!o.gate) return;
    o.gate.commissionEdit(project.id, body, {
      restore,
      onRecorded: (data) => {
        pendingEdits = (pendingEdits || []).concat([{
          projectId: project.id, add: data.add, remove: data.remove }]);
        renderRows();
      },
    });
  }

  // D16's first line, refined by Brett's 2026-08-06 annotation: ONE dropdown
  // that closes like the project selector. The placeholder line IS the
  // affordance; choosing a candidate commissions the single addition and the
  // native select closes itself, the placeholder restoring immediately.
  function mountAddRow(pendingEdit) {
    const candidates = addableRepositories(roster, o.projects, project)
      .filter((r) => !(pendingEdit && pendingEdit.add.includes(r)));
    const select = el("select", "repopick filteraddselect");
    select.setAttribute("aria-label", "add a repository to " + project.name);
    const placeholder = el("option", null,
      candidates.length ? "\uff0b add repository\u2026"
                        : "\uff0b add repository\u2026 (none available)");
    placeholder.value = "";
    select.appendChild(placeholder);
    for (const repository of candidates) {
      const opt = el("option", null, repository);
      opt.value = repository;
      select.appendChild(opt);
    }
    select.disabled = !candidates.length;
    select.addEventListener("change", () => {
      const chosen = select.value;
      select.value = "";                  // the placeholder line returns
      if (chosen) commissionEdit({ add: [chosen] }, null);
    });
    pop.appendChild(select);
  }

  // D19 \u2014 the VIEW ROW: what the wheels currently span. Union/shared is one
  // toggle, "all"/"none" are the two bulk moves, and the count states the
  // set \u2014 which together cover every selection the old all-repos line and the
  // single-select click used to cover separately.
  // A LIVE BRANCH SESSION, addressable (Brett, 2026-08-10: "how do I get to the
  // rest of the workbench on this doc?"). The serving index advertises a live
  // session as an ordinary `(repository, ref)` row (FR-014) and the roster has
  // carried it all along — nothing here asks the server anything new. What was
  // missing was a way to NAME it: the repository row picked an arbitrary ref, so
  // the only way onto a session branch was to land on it unknowingly.
  //
  // Selecting one keys the whole dashboard to that branch, which is what the
  // runbook's §4 has always described, and the freshness header then names the
  // ref. It is deliberately a plain select, not a filter tick: a session is a
  // different VIEW of one repository, never a member of the merged view.
  function mountSessionRow(row) {
    const line = el("span", "filterline filtersessionline");
    const entry = el("button", "filterrow filtersession", "⎇ " + row.ref);
    entry.type = "button";
    entry.title = "read " + row.repository + " on its live session branch "
      + row.ref + " — the documents this session has created or rewritten, "
      + "which main does not carry";
    entry.addEventListener("click", () => o.onSelect?.({
      repository: row.option.repository, ref: row.option.ref }));
    line.appendChild(entry);
    line.appendChild(el("span", "filtersessionnote", "live session"));
    pop.appendChild(line);
  }

  function mountViewRow(aggregate) {
    const members = (project.repositories || []).map(String);
    const line = el("span", "filterline filterviewline");
    if (!aggregate) {
      // No derived aggregate (no member publishes a snapshot): nothing can be
      // composed, so the view row states that and the rows below stay
      // single-select exactly as they were.
      const note = el("span", "filterrow filterall",
        "\u229e all repositories in " + project.name
        + " (merged view unavailable \u2014 no member snapshot is published)");
      note.setAttribute("aria-disabled", "true");
      line.appendChild(note);
      pop.appendChild(line);
      return;
    }
    const sharing = o.viewMode === VIEW_SHARED;
    // NOT a `filterrow`: rows are member repositories, and conflating the
    // mode control with them makes both the styling and the DOM ambiguous.
    const mode = el("button", "filtermode", sharing ? "\u2229 shared" : "\u222a union");
    mode.type = "button";
    mode.title = sharing
      ? "showing only what TWO OR MORE visible repositories carry "
        + "\u2014 click for the union"
      : "showing everything from every visible repository "
        + "\u2014 click for what two or more of them share";
    mode.disabled = visible.length < 2;      // one repository: same either way
    mode.addEventListener("click", () => applyView(
      visible, sharing ? VIEW_UNION : VIEW_SHARED));
    line.appendChild(mode);

    const count = el("span", "filtercount",
      visible.length + " of " + members.length);
    line.appendChild(count);

    const all = el("button", "filterbulk", "all");
    all.type = "button";
    all.title = "show every repository in " + project.name;
    all.disabled = visible.length === members.length;
    all.addEventListener("click", () => applyView(members, o.viewMode));
    line.appendChild(all);

    const none = el("button", "filterbulk", "none");
    none.type = "button";
    none.title = "hide every repository (the view empties until you tick one)";
    none.disabled = visible.length === 0;
    none.addEventListener("click", () => applyView([], o.viewMode));
    line.appendChild(none);
    pop.appendChild(line);
  }

  function renderRows() {
    const pendingEdit = currentPendingEdit();
    pop.textContent = "";
    if (gated) mountAddRow(pendingEdit);
    for (const row of projectFilterRows(roster, project)) {
      if (row.kind === "all") {
        mountViewRow(row.option);
        continue;
      }
      if (row.kind === "session") {
        mountSessionRow(row);
        continue;
      }
      // one member row: [eye -> show/hide] [name -> only this one] [trash]
      const line = el("span", "filterline");
      // D19: with a composable project the eyeball IS the control \u2014 it ticks
      // this repository into or out of the view. Without one (no member
      // publishes) it stays the D16 indicator over the single served view.
      const composable = !!aggregateOption;
      const shown = composable
        ? visible.includes(String(row.repository))
        : repositoryVisible(row.repository, project, o.active);
      const eye = el(composable ? "button" : "span",
        "filtereye" + (shown ? " filtervisible" : ""),
        shown ? "\ud83d\udc41" : "\u25cc");
      if (composable) {
        eye.type = "button";
        eye.title = (shown ? "hide " : "show ") + row.repository
          + " in the view";
        eye.setAttribute("aria-pressed", shown ? "true" : "false");
        eye.disabled = !row.option;        // nothing published: nothing to show
        eye.addEventListener("click", () => applyView(
          toggleVisibility(visible, row.repository,
                           project.repositories || []), o.viewMode));
      } else {
        eye.title = shown
          ? "visible in the current view"
          : "not in the current view \u2014 click the name to serve it";
      }
      line.appendChild(eye);

      const entry = el("button", "filterrow", row.repository);
      entry.type = "button";
      if (pendingEdit && pendingEdit.remove.includes(row.repository)) {
        entry.textContent += " (removal pending)";
      }
      if (row.option) {
        if (sameKey(row.option, o.active)) entry.classList.add("filteractive");
        if (!row.option.available) {
          entry.textContent += " (" + (row.option.unavailableReason
            || "snapshot unavailable") + ")";
        }
        // D19: the NAME solos \u2014 the one-click "just show me this repository"
        // gesture the single-select filter had, expressed in the visible set
        // (one visible repository serves its own snapshot, fully interactive).
        entry.title = composable
          ? "show only " + row.repository
          : "serve " + row.repository;
        entry.addEventListener("click", () => (composable
          ? applyView([row.repository], o.viewMode)
          : o.onSelect?.({ repository: row.option.repository,
                           ref: row.option.ref })));
      } else {
        entry.disabled = true;
        entry.textContent += " (no published snapshot)";
      }
      line.appendChild(entry);

      if (gated && !(pendingEdit && pendingEdit.remove.includes(row.repository))) {
        // two-click removal: the first click ARMS, the second commissions —
        // a register edit should never ride a stray click.
        const trash = el("button", "filtertrash", "\ud83d\uddd1");
        trash.type = "button";
        trash.title = "remove " + row.repository + " from " + project.name
          + " (recorded commission; the register changes at fulfilment)";
        let armed = false;
        trash.addEventListener("click", () => {
          if (!armed) {
            armed = true;
            trash.textContent = "remove?";
            trash.classList.add("filterarmed");
            return;
          }
          trash.disabled = true;
          commissionEdit({ remove: [row.repository] }, () => {
            trash.disabled = false;
            armed = false;
            trash.textContent = "\ud83d\uddd1";
            trash.classList.remove("filterarmed");
          });
        });
        line.appendChild(trash);
      }
      pop.appendChild(line);
    }
    for (const adding of ((currentPendingEdit() || {}).add || [])) {
      const row = el("button", "filterrow filterpending",
        adding + " (addition pending)");
      row.type = "button";
      row.disabled = true;
      pop.appendChild(row);
    }
  }

  renderRows();
  holder.appendChild(button);
  holder.appendChild(pop);
  return holder;
}

// The controller. `host` is the header slot; nothing is rendered when the index
// is absent (the static-image path) beyond whatever the caller already shows.
//
// `onSelect(key)` is the caller's "load that snapshot" hook; `onRefreshed(result)`
// runs after a successful refresh. Both `fetchIndex`/`postRefresh` are injectable
// for tests, and `schedule` replaces setInterval so the poll is testable.
//
// `mountProjectGate` is the `gate.projects` binding's entry, already resolved by
// the shell (§ 3.4 slice S4) or null. Present, the project commissions are
// available: the dropdown's "New Project…" line opens the create form and the
// filter's add line and trash controls raise membership edits. Null — a student
// install, or any plane with no gate column — and none of that renders, with no
// 404 and no dead control, which is RULING C2 one tier out.
//
// WHAT LEFT WITH SLICE S4 AND IS NOT REPLACED HERE: the "⟳ apply N pending"
// button. It POSTed openxFactory's own fulfilment lane, which RULING DQ-1 keeps
// at openxFactory ("a front end that hardcodes them ships one repository's lanes
// to every install", § 3.3), so RULED Q3 has it leave the bundle entirely rather
// than move to a class. Commissions still RECORD and still badge as pending
// exactly as before — what no longer exists in this bundle is the button that
// ran the fulfilment; openxFactory runs its own lane, and if it wants the button
// back it contributes one through the S3 registry the way S2's intent chips
// return. `onRefreshed` therefore has exactly one caller again: a successful
// refresh.
export function mountRepoSelector(host, opts) {
  const o = opts || {};
  const post = o.post || postRefresh;
  const load = o.loadIndex || fetchIndex;
  let index = o.index || null;
  let active = o.active || null;
  let snapshot = o.snapshot || null;
  const caps = o.caps || {};
  const binding = refreshBinding(caps);

  const wrap = el("span", "repopicker");
  const status = el("span", "repopick-msg");
  const hint = el("button", "repohint", "");
  hint.type = "button";
  hint.hidden = true;
  hint.title = "the publication lane has newer data — click to load it";
  // Operator AT nit (2026-08-02): `title` is not a reliable accessible name,
  // and this badge ships EMPTY until `renderHint` fills it — so an assistive
  // technology meeting it mid-render would find an unnamed button. The
  // aria-label states the action independently of the visible glyph text.
  hint.setAttribute("aria-label", "load the newer published data");
  let button = null;

  function renderHint() {
    const show = newerAvailable(active, snapshot);
    hint.hidden = !show;
    if (show) hint.textContent = "◆ " + hintLabel(active);
  }

  async function runRefresh() {
    if (!button) return;
    const label = button.textContent;
    button.disabled = true;
    button.textContent = "refreshing…";
    status.textContent = "";
    try {
      const result = await post({
        repository: active?.repository, ref: active?.ref,
      });
      status.textContent = "";
      if (typeof o.onRefreshed === "function") o.onRefreshed(result);
    } catch (err) {
      // The previously rendered snapshot stays exactly as it is.
      status.textContent = "refresh failed: " + (err?.message || "error");
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  }

  // Assigned by the filter block below when there IS a roster to re-derive; a
  // no-entries plane leaves it null and the poll simply has no views to refresh.
  let rosterChanged = null;
  if (Array.isArray(index?.entries) && index.entries.length) {
    let roster = buildRoster(index);
    const projects = buildProjects(o.projects);
    const pendingProjects = buildPendingProjects(o.projects);
    const pendingEdits = buildPendingEdits(o.projects);
    // D13: the viewer is always IN a project — the stored scope when the
    // projection still names it, else the first register project.
    let scope = defaultProjectScope(projects, storedProjectScope(o.storage));
    const currentProject = () => projects.find((p) => p.id === scope) || null;

    // The `gate.projects` controller, declared before the first render because
    // the filter's own gate verdict reads it (§ 3.4 slice S4). `available` is
    // knowable up front — the capability the probe reported AND a binding the
    // shell resolved — while `commissionEdit` is only needed at click time, by
    // which point the mount below has filled it in.
    const projectGate = {
      available: gateCapable(caps) && !!o.projects && !!o.mountProjectGate,
      commissionEdit: null,
    };

    // ---- the repo FILTER (D14): one icon, one popover, the current
    // project's members; re-rendered whenever the project changes ----
    let filterWrap = null;
    function renderFilter() {
      const project = currentProject();
      // D19: the visible set and view mode this project renders under —
      // resolved against its CURRENT members, so a departed repository drops.
      const view = projectViewState(project, o.storage, active);
      const next = mountProjectFilter(project, roster, pendingEdits, {
        active, caps, status, projects, fetcher: o.fetcher,
        gate: projectGate.available ? projectGate : null,
        visible: view.visible, viewMode: view.mode,
        onSelect: (key) => o.onSelect?.(key),
        onView: (state) => {
          storeViewState(project?.id, state, o.storage);
          // The view row and the wheels move together: one visible
          // repository serves ITS OWN snapshot (interactive), any other
          // count serves the project's composed aggregate, which app.js
          // narrows to the visible members under the stored mode.
          const aggregate = (projectFilterRows(roster, project)
            .find((r) => r.kind === "all") || {}).option || null;
          const solo = state.visible.length === 1
            ? roster.find((entry) => entry.kind === KIND_REPOSITORY
                && entry.repository === state.visible[0])
            : null;
          const target = solo || aggregate;
          if (target) {
            o.onSelect?.({ repository: target.repository, ref: target.ref });
          } else {
            renderFilter();          // nothing to serve: just restate the set
          }
        },
      });
      if (filterWrap) filterWrap.replaceWith(next);
      else wrap.appendChild(next);
      filterWrap = next;
    }

    // ---- the PROJECT DROPDOWN (D13): "New Project" first, then the
    // register's projects, pending commissions after them ----
    let addPendingOption = null;
    let openCreateForm = null;
    if (projects.length || pendingProjects.length) {
      const picker = el("select", "repopick projectpick");
      picker.id = "projectpick";
      picker.setAttribute("aria-label", "current project");
      const newRow = el("option", "projectnew", "New Project…");
      newRow.value = "__new__";
      // creating is a gate act, AND it needs the column that performs it
      if (!projectGate.available) newRow.disabled = true;
      picker.appendChild(newRow);
      for (const project of projects) {
        const opt = el("option", null, project.name);
        opt.value = project.id;
        if (project.id === scope) opt.selected = true;
        picker.appendChild(opt);
      }
      // INTENT entries (design D-e): recorded, undelivered create-project
      // commissions — visible so the act registered, non-selectable so a
      // pending project can never scope the roster.
      addPendingOption = (name) => {
        const opt = el("option", "projectpending",
          name + " (commissioned — pending fulfilment)");
        opt.value = "";
        opt.disabled = true;
        picker.appendChild(opt);
      };
      for (const pendingProject of pendingProjects) {
        addPendingOption(pendingProject.name);
      }
      picker.addEventListener("change", () => {
        if (picker.value === "__new__") {
          // D13: the first line ACTS — open the create form and restore the
          // previous selection. "New Project" is never a scope.
          picker.value = scope || "";
          if (openCreateForm) openCreateForm();
          return;
        }
        scope = picker.value || scope;
        storeProjectScope(scope, o.storage);
        renderFilter();
        // Switching to a project the active repository is not in serves that
        // project's DEFAULT VIEW (D19): its merged view when it has one — the
        // default visible set is every member — else the first published
        // member, which is what the pre-composition plane always did.
        const project = currentProject();
        if (project && active
            && active.repository !== project.id
            && !(project.repositories || []).includes(active.repository)) {
          const rows = projectFilterRows(roster, project);
          const aggregate = (rows.find((r) => r.kind === "all") || {}).option;
          const first = rows.find((r) => r.kind === "repo" && r.option?.available);
          const target = aggregate || first?.option;
          if (target) {
            o.onSelect?.({ repository: target.repository, ref: target.ref });
          }
        }
      });
      wrap.appendChild(picker);
    }
    renderFilter();
    // THE ROSTER CAN GROW WHILE THE PAGE IS OPEN (2026-08-10): a create opens a
    // branch session, and the serving index advertises it as a new row. The
    // filter is built from the roster, so without this the session the human
    // just created is missing from the one control that can address it — for
    // the page's whole life, since `poll` used to update only the newer-data
    // hint. Re-derived and re-rendered, so it appears on the next poll and on
    // the shell's own nudge after a session opens.
    rosterChanged = () => { roster = buildRoster(index); renderFilter(); };
    if (projectGate.available) {
      // The contributed binding mounts into the slot the selector built for it
      // and hands back the two acts this view triggers. Mounted HERE, in the
      // position the create form has always occupied, so the header's DOM order
      // is unchanged by the split.
      const controller = o.mountProjectGate(wrap, {
        roster, status, fetcher: o.fetcher, addPendingOption,
      });
      openCreateForm = controller.openCreateForm;
      projectGate.commissionEdit = controller.commissionEdit;
    }
  }
  if (refreshCapable(caps)) {
    button = el("button", "repobtn", binding === "regenerate" ? "↻ regenerate" : "↻ refresh");
    button.type = "button";
    button.title = binding === "regenerate"
      ? "re-run the generator against this checkout (derived snapshot only)"
      : "re-fetch the published index and snapshot (read-only)";
    button.addEventListener("click", runRefresh);
    wrap.appendChild(button);
  }
  wrap.appendChild(hint);
  wrap.appendChild(status);
  hint.addEventListener("click", runRefresh);
  renderHint();
  if (host) {
    host.textContent = "";
    host.appendChild(wrap);
  }

  // The background index poll: index only, never a snapshot, never a reload.
  let timer = null;
  const schedule = o.schedule || ((fn, ms) => setInterval(fn, ms));
  async function poll() {
    const fresh = await load();
    if (!fresh) return;
    index = fresh;
    active = buildRoster(index).find((r) => sameKey(r, active)) || active;
    renderHint();
    // …and the filter, so a session that opened since boot becomes addressable
    if (rosterChanged) rosterChanged();
  }
  if (o.poll !== false && refreshCapable(caps)) {
    timer = schedule(poll, o.intervalMs || POLL_INTERVAL_MS);
  }

  return {
    element: wrap,
    binding,
    poll,
    // Idempotent by design: clearing the handle is conditional, forgetting it is
    // NOT (a second stop() must stay a no-op). Braced so that reads the way it
    // runs — the one-line form said "conditional" and meant otherwise (S2681).
    stop() {
      if (timer) { clearInterval(timer); }
      timer = null;
    },
    setSnapshot(next) { snapshot = next; renderHint(); },
    setActive(next) { active = next; renderHint(); },
    refresh: runRefresh,
  };
}

// The stale banner (design D6) and the sparse-station note (D10). Rendered by
// the app shell above the views: a fallback that renders silently is the failure
// this change exists to end, so the banner is part of the contract, not chrome.
export function renderStaleBanner(host, active, sparseText) {
  if (!host) return null;
  host.textContent = "";
  const stale = staleNotice(active);
  if (!stale && !sparseText) {
    host.hidden = true;
    return null;
  }
  host.hidden = false;
  if (stale) host.appendChild(el("div", "stalebanner-line", "⚠ " + stale));
  if (sparseText) host.appendChild(el("div", "stalebanner-line sparse", "· " + sparseText));
  return host;
}

export { freshnessLabel, keyId };
