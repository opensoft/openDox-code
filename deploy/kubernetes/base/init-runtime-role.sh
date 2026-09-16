#!/bin/sh
# Create the LEAST-PRIVILEGED role the served application connects as, on the
# database's first start. Runs from `/docker-entrypoint-initdb.d/`, so it runs
# exactly once per data volume and never against an existing database.
#
# WHY TWO ROLES AT ALL. `opendox-runtime migrate` applies DDL and needs to own
# the schema; the served API needs to read and write six tables and must not be
# able to drop one. A single role makes the API's blast radius the whole
# schema for no benefit, and the compose file's separate `migrate` service
# exists precisely so the two identities are never in the same container.
#
# The runtime role is granted on the tables that EXIST at migration time and on
# everything created later by the migration owner (`alter default privileges`),
# so a 0003 that adds a table does not need this file edited.
#
# THE MIGRATION LEDGER IS THE ONE EXCEPTION, AND IT IS NARROWED ELSEWHERE.
# `opendox_schema_migrations` is the runner's tamper-evident record, and a
# served role that could INSERT, UPDATE or DELETE there could hide an applied
# migration or manufacture one — after which the fail-closed drift check would
# be checking a story the API wrote (Copilot review of openDox-code#25). This
# script cannot narrow it: it runs on the database's FIRST START, before any
# migration exists, so the default privileges above are all it can set. The
# narrowing belongs where the table is created and the privileged identity is
# already connected — `opendox-runtime migrate`, which runs
# `MigrationRunner.protect_ledger` when `OPENDOX_RUNTIME_PG_ROLE` names this
# role. SELECT is kept, because `/readyz` reads the ledger.
set -eu

if [ -z "${OPENDOX_RUNTIME_PG_PASSWORD:-}" ]; then
  echo "init-runtime-role: OPENDOX_RUNTIME_PG_PASSWORD is unset; refusing to" \
       "create a role with no password" >&2
  exit 1
fi

runtime_user="${OPENDOX_RUNTIME_PG_USER:-opendox_runtime}"

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
     -v runtime_user="$runtime_user" <<'SQL'
\getenv runtime_password OPENDOX_RUNTIME_PG_PASSWORD
select format('create role %I login password %L', :'runtime_user',
              :'runtime_password')
\gexec
select format('grant connect on database %I to %I', current_database(),
              :'runtime_user')
\gexec
select format('grant usage on schema public to %I', :'runtime_user')
\gexec
select format('grant select, insert, update, delete on all tables in schema '
              'public to %I', :'runtime_user')
\gexec
select format('alter default privileges in schema public grant select, '
              'insert, update, delete on tables to %I', :'runtime_user')
\gexec
SQL
