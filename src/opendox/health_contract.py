"""THE HEALTH CONTRACT: openDox's finding vocabulary, in the ONE module a check
pack may import (plan 038 T041, U-0; decision N-3; R2Q18 (a)).

WHY THIS FILE EXISTS. Release 2's health engine judges a corpus with the
product's own families and with check packs that a manifest pins (#1144
requirements 14 and 15). Each of them returns findings in one neutral shape,
which openDox-spec owns as `opendox-health-finding` (T040, landed as
openDox-spec `7db9438b`, bundled as `dox-v1.2` by T060; R2Q22 (a)). This module
states that shape in code: the three resolution classes, spelled exactly as
14.6 rules them (`auto-fix`, `assisted`, `human-only`), the severities, the
fields with `pack_id` and `pack_version` (15.7), the id rule, and the bounds.
openDox-code carries a digest-checked copy of the schema beside the validator
(`opendox.contracts`); this module MIRRORS that copy and never reads it,
because it may import the standard library alone. `tests/test_health_contract.py`
holds the two equal, constant for constant.

THE STANDARD LIBRARY ONLY (R2Q18 (a); N-3). A pack runs in a sandbox that binds
the install's interpreter, its standard library and this one module, never
`site-packages` (T048). So this module imports nothing else, of openDox or of
anyone, and the test proves it three ways: by its source, in a fresh
interpreter, and run alone under `python -I -S`.

THE ID RULE (N-13, refined by review round 1's ADV-07), as the copy's header
spells it:

    key = {"identity": <identity>, "kind": <kind>, "pack_id": <pack_id>,
           "path": <path>}, as
          json.dumps(key, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    h16 = the first 16 hex digits of sha256(key)
    id  = pack_id + "." + kind + "." + h16

`identity` is the POSITION-INDEPENDENT key a family supplies (a link target as
written, a pair of paths, a heading key), never a line number. `locator` is
display only and outside the hash, so an edit above a finding moves its locator
and keeps its id, and an exception keyed by that id keeps suppressing it. The
ENGINE sets the id: `make_finding()` takes none, so a pack's own value never
reaches a finding.

`identity` IS STORED AND EMITTED (the holder, `openxFactory#656` `6018624750`):
the engine hashes it into the id, T042 stores it as canonical sorted-key JSON
(`identity_json()`), and the list and the HTTP response emit it. So it is
bounded as the schema bounds it: no key named `excerpt`, `text`, `content` or
`quote`, no number, every string at most 200 characters, `{category, entry}` for
a pathless finding and `{collided_id}` for a collision.

THE ENGINE'S BOUNDS, STRICTER THAN THE SCHEMA'S. The contract module owns the
field bounds, so the engine's caps are here, each tested at its boundary:

* `NAME_MAX`: `pack_id` and `kind` are 1 to 40 characters, so `id` is at most
  98 and the fix branch `health-fix-<id>` at most 109, far below a ref path
  component's 255 bytes. The schema's patterns bound neither.
* `IDENTITY_MAX_BYTES`: the identity's canonical JSON, in UTF-8, is at most
  2048 bytes. The schema bounds each string and leaves the whole unbounded.
  T042 stores what this cap admits, and T046 enforces it at the engine's
  door; both cite this constant.
* `NESTING_MAX`: no value in `identity` or `evidence` nests more than 16
  objects and arrays deep, counting the field's own object. The walk below
  never recurses, and this bound keeps `json.dumps`, which does, far from
  Python's recursion limit.
* Every value is a JSON value: text keys, finite numbers, and no tuple, set or
  bytes (`finding-is-json`).

EVERY RULE HAS AN IDENTIFIER. A violation names the copy's own rule id (its
`x-rules` catalog: 24 shape rules and 3 reference rules) or one of the engine's
four (`ENGINE_RULES`). openDox's validator cannot build the finding schema: it
refuses a copy whose catalog names reference rules it does not implement
(`SchemaNotEvaluable`). The finding is no validator kind anyway (N-15), so all
27 rules are written here by hand, the three reference rules among them:
`id-names-its-pack-and-kind`, `id-is-the-hash-of-its-key` and
`locator-span-is-ordered`. As in openDox-spec's own test, a reference rule
judges only parts whose own rules hold, so one cause is reported once.

A REFUSAL QUOTES NOTHING OF THE FINDING. A finding may carry document text where
it must not, which is why it is refused. So no violation's text holds any of
the finding's own strings: it names the rule, the place (a JSON pointer built
only from keys this module admitted) and a size, a type or the admitted set.
A finding's names and hashes, once admitted, may be named.

THE ENGINE'S OWN IDENTITIES (contracts/health-finding.md § The id rule).
`pathless_identity()`, `collision_identity()` and `disappearance_identity()`
build the three keys the engine uses for its own findings, and `CATEGORIES`
fixes the failure categories of an install-level or pre-run finding, so each
such finding keeps one id across runs.

T045 APPENDS the pack protocol to this module (the static declaration, the
stdout document and the patch type) at T041's landing, a cross-lane hand-off
(plan.md § single-writer files).

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any, Iterator, Mapping, NamedTuple

__all__ = [
    "ASSISTED",
    "AUTO_FIX",
    "BASELINE_CLASSES",
    "CATEGORIES",
    "ENGINE_FIELDS",
    "ENGINE_RULES",
    "FIELDS",
    "FORBIDDEN_KEYS",
    "FindingRefused",
    "HASH_DIGITS",
    "HUMAN_ONLY",
    "IDENTITY_COLLISION",
    "IDENTITY_MAX_BYTES",
    "ID_MAX",
    "NAME_MAX",
    "NESTING_MAX",
    "OPENDOX",
    "OPTIONAL_FIELDS",
    "REFERENCE_RULES",
    "REQUIRED_FIELDS",
    "RESOLUTION_CLASSES",
    "SEVERITIES",
    "SHAPE_RULES",
    "STRING_MAX",
    "UNCITED_DISAPPEARANCE",
    "Violation",
    "canonical_json",
    "check_finding",
    "collision_identity",
    "disappearance_identity",
    "finding_id",
    "id_key",
    "identity_json",
    "make_finding",
    "pathless_identity",
    "to_json",
    "violations",
]

# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------

#: The three resolution classes, spelled exactly as 14.6 rules them, in the
#: store, the CLI, the view and the pack contract alike.
AUTO_FIX = "auto-fix"
ASSISTED = "assisted"
HUMAN_ONLY = "human-only"
RESOLUTION_CLASSES: tuple[str, ...] = (AUTO_FIX, ASSISTED, HUMAN_ONLY)

#: The severities, the schema's enum. Not `corpus_adapter.SEVERITIES`, which
#: adds `critical` for another surface.
SEVERITIES: tuple[str, ...] = ("error", "warning", "info")

#: The baseline classes the engine sets (R2Q12 (a)). There is no fourth value
#: (I-2 (a)).
BASELINE_CLASSES: tuple[str, ...] = ("new", "pack-upgrade", "persistent")

#: The pack id of the product's own families and of an install-level finding
#: (OQ-H15-19).
OPENDOX = "opendox"

#: The kind of the engine's finding against a producer two of whose findings
#: in one run shared one id.
IDENTITY_COLLISION = "identity-collision"

#: The kind of the engine's once-only re-raise of an uncited disappearance
#: (data-model.md § Baseline classes).
UNCITED_DISAPPEARANCE = "uncited-disappearance"

#: A finding's fields, in the schema's order.
REQUIRED_FIELDS: tuple[str, ...] = (
    "id", "kind", "pack_id", "pack_version", "path", "identity", "severity",
    "resolution_class", "message", "evidence")
OPTIONAL_FIELDS: tuple[str, ...] = ("locator", "baseline_class")
FIELDS: tuple[str, ...] = (
    "id", "kind", "pack_id", "pack_version", "path", "identity", "locator",
    "severity", "resolution_class", "message", "evidence", "baseline_class")

#: The fields the ENGINE sets; a family or pack is never asked for them (15.7).
ENGINE_FIELDS: tuple[str, ...] = ("id", "pack_id", "pack_version", "baseline_class")

#: No key of `identity` or `evidence`, at any depth, is named one of these
#: (R2Q25 (a)).
FORBIDDEN_KEYS: tuple[str, ...] = ("excerpt", "text", "content", "quote")

#: Every string of `identity`, `evidence` and `locator.target`, key or value,
#: and `message`, is at most this many characters (R2Q25 (a); ADV-27).
STRING_MAX = 200

#: The ENGINE's cap on `pack_id` and `kind`, stricter than the schema's
#: patterns, so a fix branch's name stays bounded.
NAME_MAX = 40

#: The id's hash: the first 16 hex digits of the key's SHA-256.
HASH_DIGITS = 16

#: The longest id: two names at the cap, the hash and two dots.
ID_MAX = 2 * NAME_MAX + HASH_DIGITS + 2

#: The ENGINE's cap on the identity's serialized size: its canonical JSON
#: (`identity_json()`), in UTF-8 bytes. The schema bounds each string and
#: leaves the whole unbounded, so this is stricter. The largest identity the
#: plan names, a pair of paths, fits in every UTF-8 width: two 200-character
#: strings of four-byte characters under two 40-character keys are 1693
#: bytes. T042 stores what it admits, and T046 enforces it.
IDENTITY_MAX_BYTES = 2048

#: The ENGINE's bound on nesting in `identity` and `evidence`: objects and
#: arrays, the field's own object counted as the first.
NESTING_MAX = 16

#: The failure categories of an install-level or pre-run finding, whose
#: identity is the engine's own `{category, entry}` (contracts/health-finding.md
#: § The id rule; T041 fixes them with the id rule). `entry` is the manifest
#: entry's id, or "" for none.
CATEGORIES: tuple[str, ...] = (
    "no-sandbox",            # no live sandbox, so no pack ran (R2Q16 (a))
    "entry-refused",         # a manifest entry refused by name (15.1a)
    "fetch-failed",          # a git-URL source that could not be fetched (OQ-H15-14)
    "digest-mismatch",       # a pack tree whose digest is not its entry's (15.1a)
    "declaration-refused",   # a pack's `opendox-pack.yaml` refused (15.2; OQ-H15-10)
    "pack-crashed",          # a pack that exited non-zero or on a signal (15.6)
    "pack-timed-out",        # a pack that ran past its time budget (15.6)
    "pack-bound-hit",        # a pack that hit one of the engine's bounds (15.6)
    "pack-output-refused",   # a pack's stdout the engine refused (15.5, 15.6)
)

#: The copy's catalog: the rules its own keywords state, and the three
#: cross-field rules no JSON Schema keyword can state.
SHAPE_RULES: tuple[str, ...] = (
    "finding-keys", "id-is-well-formed", "kind-is-a-family-name",
    "pack-id-is-a-name", "pack-version-is-text", "path-is-corpus-relative",
    "identity-is-an-object", "identity-holds-no-number",
    "identity-strings-are-short-text", "identity-names-no-text", "locator-keys",
    "locator-line-is-a-line-number", "locator-target-is-short-text",
    "severity-is-known", "resolution-class-is-one-of-three",
    "message-is-one-bounded-line", "evidence-is-an-object",
    "evidence-strings-are-short-text", "evidence-names-no-text",
    "baseline-class-is-known", "pathless-finding-is-human-only",
    "pathless-identity-is-category-and-entry", "identity-collision-is-human-only",
    "collision-identity-is-the-collided-id")
REFERENCE_RULES: tuple[str, ...] = (
    "id-names-its-pack-and-kind", "id-is-the-hash-of-its-key",
    "locator-span-is-ordered")

#: The engine's own rules, stricter than the copy's.
NAME_CAP = "name-is-at-most-40-characters"
SIZE_CAP = "identity-is-within-the-size-cap"
NESTING_CAP = "nesting-is-within-the-cap"
NOT_JSON = "finding-is-json"
ENGINE_RULES: tuple[str, ...] = (NAME_CAP, SIZE_CAP, NESTING_CAP, NOT_JSON)

# The schema's patterns, read as Python's `fullmatch`, which admits no trailing
# newline (the schema's `$(?!\n)`).
_NAME = re.compile(r"[a-z0-9-]+")
_ID = re.compile(r"([a-z0-9-]+)\.([a-z0-9-]+)\.([0-9a-f]{16})")
_ENTRY = re.compile(r"(?:[a-z0-9-]+)?")
_DRIVE = re.compile(r"[A-Za-z]:")
_SURROGATE = re.compile("[\ud800-\udfff]")
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_NOT_ONE_LINE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")


class Violation(NamedTuple):
    """One rule a finding breaks: the rule's id, where (a JSON pointer into the
    finding), and what was found. No part quotes the finding's own text."""

    rule: str
    where: str
    detail: str

    def line(self) -> str:
        return f"[{self.rule}] {self.where}: {self.detail}"


class FindingRefused(ValueError):
    """A finding, or a part of one, breaks a rule of the contract. `rule` and
    `where` are the first violation's; an engine records those, and never the
    refused value."""

    def __init__(self, violation: Violation, more: int = 0) -> None:
        self.violation = violation
        self.rule = violation.rule
        self.where = violation.where
        tail = f" (and {more} more)" if more else ""
        super().__init__(f"the finding is refused: {violation.line()}{tail}")


# ---------------------------------------------------------------------------
# the id rule
# ---------------------------------------------------------------------------

def canonical_json(value: Any) -> bytes:
    """`value` as canonical JSON: sorted keys at every level, no whitespace,
    each character as itself, in UTF-8. The id rule's spelling."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def id_key(*, identity: Any, kind: str, pack_id: str, path: str) -> bytes:
    """The bytes the id hashes (N-13; ADV-07). It checks nothing:
    `finding_id()` checks the parts first."""
    return canonical_json({"identity": identity, "kind": kind, "pack_id": pack_id,
                           "path": path})


def finding_id(*, identity: Any, kind: str, pack_id: str, path: str) -> str:
    """The id the engine sets: `pack_id.kind.h16`. Refuses, with
    `FindingRefused`, a key whose parts break their rules, so no id is ever
    computed over a part the contract does not admit."""
    found = (list(_name(kind, "/kind", "kind-is-a-family-name"))
             + list(_name(pack_id, "/pack_id", "pack-id-is-a-name"))
             + list(_path(path))
             + list(_identity(identity, path=path, kind=kind)))
    if found:
        raise FindingRefused(found[0], len(found) - 1)
    digest = hashlib.sha256(id_key(identity=identity, kind=kind, pack_id=pack_id,
                                   path=path)).hexdigest()
    return f"{pack_id}.{kind}.{digest[:HASH_DIGITS]}"


def identity_json(identity: Any) -> str:
    """The identity as T042 stores it: its canonical JSON, after its own
    bounds and the engine's cap. (The pathless and collision forms depend on
    the finding's path and kind; `check_finding()` judges those.)"""
    found = list(_identity(identity))
    if found:
        raise FindingRefused(found[0], len(found) - 1)
    return canonical_json(identity).decode("utf-8")


# ---------------------------------------------------------------------------
# the engine's own identities
# ---------------------------------------------------------------------------

def pathless_identity(category: str, entry: str = "") -> dict[str, str]:
    """An install-level or pre-run finding's identity: one of `CATEGORIES`,
    and the manifest entry's id, or "" for none."""
    rule = "pathless-identity-is-category-and-entry"
    if not isinstance(category, str) or category not in CATEGORIES:
        raise FindingRefused(Violation(
            rule, "/identity/category",
            f"the category is not one of the engine's: {', '.join(CATEGORIES)}"))
    if (not isinstance(entry, str) or not _ENTRY.fullmatch(entry)
            or len(entry) > STRING_MAX):
        raise FindingRefused(Violation(
            rule, "/identity/entry",
            "the entry is a manifest entry's id, of lowercase letters, digits and "
            f"hyphens and at most {STRING_MAX} characters, or the empty string"))
    return {"category": category, "entry": entry}


def collision_identity(collided_id: str) -> dict[str, str]:
    """A collision finding's identity: the id the colliding findings shared."""
    found = list(_id(collided_id, "/identity/collided_id",
                     "collision-identity-is-the-collided-id"))
    if found:
        raise FindingRefused(found[0])
    return {"collided_id": collided_id}


def disappearance_identity(disappeared_id: str) -> dict[str, str]:
    """The identity of the engine's re-raise of an uncited disappearance: the
    original's id. The re-raise has its own id, never the original's."""
    found = list(_id(disappeared_id, "/identity/disappeared_id", "id-is-well-formed"))
    if found:
        raise FindingRefused(found[0])
    return {"disappeared_id": disappeared_id}


# ---------------------------------------------------------------------------
# the rules
# ---------------------------------------------------------------------------

def _escape(key: str) -> str:
    """One JSON-pointer reference token (RFC 6901)."""
    return key.replace("~", "~0").replace("/", "~1")


def _type(value: Any) -> str:
    """The JSON type of a value, for a refusal's detail."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return f"a {type(value).__name__}, no JSON value"


def _text_problem(value: str) -> str | None:
    if len(value) > STRING_MAX:
        return f"is {len(value)} characters, above {STRING_MAX}"
    if _SURROGATE.search(value):
        return "holds a lone surrogate, which UTF-8 cannot encode"
    return None


def _name(value: Any, where: str, rule: str) -> Iterator[Violation]:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        yield Violation(rule, where, "is not a name of lowercase letters, digits and hyphens"
                        f" ({_type(value)})")
    elif len(value) > NAME_MAX:
        yield Violation(NAME_CAP, where, f"is {len(value)} characters; the engine's cap is "
                        f"{NAME_MAX}, so a fix branch's name stays bounded")


def _id(value: Any, where: str, rule: str) -> Iterator[Violation]:
    match = _ID.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        yield Violation(rule, where, "is not a pack id, a family and 16 lowercase hex "
                        f"digits, joined by dots ({_type(value)})")
    elif max(len(match.group(1)), len(match.group(2))) > NAME_MAX:
        yield Violation(NAME_CAP, where, f"names a pack or a family above the engine's "
                        f"cap of {NAME_MAX} characters")


def _pack_version(value: Any) -> Iterator[Violation]:
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        yield Violation("pack-version-is-text", "/pack_version",
                        "is not non-empty text free of control characters and lone "
                        f"surrogates ({_type(value)})")


def _path(value: Any) -> Iterator[Violation]:
    if not isinstance(value, str):
        yield Violation("path-is-corpus-relative", "/path", f"is not text ({_type(value)})")
        return
    if value.startswith("/") or _DRIVE.match(value):
        problem = "starts at a root or a drive"
    elif "\\" in value:
        problem = "holds a backslash"
    elif _CONTROL.search(value):
        problem = "holds a control character or a lone surrogate"
    elif ".." in value.split("/"):
        problem = "has a .. segment"
    else:
        return
    yield Violation("path-is-corpus-relative", "/path", problem)


def _walk(root: dict[Any, Any], where: str, field: str) -> Iterator[Violation]:
    """Every rule `identity`'s or `evidence`'s content breaks, at any depth,
    by an explicit stack and never by recursion. A refused key's value is not
    entered, so no pointer carries a key this module refused."""
    names_rule = f"{field}-names-no-text"
    strings_rule = f"{field}-strings-are-short-text"
    stack: list[tuple[Any, str, int]] = [(root, where, 1)]
    while stack:
        value, at, level = stack.pop()
        if isinstance(value, (dict, list)) and level > NESTING_MAX:
            yield Violation(NESTING_CAP, at, f"nests deeper than the engine's {NESTING_MAX} "
                            "levels of objects and arrays")
        elif isinstance(value, dict):
            inner: list[tuple[Any, str, int]] = []
            for key, item in value.items():
                if not isinstance(key, str):
                    yield Violation(NOT_JSON, at, f"has a key that is not text ({_type(key)})")
                elif key in FORBIDDEN_KEYS:
                    yield Violation(names_rule, at, f"has a key named {key}, which names "
                                    "document text")
                elif (problem := _text_problem(key)) is not None:
                    yield Violation(strings_rule, at, f"has a key that {problem}")
                else:
                    inner.append((item, f"{at}/{_escape(key)}", level + 1))
            stack.extend(reversed(inner))
        elif isinstance(value, list):
            stack.extend(reversed([(item, f"{at}/{index}", level + 1)
                                   for index, item in enumerate(value)]))
        elif isinstance(value, str):
            if (problem := _text_problem(value)) is not None:
                yield Violation(strings_rule, at, f"is a string that {problem}")
        elif value is None or isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)):
            if field == "identity":
                yield Violation("identity-holds-no-number", at,
                                "is a number, which an identity never holds")
            elif isinstance(value, float) and not math.isfinite(value):
                yield Violation(NOT_JSON, at, "is a number JSON cannot write")
            elif isinstance(value, int) and value.bit_length() > 64:
                try:
                    str(value)
                except ValueError:
                    yield Violation(NOT_JSON, at, "is an integer too long to write as text")
        else:
            yield Violation(NOT_JSON, at, f"is {_type(value)}")


def _identity(value: Any, *, path: Any = None, kind: Any = None) -> Iterator[Violation]:
    """Every rule the identity breaks: its own, the pathless or collision form
    its finding's path and kind call for (when given), and the engine's size
    cap, judged last and only over an identity every other rule admits."""
    if not isinstance(value, dict):
        yield Violation("identity-is-an-object", "/identity", f"is {_type(value)}, not an "
                        "object")
        return
    found = list(_walk(value, "/identity", "identity"))
    if kind == IDENTITY_COLLISION:
        found += _collision_form(value)
    elif path == "":
        found += _pathless_form(value)
    yield from found
    if not found:
        size = len(canonical_json(value))
        if size > IDENTITY_MAX_BYTES:
            yield Violation(SIZE_CAP, "/identity", f"its canonical JSON is {size} bytes; the "
                            f"engine's cap is {IDENTITY_MAX_BYTES}")


def _pathless_form(identity: dict[Any, Any]) -> Iterator[Violation]:
    rule = "pathless-identity-is-category-and-entry"
    if set(identity) != {"category", "entry"}:
        yield Violation(rule, "/identity", "a pathless finding's identity is exactly "
                        "{category, entry}, the engine's own")
        return
    if not isinstance(identity["category"], str) or not _NAME.fullmatch(identity["category"]):
        yield Violation(rule, "/identity/category", "is not a name of lowercase letters, "
                        "digits and hyphens")
    if not isinstance(identity["entry"], str) or not _ENTRY.fullmatch(identity["entry"]):
        yield Violation(rule, "/identity/entry", "is neither a manifest entry's id nor the "
                        "empty string")


def _collision_form(identity: dict[Any, Any]) -> Iterator[Violation]:
    rule = "collision-identity-is-the-collided-id"
    if set(identity) != {"collided_id"}:
        yield Violation(rule, "/identity", "a collision's identity is exactly "
                        "{collided_id}, the engine's own")
        return
    yield from _id(identity["collided_id"], "/identity/collided_id", rule)


def _line(value: Any) -> bool:
    """A whole number no less than 1: JSON's integer, which 12.0 is too."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 1
    return isinstance(value, float) and value.is_integer() and value >= 1


def _locator(value: Any) -> Iterator[Violation]:
    if not isinstance(value, dict):
        yield Violation("locator-keys", "/locator", f"is {_type(value)}, not an object")
        return
    keys = set(value)
    if not keys or keys - {"line_start", "line_end", "target"}:
        yield Violation("locator-keys", "/locator", "carries line_start and line_end "
                        "together, target, or both, and no other key")
    elif ("line_start" in keys) != ("line_end" in keys):
        yield Violation("locator-keys", "/locator", "carries line_start and line_end "
                        "together or neither")
    for key in ("line_start", "line_end"):
        if key in value and not _line(value[key]):
            yield Violation("locator-line-is-a-line-number", f"/locator/{key}",
                            f"is not a whole number no less than 1 ({_type(value[key])})")
    if "target" in value:
        target = value["target"]
        if not isinstance(target, str) or not target or _text_problem(target):
            yield Violation("locator-target-is-short-text", "/locator/target",
                            f"is not text of 1 to {STRING_MAX} characters free of lone "
                            f"surrogates ({_type(target)})")


def _one_of(value: Any, allowed: tuple[str, ...], where: str, rule: str) -> Iterator[Violation]:
    if not isinstance(value, str) or value not in allowed:
        yield Violation(rule, where, f"is not one of {', '.join(allowed)}")


def _message(value: Any) -> Iterator[Violation]:
    if (not isinstance(value, str) or not value or len(value) > STRING_MAX
            or _NOT_ONE_LINE.search(value)):
        size = f"{len(value)} characters" if isinstance(value, str) else _type(value)
        yield Violation("message-is-one-bounded-line", "/message",
                        f"is not one line of 1 to {STRING_MAX} characters free of control "
                        f"characters, line separators and lone surrogates ({size})")


def _evidence(value: Any) -> Iterator[Violation]:
    if not isinstance(value, dict):
        yield Violation("evidence-is-an-object", "/evidence", f"is {_type(value)}, not an "
                        "object")
        return
    yield from _walk(value, "/evidence", "evidence")


def violations(finding: Any) -> list[Violation]:
    """Every rule `finding` breaks, the copy's and the engine's, in the
    schema's field order, then the reference rules. Empty when the finding
    is admitted."""
    if not isinstance(finding, dict):
        return [Violation("finding-keys", "", f"a finding is an object, not {_type(finding)}")]
    found: list[Violation] = []
    if any(not isinstance(key, str) for key in finding):
        found.append(Violation(NOT_JSON, "", "has a field name that is not text"))
    missing = [field for field in REQUIRED_FIELDS if field not in finding]
    unknown = [key for key in finding if isinstance(key, str) and key not in FIELDS]
    if missing:
        found.append(Violation("finding-keys", "", f"lacks {', '.join(missing)}"))
    if unknown:
        found.append(Violation("finding-keys", "", f"carries {len(unknown)} field(s) the "
                               f"finding does not name; it names {', '.join(FIELDS)}"))
    checks: dict[str, Any] = {
        "id": lambda v: _id(v, "/id", "id-is-well-formed"),
        "kind": lambda v: _name(v, "/kind", "kind-is-a-family-name"),
        "pack_id": lambda v: _name(v, "/pack_id", "pack-id-is-a-name"),
        "pack_version": _pack_version,
        "path": _path,
        "identity": lambda v: _identity(v, path=finding.get("path"),
                                        kind=finding.get("kind")),
        "locator": _locator,
        "severity": lambda v: _one_of(v, SEVERITIES, "/severity", "severity-is-known"),
        "resolution_class": lambda v: _one_of(v, RESOLUTION_CLASSES, "/resolution_class",
                                              "resolution-class-is-one-of-three"),
        "message": _message,
        "evidence": _evidence,
        "baseline_class": lambda v: _one_of(v, BASELINE_CLASSES, "/baseline_class",
                                            "baseline-class-is-known"),
    }
    broken: set[str] = set()
    for field in FIELDS:
        if field in finding:
            mine = list(checks[field](finding[field]))
            if mine:
                broken.add(field)
                found += mine
    found += _conditional(finding, broken)
    found += _references(finding, broken)
    return found


def _conditional(finding: Mapping[str, Any], broken: set[str]) -> Iterator[Violation]:
    """The class a pathless or collision finding must have. (The identity's
    forms are judged with the identity.) Judged over a known class only, so a
    class outside the three is reported once, by its own rule."""
    known = "resolution_class" in finding and "resolution_class" not in broken
    if not known or finding["resolution_class"] == HUMAN_ONLY:
        return
    if finding.get("path") == "":
        yield Violation("pathless-finding-is-human-only", "/resolution_class",
                        "a pathless finding names no document a repair could edit, so it "
                        "is human-only")
    if finding.get("kind") == IDENTITY_COLLISION:
        yield Violation("identity-collision-is-human-only", "/resolution_class",
                        "an identity collision is human-only")


def _references(finding: Mapping[str, Any], broken: set[str]) -> Iterator[Violation]:
    """The three cross-field rules, each judged only over parts every rule of
    their own admits."""
    def admitted(*fields: str) -> bool:
        return all(field in finding and field not in broken for field in fields)

    if admitted("id", "kind", "pack_id"):
        named_pack, named_kind, _h16 = finding["id"].split(".")
        if (named_pack, named_kind) != (finding["pack_id"], finding["kind"]):
            yield Violation("id-names-its-pack-and-kind", "/id",
                            f"names {named_pack} and {named_kind}, and the finding is "
                            f"{finding['pack_id']}'s {finding['kind']}")
    if admitted("id", "kind", "pack_id", "path", "identity"):
        want = hashlib.sha256(id_key(identity=finding["identity"], kind=finding["kind"],
                                     pack_id=finding["pack_id"], path=finding["path"])
                              ).hexdigest()[:HASH_DIGITS]
        have = finding["id"].rsplit(".", 1)[1]
        if have != want:
            yield Violation("id-is-the-hash-of-its-key", "/id",
                            f"the hash is {have}, and the finding's key hashes to {want}")
    locator = finding.get("locator") if "locator" not in broken else None
    if isinstance(locator, dict) and "line_start" in locator and "line_end" in locator:
        start, end = locator["line_start"], locator["line_end"]
        if end < start:
            yield Violation("locator-span-is-ordered", "/locator/line_end",
                            f"the span ends at {end:g}, before it starts at {start:g}")


def check_finding(finding: Any) -> None:
    """Refuse `finding`, with `FindingRefused` naming its first violation,
    unless it breaks no rule."""
    found = violations(finding)
    if found:
        raise FindingRefused(found[0], len(found) - 1)


# ---------------------------------------------------------------------------
# the engine's door, and the module's own serialization
# ---------------------------------------------------------------------------

def make_finding(*, kind: str, pack_id: str, pack_version: str, path: str,
                 identity: dict[str, Any], severity: str, resolution_class: str,
                 message: str, evidence: dict[str, Any] | None = None,
                 locator: dict[str, Any] | None = None,
                 baseline_class: str | None = None) -> dict[str, Any]:
    """One finding, its id SET by the id rule and checked whole.

    A family or pack supplies the fields it owns; the engine passes the
    `pack_id` and `pack_version` it stamps (15.7) and any `baseline_class` it
    sets. There is no `id` parameter: the id is the engine's, and a pack's
    own value never reaches a finding. `evidence` defaults to `{}`, so every
    finding carries it (14.5; FR-011). The result is the module's own copy,
    in the schema's field order; `FindingRefused` names the first rule broken."""
    fid = finding_id(identity=identity, kind=kind, pack_id=pack_id, path=path)
    finding: dict[str, Any] = {"id": fid, "kind": kind, "pack_id": pack_id,
                               "pack_version": pack_version, "path": path,
                               "identity": identity}
    if locator is not None:
        finding["locator"] = locator
    finding.update(severity=severity, resolution_class=resolution_class, message=message,
                   evidence={} if evidence is None else evidence)
    if baseline_class is not None:
        finding["baseline_class"] = baseline_class
    check_finding(finding)
    # Copied after the check, which bounds the nesting the copy recurses into.
    return copy.deepcopy(finding)


def to_json(finding: dict[str, Any]) -> str:
    """The finding as this module serializes it: checked whole, then canonical
    JSON (sorted keys, no whitespace, each character as itself). Nothing the
    contract refuses is ever written."""
    check_finding(finding)
    return canonical_json(finding).decode("utf-8")
