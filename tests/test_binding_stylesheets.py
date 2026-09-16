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
   file and the real six modules where they are reachable — not asserted from a
   list this file keeps, which would be the second authority the census exists
   to avoid.
7. NO CONTRIBUTED SHEET DECLARES AN `--st-*` TOKEN. Reading `var(--st-…)` is
   what RULED Q7 calls the one stable styling surface; WRITING one is a second
   authority for openDox's own design tokens, and `display.applyTokens` is
   already the first.

`--noconftest` SAFE, deliberately: `validate` runs this file in the explicit
list with conftest collection off (RULED Q-L5 (b')), so nothing here may need a
fixture, a path insertion or an installed consumer. It imports
`opendox.view_extension` alone, reads bundle files as text, and drives the real
`views/view_extension.js` under the `node` the runner already has — skipped,
never failed, where node is absent, exactly as `tests/test_view_registry.py`
and `tests/test_split_route_tails.py` do.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from opendox.view_extension import ViewBinding, ViewBindingError

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
STYLES = WEB / "styles.css"
REGISTRY_JS = WEB / "views" / "view_extension.js"
NODE = shutil.which("node")

#: The six modules openXdox contributes (RULED Q5's package data). They are NOT
#: in this repository — slice S5 sent them to openXdox-code — so assertion 6
#: below reads them where an assembly has placed them and SKIPS where none has,
#: which is the same posture `tests/test_gate_loop_contributed.py` takes toward
#: the column it cannot import.
GATE_MODULES = ("gate.js", "gate-lens.js", "gate-projects.js", "dispose.js",
                "swb-create.js", "swb-session.js")

#: The 54 classes the census measures as the gate loop's own at openDox-code
#: `0b4e8bbf` / openXdox-code `0a0265f7` — every class named by one of the six
#: modules and by NO file of openDox's own bundle. Declared here so assertion 6
#: is a claim about THIS tree even in an install where the six modules are
#: absent; where they ARE present, the test re-derives the set from them and
#: refuses a drift, so this tuple can never become the second authority.
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


def _assembled_views() -> Path | None:
    """`views/` if an assembly has placed the contributed modules there."""
    views = WEB / "views"
    return views if all((views / name).is_file() for name in GATE_MODULES) else None


# ---------------------------------------------------------------------------
# 1-3. The slot.
# ---------------------------------------------------------------------------

def test_a_binding_may_name_one_bundle_relative_sheet() -> None:
    binding = _binding(styles="./views/gate.css")
    assert binding.styles == "./views/gate.css"
    assert binding.as_manifest_entry()["styles"] == "./views/gate.css"


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

for (const bad of ["/views/gate.css", "https://cdn.example/g.css",
                   "./views/gate.js", "./views/../x.css", 7]) {
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

    assert out["refusals"] == ["refused"] * 5, out["refusals"]
    assert out["absent"] == ""
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
# 6-7. The extraction itself.
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


def test_the_design_tokens_and_the_shared_selectors_stayed() -> None:
    """The other half of the same sentence: the `--st-*` family IS openDox's."""
    css = STYLES.read_text(encoding="utf-8")
    for role in ("--st-captured", "--st-organized", "--st-proposed",
                 "--st-completion"):
        # four theme blocks declare each one: :root, the dark media query and
        # the two explicit data-theme choices (S7's own arrangement).
        assert len(re.findall(rf"^\s*{role}\s*:", css, re.M)) == 4, role
    declared = _selector_classes(css)
    for shared in ("swb-cbtn", "swb-cfield", "swb-clabel", "swb-cslot",
                   "disposebtn", "dispose-intile", "cbtn", "repobtn",
                   "docstatus", "reason-form", "rf-label", "repopick-msg",
                   "dc-h", "dc-line", "dc-note", "swb-draftchrome"):
        assert shared in declared, shared


def test_the_gate_exclusive_set_is_re_derived_where_the_modules_are_present() -> None:
    """Where an assembly has placed the six modules, the declared set above is
    CHECKED against them rather than trusted: every class in `GATE_EXCLUSIVE` is
    named by at least one of the six, and none is named by openDox's own
    bundle."""
    views = _assembled_views()
    if views is None:
        pytest.skip("no assembly has placed openXdox's six contributed modules "
                    "in this bundle (RULED Q5); the declared set is asserted "
                    "against `styles.css` alone")
    gate_text = "\n".join((views / name).read_text(encoding="utf-8")
                          for name in GATE_MODULES)
    own = [p for p in sorted(views.glob("*.js")) if p.name not in GATE_MODULES]
    own_text = "\n".join(p.read_text(encoding="utf-8") for p in own)
    own_text += (WEB / "app.js").read_text(encoding="utf-8")
    own_text += (WEB / "index.html").read_text(encoding="utf-8")
    for token in GATE_EXCLUSIVE:
        stem = token.rsplit("-", 1)[0] + "-"
        named = re.search(rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])",
                          gate_text) or re.search(re.escape(stem) + r'"', gate_text)
        assert named, f"{token} is named by none of the six contributed modules"
        assert not re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])", own_text), \
            f"{token} is named by openDox's own bundle and must not have left"


def test_no_contributed_sheet_declares_a_design_token() -> None:
    """A contributed sheet READS `var(--st-…)` and never WRITES one.

    RULED Q7 makes the `--st-*` family openDox's one stable styling surface; a
    contributed sheet that declared one would be a second authority for it, and
    `views/display.js`'s `applyTokens` is already the first.
    """
    views = WEB / "views"
    sheets = sorted(views.glob("*.css"))
    if not sheets:
        pytest.skip("no assembly has placed a contributed stylesheet in this "
                    "bundle (RULED Q5); openDox ships none of its own")
    for sheet in sheets:
        css = _blank_css_comments(sheet.read_text(encoding="utf-8"))
        written = re.findall(r"^\s*(--st-[A-Za-z0-9_-]+)\s*:", css, re.M)
        assert written == [], f"{sheet.name} declares {written}"
