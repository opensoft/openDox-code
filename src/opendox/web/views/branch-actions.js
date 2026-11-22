// openDox's OWN branch actions in the browser (plan 038 T015; #1144 12.4a):
// the SUBMIT control. It posts one branch to `POST /actions/session/submit`,
// the route openDox's default profile contributes
// (`opendox/serve_branch_actions.py`), and shows where the work went.
//
// And the LAND CONFIRM CONTROL (plan 038 T016; #1144 12.6a; OQ-12-13), the
// view's half of the second confirmation issuer: it fetches a nonce for one
// branch from `POST /actions/session/land-nonce`, SHOWS the branch, the head
// that nonce is bound to and the operation the server states it will perform
// (a merge commit onto main, or a submission to the host's instrument), and
// posts it ONCE to `POST /actions/session/land`, which answers what landed.
// It is keyed on
// `actions.land`, present only under openDox's own profile and true only
// where `land` can act. Its own mount (`mountLandConfirm`), beside the submit
// control's and never inside it.
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

// Whether ANOTHER repository than the served one is on screen. The route takes
// NO repository from the request (12.4a): it pushes a branch of the checkout
// this serve was started on, which `/capabilities` declares as `repository`
// (the same authority a session verb refuses a foreign one against). A plane
// that reads several repositories writes into that one alone, so with another
// repository active the control would offer a branch name of that repository
// and the push would go out from the served one: then the control is
// withheld. An active key the plane cannot match, because it declares no
// repository, is withheld too.
//
// NO active key is not another repository. A standalone plane, the one plane
// that carries `actions.submit`, has no snapshot index (its
// `/snapshot-index.json` answers 404), so nothing is ever active there, and
// the only checkout on screen is the served one.
export function anotherRepositoryIsActive(caps, repository) {
  return typeof repository === "string" && repository.length > 0
    && repository !== caps?.repository;
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
// every acting control is withheld from it (D10). Nor does a view of another
// repository than the served one (`anotherRepositoryIsActive`). Returns a
// controller whose `submit()` runs one submission and resolves to the
// sentence it showed (null when nothing is offered).
export function mountBranchActions(
    host, { caps, branch, repository, composed, fetcher } = {}) {
  if (!host) return { enabled: false, submit: async () => null };
  host.textContent = "";
  if (composed || !submitCapable(caps)
      || anotherRepositoryIsActive(caps, repository)) {
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
  // `submit()` settles every outcome itself (its own try/catch), so the click
  // handler has nothing to await and marks the promise as handled.
  button.addEventListener("click", () => { void submit(); });
  return { enabled: true, submit };
}

// ---------------------------------------------------------------------------
// The land confirm control (plan 038 T016; #1144 12.6a; OQ-12-13)
// ---------------------------------------------------------------------------

export const ACTIONS_SESSION_LAND_NONCE_ROUTE = "/actions/session/land-nonce";
export const ACTIONS_SESSION_LAND_ROUTE = "/actions/session/land";

// Whether this plane offers the land act at all: `actions.land` exactly true
// (present only under openDox's own profile, true only where `land` can act),
// and a console token to send, since both routes refuse a request without it.
export function landCapable(caps) {
  return Boolean(caps?.actions?.land === true
    && typeof caps?.console_token === "string"
    && caps.console_token.length > 0);
}

async function postLanding(route, body, caps, fetcher) {
  const options = {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [CONSOLE_TOKEN_HEADER]: caps.console_token,
    },
    body: JSON.stringify(body),
  };
  const doFetch = fetcher || fetch;
  const response = await doFetch(route, options);
  const payload = await response.json().catch(() => null);
  return { ok: response.ok, status: response.status, payload };
}

// The question for each operation a landing performs, as the land-nonce route
// states it from the reading that decides whether `land` can act (holder
// ruling item 10, #656 `6103915259`): a merge commit onto main where a lander
// is bound, or a submission to the host's instrument where the repository is
// governed. The control asks exactly the one the server will perform.
const OPERATION_QUESTIONS = {
  merge: (what) => "land " + what + " onto " + DEFAULT_BRANCH
    + " with a merge commit?",
  submit: (what) => "submit " + what + " to the host's instrument? nothing "
    + "merges here: the merge stays its governance's act",
};
function statedOperation(operation) {
  return typeof operation === "string"
    && Object.prototype.hasOwnProperty.call(OPERATION_QUESTIONS, operation);
}

// The nonce answer, accepted only when it is bound to the branch asked for,
// names a full head and states an operation this control can ask about:
// `{ nonce, branch, head, operation }`, else null.
export function issuedNonce(answer, branch) {
  const p = answer?.payload;
  if (!answer?.ok || !p || p.branch !== branch) return null;
  if (typeof p.nonce !== "string" || !p.nonce) return null;
  if (typeof p.head !== "string" || !/^[0-9a-f]{40}([0-9a-f]{24})?$/.test(p.head)) {
    return null;
  }
  if (!statedOperation(p.operation)) return null;
  return { nonce: p.nonce, branch: p.branch, head: p.head,
           operation: p.operation };
}

// A branch name as the `land` prompt at the terminal shows it
// (`session_git.shown`): as it is, or quoted with each character a display
// acts on escaped (a control, a format character such as a bidi override, a
// separator other than the space), so the name the human confirms cannot be
// reordered on screen (Copilot at `1bba2b1c` on openDox-code#100).
const ACTED_ON = /[\p{C}\p{Z}]/u;
function escapedChar(ch) {
  if (ch === "\\") return "\\\\";
  if (ch === "'") return "\\'";
  if (ch === " " || !ACTED_ON.test(ch)) return ch;
  const cp = ch.codePointAt(0);
  const hex = (width) => cp.toString(16).padStart(width, "0");
  if (cp < 0x100) return "\\x" + hex(2);
  return cp < 0x10000 ? "\\u" + hex(4) : "\\U" + hex(8);
}
export function shownName(text) {
  const name = String(text ?? "");
  if (![...name].some((ch) => ch !== " " && ACTED_ON.test(ch))) return name;
  return "'" + [...name].map(escapedChar).join("") + "'";
}

// The question the control asks: the operation the server stated, for the
// branch and the head the nonce is bound to. An operation it cannot name is
// never guessed at.
export function confirmQuestion(issued) {
  if (!statedOperation(issued?.operation)) {
    throw new Error("the server stated no operation this control can ask about");
  }
  return OPERATION_QUESTIONS[issued.operation](
    shownName(issued.branch) + " at " + issued.head);
}

// The sentence for a landing's answer: what landed and the command that undoes
// it (`Landed`), where a governed landing went (the instrument's report), or
// the refusal the server named. The two success shapes are told apart by their
// fields (`merge_commit` is the landing's alone).
export function describeLanding(answer) {
  const p = answer?.payload;
  if (answer?.ok && p && typeof p.merge_commit === "string") {
    return "landed " + shownName(p.branch) + " as " + p.merge_commit.slice(0, 12)
      + "; nothing pushed; undo with git revert -m 1 " + p.merge_commit;
  }
  if (answer?.ok && p && typeof p.remote === "string" && typeof p.ref === "string") {
    return "submitted " + shownName(p.branch) + " to " + p.remote + " (" + p.url
      + ") as " + shownName(p.ref) + "; the merge stays its governance's act";
  }
  const why = (p && (p.message || p.error)) || ("HTTP " + (answer?.status ?? "?"));
  return "not landed: " + why;
}

// Mount the land confirm control into `host`, or leave `host` empty where this
// plane offers no land act, where the render is composed (D10), or where
// ANOTHER repository than the served one is on screen (the routes land a
// branch of the served checkout alone). Returns a controller: `ask()` fetches
// a nonce and shows what it is bound to; `confirm()` posts that nonce, once.
// Each resolves to the sentence it showed (null when nothing is offered).
export function mountLandConfirm(
    host, { caps, branch, repository, composed, fetcher } = {}) {
  const none = { enabled: false, ask: async () => null, confirm: async () => null };
  if (!host) return none;
  host.textContent = "";
  if (composed || !landCapable(caps)
      || anotherRepositoryIsActive(caps, repository)) {
    return none;
  }
  const doc = host.ownerDocument;
  const input = doc.createElement("input");
  input.type = "text";
  input.className = "search";
  input.value = proposedBranch(branch);
  input.placeholder = "branch to land";
  input.setAttribute("aria-label", "branch to land");
  const askButton = doc.createElement("button");
  askButton.type = "button";
  askButton.className = "cbtn";
  askButton.textContent = "land";
  const confirmButton = doc.createElement("button");
  confirmButton.type = "button";
  confirmButton.className = "cbtn";
  confirmButton.textContent = "confirm";
  confirmButton.disabled = true;
  const message = doc.createElement("span");
  message.setAttribute("role", "status");
  host.append(input, askButton, confirmButton, message);

  // The nonce the human is looking at, or null. It is let go BEFORE it is
  // posted, so the control can never post one nonce twice.
  let pending = null;

  function show(ok, text) {
    message.className = ok ? "" : "repopick-msg";
    message.textContent = text;
    return text;
  }

  async function ask() {
    pending = null;
    confirmButton.disabled = true;
    const name = String(input.value || "").trim();
    if (!name || name === DEFAULT_BRANCH) {
      return show(false, "name a branch other than " + DEFAULT_BRANCH);
    }
    askButton.disabled = true;
    show(true, "");
    try {
      const answer = await postLanding(ACTIONS_SESSION_LAND_NONCE_ROUTE,
                                       { branch: name }, caps, fetcher);
      const issued = issuedNonce(answer, name);
      if (!issued) return show(false, describeLanding(answer));
      pending = issued;
      confirmButton.disabled = false;
      return show(true, confirmQuestion(issued));
    } catch (err) {
      return show(false, "not landed: " + (err?.message || "error"));
    } finally {
      askButton.disabled = false;
    }
  }

  async function confirm() {
    const issued = pending;
    pending = null;
    confirmButton.disabled = true;
    if (!issued) return show(false, "ask to land a branch first");
    try {
      const answer = await postLanding(
        ACTIONS_SESSION_LAND_ROUTE,
        { branch: issued.branch, nonce: issued.nonce }, caps, fetcher);
      return show(answer.ok, describeLanding(answer));
    } catch (err) {
      return show(false, "not landed: " + (err?.message || "error"));
    }
  }
  // Each settles every outcome itself, so a click has nothing to await.
  askButton.addEventListener("click", () => { void ask(); });
  confirmButton.addEventListener("click", () => { void confirm(); });
  return { enabled: true, ask, confirm };
}
