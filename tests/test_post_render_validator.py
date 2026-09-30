"""The post-render validator in the generate verbs: plan 034's T058 (#1144's
7.2, in part).

T058 replaces the validator lookup's stand-in with openDox's own validator
(`opendox.validator`, T057), behind the lookup's protocol, one adapter per own
kind (`default_projection.VALIDATORS`). So the generate verbs validate the
neutral snapshot they write against T053's schema, read from T057's packaged
copy. `--strict` makes a validator that cannot run fatal, and `--no-validate`
skips validation. This file holds:

1. F7.2, #1144's Group 7 falsifier, through `python -m opendox.cli generate
   --strict` with neither sibling importable (`tests/standalone_child.py`).
   The good fixture exits 0. The malformed one exits non-zero, naming
   `EXPECTED_RULE` on standard error, with no `No such file or directory`.
   `generate-and-open` gives the same verdicts, and serves nothing it refused.
2. `--no-validate` skips the check, and the malformed snapshot stands.
3. The adapter's three outcomes: `VALIDATED`, `NOT_CONFORMANT` naming each
   rule, and `VALIDATOR_UNAVAILABLE` for `ValidatorUnavailable` and for a
   document it could not read. A document that is not JSON (or not YAML)
   breaks `SYNTAX_RULE`. `strict` and `search_from` change nothing.
4. The workbench manifest, read as YAML, with the two validator rules its
   schema leaves to the validator, and `workbench.save(validate=True)` over
   them.

Every case starts with nothing registered at the four projection seams and
puts back what it found.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from opendox import contracts
from opendox import default_projection
from opendox import projection_seams as ps
from opendox import validator as own
from opendox import workbench
from opendox.boundary import OutputBoundary
from standalone_child import Child, fresh_repository, run_module

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
PLAIN = FIXTURES / "plain-documents"      # T050
MALFORMED = FIXTURES / "malformed"        # T051
EXPECTED_RULE = (MALFORMED / "EXPECTED_RULE").read_text(encoding="utf-8").strip()
NEUTRAL = "opendox-snapshot"
NOW = "2026-09-27T12:00:00Z"


_SINGLE_SEAMS = (ps.registry, ps.corpus_root, ps.writer)


@pytest.fixture(autouse=True)
def _isolated_seams():
    """Nothing registered at the four projection seams, and each is PUT BACK
    whole, records included, since two cases call `register_defaults()`."""
    single = [(seam._registered, seam._is_default, seam._default_read)
              for seam in _SINGLE_SEAMS]
    kinds = (dict(ps.validators._registered), set(ps.validators._default_read))
    for seam in _SINGLE_SEAMS:
        seam.unregister()
    ps.validators.unregister()
    yield
    for seam, held in zip(_SINGLE_SEAMS, single):
        seam._registered, seam._is_default, seam._default_read = held
    ps.validators._registered, ps.validators._default_read = kinds


def _generate(tmp_path: Path, fixture: Path, *extra: str) -> tuple[Child, int, Path]:
    """`python -m opendox.cli generate` over a fresh copy of `fixture`."""
    repo = fresh_repository(fixture, tmp_path)
    out = tmp_path / "out" / "snapshot.json"
    child, status = run_module(tmp_path, "opendox.cli", "generate",
                               "--repo-root", str(repo), "--repository", "fixture",
                               "--output", str(out), *extra)
    return child, status, out


def _snapshot(tmp_path: Path, fixture: Path) -> Path:
    """A snapshot of `fixture`, written by the verb with validation skipped."""
    child, status, out = _generate(tmp_path, fixture, "--no-validate")
    assert status == 0, child.stderr_text()
    return out


def _file(tmp_path: Path, name: str, data: str | bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


# ---------------------------------------------------------------------------
# 1 — F7.2, through the module
# ---------------------------------------------------------------------------

def test_the_expected_rule_is_one_rule_of_the_neutral_contract() -> None:
    rules = {rule["id"] for rule in contracts.load(NEUTRAL)["x-rules"]}
    assert EXPECTED_RULE and EXPECTED_RULE in rules, EXPECTED_RULE


def test_F7_2_the_good_fixture_validates_under_strict(tmp_path) -> None:
    child, status, out = _generate(tmp_path, PLAIN, "--strict")
    assert status == 0, child.stderr_text()
    assert child.refused() == [], child.refused()
    assert ("  validation: opendox-snapshot: 0 violations, by opendox.validator, "
            "over its packaged copy opendox-snapshot") in child.stdout_text()
    assert "validation SKIPPED" not in child.stderr_text()
    assert json.loads(out.read_text(encoding="utf-8"))["kind"] == NEUTRAL


def test_F7_2_the_malformed_fixture_is_refused_for_its_rule(tmp_path) -> None:
    """The refusal carries the fixture's own rule identifier, and it is not a
    refusal for a missing path."""
    child, status, _out = _generate(tmp_path, MALFORMED, "--strict")
    err = child.stderr_text()
    assert status != 0, "a malformed corpus validated"
    assert child.refused() == [], child.refused()
    assert EXPECTED_RULE in err
    assert f"[{EXPECTED_RULE}] /documents/1/title:" in err, err
    assert "No such file or directory" not in err
    assert "the pinned validator REJECTED" in err and "This is the SNAPSHOT" in err
    assert "1 violation(s) of the opendox-snapshot contract" in err


def test_F7_2_the_malformed_fixture_is_refused_without_strict_too(tmp_path) -> None:
    """A snapshot the validator REJECTS fails the verb whatever `--strict`
    says: `--strict` hardens only a validator that could not run."""
    child, status, _out = _generate(tmp_path, MALFORMED)
    assert status == 1
    assert f"[{EXPECTED_RULE}] /documents/1/title:" in child.stderr_text()


@pytest.mark.parametrize("fixture,expected", [(PLAIN, 0), (MALFORMED, 1)])
def test_generate_and_open_gives_the_same_verdicts(tmp_path, fixture, expected) -> None:
    """`generate-and-open --no-open --no-serve --strict`: the good fixture
    builds its server and prints its URL, and the malformed one stops before
    a server is built, naming the rule."""
    repo = fresh_repository(fixture, tmp_path)
    child, status = run_module(tmp_path, "opendox.cli", "generate-and-open",
                               "--repo-root", str(repo), "--repository", "fixture",
                               "--no-open", "--no-serve", "--strict",
                               "--run-dir", str(tmp_path / "run"))
    assert status == expected, child.stderr_text()
    assert child.refused() == []
    served = re.search(r"^http://127\.0\.0\.1:[0-9]+/index\.html$",
                       child.stdout_text(), re.M)
    if expected == 0:
        assert served, child.stdout_text()
    else:
        assert served is None and "serving" not in child.stdout_text()
        assert f"[{EXPECTED_RULE}]" in child.stderr_text()


# ---------------------------------------------------------------------------
# 2 — `--no-validate` skips validation
# ---------------------------------------------------------------------------

def test_no_validate_skips_validation_and_the_snapshot_stands(tmp_path) -> None:
    child, status, out = _generate(tmp_path, MALFORMED, "--no-validate", "--strict")
    assert status == 0, child.stderr_text()
    assert "  validation skipped (--no-validate)" in child.stdout_text()
    assert "REJECTED" not in child.stderr_text()
    assert out.is_file()


# ---------------------------------------------------------------------------
# 3 — the adapter's three outcomes
# ---------------------------------------------------------------------------

def test_the_entry_points_register_openDoxs_own_validator_for_each_own_kind() -> None:
    ps.register_defaults()
    for kind in default_projection.OWN_KINDS:
        assert ps.validators.for_kind(kind) is default_projection.VALIDATORS[kind]
    assert set(default_projection.OWN_KINDS) <= set(own.KINDS)


def test_a_conformant_snapshot_is_validated(tmp_path) -> None:
    result = default_projection.VALIDATORS[NEUTRAL].validate(_snapshot(tmp_path, PLAIN))
    assert (result.ok, result.returncode, result.outcome) == (True, 0, ps.VALIDATED)
    digest = contracts.record().copy(NEUTRAL).sha256
    assert result.validator == (f"opendox.validator, over its packaged copy "
                                f"opendox-snapshot (sha256 {digest[:12]})")
    assert result.summary().startswith("opendox-snapshot: 0 violations, by opendox.validator")


def test_a_malformed_snapshot_is_not_conformant_and_each_rule_is_named(tmp_path) -> None:
    result = default_projection.VALIDATORS[NEUTRAL].validate(_snapshot(tmp_path, MALFORMED))
    assert (result.ok, result.returncode, result.outcome) == (False, 1, ps.NOT_CONFORMANT)
    lines = result.stdout.splitlines()
    assert lines[0].startswith(f"[{EXPECTED_RULE}] /documents/1/title: ")
    assert lines[-1].startswith("1 violation(s) of the opendox-snapshot contract")
    assert len(lines) == 2 and result.stderr == ""


def test_the_verdict_is_openDoxs_validators_own(tmp_path) -> None:
    """The adapter adds nothing to a snapshot's verdict and drops nothing: its
    lines are `opendox.validator.report()` over the same document."""
    path = _snapshot(tmp_path, MALFORMED)
    result = default_projection.VALIDATORS[NEUTRAL].validate(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert result.stdout.splitlines()[:-1] == own.report(own.validate(document, kind=NEUTRAL))


@pytest.mark.parametrize("text,why", [
    ('{"kind": "opendox-snapshot", "schema_version": NaN}', "NaN is not JSON"),
    ('{"kind": "opendox-snapshot", "kind": "opendox-snapshot"}', "given twice"),
    ('{"kind": "opendox-snapshot"', "Expecting"),
    (b'{"kind": "\xff"}', "codec"),
    ("[" * 100_000 + "]" * 100_000, ""),
])
def test_a_snapshot_that_is_not_json_breaks_the_syntax_rule(tmp_path, text, why) -> None:
    result = default_projection.VALIDATORS[NEUTRAL].validate(_file(tmp_path, "s.json", text))
    assert (result.ok, result.returncode, result.outcome) == (False, 1, ps.NOT_CONFORMANT)
    first = result.stdout.splitlines()[0]
    assert first.startswith(f"[{default_projection.SYNTAX_RULE}] <root>: the document "
                            "is not JSON, which is how a 'opendox-snapshot' document "
                            "is written: "), first
    assert why in first


def test_a_document_that_cannot_be_read_is_unavailable_not_a_verdict(tmp_path) -> None:
    result = default_projection.VALIDATORS[NEUTRAL].validate(tmp_path)
    assert (result.ok, result.outcome, result.available) == (
        False, ps.VALIDATOR_UNAVAILABLE, False)
    assert result.validator == "opendox.validator"
    assert "the document could not be read" in result.unavailable_reason


@pytest.mark.parametrize("failure", [
    contracts.CopyRefused("the packaged copy differs from its digest"),
    own.SchemaNotEvaluable("the packaged copy uses a keyword this module does not evaluate"),
])
def test_validator_unavailable_is_unavailable_with_its_reason(tmp_path, monkeypatch,
                                                              failure) -> None:
    path = _snapshot(tmp_path, PLAIN)

    def refused(kind):
        if isinstance(failure, contracts.CopyRefused):
            raise own.ValidatorUnavailable(str(failure)) from failure
        raise failure

    monkeypatch.setattr(own, "validator_for", refused)
    result = default_projection.VALIDATORS[NEUTRAL].validate(path)
    assert (result.ok, result.returncode, result.outcome) == (
        False, -1, ps.VALIDATOR_UNAVAILABLE)
    assert result.validator == "opendox.validator"
    assert result.unavailable_reason == str(failure)


def test_a_packaged_copy_that_fails_its_identity_is_unavailable(tmp_path, monkeypatch) -> None:
    """End to end through the identity check: a copy whose bytes are not the
    recorded ones is refused by `opendox.contracts`, so nothing is judged."""
    path = _snapshot(tmp_path, PLAIN)
    real = contracts._read_package_file

    def tampered(name):
        data = real(name)
        return data + b"\n" if name.endswith("opendox-snapshot.schema.yaml") else data

    monkeypatch.setattr(contracts, "_read_package_file", tampered)
    result = default_projection.VALIDATORS[NEUTRAL].validate(path)
    assert result.outcome == ps.VALIDATOR_UNAVAILABLE
    assert "is not the file the record pins" in result.unavailable_reason


def test_a_packaged_file_that_cannot_be_read_is_unavailable_not_a_traceback(
        tmp_path, monkeypatch, capsys) -> None:
    """A packaged record or copy that is present but unreadable raises an
    `OSError` below `opendox.contracts`, which converts only a missing one.
    The adapter reports it as unavailable, and the verb warns, or fails under
    `--strict`, in its own words."""
    import argparse

    from opendox import cli

    path = _snapshot(tmp_path, PLAIN)

    def unreadable(name):
        raise PermissionError(13, "Permission denied", name)

    monkeypatch.setattr(contracts, "_read_package_file", unreadable)
    result = default_projection.VALIDATORS[NEUTRAL].validate(path)
    assert (result.ok, result.outcome) == (False, ps.VALIDATOR_UNAVAILABLE)
    assert result.unavailable_reason == (
        "openDox's packaged contracts could not be read (PermissionError: "
        "Permission denied), so nothing was judged")
    ps.register_defaults()
    args = argparse.Namespace(repo_root=str(tmp_path), no_validate=False, strict=True)
    assert cli._validate(path, args) == 1
    err = capsys.readouterr().err
    assert "could not run: openDox's packaged contracts could not be read" in err
    assert "--strict was given" in err


def test_the_rules_read_a_long_list_in_linear_time() -> None:
    """None of the three lists is bounded by the schema, so a rule's reading
    of one must not be quadratic: 50,000 distinct names, and a repeat of
    each, are read in well under the seconds a quadratic scan would take."""
    import time

    names = [f"keyword-{index}" for index in range(50_000)]
    started = time.monotonic()
    read = default_projection._names(names + names + [7, None])
    elapsed = time.monotonic() - started
    assert read == names
    assert elapsed < 5, f"{elapsed:.1f}s to read 100,002 entries"


def test_strict_and_search_from_change_nothing(tmp_path) -> None:
    validator = default_projection.VALIDATORS[NEUTRAL]
    for fixture in (PLAIN, MALFORMED):
        path = _snapshot(tmp_path / fixture.name, fixture)
        plain = validator.validate(path)
        assert validator.validate(path, strict=True,
                                  search_from=(tmp_path, Path("/nonexistent"))) == plain


def test_each_validator_reads_as_its_own_kind(tmp_path) -> None:
    """A validator is bound to the kind it is registered under, so a snapshot
    handed to the workbench manifest's validator is judged as a manifest."""
    result = default_projection.VALIDATORS[workbench.KIND].validate(
        _snapshot(tmp_path, PLAIN))
    assert result.outcome == ps.NOT_CONFORMANT
    assert "[const] /kind: " in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# 4 — the workbench manifest, and its two validator rules
# ---------------------------------------------------------------------------

def _recipe_set(**recipe) -> workbench.Workbench:
    w = workbench.Workbench.create(
        "fixture", "a recipe set", seed=workbench.SEED_RECIPE,
        recipe={"checked": ["compost", "soil"], "pinned": ["soil"], **recipe}, now=NOW)
    w.add_member("notes/in.md", sorted(workbench.VIA_VALUES)[0], now=NOW,
                 reason="a human chose it")
    w.exclude("notes/out.md", "not about the shed", now=NOW)
    return w


def _manifest(tmp_path: Path, document: dict) -> Path:
    return _file(tmp_path, "set.workbench.yaml", yaml.safe_dump(document, sort_keys=False))


def test_a_manifest_openDoxs_workbench_writes_is_validated(tmp_path) -> None:
    w = _recipe_set()
    result = default_projection.VALIDATORS[workbench.KIND].validate(
        _file(tmp_path, "set.workbench.yaml", w.render()))
    assert (result.ok, result.outcome) == (True, ps.VALIDATED), result.stdout
    assert result.summary().startswith("ideation-workbench: 0 violations")


def test_a_pinned_keyword_that_is_not_checked_breaks_its_rule(tmp_path) -> None:
    document = yaml.safe_load(_recipe_set().render())
    document["recipe"]["pinned"] = ["soil", "worms", "worms"]
    result = default_projection.VALIDATORS[workbench.KIND].validate(
        _manifest(tmp_path, document))
    assert result.outcome == ps.NOT_CONFORMANT
    assert result.stdout.splitlines() == [
        "[workbench-pinned-not-checked] /recipe/pinned: pinned keyword(s) ['worms'] "
        "are not in checked: every pinned keyword MUST also be checked",
        "1 violation(s) of the ideation-workbench contract, by "
        f"{result.validator}"]


def test_a_rules_detail_quotes_a_few_names_and_counts_the_rest(tmp_path) -> None:
    document = yaml.safe_load(_recipe_set().render())
    document["recipe"]["pinned"] = [f"k{index:02d}" for index in range(25)]
    result = default_projection.VALIDATORS[workbench.KIND].validate(
        _manifest(tmp_path, document))
    first = result.stdout.splitlines()[0]
    assert first.startswith("[workbench-pinned-not-checked] /recipe/pinned: pinned "
                            "keyword(s) ['k00', 'k01', ")
    assert "'k09', and 15 more] are not in checked" in first and "'k10'" not in first


def test_a_new_candidate_already_placed_breaks_its_rule(tmp_path) -> None:
    document = yaml.safe_load(_recipe_set().render())
    document["recipe"]["new_candidates"] = ["notes/fresh.md", "notes/out.md", "notes/in.md"]
    result = default_projection.VALIDATORS[workbench.KIND].validate(
        _manifest(tmp_path, document))
    assert result.outcome == ps.NOT_CONFORMANT
    assert result.stdout.splitlines()[0] == (
        "[workbench-candidate-overlap] /recipe/new_candidates: new_candidates "
        "['notes/out.md', 'notes/in.md'] already appear in members or excluded: a "
        "new candidate is a document the set has not placed yet")


def test_the_two_rules_are_judged_beside_the_schema_and_never_crash(tmp_path) -> None:
    document = yaml.safe_load(_recipe_set().render())
    document["recipe"]["pinned"] = [["unhashable"], "worms"]
    document["recipe"]["new_candidates"] = {"not": "a list"}
    document["members"].append("not a member")
    result = default_projection.VALIDATORS[workbench.KIND].validate(
        _manifest(tmp_path, document))
    rules = [line.split("]")[0][1:] for line in result.stdout.splitlines()[:-1]]
    assert "workbench-pinned-not-checked" in rules
    assert "workbench-candidate-overlap" not in rules
    assert {"type"} <= set(rules), rules


def test_a_manifest_that_is_not_yaml_breaks_the_syntax_rule(tmp_path) -> None:
    result = default_projection.VALIDATORS[workbench.KIND].validate(
        _file(tmp_path, "set.workbench.yaml", "kind: [ideation-workbench\n"))
    assert result.outcome == ps.NOT_CONFORMANT
    assert result.stdout.startswith(
        f"[{default_projection.SYNTAX_RULE}] <root>: the document is not YAML, which "
        "is how a 'ideation-workbench' document is written: ")


def test_save_with_validate_keeps_a_valid_manifest_and_unwinds_a_broken_one(tmp_path) -> None:
    ps.register_defaults()
    boundary = OutputBoundary(tmp_path, [workbench.WORKBENCH_DIR])
    written = workbench.save(_recipe_set(), boundary, validate=True)
    assert written.is_file()
    broken = _recipe_set()
    broken.data["name"] = "a broken set"
    broken.data["recipe"]["pinned"] = ["worms"]
    with pytest.raises(workbench.ManifestInvalid) as refused:
        workbench.save(broken, boundary, validate=True)
    assert "[workbench-pinned-not-checked] /recipe/pinned:" in str(refused.value)
    assert not (tmp_path / workbench.manifest_relpath("a broken set")).exists()
