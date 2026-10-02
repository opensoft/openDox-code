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
docstring — and `opendox.runtime.config` has to import without the
`runtime` extra installed. A settings
object built out of the standard library costs nothing to import and is the
only reason `opendox runtime status` can tell a reader that FastAPI is missing
instead of failing to start with the same ImportError it was about to explain.
"""

from __future__ import annotations

import importlib.metadata
import ipaddress
import os
import re
import shlex
import sys
import tomllib
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

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
    # THE INSTALL SHAPE, READ BESIDE THE ISSUER IT DECIDES ABOUT (plan 034
    # T070; #1144 13.4, 13.5). Not `required`: its default is the SAFE value,
    # and "unset" is the case 13.4 names as the one that must be safe.
    Setting(
        PREFIX + "INSTALL_MODE", "hosted", False, False,
        "the install shape: `hosted` (the default — the broker, the pinned "
        "issuer and an operator's database, exactly as before) or `local` "
        "(one user, no broker, loopback only). `generate-and-open --local` "
        "makes the same selection; the two may not disagree, and with "
        "neither the install is hosted, so a hosted install with no issuer "
        "refuses rather than falling into local mode (13.4, 13.5)",
    ),
    # WHERE A LOCAL INSTALL KEEPS ITS OWN STATE (plan 034 T072; #1144 13.1):
    # the bundled PostgreSQL server's data directory and its Unix socket. No
    # default string, because the default is COMPUTED, per user — see
    # `state_dir`. A hosted install never reads it.
    Setting(
        PREFIX + "STATE_DIR", None, False, False,
        "the directory a LOCAL install owns: the bundled PostgreSQL server's "
        "data directory and its Unix socket live under it, and the server "
        "listens on that socket and on no TCP port (13.1). Unset, it is "
        "`$XDG_STATE_HOME/opendox`, else `~/.local/state/opendox`. A hosted "
        "install never reads it",
    ),
    Setting(
        PREFIX + "OIDC_ISSUER", None, True, False,
        "the Keycloak broker's issuer, pinned: a token from any other issuer "
        "is refused rather than trusted (RULING Q2). Required by a HOSTED "
        "install; a LOCAL install has no broker and refuses one given here",
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
        PREFIX + "SERVED_SCHEMA", "", False, False,
        "the NAME (never a credential) of the schema the SERVED application "
        "reads, declared to the migration run so it can refuse to apply DDL "
        "anywhere else; the two DSNs are configured in different workloads and "
        "no process holds both, so this is how a migration container learns "
        "what the API will read",
    ),
    Setting(
        PREFIX + "SERVED_DATABASE", "", False, False,
        "the NAME (never a credential) of the DATABASE the SERVED application "
        "reads, declared to the migration run so it can refuse to apply DDL — "
        "or to DROP the coordination tables — anywhere else; the schema "
        "declaration above answers the same question one level down, and this "
        "is the wider of the two, because a DSN may omit `dbname` entirely and "
        "libpq then defaults it to the connection USER",
    ),
    Setting(
        PREFIX + "PUBLISH_OPENAPI", "false", False, False,
        "whether to serve the interactive schema at /docs, /redoc and "
        "/openapi.json; OFF by default, because FastAPI's defaults would "
        "otherwise publish the whole API surface to an unauthenticated caller",
    ),
    Setting(
        PREFIX + "MIGRATIONS_DIR", "migrations", False, False,
        "the ordered-SQL directory, repository-root-relative. Unset, a HOSTED "
        "install uses `migrations` where the working directory holds one (a "
        "checkout, or the image's /app), as it always has, and otherwise the "
        "copy this installation carries; a LOCAL install uses ONLY the copy "
        "this installation carries and never the working directory's (plan "
        "034 T072), so launching it from a checkout of somebody else's "
        "repository cannot run that repository's SQL",
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

    `migration_database_url` is `None` from `load_settings` whenever
    `OPENDOX_MIGRATION_DATABASE_URL` is unset — RULED "required only for
    migrate" (openxFactory#656, on the claim thread for plan 034's T071,
    2026-09-28): the served workload never needs it, `deploy/compose/
    docker-compose.yaml`'s `opendox` service and `docs/runtime.md` § 3 never
    supply it, and `load_migration_settings` is the loader that actually
    requires one (unaffected by this: it already refused to load without one).

    `install_mode` is `INSTALL_MODE_HOSTED` or `INSTALL_MODE_LOCAL` (plan 034
    T070; #1144 13.4), whichever loader built the object.

    THE BROKER FIELDS DEPEND ON THE LOADER, and what follows holds for
    `load_settings` only (Copilot review of openDox-code#67):
      * From `load_settings`, a LOCAL install has no broker. Its
        `oidc_issuer` and `oidc_audience` are EMPTY and its `oidc_jwks_url`
        is `None`, never a placeholder that looks like an endpoint, and
        `jwks_url()` and `discovery_url()` answer the empty string rather
        than a path glued onto nothing. A HOSTED one always carries a real
        issuer, because `load_settings` refuses one without it.
      * From `load_migration_settings`, in EITHER shape, the issuer and
        audience are `MIGRATION_SENTINEL_ISSUER` and
        `MIGRATION_SENTINEL_AUDIENCE`. A migration run reaches no broker at
        all, and anything that tried to with those values would fail naming
        them. So neither statement above applies to it. `install_mode` there
        records the shape the run belongs to, and nothing else.
    """

    database_url: str
    migration_database_url: str | None
    install_mode: str
    state_dir: Path
    oidc_issuer: str
    oidc_audience: str
    oidc_jwks_url: str | None
    oidc_algorithms: tuple[str, ...]
    oidc_jwks_ttl_seconds: int
    oidc_leeway_seconds: int
    bind_host: str
    bind_port: int
    runtime_pg_role: str | None
    served_schema: str | None
    served_database: str | None
    publish_openapi: bool
    migrations_dir: Path
    project_repository_root: Path

    def __repr__(self) -> str:
        """Redacted, because a settings object reaches a log line eventually."""
        return (
            "RuntimeSettings(database_url=<redacted>, "
            "migration_database_url="
            f"{'<redacted>' if self.migration_database_url else 'None'}, "
            f"install_mode={self.install_mode!r}, "
            f"state_dir={str(self.state_dir)!r}, "
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
            f"served_schema={self.served_schema!r}, "
            f"served_database={self.served_database!r}, "
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

        EMPTY FOR A LOCAL INSTALL, which has no issuer to derive one from
        (plan 034 T070): the derivation would otherwise answer the bare path
        `/protocol/openid-connect/certs`, which `status` would print as if it
        were a configured endpoint.
        """
        if self.oidc_jwks_url:
            return self.oidc_jwks_url
        if not self.oidc_issuer:
            return ""
        return self.oidc_issuer.rstrip("/") + "/protocol/openid-connect/certs"

    def discovery_url(self) -> str:
        """The issuer's discovery document, for `opendox runtime status`.

        Empty for a local install, for the reason `jwks_url` gives.
        """
        if not self.oidc_issuer:
            return ""
        return self.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"


#: PARAMETER NAMES WHOSE VALUE IS A CREDENTIAL. A broker URL can carry one in
#: its QUERY as easily as in its userinfo — `https://broker/certs?token=…` — and
#: the userinfo guard looked only at the authority, so that form was accepted
#: and then printed by `repr(settings)` and by `status` (Copilot review of
#: openDox-code#25, round 24).
#:
#: THE ONE DECLARATION, SINCE § 3.6 LANDED BESIDE THIS MODULE.
#: `local_git_adapter` used to hold its own list for the REMOTE rule, and the
#: two drifted: this one lacked `pass`, so a legacy row spelled
#: `https://host/r.git?pass=hunter2` was returned verbatim by
#: `GET /api/v1/project-repositories` while the adapter's redactor hid it
#: (Copilot review of openDox-code#26, at `555a03c8`). That module now builds
#: its pattern FROM this tuple, so there is one list and two readings of it —
#: see `names_a_secret_parameter` for the difference, which is deliberate and
#: is only ever in the direction of the adapter hiding MORE.
#: THE LONGEST REMOTE THIS RUNTIME ACCEPTS, OR PRINTS IN PART. One declaration
#: and two readings, and it lives here because `config` is the module both of
#: them import. NOT a style rule: the credential predicate decodes each
#: parameter name to a fixed point, which is quadratic in that name's length,
#: and `remote_url` is caller-controlled — so a nested `%2525…` chain of
#: unbounded length is work an attacker chooses for this process (Copilot
#: review of openDox-code#26, round 10, suppressed). Two kilobytes is the
#: conventional URL ceiling and is far above any real remote.
#:
#: THE SECOND READING WAS ADDED BECAUSE THE FIRST STOPPED BEING ENOUGH.
#: `repository_act.refuse_credential_bearing_remote` refuses a NEW remote
#: longer than this, which bounded the decoder as long as everything reaching
#: it had passed that refusal. Pointing `redacted_remote_url` at the adapter's
#: redactor put a STORED value on that path for the first time, and a legacy
#: row — a restore, an older build, `psql` — never passed any refusal, so
#: every map read of it did the quadratic work (Copilot review of
#: openDox-code#26, at `4156f233`, suppressed). `local_git_adapter.redact_
#: remote_url` therefore replaces a longer STORED value whole, which is what
#: a value that cannot be read as one URL already gets.
MAX_REMOTE_URL_CHARS = 2048

SECRET_PARAMETER_KEYS = (
    "token", "access_token", "api_key", "apikey", "key", "secret",
    "pass", "password", "passwd", "pwd", "auth", "authorization",
    "credential", "credentials", "sig", "signature", "session",
)
#: The same list as a SET, because the question is "is this name one of
#: these", not "does this name contain one of these". The first cut compiled
#: the tuple into an alternation and asked `.search()`, so any name with one of
#: them as a SUBSTRING matched: `monkey` contains `key`, `sigma` contains
#: `sig`, `tokenizer` contains `token` and `authority` contains `auth` — and a
#: broker URL or a git remote carrying `?monkey=1` was refused as
#: credential-bearing, which is a false refusal at the configuration boundary
#: (Copilot review of openDox-code#25, at `056d1597`).
_SECRET_PARAMETER_WORDS = frozenset(SECRET_PARAMETER_KEYS)

#: `access_token`, `X-Api-Key` and `sessionToken` must still match, so the name
#: is split into WORDS first — on every non-alphanumeric run and at each
#: camelCase boundary — and each word is compared whole.
_WORD_SEPARATOR = re.compile(r"[^A-Za-z0-9]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


#: THE COMPOUND NAMES A WORD SPLIT CANNOT SEE, DECLARED ONE BY ONE. Whole-word
#: matching alone answered `sslpassword` — libpq's own keyword, and a query
#: parameter name a caller can write — as innocent, because it is one word and
#: is not the word `password` (Copilot review of openDox-code#26, at
#: `555a03c8`). The first repair called every needle of six characters or more
#: a SUBSTRING, which bought `sslpassword` at the price of every other compound
#: of those words: `passwordless` and `secretary` were refused as
#: credential-bearing, measured (same review, at `db5197d0`, suppressed) — a
#: false refusal at a CONFIGURATION boundary, which is the defect the
#: whole-word rule above was written for in the first place.
#:
#: SO THE COMPOUNDS ARE NAMED, not derived. There is exactly one this runtime
#: meets: libpq's `sslpassword`. A name reaches this list because somebody
#: established that a real protocol spells a secret that way, which is a
#: decision with an owner — where "every long word, anywhere inside any name"
#: is a rule that grows false refusals nobody chose.
SECRET_PARAMETER_COMPOUNDS = ("sslpassword",)
_SECRET_COMPOUND_WORDS = frozenset(SECRET_PARAMETER_COMPOUNDS)


def names_a_secret_parameter(name: str) -> bool:
    """True when a URL parameter's NAME is one of the credential names.

    WHOLE WORDS, for the reason `_SECRET_PARAMETER_WORDS` gives above, plus the
    declared compounds `_SECRET_COMPOUND_WORDS` names. The decoded name is what
    is judged, because `%74oken` is `token`.

    A WORD, NOT A SUBSTRING, AND THE DIFFERENCE IS MEASURED: `passwordless` and
    `secretary` were refused by the substring rule this replaces, and are
    accepted now; `sslpassword` is refused because it is DECLARED, not because
    it contains eight of the letters of `password`. `credentials_version` is
    still refused, and deliberately — `credentials` is one of its words, and
    the same reading is what catches `access_token`, `X-Api-Key` and
    `sessionToken`. Narrowing further would mean comparing the whole NAME,
    which those three would walk straight through.

    THIS IS THE NARROWER OF THE TWO READINGS of one declared list.
    `local_git_adapter` asks the same tuple as a plain alternation, so it
    matches every name this does and more — `monkey` among them. That
    difference is deliberate: the adapter redacts git's stderr and a push
    refusal, where over-redacting costs a word of diagnostic; this answers a
    CONFIGURATION boundary, where over-refusing costs an install that will not
    start for a reason that is not true. What must never happen is the other
    direction — something this calls a secret that the adapter does not — and
    `test_the_two_readings_of_the_one_list_never_disagree_about_hiding` holds
    it over a corpus.
    """
    spaced = _CAMEL_BOUNDARY.sub(" ", name).lower()
    words = [word for word in _WORD_SEPARATOR.split(spaced) if word]
    return any(word in _SECRET_PARAMETER_WORDS
               or word in _SECRET_COMPOUND_WORDS for word in words)


def _split_url(name: str, value: str) -> urllib.parse.SplitResult:
    """`urlsplit`, with its `ValueError` inside this module's own boundary.

    MEASURED on python 3.12: `urlsplit("https://[::1/x")` raises
    `ValueError("Invalid IPv6 URL")`. This call sits in `load_settings`, whose
    whole contract is that a bad variable produces a `ConfigurationError`
    NAMING it — so a malformed broker URL escaped as a raw `ValueError` and the
    CLI printed a traceback where it promises a refusal (Copilot review of
    openDox-code#25, round 24).

    AND THE DRIVER'S MESSAGE IS NOT REPEATED, WHICH IS THE WHOLE OF THE SECOND
    DEFECT. Round 24 interpolated `{exc}`, and CPython's `_checknetloc` raises

        ValueError("netloc '" + netloc + "' contains invalid characters under "
                   "NFKC normalization")

    — THE WHOLE NETLOC, USERINFO AND PASSWORD INCLUDED. A hostname that is not
    ASCII is the ordinary case for an IDN broker, and `_split_url` runs BEFORE
    the userinfo refusal, so the guard written to keep a password out of this
    message never got to run: `OPENDOX_OIDC_ISSUER=https://svc:hunter2@brokerâ„€evil.example/realms/x`
    printed `hunter2` on stdout from `runtime status` and `runtime init`, in
    the JSON the lifecycle contract calls redacted evidence. `cli._safe_message`
    does not save it either — the leaked run is `netloc 'svc:hunter2@…'`, which
    has no `://` and no `password=`, so `_DSN_SHAPED` passes it through
    untouched (independent adversarial review of openDox-code#25, A25-1).

    The useful half of the driver's answer is that the value is unparseable and
    which exception said so; the value is what every other refusal in
    `_broker_url` already declines to repeat. `from None` for the same reason
    as the port refusal below: `__cause__` carries the same text, and a
    traceback printed by anything at all would carry it with the exception.
    """
    try:
        return urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} is not a URL this runtime can parse "
            f"({type(exc).__name__}); set it to the broker endpoint, without "
            "userinfo — the value is not repeated here, because a URL this "
            "runtime cannot parse can still carry one") from None


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
                     if sep and names_a_secret_parameter(
                         urllib.parse.unquote(name))
                     else part)
    return "".join(parts)


#: A LIBPQ KEYWORD/VALUE PASSWORD, in the forms libpq itself accepts. A git
#: remote is an arbitrary string, and a value such as `host=db password=hunter2`
#: is neither a URL with userinfo nor a query parameter — so every pattern
#: above looked straight through it, and `_repository_json` returned it
#: VERBATIM to every member of the project (Copilot review of openDox-code#26,
#: at `555a03c8`, on the boundary this branch's own merge had just moved).
#:
#: THE ONE DEFINITION: `local_git_adapter._LIBPQ_PASSWORD` is this object, and
#: this module is where it lives because it is the one the other can import —
#: the adapter reaches for `config`, never the reverse. libpq documents that a
#: value containing spaces is single-quoted with `\'` and `\\` escaped inside;
#: the closing quote is OPTIONAL here and neither quoted form crosses a
#: newline, because a truncated value must redact MORE rather than less and
#: must not swallow the next line of a diagnostic. `sslpassword` is named
#: because `\b` before `password` does not reach it.
LIBPQ_PASSWORD = re.compile(
    r"(?i)\b(?:ssl)?password\s*=\s*"
    r"""(?:'(?:[^'\\\n]|\\.)*'?|"(?:[^"\\\n]|\\.)*"?|\S+)""")


def credential_in_a_remote_url(value: str | None) -> str | None:
    """WHAT secret a git remote URL carries, named — or None. Never the value.

    `project_repositories.remote_url` is free text by design
    (`migrations/0001_identity_and_coordination.sql`: "`remote_url` is nullable
    because RULING C3 says so in terms"), and nothing between a caller and that
    column judged it, so `https://user:hunter2@github.com/o/r.git` was a legal
    row — stored in the clear, returned verbatim by `GET
    /api/v1/project-repositories` to every member of the project, and carried
    into `git remote add` by § 3.6 (Copilot review of openDox-code#25, on the
    migration's line for that column).

    A REMOTE URL IS NOT A BROKER URL, so `_broker_url`'s test is not reusable
    as written: `ssh://git@github.com/o/r.git` and `git@github.com:o/r.git` are
    the ORDINARY forms of an ssh remote and their userinfo is a USERNAME, which
    is not a secret — while `redacted_url` replaces any userinfo at all,
    because a broker URL has no business carrying even that. What is a secret
    is a PASSWORD in the authority, in EITHER of the two shapes git accepts,
    or a credential-shaped query parameter.

    THE TWO SHAPES, measured rather than assumed (`urllib.parse.urlsplit`,
    CPython 3.12): the URL form puts the authority in `netloc`
    (`https://user:pw@host/p` → `'user:pw@host'`), and the scp-like form
    `[user[:password]@]host:path` has NO netloc at all — `urlsplit` reads
    `git@github.com:o/r.git` as a bare path and `user:pw@host:p` as the scheme
    `user` plus a path, so the authority has to be read off the text before the
    first `/` in both. Refusing is the answer for a value this module cannot
    parse, on `_split_url`'s reasoning: one that cannot be parsed can still
    carry a credential.
    """
    if not value:
        return None
    try:
        split = urllib.parse.urlsplit(value)
    except ValueError:
        return "a value this runtime cannot parse"
    if split.netloc:
        if split.netloc.rpartition("@")[0].partition(":")[2]:
            return "a password in the URL's authority"
    elif _scp_like_userinfo(value) is not None:
        return "a password in the URL's authority"
    elif _an_authority_this_runtime_cannot_read(value):
        # THE SHAPE BOTH CLASSES EXCLUDED. `_scp_like_userinfo` declines a head
        # holding whitespace so this rule cannot start judging prose, and the
        # redactor's `_CREDENTIAL_SHAPED` excludes it so an unrelated
        # `user@host` further down git's stderr is not joined to a URL above it
        # — and between the two sat `user:pa ss@host:path`, which this returned
        # `None` for while the URL form of the same value was refused (Copilot
        # review of openDox-code#26, at `db5197d0`; the redaction half was
        # closed there and this, the STORE's own guard, was registered). No
        # writer reachable from the API or the CLI could make such a row —
        # `repository_act.refuse_credential_bearing_remote` refuses the shape
        # at every one — so what this closes is the raw-SQL and restore path,
        # and it closes it by NAME rather than by guessing at the value.
        return "an authority this runtime cannot read as one word"
    # AND THE KEYWORD/VALUE FORM, which is neither an authority nor a query.
    if LIBPQ_PASSWORD.search(value):
        return "a libpq keyword/value password"
    if _a_secret_parameter_in(split.query + "&" + split.fragment):
        return "a credential-shaped query parameter"
    return None


def redacted_remote_url(value: str | None) -> str | None:
    """A stored git remote with its secret replaced — ONE redactor, called here.

    THIS USED TO BE A SECOND IMPLEMENTATION and the two disagreed three times
    in one review: `config` decoded a parameter name ONCE, so
    `?%2574oken=hunter2` was returned verbatim while the adapter's fixed-point
    decoder read it as `token`; `config` refused to judge any value holding
    whitespace, so a legacy `user:sec\nret@host:path` came back whole; and `;`
    was a parameter delimiter to `config` and NOT to the adapter — the other
    direction, and the expensive one. `local_git_adapter.carries_a_credential`
    is the adapter's redactor asked as a predicate, so it answered False for
    `…?mode=1;token=…`, `repository_act.attach_remote` accepted the value, and
    `identity.CoordinationStore` then refused it with a `RefusedError` the
    route does not catch, because it catches `RepositoryActRefused`: a 500
    where a 409 belonged (all three MEASURED at `fe421882`; Copilot review of
    openDox-code#26, at `555a03c8` and `fe421882`). A property test said the
    two never disagreed and passed, because its corpus had none of the three.

    SO THERE IS ONE REDACTOR NOW AND THIS IS A CALL INTO IT. The agreement is
    true by construction rather than by assertion, and the case that stated the
    property stays as a regression guard over the alias. The nuance the API
    boundary needs — that an ordinary `ssh://git@host/…` keeps its USERNAME,
    which is not a secret — moved into `redact_remote_url` as an argument, so
    it is one implementation with one flag and not two implementations with one
    agreement.

    THE IMPORT IS INSIDE THE FUNCTION because the dependency runs the other
    way: `local_git_adapter` imports this module for the declared key list and
    the libpq pattern. Both are stdlib-only, so nothing here changes the
    package's import weight — see `src/opendox/runtime/__init__.py`.
    """
    if not value:
        return value
    from opendox.runtime.local_git_adapter import redact_remote_url

    return redact_remote_url(value)


def _an_authority_this_runtime_cannot_read(value: str) -> bool:
    """`user:pa ss@host:path` — an authority-shaped head holding whitespace.

    THE HEAD IS TAKEN AT THE LAST `@`, for the reason `_scp_like_userinfo`
    takes it there: a password may contain `@`, and stopping at the first one
    reads the remainder as a host. A head without `:` is a bare username, which
    is not a secret in any form, and a value without `@` has no authority at
    all — so neither is refused, and a local path with a space in it
    (`/srv/my repos/x.git`, and even `/srv/a@b/my repos/x.git`) is untouched.

    REFUSING IS THE ANSWER FOR A VALUE THIS MODULE CANNOT PARSE — `_split_url`'s
    reasoning, and the same sentence `credential_in_a_remote_url` already
    applies to a `urlsplit` that raises. `local_git_adapter.redact_remote_url`
    made the same judgement for the same shape at the printing end.
    """
    head = value.rpartition("@")[0]
    if not head or ":" not in head or not any(c.isspace() for c in head):
        return False
    # A LOCAL PATH IS NOT AN AUTHORITY, and the first cut could not tell them
    # apart. `/srv/my repos/a:b@c.git` is a directory whose name holds a colon
    # and an at-sign — a legal remote for `git push` — and it was read as
    # userinfo and refused, which reached `CoordinationStore` and raised where
    # the act had accepted: a 500 (Copilot review of openDox-code#30).
    #
    # GIT'S OWN RULE IS THE TEST, and it is a rule about the FIRST colon: the
    # `[user@]host:path` form is recognised only when nothing before that colon
    # is a `/`. It separates the two cases exactly, which is why it is this rule
    # and not "a head holding any slash":
    #
    #   `ci:hun/ter2@github.com:o/r.git`  before the first `:` is `ci`      -> an
    #                                     authority, and the password holding a
    #                                     `/` is the #25 hole that stays closed
    #   `/srv/my repos/a:b@c.git`         before the first `:` is a PATH     -> a
    #                                     local path, not judged here
    return "/" not in head.partition(":")[0]


def _scp_like_userinfo(value: str) -> tuple[str, str, str] | None:
    """`(user, password, the rest)` for `[user[:password]@]host:path`, else None.

    THE LAST `@` IN THE WHOLE VALUE, and not the last `@` before the first `/`.
    The first cut truncated at the first `/` — the shape of an scp-like
    authority — and a PASSWORD CONTAINING `/` then fell outside the window:
    `ci:pa/ss@github.com:o/r.git` was reduced to `ci:pa`, read as a username
    with no password, called clean, stored in the clear and returned to every
    member of the project by `GET /api/v1/project-repositories` (Copilot review
    of openDox-code#25, at `0968ff8b` — the same class as round 29's on the
    sibling PR, where a bound that excluded `/` was defeated by a password
    holding one).

    OVER-DETECTING IS THE SAFE DIRECTION HERE and the trade is stated: a local
    path that really does contain `:`…`@` before its last component — a shape
    no git remote has — is refused with its own name. What is NOT widened is
    whitespace: a value carrying a space is not one authority, and a candidate
    holding one is left alone so this cannot start eating prose.
    """
    head, at, rest = value.rpartition("@")
    if not at or any(character.isspace() for character in head):
        return None
    user, colon, password = head.partition(":")
    if not colon or not password:
        return None
    return user, password, rest


def _a_secret_parameter_in(text: str) -> bool:
    """True when any `name=value` in `text` has a credential-shaped NAME.

    ONE DEFINITION, because two were the reason A25-1 survived: `_broker_url`
    spelled this inline and the remote-URL judgement needed the same question
    asked the same way.
    """
    return any(names_a_secret_parameter(
        urllib.parse.unquote(part.partition("=")[0]))
        for part in re.split(r"[&;]", text) if "=" in part)


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
                required: bool, is_a_base_url: bool = False) -> str | None:
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
               if _a_secret_parameter_in(split.query + "&" + split.fragment)
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
    # `https`, OR `http` ON A LOOPBACK HOST — and those two only. The
    # exception used to be written as "not https AND not loopback", which
    # accepted EVERY other scheme on a loopback host: `ftp://localhost/realms/x`
    # and `file://127.0.0.1/realms/x` both passed configuration, and
    # `HttpJwksSource` fetches with `httpx.get`, which cannot use either — so
    # the process started with an unusable trust anchor and failed at readiness
    # (Copilot review of openDox-code#25, round 29, suppressed). The exception
    # exists for a developer running a broker over plain HTTP on the loopback,
    # and that is the whole of what it now allows.
    if split.scheme != "https" and not (
            split.scheme == "http" and _is_loopback(split.hostname)):
        raise ConfigurationError(
            f"{setting.name} is {split.scheme or '(no scheme)'}://, and this "
            "is a TRUST ANCHOR: the key set fetched from it is what every "
            "token is verified against, so anyone on the path between this "
            "runtime and that host could replace it. Use https, or a loopback "
            "host for local development")
    # AND A BASE URL IS A BASE URL: `jwks_url()` and `discovery_url()` APPEND
    # their paths to the issuer, and a URL's query and fragment come after its
    # path — so `https://broker/realms/x?tenant=a` derived
    # `https://broker/realms/x?tenant=a/protocol/openid-connect/certs`, which
    # is a key-set URL nothing serves, and the verifier found out at the fetch
    # (Copilot review of openDox-code#25, round 29). Measured, both components.
    # The rule is the ISSUER's alone: an explicit `OPENDOX_OIDC_JWKS_URL` is
    # fetched as given and a broker behind a rewriting proxy may well need a
    # query on it.
    if is_a_base_url and (split.query or split.fragment):
        component = "query" if split.query else "fragment"
        raise ConfigurationError(
            f"{setting.name} carries a {component} component, and it is a BASE "
            "URL: the key-set and discovery URLs are derived by appending a "
            "path to it, which would land after that component and address "
            "nothing. Set the issuer alone, and set "
            f"{PREFIX}OIDC_JWKS_URL explicitly if the key set is somewhere a "
            "derived path does not reach (the value is not repeated here: a "
            "query can carry a credential)")
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


#: The largest value each integer setting may be given, where being unbounded
#: would make the setting meaningless rather than merely large.
#:
#: `OIDC_LEEWAY_SECONDS` IS THE ONE THAT MATTERS: PyJWT applies it as slack on
#: `exp`, so `999999999` is a legal configuration under which a token never
#: expires — a security property turned off by a number, with nothing saying
#: so (independent adversarial review of openDox-code#25, A25-5). Five minutes
#: is generous for clock skew between a broker and this runtime; an install
#: that needs more has a clock problem, not a configuration one. The other two
#: are bounded because a cache TTL of a decade and a port above 65535 are the
#: same kind of nonsense, and because a helper that bounds only the setting
#: somebody remembered is the shape this review was about.
MAXIMUM_BY_SETTING: dict[str, int] = {
    PREFIX + "OIDC_LEEWAY_SECONDS": 300,
    PREFIX + "OIDC_JWKS_TTL_SECONDS": 86_400,
    PREFIX + "BIND_PORT": 65_535,
}


def _positive_int(env: Mapping[str, str], setting: Setting) -> int:
    raw = env.get(setting.name, "").strip() or (setting.default or "")
    # `int()` TAKES PYTHON'S UNDERSCORE SEPARATORS, and an environment variable
    # is not Python source: `int("3_0_0")` is 300, so `3_0_0` was silently a
    # different number from the one an operator read in the manifest
    # (independent adversarial review of openDox-code#25, A25-5). Digits only,
    # decided before `int()` sees the string.
    if not raw.isdigit():
        raise ConfigurationError(
            f"{setting.name} must be a whole number written in digits, not "
            f"{raw!r}: {setting.purpose}")
    value = int(raw)
    if value <= 0:
        raise ConfigurationError(
            f"{setting.name} must be greater than zero, not {value}: "
            f"{setting.purpose}"
        )
    ceiling = MAXIMUM_BY_SETTING.get(setting.name)
    if ceiling is not None and value > ceiling:
        raise ConfigurationError(
            f"{setting.name} must be at most {ceiling}, not {value}: "
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


def _served_schema(env: Mapping[str, str]) -> str | None:
    """`OPENDOX_SERVED_SCHEMA`, or `None`.

    A schema NAME and never a credential, which is what makes it safe to give
    a migration container: the guard this feeds needs to know WHERE the API
    will read, and the served DSN — which carries a password — is deliberately
    not in that container at all.

    No shape rule beyond "not empty": unlike a role name this is never
    interpolated into SQL, only COMPARED with what `selected_schema` reads
    back from the connection.
    """
    return env.get(PREFIX + "SERVED_SCHEMA", "").strip() or None


def _served_database(env: Mapping[str, str]) -> str | None:
    """`OPENDOX_SERVED_DATABASE`, or `None`.

    A DATABASE NAME AND NEVER A CREDENTIAL — the same property that lets a
    migration container be told `OPENDOX_SERVED_SCHEMA`, one level up. A25-3
    established the shape and this closes the half it left: the guard it built
    compares the two DSNs, and NO SHIPPED WORKLOAD HOLDS BOTH, so the served
    SCHEMA was declared to the migration Job while the served DATABASE was not
    declared at all. A migration DSN pointed at the wrong database therefore
    applied DDL — and `runtime reset` DROPPED the six coordination tables —
    in a database the API does not read, and nothing in the shipped shape could
    notice (registered on openDox-code#26 from the round at `ebad9d65`, ruled
    item 4, and built here).

    No shape rule beyond "not empty": like the schema, it is never interpolated
    into SQL, only COMPARED with what `current_database()` reads back from the
    connection.
    """
    return env.get(PREFIX + "SERVED_DATABASE", "").strip() or None


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


def search_path_entries(path: str) -> list[str]:
    """`search_path`'s entries, split where PostgreSQL's quoting allows it.

    NOT `path.split(",")`. A schema whose NAME contains a comma is legal,
    PostgreSQL quotes it in `current_setting('search_path')`, and splitting the
    text on every comma turned `"tenant,blue", public` into `"tenant` and
    `blue"` — so this guard REFUSED a connection whose `current_schema()` was
    exactly the schema it had asked for, and named `'"tenant'` as the thing
    that did not exist (Copilot review of openDox-code#25, round 26,
    suppressed). MEASURED on postgres 16.15 against a schema created as
    `"tenant,blue"`: `current_schema()` is `tenant,blue`, the path reads
    `"tenant,blue", public`, and the refusal was raised on a valid install.

    Returns the entries RAW — quotes and surrounding space included — because
    `_unquoted` is what knows how to read one, and a quoted name's leading and
    trailing spaces are part of it.
    """
    entries: list[str] = []
    start = index = 0
    quoted = False
    while index < len(path):
        char = path[index]
        if char == '"':
            if quoted and index + 1 < len(path) and path[index + 1] == '"':
                index += 2                      # an escaped quote, still inside
                continue
            quoted = not quoted
        elif char == "," and not quoted:
            entries.append(path[start:index])
            start = index + 1
        index += 1
    entries.append(path[start:])
    return entries


def unquoted_identifier(entry: str) -> str:
    """One `search_path` entry, with PostgreSQL's quoting removed."""
    entry = entry.strip()
    if len(entry) >= 2 and entry.startswith('"') and entry.endswith('"'):
        return entry[1:-1].replace('""', '"')
    return entry


def _libpq_option_words(raw: str) -> list[str]:
    """One `options` value, split the way libpq splits it — not the way a shell does.

    `shlex` WAS WRONG HERE, and wrong in the direction that matters: POSIX
    `shlex` REMOVES double quotes, so `-c search_path="tenant,blue",public`
    became `search_path=tenant,blue,public` and the comma inside a legal schema
    name was indistinguishable from the separator between two entries — which
    is the same defect `migrations._path_entries` exists to prevent, arriving
    one layer earlier (Copilot review of openDox-code#25, round 36).

    libpq's `options` has NO quote processing at all: arguments are separated
    by whitespace, and a backslash escapes the next character. The double
    quotes in a `search_path` value belong to PostgreSQL's identifier syntax,
    which `search_path_entries` reads, and they must survive this step
    untouched.

    The conninfo layer ABOVE this one is different, and `shlex` is still right
    there: libpq's keyword/value form DOES take single quotes, which is how
    `options='-c search_path=x'` carries a space — and POSIX `shlex` leaves
    the inner double quotes alone while removing that outer quoting.
    """
    words: list[str] = []
    current: list[str] = []
    escaped = False
    for character in raw:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character.isspace():
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(character)
    if current:
        words.append("".join(current))
    return words


def schema_selected_by(dsn: str) -> str | None:
    """The schema a DSN's own `options` selects, or `None` where it names one.

    libpq takes `options=-c search_path=x` (and `-csearch_path=x`) in a URI's
    query and in the keyword/value form, and `Database(schema=…)` sets exactly
    that. The FIRST entry is what an unqualified `create table` lands in, which
    is the question `migrations.selected_schema` asks of a live connection;
    this reads the same answer out of the string, before anything connects.
    """
    raw: str | None = None
    try:
        split = urllib.parse.urlsplit(dsn)
    except ValueError:
        return None
    if split.scheme and split.query:
        for key, value in urllib.parse.parse_qsl(split.query,
                                                 keep_blank_values=True):
            if key == "options":
                raw = value
    elif not split.scheme:
        # `shlex`, NOT `str.split`: libpq writes a value holding spaces in
        # single quotes — `options='-c search_path=tenant'` — and splitting on
        # whitespace made that two tokens and the setting invisible.
        try:
            tokens = shlex.split(dsn)
        except ValueError:
            return None
        for part in tokens:
            if part.startswith("options="):
                raw = part.split("=", 1)[1]
    if not raw:
        return None
    words = _libpq_option_words(raw)
    setting: str | None = None
    effective: str | None = None
    for index, word in enumerate(words):
        if word == "-c" and index + 1 < len(words):
            setting = words[index + 1]
        elif word.startswith("-c") and len(word) > 2:
            setting = word[2:]
        else:
            continue
        if setting.startswith("search_path="):
            # THE QUOTE-AWARE SPLIT, NOT `.split(",")[0]`. A schema whose name
            # contains a comma is legal and PostgreSQL quotes it, so the simple
            # spelling reduced BOTH `"tenant,blue"` and `"tenant,red"` to
            # `tenant` — and two DSNs selecting genuinely different schemas
            # passed the comparison this function exists to feed (Copilot
            # review of openDox-code#25, round 36). It is the same parser
            # `migrations.selected_schema` reads a live connection with.
            #
            # AND THE LAST ASSIGNMENT WINS, WHICH IS WHY THIS DOES NOT RETURN
            # HERE. `options` may carry the setting more than once and the
            # BACKEND applies them in order, so reporting the first made this
            # function answer something the connection would not do. MEASURED
            # on postgres 16 through libpq itself:
            #
            #   options=-csearch_path=old -csearch_path=new  ->  'new'
            #   options=-c search_path=one -c search_path=two -> 'two'
            #
            # (`show search_path` on a real connection opened with each.) Two
            # DSNs could therefore compare EQUAL on `old` while the served one
            # read `new` — the split this comparison exists to refuse, wearing
            # the agreement it was looking for (Copilot review of
            # openDox-code#25, at `0860270f`).
            entries = search_path_entries(setting.split("=", 1)[1])
            effective = unquoted_identifier(entries[0]) or None
    return effective


def database_named_by(dsn: str) -> str | None:
    """The DATABASE a DSN names, or `None` where it leaves it to the default.

    The schema comparison one function down is only half the invariant: two
    DSNs can select the same schema NAME in two different databases, and then
    migrations apply and verify `public.migration_ledger` in one database
    while `/readyz` and the API read a different one (Copilot review of
    openDox-code#25, round 36).

    NO CREDENTIAL IS READ and none can be returned: the URI branch takes
    `urlsplit().path` and nothing else, and the keyword/value branch takes the
    `dbname=` token. `user`, `password` and the userinfo are never touched.
    """
    try:
        split = urllib.parse.urlsplit(dsn)
    except ValueError:
        return None
    if split.scheme:
        # THE QUERY'S `dbname` OVERRIDES THE PATH'S, and a repeated one takes
        # the LAST. This read the path alone, so
        # `postgresql://host/?dbname=one` and `...?dbname=two` both answered
        # `None` and passed the comparison while naming two different
        # databases (Copilot review of openDox-code#25, at `b9bc3167`).
        # MEASURED through libpq itself (`PQconninfoParse` by way of
        # `psycopg.conninfo.conninfo_to_dict`), which is the parser that
        # actually decides:
        #
        #   postgresql://host/frompath                  -> 'frompath'
        #   postgresql://host/?dbname=fromquery         -> 'fromquery'
        #   postgresql://host/frompath?dbname=fromquery -> 'fromquery'
        #   postgresql://host/?dbname=one&dbname=two    -> 'two'
        #
        # so the precedence is stated rather than assumed: query over path,
        # last over first.
        named: str | None = None
        for key, value in urllib.parse.parse_qsl(split.query,
                                                 keep_blank_values=True):
            if key == "dbname":
                named = value
        if named is not None:
            return named or None
        name = urllib.parse.unquote(split.path).lstrip("/")
        return name or None
    try:
        tokens = shlex.split(dsn)
    except ValueError:
        return None
    # THE LAST ONE WINS IN THE KEYWORD/VALUE FORM TOO, which is libpq's rule
    # for every repeated keyword there.
    named = None
    for token in tokens:
        if token.startswith("dbname="):
            named = token.split("=", 1)[1]
    return named or None


def user_named_by(dsn: str) -> str | None:
    """The CONNECTION USER a DSN names, or `None` where it leaves it to libpq.

    NOT A CREDENTIAL, and the distinction is the whole reason this is allowed
    to exist in a module that refuses to repeat a DSN: the user NAME is in
    every server log line and in `pg_stat_activity`, and `deploy/` commits it
    by name in a ConfigMap. The PASSWORD is the secret, and nothing here
    touches it — `urlsplit().username` and the `user=` keyword only.

    WHY THE COMPARISON NEEDS IT: libpq defaults BOTH the database name and
    PostgreSQL's `"$user"` search-path token to this name, so a DSN that omits
    `dbname` still names a database and a `search_path` of `"$user",public`
    still selects a schema — just not one written in the string.

    MEASURED through libpq itself (`PQconninfoParse` by way of
    `psycopg.conninfo.conninfo_to_dict`), because the precedence is not
    obvious:

      postgresql://my%20user@h/db            -> 'my user'   (percent-decoded)
      postgresql://userinfo@h/db?user=fromquery -> 'fromquery' (query wins)
      postgresql://h/db?user=one&user=two    -> 'two'       (last wins)
      host=h user=one user=two dbname=x      -> 'two'       (last wins)
    """
    try:
        split = urllib.parse.urlsplit(dsn)
    except ValueError:
        return None
    if split.scheme:
        named: str | None = None
        for key, value in urllib.parse.parse_qsl(split.query,
                                                 keep_blank_values=True):
            if key == "user":
                named = value
        if named is not None:
            return named or None
        # `urlsplit` does NOT percent-decode the userinfo and libpq does, so
        # `my%20user` is one name and not a literal `%20` (measured above).
        return (urllib.parse.unquote(split.username)
                if split.username else None)
    try:
        tokens = shlex.split(dsn)
    except ValueError:
        return None
    named = None
    for token in tokens:
        if token.startswith("user="):
            named = token.split("=", 1)[1]
    return named or None


def effective_database(dsn: str) -> str | None:
    """WHICH DATABASE this DSN reaches, including libpq's own default.

    `database_named_by` reports what the STRING says and answers `None` for a
    DSN that names no database — and the comparison below then read two
    `None`s as agreement. They are not: libpq defaults `dbname` to the
    CONNECTION USER, and this deployment's two DSNs carry deliberately
    DIFFERENT users (the privileged migration identity and the least-privileged
    served one), so two DSNs that both omit the database name reach two
    different databases (Copilot review of openDox-code#25, at `0968ff8b`).

    MEASURED on postgres 16 rather than argued: `postgresql://opendox:…@host/`
    — no database in the path, no `dbname` anywhere —  connects, and
    `select current_database()` answers `opendox`, which is the user's name.
    `PQconninfoParse` does not fill the default in, so it is not visible in the
    parse; it is applied at connect.

    `None` means UNRESOLVED and never "the same default": with neither a
    database nor a user in the string, libpq falls back to the OPERATING
    SYSTEM user of the process that connects — and the two DSNs are used by two
    different containers. A comparison that cannot be made is a refusal, which
    is the rule this module already applies to a destination it cannot resolve.
    """
    return database_named_by(dsn) or user_named_by(dsn)


def effective_schema(dsn: str) -> str | None:
    """`schema_selected_by`, with PostgreSQL's `"$user"` token substituted.

    `"$user"` is a TOKEN and not a schema name, and the comparison compared it
    as a literal — so two DSNs for different roles, both selecting
    `"$user",public`, agreed on the string `$user` while PostgreSQL resolved
    them to two different schemas (Copilot review of openDox-code#25, at
    `0968ff8b`).

    MEASURED on postgres 16, and the second measurement is the one that
    settles how to treat it:

      set search_path = "$user", public   (no schema named for the user)
          -> current_schema() = public
      … with a schema LITERALLY NAMED `$user` created
          -> current_schema() = public       (the literal is STILL skipped)
      … with a schema named `opendox` (the session user) created
          -> current_schema() = opendox      (the token IS substituted)

    So PostgreSQL never reads `"$user"` as the name of a schema, even when such
    a schema exists — which is why substituting it here matches the server, and
    why the quoted/unquoted distinction Copilot raised one module over does not
    change the answer. (`set search_path = $user` unquoted is a syntax error;
    the token is always written quoted.)

    `None` from this function keeps `schema_selected_by`'s meaning — the DSN
    names no schema — and the caller separates that from UNRESOLVED, which is
    the token with no user in the string to substitute.
    """
    selected = schema_selected_by(dsn)
    if selected != "$user":
        return selected
    return user_named_by(dsn)


#: THE ONLY DIALECT THIS RUNTIME KEEPS (plan 034, 13.2). `psycopg` is the one
#: driver `runtime` depends on and it speaks PostgreSQL alone, but a DSN is a
#: string and nothing stopped an operator writing `sqlite:///…` into either
#: setting and discovering the mismatch however far the code got before the
#: driver refused it. RULING Q1 keeps this database DOCUMENT-FREE, which is
#: why a second dialect is refused HERE rather than supported: it would double
#: every migration and every schema test forever, for a database that holds no
#: document. `postgres://` is accepted beside `postgresql://` because libpq
#: treats the two as one scheme.
POSTGRESQL_SCHEMES = frozenset({"postgresql", "postgres"})


def _refuse_non_postgresql_dsn(name: str, dsn: str | None) -> None:
    """`name`'s DSN is refused unless it selects a PostgreSQL scheme.

    `None` OR EMPTY IS A NO-OP, not a refusal: `OPENDOX_MIGRATION_DATABASE_URL`
    is optional for `load_settings` (RULED "required only for migrate",
    openxFactory#656, on the claim thread for plan 034's T071, 2026-09-28),
    so an absent migration DSN has no dialect to check — the same shape
    `_refuse_two_dsns_that_select_different_schemas` below already reads as
    "nothing to compare" rather than as a fault.

    A DSN in the keyword/value form (`host=h dbname=d …`) names NO DIALECT AT
    ALL — that syntax is libpq's own conninfo grammar, and no other driver
    reads it — so only the URI form is checked: `urlsplit` reports an EMPTY
    scheme for the keyword/value form (there is no `://` to split on), and an
    empty scheme is read as "says nothing" here, exactly as `schema_selected_by`
    reads a DSN that names no schema as `None` rather than as a refusal.

    `urlsplit` ITSELF RAISES for a DSN it cannot parse — MEASURED,
    `ValueError("Invalid IPv6 URL")` for an unbracketed IPv6 host, which
    `tests_runtime/conftest.py`'s own `postgres_dsn` docstring names as "the
    ordinary way to mis-set this variable". `_split_url` exists for exactly
    this shape in the broker settings (Copilot review of openDox-code#25,
    round 24); this is its DSN-flavoured twin; a bad `OPENDOX_DATABASE_URL`
    is not "set it to the broker endpoint", so it is not reused verbatim.
    """
    if not dsn:
        return
    try:
        scheme = urllib.parse.urlsplit(dsn).scheme
    except ValueError as exc:
        raise ConfigurationError(
            f"{name} is not a DSN this runtime can parse "
            f"({type(exc).__name__}); the value is not repeated here, "
            "because a DSN this runtime cannot parse can still carry a "
            "password") from None
    if scheme and scheme not in POSTGRESQL_SCHEMES:
        raise ConfigurationError(
            f"{name} names the {scheme!r} dialect. PostgreSQL "
            "(`postgresql://` or `postgres://`) is the only dialect this "
            "runtime keeps: a second one would double every migration and "
            "every schema test forever, for a database that holds no "
            "document (RULING Q1)")
    # A POSTGRESQL SCHEME IS A URI ONLY IN LIBPQ'S OWN SPELLING (Copilot
    # review of openDox-code#60, at its merge-from-main round). `urlsplit`
    # reads `postgresql:` with no `//`, and any capitalized `PostgreSQL://`,
    # as the PostgreSQL scheme. libpq does not: it recognizes a URI only by
    # the exact, lower-case `postgresql://` or `postgres://`, and parses
    # anything else as keyword/value, which it then refuses with a message
    # that REPEATS THE WHOLE VALUE (measured, psycopg 3.3.6:
    # `missing "=" after "postgresql:svc:hunter2@db/x" in connection info
    # string`). That is the un-named failure at the driver that 13.2 exists to
    # stop, and it carries the password with it. So it is refused here, named,
    # and the value is not repeated.
    if scheme in POSTGRESQL_SCHEMES and not dsn.startswith(
            tuple(f"{known}://" for known in sorted(POSTGRESQL_SCHEMES))):
        raise ConfigurationError(
            f"{name} reads as the PostgreSQL scheme but is not a URI libpq "
            "reads: libpq recognizes only the exact, lower-case "
            "`postgresql://` or `postgres://` prefix, and would refuse any "
            "other spelling with a message that repeats the whole value. "
            "Write the scheme as one of those two (the value is not "
            "repeated here, because it can carry a password)")


def _refuse_the_same_dsn_in_both_settings(
        served: str, migration: str | None) -> None:
    """One credential pasted into both settings is refused (plan 034, 13.3).

    A NO-OP WHEN MIGRATION IS ABSENT, exactly like
    `_refuse_two_dsns_that_select_different_schemas` below: with nothing to
    compare, there is nothing to have collapsed. `OPENDOX_MIGRATION_DATABASE_
    URL` is optional (RULED "required only for migrate", openxFactory#656, on
    the claim thread for plan 034's T071, 2026-09-28) — but WHEN BOTH ARE
    GIVEN, this refusal still applies, on every path `load_settings` serves,
    not only the falsifier's.

    `OPENDOX_DATABASE_URL` is the least-privileged identity the API serves
    with; `OPENDOX_MIGRATION_DATABASE_URL` is the privileged one ordered-SQL
    migrations run as — the whole point of keeping two settings. A
    single-user install is not a reason to collapse them into one: this is
    the two settings simply BEING each other, which is different from
    `_refuse_two_dsns_that_select_different_schemas` below, where they
    DISAGREE about where they land. It is different too from the accepted
    "single-role install" (`test_a_dsn_that_names_no_database_still_reaches_
    one`): two DSNs for the same ROLE with two DIFFERENT secrets are two
    credentials, not one pasted twice, and this checks the value actually
    given, not the identity it happens to resolve to.
    """
    if not migration:
        return
    if served == migration:
        raise ConfigurationError(
            f"{PREFIX}MIGRATION_DATABASE_URL is the same value as "
            f"{PREFIX}DATABASE_URL. The identity migrations run as must not "
            "also be the identity the API serves with; give the migration "
            "credential its own DSN, even where both reach the same "
            "database (the values are not repeated: a DSN carries a "
            "password)")


def _refuse_two_dsns_that_select_different_schemas(
        served: str, migration: str | None) -> None:
    """Both DSNs must land in one schema, or neither answer means anything.

    THE TWO ARE INDEPENDENTLY CONFIGURABLE, and nothing tied them together:
    the migration runner derives its schema from
    `OPENDOX_MIGRATION_DATABASE_URL` and the served `Database` uses
    `OPENDOX_DATABASE_URL`, so two DSNs at the same database with different
    `search_path` options let migrations apply and VERIFY schema A while
    `/readyz` and the API read schema B — including a pre-existing fully
    migrated schema, which is another install's coordination data (Copilot
    review of openDox-code#25, round 34).

    WHAT THIS CATCHES is the configured form: a schema named in either DSN's
    own `options`, which is how `Database(schema=…)`, both `deploy/` shapes
    and the runbook select one. WHAT IT DOES NOT catch is a schema that comes
    from a ROLE's default `search_path` on the server, which no string can
    see — `migrations.selected_schema` is the guard there, and it refuses a
    connection whose `current_schema()` is a fallback rather than the schema
    it asked for. The two together are the boundary; this one is the half that
    can answer before anything connects.
    """
    if not migration:
        return
    # THE DATABASE FIRST, because the schema comparison means nothing across
    # two of them: `public` in one database and `public` in another are two
    # different sets of tables, and the run would apply and VERIFY one while
    # the API reads the other (Copilot review of openDox-code#25, round 36).
    # AND THE DEFAULT COUNTS AS A NAME. `database_named_by` reports what the
    # STRING says, and two DSNs that both leave the database out both answered
    # `None` — read here as agreement. It is not: libpq defaults `dbname` to
    # the CONNECTION USER, and this deployment's two DSNs carry deliberately
    # different users, so "neither names a database" is two different
    # databases (Copilot review of openDox-code#25, at `0968ff8b`). See
    # `effective_database` for the measurement.
    mine, yours = effective_database(served), effective_database(migration)
    if mine is None or yours is None:
        unnamed = [name for name, value in (
            (PREFIX + "DATABASE_URL", mine),
            (PREFIX + "MIGRATION_DATABASE_URL", yours)) if value is None]
        raise ConfigurationError(
            f"{' and '.join(unnamed)} "
            f"{'name' if len(unnamed) > 1 else 'names'} neither a database "
            "nor a user, so which database "
            f"{'they reach' if len(unnamed) > 1 else 'it reaches'} cannot be "
            "established before connecting: "
            "libpq falls back to the OPERATING SYSTEM user of whichever "
            "process connects, and these two DSNs are used by two different "
            "containers. Name the database in both (the values are not "
            "repeated: a DSN carries a password)")
    if mine != yours:
        raise ConfigurationError(
            f"{PREFIX}DATABASE_URL reaches the database {mine} and "
            f"{PREFIX}MIGRATION_DATABASE_URL reaches {yours}. Migrations "
            "would be applied and verified in one database while the API and "
            "/readyz read the other, so a run could report an applied schema "
            "that nothing serves. Point both at the same database — and note "
            "that a DSN which names no database reaches the one named after "
            "its USER, which is how two DSNs with no `dbname` at all end up "
            "in two places (the values are not repeated beyond the database "
            "names: a DSN carries a password)")
    # THE HOST AND PORT ARE DELIBERATELY NOT COMPARED, and that is a judgement
    # rather than an omission. A served DSN through a connection pooler and a
    # migration DSN direct to the server is the ordinary secure shape, and it
    # is the SAME database reached two ways — nothing in either string tells a
    # pooler from a second server. What catches a genuinely different server
    # is the ledger: its schema is not the one this install migrated, so
    # `/readyz` and `status` report it as not applied rather than ready.
    # `"$user"` IS A TOKEN AND NOT A NAME, and comparing it as a literal made
    # two DSNs for different roles agree on the string `$user` while
    # PostgreSQL resolved them to two different schemas (Copilot review of
    # openDox-code#25, at `0968ff8b`). `effective_schema` substitutes it the
    # way the server does — see there for the measurement, including the one
    # that shows a schema LITERALLY named `$user` is skipped too.
    here, there = effective_schema(served), effective_schema(migration)
    for setting, dsn, resolved in (
            (PREFIX + "DATABASE_URL", served, here),
            (PREFIX + "MIGRATION_DATABASE_URL", migration, there)):
        if schema_selected_by(dsn) == "$user" and resolved is None:
            raise ConfigurationError(
                f"{setting} selects the schema `\"$user\"`, which PostgreSQL "
                "replaces with the session user's name — and that DSN names "
                "no user, so which schema it selects cannot be established "
                "before connecting. Name the user in the DSN, or select the "
                "schema by name (the value is not repeated: a DSN carries a "
                "password)")
    if here == there:
        return
    raise ConfigurationError(
        f"{PREFIX}DATABASE_URL selects the schema "
        f"{here or '(the connection default)'} and "
        f"{PREFIX}MIGRATION_DATABASE_URL selects "
        f"{there or '(the connection default)'}. Migrations would be applied "
        "and verified in one schema while the API and /readyz read the other, "
        "so a run could report an applied schema that nothing serves — or "
        "serve a schema this install never migrated. Point both at the same "
        "schema (the values are not repeated beyond the schema names: a DSN "
        "carries a password)")


#: THE TWO INSTALL SHAPES (plan 034 T070; #1144 13.4). One selector decides
#: the whole shape at once — the identity mode here, and the datastore source
#: 13.1 adds — because requirements 12 and 13 both describe "the standalone
#: install" and one deliberate choice should decide both.
INSTALL_MODE_HOSTED = "hosted"
INSTALL_MODE_LOCAL = "local"
INSTALL_MODES: tuple[str, ...] = (INSTALL_MODE_LOCAL, INSTALL_MODE_HOSTED)

#: The flag that makes the same selection as `OPENDOX_INSTALL_MODE=local`,
#: spelled ONCE: `opendox.cli` declares `generate-and-open`'s option with this
#: constant, and every refusal below names it with the same one (R1Q15 (b), as
#: T007 batch H's 13.4 addendum reads).
LOCAL_FLAG = "--local"

#: LOOPBACK, AS THE DOCUMENT SERVER ALREADY JUDGES IT. `serve.py` makes its
#: `session` capability conditional on a bind in exactly this set
#: (`serve.LOOPBACK_HOSTS`), and 13.4 asks the local mode to "make the same
#: judgement at the mode's own boundary" — so it is the same set, not
#: `_is_loopback` above: that one reads `127.0.0.0/8` as loopback, and a local
#: install bound to `127.0.0.2` would then pass here while the server it starts
#: treats that very bind as off-loopback. This module cannot import `serve`
#: (the import weight in `opendox/runtime/__init__.py`), so the set is spelled
#: here and `tests_runtime/test_install_mode.py` holds it equal to serve's.
LOCAL_BIND_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

#: THE SETTINGS ONLY A HOSTED INSTALL READS. Given beside the local mode, each
#: is REFUSED, by name (a holder reading on openxFactory#656, plan 034 T070,
#: the same fail-closed reading as the disagreeing flag and setting): an issuer
#: next to `local` says a broker was meant, and honouring `local` over it would
#: silently drop the authentication the operator configured.
#:
#: AND THE TWO DSNs (plan 034 T072; the same holder reading): a local install
#: SUPPLIES BOTH ITSELF, from the server it bundles (#1144 13.1, "so no
#: pre-existing service can stand in for it"), so an operator's DSN beside
#: `local` is either about to be silently overridden or is another server
#: trying to stand in for the bundled one. Neither is accepted.
#:
#: TWO CLASSES, TWO REASONS (Copilot review of openDox-code#69): the broker
#: settings are refused because honouring `local` would drop an
#: authentication, and the DSNs because the local install supplies its own
#: database. Each refusal says its own reason.
BROKER_SETTINGS: tuple[str, ...] = (
    PREFIX + "OIDC_ISSUER",
    PREFIX + "OIDC_AUDIENCE",
    PREFIX + "OIDC_JWKS_URL",
)
OPERATOR_DATABASE_SETTINGS: tuple[str, ...] = (
    PREFIX + "DATABASE_URL",
    PREFIX + "MIGRATION_DATABASE_URL",
)
HOSTED_ONLY_SETTINGS: tuple[str, ...] = BROKER_SETTINGS + OPERATOR_DATABASE_SETTINGS

#: THE BUNDLED SERVER'S IDENTITY (plan 034 T072; #1144 13.1, as T007 batch H's
#: addendum reads). The data directory and the socket directory live under the
#: install's own `OPENDOX_STATE_DIR`, at these paths — SHORT ONES, because a
#: Unix socket's whole path is bounded by the kernel (`sun_path`) and the
#: socket file is `<socket dir>/.s.PGSQL.<port>`.
BUNDLE_DATA_DIR = PurePath("postgres", "data")
BUNDLE_SOCKET_DIR = PurePath("postgres", "run")
#: The port NUMBER, which names the socket file and opens NO TCP port: the
#: server is started with `listen_addresses` empty (13.1: "on NO TCP port").
BUNDLE_PORT = 5432
#: The two identities 13.3 keeps apart, and the one database. The MIGRATION
#: identity owns the database and every table it creates; the SERVED identity
#: is the least-privileged role the API reads and writes as, granted what
#: `deploy/compose/init-runtime-role.sh` grants the compose stack's role of the
#: same name. Two DSNs, two users, never one pasted twice (13.3).
BUNDLE_OWNER_ROLE = "opendox"
BUNDLE_SERVED_ROLE = "opendox_runtime"
BUNDLE_DATABASE = "opendox"

#: The longest socket path the kernel takes, in bytes: `sizeof(sun_path)` less
#: its terminating NUL — 108 on Linux, 104 on macOS and the BSDs. PostgreSQL
#: refuses a longer one at startup; this refuses it at configuration, naming
#: the setting that made it long.
UNIX_SOCKET_PATH_MAX = 107 if sys.platform.startswith("linux") else 103


@dataclass(frozen=True)
class DatabaseBundle:
    """Where a LOCAL install's bundled PostgreSQL server lives, and its DSNs.

    Pure path and string arithmetic over `OPENDOX_STATE_DIR`, so `load_settings`
    can name both DSNs without starting anything, and `runtime status` in a
    second process derives the SAME ones and finds the same server.
    `opendox.runtime.bundle` is what starts and stops it.
    """

    state_dir: Path

    @property
    def data_dir(self) -> Path:
        return self.state_dir / BUNDLE_DATA_DIR

    @property
    def socket_dir(self) -> Path:
        return self.state_dir / BUNDLE_SOCKET_DIR

    @property
    def socket_path(self) -> Path:
        return self.socket_dir / f".s.PGSQL.{BUNDLE_PORT}"

    def dsn(self, role: str) -> str:
        """A DSN for `role` over the bundle's Unix socket, and never TCP.

        `host` is the socket DIRECTORY (libpq's rule for a value that starts
        with `/`), percent-encoded so a state directory holding a space or a
        `&` is still one value; `port` is spelled so a `PGPORT` in the
        environment cannot send libpq to a different socket file. NO
        PASSWORD, because there is none to give: the server authenticates a
        Unix-socket connection by PEER (RULED openxFactory#656 `5916000030`
        item 3). The kernel reports the connecting process's uid, and
        `pg_ident.conf` maps this install's OS user, and nobody else, to the
        two roles. The socket's directory is 0700, the server opens no TCP
        port, and a host connection is rejected outright. SonarCloud's S2115
        ("add password protection") is ACCEPTED on this line for that reason,
        with the same ruling as its authority.
        """
        host = urllib.parse.quote(str(self.socket_dir), safe="/")
        return (f"postgresql://{role}@/{BUNDLE_DATABASE}"
                f"?host={host}&port={BUNDLE_PORT}")

    @property
    def served_dsn(self) -> str:
        return self.dsn(BUNDLE_SERVED_ROLE)

    @property
    def migration_dsn(self) -> str:
        return self.dsn(BUNDLE_OWNER_ROLE)


def state_dir(env: Mapping[str, str] | None = None) -> Path:
    """The install's own state directory: `OPENDOX_STATE_DIR`, or the per-user one.

    ABSOLUTE, or refused: the document server that starts the bundled server
    and a `runtime status` run from another directory must derive the same
    socket, and a relative value would give each its own. Unset, it is
    `$XDG_STATE_HOME/opendox` where that is absolute (the XDG rule ignores a
    relative one), and otherwise `~/.local/state/opendox`.
    """
    env = os.environ if env is None else env
    setting = PREFIX + "STATE_DIR"
    raw = env.get(setting, "").strip()
    if raw:
        try:
            path = Path(raw).expanduser()
        except RuntimeError:
            # `~nosuchuser/...`: `expanduser` raises rather than answering, and
            # a setting is refused by name, never by a traceback (Copilot
            # review of openDox-code#69).
            raise ConfigurationError(
                f"{setting} is {raw!r}, whose `~` names no user this system "
                "knows, so it expands to no directory. Name the state "
                "directory absolutely") from None
        if ".." in path.parts:
            # PARENT TRAVERSAL IS REFUSED, so the path the bundle checks is
            # the one the kernel walks: `a/../b` names `b` lexically and
            # something else wherever `a` is a symbolic link (Copilot review
            # of openDox-code#69).
            raise ConfigurationError(
                f"{setting} is {raw!r}, which climbs out through `..`. Name "
                "the state directory directly")
        if not path.is_absolute():
            raise ConfigurationError(
                f"{setting} is {raw!r}, which is not an absolute path. The "
                "document server that starts the bundled PostgreSQL server "
                "and a `runtime status` run from another directory must find "
                "the same socket, so the state directory is named absolutely")
        return path
    xdg = env.get("XDG_STATE_HOME", "").strip()
    if xdg and Path(xdg).is_absolute():
        if ".." in Path(xdg).parts:
            raise ConfigurationError(
                f"{setting} is unset and XDG_STATE_HOME is {xdg!r}, which "
                f"climbs out through `..`. Set {setting}, or XDG_STATE_HOME, "
                "to the directory itself")
        return Path(xdg) / "opendox"
    try:
        home = Path.home()
    except RuntimeError:
        raise ConfigurationError(
            f"{setting} is unset and this process has no home directory to "
            "put the default under (no HOME, and no password entry for the "
            f"user). Set {setting} to an absolute path") from None
    if not home.is_absolute():
        # `Path.home()` returns HOME as given, and a relative one would give
        # the serving process and a `runtime status` run from another
        # directory two different sockets (Copilot review of openDox-code#69).
        raise ConfigurationError(
            f"{setting} is unset and HOME is {str(home)!r}, which is not an "
            "absolute path, so the default state directory would depend on "
            f"the working directory. Set {setting} to an absolute path, or "
            "HOME to one")
    if ".." in home.parts:
        raise ConfigurationError(
            f"{setting} is unset and HOME is {str(home)!r}, which climbs out "
            f"through `..`. Set {setting} to the directory itself")
    return home / ".local" / "state" / "opendox"


def database_bundle(state: Path) -> DatabaseBundle:
    """The bundle under `state`, refusing a socket path the kernel cannot bind.

    A COMMA IS REFUSED, wherever the state directory came from
    (`OPENDOX_STATE_DIR`, `XDG_STATE_HOME` or the home directory), because
    both ends read the socket directory as a LIST. PostgreSQL splits `-k`
    (`unix_socket_directories`) on commas, and libpq splits a `host` on them
    once the DSN's percent-encoding is decoded. So `…/a,…/b` made the server
    put its sockets in two directories nothing here had checked, one of
    them anyone could write, while the checked 0700 one stayed empty
    (adversarial review of openDox-code#69). The value is not repeated:
    the refusal names where it came from, and that is enough to find it.
    """
    bundle = DatabaseBundle(state_dir=state)
    if "," in str(state):
        raise ConfigurationError(
            "the state directory's path holds a `,`. PostgreSQL reads its "
            "socket directories, and libpq its hosts, as comma-separated "
            "lists, so a comma would split this install's one socket "
            "directory into two it never checked. Choose a state directory "
            f"without one: {PREFIX}STATE_DIR or, where that is unset, "
            "XDG_STATE_HOME or HOME")
    length = len(os.fsencode(str(bundle.socket_path)))
    if length > UNIX_SOCKET_PATH_MAX:
        raise ConfigurationError(
            f"{PREFIX}STATE_DIR is too long for the bundled server's Unix "
            f"socket: {bundle.socket_path} is {length} bytes and this kernel "
            f"takes at most {UNIX_SOCKET_PATH_MAX}. The socket must live under "
            "the install's own state directory (13.1), so choose a shorter "
            f"{PREFIX}STATE_DIR")
    return bundle


#: WHERE AN INSTALLED WHEEL KEEPS ITS MIGRATIONS (plan 034 T072). The
#: repository's `migrations/` stays where it is — the image copies it to
#: `/app/migrations` and runs from `/app` — and `pyproject.toml` maps the same
#: files into the wheel's data directory under this path, so an install run
#: outside any checkout still has the migrations it applies. The canonical
#: digest gate (`migrations.verify_canonical_digest`) is what proves any copy
#: found this way is the pinned one.
PACKAGED_MIGRATIONS = PurePath("share", "opendox", "migrations")


def _source_tree_migrations(module_file: Path) -> Path | None:
    """The `migrations/` of the SOURCE TREE `module_file` was imported from.

    `module_file` is this module (`src/opendox/runtime/config.py`), so the
    tree is three directories up: a checkout run with `src/` on the path, or
    an editable install, neither of which installs data files. It counts only
    where it really is that tree: `src/` is the directory the package sits
    in, and the root's `pyproject.toml` names THIS project. A wheel's
    `site-packages`, or a `--target` directory that happens to sit inside
    some other checkout, is neither.
    """
    here = module_file.resolve()
    package_parent, root = here.parents[2], here.parents[3]
    if package_parent.name != "src":
        return None
    try:
        project = tomllib.loads(
            (root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if project.get("project", {}).get("name") != "opendox":
        return None
    candidate = root / "migrations"
    return candidate if candidate.is_dir() else None


def _distribution_migrations(module_file: Path,
                             distribution: Any | None = None) -> Path | None:
    """The migrations the INSTALLED DISTRIBUTION of `module_file` carries.

    From the distribution's own `RECORD`, wherever its install scheme put the
    data files — and ONLY when that distribution is the one `module_file` was
    loaded from. A name lookup alone is not: with a checkout's `src/` on the
    path, `distribution("opendox")` can find an older wheel installed beside
    it, and that wheel's migrations are another version's (Copilot review of
    openDox-code#69).
    """
    if distribution is None:
        try:
            distribution = importlib.metadata.distribution("opendox")
        except importlib.metadata.PackageNotFoundError:
            return None
    files = list(distribution.files or ())
    here = module_file.resolve()
    tail = here.parts[-3:]                      # ("opendox", "runtime", "config.py")
    if not any(PurePath(entry).parts[-3:] == tail
               and Path(entry.locate()).resolve() == here for entry in files):
        return None
    for entry in files:
        parts = PurePath(entry).parts
        if (entry.name.endswith(".sql")
                and tuple(parts[-4:-1]) == PACKAGED_MIGRATIONS.parts):
            return Path(entry.locate()).resolve().parent
    return None


def installation_migrations_dir() -> Path | None:
    """The migrations THIS INSTALLATION carries, or `None` where it carries none.

    Tied to the code that is running, never to a name or to the working
    directory. First the source tree this module was imported from (a
    checkout, or an editable install). Then the installed distribution that
    this module belongs to, from its `RECORD` (a wheel install). A real wheel
    install has no `pyproject.toml` beside its package, so it falls through to
    its own `RECORD` (Copilot review of openDox-code#69).
    """
    module_file = Path(__file__)
    return (_source_tree_migrations(module_file)
            or _distribution_migrations(module_file))


def migrations_dir(env: Mapping[str, str] | None = None, *,
                   local: bool = False) -> Path:
    """`OPENDOX_MIGRATIONS_DIR`, or where this install's migrations are.

    SET, it is used as given, in either shape: executing another directory's
    SQL is something an operator says, not something a directory implies.

    UNSET, the shape decides.
      * A LOCAL install uses ONLY the copy this installation carries
        (`installation_migrations_dir`), never the working directory's. Its
        entry point runs every migration it finds as the bundled server's
        OWNER, and the canonical gate pins `0001` alone. So a `migrations/`
        in whatever directory a user launches it from, holding the pinned
        `0001` and SQL of its own, would otherwise be executed (Copilot
        review of openDox-code#69). An installation that carries none is
        refused, naming the setting.
      * A HOSTED install keeps today's default, unchanged (13.6): `migrations`
        where the working directory holds one (the image's `/app`, a
        checkout), and otherwise the copy this installation carries. Where
        neither exists, it is still `migrations`, and the canonical gate
        refuses it by name. The compose file and the Kubernetes manifests
        set the variable explicitly, so they read nothing implicit.
    """
    env = os.environ if env is None else env
    setting = PREFIX + "MIGRATIONS_DIR"
    raw = env.get(setting, "").strip()
    if raw:
        return Path(raw)
    if local:
        found = installation_migrations_dir()
        if found is None:
            raise ConfigurationError(
                f"{setting} is unset, and this installation carries no "
                "migrations of its own: a wheel install has them under "
                f"`{PACKAGED_MIGRATIONS}` in its data directory, and a "
                "checkout has `migrations/` beside `src/`. A LOCAL install "
                "never reads the working directory's `migrations/`, because "
                "its entry point runs them as the bundled server's owner. "
                f"Reinstall the package, or name the directory in {setting}")
        return found
    here = Path("migrations")
    if here.is_dir():
        return here
    return installation_migrations_dir() or here


def install_mode(env: Mapping[str, str] | None = None, *,
                 local_flag: bool = False) -> str:
    """`INSTALL_MODE_LOCAL` or `INSTALL_MODE_HOSTED`, or a refusal naming why.

    THE DEFAULT IS HOSTED, and it is the default because it is the safe one
    (#1144 13.4: "It is UNSET, not `local`, that must be safe"): an install
    that sets nothing is hosted, and a hosted install with no issuer refuses
    (13.5), so single-user operation is never reached by forgetting to
    configure something. A BLANK value is unset, the reading `_optional` gives
    every other setting.

    `local_flag` is `generate-and-open --local` (R1Q15 (b)). It selects local
    exactly as `OPENDOX_INSTALL_MODE=local` does, and the two may not
    DISAGREE: `--local` beside `OPENDOX_INSTALL_MODE=hosted` is refused naming
    both, so no explicit selection is silently overridden by the other. No
    answer on #656 rules that pair; the refusal is plan 034's fail-closed
    reading (Principle VII, T070), recorded for Brett in
    `evidence/analyze-round-2.md` and NOT written into #1144.

    AN UNRECOGNISED VALUE IS REFUSED, matched case-sensitively (a holder
    reading on #656, T070): `Local` or `single-user` is not a spelling of
    either shape, and guessing which one was meant is the one thing a
    selector whose default is a safety property must not do.
    """
    env = os.environ if env is None else env
    setting = PREFIX + "INSTALL_MODE"
    raw = env.get(setting, "").strip()
    if raw and raw not in INSTALL_MODES:
        raise ConfigurationError(
            f"{setting} is {raw!r}, which is neither `local` nor `hosted` (the "
            "two values are matched exactly, case included). Unset means "
            "hosted; a single-user install selects `local` explicitly, with "
            f"{setting}=local or `generate-and-open {LOCAL_FLAG}`")
    if local_flag and raw == INSTALL_MODE_HOSTED:
        raise ConfigurationError(
            f"{LOCAL_FLAG} selects the LOCAL install and {setting}=hosted "
            "selects the HOSTED one. Both are explicit selections and they "
            "disagree, so neither is allowed to override the other: drop the "
            f"flag for a hosted install, or unset {setting} (or set it to "
            "`local`) for a local one")
    if local_flag:
        return INSTALL_MODE_LOCAL
    return raw or INSTALL_MODE_HOSTED


def refuse_a_non_loopback_local_bind(name: str, host: str) -> None:
    """A LOCAL install binds loopback only, with NO opt-in (#1144 13.4).

    `name` is what set the address — `--host` on `generate-and-open`, or
    `OPENDOX_BIND_HOST` for the runtime's own listener — so the refusal names
    the thing the operator actually typed. The local mode has no broker, so a
    local install other machines can reach is an unauthenticated multi-user
    service wearing the word "local"; an install that must be reachable from
    another machine is a HOSTED install, with a broker.
    """
    if host in LOCAL_BIND_HOSTS:
        return
    raise ConfigurationError(
        f"{name} {host!r} is not a loopback address, and a LOCAL install binds "
        f"LOOPBACK ONLY ({', '.join(sorted(LOCAL_BIND_HOSTS))}). The local "
        "mode has no identity broker, so a local install another machine can "
        "reach would be an unauthenticated multi-user service. There is no "
        "opt-in: an install that must be reachable from another machine is a "
        "HOSTED install, with a broker (13.4)")


def refuse_what_a_local_install_cannot_be(env: Mapping[str, str]) -> None:
    """The two refusals a LOCAL install makes of its own environment.

    Every hosted-only setting given beside it (`HOSTED_ONLY_SETTINGS`), and a
    non-loopback `OPENDOX_BIND_HOST`, the runtime's own listener. One function,
    because `load_settings` and `generate-and-open --local` both ask it and the
    two must not come to disagree about what a local install is.
    """
    _refuse_hosted_only_settings(env)
    refuse_a_non_loopback_local_bind(
        PREFIX + "BIND_HOST",
        _optional(env, _by_name(PREFIX + "BIND_HOST")) or "127.0.0.1")


def _named(given: list[str]) -> str:
    return f"{' and '.join(given)} {'are' if len(given) > 1 else 'is'} set"


def _refuse_hosted_only_settings(env: Mapping[str, str]) -> None:
    """Every setting in `HOSTED_ONLY_SETTINGS` given beside `local`, named.

    Each CLASS carries its own reason (Copilot review of openDox-code#69).
    A broker setting says a hosted install was meant, and a DSN says another
    database was meant. A local run with only `OPENDOX_DATABASE_URL` is told
    about its database, not about an authentication it never configured.
    The values are never repeated: a DSN carries a password.
    """
    def given(names: tuple[str, ...]) -> list[str]:
        return [name for name in names if env.get(name, "").strip()]

    brokers, databases = given(BROKER_SETTINGS), given(OPERATOR_DATABASE_SETTINGS)
    if not (brokers or databases):
        return
    reasons = []
    if brokers:
        reasons.append(
            f"{_named(brokers)}, and a LOCAL install has no broker and reads "
            f"{'none of them' if len(brokers) > 1 else 'none'}. A broker "
            "setting beside the local mode says a HOSTED install was meant, "
            "and honouring `local` over it would silently drop that "
            "authentication")
    if databases:
        reasons.append(
            f"{_named(databases)}, and a LOCAL install supplies BOTH of its "
            "DSNs itself, from the PostgreSQL server it bundles under "
            f"{PREFIX}STATE_DIR (13.1). An operator's DSN beside the local "
            "mode would either be silently overridden or be another server "
            "standing in for the bundled one, and neither is accepted")
    every = brokers + databases
    raise ConfigurationError(
        "; and ".join(reasons) + f". Unset {'them' if len(every) > 1 else 'it'} "
        f"for a local install, or drop {LOCAL_FLAG} / "
        f"{PREFIX}INSTALL_MODE=local for a hosted one (the values are not "
        "repeated here)")


def require_the_hosted_issuer(env: Mapping[str, str] | None = None) -> None:
    """A HOSTED install with no issuer refuses, NAMING THE ISSUER (#1144 13.5).

    `load_settings` asks for the served DSN before it asks for the issuer, so
    a hosted `generate-and-open` run with NOTHING configured would otherwise
    be refused naming `OPENDOX_DATABASE_URL` — true, and not the refusal 13.5
    and plan 034's requirement-13 scenario ask for, which is the one that
    tells an operator this install is HOSTED and how to select the other one.
    So the document server's entry point asks this first, and `load_settings`
    keeps its own order for every verb that already relies on it (13.6: the
    hosted mode is otherwise unchanged).
    """
    env = os.environ if env is None else env
    issuer = PREFIX + "OIDC_ISSUER"
    if env.get(issuer, "").strip():
        return
    selected = (f"{PREFIX}INSTALL_MODE=hosted"
                if env.get(PREFIX + "INSTALL_MODE", "").strip()
                else f"{PREFIX}INSTALL_MODE is unset, and unset means hosted")
    raise ConfigurationError(
        f"{issuer} is required and is not set, and this install is HOSTED "
        f"({selected}). A hosted install authenticates through the broker "
        "whose issuer this names, and it does NOT fall back to single-user "
        "operation without one (13.5). A single-user install selects the "
        f"local mode explicitly: `generate-and-open {LOCAL_FLAG}` or "
        f"{PREFIX}INSTALL_MODE=local")


def _hosted_state_dir(env: Mapping[str, str]) -> Path:
    """A HOSTED install's `state_dir`: reported, never read, never refused.

    A hosted install has no bundled server, so a value it will never use is
    not a reason for it to refuse to start (13.6: otherwise unchanged). It is
    still reported, so `status` describes the whole declared setting list.
    """
    try:
        return state_dir(env)
    except ConfigurationError:
        return Path(env.get(PREFIX + "STATE_DIR", "").strip())


def load_settings(env: Mapping[str, str] | None = None, *,
                  local_flag: bool = False) -> RuntimeSettings:
    """Resolve :class:`RuntimeSettings` from `env` (default `os.environ`).

    Refuses with :class:`ConfigurationError` naming the variable — never with a
    default that would point a runtime at the wrong database or trust the wrong
    issuer.

    ALGORITHMS ARE ALLOW-LISTED AND SYMMETRIC ONES ARE REFUSED HERE, at
    configuration time rather than at the first token: a runtime configured to
    accept `HS256` would verify a token signed with the public key anybody can
    fetch from the broker's JWKS, and discovering that on the first request
    means it is already serving.

    `OPENDOX_MIGRATION_DATABASE_URL` STAYS OPTIONAL HERE (RULED "required only
    for migrate", openxFactory#656, on the claim thread for plan 034's T071,
    2026-09-28): the served workload never needs it —
    `deploy/compose/docker-compose.yaml`'s `opendox` service and
    `docs/runtime.md` § 3 never supply it, keeping the two identities in
    different containers — and `load_migration_settings` below is the loader
    that actually requires one. It is never DEFAULTED from
    `OPENDOX_DATABASE_URL` either way. WHEN BOTH ARE GIVEN, though, the two
    checks below still apply: a non-PostgreSQL migration DSN is refused
    (13.2), and the two being the exact same value is refused (13.3) —
    optional does not mean unchecked.

    THE INSTALL MODE FIRST (plan 034 T070; #1144 13.4-13.6). `local_flag` is
    `generate-and-open --local`, resolved against `OPENDOX_INSTALL_MODE` by
    `install_mode`, which refuses the two disagreeing. A HOSTED install — the
    default — is exactly what this function has always loaded, in the same
    order, with the issuer and audience required (13.6). A LOCAL install needs
    no broker: its issuer, audience and key-set URL are empty, and any of the
    three GIVEN beside it is refused (`HOSTED_ONLY_SETTINGS`); and its own
    listener, `OPENDOX_BIND_HOST`, must be loopback, with no opt-in.
    """
    env = os.environ if env is None else env

    mode = install_mode(env, local_flag=local_flag)
    local = mode == INSTALL_MODE_LOCAL
    if local:
        refuse_what_a_local_install_cannot_be(env)
    algorithms = _algorithms(env)
    # A LOCAL INSTALL SUPPLIES BOTH DSNs ITSELF (plan 034 T072; #1144 13.1),
    # from the server it bundles under its own state directory, and an
    # operator's DSN beside it was refused above. The two it supplies are two
    # users over one socket, so T071's three checks below pass them for the
    # reason they exist: one dialect, one database, and never one credential
    # in both settings.
    state = state_dir(env) if local else _hosted_state_dir(env)
    if local:
        bundle = database_bundle(state)
        served: str = bundle.served_dsn
        migration: str | None = bundle.migration_dsn
    else:
        served = _require(env, _by_name(PREFIX + "DATABASE_URL"))
        migration = _optional(env, _by_name(PREFIX + "MIGRATION_DATABASE_URL"))
    # THE DIALECT FIRST: a scheme this module cannot parse as PostgreSQL is not
    # yet a DSN worth comparing at all. A no-op on an ABSENT migration DSN —
    # see `_refuse_non_postgresql_dsn`.
    _refuse_non_postgresql_dsn(PREFIX + "DATABASE_URL", served)
    _refuse_non_postgresql_dsn(PREFIX + "MIGRATION_DATABASE_URL", migration)
    # THEN WHETHER THEY DISAGREE. See `_refuse_two_dsns_that_select_different_
    # schemas`: this is the half of that invariant a string can answer, and it
    # is asked here because this is the one loader that holds BOTH values. A
    # DSN compared against ITSELF can never disagree, so this step passes
    # silently on exactly the pair the next one exists to catch.
    _refuse_two_dsns_that_select_different_schemas(served, migration)
    # AND, LAST, WHETHER THEY ARE SIMPLY EACH OTHER. Two DSNs that agree on
    # where they land are ordinarily two credentials for the one database
    # (`test_a_dsn_that_names_no_database_still_reaches_one`'s "single-role
    # install" is exactly that, two DIFFERENT secrets for one role) — but
    # agreement bought by pasting the SAME value into both settings is not a
    # second decision at all, and this is the check the one before it cannot
    # make.
    _refuse_the_same_dsn_in_both_settings(served, migration)

    bind_host = _optional(env, _by_name(PREFIX + "BIND_HOST")) or "127.0.0.1"

    return RuntimeSettings(
        database_url=served,
        migration_database_url=migration,
        install_mode=mode,
        state_dir=state,
        oidc_issuer="" if local else _broker_url(
            env, _by_name(PREFIX + "OIDC_ISSUER"),
            required=True, is_a_base_url=True) or "",
        oidc_audience="" if local else _require(
            env, _by_name(PREFIX + "OIDC_AUDIENCE")),
        oidc_jwks_url=None if local else _broker_url(
            env, _by_name(PREFIX + "OIDC_JWKS_URL"), required=False),
        oidc_algorithms=algorithms,
        oidc_jwks_ttl_seconds=_positive_int(env, _by_name(PREFIX + "OIDC_JWKS_TTL_SECONDS")),
        oidc_leeway_seconds=_positive_int(env, _by_name(PREFIX + "OIDC_LEEWAY_SECONDS")),
        bind_host=bind_host,
        bind_port=_positive_int(env, _by_name(PREFIX + "BIND_PORT")),
        # THE BUNDLE'S OWN NAMES where the operator declares none: the served
        # role the migration narrows and verifies, and the database it may
        # touch. An operator's declaration still wins, and a wrong one is
        # refused by the migration run's own guards, as on a hosted install.
        runtime_pg_role=_role_name(env) or (BUNDLE_SERVED_ROLE if local else None),
        served_schema=_served_schema(env),
        served_database=_served_database(env) or (BUNDLE_DATABASE if local else None),
        publish_openapi=_boolean(env, _by_name(PREFIX + "PUBLISH_OPENAPI")),
        migrations_dir=migrations_dir(env, local=local),
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
    # THE ONE READING OF THE SELECTOR, AND OF WHAT A LOCAL INSTALL CANNOT BE
    # (plan 034 T070; Copilot review of openDox-code#67). A migration run is
    # part of the same install as the served one, so `runtime migrate` and
    # `runtime reset` refuse what `load_settings` and `generate-and-open`
    # refuse beside `local` — a broker setting, an operator's DSN, or a
    # non-loopback `OPENDOX_BIND_HOST` — rather than accepting it in the one
    # loader that never reads it.
    mode = install_mode(env)
    local = mode == INSTALL_MODE_LOCAL
    if local:
        # THE BUNDLE'S OWNER, over its socket (plan 034 T072): a local install
        # supplies its migration DSN as it supplies the served one, and an
        # operator's beside it is refused, exactly as `load_settings` refuses.
        refuse_what_a_local_install_cannot_be(env)
        state = state_dir(env)
        dsn = database_bundle(state).migration_dsn
    else:
        state = _hosted_state_dir(env)
        dsn = env.get(PREFIX + "MIGRATION_DATABASE_URL", "").strip()
    if not dsn:
        raise ConfigurationError(
            f"{PREFIX}MIGRATION_DATABASE_URL is required to apply migrations; "
            f"{PREFIX}DATABASE_URL is the served runtime's least-privileged "
            "identity and is deliberately not used for schema changes")
    # THE SAME DIALECT GATE `load_settings` ASKS, asked here too (Copilot
    # review of this PR): this loader is the one path 13.2's own falsifier
    # does not reach, and without this call a non-PostgreSQL migration DSN
    # sailed past configuration entirely and reached `Database` instead,
    # which is exactly the un-named, un-refused failure 13.2 exists to
    # prevent for `load_settings`. `database_url` is set to this same `dsn`
    # immediately below, so one call here covers both fields.
    _refuse_non_postgresql_dsn(PREFIX + "MIGRATION_DATABASE_URL", dsn)
    return RuntimeSettings(
        database_url=dsn,
        migration_database_url=dsn,
        # READ ABOVE, SO AN UNRECOGNISED VALUE IS REFUSED HERE TOO (plan 034
        # T070): a migration run is part of the same install and one reading
        # of the selector serves every verb. It changes nothing else a
        # migration run does; the broker fields below are sentinels in either
        # shape.
        install_mode=mode,
        state_dir=state,
        oidc_issuer=MIGRATION_SENTINEL_ISSUER,
        oidc_audience=MIGRATION_SENTINEL_AUDIENCE,
        oidc_jwks_url=None,
        oidc_algorithms=(ASYMMETRIC_ALGORITHMS[0],),
        oidc_jwks_ttl_seconds=1,
        oidc_leeway_seconds=1,
        bind_host="127.0.0.1",
        bind_port=1,
        runtime_pg_role=_role_name(env) or (BUNDLE_SERVED_ROLE if local else None),
        served_schema=_served_schema(env),
        served_database=_served_database(env) or (BUNDLE_DATABASE if local else None),
        publish_openapi=False,
        migrations_dir=migrations_dir(env, local=local),
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
