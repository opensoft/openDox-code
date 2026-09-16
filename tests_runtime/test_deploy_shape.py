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
    "OPENDOX_RUNTIME_PG_USER", "OPENDOX_RUNTIME_PG_PASSWORD",
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
    assert 'pip install --no-cache-dir ".[runtime]"' in dockerfile
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
        assert "stringData" not in document and (
            document.get("kind") == "ConfigMap" or "data" not in document), (
            f"{path} carries a `data:`/`stringData:` block outside a ConfigMap")


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


def test_the_neutral_base_leaves_the_broker_empty_rather_than_plausible() -> None:
    """An empty issuer refuses at startup; a plausible one is trusted silently."""
    kustomization = _load_yaml(KUBERNETES / "base" / "kustomization.yaml")
    generator = kustomization["configMapGenerator"][0]
    assert generator["name"] == "opendox-oidc"
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
