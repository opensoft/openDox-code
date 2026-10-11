"""The pack protocol in `opendox.health_contract` (plan 038 T045, G15-A; #1144
15.1 and 15.2; decisions N-3, OQ-H15-1, OQ-H15-10 and OQ-H15-11; R2Q18 (a)
and R2Q20 (a); the holder's rulings `openxFactory#656` `6028138991`,
`6065680005`, `6069024023` item 1, `6072086385` items 3 and 4, and
`6086098003` item 1).

THE FALSIFIER (T045's task text, with `6065680005` item 3's three nodes and
`6072086385` item 3's two):

* a family missing its version, or its `applies_to`, is refused;
* a finding of an undeclared kind, and one outside its family's globs, are
  each refused AS A FINDING AGAINST THE PACK;
* a pack's own `id` is ignored, and its `pack_id`, `pack_version` and
  `baseline_class` are each refused;
* a family that declares an engine kind is refused, and so is a pack finding
  with an empty `path`.

And `6072086385` item 4: a pack finding carrying U+0000, which no stored
finding can hold, refuses the pack's output WHOLE, as `pack-output-refused`.

WHAT ELSE IT HOLDS.

1. THE DECLARATION, as the engine reads it: bytes capped and decoded here,
   parsed by `yaml.safe_load` (this test stands in for T047, which owns that
   read, `6065680005` item 1), and checked here. Every refusal is named, the
   forbidden keys by name at either level.
2. THE GLOBS a family applies to, whole-path, with `**`.
3. THE OUTPUT, one JSON document, admitted whole or refused whole
   (`6065680005` item 2).
4. A REFUSAL IS A FINDING against the manifest entry, admitted by T041's own
   check, and it repeats nothing the pack wrote at length.
5. THE PATCH TYPE: a unified diff, git's headers included (T049 refuses
   those by its own rules), and nothing else.
6. THE PROTOCOL: closed at one member, which takes the export's root alone
   (R2Q20 (a): no model reaches a pack through the contract).

No case skips: `EXPECT_SKIPPED` stays 11.
"""

from __future__ import annotations

import ast
import inspect
import json
import shutil
import subprocess
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest
import yaml

from opendox import health_contract as hc

MODULE = Path(hc.__file__)
ENTRY, VERSION = "house-style", "1.4.0"

DECLARATION = textwrap.dedent("""\
    schema_version: 1
    kind: opendox-pack
    id: house-style
    version: 1.4.0
    families:
      - kind: heading-case
        version: "3"
        applies_to: ["notes/**/*.md", "*.md"]
        label: Heading case
      - kind: front-matter
        version: "1"
        applies_to: ["**"]
    """)


def _read(text: str | bytes, *, entry: str = ENTRY, version: str = VERSION) -> hc.PackDeclaration:
    """The engine's read, as T047 makes it: decode, `yaml.safe_load`, check."""
    raw = text.encode("utf-8") if isinstance(text, str) else text
    decoded = hc.decode_pack_declaration(raw, entry_id=entry, entry_version=version)
    return hc.check_pack_declaration(yaml.safe_load(decoded), entry_id=entry,
                                     entry_version=version)


def _document(**changes: Any) -> dict[str, Any]:
    document = yaml.safe_load(DECLARATION)
    for key, value in changes.items():
        if value is _DROP:
            document.pop(key)
        else:
            document[key] = value
    return document


def _family(index: int = 0, **changes: Any) -> dict[str, Any]:
    document = _document()
    family = document["families"][index]
    for key, value in changes.items():
        if value is _DROP:
            family.pop(key)
        else:
            family[key] = value
    return document


_DROP = object()


def _refused(document: Any) -> hc.PackRefusal:
    with pytest.raises(hc.PackRefused) as caught:
        hc.check_pack_declaration(document, entry_id=ENTRY, entry_version=VERSION)
    refusal = caught.value.refusal
    assert refusal.category == hc.DECLARATION_REFUSED
    return refusal


DECLARED = _read(DECLARATION)


def _finding(**changes: Any) -> dict[str, Any]:
    finding = {"kind": "heading-case", "path": "notes/plan.md",
               "identity": {"heading": "seasonal-specials"},
               "locator": {"line_start": 3, "line_end": 3}, "severity": "info",
               "resolution_class": "assisted", "message": "a heading is not in the house case",
               "evidence": {"lines": [3, 3]}}
    for key, value in changes.items():
        if value is _DROP:
            finding.pop(key)
        else:
            finding[key] = value
    return finding


def _output(*findings: dict[str, Any]) -> bytes:
    return json.dumps({"findings": list(findings)}).encode("utf-8")


def _check(stdout: bytes) -> tuple[hc.PackFinding, ...]:
    return hc.check_pack_output(stdout, DECLARED, entry_id=ENTRY, entry_version=VERSION)


def _output_refused(stdout: bytes) -> hc.PackRefusal:
    with pytest.raises(hc.PackRefused) as caught:
        _check(stdout)
    refusal = caught.value.refusal
    assert refusal.category == hc.OUTPUT_REFUSED
    return refusal


def _is_a_finding_against_the_pack(refusal: hc.PackRefusal) -> dict[str, Any]:
    """The refusal's finding: the engine's, pathless, attributed to the
    manifest entry, and admitted by T041's whole-finding check."""
    finding = refusal.finding()
    hc.check_finding(finding)
    assert (finding["pack_id"], finding["pack_version"]) == (ENTRY, VERSION)
    assert finding["path"] == "" and finding["resolution_class"] == hc.HUMAN_ONLY
    assert finding["identity"] == {"category": refusal.category, "entry": ENTRY}
    assert finding["kind"] == refusal.category
    assert finding["evidence"]["reason"] == refusal.reason
    return finding


# ---------------------------------------------------------------------------
# the falsifier
# ---------------------------------------------------------------------------

def test_a_family_missing_its_version_is_refused() -> None:
    refusal = _refused(_family(version=_DROP))
    assert (refusal.reason, refusal.where) == ("family-missing-version", {"family": 0})
    _is_a_finding_against_the_pack(refusal)


def test_a_family_missing_its_applies_to_is_refused() -> None:
    refusal = _refused(_family(1, applies_to=_DROP))
    assert (refusal.reason, refusal.where) == ("family-missing-applies-to", {"family": 1})
    _is_a_finding_against_the_pack(refusal)


def test_a_finding_of_an_undeclared_kind_is_refused_as_a_finding_against_the_pack() -> None:
    refusal = _output_refused(_output(_finding(), _finding(kind="orphan-heading")))
    assert refusal.reason == "undeclared-kind"
    assert refusal.where == {"kind": "orphan-heading", "finding": 1}
    _is_a_finding_against_the_pack(refusal)


def test_a_finding_outside_its_familys_globs_is_refused_as_a_finding_against_the_pack() -> None:
    refusal = _output_refused(_output(_finding(path="archive/plan.md")))
    assert refusal.reason == "outside-applies-to"
    assert refusal.where == {"kind": "heading-case", "finding": 0}
    _is_a_finding_against_the_pack(refusal)


def test_a_packs_own_id_is_ignored() -> None:
    claimed = "house-style.heading-case.0000000000000000"
    (with_id,) = _check(_output(_finding(id=claimed)))
    (without,) = _check(_output(_finding()))
    assert with_id.finding["id"] != claimed
    assert with_id.finding == without.finding


def test_a_pack_supplying_pack_id_is_refused() -> None:
    refusal = _output_refused(_output(_finding(pack_id="opendox")))
    assert (refusal.reason, refusal.where) == (
        "finding-claims-an-engine-field", {"field": "pack_id", "finding": 0})
    _is_a_finding_against_the_pack(refusal)


def test_a_pack_supplying_pack_version_is_refused() -> None:
    refusal = _output_refused(_output(_finding(pack_version=VERSION)))
    assert (refusal.reason, refusal.where) == (
        "finding-claims-an-engine-field", {"field": "pack_version", "finding": 0})
    _is_a_finding_against_the_pack(refusal)


def test_a_pack_supplying_baseline_class_is_refused() -> None:
    refusal = _output_refused(_output(_finding(baseline_class="persistent")))
    assert (refusal.reason, refusal.where) == (
        "finding-claims-an-engine-field", {"field": "baseline_class", "finding": 0})
    _is_a_finding_against_the_pack(refusal)


# ---------------------------------------------------------------------------
# 1. the declaration
# ---------------------------------------------------------------------------

def test_the_data_models_declaration_is_admitted() -> None:
    assert DECLARED == hc.PackDeclaration(ENTRY, VERSION, (
        hc.PackFamily("heading-case", "3", ("notes/**/*.md", "*.md"), "Heading case"),
        hc.PackFamily("front-matter", "1", ("**",), None)))
    assert DECLARED.family("front-matter").version == "1"
    assert DECLARED.family("orphan") is None


def test_the_declaration_is_a_file_of_its_own_kind() -> None:
    assert hc.PACK_DECLARATION_FILE == "opendox-pack.yaml"
    assert (hc.PACK_DECLARATION_KIND, hc.PACK_PROTOCOL_VERSION) == ("opendox-pack", 1)
    assert hc.PACK_DECLARATION_KEYS == ("schema_version", "kind", "id", "version", "families")
    assert hc.PACK_FAMILY_KEYS == ("kind", "version", "applies_to", "label")


def test_a_declaration_with_no_version_is_refused() -> None:
    """fixture-anonymous-pack's case (15.1a: "names another version, or none")."""
    refusal = _refused(_document(version=_DROP))
    assert refusal.reason == "missing-version"
    assert "declares no version" in _is_a_finding_against_the_pack(refusal)["message"]


@pytest.mark.parametrize("version, reason", [
    ("1.4.1", "version-differs-from-entry"),
    (1.4, "version-not-text"),
    (14, "version-not-text"),
    ("", "version-not-text"),
    ("1.4.0\n", "version-not-text"),
    (None, "version-not-text"),
])
def test_a_declared_version_that_is_not_the_entrys_is_refused(version: Any, reason: str) -> None:
    assert _refused(_document(version=version)).reason == reason


def test_a_yaml_version_written_as_a_number_is_refused_and_never_compared_loosely() -> None:
    """`version: 1.10` is the float 1.1 to YAML: refused, never read as text."""
    text = DECLARATION.replace("version: 1.4.0", "version: 1.10")
    with pytest.raises(hc.PackRefused) as caught:
        _read(text, version="1.10")
    assert caught.value.refusal.reason == "version-not-text"
    assert _read(text.replace("version: 1.10", 'version: "1.10"'), version="1.10").version == "1.10"


#: Data-model § Pack declaration's three, spelled here and not read from the
#: module, so dropping one there cannot drop its case here.
FORBIDDEN = ("baseline", "landing", "classes")


def test_the_forbidden_keys_are_the_data_models_three() -> None:
    assert hc.FORBIDDEN_DECLARATION_KEYS == FORBIDDEN


@pytest.mark.parametrize("key", FORBIDDEN)
@pytest.mark.parametrize("level", ["declaration", "family"])
def test_each_forbidden_key_is_refused_by_name(key: str, level: str) -> None:
    document = _document(**{key: "mine"}) if level == "declaration" else _family(**{key: "mine"})
    refusal = _refused(document)
    assert refusal.reason == "forbidden-key"
    assert refusal.where["key"] == key
    assert ("family" in refusal.where) is (level == "family")
    _is_a_finding_against_the_pack(refusal)


def test_a_forbidden_key_is_named_before_any_other_fault() -> None:
    document = _document(classes=["mine"], command="run.sh", version=_DROP)
    assert (_refused(document).reason, _refused(document).where) == (
        "forbidden-key", {"key": "classes"})


@pytest.mark.parametrize("key", ["command", "entrypoint", "runtime", "timeout"])
def test_a_pack_declares_no_executable_and_no_bound(key: str) -> None:
    """OQ-H15-1: Python through the engine's shim is the only pack runtime;
    and the engine's bounds are never the pack's (15.6)."""
    refusal = _refused(_document(**{key: "x"}))
    assert (refusal.reason, refusal.where) == ("unknown-key", {"key": key})


@pytest.mark.parametrize("key", ["Secret Passage " + "q" * 300, "Secret Passage",
                                 "secret passage", "secret\npassage"])
def test_an_unknown_key_that_is_not_a_short_word_is_not_repeated(key: str) -> None:
    refusal = _refused(_document(**{key: "x"}))
    assert (refusal.reason, refusal.where) == ("unknown-key", {})
    assert "passage" not in (json.dumps(refusal.finding())
                             + str(hc.PackRefused(refusal))).lower()


def test_a_key_that_is_not_text_is_refused() -> None:
    """YAML reads `yes:` as the key True."""
    with pytest.raises(hc.PackRefused) as caught:
        _read(DECLARATION + "yes: 1\n")
    assert caught.value.refusal.reason == "key-not-text"


@pytest.mark.parametrize("missing", hc.PACK_DECLARATION_KEYS)
def test_each_required_key_is_required(missing: str) -> None:
    assert _refused(_document(**{missing: _DROP})).reason == \
        "missing-" + missing.replace("_", "-")


@pytest.mark.parametrize("value, reason", [
    (True, "schema-version-unsupported"),
    (2, "schema-version-unsupported"),
    ("1", "schema-version-unsupported"),
    (1.0, "schema-version-unsupported"),
])
def test_the_schema_version_is_the_protocols(value: Any, reason: str) -> None:
    assert _refused(_document(schema_version=value)).reason == reason


def test_the_kind_is_the_declarations() -> None:
    assert _refused(_document(kind="opendox-health-packs")).reason == "kind-not-opendox-pack"


@pytest.mark.parametrize("pack_id, reason", [
    ("other-pack", "id-differs-from-entry"),
    ("House-Style", "id-not-a-name"),
    ("a" * 41, "id-not-a-name"),
    (7, "id-not-a-name"),
])
def test_the_id_is_the_entrys_name(pack_id: Any, reason: str) -> None:
    assert _refused(_document(id=pack_id)).reason == reason


def test_a_40_character_id_is_admitted() -> None:
    entry = "a" * 40
    assert hc.check_pack_declaration(_document(id=entry), entry_id=entry,
                                     entry_version=VERSION).id == entry


@pytest.mark.parametrize("families, reason", [
    ({"kind": "x"}, "families-not-a-list"),
    ([], "no-families"),
    (["heading-case"], "family-not-a-mapping"),
])
def test_the_families_are_a_list_of_mappings(families: Any, reason: str) -> None:
    assert _refused(_document(families=families)).reason == reason


def test_a_family_missing_its_kind_is_refused() -> None:
    assert _refused(_family(kind=_DROP)).reason == "family-missing-kind"


@pytest.mark.parametrize("kind, reason", [
    ("a" * 41, "family-kind-not-a-name"),
    ("Heading", "family-kind-not-a-name"),
    ("", "family-kind-not-a-name"),
    ("front-matter", "family-kind-repeated"),
])
def test_a_familys_kind_is_a_unique_name(kind: str, reason: str) -> None:
    assert _refused(_family(kind=kind)).reason == reason


def test_a_40_character_kind_is_admitted() -> None:
    kind = "k" * 40
    assert hc.check_pack_declaration(_family(kind=kind), entry_id=ENTRY,
                                     entry_version=VERSION).families[0].kind == kind


@pytest.mark.parametrize("kind", sorted(hc.ENGINE_KINDS))
def test_a_family_declaring_an_engine_kind_is_refused(kind: str) -> None:
    """`6069024023` item 1; `6072086385` item 3. Else a pack could raise a
    finding that reads as the engine's: the schema admits a pack-emitted
    identity-collision with {collided_id}."""
    refusal = _refused(_family(kind=kind))
    assert (refusal.reason, refusal.where) == ("family-kind-reserved", {"kind": kind, "family": 0})
    _is_a_finding_against_the_pack(refusal)


def test_a_family_declaring_refused_patch_is_refused() -> None:
    """`6086098003` item 1: `refused-patch` is a PATHED engine kind, and no
    category, so a pack that declared it could forge T049's refusals."""
    assert hc.REFUSED_PATCH == "refused-patch" and hc.REFUSED_PATCH not in hc.CATEGORIES
    refusal = _refused(_family(1, kind="refused-patch"))
    assert (refusal.reason, refusal.where) == (
        "family-kind-reserved", {"kind": "refused-patch", "family": 1})


def test_the_refusals_are_filed_under_t041s_per_entry_categories() -> None:
    assert (hc.DECLARATION_REFUSED, hc.OUTPUT_REFUSED) == (
        "declaration-refused", "pack-output-refused")
    assert {hc.DECLARATION_REFUSED, hc.OUTPUT_REFUSED} <= hc.ENTRY_CATEGORIES
    assert hc.PACK_FINDING_FIELDS == ("kind", "path", "identity", "locator", "severity",
                                      "resolution_class", "message", "evidence")


@pytest.mark.parametrize("version, admitted", [
    ("v" * 200, True), ("v" * 201, False), ("", False), (3, False), ("3\t", False)])
def test_a_familys_version_is_bounded_text(version: Any, admitted: bool) -> None:
    """Stamped into `evidence.family_version`, so it holds evidence's bound."""
    document = _family(version=version)
    if admitted:
        hc.check_pack_declaration(document, entry_id=ENTRY, entry_version=VERSION)
    else:
        assert _refused(document).reason == "family-version-not-text"


@pytest.mark.parametrize("applies_to", [[], "notes/*.md", None])
def test_a_familys_applies_to_is_a_list_of_one_glob_or_more(applies_to: Any) -> None:
    assert _refused(_family(applies_to=applies_to)).reason == "family-applies-to-empty"


@pytest.mark.parametrize("label, admitted", [
    ("Heading case", True), ("l" * 200, True), ("l" * 201, False), ("", False),
    ("two\nlines", False), (["a"], False)])
def test_a_familys_label_is_one_bounded_line(label: Any, admitted: bool) -> None:
    document = _family(label=label)
    if admitted:
        assert hc.check_pack_declaration(document, entry_id=ENTRY,
                                         entry_version=VERSION).families[0].label == label
    else:
        assert _refused(document).reason == "family-label-not-text"


def test_the_declaration_is_capped_and_utf8() -> None:
    padded = DECLARATION + "#" * (hc.PACK_DECLARATION_MAX_BYTES - len(DECLARATION) - 1) + "\n"
    assert len(padded.encode("utf-8")) == hc.PACK_DECLARATION_MAX_BYTES
    assert _read(padded) == DECLARED
    with pytest.raises(hc.PackRefused) as caught:
        _read(padded + "#")
    assert (caught.value.refusal.reason, caught.value.refusal.where) == (
        "declaration-too-large", {"bytes": hc.PACK_DECLARATION_MAX_BYTES + 1})
    with pytest.raises(hc.PackRefused) as caught:
        _read(DECLARATION.encode("utf-8") + b"\xff\n")
    assert caught.value.refusal.reason == "declaration-not-utf8"


def test_a_recursive_yaml_alias_is_refused_never_followed() -> None:
    text = DECLARATION.replace('applies_to: ["**"]', "applies_to: &a [*a]")
    with pytest.raises(hc.PackRefused) as caught:
        _read(text)
    assert (caught.value.refusal.reason, caught.value.refusal.where) == (
        "glob-not-text", {"glob": 0, "family": 1})


def test_a_declaration_that_is_not_a_mapping_is_refused() -> None:
    assert _refused(["a", "list"]).reason == "declaration-not-a-mapping"


def test_the_engine_names_its_own_yaml_refusal() -> None:
    """T047's parse error is filed under this protocol's vocabulary."""
    finding = hc.PackRefusal(hc.DECLARATION_REFUSED, "declaration-not-yaml", ENTRY,
                             VERSION, {}).finding()
    hc.check_finding(finding)


# ---------------------------------------------------------------------------
# 2. the globs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("glob, path, matches", [
    ("notes/**/*.md", "notes/a.md", True),
    ("notes/**/*.md", "notes/x/y/a.md", True),
    ("notes/**/*.md", "notesa.md", False),
    ("notes/**/*.md", "notes/a.txt", False),
    ("*.md", "a.md", True),
    ("*.md", "notes/a.md", False),
    ("**/*.md", "a.md", True),
    ("**/*.md", "x/y/a.md", True),
    ("**", "a", True),
    ("**", "x/y/z.md", True),
    ("notes/**", "notes/a.md", True),
    ("notes/**", "notes", False),
    ("notes/?.md", "notes/a.md", True),
    ("notes/?.md", "notes/ab.md", False),
    ("notes/?.md", "notes//.md", False),
    ("a.md", "a.md", True),
    ("a.md", "A.md", False),
    ("a+b(c).md", "a+b(c).md", True),
    ("a.md", "a_md", False),
    ("*", "", True),
])
def test_a_glob_matches_the_whole_path(glob: str, path: str, matches: bool) -> None:
    assert hc.glob_problem(glob) is None
    assert hc.path_applies([glob], path) is matches


@pytest.mark.parametrize("glob, reason", [
    ("", "glob-not-text"),
    ("g" * 201, "glob-not-text"),
    (3, "glob-not-text"),
    ("notes/\n.md", "glob-not-text"),
    ("/notes/*.md", "glob-not-corpus-relative"),
    ("C:notes/*.md", "glob-not-corpus-relative"),
    ("notes\\*.md", "glob-not-corpus-relative"),
    ("notes//*.md", "glob-bad-segment"),
    ("notes/", "glob-bad-segment"),
    ("./*.md", "glob-bad-segment"),
    ("../*.md", "glob-bad-segment"),
    ("[ab].md", "glob-unsupported-syntax"),
    ("{a,b}.md", "glob-unsupported-syntax"),
    ("notes/**.md", "glob-unsupported-syntax"),
])
def test_a_glob_outside_the_grammar_is_refused(glob: Any, reason: str) -> None:
    assert hc.glob_problem(glob) == reason
    refusal = _refused(_family(applies_to=["*.md", glob]))
    assert (refusal.reason, refusal.where) == (reason, {"glob": 1, "family": 0})


def test_path_applies_refuses_a_glob_it_does_not_admit() -> None:
    with pytest.raises(ValueError):
        hc.path_applies(["[ab].md"], "a.md")


# ---------------------------------------------------------------------------
# 3. the output
# ---------------------------------------------------------------------------

def test_an_admitted_output_is_stamped_by_the_engine() -> None:
    (admitted,) = _check(_output(_finding(evidence={"lines": [3, 3], "family_version": "9"})))
    finding = admitted.finding
    hc.check_finding(finding)
    assert (finding["pack_id"], finding["pack_version"]) == (ENTRY, VERSION)
    assert finding["evidence"] == {"lines": [3, 3], "family_version": "3"}
    assert finding["id"] == hc.finding_id(identity={"heading": "seasonal-specials"},
                                          kind="heading-case", pack_id=ENTRY,
                                          path="notes/plan.md")
    assert (admitted.proposes_patch, admitted.patch) == (False, None)


def test_evidence_is_the_engines_when_a_pack_supplies_none() -> None:
    (admitted,) = _check(_output(_finding(evidence=_DROP)))
    assert admitted.finding["evidence"] == {"family_version": "3"}


def test_the_output_round_trips_through_the_shims_encoding() -> None:
    stdout = hc.encode_pack_output([_finding(), _finding(kind="front-matter", path="x/y.txt",
                                                         identity={})])
    assert stdout.endswith(b"\n") and stdout.count(b"\n") == 1
    assert [f.finding["kind"] for f in _check(stdout)] == ["heading-case", "front-matter"]
    with pytest.raises(ValueError):
        hc.encode_pack_output([{"n": float("nan")}])


def test_an_empty_output_is_admitted_as_no_findings() -> None:
    assert _check(b'{"findings": []}\n') == ()


def test_the_patch_rides_with_its_finding_unjudged() -> None:
    """A patch is T049's to judge, per patch (`6065680005` item 4): even one
    that is no diff leaves the output admitted."""
    (with_patch, no_diff) = _check(_output(_finding(patch="--- a\n"),
                                           _finding(path="notes/b.md", patch={"not": "a diff"})))
    assert (with_patch.proposes_patch, with_patch.patch) == (True, "--- a\n")
    assert (no_diff.proposes_patch, no_diff.patch) == (True, {"not": "a diff"})
    assert "patch" not in with_patch.finding


@pytest.mark.parametrize("stdout, reason", [
    (b"\xff\xfe", "output-not-utf8"),
    (b"", "output-not-one-json-document"),
    (b"Traceback (most recent call last):\n", "output-not-one-json-document"),
    (b'{"findings": []} {"findings": []}', "output-not-one-json-document"),
    (b'{"findings": [], "findings": []}', "output-not-one-json-document"),
    (b'{"findings": [{"kind": "heading-case", "kind": "x"}]}', "output-not-one-json-document"),
    (b'{"findings": [NaN]}', "output-not-one-json-document"),
    (b'{"findings": [1e400]}', "output-not-one-json-document"),
    ("﻿{\"findings\": []}".encode("utf-8"), "output-not-one-json-document"),
    (b"[" * 100_000 + b"]" * 100_000, "output-not-one-json-document"),
    (b"[]", "output-envelope"),
    (b'{"findings": {}}', "output-envelope"),
    (b'{"findings": [], "patches": []}', "output-envelope"),
    (b"{}", "output-envelope"),
])
def test_output_that_is_not_one_document_of_the_shape_is_refused_whole(stdout: bytes,
                                                                        reason: str) -> None:
    refusal = _output_refused(stdout)
    assert refusal.reason == reason
    finding = _is_a_finding_against_the_pack(refusal)
    if reason in ("output-not-utf8", "output-not-one-json-document"):
        assert set(finding["evidence"]) == {"reason", "bytes", "sha256"}


@pytest.mark.parametrize("change, reason, where", [
    ({"kind": _DROP}, "finding-missing-field", {"field": "kind", "finding": 1}),
    ({"identity": _DROP}, "finding-missing-field", {"field": "identity", "finding": 1}),
    ({"path": ""}, "finding-names-no-document", {"kind": "heading-case", "finding": 1}),
    ({"path": ["notes/a.md"]}, "finding-shape", {"rule": "path-is-corpus-relative", "finding": 1}),
    ({"severity": "critical"}, "finding-shape", {"rule": "severity-is-known", "finding": 1}),
    ({"resolution_class": "auto-merge"}, "finding-shape",
     {"rule": "resolution-class-is-one-of-three", "finding": 1}),
    ({"identity": {"line": 3}}, "finding-shape",
     {"rule": "identity-holds-no-number", "finding": 1}),
    ({"evidence": {"excerpt": "a passage"}}, "finding-shape",
     {"rule": "evidence-names-no-text", "finding": 1}),
    ({"evidence": None}, "finding-shape", {"rule": "evidence-is-an-object", "finding": 1}),
    ({"locator": None}, "finding-shape", {"rule": "locator-keys", "finding": 1}),
    ({"message": "m" * 201}, "finding-shape",
     {"rule": "message-is-one-bounded-line", "finding": 1}),
    ({"landing": "auto"}, "finding-unknown-field", {"field": "landing", "finding": 1}),
    ({"path": "notes/../../x.md"}, "finding-shape",
     {"rule": "path-is-corpus-relative", "finding": 1}),
])
def test_one_bad_finding_refuses_the_whole_output(change: dict[str, Any], reason: str,
                                                  where: dict[str, Any]) -> None:
    refusal = _output_refused(_output(_finding(), _finding(**change)))
    assert (refusal.reason, refusal.where) == (reason, where)
    _is_a_finding_against_the_pack(refusal)


@pytest.mark.parametrize("item", [[], "a finding", None, 3])
def test_a_finding_that_is_not_an_object_is_refused(item: Any) -> None:
    refusal = _output_refused(_output(item))
    assert (refusal.reason, refusal.where) == ("finding-not-an-object", {"finding": 0})


def test_a_pack_finding_with_an_empty_path_is_refused() -> None:
    """`6069024023` item 1; `6072086385` item 3: a pathless finding is the
    engine's alone, so a pack's finding names a document."""
    refusal = _output_refused(_output(_finding(path="")))
    assert (refusal.reason, refusal.where) == (
        "finding-names-no-document", {"kind": "heading-case", "finding": 0})
    _is_a_finding_against_the_pack(refusal)


@pytest.mark.parametrize("change, rule", [
    ({"identity": {"heading": "a\u0000b"}}, "text-holds-no-nul"),
    ({"identity": {"head\u0000ing": "a"}}, "text-holds-no-nul"),
    ({"evidence": {"lines": "a\u0000b"}}, "text-holds-no-nul"),
    ({"evidence": {"li\u0000nes": "a"}}, "text-holds-no-nul"),
    ({"locator": {"target": "a\u0000b"}}, "text-holds-no-nul"),
    ({"message": "a\u0000b"}, "message-is-one-bounded-line"),
    ({"path": "notes/a\u0000b.md"}, "path-is-corpus-relative"),
])
def test_a_finding_carrying_u0000_refuses_the_whole_output(change: dict[str, Any],
                                                           rule: str) -> None:
    """`6072086385` item 4: no stored finding can carry U+0000 (jsonb refuses
    it), so a pack whose finding holds one loses its own output, never the
    run. The pack's stdout carries it as JSON's escape."""
    stdout = _output(_finding(), _finding(**change))
    assert b"\\u0000" in stdout
    refusal = _output_refused(stdout)
    assert (refusal.reason, refusal.where) == ("finding-shape", {"rule": rule, "finding": 1})
    assert "\x00" not in json.dumps(_is_a_finding_against_the_pack(refusal), ensure_ascii=False)


def test_a_raw_nul_byte_in_stdout_is_no_json_document() -> None:
    stdout = _output(_finding()).replace(b"seasonal-specials", b"seasonal\x00specials")
    assert b"\x00" in stdout
    assert _output_refused(stdout).reason == "output-not-one-json-document"


def test_u0000_in_the_declaration_is_refused() -> None:
    """Every string the declaration carries into a finding is text by T041's
    rules, which refuse U+0000 (`6072086385` item 4)."""
    assert _refused(_document(version="1.4.0\x00")).reason == "version-not-text"
    assert _refused(_family(version="3\x00")).reason == "family-version-not-text"
    assert _refused(_family(label="Heading\x00case")).reason == "family-label-not-text"
    assert _refused(_family(applies_to=["notes/\x00.md"])).reason == "glob-not-text"


def test_a_refused_output_repeats_nothing_the_pack_wrote() -> None:
    secret = "SECRET-PASSAGE-" + "q" * 300
    for stdout in (_output(_finding(kind=secret)), _output(_finding(**{secret: 1})),
                   _output(_finding(message=secret)), secret.encode("utf-8"),
                   _output(_finding(identity={"heading": secret}))):
        refusal = _output_refused(stdout)
        assert "SECRET" not in json.dumps(refusal.finding()) + str(hc.PackRefused(refusal))


def test_a_refusal_keeps_one_id_across_runs() -> None:
    """Pathless, `{category, entry}`: the same refused pack is one finding."""
    first = _output_refused(_output(_finding(kind="orphan-heading"))).finding()
    second = _output_refused(_output(_finding(path="archive/x.md"))).finding()
    assert first["id"] == second["id"]
    assert first["evidence"] != second["evidence"]


# ---------------------------------------------------------------------------
# 5. the patch type
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git, "git is required here, as on CI"
    done = subprocess.run(
        [git, "-c", "core.autocrlf=false", "-c", "diff.noprefix=false", *args], cwd=cwd,
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(cwd),
             "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "f",
             "GIT_AUTHOR_EMAIL": "f@example.invalid", "GIT_COMMITTER_NAME": "f",
             "GIT_COMMITTER_EMAIL": "f@example.invalid"})
    return done.stdout


@pytest.fixture(scope="module")
def git_diffs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    """Real `git diff` output, one per kind 15.2a names, and a plain edit."""
    repo = tmp_path_factory.mktemp("diffs")
    _git(repo, "init", "-q")
    (repo / "notes").mkdir()
    (repo / "notes" / "plan.md").write_text("# Plan\n\none\ntwo\n", encoding="utf-8")
    (repo / "notes" / "old.md").write_text("old\n", encoding="utf-8")
    (repo / "notes" / "gone.md").write_text("gone\n", encoding="utf-8")
    (repo / "notes" / "run.md").write_text("run\n", encoding="utf-8")
    (repo / "notes" / "pic.bin").write_bytes(b"\x00\x01\x02")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    (repo / "notes" / "plan.md").write_text("# Plan\n\none\nTWO\n", encoding="utf-8")
    edit = _git(repo, "diff")
    _git(repo, "checkout", "-q", "--", ".")
    _git(repo, "mv", "notes/old.md", "notes/new.md")
    rename = _git(repo, "diff", "--cached", "-M")
    _git(repo, "reset", "-q", "--hard")
    (repo / "notes" / "run.md").chmod(0o755)
    remode = _git(repo, "diff")
    _git(repo, "reset", "-q", "--hard")
    (repo / "notes" / "created.md").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "notes/created.md")
    create = _git(repo, "diff", "--cached")
    _git(repo, "reset", "-q", "--hard")
    _git(repo, "rm", "-q", "notes/gone.md")
    delete = _git(repo, "diff", "--cached")
    _git(repo, "reset", "-q", "--hard")
    (repo / "notes" / "pic.bin").write_bytes(b"\x00\x03\x02\x09")
    binary = _git(repo, "diff", "--binary")
    _git(repo, "reset", "-q", "--hard")
    return {"edit": edit, "rename": rename, "remode": remode, "create": create,
            "delete": delete, "binary": binary}


@pytest.mark.parametrize("kind", ["edit", "rename", "remode", "create", "delete", "binary"])
def test_git_diff_output_is_a_unified_diff(git_diffs: dict[str, str], kind: str) -> None:
    """Each of 15.2a's refused kinds is still a diff, so T049 refuses it by its
    own rule and names it; this type never pre-empts that."""
    assert git_diffs[kind], kind
    assert hc.unified_diff_problem(git_diffs[kind]) is None


def test_a_plain_unified_diff_and_two_files_are_admitted() -> None:
    one = "--- a/notes/a.md\n+++ b/notes/a.md\n@@ -1,2 +1,2 @@\n x\n-y\n+Y\n"
    assert hc.unified_diff_problem(one) is None
    assert hc.unified_diff_problem(one + one.replace("a.md", "b.md")) is None
    assert hc.unified_diff_problem(
        "--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\n-x\n\\ No newline at end of file\n+y\n"
        "\\ No newline at end of file\n") is None


@pytest.mark.parametrize("patch, reason", [
    (None, "patch-not-text"),
    ({"diff": "--- a"}, "patch-not-text"),
    ("", "patch-empty"),
    ("--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\n-x\n+y", "patch-no-final-newline"),
    ("# Plan\n\nThe whole replacement document.\n", "patch-not-a-unified-diff"),
    ("Here is the fix:\n--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\n-x\n+y\n",
     "patch-not-a-unified-diff"),
    ("--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\n-x\n+y\nrm -rf notes\n", "patch-not-a-unified-diff"),
    ("--- a/a.md\n+++ b/a.md\n", "patch-no-hunk"),
    ("--- a/a.md\n+++ b/a.md\n@@ -1,3 +1,3 @@\n x\n-y\n+Y\n", "patch-hunk-short"),
    ("--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\n x\n y\n", "patch-not-a-unified-diff"),
    ("--- a/a.md\n+++ b/a.md\n@@ -1,0 +1 @@\n x\n", "patch-hunk-short"),
    ("--- a/a.md\n+++ b/a.md\n@@ -1 +1,2 @@\n-x\n+y\nprose\n", "patch-hunk-short"),
    ("--- a/a.md\n+++ b/a.md\n@@ one @@\n-x\n+y\n", "patch-bad-hunk-header"),
    ("+++ b/a.md\n--- a/a.md\n@@ -1 +1 @@\n-x\n+y\n", "patch-not-a-unified-diff"),
])
def test_what_is_no_diff_is_refused(patch: Any, reason: str) -> None:
    assert hc.unified_diff_problem(patch) == reason


# ---------------------------------------------------------------------------
# 6. the protocol
# ---------------------------------------------------------------------------

class _Pack:
    def check(self, corpus: str) -> list[dict[str, Any]]:
        return []


class _NotAPack:
    def run(self, corpus: str) -> list[dict[str, Any]]:
        return []


def test_the_protocol_is_closed_at_one_member() -> None:
    assert hc.PACK_MEMBERS == ("check",)
    assert set(hc.CheckPack.__protocol_attrs__) == set(hc.PACK_MEMBERS)


def test_a_pack_conforms_by_structure_alone() -> None:
    """A class, or the pack's package itself, with nothing of openDox's imported."""
    module = types.ModuleType("a_pack")
    module.check = lambda corpus: []  # type: ignore[attr-defined]
    assert isinstance(_Pack(), hc.CheckPack) and issubclass(_Pack, hc.CheckPack)
    assert isinstance(module, hc.CheckPack)
    assert not isinstance(_NotAPack(), hc.CheckPack)
    assert not isinstance(types.ModuleType("empty"), hc.CheckPack)


def test_a_pack_is_handed_the_export_and_nothing_else() -> None:
    """R2Q20 (a): pack checks are model-free. The one member takes the
    export's root, and no model, binding or endpoint."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(hc.CheckPack)))
    (method,) = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert [arg.arg for arg in method.args.args] == ["self", "corpus"]
    assert not method.args.kwonlyargs and not method.args.vararg and not method.args.kwarg


def test_the_contract_module_runs_no_pack_code() -> None:
    """The declaration is judged before any pack code runs: the module that
    judges it imports no importer, no process and no file system."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, ast.Import) for alias in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom)}
    assert not imported & {"importlib", "runpy", "subprocess", "os", "pathlib", "pkgutil",
                           "zipimport", "yaml"}, imported
