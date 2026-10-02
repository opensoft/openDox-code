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
    of the four siblings (`openxdox`, `ideation_dashboard`,
    `doc_health`, `corpus_adapter_openxfactory`) is importable; `omp` (the
    harness the product names, `doxbench_bridge.HARNESS_COMMAND`) is not on
    the PATH; no identity broker (`openprofiler-broker`, the one that exists)
    is on the PATH and no issuer is set; no database answers on PostgreSQL's
    default port or socket and no DSN is set; and neither repository holds a
    model binding (`doxbench_binding.bindings_path`).
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
    (a) with (c)) and `/capabilities` (`install.mode == "local"`).
 6. FETCHES THE MODEL CATALOG, presenting `/capabilities`' `console_token` in
    `X-XF-Console-Token`, and it must answer with no available entry (16.4).
 7. FETCHES EVERY ROUTE THE PANES CAN REQUEST, and none may answer 5xx or
    drop the connection. The list is DERIVED from the served bundle, not kept
    here: see `derive_bundle` below.
 8. STOPS THE SERVER (SIGTERM to the entry point alone, as `kill` would), and
    asserts that no bundled PostgreSQL process is left running (R1Q16 (iv)).

HOW THE ROUTE LIST IS DERIVED (`derive_bundle`). From the RUNNING server, not
from the source tree: `/` is fetched, its `<script type="module">` and
stylesheet links are followed, and every module's static `import`/`export …
from` specifiers are followed in turn, with each literal dynamic `import("…")`
and each view-binding module `/capabilities` declares. That is the module
graph a browser loads. Every module is fetched from the server under test:
a static import must answer 200, since a failed one is a module-load
`pageerror`, which AT-R1 step 8 forbids and no declaration can excuse; a
dynamic import may be refused (10.2a's `intent-feed.js` is not owed, and its
importer degrades), but never with a 5xx. Then, in every module of that graph,
with comments stripped, every string literal that is a same-origin path (a
leading `/` or `./` and a letter, not a module or stylesheet) is a route the
bundle can request. A static read cannot tell which of them fire on load and
which on a click, so ALL of them are requested, a superset of the three
panes' load-time reads. The action routes (`/actions/…`) are requested with a
GET too, which never executes them (a GET there finds no handler, and their
POST is a user's act, not a load). Two kinds take values the panes fill from
the snapshot, and the harness fills them the same way:
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
   whose first member is the `document`;
Every request carries the console token, as the doxBench transports do, so
a guarded read answers from its handler rather than from the console check.

Run it from an openDox-code checkout: `python3 acceptance/at_r1_http.py`.
It needs Linux (it reads `/proc`), `git`, and network access to the package
index. `--help` lists its options. The standard library only: it runs before,
and outside, the environment it builds.
"""

from __future__ import annotations

import argparse
import html.parser
import http.client
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
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

#: The console-presence header the doxBench transports carry (`app.js`).
CONSOLE_TOKEN_HEADER = "X-XF-Console-Token"

#: The model-catalog route (`app.js` `CATALOG_ROUTE`), which the derived list
#: must also name, so this constant cannot drift from the bundle unseen.
CATALOG_ROUTE = "/workbench/model-catalog"

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

#: The bundled server's socket is `<OPENDOX_STATE_DIR>/postgres/run/.s.PGSQL.5432`
#: (`runtime/config.py`'s `BUNDLE_SOCKET_DIR` and `BUNDLE_PORT`), and Linux
#: takes a socket path of at most 107 bytes (`UNIX_SOCKET_PATH_MAX`). The
#: product refuses a longer one by name; the harness keeps its own state
#: directory short, and refuses to start a run that could not fit.
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


def note(text: str) -> None:
    print(f"      {text}", flush=True)


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


def bundled_server_processes(server_dir: Path | None,
                             state_dir: Path) -> list[str]:
    """Every live process that is this install's bundled server: its
    executable lies in the venv's server package, or its command line names
    the fresh state directory. Read at the operating system, not from the
    product's own report. A zombie has exited, so it is not running."""
    found = []
    state = str(state_dir.resolve())
    server = str(server_dir.resolve()) if server_dir else None
    for entry in Path("/proc").iterdir():
        pid = entry.name
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        if _proc_state(pid) in ("Z", "X", "?"):
            continue
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe = ""
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            command = " ".join(a.decode("utf-8", "replace") for a in argv if a)
        except OSError:
            command = ""
        if (server and exe.startswith(server + os.sep)) or state in command:
            found.append(f"pid {pid}: {command or exe}")
    return found


def stop_processes(pids: list[int]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = []
        for pid in pids:
            try:
                os.kill(pid, sig)
                alive.append(pid)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
        if not alive:
            return
        time.sleep(3.0)
        pids = [p for p in alive if Path(f"/proc/{p}").exists()
                and _proc_state(str(p)) not in ("Z", "X")]


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

_REGEX_AFTER_WORDS = {"return", "typeof", "instanceof", "in", "of", "new",
                      "delete", "void", "throw", "case", "do", "else",
                      "yield", "await"}


def js_strings(source: str) -> list[tuple[str, str, str]]:
    """The string literals of a JavaScript module, comments and regular
    expressions excluded: `(quote, value, preceding code)` for each, where
    the preceding code is the last 40 characters of code before it, so an
    import specifier can be told from an ordinary string. A template
    literal's value is its leading static text, before any `${`."""
    out: list[tuple[str, str, str]] = []
    code: list[str] = []
    i, n = 0, len(source)
    last_significant = ""

    def recent() -> str:
        return "".join(code[-40:])

    while i < n:
        c = source[i]
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            j = source.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "*":
            j = source.find("*/", i + 2)
            i = n if j < 0 else j + 2
            code.append(" ")
            continue
        if c == "/":
            word = re.search(r"([A-Za-z_$][\w$]*)\s*$", recent())
            prev = last_significant
            regex = (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^"
                     or (word is not None and prev.isalnum()
                         and word.group(1) in _REGEX_AFTER_WORDS))
            if regex:
                j, in_class = i + 1, False
                while j < n:
                    ch = source[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        break
                    elif ch == "\n":
                        break
                    j += 1
                j += 1
                while j < n and (source[j].isalnum() or source[j] == "_"):
                    j += 1
                code.append(" re ")
                last_significant = "e"
                i = j
                continue
        if c in "\"'":
            j, buf = i + 1, []
            while j < n and source[j] != c and source[j] != "\n":
                if source[j] == "\\" and j + 1 < n:
                    buf.append(source[j + 1])
                    j += 2
                    continue
                buf.append(source[j])
                j += 1
            out.append((c, "".join(buf), recent()))
            code.append(" s ")
            last_significant = "s"
            i = j + 1
            continue
        if c == "`":
            j, buf, static = i + 1, [], True
            depth = 0
            while j < n:
                ch = source[j]
                if depth == 0 and ch == "\\" and j + 1 < n:
                    if static:
                        buf.append(source[j + 1])
                    j += 2
                    continue
                if depth == 0 and ch == "`":
                    break
                if depth == 0 and source.startswith("${", j):
                    static = False
                    depth = 1
                    j += 2
                    continue
                if depth > 0:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                    j += 1
                    continue
                if static:
                    buf.append(ch)
                j += 1
            out.append(("`", "".join(buf), recent()))
            code.append(" s ")
            last_significant = "s"
            i = j + 1
            continue
        code.append(c)
        if not c.isspace():
            last_significant = c
        i += 1
    return out


_STATIC_IMPORT_CONTEXT = re.compile(
    r"(?:\bimport\s*|\bfrom\s*)$")
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
    path = urllib.parse.urljoin("http://loopback" + base, ref)
    parts = urllib.parse.urlsplit(path)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def derive_bundle(port: int, index_html: str, capabilities: dict,
                  verdict: Verdict, label: str) -> tuple[list[str], int]:
    """Walk the module graph the served `/` loads, fetching each module from
    the server, and return `(routes, modules)`: every same-origin path
    literal the graph names, and how many modules it holds."""
    links = _IndexLinks()
    links.feed(index_html)
    pending: list[tuple[str, bool, str]] = [
        (_resolve("/", m), True, "/") for m in links.modules]
    for view in ((capabilities.get("views") or {}).get("views") or []):
        module = view.get("module") if isinstance(view, dict) else None
        if isinstance(module, str) and module:
            pending.append((_resolve("/", module), True, "/capabilities"))
    for sheet in links.sheets:
        answer = get(port, _resolve("/", sheet))
        verdict.check(f"{label}.bundle.sheet {sheet}", answer.status == 200,
                      f"the stylesheet `/` links answers {answer.describe()}")
    seen: set[str] = set()
    routes: set[str] = set()
    modules = 0
    while pending:
        path, static, importer = pending.pop(0)
        if path in seen:
            continue
        seen.add(path)
        answer = get(port, path)
        if static:
            verdict.check(
                f"{label}.bundle.module {path}", answer.status == 200,
                f"{path}, imported statically by {importer}, answers "
                f"{answer.describe()}; a failed static import is a "
                "module-load pageerror (AT-R1 step 8)")
        else:
            verdict.check(
                f"{label}.bundle.dynamic {path}",
                answer.status is not None and answer.status < 500,
                f"{path}, imported dynamically by {importer}, answers "
                f"{answer.describe()}")
            if answer.status != 200:
                note(f"{path} (dynamic, from {importer}) answers "
                     f"{answer.describe()}: refused, and its importer "
                     "degrades")
        if answer.status != 200:
            continue
        modules += 1
        source = answer.body.decode("utf-8", "replace")
        for _quote, value, before in js_strings(source):
            if _DYNAMIC_IMPORT_CONTEXT.search(before):
                pending.append((_resolve(path, value), False, path))
            elif _STATIC_IMPORT_CONTEXT.search(before):
                pending.append((_resolve(path, value), True, path))
            elif _PATH_LITERAL.match(value) and not _MODULE_OR_SHEET.search(value):
                routes.add(_resolve("/", value))
    return sorted(routes), modules


# ---------------------------------------------------------------------------
# The steps.
# ---------------------------------------------------------------------------

def copy_tracked_tree(checkout: Path, target: Path, git: str,
                      env: dict[str, str]) -> None:
    if not checkout.is_dir():
        raise HarnessError(f"--checkout {checkout} is not a directory")
    listed = run([git, "-C", str(checkout), "ls-files", "-z"], env=env,
                 cwd=target.parent)
    if listed.returncode != 0:
        raise HarnessError(f"{checkout} is not a git checkout: "
                           f"{tail(listed.stderr)}")
    for rel in filter(None, listed.stdout.split("\0")):
        src = checkout / rel
        if not src.is_file():
            continue
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


def venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def ask_the_install(python: Path, env: dict[str, str], cwd: Path) -> dict:
    """What the installed product says about itself, read in the venv."""
    program = r"""
import importlib.metadata as md, importlib.util as iu, json, sys
siblings = sys.argv[1].split(",")
out = {"importable": [s for s in siblings if iu.find_spec(s) is not None]}
try:
    meta = md.metadata("opendox")
    out["extras"] = sorted(meta.get_all("Provides-Extra") or [])
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
    done = run([str(python), "-I", "-c", program, ",".join(SIBLINGS)],
               env=env, cwd=cwd)
    if done.returncode != 0:
        raise HarnessError(f"could not ask the install about itself: "
                           f"{tail(done.stderr)}")
    return json.loads(done.stdout)


def no_database_answers(verdict: Verdict, env: dict[str, str]) -> None:
    for host in ("127.0.0.1", "::1"):
        verdict.check(f"clean.database tcp {host}:5432",
                      not listening(host, 5432),
                      f"a database already listens on {host}:5432, so the "
                      "bundled server would not be the only one")
    for sock in ("/var/run/postgresql/.s.PGSQL.5432", "/tmp/.s.PGSQL.5432"):
        answered = False
        if os.path.exists(sock):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(1.0)
                    answered = probe.connect_ex(sock) == 0
            except OSError:
                answered = False
        verdict.check(f"clean.database socket {sock}", not answered,
                      f"a database already answers on {sock}")
    present = [name for name in DATABASE_SETTINGS if env.get(name)]
    verdict.check("clean.database settings", not present,
                  f"the child environment names a database: {present}")


def documented_prefix() -> list[str]:
    words = DOCUMENTED_START.split(" ")
    if words[-1] != "…":
        raise HarnessError("DOCUMENTED_START lost its `…`")
    return words[:-1]


def thread_query(snapshot: dict, grouping_field: str) -> str | None:
    groups = snapshot.get(grouping_field) or []
    for group in groups:
        if not isinstance(group, dict) or not group.get("id"):
            continue
        members = [edge.get("document") for edge in
                   (group.get("document_edges") or [])
                   if isinstance(edge, dict) and edge.get("document")]
        if not members:
            continue
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
    documents = [str(d.get("path")) for d in (snapshot.get("documents") or [])
                 if isinstance(d, dict) and d.get("path")]
    key = urllib.parse.quote(f"{snapshot.get('repository') or ''}@main",
                             safe="")
    targets: list[str] = []
    for route in routes:
        targets.append(route)
        if route.endswith("/"):
            for doc in documents:
                quoted = urllib.parse.quote(doc)
                targets.append(route + quoted)
                targets.append(f"{route}{key}/{quoted}")
        if route == THREAD_ROUTE:
            query = thread_query(snapshot, grouping_field)
            if query:
                targets.append(f"{route}?{query}")
    return targets


def serve_one(label: str, repo: Path, ctx: dict, verdict: Verdict) -> None:
    """Steps 4-8 for one repository: start, fetch, stop, and look for what
    is left."""
    env, venv, scratch = ctx["env"], ctx["venv"], ctx["scratch"]
    port = ctx["port"] or free_port()
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
    program = shutil.which(argv[0], path=env["PATH"])
    verdict.require(
        f"{label}.start.console-script",
        program is not None
        and Path(program).resolve().is_relative_to(venv.resolve()),
        f"`{argv[0]}` resolves to {program!r}, not the fresh venv's console "
        "script")
    note("$ " + " ".join(argv))
    log_out = scratch / f"{label}-server.out"
    log_err = scratch / f"{label}-server.err"
    with open(log_out, "wb") as out, open(log_err, "wb") as err:
        proc = subprocess.Popen(argv, executable=program, env=env,
                                cwd=str(scratch), stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True)
    ctx["servers"].append(proc)

    def server_said() -> str:
        return (f"\n--- stdout ---\n{tail(log_out.read_text('utf-8', 'replace'))}"
                f"\n--- stderr ---\n{tail(log_err.read_text('utf-8', 'replace'))}")

    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    index = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        answer = get(port, "/")
        if answer.status == 200:
            index = answer
            break
        time.sleep(0.5)
    verdict.require(
        f"{label}.start.ready", index is not None,
        (f"the documented command exited (rc={proc.returncode}) before it "
         "answered" if proc.poll() is not None else
         f"no answer on 127.0.0.1:{port} within {READY_TIMEOUT_SECONDS:.0f}s")
        + server_said())
    verdict.require(f"{label}.start.serving-process", proc.poll() is None,
                    "the launched server exited after it answered, so the "
                    "answer may not have been its own" + server_said())

    body = index.body.decode("utf-8", "replace")
    verdict.check(f"{label}.http / is HTML",
                  "<html" in body.lower()
                  and "text/html" in index.headers.get("content-type", ""),
                  f"`/` answered {index.headers.get('content-type')!r} "
                  f"without an <html> element")

    snap_answer = get(port, "/snapshot.json")
    verdict.require(f"{label}.http /snapshot.json", snap_answer.status == 200,
                    f"/snapshot.json answers {snap_answer.describe()}")
    try:
        snapshot = snap_answer.json()
    except ValueError as exc:
        snapshot = exc
    verdict.require(f"{label}.snapshot is a JSON object",
                    isinstance(snapshot, dict),
                    f"/snapshot.json is not a JSON object: {snapshot!r:.300}")
    verdict.check(f"{label}.snapshot non-empty",
                  bool(snapshot.get("documents")), "the snapshot is empty")
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in F53_WORDS)
                         + r")\b")

    def values(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from values(v)
        elif isinstance(node, list):
            for v in node:
                yield from values(v)
        elif isinstance(node, str):
            yield node

    leaks = sorted({m.group(1) for v in values(snapshot)
                    for m in pattern.finditer(v.lower())})
    verdict.check(f"{label}.snapshot neutral (F5.3)", not leaks,
                  f"openxFactory's vocabulary leaked into the neutral "
                  f"snapshot: {leaks}")
    note(f"snapshot kind={snapshot.get('kind')!r}, "
         f"{len(snapshot.get('documents') or [])} documents")

    caps_answer = get(port, "/capabilities")
    verdict.require(f"{label}.http /capabilities", caps_answer.status == 200,
                    f"/capabilities answers {caps_answer.describe()}")
    try:
        caps = caps_answer.json()
    except ValueError as exc:
        caps = exc
    verdict.require(f"{label}.capabilities is a JSON object",
                    isinstance(caps, dict),
                    f"/capabilities is not a JSON object: {caps!r:.300}")
    install = caps.get("install") or {}
    verdict.check(f"{label}.capabilities install.mode == local",
                  install.get("mode") == "local",
                  f"the served install block is {caps.get('install')!r}")
    bundle = install.get("database_bundle") or {}
    if isinstance(bundle.get("pid"), int):
        ctx["reported_pids"].append(bundle["pid"])
        note(f"the served install reports its bundled server as pid "
             f"{bundle['pid']}")
    token = caps.get("console_token")
    verdict.check(f"{label}.capabilities console_token",
                  isinstance(token, str) and bool(token),
                  "/capabilities carries no console token, so no guarded "
                  "route can be asked")
    token = token if isinstance(token, str) else None
    grouping_field = ((((caps.get("display") or {}).get("fields") or {})
                       .get("grouping") or {}).get("field")) or "clusters"
    groups = snapshot.get(grouping_field) or []
    verdict.check(f"{label}.snapshot fills the grouping station",
                  bool(groups),
                  f"the snapshot's grouping station ({grouping_field!r}) is "
                  "empty, so no grouping tile can open the chat pane "
                  "(R1Q13 (a) with (c); AT-R1 fails and does not skip)")

    catalog = get(port, CATALOG_ROUTE, token=token)
    verdict.check(f"{label}.catalog answers", catalog.status == 200,
                  f"{CATALOG_ROUTE} with the console token answers "
                  f"{catalog.describe()}: {catalog.body[:300]!r}")
    if catalog.status == 200:
        try:
            models = catalog.json().get("models")
        except ValueError:
            models = None
        verdict.check(f"{label}.catalog is a catalog",
                      isinstance(models, list),
                      f"{CATALOG_ROUTE} answered no models[]: "
                      f"{catalog.body[:300]!r}")
        available = [m.get("model_id") for m in (models or [])
                     if isinstance(m, dict) and m.get("available")]
        verdict.check(f"{label}.catalog offers no available entry",
                      not available,
                      f"no model is configured, yet the catalog offers "
                      f"{available}")

    routes, modules = derive_bundle(port, body, caps, verdict, label)
    note(f"derived from the served bundle: {modules} modules, "
         f"{len(routes)} routes: {', '.join(routes)}")
    verdict.check(f"{label}.bundle names the catalog route",
                  CATALOG_ROUTE in routes,
                  f"the served bundle no longer names {CATALOG_ROUTE}, so "
                  "this harness's catalog step asks the wrong route")
    for target in requests_for(routes, snapshot, grouping_field):
        answer = get(port, target, token=token)
        note(f"GET {target} -> {answer.describe()}")
        verdict.check(
            f"{label}.route {target}",
            answer.status is not None and answer.status < 500,
            f"GET {target} answers {answer.describe()}" + (
                "; a dropped connection is a handler that raised"
                if answer.status is None else "")
            + server_said())

    # Step 8: stop the entry point alone, as `kill` would, and look.
    proc.send_signal(signal.SIGTERM)
    try:
        rc = proc.wait(timeout=STOP_TIMEOUT_SECONDS)
        stopped = True
    except subprocess.TimeoutExpired:
        rc, stopped = None, False
    verdict.check(f"{label}.stop exits", stopped,
                  f"the server did not exit within {STOP_TIMEOUT_SECONDS:.0f}s "
                  "of SIGTERM")
    note(f"the entry point exited rc={rc}")
    left = bundled_server_processes(ctx["server_package"], ctx["state_dir"])
    verdict.check(f"{label}.stop leaves no bundled PostgreSQL process",
                  not left,
                  "still running after the entry point stopped: "
                  + "; ".join(left))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AT-R1's HTTP half (plan 034 T095): install openDox "
                    "alone, assert a clean machine, run the documented "
                    "command over two plain repositories, and check what it "
                    "serves.")
    parser.add_argument("--checkout", type=Path,
                        default=Path(__file__).resolve().parents[1],
                        help="the openDox-code checkout to install (default: "
                             "the one this file is in)")
    parser.add_argument("--scratch", type=Path, default=None,
                        help="an EMPTY directory for the venv, the repository "
                             "copies and the logs (default: a new temporary "
                             "directory)")
    parser.add_argument("--state-base", type=Path, default=None,
                        help="where the fresh OPENDOX_STATE_DIR is created "
                             "(default: the system's temporary directory). "
                             "Keep it short: the bundled server's socket "
                             "path may not pass 107 bytes. And the server "
                             "refuses a state directory below a directory "
                             "any user can write without the sticky bit")
    parser.add_argument("--port", type=int, default=0,
                        help="the port to serve on (default: a free one, "
                             "checked free before each start)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the scratch and state directories")
    parser.add_argument("--keep-going", action="store_true",
                        help="report every failed assertion instead of "
                             "stopping at the first (still exits 1)")
    args = parser.parse_args(argv)

    if not Path("/proc/self/exe").exists():
        print("AT-R1 ERROR: this harness reads /proc; run it on Linux",
              file=sys.stderr)
        return 2
    git = shutil.which("git")
    if git is None:
        print("AT-R1 ERROR: git is not on the PATH", file=sys.stderr)
        return 2
    checkout = args.checkout.resolve()
    if args.scratch is not None:
        args.scratch.mkdir(parents=True, exist_ok=True)
        if any(args.scratch.iterdir()):
            print(f"AT-R1 ERROR: --scratch {args.scratch} is not empty",
                  file=sys.stderr)
            return 2
        scratch = args.scratch.resolve()
    else:
        scratch = Path(tempfile.mkdtemp(prefix="at-r1-http-"))
    state_base = (args.state_base or Path(tempfile.gettempdir())).resolve()
    state_base.mkdir(parents=True, exist_ok=True)
    state_dir = Path(tempfile.mkdtemp(prefix="odx-", dir=state_base))
    socket_path = len(os.fsencode(state_dir)) + len(SOCKET_SUFFIX)
    if socket_path > SOCKET_PATH_MAX:
        shutil.rmtree(state_dir, ignore_errors=True)
        if args.scratch is None:
            shutil.rmtree(scratch, ignore_errors=True)
        print(f"AT-R1 ERROR: OPENDOX_STATE_DIR {state_dir} would put the "
              f"bundled server's socket at {socket_path} bytes, past "
              f"{SOCKET_PATH_MAX}; pass a shorter --state-base",
              file=sys.stderr)
        return 2
    verdict = Verdict(args.keep_going)
    ctx: dict = {"scratch": scratch, "state_dir": state_dir, "servers": [],
                 "reported_pids": [], "port": args.port,
                 "server_package": None}
    print(f"AT-R1, the HTTP half (plan 034 T095), over {checkout}")
    print(f"      the documented install: {DOCUMENTED_INSTALL}")
    print(f"      the documented start:   {DOCUMENTED_START}")
    print(f"      scratch {scratch}; OPENDOX_STATE_DIR {state_dir}", flush=True)
    try:
        base_env, dropped = stripped_environment(dict(os.environ))
        if dropped:
            note(f"not inherited by any child: {', '.join(dropped)}")
        home = scratch / "home"
        home.mkdir()
        tmp = scratch / "tmp"
        tmp.mkdir()
        base_env.update(HOME=str(home), TMPDIR=str(tmp))

        # 1. openDox alone, into a fresh venv, as `opendox[local]`.
        source = scratch / "openDox-code"
        copy_tracked_tree(checkout, source, git, base_env)
        venv = scratch / "venv"
        made = run([sys.executable, "-m", "venv", "--clear", str(venv)],
                   env=base_env, cwd=scratch)
        verdict.require("install.venv", made.returncode == 0,
                        f"python -m venv failed: {tail(made.stderr)}")
        python = venv_python(venv)
        lock = source / "constraints-cpython312-linux.txt"
        use_lock = (lock.is_file() and sys.platform.startswith("linux")
                    and sys.implementation.name == "cpython"
                    and sys.version_info[:2] == (3, 12))
        install = [str(python), "-m", "pip", "install",
                   "--disable-pip-version-check", "--no-input"]
        if use_lock:
            install += ["-c", str(lock)]
        install.append(f"{source}[local]")
        note("$ " + " ".join(install[2:]) + (
            "" if use_lock else "   (no lock: it pins CPython 3.12 on Linux)"))
        installed = run(install, env=base_env, cwd=scratch,
                        timeout=INSTALL_TIMEOUT_SECONDS)
        verdict.require("install opendox[local]", installed.returncode == 0,
                        f"the install failed (rc={installed.returncode}):\n"
                        f"{tail(installed.stdout)}\n{tail(installed.stderr)}")
        env = dict(base_env)
        env["PATH"] = str(venv / "bin") + os.pathsep + base_env.get("PATH", "")
        env["OPENDOX_STATE_DIR"] = str(state_dir)
        ctx.update(env=env, venv=venv)
        empty = scratch / "cwd"
        empty.mkdir()
        about = ask_the_install(python, env, empty)
        verdict.require("install declares the local extra",
                        "local" in (about.get("extras") or []),
                        f"the installed opendox declares the extras "
                        f"{about.get('extras')}, and no `local` (R1Q16 "
                        "(iii)): the documented install has no bundled "
                        "server to bring")
        if about.get("server_package"):
            ctx["server_package"] = Path(about["server_package"])

        # 2. The clean machine, asserted.
        verdict.check("clean.siblings", not about["importable"],
                      f"importable in the fresh venv: {about['importable']}")
        harnesses = {HARNESS_COMMAND, about.get("harness_command") or
                     HARNESS_COMMAND}
        on_path = [h for h in sorted(harnesses)
                   if shutil.which(h, path=env["PATH"])]
        verdict.check("clean.omp", not on_path,
                      f"a harness is on the PATH ({on_path}), so no-model is "
                      "not what this run measures")
        brokers = [b for b in BROKER_COMMANDS
                   if shutil.which(b, path=env["PATH"])]
        identity = [n for n in IDENTITY_SETTINGS if env.get(n)]
        verdict.check("clean.identity-broker", not brokers and not identity,
                      f"an identity broker is present: on the PATH "
                      f"{brokers}, set {identity}")
        no_database_answers(verdict, env)
        verdict.check("clean.state-dir", not any(state_dir.iterdir()),
                      f"OPENDOX_STATE_DIR {state_dir} is not empty")
        verdict.check("clean.no-bundled-server-yet",
                      not bundled_server_processes(ctx["server_package"],
                                                   state_dir),
                      "a process of this install's bundled server runs "
                      "before anything started it")

        # 3. Two plain repositories, each a fresh `git init`.
        fixture = source / "tests" / "fixtures" / "plain-documents"
        verdict.require("repos.fixture", fixture.is_dir(),
                        f"5.0's fixture is missing at {fixture}")
        repos = scratch / "repos"
        a = repos / "plain-documents"
        make_repository(a, {p.relative_to(fixture): p
                            for p in sorted(fixture.rglob("*")) if p.is_file()},
                        git, env, "fixture")
        b = repos / "plain-notes"
        make_repository(b, {Path(k): v for k, v in PLAIN_NOTES.items()},
                        git, env, "notes")
        bindings = about.get("bindings_relpath") or BINDINGS_RELPATH_FALLBACK
        for label, repo in (("a", a), ("b", b)):
            verdict.check(f"clean.binding {label}",
                          not (repo / bindings).exists(),
                          f"{repo} holds a model binding at {bindings}")
            ident = run([git, "-C", str(repo), "config", "user.name"],
                        env=env, cwd=repo)
            verdict.check(f"repos.{label} git identity",
                          ident.stdout.strip() == "fixture",
                          f"{repo} has no git identity, so no served actor")

        # 4-8, once per repository.
        for label, repo in (("a", a), ("b", b)):
            print(f"--- repository ({label}) {repo.name}", flush=True)
            serve_one(label, repo, ctx, verdict)
    except Failed as failure:
        # A fail-fast stop, or a `require` that ended a `--keep-going` run;
        # reported with the rest, after the cleanup below.
        if failure not in verdict.failures:
            verdict.failures.append(failure)
    except HarnessError as error:
        print(f"\nAT-R1 HTTP half: ERROR: {error}", flush=True)
        return 2
    except Exception:  # the harness itself broke: say so, never a PASS
        import traceback
        traceback.print_exc()
        print("\nAT-R1 HTTP half: ERROR: the harness raised before a "
              "verdict", flush=True)
        return 2
    finally:
        for proc in ctx["servers"]:
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=STOP_TIMEOUT_SECONDS)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        leftovers = [int(line.split()[1].rstrip(":")) for line in
                     bundled_server_processes(ctx["server_package"], state_dir)]
        stop_processes(leftovers)
        if args.keep:
            print(f"      kept {scratch} and {state_dir}")
        else:
            shutil.rmtree(scratch, ignore_errors=True)
            shutil.rmtree(state_dir, ignore_errors=True)
    if verdict.failures:
        first = verdict.failures[0]
        print(f"\nAT-R1 HTTP half: FAIL [{first.ident}]: "
              f"{first.why.splitlines()[0]}")
        for later in verdict.failures[1:]:
            print(f"      also FAIL [{later.ident}]: "
                  f"{later.why.splitlines()[0]}")
        print(f"      {len(verdict.failures)} failed, {verdict.passed} held")
        return 1
    print(f"\nAT-R1 HTTP half: PASS ({verdict.passed} assertions held)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
