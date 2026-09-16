"""Postgres connectivity: a pooled, injectable `Database` and nothing else.

THE ONLY MODULE IN THIS PACKAGE THAT IMPORTS A DATABASE DRIVER, on purpose.
`opendox.runtime.migrations` and `opendox.runtime.identity` take a connection
and a connection-provider respectively, so both import under the leg's
`validate` check (which installs `.[test]`, not `.[runtime]`); this module is
where `psycopg` is finally required, and it is imported at CALL time by
`app.py` and `cli.py` rather than at their import. See the import-weight
contract in `opendox/runtime/__init__.py`.

The shape is `xFactory-Hermes-Install`'s `persistence/database.py` (RULING Q2),
including the two decisions that file records and the reasons it records them
for:

  * **The pool is opened lazily and by the caller**, never at import, so
    importing the ASGI entrypoint never touches the database. The application's
    lifespan opens it.
  * **Session settings are libpq connection PARAMETERS, not a `configure`
    callback.** A callback running SQL under `autocommit=False` leaves a pooled
    connection `INTRANS` and the pool discards it; `options` applies the
    setting at startup instead.

NO BUSINESS RULE LIVES HERE. Coordination is `identity.CoordinationStore`'s;
this module owns the pool and the unit of work.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

#: The `application_name` every pooled connection reports, so a DBA reading
#: `pg_stat_activity` can tell the runtime's connections from a migration job's.
APPLICATION_NAME = "opendox-runtime"

#: How long a caller waits for a pooled connection before the wait becomes a
#: failure. BOUNDED, and bounded by this module rather than by psycopg's
#: default, because the callers differ: a request handler that waits thirty
#: seconds has already lost, and `opendox-runtime status` waiting thirty
#: seconds to report "unreachable" is a diagnostic nobody runs twice. Each
#: caller passes its own; this is the value a served request uses.
DEFAULT_CHECKOUT_TIMEOUT_SECONDS = 10.0


def utcnow() -> datetime:
    """The single source of application-side timestamps, always UTC-aware.

    Every timestamp column in the canonical schema is `timestamptz` and
    defaults to the SERVER's `now()`; this exists for the few places the
    application needs a comparable instant of its own.
    """
    return datetime.now(tz=UTC)


class Database:
    """A thin, injectable wrapper around a psycopg connection pool."""

    def __init__(self, conninfo: str, *, schema: str | None = None,
                 min_size: int = 1, max_size: int = 8,
                 application_name: str = APPLICATION_NAME,
                 checkout_timeout: float = DEFAULT_CHECKOUT_TIMEOUT_SECONDS) -> None:
        self._conninfo = conninfo
        self._schema = schema
        self._application_name = application_name
        self._checkout_timeout = checkout_timeout

        kwargs: dict[str, object] = {
            "autocommit": False,
            "application_name": application_name,
        }
        if schema is not None:
            # A server-side startup setting rather than a `configure` callback;
            # see the module docstring. The schema is an install-generated safe
            # identifier (the test harness's per-test schema), never user input.
            kwargs["options"] = f"-c search_path={schema},public"

        self._pool = ConnectionPool(conninfo=conninfo, min_size=min_size,
                                    max_size=max_size, open=False, kwargs=kwargs)

    @property
    def schema(self) -> str | None:
        return self._schema

    def open(self) -> None:
        self._pool.open()

    def close(self) -> None:
        self._pool.close()

    def __enter__(self) -> Database:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[Any]]:
        """Check out a connection; its transaction commits or rolls back with it."""
        with self._pool.connection(timeout=self._checkout_timeout) as conn:
            yield conn

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection[Any]]:
        """Check out a connection inside an EXPLICIT transaction (unit of work).

        Every call made with the yielded connection participates in one atomic
        transaction — which is what makes the repository-creation act's three
        rows (project, membership, map) commit or fail together.
        """
        with self._pool.connection(timeout=self._checkout_timeout) as conn, \
                conn.transaction():
            yield conn
