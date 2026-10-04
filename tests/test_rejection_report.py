"""The rejection report: every broken rule, once, with its count (plan 034
T084; RULED openxFactory#656 `5920216845`, item 3, *"Show every rule, grouped
(Recommended)"*).

`cli._report_non_conformance` is what the generate verbs print when the
validator registered for a snapshot's kind rejects it. It printed the LAST 20
LINES of the validator's output, so a snapshot that broke one rule a hundred
times and a second rule once showed twenty copies of the first and never named
the second. Now each broken rule id is printed ONCE, with its exact count and
where it is first broken, in the order the validator found them, and the
validator's own summary line follows.

The cases:

1. THE RULING'S CASE. A rejected snapshot that breaks one rule several times
   and a second rule once, run through `cli._validate`, the function both
   generate verbs call, with openDox's own validator registered for the
   snapshot's kind: each rule id appears ONCE, with its exact count. So an
   implementation that always prints `1`, or never groups a repeated id,
   fails it. The snapshot is the one `python -m opendox.cli generate` writes
   over a corpus with four empty titles and summaries (rule A, four times),
   with ONE more break of a second rule written into it, because openDox's
   projection does not let a corpus break that second rule at all.
2. THE VERB ITSELF, in a child with neither sibling importable
   (`tests/standalone_child.py`): `generate --strict` over that corpus exits 1
   and names its one rule once, with the count 4.
3. A VALIDATOR THAT NAMES NO RULE ID (a host's, say) still has its own last
   lines printed, as before: there is nothing to group, and nothing is hidden.

A module of its own, clear of `tests/test_post_render_validator.py` (which
T085 edits). F7.2's assertions there still hold: the fixture's rule id is
printed with where it is first broken, and so is the validator's summary.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from opendox import cli
from opendox import projection_seams as ps
from standalone_child import fresh_repository, run_module

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"

#: The rule the corpus below breaks four times, and the rule the written
#: snapshot then breaks once more.
REPEATED = "title-and-summary-are-text"
ONCE = "repository-is-text"

#: Three empty titles and one empty summary: four breaks of `REPEATED`.
_EMPTIED = {
    "notes-rain-barrel-leak.md": "title",
    "notes-rain-barrel-overflow.md": "title",
    "notes-toolshed-inventory.md": "title",
    "grouping-compost-corner.md": "summary",
}

#: One reported rule: `<count> × [<rule>] <where>: <detail>`.
_GROUPED = re.compile(r"^    (?P<count>[0-9]+) × \[(?P<rule>[^\]]+)\] (?P<rest>.+)$")


def _emptied_corpus(parent: Path) -> Path:
    edits = {}
    for name, field in _EMPTIED.items():
        text = (PLAIN / name).read_text(encoding="utf-8")
        edits[name] = re.sub(rf"(?m)^{field}: .*$", f"{field}:", text, count=1)
        assert edits[name] != text, f"{name} carries no {field}: line to empty"
    return fresh_repository(PLAIN, parent, edits=edits)


@pytest.fixture()
def seams():
    """openDox's own defaults at the projection seams, and nothing left
    behind: the seams are put back exactly as each case found them."""
    held = {name: getattr(ps, name) for name in ("registry", "corpus_root", "writer")}
    found = {name: (seam._registered, seam._is_default, seam._default_read)
             for name, seam in held.items()}
    kinds = dict(ps.validators._registered)
    read = set(ps.validators._default_read)
    for seam in held.values():
        seam.unregister()
    ps.validators.unregister()
    ps.register_defaults()
    try:
        yield
    finally:
        for name, seam in held.items():
            seam._registered, seam._is_default, seam._default_read = found[name]
        ps.validators._registered.clear()
        ps.validators._registered.update(kinds)
        ps.validators._default_read.clear()
        ps.validators._default_read.update(read)


def _written_snapshot(tmp_path: Path) -> Path:
    """The snapshot the real verb writes over the emptied corpus, unvalidated."""
    repo = _emptied_corpus(tmp_path)
    out = tmp_path / "snapshot.json"
    child, status = run_module(
        tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--no-validate")
    assert status == 0, child.stderr_text()
    assert child.refused() == [], child.refused()
    return out


def _grouped(err: str) -> list[tuple[str, int, str]]:
    return [(m["rule"], int(m["count"]), m["rest"])
            for m in map(_GROUPED.match, err.splitlines()) if m]


def test_each_broken_rule_is_printed_once_with_its_exact_count(
        tmp_path, seams, capsys) -> None:
    """The ruling's case: one rule broken four times, a second once."""
    written = _written_snapshot(tmp_path)
    snapshot = json.loads(written.read_text(encoding="utf-8"))
    snapshot["repository"] = 7                    # ONE break of `ONCE`
    written.write_text(json.dumps(snapshot), encoding="utf-8")
    args = argparse.Namespace(no_validate=False, strict=True,
                              repo_root=str(tmp_path / PLAIN.name))
    assert cli._validate(written, args) == 1
    err = capsys.readouterr().err
    grouped = _grouped(err)
    assert sorted((rule, count) for rule, count, _ in grouped) == sorted([
        (ONCE, 1), (REPEATED, 4)]), err
    # ONCE EACH: no rule id is named on any other line of the report.
    for rule in (REPEATED, ONCE):
        assert len(re.findall(re.escape(f"[{rule}]"), err)) == 1, err
    # where each is FIRST broken, in the validator's own words
    assert dict((rule, rest) for rule, _, rest in grouped)[REPEATED].startswith(
        "/documents/"), err
    assert dict((rule, rest) for rule, _, rest in grouped)[ONCE].startswith(
        "/repository:"), err
    assert "5 violation(s) of 2 rule(s)" in err, err
    # the validator's own summary line still follows
    assert "5 violation(s) of the opendox-snapshot contract" in err, err
    assert "the pinned validator REJECTED" in err and "This is the SNAPSHOT" in err


def test_the_verb_names_its_one_rule_once_with_its_count(tmp_path) -> None:
    """`python -m opendox.cli generate --strict`, with neither sibling
    importable, over the corpus that breaks one rule four times."""
    repo = _emptied_corpus(tmp_path)
    out = tmp_path / "snapshot.json"
    child, status = run_module(
        tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
        "--repository", "fixture", "--output", str(out), "--strict")
    err = child.stderr_text()
    assert status == 1, err
    assert child.refused() == [], child.refused()
    assert [(rule, count) for rule, count, _ in _grouped(err)] == [
        (REPEATED, 4)], err
    assert len(re.findall(re.escape(f"[{REPEATED}]"), err)) == 1, err
    assert "4 violation(s) of 1 rule(s)" in err, err


def test_a_report_that_names_no_rule_still_prints_its_own_last_lines(
        capsys) -> None:
    """A validator whose output names no rule id has nothing to group, so its
    own last lines are printed, as before, and nothing is hidden."""
    lines = [f"line {n}: not conformant" for n in range(30)]
    result = ps.ValidationResult(False, 1, "\n".join(lines) + "\n", "",
                                 "a host's validator")
    cli._report_non_conformance(Path("snapshot.json"), result)
    err = capsys.readouterr().err
    assert _grouped(err) == [], err
    shown = [line.strip() for line in err.splitlines()[1:]]
    assert shown == lines[-20:], err


def test_a_rule_broken_in_several_places_shows_each_place_beneath_it(capsys) -> None:
    """Grouping keeps the order the validator found the rules in, counts every
    line, names where each rule is first broken on the rule's own line, and
    shows the next places beneath it without repeating the id: one rule can be
    broken in different ways, and a count beside the first place alone would
    read as that place repeated."""
    out = "\n".join([
        "[b-rule] /x/0: first b",
        "[a-rule] /y: only a",
        "[b-rule] /x/1: second b",
        "[b-rule] /x/2: third b",
        "4 violation(s) of the k contract, by v",
    ]) + "\n"
    result = ps.ValidationResult(False, 1, out, "", "v")
    cli._report_non_conformance(Path("snapshot.json"), result)
    err = capsys.readouterr().err
    assert _grouped(err) == [("b-rule", 3, "/x/0: first b"),
                             ("a-rule", 1, "/y: only a")], err
    body = err.splitlines()
    at = body.index("    3 × [b-rule] /x/0: first b")
    assert body[at + 1:at + 4] == ["          /x/1: second b",
                                   "          /x/2: third b",
                                   "    1 × [a-rule] /y: only a"], err
    assert err.count("[b-rule]") == 1 and err.count("[a-rule]") == 1, err
    assert "4 violation(s) of 2 rule(s)" in err, err
    assert err.rstrip().endswith("4 violation(s) of the k contract, by v"), err


def test_a_rule_broken_in_many_places_says_how_many_more(capsys) -> None:
    """Past `_PLACES_SHOWN` places a rule says how many more it has, so the
    report stays short and the count stays exact."""
    many = cli._PLACES_SHOWN + 7
    out = "".join(f"[c-rule] /z/{n}: broken\n" for n in range(many))
    result = ps.ValidationResult(False, 1, out, "", "v")
    cli._report_non_conformance(Path("snapshot.json"), result)
    err = capsys.readouterr().err
    assert _grouped(err) == [("c-rule", many, "/z/0: broken")], err
    shown = [line for line in err.splitlines() if line.startswith("          /z/")]
    assert shown == [f"          /z/{n}: broken" for n in range(1, cli._PLACES_SHOWN)], err
    assert "… and 7 more of this rule" in err, err
