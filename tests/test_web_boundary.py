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


def _load_census() -> dict:
    with CENSUS_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_CENSUS = _load_census()
_ROWS: list[dict] = _CENSUS["files"]
_EXEMPTIONS: list[dict] = _CENSUS["declared_exemptions"]
# Duplicates collapse silently here (a dict can only hold one value per key);
# `test_every_web_file_is_classified_exactly_once` checks the RAW list
# instead, so a duplicate row is still caught rather than swallowed by this
# convenience lookup.
_ROWS_BY_PATH: dict[str, dict] = {row["path"]: row for row in _ROWS}


def _real_web_files() -> set[str]:
    return {p.relative_to(WEB_ROOT).as_posix() for p in WEB_ROOT.rglob("*") if p.is_file()}


def _assertion_4_scope() -> list[dict]:
    """The 14 class-C files (13 in the note's own § 3.1 total, +1 for
    `views/explorer.js` under Q2's ruling) plus the three declared class-A
    tails (note § 2.2 rule 3): `views/docs.js`, `views/grouping.js`,
    `views/repo-selector-model.js`."""
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


def _route_ownership_violations() -> list[str]:
    violations = []
    for row in _ROWS:
        if row["class"] == "B":
            continue  # exempt by construction
        text = (WEB_ROOT / row["path"]).read_text(encoding="utf-8")
        for owner, pattern in _OWNED_ROUTE_PATTERNS.items():
            for m in pattern.finditer(text):
                site = f"{row['path']}:{_line_of(text, m.start())}"
                violations.append(f"{site} names {m.group(0)} ({owner})")
    return violations


@pytest.mark.xfail(
    strict=True,
    reason=(
        "docs/front-end-package-boundary.md § 4.5 point 2 (opensoft/openDox-spec "
        "#8 -> a44ac06d): 16 sites outside class B name a route another column "
        "declares. RE-DERIVED AT SLICE S6 (RULED Q4, opensoft/openxFactory#656 "
        "comment 5642758731): it was 20 (18 at S1, +2 from S3's CORE_VIEWS "
        "entry), and the FOUR /source sites CLEAR HERE -- app.js:195/196, "
        "views/viewer.js:314, views/wheel.js:97 -- not because any of those "
        "four files changed (none did) but because the route they name is "
        "openDox's own fixed core arm now, so naming it is the boundary "
        "working. The remaining 16, measured on this branch: "
        "TWELVE are the SPLIT-file sites slice S4 closes -- "
        "views/lens-model.js:1036/1037 and views/staging-workbench-model.js:"
        "543/817/818/821/822/826 (the gate prefix), views/repo-selector.js:"
        "39/43 (the gate prefix), :46 (openxFactory's apply-register-edits "
        "lane, which leaves the bundle entirely) and :33 (/snapshot-index.json, "
        "still openXdox's -- Q4 moved the /source pair and nothing else). "
        "TWO are app.js:586/598, S3's `gate.bar` CORE_VIEWS entry and its "
        "`routes: [\"/actions/gate/ratify\"]` -- a real breach by this "
        "assertion's own rule while the entry sits in app.js (class A) rather "
        "than views/gate.js (class B, exempt by construction); TRANSITIONAL, "
        "closed at S5 when the binding moves behind a host-supplied "
        "contribution and the entry leaves app.js entirely. "
        "TWO are views/lens.js:41/45, this assertion's own STANDING DECLARED "
        "exception (§ 4.5 point 2, last paragraph): none of Q1-Q5 rules on "
        "lens.js's two openxFactory-lane routes, so they do not clear on any "
        "slice's schedule and only a future ruling closes them. They are "
        "counted here rather than excluded from the grep -- S1's own "
        "'fidelity over tidiness' choice, kept -- which is why the marker "
        "stays after S4 and S5 too and only the ruling that resolves lens.js "
        "can take it off. "
        "The marker therefore STAYS at S6: § 5's row for this slice promises "
        "assertion 2 green for views/viewer.js, which it is, not the assertion "
        "green outright, which is S5's row and — on this tree's own "
        "measurement — not even S5's while lens.js stands. strict=True is what "
        "makes that honest: the moment the residue actually reaches zero this "
        "goes XPASS and red until the marker comes off."
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "docs/front-end-package-boundary.md § 1.2(b) / § 4.5 point 3 "
        "(opensoft/openDox-spec #8 -> a44ac06d): 6 sites today (was 7; slice "
        "S3 -- opensoft/openDox-code#14 -- CLOSES app.js:43 -> views/gate.js, "
        "the shell's one direct class-B import, now a registry lookup, "
        "exactly the edge § 4.1 names) -- 2 "
        "UNRESOLVED (views/dispose.js:26 and views/wheel.js:75-76 import "
        "views/intent-feed.js, RULED not_moved and absent from this leg, "
        "docs/opendox-carve-manifest.yaml:1807-1810 RULED OQ-F) and 4 "
        "CLASS-BOUNDARY remaining (app.js:45 -> "
        "views/swb-session.js, views/staging-workbench.js -> "
        "views/swb-create.js and -> views/swb-session.js, "
        "views/wheel.js:73-74 -> views/dispose.js -- all class A/C "
        "importing class B). The note's closing paragraph assigns closure "
        "to slice S2, which is the intent-feed edge only (the 2 unresolved "
        "sites); the remaining 4 class-boundary sites are the same shape "
        "S5's gate-loop contribution closes, per § 4.1/§ 5, not S2 -- S3 "
        "closes the fifth (app.js:43) on its own account, ahead of S5, "
        "because the view registry is exactly the seam that makes doing so "
        "early possible. This assertion therefore stays red after S2 and S3 "
        "alone -- flagged here rather than narrowed to fit the note's own "
        "summary."
    ),
)
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
    reason=(
        "docs/front-end-package-boundary.md § 2.2 rule 2 / § 4.5 point 4 "
        "(opensoft/openDox-spec #8 -> a44ac06d): the 14 class-C files (13 in "
        "the note's own § 3.1 count, +1 for views/explorer.js under Q2's "
        "ruling) and the three declared class-A tails (views/docs.js, "
        "views/grouping.js, views/repo-selector-model.js) carry the "
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
