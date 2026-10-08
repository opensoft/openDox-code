"""T042 (plan 038, HA-1): the health store, `0003_health.sql` and its writer.

The falsifier T042 names: `test_the_store_refuses_a_finding_without_provenance`
(#1144 box 15.7) and `test_an_install_level_finding_is_admitted` (`pack_id`
`opendox`, an empty `path`; OQ-H15-19), beside the tests that hold the store to
boxes 14.1 to 14.3 — `0003_` additive, the two tables DOMAIN (R2Q13 (a)), and
NO DOCUMENT, so no patch column (14.3; R2Q25 (a)).

DB-BACKED where it says so (the `database` fixture: a throwaway schema with
every migration applied — `0003_` included, which is half the point), and
HERMETIC where a refusal must come BEFORE any statement: those cases hand the
store a connection that fails the test if a statement reaches it, because a
refusal the schema makes instead would look the same from the outside and
prove nothing about the store.

Every schema case writes RAW SQL, past the store, because "no path can store a
finding without them" (15.7) is a claim about the schema and not about the one
writer this package ships.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from opendox.runtime import identity
from opendox.runtime.health_store import (
    HealthStore,
    canonical_identity,
)
from opendox.runtime.identity import ConflictError, NotFoundError, RefusedError

HEX = "a" * 40
OTHER_HEX = "b" * 40
T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

#: data-model.md's two tables, column by column, in table order, with the ones
#: it makes nullable. `full_run` is the model's `full` (the holder, #656
#: `6064169640`); `run_seq` is the order runs were recorded in (`0003_`'s
#: header). There is no `patch` column and there is never going to be one
#: here (14.3; lane 3's MISLABEL row 31).
COLUMNS: dict[str, tuple[str, ...]] = {
    "health_runs": (
        "run_id", "run_seq", "corpus_root", "kind", "commit",
        "baseline_branch", "started_at", "finished_at", "outcome",
        "pack_pins", "export_commit", "full_run", "sandbox"),
    "health_findings": (
        "run_id", "id", "kind", "pack_id", "pack_version", "path", "identity",
        "locator", "severity", "resolution_class", "baseline_class", "message",
        "evidence"),
}
NULLABLE: dict[str, frozenset[str]] = {
    "health_runs": frozenset({"commit", "baseline_branch"}),
    "health_findings": frozenset({"locator"}),
}


def _run_kwargs(**over: Any) -> dict[str, Any]:
    """`record_run`'s arguments for one complete, full default-tip run."""
    base: dict[str, Any] = {
        "corpus_root": "/corpora/a", "kind": "default-tip", "commit": HEX,
        "baseline_branch": "main", "started_at": T0, "finished_at": T0,
        "outcome": "complete",
        "pack_pins": {"opendox": {"version": "0.2.0", "digest": None,
                                  "commit": None}},
        "export_commit": HEX, "full_run": True,
        "sandbox": {"live": True, "pids_max": None}, "findings": [],
    }
    base.update(over)
    return base


def _finding(**over: Any) -> dict[str, Any]:
    """The contract's own example finding (contracts/health-finding.md)."""
    base: dict[str, Any] = {
        "id": "opendox.broken-link.3c1f0e9a7b2d4c65", "kind": "broken-link",
        "pack_id": "opendox", "pack_version": "0.2.0", "path": "notes/plan.md",
        "identity": {"target": "../old/brief.md"},
        "locator": {"line_start": 12, "line_end": 12},
        "severity": "warning", "resolution_class": "auto-fix",
        "baseline_class": "new",
        "message": "link target does not exist; a unique file of that name "
                   "exists elsewhere",
        "evidence": {"candidate": "archive/brief.md", "family_version": "1"},
    }
    base.update(over)
    return base


class _NoStatement:
    """A connection the store must never reach: any statement fails the test."""

    def execute(self, sql: str, params: Any = None) -> Any:
        raise AssertionError(f"a statement reached the database: {sql[:60]}")


def _record(database: Any, **over: Any):
    """Record one run in its own committed transaction."""
    with database.transaction() as conn:
        return HealthStore(conn).record_run(**_run_kwargs(**over))


def _count(database: Any, table: str) -> int:
    with database.connection() as conn:
        return conn.execute(f"select count(*) from {table}").fetchone()[0]


def _raw(database: Any, sql: str, params: dict[str, Any]) -> Exception | None:
    """One raw statement in its own transaction: its refusal, or None."""
    try:
        with database.transaction() as conn:
            conn.execute(sql, params)
    except Exception as exc:  # noqa: BLE001
        return exc
    return None


_RAW_RUN = (
    "insert into health_runs (run_id, corpus_root, kind, commit, "
    "baseline_branch, started_at, finished_at, outcome, pack_pins, "
    "export_commit, full_run, sandbox) values (%(run_id)s::uuid, "
    "%(corpus_root)s, %(kind)s, %(commit)s, %(baseline_branch)s, "
    "%(started_at)s, %(finished_at)s, %(outcome)s, %(pack_pins)s::jsonb, "
    "%(export_commit)s, %(full_run)s, %(sandbox)s::jsonb)")

_RAW_FINDING = (
    "insert into health_findings (run_id, id, kind, pack_id, pack_version, "
    "path, identity, locator, severity, resolution_class, baseline_class, "
    "message, evidence) values (%(run_id)s::uuid, %(id)s, %(kind)s, "
    "%(pack_id)s, %(pack_version)s, %(path)s, %(identity)s, "
    "%(locator)s::jsonb, %(severity)s, %(resolution_class)s, "
    "%(baseline_class)s, %(message)s, %(evidence)s::jsonb)")


def _raw_run(**over: Any) -> dict[str, Any]:
    base = {
        "run_id": str(uuid.uuid4()), "corpus_root": "/corpora/raw",
        "kind": "default-tip", "commit": HEX, "baseline_branch": "main",
        "started_at": T0, "finished_at": T0, "outcome": "complete",
        "pack_pins": '{"opendox": {"version": "0.2.0"}}',
        "export_commit": HEX, "full_run": True,
        "sandbox": '{"live": false, "pids_max": null}',
    }
    base.update(over)
    return base


def _raw_finding(run_id: str, **over: Any) -> dict[str, Any]:
    base = {
        "run_id": run_id, "id": "opendox.orphan.0123456789abcdef",
        "kind": "orphan", "pack_id": "opendox", "pack_version": "0.2.0",
        "path": "a.md", "identity": '{"path":"a.md"}', "locator": None,
        "severity": "info", "resolution_class": "human-only",
        "baseline_class": "new", "message": "nothing links to it",
        "evidence": "{}",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# THE FALSIFIER'S TWO NAMED CASES
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", [
    {"drop": "pack_id"}, {"drop": "pack_version"},
    {"pack_id": None}, {"pack_version": None},
    {"pack_id": ""}, {"pack_version": ""},
], ids=["no-pack_id", "no-pack_version", "null-pack_id", "null-pack_version",
        "empty-pack_id", "empty-pack_version"])
def test_the_store_refuses_a_finding_without_provenance(
        database: Any, missing: dict[str, Any]) -> None:
    """Box 15.7: "no path can store a finding without them".

    Three layers, each measured on its own, so that no one of them can stand
    in for another: the STORE refuses before any statement (a connection that
    fails on a statement proves it); over a real database it refuses and the
    run row it would have written is not there either; and the SCHEMA refuses
    the same row written raw, past the store — a null by `not null`, an empty
    string by the column's check.
    """
    finding = _finding()
    field = missing.get("drop")
    if field:
        del finding[field]
    else:
        finding.update(missing)
        field = next(iter(missing))

    with pytest.raises(RefusedError) as caught:
        HealthStore(_NoStatement()).record_run(**_run_kwargs(findings=[finding]))
    assert f"has no {field}" in str(caught.value)
    assert "15.7" in str(caught.value)

    with pytest.raises(RefusedError):
        _record(database, findings=[finding])
    assert _count(database, "health_runs") == 0
    assert _count(database, "health_findings") == 0

    run = _record(database)
    value = None if field not in missing or missing.get(field) is None else ""
    refused = _raw(database, _RAW_FINDING,
                   _raw_finding(run.run_id, **{field: value}))
    assert refused is not None, f"the schema stored a finding with no {field}"
    if value is None:
        assert refused.sqlstate == "23502", refused          # not_null_violation
        assert refused.diag.column_name == field
    else:
        assert refused.sqlstate == "23514", refused          # check_violation
        assert refused.diag.constraint_name == f"health_findings_{field}_check"
    assert _count(database, "health_findings") == 0


def test_an_install_level_finding_is_admitted(database: Any) -> None:
    """OQ-H15-19: `pack_id` `opendox`, an EMPTY `path`, `human-only`.

    The finding a run without a live sandbox records (R2Q16 (a)), with the
    engine-owned identity key a pathless finding carries
    (contracts/health-finding.md: `{category, entry}`). An empty `path` is a
    value, not an absence, so `not null` must not refuse it.
    """
    finding = _finding(
        id="opendox.no-sandbox.00112233aabbccdd", kind="no-sandbox", path="",
        identity={"category": "no-sandbox", "entry": ""}, locator=None,
        severity="error", resolution_class="human-only",
        message="no live sandbox, so no pack ran", evidence={})
    run = _record(database, outcome="partial",
                  sandbox={"live": False, "pids_max": None},
                  findings=[finding])
    with database.connection() as conn:
        stored = HealthStore(conn).get_finding(run_id=run.run_id,
                                               finding_id=finding["id"])
        listed = HealthStore(conn).list_findings(run_id=run.run_id)
    assert stored.pack_id == "opendox"
    assert stored.path == ""
    assert stored.identity == {"category": "no-sandbox", "entry": ""}
    assert stored.locator is None
    assert stored.evidence == {}
    assert stored.resolution_class == "human-only"
    assert listed == [stored]


# ---------------------------------------------------------------------------
# the schema: exactly the data model's columns, and nothing that holds a document
# ---------------------------------------------------------------------------


def test_the_tables_hold_exactly_the_data_models_columns(database: Any) -> None:
    """Read off the APPLIED schema, not the file: what Postgres made of `0003_`.

    The column list is closed, so a `patch` column, a `full` spelled bare, or a
    nullable provenance column is a red here before it is anything else.
    """
    with database.connection() as conn:
        for table, expected in COLUMNS.items():
            rows = conn.execute(
                "select column_name, is_nullable from information_schema.columns "
                "where table_schema = current_schema() and table_name = %s "
                "order by ordinal_position", (table,)).fetchall()
            assert tuple(name for name, _ in rows) == expected, table
            nullable = {name for name, flag in rows if flag == "YES"}
            assert nullable == NULLABLE[table], (
                f"{table}: nullable {sorted(nullable)}, the data model "
                f"{sorted(NULLABLE[table])}")
    assert "patch" not in COLUMNS["health_findings"]
    assert "full_run" in COLUMNS["health_runs"]
    assert "full" not in COLUMNS["health_runs"]


def test_the_health_tables_are_domain_tables(database: Any) -> None:
    """R2Q13 (a): both join `identity.TABLES`, so reset, the closure test and
    the served role's access check all reach them, and the runner created them."""
    assert identity.TABLES[-2:] == ("health_runs", "health_findings")
    with database.connection() as conn:
        present = {row[0] for row in conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = current_schema()").fetchall()}
    assert {"health_runs", "health_findings"} <= present


_NOT_NULL_RUN = sorted(set(COLUMNS["health_runs"]) - NULLABLE["health_runs"]
                       - {"run_seq"})
_NOT_NULL_FINDING = sorted(set(COLUMNS["health_findings"])
                           - NULLABLE["health_findings"])


@pytest.mark.parametrize("column", _NOT_NULL_RUN)
def test_every_not_null_run_column_refuses_a_null(database: Any,
                                                  column: str) -> None:
    """`run_seq` is absent here because the server assigns it: an identity
    column `generated always` refuses ANY value, null or not."""
    refused = _raw(database, _RAW_RUN, _raw_run(**{column: None}))
    assert refused is not None, f"health_runs.{column} admitted a null"
    assert refused.sqlstate == "23502", refused
    assert refused.diag.column_name == column


@pytest.mark.parametrize("column", _NOT_NULL_FINDING)
def test_every_not_null_finding_column_refuses_a_null(database: Any,
                                                      column: str) -> None:
    run = _record(database)
    refused = _raw(database, _RAW_FINDING,
                   _raw_finding(run.run_id, **{column: None}))
    assert refused is not None, f"health_findings.{column} admitted a null"
    assert refused.sqlstate == "23502", refused
    assert refused.diag.column_name == column


#: One row per CHECK in `0003_`: the one value that breaks it ALONE, and the
#: constraint the server must name. Each vocabulary is the data model's (and
#: 14.6's for the resolution classes, "in the store … alike").
_RUN_CHECKS = [
    ({"kind": "nightly"}, "health_runs_kind_check"),
    ({"outcome": "done"}, "health_runs_outcome_check"),
    ({"kind": "working-state"}, "health_runs_commit_check"),
    ({"kind": "branch", "commit": None}, "health_runs_commit_check"),
    ({"commit": "A" * 40, "export_commit": "A" * 40},
     "health_runs_export_commit_hex_check"),
    ({"commit": "abc123", "export_commit": "abc123"},
     "health_runs_export_commit_hex_check"),
    ({"kind": "working-state", "commit": None, "export_commit": "HEAD"},
     "health_runs_export_commit_hex_check"),
    ({"export_commit": OTHER_HEX}, "health_runs_export_commit_check"),
    ({"baseline_branch": None}, "health_runs_default_tip_branch_check"),
    ({"pack_pins": "[]"}, "health_runs_pack_pins_check"),
    ({"pack_pins": '{"some-pack": {"version": "1"}}'},
     "health_runs_pack_pins_check"),
    ({"sandbox": "{}"}, "health_runs_sandbox_check"),
    ({"sandbox": '{"pids_max": null}'}, "health_runs_sandbox_check"),
    ({"sandbox": '{"live": "yes", "pids_max": null}'},
     "health_runs_sandbox_check"),
    ({"sandbox": '{"live": true}'}, "health_runs_sandbox_check"),
    ({"sandbox": '{"live": true, "pids_max": "512"}'},
     "health_runs_sandbox_check"),
    ({"sandbox": "[true]"}, "health_runs_sandbox_check"),
]

_FINDING_CHECKS = [
    ({"identity": "[]"}, "health_findings_identity_check"),
    ({"identity": '"a key"'}, "health_findings_identity_check"),
    ({"locator": "[12]"}, "health_findings_locator_check"),
    ({"severity": "critical"}, "health_findings_severity_check"),
    ({"resolution_class": "auto_fix"},
     "health_findings_resolution_class_check"),
    ({"baseline_class": "unclassed"}, "health_findings_baseline_class_check"),
    ({"evidence": "[]"}, "health_findings_evidence_check"),
]


@pytest.mark.parametrize(("over", "constraint"), _RUN_CHECKS,
                         ids=[f"{c}:{','.join(o)}" for o, c in _RUN_CHECKS])
def test_each_run_check_refuses_what_it_names(database: Any, over: dict,
                                              constraint: str) -> None:
    refused = _raw(database, _RAW_RUN, _raw_run(**over))
    assert refused is not None, f"{over} was admitted"
    assert refused.sqlstate == "23514", refused
    assert refused.diag.constraint_name == constraint
    assert _count(database, "health_runs") == 0


@pytest.mark.parametrize(("over", "constraint"), _FINDING_CHECKS,
                         ids=[f"{c}:{','.join(o)}" for o, c in _FINDING_CHECKS])
def test_each_finding_check_refuses_what_it_names(database: Any, over: dict,
                                                  constraint: str) -> None:
    run = _record(database)
    refused = _raw(database, _RAW_FINDING, _raw_finding(run.run_id, **over))
    assert refused is not None, f"{over} was admitted"
    assert refused.sqlstate == "23514", refused
    assert refused.diag.constraint_name == constraint
    assert _count(database, "health_findings") == 0


@pytest.mark.parametrize("over", [
    {},
    {"kind": "branch", "baseline_branch": None},
    {"kind": "working-state", "commit": None, "export_commit": OTHER_HEX},
    {"outcome": "partial", "full_run": False},
    {"outcome": "refused"},
    {"sandbox": '{"live": true, "pids_max": 512}'},
    {"pack_pins": '{"opendox": {"version": "0.2.0"}, "gov": {"version": "1", '
                  '"digest": "sha256:00", "commit": null}}'},
], ids=["default-tip", "branch-no-baseline-branch", "working-state",
        "partial-pack-restricted", "refused", "pids-max", "two-packs"])
def test_the_checks_admit_every_run_the_data_model_describes(
        database: Any, over: dict) -> None:
    """The other half of each check: the rows data-model.md describes go in."""
    assert _raw(database, _RAW_RUN, _raw_run(**over)) is None


def test_the_schema_refuses_identity_text_that_is_not_json(database: Any) -> None:
    run = _record(database)
    refused = _raw(database, _RAW_FINDING,
                   _raw_finding(run.run_id, identity="{not json"))
    assert refused is not None
    assert refused.sqlstate == "22P02", refused   # invalid_text_representation


def test_a_finding_must_name_a_recorded_run(database: Any) -> None:
    refused = _raw(database, _RAW_FINDING, _raw_finding(str(uuid.uuid4())))
    assert refused is not None
    assert refused.sqlstate == "23503", refused   # foreign_key_violation


# ---------------------------------------------------------------------------
# the store: no document, the canonical identity, one atomic run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["patch", "text", "excerpt", "content",
                                   "document"])
def test_the_store_keeps_no_patch_and_no_document(field: str) -> None:
    """14.3 and R2Q25 (a), at the API: a field outside the columns is refused
    by NAME, before any statement — never silently dropped."""
    with pytest.raises(RefusedError) as caught:
        HealthStore(_NoStatement()).record_run(**_run_kwargs(
            findings=[_finding(**{field: "the text of a document"})]))
    assert repr(field) in str(caught.value)
    assert "the text of a document" not in str(caught.value)


def test_identity_is_stored_as_the_canonical_text_it_was_hashed_as(
        database: Any) -> None:
    """The holder, `6018624750`: STORED, canonical sorted-key JSON.

    `jsonb` would re-order the keys and re-space the text; the column is text
    so the bytes are the ones the engine hashed into `id`. Non-ASCII stays
    itself (`ensure_ascii=False`, the finding schema header's spelling).
    """
    key = {"zeta": "ü", "alpha": ["b", "a"], "mid": {"y": "1", "x": "2"}}
    expected = json.dumps(key, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False)
    assert canonical_identity(key) == expected
    run = _record(database, findings=[_finding(identity=key)])
    with database.connection() as conn:
        text = conn.execute(
            "select identity from health_findings where run_id = %s::uuid",
            (run.run_id,)).fetchone()[0]
        stored = HealthStore(conn).list_findings(run_id=run.run_id)[0]
    assert text == expected
    assert stored.identity == key


def test_two_findings_with_one_id_in_one_run_store_nothing(database: Any) -> None:
    """The engine reports a collision as ONE finding and stores neither
    (contracts/health-finding.md); a run that reaches the store with two is a
    CONFLICT, and the caller's transaction takes the run row with it."""
    twice = [_finding(), _finding(path="other.md")]
    with pytest.raises(ConflictError):
        _record(database, findings=twice)
    assert _count(database, "health_runs") == 0
    assert _count(database, "health_findings") == 0


def test_a_vocabulary_the_schema_refuses_is_a_named_refusal(database: Any) -> None:
    with pytest.raises(RefusedError) as caught:
        _record(database, findings=[_finding(severity="critical")])
    assert "health_findings_severity_check" in str(caught.value)
    with pytest.raises(RefusedError) as caught:
        _record(database, kind="nightly")
    assert "health_runs_kind_check" in str(caught.value)
    assert _count(database, "health_runs") == 0


@pytest.mark.parametrize(("over", "says"), [
    ({"started_at": datetime(2026, 10, 8, 12, 0)}, "timezone-aware"),
    ({"finished_at": datetime(2026, 10, 8, 12, 0)}, "timezone-aware"),
    ({"full_run": 1}, "full_run must be a boolean"),
    ({"pack_pins": [["opendox", "0.2.0"]]}, "pack_pins must be"),
    ({"sandbox": "live"}, "sandbox must be"),
    ({"sandbox": {"live": True, "pids_max": float("nan")}}, "sandbox is not JSON"),
    ({"findings": ["opendox.orphan.0123456789abcdef"]}, "is not a mapping"),
    ({"findings": [_finding(identity=["target"])]}, "identity must be"),
    ({"findings": [_finding(evidence=None)]}, "evidence must be"),
    ({"findings": [_finding(locator=[12, 12])]}, "locator must be"),
    ({"findings": [_finding(kind=7)]}, "must be strings"),
    ({"findings": [{k: v for k, v in _finding().items() if k != "message"}]},
     "has no ['message']"),
], ids=["naive-start", "naive-finish", "full-run-int", "pins-list",
        "sandbox-text", "sandbox-nan", "finding-text", "identity-list",
        "evidence-none", "locator-list", "kind-int", "no-message"])
def test_malformed_input_is_refused_before_any_statement(over: dict,
                                                         says: str) -> None:
    with pytest.raises(RefusedError) as caught:
        HealthStore(_NoStatement()).record_run(**_run_kwargs(**over))
    assert says in str(caught.value)


# ---------------------------------------------------------------------------
# reads: the order of record, the baseline, one corpus at a time
# ---------------------------------------------------------------------------


def test_runs_are_ordered_by_record_and_not_by_clock(database: Any) -> None:
    """`0003_`'s header: the clock can step backwards. A run that REPORTS a
    start in the future does not stay the latest once a later one is recorded."""
    first = _record(database, started_at=datetime(2031, 1, 1, tzinfo=UTC),
                    finished_at=datetime(2031, 1, 1, tzinfo=UTC))
    second = _record(database, started_at=datetime(2001, 1, 1, tzinfo=UTC),
                     finished_at=datetime(2001, 1, 1, tzinfo=UTC))
    assert second.run_seq > first.run_seq
    with database.connection() as conn:
        store = HealthStore(conn)
        assert store.latest_run(corpus_root="/corpora/a") == second
        assert store.baseline_run(corpus_root="/corpora/a",
                                  baseline_branch="main") == second


def test_the_baseline_is_the_latest_complete_full_default_tip_run(
        database: Any) -> None:
    """R2Q12 (a), data-model.md § Baseline classes: same corpus, same baseline
    branch, default-tip, complete AND full. Every other run is recorded after
    the baseline and none of them may displace it."""
    baseline = _record(database)
    _record(database, outcome="partial")                        # a pack failed
    _record(database, full_run=False)                           # `--pack`
    _record(database, kind="branch", commit=OTHER_HEX, export_commit=OTHER_HEX)
    _record(database, kind="working-state", commit=None)
    _record(database, baseline_branch="trunk")                  # another branch
    _record(database, corpus_root="/corpora/b")                 # another corpus
    with database.connection() as conn:
        store = HealthStore(conn)
        assert store.baseline_run(corpus_root="/corpora/a",
                                  baseline_branch="main") == baseline
        assert store.baseline_run(corpus_root="/corpora/a",
                                  baseline_branch="main",
                                  before_seq=baseline.run_seq) is None
        assert store.baseline_run(corpus_root="/corpora/a",
                                  baseline_branch=None) is None
        assert store.baseline_run(corpus_root="/corpora/c",
                                  baseline_branch="main") is None


def test_two_corpora_in_one_store_never_read_each_others_runs(
        database: Any) -> None:
    a1 = _record(database, findings=[_finding()])
    b1 = _record(database, corpus_root="/corpora/b",
                 findings=[_finding(path="b.md")])
    a2 = _record(database)
    with database.connection() as conn:
        store = HealthStore(conn)
        assert store.latest_run(corpus_root="/corpora/a") == a2
        assert store.latest_run(corpus_root="/corpora/b") == b1
        assert store.latest_run(corpus_root="/corpora/none") is None
        assert [f.path for f in store.list_findings(run_id=b1.run_id)] == ["b.md"]
        assert [f.path for f in store.list_findings(run_id=a1.run_id)] == [
            "notes/plan.md"]
        assert store.list_findings(run_id=a2.run_id) == []


def test_a_runs_findings_page_by_id_and_filter_by_class(database: Any) -> None:
    findings = [
        _finding(id=f"opendox.orphan.{n:016x}", kind="orphan", path=f"{n}.md",
                 identity={"path": f"{n}.md"}, resolution_class=cls,
                 baseline_class=base)
        for n, cls, base in [(1, "human-only", "new"),
                             (2, "auto-fix", "persistent"),
                             (3, "human-only", "pack-upgrade")]]
    run = _record(database, findings=findings)
    with database.connection() as conn:
        store = HealthStore(conn)
        page = store.list_findings(run_id=run.run_id, limit=2)
        rest = store.list_findings(run_id=run.run_id, after=page[-1].id)
        assert [f.id for f in page + rest] == sorted(f["id"] for f in findings)
        assert len(page) == 2
        assert [f.path for f in store.list_findings(
            run_id=run.run_id, resolution_class="human-only")] == ["1.md", "3.md"]
        assert [f.path for f in store.list_findings(
            run_id=run.run_id, baseline_class="persistent")] == ["2.md"]
        assert store.get_run(run.run_id) == run


def test_an_unknown_run_or_finding_is_not_found(database: Any) -> None:
    run = _record(database)
    with database.connection() as conn:
        store = HealthStore(conn)
        with pytest.raises(NotFoundError):
            store.get_run(str(uuid.uuid4()))
        with pytest.raises(NotFoundError):
            store.get_run("not-a-run")
        with pytest.raises(NotFoundError):
            store.get_finding(run_id=run.run_id, finding_id="opendox.x.0")


def test_the_served_role_can_record_and_read_a_run(database: Any) -> None:
    """The served role holds TABLE grants only — the init scripts' join and
    their default privileges, both `on table`/`on tables` — and must still
    write `run_seq`. MEASURED: an identity column needs no sequence grant."""
    role = "t_served_" + uuid.uuid4().hex[:8]
    with database.transaction() as conn:
        conn.execute(f"create role {role}")
        conn.execute(f"grant usage on schema {database.schema} to {role}")
        conn.execute("grant select, insert, update, delete on table "
                     f"health_runs, health_findings to {role}")
    try:
        with database.transaction() as conn:
            conn.execute(f"set local role {role}")
            run = HealthStore(conn).record_run(**_run_kwargs(
                findings=[_finding()]))
            assert HealthStore(conn).get_run(run.run_id) == run
        assert _count(database, "health_findings") == 1
    finally:
        with database.transaction() as conn:
            conn.execute(f"drop owned by {role}")
            conn.execute(f"drop role {role}")


def test_runtime_reset_drops_a_populated_health_store(
        database: Any, postgres_dsn: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """14.3's "stays DISPOSABLE", through the verb F14.1 runs.

    A run WITH a finding, so `health_findings` references `health_runs` when
    the drop runs: `drop table` without `cascade` refuses a referenced table,
    so a `DROP_ORDER` that put `health_runs` first, or left either table out,
    fails here on the database rather than only in the order's own test. The
    token is `RESET_CONFIRMATION`, byte-identical to F14.1's command.
    """
    import io
    from contextlib import redirect_stdout

    from opendox.runtime import cli
    from opendox.runtime.config import PREFIX

    assert cli.RESET_CONFIRMATION == "yes-drop-the-coordination-database"
    _record(database, findings=[_finding()])
    separator = "&" if "?" in postgres_dsn else "?"
    monkeypatch.setenv(PREFIX + "MIGRATION_DATABASE_URL",
                       f"{postgres_dsn}{separator}"
                       f"options=-csearch_path%3D{database.schema}%2Cpublic")
    args = cli.build_parser().parse_args(
        ["runtime", "reset", "--confirm", cli.RESET_CONFIRMATION])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = args.func(args)
    evidence = json.loads(buffer.getvalue())
    assert code == 0, evidence
    assert evidence["dropped"][:2] == ["health_findings", "health_runs"]
    with database.connection() as conn:
        left = conn.execute(
            "select table_name from information_schema.tables "
            "where table_schema = current_schema()").fetchall()
    assert left == [], f"the reset left {[row[0] for row in left]}"
