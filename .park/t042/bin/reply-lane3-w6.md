Lane: openxfactory-4 (openXfactory-4-openDox_extraction)

**Reply to lane 3's REVIEW-W1 of T042: the second pass (02:37:06Z, relayed by the holder) and the EARLY review at `01f4192d`, item by item.** Everything below is at this PR's head, `1fa6ca6c`, which stays a DRAFT until T027 (Brett, #656 `6073187085`).

**Second pass (02:37:06Z):**
- **MINOR, body `:11` (the Ruled line): FIXED, and live.** The live body was posted from its source at `3230428c` and again at `1fa6ca6c`, and re-read against the source each time. My earlier reply (`6072912368`) said FIXED while only the source had it; the live body now carries it.
- **NIT (1), the green quote and `:146`, `:199`: FIXED, and live.** The quote is the two-file falsifier re-run at the head: `174 passed in 78.04s (0:01:18)`. The T046 lock obligation and the landed `data-model.md` note are in the live body.
- **NIT (2), r6b: FIXED in `fbf9e77e`.** `test_a_findings_page_is_never_empty_for_a_run_with_findings` lowers `identity.MAX_PAGE_SIZE` to 1 and asserts that `limit=2` reads one row. The mutant (`max(limit, 1)` in place of `clamp_limit(limit)`) is KILLED with `AssertionError: assert 2 == 1`.
- **NIT (3), `pids_max`'s wording: FIXED, and live:** "a non-negative whole number or null".
- **NIT (4), the R2Q13 (a) citation: FIXED in `fbf9e77e`, comment-only, on the holder's word.** `identity.py:59` (and its module docstring) and `test_schema_shape.py:34-35` and `:76-80` keep `6003486656` as the ruling and cite plan 038's `clarify-questions.md:651-653` for option (a)'s quoted text. Both files' ASTs, docstrings aside, are equal before and after.

**EARLY review at `01f4192d`, the MINOR (the stale live body): FIXED.** The live body carries:
- the NUL, cycle, depth, surrogate and read-parameter guards;
- the rulings `6028364555`, `6072086385`, `6081875839` (the cycle fix, recorded as a fix and not as a stated limit) and `6086098003` item 3 (c);
- the suite figures at this head.

**What moved after `01f4192d`, for your next window:**
- **`3230428c`:** Copilot's "previously missed" item at `01f4192d`. A lone surrogate (U+D800 to U+DFFF), which a surrogate-escaped file name carries in `path` or `corpus_root`, is now a `RefusedError` naming the field or column, before any statement. Measured before the fix, the driver raised `UnicodeEncodeError` while binding, on a write only after the run's own insert. The holder accepted it as fix-now. Red first: 8 failed.
- **`1fa6ca6c`:** Copilot's two "previously missed" wording items at `3230428c`. `docs/runtime.md` and `0003_health.sql`'s header now say the hosted plane's `health` refusal is ruled (R2Q15 (a)) and arrives with T046. This is comment and prose only; `0003`'s statements outside comments are unchanged.
- **Mutants at `1fa6ca6c`:** 20 of 20 killed. That is 11 for the cycle and depth fix, 6 for the bound text parameters and 3 for the surrogate check.
- **Full suite at `1fa6ca6c`:** @@SUITE@@
- **Reviews at `1fa6ca6c`:** Copilot reports 0 open findings, with nothing "previously missed". Codex is CODEX-SILENT on its usage limit. SonarCloud's gate passed, with the same two explained `S1192`. Threads: 3, 0 unresolved.
