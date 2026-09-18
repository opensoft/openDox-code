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
    token = mint_token(issuer="https://someone-else/realms/x")
    with pytest.raises(oidc.InvalidIssuerError):
        verifier.verify(token)


def test_a_token_for_another_audience_is_refused(verifier, mint_token) -> None:
    """A token minted for another client of the SAME broker is not ours."""
    token = mint_token(audience="some-other-client")
    with pytest.raises(oidc.InvalidAudienceError):
        verifier.verify(token)


def test_an_expired_token_is_refused(verifier, mint_token) -> None:
    token = mint_token(expires_in=-3600)
    with pytest.raises(oidc.TokenExpiredError):
        verifier.verify(token)


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
    token = mint_token(algorithm="HS256", kid=TEST_KID)
    with pytest.raises(oidc.UnsupportedAlgorithmError):
        verifier.verify(token)


def test_a_malformed_token_is_refused_with_a_named_code(verifier) -> None:
    with pytest.raises(oidc.MalformedTokenError) as caught:
        verifier.verify("not-a-jwt")
    assert caught.value.code == "auth.malformed_token"


def test_a_token_naming_an_unknown_key_is_refused(verifier, mint_token) -> None:
    token = mint_token(kid="a-key-the-broker-never-published")
    with pytest.raises(oidc.InvalidSignatureError):
        verifier.verify(token)


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


# -- the review round's own assertions (Copilot review of openDox-code#25) ---


def test_an_unknown_kid_refreshes_once_and_then_stops_hammering_the_broker(
        jwks_path: str) -> None:
    """Amplification, bounded.

    Every unknown `kid` used to force an immediate fetch that bypassed the TTL
    while the cache lock was held, so a caller sending random `kid` headers
    turned one request into one outbound broker request and serialized every
    other verification behind it. A miss still refreshes ONCE — key rotation
    needs that — and the cooldown removes the second, third and thousandth
    refresh in the same few seconds.
    """
    loads: list[int] = []
    document = json.loads(Path(jwks_path).read_text(encoding="utf-8"))

    class CountingSource:
        def load(self) -> dict:
            loads.append(1)
            return document

    cache = oidc.CachingJwks(CountingSource(), ttl_seconds=3600,
                             miss_cooldown_seconds=60.0)
    cache.keyset()
    assert len(loads) == 1

    for _ in range(50):
        with pytest.raises(oidc.InvalidSignatureError):
            cache.select_key("a-kid-nobody-published")
    assert len(loads) == 2, (
        f"{len(loads) - 1} outbound refreshes for 50 unknown-kid lookups; the "
        "cooldown allows exactly one")


def test_the_cooldown_expires_so_a_real_rotation_is_still_picked_up(
        jwks_path: str, mint_token) -> None:
    """A bound that never expired would be an outage, not a defence."""
    current = json.loads(Path(jwks_path).read_text(encoding="utf-8"))
    previous = {"keys": [dict(current["keys"][0], kid="the-previous-key")]}
    state = {"served": previous}

    class RotatingSource:
        def load(self) -> dict:
            return state["served"]

    # A zero cooldown is the limit case of "the cooldown has expired".
    cache = oidc.CachingJwks(RotatingSource(), ttl_seconds=3600,
                             miss_cooldown_seconds=0.0)
    verifier = oidc.TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
                                  jwks=cache)
    cache.keyset()
    state["served"] = current
    assert verifier.verify(mint_token(subject="rotated-late")).subject == (
        "rotated-late")


def test_one_ttl_boundary_causes_one_jwks_refresh_and_not_one_per_waiter(
        jwks_path: str) -> None:
    """`now` was read BEFORE the lock and carried through the wait.

    A caller that arrives WHILE another is fetching therefore re-evaluated
    staleness against a clock from before that fetch — and the stamp it then
    wrote was that same pre-fetch reading, so the next waiter's own older
    clock was stale against it too. Each waiter in the queue refreshed the
    JWKS in turn, serially, and the single refresh the cache exists to make
    became one refresh PER WAITER at exactly the moment the broker is busiest
    (Copilot review of openDox-code#25, round 5).

    MEASURED WITH STAGGERED ARRIVALS, and the stagger is the whole test: eight
    threads that all read the clock at the same instant cannot tell the two
    shapes apart (they share one `now`, so even the old code refreshed once),
    which is how the first cut of this test passed against the defect. They
    arrive one TTL apart instead, inside a fetch long enough to hold them all.
    """
    import threading
    import time

    from opendox.runtime.oidc import CachingJwks, FileJwksSource

    ttl = 0.05
    fetch_seconds = 1.0
    waiters = 6
    stagger = 0.08                   # > ttl, so every arrival is "stale" to the
                                     # pre-lock clock the old shape read

    class _Counting(FileJwksSource):
        # `load`, which is the source protocol's one method — an override of a
        # `fetch` this class does not have would have counted nothing.
        def __init__(self, path: str) -> None:
            super().__init__(path)
            self.loads = 0

        def load(self) -> dict:
            self.loads += 1
            time.sleep(fetch_seconds)
            return super().load()

    source = _Counting(jwks_path)
    cache = CachingJwks(source, ttl_seconds=ttl)
    cache.keyset()                                    # the first load
    assert source.loads == 1
    time.sleep(ttl * 2)                               # every reader is now stale

    errors: list[BaseException] = []

    def _read() -> None:
        try:
            cache.keyset()
        except BaseException as exc:                  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_read) for _ in range(waiters)]
    for thread in threads:
        thread.start()
        time.sleep(stagger)
    for thread in threads:
        thread.join()

    assert errors == []
    assert source.loads == 2, (
        f"{source.loads - 1} refreshes for one TTL boundary; the cache is "
        "amplifying broker traffic instead of absorbing it")


# -- Copilot's ninth round on #25 --------------------------------------------


def test_the_miss_cooldown_is_measured_against_the_serialized_decision(
        jwks_path: str) -> None:
    """The cooldown's clock was read BEFORE the lock, like the TTL's was.

    A caller that waits on the lock longer than the cooldown carried its
    pre-lock `now` through the wait and was then refused a refresh the
    cooldown had in fact already allowed — so a real key rotation arriving
    while another thread held the lock (a forced refresh holds it for a whole
    fetch) went unseen until the NEXT miss (Copilot review of openDox-code#25,
    round 9). The decision is serialized; the reading it is made against has
    to be the serialized one.

    MEASURED ON `_may_refresh_on_miss` DIRECTLY, and deliberately: the defect
    is a property of what that method reads and when, and the scheduling that
    exposes it through `select_key` cannot be forced from outside. Holding the
    cache's own lock for longer than the cooldown IS the condition, stated
    once.
    """
    import threading
    import time

    from opendox.runtime.oidc import CachingJwks, FileJwksSource

    cooldown = 0.1
    cache = CachingJwks(FileJwksSource(jwks_path), ttl_seconds=3600,
                        miss_cooldown_seconds=cooldown)
    assert cache._may_refresh_on_miss() is True          # stamps the clock
    assert cache._may_refresh_on_miss() is False         # inside the cooldown

    holding = threading.Event()
    release = threading.Event()

    def _hold_the_lock() -> None:
        with cache._lock:
            holding.set()
            release.wait(5)

    holder = threading.Thread(target=_hold_the_lock)
    holder.start()
    holding.wait(5)
    answer: list[bool] = []

    def _ask() -> None:
        answer.append(cache._may_refresh_on_miss())

    asker = threading.Thread(target=_ask)
    asker.start()
    time.sleep(cooldown * 3)          # the wait outlives the cooldown
    release.set()
    for thread in (asker, holder):
        thread.join(5)

    assert answer == [True], (
        "the refresh was refused against a clock read before the wait; a key "
        "rotation that arrives while the lock is held goes unseen")


# -- Copilot's tenth round on #25: the key-set source is a contract, not a union


def test_any_object_with_load_is_a_jwks_source_and_the_cache_takes_it(
        jwks_path: str) -> None:
    """`CachingJwks` was annotated with the two classes this module ships.

    Neither the cache nor the suites ever needed more than `load()` — the
    rotation and counting sources in this very file are third implementations,
    and a deployment reading its key set from a secret store would be a fourth.
    A union of concrete classes therefore said a false thing about the surface
    and made every legitimate source a type error (Copilot review of
    openDox-code#25, round 10). `JwksSource` is the contract, `runtime_checkable`
    so the annotation and `isinstance` ask the same question.
    """
    import inspect

    class _FromAnywhere:
        """Not a subclass of either shipped source — just `load()`."""

        def __init__(self, document: dict) -> None:
            self._document = document
            self.loads = 0

        def load(self) -> dict:
            self.loads += 1
            return self._document

    document = json.loads(Path(jwks_path).read_text(encoding="utf-8"))
    source = _FromAnywhere(document)
    assert isinstance(source, oidc.JwksSource)
    assert isinstance(oidc.FileJwksSource(jwks_path), oidc.JwksSource)

    cache = oidc.CachingJwks(source, ttl_seconds=300)
    assert cache.keyset().keys, "the cache did not accept a conformant source"
    assert source.loads == 1

    annotation = inspect.signature(oidc.CachingJwks.__init__).parameters[
        "source"].annotation
    assert annotation == "JwksSource", (
        f"the declared surface is {annotation!r}, not the contract the cache "
        "actually asks for")


def test_an_object_without_load_is_not_a_jwks_source() -> None:
    """The contract has a member, so it can be failed as well as kept."""

    class _NotASource:
        def fetch(self) -> dict:                       # the wrong spelling
            return {"keys": []}

    assert not isinstance(_NotASource(), oidc.JwksSource)


# -- Copilot's fifteenth round on #25 ----------------------------------------


def test_a_thread_denied_by_the_cooldown_re_reads_before_it_refuses(
        jwks_path: str, mint_token, monkeypatch: pytest.MonkeyPatch) -> None:
    """The cooldown denies exactly the thread that is waiting for the answer.

    Two valid requests arrive during one rotation. Both read the OLD key set
    and miss; one claims the miss refresh and fetches; the other is refused a
    refresh by the cooldown — and used to raise `InvalidSignatureError` against
    the key set it was already holding, for a token whose new `kid` had arrived
    by the time the request was handled (Copilot review of openDox-code#25,
    round 15, suppressed). The cooldown is the right bound on FETCHES; it was
    being used as a bound on ANSWERS.

    `keyset()` takes the same lock the refresh holds, so a denied thread now
    waits for the fetch in flight and reads its result. It fetches nothing
    itself, so the amplification bound is untouched — asserted below by the
    load count.

    THE ORDER IS FORCED, not raced: the denied thread is held between its read
    of the old key set and its cooldown question, which is the only window in
    which the defect exists. A thread that arrives LATER blocks on the lock and
    gets the new key set from the cache, which is why an unordered version of
    this case passes against the previous head.
    """
    import threading

    current = json.loads(Path(jwks_path).read_text(encoding="utf-8"))
    previous = {"keys": [dict(current["keys"][0], kid="the-previous-key")]}
    state = {"served": previous, "loads": 0}
    fetching = threading.Event()
    release = threading.Event()
    denied_has_the_old_set = threading.Event()
    refresh_claimed = threading.Event()

    class BlockingSource:
        def load(self) -> dict:
            state["loads"] += 1
            if state["loads"] > 1:       # the priming read returns at once
                fetching.set()
                release.wait(5)
            return state["served"]

    cache = oidc.CachingJwks(BlockingSource(), ttl_seconds=3600)
    verifier = oidc.TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
                                  jwks=cache)
    cache.keyset()                       # primes with the OLD key set
    state["served"] = current            # the broker rotates

    real_match = oidc.CachingJwks._match          # a staticmethod

    # THE THIRD ARGUMENT IS THE ALGORITHM, which `select_key` passes since the
    # key-type binding (A25-2): a stub with the old arity raised `TypeError`
    # inside the thread and the event this case waits on never fired.
    def _match_holding_the_denied_thread(keyset, kid, alg=None):
        found = real_match(keyset, kid, alg)
        if found is None and threading.current_thread().name == "denied":
            denied_has_the_old_set.set()
            refresh_claimed.wait(5)
        return found

    monkeypatch.setattr(oidc.CachingJwks, "_match",
                        staticmethod(_match_holding_the_denied_thread))

    token = mint_token(subject="rotated")
    outcome: dict[str, object] = {}

    def _verify(name: str) -> None:
        try:
            outcome[name] = verifier.verify(token).subject
        except Exception as exc:         # noqa: BLE001 - reported, not raised
            outcome[name] = exc

    denied = threading.Thread(target=_verify, args=("denied",), name="denied")
    denied.start()
    assert denied_has_the_old_set.wait(5), "the denied thread never missed"

    refresher = threading.Thread(target=_verify, args=("refresher",),
                                 name="refresher")
    refresher.start()
    assert fetching.wait(5), "the refresh this case needs never started"
    refresh_claimed.set()                # the denied thread asks the cooldown
    time.sleep(0.05)                     # ... and is now waiting on the lock
    release.set()
    for thread in (denied, refresher):
        thread.join(5)

    assert outcome["refresher"] == "rotated", outcome
    assert outcome["denied"] == "rotated", (
        "a valid token was refused because another thread was already "
        f"fetching the key set it needed: {outcome['denied']!r}")
    # AND THE COOLDOWN'S OWN BOUND IS UNTOUCHED: one priming read and one
    # refresh, not two.
    assert state["loads"] == 2, state


def test_the_cooldown_claim_and_the_refresh_are_one_lock_acquisition(
        jwks_path: str, mint_token, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-reading after a denial narrowed the window; it did not close it.

    The claim and the fetch were two acquisitions, so a denied thread could
    leave the lock and read the cache BEFORE the claiming thread had taken it
    to fetch — and reject a valid token carrying the newly rotated `kid`
    against the key set it already had (Copilot review of openDox-code#25,
    round 16). Holding the lock across the claim AND the fetch closes it.

    The case drives exactly that window: the claiming thread is paused between
    its claim and its fetch, and the denied thread runs during the pause. It
    hooks whichever method the shape under test claims the cooldown in, so it
    runs against both — against the previous head the denied thread is refused
    with `InvalidSignatureError`, because there the pause is OUTSIDE the lock.
    """
    import threading

    current = json.loads(Path(jwks_path).read_text(encoding="utf-8"))
    previous = {"keys": [dict(current["keys"][0], kid="the-previous-key")]}
    state = {"served": previous, "loads": 0}

    class Source:
        def load(self) -> dict:
            state["loads"] += 1
            return state["served"]

    cache = oidc.CachingJwks(Source(), ttl_seconds=3600)
    verifier = oidc.TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
                                  jwks=cache)
    cache.keyset()                       # primes with the OLD key set
    state["served"] = current            # the broker rotates

    claimed = threading.Event()
    denied_ran = threading.Event()
    # The shape under test: the coupled claim, or the older standalone one.
    hook = ("_claim_refresh_locked"
            if hasattr(oidc.CachingJwks, "_claim_refresh_locked")
            else "_may_refresh_on_miss")
    real_claim = getattr(oidc.CachingJwks, hook)

    def _claim_then_pause(self, *args, **kwargs):
        allowed = real_claim(self, *args, **kwargs)
        if allowed:
            claimed.set()
            denied_ran.wait(5)           # the window, forced open
        return allowed

    monkeypatch.setattr(oidc.CachingJwks, hook, _claim_then_pause)

    token = mint_token(subject="rotated")
    outcome: dict[str, object] = {}

    def _verify(name: str) -> None:
        try:
            outcome[name] = verifier.verify(token).subject
        except Exception as exc:         # noqa: BLE001 - reported, not raised
            outcome[name] = exc

    claimer = threading.Thread(target=_verify, args=("claimer",))
    claimer.start()
    assert claimed.wait(5), "the claim this case needs never happened"

    denied = threading.Thread(target=_verify, args=("denied",))
    denied.start()
    time.sleep(0.05)                     # it is inside the window now
    denied_ran.set()
    for thread in (claimer, denied):
        thread.join(5)

    assert outcome["claimer"] == "rotated", outcome
    assert outcome["denied"] == "rotated", (
        "a valid token was refused inside the window between the cooldown "
        f"claim and the refresh it claims: {outcome['denied']!r}")
    assert state["loads"] == 2, state    # one priming read, one refresh


def test_a_failed_key_set_load_is_not_retried_once_per_request(
        monkeypatch) -> None:
    """A broker outage costs ONE fetch per cooldown, not one per request.

    THE FINDING (Copilot review of openDox-code#25, round 27): when
    `_load_keyset()` raises, the assignment to `_keyset` never completes and
    `_loaded_monotonic` is unchanged — so before the first successful load, or
    after a TTL refresh fails, every authenticated request re-enters the
    refresh branch and performs another fetch. Each one waits the source's
    whole timeout WITH THE CACHE LOCK HELD, so a broker outage serializes one
    outbound request per inbound request until the worker pool is spent. The
    miss cooldown does not bound it: that one is claimed on a `kid` miss.

    FAIL-CLOSED IS PRESERVED, and this test is where that is stated: every
    call below still RAISES. The cooldown replaces a fetch with the failure
    that fetch produced; it never serves a key set, so a stale set is not used
    past its TTL and a broker that is down cannot be made to look up.

    Against the previous head the first assertion reads 5, not 1.
    """
    clock = [1000.0]
    monkeypatch.setattr(oidc.time, "monotonic", lambda: clock[0])

    class _Down:
        calls = 0

        def load(self):
            _Down.calls += 1
            raise oidc.IdentityUnavailableError(
                "the broker's JWKS endpoint could not be fetched")

    source = _Down()
    cache = oidc.CachingJwks(source, ttl_seconds=3600,
                             failed_refresh_cooldown_seconds=10.0)

    for _ in range(5):
        with pytest.raises(oidc.IdentityUnavailableError):
            cache.keyset()
    assert _Down.calls == 1, (
        f"the outage was fetched {_Down.calls} times in one cooldown; the "
        f"cache lock is held across each one")

    # THE COOLDOWN EXPIRES and exactly one more fetch is made.
    clock[0] += 10.0
    with pytest.raises(oidc.IdentityUnavailableError):
        cache.keyset()
    assert _Down.calls == 2

    # AND A MISS DOES NOT BUY A WAY AROUND IT: `keyset_after_miss` claims its
    # own cooldown and then goes through the same refresh.
    clock[0] += 1.0
    with pytest.raises(oidc.IdentityUnavailableError):
        cache.keyset_after_miss()
    assert _Down.calls == 2


def test_a_recovered_broker_is_used_at_once_and_not_after_the_cooldown(
        jwks_path: str, monkeypatch) -> None:
    """The negative cache is cleared by the success that ends the outage.

    A remembered failure that outlived its cause would turn a 5-second blip
    into a 10-second outage for every caller, which is the opposite of the
    property the cooldown is for.
    """
    clock = [1000.0]
    monkeypatch.setattr(oidc.time, "monotonic", lambda: clock[0])
    real = json.loads(Path(jwks_path).read_text(encoding="utf-8"))

    class _Flaky:
        up = False
        calls = 0

        def load(self):
            _Flaky.calls += 1
            if not _Flaky.up:
                raise oidc.IdentityUnavailableError("down")
            return real

    cache = oidc.CachingJwks(_Flaky(), ttl_seconds=3600,
                             failed_refresh_cooldown_seconds=10.0)
    with pytest.raises(oidc.IdentityUnavailableError):
        cache.keyset()

    _Flaky.up = True
    clock[0] += 10.0                       # the cooldown, and not a second more
    assert cache.keyset().keys, "the recovered broker was not used"
    assert _Flaky.calls == 2

    # And the cleared failure does not come back: a later TTL refresh that
    # succeeds is not charged a cooldown it never earned.
    clock[0] += 3600.0
    assert cache.keyset().keys
    assert _Flaky.calls == 3


def test_a_jwks_file_that_is_not_utf8_is_a_typed_refusal(tmp_path) -> None:
    """The air-gapped path's failure is `IdentityUnavailableError`, not a 500.

    THE FINDING (Copilot review of openDox-code#25, round 29, previously
    missed): `read_text(encoding="utf-8")` raises `UnicodeDecodeError`, which
    is a `ValueError` and NOT a `json.JSONDecodeError` — so it escaped the
    handler that exists to make this class's failures typed, and a malformed
    key set surfaced as a 500 instead of the readiness or authentication
    refusal the callers map. Measured before the fix: `UnicodeDecodeError:
    'utf-8' codec can't decode byte 0xff in position 10`.

    `ValueError` is the base of both, which is the same rule `HttpJwksSource`
    already states one class below for its own JSON case.
    """
    bad = tmp_path / "jwks.json"
    bad.write_bytes(b'{"keys": [\xff\xfe]}')
    with pytest.raises(oidc.IdentityUnavailableError) as caught:
        oidc.FileJwksSource(bad).load()
    assert not isinstance(caught.value, UnicodeDecodeError)
    assert str(bad) in str(caught.value), (
        "the refusal must name the file an operator has to fix")

    # The neighbouring failures this handler already covered, still typed.
    missing = tmp_path / "absent.json"
    with pytest.raises(oidc.IdentityUnavailableError):
        oidc.FileJwksSource(missing).load()
    not_json = tmp_path / "not.json"
    not_json.write_text("{oops", encoding="utf-8")
    with pytest.raises(oidc.IdentityUnavailableError):
        oidc.FileJwksSource(not_json).load()
    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(oidc.IdentityUnavailableError):
        oidc.FileJwksSource(not_object).load()


def test_a_kid_naming_a_key_of_the_wrong_type_is_refused_and_not_a_crash(
        rsa_key_pair, tmp_path: Path) -> None:
    """Selecting by `kid` alone reached the cryptography backend with the wrong key.

    A broker realm publishing an RSA and an EC signing key is what Keycloak
    publishes the moment a realm has an ES256 provider beside the default RS256
    one, and both `kid`s are public facts from the unauthenticated JWKS
    endpoint. A token whose header is `{"alg": "RS256", "kid": "<the EC key's
    kid>"}` passed the algorithm allow-list, selected the EC key by `kid`, and
    PyJWT's `RSAAlgorithm.prepare_key` answered with a plain
    `TypeError("Expecting a PEM-formatted key.")` — NOT a `PyJWTError` — which
    escaped `_decode`'s seven typed clauses, escaped `verify`, and escaped
    `app.get_principal`. The payload need not verify and need not be
    well-formed past the header (independent adversarial review of
    openDox-code#25, A25-2).

    MEASURED, PyJWT 2.14.0: `RSAAlgorithm(SHA256).prepare_key(<EC public key>)`
    raises `builtins.TypeError: Expecting a PEM-formatted key.`
    """
    import json
    import time

    import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from jwt.algorithms import ECAlgorithm, RSAAlgorithm

    private, public = rsa_key_pair
    ec_private = ec.generate_private_key(ec.SECP256R1())

    rsa_jwk = json.loads(RSAAlgorithm.to_jwk(public))
    rsa_jwk.update({"kid": "rsa-1", "use": "sig", "alg": "RS256"})
    ec_jwk = json.loads(ECAlgorithm.to_jwk(ec_private.public_key()))
    ec_jwk.update({"kid": "ec-1", "use": "sig", "alg": "ES256"})
    path = tmp_path / "two-types.json"
    path.write_text(json.dumps({"keys": [rsa_jwk, ec_jwk]}), encoding="utf-8")

    verifier = oidc.TokenVerifier(
        issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
        jwks=oidc.CachingJwks(oidc.FileJwksSource(str(path)), ttl_seconds=300))

    now = int(time.time())
    forged = jwt.encode(
        {"sub": "anyone", "iss": TEST_ISSUER, "aud": TEST_AUDIENCE,
         "iat": now, "exp": now + 300},
        private, algorithm="RS256", headers={"kid": "ec-1"})

    with pytest.raises(oidc.OidcError) as caught:
        verifier.verify(forged)
    # A TYPED refusal, and specifically not a `TypeError`: the point of the
    # finding is that an untyped exception reached the ASGI layer.
    assert isinstance(caught.value, oidc.InvalidSignatureError)
    assert not isinstance(caught.value, TypeError)

    # THE HONEST KEY STILL VERIFIES, so the type binding is a binding and not
    # a refusal of the whole two-key key set.
    honest = jwt.encode(
        {"sub": "student-1", "iss": TEST_ISSUER, "aud": TEST_AUDIENCE,
         "iat": now, "exp": now + 300},
        private, algorithm="RS256", headers={"kid": "rsa-1"})
    assert verifier.verify(honest).subject == "student-1"

    # AND THE SELECTION ITSELF IS WHERE THE BINDING IS MADE, which is what
    # keeps the cryptography backend from ever seeing the wrong key.
    cache = oidc.CachingJwks(oidc.FileJwksSource(str(path)), ttl_seconds=300)
    assert cache.select_key("ec-1", "ES256").key_id == "ec-1"
    assert cache.select_key("rsa-1", "RS256").key_id == "rsa-1"
    with pytest.raises(oidc.InvalidSignatureError):
        cache.select_key("ec-1", "RS256")
    # A `kid`-less token is now unambiguous where the ALGORITHM picks one key
    # out of a key set holding two types — which it was not before.
    assert cache.select_key(None, "RS256").key_id == "rsa-1"
    # An algorithm family this runtime does not know carries no key at all,
    # rather than being assumed to fit the first one published.
    with pytest.raises(oidc.InvalidSignatureError):
        cache.select_key(None, "XX256")


def test_no_untyped_exception_can_leave_the_decoder(verifier, mint_token,
                                                    monkeypatch) -> None:
    """The second wall: a future PyJWT shape cannot reopen A25-2.

    The selection above no longer hands over a key of the wrong type, so this
    drives the escape directly — `jwt.decode` raising a builtin, which is what
    the cryptography backend does — and asserts it still leaves as an
    `OidcError`, with the library's own text not repeated.
    """
    import jwt

    def raising(*args: object, **kwargs: object) -> dict[str, object]:
        raise TypeError("Expecting a PEM-formatted key.")

    monkeypatch.setattr(jwt, "decode", raising)
    with pytest.raises(oidc.OidcError) as caught:
        verifier.verify(mint_token())
    assert isinstance(caught.value, oidc.InvalidSignatureError)
    assert "TypeError" in str(caught.value)
    assert "PEM" not in str(caught.value)
    assert caught.value.__cause__ is None
