"""openDox's health contract module, `opendox.health_contract` (plan 038 T041,
U-0; decisions N-3, N-13, N-15 and OQ-H15-19; R2Q10 (a), R2Q18 (a), R2Q22 (a)
and R2Q25 (a); the holder's rulings `openxFactory#656` `6018624750` and
`6027706377` item 1).

THE FALSIFIER, SPLIT BY LAYER (`6027706377` item 1). T041's falsifier asserts
the bound on THIS MODULE'S OWN serialized finding shape: what `to_json()`
writes, the one serialization the contract module owns. What `health list
--json` emits is T046's falsifier, and what the HTTP Health response emits is
T057's. Neither surface exists here, and nothing below pretends to test it.
The bound, on a finding's `identity`, is openDox-spec's finding schema's (T040,
landed as openDox-spec `7db9438b`):

* no key named `excerpt`, `text`, `content` or `quote`, at any depth;
* no number, at any depth;
* every string, key or value, at most 200 characters;
* `{category, entry}` for a pathless finding, and `{collided_id}` for a
  collision.

The falsifier is section 1: every identity the contract names, built through
the module and serialized, holds the bound, and every identity outside it is
refused before it can be serialized.

WHAT ELSE IT HOLDS.

2. THE VOCABULARY IS THE PACKAGED COPY'S. The classes, the severities, the
   baseline classes, the fields, the forbidden keys, the string bound and the
   rule catalog are read from openDox-code's digest-checked copy of the
   finding schema and compared with the module's constants. The module
   mirrors the copy; it never reads it (it may import the standard library
   alone, R2Q18 (a)).
3. THE ID RULE (N-13, refined by ADV-07). The key is exactly the four fields,
   in canonical sorted-key JSON, UTF-8, each character as itself. Every id in
   openDox-spec's five finding examples is the id the module computes, each
   part of the key moves the id, and nothing outside the key does.
4. NAMES OF 1 TO 40 CHARACTERS. `pack_id` and `kind` are capped at 40, so a
   fix branch's name stays bounded. 40 is admitted, 41 refused, and the
   schema itself admits 41, so the cap is the engine's, stricter.
5. THE IDENTITY'S SERIALIZED-SIZE CAP, the engine's, stricter than the schema
   (`IDENTITY_MAX_BYTES`, which T042 stores and T046 enforces): admitted at
   its bound, refused one byte over, and an identity the schema admits is
   refused by it. The nesting bound beside it.
6. THE BOUNDS ON `message` AND `evidence` (R2Q25 (a); ADV-27).
7. EVERY RULE THE COPY CATALOGUES IS ENFORCED. Each of its 27 rules has one
   negative case, openDox-spec's own negative example rebuilt, refused for
   that rule and no other; so are the module's four engine rules.
8. THE ENGINE'S OWN IDENTITIES AND CATEGORIES, and openDox-spec's five
   examples rebuilt through `make_finding()`, id included.
9. THE CLOSURE: the module imports the standard library and nothing else. Its
   imports are read from its source, it is imported in a fresh interpreter
   that blocks openXdox and openxFactory, and it runs from a directory that
   holds it alone, under `python -I -S`, with no site-packages: what the
   sandbox binds (R2Q18 (a), T048).
10. A REFUSAL QUOTES NOTHING OF THE FINDING: no refused string, key or value
    reaches a refusal's text.

`--noconftest` SAFE. A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Iterator

import pytest

from opendox import contracts
from opendox import health_contract as hc

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
MODULE = SRC / "opendox" / "health_contract.py"

#: The packaged copy of openDox-spec's finding schema (T040), which the
#: module mirrors (N-15: a copy the engine reads, not a validator kind).
FINDING_COPY = "opendox-health-finding"

#: The bound, as T040's schema and the holder's `6018624750` state it, written
#: here apart from the module so that a changed constant there fails here.
FORBIDDEN = ("excerpt", "text", "content", "quote")
STRING_MAX = 200
NAME_MAX = 40
IDENTITY_MAX_BYTES = 2048

#: openDox-spec's five finding examples at `7db9438b`
#: (`examples/health/opendox-health-finding-*.example.yaml`), as values. Each
#: id is the one openDox-spec's own test computes by the id rule.
EXAMPLES: dict[str, dict[str, Any]] = {
    "broken-link": {
        "id": "opendox.broken-link.546cd2aacb1a6738",
        "kind": "broken-link",
        "pack_id": "opendox",
        "pack_version": "0.2.0",
        "path": "notes/plan.md",
        "identity": {"target": "../old/brief.md"},
        "locator": {"line_start": 12, "line_end": 12},
        "severity": "warning",
        "resolution_class": "auto-fix",
        "message": "link target does not exist; a unique file of that name exists elsewhere",
        "evidence": {"candidate": "archive/brief.md", "family_version": "1"},
        "baseline_class": "new",
    },
    "identity-collision": {
        "id": "house-style.identity-collision.b722027596ad8c96",
        "kind": "identity-collision",
        "pack_id": "house-style",
        "pack_version": "1.4.0",
        "path": "notes/plan.md",
        "identity": {"collided_id": "house-style.heading-case.0f1e2d3c4b5a6978"},
        "severity": "error",
        "resolution_class": "human-only",
        "message": ("two findings of one run share one id; the pack must give them "
                    "identity keys that differ"),
        "evidence": {"collided_id": "house-style.heading-case.0f1e2d3c4b5a6978",
                     "count": 2},
        "baseline_class": "new",
    },
    "no-sandbox": {
        "id": "opendox.no-sandbox.5ccbb79891acb2e8",
        "kind": "no-sandbox",
        "pack_id": "opendox",
        "pack_version": "0.2.0",
        "path": "",
        "identity": {"category": "no-sandbox", "entry": ""},
        "severity": "warning",
        "resolution_class": "human-only",
        "message": "no live sandbox on this install, so no check pack ran",
        "evidence": {"probe": "bwrap", "verdict": "absent"},
    },
    "orphan": {
        "id": "opendox.orphan.516a58a1fcc2c37f",
        "kind": "orphan",
        "pack_id": "opendox",
        "pack_version": "0.2.0",
        "path": "notes/appendix.md",
        "identity": {},
        "severity": "info",
        "resolution_class": "human-only",
        "message": "nothing links to this document",
        "evidence": {},
        "baseline_class": "persistent",
    },
    "pack-upgrade": {
        "id": "house-style.heading-case.a5db1a71f8b8340d",
        "kind": "heading-case",
        "pack_id": "house-style",
        "pack_version": "1.4.0",
        "path": "notes/caf\u00e9-menu.md",
        "identity": {"heading": "seasonal-specials"},
        "locator": {"line_start": 3, "line_end": 3},
        "severity": "info",
        "resolution_class": "assisted",
        "message": "a heading is not in the house case",
        "evidence": {"family_version": "2", "lines": [3, 3]},
        "baseline_class": "pack-upgrade",
    },
}

#: openDox-spec's 201-character passage, from its negative examples.
PASSAGE = ("The old brief said the launch would wait for the second review, and that "
           "the budget would be settled by the steering group before any vendor was "
           "asked to quote; this sentence is document text, two hund")


def _example(name: str) -> dict[str, Any]:
    return copy.deepcopy(EXAMPLES[name])


def _rules(finding: Any) -> list[str]:
    return [v.rule for v in hc.violations(finding)]


def _independent_id(pack_id: str, kind: str, path: str, identity: Any) -> str:
    """The id rule as openDox-spec's own test spells it, apart from the
    module."""
    key = json.dumps({"identity": identity, "kind": kind, "pack_id": pack_id, "path": path},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"{pack_id}.{kind}.{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def _walk(value: Any) -> Iterator[tuple[str, Any]]:
    """Every (role, item) under `value`: role is "key" for an object's key,
    "value" for anything else, at any depth."""
    stack = [value]
    while stack:
        item = stack.pop()
        yield "value", item
        if isinstance(item, dict):
            for key, inner in item.items():
                yield "key", key
                stack.append(inner)
        elif isinstance(item, list):
            stack.extend(item)


def _fields(finding: dict[str, Any]) -> dict[str, Any]:
    """`make_finding()`'s arguments for an example: every field but the
    engine's id."""
    return {k: v for k, v in finding.items() if k != "id"}


# ---------------------------------------------------------------------------
# 1. the falsifier: the module's own serialized identity holds the bound
# ---------------------------------------------------------------------------

#: A pair of corpus paths, each at the 200-character string bound.
_PATH_A = "notes/" + "a" * 191 + ".md"
_PATH_B = "notes/" + "b" * 191 + ".md"

#: Each identity the contract names, as (path, kind, identity, class).
_IDENTITIES: dict[str, tuple[str, str, Any, str]] = {
    "a link target as written": ("notes/plan.md", "broken-link",
                                 {"target": "../old/brief.md"}, "auto-fix"),
    "a pair of paths": ("notes/plan.md", "near-duplicate",
                        {"first": _PATH_A, "second": _PATH_B}, "assisted"),
    "a heading key": ("notes/caf\u00e9-menu.md", "heading-case",
                      {"heading": "seasonal-specials"}, "assisted"),
    "every value an identity admits": (
        "notes/plan.md", "house-rule",
        {"flags": [True, False, None], "nested": {"k": ["a", {"b": "c"}]},
         "long": "x" * 200, "y" * 200: "short", "empty": [], "none": None},
        "human-only"),
    "an empty identity": ("notes/appendix.md", "orphan", {}, "human-only"),
    "a pathless finding": ("", "no-sandbox", hc.pathless_identity("no-sandbox"),
                           "human-only"),
    "a pathless finding about an entry": (
        "", "fetch-failed", hc.pathless_identity("fetch-failed", "house-style"),
        "human-only"),
    "a collision": ("notes/plan.md", "identity-collision",
                    hc.collision_identity("house-style.heading-case.0f1e2d3c4b5a6978"),
                    "human-only"),
    "a pathless collision": ("", "identity-collision",
                             hc.collision_identity("opendox.no-sandbox.5ccbb79891acb2e8"),
                             "human-only"),
}


def _build(name: str) -> dict[str, Any]:
    path, kind, identity, resolution = _IDENTITIES[name]
    return hc.make_finding(kind=kind, pack_id="opendox", pack_version="0.2.0", path=path,
                           identity=identity, severity="warning",
                           resolution_class=resolution, message="a finding")


@pytest.mark.parametrize("name", list(_IDENTITIES))
def test_the_serialized_identity_holds_the_schemas_bound(name: str) -> None:
    """THE FALSIFIER (T041, split by layer, `6027706377` item 1): the
    identity this module writes holds exactly T040's bound. It is stored and
    emitted with the finding, and the id is its hash (`6018624750`)."""
    finding = _build(name)
    emitted = json.loads(hc.to_json(finding))
    identity = emitted["identity"]
    assert isinstance(identity, dict)
    keys = [item for role, item in _walk(identity) if role == "key"]
    values = [item for role, item in _walk(identity) if role == "value"]
    # no key named excerpt, text, content or quote, at any depth
    assert not set(keys) & set(FORBIDDEN), keys
    # no number, at any depth (true and false are not numbers)
    assert not [v for v in values
                if isinstance(v, (int, float)) and not isinstance(v, bool)], values
    # every string, key or value, at most 200 characters
    strings = keys + [v for v in values if isinstance(v, str)]
    assert all(len(s) <= STRING_MAX for s in strings), [len(s) for s in strings]
    # the engine's own keys
    if emitted["kind"] == "identity-collision":
        assert sorted(identity) == ["collided_id"]
    elif emitted["path"] == "":
        assert sorted(identity) == ["category", "entry"]
    # stored and emitted, and hashed into the id
    assert identity == _IDENTITIES[name][2]
    assert emitted["id"] == _independent_id(emitted["pack_id"], emitted["kind"],
                                            emitted["path"], identity)
    assert hc.identity_json(identity) == json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


_REFUSED_IDENTITIES = [
    *[({word: "a"}, "notes/plan.md", "broken-link", "identity-names-no-text")
      for word in FORBIDDEN],
    *[({"a": {word: "b"}}, "notes/plan.md", "broken-link", "identity-names-no-text")
      for word in FORBIDDEN],
    *[({"a": [{word: "b"}]}, "notes/plan.md", "broken-link", "identity-names-no-text")
      for word in FORBIDDEN],
    ({"target": "../old/brief.md", "line": 12}, "notes/plan.md", "broken-link",
     "identity-holds-no-number"),
    ({"a": 1.5}, "notes/plan.md", "broken-link", "identity-holds-no-number"),
    ({"a": 0}, "notes/plan.md", "broken-link", "identity-holds-no-number"),
    ({"a": -3}, "notes/plan.md", "broken-link", "identity-holds-no-number"),
    ({"a": [True, 1]}, "notes/plan.md", "broken-link", "identity-holds-no-number"),
    ({"a": {"b": 1e21}}, "notes/plan.md", "broken-link", "identity-holds-no-number"),
    ({"target": PASSAGE}, "notes/plan.md", "broken-link",
     "identity-strings-are-short-text"),
    ({"a" * 201: "b"}, "notes/plan.md", "broken-link", "identity-strings-are-short-text"),
    ({"a": ["x" * 201]}, "notes/plan.md", "broken-link", "identity-strings-are-short-text"),
    ({"a": {"b": "x" * 201}}, "notes/plan.md", "broken-link",
     "identity-strings-are-short-text"),
    ({"a": {"b" * 201: "x"}}, "notes/plan.md", "broken-link",
     "identity-strings-are-short-text"),
    (["../old/brief.md"], "notes/plan.md", "broken-link", "identity-is-an-object"),
    ("../old/brief.md", "notes/plan.md", "broken-link", "identity-is-an-object"),
    ({}, "", "no-sandbox", "pathless-identity-is-category-and-entry"),
    ({"category": "no-sandbox"}, "", "no-sandbox",
     "pathless-identity-is-category-and-entry"),
    ({"entry": ""}, "", "no-sandbox", "pathless-identity-is-category-and-entry"),
    ({"category": "no-sandbox", "entry": "", "detail": "x"}, "", "no-sandbox",
     "pathless-identity-is-category-and-entry"),
    ({"category": "No_Sandbox", "entry": ""}, "", "no-sandbox",
     "pathless-identity-is-category-and-entry"),
    ({"category": "no-sandbox", "entry": "House"}, "", "no-sandbox",
     "pathless-identity-is-category-and-entry"),
    ({"target": "../old/brief.md"}, "", "broken-link",
     "pathless-identity-is-category-and-entry"),
    ({"id": "house-style.heading-case.0f1e2d3c4b5a6978"}, "notes/plan.md",
     "identity-collision", "collision-identity-is-the-collided-id"),
    ({"collided_id": "house-style.heading-case.0f1e2d3c4b5a6978", "count": "2"},
     "notes/plan.md", "identity-collision", "collision-identity-is-the-collided-id"),
    ({"collided_id": "not an id"}, "notes/plan.md", "identity-collision",
     "collision-identity-is-the-collided-id"),
    ({"category": "no-sandbox", "entry": ""}, "", "identity-collision",
     "collision-identity-is-the-collided-id"),
]


@pytest.mark.parametrize("identity, path, kind, rule", _REFUSED_IDENTITIES,
                         ids=[f"{case[3]}-{index}" for index, case
                              in enumerate(_REFUSED_IDENTITIES)])
def test_an_identity_outside_the_bound_is_never_serialized(
        identity: Any, path: str, kind: str, rule: str) -> None:
    """The other half of the falsifier: an identity that breaks the bound is
    refused by `make_finding()`, and a finding assembled by hand around it,
    with the right id, is refused by `to_json()`. So no serialization this
    module writes can carry it."""
    with pytest.raises(hc.FindingRefused) as refused:
        hc.make_finding(kind=kind, pack_id="opendox", pack_version="0.2.0", path=path,
                        identity=identity, severity="info", resolution_class="human-only",
                        message="a finding")
    assert refused.value.rule == rule, refused.value
    by_hand = {"id": _independent_id("opendox", kind, path, identity), "kind": kind,
               "pack_id": "opendox", "pack_version": "0.2.0", "path": path,
               "identity": identity, "severity": "info", "resolution_class": "human-only",
               "message": "a finding", "evidence": {}}
    with pytest.raises(hc.FindingRefused) as again:
        hc.to_json(by_hand)
    assert again.value.rule == rule, again.value
    assert rule in _rules(by_hand)


# ---------------------------------------------------------------------------
# 2. the vocabulary is the packaged copy's
# ---------------------------------------------------------------------------

def test_the_vocabulary_is_the_packaged_copys() -> None:
    """The module mirrors the digest-checked copy of T040's schema, constant
    for constant, and 14.6's three classes are spelled exactly."""
    schema = contracts.load(FINDING_COPY)
    props = schema["properties"]
    defs = schema["$defs"]
    assert hc.RESOLUTION_CLASSES == tuple(props["resolution_class"]["enum"]) == (
        "auto-fix", "assisted", "human-only")
    assert (hc.AUTO_FIX, hc.ASSISTED, hc.HUMAN_ONLY) == hc.RESOLUTION_CLASSES
    assert hc.SEVERITIES == tuple(props["severity"]["enum"]) == ("error", "warning", "info")
    assert hc.BASELINE_CLASSES == tuple(props["baseline_class"]["enum"]) == (
        "new", "pack-upgrade", "persistent")
    assert hc.REQUIRED_FIELDS == tuple(schema["required"])
    assert hc.REQUIRED_FIELDS + hc.OPTIONAL_FIELDS == tuple(
        field for field in props if field in schema["required"]) + tuple(
        field for field in props if field not in schema["required"])
    assert hc.FIELDS == tuple(props)
    assert set(hc.ENGINE_FIELDS) == {"id", "pack_id", "pack_version", "baseline_class"}
    for name in ("identity_key", "evidence_key"):
        assert tuple(defs[name]["allOf"][0]["not"]["enum"]) == hc.FORBIDDEN_KEYS == FORBIDDEN
        assert defs[name]["allOf"][1]["maxLength"] == hc.STRING_MAX == STRING_MAX
    assert defs["identity_value"]["allOf"][1]["maxLength"] == STRING_MAX
    assert defs["evidence_value"]["maxLength"] == STRING_MAX
    assert props["message"]["maxLength"] == STRING_MAX
    assert props["locator"]["properties"]["target"]["maxLength"] == STRING_MAX
    assert hc.OPENDOX == "opendox"
    assert hc.IDENTITY_COLLISION == "identity-collision"


def test_the_rule_catalog_is_the_copys_plus_the_engines_own() -> None:
    schema = contracts.load(FINDING_COPY)
    catalog = {rule["id"]: rule["class"] for rule in schema["x-rules"]}
    assert len(catalog) == 27
    assert set(hc.SHAPE_RULES) == {r for r, c in catalog.items() if c == "shape"}
    assert set(hc.REFERENCE_RULES) == {r for r, c in catalog.items() if c == "reference"} == {
        "id-is-the-hash-of-its-key", "id-names-its-pack-and-kind", "locator-span-is-ordered"}
    assert len(hc.SHAPE_RULES) == len(set(hc.SHAPE_RULES)) == 24
    assert set(hc.ENGINE_RULES) == {"name-is-at-most-40-characters",
                                    "identity-is-within-the-size-cap",
                                    "nesting-is-within-the-cap", "finding-is-json"}
    assert not set(hc.ENGINE_RULES) & set(catalog)


def test_the_id_rule_is_the_one_the_copys_header_spells() -> None:
    """The copy's header gives the canonical JSON in Python; the module's key
    is those bytes."""
    header = contracts.verified_bytes(FINDING_COPY).decode("utf-8").split("{\n", 1)[0]
    assert 'json.dumps(key, sort_keys=True, separators=(",", ":"),' in header
    assert 'ensure_ascii=False).encode("utf-8")' in header
    finding = _example("broken-link")
    key = {"identity": finding["identity"], "kind": finding["kind"],
           "pack_id": finding["pack_id"], "path": finding["path"]}
    assert hc.id_key(identity=finding["identity"], kind=finding["kind"],
                     pack_id=finding["pack_id"], path=finding["path"]) == json.dumps(
        key, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# 3. the id rule
# ---------------------------------------------------------------------------

def test_the_key_is_exactly_the_contracts() -> None:
    finding = _example("broken-link")
    key = hc.id_key(identity=finding["identity"], kind=finding["kind"],
                    pack_id=finding["pack_id"], path=finding["path"])
    assert key == (b'{"identity":{"target":"../old/brief.md"},"kind":"broken-link",'
                   b'"pack_id":"opendox","path":"notes/plan.md"}')
    assert hashlib.sha256(key).hexdigest()[:16] == "546cd2aacb1a6738"


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_every_example_id_is_the_id_the_module_computes(name: str) -> None:
    """openDox-spec's five examples, each id computed by its own test, are the
    ids this module computes, and each example breaks no rule here."""
    finding = _example(name)
    assert hc.finding_id(identity=finding["identity"], kind=finding["kind"],
                         pack_id=finding["pack_id"], path=finding["path"]) == finding["id"]
    assert hc.violations(finding) == []
    hc.check_finding(finding)


@pytest.mark.parametrize("field, value", [
    ("identity", {"target": "../old/brief-2.md"}),
    ("kind", "orphan"),
    ("pack_id", "house-style"),
    ("path", "notes/plan-2.md"),
])
def test_each_part_of_the_key_moves_the_id(field: str, value: Any) -> None:
    """A hash that ignored any one of the four parts would leave the id
    unmoved here."""
    finding = _example("broken-link")
    fields = {"identity": finding["identity"], "kind": finding["kind"],
              "pack_id": finding["pack_id"], "path": finding["path"]}
    moved = hc.finding_id(**{**fields, field: value})
    assert moved != finding["id"]
    assert moved.rsplit(".", 1)[1] != finding["id"].rsplit(".", 1)[1]
    assert moved == _independent_id(**{**fields, field: value})
    changed = {**finding, field: value}
    assert set(_rules(changed)) & {"id-is-the-hash-of-its-key", "id-names-its-pack-and-kind"}


@pytest.mark.parametrize("field, value", [
    ("locator", {"line_start": 40, "line_end": 41}),
    ("locator", None),
    ("severity", "error"),
    ("message", "another message"),
    ("evidence", {}),
    ("pack_version", "9.9.9"),
    ("baseline_class", "persistent"),
    ("resolution_class", "assisted"),
])
def test_nothing_outside_the_key_moves_the_id(field: str, value: Any) -> None:
    """An edit above a finding moves its locator and keeps its id, so an
    exception keyed by that id keeps suppressing it (N-13, ADV-07)."""
    fields = _fields(_example("broken-link"))
    if value is None:
        del fields[field]
    else:
        fields[field] = value
    assert hc.make_finding(**fields)["id"] == EXAMPLES["broken-link"]["id"]


def test_the_id_hashes_each_character_as_itself() -> None:
    """UTF-8, never a \\u escape: the pack-upgrade example's path holds a
    character outside ASCII."""
    finding = _example("pack-upgrade")
    assert not finding["path"].isascii()
    key = {"identity": finding["identity"], "kind": finding["kind"],
           "pack_id": finding["pack_id"], "path": finding["path"]}
    escaped = json.dumps(key, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert hc.finding_id(**key) == finding["id"]
    assert not finding["id"].endswith(hashlib.sha256(escaped.encode()).hexdigest()[:16])


def test_the_order_of_an_identitys_keys_does_not_move_the_id() -> None:
    one = {"b": "2", "a": {"d": "4", "c": "3"}}
    two = {"a": {"c": "3", "d": "4"}, "b": "2"}
    assert list(one) != list(two)
    ids = {hc.finding_id(identity=identity, kind="k", pack_id="p", path="x.md")
           for identity in (one, two)}
    assert len(ids) == 1


def test_a_pack_cannot_set_the_engines_fields() -> None:
    """The id, and nothing a family supplies, is the engine's: `make_finding()`
    takes no id."""
    fields = _fields(_example("broken-link"))
    with pytest.raises(TypeError):
        hc.make_finding(id="opendox.broken-link.0000000000000000", **fields)


def test_every_id_is_a_git_branch_name() -> None:
    """R2Q10 (a): `health-fix-<id>` is a branch name, and the longest id, two
    40-character names and the hash, is 98 characters."""
    git = shutil.which("git")
    assert git, "git is required here, as on CI"
    longest = hc.finding_id(identity={}, kind="k" * 40, pack_id="p" * 40, path="a.md")
    assert len(longest) == 98 == hc.ID_MAX
    ids = [finding["id"] for finding in EXAMPLES.values()] + [longest]
    for fid in ids:
        done = subprocess.run([git, "check-ref-format", "--branch", f"health-fix-{fid}"],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, (fid, done.stderr)


# ---------------------------------------------------------------------------
# 4. names of 1 to 40 characters
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", ["pack_id", "kind"])
def test_a_name_of_40_characters_is_admitted_and_41_is_refused(field: str) -> None:
    fields = _fields(_example("orphan"))
    forty, forty_one = "a-" * 20, "a-" * 20 + "b"
    assert (len(forty), len(forty_one)) == (40, 41)
    admitted = hc.make_finding(**{**fields, field: forty})
    assert admitted[field] == forty
    assert len(admitted["id"]) <= hc.ID_MAX
    with pytest.raises(hc.FindingRefused) as refused:
        hc.make_finding(**{**fields, field: forty_one})
    assert refused.value.rule == "name-is-at-most-40-characters"
    assert refused.value.where == f"/{field}"
    by_hand = {**fields, field: forty_one}
    by_hand["id"] = _independent_id(by_hand["pack_id"], by_hand["kind"], by_hand["path"],
                                    by_hand["identity"])
    assert set(_rules(by_hand)) == {"name-is-at-most-40-characters"}
    assert [v.where for v in hc.violations(by_hand)] == ["/id", f"/{field}"]


@pytest.mark.parametrize("field", ["pack_id", "kind"])
def test_the_schema_itself_admits_41_so_the_cap_is_the_engines(field: str) -> None:
    pattern = contracts.load(FINDING_COPY)["properties"][field]["pattern"]
    assert re.search(pattern, "a" * 41)
    assert re.search(pattern, "a" * 41 + "\n") is None


@pytest.mark.parametrize("field, rule", [("pack_id", "pack-id-is-a-name"),
                                         ("kind", "kind-is-a-family-name")])
@pytest.mark.parametrize("value", ["", "House", "house_style", "house.style", "h\u00e9",
                                   "house\n", 7, None])
def test_a_name_outside_the_alphabet_is_refused(field: str, rule: str, value: Any) -> None:
    finding = {**_example("orphan"), field: value}
    assert rule in _rules(finding)


def test_a_collision_naming_a_41_character_part_is_refused() -> None:
    assert hc.collision_identity("p" * 40 + "." + "k" * 40 + "." + "0" * 16)
    with pytest.raises(hc.FindingRefused) as refused:
        hc.collision_identity("p" * 41 + ".k." + "0" * 16)
    assert refused.value.rule == "name-is-at-most-40-characters"


# ---------------------------------------------------------------------------
# 5. the identity's serialized-size cap, and the nesting bound
# ---------------------------------------------------------------------------

def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _identity_of(size: int, char: str = "x") -> dict[str, str]:
    """An identity whose canonical JSON is exactly `size` bytes, every string
    in it at most 200 characters. Fillers of `char` close the gap until one
    last ASCII value can close it exactly; each filler leaves 20 bytes of
    margin, more than the next key costs, so the gap never goes negative."""
    identity: dict[str, str] = {}
    width = len(char.encode("utf-8"))
    for index in range(1000):
        key = f"k{index:03d}"
        gap = size - len(_canonical({**identity, key: ""}))
        assert gap >= 0, f"no identity of {size} bytes"
        if gap <= STRING_MAX:
            identity[key] = "x" * gap
            assert len(_canonical(identity)) == size
            return identity
        identity[key] = char * min(STRING_MAX, (gap - 20) // width)
    raise AssertionError(f"no identity of {size} bytes")


def test_the_cap_is_2048_bytes_of_canonical_utf8() -> None:
    assert hc.IDENTITY_MAX_BYTES == IDENTITY_MAX_BYTES


@pytest.mark.parametrize("char", ["x", "\u00e9", "\u20ac", "\U0001f50e"])
def test_the_identity_cap_admits_its_bound_and_refuses_one_byte_over(char: str) -> None:
    at = _identity_of(IDENTITY_MAX_BYTES, char)
    over = _identity_of(IDENTITY_MAX_BYTES + 1, char)
    assert len(_canonical(at)) == IDENTITY_MAX_BYTES
    assert len(_canonical(over)) == IDENTITY_MAX_BYTES + 1
    fields = _fields(_example("orphan"))
    admitted = hc.make_finding(**{**fields, "identity": at})
    assert len(hc.identity_json(admitted["identity"]).encode("utf-8")) == IDENTITY_MAX_BYTES
    with pytest.raises(hc.FindingRefused) as refused:
        hc.make_finding(**{**fields, "identity": over})
    assert (refused.value.rule, refused.value.where) == (
        "identity-is-within-the-size-cap", "/identity")
    with pytest.raises(hc.FindingRefused):
        hc.identity_json(over)
    with pytest.raises(hc.FindingRefused):
        hc.finding_id(identity=over, kind="orphan", pack_id="opendox", path="a.md")


def test_the_cap_is_stricter_than_the_schema() -> None:
    """An identity the schema admits (every string at most 200 characters, no
    number, no forbidden key) is refused by the cap alone."""
    over = _identity_of(IDENTITY_MAX_BYTES + 1)
    assert all(len(k) <= STRING_MAX and len(v) <= STRING_MAX for k, v in over.items())
    assert not set(over) & set(FORBIDDEN)
    finding = {**_example("orphan"), "identity": over}
    finding["id"] = _independent_id("opendox", "orphan", finding["path"], over)
    assert _rules(finding) == ["identity-is-within-the-size-cap"]


def test_the_plans_largest_identity_fits_in_every_utf8_width() -> None:
    """A pair of paths, each at the 200-character bound in four-byte
    characters, under two 40-character keys, fits the cap."""
    widest = {"a" * 40: "\U0001f50e" * 200, "b" * 40: "\U0001f50e" * 200}
    assert len(_canonical(widest)) < IDENTITY_MAX_BYTES
    hc.make_finding(**{**_fields(_example("orphan")), "identity": widest})


def _nested(levels: int, leaf: Any = "x") -> dict[str, Any]:
    """An object `levels` containers deep, counting itself: lists inside."""
    value: Any = leaf
    for _ in range(levels - 1):
        value = [value]
    return {"a": value}


@pytest.mark.parametrize("field", ["identity", "evidence"])
def test_the_nesting_bound_admits_its_bound_and_refuses_one_level_over(field: str) -> None:
    assert hc.NESTING_MAX == 16
    fields = _fields(_example("orphan"))
    hc.make_finding(**{**fields, field: _nested(16)})
    over = {**fields, field: _nested(17)}
    with pytest.raises(hc.FindingRefused) as refused:
        hc.make_finding(**over)
    assert refused.value.rule == "nesting-is-within-the-cap"


@pytest.mark.parametrize("field", ["identity", "evidence"])
def test_a_deep_value_is_refused_never_a_recursion_error(field: str) -> None:
    """A value nested past Python's recursion limit is judged, and refused,
    by the bound: the walk does not recurse, and nothing deep reaches
    `json.dumps`."""
    deep = _nested(sys.getrecursionlimit() * 5)
    finding = {**_example("orphan"), field: deep}
    assert "nesting-is-within-the-cap" in _rules(finding)
    with pytest.raises(hc.FindingRefused):
        hc.to_json(finding)
    fields = {**_fields(_example("orphan")), field: deep}
    with pytest.raises(hc.FindingRefused):
        hc.make_finding(**fields)


# ---------------------------------------------------------------------------
# 6. the bounds on message and evidence (R2Q25 (a); ADV-27)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message, admitted", [
    ("x" * 200, True),
    ("caf\u00e9 \u2713 \U0001f50e", True),
    ("x" * 201, False),
    ("", False),
    *[(f"a{c}b", False) for c in ("\n", "\r", "\t", "\x00", "\x1f", "\x7f", "\x85", "\x9f",
                                    "\u2028", "\u2029", "\ud800", "\udfff")],
    ("\u00a0 is admitted", True),
    (None, False),
    (["a line"], False),
])
def test_the_message_is_one_bounded_line(message: Any, admitted: bool) -> None:
    finding = {**_example("broken-link"), "message": message}
    rules = _rules(finding)
    assert rules == ([] if admitted else ["message-is-one-bounded-line"])


@pytest.mark.parametrize("evidence, where, rule", [
    ({}, None, None),
    ({"span": [3, 4], "ok": True, "none": None, "digest": "ab" * 32, "ratio": 0.5}, None, None),
    ({"a": "x" * 200}, None, None),
    ({"x" * 200: "a"}, None, None),
    ({"a": "\U0001f50e caf\u00e9"}, None, None),
    ({"count": 2, "paths": ["a.md", "b.md"]}, None, None),
    ({"a": "x" * 201}, "/evidence/a", "evidence-strings-are-short-text"),
    ({"a": {"b": ["x" * 201]}}, "/evidence/a/b/0", "evidence-strings-are-short-text"),
    ({"x" * 201: "a"}, "/evidence", "evidence-strings-are-short-text"),
    ({"a": {"x" * 201: 1}}, "/evidence/a", "evidence-strings-are-short-text"),
    ({"a": "\udc80"}, "/evidence/a", "evidence-strings-are-short-text"),
    *[({word: "a"}, "/evidence", "evidence-names-no-text") for word in FORBIDDEN],
    *[({"a": [{"b": {word: "c"}}]}, "/evidence/a/0/b", "evidence-names-no-text")
      for word in FORBIDDEN],
    ({"a/b": {"c~d": "x" * 201}}, "/evidence/a~1b/c~0d", "evidence-strings-are-short-text"),
    ("archive/brief.md", "/evidence", "evidence-is-an-object"),
    (["archive/brief.md"], "/evidence", "evidence-is-an-object"),
    ({"a": float("nan")}, "/evidence/a", "finding-is-json"),
    ({"a": float("inf")}, "/evidence/a", "finding-is-json"),
    ({"a": ("a", "b")}, "/evidence/a", "finding-is-json"),
    ({"a": b"bytes"}, "/evidence/a", "finding-is-json"),
    ({1: "a"}, "/evidence", "finding-is-json"),
    ({"a": 10 ** 5000}, "/evidence/a", "finding-is-json"),
])
def test_evidence_holds_locators_only(evidence: Any, where: str | None,
                                      rule: str | None) -> None:
    finding = {**_example("broken-link"), "evidence": evidence}
    found = hc.violations(finding)
    if rule is None:
        assert found == []
        assert json.loads(hc.to_json(finding))["evidence"] == evidence
    else:
        assert [(v.rule, v.where) for v in found] == [(rule, where)]


def test_evidence_is_an_empty_object_when_a_family_supplies_none() -> None:
    """14.5, FR-011: every emitted finding carries `evidence`."""
    fields = _fields(_example("orphan"))
    del fields["evidence"]
    finding = hc.make_finding(**fields)
    assert finding["evidence"] == {}
    assert json.loads(hc.to_json(finding))["evidence"] == {}
    assert "locator" not in finding


@pytest.mark.parametrize("identity, rule", [
    ({"a": float("nan")}, "identity-holds-no-number"),
    ({"a": ("b",)}, "finding-is-json"),
    ({1: "a"}, "finding-is-json"),
    ({"a": "\ud800"}, "identity-strings-are-short-text"),
    ({"\udfff": "a"}, "identity-strings-are-short-text"),
])
def test_an_identity_that_is_not_text_utf8_can_encode_is_refused(identity: Any,
                                                                  rule: str) -> None:
    with pytest.raises(hc.FindingRefused) as refused:
        hc.finding_id(identity=identity, kind="orphan", pack_id="opendox", path="a.md")
    assert refused.value.rule == rule


@pytest.mark.parametrize("locator, rules", [
    ({"line_start": 1, "line_end": 1}, []),
    ({"target": "../old/brief.md"}, []),
    ({"line_start": 3, "line_end": 9, "target": "x" * 200}, []),
    ({"line_start": 12.0, "line_end": 12}, []),
    ({}, ["locator-keys"]),
    ({"line_end": 12}, ["locator-keys"]),
    ({"line_start": 1, "line_end": 2, "column": 3}, ["locator-keys"]),
    ("12", ["locator-keys"]),
    ({"line_start": 0, "line_end": 1}, ["locator-line-is-a-line-number"]),
    ({"line_start": 1, "line_end": True}, ["locator-line-is-a-line-number"]),
    ({"line_start": 1.5, "line_end": 2}, ["locator-line-is-a-line-number"]),
    ({"line_start": "1", "line_end": 2}, ["locator-line-is-a-line-number"]),
    ({"line_start": float("nan"), "line_end": 2}, ["locator-line-is-a-line-number"]),
    ({"line_start": 5, "line_end": 4}, ["locator-span-is-ordered"]),
    ({"line_start": 0, "line_end": -1}, ["locator-line-is-a-line-number",
                                         "locator-line-is-a-line-number"]),
    ({"target": ""}, ["locator-target-is-short-text"]),
    ({"target": "x" * 201}, ["locator-target-is-short-text"]),
    ({"target": "\ud800"}, ["locator-target-is-short-text"]),
])
def test_the_locator_is_display_only_and_bounded(locator: Any, rules: list[str]) -> None:
    finding = {**_example("broken-link"), "locator": locator}
    assert _rules(finding) == rules


#: Integers JSON admits that Python's encoder cannot write: past the
#: integer-string conversion limit (4300 digits by default).
_UNWRITABLE = 10 ** 5000


@pytest.mark.parametrize("locator, rules", [
    ({"line_start": _UNWRITABLE, "line_end": _UNWRITABLE},
     ["finding-is-json", "finding-is-json"]),
    ({"line_start": 1, "line_end": _UNWRITABLE}, ["finding-is-json"]),
    # openDox-code#97, Codex r4223401860: a 401-digit line is writable, and an
    # out-of-order span of it is refused by its rule, never an OverflowError
    ({"line_start": 10 ** 400, "line_end": 1}, ["locator-span-is-ordered"]),
    ({"line_start": 1, "line_end": 10 ** 400}, []),
    ({"line_start": 1e308, "line_end": 1}, ["locator-span-is-ordered"]),
    ({"line_start": 1, "line_end": 1e308}, []),
], ids=["both unwritable", "line_end unwritable", "401 digits out of order",
        "401 digits in order", "1e308 out of order", "1e308 in order"])
def test_a_locator_of_any_size_is_judged_never_raised(locator: Any, rules: list[str]) -> None:
    """Copilot r4223399258 and Codex r4223401860 on openDox-code#97: a checked
    finding always serializes, and judging one never raises."""
    finding = {**_example("broken-link"), "locator": locator}
    assert _rules(finding) == rules
    if rules:
        with pytest.raises(hc.FindingRefused):
            hc.to_json(finding)
        fields = {**_fields(_example("broken-link")), "locator": locator}
        with pytest.raises(hc.FindingRefused):
            hc.make_finding(**fields)
    else:
        assert json.loads(hc.to_json(finding))["locator"] == locator


def test_evidence_of_any_size_is_judged_never_raised() -> None:
    finding = {**_example("broken-link"), "evidence": {"a": [_UNWRITABLE], "b": 10 ** 400}}
    assert [(v.rule, v.where) for v in hc.violations(finding)] == [
        ("finding-is-json", "/evidence/a/0")]
    with pytest.raises(hc.FindingRefused):
        hc.to_json(finding)
    finding["evidence"] = {"b": 10 ** 400}
    assert json.loads(hc.to_json(finding))["evidence"] == {"b": 10 ** 400}


@pytest.mark.parametrize("path, admitted", [
    ("notes/plan.md", True), ("", True), ("a/..b/c..", True), ("caf\u00e9.md", True),
    ("/etc/passwd", False), ("C:notes.md", False), ("c:/notes.md", False),
    ("notes\\plan.md", False), ("../plan.md", False), ("notes/../plan.md", False),
    ("notes/..", False), ("..", False), ("a\nb", False), ("a\x7fb", False),
    ("a\udc80b", False), (None, False), (3, False),
])
def test_the_path_is_corpus_relative(path: Any, admitted: bool) -> None:
    finding = _example("orphan")
    finding["path"] = path
    if path == "":
        finding["identity"] = {"category": "x", "entry": ""}
    rules = [r for r in _rules(finding) if r != "id-is-the-hash-of-its-key"]
    assert rules == ([] if admitted else ["path-is-corpus-relative"])


@pytest.mark.parametrize("version, admitted", [
    ("0.2.0", True), ("1.4.0+local build", True), ("", False), ("1\n", False),
    ("1\x85", False), ("1\ud800", False), (1, False)])
def test_the_pack_version_is_text(version: Any, admitted: bool) -> None:
    finding = {**_example("broken-link"), "pack_version": version}
    assert _rules(finding) == ([] if admitted else ["pack-version-is-text"])


@pytest.mark.parametrize("field, value, rule", [
    ("severity", "critical", "severity-is-known"),
    ("severity", None, "severity-is-known"),
    ("resolution_class", "auto_fix", "resolution-class-is-one-of-three"),
    ("resolution_class", "Auto-Fix", "resolution-class-is-one-of-three"),
    ("resolution_class", ["auto-fix"], "resolution-class-is-one-of-three"),
    ("baseline_class", "gone", "baseline-class-is-known"),
    ("baseline_class", None, "baseline-class-is-known"),
])
def test_the_closed_values_are_closed(field: str, value: Any, rule: str) -> None:
    finding = {**_example("broken-link"), field: value}
    assert _rules(finding) == [rule]


# ---------------------------------------------------------------------------
# 7. every rule the copy catalogues is enforced, and the engine's own
# ---------------------------------------------------------------------------

def _with(name: str, **changes: Any) -> dict[str, Any]:
    finding = _example(name)
    for key, value in changes.items():
        if value is _DROP:
            del finding[key]
        else:
            finding[key] = value
    return finding


_DROP = object()

#: openDox-spec's negative example for each catalogued rule, rebuilt as the
#: positive example it names with its one change, then the engine's own.
NEGATIVES: dict[str, dict[str, Any]] = {
    "finding-keys": _with("broken-link", patch="--- a/notes/plan.md\n+++ b/notes/plan.md\n"),
    "id-is-well-formed": _with("broken-link", id="opendox.broken-link.546CD2AACB1A6738"),
    "kind-is-a-family-name": _with("broken-link", kind="Broken_Link"),
    "pack-id-is-a-name": _with("broken-link", pack_id="house_style"),
    "pack-version-is-text": _with("broken-link", pack_version=""),
    "path-is-corpus-relative": _with("broken-link", path="../outside/plan.md"),
    "identity-is-an-object": _with("broken-link", identity=["../old/brief.md"]),
    "identity-holds-no-number": _with("broken-link",
                                      identity={"target": "../old/brief.md", "line": 12}),
    "identity-strings-are-short-text": _with("broken-link", identity={"target": PASSAGE}),
    "identity-names-no-text": _with("broken-link", identity={"target": "../old/brief.md",
                                                            "text": "see the old brief"}),
    "locator-keys": _with("broken-link", locator={"line_start": 12}),
    "locator-line-is-a-line-number": _with("broken-link",
                                           locator={"line_start": 0, "line_end": 12}),
    "locator-target-is-short-text": _with("broken-link", locator={
        "line_start": 12, "line_end": 12, "target": PASSAGE}),
    "severity-is-known": _with("broken-link", severity="critical"),
    "resolution-class-is-one-of-three": _with("broken-link", resolution_class="auto_fix"),
    "message-is-one-bounded-line": _with("broken-link", message=(
        "link target does not exist;\na unique file of that name exists elsewhere")),
    "evidence-is-an-object": _with("broken-link", evidence="archive/brief.md"),
    "evidence-strings-are-short-text": _with("broken-link", evidence={
        "candidate": "archive/brief.md", "family_version": "1", "context": PASSAGE}),
    "evidence-names-no-text": _with("broken-link", evidence={
        "candidate": "archive/brief.md", "family_version": "1",
        "excerpt": "see the old brief"}),
    "baseline-class-is-known": _with("broken-link", baseline_class="unclassed"),
    "pathless-finding-is-human-only": _with("no-sandbox", resolution_class="assisted"),
    "pathless-identity-is-category-and-entry": _with("no-sandbox", identity={}),
    "identity-collision-is-human-only": _with("identity-collision",
                                              resolution_class="assisted"),
    "collision-identity-is-the-collided-id": _with("identity-collision", identity={
        "id": "house-style.heading-case.0f1e2d3c4b5a6978"}),
    "id-names-its-pack-and-kind": _with("broken-link",
                                        id="house-style.broken-link.546cd2aacb1a6738"),
    "id-is-the-hash-of-its-key": _with("broken-link",
                                       identity={"target": "../old/brief-2.md"}),
    "locator-span-is-ordered": _with("broken-link",
                                     locator={"line_start": 14, "line_end": 12}),
    # the engine's own
    # a 41-character kind under the orphan's own id: the id is well formed,
    # and the reference rules judge no part their own rules refuse
    "name-is-at-most-40-characters": _with("orphan", kind="o" * 41),
    "identity-is-within-the-size-cap": _with(
        "orphan", identity=_identity_of(IDENTITY_MAX_BYTES + 1),
        id=_independent_id("opendox", "orphan", "notes/appendix.md",
                           _identity_of(IDENTITY_MAX_BYTES + 1))),
    "nesting-is-within-the-cap": _with("orphan", evidence=_nested(17)),
    "finding-is-json": _with("orphan", evidence={"a": ("b",)}),
}


def test_every_catalogued_rule_and_every_engine_rule_has_a_negative() -> None:
    assert set(NEGATIVES) == set(hc.SHAPE_RULES) | set(hc.REFERENCE_RULES) | set(
        hc.ENGINE_RULES)


@pytest.mark.parametrize("rule", sorted(NEGATIVES))
def test_each_negative_breaks_its_rule_and_no_other(rule: str) -> None:
    finding = NEGATIVES[rule]
    assert _rules(finding) == [rule], hc.violations(finding)
    with pytest.raises(hc.FindingRefused) as refused:
        hc.check_finding(finding)
    assert refused.value.rule == rule
    assert refused.value.violation == hc.violations(finding)[0]


@pytest.mark.parametrize("missing", hc.REQUIRED_FIELDS)
def test_a_finding_without_a_required_field_is_refused(missing: str) -> None:
    finding = _with("broken-link", **{missing: _DROP})
    assert "finding-keys" in _rules(finding)


@pytest.mark.parametrize("finding", [[], "a finding", None, 3])
def test_a_finding_that_is_not_an_object_is_refused(finding: Any) -> None:
    assert [(v.rule, v.where) for v in hc.violations(finding)] == [("finding-keys", "")]


def test_a_pathless_finding_breaks_the_human_only_rule_only_over_a_known_class() -> None:
    """A class outside the three is that rule's refusal, and not also the
    pathless rule's: one cause, one violation."""
    assert _rules(_with("no-sandbox", resolution_class="later")) == [
        "resolution-class-is-one-of-three"]
    assert _rules(_with("identity-collision", resolution_class="later")) == [
        "resolution-class-is-one-of-three"]


@pytest.mark.parametrize("fid", [
    "house-style.broken-link.546cd2aacb1a6738",
    "opendox.orphan.546cd2aacb1a6738",
    "house-style.orphan.546cd2aacb1a6738",
], ids=["another pack", "another kind", "both"])
def test_the_id_names_the_findings_own_pack_and_its_own_kind(fid: str) -> None:
    """Each of the id's two names is judged: its hash is still the hash of
    the finding's own key, so this rule alone is broken."""
    assert _rules(_with("broken-link", id=fid)) == ["id-names-its-pack-and-kind"]


def test_the_reference_rules_judge_only_admitted_parts() -> None:
    """A malformed part is reported once, by its own rule: the hash is not
    judged over a key it could not be computed from, as in openDox-spec's own
    test."""
    assert _rules(_with("broken-link", kind="Broken_Link")) == ["kind-is-a-family-name"]
    assert _rules(_with("no-sandbox", identity={})) == [
        "pathless-identity-is-category-and-entry"]
    assert _rules(_with("broken-link", identity={"target": "\ud800"})) == [
        "identity-strings-are-short-text"]


def test_a_pathless_collision_keeps_the_collisions_identity() -> None:
    finding = hc.make_finding(
        kind="identity-collision", pack_id="opendox", pack_version="0.2.0", path="",
        identity=hc.collision_identity("opendox.no-sandbox.5ccbb79891acb2e8"),
        severity="error", resolution_class="human-only", message="m")
    assert hc.violations(finding) == []
    assert _rules({**finding, "resolution_class": "assisted"}) == [
        "pathless-finding-is-human-only", "identity-collision-is-human-only"]


# ---------------------------------------------------------------------------
# 8. the engine's own identities and categories; the examples rebuilt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_make_finding_rebuilds_each_example_id_and_all(name: str) -> None:
    """The engine's door: given a family's or pack's fields and the engine's
    pack_id and pack_version, `make_finding()` stamps the example's own id
    and writes nothing else."""
    example = _example(name)
    built = hc.make_finding(**_fields(example))
    assert built == example
    assert list(built) == [field for field in hc.FIELDS if field in example]
    assert json.loads(hc.to_json(built)) == example


def test_make_finding_returns_its_own_copy() -> None:
    fields = _fields(_example("broken-link"))
    built = hc.make_finding(**fields)
    fields["identity"]["target"] = "elsewhere"
    fields["evidence"]["candidate"] = "elsewhere"
    fields["locator"]["line_start"] = 99
    assert built == EXAMPLES["broken-link"]


def test_to_json_is_the_canonical_serialization() -> None:
    built = hc.make_finding(**_fields(_example("pack-upgrade")))
    text = hc.to_json(built)
    assert text == json.dumps(built, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
    assert "caf\u00e9" in text


def test_the_categories_are_names_and_the_copys_example_is_one() -> None:
    assert "no-sandbox" in hc.CATEGORIES
    assert len(set(hc.CATEGORIES)) == len(hc.CATEGORIES)
    for category in hc.CATEGORIES:
        assert re.fullmatch(r"[a-z0-9-]{1,40}", category), category


@pytest.mark.parametrize("category", hc.CATEGORIES)
def test_each_category_makes_a_pathless_finding_with_one_id_across_runs(
        category: str) -> None:
    def build() -> dict[str, Any]:
        return hc.make_finding(
            kind=category, pack_id="opendox", pack_version="0.2.0", path="",
            identity=hc.pathless_identity(category, "house-style"), severity="warning",
            resolution_class="human-only", message="the pack did not run")
    first, second = build(), build()
    assert first["id"] == second["id"]
    assert first["identity"] == {"category": category, "entry": "house-style"}


@pytest.mark.parametrize("category, entry", [
    ("not-a-category", ""), ("No-Sandbox", ""), ("", ""), (None, ""),
    ("no-sandbox", "House"), ("no-sandbox", "a" * 201), ("no-sandbox", None)])
def test_the_pathless_identity_refuses_what_is_not_the_engines(category: Any,
                                                                 entry: Any) -> None:
    with pytest.raises(hc.FindingRefused) as refused:
        hc.pathless_identity(category, entry)
    assert refused.value.rule == "pathless-identity-is-category-and-entry"


@pytest.mark.parametrize("value", ["", "opendox.broken-link", "opendox.broken-link.XYZ",
                                   "opendox.broken-link.546cd2aacb1a673",
                                   "opendox.broken-link.546cd2aacb1a6738\n", None])
def test_a_collision_names_a_well_formed_id(value: Any) -> None:
    with pytest.raises(hc.FindingRefused) as refused:
        hc.collision_identity(value)
    assert refused.value.rule == "collision-identity-is-the-collided-id"


def test_the_engines_identities_are_their_keys() -> None:
    fid = "opendox.broken-link.546cd2aacb1a6738"
    assert hc.collision_identity(fid) == {"collided_id": fid}
    assert hc.pathless_identity("no-sandbox") == {"category": "no-sandbox", "entry": ""}


# ---------------------------------------------------------------------------
# 9. the closure: the standard library, and nothing else
# ---------------------------------------------------------------------------

def test_the_module_names_only_the_standard_library() -> None:
    """Read from the source: every import is the standard library's, and none
    is relative or of openDox (R2Q18 (a); N-3)."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import"
            names.append(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("__import__", "exec", "eval"), node.func.id
    assert names
    assert sorted({n for n in names if n.split(".")[0] not in sys.stdlib_module_names
                   and n != "__future__"}) == []


#: openXdox, and openxFactory's packages, blocked at the finder.
_BLOCKED = ("openxdox", "doc_health", "ideation_dashboard",
            "corpus_adapter_openxfactory", "scripts", "yaml")

_IMPORT_WEIGHT = """
import json, sys
for name in {blocked!r}:
    sys.modules[name] = None
before = set(sys.modules)
import opendox.health_contract
added = set(sys.modules) - before
print(json.dumps({{
    "foreign": sorted(m for m in added
                      if m.split(".")[0] not in sys.stdlib_module_names
                      and m.split(".")[0] != "opendox"),
    "own": sorted(m for m in added if m.split(".")[0] == "opendox"),
}}))
"""


def test_the_module_loads_the_standard_library_and_nothing_else_of_opendox() -> None:
    env = {**os.environ,
           "PYTHONPATH": os.pathsep.join([str(SRC), os.environ.get("PYTHONPATH", "")])}
    done = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(_IMPORT_WEIGHT.format(blocked=_BLOCKED))],
        capture_output=True, text=True, cwd=str(SRC), env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout.strip().splitlines()[-1])
    assert found == {"foreign": [], "own": ["opendox", "opendox.health_contract"]}, found


_ALONE = """
import json, sys
sys.path.insert(0, {root!r})
import opendox.health_contract as hc
finding = hc.make_finding(kind="broken-link", pack_id="opendox", pack_version="0.2.0",
                          path="notes/plan.md", identity={{"target": "../old/brief.md"}},
                          locator={{"line_start": 12, "line_end": 12}}, severity="warning",
                          resolution_class="auto-fix", message="m", evidence={{}})
print(json.dumps({{
    "json": hc.to_json(finding),
    "site": "site" in sys.modules,
    "paths": [p for p in sys.path if "site-packages" in p or "dist-packages" in p],
    "file": hc.__file__,
}}))
"""


def test_the_module_runs_alone_with_no_site_packages(tmp_path: Path) -> None:
    """What the sandbox binds (R2Q18 (a)): the interpreter, its standard
    library and this one module. It is copied into a directory that holds it
    and an empty package marker, and run under `-I -S`."""
    package = tmp_path / "opendox"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copyfile(MODULE, package / "health_contract.py")
    assert sorted(p.name for p in package.iterdir()) == ["__init__.py", "health_contract.py"]
    done = subprocess.run(
        [sys.executable, "-I", "-S", "-c", textwrap.dedent(_ALONE.format(root=str(tmp_path)))],
        capture_output=True, text=True, cwd=str(tmp_path), timeout=120,
        env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"})
    assert done.returncode == 0, done.stderr
    found = json.loads(done.stdout.strip().splitlines()[-1])
    assert found["site"] is False
    assert found["paths"] == []
    assert Path(found["file"]).parent == package
    here = hc.make_finding(kind="broken-link", pack_id="opendox", pack_version="0.2.0",
                           path="notes/plan.md", identity={"target": "../old/brief.md"},
                           locator={"line_start": 12, "line_end": 12}, severity="warning",
                           resolution_class="auto-fix", message="m", evidence={})
    assert found["json"] == hc.to_json(here)
    assert json.loads(found["json"])["id"] == EXAMPLES["broken-link"]["id"]


# ---------------------------------------------------------------------------
# 10. a refusal quotes nothing of the finding
# ---------------------------------------------------------------------------

_SECRET = "SECRET-PASSAGE-" + "q" * 300


@pytest.mark.parametrize("change", [
    {"identity": {"target": _SECRET}},
    {"identity": {_SECRET: "a"}},
    {"identity": {"a": [_SECRET]}},
    {"evidence": {"a": _SECRET}},
    {"evidence": {_SECRET: "a"}},
    {"message": _SECRET},
    {"locator": {"target": _SECRET}},
    {"pack_version": _SECRET + "\n"},
    {"path": "../" + _SECRET},
    {"kind": _SECRET},
    {_SECRET: "an unknown field"},
])
def test_a_refusal_quotes_nothing_of_the_finding(change: dict[str, Any]) -> None:
    finding = {**_example("broken-link"), **change}
    found = hc.violations(finding)
    assert found
    for violation in found:
        assert "SECRET" not in violation.line(), violation
    with pytest.raises(hc.FindingRefused) as refused:
        hc.check_finding(finding)
    assert "SECRET" not in str(refused.value)


def test_a_violation_reads_as_its_rule_its_place_and_its_detail() -> None:
    violation = hc.violations(NEGATIVES["locator-span-is-ordered"])[0]
    assert violation.rule == "locator-span-is-ordered"
    assert violation.where == "/locator/line_end"
    assert violation.line() == f"[locator-span-is-ordered] /locator/line_end: {violation.detail}"
    # it names no value of the finding, the lines included
    assert "12" not in violation.detail
    assert "14" not in violation.detail
    refused = hc.FindingRefused(violation)
    assert isinstance(refused, ValueError)
    assert (refused.rule, refused.where) == (violation.rule, violation.where)
    assert violation.line() in str(refused)


def test_no_number_check_admits_booleans_and_refuses_every_number() -> None:
    """`True` is an `int` in Python and a boolean in JSON: the identity admits
    it and refuses `1`."""
    assert isinstance(True, int)
    hc.finding_id(identity={"a": True, "b": False}, kind="k", pack_id="p", path="a.md")
    for number in (1, 0, -1, 1.0, 0.5, math.pi, 10 ** 30):
        with pytest.raises(hc.FindingRefused) as refused:
            hc.finding_id(identity={"a": number}, kind="k", pack_id="p", path="a.md")
        assert refused.value.rule == "identity-holds-no-number"
