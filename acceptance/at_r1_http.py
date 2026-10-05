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
    console token: a standalone plane hands its token to no loopback
    caller, T104). As quickstart.md § 3 asserts it (T007 batch N), the RAW
    payload carries the token neither by name, at any depth, nor by value,
    which step 6 checks once the opener has handed the harness the token.
 6. READS THE CONSOLE TOKEN THE WAY THE USER'S BROWSER IS HANDED IT (plan 034
    T104; RULED openxFactory#656 `5963851934`). The start prints the PATH of
    a private opener file, `<OPENDOX_STATE_DIR>/console/<port>.html`, and
    never the token. The file must be this user's regular file, mode 0600,
    with one link, in a directory of mode 0700, under a state
    directory and ancestors no other user can change (T104's own rules for
    that tree), and outside the served repository. Its one LIVE
    meta-refresh (none inside a `<template>`, a `<noscript>` or a raw-text
    element counts, as none forwards a browser that runs scripts) forwards
    to this plane on loopback with `#console_token=<token>` in the URL's
    FRAGMENT, and never in the query. Its JSON record (`#opendox-console`, kind
    `opendox-console-access` v1) must describe that same forward: its port,
    its token, its `opened_url` and its `page_url`. The harness reads that
    file itself, with the standard library, as a browser would, and imports
    nothing from the product. No line the harness prints quotes that token,
    or any other the opener or `/capabilities` carries (`Verdict.redact`):
    it reads the opener's tokens as soon as the start answers, before step 5
    quotes anything (`learn_opener_tokens`), and no diagnostic quotes the
    entry point's output or a `/capabilities` payload.
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
load). A route ending in `/` (`/source/`) is a prefix the wheel, the viewer
and the workbench's source loader complete with a document path, so it is
also requested once per document the snapshot lists, plain and keyed by the
workbench's `(repository, ref)` key, as the panes fill it.
The chat rail's THREAD READ is not requested with a query, because a
standalone plane's rail sends none: the rail reads `/workbench/thread` only
where `/capabilities` contributes a branch-session column,
`gate.workbench.session`, and otherwise answers "no readable thread" itself
(`app.js`, `doxbenchThreadSeam`; openDox-code#85, the T102 follow-on, holder
ruling F1 (i) on openxFactory#656). The harness asserts that this plane
contributes none, and asks the bare route literal only, as it asks every
literal.
Every request carries the console token the opener delivered (step 6), as
the doxBench transports do, so a guarded read answers from its handler
rather than from the console check.

RUNNING IT. From an openDox-code checkout, `python3 acceptance/at_r1_http.py`
installs and drives THAT checkout (the one this file is in); to measure
another tree, copy this file into it. It takes no path or port: its scratch
space and its `OPENDOX_STATE_DIR` are fresh temporary directories, so
`TMPDIR` chooses where they go. Choose a short one that only you can write:
the bundled server refuses a state directory below a directory any user can
write without the sticky bit, and so does the harness, before it installs
anything (exit 2); and the socket path may not pass 107 bytes.
It needs Linux (it reads `/proc`), `git`, and network access to the package
index. The standard library only: it runs before, and outside, the
environment it builds.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import errno
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
#: The only token the page accepts from the fragment (T104's
#: `web/views/notebook.js`, `CONSOLE_TOKEN_SHAPE`, `^[A-Za-z0-9_-]{16,512}$`).
CONSOLE_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{16,512}")
#: What stands for a console token in every line the harness prints
#: (`Verdict.redact`), and the least length of a value it stands for: the
#: page's own least length, so a short value never blanks out a word.
REDACTED = "<the console token>"
#: A run of a token's characters and `%XX` escapes, which `Verdict.redact`
#: percent-decodes.
_ENCODABLE_RUN = re.compile(r"(?:[A-Za-z0-9_-]|%[0-9A-Fa-f]{2})+")
SECRET_MIN_LENGTH = 16
CONSOLE_LINE = re.compile(r"^[ \t]*console (?P<where>(?:file:|/)\S*)", re.M)
#: The opener's machine-readable record, "for a harness or a script"
#: (`opendox.console_access`, T104): JSON in
#: `<script type="application/json" id="opendox-console">`. The harness parses
#: it itself, with the standard library, and imports nothing from the product.
CONSOLE_RECORD_ID = "opendox-console"
CONSOLE_RECORD_KIND = "opendox-console-access"
CONSOLE_RECORD_SCHEMA_VERSION = 1
OPENER_MODE = 0o600
#: The most of an opener the harness reads, and it reads it whole: a larger
#: file is refused by name, never judged by a truncated prefix. T104's is
#: about one kilobyte.
OPENER_READ_LIMIT = 64 * 1024
#: The opener's directory, `console/`, exactly (quickstart.md § 3; T104).
OPENER_DIRECTORY_MODE = 0o700
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
#: The paths that serve the console page, `/` and the `/index.html` T104's
#: entry points open (`serve_mod.server_url(httpd, "/index.html")`).
CONSOLE_PAGES = ("/", "/index.html")

#: The model-catalog route (`app.js` `CATALOG_ROUTE`), which the derived list
#: must also name, so this constant cannot drift from the bundle unseen.
CATALOG_ROUTE = "/workbench/model-catalog"

#: The only catalog envelope the chat rail ADOPTS (`views/doxbench-chat-model.js`,
#: `adoptCatalog`: `schema_version === 1`, `kind === CATALOG_WIRE_KIND`, and an
#: array of `models`); it reads any other as unreadable. The served bundle must
#: name the kind too, so this constant cannot drift from the bundle unseen.
CATALOG_KIND = "workbench-model-catalog"
CATALOG_SCHEMA_VERSION = 1

#: The chat rail's thread read, and the contributed binding it is read
#: through: the rail sends one only where `/capabilities` contributes a
#: branch-session column, `gate.workbench.session` (`app.js`,
#: `doxbenchThreadSeam`; openDox-code#85, the T102 follow-on; holder ruling
#: F1 (i) on openxFactory#656, `5973854291`). A standalone plane has none.
THREAD_ROUTE = "/workbench/thread"
SESSION_BINDING_ID = "gate.workbench.session"

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
    the next step does not depend on the failed one.

    NO LINE IT PRINTS QUOTES A CONSOLE TOKEN. Every token the run has seen
    (`keep_secret`: the one the opener carries, any other its forwards or
    its record carry, one `/capabilities` publishes) is blanked out of every
    assertion id, every reason and every note, so a product that echoes its
    token into an answer or a path cannot make the harness publish it in the
    CI log."""

    def __init__(self, keep_going: bool) -> None:
        self.keep_going = keep_going
        self.failures: list[Failed] = []
        self.passed = 0
        self.secrets: set[str] = set()

    def keep_secret(self, value: object) -> None:
        """Never print `value`: a console token this run has seen. Only a
        string of a token's least length (`CONSOLE_TOKEN_SHAPE`) is kept, so
        a short value never blanks words out of an unrelated line."""
        if isinstance(value, str) and len(value) >= SECRET_MIN_LENGTH:
            self.secrets.add(value)

    def redact(self, text: str) -> str:
        """`text` with every secret blanked out: as it is, and inside any run
        of the token's characters and `%XX` escapes whose percent-decodings
        hold it, partly encoded or encoded twice (Copilot review of
        openDox-code#75 at ba216f84, r4178913911)."""
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, REDACTED)
        if not self.secrets:
            return text

        def blank(run: re.Match) -> str:
            if "%" in run.group(0) and any(
                    secret in form for form in _decodings(run.group(0))
                    for secret in self.secrets):
                return REDACTED
            return run.group(0)
        return _ENCODABLE_RUN.sub(blank, text)

    def note(self, text: str) -> None:
        note(self.redact(text))

    def check(self, ident: str, condition: object, why: str) -> bool:
        ident, why = self.redact(ident), self.redact(why)
        if condition:
            self.passed += 1
            print(f"ok    [{printable(ident)}]", flush=True)
            return True
        failure = Failed(ident, why)
        if not self.keep_going:
            raise failure
        self.failures.append(failure)
        print(f"FAIL  [{printable(ident)}]: {printable_lines(why)}",
              flush=True)
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
        # Again here: a token learned after a failure was recorded.
        first = self.failures[0]
        print("\nAT-R1 HTTP half: FAIL "
              + self._shown(first.ident, first_line(first.why)))
        for later in self.failures[1:]:
            print("      also FAIL "
                  + self._shown(later.ident, first_line(later.why)))
        print(f"      {len(self.failures)} failed, {self.passed} held")
        return 1

    def _shown(self, ident: str, why: str) -> str:
        return (f"[{printable(self.redact(ident))}]: "
                f"{printable(self.redact(why))}")


def note(text: str) -> None:
    print(f"      {printable(text)}", flush=True)


def first_line(text: str) -> str:
    return (text.splitlines() or [""])[0]


def printable(text: str) -> str:
    """`text` as one line of the CI log carries it: every character that is
    not printable written as its escape (a control, a newline, a format
    character such as a bidirectional override, a lone surrogate, a line or
    paragraph separator), so nothing a server sends can end a line, forge
    one, or raise while it is printed (the self-pass after Copilot's review
    of openDox-code#75 at 4bdb41fb, r4178395690)."""
    return "".join(c if c.isprintable()
                   else c.encode("unicode_escape").decode("ascii")
                   for c in text)


def printable_lines(text: str) -> str:
    """A reason of several lines (the install's output tails), each line
    `printable`, and every line after the first indented under a `|`, so no
    line of it can stand at the start of a line of the log."""
    return "\n      | ".join(printable(line) for line in text.split("\n"))


#: ASCII upper case to lower case, and nothing else: `str.lower` also folds
#: non-ASCII letters, where the HTML and MIME standards compare
#: ASCII-case-insensitively.
_ASCII_LOWER = {code: code + 32 for code in range(ord("A"), ord("Z") + 1)}


def ascii_lower(text: str) -> str:
    return text.translate(_ASCII_LOWER)


def scalar_values(text: str) -> str:
    """`text` as a browser reads a URL from a JavaScript or JSON string: as
    a USVString (WebIDL), a surrogate pair joined into the one code point it
    encodes and a lone surrogate replaced by U+FFFD. Python keeps
    `"\\uD83D\\uDE00"`, decoded escape by escape, as two code points that no
    codec encodes (Copilot review of openDox-code#75 at 4bdb41fb,
    r4178395690)."""
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le",
                                                            "replace")


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

def _no_constant(name: str):
    raise ValueError(f"{name} is no JSON value")


def strict_json(text: str):
    """`text` parsed as a browser's `JSON.parse` and `response.json()`
    parse it: `NaN`, `Infinity` and `-Infinity`, which `json.loads` admits,
    are refused as malformed (Copilot review of openDox-code#75 at
    2dcb98d3, r4178069345)."""
    return json.loads(text, parse_constant=_no_constant)


class Answer:
    def __init__(self, status: int | None, headers: dict[str, str],
                 body: bytes, error: str | None) -> None:
        self.status = status
        self.headers = headers
        self.body = body
        self.error = error

    def json(self):
        """The body as JSON. A body nested past the parser's depth raises
        `ValueError`, as any other malformed body does, so every caller's
        named failure takes it, never a harness ERROR (Copilot review of
        openDox-code#75 at ec95f451, r4175016692)."""
        try:
            # A browser's `response.json()` decodes UTF-8 as the Encoding
            # standard does: a leading BOM dropped, and invalid bytes read as
            # U+FFFD, never an error.
            return strict_json(self.body.decode("utf-8-sig", "replace"))
        except RecursionError as exc:
            raise ValueError("JSON nested past the parser's depth") from exc

    def describe(self) -> str:
        return f"HTTP {self.status}" if self.status is not None else (
            f"no answer ({self.error})")


#: What a browser's URL parser percent-encodes in a path, and in a special
#: URL's query, beside C0 controls, space and every code point past U+007E
#: (the URL standard's path and special-query percent-encode sets).
_PATH_ENCODED = frozenset('"#<>?`{}')
_QUERY_ENCODED = frozenset('"#<>\'')


#: What a 3xx answer reads as: no answer this harness judges.
REDIRECTED = "a redirect, which this harness does not follow"


def browser_target(target: str) -> str:
    """`target` (a path, perhaps with a query) as a browser requests it:
    a space, a non-ASCII character or a control percent-encoded, and every
    `%` left as it is. `http.client` refuses such a target, or raises on a
    non-ASCII one, where a browser sends it encoded (the self-pass after
    Copilot's review of openDox-code#75 at 2dcb98d3). A lone surrogate,
    which no codec encodes, is first read as the browser reads it
    (`scalar_values`)."""
    path, mark, query = scalar_values(target).partition("?")

    def encode(text: str, extra: frozenset) -> str:
        return "".join(
            urllib.parse.quote(c, safe="")
            if ord(c) <= 0x20 or ord(c) > 0x7E or c in extra else c
            for c in text)
    return encode(path, _PATH_ENCODED) + mark + encode(query, _QUERY_ENCODED)


def get(port: int, target: str, *, token: str | None = None,
        host: str = "127.0.0.1") -> Answer:
    """`target` asked of the plane on `port` at `host`, as a browser on a
    page of that origin asks it: `http.client` sends that host in `Host`,
    which the plane's loopback gate reads."""
    conn = http.client.HTTPConnection(host, port,
                                      timeout=REQUEST_TIMEOUT_SECONDS)
    headers = {"Accept": "*/*", "Cache-Control": "no-store"}
    if token:
        headers[CONSOLE_TOKEN_HEADER] = token
    try:
        conn.request("GET", browser_target(target), headers=headers)
        response = conn.getresponse()
        body = response.read()
        if 300 <= response.status < 400:
            # A browser follows it, to a URL this harness would have to
            # judge in its place: refused by name, never judged as the
            # status it is (the self-pass after Copilot's review of
            # openDox-code#75 at 4bdb41fb).
            return Answer(None, {}, b"", f"HTTP {response.status}, "
                          f"{REDIRECTED}")
        # A header sent twice is read as one, its values joined by `, `, as
        # a browser joins them (Fetch's "get" on a header list).
        received: dict[str, str] = {}
        for name, value in response.getheaders():
            name = name.lower()
            received[name] = (f"{received[name]}, {value}"
                              if name in received else value)
        return Answer(response.status, received, body, None)
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return Answer(None, {}, b"", error_name(exc))
    finally:
        conn.close()


def error_name(exc: BaseException) -> str:
    """A failed request, named without the text the peer sent: the error's
    type, and the operating system's own words where it has them. An
    `http.client` error's message quotes the server's status line or
    headers, which may carry the token (Copilot review of openDox-code#75
    at 82869769, r4177924097, carried to every answer)."""
    strerror = exc.strerror if isinstance(exc, OSError) else None
    return f"{type(exc).__name__}: {strerror}" if strerror else type(exc).__name__


#: A plain MIME type essence, the only `Content-Type` a reason quotes.
_PLAIN_MEDIA_TYPE = re.compile(r"[a-z0-9!#$&^_.+-]{1,64}/[a-z0-9!#$&^_.+-]{1,64}")


def shown_type(answer: Answer) -> str:
    """The answer's `Content-Type` for a reason: its essence where it is a
    plain MIME type, and otherwise not quoted, as it is the server's own
    bytes (r4177924097)."""
    if "content-type" not in answer.headers:
        return "no Content-Type"
    essence = media_type(answer)
    if _PLAIN_MEDIA_TYPE.fullmatch(essence):
        return repr(essence)
    return "a Content-Type that is no plain MIME type (not quoted)"


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

#: A `/` after one of these words starts a regular expression, not a division:
#: the reserved words an expression may follow, and those a line break ends
#: (`break`, `continue`, `debugger`), after which a statement starts.
_REGEX_AFTER_WORDS = frozenset({
    "return", "typeof", "instanceof", "in", "new", "delete", "void",
    "throw", "case", "default", "do", "else", "extends", "yield", "await",
    "break", "continue", "debugger"})
#: ... and `of`, which is a keyword only in a `for` head, and a name elsewhere
#: (`const of = 4; of / 2` divides).
_FOR_HEAD_WORDS = _REGEX_AFTER_WORDS | {"of"}
#: ... and so does a `/` after one of these characters, or at the start.
_REGEX_AFTER_PUNCTUATION = frozenset("(,=:[!&|?{};+-*%<>~^")
#: The keywords whose `(…)` is a condition, after which a statement, and so
#: a regular expression, may start.
_CONDITION_WORDS = frozenset({"if", "while", "for", "with"})
#: The last name of some code, whitespace already read as one space: a whole
#: name, so `ñreturn` is no `return`, and a private one with its `#`.
_LAST_NAME = re.compile(r"(#?[\w$]+) ?$")
#: The `.` (or `?.`) before a member's name; and a `.` that is no member
#: access, the last of a spread's `...` or a decimal literal's own point
#: (`1. in`, but neither `1 .`, `1..`, `1.5.` nor `1e5.`).
_MEMBER_DOT = re.compile(r"\. ?$")
_NO_MEMBER_DOT = re.compile(r"(?:\.\.|(?<![\w$.])\d[\d_]*)\. ?$")


def _condition_opened(code: str) -> str:
    """The keyword whose condition a `(` after `code` opens: `if`, `while`,
    `for` or `with`, and `for` after `for await`; or "" for none."""
    word = _LAST_NAME.search(code)
    if word is None:
        return ""
    if word.group(1) == "await" and _ends_with_keyword(code[:word.start()],
                                                       frozenset({"for"})):
        return "for"
    return word.group(1) if _ends_with_keyword(code, _CONDITION_WORDS) else ""


def _ends_with_keyword(code: str, words: frozenset) -> bool:
    """Whether `code` ends with one of `words` as a KEYWORD: never as a
    member's name (`obj.return`, `obj . if`, `obj?.of`), which is an operand
    (Copilot review of openDox-code#75 at ff04e015, r4180554323), nor as
    part of a longer or private name (`ñreturn`, `this.#of`). After a
    spread's `...` or a decimal point (`[...typeof x]`, `1. in x`), it is
    still the keyword."""
    word = _LAST_NAME.search(code)
    if word is None or word.group(1) not in words:
        return False
    before = code[:word.start()]
    return (not _MEMBER_DOT.search(before)
            or _NO_MEMBER_DOT.search(before) is not None)


#: JavaScript's WhiteSpace and LineTerminator code points (ECMA-262): tab,
#: VT, FF, U+FEFF, every space separator (Zs), LF, CR, LS and PS. Python's
#: `\s` is not this set: it lacks U+FEFF, and adds U+001C-U+001F and U+0085
#: (Copilot review of openDox-code#75 at ba216f84, r4178913887).
_JS_WHITESPACE = frozenset(
    "\t\v\f \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006"
    "\u2007\u2008\u2009\u200a\u202f\u205f\u3000\ufeff\n\r\u2028\u2029")

#: What ends a line comment, as JavaScript's LineTerminator: LF, and CR,
#: U+2028 and U+2029 as well (Copilot's review of openDox-code#75 at
#: 9229c659, its overview).
_JS_LINE_END = re.compile("[\n\r\u2028\u2029]")

#: JavaScript's single-character escapes.
_JS_SINGLE_ESCAPES = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
                      "v": "\v"}
_JS_LINE_TERMINATORS = "\r\n\u2028\u2029"
_JS_DIGITS = "0123456789"
_JS_HEX2 = re.compile(r"[0-9A-Fa-f]{2}")
_JS_UNICODE = re.compile(r"\{([0-9A-Fa-f]+)\}|([0-9A-Fa-f]{4})")


def js_escape(src: str, j: int) -> tuple[str | None, int]:
    r"""The text the escape sequence at `src[j]` (a backslash) stands for in
    a JavaScript string or template, and the index after it: `\n`, `\t` and
    the other single escapes, `\0` where no digit follows, `\xHH`,
    `\uHHHH`, `\u{H…}` (any number of digits, up to U+10FFFF), a line
    continuation (nothing), and any other character as itself. A specifier
    is read as the browser reads it, so `"./ch\tild.js"` holds a TAB, and
    `"./\u0063hild.js"` is `./child.js` (found while answering Copilot's
    review of openDox-code#75 at 2dcb98d3, r4178069374).

    `None` where a MODULE refuses the escape, as it is strict code: a legacy
    octal escape (`\1`, `\00`), `\8` and `\9`, and a `\x` or `\u` that is
    not well formed are each a SyntaxError, and a browser loads none of the
    module (the self-pass after Copilot's review of openDox-code#75 at
    4bdb41fb)."""
    c = src[j + 1]
    if c in _JS_LINE_TERMINATORS:
        end = j + 2
        if c == "\r" and src.startswith("\n", end):
            end += 1
        return "", end
    if c in _JS_DIGITS:
        following = src[j + 2:j + 3]
        if c == "0" and not (following and following in _JS_DIGITS):
            return "\0", j + 2
        return None, j + 2
    if c in _JS_SINGLE_ESCAPES:
        return _JS_SINGLE_ESCAPES[c], j + 2
    if c == "x":
        if _JS_HEX2.fullmatch(src[j + 2:j + 4]):
            return chr(int(src[j + 2:j + 4], 16)), j + 4
        return None, j + 2
    if c == "u":
        match = _JS_UNICODE.match(src, j + 2)
        if match and int(match.group(1) or match.group(2), 16) <= 0x10FFFF:
            return chr(int(match.group(1) or match.group(2), 16)), match.end()
        return None, j + 2
    return c, j + 2


class JsStrings:
    """The string literals of one JavaScript module, comments and regular
    expressions excluded.

    `scan()` returns `(quote, value, preceding code)` for each literal, where
    the preceding code is the last 40 characters of code before it (other
    strings blanked, comments and every run of JavaScript whitespace read
    as ONE space, so no run is too long for it), so an import specifier can
    be told from an ordinary string. A template literal's value is its
    leading static text, before any `${`; each `${…}` in it is CODE, and is
    read as code is, so an import or a route inside one is found (Copilot
    review of openDox-code#75 at 3392f93a, r4179115282), and a `}` in its
    strings closes nothing. Each value is read as a browser reads a URL from it
    (`scalar_values`). `malformed` is set where a string holds an escape a
    module refuses (`js_escape`), as an untagged template does too, and
    `ambiguous` where a `/` stands right after a `}`, which a lexer cannot
    read. It is a lexer for this bundle's own idioms, not a parser."""

    def __init__(self, source: str) -> None:
        self.src = source
        self.i = 0
        self.code: list[str] = []
        self.last = ""
        self.found: list[tuple[str, str, str]] = []
        self.malformed = False
        # `{` open in code; and, for each `${` being read, the depth its `}`
        # closes at and whether its template is tagged.
        self.depth = 0
        self.interpolations: list[tuple[int, bool]] = []
        # For each `(` open in code, the keyword whose condition it opens
        # (`if`, `while`, `for` or `with`), or "" for none; and whether the
        # last `)` closed one.
        self.parens: list[str] = []
        self.closed_condition = False
        # Whether a `/` stood right after a `}`, which this lexer cannot read.
        self.ambiguous = False

    def scan(self) -> list[tuple[str, str, str]]:
        while self.i < len(self.src):
            self._step()
        return self.found

    def _step(self) -> None:
        c = self.src[self.i]
        if self.src.startswith("//", self.i) or (
                self.i == 0 and self.src.startswith("#!")):  # or a hashbang
            end = _JS_LINE_END.search(self.src, self.i)
            self.i = len(self.src) if end is None else end.start()
        elif self.src.startswith("/*", self.i):
            end = self.src.find("*/", self.i + 2)
            self.i = len(self.src) if end < 0 else end + 2
            self._space()
        elif c == "/" and self.last == "}":
            # A `}` that closes a BLOCK is followed by a statement, so a `/`
            # opens a regular expression; one that closes an EXPRESSION (an
            # object literal, a function or class expression) is followed by
            # a division. Telling them apart takes a parser, so the module is
            # refused by name, never read by a guess (Copilot review of
            # openDox-code#75 at d50e8cef, r4180454790). It is read on as a
            # regular expression.
            self.ambiguous = True
            self._skip_regex()
        elif c == "/" and self._regex_may_start():
            self._skip_regex()
        elif c in "\"'":
            self._quoted(c)
        elif c == "`":
            self._template()
        elif c in _JS_WHITESPACE:
            self._space()
            self.i += 1
        elif (c == "}" and self.interpolations
                and self.interpolations[-1][0] == self.depth):
            self._template(resume=self.interpolations.pop()[1])
        else:
            if c == "{":
                self.depth += 1
            elif c == "}":
                self.depth -= 1
            elif c == "(":
                self.parens.append(_condition_opened(self._recent()))
            elif c == ")":
                self.closed_condition = bool(self.parens and self.parens.pop())
            self.code.append(c)
            self.last = c
            self.i += 1

    def _space(self) -> None:
        if not (self.code and self.code[-1].endswith(" ")):
            self.code.append(" ")

    def _recent(self) -> str:
        return "".join(self.code[-40:])

    def _emit(self, quote: str, value: str, end: int) -> None:
        self.found.append((quote, scalar_values(value), self._recent()))
        self.code.append(" s ")
        self.last = "s"
        self.i = end

    def _regex_may_start(self) -> bool:
        """Whether a `/` here opens a regular expression, not a division:
        where no operand ends just before it. After `)`, only where it closed
        the condition of an `if`, `while`, `for` or `with`; after `++` or
        `--`, only where the operator is a prefix, with no operand before it
        (Copilot review of openDox-code#75 at b7b9b843, r4179348386: `n++ /
        2` divides). After a spread's `...`, or a keyword an expression may
        follow, it opens one; `of` is that keyword only in a `for` head (the
        pass after Copilot's review overview at ea4f7838)."""
        if self.last == ")":
            return self.closed_condition
        code = self._recent().rstrip(" ")
        if code.endswith(("++", "--")):
            return not self._ends_an_operand(code[:-2].rstrip(" "))
        if code.endswith("..."):        # a spread, before an expression
            return True
        if self.last == "" or self.last in _REGEX_AFTER_PUNCTUATION:
            return True
        return _ends_with_keyword(self._recent(), self._keywords())

    def _keywords(self) -> frozenset:
        """The words after which an expression starts here: `of` among them
        only in a `for` head, where it is the keyword."""
        if self.parens and self.parens[-1] == "for":
            return _FOR_HEAD_WORDS
        return _REGEX_AFTER_WORDS

    def _ends_an_operand(self, code: str) -> bool:
        """Whether `code` ends with an operand: a name or a literal that is
        no keyword before an expression (a member's name, `obj.of`, is
        none), a `)`, a `]`, or a string."""
        if code.endswith((")", "]")):
            return True
        return (_LAST_NAME.search(code) is not None
                and not _ends_with_keyword(code, self._keywords()))

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
                text, j = js_escape(src, j)
                if text is None:
                    self.malformed, text = True, ""
                buf.append(text)
                continue
            buf.append(src[j])
            j += 1
        self._emit(quote, "".join(buf), j + 1)

    def _template(self, resume: bool | None = None) -> None:
        """A template's text from `self.i` (its opening backtick, or, where
        `resume` holds its taggedness, the `}` that closed a `${`) to its
        closing backtick or its next `${`. Its leading static text is its
        value; at a `${` the scan goes back to reading code, until the `}`
        that closes it at the same depth calls this again."""
        src, j, buf = self.src, self.i + 1, []
        # A TAGGED template (`String.raw` before one) may hold an escape a
        # module otherwise refuses. Its tag is an expression, so it stands
        # where a regular expression could not start.
        tagged = (not self._regex_may_start()) if resume is None else resume
        while j < len(src) and src[j] != "`":
            if src[j] == "\\" and j + 1 < len(src):
                text, j = js_escape(src, j)
                if text is None:
                    self.malformed = self.malformed or not tagged
                    text = ""
                buf.append(text)
            elif src.startswith("${", j):
                self._close_text(resume, "".join(buf), j + 2)
                self.interpolations.append((self.depth, tagged))
                # An EXPRESSION starts here, so a `/` opens a regular
                # expression, as after any `{` (Copilot review of
                # openDox-code#75 at 0717f72f, r4179220628).
                self.code.append("${")
                self.last = "{"
                return
            else:
                buf.append(src[j])
                j += 1
        self._close_text(resume, "".join(buf), j + 1)

    def _close_text(self, resume: bool | None, value: str, end: int) -> None:
        # The LEADING text is the template's value; a later one is not.
        if resume is None:
            self._emit("`", value, end)
        else:
            self.code.append(" s ")
            self.last = "s"
            self.i = end


#: The code before an import's specifier, whitespace already read as one
#: space (`JsStrings`): `import` or `from`, or `import(`, and never a member
#: named `import` (`loader.import("x")` is a call, not an import).
_STATIC_IMPORT_CONTEXT = re.compile(r"(?<![\w$.])(?<!\. )(?:import|from) ?$")
_DYNAMIC_IMPORT_CONTEXT = re.compile(r"(?<![\w$.])(?<!\. )import ?\( ?$")
_PATH_LITERAL = re.compile(r"^\.?/[A-Za-z][\w\-./%@~]*(?:\?\S*)?$")
_MODULE_OR_SHEET = re.compile(r"\.(?:m?js|css)(?:[?#].*)?$")


#: Elements whose content a browser that runs scripts (as the console page
#: needs) never makes live, by the HTML standard's parsing rules: a
#: `<template>`'s content is inert, a `<noscript>`'s is text where scripts
#: run, and a raw-text or escapable raw-text element holds text, never
#: elements. A refresh or a record inside one forwards and records nothing
#: (Copilot review of openDox-code#75 at 4809b3d2, r4174671390). Two more
#: are not modeled: `select`, whose content parsers have dropped or kept as
#: they changed, and `frameset`, after which no other element is inserted,
#: once the page has allowed one. A tag a reader watches inside a live
#: `select`, and a live `frameset`, are each refused by name (`_LivePage`).
_INERT_CONTENT = frozenset({"template", "noscript", "script", "style",
                            "textarea", "title", "xmp", "iframe", "noembed",
                            "noframes", "plaintext", "select", "frameset"})
#: ... and of those, the ones whose content is TEXT: nothing inside opens an
#: element, and only their own end tag closes them.
_TEXT_CONTENT = _INERT_CONTENT - {"template", "select", "frameset"}
#: ... and the ones nothing closes, to the end of the page.
_NEVER_CLOSED = frozenset({"plaintext", "frameset"})


#: A named character reference not ended by `;` (`&amp` before a letter).
_UNTERMINATED_REFERENCE = re.compile(r"&[A-Za-z][A-Za-z0-9]*(?![A-Za-z0-9;])")


def _first_attributes(attrs) -> dict[str, str]:
    """A tag's attributes as a browser keeps them: where a name repeats,
    the FIRST value, never the last."""
    named: dict[str, str] = {}
    for key, value in attrs:
        named.setdefault(key.lower(), value or "")
    return named


#: The Encoding standard's labels of UTF-8, the one encoding this harness
#: reads a page in.
_UTF8_LABELS = frozenset({"unicode-1-1-utf-8", "unicode11utf8",
                          "unicode20utf8", "utf-8", "utf8", "x-unicode20utf8"})
#: A `charset=` as a `Content-Type`, a `<meta charset>`, a `<meta
#: http-equiv="content-type">` or the encoding prescan of a page's first
#: bytes reads one.
_CHARSET = re.compile(
    r"charset[\t\n\f\r ]*=[\t\n\f\r ]*[\"']?([^\"'\t\n\f\r ;>]*)",
    re.IGNORECASE | re.ASCII)


def not_utf8_because(body: bytes, content_type: str | None) -> str | None:
    """Why a browser may decode `body` other than as UTF-8, which is how
    this harness reads a page, or `None`. A UTF-8 byte order mark decides it
    (it outranks every declaration). Otherwise a UTF-16 one, or any
    `charset=` in `content_type` or anywhere in the page that names no
    UTF-8 label, is refused by name: a browser may read such a page's bytes
    as other characters, or, for a label of the replacement encoding
    (`iso-2022-kr`), as nothing at all (the self-pass after Copilot's review
    of openDox-code#75 at 4bdb41fb). The label is not quoted."""
    if body.startswith(b"\xef\xbb\xbf"):
        return None
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "it starts with a UTF-16 byte order mark"
    for where, text in (("its Content-Type", content_type or ""),
                        ("the page", body.decode("utf-8", "replace"))):
        for match in _CHARSET.finditer(text):
            label = ascii_lower(match.group(1).strip(_ASCII_WHITESPACE))
            if label not in _UTF8_LABELS:
                return (f"{where} declares a charset other than UTF-8 (not "
                        "quoted)")
    return None


#: Foreign content, whose parsing this harness does not model: inside `<svg>`
#: and `<math>`, `<script>` and `<link>` are not HTML elements, `<style>`
#: and `<title>` hold markup, and `<meta>` breaks out as a live HTML element.
_FOREIGN_CONTENT = frozenset({"svg", "math"})


class _LivePage(html.parser.HTMLParser):
    """A page's LIVE elements, as a browser that runs scripts parses it:
    `live_tag(tag, attributes)` is called for each, with the FIRST of a
    repeated attribute, and nothing inside `_INERT_CONTENT` is live. `/>`
    closes only a void element, so `<template/>` stays open.

    What this harness does not model is named in `unmodeled`, and each
    reader refuses the page by name on it, never reading it as an
    approximation: a live `<svg>` or `<math>`, a live `<frameset>`, and a
    tag the reader WATCHES inside a live `<select>` (the self-pass after
    Copilot's review of openDox-code#75 at 4bdb41fb, r4178395669)."""

    WATCHED: frozenset = frozenset()

    def __init__(self) -> None:
        super().__init__()
        self._inert: list[str] = []
        self.unmodeled: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if self._inert and self._inert[-1] in _TEXT_CONTENT:
            return                      # text to a browser, not an element
        live = not self._inert
        if (not live and tag in self.WATCHED and self._inert[0] == "select"
                and "template" not in self._inert):
            self.unmodeled.append(f"a <{tag}> inside a <select>")
        if tag in _INERT_CONTENT:
            self._inert.append(tag)
        if not live:
            return
        if tag in _FOREIGN_CONTENT or tag == "frameset":
            self.unmodeled.append(f"<{tag}> content")
        self.live_tag(tag, _first_attributes(attrs))

    def handle_startendtag(self, tag, attrs) -> None:
        # A browser ignores `/>` on any element but a void one.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag) -> None:
        if self._inert and tag == self._inert[-1] and tag not in _NEVER_CLOSED:
            self._inert.pop()
            self.closed(tag)

    def live_tag(self, tag: str, named: dict[str, str]) -> None:
        """A live element's start tag."""

    def closed(self, tag: str) -> None:
        """The end of an inert element's content."""


def script_type(named: dict[str, str]) -> str | None:
    """What a browser makes of a `<script>`, by its `type` and `language`
    (the HTML standard's "prepare the script element"): `"classic"`,
    `"module"` or `"importmap"`, or `None` for a data block, which it never
    runs. A `type` is trimmed of ASCII whitespace and compared
    ASCII-case-insensitively, so `" Module "` is a module, and
    `"application/json"` and `"  "` are data blocks."""
    if "type" in named:
        if named["type"] == "":
            return "classic"
        kind = named["type"].strip(_ASCII_WHITESPACE)
    elif named.get("language", ""):
        kind = "text/" + named["language"]
    else:
        return "classic"
    kind = ascii_lower(kind)
    if kind in JAVASCRIPT_TYPES:
        return "classic"
    if kind in ("module", "importmap"):
        return kind
    return None


class _IndexLinks(_LivePage):
    """The page's LIVE scripts, stylesheets and `<base>`, read as a browser
    reads them (`_LivePage`): `rel` as a set of ASCII-case-insensitive
    tokens, and a script by what a browser makes of it (`script_type`).

    Only a live MODULE script with a `src` is a root of the module graph:
    a script inside a `<template>` runs nothing, a data block runs nothing,
    and one with an empty `src` fails to load (Copilot review of
    openDox-code#75 at 4bdb41fb, r4178395669). A CLASSIC script, by its
    `src` or inline, and an INLINE module script each run code this harness
    does not read, so each is a named failure, except a classic script
    marked `nomodule`, which a browser that runs modules skips. A `<base
    href>` or an import map changes how a browser resolves what the page
    loads, and this harness models neither, so each is a named failure too
    (`_check_page_resolution`)."""

    WATCHED = frozenset({"script", "link", "base"})

    def __init__(self) -> None:
        super().__init__()
        self.modules: list[str] = []
        self.sheets: list[str] = []
        self.bases: list[str] = []
        self.import_maps = 0
        self.classic: list[str] = []        # each `src`, or "" where inline
        self.inline_modules = 0

    def live_tag(self, tag, named):
        # `html.unescape` decodes `&copy=2` in an attribute; a browser keeps
        # a reference with no `;` before `=` or a letter or digit as text, so
        # the two read different URLs. Refused by name, as the opener's
        # refresh is (Copilot review of openDox-code#75 at 0717f72f,
        # r4179220641).
        if tag in self.WATCHED and _UNTERMINATED_REFERENCE.search(
                self.get_starttag_text() or ""):
            self.unmodeled.append(f"a <{tag}> whose attributes hold a "
                                  "character reference with no `;`")
            return
        if tag == "script":
            kind = script_type(named)
            if kind == "importmap":
                self.import_maps += 1
            elif kind == "module" and "src" not in named:
                self.inline_modules += 1
            elif kind == "module" and named["src"]:
                self.modules.append(named["src"])
            elif (kind == "classic" and "nomodule" not in named
                    and named.get("src", "x")):
                self.classic.append(named.get("src", ""))
        rel = re.split(r"[ \t\n\f\r]+", ascii_lower(named.get("rel", "")))
        if tag == "link" and "stylesheet" in rel and named.get("href"):
            self.sheets.append(named["href"])
        if tag == "base" and "href" in named:
            self.bases.append(named["href"])


#: The origin a reference is resolved against where no server is named (a
#: route literal, which is a path). `derive_bundle` resolves the module
#: graph against the RUNNING server's own origin (`plane_origin`).
_SAME_ORIGIN = "http://loopback"
#: What a reference this harness cannot parse resolves to: never a path.
UNPARSEABLE_PREFIX = "unparseable:"
#: What a reference a browser reads differently resolves to: never a path.
#: A browser reads a backslash in an http URL as `/`, so
#: `http://external.invalid\@127.0.0.1:<port>/x.js` goes to
#: `external.invalid` and `/\host/x.js` to `host`, and it drops tab and
#: newline characters and trims spaces and control characters, while
#: `urllib.parse` keeps them all (Copilot review of openDox-code#75 at
#: 2dcb98d3, r4178069374). Such a reference is refused by name.
DIVERGENT_PREFIX = "divergent:"
#: The URL standard's divergences from `urllib.parse`: a backslash (read as
#: `/` in an http URL), a tab or newline anywhere (removed), and a C0
#: control or space at either end (trimmed). An inner space is encoded, not
#: dropped, so it is no divergence.
_DIVERGENT_REFERENCE = re.compile(r"\\|[\t\n\r]|^[\x00-\x20]|[\x00-\x20]$")
#: A path SEGMENT a browser's URL parser reads as `.` or `..` and urljoin
#: does not: `%2e`, `.%2e`, `%2e.` or `%2e%2e`, in any case. A `%2e` inside
#: a longer segment (`child%2Ejs`) is no dot segment, and a browser
#: requests it as it is (Copilot review of openDox-code#75 at ba216f84,
#: r4178913926). And a URL with user information, which a browser refuses
#: to fetch a module or a stylesheet from, is divergent too (`_resolve`).
_ENCODED_DOT = re.compile(r"(?:^|/)(?:%2e|\.%2e|%2e\.|%2e%2e)(?=/|$)",
                          re.IGNORECASE | re.ASCII)
_DEFAULT_PORTS = {"http": 80, "https": 443}


def plane_origin(port: int, host: str = "127.0.0.1") -> str:
    """The origin of the page the harness loads: the loopback host the
    opener's forward names (`127.0.0.1` for `/` itself), on the launched
    plane's port. Plain HTTP, as the plane serves on loopback only, and the
    host is one `token_in_fragment` admitted from `LOOPBACK_HOSTS`."""
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return urllib.parse.urlunsplit(("http", netloc, "", "", ""))


def _origin_of(url: str) -> tuple | None:
    """`(scheme, host, port)` of `url` as the URL standard compares origins
    (a default port made explicit), or `None` where it has no host or no
    readable port, which no same-origin check admits."""
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port or _DEFAULT_PORTS.get(parts.scheme)
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return parts.scheme, parts.hostname, port


def _resolve(base: str, ref: str, origin: str = _SAME_ORIGIN) -> str:
    """`ref` resolved against `base` as a browser resolves it on this plane:
    a same-origin path (with its query), or, for anything that leaves the
    plane, the whole absolute URL, which never starts with `/` (Copilot
    review of openDox-code#75 at 142d1352, previously missed). Same-origin
    is the RUNNING server's origin, so an absolute
    `http://127.0.0.1:<port>/app.js` is a path of this plane, as it is to
    the browser (Copilot review of openDox-code#75 at 82869769,
    r4177924129). A reference no parser here can read is never a path. A
    lone surrogate is read first as the browser reads it (`scalar_values`;
    Copilot review of openDox-code#75 at 4bdb41fb, r4178395690)."""
    ref = scalar_values(ref)
    if (_DIVERGENT_REFERENCE.search(ref)
            or _ENCODED_DOT.search(re.split(r"[?#]", ref, maxsplit=1)[0])):
        return DIVERGENT_PREFIX + ref
    try:
        joined = urllib.parse.urljoin(origin + base, ref)
        parts = urllib.parse.urlsplit(joined)
        credentials = parts.username is not None or parts.password is not None
    except ValueError:
        return UNPARSEABLE_PREFIX + ref
    if credentials or "@" in parts.netloc:
        return DIVERGENT_PREFIX + ref
    if _origin_of(joined) != _origin_of(origin):
        return joined
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _external(where: str) -> bool:
    return not where.startswith("/")


def _check_page_resolution(links: "_IndexLinks", origin: str,
                           verdict: Verdict, label: str,
                           page: str = "/") -> None:
    """A `<base>` other than the page's own root, or an import map, would
    send the browser elsewhere than the harness resolves to: refused by
    name (the self-pass after Copilot's review of openDox-code#75 at
    2dcb98d3). So is what the page runs that this harness does not read,
    and a page that runs no module at all (Copilot review of
    openDox-code#75 at 4bdb41fb, r4178395669)."""
    if links.unmodeled:
        verdict.check(f"{label}.bundle.unmodeled", False,
                      f"`/` holds {', '.join(sorted(set(links.unmodeled)))},"
                      " whose parsing this harness does not model, so it "
                      "cannot tell which scripts and links a browser loads")
    for src in links.classic:
        shown = repr(src) if src else "(inline)"
        verdict.check(f"{label}.bundle.classic-script {shown}", False,
                      f"`/` runs {shown} as a CLASSIC script, which this "
                      "harness does not read: a browser runs it as a script, "
                      "not a module, and an import in it is a SyntaxError")
    if links.inline_modules:
        verdict.check(f"{label}.bundle.inline-module", False,
                      f"`/` holds {links.inline_modules} inline module "
                      "script(s), whose imports this harness does not read")
    verdict.check(f"{label}.bundle.entry", bool(links.modules),
                  "`/` loads no live module script (`<script type=\"module\" "
                  "src>`), so a browser runs no application; a view module "
                  "/capabilities declares is no entry, and neither is a "
                  "script inside a <template>, a data block, or one with an "
                  "empty `src`")
    for base in links.bases[:1]:            # only the first one counts
        verdict.check(f"{label}.bundle.base",
                      _resolve(page, base, origin) == "/",
                      "`/` sets a base URL other than its own root (not "
                      "quoted); a browser then resolves the page's links "
                      "against it, and this harness resolves them against "
                      "`/`")
    if links.import_maps:
        verdict.check(f"{label}.bundle.importmap", False,
                      "`/` declares an import map, which this harness does "
                      "not resolve: a browser maps bare specifiers through it "
                      "and may remap relative ones")


def _graph_roots(index_html: str, capabilities: dict,
                 origin: str = _SAME_ORIGIN, verdict: Verdict | None = None,
                 label: str = "", page: str = "/") -> tuple[list, list]:
    links = _IndexLinks()
    links.feed(index_html)
    if verdict is not None:
        _check_page_resolution(links, origin, verdict, label, page)
    # THE DOCUMENT'S BASE URL resolves the page's scripts and stylesheets: a
    # `<base href>`'s, resolved against the page, where it names a path of
    # this plane, and the page's own otherwise (Copilot review of
    # openDox-code#75 at b7b9b843, r4179348414: on `/index.html` with
    # `<base href="/">`, `src="?m=1"` is `/?m=1`).
    base = _resolve(page, links.bases[0], origin) if links.bases else page
    base = base if base.startswith("/") else page
    roots = [(_resolve(base, m, origin), True, "/") for m in links.modules]
    for view in as_list(as_object(capabilities.get("views")).get("views")):
        module = as_object(view).get("module")
        if isinstance(module, str) and module:
            roots.append((_resolve("/", module, origin), True,
                          "/capabilities"))
    return roots, [_resolve(base, sheet, origin) for sheet in links.sheets]


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


#: HTTP whitespace, and an HTTP token, as the MIME Sniffing standard reads a
#: type and a subtype.
_HTTP_WHITESPACE = " \t\r\n"
_HTTP_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def media_type(answer: Answer) -> str:
    """The answer's MIME type essence as a browser parses it (the MIME
    Sniffing standard): HTTP whitespace trimmed, a type and a subtype of
    HTTP token code points, ASCII-lowercased, parameters such as `charset`
    aside. EMPTY where there is none, where it does not parse
    (`text/javascript\\xa0`, which `str.strip` would have trimmed), and
    where `Content-Type` holds more than one value: a browser takes the
    last that parses (Fetch's "extract a MIME type"), and this harness
    does not split them (the self-pass after Copilot's review of
    openDox-code#75 at 4bdb41fb)."""
    value = answer.headers.get("content-type")
    if value is None or "," in value:
        return ""
    essence = value.split(";", 1)[0].strip(_HTTP_WHITESPACE)
    kind, slash, subtype = essence.partition("/")
    if not (slash and _HTTP_TOKEN.fullmatch(kind)
            and _HTTP_TOKEN.fullmatch(subtype)):
        return ""
    return ascii_lower(essence)


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
            verdict.note(f"{path} (dynamic, from {importer}) answers "
                         f"{answer.describe()}: refused, and its importer "
                         "degrades")
    if answer.status == 200:
        # SERVED, so it must be runnable: a module of any other type is
        # refused by the browser as surely as a 404 (Copilot review of
        # openDox-code#75 at f29b4ddd, r4173769822).
        verdict.check(
            f"{label}.bundle.module-type {path}",
            media_type(answer) in JAVASCRIPT_TYPES,
            f"{path}, imported {'statically' if static else 'dynamically'} "
            f"by {importer}, is served as {shown_type(answer)}, which a "
            "browser refuses for a module script")


#: A bare module specifier (`import "child.js"`), marked so: with no import
#: map, a browser resolves only a specifier that starts with `/`, `./` or
#: `../`, or one that is an absolute URL, and throws on any other (the HTML
#: standard's "resolve a module specifier"). The served page has no import
#: map (Copilot review of openDox-code#75 at 27479495, r4174411680).
BARE_PREFIX = "bare:"
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _specifier(importer: str, value: str,
               origin: str = _SAME_ORIGIN) -> str:
    """A module specifier as a browser with no import map resolves it: the
    resolved path or URL, or `bare:<specifier>` where it throws."""
    if value.startswith(("/", "./", "../")) or _URL_SCHEME.match(value):
        return _resolve(importer, value, origin)
    return BARE_PREFIX + value


def _scan_module(path: str, body: bytes, pending: collections.deque,
                 routes: set[str], literals: set[str] | None = None,
                 origin: str = _SAME_ORIGIN) -> tuple[bool, bool]:
    """Queue the module's imports and collect its routes. It is decoded as a
    browser decodes a module script, as UTF-8 with a leading BOM dropped.
    Returns whether it holds a string escape a module refuses
    (`JsStrings.malformed`), and whether a `/` in it stands right after a
    `}` (`JsStrings.ambiguous`)."""
    strings = JsStrings(body.decode("utf-8-sig", "replace"))
    for _quote, value, before in strings.scan():
        if literals is not None:
            literals.add(value)
        if _DYNAMIC_IMPORT_CONTEXT.search(before):
            pending.append((_specifier(path, value, origin), False, path))
        elif _STATIC_IMPORT_CONTEXT.search(before):
            pending.append((_specifier(path, value, origin), True, path))
        elif _PATH_LITERAL.match(value) and not _MODULE_OR_SHEET.search(value):
            routes.add(_resolve("/", value))
    return strings.malformed, strings.ambiguous


def _judge_divergent(where: str, importer: str, how: str, verdict: Verdict,
                     label: str) -> None:
    ref = where[len(DIVERGENT_PREFIX):]
    verdict.check(
        f"{label}.bundle.divergent {ref!r}", False,
        f"{importer} {how} {ref!r}, which a browser reads as another URL "
        "than this harness would, or refuses (a backslash, a tab or newline, "
        "whitespace or a control character at an end, a percent-encoded dot "
        "segment, or user information): refused, never resolved or fetched")


def derive_bundle(port: int, index_html: str, capabilities: dict,
                  verdict: Verdict, label: str,
                  literals: set[str] | None = None, *,
                  host: str = "127.0.0.1",
                  page: str = "/") -> tuple[list[str], int]:
    """Walk the module graph the served `/` loads, fetching each module from
    the server, and return `(routes, modules)`: every same-origin path
    literal the graph names, and how many modules it holds. Every string
    literal of the graph is added to `literals` where one is given."""
    # The page's own origin and path: the browser resolves and asks every
    # module, sheet and route there (Copilot review of openDox-code#75 at
    # 3392f93a, r4179115311).
    origin = plane_origin(port, host)
    roots, sheets = _graph_roots(index_html, capabilities, origin, verdict,
                                 label, page)
    for sheet in sheets:
        if sheet.startswith(DIVERGENT_PREFIX):
            _judge_divergent(sheet, "/", "links the stylesheet", verdict,
                             label)
            continue
        if _external(sheet):
            verdict.check(
                f"{label}.bundle.external {sheet}", False,
                f"`/` links the stylesheet {sheet}, from outside this plane, "
                "which a clean machine with only openDox installed cannot be "
                "assumed to reach")
            continue
        answer = get(port, sheet, host=host)
        verdict.check(f"{label}.bundle.sheet {sheet}", answer.status == 200,
                      f"the stylesheet `/` links answers {answer.describe()}")
        if answer.status == 200:
            # (Copilot review of openDox-code#75 at f29b4ddd, r4173769844.)
            verdict.check(
                f"{label}.bundle.sheet-type {sheet}",
                media_type(answer) == STYLESHEET_TYPE,
                f"the stylesheet `/` links is served as "
                f"{shown_type(answer)}, which a standards-mode page does not "
                "apply as CSS")
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
        if path.startswith(BARE_PREFIX):
            verdict.check(
                f"{label}.bundle.bare {path[len(BARE_PREFIX):]}", False,
                f"{importer} imports {path[len(BARE_PREFIX):]!r} "
                f"{'statically' if static else 'dynamically'} as a bare "
                "specifier, which a browser with no import map refuses; a "
                "relative one starts with `./` or `../`")
            continue
        if path.startswith(DIVERGENT_PREFIX):
            _judge_divergent(path, importer,
                             f"imports {'statically' if static else 'dynamically'}",
                             verdict, label)
            continue
        if _external(path):
            # Never fetched from loopback by its path, where a local file of
            # the same name would answer for it.
            verdict.check(
                f"{label}.bundle.external {path}", False,
                f"{importer} imports {path} "
                f"{'statically' if static else 'dynamically'}, from outside "
                "this plane, which a clean machine with only openDox "
                "installed cannot be assumed to reach")
            continue
        first = path not in answers
        if first:
            answers[path] = get(port, path, host=host)
        answer = answers[path]
        _judge_module(answer, path, static, importer, verdict, label)
        if not (first and answer.status == 200):
            continue
        malformed, ambiguous = _scan_module(path, answer.body, pending,
                                            routes, literals, origin)
        if ambiguous:
            verdict.check(
                f"{label}.bundle.ambiguous-slash {path}", False,
                f"{path} has a `/` right after a `}}`, which divides where the "
                "`}` ends an expression (an object literal, a function or "
                "class expression) and opens a regular expression where it "
                "ends a block; this harness does not tell the two apart, so "
                "it cannot be sure which imports and routes follow")
        if malformed:
            verdict.check(
                f"{label}.bundle.syntax {path}", False,
                f"{path} holds a string escape a module refuses (a legacy "
                "octal escape, `\\8` or `\\9`, or a `\\x` or `\\u` that is "
                "not well formed): a SyntaxError, so a browser loads none "
                "of it")
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
    verdict.note("$ " + " ".join(install[2:]) + (
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
            verdict.note(f"{sock} is another install's private socket "
                         "(its directory admits no other user); no child is "
                         "configured to reach it")
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
        """Where the entry point's output is, for a diagnostic, and never
        the output itself: it may hold the console token, and a diagnostic
        reaches the CI log before the after-stop check could catch a printed
        token (Copilot review of openDox-code#75 at 33841d4a,
        r4174621486). `printed()` still reads the whole output for that
        check."""
        return (f" (the entry point's output is in {self.out} and "
                f"{self.err}, not echoed here because it may hold the console "
                "token; run with --keep to keep it)")

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
    verdict.note("$ " + " ".join(argv))
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


def fetch_object(server: Server, route: str,
                 verdict: Verdict) -> tuple[dict, str]:
    """`route`'s JSON object, and its RAW payload as text."""
    answer = get(server.port, route)
    verdict.require(f"{server.label}.http {route}", answer.status == 200,
                    f"{route} answers {answer.describe()}")
    try:
        body = answer.json()
        parsed = f"it is JSON, a {type(body).__name__}"
    except ValueError:
        body, parsed = None, "it is not JSON"
    # The payload itself is not quoted: it may carry the console token
    # (Copilot review of openDox-code#75 at ec95f451, r4175016672).
    verdict.require(f"{server.label}.{route} is a JSON object",
                    isinstance(body, dict),
                    f"{route} is not a JSON object: {parsed}")
    return body, answer.body.decode("utf-8", "replace")


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
                verdict: Verdict) -> tuple[dict, dict, str]:
    """Step 5: `/`, `/snapshot.json` and `/capabilities`, whose RAW payload
    is returned with it, for step 6's by-value check."""
    label = server.label
    page = index.body.decode("utf-8", "replace")
    encoding = not_utf8_because(index.body,
                                index.headers.get("content-type"))
    verdict.check(f"{label}.http / is UTF-8", encoding is None,
                  f"`/` may be decoded other than as UTF-8, as this harness "
                  f"reads it: {encoding}")
    verdict.check(f"{label}.http / is HTML",
                  "<html" in page.lower()
                  and media_type(index) == "text/html",
                  f"`/` answered {shown_type(index)}, not text/html with an "
                  "<html> element")
    snapshot, _raw = fetch_object(server, "/snapshot.json", verdict)
    documents = snapshot.get("documents")
    verdict.check(f"{label}.snapshot non-empty",
                  isinstance(documents, list) and bool(documents),
                  f"the snapshot's documents are not a non-empty list: they "
                  f"are {'an empty list' if documents == [] else 'a ' + type(documents).__name__} "
                  "(not quoted)")
    # EVERY DOCUMENT NAMES ITS PATH, or `requests_for` would skip its source
    # reads and the run would pass on less than it claims (Copilot review of
    # openDox-code#75 at 33841d4a, r4174621535).
    pathless = [position for position, document
                in enumerate(as_list(documents))
                if not (isinstance(document, dict)
                        and isinstance(document.get("path"), str)
                        and document["path"])]
    verdict.check(f"{label}.snapshot documents each name a path",
                  not pathless,
                  f"the snapshot's documents at {pathless[:10]} are not "
                  "objects with a non-empty string `path`, so no source read "
                  "can be asked for them")
    leaks = sorted({m.group(1) for v in string_values(snapshot)
                    for m in F53_PATTERN.finditer(v.lower())})
    verdict.check(f"{label}.snapshot neutral (F5.3)", not leaks,
                  f"openxFactory's vocabulary leaked into the neutral "
                  f"snapshot: {leaks}")
    verdict.note(f"the snapshot lists "
                 f"{len(as_list(snapshot.get('documents')))} documents")
    caps, caps_raw = fetch_object(server, "/capabilities", verdict)
    # A token `/capabilities` publishes, under its name at any depth, is
    # never printed either, though the check below fails on it (T104;
    # Copilot review of openDox-code#75 at ec95f451, r4175016672).
    for published in values_under_names(caps, CONSOLE_TOKEN_FIELD):
        verdict.keep_secret(published)
    install_block = as_object(caps.get("install"))
    verdict.check(f"{label}.capabilities install.mode == local",
                  install_block.get("mode") == "local",
                  "the served install block reports no mode \"local\" (it "
                  "is not quoted: /capabilities may carry the console "
                  "token)")
    pid = as_object(install_block.get("database_bundle")).get("pid")
    if isinstance(pid, int):
        verdict.note(f"the served install reports its bundled server as "
                     f"pid {pid}")
    check_no_published_token(label, caps, caps_raw, verdict)
    return snapshot, caps, caps_raw


def values_under_names(node, name: str):
    """Every string under a key that contains `name`, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if name in key:
                yield from string_values(value)
            else:
                yield from values_under_names(value, name)
    elif isinstance(node, list):
        for value in node:
            yield from values_under_names(value, name)


def keys_at_any_depth(node):
    """Every key of every JSON object in `node`, however deep."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys_at_any_depth(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys_at_any_depth(value)


def check_no_published_token(label: str, caps: dict, caps_raw: str,
                             verdict: Verdict) -> None:
    """A standalone plane does not publish its console token on
    `/capabilities` (plan 034 T104): any loopback caller, another OS user of
    the machine included, can read that route. BY NAME, at any depth, as
    quickstart.md § 3 asserts it (T007 batch N): `console_token` nowhere in
    the RAW payload, and in no key of the parsed one, however deep or
    however escaped."""
    named = (CONSOLE_TOKEN_FIELD in caps_raw
             or any(CONSOLE_TOKEN_FIELD in key
                    for key in keys_at_any_depth(caps)))
    verdict.check(f"{label}.capabilities carries no console token",
                  not named,
                  f"/capabilities publishes `{CONSOLE_TOKEN_FIELD}` to any "
                  "loopback caller; a standalone plane delivers it only "
                  "through the 0600 opener file (T104, adversarial review "
                  "2's M5)")


def check_no_token_value(label: str, caps: dict, caps_raw: str, token: str,
                         verdict: Verdict) -> None:
    """Step 6's by-value half of step 5's check (T007 batch N; quickstart.md
    § 3): the token the opener delivers is nowhere in `/capabilities`' RAW
    payload, nor in any key or string value of the parsed one, under
    whatever name. Neither the token nor the payload is quoted."""
    carried = (token in caps_raw
               or any(token in text for text in string_values(caps))
               or any(token in key for key in keys_at_any_depth(caps)))
    verdict.check(f"{label}.capabilities carries the opener's token nowhere",
                  not carried,
                  "/capabilities carries the console token the opener "
                  "delivers, under another name or inside a value, to any "
                  "loopback caller (T104; T007 batch N)")


def grouping_field_of(caps: dict) -> str:
    fields = as_object(as_object(caps.get("display")).get("fields"))
    field = as_object(fields.get("grouping")).get("field")
    return field if isinstance(field, str) and field else "clusters"


def check_grouping(label: str, snapshot: dict, caps: dict,
                   verdict: Verdict) -> None:
    """A grouping tile the chat pane can open on: an id and a member
    document (Copilot review of openDox-code#75, at 32ef3e8c)."""
    field = grouping_field_of(caps)
    verdict.check(f"{label}.snapshot fills the grouping station",
                  grouping_tile(snapshot, field) is not None,
                  "the snapshot's grouping station (the field /capabilities "
                  "names, not quoted, nor its value) holds no tile with an id "
                  "and a member document, so no grouping tile can open the "
                  "chat pane (R1Q13 (a) with (c); AT-R1 fails and does not "
                  "skip)")


# ---------------------------------------------------------------------------
# Step 6: the console token, as the user's browser is handed it (T104).
# ---------------------------------------------------------------------------

class _RefreshContents(_LivePage):
    """The `content` of every LIVE `<meta http-equiv="refresh">` in a page,
    unescaped, and the text of every live JSON `<script>` whose id is the
    console record's (`_LivePage`): `http-equiv` is `refresh` exactly
    (ASCII case aside, and no whitespace trimmed)."""

    WATCHED = frozenset({"meta", "script"})

    def __init__(self) -> None:
        super().__init__()
        self.contents: list[str | None] = []
        self.records: list[str] = []
        self._in_record = False

    def live_tag(self, tag, named) -> None:
        if tag == "script":
            self._in_record = (
                named.get("id") == CONSOLE_RECORD_ID
                and ascii_lower(named.get("type", "").strip(_ASCII_WHITESPACE))
                == "application/json")
            if self._in_record:
                self.records.append("")
            return
        equiv = named.get("http-equiv", "")
        if tag == "meta" and ascii_lower(equiv) == "refresh":
            # A named character reference with no `;` is decoded by
            # `html.unescape` and, in an attribute, left as text by a browser
            # where `=` or a letter or digit follows (`&ampconsole_token=`),
            # so the two read different URLs: no URL is read from it.
            raw = self.get_starttag_text() or ""
            self.contents.append(None if _UNTERMINATED_REFERENCE.search(raw)
                                 else named.get("content", ""))

    def closed(self, tag) -> None:
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
    record = _json_or_none(records[0])
    if not isinstance(record, dict):
        return "the opener's record is not a JSON object"
    version = record.get("schema_version")
    problems = []
    if record.get("kind") != CONSOLE_RECORD_KIND or not (
            is_json_number(version)
            and version == CONSOLE_RECORD_SCHEMA_VERSION):
        problems.append(f"it is not {CONSOLE_RECORD_KIND!r} "
                        f"v{CONSOLE_RECORD_SCHEMA_VERSION}")
    if not (is_json_number(record.get("port")) and record.get("port") == port):
        problems.append(f"its port is not {port}")
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


_ASCII_WHITESPACE = " \t\n\f\r"


def refresh_target(content: str | None) -> str | None:
    """The URL a browser's refresh follows from `content`, or `None` where a
    browser follows none: the HTML standard's "shared declarative refresh
    steps", for the forms a refresh takes (`0;url=<target>`, `0; URL='…'`,
    `0,url=…`, `.5;url=…`, `0;<target>`).

    A browser ABORTS the refresh when the first non-whitespace code point is
    neither an ASCII digit nor `.`, so `invalid;url=…` and `-1;url=…` open
    nothing, and a user is left on the opener (Copilot review of
    openDox-code#75 at 5636eb8d, r4173894317). A `content` with no URL part
    refreshes the opener itself, which opens no console either."""
    if content is None:          # unreadable alike (`_RefreshContents`)
        return None
    rest = content.lstrip(_ASCII_WHITESPACE)
    digits = len(rest) - len(rest.lstrip("0123456789"))
    if digits == 0 and not rest.startswith("."):
        return None
    rest = rest[digits:].lstrip("0123456789.")
    rest = rest.lstrip(_ASCII_WHITESPACE)
    if rest[:1] in (";", ","):
        rest = rest[1:]
    rest = rest.lstrip(_ASCII_WHITESPACE)
    if rest[:3].lower() == "url":
        after = rest[3:].lstrip(_ASCII_WHITESPACE)
        if after.startswith("="):
            rest = after[1:].lstrip(_ASCII_WHITESPACE)
    if rest[:1] in ("'", '"'):
        quote, rest = rest[0], rest[1:]
        rest = rest.split(quote, 1)[0]
    target = rest.strip(_ASCII_WHITESPACE)
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


def _writable_by(mode: int) -> str:
    return "every user" if mode & 0o002 else "its group"


def directory_unsafe_because(info: os.stat_result, *, own: bool) -> str | None:
    """Why one directory on a private file's path lets another user replace
    what lies below it, or `None`. The rules T104's opener writer holds its
    own tree to (`opendox.console_access._unsafe_because`, the bundle's,
    copied), asked again here of what the run left: a directory of the
    state tree (`own`) is a real directory, this user's, that no one else
    can write; one above it is this user's or root's, and sticky where
    others can write it."""
    mode = info.st_mode
    if stat.S_ISLNK(mode):
        return "is a symbolic link"
    if not stat.S_ISDIR(mode):
        return "is not a directory"
    if own:
        if info.st_uid != os.getuid():
            return f"is owned by uid {info.st_uid}, not by this user"
        if mode & 0o022:
            return (f"is writable by {_writable_by(mode)} "
                    f"(mode {stat.S_IMODE(mode):o})")
        return None
    if info.st_uid not in (os.getuid(), 0):
        return f"is owned by uid {info.st_uid}, neither this user nor root"
    if mode & 0o022 and not mode & stat.S_ISVTX:
        return (f"is writable by {_writable_by(mode)} and is not sticky "
                f"(mode {stat.S_IMODE(mode):o})")
    return None


def tree_unsafe_because(state: Path) -> tuple[Path, str] | None:
    """`(directory, why)` for the first directory on `state`'s path that
    lets another user replace what lies below it, or `None`: `state` itself
    by the state tree's rule, every directory above it, as written and as
    resolved, by the rule for the directories above, and every symbolic link
    on the way, which must be this user's or root's, as T104 holds its own
    tree (Copilot review of openDox-code#75 at 4809b3d2, r4174671426)."""
    try:
        for component in (state, *state.parents):
            info = os.lstat(component)
            if stat.S_ISLNK(info.st_mode) and info.st_uid not in (os.getuid(),
                                                                  0):
                return component, (f"is a symbolic link owned by uid "
                                   f"{info.st_uid}, neither this user nor "
                                   "root, who could point it elsewhere")
        reason = directory_unsafe_because(os.lstat(state), own=True)
        if reason is not None:
            return state, reason
        resolved = Path(os.path.realpath(state))
        for directory in dict.fromkeys([*state.parents, *resolved.parents]):
            reason = directory_unsafe_because(os.stat(directory), own=False)
            if reason is not None:
                return directory, reason
    except OSError as exc:
        return state, (f"cannot be examined ({type(exc).__name__}: "
                       f"{exc.strerror})")
    return None


def opener_unsafe_because(path: Path) -> tuple[Path, str] | None:
    """`(where, why)` for the first reason `path` is not a private opener,
    or `None`: this user's regular file, mode exactly 0600, with one link,
    in this user's own directory, mode exactly 0700, under a
    state directory and ancestors no other user can change. `where` is the
    file or the directory at fault, and no reason quotes a path, so a
    caller decides whether it may quote `where`."""
    try:
        info = os.lstat(path)
        directory = os.lstat(path.parent)
    except OSError as exc:
        return path, f"cannot be examined ({type(exc).__name__}: {exc.strerror})"
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
    if reason is not None:
        return path, reason
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != uid:
        return path.parent, "is not this user's own directory"
    if stat.S_IMODE(directory.st_mode) != OPENER_DIRECTORY_MODE:
        return path.parent, (f"has mode {stat.S_IMODE(directory.st_mode):o}, "
                             f"not {OPENER_DIRECTORY_MODE:o}, as quickstart.md "
                             "§ 3 checks it")
    return tree_unsafe_because(path.parent.parent)


def _read_without_following(path: Path,
                            limit: int = OPENER_READ_LIMIT) -> bytes:
    """The file at `path`, opened without following a link and WITHOUT
    BLOCKING, and read only if what opened is a regular file: a FIFO with no
    writer would otherwise hang the harness before its verdict and its
    cleanup (Copilot review of openDox-code#75 at 27479495, previously
    missed). Read WHOLE, or refused: a file past `limit` bytes is an error,
    never a truncated page whose checks would judge only its first part,
    while a browser reads it all (Copilot review of openDox-code#75 at
    82869769, r4177924060)."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(descriptor, limit + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        os.close(descriptor)
    if size > limit:
        raise OSError(errno.EFBIG, f"larger than the {limit} bytes this "
                      "harness reads whole")
    return b"".join(chunks)


def _within(path: Path, root: Path) -> bool:
    real = Path(os.path.realpath(path))
    return real.is_relative_to(Path(os.path.realpath(root)))


#: What a browser's URL parser reads differently from `urllib.parse`, so a
#: forward carrying it is refused before it is parsed at all: a backslash,
#: which a browser reads as `/` in an http URL (`http://evil\@127.0.0.1/`
#: goes to `evil`), and whitespace and control characters, which a browser
#: strips or rejects.
_UNPARSED_ALIKE = re.compile(r"[\\\x00-\x20\x7f]")


def served_loopback_hosts(port: int) -> tuple[str, ...]:
    """The loopback hosts the launched plane answers on: `127.0.0.1` and
    `::1` each where something listens on `port`, and `localhost`, which a
    browser resolves to either, where one does."""
    hosts = [host for host in ("127.0.0.1", "::1") if listening(host, port)]
    return (*hosts, "localhost") if hosts else ()


def token_in_fragment(targets: list[str | None], port: int,
                      hosts: tuple[str, ...]) -> tuple[str | None, str]:
    """The token the opener's one forward carries in its FRAGMENT, or `None`
    and why not. No message here quotes a token, or any part of the URL,
    which could hold one (Copilot review of openDox-code#75 at d53a7378,
    r4173842794)."""
    if len(targets) != 1 or targets[0] is None:
        return None, (f"the opener has {len(targets)} meta-refresh forwards, "
                      "not one a browser follows to a URL (a delay that "
                      "does not start with a digit or `.` aborts it, and a "
                      "named character reference with no `;` reads "
                      "differently in a browser)")
    answering = " and ".join(hosts) or "no host"
    elsewhere = (f"the opener does not forward to this plane on loopback "
                 f"port {port}, which answers on {answering} (its forward is "
                 "not quoted, because it may hold the token)")
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
    # A loopback host the LAUNCHED plane answers on: a forward to `[::1]`
    # reaches nothing where the plane listens on 127.0.0.1 alone (Copilot
    # review of openDox-code#75 at 142d1352, previously missed).
    if (parts.scheme != "http" or parts.hostname not in LOOPBACK_HOSTS
            or parts.hostname not in hosts or target_port != port):
        return None, elsewhere
    # THE CONSOLE PAGE, and no other page of this plane: a forward to
    # `/missing.html` or `/snapshot.json` opens no console, though every
    # later check asks `/` and the catalog itself (Copilot review of
    # openDox-code#75 at 486e426e, previously missed).
    # (An empty path is `/` to a browser, as the URL standard reads it.)
    if (parts.path or "/") not in CONSOLE_PAGES:
        return None, (f"the opener's forward opens a page other than the "
                      f"console ({' or '.join(CONSOLE_PAGES)}) of this plane "
                      "(the path is not quoted, because it may hold the "
                      "token)")
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
    # THE TOKEN THE PAGE ACCEPTS, or the harness could authenticate where the
    # user's page cannot: T104's `takeDeliveredConsoleToken`
    # (`web/views/notebook.js`) discards any other value (Copilot review of
    # openDox-code#75 at 5636eb8d, r4173894352).
    if not CONSOLE_TOKEN_SHAPE.fullmatch(values[0]):
        return None, ("the opener's forward carries a token the page "
                      "discards: `takeDeliveredConsoleToken` accepts only "
                      f"{CONSOLE_TOKEN_SHAPE.pattern} (the value is not "
                      "quoted)")
    # Decoded too, as often as it decodes: a percent-encoded copy in the path
    # or the query still reaches the request line and the server's log, and
    # is recovered from them (Copilot review of openDox-code#75 at 142d1352,
    # r4174355680).
    if any(values[0] in form for part in (parts.path, parts.query)
           for form in _decodings(part)):
        return None, ("the opener's forward carries the token outside its "
                      "fragment too, perhaps percent-encoded (the copy is "
                      "not quoted)")
    return values[0], ""


def opener_unread_because(page: bytes,
                          contents: "_RefreshContents") -> str | None:
    """Why this harness cannot read the opener as the user's browser reads
    it, or `None`: an encoding other than UTF-8, or markup it does not model
    (`_LivePage.unmodeled`). Either is a named failure of the forward check,
    never a reading by approximation (the self-pass after Copilot's review
    of openDox-code#75 at 4bdb41fb)."""
    encoding = not_utf8_because(page, None)
    if encoding:
        return (f"the opener may be decoded other than as UTF-8, as this "
                f"harness reads it: {encoding}")
    if contents.unmodeled:
        return (f"the opener holds "
                f"{', '.join(sorted(set(contents.unmodeled)))}, whose "
                "parsing this harness does not model, so it cannot tell "
                "which refresh a browser follows")
    return None


def _json_or_none(text: str):
    """`text` parsed as JSON, or `None` where it is not JSON or nests past
    the parser's depth, which is the product's output and so a named
    failure, never a harness error."""
    try:
        return strict_json(text)
    except (ValueError, RecursionError):
        return None


def carried_tokens(targets: list[str | None], records: list[str]) -> list[str]:
    """Every value the opener carries under `console_token`: in any
    forward's fragment or query, or in any of its records, delivered or
    refused. Each may be this plane's token, so `Verdict.keep_secret` keeps
    them all out of every line the harness prints."""
    found: list[str] = []
    for target in filter(None, targets):
        try:
            parts = urllib.parse.urlsplit(target)
        except ValueError:
            continue
        for part in (parts.fragment, parts.query):
            found += urllib.parse.parse_qs(part, keep_blank_values=True).get(
                CONSOLE_FRAGMENT_KEY, [])
    for text in records:
        value = as_object(_json_or_none(text)).get(CONSOLE_FRAGMENT_KEY)
        if isinstance(value, str):
            found.append(value)
    return found


def _decodings(text: str, rounds: int = 5) -> set[str]:
    """`text` and every percent-decoding of it (with `+` read as a space, and
    not), repeated until nothing new appears, at most `rounds` deep."""
    forms, frontier = {text}, [text]
    for _ in range(rounds):
        frontier = [decoded for form in frontier
                    for decoded in (urllib.parse.unquote(form),
                                    urllib.parse.unquote_plus(form))
                    if decoded not in forms]
        if not frontier:
            break
        forms.update(frontier)
    return forms


def check_console_opener(label: str, port: int, printed: str, state_dir: Path,
                         served_root: Path, verdict: Verdict, *,
                         hosts: tuple[str, ...],
                         forward: list[str] | None = None,
                         ) -> tuple[Path | None, str | None]:
    """Step 6: the opener the start printed, and the token its forward
    carries, read from the file as the user's browser reads it. Where the
    forward is the one a browser follows to this plane's console page, it
    is appended to `forward`, for `check_console_page`."""
    path = opener_location(printed)
    verdict.check(f"{label}.console opener printed", path is not None,
                  "the start printed no `console <file URL>` line naming the "
                  "opener, so a user has no way to open the console page")
    if path is None:
        return None, None
    expected = state_dir / CONSOLE_DIRNAME / f"{port}.html"
    here = path == expected
    verdict.check(f"{label}.console opener is OPENDOX_STATE_DIR/console/<port>.html",
                  here, f"the start printed another path, not {expected} (the "
                  "printed path is not quoted here or below: it is the entry "
                  "point's output, which may hold the console token)")

    def shown(where: Path) -> str:
        # The printed path is the entry point's output, so it is quoted, and
        # so is a directory on it, only where it is the path this run made
        # (Copilot review of openDox-code#75 at 33841d4a, r4174621486).
        if here:
            return str(where)
        return ("the printed opener" if where == path
                else "a directory on the printed opener's path")

    verdict.check(f"{label}.console opener is outside the served repository",
                  not _within(path, served_root),
                  f"{shown(path)} is inside the served repository "
                  f"{served_root}")
    unsafe = opener_unsafe_because(path)
    verdict.check(f"{label}.console opener is private", unsafe is None,
                  f"{shown(unsafe[0])} {unsafe[1]}" if unsafe else "")
    try:
        page = _read_without_following(path)
    except OSError as exc:
        verdict.check(f"{label}.console opener forwards with the token in its "
                      "fragment", False,
                      f"{shown(path)} cannot be read ({type(exc).__name__}: "
                      f"{exc.strerror})")
        return path, None
    contents = _RefreshContents()
    contents.feed(page.decode("utf-8", "replace"))
    contents.close()
    targets = [refresh_target(content) for content in contents.contents]
    # Every token the opener carries, delivered or refused, is never printed
    # from here on, whatever answer or path later echoes it.
    for carried in carried_tokens(targets, contents.records):
        verdict.keep_secret(carried)
    unread = opener_unread_because(page, contents)
    token, why = ((None, unread) if unread
                  else token_in_fragment(targets, port, hosts))
    verdict.check(f"{label}.console opener forwards with the token in its "
                  "fragment", token is not None, why)
    if token is not None:
        disagrees = record_disagrees_because(contents.records, port,
                                             targets[0], token)
        verdict.check(f"{label}.console opener record agrees with its forward",
                      disagrees is None, disagrees or "")
    if token is not None and forward is not None:
        forward.append(targets[0])
    return path, token


def console_page_of(target: str) -> tuple[str, str]:
    """`(host, page)` of a forward `token_in_fragment` has validated: its
    loopback host, and its path and query without the fragment, as a
    browser requests it."""
    parts = urllib.parse.urlsplit(target)
    return (parts.hostname or "127.0.0.1",
            (parts.path or "/") + (f"?{parts.query}" if parts.query else ""))


def check_console_page(server: Server, target: str,
                       verdict: Verdict) -> tuple[Answer, str, str]:
    """Step 6's PAGE: the one the opener's forward opens, asked as the
    browser asks it, of the forward's own host with its path and query.
    It must answer 200 as HTML, and be UTF-8; its module graph and the
    routes are then read from it, at its origin, never from `/` in its
    place (Copilot review of openDox-code#75 at 3392f93a, r4179115311).
    Returns `(answer, host, page)`. The query is not quoted: it is the
    product's output."""
    label = server.label
    host, page = console_page_of(target)
    shown = f"{urllib.parse.urlsplit(target).path or '/'} on {host}"
    answer = get(server.port, page, host=host)
    body = answer.body.decode("utf-8", "replace")
    verdict.check(f"{label}.console page is HTML",
                  answer.status == 200 and media_type(answer) == "text/html"
                  and "<html" in body.lower(),
                  f"the page the opener forwards to, {shown}, answers "
                  f"{answer.describe()} as {shown_type(answer)}, not "
                  "text/html with an <html> element, so the user's browser "
                  "opens no console there")
    encoding = not_utf8_because(answer.body,
                                answer.headers.get("content-type"))
    verdict.check(f"{label}.console page is UTF-8", encoding is None,
                  f"the page the opener forwards to, {shown}, may be decoded "
                  f"other than as UTF-8, as this harness reads it: {encoding}")
    return answer, host, page


def check_catalog(server: Server, token: str | None, verdict: Verdict, *,
                  host: str = "127.0.0.1") -> None:
    """Step 7: the catalog, asked as the console, offers nothing available,
    and asked without the token, refuses."""
    label = server.label
    bare = get(server.port, CATALOG_ROUTE, host=host)
    verdict.check(f"{label}.catalog refuses a caller without the console token",
                  bare.status is not None and 400 <= bare.status < 500,
                  f"{CATALOG_ROUTE} without the token answers "
                  f"{bare.describe()}, so the token the opener carries would "
                  "guard nothing")
    catalog = get(server.port, CATALOG_ROUTE, token=token, host=host)
    asked = ("with the console token" if token else
             "with no console token to present (step 6 found none)")
    # No reason here quotes the catalog's body: it answers a request that
    # carries the token, so it may echo it, escaped in ways no literal
    # redaction finds (Copilot review of openDox-code#75 at 82869769,
    # r4177924097).
    verdict.check(f"{label}.catalog answers", catalog.status == 200,
                  f"{CATALOG_ROUTE} {asked} answers "
                  f"{catalog.describe()} (its body is not quoted)")
    if catalog.status != 200:
        return
    # The payload's SHAPE is a named check, never a harness error: `[]`,
    # `null` or `{"models": 1}` fail `catalog is a catalog` (Copilot review
    # of openDox-code#75, r4170450491).
    try:
        payload = catalog.json()
        shape = (f"its `models` is a {type(payload['models']).__name__}"
                 if isinstance(payload, dict) and "models" in payload else
                 f"it is JSON, a {type(payload).__name__}")
    except ValueError:
        payload, shape = None, "it is not JSON"
    models = as_object(payload).get("models")
    verdict.check(f"{label}.catalog is a catalog", isinstance(models, list),
                  f"{CATALOG_ROUTE} answered no models[]: {shape} (its body "
                  "is not quoted)")
    # THE ENVELOPE THE RAIL ADOPTS, or it shows "the catalog could not be
    # read" and never its no-model state (Copilot review of
    # openDox-code#75, at f0e0ffe1). JavaScript's `=== 1` admits no `true`
    # and no `"1"`, so neither does this. It admits every JSON NUMBER equal to
    # 1, though: `1.0` and `1e0` parse to the same JavaScript number, and
    # Python reads them as the float 1.0 (Copilot review of #75 at 1c0ff975,
    # r4173473346).
    envelope = as_object(payload)
    version = envelope.get("schema_version")
    # No reason quotes a value the catalog sent: a token in it, percent- or
    # otherwise encoded, would pass any literal redaction (Copilot review of
    # openDox-code#75 at ba216f84, r4178913911).
    version_ok = (is_json_number(version)
                  and version == CATALOG_SCHEMA_VERSION)
    kind_ok = envelope.get("kind") == CATALOG_KIND
    wrong = [part for part, ok in (("schema_version", version_ok),
                                   ("kind", kind_ok)) if not ok]
    verdict.check(f"{label}.catalog envelope is the one the chat rail adopts",
                  not wrong,
                  f"the catalog's {' and '.join(wrong)} is not what the chat "
                  f"rail adopts (schema_version={CATALOG_SCHEMA_VERSION}, "
                  f"kind={CATALOG_KIND!r}); the values it sent are not "
                  "quoted")
    # As the rail reads it: `m.available === true`, and nothing else
    # (`views/doxbench-chat-model.js`).
    available = [as_object(m).get("model_id") for m in as_list(models)
                 if as_object(m).get("available") is True]
    verdict.check(f"{label}.catalog offers no available entry", not available,
                  f"no model is configured, yet the catalog offers "
                  f"{len(available)} available entr"
                  f"{'y' if len(available) == 1 else 'ies'} (the ids are not "
                  "quoted)")


def grouping_tile(snapshot: dict,
                  grouping_field: str) -> tuple[str, str] | None:
    """`(tile id, member document)` for the first grouping tile that has a
    member document: the tile the chat pane opens from."""
    for group in map(as_object, as_list(snapshot.get(grouping_field))):
        if not group.get("id"):
            continue
        members = [edge.get("document") for edge in
                   map(as_object, as_list(group.get("document_edges")))
                   if edge.get("document")]
        if members:
            return str(group["id"]), str(members[0])
    return None


def requests_for(routes: list[str], snapshot: dict) -> list[str]:
    """Every route literal, and every `/`-ended one completed with each
    document the snapshot lists. No thread read is completed with a query:
    a standalone plane's rail sends none (`check_no_thread_read`)."""
    documents = [urllib.parse.quote(scalar_values(str(d["path"])))
                 for d in map(as_object, as_list(snapshot.get("documents")))
                 if d.get("path")]
    key = urllib.parse.quote(
        scalar_values(f"{snapshot.get('repository') or ''}@main"), safe="")
    targets: list[str] = []
    for route in routes:
        targets.append(route)
        if route.endswith("/"):
            targets += [route + doc for doc in documents]
            targets += [f"{route}{key}/{doc}" for doc in documents]
    return targets


def session_bindings(caps: dict) -> list[dict]:
    """The contributed view bindings `/capabilities` declares under the
    branch-session column's id, as the shell's `resolveView` finds them."""
    views = as_list(as_object(caps.get("views")).get("views"))
    return [view for view in map(as_object, views)
            if view.get("id") == SESSION_BINDING_ID]


def check_no_thread_read(label: str, caps: dict, verdict: Verdict) -> None:
    """The chat rail reads a thread only through a branch-session column
    (openDox-code#85; holder ruling F1 (i)), and a standalone plane
    contributes none, so its rail sends no thread read and this harness asks
    none. A binding whose `requires` would leave it unresolved still counts
    here: the check fails closed."""
    verdict.check(f"{label}.chat rail reads no thread (no branch session)",
                  not session_bindings(caps),
                  f"/capabilities contributes `{SESSION_BINDING_ID}`, so the "
                  f"chat rail reads {THREAD_ROUTE} on every switch of its "
                  "document; a standalone plane has no branch session, and "
                  "answers each such read 403 with a console error "
                  "(openDox-code#85, the T102 follow-on)")


def check_routes(server: Server, index: Answer, snapshot: dict, caps: dict,
                 token: str | None, verdict: Verdict, *,
                 host: str = "127.0.0.1", page: str = "/") -> None:
    """Step 8: every route the served bundle names answers, below 5xx. The
    bundle is the one `index` loads, the page at `page` on `host` (the one
    the opener opens), and every request goes to that origin."""
    label = server.label
    literals: set[str] = set()
    routes, modules = derive_bundle(server.port,
                                    index.body.decode("utf-8", "replace"),
                                    caps, verdict, label, literals,
                                    host=host, page=page)
    verdict.note(f"derived from the served bundle: {modules} modules, "
                 f"{len(routes)} routes: {', '.join(routes)}")
    verdict.check(f"{label}.bundle names the catalog route",
                  CATALOG_ROUTE in routes,
                  f"the served bundle no longer names {CATALOG_ROUTE}, so "
                  "this harness's catalog step asks the wrong route")
    verdict.check(f"{label}.bundle names the catalog kind",
                  CATALOG_KIND in literals,
                  f"the served bundle no longer names {CATALOG_KIND!r}, so "
                  "this harness's catalog envelope check is stale")
    check_no_thread_read(label, caps, verdict)
    for target in requests_for(routes, snapshot):
        answer = get(server.port, target, token=token, host=host)
        verdict.note(f"GET {target} -> {answer.describe()}")
        dropped = ("; a dropped connection is a handler that raised"
                   if answer.status is None
                   and not (answer.error or "").endswith(REDIRECTED) else "")
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
    # EXIT STATUS 0, as `tests_runtime/test_bundled_postgres.py` requires of
    # the same stop: a server that fails its own shutdown has not stopped
    # cleanly, whatever it removed first (Copilot review of openDox-code#75
    # at 142d1352, previously missed).
    verdict.check(f"{label}.stop exits 0", rc == 0,
                  f"the server did not exit within {STOP_TIMEOUT_SECONDS:.0f}s "
                  "of SIGTERM" if rc is None else
                  f"the server exited rc={rc} after SIGTERM, not 0")
    verdict.note(f"the entry point exited rc={rc}")
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
                      "the opener the start printed is still there after the "
                      "server stopped, and its token was this serve's")
    if token is not None:
        verdict.check(f"{label}.console token never printed",
                      token not in printed,
                      "the entry point printed the console token itself; "
                      "it prints only the opener's path")


def learn_opener_tokens(printed: str, verdict: Verdict) -> None:
    """Every token the opener carries, kept out of every line BEFORE step 5
    quotes anything a route answered, so a payload that carries the token
    under any name prints none of it (Copilot review of openDox-code#75 at
    ec95f451, r4175016672). It only reads the opener, as step 6 reads it,
    and judges nothing: step 6 does, in its place. The entry point writes
    the opener before it serves (`console_access.publish`), so it is there
    once `/` has answered."""
    path = opener_location(printed)
    if path is None:
        return
    try:
        page = _read_without_following(path)
    except OSError:
        return
    contents = _RefreshContents()
    contents.feed(page.decode("utf-8", "replace"))
    contents.close()
    targets = [refresh_target(content) for content in contents.contents]
    for carried in carried_tokens(targets, contents.records):
        verdict.keep_secret(carried)


def serve_one(label: str, repo: Path, ctx: Context, verdict: Verdict) -> None:
    """Steps 4-9 for one repository: start, fetch, stop, and look."""
    server, index = launch(label, repo, ctx, verdict)
    learn_opener_tokens(server.printed(), verdict)
    snapshot, caps, caps_raw = check_pages(server, index, verdict)
    check_grouping(label, snapshot, caps, verdict)
    forward: list[str] = []
    opener, token = check_console_opener(
        label, server.port, server.printed(), ctx.state_dir, repo, verdict,
        hosts=served_loopback_hosts(server.port), forward=forward)
    # The page the user's browser opens is the forward's, not `/`: the
    # catalog, the module graph and the routes are read from it, at its
    # origin. With no forward to follow (a failure already named), `/`.
    console, host, page = index, "127.0.0.1", "/"
    if forward:
        console, host, page = check_console_page(server, forward[0], verdict)
    if token is not None:
        check_no_token_value(label, caps, caps_raw, token, verdict)
    check_catalog(server, token, verdict, host=host)
    check_routes(server, console, snapshot, caps, token, verdict, host=host,
                 page=page)
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
    # THE STATE TREE STARTS PRIVATE, so step 6's verdict on it judges what
    # the product made of it, never where TMPDIR happened to point.
    unsafe = tree_unsafe_because(state_dir)
    if unsafe is not None:
        shutil.rmtree(scratch, ignore_errors=True)
        shutil.rmtree(state_dir, ignore_errors=True)
        raise HarnessError(
            f"{unsafe[0]} {unsafe[1]}, so another user could replace the "
            f"console opener under OPENDOX_STATE_DIR {state_dir}; set TMPDIR "
            "to a directory only you can change")
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
        print(verdict.redact(traceback.format_exc()), end="",
              file=sys.stderr, flush=True)
        error = "the harness raised before a verdict"
    finally:
        cleanup(ctx, args.keep)
    if error is not None:
        print("\nAT-R1 HTTP half: ERROR: " + printable(verdict.redact(error)),
              flush=True)
        return 2
    return verdict.report()


if __name__ == "__main__":
    sys.exit(main())
