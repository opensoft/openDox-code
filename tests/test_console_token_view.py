"""The page's half of plan 034 T104: `web/views/notebook.js` takes the
console token from the opened URL's FRAGMENT, keeps it, and strips it
(RULED openxFactory#656 comment `5963851934`).

On a standalone plane `/capabilities` carries no token. The page is opened at
`…/index.html#console_token=<token>` (`opendox.console_access.opened_url`), and
the module takes it the moment it is imported: it keeps it in
`sessionStorage`, or in memory where storage is blocked, and rewrites the
address bar with `history.replaceState` so the token does not stay in it.
`probeCapabilities` then fills it into a payload that carries none, so every
view keeps reading `caps.console_token`, and a host's own published token
always wins. Each case runs in node, against the module itself, with the
browser globals stood in; a fresh module instance per case (`?case=`).

A CREATED FILE, with no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK_JS = ROOT / "src" / "opendox" / "web" / "views" / "notebook.js"
NODE = shutil.which("node")

TOKEN = "Tk_" + "a1B2-c3D4" * 4          # `secrets.token_urlsafe`'s alphabet
SERVED = "Served_" + "z9Y8-x7W6" * 4

_HARNESS = r"""
const TOKEN = %(token)s, SERVED = %(served)s;
const out = {};

function storage({ throwing = false, seed = null } = {}) {
  const map = new Map(seed ? [["opendox.console-token", seed]] : []);
  const api = {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
    dump: () => Object.fromEntries(map),
  };
  return throwing ? null : api;
}

function scope({ hash = "", search = "", store = storage(), throwing = false } = {}) {
  const calls = [];
  const s = {
    location: { hash, search, pathname: "/index.html" },
    history: { state: { kept: 1 }, replaceState: (st, title, url) => { calls.push([st, title, url]); } },
    calls,
    store,
  };
  if (throwing) {
    Object.defineProperty(s, "sessionStorage", { get() { throw new Error("blocked"); } });
  } else {
    s.sessionStorage = store;
  }
  return s;
}

function install(s) {
  for (const name of ["location", "history"]) globalThis[name] = s[name];
  try { delete globalThis.sessionStorage; } catch {}
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    get() { return s.sessionStorage; },
  });
}

const ok = (payload) => async () => ({ ok: true, json: async () => payload });

// 1. THE MODULE ITSELF, opened with the token in the fragment.
let s = scope({ hash: "#console_token=" + TOKEN });
install(s);
let m = await import("./notebook.js?case=fragment");
out.fragment = {
  replaced: s.calls,
  stored: s.store.dump(),
  probed: await m.probeCapabilities(ok({ actions: { session: true } })),
  hostWins: await m.probeCapabilities(ok({ actions: {}, console_token: SERVED })),
  absentRoute: await m.probeCapabilities(async () => ({ ok: false })),
  offline: await m.probeCapabilities(async () => { throw new Error("file://"); }),
  notAnObject: await m.probeCapabilities(ok([1, 2])),
};

// 2. A RELOAD: no fragment, the tab's storage holds the token.
s = scope({ store: storage({ seed: TOKEN }) });
install(s);
m = await import("./notebook.js?case=reload");
out.reload = { replaced: s.calls,
               probed: await m.probeCapabilities(ok({ actions: {} })) };

// 3. THE QUERY STRING IS NEVER READ: a token there is not taken.
s = scope({ search: "?console_token=" + TOKEN });
install(s);
m = await import("./notebook.js?case=query");
out.query = { replaced: s.calls, stored: s.store.dump(),
              probed: await m.probeCapabilities(ok({ actions: {} })) };

// 4. A MALFORMED TOKEN: stripped from the address bar, not kept.
s = scope({ hash: "#console_token=%%3Cscript%%3E" });
install(s);
m = await import("./notebook.js?case=malformed");
out.malformed = { replaced: s.calls, stored: s.store.dump(),
                  probed: await m.probeCapabilities(ok({ actions: {} })) };

// 5. BLOCKED STORAGE: the token is still taken, in memory.
s = scope({ hash: "#console_token=" + TOKEN, throwing: true });
install(s);
m = await import("./notebook.js?case=blocked");
out.blocked = { replaced: s.calls,
                probed: await m.probeCapabilities(ok({ actions: {} })) };

// 6. THE PURE FUNCTIONS, with no page at all.
out.pure = {
  noScope: m.takeDeliveredConsoleToken(undefined),
  noHash: m.takeDeliveredConsoleToken({ location: {} }),
  otherFragment: m.takeDeliveredConsoleToken(scope({ hash: "#section-2" })),
  explicitNull: m.withDeliveredConsoleToken({ actions: {} }, null),
  keys: [m.CONSOLE_TOKEN_FRAGMENT_KEY, m.CONSOLE_TOKEN_STORAGE_KEY],
};

process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    if NODE is None:
        pytest.skip("node not available for the console-token page probe")
    root = tmp_path_factory.mktemp("console-token-view")
    shutil.copy(NOTEBOOK_JS, root / "notebook.js")
    (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    harness = root / "harness.mjs"
    harness.write_text(_HARNESS % {"token": json.dumps(TOKEN),
                                   "served": json.dumps(SERVED)},
                       encoding="utf-8")
    proc = subprocess.run([NODE, str(harness)], capture_output=True, text=True,
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_fragment_token_is_taken_kept_and_stripped(page) -> None:
    case = page["fragment"]
    # stripped: the address bar is rewritten to the path, the state kept
    assert case["replaced"] == [[{"kept": 1}, "", "/index.html"]]
    assert case["stored"] == {"opendox.console-token": TOKEN}
    assert case["probed"] == {"actions": {"session": True}, "console_token": TOKEN}


def test_a_hosts_published_token_wins_and_a_degraded_probe_gets_none(page) -> None:
    case = page["fragment"]
    assert case["hostWins"]["console_token"] == SERVED
    assert case["absentRoute"] == {"actions": {"notebook": False}}
    assert case["offline"] == {"actions": {"notebook": False}}
    assert case["notAnObject"] == [1, 2]


def test_a_reload_keeps_the_token_from_the_tabs_storage(page) -> None:
    assert page["reload"]["replaced"] == []
    assert page["reload"]["probed"]["console_token"] == TOKEN


def test_a_token_in_the_query_string_is_never_read(page) -> None:
    case = page["query"]
    assert case["replaced"] == [] and case["stored"] == {}
    assert "console_token" not in case["probed"]


def test_a_malformed_token_is_stripped_and_not_kept(page) -> None:
    case = page["malformed"]
    assert case["replaced"] == [[{"kept": 1}, "", "/index.html"]]
    assert case["stored"] == {}
    assert "console_token" not in case["probed"]


def test_blocked_storage_still_yields_the_token_in_memory(page) -> None:
    assert page["blocked"]["replaced"] == [[{"kept": 1}, "", "/index.html"]]
    assert page["blocked"]["probed"]["console_token"] == TOKEN


def test_the_pure_readers_take_nothing_from_nothing(page) -> None:
    case = page["pure"]
    assert case["noScope"] is None and case["noHash"] is None
    assert case["otherFragment"] is None
    assert case["explicitNull"] == {"actions": {}}
    # the page reads the key the server writes (`console_access.FRAGMENT_KEY`)
    from opendox import console_access
    assert case["keys"] == [console_access.FRAGMENT_KEY, "opendox.console-token"]
