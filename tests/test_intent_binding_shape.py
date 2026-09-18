"""SHAPE assertions for the intent-feed optional binding (RULED Q5,
`docs/front-end-package-boundary.md` § 6 Q5 / § 4.2, opensoft/openxFactory#656
comment 5642758731; split-opendox-two-layer-product § 3.4, slice S2).

Parses the tree and imports nothing — the same idiom `test_leg_shape.py`,
`test_consumer_reach.py` and `test_profile_registration.py` already use, and
for the same reason: this suite runs `--noconftest` (`.github/workflows/
validate.yml`), so a test that needed a fixture or a package import here
would need the conftest chain this invocation deliberately does not load.

WHAT THIS PROVES, IN THE ABSENCE OF A JS TEST RUNNER. `views/intent-feed.js`
is RULED `not_moved` (`docs/opendox-carve-manifest.yaml`:1807-1810) and is
therefore never present in this leg's own tree — so the one thing a shape
test CAN prove here is the STATIC shape of the seam: neither `dispose.js` nor
`wheel.js` names the absent module in a static `import … from` clause any
more (the defect the note's § 1.2(b) measured — a dangling import that fails
the whole module graph, not merely a missing render), both name the new
`intent-binding.js` instead with the same imported symbols, and that module's
only reference to `./intent-feed.js` is inside a dynamic `import(` call,
which is what makes the reference OPTIONAL rather than dangling.

It deliberately does NOT prove the seam RENDERS correctly with and without
the contribution — that needs a real ECMAScript module loader, which is
`tests/test_intent_binding_dom.py`'s job (Node, and a RUNTIME `pytest.skip`
inside its `_run` helper when node is absent rather than a
`pytest.mark.skipif` — the same mechanism the precedent
`tests/test_intent_tray_dom.py` used, measured at `8efb3cf5`; a marker would
have to answer at COLLECTION time, and what the probe actually needs to know
is whether the interpreter it is about to invoke exists. That file was
RETIRED at this leg on 2026-09-13, RULED `openxFactory#656` comment
5656343213, so the precedent survives in the harness and not in a file you can
open here).

WHY THAT FILE IS NOT ON THE `--noconftest` LIST AND THIS ONE IS. Stated
narrowly, because the wide version of the sentence — that no DOM probe of a
`web/` view is on the list — was false (opensoft/openDox-code#24, Copilot):
`tests/test_view_registry.py`, `tests/test_split_route_tails.py` and
`tests/test_gate_loop_contributed.py` are all on it and all drive real `web/`
modules under node behind a DOM stand-in of their own. The list is an
allow-list, admitted file by file, and `.github/workflows/validate.yml` records
the same reason for every entry: the file is the SHAPE assertion RULED Q-L5
(b′) leaves running while the carved suite waits on the BUILD arc, or without
it the slice's ruled contract would be only DESCRIBED (S3's "the only place
slice S3's ruled contract is executed rather than described"; S4's and S5's
"measures the other half"; S6's "the slice's only running proof"). THIS file is
the first kind. S2's contract is not left undescribed without the second one:
delete the intent reach instead of routing it through the binding and
`test_wheel_imports_the_intent_names_from_the_binding` below goes red. It is
that test ALONE, and the header used to claim both (Copilot review of
openDox-code#24): `test_intent_binding_exports_every_name_the_views_need` reads
`intent-binding.js` against a FIXED `REQUIRED_BINDING_EXPORTS` tuple, so it is
blind to what the CONSUMERS do — measured by deleting wheel.js's static import
of the binding, which leaves it green and reds only the consumer test. One
running proof of S2's contract, not two, which is exactly enough and is what
the paragraph above claims. What
the DOM probe adds is the seam's FORWARDING, and three of its six cases have to
write a stand-in for the never-carried `views/intent-feed.js` to measure it.
Admitting behavioural probes as a CLASS is BUILD-arc work (S8), not this
slice's.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "src" / "opendox" / "web" / "views"

DISPOSE = VIEWS / "dispose.js"
WHEEL = VIEWS / "wheel.js"
BINDING = VIEWS / "intent-binding.js"

# One static-import clause: `import { a, b } from "./x.js";`, possibly
# wrapped across two lines the way `wheel.js`'s own import already is. A
# regex and not `ast` — there is no JS parser in this leg's dependency set
# (`pyproject.toml` declares exactly PyYAML and pytest), and the front-end
# package boundary note's own § 4.5 test is written to the same constraint.
_STATIC_IMPORT_RE = re.compile(
    r'import\s*\{([^}]*)\}\s*from\s*"(\./[^"]+)"\s*;', re.MULTILINE)

# The dynamic form: `import("./x.js")` — a call, never a `from` clause, so
# this pattern cannot collide with `_STATIC_IMPORT_RE` above.
_DYNAMIC_IMPORT_RE = re.compile(r'import\(\s*"(\./[^"]+)"\s*\)')

REQUIRED_BINDING_EXPORTS = (
    "emitIntent",
    "renderIntentChips",
    "feedActor",
    "intentCapable",
    "refusalLine",
    "startIntentFeed",
    "statesByTarget",
)


def _static_imports(text: str) -> list[tuple[list[str], str]]:
    """`[(imported names, relative specifier), …]` for every static
    `import { … } from "./…"` clause in `text`."""
    out = []
    for names_blob, specifier in _STATIC_IMPORT_RE.findall(text):
        names = [n.strip() for n in names_blob.split(",") if n.strip()]
        out.append((names, specifier))
    return out


def test_the_absent_module_is_still_absent_from_disk_as_a_check() -> None:
    # Sanity: if this ever stops being true the whole premise of this file —
    # and of RULING OQ-F — needs re-reading, not a silently-skipped suite.
    assert not (VIEWS / "intent-feed.js").exists(), (
        "views/intent-feed.js exists at this leg; RULING OQ-F "
        "(`not_moved / stays_openxfactory_adapter`) says it should not. If "
        "the ruling changed, this whole optional-binding seam (and this "
        "test) is answering a question that no longer applies"
    )


def test_intent_binding_module_exists() -> None:
    assert BINDING.is_file(), (
        f"{BINDING} is missing: dispose.js and wheel.js import the "
        "intent-feed names through it (RULED Q5, split-opendox § 3.4 S2)"
    )


def test_intent_binding_exports_every_name_the_views_need() -> None:
    text = BINDING.read_text(encoding="utf-8")
    for name in REQUIRED_BINDING_EXPORTS:
        pattern = re.compile(
            r'export\s+(?:async\s+function|function|const)\s+' + re.escape(name)
            + r'\b')
        assert pattern.search(text), (
            f"intent-binding.js does not export `{name}`, which dispose.js "
            "or wheel.js imports from it"
        )


def test_intent_binding_reaches_intent_feed_only_dynamically() -> None:
    text = BINDING.read_text(encoding="utf-8")
    assert not _static_imports(text), (
        "intent-binding.js carries a static `import { … } from \"./…\"` "
        "clause; the whole point of this file is that its ONE reference to "
        "the possibly-absent module is a dynamic import() a missing file "
        "cannot make fail to resolve"
    )
    dynamic = _DYNAMIC_IMPORT_RE.findall(text)
    assert dynamic == ["./intent-feed.js"], (
        f"expected intent-binding.js's one dynamic import() to name "
        f"./intent-feed.js; found {dynamic!r}"
    )


def test_dispose_and_wheel_no_longer_name_intent_feed_directly() -> None:
    """AMENDED BY SLICE S5: `views/dispose.js` left this bundle.

    S2's fix stands and travelled with the module. `dispose.js` is openXdox-code's
    package data now (RULED Q5, openxFactory#656 comment `5648044785`), and the
    property this test asserts of it is asserted THERE, at
    `tests/test_gate_loop_views.py::test_the_bundle_reach_is_exactly_declared`,
    which holds that module's relative imports to an EXACT declared set —
    `./helpers.js` and `./intent-binding.js` — so `intent-feed.js` reappearing
    in it fails as an undeclared reach rather than as a missing string. What
    stays measurable here is `views/wheel.js`, which stayed.
    """
    for path in (WHEEL,):
        text = path.read_text(encoding="utf-8")
        assert "intent-feed.js" not in text, (
            f"{path} still names intent-feed.js directly; the note's "
            "§ 1.2(b) defect (a dangling static import failing the whole "
            "module graph the moment this leg carries no such file) is "
            "exactly what routing the reference through intent-binding.js "
            "removes — RULED Q5 requires dispose.js and wheel.js to reach "
            "the chips ONLY through the optional binding"
        )


def test_dispose_left_the_bundle_with_its_intent_reach_intact() -> None:
    """AMENDED BY SLICE S5. This asserted that `views/dispose.js` imported
    `emitIntent` and `renderIntentChips` from `./intent-binding.js`; the module
    moved to openXdox-code and the assertion moved with it
    (`tests/test_gate_loop_views.py`'s `BUNDLE_REACH` table names
    `./intent-binding.js` for `dispose.js` exactly).

    What this leg can still say — and it is the half that matters here — is that
    the module is GONE and that `views/intent-binding.js`, which S2 created and
    S5 does not move, is still here for the contributed module to reach once the
    assembly places it beside this bundle."""
    assert not DISPOSE.exists(), (
        "views/dispose.js is still in this bundle; slice S5 moves the gate "
        "loop's six class-B modules to openXdox-code's package data")
    assert BINDING.is_file(), (
        "views/intent-binding.js is gone: it is class A, it stays, and the "
        "contributed dispose module imports it by a bundle-relative specifier "
        "that the composed assembly resolves in place")


def test_wheel_imports_the_intent_names_from_the_binding() -> None:
    text = WHEEL.read_text(encoding="utf-8")
    imports = {specifier: names for names, specifier in _static_imports(text)}
    assert "./intent-binding.js" in imports, (
        "wheel.js does not statically import from ./intent-binding.js"
    )
    names = set(imports["./intent-binding.js"])
    expected = {"feedActor", "intentCapable", "refusalLine",
                "startIntentFeed", "statesByTarget"}
    assert expected <= names, (
        f"wheel.js imports {sorted(names)} from intent-binding.js; expected "
        f"at least {sorted(expected)} (unchanged from its former import of "
        "intent-feed.js)"
    )


def test_every_static_relative_import_in_the_touched_files_resolves() -> None:
    # A narrow, three-file rehearsal of the note's § 4.5 assertion 3 ("every
    # relative import resolves"), proving THIS slice's own fix rather than
    # standing in for slice S1's full-tree census test. `intent-binding.js`'s
    # own reference to intent-feed.js is DYNAMIC and is deliberately not
    # required to resolve — that is the seam, not a gap in it.
    # SLICE S5: `dispose.js` is no longer one of the files this leg ships, so
    # the rehearsal is over the two that stayed. Its own imports are held to an
    # exact declared set at openXdox-code, which is a stronger check than
    # "resolves" and is made where the file is.
    for path in (WHEEL, BINDING):
        text = path.read_text(encoding="utf-8")
        for _names, specifier in _static_imports(text):
            target = (path.parent / specifier).resolve()
            assert target.is_file(), (
                f"{path} statically imports {specifier!r}, which resolves "
                f"to {target}, and no such file exists"
            )
