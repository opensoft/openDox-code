"""OPENDOX'S OWN VALIDATOR: its own document kinds, read from its own packaged
copies of their schemas.

WHY THIS FILE EXISTS. #1144's requirement 7 asks for *"a validator openDox can
run"*, and its 7.1 says to *"NARROW THE INPUT SET FIRST, then acquire what
remains"*: openDox's validator validates openDox's OWN document kinds, whose
schemas its own spec leg owns. T007's batch G amends 7.1 on R1Q11 (a) and
R1Q12 (a) (`openxFactory#656` comment `5850003126`), so the set is FOUR
schemas: 7.1's three, `ideation-workbench`, `xfactory-workbench-chat-turn` and
`xfactory-workbench-model-catalog`, and the neutral snapshot contract,
`opendox-snapshot`, which T053 adds to openDox-spec. This module is plan 034's
T057. `opendox.contracts` beside it carries the four as package data, each one
digest-checked before it is read.

THE INPUT SET, AND WHAT IS LEFT OUT (7.1, 7.1b). `KIND_ENTRIES` maps each
instance kind openDox validates to the copy that holds its schema. Nothing else
is in it.

* openXdox-spec's three, `ideation-dashboard-snapshot`, its `-index` and
  `gate-action-record`, *"belong to the CONSUMER's validator and openDox never
  needs them"* (7.1). The consumer locates them itself (7.3, plan 034's T061).
* openxFactory's four are not in it either, and 7.1b names two of them as
  unavailable by any route. `gate-intent` is an intent-plane schema, which
  requirement 1 keeps with openxFactory. `ideation-possibles-register` is
  filed `stays_openxfactory_adapter`, as openxFactory's own candidate
  register. Vendoring either would meet requirement 7 by breaching
  requirement 1. No openDox verb needs one, so neither is carried.

WHY THE CONSUMER'S SCRIPT IS NOT REUSED (7.1a). The validator the carve left,
`scripts/validate-ideation-dashboard-contracts.py`, lives in openXdox-code. It
was run at openXdox-code `4610bca5` for this record.

1. It finds its schemas from its own position. `ROOT` is
   `Path(__file__).resolve().parents[1]`, and it reads `ROOT / "contracts"`,
   or the directory `CONTRACTS_DIR` names. #1144 measured the first half
   (*"run from openXdox-code it exits 2 with `ERROR .../contracts/schemas not
   found`"*), and C3's openXdox-code#28 has added the second since. Run at
   `4610bca5` with no `CONTRACTS_DIR`, it still exits 2: `ERROR harness
   failure: .../contracts/schemas carries none of the family's 10 schemas`.
   An installed openDox carries neither the script nor a `contracts/` beside
   it, and no environment variable is part of `pip install`, which is the
   checkout requirement 7 means (7.1). That is 7.1a's defect, and it is the
   consumer's to fix for its own set (T061).
2. It names TEN schemas, of three owners (`SCHEMA_FILENAMES`). openDox's
   validator reads four, all openDox-spec's (7.1).
3. It is the CONSUMER's file. openDox pins nothing of openXdox's, and a reach
   into it is the direction requirements 2 and 5 close.
4. It needs `jsonschema`, `referencing` and `rfc3339-validator`. openDox-code
   declares PyYAML alone, and this module needs no more.
5. It knows no `opendox-snapshot`. Given openDox-spec's contracts through
   `CONTRACTS_DIR`, it refuses openDox-spec's own six-station example with
   exit 1, `ERROR [kind] ...: unrecognized document (no known kind ...)`,
   because its `KIND_TO_SCHEMA` has no entry for the neutral kind.
6. It is a script, run as a subprocess over a file. openDox-code has no
   `scripts/` directory (7.2), and this validator is a library call that
   answers violations.

NEW SURFACE (7.2). This file is CREATED at the code leg, not relocated, and it
has no row in openxFactory's `docs/opendox-carve-manifest.yaml`, because the
manifest declares what LEAVES openxFactory and never what a destination
assembles (RULED OQ-C). It adds no verb, and #1144 adds none. Validation is the
post-render step inside the generate verbs, which plan 034's T058 routes here.

THE EVALUATOR. It evaluates JSON Schema draft 2020-12, and exactly the keywords
the four copies use (`KEYWORDS`), as that draft defines them. JSON equality
holds throughout: `true` is not `1`, `1` is `1.0`, and key order does not
count. `format` is ASSERTED, as the consumer's validator asserts it with its
format checker, and `date-time` is the one format the four use. A copy that
uses a keyword, a format, a dialect or a reference this module does not
evaluate is REFUSED when its validator is built (`SchemaNotEvaluable`). It is
never evaluated with that keyword left out, which would pass whatever the
keyword refuses. So is a copy that gives an evaluated keyword a value of
another shape (`_SHAPES`: `uniqueItems: "yes"`, `type: {}`, a negative
`maxLength`), an embedded resource (`$id` or `$schema` below the root, which
would move where its references resolve), a subschema that contains itself,
and a cycle of references that never moves into the instance (`$ref: "#"`),
which no evaluation ends. A recursive schema that moves into the instance
before it recurs (a tree's children, as items) is evaluated. It recurs once per
level of the instance, so an instance nested past what Python's recursion limit
lets the walk reach cannot be walked to its end. Such an instance is judged,
never crashed on: it breaks `DEPTH_RULE`, at the root, so it is never valid,
and whatever the walk found before the limit stands. The build walks
every subschema and every reference's target, so nothing the evaluator can
reach escapes those checks, and a malformed copy is reported as unavailable
instead of crashing the build or an evaluation, or misjudging an instance.

RULE IDENTIFIERS. Every violation names the rule it broke. The neutral snapshot
contract gives each rule an id, carried as `x-rule` by the subschema that
enforces it, and that id is the violation's `rule`. A subschema that names none
(the three older contracts do not use the convention) is identified by the JSON
Schema keyword that failed. `Violation.line()` renders
`[<rule>] <where>: <detail>`, with `where` a JSON pointer into the instance, so
a refusal carries the identifier a caller can match. T051's `EXPECTED_RULE` is
one such identifier, and F7.2 greps the verbs' stderr for it.

THE NEUTRAL SNAPSHOT'S REFERENCE RULES. Seven of the contract's 32 rules are
cross-references that no JSON Schema keyword can state, so this module
implements them (`REFERENCE_RULES`). The contract catalogues each rule with its
class in `x-rules`. A snapshot validator is REFUSED when that catalog names a
reference rule this module does not implement, or when this module implements
one the catalog does not name. So a validator never enforces less than the
contract says, or more.

IDENTITY BEFORE USE, ON EVERY CALL. `validator_for()` has
`opendox.contracts.verified_bytes()` prove each copy before its bytes are
parsed. A compiled validator is cached under the digest that proof returned,
never under a name or a time. So a changed byte is refused on the very call
that sees it, as openxFactory's `doxbench_contracts.validators()` refuses one.

THE WORKBENCH MANIFEST'S TWO VALIDATOR RULES (plan 034's T085; RULED
`openxFactory#656` comment `5920216845`, item 2, *"Move into openDox's
validator (Recommended)"*). The `ideation-workbench` copy states two rules in
its own text and leaves them to its validator, because no JSON Schema keyword
states either: `recipe.pinned` says *"every pinned keyword MUST also appear in
`checked` -- this schema does not encode the subset constraint"*, and a
`recipe.new_candidates` entry is a document the set has not placed yet. The
copy carries no `x-rules` catalog, so this module OWNS the two rules
(`OWNED_RULES`), under ids it gives them, stating what must hold as its other
rules do: `pinned-keywords-are-checked` and `new-candidates-are-disjoint`.
T058 carried them in `default_projection`, under the consumer script's
identifiers. They live here now, and nothing answers to the old identifiers.
A copy that DOES carry a catalog has its rules from the catalog alone, so a
copy that carries one and is also owned rules here is refused when its
validator is built: one rule is enforced from one place.

jsonschema's SHAPE, FOR THE doxBench SEAM. `KindValidator.iter_errors()`
yields violations whose `validator` (the failed keyword) and `absolute_path`
read as a `jsonschema` error's do. Those are the two fields
`serve_workbench`'s readers of the doxBench-validators seam read.
`doxbench_validators()` answers one validator per doxBench wire kind
(`DOXBENCH_KINDS`): the model catalog's whole document, and each chat-turn
envelope's own `$defs` entry, as openxFactory's `doxbench_contracts` builds
them. It is openDox's own default at that seam, which the entry points
register where no host has (plan 034's T085, R1Q10 (a);
`opendox.doxbench_defaults`). The doxBench kinds are validated structurally
here, as openxFactory's `validators()` validates them.

IMPORT WEIGHT. The standard library, and `opendox.contracts`, whose record and
copies are read with PyYAML only when a validator is built. It names no
sibling.
"""

from __future__ import annotations

import calendar
import hashlib
import math
import re
import reprlib
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Mapping

from opendox import contracts

__all__ = [
    "DEPTH_RULE",
    "DIALECT",
    "DOXBENCH_KINDS",
    "FORMATS",
    "KEYWORDS",
    "KINDS",
    "KIND_ENTRIES",
    "KindValidator",
    "OWNED_RULES",
    "REFERENCE_RULES",
    "SchemaNotEvaluable",
    "UnknownKind",
    "ValidatorUnavailable",
    "Violation",
    "doxbench_validators",
    "report",
    "validate",
    "validator_for",
    "validators",
]

#: The one dialect the four copies declare, and the one this module evaluates.
DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: The rule an instance breaks when it nests deeper than the evaluation can
#: walk. It is this evaluator's own limit, and no contract's rule. A recursive
#: schema that moves into the instance recurs once per level, so a deep enough
#: instance reaches Python's recursion limit. It is judged, not crashed on
#: (`KindValidator.iter_errors`): one violation at the root, so it is never
#: valid, which is failing closed.
DEPTH_RULE = "evaluation-depth"

#: THE INPUT SET (7.1, as batch G amends it): each instance kind openDox
#: validates, and where its schema is, as (packaged copy id, JSON pointer into
#: that copy). "" is the copy's whole document. The chat-turn copy holds three
#: envelopes, and each wire kind is validated against its own envelope, as
#: openxFactory's `doxbench_contracts.CHAT_TURN_DEFS` names them.
KIND_ENTRIES: Mapping[str, tuple[str, str]] = {
    "ideation-workbench": ("ideation-workbench", ""),
    "opendox-snapshot": ("opendox-snapshot", ""),
    "workbench-chat-turn-v2": ("xfactory-workbench-chat-turn", "/$defs/request_v2"),
    "workbench-chat-turn-v2-failure": ("xfactory-workbench-chat-turn",
                                       "/$defs/failure_v2"),
    "workbench-chat-turn-v2-success": ("xfactory-workbench-chat-turn",
                                       "/$defs/success_v2"),
    "workbench-model-catalog": ("xfactory-workbench-model-catalog", ""),
}

#: The instance kinds, sorted.
KINDS: tuple[str, ...] = tuple(sorted(KIND_ENTRIES))

#: The doxBench WIRE kinds, sorted: the model catalog and the three chat-turn
#: envelopes, which the two model routes validate through the
#: doxBench-validators seam (`serve_wire`), as openxFactory's
#: `doxbench_contracts.WIRE_KINDS` names them. Each is held in openDox's
#: packaged copy of `xfactory-workbench-model-catalog` or
#: `xfactory-workbench-chat-turn` (R1Q12 (a)).
DOXBENCH_KINDS: tuple[str, ...] = tuple(sorted(
    kind for kind, (copy_id, _pointer) in KIND_ENTRIES.items()
    if copy_id in ("xfactory-workbench-chat-turn", "xfactory-workbench-model-catalog")))

#: The keywords that can FAIL, and that this module evaluates.
_ASSERTING = frozenset({
    "const", "dependentRequired", "enum", "format", "maxItems", "maxLength",
    "maxProperties", "maximum", "minItems", "minLength", "minProperties",
    "minimum", "pattern", "required", "type", "uniqueItems"})
#: The keywords that route a value into subschemas.
_APPLYING = frozenset({
    "$ref", "additionalProperties", "allOf", "anyOf", "contains", "if", "items",
    "not", "oneOf", "properties", "propertyNames", "then"})
#: The keywords that only carry or annotate.
_ANNOTATING = frozenset({
    "$defs", "$id", "$schema", "contract_schema_version", "description",
    "title", "x-rule", "x-rules"})
#: Every keyword this module evaluates or knows to carry nothing. A copy that
#: uses any other is refused (`SchemaNotEvaluable`).
KEYWORDS = _ASSERTING | _APPLYING | _ANNOTATING

_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object",
                    "string"})

#: How much of a value a violation's detail quotes.
_BRIEF = 80


class ValidatorUnavailable(RuntimeError):
    """openDox's validator cannot run for a kind.

    Either a packaged copy failed its identity check (`opendox.contracts`
    refused it), or it uses something this module does not evaluate. No
    verdict was reached, and no verdict is never a pass: a caller reports the
    validator as unavailable, and `--strict` makes that fatal (T058)."""


class SchemaNotEvaluable(ValidatorUnavailable):
    """A packaged copy uses a keyword, format, dialect or reference this
    module does not evaluate, gives a keyword a value of a shape it does not
    evaluate, or declares reference rules it does not implement. It is
    refused when its validator is built."""


class UnknownKind(ValueError):
    """The instance's kind is not one of openDox's own kinds (7.1).

    Raised instead of answering an empty list, which would read as valid. An
    unknown kind has no schema here, so it has no verdict."""


@dataclass(frozen=True)
class Violation:
    """One broken rule, at one place in the instance."""

    rule: str                         # the broken rule's identifier
    path: tuple[str | int, ...]       # where, as the instance's own keys and indices
    keyword: str                      # the schema keyword that failed, or "reference"
    detail: str                       # what was found

    @property
    def where(self) -> str:
        """`path` as a JSON pointer ("" is the instance itself). A part that
        is not text or an index is shown as `_shown` shows it, so a key of any
        size is named and never crashes the pointer (an int past 4300 digits
        has no decimal text; Copilot at openDox-code#58 2b8ad245,
        r4139823704)."""
        return "".join("/" + _part_text(part).replace("~", "~0").replace("/", "~1")
                       for part in self.path)

    # jsonschema's names for the same fields, for the doxBench seam's readers.
    @property
    def validator(self) -> str:
        return self.keyword

    @property
    def absolute_path(self) -> tuple[str | int, ...]:
        return self.path

    @property
    def message(self) -> str:
        return self.detail

    def line(self) -> str:
        """`[<rule>] <where>: <detail>`, the form a refusal prints."""
        return f"[{self.rule}] {self.where or '<root>'}: {self.detail}"


def report(violations: Iterable[Violation]) -> list[str]:
    """Each violation's `line()`, in the order they were found."""
    return [violation.line() for violation in violations]


# ---------------------------------------------------------------------------
# JSON values
# ---------------------------------------------------------------------------

#: A repr that stops at a few levels, for a value too deep for `repr()`.
_SHALLOW = reprlib.Repr()
_SHALLOW.maxlevel = 3


def _shown(value: Any) -> str:
    """`repr(value)`, or a stand-in where it cannot be made: a value nested
    past Python's limit shows its first levels, and an int past 4300 digits
    (which only Python, never YAML or JSON, can hand in) shows its size."""
    try:
        return repr(value)
    except (RecursionError, ValueError):
        try:
            return _SHALLOW.repr(value)
        except (RecursionError, ValueError):
            if isinstance(value, int):
                return f"<an int of {value.bit_length()} bits>"
            return f"<a {type(value).__name__} too large to show>"


def _part_text(part: Any) -> str:
    """A path part as pointer text: text as it is, anything else as `str()`
    gives it, or as `_shown` does where `str()` cannot."""
    if isinstance(part, str):
        return part
    try:
        return str(part)
    except (RecursionError, ValueError):
        return _shown(part)


def _brief(value: Any) -> str:
    text = _shown(value)
    return text if len(text) <= _BRIEF else text[:_BRIEF - 3] + "..."


def _brief_items(values: list[Any]) -> str:
    """A list shown item by item, each as `_shown` shows it, and cut as
    `_brief` cuts. So one key too large to show is named by its size, and the
    others still read as themselves (Copilot at openDox-code#58 2b8ad245,
    r4139823779). An ordinary list reads exactly as `_brief` shows it."""
    text = "[" + ", ".join(_shown(value) for value in values) + "]"
    return text if len(text) <= _BRIEF else text[:_BRIEF - 3] + "..."


def _is_type(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):          # JSON true is not the number 1
        return False
    if name == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    return isinstance(value, (int, float))    # "number"; _TYPES was checked at build


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _token(tag: str, text: str) -> str:
    return f"{tag}{len(text)}:{text}"


def _canon_scalar(value: Any) -> str | None:
    """A value that is not a list or a mapping, canonical; None for one that is."""
    if isinstance(value, bool):
        return _token("b", "1" if value else "0")
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        # 1 is 1.0. Hex, because decimal text of an int stops at 4300 digits.
        return _token("n", format(int(value), "x"))
    if isinstance(value, float):
        return _token("f", value.hex())
    if isinstance(value, str):
        return _token("s", value)
    if value is None:
        return _token("z", "")
    if isinstance(value, (list, dict)):
        return None
    # Never equal to a JSON value. Where no repr can be made, the object is its
    # own identity, equal to itself alone.
    try:
        return _token("o", repr(value))
    except (RecursionError, ValueError):
        return _token("o", f"<{type(value).__name__} {id(value)}>")


#: What a list or mapping that contains itself canonicalizes to. A YAML alias
#: can build one, and no JSON value is one. No token begins with "!".
_ITSELF = "!itself"


def _canon(value: Any) -> str:
    """JSON equality: `true` is not `1`, `1` is `1.0`, and key order is noise.

    The canon is text: every value is a tag, a length and its payload, and a
    list or mapping is its children's canons, the mapping's sorted, so two
    canons are equal exactly when their values are. It is built without
    recursing, and compared and hashed as text, so a value of any depth is
    judged without exhausting Python's stack (nested tuples compare
    recursively, and would). A list or mapping inside itself ends as
    `_ITSELF`."""
    scalar = _canon_scalar(value)
    if scalar is not None:
        return scalar
    done: list[str] = []                # finished canons, in the order met
    open_ids: set[int] = set()          # the containers on the current path
    work: list[tuple[bool, Any]] = [(False, value)]
    while work:
        closing, item = work.pop()
        if closing:
            open_ids.discard(id(item))
            done.append(_close(item, done))
            continue
        scalar = _canon_scalar(item)
        if scalar is not None:
            done.append(scalar)
        elif id(item) in open_ids:
            done.append(_ITSELF)
        else:
            open_ids.add(id(item))
            work.append((True, item))
            work.extend((False, child) for child in reversed(
                list(item.values()) if isinstance(item, dict) else item))
    return done[0]


def _close(container: list[Any] | dict[Any, Any], done: list[str]) -> str:
    """The canon of `container`, from its children's canons at the end of
    `done`, which it takes off."""
    count = len(container)
    children = done[len(done) - count:]
    del done[len(done) - count:]
    if isinstance(container, list):
        return f"a{count}:" + "".join(children)
    # A key is text in JSON. A YAML instance can carry another scalar as a key,
    # and a key is a scalar, so each key is its own canon: a text key is never
    # the number it spells.
    return f"d{count}:" + "".join(sorted(
        _canon_scalar(key) + child for key, child in zip(container, children)))


def _holds_itself(value: Any) -> bool:
    """Whether a list or mapping inside `value` contains itself."""
    path: set[int] = set()
    work: list[tuple[bool, Any]] = [(False, value)]
    while work:
        leaving, node = work.pop()
        if leaving:
            path.discard(id(node))
        elif isinstance(node, (list, dict)):
            if id(node) in path:
                return True
            path.add(id(node))
            work.append((True, node))
            work.extend((False, child)
                        for child in (node.values() if isinstance(node, dict) else node))
    return False


def _first_non_json(value: Any) -> str | None:
    """What in `value` is not a JSON value, or None where all of it is: text,
    a whole or finite number, true, false, null, and lists and mappings of
    them whose keys are text. Walked without recursing; the caller has
    already refused a value that contains itself."""
    work: list[Any] = [value]
    while work:
        node = work.pop()
        if node is None or isinstance(node, (bool, str)):
            continue
        if _is_number(node):
            if not _is_bound(node):
                return f"the non-finite number {node!r}"
            continue
        if isinstance(node, list):
            work.extend(node)
        elif isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    return f"a mapping key that is not text ({_brief(key)})"
                work.append(child)
        else:
            return f"a {type(node).__name__} ({_brief(node)})"
    return None


_DATE_TIME = re.compile(
    r"([0-9]{4})-(0[1-9]|1[0-2])-([0-9]{2})T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def _is_date_time(value: str) -> bool:
    """An RFC 3339 date-time, as the consumer's validator checks one.

    That is `jsonschema`'s `date-time` checker, which is `rfc3339-validator`
    over the upper-cased value: a year other than 0000, a day the month has,
    and no leap second. It differs in one place, deliberately: the whole value
    must match. `rfc3339-validator` anchors its pattern with `$`, which also
    matches before a final newline, so it admits `...Z` followed by a
    newline, and this does not."""
    match = _DATE_TIME.fullmatch(value.upper())
    if match is None:
        return False
    year, month, day = (int(group) for group in match.groups())
    return year != 0 and 1 <= day <= calendar.monthrange(year, month)[1]


#: The formats this module asserts. A copy naming another is refused.
FORMATS: Mapping[str, Callable[[str], bool]] = {"date-time": _is_date_time}


# ---------------------------------------------------------------------------
# the neutral snapshot's reference rules
# ---------------------------------------------------------------------------

def _entries(snap: Any, section: str) -> list[tuple[int, dict[str, Any]]]:
    items = snap.get(section) if isinstance(snap, dict) else None
    if not isinstance(items, list):
        return []           # absent or not a list is a shape rule's to report
    return [(i, entry) for i, entry in enumerate(items) if isinstance(entry, dict)]


def _ids(snap: Any, section: str, key: str = "id") -> set[str]:
    return {entry[key] for _i, entry in _entries(snap, section)
            if isinstance(entry.get(key), str)}


def _broken(rule: str, path: tuple[str | int, ...], detail: str) -> Violation:
    return Violation(rule, path, "reference", detail)


def _ids_are_unique(snap: Any) -> Iterator[Violation]:
    for section, key in (("documents", "id"), ("clusters", "id"), ("possibles", "id"),
                         ("staged_topics", "staging_id"), ("changes", "id")):
        seen: set[str] = set()
        for i, entry in _entries(snap, section):
            value = entry.get(key)
            if isinstance(value, str):
                if value in seen:
                    yield _broken("ids-are-unique", (section, i, key),
                                  f"{_brief(value)} is already an id in {section}")
                seen.add(value)


def _edges(group: dict[str, Any]) -> list[tuple[int, Any]]:
    edges = group.get("document_edges")
    return list(enumerate(edges if isinstance(edges, list) else []))


def _edge_names_a_document(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "documents")
    for gi, group in _entries(snap, "clusters"):
        for ei, edge in _edges(group):
            ref = edge.get("document") if isinstance(edge, dict) else None
            if isinstance(ref, str) and ref not in known:
                yield _broken("edge-names-a-document",
                              ("clusters", gi, "document_edges", ei, "document"),
                              f"no document has the id {_brief(ref)}")


def _one_edge_per_document(snap: Any) -> Iterator[Violation]:
    for gi, group in _entries(snap, "clusters"):
        seen: set[str] = set()
        for ei, edge in _edges(group):
            ref = edge.get("document") if isinstance(edge, dict) else None
            if isinstance(ref, str):
                if ref in seen:
                    yield _broken("one-edge-per-document",
                                  ("clusters", gi, "document_edges", ei, "document"),
                                  f"{_brief(ref)} already has an edge in this group")
                seen.add(ref)


def _candidate_names_a_group(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "clusters")
    for pi, candidate in _entries(snap, "possibles"):
        refs = candidate.get("claiming_clusters")
        for ri, ref in enumerate(refs if isinstance(refs, list) else []):
            if isinstance(ref, str) and ref not in known:
                yield _broken("candidate-names-a-group",
                              ("possibles", pi, "claiming_clusters", ri),
                              f"no group has the id {_brief(ref)}")


def _pick_names_a_selection(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "staged_topics", "staging_id")
    for pi, candidate in _entries(snap, "possibles"):
        pick = candidate.get("pick")
        ref = pick.get("staging_id") if isinstance(pick, dict) else None
        if isinstance(ref, str) and ref not in known:
            yield _broken("pick-names-a-selection", ("possibles", pi, "pick", "staging_id"),
                          f"no selection has the staging_id {_brief(ref)}")


def _target_names_a_submission(snap: Any) -> Iterator[Violation]:
    known = _ids(snap, "changes")
    for ti, selection in _entries(snap, "staged_topics"):
        ref = selection.get("target_change")
        if isinstance(ref, str) and ref not in known:
            yield _broken("target-names-a-submission", ("staged_topics", ti, "target_change"),
                          f"no changes entry has the id {_brief(ref)}")


def _keyword_index_matches_topics(snap: Any) -> Iterator[Violation]:
    """Present, the index never contradicts the documents: every topic they
    carry has one entry, and each entry counts the documents that carry its
    keyword. An entry for a keyword no document carries is lawful at 0."""
    index = snap.get("keyword_index") if isinstance(snap, dict) else None
    if not isinstance(index, list):
        return              # absent is lawful; not a list is section-is-a-list's
    carried: dict[str, int] = {}
    for _i, document in _entries(snap, "documents"):
        topics = document.get("topics")
        for topic in ({t for t in topics if isinstance(t, str)}
                      if isinstance(topics, list) else ()):
            carried[topic] = carried.get(topic, 0) + 1
    rule = "keyword-index-matches-topics"
    listed: set[str] = set()
    for ki, entry in enumerate(index):
        keyword = entry.get("keyword") if isinstance(entry, dict) else None
        if not isinstance(keyword, str):
            continue        # keyword-entry-keys and topic-is-trimmed-text say why
        if keyword in listed:
            yield _broken(rule, ("keyword_index", ki, "keyword"),
                          f"{_brief(keyword)} already has an entry")
            continue
        listed.add(keyword)
        count = entry.get("declared_doc_count")
        if _is_type(count, "integer") and count != carried.get(keyword, 0):
            yield _broken(rule, ("keyword_index", ki, "declared_doc_count"),
                          f"{count} documents, but {carried.get(keyword, 0)} carry "
                          f"{_brief(keyword)}")
    unlisted = sorted(set(carried) - listed)
    if unlisted:
        yield _broken(rule, ("keyword_index",),
                      f"topics the documents carry and the index does not list: "
                      f"{_brief(unlisted)}")


#: The reference rules this module implements, per packaged copy. Only the
#: neutral snapshot contract declares any.
REFERENCE_RULES: Mapping[str, Mapping[str, Callable[[Any], Iterator[Violation]]]] = {
    "opendox-snapshot": {
        "ids-are-unique": _ids_are_unique,
        "edge-names-a-document": _edge_names_a_document,
        "one-edge-per-document": _one_edge_per_document,
        "candidate-names-a-group": _candidate_names_a_group,
        "pick-names-a-selection": _pick_names_a_selection,
        "target-names-a-submission": _target_names_a_submission,
        "keyword-index-matches-topics": _keyword_index_matches_topics,
    },
}


# ---------------------------------------------------------------------------
# the workbench manifest's two validator rules (plan 034's T085)
# ---------------------------------------------------------------------------

def _names(value: Any) -> list[str]:
    """A list's string entries, once each, in order. Anything else answers
    none: its shape is the schema's to judge, and these rules only compare.

    Linear: the schema bounds none of the three lists, so membership is a
    set's, and the list only keeps the order (Copilot at openDox-code#68
    09cd1e8a, r4139734444)."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str) and item not in seen:
            seen.add(item)
            names.append(item)
    return names


#: How many names a rule's detail quotes before it says how many more, and
#: how much of each name it quotes.
_QUOTED = 10
_NAME_CHARS = 80


def _quoted(names: list[str]) -> str:
    """`names` as a detail quotes them: the first few, each cut to a readable
    length, and a count of the rest, so one violation stays one readable line.
    The schema bounds neither the lists nor their strings (Copilot at
    openDox-code#68 21e4723f, r4139769791)."""
    shown = repr([name if len(name) <= _NAME_CHARS else name[:_NAME_CHARS - 1] + "…"
                  for name in names[:_QUOTED]])
    return shown if len(names) <= _QUOTED else f"{shown[:-1]}, and {len(names) - _QUOTED} more]"


def _placed(entries: Any) -> set[str]:
    """The `document` of each entry of a members or excluded list."""
    if not isinstance(entries, list):
        return set()
    return {entry["document"] for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("document"), str)}


def _recipe(manifest: Any) -> dict[str, Any] | None:
    recipe = manifest.get("recipe") if isinstance(manifest, dict) else None
    return recipe if isinstance(recipe, dict) else None


def _pinned_keywords_are_checked(manifest: Any) -> Iterator[Violation]:
    """Every `recipe.pinned` keyword is also in `recipe.checked`: a keyword
    is pinned (required) only among the keywords that stratify the set."""
    recipe = _recipe(manifest)
    if recipe is None:
        return
    checked = set(_names(recipe.get("checked")))
    stray = [name for name in _names(recipe.get("pinned")) if name not in checked]
    if stray:
        yield _broken("pinned-keywords-are-checked", ("recipe", "pinned"),
                      f"pinned keyword(s) {_quoted(stray)} are not in checked: "
                      "every pinned keyword MUST also be checked")


def _new_candidates_are_disjoint(manifest: Any) -> Iterator[Violation]:
    """No `recipe.new_candidates` document is already a member or excluded: a
    new candidate is a document the set has not placed yet."""
    recipe = _recipe(manifest)
    if recipe is None:
        return
    placed = _placed(manifest.get("members")) | _placed(manifest.get("excluded"))
    overlap = [name for name in _names(recipe.get("new_candidates")) if name in placed]
    if overlap:
        yield _broken("new-candidates-are-disjoint", ("recipe", "new_candidates"),
                      f"new_candidates {_quoted(overlap)} already appear in members "
                      "or excluded: a new candidate is a document the set has not "
                      "placed yet")


#: The rules this module OWNS, per packaged copy: rules a copy states in its own
#: text and leaves to its validator, because no JSON Schema keyword states them,
#: for a copy that carries no `x-rules` catalog (this module's docstring). Only
#: the workbench manifest's copy has any (RULED `5920216845`, item 2).
OWNED_RULES: Mapping[str, Mapping[str, Callable[[Any], Iterator[Violation]]]] = {
    "ideation-workbench": {
        "pinned-keywords-are-checked": _pinned_keywords_are_checked,
        "new-candidates-are-disjoint": _new_candidates_are_disjoint,
    },
}


# ---------------------------------------------------------------------------
# a copy, compiled
# ---------------------------------------------------------------------------

def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _at_pointer(document: Any, pointer: str) -> Any:
    """The node `pointer` (a JSON pointer, "" for the root) names in `document`."""
    node = document
    if pointer == "":
        return node
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    for token in pointer[1:].split("/"):
        # RFC 6901 escapes only `~0` and `~1`; any other `~` makes no pointer.
        if not _TOKEN.fullmatch(token):
            raise KeyError(pointer)
        token = _unescape(token)
        if isinstance(node, dict):
            node = node[token]
        elif isinstance(node, list):
            # A JSON pointer's array index is a plain decimal: never "-1" and
            # never "01", which Python's int() would read as other elements.
            if not _INDEX.fullmatch(token):
                raise KeyError(pointer)
            node = node[int(token)]
        else:
            raise KeyError(pointer)
    return node


_INDEX = re.compile(r"0|[1-9][0-9]*")
_TOKEN = re.compile(r"(?:[^~]|~[01])*")


# ---------------------------------------------------------------------------
# the shapes the evaluator reads
# ---------------------------------------------------------------------------

def _is_schema(value: Any) -> bool:
    return isinstance(value, (dict, bool))


def _is_count(value: Any) -> bool:
    """A non-negative integer, as JSON counts one: `2.0` is 2, `true` is not 1."""
    return _is_type(value, "integer") and value >= 0


def _is_bound(value: Any) -> bool:
    """A number that is not infinite or NaN. Every int is finite, and
    `math.isfinite()` cannot convert one past a float's range, so it is asked
    only about floats."""
    return _is_number(value) and (isinstance(value, int) or math.isfinite(value))


def _are_names(value: Any) -> bool:
    """A list of distinct property names."""
    return (isinstance(value, list) and all(isinstance(name, str) for name in value)
            and len(set(value)) == len(value))


def _are_schemas(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(map(_is_schema, value))


def _names_schemas(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str) and _is_schema(sub) for name, sub in value.items())


def _names_names(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(name, str) and _are_names(needed) for name, needed in value.items())


def _names_types(value: Any) -> bool:
    names = value if isinstance(value, list) else [value]
    return (bool(names) and all(isinstance(name, str) and name in _TYPES for name in names)
            and len(set(names)) == len(names))


#: The shape each evaluated keyword's value must have, as draft 2020-12 gives
#: it, and how a refusal names that shape. The evaluator reads every value as
#: shaped here, so a copy whose keyword holds anything else is refused when its
#: validator is built. It is never evaluated, where it would crash on an
#: instance or judge it wrongly: a `uniqueItems: "yes"` read as true, or a
#: negative `maxLength` that no string meets. `format` and `$ref` are checked
#: beside it, with their own refusals.
_SHAPES: Mapping[str, tuple[Callable[[Any], bool], str]] = {
    "$defs": (_names_schemas, "an object of schemas"),
    "additionalProperties": (_is_schema, "a schema"),
    "allOf": (_are_schemas, "a non-empty list of schemas"),
    "anyOf": (_are_schemas, "a non-empty list of schemas"),
    "contains": (_is_schema, "a schema"),
    "dependentRequired": (_names_names,
                          "an object of lists of distinct property names"),
    "enum": (lambda value: isinstance(value, list), "a list"),
    "if": (_is_schema, "a schema"),
    "items": (_is_schema, "a schema"),
    "maxItems": (_is_count, "a non-negative integer"),
    "maxLength": (_is_count, "a non-negative integer"),
    "maxProperties": (_is_count, "a non-negative integer"),
    "maximum": (_is_bound, "a finite number"),
    "minItems": (_is_count, "a non-negative integer"),
    "minLength": (_is_count, "a non-negative integer"),
    "minProperties": (_is_count, "a non-negative integer"),
    "minimum": (_is_bound, "a finite number"),
    "not": (_is_schema, "a schema"),
    "oneOf": (_are_schemas, "a non-empty list of schemas"),
    "pattern": (lambda value: isinstance(value, str), "text"),
    "properties": (_names_schemas, "an object of schemas"),
    "propertyNames": (_is_schema, "a schema"),
    "required": (_are_names, "a list of distinct property names"),
    "then": (_is_schema, "a schema"),
    "type": (_names_types,
             f"one of {sorted(_TYPES)}, or a non-empty list of distinct ones"),
    "uniqueItems": (lambda value: isinstance(value, bool), "a boolean"),
    "x-rule": (lambda value: isinstance(value, str) and bool(value),
               "a rule's identifier"),
}


class _ContainsItself(ValueError):
    """A subschema is its own ancestor: a YAML alias can build one, and no walk
    of it ends."""


class KindValidator:
    """The validator of one kind, built over one proved copy.

    `iter_errors(instance)` yields every `Violation`: the schema's, in the
    order the schema is walked, then the reference rules', in the contract's
    catalog order, and then the rules this module owns for the copy
    (`OWNED_RULES`), in their order. `violations()` lists them and
    `is_valid()` asks whether there are none."""

    def __init__(self, kind: str, copy_id: str, pointer: str, document: Any,
                 digest: str) -> None:
        self.kind = kind
        self.copy_id = copy_id
        self.pointer = pointer
        self.digest = digest
        self._document = document
        self._patterns: dict[str, re.Pattern[str]] = {}
        self._refuse_what_is_not_evaluated(document, pointer)
        self._entry = _at_pointer(document, pointer)    # resolved, and a schema
        self._reference = self._reference_rules(document)
        self._owned = self._owned_rules(document)

    # -- building -----------------------------------------------------------

    def _not_evaluable(self, detail: str) -> SchemaNotEvaluable:
        return SchemaNotEvaluable(
            f"openDox's validator cannot evaluate its packaged copy of "
            f"{self.copy_id} for {self.kind}: {detail}")

    def _refuse_what_is_not_evaluated(self, document: Any, pointer: str) -> None:
        """Refuse the copy unless the evaluator would read all of it as it
        stands: the whole document, the kind's entry, and every reference's
        target. A reference can reach a node that no walk of the document's
        subschemas passes (one inside an `enum`, say), and the evaluator would
        read that node all the same."""
        if not isinstance(document, dict):
            raise self._not_evaluable(f"it is a {type(document).__name__}, not a schema")
        if document.get("$schema") != DIALECT:
            raise self._not_evaluable(
                f"its dialect is {document.get('$schema')!r}, not {DIALECT!r}")
        try:
            entry = _at_pointer(document, pointer)
        except (KeyError, IndexError, ValueError) as exc:
            raise self._not_evaluable(f"it has no {pointer!r} for {self.kind}") from exc
        if not _is_schema(entry):
            raise self._not_evaluable(f"its {pointer!r} for {self.kind} is a "
                                      f"{type(entry).__name__}, not a schema")
        nodes: dict[int, tuple[str, dict[str, Any]]] = {}
        pending: list[tuple[str, Any]] = [("", document), (pointer, entry)]
        try:
            while pending:
                start, subtree = pending.pop()
                for at, node in _subschemas(subtree, start):
                    if id(node) not in nodes:
                        nodes[id(node)] = (at, node)
                        pending.extend(self._refuse_node(document, at, node))
        except _ContainsItself as exc:
            raise self._not_evaluable(
                f"{exc.args[0] or '<root>'} contains itself; this module evaluates a "
                "schema that is a tree, and a copy repeats itself only by "
                "reference") from None
        except RecursionError:
            raise self._not_evaluable("it nests deeper than this module walks") from None
        cycle = _cycle_in_place(nodes, document)
        if cycle:
            raise self._not_evaluable(
                f"{' -> '.join(cycle)} is a cycle of subschemas that apply one another "
                "at one place in the instance, so no evaluation of it ends; a "
                "recursive schema moves into the instance (a property, an item) "
                "before it recurs")

    def _refuse_node(self, document: dict[str, Any], at: str,
                     node: dict[str, Any]) -> list[tuple[str, Any]]:
        """Refuse `node` unless this module evaluates it as it stands, and
        answer its reference's target, for the walk to check in its turn."""
        where = at or "<root>"
        unknown = sorted((key for key in node if key not in KEYWORDS), key=_shown)
        if unknown:
            raise self._not_evaluable(f"{where} uses {unknown}, which "
                                      "this module does not evaluate")
        if at and ("$id" in node or "$schema" in node):
            raise self._not_evaluable(
                f"{where} is an embedded resource (it carries its own "
                f"{'$id' if '$id' in node else '$schema'}), which would move where "
                "its references resolve; this module resolves every reference "
                "against the copy's root")
        for keyword in ("const", "enum"):
            if keyword in node and _holds_itself(node[keyword]):
                raise self._not_evaluable(
                    f"{where}'s {keyword} holds a value that contains itself, "
                    "which no JSON value does")
            # AND ONLY JSON VALUES (Copilot at openDox-code#58 cb40b977,
            # r4139739110). YAML builds sets, bytes and dates, which no JSON
            # value is, and a `const: !!set {a: null}` would otherwise build
            # and accept an equal set. Checked after the cycle test, so the
            # walk ends.
            stray = _first_non_json(node[keyword]) if keyword in node else None
            if stray is not None:
                raise self._not_evaluable(
                    f"{where}'s {keyword} holds {stray}, which is not a JSON "
                    "value")
        for keyword, value in node.items():
            shape = _SHAPES.get(keyword)
            if shape is not None and not shape[0](value):
                raise self._not_evaluable(
                    f"{where}'s {keyword} is {_brief(value)}, and this module "
                    f"evaluates {keyword} only as {shape[1]}")
        if "format" in node and not (isinstance(node["format"], str)
                                     and node["format"] in FORMATS):
            raise self._not_evaluable(
                f"{where} names the format {_brief(node['format'])}, which this module "
                f"does not assert (it asserts {sorted(FORMATS)})")
        if "pattern" in node:
            try:
                self._patterns[node["pattern"]] = re.compile(node["pattern"])
            except (re.error, OverflowError, RecursionError) as exc:
                raise self._not_evaluable(
                    f"{where}'s pattern does not compile ({exc})") from exc
        return self._reference_target(document, where, node) if "$ref" in node else []

    def _reference_target(self, document: dict[str, Any], where: str,
                          node: dict[str, Any]) -> list[tuple[str, Any]]:
        """What `node`'s reference names, as (pointer, target), for the walk.
        Refused unless the target is a schema inside the copy itself."""
        ref = node["$ref"]
        if not isinstance(ref, str) or not (ref == "#" or ref.startswith("#/")):
            raise self._not_evaluable(
                f"{where} refers to {_brief(ref)}; only a reference inside the copy "
                "is evaluated")
        if "%" in ref:
            # A reference's fragment is percent-encoded (RFC 3986), and this
            # module does not decode it: read literally, `a%20b` would name
            # another key than the `a b` jsonschema resolves.
            raise self._not_evaluable(
                f"{where} refers to {ref!r}, a percent-encoded fragment, which this "
                "module does not decode")
        try:
            target = _at_pointer(document, ref[1:])
        except (KeyError, IndexError, ValueError) as exc:
            raise self._not_evaluable(f"{where}'s reference {ref!r} names "
                                      "nothing in the copy") from exc
        if not _is_schema(target):
            raise self._not_evaluable(f"{where}'s reference {ref!r} names a "
                                      f"{type(target).__name__}, not a schema")
        return [(ref[1:], target)]

    def _reference_rules(self, document: dict[str, Any]
                         ) -> tuple[Callable[[Any], Iterator[Violation]], ...]:
        implemented = REFERENCE_RULES.get(self.copy_id, {})
        catalog = document.get("x-rules", [])
        if not isinstance(catalog, list) or not all(
                isinstance(rule, dict) and isinstance(rule.get("id"), str)
                for rule in catalog):
            raise self._not_evaluable("its x-rules catalog is not a list of rules "
                                      "that each carry an id")
        declared = [rule["id"] for rule in catalog if rule.get("class") == "reference"]
        if sorted(declared) != sorted(implemented):
            raise self._not_evaluable(
                f"its catalog declares the reference rules {sorted(declared)}, and "
                f"this module implements {sorted(implemented)}; a reference rule "
                "is enforced only when both name it")
        return tuple(implemented[rule] for rule in declared)

    def _owned_rules(self, document: dict[str, Any]
                     ) -> tuple[Callable[[Any], Iterator[Violation]], ...]:
        """The rules this module owns for the copy (`OWNED_RULES`), in their
        order. Refused for a copy that carries an `x-rules` catalog: the
        catalog then states every rule the copy has, and a rule this module
        also owned would be enforced from two places."""
        owned = OWNED_RULES.get(self.copy_id, {})
        if owned and "x-rules" in document:
            raise self._not_evaluable(
                f"it carries an x-rules catalog, and this module also owns the "
                f"rules {sorted(owned)} for it; a copy with a catalog has its "
                "rules from the catalog alone")
        return tuple(owned.values())

    # -- evaluating ---------------------------------------------------------

    def iter_errors(self, instance: Any) -> Iterator[Violation]:
        try:
            yield from self._evaluate(instance, self._entry, ())
        except RecursionError:
            # JUDGED, NOT CRASHED ON (Copilot at openDox-code#58 27bcefc0,
            # r4136329332). A recursive schema that moves into the instance
            # recurs once per level, so an instance nested past what Python's
            # recursion limit lets the walk reach raised out of the validator.
            # The walk's frames have unwound by the time this is yielded.
            # What it found before the limit stands, and one violation names
            # the limit, so the instance is never valid.
            yield Violation(DEPTH_RULE, (), "depth",
                            "the instance nests deeper than this validator's "
                            "evaluation can walk (Python's recursion limit), so "
                            "it is not judged valid")
        for check in self._reference:
            yield from check(instance)
        for check in self._owned:
            yield from check(instance)

    def violations(self, instance: Any) -> list[Violation]:
        return list(self.iter_errors(instance))

    def is_valid(self, instance: Any) -> bool:
        return next(self.iter_errors(instance), None) is None

    def _valid(self, value: Any, schema: Any, path: tuple[str | int, ...]) -> bool:
        return next(self._evaluate(value, schema, path), None) is None

    def _pattern(self, pattern: str) -> re.Pattern[str]:
        """The compiled pattern. The build walks every subschema the evaluator
        can reach, references' targets included, and compiles each pattern it
        meets, so this reads what the build compiled."""
        return self._patterns[pattern]

    def _evaluate(self, value: Any, schema: Any,
                  path: tuple[str | int, ...]) -> Iterator[Violation]:
        if schema is True:
            return
        if schema is False:
            yield Violation("false", path, "false", "no value is valid here")
            return
        named = schema.get("x-rule")

        def broken(keyword: str, detail: str) -> Violation:
            return Violation(named or keyword, path, keyword, detail)

        if "$ref" in schema:
            # Draft 2020-12: a reference applies BESIDE its sibling keywords.
            yield from self._evaluate(value, _at_pointer(self._document, schema["$ref"][1:]),
                                      path)
        if "type" in schema:
            names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(_is_type(value, name) for name in names):
                yield broken("type", f"{_brief(value)} is not of type {' or '.join(names)}")
        if "const" in schema and _canon(value) != _canon(schema["const"]):
            yield broken("const", f"{_brief(value)} is not {_brief(schema['const'])}")
        if "enum" in schema and _canon(value) not in {_canon(v) for v in schema["enum"]}:
            yield broken("enum", f"{_brief(value)} is not one of {_brief(schema['enum'])}")
        if isinstance(value, str):
            yield from self._string(value, schema, broken)
        if _is_number(value):
            if "minimum" in schema and value < schema["minimum"]:
                yield broken("minimum", f"{_brief(value)} is less than {_brief(schema['minimum'])}")
            if "maximum" in schema and value > schema["maximum"]:
                yield broken("maximum", f"{_brief(value)} is more than {_brief(schema['maximum'])}")
        if isinstance(value, list):
            yield from self._array(value, schema, path, broken)
        if isinstance(value, dict):
            yield from self._object(value, schema, path, broken)
        for sub in schema.get("allOf", ()):
            yield from self._evaluate(value, sub, path)
        if "anyOf" in schema:
            if not any(self._valid(value, sub, path) for sub in schema["anyOf"]):
                yield broken("anyOf", f"{_brief(value)} is valid under none of the "
                                      f"{len(schema['anyOf'])} subschemas")
        if "oneOf" in schema:
            valid = [i for i, sub in enumerate(schema["oneOf"]) if self._valid(value, sub, path)]
            if len(valid) != 1:
                yield broken("oneOf", f"{_brief(value)} is valid under "
                             + ("none" if not valid else f"subschemas {valid}")
                             + f" of the {len(schema['oneOf'])}, not exactly one")
        if "not" in schema and self._valid(value, schema["not"], path):
            yield broken("not", f"{_brief(value)} is valid under the subschema `not` refuses")
        # `if` is a test, never a failure: it only chooses whether `then` applies.
        if "if" in schema and "then" in schema and self._valid(value, schema["if"], path):
            yield from self._evaluate(value, schema["then"], path)

    def _string(self, value: str, schema: dict[str, Any],
                broken: Callable[[str, str], Violation]) -> Iterator[Violation]:
        if len(value) < schema.get("minLength", 0):
            yield broken("minLength", f"{_brief(value)} is shorter than {_brief(schema['minLength'])}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            yield broken("maxLength", f"{_brief(value)} is longer than {_brief(schema['maxLength'])}")
        if "pattern" in schema and not self._pattern(schema["pattern"]).search(value):
            yield broken("pattern", f"{_brief(value)} does not match the rule's pattern")
        if "format" in schema and not FORMATS[schema["format"]](value):
            yield broken("format", f"{_brief(value)} is not a {schema['format']}")

    def _array(self, value: list[Any], schema: dict[str, Any],
               path: tuple[str | int, ...],
               broken: Callable[[str, str], Violation]) -> Iterator[Violation]:
        if len(value) < schema.get("minItems", 0):
            yield broken("minItems", f"{len(value)} items, fewer than {_brief(schema['minItems'])}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            yield broken("maxItems", f"{len(value)} items, more than {_brief(schema['maxItems'])}")
        if schema.get("uniqueItems") and len({_canon(v) for v in value}) != len(value):
            yield broken("uniqueItems", f"{_brief(value)} repeats an item")
        if "items" in schema:
            for i, item in enumerate(value):
                yield from self._evaluate(item, schema["items"], path + (i,))
        if "contains" in schema and not any(
                self._valid(item, schema["contains"], path + (i,))
                for i, item in enumerate(value)):
            yield broken("contains", "no item is valid under the subschema `contains` asks for")

    def _object(self, value: dict[str, Any], schema: dict[str, Any],
                path: tuple[str | int, ...],
                broken: Callable[[str, str], Violation]) -> Iterator[Violation]:
        for key in schema.get("required", ()):
            if key not in value:
                yield broken("required", f"{key!r} is required")
        if len(value) < schema.get("minProperties", 0):
            yield broken("minProperties",
                         f"{len(value)} properties, fewer than {_brief(schema['minProperties'])}")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            yield broken("maxProperties",
                         f"{len(value)} properties, more than {_brief(schema['maxProperties'])}")
        for key, needed in schema.get("dependentRequired", {}).items():
            if key in value:
                for other in needed:
                    if other not in value:
                        yield broken("dependentRequired",
                                     f"{other!r} is required beside {key!r}")
        properties = schema.get("properties", {})
        for key, sub in properties.items():
            if key in value:
                yield from self._evaluate(value[key], sub, path + (key,))
        if "additionalProperties" in schema:
            extra = [key for key in value if key not in properties]
            extra_schema = schema["additionalProperties"]
            if extra_schema is False:
                if extra:
                    yield broken("additionalProperties",
                                 f"unexpected properties "
                                 f"{_brief_items(sorted(extra, key=_shown))}")
            else:
                for key in extra:
                    yield from self._evaluate(value[key], extra_schema, path + (key,))
        if "propertyNames" in schema:
            # jsonschema does not extend the path for a name: the object is where.
            for key in value:
                for found in self._evaluate(key, schema["propertyNames"], path):
                    yield Violation(found.rule, path, found.keyword,
                                    f"the property name {_brief(key)}: {found.detail}")


def _subschemas(node: Any, at: str = "", _above: frozenset[int] = frozenset()
                ) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every subschema of `node` that is an object, with its location as a JSON
    pointer. A node is yielded before its subschemas are walked, so a caller
    that refuses a malformed node stops the walk before it reads what the node
    holds. Raises `_ContainsItself` at a subschema that is its own ancestor."""
    if not isinstance(node, dict):
        return
    if id(node) in _above:
        raise _ContainsItself(at)
    yield at, node
    above = _above | {id(node)}
    for key in ("properties", "$defs"):
        for name, sub in node.get(key, {}).items() if isinstance(node.get(key), dict) else ():
            yield from _subschemas(sub, f"{at}/{key}/{_escape(name)}", above)
    for key in ("additionalProperties", "items", "contains", "propertyNames", "not",
                "if", "then"):
        if key in node:
            yield from _subschemas(node[key], f"{at}/{key}", above)
    for key in ("allOf", "anyOf", "oneOf"):
        for i, sub in enumerate(node.get(key, ())):
            yield from _subschemas(sub, f"{at}/{key}/{i}", above)


def _escape(token: Any) -> str:
    """A JSON pointer's reference token for a key."""
    return str(token).replace("~", "~0").replace("/", "~1")


def _in_place(node: dict[str, Any], document: dict[str, Any]) -> Iterator[Any]:
    """The subschemas `node` applies at the same place in the instance as
    itself: its reference's target, its `allOf`, `anyOf` and `oneOf` branches,
    its `not`, and its `if` and `then` when it has both (the evaluator reads
    neither alone). Every other applicator moves into the instance: to a
    property, an item, or a property's name."""
    if "$ref" in node:
        yield _at_pointer(document, node["$ref"][1:])
    for key in ("allOf", "anyOf", "oneOf"):
        yield from node.get(key, ())
    if "not" in node:
        yield node["not"]
    if "if" in node and "then" in node:
        yield node["if"]
        yield node["then"]


def _in_place_ids(node: dict[str, Any], nodes: Mapping[int, Any],
                  document: dict[str, Any]) -> Iterator[int]:
    return (id(sub) for sub in _in_place(node, document) if id(sub) in nodes)


def _cycle_in_place(nodes: Mapping[int, tuple[str, dict[str, Any]]],
                    document: dict[str, Any]) -> list[str]:
    """The locations around a cycle of subschemas that apply one another at
    one place in the instance, or [] when the copy has none. Evaluating such a
    cycle never moves into the instance, so it never ends, whatever the
    instance. (jsonschema recurses until Python's limit.)"""
    done: set[int] = set()
    for start in nodes:
        loop = [] if start in done else _cycle_from(start, nodes, document, done)
        if loop:
            return [nodes[node_id][0] or "<root>" for node_id in loop]
    return []


def _cycle_from(start: int, nodes: Mapping[int, tuple[str, dict[str, Any]]],
                document: dict[str, Any], done: set[int]) -> list[int]:
    """Depth first from `start`, without recursing: the first cycle met, as
    the ids around it, or [] once every node reached is marked done."""
    trail = [start]
    branches = [_in_place_ids(nodes[start][1], nodes, document)]
    while branches:
        step = next(branches[-1], None)
        if step is None:
            done.add(trail.pop())
            branches.pop()
        elif step in trail:
            return trail[trail.index(step):] + [step]
        elif step not in done:
            trail.append(step)
            branches.append(_in_place_ids(nodes[step][1], nodes, document))
    return []


# ---------------------------------------------------------------------------
# the validators, over copies proved on every call
# ---------------------------------------------------------------------------

_CACHE: dict[tuple[str, str], KindValidator] = {}
_CACHE_LOCK = threading.Lock()


def validator_for(kind: str) -> KindValidator:
    """The validator of `kind`, over its packaged copy, proved on this call.

    Raises `UnknownKind` for a kind outside the input set, and
    `ValidatorUnavailable` when the copy fails its identity check or uses
    something this module does not evaluate."""
    if kind not in KIND_ENTRIES:
        raise UnknownKind(
            f"{kind!r} is not one of openDox's own kinds; openDox's validator "
            f"validates {list(KINDS)} (#1144 7.1)")
    copy_id, pointer = KIND_ENTRIES[kind]
    try:
        data = contracts.verified_bytes(copy_id)
    except contracts.CopyRefused as exc:
        raise ValidatorUnavailable(str(exc)) from exc
    key = (kind, hashlib.sha256(data).hexdigest())
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached
    import yaml

    try:
        document = yaml.safe_load(data)
    except (yaml.YAMLError, RecursionError, ValueError) as exc:
        raise ValidatorUnavailable(
            f"the packaged copy of {copy_id} matches its digest but is not YAML "
            f"({exc.__class__.__name__})") from exc
    built = KindValidator(kind, copy_id, pointer, document, key[1])
    with _CACHE_LOCK:
        return _CACHE.setdefault(key, built)


def validators() -> dict[str, KindValidator]:
    """One validator per kind, every copy proved on this call. A fresh dict,
    so a caller changing its copy changes no other caller's."""
    return {kind: validator_for(kind) for kind in KINDS}


def doxbench_validators() -> dict[str, KindValidator]:
    """openDox's own validators for the doxBench wire kinds (`DOXBENCH_KINDS`),
    every copy proved on this call: the factory openDox registers, as its
    default, at the doxBench-validators seam (`serve_wire`; plan 034's T085,
    R1Q10 (a) and R1Q12 (a)). The seam calls it once per request, so a copy
    that changes is refused on the very request that reads it. A copy that
    fails its proof raises `ValidatorUnavailable`, and the seam's reader turns
    that into no validators, so both model routes refuse: no verdict is never
    a pass. A fresh dict on every call."""
    return {kind: validator_for(kind) for kind in DOXBENCH_KINDS}


def validate(instance: Any, *, kind: str | None = None) -> list[Violation]:
    """Every rule of `kind`'s contract that `instance` breaks.

    `kind` names the contract the instance must meet, as a generator declares
    the contract it writes (`generator_seam.SnapshotGenerator.contract`). Given
    one, the instance's own `kind` field is checked by that contract. Without
    one, the instance's own `kind` field picks the contract, and a kind that is
    not openDox's raises `UnknownKind`."""
    if kind is None:
        kind = instance.get("kind") if isinstance(instance, dict) else None
        if not isinstance(kind, str) or kind not in KIND_ENTRIES:
            raise UnknownKind(
                f"the instance's kind is {_brief(kind)}, which is not one of "
                f"openDox's own kinds {list(KINDS)} (#1144 7.1)")
    return validator_for(kind).violations(instance)
