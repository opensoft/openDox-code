"""The health store: the runs and findings `migrations/0003_health.sql` declares.

RULED DOMAIN (R2Q13 (a), Brett Heap, opensoft/openxFactory#656 comment
6003486656): `health_runs` and `health_findings` join RULING Q1's six in
`identity.TABLES`, so the closure test, `runtime reset` and the served role's
access check all read them. This module is the only writer of the two tables,
as `identity.CoordinationStore` is of the six.

IT STORES NO DOCUMENT (#1144 box 14.3; R2Q25 (a)). A finding ADDRESSES a
document — a corpus-relative `path`, a display-only `locator` — and never
carries its text. There is no patch column (lane 3's MISLABEL row 31), and
`record_run` REFUSES any finding field outside the table's columns, by name,
before a statement runs: a caller that hands this store a `patch`, a `text` or
an `excerpt` learns at once that it is not kept, rather than finding out from
a column that silently dropped it. The FIELD BOUNDS — the id grammar,
`identity`'s serialized-size cap, `message`'s 200 characters, the keys
`evidence` may not use — are the contract module's (`health_contract`, T041),
which the engine applies before it calls here; this store is not a second
spelling of them, and imports nothing from it.

WHAT POSTGRESQL OR JSON CANNOT KEEP IS REFUSED BY NAME, before any statement:
a NUL or a lone surrogate anywhere in a field or a bound text parameter, a
value that contains itself, and a value nested deeper than `MAX_JSON_DEPTH`
(the holder, opensoft/openxFactory#656 comments 6072086385 item 4, 6081875839
and 6086098003 item 3 (c)). These are not field bounds but what the store can
hold at all, so the driver's NUL and encoding errors and `RecursionError`
never leave it.

PROVENANCE IS REFUSED HERE AND IN THE SCHEMA (box 15.7). A finding with no
`pack_id` or no `pack_version` — absent, null or empty — is refused by
`record_run` before any statement runs, and `0003_`'s `not null` and
non-empty checks refuse the same row from any other path. "Enforced at the
store and not only in the engine" is the box's own phrase.

RUNS ARE ORDERED BY `run_seq`, which the server assigns at insert, and never
by `started_at` (`0003_`'s header: this host's clock "can step backwards under
load"). So "the latest run" and the baseline's "latest earlier default-tip
run" (R2Q12 (a)) are the latest RECORDED, and a run reporting a start time in
the past or the future cannot move itself.

ONE RUN IS RECORDED IN ONE CALL, with all of its findings, in two statements
on the caller's connection: the run row, then every finding through
`jsonb_to_recordset`. The connection is the caller's unit of work, as it is for
`identity.CoordinationStore`: nothing here opens, commits or rolls back, so a
refused finding leaves the caller's transaction to roll back the run row with
it, and no reader ever sees a run without the findings it found.

NO DRIVER IS IMPORTED HERE. The store is handed a connection — anything with
`.execute(sql, params)` returning a cursor with `.fetchone()` /
`.fetchall()` — so this module imports with the standard library and
`opendox.runtime.identity` alone, and reaches the database only when a caller
hands it one (`opendox/runtime/__init__.py`'s import-weight contract). JSON
values travel as TEXT PARAMETERS cast in SQL (`%s::jsonb`), so no driver type
is needed to send them either.

EVERY STATEMENT IS COMPOSED FROM MODULE-LEVEL CONSTANTS AND EVERY RUNTIME VALUE
IS A `%s` PARAMETER, exactly as in `identity.py`.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .identity import (
    FOREIGN_KEY_VIOLATION,
    UNIQUE_VIOLATION,
    ConflictError,
    NotFoundError,
    RefusedError,
    clamp_limit,
)

#: Postgres's SQLSTATEs for a row the schema refuses: `not_null_violation`,
#: `check_violation` and `invalid_text_representation` (a value a column type
#: cannot parse). Matched by value off the exception, as `identity.py` matches
#: its two, because this module imports no driver.
NOT_NULL_VIOLATION = "23502"
CHECK_VIOLATION = "23514"
INVALID_TEXT_REPRESENTATION = "22P02"

#: The fields a finding handed to `record_run` may carry: `health_findings`'
#: columns, less `run_id`, which the run supplies. CLOSED — a field outside it
#: is refused by name (the module docstring says why).
REQUIRED_FINDING_FIELDS: tuple[str, ...] = (
    "id", "kind", "pack_id", "pack_version", "path", "identity", "severity",
    "resolution_class", "baseline_class", "message", "evidence",
)
OPTIONAL_FINDING_FIELDS: tuple[str, ...] = ("locator",)

#: The provenance a finding must carry (box 15.7), refused by name.
PROVENANCE_FIELDS: tuple[str, ...] = ("pack_id", "pack_version")

#: How deep a JSON field the store keeps may nest, counting the field's own
#: object as level 1. The data model's shapes nest two or three levels (an
#: `identity` key, a locator span, `pack_pins`' per-pack object, a list of
#: colliding paths in `evidence`). Every reader of the stored value meets a
#: limit far deeper than this: CPython 3.12's `json` encoder and decoder raise
#: `RecursionError` at about 10,000 levels (measured), and the decoder is what
#: reads a `jsonb` column back. A deeper value is refused by name before any
#: statement (the holder, opensoft/openxFactory#656 comment 6081875839).
MAX_JSON_DEPTH = 64

#: The required fields whose columns are `text`. `jsonb_to_recordset` would
#: turn a JSON number into text without a word, so a non-string is refused here.
_TEXT_FINDING_FIELDS: tuple[str, ...] = tuple(
    field for field in REQUIRED_FINDING_FIELDS
    if field not in ("identity", "evidence"))

_RUN_INSERT_COLUMNS = (
    "run_id, corpus_root, kind, commit, baseline_branch, started_at, "
    "finished_at, outcome, pack_pins, export_commit, full_run, sandbox")
_RUN_SELECT = (
    "run_id::text, run_seq, corpus_root, kind, commit, baseline_branch, "
    "started_at, finished_at, outcome, pack_pins, export_commit, full_run, "
    "sandbox")
#: A finding's own columns, in table order: what `record_run` reads from
#: each finding's record, and, after `run_id`, what it writes.
_FINDING_FIELDS = (
    "id, kind, pack_id, pack_version, path, identity, locator, severity, "
    "resolution_class, baseline_class, message, evidence")
_FINDING_INSERT_COLUMNS = "run_id, " + _FINDING_FIELDS
_FINDING_SELECT = (
    "run_id::text, id, kind, pack_id, pack_version, path, identity, locator, "
    "severity, resolution_class, baseline_class, message, evidence")
#: The record type `jsonb_to_recordset` reads each finding as: the columns
#: above, less `run_id`, each with its column's type.
_FINDING_RECORD = (
    "id text, kind text, pack_id text, pack_version text, path text, "
    "identity text, locator jsonb, severity text, resolution_class text, "
    "baseline_class text, message text, evidence jsonb")


#: Why a value cannot be stored, by the name `_unstorable` gives it.
_UNSTORABLE: dict[str, str] = {
    "nul": (
        "carries U+0000 (NUL), which PostgreSQL can store in neither text nor "
        "jsonb"),
    "surrogate": (
        "carries a lone surrogate (U+D800 to U+DFFF), which UTF-8, and so "
        "PostgreSQL, cannot encode"),
    "cycle": (
        "contains itself (a cycle), which JSON cannot represent"),
    "depth": (
        f"nests deeper than {MAX_JSON_DEPTH} levels, which is as deep as this "
        "store follows a value"),
}


#: A UTF-16 surrogate code point. A Python string holds one only "lone": a
#: surrogate-escaped file name (`os.fsdecode` of bytes that are not UTF-8),
#: or text decoded with `surrogatepass`. UTF-8 cannot encode it, so the driver
#: raised `UnicodeEncodeError` ("surrogates not allowed") while binding it
#: (Copilot's review of openDox-code#99 at `01f4192d`).
_SURROGATE = re.compile("[\ud800-\udfff]")


def _text_unstorable(text: str) -> str | None:
    """What makes one string unstorable (a key of `_UNSTORABLE`), or None."""
    if "\x00" in text:
        return "nul"
    if _SURROGATE.search(text):
        return "surrogate"
    return None


def _json_children(item: Any) -> list[Any] | None:
    """What the walk visits under `item`: a mapping's keys and values, or a
    list's (or tuple's) items. None for a value that holds nothing."""
    if isinstance(item, Mapping):
        return [part for pair in item.items() for part in pair]
    if isinstance(item, (list, tuple)):
        return list(item)
    return None


def _unstorable(value: Any) -> str | None:
    """What makes `value` unstorable (a key of `_UNSTORABLE`), or None.

    One walk over a string, or a mapping's keys and values, or a list's items,
    at any depth: a NUL or a lone surrogate anywhere, a container that
    contains itself, or a container nested deeper than `MAX_JSON_DEPTH`. The walk is ITERATIVE and
    keeps only the containers on its current path, so no input can make it
    recurse, a cycle is named rather than followed, and a value shared by two
    branches (which is not a cycle, and which `json.dumps` writes twice) is
    admitted (the holder, opensoft/openxFactory#656 comment 6081875839).
    """
    pending: list[tuple[Any, int, bool]] = [(value, 1, False)]
    on_path: set[int] = set()
    while pending:
        item, depth, leaving = pending.pop()
        if leaving:
            on_path.discard(id(item))
            continue
        if isinstance(item, str):
            reason = _text_unstorable(item)
            if reason is not None:
                return reason
            continue
        children = _json_children(item)
        if children is None:
            continue
        if id(item) in on_path:
            return "cycle"
        if depth > MAX_JSON_DEPTH:
            return "depth"
        on_path.add(id(item))
        pending.append((item, depth, True))
        pending.extend((child, depth + 1, False) for child in children)
    return None


def _refuse_unstorable(value: Any, what: str) -> None:
    """Refuse what PostgreSQL or JSON cannot keep, BY NAME, before any statement.

    A NUL: PostgreSQL stores one in neither `jsonb` (SQLSTATE 22P05, raised by
    the server, whose message quotes the JSON around it) nor a `text`
    parameter (a client-side `DataError`), both measured on postgres 16.15.
    Without this the store raised a DRIVER error for a value it could have
    judged, and the jsonb one put a slice of the finding's text in the
    exception (lane 3's REVIEW-W1 of T042, MINOR 1). The holder,
    opensoft/openxFactory#656 comment 6072086385 item 4: the store refuses it
    itself, as a `RefusedError` that names the field and quotes nothing, as
    defence in depth behind the contract module's own refusal.

    A lone surrogate (U+D800 to U+DFFF), which a surrogate-escaped file name
    carries: UTF-8 cannot encode it, so the driver raised `UnicodeEncodeError`
    while binding it, on a write only after the run's own insert (Copilot's
    review of openDox-code#99 at `01f4192d`, under the holder's principle in
    opensoft/openxFactory#656 comment 6086098003 item 3 (c)).

    A cycle, or a value nested past `MAX_JSON_DEPTH`: the holder,
    opensoft/openxFactory#656 comment 6081875839 (Copilot's review of
    openDox-code#99 at `fbf9e77e`). `json.dumps` refused a cycle by name
    before the NUL walk was put in front of it, and that walk, recursive,
    then let a cycle or a deep value escape as `RecursionError`. Both are a
    `RefusedError` naming the field again, and `RecursionError` never leaves
    the store.
    """
    reason = _unstorable(value)
    if reason is not None:
        raise RefusedError(
            f"{what} {_UNSTORABLE[reason]}; the store refuses it before any "
            "statement, and the value is not repeated here")


def _refuse_nul_parameters(**columns: str | None) -> None:
    """Refuse U+0000, or a lone surrogate, in each text parameter a READ
    binds, naming its column.

    The holder, opensoft/openxFactory#656 comment 6086098003 item 3 (c): the
    store refuses U+0000 in EVERY text parameter it binds, as a `RefusedError`
    naming the column, before any statement, and never as the driver's
    `DataError` ("PostgreSQL text fields cannot contain NUL (0x00) bytes",
    measured from `latest_run` at `7e13130d`). The writes were already
    guarded (`_refuse_unstorable`); this is the same defence in depth for the
    reads. A lone surrogate, which UTF-8 cannot encode, is refused the same
    way (`_text_unstorable`; Copilot's review of openDox-code#99 at
    `01f4192d`). Each keyword names a column: `id (finding_id)` and
    `id (after)` are the `id` column, read through those parameters.
    """
    for column, value in columns.items():
        _refuse_unstorable(value, column)


def _dumps(value: Any, what: str) -> str:
    """Strict JSON text for a `%s::jsonb` parameter, or a refusal naming `what`.

    `allow_nan=False`, because `NaN` is Python's JSON and not JSON: Postgres
    would refuse the cast, and the refusal belongs here, by name. It does NOT
    walk `value`: `_json_text` walks a field first, and the run's findings are
    dumped whole only after `_finding_record` walked each of their fields.
    """
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RefusedError(
            f"{what} is not JSON this store can keep (a value JSON cannot "
            "represent); the value is not repeated here") from exc


def _json_text(value: Any, what: str) -> str:
    """One field's strict JSON text, walked first (`_refuse_unstorable`): a NUL
    in a key or a value, a cycle and an over-deep value are refused by name."""
    _refuse_unstorable(value, what)
    return _dumps(value, what)


def canonical_identity(identity: Mapping[str, Any]) -> str:
    """A finding's `identity`, as the `identity` column stores it.

    Canonical sorted-key JSON, no whitespace, UTF-8 text: the spelling the
    finding schema's header gives for the id's key (`json.dumps(key,
    sort_keys=True, separators=(",", ":"), ensure_ascii=False)`), so the
    stored text is the text the engine hashed (the holder, `6018624750`).
    """
    if not isinstance(identity, Mapping):
        raise RefusedError(
            "a finding's identity must be a JSON object (the position-"
            "independent key its family supplies); it is not one")
    return _json_text(dict(identity), "a finding's identity")


def _loaded(value: Any) -> Any:
    """A `jsonb` (or JSON text) column's value as Python data."""
    return json.loads(value) if isinstance(value, str) else value


def _uuid_text(run_id: str) -> str:
    """`run_id` as the canonical uuid text, or NOT FOUND: no other run exists."""
    try:
        return str(uuid.UUID(str(run_id)))
    except ValueError as exc:
        raise NotFoundError(
            "no health run with that run_id (it is not a uuid)") from exc


#: What a UNIQUE violation means, by the constraint that raised it: two keys,
#: two different causes, and a caller acts on each differently (Copilot's and
#: Codex's reviews of openDox-code#99 at `56d95d4f`).
_UNIQUE_CONFLICTS: dict[str, str] = {
    "health_findings_pkey": (
        "two findings of this run share one id. The engine records such a "
        "collision as ONE finding against their producer and stores neither "
        "(contracts/health-finding.md, the id rule); the run is not recorded"),
    "health_runs_run_seq_key": (
        "the run sequence handed out a run_seq that a recorded run already "
        "holds: the identity sequence is behind the recorded runs (a restore "
        "or a restart). Move it past the highest recorded run_seq; the run is "
        "not recorded"),
}


def _refused_by_the_schema(call: Any, what: str) -> Any:
    """Run `call`, turning the schema's refusals into this store's errors.

    A duplicate key is a CONFLICT, a missing referenced run is NOT FOUND, and
    a null, a failed check or an unparseable value is REFUSED, named by the
    constraint the server reports. Anything else re-raises.
    """
    try:
        return call()
    except Exception as exc:  # noqa: BLE001
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate == UNIQUE_VIOLATION:
            constraint = getattr(getattr(exc, "diag", None),
                                 "constraint_name", None)
            raise ConflictError(_UNIQUE_CONFLICTS.get(
                constraint,
                f"{what}: a row with this key is already recorded "
                f"({constraint or 'a unique key'})")) from exc
        if sqlstate == FOREIGN_KEY_VIOLATION:
            raise NotFoundError(
                f"{what}: the run it names does not exist") from exc
        if sqlstate in (NOT_NULL_VIOLATION, CHECK_VIOLATION,
                        INVALID_TEXT_REPRESENTATION):
            constraint = getattr(getattr(exc, "diag", None),
                                 "constraint_name", None)
            column = getattr(getattr(exc, "diag", None), "column_name", None)
            named = constraint or column or "a column's type"
            raise RefusedError(
                f"{what}: refused by the schema ({named}, "
                "migrations/0003_health.sql)") from exc
        raise


# ---------------------------------------------------------------------------
# records — frozen, one per table, fields in the table's column order
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthRun:
    """One recorded run (data-model.md § Health run).

    `full_run` is the data model's field `full`: PostgreSQL 16 reserves the
    bare word as a column name (the holder, `6064169640`).
    """

    run_id: str
    run_seq: int
    corpus_root: str
    kind: str
    commit: str | None
    baseline_branch: str | None
    started_at: datetime
    finished_at: datetime
    outcome: str
    pack_pins: dict[str, Any]
    export_commit: str
    full_run: bool
    sandbox: dict[str, Any]

    @classmethod
    def _from_row(cls, row: Sequence[Any]) -> HealthRun:
        values = list(row)
        values[9] = _loaded(values[9])      # pack_pins
        values[12] = _loaded(values[12])    # sandbox
        return cls(*values)


@dataclass(frozen=True)
class HealthFinding:
    """One stored finding (data-model.md § Finding).

    `identity` is the parsed form of the column's canonical JSON text, which
    is what `health list --json` emits; `canonical_identity` gives the text.
    """

    run_id: str
    id: str
    kind: str
    pack_id: str
    pack_version: str
    path: str
    identity: dict[str, Any]
    locator: dict[str, Any] | None
    severity: str
    resolution_class: str
    baseline_class: str
    message: str
    evidence: dict[str, Any]

    @classmethod
    def _from_row(cls, row: Sequence[Any]) -> HealthFinding:
        values = list(row)
        values[6] = json.loads(values[6])   # identity: text, by design
        values[7] = _loaded(values[7])      # locator
        values[12] = _loaded(values[12])    # evidence
        return cls(*values)


def _one(row: Sequence[Any] | None, what: str) -> Sequence[Any]:
    if row is None:
        raise NotFoundError(f"no {what}")
    return row


def _aware(value: datetime, what: str) -> datetime:
    """A timestamp the server can place: a NAIVE one is refused.

    `timestamptz` reads a naive value in the SESSION's time zone, so the same
    call would record different instants on two servers.
    """
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise RefusedError(
            f"{what} must be a timezone-aware datetime; a naive one is read "
            "in whatever time zone the session has")
    return value


def _finding_record(index: int, finding: Any) -> dict[str, Any]:
    """One finding, checked and shaped for `jsonb_to_recordset`.

    Every refusal here runs BEFORE any statement, and names the finding by its
    position and the field by its name, never by a value.
    """
    if not isinstance(finding, Mapping):
        raise RefusedError(f"finding {index} is not a mapping")
    for field in PROVENANCE_FIELDS:
        value = finding.get(field)
        if not isinstance(value, str) or not value:
            raise RefusedError(
                f"finding {index} has no {field}. Every finding carries the "
                "pack_id and pack_version of the pack that produced it — "
                "`opendox` and the installed version for the product's own "
                "families — and the store refuses one without them (#1144 box "
                "15.7; test_the_store_refuses_a_finding_without_provenance)")
    allowed = set(REQUIRED_FINDING_FIELDS) | set(OPTIONAL_FINDING_FIELDS)
    unknown = sorted(str(key) for key in finding if key not in allowed)
    if unknown:
        raise RefusedError(
            f"finding {index} carries {unknown}, which this store does not "
            "keep. It holds no document and no patch (#1144 box 14.3; R2Q25 "
            "(a)): a finding is its columns, and a pack's patch is re-obtained "
            "at `fix`, never stored")
    missing = [field for field in REQUIRED_FINDING_FIELDS if field not in finding]
    if missing:
        raise RefusedError(f"finding {index} has no {missing}")
    not_text = [field for field in _TEXT_FINDING_FIELDS
                if not isinstance(finding[field], str)]
    if not_text:
        raise RefusedError(
            f"finding {index}'s {not_text} must be strings; the store does not "
            "turn another type into text for them")
    for field in (*REQUIRED_FINDING_FIELDS, *OPTIONAL_FINDING_FIELDS):
        _refuse_unstorable(finding.get(field), f"finding {index}'s {field}")
    evidence = finding["evidence"]
    if not isinstance(evidence, Mapping):
        raise RefusedError(
            f"finding {index}'s evidence must be a JSON object (`{{}}` when "
            "there is nothing to locate)")
    record = {field: finding[field] for field in REQUIRED_FINDING_FIELDS}
    record["identity"] = canonical_identity(finding["identity"])
    record["evidence"] = dict(evidence)
    locator = finding.get("locator")
    if locator is not None:
        if not isinstance(locator, Mapping):
            raise RefusedError(
                f"finding {index}'s locator must be a JSON object or absent")
        record["locator"] = dict(locator)
    return record


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------


class HealthStore:
    """Every read and write of the two health tables, over ONE connection."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def record_run(self, *, corpus_root: str, kind: str, commit: str | None,
                   baseline_branch: str | None, started_at: datetime,
                   finished_at: datetime, outcome: str,
                   pack_pins: Mapping[str, Any], export_commit: str,
                   full_run: bool, sandbox: Mapping[str, Any],
                   findings: Sequence[Mapping[str, Any]]) -> HealthRun:
        """Record one run and every finding it stores, on the caller's unit of work.

        Every check this module makes runs first, over the whole run, so a
        refused finding writes nothing at all; the schema's own constraints
        then refuse whatever reaches it from a value this module does not
        judge (a vocabulary, a commit's form), named by the constraint.
        """
        _aware(started_at, "started_at")
        _aware(finished_at, "finished_at")
        if not isinstance(full_run, bool):
            raise RefusedError("full_run must be a boolean (whether no "
                               "`--pack` restricted the run)")
        if not isinstance(pack_pins, Mapping):
            raise RefusedError("pack_pins must be a JSON object (the run's "
                               "pack inventory, keyed by pack id)")
        if not isinstance(sandbox, Mapping):
            raise RefusedError("sandbox must be a JSON object (what the "
                               "per-run probe found)")
        for name, value in (("corpus_root", corpus_root), ("kind", kind),
                            ("commit", commit),
                            ("baseline_branch", baseline_branch),
                            ("outcome", outcome),
                            ("export_commit", export_commit)):
            _refuse_unstorable(value, name)
        records = [_finding_record(index, finding)
                   for index, finding in enumerate(findings)]
        pins_text = _json_text(dict(pack_pins), "pack_pins")
        sandbox_text = _json_text(dict(sandbox), "sandbox")
        # Every field of every record was walked by `_finding_record`, so the
        # records are dumped, not walked again: a walk from the list down
        # would count two levels more than each field's own.
        findings_text = _dumps(records, "the run's findings")
        run_id = str(uuid.uuid4())
        row = _refused_by_the_schema(
            lambda: self._conn.execute(
                f"insert into health_runs ({_RUN_INSERT_COLUMNS}) "
                "values (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, "
                f"%s, %s::jsonb) returning {_RUN_SELECT}",
                (run_id, corpus_root, kind, commit, baseline_branch,
                 started_at, finished_at, outcome, pins_text, export_commit,
                 full_run, sandbox_text),
            ).fetchone(),
            "the run")
        run = HealthRun._from_row(_one(row, "health run returned by its insert"))
        if records:
            _refused_by_the_schema(
                lambda: self._conn.execute(
                    f"insert into health_findings ({_FINDING_INSERT_COLUMNS}) "
                    f"select %s::uuid, {_FINDING_FIELDS} "
                    f"from jsonb_to_recordset(%s::jsonb) as f({_FINDING_RECORD})",
                    (run_id, findings_text)),
                "a finding of the run")
        return run

    def get_run(self, run_id: str) -> HealthRun:
        row = self._conn.execute(
            f"select {_RUN_SELECT} from health_runs where run_id = %s::uuid",
            (_uuid_text(run_id),)).fetchone()
        return HealthRun._from_row(_one(row, f"health run {run_id!r}"))

    def latest_run(self, *, corpus_root: str) -> HealthRun | None:
        """The corpus's latest RECORDED run, of any kind and outcome, or None.

        Only this corpus's: two corpora sharing one store never read each
        other's runs (`list`, `fix` and `accept` read the resolved corpus's).
        """
        _refuse_nul_parameters(corpus_root=corpus_root)
        row = self._conn.execute(
            f"select {_RUN_SELECT} from health_runs where corpus_root = %s "
            "order by run_seq desc limit 1", (corpus_root,)).fetchone()
        return None if row is None else HealthRun._from_row(row)

    def baseline_run(self, *, corpus_root: str, baseline_branch: str | None,
                     before_seq: int | None = None) -> HealthRun | None:
        """B: the latest default-tip run that is COMPLETE and FULL, or None.

        R2Q12 (a), as data-model.md § Baseline classes words it: the SAME
        resolved `corpus_root` and `baseline_branch`, never another corpus's
        run, and only a `complete`, `full` default-tip run forms a baseline.
        `before_seq` bounds it to runs recorded before a given one. With no
        baseline branch no run is default-tip, so there is no B.
        """
        _refuse_nul_parameters(corpus_root=corpus_root,
                               baseline_branch=baseline_branch)
        if baseline_branch is None:
            return None
        row = self._conn.execute(
            f"select {_RUN_SELECT} from health_runs "
            "where corpus_root = %s and baseline_branch = %s "
            "and kind = 'default-tip' and outcome = 'complete' and full_run "
            "and (%s::bigint is null or run_seq < %s) "
            "order by run_seq desc limit 1",
            (corpus_root, baseline_branch, before_seq, before_seq)).fetchone()
        return None if row is None else HealthRun._from_row(row)

    def get_finding(self, *, run_id: str, finding_id: str) -> HealthFinding:
        _refuse_nul_parameters(**{"id (finding_id)": finding_id})
        row = self._conn.execute(
            f"select {_FINDING_SELECT} from health_findings "
            "where run_id = %s::uuid and id = %s",
            (_uuid_text(run_id), finding_id)).fetchone()
        return HealthFinding._from_row(
            _one(row, f"finding {finding_id!r} in health run {run_id!r}"))

    def list_findings(self, *, run_id: str, limit: int | None = None,
                      after: str | None = None,
                      resolution_class: str | None = None,
                      baseline_class: str | None = None) -> list[HealthFinding]:
        """One page of a run's findings, ordered by id; `after` walks the rest.

        Bounded like every listing in this package (`identity.clamp_limit`).
        """
        _refuse_nul_parameters(**{"id (after)": after},
                               resolution_class=resolution_class,
                               baseline_class=baseline_class)
        rows = self._conn.execute(
            f"select {_FINDING_SELECT} from health_findings "
            "where run_id = %s::uuid "
            "and (%s::text is null or id > %s) "
            "and (%s::text is null or resolution_class = %s) "
            "and (%s::text is null or baseline_class = %s) "
            "order by id limit %s",
            (_uuid_text(run_id), after, after, resolution_class,
             resolution_class, baseline_class, baseline_class,
             clamp_limit(limit))).fetchall()
        return [HealthFinding._from_row(row) for row in rows]
