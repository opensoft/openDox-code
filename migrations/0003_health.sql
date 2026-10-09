-- 0003 — the health store: one table of runs and one of findings, ADDITIVE.
--
-- WHY `0003_` AND NOT `0002_` (#1144 box 14.1): `0002_migration_state.sql`
-- is the ledger, and `0001` is applied verbatim behind
-- `CANONICAL_MIGRATION_SHA256`, so its header's own rule applies: "Changing
-- the schema is therefore an ADDITIVE `0002_…`/`0003_…` file, never an edit
-- here". `0001`'s header still names six tables, and it stays as written,
-- because its bytes are the pin.
--
-- DOMAIN TABLES, DECLARED IN THE OPEN (#1144 box 14.2; R2Q13 (a), Brett Heap,
-- opensoft/openxFactory#656 comment 6003486656). Ruling 5784155201 item 4
-- reads "health results become a seventh table … with the closure test moved
-- in the SAME change", and that is this change: `identity.TABLES` names both
-- tables below, `tests_runtime/test_schema_shape.py` reads `0001` with this
-- file, and `verify_runtime_access` measures the served role's rights on them
-- exactly as it does on the other six (`SERVED_TABLES` is `identity.TABLES`).
--
-- NO DOCUMENT, AND THE STORE STAYS DISPOSABLE (box 14.3; RULING Q1's
-- principle; R2Q25 (a)). A finding ADDRESSES a document (`path`, a display
-- `locator`) and never carries its text: there is NO patch column (lane 3's
-- MISLABEL row 31; OQ-H15-20 as refined: a pack's patch is re-obtained at
-- `fix`, never stored), and `evidence` holds locators only. Every row here is
-- recomputable from git, so `runtime reset` drops these tables with the six
-- and a reset costs a recomputation (`runtime/cli.py`, `DROP_ORDER`).
--
-- PROVENANCE IS NOT NULL FROM THE FIRST LANDING (box 15.7): `pack_id` and
-- `pack_version` are `not null`, and not empty, so no path can store a finding
-- without them. "Not empty" is spelled `length(…) > 0` rather than `<> ''`,
-- which means the same in PostgreSQL but reads as a null comparison to
-- analyzers that apply Oracle's rule that `''` is null. That is enforced HERE, at the store, and not only in the
-- engine that stamps them.
--
-- NO FOREIGN KEY TO `projects` (OQ-H-22): a run is keyed by the corpus's
-- resolved root, because F14.1 runs `health` over a corpus no project row
-- names.
--
-- THE COLUMN `full_run` IS data-model.md's FIELD `full`. PostgreSQL 16 lists
-- `full` as a TYPE_FUNC_NAME_KEYWORD, which a column definition's name cannot
-- be; a quoted `"full"` would be legal SQL and a trap in every statement that
-- forgot the quotes. Holder ruling, opensoft/openxFactory#656 comment
-- 6064169640: the model's field stays `full`, its SQL column is `full_run`.
--
-- RUNS ARE ORDERED BY `run_seq`, NOT BY A CLOCK. The baseline is "the latest
-- earlier default-tip run" of a corpus (R2Q12 (a)), and `0001`'s header
-- records why this host's ordering must not be wall time: the clock "can step
-- backwards under load". `run_id` is a uuid (data-model.md) and so orders
-- nothing; `run_seq` is an identity column the server hands out at insert, so
-- the order is the order runs were recorded in. `started_at` and
-- `finished_at` are what the run reports, for display, and deliberately carry
-- no ordering constraint for the same reason.
--
-- `identity` IS TEXT HOLDING CANONICAL SORTED-KEY JSON (the holder,
-- opensoft/openxFactory#656 comment 6018624750): the position-independent key
-- the engine hashes into `id`, stored byte for byte as it was hashed and
-- emitted by `health list --json`. `jsonb` would re-order and re-space it.
-- Its serialized-size cap is the engine's, T041's, in the contract module,
-- and deliberately NOT a constraint here: the store stores what the contract
-- bounds. Likewise every other field bound (the id grammar, `message`'s 200
-- characters, a key named `excerpt`) belongs to the contract module; this file
-- holds the closed vocabularies and the shapes the data model fixes.
--
-- A COMMIT IS 40 LOWERCASE HEX DIGITS, held by ONE check. `commit` is null
-- exactly for a working-state run, and otherwise equals `export_commit`
-- (data-model.md: "`commit` for a default-tip or branch run"), so the
-- `export_commit` form check holds `commit` too; a second check on `commit`
-- could never be the one that refuses a row.
--
-- `sandbox` IS `{"live": bool, "pids_max": int or null}` (data-model.md), and
-- an int here is a NON-NEGATIVE WHOLE number: a fraction or a negative count of
-- processes is no bound the probe can have found (lane 3's REVIEW-W1 of T042).
-- The check is a CASE so that the numeric cast is reached only for a JSON
-- number: SQL does not promise to evaluate an AND's operands in order.
--
-- EVERY STORED FINDING CARRIES ITS BASELINE CLASS (`baseline_class not
-- null`). R2Q12 (a) rules exactly three classes and I-2 (a) rules out a
-- fourth, and a null would be that fourth ("unclassed") by another name: the
-- engine classes a run's findings against the store before it records them,
-- so a row without a class is a row the engine never classed.
--
-- THE HOSTED PLANE MIGRATES THIS FILE TOO (R2Q15 (a)): there is one
-- migration set. The hosted plane refuses the `health` verbs and routes by
-- name and records nothing, so its tables stay empty.

create table health_runs (
  run_id           uuid primary key,
  run_seq          bigint not null generated always as identity,
  corpus_root      text not null,
  kind             text not null,
  commit           text,
  baseline_branch  text,
  started_at       timestamptz not null,
  finished_at      timestamptz not null,
  outcome          text not null,
  pack_pins        jsonb not null,
  export_commit    text not null,
  full_run         boolean not null,
  sandbox          jsonb not null,
  constraint health_runs_run_seq_key unique (run_seq),
  constraint health_runs_kind_check check (kind in ('default-tip', 'branch', 'working-state')),
  constraint health_runs_outcome_check check (outcome in ('complete', 'partial', 'refused')),
  constraint health_runs_commit_check check ((kind = 'working-state') = (commit is null)),
  constraint health_runs_export_commit_hex_check check (export_commit ~ '^[0-9a-f]{40}$'),
  constraint health_runs_export_commit_check check (commit is null or export_commit = commit),
  constraint health_runs_default_tip_branch_check check (kind <> 'default-tip' or baseline_branch is not null),
  constraint health_runs_pack_pins_check check (jsonb_typeof(pack_pins) = 'object' and pack_pins ? 'opendox'),
  constraint health_runs_sandbox_check check (coalesce(jsonb_typeof(sandbox -> 'live'), 'absent') = 'boolean' and case jsonb_typeof(sandbox -> 'pids_max') when 'null' then true when 'number' then (sandbox ->> 'pids_max')::numeric >= 0 and (sandbox ->> 'pids_max')::numeric = trunc((sandbox ->> 'pids_max')::numeric) else false end)
);

create table health_findings (
  run_id            uuid not null references health_runs (run_id) on delete cascade,
  id                text not null,
  kind              text not null,
  pack_id           text not null,
  pack_version      text not null,
  path              text not null,
  identity          text not null,
  locator           jsonb,
  severity          text not null,
  resolution_class  text not null,
  baseline_class    text not null,
  message           text not null,
  evidence          jsonb not null,
  constraint health_findings_pkey primary key (run_id, id),
  constraint health_findings_pack_id_check check (length(pack_id) > 0),
  constraint health_findings_pack_version_check check (length(pack_version) > 0),
  constraint health_findings_identity_check check (jsonb_typeof(identity::jsonb) = 'object'),
  constraint health_findings_locator_check check (locator is null or jsonb_typeof(locator) = 'object'),
  constraint health_findings_severity_check check (severity in ('error', 'warning', 'info')),
  constraint health_findings_resolution_class_check check (resolution_class in ('auto-fix', 'assisted', 'human-only')),
  constraint health_findings_baseline_class_check check (baseline_class in ('new', 'pack-upgrade', 'persistent')),
  constraint health_findings_evidence_check check (jsonb_typeof(evidence) = 'object')
);

-- The one lookup every reader makes: a corpus's runs, newest first.
create index health_runs_corpus_root_run_seq_idx on health_runs (corpus_root, run_seq);
