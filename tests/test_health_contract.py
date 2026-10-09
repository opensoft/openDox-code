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
   that rule and no other; so are the module's five engine rules.
8. THE ENGINE'S OWN FINDINGS (the holder's `6069024023`): the eleven ruled
   categories, each one finding per category and entry with one id across
   runs and the `pack_id` its category takes (`engine_finding()`; `6072086385`
   item 1); the disappearance re-raise in both forms, option (D); and
   openDox-spec's five examples rebuilt through `make_finding()` and
   `engine_finding()`, id included.
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
import datetime
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
    "a refused manifest, the whole file": (
        "", "manifest-refused", hc.pathless_identity("manifest-refused"), "human-only"),
    "a refused dispositions file": (
        "", "dispositions-refused", hc.pathless_identity("dispositions-refused"), "human-only"),
    "the disappearance of a pathed finding": (
        "notes/plan.md", "uncited-disappearance",
        hc.disappearance_identity(EXAMPLES["broken-link"]), "human-only"),
    "the disappearance of a pathless finding": (
        "", "uncited-disappearance",
        hc.disappearance_identity(EXAMPLES["no-sandbox"]), "human-only"),
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
    # the holder's 6072197564: (b) a closed set of categories; (e) one
    # install-level finding per run, so its entry is ""
    ({"category": "orphan", "entry": ""}, "", "no-sandbox",
     "pathless-identity-is-category-and-entry"),
    ({"category": "no-sandbox", "entry": "house-style"}, "", "no-sandbox",
     "pathless-identity-is-category-and-entry"),
    ({"target": "../old/brief.md"}, "", "broken-link",
     "pathless-identity-is-category-and-entry"),
    ({"id": "house-style.heading-case.0f1e2d3c4b5a6978"}, "notes/plan.md",
     "identity-collision", "collision-identity-is-the-collided-id"),
    ({"collided_id": "house-style.heading-case.0f1e2d3c4b5a6978", "count": "2"},
     "notes/plan.md", "identity-collision", "collision-identity-is-the-collided-id"),
    ({"collided_id": "not an id"}, "notes/plan.md", "identity-collision",
     "collision-identity-is-the-collided-id"),
    # U+0000, which jsonb cannot store (the holder's 6072086385 item 4)
    ({"target": "../old/brief\x00.md"}, "notes/plan.md", "broken-link", "text-holds-no-nul"),
    ({"tar\x00get": "../old/brief.md"}, "notes/plan.md", "broken-link", "text-holds-no-nul"),
    ({"a": ["b", "\x00"]}, "notes/plan.md", "broken-link", "text-holds-no-nul"),
    ({"a": {"\x00": "b"}}, "notes/plan.md", "broken-link", "text-holds-no-nul"),
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
    assert hc.RESOLUTION_CLASSES == (hc.AUTO_FIX, hc.ASSISTED, hc.HUMAN_ONLY)
    assert hc.SEVERITIES == tuple(props["severity"]["enum"]) == ("error", "warning", "info")
    assert hc.BASELINE_CLASSES == tuple(props["baseline_class"]["enum"]) == (
        "new", "pack-upgrade", "persistent")
    assert hc.REQUIRED_FIELDS == tuple(schema["required"])
    assert hc.REQUIRED_FIELDS + hc.OPTIONAL_FIELDS == tuple(
        field for field in props if field in schema["required"]) + tuple(
        field for field in props if field not in schema["required"])
    assert hc.FIELDS == tuple(props)
    # the holder's 6072197564 (d): a pack's id is ignored; the rest are the engine's
    assert hc.IGNORED_FIELDS == ("id",)
    assert hc.STAMPED_FIELDS == ("pack_id", "pack_version", "baseline_class")
    assert set(hc.IGNORED_FIELDS + hc.STAMPED_FIELDS) < set(hc.FIELDS)
    for name in ("identity_key", "evidence_key"):
        assert tuple(defs[name]["allOf"][0]["not"]["enum"]) == hc.FORBIDDEN_KEYS == FORBIDDEN
        assert defs[name]["allOf"][1]["maxLength"] == hc.STRING_MAX == STRING_MAX
    assert defs["identity_value"]["allOf"][1]["maxLength"] == STRING_MAX
    assert defs["evidence_value"]["maxLength"] == STRING_MAX
    assert props["message"]["maxLength"] == STRING_MAX
    assert props["locator"]["properties"]["target"]["maxLength"] == STRING_MAX
    assert hc.OPENDOX == "opendox"
    assert hc.IDENTITY_COLLISION == "identity-collision"
    assert hc.UNCITED_DISAPPEARANCE == "uncited-disappearance"


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
                                    "nesting-is-within-the-cap", "finding-is-json",
                                    "text-holds-no-nul"}
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


def test_finding_id_is_the_one_hash_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The module-level `finding_id()` is the SINGLE hash path (the holder's
    `6069507373`, T046 item 2): a test that patches it patches both the id
    `make_finding()` sets and the id the reference rule checks."""
    real = hc.finding_id
    seen: list[dict[str, Any]] = []

    def patched(**key: Any) -> str:
        seen.append(key)
        return real(**key)[:-16] + "0" * 16

    monkeypatch.setattr(hc, "finding_id", patched)
    built = hc.make_finding(**_fields(_example("broken-link")))
    assert built["id"] == "opendox.broken-link.0000000000000000"
    assert len(seen) == 2, "the id it set, and the id its own check recomputed"
    assert hc.violations(built) == []
    assert _rules(_example("broken-link")) == ["id-is-the-hash-of-its-key"]
    assert len(seen) == 4


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
    ({"a": "b\x00"}, "/evidence/a", "text-holds-no-nul"),
    ({"a\x00": "b"}, "/evidence", "text-holds-no-nul"),
    ({"a": [{"b": "\x00"}]}, "/evidence/a/0/b", "text-holds-no-nul"),
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


@pytest.mark.parametrize("field, value, rule, where", [
    ("identity", {"target": "../old/brief.md\x00"}, "text-holds-no-nul", "/identity/target"),
    ("identity", {"tar\x00get": "../old/brief.md"}, "text-holds-no-nul", "/identity"),
    ("identity", {"a": [{"b": "\x00"}]}, "text-holds-no-nul", "/identity/a/0/b"),
    ("identity", {"k" * 189: {"x": "\x00"}}, "text-holds-no-nul", "/identity/" + "k" * 189),
    ("evidence", {"a": "\x00"}, "text-holds-no-nul", "/evidence/a"),
    ("evidence", {"\x00": "a"}, "text-holds-no-nul", "/evidence"),
    ("locator", {"target": "\x00"}, "text-holds-no-nul", "/locator/target"),
    ("message", "a\x00b", "message-is-one-bounded-line", "/message"),
    ("path", "notes/pl\x00an.md", "path-is-corpus-relative", "/path"),
    ("pack_version", "0.2.0\x00", "pack-version-is-text", "/pack_version"),
], ids=["identity value", "identity key", "identity, deep", "identity, past the bound",
        "evidence value", "evidence key", "locator target", "message", "path",
        "pack_version"])
def test_u0000_is_refused_in_every_string_a_finding_carries(field: str, value: Any,
                                                            rule: str, where: str) -> None:
    """The holder's `6072086385` item 4: Postgres `jsonb` cannot store U+0000
    (SQLSTATE 22P05), so no string a finding carries holds it, keys and values
    alike. The schema admits it in `identity`, `evidence` and `locator.target`,
    where the engine's rule refuses it; in `message`, `path` and
    `pack_version`, the schema's own rules do. Each refusal is a
    `FindingRefused` with a bounded `where`, never a raw error, and quotes
    nothing it refused."""
    finding = {**_example("broken-link"), field: value}
    assert [(v.rule, v.where) for v in hc.violations(finding)] == [(rule, where)]
    assert len(where) <= STRING_MAX
    with pytest.raises(hc.FindingRefused) as refused:
        hc.check_finding(finding)
    assert refused.value.rule == rule
    assert refused.value.where == where
    assert "\x00" not in str(refused.value)
    with pytest.raises(hc.FindingRefused):
        hc.to_json(finding)
    fields = {**_fields(_example("broken-link")), field: value}
    with pytest.raises(hc.FindingRefused) as made:
        hc.make_finding(**fields)
    assert made.value.rule == rule


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
    ({"target": "../old/\x00brief.md"}, ["text-holds-no-nul"]),
    ({"line_start": 1, "line_end": 1, "target": "\x00"}, ["text-holds-no-nul"]),
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
    # lane 3's REVIEW-W1 MAJOR probe: a reversed span of 401-digit integers
    ({"line_start": 10 ** 400, "line_end": 10 ** 399}, ["locator-span-is-ordered"]),
    ({"line_start": 1, "line_end": 10 ** 400}, []),
    ({"line_start": 1e308, "line_end": 1}, ["locator-span-is-ordered"]),
    ({"line_start": 1, "line_end": 1e308}, []),
], ids=["both unwritable", "line_end unwritable", "401 digits out of order",
        "lane 3's reversed 401-digit span", "401 digits in order", "1e308 out of order",
        "1e308 in order"])
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
    ("a\udc80b", False), ("a\x00b", False), (None, False), (3, False),
])
def test_the_path_is_corpus_relative(path: Any, admitted: bool) -> None:
    finding = _example("orphan")
    finding["path"] = path
    if path == "":
        finding["identity"] = {"category": "no-sandbox", "entry": ""}
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
    "text-holds-no-nul": _with("orphan", evidence={"a": "b\x00c"}),
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


def test_a_field_name_that_is_not_text_is_refused() -> None:
    """Lane 3's REVIEW-W1 MINOR: with this refusal gone, the finding was
    admitted and `to_json()` raised `TypeError`."""
    finding = {**_example("broken-link"), 1: "x"}
    assert [(v.rule, v.where) for v in hc.violations(finding)] == [("finding-is-json", "")]
    with pytest.raises(hc.FindingRefused):
        hc.to_json(finding)


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


#: The categories as the holder ruled them (`6069024023` item 1): the nine
#: T041 drafted, accepted as written, and the two added.
RULED_CATEGORIES = ("no-sandbox", "entry-refused", "fetch-failed", "digest-mismatch",
                    "declaration-refused", "pack-crashed", "pack-timed-out",
                    "pack-bound-hit", "pack-output-refused", "manifest-refused",
                    "dispositions-refused")

#: The categories whose finding is against the product itself; the rest are
#: against the pack their manifest entry launched.
AGAINST_OPENDOX = {"no-sandbox", "entry-refused", "manifest-refused", "dispositions-refused"}

#: The install-level categories: a run raises ONE such finding, so its entry
#: is "" (the holder's `6072197564` (e); data-model.md:382).
INSTALL_LEVEL = {"no-sandbox", "manifest-refused", "dispositions-refused"}

#: The categories against the pack a valid manifest entry launched, whose
#: entry is that pack's id, never "" (`6072086385` item 1).
AGAINST_A_PACK = set(RULED_CATEGORIES) - AGAINST_OPENDOX


def test_the_categories_are_the_ruled_ones_and_names() -> None:
    assert hc.CATEGORIES == RULED_CATEGORIES
    assert "no-sandbox" in hc.CATEGORIES  # openDox-spec's own released example
    for category in hc.CATEGORIES:
        assert re.fullmatch(r"[a-z0-9-]{1,40}", category), category
    assert set(hc.CATEGORIES) - hc.ENTRY_CATEGORIES == AGAINST_OPENDOX
    assert hc.ENTRY_CATEGORIES < set(hc.CATEGORIES)
    assert hc.ENGINE_KINDS == set(RULED_CATEGORIES) | {"identity-collision",
                                                      "uncited-disappearance",
                                                      "refused-patch"}
    assert hc.INSTALL_CATEGORIES == INSTALL_LEVEL
    assert hc.PATHLESS_CATEGORIES == set(RULED_CATEGORIES) | {"identity-collision"}


@pytest.mark.parametrize("category", [c for c in RULED_CATEGORIES if c not in INSTALL_LEVEL])
def test_each_category_makes_one_engine_finding_per_entry_with_one_id(category: str) -> None:
    """A category is its finding's kind, the path is empty, it is human-only,
    its `pack_id` is the one its category takes (`6072086385` item 1), and one
    id per category and entry across runs (the holder's `6069024023` item 1)."""
    entry = "house-style"

    def build(entry: str = entry, message: str = "the pack did not run") -> dict[str, Any]:
        return hc.engine_finding(category, entry, pack_version="1.4.0", severity="warning",
                                 message=message, evidence={"reasons": ["one", "two"]})

    first = build()
    assert first["id"] == build(message="another run, other words")["id"]
    assert first["id"] != build(entry="other-pack")["id"]
    assert (first["kind"], first["path"], first["resolution_class"]) == (
        category, "", "human-only")
    assert first["identity"] == {"category": category, "entry": entry}
    assert first["pack_id"] == ("opendox" if category in AGAINST_OPENDOX else entry)
    assert first["evidence"] == {"reasons": ["one", "two"]}
    assert hc.violations(first) == []


@pytest.mark.parametrize("category", sorted(AGAINST_OPENDOX))
def test_a_finding_against_the_product_may_name_no_entry(category: str) -> None:
    built = hc.engine_finding(category, pack_version="0.2.0", severity="warning",
                              message="the run could not use it")
    assert (built["pack_id"], built["identity"]) == ("opendox", {"category": category,
                                                                 "entry": ""})


@pytest.mark.parametrize("entry", ["", "opendox"])
@pytest.mark.parametrize("category", sorted(set(RULED_CATEGORIES) - AGAINST_OPENDOX))
def test_a_finding_against_a_pack_names_that_packs_entry(category: str, entry: str) -> None:
    with pytest.raises(hc.FindingRefused) as refused:
        hc.engine_finding(category, entry, pack_version="0.2.0", severity="warning",
                          message="the pack did not run")
    assert refused.value.rule == "pathless-identity-is-category-and-entry"


@pytest.mark.parametrize("category", sorted(INSTALL_LEVEL))
def test_an_install_level_finding_takes_no_entry(category: str) -> None:
    """Lane 3's REVIEW-W1 MINOR at `f9cc4b0c` (`health_contract.py:865`) and the
    holder's `6072197564` (e): a run raises ONE install-level finding, never one
    per entry (data-model.md:382), so its entry is "", and a non-empty one is
    refused by `engine_finding()`, `pathless_identity()` and `check_finding()`
    alike. Otherwise one whole-file refusal could split per entry."""
    with pytest.raises(hc.FindingRefused) as refused:
        hc.engine_finding(category, "house-style", pack_version="0.2.0", severity="warning",
                          message="the run could not use it")
    assert refused.value.rule == "pathless-identity-is-category-and-entry"
    assert refused.value.where == "/identity/entry"
    with pytest.raises(hc.FindingRefused) as built:
        hc.pathless_identity(category, "house-style")
    assert built.value.where == "/identity/entry"
    identity = {"category": category, "entry": "house-style"}
    finding = {**_example("no-sandbox"), "kind": category, "identity": identity,
               "id": _independent_id("opendox", category, "", identity)}
    assert [(v.rule, v.where) for v in hc.violations(finding)] == [
        ("pathless-identity-is-category-and-entry", "/identity/entry")]


@pytest.mark.parametrize("category, admitted", [
    *[(category, True) for category in RULED_CATEGORIES],
    ("identity-collision", True),
    ("uncited-disappearance", False), ("broken-link", False), ("orphan", False),
])
def test_a_pathless_identity_names_an_engine_category_or_a_collision(category: str,
                                                                      admitted: bool) -> None:
    """The holder's `6072197564` (b): the set is CLOSED. Only the engine raises
    a pathless finding, so its category is one of the engine's, or
    `identity-collision` in the re-raise of a pathless collision's
    disappearance (option (D))."""
    entry = "house-style" if category in AGAINST_A_PACK else ""
    identity = {"category": category, "entry": entry}
    finding = {**_example("no-sandbox"), "kind": "uncited-disappearance", "identity": identity,
               "id": _independent_id("opendox", "uncited-disappearance", "", identity)}
    found = [(v.rule, v.where) for v in hc.violations(finding)]
    if admitted:
        assert found == []
    else:
        assert found == [("pathless-identity-is-category-and-entry", "/identity/category")]


@pytest.mark.parametrize("category, entry, admitted", [
    *[(category, "", False) for category in sorted(AGAINST_A_PACK)],
    *[(category, "house-style", True) for category in sorted(AGAINST_A_PACK)],
    # the holder's 6082100803: the reserved `opendox`, and the 40-character name
    *[(category, "opendox", False) for category in sorted(AGAINST_A_PACK)],
    *[(category, "p" * 41, False) for category in sorted(AGAINST_A_PACK)],
    *[(category, "p" * 40, True) for category in sorted(AGAINST_A_PACK)],
    ("entry-refused", "opendox", True),
    ("entry-refused", "p" * 200, True),
    ("identity-collision", "house-style", False),
    ("identity-collision", "", True),
    *[(category, "house-style", False) for category in sorted(INSTALL_LEVEL)],
    *[(category, "", True) for category in sorted(INSTALL_LEVEL)],
    ("entry-refused", "", True),
    ("entry-refused", "house-style", True),
])
def test_a_pathless_entry_takes_its_categorys_form(category: str, entry: str,
                                                   admitted: bool) -> None:
    """Lane 3's REVIEW-W1 MINOR at `c620dacd` (`health_contract.py:693`), as the
    holder ruled it: a category against a pack names that pack's entry, never
    "", and an install-level category and a collision's re-raise take "";
    `entry-refused` takes either. Before, `check_finding()` admitted
    `{identity-collision, <an entry>}` and `{pack-crashed, ""}`, two forms
    the engine never builds."""
    identity = {"category": category, "entry": entry}
    finding = {**_example("no-sandbox"), "kind": "uncited-disappearance", "identity": identity,
               "id": _independent_id("opendox", "uncited-disappearance", "", identity)}
    found = [(v.rule, v.where) for v in hc.violations(finding)]
    if admitted:
        assert found == []
    else:
        assert found == [("pathless-identity-is-category-and-entry", "/identity/entry")]


#: Entries the exactness probe tries for every category.
_PROBE_ENTRIES = ["", "opendox", "house-style", "p" * 40, "p" * 41, "p" * 200, "p" * 201,
                  "House", "house style", "-", "a\x00b"]


def test_check_finding_admits_exactly_what_engine_finding_builds() -> None:
    """Lane 3's exactness probe (REVIEW-W1 MINOR at `4cc065ad`; the holder's
    `6082100803`): for every category and every probed entry, `engine_finding()`
    builds the finding exactly when `check_finding()` admits its identity in a
    re-raise, whose `pack_id` is `opendox`. It found 21 mismatches at
    `4cc065ad`; it reads 0 now."""
    mismatches = []
    for category in hc.CATEGORIES:
        for entry in _PROBE_ENTRIES:
            try:
                hc.engine_finding(category, entry, pack_version="1.0.0", severity="error",
                                  message="the probe")
                built = True
            except hc.FindingRefused:
                built = False
            identity = {"category": category, "entry": entry}
            reraise = {**_example("no-sandbox"), "kind": "uncited-disappearance",
                       "identity": identity,
                       "id": _independent_id("opendox", "uncited-disappearance", "", identity)}
            admitted = not hc.violations(reraise)
            if built != admitted:
                mismatches.append((category, entry[:12], built, admitted))
    assert mismatches == []


def test_refused_patch_is_a_pathed_engine_kind() -> None:
    """The holder's `6086098003` item 1: only the engine raises `refused-patch`,
    so T045 refuses a pack declaring it. It is PATHED, like
    `uncited-disappearance`: no category, and no pathless identity names it."""
    assert hc.REFUSED_PATCH == "refused-patch"
    assert hc.REFUSED_PATCH in hc.ENGINE_KINDS
    assert hc.REFUSED_PATCH not in hc.CATEGORIES
    assert hc.REFUSED_PATCH not in hc.PATHLESS_CATEGORIES
    finding = hc.make_finding(
        kind=hc.REFUSED_PATCH, pack_id="house-style", pack_version="1.4.0",
        path="notes/plan.md", identity={"refused_patch": "house-style.heading-case.1"},
        severity="error", resolution_class="human-only",
        message="the engine refused the pack's patch",
        evidence={"reason": "it reaches outside its path"})
    assert hc.violations(finding) == []
    identity = {"category": "refused-patch", "entry": ""}
    pathless = {**_example("no-sandbox"), "kind": "uncited-disappearance",
                "identity": identity,
                "id": _independent_id("opendox", "uncited-disappearance", "", identity)}
    assert [(v.rule, v.where) for v in hc.violations(pathless)] == [
        ("pathless-identity-is-category-and-entry", "/identity/category")]


def _canonical_digest(entry_id: Any) -> str:
    """The holder's `6088484643`, spelled independently of the module."""
    try:
        text = json.dumps(entry_id, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=True, default=str)
    except (TypeError, ValueError):
        text = repr(entry_id)
    return "sha256-" + hashlib.sha256(text.encode("ascii", "backslashreplace")).hexdigest()


_SELF: list[Any] = []
_SELF.append(_SELF)

#: Each refused id, and the entry `refused_entry()` gives it.
_REFUSED_IDS = {
    "an absent id": (None, ""),
    "a conforming id": ("house-style", "house-style"),
    "a conforming id of 200 characters": ("p" * 200, "p" * 200),
    "an uppercase id": ("House-Style", _canonical_digest("House-Style")),
    "a spaced id": ("house style", _canonical_digest("house style")),
    "an id with U+0000": ("house\x00style", _canonical_digest("house\x00style")),
    "an empty string": ("", _canonical_digest("")),
    "a non-string id": (5, _canonical_digest(5)),
    "a boolean id": (True, _canonical_digest(True)),
    "a float id, NaN": (float("nan"), "sha256-" + hashlib.sha256(b"NaN").hexdigest()),
    "a date id": (datetime.date(2026, 10, 9), _canonical_digest("2026-10-09")),
    "a list id": (["a", 1], _canonical_digest(["a", 1])),
    "a 201-character id": ("p" * 201, _canonical_digest("p" * 201)),
    "a mapping with mixed-type keys": (
        {1: "a", "b": 2}, "sha256-" + hashlib.sha256(repr({1: "a", "b": 2}).encode()).hexdigest()),
    "mixed-type keys with non-ASCII text": (
        {1: "caf\u00e9", "b": 2},
        "sha256-" + hashlib.sha256(b"{1: 'caf\\xe9', 'b': 2}").hexdigest()),
    "a self-referencing list": (_SELF, "sha256-" + hashlib.sha256(b"[[...]]").hexdigest()),
}


@pytest.mark.parametrize("name", list(_REFUSED_IDS))
def test_refused_entry_builds_entry_refuseds_entry(name: str) -> None:
    """The holder's `6086098003` item 4 and `6088484643`: "" for no id, the id
    as written when it is `[a-z0-9-]+` of at most 200 characters, and otherwise
    `sha256-` and the SHA-256 of its canonical text, its JSON with sorted keys,
    no whitespace and ASCII escapes (`repr()` when that raises). The entry is
    one `pathless_identity()` admits, never truncated, and never a refusal."""
    entry_id, entry = _REFUSED_IDS[name]
    assert hc.refused_entry(entry_id) == entry
    assert hc.refused_entry(entry_id) == entry  # deterministic
    assert hc.pathless_identity("entry-refused", entry) == {"category": "entry-refused",
                                                           "entry": entry}


def test_refused_entry_keeps_distinct_ids_apart_and_never_raises() -> None:
    entries = [hc.refused_entry(entry_id) for entry_id, _ in _REFUSED_IDS.values()]
    assert len(set(entries)) == len(entries)
    deep: Any = "x"
    for _ in range(sys.getrecursionlimit() * 3):
        deep = [deep]
    deep_entry = hc.refused_entry(deep)
    assert re.fullmatch(r"sha256-[0-9a-f]{64}", deep_entry)
    assert hc.refused_entry({"b": 1, "a": [2, 1]}) == hc.refused_entry({"a": [2, 1], "b": 1})


def test_an_engine_finding_against_a_41_character_pack_is_refused() -> None:
    """The holder's `6082100803`: a per-entry category's entry is a pack id of
    1 to 40 characters, judged at the identity, so `check_finding()` and
    `engine_finding()` refuse the same entries."""
    hc.engine_finding("pack-crashed", "p" * 40, pack_version="1", severity="error",
                      message="the pack crashed")
    with pytest.raises(hc.FindingRefused) as refused:
        hc.engine_finding("pack-crashed", "p" * 41, pack_version="1", severity="error",
                          message="the pack crashed")
    assert refused.value.rule == "pathless-identity-is-category-and-entry"
    assert refused.value.where == "/identity/entry"


def test_engine_finding_rebuilds_openDox_specs_no_sandbox_example() -> None:
    example = _example("no-sandbox")
    built = hc.engine_finding("no-sandbox", pack_version=example["pack_version"],
                              severity=example["severity"], message=example["message"],
                              evidence=example["evidence"])
    assert built == example


@pytest.mark.parametrize("category", ["manifest-refused", "dispositions-refused"])
def test_the_two_added_categories_are_admitted(category: str) -> None:
    assert hc.pathless_identity(category) == {"category": category, "entry": ""}


@pytest.mark.parametrize("category, entry", [
    ("not-a-category", ""), ("No-Sandbox", ""), ("", ""), (None, ""),
    ("entry-refused", "House"), ("entry-refused", "a" * 201), ("entry-refused", None),
    ("no-sandbox", "house-style"), ("manifest-refused", "house-style"),
    ("dispositions-refused", "house-style"), ("pack-crashed", ""), ("fetch-failed", "")])
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


def _pathless_collision() -> dict[str, Any]:
    return hc.make_finding(kind="identity-collision", pack_id="house-style",
                           pack_version="1.4.0", path="",
                           identity=hc.collision_identity(
                               "house-style.pack-crashed.0f1e2d3c4b5a6978"),
                           severity="error", resolution_class="human-only",
                           message="two findings of one run share one id")


#: Each original, and the identity its re-raise takes (option (D)).
_DISAPPEARED = {
    "a pathed finding": (lambda: _example("broken-link"),
                         {"disappeared_id": "opendox.broken-link.546cd2aacb1a6738"}),
    "a pathless finding": (lambda: _example("no-sandbox"),
                           {"category": "no-sandbox", "entry": ""}),
    "a pathless finding about an entry": (
        lambda: hc.engine_finding("pack-crashed", "house-style", pack_version="1.4.0",
                                  severity="error", message="the pack crashed"),
        {"category": "pack-crashed", "entry": "house-style"}),
    "a pathless collision": (_pathless_collision,
                             {"category": "identity-collision", "entry": ""}),
}


@pytest.mark.parametrize("name", list(_DISAPPEARED))
def test_the_disappearance_takes_the_form_its_originals_path_calls_for(name: str) -> None:
    """Option (D) (the holder's `6069024023` item 2): a pathed original's
    re-raise keeps `{disappeared_id}` and the original's path; a pathless
    original's takes the pathless form the schema requires. Either re-raise
    is a finding the contract admits, under its own id."""
    make_original, identity = _DISAPPEARED[name]
    original = make_original()
    assert hc.disappearance_identity(original) == identity
    reraise = hc.make_finding(
        kind="uncited-disappearance", pack_id="opendox", pack_version="0.2.0",
        path=original["path"], identity=hc.disappearance_identity(original),
        severity="warning", resolution_class="human-only",
        message="a finding disappeared with no landed repair citing it",
        evidence={"disappeared_id": original["id"], "baseline_run": "run-1"})
    assert hc.violations(reraise) == []
    assert reraise["id"] != original["id"]
    assert reraise["path"] == original["path"]


def test_a_pathless_reraise_takes_its_originals_kind_not_its_category() -> None:
    """Lane 3's REVIEW-W1 NIT at `f9cc4b0c`: an original whose kind is not its
    identity's category, the engine's own re-raise of a pathless
    disappearance. Its disappearance's identity names the original's KIND
    (option (D)). Under the closed set (`6072197564` (b)) no pathless finding
    names that kind, so the contract admits no re-raise of a pathless
    re-raise's disappearance."""
    original = hc.make_finding(
        kind="uncited-disappearance", pack_id="opendox", pack_version="0.2.0", path="",
        identity={"category": "no-sandbox", "entry": ""}, severity="warning",
        resolution_class="human-only",
        message="a finding disappeared with no landed repair citing it")
    identity = hc.disappearance_identity(original)
    assert identity == {"category": "uncited-disappearance", "entry": ""}
    with pytest.raises(hc.FindingRefused) as refused:
        hc.make_finding(kind="uncited-disappearance", pack_id="opendox", pack_version="0.2.0",
                        path="", identity=identity, severity="warning",
                        resolution_class="human-only", message="it disappeared again")
    assert refused.value.where == "/identity/category"


def test_the_disappeared_id_alone_is_refused_for_a_pathless_original() -> None:
    """Why the pathless form exists: `{disappeared_id}` on an empty path breaks
    the schema's `pathless-identity-is-category-and-entry`."""
    with pytest.raises(hc.FindingRefused) as refused:
        hc.make_finding(kind="uncited-disappearance", pack_id="opendox",
                        pack_version="0.2.0", path="",
                        identity={"disappeared_id": EXAMPLES["no-sandbox"]["id"]},
                        severity="warning", resolution_class="human-only", message="m")
    assert refused.value.rule == "pathless-identity-is-category-and-entry"


def test_the_disappearance_of_a_malformed_original_is_refused() -> None:
    original = _with("broken-link", id="opendox.broken-link.0000000000000000")
    with pytest.raises(hc.FindingRefused) as refused:
        hc.disappearance_identity(original)
    assert refused.value.rule == "id-is-the-hash-of-its-key"


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


def test_where_names_an_admitted_key_and_detail_names_none() -> None:
    """`where` is a pointer built from keys the module ADMITTED, and names them
    verbatim within its bound (below); `detail` names no key."""
    key = "ADMITTED-HEADING-KEY"
    violation = hc.violations({**_example("broken-link"), "identity": {key: 5}})[0]
    assert violation.rule == "identity-holds-no-number"
    assert violation.where == f"/identity/{key}"
    assert key not in violation.detail


def _nested_keys(levels: int, key: str, leaf: Any) -> dict[str, Any]:
    """`levels` objects, each holding the next under `key`, and `leaf` last."""
    value: Any = leaf
    for _ in range(levels):
        value = {key: value}
    return value


@pytest.mark.parametrize("identity, where", [
    ({"k" * 171: 5}, "/identity/" + "k" * 171),
    ({"k" * 190: 5}, "/identity/" + "k" * 190),
    ({"k" * 191: 5}, "/identity"),
    (_nested_keys(15, "/" * 200, 5), "/identity"),
    ({"a": {"b" * 195: {"c": 5}}}, "/identity/a"),
    ({"~" * 95: 5}, "/identity/" + "~0" * 95),
    ({"~" * 96: 5}, "/identity"),
    ({"a": [["x"], [True, 1]]}, "/identity/a/1/1"),
    ({"k" * 189: [5]}, "/identity/" + "k" * 189),
    ({"k" * 189: [[[[5]]]]}, "/identity/" + "k" * 189),
    ({"k" * 195: [{"a": 5}]}, "/identity"),
], ids=["a 171-character key, named", "the bound, 200 characters",
        "one past it, the ancestor", "lane 3's fifteen nested 200-character keys",
        "a stopped pointer stays stopped", "escapes count, at the bound",
        "escapes count, one past it", "array indices",
        "an index one past the bound, 201 characters", "indices to 207 characters",
        "a stopped pointer stays stopped through an index"])
def test_where_is_bounded_at_the_nearest_ancestor_that_fits(identity: Any, where: str) -> None:
    """Lane 3's REVIEW-W1 MINOR, bounded as the holder preferred: `where` is at
    most 200 characters, the place's own pointer or its nearest ancestor's that
    fits, so an engine may carry it as evidence. Unbounded, fifteen nested
    200-character keys of `/` made a 6026-character pointer. A pointer that
    stops stays stopped, so it never names a path that is not there."""
    found = hc.violations({**_example("broken-link"), "identity": identity})
    assert [(v.rule, v.where) for v in found] == [("identity-holds-no-number", where)]
    assert len(where) <= STRING_MAX


def test_where_is_bounded_in_evidence_too() -> None:
    evidence = {"a": {"b" * 195: {"text": "c"}}}
    found = hc.violations({**_example("broken-link"), "evidence": evidence})
    assert [(v.rule, v.where) for v in found] == [("evidence-names-no-text", "/evidence/a")]


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
