#!/bin/sh
# Create the LEAST-PRIVILEGED role the served application connects as, on the
# database's first start. Runs from `/docker-entrypoint-initdb.d/`, so it runs
# exactly once per data volume and never against an existing database.
#
# WHY TWO ROLES AT ALL. `opendox-runtime runtime migrate` applies DDL and needs to own
# the schema; the served API needs to read and write six tables and must not be
# able to drop one. A single role makes the API's blast radius the whole
# schema for no benefit, and the compose file's separate `migrate` service
# exists precisely so the two identities are never in the same container.
#
# The runtime role is granted on the tables that EXIST at migration time and on
# everything created later by the migration owner (`alter default privileges`),
# so a 0003 that adds a table does not need this file edited.
#
# AND `alter default privileges` IS AIMED AT THE MIGRATION OWNER BY NAME.
# Default privileges belong to the role that CREATES the object, and this
# script runs as `$POSTGRES_USER`; the migration service's DSN is configured
# separately and may authenticate as a different owner. In that valid
# configuration `0001` created the six tables owned by that role, with no
# default privilege for the served one — the Job succeeded, `/readyz` reported
# an applied schema, and every API query failed `permission denied` (Copilot
# review of openDox-code#25, round 12). `OPENDOX_MIGRATION_PG_USER` names that
# owner, defaulting to `$POSTGRES_USER` (the bundled single-owner shape, which
# is what compose and the StatefulSet ship). The role must already exist —
# `ON_ERROR_STOP=1` makes a name nobody created a loud first-start failure
# rather than a silent absence of grants — and `MigrationRunner.
# verify_runtime_access` asks Postgres at the end of every run whether the
# served role can actually use what was applied, so a mismatch that reaches a
# migration fails the migration instead of the first request.
#
# THE MIGRATION LEDGER IS THE ONE EXCEPTION, AND IT IS NARROWED ELSEWHERE.
# `opendox_schema_migrations` is the runner's tamper-evident record, and a
# served role that could INSERT, UPDATE or DELETE there could hide an applied
# migration or manufacture one — after which the fail-closed drift check would
# be checking a story the API wrote (Copilot review of openDox-code#25). This
# script cannot narrow it: it runs on the database's FIRST START, before any
# migration exists, so the default privileges above are all it can set. The
# narrowing belongs where the table is created and the privileged identity is
# already connected — `opendox-runtime runtime migrate`, which runs
# `MigrationRunner.protect_ledger` when `OPENDOX_RUNTIME_PG_ROLE` names this
# role. SELECT is kept, because `/readyz` reads the ledger.
set -eu

if [ -z "${OPENDOX_RUNTIME_PG_PASSWORD:-}" ]; then
  echo "init-runtime-role: OPENDOX_RUNTIME_PG_PASSWORD is unset; refusing to" \
       "create a role with no password" >&2
  exit 1
fi

runtime_user="${OPENDOX_RUNTIME_PG_USER:-opendox_runtime}"
migration_owner="${OPENDOX_MIGRATION_PG_USER:-$POSTGRES_USER}"

# AND THE MIGRATION OWNER HAS TO EXIST, because `alter default privileges for
# role %I` names it and this script creates only the SERVED role. Documented as
# an alternate owner, `OPENDOX_MIGRATION_PG_USER` set to a role nobody had
# provisioned made that statement fail under `ON_ERROR_STOP=1` on a fresh
# volume — the stack could not initialize, and the message was PostgreSQL's
# rather than one naming the variable (Copilot review of openDox-code#25,
# round 30). The bundled path does not create it: an alternate owner is
# externally provisioned, with its own credential, which is what this refusal
# says.
if ! psql -tAqX --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      -v owner="$migration_owner" \
      -c "select 1 from pg_roles where rolname = :'owner'" | grep -q '^1$'; then
  echo "init-runtime-role: OPENDOX_MIGRATION_PG_USER names '$migration_owner'," \
       "which this database does not have. The bundled first start creates the" \
       "SERVED role only; an alternate migration owner is provisioned" \
       "externally, with its own credential, before this container starts." >&2
  exit 1
fi

# THE PASSWORD IS NEVER AN ARGUMENT. `-v runtime_password=…` puts it in
# `psql`'s argv, where `ps`, `/proc/<pid>/cmdline` and any host tooling that
# reads process tables can see it — for the whole life of the command, on a
# host the operator may not be alone on (Copilot review of openDox-code#25,
# round 11). `\getenv` reads it from psql's OWN ENVIRONMENT instead, which this
# script already has it in; the role NAME stays an argument because a name is
# not a secret. Measured against psql 16 before it was written here: the
# variable is set, `%L` quotes it, and the role is created with that password.
psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v runtime_user="$runtime_user" \
     -v migration_owner="$migration_owner" <<'SQL'
\getenv runtime_password OPENDOX_RUNTIME_PG_PASSWORD
select format('create role %I login password %L', :'runtime_user',
              :'runtime_password')
\gexec
select format('grant connect on database %I to %I', current_database(),
              :'runtime_user')
\gexec
select format('grant usage on schema public to %I', :'runtime_user')
\gexec
-- THE COORDINATION TABLES THAT ALREADY EXIST, and only those. A database
-- migrated before this prerequisite ran already holds them, and a `grant … on
-- table` for one that is absent is an error — so the list is a JOIN against
-- the catalogue rather than seven statements, and it emits NOTHING on a fresh
-- database. It used to read `on all tables in schema public`, which on a
-- REUSED database handed the served role another application's data (Copilot
-- review of openDox-code#25, round 30). The names are Q1's six plus the
-- ledger; `tests_runtime/test_deploy_shape.py` derives them from
-- `identity.TABLES` and `migrations.LEDGER_TABLE` so this list cannot drift.
select format('grant select, insert, update, delete on table %I to %I',
              c.relname, :'runtime_user')
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r'
   and c.relname = any (array['drafts', 'memberships',
                              'opendox_schema_migrations',
                              'project_repositories', 'projects', 'sessions',
                              'users'])
\gexec

-- NO `GRANT … ON ALL TABLES IN SCHEMA public`, deliberately. It used to be
-- here, and on a REUSED or managed database it handed the served role
-- select/insert/update/delete on every table that schema already held —
-- another application's data, which the migration preflight explicitly
-- tolerates being there (Copilot review of openDox-code#25, round 30). It was
-- not even doing the job it looked like it was doing: at first start the six
-- coordination tables DO NOT EXIST YET, so that grant could only ever reach
-- tables this install did not create.
--
-- The `alter default privileges` below is the whole grant, and it is exactly
-- the narrow one: every table the MIGRATION OWNER creates from here on, which
-- is the six and the ledger and nothing else. MEASURED on postgres 16.15 —
-- with the broad grant removed, a table created afterwards by the owner
-- carries `DELETE, INSERT, SELECT, UPDATE` for the served role, and a table
-- created by anybody else carries none.
select format('alter default privileges for role %I in schema public grant '
              'select, insert, update, delete on tables to %I',
              :'migration_owner', :'runtime_user')
\gexec
SQL
