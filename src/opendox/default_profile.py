"""openDox's OWN default profile: the domain of documents and ideas.

WHY THIS FILE EXISTS. Requirement 3 of openxFactory's
`add-neutral-product-standalone-operability` (RATIFIED on `openxFactory#656`
comment `5815412869`): *"A neutral product whose entry points require a
registered domain profile SHALL ship a DEFAULT PROFILE for its own neutral
domain and SHALL start on it with no host present, while the composition point
REMAINS OPEN for any host to register a different profile."* Its task 3.1 asks
for that profile *"for openDox's OWN domain — documents and ideas — carrying
none of openxFactory's status taxonomy or change/spec/delta nouns (RULING C2,
DIRECTION Q5)"*. Before this file the only real profile anywhere was
openxFactory's composite in `scripts/opendox_host.py`, whose base class is
`openxdox.domain_profile.DomainProfile`. The one profile that existed needed
BOTH siblings installed, so openDox alone had nothing to build a parser from.

IT DOES NOT RE-OWN THE COMPOSITION POINT (the packet's `design.md` § D5). The
§ 3 carve deleted `profile_openxfactory.py` because a CORE carrying ANOTHER
domain's profile is what RULING C2 refuses. This module is the core carrying ITS
OWN domain's profile, as a default that any host replaces by registering its
own. `domain_profile` still holds the one registration. This module is one
candidate for it, a host's profile is another, and nothing here names a host.

AN EMPTY DEFAULT IS STILL REFUSED (RULED ASK-2, comment `5628886636`; design
§ D5): *"a parser whose contributed verbs are silently absent is
indistinguishable from a working one until someone types the missing
command."* So the default contributes openDox's OWN verbs (R1Q4 (a), comment
`5817152735`), and today those are the runtime's lifecycle verbs.
`RuntimeSubcommand` is the `subcommand_extension.SubcommandExtension` that
`opendox/runtime/cli.py` ships for exactly this assembly point (RULED Q-R4,
comment `5701772032`). It is in `SUBCOMMAND_EXTENSIONS` from this module's
FIRST landing (R1Q5 (a)), so no build ever meets an empty default:

* a parser built on this default carries `runtime init | migrate | serve |
  status | reset`, and plan 034's T038 gives those verbs the `opendox` console
  script;
* `opendox-runtime` stays as their alias;
* a host that registers its own profile keeps its own command tree, including
  the 31-entry `--help` tree openxFactory's golden pins, because it never meets
  this one.

Release 2's `submit`, `land` and `health` join the tuple as they land.
`submit` has (plan 038 T015; #1144 12.4a; decision N-2, refined by ADV-14), and
`land` has (plan 038 T016; #1144 12.6a): `cli_branch_actions
.BranchActionSubcommands` follows `RuntimeSubcommand` and registers both, so a
parser built on this default carries `opendox submit` and `opendox land` too,
and a host's command tree, which never meets this one, does not (R2Q3 (a)).
`ProjectSubcommand` is NOT here. R1Q5 (a) names the runtime verbs alone, so
`project create-repository` stays on the `opendox-runtime` alias until a ruling
says otherwise (plan 034, T006's finding U4). The holder's reading, recorded on
`openxFactory#656` comment `5851560764`, keeps it out under R1Q5 (a).

THE FIVE FACETS, AND WHY ONLY THREE ARE DECLARED.

* `SUBCOMMAND_EXTENSIONS` is declared, above. `cli.build_parser()` reads it
  strictly: a registered profile without it is `ProfileFacetMissing`.
* `ROUTE_EXTENSIONS` is declared, and `serve.build_server()` reads it as
  strictly as the parser reads the verbs. openDox's older routes are the core
  server's fixed dispatch. The submit route, `POST /actions/session/submit`, is
  the first that is not (plan 038 T015; 12.4a), and the two land routes, `POST
  /actions/session/land-nonce` and `POST /actions/session/land`, follow it
  (plan 038 T016; 12.6a; OQ-12-13): they are this profile's contribution,
  `serve_branch_actions.BranchActionRouteExtension`, so a host profile that
  replaces the default carries none of them, and its `/capabilities` payload
  carries no `actions.submit` or `actions.land` key (decision N-2, refined by
  ADV-14; OQ-12-14; R2Q3 (a)).
* `DISPLAY` is NOT declared, and that is how the default's vocabulary is
  `NEUTRAL_DISPLAY` unchanged (requirement 3's third scenario; R1Q4 (a)). For a
  registered profile without the facet, `display_profile.host_display()`
  answers `None`, and `display_manifest` renders `NEUTRAL_DISPLAY` word for
  word: openDox's plain words for its own shape, which this arc neither
  re-authors nor designs around. Declaring `DISPLAY = NEUTRAL_DISPLAY` would
  render the same words, and it would ALSO publish all four design tokens as
  the host's own (`declared_tokens`). `views/display.js` would then write the
  light theme's colours inline on `:root`, shadowing every dark-theme rule in
  `styles.css`. That is the failure
  `tests/test_display_facet.py::test_only_the_tokens_a_host_declared_are_written_onto_root`
  exists to forbid, so the default declares no facet and renders the neutral
  one. The holder recorded that reading on `openxFactory#656` comment
  `5851560764`.
* `VIEW_EXTENSIONS` is NOT declared. The default contributes no consumer
  panel, because openDox's own views are its core arm, and
  `view_extension.host_view_facet()` answers an empty column, named `absent`,
  for a profile without the facet.
* `HANDLER_CONTRIBUTIONS` is declared (plan 038 T015). It holds the mixin
  classes whose methods a profile's route bindings name (plan 034's T010;
  R1Q1 (a)), and `serve.build_server()` reads it by presence and composes each
  mixin after the core handler (`route_extension.compose_handler`). The
  default's one mixin is `serve_branch_actions.BranchActionRoutes`, which holds
  the methods the submit and land bindings name, and the gate they share.

HOW IT IS REGISTERED: by the entry points, and never at import (R1Q3 (a)).
`cli.build_parser()`, `serve.build_server()` and both `main()`s call
`domain_profile.register_default(default_profile)` before anything reads the
profile, and that call registers this module only where nothing is registered.
The default is a registration an entry point makes, and never a fallback inside
`domain_profile.current()`. So:

* importing this module registers nothing, and a process that builds nothing
  still meets `domain_profile.ProfileNotRegistered`, the library caller's case;
* a host that registers its own profile BEFORE anything is built replaces this
  one, whether it registered first or an entry point's `main()` had already
  registered the default;
* AFTER a parser or a server has been built from this default, a host's
  registration is refused as `AlreadyRegistered` (R1Q3 (ii); RN-1 (a),
  `openxFactory#656` comment `5850003126`).

A PROFILE IS A MODULE OR AN OBJECT (RULED ASK-2's words: "registers the real
module"). This one is a MODULE, so `domain_profile.name_of()` names it by its
dotted path, `opendox.default_profile`, in every refusal and in the
`host_profile` field that `/capabilities` publishes.

IMPORT WEIGHT. The standard library, `opendox.runtime.cli`, which
`opendox/runtime/__init__.py` holds to the standard library as a contract, and
the two branch-action modules, which import only the standard library and
`opendox.session_pr` when they load. So this module imports with no extra
installed, and it imports nothing from
`openxdox`, `ideation_dashboard`, `doc_health` or `corpus_adapter_openxfactory`.

A CREATED FILE: no row in openxFactory's `docs/opendox-carve-manifest.yaml`,
because the manifest declares what LEAVES openxFactory and never what a
destination assembles (RULED OQ-C).
"""

from __future__ import annotations

from opendox.cli_branch_actions import BranchActionSubcommands
from opendox.runtime.cli import RuntimeSubcommand
from opendox.serve_branch_actions import (
    BranchActionRouteExtension,
    BranchActionRoutes,
)

__all__ = ["HANDLER_CONTRIBUTIONS", "ROUTE_EXTENSIONS", "SUBCOMMAND_EXTENSIONS"]

#: openDox's OWN verbs, contributed through the § 2.4 subcommand seam (R1Q4 (a),
#: R1Q5 (a)): the runtime's, then `submit` (plan 038 T015; 12.4a) and `land`
#: (T016; 12.6a). Never empty: the module docstring gives the ruling that
#: forbids it.
SUBCOMMAND_EXTENSIONS: tuple = (RuntimeSubcommand(), BranchActionSubcommands())

#: openDox's OWN contributed routes: the submit route (plan 038 T015; 12.4a)
#: and the two land routes (T016; 12.6a). Every older route openDox owns is in
#: the core server's fixed dispatch.
ROUTE_EXTENSIONS: tuple = (BranchActionRouteExtension(),)

#: The mixin holding the methods the submit and land bindings name (plan 038
#: T015, T016), composed after the core handler by `serve.build_server()`.
HANDLER_CONTRIBUTIONS: tuple = (BranchActionRoutes,)
