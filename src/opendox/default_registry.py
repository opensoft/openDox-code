"""openDox's OWN snapshot registry and snapshot source: the registry seam's
default (plan 034's T055; R1Q10 (a), `openxFactory#656` comment `5850003126`).

WHAT IT IS. The registration `projection_seams.registry` holds where no host
has contributed one. It carries what openDox's own code reads off a registry:
the entry, registry and source types, the key and containment rules, and the
refresh bindings. The entry points register it (R1Q3 (a)'s pattern), and a
host contributes its governed registry through the same seam (openXdox's
`snapshot_registry`, T059).

ONE REGISTRY, KEYED `(repository, ref)`, WITH `ref` DEFAULTING TO `main`. An
entry is one snapshot on disk and the facts a viewer needs to trust it: its
repository and ref, the `source_revision` it projects, its `generated_at`, and
the ROOT its `/source/` pass-through is confined to. A session is an entry at a
session ref whose root is the session's worktree (`branch_session`), and its
owner and base survive a re-registration.

WHAT IT DOES NOT DO, AND SAYS SO. It reads NO DATA SOURCE and NO INDEX. A
published index is a governed contract (`ideation-dashboard-snapshot-index`),
and openDox has no index kind of its own (plan 034's T053 records that), so
this registry refuses a declared data source and a declared local index rather
than ignoring either, naming the seam a host registers through. The same goes
for aggregates: `compose_view` composes nothing. So standalone, the server
serves the one snapshot it was handed, and a regenerate rewrites it.

THE LOCAL REGENERATE GOES THROUGH THE SEAMS. `SnapshotSource.refresh` re-runs
the REGISTERED generator (`generator_seam.generate`, looked up on each call)
against the entry's own root, and writes through the REGISTERED writer
(`projection_seams.writer`), inside the interactivity boundary. So the server
and the generate verbs write with the same generator and the same writer.

THE CONTAINMENT RULE. `resolve_within` is the rule `/source/` has always been
confined by, as openDox states it: no absolute path, no NUL, no escape of the
root (`..`, percent-encoded `..`, a symlink), no dot-directory ever, and a
dot-file only with an extension a document carries. The dot-directory half is
where credentials live (`.git/config` carries a remote's token, T092's defect
10), so nothing below a dot-directory is ever served.

IMPORT WEIGHT. `opendox.boundary`, `opendox.defaults`, `opendox.generator_seam`,
`opendox.projection_seams` and the standard library. So this module imports
with no extra installed and no sibling present.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import contextlib
import json
import threading
import urllib.parse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from opendox import defaults, generator_seam, projection_seams
from opendox.boundary import OutputBoundary

__all__ = [
    "BINDING_REFETCH",
    "BINDING_REGENERATE",
    "DEFAULT_INDEX_NAME",
    "DEFAULT_PUBLISH_PATH",
    "DEFAULT_REF",
    "NeutralRegistryRefused",
    "ORIGIN_LOCAL",
    "PEEK_TTL_SECONDS",
    "SERVED_DOTFILE_SUFFIXES",
    "SnapshotEntry",
    "SnapshotRegistry",
    "SnapshotSource",
    "data_source_from_options",
    "entry_from_snapshot_file",
    "github_raw_base_url",
    "is_publishable_ref",
    "key_id",
    "normalize_ref",
    "parse_key_id",
    "resolve_within",
    "snapshot_key",
]

#: The shared truth every ref-less request means.
DEFAULT_REF = "main"

#: The two refresh bindings. `refetch` re-reads a declared data source, which
#: this registry never has. `regenerate` re-runs the generator against a real
#: checkout, and it is this registry's only binding.
BINDING_REFETCH = "refetch"
BINDING_REGENERATE = "regenerate"

#: A snapshot generated on this host from a checkout. The only origin here.
ORIGIN_LOCAL = "local"

#: The data source's defaults, which `serve.main()` offers as its options'
#: defaults. openDox's own values (`defaults.py`), and an empty publication
#: path, which means the published tree sits at the source's root.
DEFAULT_INDEX_NAME = defaults.DEFAULT_INDEX_NAME
PEEK_TTL_SECONDS = defaults.PEEK_TTL_SECONDS
DEFAULT_PUBLISH_PATH = ""

#: The dot-file extensions `/source` serves: a dot-file is served only when it
#: is a document by its extension.
SERVED_DOTFILE_SUFFIXES = frozenset({".yaml", ".yml", ".md", ".json"})

#: Where every refusal below sends a caller who needs what it refuses.
_REGISTRATION = projection_seams.registry.registration_call


class NeutralRegistryRefused(projection_seams.ProjectionSeamError):
    """openDox's own registry was asked for something only a host's registry
    offers: a data source, a local index, or a refresh it has no binding for.
    Refused, never ignored: a server that silently dropped a declared data
    source would serve something other than what its operator declared."""


# --------------------------- keys ---------------------------

def normalize_ref(ref: str | None) -> str:
    """`None`, empty and whitespace all mean `main`."""
    if ref is None:
        return DEFAULT_REF
    text = str(ref).strip()
    return text or DEFAULT_REF


def snapshot_key(repository: str, ref: str | None = None) -> tuple[str, str]:
    """The registry key, `(repository, ref)`, with `ref` defaulting to `main`."""
    return (str(repository), normalize_ref(ref))


def key_id(repository: str, ref: str | None = None) -> str:
    """A key's wire form, `repository@ref`."""
    repo, ref_name = snapshot_key(repository, ref)
    return f"{repo}@{ref_name}"


def parse_key_id(text: str) -> tuple[str, str] | None:
    """`key_id`'s inverse, or None where `text` is not a key's form. Parsing
    is not admission: the registry still decides whether the pair exists."""
    if not text or "@" not in text:
        return None
    repo, _, ref = text.rpartition("@")
    if not repo:
        return None
    return snapshot_key(urllib.parse.unquote(repo), urllib.parse.unquote(ref))


def is_publishable_ref(ref: str | None) -> bool:
    """Only `main` is shared truth. Every other ref is a session's, which a
    hosted plane never names (FR-048)."""
    return normalize_ref(ref) == DEFAULT_REF


# --------------------------- entries ---------------------------

@dataclass
class SnapshotEntry:
    """One `(repository, ref)` snapshot the registry can serve."""

    repository: str
    ref: str = DEFAULT_REF
    snapshot_path: Path | None = None
    payload: bytes | None = None
    source_root: Path | None = None
    source_revision: str | None = None
    generated_at: str | None = None
    origin: str = ORIGIN_LOCAL
    display_name: str | None = None
    stale: bool = False
    stale_reason: str | None = None
    location: str | None = None
    unavailable_reason: str | None = None
    #: WHOSE session this entry is, `(scope_kind, scope_id)`: set only by the
    #: code that opened the session, the one place the answer is known.
    session_tile: tuple[str, str] | None = None
    #: What the session branched from, `(base_ref, base_revision)`.
    session_base: tuple[str, str] | None = None
    #: The other recorded spellings of the base's revision.
    session_base_aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.ref = normalize_ref(self.ref)
        if self.snapshot_path is not None:
            self.snapshot_path = Path(self.snapshot_path)
        if self.source_root is not None:
            self.source_root = Path(self.source_root)

    @property
    def key(self) -> tuple[str, str]:
        return (self.repository, self.ref)

    @property
    def key_id(self) -> str:
        return key_id(self.repository, self.ref)

    @property
    def available(self) -> bool:
        """Whether this entry can serve bytes at all."""
        if self.payload is not None:
            return True
        return bool(self.snapshot_path and self.snapshot_path.is_file())

    def read_bytes(self) -> bytes | None:
        """The snapshot's bytes: the in-process copy first, then the file."""
        if self.payload is not None:
            return self.payload
        if self.snapshot_path is None:
            return None
        try:
            return self.snapshot_path.read_bytes()
        except OSError:
            return None

    def read_json(self) -> dict | None:
        raw = self.read_bytes()
        if raw is None:
            return None
        try:
            document = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return document if isinstance(document, dict) else None

    def short_revision(self) -> str:
        return (self.source_revision or "")[:12] or "unknown"

    def freshness(self) -> dict:
        """What a viewer's freshness header reads off the entry."""
        return {
            "repository": self.repository,
            "ref": self.ref,
            "source_revision": self.source_revision,
            "source_revision_short": self.short_revision(),
            "generated_at": self.generated_at,
            "origin": self.origin,
            "stale": bool(self.stale),
            "stale_reason": self.stale_reason,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


def entry_from_snapshot_file(
    path: Path | str,
    *,
    repository: str | None = None,
    ref: str | None = None,
    source_root: Path | str | None = None,
    origin: str = ORIGIN_LOCAL,
    stale: bool = False,
    stale_reason: str | None = None,
    display_name: str | None = None,
) -> SnapshotEntry:
    """An entry for a snapshot ON DISK. Its repository and its generation
    stamps are read OUT OF the snapshot, which is their source, unless the
    caller names the repository."""
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        document = {}
    if not isinstance(document, dict):
        document = {}
    generation = document.get("generation")
    generation = generation if isinstance(generation, dict) else {}
    return SnapshotEntry(
        repository=str(repository or document.get("repository") or "unknown"),
        ref=normalize_ref(ref),
        snapshot_path=path,
        source_root=Path(source_root) if source_root is not None else None,
        source_revision=generation.get("source_revision"),
        generated_at=generation.get("generated_at"),
        origin=origin,
        stale=stale,
        stale_reason=stale_reason,
        display_name=display_name,
    )


# --------------------------- containment (pure) ---------------------------

def resolve_within(root: Path | str, url_tail: str) -> Path | None:
    """`url_tail` as an absolute FILE under `root`, or None to refuse it.

    Percent-decoding comes FIRST, so `%2e%2e` and `%2egit` meet the same
    checks as their plain spellings. Then it refuses an empty tail, an
    absolute one and a NUL; any component but the last that is a dot-directory;
    a last component that is a dot-file without a document's extension; any
    path that resolves outside `root`, whether by `..` or by a symlink; and
    anything that is not a regular file."""
    rel = urllib.parse.unquote(str(url_tail))
    rel = rel.split("?", 1)[0].split("#", 1)[0]
    if not rel or rel.startswith("/") or "\x00" in rel:
        return None
    parts = [part for part in rel.replace("\\", "/").split("/")
             if part not in ("", ".")]
    if any(part.startswith(".") and part != ".." for part in parts[:-1]):
        return None
    if parts and parts[-1].startswith(".") and parts[-1] != "..":
        if PurePosixPath(parts[-1]).suffix not in SERVED_DOTFILE_SUFFIXES:
            return None
    try:
        base = Path(root).resolve()
        resolved = (base / rel).resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if resolved != base and not resolved.is_relative_to(base):
        return None
    if not resolved.is_file():
        return None
    return resolved


# --------------------------- the registry ---------------------------

class SnapshotRegistry:
    """The ONE snapshot registry, keyed `(repository, ref)`.

    Per-process and in memory. `serve.py` answers requests on threads of their
    own, so every mutation is serialized under a re-entrant lock, and
    `atomically()` holds it across a read-modify-write, as
    `branch_session._preserving_active` needs."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], SnapshotEntry] = {}
        self._active: tuple[str, str] | None = None
        self._lock = threading.RLock()

    @contextlib.contextmanager
    def atomically(self):
        """Hold the registry across a read-modify-write. Re-entrant."""
        with self._lock:
            yield self

    def register(self, entry: SnapshotEntry, *,
                 active: bool = False) -> SnapshotEntry:
        """Register (or replace) `entry`. The first entry registered becomes
        active, and so does one registered with `active=True`.

        A replacement that does not know its session's owner or base inherits
        them from the entry it replaces: a regenerate rebuilds the entry from
        its snapshot, and only the code that OPENED the session knows either."""
        with self._lock:
            previous = self._entries.get(entry.key)
            if previous is not None and entry.session_tile is None:
                entry.session_tile = previous.session_tile
            if previous is not None and entry.session_base is None:
                entry.session_base = previous.session_base
                entry.session_base_aliases = previous.session_base_aliases
            self._entries[entry.key] = entry
            if active or self._active is None:
                self._active = entry.key
            return entry

    def drop(self, repository: str, ref: str | None = None) -> None:
        with self._lock:
            self._entries.pop(snapshot_key(repository, ref), None)

    def get(self, repository: str, ref: str | None = None) -> SnapshotEntry | None:
        """A ref-less lookup means `main`."""
        return self._entries.get(snapshot_key(repository, ref))

    def entries(self) -> list[SnapshotEntry]:
        """Every entry, ordered by `(repository, ref)`."""
        with self._lock:
            return [self._entries[key] for key in sorted(self._entries)]

    def keys(self) -> list[tuple[str, str]]:
        with self._lock:
            return sorted(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def active(self) -> SnapshotEntry | None:
        key = self._active
        return None if key is None else self._entries.get(key)

    def set_active(self, repository: str,
                   ref: str | None = None) -> SnapshotEntry | None:
        with self._lock:
            entry = self.get(repository, ref)
            if entry is not None:
                self._active = entry.key
            return entry

    def resolve(self, repository: str | None,
                ref: str | None = None) -> SnapshotEntry | None:
        """A named pair, or the ACTIVE entry when no repository is named."""
        if repository is None or repository == "":
            return self.active
        return self.get(repository, ref)

    def resolve_source(self, repository: str | None, ref: str | None,
                       tail: str) -> Path | None:
        """A `/source/` read through ONE entry, confined to that entry's own
        root. An unknown pair, or an entry with no root, serves nothing."""
        entry = self.resolve(repository, ref)
        if entry is None or entry.source_root is None:
            return None
        return resolve_within(entry.source_root, tail)


# --------------------------- data sources: none ---------------------------

def data_source_from_options(*, directory: Path | str | None = None,
                             url: str | None = None,
                             token_env: str | None = None,
                             opener: Callable[..., Any] | None = None):
    """None when no data source is declared, which is the only plane this
    registry serves. A declared one is REFUSED, never ignored."""
    if directory or url:
        raise NeutralRegistryRefused(
            "a runtime data source was declared "
            f"({'--data-source-dir' if directory else '--data-source-url'}), "
            "and openDox's own snapshot registry reads none: a published "
            "snapshot tree is located by a snapshot index, which is a governed "
            "contract, and openDox has no index kind of its own. Serve the "
            "snapshot this checkout generates, or register a host registry "
            f"that reads a data source, at process start, with {_REGISTRATION}")
    return None


def github_raw_base_url(owner_repo: str, *, ref: str = DEFAULT_REF,
                        path: str = DEFAULT_PUBLISH_PATH) -> str:
    """A repository's raw-file base URL, composed from operator flags alone.
    openDox's registry reads no data source, so a URL composed here is refused
    by `data_source_from_options`, naming the seam."""
    slug = str(owner_repo).strip().strip("/")
    if slug.count("/") != 1 or not all(slug.split("/")):
        raise ValueError(f"expected OWNER/REPO, got {owner_repo!r}")
    tree = str(path or "").strip("/")
    tail = f"{slug}/{ref}/" + (f"{tree}/" if tree else "")
    return f"https://raw.githubusercontent.com/{tail}"


# --------------------------- the source ---------------------------

class SnapshotSource:
    """What a server holds: the registry, the snapshot it was handed, and the
    one refresh binding a checkout offers, `regenerate`.

    It takes the keywords a host's source takes, so `serve.build_server` and
    `branch_session` build either through the seam with one call. A declared
    `data_source` or `local_index` is refused at construction (see the module
    docstring). `index_name` and `peek_ttl_seconds` are a data source's, and
    are held but never read here. `generator` is a test's seam: a callable
    taking the regenerate's call, used instead of the registered generator."""

    def __init__(
        self,
        *,
        baked_snapshot: Path | str | None = None,
        repository: str | None = None,
        ref: str | None = None,
        checkout_root: Path | str | None = None,
        data_source=None,
        index_name: str = DEFAULT_INDEX_NAME,
        source_roots: dict[str, Path | str] | None = None,
        local_index: Path | str | None = None,
        generator: Callable[..., dict] | None = None,
        project_register: Path | str | None = None,
        peek_ttl_seconds: float = PEEK_TTL_SECONDS,
    ) -> None:
        if data_source is not None:
            raise NeutralRegistryRefused(
                "a data source was handed to openDox's own snapshot source, "
                "which reads none (a published tree is located by a governed "
                "snapshot index, and openDox has no index kind). Register a "
                f"host registry at process start with {_REGISTRATION}")
        if local_index is not None:
            raise NeutralRegistryRefused(
                f"a local snapshot index ({local_index}) was declared, and "
                "openDox's own snapshot source reads none: a snapshot index "
                "is a governed contract, and openDox has no index kind of its "
                "own. Serve one snapshot, or register a host registry at "
                f"process start with {_REGISTRATION}")
        self.baked_snapshot = Path(baked_snapshot) if baked_snapshot else None
        self.checkout_root = Path(checkout_root) if checkout_root else None
        self.data_source = None
        self.index_name = index_name
        self.local_index = None
        self.peek_ttl_seconds = float(peek_ttl_seconds)
        # Declared confinement roots, keyed canonically: `repo` means
        # `repo@main`, and `repo@ref` names the pair.
        self.source_roots = {
            key_id(*(parse_key_id(raw) or snapshot_key(raw))): Path(value)
            for raw, value in (source_roots or {}).items()
        }
        self.registry = SnapshotRegistry()
        self._refresh_lock = threading.RLock()
        self._generator = generator
        self.project_register = Path(project_register) if project_register else None
        self.errors: list[str] = []
        self.baked_repository = repository
        self.baked_ref = normalize_ref(ref)

    def bootstrap(self) -> SnapshotRegistry:
        """Register the snapshot this source was handed, where it exists."""
        self._register_baked()
        return self.registry

    def _source_root_for(self, repository: str, ref: str) -> Path | None:
        """An entry's confinement root: a declared `--source-root` first, the
        served checkout for the snapshot this source was handed, and none for
        anything else, which then serves no documents."""
        declared = self.source_roots.get(key_id(repository, ref))
        if declared is not None:
            return declared
        if (repository, ref) == (self.baked_repository, self.baked_ref):
            return self.checkout_root
        return None

    def _register_baked(self) -> None:
        if self.baked_snapshot is None or not self.baked_snapshot.is_file():
            return
        entry = entry_from_snapshot_file(
            self.baked_snapshot, repository=self.baked_repository,
            ref=self.baked_ref)
        self.baked_repository = self.baked_repository or entry.repository
        entry.source_root = self._source_root_for(entry.repository, entry.ref)
        self.registry.register(entry, active=self.registry.active is None)

    def peek_hints(self, *, now: float | None = None) -> dict:
        """What a data source advertises. There is none, so nothing."""
        return {}

    def compose_view(self, aggregate_id: str, *,
                     publishable_only: bool = False) -> dict | None:
        """A composed view of several snapshots. openDox's registry composes
        none, so an aggregate id is an unknown snapshot."""
        return None

    @property
    def refresh_binding(self) -> str | None:
        """`regenerate` over a real checkout directory, else no binding."""
        if self.checkout_root is not None and Path(self.checkout_root).is_dir():
            return BINDING_REGENERATE
        return None

    def refresh(self, *, repository: str | None = None,
                ref: str | None = None) -> dict:
        """Run this source's refresh binding for one `(repository, ref)`,
        serialized against every other refresh. Raises on refusal, and leaves
        the previous snapshot in place."""
        binding = self.refresh_binding
        with self._refresh_lock:
            if binding == BINDING_REGENERATE:
                return self._regenerate(repository=repository, ref=ref)
        raise NeutralRegistryRefused(
            "no refresh binding is available on this plane: openDox's own "
            "source regenerates from a checkout directory, and none was given")

    def _regenerate(self, *, repository: str | None, ref: str | None) -> dict:
        """Re-run the REGISTERED generator against the entry's own root and
        rewrite that entry's snapshot through the REGISTERED writer, inside
        the interactivity boundary. The only write a refresh performs.

        A regenerate keeps `main` active, and never promotes a session's ref:
        a session enters the key space and changes nothing the shared
        surfaces render (FR-014a)."""
        previous = self.registry.active
        entry = self.registry.resolve(repository, ref)
        if entry is None:
            raise ValueError(f"unknown snapshot {repository}@{normalize_ref(ref)}")
        if entry.snapshot_path is None:
            raise ValueError(f"{entry.key_id}: no local snapshot path to regenerate")
        root = entry.source_root or self.checkout_root
        if root is None or not Path(root).is_dir():
            raise ValueError(f"{entry.key_id}: no served checkout to regenerate from")
        generate = self._generator or generator_seam.generate
        snapshot = generate(Path(root), entry.repository,
                            project_register_source=self.project_register)
        target = Path(entry.snapshot_path)
        boundary = OutputBoundary(target.parent, [target.name])
        projection_seams.writer.current().write_snapshot(snapshot, target, boundary)
        refreshed = entry_from_snapshot_file(
            target, repository=entry.repository, ref=entry.ref,
            source_root=entry.source_root, origin=ORIGIN_LOCAL)
        refreshed.location = entry.location
        refreshed.display_name = entry.display_name
        already_active = previous is not None and previous.key == entry.key
        self.registry.register(
            refreshed, active=(already_active or is_publishable_ref(entry.ref)))
        return {"binding": BINDING_REGENERATE, "entries": len(self.registry),
                **refreshed.freshness()}
