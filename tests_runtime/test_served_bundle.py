"""The door: an openDox-only install serves the whole web bundle (plan 034
T075; #1144 10.2 and 10.2a).

T075's falsifier is F10.1's fetch, as T007 batch H amends it: a `.[local]`
install, and `opendox generate-and-open --local …`, which starts the bundled
server (13.1; R1Q15 (b), R1Q16 (iii), `5850003126`). F10.1 fetches `/` and
reads `<html` from it. 10.2 asks more than that page: *"The web bundle is
served by that entry point and is reachable in a browser from an
openDox-only install"*, and the bundle is 42 files. So the fetch is widened
here to every one of them, the way F10.1's own fetch is made: an HTTP GET to
the running console script, whose status is the status.

WHAT THE MEASUREMENT FOUND, at openDox-code#69's head after its
merge-from-main round. The suite's own runs are EDITABLE installs, which put
`src/` on the path, so every one of them serves the tree's 42 files. A WHEEL
is what `pip install ".[local]"` installs, and the wheel carried 41: the
package data's `web/**` is expanded by the standard library's `glob`, which
skips a name that starts with a dot, so `vendor/.gitkeep` never reached an
install and `GET /vendor/.gitkeep` answered 404 from one. The census
(`tests/fixtures/web_boundary_census.yaml`) counts that file, and
`pyproject.toml`'s own note says the glob "ships exactly what that census
counts". Slice S5 had measured the same omission and let it stand, as a
directory keeper that only git needs (`tests/test_gate_loop_contributed.py`'s
setuptools-floor case); 10.2 counts it among the 42, so T075 ships it.
`web/**/.*` beside `web/**` closes the gap, and nothing else was missing: the
static route (`SimpleHTTPRequestHandler`'s, over `opendox/web/` beside the
installed `opendox/cli.py`) served the other 41, each with the bytes the tree
holds and a type a browser accepts.

THE CASES, each against a wheel built from this checkout and installed
OUTSIDE it (T072's own recipe, `tests_runtime/test_bundled_postgres.py`):

1. the wheel carries every file the tree's `src/opendox/web/` holds, and
   nothing else there;
2. F10.1's fetch, widened: the installed `opendox` console script, started
   with `generate-and-open --local --no-open` from a directory that is not a
   checkout, with no sibling importable, answers `/` with the bundle's
   `<html`, and answers every one of the 42 files with 200, the tree's bytes
   and a content type a browser accepts for it. The module graph a browser
   walks from `/` closes inside the bundle. It stops on SIGTERM, as F10.1's
   `kill "$SERVER"` stops it, and its bundled server stops with it.

10.2a, A DECLARATION AND NOT A GAP. `views/intent-feed.js` stays at
openxFactory (RULED OQ-F) and is not owed to openDox; `views/intent-binding.js`
is openDox's replacement and reaches it only by a dynamic `import()`, so a
missing module is an absent binding, not a broken bundle. Case 2 holds both
halves: the 42 do not include it, and the installed server answers it 404.

THE CHILD'S ENVIRONMENT IS SCRUBBED of every `OPENDOX_*`, `PG*`, `GIT_*` and
`XF_*` name the suite runs with: the suite exports a gate roster
(`XF_GATE_PRINCIPALS`), and a setting the runner happens to carry must not
decide what the install serves. It is stopped with SIGTERM, which the local
lifecycle reads as the interrupt its serve loop ends on, so a runner started
as a background job (whose children ignore SIGINT) tests the server, not how
the suite was launched.

NOT SKIPPED IN CI. The bundled server comes with the `local` extra, which the
`test` extra installs; under `CI` its absence is a FAILURE, as it is in
`test_bundled_postgres.py`, because `validate.yml` pins the skip count
exactly.

NOT HERE: F10.1 itself, run as batch H amends it in a fresh environment, is
T077's. This file is the fetch it ends with, made over every file.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import os
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

from opendox.runtime import bundle as bundle_mod
from opendox.runtime import config
from opendox.runtime.config import PREFIX

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
PLAIN_DOCUMENTS = ROOT / "tests" / "fixtures" / "plain-documents"

#: #1144 10.2's count of the bundle openDox-code carries.
BUNDLE_FILES = 42

#: 10.2a: not owed to openDox, and not counted as a missing file.
NOT_OWED = "views/intent-feed.js"

#: The four packages a lone openDox runs without (#1144's F2.1), and F10.1's
#: `python -c "import openxdox"` guard over each of them.
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

#: The probe's exit status when one of them is importable.
SIBLING_PRESENT = 3

#: The JavaScript MIME type essences the HTML standard lists. A module
#: script served under any other type is refused by the browser.
JAVASCRIPT_TYPES = frozenset({
    "application/ecmascript", "application/javascript",
    "application/x-ecmascript", "application/x-javascript",
    "text/ecmascript", "text/javascript", "text/javascript1.0",
    "text/javascript1.1", "text/javascript1.2", "text/javascript1.3",
    "text/javascript1.4", "text/javascript1.5", "text/jscript",
    "text/livescript", "text/x-ecmascript", "text/x-javascript",
})

#: The content type a browser needs for each other kind the bundle holds.
REQUIRED_TYPES = {".html": {"text/html"}, ".css": {"text/css"}}

#: The scrubbed prefixes of the child's environment (see the module note).
SCRUBBED = ("OPENDOX_", "PG", "GIT_", "XF_")

START_SECONDS = 120
STOP_SECONDS = 60


def _in_ci() -> bool:
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(scope="module", autouse=True)
def _the_server_is_installed() -> None:
    """The `local` extra's binaries, or this module's refusal to pass silently."""
    try:
        bundle_mod.server_binaries()
    except bundle_mod.BundleRefused as exc:
        if _in_ci():
            pytest.fail(f"CI is set, so the served-bundle suite must RUN: {exc}",
                        pytrace=False)
        pytest.skip(str(exc))
    if hasattr(os, "geteuid") and os.geteuid() == 0:   # pragma: no cover
        pytest.fail("the bundled server refuses root; run the suite as a user")


def _tree_files() -> set[str]:
    """Every file under the tree's `src/opendox/web/`, as a bundle path."""
    return {p.relative_to(WEB).as_posix() for p in WEB.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> Path:
    """This checkout's wheel, built offline from a copy of what it packages."""
    work = tmp_path_factory.mktemp("t075-wheel")
    source = work / "source"
    source.mkdir()
    for name in ("pyproject.toml", "src", "migrations"):
        item = ROOT / name
        if item.is_dir():
            shutil.copytree(item, source / name, ignore=shutil.ignore_patterns(
                "__pycache__", "*.egg-info"))
        else:
            shutil.copy2(item, source / name)
    wheels = work / "wheels"
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-index",
         "--no-build-isolation", "-q", "-w", str(wheels), str(source)],
        capture_output=True, text=True, timeout=300)
    assert built.returncode == 0, built.stderr[-3000:]
    (found,) = wheels.glob("opendox-*.whl")
    return found


@pytest.fixture(scope="module")
def installed(wheel: Path, tmp_path_factory) -> tuple[Path, Path]:
    """The wheel installed under a prefix of its own: `(console script, site)`.

    `--ignore-installed` is load-bearing, as T072's case records: without it
    pip uninstalls the suite's own editable `opendox` first."""
    prefix = tmp_path_factory.mktemp("t075-prefix")
    done = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
         "--ignore-installed", "-q", "--prefix", str(prefix), str(wheel)],
        capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "uninstall" not in (done.stdout + done.stderr).lower()
    site = Path(sysconfig.get_path("purelib", vars={"base": str(prefix),
                                                     "platbase": str(prefix)}))
    script = Path(sysconfig.get_path("scripts", vars={"base": str(prefix),
                                                       "platbase": str(prefix)}))
    return script / "opendox", site


def _child_env(site: Path, **extra: str) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items()
           if not name.startswith(SCRUBBED)}
    env["PYTHONPATH"] = str(site)
    env.pop("PYTHONUNBUFFERED", None)
    env.update(extra)
    return env


def _fresh_repository(parent: Path) -> Path:
    """#1144's preamble: T050's fixture in a FRESH repository, one commit, as
    the fixture's own identity and no user or system configuration."""
    root = parent / PLAIN_DOCUMENTS.name
    shutil.copytree(PLAIN_DOCUMENTS, root)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    for args in (("-c", "init.defaultBranch=main", "init", "-q"),
                 ("add", "-A"), ("commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, env=env)
    return root


@pytest.fixture()
def state_dir():
    """A SHORT state directory (the socket's path is bounded by the kernel),
    removed afterwards once any server on it is checked stopped.

    THE REMOVAL IS RETRIED, BOUNDED. A server killed on a red path can leave a
    backend still writing its WAL for a moment after the postmaster has gone,
    and a single `rmtree` that races it leaves a data directory behind under
    `/tmp` (seen once, on a mutant run, as `postgres/data/pg_wal/…`)."""
    base = "/tmp" if os.path.isdir("/tmp") else None
    path = Path(tempfile.mkdtemp(prefix="odx-t075-", dir=base))
    yield path
    pid = bundle_mod.running_pid(config.DatabaseBundle(path))
    if pid is not None:                                  # pragma: no cover
        os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + STOP_SECONDS
    while True:
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists() or time.monotonic() > deadline:
            break
        time.sleep(0.2)                                  # pragma: no cover
    assert not path.exists(), f"the state directory outlived its test: {path}"


def _served_url(child: subprocess.Popen, said: Path, seconds: float) -> str | None:
    """The URL line the entry point prints once it serves, read from the FILE
    its standard output goes to, or `None` once `seconds` pass or it exits.

    A file and not a pipe: nothing has to drain it while the server runs, and
    the entry point flushes that line before it blocks (plan 034 T056), so a
    server that serves has said where by the time the line is looked for."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        text = said.read_text(encoding="utf-8", errors="replace")
        found = [line for line in text.splitlines() if line.startswith("http://")]
        if found:
            return found[0].strip()
        if child.poll() is not None:
            return None
        time.sleep(0.2)
    return None


def _get(base: tuple[str, int], path: str) -> tuple[int, str, bytes]:
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return (response.status, response.getheader("Content-Type") or "",
                response.read())
    finally:
        connection.close()


def _essence(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


# What a browser fetches from the bundle on its own: the page's `src`/`href`
# attributes, and each module's STATIC imports. A static import that names a
# missing file fails the whole module graph; a dynamic `import()` is how the
# bundle reaches what may be absent (10.2a), so those are read separately, and
# walked on only where the bundle carries the target.
_PAGE_REFERENCE = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""")
_STATIC_IMPORT = re.compile(
    r"""^[ \t]*(?:import|export)\b[^;'"`]*?\bfrom[ \t]*(["'])([^"'\n]+)\1"""
    r"""|^[ \t]*import[ \t]*(["'])([^"'\n]+)\3""",
    re.MULTILINE)
_DYNAMIC_IMPORT = re.compile(r"""\bimport\(\s*(["'])(\.{1,2}/[^"'\n]+)\1\s*\)""")


def _local(reference: str) -> bool:
    return not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", reference, re.I)


def _resolve(importer: str, reference: str) -> str:
    target = posixpath.normpath(posixpath.join(posixpath.dirname(importer),
                                               reference.split("?", 1)[0]))
    assert not target.startswith("../"), (importer, reference)
    return target


def _module_graph(read, carried: set[str]) -> tuple[set[str], set[str]]:
    """`(reached, dynamic)`: every bundle path a browser fetches from `/`, and
    every relative dynamic `import()` target any reached module names.

    The walk starts at the page's references and follows each module's static
    imports. A dynamic target the bundle CARRIES is a module a browser can
    load too, so it is walked like any other (Copilot review of
    openDox-code#73: `views/repo-selector.js` loads `views/projection-index.js`
    that way); one the bundle does not carry, 10.2a's, stays a leaf.
    `read(path)` answers a path's text."""
    page = "index.html"
    queue = [_resolve(page, ref) for ref in _PAGE_REFERENCE.findall(read(page))
             if _local(ref)]
    reached, dynamic = {page}, set()
    while queue:
        path = queue.pop()
        if path in reached:
            continue
        reached.add(path)
        if not path.endswith(".js"):
            continue
        text = read(path)
        for match in _STATIC_IMPORT.finditer(text):
            reference = match.group(2) or match.group(4)
            if reference.startswith((".", "/")):
                queue.append(_resolve(path, reference))
        for match in _DYNAMIC_IMPORT.finditer(text):
            target = _resolve(path, match.group(2))
            dynamic.add(target)
            if target in carried:
                queue.append(target)
    return reached, dynamic


# ---------------------------------------------------------------------------
# 1 — the wheel carries the whole bundle
# ---------------------------------------------------------------------------

def test_the_wheel_carries_every_web_file_the_tree_holds(wheel: Path) -> None:
    """10.2's 42 files, all of them in the wheel `pip install ".[local]"`
    installs, and nothing under `opendox/web/` that the tree does not hold."""
    tree = _tree_files()
    assert len(tree) == BUNDLE_FILES, sorted(tree)
    assert NOT_OWED not in tree                              # 10.2a
    with zipfile.ZipFile(wheel) as archive:
        carried = {name[len("opendox/web/"):] for name in archive.namelist()
                   if name.startswith("opendox/web/") and not name.endswith("/")}
    assert sorted(tree - carried) == [], "the tree holds files the wheel omits"
    assert sorted(carried - tree) == [], "the wheel carries files the tree does not"


# ---------------------------------------------------------------------------
# 2 — F10.1's fetch, over every file, from the installed local entry point
# ---------------------------------------------------------------------------

def test_F10_1_fetch_the_installed_local_entry_point_serves_every_bundle_file(
        installed: tuple[Path, Path], state_dir: Path, tmp_path: Path) -> None:
    """`opendox generate-and-open --local --no-open`, as installed, from a
    directory that is not a checkout: `/` is the bundle's page, every one of
    the 42 files answers with the tree's bytes, the browser's module graph
    closes inside the bundle, and 10.2a's file is the one that is absent."""
    script, site = installed
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    repo = _fresh_repository(tmp_path)
    env = _child_env(site, **{PREFIX + "STATE_DIR": str(state_dir)})

    # F10.1's preconditions, in the environment the server runs in: no
    # sibling importable, the console script exists, and the `opendox` it
    # runs is the installed one, whose bundle is the wheel's copy.
    probe = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util, sys\n"
         f"present = [n for n in {SIBLINGS!r} if importlib.util.find_spec(n)]\n"
         "if present:\n"
         "    print('importable siblings:', present, file=sys.stderr)\n"
         f"    sys.exit({SIBLING_PRESENT})\n"
         "from opendox import cli\n"
         "print(cli.WEB_DIR.resolve())\n"],
        cwd=elsewhere, env=env, capture_output=True, text=True, timeout=60)
    # Named, so a red here says WHICH sibling, and an import that fails for
    # another reason is not reported as one.
    assert probe.returncode != SIBLING_PRESENT, (
        f"a sibling is importable: {probe.stderr[-2000:]}")
    assert probe.returncode == 0, probe.stderr[-2000:]
    served_dir = Path(probe.stdout.strip().splitlines()[-1])
    assert served_dir.is_relative_to(site.resolve()), served_dir
    helped = subprocess.run([str(script), "--help"], cwd=elsewhere, env=env,
                            capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0, helped.stderr[-2000:]

    # Both streams go to FILES: the server logs every request on standard
    # error, and an unread pipe that fills would stall it mid-fetch.
    out, err = tmp_path / "entry-point.stdout", tmp_path / "entry-point.stderr"
    with out.open("wb") as stdout, err.open("wb") as stderr:
        child = subprocess.Popen(
            [str(script), "generate-and-open", "--local",
             "--repo-root", str(repo), "--repository", "fixture",
             "--run-dir", str(tmp_path / "run"), "--no-open", "--port", "0"],
            cwd=elsewhere, env=env, stdout=stdout, stderr=stderr)

    def said() -> str:
        return err.read_text(encoding="utf-8", errors="replace")[-3000:]

    try:
        url = _served_url(child, out, START_SECONDS)
        if url is None:
            child.kill()
            child.wait(timeout=STOP_SECONDS)
            raise AssertionError(f"the installed entry point never served: {said()}")
        match = re.match(r"^http://([0-9.]+):([0-9]+)/index\.html$", url)
        assert match, url
        base = (match.group(1), int(match.group(2)))

        # F10.1's fetch, as written: `/` answers, and it is really the bundle.
        status, _kind, body = _get(base, "/")
        assert status == 200, status
        assert "<html" in body.decode("utf-8", "replace").lower()

        # ...widened to every file 10.2 counts.
        wrong = []
        for path in sorted(_tree_files()):
            status, kind, body = _get(base, "/" + path)
            suffix = Path(path).suffix
            if status != 200:
                wrong.append((path, f"status {status}"))
            elif body != (WEB / path).read_bytes():
                wrong.append((path, "not the tree's bytes"))
            elif suffix == ".js" and _essence(kind) not in JAVASCRIPT_TYPES:
                wrong.append((path, f"served as {kind!r}"))
            elif suffix in REQUIRED_TYPES and _essence(kind) not in REQUIRED_TYPES[suffix]:
                wrong.append((path, f"served as {kind!r}"))
        assert wrong == [], f"the installed entry point does not serve: {wrong}"

        # The graph a browser walks from `/` closes inside the bundle.
        def read(path: str) -> str:
            status, _kind, body = _get(base, "/" + path)
            assert status == 200, (path, status)
            return body.decode("utf-8")

        tree = _tree_files()
        reached, dynamic = _module_graph(read, tree)
        assert reached - tree == set(), sorted(reached - tree)
        assert {"app.js", "styles.css", "views/intent-binding.js",
                "views/projection-index.js"} <= reached

        # 10.2a: the one module the bundle reaches for and does not carry is
        # the declared one, reached only dynamically, and it is absent.
        assert dynamic - tree == {NOT_OWED}, sorted(dynamic - tree)
        status, _kind, _body = _get(base, "/" + NOT_OWED)
        assert status == 404, status

        bundled_pid = bundle_mod.running_pid(config.DatabaseBundle(state_dir))
        assert bundled_pid is not None, "no bundled server is running"
        child.send_signal(signal.SIGTERM)
        assert child.wait(timeout=STOP_SECONDS) == 0, said()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=STOP_SECONDS)
    assert bundle_mod.running_pid(config.DatabaseBundle(state_dir)) is None
