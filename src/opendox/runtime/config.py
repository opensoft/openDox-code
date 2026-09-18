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
import shlex
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
        PREFIX + "SERVED_SCHEMA", "", False, False,
        "the NAME (never a credential) of the schema the SERVED application "
        "reads, declared to the migration run so it can refuse to apply DDL "
        "anywhere else; the two DSNs are configured in different workloads and "
        "no process holds both, so this is how a migration container learns "
        "what the API will read",
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
    served_schema: str | None
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
            f"served_schema={self.served_schema!r}, "
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


#: THE NEEDLES LONG ENOUGH TO BE UNAMBIGUOUS INSIDE A LONGER WORD. Whole-word
#: matching alone answered `sslpassword` — libpq's own keyword, and a query
#: parameter name a caller can write — as innocent, because it is one word and
#: is not the word `password` (Copilot review of openDox-code#26, at
#: `555a03c8`). Six characters is the line: `password`, `passwd`, `secret`,
#: `token`, `credential`, `signature`, `apikey`, `api_key`, `access_token`,
#: `authorization` and `credentials` cannot appear inside an innocent
#: parameter name by accident, while the short ones that CAN — `key` in
#: `monkey`, `sig` in `sigma`, `auth` in `authority`, `pass` in `passage`,
#: `pwd` — stay whole-word.
_LONG_SECRET_NEEDLES = tuple(
    sorted((key for key in SECRET_PARAMETER_KEYS if len(key) >= 6), key=len))


def names_a_secret_parameter(name: str) -> bool:
    """True when a URL parameter's NAME is one of the credential names.

    WHOLE WORDS for the short needles, for the reason
    `_SECRET_PARAMETER_WORDS` gives above, and SUBSTRINGS for the long ones,
    for the reason `_LONG_SECRET_NEEDLES` gives. The decoded name is what is
    judged, because `%74oken` is `token`.

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
    if any(needle in spaced for needle in _LONG_SECRET_NEEDLES):
        return True
    return any(word in _SECRET_PARAMETER_WORDS
               for word in _WORD_SEPARATOR.split(spaced) if word)


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
    # AND THE TWO DSNs LAND IN ONE SCHEMA. See
    # `_refuse_two_dsns_that_select_different_schemas`: this is the half of
    # that invariant a string can answer, and it is asked here because this is
    # the one loader that holds BOTH values.
    _refuse_two_dsns_that_select_different_schemas(
        _require(env, _by_name(PREFIX + "DATABASE_URL")),
        _optional(env, _by_name(PREFIX + "MIGRATION_DATABASE_URL")))

    return RuntimeSettings(
        database_url=_require(env, _by_name(PREFIX + "DATABASE_URL")),
        migration_database_url=_optional(env, _by_name(PREFIX + "MIGRATION_DATABASE_URL")),
        oidc_issuer=_broker_url(env, _by_name(PREFIX + "OIDC_ISSUER"),
                                required=True, is_a_base_url=True) or "",
        oidc_audience=_require(env, _by_name(PREFIX + "OIDC_AUDIENCE")),
        oidc_jwks_url=_broker_url(env, _by_name(PREFIX + "OIDC_JWKS_URL"),
                                  required=False),
        oidc_algorithms=algorithms,
        oidc_jwks_ttl_seconds=_positive_int(env, _by_name(PREFIX + "OIDC_JWKS_TTL_SECONDS")),
        oidc_leeway_seconds=_positive_int(env, _by_name(PREFIX + "OIDC_LEEWAY_SECONDS")),
        bind_host=_optional(env, _by_name(PREFIX + "BIND_HOST")) or "127.0.0.1",
        bind_port=_positive_int(env, _by_name(PREFIX + "BIND_PORT")),
        runtime_pg_role=_role_name(env),
        served_schema=_served_schema(env),
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
        served_schema=_served_schema(env),
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
