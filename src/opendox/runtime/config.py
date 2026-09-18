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

import ipaddress
import os
import re
import urllib.parse
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
            # REDACTED TOO, and not because `load_settings` allows userinfo
            # here — it refuses it. A `RuntimeSettings` built by hand, in a
            # test or by a future caller, does not go through that door, and
            # this method's whole promise is about what reaches a log line
            # (Copilot review of openDox-code#25, round 22).
            f"oidc_issuer={redacted_url(self.oidc_issuer)!r}, "
            f"oidc_audience={self.oidc_audience!r}, "
            f"oidc_jwks_url={redacted_url(self.oidc_jwks_url)!r}, "
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


#: PARAMETER NAMES WHOSE VALUE IS A CREDENTIAL. A broker URL can carry one in
#: its QUERY as easily as in its userinfo — `https://broker/certs?token=…` — and
#: the userinfo guard looked only at the authority, so that form was accepted
#: and then printed by `repr(settings)` and by `status` (Copilot review of
#: openDox-code#25, round 24). `opendox.runtime.local_git_adapter` holds the
#: same list for the REMOTE rule on the sibling PR, and a case there pins the
#: two spellings together; this module cannot import it, because that module
#: does not exist on this branch.
SECRET_PARAMETER_KEYS = (
    "token", "access_token", "api_key", "apikey", "key", "secret",
    "password", "passwd", "pwd", "auth", "authorization", "credential",
    "credentials", "sig", "signature", "session",
)
_SECRET_PARAMETER = re.compile("|".join(SECRET_PARAMETER_KEYS), re.IGNORECASE)


def _split_url(name: str, value: str) -> urllib.parse.SplitResult:
    """`urlsplit`, with its `ValueError` inside this module's own boundary.

    MEASURED on python 3.12: `urlsplit("https://[::1/x")` raises
    `ValueError("Invalid IPv6 URL")`. This call sits in `load_settings`, whose
    whole contract is that a bad variable produces a `ConfigurationError`
    NAMING it — so a malformed broker URL escaped as a raw `ValueError` and the
    CLI printed a traceback where it promises a refusal (Copilot review of
    openDox-code#25, round 24).
    """
    try:
        return urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} is not a URL this runtime can parse ({exc}); set it to "
            "the broker endpoint, without userinfo") from exc


def redacted_url(value: str | None) -> str | None:
    """A URL with any userinfo replaced, for evidence and for `repr`.

    STDLIB ONLY, and deliberately small: this module is on the hermetic
    import-weight list, so it cannot reach for `local_git_adapter`'s redactor —
    and it does not need the general one. The values here are broker endpoints
    whose only credential-bearing shape is userinfo, which `urlsplit` names
    exactly (Copilot review of openDox-code#25, round 22).
    """
    if not value:
        return value
    try:
        split = urllib.parse.urlsplit(value)
    except ValueError:
        return "<redacted-url>"           # unparseable: shown whole or not at all
    netloc = split.netloc
    if "@" in netloc:
        netloc = "<redacted>@" + netloc.rsplit("@", 1)[1]
    query = _redacted_query(split.query)
    fragment = _redacted_query(split.fragment)
    if (netloc, query, fragment) == (split.netloc, split.query, split.fragment):
        return value
    return urllib.parse.urlunsplit(
        (split.scheme, netloc, split.path, query, fragment))


def _redacted_query(query: str) -> str:
    """Every credential-shaped parameter's VALUE replaced, the rest kept.

    The host is not the secret and neither is `?format=jwk`: an operator has to
    be able to see which endpoint was configured, which is the same trade the
    remote redactor makes on the sibling PR.
    """
    if not query:
        return query
    parts = []
    for part in re.split(r"([&;])", query):
        if part in ("&", ";"):
            parts.append(part)
            continue
        name, sep, _ = part.partition("=")
        parts.append(name + sep + "<redacted>"
                     if sep and _SECRET_PARAMETER.search(
                         urllib.parse.unquote(name))
                     else part)
    return "".join(parts)


def _is_loopback(host: str | None) -> bool:
    """`localhost`, `127.0.0.0/8` or `::1` — a host with no network to attack.

    Judged by `ipaddress` where the host is a literal, so `127.0.0.1`,
    `127.5.5.5` and `[::1]` are all one answer and a name that merely LOOKS
    like one (`127.0.0.1.evil.test`) is not.
    """
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _broker_url(env: Mapping[str, str], setting: Setting, *,
                required: bool) -> str | None:
    """A broker endpoint, REFUSED when it carries URL userinfo.

    `oidc_issuer` and an explicit `oidc_jwks_url` are PUBLIC endpoints: the
    issuer is a value tokens are compared against and the key set is fetched
    unauthenticated. `load_settings` accepted any string, so
    `https://svc:pw@broker/realms/x` was a legal configuration — and then
    `repr(settings)` printed it, `opendox-runtime runtime status` printed the
    derived JWKS URL and the discovery URL built from it, and this module's
    promise that a credential never reaches a log was false for a value that
    had never been a DSN (Copilot review of openDox-code#25, round 22, in both
    places).

    IN THE QUERY AS WELL AS IN THE AUTHORITY, since round 24:
    `https://broker/certs?token=…` carries a credential just as surely and the
    first cut looked only at `netloc`. And the parse itself is inside this
    module's boundary — `urlsplit` raises `ValueError` for an unmatched IPv6
    bracket, which is a malformed VARIABLE and owes a `ConfigurationError`
    naming it rather than a traceback.

    REFUSED RATHER THAN REDACTED, and that is the choice: redaction would make
    the evidence safe and leave the configuration wrong — a broker that needs
    userinfo to serve its key set is not a broker this runtime can use, because
    `jwks_url()` is also what the verifier fetches and what an operator is told
    to check. The two `repr`/evidence paths redact it as well, because a
    settings object built by hand in a test or a future caller does not go
    through here.
    """
    value = _require(env, setting) if required else _optional(env, setting)
    if not value:
        return value
    split = _split_url(setting.name, value)
    carried = ("userinfo" if "@" in split.netloc else
               "a credential-shaped query parameter"
               if any(_SECRET_PARAMETER.search(
                   urllib.parse.unquote(part.partition("=")[0]))
                   for part in re.split(r"[&;]", split.query + "&"
                                        + split.fragment) if "=" in part)
               else None)
    # AND THE SCHEME IS THE TRUST ANCHOR'S OWN. `HttpJwksSource` FETCHES this
    # URL and the keys it returns are what every token is verified against, so
    # over `http://` a network attacker replaces the key set and mints tokens
    # whose `iss` and `aud` still pass — the whole verification reduced to
    # whoever controls the path (Copilot review of openDox-code#25, round 25).
    # `https` or a LOOPBACK host, and only those: a developer running a broker
    # on `127.0.0.1` has no network for anyone to be on, and every other
    # `http://` is refused rather than warned about.
    # AND IT MUST NAME A HOST AT ALL, which the scheme check below does not
    # ask: `urlsplit("https:///realms/x")` gives scheme `https` and hostname
    # `None`, so a URL nothing can be fetched from passed as a trust anchor and
    # the install found out when `/readyz` failed on the key-set fetch —
    # configuration discovered at serve time, which is the boundary this
    # function exists to hold (Copilot review of openDox-code#25, round 26,
    # suppressed). THE VALUE IS NOT ECHOED: `https://user:pw@/realms/x` also
    # has no hostname, and its netloc carries the password.
    if not split.hostname:
        raise ConfigurationError(
            f"{setting.name} is a {split.scheme or '(no scheme)'} URL that "
            "names no HOST, so no key set can be fetched from it and no "
            "issuer can be compared against a token's `iss`. Set it to the "
            "broker's full URL, e.g. "
            "https://broker.example/realms/opendox (the value is not repeated "
            "here: a URL with no host can still carry userinfo)")
    # AND THE PORT IS PARSED HERE, not at the first fetch. `urlsplit` SUCCEEDS
    # for `https://broker:not-a-port/realms/x` and defers the error to `.port`,
    # a property that parses on read — so an unusable broker URL passed this
    # boundary and raised `ValueError` inside `httpx` when the key set was
    # fetched, which is neither a `ConfigurationError` nor a named setting
    # (Copilot review of openDox-code#25, round 27). The value is not echoed,
    # for the reason above.
    try:
        split.port
    except ValueError:
        raise ConfigurationError(
            f"{setting.name} names a PORT that is not a number in 0-65535, so "
            "no key set can be fetched from it. Set it to the broker's full "
            "URL (the value is not repeated here: a URL this runtime cannot "
            "parse can still carry userinfo)") from None
    if split.scheme != "https" and not _is_loopback(split.hostname):
        raise ConfigurationError(
            f"{setting.name} is {split.scheme or '(no scheme)'}://, and this "
            "is a TRUST ANCHOR: the key set fetched from it is what every "
            "token is verified against, so anyone on the path between this "
            "runtime and that host could replace it. Use https, or a loopback "
            "host for local development")
    if carried:
        raise ConfigurationError(
            f"{setting.name} carries a credential in its URL ({carried}). It "
            "is a PUBLIC endpoint — the issuer is compared against a token's "
            "`iss` and the key set is fetched unauthenticated — and a "
            "credential there would be printed by `status` and by any log line "
            "holding the settings. Set it without one")
    return value


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
        oidc_issuer=_broker_url(env, _by_name(PREFIX + "OIDC_ISSUER"),
                                required=True) or "",
        oidc_audience=_require(env, _by_name(PREFIX + "OIDC_AUDIENCE")),
        oidc_jwks_url=_broker_url(env, _by_name(PREFIX + "OIDC_JWKS_URL"),
                                  required=False),
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
