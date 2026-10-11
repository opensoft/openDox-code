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
reaches a finding. `finding_id()` is the module's ONE hash path: every id it
sets or checks is computed there.

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
* No string a finding carries holds U+0000 (`text-holds-no-nul`; the holder's
  `openxFactory#656` `6072086385` item 4), keys and values alike: Postgres
  `jsonb` cannot store it (SQLSTATE 22P05), so such a finding could never be
  stored. The schema admits it in `identity`, `evidence` and `locator.target`,
  so this rule refuses it there, with a bounded `where`; in `message`, `path`
  and `pack_version` the schema's own control-character rules refuse it
  already. For a pack's output, this refusal is T045's whole-output
  `pack-output-refused` (`6069024023` item 1's mapping), so a broken or hostile
  pack loses its own output, never the run. T042's `_json_text` refuses it
  too, as defence in depth.

EVERY RULE HAS AN IDENTIFIER. A violation names the copy's own rule id (its
`x-rules` catalog: 24 shape rules and 3 reference rules) or one of the engine's
five (`ENGINE_RULES`). openDox's validator cannot build the finding schema: it
refuses a copy whose catalog names reference rules it does not implement
(`SchemaNotEvaluable`). The finding is no validator kind anyway (N-15), so all
27 rules are written here by hand, the three reference rules among them:
`id-names-its-pack-and-kind`, `id-is-the-hash-of-its-key` and
`locator-span-is-ordered`. As in openDox-spec's own test, a reference rule
judges only parts whose own rules hold, so one cause is reported once.

A REFUSAL QUOTES NOTHING IT REFUSED, AND ITS POINTER IS BOUNDED. A finding may
carry document text where it must not, which is why it is refused. So no
refused string, key or value reaches a violation: its `detail` names a size, a
type or the admitted set, never a value of the finding, and a finding's names
and hashes are named only once admitted. Its `where` is a JSON pointer built
only from keys this module ADMITTED, so it names those verbatim (each within
the contract's own bound on a key) and never a refused one, and it is at most
`STRING_MAX` characters: the place's own pointer, or, when that is longer, its
nearest ancestor's that fits. So an engine may record a refusal's `rule` and
`where` as `evidence` of the finding against the pack, whose every string is
bounded at 200 characters.

THE ENGINE'S OWN FINDINGS (contracts/health-finding.md § The id rule; the
holder's rulings `openxFactory#656` `6069024023`, items 1 and 2).

* `CATEGORIES` fixes the failure categories of an install-level or pre-run
  finding. A category is also that finding's `kind`, its `pack_id` is fixed
  per category (`ENTRY_CATEGORIES`; the value is `6072086385` item 1's), and
  its identity is `{category, entry}`, so the engine raises ONE such finding
  per category and entry in a run, with the reasons in `evidence`, and it
  keeps one id across runs. The install-level categories
  (`INSTALL_CATEGORIES`) take entry "": a run raises ONE such finding
  (`6072197564` (e)). `pathless_identity()` builds the identity and
  `engine_finding()` the whole finding.
* A pathless finding's `identity.category` is one of `PATHLESS_CATEGORIES`,
  the engine's categories and `identity-collision`, and nothing else
  (`6072197564` (b)): only the engine raises a pathless finding.
* `collision_identity()` builds a collision's `{collided_id}`.
* `disappearance_identity()` builds the identity of the re-raise of an
  uncited disappearance, in the form its original's path calls for: a pathed
  original's `{disappeared_id}`, and for a pathless original the pathless form
  the schema requires, `{category: <the original's kind>, entry: <its entry,
  or "">}` (option (D)). T046 raises it.
* `ENGINE_KINDS` are the kinds only the engine raises, which T045 refuses in a
  pack's declaration: the categories, `identity-collision`, and the PATHED
  `uncited-disappearance` and `refused-patch` (`6086098003` item 1).
* `refused_entry()` builds `entry-refused`'s `identity.entry` from a refused
  entry's id (`6086098003` item 4, `6088484643`): "" for no id, the id as
  written when it is a pack-id-shaped name of at most 200 characters, and
  otherwise `sha256-` and the digest of its canonical text. That digest is no
  finding id: every id is still `finding_id()`'s.
* `IGNORED_FIELDS` and `STAMPED_FIELDS` split the fields a pack does not own
  by what happens to a pack's value (`6072197564` (d)): its `id` is ignored,
  and `pack_id`, `pack_version` and `baseline_class` are the engine's.

T045 APPENDS the pack protocol to this module (the static declaration, the
stdout document and the patch type) at T041's landing, a cross-lane hand-off
(plan.md:458, § "Parallel slices, and the files only one writer may touch at
a time").

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
    "ENGINE_KINDS",
    "ENGINE_RULES",
    "ENTRY_CATEGORIES",
    "FIELDS",
    "FORBIDDEN_KEYS",
    "FindingRefused",
    "HASH_DIGITS",
    "HUMAN_ONLY",
    "IDENTITY_COLLISION",
    "IDENTITY_MAX_BYTES",
    "ID_MAX",
    "IGNORED_FIELDS",
    "INSTALL_CATEGORIES",
    "NAME_MAX",
    "NESTING_MAX",
    "OPENDOX",
    "OPTIONAL_FIELDS",
    "PATHLESS_CATEGORIES",
    "REFERENCE_RULES",
    "REFUSED_PATCH",
    "REQUIRED_FIELDS",
    "RESOLUTION_CLASSES",
    "SEVERITIES",
    "SHAPE_RULES",
    "STAMPED_FIELDS",
    "STRING_MAX",
    "UNCITED_DISAPPEARANCE",
    "Violation",
    "canonical_json",
    "check_finding",
    "collision_identity",
    "disappearance_identity",
    "engine_finding",
    "finding_id",
    "id_key",
    "identity_json",
    "make_finding",
    "pathless_identity",
    "refused_entry",
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
#: (data-model.md § Baseline classes; T046 raises it).
UNCITED_DISAPPEARANCE = "uncited-disappearance"

#: The kind of the engine's finding against a pack whose patch it refused,
#: naming `refused_patch` and `reason` (T049; data-model.md:209, :223, :369).
#: A PATHED engine kind, like `uncited-disappearance`, and no category (the
#: holder's `6086098003` item 1).
REFUSED_PATCH = "refused-patch"

#: A finding's fields, in the schema's order.
REQUIRED_FIELDS: tuple[str, ...] = (
    "id", "kind", "pack_id", "pack_version", "path", "identity", "severity",
    "resolution_class", "message", "evidence")
OPTIONAL_FIELDS: tuple[str, ...] = ("locator", "baseline_class")
FIELDS: tuple[str, ...] = (
    "id", "kind", "pack_id", "pack_version", "path", "identity", "locator",
    "severity", "resolution_class", "message", "evidence", "baseline_class")

#: The fields a pack does not own, split by what happens to its value (the
#: holder's `6072197564` (d)). A pack's own `id` is IGNORED: the engine computes
#: every id by the id rule (`finding_id()`), so `make_finding()` takes none and
#: a pack's value never reaches a finding (`6065680005` item 3).
IGNORED_FIELDS: tuple[str, ...] = ("id",)
#: The fields that are the ENGINE's: it stamps `pack_id` and `pack_version`
#: (15.7) and sets `baseline_class`; a pack's output that sets one is refused
#: (T045, `6065680005` item 3).
STAMPED_FIELDS: tuple[str, ...] = ("pack_id", "pack_version", "baseline_class")

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
#: entry's id, or "" for none. The nine T041 drafted are ACCEPTED as written,
#: and the last two are ADDED, by the holder's `6069024023` item 1. A category
#: is also its finding's `kind`.
CATEGORIES: tuple[str, ...] = (
    "no-sandbox",            # no live sandbox, so no pack ran (R2Q16 (a))
    "entry-refused",         # a manifest entry refused by name (15.1a)
    "fetch-failed",          # a git-URL source that could not be fetched (OQ-H15-14)
    "digest-mismatch",       # a pack tree whose digest is not its entry's (15.1a)
    "declaration-refused",   # a pack's `opendox-pack.yaml` refused (15.2; OQ-H15-10)
    "pack-crashed",          # a pack that exited non-zero or on a signal (15.6)
    "pack-timed-out",        # a pack that ran past its time budget (15.6)
    "pack-bound-hit",        # a pack that hit one of the engine's bounds, its
                             # stdout cap included (15.6)
    "pack-output-refused",   # a pack's stdout that is not one JSON document, or
                             # breaks the contract; refused whole (15.5, 15.6)
    "manifest-refused",      # `health/packs.yaml` refused as a whole; entry "" (15.1a)
    "dispositions-refused",  # `health/dispositions.yaml` refused; entry ""
                             # (contracts/health-exceptions.md; T054 raises it)
)

#: The categories whose finding is against the PACK its manifest entry
#: launched: the finding's `pack_id` is the entry's id, which is its pack's id
#: (15.7), so `entry` is never empty for them. Every other category's finding is
#: against the product itself, `opendox`: no live sandbox, a refused manifest or
#: dispositions file, and a refused entry, whose id may be malformed, reserved
#: or repeated and so is no pack id to attribute a finding to; it rides only in
#: `identity.entry`. This is the holder's `6072086385` item 1, beside
#: `6069024023` item 1: it names the value that ruling's "one pack_id per
#: category" left open, after dox-v1.2's schema text for `pack_id`.
ENTRY_CATEGORIES: frozenset[str] = frozenset({
    "fetch-failed", "digest-mismatch", "declaration-refused", "pack-crashed",
    "pack-timed-out", "pack-bound-hit", "pack-output-refused"})

#: The kinds only the ENGINE raises: its categories, a collision and the
#: re-raise of a disappearance. A pack declares none of them (T045 refuses
#: one; the holder's `6069024023` item 1).
ENGINE_KINDS: frozenset[str] = frozenset(CATEGORIES) | {IDENTITY_COLLISION,
                                                       UNCITED_DISAPPEARANCE,
                                                       REFUSED_PATCH}

#: The install-level categories: a run raises ONE such finding, never one per
#: entry (data-model.md:382, "ONE install-level finding"; R2Q16 (a)), so its
#: entry is always "" and a non-empty one is refused (the holder's `6069024023`
#: item 1 and `6072197564` (e)). Only `ENTRY_CATEGORIES` and `entry-refused`
#: take an entry.
INSTALL_CATEGORIES: frozenset[str] = frozenset({
    "no-sandbox", "manifest-refused", "dispositions-refused"})

#: The categories a pathless finding's identity may name, a CLOSED set (the
#: holder's `6072197564` (b)): the engine's own, and `identity-collision`, the
#: kind of a pathless collision whose disappearance is re-raised (option (D)).
#: A pack raises no pathless finding (T045 refuses one; `6072086385` item 3).
PATHLESS_CATEGORIES: frozenset[str] = frozenset(CATEGORIES) | {IDENTITY_COLLISION}

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
NO_NUL = "text-holds-no-nul"
ENGINE_RULES: tuple[str, ...] = (NAME_CAP, SIZE_CAP, NESTING_CAP, NOT_JSON, NO_NUL)

# The pointers of the fields more than one rule reports at.
_AT_IDENTITY = "/identity"
_AT_ENTRY = "/identity/entry"
_AT_LOCATOR = "/locator"
_AT_TARGET = "/locator/target"
_AT_RESOLUTION_CLASS = "/resolution_class"

# The schema's patterns, read as Python's `fullmatch`, which admits no trailing
# newline (the schema's `$(?!\n)`).
_NAME = re.compile(r"[a-z0-9-]+")
_ID = re.compile(r"([a-z0-9-]+)\.([a-z0-9-]+)\.([0-9a-f]{16})")
_ENTRY = re.compile(r"(?:[a-z0-9-]+)?")
_DRIVE = re.compile(r"[A-Za-z]:")
_SURROGATE = re.compile("[\ud800-\udfff]")
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
_NOT_ONE_LINE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\ud800-\udfff]")
_NUL = "\x00"
_NUL_DETAIL = "holds U+0000, which a stored finding cannot carry (jsonb refuses it)"
_ENTRY_FORM_DETAIL = ("does not take its category's form: a pack's id for a category "
                      "against a pack, and empty for an install-level category or a "
                      "collision")


class Violation(NamedTuple):
    """One rule a finding breaks: the rule's id, where (a JSON pointer into the
    finding of at most `STRING_MAX` characters, built from keys this module
    admitted, which it names verbatim; past the bound, the nearest ancestor's
    pointer that fits), and what was found. No part quotes a string, key or
    value it refused."""

    rule: str
    where: str
    detail: str

    def line(self) -> str:
        return f"[{self.rule}] {self.where}: {self.detail}"


class FindingRefused(ValueError):
    """A finding, or a part of one, breaks a rule of the contract. `rule` and
    `where` are the first violation's, and an engine records those, never the
    refused value: `where` is at most `STRING_MAX` characters and names only
    admitted keys."""

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
    computed over a part the contract does not admit.

    THE ONE HASH PATH (the holder's `6069507373`, T046 item 2). Every id this
    module sets or checks is computed here, and its callers look it up at call
    time, so a test that patches `health_contract.finding_id` patches them all."""
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
            rule, _AT_ENTRY,
            "the entry is a manifest entry's id, of lowercase letters, digits and "
            f"hyphens and at most {STRING_MAX} characters, or the empty string"))
    if _entry_breaks_form(category, entry):
        raise FindingRefused(Violation(rule, _AT_ENTRY, _ENTRY_FORM_DETAIL))
    return {"category": category, "entry": entry}


def collision_identity(collided_id: str) -> dict[str, str]:
    """A collision finding's identity: the id the colliding findings shared."""
    found = list(_id(collided_id, "/identity/collided_id",
                     "collision-identity-is-the-collided-id"))
    if found:
        raise FindingRefused(found[0])
    return {"collided_id": collided_id}


def _spelling(value: Any) -> Any:
    """`refused_entry()`'s `default` hook for a value JSON cannot represent: a
    set's members in the order of their `ascii()` text, and anything else by
    its `str()` (the holder's `6090537166` item 8 (b))."""
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=ascii)
    return str(value)


def refused_entry(entry_id: Any) -> str:
    """`entry-refused`'s `identity.entry` for a refused manifest entry's id
    (the holder's `6086098003` item 4 and `6088484643`). Deterministic, total
    over every value the manifest's YAML parser yields, and it never raises.

    * No id (`None`, as the parser gives an absent or null `id`): "".
    * A string matching `[a-z0-9-]+` of at most `STRING_MAX` characters: the id
      as written.
    * Anything else (a malformed or over-long string, one carrying U+0000, a
      non-string): `sha256-` and the lowercase SHA-256 hex of the ASCII bytes
      of its CANONICAL TEXT, 71 characters. The canonical text is
      `json.dumps(entry_id, sort_keys=True, separators=(",", ":"),
      ensure_ascii=True, allow_nan=True, default=...)`, whose `default` hook
      spells a `set` or `frozenset` as the list of its members sorted by each
      member's `ascii()` text, so a YAML `!!set` is spelled one way under every
      `PYTHONHASHSEED`, and spells every other value JSON cannot represent (a
      YAML date, timestamp or binary) by its `str()` (the holder's `6090537166`
      item 8 (b)). When that raises (a mapping whose keys JSON cannot spell or
      sort, a self-referencing value), the text is `ascii(entry_id)`,
      Python's `repr()` with every non-ASCII character escaped (`6088732352`
      (b)), so it is always ASCII.
      A value neither spelling can write, an integer past Python's 4300-digit
      conversion limit (which YAML yields from a long `0x` or `0b` literal) or
      a value nested past the recursion limit, takes ONE fixed text, `<past
      the int-digit or recursion limit>` (item 8 (a)). So the digest never
      raises.

    ACCEPTED LIMITS (`6088732352` (a), `6089449884`, `6090537166`): the text is
    not injective across YAML value types (a date and its `str()`, a
    non-string mapping key and its JSON spelling), two ids past the limits
    share the fixed text, and a set reached only through the `ascii()`
    fallback keeps Python's order. `identity-collision` reports any
    collision.

    The digest is no finding id (every id is `finding_id()`'s); it keeps a
    refused id out of the stored identity while keeping two distinct ids
    apart."""
    if entry_id is None:
        return ""
    if (isinstance(entry_id, str) and len(entry_id) <= STRING_MAX
            and _NAME.fullmatch(entry_id)):
        return entry_id
    try:
        text = json.dumps(entry_id, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=True, default=_spelling)
    except (TypeError, ValueError, RecursionError):
        try:
            text = ascii(entry_id)
        except (ValueError, RecursionError):
            text = "<past the int-digit or recursion limit>"
    digest = hashlib.sha256(text.encode("ascii")).hexdigest()
    return f"sha256-{digest}"


def disappearance_identity(original: dict[str, Any]) -> dict[str, str]:
    """The identity of the engine's re-raise of an uncited disappearance, in
    the form the ORIGINAL's path calls for (option (D), the holder's
    `6069024023` item 2). T046 raises the re-raise: kind
    `uncited-disappearance`, the original's path, human-only, and the
    original's id and the baseline run in `evidence`.

    * A pathed original's: `{"disappeared_id": <its id>}`.
    * A pathless original's: the pathless form the schema requires,
      `{"category": <its kind>, "entry": <its identity's entry, or "">}`. A
      pathless collision has no entry, so its entry is "".

    `original` is the finding as stored, checked whole first."""
    check_finding(original)
    if original["path"] != "":
        return {"disappeared_id": original["id"]}
    return {"category": original["kind"], "entry": original["identity"].get("entry", "")}


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


#: One place in a walk: the value, its bounded pointer, whether that pointer
#: has stopped at an ancestor, and the value's nesting level.
_Place = tuple[Any, str, bool, int]


def _child(at: str, stopped: bool, token: str) -> tuple[str, bool]:
    """A child's pointer, bounded: `at` extended by `token` while the result
    is at most `STRING_MAX` characters, and otherwise `at` itself, marked as
    STOPPED. A stopped pointer stays stopped for every descendant, so `where`
    names the nearest ancestor that fits and never a path that is not there."""
    if not stopped:
        child = f"{at}/{_escape(token)}"
        if len(child) <= STRING_MAX:
            return child, False
    return at, True


def _walk(root: dict[Any, Any], where: str, field: str) -> Iterator[Violation]:
    """Every rule `identity`'s or `evidence`'s content breaks, at any depth,
    by an explicit stack and never by recursion. A refused key's value is not
    entered, so no pointer carries a key this module refused, and every
    pointer is bounded (`_child`)."""
    stack: list[_Place] = [(root, where, False, 1)]
    while stack:
        value, at, stopped, level = stack.pop()
        if not isinstance(value, (dict, list)):
            yield from _scalar(value, at, field)
        elif level > NESTING_MAX:
            yield Violation(NESTING_CAP, at, f"nests deeper than the engine's {NESTING_MAX} "
                            "levels of objects and arrays")
        elif isinstance(value, dict):
            refused, inner = _members(value, at, stopped, level, field)
            yield from refused
            stack.extend(reversed(inner))
        else:
            stack.extend(reversed([(item, *_child(at, stopped, str(index)), level + 1)
                                   for index, item in enumerate(value)]))


def _members(value: dict[Any, Any], at: str, stopped: bool, level: int, field: str
             ) -> tuple[list[Violation], list[_Place]]:
    """An object's refused keys, and the members to enter: those whose keys
    every rule admits."""
    refused: list[Violation] = []
    inner: list[_Place] = []
    for key, item in value.items():
        if not isinstance(key, str):
            refused.append(Violation(NOT_JSON, at, f"has a key that is not text ({_type(key)})"))
        elif key in FORBIDDEN_KEYS:
            refused.append(Violation(f"{field}-names-no-text", at,
                                     f"has a key named {key}, which names document text"))
        elif (problem := _text_problem(key)) is not None:
            refused.append(Violation(f"{field}-strings-are-short-text", at,
                                     f"has a key that {problem}"))
        elif _NUL in key:
            refused.append(Violation(NO_NUL, at, f"has a key that {_NUL_DETAIL}"))
        else:
            inner.append((item, *_child(at, stopped, key), level + 1))
    return refused, inner


def _scalar(value: Any, at: str, field: str) -> Iterator[Violation]:
    """The rules a value that is no object or array breaks."""
    if isinstance(value, str):
        if (problem := _text_problem(value)) is not None:
            yield Violation(f"{field}-strings-are-short-text", at, f"is a string that {problem}")
        elif _NUL in value:
            yield Violation(NO_NUL, at, f"is a string that {_NUL_DETAIL}")
    elif value is None or isinstance(value, bool):
        return
    elif not isinstance(value, (int, float)):
        yield Violation(NOT_JSON, at, f"is {_type(value)}")
    elif field == "identity":
        yield Violation("identity-holds-no-number", at,
                        "is a number, which an identity never holds")
    elif isinstance(value, float) and not math.isfinite(value):
        yield Violation(NOT_JSON, at, "is a number JSON cannot write")
    elif isinstance(value, int) and not _writable(value):
        yield Violation(NOT_JSON, at, "is an integer too long to write as text")


def _identity(value: Any, *, path: Any = None, kind: Any = None) -> Iterator[Violation]:
    """Every rule the identity breaks: its own, the pathless or collision form
    its finding's path and kind call for (when given), and the engine's size
    cap, judged last and only over an identity every other rule admits."""
    if not isinstance(value, dict):
        yield Violation("identity-is-an-object", _AT_IDENTITY, f"is {_type(value)}, not an "
                        "object")
        return
    found = list(_walk(value, _AT_IDENTITY, "identity"))
    if kind == IDENTITY_COLLISION:
        found += _collision_form(value)
    elif path == "":
        found += _pathless_form(value)
    yield from found
    if not found:
        size = len(canonical_json(value))
        if size > IDENTITY_MAX_BYTES:
            yield Violation(SIZE_CAP, _AT_IDENTITY, f"its canonical JSON is {size} bytes; the "
                            f"engine's cap is {IDENTITY_MAX_BYTES}")


def _pathless_form(identity: dict[Any, Any]) -> Iterator[Violation]:
    rule = "pathless-identity-is-category-and-entry"
    if set(identity) != {"category", "entry"}:
        yield Violation(rule, _AT_IDENTITY, "a pathless finding's identity is exactly "
                        "{category, entry}, the engine's own")
        return
    category, entry = identity["category"], identity["entry"]
    known = isinstance(category, str) and category in PATHLESS_CATEGORIES
    if not known:
        yield Violation(rule, "/identity/category", "is not one of the engine's categories "
                        "or identity-collision")
    if not isinstance(entry, str) or not _ENTRY.fullmatch(entry):
        yield Violation(rule, _AT_ENTRY, "is neither a manifest entry's id nor the "
                        "empty string")
    elif known and _entry_breaks_form(category, entry):
        yield Violation(rule, _AT_ENTRY, _ENTRY_FORM_DETAIL)


def _entry_breaks_form(category: str, entry: str) -> bool:
    """Whether a pathless identity's entry breaks the form its category calls
    for (the holder's `6073087924`, on lane 3's MINOR at `c620dacd`, refining
    `6072197564` (e)), so `check_finding()` admits exactly what
    `engine_finding()` builds. A category against a pack (`ENTRY_CATEGORIES`)
    names that pack's entry, which is that pack's id: never empty, never the
    reserved `opendox` (contracts/health-packs-manifest.md:24) and a name of 1
    to `NAME_MAX` characters (the holder's `6082100803`; the alphabet is
    checked before this). An install-level category and a collision's re-raise
    take entry ""; `entry-refused` takes either (`refused_entry()`)."""
    if category in ENTRY_CATEGORIES:
        return entry in ("", OPENDOX) or len(entry) > NAME_MAX
    if category in INSTALL_CATEGORIES or category == IDENTITY_COLLISION:
        return entry != ""
    return False


def _collision_form(identity: dict[Any, Any]) -> Iterator[Violation]:
    rule = "collision-identity-is-the-collided-id"
    if set(identity) != {"collided_id"}:
        yield Violation(rule, _AT_IDENTITY, "a collision's identity is exactly "
                        "{collided_id}, the engine's own")
        return
    yield from _id(identity["collided_id"], "/identity/collided_id", rule)


def _writable(value: int) -> bool:
    """Whether `json.dumps` can write this integer: Python refuses one longer
    than its integer-string conversion limit (4300 digits by default), with a
    `ValueError`. So a checked finding always serializes."""
    if value.bit_length() <= 64:
        return True
    try:
        str(value)
    except ValueError:
        return False
    return True


def _line(value: Any) -> bool:
    """A whole number no less than 1: JSON's integer, which 12.0 is too."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 1
    return isinstance(value, float) and value.is_integer() and value >= 1


def _locator(value: Any) -> Iterator[Violation]:
    if not isinstance(value, dict):
        yield Violation("locator-keys", _AT_LOCATOR, f"is {_type(value)}, not an object")
        return
    keys = set(value)
    if not keys or keys - {"line_start", "line_end", "target"}:
        yield Violation("locator-keys", _AT_LOCATOR, "carries line_start and line_end "
                        "together, target, or both, and no other key")
    elif ("line_start" in keys) != ("line_end" in keys):
        yield Violation("locator-keys", _AT_LOCATOR, "carries line_start and line_end "
                        "together or neither")
    for key in ("line_start", "line_end"):
        if key not in value:
            continue
        line = value[key]
        # a bool is an int Python can always write; `_line()` refuses it next
        if isinstance(line, int) and not _writable(line):
            yield Violation(NOT_JSON, f"/locator/{key}", "is an integer too long to write "
                            "as text")
        elif not _line(line):
            yield Violation("locator-line-is-a-line-number", f"/locator/{key}",
                            f"is not a whole number no less than 1 ({_type(line)})")
    if "target" in value:
        yield from _target(value["target"])


def _target(target: Any) -> Iterator[Violation]:
    if not isinstance(target, str) or not target or _text_problem(target):
        yield Violation("locator-target-is-short-text", _AT_TARGET,
                        f"is not text of 1 to {STRING_MAX} characters free of lone "
                        f"surrogates ({_type(target)})")
    elif _NUL in target:
        yield Violation(NO_NUL, _AT_TARGET, _NUL_DETAIL)


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
        "resolution_class": lambda v: _one_of(v, RESOLUTION_CLASSES, _AT_RESOLUTION_CLASS,
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
        yield Violation("pathless-finding-is-human-only", _AT_RESOLUTION_CLASS,
                        "a pathless finding names no document a repair could edit, so it "
                        "is human-only")
    if finding.get("kind") == IDENTITY_COLLISION:
        yield Violation("identity-collision-is-human-only", _AT_RESOLUTION_CLASS,
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
        # finding_id() is the ONE hash path (the holder's `6069507373`, T046
        # item 2), looked up at call time: a test that patches
        # `health_contract.finding_id` patches this check and make_finding() alike.
        want = finding_id(identity=finding["identity"], kind=finding["kind"],
                          pack_id=finding["pack_id"], path=finding["path"]).rsplit(".", 1)[1]
        have = finding["id"].rsplit(".", 1)[1]
        if have != want:
            yield Violation("id-is-the-hash-of-its-key", "/id",
                            f"the hash is {have}, and the finding's key hashes to {want}")
    locator = finding.get("locator") if "locator" not in broken else None
    if isinstance(locator, dict) and "line_start" in locator and "line_end" in locator:
        start, end = locator["line_start"], locator["line_end"]
        if end < start:
            # The lines are not quoted: a refusal names no value of the finding,
            # and a line may be any integer JSON can write.
            yield Violation("locator-span-is-ordered", "/locator/line_end",
                            "line_end is less than line_start, so the span ends before "
                            "it starts")


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


def engine_finding(category: str, entry: str = "", *, pack_version: str, severity: str,
                   message: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """An install-level or pre-run finding, as the engine raises it (the
    holder's `6069024023` item 1). Its `kind` is its category, its `path` is
    empty, its identity is `{category, entry}`, and it is human-only. Its
    `pack_id` is the one its category fixes (`6072086385` item 1): for
    `ENTRY_CATEGORIES`, `entry`, the manifest entry's id, which is never empty
    and never `opendox`; for every other category, `opendox`. An
    install-level category (`INSTALL_CATEGORIES`) takes entry "", and a
    non-empty one is refused (`6072197564` (e)). `pack_version` is that pack's: the
    entry's version, or the installed version for `opendox`. The reasons ride
    in `evidence`, so a run raises one such finding per category and entry,
    and it keeps one id across runs."""
    identity = pathless_identity(category, entry)
    pack_id = entry if category in ENTRY_CATEGORIES else OPENDOX
    return make_finding(kind=category, pack_id=pack_id, pack_version=pack_version, path="",
                        identity=identity, severity=severity, resolution_class=HUMAN_ONLY,
                        message=message, evidence=evidence)


def to_json(finding: dict[str, Any]) -> str:
    """The finding as this module serializes it: checked whole, then canonical
    JSON (sorted keys, no whitespace, each character as itself). Nothing the
    contract refuses is ever written."""
    check_finding(finding)
    return canonical_json(finding).decode("utf-8")


# ===========================================================================
# THE PACK PROTOCOL (plan 038 T045, G15-A; #1144 15.1 and 15.2; decisions
# N-3, OQ-H15-1, OQ-H15-10 and OQ-H15-11; R2Q18 (a) and R2Q20 (a); the
# holder's rulings `openxFactory#656` `6028138991`, `6065680005`,
# `6069024023` item 1, `6072086385` items 3 and 4, and `6086098003` item 1)
# ===========================================================================
#
# Appended below T041's finding vocabulary: one stdlib-only contract module
# (N-3), handed over at T041's landing. Nothing above this line is T045's.
#
# WHAT A PACK IS (15.1; OQ-H15-1). A Python package, the only pack runtime,
# that the engine runs in a sandbox through its shim. It conforms to
# `CheckPack` STRUCTURALLY, on `corpus_adapter.py`'s pattern: a
# `runtime_checkable` Protocol with a CLOSED member set (`PACK_MEMBERS`), so a
# pack authored elsewhere conforms without importing openDox's tooling. Its one
# member, `check`, takes the read-only export's root and nothing else: no model,
# no binding and no network (R2Q20 (a): pack checks are model-free).
#
# THE STATIC DECLARATION, READ BEFORE ANY PACK CODE RUNS (15.2; OQ-H15-10).
# `opendox-pack.yaml`, inside the pack, names the pack's id and version (both
# the manifest entry's), its families with each one's `kind`, own `version` and
# `applies_to` globs, and each family's optional label. No family declares one
# of `ENGINE_KINDS`, the kinds only the engine raises, so no pack can forge an
# engine finding (`6069024023` item 1; `6086098003` item 1). This module imports the
# standard library alone (`6028138991`), so it never parses YAML: the engine's
# manifest reader (T047) reads at most `PACK_DECLARATION_MAX_BYTES`, passes them
# through `decode_pack_declaration()`, parses the text with `yaml.safe_load`,
# and hands the result to `check_pack_declaration()` (`6065680005` item 1). The
# check judges every type it is handed, because YAML gives more than text: a
# float for `1.10`, a date, `True` for a `yes:` key.
#
# THE OUTPUT: ONE JSON DOCUMENT ON STDOUT (OQ-H15-11). `{"findings": [...]}`,
# each a finding in the neutral shape without the fields the engine stamps,
# and optionally a `patch`. `check_pack_output()` admits it WHOLE or refuses it
# WHOLE (`6065680005` item 2): one finding against the pack says why, and none
# of the output is stored, as 15.6 has it for output the engine cannot read.
# A pack's own `id` is IGNORED, because the engine computes every id; a pack's
# `pack_id`, `pack_version` or `baseline_class` is REFUSED, because they are
# provenance the engine stamps (15.7; `6065680005` item 3): T041's
# `IGNORED_FIELDS` and `STAMPED_FIELDS`. A pack finding names a document, so an
# empty `path` is refused: a pathless finding is the engine's alone
# (`6069024023` item 1). A string carrying U+0000, which no stored finding can
# hold, refuses the output whole too (`6072086385` item 4). stderr is no input
# here: the engine records only its size and digest (T056).
#
# THE PATCH TYPE: A UNIFIED DIFF AND NOTHING ELSE (15.2; ADV-12).
# `unified_diff_problem()` says whether a value is one. It admits git's
# extended headers, so the patch validator (T049), which calls it first, can
# refuse a rename, a mode change or a binary patch by its own rule; and a patch
# that is not a diff is refused PER PATCH, there, never by refusing the output
# (`6065680005` item 4). The size bound is 15.2a's, and T049's.
#
# A REFUSAL IS A FINDING AGAINST THE PACK (15.5, 15.6). `PackRefused` carries a
# `PackRefusal`, whose `finding()` is T041's `engine_finding()` for the
# category `declaration-refused` or `pack-output-refused`, two of
# `ENTRY_CATEGORIES`: pathless, `human-only`, `identity` `{category, entry}`,
# and `pack_id` and `pack_version` the manifest entry's (`6072086385` item 1).
# One such finding per category and entry in a run, so its id is stable across
# runs, and the reason rides in `evidence`. It quotes nothing of the pack: its
# evidence holds the reason, indexes, the engine's own words and rule ids, a
# name only where it is a short lowercase word, and a size and a digest.

from typing import Iterable, Protocol, runtime_checkable  # noqa: E402 - T045's section (the cli.py:1693 form)
import functools  # noqa: E402

__all__ += [
    "CheckPack",
    "DECLARATION_REASONS",
    "DECLARATION_REFUSED",
    "FORBIDDEN_DECLARATION_KEYS",
    "OUTPUT_REASONS",
    "OUTPUT_REFUSED",
    "PACK_DECLARATION_FILE",
    "PACK_DECLARATION_KEYS",
    "PACK_DECLARATION_KIND",
    "PACK_DECLARATION_MAX_BYTES",
    "PACK_FAMILY_KEYS",
    "PACK_FAMILY_REQUIRED",
    "PACK_FINDING_FIELDS",
    "PACK_MEMBERS",
    "PACK_OUTPUT_KEYS",
    "PACK_PROTOCOL_VERSION",
    "PACK_REQUIRED_FIELDS",
    "PATCH_FIELD",
    "PackDeclaration",
    "PackFamily",
    "PackFinding",
    "PackRefusal",
    "PackRefused",
    "check_pack_declaration",
    "check_pack_output",
    "decode_pack_declaration",
    "encode_pack_output",
    "glob_problem",
    "path_applies",
    "unified_diff_problem",
]

#: The closed member set of `CheckPack`. A companion test reads
#: `CheckPack.__protocol_attrs__` against it, so growing the surface is a
#: two-file act somebody has to mean.
PACK_MEMBERS: tuple[str, ...] = ("check",)


@runtime_checkable
class CheckPack(Protocol):
    """One method, and nothing else, ever: see `PACK_MEMBERS`."""

    def check(self, corpus: str) -> Iterable[Mapping[str, Any]]:
        """The pack's findings over the read-only export whose root is
        `corpus`, each a mapping in the shape `check_pack_output()` admits.
        The engine's shim writes them to stdout as one document."""


#: The declaration's file, at the root of the pack's pinned tree.
PACK_DECLARATION_FILE = "opendox-pack.yaml"

#: Its `kind`, and the protocol version its `schema_version` names: the
#: version of this whole protocol, the declaration and the output alike.
PACK_DECLARATION_KIND = "opendox-pack"
PACK_PROTOCOL_VERSION = 1

#: The most bytes of a declaration the engine reads and decodes; 15.2a's
#: patch bound, and the order of the server's own body bound.
PACK_DECLARATION_MAX_BYTES = 65_536

#: The declaration's keys, all required, and a family's, `label` optional.
PACK_DECLARATION_KEYS: tuple[str, ...] = ("schema_version", "kind", "id", "version",
                                          "families")
PACK_FAMILY_KEYS: tuple[str, ...] = ("kind", "version", "applies_to", "label")
PACK_FAMILY_REQUIRED: tuple[str, ...] = ("kind", "version", "applies_to")

#: Keys refused BY NAME, at either level: a pack never redefines the classes,
#: the baseline or who may land (requirement 16; 15.5).
FORBIDDEN_DECLARATION_KEYS: tuple[str, ...] = ("baseline", "landing", "classes")

#: The two categories a refusal here is filed under (T041's `CATEGORIES`).
DECLARATION_REFUSED = "declaration-refused"
OUTPUT_REFUSED = "pack-output-refused"

#: The output document's one key, and what a pack's finding may carry: the
#: fields it owns, beside T041's `IGNORED_FIELDS` (its `id`, ignored) and
#: `STAMPED_FIELDS` (refused), and a `patch`.
PACK_OUTPUT_KEYS: tuple[str, ...] = ("findings",)
PATCH_FIELD = "patch"
PACK_FINDING_FIELDS: tuple[str, ...] = tuple(
    field for field in FIELDS if field not in IGNORED_FIELDS + STAMPED_FIELDS)
PACK_REQUIRED_FIELDS: tuple[str, ...] = (
    "kind", "path", "identity", "severity", "resolution_class", "message")

#: Every reason a declaration is refused for, in the engine's own words.
DECLARATION_REASONS: dict[str, str] = {
    "declaration-too-large": f"it is larger than {PACK_DECLARATION_MAX_BYTES} bytes",
    "declaration-not-utf8": "it is not UTF-8 text",
    "declaration-not-yaml": "it is not YAML the engine can read",
    "declaration-not-a-mapping": "it is not a mapping",
    "key-not-text": "a key is not text",
    "forbidden-key": "it declares a rule only the engine owns",
    "unknown-key": "it carries a key the declaration does not name",
    "missing-schema-version": "it has no schema_version",
    "missing-kind": "it has no kind",
    "missing-id": "it has no id",
    "missing-version": "it declares no version",
    "missing-families": "it declares no families",
    "schema-version-unsupported": f"its schema_version is not {PACK_PROTOCOL_VERSION}",
    "kind-not-opendox-pack": f"its kind is not {PACK_DECLARATION_KIND}",
    "id-not-a-name": f"its id is not a name of 1 to {NAME_MAX} lowercase letters, digits "
                     "and hyphens",
    "id-differs-from-entry": "its id is not its manifest entry's",
    "version-not-text": "its version is not text (quote a version such as 1.10)",
    "version-differs-from-entry": "its version is not its manifest entry's",
    "families-not-a-list": "its families are not a list",
    "no-families": "it declares no family",
    "family-not-a-mapping": "a family is not a mapping",
    "family-missing-kind": "a family has no kind",
    "family-missing-version": "a family has no version",
    "family-missing-applies-to": "a family has no applies_to",
    "family-kind-not-a-name": f"a family's kind is not a name of 1 to {NAME_MAX} lowercase "
                              "letters, digits and hyphens",
    "family-kind-reserved": "a family's kind is one of the engine's own",
    "family-kind-repeated": "two families share a kind",
    "family-version-not-text": f"a family's version is not text of 1 to {STRING_MAX} "
                               "characters",
    "family-applies-to-empty": "a family's applies_to is not a list of one glob or more",
    "family-label-not-text": f"a family's label is not one line of 1 to {STRING_MAX} "
                             "characters",
    "glob-not-text": f"a glob is not text of 1 to {STRING_MAX} characters",
    "glob-not-corpus-relative": "a glob starts at a root or a drive, or holds a backslash",
    "glob-bad-segment": "a glob has an empty, . or .. segment",
    "glob-unsupported-syntax": "a glob uses a class, a brace or a ** inside a segment",
}

#: Every reason a pack's output is refused for, in the engine's own words.
OUTPUT_REASONS: dict[str, str] = {
    "output-not-utf8": "its stdout is not UTF-8 text",
    "output-not-one-json-document": "its stdout is not one JSON document",
    "output-envelope": "its document is not exactly {findings: [...]}",
    "finding-not-an-object": "a finding is not an object",
    "finding-key-not-text": "a finding has a field name that is not text",
    "finding-claims-an-engine-field": "a finding supplies a field only the engine stamps",
    "finding-unknown-field": "a finding carries a field the contract does not name",
    "finding-missing-field": "a finding lacks a field the contract requires",
    "finding-names-no-document": "a finding names no document",
    "undeclared-kind": "a finding is of a kind its declaration does not list",
    "outside-applies-to": "a finding's path matches none of its family's globs",
    "finding-shape": "a finding breaks a rule of the neutral shape",
}

#: A name a refusal may repeat: short, lowercase, and never a passage.
_SAFE_WORD = re.compile(r"[a-z0-9_-]{1,40}")
_GLOB_SYNTAX = re.compile(r"[\[\]{}]")


class PackFamily(NamedTuple):
    """One family a pack declares: its kind, its own version, the globs of
    the documents it applies to, and its optional label."""

    kind: str
    version: str
    applies_to: tuple[str, ...]
    label: str | None


class PackDeclaration(NamedTuple):
    """A declaration `check_pack_declaration()` admitted."""

    id: str
    version: str
    families: tuple[PackFamily, ...]

    def family(self, kind: Any) -> PackFamily | None:
        """The family declaring `kind`, or None."""
        for declared in self.families:
            if declared.kind == kind:
                return declared
        return None


class PackFinding(NamedTuple):
    """One finding of an admitted output: the finding, stamped and checked
    whole, and the patch the pack proposed for it, unjudged (T049's)."""

    finding: dict[str, Any]
    proposes_patch: bool
    patch: Any


class PackRefusal(NamedTuple):
    """Why a pack's declaration or output is refused, against which manifest
    entry. `where` holds indexes, rule ids and safe names only."""

    category: str
    reason: str
    entry: str
    version: str
    where: Mapping[str, Any]

    def finding(self) -> dict[str, Any]:
        """The engine's finding against the pack, T041's `engine_finding()`:
        pathless, `human-only`, attributed to the manifest entry, and checked
        whole."""
        if self.category == DECLARATION_REFUSED:
            lead, words = "the pack's declaration is refused", DECLARATION_REASONS
        else:
            lead, words = "the pack's output is refused, and none of it is stored", OUTPUT_REASONS
        return engine_finding(self.category, self.entry, pack_version=self.version,
                              severity="error", message=f"{lead}: {words[self.reason]}",
                              evidence={"reason": self.reason, **self.where})


class PackRefused(ValueError):
    """A declaration or an output refused; `refusal.finding()` is what the
    engine records."""

    def __init__(self, refusal: PackRefusal) -> None:
        self.refusal = refusal
        detail = ", ".join(f"{key}={value}" for key, value in refusal.where.items())
        super().__init__(f"{refusal.category}: {refusal.reason}"
                         + (f" ({detail})" if detail else ""))


def _refuse(category: str, reason: str, entry: str, version: str, **where: Any) -> PackRefused:
    words = DECLARATION_REASONS if category == DECLARATION_REFUSED else OUTPUT_REASONS
    if reason not in words:
        raise KeyError(reason)
    return PackRefused(PackRefusal(category, reason, entry, version, dict(where)))


def _safe(label: str, value: Any) -> dict[str, str]:
    """`{label: value}` when `value` is a short lowercase word; else nothing,
    so a refusal never repeats what a pack wrote at length."""
    return {label: value} if isinstance(value, str) and _SAFE_WORD.fullmatch(value) else {}


def _is_name(value: Any) -> bool:
    return isinstance(value, str) and bool(_NAME.fullmatch(value)) and len(value) <= NAME_MAX


def _is_version(value: Any, limit: int | None = None) -> bool:
    """T041's `pack-version-is-text`: non-empty text free of control
    characters and lone surrogates; at most `limit` characters when given."""
    return (isinstance(value, str) and value != "" and not _CONTROL.search(value)
            and (limit is None or len(value) <= limit))


# ---------------------------------------------------------------------------
# the globs a family applies to
# ---------------------------------------------------------------------------

def glob_problem(pattern: Any) -> str | None:
    """None when `pattern` is a glob this protocol admits; else the reason.

    A glob is corpus-relative and `/`-separated. `*` matches any characters
    but `/`, `?` one character but `/`, and a whole segment `**` any number
    of segments (one or more when it is the last). Every other character is
    itself. A class, a brace, or `**` inside a segment is refused, so no glob
    means something it does not say."""
    if not isinstance(pattern, str) or not pattern or len(pattern) > STRING_MAX \
            or _CONTROL.search(pattern):
        return "glob-not-text"
    if pattern.startswith("/") or _DRIVE.match(pattern) or "\\" in pattern:
        return "glob-not-corpus-relative"
    segments = pattern.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return "glob-bad-segment"
    if _GLOB_SYNTAX.search(pattern) or any("**" in s and s != "**" for s in segments):
        return "glob-unsupported-syntax"
    return None


@functools.lru_cache(maxsize=1024)
def _glob(pattern: str) -> re.Pattern[str]:
    segments = pattern.split("/")
    parts: list[str] = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            parts.append(r"[^/]+(?:/[^/]+)*" if last else r"(?:[^/]+/)*")
            continue
        piece = "".join(r"[^/]*" if char == "*" else r"[^/]" if char == "?"
                        else re.escape(char) for char in segment)
        parts.append(piece if last else piece + "/")
    return re.compile("".join(parts), re.DOTALL)


def path_applies(globs: Iterable[str], path: str) -> bool:
    """Whether `path` matches one of `globs` WHOLE (so `*.md` is a top-level
    document's). Each glob must be one `glob_problem()` admits."""
    for pattern in globs:
        if glob_problem(pattern) is not None:
            raise ValueError("a glob the protocol does not admit")
        if _glob(pattern).fullmatch(path):
            return True
    return False


# ---------------------------------------------------------------------------
# the declaration
# ---------------------------------------------------------------------------

def decode_pack_declaration(raw: bytes, *, entry_id: str, entry_version: str) -> str:
    """The declaration's text, for the engine to parse: at most
    `PACK_DECLARATION_MAX_BYTES`, and UTF-8. Refuses with `PackRefused`."""
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("decode_pack_declaration() takes the file's bytes")
    if len(raw) > PACK_DECLARATION_MAX_BYTES:
        raise _refuse(DECLARATION_REFUSED, "declaration-too-large", entry_id, entry_version,
                      bytes=len(raw))
    try:
        return bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse(DECLARATION_REFUSED, "declaration-not-utf8", entry_id,
                      entry_version) from None


def _keys(mapping: dict[Any, Any], allowed: tuple[str, ...], required: tuple[str, ...],
          missing_prefix: str, refuse: Any, where: dict[str, Any]) -> None:
    if any(not isinstance(key, str) for key in mapping):
        raise refuse("key-not-text", **where)
    for key in FORBIDDEN_DECLARATION_KEYS:
        if key in mapping:
            raise refuse("forbidden-key", key=key, **where)
    for key in mapping:
        if key not in allowed:
            raise refuse("unknown-key", **_safe("key", key), **where)
    for key in required:
        if key not in mapping:
            raise refuse(missing_prefix + key.replace("_", "-"), **where)


def check_pack_declaration(document: Any, *, entry_id: str,
                           entry_version: str) -> PackDeclaration:
    """The declaration, admitted, or `PackRefused` naming the first reason.

    `document` is what the engine parsed from `opendox-pack.yaml`; this
    module parses nothing. `entry_id` and `entry_version` are the manifest
    entry's, which the declaration's id and version must equal (15.1a)."""
    def refuse(reason: str, **where: Any) -> PackRefused:
        return _refuse(DECLARATION_REFUSED, reason, entry_id, entry_version, **where)

    if not isinstance(document, dict):
        raise refuse("declaration-not-a-mapping")
    _keys(document, PACK_DECLARATION_KEYS, PACK_DECLARATION_KEYS, "missing-", refuse, {})
    schema_version = document["schema_version"]
    if isinstance(schema_version, bool) or schema_version != PACK_PROTOCOL_VERSION \
            or not isinstance(schema_version, int):
        raise refuse("schema-version-unsupported")
    if document["kind"] != PACK_DECLARATION_KIND:
        raise refuse("kind-not-opendox-pack")
    if not _is_name(document["id"]):
        raise refuse("id-not-a-name")
    if document["id"] != entry_id:
        raise refuse("id-differs-from-entry")
    if not _is_version(document["version"]):
        raise refuse("version-not-text")
    if document["version"] != entry_version:
        raise refuse("version-differs-from-entry")
    families = document["families"]
    if not isinstance(families, list):
        raise refuse("families-not-a-list")
    if not families:
        raise refuse("no-families")
    admitted: list[PackFamily] = []
    for index, family in enumerate(families):
        where = {"family": index}
        if not isinstance(family, dict):
            raise refuse("family-not-a-mapping", **where)
        _keys(family, PACK_FAMILY_KEYS, PACK_FAMILY_REQUIRED, "family-missing-", refuse, where)
        kind = family["kind"]
        if not _is_name(kind):
            raise refuse("family-kind-not-a-name", **where)
        if kind in ENGINE_KINDS:
            raise refuse("family-kind-reserved", kind=kind, **where)
        if any(seen.kind == kind for seen in admitted):
            raise refuse("family-kind-repeated", kind=kind, **where)
        if not _is_version(family["version"], STRING_MAX):
            raise refuse("family-version-not-text", **where)
        globs = family["applies_to"]
        if not isinstance(globs, list) or not globs:
            raise refuse("family-applies-to-empty", **where)
        for position, pattern in enumerate(globs):
            problem = glob_problem(pattern)
            if problem is not None:
                raise refuse(problem, glob=position, **where)
        label = family.get("label")
        if label is not None and (not isinstance(label, str) or not label
                                  or len(label) > STRING_MAX or _NOT_ONE_LINE.search(label)):
            raise refuse("family-label-not-text", **where)
        admitted.append(PackFamily(kind, family["version"], tuple(globs), label))
    return PackDeclaration(document["id"], document["version"], tuple(admitted))


# ---------------------------------------------------------------------------
# the output
# ---------------------------------------------------------------------------

def _no_repeated_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("a key is given twice in one object")
        document[key] = value
    return document


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON number")


def _finite(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("a number JSON cannot write")
    return value


def encode_pack_output(findings: Iterable[Mapping[str, Any]]) -> bytes:
    """The one document a pack's shim writes to stdout: `{"findings": [...]}`,
    UTF-8, no NaN or infinity, one line."""
    return (json.dumps({"findings": list(findings)}, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def check_pack_output(stdout: bytes, declaration: PackDeclaration, *, entry_id: str,
                      entry_version: str) -> tuple[PackFinding, ...]:
    """The pack's findings, each stamped and checked whole, or `PackRefused`
    for the WHOLE output, naming its first reason (`6065680005` item 2).

    The engine stamps `pack_id` and `pack_version` from the manifest entry,
    the family's declared version into `evidence.family_version`, and the id by
    T041's rule; a pack's own `id` is ignored, and its `pack_id`,
    `pack_version` or `baseline_class` is refused."""
    def refuse(reason: str, **where: Any) -> PackRefused:
        return _refuse(OUTPUT_REFUSED, reason, entry_id, entry_version, **where)

    measured = {"bytes": len(stdout), "sha256": hashlib.sha256(stdout).hexdigest()}
    try:
        text = bytes(stdout).decode("utf-8")
    except UnicodeDecodeError:
        raise refuse("output-not-utf8", **measured) from None
    try:
        document = json.loads(text, object_pairs_hook=_no_repeated_keys,
                              parse_constant=_no_constant, parse_float=_finite)
    except (ValueError, RecursionError):
        raise refuse("output-not-one-json-document", **measured) from None
    if (not isinstance(document, dict) or tuple(document) != PACK_OUTPUT_KEYS
            or not isinstance(document["findings"], list)):
        raise refuse("output-envelope")
    admitted: list[PackFinding] = []
    for index, item in enumerate(document["findings"]):
        where = {"finding": index}
        if not isinstance(item, dict):
            raise refuse("finding-not-an-object", **where)
        for field in STAMPED_FIELDS:
            if field in item:
                raise refuse("finding-claims-an-engine-field", field=field, **where)
        for key in item:
            if key not in PACK_FINDING_FIELDS + IGNORED_FIELDS + (PATCH_FIELD,):
                raise refuse("finding-unknown-field", **_safe("field", key), **where)
        for field in PACK_REQUIRED_FIELDS:
            if field not in item:
                raise refuse("finding-missing-field", field=field, **where)
        family = declaration.family(item["kind"])
        if family is None:
            raise refuse("undeclared-kind", **_safe("kind", item["kind"]), **where)
        path = item["path"]
        if path == "":
            raise refuse("finding-names-no-document", kind=family.kind, **where)
        if not isinstance(path, str):
            raise refuse("finding-shape", rule="path-is-corpus-relative", **where)
        if not path_applies(family.applies_to, path):
            raise refuse("outside-applies-to", kind=family.kind, **where)
        if "locator" in item and not isinstance(item["locator"], dict):
            raise refuse("finding-shape", rule="locator-keys", **where)
        evidence = item.get("evidence", {})
        if not isinstance(evidence, dict):
            raise refuse("finding-shape", rule="evidence-is-an-object", **where)
        try:
            finding = make_finding(
                kind=family.kind, pack_id=entry_id, pack_version=entry_version, path=path,
                identity=item["identity"], severity=item["severity"],
                resolution_class=item["resolution_class"], message=item["message"],
                evidence={**evidence, "family_version": family.version},
                locator=item.get("locator"))
        except FindingRefused as refused:
            raise refuse("finding-shape", rule=refused.rule, **where) from None
        admitted.append(PackFinding(finding, PATCH_FIELD in item, item.get(PATCH_FIELD)))
    return tuple(admitted)


# ---------------------------------------------------------------------------
# the patch type
# ---------------------------------------------------------------------------

_HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?")
_EXTENDED_HEADER = re.compile(
    r"(?:old mode|new mode|deleted file mode|new file mode) [0-7]{6}"
    r"|(?:copy|rename) (?:from|to) .+"
    r"|(?:similarity|dissimilarity) index \d{1,3}%"
    r"|index [0-9a-f]{4,64}\.\.[0-9a-f]{4,64}(?: [0-7]{6})?")


def unified_diff_problem(patch: Any) -> str | None:
    """None when `patch` is a unified diff and nothing else; else the reason.

    The diff may carry git's headers (`diff --git`, `index`, the mode,
    rename and copy lines, a binary patch): they are a diff's, and the patch
    validator refuses those it must by its own rules (15.2a, T049). What is
    refused here is what is no diff at all: replacement text, prose around a
    diff, a hunk whose lines do not add up, a file with no hunk."""
    if not isinstance(patch, str):
        return "patch-not-text"
    if not patch:
        return "patch-empty"
    if not patch.endswith("\n"):
        return "patch-no-final-newline"
    lines = patch[:-1].split("\n")
    at, files = 0, 0
    while at < len(lines):
        git = lines[at].startswith("diff --git ")
        if git:
            at += 1
            while at < len(lines) and _EXTENDED_HEADER.fullmatch(lines[at]):
                at += 1
        if git and at < len(lines) and (lines[at] == "GIT binary patch"
                                        or lines[at].startswith("Binary files ")):
            at += 1
            while at < len(lines) and not lines[at].startswith("diff --git "):
                at += 1
            files += 1
            continue
        if at + 1 < len(lines) and lines[at].startswith("--- ") \
                and lines[at + 1].startswith("+++ "):
            at += 2
        elif git and (at == len(lines) or lines[at].startswith("diff --git ")):
            files += 1  # a rename or a mode change alone: no hunk to carry
            continue
        else:
            return "patch-not-a-unified-diff"
        hunks = 0
        while at < len(lines) and lines[at].startswith("@@"):
            header = _HUNK_HEADER.fullmatch(lines[at])
            if header is None:
                return "patch-bad-hunk-header"
            old = 1 if header.group(2) is None else int(header.group(2))
            new = 1 if header.group(4) is None else int(header.group(4))
            at += 1
            while old > 0 or new > 0:
                if at == len(lines):
                    return "patch-hunk-short"
                line = lines[at]
                if line.startswith("\\ "):
                    pass
                elif line == "" or line.startswith(" "):
                    old, new = old - 1, new - 1
                elif line.startswith("-"):
                    old -= 1
                elif line.startswith("+"):
                    new -= 1
                else:
                    return "patch-hunk-short"
                at += 1
            if old < 0 or new < 0:
                return "patch-hunk-short"
            while at < len(lines) and lines[at].startswith("\\ "):
                at += 1
            hunks += 1
        if hunks == 0:
            return "patch-no-hunk"
        files += 1
    return None if files else "patch-not-a-unified-diff"
