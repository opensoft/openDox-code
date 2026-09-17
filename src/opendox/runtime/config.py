"""Runtime configuration, read from the environment and from nowhere else.

EVERY SETTING IS AN ENVIRONMENT VARIABLE NAMED IN `deploy/compose/.env.example`,
and this module is the only place their names are spelled in Python. A setting
that appears in a compose file, a Kubernetes ConfigMap and a Python default is
three spellings of one thing; `tests_runtime/test_deploy_shape.py` reads
`SETTINGS` below against `deploy/compose/.env.example` and against the
Kubernetes manifests, so the three cannot drift apart while all three keep
working.

NO CREDENTIAL IS EVER A DEFAULT AND NO CREDENTIAL IS EVER LOGGED. The two DSNs
carry a password in production and therefore have NO default at all: a runtime
with no `OPENDOX_DATABASE_URL` REFUSES to start, naming the variable, rather
than falling back to a local one that would silently be the wrong database.
`RuntimeSettings.__repr__` is overridden to redact both, because a settings
object reaches a log line the first time somebody debugs a startup failure.

WHY A FROZEN DATACLASS AND NOT `pydantic-settings` (which the Hermes install
uses). This subpackage's import weight is a contract — see the package
docstring — and `opendox.runtime.config` has to import under the leg's
`validate` check, which installs `.[test]` and not `.[runtime]`. A settings
object built out of the standard library costs nothing to import and is the
only reason `opendox runtime status` can tell a reader that FastAPI is missing
instead of failing to start with the same ImportError it was about to explain.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: The environment prefix. One string, so a rename is one edit.
PREFIX = "OPENDOX_"

#: The issuer and audience a MIGRATION run carries. Sentinels, and they are
#: sentinels rather than empty strings so that anything which reached a broker
#: with them would fail loudly and name this constant rather than silently
#: trusting an unpinned issuer. `.invalid` is reserved (RFC 2606) and can never
#: resolve.
MIGRATION_SENTINEL_ISSUER = "https://migration-run.opendox.invalid/no-broker"
MIGRATION_SENTINEL_AUDIENCE = "opendox-migration-run"


class ConfigurationError(Exception):
    """A setting that is absent or unusable, named. Carries no secret material.

    One exception for the whole module because a caller does nothing different
    for any of them: the runtime must not start.
    """


@dataclass(frozen=True)
class Setting:
    """One environment variable, its default and why it has the default it has.

    `secret` marks a value that must never be printed, logged or written into
    an evidence document. `required` marks one with no usable default: absent,
    it is a refusal and not a fallback.
    """

    name: str
    default: str | None
    required: bool
    secret: bool
    purpose: str


#: THE CLOSED SETTING LIST. Ordered as a reader meets them: where the database
#: is, where the broker is, where the service listens, where the migrations and
#: the project repositories live.
SETTINGS: tuple[Setting, ...] = (
    Setting(
        PREFIX + "DATABASE_URL", None, True, True,
        "the RUNTIME DSN — the least-privileged identity the API serves with; "
        "it must not be the identity migrations run as",
    ),
    Setting(
        PREFIX + "MIGRATION_DATABASE_URL", None, False, True,
        "the PRIVILEGED DSN ordered-SQL migrations are applied with, used by "
        "`opendox runtime migrate` alone and never by the served application",
    ),
    Setting(
        PREFIX + "OIDC_ISSUER", None, True, False,
        "the Keycloak broker's issuer, pinned: a token from any other issuer "
        "is refused rather than trusted (RULING Q2)",
    ),
    Setting(
        PREFIX + "OIDC_AUDIENCE", None, True, False,
        "the audience this runtime accepts; a token minted for another client "
        "of the same broker is not a token for this one",
    ),
    Setting(
        PREFIX + "OIDC_JWKS_URL", None, False, False,
        "the broker's JWKS URL. When unset it is the issuer with "
        "`/protocol/openid-connect/certs` appended — the fixed Keycloak "
        "endpoint, NOT a discovery request: nothing here reads "
        "`.well-known/openid-configuration`, so a broker that publishes a "
        "different `jwks_uri` must set this (Copilot review of "
        "openDox-code#25, round 16, suppressed: the setting promised a "
        "discovery this runtime does not make)",
    ),
    Setting(
        PREFIX + "OIDC_ALGORITHMS", "RS256", False, False,
        "the ASYMMETRIC signature algorithms accepted, comma-separated; the "
        "allow-list is what defeats the `alg: none` downgrade",
    ),
    Setting(
        PREFIX + "OIDC_JWKS_TTL_SECONDS", "300", False, False,
        "how long a fetched key set is reused before it is refetched",
    ),
    Setting(
        PREFIX + "OIDC_LEEWAY_SECONDS", "60", False, False,
        "clock skew allowed when checking `exp`",
    ),
    Setting(
        PREFIX + "BIND_HOST", "127.0.0.1", False, False,
        "the interface the API binds; the container overrides it to 0.0.0.0 "
        "and a developer's default stays loopback",
    ),
    Setting(
        PREFIX + "BIND_PORT", "8080", False, False,
        "the port the API binds",
    ),
    Setting(
        PREFIX + "RUNTIME_PG_ROLE", "", False, False,
        "the NAME (never a credential) of the least-privileged role the served "
        "application connects as; when set, `migrate` narrows that role's "
        "rights on the migration ledger to SELECT after applying, so a "
        "compromised API cannot rewrite the runner's own record",
    ),
    Setting(
        PREFIX + "PUBLISH_OPENAPI", "false", False, False,
        "whether to serve the interactive schema at /docs, /redoc and "
        "/openapi.json; OFF by default, because FastAPI's defaults would "
        "otherwise publish the whole API surface to an unauthenticated caller",
    ),
    Setting(
        PREFIX + "MIGRATIONS_DIR", "migrations", False, False,
        "the ordered-SQL directory, repository-root-relative",
    ),
    Setting(
        PREFIX + "PROJECT_REPOSITORY_ROOT", "var/projects", False, False,
        "where the repository-creation act creates a project's plain local git "
        "repository (RULING C3); one directory per project id",
    ),
)

SETTING_NAMES: tuple[str, ...] = tuple(setting.name for setting in SETTINGS)

#: The settings whose values must never be printed. Read by the CLI's `status`
#: verb and by the evidence it emits.
SECRET_NAMES: frozenset[str] = frozenset(s.name for s in SETTINGS if s.secret)


@dataclass(frozen=True)
class RuntimeSettings:
    """The resolved configuration of one runtime process.

    Construct with :func:`load_settings`; the fields are in `SETTINGS` order.
    """

    database_url: str
    migration_database_url: str | None
    oidc_issuer: str
    oidc_audience: str
    oidc_jwks_url: str | None
    oidc_algorithms: tuple[str, ...]
    oidc_jwks_ttl_seconds: int
    oidc_leeway_seconds: int
    bind_host: str
    bind_port: int
    runtime_pg_role: str | None
    publish_openapi: bool
    migrations_dir: Path
    project_repository_root: Path

    def __repr__(self) -> str:
        """Redacted, because a settings object reaches a log line eventually."""
        return (
            "RuntimeSettings(database_url=<redacted>, "
            "migration_database_url="
            f"{'<redacted>' if self.migration_database_url else 'None'}, "
            f"oidc_issuer={self.oidc_issuer!r}, "
            f"oidc_audience={self.oidc_audience!r}, "
            f"oidc_jwks_url={self.oidc_jwks_url!r}, "
            f"oidc_algorithms={self.oidc_algorithms!r}, "
            f"oidc_jwks_ttl_seconds={self.oidc_jwks_ttl_seconds!r}, "
            f"oidc_leeway_seconds={self.oidc_leeway_seconds!r}, "
            f"bind_host={self.bind_host!r}, bind_port={self.bind_port!r}, "
            f"runtime_pg_role={self.runtime_pg_role!r}, "
            f"publish_openapi={self.publish_openapi!r}, "
            f"migrations_dir={str(self.migrations_dir)!r}, "
            f"project_repository_root={str(self.project_repository_root)!r})"
        )

    def jwks_url(self) -> str:
        """The key-set URL, explicit or derived from the pinned issuer.

        Keycloak publishes `<issuer>/protocol/openid-connect/certs` and
        advertises it in `<issuer>/.well-known/openid-configuration`. Deriving
        it saves one variable in the common case; setting it explicitly is what
        a broker behind a rewriting proxy needs, which is why the variable
        exists at all rather than the URL always being computed.
        """
        if self.oidc_jwks_url:
            return self.oidc_jwks_url
        return self.oidc_issuer.rstrip("/") + "/protocol/openid-connect/certs"

    def discovery_url(self) -> str:
        """The issuer's discovery document, for `opendox runtime status`."""
        return self.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"


def _require(env: Mapping[str, str], setting: Setting) -> str:
    value = env.get(setting.name, "").strip()
    if not value:
        raise ConfigurationError(
            f"{setting.name} is required and is not set: {setting.purpose}. "
            f"See deploy/compose/.env.example."
        )
    return value


def _optional(env: Mapping[str, str], setting: Setting) -> str | None:
    value = env.get(setting.name, "").strip()
    return value or setting.default


def _positive_int(env: Mapping[str, str], setting: Setting) -> int:
    raw = env.get(setting.name, "").strip() or (setting.default or "")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"{setting.name} must be a whole number, not {raw!r}: "
            f"{setting.purpose}"
        ) from exc
    if value <= 0:
        raise ConfigurationError(
            f"{setting.name} must be greater than zero, not {value}: "
            f"{setting.purpose}"
        )
    return value


#: The asymmetric signature algorithms this runtime may be configured with,
#: spelled EXACTLY as PyJWT spells them — which is why they are a declared set
#: and not a prefix test over an upper-cased string. Measured: PyJWT's name is
#: `EdDSA`, mixed case; upper-casing the configured value turned it into
#: `EDDSA`, which then failed a `startswith(("RS", "ES", "PS", "Ed"))` test and
#: was refused as symmetric — and would not have matched a token's `alg` header
#: either, since `jwt.decode`'s comparison is case-sensitive (Copilot review of
#: openDox-code#25). A configured name is now matched case-INSENSITIVELY
#: against this set and CANONICALIZED to the spelling in it.
ASYMMETRIC_ALGORITHMS: tuple[str, ...] = (
    "RS256", "RS384", "RS512",
    "PS256", "PS384", "PS512",
    "ES256", "ES256K", "ES384", "ES512",
    "EdDSA",
)

_CANONICAL_ALGORITHM = {name.lower(): name for name in ASYMMETRIC_ALGORITHMS}


def _algorithms(env: Mapping[str, str]) -> tuple[str, ...]:
    """The configured allow-list, canonicalized, or a refusal naming the value.

    REFUSED AT CONFIGURATION TIME AND NOT AT THE FIRST TOKEN: a runtime
    configured to accept `HS256` would verify a token signed with the public
    key anybody can fetch from the broker's JWKS, and discovering that on the
    first request means it is already serving.
    """
    configured = [part.strip() for part
                  in (_optional(env, _by_name(PREFIX + "OIDC_ALGORITHMS")) or "").split(",")
                  if part.strip()]
    if not configured:
        raise ConfigurationError(
            f"{PREFIX}OIDC_ALGORITHMS resolved to an empty allow-list; a "
            "runtime that accepts no algorithm can verify no token")
    unknown = [name for name in configured
               if name.lower() not in _CANONICAL_ALGORITHM]
    if unknown:
        raise ConfigurationError(
            f"{PREFIX}OIDC_ALGORITHMS names {unknown}, which is not among the "
            f"asymmetric signature algorithms {list(ASYMMETRIC_ALGORITHMS)}. A "
            "shared-secret or `none` algorithm would let anybody holding the "
            "broker's PUBLIC key mint a token this runtime accepts")
    return tuple(_CANONICAL_ALGORITHM[name.lower()] for name in configured)


#: A plain, unquoted SQL identifier. The role NAME reaches a `revoke` that
#: cannot be parameterized — SQL takes identifiers as syntax, not as values —
#: so it is validated here against a closed shape and refused otherwise, which
#: is the only safe way to interpolate one.
_ROLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _role_name(env: Mapping[str, str]) -> str | None:
    value = env.get(PREFIX + "RUNTIME_PG_ROLE", "").strip()
    if not value:
        return None
    if not _ROLE_NAME.fullmatch(value):
        raise ConfigurationError(
            f"{PREFIX}RUNTIME_PG_ROLE is {value!r}, which is not a plain SQL "
            "identifier ([A-Za-z_][A-Za-z0-9_]*, at most 63 characters). A "
            "role name is interpolated into a `revoke` as SYNTAX and cannot be "
            "passed as a parameter, so a name outside this shape is refused "
            "rather than quoted and hoped for")
    return value


def _boolean(env: Mapping[str, str], setting: Setting) -> bool:
    """A strict boolean: the value is one of a named set, or it is a refusal.

    Deliberately NOT `bool(value)` and not "anything but empty is true":
    `OPENDOX_PUBLISH_OPENAPI=off` reading as TRUE is how a surface nobody meant
    to publish ends up published.
    """
    raw = (env.get(setting.name, "").strip() or (setting.default or "")).lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(
        f"{setting.name} must be one of true/false/yes/no/on/off/1/0, not "
        f"{raw!r}: {setting.purpose}")


def _by_name(name: str) -> Setting:
    for setting in SETTINGS:
        if setting.name == name:
            return setting
    raise KeyError(name)  # pragma: no cover - a typo in this module


def load_settings(env: Mapping[str, str] | None = None) -> RuntimeSettings:
    """Resolve :class:`RuntimeSettings` from `env` (default `os.environ`).

    Refuses with :class:`ConfigurationError` naming the variable — never with a
    default that would point a runtime at the wrong database or trust the wrong
    issuer.

    ALGORITHMS ARE ALLOW-LISTED AND SYMMETRIC ONES ARE REFUSED HERE, at
    configuration time rather than at the first token: a runtime configured to
    accept `HS256` would verify a token signed with the public key anybody can
    fetch from the broker's JWKS, and discovering that on the first request
    means it is already serving.
    """
    env = os.environ if env is None else env

    algorithms = _algorithms(env)

    return RuntimeSettings(
        database_url=_require(env, _by_name(PREFIX + "DATABASE_URL")),
        migration_database_url=_optional(env, _by_name(PREFIX + "MIGRATION_DATABASE_URL")),
        oidc_issuer=_require(env, _by_name(PREFIX + "OIDC_ISSUER")),
        oidc_audience=_require(env, _by_name(PREFIX + "OIDC_AUDIENCE")),
        oidc_jwks_url=_optional(env, _by_name(PREFIX + "OIDC_JWKS_URL")),
        oidc_algorithms=algorithms,
        oidc_jwks_ttl_seconds=_positive_int(env, _by_name(PREFIX + "OIDC_JWKS_TTL_SECONDS")),
        oidc_leeway_seconds=_positive_int(env, _by_name(PREFIX + "OIDC_LEEWAY_SECONDS")),
        bind_host=_optional(env, _by_name(PREFIX + "BIND_HOST")) or "127.0.0.1",
        bind_port=_positive_int(env, _by_name(PREFIX + "BIND_PORT")),
        runtime_pg_role=_role_name(env),
        publish_openapi=_boolean(env, _by_name(PREFIX + "PUBLISH_OPENAPI")),
        migrations_dir=Path(_optional(env, _by_name(PREFIX + "MIGRATIONS_DIR")) or "migrations"),
        project_repository_root=Path(
            _optional(env, _by_name(PREFIX + "PROJECT_REPOSITORY_ROOT")) or "var/projects"
        ),
    )


def load_migration_settings(env: Mapping[str, str] | None = None) -> RuntimeSettings:
    """Settings for a MIGRATION run, which needs no served identity and no broker.

    WHY THIS EXISTS AT ALL — Copilot review of openDox-code#25, and the finding
    was right. `load_settings` requires `OPENDOX_DATABASE_URL`,
    `OPENDOX_OIDC_ISSUER` and `OPENDOX_OIDC_AUDIENCE`, so the compose migration
    service and the Kubernetes migration Job were handed the PRIVILEGED DSN in
    `OPENDOX_DATABASE_URL` as well, purely to satisfy the loader. That defeats
    the separation those two files exist to keep: any path in that container
    that read `settings.database_url` would have been running with
    schema-changing privileges.

    So a migration run loads THIS instead: the migration DSN and the migrations
    directory are real, and every served-identity field is a placeholder that
    cannot connect or trust anything — `database_url` is the SAME migration DSN
    the run is already using (so there is no second credential in the
    container, and nothing is silently *more* privileged than the run itself),
    the issuer and audience are unusable sentinels, and `publish_openapi` is
    off. `opendox-runtime runtime migrate` and `reset` use it; `serve` and `status` do
    not, because those are the served runtime and must have the real thing.
    """
    env = os.environ if env is None else env
    dsn = env.get(PREFIX + "MIGRATION_DATABASE_URL", "").strip()
    if not dsn:
        raise ConfigurationError(
            f"{PREFIX}MIGRATION_DATABASE_URL is required to apply migrations; "
            f"{PREFIX}DATABASE_URL is the served runtime's least-privileged "
            "identity and is deliberately not used for schema changes")
    return RuntimeSettings(
        database_url=dsn,
        migration_database_url=dsn,
        oidc_issuer=MIGRATION_SENTINEL_ISSUER,
        oidc_audience=MIGRATION_SENTINEL_AUDIENCE,
        oidc_jwks_url=None,
        oidc_algorithms=(ASYMMETRIC_ALGORITHMS[0],),
        oidc_jwks_ttl_seconds=1,
        oidc_leeway_seconds=1,
        bind_host="127.0.0.1",
        bind_port=1,
        runtime_pg_role=_role_name(env),
        publish_openapi=False,
        migrations_dir=Path(
            _optional(env, _by_name(PREFIX + "MIGRATIONS_DIR")) or "migrations"),
        project_repository_root=Path(
            _optional(env, _by_name(PREFIX + "PROJECT_REPOSITORY_ROOT"))
            or "var/projects"),
    )


def migration_database_url(settings: RuntimeSettings) -> str:
    """The DSN migrations are applied with, refusing rather than borrowing.

    SEPARATE IDENTITIES ARE THE POINT. The compose package and the Kubernetes
    manifests give the migration job a privileged role and the served
    application a least-privileged one, exactly as the Hermes install does
    (`deploy/compose/docker-compose.yaml`: "Privileged one-shot migration
    executor. This service is never the long-running application container and
    receives no runtime DSN"). Silently falling back to `OPENDOX_DATABASE_URL`
    here would undo that separation in the one place nobody looks, so an unset
    migration DSN is a refusal that names the variable.
    """
    if not settings.migration_database_url:
        raise ConfigurationError(
            f"{PREFIX}MIGRATION_DATABASE_URL is required to apply migrations; "
            f"{PREFIX}DATABASE_URL is the served runtime's least-privileged "
            "identity and is deliberately not used for schema changes"
        )
    return settings.migration_database_url
