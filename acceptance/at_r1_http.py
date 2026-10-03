#!/usr/bin/env python3
"""AT-R1, the HTTP half: release 1's acceptance, run in CI (plan 034 T095).

The brief AT-R1 makes checkable (openxFactory
`specs/034-opendox-standalone-operation/spec.md` § "AT-R1"): *"on a clean
machine with only openDox installed, a plain git repo opens, and the wheel,
radar lens and chat panes work, with chat's 'no model configured' state."*
This harness is that test's HTTP half: steps 1-4, and the route answers behind
steps 5-8. The browser half is a Playwright run on the host (T096), whose
verdict `tests/smoke_signals.py` computes. It realizes FR-011's HTTP half.

WHAT IT IS NOT. It is not a pytest module, and it sits outside `tests/` and
`tests_runtime/`, so `pyproject.toml`'s `testpaths` never collects it and
#1144's F9.1 is unchanged. It installs the product and drives it from
outside, as a user would, so it is no member of this leg's suite, and FR-006's
"no exclusion" still holds. It runs in its own `acceptance` job in
`.github/workflows/validate.yml`, which has NO database service, because the
harness asserts a clean machine and the `validate` job's PostgreSQL service
would break that precondition. Making `acceptance` a required check is a
ruleset change for the repository's owner.

WHAT IT DOES, in order. Each step is an assertion with an id; the run stops at
the FIRST that fails, prints `AT-R1 HTTP half: FAIL [<id>]: <why>` and exits 1
(`--keep-going` reports every failed assertion instead, and still exits 1).
A harness that breaks before a verdict exits 2, never 0.

 1. INSTALLS openDox ALONE into a fresh venv, as `opendox[local]` (R1Q16
    (iii)), from a copy of this checkout's tracked files. The documented
    install is `pip install "opendox[local]"`; no release of `opendox` is
    published to a package index, so this installs the same distribution
    with the same extra from the checkout, `pip install "<checkout>[local]"`,
    which is the substitution the openDox root's README states for the first
    line. With `constraints-cpython312-linux.txt` beside it and a CPython
    3.12 on Linux, the install reads that lock, as every install of this
    package does (`tests_runtime/test_deploy_shape.py`); the lock pins
    versions and adds no package.
 2. ASSERTS THE CLEAN MACHINE, in a fresh `OPENDOX_STATE_DIR` created empty
    for this run (and short, so the bundled server's socket path fits): none
    of the four siblings (`openxdox`, `ideation_dashboard`, `doc_health`,
    `corpus_adapter_openxfactory`) is importable; `omp` (the harness the
    product names, `doxbench_bridge.HARNESS_COMMAND`) is not on the PATH; no
    identity broker (`openprofiler-broker`, the one that exists) is on the
    PATH and no issuer is set; no database answers on PostgreSQL's default
    port or on a distribution's socket, and no DSN is set; and neither
    repository holds a model binding (`doxbench_binding.bindings_path`).
 3. COPIES BOTH PLAIN REPOSITORIES into fresh `git init`s (AT-R1 step 3):
    (a) 5.0's `tests/fixtures/plain-documents`, and (b) three ordinary
    Markdown notes with no front matter at all, quickstart.md § 2's. Each gets
    a git identity (`git config user.name` and `user.email`), which the served
    actor is read from.
 4. RUNS THE DOCUMENTED COMMAND on loopback, once per repository. The command
    is the one T007 batch H's 10.3 addendum names and the openDox root's
    README documents, `opendox generate-and-open --local …`. The harness fills
    the `…` with the verb's own arguments, as quickstart.md § 3 does, and
    checks its argv against that line before it runs it.
 5. FETCHES `/` (it must be HTML), `/snapshot.json` (non-empty, and neutral
    per F5.3: none of openxFactory's declared governance words in any string
    value; and it fills the grouping station, so the chat pane can open, R1Q13
    (a) with (c)) and `/capabilities` (`install.mode == "local"`, and NO
    `console_token`: a standalone plane hands its token to no loopback
    caller, T104).
 6. READS THE CONSOLE TOKEN THE WAY THE USER'S BROWSER IS HANDED IT (plan 034
    T104; RULED openxFactory#656 `5963851934`). The start prints the PATH of
    a private opener file, `<OPENDOX_STATE_DIR>/console/<port>.html`, and
    never the token. The file must be this user's regular file, mode 0600,
    with one link, in a directory no one else can enter, and outside the
    served repository. Its meta-refresh forwards to this plane on loopback
    with `#console_token=<token>` in the URL's FRAGMENT, and never in the
    query. Its JSON record (`#opendox-console`, kind
    `opendox-console-access` v1) must describe that same forward: its port,
    its token, its `opened_url` and its `page_url`. The harness reads that
    file itself, with the standard library, as a browser would, and imports
    nothing from the product.
 7. FETCHES THE MODEL CATALOG, presenting that token in
    `X-XF-Console-Token`. It must answer the envelope the chat rail adopts
    (`schema_version` 1, `kind` `workbench-model-catalog`, `models[]`), with
    no available entry (16.4). Asked WITHOUT the token, it must refuse, so
    the token the opener carries is the one that opens it.
 8. FETCHES EVERY ROUTE THE PANES CAN REQUEST, and none may answer 5xx or
    drop the connection. The list is DERIVED from the served bundle, not kept
    here: see `derive_bundle` below.
 9. STOPS THE SERVER (SIGTERM to the entry point alone, as `kill` would), and
    asserts that no bundled PostgreSQL process is left running (R1Q16 (iv))
    and that the opener file went with the server.

HOW THE ROUTE LIST IS DERIVED (`derive_bundle`). From the RUNNING server, not
from the source tree: `/` is fetched, its `<script type="module">` and
stylesheet links are followed, and every module's static `import`/`export …
from` specifiers are followed in turn, with each literal dynamic `import("…")`
and each view-binding module `/capabilities` declares. That is the module
graph a browser loads. Every module is fetched from the server under test:
a static import must answer 200, since a failed one is a module-load
`pageerror`, which AT-R1 step 8 forbids and no declaration can excuse; a
dynamic import may be refused (10.2a's `intent-feed.js` is not owed, and its
importer degrades), but never with a 5xx. A module the server DOES serve
(200) must be served as JavaScript, and a linked stylesheet as `text/css`,
parameters such as `charset` aside: a browser refuses a module script of any
other type, and a standards-mode page applies no stylesheet of any other type
(Copilot review of openDox-code#75 at f29b4ddd). Then, in every module of
that graph, with comments stripped, every string literal that is a
same-origin path (a leading `/` or `./` and a letter, not a module or
stylesheet) is a route the bundle can request. A static read cannot tell
which of them fire on load and which on a click, so ALL of them are
requested, a superset of the three panes' load-time reads. The action
routes (`/actions/…`) are requested with a GET too, which never executes
them (a GET there finds no handler, and their POST is a user's act, not a
load). Two kinds take values the panes fill from the snapshot, and the
harness fills them the same way:
 * a route ending in `/` (`/source/`) is a prefix the wheel, the viewer and
   the workbench's source loader complete with a document path, so it is also
   requested once per document the snapshot lists, plain and keyed by the
   workbench's `(repository, ref)` key;
 * the thread read (`/workbench/thread`) is also requested with the query the
   chat rail sends when it opens on a document (`views/staging-workbench.js`,
   `loadThread`): `repository` and `ref` from the workbench's key, which with
   no snapshot index is the snapshot's repository at `main` (`app.js`,
   `sourceKeyFor`), `tile_kind` `cluster` (a grouping tile's kind,
   `views/wheel-model.js`) and `tile_id` the snapshot's first grouping tile,
   whose first member is the `document`.
Every request carries the console token the opener delivered (step 6), as
the doxBench transports do, so a guarded read answers from its handler
rather than from the console check.

RUNNING IT. From an openDox-code checkout, `python3 acceptance/at_r1_http.py`
installs and drives THAT checkout (the one this file is in); to measure
another tree, copy this file into it. It takes no path or port: its scratch
space and its `OPENDOX_STATE_DIR` are fresh temporary directories, so
`TMPDIR` chooses where they go. Choose a short one that only you can write:
the bundled server refuses a state directory below a directory any user can
write without the sticky bit, and its socket path may not pass 107 bytes.
It needs Linux (it reads `/proc`), `git`, and network access to the package
index. The standard library only: it runs before, and outside, the
environment it builds.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import html.parser
import http.client
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# What the harness takes from the record, verbatim, so a reader can check it.
# ---------------------------------------------------------------------------

#: The install and the one start, as T007 batch H's 10.3 addendum names them
#: (openxFactory `openspec/changes/add-neutral-product-standalone-operability/
#: tasks.md`, 10.3, "AMENDED — T007 Batch H (`5850003126`; Ruled R1Q15 (b),
#: R1Q16 (iii))") and as the openDox root's README documents them (T076). The
#: `…` is U+2026, and it stands for the verb's own arguments.
DOCUMENTED_INSTALL = 'pip install "opendox[local]"'
DOCUMENTED_START = "opendox generate-and-open --local …"

#: AT-R1 step 1's four siblings: none may be importable.
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: The harness `omp`, by the name quickstart.md § 1 checks; the product's own
#: `doxbench_bridge.HARNESS_COMMAND` is checked beside it.
HARNESS_COMMAND = "omp"

#: The one identity broker that exists (`design.md` § D14, quickstart.md § 1).
BROKER_COMMANDS = ("openprofiler-broker",)

#: Where a binding lives when the product cannot be asked
#: (`doxbench_binding.DEFAULT_BINDINGS_RELPATH`, quickstart.md § 2).
BINDINGS_RELPATH_FALLBACK = "ideation/dashboard/model-provider-bindings.yaml"

#: F5.3's declared vocabulary, verbatim from #1144's falsifier under 5.5: a
#: neutral snapshot carries none of these in any string VALUE.
F53_WORDS = ["brainstorm", "staged", "draft", "ratified", "standard",
             "superseded", "retired", "record", "openspec", "proposal.md",
             "tasks.md", "design.md", "added requirements",
             "modified requirements"]
F53_PATTERN = re.compile(r"\b(" + "|".join(re.escape(w) for w in F53_WORDS)
                         + r")\b")

#: The console-presence header the doxBench transports carry (`app.js`).
CONSOLE_TOKEN_HEADER = "X-XF-Console-Token"

#: THE CONSOLE TOKEN'S DELIVERY on a standalone plane (plan 034 T104; RULED
#: openxFactory#656 `5963851934`, adversarial review 2's M5). `/capabilities`
#: carries no `console_token`. The start prints the opener's location on a
#: `console <file URL>` line, and the opener is
#: `<OPENDOX_STATE_DIR>/console/<port>.html`, mode 0600. Its meta-refresh
#: carries the token as `#console_token=<token>`, in the fragment and never in
#: the query, because a fragment never reaches a request line, a server log
#: or a `Referer`.
CONSOLE_TOKEN_FIELD = "console_token"
CONSOLE_DIRNAME = "console"
CONSOLE_FRAGMENT_KEY = "console_token"
CONSOLE_LINE = re.compile(r"^[ \t]*console (?P<where>(?:file:|/)\S*)", re.M)
#: The opener's machine-readable record, "for a harness or a script"
#: (`opendox.console_access`, T104): JSON in
#: `<script type="application/json" id="opendox-console">`. The harness parses
#: it itself, with the standard library, and imports nothing from the product.
CONSOLE_RECORD_ID = "opendox-console"
CONSOLE_RECORD_KIND = "opendox-console-access"
CONSOLE_RECORD_SCHEMA_VERSION = 1
OPENER_MODE = 0o600
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

#: The model-catalog route (`app.js` `CATALOG_ROUTE`), which the derived list
#: must also name, so this constant cannot drift from the bundle unseen.
CATALOG_ROUTE = "/workbench/model-catalog"

#: The only catalog envelope the chat rail ADOPTS (`views/doxbench-chat-model.js`,
#: `adoptCatalog`: `schema_version === 1`, `kind === CATALOG_WIRE_KIND`, and an
#: array of `models`); it reads any other as unreadable. The served bundle must
#: name the kind too, so this constant cannot drift from the bundle unseen.
CATALOG_KIND = "workbench-model-catalog"
CATALOG_SCHEMA_VERSION = 1

#: The thread read the chat rail makes on open, and the kind of a grouping
#: tile (`views/wheel-model.js`: "clusters -> \"cluster\"").
THREAD_ROUTE = "/workbench/thread"
GROUPING_TILE_KIND = "cluster"

#: Repository (b): ordinary Markdown with NO front matter at all, quickstart.md
#: § 2's three notes, byte for byte.
PLAIN_NOTES = {
    "roadmap.md": "# Roadmap\n\nThe roadmap links to the [budget](budget.md) "
                  "and the [notes](notes.md).\n",
    "budget.md": "# Budget\n\nBudget figures for the roadmap.\n",
    "notes.md": "# Meeting notes\n\nWe discussed the roadmap and the budget.\n",
}

#: Settings a child must not inherit. A database or an issuer the user set
#: would stand in for the bundle or for local identity; a GIT_* variable
#: would point git at another repository; an XF_* variable (the suite's
#: XF_GATE_PRINCIPALS roster, for one) changes who the served actor is; a
#: PYTHONPATH could make a sibling importable.
STRIPPED_PREFIXES = ("GIT_", "XF_", "OPENDOX_", "PG")
STRIPPED_NAMES = ("DATABASE_URL", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
                  "PYTHONUSERBASE", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__")
#: The names a user-provided database or broker would arrive under, asserted
#: absent from every child's environment (quickstart.md § 1's `unset` list).
DATABASE_SETTINGS = ("OPENDOX_DATABASE_URL", "OPENDOX_MIGRATION_DATABASE_URL",
                     "DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE",
                     "PGUSER", "PGPASSWORD", "PGSERVICE")
IDENTITY_SETTINGS = ("OPENDOX_OIDC_ISSUER", "OPENDOX_OIDC_AUDIENCE",
                     "OPENDOX_INSTALL_MODE")
#: Where a distribution's PostgreSQL listens by default (Debian and Ubuntu,
#: the runner's own family). Probed even where `/proc/net/unix` cannot be
#: read; every other PostgreSQL socket is found there (`postgres_sockets`).
DISTRIBUTION_SOCKETS = ("/var/run/postgresql/.s.PGSQL.5432",
                        "/run/postgresql/.s.PGSQL.5432")

#: The bundled server's socket is `<OPENDOX_STATE_DIR>/postgres/run/.s.PGSQL.5432`
#: (`runtime/config.py`'s `BUNDLE_SOCKET_DIR` and `BUNDLE_PORT`), and Linux
#: takes a socket path of at most 107 bytes (`UNIX_SOCKET_PATH_MAX`). The
#: product refuses a longer one by name; the harness refuses to start a run
#: whose state directory could not fit, before anything is installed.
SOCKET_SUFFIX = "/postgres/run/.s.PGSQL.5432"
SOCKET_PATH_MAX = 107

READY_TIMEOUT_SECONDS = 120.0
STOP_TIMEOUT_SECONDS = 90.0
REQUEST_TIMEOUT_SECONDS = 30.0
INSTALL_TIMEOUT_SECONDS = 900.0


# ---------------------------------------------------------------------------
# The verdict.
# ---------------------------------------------------------------------------

class HarnessError(Exception):
    """The harness itself could not proceed: not a verdict on the product.
    `main` prints it as `AT-R1 HTTP half: ERROR` and exits 2."""


class Failed(Exception):
    """One named assertion that did not hold."""

    def __init__(self, ident: str, why: str) -> None:
        super().__init__(f"[{ident}]: {why}")
        self.ident = ident
        self.why = why


class Verdict:
    """Fail fast by default; with `--keep-going`, record and carry on where
    the next step does not depend on the failed one."""

    def __init__(self, keep_going: bool) -> None:
        self.keep_going = keep_going
        self.failures: list[Failed] = []
        self.passed = 0

    def check(self, ident: str, condition: object, why: str) -> bool:
        if condition:
            self.passed += 1
            print(f"ok    [{ident}]", flush=True)
            return True
        failure = Failed(ident, why)
        if not self.keep_going:
            raise failure
        self.failures.append(failure)
        print(f"FAIL  [{ident}]: {why}", flush=True)
        return False

    def require(self, ident: str, condition: object, why: str) -> None:
        """A check the following steps depend on: it stops the run even under
        `--keep-going`."""
        if not self.check(ident, condition, why):
            raise self.failures[-1]

    def record(self, failure: Failed) -> None:
        if failure not in self.failures:
            self.failures.append(failure)

    def report(self) -> int:
        if not self.failures:
            print(f"\nAT-R1 HTTP half: PASS ({self.passed} assertions held)")
            return 0
        first = self.failures[0]
        print(f"\nAT-R1 HTTP half: FAIL [{first.ident}]: "
              f"{first.why.splitlines()[0]}")
        for later in self.failures[1:]:
            print(f"      also FAIL [{later.ident}]: "
                  f"{later.why.splitlines()[0]}")
        print(f"      {len(self.failures)} failed, {self.passed} held")
        return 1


def note(text: str) -> None:
    print(f"      {text}", flush=True)


def as_object(value) -> dict:
    """A JSON object the product sent, or an empty one where it sent
    anything else, so a malformed answer fails a named check instead of
    raising inside the harness."""
    return value if isinstance(value, dict) else {}


def is_json_number(value) -> bool:
    """A JSON number as JavaScript reads it: an int or a float, never a
    bool (which Python counts as an int) and never a string."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def as_list(value) -> list:
    return value if isinstance(value, list) else []


@dataclasses.dataclass
class Context:
    """What one run holds: its directories, its environments, and every
    process it started."""

    checkout: Path
    scratch: Path
    state_dir: Path
    git: str
    base_env: dict[str, str]
    env: dict[str, str] = dataclasses.field(default_factory=dict)
    venv: Path | None = None
    python: Path | None = None
    server_package: Path | None = None
    servers: list[subprocess.Popen] = dataclasses.field(default_factory=list)


# ---------------------------------------------------------------------------
# Children: a clean environment, and nothing inherited that could stand in.
# ---------------------------------------------------------------------------

def stripped_environment(base: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    env, dropped = {}, []
    for name, value in base.items():
        if name.startswith(STRIPPED_PREFIXES) or name in STRIPPED_NAMES:
            dropped.append(name)
            continue
        env[name] = value
    env["LANG"] = env.get("LANG") or "C.UTF-8"
    return env, sorted(dropped)


def run(argv: list[str], *, env: dict[str, str], cwd: Path,
        timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, cwd=str(cwd), capture_output=True,
                          text=True, timeout=timeout, check=False)


def tail(text: str, lines: int = 25) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


# ---------------------------------------------------------------------------
# Processes: what "no bundled PostgreSQL process is left" is checked against.
# ---------------------------------------------------------------------------

def _proc_state(pid: str) -> str:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return "?"
    return stat.rsplit(")", 1)[-1].split()[0]


def _process_identity(pid: str) -> tuple[str, str]:
    """`(executable, command line)` of a process, empty where unreadable."""
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = ""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        argv = []
    return exe, " ".join(a.decode("utf-8", "replace") for a in argv if a)


def bundled_server_processes(server_dir: Path | None,
                             state_dir: Path) -> list[tuple[int, str]]:
    """Every live process that is this install's bundled server: its
    executable lies in the venv's server package, or its command line names
    the fresh state directory. Read at the operating system, not from the
    product's own report. A zombie has exited, so it is not running."""
    state = str(state_dir.resolve())
    server = str(server_dir.resolve()) + os.sep if server_dir else None
    found = []
    for entry in Path("/proc").iterdir():
        pid = entry.name
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        if _proc_state(pid) in ("Z", "X", "?"):
            continue
        exe, command = _process_identity(pid)
        if (server and exe.startswith(server)) or state in command:
            found.append((int(pid), command or exe))
    return found


def stop_processes(pids: list[int]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = []
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                continue
            alive.append(pid)
        if not alive:
            return
        time.sleep(3.0)
        pids = [p for p in alive if _proc_state(str(p)) not in ("Z", "X", "?")]


# ---------------------------------------------------------------------------
# HTTP, against loopback only, with the status of every answer kept.
# ---------------------------------------------------------------------------

class Answer:
    def __init__(self, status: int | None, headers: dict[str, str],
                 body: bytes, error: str | None) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self.error = error

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def describe(self) -> str:
        return f"HTTP {self.status}" if self.status is not None else (
            f"no answer ({self.error})")


def get(port: int, target: str, *, token: str | None = None) -> Answer:
    conn = http.client.HTTPConnection("127.0.0.1", port,
                                      timeout=REQUEST_TIMEOUT_SECONDS)
    headers = {"Accept": "*/*", "Cache-Control": "no-store"}
    if token:
        headers[CONSOLE_TOKEN_HEADER] = token
    try:
        conn.request("GET", target, headers=headers)
        response = conn.getresponse()
        body = response.read()
        return Answer(response.status,
                      {k.lower(): v for k, v in response.getheaders()},
                      body, None)
    except (OSError, http.client.HTTPException) as exc:
        return Answer(None, {}, b"", f"{type(exc).__name__}: {exc}")
    finally:
        conn.close()


def listening(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            return probe.connect_ex((host, port)) == 0
    except OSError:
        return False


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ---------------------------------------------------------------------------
# The served bundle, read as JavaScript well enough to find its strings.
# ---------------------------------------------------------------------------

#: A `/` after one of these words starts a regular expression, not a division.
_REGEX_AFTER_WORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await"})
#: ... and so does a `/` after one of these characters, or at the start.
_REGEX_AFTER_PUNCTUATION = frozenset("(,=:[!&|?{};+-*%<>~^")


class JsStrings:
    """The string literals of one JavaScript module, comments and regular
    expressions excluded.

    `scan()` returns `(quote, value, preceding code)` for each literal, where
    the preceding code is the last 40 characters of code before it (other
    strings blanked), so an import specifier can be told from an ordinary
    string. A template literal's value is its leading static text, before
    any `${`. It is a lexer for this bundle's own idioms, not a parser."""

    def __init__(self, source: str) -> None:
        self.src = source
        self.i = 0
        self.code: list[str] = []
        self.last = ""
        self.found: list[tuple[str, str, str]] = []

    def scan(self) -> list[tuple[str, str, str]]:
        while self.i < len(self.src):
            self._step()
        return self.found

    def _step(self) -> None:
        c = self.src[self.i]
        if self.src.startswith("//", self.i):
            end = self.src.find("\n", self.i)
            self.i = len(self.src) if end < 0 else end
        elif self.src.startswith("/*", self.i):
            end = self.src.find("*/", self.i + 2)
            self.i = len(self.src) if end < 0 else end + 2
            self.code.append(" ")
        elif c == "/" and self._regex_may_start():
            self._skip_regex()
        elif c in "\"'":
            self._quoted(c)
        elif c == "`":
            self._template()
        else:
            self.code.append(c)
            if not c.isspace():
                self.last = c
            self.i += 1

    def _recent(self) -> str:
        return "".join(self.code[-40:])

    def _emit(self, quote: str, value: str, end: int) -> None:
        self.found.append((quote, value, self._recent()))
        self.code.append(" s ")
        self.last = "s"
        self.i = end

    def _regex_may_start(self) -> bool:
        if self.last == "" or self.last in _REGEX_AFTER_PUNCTUATION:
            return True
        word = re.search(r"([A-Za-z_$][\w$]*)\s*$", self._recent())
        return word is not None and word.group(1) in _REGEX_AFTER_WORDS

    def _skip_regex(self) -> None:
        src, j, in_class = self.src, self.i + 1, False
        while j < len(src) and src[j] != "\n":
            ch = src[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "/" and not in_class:
                break
            if ch in "[]":
                in_class = ch == "["
            j += 1
        j += 1
        while j < len(src) and (src[j].isalnum() or src[j] == "_"):
            j += 1
        self.code.append(" re ")
        self.last = "e"
        self.i = j

    def _quoted(self, quote: str) -> None:
        src, j, buf = self.src, self.i + 1, []
        while j < len(src) and src[j] not in (quote, "\n"):
            if src[j] == "\\" and j + 1 < len(src):
                buf.append(src[j + 1])
                j += 2
                continue
            buf.append(src[j])
            j += 1
        self._emit(quote, "".join(buf), j + 1)

    def _template(self) -> None:
        src, j, buf, static = self.src, self.i + 1, [], True
        while j < len(src) and src[j] != "`":
            if src[j] == "\\" and j + 1 < len(src):
                if static:
                    buf.append(src[j + 1])
                j += 2
            elif src.startswith("${", j):
                static = False
                j = self._after_braces(j + 2)
            else:
                if static:
                    buf.append(src[j])
                j += 1
        self._emit("`", "".join(buf), j + 1)

    def _after_braces(self, j: int) -> int:
        depth = 1
        while j < len(self.src) and depth:
            if self.src[j] == "{":
                depth += 1
            elif self.src[j] == "}":
                depth -= 1
            j += 1
        return j


_STATIC_IMPORT_CONTEXT = re.compile(r"(?:\bimport\s*|\bfrom\s*)$")
_DYNAMIC_IMPORT_CONTEXT = re.compile(r"\bimport\s*\(\s*$")
_PATH_LITERAL = re.compile(r"^\.?/[A-Za-z][\w\-./%@~]*(?:\?\S*)?$")
_MODULE_OR_SHEET = re.compile(r"\.(?:m?js|css)(?:[?#].*)?$")


class _IndexLinks(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.modules: list[str] = []
        self.sheets: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.modules.append(a["src"])
        if tag == "link" and "stylesheet" in (a.get("rel") or "") and a.get("href"):
            self.sheets.append(a["href"])


def _resolve(base: str, ref: str) -> str:
    parts = urllib.parse.urlsplit(
        urllib.parse.urljoin("http://loopback" + base, ref))
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _graph_roots(index_html: str, capabilities: dict) -> tuple[list, list]:
    links = _IndexLinks()
    links.feed(index_html)
    roots = [(_resolve("/", m), True, "/") for m in links.modules]
    for view in as_list(as_object(capabilities.get("views")).get("views")):
        module = as_object(view).get("module")
        if isinstance(module, str) and module:
            roots.append((_resolve("/", module), True, "/capabilities"))
    return roots, [_resolve("/", sheet) for sheet in links.sheets]


#: The JavaScript MIME type essences the HTML standard lists, as
#: `tests_runtime/test_served_bundle.py`'s `JAVASCRIPT_TYPES` lists them. A
#: browser refuses a module script served under any other type.
JAVASCRIPT_TYPES = frozenset({
    "application/ecmascript", "application/javascript",
    "application/x-ecmascript", "application/x-javascript",
    "text/ecmascript", "text/javascript", "text/javascript1.0",
    "text/javascript1.1", "text/javascript1.2", "text/javascript1.3",
    "text/javascript1.4", "text/javascript1.5", "text/jscript",
    "text/livescript", "text/x-ecmascript", "text/x-javascript",
})
#: The one type a standards-mode page applies a linked stylesheet under.
STYLESHEET_TYPE = "text/css"


def media_type(answer: Answer) -> str:
    """The answer's MIME type essence: `Content-Type` without parameters
    such as `charset`, lowercased; empty where there is none."""
    value = answer.headers.get("content-type", "")
    return value.split(";", 1)[0].strip().lower()


def _judge_module(answer: Answer, path: str, static: bool, importer: str,
                  verdict: Verdict, label: str) -> None:
    if static:
        verdict.check(
            f"{label}.bundle.module {path}", answer.status == 200,
            f"{path}, imported statically by {importer}, answers "
            f"{answer.describe()}; a failed static import is a module-load "
            "pageerror (AT-R1 step 8)")
    else:
        verdict.check(
            f"{label}.bundle.dynamic {path}",
            answer.status is not None and answer.status < 500,
            f"{path}, imported dynamically by {importer}, answers "
            f"{answer.describe()}")
        if answer.status != 200:
            note(f"{path} (dynamic, from {importer}) answers "
                 f"{answer.describe()}: refused, and its importer degrades")
    if answer.status == 200:
        # SERVED, so it must be runnable: a module of any other type is
        # refused by the browser as surely as a 404 (Copilot review of
        # openDox-code#75 at f29b4ddd, r4173769822).
        verdict.check(
            f"{label}.bundle.module-type {path}",
            media_type(answer) in JAVASCRIPT_TYPES,
            f"{path}, imported {'statically' if static else 'dynamically'} "
            f"by {importer}, is served as "
            f"{answer.headers.get('content-type')!r}, which a browser "
            "refuses for a module script")


def _scan_module(path: str, body: bytes, pending: collections.deque,
                 routes: set[str], literals: set[str] | None = None) -> None:
    for _quote, value, before in JsStrings(
            body.decode("utf-8", "replace")).scan():
        if literals is not None:
            literals.add(value)
        if _DYNAMIC_IMPORT_CONTEXT.search(before):
            pending.append((_resolve(path, value), False, path))
        elif _STATIC_IMPORT_CONTEXT.search(before):
            pending.append((_resolve(path, value), True, path))
        elif _PATH_LITERAL.match(value) and not _MODULE_OR_SHEET.search(value):
            routes.add(_resolve("/", value))


def derive_bundle(port: int, index_html: str, capabilities: dict,
                  verdict: Verdict, label: str,
                  literals: set[str] | None = None) -> tuple[list[str], int]:
    """Walk the module graph the served `/` loads, fetching each module from
    the server, and return `(routes, modules)`: every same-origin path
    literal the graph names, and how many modules it holds. Every string
    literal of the graph is added to `literals` where one is given."""
    roots, sheets = _graph_roots(index_html, capabilities)
    for sheet in sheets:
        answer = get(port, sheet)
        verdict.check(f"{label}.bundle.sheet {sheet}", answer.status == 200,
                      f"the stylesheet `/` links answers {answer.describe()}")
        if answer.status == 200:
            # (Copilot review of openDox-code#75 at f29b4ddd, r4173769844.)
            verdict.check(
                f"{label}.bundle.sheet-type {sheet}",
                media_type(answer) == STYLESHEET_TYPE,
                f"the stylesheet `/` links is served as "
                f"{answer.headers.get('content-type')!r}, which a "
                "standards-mode page does not apply as CSS")
    # Each path is FETCHED and scanned once, but JUDGED once per way it is
    # imported: a module refused as a dynamic import must still answer 200
    # where another module imports it statically (Copilot review of
    # openDox-code#75, r4170450448).
    pending = collections.deque(roots)
    answers: dict[str, Answer] = {}
    judged: set[tuple[str, bool]] = set()
    routes: set[str] = set()
    while pending:
        path, static, importer = pending.popleft()
        if (path, static) in judged:
            continue
        judged.add((path, static))
        first = path not in answers
        if first:
            answers[path] = get(port, path)
        answer = answers[path]
        _judge_module(answer, path, static, importer, verdict, label)
        if first and answer.status == 200:
            _scan_module(path, answer.body, pending, routes, literals)
    modules = sum(1 for answer in answers.values() if answer.status == 200)
    return sorted(routes), modules


# ---------------------------------------------------------------------------
# Steps 1-3: the install, the clean machine, the repositories.
# ---------------------------------------------------------------------------

def copy_tracked_tree(checkout: Path, target: Path, git: str,
                      env: dict[str, str]) -> None:
    listed = run([git, "-C", str(checkout), "ls-files", "-z"], env=env,
                 cwd=target.parent)
    if listed.returncode != 0:
        raise HarnessError(f"{checkout} is not a git checkout: "
                           f"{tail(listed.stderr)}")
    for rel in filter(None, listed.stdout.split("\0")):
        src = checkout / rel
        if src.is_file():
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def make_repository(root: Path, files: dict[Path, Path | str], git: str,
                    env: dict[str, str], message: str) -> None:
    root.mkdir(parents=True)
    for rel, content in files.items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copy2(content, dst)
        else:
            dst.write_text(content, encoding="utf-8")
    for argv in (["init", "-q"],
                 ["config", "user.name", "fixture"],
                 ["config", "user.email", "fixture@example.invalid"],
                 ["add", "-A"],
                 ["commit", "-q", "-m", message]):
        done = run([git, "-C", str(root), *argv], env=env, cwd=root)
        if done.returncode != 0:
            raise HarnessError(f"git {' '.join(argv)} in {root} failed: "
                               f"{tail(done.stderr)}")


_ASK_THE_INSTALL = r"""
import importlib.metadata as md, importlib.util as iu, json, sys
siblings = sys.argv[1].split(",")
out = {"importable": [s for s in siblings if iu.find_spec(s) is not None]}
try:
    out["extras"] = sorted(md.metadata("opendox").get_all("Provides-Extra") or [])
except md.PackageNotFoundError:
    out["extras"] = None
try:
    from opendox import doxbench_bridge
    out["harness_command"] = doxbench_bridge.HARNESS_COMMAND
except Exception:
    out["harness_command"] = None
try:
    from opendox import doxbench_binding
    out["bindings_relpath"] = doxbench_binding.DEFAULT_BINDINGS_RELPATH
except Exception:
    out["bindings_relpath"] = None
spec = iu.find_spec("pixeltable_pgserver")
out["server_package"] = (list(spec.submodule_search_locations)[0]
                         if spec and spec.submodule_search_locations else None)
print(json.dumps(out))
"""


def ask_the_install(ctx: Context) -> dict:
    """What the installed product says about itself, read in the venv, in
    isolated mode, from an empty directory."""
    empty = ctx.scratch / "cwd"
    empty.mkdir(exist_ok=True)
    done = run([str(ctx.python), "-I", "-c", _ASK_THE_INSTALL,
                ",".join(SIBLINGS)], env=ctx.env, cwd=empty)
    if done.returncode != 0:
        raise HarnessError(f"could not ask the install about itself: "
                           f"{tail(done.stderr)}")
    return json.loads(done.stdout)


def install_opendox(ctx: Context, verdict: Verdict) -> dict:
    """Step 1: openDox alone, into a fresh venv, as `opendox[local]`."""
    source = ctx.scratch / "openDox-code"
    copy_tracked_tree(ctx.checkout, source, ctx.git, ctx.base_env)
    ctx.venv = ctx.scratch / "venv"
    made = run([sys.executable, "-m", "venv", "--clear", str(ctx.venv)],
               env=ctx.base_env, cwd=ctx.scratch)
    verdict.require("install.venv", made.returncode == 0,
                    f"python -m venv failed: {tail(made.stderr)}")
    ctx.python = ctx.venv / "bin" / "python"
    lock = source / "constraints-cpython312-linux.txt"
    use_lock = (lock.is_file() and sys.platform.startswith("linux")
                and sys.implementation.name == "cpython"
                and sys.version_info[:2] == (3, 12))
    install = [str(ctx.python), "-m", "pip", "install",
               "--disable-pip-version-check", "--no-input"]
    if use_lock:
        install += ["-c", str(lock)]
    install.append(f"{source}[local]")
    note("$ " + " ".join(install[2:]) + (
        "" if use_lock else "   (no lock: it pins CPython 3.12 on Linux)"))
    installed = run(install, env=ctx.base_env, cwd=ctx.scratch,
                    timeout=INSTALL_TIMEOUT_SECONDS)
    verdict.require("install opendox[local]", installed.returncode == 0,
                    f"the install failed (rc={installed.returncode}):\n"
                    f"{tail(installed.stdout)}\n{tail(installed.stderr)}")
    ctx.env = dict(ctx.base_env)
    ctx.env["PATH"] = (str(ctx.venv / "bin") + os.pathsep
                       + ctx.base_env.get("PATH", ""))
    ctx.env["OPENDOX_STATE_DIR"] = str(ctx.state_dir)
    about = ask_the_install(ctx)
    verdict.require("install declares the local extra",
                    "local" in (about.get("extras") or []),
                    f"the installed opendox declares the extras "
                    f"{about.get('extras')}, and no `local` (R1Q16 (iii)): the "
                    "documented install has no bundled server to bring")
    if about.get("server_package"):
        ctx.server_package = Path(about["server_package"])
    return about


def postgres_sockets() -> list[str]:
    """Every listening Unix socket the kernel lists (`/proc/net/unix`) whose
    name is PostgreSQL's, `.s.PGSQL.<port>`, wherever it lies: `/tmp`
    (libpq's upstream default), a distribution's directory, or any other."""
    try:
        rows = Path("/proc/net/unix").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = {row.split()[-1] for row in rows[1:]
             if len(row.split()) >= 8
             and Path(row.split()[-1]).name.startswith(".s.PGSQL.")}
    return sorted(found)


def _shared_directory(sock: str) -> bool:
    """Whether other users can traverse the socket's directory, as they can
    every default libpq consults (`/tmp`, `/var/run/postgresql`). A socket
    in a private (0700) directory is another install's own, reachable only
    by its owner through an explicit setting, and no child inherits one.
    A directory that cannot be read is treated as shared: fail closed."""
    try:
        mode = os.stat(os.path.dirname(sock)).st_mode
    except OSError:
        return True
    return bool(mode & stat.S_IXOTH)


def _socket_answers(sock: str) -> bool:
    if not os.path.exists(sock):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            return probe.connect_ex(sock) == 0
    except OSError:
        return False


def no_database_answers(verdict: Verdict, env: dict[str, str]) -> None:
    for host in ("127.0.0.1", "::1"):
        verdict.check(f"clean.database tcp {host}:5432",
                      not listening(host, 5432),
                      f"a database already listens on {host}:5432, so the "
                      "bundled server would not be the only one")
    # EVERY PostgreSQL socket the kernel lists, not a list of directories
    # kept here (Copilot review of openDox-code#75, r4170537350: a server on
    # `/tmp`'s socket alone, with TCP off, passed a fixed list).
    for sock in sorted(set(postgres_sockets()) | set(DISTRIBUTION_SOCKETS)):
        if not _shared_directory(sock):
            note(f"{sock} is another install's private socket (its "
                 "directory admits no other user); no child is configured "
                 "to reach it")
            continue
        verdict.check(f"clean.database socket {sock}",
                      not _socket_answers(sock),
                      f"a database already answers on {sock}, a directory "
                      "every user's libpq can default to")
    present = [name for name in DATABASE_SETTINGS if env.get(name)]
    verdict.check("clean.database settings", not present,
                  f"the child environment names a database: {present}")


def assert_clean_machine(ctx: Context, about: dict, verdict: Verdict) -> None:
    """Step 2: every absence AT-R1 step 1 names, asserted, not assumed."""
    path = ctx.env["PATH"]
    verdict.check("clean.siblings", not about["importable"],
                  f"importable in the fresh venv: {about['importable']}")
    harnesses = {HARNESS_COMMAND, about.get("harness_command") or HARNESS_COMMAND}
    on_path = [h for h in sorted(harnesses) if shutil.which(h, path=path)]
    verdict.check("clean.omp", not on_path,
                  f"a harness is on the PATH ({on_path}), so no-model is not "
                  "what this run measures")
    brokers = [b for b in BROKER_COMMANDS if shutil.which(b, path=path)]
    identity = [n for n in IDENTITY_SETTINGS if ctx.env.get(n)]
    verdict.check("clean.identity-broker", not brokers and not identity,
                  f"an identity broker is present: on the PATH {brokers}, "
                  f"set {identity}")
    no_database_answers(verdict, ctx.env)
    verdict.check("clean.state-dir", not any(ctx.state_dir.iterdir()),
                  f"OPENDOX_STATE_DIR {ctx.state_dir} is not empty")
    verdict.check("clean.no-bundled-server-yet",
                  not bundled_server_processes(ctx.server_package,
                                               ctx.state_dir),
                  "a process of this install's bundled server runs before "
                  "anything started it")


def make_repositories(ctx: Context, about: dict,
                      verdict: Verdict) -> list[tuple[str, Path]]:
    """Step 3: both plain repositories, each a fresh `git init` with a git
    identity and no model binding."""
    fixture = ctx.scratch / "openDox-code" / "tests" / "fixtures" / "plain-documents"
    verdict.require("repos.fixture", fixture.is_dir(),
                    f"5.0's fixture is missing at {fixture}")
    repos = ctx.scratch / "repos"
    a, b = repos / "plain-documents", repos / "plain-notes"
    make_repository(a, {p.relative_to(fixture): p
                        for p in sorted(fixture.rglob("*")) if p.is_file()},
                    ctx.git, ctx.env, "fixture")
    make_repository(b, {Path(k): v for k, v in PLAIN_NOTES.items()},
                    ctx.git, ctx.env, "notes")
    bindings = about.get("bindings_relpath") or BINDINGS_RELPATH_FALLBACK
    for label, repo in (("a", a), ("b", b)):
        verdict.check(f"clean.binding {label}", not (repo / bindings).exists(),
                      f"{repo} holds a model binding at {bindings}")
        name = run([ctx.git, "-C", str(repo), "config", "user.name"],
                   env=ctx.env, cwd=repo)
        verdict.check(f"repos.{label} git identity",
                      name.stdout.strip() == "fixture",
                      f"{repo} has no git identity, so no served actor")
    return [("a", a), ("b", b)]


# ---------------------------------------------------------------------------
# Steps 4-8, once per repository.
# ---------------------------------------------------------------------------

class Server:
    """One launched entry point, and what it has said."""

    def __init__(self, label: str, proc: subprocess.Popen, port: int,
                 out: Path, err: Path) -> None:
        self.label = label
        self.proc = proc
        self.port = port
        self.out = out
        self.err = err

    def said(self) -> str:
        return (f"\n--- stdout ---\n{tail(self.out.read_text('utf-8', 'replace'))}"
                f"\n--- stderr ---\n{tail(self.err.read_text('utf-8', 'replace'))}")

    def printed(self) -> str:
        """Everything the entry point has written so far, both streams."""
        return (self.out.read_text("utf-8", "replace") + "\n"
                + self.err.read_text("utf-8", "replace"))


def documented_prefix() -> list[str]:
    words = DOCUMENTED_START.split(" ")
    if words[-1] != "…":
        raise HarnessError("DOCUMENTED_START lost its `…`")
    return words[:-1]


def launch(label: str, repo: Path, ctx: Context,
           verdict: Verdict) -> tuple[Server, Answer]:
    """Step 4: the documented start, checked before and after it runs."""
    port = free_port()
    for host in ("127.0.0.1", "::1"):
        verdict.require(f"{label}.start.port-free {host}:{port}",
                        not listening(host, port),
                        f"something already listens on {host}:{port}, so a "
                        "ready answer would not come from this run")
    prefix = documented_prefix()
    argv = prefix + ["--repo-root", str(repo), "--repository", "fixture",
                     "--no-open", "--port", str(port)]
    verdict.require(f"{label}.start.documented-command",
                    argv[:len(prefix)] == prefix,
                    f"the harness would run {argv[:len(prefix)]}, not the "
                    f"documented `{DOCUMENTED_START}`")
    program = shutil.which(argv[0], path=ctx.env["PATH"])
    verdict.require(
        f"{label}.start.console-script",
        program is not None
        and Path(program).resolve().is_relative_to(ctx.venv.resolve()),
        f"`{argv[0]}` resolves to {program!r}, not the fresh venv's console "
        "script")
    note("$ " + " ".join(argv))
    out, err = ctx.scratch / f"{label}-server.out", ctx.scratch / f"{label}-server.err"
    with open(out, "wb") as stdout, open(err, "wb") as stderr:
        proc = subprocess.Popen(argv, executable=program, env=ctx.env,
                                cwd=str(ctx.scratch), stdout=stdout,
                                stderr=stderr, stdin=subprocess.DEVNULL,
                                start_new_session=True)
    ctx.servers.append(proc)
    server = Server(label, proc, port, out, err)
    index = wait_until_ready(server)
    verdict.require(
        f"{label}.start.ready", index is not None,
        (f"the documented command exited (rc={proc.returncode}) before it "
         "answered" if proc.poll() is not None else
         f"no answer on 127.0.0.1:{port} within {READY_TIMEOUT_SECONDS:.0f}s")
        + server.said())
    verdict.require(f"{label}.start.serving-process", proc.poll() is None,
                    "the launched server exited after it answered, so the "
                    "answer may not have been its own" + server.said())
    return server, index


def wait_until_ready(server: Server) -> Answer | None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline and server.proc.poll() is None:
        answer = get(server.port, "/")
        if answer.status == 200:
            return answer
        time.sleep(0.5)
    return None


def fetch_object(server: Server, route: str, verdict: Verdict) -> dict:
    answer = get(server.port, route)
    verdict.require(f"{server.label}.http {route}", answer.status == 200,
                    f"{route} answers {answer.describe()}")
    try:
        body = answer.json()
    except ValueError as exc:
        body = exc
    verdict.require(f"{server.label}.{route} is a JSON object",
                    isinstance(body, dict),
                    f"{route} is not a JSON object: {body!r:.300}")
    return body


def string_values(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from string_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from string_values(value)
    elif isinstance(node, str):
        yield node


def check_pages(server: Server, index: Answer,
                verdict: Verdict) -> tuple[dict, dict]:
    """Step 5: `/`, `/snapshot.json` and `/capabilities`."""
    label = server.label
    page = index.body.decode("utf-8", "replace")
    verdict.check(f"{label}.http / is HTML",
                  "<html" in page.lower()
                  and "text/html" in index.headers.get("content-type", ""),
                  f"`/` answered {index.headers.get('content-type')!r} "
                  "without an <html> element")
    snapshot = fetch_object(server, "/snapshot.json", verdict)
    documents = snapshot.get("documents")
    verdict.check(f"{label}.snapshot non-empty",
                  isinstance(documents, list) and bool(documents),
                  f"the snapshot's documents are not a non-empty list: "
                  f"{documents!r:.200}")
    leaks = sorted({m.group(1) for v in string_values(snapshot)
                    for m in F53_PATTERN.finditer(v.lower())})
    verdict.check(f"{label}.snapshot neutral (F5.3)", not leaks,
                  f"openxFactory's vocabulary leaked into the neutral "
                  f"snapshot: {leaks}")
    note(f"snapshot kind={snapshot.get('kind')!r}, "
         f"{len(as_list(snapshot.get('documents')))} documents")
    caps = fetch_object(server, "/capabilities", verdict)
    install_block = as_object(caps.get("install"))
    verdict.check(f"{label}.capabilities install.mode == local",
                  install_block.get("mode") == "local",
                  f"the served install block is {caps.get('install')!r}")
    pid = as_object(install_block.get("database_bundle")).get("pid")
    if isinstance(pid, int):
        note(f"the served install reports its bundled server as pid {pid}")
    check_no_published_token(label, caps, verdict)
    return snapshot, caps


def check_no_published_token(label: str, caps: dict, verdict: Verdict) -> None:
    """A standalone plane does not publish its console token on
    `/capabilities` (plan 034 T104): any loopback caller, another OS user of
    the machine included, can read that route."""
    verdict.check(f"{label}.capabilities carries no console token",
                  CONSOLE_TOKEN_FIELD not in caps,
                  f"/capabilities publishes `{CONSOLE_TOKEN_FIELD}` to any "
                  "loopback caller; a standalone plane delivers it only "
                  "through the 0600 opener file (T104, adversarial review "
                  "2's M5)")


def grouping_field_of(caps: dict) -> str:
    fields = as_object(as_object(caps.get("display")).get("fields"))
    field = as_object(fields.get("grouping")).get("field")
    return field if isinstance(field, str) and field else "clusters"


def check_grouping(label: str, snapshot: dict, caps: dict,
                   verdict: Verdict) -> None:
    """A grouping tile the chat pane can open on: an id and a member
    document, which is also what the rail's thread read is built from
    (Copilot review of openDox-code#75, at 32ef3e8c)."""
    field = grouping_field_of(caps)
    verdict.check(f"{label}.snapshot fills the grouping station",
                  thread_query(snapshot, field) is not None,
                  f"the snapshot's grouping station ({field!r}) holds no "
                  "tile with an id and a member document, so no grouping "
                  "tile can open the chat pane (R1Q13 (a) with (c); AT-R1 "
                  f"fails and does not skip): {snapshot.get(field)!r:.200}")


# ---------------------------------------------------------------------------
# Step 6: the console token, as the user's browser is handed it (T104).
# ---------------------------------------------------------------------------

class _RefreshContents(html.parser.HTMLParser):
    """Every `<meta http-equiv="refresh">` `content` in a page, unescaped,
    and the text of every JSON `<script>` whose id is the console record's."""

    def __init__(self) -> None:
        super().__init__()
        self.contents: list[str] = []
        self.records: list[str] = []
        self._in_record = False

    def handle_starttag(self, tag, attrs) -> None:
        named = {key.lower(): value or "" for key, value in attrs}
        if tag == "script":
            self._in_record = (
                named.get("id") == CONSOLE_RECORD_ID
                and named.get("type", "").strip().lower() == "application/json")
            if self._in_record:
                self.records.append("")
            return
        if tag != "meta":
            return
        if named.get("http-equiv", "").strip().lower() == "refresh":
            self.contents.append(named.get("content", ""))

    def handle_endtag(self, tag) -> None:
        if tag == "script":
            self._in_record = False

    def handle_data(self, data) -> None:
        if self._in_record:
            self.records[-1] += data


def record_disagrees_because(records: list[str], port: int,
                             target: str | None, token: str) -> str | None:
    """Why the opener's record does not describe its own forward, or `None`.
    No reason quotes the token."""
    if len(records) != 1:
        return (f"the opener holds {len(records)} `#{CONSOLE_RECORD_ID}` "
                "JSON records, not one")
    try:
        record = json.loads(records[0])
    except ValueError:
        return "the opener's record is not JSON"
    if not isinstance(record, dict):
        return "the opener's record is not a JSON object"
    version = record.get("schema_version")
    problems = []
    if record.get("kind") != CONSOLE_RECORD_KIND or not (
            is_json_number(version)
            and version == CONSOLE_RECORD_SCHEMA_VERSION):
        problems.append(f"it is kind={record.get('kind')!r} "
                        f"schema_version={version!r}, not "
                        f"{CONSOLE_RECORD_KIND!r} v{CONSOLE_RECORD_SCHEMA_VERSION}")
    if not (is_json_number(record.get("port")) and record.get("port") == port):
        problems.append(f"its port is {record.get('port')!r}, not {port}")
    if record.get(CONSOLE_FRAGMENT_KEY) != token:
        problems.append(f"its `{CONSOLE_FRAGMENT_KEY}` is not the token the "
                        "forward carries")
    if record.get("opened_url") != target:
        problems.append("its `opened_url` is not the URL the forward opens")
    page_url = record.get("page_url")
    if not (isinstance(page_url, str) and isinstance(target, str)
            and target.split("#", 1)[0] == page_url):
        problems.append("its `page_url` is not the forward's page")
    if not problems:
        return None
    # A record value may hold the token (a `kind` that is the token, say),
    # and a reason reaches the CI log, so it never quotes it.
    reason = "the opener's record disagrees with its forward: " + "; ".join(
        problems)
    return reason.replace(token, "<the console token>")


def refresh_target(content: str) -> str | None:
    """The URL a refresh's `content` names (`0;url=<target>`, quoted or not)."""
    _delay, separator, rest = content.partition(";")
    rest = rest.strip()
    if not separator or rest[:4].lower() != "url=":
        return None
    target = rest[4:].strip()
    if len(target) >= 2 and target[0] == target[-1] and target[0] in "'\"":
        target = target[1:-1]
    return target or None


def opener_location(printed: str) -> Path | None:
    """The opener's path, from the start's `console <file URL>` line."""
    match = CONSOLE_LINE.search(printed)
    if match is None:
        return None
    where = match.group("where")
    if not where.startswith("file:"):
        return Path(where)
    # An unparseable file URL is the product's output, so it is the named
    # `console opener printed` failure, never a harness error (Copilot review
    # of openDox-code#75 at d53a7378, r4173842805).
    try:
        parts = urllib.parse.urlsplit(where)
    except ValueError:
        return None
    if parts.netloc not in ("", "localhost") or parts.query or parts.fragment:
        return None
    return Path(urllib.parse.unquote(parts.path))


def opener_unsafe_because(path: Path) -> str | None:
    """Why `path` is not a private opener, or `None`: this user's regular
    file, mode exactly 0600, with one link, in this user's own directory,
    which no one else can enter."""
    try:
        info = os.lstat(path)
        directory = os.lstat(path.parent)
    except OSError as exc:
        return f"cannot be examined ({type(exc).__name__}: {exc.strerror})"
    uid = os.getuid()
    mode = stat.S_IMODE(info.st_mode)
    reason = None
    if stat.S_ISLNK(info.st_mode):
        reason = "is a symbolic link"
    elif not stat.S_ISREG(info.st_mode):
        reason = "is not a regular file"
    elif info.st_uid != uid:
        reason = f"is owned by uid {info.st_uid}, not by this user"
    elif info.st_nlink != 1:
        reason = f"has {info.st_nlink} hard links, not one"
    elif mode != OPENER_MODE:
        reason = f"has mode {mode:o}, not {OPENER_MODE:o}"
    elif not stat.S_ISDIR(directory.st_mode) or directory.st_uid != uid:
        reason = f"sits in {path.parent}, which is not this user's own directory"
    elif directory.st_mode & 0o077:
        reason = (f"sits in {path.parent}, mode "
                  f"{stat.S_IMODE(directory.st_mode):o}, which others can enter")
    return reason


def _read_without_following(path: Path, limit: int = 64 * 1024) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        chunks, size = [], 0
        while size < limit:
            chunk = os.read(descriptor, limit - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        os.close(descriptor)
    return b"".join(chunks).decode("utf-8", "replace")


def _within(path: Path, root: Path) -> bool:
    real = Path(os.path.realpath(path))
    return real.is_relative_to(Path(os.path.realpath(root)))


#: What a browser's URL parser reads differently from `urllib.parse`, so a
#: forward carrying it is refused before it is parsed at all: a backslash,
#: which a browser reads as `/` in an http URL (`http://evil\@127.0.0.1/`
#: goes to `evil`), and whitespace and control characters, which a browser
#: strips or rejects.
_UNPARSED_ALIKE = re.compile(r"[\\\x00-\x20\x7f]")


def token_in_fragment(targets: list[str | None],
                      port: int) -> tuple[str | None, str]:
    """The token the opener's one forward carries in its FRAGMENT, or `None`
    and why not. No message here quotes a token, or any part of the URL,
    which could hold one (Copilot review of openDox-code#75 at d53a7378,
    r4173842794)."""
    if len(targets) != 1 or targets[0] is None:
        return None, (f"the opener has {len(targets)} meta-refresh forwards, "
                      "not one that names a URL")
    elsewhere = (f"the opener does not forward to this plane on loopback "
                 f"port {port} (its forward is not quoted, because it may "
                 "hold the token)")
    target = targets[0]
    # A browser and `urllib.parse` must read the SAME destination, or the
    # check below judges a URL the browser never opens (r4173842763).
    if _UNPARSED_ALIKE.search(target):
        return None, (f"{elsewhere}: it holds a backslash, whitespace or a "
                      "control character, which a browser reads differently")
    try:
        parts = urllib.parse.urlsplit(target)
        target_port = parts.port
    except ValueError:      # a malformed authority or port (r4173842811)
        return None, f"{elsewhere}: it is not a URL this harness can parse"
    if parts.username is not None or parts.password is not None \
            or "@" in parts.netloc:
        return None, (f"{elsewhere}: it carries user information before its "
                      "host")
    if (parts.scheme != "http" or parts.hostname not in LOOPBACK_HOSTS
            or target_port != port):
        return None, elsewhere
    if CONSOLE_FRAGMENT_KEY in urllib.parse.parse_qs(parts.query,
                                                     keep_blank_values=True):
        return None, ("the opener's forward carries the token in its QUERY, "
                      "which reaches the request line, the server's log and "
                      "any Referer")
    values = urllib.parse.parse_qs(parts.fragment, keep_blank_values=True).get(
        CONSOLE_FRAGMENT_KEY, [])
    if len(values) != 1 or not values[0]:
        return None, (f"the opener's forward carries no single "
                      f"`#{CONSOLE_FRAGMENT_KEY}=` in its fragment")
    if values[0] in parts.path or values[0] in parts.query:
        return None, ("the opener's forward carries the token outside its "
                      "fragment too")
    return values[0], ""


def check_console_opener(label: str, port: int, printed: str, state_dir: Path,
                         served_root: Path,
                         verdict: Verdict) -> tuple[Path | None, str | None]:
    """Step 6: the opener the start printed, and the token its forward
    carries, read from the file as the user's browser reads it."""
    path = opener_location(printed)
    verdict.check(f"{label}.console opener printed", path is not None,
                  "the start printed no `console <file URL>` line naming the "
                  "opener, so a user has no way to open the console page")
    if path is None:
        return None, None
    expected = state_dir / CONSOLE_DIRNAME / f"{port}.html"
    verdict.check(f"{label}.console opener is OPENDOX_STATE_DIR/console/<port>.html",
                  path == expected, f"the start printed {path}, not {expected}")
    verdict.check(f"{label}.console opener is outside the served repository",
                  not _within(path, served_root),
                  f"{path} is inside the served repository {served_root}")
    reason = opener_unsafe_because(path)
    verdict.check(f"{label}.console opener is private", reason is None,
                  f"{path} {reason}")
    try:
        page = _read_without_following(path)
    except OSError as exc:
        verdict.check(f"{label}.console opener forwards with the token in its "
                      "fragment", False,
                      f"{path} cannot be read ({type(exc).__name__}: "
                      f"{exc.strerror})")
        return path, None
    contents = _RefreshContents()
    contents.feed(page)
    contents.close()
    targets = [refresh_target(content) for content in contents.contents]
    token, why = token_in_fragment(targets, port)
    verdict.check(f"{label}.console opener forwards with the token in its "
                  "fragment", token is not None, why)
    if token is not None:
        disagrees = record_disagrees_because(contents.records, port,
                                             targets[0], token)
        verdict.check(f"{label}.console opener record agrees with its forward",
                      disagrees is None, disagrees or "")
    return path, token


def check_catalog(server: Server, token: str | None, verdict: Verdict) -> None:
    """Step 7: the catalog, asked as the console, offers nothing available,
    and asked without the token, refuses."""
    label = server.label
    bare = get(server.port, CATALOG_ROUTE)
    verdict.check(f"{label}.catalog refuses a caller without the console token",
                  bare.status is not None and 400 <= bare.status < 500,
                  f"{CATALOG_ROUTE} without the token answers "
                  f"{bare.describe()}, so the token the opener carries would "
                  "guard nothing")
    catalog = get(server.port, CATALOG_ROUTE, token=token)
    asked = ("with the console token" if token else
             "with no console token to present (step 6 found none)")
    verdict.check(f"{label}.catalog answers", catalog.status == 200,
                  f"{CATALOG_ROUTE} {asked} answers "
                  f"{catalog.describe()}: {catalog.body[:300]!r}")
    if catalog.status != 200:
        return
    # The payload's SHAPE is a named check, never a harness error: `[]`,
    # `null` or `{"models": 1}` fail `catalog is a catalog` (Copilot review
    # of openDox-code#75, r4170450491).
    try:
        payload = catalog.json()
    except ValueError:
        payload = None
    models = as_object(payload).get("models")
    verdict.check(f"{label}.catalog is a catalog", isinstance(models, list),
                  f"{CATALOG_ROUTE} answered no models[]: "
                  f"{catalog.body[:300]!r}")
    # THE ENVELOPE THE RAIL ADOPTS, or it shows "the catalog could not be
    # read" and never its no-model state (Copilot review of
    # openDox-code#75, at f0e0ffe1). JavaScript's `=== 1` admits no `true`
    # and no `"1"`, so neither does this. It admits every JSON NUMBER equal to
    # 1, though: `1.0` and `1e0` parse to the same JavaScript number, and
    # Python reads them as the float 1.0 (Copilot review of #75 at 1c0ff975,
    # r4173473346).
    envelope = as_object(payload)
    version = envelope.get("schema_version")
    verdict.check(f"{label}.catalog envelope is the one the chat rail adopts",
                  is_json_number(version) and version == CATALOG_SCHEMA_VERSION
                  and envelope.get("kind") == CATALOG_KIND,
                  f"the catalog's envelope is schema_version={version!r}, "
                  f"kind={envelope.get('kind')!r}; the chat rail adopts only "
                  f"schema_version={CATALOG_SCHEMA_VERSION}, "
                  f"kind={CATALOG_KIND!r}")
    available = [as_object(m).get("model_id") for m in as_list(models)
                 if as_object(m).get("available")]
    verdict.check(f"{label}.catalog offers no available entry", not available,
                  f"no model is configured, yet the catalog offers {available}")


def thread_query(snapshot: dict, grouping_field: str) -> str | None:
    """The query the chat rail sends on open, for the first grouping tile
    that has a member document."""
    for group in map(as_object, as_list(snapshot.get(grouping_field))):
        if not group.get("id"):
            continue
        members = [edge.get("document") for edge in
                   map(as_object, as_list(group.get("document_edges")))
                   if edge.get("document")]
        if members:
            return urllib.parse.urlencode({
                "repository": str(snapshot.get("repository") or ""),
                "ref": "main",
                "tile_kind": GROUPING_TILE_KIND,
                "tile_id": str(group["id"]),
                "document": str(members[0]),
            })
    return None


def requests_for(routes: list[str], snapshot: dict,
                 grouping_field: str) -> list[str]:
    documents = [urllib.parse.quote(str(d["path"]))
                 for d in map(as_object, as_list(snapshot.get("documents")))
                 if d.get("path")]
    key = urllib.parse.quote(f"{snapshot.get('repository') or ''}@main",
                             safe="")
    query = thread_query(snapshot, grouping_field)
    targets: list[str] = []
    for route in routes:
        targets.append(route)
        if route.endswith("/"):
            targets += [route + doc for doc in documents]
            targets += [f"{route}{key}/{doc}" for doc in documents]
        if route == THREAD_ROUTE and query:
            targets.append(f"{route}?{query}")
    return targets


def check_routes(server: Server, index: Answer, snapshot: dict, caps: dict,
                 token: str | None, verdict: Verdict) -> None:
    """Step 8: every route the served bundle names answers, below 5xx."""
    label = server.label
    literals: set[str] = set()
    routes, modules = derive_bundle(server.port,
                                    index.body.decode("utf-8", "replace"),
                                    caps, verdict, label, literals)
    note(f"derived from the served bundle: {modules} modules, "
         f"{len(routes)} routes: {', '.join(routes)}")
    verdict.check(f"{label}.bundle names the catalog route",
                  CATALOG_ROUTE in routes,
                  f"the served bundle no longer names {CATALOG_ROUTE}, so "
                  "this harness's catalog step asks the wrong route")
    verdict.check(f"{label}.bundle names the catalog kind",
                  CATALOG_KIND in literals,
                  f"the served bundle no longer names {CATALOG_KIND!r}, so "
                  "this harness's catalog envelope check is stale")
    for target in requests_for(routes, snapshot, grouping_field_of(caps)):
        answer = get(server.port, target, token=token)
        note(f"GET {target} -> {answer.describe()}")
        dropped = ("; a dropped connection is a handler that raised"
                   if answer.status is None else "")
        verdict.check(f"{label}.route {target}",
                      answer.status is not None and answer.status < 500,
                      f"GET {target} answers {answer.describe()}{dropped}"
                      + server.said())


def stop_and_look(server: Server, ctx: Context, verdict: Verdict,
                  opener: Path | None = None, token: str | None = None) -> None:
    """Step 9: stop the entry point alone, as `kill` would, and look."""
    label = server.label
    server.proc.send_signal(signal.SIGTERM)
    try:
        rc = server.proc.wait(timeout=STOP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        rc = None
    verdict.check(f"{label}.stop exits", rc is not None,
                  f"the server did not exit within {STOP_TIMEOUT_SECONDS:.0f}s "
                  "of SIGTERM")
    note(f"the entry point exited rc={rc}")
    left = bundled_server_processes(ctx.server_package, ctx.state_dir)
    verdict.check(f"{label}.stop leaves no bundled PostgreSQL process",
                  not left,
                  "still running after the entry point stopped: "
                  + "; ".join(f"pid {pid}: {what}" for pid, what in left))
    # Over the WHOLE serve's output, its shutdown included.
    check_console_gone(label, opener, token, server.printed(), verdict)


def check_console_gone(label: str, opener: Path | None, token: str | None,
                       printed: str, verdict: Verdict) -> None:
    """After the stop: the opener went with the server, and the token was
    never printed, in either stream."""
    if opener is not None:
        verdict.check(f"{label}.stop removes the console opener",
                      not os.path.lexists(opener),
                      f"{opener} is still there after the server stopped, "
                      "and its token was this serve's")
    if token is not None:
        verdict.check(f"{label}.console token never printed",
                      token not in printed,
                      "the entry point printed the console token itself; "
                      "it prints only the opener's path")


def serve_one(label: str, repo: Path, ctx: Context, verdict: Verdict) -> None:
    """Steps 4-9 for one repository: start, fetch, stop, and look."""
    server, index = launch(label, repo, ctx, verdict)
    snapshot, caps = check_pages(server, index, verdict)
    check_grouping(label, snapshot, caps, verdict)
    opener, token = check_console_opener(label, server.port, server.printed(),
                                         ctx.state_dir, repo, verdict)
    check_catalog(server, token, verdict)
    check_routes(server, index, snapshot, caps, token, verdict)
    stop_and_look(server, ctx, verdict, opener, token)


# ---------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------

def prepare() -> Context:
    """The run's directories and its children's base environment, or a
    HarnessError before anything is installed."""
    if not Path("/proc/self/exe").exists():
        raise HarnessError("this harness reads /proc; run it on Linux")
    git = shutil.which("git")
    if git is None:
        raise HarnessError("git is not on the PATH")
    scratch = Path(tempfile.mkdtemp(prefix="at-r1-http-")).resolve()
    state_dir = Path(tempfile.mkdtemp(prefix="odx-")).resolve()
    socket_path = len(os.fsencode(state_dir)) + len(SOCKET_SUFFIX)
    if socket_path > SOCKET_PATH_MAX:
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(state_dir, ignore_errors=True)
        raise HarnessError(
            f"OPENDOX_STATE_DIR {state_dir} would put the bundled server's "
            f"socket at {socket_path} bytes, past {SOCKET_PATH_MAX}; set "
            "TMPDIR to a shorter directory")
    base_env, dropped = stripped_environment(dict(os.environ))
    if dropped:
        note(f"not inherited by any child: {', '.join(dropped)}")
    for name in ("home", "tmp"):
        (scratch / name).mkdir()
    base_env.update(HOME=str(scratch / "home"), TMPDIR=str(scratch / "tmp"))
    return Context(checkout=Path(__file__).resolve().parents[1],
                   scratch=scratch, state_dir=state_dir, git=git,
                   base_env=base_env)


def cleanup(ctx: Context, keep: bool) -> None:
    """However the run ended: stop what it started, then remove what it
    made. A leftover bundled server is killed only here, after the verdict
    on it has been taken."""
    for proc in ctx.servers:
        if proc.poll() is not None:
            continue
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=STOP_TIMEOUT_SECONDS)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    stop_processes([pid for pid, _ in
                    bundled_server_processes(ctx.server_package, ctx.state_dir)])
    if keep:
        note(f"kept {ctx.scratch} and {ctx.state_dir}")
        return
    shutil.rmtree(ctx.scratch, ignore_errors=True)
    shutil.rmtree(ctx.state_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AT-R1's HTTP half (plan 034 T095): install the openDox "
                    "checkout this file is in, alone, assert a clean machine, "
                    "run the documented command over two plain repositories, "
                    "and check what it serves. TMPDIR chooses where its "
                    "scratch and state directories go.")
    parser.add_argument("--keep", action="store_true",
                        help="keep the scratch and state directories")
    parser.add_argument("--keep-going", action="store_true",
                        help="report every failed assertion instead of "
                             "stopping at the first (still exits 1)")
    args = parser.parse_args(argv)
    # Anything that stops the preparation is the harness's own failure, never
    # a verdict on the product: a refusal it names, or an error it did not
    # expect (a full disk under `tempfile.mkdtemp`, for one), and both exit 2
    # (Copilot review of openDox-code#75, at b4fc637f).
    try:
        ctx = prepare()
    except HarnessError as error:
        print(f"AT-R1 HTTP half: ERROR: {error}", file=sys.stderr)
        return 2
    except Exception:
        traceback.print_exc()
        print("AT-R1 HTTP half: ERROR: the harness could not prepare its "
              "directories", file=sys.stderr)
        return 2
    verdict = Verdict(args.keep_going)
    print(f"AT-R1, the HTTP half (plan 034 T095), over {ctx.checkout}")
    print(f"      the documented install: {DOCUMENTED_INSTALL}")
    print(f"      the documented start:   {DOCUMENTED_START}")
    print(f"      scratch {ctx.scratch}; OPENDOX_STATE_DIR {ctx.state_dir}",
          flush=True)
    error = None
    try:
        about = install_opendox(ctx, verdict)
        assert_clean_machine(ctx, about, verdict)
        for label, repo in make_repositories(ctx, about, verdict):
            print(f"--- repository ({label}) {repo.name}", flush=True)
            serve_one(label, repo, ctx, verdict)
    except Failed as failure:
        # A fail-fast stop, or a `require` that ended a `--keep-going` run;
        # reported with the rest, after the cleanup below.
        verdict.record(failure)
    except HarnessError as exc:
        error = str(exc)
    except Exception:  # the harness itself broke: say so, never a PASS
        traceback.print_exc()
        error = "the harness raised before a verdict"
    finally:
        cleanup(ctx, args.keep)
    if error is not None:
        print(f"\nAT-R1 HTTP half: ERROR: {error}", flush=True)
        return 2
    return verdict.report()


if __name__ == "__main__":
    sys.exit(main())
