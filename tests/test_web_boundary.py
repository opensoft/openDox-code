"""The front-end package boundary, declared and measured -- slice S1.

`docs/front-end-package-boundary.md` (opensoft/openDox-spec #8 -> `a44ac06d`)
invents the boundary `src/opendox/web/` never had (§ 1: "40 files, 30,410
lines, and NO package boundary at all today"). § 4.5 states the test that
holds it, four assertions, and slice S1 (§ 5) is: "Land the census table of
§ 3.2 as data plus `tests/test_web_boundary.py` with all four assertions, add
the file to `validate`'s explicit list in the SAME commit, and mark
assertions 2, 3 and 4 `@pytest.mark.xfail(strict=True)` citing the defect
each measures ... Assertion 1 is unmarked." This module is that file; the
declared data is `tests/fixtures/web_boundary_census.yaml`.

RULED -- opensoft/openxFactory#656 comment `5642758731` (Brett Heap,
2026-09-12T02:07:53Z, "RULED -- § 3.4 front-end package boundary, the five
open questions ... every recommended answer adopted" / "RULED, same sitting
-> START S1-S3 NOW, with the note amended to carry these rulings"). The
fixture's own header carries each ruling against the census row it changes;
only `views/explorer.js` actually moves (from "?" to C, Q2) -- the other four
rulings (Q1, Q3, Q4, Q5) are recorded against slices S2/S4/S6/S7, not this one.

WHY `strict=True`, AND WHY THAT IS THE WHOLE POINT (note § 4.5, last
paragraph). openDox-code's `validate` runs an explicit file list with
`--noconftest` (§ 1.2(d) / `.github/workflows/validate.yml`), so a new test
file is not exercised until the workflow names it -- naming it while three of
its four assertions are known-red would put the required check red for the
duration of the whole S2-S7 arc. Marking those three `xfail(strict=True)`
instead keeps `validate` GREEN while the defect stands, and flips it RED the
moment a later slice closes the defect without also removing the marker --
the measurement cannot rot into a permanently tolerated failure, and a slice
that claims to have closed a defect it has not gets caught by CI rather than
by review. Symmetrically: a marker left in place after its defect is truly
gone is an XPASS, and `strict=True` turns THAT red too.

A NOTE ON FIDELITY OVER TIDINESS. Assertions 2 and 3 are each implemented to
the FULL WIDTH of what § 4.5 states, not narrowed to whatever count would
make the note's own closing-paragraph slice attribution come out even. Where
that surfaced a real disagreement inside the note itself, the `reason=`
string says so rather than picking a slice number quietly. This does not
weaken the ratchet: `strict=True` only ever fires on an UNEXPECTED PASS, so
if a slice the note names ships without actually closing every site this
assertion checks, the marker stays valid (still XFAIL) and the check stays
green -- CI, not this module, is what makes an author look again before
removing a marker their slice has not fully earned.

`--noconftest` SAFE, deliberately, like its three neighbours already on the
explicit list (`test_leg_shape.py`, `test_consumer_reach.py`,
`test_profile_registration.py`): this module parses the TREE and the
declared YAML census; it imports no view module (they are JavaScript, not
Python) and no `opendox` submodule, so it needs no fixture, no path
insertion and no installed consumer. `PyYAML` is already a runtime
dependency (`pyproject.toml`'s `[project] dependencies`), not a test-only
addition made here.

AMENDED BY SLICE S4 -- "split the three RULED `SPLIT` files" (RULED Q3, same
comment; leg branch `build/s4-split-route-tails`). Four things changed here and
nothing else:

  1. ASSERTION 1 GREW ITS POST-S4 CUTOFF, which is the half of note § 4.5
     point 1 that S1 could not yet enforce: "after S4 the assertion fails on any
     row still `?` OR still `SPLIT` -- EXCEPT `views/lens.js`'s `?`, named
     here". S4 is the slice that performs the split, so S4 is the slice that
     owns the cutoff. The one exception is DECLARED DATA
     (`declared_transitional_rows`), never a literal in this module, for the
     note's own reason: "a permanent UNDECLARED 'undecided' is an escape hatch,
     not a boundary; a permanent DECLARED one, cited to the ruling gap that
     causes it, is how this census stays honest about what it does not yet
     know."
  2. ASSERTION 2 GREW ITS OWN DECLARED EXCEPTION, likewise as data
     (`route_ownership_exceptions`): `views/lens.js`'s two openxFactory-lane
     sites are "excluded from the in-scope grep until a future ruling folds
     lens.js back in ... they never entered it" (§ 4.5 point 2, last paragraph).
     Every other site the assertion was tolerating stays in scope and stays
     measured.
  3. THE THREE MARKERS GAINED `raises=AssertionError`. An `xfail(strict=True)`
     with no `raises` tolerates ANY exception, so a `KeyError` from a malformed
     fixture, or an `OSError` from a renamed file, would read as the expected
     failure and keep the check green. These three markers stand for a MEASURED
     defect -- an assertion that fails -- and now say so; anything else is a
     broken test and fails as one. (Register nit 1 of the four S1 left; nit 2 is
     the cutoff above. The other two -- the exemption test checking text
     presence rather than a declaration, and the fixture's row-level `exempt:`
     not being cross-checked against `declared_exemptions` -- belong to
     assertion 4's own scope and are left to S7, which is the slice that
     discharges it.)
  4. THE CENSUS DECLARES ITS TOTALS and this module re-derives them, so the
     class arithmetic in the fixture's header cannot drift from its rows.

A CREATED file (this module and its fixture): no carve-manifest row (RULED
OQ-C) -- the front end's package boundary did not exist before this note, so
there is nothing for either file to have been carved FROM.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "src" / "opendox" / "web"
CENSUS_PATH = Path(__file__).resolve().parent / "fixtures" / "web_boundary_census.yaml"

VALID_CLASSES = {"A", "B", "C", "?"}

# The classes note § 4.5 point 1 calls transitional and forbids after slice S4.
# "SPLIT" is named here as the note names it even though this fixture never
# spelled it (S1 collapsed both into `"?"`, whose own legend says so): a row
# that reintroduced it would already fail the `VALID_CLASSES` check above, and
# stating the rule over BOTH words keeps this module readable against the note
# rather than against one fixture's spelling choice.
TRANSITIONAL_CLASSES = {"?", "SPLIT"}


def _load_census() -> dict:
    with CENSUS_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_CENSUS = _load_census()
_ROWS: list[dict] = _CENSUS["files"]
_EXEMPTIONS: list[dict] = _CENSUS["declared_exemptions"]
_TOTALS: dict[str, dict] = _CENSUS["totals"]
# Assertion 1's declared, ruled-later exceptions (note § 4.5 point 1) and
# assertion 2's own (point 2). Both are DATA, so adding one is a reviewed diff
# in the fixture beside the reason, never a literal buried in this module.
_TRANSITIONAL_EXCEPTIONS: list[dict] = _CENSUS["declared_transitional_rows"]
_ROUTE_EXCEPTIONS: list[dict] = _CENSUS["route_ownership_exceptions"]
# Duplicates collapse silently here (a dict can only hold one value per key);
# `test_every_web_file_is_classified_exactly_once` checks the RAW list
# instead, so a duplicate row is still caught rather than swallowed by this
# convenience lookup.
_ROWS_BY_PATH: dict[str, dict] = {row["path"]: row for row in _ROWS}


def _real_web_files() -> set[str]:
    return {p.relative_to(WEB_ROOT).as_posix() for p in WEB_ROOT.rglob("*") if p.is_file()}


def _assertion_4_scope() -> list[dict]:
    """The 14 class-C files (13 in the note's own § 3.1 total, +1 for
    `views/explorer.js` under Q2's ruling) plus the declared class-A tails
    (note § 2.2 rule 3): `views/docs.js`, `views/grouping.js`,
    `views/repo-selector-model.js` -- and, since slice S4,
    `views/staging-workbench-model.js`, whose class-C substance
    (`STATUS_BRAINSTORM` / `BRAINSTORM_AREA` / `STAGING_AREA`, § 3.2's own
    reading of the row) is what is left once its six class-B route constants
    travel. Four tails, 18 files in scope; all of it S7's."""
    return [row for row in _ROWS if row["class"] == "C" or row.get("tail")]


# ---------------------------------------------------------------------------
# Assertion 1 -- the census is complete, and "?" is transitional (note § 4.5
# point 1). UNMARKED: this is the ratchet, and it must hold from the moment
# the census is written, or a new file with no row could survive silently.
# ---------------------------------------------------------------------------

def test_every_web_file_is_classified_exactly_once() -> None:
    real = _real_web_files()
    declared = set(_ROWS_BY_PATH)

    missing_rows = sorted(real - declared)
    assert not missing_rows, (
        f"{len(missing_rows)} file(s) under src/opendox/web/ carry no census "
        f"row in tests/fixtures/web_boundary_census.yaml: {missing_rows} -- "
        f"a new or renamed file must be classified in the same commit that "
        f"adds it (note § 4.5 point 1)."
    )

    stale_rows = sorted(declared - real)
    assert not stale_rows, (
        f"{len(stale_rows)} census row(s) name a file that no longer exists "
        f"under src/opendox/web/: {stale_rows} -- update or remove the row."
    )

    raw_paths = [row["path"] for row in _ROWS]
    dup_paths = sorted({p for p in raw_paths if raw_paths.count(p) > 1})
    assert not dup_paths, f"duplicate census row(s) for: {dup_paths}"

    bad_class_rows = sorted(row["path"] for row in _ROWS if row["class"] not in VALID_CLASSES)
    assert not bad_class_rows, (
        f"row(s) with a class outside {sorted(VALID_CLASSES)}: {bad_class_rows}"
    )

    # LOC is provenance the fixture carries voluntarily (mirroring the
    # note's own § 3.1 totals); a census that drifts from the tree it
    # describes is itself a data-quality defect, and it is cheap to catch
    # here before anything downstream trusts it. `wc -l` (what the note and
    # this fixture were measured with) counts NEWLINE CHARACTERS, which
    # `.count("\n")` mirrors exactly regardless of a missing trailing
    # newline -- both simply count the same bytes.
    mismatched_loc = []
    for row in _ROWS:
        text = (WEB_ROOT / row["path"]).read_text(encoding="utf-8", errors="replace")
        real_loc = text.count("\n")
        if real_loc != row["loc"]:
            mismatched_loc.append((row["path"], row["loc"], real_loc))
    assert not mismatched_loc, (
        f"census `loc` drifted from the tree (path, declared, actual): {mismatched_loc}"
    )

    # THE POST-S4 CUTOFF (note § 4.5 point 1, and slice S4 is the slice that
    # earns the right to enforce it): "`?` and `SPLIT` are classes the census
    # may carry only until S4 ... after S4 the assertion fails on any row still
    # `?` OR still `SPLIT` -- EXCEPT `views/lens.js`'s `?`, named here". The
    # exception is read from the fixture, so the census declares its own one
    # loose end and this module only enforces that there is nothing else.
    declared_transitional = {e["path"] for e in _TRANSITIONAL_EXCEPTIONS}
    still_transitional = sorted(
        row["path"] for row in _ROWS
        if row["class"] in TRANSITIONAL_CLASSES
        and row["path"] not in declared_transitional
    )
    assert not still_transitional, (
        f"{len(still_transitional)} row(s) still carry a TRANSITIONAL class "
        f"after slice S4: {still_transitional}. § 4.5 point 1: `?` and `SPLIT` "
        f"are classes the census may carry only until S4, and S4 is the slice "
        f"that splits all three of them (§ 5) -- so a transitional row still "
        f"standing fails exactly like an undeclared row would. A row that "
        f"genuinely cannot be classified yet is DECLARED in the census's "
        f"`declared_transitional_rows`, with the ruling gap that causes it and "
        f"what would discharge it; a permanent UNDECLARED 'undecided' is an "
        f"escape hatch, not a boundary."
    )


def test_the_declared_transitional_rows_are_real_and_still_transitional() -> None:
    """Assertion 1's exception list cannot outlive its cause (note § 4.5 point
    1's own reasoning about a DECLARED exception, applied to the declaration).

    Unmarked and passing: bookkeeping on the fixture, not a measurement of the
    boundary defect.
    """
    for exception in _TRANSITIONAL_EXCEPTIONS:
        path = exception["path"]
        row = _ROWS_BY_PATH.get(path)
        assert row is not None, (
            f"declared transitional exception names {path}, which carries no "
            f"census row"
        )
        assert row["class"] in TRANSITIONAL_CLASSES, (
            f"{path} is declared a transitional exception but its census row is "
            f"class {row['class']!r} -- the exception is STALE, and a stale one "
            f"is how the next `?` row slips through behind it"
        )
        assert row["class"] == exception["class"], (
            f"{path}'s declared exception names class {exception['class']!r} and "
            f"its row carries {row['class']!r}"
        )
        assert exception.get("reason"), f"{path}'s transitional exception carries no reason"
        assert exception.get("until"), (
            f"{path}'s transitional exception names nothing that would discharge "
            f"it; an exception with no exit is a permanent one wearing a label"
        )


def test_the_declared_totals_are_re_derived_from_the_rows() -> None:
    """The census states its own per-class shape and it must be the shape of
    its rows -- so the header arithmetic every slice quotes cannot drift from
    the data underneath it. Unmarked: arithmetic, not a defect measurement."""
    derived: dict[str, dict[str, int]] = {}
    for row in _ROWS:
        entry = derived.setdefault(row["class"], {"files": 0, "loc": 0})
        entry["files"] += 1
        entry["loc"] += row["loc"]
    assert derived == _TOTALS, (
        f"the census's declared `totals:` disagree with its own rows.\n"
        f"declared: {_TOTALS}\nderived:  {derived}"
    )


# ---------------------------------------------------------------------------
# Assertion 2 -- no file OUTSIDE class B names a route another column
# declares (note § 2.2 rule 1, § 4.5 point 2). Class B is exempt BY
# CONSTRUCTION: a gate-loop file naming a gate route is the boundary
# working, not breaking.
# ---------------------------------------------------------------------------

# The three owners, per the note's § 3.3 table -- the ownership the front
# end does not yet know about. Matched as a JS/HTML STRING LITERAL
# (immediately after a quote character, immediately before the closing one),
# so a bare mention in a `//` comment --
# `views/staging-workbench-model.js`:899's trailing
# `"agent_invocation",   // /actions/gate/* and /actions/edit"` -- is not
# flagged: only a literal that ADDRESSES the route is the § 1.2(c)/(d)
# defect this assertion measures.
_OWNED_ROUTE_PATTERNS = {
    "the gate prefix (serve_gate.ACTIONS_GATE_PREFIX)": re.compile(r'["\']/actions/gate/'),
    "openxFactory's adapter lanes (serve_openxfactory_lanes.py)": re.compile(
        r'["\']/actions/(?:dtn-seed|staging-seed|apply-register-edits)["\']'
    ),
    "openXdox's projection routes (serve_projection.py)": re.compile(
        r'["\']/(?:snapshot-index\.json|source/?|projections/(?:evidence|workbench|role-authority))["\']'
    ),
}


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _excepted_routes(path: str) -> set[str]:
    """The routes DECLARED out of this file's in-scope grep (note § 4.5 point
    2's own standing exception, added at slice S4). Keyed by route and never by
    line: "they never entered it", so the exclusion has to survive every edit
    above the site."""
    excepted: set[str] = set()
    for exception in _ROUTE_EXCEPTIONS:
        if exception["path"] == path:
            excepted.update(exception["routes"])
    return excepted


def _route_ownership_violations() -> list[str]:
    violations = []
    for row in _ROWS:
        if row["class"] == "B":
            continue  # exempt by construction
        excepted = _excepted_routes(row["path"])
        text = (WEB_ROOT / row["path"]).read_text(encoding="utf-8")
        for owner, pattern in _OWNED_ROUTE_PATTERNS.items():
            for m in pattern.finditer(text):
                # The match carries its delimiters (`"/actions/dtn-seed"`), and
                # the gate-prefix pattern matches a PREFIX rather than a whole
                # route -- so the exception is tested against the matched text
                # stripped of quotes, which is the whole route for every
                # exception this census declares or can declare (a prefix-only
                # exception would have to be spelled as the prefix).
                literal = m.group(0).strip("\"'")
                if literal in excepted:
                    continue
                site = f"{row['path']}:{_line_of(text, m.start())}"
                violations.append(f"{site} names {m.group(0)} ({owner})")
    return violations


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "docs/front-end-package-boundary.md § 4.5 point 2 (opensoft/openDox-spec "
        "#8 -> a44ac06d): 4 sites outside class B name a route another column "
        "declares. THE ARITHMETIC, since every slice so far has moved it: 18 at "
        "S1 -> 20 at S3 (which added app.js's `gate.bar` entry and closed none) "
        "-> 12 measured after S4 -> 10 in scope (S4 also gives this assertion "
        "the DECLARED EXCEPTION the note's own last paragraph states for "
        "views/lens.js:41/45) -> 4 HERE. SLICE S5 CLEARED ALL SIX GATE-PREFIX "
        "SITES, and every one of them was in app.js's CORE arm: the `gate.bar` "
        "entry (S3) and the `gate.lens` / `gate.projects` entries (S4), each a "
        "class-B binding's `routes:` declaration sitting in a class-A file. "
        "They closed the way the marker predicted -- the six class-B modules "
        "LEFT this bundle for openXdox-code's package data and their bindings "
        "arrive through contributedViewBindings() (RULED Q5, openxFactory#656 "
        "comment 5648044785), so app.js carries no gate route literal at all. "
        "WHAT IS LEFT is one family and it is not this slice's: 4 of openXdox's "
        "projection routes -- app.js:205/:206, views/viewer.js:314, "
        "views/wheel.js:131, the `/source/` sites RULED Q4 re-homes at slice S6 "
        "(openDox-code#16, openXdox-code#17, both in flight on their own "
        "branches and not in this stack). NOT IN SCOPE, by declaration rather "
        "than by silence: views/lens.js's two openxFactory-lane sites "
        "(`route_ownership_exceptions` in the census) -- none of Q1-Q5 rules on "
        "that file, so they clear on no slice's schedule. This marker therefore "
        "comes off at S6; unmark only once verified green."
    ),
)
def test_no_ownership_violation_outside_class_b() -> None:
    violations = _route_ownership_violations()
    assert not violations, f"{len(violations)} route-ownership violation(s):\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Assertion 3 -- every relative import resolves, and no class-A/C file
# imports a class-B module (note § 4.5 point 3). Catches § 1.2(b) -- the
# carve's RULED `not_moved` row for `views/intent-feed.js` left two dangling
# imports at this leg -- as a test failure rather than a blank page.
# ---------------------------------------------------------------------------

# Matches `import {...} from "./x.js"` (the `{...}` may span multiple source
# lines -- `views/wheel.js`:73-76 does exactly this twice -- but the
# `from "..."` clause itself is always on one line, which is all this
# pattern anchors on) and the bare side-effect form `import "./x.js";`
# (`views/viewer.js`:23's vendored markdown-it). Anchored on a RELATIVE
# specifier (`./` or `../`) immediately inside the quotes, which is what
# keeps a string built at runtime -- `"...Drafted from " + n + " document..."`
# in `views/lens.js`:802 is the one near-miss this tree actually has -- from
# being read as an import.
_IMPORT_FROM = re.compile(r'from\s*["\'](\.\.?/[^"\']+)["\']')
_IMPORT_BARE = re.compile(r'^\s*import\s*["\'](\.\.?/[^"\']+)["\']', re.MULTILINE)


def _relative_import_specifiers(text: str) -> list[str]:
    return [m.group(1) for m in _IMPORT_FROM.finditer(text)] + [
        m.group(1) for m in _IMPORT_BARE.finditer(text)
    ]


def _import_violations() -> list[str]:
    violations = []
    for row in _ROWS:
        path = row["path"]
        if not path.endswith(".js"):
            continue
        text = (WEB_ROOT / path).read_text(encoding="utf-8")
        importer_dir = (WEB_ROOT / path).parent
        for specifier in _relative_import_specifiers(text):
            target = (importer_dir / specifier).resolve()
            try:
                target_rel = target.relative_to(WEB_ROOT.resolve()).as_posix()
            except ValueError:
                violations.append(f"{path} -> {specifier}: resolves OUTSIDE src/opendox/web/ ({target})")
                continue
            if not target.is_file():
                violations.append(f"{path} -> {specifier}: UNRESOLVED (no file at {target_rel})")
                continue
            target_row = _ROWS_BY_PATH.get(target_rel)
            if target_row is None:
                violations.append(
                    f"{path} -> {specifier}: resolves to {target_rel}, which carries no census row"
                )
                continue
            if row["class"] in ("A", "C") and target_row["class"] == "B":
                violations.append(f"{path} (class {row['class']}) imports {target_rel} (class B)")
    return violations


# THE MARKER IS OFF -- SLICE S5 DISCHARGED THIS ASSERTION (note § 4.5's own
# closing paragraph: "Assertions 2, 3 and 4 carry the marker at S1, and each is
# unmarked by the slice that discharges it: 3 by S2, 2 by S5 and S6, 4 by S7").
#
# THE ARITHMETIC, since every slice so far has moved it: 7 at S1 -> 6 once S3
# (opensoft/openDox-code#14) closed `app.js`:43 -> `views/gate.js` -> 4 once S2
# (#15) closed the two UNRESOLVED intent-feed imports -> 0 HERE. The four this
# slice closed were the gate loop's own, and they closed the way the note said
# they would -- by the modules LEAVING, not by the importers being rewritten
# around them:
#
#   app.js                     -> views/swb-session.js   (`firstEditTransport`,
#                                                         RULED Q10)
#   views/staging-workbench.js -> views/swb-create.js    (RULED Q5 + Q3)
#   views/staging-workbench.js -> views/swb-session.js   (RULED Q5 + Q3)
#   views/wheel.js             -> views/dispose.js       (RULED Q5 + Q2)
#
# Each importer now reads the DECLARED NAMESPACE of a contributed binding the
# shell resolved (RULED Q2's `exports` tuple), handed down already-bound, with a
# null column making every affordance unoffered where openXdox is not
# registered. The six modules are openXdox-code's package data
# (`src/openxdox/web/views/`), placed into this bundle at assembly (RULED Q5).
#
# `strict=True` IS WHY THIS IS SAFE TO UNMARK AND NOT A CHOICE: leaving the
# marker on a passing assertion is an XPASS and turns the required check RED, so
# the marker had to come off in the same commit that closed the last breach --
# which is precisely the rot the marker exists to prevent, working.
def test_every_relative_import_resolves_and_stays_in_class() -> None:
    violations = _import_violations()
    assert not violations, f"{len(violations)} import violation(s):\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# Assertion 4 -- no class-C file, and no declared class-A tail, carries a
# governance literal (note § 2.2 rule 2, § 4.5 point 4).
# ---------------------------------------------------------------------------

# A CLOSED word list: the eight controlled `Status:` words
# (openxFactory's `docs/document-lifecycle.md`) plus the stage vocabulary
# this tree's own funnel/wheel/board actually spell (`COLUMN_KEYS`,
# `WHEEL_KEYS`/`WHEEL_LABELS`, board.js's four columns, styles.css's
# `--st-*` tokens) -- evidenced, not guessed: every file this assertion
# scopes independently carries at least one of these words today, verified
# against openDox-code `main` `a99eba03` at S1 authoring time.
_STATUS_WORDS = (
    "brainstorm", "staged", "draft", "ratified", "standard",
    "superseded", "retired", "record",
)
_STAGE_WORDS = (
    "docs", "documents", "clusters", "cluster", "possibles", "possible",
    "proposals", "proposal", "realized", "changes", "active", "archived",
)
GOVERNANCE_WORDS = tuple(sorted(set(_STATUS_WORDS) | set(_STAGE_WORDS)))
_GOVERNANCE_WORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in GOVERNANCE_WORDS) + r")\b"
)

# PR REVIEW FIX (opensoft/openDox-code#13, Copilot on tests/test_web_boundary.py
# :330): the sweep must not run over prose. `views/model.js`:8-9's own comment
# -- "Six-column docs-first funnel ... docs -> clusters -> possibles -> staged
# picks -> proposals -> realized" -- and `views/board.js`:1-5's "Four lifecycle
# columns -- brainstorm, staged, active proposals, realized/archived" carry six
# of the eight watched words as EXPLANATORY TEXT, not as runtime vocabulary; so
# does `styles.css`:1 ("grown verbatim from the staged mockup") among 197 `/*
# */` blocks. Left unstripped, S7 parameterizing every real literal would still
# not turn this assertion green -- the note's own words are "a governance word
# AS A LITERAL" (§ 2.2 rule 2), and a `//`/`/*`/`<!--` comment is not a literal.
# `_strip_comments_for_scan` blanks `//` and `/* */` (JS/CSS) and `<!-- -->`
# (HTML) to spaces -- preserving every newline, so `_line_of` still lines up --
# tracking quotes so a comment MARKER that turns up inside a real string (a
# URL, say) is left alone; none of the 17 in-scope files hit that case today
# (`grep -rn '://'` over them is empty), so no genuine literal is at risk of
# being swallowed by the tracking itself. Verified this does not silently empty
# the assertion: every one of the 17 in-scope files still carries at least one
# hit with comments excluded (1,377 raw hits across the set fall to 841 with
# comments stripped, and the per-file minimum is 3, not 0) -- so the assertion
# keeps failing today for a real, in-code reason and `strict=True` cannot XPASS
# out from under S1.
#
# NOT FIXED HERE, same footing as assertions 2/3's own "fidelity over
# tidiness" notes: a bare identifier or property access that only READS a
# snapshot schema key (`s.documents`, `s.clusters` and their kind, all over
# `model.js`/`board.js`) still trips this sweep, even though note § 2.2 rule 3
# treats a schema key as distinct from a rendered word. Whether those sites
# need their own declared exemption (mirroring `declared_exemptions`) or a
# literal-vs-identifier-aware rewrite is left for S7 (or a further amendment)
# to decide against the real vocabulary sites it is parameterizing, rather
# than guessed at here.


def _strip_comments_for_scan(text: str, path: str) -> str:
    """Blank out this file's COMMENT syntax -- `//`/`/* */` for `.js`, `/* */`
    only for `.css` (no line-comment syntax exists), `<!-- -->` for `.html` --
    replacing every character except newlines with a space, so byte offsets
    inside a comment never match and `_line_of` still reports the original
    line for every match outside one. Quote-aware for the C-style languages
    (single/double/backtick), so a `//` or `/*` that appears INSIDE a string
    literal (a URL, say) is not mistaken for a comment opener; a file with no
    comment syntax at all (nothing under `WEB_ROOT` today besides these three
    extensions) is returned unchanged.
    """
    if path.endswith(".js"):
        return _strip_c_style_comments(text, allow_line_comments=True)
    if path.endswith(".css"):
        return _strip_c_style_comments(text, allow_line_comments=False)
    if path.endswith(".html"):
        return _strip_html_comments(text)
    return text


def _strip_c_style_comments(text: str, *, allow_line_comments: bool) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    in_string: str | None = None  # one of '"', "'", "`", or None
    in_line_comment = False
    in_block_comment = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
                out.append(c)
            else:
                out.append(" ")
            i += 1
            continue
        if in_block_comment:
            if c == "*" and nxt == "/":
                in_block_comment = False
                out.append("  ")
                i += 2
                continue
            out.append(c if c == "\n" else " ")
            i += 1
            continue
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(nxt)  # keep the escaped character verbatim too
                i += 2
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            in_string = c
            out.append(c)
            i += 1
            continue
        if allow_line_comments and c == "/" and nxt == "/":
            in_line_comment = True
            out.append("  ")
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block_comment = True
            out.append("  ")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _strip_html_comments(text: str) -> str:
    return re.sub(
        r"<!--.*?-->",
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        text,
        flags=re.DOTALL,
    )


def _governance_literal_violations() -> list[str]:
    violations = []
    for row in _assertion_4_scope():
        path = row["path"]
        text = _strip_comments_for_scan(
            (WEB_ROOT / path).read_text(encoding="utf-8"), path
        )
        for m in _GOVERNANCE_WORD_PATTERN.finditer(text):
            violations.append(f"{path}:{_line_of(text, m.start())} carries {m.group(1)!r}")
    return violations


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "docs/front-end-package-boundary.md § 2.2 rule 2 / § 4.5 point 4 "
        "(opensoft/openDox-spec #8 -> a44ac06d): the 14 class-C files (13 in "
        "the note's own § 3.1 count, +1 for views/explorer.js under Q2's "
        "ruling) and the FOUR declared class-A tails (views/docs.js, "
        "views/grouping.js, views/repo-selector-model.js, and -- added by "
        "slice S4 -- views/staging-workbench-model.js, whose class-C substance "
        "STATUS_BRAINSTORM / BRAINSTORM_AREA / STAGING_AREA is what § 3.2's "
        "own row says is left once its six class-B route constants travel; a "
        "tail rather than a reclassification, so the file enters this sweep "
        "for S7 instead of escaping it unremarked) carry the "
        "registered profile's vocabulary as LITERALS -- COLUMN_KEYS, "
        "WHEEL_KEYS/WHEEL_LABELS, board.js's four columns, styles.css's "
        "four --st-* tokens, and more (every in-scope file trips at least "
        "one hit today IN CODE, once `//`/`/* */`/`<!-- -->` prose comments "
        "are excluded from the sweep by `_strip_comments_for_scan` -- added "
        "on this PR's review, opensoft/openDox-code#13, after Copilot caught "
        "the unstripped sweep counting explanatory comments too, e.g. "
        "views/model.js's own \"docs -> clusters -> possibles -> staged "
        "picks -> proposals -> realized\" pipeline sentence). The note "
        "assigns closure to slice S7 (parameterize class C from the "
        "registered domain profile). A bare identifier or property access "
        "that only reads a snapshot schema key (`s.documents`, `s.clusters` "
        "and their kind) still trips this sweep and is NOT excluded here -- "
        "left for S7 (or a further amendment) to decide against the real "
        "sites it parameterizes, the same fidelity-over-tidiness call "
        "assertions 2 and 3 already make about their own scope."
    ),
)
def test_no_class_c_file_carries_a_governance_literal() -> None:
    violations = _governance_literal_violations()
    assert not violations, (
        f"{len(violations)} governance-literal violation(s) (showing up to 20 of them):\n"
        + "\n".join(violations[:20])
    )


# ---------------------------------------------------------------------------
# Companion check -- the two declared exemptions are REAL and OUT OF SCOPE
# (note § 2.2 rule 3: "an exemption that is silence is how a literal
# survives a vocabulary sweep"). NOT one of the note's four numbered
# assertions; passes today and stays unmarked -- it is bookkeeping on the
# fixture, not a measurement of the boundary defect.
# ---------------------------------------------------------------------------

def test_declared_governance_literal_exemptions_are_real_and_out_of_scope() -> None:
    in_scope_paths = {row["path"] for row in _assertion_4_scope()}
    for exemption in _EXEMPTIONS:
        path = exemption["path"]
        assert path in _ROWS_BY_PATH, f"declared exemption names an unclassified file: {path}"
        assert path not in in_scope_paths, (
            f"{path} is declared exempt from the governance-literal sweep, but its "
            f"census row also puts it in assertion 4's scope (class C or a declared "
            f"tail) -- the exemption is CONTRADICTED, not silent, which is worse."
        )
        assert exemption.get("reason"), f"declared exemption for {path} carries no reason"
        text = (WEB_ROOT / path).read_text(encoding="utf-8")
        assert exemption["identifier"] in text, (
            f"declared exemption names {exemption['identifier']!r}, which does not "
            f"appear in {path} -- the exemption is stale"
        )
