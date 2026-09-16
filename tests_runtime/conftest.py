"""Fixtures for the DB-backed half of `tests_runtime/`.

WHY THIS FILE IS NOT READ BY THE REQUIRED CHECK. The leg's `validate` job runs
its pytest step with `--noconftest` — the root `conftest.py`'s `collect_ignore`
and `tests/conftest.py`'s autouse fixtures are both written for a tree that can
import `opendox.serve`, and until the BUILD arc repairs that, a file named in
that job has to stand on its own. The `runtime` job runs WITHOUT `--noconftest`
and is the only reader of this file, so the hermetic modules never depend on a
fixture and the DB-backed ones never repeat the harness.

SKIPPED, NEVER FAILED, WHERE THERE IS NO POSTGRES — and the skip SAYS SO. A
suite that silently passed without a database would advertise coverage that is
not running; a suite that failed would make every developer without a local
Postgres look at a red tree that is telling them nothing. `pytest.skip` with
the reason printed is the third answer, and it is the one the estate already
uses for the node-driven probes ("skipped, never failed, where node is
absent").

EACH TEST GETS ITS OWN SCHEMA on a shared server, which is the Hermes install's
harness shape: `Database(schema=…)` sets `search_path` as a libpq connection
parameter, so the migrations create the six tables inside that schema and the
teardown drops it whole. Two tests cannot see each other's rows and neither can
see anything a previous run left.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

#: The DSN the DB-backed tests connect with. A DEDICATED variable and not
#: `OPENDOX_DATABASE_URL`: a test run that silently reached a developer's real
#: runtime database and created and dropped schemas in it would be a harness
#: nobody could trust twice.
TEST_DSN_ENV = "OPENDOX_TEST_DATABASE_URL"

_SKIP_REASON = (
    f"{TEST_DSN_ENV} is not set, so the DB-backed runtime suites did not run. "
    "Start one and export it, e.g.\n"
    "  docker run -d --name opendox-test-pg -e POSTGRES_USER=opendox "
    "-e POSTGRES_PASSWORD=opendox -e POSTGRES_DB=opendox -p 55432:5432 "
    "postgres:16\n"
    f"  export {TEST_DSN_ENV}="
    "'postgresql://opendox:opendox@127.0.0.1:55432/opendox'\n"
    "CI runs them in the `runtime` job, which supplies a `postgres:16` service."
)


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    dsn = os.environ.get(TEST_DSN_ENV, "").strip()
    if not dsn:
        pytest.skip(_SKIP_REASON)
    pytest.importorskip(
        "psycopg",
        reason="the `runtime` extra is not installed: pip install -e '.[runtime,test]'")
    return dsn


@pytest.fixture
def database(postgres_dsn: str) -> Iterator[object]:
    """A `Database` on a throwaway schema, with the migrations already applied."""
    from opendox.runtime.db import Database
    from opendox.runtime.migrations import MigrationRunner

    schema = "t_" + uuid.uuid4().hex[:12]
    admin = Database(postgres_dsn, application_name="opendox-test-admin")
    with admin:
        with admin.transaction() as conn:
            # The schema name is generated here from a uuid, never from input.
            conn.execute(f"create schema {schema}")
        db = Database(postgres_dsn, schema=schema,
                      application_name="opendox-test")
        try:
            with db:
                MigrationRunner(db, migrations_dir="migrations").apply()
                yield db
        finally:
            with admin.transaction() as conn:
                conn.execute(f"drop schema if exists {schema} cascade")


@pytest.fixture
def store(database: object) -> Iterator[object]:
    """A `CoordinationStore` over one transaction, rolled back at teardown."""
    from opendox.runtime.identity import CoordinationStore

    with database.connection() as conn:  # type: ignore[attr-defined]
        yield CoordinationStore(conn)


# ---------------------------------------------------------------------------
# a LOCAL broker: an RSA key pair, a JWKS file, and a token minter
#
# The suites verify against the REAL `TokenVerifier` over a key set generated
# in-fixture, so every property they assert — the signature, the pinned issuer,
# the pinned audience, the expiry, the algorithm allow-list — is the property
# the deployed runtime has. A stub verifier would assert the tests' own
# arithmetic instead. `FileJwksSource` exists for exactly this, and for an
# air-gapped install; no network is reached.
# ---------------------------------------------------------------------------

TEST_ISSUER = "https://broker.test/realms/opendox"
TEST_AUDIENCE = "opendox-runtime"
TEST_KID = "test-key-1"


@pytest.fixture(scope="session")
def rsa_key_pair() -> tuple[object, object]:
    pytest.importorskip(
        "cryptography",
        reason="the `runtime` extra is not installed: pip install -e '.[runtime,test]'")
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


@pytest.fixture(scope="session")
def jwks_path(rsa_key_pair: tuple[object, object], tmp_path_factory) -> str:
    import json

    from jwt.algorithms import RSAAlgorithm

    _private, public = rsa_key_pair
    jwk = json.loads(RSAAlgorithm.to_jwk(public))
    jwk.update({"kid": TEST_KID, "use": "sig", "alg": "RS256"})
    path = tmp_path_factory.mktemp("broker") / "jwks.json"
    path.write_text(json.dumps({"keys": [jwk]}), encoding="utf-8")
    return str(path)


@pytest.fixture
def mint_token(rsa_key_pair: tuple[object, object]):
    """Mint a token the local broker would have issued."""
    import time

    import jwt

    private, _public = rsa_key_pair

    def _mint(*, subject: str = "student-1", issuer: str = TEST_ISSUER,
              audience: str = TEST_AUDIENCE, expires_in: int = 300,
              algorithm: str = "RS256", kid: str | None = TEST_KID,
              **claims: object) -> str:
        now = int(time.time())
        payload: dict[str, object] = {
            "sub": subject, "iss": issuer, "aud": audience,
            "iat": now, "exp": now + expires_in, **claims,
        }
        # The symmetric branch exists only so a suite can prove the allow-list
        # refuses HS256. The secret is 32+ bytes so PyJWT does not also warn
        # about its length and bury the assertion under a warning.
        key = (private if algorithm.startswith(("RS", "PS"))
               else "a-shared-secret-of-at-least-32-bytes")
        headers = {"kid": kid} if kid else None
        return jwt.encode(payload, key, algorithm=algorithm, headers=headers)

    return _mint


@pytest.fixture
def verifier(jwks_path: str):
    """The real `TokenVerifier` over the local key set."""
    from opendox.runtime.oidc import CachingJwks, FileJwksSource, TokenVerifier

    return TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE,
                         jwks=CachingJwks(FileJwksSource(jwks_path),
                                          ttl_seconds=300))
