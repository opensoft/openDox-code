"""`.github/workflows/release.yml`, held to the gates it promises (plan 034 T099).

The release workflow publishes openDox to PyPI by trusted publishing (RULED
openxFactory#656 comment 5962754358, item 1), and it publishes only the commit
the openDox root pins (RULED 5963162921). Nothing executes a workflow until it
is dispatched, and a dispatch is a publish, so every gate it carries would
otherwise go unexercised until the one run that cannot be taken back. Copilot's
review of openDox-code#78 asked for this file.

SO THE STEPS' OWN SCRIPTS ARE WHAT RUN HERE, extracted from the workflow rather
than restated, as `tests/test_triple_pin.py` runs `validate.yml`'s pin. A copy
of a script in a test is a test of the copy.

EVERY CASE IS HERMETIC. The two steps that call `gh` run with a stand-in `gh`
first on `PATH`, which answers from the case's own fixture and records nothing,
so no case reaches GitHub (and `tests/hermeticity.py`'s refusal shim stays the
answer for any other `gh`). The release-commit step reads the openDox root's
pin over git, from `https://github.com/opensoft/openDox.git`. Each case
redirects that URL, through git's own `url.<base>.insteadOf` in the
environment's config, to a repository the case builds under its temporary
directory, so the step's script runs unchanged and reaches no network. No case
reaches an index. The one step that reads TestPyPI over HTTP is not run here;
it runs at the dry run.

What is held:
  * the shape: dispatch only, one `version` input, no secret, `id-token: write`
    on the two publish jobs alone, each in its own environment, every action
    pinned by a full commit SHA, and the four jobs chained;
  * the release-commit step: the pinned commit on `main` passes, and a commit
    the openDox root does not pin, a commit off `main`, another repository's
    pin, a tag other than `v<version>`, an unreachable root and a root with no
    pin each refuse. The pin is read over git with no credential, and the
    step's one `gh` call is the compare with this repository's `main`;
  * the environment step: both environments with a reviewer pass, and either
    one without a reviewer, or unreadable, refuses;
  * the version gate, case by case, a pre-release and a development release
    among the refusals;
  * the artifact checks, over a small built-by-hand wheel and sdist in a git
    tree of their own: the whole set passes, and each kind of gap refuses;
  * the publish jobs' digest check: the verified files pass, and a changed
    byte or a third file refuses.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
REPOSITORY = "opensoft/openDox-code"
PINNED = "047bb4fa394f3e1bf42466062a67ef18e99f8d6a"

needs_a_shell = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="the steps are bash scripts, and the artifact checks read git")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> dict:
    for step in _workflow()["jobs"][job]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"the {job} job has no step named {name!r}")


def _shim(where: Path) -> Path:
    """A directory holding `python`, this interpreter, which has `packaging`."""
    where.mkdir(parents=True, exist_ok=True)
    python = where / "python"
    if not python.exists():
        python.symlink_to(sys.executable)
    return where


def _run(script: str, cwd: Path, env: dict[str, str],
         path: tuple[Path, ...] = ()) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": os.pathsep.join([*(str(p) for p in path),
                                 os.environ.get("PATH", "/usr/bin:/bin")]),
        "HOME": str(cwd),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "LANG": "C.UTF-8",
    }
    return subprocess.run(
        ("bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script),
        cwd=cwd, env={**base, **env}, capture_output=True, text=True)


def _tools(runner_temp: Path) -> Path:
    """`$RUNNER_TEMP/tools/bin/python`, the release tools' interpreter."""
    return _shim(runner_temp / "tools" / "bin")


# ---------------------------------------------------------------------------
# The shape.


def test_the_workflow_runs_only_when_dispatched_with_one_version_input() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))  # YAML 1.1 reads `on` as True
    assert list(triggers) == ["workflow_dispatch"], triggers
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["version"]
    assert inputs["version"]["required"] is True


def test_only_the_two_publish_jobs_can_mint_an_identity_token() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    minting = {name for name, job in workflow["jobs"].items()
               if (job.get("permissions") or {}).get("id-token") == "write"}
    assert minting == {"testpypi", "pypi"}
    for name in minting:
        assert workflow["jobs"][name]["environment"]["name"] == name


def test_no_secret_and_no_password_is_named() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in text
    for job in _workflow()["jobs"].values():
        for step in job["steps"]:
            if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@"):
                assert not {"password", "user"} & set(step.get("with") or {}), step


def test_every_action_is_pinned_by_a_full_commit_sha() -> None:
    lines = [line.strip() for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
             if re.match(r"\s*-?\s*uses:", line)]
    assert lines
    for line in lines:
        assert re.fullmatch(r"-?\s*uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\S+", line), line


def test_the_four_jobs_are_chained() -> None:
    jobs = _workflow()["jobs"]
    needs = {name: sorted([job["needs"]] if isinstance(job.get("needs"), str)
                          else job.get("needs", []))
             for name, job in jobs.items()}
    assert needs == {"build": [], "testpypi": ["build"],
                     "testpypi-install": ["build", "testpypi"],
                     "pypi": ["build", "testpypi-install"]}


# ---------------------------------------------------------------------------
# The release-commit step and the environment step, with a stand-in `gh`.

FAKE_GH = """#!/usr/bin/env bash
# A stand-in `gh`: it answers from the case's fixture and records nothing.
case "$*" in
  *compare/*) printf '%s\\n' "$FAKE_STATUS" ;;
  *environments/*)
    args="$*"; environment="${args##*environments/}"; environment="${environment%% *}"
    variable="FAKE_REVIEWERS_${environment}"
    [ -z "${!variable:-}" ] && { echo "HTTP 404" >&2; exit 1; }
    printf '%s\\n' "${!variable}" ;;
  *) echo "the stand-in gh has no answer for: $*" >&2; exit 2 ;;
esac
"""


def _fake_gh(where: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    gh = where / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    return _shim(where)


def _pin(commit: str, source: str = REPOSITORY) -> str:
    return (f'leg_role: code\nsource_repository: {source}\nsubmodule_path: code\n\n'
            f'commit: "{commit}"\nrevision_kind: commit\n')


ROOT_URL = "https://github.com/opensoft/openDox.git"


def _root(where: Path, pin: str | None) -> Path:
    """A stand-in openDox root: a repository whose `main` carries `pin` as
    `contracts/code-pin.yaml`, or carries no pin at all when `pin` is None."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(where),
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "root", "GIT_AUTHOR_EMAIL": "root@example.invalid",
           "GIT_COMMITTER_NAME": "root", "GIT_COMMITTER_EMAIL": "root@example.invalid"}
    where.mkdir(parents=True)
    subprocess.run(("git", "init", "-q", "-b", "main", str(where)), check=True, env=env)
    if pin is None:
        (where / "README.md").write_text("no pin\n", encoding="utf-8")
    else:
        (where / "contracts").mkdir()
        (where / "contracts" / "code-pin.yaml").write_text(pin, encoding="utf-8")
    subprocess.run(("git", "-C", str(where), "add", "-A"), check=True, env=env)
    subprocess.run(("git", "-C", str(where), "commit", "-q", "-m", "root"), check=True, env=env)
    return where


def _redirect(to: Path) -> dict[str, str]:
    """Git config, in the environment, that sends the root's URL to `to`.

    `GIT_ALLOW_PROTOCOL=file` makes git refuse every other transport, so a
    redirect that failed to apply would refuse the fetch rather than read the
    real root over the network: no case can pass by reaching GitHub."""
    return {"GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{to.as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": ROOT_URL,
            "GIT_ALLOW_PROTOCOL": "file"}


RELEASE_COMMIT_CASES = {
    "the pinned commit, at main's head": (
        dict(sha=PINNED, pin=_pin(PINNED), status="identical"), None),
    "the pinned commit, with main moved past it": (
        dict(sha=PINNED, pin=_pin(PINNED), status="ahead"), None),
    "the pinned commit, dispatched on its v<version> tag": (
        dict(sha=PINNED, pin=_pin(PINNED), status="ahead", ref="refs/tags/v0.1.0"), None),
    "a commit the root does not pin": (
        dict(sha="1" * 40, pin=_pin(PINNED), status="identical"),
        "a release publishes only the pinned commit"),
    "the pinned commit, off main": (
        dict(sha=PINNED, pin=_pin(PINNED), status="behind"),
        "is not on this repository's main"),
    "another repository's pin": (
        dict(sha=PINNED, pin=_pin(PINNED, "opensoft/openXdox-code"), status="identical"),
        "not 'opensoft/openDox-code'"),
    "a pin with no full commit": (
        dict(sha=PINNED, pin=_pin("047bb4fa"), status="identical"),
        "names no full commit"),
    "a tag other than v<version>": (
        dict(sha=PINNED, pin=_pin(PINNED), status="identical", ref="refs/tags/latest"),
        "names v0.1.0"),
    "an unreachable root": (
        dict(sha=PINNED, pin=_pin(PINNED), status="identical", unreachable=True),
        "cannot be read"),
    "a root with no pin": (
        dict(sha=PINNED, pin=None, status="identical"),
        "cannot be read"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(RELEASE_COMMIT_CASES))
def test_the_release_commit_step(case: str, tmp_path: Path) -> None:
    given, refusal = RELEASE_COMMIT_CASES[case]
    step = _step("build", "the dispatched commit is the one the openDox root pins")
    root = _root(tmp_path / "root", given["pin"])
    if given.get("unreachable"):
        root = tmp_path / "no-such-root"
    (tmp_path / "rt").mkdir()
    env = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_SHA": given["sha"],
           "GITHUB_REF": given.get("ref", "refs/heads/main"), "VERSION": "0.1.0",
           "RUNNER_TEMP": str(tmp_path / "rt"), "FAKE_STATUS": given["status"],
           "GH_TOKEN": "unused", **_redirect(root)}
    result = _run(step["run"], tmp_path, env, (_fake_gh(tmp_path / "bin"),))
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "is the commit opensoft/openDox main pins" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr


def test_the_root_pin_is_read_over_git_with_no_credential() -> None:
    script = _step("build", "the dispatched commit is the one the openDox root pins")["run"]
    assert "contents/contracts/code-pin.yaml" not in script
    assert re.search(r'GIT_TERMINAL_PROMPT=0 git -C "\$root" -c credential\.helper= \\\n'
                     r'\s+fetch -q --depth 1 --no-tags ' + re.escape(ROOT_URL) + r' main', script), script
    calls = [line.strip() for line in script.splitlines() if re.search(r"\bgh\b", line)]
    assert len(calls) == 1 and "/compare/" in calls[0], calls


ENVIRONMENT_CASES = {
    "both name a reviewer": (dict(testpypi="1", pypi="1"), None),
    "pypi names none": (dict(testpypi="1", pypi="0"), "the pypi environment names no required reviewer"),
    "testpypi does not exist": (dict(pypi="1"), "the testpypi environment cannot be read"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(ENVIRONMENT_CASES))
def test_the_environment_step(case: str, tmp_path: Path) -> None:
    reviewers, refusal = ENVIRONMENT_CASES[case]
    step = _step("build", "both environments ask a reviewer before they deploy")
    env = {"GITHUB_REPOSITORY": REPOSITORY, "GH_TOKEN": "unused",
           **{f"FAKE_REVIEWERS_{name}": count for name, count in reviewers.items()}}
    result = _run(step["run"], tmp_path, env, (_fake_gh(tmp_path / "bin"),))
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# The version gate.

VERSION_CASES = {
    "the declared version": ("0.1.0", "0.1.0", None),
    "another version": ("0.1.0", "0.2.0", "they must be equal"),
    "a version not in normalized form": ("0.1.0", "v0.1.0", "normalized form"),
    "a local label": ("0.1.0", "0.1.0+local", "local label"),
    "an epoch": ("1!2.0", "1!2.0", "carries an epoch"),
    "the placeholder": ("0.0.0", "0.0.0", "the scaffold's placeholder"),
    "no version at all": ("0.1.0", "banana", "is not a PEP 440 version"),
    "a pre-release": ("0.2.0rc1", "0.2.0rc1", "is a pre-release or a development release"),
    "a development release": ("0.2.0.dev1", "0.2.0.dev1",
                              "is a pre-release or a development release"),
    "a post-release": ("0.1.0.post1", "0.1.0.post1", None),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(VERSION_CASES))
def test_the_version_gate(case: str, tmp_path: Path) -> None:
    declared, asked, refusal = VERSION_CASES[case]
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "opendox"\nversion = "{declared}"\n', encoding="utf-8")
    _tools(tmp_path / "rt")
    step = _step("build", "the version input is pyproject's version")
    result = _run(step["run"], tmp_path, {"VERSION": asked, "RUNNER_TEMP": str(tmp_path / "rt")})
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# The artifact checks, over a wheel and an sdist built by hand.

PYPROJECT = """[project]
name = "opendox"
version = "0.1.0"
dependencies = ["PyYAML>=6.0"]

[project.optional-dependencies]
runtime = ["fastapi>=0.115"]
local = ["opendox[runtime]", "pixeltable-pgserver>=0.6.0"]
"""

REQUIRES = ["PyYAML>=6.0", 'fastapi>=0.115; extra == "runtime"',
            'opendox[runtime]; extra == "local"', 'pixeltable-pgserver>=0.6.0; extra == "local"']

TREE = {
    "src/.gitkeep": "",
    "src/opendox/__init__.py": "",
    "src/opendox/cli.py": "def main():\n    return 0\n",
    "src/opendox/web/index.html": "<!doctype html>\n",
    "src/opendox/web/vendor/.gitkeep": "",
    "src/route_extension.py": "",
    "migrations/0001_first.sql": "select 1;\n",
}


def _tree(where: Path) -> None:
    (where / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    for path, text in TREE.items():
        (where / path).parent.mkdir(parents=True, exist_ok=True)
        (where / path).write_text(text, encoding="utf-8")
    git = ("git", "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "init.defaultBranch=main")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "tree")):
        subprocess.run((*git, *args), cwd=where, check=True, env=env, capture_output=True)


def _wheel(where: Path, *, drop: str = "", add: str = "", requires: list[str] | None = None,
           scripts: str = "opendox = opendox.cli:main") -> None:
    dist = where / "dist"
    dist.mkdir(exist_ok=True)
    info, data = "opendox-0.1.0.dist-info", "opendox-0.1.0.data/data"
    requires = REQUIRES if requires is None else requires
    metadata = ("Metadata-Version: 2.4\nName: opendox\nVersion: 0.1.0\n"
                + "".join(f"Provides-Extra: {e}\n" for e in ("runtime", "local"))
                + "".join(f"Requires-Dist: {r}\n" for r in requires))
    members = {
        **{p.removeprefix("src/"): t for p, t in TREE.items()
           if p.startswith("src/") and p != "src/.gitkeep"},
        f"{data}/share/opendox/migrations/0001_first.sql": TREE["migrations/0001_first.sql"],
        f"{info}/METADATA": metadata,
        f"{info}/entry_points.txt": f"[console_scripts]\n{scripts}\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\n",
    }
    members.pop(drop, None)
    if add:
        members[add] = ""
    with zipfile.ZipFile(dist / "opendox-0.1.0-py3-none-any.whl", "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    (dist / "opendox-0.1.0.tar.gz").write_bytes(b"an sdist stands here")


ARTIFACT_CASES = {
    "the whole set": ({}, None),
    "a web dotfile missing": (dict(drop="opendox/web/vendor/.gitkeep"), "the wheel lacks web files"),
    "a top-level module missing": (dict(drop="route_extension.py"), "the wheel lacks tracked files"),
    "a stray file": (dict(add="opendox/stray.txt"), "the tree does not track"),
    "a migration missing": (dict(drop="opendox-0.1.0.data/data/share/opendox/migrations/0001_first.sql"),
                            "the wheel lacks migrations"),
    "the server's package dropped from the local extra": (
        dict(requires=[r for r in REQUIRES if "pixeltable" not in r]), "are not pyproject.toml's"),
    "a requirement the tree does not declare": (
        dict(requires=[*REQUIRES, 'httpx>=0.27; extra == "local"']), "are not pyproject.toml's"),
    "no console script": (dict(scripts="opendox-runtime = opendox.runtime.cli:main"),
                          "the console script `opendox = opendox.cli:main` is not declared"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(ARTIFACT_CASES))
def test_the_artifact_checks(case: str, tmp_path: Path) -> None:
    mutation, refusal = ARTIFACT_CASES[case]
    _tree(tmp_path)
    _wheel(tmp_path, **mutation)
    _tools(tmp_path / "rt")
    step = _step("build", "verify the artifacts")
    result = _run(step["run"], tmp_path, {"VERSION": "0.1.0", "RUNNER_TEMP": str(tmp_path / "rt")})
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "5. web bundle: 2 of 2 tracked files are in the wheel" in result.stdout
        assert "the artifacts carry what an install runs from" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout, result.stdout + result.stderr


@needs_a_shell
def test_the_artifact_checks_refuse_a_third_file(tmp_path: Path) -> None:
    _tree(tmp_path)
    _wheel(tmp_path)
    (tmp_path / "dist" / "evil-0.1.0-py3-none-any.whl").write_bytes(b"")
    _tools(tmp_path / "rt")
    step = _step("build", "verify the artifacts")
    result = _run(step["run"], tmp_path, {"VERSION": "0.1.0", "RUNNER_TEMP": str(tmp_path / "rt")})
    assert result.returncode != 0
    assert "a release is exactly" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# The publish jobs' digest check.


@needs_a_shell
@pytest.mark.parametrize("job", ["testpypi", "pypi"])
@pytest.mark.parametrize("change", ["none", "a changed byte", "a third file"])
def test_the_publish_jobs_check_the_digests(job: str, change: str, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel, sdist = "opendox-0.1.0-py3-none-any.whl", "opendox-0.1.0.tar.gz"
    (dist / wheel).write_bytes(b"the wheel")
    (dist / sdist).write_bytes(b"the sdist")
    env = {"WHEEL": wheel, "SDIST": sdist,
           "WHEEL_SHA256": hashlib.sha256(b"the wheel").hexdigest(),
           "SDIST_SHA256": hashlib.sha256(b"the sdist").hexdigest()}
    if change == "a changed byte":
        (dist / wheel).write_bytes(b"the wheeL")
    elif change == "a third file":
        (dist / "evil-0.1.0-py3-none-any.whl").write_bytes(b"")
    step = _step(job, "the files are the ones the build job verified")
    result = _run(step["run"], tmp_path, env)
    assert (result.returncode == 0) == (change == "none"), result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Re-running an upload, and what each index serves after it.


def test_both_uploads_skip_a_file_the_index_already_holds() -> None:
    """A re-run after a partial upload uploads the rest instead of stopping on
    the file already there (Copilot's review of openDox-code#78)."""
    for job in ("testpypi", "pypi"):
        uploads = [step for step in _workflow()["jobs"][job]["steps"]
                   if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@")]
        assert len(uploads) == 1, job
        assert uploads[0]["with"]["skip-existing"] is True, job


INDEX_STEPS = {"TestPyPI": ("testpypi-install", "TestPyPI serves the files the build job verified"),
               "PyPI": ("pypi", "PyPI serves the files the build job verified")}


def test_each_upload_is_followed_by_one_index_check_script() -> None:
    """skip-existing can only skip a file name the index already holds, so
    each upload is followed by the check that the index serves exactly the two
    verified digests. Both checks are the same script, differing only in the
    index they read."""
    jobs = _workflow()["jobs"]
    steps = {index: _step(job, name) for index, (job, name) in INDEX_STEPS.items()}
    assert steps["TestPyPI"]["run"] == steps["PyPI"]["run"]
    assert steps["TestPyPI"]["env"]["JSON_BASE"] == "https://test.pypi.org/pypi/opendox/"
    assert steps["PyPI"]["env"]["JSON_BASE"] == "https://pypi.org/pypi/opendox/"
    for index, step in steps.items():
        assert step["env"]["INDEX"] == index
        assert (step["env"]["READS"], step["env"]["PAUSE"]) == ("20", "15")
    names = [step.get("name") or step.get("uses") for step in jobs["pypi"]["steps"]]
    upload = next(i for i, step in enumerate(jobs["pypi"]["steps"])
                  if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@"))
    assert names[upload + 1] == INDEX_STEPS["PyPI"][1], names


class _Index:
    """A local JSON API: `answers` is the list of (status, files) it gives,
    one per request, the last one repeated."""

    def __init__(self, answers: list[tuple[int, dict[str, str]]]) -> None:
        import http.server
        import threading

        self.answers, self.requests = answers, []
        index = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (the stdlib's name)
                index.requests.append(self.path)
                status, files = index.answers[min(len(index.requests), len(index.answers)) - 1]
                body = json.dumps({"urls": [{"filename": name, "digests": {"sha256": digest}}
                                            for name, digest in files.items()]}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/pypi/opendox/"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


WHEEL_FILE, SDIST_FILE = "opendox-0.1.0-py3-none-any.whl", "opendox-0.1.0.tar.gz"
VERIFIED = {WHEEL_FILE: "a" * 64, SDIST_FILE: "b" * 64}

INDEX_CASES = {
    "it serves exactly the verified files": ([(200, VERIFIED)], None),
    "it lags, then serves them": ([(404, {}), (200, {WHEEL_FILE: "a" * 64}), (200, VERIFIED)], None),
    "it serves another sdist": ([(200, {**VERIFIED, SDIST_FILE: "c" * 64})], "after 3 reads"),
    "it serves a third file": ([(200, {**VERIFIED, "opendox-0.1.0-py2-none-any.whl": "d" * 64})],
                               "after 3 reads"),
    "it refuses the read": ([(403, {})], "HTTP Error 403"),
}


@needs_a_shell
@pytest.mark.parametrize("index", sorted(INDEX_STEPS))
@pytest.mark.parametrize("case", sorted(INDEX_CASES))
def test_the_index_check(index: str, case: str, tmp_path: Path) -> None:
    answers, refusal = INDEX_CASES[case]
    step = _step(*INDEX_STEPS[index])
    server = _Index(answers)
    try:
        env = {"INDEX": index, "JSON_BASE": server.base, "READS": "3", "PAUSE": "0",
               "VERSION": "0.1.0", "WHEEL": WHEEL_FILE, "WHEEL_SHA256": "a" * 64,
               "SDIST": SDIST_FILE, "SDIST_SHA256": "b" * 64}
        result = _run(step["run"], tmp_path, env, (_python3(tmp_path / "bin"),))
    finally:
        server.close()
    assert server.requests and set(server.requests) == {"/pypi/opendox/0.1.0/json"}
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{index} serves exactly the verified files" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr


def _python3(where: Path) -> Path:
    """A directory holding `python3`, this interpreter."""
    where.mkdir(parents=True, exist_ok=True)
    python3 = where / "python3"
    if not python3.exists():
        python3.symlink_to(sys.executable)
    return where


def _seconds(text: str, pattern: str) -> int:
    found = re.search(pattern, text)
    assert found, pattern
    return int(found.group(1))


def test_each_job_timeout_covers_the_retries_it_promises() -> None:
    """A job cut off by its timeout would break a promised retry (Copilot's
    review of openDox-code#78), so each budget is recomputed from the steps."""
    jobs = _workflow()["jobs"]
    check = _step(*INDEX_STEPS["TestPyPI"])
    per_read = _seconds(check["run"], r"urlopen\(url, timeout=(\d+)\)")
    reads, pause = int(check["env"]["READS"]), int(check["env"]["PAUSE"])
    json_budget = reads * (per_read + pause)
    install = _step("testpypi-install", "install opendox[local] from TestPyPI into a fresh venv, and run it")["run"]
    tries = len(re.search(r"for attempt in ((?:\d+ ?)+); do", install).group(1).split())
    per_try = _seconds(install, r"timeout (\d+) \"\$RUNNER_TEMP/fresh/bin/python\" -m pip install")
    wait = _seconds(install, r"sleep (\d+)")
    setup = 5 * 60
    assert jobs["testpypi-install"]["timeout-minutes"] * 60 >= (
        json_budget + tries * (per_try + wait) + setup)
    upload = 10 * 60
    assert jobs["pypi"]["timeout-minutes"] * 60 >= upload + json_budget + setup
