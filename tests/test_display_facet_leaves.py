"""THE FACET REACHES THE LEAVES, not just the mounts.

`docs/front-end-package-boundary.md` § 3.4 slice S7 installed the DISPLAY facet
at every mount (`tests/test_display_facet.py` is its proof). This file measures
the half that slice's own review found missing at its gated head: SEVEN leaves
inside those mounted modules that never read the vocabulary the mount installed
-- two of them threads Copilot opened on opensoft/openDox-code#21 at
`c7a216c782cb4ca434838490c8bae00af8cdbf38` and five more it left SUPPRESSED in
review `5192900474`'s body, where a lane reading `unresolved == 0` would never
have seen them.

Every one of the seven is the same failure, and it is not the failure
`tests/test_web_boundary.py` measures. Assertion 4 there asks whether a
governance WORD survives as a literal; six of these seven survive that sweep
untouched -- `captured` is in neither of its word lists, a mount that forwards
no option spells nothing at all, and a fallback that keeps the previous
vocabulary is a missing RESET rather than a literal. So the boundary census can
be green while a pane still renders in two vocabularies at once.

WHY THIS IS A SEPARATE ACT AND NOT PART OF #21. Every carved file it edits is a
`moved_*` row of `docs/opendox-carve-manifest.yaml`, and the S7 window that
landed with #21 (openxFactory#1030 -> `b3a75537`) does not declare these lines.
RULING Q-L1 (openxFactory#656 comment `5628560136`) says the annotation lands
FIRST, so the lines are declared on the paired openxFactory row annotation
under RULING OQ-1's closed class `adapter calls`, and this leg realizes them.
`views/display.js` is an ADMITTED created file with no manifest row (RULED
OQ-C), and so is this file.

IT STANDS ON THE SAME FOOTING as its neighbours in `validate.yml`'s narrowed
list (`test_view_registry.py`, `test_split_route_tails.py`,
`test_display_facet.py`): it imports no `opendox` submodule at all, reads
bundle files as text, and drives the REAL `views/display.js`,
`views/explorer.js` and `views/outline-model.js` under the `node` the runner
already has -- SKIPPED, never failed, where node is absent. `--noconftest` safe
and needs no consumer.

THREE OF THE SEVEN ARE PROVED BY RUNNING THE MODULE and four by reading it,
and the split is the tree's, not a preference: `applyTokens`, `drillKindWord`
and `insertSection` are reachable from a pure ES-module harness, while the
other four sites live inside render functions that need a DOM to enter. For
those four the assertion is made on the SOURCE, the same constraint
`tests/test_intent_binding_shape.py` and `tests/test_split_route_tails.py`
work under (there is no JS parser in this leg's dependency set) -- and where a
source assertion could pass on a decoration alone, a behavioural probe of the
thing it feeds sits beside it: `test_insert_section_honours_the_declared_order`
is what makes `runAddSection`'s one added argument matter.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
VIEWS = WEB / "views"
NODE = shutil.which("node")

DISPLAY_JS = VIEWS / "display.js"
DOCS_JS = VIEWS / "docs.js"
BOARD_JS = VIEWS / "board.js"
EXPLORER_JS = VIEWS / "explorer.js"
LINEAGE_JS = VIEWS / "lineage.js"
OUTLINE_MODEL_JS = VIEWS / "outline-model.js"
WORKBENCH_JS = VIEWS / "staging-workbench.js"

#: Every `views/` module that installs a MODULE-LEVEL vocabulary at its render
#: entry point. Read off the tree in `test_every_module_vocabulary_resets`
#: below rather than trusted from here; this list is what that read must find,
#: so a new module that adopts the idiom and forgets the reset is a failure
#: here and not a silent eleventh site.
RESETTING_MODULES = (
    "board.js", "canvas.js", "doc-wheel.js", "docs.js", "funnel.js",
    "grouping.js", "lineage.js", "staging-workbench.js",
    "staging-workbench-model.js", "wheel.js",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_node(source: str, tmp_path: Path):
    """Run an ES-module harness against the REAL view modules.

    The same helper `tests/test_display_facet.py` uses, for the same reason:
    the modules under test are JavaScript, and the only way to assert what one
    DOES rather than what it SAYS is to run it.
    """
    script = tmp_path / "harness.mjs"
    script.write_text(source, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _payload(**facet) -> dict:
    """The smallest `/capabilities` payload `readDisplay` accepts.

    The envelope `readDisplay` checks (`kind` and `schema_version`) wrapped
    around whatever facet keys the caller declares -- `tokens`, `stages`,
    `sections` -- exactly as `display_profile.display_manifest` publishes them:
    FLAT on the `display` object, not nested under a `facet` key.
    """
    return {"display": dict({"kind": "opendox.display-facet",
                             "schema_version": 1}, **facet)}


def _tokens(tokens: dict[str, str]) -> dict:
    """A payload declaring `tokens`, with the server's own provenance list.

    `declared_tokens` is what `applyTokens` honours: the server merges openDox's
    own values into `tokens` before the payload leaves it, so key presence on
    the wire says nothing about what the HOST wrote.
    """
    return _payload(tokens=tokens, declared_tokens=sorted(tokens))


# ---------------------------------------------------------------------------
# 1. views/display.js -- applyTokens CLEARS before it writes (suppressed 2)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_apply_tokens_clears_a_previous_facets_inline_properties(tmp_path):
    """A host-declared colour must not survive a later facet that declares none.

    `applyTokens` only ever ADDED custom properties, so re-applying after a
    host swap -- a second `/capabilities` read, a probe, a test that mounts the
    same element twice -- left `:root` carrying the OLD profile's value for
    every role the NEW one does not declare. An inline custom property outranks
    the stylesheet's own theme-aware `--st-<role>` rules, so the stale value
    won on screen. The element double below is the honest one: it records what
    `setProperty` writes and forgets what `removeProperty` clears.
    """
    out = _run_node(
        f"import * as D from {json.dumps(str(DISPLAY_JS))};\n"
        + """
const written = {};
const el = { style: { setProperty: (k, v) => { written[k] = v; },
                      removeProperty: (k) => { delete written[k]; } } };
const payloads = """ + json.dumps({
            "declaring": _tokens({"captured": "#111111",
                                 "organized": "#222222"}),
            "narrower": _tokens({"organized": "#333333"}),
            "neutral": None,
        }) + """;
const seen = {};
for (const name of ["declaring", "narrower", "neutral"]) {
  D.readDisplay(payloads[name]).applyTokens(el);
  seen[name] = { ...written };
}
console.log(JSON.stringify(seen));
""", tmp_path)
    assert out["declaring"] == {"--st-captured": "#111111",
                                "--st-organized": "#222222"}
    # THE WHOLE FINDING: `--st-captured` is GONE, not left at `#111111`.
    assert out["narrower"] == {"--st-organized": "#333333"}
    # And a facet that declares no token at all leaves the stylesheet's own
    # theme defaults in charge, which is what a neutral install must look like.
    assert out["neutral"] == {}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_apply_tokens_still_returns_the_roles_it_wrote(tmp_path):
    """The clear is additive to the contract, not a change of it: callers read
    the returned role list, and it still names exactly what was written."""
    out = _run_node(
        f"import * as D from {json.dumps(str(DISPLAY_JS))};\n"
        + """
const el = { style: { setProperty: () => {}, removeProperty: () => {} } };
const payload = """ + json.dumps(_tokens({"proposed": "#abcdef"})) + """;
console.log(JSON.stringify({
  declared: D.readDisplay(payload).applyTokens(el),
  neutral: D.neutralDisplay().applyTokens(el),
  noElement: D.neutralDisplay().applyTokens(null) ?? null,
}));
""", tmp_path)
    assert out["declared"] == ["proposed"]
    assert out["neutral"] == []
    assert out["noElement"] is None


def test_apply_tokens_clears_the_whole_closed_token_family():
    """It clears `TOKEN_ROLES`, never `this._declaredTokens` -- clearing only
    what THIS facet declares would leave exactly the stale roles the finding is
    about. Read off the source because the distinction is invisible to a probe
    that happens to declare every role."""
    text = _text(DISPLAY_JS)
    body = re.search(r"\n  applyTokens\(element\) \{(.*?)\n  \}\n", text, re.S)
    assert body, "views/display.js declares no applyTokens(element)"
    clear = re.search(r"for \(const role of (\S+)\) \{\s*"
                      r"element\.style\.removeProperty", body.group(1))
    assert clear, "applyTokens no longer clears before it writes"
    assert clear.group(1) == "TOKEN_ROLES", (
        "applyTokens clears " + clear.group(1) + ", so a role the NEW facet "
        "does not declare keeps the OLD facet's inline value -- which is the "
        "defect this test exists for")


# ---------------------------------------------------------------------------
# 2. views/explorer.js -- the stale-tile fallback title (suppressed 3)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_stale_tiles_title_renders_the_kind_by_role(tmp_path):
    """The one branch `resolveExplorerTarget` cannot reach.

    A tile whose snapshot row has gone is the ONLY place a human is shown the
    tile KIND rather than its id, and it rendered the raw `DRILL_KINDS` seam
    key: a host whose submissions are "requests" still read `proposal · REQ-14`
    in the dialog heading, inside an overlay whose every other label resolves.
    """
    facet = _payload(stages={
        "selection": {"one": "shortlist entry", "many": "shortlist entries",
                      "short": "shortlist", "label": "shortlist"},
        "submission": {"one": "request", "many": "requests",
                       "short": "requests", "label": "requests"},
        "completion": {"one": "delivery", "many": "deliveries",
                       "short": "deliveries", "label": "deliveries"}})
    out = _run_node(
        f"import * as E from {json.dumps(str(EXPLORER_JS))};\n"
        f"import * as D from {json.dumps(str(DISPLAY_JS))};\n"
        + "const host = D.readDisplay(" + json.dumps(facet) + ");\n"
        + """
const out = { host: {}, neutral: {} };
for (const kind of ["staged", "proposal", "realized"]) {
  out.host[kind] = E.drillKindWord(kind, host);
  out.neutral[kind] = E.drillKindWord(kind, D.neutralDisplay());
}
// A kind no role carries, and the absent-facet call the mount makes when the
// host declares nothing: neither may throw inside a dialog heading.
out.unknown = E.drillKindWord("nosuchkind", host);
out.noDisplay = E.drillKindWord("proposal", undefined);
console.log(JSON.stringify(out));
""", tmp_path)
    assert out["host"] == {"staged": "shortlist entry", "proposal": "request",
                           "realized": "delivery"}
    # The NEUTRAL install still reads openDox's own words, not openxFactory's.
    assert out["neutral"]["proposal"] == "submission"
    assert out["unknown"] == "nosuchkind"
    assert out["noDisplay"] == "submission"


def test_the_stale_tile_branch_calls_the_resolver():
    """The export exists and the fallback title is what uses it -- a helper
    nothing calls would pass the probe above and change no screen."""
    text = _text(EXPLORER_JS)
    assert "export function drillKindWord(" in text
    assert 'title.textContent = drillKindWord(kind, display) + " · " + id;' in text
    assert 'title.textContent = kind + " · " + id;' not in text


# ---------------------------------------------------------------------------
# 3. views/outline-model.js + views/staging-workbench.js -- the interactive
#    add takes the host's section order (suppressed 5)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_insert_section_honours_the_declared_order(tmp_path):
    """WHY `runAddSection`'s one added argument matters.

    `insertSection` places a canonical heading behind the last EARLIER template
    section present, and the template order is the registered domain's
    (`templateOrder(options.display)`). Handed no `display`, it places against
    openDox's own shipped `SECTION_ORDER` -- so with a host that orders its
    fragment differently, the same press put the same section in two different
    places depending on an argument the caller forgot.
    """
    facet = _payload(sections=["conflicts", "claims", "why"])
    fragment = "# F\n\n## Claims\n\nc\n\n## Why\n\nw\n"
    out = _run_node(
        f"import * as O from {json.dumps(str(OUTLINE_MODEL_JS))};\n"
        f"import * as D from {json.dumps(str(DISPLAY_JS))};\n"
        + "const host = D.readDisplay(" + json.dumps(facet) + ");\n"
        + "const text = " + json.dumps(fragment) + ";\n"
        + """
const headings = (t) => t.split("\\n").filter((l) => l.startsWith("## "));
const ask = { title: "Conflicts", required: true };
const withHost = O.insertSection(text, { ...ask, display: host });
const without = O.insertSection(text, ask);
console.log(JSON.stringify({
  order: D.readDisplay(""" + json.dumps(facet) + """).sections(),
  withHost: withHost.ok ? headings(withHost.text) : withHost.reason,
  without: without.ok ? headings(without.text) : without.reason,
}));
""", tmp_path)
    assert out["order"] == ["conflicts", "claims", "why"]
    # The host orders conflicts FIRST, so the section lands ahead of "Claims".
    assert out["withHost"] == ["## Conflicts", "## Claims", "## Why"]
    # openDox's own order puts conflicts seventh of nine, behind both, so the
    # SAME press on the SAME fragment lands it at the other end.
    assert out["without"] == ["## Claims", "## Why", "## Conflicts"]
    assert out["withHost"] != out["without"], (
        "this fixture no longer separates the two orders, so it can no longer "
        "prove that supplying `display` changes anything")


def test_outline_add_threads_the_mounts_own_vocabulary():
    """The add route must keep the vocabulary of the workbench that owns it."""
    text = _text(WORKBENCH_JS)
    signature = re.search(r"async function runAddSection\((.*?)\)", text)
    assert signature, "staging-workbench.js declares no runAddSection(...)"
    assert "display" in signature.group(1).split(", "), (
        "runAddSection() no longer takes a per-mount display argument, so a "
        "second workbench can overwrite the vocabulary an earlier add button uses")
    call = re.search(r"const patch = insertSection\(live\.text, \{(.*?)\}\);",
                     text, re.S)
    assert call, "staging-workbench.js no longer calls insertSection(live.text, …)"
    assert "display" in call.group(1), (
        "runAddSection() hands insertSection no per-mount display facet, so an "
        "interactive add places and duplicate-checks against the neutral "
        "SECTION_ORDER inside an outline rendered in the host's words")
    assert "display: vocab" not in call.group(1), (
        "runAddSection() still reads module state here, so two live workbenches "
        "can race each other for section order")


def test_the_outline_path_captures_the_mounts_display_once():
    """The outline callback and add controls close over the owner mount's facet."""
    text = _text(WORKBENCH_JS)
    assert "vocab = display || neutralDisplay();" in text
    assert "const mountDisplay = vocab;" in text
    assert "setDisplay(mountDisplay);" in text
    assert re.search(r"renderOutlinePanel\(pane, snapshot, scope, create, sourceBase, edit,\s*"
                     r"outlineSectionSeam\(\), mountDisplay\)", text), (
        "mountStagingWorkbench no longer threads its own display into the outline pane")
    assert "onText: (text) => renderOutlineIndex(index, text, path, sections, display)" in text
    assert "await runAddSection(seam, path, note, asked.title, asked.after,\n" \
           "                            asked.required === true, display);" in text


# ---------------------------------------------------------------------------
# 4. views/staging-workbench.js -- the nested wheel is mounted WITH the
#    vocabulary the module installed (thread 2)
# ---------------------------------------------------------------------------

def test_the_nested_doc_wheel_is_mounted_with_the_panes_vocabulary():
    """`doc-wheel.js` RESETS its module vocabulary to `opts.display ||
    neutralDisplay()` on every render, so a wheel mounted without the option
    renders neutral labels, sub-lines and ARIA text inside a workbench whose
    every other surface speaks the host's."""
    wheel = re.search(r"const wheel = renderDocWheel\(selector, entries, \{(.*?)\n  \}\)",
                      _text(WORKBENCH_JS), re.S)
    assert wheel, "staging-workbench.js no longer mounts renderDocWheel"
    assert "display: vocab" in wheel.group(1), (
        "the nested doc wheel is mounted without `display`, so one pane "
        "renders in two vocabularies")
    # The reset that makes the omission visible, asserted where it lives.
    assert "vocab = opts.display || neutralDisplay();" in _text(VIEWS / "doc-wheel.js")


# ---------------------------------------------------------------------------
# 5. views/docs.js -- the search matches the word the row DISPLAYS (thread 1)
# ---------------------------------------------------------------------------

def test_the_docs_search_indexes_both_spellings_of_the_stage():
    """A host that maps `brainstorm` to `jotted` hid every such document from a
    search for the word the user can SEE. BOTH spellings are indexed: the raw
    enum must go on matching (and two enums may map onto one word), so this is
    an addition and never a substitution."""
    haystack = re.search(r"function docHaystack\(d\) \{(.*?)\n\}",
                         _text(DOCS_JS), re.S)
    assert haystack, "views/docs.js declares no docHaystack(d)"
    body = haystack.group(1)
    assert "vocab.documentStageWord(d.stage)" in body, (
        "docHaystack indexes the raw stage enum alone, so a search for the "
        "stage word the row renders finds nothing")
    assert re.search(r"\bd\.stage\b(?!\s*\))", body), (
        "docHaystack no longer indexes the raw enum -- a search for "
        "`brainstorm` must go on working")
    # The filter and the haystack are the same function, so the index the test
    # reads is the index the search uses.
    assert "docHaystack(d).includes(state.search)" in _text(DOCS_JS)


# ---------------------------------------------------------------------------
# 6. views/board.js -- the card's date word is the column's word (suppressed 1)
# ---------------------------------------------------------------------------

def test_the_brainstorm_cards_date_metadata_resolves_the_status():
    """`columnLabel(SOURCE)` resolves the CAPTURED status through the facet
    while the metadata line beneath the same card spelled openDox's own
    `captured` as a literal. Invisible to `tests/test_web_boundary.py`
    assertion 4 -- `captured` is in neither of its word lists -- which is why a
    review round and not the census found it."""
    text = _text(BOARD_JS)
    card = re.search(r"function brainstormCard\(d, indexes\) \{(.*?)\n\}",
                     text, re.S)
    assert card, "views/board.js declares no brainstormCard(d, indexes)"
    body = card.group(1)
    assert '"captured "' not in body, (
        "brainstormCard still prefixes its date with the literal `captured`")
    assert "vocab.status(VOCABULARY.DOCUMENT, STATUS_ROLE.CAPTURED)" in body
    # The SCHEMA key is untouched: `d.dates.captured` is the snapshot's own
    # field name (§ 2.2 rule 3), not a rendered word.
    # Split, so a failure names WHICH half went (SonarCloud python:S9073).
    assert "d.dates?.captured" in body, "the optional-chained read is gone"
    assert "d.dates.captured" in body, "the date value itself is no longer rendered"


# ---------------------------------------------------------------------------
# 7. views/lineage.js -- the stats strip RESETS (suppressed 4)
# ---------------------------------------------------------------------------

def test_the_stats_strip_resets_to_the_neutral_vocabulary():
    """`|| vocab` kept the PREVIOUS render's words where this one declares
    none, so a render after a host facet was withdrawn went on speaking the
    withdrawn host's vocabulary instead of coming up visibly un-domained --
    the invisible-survival failure § 4.3 point 5's refusal rule exists to end.
    """
    text = _text(LINEAGE_JS)
    assert "vocab = opts?.display || vocab;" not in text
    assert text.count("vocab = opts?.display || neutralDisplay();") == 2, (
        "views/lineage.js has two render entry points (renderStats and "
        "renderLineage) and each must reset")


def test_every_module_vocabulary_resets():
    """THE RATCHET, and the reason this one site was findable at all: ten other
    `views/` modules install a module-level vocabulary at their render entry
    point, and every one of them resets to `neutralDisplay()`. A new module
    that adopts the idiom and carries the previous render's words forward fails
    here rather than waiting for a review round to notice."""
    carried: list[str] = []
    found: set[str] = set()
    for path in sorted(VIEWS.glob("*.js")):
        for line in _text(path).splitlines():
            stripped = line.strip()
            m = re.fullmatch(r"vocab = (.+?);", stripped)
            if not m or stripped.startswith("//"):
                continue
            found.add(path.name)
            if "neutralDisplay()" not in m.group(1):
                carried.append(f"{path.name}: {stripped}")
    assert not carried, (
        "these render entry points keep the previous render's vocabulary "
        f"instead of resetting: {carried}")
    assert found == set(RESETTING_MODULES) | {"lineage.js"}, (
        "the set of modules installing a module-level vocabulary has moved; "
        f"found {sorted(found)}")
