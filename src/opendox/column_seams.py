"""THE CONSUMER COLUMNS' SEAMS: the gate primitives, the doxBench scope,
kickoff and the cross-reference register. Each is a host's contribution or
openDox's own default, held for late resolution (plan 034 T084; #1144 4.3, as
T007 batch G's and batch L's addenda read).

WHY THIS FILE EXISTS. #1144's 4.3: *"Route EVERY deferred reach through a seam
the product declares. None stays late-bound by name."* After phase 2, openDox's
own verbs still reached four mechanisms of openXdox's columns by module name:
the gate console (`branch_session` and `cli` through `consumer_reach`'s late
stand-in, and `serve_workbench`'s model approval and chat Save by deferred
imports), the doxBench scope authority (`serve_workbench`'s thread, chat-turn
and document-abstract routes), kickoff (`branch_session`'s proposal state and
`serve_project`'s register projection) and the cross-reference register
(`branch_session`'s pick fallbacks). With openXdox absent, which is the normal
state of a neutral openDox, each of those raised from inside a function, and
three of them ended a request with a dropped connection (batch L). This module
declares a seam for each, in `projection_seams`' discipline (the class is the
same one, `projection_seams._Seam`, naming this module).

R1Q10 (a) (`openxFactory#656` comment `5850003126`, in R-G3's pattern):
openDox grows a small neutral default for each, `opendox.default_columns`, and
openXdox contributes its governed one through the same seam (T086). What each
default does, and the holder's reading behind it, is that module's docstring.

THE ENTRY POINTS REGISTER THE DEFAULTS WHERE NO HOST HAS (R1Q3 (a), comment
`5817152735`). `cli.build_parser()`, `cli.main()`, `serve.build_server()` and
`serve.main()` call `register_defaults()`, beside `projection_seams`'. So a
process that runs none of them still meets `SeamNotRegistered`, naming the
seam and the call (4.2); a host registration made before a default has been
read replaces it; one made after is refused (`SeamAlreadyRegistered`); and the
same registration again is a no-op. These are `projection_seams`' exception
classes, so a verb that reports one projection-seam refusal in a clause reports
these in the same one.

THE FOUR SEAMS, AND WHAT A REGISTRATION CARRIES. Each is a module, or any
object, carrying the names below. openXdox's modules carry them as they stand,
except the gate's: `first_edit_gate_factory` is `gate_routes`', so openXdox's
gate registration is `gate_console` with that one name beside it.

* `gate`: `GATE_CALLABLES` and `GATE_VALUES`, every gate-console name openDox
  reads. ONE registration for the whole family, because the names agree with
  each other: a record builder checks a `Provenance` of its own type, and a
  caller catches its own `GateRefused`.
* `scope`: `SCOPE_CALLABLES`, the scope authority. The scope VALUE types are
  openDox's own (`opendox.doxbench_scope_types`) and are no seam.
* `kickoff`: `KICKOFF_CALLABLES`, the dispatched commissions and the project
  register's discovery.
* `register`: `REGISTER_CALLABLES`, the cross-reference register's adapter.

`gate_records_writable()` answers whether a HOST's gate is registered, so the
model-intake surface can decline to start a flow whose approval openDox's
default would refuse (plan 034 T084, a holder reading under batch G and R1Q10
(a) that Brett may overrule).

IMPORT WEIGHT: `opendox.projection_seams` only, which is stdlib-only, so this
module names no sibling in an import. `register_defaults()` imports
`opendox.default_columns` when it is CALLED.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

from opendox import projection_seams
from opendox.projection_seams import (
    ProjectionSeamError,
    SeamAlreadyRegistered,
    SeamNotRegistered,
)

__all__ = [
    "GATE_CALLABLES",
    "GATE_VALUES",
    "KICKOFF_CALLABLES",
    "ProjectionSeamError",
    "REGISTER_CALLABLES",
    "SCOPE_CALLABLES",
    "SeamAlreadyRegistered",
    "SeamNotRegistered",
    "gate",
    "gate_records_writable",
    "kickoff",
    "register",
    "register_defaults",
    "scope",
]

_MODULE = "opendox.column_seams"

#: What a gate registration must carry as callables: the human-gate guard and
#: the types it works with, the record functions, the session-ref target id,
#: the first-edit gate builder chat's Save writes through, and the clock, the
#: stamp and the records prefix the session layer composes with them.
GATE_CALLABLES: tuple[str, ...] = (
    "GateConsole", "GateRefused", "HumanGate", "Provenance",
    "build_gate_action_record", "validate_gate_action_record",
    "write_gate_action_record", "validate_demotion_execution_receipt",
    "require_human_gate", "ref_target_id", "first_edit_gate_factory",
    "_prefix", "_stamp", "_utcnow")

#: ...and as values: the session actions and the commit artifact, the default
#: records prefix, the HTTP console's provenance, and the CLI's surface and
#: presence proofs.
GATE_VALUES: tuple[str, ...] = (
    "ACTION_ABANDON_SESSION", "ACTION_CREATE_DOCUMENT", "ACTION_EDIT_DOCUMENT",
    "ART_COMMIT", "DEFAULT_RECORDS_DIR", "HTTP_CONSOLE_TOKEN",
    "PRESENCE_DECLARED", "PRESENCE_TTY", "SURFACE_CLI")

#: What a scope registration must carry.
SCOPE_CALLABLES: tuple[str, ...] = (
    "resolve_scope", "is_live_session_ref", "session_created_paths_for_scope")

#: What a kickoff registration must carry.
KICKOFF_CALLABLES: tuple[str, ...] = (
    "dispatched_commission_rows", "dispatched_commissions",
    "dispatched_propose_topics", "discover_project_register")

#: What a cross-reference register registration must carry.
REGISTER_CALLABLES: tuple[str, ...] = ("CrossReferenceIndexAdapter",)

gate = projection_seams._Seam(
    "gate", what="gate primitives", callables=GATE_CALLABLES,
    values=GATE_VALUES, default="opendox.default_columns.GATE",
    consequence="no gate action can be guarded, stamped or recorded",
    module=_MODULE)

scope = projection_seams._Seam(
    "scope", what="doxBench scope authority", callables=SCOPE_CALLABLES,
    default="opendox.default_columns.SCOPE",
    consequence="no workbench tile can be resolved to its documents",
    module=_MODULE)

kickoff = projection_seams._Seam(
    "kickoff", what="commission reader", callables=KICKOFF_CALLABLES,
    default="opendox.default_columns.KICKOFF",
    consequence="no dispatched commission, proposal or project register can "
                "be read",
    module=_MODULE)

register = projection_seams._Seam(
    "register", what="cross-reference register", callables=REGISTER_CALLABLES,
    default="opendox.default_columns.REGISTER",
    consequence="no cross-reference register can be read",
    module=_MODULE)


def register_defaults() -> None:
    """Register openDox's OWN default at each of the four seams, where no host
    has registered one (R1Q10 (a), in R1Q3 (a)'s pattern). It registers
    nothing over a host and reads nothing, so a host registration made
    afterwards, and before any consumer reads a default, still replaces it.
    Importing this module registers nothing."""
    from opendox import default_columns

    gate.register_default(default_columns.GATE)
    scope.register_default(default_columns.SCOPE)
    kickoff.register_default(default_columns.KICKOFF)
    register.register_default(default_columns.REGISTER)


def gate_records_writable() -> bool:
    """Whether a HOST's gate is registered, which is what can write a governed
    gate-action record: openDox's own default writes none. Answers without
    reading the seam, so it closes no default's window."""
    return gate.holds_a_hosts()
