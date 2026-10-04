"""Local backend for the ideation dashboard (plan "serve.py"; change task 3.3;
T011 + v2 local/served seam). Still a thin `http.server` shim, still loopback-
only for every write — but now the explicit LOCAL backend of the v2 seam, so it
grew its first write route. It serves:

  1. the static `web/` bundle (the renderer), with SimpleHTTPRequestHandler's
     own traversal defense over that tree;
  2. the ACTIVE generated snapshot at `/snapshot.json`, and any registered
     snapshot at `/snapshot.json?repository=<id>&ref=<ref>` — every snapshot is
     addressed through the ONE (repository, ref) registry
     (`snapshot_registry.py`, add-dashboard-repo-selector task 2.1), with `ref`
     defaulting to `main`, so a query-less request is exactly today's behaviour;
  2b. `GET /snapshot-index.json` — the snapshot INDEX composed from that
     registry (the openxFactory `ideation-dashboard-snapshot-index` locator plus
     additive serving-side freshness fields). This is the ONLY roster the
     repository selector reads; when the route is absent the renderer degrades
     to the single baked snapshot, which is what the static image does;
  3. a READ-ONLY `/source/<repo-relative-path>` pass-through returning file
     bytes from the pinned checkout (D15), and its keyed form
     `/source/<repository>@<ref>/<repo-relative-path>` which reads through THAT
     registry entry's own root (per-entry confinement, task 2.2). GET-only,
     confined to that entry's root, and rejecting every path-traversal attempt
     (`..`, encoded `..`, absolute paths, symlink escapes) with 404;
  4. `GET /capabilities` — a JSON capability probe (`{"actions": {...}}`)
     computed ONCE at startup. The static served image (nginx) never serves this
     route, so the UI probes once at load and hides every action affordance when
     the route is absent/404 or a capability is false;
  5. `POST /actions/notebook` — the "Open in NotebookLM" tile action (the first
     write route). LOOPBACK-ONLY: refused with 403 on a non-loopback bind. It
     resolves a tile's doc set and projects it into an `xf-wb-*` scratch
     notebook via the workbench NotebookAdapter, returning the notebook URL.
     Every failure is a structured JSON `{"error": <catalog code>, "message":
     <fixed string>}` drawn from `action_errors.ERROR_CATALOG` — request-
     derived data never enters a response, there is never a traceback, and
     never a hang (the adapter carries a subprocess timeout).
  6. `POST /actions/refresh` — ONE refresh affordance with TWO plane bindings
     (design D7), the binding chosen by the plane rather than by the client:
       * SERVED (a data source is declared): re-fetch the index and the active
         snapshot into the in-process derived cache and report the new
         freshness. Strictly READ-ONLY — fetching fresher derived data is a
         read, it writes nothing anywhere, and it is reachable off-loopback
         because that is the hosted refresh;
       * LOCAL (no data source, a real checkout): re-run the generator against
         the served checkout for one (repository, ref) and rewrite ONLY that
         derived snapshot artifact, through the interactivity boundary, with NO
         server restart. LOOPBACK-ONLY, and UNGATED on the `open-workbench`
         precedent — the snapshot is derived data, regeneration mutates nothing
         governed, and a gate record per regeneration would be audit noise about
         a cache (design D7 / open question 3's recommendation, stated here
         rather than inherited).
     Neither binding can trigger an image build, a rollout, or a publication:
     a serving surface dispatches recorded requests and never executes a final
     action (D1). A failed refresh leaves the previously rendered snapshot in
     place and reports inline.
  7. `POST /actions/edit` — the human select-to-edit escape hatch. It is
     available only on the loopback human console with a real checkout and
     resolved actor, requires the per-serve console token, resolves the selected
     document through the active registry entry's own source root, proves that
     the selected path is listed in that entry's snapshot, and launches the
     human's editor without modifying the document.

The `notebook` capability is TRUE only on a loopback bind with `nlm` on PATH and
a real (non-empty) checkout root — modelling the seam: the served static image
cannot hold `nlm` browser auth, so the action degrades to hidden there.

The `session` capability (007-workbench-branch-sessions T083, FR-048) is TRUE only
on a loopback bind with a real checkout and a RESOLVED HUMAN ACTOR, and the HOSTED
plane additionally refuses any request naming a non-`main` ref
(`hosted_ref_refused`, which also RECORDS the arrival path a hosted session would
one day take). Both halves are one decision: the session's remote-write identity is
the invoking engineer's own `gh` authentication (FR-034, D22), a personal
credential a hosted plane must never hold, and the port that uses it
(`_session_pull_requests`) is declared under exactly this capability.

Every snapshot/source response carries the snapshot↔checkout divergence, derived
from the snapshot's `generation.source_revision` versus the checkout's current
git HEAD (`X-Snapshot-Divergence: aligned|diverged|unknown`), so a viewer can
warn when the working tree has moved past the projected revision — plus the
active entry's freshness (`X-Snapshot-Repository`, `X-Snapshot-Ref`,
`X-Snapshot-Origin`, `X-Snapshot-Generated-At`, `X-Snapshot-Stale`), the
transport half of the freshness header the renderer displays (design D11).

Security posture: binds LOOPBACK only by default (127.0.0.1); on a loopback
plane EVERY request, whatever its route or method, is refused unless its one
`Host` names this serve's own loopback authority at the bound port, so a
DNS-rebinding page cannot read the corpus through the engineer's browser (plan
034 T103; see `host_names_this_loopback_serve`); every write route is
loopback-gated; the source route is read-only and confined PER REGISTRY ENTRY
(an entry with no declared root serves no documents at all); the actions
validate their request body and confine every path through the read-side guard
before touching the filesystem.

INVOCATION (design D12). This module is runnable BOTH as a script
(`python3 scripts/ideation_dashboard/serve.py …`, which is what the served
container image does) AND as a module (`python3 -m ideation_dashboard.serve`).
It self-inserts `scripts/` on the import path and uses ABSOLUTE
`ideation_dashboard.*` imports for its route collaborators; the old relative
`from . import …` imports 500'd every POST route under plain-script invocation,
and this change adds a POST route rather than carrying that workaround into it.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import secrets
import socket
import subprocess
import sys
import urllib.parse
from pathlib import Path


# The ROUTE EXTENSION POINT (`split-opendox-two-layer-product` § 2.4, design
# § D2). A neutral module at the top of `scripts/`, belonging to neither
# package and importing neither, for the same three reasons `output_boundary`
# and `corpus_adapter` sit there: both sides of the carve consume it, it travels
# with the carve, and it therefore imports nothing from here. Spelled as a bare
# top-level import for the same reason `boundary.py` spells `output_boundary`
# that way.
import route_extension  # noqa: E402

from opendox import action_errors  # noqa: E402
from opendox import doxbench_abstract_store  # noqa: E402
# The INSTALL-TIME model-provider declaration the two entrypoints make.
# Hoisted to module scope by add-doxbench-distilled-abstract §5: the graph is
# acyclic (`doxbench_install` -> `doxbench_bridge` -> `doxbench_mcp`/
# `doxbench_threads`/`doxbench_model`, none of which imports this module), and
# importing the declaration STARTS nothing -- the bridge is constructed lazily
# on the first resolution and its child only at the first turn that needs one.
# It used to be a function-scope import inside `serve()`, justified as "only an
# ENTRYPOINT has any business reading an install declaration"; that is a rule
# about who CALLS `model_port_factory`, which is still exactly one place, and
# a deferred import was never what enforced it.
from opendox import doxbench_install  # noqa: E402
from opendox import doxbench_knowledge  # noqa: E402
from opendox import doxbench_packet  # noqa: E402
from opendox import doxbench_telemetry  # noqa: E402
# THE PROJECTION REGISTRY, THROUGH ITS SEAM, AND openDox'S OWN DEFAULTS BESIDE
# IT. `from openxdox import snapshot_registry as registry_mod` stood here until
# BUILD slice 2b made it a late `consumer_reach` stand-in, which still refused
# the first read in a lone openDox, so a server could not be built standalone
# (plan 034, research R7). Since plan 034 T055 `registry_mod` is the proxy over
# the snapshot registry SEAM (`projection_seams.registry`): each `registry_mod.X`
# read below resolves the registry registered at that moment, openDox's own
# (`opendox.default_registry`) where no host has contributed one, and every one
# of them is unchanged.
#
# EXCEPT `build_server`'s two signature DEFAULTS (`index_name` and
# `peek_ttl_seconds`), which no proxy can defer: a default argument is
# evaluated where the `def` sits, at import time. openDox owns those two
# values (`defaults.py`), and openXdox-code's drift guard holds the literals
# together.
from opendox import defaults  # noqa: E402
from opendox import projection_seams  # noqa: E402
from opendox import column_seams  # noqa: E402
# openDox's own defaults for the two doxBench seams (plan 034 T085), which
# `build_server()` and `main()` register where no host has. Importing it
# registers nothing.
from opendox import doxbench_defaults  # noqa: E402
# § 3.4 slice S5: `build_server()` publishes the VIEW MANIFEST on
# `/capabilities`, the one line slice S3 built both ends of and left for the
# slice at which a contribution first exists to deliver.
from opendox import view_extension  # noqa: E402
# § 3.4 slice S7: and the DISPLAY FACET beside it, on the same payload and for
# the same stated reason — § 4.3 step 2, "no new route and no second fetch".
from opendox import display_profile  # noqa: E402
# THE HOME-CORPUS SEAM'S DEFAULT (4.1a; plan 034 T022) -- see
# `_default_home_factory` and `corpus_adapter.register_default_home(...)`
# below, beside `build_server()`.
# Neither module names `openxdox` or `ideation_dashboard`: `corpus_adapter` is
# stdlib-only (F4.1's own scan proves it), and `local_git_adapter` names only
# `opendox.runtime.config` and `opendox.corpus_adapter` besides the stdlib.
from opendox import corpus_adapter  # noqa: E402
from opendox.runtime import local_git_adapter  # noqa: E402
# THE CONSOLE TOKEN'S DELIVERY on a standalone plane (plan 034 T104): which
# delivery a plane uses, and the private copy an entry point writes.
from opendox import console_access  # noqa: E402
# THE GENERATOR SEAM'S DEFAULT (5.4; plan 034 T052): openDox's own snapshot
# generator, which `build_server()` and `main()` register where no host has.
# Both modules are stdlib-only and name no sibling, so this adds no reach.
from opendox import default_generator, generator_seam  # noqa: E402

registry_mod = projection_seams.registry.proxy  # noqa: E402
# THE BY-FUNCTION SPLIT (`split-opendox-two-layer-product` § 2.4, PRs 2 and 3
# of 4). The openDox column's routes live in `serve_workbench.py` (the doxBench
# workbench surface) and `serve_project.py` (projects, the notebook tile action,
# select-to-edit); openXdox's live in `serve_gate.py` (the gate console's door)
# and `serve_projection.py` (the snapshot, index and `/source` routes);
# openxFactory's OWN lane routes live in its `serve_openxfactory_lanes.py`
# (RULING DQ-1). The wire vocabulary, the body bounds and the hosted-plane
# confinement this core AND every column read live in `serve_wire.py`. No
# column imports this module — the graph is a DAG, which is the whole reason
# the vocabulary moved out rather than staying here — and the columns are
# composed back onto `DashboardHandler` as MIXINS below.
#
# THE LANE COLUMN IS NO LONGER ONE OF THEM (plan 034 T011, #1144 tasks 2.1 and
# 2.2). It lives in a package openDox can never import, so naming it as a base
# made `import opendox.serve` require openxFactory. It now arrives at BUILD
# time, through the handler-contribution facet (R1Q1 (a), openxFactory#656
# comment 5817152735). The host that contributes the lane routes declares the
# mixin as well, and `build_server` composes it into the class it binds
# (`route_extension.compose_handler`).
#
# TWO REGISTRATION MODES, and the difference is the point of PR 3. PR 2's
# columns are still FIXED CORE ARMS of `_route`/`do_POST`, exactly as they were.
# PR 3's three are CONTRIBUTED: their arms have left the fixed tables and they
# arrive as `RouteBinding`s through the extension point, assembled in
# `route_extension.collect_bindings` and dispatched BY NAME against the live handler —
# so they meet `self.loopback`, `self.capabilities` and the console test by
# construction rather than by their author's memory. One route deliberately
# straddles the two: `/snapshot.json`'s HANDLER moved to `serve_projection.py`
# with its neighbours while its ARM stayed core, because that arm tests
# `path == self.snapshot_route` — a per-server keyword `build_server` accepts,
# which a frozen `RouteBinding.pattern` cannot carry.
#
# AND ONE ROUTE HAS SINCE GONE THE OTHER WAY. § 3.4 slice S6 (RULED Q4, Brett
# Heap, 2026-09-12, openxFactory#656 comment 5642758731) returns the `/source`
# pair from CONTRIBUTED to FIXED: the read-only pass-through over the pinned
# checkout is the NEUTRAL product's own, so `SOURCE_PREFIX`,
# `BARE_SOURCE_ROUTE` and the three methods that answer them are declared below
# and `_route` branches on them again, above the contributed consult so no
# binding can take the route back. The projection column's contribution is
# `/snapshot-index.json` alone now. It is a route-ownership correction, not a
# reversal of PR 3: what a COLUMN owns is contributed, and `/source` turned out
# not to be a column's.
#
# EVERY MOVED MODULE-LEVEL NAME IS IMPORTED BACK BY NAME, so this module's
# namespace is what it always was: `serve.doxbench_error_body`,
# `serve.DOXBENCH_ERROR_CATALOG`, `serve.JSON_CTYPE`, `serve._launch_editor`,
# `serve.resolve_source_path`, `serve.hosted_index` and the rest all still
# resolve for every reader that already had them.
# That is what the `F401`s below declare: names imported to be RE-EXPORTED,
# not names this module happens not to use yet.
#
# THE LANE COLUMN'S FIVE ROUTE NAMES ARE NOT RE-EXPORTED ANY MORE (plan 034
# T011, #1144 tasks 2.1 and 2.1a). `COMMITTED_INTENTS_ROUTE`,
# `ACTIONS_REFRESH_ROUTE`, `ACTIONS_APPLY_REGISTER_EDITS_ROUTE`,
# `ACTIONS_DTN_SEED_ROUTE` and `ACTIONS_STAGING_SEED_ROUTE` are openxFactory's
# constants, and they are spelled where they live:
# `ideation_dashboard.serve_openxfactory_lanes`. No reader in this package
# needs them here. The module is not vendored either, because it imports
# openXdox itself, so a copy here would re-create the consumer reach BUILD
# slice 2b removed.
from opendox import serve_project  # noqa: E402
from opendox import serve_workbench  # noqa: E402
# `serve_gate`'s ONE re-exported name (`ACTIONS_GATE_PREFIX`) is no longer bound
# here (BUILD slice 2b). It named openXdox at import time and nothing in this
# module read it: the prefix belongs to the binding `GateRoutesExtension.routes()`
# declares, and `openxdox.serve_gate.ACTIONS_GATE_PREFIX` is where it lives.
from opendox.serve_project import (  # noqa: E402,F401
    _edit_request_fields,
    _launch_editor,
    _listed_source_paths,
    _resolved_listed_edit_entry,
)
# `serve_projection`'s six re-exported names are no longer bound by an import
# statement here (BUILD slice 2b): the statement named openXdox at import time.
# TWO of the six are still the projection column's — `SNAPSHOT_INDEX_ROUTE` is
# the pattern `ProjectionRoutesExtension.routes()` declares and travels with it,
# and `hosted_index` is the column's own verb — and both stay reachable at
# `openxdox.serve_projection`, which is where they live.
#
# THREE OF THE SIX ARE THIS MODULE'S OWN NAMES SINCE § 3.4 SLICE S6 (RULED Q4,
# Brett Heap, 2026-09-12, openxFactory#656 comment 5642758731: "`/source/` is
# openDox's, and openXdox's projection binding keeps only `/snapshot-index.json`
# and the three `/projections/*` routes"). `SOURCE_PREFIX`, `BARE_SOURCE_ROUTE`
# and `resolve_source_path` are DECLARED BELOW, because reading a file out of
# the pinned checkout is the NEUTRAL product's own read-only pass-through and is
# therefore a fixed core arm rather than a contributed binding. The last of the
# three is what `notebook_action.py`:52 imports `from .serve` and re-checks
# every resolved document with at :139 — a containment check reached through
# this module's name, and now a real definition here rather than a forwarder
# into the layer that pins this one.
#
# `hosted_ref_refused` IS DEFINED BELOW SINCE PLAN 034 T055, and the rule it
# applies has not moved. It decides that a hosted response must never NAME a
# session ref (FR-048), and its one dependency is the REGISTRY's own rule for
# "a ref a hosted plane may see", `is_publishable_ref`, which it now reads
# through the registry seam like every other `registry_mod.X`. It had to come
# here with the core `/snapshot.json` arm's handlers (see `_serve_snapshot`),
# which ask it on every response: forwarded to openXdox, a standalone server
# refused every one.
from opendox.serve_wire import (  # noqa: E402,F401
    AGENT_INVOCATION_REFUSAL,
    CONTEXT_REDUCED_REASON_MAX_LENGTH,
    HOSTED_SESSION_REFUSAL,
    DOXBENCH_ABSTRACT_CONVERSATION_KIND,
    DOXBENCH_ABSTRACT_REFUSAL_STATUS,
    DOXBENCH_ABSTRACT_REFUSED_PROSE_BYTES,
    DOXBENCH_ABSTRACT_REFUSED_SUBJECT_BYTES,
    DOXBENCH_ABSTRACT_REFUSED_SUBJECT_NOT_DISTILLABLE,
    DOXBENCH_ABSTRACT_REFUSED_SUBJECT_NOT_ELIGIBLE,
    DOXBENCH_CHAT_TURN_V2_FAILURE_KIND,
    DOXBENCH_CHAT_TURN_V2_KIND,
    DOXBENCH_CHAT_TURN_V2_SUCCESS_KIND,
    DOXBENCH_ERROR_CATALOG,
    DOXBENCH_ERR_ABSTRACT_UNAVAILABLE,
    DOXBENCH_ERR_APPROVAL_REFUSED,
    DOXBENCH_ERR_CATALOG_UNAVAILABLE,
    DOXBENCH_ERR_CONSOLE_REQUIRED,
    DOXBENCH_ERR_CONTENT_IDENTITY_MISMATCH,
    DOXBENCH_ERR_CONTEXT_PACKET_BOUND_EXCEEDED,
    DOXBENCH_ERR_CONTEXT_PACKET_INVALID,
    DOXBENCH_ERR_INTAKE_REFUSED,
    DOXBENCH_ERR_INVALID_ABSTRACT_REQUEST,
    DOXBENCH_ERR_INVALID_INTAKE_REQUEST,
    DOXBENCH_ERR_INVALID_TURN_REQUEST,
    DOXBENCH_ERR_MODEL_CAPABILITY_UNAVAILABLE,
    DOXBENCH_ERR_MODEL_FAILED,
    DOXBENCH_ERR_MODEL_TIMEOUT,
    DOXBENCH_ERR_MODEL_UNAVAILABLE,
    DOXBENCH_ERR_REQUEST_LIMIT_EXCEEDED,
    DOXBENCH_ERR_RESPONSE_INVALID,
    DOXBENCH_ERR_THREAD_CAPABILITY_UNAVAILABLE,
    DOXBENCH_ERR_TURN_ID_CONFLICT,
    DOXBENCH_ERR_TURN_IN_FLIGHT,
    DOXBENCH_ERR_TURN_SCOPE_REFUSED,
    DOXBENCH_ERR_UNRECOGNIZED_TURN_KIND,
    DOXBENCH_LIMIT_BEARING_CODES,
    DOXBENCH_MAX_REQUEST_BYTES,
    DOXBENCH_MODEL_CATALOG_KIND,
    DOXBENCH_WIRE_SCHEMA_VERSION,
    JSON_CTYPE,
    JSON_OBJECT_BODY_REQUIRED,
    NO_LIVE_SESSION_CAUSE,
    NO_RESOLVED_ACTOR_CAUSE,
    _ABSTRACT_REASON_NOT_DISTILLABLE,
    _ABSTRACT_REASON_NOT_ELIGIBLE,
    _ABSTRACT_REASON_NO_DECLARED_BASE,
    _ABSTRACT_REASON_SUBJECT_BYTES,
    _CredentialStream,
    _DOXBENCH_MSG_ABSTRACT_UNAVAILABLE,
    _DOXBENCH_MSG_APPROVAL_REFUSED,
    _DOXBENCH_MSG_CATALOG_UNAVAILABLE,
    _DOXBENCH_MSG_CONSOLE_REQUIRED,
    _DOXBENCH_MSG_CONTENT_IDENTITY_MISMATCH,
    _DOXBENCH_MSG_CONTEXT_PACKET_BOUND_EXCEEDED,
    _DOXBENCH_MSG_CONTEXT_PACKET_INVALID,
    _DOXBENCH_MSG_INTAKE_REFUSED,
    _DOXBENCH_MSG_INVALID_ABSTRACT_REQUEST,
    _DOXBENCH_MSG_INVALID_INTAKE_REQUEST,
    _DOXBENCH_MSG_INVALID_TURN_REQUEST,
    _DOXBENCH_MSG_MODEL_CAPABILITY_UNAVAILABLE,
    _DOXBENCH_MSG_MODEL_FAILED,
    _DOXBENCH_MSG_MODEL_TIMEOUT,
    _DOXBENCH_MSG_MODEL_UNAVAILABLE,
    _DOXBENCH_MSG_REQUEST_LIMIT_EXCEEDED,
    _DOXBENCH_MSG_RESPONSE_INVALID,
    _DOXBENCH_MSG_THREAD_CAPABILITY_UNAVAILABLE,
    _DOXBENCH_MSG_TURN_HAS_NO_DOCUMENT,
    _DOXBENCH_MSG_TURN_ID_CONFLICT,
    _DOXBENCH_MSG_TURN_IN_FLIGHT,
    _DOXBENCH_MSG_TURN_SCOPE_REFUSED,
    _DOXBENCH_MSG_UNRECOGNIZED_TURN_KIND,
    _MAX_BODY_BYTES,
    _MAX_REFUSED_DRAIN_BYTES,
    _UNSET_VALIDATOR_FACTORY,
    _abstract_reason_prose_bytes,
    _drain_refused_body,
    _no_dereference,
    _sidecar_text,
    _thread_absence_body,
    default_doxbench_validators,
    doxbench_abstract_conversation_key,
    doxbench_abstract_refusal_body,
    doxbench_abstract_refusal_status,
    doxbench_abstract_success_body,
    doxbench_context_packet,
    doxbench_declared_fields,
    doxbench_error_body,
    doxbench_error_status,
    doxbench_selected_model,
    doxbench_turn_failure_body,
    doxbench_turn_v2_success_body,
    fresh_ledger_events,
    mint_ledger_snapshot,
    provider_retry_fact,
)

DEFAULT_HOST = "127.0.0.1"
SNAPSHOT_ROUTE = "/snapshot.json"
# add-project-scoped-selection: the register projection the selector's project
# picker reads. The snapshot INDEX is a locator and deliberately carries no
# grouping, so the register itself — aggregation-owned, discovered upward from
# the checkout — is served read-only here. Absent register (or the static
# image, which never serves this route) -> 404 -> the picker hides and the
# selector degrades to today's ungrouped roster.
PROJECT_REGISTER_ROUTE = "/project-register.json"
# THE READ-ONLY SOURCE PASS-THROUGH (D15), a FIXED CORE ARM of this module since
# § 3.4 slice S6 — RULED Q4 (Brett Heap, 2026-09-12, openxFactory#656 comment
# 5642758731). It was `openxdox/serve_projection.py`'s contributed pair from
# § 2.4 PR 3 until then, which is what made `views/viewer.js` — the read-only
# Markdown viewer, class A, the most obviously student-usable surface in the
# bundle — address a route another column declared: the ONE § 2.2 rule 1 breach
# the boundary note's census carries (openDox-spec
# `docs/front-end-package-boundary.md` § 3.2, § 4.5 assertion 2). Under RULING
# OQ-2 a student runs openDox ALONE, so a viewer that cannot load a file without
# the consumer layer is a route-ownership defect, not a layering one.
#
# THE PAIR IS ONE ROUTE WITH TWO ANSWERS and the ORDER between them is
# load-bearing, so it is restated here rather than left to whoever reads the two
# arms next. `/source` EXACTLY — no file named — is `send_error(404, "no source
# path")`. `/source/` with an empty tail is NOT that: it reaches the prefix arm
# with `tail == ""`, resolves nothing, and answers 404 with the divergence
# headers and a zero-length body. `serve_projection.py` reproduced that split
# with an exact binding plus a prefix binding, relying on `collect_bindings`
# grouping every exact ahead of every prefix; `_route` reproduces it by putting
# the exact arm above the prefix arm, which is the same order written the way a
# fixed arm writes it.
SOURCE_PREFIX = "/source/"
#: The BARE `/source` route, with no file named.
BARE_SOURCE_ROUTE = "/source"
CAPABILITIES_ROUTE = "/capabilities"
ACTIONS_NOTEBOOK_ROUTE = "/actions/notebook"
ACTIONS_EDIT_ROUTE = "/actions/edit"
# T050/T051 (change 010-doxbench-editor-chat): the two doxBench HTTP routes.
# See the section banner above `_handle_workbench_model_catalog` for the
# judgement calls their handlers make.
WORKBENCH_MODEL_CATALOG_ROUTE = "/workbench/model-catalog"
# add-doxbench-editing-phase-b task 9.5: the THREAD read route. A console-
# internal surface, deliberately NOT a released contract envelope — no
# openxFactory schema declares a thread shape, and inventing a `schema_version`
# for one here would claim a release that was never cut. It carries the same
# unversioned local shape `/capabilities` does, and the sidecar file itself is
# the governed artifact.
WORKBENCH_THREAD_ROUTE = "/workbench/thread"
ACTIONS_WORKBENCH_CHAT_TURN_ROUTE = "/actions/workbench/chat-turn"
# add-doxbench-distilled-abstract §5 (design D1): the model-derived per-document
# distilled abstract's OWN route, deliberately NOT a scoped chat turn. The
# released turn envelope carries a bound buffer key, per-buffer observed hashes
# and a buffer-keyed proposal target that an abstract request has none of, and
# `dispatch_turn` would still demand a `{assistant_prose, proposals}` answer from
# a request that is not a conversation. The provider-boundary requirement says it
# in as many words -- a consumer whose request is not a conversation SHALL carry
# its own request shape and its own declared purpose -- so this is a second
# CONSUMER of the one model seam, never a second meaning for the chat route.
ACTIONS_WORKBENCH_DOCUMENT_ABSTRACT_ROUTE = "/actions/workbench/document-abstract"
# add-doxchat-model-intake §2/§3: the MODEL INTAKE surface and its two acts.
# Three routes and not one, because they answer three different questions and
# carry three different things.
#
#   * the SURFACE (a GET) discloses whether intake is offered at all, which
#     authentication kinds the declared broker can take, and which declarations
#     are still waiting on a human. It is what makes the selector's intake
#     affordance honest: the affordance is rendered only when this route says the
#     flow behind it can be opened AND completed;
#   * the INTAKE act (a POST) carries a CREDENTIAL, and so carries it in a way
#     nothing else on this server does — the facts ride the query string, where a
#     fact belongs, and the body is the credential and NOTHING ELSE, streamed
#     straight into the broker's standard input. See `_handle_workbench_model_intake`;
#   * the APPROVAL act (a POST) carries no credential at all: it names a
#     declaration and writes the gate-action record that makes it available.
#
# Console-internal local shapes, deliberately NOT released contract envelopes,
# exactly as `WORKBENCH_THREAD_ROUTE` is: no openxFactory schema declares an
# intake shape, and inventing a `schema_version` for one here would claim a
# release that was never cut. The governed artifacts are the ones that ARE
# released — the gate-action record the approval writes, and the settings
# documents the flow leaves behind.
WORKBENCH_MODEL_INTAKE_ROUTE = "/workbench/model-intake"
ACTIONS_WORKBENCH_MODEL_INTAKE_ROUTE = "/actions/workbench/model-intake"
ACTIONS_WORKBENCH_MODEL_APPROVAL_ROUTE = "/actions/workbench/model-approval"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
# THE TWO ROUTES THE `actions` MAP NAMES THAT A HOST CONTRIBUTES (plan 034
# T084; #1144 4.3 as T007 batch L's addendum reads, RULED openxFactory#656
# `5920216845`, item 1). Neither is a fixed core arm: a gate verb is
# `POST /actions/gate/<verb>` and the refresh is `POST /actions/refresh`, and
# each answers only where a route binding the assembly collected carries it.
# Everything else `do_POST` reaches is core. So `gate` and `refresh` are true
# only where such a binding is assembled (`compute_capabilities`), and a
# standalone server, which carries neither, reports both false rather than
# offering two affordances that would answer `404 unknown_action`.
ACTIONS_GATE_PREFIX = "/actions/gate/"
ACTIONS_REFRESH_ROUTE = "/actions/refresh"

# THE STATIC BUNDLE'S CONTENT TYPES, PINNED (plan 034 T084, the holder's
# addition for #1144 10.2, "reachable in a browser from an openDox-only
# install", from T075's finding on openDox-code#73). The static route is
# `SimpleHTTPRequestHandler`'s, whose `guess_type` reads the handler's
# `extensions_map` FIRST and the platform's `mimetypes` table only for an
# extension that map lacks. The platform table is the host's: on Linux and
# in CI it answers `text/javascript` for `.js`, but a host whose table
# differs, and Windows reads its table from the registry, can serve an ES
# module as `text/plain`, which a browser refuses to run, so the console
# opens blank. Every extension the wheel's bundle carries is pinned here
# (measured at T084: 41 files under `opendox/web/`, 39 `.js`, one `.html` and
# one `.css`), with the types the bundle's own kinds of file take beside
# them. Each value is the one the standard library's built-in table gives
# (`.woff2`, which it lacks, takes its registered type, RFC 8081), so a host
# whose table was already right serves exactly what it served before. Any
# other extension still falls back to the platform table.
STATIC_CONTENT_TYPES: dict[str, str] = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/vnd.microsoft.icon",
    ".woff2": "font/woff2",
}


def answers_a_gate_verb(binding) -> bool:
    """Whether a contributed route binding answers `POST /actions/gate/<verb>`
    for some verb: a POST prefix at or under `ACTIONS_GATE_PREFIX`, or one that
    covers it, or an exact POST naming one verb under it. The match rule is the
    binding's own (`RouteBinding.matches`), read for a family of paths."""
    if binding.method != "POST":
        return False
    pattern = binding.pattern
    if binding.is_prefix:
        return (pattern.startswith(ACTIONS_GATE_PREFIX)
                or ACTIONS_GATE_PREFIX.startswith(pattern))
    return (pattern.startswith(ACTIONS_GATE_PREFIX)
            and len(pattern) > len(ACTIONS_GATE_PREFIX))


def answers_the_refresh(binding) -> bool:
    """Whether a contributed route binding answers `POST /actions/refresh`."""
    return binding.matches("POST", ACTIONS_REFRESH_ROUTE)

_DEFAULT_CAPABILITIES = {"actions": {"notebook": False, "gate": False, "refresh": False,
                                    "session": False, "edit": False,
                                    "intent": False},
                         "actor": None, "refresh": {"binding": None, "loopback_only": True}}


# --------------------------- capability discovery (pure) ---------------------------

def compute_capabilities(*, nlm_present: bool, checkout_real: bool, loopback: bool,
                         actor: str | None = None,
                         refresh_binding: str | None = None,
                         route_bindings: tuple = ()) -> dict:
    """The startup capability verdict. The notebook action is available only on
    a loopback bind with `nlm` reachable and a real checkout — the served static
    image satisfies none of these, so the UI hides the affordance there. GATE
    actions (the local action center, add-ideation-intent-plane §3) require a
    loopback bind, a real checkout, AND a resolved human actor — the hosted
    image fails all three, so the tray/executing gate bar never renders there
    (the intent plane replaces this seam hosted-side in §4).

    REFRESH (add-dashboard-repo-selector, design D7) is ONE affordance with two
    bindings, and the capability reports WHICH binding this plane offers so the
    UI renders one button either way: `refetch` (a declared data source; a
    read, hence available off-loopback — that IS the hosted refresh) or
    `regenerate` (a real checkout; loopback-only, because it writes the derived
    snapshot). No binding means no affordance.

    SESSION (007-workbench-branch-sessions T083, FR-048) is stated SEPARATELY from
    the gate leg even though it currently shares the gate's three conditions, and
    that is deliberate on both counts:

      * the HOSTED dashboard must expose NONE of this capability, and a reader of
        `/capabilities` should not have to infer "no session" from "no gate". The
        renderer keys its session affordances on this key, so a plane that says
        `false` gets copyable CLI descriptors and no live control (FR-046).
      * the conditions are the gate's because a session write IS a gate write, and
        because the session's remote-write identity is the invoking engineer's OWN
        `gh` authentication (FR-034, D22) — a PERSONAL credential, which a hosted
        plane must never hold or borrow. Declaring the pull-request port and
        confining the hosted plane are therefore ONE decision (Phase 7 note 6).

    It is INDEPENDENT of `nlm`: a local plane with no notebook still has full
    sessions, because FR-042 already requires a session without its notebook to be
    a complete session.

    INTENT (add-ideation-intent-plane task 4.4, design D5) is the gate seam's
    OTHER binding, and it is the photographic negative of the gate leg: the
    SERVED plane emits intents, the loopback plane executes. D5 fixes the pair
    — "the LOCAL dashboard gets executing gate routes + the dispose tray FIRST
    ... and the identical tray then targets the intent API when hosted" — so
    exactly one of `gate` and `intent` is ever true, and a local session's
    `gate = local_human` verdict is unchanged by this key's existence.

    Three things it deliberately does NOT depend on, each for its own reason:

      * `hosted_actor`. That field is stamped PER REQUEST from the gateway
        header and is DISPLAY-ONLY: `add-dashboard-account-menu` Requirement 2
        says the header flips no capability verdict, and the `/capabilities`
        handler says the same in its own comment. Keying intent emission on it
        would make a display fact into an authorization input and would make
        the `actions` map differ between two requests to one server. The inbox
        is the identity authority: an unauthenticated POST gets its own 401
        there, which is a refusal the tray RENDERS rather than a capability the
        dashboard withholds.
      * `actor`. That is the LOCAL identity resolved from the checkout; a
        hosted plane has none by construction and must still emit.
      * `checkout_real`. Intent emission is a POST to another pod; it needs no
        corpus. (The committed-intent FEED does read the checkout, but a feed
        with nothing in it is an empty feed, not an absent capability.)

    So the predicate is the plane itself, and nothing else.

    A FLAG WHOSE AFFORDANCE IS A ROUTE THIS SERVER SERVES IS TRUE ONLY WHERE
    SUCH A ROUTE ANSWERS (plan 034 T084; #1144 4.3 as T007 batch L's addendum
    reads, RULED openxFactory#656 `5920216845`, item 1). `gate` and `refresh`
    govern routes a HOST contributes, `POST /actions/gate/<verb>` and
    `POST /actions/refresh`, so each is true only when `route_bindings`, the
    bindings the assembly collected, carry a route it governs
    (`answers_a_gate_verb`, `answers_the_refresh`), and otherwise its
    conditions above stand as they were. Measured at openDox-code `047bb4fa`,
    a standalone server answered both true while every such POST answered
    `404 unknown_action`, and the gate flag followed the checkout's git
    identity alone. Standalone both now read false, which also hides the
    workbench's session controls (`sessionActionsLive` reads `actions.gate`),
    and a composed host that contributes the routes reads as before.
    `notebook`, `edit` and `session` govern core routes and keep their
    conditions. `intent` governs a POST to ANOTHER plane's intent API, which
    that plane answers, so its condition, the served plane, stands. The
    `refresh` block below still names the plane's binding: it says which
    binding a contributed refresh would use, and the flag says whether one is
    offered."""
    binding = refresh_binding
    if binding == registry_mod.BINDING_REGENERATE and not (loopback and checkout_real):
        binding = None
    local_human = bool(actor and checkout_real and loopback)
    bindings = tuple(route_bindings or ())
    gate_routed = any(answers_a_gate_verb(b) for b in bindings)
    refresh_routed = any(answers_the_refresh(b) for b in bindings)
    return {
        "actions": {
            "notebook": bool(nlm_present and checkout_real and loopback),
            "gate": local_human and gate_routed,
            "refresh": bool(binding) and refresh_routed,
            "session": local_human,
            "edit": local_human,
            # THE HOSTED WRITE-REQUEST SEAM, and the only capability here that
            # is true OFF loopback. It grants no write: an intent is a REQUEST
            # the apply lane revalidates and may refuse (kernel schema: "an
            # intent is NEVER a write"), which is why it does not join the
            # account menu's WRITE_ACTIONS list either.
            "intent": not loopback,
        },
        "actor": actor if (actor and checkout_real and loopback) else None,
        "refresh": {
            "binding": binding,
            # Only the writing binding is loopback-gated; the read-only re-fetch
            # must work on the served (0.0.0.0) bind behind the ingress.
            "loopback_only": binding != registry_mod.BINDING_REFETCH,
        },
    }


def _is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS


# --------------------------- hosted-plane ref confinement (pure) ---------------------------

def hosted_ref_refused(loopback: bool, ref: str | None) -> bool:
    """Whether a request naming `ref` must be REFUSED because this is the
    hosted plane (007-workbench-branch-sessions T083, FR-048: "a hosted request
    naming a non-`main` ref MUST refuse").

    The test is the BIND, never the advertised capability: the bind is what
    makes a plane hosted. `None` or blank means `main`, so a ref-less request
    is untouched, and the LOCAL plane is untouched entirely. "A ref a hosted
    plane may see" is the REGISTERED registry's rule, `is_publishable_ref`,
    read through the registry seam (plan 034 T055), so there is still one
    definition of it per process: the one the registry serves by."""
    if loopback:
        return False
    return not registry_mod.is_publishable_ref(ref)


# --------------------------- the human console (FR-019) ---------------------------
#
# FR-019's THIRD clause — "reject and report any agent or automated invocation" —
# had no runtime realization on either public surface (PR #49 review finding 2).
# The first two clauses were enforced here before the body parse; the third was
# discharged only by in-process OBJECT TYPE (`gate_console.require_human_gate`
# refusing anything that is not a `HumanGate`), which no HTTP caller is ever
# asked about. The consequences were measured during the adjudication: a bare
# `http.client` POST tore a live session down with `200` and a gate-action record
# naming the HUMAN, and — worse — a CROSS-ORIGIN simple request from
# `https://evil.example` with `Content-Type: text/plain` did the same, so any page
# open in the engineer's browser could drive session verbs on the loopback plane.
#
# The realization is a HUMAN CONSOLE test, applied to the session verbs before the
# body is parsed, exactly where the other two clauses live:
#
#   1. a per-serve TOKEN, minted at start-up. On a HOST's plane it is published
#      ONLY on `/capabilities`: the served page reads it same-origin, and a
#      cross-origin page cannot read a same-origin JSON response at all, so the
#      drive-by class is structurally out. On a STANDALONE plane it is not on
#      `/capabilities` at all (plan 034 T104; RULED openxFactory#656
#      `5963851934`, adversarial review 2's M5): the page is opened with it in
#      the URL's FRAGMENT, through a 0600 private copy in the state directory
#      (`console_access`), so another OS user of the machine cannot simply ask
#      this loopback server for it.
#   2. a same-origin `Origin`/`Referer` when the caller sends one, so a browser
#      that CAN reach the plane cannot borrow the human's session from another
#      site.
#   3. a JSON `Content-Type`, which a CSRF "simple request" is not allowed to set.
#
# What this HONESTLY does not do, stated so no reader over-reads it: a process
# already running as the engineer, on the engineer's own machine, can `GET
# /capabilities` on a host's plane, or read the private copy on a standalone
# one, and present the token. Hardening THAT is the xForge host's
# concern (the pre-existing ruling recorded at `cli.py`'s `_human_gate` and D22),
# not this local console's. What the check removes is every caller that cannot
# demonstrate it came from the console this serve started — which is the whole of
# the reachable attack surface the review reproduced.
CONSOLE_TOKEN_HEADER = "X-XF-Console-Token"
CONSOLE_TOKEN_FIELD = "console_token"
JSON_CONTENT_TYPE_PREFIX = "application/json"


def mint_console_token() -> str:
    """A fresh, unguessable per-serve console token. New on every start, so a
    token cannot outlive the console that minted it."""
    return secrets.token_urlsafe(32)


def loopback_authorities(port: int, bound_host: str | None = None) -> frozenset[str]:
    """Normalized ``Host``/origin authorities for this loopback serve.

    `bound_host` is the address the socket is actually bound to
    (`server_address[0]`). Given one, the IPv6 literal ``[::1]`` is an
    authority only where the socket is bound to ``::1`` (plan 034 T103): a
    browser that names ``[::1]`` connects to ``::1``, which an IPv4 bind never
    answers, so on that bind no legitimate page names it. ``127.0.0.1`` and
    ``localhost`` stay authorities on every loopback bind. With no
    `bound_host` the set is every loopback spelling, as it always was."""
    hosts = (LOOPBACK_HOSTS if bound_host is None else
             frozenset(host for host in LOOPBACK_HOSTS
                       if ":" not in host or host == bound_host))
    authorities = {
        f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        for host in hosts
    }
    if port == 80:
        authorities |= {
            f"[{host}]" if ":" in host else host
            for host in hosts
        }
    return frozenset(authorities)


# --------------------------- the loopback Host gate (plan 034 T103) ---------------------------
#
# DNS REBINDING READ THE WHOLE CORPUS (adversarial review 2, 2026-10-03, M4,
# measured at openDox-code#77 `b1db1965`). A page on `evil.example` whose name
# is re-pointed at 127.0.0.1 makes the engineer's own browser send
# `GET /source/<doc>.md` with `Host: evil.example:<port>` to this loopback
# socket, and the page may read the answer, because to the browser it is
# same-origin. Only `/capabilities` (and only when a console token had been
# minted) and the console routes asked whether the `Host` named this serve, so
# `/source/*`, `/snapshot.json` and the static bundle answered 200 to any
# `Host`. And L2: with no git identity a local serve mints no token, so
# `/capabilities` skipped its own check and handed the install block (the data
# directory, the socket directory and the bundled server's pid, which name
# the OS user) to any `Host` as well.
#
# THE GATE IS ONE CHECK AT ONE PLACE, ahead of every route:
# `DashboardHandler.parse_request`, which the standard library runs on every
# request before it looks for a `do_<METHOD>` at all. So the static bundle
# (`index.html`, `app.js`, `views/*`), `/source/*`, `/snapshot.json`,
# `/capabilities` whatever the token state, every `/workbench` and
# `/actions` route, a route a host contributes, HEAD, OPTIONS and any other
# method are refused alike, and a route added tomorrow is behind it without
# its author doing anything.
#
# WHAT IT ACCEPTS: exactly one `Host` line naming one of the plane's own
# loopback authorities at the BOUND port (`loopback_authorities`, the same
# set the console's Origin test reads): `127.0.0.1:<port>`,
# `localhost:<port>` in any case, and `[::1]:<port>` only where the socket is
# bound to `::1`. Exact match after trimming the optional whitespace RFC 9110
# allows around a field value, and lower-casing, which is all `localhost`
# needs. No suffix, no prefix, no other port, no missing or empty `Host`, no
# second `Host` line (RFC 9112 § 3.2 refuses that too).
#
# WHAT IT ANSWERS: one fixed status and one fixed body, built from constants
# below, so a refusal never echoes the `Host` it refused and never says which
# test failed. 403 and `invalid_host`, the code `/capabilities` already
# answered a rebinding `Host` with, so a client that read that refusal reads
# this one. A declared request body is drained, bounded, first, as every other
# refusal here drains one, so the refusal survives its own transport.
#
# A HOSTED PLANE IS UNTOUCHED. Off loopback the bind is `0.0.0.0` behind an
# ingress, whose `Host` is the public name, and the hosted plane's rules are
# its own (`hosted_ref_refused`, the gateway's identity): `parse_request` asks
# `self.loopback` first and does nothing else when it is false.
FOREIGN_HOST_STATUS = 403
FOREIGN_HOST_ERROR = "invalid_host"
FOREIGN_HOST_MESSAGE = "the request Host does not name this loopback server"
FOREIGN_HOST_BODY = json.dumps({"ok": False, "error": FOREIGN_HOST_ERROR,
                                "message": FOREIGN_HOST_MESSAGE}).encode("utf-8")


def host_names_this_loopback_serve(host_lines, port: int,
                                   bound_host: str | None = None) -> bool:
    """Whether a request's `Host` header lines name this loopback serve.

    `host_lines` is every `Host` line the request carried, in order
    (`headers.get_all("Host")`, which is None when there is none). True only
    for exactly one line whose value, with the surrounding spaces and tabs
    trimmed and lower-cased, is one of `loopback_authorities(port,
    bound_host)`. Pure, so the table of crafted `Host`s is asserted on it
    directly as well as through a live server."""
    lines = list(host_lines or ())
    if len(lines) != 1:
        return False
    value = str(lines[0]).strip(" \t").lower()
    return value in loopback_authorities(port, bound_host)


# --------------------------- source-path containment (pure) ---------------------------

def read_unless_private(path: Path | str, private_roots) -> bytes | None:
    """The bytes of `path`, or None where the file it OPENS is a console
    token's private copy (`console_access.is_private_file`, plan 034 T104).

    Every route that reads a file for any caller, with no console check,
    reads through this (Copilot at openDox-code#84, r4178133842): `/source`
    and `/snapshot.json`. A root or a snapshot named through a link is
    resolved again on every request, and could be re-pointed at the state
    directory after the copy was published; a hard link reaches the copy by
    another name. The file actually opened is judged, so neither is served.
    With no private root (a host's plane, or a plane that wrote no copy) it
    reads as before."""
    with open(path, "rb") as stream:
        if private_roots and console_access.is_private_file(
                stream.fileno(), private_roots):
            return None
        return stream.read()


def resolve_source_path(checkout_root: Path, url_tail: str) -> Path | None:
    """Resolve a `/source/<tail>` request to an absolute file under
    `checkout_root`, or None to reject. Rejects absolute paths, NUL bytes, any
    escape of the root (via `..`, encoded `..`, or a symlink), and non-files.
    Percent-decoding happens BEFORE the containment check so `%2e%2e` cannot slip
    past.

    The containment check itself lives in the registry's `resolve_within` so
    the SAME rule applies per registry entry (task 2.2); this stays the
    single-root entry point every existing caller and test uses.

    ARRIVED HERE AT § 3.4 SLICE S6 (RULED Q4) with the route it confines, from
    `openxdox/serve_projection.py`:66. The body is unchanged: the RULE is the
    registry's `resolve_within`, it is the same rule per registry entry, and
    it is reached through the registry SEAM (plan 034 T055), as
    `serve_workbench.py` reaches it too, so a process has one rule: the
    registered registry's. What moved is the ENTRY POINT, to the module that
    now declares the route and to the module `notebook_action.py`:52 already
    imported it from. A second copy of the containment rule here would be the
    fork `route_extension.py`:89 names. This is not one."""
    return registry_mod.resolve_within(Path(checkout_root), url_tail)


def _checkout_real(checkout_root: Path | str) -> bool:
    """A real corpus checkout, not the served image's empty `/srv/empty` sentinel.

    "Real" means SCANNABLE AS A CORPUS, as the REGISTERED corpus-root predicate
    decides (`projection_seams.corpus_root`, plan 034 T055) — the same
    predicate `cli.py`'s `--repo-root` guard uses, which is the same value under a
    second spelling (runbook §2). It used to mean merely "an existing, non-empty
    directory", which is what the sentinel fails; but that let a wrong-but-populated
    path (a home directory, a workspace root, a sibling repository) satisfy the
    condition that turns the local gate/session affordances ON — and those affordances
    WRITE INTO whatever tree this names. The docstring already promised a corpus;
    this makes the code keep the promise. The empty sentinel still fails it, so the
    hosted image is unchanged.

    This runs on every `build_server`, including the served image's, so the
    predicate is structural and imports nothing heavy: openDox's own asks for
    a git repository's root, and the governed one for the roots a snapshot is
    projected from."""
    return projection_seams.corpus_root.current().corpus_scan_defect(
        checkout_root) is None


def resolve_actor(checkout_root: Path | str, override: str | None = None) -> str | None:
    """The local action center's human identity. None (no identity) keeps gate
    actions unavailable — fail-closed, never a guessed actor.

    THE `--actor` TRUST GAP, on this surface. An explicit `--actor` used to WIN
    OUTRIGHT: whatever string the flag carried became the identity every
    gate-action record this serve wrote would name, checked against nothing. The
    override is now a CLAIM that must match the authenticated principal
    (`actor_identity`) — the gateway-verified user, a launcher-supplied
    principal, an explicit allowlist, or this checkout's own git identity, which
    is also the no-override default the function has always used. An override
    that cannot be authenticated resolves to None, which is this surface's
    fail-closed spelling: the plane comes up with gate actions OFF rather than
    with a fabricated identity attached to them."""
    from opendox import actor_identity

    if override and str(override).strip():
        return actor_identity.authenticated_actor_or_none(
            override, checkout_root=checkout_root)
    return actor_identity.authenticated_actor_or_none(
        None, checkout_root=checkout_root)


def real_notebook_adapter():
    """The REAL `nlm`-backed adapter — the ONE place a serve constructs one.

    Named, and supplied by the ENTRYPOINTS rather than defaulted inside
    `build_server` (PR #49 hardening item 1). `_make_adapter` used to fall back
    here whenever no factory was injected, so `build_server(...)` with no
    `adapter_factory` — which is how 10 of the 10 test call sites build a server —
    would reach the SHARED NotebookLM account the moment a session open or a
    notebook action succeeded on that server. Nothing fired only because no such
    test existed yet; the next one written would have, silently, because every
    adapter call site degrades on failure (FR-042) and therefore passes
    identically whether `nlm` is absent, failing, or succeeding.

    So the library default is ABSENCE and the two production entrypoints —
    `serve()` (which `main()` runs) and the CLI's `generate-and-open` — declare
    this factory explicitly. A caller that declares no adapter gets a plane with
    no notebook capability, which FR-042 already defines as a complete session."""
    from opendox import workbench

    return workbench.NotebookAdapter()


def _probe_nlm(adapter_factory) -> bool:
    """Whether the DECLARED notebook adapter reports `nlm` available.

    No declared adapter is no capability: probing a real adapter a caller never
    asked for would advertise a `notebook` capability the server then could not
    honour without reaching a binary nobody declared (see
    `real_notebook_adapter`). A missing dependency or import is the same verdict."""
    if adapter_factory is None:
        return False
    try:
        return bool(adapter_factory().available())
    except Exception:  # noqa: BLE001
        # absence is a capability verdict, not an error
        return False


# --------------------------- divergence (pure) ---------------------------

def divergence(source_revision: str | None, head: str | None) -> dict[str, str | None]:
    """The snapshot↔checkout relationship. `unknown` when HEAD is undeterminable
    (e.g. no git); `aligned` when the checkout still sits on the projected
    revision; `diverged` when it has moved. Pure — unit-tested directly."""
    if not head:
        state = "unknown"
    elif source_revision and head == source_revision:
        state = "aligned"
    else:
        state = "diverged"
    return {"state": state, "source_revision": source_revision, "head": head}


class _CheckoutHead:
    """openDox's OWN reader of a checkout's HEAD (plan 034 T012, #1144 task
    4.3). It replaced a deferred reach into openxFactory's
    `doc_health.corpus.RealGit`, which a standalone openDox never had, so its
    HEAD was always unknown. The read is the one `RealGit.head_sha` made:
    `git -C <checkout> rev-parse HEAD`, bounded by the same 30 seconds. Every
    failure is `None`: no `git`, not a repository, an unborn HEAD, a timeout."""

    TIMEOUT_SECONDS = 30

    def head_sha(self, repo: Path) -> str | None:
        try:
            done = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=False,
                timeout=self.TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            return None
        head = done.stdout.strip() if done.returncode == 0 else ""
        return head or None


def _head_of(checkout_root: Path, git=None) -> str | None:
    """Current git HEAD of the checkout, or None (degrades — never blocks
    serving). `git` is the injectable reader: anything with
    `head_sha(repo)`, as the suite's `FakeGit` has."""
    try:
        return (git or _CheckoutHead()).head_sha(Path(checkout_root))
    except Exception:
        return None


# --------------------------- request handler ---------------------------

class DashboardHandler(serve_workbench.WorkbenchRoutes,
                       serve_project.ProjectRoutes,
                       # Plan 034 T084 (#1144 4.3; R1Q1 (a), openxFactory#656
                       # comment 5817152735): openXdox's gate and projection
                       # columns, `serve_gate.GateRoutes` and
                       # `serve_projection.ProjectionRoutes`, stood here, as
                       # `consumer_reach`'s late stand-ins since BUILD slice 2b
                       # and as the classes themselves before it. They are a
                       # HOST's columns, so they are composed in at build
                       # time through the handler-contribution facet, beside
                       # the route bindings that name their methods
                       # (`_handle_gate_action`, `_serve_index`). A host that
                       # contributes a binding without its column is refused
                       # at wiring, before a socket (`route_extension.
                       # resolve_handlers`). A lone openDox carries neither.
                       # Plan 034 T011 (#1144 task 2.2): openxFactory's
                       # `serve_openxfactory_lanes.LaneRoutes` stood here.
                       # It is a descendant's column in a package openDox
                       # cannot import, so it is composed in at build time,
                       # through the handler-contribution facet.
                       http.server.SimpleHTTPRequestHandler):
    """Static bundle + snapshot + read-only source pass-through. Bound
    subclasses set the class attributes below via `build_server`, and compose
    in any mixin a profile or extension declares under
    `route_extension.HANDLER_FACET`."""

    # W-5 (wave re-review): one stalled or lying client must never pin a
    # handler thread forever. `StreamRequestHandler.timeout` puts a socket
    # timeout on every read and write of the connection (setup() calls
    # settimeout), so a body that stops arriving — including mid-DRAIN of a
    # refused over-cap body, which without this blocked UNBOUNDEDLY — raises
    # OSError instead. The value bounds NETWORK SILENCE, never request
    # duration: a slow model dispatch performs no socket operation while it
    # waits, and a healthy local client is orders of magnitude faster.
    timeout = 30

    # The static bundle's types, pinned ahead of the platform's table (see
    # `STATIC_CONTENT_TYPES`). The stdlib's own compression entries stay.
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      **STATIC_CONTENT_TYPES}

    checkout_root: Path = Path(".")
    snapshot_path: Path = Path("snapshot.json")
    snapshot_route: str = SNAPSHOT_ROUTE
    source_revision: str | None = None
    head: str | None = None
    quiet: bool = True
    # The ONE (repository, ref) snapshot source: the registry every snapshot,
    # index, and refresh response is resolved through (task 2.1). None only in
    # hand-constructed handlers; `build_server` always supplies one.
    source = None
    # v2 seam: the startup capability verdict, whether the bind is loopback (the
    # write-route gate), and an injectable adapter factory (tests supply a fake).
    capabilities: dict = _DEFAULT_CAPABILITIES
    # THE SERVING PROCESS'S OWN INSTALL SHAPE (plan 034 T073; #1144 13.4a):
    # a zero-argument callable answering `/capabilities`' `install` block, or
    # None where the process that built this server resolved no install shape
    # (a library caller or a test), which publishes no block. See
    # `build_server(install_report=)`.
    install_report = None
    loopback: bool = True
    adapter_factory = None
    # The session's remote-write port supplier (T082). None means "build the real
    # `GhPullRequests` for this checkout"; a test injects its fake here.
    pull_request_factory = None
    # The doxBench `WorkbenchModelPort` supplier (T024, research R6). None means
    # NO model port at all — the honest empty-catalog/editor-only posture
    # (FR-025), not an error. The injection boundary stays DUCK-TYPED; see
    # `_workbench_model_port`.
    model_port_factory = None
    # The doxBench RELEASED-schema validator supplier (T024/T050/T051 wire
    # clause). Bound by `build_server` to `default_doxbench_validators` unless
    # a caller injects its own; None only in hand-constructed handlers, and a
    # None factory REFUSES both model routes, which is the fail-closed
    # direction (see `_doxbench_validators`).
    schema_validator_factory = None
    # The per-process doxBench turn-idempotency ledger (T050/T051). None only
    # in hand-constructed handlers; `build_server` always binds a fresh
    # `doxbench_turns.TurnStore()` here -- ONE store per served process, never
    # shared across servers (see `test_turn_store_is_bound_per_server_process`).
    turn_store = None
    # The per-process DISTILLED-ABSTRACT cache (add-doxbench-distilled-abstract
    # §5.3, clarification N1). A SEPARATE instance with SEPARATE bounds, never
    # the chat ledger above: a scope holding more documents than the bound is
    # the ordinary case for abstracts, so a shared store would evict chat
    # idempotency records under ordinary abstract churn and a chat retry that
    # should replay would re-dispatch. None only in hand-constructed handlers;
    # `build_server` always binds a fresh one.
    abstract_store = None
    # The doxBench STAGED-SET KNOWLEDGE SERVICE, declared at INSTALL time
    # (add-doxbench-editing-phase-b D11, task 10.6). None means NO knowledge
    # service, which is a declared POSTURE and not an error: the turn degrades
    # to the reduced packet with its reduction stated, the rails still run, and
    # the editors are untouched. NOTHING at runtime — no turn, no prompt, no
    # heuristic — may choose a backend, which is why this is a serve-level
    # declaration and why the route below only ever READS it.
    knowledge_declaration = None
    # The packet assembler this route reaches, bound by `build_server` to
    # `doxbench_packet.assemble_packet`. INJECTED for the same reason every
    # other collaborator on this route is (the model port, the notebook
    # adapter, the schema validators): the packet is now a collaborator, and
    # the leash it carries -- purpose, scope, expiry -- can only be exercised
    # end to end by a route that was handed one it must reject. Unlike the
    # capability seams, absence here is NOT a posture: the real assembler is
    # the default, because assembling a packet is the pipeline, not a
    # capability an install may decline.
    packet_assembler = staticmethod(doxbench_packet.assemble_packet)
    # The per-process content-free usage meter (task 10.8). None only in
    # hand-constructed handlers; one meter per served process, beside the turn
    # store and never shared across servers.
    usage_meter = None
    actor: str | None = None
    # The repository half of every session key this process serves, BOUND at
    # `build_server` to the served checkout's own repository (finding R2-11). None
    # only in hand-constructed handlers — see `_session_repository`, which is the
    # one reader and which never re-reads the mutable active entry when this is set.
    session_repository: str | None = None
    # The per-serve human-console token (FR-019's third clause). None on a plane
    # that has no session capability — and a None token REFUSES every session
    # verb, which is the fail-closed direction.
    console_token: str | None = None
    gate_index_validator = None  # test seam: injectable pinned-validator path
    gate_manifest_validator = None  # test seam: pinned workbench-manifest validator
    gate_xref_validator = None  # test seam: pinned cross-reference validator
    # The CONTRIBUTED routes this server was assembled with
    # (`split-opendox-two-layer-product` § 2.4), already flattened into one
    # consult order by `route_extension.collect_bindings`: the in-tree profile
    # (`profile_openxfactory.ROUTE_EXTENSIONS` — now host-registered — the gate console, the
    # projection routes, this repository's lane routes) plus whatever the
    # caller added. The fixed core arms below are consulted first and the
    # fallback after, so the ORDER a route is reached in is unchanged by where
    # it is registered. Bound by `build_server`; `()` in hand-constructed
    # handlers, which therefore serve the core arms alone — the same posture a
    # hand-constructed handler has always had for every seam `build_server`
    # binds (no adapter, no validators, no turn store).
    route_bindings: tuple = ()

    # keep the console quiet unless asked otherwise
    def log_message(self, fmt, *args):  # noqa: N802
        if not self.quiet:
            super().log_message(fmt, *args)

    def end_headers(self) -> None:  # noqa: N802
        # Every response is revalidated (`no-cache` = cached but checked, not
        # `no-store`): the bundle is rebuilt/redeployed in place under the
        # SAME urls (index.html/app.js/views/*), and browsers' heuristic
        # caching of those assets made a fresh deploy invisible until a hard
        # refresh. The snapshot route already fetches with cache: "no-store"
        # client-side; this closes the same gap for the static bundle.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _divergence_headers(self, entry=None) -> None:
        state = divergence(self.source_revision, self.head)["state"]
        self.send_header("X-Snapshot-Source-Revision", str(self.source_revision or ""))
        self.send_header("X-Source-Head", str(self.head or ""))
        self.send_header("X-Snapshot-Divergence", state)
        # The transport half of the freshness header (design D11): which
        # (repository, ref) this response projects, where those bytes came from,
        # and whether they are the stale fallback.
        entry = entry if entry is not None else self._active_entry()
        # never NAME a session ref on a hosted response (FR-048, finding 14):
        # every route that would SERVE one already refuses, but `/capabilities`
        # and the static bundle also carry these headers, and the ref itself is
        # the topic id of unmerged work.
        if entry is not None and hosted_ref_refused(self.loopback,
                                                    getattr(entry, "ref", None)):
            entry = None
        if entry is not None:
            self.send_header("X-Snapshot-Repository", str(entry.repository))
            self.send_header("X-Snapshot-Ref", str(entry.ref))
            self.send_header("X-Snapshot-Origin", str(entry.origin))
            self.send_header("X-Snapshot-Generated-At", str(entry.generated_at or ""))
            self.send_header("X-Snapshot-Stale", "true" if entry.stale else "false")

    def _active_entry(self):
        return self.source.registry.active if self.source is not None else None

    # ---- the branch-session seam (007-workbench-branch-sessions T025) ----
    def _session_registry(self):
        """The registry a gate route keys session liveness on (FR-008), or None.

        None for a hand-constructed handler with no source: with nowhere to record
        liveness there can be no session, and `create-document` then takes its
        pre-session path unchanged rather than half-opening one."""
        return self.source.registry if self.source is not None else None

    def _session_notebook(self):
        """The notebook adapter a session's notebook is created and retired
        through (007-workbench-branch-sessions T074; FR-036, FR-021, D16), or None.

        Declared ONLY when the `notebook` capability is TRUE — a loopback bind, a
        real checkout, and `nlm` reachable (`compute_capabilities`) — so this is the
        same confinement decision the capability itself already made: a hosted
        plane never touches `nlm`, and a session on one simply has no notebook,
        which FR-042 already requires to be a complete session. Built through
        `_make_adapter`, which returns the DECLARED adapter and never falls back
        to the real `nlm`-backed one (PR #49 hardening item 1), so a server built
        with no `adapter_factory` — every test that does not inject a fake — has
        no notebook rather than a silent reach for the shared account (FR-043). An
        adapter that cannot be constructed is absence, not an error — the same
        verdict `_probe_nlm` reaches."""
        if not self.capabilities.get("actions", {}).get("notebook"):
            return None
        try:
            return self._make_adapter()
        except Exception:  # noqa: BLE001 - absence is a capability verdict
            return None

    def _session_pull_requests(self):
        """The `PullRequestPort` `open-pr` pushes and opens the pull request
        through (007-workbench-branch-sessions T082; FR-029, FR-034, D22), or None.

        Declared ONLY when the `session` capability is TRUE — a loopback bind, a
        real checkout, and a resolved human actor — because the identity this port
        writes with is the INVOKING ENGINEER'S OWN ambient `gh` authentication. It
        accepts no token, stores no credential, and has no hosted mode: that is
        exactly why declaring it here is the SAME decision as confining the hosted
        plane (`hosted_ref_refused`, FR-048). A hosted plane never gets one, and
        with none declared `open-pr` REFUSES naming the CLI parity command rather
        than inventing an identity.

        Built through `pull_request_factory` so a test injects `FakePullRequests`
        by the ONE seam and no test can reach a real `gh` or a network (quickstart
        step 6). A port that cannot be constructed is absence, not an error — the
        same verdict `_session_notebook` reaches."""
        if not self.capabilities.get("actions", {}).get("session"):
            return None
        try:
            if self.pull_request_factory is not None:
                return self.pull_request_factory()
            from opendox.session_pr import GhPullRequests
            return GhPullRequests(Path(self.checkout_root))
        except Exception:  # noqa: BLE001 - absence is a capability verdict
            return None

    def _session_repository(self):
        """The repository half of the `(repository, session-branch)` key.

        BOUND ONCE PER PROCESS, at `build_server`, to the SERVED checkout's own
        repository — the value `_bootstrap_session_entries` registered this
        process's live sessions under (PR #49 second-review finding R2-11).

        It used to be read from `registry.active` per request, and `active` is
        precisely what the HUMAN moves: on a `--local-index` plane one legitimate
        `POST /actions/refresh` naming ANOTHER repository promotes that entry
        (`_regenerate` does that for any publishable ref, correctly), and from then
        on every session verb was keyed on it. Reproduced end to end:
        `edit-document` answered 409 `repository_mismatch` claiming "this dashboard
        serves 'repoB'" about a served checkout that IS repoA, and `propose` —
        deliberately outside `refuse_foreign_repository`, being a main-resident
        verb — proceeded over an unmerged live session, which is the exact D15 /
        FR-023 hazard.

        A session lives in ONE tree: the served checkout. Which snapshot the human
        is looking at is a view, and a view cannot re-key a session. Two
        repositories can still carry the same tile id, so the repository half is
        still mandatory (FR-037, spec C9) — it is simply not a per-request read.

        The fallbacks below are for a handler built WITHOUT `build_server` (the
        hand-constructed handlers in tests), which has no session bootstrap either:
        the source's own baked repository first, and only then the active entry."""
        if self.session_repository:
            return str(self.session_repository)
        baked = getattr(self.source, "baked_repository", None) if self.source else None
        if baked:
            return str(baked)
        entry = self._active_entry()
        return str(entry.repository) if entry is not None else None

    def _route(self, head_only: bool) -> bool:
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == self.snapshot_route:
            self._serve_snapshot(head_only)
            return True
        if path == PROJECT_REGISTER_ROUTE:
            self._serve_project_register(head_only)
            return True
        if path == CAPABILITIES_ROUTE:
            # NO HOST TEST OF ITS OWN HERE ANY MORE (plan 034 T103). One stood
            # here, run only when a console token had been minted, so a local
            # serve with no git identity handed its install block to a
            # DNS-rebinding `Host` (adversarial review 2, L2). On a loopback
            # plane `parse_request` has refused every such request before any
            # route is reached, whatever the token state; on a hosted plane
            # no token is ever minted (the `session` capability needs
            # loopback), so the old test could not fire there either.
            #
            # THE ONE REPOSITORY THIS SERVE CAN WRITE TO, reported from the
            # SAME authority a create is refused against (`_session_repository`
            # — a session lives in one tree, the served checkout), so the
            # capability and the refusal can never disagree. Resolved per
            # request rather than at startup, because the registry that answers
            # it is not populated when the capability dict is built.
            #
            # The browser used to have to GUESS this, and under a composed
            # project view it guessed the PROJECT id — not a repository at all,
            # and refused. A serve knows what it serves, so it says so.
            payload = dict(self.capabilities)
            writable = self._session_repository()
            if writable:
                payload["repository"] = str(writable)
            # THE HOSTED ACTOR (add-dashboard-account-menu), resolved PER REQUEST
            # beside `repository`, `None` when the header is absent. Read from the
            # gateway-stamped `X-Auth-Request-User` header; DISPLAY-ONLY — the
            # dox-auth gateway remains the identity authority (it strips any
            # client value before stamping its own), and the dashboard's trust in
            # this header rests entirely on the NetworkPolicy boundary that lets
            # only the gateway reach it. It feeds NO capability verdict and NO
            # route consults it to authorize: reading a stamped identity for
            # display does not make this credential-free surface a credential
            # holder or an auth authority (design D16 nuance).
            payload["hosted_actor"] = self.headers.get("X-Auth-Request-User") or None
            # THE INSTALL BLOCK (plan 034 T073; #1144 13.4a), read PER REQUEST
            # from the serving process's own settings and its own bundled
            # server, so the pid it names is the server's at the moment it is
            # asked: a child that has gone is reported as gone.
            if self.install_report is not None:
                payload["install"] = self.install_report()
            self._serve_bytes(json.dumps(payload).encode("utf-8"),
                              JSON_CTYPE, head_only)
            return True
        if path == WORKBENCH_MODEL_CATALOG_ROUTE:
            self._handle_workbench_model_catalog(head_only)
            return True
        if path == WORKBENCH_MODEL_INTAKE_ROUTE:
            self._handle_workbench_model_intake_surface(head_only)
            return True
        if path == WORKBENCH_THREAD_ROUTE:
            self._handle_workbench_thread(head_only)
            return True
        # ---- the read-only source pass-through (D15; RULED Q4, § 3.4 S6) ----
        # THE EXACT ARM SITS ABOVE THE PREFIX ARM, and that is the whole of the
        # order `serve_projection.py` got from `collect_bindings` grouping every
        # exact binding ahead of every prefix one. `/source` matches the first
        # and refuses with a message; `/source/` does not (the strings differ),
        # falls to the second, and reaches `_serve_source("")` — 404 with the
        # divergence headers and a zero-length body, never an HTML error page.
        # Written the other way round the bare route would become unreachable.
        if path == BARE_SOURCE_ROUTE:
            self._refuse_bare_source(head_only)
            return True
        if path.startswith(SOURCE_PREFIX):
            self._serve_source(path[len(SOURCE_PREFIX):], head_only)
            return True
        # ---- the CONTRIBUTED read routes (§ 2.4) ----
        # AFTER every fixed core arm and BEFORE the static fallback, which is
        # the placement that makes two things true at once: a contributed route
        # can never shadow a core one (the core arms have already returned), and
        # a path no binding claims still falls through to exactly the static
        # behaviour it falls through to today. Dispatch is BY NAME against
        # `self`, so a contributed route meets the same gating primitives — the
        # loopback verdict, the capability dict, the console-host check — that
        # every arm above meets.
        matched = route_extension.match(
            self.route_bindings, "HEAD" if head_only else "GET", path)
        if matched is not None:
            binding, remainder = matched
            handler = getattr(self, binding.handler)
            if binding.is_prefix:
                handler(remainder, head_only)
            else:
                handler(head_only)
            return True
        return False

    def send_head(self):
        """The static bundle's file, as `SimpleHTTPRequestHandler` serves it,
        except a target inside a console token's private-copy directory.

        The stdlib handler follows links inside `--web-dir`, and a governed
        host's composed web root is MADE of links out of it, so links are not
        refused wholesale. But a link into the state directory must never
        serve the token's copy (plan 034 T104; Copilot at openDox-code#84,
        r4173889294): a target whose RESOLVED path is a directory the entry
        point marked private (`console_access.publish` sets
        `private_roots` on the server), or lies inside one, is a 404, for GET
        and HEAD, files and listings alike. A server with no copy marks
        nothing, and serves exactly as before.

        A DIRECTORY REQUEST IS JUDGED BY WHAT IT SERVES (Copilot at
        openDox-code#84, r4174674625). For `/sub/` the stdlib handler serves
        the directory's first index page that exists (`index_pages`:
        `index.html`, then `index.htm`), so the index page it would pick is
        judged as well as the directory, and `web/sub/index.html` linked to a
        copy is a 404 like the link itself.

        AND BY THE IDENTITY OF THE FILE (Copilot at openDox-code#84,
        r4178133842). A path cannot tell a hard link to the copy from any
        other file, so the file the handler would serve is opened and judged
        by `(st_dev, st_ino)` first (`console_access.is_private_file`), and a
        private copy is a 404. The file the stdlib handler then opens is
        judged the same way, against a link swapped in between: its headers
        are already sent by then, so it is closed unread and its bytes are
        never written."""
        private = getattr(self.server, "private_roots", ())
        if private:
            path = Path(self.translate_path(self.path))
            judged = [path]
            if path.is_dir():
                for name in getattr(self, "index_pages", ("index.html", "index.htm")):
                    if (path / name).is_file():
                        judged.append(path / name)
                        break
            for candidate in judged:
                target = candidate.resolve()
                if (any(target == root or root in target.parents
                        for root in private)
                        or console_access.opens_a_private_file(candidate, private)):
                    self.send_error(404, "File not found")
                    return None
        stream = super().send_head()
        if private and stream is not None:
            try:
                handle = stream.fileno()
            except (AttributeError, OSError, ValueError):
                handle = None               # a directory listing, in memory
            if handle is not None and console_access.is_private_file(handle, private):
                stream.close()
                self.close_connection = True    # its promised body never comes
                return None
        return stream

    def do_GET(self):  # noqa: N802
        if not self._route(head_only=False):
            super().do_GET()

    def do_HEAD(self):  # noqa: N802
        if not self._route(head_only=True):
            super().do_HEAD()

    # ---- the snapshot: `/snapshot.json`'s core arm (plan 034 T055) ----
    # THIS CLASS'S OWN SINCE T055. The arm (`_route`'s first test) stayed core
    # at § 2.4 PR 3, because it tests `path == self.snapshot_route`, a
    # per-server keyword a frozen `RouteBinding.pattern` cannot carry, while
    # its handlers travelled to openXdox's projection column and were reached
    # through a late stand-in for it (`consumer_reach`, retired at T084). So
    # a standalone server refused every `/snapshot.json`. The four methods
    # below are that route's handlers, answering from the REGISTERED snapshot
    # source: the query key, the active snapshot's bytes, the route itself,
    # and FR-048's per-entry hosted refusal, which `_serve_source` asks too.
    # The rules they consult are the registry's, through its seam.
    def _query_key(self) -> tuple[str | None, str | None]:
        """The optional `?repository=&ref=` of a read route. No repository
        means the ACTIVE entry, which is what a query-less request asks for."""
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return ((params.get("repository") or [None])[0],
                (params.get("ref") or [None])[0])

    def _read_snapshot(self, entry=None) -> bytes | None:
        """The bytes of `entry`, the active entry a request resolved to, and
        of the configured path where it resolved none (a hand-built handler, or
        a source with nothing registered).

        It never resolves the active entry itself. `_serve_snapshot` resolves
        it ONCE and hands the same entry to the refusal, this read and the
        headers, so a refresh that changes the active entry mid-request cannot
        pass the hosted refusal with one entry and serve another's bytes
        (FR-048)."""
        if entry is not None:
            return self._entry_bytes(entry)
        try:
            return read_unless_private(
                self.snapshot_path, getattr(self.server, "private_roots", ()))
        except OSError:
            return None

    def _entry_bytes(self, entry) -> bytes | None:
        """A registered entry's snapshot bytes, read as `read_unless_private`
        reads, where this plane marked a private-copy directory and the entry
        names its file. Otherwise the entry reads itself, as before."""
        private = getattr(self.server, "private_roots", ())
        path = getattr(entry, "snapshot_path", None)
        if private and path is not None:
            try:
                return read_unless_private(path, private)
            except OSError:
                return None
        return entry.read_bytes()

    def _serve_snapshot(self, head_only: bool) -> None:
        """`/snapshot.json`: the active snapshot, or the registered
        `(repository, ref)` the query names. An unknown pair is a 404, and the
        view the client already has stays as it is.

        On the HOSTED plane a non-`main` ref refuses before anything resolves
        (FR-048), and so does a query-less request whose ACTIVE entry is at a
        session ref: the refusal follows the entry a request resolved to, not
        only the ref it named. An id the registry does not hold may be an
        aggregate the source composes, at the default ref only, and composed
        from publishable members only off loopback; openDox's own source
        composes none."""
        repository, ref = self._query_key()
        if hosted_ref_refused(self.loopback, ref):
            self._send_json(403, {"ok": False, "error": "session_unavailable",
                                  "message": HOSTED_SESSION_REFUSAL})
            return
        if repository and self.source is not None:
            entry = self.source.registry.resolve(repository, ref)
            if entry is None:
                composed = None
                if registry_mod.is_publishable_ref(ref):
                    composed = self.source.compose_view(
                        repository, publishable_only=not self.loopback)
                if composed is not None:
                    self._serve_bytes(json.dumps(composed).encode("utf-8"),
                                      JSON_CTYPE, head_only)
                    return
                self.send_error(404, "no such snapshot")
                return
            if self._hosted_entry_refused(entry):
                return
            self._serve_bytes(self._entry_bytes(entry), JSON_CTYPE, head_only,
                              entry=entry)
            return
        if repository:
            self.send_error(404, "no such snapshot")
            return
        # ONE RESOLUTION of the active entry, for the refusal, the body and
        # the headers alike (see `_read_snapshot`).
        entry = self._active_entry()
        if self._hosted_entry_refused(entry):
            return
        self._serve_bytes(self._read_snapshot(entry), JSON_CTYPE, head_only,
                          entry=entry)

    def _hosted_entry_refused(self, entry) -> bool:
        """Refuse, and answer, when the entry a request RESOLVED to is at a
        session ref and this is the hosted plane. Returns whether it answered."""
        if entry is None or not hosted_ref_refused(
                self.loopback, getattr(entry, "ref", None)):
            return False
        self._send_json(403, {"ok": False, "error": "session_unavailable",
                              "message": HOSTED_SESSION_REFUSAL})
        return True

    # ---- source pass-through ----
    # ARRIVED HERE AT § 3.4 SLICE S6 (RULED Q4, openxFactory#656 comment
    # 5642758731) from `openxdox/serve_projection.py`:295-361, byte for byte.
    # The three methods are a unit: `_serve_source` is the arm, `_keyed_source`
    # is the optional `<repository>@<ref>/` split it starts with, and
    # `_refuse_bare_source` is the bare route's one-line answer.
    #
    # THE RULES THEY CONSULT ARE THE REGISTRY'S. `hosted_ref_refused` is
    # FR-048's hosted-plane confinement, and `self.source.registry` and
    # `self._hosted_entry_refused` apply the snapshot registry's per-entry
    # rules. Q4 ruled on ROUTE OWNERSHIP — "this is a route-ownership
    # correction at § 4.3 of the packet, not a new capability" — so the arm
    # came here and its rules stayed the registry's. Since plan 034 T055 they
    # are reached through the registry SEAM, so the route answers in a lone
    # openDox, from openDox's own registry, and from a host's where one is
    # registered.
    def _keyed_source(self, tail: str):
        """Split an optional `<repository>@<ref>/` prefix off a `/source/` tail.
        The prefix is honoured ONLY when it names a REGISTERED pair, so a real
        file whose first path segment happens to contain `@` still resolves as a
        path. Returns (repository, ref, remaining tail).

        A SESSION ref CONTAINS a slash (`draft/<topic>`, `cluster/<id>`), so the
        key is not always one path segment: the split is tried at every separator,
        shortest prefix first, and the first candidate naming a REGISTERED pair
        wins. Registration remains the whole admission test — an unregistered pair
        falls through to the plain path exactly as before — so widening the split
        cannot make an unknown key addressable. Both spellings work: the browser
        percent-encodes the whole key (`repo%40draft%2Ftopic`, one segment) and the
        runbook's `curl` writes it plainly (`repo@draft/topic`, two)."""
        if self.source is None or "/" not in tail:
            return None, None, tail
        parts = tail.split("/")
        for cut in range(1, len(parts)):
            rest = "/".join(parts[cut:])
            if not rest:
                break
            parsed = registry_mod.parse_key_id(
                urllib.parse.unquote("/".join(parts[:cut])))
            if parsed is None:
                continue
            if self.source.registry.get(*parsed) is not None:
                return parsed[0], parsed[1], rest
        return None, None, tail

    def _serve_source(self, tail: str, head_only: bool) -> None:
        repository, ref, rest = self._keyed_source(tail)
        # the keyed form is the OTHER route that names a ref (FR-048): a hosted
        # plane serves no session worktree's bytes, keyed or not
        if hosted_ref_refused(self.loopback, ref):
            self._send_json(403, {"ok": False, "error": "session_unavailable",
                                  "message": HOSTED_SESSION_REFUSAL})
            return
        entry = None
        if self.source is not None:
            # ONE RESOLUTION of the entry, for the refusal, the confined path
            # and the headers alike. The UNKEYED form resolves to the ACTIVE
            # entry, which the query never named, the same ref-less hole
            # `_serve_snapshot` closes. Resolved twice, once for the path and
            # once for the refusal, a refresh that changed the active entry
            # between the two could serve one entry's file under another's
            # refusal and headers (FR-048). So the entry is resolved once.
            #
            # AND THE PATH IS CONFINED TO THAT ENTRY'S OWN ROOT, with no second
            # lookup (Copilot at openDox-code#59: r4136585695 at 687d37bf and
            # r4136863569 at 96f18c45). Asked for by the entry's pair, the
            # registry looked the pair up again, so a refresh that
            # re-registered the key in between put another root behind the
            # path. Holding the registry's lock across both lookups would ask
            # a contributed registry for a method the seam does not declare.
            # So the entry in hand is confined through this arm's one entry
            # point, `resolve_source_path`, as the no-registry path below is.
            # It applies the registry's declared per-entry containment rule
            # (`projection_seams.REGISTRY_CALLABLES`), as `serve_workbench.py`
            # does for the roots it holds. An entry with no root serves
            # nothing.
            entry = self.source.registry.resolve(repository, ref)
            if self._hosted_entry_refused(entry):
                return
            root = None if entry is None else entry.source_root
            target = (None if root is None else
                      resolve_source_path(Path(root), rest))
        else:
            target = resolve_source_path(Path(self.checkout_root), rest)
        if target is None:
            self.send_response(404)
            self._divergence_headers(entry)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            body = read_unless_private(
                target, getattr(self.server, "private_roots", ()))
        except OSError:
            self.send_error(404, "unreadable source")
            return
        if body is None:                    # a console token's private copy
            self.send_response(404)
            self._divergence_headers(entry)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        ctype = "text/markdown; charset=utf-8" if target.suffix == ".md" else "text/plain; charset=utf-8"
        self._serve_bytes(body, ctype, head_only, entry=entry)

    def _refuse_bare_source(self, head_only: bool) -> None:
        """`GET /source` with no file named — refused, exactly as before.

        `head_only` is accepted and unused for the same reason the pre-carve core
        arm ignored it: `send_error` suppresses the body on a HEAD itself.
        """
        self.send_error(404, "no source path")

    # ---- write route (v2 seam): the loopback-only "Open in NotebookLM" action ----
    # RESPONSE DISCIPLINE: every error body is {"error": <catalog code>,
    # "message": <catalog fixed string>} — request-derived data (tile ids,
    # nlm stderr) NEVER enters a response; diagnostics go to the server log.
    def do_POST(self):  # noqa: N802
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == ACTIONS_NOTEBOOK_ROUTE:
            self._handle_notebook_action()
            return
        if path == ACTIONS_EDIT_ROUTE:
            self._handle_edit_action()
            return
        if path == ACTIONS_WORKBENCH_CHAT_TURN_ROUTE:
            self._handle_workbench_chat_turn()
            return
        if path == ACTIONS_WORKBENCH_DOCUMENT_ABSTRACT_ROUTE:
            self._handle_workbench_document_abstract()
            return
        if path == ACTIONS_WORKBENCH_MODEL_INTAKE_ROUTE:
            self._handle_workbench_model_intake()
            return
        if path == ACTIONS_WORKBENCH_MODEL_APPROVAL_ROUTE:
            self._handle_workbench_model_approval()
            return
        # ---- the CONTRIBUTED write routes (§ 2.4) ----
        # The read path's clause, with the write path's two call shapes and its
        # own fallback: an action no binding claims still answers
        # ERR_UNKNOWN_ACTION exactly as it does today. Same by-name dispatch
        # against `self`, so a contributed write route reaches the loopback and
        # capability gates by construction rather than by its author's memory.
        matched = route_extension.match(self.route_bindings, "POST", path)
        if matched is not None:
            binding, remainder = matched
            handler = getattr(self, binding.handler)
            if binding.is_prefix:
                handler(remainder)
            else:
                handler()
            return
        self._send_error_code(action_errors.ERR_UNKNOWN_ACTION)

    # ---- the loopback Host gate (plan 034 T103), ahead of every route ----
    def parse_request(self) -> bool:
        """The standard library's request parse, then THE LOOPBACK HOST GATE.

        `BaseHTTPRequestHandler.handle_one_request` calls this for every
        request and dispatches to `do_<METHOD>` only when it answers True, so
        a refusal here is ahead of every route and every method, the ones a
        host contributes included (see the gate's banner beside
        `host_names_this_loopback_serve`). `DashboardHandler` is the first
        base of every bound class (`route_extension.compose_handler`), so no
        contributed mixin comes ahead of it.

        Off loopback it is the standard parse and nothing else: the hosted
        plane keeps its own rules."""
        if not super().parse_request():
            return False
        if self.loopback and not self._trusted_console_host():
            self._refuse_foreign_host()
            return False
        return True

    def _refuse_foreign_host(self) -> None:
        """The gate's ONE answer: a fixed status and body, never the `Host`.

        The declared body, if any, is drained (bounded) first, as every other
        refusal on this surface drains one: answering with bytes unread can
        reset the connection under the refusal before the client reads it. The
        connection closes after it, so nothing left on the socket is read as
        a next request. The server log gets one fixed line, so the refusal is
        reported as well as made, and that line names no request-derived
        value either."""
        try:
            declared = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > 0:
            _drain_refused_body(self.rfile, declared)
        sys.stderr.write("[loopback] refused a request whose Host does not "
                         "name this loopback server\n")
        self.close_connection = True
        self.send_response(FOREIGN_HOST_STATUS)
        self.send_header("Content-Type", JSON_CTYPE)
        self.send_header("Content-Length", str(len(FOREIGN_HOST_BODY)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(FOREIGN_HOST_BODY)

    def _bound_authorities(self) -> frozenset[str]:
        """This serve's own loopback authorities, from the BOUND socket: its
        port and its address, never anything the request said."""
        bound = self.server.server_address
        return loopback_authorities(int(bound[1]), str(bound[0]))

    # ---- the human-console test (FR-019's third clause) ----
    def _trusted_console_host(self) -> bool:
        """Whether the request's ONE ``Host`` line names this server's bound
        loopback port (`host_names_this_loopback_serve`). The gate in
        `parse_request` asks it of every request on a loopback plane, and the
        console test asks it again, so the console's answer never depends on
        the gate having run (a hand-built handler)."""
        bound = self.server.server_address
        return host_names_this_loopback_serve(
            self.headers.get_all("Host"), int(bound[1]), str(bound[0]))

    def _own_origin_authorities(self) -> set[str]:
        """The `host:port` spellings a request from THIS serve's own page can
        legitimately name. Derived from the bound socket, never from the
        request's untrusted ``Host``, so DNS rebinding cannot define its own
        origin."""
        return set(self._bound_authorities())

    def _foreign_origin(self) -> bool:
        """Whether the caller declares an origin that is not this serve's own.
        A caller that declares NONE (a plain `curl`) is not exonerated here — the
        token check below is what refuses it; this closes the browser class."""
        for header in ("Origin", "Referer"):
            raw = str(self.headers.get(header) or "").strip()
            if not raw or raw == "null":
                continue
            parts = urllib.parse.urlsplit(raw)
            if (parts.netloc
                    and parts.netloc.lower() not in self._own_origin_authorities()):
                return True
        return False

    def _not_the_human_console(self) -> str | None:
        """Why this request is not the human console, or None when it is.

        The reason is for the SERVER LOG (FR-019 says reject AND report); the wire
        gets one fixed sentence, keeping this module's response discipline —
        request-derived data never reaches a response body."""
        expected = self.console_token
        if not expected:
            return "this plane minted no console token (no session capability)"
        if not self._trusted_console_host():
            return "the request Host does not name this loopback console"
        ctype = str(self.headers.get("Content-Type") or "")
        # T098 finding fix (operator ruling (a), spec Clarifications
        # 2026-07-31): the clause exists to prove the request is NOT a
        # cross-origin "simple request". A JSON Content-Type proves it — and
        # so does the PRESENCE of the custom console-token header, which
        # forces a CORS preflight on every browser. Presence satisfies only
        # THIS clause; the token's VALIDITY (compare_digest below), Host
        # trust, and foreign-origin checks refuse independently, unchanged.
        token_bearing = bool(str(self.headers.get(CONSOLE_TOKEN_HEADER) or ""))
        if not token_bearing and not ctype.split(";", 1)[0].strip().lower().startswith(
                JSON_CONTENT_TYPE_PREFIX):
            return "the request is not a JSON submission (a cross-origin simple request cannot be)"
        if self._foreign_origin():
            return "the request declares a foreign origin"
        presented = str(self.headers.get(CONSOLE_TOKEN_HEADER) or "")
        if not presented:
            return "no console token was presented"
        if not presented.isascii():
            # compare_digest raises on non-ASCII str (headers decode as
            # latin-1) — refuse fixed instead of dropping the connection.
            return "the console token is not a valid token"
        if not secrets.compare_digest(presented, expected):
            return "the console token does not match this serve's"
        return None

    def _send_json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_CTYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_code(self, code: str) -> None:
        """One structured refusal: status + body both come from the fixed error
        catalog, so no request-derived value can reach the response."""
        status, _message = action_errors.ERROR_CATALOG[code]
        self._send_json(status, action_errors.error_body(code))

    def _read_json_body(self):
        """Parse a capped JSON request body, or None on any malformation. Never
        trusts Content-Length beyond the cap — a tile-action body is tiny."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return None
        if length <= 0:
            return None
        if length > _MAX_BODY_BYTES:
            # DRAIN the refused body before answering (T104 F5/F8 — the
            # carried "65kb test" flake, closed at its root). Refusing with
            # every byte unread closed the socket on a client still mid-body,
            # and the kernel's reset could destroy the queued 400 before the
            # client read it — the refusal raced its own transport.
            _drain_refused_body(self.rfile, length)
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (OSError, ValueError):  # UnicodeDecodeError is a ValueError
            return None


    def _read_bounded_json_body(self, max_bytes: int, dimension: str):
        """Route-specific bounded JSON body reader (T024, research R7).

        UNLIKE `_read_json_body` above — which stays EXACTLY as it is, at the
        existing 65,536-byte global cap, for every route that already exists
        — this reader is PARAMETERISED per call site. The doxBench chat-turn
        route passes its own `max_bytes` and a fixed `dimension` name for the
        measured-limit verdict FR-017 requires.

        Returns `(payload, refusal)`:
          * success -> `(<dict>, None)`;
          * OVER the bound -> `(None, {"dimension": dimension, "measured": N,
            "maximum": max_bytes})` — a quantified verdict (FR-017), unlike
            this class's OTHER reader, whose bare `None` is exactly what
            research R7 says a global cap loses. `N` here is the DECLARED
            Content-Length (the refusal's actual basis — see the over-bound
            branch), not a count of buffered bytes;
          * any OTHER malformation (missing/unparseable `Content-Length`, a
            short read, invalid UTF-8, non-JSON, or JSON that is not an
            object) -> `(None, None)` — no measurement to report, and NOTHING
            request-derived (no body text, no header value) is ever returned
            in either element.

        Measurement is EXACT BYTES, never decoded characters (research R4's
        exact-byte discipline applies to request bounds too: a multi-byte
        UTF-8 body can be over the byte bound while under a code-point count,
        and the reverse must never be mistaken for a refusal). A lying
        `Content-Length` is never trusted for the READ itself: at most
        `max_bytes + 1` bytes are ever pulled off the socket, however large a
        declared length claims, so a flood cannot buffer past the bound
        merely by declaring a bigger number."""
        try:
            declared = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return None, None
        if declared <= 0:
            return None, None
        if declared > max_bytes:
            # Drain the refused body (W-6: this reader used to pull only
            # max_bytes + 1 and abandon the remainder on the socket, so the
            # measured 413 could still be destroyed by the close-with-unread
            # reset — the same race the tiny reader's drain closes). Same
            # shared posture: chunked, bounded, and backed by the socket
            # timeout so a stalled sender raises instead of holding the
            # thread.
            #
            # Wave re-review P3 honesty note: the `measured` value below is
            # the DECLARED Content-Length, not a count of bytes read — an
            # over-cap body is refused on its declaration precisely so it is
            # never buffered to be counted. That is the honest basis of this
            # refusal: the caller declared more than the bound admits.
            _drain_refused_body(self.rfile, declared)
            return None, {"dimension": dimension, "measured": declared,
                          "maximum": max_bytes}
        try:
            raw = self.rfile.read(declared)
        except OSError:
            return None, None
        if len(raw) != declared:
            return None, None  # a short read: fewer bytes arrived than declared
        try:
            text = raw.decode("utf-8")
        except ValueError:  # UnicodeDecodeError is a ValueError
            return None, None
        try:
            payload = json.loads(text)
        except ValueError:
            return None, None
        if not isinstance(payload, dict):
            return None, None
        return payload, None

    def _make_adapter(self):
        """The notebook adapter this server was BUILT with, or None.

        There is no fallback to the real `nlm`-backed adapter here (PR #49
        hardening item 1): a server is handed its adapter by whoever built it, so
        an undeclared adapter is absence rather than an implicit reach for the
        shared NotebookLM account. `_probe_nlm` keeps the `notebook` capability in
        step with exactly this decision, so a route that checks the capability
        first can never arrive here holding None."""
        if self.adapter_factory is None:
            return None
        return self.adapter_factory()

    def _serve_bytes(self, body: bytes | None, ctype: str, head_only: bool,
                     entry=None) -> None:
        if body is None:
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._divergence_headers(entry)
        self.end_headers()
        if not head_only:
            # Serving file bytes IS this route's function (S5131 justification):
            # the snapshot path is server config (never request data) and every
            # /source path is root-confined by resolve_source_path before it is
            # read — a read-only pass-through, exactly like the stdlib static
            # handler this class extends.
            self.wfile.write(body)  # NOSONAR


# --------------------------- server construction ---------------------------

def served_repository(source) -> str | None:
    """The repository half of THIS PROCESS's session keys (finding R2-11).

    The SERVED CHECKOUT's own identity, not the view's: the baked/local snapshot's
    repository — which `SnapshotSource` reads out of the snapshot file itself when
    no `--repository` is given — because that is the snapshot generated FROM the
    served tree, and the served tree is the only tree a session can live in. The
    active entry is consulted ONLY when there is no baked snapshot at all, and even
    then it is read once, here, rather than per request.

    Public because it is a decision, not a detail: `_bootstrap_session_entries`
    registers the live sessions under this value and every gate dispatch is keyed
    on the same one, so the two cannot drift."""
    baked = getattr(source, "baked_repository", None)
    if baked:
        return str(baked)
    active = getattr(getattr(source, "registry", None), "active", None)
    return str(active.repository) if active is not None else None


def _bootstrap_session_entries(source, checkout_root: Path,
                               repository: str | None = None) -> None:
    """Re-derive THIS PROCESS's live branch-session entries at start-up
    (007-workbench-branch-sessions T033a; FR-008, D10, G13).

    `SnapshotRegistry._entries` is an in-process dict, so a fresh serve starts with
    no session entries at all: without this, a restart mid-session would 404 the
    session ref, the next gate write would open a SECOND session on the same tile,
    the resume-or-new prompt would re-fire, and `propose` would proceed over
    unmerged drafts — the exact D15 hazard. The re-derivation reads the worktree and
    its branch JOINTLY under the sessions container, which D10 already names as the
    session's derivation source, and each half-signal is reported stale for the
    human rather than adopted or cleaned up.

    `repository` is the SERVED checkout's own (`served_repository`) and is the same
    value every gate dispatch is keyed on (finding R2-11); it defaults to that
    resolution rather than to the active entry, which the human moves.

    Never fatal. A served tree with no git, no sessions container, or no resolvable
    repository simply has no sessions, and the dashboard comes up exactly as it did
    before sessions existed."""
    repository = repository or served_repository(source)
    if not repository:
        return
    from opendox import branch_session as session_mod
    report = session_mod.bootstrap_sessions(
        source.registry, repository=repository,
        checkout_root=Path(checkout_root))
    for note in report.stale:
        sys.stderr.write(f"[sessions] stale ({note.kind}): {note.reason}\n")
    for message in report.errors:
        sys.stderr.write(f"[sessions] {message}\n")


def _read_source_revision(snapshot_path: Path) -> str | None:
    try:
        data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        return data.get("generation", {}).get("source_revision")
    except (OSError, ValueError, AttributeError):
        return None


def _default_home_factory(root):
    """`home_corpus`'s shape (`adapter, ref = factory(root)`), over
    `WorkingTreeCorpus` at its own defaults, whose `required_fields` is the
    small neutral field set R1Q13 (a) decides (`NEUTRAL_FIELDS`, `title` and
    `summary`, since plan 034 T054). Its `__init__` takes no root -- it is
    root-agnostic, and `resolve(ref)` reads `ref.location` -- so one
    `CorpusRef` per call carries the root this factory was given, and the
    adapter itself needs none.

    READS THE WORKING TREE, uncommitted edits included -- RULING, Brett Heap,
    2026-09-27, via the holder: "Working tree (Recommended)". A standalone
    user edits files in their own editor, and openxFactory's hosted adapter
    already shows worktree bytes, so the standalone default matches it rather
    than reading the session's git HEAD. `WorkingTreeCorpus`
    (`local_git_adapter.py`) is `LocalGitCorpus` with `list_documents`/`read`
    aimed at the filesystem instead of a resolved commit, and with openDox's
    own settings documents (`doxbench_intake.SETTINGS_DOCUMENTS`, plan 034
    T082) left out of its listing and out of a whole-corpus `check`; see its
    own docstring for what stays unchanged (`resolve`, `classify`,
    `write_back`, and a `check` of named subjects) and what does not.

    A FRESH ADAPTER EVERY CALL, ON PURPOSE: nothing here is held onto across
    calls, so there is no listing cache keyed on whatever HEAD was at an
    earlier call -- each call gets an instance that reads the CURRENT
    filesystem state, and `WorkingTreeCorpus` itself caches nothing further
    within a call either (its own docstring says so).

    Kept byte-for-byte identical to `cli.py`'s copy of the same function (one
    home corpus, one default, read by two entry points): neither module may
    import the other, and `corpus_adapter.py` cannot hold this one without
    importing `local_git_adapter` and creating the cycle that module already
    imports `corpus_adapter` the other way (4.1a, T022)."""
    return (local_git_adapter.WorkingTreeCorpus(),
            corpus_adapter.CorpusRef(name="home", location=str(root)))


def build_server(
    web_dir: Path | str,
    snapshot_path: Path | str,
    checkout_root: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = 0,
    head: str | None = None,
    snapshot_route: str = SNAPSHOT_ROUTE,
    git=None,
    quiet: bool = True,
    adapter_factory=None,
    pull_request_factory=None,
    model_port_factory=None,
    schema_validator_factory=_UNSET_VALIDATOR_FACTORY,
    actor: str | None = None,
    gate_index_validator=None,
    gate_manifest_validator=None,
    gate_xref_validator=None,
    repository: str | None = None,
    ref: str | None = None,
    data_source=None,
    index_name: str = defaults.DEFAULT_INDEX_NAME,
    source_roots: dict | None = None,
    local_index: Path | str | None = None,
    project_register: Path | str | None = None,
    peek_ttl_seconds: float = defaults.PEEK_TTL_SECONDS,
    snapshot_source=None,
    knowledge_declaration=None,
    packet_assembler=None,
    route_extensions: tuple = (),
    install_report=None,
) -> http.server.ThreadingHTTPServer:
    """Build (but do not start) the loopback server. `port=0` binds an ephemeral
    port (read it back from `httpd.server_address`). `head` is injectable so a
    divergence can be exercised without a git checkout. `adapter_factory` is the
    `NotebookAdapter` supplier and it is REQUIRED for a plane to have notebooks
    at all: unset means NO adapter, not "build the real one" (PR #49 hardening
    item 1 — see `real_notebook_adapter`, which the entrypoints declare). It also
    drives the startup `notebook` capability verdict, keeping capability and
    behaviour consistent. `pull_request_factory` is the same kind of seam for the
    session's
    `PullRequestPort` (T082): unset builds the real `GhPullRequests` for this
    checkout, which writes with the invoking engineer's own `gh` auth (FR-034,
    D22), and every test injects `FakePullRequests` through it so no test can
    reach a network. `model_port_factory` is the SAME kind of seam for the
    doxBench `WorkbenchModelPort` (T024, research R6): unset means NO model
    port at all — the honest empty-catalog/editor-only posture (FR-025), not
    an error — and it is gated on the reused `session` local-human verdict
    (see `_workbench_model_port`). The current catalog-only port is consumed
    by the catalog route; the turn route still stops before provider dispatch.

    The (repository, ref) SOURCE is built here and bootstrapped once: a declared
    `data_source` (the served plane) is tried first, then a `local_index` (the
    multi-repository local plane), and the `snapshot_path` argument always
    remains available as the baked/local fallback — so a server built exactly as
    every existing caller builds one serves exactly one `(repository, main)`
    entry and behaves as it always has. `snapshot_source` is injectable for
    tests.

    `knowledge_declaration` is the INSTALL-TIME declaration of the doxBench
    staged-set knowledge service's retrieval backend
    (add-doxbench-editing-phase-b D11): unset means NO knowledge service, which
    is the declared reduced-packet posture rather than an error, and the
    production entrypoint declares `SELF_HOSTED_LOCAL_EMBEDDED` explicitly —
    the same discipline `real_notebook_adapter` carries, and for the same
    reason: an operator must be able to read what their install talks to, and a
    library default that quietly built one would defeat that.

    `install_report` is THE SERVING PROCESS'S OWN INSTALL SHAPE (plan 034
    T073; #1144 13.4a; RULED R1Q16 (i), `5850003126`): a zero-argument callable
    answering `/capabilities`' `install` block, `{"mode": ...,
    "database_bundle": ...}`, asked on each request. The ENTRY POINT supplies
    it, from the settings it loaded and the bundled server it started as its
    own child (`cli._install_report`), so the block describes the process a
    user reached and not a second process that read the same settings.
    Unset, the payload carries no `install` block: nothing in this process
    resolved an install shape, and none is invented. This module reads no
    runtime setting itself (research R9: the document surface never imports
    the runtime).

    `route_extensions` is the ROUTE EXTENSION POINT
    (`split-opendox-two-layer-product` § 2.4, design § D2): the tuple of
    `route_extension.RouteExtension`s this server is ASSEMBLED with, each
    contributing routes the fixed core dispatch does not carry. `routes()` is
    called ONCE, here, and the flattened bindings are bound to the handler
    class; the extensions themselves are deliberately NOT retained, because an
    extension reachable from a request is an invitation to re-ask it per
    request, and a dispatch table that can change under traffic is not a
    dispatch table.

    THE HOST-REGISTERED PROFILE (`profile_openxfactory.ROUTE_EXTENSIONS`) is registered
    HERE, ahead of the caller's tuple, and is NOT passed in by `main()` — the
    same shape `build_parser` uses for `SUBCOMMAND_EXTENSIONS` (PR 4 of § 2.4).
    `build_server(...)` names the whole of THIS assembly's server, which is what
    all 31 in-tree test `build_server(...)` call sites across 27 test files
    already read it as, so the routes PR 3 moved out of the fixed tables are
    served by a caller who passes nothing — and by a
    caller who passes `route_extensions=()` explicitly, which is the same
    request spelled twice. `route_extensions` stays the seam for whatever a
    caller adds ON TOP; the default `()` therefore still means "add nothing".
    A SENTINEL (`None` -> profile, `()` -> none) was considered and refused: the
    only in-tree caller that passes the keyword at all passes `()` and would
    have silently lost `/snapshot-index.json`, `/source/` and every gate verb
    from the servers in the file that tests this very seam. This line is also
    the one the § 3 carve deletes rather than moves."""
    # FIRST, before anything else this function does (4.1a, T022, R1Q3 (a)
    # -- "the default profile and the default adapter are both entry-point
    # registrations"): a bare process that only builds a server still needs
    # the home corpus to resolve for `create`/`edit` (`authoring.py`), and a
    # host that DID register its own adapter must see it left alone. This
    # registration has no downstream read of its own inside THIS function --
    # unlike the profile's, read further below beside `profile_proxy`, where
    # a wiring input read once per build belongs beside the composition it
    # feeds -- so it stays here, as early as possible, on the same footing
    # T016 gives its own call in `cli.build_parser()`. `register_default_home`
    # registers ONLY where nothing already answers `corpus_adapter.home()`,
    # exactly as `domain_profile.register_default()` does for the profile.
    corpus_adapter.register_default_home(_default_home_factory)
    # AND openDox's OWN snapshot generator (5.4, T052; R1Q10 (a), in the same
    # R1Q3 (a) pattern), registered only where no host has contributed one.
    generator_seam.register_default(default_generator.GENERATOR)
    # AND openDox's OWN snapshot registry and source, corpus-root predicate,
    # writer and validators (5.5, T055; the same ruling and pattern), each only
    # where no host has registered its own. The snapshot source below is built
    # from the registered registry, which is what lets a server be BUILT with
    # nothing else installed (plan 034, research R7).
    projection_seams.register_defaults()
    # AND openDox's OWN doxBench validators and status-exemption rail (4.3,
    # T085; R1Q10 (a) and R1Q12 (a), the same pattern), each only where no host
    # has registered its own. So the served model catalog answers standalone,
    # validated by openDox's own validator over its packaged copies.
    doxbench_defaults.register_defaults()
    # AND the consumer columns' defaults (plan 034 T084; #1144 4.3,
    # R1Q10 (a)): the gate primitives, the doxBench scope, kickoff and
    # the cross-reference register, the same way.
    column_seams.register_defaults()

    from opendox import doxbench_turns
    # Imported HERE rather than at module scope, for the reason that is
    # actually true on this branch — narrower than the one this comment gave
    # before (Copilot review `PRRT_kwDOTAvnrs6f_iG1`): the profile is a WIRING
    # input, read once per build and never per request, so it belongs beside
    # the composition it feeds rather than in this module's import header.
    # What it is NOT doing is keeping the contributed columns out of the import
    # graph: `serve.py` already imports all three at module scope above,
    # because they are `DashboardHandler`'s mixin bases, and the profile
    # imports exactly those three. The dependency that must stay out of a
    # module the container runs as a plain script is the CLI column —
    # `cli_gate` reaches `authoring` -> `workbench` -> PyYAML, which the hosted
    # image deliberately does not carry — and that one is held out at the
    # profile's own end, which resolves `SUBCOMMAND_EXTENSIONS` (and
    # `cli_gate`) on ACCESS through PEP 562 rather than binding them at import
    # time, so only `cli.py`'s read of them pays. `cli.py` names the same
    # profile at module scope because a parser is built from it at import time;
    # a server is not.
    #
    # § 4.3, THE ROUTES HALF — RULED ASK-6 -> 1 (openxFactory#656 comment
    # 5635150678): "the routes half of § 4.3 — serve.py reads the proxy too;
    # after 2b lands and openDox-code #11 is rebased onto main, the same
    # author adds the server-side binding in the same PR (one mechanism, one
    # registration, under ASK-2)". The name is back AT ITS OWN SITE: the carve
    # deleted `from ideation_dashboard import profile_openxfactory` from this
    # line (the declared `:1371`), and what replaces it is not another in-tree
    # module but the LAZY PROXY over the host's registration.
    #
    # THE DEFERRAL NO LONGER KEEPS ANYTHING OUT OF THE IMPORT GRAPH, and the
    # paragraph above is the only reason left for it: `opendox.profile_proxy`
    # resolves NOTHING when imported — it touches no registry and cannot fail
    # for want of a host — so this line would cost nothing in the module
    # header. It sits here because the read it feeds is the NEXT STATEMENT in
    # this body, and a wiring input read once per build belongs beside the
    # composition it feeds. `tests/test_profile_registration.py` holds the
    # import to this body rather than to the module, so the posture is
    # asserted and not merely intended.
    from opendox.profile_proxy import profile_openxfactory
    # THE ENTRY POINT'S DEFAULT (R1Q3 (a), openxFactory#656 comment
    # 5817152735), a wiring input like the proxy, so it is imported beside it:
    # where no host has registered a profile, register openDox's own, so the
    # `ROUTE_EXTENSIONS` read below builds on it instead of refusing.
    from opendox import default_profile, domain_profile
    domain_profile.register_default(default_profile)

    # FIRST, before a socket, a checkout read or a session bootstrap: a
    # malformed, duplicated, overlapping or non-conforming binding refuses the
    # BUILD, and it costs nothing to find out before the expensive work starts.
    # The profile's own bindings go through the SAME collection — a collision
    # between a contributed route and one of this assembly's own is refused
    # here too, INCLUDING a caller's exact binding declared under one of this
    # assembly's prefixes (RULING A, 2026-09-07; `collect_bindings`).
    # THE IN-TREE PROFILE IS GONE AND THE CONTRIBUTION IS BACK — two different
    # facts, from two different acts. At the carve commit this read
    # `tuple(profile_openxfactory.ROUTE_EXTENSIONS) + tuple(route_extensions)`,
    # naming a module openxFactory's carve manifest files as `not_moved /
    # deleted_at_carve`: "the one file the § 3 carve deletes rather than moves
    # -- after the carve openXdox declares its own profile and openDox's core
    # has no line naming any". The deferred import that fed the reach WAS
    # deleted with the carve (the declared `:1371`) and the reach itself was
    # left behind, so `build_server()` raised `NameError: profile_openxfactory`
    # for every caller. BUILD slice 2b cut the reach out rather than repairing
    # it, because repairing it needed a ruling it did not yet have.
    #
    # It has one now (RULED ASK-6 -> 1). THE ORDER AND THE SHAPE ARE THE
    # CARVE'S, unchanged — the host's routes ahead of the caller's tuple, and
    # `route_extensions` still the seam for whatever a caller adds ON TOP. Only
    # the SOURCE of the name is different: an in-tree module became a host
    # registration resolved at first access.
    #
    # A SERVER BUILT WITH NO HOST REGISTERED BUILDS ON openDox's OWN DEFAULT,
    # which the entry-point registration above put in place (R1Q3 (a)), exactly
    # as `build_parser()` does before its own read of `SUBCOMMAND_EXTENSIONS`.
    # It is never an EMPTY profile, which ASK-2's "REFUSAL, NOT A DEFAULT"
    # still refuses ("a server missing its contributed routes looks exactly
    # like a working one"): the default contributes openDox's own verbs. This
    # read is the build, so from here a host's `register()` over the default is
    # refused rather than applied (R1Q3 (ii); RN-1 (a), comment 5850003126),
    # which is why `domain_profile.current()`'s message tells a host to
    # register "before it calls `cli.build_parser()` or `serve.build_server()`".
    #
    # THE DOCSTRING ABOVE STILL DESCRIBES THE IN-TREE PROFILE and is NOT
    # corrected here: its lines are not ones openxFactory's carve manifest
    # declares for this row, and an edit outside the declared lines is an
    # UNDECLARED MOVEMENT that the arrival verifier refuses (RULED OQ-1) —
    # RULED ASK-7 -> 1 leaves those four stale lines standing until the next
    # declared-edit window. This comment is the correction until then.
    #
    # ONE STATEMENT, and it names the extensions it collects (`contributed`),
    # because the handler-contribution facet below reads them again.
    # `tests/test_profile_registration.py` lifts every statement of this body
    # that reads `ROUTE_EXTENSIONS` off the proxy and EXECUTES it against a
    # stand-in seam that carries `collect_bindings` alone. A read split from its
    # collection would leave that test executing a read that collects nothing,
    # and a second read would hand the stand-in a call it does not have.
    route_bindings = route_extension.collect_bindings(
        contributed := tuple(profile_openxfactory.ROUTE_EXTENSIONS)
        + tuple(route_extensions))
    # THE HANDLER-CONTRIBUTION FACET (R1Q1 (a), openxFactory#656 comment
    # 5817152735): the mixins holding the methods those bindings name, read
    # off the host profile and off every extension collected above. They are
    # checked against the core handler HERE, beside the bindings and for the
    # same reason: a contribution that would shadow the core, or clash with
    # another, refuses the build before any expensive work starts. They are
    # composed into the bound class below, ahead of `resolve_handlers`.
    handler_contributions = route_extension.collect_handler_contributions(
        (profile_openxfactory, *contributed), base=DashboardHandler)

    web_dir = Path(web_dir).resolve()
    snapshot_path = Path(snapshot_path).resolve()
    checkout_root = Path(checkout_root).resolve()
    if head is None:
        head = _head_of(checkout_root, git)

    source = snapshot_source or registry_mod.SnapshotSource(
        baked_snapshot=snapshot_path,
        repository=repository,
        ref=ref,
        checkout_root=checkout_root,
        data_source=data_source,
        index_name=index_name,
        source_roots=source_roots,
        local_index=local_index,
        project_register=project_register,
        peek_ttl_seconds=peek_ttl_seconds,
    )
    source.bootstrap()
    loopback = _is_loopback(host)
    # the LIVE branch sessions of this checkout, re-derived for this process
    # (T033a) — before any route can be asked about a session ref.
    #
    # ADMISSION IS THE CONFINEMENT (PR #49 review finding 14). This ran
    # UNCONDITIONALLY and BEFORE the bind was even classified, so an engineer who
    # served a real checkout with `--host 0.0.0.0` admitted every live session
    # into the registry of a HOSTED plane — and `/snapshot-index.json` then
    # advertised the branch names of unmerged work, the selector offered a row
    # that could only ever 403, and the page printed the session's CLI verbs.
    # FR-048 says a hosted plane has NO session, so the cheapest and most
    # complete confinement is never to admit the rows: a filter can be forgotten
    # by the next route, an empty registry cannot.
    # ONE resolution of the session key's repository half, before the bootstrap
    # that registers under it and before any request can read it (finding R2-11).
    session_repository = served_repository(source)
    if loopback:
        _bootstrap_session_entries(source, checkout_root,
                                   repository=session_repository)
    active = source.registry.active
    source_revision = active.source_revision if active else _read_source_revision(snapshot_path)

    # gate actions need a HUMAN actor: explicit arg, else the checkout's git
    # user.name; unresolvable identity keeps the capability off (fail-closed).
    resolved_actor = resolve_actor(checkout_root, actor) if loopback else None
    capabilities = compute_capabilities(
        nlm_present=_probe_nlm(adapter_factory),
        checkout_real=_checkout_real(checkout_root),
        loopback=loopback,
        actor=resolved_actor,
        refresh_binding=source.refresh_binding,
        # THE ROUTES THIS ASSEMBLY COLLECTED, so a flag whose affordance is a
        # contributed route is true only where one answers (T084; batch L).
        route_bindings=route_bindings,
    )
    # The human console's per-serve token (FR-019's third clause, review finding
    # 2). Minted only where session verbs exist at all.
    #
    # WHERE IT IS DELIVERED depends on whose plane this is (plan 034 T104;
    # RULED openxFactory#656 `5963851934`). On a HOST's plane it is published on
    # `/capabilities`, the one route the served page reads same-origin and no
    # cross-origin page can read, as it always was. On a STANDALONE plane,
    # built from openDox's own default profile, it is NOT: any loopback caller
    # can read `/capabilities`, other OS users of the machine included. The
    # entry point writes it into a 0600 private copy instead and opens the page
    # with it in the URL's fragment (`console_access.publish`). The routes that
    # require it require it exactly as before; only the delivery differs.
    console_token = (mint_console_token()
                     if capabilities["actions"]["session"] else None)
    console_delivery = (console_access.delivery_for(domain_profile.current())
                        if console_token else None)
    if console_token and console_delivery == console_access.DELIVERY_CAPABILITIES:
        capabilities[CONSOLE_TOKEN_FIELD] = console_token
    # THE ONE REPOSITORY THIS SERVE CAN WRITE TO. A plane reaching several
    # repositories serves them all for READING through per-entry source roots,
    # but exactly one of them is the checkout a gate verb writes into, and
    # `refuse_foreign_repository` refuses any create that names another —
    # correctly, because "cannot verify" is not "matches".
    #
    # The browser previously had to GUESS it, and under a composed project view
    # it guessed the PROJECT id, which is not a repository at all. A serve knows
    # what it serves, so it says so; the client stops inferring. Absent
    # (no writable checkout) means no create is possible, which is the honest
    # reading of a plane that cannot name one.

    # ---- THE VIEW MANIFEST, PUBLISHED (§ 3.4 slice S5) ----------------------
    #
    # THE ONE LINE SLICE S3 BUILT BOTH ENDS OF AND DELIBERATELY DID NOT WRITE.
    # `opendox/view_extension.py` says so of itself: "The ONE line that puts it
    # there (`capabilities["views"] = view_manifest(...)` in
    # `serve.build_server`) is NOT written by slice S3 ... S5, the slice at
    # which a contribution first EXISTS to deliver, joins them in its own
    # declared-edit window." A contribution exists now — openXdox-code's
    # `view_extensions.VIEW_EXTENSIONS`, six gate-loop bindings — so the two
    # ends are joined here.
    #
    # NO NEW ROUTE AND NO SECOND FETCH, which is § 4.3's rule for the profile's
    # display facet applied unchanged: the manifest rides on `/capabilities`,
    # the payload `views/notebook.js`'s `probeCapabilities()` already fetches
    # once at load. A shell served as a static image 404s that route and reads
    # an empty consumer column, which is how a student install comes up with no
    # gate bar and no 404.
    #
    # COLLECTED THE WAY THE ROUTES ARE, three statements above: the host's
    # contributed extensions through ONE `collect_view_bindings`, checked
    # against the routes THIS assembly actually contributed — so a class-A or
    # class-C binding naming `/actions/gate/*` is refused where the server is
    # built rather than discovered in a browser. Class B is exempt by
    # construction, which is the boundary working.
    #
    # ABSENT IS AN EMPTY COLUMN, MALFORMED FAILS CLOSED, and the asymmetry is
    # `host_view_extensions`' own: a host registered with no `VIEW_EXTENSIONS`
    # facet gets `host_facet: "absent"` with its profile NAMED, never a refusal,
    # because every host has yet to grow the facet and refusing would be a flag
    # day imposed by the seam that exists to avoid one.
    #
    # PRESENCE, NOT TRUTHINESS (Copilot review, round 2). `host_view_facet`
    # answers BOTH halves in one read: a host that declares `VIEW_EXTENSIONS =
    # ()` is "declared" with an empty column, and a host that never grew the
    # facet is "absent" — the same empty tuple, two different facts, and a
    # conditional on the tuple's TRUTHINESS reported both as the second. That is
    # the diagnostic this manifest exists to carry, so it is read the way it is
    # written.
    host_facet, view_extensions = view_extension.host_view_facet(
        profile_openxfactory)
    capabilities["views"] = view_extension.view_manifest(
        view_extension.collect_view_bindings(
            view_extensions, contributed_routes=route_bindings),
        contributed_routes=route_bindings,
        host_facet=host_facet,
        # THE PROFILE'S NAME COMES THROUGH THE ESTATE'S OWN NAMER, never off a
        # dunder (Copilot review, round 3). `getattr(profile_openxfactory,
        # "__name__", None)` could only ever answer `None`:
        # `_LateProfile.__getattr__` refuses every dunder BY DESIGN, so that
        # `copy`, `pickle`, `inspect` and pytest's assertion rewriting cannot
        # fire the composition point by probing. The manifest's named-absence
        # contract — "a host IS registered and simply does not contribute
        # panels, which is a different fact from no host at all" — needs the
        # name, and it was blank in every payload this serve published.
        # `view_extension.host_profile_name()` resolves the profile the way
        # `profile_proxy`'s own refusal does, through
        # `domain_profile.name_of()`, so both accessors of ONE registration name
        # a profile the same way.
        host_profile=view_extension.host_profile_name(profile_openxfactory),
    )

    # ---- THE DISPLAY FACET, PUBLISHED (§ 3.4 slice S7) ----------------------
    #
    # § 4.3 STEP 2, VERBATIM: "`serve.py` exposes the profile's DISPLAY FACET —
    # the stage keys with their labels, the status vocabulary, the
    # artifact-folder words — on the existing `/capabilities` payload (already
    # fetched once at load by `views/notebook.js`'s `probeCapabilities`), so no
    # new route and no second fetch." One more facet of the ONE registered
    # profile, read through the SAME lazy proxy as `ROUTE_EXTENSIONS` and
    # `VIEW_EXTENSIONS` three statements above.
    #
    # WHY IT RIDES BESIDE `views` RATHER THAN INSIDE IT: the two answer
    # different questions of the same host. `views` is WHICH PANELS a consumer
    # column contributes; `display` is WHAT THIS DOMAIN CALLS THINGS, which
    # every class-C file in openDox's OWN core arm reads whether or not any
    # column is contributed. A student install has no `views` and still has a
    # funnel to label.
    #
    # ABSENT IS NEUTRAL AND NAMED, never openxFactory's words: a host with no
    # `DISPLAY` facet gets `host_facet: "absent"` with its profile NAMED and
    # openDox's own neutral vocabulary in the payload, so the shell comes up
    # saying `sources → groups → candidates → …` — visibly un-domained rather
    # than invisibly re-domained. `display_profile`'s module docstring carries
    # the argument for departing from § 4.3 point 5's "refusal, not a default"
    # here and nowhere else. MALFORMED still fails closed: a facet that IS
    # declared and does not conform raises `DisplayFacetError` HERE, where the
    # server is built, naming the role, the field and the value.
    capabilities["display"] = display_profile.display_manifest(
        display_profile.host_display(profile_openxfactory),
        # THE NAME THROUGH THE HELPER, not a dunder (Copilot round 3 on S5 leg
        # B, applied to the display block for the same reason): the lazy proxy
        # refuses every dunder by design, so this read could only ever answer
        # `None` and `host_facet: "absent"` was never NAMED — which is the one
        # fact the named absence exists to carry.
        host_profile=view_extension.host_profile_name(profile_openxfactory),
    )

    # The core handler FIRST among the bases and the declared contributions
    # after it (`route_extension.compose_handler`). With none declared, this is
    # exactly the `type("BoundDashboardHandler", (DashboardHandler,), {...})`
    # it replaces.
    bound = route_extension.compose_handler(
        "BoundDashboardHandler", DashboardHandler, handler_contributions, {
        "checkout_root": checkout_root,
        "snapshot_path": snapshot_path,
        "snapshot_route": snapshot_route,
        "source_revision": source_revision,
        "head": head,
        "quiet": quiet,
        "capabilities": capabilities,
        "loopback": loopback,
        "adapter_factory": staticmethod(adapter_factory) if adapter_factory is not None else None,
        "pull_request_factory": (staticmethod(pull_request_factory)
                                if pull_request_factory is not None else None),
        "model_port_factory": (staticmethod(model_port_factory)
                              if model_port_factory is not None else None),
        # UNSET defaults to the pinned loader; an EXPLICIT None is a caller
        # saying "no validators", which refuses both model routes. The two are
        # distinguished deliberately: an absent argument must never become an
        # implicit "serve unvalidated".
        "schema_validator_factory": (
            staticmethod(default_doxbench_validators)
            if schema_validator_factory is _UNSET_VALIDATOR_FACTORY
            else (staticmethod(schema_validator_factory)
                  if schema_validator_factory is not None else None)),
        # ONE fresh turn-idempotency ledger per served process (T050/T051).
        "turn_store": doxbench_turns.TurnStore(),
        # ONE fresh abstract cache per served process, beside it and never it
        # (add-doxbench-distilled-abstract §5.3, N1). Two stores, two bounds:
        # abstract churn over a scope larger than the abstract bound evicts
        # abstracts and nothing else.
        "abstract_store": doxbench_abstract_store.AbstractStore(),
        # The INSTALL-TIME retrieval-backend declaration (task 10.6). Bound
        # once, here, and READ by the route; the backend instance itself is
        # built per request from this declaration and from nothing else, so no
        # tile's derived index is ever visible to another tile's turn.
        "knowledge_declaration": knowledge_declaration,
        # The packet assembler, defaulted to the real one (see the class
        # attribute's own note on why absence is not a posture here).
        "packet_assembler": staticmethod(
            packet_assembler if packet_assembler is not None
            else doxbench_packet.assemble_packet),
        # ONE fresh content-free usage meter per served process (task 10.8).
        "usage_meter": doxbench_telemetry.UsageMeter(),
        "actor": resolved_actor,
        # the session key's repository half, for this whole process (R2-11)
        "session_repository": session_repository,
        "console_token": console_token,
        "gate_index_validator": gate_index_validator,
        "gate_manifest_validator": gate_manifest_validator,
        "gate_xref_validator": gate_xref_validator,
        "source": source,
        # The contributed routes, already in consult order (§ 2.4). One more
        # injected class attribute, exactly like the seams above it.
        "route_bindings": route_bindings,
        # THE SERVING PROCESS'S OWN INSTALL SHAPE (T073; 13.4a), asked per
        # request by the `/capabilities` arm.
        "install_report": (staticmethod(install_report)
                           if install_report is not None else None),
    })
    # A ROUTE THAT CANNOT BE SERVED MUST NOT START. Resolved against the bound
    # class — the object the dispatch will `getattr` on — so a binding naming a
    # handler this server does not have is a refused build rather than a stack
    # trace on the first live connection.
    route_extension.resolve_handlers(route_bindings, bound)
    factory = functools.partial(bound, directory=str(web_dir))
    httpd = _server_class_for(host)((host, port), factory)
    # FOR THE ENTRY POINT, which delivers the token where `/capabilities` does
    # not (`console_access.publish`): the token, and which delivery this plane
    # uses. Both `None` where no token was minted.
    httpd.console_token = console_token
    httpd.console_token_delivery = console_delivery
    # ...and EVERY root this plane serves files from, which the token's copy
    # may not sit in (Copilot at openDox-code#84, r4173806506): the checkout,
    # the static bundle's directory, each declared source root, the root of
    # each entry the registry holds now (the bootstrapped session worktrees
    # among them), and, on a loopback plane, the sessions container every
    # later session worktree is made in (`branch_session.sessions_root`).
    #
    # AND THE SNAPSHOT FILES `/snapshot.json` READS DIRECTLY (Copilot at
    # openDox-code#84, r4175213798), not through the static handler: the
    # configured snapshot, each registered entry's, and, on a loopback plane,
    # the container every session's snapshot is written in. A snapshot named
    # at an earlier copy would otherwise be replaced by the new one and served.
    served = [checkout_root, web_dir, snapshot_path,
              *(Path(path).resolve() for path in (source_roots or {}).values())]
    if loopback:
        from opendox import branch_session as session_mod
        served.append(session_mod.sessions_root(checkout_root))
        served.append(session_mod.snapshots_root(checkout_root))
    entries = getattr(source.registry, "entries", None)
    for entry in (entries() if callable(entries) else ()):
        for root in (getattr(entry, "source_root", None),
                     getattr(entry, "snapshot_path", None)):
            if root:
                served.append(Path(root).resolve())
    httpd.served_roots = tuple(dict.fromkeys(served))
    return httpd


class _IPv6ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    """`ThreadingHTTPServer` over `AF_INET6`, for a bind to an IPv6 literal
    (plan 034 T103; Copilot at openDox-code#80, r4171161548).

    The standard class is `AF_INET` only, so `host="::1"`, which
    `LOOPBACK_HOSTS` and the local install's `LOCAL_BIND_HOSTS` both name,
    failed at the bind with `gaierror`, and `generate-and-open --local --host
    ::1` ended in a traceback. The loopback Host gate accepts `[::1]:<port>`
    exactly where the socket is bound to `::1`, so the bind it names has to
    be one this module can make."""

    address_family = socket.AF_INET6


def _server_class_for(host: str) -> type[http.server.ThreadingHTTPServer]:
    """The server class a bind to `host` takes: `AF_INET6` for an IPv6
    literal (the one spelling of a host that contains a colon), and the
    standard `AF_INET` class for everything else, exactly as before."""
    return (_IPv6ThreadingHTTPServer if ":" in str(host)
            else http.server.ThreadingHTTPServer)


def server_url(httpd: http.server.ThreadingHTTPServer, path: str = "/") -> str:
    host, port = httpd.server_address[:2]
    # A WILDCARD BIND IS ANNOUNCED AT ITS OWN FAMILY'S LOOPBACK (Copilot at
    # openDox-code#80, r4173481146). Since T103's fix round 1 `::` binds an
    # `AF_INET6` socket, which is IPv6-only on some platforms, so announcing
    # it at `127.0.0.1` could print a URL nothing answers. `::` is `::1`;
    # the IPv4 wildcard stays `127.0.0.1`.
    if host == "::":
        host = "::1"
    elif host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    # AN IPv6 LITERAL IS BRACKETED in a URL (RFC 3986 § 3.2.2): `::1` is
    # `http://[::1]:<port>/`, and `[::1]:<port>` is also the `Host` a browser
    # then sends, which the loopback gate accepts on that bind (T103).
    if ":" in str(host):
        host = f"[{host}]"
    # plain-HTTP by design (S5332): a loopback-only local dev server — TLS adds
    # nothing on 127.0.0.1; the scheme is composed so no insecure-URL literal
    # exists for a copy-paste into non-loopback code.
    scheme = "http"
    return f"{scheme}://{host}:{port}{path}"


def serve(
    web_dir: Path | str,
    snapshot_path: Path | str,
    checkout_root: Path | str,
    *,
    host: str = DEFAULT_HOST,
    port: int = 0,
    quiet: bool = False,
    actor: str | None = None,
    **build_kwargs,
) -> None:
    """Build and run forever (standalone use).

    THIS is where the real notebook adapter is declared (PR #49 hardening item
    1): `serve()` is an entrypoint a human runs, so it opts into `nlm` explicitly
    rather than letting `build_server` reach for it on every caller's behalf. A
    caller that passes its own `adapter_factory` (a test, a harness) keeps it."""
    build_kwargs.setdefault("adapter_factory", real_notebook_adapter)
    # The INSTALL-TIME retrieval-backend declaration, made by the ENTRYPOINT for
    # the same reason the notebook adapter is: an operator must be able to read
    # what their install talks to, and `build_server` reaching for one on every
    # caller's behalf would put that decision out of sight. This is the
    # self-hosted case of the ratified two-case principle; a tenant install
    # declares its own here instead.
    build_kwargs.setdefault("knowledge_declaration",
                            doxbench_knowledge.SELF_HOSTED_LOCAL_EMBEDDED)
    # THE MODEL PROVIDER, declared by the same entrypoint discipline. This is
    # the STANDALONE SECONDARY PATH: the primary entrypoint is
    # `cli.cmd_generate_and_open`, which makes the identical declaration with
    # its own `--model-session-root` flag. Both are written out because a
    # declaration only one of them makes is a serve whose operator cannot tell
    # which install talks to a model — and `setdefault` keeps a caller's own
    # factory (a test, a harness) exactly as the two above do.
    #
    # The session root follows the SAME rule the CLI defaults to — beside the
    # served snapshot — so the two entrypoints cannot drift into writing harness
    # sessions in two different places.
    #
    # `doxbench_install` is imported at module scope (see the import block's own
    # note): the graph is acyclic and importing the declaration starts nothing.
    # What stays an ENTRYPOINT decision is this call -- the two entrypoints are
    # the only places that reach for the real declaration, and `build_server`
    # still never does it on a caller's behalf.
    #
    # SINCE add-model-provider-broker (ratified 2026-08-26) the declaration is
    # `declared_model_port_factory`, which reads the checkout's model-provider
    # BINDINGS and resolves the broker-backed port when one is declared. A
    # checkout declaring none resolves exactly the harness factory this line
    # used to name, so the unconfigured posture is unchanged byte for byte.
    # This file still names no provider endpoint, holds no credential and holds
    # no token: all three live in `doxbench_provider` and nowhere else, which
    # is the narrowed boundary the structural test enforces.
    build_kwargs.setdefault(
        "model_port_factory",
        doxbench_install.declared_model_port_factory(
            doxbench_install.session_root_beside(snapshot_path),
            checkout_root=checkout_root))
    httpd = build_server(web_dir, snapshot_path, checkout_root, host=host,
                         port=port, quiet=quiet, actor=actor, **build_kwargs)
    page = server_url(httpd, "/index.html")
    # THE CONSOLE TOKEN'S PRIVATE COPY on a standalone plane (plan 034 T104),
    # as `cli.cmd_generate_and_open` writes it: its PATH is printed, never the
    # token, and it goes when the server does. A copy that cannot be written
    # safely refuses the start (`console_access.ConsoleAccessRefused`).
    #
    # A plain `kill`, or a closed terminal, stops a standalone console the way
    # Ctrl-C does, from BEFORE the copy is written to after it is removed, and
    # a stop that arrives while the copy is written or removed is held until
    # that is done (Copilot at openDox-code#84, r4175213864). A plane that
    # writes no copy keeps the signals' defaults.
    console = None
    with console_access.terminate_as_interrupt(console_access.needs_copy(httpd)):
        try:
            try:
                with console_access.deferred_termination():
                    console = console_access.publish(httpd, page_url=page)
                if console is not None:
                    print(f"console {console.file_url} (this user's private "
                          "copy, mode 0600: open it to open the console page)")
                # FLUSHED before the process blocks (plan 034 T056): where
                # standard output is a pipe or a file it is block-buffered, so
                # an unflushed line never reaches a wrapper while the server
                # runs, and the wrapper cannot learn an ephemeral port or tell
                # that the server started.
                print(f"serving ideation dashboard at {page}", flush=True)
                httpd.serve_forever()
            except KeyboardInterrupt:
                pass
        finally:
            # The copy FIRST, while this process still holds the port, then
            # the socket (`console_access.remove_private_copy`). A stop that
            # arrives meanwhile lets both finish.
            with console_access.deferred_termination(raise_pending=False):
                console_access.remove_private_copy(console)
                httpd.server_close()


def _source_roots_from_args(values) -> dict:
    """`--source-root repo[@ref]=PATH`, repeatable. Explicit by design: nothing
    guesses where another repository's checkout is, and an entry with no declared
    root serves no documents at all (fail-closed, task 2.2)."""
    roots: dict[str, str] = {}
    for raw in values or []:
        key, sep, path = str(raw).partition("=")
        if not sep or not key.strip() or not path.strip():
            raise SystemExit(f"--source-root expects repo[@ref]=PATH, got {raw!r}")
        roots[key.strip()] = path.strip()
    return roots


# The shape a correct invocation has, shown in the `--checkout-root` refusal.
# Placeholders only, for the same reason `cli._GENERATE_SHAPE` carries none: a real
# path in the message would re-create the confusion it is ending.
_SERVE_SHAPE = (
    "python3 src/opendox/serve.py \\\n"
    "  --snapshot <the snapshot json to serve> \\\n"
    "  --checkout-root <path to the corpus checkout>"
)


def _refuse_impossible_checkout_root(value: Path | str) -> int:
    """Refuse a `--checkout-root` that CANNOT be a checkout; report one that
    merely is not a corpus. Returns the process exit status (0 = keep going).

    `--checkout-root` is `cli.py`'s `--repo-root` under a second spelling (runbook
    §2) and it had the same T092 hole in a different shape: a path from another
    filesystem namespace was accepted in silence, and the dashboard then came up
    looking fine with every checkout-bound affordance simply absent and `/source/`
    404ing. Nothing said why.

    The two cases are NOT the same, so they are not treated the same:

      * a path that does not exist, or is not a directory, can never be a served
        checkout in any configuration -> REFUSED here, before a socket is bound.
      * an existing directory that holds no corpus IS a supported configuration:
        the served image mounts the empty `/srv/empty` sentinel precisely so
        `_checkout_real` reports false and the write-bearing affordances stay off.
        So it serves, and says loudly what it will not be able to do — which on a
        LOCAL run is the same wrong path, diagnosed.

    Both answers are the REGISTERED corpus-root predicate's
    (`projection_seams.corpus_root`, plan 034 T055)."""
    predicate = projection_seams.corpus_root.current()
    path = Path(value)
    if not path.is_dir():
        print(predicate.corpus_root_refusal(value, flag="--checkout-root",
                                            shape=_SERVE_SHAPE), file=sys.stderr)
        return 1
    defect = predicate.corpus_scan_defect(value)
    if defect is not None:
        print(f"--checkout-root {path.resolve()} is not a corpus checkout: "
              f"{defect}", file=sys.stderr)
        print("  serving anyway — an empty directory is the hosted image's "
              "sentinel — with every affordance that needs a real checkout OFF: "
              "no gate actions, no branch sessions, no /source/ pass-through",
              file=sys.stderr)
        print("  on a LOCAL run this is a wrong --checkout-root: it must name the "
              "SERVED CHECKOUT, the corpus tree itself", file=sys.stderr)
    return 0


#: THE SERVER ENTRY POINT'S OWN NAME AND WORDS (plan 034 T084, with
#: `cli.PROG`; adversarial review 2). `python -m opendox.serve --help` printed
#: `usage: ideation-dashboard-serve` and this module's docstring, which is
#: openxFactory's pre-carve history. It names how it is run and openDox only.
#: Loopback is the DEFAULT bind, not a promise: `--host` takes any address, and
#: a hosted install serves through this entry point (Copilot review of
#: openDox-code#77, r4173844338).
SERVE_PROG = "python -m opendox.serve"
SERVE_DESCRIPTION = (
    "Serve an openDox snapshot: the browser bundle, the snapshot and the "
    "read-only source of the checkout it was generated from, on a loopback "
    "address unless --host names another. `opendox generate-and-open` "
    "generates a snapshot and serves it in one command.")


def main(argv: list[str] | None = None) -> int:
    # The process entry point registers openDox's own default where no host has
    # (R1Q3 (a)), exactly where a host would register its own. Nothing is BUILT
    # from it until `build_server()` reads it, so until then a host's
    # registration still replaces it (R1Q3 (ii); RN-1 (a)).
    from opendox import default_profile, domain_profile
    domain_profile.register_default(default_profile)
    # AND its own default home corpus (4.1a, T022, same ruling), exactly
    # where a host would register its own adapter. `build_server()` below
    # makes the identical call as its own first statement, so this one is a
    # no-op once that runs; kept for the same reason T016 keeps its own
    # match here: the OUTERMOST entry point states the contract on its own.
    corpus_adapter.register_default_home(_default_home_factory)
    # AND openDox's own snapshot generator (5.4, T052), the same way.
    generator_seam.register_default(default_generator.GENERATOR)
    # AND openDox's own projection defaults (5.5, T055), the same way, and
    # BEFORE the parser: its option defaults below read the registered
    # registry (`registry_mod.DEFAULT_REF` and the data source's defaults).
    projection_seams.register_defaults()
    # AND openDox's own doxBench defaults (4.3, T085), the same way.
    doxbench_defaults.register_defaults()
    # AND the consumer columns' defaults (plan 034 T084; #1144 4.3,
    # R1Q10 (a)): the gate primitives, the doxBench scope, kickoff and
    # the cross-reference register, the same way.
    column_seams.register_defaults()
    parser = argparse.ArgumentParser(prog=SERVE_PROG,
                                     description=SERVE_DESCRIPTION)
    parser.add_argument("--web-dir", default=str(Path(__file__).resolve().parent / "web"),
                        help="static bundle directory (default: the packaged web/)")
    parser.add_argument("--snapshot", required=True,
                        help="snapshot JSON served as the baked/local entry — the "
                             "FIRST-BOOT and OFFLINE fallback when a data source is "
                             "declared (design D6)")
    parser.add_argument("--checkout-root", required=True, help="pinned checkout root for /source/ pass-through")
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host (default: 127.0.0.1, loopback only)")
    parser.add_argument("--port", type=int, default=0, help="bind port (default: ephemeral)")
    parser.add_argument("--actor", default=None,
                        help="human identity for loopback gate actions "
                             "(default: the checkout's git user.name; "
                             "unresolvable keeps gate actions off)")
    parser.add_argument("--repository", default=None,
                        help="repository id of the baked/local snapshot "
                             "(default: the snapshot's own `repository` field)")
    parser.add_argument("--ref", default=registry_mod.DEFAULT_REF,
                        help=f"ref of the baked/local snapshot (default: "
                             f"{registry_mod.DEFAULT_REF}; the served plane only "
                             f"ever exercises {registry_mod.DEFAULT_REF})")
    parser.add_argument("--data-source-dir", default=None,
                        help="RUNTIME DATA SOURCE: a directory holding the published "
                             "index + per-repository snapshots (a mounted volume or a "
                             "checked-out publication tree)")
    parser.add_argument("--data-source-url", default=None,
                        help="RUNTIME DATA SOURCE: base URL of the published tree, read "
                             "SERVER-SIDE (the browser never reaches it). Brett's "
                             "2026-07-26 ruling on open question 1 is the aggregation "
                             "repo's raw files, which is what --data-source-github "
                             "composes")
    parser.add_argument("--data-source-github", default=None, metavar="OWNER/REPO",
                        help="RUNTIME DATA SOURCE (the RULED hosted binding): read the "
                             "published tree from this repository's raw files, i.e. "
                             "https://raw.githubusercontent.com/OWNER/REPO/<ref>/<path>/")
    parser.add_argument("--data-source-github-ref", default=registry_mod.DEFAULT_REF,
                        help=f"ref of the raw-file source (default: {registry_mod.DEFAULT_REF})")
    parser.add_argument("--data-source-path", default=registry_mod.DEFAULT_PUBLISH_PATH,
                        help=f"path of the published tree inside the source repository "
                             f"(default: "
                             f"{registry_mod.DEFAULT_PUBLISH_PATH or 'the source root'})")
    parser.add_argument("--data-source-index", default=registry_mod.DEFAULT_INDEX_NAME,
                        help=f"index filename inside the data source (default: "
                             f"{registry_mod.DEFAULT_INDEX_NAME})")
    parser.add_argument("--data-source-peek-seconds", type=float,
                        default=registry_mod.PEEK_TTL_SECONDS,
                        help="how long the serving side caches its cheap INDEX peek "
                             "before answering a freshness poll from the source again "
                             f"(default: {int(registry_mod.PEEK_TTL_SECONDS)}s; the "
                             "browser polls every ~5 minutes, so N viewers cost the "
                             "source at most one index read per TTL)")
    parser.add_argument("--data-source-token-env", default=None, metavar="ENV_NAME",
                        help="NAME of an environment variable holding a READ-ONLY bearer "
                             "token for the data source (deploy-time config: never a "
                             "credential in a repository, never reachable from the "
                             "browser)")
    parser.add_argument("--source-root", action="append", default=None,
                        metavar="REPO[@REF]=PATH",
                        help="per-entry /source confinement root, repeatable; an entry "
                             "with no declared root serves no documents (fail-closed)")
    parser.add_argument("--local-index", default=None,
                        help="a LOCAL snapshot index (multi-repository local plane); "
                             "snapshot locations resolve relative to the index file")
    parser.add_argument("--project-register", default=None,
                        help="project-register instance passed to the generator on a "
                             "local regenerate (grouping resolution)")
    args = parser.parse_args(argv)
    if args.project_register == "":
        # AN EMPTY `--project-register` IS REFUSED, fail closed (the holder,
        # 2026-09-28; the generate verbs refuse it the same way, as
        # `cli.SourceOptionRefused`). The snapshot source tests the value for
        # truth, so an empty one would be dropped without a word, and
        # `Path("")` would name the current directory. Neither is what a
        # caller who typed the option asked for.
        print("serve refused: --project-register was given an empty path. "
              "Name the file to read, or leave --project-register out",
              file=sys.stderr)
        return 1
    rc = _refuse_impossible_checkout_root(args.checkout_root)
    if rc:
        return rc
    try:
        # EVERY DATA-SOURCE OPTION IS HANDED OVER AS GIVEN (plan 034 T055).
        # `None` means "not given", and anything else, an explicitly empty
        # value included, is a declaration the REGISTERED registry decides
        # about: openDox's own refuses each one by name, and a host's reads
        # it. So each option is tested against None, never for truth. A
        # GitHub source is composed into the URL only where no URL was given,
        # and a slug that cannot be composed is refused like any other.
        url = args.data_source_url
        if url is None and args.data_source_github is not None:
            try:
                url = registry_mod.github_raw_base_url(
                    args.data_source_github, ref=args.data_source_github_ref,
                    path=args.data_source_path)
            except ValueError as exc:
                print(f"serve refused: --data-source-github: {exc}",
                      file=sys.stderr)
                return 1
        data_source = registry_mod.data_source_from_options(
            directory=args.data_source_dir,
            url=url,
            token_env=args.data_source_token_env,
        )
        serve(args.web_dir, args.snapshot, args.checkout_root, host=args.host,
              port=args.port, actor=args.actor,
              repository=args.repository, ref=args.ref,
              data_source=data_source, index_name=args.data_source_index,
              source_roots=_source_roots_from_args(args.source_root),
              local_index=args.local_index,
              project_register=args.project_register,
              peek_ttl_seconds=args.data_source_peek_seconds)
    except projection_seams.ProjectionSeamError as exc:
        # A PROJECTION SEAM'S REFUSAL, before a socket is bound (plan 034
        # T055): openDox's own registry refuses a declared data source or
        # local index rather than ignoring it, since only a host's registry
        # reads one. Reported on stderr with a non-zero status, as the
        # `--checkout-root` refusal above is.
        print(f"serve refused: {exc}", file=sys.stderr)
        return 1
    except console_access.ConsoleAccessRefused as exc:
        # NO SAFE PRIVATE COPY, NO SERVE (plan 034 T104): a standalone console
        # whose token nobody can be handed is refused, before it serves.
        print(f"serve refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
