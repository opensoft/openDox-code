"""openDox's own validator, `opendox.validator` (plan 034's T057).

`tests/test_validator_input_set.py` holds WHAT the validator reads: its four
packaged copies, each proved before it is read, and nothing else. This module
holds HOW it judges an instance against them.

THE CORPUS. `tests/fixtures/spec-examples/` is openDox-spec's own examples,
copied byte for byte from openDox-spec#16 at `cd49eb25`
(`examples/ideation-dashboard/`, T053). They are every positive example of the
four kinds, and the neutral snapshot contract's 32 negatives, one per rule.
Each negative's `# expected_failure:` line names the rule it breaks, so the
corpus asks the validator for the rule itself, not for a wording it guesses at.

WHAT IT HOLDS.

1. THE NEUTRAL CONTRACT'S RULES, ALL 32. Each negative is refused for exactly
   the rule it names, at one place, and its report names that rule as
   `[<rule>]`. Each positive is refused for nothing. The contract's catalog
   and this module's reference rules name the same seven, and every
   subschema that can fail names a catalogued shape rule, so no refusal of
   the neutral kind is left without an identifier.
2. THE OTHER THREE KINDS, STRUCTURALLY. Every positive example of theirs
   validates, and each chat-turn wire kind is judged against its own
   envelope.
3. THE EVALUATOR'S SEMANTICS, keyword by keyword, over small schemas of its
   own: JSON equality, the date-time format, the applicators, and where a
   violation is reported.
4. FAIL CLOSED. A copy that uses what this module does not evaluate is refused
   when its validator is built, never evaluated with a keyword left out.
5. jsonschema's SHAPE, FOR THE doxBench SEAM. `serve_workbench`'s two readers
   of the seam, run over `validators()`, judge the chat turn as they judge it
   over openxFactory's jsonschema validators, so plan 034's T085 can register
   them.
6. OVER openDox's OWN PROJECTION. T050's fixture, projected by openDox's own
   generator, breaks no rule, and T051's malformed fixture breaks exactly its
   `EXPECTED_RULE`. This is F7.2's judgment, in process, and T058 wires it
   into the generate verbs.
7. NO REACH. The validator imports, and validates, with every sibling blocked
   and no third-party module but PyYAML.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

from opendox import contracts
from opendox import corpus_adapter
from opendox import default_generator
from opendox import domain_profile
from opendox import generator_seam as gs
from opendox import serve_workbench
from opendox import validator as V
from opendox.runtime import local_git_adapter as lga

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLES = FIXTURES / "spec-examples"
POSITIVE = sorted(EXAMPLES.glob("*.example.yaml"))
NEGATIVE = sorted((EXAMPLES / "negative").glob("opendox-snapshot-*.negative.yaml"))
PLAIN = FIXTURES / "plain-documents"      # T050, openDox-code#53
MALFORMED = FIXTURES / "malformed"        # T051, openDox-code#56
SNAPSHOT = gs.NEUTRAL_SNAPSHOT_KIND

#: The four packages a neutral openDox must import without (#1144's F2.1).
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")


def _read(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _expected_failure(path: Path) -> str:
    named = re.findall(r"^# expected_failure: (\S+)\s*$",
                       path.read_text(encoding="utf-8"), re.M)
    assert len(named) == 1, f"{path.name} must name exactly one expected_failure: {named}"
    return named[0]


def _contract() -> dict[str, Any]:
    return contracts.load("opendox-snapshot")


def _built(schema: dict[str, Any], *, copy_id: str = "a-test-schema",
           pointer: str = "") -> V.KindValidator:
    """A validator over a schema of the test's own, in the copies' dialect."""
    return V.KindValidator("a-test-kind", copy_id, pointer,
                           {"$schema": V.DIALECT, **schema}, "0" * 64)


def _found(schema: dict[str, Any], instance: Any) -> set[tuple[str, str]]:
    return {(v.keyword, v.where) for v in _built(schema).iter_errors(instance)}


# ---------------------------------------------------------------------------
# 1. the neutral contract's 32 rules
# ---------------------------------------------------------------------------

def test_the_corpus_is_one_negative_per_rule_and_the_two_positives() -> None:
    catalog = [rule["id"] for rule in _contract()["x-rules"]]
    assert len(catalog) == 32
    assert sorted(_expected_failure(path) for path in NEGATIVE) == sorted(catalog)
    assert [p.name for p in POSITIVE if p.name.startswith("opendox-snapshot-")] == [
        "opendox-snapshot-no-front-matter.example.yaml",
        "opendox-snapshot-six-stations.example.yaml"]


@pytest.mark.parametrize("path", NEGATIVE, ids=lambda p: p.name)
def test_a_negative_is_refused_for_its_rule_alone_and_its_report_names_it(
        path: Path) -> None:
    """Validated against the neutral contract, as openDox's generator declares
    it writes, each negative breaks exactly the rule its header names, at one
    place, and every line of the report opens with `[<rule>]`."""
    expected = _expected_failure(path)
    found = V.validate(_read(path), kind=SNAPSHOT)
    assert {v.rule for v in found} == {expected}, V.report(found)
    assert len({v.where for v in found}) == 1, V.report(found)
    assert all(line.startswith(f"[{expected}] ") for line in V.report(found))


@pytest.mark.parametrize("path", [p for p in POSITIVE if p.name.startswith("opendox-")],
                         ids=lambda p: p.name)
def test_a_positive_breaks_no_rule(path: Path) -> None:
    assert V.validate(_read(path)) == []
    assert V.validate(_read(path), kind=SNAPSHOT) == []


def test_the_catalog_and_the_reference_rules_are_one_set() -> None:
    """25 shape rules and 7 reference rules. This module implements exactly
    the seven the catalog declares, and in the catalog's order."""
    catalog = _contract()["x-rules"]
    reference = [rule["id"] for rule in catalog if rule["class"] == "reference"]
    shape = [rule["id"] for rule in catalog if rule["class"] == "shape"]
    assert (len(shape), len(reference)) == (25, 7)
    assert list(V.REFERENCE_RULES["opendox-snapshot"]) == reference
    assert set(V.REFERENCE_RULES) == {"opendox-snapshot"}


def test_every_subschema_of_the_neutral_contract_that_can_fail_names_its_rule() -> None:
    """So every refusal of the neutral kind carries the contract's identifier,
    and none falls back to a bare keyword."""
    catalog = {rule["id"]: rule["class"] for rule in _contract()["x-rules"]}
    can_fail = V._ASSERTING | {"anyOf", "oneOf", "not", "contains"}
    named = set()
    for at, node in V._subschemas(_contract()):
        if "if" in at.split("/"):
            continue            # an `if` is a test and never reports
        if can_fail & set(node):
            assert "x-rule" in node, f"{at or '<root>'} can fail and names no rule"
        if "x-rule" in node:
            assert catalog.get(node["x-rule"]) == "shape", (at, node["x-rule"])
            named.add(node["x-rule"])
    assert named == {rule for rule, cls in catalog.items() if cls == "shape"}


def test_the_governed_kind_is_refused_as_a_rule_or_as_unknown() -> None:
    """A snapshot of the consumer's governed kind is not openDox's. Asked for
    the neutral contract, the validator refuses it for
    `kind-is-opendox-snapshot`; asked to pick a contract by the instance's own
    kind, it has none, and says so rather than answering an empty list."""
    governed = _read(EXAMPLES / "negative" /
                     "opendox-snapshot-kind-is-opendox-snapshot.negative.yaml")
    assert governed["kind"] == "ideation-dashboard-snapshot"
    assert {v.rule for v in V.validate(governed, kind=SNAPSHOT)} == {"kind-is-opendox-snapshot"}
    with pytest.raises(V.UnknownKind):
        V.validate(governed)
    for not_an_instance in ([], "opendox-snapshot", None, {"kind": 1}):
        with pytest.raises(V.UnknownKind):
            V.validate(not_an_instance)
    with pytest.raises(V.UnknownKind):
        V.validate({}, kind="ideation-dashboard-snapshot")


def test_a_report_line_names_the_rule_the_place_and_what_was_found() -> None:
    snap = _read(EXAMPLES / "opendox-snapshot-no-front-matter.example.yaml")
    snap["documents"][0]["title"] = ""
    snap["clusters"][0]["document_edges"][0]["document"] = "nowhere.md"
    lines = V.report(V.validate(snap, kind=SNAPSHOT))
    assert lines == [
        "[title-and-summary-are-text] /documents/0/title: '' is shorter than 1",
        "[edge-names-a-document] /clusters/0/document_edges/0/document: "
        "no document has the id 'nowhere.md'",
    ], lines


def test_a_pointer_escapes_its_keys_and_the_root_is_named() -> None:
    violation = V.Violation("r", ("a/b", "c~d", 0), "type", "detail")
    assert violation.where == "/a~1b/c~0d/0"
    assert V.Violation("envelope-keys", (), "type", "x").line() == "[envelope-keys] <root>: x"


# ---------------------------------------------------------------------------
# 2. the other three kinds, structurally
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", [p for p in POSITIVE if not p.name.startswith("opendox-")],
                         ids=lambda p: p.name)
def test_every_positive_example_of_the_other_kinds_validates(path: Path) -> None:
    instance = _read(path)
    assert instance["kind"] in V.KIND_ENTRIES
    assert V.validate(instance) == [], V.report(V.validate(instance))


def test_each_chat_turn_kind_is_judged_against_its_own_envelope() -> None:
    """A success envelope is valid as a success and not as a request: each
    wire kind is its own envelope, as openxFactory's `CHAT_TURN_DEFS` names
    them, and not the chat-turn file's three-way `oneOf`."""
    success = _read(EXAMPLES / "workbench-chat-turn-v2-success.example.yaml")
    assert V.validate(success, kind="workbench-chat-turn-v2-success") == []
    as_request = V.validate(success, kind="workbench-chat-turn-v2")
    assert ("const", "/kind") in {(v.keyword, v.where) for v in as_request}
    assert "oneOf" not in {v.keyword for v in as_request}


# ---------------------------------------------------------------------------
# 3. the evaluator, keyword by keyword
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("types, value, ok", [
    ("integer", 2, True), ("integer", 2.0, True), ("integer", 2.5, False),
    ("integer", True, False), ("number", 1.5, True), ("number", False, False),
    ("boolean", 0, False), ("null", None, True), ("string", None, False),
    (["string", "null"], None, True), ("array", {}, False), ("object", [], False),
], ids=repr)
def test_type_is_json_type(types: Any, value: Any, ok: bool) -> None:
    """JSON's types: `true` is not a number, and 2.0 is the integer 2."""
    assert (not _found({"type": types}, value)) is ok


@pytest.mark.parametrize("schema, value, ok", [
    ({"const": 1}, 1.0, True), ({"const": 1}, True, False),
    ({"const": {"a": 1, "b": [1, 2]}}, {"b": [1.0, 2], "a": 1}, True),
    ({"const": [1, 2]}, [2, 1], False),
    ({"enum": [False, "x"]}, 0, False), ({"enum": [False, "x"]}, False, True),
    ({"uniqueItems": True}, [1, 1.0], False), ({"uniqueItems": True}, [1, True], True),
    ({"uniqueItems": True}, [{"a": 1}, {"a": 1}], False),
    ({"uniqueItems": True}, [{1: "a"}, {"1": "a"}], True),
], ids=repr)
def test_const_enum_and_uniqueness_are_json_equality(schema: dict, value: Any,
                                                    ok: bool) -> None:
    assert (not _found(schema, value)) is ok


@pytest.mark.parametrize("value, ok", [
    ("2026-09-27T12:00:00Z", True), ("2026-09-27t12:00:00.25+05:30", True),
    ("2024-02-29T00:00:00Z", True), ("2000-02-29T23:59:59z", True),
    ("0001-01-01T00:00:00Z", True),
    ("2026-02-29T00:00:00Z", False), ("1900-02-29T00:00:00Z", False),
    ("2026-04-31T00:00:00Z", False), ("2026-13-01T00:00:00Z", False),
    ("0000-01-01T00:00:00Z", False), ("2016-12-31T23:59:60Z", False),
    ("2026-09-27T24:00:00Z", False), ("2026-09-27T12:00:00", False),
    ("2026-09-27", False), ("2026-09-27T12:00:00+0530", False),
    ("２０２６-09-27T12:00:00Z", False),
    ("2026-09-27T12:00:00Z\n", False),
], ids=repr)
def test_the_date_time_format_is_asserted(value: str, ok: bool) -> None:
    """RFC 3339, as the consumer's validator asserts it: ASCII digits, a year
    other than 0000, a day the month has, no leap second. The whole value must
    match, so a trailing newline is refused, which is the one place this is
    stricter than `rfc3339-validator`. `format` holds only for text."""
    assert (not _found({"format": "date-time"}, value)) is ok
    assert not _found({"format": "date-time"}, 12)


def test_lengths_count_characters_and_a_pattern_searches() -> None:
    assert _found({"minLength": 2, "maxLength": 3}, "é") == {("minLength", "")}
    assert not _found({"minLength": 2, "maxLength": 3}, "éé")
    assert _found({"maxLength": 3}, "abcd") == {("maxLength", "")}
    # A JSON Schema pattern is not anchored: `b` is found inside `abc`.
    assert not _found({"pattern": "b"}, "abc")
    assert _found({"pattern": "^b"}, "abc") == {("pattern", "")}
    # A length or a pattern says nothing about a value that is not text.
    assert not _found({"minLength": 5, "pattern": "^x$"}, 7)


def test_numbers_have_bounds_and_booleans_are_not_numbers() -> None:
    assert _found({"minimum": 0, "maximum": 3}, -1) == {("minimum", "")}
    assert _found({"minimum": 0, "maximum": 3}, 4) == {("maximum", "")}
    assert not _found({"minimum": 0, "maximum": 3}, 3.0)
    assert not _found({"minimum": 1}, False)


def test_array_keywords() -> None:
    schema = {"minItems": 1, "maxItems": 2, "items": {"type": "string"},
              "contains": {"const": "x"}}
    assert _found(schema, []) == {("minItems", ""), ("contains", "")}
    assert _found(schema, ["x", "y", "z"]) == {("maxItems", "")}
    assert _found(schema, ["x", 1]) == {("type", "/1")}
    assert _found(schema, ["y"]) == {("contains", "")}


def test_object_keywords() -> None:
    schema = {"required": ["a"], "minProperties": 1, "maxProperties": 2,
              "dependentRequired": {"b": ["c"]},
              "properties": {"a": {"type": "string"}, "b": {}, "c": {}},
              "additionalProperties": False}
    assert _found(schema, {}) == {("required", ""), ("minProperties", "")}
    assert _found(schema, {"a": 1}) == {("type", "/a")}
    assert _found(schema, {"a": "x", "b": 1}) == {("dependentRequired", "")}
    assert _found(schema, {"a": "x", "b": 1, "c": 2}) == {("maxProperties", "")}
    assert _found(schema, {"a": "x", "z": 1}) == {("additionalProperties", "")}
    # An additionalProperties SCHEMA judges each unnamed property where it is.
    assert _found({"properties": {"a": {}}, "additionalProperties": {"type": "integer"}},
                  {"a": "x", "z": "y"}) == {("type", "/z")}


def test_property_names_are_judged_at_the_object() -> None:
    """jsonschema reports a bad property NAME at the object, with the keyword
    that refused the name, and so does this module."""
    found = _built({"properties": {"o": {"propertyNames": {"pattern": "^[a-z]+$"},
                                         "maxProperties": 5}}}).violations(
        {"o": {"ok": 1, "Not OK": 2}})
    assert [(v.keyword, v.where) for v in found] == [("pattern", "/o")]
    assert "Not OK" in found[0].detail


def test_applicators() -> None:
    one_of = {"oneOf": [{"type": "integer"}, {"minimum": 0}]}
    assert _found(one_of, -1) == set()                      # integer only
    assert _found(one_of, 1) == {("oneOf", "")}             # both
    assert _found(one_of, "x") == set()                     # `minimum` holds for text
    assert _found({"oneOf": [{"type": "integer"}, {"type": "null"}]}, "x") == {("oneOf", "")}
    any_of = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    assert _found(any_of, "x") == {("anyOf", "")} and not _found(any_of, None)
    assert _found({"not": {"required": ["a"]}}, {"a": 1}) == {("not", "")}
    assert _found({"allOf": [{"minimum": 1}, {"maximum": 0}]}, 0.5) == {
        ("minimum", ""), ("maximum", "")}
    # `if` never reports; it only chooses whether `then` applies.
    conditional = {"if": {"properties": {"k": {"const": "a"}}, "required": ["k"]},
                   "then": {"required": ["a"]}}
    assert _found(conditional, {"k": "a"}) == {("required", "")}
    assert not _found(conditional, {"k": "b"})
    assert not _found(conditional, {})


def test_a_reference_applies_beside_its_siblings_and_names_its_own_rule() -> None:
    """Draft 2020-12: `$ref` applies BESIDE the keywords next to it, and a
    violation found through the reference carries the referenced subschema's
    rule."""
    built = _built({"properties": {"n": {"$ref": "#/$defs/n", "x-rule": "outer",
                                         "maximum": 5}},
                    "$defs": {"n": {"x-rule": "inner", "type": "integer"}}})
    assert {(v.rule, v.keyword) for v in built.violations({"n": 6.5})} == {
        ("inner", "type"), ("outer", "maximum")}


def test_a_boolean_schema() -> None:
    assert not _found({"properties": {"a": True}}, {"a": object()})
    assert _found({"properties": {"a": False}}, {"a": 1}) == {("false", "/a")}


# ---------------------------------------------------------------------------
# 4. fail closed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("schema, says", [
    ({"patternProperties": {"^x": {}}}, "does not evaluate"),
    ({"properties": {"a": {"else": {}}}}, "does not evaluate"),
    ({"format": "uri"}, "does not assert"),
    ({"$ref": "other.schema.yaml#/$defs/x"}, "only a reference inside the copy"),
    ({"$ref": "#/$defs/missing"}, "names nothing in the copy"),
    ({"$ref": "#/title", "title": "t"}, "not a schema"),
    ({"pattern": "("}, "does not compile"),
    ({"type": "text"}, "names the type"),
    ({"x-rules": [{"id": "r", "class": "reference", "says": "?"}]},
     "implements []"),
    ({"x-rules": ["not a rule"]}, "each carry an id"),
], ids=["patternProperties", "else", "a format", "a remote reference",
        "a dangling reference", "a reference to text", "a bad pattern",
        "an unknown type", "an unimplemented reference rule", "a malformed catalog"])
def test_what_is_not_evaluated_is_refused_when_the_validator_is_built(
        schema: dict, says: str) -> None:
    with pytest.raises(V.SchemaNotEvaluable) as refused:
        _built(schema)
    assert says in str(refused.value)
    assert isinstance(refused.value, V.ValidatorUnavailable)


def test_another_dialect_is_refused() -> None:
    with pytest.raises(V.SchemaNotEvaluable) as refused:
        V.KindValidator("k", "c", "", {"$schema": "http://json-schema.org/draft-07/schema#"},
                        "0" * 64)
    assert "dialect" in str(refused.value)


def test_a_reference_rule_the_catalog_does_not_declare_is_not_enforced() -> None:
    """The neutral contract's catalog, less one reference rule, is refused:
    this module implements it and the contract would not declare it."""
    contract = _contract()
    contract["x-rules"] = [r for r in contract["x-rules"] if r["id"] != "ids-are-unique"]
    with pytest.raises(V.SchemaNotEvaluable) as refused:
        V.KindValidator(SNAPSHOT, "opendox-snapshot", "", contract, "0" * 64)
    assert "ids-are-unique" in str(refused.value)


def test_every_copy_builds_and_is_cached_by_its_proved_digest() -> None:
    first = V.validators()
    assert sorted(first) == list(V.KINDS)
    again = V.validators()
    assert first is not again and all(first[k] is again[k] for k in V.KINDS)
    for kind, built in first.items():
        copy_id, pointer = V.KIND_ENTRIES[kind]
        assert (built.kind, built.copy_id, built.pointer) == (kind, copy_id, pointer)
        assert built.digest == contracts.record().copy(copy_id).sha256


# ---------------------------------------------------------------------------
# 5. the doxBench seam's two readers, over these validators
# ---------------------------------------------------------------------------

def test_the_doxbench_seams_readers_judge_the_chat_turn_through_these_validators() -> None:
    """`serve_workbench` reads a validator's `iter_errors()` and each error's
    `validator` and `absolute_path`, as jsonschema spells them. Over
    `validators()`, a valid request conforms; a request carrying only the
    outline breaks the buffers' `minItems` floor and nothing else; and one
    that breaks something besides is told apart from it."""
    seam = serve_workbench.WorkbenchRoutes
    validators = V.validators()
    request = _read(EXAMPLES / "workbench-chat-turn-v2-loaded-set.example.yaml")
    kind = request["kind"]
    assert seam._doxbench_wire_conforms(validators, kind, request)
    assert not seam._doxbench_violation_beside_the_buffers_floor(validators, kind, request)

    outline_only = {**request, "buffers": [b for b in request["buffers"]
                                           if b.get("kind") == "outline"]}
    assert len(outline_only["buffers"]) == 1
    errors = list(validators[kind].iter_errors(outline_only))
    assert [(e.validator, list(e.absolute_path)) for e in errors] == [("minItems", ["buffers"])]
    assert not seam._doxbench_wire_conforms(validators, kind, outline_only)
    assert not seam._doxbench_violation_beside_the_buffers_floor(validators, kind,
                                                                 outline_only)

    and_more = {**outline_only, "message": ""}
    assert seam._doxbench_violation_beside_the_buffers_floor(validators, kind, and_more)
    # A kind with no validator is no verdict, and no verdict is not consent.
    assert not seam._doxbench_wire_conforms(validators, "workbench-chat-turn", request)


# ---------------------------------------------------------------------------
# 6. over openDox's own projection (F7.2's judgment, in process)
# ---------------------------------------------------------------------------

ANCHOR_DATE = "2026-09-27T12:00:00+00:00"


def _git(root: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": ANCHOR_DATE, "GIT_COMMITTER_DATE": ANCHOR_DATE,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
    })
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def _committed_copy(tmp_path: Path, fixture: Path) -> Path:
    root = tmp_path / fixture.name
    shutil.copytree(fixture, root)
    _git(root, "-c", "init.defaultBranch=main", "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "fixture")
    return root


@pytest.fixture
def _default_home():
    """openDox's default home corpus registered, and the registry put back."""
    saved = corpus_adapter._home_factory
    corpus_adapter.register_home(lambda root: (
        lga.WorkingTreeCorpus(), corpus_adapter.CorpusRef(name="home", location=str(root))))
    yield
    corpus_adapter._home_factory = saved


def test_openDox_projection_of_the_plain_fixture_breaks_no_rule(
        tmp_path: Path, _default_home) -> None:
    snapshot = default_generator.generate(_committed_copy(tmp_path, PLAIN), "fixture")
    assert snapshot["kind"] == SNAPSHOT
    assert V.validate(snapshot, kind=default_generator.GENERATOR.contract) == []


def test_openDox_projection_of_the_malformed_fixture_breaks_its_expected_rule(
        tmp_path: Path, _default_home) -> None:
    """T051's fixture breaks exactly one rule, and the report names the rule
    `EXPECTED_RULE` holds, which is what F7.2 greps the verbs' output for."""
    rule = (MALFORMED / "EXPECTED_RULE").read_text(encoding="utf-8").strip()
    snapshot = default_generator.generate(_committed_copy(tmp_path, MALFORMED), "fixture")
    found = V.validate(snapshot, kind=SNAPSHOT)
    assert [(v.rule, v.where) for v in found] == [(rule, "/documents/1/title")], V.report(found)
    assert any(rule in line for line in V.report(found))


# ---------------------------------------------------------------------------
# 7. no reach
# ---------------------------------------------------------------------------

_BLOCKED = """
import json, sys
for name in SIBLINGS:
    sys.modules[name] = None
before = set(sys.modules)
import yaml     # what PyYAML brings with it (its C binding's runtime) is PyYAML's
pyyaml = sorted({m.split(".")[0] for m in set(sys.modules) - before})
from opendox import validator
built = validator.validators()
snap = {"schema_version": 1, "kind": "opendox-snapshot", "repository": "r",
        "generation": {"source_revision": "HEAD"}, "documents": [], "clusters": [],
        "possibles": [], "staged_topics": [], "changes": []}
print(json.dumps({"kinds": sorted(built), "violations": validator.report(validator.validate(snap)),
                  "pyyaml": pyyaml,
                  "siblings": [n for n in SIBLINGS if sys.modules.get(n) is not None],
                  "new": sorted({m.split(".")[0] for m in set(sys.modules) - before})}))
"""


def test_the_validator_imports_and_validates_with_every_sibling_blocked() -> None:
    program = (f"import sys; sys.path.insert(0, {str(SRC)!r})\n"
               f"SIBLINGS = {SIBLINGS!r}\n" + textwrap.dedent(_BLOCKED))
    done = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True,
                          cwd=str(ROOT), timeout=120)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["kinds"] == list(V.KINDS)
    assert out["violations"] == []
    assert "yaml" in out["pyyaml"]
    third_party = sorted(set(out["new"]) - set(sys.stdlib_module_names)
                         - {"opendox"} - set(out["pyyaml"]) - set(SIBLINGS))
    assert third_party == [], third_party
    assert out["siblings"] == [], "a sibling was imported past its block"


def test_the_validator_leaves_the_registries_as_it_found_them() -> None:
    """Validating registers nothing: no profile, no generator, no home."""
    before = (domain_profile._registered, gs._registered, corpus_adapter._home_factory)
    V.validate(_read(EXAMPLES / "opendox-snapshot-six-stations.example.yaml"))
    assert (domain_profile._registered, gs._registered,
            corpus_adapter._home_factory) == before
