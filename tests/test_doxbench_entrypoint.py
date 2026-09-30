"""The model-provider port is DECLARED AT THE REAL ENTRYPOINT, and it resolves
to ONE process-lifetime adapter (add-doxbench-distilled-abstract §2.1-2.2a, D9).

WHY THIS FILE EXISTS. Every existing model test injects `model_port_factory`
into `build_server` itself, so the whole suite could be green while no entrypoint
declared a port at all — which is exactly the state this change found:
`_workbench_model_port` returned `None` in every real serve, and the honest
posture of every model consumer was "absent capability" forever. The requirement
this pins is the provider-boundary one's last two clauses: the port "MUST also be
DECLARED AT AN ENTRYPOINT for any consumer to reach a provider at all", and where
the declared adapter is stateful the declaration "SHALL resolve to ONE instance
for the life of the served process".

THE BAR IS NOT NON-`None`. `OmpHarnessBridge`'s `catalog` argument defaults to
`EMPTY_CATALOG` (`doxbench_model.py:719`), so a bare declaration would resolve,
disclose nothing, and look like a working install. The pin is therefore that the
resolved port's `catalog()` discloses AT LEAST ONE AVAILABLE ENTRY.

NO TEST HERE REACHES A REAL `omp`. The bridge starts its child lazily, at the
first turn that needs one, and nothing below takes a turn — but "nothing below
takes a turn" is a claim about today's code, so the spawn seam is REPLACED by a
refusal for the whole fixture. If a future edit makes resolution start a child,
these tests fail with that sentence rather than silently launching a harness.
That is the same discipline `tests/hermeticity.py` now applies to the `omp`
binary itself (§2.3): two independent layers, neither one's substitute.

THE ENTRYPOINT RUNS FOR REAL, AND SIX OF ITS REACHES ARE STOOD IN (plan 034
T035). `cmd_generate_and_open` is what these cases exist to drive, and they now
drive it in a lone checkout. Before this, all four fixture cases errored in
fixture setup at the first reach across the carve, `openxdox.corpus_root`
(`ConsumerReachUnavailable`). The reaches are the ones plan 034 names as its
phase-1 limit (plan.md, "Phase-1 limit"; research R7), and phase 2 gives
openDox its own snapshot and generator. Until then each one is stood in here,
and nothing else is:

  * three in `cli`, the `consumer_reach` names `generate-and-open` calls:
    `corpus_root_refusal`, `generate_snapshot` and
    `snapshot_mod.write_snapshot`. A fourth, `SCANNED_ROOTS`, is read only to
    warn about a snapshot with no document, and the stand-in snapshot carries
    one, so it is never reached;
  * three in `serve`, T011's `standalone` stand-ins
    (`tests/test_route_handler_contribution.py`, section 6): the snapshot
    source, through `build_server`'s own `snapshot_source=` seam;
    `_checkout_real`; and `registry_mod`'s two `BINDING_*` constants.

`_checkout_real` ANSWERS TRUE HERE, where T011's answers false. The model port
is gated on the `session` verdict (`serve_workbench._workbench_model_port`):
loopback, a real checkout, and a resolved human actor. The carve's `base-repo`
fixture, which these cases used to serve, was a real corpus checkout, so the
stand-in gives the answer that fixture gave. The predicate itself is
openXdox's (`corpus_root.corpus_scan_defect`), and a lone checkout cannot ask
it.

What these cases test is openDox's own: the port the entrypoint declares
(`doxbench_install.declared_model_port_factory`), the one adapter it resolves
to, and the session root it is handed. None of them reads the snapshot. The
checkout is an empty scratch directory rather than the carve's `base-repo`
fixture, which stayed in openxFactory and does not exist at this leg.
"""

from __future__ import annotations

import json
import types

import pytest

from conftest import PINNED_REVISION

from opendox import cli as cli_mod
from opendox import doxbench_bridge as br
from opendox import doxbench_install as install_mod
from opendox import doxbench_model
from opendox import serve as serve_mod
from opendox.runtime import config as runtime_config


def _handler_class(httpd):
    """The bound `DashboardHandler` subclass a server was built with — the same
    unwrap `test_doxbench_request_handling.py` uses."""
    return getattr(httpd.RequestHandlerClass, "func", httpd.RequestHandlerClass)


# --------------------------------------------------------------------------
# the phase-1 stand-ins (see the module docstring), and nothing else
# --------------------------------------------------------------------------

class _StandInSource:
    """`build_server`'s snapshot source as T011's `standalone` fixture injects
    it: nothing registered, nothing baked, so no session is re-derived."""

    refresh_binding = None
    baked_repository = None

    class registry:
        active = None

    def bootstrap(self):
        pass


def _stand_in_generate_snapshot(repo_root, repository, *, source_revision=None,
                                **_ignored):
    """`generate_snapshot`'s stand-in: exactly the fields `generate-and-open`
    reads back when it reports the run. ONE document, so `_report` has no empty
    projection to warn about and never reaches `SCANNED_ROOTS`."""
    return {"repository": repository,
            "generation": {"source_revision": source_revision},
            "documents": [{"id": "stand-in.md"}]}


def _stand_in_write_snapshot(snapshot, output, boundary):
    """`snapshot.write_snapshot`'s stand-in: the file `build_server` is handed,
    which it opens only to read `generation.source_revision` back."""
    output.write_text(json.dumps(snapshot), encoding="utf-8")
    return output


@pytest.fixture()
def entrypoint_server(tmp_path, monkeypatch):
    """A server built by the REAL entrypoint path: `cli.cmd_generate_and_open`,
    which is what `generate-and-open` runs and where `build_server` is called.

    `--no-serve` still BUILDS the server (it prints the URL and closes it), so
    the handler class this yields is the one a real launch would serve with.
    Yields `(handler, spawned, session_root)`; `spawned` stays empty unless a
    harness child was started, which is itself an assertion below."""
    spawned = []

    def _refuse_spawn(argv, environment, cwd):
        spawned.append(tuple(argv))
        raise AssertionError(
            "resolving the entrypoint's model port started a harness child: "
            f"no test may reach a real `omp` ({list(argv)!r})")

    monkeypatch.setattr(br, "_spawn_child", _refuse_spawn)

    monkeypatch.setattr(cli_mod, "corpus_root_refusal",
                        lambda root, shape=None: None)
    monkeypatch.setattr(cli_mod, "generate_snapshot", _stand_in_generate_snapshot)
    monkeypatch.setattr(cli_mod, "snapshot_mod", types.SimpleNamespace(
        write_snapshot=_stand_in_write_snapshot))
    monkeypatch.setattr(serve_mod, "_checkout_real", lambda root: True)
    monkeypatch.setattr(serve_mod, "registry_mod", types.SimpleNamespace(
        BINDING_REGENERATE="regenerate", BINDING_REFETCH="refetch"))

    built = []
    real_build_server = serve_mod.build_server

    def _capture(*args, **kwargs):
        # A TRIPWIRE, not only an injection: the day the entrypoint declares a
        # snapshot source of its own (phase 2), this stand-in must go, and this
        # line says so instead of silently standing in over it.
        assert "snapshot_source" not in kwargs, (
            "the entrypoint now declares its own snapshot source; drop the "
            "phase-1 stand-in from this fixture")
        httpd = real_build_server(*args, snapshot_source=_StandInSource(),
                                  **kwargs)
        built.append(httpd)
        return httpd

    monkeypatch.setattr(serve_mod, "build_server", _capture)

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    session_root = tmp_path / "model-sessions"
    # THE LOCAL INSTALL, SELECTED EXPLICITLY (plan 034 T070; #1144 13.4, as
    # T007 batch H's addendum reads). With neither `--local` nor
    # `OPENDOX_INSTALL_MODE=local` the install is HOSTED, and a hosted install
    # with no issuer refuses (13.5) before `build_server` is ever reached. This
    # fixture drives the single-user entrypoint a student runs, so it says so,
    # and it scrubs every runtime setting first: a broker setting inherited
    # from the shell would be refused beside the local mode, by design.
    for name in runtime_config.SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    args = cli_mod.build_parser().parse_args([
        "generate-and-open",
        runtime_config.LOCAL_FLAG,
        "--repo-root", str(checkout),
        "--repository", "fixture-repo",
        "--source-revision", PINNED_REVISION,
        "--run-dir", str(tmp_path / "run"),
        "--actor", "brett",
        "--model-session-root", str(session_root),
        "--no-validate", "--no-open", "--no-serve",
    ])
    rc = cli_mod.cmd_generate_and_open(args, opener=lambda url: None)
    assert rc == 0, "the entrypoint did not complete"
    assert built, "the entrypoint never reached build_server"
    yield _handler_class(built[-1]), spawned, session_root


# --------------------------------------------------------------------------
# 2.1 — the declaration exists and DISCLOSES something
# --------------------------------------------------------------------------

def test_the_entrypoint_resolves_a_port_that_discloses_an_available_model(
        entrypoint_server):
    """§2.1. A server built by the entrypoint path resolves a port whose
    `catalog()` carries at least one AVAILABLE entry."""
    handler, spawned, _root = entrypoint_server
    port = handler._workbench_model_port(handler)
    assert port is not None, (
        "the entrypoint declared no model_port_factory: every model consumer's "
        "honest posture is an absent capability, so nothing on this surface can "
        "reach a provider at all")
    catalog = port.catalog()
    assert isinstance(catalog, doxbench_model.ModelCatalog), catalog
    available = [entry for entry in catalog.entries if entry.available]
    assert available, (
        "the entrypoint's port discloses no AVAILABLE model — an inert "
        "declaration that resolves, discloses nothing, and looks like a working "
        "install (the EMPTY_CATALOG default, doxbench_model.py:719)")
    assert spawned == [], "resolving the port must not start a harness child"


def test_resolving_the_port_starts_no_harness_child(entrypoint_server):
    """The child is started at the first TURN that needs one, never by the act
    of resolving — an editor-only session must spawn no model process."""
    handler, spawned, _root = entrypoint_server
    port = handler._workbench_model_port(handler)
    assert port is not None
    port.catalog()
    assert spawned == []
    assert port.started is False


# --------------------------------------------------------------------------
# 2.2a — ONE instance for the life of the process
# --------------------------------------------------------------------------

def test_two_resolutions_in_one_process_return_the_same_adapter(
        entrypoint_server):
    """§2.2a / the "A stateful adapter is resolved twice in one process"
    scenario. `_workbench_model_port` is called PER REQUEST (`serve.py:2162`,
    `:2700`) and `OmpHarnessBridge` is stateful (`_sessions`/`_selected`), so a
    per-request construction would break the one-session-per-document-thread
    correspondence BY CONSTRUCTION and restart a child on every call.

    IDENTITY, not equality: two equal-but-distinct bridges hold two disjoint
    session tables, which is the defect."""
    handler, spawned, _root = entrypoint_server
    first = handler._workbench_model_port(handler)
    second = handler._workbench_model_port(handler)
    assert first is not None and second is not None
    assert first is second, (
        "two requests resolved two DIFFERENT adapters: each holds its own "
        "harness sessions, so one document thread's context cannot survive its "
        "own second request")
    assert spawned == [], "no adapter child may be started by resolving, twice or once"


# --------------------------------------------------------------------------
# 2.2 — the three install-time inputs, and the ZERO-ARGUMENT factory
# --------------------------------------------------------------------------

def test_the_declared_factory_takes_no_arguments_and_memoizes(tmp_path):
    """`_workbench_model_port` calls `self.model_port_factory()` with NO
    arguments (`serve.py:1549`), so nothing about this adapter may become a
    per-request or per-turn input: the factory is what closes over the
    install-time declaration."""
    factory = install_mod.model_port_factory(tmp_path / "sessions")
    port = factory()
    assert isinstance(port, br.OmpHarnessBridge)
    assert factory() is port


def test_the_declared_launch_carries_a_provider_id_and_a_command(tmp_path):
    """The `LaunchConfig` shape D9 names, and the one the live fixture builds
    (`test_doxbench_bridge_live.py:145-146`): a `provider_id` and a `command`.
    `OmpHarnessBridge` cannot be built bare — `session_root` is keyword-only
    with no default — so all three inputs are declared install-time."""
    root = tmp_path / "sessions"
    launch = install_mod.harness_launch(root)
    assert launch.provider_id == install_mod.HARNESS_PROVIDER_ID
    assert launch.command == br.HARNESS_COMMAND
    argv = launch.argv()
    assert argv[0] == br.HARNESS_COMMAND
    assert str(root) in argv, argv


def test_the_declared_catalog_is_a_declaration_constant_with_an_available_entry():
    """The CATALOG is an install-time declaration constant, not a per-turn
    parameter — the idiom `knowledge_declaration` already uses."""
    catalog = install_mod.HARNESS_CATALOG
    assert isinstance(catalog, doxbench_model.ModelCatalog)
    assert [entry for entry in catalog.entries if entry.available]


def test_the_session_root_is_an_entrypoint_flag_the_adapter_actually_uses(
        entrypoint_server):
    """`session_root` is a CLI flag on the entrypoint, and the value reaches the
    adapter's own launch — which is where a harness child would run and write.
    Read off the bridge's recorded launch because that is the only place the
    consequence is observable without starting anything."""
    handler, _spawned, session_root = entrypoint_server
    port = handler._workbench_model_port(handler)
    assert port is not None
    assert port._launch.session_dir == session_root  # noqa: SLF001 - see docstring
    assert str(session_root) in port._launch.argv()  # noqa: SLF001


def test_the_session_root_defaults_beside_the_served_snapshot(tmp_path):
    """Defaulted next to the other path arguments: with no flag, the model
    session root sits beside the run directory's snapshot — a scratch directory
    this process owns, never the served checkout and never a corpus path."""
    snapshot = tmp_path / "run" / "snapshot.json"
    assert install_mod.session_root_beside(snapshot) == \
        tmp_path / "run" / install_mod.MODEL_SESSIONS_DIRNAME
