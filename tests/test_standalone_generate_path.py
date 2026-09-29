"""The standalone generate path, end to end, through the verbs themselves:
plan 034's T056 (#1144's 5.1, in part).

T054 tests the neutral projection in process, and T055 routes the verbs
through the seams. What neither shows is the path a user runs:
`python -m opendox.cli generate` and `generate-and-open`, in a process of their
own, with neither sibling importable, until the server STARTS and answers. That
is what research R7 measured as refused, and this file holds the lifted limit:

1. F5.3, #1144's falsifier for Group 5, run the way it is written:
   `python -m opendox.cli generate` over a fresh repository copied from T050's
   `tests/fixtures/plain-documents`. The snapshot is not empty, it is the
   neutral kind, and none of openxFactory's declared vocabulary is in a string
   value of it.
2. The verb's half of spec.md's `stage:` edge case. Over a copy of T050's
   fixture in which one document declares a `stage:` value outside the six
   role keys, the verb reports it, naming the document, the value and the six
   keys, and the snapshot it writes reads that document as a source. T054
   tests the projection's half in process.
3. `python -m opendox.cli generate-and-open --no-open` STARTS a server, which
   answers `/index.html`, `/snapshot.json`, `/capabilities` and `/source/`,
   refuses `/source/.git/config`, and stops on an interrupt with status 0.
4. `python -m opendox.serve`, the server's own entry point, starts and answers
   the same way.

HOW "NEITHER SIBLING IS IMPORTABLE" IS MADE TRUE. Each run is a real child
process, `python -m ...`, whose interpreter loads a `sitecustomize` from a
directory put first on `PYTHONPATH`. It installs a meta-path finder that
refuses `openxdox`, `ideation_dashboard`, `doc_health` and
`corpus_adapter_openxfactory`, whatever is installed, and it records every
refused name in a log. Each case asserts that the log is EMPTY. A refused
import that some `except ImportError` swallowed would otherwise pass as a
degraded run, so the case holds both halves: the siblings cannot be imported,
and nothing on the path tries to.

THE CHILD'S STANDARD OUTPUT IS A PIPE, with Python's default buffering, as
any wrapper that reads the URL sees it. `PYTHONUNBUFFERED` is taken out of the
child's environment on purpose. A server that printed its URL and then
blocked in `serve_forever()` without flushing never delivered that line on a
pipe, so a caller could neither learn an ephemeral port nor tell that the
server had started (measured at openDox-code#59 `e3ef506a`: zero lines in 20
seconds). T056 flushes it in both entry points, and cases 3 and 4 fail
without that.

NOT HERE: F10.1's run through a plain install, with the console script and no
`--local`, arrives in phase 3 (T070, and T077 as batch H amends it).

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAIN_DOCUMENTS = ROOT / "tests" / "fixtures" / "plain-documents"
NEUTRAL = "opendox-snapshot"
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: The six station role keys, in the order the neutral contract lists them.
ROLE_KEYS = ("source", "grouping", "candidate", "selection", "submission",
             "completion")

#: F5.3's declared vocabulary, verbatim: the eight lifecycle `Status:` words
#: and the change/spec/delta nouns, as #1144's Group 5 falsifier spells them.
F53_WORDS = ["brainstorm", "staged", "draft", "ratified", "standard",
             "superseded", "retired", "record", "openspec", "proposal.md",
             "tasks.md", "design.md", "added requirements",
             "modified requirements"]

#: How long a child may take to say where it serves. Generation over the
#: fixture takes about a second; the margin is for a loaded CI runner.
START_DEADLINE_SECONDS = 120.0

#: How long a child may take to stop once interrupted.
STOP_DEADLINE_SECONDS = 30.0

#: The `sitecustomize` every child loads. It refuses the siblings at the
#: FIRST finder, drops any that a `.pth` file imported before it ran, and
#: logs each refused name to the file `OPENDOX_T056_REFUSED` names.
_BLOCKER = f'''\
import os
import sys

_SIBLINGS = {SIBLINGS!r}

for _name in list(sys.modules):
    if _name.split(".")[0] in _SIBLINGS:
        del sys.modules[_name]


class _RefuseTheSiblings:
    """Neither sibling is importable in this process (plan 034 T056)."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in _SIBLINGS:
            return None
        log = os.environ.get("OPENDOX_T056_REFUSED")
        if log:
            with open(log, "a", encoding="utf-8") as stream:
                stream.write(name + "\\n")
        raise ModuleNotFoundError(
            f"No module named {{name!r}} (refused: a lone openDox has no "
            f"sibling)", name=name)


sys.meta_path.insert(0, _RefuseTheSiblings())
'''


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _git(root: Path, *args: str) -> None:
    """`git` in `root` as F5.3's fixture identity, with no inherited `GIT_*`
    variable and no user or system configuration."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, env=env)


def _fresh_repository(tmp_path: Path, *, edits: dict[str, str] | None = None) -> Path:
    """F5.3's preamble: T050's fixture copied into a FRESH repository, with
    `edits` (a document's new text, by name) applied before the commit."""
    root = tmp_path / "plain-documents"
    shutil.copytree(PLAIN_DOCUMENTS, root)
    for name, text in (edits or {}).items():
        (root / name).write_text(text, encoding="utf-8")
    _git(root, "-c", "init.defaultBranch=main", "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")
    return root


class _Child:
    """One `python -m <module> ...` child with the siblings refused, its
    standard output a buffered pipe."""

    def __init__(self, tmp_path: Path, module: str, *args: str) -> None:
        blocker = tmp_path / "sibling-blocker"
        blocker.mkdir(exist_ok=True)
        (blocker / "sitecustomize.py").write_text(_BLOCKER, encoding="utf-8")
        self.refused_log = tmp_path / "refused-imports.log"
        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(blocker), *filter(None, [env.get("PYTHONPATH")])])
        env["OPENDOX_T056_REFUSED"] = str(self.refused_log)
        self.argv = [sys.executable, "-m", module, *args]
        verb = args[0] if args and not args[0].startswith("-") else ""
        self.label = f"python -m {module} {verb}".strip()
        self.process = subprocess.Popen(
            self.argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace")
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stdout: list[str] = []
        self.stderr: list[str] = []
        self._pumps = [
            threading.Thread(target=self._pump, args=(self.process.stdout, True),
                             daemon=True),
            threading.Thread(target=self._pump, args=(self.process.stderr, False),
                             daemon=True),
        ]
        for pump in self._pumps:
            pump.start()

    def _pump(self, stream, is_stdout: bool) -> None:
        for line in stream:
            (self.stdout if is_stdout else self.stderr).append(line)
            if is_stdout:
                self.lines.put(line)
        if is_stdout:
            self.lines.put(None)

    def wait_for_line(self, pattern: re.Pattern[str]) -> re.Match[str]:
        """The first standard-output line matching `pattern`, read while the
        child runs. Fails, naming what the child said, if it exits first or
        the deadline passes."""
        deadline = time.monotonic() + START_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if line is None:
                break
            match = pattern.search(line)
            if match:
                return match
        raise AssertionError(
            f"{self.label} never printed a line matching "
            f"{pattern.pattern!r} on its (buffered) standard output while it "
            f"ran: exit status {self.process.poll()}, standard output "
            f"{''.join(self.stdout)!r}, standard error {self.stderr_text()[-2000:]!r}")

    def interrupt(self) -> int:
        """Send SIGINT, as Ctrl-C would, and answer the exit status."""
        self.process.send_signal(signal.SIGINT)
        try:
            return self.process.wait(timeout=STOP_DEADLINE_SECONDS)
        finally:
            for pump in self._pumps:
                pump.join(timeout=STOP_DEADLINE_SECONDS)

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=STOP_DEADLINE_SECONDS)

    def stderr_text(self) -> str:
        return "".join(self.stderr)

    def refused(self) -> list[str]:
        if not self.refused_log.exists():
            return []
        return self.refused_log.read_text(encoding="utf-8").split()


def _run(tmp_path: Path, module: str, *args: str) -> tuple[_Child, int]:
    """A child run to completion."""
    child = _Child(tmp_path, module, *args)
    try:
        status = child.process.wait(timeout=300)
    finally:
        child.kill()
    for pump in child._pumps:
        pump.join(timeout=STOP_DEADLINE_SECONDS)
    return child, status


def _get(base: tuple[str, int], path: str) -> tuple[int, str, bytes]:
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return (response.status, response.getheader("Content-Type") or "",
                response.read())
    finally:
        connection.close()


def _string_values(value):
    """Every string VALUE in a JSON document: keys are the product's own
    structure, as F5.3 reads it."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_values(item)
    elif isinstance(value, str):
        yield value


def _leaks(snapshot: dict) -> list[str]:
    """F5.3's assertion, verbatim in substance: the declared words found as
    whole words in a lower-cased string value."""
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in F53_WORDS) + r")\b")
    return sorted({m.group(1) for text in _string_values(snapshot)
                   for m in pattern.finditer(text.lower())})


def _assert_the_server_answers(base: tuple[str, int], written: Path,
                               repo: Path) -> None:
    """The core routes a standalone server answers, from openDox's own
    registry and source."""
    status, kind, body = _get(base, "/index.html")
    assert status == 200 and "<html" in body.decode("utf-8", "replace").lower()
    status, kind, body = _get(base, "/snapshot.json")
    assert status == 200, status
    served = json.loads(body)
    assert served["kind"] == NEUTRAL
    assert served == json.loads(written.read_text(encoding="utf-8"))
    status, kind, body = _get(base, "/capabilities")
    assert status == 200, status
    capabilities = json.loads(body)
    assert capabilities["refresh"]["binding"] == "regenerate"
    assert capabilities["actions"]["refresh"] is True
    document = "notes-toolshed-inventory.md"
    status, kind, body = _get(base, f"/source/{document}")
    assert status == 200, status
    assert body == (repo / document).read_bytes()
    status, kind, body = _get(base, "/source/.git/config")
    assert status == 404, status


def _assert_the_port_is_closed(base: tuple[str, int]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(5)
        assert probe.connect_ex(base) != 0, f"{base} still accepts connections"


_URL = re.compile(r"^(http://([0-9.]+):([0-9]+))/index\.html$")
_SERVE_URL = re.compile(r"^serving ideation dashboard at "
                        r"(http://([0-9.]+):([0-9]+))/index\.html$")


# ---------------------------------------------------------------------------
# 1 — F5.3, through the module
# ---------------------------------------------------------------------------

def test_F5_3_generate_through_the_module_writes_the_neutral_snapshot(tmp_path) -> None:
    """#1144's F5.3, as written: `python -m opendox.cli generate` over a fresh
    copy of T050's fixture, with neither sibling importable."""
    repo = _fresh_repository(tmp_path)
    out = tmp_path / "snap.json"
    child, status = _run(tmp_path, "opendox.cli", "generate",
                         "--repo-root", str(repo), "--repository", "fixture",
                         "--output", str(out))
    assert status == 0, child.stderr_text()
    assert child.refused() == [], child.refused()
    snapshot = json.loads(out.read_text(encoding="utf-8"))
    assert snapshot["documents"], "snapshot is empty"
    assert snapshot["kind"] == NEUTRAL
    assert snapshot["repository"] == "fixture"
    assert _leaks(snapshot) == [], (
        f"openxFactory's vocabulary leaked into the neutral projection: "
        f"{_leaks(snapshot)}")
    assert f"wrote {out}" in "".join(child.stdout)
    assert "notice:" not in child.stderr_text()


# ---------------------------------------------------------------------------
# 2 — the verb's half of the `stage:` edge case
# ---------------------------------------------------------------------------

def test_the_verb_reports_a_stage_outside_the_six_and_reads_it_as_a_source(
        tmp_path) -> None:
    """spec.md's edge case, through `python -m opendox.cli generate`: the value
    is not a declaration, the verb names the document, the value and the six
    keys, and the snapshot reads the document as a source."""
    document = "candidate-toolshed-rebuild.md"
    original = (PLAIN_DOCUMENTS / document).read_text(encoding="utf-8")
    assert original.startswith("stage: candidate\n"), original[:40]
    repo = _fresh_repository(
        tmp_path, edits={document: original.replace(
            "stage: candidate\n", "stage: someday\n", 1)})
    out = tmp_path / "snap.json"
    child, status = _run(tmp_path, "opendox.cli", "generate",
                         "--repo-root", str(repo), "--repository", "fixture",
                         "--output", str(out))
    assert status == 0, child.stderr_text()
    assert child.refused() == [], child.refused()
    notices = [line for line in child.stderr_text().splitlines()
               if line.startswith("notice:")]
    assert len(notices) == 1, child.stderr_text()
    notice = notices[0]
    assert document in notice
    assert "'someday'" in notice
    for key in ROLE_KEYS:
        assert re.search(rf"\b{key}\b", notice), (key, notice)
    assert "read as a source" in notice
    snapshot = json.loads(out.read_text(encoding="utf-8"))
    [entry] = [d for d in snapshot["documents"] if d["path"] == document]
    assert entry["stage"] == "source"
    assert "someday" not in set(_string_values(snapshot))
    assert {d["stage"] for d in snapshot["documents"]} <= set(ROLE_KEYS)


def test_the_unedited_fixture_declares_that_document_a_candidate(tmp_path) -> None:
    """The control for the case above: the same document, as T050 ships it,
    is a declared candidate and draws no notice. So the reading above is the
    out-of-six value's doing."""
    repo = _fresh_repository(tmp_path)
    out = tmp_path / "snap.json"
    child, status = _run(tmp_path, "opendox.cli", "generate",
                         "--repo-root", str(repo), "--repository", "fixture",
                         "--output", str(out))
    assert status == 0, child.stderr_text()
    snapshot = json.loads(out.read_text(encoding="utf-8"))
    [entry] = [d for d in snapshot["documents"]
               if d["path"] == "candidate-toolshed-rebuild.md"]
    assert entry["stage"] == "candidate"
    assert "notice:" not in child.stderr_text()


# ---------------------------------------------------------------------------
# 3 — `generate-and-open` STARTS the server (research R7's limit, lifted)
# ---------------------------------------------------------------------------

def test_generate_and_open_starts_a_server_that_answers_with_no_sibling(tmp_path) -> None:
    """`python -m opendox.cli generate-and-open --no-open`, with no
    `--no-serve`: the server starts, says where on a buffered pipe, answers
    the core routes, and stops on an interrupt with status 0."""
    repo = _fresh_repository(tmp_path)
    run_dir = tmp_path / "run"
    child = _Child(tmp_path, "opendox.cli", "generate-and-open",
                   "--repo-root", str(repo), "--repository", "fixture",
                   "--no-open", "--port", "0", "--run-dir", str(run_dir))
    try:
        match = child.wait_for_line(_URL)
        base = (match.group(2), int(match.group(3)))
        assert child.process.poll() is None, "the server exited after printing its URL"
        _assert_the_server_answers(base, run_dir / "snapshot.json", repo)
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    _assert_the_port_is_closed(base)
    assert child.refused() == [], child.refused()
    assert "serving until interrupted" in "".join(child.stdout)


# ---------------------------------------------------------------------------
# 4 — the server's own entry point starts the same way
# ---------------------------------------------------------------------------

def test_serve_main_starts_a_server_that_answers_with_no_sibling(tmp_path) -> None:
    """`python -m opendox.serve` over a snapshot `generate` wrote: it starts,
    announces its URL on a buffered pipe, answers, and stops on an interrupt."""
    repo = _fresh_repository(tmp_path)
    out = tmp_path / "out" / "snapshot.json"
    generated, status = _run(tmp_path, "opendox.cli", "generate",
                             "--repo-root", str(repo), "--repository", "fixture",
                             "--output", str(out), "--no-validate")
    assert status == 0, generated.stderr_text()
    child = _Child(tmp_path, "opendox.serve", "--snapshot", str(out),
                   "--checkout-root", str(repo), "--port", "0")
    try:
        match = child.wait_for_line(_SERVE_URL)
        base = (match.group(2), int(match.group(3)))
        _assert_the_server_answers(base, out, repo)
        assert child.interrupt() == 0, child.stderr_text()
    finally:
        child.kill()
    _assert_the_port_is_closed(base)
    assert child.refused() == [], child.refused()
