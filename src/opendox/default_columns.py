"""openDox's OWN defaults for the four column seams: the gate primitives, the
doxBench scope, kickoff and the cross-reference register (plan 034 T084;
#1144 4.3 as T007 batch G's addendum reads; RULED R1Q10 (a), openxFactory#656
comment `5850003126`).

WHAT THIS MODULE IS. `opendox.column_seams` declares four seams where openDox's
own verbs reached the consumer's columns by module name (`openxdox.gate_console`,
`openxdox.gate_routes`, `openxdox.doxbench_scope`, `openxdox.kickoff`,
`openxdox.register`). Each seam is a host's contribution or openDox's default,
and the entry points register the defaults below where no host has (R1Q3 (a)'s
pattern, `5817152735`). openXdox contributes its governed ones through the same
seams (T086). Each default is small and neutral, and it is new code, not
openXdox's modules relocated: R1Q10's option (b), the relocation, was not the
ruling.

WHAT EACH DEFAULT DOES, as the holder read R1Q10 (a) for T084 (relayed on
openxFactory#656's thread, 2026-10-02; Brett may overrule):

* `GATE`, the gate primitives. The VOCABULARY-FREE primitives are real code:
  the human-gate guard (`require_human_gate`, over `opendox.boundary`'s
  `HumanGate`), the clock and the stamp (`_utcnow`, `_stamp`), the records
  prefix (`_prefix`) and the session-ref target id (`ref_target_id`), the
  gateway `Provenance` with its surface and presence constants and
  `HTTP_CONSOLE_TOKEN`, `GateRefused`, the session action and artifact
  constants, and the first-edit gate builder chat's Save writes through
  (`first_edit_gate_factory`). The GOVERNED record functions, a gate-action
  record's build, validation and write, the demotion-receipt validator and the
  `GateConsole` facade, are NOT emulated: the gate-action record is a shape only
  openxFactory's pinned schema declares, and openDox writes no governed shape it
  does not own. With no host's gate registered they refuse, naming the seam and
  the call that registers one (4.2), as `GateRecordsNotRegistered`.
* `SCOPE`, the doxBench scope authority. `resolve_scope` projects a tile of the
  neutral snapshot (a group's members, a selection's files, a candidate's
  claiming groups' members), each path confined to the selected root by the
  registry seam's own `resolve_within`. A TILE'S OWN DOCUMENTS ARE EDITABLE
  (RULED by Brett Heap, openxFactory#656 comment `5961651355`, "Tile's own
  documents editable (Recommended)", superseding the holder's read-only
  reading): those are exactly the three sections above, as openXdox's own
  authority marks its owned sections, and the set is one named function,
  `editable_paths`. `is_live_session_ref` keeps the governed authority's logic, which is
  openDox's own session layer (`branch_session.live_session_branches`).
  `session_created_paths_for_scope` answers no path: which documents a session
  CREATED is known only from governed gate-action records, which this default
  neither writes nor reads.
* `KICKOFF`: no dispatched commission and no dispatched proposal, and no
  project register, so `/project-register.json` keeps today's structured
  "no project register" answer.
* `REGISTER`: a cross-reference register with no possibles.

NOTHING HERE NAMES THE CONSUMER OR THE PUBLISHER, at import time or in a body:
the standard library, `opendox.boundary`, `opendox.path_slug`,
`opendox.doxbench_threads` and `opendox.defaults` at import, and
`opendox.branch_session` and `opendox.projection_seams` inside the bodies that
need them, so `import opendox.default_columns` starts nothing.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from opendox import defaults
from opendox.column_seams import GATE_RECORDS_REFUSAL
from opendox.boundary import GATE_SIDE_EFFECT, BoundaryViolation, HumanGate, Refusal
from opendox.doxbench_scope_types import (
    ScopeConfinementError,
    ScopeDocument,
    ScopeKey,
    ScopeProjection,
    ScopeSection,
)
from opendox.doxbench_threads import THREAD_PREFIX
from opendox.path_slug import slug

__all__ = [
    "GATE",
    "GATE_RECORDS_REFUSAL",
    "GateRecordsNotRegistered",
    "GateRefused",
    "KICKOFF",
    "Provenance",
    "REGISTER",
    "SCOPE",
]


class _Registration:
    """One default, as a seam registration: a named object carrying the names
    its seam requires. `__name__` is what a refusal names it by."""

    def __init__(self, name: str, members: Mapping[str, Any]) -> None:
        self.__name__ = name
        for key, value in members.items():
            setattr(self, key, value)

    def __repr__(self) -> str:
        return f"<openDox default {self.__name__}>"


# ==========================================================================
# GATE — the vocabulary-free primitives, and refusals for the governed rest
# ==========================================================================

class GateRefused(Exception):
    """A gate action refused on a precondition. openDox's default raises it
    for a refusal of its own, and `GateRecordsNotRegistered` below for the
    governed functions it does not carry."""


class GateRecordsNotRegistered(GateRefused):
    """A governed gate function was asked for and no host's gate is
    registered: openDox's default carries none of them (see the module
    docstring)."""

    def __init__(self, what: str) -> None:
        super().__init__(f"{what}: {GATE_RECORDS_REFUSAL}")


def _governed(what: str):
    def refuse(*_args: Any, **_kwargs: Any):
        raise GateRecordsNotRegistered(what)

    refuse.__name__ = what.split(" ", 1)[0]
    refuse.__doc__ = (f"`{what}`, which openDox's default does not carry: "
                      "refused as `GateRecordsNotRegistered`.")
    return refuse


class _NoGateConsole:
    """`GateConsole`, which openDox's default does not carry: constructing it
    refuses as `GateRecordsNotRegistered`."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise GateRecordsNotRegistered("GateConsole")


#: The gateway SURFACES and the CONSOLE-PRESENCE proofs a provenance block may
#: name. The words are the gateway facts openDox's own entry points observe
#: (`cli.console_presence`, the console-token check), and nothing governs them
#: but this list.
SURFACE_HTTP = "http"
SURFACE_CLI = "cli"
SURFACES = (SURFACE_HTTP, SURFACE_CLI)
PRESENCE_CONSOLE_TOKEN = "console-token"
PRESENCE_TTY = "tty"
PRESENCE_DECLARED = "declared"
CONSOLE_PRESENCES = (PRESENCE_CONSOLE_TOKEN, PRESENCE_TTY, PRESENCE_DECLARED)


@dataclass(frozen=True)
class Provenance:
    """The gateway facts about one invocation: the surface it arrived on and
    how console presence was shown. A type, validated at construction, so a
    mapping a request body could carry is never a provenance."""

    surface: str
    console_presence: str

    def __post_init__(self) -> None:
        if self.surface not in SURFACES:
            raise GateRefused(
                f"unknown gateway surface {self.surface!r}: a provenance names "
                f"one of {', '.join(SURFACES)}")
        if self.console_presence not in CONSOLE_PRESENCES:
            raise GateRefused(
                f"unknown console-presence proof {self.console_presence!r}: a "
                f"provenance names one of {', '.join(CONSOLE_PRESENCES)}, and "
                "there is no value meaning 'presence was not shown'")

    def as_record(self) -> dict:
        return {"surface": self.surface, "console_presence": self.console_presence}


HTTP_CONSOLE_TOKEN = Provenance(SURFACE_HTTP, PRESENCE_CONSOLE_TOKEN)


def require_human_gate(gate: Any) -> HumanGate:
    """A `HumanGate` passes; anything else is REJECTED and REPORTED: appended to
    its own refusal ledger where it has one, then raised as a
    `BoundaryViolation` carrying the structured `Refusal`."""
    if isinstance(gate, HumanGate):
        return gate
    actor = (getattr(gate, "actor", None)
             or getattr(gate, "human_actor", None) or "non-human")
    refusal = Refusal(
        GATE_SIDE_EFFECT, str(actor), "<gate>",
        "a gate action requires a HumanGate constructed with an identified "
        "human actor; an OutputBoundary or agent path cannot invoke one")
    ledger = getattr(gate, "refusals", None)
    if isinstance(ledger, list):
        ledger.append(refusal)
    raise BoundaryViolation(refusal)


def _utcnow() -> str:
    """Wall-clock UTC, as a date-time: a gate action is a live event."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(at: str) -> str:
    """A filesystem-safe slug of a timestamp (its separators dropped)."""
    return re.sub(r"[^0-9A-Za-z]", "", at) or "unstamped"


def _prefix(records_dir: str) -> str:
    return records_dir if records_dir.endswith("/") else records_dir + "/"


def ref_target_id(ref: str) -> str:
    """The records-path segment for a session ref: the branch, slugged, so a
    hostile value can never traverse the records tree."""
    return slug(str(ref or "").replace("/", "-"))


def first_edit_gate_factory(actor: str, records_dir: str):
    """The worktree-rooted gate chat's Save writes through: the records tree
    and the thread-sidecar tree declared, and nothing else."""
    def build(worktree):
        return HumanGate(worktree, [records_dir, THREAD_PREFIX],
                         human_actor=actor, session_root=worktree)
    return build


GATE = _Registration("opendox.default_columns.GATE", {
    # the vocabulary-free primitives, as real code
    "GateRefused": GateRefused,
    "HumanGate": HumanGate,
    "Provenance": Provenance,
    "require_human_gate": require_human_gate,
    "ref_target_id": ref_target_id,
    "first_edit_gate_factory": first_edit_gate_factory,
    "_prefix": _prefix,
    "_stamp": _stamp,
    "_utcnow": _utcnow,
    "ACTION_ABANDON_SESSION": "abandon-session",
    "ACTION_CREATE_DOCUMENT": "create-document",
    "ACTION_EDIT_DOCUMENT": "edit-document",
    "ART_COMMIT": "commit",
    "DEFAULT_RECORDS_DIR": defaults.DEFAULT_RECORDS_DIR,
    "HTTP_CONSOLE_TOKEN": HTTP_CONSOLE_TOKEN,
    "PRESENCE_DECLARED": PRESENCE_DECLARED,
    "PRESENCE_TTY": PRESENCE_TTY,
    "SURFACE_CLI": SURFACE_CLI,
    # the governed rest, refused by name (4.2)
    "GateConsole": _NoGateConsole,
    "build_gate_action_record": _governed("build_gate_action_record"),
    "validate_gate_action_record": _governed("validate_gate_action_record"),
    "write_gate_action_record": _governed("write_gate_action_record"),
    "validate_demotion_execution_receipt": _governed(
        "validate_demotion_execution_receipt"),
})


# ==========================================================================
# SCOPE — a small, neutral projection of a tile, its own documents editable
# ==========================================================================

def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, (list, tuple)) else ()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _canonical(path: Any) -> str:
    """`path` if it is a canonical repository-relative POSIX path, or a
    `ScopeConfinementError`: a projection never carries a path it cannot
    name safely."""
    if (not isinstance(path, str) or not path or "\x00" in path or "\\" in path
            or path.startswith("/")):
        raise ScopeConfinementError(
            "scope paths must be non-empty repository-relative POSIX paths")
    parts = PurePosixPath(path).parts
    if PurePosixPath(path).as_posix() != path or ".." in parts or "." in parts:
        raise ScopeConfinementError(
            f"scope path {path!r} must use canonical repository-relative spelling")
    return path


def _section(key: str, label: str, note: str, paths: Iterable[Any], *,
             known: set[str], seen: set[str], root: Path,
             inherited: bool, owned: bool) -> ScopeSection:
    from opendox import projection_seams

    resolve_within = projection_seams.registry.current().resolve_within
    rows: list[ScopeDocument] = []
    for raw in paths:
        path = _canonical(raw)
        if path in seen:
            continue
        seen.add(path)
        resolved = path in known and resolve_within(root, path) is not None
        rows.append(ScopeDocument(id=path, path=path, resolved=resolved))
    return ScopeSection(key=key, label=label, note=note, inherited=inherited,
                        owned=owned, documents=tuple(rows))


def editable_paths(sections: Sequence[ScopeSection]) -> tuple[str, ...]:
    """The paths a projected tile lets a turn edit: THE TILE'S OWN DOCUMENTS.

    RULED by Brett Heap, openxFactory#656 comment `5961651355`, "Tile's own
    documents editable (Recommended)", which supersedes the holder's read-only
    reading of R1Q10 (a). A tile's own documents are the resolved rows of its
    OWNED sections, in order and once each, as openXdox's own authority derives
    its editable set from its owned sections. In openDox's default every
    section a tile projects is its own: a group's members, a selection's files
    and a candidate's claiming groups' members. Nothing outside them is
    editable, a row that does not resolve is not, and neither is a created path
    (this default records none). openDox's turn guard requires a turn's paths
    to be in scope AND editable (`doxbench_turns._require_in_scope_and_editable`),
    so a turn over a tile's own document passes it, and one over any other
    document is still refused. ONE named function, so the set is decided in
    one place."""
    editable: list[str] = []
    for section in sections:
        if not section.owned:
            continue
        for row in section.documents:
            if row.resolved and row.path not in editable:
                editable.append(row.path)
    return tuple(editable)


def resolve_scope(snapshot: Mapping[str, Any], key: ScopeKey, *,
                  source_root: Path, created_paths: Iterable[str] = ()
                  ) -> ScopeProjection | None:
    """One tile of the neutral snapshot, or None where the snapshot has no
    such tile.

    A group (`cluster`) projects its members, a selection (`staged`) its files,
    and a candidate (`possible`) the members of the groups that claim it. Each
    path is confined to `source_root` by the registry seam's own
    `resolve_within`. Each of those sections is the tile's OWN, so its
    resolved documents are editable (`editable_paths`, RULED `5961651355`),
    `active_document_candidates` are the documents the turn guard would
    accept, and there is no outline. A `created_paths` entry is confined and
    readable, never editable."""
    if not isinstance(snapshot, Mapping):
        return None
    if isinstance(created_paths, (str, bytes, bytearray)):
        raise ScopeConfinementError(
            "created_paths must be a collection of repository-relative paths")
    try:
        created = tuple(created_paths)
    except TypeError as error:
        raise ScopeConfinementError(
            "created_paths must be a collection of repository-relative paths"
        ) from error
    root = Path(source_root)
    known = {_text(_mapping(d).get("path")) for d in _sequence(snapshot.get("documents"))}
    groups = {_text(_mapping(g).get("id")): _mapping(g)
              for g in _sequence(snapshot.get("clusters"))}

    def members(group: Mapping[str, Any]) -> list[Any]:
        return [_mapping(edge).get("document")
                for edge in _sequence(group.get("document_edges"))]

    seen: set[str] = set()
    sections: list[ScopeSection] = []
    keywords: tuple[str, ...] = ()
    if key.tile_kind == "cluster":
        group = groups.get(key.tile_id)
        if group is None:
            return None
        title = _text(group.get("name")) or key.tile_id
        keywords = tuple(_text(t) for t in _sequence(group.get("topics")) if _text(t))
        sections.append(_section(
            "members", "group documents", "the group's own document edges",
            members(group), known=known, seen=seen, root=root, inherited=False,
            owned=True))
    elif key.tile_kind == "staged":
        selection = next((_mapping(s) for s in _sequence(snapshot.get("staged_topics"))
                          if _text(_mapping(s).get("staging_id")) == key.tile_id), None)
        if selection is None:
            return None
        title = key.tile_id
        sections.append(_section(
            "files", "selection files", "the documents this selection names",
            _sequence(selection.get("files")), known=known, seen=seen, root=root,
            inherited=False, owned=True))
    elif key.tile_kind == "possible":
        candidate = next((_mapping(p) for p in _sequence(snapshot.get("possibles"))
                          if _text(_mapping(p).get("id")) == key.tile_id), None)
        if candidate is None:
            return None
        title = _text(candidate.get("title")) or key.tile_id
        claimed = [path for group_id in _sequence(candidate.get("claiming_clusters"))
                   for path in members(groups.get(_text(group_id), {}))]
        sections.append(_section(
            "claiming", "documents of the claiming groups",
            "membership inferred from the groups that claim this candidate",
            claimed, known=known, seen=seen, root=root, inherited=True,
            owned=True))
    else:
        return None
    context = [row.path for section in sections for row in section.documents
               if row.resolved]
    for raw in created:
        path = _canonical(raw)
        if path not in context:
            context.append(path)
    revision = _text(_mapping(snapshot.get("generation")).get("source_revision"))
    editable = editable_paths(sections)
    return ScopeProjection(
        key=key, title=title, keywords=keywords, source_revision=revision,
        sections=tuple(sections), context_paths=tuple(context),
        editable_paths=editable, outline_path=None,
        # what the turn guard would accept: in scope AND editable
        active_document_candidates=tuple(p for p in context if p in editable))


def _normalize_ref(ref: Any) -> str:
    from opendox import projection_seams

    text = str(ref).strip() if ref is not None else ""
    return text or projection_seams.registry.current().DEFAULT_REF


def is_live_session_ref(registry: Any, key: ScopeKey, *, repository: str,
                        ref: str) -> bool:
    """Whether `ref` is one of THIS tile's live session branches, by openDox's
    own session layer. A declared session refusal (a cross-tile collision, an
    ambiguous family) is "not this tile's session"; any other failure is the
    caller's to handle."""
    from opendox import branch_session

    kinds = {"cluster": branch_session.CLUSTER,
             "possible": branch_session.POSSIBLE,
             "staged": branch_session.STAGED_TOPIC}
    scope_kind = kinds.get(key.tile_kind)
    if scope_kind is None or not ref or registry is None:
        return False
    try:
        tile = branch_session.Tile(scope_kind, key.tile_id)
        live = branch_session.live_session_branches(registry, repository, tile)
    except branch_session.SessionRefused:
        return False
    wanted = _normalize_ref(ref)
    return any(wanted == _normalize_ref(branch) for branch in live)


def session_created_paths_for_scope(registry: Any, key: ScopeKey, *,
                                    repository: str, ref: str,
                                    source_root: Path | str) -> tuple[str, ...]:
    """No path: which documents a session created is known only from the
    governed gate-action records, which this default neither writes nor
    reads."""
    return ()


SCOPE = _Registration("opendox.default_columns.SCOPE", {
    "resolve_scope": resolve_scope,
    "is_live_session_ref": is_live_session_ref,
    "session_created_paths_for_scope": session_created_paths_for_scope,
})


# ==========================================================================
# KICKOFF and REGISTER — nothing dispatched, no register
# ==========================================================================

def dispatched_commission_rows(records_root: Any, verb: str) -> list:
    """No dispatched commission: openDox commissions no workflow."""
    return []


def dispatched_commissions(records_root: Any, verb: str) -> dict:
    """No dispatched commission, by target."""
    return {}


def dispatched_propose_topics(records_root: Any) -> set:
    """No dispatched proposal."""
    return set()


def discover_project_register(root: Any) -> None:
    """No project register: openDox's own corpus declares none."""
    return None


KICKOFF = _Registration("opendox.default_columns.KICKOFF", {
    "dispatched_commission_rows": dispatched_commission_rows,
    "dispatched_commissions": dispatched_commissions,
    "dispatched_propose_topics": dispatched_propose_topics,
    "discover_project_register": discover_project_register,
})


class _NoPossibles:
    def possibles(self) -> tuple:
        return ()


class CrossReferenceIndexAdapter:
    """A cross-reference register with no possibles: openDox's own corpus
    declares none."""

    @classmethod
    def discover(cls, root: Any) -> _NoPossibles:
        return _NoPossibles()


REGISTER = _Registration("opendox.default_columns.REGISTER", {
    "CrossReferenceIndexAdapter": CrossReferenceIndexAdapter,
})
