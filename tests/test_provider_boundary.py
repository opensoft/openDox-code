"""THE NARROWED PROVIDER BOUNDARY (add-model-provider-broker task 2.3).

WHAT THIS FILE REPLACES, AND WHY IT IS NOT A DELETION. Before this change the
claim was "no provider is contacted from this repository", and it was enforced
by a family of PER-MODULE source scans — `test_doxbench_model.py`'s
`FORBIDDEN_SOURCE_SNIPPETS`, `test_doxbench_turns.py`'s copy of it,
`test_doxbench_packet.py`'s, `test_doxbench_knowledge.py`'s,
`test_doxbench_threads.py`'s, `test_doxbench_memory_gateway.py`'s,
`test_doxbench_bridge.py`'s credential-name scan, and the browser-side scans in
`test_doxbench_privacy.py` / `test_doxbench_transport.py` /
`test_doxbench_mutation_boundary.py`. Every one of those still exists, still
scans exactly what it scanned, and still passes UNMODIFIED — this file pins
their continued existence by name at the bottom, precisely so the narrowing
cannot be achieved by deleting the guard it narrows.

What none of them ever did was sweep the PACKAGE. Each names one module, so a
NEW module added under `scripts/ideation_dashboard/` (the package's pre-carve
home; it is `src/opendox/` at this leg) inherited no check at all — which is
exactly the gap a change that introduces a provider client must close rather
than widen. So the boundary is restated here in the form the ratified delta
gives it:

    Exactly ONE named module may hold a provider endpoint, a provider SDK, or a
    minted token, and every other module in this repository stays free of all
    three.

and it is enforced package-wide, over every `*.py` under `src/opendox/`, with
exactly one exemption whose name the module itself declares
(`doxbench_provider.PROVIDER_CLIENT_MODULE`).

TWO TIERS, because the honest rule has two. The PROVIDER tier — SDK imports,
provider hosts and paths, this repository's own minted-token type — is exempt
for one module and one module only. The generic HTTP-CLIENT tier
(`urllib.request`, `Authorization`, `Bearer `) has other, NAMED holders: the
runtime's identity surface, whose bearer token is the IDENTITY BROKER's, and is
not a provider credential in any sense. Rather than let that exemption blur the
rule, this file asserts POSITIVELY that each of them holds nothing from the
provider tier — so its presence on the second list cannot become a doorway to
the first.

THE VIEWS CLAUSE STAYS ABSOLUTE. No browser module is exempt from anything: a
token in a page is exfiltratable by anything able to run script there, and the
provider call is made server-side precisely so no page ever holds one.

REPAIRED AT THIS LEG FOR #1144 16.6's THREE STALE REASONS (plan 034 T034). The
file arrived with the carve and stayed a standing red that no required check
ran: 12 of its 28 cases failed, for three reasons, none of them a crossing.

  1. IT READ `snapshot_registry.py`, its second HTTP-client holder. The carve
     sent that module to openXdox-code (`src/openxdox/snapshot_registry.py`), so
     it holds nothing in THIS package, and the claim about it is not this
     leg's to make.
  2. IT PINNED SEVEN PER-MODULE SCAN SUITES BY FILENAME that this checkout does
     not carry. The carve sent five to openXdox-code and left two in
     openxFactory (`stays_openxfactory_adapter`). They are recorded below with
     their homes. This file asserts the three that are here, and that the seven
     are not.
  3. ITS SWEEP REACHED THE RUNTIME (`split-opendox` § 3.5), which the carve
     created at this leg and never scanned. `runtime/app.py` spells
     `Authorization` and `Bearer ` for the identity broker's token, which it
     checks on the way in. `runtime/oidc.py`, which verifies that token,
     spells `Authorization` where it says what this runtime's authorization
     is. `runtime/config.py` names `access_token` among the secret parameter
     names it refuses and redacts. None of them holds a provider credential.
     Each is named below, with its reason, and the provider tier is asserted
     absent from each.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from conftest import REPO_ROOT

from opendox import doxbench_provider as provider_mod

PACKAGE = REPO_ROOT / "src" / "opendox"
WEB = PACKAGE / "web"

#: The ONE module the boundary permits. Read from the module's own constant so
#: the test and the module cannot drift into naming two different files.
PROVIDER_CLIENT_MODULE = provider_mod.PROVIDER_CLIENT_MODULE

#: THE RUNTIME'S IDENTITY SURFACE (`split-opendox` § 3.5): the generic
#: HTTP-client needles' other named holders, and holders of nothing from the
#: provider tier. `runtime/app.py` takes the `Authorization: Bearer` header a
#: caller presents, and `runtime/oidc.py` verifies that token against the
#: identity broker's published keys. The token is the BROKER's and says WHO the
#: caller is. It travels only INTO this process, and neither module mints it,
#: stores it or presents it to anything, which is what separates it from a
#: provider credential. They replace `snapshot_registry.py`, the snapshot data
#: source's bearer client, which the carve sent to openXdox-code. Paths are
#: relative to the package, because the runtime is a SUBPACKAGE and a bare
#: filename (`app.py`) names no one module.
IDENTITY_MODULES: tuple[str, ...] = ("runtime/app.py", "runtime/oidc.py")

#: ONE provider-tier spelling that ONE module may carry, and why.
#: `runtime/config.py` names `access_token` in `SECRET_PARAMETER_KEYS`: the
#: credential NAMES the runtime refuses in a configured URL and redacts from
#: anything it prints. A module that lists a credential's name so that it never
#: accepts or shows one is the opposite of a module that holds one. So the
#: permit is exactly that needle, in exactly that module, only while that
#: declared list still names it — and the rest of the provider tier is asserted
#: absent there, as it is everywhere else.
#: `module -> (needle, the declared tuple that must name it)`.
REDACTION_PERMITS: dict[str, tuple[str, str]] = {
    "runtime/config.py": ("access_token", "SECRET_PARAMETER_KEYS"),
}

# --- tier one: PROVIDER endpoints, PROVIDER SDKs, MINTED TOKENS -------------
#
# Every needle here is absent from every module in the package except the one
# named above — measured, not assumed, on the tree this change landed on.
PROVIDER_NEEDLES: tuple[str, ...] = (
    # provider SDKs
    "import openai",
    "import anthropic",
    "from openai",
    "from anthropic",
    "boto3",
    "google.generativeai",
    "mistralai",
    "import cohere",
    "import ollama",
    # provider endpoints
    "api.openai.com",
    "api.anthropic.com",
    "generativelanguage.googleapis.com",
    "openai.azure.com",
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/messages",
    # credential-shaped header and field spellings a provider client needs
    "apiKey",
    "api-key",
    "x-api-key",
    "access_token",
    "refresh_token",
    "client_secret",
    # THIS repository's own minted-token type and provider-call helpers: the
    # names by which a second module would have to hold a token to use one
    "MintedToken",
    "_post_to_provider",
    "PROVIDER_STATUS_TOKEN_EXPIRED",
    "PROVIDER_REQUEST_PROMPT_FIELD",
)

# --- tier two: the generic HTTP client -------------------------------------
HTTP_CLIENT_NEEDLES: tuple[str, ...] = (
    "urllib.request",
    "Authorization",
    "Bearer ",
)


def _package_modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _name(path: Path) -> str:
    """A module's path relative to the package: `serve.py`, `runtime/app.py`."""
    return path.relative_to(PACKAGE).as_posix()


def _declared_strings(path: Path, constant: str) -> set[str]:
    """The string elements of one module-level tuple, read with `ast`.

    Parsed rather than imported, so the permit's condition holds under the
    `test` extra alone, where the runtime's third-party packages are absent."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == constant for t in node.targets):
            return {e.value for e in ast.walk(node.value)
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# the package sweep
# ===========================================================================


def test_exactly_one_module_may_hold_a_provider_endpoint_or_a_minted_token():
    """THE NARROWED BOUNDARY, swept over every module in the package.

    The one permit is `REDACTION_PERMITS`' single needle in its single module,
    which a later case holds to its declared reason."""
    offenders: list[str] = []
    for module in _package_modules():
        if _name(module) == PROVIDER_CLIENT_MODULE:
            continue
        source = _source(module)
        permitted = REDACTION_PERMITS.get(_name(module), (None, None))[0]
        for needle in PROVIDER_NEEDLES:
            if needle in source and needle != permitted:
                offenders.append(f"{_name(module)}: {needle}")
    assert not offenders, (
        "the provider boundary is exactly one module wide; these modules "
        f"crossed it: {offenders}")


def test_the_exemption_is_not_vacuous():
    """The named module really IS the one holding the transport.

    Without this, the sweep above would pass just as well if the provider
    client were deleted, or if it never contacted a provider at all — and a
    boundary drawn around an empty room proves nothing. It also pins the
    module's self-declaration equal to the name this file exempts."""
    module = PACKAGE / PROVIDER_CLIENT_MODULE
    assert module.is_file(), PROVIDER_CLIENT_MODULE
    source = _source(module)
    for needle in ("urllib.request", "Authorization", "Bearer ", "MintedToken",
                   "_post_to_provider"):
        assert needle in source, needle
    assert provider_mod.PROVIDER_CLIENT_MODULE == module.name


def test_the_generic_http_client_has_exactly_its_named_holders():
    """`urllib.request` / `Authorization` / `Bearer ` are HTTP-client facts, not
    provider facts, so their other holders are named rather than swept away:
    the provider client, and the runtime's identity surface."""
    permitted = {PROVIDER_CLIENT_MODULE, *IDENTITY_MODULES}
    offenders: list[str] = []
    holders_seen: set[str] = set()
    for module in _package_modules():
        if _name(module) in permitted:
            source = _source(module)
            if any(needle in source for needle in HTTP_CLIENT_NEEDLES):
                holders_seen.add(_name(module))
            continue
        source = _source(module)
        for needle in HTTP_CLIENT_NEEDLES:
            if needle in source:
                offenders.append(f"{_name(module)}: {needle}")
    assert not offenders, offenders
    # "Exactly" means both halves: no unnamed holder above, and each named
    # holder really holds — an exemption for a module with no needles would be
    # a stale permit waiting to hide a future offender.
    assert holders_seen == permitted, holders_seen


@pytest.mark.parametrize("module_name", IDENTITY_MODULES)
def test_the_identity_surface_holds_nothing_from_the_provider_tier(module_name):
    """The identity holders' exemption reaches tier two and stops there.

    Their bearer token is the identity broker's, and it only ever arrives: it is
    not a provider credential, and this assertion is what keeps that
    distinction from eroding into a second doorway. It is the assertion this
    file made of `snapshot_registry.py` before the carve took that module to
    openXdox-code."""
    source = _source(PACKAGE / module_name)
    for needle in PROVIDER_NEEDLES:
        assert needle not in source, f"{module_name}: {needle}"


@pytest.mark.parametrize("module_name", sorted(REDACTION_PERMITS))
def test_a_redaction_permit_names_a_credential_only_to_refuse_it(module_name):
    """The one provider-tier permit is exactly as wide as its reason.

    The permitted needle is still THERE (a permit for a spelling a module no
    longer carries is a stale permit), the declared refusal list still NAMES it
    (the reason the permit exists), and no OTHER provider-tier spelling is in
    the module."""
    needle, declared = REDACTION_PERMITS[module_name]
    path = PACKAGE / module_name
    source = _source(path)
    assert needle in source, (
        f"{module_name} no longer spells {needle!r}: remove its permit")
    assert needle in _declared_strings(path, declared), (
        f"{module_name}'s {declared} no longer names {needle!r}, so the spelling "
        "is no longer a name the module refuses, and the permit's reason is gone")
    others = [n for n in PROVIDER_NEEDLES if n != needle and n in source]
    assert not others, f"{module_name}: {others}"


# ===========================================================================
# the views clause — ABSOLUTE, no module exempt
# ===========================================================================

BROWSER_NEEDLES: tuple[str, ...] = (
    "Authorization",
    "Bearer",
    "api_key",
    "apiKey",
    "api-key",
    "x-api-key",
    "access_token",
    "MintedToken",
    "https://",
    "api.openai.com",
    "api.anthropic.com",
)


def _browser_modules() -> list[Path]:
    return sorted(path for path in WEB.rglob("*.js")
                  if "vendor" not in path.relative_to(WEB).parts)


@pytest.mark.parametrize("needle", BROWSER_NEEDLES)
def test_no_browser_module_carries_a_provider_endpoint_or_a_token(needle):
    """A minted token NEVER crosses to the browser, and no page names a
    provider. Absolute: the one-module exemption does not reach here, because
    the browser is where a token would be most exfiltratable and least
    necessary."""
    offenders = [path.relative_to(WEB).as_posix()
                 for path in _browser_modules()
                 if needle in _source(path)]
    assert not offenders, f"{needle} appears in {offenders}"


# ===========================================================================
# the guard this one narrows still exists
# ===========================================================================

#: (test module, the assertion or constant that must survive in it). A clobber
#: that "passed" this file by deleting the per-module scans it narrows would
#: fail here instead. Only the scans THIS checkout carries: the carve took the
#: rest elsewhere (below).
PRESERVED_SCANS: tuple[tuple[str, str], ...] = (
    ("test_doxbench_knowledge.py",
     "def test_the_knowledge_module_contains_no_forbidden_spelling"),
    ("test_doxbench_memory_gateway.py",
     "def test_the_declaration_module_contains_no_forbidden_spelling"),
    ("test_doxbench_privacy.py", "FORBIDDEN_SOURCE_NEEDLES"),
)

#: The per-module scans this file pinned before the carve, which the carve
#: manifest (openxFactory `docs/opendox-carve-manifest.yaml`) took elsewhere:
#: `(test module, the marker it carried, where the module lives now)`. Their
#: survival is asserted where they live, not here. Each is asserted ABSENT from
#: this checkout, so the record cannot go stale: a module that came back would
#: have to return to `PRESERVED_SCANS` in the same act.
PRESERVED_ELSEWHERE: tuple[tuple[str, str, str], ...] = (
    ("test_doxbench_model.py", "FORBIDDEN_SOURCE_SNIPPETS",
     "openxFactory (stays_openxfactory_adapter)"),
    ("test_doxbench_model.py",
     "def test_module_source_contains_no_network_or_provider_or_schema_markers",
     "openxFactory (stays_openxfactory_adapter)"),
    ("test_doxbench_model.py", "FORBIDDEN_PORT_MEMBERS",
     "openxFactory (stays_openxfactory_adapter)"),
    ("test_doxbench_turns.py",
     "def test_module_source_contains_no_network_provider_serve_or_logging_markers",
     "openXdox-code"),
    ("test_doxbench_packet.py",
     "def test_the_packet_module_contains_no_forbidden_spelling",
     "openXdox-code"),
    ("test_doxbench_status_exemption.py",
     "def test_the_carved_module_contains_no_forbidden_spelling",
     "openxFactory (stays_openxfactory_adapter)"),
    ("test_doxbench_threads.py",
     "def test_the_thread_module_contains_no_forbidden_spelling",
     "openXdox-code"),
    ("test_doxbench_bridge.py",
     "def test_the_bridge_module_declares_no_credential_shaped_name",
     "openXdox-code"),
    ("test_doxbench_mutation_boundary.py", "_FORBIDDEN_NEEDLES",
     "openXdox-code"),
)


@pytest.mark.parametrize("module_name,marker", PRESERVED_SCANS)
def test_the_per_module_scans_this_boundary_narrows_still_exist(module_name,
                                                                marker):
    text = (Path(__file__).parent / module_name).read_text(encoding="utf-8")
    assert marker in text, f"{module_name} no longer carries {marker}"


def test_the_scans_the_carve_took_elsewhere_are_recorded_not_pinned():
    """The seven carved-away suites are a RECORD here, and the record is true.

    None of them is in this checkout. One that came back would be pinned by
    nothing while this record said it lived elsewhere, so its return has to
    move it into `PRESERVED_SCANS`."""
    here = Path(__file__).parent
    back = sorted({name for name, _marker, _home in PRESERVED_ELSEWHERE
                   if (here / name).exists()})
    assert not back, (
        f"{back} are in this checkout again: move their rows from "
        "PRESERVED_ELSEWHERE into PRESERVED_SCANS, so their scans are pinned")
    assert not {name for name, _marker in PRESERVED_SCANS} & {
        name for name, _marker, _home in PRESERVED_ELSEWHERE}


def test_doxbench_model_stays_free_of_the_provider_client():
    """The seam's own module is NOT the exempt one, and never becomes it.

    `doxbench_model.py` declares the port protocol and the pure catalog types;
    its own scan bans `urllib`, `subprocess` and every credential spelling. The
    provider client is a separate module BEHIND that seam, which is what keeps
    the protocol free of a provider verb (`FORBIDDEN_PORT_MEMBERS`)."""
    source = _source(PACKAGE / "doxbench_model.py")
    assert PROVIDER_CLIENT_MODULE.removesuffix(".py") not in source
    assert "urllib" not in source
