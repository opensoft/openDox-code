"""RULED Q7 — a contributed binding's CSS lives WITH THE BINDING, in its own sheet.

    "a contributed binding's CSS lives WITH THE BINDING, in its own sheet;
     openDox's declared design tokens (the `--st-*` family, S7) are the one
     stable styling surface; nothing else in `styles.css` is."
        — Brett Heap, 2026-09-12, `opensoft/openxFactory#656` comment `5648049748`

This is the half of that ruling openDox owes: the `styles` slot on `ViewBinding`,
the `<link>` the shell injects for it, and the PROOF that the gate loop's
selectors have left `src/opendox/web/styles.css` and that openDox's own have not.

WHAT IT HOLDS, and why each is here rather than implied:

1. THE SLOT IS VALIDATED THE WAY `module` IS, at both halves of the seam. A
   root-relative href, an absolute URL, a `..` climb and a non-string all refuse
   with `ViewBindingError` in Python and with the same refusal in the client's
   own `viewBinding()` — § 4.1's "one vocabulary, both halves", which is the
   rule the `_ENTRY` grammar was written for when the two halves disagreed about
   what a JS identifier is.
2. AN ABSENT SHEET IS AN ANSWER, NOT AN OMISSION. `styles: ""` is the default
   and the manifest carries it; measured over the six gate-loop bindings,
   `gate.lens` owns no selector of its own and declares none.
3. THE SHEET TRAVELS ON `/capabilities` WITH NO NEW ROUTE, because
   `as_manifest_entry()` carries it — which is the whole reason the field is on
   the binding and not in a second table.
4. THE LINK GOES IN `document.head`, ONCE PER HREF. RULED Q8 (same comment):
   "`document.body` is never a contract surface". The dedupe is not an
   optimisation: two bindings of one column may name the same sheet, which is
   the only shape that neither duplicates a shared rule family into two files
   nor makes one optional binding depend on another's sheet.
5. A FAILED SHEET IS NAMED AND NON-FATAL. A binding's CONTRACT is its manifest
   entry; styling is not in it. A panel that mounts unstyled is degraded, a
   panel that refuses to mount because a stylesheet 404'd is deleted.
6. `styles.css` NO LONGER CARRIES THE GATE LOOP'S SELECTORS, and still carries
   every `--st-*` token and every shared one. MEASURED HERE, against the real
   file and openDox's own bundle — not asserted from a list this file keeps,
   which would be the second authority the census exists to avoid.

WHAT THIS FILE NO LONGER HOLDS, AND WHERE IT WENT (plan 034 T037; requirement
9.4). Two cases here needed openXdox's six contributed modules or its sheets.
This leg never ships them, because RULED Q5 places them at assembly, so both
skipped on every run of this leg's suite. That is the skip 9.4 ends: behaviour
that needs both legs is an integration test at the declared composition
(FR-006). The list, with each destination, is at the end of this file:

- the re-derivation of `GATE_EXCLUSIVE` from the six modules goes to
  openXdox-code's `tests/integration/` (T042), where the six are placed in the
  pinned openDox's bundle on every run. The half that needs no assembly stays
  here and asserts for real: openDox's own bundle names none of the 54 classes;
- NO CONTRIBUTED SHEET DECLARES AN `--st-*` TOKEN is asserted where the sheets
  are, in openXdox-code's `tests/test_gate_loop_views.py`, over every sheet
  that leg declares, and beside the same guard's negative control.

`--noconftest` SAFE still, though `validate` no longer runs it that way: the
explicit list with conftest collection off (RULED Q-L5 (b')) ended with plan
034 T036. Nothing here needs a fixture, a path insertion or an installed
consumer. It imports `opendox.view_extension` alone, reads bundle files as
text, and drives the real `views/view_extension.js` under the `node` the runner
already has — skipped, never failed, where node is absent, exactly as
`tests/test_view_registry.py` and `tests/test_split_route_tails.py` do.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from opendox.view_extension import ViewBinding, ViewBindingError

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
STYLES = WEB / "styles.css"
REGISTRY_JS = WEB / "views" / "view_extension.js"
NODE = shutil.which("node")

#: The six modules openXdox contributes (RULED Q5's package data). They are NOT
#: in this repository — slice S5 sent them to openXdox-code — and no case here
#: reads the real ones any more: the one that did is an integration test at
#: the composition now (plan 034 T037 → T042). The names stay because a
#: developer's assembly may have placed the six in this bundle, and openDox's
#: own corpus must EXCLUDE them there, or a class only they name would read as
#: openDox's (`_own_bundle_text()`). The exclusion case below writes six
#: stand-ins under these names into a throwaway bundle, to drive that rule.
GATE_MODULES = ("gate.js", "gate-lens.js", "gate-projects.js", "dispose.js",
                "swb-create.js", "swb-session.js")

#: The 54 classes the census measures as the gate loop's own at openDox-code
#: `0b4e8bbf` / openXdox-code `0a0265f7` — every class named by one of the six
#: modules and by NO file of openDox's own bundle. Declared here so assertion 6
#: is a claim about THIS tree, where the six modules are absent. Two cases read
#: it: `styles.css` declares none of these classes, and openDox's own bundle
#: names none of them. That the six modules name every one, and that no class
#: they alone name is left in `styles.css`, needs both legs, so it is
#: re-derived at the composition (T042), where a drift in this tuple is refused.
#: Here the orphan register below is the proof that reads no tuple, so a class
#: this one never heard of still cannot be left behind unseen.
GATE_EXCLUSIVE = (
    "dispose-accepted", "dispose-deferred", "dispose-propose", "dispose-rejected",
    "disposetray", "gatebar", "gatebar-actions", "gatebar-cmd", "gatebar-title",
    "gatebtn", "gatebtn-live", "intentchips", "is-busy", "is-error", "is-ok",
    "is-queued", "is-refused", "is-stalled", "panelbuttons", "panelfield",
    "panelhead", "panellabel", "panelmembers", "panelnote", "projectform",
    "projectmember", "projectname", "projectpanel", "refusalpanel",
    "refusalpanel-clear", "refusalpanel-head", "refusalpanel-item",
    "refusalpanel-kind", "refusalpanel-list", "refusalpanel-msg",
    "refusalpanel-title", "swb-cactions", "swb-ccmd", "swb-cdescriptor",
    "swb-cform", "swb-ch", "swb-chelp", "swb-clanded", "swb-cline", "swb-cnote",
    "swb-crefused", "swb-creq", "swb-cresult", "swb-csource", "swb-cwrap",
    "swb-notice", "swb-sessionactions", "swb-sessionbtn",
    "swb-sessiondescriptors",
)

#: THE ORPHAN REGISTER — every class `styles.css` still declares in a selector
#: that NO file of openDox's own bundle names, MEASURED after the extraction.
#: This is the tuple-free half of the proof, and it is the one that runs in a
#: checkout with no assembly (Copilot review, round 1: the re-derivation test
#: SKIPPED here, and has since left for the composition, plan 034 T037, so a
#: gate-only class this file's `GATE_EXCLUSIVE` never heard of could be left
#: behind and nothing in this leg would say so). A class openDox does not
#: name is either one of these declared orphans or a rule that belongs at
#: another leg — there is no third kind — so a NEW one fails, whatever tuple
#: does or does not mention it.
#:
#: WHAT THEY ARE, and none of them is this act's: 6 `.intentchip*` are the
#: hosted intent feed's, whose builder (`views/intent-feed.js`) is RULED OQ-F
#: `not_moved` and never arrived, so `views/intent-binding.js` delegates to an
#: absent module; the rest are rules whose builders the carve left elsewhere or
#: which the bundle stopped using. They are REGISTERED here rather than swept:
#: a register that names 30 is a measurement, and a test that skipped them
#: silently was the defect.
STYLES_CSS_ORPHANS = (
    # `divider` and `ghost` JOINED THE REGISTER when comments stopped counting
    # as ownership evidence (Copilot review, round 2): openDox's bundle names
    # each of them in a comment and nowhere else, which is precisely the
    # evidence that finding says must not count — and it is the register, not
    # the extraction, that the correction moved.
    "divider", "filteradd", "ghost", "gridwrap", "intentchip",
    "intentchip-applied",
    "intentchip-error", "intentchip-pending", "intentchip-refused",
    "intentchip-stalled", "managepane", "sigrid-collab", "sigrid-row",
    "sigrid-rowlab", "swb-bar", "swb-bar-fill", "swb-completeness",
    "swb-inheritedhead", "swb-name", "swb-nobar", "swb-row",
    "swb-row-selected", "swb-rowinfo", "swb-score", "swb-sectionhead",
    "swb-sectionlabel", "swb-sectionnote", "swb-signals", "swb-unresolved",
    "swb-where",
)

#: THE SHARED HALF — every class named by openDox's own bundle AND by
#: openXdox's six contributed modules, measured at openDox-code `0b4e8bbf` /
#: openXdox-code `0a0265f7` by `measure_opendox_css_census.py`'s class-bearing
#: scan (openxFactory `scripts/`). **18** today; `STYLE_RESIDUE` recorded 24 at
#: `cb343ae8`; slice S7 retired `possible` / `proposal` / `rejected`, and `why`
#: left when the census stopped counting a bare literal in a non-class position
#: (Copilot review of openxFactory #1068, round 3). `g`, `lens` and `topic`
#: left on that review's ROUND 5, when the gate-side scan was narrowed again:
#: a `.token` counts only inside a literal shaped like a selector with the dot
#: in selector position, and an assignment only where the target is
#: class-named, so `"e.g. Field Pilots"` (gate-projects.js), `"gate.lens: ..."`
#: (gate-lens.js) and `btn.title = "... this staging topic "` (dispose.js:402)
#: stop naming them. THE EXTRACTION IS UNCHANGED BY THAT — 54 gate-exclusive
#: classes, the same 59 blocks at the same extents, 89 lines — because a class
#: leaving the SHARED bucket for openDox's own is a class that stays either
#: way. These STAY in `styles.css` — they are openDox's, and a class both
#: columns name was never a candidate to leave.
SHARED_CLASSES = (
    "cbtn", "dc-h", "dc-line", "dc-note", "dispose-intile", "disposebtn",
    "docstatus", "member", "name", "reason-form", "repobtn",
    "repopick-msg", "rf-label", "swb-cbtn", "swb-cfield", "swb-clabel",
    "swb-cslot", "tile",
)

#: The ONE openDox class a contributed sheet names as its HOST CONTEXT:
#: `.swb-draftchrome .swb-cactions` places the create affordance's action row
#: inside openDox's own draft chrome. Declared, so it is a known coupling rather
#: than a silent one.
HOST_CONTEXT_CLASSES = ("swb-draftchrome",)


def _binding(**over) -> ViewBinding:
    spec = dict(id="gate.bar", region="viewer-gatebar", module="./views/gate.js",
                entry="mountGateBar", view_class="B")
    spec.update(over)
    return ViewBinding(**spec)


def _blank_css_comments(css: str) -> str:
    """`/* … */` blanked, newlines kept — a selector scan must not read prose."""
    out, i, n = [], 0, len(css)
    while i < n:
        if css.startswith("/*", i):
            j = css.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", css[i:j]))
            i = j
            continue
        out.append(css[i])
        i += 1
    return "".join(out)


def _selector_classes(css: str) -> set[str]:
    """Every class token declared in a SELECTOR, comments and bodies excluded.

    The body is excluded because `content: ".foo"` and a `url(.../x.css)` are
    not selectors; the comments because openDox's prose may legitimately discuss
    a rule that has left, and a scan that read it would make the record of a
    move into a violation of it.
    """
    scan = _blank_css_comments(css)
    out: set[str] = set()
    i, n, seg = 0, len(scan), 0
    while i < n:
        c = scan[i]
        if c == "{":
            prelude = scan[seg:i]
            if not prelude.strip().startswith("@"):
                out.update(re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", prelude))
            depth, j = 1, i + 1
            while j < n and depth:
                if scan[j] == "{":
                    depth += 1
                elif scan[j] == "}":
                    depth -= 1
                j += 1
            if prelude.strip().startswith("@"):
                out |= _selector_classes(scan[i + 1:j - 1])
            i = seg = j
            continue
        if c == ";":
            seg = i + 1
        i += 1
    return out


def _blank_code_comments(text: str, html: bool = False) -> str:
    """`//`, `/* */` and `<!-- -->` blanked, QUOTE-AWARE, newlines kept.

    A COMMENT IS NOT OWNERSHIP EVIDENCE (Copilot review, round 2). The orphan
    register below asks "does openDox's own bundle NAME this class", and a raw
    concatenation answers yes for a class mentioned only in a comment or a
    docstring — so a gate-only selector left behind in `styles.css` could be
    excused by prose that never emits it, which is the one way that register
    can be talked out of a finding.

    QUOTE-AWARE and not a regex, because `"https://…"` carries a `//` inside a
    string and blanking from there would delete real code — a false GREEN is
    what this whole function is about, and a false RED for the same reason is
    no better. A local copy of `test_web_boundary.py`'s walk rather than an
    import: these files were collected `--noconftest` as top-level modules
    until plan 034 T036, and neither may depend on the other being
    importable.
    """
    out, i, n = [], 0, len(text)
    quote = ""
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if quote:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(nxt)
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if not html and c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            continue
        if html and text.startswith("<!--", i):
            j = text.find("-->", i + 4)
            j = n if j < 0 else j + 3
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
            continue
        if not html and c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        if not html and c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _own_bundle_text() -> str:
    """openDox's OWN bundle as one corpus, comments blanked: every
    `views/*.js` but the six contributed modules, then `app.js`, then
    `index.html`.

    THE SIX ARE EXCLUDED BY NAME (Copilot review, round 7). Where an assembly
    HAS placed them in this bundle, a plain glob sweeps them into openDox's
    own corpus, and a class only they name would read as named by openDox —
    hiding exactly the left-behind selector the orphan scan exists to catch.
    """
    own = "\n".join(_blank_code_comments(p.read_text(encoding="utf-8"))
                    for p in sorted((WEB / "views").glob("*.js"))
                    if p.name not in GATE_MODULES)
    own += _blank_code_comments((WEB / "app.js").read_text(encoding="utf-8"))
    own += _blank_code_comments((WEB / "index.html").read_text(encoding="utf-8"),
                                html=True)
    return own


def _class_namer(corpus: str):
    """`names(token)`: does `corpus` name the class `token`?

    As a whole token, or by a PREFIX the code concatenates onto:
    `"swb-pane-" + kind` and `` `x-${kind}` `` name a class that no literal
    search can see, because the name is never written down whole.
    """
    prefixes = re.findall(r"[\"\'`\s]([A-Za-z_][A-Za-z0-9_-]*-)(?:[\"\'`]|\$\{)",
                          corpus)

    def names(token: str) -> bool:
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])",
                     corpus):
            return True
        return any(token.startswith(prefix) for prefix in prefixes)

    return names


# ---------------------------------------------------------------------------
# 1-3. The slot.
# ---------------------------------------------------------------------------

def test_a_binding_may_name_one_bundle_relative_sheet() -> None:
    binding = _binding(styles="./views/gate.css")
    assert binding.styles == "./views/gate.css"
    assert binding.as_manifest_entry()["styles"] == "./views/gate.css"


def test_the_single_specifier_shape_is_cited_as_ruled() -> None:
    """ONE SHEET PER BINDING, AND TWO BINDINGS MAY NAME THE SAME ONE — the
    measured shape, and a RULED one.

    The alternative (a tuple of specifiers with a shared sheet beside each
    binding's own) was put to Brett Heap with the measurement that raised it
    and refused: RULED openxFactory#656 comment `5700475319`, 2026-09-16, by
    interactive multi-choice. The citation is asserted rather than trusted, so
    a successor widening the field has to move the reference with it instead of
    leaving a sentence that attributes its own choice to a ruling.
    """
    source = (ROOT / "src" / "opendox" / "view_extension.py").read_text(
        encoding="utf-8")
    assert "5700475319" in source
    assert ViewBinding.__dataclass_fields__["styles"].type in ("str", str)


def test_a_binding_with_no_sheet_is_the_default_and_is_carried() -> None:
    """RULED Q7's absent case, which `gate.lens` is the measured instance of."""
    binding = _binding()
    assert binding.styles == ""
    assert binding.as_manifest_entry()["styles"] == ""


@pytest.mark.parametrize("bad", [
    "/views/gate.css",                     # root-relative breaks a served sub-path
    "https://cdn.example/gate.css",        # § 4.4: no CDN, no remote asset
    "//cdn.example/gate.css",              # protocol-relative is the same reach
    "./views/gate.js",                     # a module is not a sheet
    "views/gate.css",                      # not bundle-relative at all
    "./views/../../etc/passwd.css",        # climbs out of the bundle
    "./views/gate.css\n",                  # Python's `$` admits it, JS's does not
])
def test_a_malformed_sheet_refuses_where_it_is_declared(bad: str) -> None:
    with pytest.raises(ViewBindingError) as exc:
        _binding(styles=bad)
    assert "styles" in str(exc.value)
    assert "gate.bar" in str(exc.value)


def test_a_sheet_that_is_not_a_string_refuses() -> None:
    with pytest.raises(ViewBindingError) as exc:
        _binding(styles=["./views/gate.css"])
    assert "not a string" in str(exc.value)


# ---------------------------------------------------------------------------
# 1 and 4-5. The client half, under the real registry.
# ---------------------------------------------------------------------------

_HARNESS = """
import { viewBinding, injectBindingStyles, ViewBindingError }
  from %(registry)s;

const out = { refusals: [], injected: [], deduped: null, warned: null };

// `null` IS IN THIS LIST DELIBERATELY (Copilot review, round 1): the Python
// seam refuses `styles=None` as a non-string, and a client that accepted it
// and normalized it to "" would be § 4.1's "one vocabulary, both halves"
// broken for the second time on this module. Omission and "" are the two
// absent forms and `null` is neither.
// `"./views/gate.css\\n"` IS IN THIS LIST FOR THE SAME REASON (Copilot review,
// round 6). This act rests on Python's `\\Z` and JavaScript's `$` refusing a
// trailing newline ALIKE — the Python half parameterizes exactly that input at
// `test_a_malformed_sheet_refuses_where_it_is_declared` — and the client half
// never exercised it, so a `SHEET` regex that regressed to `$` under the `m`
// flag would have left this suite green with the two halves disagreeing.
for (const bad of ["/views/gate.css", "https://cdn.example/g.css",
                   "./views/gate.js", "./views/../x.css",
                   "./views/gate.css\\n", 7, null]) {
  try {
    viewBinding({ id: "gate.bar", region: "viewer-gatebar",
                  module: "./views/gate.js", entry: "mountGateBar",
                  view_class: "B", styles: bad });
    out.refusals.push(null);
  } catch (e) {
    out.refusals.push(e instanceof ViewBindingError ? "refused" : "wrong-type");
  }
}
out.absent = viewBinding({ id: "gate.lens", region: "lens-gate",
                           module: "./views/gate-lens.js", entry: "mountLensGate",
                           view_class: "B" }).styles;
out.absentEmpty = viewBinding({ id: "gate.lens", region: "lens-gate",
                                module: "./views/gate-lens.js",
                                entry: "mountLensGate", view_class: "B",
                                styles: "" }).styles;

// A DOM stub, for `test_view_registry.py`'s reason: this bundle ships no DOM
// implementation and the injector's whole contract is which element it appends
// to and how many times.
const made = [];
const head = { appendChild(node) { made.push(node); } };
const body = { appendChild() { throw new Error("body is never a contract surface"); } };
const doc = { head, body, createElement(tag) {
  const node = { tagName: tag, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
  return node;
} };

const one = { id: "gate.workbench.create", styles: "./views/swb.css" };
const two = { id: "gate.workbench.session", styles: "./views/swb.css" };
const root = new URL("file:///bundle/");
injectBindingStyles(one, root, doc);
injectBindingStyles(two, root, doc);
injectBindingStyles({ id: "gate.lens", styles: "" }, root, doc);
out.injected = made.map((n) => [n.tagName, n.rel, n.href, n.attrs["data-view-binding"]]);
out.deduped = made.length;

// A failed sheet is NAMED and does not throw.
const warnings = [];
const realWarn = console.warn;
console.warn = (m) => warnings.push(String(m));
const link = made[0];
link.onerror();
console.warn = realWarn;
out.warned = warnings;

console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed on this runner")
def test_the_client_half_validates_and_injects(tmp_path: Path) -> None:
    script = tmp_path / "harness.mjs"
    script.write_text(_HARNESS % {"registry": json.dumps(REGISTRY_JS.as_uri())},
                      encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    # SEVEN, not six: the seventh is `"./views/gate.css\n"`, the newline case
    # the Python half already parameterizes (Copilot review, round 6).
    assert out["refusals"] == ["refused"] * 7, out["refusals"]
    assert out["absent"] == ""
    assert out["absentEmpty"] == ""
    # ONE link for two bindings naming one sheet, and none for the binding that
    # declares no sheet.
    assert out["deduped"] == 1, out["injected"]
    tag, rel, href, owner = out["injected"][0]
    assert (tag, rel) == ("link", "stylesheet")
    assert href == "file:///bundle/views/swb.css"
    assert owner == "gate.workbench.create"
    assert len(out["warned"]) == 1
    assert "swb.css" in out["warned"][0]
    assert "UNSTYLED" in out["warned"][0]


# ---------------------------------------------------------------------------
# 6. The extraction itself.
# ---------------------------------------------------------------------------

def test_styles_css_declares_no_selector_only_the_gate_loop_uses() -> None:
    """RULED Q7's own sentence, measured against the file.

    EVERY class in `GATE_EXCLUSIVE` is gone from `styles.css`'s selectors. The
    two MIXED rules the census found are handled and not exempted:
    `.filterpop[hidden], .projectform.projectpanel[hidden]` was SPLIT (openDox
    keeps its half) and `.swb-draftchrome .swb-cactions` MOVED whole.
    """
    declared = _selector_classes(STYLES.read_text(encoding="utf-8"))
    leftover = sorted(set(GATE_EXCLUSIVE) & declared)
    assert leftover == [], (
        "styles.css still declares selectors only openXdox's six contributed "
        f"modules use: {leftover}. RULED Q7 sends them to the binding's own "
        "sheet (openxFactory#656 comment 5648049748)")
    # openDox's own half of the one SPLIT rule stayed.
    assert ".filterpop[hidden]" in STYLES.read_text(encoding="utf-8")

    # AND THE PROOF THAT DOES NOT READ `GATE_EXCLUSIVE` AT ALL, which is the
    # one that runs in a checkout with no assembly: every class this file still
    # declares is named by openDox's own bundle, or is one of the DECLARED
    # orphans. A gate-only selector left behind is named by neither — and a
    # tuple that forgot it cannot hide it, because this assertion never reads
    # the tuple.
    # The corpus excludes the six contributed modules by name wherever an
    # assembly has placed them (Copilot review, round 7): `_own_bundle_text()`.
    named_by_opendox = _class_namer(_own_bundle_text())

    unnamed = sorted(t for t in declared if not named_by_opendox(t))
    assert unnamed == sorted(STYLES_CSS_ORPHANS), (
        "the set of classes `styles.css` declares and openDox's own bundle does "
        "not name has changed. New: "
        f"{sorted(set(unnamed) - set(STYLES_CSS_ORPHANS))}; gone: "
        f"{sorted(set(STYLES_CSS_ORPHANS) - set(unnamed))}. A NEW one is either "
        "a rule this extraction should have taken to the binding that owns it, "
        "or a new orphan to register here with its reason")


def test_the_design_tokens_and_the_shared_selectors_stayed() -> None:
    """The other half of the same sentence: the `--st-*` family IS openDox's."""
    css = STYLES.read_text(encoding="utf-8")
    for role in ("--st-captured", "--st-organized", "--st-proposed",
                 "--st-completion"):
        # four theme blocks declare each one: :root, the dark media query and
        # the two explicit data-theme choices (S7's own arrangement).
        assert len(re.findall(rf"^\s*{role}\s*:", css, re.M)) == 4, role
    declared = _selector_classes(css)
    # AND THE WHOLE RETAINED SET IS PINNED BY COUNT (Copilot review, round 4).
    # The shared-class assertion below protects 18 names; if the extraction had
    # taken a rule only openDox names, `declared` would simply SHRINK and both
    # that check and the orphan register — which examines only what remains —
    # would still pass. This figure is a CENSUS FIGURE on the same footing as
    # `tests/fixtures/web_boundary_census.yaml`'s `loc`: it moves when openDox
    # adds or removes a rule of its own, and then it is re-derived and the
    # commit says which. It does NOT move for this act any more, because this
    # act is finished; a change to it in a Q7 follow-up is a rule that left
    # when it should not have.
    assert len(declared) == 572, (
        f"`styles.css` declares {len(declared)} classes in selectors and this "
        "census says 572. If a rule LEFT, the extraction took an openDox-owned "
        "selector with it; if one arrived, re-derive this number and say so")

    # THE COMPLETE SHARED SET, not a sample of it (Copilot review, round 2).
    # Sixteen names stood here, and removing an unlisted shared rule left this
    # green — an extraction that took openDox-owned styling with it and said
    # nothing. `SHARED_CLASSES` is the census's own `shared` bucket at
    # openDox-code `0b4e8bbf` / openXdox-code `0a0265f7`: every class named by
    # BOTH columns, which is exactly the set this extraction puts at risk. A
    # class openDox alone names was never a candidate to leave.
    missing = sorted(set(SHARED_CLASSES) - declared)
    assert missing == [], (
        f"these classes are named by openDox's own bundle AND by openXdox's six "
        f"contributed modules, so they are openDox's and stay: {missing}. An "
        "extraction that took one took openDox-owned styling with it")
    # and the host-context class the one moved cross-rule names
    for host in HOST_CONTEXT_CLASSES:
        assert host in declared, host


def test_opendox_own_bundle_names_no_gate_exclusive_class() -> None:
    """THE HALF OF THE RE-DERIVATION THIS LEG PROVES ALONE, asserted on every
    run (plan 034 T037).

    Each class in `GATE_EXCLUSIVE` could leave `styles.css` only because no
    file of openDox's own bundle names it. That premise needs no assembly, so
    it is measured here, over the same comment-blanked corpus the orphan scan
    reads. An element of openDox's own that started to carry one of these
    classes would render unstyled wherever the contributed sheet is absent, a
    lone install included, because the class's only rule is in that sheet now.

    This loop used to run only inside
    `test_the_gate_exclusive_set_is_re_derived_where_the_modules_are_present`,
    which skipped on every run of this leg's suite, because the six modules
    are never here. The rest of that case needs both legs, and it is an
    integration test at the composition now (T042; the record is below).
    """
    names = _class_namer(_own_bundle_text())
    named = sorted(token for token in GATE_EXCLUSIVE if names(token))
    assert named == [], (
        "openDox's own bundle names these gate-loop classes, whose only rules "
        f"left `styles.css` for a contributed sheet (RULED Q7): {named}. An "
        "element that carries one renders unstyled in a lone install")


def test_the_own_bundle_corpus_leaves_out_an_assembled_contributed_module(
        tmp_path: Path, monkeypatch) -> None:
    """THE EXCLUSION, DRIVEN (Copilot review of openDox-code#55 at `7f98b46f`).

    No run of this leg's suite has the six in its bundle, so the real
    `_own_bundle_text()` never has anything to leave out, and dropping its
    `if p.name not in GATE_MODULES` would leave every case above green. That
    line is load-bearing wherever an assembly HAS placed the six: without it a
    class only they name reads as openDox's own, which is the false ownership
    the orphan scan and the case above would then accept. So a throwaway
    bundle is assembled here. It has one view of openDox's own, `app.js`,
    `index.html`, and all six contributed modules, each naming a gate-only
    class. The corpus reads openDox's view and none of the six.
    """
    views = tmp_path / "views"
    views.mkdir()
    (views / "docs.js").write_text('export const own = "docpanel";\n',
                                   encoding="utf-8")
    placed = dict(zip(GATE_MODULES, GATE_EXCLUSIVE))
    for module, cls in placed.items():
        (views / module).write_text(f'export const cls = "{cls}";\n',
                                    encoding="utf-8")
    (tmp_path / "app.js").write_text("// the shell\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "WEB", tmp_path)

    names = _class_namer(_own_bundle_text())
    assert names("docpanel"), "openDox's own view must be read"
    leaked = sorted(cls for cls in placed.values() if names(cls))
    assert leaked == [], (
        f"the own-bundle corpus read {leaked} from the contributed modules; "
        "they must be left out by name wherever an assembly placed them")


# ---------------------------------------------------------------------------
# WHAT LEFT THIS FILE, AND WHERE IT WENT (plan 034 T037; requirement 9.4).
#
# Two cases here read openXdox's six contributed modules or its sheets, and so
# SKIPPED on every run of this leg's suite: this leg never ships them, because
# RULED Q5 places them at assembly. That is the skip 9.4 ends, and FR-006
# sends behaviour that needs both legs to an integration test at the declared
# composition. Two more cases served only those two. The pull request that
# removed all four lists each one with its destination, and T049 checks that
# each arrived.
#
# - `test_the_gate_exclusive_set_is_re_derived_where_the_modules_are_present`
#   goes to openXdox-code's `tests/integration/` (T042). There the six are
#   placed in the pinned openDox's bundle on every run, so its derivation
#   asserts for real: no class that the six name and no openDox file names is
#   still declared in `styles.css`, and each of the 54 classes is named by one
#   of the six. Its openDox-only loop stays above, as
#   `test_opendox_own_bundle_names_no_gate_exclusive_class`.
# - `test_a_partial_assembly_is_a_failure_and_not_a_skip`, with its helper
#   `_assembled_views()`, goes to the same place. Its rule existed so that a
#   partial assembly could not hide behind the case above's skip.
# - `test_no_contributed_sheet_declares_a_design_token` is asserted for real
#   where the sheets are: openXdox-code's `tests/test_gate_loop_views.py`
#   carries a case of the same name, over every sheet that leg declares (at
#   openXdox-code `e28930bf`). This leg's version scanned an ASSEMBLED bundle's
#   `views/**/*.css` recursively, and that scan goes to T042 with the first.
# - `test_the_design_token_guard_sees_an_inline_declaration`, with its helper
#   `_declared_st_tokens()`, is the guard's negative control. openXdox-code's
#   `tests/test_gate_loop_views.py` carries the same case, with the same regex,
#   beside the case it guards.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(NODE is None, reason="node is not installed on this runner")
def test_a_failed_sheet_is_forgotten_so_the_next_render_may_retry(
        tmp_path: Path) -> None:
    """THE DEDUPE IS ABOUT ONE SUCCESSFUL INJECTION, NOT ONE ATTEMPT EVER
    (Copilot review, round 5).

    The href joins the per-document set BEFORE the fetch resolves — it has to,
    or two bindings naming one sheet in the same pass would each inject a link
    — so a transient 404 would otherwise be PERMANENT: every later render would
    see the href as already injected and skip it, and the panel would stay
    unstyled until a full page reload.
    """
    script = tmp_path / "retry.mjs"
    script.write_text("""
import { injectBindingStyles } from %(registry)s;
const made = [];
const head = { appendChild(n) { made.push(n); n.parentNode = head; },
               removeChild(n) { n.parentNode = null; } };
const doc = { head, body: { appendChild() { throw new Error("body"); } },
              createElement: (tag) => ({ tagName: tag, attrs: {},
                setAttribute(k, v) { this.attrs[k] = v; } }) };
const b = { id: "gate.bar", styles: "./views/gate.css" };
const root = new URL("file:///bundle/");
injectBindingStyles(b, root, doc);
const second = injectBindingStyles(b, root, doc);   // deduped: no second link
made[0].onerror();                                   // the fetch fails
const third = injectBindingStyles(b, root, doc);     // may retry now
console.log(JSON.stringify({
  deduped: second === null, retried: third !== null, links: made.length,
  detached: made[0].parentNode === null }));
""" % {"registry": json.dumps(REGISTRY_JS.as_uri())}, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["deduped"] is True        # a successful href injects once
    assert out["retried"] is True        # a FAILED one does not block forever
    assert out["links"] == 2
    assert out["detached"] is True       # and the dead link leaves the document


@pytest.mark.skipif(NODE is None, reason="node is not installed on this runner")
def test_the_generic_mount_pass_puts_the_sheet_in_the_document_it_mounts_into(
        tmp_path: Path) -> None:
    """THE SHEET FOLLOWS THE PANEL (Copilot review, round 1).

    `mountContributedViews` chooses its own `document` — a caller may mount into
    an iframe, a probe document or a test one — and it used to resolve each
    binding with `resolveBinding(binding)`, which forwards nothing. The panel
    then landed in the supplied document and its stylesheet in the global one,
    or nowhere at all where there is no global: a binding mounted UNSTYLED, with
    nothing refused and nothing logged, which is the failure class this whole
    seam exists to replace.

    Driven against the REAL registry in a throwaway bundle, because the claim is
    about which document the `<link>` reaches and no source read can make it.
    """
    web = tmp_path / "web"
    (web / "views").mkdir(parents=True)
    (web / "package.json").write_text('{"private": true, "type": "module"}\n',
                                      encoding="utf-8")
    (web / "views" / "view_extension.js").write_bytes(REGISTRY_JS.read_bytes())
    (web / "views" / "panel.js").write_text(
        "export function mount(host) { host.mounted = true; return 'ok'; }\n",
        encoding="utf-8")
    (web / "views" / "panel.css").write_text(".p { color: red; }\n",
                                             encoding="utf-8")

    source = """
import { collectViewBindings, mountContributedViews }
  from %(registry)s;
const links = [];
const host = { id: "view-docs", appendChild() {} };
const doc = {
  getElementById: (id) => (id === "view-docs" ? host : null),
  head: { appendChild(node) { links.push(node); } },
  body: { appendChild() { throw new Error("body is never a contract surface"); } },
  createElement: (tag) => ({ tag, attrs: {},
                             setAttribute(k, v) { this.attrs[k] = v; },
                             appendChild() {} }),
};
const bindings = collectViewBindings([{ views: () => [
  { id: "panel.one", region: "view-docs", module: "./views/panel.js",
    entry: "mount", view_class: "B", optional: true,
    styles: "./views/panel.css" },
]}]);
await mountContributedViews(bindings, {}, {}, { document: doc });
console.log(JSON.stringify({
  mounted: host.mounted === true,
  links: links.map((n) => [n.tag, n.rel, n.href, n.attrs["data-view-binding"]]),
}));
"""
    script = tmp_path / "harness.mjs"
    script.write_text(
        source % {"registry": json.dumps((web / "views" / "view_extension.js").as_uri())},
        encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["mounted"] is True
    # ONE link, in the SUPPLIED document's head — not the global one, and not
    # `document.body` (RULED Q8), which this stub throws on.
    assert len(out["links"]) == 1, out["links"]
    tag, rel, href, owner = out["links"][0]
    assert (tag, rel, owner) == ("link", "stylesheet", "panel.one")
    assert href.endswith("/views/panel.css"), href
