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
    # Read by the first-start role bootstrap, never by the runtime: it names
    # the role the MIGRATION connects as, so `alter default privileges` can be
    # aimed at the owner that will create the tables (Copilot review of
    # openDox-code#25, round 12).
    "OPENDOX_MIGRATION_PG_USER",
    # And the schema those grants are made in: a runtime DSN selects one with
    # `options=-c search_path=…`, and the bootstrap cannot read a DSN — it is
    # the DATABASE container's environment and a DSN carries a password
    # (Copilot review of openDox-code#25, round 36, suppressed).
    "OPENDOX_PG_SCHEMA",
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
    # THE PROBE FOLLOWS THE CONFIGURED PORT — and since round 23 it reads it
    # from the ENVIRONMENT rather than having it interpolated into its own
    # source, so what is asserted is that the two are the same variable and
    # that the script holds no interpolation at all.
    assert PREFIX + "BIND_PORT" in probe, (
        "the healthcheck names a literal port; a configured one is unhealthy")
    assert "os.environ" in probe, (
        "the port is interpolated into this script instead of being read from "
        "the environment; see the round-23 finding")
    assert "${" not in probe, (
        "an operator's value is interpolated into a script this container "
        "executes: " + probe)
    assert "localhost:8080/livez" not in probe
    assert service["environment"][PREFIX + "BIND_PORT"].startswith(
        "${" + PREFIX + "BIND_PORT"), (
        "the container is not given the port the probe reads")

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


def _declared_seconds(module: str, constant: str) -> float:
    """A default read out of the module that DECLARES it, as text.

    As text because this suite is the hermetic one: `opendox.runtime.db`
    imports `psycopg` and `opendox.runtime.oidc` imports `jwt` and `httpx`, all
    of which belong to the `runtime` extra the REQUIRED job does not install.
    The number still has to come from the declaration rather than from a copy
    of it here, or the relation below is asserted against this file's memory of
    the budgets instead of against the budgets.
    """
    source = (ROOT / "src" / "opendox" / "runtime" / module).read_text(
        encoding="utf-8")
    match = re.search(rf"^{constant} = ([0-9.]+)$", source, re.MULTILINE)
    assert match, f"{constant} is not declared in {module}"
    return float(match.group(1))


def test_the_readiness_probe_allows_the_endpoints_own_budgets() -> None:
    """Kubernetes defaults `timeoutSeconds` to ONE.

    `/readyz` can spend the database checkout timeout plus the broker's JWKS
    HTTP timeout before it answers, so a healthy but slow dependency was
    reported unready and every cut probe left its request running in the
    process (Copilot review of openDox-code#25, round 6, suppressed).

    AND STRICTLY OVER THE SUM, not equal to it. The first cut chose exactly
    `10 + 5` while the manifest's own comment called it "longer than both
    budgets together": a worst-case-but-valid readiness request had nothing
    left for probe scheduling, network latency or writing the response, so the
    probe could cut a request the endpoint was about to answer and mark the pod
    unavailable (Copilot review of openDox-code#25, round 10, suppressed). Both
    budgets are read from the modules that declare them, so a change to either
    default is a change this assertion sees.
    """
    deployment = _load_yaml(KUBERNETES / "base" / "opendox-deployment.yaml")
    probe = _containers(deployment)[0]["readinessProbe"]
    # THE STATEMENT BOUND IS PART OF THE BUDGET NOW. The first two cover
    # waiting to GET a connection and fetching the key set; neither says how
    # long a statement may then take, and `select 1` behind a lock could
    # outlast the whole probe (Copilot review of openDox-code#25, round 30,
    # suppressed). `/readyz` sets `statement_timeout` for its own transaction,
    # so the third term is real and is read from the module that declares it.
    # THE DATABASE TERM IS A TOTAL PLUS ONE STATEMENT, and that is the exact
    # bound `/readyz` holds: no statement is STARTED after the budget's
    # deadline, and one that starts is capped at the per-statement ceiling. The
    # third term used to be the CEILING ALONE, while the probe runs four
    # statements — so the derived budget was under a quarter of the real worst
    # case (Copilot review of openDox-code#25, round 36, suppressed).
    budget = (_declared_seconds("db.py", "DEFAULT_CHECKOUT_TIMEOUT_SECONDS")
              + _declared_seconds("oidc.py", "DEFAULT_JWKS_TIMEOUT_SECONDS")
              + _declared_seconds("app.py",
                                  "READINESS_DATABASE_BUDGET_SECONDS")
              + _declared_seconds("app.py",
                                  "READINESS_STATEMENT_TIMEOUT_SECONDS"))
    assert probe["timeoutSeconds"] > budget, (
        f"the readiness probe's timeout ({probe['timeoutSeconds']}s) leaves "
        f"nothing over the endpoint's own dependency budgets ({budget}s); a "
        "slow but healthy dependency reads as an unready pod")
    assert probe["timeoutSeconds"] <= probe["periodSeconds"], (
        "a probe that can outlive its own period overlaps itself")


def test_the_runbook_makes_the_managed_database_role_an_explicit_prerequisite(
) -> None:
    """A managed database runs no init script, so nothing grants the role.

    The bundled Postgres creates and grants the served role on its first start
    (`init-runtime-role.sh`, mounted by the StatefulSet). The documented
    managed-database path pointed both DSNs at the external server and cleared
    the wait host and said nothing about privileges, so the migration owner
    created the six tables and the served role had no access to any of them:
    the Job succeeded, `/readyz` reported an applied schema, and every request
    then failed with `permission denied` (Copilot review of openDox-code#25,
    round 10). The remedy this act took is the one that matches how the role is
    provisioned in the first place — out of band, with its password — so the
    runbook states it as a prerequisite, and this holds the runbook to the same
    grants the bundled script performs.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    script = (COMPOSE / "init-runtime-role.sh").read_text(encoding="utf-8")
    managed = runbook.split("**A managed database instead of the bundled "
                            "Postgres.**", 1)
    assert len(managed) == 2, "the runbook no longer has a managed-database note"
    section = managed[1].split("\n## ", 1)[0]

    for statement in ("create role", "grant connect on database",
                      "grant usage on schema %i",
                      "grant select, insert, update, delete on table %i",
                      "alter default privileges"):
        assert statement in script.lower(), (
            f"{statement!r} is no longer what the bundled bootstrap does; the "
            "runbook's managed-database prerequisite is derived from it")
        assert statement in section.lower(), (
            f"the managed-database prerequisite does not name {statement!r}, "
            "which the bundled Postgres does for the operator")
    assert "protect_ledger" in section, (
        "the prerequisite must say what the migration run then narrows, or an "
        "operator granting everything has no way to know the ledger is the "
        "one exception")


def test_the_bootstrap_creates_the_role_the_migration_narrows() -> None:
    """One name, and in Kubernetes that means one ConfigMap key.

    The StatefulSet's bootstrap hard-coded `opendox_runtime` while the
    migration Job read `runtime_pg_role`, so an overlay that changed the
    documented served role created one role and narrowed another — a startup
    failure, or the real served role left able to write the ledger (Copilot
    review of openDox-code#25, round 7).
    """
    statefulset = _load_yaml(KUBERNETES / "base" / "postgres-statefulset.yaml")
    created = next(e for e in _containers(statefulset)[0]["env"]
                   if e["name"] == PREFIX + "RUNTIME_PG_USER")
    job = _load_yaml(KUBERNETES / "base" / "migration-job.yaml")
    narrowed = next(e for e in _containers(job)[0]["env"]
                    if e["name"] == PREFIX + "RUNTIME_PG_ROLE")
    assert "value" not in created, "the bootstrap hard-codes the role again"
    assert (created["valueFrom"]["configMapKeyRef"]
            == narrowed["valueFrom"]["configMapKeyRef"]), (
        "the role the bootstrap creates and the role the migration narrows "
        "come from different places; they are one role")


# -- Copilot's eleventh round on #25 -----------------------------------------


def test_the_documented_first_command_builds_the_image_it_runs() -> None:
    """`docker compose run` does not build by policy — `up` and `create` do.

    The asymmetry is in the CLI itself: `up` and `create` carry `--no-build`
    ("Don't build an image, even if it's policy") and `run` does not, because
    `run` has nothing to suppress. The default `OPENDOX_IMAGE` is the local tag
    `opendox-runtime:local`, which no registry has, so on a clean checkout the
    documented FIRST command tried to pull an image that had never been built
    (Copilot review of openDox-code#25, round 11 — three copies of it). The
    `build:` stanza in the compose file says HOW, not WHEN.
    """
    documented = {
        "docs/runtime.md": (ROOT / "docs" / "runtime.md"),
        ".env.example": ENV_EXAMPLE,
        "docker-compose.yaml": (COMPOSE / "docker-compose.yaml"),
    }
    for label, path in documented.items():
        text = path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines()
                 if "run --rm" in line and "migrate" in line]
        assert lines, f"{label} no longer documents the migration run"
        for line in lines:
            assert "--build" in line, (
                f"{label} documents `{line.strip()}`, which cannot start from a "
                "clean checkout: `docker compose run` does not build a missing "
                "image")


def test_the_role_bootstrap_never_puts_the_password_in_the_process_arguments(
) -> None:
    """`-v runtime_password=…` is visible in `ps` for the life of the command.

    `/proc/<pid>/cmdline` is world-readable on a default Linux host, so the
    role's password was copied out of the Secret and into a process table
    (Copilot review of openDox-code#25, round 11). `\\getenv` reads it from
    psql's own environment instead — measured against psql 16 before it was
    written: the variable is set, `%L` quotes it, and the role is created.
    """
    for path in (COMPOSE / "init-runtime-role.sh",
                 KUBERNETES / "base" / "init-runtime-role.sh"):
        script = path.read_text(encoding="utf-8")
        assert "\\getenv runtime_password OPENDOX_RUNTIME_PG_PASSWORD" in script, (
            f"{path.name} no longer loads the password inside psql")
        # COMMENT LINES ARE EXCLUDED, because the paragraph that explains this
        # fix quotes the shape it removed.
        executed = "\n".join(line for line in script.splitlines()
                             if not line.lstrip().startswith("#"))
        assert "-v runtime_password=" not in executed, (
            f"{path.name} passes the role password as a psql argument, where "
            "any process listing can read it")
        # The role NAME is still an argument, and that is deliberate.
        assert '-v runtime_user="$runtime_user"' in executed


def test_the_migration_job_can_outlast_a_database_that_is_recovering() -> None:
    """The TCP wait proves a LISTENER, not a server that will take a session.

    Postgres accepts the socket while it replays a crash recovery and answers
    "the database system is starting up"; the initContainer carries no
    credential and cannot tell the two apart. Two attempts could therefore
    exhaust the Job while the database came up seconds later (Copilot review of
    openDox-code#25, round 11). The migration container is the honest probe —
    it opens a real session — and the retry budget is what makes that a wait
    rather than a failure.
    """
    job = _load_yaml(KUBERNETES / "base" / "migration-job.yaml")
    assert job["spec"]["backoffLimit"] >= 5, (
        "the Job's retry budget is too small to cover a database that is "
        "still recovering when the TCP wait returns")


# -- Copilot's twelfth round on #25 -------------------------------------------


def test_the_bootstrap_aims_default_privileges_at_the_migration_owner() -> None:
    """Default privileges belong to the role that CREATES the table.

    This script runs as `$POSTGRES_USER`, and the migration service's DSN is
    configured separately: point it at another owner and `0001` created the six
    tables with no default privilege for the served role — the Job succeeded,
    `/readyz` reported an applied schema, and every API query failed
    `permission denied` (Copilot review of openDox-code#25, round 12). The
    grant now names the owner, and the name reaches the script from the same
    place in both deployment shapes.
    """
    for path in (COMPOSE / "init-runtime-role.sh",
                 KUBERNETES / "base" / "init-runtime-role.sh"):
        script = path.read_text(encoding="utf-8")
        executed = "\n".join(line for line in script.splitlines()
                             if not line.lstrip().startswith("#"))
        assert "alter default privileges for role %I" in executed, (
            f"{path.name} sets default privileges for whoever runs the script, "
            "not for the role that will create the tables")
        assert ('migration_owner="${OPENDOX_MIGRATION_PG_USER:-$POSTGRES_USER}"'
                in executed), (
            f"{path.name} does not take the migration owner from the "
            "environment, defaulting to the bundled single-owner shape")
        assert '-v migration_owner="$migration_owner"' in executed, (
            f"{path.name} never passes the owner into psql")

    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    postgres_env = compose["services"]["postgres"]["environment"]
    assert "OPENDOX_MIGRATION_PG_USER" in postgres_env, (
        "the compose Postgres service cannot be told who the migration owner "
        "is, so the bootstrap can only ever grant for POSTGRES_USER")

    statefulset = _load_yaml(KUBERNETES / "base" / "postgres-statefulset.yaml")
    owner = next(e for e in _containers(statefulset)[0]["env"]
                 if e["name"] == "OPENDOX_MIGRATION_PG_USER")
    key = owner["valueFrom"]["configMapKeyRef"]
    assert key["name"] == "opendox-runtime-config", key
    kustomization = (KUBERNETES / "base" / "kustomization.yaml").read_text(
        encoding="utf-8")
    assert f"- {key['key']}=" in kustomization, (
        f"the StatefulSet reads {key['key']!r} from a ConfigMap that does not "
        "declare it; the pod would not start")


def test_the_managed_prerequisite_never_types_the_password_into_sql() -> None:
    """A password holding a `'` was a syntax error, or worse, a changed password.

    The runbook told an operator to substitute the value inside a single-quoted
    SQL literal, while the bundled script it is derived from has used psql's own
    `\\getenv` and `%L` since round 11 (Copilot review of openDox-code#25, round
    12, suppressed). The two now do the same thing, and the secret never enters
    the SQL, this file, or `~/.psql_history`.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    section = runbook.split("**A managed database instead of the bundled "
                            "Postgres.**", 1)[1].split("\n## ", 1)[0]
    assert "\\getenv runtime_password OPENDOX_RUNTIME_PG_PASSWORD" in section, (
        "the managed-database prerequisite does not read the password from the "
        "environment the way the bundled bootstrap does")
    assert "login password %L" in section, (
        "the prerequisite does not quote the password as a SQL literal through "
        "`format`'s %L")
    assert "password '" not in section, (
        "the prerequisite still asks an operator to paste a password inside a "
        "single-quoted SQL literal")


def test_the_run_verifies_the_served_role_can_use_what_it_applied() -> None:
    """The runbook's prerequisite is now measured by the run, and says so.

    A skipped prerequisite used to surface as a successful Job, a `/readyz`
    reporting an applied schema and a first request refused `permission denied`
    (Copilot review of openDox-code#25, rounds 10 and 12). `verify_runtime_access`
    is the last act of a run, so the failure lands on the migration.
    """
    from opendox.runtime import migrations

    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    section = runbook.split("**A managed database instead of the bundled "
                            "Postgres.**", 1)[1].split("\n## ", 1)[0]
    assert "verify_runtime_access" in section, (
        "the runbook does not say that the run checks the prerequisite it asks "
        "for")
    assert hasattr(migrations.MigrationRunner, "verify_runtime_access"), (
        "the runbook names a check the runner does not have")
    assert issubclass(migrations.RuntimeAccessMissingError,
                      migrations.MigrationError)


# -- Copilot's thirteenth round on #25 ----------------------------------------


def test_the_repository_root_this_package_documents_is_a_mount_target() -> None:
    """A container mount target cannot be relative, and this value is one.

    The application's own default is the RELATIVE `var/projects` — right for a
    developer running `opendox-runtime` directly — and the compose file uses
    the configured root as the `project_repositories` volume's target, so an
    operator who copied that default into `.env` got an invalid mount instead
    of a running stack (Copilot review of openDox-code#25, round 13,
    suppressed). Measured on Docker Compose v5.5.1: `docker compose config`
    ACCEPTS the relative target and the daemon refuses at container creation
    with "mount path must be absolute", so the failure is loud and names the
    path. What this holds is the documented value and the single expression.

    NOT A REGRESSION TEST, AND IT SAYS SO: it passes against the previous head,
    because the committed default was already absolute. The value that can be
    relative is the one in an operator's OWN `.env`, which this repository does
    not hold — so the remedy is the sentence beside it in `.env.example` and in
    the compose file, and what a test can do is keep the documented default
    absolute and keep the two places from drifting into two expressions.
    """
    documented = [line.split("=", 1)[1]
                  for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
                  if line.startswith("OPENDOX_PROJECT_REPOSITORY_ROOT=")]
    assert documented, ".env.example no longer documents the repository root"
    assert Path(documented[0]).is_absolute(), (
        f"the documented repository root {documented[0]!r} is relative; the "
        "compose package uses it as a container mount target")

    compose = (COMPOSE / "docker-compose.yaml").read_text(encoding="utf-8")
    expression = ("${OPENDOX_PROJECT_REPOSITORY_ROOT:-"
                  + documented[0] + "}")
    assert compose.count(expression) == 2, (
        "the service's environment and the volume's mount target no longer "
        f"come from one expression ({expression!r}); an operator who changes "
        "the root would write repositories outside the volume")


def test_the_managed_prerequisite_substitutes_nothing_by_hand() -> None:
    """A placeholder copied verbatim creates a role literally named for it.

    The block still carried `'<runtime role>'`, `"<database>"` and
    `"<migration owner>"`, so an operator who pasted it got a role and a
    database named after the placeholders and the real served role with no
    access at all (Copilot review of openDox-code#25, round 13, suppressed).
    Every name now arrives through psql's `\\getenv` and is quoted by
    `format`'s `%I`; the password by `%L`.

    MEASURED against postgres 16.15 before this was written, by running the
    block verbatim with the four variables set: it created a role whose name
    contains a SPACE (`Svc Role`) with a password containing a quote, that role
    logged in with that password, and `pg_default_acl` shows the grantor is the
    MIGRATION OWNER and the grantee is `"Svc Role"`.

    THAT NAME IS NOT A SUPPORTED SERVED ROLE, and the case below says so: the
    block will create it and this runtime refuses it, because the ledger
    narrowing interpolates a role name as syntax (round 14).
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    section = runbook.split("**A managed database instead of the bundled "
                            "Postgres.**", 1)[1].split("\n## ", 1)[0]
    block = section.split("```sql", 1)[1].split("```", 1)[0]
    for placeholder in ("<runtime role>", "<database>", "<migration owner>",
                        "<runtime password>"):
        assert placeholder not in block, (
            f"the prerequisite still carries the placeholder {placeholder!r}, "
            "which an operator can copy verbatim into a real database")
    for name in ("runtime_role", "migration_owner", "database",
                 "runtime_password"):
        assert f"\\getenv {name} OPENDOX_" in block, (
            f"{name!r} no longer comes from the environment")
    assert "%I" in block and "%L" in block, (
        "the block no longer quotes its identifiers and its literal")


def test_the_runbook_and_the_runtime_agree_on_the_served_role_s_grammar() -> None:
    """The prerequisite accepted a role the runtime then refuses.

    The block quotes every name with `%I`, so it will create a served role
    whose name holds a space — measured in round 13, and true. But
    `config.load_migration_settings` refuses that name before `migrate`
    connects, and `MigrationRunner.protect_ledger` refuses it again, because
    the ledger narrowing interpolates a role name into a `revoke` as SYNTAX.
    An operator could therefore complete the documented prerequisite and still
    not be able to start (Copilot review of openDox-code#25, round 14,
    suppressed). The runbook states the grammar now, and this pins the
    STATEMENT and the two REFUSALS to one spelling.
    """
    from opendox.runtime import config, migrations

    grammar = "[A-Za-z_][A-Za-z0-9_]{0,62}"
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    assert grammar in runbook, (
        "the managed-database prerequisite no longer states the grammar the "
        "served role's name must satisfy")
    assert grammar in config._ROLE_NAME.pattern
    assert grammar in migrations._PLAIN_IDENTIFIER.pattern

    # And the refusal is real, in both halves, against the name the round-13
    # measurement used.
    with pytest.raises(config.ConfigurationError):
        config._role_name({config.PREFIX + "RUNTIME_PG_ROLE": "Svc Role"})
    assert config._role_name(
        {config.PREFIX + "RUNTIME_PG_ROLE": "svc_role"}) == "svc_role"


def test_the_build_context_carries_only_what_the_dockerfile_copies() -> None:
    """`deploy/compose/.env` was uploaded to the docker daemon on every build.

    `docker-compose.yaml` builds with `context: ../..` — the whole repository,
    because the Dockerfile installs this package from source — and the build
    context is uploaded to the daemon or to a remote builder BEFORE any
    instruction runs. A filled-in `deploy/compose/.env` is git-ignored, which
    is not a build-context rule, so it travelled with every `docker compose …
    --build` carrying its DSN and its password, even though the Dockerfile
    never copies it into the image (Copilot review of openDox-code#25, round
    19).

    MEASURED with the docker daemon this workstation runs (server 29.6.2), by
    building `FROM busybox; COPY . /ctx` against this same context:

        before  /ctx/deploy/compose/ holds .env, .env.example, Dockerfile,
                docker-compose.yaml, init-runtime-role.sh
                /ctx holds .git, .pytest_cache, __pycache__, tests, docs, …
        after   /ctx holds README.md, migrations, pyproject.toml, src
                /ctx/deploy does not exist

    and the real image still builds from it and runs (`opendox-runtime --help`
    inside `opendox-runtime:dockerignore-probe`).

    THE GUARD IS DERIVED FROM THE DOCKERFILE, not hand-kept: a `COPY` added
    without its source re-included fails here rather than at somebody's build.
    """
    dockerignore = ROOT / ".dockerignore"
    assert dockerignore.exists(), (
        "the compose build context is the repository root and nothing "
        "excludes anything from it")
    lines = [line.strip() for line in
             dockerignore.read_text(encoding="utf-8").splitlines()]
    rules = [line for line in lines if line and not line.startswith("#")]
    assert rules[0] == "*", (
        "this file is an allowlist by design — everything excluded, then the "
        f"Dockerfile's own COPY sources named back in; it starts {rules[0]!r}")
    allowed = {rule[1:] for rule in rules[1:] if rule.startswith("!")}

    dockerfile = (COMPOSE / "Dockerfile").read_text(encoding="utf-8")
    copied: set[str] = set()
    for line in dockerfile.splitlines():
        if line.startswith("COPY "):
            parts = line.split()[1:]
            copied.update(part for part in parts[:-1] if not
                          part.startswith("--"))
    assert copied, "no COPY line was found, so this test measured nothing"
    assert copied <= allowed, (
        f"the Dockerfile copies {sorted(copied - allowed)}, which this "
        "context excludes: the image build would fail")

    # And the file this finding is about is NOT in the context, by the first
    # rule rather than by an entry somebody remembered to write.
    assert "deploy" not in allowed and "deploy/compose/.env" not in allowed
    assert not any(rule.startswith("!deploy") for rule in rules), (
        "`deploy/` is re-included, so the filled-in `.env` travels again")


def test_the_migration_wait_ends_on_the_clock_not_after_a_count() -> None:
    """120 attempts is not 240 seconds, and the message said 240 seconds.

    `socket.create_connection(..., timeout=2)` can spend its WHOLE two seconds
    before the `sleep(2)` that follows, so a loop counted to 120 ran for up to
    480s while the line it ends with — and the runbook that quotes it — said
    240s (Copilot review of openDox-code#25, round 19, suppressed).

    MEASURED against a non-routable address, where every connect burns its full
    timeout, with the counts scaled down by 40:

        the shape this replaced   3 x (2s connect + 2s sleep), claiming 6s
                                  -> 12.1s, exactly twice its stated budget

    The loop is a `time.monotonic()` deadline now: the same four minutes
    whatever each attempt costs. Both halves are asserted here — the shape, so
    a counted loop cannot come back, and one real run, so the shape is not
    merely spelled correctly.
    """
    import subprocess
    import time

    job = yaml.safe_load(
        (KUBERNETES / "base" / "migration-job.yaml").read_text(
            encoding="utf-8"))
    script = job["spec"]["template"]["spec"]["initContainers"][0]["command"][-1]

    assert "time.monotonic()" in script, script
    assert "for _ in range(" not in script, (
        "the readiness wait counts attempts again; a count is not a clock")

    # AND IT REALLY ENDS THERE. The deadline is scaled down for the run; the
    # port is one nothing listens on, so each attempt returns at once and the
    # loop's own bound is what stops it.
    started = time.monotonic()
    done = subprocess.run(
        ["python3", "-c", script.replace("time.monotonic() + 240",
                                         "time.monotonic() + 1")],
        capture_output=True,
        env={"OPENDOX_MIGRATION_WAIT_HOST": "127.0.0.1",
             "OPENDOX_MIGRATION_WAIT_PORT": "1", "PATH": "/usr/bin:/bin"})
    elapsed = time.monotonic() - started
    assert done.returncode == 1, done
    assert b"did not accept connections in 240s" in done.stderr, done.stderr
    assert 1 <= elapsed < 4, (
        f"a one-second deadline took {elapsed:.1f}s")

    # An empty wait host is still an immediate exit 0 — a managed database has
    # nothing in this cluster to wait for.
    assert subprocess.run(
        ["python3", "-c", script], capture_output=True,
        env={"OPENDOX_MIGRATION_WAIT_HOST": "", "PATH": "/usr/bin:/bin"}
    ).returncode == 0


def test_no_documented_command_puts_a_secret_in_its_own_argv() -> None:
    """`--from-literal=password=…` is readable in `/proc/<pid>/cmdline`.

    The runbook told an operator to put the Postgres passwords and both DSNs on
    a `kubectl` command line — where they land in the shell's history file and
    in every other process's view of the host for as long as `kubectl` runs —
    while the managed-database block one page down already took the same class
    of secret through `read -rs`. Two paths, one secret, different rules
    (Copilot review of openDox-code#25, round 19, suppressed).

    MEASURED with a `kubectl` on PATH that prints its own argv: the documented
    block passes `--from-file=password=/tmp/…/password` and nothing else, and
    removes the directory it wrote.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    secret_shaped = re.compile(
        r"--from-literal=(?P<key>[\w.-]*(?:password|dsn|secret|token)[\w.-]*)=",
        re.IGNORECASE)
    offenders = [line.strip() for line in runbook.splitlines()
                 if secret_shaped.search(line)]
    assert not offenders, (
        "these documented commands carry a secret in their own argv:\n"
        + "\n".join(offenders))
    # And the replacement is the one that keeps it off: a file whose NAME is
    # the key, written under `umask 077` and removed afterwards.
    assert "umask 077" in runbook
    assert "--from-file=password=" in runbook
    assert 'rm -rf "$secrets"' in runbook


def test_the_managed_database_path_ships_the_overlay_it_requires() -> None:
    """Pointing the DSNs elsewhere does not remove the bundled Postgres.

    The runbook's managed-database paragraph said to point both DSNs at the
    managed database and empty `migration_wait_host` — and stopped, while the
    base still lists `postgres-statefulset.yaml` and `postgres-service.yaml`.
    Following it started a second database nobody uses and failed on the
    `opendox-postgres` Secret the StatefulSet mounts and that path never
    creates (Copilot review of openDox-code#25, round 19, suppressed). An
    overlay is the only place kustomize can remove a base resource, so the
    instruction ships with one.

    MEASURED with kustomize v5.4.3 — `kustomize build
    deploy/kubernetes/overlays/managed-database` renders Namespace, the two
    ConfigMaps, the runtime Service, the PVC, the Deployment and the migration
    Job, and NEITHER `StatefulSet/opendox-postgres`, `Service/opendox-postgres`
    nor `ConfigMap/opendox-postgres-init`, with `migration_wait_host` empty.
    The binary is not on the CI runner, so what is asserted here is the
    overlay's own declaration and the runbook pointing at it.
    """
    overlay = (KUBERNETES / "overlays" / "managed-database"
               / "kustomization.yaml")
    assert overlay.exists(), (
        "the runbook's managed-database path has no overlay to build")
    declared = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert declared["resources"] == ["../../base"]

    removed = {(patch["target"]["kind"], patch["target"]["name"])
               for patch in declared["patches"]
               if "$patch: delete" in patch["patch"]}
    assert removed == {("StatefulSet", "opendox-postgres"),
                       ("Service", "opendox-postgres"),
                       ("ConfigMap", "opendox-postgres-init")}, removed

    # Every one of those is in the base, or this overlay is deleting nothing.
    base = yaml.safe_load(
        (KUBERNETES / "base" / "kustomization.yaml").read_text(
            encoding="utf-8"))
    assert "postgres-statefulset.yaml" in base["resources"]
    assert "postgres-service.yaml" in base["resources"]

    generated = {entry["name"]: entry
                 for entry in declared["configMapGenerator"]}
    assert "migration_wait_host=" in \
        generated["opendox-runtime-config"]["literals"]

    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    assert "overlays/managed-database" in runbook, (
        "the runbook does not tell an operator this overlay exists")


def test_every_applyable_overlay_supplies_the_settings_the_base_leaves_empty(
) -> None:
    """The base leaves the broker's facts EMPTY, deliberately.

    `opendox-oidc` carries `oidc_issuer=` and `oidc_audience=` with no values
    because they are an environment's facts and not a repository's — so an
    overlay the runbook tells an operator to BUILD must supply them, or the
    Deployment it renders fails `load_settings` before it serves.
    `overlays/dev` carries a worked example for exactly that reason;
    `overlays/managed-database` was added without one while the runbook told an
    operator to apply it (Copilot review of openDox-code#25, round 22).

    Derived from the base rather than hand-kept: every `OPENDOX_*` setting the
    base declares EMPTY and `config.SETTINGS` marks required must be supplied
    by each overlay, whatever overlays exist later.
    """
    overlays = sorted(path for path in (KUBERNETES / "overlays").iterdir()
                      if (path / "kustomization.yaml").is_file())
    assert overlays, "no overlay was found, so this test measured nothing"

    base = yaml.safe_load(
        (KUBERNETES / "base" / "kustomization.yaml").read_text(
            encoding="utf-8"))
    generated = next(generator for generator in base["configMapGenerator"]
                     if generator["name"] == "opendox-oidc")
    empty = {literal.partition("=")[0]
             for literal in generated["literals"]
             if literal.partition("=")[2] == ""
             and literal.partition("=")[0] in {"oidc_issuer", "oidc_audience"}}
    assert empty, (
        "the base no longer leaves the broker's facts empty; re-derive this")

    for overlay in overlays:
        declared = yaml.safe_load(
            (overlay / "kustomization.yaml").read_text(encoding="utf-8"))
        supplied: set[str] = set()
        for generator in declared.get("configMapGenerator") or ():
            if generator.get("name") != "opendox-oidc":
                continue
            for literal in generator.get("literals") or ():
                key, _, value = literal.partition("=")
                if value:
                    supplied.add(key)
        assert empty <= supplied, (
            f"overlay {overlay.name} supplies {sorted(supplied)} and the base "
            f"leaves {sorted(empty)} empty; `kustomize build "
            f"deploy/kubernetes/overlays/{overlay.name}` renders a Deployment "
            "that cannot start")

    # And the runbook points an operator at one of them for each path.
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    for overlay in overlays:
        assert f"overlays/{overlay.name}" in runbook, (
            f"overlay {overlay.name} is never named in the runbook")


def test_no_healthcheck_puts_an_operators_value_into_code_it_runs() -> None:
    """Compose interpolates `${VAR}` BEFORE the container sees the string.

    So `CMD-SHELL` made an operator's `.env` value shell SOURCE, and the
    application probe made it python SOURCE — both evaluated on every health
    probe, and the python one before `config.load_settings` had looked at the
    port at all (Copilot review of openDox-code#25, round 23, in both places).

    MEASURED on the script this file now declares, with
    `OPENDOX_BIND_PORT="8080'),None) or __import__('os').system('touch
    /tmp/PWNED')#"` in the environment: exit 1 with a `ValueError`, and no
    marker — the value is data that `int()` refuses, not code.

    The rule is asserted over EVERY service, so a healthcheck added later is
    covered by it: exec form, and no `${` in any argument that is a script.
    """
    import subprocess

    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    for name, service in compose["services"].items():
        check = service.get("healthcheck")
        if not check:
            continue
        test = check["test"]
        assert isinstance(test, list) and test[0] == "CMD", (
            f"{name}'s healthcheck is {test[0] if isinstance(test, list) else test!r}; "
            "CMD-SHELL makes every interpolated value shell source")
        # An interpolated value may be an ARGUMENT — that is the point of exec
        # form — but never part of a `-c` script.
        for index, part in enumerate(test):
            if index and test[index - 1] == "-c":
                assert "${" not in str(part), (
                    f"{name}'s healthcheck interpolates a value into the "
                    f"script it runs: {part}")

    # And the application's probe really does refuse a hostile value.
    script = compose["services"]["opendox"]["healthcheck"]["test"][-1]
    hostile = "8080'),None) or __import__('os').system('touch /tmp/PWNED')#"
    done = subprocess.run(
        ["python3", "-c", script], capture_output=True,
        env={"PATH": "/usr/bin:/bin", PREFIX + "BIND_PORT": hostile})
    assert done.returncode != 0
    assert b"ValueError" in done.stderr, done.stderr
    assert not Path("/tmp/PWNED").exists()


def test_the_managed_database_path_names_the_role_the_job_narrows() -> None:
    """One name, and a managed database makes it the operator's choice.

    The overlay clears the wait host and inherits the base's
    `runtime_pg_role=opendox_runtime` — which is the role the BUNDLED Postgres
    creates on first start. A managed database runs no init script, so the
    served role is whichever one the operator provisioned and put in
    `opendox-db-runtime`'s DSN; if the two differ, the migration Job narrows
    `opendox_runtime` (or fails because it does not exist) while the role
    actually serving keeps the right to rewrite the ledger (Copilot review of
    openDox-code#25, round 24).

    The overlay cannot know that name, so what is asserted is that the required
    edit is STATED in both places an operator reads — the overlay and the
    runbook's managed-database section — rather than inherited in silence.
    """
    overlay = (KUBERNETES / "overlays" / "managed-database"
               / "kustomization.yaml").read_text(encoding="utf-8")
    assert "runtime_pg_role" in overlay, (
        "the overlay inherits the bundled Postgres's role name without saying "
        "so; a managed install narrows the wrong role")

    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    managed = runbook.split("**A managed database instead of the bundled "
                            "Postgres.**", 1)
    assert len(managed) == 2, "the managed-database section moved"
    section = managed[1].split("\n## ", 1)[0]
    assert "runtime_pg_role" in section, (
        "the managed-database instructions never mention the ConfigMap value "
        "the migration Job narrows")
    assert "opendox-db-runtime" in section


def test_no_documented_apply_reaches_the_cluster_with_the_placeholder_image(
) -> None:
    """Every documented `kubectl apply` is guarded against the placeholder tag.

    THE FINDING (Copilot review of openDox-code#25, round 26): the runbook
    tells operators to apply the `dev` overlay directly, the overlay carries
    `ghcr.io/opensoft/opendox-runtime:0.0.0`, and this repository publishes no
    image — so "a clean Kubernetes install will therefore reach
    `ImagePullBackOff` before the runtime or migration Job can start".

    TRUE, AND MEASURED: `kustomize build deploy/kubernetes/overlays/dev`
    against kustomize v5.4.3 emits `image: ghcr.io/opensoft/opendox-runtime:
    0.0.0` at three container sites (the Deployment, and both of the migration
    Job's containers). The reviewer offered two dispositions and this is the
    second one — require the replacement before the documented apply — because
    the first (build a local image) would make the runbook's happy path a
    development shortcut rather than the install it documents.

    So the runbook now carries the `kustomize edit set image ...@sha256:` step
    and a guard that greps the BUILD OUTPUT for the placeholder, and this test
    is what keeps all three in agreement: the guard's pattern, the tag the base
    declares, and the tag each overlay sets. Anyone who bumps the placeholder
    without touching the runbook fails here.

    NOT A STYLE CHECK. The assertion is per apply command: a new documented
    apply that goes straight to `kubectl` fails this test even if every
    existing one is guarded.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")

    # THE PLACEHOLDER, TAKEN FROM THE MANIFESTS and not written here twice.
    declared = {
        line.split("image:", 1)[1].strip()
        for path in sorted(KUBERNETES.rglob("*.yaml"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("image:") and "opendox-runtime" in line
    }
    assert declared == {"ghcr.io/opensoft/opendox-runtime:0.0.0"}, (
        f"the base declares more than one runtime image: {declared}")
    tag = declared.pop().rsplit(":", 1)[1]
    for overlay in sorted(p for p in (KUBERNETES / "overlays").iterdir()
                          if p.is_dir()):
        entry = _load_yaml(overlay / "kustomization.yaml")["images"][0]
        assert entry.get("newTag") == tag, (
            f"{overlay.name} sets {entry} and the base declares :{tag}; the "
            f"runbook's guard greps for one string and would miss the other")

    guard = f"grep -q 'opendox-runtime:{tag.replace('.', chr(92) + '.')}'"
    assert guard in runbook, (
        f"the runbook's placeholder guard does not match the declared tag; "
        f"expected a line containing {guard!r}")

    # PER APPLY, AND IN ITS OWN FENCED BLOCK: an operator pastes a block, so
    # a guard three sections earlier is not a guard for this one.
    seen = 0
    block: list[str] = []
    for line in runbook.splitlines():
        if line.startswith("```"):
            # `sh` OR `bash`: the install blocks are fenced `bash` because
            # `read -rs -p` is not POSIX (round 30), and a scanner that knew
            # only `sh` would have stopped seeing them the moment that was
            # corrected — reading the guard from a stale block.
            block = [] if line.startswith(("```sh", "```bash")) else block
            continue
        if "kubectl apply" in line and "kustomize build" in line:
            seen += 1
            overlay = line.split("overlays/", 1)[1].split()[0]
            body = "\n".join(block)
            assert (guard in body
                    and f"overlays/{overlay} | grep -q" in body), (
                f"the documented apply of `{overlay}` is not preceded, in its "
                f"own shell block, by the placeholder guard for that overlay: "
                f"a clean install pasting this block reaches ImagePullBackOff")
        block.append(line)
    assert seen == 3, (
        f"the runbook documents {seen} applies and this test was written "
        f"against 3; a new one must be guarded, not counted away")
    assert "edit set image" in runbook, (
        "the runbook guards the apply without saying how to replace the "
        "image, which leaves the operator stuck at the guard")


def test_the_managed_database_overlay_is_applied_after_its_prerequisites(
) -> None:
    """The managed path applies only once the role it narrows exists and is named.

    THE FINDING (Copilot review of openDox-code#25, round 27): the apply block
    stood above both the `runtime_pg_role` instruction and the role-provisioning
    prerequisite, so an operator working top to bottom applied the overlay
    carrying the base's inherited `opendox_runtime` — the BUNDLED database's
    role. The migration Job then narrows a role nobody serves as (or fails
    because it does not exist on a managed database, which runs no init
    script), while the role actually serving keeps the right to rewrite the
    ledger. That is round 24's defect reached by ordering rather than by a
    missing edit, which is why it needs its own assertion and not a sentence.

    ORDERING IS THE WHOLE CLAIM, so this measures positions in the document.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    apply_at = runbook.index(
        "kustomize build deploy/kubernetes/overlays/managed-database "
        "| kubectl apply")
    for earlier in (
            "**Set `runtime_pg_role` in that overlay",   # names the role
            "\\getenv runtime_role OPENDOX_RUNTIME_PG_ROLE",  # creates it
            "\\gexec",                                   # runs that block
    ):
        assert runbook.index(earlier) < apply_at, (
            f"the managed-database apply comes BEFORE {earlier!r}; an operator "
            f"working top to bottom would narrow the bundled role")

    # And the dev path's apply still comes after the Secrets it needs, which is
    # the same rule for the other overlay.
    dev_at = runbook.index(
        "kustomize build deploy/kubernetes/overlays/dev | kubectl apply")
    assert runbook.index("create secret generic opendox-db-runtime") < dev_at


def test_the_secret_block_is_fail_fast_and_its_set_e_is_not_defeated() -> None:
    """A failed `create secret` stops the block, and `set -e` actually runs.

    THE FINDING (Copilot review of openDox-code#25, rounds 27 and 29,
    suppressed twice): the block had no fail-fast, so a failed `kubectl create
    secret` was followed by the remaining creates and by the cleanup, and a run
    that had not created the credentials looked like one that had.

    THREE PROPERTIES, and each is here because the obvious fix breaks one:

      * `set -e` is INSIDE A SUBSHELL. Pasted into an interactive shell it
        would close the operator's own shell on the first failure.
      * the subshell's status is taken by `$?` ON ITS OWN LINE. MEASURED with
        a `kubectl` stub that refuses the first create: written as `) && ok=yes
        || ok=no`, bash SUPPRESSES `set -e` inside a compound command that is
        an operand of `&&`/`||` — the suppression is inherited — and all three
        creates ran and the status was 0. With `secrets_created=$?` the block
        stopped at the first failure, the EXIT trap removed the files, and the
        status was 1.
      * the signal traps `exit` rather than re-raising. `$$` inside a subshell
        is still the PARENT's pid, so the round-26 `kill -INT $$` would have
        signalled the operator's shell from inside the subshell.

    The apply is guarded on that status, so a half-created install applies
    nothing.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    start = runbook.index("(\n  set -e")
    block = runbook[start:runbook.index("secrets_created=$?", start)]

    assert "set -e" in block
    assert block.count("kubectl -n opendox create secret") == 3, (
        "this test is written against the three creates the base needs")
    assert "kill -INT $$" not in block and "kill -TERM $$" not in block, (
        "`$$` in a subshell is the operator's shell, not this one")
    for signal, status in (("EXIT", None), ("INT", "130"), ("TERM", "143")):
        line = [l for l in block.splitlines() if f"' {signal}" in l]
        assert line, f"no trap for {signal}"
        assert 'rm -rf "$secrets"' in line[0], line
        if status:
            assert f"exit {status}" in line[0], line

    assert ") && secrets_created" not in runbook, (
        "an `&&` after the subshell suppresses the `set -e` inside it; "
        "measured, and it ran every remaining kubectl")
    assert "\n)\n" in runbook[start:start + len(block) + 200] or \
        "\n)\n" in runbook[start:], "the subshell is never closed"

    # AND THE APPLY IS GUARDED ON IT.
    assert '[ "${secrets_created:-1}" -ne 0 ]' in runbook, (
        "the documented apply does not check whether the Secrets were created")
    apply_at = runbook.index(
        "kustomize build deploy/kubernetes/overlays/dev | kubectl apply")
    assert runbook.index('[ "${secrets_created:-1}" -ne 0 ]') < apply_at


def test_the_bootstrap_grants_the_coordination_tables_and_no_others() -> None:
    """Least privilege, and the table list is DERIVED rather than restated.

    THE FINDING (Copilot review of openDox-code#25, round 30, on both copies of
    the script and on the runbook): `grant … on all tables in schema public`
    hands the served role select/insert/update/delete on every table that
    schema already holds — another application's data on a reused or managed
    database, which the migration preflight explicitly tolerates being there.
    It was not even doing the job it looked like it was doing: at first start
    the coordination tables do not exist yet, so that grant could only ever
    reach tables this install did not create.

    THE REPLACEMENT IS TWO NARROW HALVES, and both are measured on postgres
    16.15 rather than reasoned about:

      * `alter default privileges for role <owner>` covers every table the
        MIGRATION OWNER creates from then on — measured: a table the owner
        creates afterwards carries `DELETE, INSERT, SELECT, UPDATE` for the
        served role, and a table created by anybody else carries none;
      * a JOIN against the catalogue grants the coordination tables that
        ALREADY exist, for a database migrated before the prerequisite ran —
        measured: with `projects` and `unrelated_app` both present it emitted
        exactly `grant … on table projects …`, and the unrelated table ended
        with zero grants for the served role.

    THE LIST IS DERIVED HERE, from `identity.TABLES` and
    `migrations.LEDGER_TABLE`, so a seventh coordination table cannot be added
    to the schema and left out of the grant — which is the failure the broad
    grant was hiding.
    """
    from opendox.runtime import identity, migrations

    expected = sorted(set(identity.TABLES) | {migrations.LEDGER_TABLE})
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    script = (COMPOSE / "init-runtime-role.sh").read_text(encoding="utf-8")

    for name, text in (("init-runtime-role.sh", script),
                       ("docs/runtime.md", runbook)):
        assert "on all tables in schema " not in text.replace(
            "`on all tables in schema public`", ""), (
            f"{name} still grants the served role every table in the schema")
        listed = re.search(r"c\.relname = any \(array\[(.*?)\]\)", text,
                           re.S)
        assert listed, f"{name} has no derived coordination-table list"
        names = sorted(re.findall(r"'([a-z_]+)'", listed.group(1)))
        assert names == expected, (
            f"{name} grants {names}; the coordination tables are {expected}")
        assert "alter default privileges" in text, (
            f"{name} drops the grant that covers the tables the migration "
            f"owner has yet to create")


def test_the_readiness_probe_bounds_its_own_statements() -> None:
    """The probe's budget covers waiting for a connection AND using it.

    THE FINDING (Copilot review of openDox-code#25, round 30, suppressed): the
    budget bounded the pool checkout and the JWKS fetch, and `Database.
    connection(timeout=…)` sets no statement or socket timeout — so once a
    connection was in hand, a lock or a stalled server could hold `select 1`
    past `timeoutSeconds`, kubelet would cut the probe off, and the next probe
    would overlap it. The comment above the endpoint claimed the full budget
    was covered.

    `SET LOCAL` IN AN EXPLICIT TRANSACTION, and that shape is measured rather
    than idiomatic: a session-level `set statement_timeout` on a POOLED
    connection survived the checkout it was made in — a later checkout of the
    same connection still read `1234ms` — so the bound would have leaked onto
    whatever request borrowed that connection next. And the value is
    interpolated because `SET` takes no bind parameter: `set local
    statement_timeout = %s` is a `SyntaxError` from PostgreSQL, measured.
    """
    import ast

    source = (ROOT / "src" / "opendox" / "runtime" / "app.py").read_text(
        encoding="utf-8")
    assert '"set local statement_timeout = "' in source, (
        "the readiness path no longer bounds its own statements")
    assert "READINESS_STATEMENT_TIMEOUT_SECONDS" in source
    assert "READINESS_DATABASE_BUDGET_SECONDS" in source, (
        "the per-statement ceiling is not a total, and this probe runs four "
        "statements")
    assert 'conn.execute("set statement_timeout' not in source, (
        "a session-level statement timeout leaks out of the checkout")

    # ASKED OF THE PARSE TREE, because the bound is now set by a closure the
    # transaction calls rather than by a literal beside it — and proximity in
    # the source proves nothing about a function. What must hold is that every
    # call that sets the bound, and every statement it guards, happens INSIDE
    # `with conn.transaction():`: `SET LOCAL` outside a transaction is a no-op
    # with a warning, and a session-level SET leaks onto the next borrower of
    # a pooled connection.
    readyz = next(n for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.FunctionDef) and n.name == "readyz")
    setter = next(n for n in ast.walk(readyz)
                  if isinstance(n, ast.FunctionDef) and n.name == "_bound_by")
    assert any(isinstance(node, ast.Constant) and isinstance(node.value, str)
               and node.value.startswith("set local statement_timeout")
               for node in ast.walk(setter)), (
        "`_bound_by` no longer sets the bound it is named for")

    transactions = [n for n in ast.walk(readyz) if isinstance(n, ast.With)
                    and "transaction" in ast.dump(n.items[0].context_expr)]
    assert len(transactions) == 1
    inside = {id(n) for n in ast.walk(transactions[0])}
    calls = [n for n in ast.walk(readyz) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_bound_by"]
    assert len(calls) == 3, (
        "the probe runs `select 1`, `plan()` and `drift()`; each phase must "
        "re-read the deadline or the budget is not a total")
    assert all(id(call) in inside for call in calls), (
        "a `SET LOCAL` outside the transaction is a no-op with a warning")


def test_every_secret_prompt_aborts_the_block_and_every_create_is_idempotent(
) -> None:
    """Two ways the documented block could look successful and not be.

    TWO FINDINGS (Copilot review of openDox-code#25, round 32, suppressed):

    * **`set -e` does not abort on the left operand of `&&`.** MEASURED: with
      `read -rs -p … && printf …`, an EOF on stdin left the block RUNNING with
      the variable unset — "second command ran", status 0 — so a Secret could
      be created from a file that was never written. Each prompt is its own
      `if ! read …; then … exit 1; fi` now, and the same measurement on that
      form stops at the failed read with status 1.
    * **Three independent `create` calls are not re-runnable.** A failure in
      the second or third leaves the earlier Secrets behind, and the re-run
      fails with `AlreadyExists` — an install half-configured and a cleanup by
      hand. `create --dry-run=client -o yaml | kubectl apply -f -` renders the
      same object and applies it: created once, updated thereafter.

    The value still never reaches a command line, which is round 19's rule and
    the reason `--from-file` is there at all — so this test asserts that too,
    since an idempotent form built from `--from-literal` would trade one defect
    for a worse one.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    start = runbook.index("(\n  set -e")
    block = runbook[start:runbook.index("secrets_created=$?", start)]

    executable = "\n".join(line for line in block.splitlines()
                           if not line.strip().startswith("#"))
    assert "&& printf" not in executable, (
        "a prompt whose failure `set -e` does not see; measured to leave the "
        "block running with the variable unset")
    prompts = [line for line in block.splitlines() if "read -rs -p" in line]
    assert len(prompts) == 4, prompts
    for line in prompts:
        assert line.strip().startswith("if ! read"), line

    creates = [line for line in block.splitlines()
               if "create secret generic" in line]
    assert len(creates) == 3, creates
    for name in ("opendox-postgres", "opendox-db-runtime",
                 "opendox-db-migration"):
        rendered = block.split(f"generic {name}", 1)[1].split("\n\n", 1)[0]
        assert "--dry-run=client -o yaml | kubectl -n opendox apply -f -" in \
            rendered, (name, rendered)
        assert "--from-literal" not in rendered, (
            f"{name} puts a value on a command line, where `ps` and "
            f"/proc/<pid>/cmdline can read it")


def test_the_healthcheck_probes_the_configured_bind_host_and_not_localhost(
) -> None:
    """The port finding's twin, one setting over.

    `OPENDOX_BIND_HOST` is a service setting (`${OPENDOX_BIND_HOST:-0.0.0.0}`
    in the compose `environment:`), and the probe always connected to
    `localhost` — so a container told to bind its own address served every
    request while this check got `connection refused`, marked it unhealthy and
    had the orchestrator restart a working server (Copilot review of
    openDox-code#25, round 35, suppressed).

    THE SCRIPT IS RUN, not read for a substring: what matters is the URL it
    actually dials for each configured value, and a wildcard must be MAPPED
    rather than dialled because nothing connects to `0.0.0.0`.
    """
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    service = compose["services"]["opendox"]
    script = service["healthcheck"]["test"][-1]
    assert PREFIX + "BIND_HOST" in script, (
        "the healthcheck names a literal host; a configured bind host is "
        "permanently unhealthy")
    assert "${" not in script, "an operator's value is interpolated again"
    assert service["environment"][PREFIX + "BIND_HOST"].startswith(
        "${" + PREFIX + "BIND_HOST"), (
        "the container is not given the host the probe reads")

    def dialled(environment: dict[str, str]) -> str:
        """The URL this exact script opens, with the environment it is given."""
        seen: list[str] = []

        class _Answer:
            status = 200

        def urlopen(url: str, timeout: float | None = None) -> _Answer:
            seen.append(url)
            return _Answer()

        import types
        request = types.SimpleNamespace(urlopen=urlopen)
        namespace = {"os": types.SimpleNamespace(environ=environment),
                     "urllib": types.SimpleNamespace(request=request),
                     "sys": types.SimpleNamespace(exit=lambda code: None)}
        # The script's own `import` statements are dropped so the stubs above
        # are what it reaches; every other character is the shipped one.
        body = script.split(";", 1)[1].lstrip()
        assert script.split(";", 1)[0].startswith("import ")
        exec(body, namespace)  # noqa: S102 - the subject of the test
        return seen[0]

    # A WILDCARD IS MAPPED TO THE LOOPBACK ADDRESS OF ITS OWN FAMILY, an IPv6
    # literal is bracketed, and every other value is dialled verbatim.
    assert dialled({}) == "http://127.0.0.1:8080/livez"
    assert dialled({PREFIX + "BIND_HOST": "0.0.0.0"}
                   ) == "http://127.0.0.1:8080/livez"
    assert dialled({PREFIX + "BIND_HOST": "::", PREFIX + "BIND_PORT": "9443"}
                   ) == "http://[::1]:9443/livez"
    assert dialled({PREFIX + "BIND_HOST": "172.20.0.5"}
                   ) == "http://172.20.0.5:8080/livez"
    assert dialled({PREFIX + "BIND_HOST": "fd00::5"}
                   ) == "http://[fd00::5]:8080/livez"

    # AND THE SHAPE IT FORBIDS IS RUN: the previous spelling dialled
    # `localhost` for every one of those, which is the defect.
    previous = ("import os,urllib.request,sys; sys.exit(0 if "
                "urllib.request.urlopen('http://localhost:%s/livez' % "
                "int(os.environ.get('OPENDOX_BIND_PORT') or 8080),"
                "timeout=3).status==200 else 1)")
    script = previous
    assert dialled({PREFIX + "BIND_HOST": "172.20.0.5"}
                   ) == "http://localhost:8080/livez"


def test_the_secret_block_stops_when_the_left_side_of_a_pipeline_fails(
) -> None:
    """`set -e` alone does not see a failure inside a pipeline.

    Every Secret is created by `kubectl create --dry-run=client -o yaml |
    kubectl apply -f -`, and a shell reports a pipeline's status as its RIGHT
    side's — so a failed `create` followed by an `apply` that exits 0 left
    `set -e` nothing to act on and the block carried on as though the Secret
    had been made (Copilot review of openDox-code#25, round 35, suppressed).
    """
    import subprocess

    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    block = runbook[runbook.index("(\n  set -e"):]
    block = block[:block.index("\n)")]
    assert "set -e -o pipefail" in block, (
        "the secret subshell enables `set -e` without `pipefail`, so a failed "
        "`kubectl create` in a pipeline does not stop it")
    assert "--dry-run=client -o yaml | kubectl apply -f -" in block

    # BOTH WAYS, MEASURED IN THE SHELL THE BLOCK IS WRITTEN FOR — a claim
    # about `set -e` is worth nothing unread from an actual shell.
    without = subprocess.run(
        ["bash", "-c", "set -e; (exit 3) | cat; echo reached"],
        capture_output=True, text=True, check=False)
    assert without.returncode == 0 and "reached" in without.stdout, (
        "this shell already stops on a failed left side; the finding would "
        "not reproduce and the fix would be untested")
    with_it = subprocess.run(
        ["bash", "-c", "set -e -o pipefail; (exit 3) | cat; echo reached"],
        capture_output=True, text=True, check=False)
    assert with_it.returncode == 3 and "reached" not in with_it.stdout


def test_the_managed_database_prerequisite_refuses_before_it_provisions(
) -> None:
    """psql runs the NEXT statement after a failed one unless told not to.

    An unprovisioned migration owner made the `create role` fail while the
    grants below it still ran, so the prerequisite ended looking successful
    with the identity it exists to create never made; and the shell block above
    it can only DECLINE TO EXPORT an empty password — it must export into the
    operator's own shell for `\\getenv` to see anything, so it cannot be a
    subshell and `exit 1` in it would close that shell. An operator who pasted
    this block anyway reached `create role … password %L` with nothing (Copilot
    review of openDox-code#25, round 35, suppressed).

    NOT MEASURED AGAINST A SERVER: no `psql` binary exists in the `validate`
    job, which installs `.[test]` and nothing else. What is asserted is the
    ORDER — every guard before the first act — which is the property that was
    wrong, and `deploy/*/init-runtime-role.sh` carry the same setting in the
    spelling psql takes on its command line.
    """
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    start = runbook.index("\\getenv runtime_role OPENDOX_RUNTIME_PG_ROLE")
    block = runbook[runbook.rindex("```sql", 0, start):]
    block = block[:block.index("\n```")]

    assert "\\set ON_ERROR_STOP on" in block, (
        "psql reports a failed statement and runs the next one; this block "
        "must stop on the first error the way the bundled bootstrap does")
    assert "ON_ERROR_STOP=1" in (
        ROOT / "deploy" / "compose" / "init-runtime-role.sh"
    ).read_text(encoding="utf-8"), "the bundled bootstrap lost its own setting"

    create = block.index("create role %I login password %L")
    assert block.index("\\set ON_ERROR_STOP on") < create
    # THE BLANK-PASSWORD GUARD IS BEFORE THE ROLE IS CREATED, and it raises
    # rather than warning: with `ON_ERROR_STOP` a raised exception is what
    # gives psql a nonzero exit.
    assert block.index("\\if :opendox_blank_password") < create
    assert block.index("raise exception") < create
    assert "\\if :{?runtime_password}" in block, (
        "an UNSET variable is not an empty one in psql; `:'runtime_password'` "
        "would be substituted as its own literal text")
    assert block.index("\\if :{?runtime_password}") < block.index(
        "\\if :opendox_blank_password")


def test_the_bootstrap_grants_in_the_schema_the_dsns_select(
) -> None:
    """A supported DSN shape the bootstrap could not serve.

    A runtime DSN may carry `options=-c search_path=<schema>` — a form
    `migrations.selected_schema` supports and validates, and `load_settings`
    refuses two DSNs from disagreeing about — while every grant in the
    first-start bootstrap named `public`. In that configuration the DDL lands
    in the selected schema and the served role gets no USAGE there, no table
    grants there and no default privilege there, so `verify_runtime_access`
    fails the migration and the install cannot start (Copilot review of
    openDox-code#25, round 36, suppressed).

    The bootstrap cannot read a DSN — it is the DATABASE container's
    environment and a DSN carries a password — so the schema arrives as its
    own variable and the runbook says it must be the same one.
    """
    scripts = [(COMPOSE / "init-runtime-role.sh"),
               (KUBERNETES / "base" / "init-runtime-role.sh")]
    for path in scripts:
        text = path.read_text(encoding="utf-8")
        assert 'schema="${OPENDOX_PG_SCHEMA:-public}"' in text, (
            f"{path.name} has no schema variable; every grant in it is "
            "hard-coded to `public`")
        assert '-v schema="$schema"' in text, (
            f"{path.name} does not pass the schema to psql")
        assert "grant usage on schema %I" in text
        assert "in schema %I grant " in text
        assert "n.nspname = :'schema'" in text
        assert "n.nspname = 'public'" not in text, (
            f"{path.name} still pins a grant to `public`")
        # THE SCHEMA IS CREATED BEFORE IT IS GRANTED ON, and only when it is
        # not `public`, which every database already has.
        assert "create schema if not exists %I authorization %I" in text
        assert "where :'schema' <> 'public'" in text

    # THE VARIABLE IS SUPPLIED BY BOTH DEPLOYMENTS, or the script reads a
    # default nothing configured.
    compose = _load_yaml(COMPOSE / "docker-compose.yaml")
    assert compose["services"]["postgres"]["environment"][
        "OPENDOX_PG_SCHEMA"].startswith("${OPENDOX_PG_SCHEMA")
    assert "OPENDOX_PG_SCHEMA" in ENV_EXAMPLE.read_text(encoding="utf-8")
    statefulset = _load_yaml(KUBERNETES / "base" / "postgres-statefulset.yaml")
    named = {v["name"]: v for v in _containers(statefulset)[0]["env"]}
    assert named["OPENDOX_PG_SCHEMA"]["valueFrom"]["configMapKeyRef"][
        "key"] == "pg_schema"
    assert "pg_schema=" in (
        KUBERNETES / "base" / "kustomization.yaml").read_text(encoding="utf-8")

    # AND THE RUNBOOK'S MANAGED PATH TAKES THE SAME VARIABLE, since it is the
    # hand-run copy of this script.
    runbook = (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")
    assert "\\getenv schema OPENDOX_PG_SCHEMA" in runbook
    assert "export OPENDOX_PG_SCHEMA=public" in runbook


def test_the_default_privilege_is_refused_for_a_shared_migration_owner(
) -> None:
    """`alter default privileges` follows the ROLE, not a table list.

    So every table that owner creates from here on becomes readable and
    writable by the served role — and on a shared or reused database, which
    the managed path explicitly tolerates, that is another application's data:
    the same boundary replacing `grant … on all tables in schema public` was
    meant to draw (Copilot review of openDox-code#25, round 36).

    The grant is refused when the owner already owns a table this runtime did
    not create. MEASURED on postgres 16.15 against the shipped statement with
    `:'owner'` and `:'schema'` bound: no row for a schema with no tables, no
    row for one holding only the seven coordination tables, exactly one row
    for an owner that also owns `invoices` — and that row's `do` block raises
    with the message naming the owner and the foreign table. `\\gexec` runs
    nothing when there is no row, so the `having` is the whole conditional.
    """
    from opendox.runtime import identity, migrations

    expected = sorted(set(identity.TABLES) | {migrations.LEDGER_TABLE})
    for text in [(COMPOSE / "init-runtime-role.sh").read_text(encoding="utf-8"),
                 (KUBERNETES / "base" / "init-runtime-role.sh").read_text(
                     encoding="utf-8"),
                 (ROOT / "docs" / "runtime.md").read_text(encoding="utf-8")]:
        guard = text[text.index("do $refuse$ begin raise exception %L"):]
        guard = guard[:guard.index("\\gexec")]
        assert "r.rolname = :'migration_owner'" in guard, (
            "the guard does not ask about the migration owner's own tables")
        assert "having count(*) > 0" in guard, (
            "without the `having`, `\\gexec` is handed a row on every install "
            "and the bootstrap always refuses")
        assert "c.relname <> all (array[" in guard
        # THE EXEMPT LIST IS THIS RUNTIME'S OWN TABLES, derived rather than
        # typed, so a migration that adds one cannot make the guard refuse a
        # correct install.
        named = sorted(re.findall(r"'([a-z_]+)'",
                                  guard.split("array[", 1)[1].split("]", 1)[0]))
        assert named == expected, (
            f"the guard exempts {named}; this runtime's tables are {expected}")
        # AND IT IS BEFORE THE GRANT IT GUARDS.
        assert text.index("having count(*) > 0") < text.index(
            "alter default privileges for role %I in schema %I")
