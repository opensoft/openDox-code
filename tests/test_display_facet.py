"""THE DISPLAY FACET, BOTH HALVES, HELD TOGETHER.

`docs/front-end-package-boundary.md` § 3.4 slice S7 (opensoft/openDox-spec #8 ->
`7d12428c`; RULED with S1-S3 at opensoft/openxFactory#656 comment
`5642758731`) parameterizes the fourteen class-C files and the four declared
class-A tails from the registered domain's profile. `tests/test_web_boundary.py`
measures the BOUNDARY -- that no governance word survives as a literal -- and
would be just as green if every word had been DELETED. This file measures the
other half: that the words come from somewhere, that the somewhere is the ONE
registered profile, that a host which declares nothing gets openDox's own
neutral vocabulary and not openxFactory's, and that the two halves of the facet
-- `src/opendox/display_profile.py` and `src/opendox/web/views/display.js` --
say the same thing.

It stands on the same footing as its seven neighbours in `validate.yml`'s
narrowed list (`test_view_registry.py`, `test_split_route_tails.py`,
`test_gate_loop_contributed.py` and the rest): it imports `opendox`'s own
modules alone, reads bundle files as text, and drives the real
`views/display.js` under the `node` the runner already has (SKIPPED, never
failed, where node is absent). `--noconftest` safe and needs no consumer.

THE RULE IT GUARDS, in openXdox-spec `docs/domain-profile-design-note.md` § 6's
words: *"a profile whose organized status is spelled `triaged` must work with no
engine change, which a `profile.statuses['staged']` lookup would not deliver."*
And RULING C2's consequence, which § 4.3 point 5 states as the thing to protect
against: *"a fallback to TODAY'S WORDS is how the literals survive the refactor
invisibly."* A neutral install must look VISIBLY un-domained, never invisibly
re-domained -- which is what `test_a_student_install_renders_no_openxfactory_word`
below is for.

A CREATED FILE: no carve-manifest row (RULED OQ-C -- the manifest declares what
LEAVES openxFactory, never what a destination assembles).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from opendox import display_profile
from opendox.display_profile import (
    AREA_ROLES,
    ARTIFACT_ROLES,
    DISPLAY_KIND,
    DISPLAY_SCHEMA_VERSION,
    NEUTRAL_DISPLAY,
    PROFILE_FACET,
    SECTION_ORDER,
    SNAPSHOT_VALUES,
    STAGE_ROLES,
    STATUS_ROLES,
    TOKEN_ROLES,
    DisplayFacetError,
    display_manifest,
    host_display,
    normalize_display,
)

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "opendox" / "web"
DISPLAY_JS = WEB / "views" / "display.js"
APP_JS = WEB / "app.js"
NODE = shutil.which("node")

#: openxFactory's OWN vocabulary -- the words a neutral install must not show.
#: The eight controlled `Status:` words of `docs/document-lifecycle.md` plus the
#: stage nouns this tree's funnel, wheel and board used to spell. Identical to
#: `tests/test_web_boundary.py`'s watched set by construction: the two are the
#: same question asked at the two ends, and a word that left one list and not
#: the other would be a hole in whichever list forgot it.
OPENXFACTORY_WORDS = (
    "brainstorm", "staged", "draft", "ratified", "standard",
    "superseded", "retired", "record",
    "docs", "documents", "clusters", "cluster", "possibles", "possible",
    "proposals", "proposal", "realized", "changes", "active", "archived",
)


#: THE SCHEMA HALF of the payload, named here rather than swept. § 2.2 rule 3's
#: whole distinction: `fields` and `values` carry the snapshot's own field names
#: and closed enums, `stage_order` / `area_order` / `artifact_roles` /
#: `token_roles` / `sections` are ROLE tables and needles, and the rest is the
#: envelope. None of it is a word a human reads.
_SCHEMA_HALF = frozenset({
    "fields", "values", "stage_order", "area_order", "artifact_roles",
    "token_roles", "sections", "kind", "facet", "schema_version",
    "host_profile", "host_facet", "declared_tokens",
})


def _rendered_words(value) -> list[str]:
    """Every string VALUE in the payload, and no key.

    A KEY here is a role name, and THREE of the eight status roles -- `ratified`,
    `superseded`, `retired` -- are spelled identically to the openxFactory words
    they name the role OF. That is the lifecycle-state column's own coincidence
    (openXdox-spec `docs/domain-profile-design-note.md` § 6), stated in
    `views/display.js`'s own comment on `STATUS_ROLE`, and it is not something
    to respell: a role is a role because of where it SITS, not because of how it
    looks. Sweeping keys would make this test demand that openDox rename a
    neutral role to avoid resembling a domain's word, which is the tail wagging
    the dog.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [w for v in value.values() for w in _rendered_words(v)]
    if isinstance(value, list):
        return [w for v in value for w in _rendered_words(v)]
    return []


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _js_text() -> str:
    return DISPLAY_JS.read_text(encoding="utf-8")


def _js_array(name: str) -> list[str]:
    """A `export const NAME = [...]` string array, read out of the JS half."""
    text = _js_text()
    m = re.search(rf"export const {re.escape(name)} = \[(.*?)\];", text, re.S)
    assert m, f"views/display.js declares no array {name}"
    return re.findall(r'"([^"]*)"', m.group(1))


def _js_object(name: str) -> dict[str, str]:
    """A `export const NAME = {...}` flat string table, read out of the JS half.

    Deliberately TEXT, not an import: the Python side cannot import an ES
    module, and the point of this file is that the two halves are compared
    rather than one of them being assumed.
    """
    text = _js_text()
    m = re.search(rf"export const {re.escape(name)} = \{{(.*?)\n\}};", text, re.S)
    assert m, f"views/display.js declares no object {name}"
    body = m.group(1)
    out = {}
    for key, value in re.findall(r'(\w+):\s*"([^"]*)"', body):
        out[key] = value
    return out


def _run_node(source: str, tmp_path: Path) -> dict:
    """Run an ES-module harness against the REAL `views/display.js`."""
    script = tmp_path / "harness.mjs"
    script.write_text(source, encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _import_line(module: Path | str = DISPLAY_JS) -> str:
    return f"import * as D from {json.dumps(str(module))};"


# ---------------------------------------------------------------------------
# 1. THE TWO HALVES SAY THE SAME THING
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name, python_value",
    [("STAGE_ROLES", STAGE_ROLES), ("AREA_ROLES", AREA_ROLES),
     ("TOKEN_ROLES", TOKEN_ROLES), ("STATUS_ROLES", STATUS_ROLES),
     ("ARTIFACT_ROLES", ARTIFACT_ROLES)],
)
def test_every_role_table_is_declared_identically_on_both_sides(name, python_value):
    """A ROLE is a position, and the two halves must agree about which
    positions exist and IN WHAT ORDER -- `views/model.js` renders six columns
    left to right and `views/wheel-model.js` six reels in the same order, so
    the order is part of the declaration."""
    assert _js_array(name) == list(python_value), (
        f"{name} differs between src/opendox/display_profile.py and "
        f"src/opendox/web/views/display.js. The two halves of one facet must "
        f"declare the same roles in the same order, or a renderer invents an "
        f"axis the server never published.")


def test_the_neutral_vocabulary_is_byte_for_byte_the_same_on_both_sides():
    """openDox's own words are shipped TWICE -- once for the server's payload
    and once for the browser's pre-probe default -- and a difference between
    them is a page that changes wording the moment `/capabilities` answers."""
    text = _js_text()
    m = re.search(r"export const NEUTRAL_DISPLAY = \{(.*?)\n\};", text, re.S)
    assert m, "views/display.js declares no NEUTRAL_DISPLAY"
    js_words = set(re.findall(r'"([^"]*)"', m.group(1)))

    def _py_words(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for v in value.values():
                yield from _py_words(v)
        elif isinstance(value, list):
            for v in value:
                yield from _py_words(v)

    py_words = set(_py_words(NEUTRAL_DISPLAY))
    missing = sorted(py_words - js_words)
    assert not missing, (
        f"{missing} are in display_profile.NEUTRAL_DISPLAY and not in "
        f"views/display.js's. The browser renders its own copy until the probe "
        f"resolves, so a difference is a visible re-wording at first paint.")


def test_the_snapshot_enums_and_the_section_order_agree_on_both_sides():
    """§ 2.2 rule 3's schema half: values the renderer MATCHES, never renders.
    A drift here is a column that filters on a word the generator never wrote."""
    text = _js_text()
    m = re.search(r"export const SNAPSHOT_VALUES = \{(.*?)\n\};", text, re.S)
    assert m
    js_values = set(re.findall(r'"([^"]*)"', m.group(1)))
    for table in SNAPSHOT_VALUES.values():
        for word in table.values():
            assert word in js_values, (
                f"{word!r} is a snapshot enum value on the Python side and not "
                f"on the JavaScript one; the browser would match on a word the "
                f"generator never writes.")
    assert _js_array("SECTION_ORDER") == list(SECTION_ORDER)


def test_the_facet_name_kind_and_schema_version_agree_on_both_sides():
    text = _js_text()
    assert f'export const DISPLAY_KIND = "{DISPLAY_KIND}";' in text
    assert (f"export const DISPLAY_SCHEMA_VERSION = {DISPLAY_SCHEMA_VERSION};"
            in text)
    assert PROFILE_FACET == "DISPLAY"


# ---------------------------------------------------------------------------
# 2. THE FACET'S REFUSALS
# ---------------------------------------------------------------------------

def test_a_partial_declaration_is_legal_and_fills_from_the_neutral_words():
    """§ 4.3's own shape: a host declares the roles it has words for and
    openDox's own answer the rest. A facet that demanded all six stations
    would be a flag day for every profile in the estate."""
    payload = normalize_display({"stages": {"grouping": {"one": "cluster"}}})
    assert payload["stages"]["grouping"]["one"] == "cluster"
    assert (payload["stages"]["grouping"]["many"]
            == NEUTRAL_DISPLAY["stages"]["grouping"]["many"])
    assert (payload["stages"]["source"]["one"]
            == NEUTRAL_DISPLAY["stages"]["source"]["one"])


def test_an_unknown_role_is_refused_and_the_message_names_the_declared_set():
    """A role openDox has never heard of renders nowhere, so declaring one is a
    silent no-op -- and a silent no-op in a vocabulary is a blank label found
    by a human, once, much later."""
    with pytest.raises(DisplayFacetError) as excinfo:
        normalize_display({"stages": {"triage": {"one": "triaged item"}}})
    message = str(excinfo.value)
    assert "triage" in message
    assert "source" in message and "completion" in message


def test_a_blank_word_is_refused_rather_than_rendered_as_a_blank_surface():
    with pytest.raises(DisplayFacetError):
        normalize_display({"stages": {"source": {"one": "   "}}})


def test_a_corpus_prefix_without_a_separator_is_refused():
    """Copilot review. A prefix is matched with `startsWith` and composed into
    a path: `"ideation/staging"` would claim `ideation/stagingfoo/x.md` for the
    staging area AND compose `ideation/staging<id>` where a folder was meant.
    Refused at the declaration rather than normalised silently, because a
    profile that meant one of those two should say which."""
    with pytest.raises(DisplayFacetError, match="does not end in"):
        normalize_display({"areas": {"captured": {"prefix": "ideation/brainstorm"}}})
    with pytest.raises(DisplayFacetError, match="does not end in"):
        normalize_display({"artifacts": {"root": {"prefix": "openspec/changes"}}})
    # …and the well-formed one is taken whole
    ok = normalize_display({"areas": {"captured": {"prefix": "ideation/brainstorm/"}}})
    assert ok["areas"]["captured"]["prefix"] == "ideation/brainstorm/"


def test_two_roles_may_not_share_one_snapshot_enum_value():
    """Copilot round 4. The client reverse lookup (`registerRole(value)`)
    answers the FIRST role whose declared value matches, so a host mapping two
    roles to one value would have one role's cards silently rendered as the
    other's — the wrong word AND the wrong `cstate-<role>` hook, with nothing
    saying so. Refused after the MERGE, not on the declaration alone: the
    collision that matters is between a declared value and one openDox still
    ships for another role, which is exactly what a partial override causes."""
    # `display_manifest`, not `normalize_display`: the enum tables are the
    # SCHEMA half of the payload and are built by `_snapshot_values`, which is
    # the manifest's own step. That is also where the merge happens, and the
    # merge is what this check has to see.
    with pytest.raises(DisplayFacetError, match="BOTH"):
        display_manifest({"values": {"register_state": {
            "captured": "same", "proposed": "same"}}})
    # the partial-override case: one declared value colliding with a shipped one
    with pytest.raises(DisplayFacetError, match="BOTH"):
        display_manifest({"values": {"register_state": {"proposed": "latent"}}})
    # …and distinct values are taken whole
    ok = display_manifest({"values": {"register_state": {
        "captured": "new", "proposed": "chosen"}}})
    assert ok["values"]["register_state"]["captured"] == "new"
    assert ok["values"]["register_state"]["proposed"] == "chosen"


def test_a_role_table_that_is_not_a_mapping_is_refused():
    with pytest.raises(DisplayFacetError):
        normalize_display({"stages": ["source"]})


def test_host_display_answers_none_for_a_registered_profile_with_no_facet():
    """TWO ABSENCES, TWO ANSWERS. A host that registered and declares no
    vocabulary is `None` -- the NAMED absence -- not a refusal: every profile
    in the estate is in this state today, so refusing would be a flag day
    imposed by the seam that exists to avoid one."""
    class _Profile:
        ROUTE_EXTENSIONS = ()

    assert host_display(_Profile()) is None


def test_host_display_lets_a_missing_registration_refuse_untouched():
    """The other absence: no host at all. `domain_profile.current()` refuses,
    and this function does not turn that into a default."""
    class _Unregistered:
        def __getattr__(self, name):
            raise RuntimeError("no profile is registered: call register(...)")

    with pytest.raises(RuntimeError, match="no profile is registered"):
        host_display(_Unregistered())


# ---------------------------------------------------------------------------
# 3. THE STUDENT INSTALL -- the slice's own success test
# ---------------------------------------------------------------------------

def test_a_student_install_renders_no_openxfactory_word():
    """§ 4.3 point 5's failure mode, made into an assertion: *"a fallback to
    TODAY'S WORDS is how the literals survive the refactor invisibly."*

    A manifest built with NO declared facet is the whole surface a student
    install renders from, and no word of openxFactory's stage or status
    vocabulary may appear anywhere in it -- not in a label, not in a status
    word, not in a corpus prefix. The SCHEMA half is exempt by construction and
    named here: `fields`, `values` and `stage_order` carry the snapshot's own
    field names and closed enums, which are openDox's schema and the very thing
    § 2.2 rule 3 distinguishes from a domain's vocabulary.
    """
    payload = display_manifest(None, host_profile="opendox.neutral")
    assert payload["host_facet"] == "absent"
    assert payload["host_profile"] == "opendox.neutral"
    rendered = {k: v for k, v in payload.items()
                if k not in _SCHEMA_HALF}
    blob = " | ".join(_rendered_words(rendered))
    offenders = sorted({w for w in OPENXFACTORY_WORDS
                        if re.search(rf"\b{re.escape(w)}\b", blob)})
    assert not offenders, (
        f"the neutral payload a student install renders from carries "
        f"{offenders} -- openxFactory's own words, shipped to an install that "
        f"never declared them. A funnel labelled `sources -> groups -> "
        f"candidates` is visibly un-domained; one labelled `docs -> clusters "
        f"-> possibles` is invisibly RE-domained, which is worse.")


def test_a_student_install_declares_no_corpus_prefix():
    """A product told no corpus layout has none. Every area falls in the
    terminal `reference` bucket, and the create dialog defaults to the
    repository root rather than inventing `ideation/brainstorm/`."""
    payload = display_manifest(None)
    for role, area in payload["areas"].items():
        assert area["prefix"] is None, (
            f"the neutral vocabulary declares a corpus prefix for {role!r}: "
            f"{area['prefix']!r}. A prefix is one domain's folder layout.")


def test_a_declared_facet_reaches_the_payload_whole():
    declared = {
        "stages": {"grouping": {"one": "cluster", "many": "clusters",
                                "short": "clusters", "label": "clusters"}},
        "areas": {"captured": {"prefix": "ideation/brainstorm/",
                               "label": "brainstorm"}},
        "tokens": {"organized": "#0D9488"},
    }
    payload = display_manifest(declared, host_profile="openxfactory.engineering")
    assert payload["host_facet"] == "declared"
    assert payload["stages"]["grouping"]["short"] == "clusters"
    assert payload["areas"]["captured"]["prefix"] == "ideation/brainstorm/"
    assert payload["tokens"]["organized"] == "#0D9488"
    # and the roles it did NOT declare keep openDox's own words
    assert (payload["stages"]["source"]["one"]
            == NEUTRAL_DISPLAY["stages"]["source"]["one"])


def test_serve_projects_the_facet_beside_the_view_registry():
    """The ONE crossing of the boundary, on the payload the shell already
    fetches -- no new route and no second fetch (§ 4.3 step 1)."""
    source = (ROOT / "src" / "opendox" / "serve.py").read_text(encoding="utf-8")
    assert 'capabilities["display"] = display_profile.display_manifest(' in source
    assert "host_display(" in source


# ---------------------------------------------------------------------------
# 4. THE CONTEXT HOP
# ---------------------------------------------------------------------------

def test_the_shell_reads_the_facet_once_and_hands_it_down_through_ctx():
    """§ 4.3 steps 2-3: ONE read, at boot, then `ctx.display` to every view.
    A second `readDisplay` anywhere in the shell would be a second vocabulary
    that could disagree with the first."""
    app = APP_JS.read_text(encoding="utf-8")
    assert 'import { readDisplay, STAGE_ROLES } from "./views/display.js";' in app
    assert app.count("readDisplay(") == 1, (
        "app.js reads the facet at exactly ONE call site; a second read would "
        "be a second vocabulary that could disagree with the first.")
    assert "const display = readDisplay(probedCaps);" in app, (
        "the facet rides on the payload `probeCapabilities()` already fetched "
        "-- no new route and no second fetch (§ 4.3 step 1).")
    assert "display.applyTokens(document.documentElement);" in app
    assert "applyShellVocabulary(display);" in app
    assert "display: ctx.display" in app


def test_the_view_contract_declares_the_context_key():
    """The shell and the contributed column must agree on what `ctx` carries;
    `CTX_KEYS` is where that is declared, on both sides."""
    py = (ROOT / "src" / "opendox" / "view_extension.py").read_text(encoding="utf-8")
    js = (WEB / "views" / "view_extension.js").read_text(encoding="utf-8")
    py_keys = set(re.findall(r'^\s*"(\w+)":', re.search(
        r"CTX_KEYS[^=]*=\s*\{(.*?)\n\}", py, re.S).group(1), re.M))
    js_keys = set(re.findall(r'^\s*(\w+):', re.search(
        r"CTX_KEYS\s*=\s*\{(.*?)\n\}", js, re.S).group(1), re.M))
    assert "display" in py_keys, (
        "the Python half of the view contract does not declare `ctx.display`")
    assert py_keys == js_keys, (
        f"the two CTX_KEYS tables disagree: {sorted(py_keys ^ js_keys)}")


# ---------------------------------------------------------------------------
# 5. NODE PROBES -- the real module, and two real views
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_client_half_resolves_by_role_and_refuses_an_unknown_one(tmp_path):
    out = _run_node(
        _import_line() + """
const neutral = D.neutralDisplay();
let refused = null;
try { neutral.one("triage"); } catch (e) { refused = e.name + ": " + e.message; }
const declared = D.readDisplay({ display: {
  schema_version: 1, kind: "opendox.display-facet", host_facet: "declared",
  stages: { grouping: { one: "cluster", many: "clusters", short: "clusters",
                        label: "clusters" } },
  statuses: { document: { captured: "brainstorm" } },
  areas: { captured: { prefix: "ideation/brainstorm/", label: "brainstorm" } },
  tokens: { organized: "#123456" },
} });
console.log(JSON.stringify({
  neutralOne: neutral.one("grouping"),
  neutralStatus: neutral.status("document", "captured"),
  neutralArea: neutral.areaOf("ideation/brainstorm/a.md").role,
  refused,
  declaredOne: declared.one("grouping"),
  declaredStatus: declared.status("document", "captured"),
  declaredArea: declared.areaOf("ideation/brainstorm/a.md").role,
  declaredSourceOne: declared.one("source"),
  tokenVar: declared.tokenVar("organized"),
}));
""", tmp_path)
    assert out["neutralOne"] == NEUTRAL_DISPLAY["stages"]["grouping"]["one"]
    assert out["neutralStatus"] == "captured"
    # no prefix declared -> the terminal bucket, which is the honest answer
    assert out["neutralArea"] == "reference"
    assert out["refused"].startswith("DisplayRoleError")
    assert "triage" in out["refused"]
    assert out["declaredOne"] == "cluster"
    assert out["declaredStatus"] == "brainstorm"
    assert out["declaredArea"] == "captured"
    # the roles the host did not declare keep openDox's own words
    assert out["declaredSourceOne"] == NEUTRAL_DISPLAY["stages"]["source"]["one"]
    assert out["tokenVar"] == "var(--st-organized)"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_shell_refuses_a_display_payload_it_cannot_describe(tmp_path):
    out = _run_node(
        _import_line() + """
function refusal(payload) {
  try { D.readDisplay(payload); return null; }
  catch (e) { return e.name + ": " + e.message; }
}
console.log(JSON.stringify({
  absent: D.readDisplay(null).hostFacet,
  wrongKind: refusal({ display: { kind: "something.else", schema_version: 1 } }),
  wrongVersion: refusal({ display: { kind: "opendox.display-facet",
                                     schema_version: 99 } }),
  notAnObject: refusal({ display: ["stages"] }),
}));
""", tmp_path)
    assert out["absent"] == "absent"
    assert "DisplayRoleError" in out["wrongKind"]
    assert "DisplayRoleError" in out["wrongVersion"]
    assert "DisplayRoleError" in out["notAnObject"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_only_the_tokens_a_host_declared_are_written_onto_root(tmp_path):
    """`styles.css` restates all four tokens PER THEME and an inline custom
    property on `:root` outranks every one of those rules, so writing the
    neutral values unconditionally would pin one theme's palette onto every
    install that declares none -- which is every install in the estate today."""
    out = _run_node(
        _import_line() + """
function apply(payload) {
  const written = {};
  const el = { style: { setProperty: (k, v) => { written[k] = v; } } };
  D.readDisplay(payload).applyTokens(el);
  return written;
}
console.log(JSON.stringify({
  neutral: apply(null),
  declared: apply({ display: { kind: "opendox.display-facet", schema_version: 1,
                               tokens: { organized: "#123456" } } }),
}));
""", tmp_path)
    assert out["neutral"] == {}, (
        "a neutral install had its `:root` written, which shadows every dark "
        "and explicit-theme rule in styles.css")
    assert out["declared"] == {"--st-organized": "#123456"}


def test_the_payload_names_which_tokens_the_host_declared():
    """`tokens` cannot answer this and never could: `normalize_display` merges
    the host's over openDox's, so the served table carries all four keys
    whether the host declared four, one or none. The provenance is therefore
    published beside the words (Copilot round 6)."""
    assert display_manifest(None)["declared_tokens"] == []
    assert display_manifest({})["declared_tokens"] == []
    partial = display_manifest({"tokens": {"organized": "#123456"}})
    assert partial["declared_tokens"] == ["organized"]
    # …while the table itself still carries all four, because the SHELL needs
    # a value for every role it may be asked for.
    assert sorted(partial["tokens"]) == sorted(TOKEN_ROLES)
    whole = display_manifest({"tokens": {role: "#123456" for role in TOKEN_ROLES}})
    assert whole["declared_tokens"] == list(TOKEN_ROLES)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_served_payload_writes_only_the_host_declared_tokens(tmp_path):
    """THE REGRESSION THE PREVIOUS TEST COULD NOT SEE (Copilot round 6).

    `test_only_the_tokens_a_host_declared_are_written_onto_root` hands `Display`
    a hand-built facet, where a token key IS a host declaration. The payload the
    server actually serves is not that shape: `display_manifest` has already
    merged openDox's own tokens in, so every install — including every one in
    the estate today, none of which declares a DISPLAY facet — would have had
    all four properties written inline on `:root`, outranking `styles.css`'s
    per-theme rules and ending dark mode there.

    So this drives the same code path with the REAL payload, built here by the
    real `display_manifest`, and nothing in between.
    """
    payloads = {
        "absent": {"display": display_manifest(None,
                                               host_profile="opendox.neutral")},
        "declared_none": {"display": display_manifest(
            {"stages": {"grouping": {"one": "cluster", "many": "clusters",
                                     "short": "clusters", "label": "clusters"}}},
            host_profile="openxfactory.engineering")},
        "declared_one": {"display": display_manifest(
            {"tokens": {"organized": "#123456"}},
            host_profile="openxfactory.engineering")},
    }
    out = _run_node(
        _import_line() + f"""
const payloads = {json.dumps(payloads)};
function apply(payload) {{
  const written = {{}};
  const el = {{ style: {{ setProperty: (k, v) => {{ written[k] = v; }} }} }};
  D.readDisplay(payload).applyTokens(el);
  return written;
}}
const out = {{}};
for (const [name, payload] of Object.entries(payloads)) out[name] = apply(payload);
console.log(JSON.stringify(out));
""", tmp_path)
    assert out["absent"] == {}, (
        "the payload a host-less install is served wrote `:root` — every "
        "install in the estate loses dark mode the moment this lands")
    assert out["declared_none"] == {}, (
        "a host that declares a vocabulary but no palette had openDox's own "
        "four colours pinned inline over its themes")
    assert out["declared_one"] == {"--st-organized": "#123456"}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_two_real_views_render_the_declared_words(tmp_path):
    """The two pure models the whole bundle's vocabulary flows through: the
    funnel's column model (`views/model.js`) and the wheel deck's
    (`views/wheel-model.js`). Both are driven here with a DECLARED facet and
    with none, and the two runs must differ in exactly the words."""
    views = json.dumps(str(WEB / "views"))
    out = _run_node(f"""
const base = {views} + "/";
const D = await import(base + "display.js");
const {{ buildFunnelModel }} = await import(base + "model.js");
const {{ buildWheelModel }} = await import(base + "wheel-model.js");
const snap = {{
  documents: [{{ id: "a.md", stage: "brainstorm" }}],
  clusters: [{{ id: "c1", name: "C", document_edges: [{{ document: "a.md" }}],
              tallies: {{ document_links: 1 }} }}],
  possibles: [], staged_topics: [], changes: [],
}};
const declared = D.readDisplay({{ display: {{
  schema_version: 1, kind: "opendox.display-facet", host_facet: "declared",
  stages: {{ source: {{ one: "doc", many: "docs", short: "docs", label: "docs" }},
           grouping: {{ one: "cluster", many: "clusters", short: "clusters",
                      label: "clusters" }} }},
}} }});
const neutral = D.neutralDisplay();
const labels = (d) => buildFunnelModel(snap, d).columns.map((c) => c.label);
const reels = (d) => buildWheelModel(snap, d).wheels.map((w) => w.label);
console.log(JSON.stringify({{
  neutralColumns: labels(neutral), declaredColumns: labels(declared),
  neutralReels: reels(neutral), declaredReels: reels(declared),
}}));
""", tmp_path)
    assert out["declaredColumns"][:2] == ["docs", "clusters"]
    assert out["neutralColumns"][:2] != out["declaredColumns"][:2]
    assert out["declaredReels"][:2] == ["docs", "clusters"]
    assert out["neutralReels"][:2] != out["declaredReels"][:2]
    for word in ("docs", "clusters"):
        assert word not in out["neutralColumns"], (
            "the neutral run rendered an openxFactory word")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_workbench_model_takes_the_vocabulary_at_the_mount(tmp_path):
    """`views/staging-workbench-model.js` is the one in-scope module that takes
    the facet in MODULE SCOPE rather than on every signature -- it is derived
    through from five call sites in the overlay and from the node parity
    harness, and a fourth positional argument there is a worse seam than one
    assignment at the mount. `setDisplay` is that assignment, and this is the
    probe that it actually moves the words."""
    model = json.dumps(str(WEB / "views" / "staging-workbench-model.js"))
    display = json.dumps(str(DISPLAY_JS))
    out = _run_node(f"""
const M = await import({model});
const D = await import({display});
const snap = {{ clusters: [{{ id: "c1", name: "C",
                            document_edges: [{{ document: "a.md" }}] }}],
              documents: [{{ id: "a.md", path: "a.md" }}] }};
const neutralLabel = M.workbenchScope(snap, D.SCOPE_KINDS.grouping, "c1")
  .sections[0].label;
M.setDisplay(D.readDisplay({{ display: {{
  schema_version: 1, kind: "opendox.display-facet", host_facet: "declared",
  stages: {{ source: {{ one: "doc", many: "docs", short: "docs", label: "docs" }},
           grouping: {{ one: "cluster", many: "clusters", short: "clusters",
                      label: "clusters" }} }},
  areas: {{ captured: {{ prefix: "ideation/brainstorm/", label: "brainstorm" }},
          organized: {{ prefix: "ideation/staging/", label: "staged" }} }},
}} }}));
console.log(JSON.stringify({{
  neutralLabel,
  declaredLabel: M.workbenchScope(snap, D.SCOPE_KINDS.grouping, "c1")
    .sections[0].label,
  neutralAreaAfterReset: (M.setDisplay(null), M.createArea(null)),
  declaredArea: (M.setDisplay(D.readDisplay({{ display: {{
      schema_version: 1, kind: "opendox.display-facet",
      areas: {{ captured: {{ prefix: "ideation/brainstorm/", label: "b" }} }} }} }})),
    M.createArea(null)),
}}));
""", tmp_path)
    assert out["neutralLabel"] == "group source items"
    assert out["declaredLabel"] == "cluster docs"
    # a product told no corpus layout defaults to the repository root
    assert out["neutralAreaAfterReset"] == ""
    assert out["declaredArea"] == "ideation/brainstorm/"
