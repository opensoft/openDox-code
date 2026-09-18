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

#: How long the connectivity probe waits before calling the server unreachable.
#: Short on purpose: this runs once per session and its whole job is to turn a
#: developer's stopped container into one skip line instead of a wall of
#: connection errors.
PROBE_TIMEOUT_SECONDS = 5

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


def in_ci() -> bool:
    """Whether this run is CI's, by CI's own variable.

    GitHub Actions sets `CI=true` in every job (and so does every other runner
    this estate uses), which is the one signal that does not require the suite
    to know whose CI it is.
    """
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes", "on"}


def _redacted_dsn(dsn: str) -> str:
    """The DSN with everything but its destination removed.

    Not `local_git_adapter.redact_credentials`: this file is `conftest.py` and
    runs before the package is necessarily importable — the very failure this
    is reporting can be an ImportError. So it is written here, small and
    stdlib-only, and it keeps ONLY what an operator needs to know which server
    was asked: scheme, host and port for a URI, `host=`/`port=` for the
    keyword/value form. Everything else, including any parameter this does not
    recognize, is dropped rather than shown.
    """
    import urllib.parse

    try:
        split = urllib.parse.urlsplit(dsn)
    except ValueError:
        return "<the configured DSN>"
    if split.scheme and split.hostname:
        # BRACKETS KEPT FOR AN IPv6 LITERAL, which this act has been wrong
        # about before: `::1` unbracketed is not the host it names.
        host = (f"[{split.hostname}]" if ":" in split.hostname
                else split.hostname)
        port = f":{split.port}" if split.port else ""
        return f"{split.scheme}://{host}{port}/<redacted>"
    kept = [part for part in dsn.split()
            if part.split("=", 1)[0] in ("host", "port", "hostaddr")]
    return " ".join(kept) if kept else "<the configured DSN>"


def _skip_or_fail(reason: str) -> None:
    """A developer's skip is CI's FAILURE, and that asymmetry is the point.

    Skipping where there is no Postgres is right for a developer and wrong for
    the `runtime` job: pytest exits 0 when every collected case is skipped, so
    a job whose `postgres:16` service failed to start went GREEN while running
    no database-backed assertion at all — reporting the opposite of what the
    workflow's own comment claims about it (Copilot review of openDox-code#25).
    The job exists to supply that service, so its absence there is a defect in
    the job and is reported as one.
    """
    if in_ci():
        pytest.fail(
            "CI is set, so the DB-backed runtime suites must RUN and not skip: "
            "the `runtime` job supplies a `postgres:16` service and this is "
            "what its absence looks like. " + reason, pytrace=False)
    pytest.skip(reason)


def _import_psycopg():
    """`psycopg`, or the same asymmetry: a developer skips, CI fails."""
    try:
        import psycopg
    except ImportError as exc:
        _skip_or_fail(
            "the `runtime` extra is not installed "
            f"(pip install -e '.[runtime,test]'): {exc}")
        raise                       # unreachable: `_skip_or_fail` always raises
    return psycopg


@pytest.fixture(scope="session")
def postgres_dsn() -> str:
    """The DSN, PROBED — an unreachable one skips, it does not fail.

    The variable being ABSENT was the only skip at first, and the module, the
    runbook and the PR all promised a skip "whenever Postgres is unreachable"
    (Copilot review of openDox-code#25, and it was right). A developer with a
    stale or stopped container therefore got a wall of connection errors from a
    promise that said otherwise. The probe below is bounded — one connection
    attempt with a short timeout — and its failure is a skip that NAMES the DSN
    host and the error, so "skipped" never means "nobody knows why".

    AND IN CI IT IS NOT A SKIP AT ALL — it is a FAILURE, through
    `_skip_or_fail`. The sentence here used to say "a skip there would be a
    real failure of that job's own setup", which was true of the intent and
    false of the code: pytest exits 0 when every collected case is skipped, so
    a `runtime` job whose `postgres:16` service failed to start reported GREEN
    while running no database-backed assertion (Copilot review of
    openDox-code#25). The job supplies the service; its absence there is the
    job's defect and is reported as one.
    """
    dsn = os.environ.get(TEST_DSN_ENV, "").strip()
    if not dsn:
        _skip_or_fail(_SKIP_REASON)
    psycopg = _import_psycopg()
    try:
        with psycopg.connect(dsn, connect_timeout=PROBE_TIMEOUT_SECONDS) as conn:
            conn.execute("select 1")
    except Exception as exc:  # noqa: BLE001
        # THE EXCEPTION'S TYPE, NOT ITS TEXT, and the reproducer is exact.
        # `str(exc)` was copied into a reason that pytest prints in the CI log
        # of a job whose DSN carries a password (Copilot review of
        # openDox-code#25, round 26). MEASURED against psycopg 3 / libpq on a
        # DSN reading `postgresql://opendox:hunter2@[::1/opendox` — an
        # unbracketed IPv6 host, which is the ordinary way to mis-set this
        # variable:
        #
        #   ProgrammingError: end of string reached when looking for matching
        #   "]" in IPv6 host address in URI:
        #   "postgresql://opendox:hunter2@[::1/opendox"
        #
        # The password is in that line. Four other forms were measured and do
        # not leak (a refused connection, an unknown URI parameter, an unknown
        # keyword/value option, the keyword/value form refused): libpq quotes
        # the whole conninfo when it cannot PARSE it, which is exactly the case
        # an operator hits by typo. The type is what makes the skip diagnosable
        # (`OperationalError` vs `ImportError` vs a timeout) and it carries no
        # value; the destination is rebuilt by `_redacted_dsn` from the
        # environment's own DSN, so an operator still learns which server did
        # not answer.
        _skip_or_fail(
            f"{TEST_DSN_ENV} is set and the server did not answer within "
            f"{PROBE_TIMEOUT_SECONDS}s: {type(exc).__name__} for "
            f"{_redacted_dsn(dsn)}. The DB-backed runtime suites did not run.")
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
                # ISOLATION, ASSERTED BEFORE ANYTHING IS CREATED. `search_path`
                # is `<schema>,public`, so a schema that does not exist is not
                # an error — every `create table` simply lands in `public`
                # instead, and the suite then pollutes the shared database and
                # the NEXT test sees an already-migrated ledger through the
                # search path. Measured, not hypothetical: it happened once in
                # this act's own development, and this is the assertion that
                # makes it a failure at the fixture instead of a mystery three
                # tests later.
                with db.connection() as conn:
                    current = conn.execute("select current_schema()").fetchone()
                assert current and current[0] == schema, (
                    f"the test schema {schema} is not the current schema "
                    f"({current}); writes would land in `public`")
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
    """The in-fixture key pair — CI-AWARE, like the DSN probe above.

    `pytest.importorskip` here was not: a `cryptography` that is installed and
    cannot be imported skipped every OIDC and API case that depends on this
    fixture, and the `runtime` job then passed having exercised only the
    migrations and the shape checks (Copilot review of openDox-code#25, round
    6). Same policy, same reason: a developer skips, CI fails.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError as exc:
        _skip_or_fail(
            "the `runtime` extra is not installed "
            f"(pip install -e '.[runtime,test]'): {exc}")
        raise                       # unreachable: `_skip_or_fail` always raises

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
