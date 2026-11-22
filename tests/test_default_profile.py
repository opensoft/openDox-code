"""openDox's OWN default profile, held to requirement 3 (plan 034, T015).

`src/opendox/default_profile.py` is the default profile requirement 3 of
openxFactory's `add-neutral-product-standalone-operability` asks for (RATIFIED,
`openxFactory#656` comment `5815412869`; task 3.1), carrying what Brett Heap
ruled on comment `5817152735`: openDox's own verbs (R1Q4 (a)), with
`RuntimeSubcommand` in `SUBCOMMAND_EXTENSIONS` from the first landing (R1Q5 (a)).

WHAT IT ASSERTS, AND WHY EACH IS HERE

1. THE RUNTIME VERBS ARE IN IT, and the default is never empty.
   `RuntimeSubcommand` is in `SUBCOMMAND_EXTENSIONS` and conforms to the § 2.4
   seam. Registering the tuple through that seam, with the same `register_all`
   call `cli.build_parser()` makes, gives exactly the `runtime` command that
   `opendox-runtime` builds: one registration function, so no fork. An EMPTY
   default stays refused (RULED ASK-2, comment `5628886636`, and the packet's
   design § D5), because a parser whose contributed verbs are silently absent
   looks exactly like a working one.
2. THE VOCABULARY IS HELD OUT (requirement 3's second scenario): *"WHEN a
   neutral product's default profile names the publishing repository's status
   taxonomy, its change/spec/delta nouns or its act verbs — THEN the profile is
   refused under RULING C2 and DIRECTION Q5."* Every name the default declares,
   and every word it renders or prints as help, is swept for those three
   families. A stand-in profile that carries them is caught by the same sweep,
   so the sweep is shown not to be vacuous.
3. ITS WORDS ARE openDox's OWN, UNCHANGED (requirement 3's third scenario).
   The display the default yields is `NEUTRAL_DISPLAY` byte for byte, and no
   design token is claimed as declared.
4. IT IMPORTS ALONE AND REGISTERS NOTHING. The import needs no sibling and no
   third-party module, and it registers no profile.

`--noconftest` SAFE, deliberately, like its neighbour
`tests/test_profile_registration.py`. Until plan 034's T011 lands,
`opendox.cli` and `opendox.serve` do not import in a lone checkout, and the root
conftest's autouse fixture imports `opendox.cli` (plan 034, tasks.md
§ Phase 1). So nothing here imports either module, needs a fixture, or
registers a profile.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import route_extension
import subcommand_extension
from opendox import default_profile, display_profile, domain_profile, view_extension
from opendox.display_profile import NEUTRAL_DISPLAY
from opendox.runtime import cli as runtime_cli

SRC = Path(__file__).resolve().parent.parent / "src"

#: The four packages a neutral openDox must import without: the consumer, the
#: publisher's pre-carve package, the publisher's checker and the publisher's
#: corpus adapter (#1144 Group 2's F2.1 names the same four).
SIBLINGS = ("openxdox", "ideation_dashboard", "doc_health",
            "corpus_adapter_openxfactory")

# --------------------------------------------------------------------------
# The publishing repository's vocabulary: the three families requirement 3's
# second scenario names. Each is copied from where openxFactory declares it,
# at openxFactory `42f34ab7`. openDox cannot read that tree in its own checkout,
# so the words are carried here, with their source.
# --------------------------------------------------------------------------

#: Its STATUS TAXONOMY: the eight controlled `Status:` words of
#: `docs/document-lifecycle.md`, which `tests/test_display_facet.py`'s
#: `OPENXFACTORY_WORDS` also opens with, plus `projection`, the ninth value
#: that `contracts/domain-profiles/openxfactory-engineering.yaml`'s `lifecycle`
#: block declares.
STATUS_TAXONOMY = ("brainstorm", "staged", "draft", "ratified", "standard",
                   "superseded", "retired", "record", "projection")

#: Its CHANGE/SPEC/DELTA NOUNS: the OpenSpec artifact a governed change is, and
#: the proposal that opens one.
CHANGE_SPEC_DELTA_NOUNS = ("change", "changes", "spec", "specs", "delta",
                           "deltas", "openspec", "proposal", "proposals")

#: Its ACT VERBS: the twenty values of the gate-action act enum, as the same
#: profile's `acts` block declares them.
ACT_VERBS = ("demote", "edit-apply", "ratify", "kickoff", "propose",
             "promote-to-staging", "dispose-possible", "derive-possibles",
             "research-brief", "create-document", "edit-document", "open-pr",
             "abandon-session", "share-session", "cleanup-abandoned-branch",
             "approve-model", "create-project", "edit-project",
             "lens-save-recipe", "lens-add-as-cluster")

#: One word each: compared whole against each token of a NAME, and matched as a
#: whole word in help text and in rendered words.
_WORDS = frozenset(STATUS_TAXONOMY + CHANGE_SPEC_DELTA_NOUNS
                   + tuple(verb for verb in ACT_VERBS if "-" not in verb))

#: The help strings that use a swept word in ANOTHER sense, each one measured,
#: whole, with the word it may carry. `change` is an English verb as often as
#: the OpenSpec noun, and the runtime's own help uses it that way once:
#: `runtime migrate --plan` reads "report what would be applied and change
#: nothing". Only that exact string is exempt, and only for that word. So any
#: other use of `change` or `changes` in help text, noun or verb, fails the
#: sweep until someone has read it and entered it here.
#: `test_every_exempt_help_string_is_one_the_default_really_carries` keeps the
#: list from outliving the text it names.
_OTHER_SENSES = frozenset({
    ("change", "report what would be applied and change nothing"),
})


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    found = [a for a in parser._actions
             if isinstance(a, argparse._SubParsersAction)]
    assert len(found) == 1, f"{parser.prog} has {len(found)} subparsers actions"
    return found[0]


def _contributed_parser(extensions) -> argparse.ArgumentParser:
    """A bare parser with `extensions` registered through the § 2.4 seam.

    The same call `cli.build_parser()` makes for the profile it resolves
    (`subcommand_extension.register_all(<SUBCOMMAND_EXTENSIONS>, sub)`), on a
    parser that carries no core verb, so what it holds is exactly the
    contribution.
    """
    parser = argparse.ArgumentParser(prog="opendox")
    sub = parser.add_subparsers(dest="command", required=True)
    subcommand_extension.register_all(tuple(extensions), sub)
    return parser


def _walk(parser: argparse.ArgumentParser, names: list[str],
          prose: list[str]) -> None:
    """Every NAME and every sentence of HELP a parser tree declares.

    NAMES are what a user types or a program reads: command and verb names,
    option strings, `dest`s, `choices` and metavars. PROSE is what a user reads:
    descriptions and help strings.
    """
    if parser.description:
        prose.append(parser.description)
    for action in parser._actions:
        names.extend(action.option_strings)
        if isinstance(action.dest, str) and action.dest != argparse.SUPPRESS:
            names.append(action.dest)
        if isinstance(action.metavar, str):
            names.append(action.metavar)
        if isinstance(action.help, str) and action.help != argparse.SUPPRESS:
            prose.append(action.help)
        if isinstance(action, argparse._SubParsersAction):
            for pseudo in action._choices_actions:
                if isinstance(pseudo.help, str):
                    prose.append(pseudo.help)
            for name, child in action.choices.items():
                names.append(name)
                _walk(child, names, prose)
        elif action.choices is not None:
            names.extend(str(choice) for choice in action.choices)


def _declared(profile) -> tuple[list[str], list[str], list[str]]:
    """What `profile` declares: its NAMES, its HELP PROSE and its DISPLAY WORDS.

    * The command tree its `SUBCOMMAND_EXTENSIONS` contribute, walked whole.
    * The patterns and handler names its `ROUTE_EXTENSIONS` bind.
    * The views its `VIEW_EXTENSIONS` facet contributes, read the way the
      server reads them.
    * Its own registered name, as every refusal and `/capabilities` quote it.
    * The words its display renders: every string VALUE of the display
      manifest built from its `DISPLAY` facet, less the schema half, which
      carries openDox's own field names and role keys and no word a human reads.
    """
    names: list[str] = [domain_profile.name_of(profile)]
    prose: list[str] = []
    _walk(_contributed_parser(profile.SUBCOMMAND_EXTENSIONS), names, prose)
    for extension in profile.ROUTE_EXTENSIONS:
        for binding in extension.routes():
            names.extend(str(getattr(binding, field, "") or "")
                         for field in ("pattern", "handler"))
    _facet, views = view_extension.host_view_facet(profile)
    for view in views:
        names.extend(str(getattr(view, field, "") or "")
                     for field in ("id", "view_id", "module", "region"))
    manifest = display_profile.display_manifest(
        display_profile.host_display(profile),
        host_profile=domain_profile.name_of(profile))
    schema_half = {"fields", "values", "stage_order", "area_order",
                   "artifact_roles", "token_roles", "sections", "kind", "facet",
                   "schema_version", "host_profile", "host_facet",
                   "declared_tokens"}
    words: list[str] = []

    def strings(value) -> None:
        if isinstance(value, str):
            words.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                strings(item)

    strings({k: v for k, v in manifest.items() if k not in schema_half})
    return names, prose, words


def _offending_names(names: list[str]) -> list[str]:
    """Each NAME that carries a word of the three families.

    A name is split into its tokens (`--log-level` is `log`, `level`), and a
    token matching a word is an offence. So is a hyphenated act verb spelled
    anywhere inside the name, `gate-open-pr` as much as `open-pr`.
    """
    offences: set[str] = set()
    for name in names:
        normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        tokens = normalized.split("-")
        for token in tokens:
            if token in _WORDS:
                offences.add(f"{name!r} names {token!r}")
        for verb in ACT_VERBS:
            if "-" in verb and f"-{verb}-" in f"-{normalized}-":
                offences.add(f"{name!r} names {verb!r}")
    return sorted(offences)


def _offending_words(texts: list[str], words: frozenset[str], *,
                     exempt: frozenset[tuple[str, str]] = frozenset()
                     ) -> list[str]:
    """Each whole word of `words`, and each hyphenated act verb, in `texts`.

    `exempt` holds `(word, text)` pairs read and found to use the word in
    another sense. It exempts that word in that whole text, and nothing else.
    """
    offences: set[str] = set()
    for text in texts:
        lowered = text.lower()
        for word in words:
            if (word, text) in exempt:
                continue
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                offences.add(f"{word!r} in {text!r}")
        for verb in ACT_VERBS:
            if "-" in verb and verb in lowered:
                offences.add(f"{verb!r} in {text!r}")
    return sorted(offences)


# --------------------------------------------------------------------------
# 1 — the runtime verbs are in it, and it is never empty
# --------------------------------------------------------------------------

def test_runtime_subcommand_is_in_the_defaults_subcommand_extensions() -> None:
    """R1Q5 (a): the runtime verbs arrive through the default's own facet.

    From the first landing, so that no build between this task and the console
    script (T038) ever meets a default that contributes nothing.
    """
    extensions = tuple(default_profile.SUBCOMMAND_EXTENSIONS)
    assert any(isinstance(extension, runtime_cli.RuntimeSubcommand)
               for extension in extensions), (
        "RuntimeSubcommand is not in the default profile's SUBCOMMAND_EXTENSIONS "
        f"({extensions!r}). R1Q5 (a), openxFactory#656 comment 5817152735, "
        "wires the runtime verbs through exactly this facet")
    for extension in extensions:
        assert isinstance(extension, subcommand_extension.SubcommandExtension), (
            f"{extension!r} does not conform to the § 2.4 seam, so "
            "`build_parser()` would refuse it where it is wired")


def test_the_default_is_never_an_empty_profile() -> None:
    """RULED ASK-2's reason, which requirement 3 keeps: an EMPTY default is refused."""
    assert tuple(default_profile.SUBCOMMAND_EXTENSIONS), (
        "the default profile contributes no verb. A parser built on it would be "
        "indistinguishable from a working one with its verbs silently absent, "
        "which is the failure RULED ASK-2 (comment 5628886636) refuses and the "
        "packet's design § D5 keeps refused")


def test_the_default_contributes_the_runtime_command_opendox_runtime_builds() -> None:
    """One registration function, two spellings: the seam and the alias agree.

    The contribution is registered through `subcommand_extension.register_all`,
    the call `cli.build_parser()` makes, and compared with the `runtime` command
    the `opendox-runtime` console script builds, verb for verb and option for
    option. `project` is NOT contributed: R1Q5 (a) names the runtime verbs
    alone, so `project create-repository` stays on the alias (plan 034, T006's
    finding U4).
    """
    contributed = _subparsers(_contributed_parser(
        default_profile.SUBCOMMAND_EXTENSIONS))
    assert list(contributed.choices) == ["runtime", "submit", "land"], (
        f"the default contributes {list(contributed.choices)}, where R1Q4 (a) "
        "and R1Q5 (a) give it the runtime verbs, plan 038 T015 adds `submit` "
        "(#1144 12.4a) and T016 adds `land` (12.6a). A further verb is a "
        "ruled act: release 2's health, or the `project` command if Brett "
        "Heap rules on U4")

    def shape(parser: argparse.ArgumentParser) -> dict:
        verbs = _subparsers(parser)
        return {name: sorted(((tuple(a.option_strings), a.dest, a.help)
                              for a in child._actions), key=repr)
                for name, child in verbs.choices.items()}

    alias = _subparsers(runtime_cli.build_parser()).choices["runtime"]
    ours = contributed.choices["runtime"]
    assert tuple(_subparsers(ours).choices) == runtime_cli.VERBS
    assert shape(ours) == shape(alias), (
        "the default's `runtime` command differs from the one opendox-runtime "
        "builds, so the two spellings are no longer one registration")


def test_the_default_declares_the_two_facets_the_composition_points_read() -> None:
    """The two facets openDox reads STRICTLY, and the two it reads with a default.

    `build_parser()` reads `SUBCOMMAND_EXTENSIONS` and `build_server()` reads
    `ROUTE_EXTENSIONS`, and a registered profile without either is refused
    (`profile_proxy.ProfileFacetMissing`), so both are declared. `DISPLAY` and
    `VIEW_EXTENSIONS` are read with a named absence, and the default declares
    neither (the module docstring gives why). T010's `HANDLER_CONTRIBUTIONS`
    is read by presence, and the default declares it since plan 038 T015: its
    one mixin, `serve_branch_actions.BranchActionRoutes`, holds the method the
    default's submit route names (#1144 12.4a).
    """
    assert isinstance(default_profile.SUBCOMMAND_EXTENSIONS, tuple)
    assert isinstance(default_profile.ROUTE_EXTENSIONS, tuple)
    assert not hasattr(default_profile, display_profile.PROFILE_FACET)
    assert not hasattr(default_profile, view_extension.PROFILE_FACET)
    assert view_extension.host_view_facet(default_profile) == ("absent", ())
    from opendox.serve_branch_actions import BranchActionRoutes
    assert route_extension.declared_handler_contributions(default_profile) == (
        BranchActionRoutes,)


def test_the_default_is_named_by_its_module_path() -> None:
    """Every refusal and every `/capabilities` payload names it this way."""
    assert domain_profile.name_of(default_profile) == "opendox.default_profile"


# --------------------------------------------------------------------------
# 2 — the publishing repository's vocabulary is held out
# --------------------------------------------------------------------------

def test_the_default_names_none_of_the_publishers_vocabulary() -> None:
    """Requirement 3, second scenario, over every name the default declares."""
    names, _prose, _words = _declared(default_profile)
    assert "runtime" in names and "--plan" in names, (
        "the sweep read no command tree, so it would pass over anything")
    offences = _offending_names(names)
    assert not offences, (
        "the default profile names the publishing repository's vocabulary: "
        f"{offences}. Requirement 3's second scenario refuses it under RULING "
        "C2 and DIRECTION Q5; those words stay in the declaration of the domain "
        "they belong to")


def test_the_defaults_help_carries_none_of_the_publishers_vocabulary() -> None:
    """The same sweep over every description and help string it contributes."""
    _names, prose, _words = _declared(default_profile)
    assert prose, "the sweep read no help text"
    offences = _offending_words(prose, _WORDS, exempt=_OTHER_SENSES)
    assert not offences, (
        f"the default profile's help text carries {offences}, words of the "
        "publishing repository's status taxonomy, nouns or acts. If one is used "
        "in another sense, read it and enter the whole string in _OTHER_SENSES")


def test_every_exempt_help_string_is_one_the_default_really_carries() -> None:
    """An exemption names text that exists, and a swept word that is in it.

    Otherwise the list would go on exempting a string after the text had
    changed, and a new use of the word could come in under a stale entry.
    """
    _names, prose, _words = _declared(default_profile)
    for word, text in sorted(_OTHER_SENSES):
        assert text in prose, (
            f"_OTHER_SENSES exempts {text!r}, which the default no longer "
            "carries as a help string; remove the entry")
        assert word in _WORDS and re.search(rf"\b{re.escape(word)}\b",
                                            text.lower()), (
            f"_OTHER_SENSES exempts {word!r} in {text!r}, where it does not occur")


def test_the_default_renders_none_of_the_publishers_vocabulary() -> None:
    """The same sweep over every word the default's display renders."""
    _names, _prose, words = _declared(default_profile)
    assert words, "the sweep read no rendered word"
    offences = _offending_words(words, _WORDS)
    assert not offences, (
        f"the default profile's display renders {offences}, words of the "
        "publishing repository's vocabulary, where openDox's own words belong")


def test_the_sweep_catches_a_profile_that_carries_the_vocabulary() -> None:
    """The three sweeps above prove nothing unless they can fail.

    A stand-in that contributes openxFactory's gate verbs, spells a status word
    in an option, writes a noun into its help and renders a status word is
    caught by every one of them.
    """
    class _GovernedExtension:
        def register(self, subparsers) -> None:
            gate = subparsers.add_parser("gate", help="ratify the spec delta")
            verbs = gate.add_subparsers(dest="gate_command", required=True)
            verbs.add_parser("open-pr", help="open a pull request")
            ratify = verbs.add_parser("ratify", help="ratify a change")
            ratify.add_argument("--staged", action="store_true",
                                help="only staged documents")

    class _GovernedProfile:
        SUBCOMMAND_EXTENSIONS = (_GovernedExtension(),)
        ROUTE_EXTENSIONS = ()
        DISPLAY = {"stages": {"source": {"label": "brainstorm"}}}

    names, prose, words = _declared(_GovernedProfile())
    assert {"'ratify' names 'ratify'", "'open-pr' names 'open-pr'",
            "'--staged' names 'staged'"} <= set(_offending_names(names))
    help_offences = _offending_words(prose, _WORDS, exempt=_OTHER_SENSES)
    assert {"'spec' in 'ratify the spec delta'",
            "'change' in 'ratify a change'"} <= set(help_offences), (
        "the help sweep missed a noun, `change` among them: the exemption for "
        "the runtime's verb must not exempt the word elsewhere")
    assert any("'brainstorm'" in offence
               for offence in _offending_words(words, _WORDS))


# --------------------------------------------------------------------------
# 3 — its words are openDox's own, unchanged
# --------------------------------------------------------------------------

def test_the_default_renders_neutral_display_unchanged() -> None:
    """Requirement 3, third scenario: *"those words are the default profile's
    vocabulary unchanged"*, which R1Q4 (a) states as `DISPLAY` =
    `NEUTRAL_DISPLAY`.

    The display the default yields, built exactly as `build_server()` builds
    it, equals the neutral one field for field, and its word tables are
    `NEUTRAL_DISPLAY`'s own.
    """
    name = domain_profile.name_of(default_profile)
    ours = display_profile.display_manifest(
        display_profile.host_display(default_profile), host_profile=name)
    neutral = display_profile.display_manifest(None, host_profile=name)
    assert ours == neutral
    for table in ("stages", "statuses", "areas", "tokens", "acts", "artifacts"):
        assert ours[table] == NEUTRAL_DISPLAY[table], (
            f"the default's {table!r} table is not NEUTRAL_DISPLAY's")


def test_the_default_claims_no_design_token_so_dark_mode_keeps_its_palette() -> None:
    """Why the default declares no `DISPLAY` facet, rather than NEUTRAL_DISPLAY.

    `display_manifest` reports a facet's tokens as the HOST's own
    (`declared_tokens`), and `views/display.js` writes exactly those onto
    `:root` inline, where they outrank every per-theme rule in `styles.css`
    (`tests/test_display_facet.py::test_only_the_tokens_a_host_declared_are_written_onto_root`).
    The literal spelling, `DISPLAY = NEUTRAL_DISPLAY`, would claim all four and
    pin the light palette onto a standalone install. The default claims none.
    """
    ours = display_profile.display_manifest(
        display_profile.host_display(default_profile))
    assert ours["host_facet"] == "absent"
    assert ours["declared_tokens"] == []
    literal = display_profile.display_manifest(NEUTRAL_DISPLAY)
    assert literal["declared_tokens"] == list(display_profile.TOKEN_ROLES), (
        "the reason this default declares no DISPLAY facet no longer holds; "
        "re-read the module docstring before changing either")


# --------------------------------------------------------------------------
# 4 — it imports alone, and importing it registers nothing
# --------------------------------------------------------------------------

def test_importing_the_default_registers_nothing_and_needs_no_sibling() -> None:
    """In a fresh interpreter, with the four siblings made unimportable.

    Importing the default registers no profile: the entry points register it
    (R1Q3 (a)), so a process that builds nothing still meets
    `ProfileNotRegistered`. And the import loads no module outside the standard
    library and `opendox` itself, so it needs no extra. T038's plain-install
    runs show the same from outside.
    """
    program = f"import sys; sys.path.insert(0, {str(SRC)!r})\n" + textwrap.dedent(f"""
        for name in {SIBLINGS!r}:
            sys.modules[name] = None
        before = set(sys.modules)
        import opendox.default_profile
        loaded = sorted(set(sys.modules) - before)
        from opendox import domain_profile
        assert not domain_profile.is_registered(), "importing registered a profile"
        foreign = [m for m in loaded
                   if m.split(".")[0] not in sys.stdlib_module_names
                   and m.split(".")[0] != "opendox"]
        assert not foreign, f"importing the default loaded {{foreign}}"
        print("clean")
    """)
    done = subprocess.run([sys.executable, "-c", program],
                          capture_output=True, text=True)
    assert done.returncode == 0, (
        "importing openDox's default profile failed, registered something, or "
        f"loaded a module outside the standard library:\n{done.stderr}")
    assert "clean" in done.stdout


@pytest.mark.parametrize("sibling", SIBLINGS)
def test_the_default_names_no_sibling_package(sibling: str) -> None:
    """Parsed, not grepped: no import of a sibling anywhere in the module."""
    import ast

    tree = ast.parse(Path(default_profile.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        imported: list[str] = []
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported = [node.module]
        for name in imported:
            assert name.split(".")[0] != sibling, (
                f"default_profile.py imports {name!r} at line {node.lineno}")
