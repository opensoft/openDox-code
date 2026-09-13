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
     discharges it -- and did; see the S7 block below.)
  4. THE CENSUS DECLARES ITS TOTALS and this module re-derives them, so the
     class arithmetic in the fixture's header cannot drift from its rows.

SLICE S7 (`build/s7-parameterize-class-c`) closes ASSERTION 4 and, with it, the
last two of S1's four register nits -- the ones item 3 above leaves to "the
slice that discharges it". Three things changed:

  a. THE ASSERTION IS REWRITTEN TO THE RULE, not to a word search. S1's own
     "NOT FIXED HERE" note asked for exactly this: "a bare identifier or
     property access that only READS a snapshot schema key still trips this
     sweep, even though note § 2.2 rule 3 treats a schema key as distinct from
     a rendered word ... left for S7 to decide against the real vocabulary
     sites it is parameterizing." The rule and its three per-language positions
     are stated above `_js_spans` below, with a REGEX-LITERAL-AWARE scanner
     replacing the quote-tracking strip for the sweep that has to reach zero.
     Two declared, checked exemption classes carry what is left: `style_hooks`
     and `prose_exemptions`, both DATA in the fixture beside their reasons.
  b. THE EXEMPTION TEST CHECKS A DECLARATION (nit 3): `_declares_identifier`
     demands `const`/`let`/`var`/`function`/`class` at the head of a line, so an
     identifier that survives only in a comment -- or as part of a longer name
     -- no longer answers for one that is gone.
  c. THE ROW-LEVEL `exempt:` IS CROSS-CHECKED (nit 4): held to SET EQUALITY
     against `declared_exemptions` per path, with `exempt:` accepting a list
     because `views/display.js` carries eleven declared seam tables and a
     scalar would have made ten of them invisible to the check that was
     supposed to be watching them.

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
# SLICE S7's two declared exemption classes for assertion 4 (§ 4.5 point 4's
# "an exemption that is silence is how a literal survives a vocabulary sweep",
# read the other way round: an exemption that is DECLARED and CHECKED is how a
# sweep reaches zero honestly). Both are DATA in the fixture, beside a reason,
# for the same cause as the two lists above.
#
# `prose_exemptions` is keyed by (path, literal) rather than by (path, line),
# which is where openXdox-code's `PROSE_EXEMPT` -- (module, lineno) -- has to
# be re-audited on every edit that moves a line. A literal is stable under
# reflow and cannot silently start covering a DIFFERENT string.
_PROSE_EXEMPTIONS: list[dict] = _CENSUS["prose_exemptions"]
_PROSE_EXEMPT_BY_PATH: dict[str, set[str]] = {}
for _row in _PROSE_EXEMPTIONS:
    _PROSE_EXEMPT_BY_PATH.setdefault(_row["path"], set()).add(_row["literal"])


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
    # `/source` AND `/source/` LEFT THIS PATTERN AT SLICE S6 — RULED Q4 (Brett
    # Heap, 2026-09-12, opensoft/openxFactory#656 comment 5642758731):
    # "`/source/` is openDox's, and openXdox's projection binding keeps only
    # `/snapshot-index.json` and the three `/projections/*` routes." The pair is
    # a FIXED CORE ARM of `opendox/serve.py` now (`SOURCE_PREFIX`,
    # `BARE_SOURCE_ROUTE`, `_serve_source`, `_refuse_bare_source`), so a class-A
    # or class-C file addressing it is no longer naming ANOTHER column's route —
    # it is naming its own product's. That is why S6 discharges four sites
    # without editing one line of the four files that carry them (§ 5 row S6:
    # "`views/viewer.js` and `views/wheel.js`:97 become clean"): the note's
    # remedy for the census's ONE class-A breach was always to move the ROUTE,
    # not the file. The § 3.3 ownership table this dict transcribes is amended
    # by the same ruling; the note's own § 3.3 predates it.
    "openXdox's projection routes (serve_projection.py)": re.compile(
        r'["\']/(?:snapshot-index\.json|projections/(?:evidence|workbench|role-authority))["\']'
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


# ASSERTION 2 IS GREEN. The `xfail(strict=True)` that stood here from slice S1
# comes off at slice S5, which is the slice its own last revision named — and it
# comes off because the count is ZERO, measured, not because the marker was
# tidied away.
#
# THE ARITHMETIC, since every slice moved it: 18 at S1 -> 20 at S3 (which added
# `app.js`'s `gate.bar` entry and closed none) -> 12 measured after S4, 10 in
# scope (S4 CLEARS ALL TWELVE SPLIT-FILE SITES the note's point-2 table assigns
# to it — `views/lens-model.js`:1036/1037, `views/repo-selector.js`:33/39/43/46,
# `views/staging-workbench-model.js`:543/817/818/821/822/826 — every one of
# those constants now sitting in a class-B file, exempt by construction, which
# is RULED Q3 in force rather than described; and S4 gives this assertion the
# DECLARED EXCEPTION the note's own last paragraph states for `views/lens.js`)
# -> 8 measured, 6 in scope once S6 is also applied (RULED Q4, openxFactory#656
# comment `5642758731`: the four openXdox projection sites clear because
# `/source/` is openDox's own fixed core arm now, so naming it is the boundary
# working rather than breaking — no file changed, the ROUTE moved) -> 0 HERE.
#
# THE LAST SIX WERE ALL ONE FAMILY AND ALL IN ONE PLACE: `app.js`'s CORE arm,
# the `gate.bar` entry (S3) and the `gate.lens` / `gate.projects` entries (S4),
# each a class-B binding's `routes:` declaration sitting in a class-A file —
# "a real breach by this assertion's own rule only while the entry sits in
# app.js rather than in the class-B module it names", as the census row said of
# them. They closed the way that row predicted: the six class-B modules LEFT
# this bundle for openXdox-code's package data and their bindings arrive
# through `contributedViewBindings()` (RULED Q5, openxFactory#656 comment
# `5648044785`), so `app.js` carries no gate route literal at all.
#
# NOT IN SCOPE, by declaration rather than by silence: `views/lens.js`'s two
# openxFactory-lane sites, `/actions/dtn-seed` and `/actions/staging-seed`,
# declared in the census's `route_ownership_exceptions` with the ruling gap
# beside them. None of Q1–Q5 rules on that file, so they clear on no slice's
# schedule — "they never entered it".
def test_no_ownership_violation_outside_class_b() -> None:
    violations = _route_ownership_violations()
    assert not violations, f"{len(violations)} route-ownership violation(s):\n" + "\n".join(violations)


def test_the_route_ownership_exceptions_are_real_and_still_present() -> None:
    """Assertion 2's exception list cannot outlive its cause, on the same
    reasoning `declared_transitional_rows` already stands on (note § 4.5
    point 2's own last paragraph, applied to the declaration this time
    instead of to the class-A/C sweep): a stale exception that keeps
    excluding a route nobody re-measures is how a real breach hides behind a
    label the site no longer earns. This module's own comment above
    `route_ownership_exceptions` in the fixture says "each route is checked
    to be really present in the file it exempts" -- this test is that check,
    not just the claim of it.

    Unmarked and passing: bookkeeping on the fixture, not a measurement of
    the boundary defect.
    """
    for exception in _ROUTE_EXCEPTIONS:
        path = exception["path"]
        row = _ROWS_BY_PATH.get(path)
        assert row is not None, (
            f"route_ownership_exceptions names {path}, which carries no census row"
        )
        assert exception.get("reason"), f"{path}'s route exception carries no reason"
        assert exception.get("until"), (
            f"{path}'s route exception names nothing that would discharge it; "
            f"an exception with no exit is a permanent one wearing a label"
        )
        routes = exception.get("routes")
        assert routes, f"{path}'s route exception declares no routes at all"
        text = (WEB_ROOT / path).read_text(encoding="utf-8")
        for route in routes:
            quoted = (f'"{route}"' in text) or (f"'{route}'" in text)
            assert quoted, (
                f"{path}'s route exception names {route!r}, which is not actually "
                f"present in the file as a string literal any more -- the "
                f"exception has outlived its site and is now excluding nothing, "
                f"or excluding the wrong thing"
            )


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


# ---------------------------------------------------------------------------
# THE RULE (slice S7). Assertion 4 was a WORD SEARCH over the whole file with
# comments stripped; it is now a sweep over the positions a governance word can
# actually reach a human or a domain from, one rule per language. The reason is
# the one S1's own "NOT FIXED HERE" note left open: "a bare identifier or
# property access that only READS a snapshot schema key (`s.documents`,
# `s.clusters`) still trips this sweep, even though note § 2.2 rule 3 treats a
# schema key as distinct from a rendered word ... left for S7 to decide against
# the real vocabulary sites it is parameterizing." S7 parameterized them, and
# this is that decision, written as the rule rather than as a list.
#
# THE RULE, in the note's own terms (§ 2.2 rules 2 and 3): a class-C file may
# carry no governance word in a position a HUMAN READS, and no governance word
# in a NAME that would have to change if the domain's word changed. Everything
# else in these files -- an identifier, a property access, a DOM id, a CSS
# selector, a media feature -- is machinery, and machinery is what § 2.2 rule 3
# distinguishes from vocabulary in the first place.
#
#   `.js`   STRING LITERALS ONLY, with comments AND regex literals excluded,
#           minus three declared classes: a string in KEY POSITION (it names a
#           seam, not a word -- openXdox-code's `test_no_hardcoded_status_words`
#           excludes dict keys for exactly this reason), a declared STYLE HOOK,
#           and a declared PROSE exemption.
#   `.html` TEXT NODES plus the five RENDERED attributes. `id`, `class`,
#           `aria-controls`, `aria-labelledby`, `for`, `name`, `data-*` and
#           `href` are DOM hooks by construction: `id="tab-docs"` is the handle
#           `app.js` reaches the button by, and renaming it would rename a seam,
#           not a word.
#   `.css`  CUSTOM PROPERTY NAMES and `content:` values, and nothing else --
#           RULED Q7 (openxFactory#656 comment `5648049748`) in as many words:
#           *"openDox's declared design tokens (the `--st-*` family, S7) are the
#           one stable styling surface; nothing else in `styles.css` is."* A
#           selector is the other end of a class string in a `.js` file and is
#           held by the STYLE HOOK rule there, at the end that carries the word.
#
# WHY A REGEX-LITERAL-AWARE SCANNER. `_strip_comments_for_scan` below tracks
# quotes but not regex literals, so a `/` inside a character class or a division
# that looks like one can desynchronise the walk and blank real code or leave a
# comment unblanked. It survived S1 because S1 only ever asked "does this file
# still carry a word", which no desynchronisation could make false. A sweep that
# must reach ZERO cannot be built on it, so the span walk below is the scanner,
# and `_strip_comments_for_scan` stays exactly where it was, for the assertion
# that still uses it.

_JS_REGEX_PREFIX = re.compile(
    r"(?:[=(,:;!&|?{}\[\+\-*%<>~^]|^|\breturn\b|\btypeof\b|\bcase\b|\bin\b|\bof\b"
    r"|\bnew\b|\bdelete\b|\bvoid\b|\binstanceof\b|\bdo\b|\belse\b|\byield\b"
    r"|\bawait\b)\s*$"
)


def _js_spans(text: str) -> list[tuple[str, int, int]]:
    """Every comment, string and regex-literal span in `text`, in order.

    `kind` is one of `comment`, `string`, `regex`; code between spans is not
    reported. A template literal's `${...}` substitutions are walked THROUGH
    rather than swallowed, so a governance word interpolated into a template is
    read as the code it is and a word in the template's own text is read as the
    string it is.
    """
    spans: list[tuple[str, int, int]] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            spans.append(("comment", i, j))
            i = j
            continue
        if c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append(("comment", i, j))
            i = j
            continue
        if c in "\"'`":
            quote, j = c, i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    break
                if quote == "`" and text[j] == "$" and j + 1 < n and text[j + 1] == "{":
                    depth, k = 1, j + 2
                    while k < n and depth:
                        if text[k] == "{":
                            depth += 1
                        elif text[k] == "}":
                            depth -= 1
                        k += 1
                    j = k
                    continue
                j += 1
            end = min(j + 1, n)
            spans.append(("string", i, end))
            i = end
            continue
        if c == "/":
            before = text[max(0, i - 40):i]
            if _JS_REGEX_PREFIX.search(before):
                j, in_class = i + 1, False
                while j < n:
                    ch = text[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        break
                    elif ch == "\n":
                        break
                    j += 1
                if j < n and text[j] == "/":
                    spans.append(("regex", i, j + 1))
                    i = j + 1
                    continue
        i += 1
    return spans


#: A string literal is in KEY POSITION when the first non-space character after
#: its closing quote is a `:` AND the last non-space character before its
#: opening quote is not `?`. The first half covers every object-literal key and
#: every computed-property key in this bundle; the second excludes a ternary's
#: first branch (`cond ? "a" : "b"`), which is a value a human reads and whose
#: `:` would otherwise read as a key's. Checked against the real tree: no
#: in-scope file carries a labelled statement or a `case "x":`, the two other
#: productions a bare `:` could close.
#:
#: openXdox-code's `tests/test_no_hardcoded_status_words.py` makes the same
#: exclusion for the same reason -- there over an `ast` walk, here over text,
#: because there is no JS parser in this leg's dependency set and § 4.5's own
#: test is written to that constraint.
def _in_key_position(text: str, start: int, end: int) -> bool:
    j = end
    while j < len(text) and text[j] in " \t\n\r":
        j += 1
    if j >= len(text) or text[j] != ":":
        return False
    before = text[:start].rstrip()
    return not before.endswith("?")


def _style_hook_tokens() -> set[str]:
    """Every COMPOUND class token declared in `styles.css` as a real selector.

    Compound -- it carries a `-` -- because a bare governance word is ambiguous
    between a class and a value and the sweep must not guess: `"staged"` could
    be a class name or the word a card renders, and only one of those is legal.
    `.lchip-selection` cannot be either.
    """
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
    return {t for t in re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", css) if "-" in t}


def _is_declared_style_hook(value: str, hooks: set[str]) -> bool:
    """True when EVERY governance-word-bearing token of `value` is a declared
    compound style hook. A class attribute is often several tokens
    (`"swb-pane swb-pane-docs"`), and a leading `.` makes it a selector string
    (`".swb-pane-docs"`, handed to `querySelector`); both are the same hook.
    """
    tokens = value.split()
    if not tokens:
        return False
    for token in tokens:
        bare = token[1:] if token.startswith(".") else token
        if not _GOVERNANCE_WORD_PATTERN.search(token):
            continue
        if bare not in hooks:
            return False
    return True


_HTML_RENDERED_ATTRS = ("placeholder", "title", "alt", "aria-label", "value")


def _html_read_positions(text: str) -> list[tuple[int, str]]:
    """(offset, text) for every TEXT NODE and every rendered attribute value."""
    out: list[tuple[int, str]] = []
    stripped = _strip_html_comments(text)
    for m in re.finditer(r">([^<]*)<", stripped):
        out.append((m.start(1), m.group(1)))
    attrs = "|".join(_HTML_RENDERED_ATTRS)
    for m in re.finditer(rf'\b(?:{attrs})\s*=\s*"([^"]*)"', stripped):
        out.append((m.start(1), m.group(1)))
    return out


def _css_read_positions(text: str) -> list[tuple[int, str]]:
    """(offset, text) for every custom-property NAME and every `content:` value."""
    stripped = _strip_comments_for_scan(text, "styles.css")
    out = [(m.start(), m.group(0)) for m in re.finditer(r"--[A-Za-z0-9_-]+", stripped)]
    out += [(m.start(1), m.group(1)) for m in re.finditer(r"content\s*:\s*([^;]*);", stripped)]
    return out


def _governance_literal_violations() -> list[str]:
    hooks = _style_hook_tokens()
    violations = []
    for row in _assertion_4_scope():
        path = row["path"]
        raw = (WEB_ROOT / path).read_text(encoding="utf-8")
        prose = _PROSE_EXEMPT_BY_PATH.get(path, set())
        if path.endswith(".js"):
            for kind, start, end in _js_spans(raw):
                if kind != "string":
                    continue
                value = raw[start + 1:end - 1]
                if not _GOVERNANCE_WORD_PATTERN.search(value):
                    continue
                if _in_key_position(raw, start, end):
                    continue
                if _is_declared_style_hook(value, hooks):
                    continue
                if value in prose:
                    continue
                violations.append(
                    f"{path}:{_line_of(raw, start)} carries {value[:70]!r}")
        elif path.endswith(".html"):
            for offset, value in _html_read_positions(raw):
                if not _GOVERNANCE_WORD_PATTERN.search(value):
                    continue
                if value in prose:
                    continue
                violations.append(
                    f"{path}:{_line_of(raw, offset)} renders {value.strip()[:70]!r}")
        elif path.endswith(".css"):
            for offset, value in _css_read_positions(raw):
                if not _GOVERNANCE_WORD_PATTERN.search(value):
                    continue
                if value in prose:
                    continue
                violations.append(
                    f"{path}:{_line_of(raw, offset)} names {value.strip()[:70]!r}")
        else:  # pragma: no cover -- the census admits only these three kinds
            raise AssertionError(f"no assertion-4 rule for {path}")
    return violations


# S1's ORIGINAL INSTRUMENT, kept and still measured. It is the coarse word
# search this assertion used to BE, and `test_the_rule_and_the_instrument_agree`
# below holds the two together: the rule may only ever be narrower than the
# instrument, never blind to a file the instrument still sees nothing in.
def _instrument_hits(path: str) -> int:
    text = _strip_comments_for_scan(
        (WEB_ROOT / path).read_text(encoding="utf-8"), path)
    return len(_GOVERNANCE_WORD_PATTERN.findall(text))


def test_no_class_c_file_carries_a_governance_literal() -> None:
    """ASSERTION 4, CLOSED BY SLICE S7 -- the `xfail(strict=True)` marker came
    off in the commit that closed it, which is what `strict=True` is for.

    Every governance word a class-C file used to spell is now a read of the
    display facet BY ROLE (`docs/front-end-package-boundary.md` § 4.3), and the
    two positions where a word survives are DECLARED in the census fixture and
    checked by the two tests below: `style_hooks` (compound class tokens, each
    proven a real selector) and `prose_exemptions` (keyed by path and by the
    exact literal, each proven present).
    """
    violations = _governance_literal_violations()
    assert not violations, (
        f"{len(violations)} governance-literal violation(s) (showing up to 20 of them):\n"
        + "\n".join(violations[:20])
        + "\n\nEach of these is a word a human reads. Ask the display facet for "
        "it BY ROLE -- `display.one(role)`, `display.status(vocabulary, role)`, "
        "`display.area(role)` -- or, if it really is plain English that happens "
        "to spell a watched word, declare it under `prose_exemptions` in "
        "tests/fixtures/web_boundary_census.yaml beside its reason.")


# ---------------------------------------------------------------------------
# Companion checks -- the declared exemptions are REAL, and the sweep above is
# narrower than S1's instrument without being blind. NOT among the note's four
# numbered assertions; they pass today and stay unmarked -- bookkeeping on the
# fixture and on the rule, not a measurement of the boundary defect.
# ---------------------------------------------------------------------------

#: `const X`, `let X`, `var X`, `export const X`, `function X` or a class field
#: `X:` at the head of a line -- the productions that DECLARE a name in this
#: bundle. S1's own REGISTER entry names this as defect (a): "the exemption test
#: checks TEXT PRESENCE, not a DECLARATION", so an exemption naming an
#: identifier that only appears inside a comment -- or inside the word
#: `SNAPSHOT_FIELDS_OLD` -- passed. It does not now.
def _declares_identifier(text: str, identifier: str) -> bool:
    pattern = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var|function|class)\s+"
        + re.escape(identifier) + r"\b",
        re.M)
    return bool(pattern.search(text))


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
        assert _declares_identifier(text, exemption["identifier"]), (
            f"declared exemption names {exemption['identifier']!r}, which {path} does "
            f"not DECLARE -- only mentioning it (in a comment, or as part of a longer "
            f"name) is not an exemption, it is a stale one. S1's REGISTER, defect (a)."
        )


def test_every_row_level_exempt_matches_the_declared_exemptions_for_that_path() -> None:
    """S1's REGISTER, defect (b): the census row's own `exempt:` was never
    cross-checked against `declared_exemptions`, so the row could name one
    identifier while the list named another -- or none -- and both halves of
    the fixture would read as if the file were accounted for.

    They are held to SET EQUALITY per path here. `exempt:` accepts a list,
    because `views/display.js` carries eleven declared seam tables and a scalar
    would have made ten of them invisible to this check.
    """
    declared: dict[str, set[str]] = {}
    for exemption in _EXEMPTIONS:
        declared.setdefault(exemption["path"], set()).add(exemption["identifier"])
    rows: dict[str, set[str]] = {}
    for row in _ROWS:
        if "exempt" not in row:
            continue
        value = row["exempt"]
        names = set(value) if isinstance(value, list) else {value}
        rows[row["path"]] = names
    assert rows == declared, (
        "the census rows' `exempt:` and `declared_exemptions` disagree:\n"
        + "\n".join(
            f"  {path}: row {sorted(rows.get(path, set()))} "
            f"vs list {sorted(declared.get(path, set()))}"
            for path in sorted(set(rows) | set(declared))
            if rows.get(path, set()) != declared.get(path, set())))


def test_every_declared_style_hook_is_a_real_selector() -> None:
    """The census enumerates the hooks that carry a governance word so a
    reviewer can see them; the sweep derives the legal set from `styles.css`.
    This holds the enumeration honest -- a hook that stops being a selector
    stops being legal whether or not anyone remembers to edit the list."""
    hooks = _style_hook_tokens()
    declared = _CENSUS["style_hooks"]["carrying_a_governance_word"]
    missing = [h for h in declared if h not in hooks]
    assert not missing, (
        f"{missing} are declared as style hooks carrying a governance word, but "
        f"styles.css declares no `.<token>` selector for them -- the hook is gone "
        f"and the exemption it justified is stale.")
    assert all(_GOVERNANCE_WORD_PATTERN.search(h) for h in declared), (
        "a hook that carries no governance word does not belong on this list: it "
        "is exempt by construction and listing it makes the list read as longer "
        "than the surface it describes.")


def test_every_prose_exemption_is_present_and_in_scope() -> None:
    """Keyed by (path, literal) and checked PRESENT, so a reflow cannot move an
    exemption onto a different string and a deleted sentence cannot leave a
    standing licence behind."""
    in_scope_paths = {row["path"] for row in _assertion_4_scope()}
    for exemption in _PROSE_EXEMPTIONS:
        path, literal = exemption["path"], exemption["literal"]
        assert path in in_scope_paths, (
            f"{path} is not in assertion 4's scope, so a prose exemption for it "
            f"licenses nothing and only makes the fixture read as if it did.")
        assert exemption.get("reason"), f"prose exemption for {path} carries no reason"
        assert _GOVERNANCE_WORD_PATTERN.search(literal), (
            f"{literal!r} carries no governance word, so it needs no exemption.")
        text = (WEB_ROOT / path).read_text(encoding="utf-8")
        assert literal in text, (
            f"{path} no longer carries {literal!r} -- the prose exemption is stale, "
            f"and a stale exemption is a standing licence for a string nobody wrote.")


def test_the_rule_and_the_instrument_agree() -> None:
    """The rule may be NARROWER than S1's instrument -- that is the whole point
    of S7 rewriting it -- but it may not be blind: a file the instrument still
    sees hits in must be a file the rule has a POSITION rule for, and every
    in-scope file must still be reachable by both. This is what stops a future
    edit narrowing the rule until it measures nothing, which is the failure a
    sweep that reaches zero is most exposed to.
    """
    scope = _assertion_4_scope()
    assert scope, "assertion 4's scope is empty -- the census lost its class-C rows"
    assert len(scope) == 18, (
        f"assertion 4 scopes {len(scope)} files; the note's § 3.2 count is 18 "
        f"(14 class-C + 4 declared class-A tails)")
    # every in-scope file is one of the three languages the rule speaks
    for row in scope:
        assert row["path"].endswith((".js", ".html", ".css")), row["path"]
    # and the instrument still finds the words -- in comments, in identifiers,
    # in selectors -- which is exactly what the rule now declines to count.
    still_seen = [row["path"] for row in scope if _instrument_hits(row["path"])]
    assert len(still_seen) >= 14, (
        f"only {len(still_seen)} of {len(scope)} in-scope files still trip S1's "
        f"coarse instrument. If the words have genuinely left the tree the rule "
        f"is no longer measuring anything and this companion should be retired "
        f"deliberately, not discovered later.")


def test_every_in_scope_file_reads_the_display_facet() -> None:
    """§ 4.3's own success condition, stated as a test: a class-C file that
    carries no governance literal AND asks the facet for nothing has not been
    parameterized -- it has been emptied, or it never rendered a word at all
    and should not be in this scope.

    The two files the rule reaches through another end are named here with
    their reason: `styles.css` has no import mechanism and takes its four token
    VALUES from `app.js`'s `applyTokens`, and `index.html` ships its labels
    empty and takes them from `app.js`'s `applyShellVocabulary`. Both are the
    shell reaching IN, which is § 4.3 step 3's own shape.
    """
    through_the_shell = {
        "styles.css": "--st-",
        "index.html": 'id="tab-',
    }
    missing = []
    for row in _assertion_4_scope():
        path = row["path"]
        text = (WEB_ROOT / path).read_text(encoding="utf-8")
        if path in through_the_shell:
            assert through_the_shell[path] in text, path
            continue
        # THE SIBLING IMPORT, NOT THE WORD (Copilot round 2). An `or "display"
        # in text` fallback treated a comment -- or an identifier like
        # `displayVocabulary` -- as proof that a file reads the facet, which is
        # the exact class of "an exemption that is silence" this module exists
        # to refuse. Every in-scope file that is not one of the two the shell
        # reaches INTO must import `./display.js` itself.
        if 'from "./display.js"' not in text:
            missing.append(path)
    assert not missing, (
        f"{missing} carry no governance literal and read no display facet -- a "
        f"file in assertion 4's scope renders a station's words or does not "
        f"belong in it (docs/front-end-package-boundary.md § 4.3 step 4).")
