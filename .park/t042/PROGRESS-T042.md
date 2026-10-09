# T042 progress (lane openxfactory-4, plan 038 HA-1): PARKED 2026-10-09 22:5xZ (holder STOP, team-01i 49%)

- **#99 head = local head = `1fa6ca6c`.** DRAFT. Clone clean. Nothing local running.
- **headw6 (full suite at 1fa6ca6c):** 5972 selected, 5960 passed, 11 skipped, 1 failed = the timing flake. node-compare vs baseline3: 0 missing, 1 changed (the flake), same 11 skips, +166 all passing (165 store + walker).
- **Timing flake** `test_the_draft_page_budget_does_not_read_the_bodies_it_sizes`: interleaved at the same load, head 3/8 failed, main 6827cafc 3/8 failed (`bin/logs-w6/interhead*`, `intermain*`).
- **Live body posted 22:5xZ and re-read == source:** head row 5972/5960/11/1, the flake evidence, +166 comparison, CI validate re-run 'in progress'.
- **CI validate at 1fa6ca6c:** holder's re-run (run 37992308767, job 114056619178) IN_PROGRESS since 22:38:59Z (past the Docker pull, so tests running). acceptance + SonarCloud SUCCESS.
- **Next:** (1) read validate job 114056619178 (GraphQL rollup; one REST read of its log for the `triple:` line) -- if Docker pull failed again: report CI-BLOCKED run 37992308767 (at most one more re-run); (2) body: CI row at 1fa6ca6c + pins margin line; post + re-read; (3) post `bin/reply-lane3-w6.md` on #99 after filling @@SUITE@@ (`5972/5960/11 + 1 known timing flake; +166`) -- `gh pr comment 99 -R opensoft/openDox-code --body-file`, re-read; (4) DRAFT-CLEAN 1fa6ca6c (keep the draft).

## Earlier state (superseded)

# T042 progress (lane openxfactory-4, plan 038 HA-1): parked 2026-10-09 01:3xZ (REVIEW-W1 fix round)

- **#99:** head still `08e80d2e` (DRAFT); not pushed this round.
- **Local `r2/t042-health-store`:** `68f70b8`, pushed only as `wip/r2-t042-park-0126` (a park commit on it carries `.park/t042/**`: `bin/` helpers, `pr-body.md`, this file).
- **Base:** openDox-code main `6827cafc`, unchanged. Baseline junit in `bin/logs-2135/baseline3.xml` (same environment).

## REVIEW-W1 (#99 6071241577; rulings #656 6072086385)
- **MINOR 1, NUL — DONE in `68f70b8`.** `_refuse_nul` checks keys and values at any depth, in `_json_text`, in every finding field (naming `finding N's <field>`) and in the run-level text fields; it raises `RefusedError` before any statement and quotes nothing. Red first: 11 hermetic cases reached the DB, and lane 3's DB case raised `psycopg.errors.UntranslatableCharacter`.
- **MINOR 2, read-back — DONE:** `test_a_pathed_finding_reads_back_field_for_field`.
- **MINOR 3, Ruled line — DONE in the body source** (`bin/pr-body.md`, not yet posted).
- **NITs:**
  - **Done in the body source:** :146 (the T046 lock obligation), :199 (landed at `3a2ab303`), and the stale-comment and citation report-only bullets.
  - **Pending:** :65, the green re-quote at the head.
  - **Done with tests:** r1 cascade (`test_deleting_a_run_takes_its_findings_with_it`), r16 (`test_run_seq_is_generated_always_with_a_cache_of_one`) and r6 (`test_a_findings_page_is_never_empty_for_a_run_with_findings`).
  - **Done in SQL:** `pids_max` must be a non-negative integer or null (a CASE check), with tests.
  - **Reported, not fixed:** whitespace `pack_id`, `pack_pins.opendox`=5, empty default-tip `baseline_branch`, and NUL on the read path.
- **Local:** test_health_store 123 + schema_shape 9 + the walker node = 133/133 green (before commit; same tree as `68f70b8`).

## Running at park (DO NOT edit the clone until it ends)
- **w1 mutants:** PID `3328908`, log `bin/logs-w1/mutants-w1.log`. It applies each mutant to `openDox-code` IN PLACE and restores it with `git checkout --`. It had done 8 of 15, all killed (`nul` ×5, `pids_max` ×3); the remaining 7 are r1, r3, r4, r5, r6 and r16 (two forms). Expected end about 01:45Z. On resume, check for the TOTAL line and `git status` clean first.

## Next on resume
1. Read `mutants-w1.log` TOTAL (expect 15/15 killed); confirm the clone is clean at `68f70b8`.
2. Run the full suite at `68f70b8` with `LOGDIR=bin/logs-w1` and `bin/run-suite.sh headw1`, nohup and poll. Compare node ids against `bin/logs-2135/baseline3.xml` (expect +123 −97 = +26 over the last head, 0 changed, the same 11 skips).
3. Fill the body: GREEN-QUOTE-PLACEHOLDER (re-quote at the head), the triples table (a head row for `68f70b8`), a mutants w1 line and a REVIEW-W1 dispositions section.
4. Push `r2/t042-health-store` to #99. Request Copilot (reviewer API), post the Codex trigger once, reply on #99 to lane 3's comment with the dispositions, `gh pr edit 99 --body-file` and re-read it live.
5. Report DRAFT-CLEAN `<head8>`.
