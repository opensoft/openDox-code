# Branch protection: the `validate` check is required

Closes item 1.5 of `openxFactory openspec/changes/split-opendox-two-layer-product/tasks.md`
for this repository: *"Branch-protection ruleset created in EVALUATE mode in
each, promoted to ACTIVE once its required check has reported once."*

Ruleset state is a repository setting, not a tree fact — nothing under
`tests/` can assert it — so this file is the evidence line 1.5 asks for.

## What exists

A **repository-level** ruleset (distinct from the two organization-sourced
rulesets `Require Code Owner Review` and `Copilot Auto-Review All PRs`, which
were already in force before this project existed and enforce PR-and-review,
not any check content):

| field | value |
|---|---|
| name | `Require validate check` |
| id | `22364973` |
| target | `main` (the default branch) |
| rule | `required_status_checks`, naming context `validate` |

## The `evaluate` → `active` history

1. **Created in `evaluate`** on 2026-09-05, before this pull request existed,
   so the required check's first real report under the ruleset is this PR's
   own `validate` run rather than a backdated claim.
2. **`validate` reported** on this PR's head commit — see this PR's checks
   for the run link; a passing run satisfies "reported once."
3. **Promoted to `active`** once step 2's run completed, before this PR was
   merged — so the very PR that adds this evidence file is also the first PR
   whose merge that ruleset actually gated.

Before this ruleset existed, nothing in this repository required `validate`
to pass before a merge: the org-wide rulesets require a pull request and a
Copilot review, but neither names a status check, and classic branch
protection was never configured — `gh api
repos/opensoft/openDox-code/branches/main/protection` returned `404 Branch not
protected`. The one PR this project merged before this one (#1, bootstrapping
posture) landed without `validate` being a required check — a gap this file,
and the ruleset it documents, closes.

## Correction to PR #1's claim

PR #1's body stated compliance with tasks.md "§ 1.3-1.5". That overstated the
work: 1.5 (this file's subject) was not done in PR #1 — no ruleset existed in
this repository until this pull request. PR #1's description is being
corrected, as part of landing this fix, to say § 1.3-1.4 with a pointer to
this PR for 1.5.

## One difference from the openXdox family, RECORDED rather than changed

Added by the **OQ-O scaffold-levelling pass** (`opensoft/openxFactory#656`,
RULING of 2026-09-09: *"level the six scaffolds first, one small PR per
repo"*), which measured the six rulesets and found one difference that is not
a tree fact and cannot be closed by a pull request.

`strict_required_status_checks_policy` is **`false`** on all three openDox-family
rulesets (this one is id `22364973`) and **`true`** on all three openXdox-family
rulesets. Strict means a pull request must be **up to date with `main`**
before it can merge; not-strict means a stale-but-green branch may merge.

The levelling pass does **not** change it. A ruleset is a repository setting
outside any pull request's reach, and choosing which of the two policies the
family should standardise on is Brett Heap's act, not an author's. What the
pass owes is that the difference is written down where somebody hits it —
which is here, in the openXdox family's matching file, and in the pull
requests that add both.
