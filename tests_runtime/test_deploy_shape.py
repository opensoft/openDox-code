"""`deploy/` measured against `config.SETTINGS`, and the no-credential rule.

§ 3.5 puts `deploy/compose/` and `deploy/kubernetes/` at the root of this leg;
this file is what keeps the three declarations of one setting — the Python, the
compose `.env.example`, the Kubernetes manifests — from drifting while all
three keep working, which is the failure mode a variable added in one place and
forgotten in another produces.

HERMETIC: standard library plus `PyYAML`, which is this package's own base
dependency and is therefore present wherever `.[test]` is.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from opendox.runtime.config import PREFIX, SETTINGS, SETTING_NAMES

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"
COMPOSE = ROOT / "deploy" / "compose"
KUBERNETES = ROOT / "deploy" / "kubernetes"
ENV_EXAMPLE = COMPOSE / ".env.example"

#: `OPENDOX_`-prefixed variables that belong to the COMPOSE PACKAGE and not to
#: the runtime: the Postgres container's own credentials, the role the init
#: script creates, and the image coordinates. They are declared here so the
#: cross-check below is exact rather than prefix-based — an unexplained
#: `OPENDOX_*` in `.env.example` is a setting somebody forgot to declare.
COMPOSE_ONLY = frozenset({
    "OPENDOX_PG_USER", "OPENDOX_PG_PASSWORD", "OPENDOX_PG_DB",
    "OPENDOX_RUNTIME_PG_PASSWORD",
    "OPENDOX_IMAGE", "OPENDOX_SOURCE_REVISION",
})


def _env_example_names() -> list[str]:
    names = []
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        names.append(line.split("=", 1)[0])
    return names


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _kubernetes_documents() -> list[tuple[Path, Any]]:
    out = []
    for path in sorted(KUBERNETES.rglob("*.yaml")):
        for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if document is not None:
                out.append((path, document))
    return out


def _env_names_of(container: dict[str, Any]) -> set[str]:
    return {entry["name"] for entry in container.get("env", [])}


def _containers(document: Any) -> list[dict[str, Any]]:
    spec = (document.get("spec") or {}).get("template", {}).get("spec", {})
    return list(spec.get("containers", []))


# -- the workflow is a file GitHub can actually read -------------------------
#
# THIS SUITE EXISTS BECAUSE THE ABSENCE OF A RUN LOOKS LIKE NOTHING. A workflow
# file GitHub cannot parse does not fail a job — it runs NO job, reports under
# the file's own path instead of its jobs' names, and every required check
# simply never appears. Measured on this act: `run: python -m pip install
# --only-binary :all: -e ".[runtime,test]"` written as a PLAIN scalar contains
# `: `, which YAML reads as a mapping indicator, so at head `4d3ce664` neither
# `validate` nor `runtime` started and only SonarCloud reported. Nothing in the
# tree noticed; a green-looking PR page did.


def test_the_workflow_file_parses_as_yaml() -> None:
    try:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - the failure this guards
        raise AssertionError(
            f"{WORKFLOW} is not parseable YAML, so GitHub Actions will run NO "
            f"job from it and every required check will be ABSENT: {exc}"
        ) from exc
    assert isinstance(workflow, dict)
    assert isinstance(workflow.get("jobs"), dict)


def test_the_workflow_declares_both_jobs_and_their_steps() -> None:
    """The required job, and the DB-backed job this act adds beside it."""
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    assert "validate" in jobs, (
        "`validate` is this repository's one REQUIRED status check "
        "(openDox-code#2) and the workflow no longer declares it")
    assert "runtime" in jobs, (
        "the DB-backed `runtime` job is gone; the suites that need Postgres, a "
        "token or a web framework would then run nowhere")
    names = [step.get("name") for step in jobs["validate"]["steps"]]
    assert "pytest (runtime, hermetic)" in names, (
        "the required job no longer runs this act's hermetic suites")
    assert names.index("pytest") < names.index("pytest (runtime, hermetic)"), (
        "this act's step must stay APPENDED after the existing pytest step; "
        "reordering is an edit to what the required check already ran")
    runtime_names = [step.get("name") for step in jobs["runtime"]["steps"]]
    assert runtime_names[-1] == "pytest (runtime, database-backed)"


def test_the_runtime_job_supplies_a_postgres_service_and_the_extras() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    service = jobs["runtime"]["services"]["postgres"]
    assert service["image"].startswith("postgres:")
    install = next(step["run"] for step in jobs["runtime"]["steps"]
                   if step.get("name", "").startswith("install"))
    assert "--only-binary :all:" in install
    assert '.[runtime,test]' in install
    probe = next(step for step in jobs["runtime"]["steps"]
                 if step.get("name") == "pytest (runtime, database-backed)")
    assert probe["env"]["OPENDOX_TEST_DATABASE_URL"].startswith("postgresql://")


def test_the_required_job_installs_only_the_test_extra() -> None:
    """The import-weight contract, read off the workflow rather than the prose.

    If the required job ever installed `.[runtime]`, every assertion about what
    imports without the extra would still pass and would stop meaning anything.
    """
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    installs = [step.get("run", "") for step in jobs["validate"]["steps"]
                if "pip install" in step.get("run", "")]
    assert installs, "the required job installs nothing"
    for line in installs:
        assert "runtime" not in line, (
            f"the required `validate` job installs {line!r}; it must install "
            "the test extra alone, or the hermetic suites stop measuring the "
            "import-weight contract they exist for")


# -- the three declarations agree -------------------------------------------


@pytest.mark.parametrize("setting", [s.name for s in SETTINGS])
def test_every_runtime_setting_is_documented_in_env_example(setting: str) -> None:
    assert setting in _env_example_names(), (
        f"{setting} is declared in `opendox.runtime.config.SETTINGS` and is "
        "not in deploy/compose/.env.example. That file is where an operator "
        "learns a variable exists; a setting that is only in Python is a "
        "setting nobody sets.")


def test_every_opendox_variable_in_env_example_is_declared_somewhere() -> None:
    unexplained = [name for name in _env_example_names()
                   if name.startswith(PREFIX)
                   and name not in SETTING_NAMES
                   and name not in COMPOSE_ONLY]
    assert unexplained == [], (
        f"{unexplained} appear in .env.example and are neither a declared "
        "runtime setting nor a declared compose-package variable")


def test_env_example_declares_every_variable_once() -> None:
    names = _env_example_names()
    assert len(names) == len(set(names))


# -- the compose package -----------------------------------------------------


def test_compose_gives_the_served_container_no_migration_dsn() -> None:
    """The two identities never meet in one container.

    The separation `config.migration_database_url` refuses to undo in code, in
    the file that would otherwise undo it by convenience.
    """
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    served = compose["services"]["opendox"]["environment"]
    assert PREFIX + "MIGRATION_DATABASE_URL" not in served
    assert PREFIX + "DATABASE_URL" in served

    migrate = compose["services"]["migrate"]
    assert migrate["profiles"] == ["migration"], (
        "the migration executor must be profile-gated: a one-shot privileged "
        "job that ran on every `docker compose up` is not one-shot")
    assert migrate["restart"] == "no"
    assert PREFIX + "MIGRATION_DATABASE_URL" in migrate["environment"]


def test_compose_publishes_no_host_port() -> None:
    """Internal-only; TLS and ingress terminate at the platform."""
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    for name, service in compose["services"].items():
        assert "ports" not in service, f"service {name} publishes a host port"


def test_compose_commits_no_credential_value() -> None:
    """Every secret is a `${...}` reference; nothing is a literal."""
    text = (COMPOSE / "docker-compose.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if re.search(r"(PASSWORD|DATABASE_URL|SECRET|TOKEN)\s*:", line):
            value = line.split(":", 1)[1].strip()
            assert value.startswith("${"), (
                f"{line.strip()!r} is a literal; secrets enter by environment "
                "reference only")


def test_env_example_carries_placeholders_and_not_a_usable_secret() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(("OPENDOX_PG_PASSWORD=",
                            "OPENDOX_RUNTIME_PG_PASSWORD=")):
            assert "change-me" in line, (
                f"{line!r} looks like a real credential; .env.example carries "
                "placeholders and the filled-in copy is gitignored")


def test_the_image_ships_git_and_installs_the_runtime_extra() -> None:
    """RULING C3's act shells out to `git`, so the image has to carry it."""
    dockerfile = (COMPOSE / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"apt-get install[^\n]*\bgit\b", dockerfile), (
        "the runtime image must install git: the repository-creation act runs "
        "it as a subprocess, and an image without it fails the one thing "
        "§ 3.6 exists to do")
    assert 'pip install --no-cache-dir --only-binary :all: ".[runtime]"' in (
        dockerfile), (
        "the image must install the runtime extra, and with `--only-binary "
        ":all:` so pip never builds a dependency from an sdist — which would "
        "run that project's `setup.py` inside the image build")
    assert "COPY migrations ./migrations" in dockerfile, (
        "the ordered SQL travels with the image; a migration job that had to "
        "mount the repository could run against SQL the image never saw")
    assert re.search(r"^USER opendox$", dockerfile, re.MULTILINE)


# -- the Kubernetes base -----------------------------------------------------


def test_the_kubernetes_base_commits_no_secret_object_at_all() -> None:
    for path, document in _kubernetes_documents():
        assert document.get("kind") != "Secret", (
            f"{path} declares a Secret. This repository commits a Secret's "
            "NAME and key and never its value; the object is created out of "
            "band or by the platform's secret store.")
        assert "stringData" not in document, (
            f"{path} carries a `stringData:` block; this repository commits a "
            "Secret's NAME and key and never its value")
        if document.get("kind") != "ConfigMap":
            assert "data" not in document, (
                f"{path} carries a `data:` block outside a ConfigMap")


def test_the_deployment_takes_its_dsn_by_secret_reference() -> None:
    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    container = _containers(deployment)[0]
    dsn = next(e for e in container["env"]
               if e["name"] == PREFIX + "DATABASE_URL")
    assert "value" not in dsn, "the DSN must never be a literal in a manifest"
    assert dsn["valueFrom"]["secretKeyRef"]["name"] == "opendox-db-runtime"
    assert PREFIX + "MIGRATION_DATABASE_URL" not in _env_names_of(container), (
        "the long-running Deployment must not receive the privileged DSN")


def test_the_migration_job_is_the_only_holder_of_the_privileged_dsn() -> None:
    holders = []
    for path, document in _kubernetes_documents():
        for container in _containers(document):
            if PREFIX + "MIGRATION_DATABASE_URL" in _env_names_of(container):
                holders.append(f"{document['kind']}/{document['metadata']['name']}")
    assert holders == ["Job/opendox-migrate"], holders


@pytest.mark.parametrize(
    "setting", [s.name for s in SETTINGS if s.required and not s.secret])
def test_every_required_non_secret_setting_reaches_the_deployment(
        setting: str) -> None:
    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    assert setting in _env_names_of(_containers(deployment)[0]), (
        f"{setting} is required and the Deployment does not set it; the pod "
        "would refuse at startup naming it, which is honest and avoidable")


def _generator(name: str) -> dict[str, Any]:
    kustomization = _load_yaml(KUBERNETES / "base" / "kustomization.yaml")
    for entry in kustomization["configMapGenerator"]:
        if entry["name"] == name:
            return entry
    raise AssertionError(
        f"the base declares no configMapGenerator named {name!r}")


def test_the_bundled_postgres_provisions_the_least_privileged_role() -> None:
    """One init script, shared with the compose package, not a second copy.

    The base ships its own Postgres, and the Deployment connects as a role that
    something has to create. Without this the base authenticated only as the
    schema-owning role, which is the separation the whole layout exists to keep.
    """
    generator = _generator("opendox-postgres-init")
    assert generator["files"] == ["010-runtime-role.sh=init-runtime-role.sh"], (
        "the generator source must be INSIDE the kustomization root; "
        "kustomize's default load restrictor refuses one outside it, and the "
        "documented `kustomize build` then fails rather than renders")
    assert (KUBERNETES / "base" / "init-runtime-role.sh").is_file()
    assert (COMPOSE / "init-runtime-role.sh").is_file()

    statefulset = _load_yaml(KUBERNETES / "base" / "postgres-statefulset.yaml")
    container = _containers(statefulset)[0]
    assert "OPENDOX_RUNTIME_PG_PASSWORD" in _env_names_of(container)
    mounts = {mount["name"]: mount["mountPath"]
              for mount in container["volumeMounts"]}
    assert mounts["init-runtime-role"] == "/docker-entrypoint-initdb.d"


def test_the_two_copies_of_the_role_bootstrap_are_byte_identical() -> None:
    """The duplication kustomize forces, kept honest by a test instead of a path.

    `LoadRestrictionsRootOnly` refuses a generator source outside the
    kustomization root, so the Kubernetes base cannot read the compose
    package's script and has to carry its own copy. One source of truth is then
    something a test enforces rather than something the filesystem does.
    """
    compose = (COMPOSE / "init-runtime-role.sh").read_bytes()
    kubernetes = (KUBERNETES / "base" / "init-runtime-role.sh").read_bytes()
    assert compose == kubernetes, (
        "deploy/compose/init-runtime-role.sh and "
        "deploy/kubernetes/base/init-runtime-role.sh have drifted apart. They "
        "are one script in two places because kustomize's load restrictor "
        "requires it; copy one over the other rather than editing either alone.")


def test_the_migration_job_says_how_it_is_re_run() -> None:
    """A Job's pod template is immutable, so `kubectl apply` does not re-run it.

    That is a property of Jobs and not of this manifest, and the answer is to
    SAY so where an operator will look, rather than to let a second apply
    silently not migrate.
    """
    job = _load_yaml(KUBERNETES / "base" / "migration-job.yaml")
    assert job["spec"].get("ttlSecondsAfterFinished"), (
        "a finished Job with no TTL sits in the namespace and blocks the next "
        "apply's template patch")
    manifest = (KUBERNETES / "base" / "migration-job.yaml").read_text(
        encoding="utf-8")
    assert "delete job opendox-migrate" in manifest
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    assert "delete job opendox-migrate" in runbook, (
        "the runbook must state the re-run; the manifest alone is not where an "
        "operator looks")


def test_the_runbook_creates_every_secret_key_the_base_references() -> None:
    """A secret with one key of two leaves the Postgres pod unable to start."""
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    referenced: set[tuple[str, str]] = set()
    for _path, document in _kubernetes_documents():
        for container in _containers(document):
            for entry in container.get("env", []):
                ref = (entry.get("valueFrom") or {}).get("secretKeyRef")
                if ref:
                    referenced.add((ref["name"], ref["key"]))
    assert referenced, "no secretKeyRef found; the walk is wrong"
    for name, key in sorted(referenced):
        assert name in runbook, f"the runbook never creates secret {name}"
        assert f"{key}=" in runbook, (
            f"the runbook creates {name} without the `{key}` key the base "
            "references")


def test_the_neutral_base_leaves_the_broker_empty_rather_than_plausible() -> None:
    """An empty issuer refuses at startup; a plausible one is trusted silently."""
    generator = _generator("opendox-oidc")
    literals = dict(item.split("=", 1) for item in generator["literals"])
    assert literals["oidc_issuer"] == ""
    assert literals["oidc_audience"] == ""
    assert literals["oidc_algorithms"] == "RS256"


def test_the_runtime_probes_are_the_two_the_application_serves() -> None:
    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    container = _containers(deployment)[0]
    assert container["livenessProbe"]["httpGet"]["path"] == "/livez"
    assert container["readinessProbe"]["httpGet"]["path"] == "/readyz"


def test_one_replica_and_recreate_because_git_has_no_shared_writer_protocol() -> None:
    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["strategy"]["type"] == "Recreate"
    claim = _load_yaml(KUBERNETES / "base" / "project-repositories-pvc.yaml")
    assert claim["spec"]["accessModes"] == ["ReadWriteOnce"]


# -- the review round's own assertions (Copilot review of openDox-code#25) ---


def test_the_migration_container_carries_no_served_identity() -> None:
    """Compose and Kubernetes both stopped aliasing the privileged DSN.

    Both used to set `OPENDOX_DATABASE_URL` to the MIGRATION DSN purely to
    satisfy the served loader, which made any path reading
    `settings.database_url` in that container schema-privileged and defeated
    the separation the two files exist to keep.
    """
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    migrate = compose["services"]["migrate"]["environment"]
    assert PREFIX + "DATABASE_URL" not in migrate
    assert PREFIX + "OIDC_ISSUER" not in migrate
    assert set(migrate) == {PREFIX + "MIGRATION_DATABASE_URL",
                            PREFIX + "MIGRATIONS_DIR",
                            PREFIX + "RUNTIME_PG_ROLE"}

    job = _load_yaml(KUBERNETES / "base" / "migration-job.yaml")
    names = _env_names_of(_containers(job)[0])
    assert PREFIX + "DATABASE_URL" not in names
    assert PREFIX + "OIDC_ISSUER" not in names
    assert names == {PREFIX + "MIGRATION_DATABASE_URL",
                     PREFIX + "MIGRATIONS_DIR",
                     PREFIX + "RUNTIME_PG_ROLE"}


def test_the_role_the_migration_narrows_is_a_name_and_not_a_credential() -> None:
    """`OPENDOX_RUNTIME_PG_ROLE` is the exception that proves the rule.

    Every other value the migration container receives is a Secret reference;
    this one is a plain literal in both deployments, and it is allowed to be
    because a role NAME is not a credential — the password for that role lives
    in `opendox-postgres/runtime-password` and never reaches this container.
    """
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    value = compose["services"]["migrate"]["environment"][PREFIX + "RUNTIME_PG_ROLE"]
    assert "PASSWORD" not in value.upper()
    job = _load_yaml(KUBERNETES / "base" / "migration-job.yaml")
    entry = next(e for e in _containers(job)[0]["env"]
                 if e["name"] == PREFIX + "RUNTIME_PG_ROLE")
    # FROM THE ConfigMap, because the narrowed role must match the user in the
    # `opendox-db-runtime` Secret's DSN — which is created out of band, so an
    # overlay that serves as another role and a Job that narrows the bundled
    # one would leave the real served role able to rewrite the migration ledger
    # (Copilot review of openDox-code#25, round 5).
    reference = entry["valueFrom"]["configMapKeyRef"]
    assert reference["name"] == "opendox-runtime-config"
    assert reference["key"] == "runtime_pg_role"
    assert "secretKeyRef" not in str(entry), "a role NAME is not a credential"
    literals = dict(item.split("=", 1)
                    for item in _generator("opendox-runtime-config")["literals"])
    assert literals["runtime_pg_role"] == "opendox_runtime"
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    assert "runtime_pg_role" in runbook, (
        "the runbook must say that this role and the served DSN's user are one "
        "role; the ledger narrowing is pointless if they are two")


def test_both_pods_declare_command_and_not_only_args() -> None:
    """The image has a `CMD` and no `ENTRYPOINT`.

    Kubernetes `args` replaces CMD's ARGUMENTS and leaves the entrypoint empty,
    so a container declared with `args:` alone has no executable and never
    starts (Copilot review of openDox-code#25 — a defect no test of this
    repository could have caught, because nothing here runs a cluster; the
    assertion is on the manifest's shape instead).
    """
    for name in ("opendox-deployment.yaml", "migration-job.yaml"):
        document = _load_yaml(KUBERNETES / "base" / name)
        for container in _containers(document):
            assert container.get("command"), (
                f"{name}: {container['name']} declares no `command:`")
            assert container["command"][0] == "opendox-runtime"
            assert "args" not in container, (
                f"{name}: {container['name']} still carries `args:`")


def test_the_compose_migration_service_can_be_built_like_the_served_one() -> None:
    """The runbook runs `migrate` BEFORE `up`, so it cannot need a pulled image."""
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    served = compose["services"]["opendox"]["build"]
    migrate = compose["services"]["migrate"]["build"]
    assert migrate == served, (
        "the migration service must build the same image the served service "
        "does; with `image:` alone a fresh checkout tries to PULL "
        "`opendox-runtime:local`, which is in no registry")


def test_the_dev_overlay_does_not_claim_a_pin_it_does_not_make() -> None:
    """`newTag:` is mutable; a comment that called it a digest was describing
    a line that did not do it."""
    text = (KUBERNETES / "overlays" / "dev" / "kustomization.yaml").read_text(
        encoding="utf-8")
    overlay = _load_yaml(KUBERNETES / "overlays" / "dev" / "kustomization.yaml")
    entry = overlay["images"][0]
    if "digest" in entry:
        assert entry["digest"].startswith("sha256:")
    else:
        assert "newTag" in entry
        assert "non-production placeholder" in text.lower(), (
            "the overlay pins a MUTABLE tag and must say so; a comment "
            "claiming a digest here would be describing a line that does not "
            "make one")
        assert "digest:" in text, (
            "the overlay must show the `digest:` form a real environment uses")


def test_the_init_script_mode_is_an_integer_kubernetes_accepts() -> None:
    """`defaultMode: 0o555` is a STRING in YAML 1.1, and the API server refuses it.

    A Kubernetes manifest is parsed as YAML 1.1, whose octal spelling is a
    leading zero (`0555`); Python's `0o` prefix is not an integer there at all,
    so the StatefulSet was rejected before Postgres could start and nothing in
    this repository noticed (Copilot review of openDox-code#25). The assertion
    is on the PARSED value, not the text, because the text is exactly what
    looked right.
    """
    statefulset = _load_yaml(KUBERNETES / "base" / "postgres-statefulset.yaml")
    volume = next(v for v in statefulset["spec"]["template"]["spec"]["volumes"]
                  if v["name"] == "init-runtime-role")
    mode = volume["configMap"]["defaultMode"]
    assert isinstance(mode, int), (
        f"defaultMode parsed as {type(mode).__name__} {mode!r}; Kubernetes "
        "declares it an int32 and rejects the object when it is a string")
    assert mode == 0o555, oct(mode)


def test_the_migration_job_waits_for_postgres_before_it_runs() -> None:
    """Nothing orders a Job against the StatefulSet it needs.

    One `kubectl apply` admits both; the Job's first attempt can therefore meet
    a server still running `initdb`, and `backoffLimit: 2` can retire the whole
    Job seconds before the database is ready (Copilot review of
    openDox-code#25). The wait is a readiness gate rather than a bigger retry
    budget, and it reaches the Postgres SERVICE this base ships.
    """
    job = _load_yaml(KUBERNETES / "base" / "migration-job.yaml")
    inits = job["spec"]["template"]["spec"].get("initContainers") or []
    assert inits, "the migration Job runs with nothing waiting for Postgres"
    wait = inits[0]

    # THE ADDRESS COMES FROM THE ConfigMap, not from this file. The first cut
    # hard-coded the bundled Service, which the base also says an overlay may
    # replace with a managed database — and there the wait burned its whole
    # budget and failed the Job before the configured DSN was used (Copilot
    # review of openDox-code#25, round 5).
    keys = {entry["name"]: entry["valueFrom"]["configMapKeyRef"]
            for entry in wait["env"]}
    assert keys["OPENDOX_MIGRATION_WAIT_HOST"]["key"] == "migration_wait_host"
    assert keys["OPENDOX_MIGRATION_WAIT_PORT"]["key"] == "migration_wait_port"
    literals = dict(item.split("=", 1)
                    for item in _generator("opendox-runtime-config")["literals"])
    service = _load_yaml(KUBERNETES / "base" / "postgres-service.yaml")
    assert literals["migration_wait_host"] == service["metadata"]["name"]
    assert literals["migration_wait_port"] == str(
        service["spec"]["ports"][0]["port"])

    script = "\n".join(str(part) for part in wait["command"])
    # An EMPTY host is "nothing to wait for" — the managed-database overlay.
    assert "if not host" in script and "sys.exit(0)" in script
    # The same image, so the wait adds no dependency to the install path.
    assert wait["image"] == _containers(job)[0]["image"]
    # And it carries no credential: the question is whether the port answers.
    assert all("secretKeyRef" not in str(entry) for entry in wait["env"])
    assert wait["securityContext"]["allowPrivilegeEscalation"] is False


# -- Copilot's fifth round on #25 --------------------------------------------


def test_the_schema_viewer_switch_reaches_both_deployments() -> None:
    """`OPENDOX_PUBLISH_OPENAPI` was documented everywhere and passed nowhere.

    `.env.example` declares it, `config.SETTINGS` reads it and the runbook's
    boundary table names it — and neither the compose service nor the
    Kubernetes Deployment handed it to the container, so setting it in the
    documented `.env` changed nothing and `/docs` stayed 404 with no way to
    tell why (Copilot review of openDox-code#25, round 5).
    """
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    served = compose["services"]["opendox"]["environment"]
    assert PREFIX + "PUBLISH_OPENAPI" in served
    # The application's own default: OFF.
    assert served[PREFIX + "PUBLISH_OPENAPI"].endswith(":-false}")

    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    entry = next(e for e in _containers(deployment)[0]["env"]
                 if e["name"] == PREFIX + "PUBLISH_OPENAPI")
    reference = entry["valueFrom"]["configMapKeyRef"]
    assert reference["name"] == "opendox-runtime-config"
    assert reference["key"] == "publish_openapi"
    literals = dict(item.split("=", 1)
                    for item in _generator("opendox-runtime-config")["literals"])
    assert literals["publish_openapi"] == "false"


def test_the_runbook_creates_the_namespace_before_it_creates_secrets() -> None:
    """Every `kubectl -n opendox create secret` needs the namespace to exist.

    On a clean cluster it did not: the namespace arrived with the manifest, on
    the LAST line of the block, so all three `create secret` calls failed with
    `namespaces "opendox" not found` and the documented install could not
    proceed (Copilot review of openDox-code#25, round 5).
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    creates_namespace = runbook.index("apply -f deploy/kubernetes/base/namespace.yaml")
    first_secret = runbook.index("create secret generic opendox-postgres")
    assert creates_namespace < first_secret, (
        "the runbook creates a Secret in a namespace it has not created yet")


def test_the_image_comment_does_not_claim_a_layer_cache_it_does_not_have() -> None:
    """`COPY src` precedes the install, so a source edit reinstalls everything.

    The comment above those lines claimed the opposite (Copilot review of
    openDox-code#25, round 5). The ORDER is forced — pip builds the package
    from its own source — so the comment is what had to change, and it now
    names the lockfile act where the split belongs.
    """
    text = (COMPOSE / "Dockerfile").read_text(encoding="utf-8")
    copy_src = text.index("COPY src ./src")
    install = text.index('pip install --no-cache-dir --only-binary :all: ".[runtime]"')
    assert copy_src < install, "the layer order changed; re-read the comment"
    claim = text[:copy_src]
    assert "does not reinstall" not in claim, (
        "the comment claims a dependency-layer cache this Dockerfile does not "
        "have; either split the install or keep the comment honest")
    assert "REINSTALLED ON ANY SOURCE CHANGE" in claim


# -- Copilot's sixth round on #25 --------------------------------------------


def test_the_served_roles_name_is_declared_once_and_reaches_both_services(
) -> None:
    """Two names for one role is how creation and narrowing come apart.

    `.env.example` declared `OPENDOX_RUNTIME_PG_USER` (which created the role)
    AND `OPENDOX_RUNTIME_PG_ROLE` (which the runtime reads and the migration
    narrows), while the compose file read only the first — so setting the
    documented one changed nothing, and setting both differently created one
    role and narrowed another, leaving the real served role able to rewrite the
    migration ledger (Copilot review of openDox-code#25, round 6).
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    declarations = [line.split("=", 1)[0] for line in text.splitlines()
                    if line.strip() and not line.startswith("#") and "=" in line]
    assert PREFIX + "RUNTIME_PG_USER" not in declarations, (
        "a second name for the served role is back in .env.example")
    assert declarations.count(PREFIX + "RUNTIME_PG_ROLE") == 1

    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    creates = compose["services"]["postgres"]["environment"][
        PREFIX + "RUNTIME_PG_USER"]
    narrows = compose["services"]["migrate"]["environment"][
        PREFIX + "RUNTIME_PG_ROLE"]
    # Both services interpolate the SAME `.env` name, whatever each container's
    # own variable is called.
    assert "${" + PREFIX + "RUNTIME_PG_ROLE" in creates
    assert "${" + PREFIX + "RUNTIME_PG_ROLE" in narrows
    served_dsn = compose["services"]["opendox"]["environment"][
        PREFIX + "DATABASE_URL"]
    assert "${" + PREFIX + "DATABASE_URL" in served_dsn, (
        "the served DSN must stay an operator-supplied value; the role name in "
        "it is the same role these two derive")


def test_the_compose_probe_and_the_repository_mount_follow_their_settings(
) -> None:
    """A setting the deployment does not follow is a setting that breaks it.

    The healthcheck probed a literal 8080 while the service accepts
    `OPENDOX_BIND_PORT`, so any other configured port made the container
    permanently unhealthy and eligible for restart with the server listening;
    and the repositories volume mounted a literal path while
    `OPENDOX_PROJECT_REPOSITORY_ROOT` is interpolated into the environment, so
    a changed root wrote documents outside the volume — onto the read-only
    filesystem or into a layer that dies with the container (Copilot review of
    openDox-code#25, round 6, suppressed).
    """
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    service = compose["services"]["opendox"]
    probe = " ".join(str(part) for part in service["healthcheck"]["test"])
    assert "${" + PREFIX + "BIND_PORT" in probe, (
        "the healthcheck names a literal port; a configured one is unhealthy")
    assert "localhost:8080/livez" not in probe

    mounts = service["volumes"]
    assert any("${" + PREFIX + "PROJECT_REPOSITORY_ROOT" in str(m)
               for m in mounts), (
        "the repositories volume mounts a literal path while the root is "
        "configurable; the two must be one expression")


def test_the_kubernetes_repository_root_equals_the_mount_it_is_claimed_at(
) -> None:
    """A volumeMount path cannot read a ConfigMap, so the root is FIXED here.

    The Deployment exposed the root as an environment value while the PVC
    stayed at a literal path, so a changed root bypassed the claim (Copilot
    review of openDox-code#25, round 6, suppressed). In this shape the two are
    one value, held equal here, and an overlay moves both in one patch.
    """
    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    container = _containers(deployment)[0]
    root = next(e for e in container["env"]
                if e["name"] == PREFIX + "PROJECT_REPOSITORY_ROOT")["value"]
    mount = next(m for m in container["volumeMounts"]
                 if m["name"] == "project-repositories")["mountPath"]
    assert root == mount, (
        f"the configured root {root!r} is not the path the claim is mounted "
        f"at ({mount!r}); repository creation would bypass the volume")


def test_the_readiness_probe_allows_the_endpoints_own_budgets() -> None:
    """Kubernetes defaults `timeoutSeconds` to ONE.

    `/readyz` can spend the database checkout timeout plus the broker's JWKS
    HTTP timeout before it answers, so a healthy but slow dependency was
    reported unready and every cut probe left its request running in the
    process (Copilot review of openDox-code#25, round 6, suppressed).
    """
    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    probe = _containers(deployment)[0]["readinessProbe"]
    assert probe["timeoutSeconds"] >= 10, (
        "the readiness probe's timeout is under the endpoint's own dependency "
        "budgets; a slow dependency reads as an unready pod")
    assert probe["timeoutSeconds"] <= probe["periodSeconds"], (
        "a probe that can outlive its own period overlaps itself")
