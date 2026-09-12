"""THE DISPLAY FACET: the host's rendered vocabulary, resolved by ROLE.

WHY THIS FILE EXISTS. `docs/front-end-package-boundary.md` § 2.1 puts fourteen
files of `src/opendox/web/` in **class C** — *"the file's STRUCTURE is neutral —
a wheel, a funnel, a bullseye, a column strip, a sectioned outline — and its
NAMES are one domain's mapping … A class-C file stays in `openDox-code` and is
PARAMETERIZED: its vocabulary comes from the registered domain profile, never
from a literal."* That is RULING C2 applied one tier out — *"a clinician using
`MedxDox` never sees the word 'requirement'"* — and § 4.3 names the mechanism in
five steps:

    1. The host registers its profile at process start, unchanged.
    2. `serve.py` exposes the profile's DISPLAY FACET — the stage keys with
       their labels, the status vocabulary, the artifact-folder words — on the
       existing `/capabilities` payload … so no new route and no second fetch.
    3. `app.js` puts that facet in the context object every binding already
       receives.
    4. A class-C module resolves BY ROLE, NOT BY STRING.
    5. Refusal, not a default.

This module is step 2's server half; `views/display.js` is its client half. Both
carry `STAGE_FIELDS` / `SNAPSHOT_FIELDS`, which is § 2.2 rule 3's OTHER half —
the snapshot's own field names, openDox's schema and not a domain's vocabulary,
declared once so that no class-C file has to spell one.

RESOLVE BY ROLE, NOT BY STRING — the rule this module exists to make possible.
openXdox-spec `docs/domain-profile-design-note.md` § 6 states it for the Python
engine and it is unchanged here: *"`STAGED_STATUS` is not 'the string `staged`';
it is 'the status this domain's documents carry while ORGANIZED'. A profile
whose organized status is spelled `triaged` must work with no engine change,
which a `profile.statuses["staged"]` lookup would not deliver."* Every key in
the payload below is therefore a ROLE — a neutral word naming a POSITION in the
pipeline — and every VALUE is the registered domain's own spelling of it.

WHAT A ROLE IS HERE. Two families, and they are not the same question:

* `STAGE_ROLES` — the six stations of the realization funnel the shell renders
  (`views/model.js`'s columns, `views/wheel-model.js`'s reels,
  `views/repo-selector-model.js`'s stations). A stage is a POSITION in a
  pipeline: raw material, grouped material, a candidate, a selection, a
  submission, a completion. openxFactory spells those `docs`, `clusters`,
  `possibles`, `staged`, `proposals`, `realized`; a clinical descendant would
  spell them something else and the geometry would not move.
* `STATUS_ROLES` — the lifecycle-state column of the registered profile's own
  vocabulary, verbatim from openXdox-spec's design note § 6: *"the
  lifecycle-state column of `document-lifecycle.md`'s own table (`captured |
  organized | proposed | ratified | promoted | superseded | retired | out of
  band`) is the neutral role vocabulary that makes this possible, and it is why
  the schema carries a `role:` per status."* openxFactory's real profile
  (`contracts/domain-profiles/openxfactory-engineering.yaml`:151-159) declares
  exactly those roles against exactly those words, so a host that already has a
  profile has already answered this question and the facet is a projection of an
  answer rather than a second declaration.

  A status vocabulary is per ARTIFACT KIND in the profile (a governance
  document, an OpenSpec change and a register possible each carry their own
  closed word list), so the facet keeps that shape: `statuses[<kind role>][<status
  role>]`. Collapsing them would make `proposed` mean `draft` and `picked` at
  once, which is exactly the collision the per-kind vocabulary exists to avoid.

ABSENT IS NEUTRAL, NOT OPENXFACTORY'S WORDS — and this is the one place this
module departs from § 4.3's point 5 ("refusal, not a default"), deliberately and
with the reason stated, because the note's own argument for that point is
narrower than its wording:

    A fallback to TODAY'S WORDS is how the literals survive the refactor
    invisibly.  (§ 4.3 point 5)

The defect the point guards against is a fallback to `docs` / `clusters` /
`possibles` / `staged` / `proposals` / `realized` — openxFactory's spelling,
reappearing when no profile answers, so that nobody ever notices the
parameterization did not happen. `NEUTRAL_DISPLAY` below is the opposite of
that: it is openDox's OWN vocabulary, the neutral product's plain words for
the neutral product's own shape, and a shell that renders it is VISIBLY not
rendering a domain's. A student who installs openDox alone gets a working
funnel that says `sources → groups → candidates → selections → submissions →
completions`, which is RULING OQ-2's student install and § 2.1's own test for
class C — *"replace every governance word in it with a placeholder and the file
still renders correctly"* — performed by the product rather than asserted about
it.

The asymmetry with `ROUTE_EXTENSIONS` is `view_extension.host_view_extensions`'
own and is argued there at length: a server missing its contributed ROUTES looks
exactly like a working one until a path 404s, whereas a shell rendering neutral
words is self-evidently rendering neutral words. **AND THE ABSENCE IS NAMED,
NEVER SILENT** — `display_manifest` carries `host_facet` = `"declared"` or
`"absent"` with the facet name and the registered profile's name, so a host
debugging a funnel that says `groups` reads the reason out of the payload the
page already fetches instead of inferring it.

MALFORMED FAILS CLOSED. An absent facet is neutral; a facet that IS declared and
does not conform is a `DisplayFacetError` at `build_server()` time, naming the
role, the field and the value. That is `collect_view_bindings`' stance for the
same reason: a contributed declaration checked where the server is built cannot
become a browser-side mystery, and "the host meant well" is not a vocabulary.

A CREATED FILE: no row in openxFactory's `docs/opendox-carve-manifest.yaml`,
because the manifest declares what LEAVES openxFactory and never what a
destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

__all__ = [
    "AREA_ROLES",
    "ARTIFACT_ROLES",
    "DISPLAY_KIND",
    "DISPLAY_SCHEMA_VERSION",
    "NEUTRAL_DISPLAY",
    "PROFILE_FACET",
    "SECTION_ORDER",
    "SNAPSHOT_VALUES",
    "STAGE_FIELDS",
    "STAGE_ROLES",
    "STATUS_ROLES",
    "TOKEN_ROLES",
    "DisplayFacetError",
    "display_manifest",
    "host_display",
    "normalize_display",
]


#: The facet name a host's profile carries, beside `ROUTE_EXTENSIONS`,
#: `SUBCOMMAND_EXTENSIONS` and `VIEW_EXTENSIONS` — ONE composite profile, one
#: registration, four facets, all resolved through the SAME lazy proxy (RULED
#: ASK-2 option (2), openxFactory#656 comment `5628886636`).
PROFILE_FACET = "DISPLAY"

DISPLAY_KIND = "opendox.display-facet"
DISPLAY_SCHEMA_VERSION = 1

#: THE SIX STAGE ROLES, in spine order. A ROLE, never a word: `source` is "the
#: raw material this domain works from", not "the string `docs`". The order is
#: part of the declaration — `views/model.js` renders six columns left to right
#: and `views/wheel-model.js` six reels in the same order, so a renderer that
#: had to invent the axis would be inventing domain knowledge.
STAGE_ROLES: tuple[str, ...] = (
    "source",
    "grouping",
    "candidate",
    "selection",
    "submission",
    "completion",
)

#: THE NEUTRAL ROLE VOCABULARY FOR A STATUS, verbatim from the lifecycle-state
#: column openXdox-spec's design note § 6 names (`captured | organized |
#: proposed | ratified | promoted | superseded | retired | out of band`), with
#: the out-of-band pair spelled as one hyphenated role because that is how
#: openxFactory's own profile spells it
#: (`contracts/domain-profiles/openxfactory-engineering.yaml`:158-159).
STATUS_ROLES: tuple[str, ...] = (
    "captured",
    "organized",
    "proposed",
    "ratified",
    "promoted",
    "superseded",
    "retired",
    "out-of-band",
)

#: THE CORPUS AREAS a document may live in, by role. `views/docs.js`:18's
#: `AREA_ORDER` hardcodes `ideation/brainstorm` and `ideation/staging` — which
#: is openxFactory's own corpus layout, and RULED Q1 (openxFactory#656 comment
#: `5642758731`) is *"openDox, class A, with the area map parameterized"*. The
#: roles are the pipeline positions the folders hold, not the folders.
#:
#: `reference` is the terminal bucket — everything the declared areas do not
#: claim — and it is openDox's own, so it carries a label and never a prefix.
AREA_ROLES: tuple[str, ...] = ("captured", "organized", "proposed", "reference")

#: THE FOUR DESIGN TOKENS, by role. `styles.css` used to define
#: `--st-brainstorm` / `--st-staged` / `--st-proposal` / `--st-realized` — four
#: names that spelled one domain's stages into the ONE styling surface RULED Q7
#: (openxFactory#656 comment `5648049748`) calls stable: *"openDox's declared
#: design tokens (the `--st-*` family, S7) are the one stable styling surface;
#: nothing else in `styles.css` is."* Slice S7 renamed them `--st-<role>` for
#: each of the four below. The names become roles; the VALUES stay
#: openDox's, because a colour is not a domain's word — a host may override
#: them and none has to.
TOKEN_ROLES: tuple[str, ...] = ("captured", "organized", "proposed", "completion")

#: THE SNAPSHOT'S OWN FIELD NAMES, per stage role — § 2.2 rule 3's other half,
#: declared HERE and nowhere else on this side of the process boundary: *"A
#: SNAPSHOT SCHEMA KEY is not a stage name; a RENDERED WORD or a CORPUS PATH
#: is."* These names are openDox's schema, not a domain's vocabulary: the
#: renderer reads `snapshot.json`, a document this leg's own generator contract
#: fixes, and a descendant that renamed `clusters` would be shipping a different
#: snapshot rather than a different domain. They travel on the payload so the
#: CLIENT's schema map and this one cannot drift — the same reason
#: `view_manifest` carries `regions`.
#:
#: `status` is the closed VALUE the two change stations split on
#: (`changes[].status`), not a word anyone renders; `null` where a station reads
#: a whole collection.
STAGE_FIELDS: tuple[tuple[str, str, str | None], ...] = (
    ("source", "documents", None),
    ("grouping", "clusters", None),
    ("candidate", "possibles", None),
    ("selection", "staged_topics", None),
    ("submission", "changes", "active"),
    ("completion", "changes", "archived"),
)

#: THE SNAPSHOT'S CLOSED ENUM VALUES, by role — the rest of § 2.2 rule 3's
#: schema half, and the reason it is here rather than in the vocabulary above.
#:
#: `documents[].stage` and `possibles[].state` are VALUES the renderer MATCHES
#: (which column a card belongs in, which dot a candidate wears); they are never
#: VALUES IT RENDERS — every word a human reads comes from `statuses` above,
#: through `display.status(vocabulary, role)`. That distinction is exactly
#: § 2.2 rule 3's ("a class-A file MAY read a schema key; it may NOT carry a
#: word it renders"), read over a closed enum rather than over a field name, and
#: it is what keeps the product working: `build_server()` refuses without a
#: registered profile, but every profile in the estate today registers WITHOUT a
#: `DISPLAY` facet, so a board that filtered on the facet's neutral word would
#: show an empty first column against the very snapshot it was built to render.
#:
#: A HOST MAY STILL OVERRIDE THEM, on the `values` block of the facet, for the
#: descendant whose generator writes different words into the same schema. The
#: default is openDox's declaration, not a domain's silence.
SNAPSHOT_VALUES: dict[str, dict[str, str]] = {
    # `documents[].stage` — which pipeline column a source document sits in.
    "document_stage": {"captured": "brainstorm", "organized": "staged"},
    # `possibles[].state` — the candidate register's own four-state enum.
    "register_state": {"captured": "latent", "proposed": "picked",
                       "retired": "rejected", "superseded": "superseded"},
}

#: THE STAGING TEMPLATE'S CANONICAL HEADING ORDER — the last member of § 2.2
#: rule 3's schema family, and here for the same reason `SNAPSHOT_VALUES` is.
#: `views/outline-model.js` MATCHES these needles against the headings a human
#: already wrote, to decide which existing section a new one goes next to; it
#: never renders one. A domain whose staging template is shaped differently
#: overrides the list on the facet, and openDox ships the order it has always
#: shipped so that no install loses its outline ordering to a facet nobody has
#: declared yet.
SECTION_ORDER: tuple[str, ...] = (
    "last proposal attempt", "claims", "why", "what changes", "impact",
    "idea notes", "conflicts", "open questions", "exit",
)

#: openDox's OWN words — the neutral product's plain vocabulary for its own
#: shape, rendered when no host declares a `DISPLAY` facet. NOT openxFactory's
#: words, deliberately: see the module docstring's "ABSENT IS NEUTRAL" for the
#: argument, and `tests/test_display_facet.py` for the assertion that holds it
#: (no word of openxFactory's stage or status vocabulary appears here).
NEUTRAL_DISPLAY: dict[str, Any] = {
    "stages": {
        "source": {"one": "source item", "many": "source items",
                   "short": "sources", "label": "source items",
                   "gate": "declared topics"},
        "grouping": {"one": "group", "many": "groups",
                     "short": "groups", "label": "groups", "gate": None},
        "candidate": {"one": "candidate", "many": "candidates",
                      "short": "candidates", "label": "candidates",
                      "gate": "→ select gate"},
        "selection": {"one": "selection", "many": "selections",
                      "short": "selections", "label": "selections",
                      "gate": "→ submit gate"},
        "submission": {"one": "submission", "many": "submissions",
                       "short": "submissions", "label": "open submissions",
                       "gate": "→ complete gate"},
        "completion": {"one": "completed item", "many": "completed items",
                       "short": "completed", "label": "completed",
                       "gate": None},
    },
    "statuses": {
        "document": {
            "captured": "captured",
            "organized": "organized",
            "proposed": "proposed",
        },
        "change": {
            "proposed": "open",
            "ratified": "accepted",
            "promoted": "completed",
            "superseded": "replaced",
        },
        "candidate": {
            "captured": "unselected",
            "proposed": "selected",
            "retired": "declined",
            "superseded": "replaced",
        },
    },
    "areas": {
        "captured": {"prefix": None, "label": "captured material"},
        "organized": {"prefix": None, "label": "organized material"},
        "proposed": {"prefix": None, "label": "submissions"},
        "reference": {"prefix": None, "label": "other (read-only reference)"},
    },
    "tokens": {
        "captured": "#7A5AD0",
        "organized": "#0D9488",
        "proposed": "#B96A1B",
        "completion": "#3B6FD4",
    },
    "acts": {
        "derive": "derive candidates",
        "brief": "research brief",
        "promote": "promote to selection",
        "propose": "start a submission",
    },
    "artifacts": {
        "root": {"prefix": None, "label": "submission folder"},
        "packet": {"prefix": None, "label": "packet files",
                   "order": []},
        "delta": {"prefix": None, "label": "detail files"},
        "supporting": {"prefix": None, "label": "supporting files"},
    },
}

#: THE ARTIFACT-FOLDER VOCABULARY, by role — the axis RULED Q1's own argument
#: names ("the profile already has to carry an artifact-vocabulary axis for
#: `outline-model.js`") and the one § 2.1 says is `views/explorer.js`'s "only
#: domain content". `root` is the folder prefix a submission's files live under;
#: `packet` is its ORDERED front matter (openxFactory: `proposal.md`,
#: `design.md`, `tasks.md`); `delta` and `supporting` are the two subfolders the
#: explorer groups by. Every prefix is `None` in the neutral vocabulary, because
#: a product told no corpus layout has none — the explorer then groups by folder
#: and says so, which is the honest answer.
ARTIFACT_ROLES: tuple[str, ...] = ("root", "packet", "delta", "supporting")

#: A design token's value: an explicit six-digit hex colour. Narrow on purpose —
#: the value is written into a CSS custom property on `:root` at boot, so a
#: permissive one is a declared injection point into the shell's own stylesheet.
_COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")

#: The status vocabularies the shell reads, by the ARTIFACT-KIND role each
#: belongs to. openxFactory's profile declares one closed word list per artifact
#: kind (`governance-document`, `openspec-change`, `register-possible`, …), and
#: the three the front end actually renders are these.
_STATUS_VOCABULARIES: tuple[str, ...] = ("document", "change", "candidate")

_STAGE_FIELDS_REQUIRED: tuple[str, ...] = ("one", "many", "short", "label")


class DisplayFacetError(ValueError):
    """A host DECLARED a `DISPLAY` facet and it does not conform.

    Distinct from the ABSENCE of the facet, which is neutral and named (see the
    module docstring): this is a declaration that cannot be read, and it is
    raised where the server is built rather than discovered as a column
    rendering `undefined`. `ViewBindingError` is the same stance for the same
    reason, and the message carries the same three things: the role, the field
    and the value.
    """


def host_display(profile: Any = None) -> Any:
    """The host's declared `DISPLAY` facet, or `None`.

    TWO ABSENCES, TWO ANSWERS, exactly as `view_extension.host_view_extensions`
    documents for `VIEW_EXTENSIONS`:

    * **NO HOST REGISTERED -> REFUSES.** `domain_profile.current()` raises
      `ProfileNotRegistered` naming the registration call and the runbook, and
      this function lets it through untouched (ASK-2's "REFUSAL, NOT A
      DEFAULT"). `build_server()` has already refused at its own read of
      `ROUTE_EXTENSIONS` long before anything asks for a word.
    * **HOST REGISTERED, NO `DISPLAY` FACET -> `None`,** which
      `display_manifest` renders as `NEUTRAL_DISPLAY` with `host_facet:
      "absent"` and the profile NAMED. Every host today is in this state — no
      profile in the estate declares the facet yet — so refusing would be a flag
      day imposed by the seam that exists to avoid one.

    `profile` is the seam a test injects through; absent, the module resolves the
    real proxy at CALL time (never at import time — the whole value of the lazy
    proxy is that importing it cannot fail for want of a host).
    """
    if profile is None:
        from opendox.profile_proxy import profile_openxfactory
        profile = profile_openxfactory
    return getattr(profile, PROFILE_FACET, None)


def _text(value: Any, *, where: str, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DisplayFacetError(
            f"the host profile's {PROFILE_FACET} facet gives {where} the value "
            f"{value!r}; a rendered word is a non-empty string. openDox reads "
            "this facet BY ROLE and renders what it is handed, so a blank is a "
            "blank surface rather than a refusal anyone can see.")
    return value


def _mapping(value: Any, *, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DisplayFacetError(
            f"the host profile's {PROFILE_FACET} facet gives {where} "
            f"{value!r}; a role table is a mapping of ROLE -> declaration. "
            "Resolve by role, not by string (openXdox-spec "
            "docs/domain-profile-design-note.md § 6).")
    return value


def _unknown_roles(declared: Iterable[str], known: Iterable[str],
                   *, where: str) -> None:
    extra = [role for role in declared if role not in tuple(known)]
    if extra:
        raise DisplayFacetError(
            f"the host profile's {PROFILE_FACET} facet declares {extra!r} under "
            f"{where}, which openDox does not read. The declared roles are "
            f"{tuple(known)!r}: a role openDox has never heard of renders "
            "nowhere, so declaring one is a silent no-op and is refused here "
            "instead.")


def normalize_display(declared: Any) -> dict[str, Any]:
    """Read a host's declared facet into the payload shape, or refuse it.

    PARTIAL IS LEGAL, AND IT IS THE POINT. A host declares the roles it has
    words for and openDox fills the rest from `NEUTRAL_DISPLAY`, per role and
    per field — so a descendant that has renamed only its candidate stage
    declares one entry rather than a whole vocabulary, and a facet written
    against a later revision of this module keeps working for the roles both
    ends know. An UNKNOWN role is still refused: it renders nowhere, so
    accepting it would be accepting a silent no-op.
    """
    if declared is None:
        return _copy_display(NEUTRAL_DISPLAY)
    table = _mapping(declared, where="the facet itself")
    _unknown_roles(table.keys(),
                   ("stages", "statuses", "areas", "tokens", "acts",
                    "artifacts", "values", "sections"),
                   where="the facet itself")
    out = _copy_display(NEUTRAL_DISPLAY)

    stages = _mapping(table.get("stages", {}), where="stages")
    _unknown_roles(stages.keys(), STAGE_ROLES, where="stages")
    for role, entry in stages.items():
        fields = _mapping(entry, where=f"stages.{role}")
        _unknown_roles(fields.keys(),
                       _STAGE_FIELDS_REQUIRED + ("gate",),
                       where=f"stages.{role}")
        for field in _STAGE_FIELDS_REQUIRED:
            if field in fields:
                out["stages"][role][field] = _text(
                    fields[field], where=f"stages.{role}.{field}")
        if "gate" in fields:
            out["stages"][role]["gate"] = _text(
                fields["gate"], where=f"stages.{role}.gate", allow_none=True)

    statuses = _mapping(table.get("statuses", {}), where="statuses")
    _unknown_roles(statuses.keys(), _STATUS_VOCABULARIES, where="statuses")
    for vocabulary, entry in statuses.items():
        words = _mapping(entry, where=f"statuses.{vocabulary}")
        _unknown_roles(words.keys(), STATUS_ROLES,
                       where=f"statuses.{vocabulary}")
        for role, word in words.items():
            out["statuses"][vocabulary][role] = _text(
                word, where=f"statuses.{vocabulary}.{role}")

    areas = _mapping(table.get("areas", {}), where="areas")
    _unknown_roles(areas.keys(), AREA_ROLES, where="areas")
    for role, entry in areas.items():
        fields = _mapping(entry, where=f"areas.{role}")
        _unknown_roles(fields.keys(), ("prefix", "label"),
                       where=f"areas.{role}")
        if "label" in fields:
            out["areas"][role]["label"] = _text(
                fields["label"], where=f"areas.{role}.label")
        if "prefix" in fields:
            prefix = _text(fields["prefix"], where=f"areas.{role}.prefix",
                           allow_none=True)
            if role == "reference" and prefix is not None:
                raise DisplayFacetError(
                    "the host profile's DISPLAY facet gives areas.reference a "
                    f"prefix ({prefix!r}). `reference` is the TERMINAL bucket — "
                    "every document the declared areas do not claim — so a "
                    "prefix on it would leave the documents outside every "
                    "declared area with nowhere to be listed.")
            out["areas"][role]["prefix"] = prefix

    tokens = _mapping(table.get("tokens", {}), where="tokens")
    _unknown_roles(tokens.keys(), TOKEN_ROLES, where="tokens")
    for role, value in tokens.items():
        if not isinstance(value, str) or not _COLOUR.match(value):
            raise DisplayFacetError(
                f"the host profile's {PROFILE_FACET} facet gives tokens.{role} "
                f"the value {value!r}; a design token is an explicit "
                "`#rrggbb` colour. The value is written into a CSS custom "
                "property on `:root` at boot, so anything wider is a declared "
                "injection point into the shell's own stylesheet.")
        out["tokens"][role] = value

    artifacts = _mapping(table.get("artifacts", {}), where="artifacts")
    _unknown_roles(artifacts.keys(), ARTIFACT_ROLES, where="artifacts")
    for role, entry in artifacts.items():
        fields = _mapping(entry, where=f"artifacts.{role}")
        _unknown_roles(fields.keys(), ("prefix", "label", "order"),
                       where=f"artifacts.{role}")
        if "label" in fields:
            out["artifacts"][role]["label"] = _text(
                fields["label"], where=f"artifacts.{role}.label")
        if "prefix" in fields:
            out["artifacts"][role]["prefix"] = _text(
                fields["prefix"], where=f"artifacts.{role}.prefix",
                allow_none=True)
        if "order" in fields:
            order = fields["order"]
            if not isinstance(order, (list, tuple)):
                raise DisplayFacetError(
                    f"the host profile's {PROFILE_FACET} facet gives "
                    f"artifacts.{role}.order {order!r}; an ORDER is a list of "
                    "file names, read left to right.")
            out["artifacts"][role]["order"] = [
                _text(name, where=f"artifacts.{role}.order") for name in order]

    acts = _mapping(table.get("acts", {}), where="acts")
    _unknown_roles(acts.keys(), tuple(NEUTRAL_DISPLAY["acts"]), where="acts")
    for role, word in acts.items():
        out["acts"][role] = _text(word, where=f"acts.{role}")
    return out


def _copy_display(source: Mapping[str, Any]) -> dict[str, Any]:
    """A deep-enough copy: the payload is two levels of plain mappings.

    Written out rather than `copy.deepcopy`d so that the shape this module
    promises is visible in this module, and so that a future third level fails
    loudly here instead of being aliased into every served payload.
    """
    return {
        "stages": {role: dict(entry)
                   for role, entry in source["stages"].items()},
        "statuses": {vocabulary: dict(words)
                     for vocabulary, words in source["statuses"].items()},
        "areas": {role: dict(entry)
                  for role, entry in source["areas"].items()},
        "tokens": dict(source["tokens"]),
        "acts": dict(source["acts"]),
        "artifacts": {role: dict(entry)
                      for role, entry in source["artifacts"].items()},
    }


def _section_order(declared: Any) -> list[str]:
    """The staging template's heading order, host-overridden where declared."""
    if declared is None:
        return list(SECTION_ORDER)
    table = _mapping(declared, where="the facet itself")
    order = table.get("sections")
    if order is None:
        return list(SECTION_ORDER)
    if not isinstance(order, (list, tuple)):
        raise DisplayFacetError(
            f"the host profile's {PROFILE_FACET} facet gives sections "
            f"{order!r}; the staging template's heading order is a list of "
            "lowercase needles, read left to right.")
    return [_text(needle, where="sections") for needle in order]


def _snapshot_values(declared: Any) -> dict[str, dict[str, str]]:
    """The snapshot's enum values, host-overridden per role where declared.

    Refuses an unknown enum or an unknown role for the same reason every other
    role table does: a value openDox never matches on changes nothing, so
    declaring one is a silent no-op.
    """
    out = {name: dict(values) for name, values in SNAPSHOT_VALUES.items()}
    if declared is None:
        return out
    table = _mapping(declared, where="the facet itself")
    values = _mapping(table.get("values", {}), where="values")
    _unknown_roles(values.keys(), tuple(SNAPSHOT_VALUES), where="values")
    for name, entry in values.items():
        words = _mapping(entry, where=f"values.{name}")
        _unknown_roles(words.keys(), tuple(SNAPSHOT_VALUES[name]),
                       where=f"values.{name}")
        for role, word in words.items():
            out[name][role] = _text(word, where=f"values.{name}.{role}")
    return out


def display_manifest(declared: Any, *, host_profile: str | None = None
                     ) -> dict[str, Any]:
    """The `display` block of `/capabilities` — the ONE crossing of the boundary.

    Carries `schema_version` and `kind` because every declared document in this
    estate does (openxFactory `CLAUDE.md` working rule 4), and because a payload
    the shell must be able to REFUSE needs to be identifiable before it is
    trusted — `view_manifest`'s own argument, applied to the vocabulary.

    `stage_order` and `fields` travel WITH the words so the client's schema map
    and this one cannot drift: the client reads the snapshot through the field
    names declared here, exactly as it reads the shell's regions through the
    `regions` table `view_manifest` publishes rather than through a second copy.

    `host_facet` / `host_profile` are the NAMED ABSENCE: `"absent"` plus the
    profile's name says a host IS registered and simply does not declare a
    vocabulary, which is a different fact from no host at all, and the shell
    then renders openDox's own neutral words rather than a domain's.
    """
    return {
        "schema_version": DISPLAY_SCHEMA_VERSION,
        "kind": DISPLAY_KIND,
        "facet": PROFILE_FACET,
        "host_facet": "declared" if declared is not None else "absent",
        "host_profile": host_profile,
        "stage_order": list(STAGE_ROLES),
        "fields": {role: {"field": field, "status": status}
                   for role, field, status in STAGE_FIELDS},
        "values": _snapshot_values(declared),
        "area_order": list(AREA_ROLES),
        "sections": _section_order(declared),
        "artifact_roles": list(ARTIFACT_ROLES),
        "token_roles": list(TOKEN_ROLES),
        **normalize_display(declared),
    }
