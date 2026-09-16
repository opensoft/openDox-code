"""The openDox RUNTIME: FastAPI + Postgres on the `xFactory-Hermes-Install`
pattern (`split-opendox-two-layer-product` § 3.5, RULING Q2), holding identity
and coordination and nothing else (RULING Q1), with the repository-creation act
and its plain-local-git adapter beside it (§ 3.6, RULING C3).

RULING Q2 (opensoft/openxFactory#656 comment 5542792997, Brett Heap,
2026-09-04T15:31Z), verbatim: "reuse the Hermes install pattern — FastAPI +
Postgres, deployed the way `xFactory-Hermes-Install` is (live on AKS since
2026-07-19), OIDC through the Keycloak broker being adopted in QA". Rejected
there: "bolting a database onto today's stdlib `serve.py` monolith".

WHAT THIS SUBPACKAGE IS NOT. It is not a second dashboard and it does not
import `opendox.serve`. `serve.py` is the stdlib document surface the carve
delivered; this package is the identity and coordination runtime the rulings
add BESIDE it, and the two are joined only by the project-to-repository map —
which is a database row, not an import. Keeping them separate is what lets the
runtime be deployed (a container, a Postgres, a broker) while the document
surface stays a thing a student runs from a checkout.

IMPORT WEIGHT IS A CONTRACT HERE, not an accident, and this file is where it is
kept. Importing `opendox.runtime`, `opendox.runtime.config`,
`opendox.runtime.migrations`, `opendox.runtime.identity`,
`opendox.runtime.cli` or `opendox.runtime.local_git_adapter` costs STDLIB ONLY
— no FastAPI, no psycopg, no PyJWT, no httpx. Three consumers depend on that:

  * `split-opendox-two-layer-product` § 3.7's neutral conformance corpus, which
    holds an adapter against `opendox.corpus_adapter.CorpusAdapter` in a
    process that installed neither a web framework nor a database driver. The
    adapter openDox offers it is `opendox.runtime.local_git_adapter`, and
    `opendox.runtime.repository_act.initialize_repository` builds a corpus to
    check without a database. Both arrive with the § 3.6 act — on THIS branch
    they are here; on the § 3.5 branch this one is stacked on
    (openDox-code#25) they are not yet, which is why
    `tests_runtime/test_runtime_surface.py` measures whichever of the declared
    modules the tree actually carries rather than assuming all of them
    (Copilot review of openDox-code#25);
  * the leg's REQUIRED `validate` check, which installs `.[test]` and not
    `.[runtime]`, so every assertion it runs has to hold without the extra;
  * a reader running `opendox runtime status` to find out why the runtime will
    not start, which must not itself fail on the missing dependency it is
    about to report.

So the modules that need the extra — `db`, `oidc`, `app` — are imported at CALL
time inside the verb or the factory that needs them, never at module import,
and `tests_runtime/test_runtime_surface.py` asserts that by parsing rather than
by trusting this paragraph.
"""

from __future__ import annotations

#: The API prefix every coordination route is mounted under. Declared here
#: rather than in `app.py` so the CLI, the deployment manifests and the tests
#: read ONE spelling: a prefix that lives in the router and in a Kubernetes
#: probe path is two spellings that drift on the day one of them moves.
API_V1 = "/api/v1"

#: The six coordination collections RULING Q1 names, in the ruling's own order,
#: as the route segments `app.py` mounts. CLOSED, and
#: `tests_runtime/test_runtime_surface.py` reads this tuple against the routes
#: the application actually declares — a seventh collection is a claim about
#: what the database owns and has to be made in the open.
COLLECTIONS: tuple[str, ...] = (
    "users",
    "memberships",
    "projects",
    "project-repositories",
    "sessions",
    "drafts",
)

__all__ = ["API_V1", "COLLECTIONS"]
