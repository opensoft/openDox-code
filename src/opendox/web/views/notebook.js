// "Open in NotebookLM" tile action (v2 local-backend seam debut). This is the
// ONLY module besides app.js (the snapshot fetch) and viewer.js (the /source
// pass-through) that issues a network call: it probes GET /capabilities ONCE at
// load and POSTs to /actions/notebook on click. Both routes exist only on a
// loopback LOCAL backend (serve.py); the static SERVED image (nginx) serves
// neither, so probeCapabilities degrades to "notebook: false" and no button is
// ever mounted — the capability-probe degradation story in one place.
//
// DOM-SAFETY: every dynamic value binds through textContent (helpers discipline);
// innerHTML is never assigned here. Errors surface inline via textContent only.

export const CAPABILITIES_ROUTE = "/capabilities";
export const ACTIONS_NOTEBOOK_ROUTE = "/actions/notebook";

// Local textContent-first element builder (this view keeps its own, like the
// other textContent-family views — see helpers.js scope note).
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

// pure — node-testable. True only when the probe EXPLICITLY reported the
// notebook action available; any other shape reads as unavailable.
export function notebookCapable(caps) {
  return caps?.actions?.notebook === true;
}

// ---- the console token, DELIVERED IN THE OPENED URL (plan 034 T104) --------
//
// RULED openxFactory#656 `5963851934` (adversarial review 2's M5): on a
// STANDALONE plane the server no longer publishes the per-serve console token
// on `/capabilities`, where any loopback caller, another OS user included,
// could read it. `opendox generate-and-open` opens this page through a private
// 0600 file instead, which forwards here with the token in the URL FRAGMENT
// (`#console_token=…`). A fragment never reaches a server, so it is in no
// request line, no server log and no `Referer`.
//
// This module takes it the moment it is imported (before the shell's first
// fetch), keeps it in `sessionStorage` (this tab only, so a reload keeps it;
// memory where storage is blocked), and STRIPS the fragment from the address
// bar with `history.replaceState`. `probeCapabilities` then fills it into the
// payload where the server published none, so every view keeps reading
// `caps.console_token` exactly as before. A HOST's plane still publishes its
// own token on `/capabilities`, and that one always wins.
export const CONSOLE_TOKEN_FRAGMENT_KEY = "console_token";
export const CONSOLE_TOKEN_STORAGE_KEY = "opendox.console-token";
// The `/capabilities` field every view reads the token from (the server's
// `CONSOLE_TOKEN_FIELD`; `staging-workbench-model.js` spells it too, and this
// leaf module imports nothing).
const CAPS_CONSOLE_TOKEN_FIELD = "console_token";
// `secrets.token_urlsafe`'s alphabet: a value outside it is not a token.
const CONSOLE_TOKEN_SHAPE = /^[A-Za-z0-9_-]{16,512}$/;

function consoleStore(scope) {
  try {
    return scope && scope.sessionStorage ? scope.sessionStorage : null;
  } catch {
    return null;                        // blocked storage throws on access
  }
}

// pure over `scope` (`window` in the page) — node-testable. Returns the
// delivered token or null. A fragment that names the key is stripped from the
// address bar whatever it holds, so a malformed token does not linger either.
export function takeDeliveredConsoleToken(scope) {
  const loc = scope && scope.location;
  if (!loc || typeof loc.hash !== "string") return null;
  let fromFragment = null;
  if (loc.hash.length > 1) {
    let raw = null;
    try {
      raw = new URLSearchParams(loc.hash.slice(1)).get(CONSOLE_TOKEN_FRAGMENT_KEY);
    } catch {
      raw = null;
    }
    if (raw !== null) {
      try {
        const history = scope.history;
        if (history && typeof history.replaceState === "function") {
          history.replaceState(history.state, "",
            String(loc.pathname || "") + String(loc.search || ""));
        }
      } catch {
        // an address bar that cannot be rewritten still yields the token
      }
      if (CONSOLE_TOKEN_SHAPE.test(raw)) fromFragment = raw;
    }
  }
  const store = consoleStore(scope);
  if (fromFragment) {
    try {
      if (store) store.setItem(CONSOLE_TOKEN_STORAGE_KEY, fromFragment);
    } catch {
      // memory only: this load still has it
    }
    return fromFragment;
  }
  let kept = null;
  try {
    kept = store ? store.getItem(CONSOLE_TOKEN_STORAGE_KEY) : null;
  } catch {
    kept = null;
  }
  return typeof kept === "string" && CONSOLE_TOKEN_SHAPE.test(kept) ? kept : null;
}

// Taken ONCE, at import. Outside a page (node) there is no `location`, and
// this is null.
const DELIVERED_CONSOLE_TOKEN = takeDeliveredConsoleToken(globalThis);

// pure — node-testable. The payload, with the delivered token filled in where
// the server published none. Mutated in place, so the object the shell holds
// is the object the views read.
export function withDeliveredConsoleToken(payload, token = DELIVERED_CONSOLE_TOKEN) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const served = payload[CAPS_CONSOLE_TOKEN_FIELD];
  if (typeof served === "string" && served) return payload;
  if (typeof token === "string" && token) payload[CAPS_CONSOLE_TOKEN_FIELD] = token;
  return payload;
}

// Probe the local backend ONCE. Any non-OK response (the static image 404s this
// route) or a network failure (file://) degrades to "not available" — never
// throws, never blocks the dashboard. `injectedFetch` is for tests; so is
// `deliveredToken`, which defaults to the one this page was opened with.
export async function probeCapabilities(injectedFetch, deliveredToken = DELIVERED_CONSOLE_TOKEN) {
  try {
    const response = injectedFetch
      ? await injectedFetch(CAPABILITIES_ROUTE, { cache: "no-store" })
      : await fetch(CAPABILITIES_ROUTE, { cache: "no-store" });
    if (!response?.ok) return { actions: { notebook: false } };
    return withDeliveredConsoleToken(await response.json(), deliveredToken);
  } catch {
    return { actions: { notebook: false } };
  }
}

// POST one tile action; resolves to the backend's {url, notebook_alias,
// sources, created}, or throws an Error carrying the backend's fixed catalog
// message (preferring the human `message` over the stable `error` code).
export async function postNotebookAction(body, injectedFetch) {
  const opts = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
  const response = injectedFetch
    ? await injectedFetch(ACTIONS_NOTEBOOK_ROUTE, opts)
    : await fetch(ACTIONS_NOTEBOOK_ROUTE, opts);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data?.message || data?.error || ("HTTP " + response.status));
  return data;
}

// One click cycle: disable + spinner text -> POST -> open the url in a new tab
// -> restore; error -> inline message (textContent). Extracted so `button`
// stays a small factory.
async function runClick(btn, msg, kind, id, post, open) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = "opening NotebookLM…";
  msg.textContent = "";
  try {
    const result = await post({ tile_kind: kind, tile_id: id });
    if (result?.url) open(result.url);
    else msg.textContent = "no notebook url returned";
  } catch (err) {
    msg.textContent = "could not open NotebookLM: " + (err?.message || "error");
  } finally {
    btn.disabled = false;
    btn.textContent = label;
  }
}

// The action controller. `button(kind, id)` returns a mount-ready element when
// enabled, else null — so views append `notebook.button(...)` guarded by a
// truthiness check and nothing renders when the capability is absent. `post`
// and `open` are injectable for tests.
export function createNotebookAction(opts) {
  const options = opts || {};
  const enabled = Boolean(options.enabled);
  const post = options.post || postNotebookAction;
  const open = options.open
    || ((url) => window.open(url, "_blank", "noopener"));

  function button(kind, id) {
    if (!enabled) return null;
    const wrap = el("span", "nb-action");
    const btn = el("button", "nbbtn", "◇ open in NotebookLM");
    btn.type = "button";
    const msg = el("span", "nb-msg");
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();  // never trip the funnel card's click-to-pin gesture
      runClick(btn, msg, kind, id, post, open);
    });
    wrap.appendChild(btn);
    wrap.appendChild(msg);
    return wrap;
  }

  return { enabled, button };
}
