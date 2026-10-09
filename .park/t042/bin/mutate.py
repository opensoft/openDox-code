#!/usr/bin/env python3
"""T042 mutation run: each mutant is ONE exact edit to a committed file.

Applies it, runs the named tests with -x, records KILLED (with the first failing
node) or SURVIVED, and restores the file with `git checkout --`. Refuses to start
on a dirty tree and verifies the tree is clean after every mutant.
Usage: mutate.py <clone> <venv-python> <state-dir> [mutant-id-substring]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

CLONE, PY, STATE = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
ONLY = sys.argv[4] if len(sys.argv) > 4 else ""

SQL = "migrations/0003_health.sql"
HS = "src/opendox/runtime/health_store.py"
ID = "src/opendox/runtime/identity.py"
CLI = "src/opendox/runtime/cli.py"
SHAPE = "tests_runtime/test_schema_shape.py"
COMPOSE = "deploy/compose/init-runtime-role.sh"
K8S = "deploy/kubernetes/base/init-runtime-role.sh"
DOCS = "docs/runtime.md"

T_STORE = ["tests_runtime/test_health_store.py"]
T_SHAPE = ["tests_runtime/test_schema_shape.py"]
T_DEPLOY = ["tests_runtime/test_deploy_shape.py"]
T_DROP = ["tests_runtime/test_runtime_cli.py::test_the_drop_order_is_topological_and_not_reversed_declaration_order",
          "tests_runtime/test_health_store.py::test_runtime_reset_drops_a_populated_health_store"]

MUTANTS: list[tuple[str, str, str, str, list[str]]] = []


def m(mid: str, path: str, old: str, new: str, tests: list[str]) -> None:
    MUTANTS.append((mid, path, old, new, tests))


# -- 0003: every NOT NULL -----------------------------------------------------
for col, decl in [
        ("corpus_root", "  corpus_root      text not null,"),
        ("kind(run)", "  kind             text not null,"),
        ("started_at", "  started_at       timestamptz not null,"),
        ("finished_at", "  finished_at      timestamptz not null,"),
        ("outcome", "  outcome          text not null,"),
        ("pack_pins", "  pack_pins        jsonb not null,"),
        ("export_commit", "  export_commit    text not null,"),
        ("full_run", "  full_run         boolean not null,"),
        ("sandbox", "  sandbox          jsonb not null,"),
        ("finding.run_id", "  run_id            uuid not null references"),
        ("finding.id", "  id                text not null,"),
        ("finding.kind", "  kind              text not null,"),
        ("pack_id", "  pack_id           text not null,"),
        ("pack_version", "  pack_version      text not null,"),
        ("path", "  path              text not null,"),
        ("identity", "  identity          text not null,"),
        ("severity", "  severity          text not null,"),
        ("resolution_class", "  resolution_class  text not null,"),
        ("baseline_class", "  baseline_class    text not null,"),
        ("message", "  message           text not null,"),
        ("evidence", "  evidence          jsonb not null"),
]:
    m(f"sql-not-null:{col}", SQL, decl, decl.replace(" not null", ""), T_STORE)

# -- 0003: every CHECK, neutralized to `check (true)` ---------------------------
for name in ["health_runs_kind_check", "health_runs_outcome_check",
             "health_runs_commit_check", "health_runs_export_commit_hex_check",
             "health_runs_export_commit_check",
             "health_runs_default_tip_branch_check",
             "health_runs_pack_pins_check", "health_runs_sandbox_check",
             "health_findings_pack_id_check", "health_findings_pack_version_check",
             "health_findings_identity_check", "health_findings_locator_check",
             "health_findings_severity_check",
             "health_findings_resolution_class_check",
             "health_findings_baseline_class_check",
             "health_findings_evidence_check"]:
    m(f"sql-check:{name}", SQL, f"constraint {name} check (",
      f"constraint {name} check (true or ", T_STORE)

m("sql-check-part:pack_pins-no-opendox-key", SQL,
  "jsonb_typeof(pack_pins) = 'object' and pack_pins ? 'opendox'",
  "jsonb_typeof(pack_pins) = 'object'", T_STORE)
m("sql-check-part:sandbox-no-pids_max", SQL,
  " and coalesce(jsonb_typeof(sandbox -> 'pids_max'), 'absent') in ('number', 'null'))",
  ")", T_STORE)
m("sql-check-part:severity-admits-critical", SQL,
  "severity in ('error', 'warning', 'info')",
  "severity in ('error', 'warning', 'info', 'critical')", T_STORE)
m("sql-check-part:baseline-admits-unclassed", SQL,
  "baseline_class in ('new', 'pack-upgrade', 'persistent')",
  "baseline_class in ('new', 'pack-upgrade', 'persistent', 'unclassed')", T_STORE)
m("sql-fk:findings-run_id", SQL,
  " references health_runs (run_id) on delete cascade", "", T_STORE)
m("sql-pk:findings", SQL,
  "constraint health_findings_pkey primary key (run_id, id)",
  "constraint health_findings_pkey check (true)", T_STORE)
m("sql-unique:run_seq", SQL,
  "constraint health_runs_run_seq_key unique (run_seq)",
  "constraint health_runs_run_seq_key check (true)", T_STORE)
m("sql-full_run-reverted-to-bare-full", SQL,
  "  full_run         boolean not null,", "  full             boolean not null,",
  T_STORE)
m("sql-identity-as-jsonb", SQL,
  "  identity          text not null,", "  identity          jsonb not null,",
  T_STORE)
m("sql-patch-column-added", SQL,
  "  evidence          jsonb not null,",
  "  evidence          jsonb not null,\n  patch             text,", T_STORE)

# -- health_store.py: the guards ----------------------------------------------
m("py:provenance-refusal-removed", HS,
  "        if not isinstance(value, str) or not value:\n            raise RefusedError(\n                f\"finding {index} has no {field}.",
  "        if False:\n            raise RefusedError(\n                f\"finding {index} has no {field}.", T_STORE)
m("py:provenance-admits-empty", HS,
  "        if not isinstance(value, str) or not value:\n            raise RefusedError(\n                f\"finding {index} has no {field}.",
  "        if not isinstance(value, str):\n            raise RefusedError(\n                f\"finding {index} has no {field}.", T_STORE)
m("py:unknown-field-admitted", HS, "    if unknown:\n", "    if False:\n", T_STORE)
m("py:naive-datetime-admitted", HS,
  "if not isinstance(value, datetime) or value.utcoffset() is None:",
  "if not isinstance(value, datetime):", T_STORE)
m("py:full_run-bool-check-removed", HS,
  "        if not isinstance(full_run, bool):", "        if False:", T_STORE)
m("py:text-field-check-removed", HS, "    if not_text:\n", "    if False:\n", T_STORE)
m("py:evidence-mapping-check-removed", HS,
  "    if not isinstance(evidence, Mapping):", "    if False:", T_STORE)
m("py:identity-not-sorted", HS,
  "return json.dumps(value, sort_keys=True,", "return json.dumps(value, sort_keys=False,",
  T_STORE)
m("py:identity-ascii-escaped", HS, "ensure_ascii=False, allow_nan=False)",
  "ensure_ascii=True, allow_nan=False)", T_STORE)
m("py:latest-orders-by-clock", HS,
  "\"order by run_seq desc limit 1\", (corpus_root,)",
  "\"order by started_at desc limit 1\", (corpus_root,)", T_STORE)
m("py:baseline-orders-by-clock", HS,
  "\"order by run_seq desc limit 1\",\n            (corpus_root, baseline_branch,",
  "\"order by started_at desc limit 1\",\n            (corpus_root, baseline_branch,",
  T_STORE)
m("py:latest-ignores-corpus", HS,
  "f\"select {_RUN_SELECT} from health_runs where corpus_root = %s \"\n            \"order by run_seq desc limit 1\"",
  "f\"select {_RUN_SELECT} from health_runs where %s::text is not null \"\n            \"order by run_seq desc limit 1\"",
  T_STORE)
m("py:baseline-admits-partial", HS, "and outcome = 'complete' and full_run ",
  "and full_run ", T_STORE)
m("py:baseline-admits-pack-restricted", HS, "and outcome = 'complete' and full_run ",
  "and outcome = 'complete' ", T_STORE)
m("py:baseline-admits-any-kind", HS, "\"and kind = 'default-tip' and outcome",
  "\"and outcome", T_STORE)
m("py:baseline-ignores-branch", HS,
  "\"where corpus_root = %s and baseline_branch = %s \"",
  "\"where corpus_root = %s and %s::text is not null \"", T_STORE)
m("py:baseline-ignores-before_seq", HS, "or run_seq < %s)", "or %s::bigint is not null)",
  T_STORE)
m("py:list-ignores-resolution-filter", HS,
  "\"and (%s::text is null or resolution_class = %s) \"",
  "\"and (%s::text is null or %s::text is not null) \"", T_STORE)

# -- identity.TABLES, cli.DROP_ORDER, the token --------------------------------
m("tables:drop-health_runs", ID, "    \"health_runs\",\n    \"health_findings\",\n)",
  "    \"health_findings\",\n)", T_SHAPE + T_DEPLOY + T_STORE)
m("tables:drop-health_findings", ID, "    \"health_runs\",\n    \"health_findings\",\n)",
  "    \"health_runs\",\n)", T_SHAPE + T_DEPLOY + T_STORE)
m("drop-order:miss-health_findings", CLI,
  "    \"health_findings\",        # references health_runs\n", "", T_DROP)
m("drop-order:miss-health_runs", CLI,
  "    \"health_runs\",\n    \"drafts\",", "    \"drafts\",", T_DROP)
m("drop-order:runs-before-findings", CLI,
  "    \"health_findings\",        # references health_runs\n    \"health_runs\",\n",
  "    \"health_runs\",\n    \"health_findings\",        # references health_runs\n",
  T_DROP)
m("token:changed", CLI,
  "RESET_CONFIRMATION = \"yes-drop-the-coordination-database\"",
  "RESET_CONFIRMATION = \"yes-drop-the-coordination-and-health-database\"",
  ["tests_runtime/test_health_store.py::test_runtime_reset_drops_a_populated_health_store"])

# -- the closure reader, the arrays ---------------------------------------------
m("shape:reader-reads-0001-only", SHAPE, "for declaring in (CANONICAL, HEALTH)",
  "for declaring in (CANONICAL,)", T_SHAPE)
m("shape:ruled-without-health", SHAPE, "    \"health_runs\", \"health_findings\",\n)",
  ")", T_SHAPE)
m("deploy:compose-grant-misses-health_runs", COMPOSE,
  "any (array['drafts', 'health_findings', 'health_runs',",
  "any (array['drafts', 'health_findings',", T_DEPLOY)
m("deploy:k8s-guard-misses-health_findings", K8S,
  "all (array['drafts', 'health_findings', 'health_runs',",
  "all (array['drafts', 'health_runs',", T_DEPLOY)
m("deploy:docs-grant-misses-health_findings", DOCS,
  "any (array['drafts', 'health_findings', 'health_runs',",
  "any (array['drafts', 'health_runs',", T_DEPLOY)


# -- REVIEW-W1 (#99 6071241577) and the holder's 6072086385: the new guards
#    and lane 3's six surviving mutants, named as lane 3 named them ------------
m("w1:nul-json_text-check-removed", HS, "    _refuse_nul(value, what)\n    try:",
  "    try:", T_STORE)
m("w1:nul-finding-loop-removed", HS,
  "    for field in (*REQUIRED_FINDING_FIELDS, *OPTIONAL_FINDING_FIELDS):\n"
  "        _refuse_nul(finding.get(field), f\"finding {index}'s {field}\")\n",
  "", T_STORE)
m("w1:nul-run-fields-unchecked", HS, "            _refuse_nul(value, name)\n",
  "            pass\n", T_STORE)
m("w1:nul-keys-unchecked", HS, "any(_carries_nul(key) or _carries_nul(item)",
  "any(_carries_nul(item)", T_STORE)
m("w1:nul-lists-unchecked", HS,
  "    if isinstance(value, (list, tuple)):\n"
  "        return any(_carries_nul(item) for item in value)\n", "", T_STORE)
m("w1:pids_max-check-reverted", SQL,
  "case jsonb_typeof(sandbox -> 'pids_max') when 'null' then true when 'number' then "
  "(sandbox ->> 'pids_max')::numeric >= 0 and (sandbox ->> 'pids_max')::numeric = "
  "trunc((sandbox ->> 'pids_max')::numeric) else false end)",
  "coalesce(jsonb_typeof(sandbox -> 'pids_max'), 'absent') in ('number', 'null'))",
  T_STORE)
m("w1:pids_max-admits-fraction", SQL,
  " and (sandbox ->> 'pids_max')::numeric = trunc((sandbox ->> 'pids_max')::numeric)",
  "", T_STORE)
m("w1:pids_max-admits-negative", SQL, "(sandbox ->> 'pids_max')::numeric >= 0 and ",
  "", T_STORE)
m("w1:r1-cascade-removed", SQL,
  " references health_runs (run_id) on delete cascade",
  " references health_runs (run_id)", T_STORE)
m("w1:r3-locator-dropped", HS, "        record[\"locator\"] = dict(locator)\n",
  "        pass\n", T_STORE)
m("w1:r4-evidence-emptied", HS, "    record[\"evidence\"] = dict(evidence)\n",
  "    record[\"evidence\"] = {}\n", T_STORE)
m("w1:r5-message-overwritten", HS,
  "    record[\"identity\"] = canonical_identity(finding[\"identity\"])\n",
  "    record[\"identity\"] = canonical_identity(finding[\"identity\"])\n"
  "    record[\"message\"] = record[\"kind\"]\n", T_STORE)
m("w1:r6-limit-unclamped", HS, "             clamp_limit(limit))).fetchall()",
  "             limit)).fetchall()", T_STORE)
m("w1:r6b-limit-uncapped", HS, "             clamp_limit(limit))).fetchall()",
  "             max(limit, 1) if limit is not None else clamp_limit(None))).fetchall()",
  T_STORE)
m("w1:r16-by-default", SQL, "generated always as identity,",
  "generated by default as identity,", T_STORE)
m("w1:r16-cache-20", SQL, "generated always as identity,",
  "generated always as identity (cache 20),", T_STORE)


# -- w2: #656 6081875839 (cycle / depth; Copilot at fbf9e77e) ------------------
K_UNSTORABLE = ["tests_runtime/test_health_store.py", "-k", "unstorable"]
K_BOUND = ["tests_runtime/test_health_store.py", "-k", "exactly_to_the_bound"]
K_SHARED = ["tests_runtime/test_health_store.py", "-k", "shared_by_two"]
K_NUL = ["tests_runtime/test_health_store.py", "-k", "nul"]
m("w2:cycle-check-removed", HS,
  "        if id(item) in on_path:\n            return \"cycle\"\n", "", K_UNSTORABLE)
m("w2:depth-check-removed", HS,
  "        if depth > MAX_JSON_DEPTH:\n            return \"depth\"\n", "", K_UNSTORABLE)
m("w2:depth-off-by-one-strict", HS, "        if depth > MAX_JSON_DEPTH:\n",
  "        if depth >= MAX_JSON_DEPTH:\n", K_BOUND)
m("w2:depth-one-level-loose", HS, "        if depth > MAX_JSON_DEPTH:\n",
  "        if depth > MAX_JSON_DEPTH + 1:\n", K_UNSTORABLE)
m("w2:path-never-left", HS, "            on_path.discard(id(item))\n",
  "            pass\n", K_SHARED)
m("w2:keys-not-walked", HS,
  "        return [part for pair in item.items() for part in pair]\n",
  "        return list(item.values())\n", K_NUL)
m("w2:lists-not-walked", HS,
  "    if isinstance(item, (list, tuple)):\n        return list(item)\n",
  "    if isinstance(item, (list, tuple)):\n        return []\n", K_UNSTORABLE)
m("w2:json_text-walk-removed", HS,
  "    _refuse_unstorable(value, what)\n    return _dumps(value, what)\n",
  "    return _dumps(value, what)\n", K_UNSTORABLE)
m("w2:finding-field-walk-removed", HS,
  "        _refuse_unstorable(finding.get(field), f\"finding {index}'s {field}\")\n",
  "        pass\n", K_UNSTORABLE)
m("w2:records-rewalked", HS,
  "        findings_text = _dumps(records, \"the run's findings\")\n",
  "        findings_text = _json_text(records, \"the run's findings\")\n", K_BOUND)
m("w2:nul-check-removed", HS,
  "    if \"\\x00\" in text:\n        return \"nul\"\n",
  "    if False:\n        return \"nul\"\n", K_NUL)

# -- w4: Copilot at 01f4192d (a lone surrogate is a named refusal) ---------------
K_SURROGATE = ["tests_runtime/test_health_store.py", "-k", "lone_surrogate"]
m("w4:surrogate-check-removed", HS, "    if _SURROGATE.search(text):\n",
  "    if False:\n", K_SURROGATE)
m("w4:surrogate-range-high-only", HS, "_SURROGATE = re.compile(\"[\\ud800-\\udfff]\")",
  "_SURROGATE = re.compile(\"[\\ud800-\\udbff]\")", K_SURROGATE)
m("w4:text-check-skipped-in-walk", HS,
  "            reason = _text_unstorable(item)\n            if reason is not None:\n                return reason\n",
  "", K_SURROGATE)

# -- w3: #656 6086098003 item 3 (c) (U+0000 in every bound text parameter) ------
K_READS = ["tests_runtime/test_health_store.py", "-k", "nul_in_a_read"]
K_PATH = ["tests_runtime/test_health_store.py", "-k", "nul_is_refused_by_name and path or nul_in_a_path"]
m("w3:latest-run-guard-removed", HS,
  "        _refuse_nul_parameters(corpus_root=corpus_root)\n", "", K_READS)
m("w3:baseline-run-guard-removed", HS,
  "        _refuse_nul_parameters(corpus_root=corpus_root,\n"
  "                               baseline_branch=baseline_branch)\n", "", K_READS)
m("w3:get-finding-guard-removed", HS,
  "        _refuse_nul_parameters(**{\"id (finding_id)\": finding_id})\n", "", K_READS)
m("w3:list-findings-guard-removed", HS,
  "        _refuse_nul_parameters(**{\"id (after)\": after},\n"
  "                               resolution_class=resolution_class,\n"
  "                               baseline_class=baseline_class)\n", "", K_READS)
m("w3:parameter-walk-noop", HS,
  "    for column, value in columns.items():\n        _refuse_unstorable(value, column)\n",
  "    for column, value in columns.items():\n        pass\n", K_READS)
m("w3:path-unchecked", HS,
  "    for field in (*REQUIRED_FINDING_FIELDS, *OPTIONAL_FINDING_FIELDS):\n"
  "        _refuse_unstorable(",
  "    for field in (*REQUIRED_FINDING_FIELDS, *OPTIONAL_FINDING_FIELDS):\n"
  "        if field == \"path\":\n            continue\n        _refuse_unstorable(", K_PATH)

def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=CLONE, check=True,
                          capture_output=True, text=True).stdout


def main() -> int:
    if git("status", "--porcelain").strip():
        print("REFUSED: the clone is dirty"); return 2
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "XF_"))}
    env.update(LANG="C.UTF-8", TMPDIR=str(STATE), CI="true",
               OPENDOX_TEST_DATABASE_URL="postgresql://opendox:opendox@host.docker.internal:55460/opendox")
    killed = survived = 0
    for mid, path, old, new, tests in MUTANTS:
        if ONLY and ONLY not in mid:
            continue
        f = CLONE / path
        text = f.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"BAD-MUTANT {mid}: old text found {text.count(old)} times", flush=True)
            return 3
        f.write_text(text.replace(old, new), encoding="utf-8")
        try:
            run = subprocess.run(
                [PY, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider",
                 f"--basetemp={STATE}/pt-mut", "-rfE", *tests],
                cwd=CLONE, env=env, capture_output=True, text=True, timeout=1500)
        finally:
            git("checkout", "--", path)
        if git("status", "--porcelain").strip():
            print("REFUSED: the tree is dirty after a restore"); return 4
        first = next((line for line in run.stdout.splitlines()
                      if re.match(r"^(FAILED|ERROR) ", line)), "")
        if run.returncode == 0:
            survived += 1
            print(f"SURVIVED {mid}", flush=True)
        else:
            killed += 1
            print(f"KILLED   {mid} (rc={run.returncode}) by {first[:200]}", flush=True)
    print(f"TOTAL killed={killed} survived={survived}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
