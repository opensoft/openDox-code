// openDox's OWN branch actions in the browser (plan 038 T015; #1144 12.4a):
// the SUBMIT control. It posts one branch to `POST /actions/session/submit`,
// the route openDox's default profile contributes
// (`opendox/serve_branch_actions.py`), and shows where the work went.
//
// KEYED ON `actions.submit`, NEVER ON `session` (OQ-12-14, refined by ADV-14).
// The key is present only where openDox's own profile contributed the route,
// and true only where that route answers for a local human, so the control is
// never offered where no submit route answers: a host's plane carries no key,
// and a hosted plane carries it false. The console token is required too,
// because the route refuses any request without it (12.4a's third clause).
//
// It lives HERE and never in the `doxbench-*.js` files (OQ-12-14). Import-free
// by design, like `edit.js`: it addresses no route another column declares and
// names no governance word.

export const ACTIONS_SESSION_SUBMIT_ROUTE = "/actions/session/submit";
const CONSOLE_TOKEN_HEADER = "X-XF-Console-Token";
// The default branch the act refuses (R2Q5 (a)). The control never offers it,
// and the server refuses it by name whatever the page sends.
export const DEFAULT_BRANCH = "main";

// Whether this plane offers the submit act at all.
export function submitCapable(caps) {
  return Boolean(caps?.actions?.submit === true
    && typeof caps?.console_token === "string"
    && caps.console_token.length > 0);
}

// The branch the control proposes: the one the page is looking at, unless it
// is the default branch. The human may type another.
export function proposedBranch(ref) {
  return typeof ref === "string" && ref && ref !== DEFAULT_BRANCH ? ref : "";
}

// POST one submit; resolves to `{ ok, status, payload }`, never throws for a
// refusal, so the control can state the server's own sentence.
export async function postSubmit(branch, caps, fetcher) {
  const options = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [CONSOLE_TOKEN_HEADER]: caps.console_token,
    },
    body: JSON.stringify({ branch }),
  };
  const doFetch = fetcher || fetch;
  const response = await doFetch(ACTIONS_SESSION_SUBMIT_ROUTE, options);
  const payload = await response.json().catch(() => null);
  return { ok: response.ok, status: response.status, payload };
}

// The sentence the control shows for an answer: where the work went (12.1a),
// or the refusal the server named.
export function describeAnswer(answer) {
  const p = answer?.payload;
  if (answer?.ok && p && typeof p.remote === "string" && typeof p.ref === "string") {
    return "submitted " + p.branch + " to " + p.remote + " (" + p.url + ") as "
      + p.ref + " at " + String(p.commit || "").slice(0, 12);
  }
  const why = (p && (p.message || p.error)) || ("HTTP " + (answer?.status ?? "?"));
  return "not submitted: " + why;
}

// Mount the control into `host`, or leave `host` empty where this plane offers
// no submit act. A COMPOSED render offers none either: it is read-only, and
// every acting control is withheld from it (D10). Returns a controller whose
// `submit()` runs one submission and resolves to the sentence it showed (null
// when nothing is offered).
export function mountBranchActions(host, { caps, branch, composed, fetcher } = {}) {
  if (!host) return { enabled: false, submit: async () => null };
  host.textContent = "";
  if (composed || !submitCapable(caps)) {
    return { enabled: false, submit: async () => null };
  }
  const doc = host.ownerDocument;
  const input = doc.createElement("input");
  input.type = "text";
  input.className = "search";
  input.value = proposedBranch(branch);
  input.placeholder = "branch to submit";
  input.setAttribute("aria-label", "branch to submit");
  const button = doc.createElement("button");
  button.type = "button";
  button.className = "cbtn";
  button.textContent = "submit";
  const message = doc.createElement("span");
  message.setAttribute("role", "status");
  host.append(input, button, message);

  // A refusal is styled as one; a success is plain.
  function show(ok, text) {
    message.className = ok ? "" : "repopick-msg";
    message.textContent = text;
    return text;
  }

  async function submit() {
    const name = String(input.value || "").trim();
    if (!name || name === DEFAULT_BRANCH) {
      return show(false, "name a branch other than " + DEFAULT_BRANCH);
    }
    button.disabled = true;
    show(true, "");
    try {
      const answer = await postSubmit(name, caps, fetcher);
      show(answer.ok, describeAnswer(answer));
    } catch (err) {
      show(false, "not submitted: " + (err?.message || "error"));
    } finally {
      button.disabled = false;
    }
    return message.textContent;
  }
  button.addEventListener("click", () => { submit(); });
  return { enabled: true, submit };
}
