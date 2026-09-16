"""Token verification against a locally generated key pair.

RULING Q2 (openxFactory#656 comment 5542792997) delegates authentication to the
Keycloak broker; this file is where that delegation is EXECUTED rather than
described. Every case runs the real `TokenVerifier` — the one `build_verifier`
constructs in production, differing only in where the key set comes from — so a
property proved here is a property the deployed runtime has.

These suites need `PyJWT[crypto]` and therefore run in the `runtime` CI job;
the required `validate` job installs `.[test]` alone. See `conftest.py` for the
in-fixture RSA key pair, the JWKS file and the token minter.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from opendox.runtime import oidc
from tests_runtime.conftest import TEST_AUDIENCE, TEST_ISSUER, TEST_KID


def test_a_well_formed_token_verifies_and_carries_the_brokers_claims(
        verifier, mint_token) -> None:
    claims = verifier.verify(mint_token(subject="student-1",
                                        email="s1@example.test",
                                        name="Student One"))
    assert claims.subject == "student-1"
    assert claims.issuer == TEST_ISSUER
    assert claims.audience == TEST_AUDIENCE
    assert claims.email == "s1@example.test"
    assert claims.display_name == "Student One"


def test_the_claims_object_carries_the_subject_and_not_the_payload(
        verifier, mint_token) -> None:
    """A claims object reaches a log line; a copy of the payload must not."""
    claims = verifier.verify(mint_token(some_private_claim="do-not-log-me"))
    assert claims.raw == {"sub": claims.subject}
    assert "do-not-log-me" not in repr(claims)


def test_a_token_from_another_issuer_is_refused(verifier, mint_token) -> None:
    with pytest.raises(oidc.InvalidIssuerError):
        verifier.verify(mint_token(issuer="https://someone-else/realms/x"))


def test_a_token_for_another_audience_is_refused(verifier, mint_token) -> None:
    """A token minted for another client of the SAME broker is not ours."""
    with pytest.raises(oidc.InvalidAudienceError):
        verifier.verify(mint_token(audience="some-other-client"))


def test_an_expired_token_is_refused(verifier, mint_token) -> None:
    with pytest.raises(oidc.TokenExpiredError):
        verifier.verify(mint_token(expires_in=-3600))


def test_a_token_signed_by_another_key_is_refused(verifier, mint_token) -> None:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    impostor = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode({"sub": "student-1", "iss": TEST_ISSUER,
                        "aud": TEST_AUDIENCE, "iat": now, "exp": now + 300},
                       impostor, algorithm="RS256", headers={"kid": TEST_KID})
    with pytest.raises(oidc.InvalidSignatureError):
        verifier.verify(token)


def test_an_unsigned_token_is_refused_before_verification(verifier) -> None:
    """The classic `alg: none` downgrade, refused by the allow-list."""
    import base64

    def _segment(payload: dict) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    now = int(time.time())
    token = ".".join([
        _segment({"alg": "none", "typ": "JWT"}),
        _segment({"sub": "attacker", "iss": TEST_ISSUER,
                  "aud": TEST_AUDIENCE, "exp": now + 300}),
        "",
    ])
    with pytest.raises(oidc.UnsupportedAlgorithmError):
        verifier.verify(token)


def test_a_symmetrically_signed_token_is_refused(verifier, mint_token) -> None:
    """HS256 signed with the broker's PUBLIC key — refused by the allow-list."""
    with pytest.raises(oidc.UnsupportedAlgorithmError):
        verifier.verify(mint_token(algorithm="HS256", kid=TEST_KID))


def test_a_malformed_token_is_refused_with_a_named_code(verifier) -> None:
    with pytest.raises(oidc.MalformedTokenError) as caught:
        verifier.verify("not-a-jwt")
    assert caught.value.code == "auth.malformed_token"


def test_a_token_naming_an_unknown_key_is_refused(verifier, mint_token) -> None:
    with pytest.raises(oidc.InvalidSignatureError):
        verifier.verify(mint_token(kid="a-key-the-broker-never-published"))


def test_an_unreachable_key_set_is_a_named_refusal_and_not_a_crash(
        tmp_path) -> None:
    source = oidc.FileJwksSource(tmp_path / "there-is-no-jwks-here.json")
    cache = oidc.CachingJwks(source, ttl_seconds=300)
    verifier = oidc.TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
                                  jwks=cache)
    with pytest.raises(oidc.IdentityUnavailableError) as caught:
        verifier.probe_keys()
    assert caught.value.code == "auth.identity_unavailable"


def test_the_key_set_is_cached_and_refreshed_on_a_monotonic_ttl(
        jwks_path: str) -> None:
    """Not on wall time: this host's clock can step backwards under load."""
    loads: list[int] = []

    class CountingSource:
        def load(self) -> dict:
            loads.append(1)
            return json.loads(Path(jwks_path).read_text(encoding="utf-8"))

    cache = oidc.CachingJwks(CountingSource(), ttl_seconds=3600)
    cache.keyset()
    cache.keyset()
    assert len(loads) == 1, "a second read inside the TTL refetched the key set"
    cache.keyset(force_refresh=True)
    assert len(loads) == 2, "a forced refresh did not refetch"


def test_a_rotated_key_is_found_after_one_refresh(jwks_path: str,
                                                  mint_token) -> None:
    """A `kid` miss refreshes ONCE before giving up — key rotation, not outage.

    The cache is primed with a key set carrying only the PREVIOUS key, which is
    what a broker mid-rotation serves; the token names the new `kid`, the
    select misses, and the one forced refresh is what finds it.
    """
    current = json.loads(Path(jwks_path).read_text(encoding="utf-8"))
    previous = {"keys": [dict(current["keys"][0], kid="the-previous-key")]}
    state = {"served": previous}

    class RotatingSource:
        def load(self) -> dict:
            return state["served"]

    cache = oidc.CachingJwks(RotatingSource(), ttl_seconds=3600)
    verifier = oidc.TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
                                  jwks=cache)
    cache.keyset()                       # primes the cache with the old key set
    state["served"] = current
    claims = verifier.verify(mint_token(subject="rotated"))
    assert claims.subject == "rotated"


def test_an_empty_key_set_is_a_named_refusal_and_not_a_crash() -> None:
    """A realm mid-rotation can serve `{"keys": []}`; PyJWT raises for it.

    `PyJWKSetError` is not a `PyJWKError`, so it has to be caught by name or it
    escapes past `app.get_principal`'s 401 mapping and surfaces as a 500 —
    measured here rather than assumed.
    """

    class EmptySource:
        def load(self) -> dict:
            return {"keys": []}

    cache = oidc.CachingJwks(EmptySource(), ttl_seconds=300)
    with pytest.raises(oidc.IdentityUnavailableError) as caught:
        cache.keyset()
    assert caught.value.code == "auth.identity_unavailable"


def test_first_login_writes_the_durable_row_and_later_logins_refresh_it(
        store, verifier, mint_token) -> None:
    """Design § D5's inversion, executed.

    "an account is a durable row, authentication delegates to the Keycloak
    broker, and authorization stops being a property of the request's origin."
    """
    first = oidc.principal_for(
        store, verifier.verify(mint_token(subject="student-2",
                                          email="s2@example.test",
                                          name="Student Two")))
    assert first.issuer == TEST_ISSUER
    assert first.subject == "student-2"
    assert first.email == "s2@example.test"

    again = oidc.principal_for(
        store, verifier.verify(mint_token(subject="student-2",
                                          email="s2-new@example.test",
                                          name="Student Two")))
    assert again.id == first.id, "a second login must not mint a second account"
    assert again.email == "s2-new@example.test"
    assert again.last_seen_at >= first.last_seen_at


def test_two_issuers_are_two_people_even_with_the_same_subject(
        store, jwks_path: str, mint_token) -> None:
    """`subject` is unique only WITHIN an issuer — the schema's natural key."""
    other_issuer = "https://broker.test/realms/other"
    here = oidc.TokenVerifier(
        issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
        jwks=oidc.CachingJwks(oidc.FileJwksSource(jwks_path), ttl_seconds=300))
    there = oidc.TokenVerifier(
        issuer=other_issuer, audience=TEST_AUDIENCE,
        jwks=oidc.CachingJwks(oidc.FileJwksSource(jwks_path), ttl_seconds=300))
    one = oidc.principal_for(store, here.verify(mint_token(subject="collide")))
    two = oidc.principal_for(
        store, there.verify(mint_token(subject="collide", issuer=other_issuer)))
    assert one.id != two.id
