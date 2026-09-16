"""Bearer-token verification against the Keycloak broker, and the first-login
row it writes.

RULING Q2 (opensoft/openxFactory#656 comment 5542792997): "OIDC through the
Keycloak broker being adopted in QA". So this runtime is a VERIFIER and never
an issuer: it fetches the broker's published key set, checks the signature, the
pinned issuer, the pinned audience and the expiry, and mints nothing. It never
stores a raw token — `migrations/0001_…sql` has no column one could be stored
in, which is the honest place to enforce that.

DESIGN § D5's INVERSION IS REALIZED IN `principal_for`. "an account is a
durable row, authentication delegates to the Keycloak broker, and authorization
stops being a property of the request's origin. This is the largest conceptual
change in the rulings and the easiest to under-read." A verified token
therefore RESOLVES TO A ROW — upserted on first login — and every later
authorization question is asked about that row, never about where the request
came from. A loopback caller with no token is not privileged here.

THE SHAPE IS `xFactory-Hermes-Install`'s `authz/oidc.py` (RULING Q2), with the
three properties that file records and openDox needs unchanged:

  * **An asymmetric ALGORITHM ALLOW-LIST**, checked against the token header
    before verification, which is what defeats the classic `alg: none`
    downgrade. openDox refuses a symmetric algorithm one step EARLIER as well,
    at configuration time (`config.load_settings`), because a runtime
    configured to accept `HS256` would verify tokens signed with the public key
    anybody can fetch, and discovering that at the first request means it is
    already serving.
  * **A key-set cache on a MONOTONIC clock** with a refresh on `kid` miss, for
    key rotation. Monotonic and not wall time because this host's clock can
    step backwards, and a cache whose freshness depended on it would serve a
    stale key set for as long as the step.
  * **Typed, non-disclosing errors.** Every failure carries a stable machine
    `code` and never the token.

WHAT openDox DOES NOT TAKE from that file: its layer-scope claim and its scope
vocabulary. Hermes is a three-layer product and its tokens carry a layer;
openDox is single-layer, so a `layer` claim here would be a shape copied
without a meaning. Authorization in this runtime is `memberships.role` — a row,
per D5 — and the token's only job is to say WHO.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet

DEFAULT_JWKS_TIMEOUT_SECONDS = 5.0

#: How long a `kid` MISS is remembered before another outbound refresh is
#: allowed. Copilot's review of openDox-code#25 named the hole this closes,
#: critical and correct: without it every token carrying an unknown `kid`
#: forced an immediate fetch that bypassed the TTL, WHILE THE CACHE LOCK WAS
#: HELD — so a caller sending random `kid` headers turned one request into one
#: outbound broker request and serialized every other verification behind it.
#:
#: A miss still refreshes ONCE, which is what key rotation needs; what the
#: cooldown removes is the second, third and thousandth refresh in the same
#: few seconds. Short, because a rotation should be picked up in seconds, not
#: minutes — the cost of being wrong here is one extra fetch, and the cost of
#: having no cooldown is the broker taking the traffic.
DEFAULT_MISS_REFRESH_COOLDOWN_SECONDS = 10.0


class OidcError(Exception):
    """Base class for token-validation failures. Carries no secret material."""

    code = "auth.invalid_token"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class MalformedTokenError(OidcError):
    code = "auth.malformed_token"


class UnsupportedAlgorithmError(OidcError):
    code = "auth.unsupported_algorithm"


class InvalidSignatureError(OidcError):
    code = "auth.invalid_signature"


class InvalidIssuerError(OidcError):
    code = "auth.invalid_issuer"


class InvalidAudienceError(OidcError):
    code = "auth.invalid_audience"


class TokenExpiredError(OidcError):
    code = "auth.token_expired"


class MissingClaimError(OidcError):
    code = "auth.missing_claim"


class IdentityUnavailableError(OidcError):
    """The broker's signing keys could not be resolved."""

    code = "auth.identity_unavailable"


@dataclass(frozen=True)
class Claims:
    """The validated, non-secret claims of one access token.

    `raw` deliberately carries the subject and nothing else: a claims object
    reaches a log line the first time somebody debugs an authorization
    refusal, and a copy of the whole token payload is the wrong thing to have
    put there.
    """

    subject: str
    issuer: str
    audience: str
    email: str | None = None
    display_name: str | None = None
    expires_at: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class FileJwksSource:
    """Load a key set from a local file — tests and air-gapped installs."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IdentityUnavailableError(
                f"JWKS file could not be read at {self._path}") from exc
        if not isinstance(data, dict):
            raise IdentityUnavailableError("JWKS file did not parse to an object")
        return data


class HttpJwksSource:
    """Fetch the key set from the broker's published JWKS URL."""

    def __init__(self, url: str, *,
                 timeout: float = DEFAULT_JWKS_TIMEOUT_SECONDS) -> None:
        self._url = url
        self._timeout = timeout

    def load(self) -> dict[str, Any]:
        try:
            response = httpx.get(self._url, timeout=self._timeout)
            response.raise_for_status()
            data = response.json()
        # `ValueError` ALONE covers the JSON case: `json.JSONDecodeError` is a
        # subclass of it (measured), so naming both is redundant and reads as
        # if they were two different failures.
        except (httpx.HTTPError, ValueError) as exc:
            raise IdentityUnavailableError(
                "the broker's JWKS endpoint could not be fetched") from exc
        if not isinstance(data, dict):
            raise IdentityUnavailableError(
                "the broker's JWKS endpoint did not return an object")
        return data


class CachingJwks:
    """A key-set cache that refreshes on a MONOTONIC TTL and on a `kid` miss."""

    def __init__(self, source: FileJwksSource | HttpJwksSource, *,
                 ttl_seconds: int,
                 miss_cooldown_seconds: float =
                 DEFAULT_MISS_REFRESH_COOLDOWN_SECONDS) -> None:
        self._source = source
        self._ttl = ttl_seconds
        self._miss_cooldown = miss_cooldown_seconds
        self._lock = threading.Lock()
        self._keyset: PyJWKSet | None = None
        self._loaded_monotonic = 0.0
        self._last_miss_refresh = float("-inf")

    def _load_keyset(self) -> PyJWKSet:
        raw = self._source.load()
        try:
            return PyJWKSet.from_dict(raw)
        except (jwt.PyJWKError, jwt.PyJWKSetError, jwt.InvalidKeyError,
                KeyError, TypeError, AttributeError) as exc:
            # `PyJWKSetError` is NOT a subclass of `PyJWKError` and has to be
            # named separately — measured, not assumed: a broker serving
            # `{"keys": []}` (a realm mid-rotation, a misconfigured proxy)
            # raises it, and without this clause it would escape as an
            # untyped exception past the 401 mapping in `app.get_principal`
            # and surface as a 500.
            raise IdentityUnavailableError(
                "the broker's JWKS document could not be parsed") from exc

    def keyset(self, *, force_refresh: bool = False) -> PyJWKSet:
        now = time.monotonic()
        with self._lock:
            stale = (now - self._loaded_monotonic) >= self._ttl
            if force_refresh or self._keyset is None or stale:
                self._keyset = self._load_keyset()
                self._loaded_monotonic = now
            return self._keyset

    def select_key(self, kid: str | None) -> PyJWK:
        keyset = self.keyset()
        key = self._match(keyset, kid)
        if key is None and self._may_refresh_on_miss():
            # Key rotation: refresh ONCE, and at most once per cooldown — see
            # `DEFAULT_MISS_REFRESH_COOLDOWN_SECONDS` for the amplification
            # this bound removes.
            keyset = self.keyset(force_refresh=True)
            key = self._match(keyset, kid)
        if key is None:
            raise InvalidSignatureError("no broker signing key matched the token")
        return key

    def _may_refresh_on_miss(self) -> bool:
        """True at most once per cooldown, measured on the MONOTONIC clock.

        Under the same lock the cache uses, so two threads missing at once
        produce one refresh rather than two.
        """
        now = time.monotonic()
        with self._lock:
            if (now - self._last_miss_refresh) < self._miss_cooldown:
                return False
            self._last_miss_refresh = now
            return True

    @staticmethod
    def _match(keyset: PyJWKSet, kid: str | None) -> PyJWK | None:
        keys = list(keyset.keys)
        if not keys:
            return None
        if kid is None:
            # A token with no `kid` is only unambiguous where the broker
            # publishes exactly one key; guessing among several is how a
            # rotation becomes an outage nobody can explain.
            return keys[0] if len(keys) == 1 else None
        for key in keys:
            if key.key_id == kid:
                return key
        return None


class TokenVerifier:
    """Validate a bearer token against the pinned issuer, audience and keys."""

    def __init__(self, *, issuer: str, audience: str, jwks: CachingJwks,
                 algorithms: tuple[str, ...] = ("RS256",),
                 leeway_seconds: int = 60,
                 email_claim: str = "email",
                 name_claim: str = "name") -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks = jwks
        self._algorithms = tuple(algorithms)
        self._leeway = leeway_seconds
        self._email_claim = email_claim
        self._name_claim = name_claim

    @property
    def issuer(self) -> str:
        return self._issuer

    @property
    def audience(self) -> str:
        return self._audience

    def probe_keys(self) -> None:
        """Load the key set — the readiness probe; raises on unavailability."""
        self._jwks.keyset()

    def verify(self, token: str) -> Claims:
        """Return validated :class:`Claims`, or raise an :class:`OidcError`."""
        if not token or token.count(".") != 2:
            raise MalformedTokenError(
                "token is not a well-formed JWS compact serialization")

        # READING THE HEADER BEFORE VERIFYING IS NOT A MISSING CHECK, it is the
        # only possible order: the header carries the `kid` that selects the
        # signing key and the `alg` the allow-list is applied to, and neither
        # can be known until it is read. NOTHING from this header is trusted —
        # `alg` is checked against the allow-list below, and the signature is
        # verified against the broker's own key in `_decode`, which runs with
        # `verify_signature: True` and a required-claim list. The marker on the
        # call below suppresses `python:S5659` on that measurement — and it is
        # written only THERE, because a prose comment that spells the marker is
        # itself read as a malformed suppression (`python:S7632`, which is what
        # this act's first pass earned).
        try:
            header = jwt.get_unverified_header(token)  # NOSONAR
        except jwt.PyJWTError as exc:
            raise MalformedTokenError("token header could not be parsed") from exc

        alg = header.get("alg")
        if alg not in self._algorithms:
            raise UnsupportedAlgorithmError(
                f"token algorithm is not in the accepted set "
                f"{list(self._algorithms)}")

        signing_key = self._jwks.select_key(header.get("kid"))
        claims = self._decode(token, signing_key)

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise MissingClaimError("token has no usable subject claim")

        email = claims.get(self._email_claim)
        name = claims.get(self._name_claim)
        return Claims(
            subject=subject,
            issuer=str(claims.get("iss") or self._issuer),
            audience=self._audience,
            email=email if isinstance(email, str) and email else None,
            display_name=name if isinstance(name, str) and name else None,
            expires_at=claims.get("exp"),
            raw={"sub": subject},
        )

    def _decode(self, token: str, signing_key: PyJWK) -> dict[str, Any]:
        """`jwt.decode` with this runtime's pins, and its errors made ours.

        A METHOD OF ITS OWN because the mapping is seven clauses and `verify`
        is the readable part: with both in one body `verify`'s cognitive
        complexity was 17 (SonarCloud `python:S3776`, limit 15). The seven
        clauses are also exactly what a reader wants to read on its own — each
        turns a PyJWT exception into an `OidcError` subclass carrying a stable
        machine `code` and never the token.
        """
        try:
            return jwt.decode(
                token,
                key=signing_key.key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={
                    "require": ["exp", "iss", "aud", "sub"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("token has expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise InvalidIssuerError(
                "token issuer is not the pinned broker") from exc
        except jwt.InvalidAudienceError as exc:
            raise InvalidAudienceError(
                "token audience is not this runtime") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise MissingClaimError("token is missing a required claim") from exc
        except (jwt.InvalidSignatureError, jwt.InvalidAlgorithmError) as exc:
            raise InvalidSignatureError("token signature is invalid") from exc
        except jwt.PyJWTError as exc:
            raise OidcError("token could not be validated") from exc


def build_verifier(settings: Any) -> TokenVerifier:
    """The verifier one runtime process serves with, from its settings.

    Takes `config.RuntimeSettings` (typed loosely so this module never imports
    the config module and the two can be read in either order).
    """
    jwks = CachingJwks(HttpJwksSource(settings.jwks_url()),
                       ttl_seconds=settings.oidc_jwks_ttl_seconds)
    return TokenVerifier(issuer=settings.oidc_issuer,
                         audience=settings.oidc_audience,
                         jwks=jwks,
                         algorithms=tuple(settings.oidc_algorithms),
                         leeway_seconds=settings.oidc_leeway_seconds)


def principal_for(store: Any, claims: Claims) -> Any:
    """The DURABLE ROW a verified token resolves to (design § D5's inversion).

    Upserts on every login: the first one creates the account, later ones
    refresh what the broker last said about it and stamp `last_seen_at`. The
    returned `identity.User` — not the token, not the request's origin — is the
    subject of every authorization question this runtime asks.

    `store` is an `identity.CoordinationStore`; typed loosely for the same
    reason `build_verifier`'s argument is.
    """
    return store.upsert_user(issuer=claims.issuer, subject=claims.subject,
                             email=claims.email,
                             display_name=claims.display_name)
