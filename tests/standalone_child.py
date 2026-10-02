"""A lone openDox, as a CHILD PROCESS: `python -m <module> ...` with neither
sibling importable (plan 034's T056, and T058's F7.2 case after it).

A test that means "the verb, the way a user runs it" runs the verb in a process
of its own, through `python -m`, as #1144's falsifiers are written. This module
builds that child and reads it:

* NEITHER SIBLING IS IMPORTABLE. The child's interpreter loads a
  `sitecustomize` from a directory put first on `PYTHONPATH`. It installs a
  meta-path finder that refuses `openxdox`, `ideation_dashboard`, `doc_health`
  and `corpus_adapter_openxfactory`, whatever is installed, and drops any of
  them that a `.pth` file imported before it ran. It records every refused name
  in a log (`Child.refused()`). A case asserts that the log is EMPTY: a refused
  import that some `except ImportError` swallowed would otherwise pass as a
  degraded run.
* ITS STANDARD OUTPUT IS A PIPE WITH PYTHON'S DEFAULT BUFFERING, as any
  wrapper that reads it sees it. `PYTHONUNBUFFERED` is taken out of the
  child's environment on purpose, so a line the child prints and does not
  flush before it blocks is a line a case never reads.
* It is read on threads while it runs (`Child.wait_for_line`), so a server that
  never exits can still be asked where it serves, and then interrupted
  (`Child.interrupt`, SIGINT, as Ctrl-C sends).
* CTRL-C REACHES IT AS IT WOULD AT A TERMINAL, whatever the runner's own
  disposition. The same `sitecustomize` sets SIGINT back to Python's
  KeyboardInterrupt handler. A runner started as a background job
  (`nohup pytest ... &`) has SIGINT ignored, and every child would inherit
  that, so an interrupted server would time out and the case would report the
  runner, not the server (measured at openDox-code#66 a6e953ce). A child that
  ignores SIGINT ITSELF, after startup, still does, and is killed at the
  deadline.

`fresh_repository()` is #1144's preamble: a fixture copied into a FRESH git
repository and committed as the fixture's own identity.

A helper module, not a test module: it holds no case. A CREATED FILE, with no
carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The four packages a neutral openDox must run without (#1144's F2.1).
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: How long a child may take to print what a case waits for. Generation over a
#: fixture takes about a second; the margin is for a loaded CI runner.
START_DEADLINE_SECONDS = 120.0

#: How long a child may take to stop once interrupted, or to finish a run.
STOP_DEADLINE_SECONDS = 30.0
RUN_DEADLINE_SECONDS = 300.0

#: The environment variable naming the child's refused-import log.
REFUSED_LOG_ENV = "OPENDOX_STANDALONE_CHILD_REFUSED"

#: The `sitecustomize` every child loads.
_BLOCKER = f'''\
import os
import signal
import sys

# Ctrl-C as at a terminal: a runner started as a background job ignores
# SIGINT, and an ignored signal is inherited across exec (tests/standalone_child.py).
signal.signal(signal.SIGINT, signal.default_int_handler)

_SIBLINGS = {SIBLINGS!r}

for _name in list(sys.modules):
    if _name.split(".")[0] in _SIBLINGS:
        del sys.modules[_name]


class _RefuseTheSiblings:
    """Neither sibling is importable in this process (plan 034 T056)."""

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in _SIBLINGS:
            return None
        log = os.environ.get({REFUSED_LOG_ENV!r})
        if log:
            with open(log, "a", encoding="utf-8") as stream:
                stream.write(name + "\\n")
        raise ModuleNotFoundError(
            f"No module named {{name!r}} (refused: a lone openDox has no "
            f"sibling)", name=name)


sys.meta_path.insert(0, _RefuseTheSiblings())
'''


def git(root: Path, *args: str) -> None:
    """`git` in `root` as #1144's fixture identity, with no inherited `GIT_*`
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


def fresh_repository(fixture: Path, parent: Path, *,
                     edits: dict[str, str] | None = None) -> Path:
    """#1144's preamble: `fixture` copied into a FRESH repository under
    `parent`, named as the fixture is, with `edits` (a document's new text, by
    name) applied before the one commit."""
    root = parent / fixture.name
    shutil.copytree(fixture, root)
    for name, text in (edits or {}).items():
        (root / name).write_text(text, encoding="utf-8")
    git(root, "-c", "init.defaultBranch=main", "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "fixture")
    return root


class Child:
    """One `python -m <module> ...` child, with the siblings refused and its
    standard output a buffered pipe. `workdir` holds the blocker and the log."""

    def __init__(self, workdir: Path, module: str, *args: str) -> None:
        blocker = workdir / "sibling-blocker"
        blocker.mkdir(parents=True, exist_ok=True)
        (blocker / "sitecustomize.py").write_text(_BLOCKER, encoding="utf-8")
        self.refused_log = workdir / "refused-imports.log"
        env = dict(os.environ)
        env.pop("PYTHONUNBUFFERED", None)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(blocker), *filter(None, [env.get("PYTHONPATH")])])
        env[REFUSED_LOG_ENV] = str(self.refused_log)
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

    def wait(self) -> int:
        """Run the child to completion and answer its exit status."""
        try:
            return self.process.wait(timeout=RUN_DEADLINE_SECONDS)
        finally:
            self.kill()
            self._join()

    def interrupt(self) -> int:
        """Send SIGINT, as Ctrl-C would, and answer the exit status.

        A child that does not stop within `STOP_DEADLINE_SECONDS` is KILLED
        before its pipes are joined, and the timeout is raised (Copilot at
        openDox-code#66 1597511d, r4139607689). Its readers block until the
        pipes close, so joining first would hold the caller for two more
        deadlines on exactly the path, an interrupt that is ignored, this
        helper exists to report."""
        self.process.send_signal(signal.SIGINT)
        try:
            return self.process.wait(timeout=STOP_DEADLINE_SECONDS)
        finally:
            self.kill()
            self._join()

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=STOP_DEADLINE_SECONDS)

    def _join(self) -> None:
        for pump in self._pumps:
            pump.join(timeout=STOP_DEADLINE_SECONDS)

    def stdout_text(self) -> str:
        return "".join(self.stdout)

    def stderr_text(self) -> str:
        return "".join(self.stderr)

    def refused(self) -> list[str]:
        """Every sibling name the child tried to import, in order."""
        if not self.refused_log.exists():
            return []
        return self.refused_log.read_text(encoding="utf-8").split()


def run_module(workdir: Path, module: str, *args: str) -> tuple[Child, int]:
    """A child run to completion: `(child, exit status)`."""
    child = Child(workdir, module, *args)
    return child, child.wait()
