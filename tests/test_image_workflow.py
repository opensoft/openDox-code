"""`.github/workflows/image.yml`, held to the gates it promises.

The image workflow builds the runtime image and pushes it to the QA registry
by OIDC, behind the `acr-qa` environment (`docs/image-release.md`). Nothing
executes a workflow until it is dispatched, and its push cannot run until an
Azure identity exists, so every gate it carries would otherwise go unexercised
until the first real push.

SO THE STEPS' OWN SCRIPTS ARE WHAT RUN HERE, extracted from the workflow rather
than restated, as `tests/test_release_workflow.py` runs `release.yml`'s. A copy
of a script in a test is a test of the copy.

EVERY CASE IS HERMETIC. `gh`, `docker`, `az` and `curl` are stand-ins first on
`PATH`, each answering from the case's own fixture and recording its argv in
the case's directory, so no case reaches GitHub, a Docker daemon, Azure or a
download (and `tests/hermeticity.py`'s refusal shim stays the answer for any
other `gh`). The revision step reads this repository's tags over git; each
case redirects that URL, through git's own `url.<base>.insteadOf` in the
environment's config, to a repository it builds, and `GIT_ALLOW_PROTOCOL=file`
refuses every other transport, so a redirect that failed to apply refuses the
read rather than reaching the network.

What is held:
  * the shape: dispatch only, a `revision` input and a `target` choice of `qa`
    alone, no `pull_request_target`, `id-token: write` on the push job alone,
    in `acr-qa`, every action pinned by a full commit SHA (checkout and the
    artifact actions at `release.yml`'s own pins), no expression inside any
    `run:` script, no estate identifier in the file, and each job's timeout
    covering its steps';
  * the Azure IDs: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and
    `AZURE_SUBSCRIPTION_ID` are environment SECRETS (Brett Heap, 2026-11-17,
    "Secrets"), read from `secrets` and never from `vars`, in the push job
    alone, which names the environment that holds them, and by the two places
    that need them; `ACR_NAME` stays a variable;
  * the order: the image is recorded and uploaded before Trivy runs, and the
    push job checks its secrets and variable, its approval and the archive
    before it signs in;
  * the target step: `qa` passes with an empty scan gate, and anything else,
    `prod` among them, refuses;
  * the revision step: a full commit on `main` passes, and one off `main` or
    unknown refuses; a tag resolves to its commit (an annotated one to the
    commit it points at, and a tag beside a branch of the same name to the
    tag's), and a branch name, an abbreviated commit, a name an image tag
    cannot carry and unreadable tags each refuse;
  * the environment step and the approval step (the latter `release.yml`'s own
    script, byte for byte);
  * the build step builds at the gated commit only, with the flags it names;
  * the record step and the load step: the revision label, the platform, the
    archive's sha256 and the image ID each refuse a mismatch;
  * Trivy is unpacked only at its recorded sha256;
  * the scan's verdict: report only with an empty gate, and with a gate, a
    finding at a gated severity, a misspelt gate and an unreadable report each
    refuse;
  * the settings step names each missing or malformed secret or variable, and
    prints no value;
  * the push step: `az acr login` with no resource group, the server from the
    cloud's suffix, lowercased, the digest from the push, read back by a pull,
    and a missing digest or another image refusing;
  * the record step writes the four fields the record promises, and no
    registry host;
  * the workflow, the operator page and this file name no deployment
    repository, no path inside one and no estate domain: the next step is
    "the deployment repository's QA overlay", and the step summary says the
    same;
  * the operator page (`docs/image-release.md`) gives no hand `az` command that
    creates the identity, its federated credential or the role assignment
    (Terraform provisions them, 2026-11-17, "Terraform"), sets the three IDs
    as secrets, from a command's output and never a typed literal, and holds
    no identifier of the estate.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "image.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
REPOSITORY = "opensoft/openDox-code"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}.git"
OPERATOR_PAGE = ROOT / "docs" / "image-release.md"
# Environment SECRETS of `acr-qa` (2026-11-17, "Secrets"); `ACR_NAME` is a variable.
AZURE_IDS = ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID")
# What a public repository must not spell: the estate's deployment repository
# (Brett Heap, 2026-11-17: "Remove tenant name from #104"), a path inside it,
# and the estate's domain. Built from parts so that this file does not spell
# them itself, and matched without regard to case.
ESTATE_MARKERS = ("opensoft" + "-tenant", "gitops" + "/", "kustomization" + ".yaml", "opensoft" + ".dev")

needs_a_shell = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="the steps are bash scripts, and the revision step reads git")


def _workflow(path: Path = WORKFLOW) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step(job: str, name: str, path: Path = WORKFLOW) -> dict:
    for step in _workflow(path)["jobs"][job]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"the {job} job has no step named {name!r}")


def _names(job: str) -> list[str]:
    return [step.get("name") or step["uses"].split("@")[0] for step in _workflow()["jobs"][job]["steps"]]


def _run(script: str, cwd: Path, env: dict[str, str],
         path: tuple[Path, ...] = ()) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": os.pathsep.join([*(str(p) for p in path),
                                 os.environ.get("PATH", "/usr/bin:/bin")]),
        "HOME": str(cwd),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "LANG": "C.UTF-8",
        "IMAGE_NAME": "opendox-runtime",
        "TARGET": "qa",
    }
    return subprocess.run(
        ("bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script),
        cwd=cwd, env={**base, **env}, capture_output=True, text=True)


def _python3(where: Path) -> Path:
    """A directory holding `python3`, this interpreter."""
    where.mkdir(parents=True, exist_ok=True)
    python3 = where / "python3"
    if not python3.exists():
        python3.symlink_to(sys.executable)
    return where


def _stand_in(where: Path, name: str, script: str) -> Path:
    """An executable `name` in `where`, and `python3` beside it."""
    where.mkdir(parents=True, exist_ok=True)
    tool = where / name
    tool.write_text(script, encoding="utf-8")
    tool.chmod(0o755)
    return _python3(where)


def _outputs(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)


def _log(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


# ---------------------------------------------------------------------------
# The shape.


def test_the_workflow_runs_only_when_dispatched_with_a_revision_and_a_qa_target() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))  # YAML 1.1 reads `on` as True
    assert list(triggers) == ["workflow_dispatch"], triggers
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["revision", "target"]
    assert inputs["revision"]["required"] is True
    assert inputs["revision"]["type"] == "string"
    assert inputs["target"]["type"] == "choice"
    assert inputs["target"]["options"] == ["qa"]
    assert "pull_request_target" not in WORKFLOW.read_text(encoding="utf-8")


def test_only_the_push_job_can_mint_an_identity_token_and_it_runs_in_acr_qa() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {}
    jobs = workflow["jobs"]
    minting = {name for name, job in jobs.items()
               if (job.get("permissions") or {}).get("id-token") == "write"}
    assert minting == {"push"}
    assert jobs["push"]["environment"]["name"] == "acr-qa"
    assert jobs["push"]["permissions"] == {"id-token": "write", "actions": "read"}
    assert jobs["build"]["permissions"] == {"contents": "read", "actions": "read"}
    assert "environment" not in jobs["build"]
    assert jobs["push"]["needs"] == "build"


def _strings(node: object):
    """Every string of a parsed document, keys included."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _strings(item)


def _reads(node: object) -> list[tuple[str, str]]:
    """Each `secrets.NAME` and `vars.NAME` read inside a `${{ }}` expression
    of the parsed document, as (context, NAME). Comments are not parsed, and a
    `run:` script holds no expression (another test), so only real reads count."""
    return [match for text in _strings(node)
            for expression in re.findall(r"\$\{\{(.*?)\}\}", text, re.S)
            for match in re.findall(r"\b(secrets|vars)\.(\w+)", expression)]


def test_the_three_azure_ids_are_secrets_read_in_two_places_and_never_variables() -> None:
    """Brett Heap, 2026-11-17: the IDs are environment secrets, so that GitHub
    masks them in a public repository's run logs. Each is read exactly twice,
    by the step that checks it is set and by `azure/login`, and the registry's
    name stays a variable."""
    reads = _reads(_workflow())
    for name in AZURE_IDS:
        assert reads.count(("secrets", name)) == 2, (name, reads)
        assert ("vars", name) not in reads, f"{name} is read from vars"
    assert reads.count(("vars", "ACR_NAME")) == 2, reads
    assert ("secrets", "ACR_NAME") not in reads
    assert sorted(set(reads)) == sorted([("secrets", name) for name in AZURE_IDS] + [("vars", "ACR_NAME")]), reads
    # Not even in a comment: nothing in the file spells an Azure ID as a variable.
    assert not re.search(r"\bvars\.AZURE_", WORKFLOW.read_text(encoding="utf-8"))


def test_a_secret_is_read_only_in_a_job_that_names_the_acr_qa_environment() -> None:
    """An environment's secrets reach a job only if it names the environment
    (and only after its approval). The build job names none and reads none, and
    nothing outside the jobs (the workflow's own `env`) reads any."""
    workflow = _workflow()
    jobs = workflow["jobs"]
    for name, job in jobs.items():
        secrets = [secret for kind, secret in _reads(job) if kind == "secrets"]
        if secrets:
            assert (job.get("environment") or {}).get("name") == "acr-qa", (name, secrets)
    assert [kind for kind, _ in _reads(jobs["build"]) if kind == "secrets"] == []
    assert _reads({key: value for key, value in workflow.items() if key != "jobs"}) == []


def test_no_step_prints_or_passes_an_azure_id_but_the_check_and_the_login() -> None:
    """Outside the step that checks the settings and `azure/login`, no step's
    script or environment mentions an Azure ID, so no step can echo one."""
    for job_name, job in _workflow()["jobs"].items():
        for step in job["steps"]:
            if step.get("name") == SETTINGS_STEP or step.get("uses", "").startswith("azure/login@"):
                continue
            for name in AZURE_IDS:
                assert name not in json.dumps(step), (job_name, step.get("name"), name)


def _uses(path: Path) -> list[str]:
    return [line.strip().removeprefix("- ").strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if re.match(r"\s*-?\s*uses:", line)]


def test_every_action_is_pinned_by_a_full_commit_sha_and_shares_release_yml_pins() -> None:
    lines = _uses(WORKFLOW)
    assert lines
    for line in lines:
        assert re.fullmatch(r"uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\S+", line), line
    release = set(_uses(RELEASE))
    for line in lines:
        if line.startswith(("uses: actions/checkout@", "uses: actions/upload-artifact@",
                            "uses: actions/download-artifact@")):
            assert line in release, f"{line} is not release.yml's pin"


def test_no_expression_is_pasted_into_a_run_script() -> None:
    """Every input, output and variable reaches a script through `env:`, so
    no value can become shell or Python source."""
    for job_name, job in _workflow()["jobs"].items():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), (job_name, step.get("name"))


GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def test_no_estate_identifier_is_written_in_the_file() -> None:
    """The repository is public: the Azure IDs are secrets and the registry's
    name is a variable, read in exactly the places that need them."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not GUID.search(text), GUID.search(text)
    for literal in ("azurecr.io", "/subscriptions/", "resourceGroups"):
        assert literal not in text, literal
    assert sorted(set(_reads(_workflow()))) == [
        ("secrets", "AZURE_CLIENT_ID"), ("secrets", "AZURE_SUBSCRIPTION_ID"),
        ("secrets", "AZURE_TENANT_ID"), ("vars", "ACR_NAME")]
    login = next(step for step in _workflow()["jobs"]["push"]["steps"]
                 if step.get("uses", "").startswith("azure/login@"))
    assert login["with"] == {"client-id": "${{ secrets.AZURE_CLIENT_ID }}",
                             "tenant-id": "${{ secrets.AZURE_TENANT_ID }}",
                             "subscription-id": "${{ secrets.AZURE_SUBSCRIPTION_ID }}"}


def test_each_job_timeout_covers_its_steps() -> None:
    for name, job in _workflow()["jobs"].items():
        bounds = [step.get("timeout-minutes") for step in job["steps"]]
        assert all(isinstance(bound, int) and bound > 0 for bound in bounds), (name, bounds)
        assert job["timeout-minutes"] >= sum(bounds), (name, job["timeout-minutes"], bounds)


RECORD_STEP = "record the image and its archive"
TRIVY_STEP = "install Trivy from its pinned release, by sha256"
VERDICT_STEP = "the scan's verdict"


def test_the_image_is_recorded_and_uploaded_before_trivy_runs() -> None:
    names = _names("build")
    record, upload, trivy = (names.index(RECORD_STEP), names.index("actions/upload-artifact"),
                             names.index(TRIVY_STEP))
    assert record < upload < trivy, names
    upload_step = _workflow()["jobs"]["build"]["steps"][upload]
    assert upload_step["with"]["name"] == "image"
    assert upload_step["with"]["retention-days"] == 7
    outputs = _workflow()["jobs"]["build"]["outputs"]
    assert outputs["image-id"] == "${{ steps.image.outputs.image-id }}"
    assert outputs["archive-sha256"] == "${{ steps.image.outputs.archive-sha256 }}"


SETTINGS_STEP = "the Azure secrets and the registry variable are set"
APPROVAL_STEP = ("this environment still asks a reviewer and limits its refs, "
                 "and this run's deployment to it was approved")
LOAD_STEP = "the archive is the one the build job recorded, and loads as its image"
PUSH_STEP = "push the image, and read its digest back from the registry"
RELEASE_RECORD_STEP = "record the pushed image"


def test_the_push_job_checks_everything_before_it_signs_in() -> None:
    assert _names("push") == [SETTINGS_STEP, APPROVAL_STEP, "actions/download-artifact", LOAD_STEP,
                              "azure/login", PUSH_STEP, RELEASE_RECORD_STEP, "actions/upload-artifact"]


def test_the_approval_check_is_release_yml_own_script() -> None:
    mine = _step("push", APPROVAL_STEP)
    theirs = _step("pypi", APPROVAL_STEP, RELEASE)
    assert mine["run"] == theirs["run"]
    assert mine["env"] == {"GH_TOKEN": "${{ github.token }}", "ENVIRONMENT": "acr-qa"}


def test_the_qa_scan_gate_is_the_target_step_output() -> None:
    assert _step("build", VERDICT_STEP)["env"] == {"FAIL_ON": "${{ steps.target.outputs.scan-fail-on }}"}


# ---------------------------------------------------------------------------
# The target step.

TARGET_STEP = "the target's rules"


@needs_a_shell
@pytest.mark.parametrize("target", ["qa", "prod", "", "qa; true"])
def test_the_target_step(target: str, tmp_path: Path) -> None:
    output = tmp_path / "github-output"
    output.write_text("")
    result = _run(_step("build", TARGET_STEP)["run"], tmp_path,
                  {"TARGET": target, "GITHUB_OUTPUT": str(output)})
    if target == "qa":
        assert result.returncode == 0, result.stdout + result.stderr
        assert _outputs(output) == {"scan-fail-on": ""}
    else:
        assert result.returncode != 0, result.stdout
        assert "only qa exists" in result.stdout, result.stdout + result.stderr
        assert output.read_text() == ""


# ---------------------------------------------------------------------------
# The revision step, with a stand-in `gh` and a stand-in repository.

FAKE_GH = """#!/usr/bin/env bash
# A stand-in `gh`: it answers from the case's fixture and records its argv.
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$*" in
  *compare/*)
    [ -n "${FAKE_COMPARE_FAILS:-}" ] && { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
    printf '%s\\n' "$FAKE_STATUS" ;;
  *actions/runs/*/approvals*)
    [ -n "${FAKE_APPROVALS_FAILS:-}" ] && { echo "HTTP 404" >&2; exit 1; }
    printf '%s\\n' "$FAKE_APPROVALS" ;;
  *environments/*)
    args="$*"; environment="${args##*environments/}"; environment="${environment%% *}"
    variable="FAKE_ENVIRONMENT_${environment//-/_}"
    [ -z "${!variable:-}" ] && { echo "HTTP 404" >&2; exit 1; }
    printf '%s\\n' "${!variable}" ;;
  *) echo "the stand-in gh has no answer for: $*" >&2; exit 2 ;;
esac
"""

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(where: Path, *args: str) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(where), **GIT_ENV}
    return subprocess.run(("git", "-C", str(where), *args), check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


def _repository(where: Path) -> dict[str, str]:
    """A stand-in of this repository: two commits on `main`, an annotated tag
    `v0.1.0` at the first, a lightweight tag `light-1` at the second, and a
    branch `dup` at the first beside a TAG `dup` at the second."""
    where.mkdir(parents=True)
    _git(where, "init", "-q", "-b", "main")
    (where / "a.txt").write_text("one\n", encoding="utf-8")
    _git(where, "add", "-A")
    _git(where, "commit", "-q", "-m", "first")
    first = _git(where, "rev-parse", "HEAD")
    (where / "a.txt").write_text("two\n", encoding="utf-8")
    _git(where, "commit", "-q", "-am", "second")
    second = _git(where, "rev-parse", "HEAD")
    _git(where, "tag", "-a", "-m", "release", "v0.1.0", first)
    _git(where, "tag", "light-1", second)
    _git(where, "branch", "dup", first)
    _git(where, "tag", "dup", second)
    return {"first": first, "second": second, "tag-object": _git(where, "rev-parse", "v0.1.0")}


def _redirect(to: Path) -> dict[str, str]:
    """Git config, in the environment, that sends this repository's URL to `to`."""
    return {"GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{to.as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": REPOSITORY_URL,
            "GIT_ALLOW_PROTOCOL": "file"}


REVISION_STEP = "the revision is a tag or a full commit on this repository's main"
ANY = "c" * 40

# revision (or a key of the stand-in repository's commits), compare status,
# then None and the expected (sha, tag) for a pass, or the refusal's words.
REVISION_CASES = {
    "a full commit at main's head": (ANY, "identical", None, (ANY, ANY[:12])),
    "a full commit main has moved past": (ANY, "ahead", None, (ANY, ANY[:12])),
    "a full commit off main": (ANY, "diverged", "is not on this repository's main", None),
    "a full commit ahead of main": (ANY, "behind", "is not on this repository's main", None),
    "a commit this repository does not have": (ANY, "unknown", "cannot be compared", None),
    "an annotated tag": ("v0.1.0", "ahead", None, ("first", "v0.1.0")),
    "a lightweight tag": ("light-1", "identical", None, ("second", "light-1")),
    "a tag beside a branch of the same name": ("dup", "identical", None, ("second", "dup")),
    "a tag that does not exist": ("v9.9.9", "identical", "has no tag v9.9.9", None),
    "a branch name": ("main", "identical", "has no tag main", None),
    "an abbreviated commit": ("cccccccc", "identical", "has no tag cccccccc", None),
    "a full commit in capitals": ("C" * 40, "identical", "has no tag", None),
    "a name with a slash": ("release/1", "identical", "names neither", None),
    "a name starting with a dash": ("-v1", "identical", "names neither", None),
    "a name git refuses": ("a..b", "identical", "names neither", None),
    "a name with shell in it": ("v1;touch${IFS}pwned", "identical", "names neither", None),
    "nothing": ("", "identical", "names neither", None),
    "tags that cannot be read": ("v0.1.0", "identical", "cannot be read", None),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(REVISION_CASES))
def test_the_revision_step(case: str, tmp_path: Path) -> None:
    revision, status, refusal, expected = REVISION_CASES[case]
    commits = _repository(tmp_path / "repository")
    source = tmp_path / ("no-such-repository" if case == "tags that cannot be read" else "repository")
    output, log = tmp_path / "github-output", tmp_path / "gh.log"
    output.write_text("")
    work = tmp_path / "work"
    work.mkdir()
    env = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_OUTPUT": str(output), "REVISION": revision,
           "FAKE_STATUS": status, "FAKE_LOG": str(log), "GH_TOKEN": "unused", **_redirect(source)}
    if status == "unknown":
        env["FAKE_COMPARE_FAILS"] = "1"
    result = _run(_step("build", REVISION_STEP)["run"], work, env,
                  (_stand_in(tmp_path / "bin", "gh", FAKE_GH),))
    assert not (work / "pwned").exists()
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        sha = commits.get(expected[0], expected[0])
        assert _outputs(output) == {"sha": sha, "tag": expected[1]}
        assert sha != commits["tag-object"]
        assert _log(log) == [f"api repos/{REPOSITORY}/compare/{sha}...refs/heads/main --jq .status"]
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr
        assert output.read_text() == ""


def test_the_revision_step_reads_tags_over_git_with_no_credential() -> None:
    script = _step("build", REVISION_STEP)["run"]
    assert re.search(r'GIT_TERMINAL_PROMPT=0 git -c credential\.helper= \\\n'
                     r'\s+ls-remote --tags "https://github\.com/\$GITHUB_REPOSITORY\.git" \\\n'
                     r'\s+"refs/tags/\$REVISION" "refs/tags/\$REVISION\^\{\}"\)"; then\n', script), script
    calls = [line.strip() for line in script.splitlines() if re.search(r"\bgh\b", line)]
    assert len(calls) == 1, calls
    assert '/compare/$sha...refs/heads/main"' in calls[0], calls


# ---------------------------------------------------------------------------
# The environment step and the approval step.

LIMITED = {"custom_branch_policies": True, "protected_branches": False}


def _environment(reviewers: int, policy: dict | None = LIMITED) -> str:
    """An environment as `GET /repos/{owner}/{repo}/environments/{name}`
    answers it: `reviewers` required reviewers, and `policy` as its
    `deployment_branch_policy`, which is null when any ref may deploy."""
    rules = [{"id": 1, "type": "required_reviewers", "prevent_self_review": False,
              "reviewers": [{"type": "User", "reviewer": {"login": f"reviewer{n}"}}
                            for n in range(reviewers)]}]
    if policy is not None:
        rules.append({"id": 2, "type": "branch_policy"})
    return json.dumps({"id": 1, "name": "acr-qa", "protection_rules": rules,
                       "deployment_branch_policy": policy})


ENVIRONMENT_STEP = "the acr-qa environment asks a reviewer and limits the refs that deploy"

ENVIRONMENT_CASES = {
    "a reviewer named and the refs limited": (_environment(1), None),
    "no reviewer": (_environment(0), "names no required reviewer"),
    "not created yet": (None, "cannot be read"),
    "any ref may deploy": (_environment(1, None), "does not limit the refs"),
    "its protected branches, not named refs": (
        _environment(1, {"custom_branch_policies": False, "protected_branches": True}),
        "does not limit the refs"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(ENVIRONMENT_CASES))
def test_the_environment_step(case: str, tmp_path: Path) -> None:
    document, refusal = ENVIRONMENT_CASES[case]
    step = _step("build", ENVIRONMENT_STEP)
    assert step["env"]["ENVIRONMENT"] == _workflow()["jobs"]["push"]["environment"]["name"]
    env = {"GITHUB_REPOSITORY": REPOSITORY, "GH_TOKEN": "unused", "FAKE_LOG": str(tmp_path / "gh.log"),
           "ENVIRONMENT": step["env"]["ENVIRONMENT"]}
    if document is not None:
        env["FAKE_ENVIRONMENT_acr_qa"] = document
    result = _run(step["run"], tmp_path, env, (_stand_in(tmp_path / "bin", "gh", FAKE_GH),))
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "acr-qa: 1 required reviewer(s)" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout, result.stdout + result.stderr


def _approval(state: str, *environments: str) -> dict:
    return {"state": state, "comment": "", "user": {"login": "a-reviewer"},
            "environments": [{"id": 1, "name": name} for name in environments]}


APPROVAL_CASES = {
    "a reviewer named, the refs limited, and this deployment approved": (
        _environment(1), [_approval("approved", "acr-qa")], None),
    "the reviewer rule removed meanwhile": (
        _environment(0), [_approval("approved", "acr-qa")], "names no required reviewer now"),
    "the deployment limit removed meanwhile": (
        _environment(1, None), [_approval("approved", "acr-qa")], "no longer limits the refs"),
    "the environment unreadable": (None, [_approval("approved", "acr-qa")], "cannot be read"),
    "no approval at all": (_environment(1), [], "holds no approval"),
    "only another environment approved": (_environment(1), [_approval("approved", "pypi")],
                                          "holds no approval"),
    "this deployment rejected": (_environment(1), [_approval("rejected", "acr-qa")], "holds no approval"),
    "the review history unreadable": (_environment(1), None, "review history cannot be read"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(APPROVAL_CASES))
def test_the_approval_step(case: str, tmp_path: Path) -> None:
    document, approvals, refusal = APPROVAL_CASES[case]
    step = _step("push", APPROVAL_STEP)
    env = {"GITHUB_REPOSITORY": REPOSITORY, "GITHUB_RUN_ID": "1", "GH_TOKEN": "unused",
           "ENVIRONMENT": step["env"]["ENVIRONMENT"], "FAKE_LOG": str(tmp_path / "gh.log")}
    if document is not None:
        env["FAKE_ENVIRONMENT_acr_qa"] = document
    if approvals is None:
        env["FAKE_APPROVALS_FAILS"] = "1"
    else:
        env["FAKE_APPROVALS"] = json.dumps(approvals)
    result = _run(step["run"], tmp_path, env, (_stand_in(tmp_path / "bin", "gh", FAKE_GH),))
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "acr-qa: a required reviewer is named" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# The build, the record and the load, with a stand-in `docker`.

FAKE_DOCKER = """#!/usr/bin/env bash
# A stand-in `docker`: it answers from the case's fixture and records its argv.
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$1" in
  image)
    case "$4" in
      '{{.Id}}') printf '%s\\n' "$FAKE_ID" ;;
      *org.opencontainers.image.revision*) printf '%s\\n' "$FAKE_REVISION" ;;
      '{{.Os}}/{{.Architecture}}') printf '%s\\n' "$FAKE_PLATFORM" ;;
      *) echo "the stand-in docker has no answer for the format $4" >&2; exit 2 ;;
    esac ;;
  save) printf '%s' "$FAKE_ARCHIVE" > "$3" ;;
  push)
    [ -n "${FAKE_PUSH_FAILS:-}" ] && { echo "denied: requested access to the resource is denied" >&2; exit 1; }
    printf '%b\\n' "$FAKE_PUSH_OUTPUT" ;;
  buildx|load|tag|pull) ;;
  *) echo "the stand-in docker has no answer for: $*" >&2; exit 2 ;;
esac
"""

SHA = "d" * 40
IMAGE_ID = "sha256:" + "e" * 64

BUILD_STEP = "build the image for linux/amd64 at the gated commit"


@needs_a_shell
@pytest.mark.parametrize("at_the_gated_commit", [True, False])
def test_the_build_step(at_the_gated_commit: bool, tmp_path: Path) -> None:
    commits = _repository(tmp_path / "checkout")
    log = tmp_path / "docker.log"
    sha = commits["second"] if at_the_gated_commit else commits["first"]
    result = _run(_step("build", BUILD_STEP)["run"], tmp_path / "checkout",
                  {"SHA": sha, "TAG": "v0.1.0", "FAKE_LOG": str(log)},
                  (_stand_in(tmp_path / "bin", "docker", FAKE_DOCKER),))
    if not at_the_gated_commit:
        assert result.returncode != 0, result.stdout
        assert f"the gate passed {sha}" in result.stdout
        assert _log(log) == []
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert _log(log) == [
        "buildx build --platform linux/amd64 --pull --provenance=false --sbom=false "
        f"--file deploy/compose/Dockerfile --build-arg SOURCE_REVISION={sha} "
        "--tag opendox-runtime:v0.1.0 --load ."]


RECORD_CASES = {
    "the gated commit, linux/amd64": (dict(revision=SHA, platform="linux/amd64"), None),
    "another revision label": (dict(revision="unknown", platform="linux/amd64"),
                               "carries the revision label 'unknown'"),
    "another platform": (dict(revision=SHA, platform="linux/arm64"), "is linux/arm64, not linux/amd64"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(RECORD_CASES))
def test_the_record_step(case: str, tmp_path: Path) -> None:
    given, refusal = RECORD_CASES[case]
    output, summary, log = tmp_path / "github-output", tmp_path / "summary", tmp_path / "docker.log"
    output.write_text("")
    summary.write_text("")
    (tmp_path / "rt").mkdir()
    env = {"SHA": SHA, "TAG": "v0.1.0", "REVISION": "v0.1.0", "RUNNER_TEMP": str(tmp_path / "rt"),
           "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary), "FAKE_LOG": str(log),
           "FAKE_ID": IMAGE_ID, "FAKE_REVISION": given["revision"], "FAKE_PLATFORM": given["platform"],
           "FAKE_ARCHIVE": "the archive"}
    result = _run(_step("build", RECORD_STEP)["run"], tmp_path, env,
                  (_stand_in(tmp_path / "bin", "docker", FAKE_DOCKER),))
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert _outputs(output) == {"image-id": IMAGE_ID,
                                    "archive-sha256": hashlib.sha256(b"the archive").hexdigest()}
        assert (tmp_path / "rt" / "image" / "opendox-runtime.tar").read_text() == "the archive"
        assert f"| commit | `{SHA}` |" in summary.read_text()
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout, result.stdout + result.stderr
        assert output.read_text() == ""
        assert not any(line.startswith("save") for line in _log(log))


LOAD_CASES = {
    "the recorded archive and image": ({}, None),
    "a changed byte": (dict(archive="the archivE"), "is not the one the build job recorded"),
    "another image inside": (dict(loaded="sha256:" + "f" * 64), "the archive loads as sha256:fff"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(LOAD_CASES))
def test_the_load_step(case: str, tmp_path: Path) -> None:
    given, refusal = LOAD_CASES[case]
    (tmp_path / "rt" / "image").mkdir(parents=True)
    (tmp_path / "rt" / "image" / "opendox-runtime.tar").write_text(given.get("archive", "the archive"))
    log = tmp_path / "docker.log"
    env = {"RUNNER_TEMP": str(tmp_path / "rt"), "TAG": "v0.1.0", "IMAGE_ID": IMAGE_ID,
           "ARCHIVE_SHA256": hashlib.sha256(b"the archive").hexdigest(), "FAKE_LOG": str(log),
           "FAKE_ID": given.get("loaded", IMAGE_ID)}
    result = _run(_step("push", LOAD_STEP)["run"], tmp_path, env,
                  (_stand_in(tmp_path / "bin", "docker", FAKE_DOCKER),))
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert _log(log)[0] == f"load --input {tmp_path / 'rt' / 'image' / 'opendox-runtime.tar'}"
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr
        if case == "a changed byte":
            assert _log(log) == []


# ---------------------------------------------------------------------------
# Trivy, unpacked only at its recorded sha256.

FAKE_CURL = """#!/usr/bin/env bash
# A stand-in `curl`: `--output PATH URL` copies the case's tarball to PATH.
printf '%s\\n' "$*" >> "$FAKE_LOG"
while [ "$#" -gt 0 ]; do
  case "$1" in --output) out="$2"; shift 2 ;; *) url="$1"; shift ;; esac
done
cp "$FAKE_TARBALL" "$out"
"""


def _trivy_tarball(where: Path) -> Path:
    payload = b"#!/bin/sh\necho 'Version: 0.76.1'\n"
    member = tarfile.TarInfo("trivy")
    member.size, member.mode = len(payload), 0o755
    with tarfile.open(where, "w:gz") as archive:
        archive.addfile(member, io.BytesIO(payload))
    return where


def test_trivy_is_pinned_by_version_and_sha256() -> None:
    step = _step("build", TRIVY_STEP)
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(step["env"]["TRIVY_VERSION"]))
    assert re.fullmatch(r"[0-9a-f]{64}", step["env"]["TRIVY_SHA256"])
    script = step["run"]
    assert script.index("sha256sum --strict -c") < script.index("tar -xzf")
    assert ("https://github.com/aquasecurity/trivy/releases/download/v$TRIVY_VERSION/"
            "trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz") in script
    assert "curl -fsSL --proto '=https' --tlsv1.2 " in script


@needs_a_shell
@pytest.mark.parametrize("digest", ["the tarball's", "another"])
def test_trivy_is_unpacked_only_at_its_recorded_sha256(digest: str, tmp_path: Path) -> None:
    tarball = _trivy_tarball(tmp_path / "fixture.tar.gz")
    (tmp_path / "rt").mkdir()
    log = tmp_path / "curl.log"
    recorded = hashlib.sha256(tarball.read_bytes()).hexdigest() if digest == "the tarball's" else "0" * 64
    env = {"RUNNER_TEMP": str(tmp_path / "rt"), "TRIVY_VERSION": "0.76.1", "TRIVY_SHA256": recorded,
           "FAKE_TARBALL": str(tarball), "FAKE_LOG": str(log)}
    result = _run(_step("build", TRIVY_STEP)["run"], tmp_path, env,
                  (_stand_in(tmp_path / "bin", "curl", FAKE_CURL),))
    assert _log(log)[0].endswith(
        "https://github.com/aquasecurity/trivy/releases/download/v0.76.1/trivy_0.76.1_Linux-64bit.tar.gz")
    if digest == "the tarball's":
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Version: 0.76.1" in result.stdout
    else:
        assert result.returncode != 0, result.stdout
        assert "nothing from it runs" in result.stdout
        assert not (tmp_path / "rt" / "trivy" / "trivy").exists()


# ---------------------------------------------------------------------------
# The scan's verdict.


def _report(*findings: tuple[str, str, str], secrets: tuple[str, ...] = ()) -> dict:
    """A Trivy JSON report (schema 2): `findings` as (id, severity, fixed
    version, or "" for none), and `secrets` by severity."""
    return {"SchemaVersion": 2, "ArtifactName": "opendox-runtime.tar", "Results": [
        {"Target": "debian", "Class": "os-pkgs",
         "Vulnerabilities": [{"VulnerabilityID": vid, "PkgName": "pkg", "InstalledVersion": "1",
                              "FixedVersion": fixed, "Severity": severity}
                             for vid, severity, fixed in findings]},
        {"Target": "/app", "Class": "secret",
         "Secrets": [{"RuleID": "r", "Severity": severity} for severity in secrets]}]}


CRITICAL_FIXED = ("CVE-1", "CRITICAL", "2026.10.18")
HIGH_UNFIXED = ("CVE-2", "HIGH", "")
MEDIUM = ("CVE-3", "MEDIUM", "2")

VERDICT_CASES = {
    "QA's empty gate, a critical finding": ("", _report(CRITICAL_FIXED, HIGH_UNFIXED), None),
    "a gate, a gated finding": ("CRITICAL,HIGH", _report(HIGH_UNFIXED, MEDIUM), "nothing is pushed"),
    "a gate, only ungated findings": ("CRITICAL,HIGH", _report(MEDIUM), None),
    "a gate, a gated secret": ("CRITICAL,HIGH", _report(MEDIUM, secrets=("HIGH",)), "nothing is pushed"),
    "a gate in lower case": ("critical", _report(CRITICAL_FIXED), "nothing is pushed"),
    "a misspelt gate": ("CRITCAL", _report(), "a misspelt gate would pass everything"),
    "no report": ("", None, "a report that did not appear is a refusal"),
    "not a Trivy report": ("", {"Results": []}, "not a Trivy report of schema version 2"),
    "a report with no results": ("CRITICAL", {"SchemaVersion": 2, "Results": None}, None),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(VERDICT_CASES))
def test_the_scan_verdict(case: str, tmp_path: Path) -> None:
    gate, report, refusal = VERDICT_CASES[case]
    (tmp_path / "rt" / "scan").mkdir(parents=True)
    if report is not None:
        (tmp_path / "rt" / "scan" / "trivy.json").write_text(json.dumps(report), encoding="utf-8")
    summary = tmp_path / "summary"
    summary.write_text("")
    env = {"RUNNER_TEMP": str(tmp_path / "rt"), "FAIL_ON": gate, "GITHUB_STEP_SUMMARY": str(summary)}
    result = _run(_step("build", VERDICT_STEP)["run"], tmp_path, env, (_python3(tmp_path / "bin"),))
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr
    if case == "QA's empty gate, a critical finding":
        assert "report only for qa" in result.stdout
        text = summary.read_text()
        assert "| CRITICAL | 1 | 1 | 0 |" in text
        assert "| HIGH | 1 | 0 | 0 |" in text
        assert "| CRITICAL | CVE-1 | pkg | 1 | 2026.10.18 |" in text
        assert "CVE-2" not in text  # no fix, so not in the list of fixable findings


# ---------------------------------------------------------------------------
# The settings step: three secrets and one variable.

GOOD_SETTINGS = {"AZURE_CLIENT_ID": "11111111-2222-3333-4444-555555555555",
                 "AZURE_TENANT_ID": "66666666-7777-8888-9999-aaaaaaaaaaaa",
                 "AZURE_SUBSCRIPTION_ID": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                 "ACR_NAME": "exampleregistry"}

# A secret that is not set reads as an empty string, as a variable does, so an
# empty value is the "not set" case for all four.
SETTINGS_CASES = {
    "three secrets and a variable, each in its shape": ({}, None),
    "no client id": ({"AZURE_CLIENT_ID": ""}, "the secret AZURE_CLIENT_ID is not set"),
    "no tenant id": ({"AZURE_TENANT_ID": ""}, "the secret AZURE_TENANT_ID is not set"),
    "no subscription id": ({"AZURE_SUBSCRIPTION_ID": ""}, "the secret AZURE_SUBSCRIPTION_ID is not set"),
    "no registry": ({"ACR_NAME": ""}, "the variable ACR_NAME is not set"),
    "a registry's login server in place of its name": ({"ACR_NAME": "exampleregistry.example.invalid"},
                                                       "the variable ACR_NAME is not a registry name"),
    "a client id that is not a GUID": ({"AZURE_CLIENT_ID": "exampleregistry"},
                                       "the secret AZURE_CLIENT_ID is not a GUID"),
    "a tenant id that is not a GUID": ({"AZURE_TENANT_ID": "66666666-7777-8888-9999"},
                                       "the secret AZURE_TENANT_ID is not a GUID"),
    "all three secrets unset": ({name: "" for name in AZURE_IDS},
                                "the secret AZURE_SUBSCRIPTION_ID is not set"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(SETTINGS_CASES))
def test_the_settings_step(case: str, tmp_path: Path) -> None:
    change, refusal = SETTINGS_CASES[case]
    env = {**GOOD_SETTINGS, **change}
    result = _run(_step("push", SETTINGS_STEP)["run"], tmp_path, env, (_python3(tmp_path / "bin"),))
    for value in env.values():
        if value:
            assert value not in result.stdout + result.stderr, "a secret's or variable's value was printed"
    if refusal is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout, result.stdout + result.stderr
    if case == "all three secrets unset":
        for name in AZURE_IDS:
            assert f"the secret {name} is not set on the acr-qa environment" in result.stdout, result.stdout


def test_the_settings_step_reads_three_secrets_and_one_variable() -> None:
    assert _step("push", SETTINGS_STEP)["env"] == {
        **{name: f"${{{{ secrets.{name} }}}}" for name in AZURE_IDS}, "ACR_NAME": "${{ vars.ACR_NAME }}"}


def test_the_push_step_reads_the_registry_name_as_a_variable() -> None:
    assert _step("push", PUSH_STEP)["env"]["ACR_NAME"] == "${{ vars.ACR_NAME }}"


# ---------------------------------------------------------------------------
# The push, with a stand-in `az` and `docker`.

FAKE_AZ = """#!/usr/bin/env bash
# A stand-in `az`: it answers from the case's fixture and records its argv.
printf '%s\\n' "$*" >> "$FAKE_AZ_LOG"
case "$1 $2" in
  "acr login")
    [ -n "${FAKE_AZ_LOGIN_FAILS:-}" ] && { echo "ERROR: unauthorized" >&2; exit 1; }
    echo "Login Succeeded" ;;
  "cloud show") printf '%s\\n' "$FAKE_SUFFIX" ;;
  *) echo "the stand-in az has no answer for: $*" >&2; exit 2 ;;
esac
"""

DIGEST = "sha256:" + "a" * 64
PUSHED = ("The push refers to repository [exampleregistry.azurecr.io/opendox-runtime]\\n"
          "5f70bf18a086: Pushed\\n"
          f"v0.1.0: digest: {DIGEST} size: 1574")

PUSH_CASES = {
    "pushed, and served as the recorded image": ({}, None),
    "a registry name in mixed case": (dict(ACR_NAME="ExampleRegistry"), None),
    "no digest reported": (dict(FAKE_PUSH_OUTPUT="v0.1.0: pushed"), "reported no digest"),
    "another image served": (dict(FAKE_ID="sha256:" + "f" * 64), "the registry serves"),
    "the sign-in refused": (dict(FAKE_AZ_LOGIN_FAILS="1"), "ERROR: unauthorized"),
    "the push refused": (dict(FAKE_PUSH_FAILS="1"), "denied"),
}


@needs_a_shell
@pytest.mark.parametrize("case", sorted(PUSH_CASES))
def test_the_push_step(case: str, tmp_path: Path) -> None:
    change, refusal = PUSH_CASES[case]
    (tmp_path / "rt").mkdir()
    output, docker_log, az_log = tmp_path / "github-output", tmp_path / "docker.log", tmp_path / "az.log"
    output.write_text("")
    bin_dir = _stand_in(tmp_path / "bin", "docker", FAKE_DOCKER)
    _stand_in(bin_dir, "az", FAKE_AZ)
    env = {"RUNNER_TEMP": str(tmp_path / "rt"), "GITHUB_OUTPUT": str(output), "TAG": "v0.1.0",
           "IMAGE_ID": IMAGE_ID, "ACR_NAME": "exampleregistry", "FAKE_SUFFIX": ".azurecr.io",
           "FAKE_PUSH_OUTPUT": PUSHED, "FAKE_ID": IMAGE_ID, "FAKE_LOG": str(docker_log),
           "FAKE_AZ_LOG": str(az_log), **change}
    result = _run(_step("push", PUSH_STEP)["run"], tmp_path, env, (bin_dir,))
    login = _log(az_log)[0]
    assert login == f"acr login --name {env['ACR_NAME']}", login
    if refusal is not None:
        assert result.returncode != 0, result.stdout
        assert refusal in result.stdout + result.stderr, result.stdout + result.stderr
        assert output.read_text() == ""
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert _outputs(output) == {"digest": DIGEST}
    remote = "exampleregistry.azurecr.io/opendox-runtime"
    assert _log(docker_log) == [f"tag opendox-runtime:v0.1.0 {remote}:v0.1.0", f"push {remote}:v0.1.0",
                                f"pull {remote}@{DIGEST}", f"image inspect --format {{{{.Id}}}} {remote}@{DIGEST}"]


def test_the_push_names_no_resource_group() -> None:
    """With only `AcrPush`, the identity cannot read the registry's resource;
    `az acr login` without a resource group falls back to the login server
    suffix, and with one it would make a direct read, and fail."""
    script = _step("push", PUSH_STEP)["run"]
    assert "--resource-group" not in script
    assert " -g " not in script
    assert 'az acr login --name "$ACR_NAME"' in script


# ---------------------------------------------------------------------------
# The record of the pushed image.


@needs_a_shell
@pytest.mark.parametrize("digest", [DIGEST, "sha256:short"])
def test_the_release_record(digest: str, tmp_path: Path) -> None:
    (tmp_path / "rt").mkdir()
    summary = tmp_path / "summary"
    summary.write_text("")
    env = {"RUNNER_TEMP": str(tmp_path / "rt"), "GITHUB_STEP_SUMMARY": str(summary), "DIGEST": digest,
           "SHA": SHA, "TAG": "v0.1.0", "REVISION": "v0.1.0"}
    result = _run(_step("push", RELEASE_RECORD_STEP)["run"], tmp_path, env, (_python3(tmp_path / "bin"),))
    record = tmp_path / "rt" / "release" / "image-release.json"
    if digest != DIGEST:
        assert result.returncode != 0, result.stdout
        assert "is not an image digest" in result.stdout + result.stderr
        assert not record.exists()
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(record.read_text()) == {"image": "opendox-runtime:v0.1.0", "digest": DIGEST,
                                              "source_revision": SHA, "ref": "v0.1.0", "target": "qa"}
    assert f"::notice title=opendox-runtime:v0.1.0::{DIGEST} from {SHA}" in result.stdout
    for text in (record.read_text(), summary.read_text()):
        assert "azurecr" not in text
        for marker in ESTATE_MARKERS:
            assert marker not in text.lower(), marker
    assert "The deployment repository's QA overlay is bumped by hand" in summary.read_text()


# ---------------------------------------------------------------------------
# The operator page.


def _page() -> str:
    return OPERATOR_PAGE.read_text(encoding="utf-8")


def test_the_page_creates_no_azure_resource_by_hand() -> None:
    """Brett Heap, 2026-11-17, "Terraform": the identity, its federated
    credential and the registry role assignment are created through the
    estate's infrastructure-as-code by an operator, never by hand `az`. The
    page states their end state and keeps `az` for reading."""
    page = _page()
    for creating in ("az identity create", "az identity federated-credential create",
                     "az ad app federated-credential create", "az role assignment create",
                     "az identity update", "az role assignment update"):
        assert creating not in page, creating
    shell = "\n".join(re.findall(r"```sh\n(.*?)```", page, re.S))
    commands = re.findall(r"\baz((?: [a-z][a-z-]*)+)", shell)  # `az` and its subcommand words
    assert commands, "the page keeps its read-only az commands"
    for command in commands:
        assert command.split()[-1] in ("show", "list"), f"az{command}"
    assert "Terraform" in page
    # The end state: the issuer, the audience, the subject and where its prefix comes from, and the role.
    flat = " ".join(page.split())  # the page wraps its lines
    for property_ in ("https://token.actions.githubusercontent.com", "api://AzureADTokenExchange",
                      "<prefix>:environment:acr-qa", "actions/oidc/customization/sub",
                      "`AcrPush`", "Container Registry Repository Writer", "roleAssignmentMode"):
        assert property_ in flat, property_


def test_the_page_sets_the_three_ids_as_secrets_from_a_command_and_never_a_literal() -> None:
    page = _page()
    for name in AZURE_IDS:
        assert re.search(rf"\| gh secret set {name} --env acr-qa --repo {REPOSITORY}\b", page), name
        assert f"gh variable set {name}" not in page
    assert not re.search(r"gh secret set \w+[^\n]*--(?:body|env-file)", page), "a secret's value typed on the line"
    assert f'gh variable set ACR_NAME --env acr-qa --repo {REPOSITORY} --body "<REGISTRY_NAME>"' in page
    assert "gh secret list --env acr-qa" in page


def test_the_workflow_the_page_and_this_file_name_no_deployment_repository() -> None:
    """The deployment repository is the estate's, and this one is public: it is
    "the deployment repository", and its overlay "the QA overlay", everywhere."""
    for path in (WORKFLOW, OPERATOR_PAGE, Path(__file__)):
        text = path.read_text(encoding="utf-8").lower()
        for marker in ESTATE_MARKERS:
            assert marker not in text, (path.name, marker)
    assert "the deployment repository's qa overlay" in " ".join(_page().lower().split())


def test_the_page_holds_only_placeholders_for_the_estate() -> None:
    page = _page()
    assert not GUID.search(page), GUID.search(page)
    for literal in ("/home/", "/workspace/", "/Users/", "/subscriptions/", "resourceGroups", "vault.azure"):
        assert literal not in page, literal
    assert not re.search(r"[A-Za-z0-9]\.azurecr\.io", page), "a registry host"
