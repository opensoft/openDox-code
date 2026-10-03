"""openDox's own defaults for the two doxBench seams: plan 034's T085 (#1144's
4.3 as T007's batch G amends it, and 16.4 in part; R1Q10 (a) and R1Q12 (a),
`openxFactory#656` comment `5850003126`).

T027 made two reaches into openxFactory seams that refuse, naming themselves,
when nothing is registered: the doxBench schema validators
(`serve_wire.register_doxbench_validators`) and the status-exemption rail
(`doxbench_packet.register_status_exemption`). Standalone, nothing registered
either, so a standalone server's `GET /workbench/model-catalog` answered `500
catalog_unavailable` (measured at openDox-code `047bb4fa`). T085 gives each seam
an openDox default, `opendox.doxbench_defaults`, which the four entry points
register where no host has. This file holds:

1. THE DEFAULTS THEMSELVES. The validators are `opendox.validator`'s own over
   its packaged copies of the two doxBench schemas, one per wire kind, and they
   meet the jsonschema-shaped contract the seam's readers in `serve_workbench`
   read: openDox-spec's own examples conform, its negative ones do not, and
   the buffers-floor reader tells the floor from any other fault. The rail
   exempts nothing, and reports a document's own `Status:` line, raw.
2. THE SEAM RULES, for both seams. Nothing registered still refuses, naming
   the seam and both calls (4.2). A default registers only where nothing is
   registered. A host registered first is kept. A host registered after the
   default and before it is read replaces it. After a read, a host is
   refused, and the default stays. A malformed default is refused anyway.
3. THE ENTRY POINTS. `cli.build_parser()`, `cli.main()`,
   `serve.build_server()` and `serve.main()` each register both defaults, and
   each keeps a host registered first. Each runs in a fresh interpreter, so
   no other case's registrations reach it.
4. THE FALSIFIER: THE SERVED CATALOG ROUTE ANSWERS STANDALONE. A
   `python -m opendox.cli generate-and-open` child and a `python -m
   opendox.serve` child, with neither sibling importable
   (`tests/standalone_child.py`), each answer `GET /workbench/model-catalog`
   200 with an envelope openDox's own validator accepts. What that catalog
   OFFERS is 16.4's and T081's: at this task's head it is the harness
   declaration, `omp-local`, declared available, and T081 asserts that no
   entry is available with no model configured. Plan 034's T085 box is ticked
   when both hold, at T081's landing (the holder's ruling, 2026-10-02).

Every in-process case starts with nothing registered at either seam, and puts
back exactly what it found, records included. Against a tree WITHOUT T085,
`opendox.doxbench_defaults` does not import and each case fails on its own
assertion rather than the file failing to collect, which keeps the red run
legible.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import http.client
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from opendox import contracts
from opendox import doxbench_model
from opendox import doxbench_packet as pk
from opendox import serve_wire
from opendox import validator as own
from opendox.serve_workbench import WorkbenchRoutes
from session_fixtures import GATE_TEST_PRINCIPALS
from standalone_child import Child, fresh_repository

try:
    from opendox import doxbench_defaults as defaults
except ImportError:     # a tree without T085: each case fails on its own line
    defaults = None

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "tests" / "fixtures" / "spec-examples"
PLAIN = ROOT / "tests" / "fixtures" / "plain-documents"

#: The doxBench wire kinds, as `serve_wire` spells them.
WIRE_KINDS = (serve_wire.DOXBENCH_MODEL_CATALOG_KIND,
              serve_wire.DOXBENCH_CHAT_TURN_V2_KIND,
              serve_wire.DOXBENCH_CHAT_TURN_V2_SUCCESS_KIND,
              serve_wire.DOXBENCH_CHAT_TURN_V2_FAILURE_KIND)

#: The packaged copies the four kinds are read from (R1Q12 (a)).
CHAT_COPIES = ("xfactory-workbench-chat-turn", "xfactory-workbench-model-catalog")

#: Each seam's slots and calls, read through `getattr` so that against a tree
#: without T085 each case fails on its own assertion.
SEAMS = {
    "validators": dict(
        module=serve_wire,
        slots=("_doxbench_validators_factory", "_doxbench_validators_is_default",
               "_doxbench_validators_default_read"),
        register="register_doxbench_validators",
        register_default="register_default_doxbench_validators",
        unregister="unregister_doxbench_validators",
        registered="doxbench_validators_registered",
        read=lambda: serve_wire.default_doxbench_validators(),
        not_registered=serve_wire.DoxbenchValidatorsNotRegistered,
        already=serve_wire.DoxbenchValidatorsAlreadyRegistered,
        default=lambda: own.doxbench_validators,
        host=lambda: (lambda: {"stand-in": True}),
        malformed="not callable"),
    "rail": dict(
        module=pk,
        slots=("_status_exemption_rail", "_status_exemption_is_default",
               "_status_exemption_default_read"),
        register="register_status_exemption",
        register_default="register_default_status_exemption",
        unregister="unregister_status_exemption",
        registered="status_exemption_registered",
        read=lambda: pk._status_exemption(),
        not_registered=pk.StatusExemptionNotRegistered,
        already=pk.StatusExemptionAlreadyRegistered,
        default=lambda: defaults.NO_STATUS_EXEMPTION,
        host=lambda: _HostRail(),
        malformed=object()),
}


class _HostRail:
    """A host's stand-in rail, exempting everything."""

    def lifecycle_status(self, text):
        return "host"

    def is_compression_exempt(self, text):
        return True


@pytest.fixture(autouse=True)
def _empty_seams():
    """Nothing registered at either seam, and each PUT BACK exactly, records
    included, so an entry point's default is never handed back as a host's."""
    held = {name: [getattr(seam["module"], slot, None) for slot in seam["slots"]]
            for name, seam in SEAMS.items()}
    for seam in SEAMS.values():
        getattr(seam["module"], seam["unregister"])()
    yield
    for name, seam in SEAMS.items():
        for slot, value in zip(seam["slots"], held[name]):
            if hasattr(seam["module"], slot):
                setattr(seam["module"], slot, value)


def _example(name: str):
    return yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1 — the defaults themselves
# ---------------------------------------------------------------------------

def test_the_validators_are_openDoxs_own_one_per_wire_kind() -> None:
    assert own.DOXBENCH_KINDS == tuple(sorted(WIRE_KINDS))
    built = own.doxbench_validators()
    assert sorted(built) == sorted(WIRE_KINDS)
    pins = contracts.record()
    for kind, validator in built.items():
        assert isinstance(validator, own.KindValidator), kind
        assert validator.copy_id in CHAT_COPIES, kind
        assert validator.digest == pins.copy(validator.copy_id).sha256, kind
    assert own.doxbench_validators() is not built, "a fresh dict per call"


@pytest.mark.parametrize("name", sorted(
    path.name for path in EXAMPLES.glob("workbench-*.example.yaml")))
def test_openDox_specs_own_examples_conform_through_the_seams_reader(name) -> None:
    """The reader the model routes call (`_doxbench_wire_conforms`) accepts
    every doxBench example openDox-spec ships, judged by openDox's own
    validators."""
    instance = _example(name)
    assert WorkbenchRoutes._doxbench_wire_conforms(
        own.doxbench_validators(), instance["kind"], instance), name


def test_a_malformed_envelope_does_not_conform_and_an_unknown_kind_has_no_verdict() -> None:
    validators = own.doxbench_validators()
    catalog = doxbench_model.catalog_wire_envelope(doxbench_model.EMPTY_CATALOG)
    assert WorkbenchRoutes._doxbench_wire_conforms(
        validators, serve_wire.DOXBENCH_MODEL_CATALOG_KIND, catalog)
    assert not WorkbenchRoutes._doxbench_wire_conforms(
        validators, serve_wire.DOXBENCH_MODEL_CATALOG_KIND, {**catalog, "models": "none"})
    assert not WorkbenchRoutes._doxbench_wire_conforms(
        validators, "ideation-workbench", {"kind": "ideation-workbench"})


def test_the_buffers_floor_reader_reads_openDoxs_violations() -> None:
    """`_doxbench_violation_beside_the_buffers_floor` reads a violation's
    `validator` keyword and `absolute_path`. Over openDox's validators, a
    request whose only fault is an empty `buffers` reads as the floor alone,
    and one with a second fault does not."""
    validators = own.doxbench_validators()
    kind = serve_wire.DOXBENCH_CHAT_TURN_V2_KIND
    request = _example("workbench-chat-turn-v2-loaded-set.example.yaml")
    floor_only = {**request, "buffers": []}
    assert not WorkbenchRoutes._doxbench_wire_conforms(validators, kind, floor_only)
    assert WorkbenchRoutes._doxbench_violation_beside_the_buffers_floor(
        validators, kind, floor_only) is False
    assert WorkbenchRoutes._doxbench_violation_beside_the_buffers_floor(
        validators, kind, {**floor_only, "client_turn_id": 7}) is True


def test_the_default_rail_exempts_nothing() -> None:
    """There is no status exemption by default (batch G's addendum to 4.3),
    whatever the document's status says."""
    rail = defaults.NO_STATUS_EXEMPTION
    for status in ("ratified", "approved", "standard", "draft"):
        assert rail.is_compression_exempt(f"# A doc\n\nStatus: {status}\n") is False
    assert rail.EXEMPT_STATUSES == frozenset()


def test_the_default_rail_reports_a_documents_own_status_raw() -> None:
    """So the packet's label (`Status: <raw>`, or `no Status: header`) stays
    true of the document."""
    rail = defaults.NO_STATUS_EXEMPTION
    assert rail.lifecycle_status("# T\n\nStatus: ratified (by a change)  \n") == \
        "ratified (by a change)"
    assert rail.lifecycle_status("# T\r\nStatus: draft\r\n") == "draft"
    assert rail.lifecycle_status("# T\rStatus: draft\r") == "draft"
    assert rail.lifecycle_status("# A doc with no status\n\nbody\n") is None
    assert rail.lifecycle_status("x\n" * 15 + "Status: late\n") is None
    assert rail.lifecycle_status("x\n" * 14 + "Status: last\n") == "last"
    # only CR, LF and CRLF end a line, so a form feed or U+2028 does not
    # start one
    assert rail.lifecycle_status("# T\fStatus: hidden\n") is None
    assert rail.lifecycle_status("# T Status: hidden\n") is None
    assert rail.lifecycle_status(None) is None


def test_the_assembler_marks_every_source_with_the_default_rail() -> None:
    pk.register_default_status_exemption(defaults.NO_STATUS_EXEMPTION)
    sources = [
        pk.PacketSource(ref="notes/a.md", kind=pk.SOURCE_EVIDENCE,
                        text="Status: ratified\n\nbody\n", status=None,
                        compression_exempt=True),
        pk.PacketSource(ref="notes/b.md", kind=pk.SOURCE_EVIDENCE,
                        text="no header\n", status="stale", compression_exempt=True),
    ]
    marked = pk.exemption_rail(sources)
    assert [(s.status, s.compression_exempt) for s in marked] == [
        ("ratified", False), (None, False)]
    assert pk.EXEMPT_STATUSES == frozenset()


# ---------------------------------------------------------------------------
# 2 — the seam rules, for both seams
# ---------------------------------------------------------------------------

def _call(seam, name, *args):
    return getattr(seam["module"], seam[name])(*args)


def _held(seam):
    return [getattr(seam["module"], slot) for slot in seam["slots"]]


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_nothing_registered_refuses_naming_the_seam_and_both_calls(name) -> None:
    seam = SEAMS[name]
    assert _call(seam, "registered") is False
    with pytest.raises(seam["not_registered"]) as refused:
        seam["read"]()
    text = str(refused.value)
    assert "opendox.doxbench_defaults.register_defaults()" in text
    assert f"{seam['module'].__name__}.{seam['register']}(" in text
    for entry_point in ("cli.build_parser()", "cli.main()", "serve.build_server()",
                        "serve.main()"):
        assert entry_point in text, entry_point


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_register_defaults_registers_each_default_only_where_nothing_is(name) -> None:
    seam = SEAMS[name]
    defaults.register_defaults()
    assert _held(seam) == [seam["default"](), True, False]
    defaults.register_defaults()
    assert _held(seam) == [seam["default"](), True, False], "a second call is a no-op"
    assert _call(seam, "registered") is True


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_a_host_registered_first_is_kept(name) -> None:
    seam = SEAMS[name]
    host = seam["host"]()
    _call(seam, "register", host)
    defaults.register_defaults()
    assert _held(seam) == [host, False, False]


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_a_host_replaces_the_default_until_it_is_read(name) -> None:
    seam = SEAMS[name]
    defaults.register_defaults()
    host = seam["host"]()
    assert _call(seam, "register", host) is host
    assert _held(seam) == [host, False, False]
    assert _call(seam, "register", host) is host, "the same host again is a no-op"


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_after_the_default_is_read_a_host_is_refused_and_the_default_stays(name) -> None:
    seam = SEAMS[name]
    defaults.register_defaults()
    seam["read"]()
    assert _held(seam) == [seam["default"](), True, True]
    with pytest.raises(seam["already"], match=r"R1Q3 \(ii\)"):
        _call(seam, "register", seam["host"]())
    assert _held(seam) == [seam["default"](), True, True]
    _call(seam, "unregister")
    assert _held(seam) == [None, False, False]


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_a_second_host_over_a_host_is_refused(name) -> None:
    seam = SEAMS[name]
    first = seam["host"]()
    _call(seam, "register", first)
    with pytest.raises(seam["already"]):
        _call(seam, "register", seam["host"]())
    assert _held(seam)[0] is first


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_a_malformed_default_is_refused_whether_or_not_anything_is_registered(name) -> None:
    seam = SEAMS[name]
    with pytest.raises(TypeError, match="openDox's own"):
        _call(seam, "register_default", seam["malformed"])
    _call(seam, "register", seam["host"]())
    with pytest.raises(TypeError, match="openDox's own"):
        _call(seam, "register_default", seam["malformed"])


def test_the_registered_default_validators_answer_through_the_seam() -> None:
    defaults.register_defaults()
    answered = serve_wire.default_doxbench_validators()
    assert sorted(answered) == sorted(WIRE_KINDS)
    assert all(validator.copy_id in CHAT_COPIES for validator in answered.values())


# ---------------------------------------------------------------------------
# 3 — the entry points register both, and keep a host's
# ---------------------------------------------------------------------------

_ENTRY_POINT = textwrap.dedent("""
    import json, sys
    from pathlib import Path
    from opendox import doxbench_defaults, doxbench_packet, serve_wire, validator
    entry, host_first = sys.argv[1], sys.argv[2] == "host"
    host_factory = lambda: {}
    class HostRail:
        def lifecycle_status(self, text): return None
        def is_compression_exempt(self, text): return True
    host_rail = HostRail()
    if host_first:
        serve_wire.register_doxbench_validators(host_factory)
        doxbench_packet.register_status_exemption(host_rail)
    from opendox import cli, serve
    if entry == "cli.build_parser":
        cli.build_parser()
    elif entry in ("cli.main", "serve.main"):
        try:
            (cli.main if entry == "cli.main" else serve.main)(["--help"])
        except SystemExit:
            pass
    elif entry == "serve.build_server":
        tmp = Path(sys.argv[3])
        (tmp / "web").mkdir()
        (tmp / "snapshot.json").write_text("{}")
        serve.build_server(tmp / "web", tmp / "snapshot.json", tmp, port=0).server_close()
    factory = serve_wire._doxbench_validators_factory
    rail = doxbench_packet._status_exemption_rail
    print(json.dumps({
        "validators": ("host" if factory is host_factory else
                       "default" if factory is validator.doxbench_validators else repr(factory)),
        "validators_is_default": serve_wire._doxbench_validators_is_default,
        "rail": ("host" if rail is host_rail else
                 "default" if rail is doxbench_defaults.NO_STATUS_EXEMPTION else repr(rail)),
        "rail_is_default": doxbench_packet._status_exemption_is_default,
    }))
    """)

ENTRY_POINTS = ("cli.build_parser", "cli.main", "serve.build_server", "serve.main")


def _entry_point(tmp_path: Path, entry: str, host_first: bool) -> dict:
    done = subprocess.run(
        [sys.executable, "-c", _ENTRY_POINT, entry, "host" if host_first else "none",
         str(tmp_path)],
        capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_each_entry_point_registers_both_defaults_where_no_host_has(tmp_path, entry) -> None:
    assert _entry_point(tmp_path, entry, host_first=False) == {
        "validators": "default", "validators_is_default": True,
        "rail": "default", "rail_is_default": True}


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_each_entry_point_keeps_a_host_registered_first(tmp_path, entry) -> None:
    assert _entry_point(tmp_path, entry, host_first=True) == {
        "validators": "host", "validators_is_default": False,
        "rail": "host", "rail_is_default": False}


# ---------------------------------------------------------------------------
# 4 — THE FALSIFIER: the served catalog route answers standalone
# ---------------------------------------------------------------------------

_URL = re.compile(r"(http://([0-9.]+):([0-9]+))/index\.html$")


#: The console's human: one of the principals this suite declares
#: (`session_fixtures.GATE_TEST_PRINCIPALS`, the `XF_GATE_PRINCIPALS` roster the
#: child inherits), claimed with `--actor`, so the served console resolves it
#: and offers its session routes.
ACTOR = "tester"


def _repository(tmp_path: Path) -> Path:
    """T050's fixture in a fresh repository (#1144's preamble)."""
    return fresh_repository(PLAIN, tmp_path)


def _get(base: tuple[str, int], path: str, headers: dict | None = None):
    connection = http.client.HTTPConnection(*base, timeout=30)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def served_catalog(child: Child) -> dict:
    """The served model catalog, read as the chat rail reads it: the console
    token from `/capabilities`, then `GET /workbench/model-catalog`. Asserts
    the route ANSWERS, with an envelope openDox's own validator accepts."""
    assert ACTOR in GATE_TEST_PRINCIPALS
    match = child.wait_for_line(_URL)
    base = (match.group(2), int(match.group(3)))
    status, body = _get(base, "/capabilities")
    assert status == 200, status
    capabilities = json.loads(body)
    assert capabilities["actions"]["session"] is True, capabilities
    status, body = _get(base, "/workbench/model-catalog",
                        {"X-XF-Console-Token": capabilities["console_token"]})
    assert status == 200, (status, body)
    envelope = json.loads(body)
    assert envelope["kind"] == serve_wire.DOXBENCH_MODEL_CATALOG_KIND
    assert own.validate(envelope) == [], own.report(own.validate(envelope))
    assert child.interrupt() == 0, child.stderr_text()
    assert child.refused() == [], child.refused()
    return envelope


def test_the_served_catalog_route_answers_from_generate_and_open(tmp_path) -> None:
    """`python -m opendox.cli generate-and-open`, the documented command, with
    neither sibling importable. At `047bb4fa` it answered `500
    catalog_unavailable`."""
    # `--local`: the single-user install. Since plan 034 T070 an unflagged
    # `generate-and-open` is HOSTED, and with no issuer it refuses (13.5)
    # before it serves anything.
    child = Child(tmp_path, "opendox.cli", "generate-and-open", "--local",
                  "--repo-root", str(_repository(tmp_path)), "--repository", "fixture",
                  "--no-open", "--port", "0", "--run-dir", str(tmp_path / "run"),
                  "--actor", ACTOR)
    try:
        served_catalog(child)
    finally:
        child.kill()


def test_the_served_catalog_route_answers_from_serve_main(tmp_path) -> None:
    """The server's own entry point, over a snapshot `generate` wrote."""
    repo = _repository(tmp_path)
    out = tmp_path / "out" / "snapshot.json"
    generated = Child(tmp_path, "opendox.cli", "generate", "--repo-root", str(repo),
                      "--repository", "fixture", "--output", str(out))
    assert generated.wait() == 0, generated.stderr_text()
    child = Child(tmp_path, "opendox.serve", "--snapshot", str(out),
                  "--checkout-root", str(repo), "--port", "0", "--actor", ACTOR)
    try:
        served_catalog(child)
    finally:
        child.kill()
