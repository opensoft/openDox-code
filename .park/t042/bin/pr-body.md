Lane: openxfactory-4 (openXfactory-4-openDox_extraction)

**T042 (plan 038, HA-1): the health store, `0003_`, one owner.** New `migrations/0003_health.sql` (`health_runs`, `health_findings`), new `runtime/health_store.py`, the two tables in `identity.TABLES`, `DROP_ORDER` and the reset wording, both role-init scripts, `docs/runtime.md`, and the five `tests_runtime/` suites `0003_` moves, plus the new `tests_runtime/test_health_store.py`.

Arc: neutral-product-standalone-operability

**Lands after T027 (Brett, 6035546708)**: "Write now, land after T027 (Recommended)"; the holder's claim `6035574389`. Brett's later word, recorded at #656 `6073187085`, is "Green now, land after T027 (Recommended)": every gate is finished now, and this PR stays a frozen DRAFT until T027 has pinned phase 4's openDox-code commit (N-6 (a)). It then merges `main` and is reviewed again at its final head.

- **Realizes**: 14.1, 14.2, 14.3, 15.7 (part: the columns).
- **Falsifier**: new `tests_runtime/test_health_store.py`, carrying `test_the_store_refuses_a_finding_without_provenance` and a test that an install-level finding (`pack_id` `opendox`, empty `path`) is admitted; the five suites above.
- **Ruled**: R2Q13, R2Q15, R2Q25; the holder's `6018624750` and `6028364555` (items 1 and 2: the byte-identical `RESET_CONFIRMATION`, and `docs/runtime.md` with `RULED_TABLES` as R2-INV-P5 words them), as tasks.md's T042 Ruled line has it. Also the holder's:
  - `6064169640` (the SQL column is `full_run`);
  - `6069024023` item 3 (`run_seq` ACCEPTED);
  - `6069024568` item 3 (`tests_runtime/test_api_endpoints.py` admitted for one edit);
  - `6072086385` items 2 and 4 (`run_seq`'s catalog pin; the store refuses U+0000);
  - `6081875839` (FIX-NOW: a cyclic or over-deep value is a `RefusedError` naming the field, never `RecursionError`);
  - `6086098003` item 3 (c) (U+0000 in EVERY text parameter the store binds is a `RefusedError` naming the column, never the driver's `DataError`).
  **Decisions**: OQ-H-22, OQ-H15-18, -19, -20.

## What it does

- **`0003_health.sql`** is additive. `0001` is byte-pinned and keeps its header; this file's header says why, cites every ruling, and declares the two tables DOMAIN (14.2, R2Q13 (a)).
  - **`health_runs`**: the columns of data-model.md § Health run.
    - `full` is spelled `full_run`, because PostgreSQL 16 reserves `full` (holder `6064169640`).
    - `run_seq` is added (see *For the holder*).
    - CHECKs hold the closed vocabularies (run kind, outcome) and the shapes the data model fixes:
      - `commit` is null exactly for a working-state run, and otherwise equals `export_commit`, which is 40 lowercase hex digits;
      - a default-tip run names its baseline branch;
      - `pack_pins` is an object that includes `opendox`;
      - `sandbox` is an object whose `live` is a boolean and whose `pids_max` is a non-negative whole number or null.
  - **`health_findings`**: the columns of data-model.md § Finding.
    - `pack_id` and `pack_version` are NOT NULL and non-empty (`length(…) > 0`) from this first landing (15.7).
    - `identity` is TEXT holding canonical sorted-key JSON (holder `6018624750`), with no size cap in SQL; the cap is T041's.
    - Severity, resolution class (14.6: "in the store … alike") and baseline class are CHECKed.
    - The primary key is `(run_id, id)`, and the foreign key to the run cascades on delete.
    - There is **NO patch column** (14.3; R2Q25 (a)) and no foreign key to `projects` (OQ-H-22).
  - The hosted plane migrates it too (R2Q15 (a)).
- **`runtime/health_store.py`**:
  - It imports no driver, stdlib plus `identity` only, so it reaches the database lazily, through the connection a caller hands it, as `identity.py` does. JSON travels as `%s::jsonb` text.
  - `record_run` refuses BEFORE any statement:
    - a finding without provenance (15.7);
    - any field outside the columns, by name: a `patch`, `text` or `excerpt` is refused, never dropped (14.3);
    - naive timestamps;
    - non-object `identity`, `evidence` or `locator`;
    - a value it cannot keep, named by its field and quoting nothing: U+0000 anywhere (`6072086385` item 4), a lone surrogate (U+D800 to U+DFFF; Copilot at `01f4192d`), a value that contains itself, or one nested deeper than `MAX_JSON_DEPTH` (64) levels (`6081875839`). One ITERATIVE walk finds all three. It keeps only the containers on its current path, so no input can make it recurse, and a value shared by two branches is admitted. The run's findings are then dumped whole without a second walk.
  - It then writes the run and every finding in two statements on the caller's unit of work.
  - The schema's refusals map to `RefusedError` (naming the constraint), `ConflictError` and `NotFoundError`.
  - The reads are `get_run`, `latest_run(corpus_root)`, `baseline_run(corpus_root, baseline_branch, before_seq)` (R2Q12 (a): complete, full, default-tip, same corpus and branch), `get_finding` and `list_findings` (keyset by id, filters by class).
  - Each read refuses U+0000, or a lone surrogate, in every text parameter it binds, as a `RefusedError` naming the column, before any statement (`6086098003` item 3 (c)). Before this, a NUL there raised psycopg's `DataError`, and a surrogate its `UnicodeEncodeError`. The writes were already guarded, `path` among them.
- **`identity.TABLES`** gains `health_runs` and `health_findings`, citing R2Q13 (a): the ruling `6003486656`, and option (a)'s text at plan 038's `clarify-questions.md:651-653`. So `verify_runtime_access`, whose `SERVED_TABLES` is `TABLES`, now measures the served role's rights on them.
- **`runtime/cli.py`**:
  - `DROP_ORDER` drops the two health tables first, findings before runs.
  - The reset docstring, comments and note name the health tables.
  - **`RESET_CONFIRMATION` is byte-identical**, `yes-drop-the-coordination-database`, as F14.1 spells it. A comment now says so, and `test_runtime_reset_drops_a_populated_health_store` asserts it.
- **Both init scripts** (still byte-identical) and **`docs/runtime.md`**:
  - The grant array and the owner-guard's exempt array gain both tables.
  - The comments name them.
  - The guard's "MEASURED" sentence is re-measured on postgres 16.15 with the nine tables: no row with only this runtime's nine tables, and exactly one row (`invoices`) when the owner also owns `invoices`.
  - `docs/runtime.md` § 8a's migration lists and `dropped` are **re-measured**: `opendox-runtime runtime init|migrate|status|reset` against postgres 16.15, which gave `["0001","0002","0003"]` and nine tables dropped, health tables first. The section says which figures are new. § 1 and § 7 prose name the health tables.
- **The five suites**:
  - `test_schema_shape.py`: `_statements` reads `0001` with `0003_`, and `RULED_TABLES` gains both tables. Its comment cites the ruling, `6003486656`, and quotes option (a)'s text from plan 038's `clarify-questions.md:651-653`. The `…_exactly_rulings_six_tables` node keeps its name for #1144 box 14.2's citation; its docstring says what it reads now.
  - The ten hard-coded `["0001", "0002"]` lists, exactly as R2-INV-P5 lists them: `test_migrations_apply.py` `:71`, `:72`, `:360`, `:431`, `:737`, `:852`, `:996`; `test_bundled_postgres.py` `:540`, `:924`; `test_runtime_cli.py` `:277`.
  - `test_runtime_cli.py:342`'s reference map gains `health_findings → health_runs`.
  - `test_deploy_shape.py` moves with `TABLES`: re-run, not edited.
  - **Four tree copies in `test_migrations_apply.py` gained `0003_health.sql`** (`:831` for `:852`, and three the map did not count; see *For the holder*).
  - **`test_api_endpoints.py`, one edit, admitted by the holder (`6069024568` item 3).** `test_readiness_refuses_a_database_whose_migration_file_has_changed`'s tree gains `0003_health.sql`, for the same cause.

## Falsifier: red, then green

Red at openDox-code `main` `99220883`:
- **The test file alone:** `python -m pytest -q tests_runtime/test_health_store.py` gives `E   ModuleNotFoundError: No module named 'opendox.runtime.health_store'`, so collection is interrupted, rc=2.
- **The store module, but no `0003_`:** `74 failed, 17 passed`, and every DB node fails with `psycopg.errors.UndefinedTable: relation "health_runs" does not exist`. That includes `test_the_store_refuses_a_finding_without_provenance[no-pack_id]` and `test_an_install_level_finding_is_admitted`. The 17 that pass are the hermetic refusals, which never reach a database.

Green at this head (`1fa6ca6c`), with `CI=true` and `OPENDOX_TEST_DATABASE_URL` set to the `postgres:16` (16.15) container: `python -m pytest -q tests_runtime/test_health_store.py tests_runtime/test_schema_shape.py` gives `174 passed in 78.04s (0:01:18)` (165 nodes in `test_health_store.py` and 9 in `test_schema_shape.py`), including:

```
PASSED test_the_store_refuses_a_finding_without_provenance[no-pack_id]
PASSED test_the_store_refuses_a_finding_without_provenance[no-pack_version]
PASSED test_the_store_refuses_a_finding_without_provenance[null-pack_id]
PASSED test_the_store_refuses_a_finding_without_provenance[null-pack_version]
PASSED test_the_store_refuses_a_finding_without_provenance[empty-pack_id]
PASSED test_the_store_refuses_a_finding_without_provenance[empty-pack_version]
PASSED test_an_install_level_finding_is_admitted
PASSED test_a_nul_is_refused_by_name_before_any_statement[identity-value]   (one of 11 cases)
PASSED test_a_nul_in_an_identity_never_reaches_the_driver
```

The NUL tests (REVIEW-W1 MINOR 1) were red first, at `08e80d2e`. All 11 hermetic cases failed with `AssertionError: a statement reached the database`, and the DB case failed with `psycopg.errors.UntranslatableCharacter: unsupported Unicode escape sequence`. `pids_max` 1.5, -1 and -0.5 were admitted.

The provenance test proves three layers separately:
1. The store refuses before any statement, measured with a connection double that fails on any statement.
2. Over a real database it refuses, and no run row is left behind.
3. The SCHEMA refuses the same row written raw, past the store: `23502` on `health_findings.<field>` for a null, and `23514 health_findings_<field>_check` for an empty string.

The five suites, plus `test_deploy_shape.py`, `test_migration_shape.py` and `test_runtime_surface.py`, ran on the working tree before `0ee72652` was committed: 425 selected, 421 passed, 4 failed. The 4 were the three copy sites (*For the holder*) and one parametrization bug in the new test. All four are fixed in `0ee72652`; those nodes, plus `test_health_store.py`, then re-ran 95/95.

## The full suite, as CI runs it: baseline and head, node by node

Both runs were local, in one environment. The command was `python -m pytest -q --junitxml=…`, run from the repository root with `CI=true` and `LANG=C.UTF-8`, with every `GIT_*` and `XF_*` variable unset. Each run had a venv built with CI's own install command, `pip install --only-binary :all: -c constraints-cpython312-linux.txt -e ".[runtime,test]"`, on `/usr/bin/python3.12`. Both ran against the same `postgres:16` (16.15) container, with TMPDIR and `--basetemp` outside every checkout.

| tree | selected | passed | skipped | failed | errors |
|---|---|---|---|---|---|
| baseline: openDox-code `main` `6827cafc` | 5806 | 5795 | 11 | 0 | 0 |
| head: this PR `1fa6ca6c` | 5972 | 5960 | 11 | 1 (the timing flake below) | 0 |
| CI `validate` at `0336a838` ("Pin the triple") | 5964 | 5953 | 11 | 0 | 0 |
| earlier head `fbf9e77e` (local) | 5930 | 5919 | 11 | 0 | 0 |

**CI's `validate` at `1fa6ca6c`:** its earlier attempts ran no test, because Docker Hub refused the `postgres:16` service image pull (`toomanyrequests: You have reached your unauthenticated pull rate limit`). The holder's re-run started at 22:38:59Z and was still in progress at 22:52Z.

**The one red at the head is a timing flake that `main` has too:** `test_migrations_apply.py::test_the_draft_page_budget_does_not_read_the_bodies_it_sizes` asserts that reading draft bodies takes more than four times as long as sizing them. At the head it failed with `assert 0.029287184996064752 > (0.014348337994306348 * 4)`. Run eight times each, interleaved with `main` (`6827cafc`) under the same host load (about 70), it failed 3 of 8 at the head and 3 of 8 at `main`. T042 does not touch the drafts or that test.

**Compared by node id, from the two junit files, not by counts:**
- 0 baseline nodes are missing at the head.
- At `1fa6ca6c`, 1 baseline node changed outcome: the timing flake above, `passed -> failed`. It failed on `main` at the same rate.
- The skipped set is identical: the same 11 nodes.
- The head, `1fa6ca6c`, adds exactly 166 nodes, all passing:
  - 165 in `tests_runtime/test_health_store.py`;
  - 1 in `tests_runtime/test_runtime_cli.py`: `test_no_handler_in_this_package_emits_an_exception_without_the_redactor[health_store.py]`. That walker is parametrized over the runtime package's modules, and R2-INV-P5 predicted this node (`:1892`).
- CI's pins hold at `0336a838`: `selected>=3977 (margin 1987) passed>=3966 (margin 1987) skipped==11`.
- At `0336a838`, CI's `validate` selected 158 nodes more than the baseline (5964 against 5806): 157 in `test_health_store.py`, plus the walker node.

An earlier baseline at `99220883` was discarded: its venv's interpreter symlink pointed at a `~/.local/bin/python3.12` that something outside T042 removed mid-run, and its reds were all `FileNotFoundError` on that path. A clean re-run at `99220883` was 5647 passed, 11 skipped, 0 failed. `main` then moved to `6827cafc` (#90), and the baseline above was taken there.

## Mutants: round 1, 76 run, 74 killed, 2 equivalent (proven); REVIEW-W1 rounds, 16 run, 16 killed; the holder's two fixes and the surrogate check, 20 run, 20 killed at `1fa6ca6c`

**At this head, `1fa6ca6c`:** the cycle and depth mutants (`TOTAL killed=11 survived=0`), the bound-parameter mutants (`TOTAL killed=6 survived=0`) and the surrogate mutants (`TOTAL killed=3 survived=0`) were all re-run in place. Two of the 11 changed text after SonarCloud's `_json_children` refactor (`01f4192d`), and the NUL check moved into `_text_unstorable` (`3230428c`).

**The surrogate check (Copilot at `01f4192d`): `TOTAL killed=3 survived=0`.** Each is killed by `test_a_lone_surrogate_in_a_write_is_refused_by_name_before_any_statement[path]`, "a statement reached the database":
- the surrogate check removed;
- the range narrowed to high surrogates only (the `path` case carries `\udcff`, a low one);
- the walk skipping its text check.

**`6081875839` (cycle and depth): `TOTAL killed=11 survived=0` at `0336a838`, and again at `01f4192d`, after SonarCloud's `_json_children` refactor moved two mutants' text.** Red first: against `fbf9e77e`'s walk (with only the new constant added, so the file imports), the new tests gave `20 failed, 6 passed`. 15 failed with `RecursionError: maximum recursion depth exceeded`, and in 5 the over-deep value reached the database (`AssertionError: a statement reached the database`). The killing tests:
- **the cycle check removed:** `[cyclic-mapping-identity]`, because the refusal said "nests deeper than 64 levels", not "contains itself";
- **the depth check removed**, or **loosened by one level:** `[over-deep-identity]`, "a statement reached the database";
- **the depth check one level too strict:** `test_a_value_nested_exactly_to_the_bound_is_kept_and_reads_back[identity]`;
- **the path never left** (every container seen counted as a cycle): `test_a_value_shared_by_two_branches_is_not_a_cycle`;
- **keys not walked:** the NUL row `[identity-key]`;
- **lists not walked:** `[cyclic-list-identity]` ("is not JSON this store can keep", not the cycle);
- **`_json_text`'s walk removed:** `[cyclic-mapping-pack_pins]`;
- **the per-field walk removed:** `[cyclic-mapping-identity]` (named "a finding's identity", not "finding 0's identity");
- **the findings re-walked whole:** `…_exactly_to_the_bound…[evidence]` ("the run's findings nests deeper than 64 levels");
- **the NUL check removed:** the NUL row `[identity-value]`.

**`6086098003` item 3 (c) (U+0000 in a bound text parameter): `TOTAL killed=6 survived=0` at `0336a838`, and again at `01f4192d`.** Red first: at `7e13130d` all 7 read rows reached the database, and over a real one `latest_run` raised `psycopg.DataError: PostgreSQL text fields cannot contain NUL (0x00) bytes`. The `path` row was already green, since the write path walks every finding field. The killing tests:
- **each read's guard removed** (`latest_run`, `baseline_run`, `get_finding`, `list_findings`), or **the shared parameter walk made a no-op:** the matching `test_a_nul_in_a_read_is_refused_by_name_never_by_the_driver[…]` row, "a statement reached the database";
- **`path` skipped by the per-field walk:** the NUL row `[path]`, "a statement reached the database".

**r6b, the upper cap removed (lane 3's second pass), at `fbf9e77e`: KILLED.** The mutant reads `max(limit, 1)` in place of `clamp_limit(limit)` in `list_findings`. At `68f70b8a` it survived (lane 3): the run holds two findings, so a cap of 500 cannot bite, and that assertion could not fail. The test now lowers `identity.MAX_PAGE_SIZE` to 1 and asserts that a limit of 2 reads one row. Under the mutant it fails with `AssertionError: assert 2 == 1`, where `2 = len([...])` is `list_findings(run_id=…, limit=2)`.

**REVIEW-W1 round, at `68f70b8a`:** `TOTAL killed=15 survived=0`. Each mutant was killed by the test meant for it:
- **NUL, `_json_text`'s check removed:** `[pack-pins-key]` failed with "a statement reached the database".
- **NUL, the per-finding loop removed:** `[identity-value]` failed; the refusal named "a finding's identity", not "finding 0's identity".
- **NUL, the run fields unchecked:** `[corpus-root]`.
- **NUL, keys unchecked:** `[identity-key]`.
- **NUL, lists unchecked:** `[evidence-list]`.
- **`pids_max` check reverted, or admitting fractions:** `[1.5] … was admitted`.
- **`pids_max` admitting negatives:** `[-1] … was admitted`.
- **r1, cascade removed:** `psycopg.errors.ForeignKeyViolation`.
- **r3, the locator dropped:** `assert None == {'line_end': 12, 'line_start': 12}`.
- **r4, the evidence emptied:** `assert {} == {'candidate':…}`.
- **r5, the message overwritten:** `assert 'broken-link' == 'link target …'`.
- **r6, the limit unclamped:** `assert 0 == 1`.
- **r16, by default:** `… 'BY DEFAULT') == (…`.
- **r16, cache 20:** `assert (20, 1, False) == (1, 1, False)`.

**Round 1** follows.

Each mutant is one exact edit to the committed tree. Each was applied, run against its tests with `-x`, and restored with `git checkout --`. The runner is kept outside the repository. Grouped by kill:
- **Every NOT NULL** (21 mutants): killed by `test_the_tables_hold_exactly_the_data_models_columns` (the nullable set read off the applied schema). For `pack_id` and `pack_version`, the provenance test killed them first.
  - Two survived and are **equivalent**: `health_findings.run_id` and `.id`. Both are in the composite primary key `(run_id, id)`, which imposes NOT NULL by itself. Proof: under each mutant, `information_schema.columns.is_nullable` for both columns reads `NO` (applied to postgres 16.15).
- **Every CHECK neutralized to `check (true or …)`** (16), plus four partial mutants:
  - `pack_pins` without the `opendox` key;
  - `sandbox` without `pids_max`;
  - severity admitting `critical`;
  - baseline class admitting `unclassed`.
  - Each is killed by `test_each_run_check_refuses_what_it_names[<constraint>…]` or `test_each_finding_check_refuses_what_it_names[…]`, which assert the constraint the server names, and the provenance test kills the two empty-string checks.
- **The other schema mutants:**
  - foreign key removed: killed by `test_a_finding_must_name_a_recorded_run`;
  - primary key removed: killed by `test_two_findings_with_one_id_in_one_run_store_nothing`;
  - `run_seq` unique removed: killed by `test_a_restarted_sequence_cannot_record_a_second_run_at_one_position`;
  - `identity` as `jsonb`: killed by `test_an_install_level_finding_is_admitted`;
  - a `patch` column added: killed by `test_the_tables_hold_exactly_the_data_models_columns`.
- **`full_run` reverted to a bare `full`:** killed by `ERROR … psycopg.errors.SyntaxError: syntax error at or near "full"`.
- **`health_store.py` guards** (17):
  - the provenance refusal removed, or admitting empty;
  - an unknown field admitted;
  - a naive datetime admitted;
  - the `full_run` bool check, the text-field check or the evidence-mapping check removed;
  - identity not sorted, or ASCII-escaped;
  - latest or baseline ordered by `started_at`;
  - latest ignoring the corpus;
  - baseline admitting partial, `--pack`-restricted or any-kind runs, ignoring the branch, or ignoring `before_seq`;
  - the class filter ignored.
  - All are killed by the named `test_health_store.py` nodes.
- **A dropped `TABLES` entry** (either table): killed by `test_schema_shape.py::test_the_store_declares_exactly_the_tables_the_ruling_names`.
- **A `DROP_ORDER` that misses either health table, or drops runs before findings:** killed by `test_runtime_cli.py::test_the_drop_order_is_topological_and_not_reversed_declaration_order`, with the DB-backed `test_runtime_reset_drops_a_populated_health_store` behind it.
- **The reset token changed:** killed by `test_runtime_reset_drops_a_populated_health_store`.
- **The closure reader reading `0001` only:** killed by `test_the_canonical_schema_declares_exactly_rulings_six_tables`.
- **`RULED_TABLES` without the health tables:** killed by `test_the_store_declares_exactly_the_tables_the_ruling_names`.
- **An array missing a health table**, in the compose grant, the Kubernetes guard or the docs grant: killed by `test_deploy_shape.py`, through the byte-identity and derived-list tests.

## For the holder

- **`run_seq`, the order of record: ACCEPTED by the holder (`6069024023` item 3); the data-model row is bookkeeping.**
  - data-model.md gives `run_id` the type uuid and no ordering column, and `0001`'s header forbids ordering by wall time ("can step backwards under load").
  - So `health_runs` carries `run_seq bigint not null generated always as identity`, with a unique constraint. "Latest run" and the baseline order by it, never by `started_at` (killed mutants: `py:latest-orders-by-clock`, `py:baseline-orders-by-clock`).
  - **Limit: the sequence value is taken at INSERT time, not COMMIT time.** Two runs of one corpus recorded in overlapping transactions take their order from their inserts, so the one that commits first can carry the higher number. **That ordering is an OBLIGATION on T046, not a T042 feature:** `6069024023` item 3 rules that "T046 serializes its classing and recording per corpus with an advisory transaction lock, so a run's sequence position is the order in which it was classed. It tests that two overlapping runs serialize." T042 supplies the column, the uniqueness and the CACHE 1 that the ruling keeps (pinned by `test_run_seq_is_generated_always_with_a_cache_of_one`).
  - The served role writes it with table grants only. Measured: no sequence privilege is needed (`has_sequence_privilege … 'usage'` = false, and the insert succeeds). `test_the_served_role_can_record_and_read_a_run` holds that.
- **Four copy sites the readiness map did not count.** The fourth, `test_api_endpoints.py`'s readiness-drift test, is in a sixth suite outside the Files line and was admitted by the holder (`6069024568` item 3).
  - `test_migrations_apply.py`'s `test_editing_an_applied_migration_refuses_rather_than_reapplying`, `test_a_later_migration_is_applied_in_numeric_order` and `test_drift_sees_what_plan_cannot` copy only `0001` and `0002` into `tmp_path`, then run over the `database` fixture's ledger, which now records `0003`.
  - They went red with `the ledger records migration(s) ['0003'] that this tree does not contain`, so their copies gained `0003_health.sql`, inside a suite T042 owns.
  - `:1384` (`0003_not_utf8.sql`) and `test_a_tampered_canonical_migration_applies_nothing_at_all` run on fresh schemas and did not move, as the map said.
- **`baseline_class` is NOT NULL.** R2Q12 (a) rules three classes, and I-2 (a) rules out a fourth; a null would be that fourth. The engine classes before it records (T046).
- **No `commit` hex check of its own.** A non-null `commit` must equal `export_commit`, whose form is checked, so a second check could never be the one that refuses a row, and its mutant could not be killed. The header says so.
- **Not edited, and stale only in wording (REPORT ONLY, per the holder; for a follow-up):**
  - `migrations.py`'s comments on `SERVED_TABLES` ("RULING Q1's own list") and `:93-94` ("reads the closed six against `0001` alone");
  - `bundle.py:1154` ("the six coordination tables and the ledger, and nothing else");
  - `runtime/__init__.py`'s import-weight paragraph.
  - None of these is on T042's Files line, and all behave correctly through `TABLES`.
- **FIXED in `fbf9e77e`, on the holder's word (comment-only): the R2Q13 (a) citation.** The words quoted as R2Q13 (a) at `identity.py:59` (and in its module docstring) and at `test_schema_shape.py:34-35` and `:76-80` were attributed to `#656` `6003486656`. They are R2Q13's option (a) text, at plan 038's `clarify-questions.md:651-653`, which `6003486656` ruled (a) in other words. Each comment now keeps `6003486656` as the ruling and cites `clarify-questions.md:651-653` for the quoted text. Both files' ASTs, docstrings aside, are equal before and after.

## Reviews and SonarCloud

- **Round 1, at `56d95d4f`:**
  - **Copilot** ("Changes recommended", 2 findings):
    - (1) JSON `null` passing the object CHECKs. *Accepted limit, not a defect.* On postgres 16.15, `jsonb_typeof('null'::jsonb)` is the text `'null'`, and all five object checks refuse it. `0c5e3cc` holds five test cases.
    - (2) A `run_seq` conflict reported as a finding collision. *Fix-now, fixed in `0c5e3cc`:* each unique constraint now has its own message, and two mapping mutants are killed.
  - **Codex** ("Reviewed commit: `56d95d4f93`"): one P2, the same finding as Copilot (2), fixed.
  - All 3 threads are answered and resolved.
- **SonarCloud, at `56d95d4f`:** the gate failed on reliability C.
  - **2 BUGs, `plsql:NullComparison`, on `pack_id <> ''` and `pack_version <> ''`.** The PL/SQL analyzer applies Oracle's rule that `''` is NULL; in PostgreSQL it is not. `0c5e3cc` spells both as `length(…) > 0`, which is the same check in PostgreSQL, and the two empty-string mutants are still killed.
  - **4 `python:S5778`** (more than one possibly-raising call in a `pytest.raises` block): fixed in `0c5e3cc`, one call per block.
  - **1 `plsql:S1192`** ("Define a constant instead of duplicating this literal 4 times": `'object'` in four `jsonb_typeof(…) = 'object'` checks) is EXPLAINED, not changed:
    - SQL DDL has no named constant a CHECK can use.
    - A shared domain or function would hide which constraint refuses a row, and each check is named on its own because `test_each_*_check_refuses_what_it_names` kills its mutant by the constraint name the server reports.
    - The literal is `jsonb_typeof`'s own vocabulary, so repeating it is the readable form.

- **Round 2, at `08e80d2e`** (after `0c5e3cc`, `808524c` and the merge of `main` `6827cafc`):
  - **Copilot** reviewed `08e80d2e`: "🔵 Needs a closer look", **0 open findings**, 2 resolved since its last review. The stated reason is only that "the cross-cutting schema, persistence, and deployment change remains a draft gated on T027 and final validation". It is not "Changes recommended", and it opened no thread.
  - **Codex** reviewed `08e80d2e` (comment at 23:23:05Z): "Didn't find any major issues", with **Reviewed commit:** `08e80d2e48`. No thread was opened. An earlier trigger, at 21:36Z, had been answered with a usage limit.
  - **SonarCloud:** quality gate **passed** (new reliability, security and maintainability all A, 0.0% duplication). 1 open issue, the `S1192` explained above.
  - **CI:** `validate`, `acceptance` and SonarCloud are all SUCCESS.
  - **Threads:** 3 in all, 0 unresolved.

- **Round 3, at `68f70b8a`** (lane 3's REVIEW-W1 of `08e80d2e`, #99 `6071241577`: GO, with 0 BLOCKER, 0 MAJOR, 3 MINOR and 9 NIT; the holder's rulings, #656 `6072086385`; item-by-item reply `6072912368`):
  - **Fixed:**
    - MINOR 1: a NUL (U+0000) is refused by name before any statement;
    - MINOR 2: the pathed read-back test;
    - MINOR 3: the Ruled line;
    - the NITs on the body (:65, :146, :199), the cascade, `run_seq`'s catalog, the page bound and `pids_max`.
  - **Reported only, per the holder:** the stale comments and the R2Q13 (a) citation (*For the holder*), and the shape gaps not ruled (*What is NOT done*).
  - **Copilot** reviewed `68f70b8a`: "🔵 Needs a closer look", **0 open findings**. Its stated reason is only that the change "remains draft-gated on T027 and needs final human confirmation"; it is not "Changes recommended".
  - **Codex:** CODEX-SILENT `68f70b8a`. Its answer to the trigger (02:18:56Z) was "You have reached your Codex usage limits for code reviews". Its last review was clean at `08e80d2e48`.
  - **SonarCloud:** gate **OK** (A, A, A; 0.0% duplication).
    - 2 open issues, both `plsql:S1192`, both EXPLAINED, not changed. One is `'object'` ×4 (line 105), as above.
    - The other is `'pids_max'` ×4 (line 106): `health_runs_sandbox_check` reads that one key four times inside a CASE. The CASE is there so the numeric cast is reached only for a JSON number, because SQL does not promise to evaluate an AND's operands in order, and DDL has no constant to name the key.
    - A `jsonpath` form (`sandbox @? '$.pids_max ? (…)'`) would read it once. It is a less familiar syntax for the same check, and it would change a head whose suite is already measured, so it is the holder's word if wanted.
  - **Threads:** 3 in all, 0 unresolved. REVIEW-W1 is a top-level comment and opened no thread.

- **Round 4, at `fbf9e77e`** (lane 3's second pass of `68f70b8a`, relayed by the holder: GO, with one MINOR and four NITs still open):
  - **Fixed:**
    - r6b: the page test now lowers the cap, and the mutant is killed (*Mutants*);
    - the R2Q13 (a) citation, comment-only, on the holder's word (*For the holder*);
    - the body: this text is now the live body (the Ruled line, the green quote at the head, the T046 obligation, the landed `data-model.md` note), and `pids_max` reads "a non-negative whole number or null".
  - **Copilot** reviewed `fbf9e77e`: "🔵 Needs a closer look", **0 open findings**, and no thread. Its one "previously missed" item (medium): a CYCLIC mapping or list raised `RecursionError` from the NUL walk, not `RefusedError`.
    - **FIXED in `7e13130d`, by the holder's FIX-NOW ruling, #656 `6081875839`.** The NUL walk, put in front of `json.dumps`, had regressed a refusal the store already had: `json.dumps` refuses a cycle with `ValueError`, which the store turned into `RefusedError`. The same walk let a value nested past Python's recursion limit escape as `RecursionError` too.
    - Now one iterative walk refuses a cycle, or nesting past `MAX_JSON_DEPTH` (64), by the field's name, before any statement, quoting nothing, and with no row written. The tests and mutants are above.
  - **Codex:** CODEX-SILENT `fbf9e77e`. Its answer to the trigger (`6073222041`) was the usage-limit message (`6073223584`).
  - **SonarCloud:** gate **passed** at `fbf9e77e`, with the same 2 open `plsql:S1192`, explained above. **CI:** `validate`, `acceptance` and SonarCloud SUCCESS.
  - **Threads:** 3 in all, 0 unresolved.

- **Round 5, at `0336a838` and `01f4192d`** (the two holder rulings):
  - `7e13130d` carries `6081875839` (above). `0336a838` carries `6086098003` item 3 (c): every read now refuses U+0000 in each text parameter it binds, naming the column, where psycopg had raised `DataError`.
  - **Copilot** reviewed `0336a838`: "🔵 Needs a closer look", **0 open findings**, with no "previously missed" item. Its stated reason is only that the change "remains a draft with an explicit T027 landing dependency requiring final human validation".
  - **Codex:** CODEX-SILENT `0336a838`. Its answer to the trigger (`6086316679`) was the usage-limit message (`6086319829`).
  - **SonarCloud at `0336a838`:** the gate passed, but there were 5 new issues on the two fixes. **All 5 are FIXED in `01f4192d`, with no behaviour change:**
    - 4 `python:S5778`: each `pytest.raises` block in the new tests now holds one call;
    - 1 `python:S3776` (cognitive complexity 16 of 15) in `_unstorable`: what the walk visits is now `_json_children`.
  - **CI at `0336a838`:** `validate` (`triple: selected=5964 passed=5953 skipped=11`), `acceptance` and SonarCloud SUCCESS.
  - **Copilot** reviewed `01f4192d`: "🔵 Needs a closer look", **0 open findings**, and no thread. Its one "previously missed" item: a LONE SURROGATE (U+D800 to U+DFFF), which a surrogate-escaped file name carries in `path` or `corpus_root`, passed the walk. Measured at `01f4192d`, the driver raised `UnicodeEncodeError: 'utf-8' codec can't encode character '\udcff' … surrogates not allowed` while binding, and on a write only after the run's own insert.
    - **FIXED in `3230428c`, classified fix-now** under the holder's principle in `6086098003` item 3 (c) and `6081875839`: a driver error instead of the store's named refusal, from a simple payload, with a small fix. The walk's text check now refuses a lone surrogate as it refuses U+0000, by name, before any statement, on writes and on every read parameter.
    - **Red first:** 8 failed (7 reached the database, 1 raised `UnicodeEncodeError`). **Green:** the two files plus the walker node, `186 passed`.
  - **Codex:** CODEX-SILENT `01f4192d`. Its answer to the trigger (`6088583751`) was the usage-limit message (`6088585995`).
  - **Copilot** reviewed `3230428c`: "🔵 Needs a closer look", **0 open findings**, and no thread. It raised two "previously missed" items, both wording: `docs/runtime.md:31` and `0003_health.sql`'s header (`:82`) stated in the present tense that the hosted plane refuses `health` by name. R2Q15 (a) rules that refusal, but T046 adds it with the `health` verbs and routes, and this change adds neither.
    - **FIXED in `1fa6ca6c`**, as comment and prose only: both now say the refusal is ruled and arrives with T046. `0003`'s statements outside `--` comments are unchanged (compared line by line). This head's full suite had not yet run, so the fix cost one review round.
  - **Codex:** CODEX-SILENT `3230428c`. It answered the trigger (`6088723901`) with the usage-limit message.
  - **At `1fa6ca6c`:**
    - **Copilot:** "🔵 Needs a closer look", **0 open findings**, and nothing "previously missed". Its stated reason is only the T027 gate and the pending full-suite and mutation validation.
    - **Codex:** CODEX-SILENT `1fa6ca6c` (`6089385155`, the usage limit).
    - **SonarCloud:** the gate passed, with the same 2 `S1192`, now at lines 107 and 108.
    - **Mutants:** 20 of 20 killed (*Mutants*).
  - **Threads:** 3 in all, 0 unresolved.

## Files changed

- `migrations/0003_health.sql` (new)
- `src/opendox/runtime/health_store.py` (new)
- `src/opendox/runtime/identity.py`
- `src/opendox/runtime/cli.py`
- `deploy/compose/init-runtime-role.sh`
- `deploy/kubernetes/base/init-runtime-role.sh`
- `docs/runtime.md`
- `tests_runtime/test_health_store.py` (new)
- `tests_runtime/test_schema_shape.py`
- `tests_runtime/test_migrations_apply.py`
- `tests_runtime/test_bundled_postgres.py`
- `tests_runtime/test_runtime_cli.py`
- `tests_runtime/test_api_endpoints.py` (one edit, admitted by the holder in `6069024568`)

## What is NOT done

- **The serialized-size cap on `identity`, and every other field bound** (the id grammar, `message`'s 200 characters, the banned keys): T041's, in `health_contract.py`. Not imported, and not encoded in SQL.
- **The engine, baseline classes, `health run|list` and the hosted-plane refusal:** T046.
- **LANDED, not this PR's:** the `data-model.md` note that the `full` field's SQL column is `full_run` is on openxFactory main since `3a2ab303` (`data-model.md:160`). The `run_seq` row (`6069024023` item 3 bookkeeping) is the holder's batch.
- **Reported, not fixed (lane 3's REVIEW-W1, beside the `pids_max` NIT), because none is a shape this PR's rulings fix:**
  - a whitespace-only `pack_id` (its grammar is T041's bound);
  - `pack_pins.opendox` = 5 (data-model.md fixes `pack_pins` as `{pack_id: {"version", "digest", "commit"}}`, with "`opendox`'s entry the installed version alone", which leaves that entry's form open);
  - an empty `baseline_branch` on a default-tip run (in T042's Files and one constraint away, `coalesce(length(baseline_branch), 0) > 0`; not ruled, so not added).
- **`test_runtime_surface.py` is not moved.** `health_store.py` imports nothing beyond the standard library and `identity` at module level, so it passes the heavy-module closure without joining `STDLIB_ONLY_MODULES`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
