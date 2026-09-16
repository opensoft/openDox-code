-- 0002 — the migration ledger, ADDITIVE, and the canonical reviewable copy of
-- the DDL the runner bootstraps.
--
-- WHY THE RUNNER ALSO CARRIES THIS DDL. Recording that migration 0001 was
-- applied needs the ledger table to already exist, so
-- `opendox.runtime.migrations.MigrationRunner` creates it with
-- `create table if not exists` BEFORE it applies anything. That copy lives in
-- `LEDGER_DDL` and this file is the reviewable one;
-- `tests_runtime/test_migration_shape.py::test_ledger_ddl_matches_this_file`
-- asserts the two are textually identical, so the bootstrap can never drift
-- into a shape no migration declares. The pattern, and the reason, are
-- `xFactory-Hermes-Install`'s (`persistence/migrations.py` "Ledger bootstrap",
-- `migrations/0005_migration_state.sql`); openDox takes the shape, at 0002,
-- because it has no provider schema to leave room for.
--
-- WHY IT IS A SEPARATE FILE AND NOT PART OF 0001. 0001 is byte-pinned
-- (`CANONICAL_MIGRATION_SHA256`) and the runner has to create the ledger
-- before it can verify or record anything, so a ledger inside 0001 would have
-- to be applied before 0001 was gated — the gate would be running after the
-- first mutation instead of before it.
--
-- `reversible` records whether a `<version>_<name>.down.sql` sidecar existed
-- when the migration was applied. openDox ships no down migration today; the
-- column is here because the runner computes the fact and a ledger that
-- silently dropped it would make a later reversal unauditable.

create table if not exists opendox_schema_migrations (
  version text primary key,
  name text not null,
  checksum text not null,
  reversible boolean not null default false,
  applied_at timestamptz not null default now()
);
