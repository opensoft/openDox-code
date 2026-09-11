"""Defaults openDox's own signatures carry, owned HERE rather than borrowed.

WHY THIS FILE EXISTS. A DEFAULT ARGUMENT is evaluated where the `def` sits,
which is at import time. Eleven of openDox's public signatures defaulted a
parameter to `<consumer module>.<CONSTANT>`:

    def _demotion_retention_candidates(
        checkout_root, tile, *,
        records_dir: str = gate_console.DEFAULT_RECORDS_DIR,   # ← runs on import
    ):

so `import opendox.branch_session` required `openxdox` to be installed even
after the import STATEMENT was made late. openDox-code #9 § 3 proved exactly
that, converted the imports, measured the result and REVERTED the conversion:
the openXdox-side ratchet counts `ast.Import`/`ast.ImportFrom` nodes and a
default argument is neither, so the conversion alone would have recorded
`branch_session` at `(0, 7)` — "this module no longer imports openXdox" — while
`import opendox.branch_session` still failed without it. A census that reads
better than the tree is worse than no census.

WHAT THIS FILE DOES. It gives openDox its own definition of each value, so the
signature's default is openDox's and resolves nothing. `design.md`:243 states
the standard: *"What must not survive is the direction, not the calls."* A
default argument is not a call at all — it is a VALUE openDox's own signature
publishes, and publishing a value borrowed from the layer that pins you is the
direction, not the call.

WHY NOT A LATE STAND-IN (`consumer_reach`). Because a default argument is
evaluated at import time by definition, so a stand-in would either resolve the
consumer there (the reach, unchanged) or put an unresolved proxy object into
every caller's `records_dir` — a value that is not a `str`, handed to
`Path(...)`, `str.startswith` and `os.fspath` at a hundred call sites. The
reach this file removes is not late-bindable; it is OWNERSHIP, and the answer
is to own it.

WHY THE VALUES ARE RESTATED AND NOT RE-IMPORTED. The lawful direction is
openXdox → openDox: openXdox pins openDox by commit and tree digest
(`split-opendox-two-layer-product` § 4.2, RULED OQ-2), so openXdox's
`gate_console` re-importing this module would be a dependency pointing the
right way. That edit CANNOT BE MADE TODAY: openxFactory's
`docs/opendox-carve-manifest.yaml` declares `gate_console.py` lines
`63, 67, 567, 689, 700, 1195, 2047, 2093` and `snapshot_registry.py` lines
`72, 85, 1284, 1285, 1288`, and the three definitions sit at `gate_console.py`
:165 and `snapshot_registry.py` :90 and :102 — none of them declared, and an
insertion beside a declared line lands either ABOVE the definition (where the
definition rebinds over it) or in the middle of an unrelated paragraph. So the
values are restated here with their provenance, and openXdox-code's
`tests/test_dependency_direction.py` carries a DRIFT GUARD that parses those
three literals out of the consumer's tree and refuses if either side moves
without the other. The guard is the invariant; the re-import is the spelling,
and the spelling is owed a declared line.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C). It sits under
a declared root, so the arrival verifier is told about it explicitly with
`--allow-created src/opendox/defaults.py`.
"""

from __future__ import annotations

#: The default gate-records prefix, carried by nine `records_dir` parameters of
#: `opendox.branch_session` (:1740, :1859, :1878, :4179, :4217, :4254, :4287,
#: :4504, :4991) and read once by `opendox.serve_project`.
#:
#: A CALLER-DECLARED OUTPUT PATH, which is why openDox can own it: it is the
#: `HumanGate` allowlist entry a caller declares, not a location any writer here
#: bakes in. openXdox's `gate_console.DEFAULT_RECORDS_DIR` states the same
#: literal for the same reason and the drift guard holds the two together.
DEFAULT_RECORDS_DIR = "ideation/dashboard/gate-records/"

#: The default snapshot-index filename, carried by `opendox.serve.build_server`'s
#: `index_name` parameter (:1279). Mirrors
#: `openxdox.snapshot_registry.DEFAULT_INDEX_NAME`.
DEFAULT_INDEX_NAME = "index.json"

#: The default peek TTL in seconds, carried by `opendox.serve.build_server`'s
#: `peek_ttl_seconds` parameter (:1283). Mirrors
#: `openxdox.snapshot_registry.PEEK_TTL_SECONDS`.
PEEK_TTL_SECONDS = 60

#: The names the openXdox-side drift guard holds against this module, as
#: `(consumer module, attribute)` -> the name HERE. Exported so the guard reads
#: the pairing from the side that owns the values rather than restating it a
#: third time.
MIRRORED_AT_CONSUMER: dict[tuple[str, str], str] = {
    ("gate_console", "DEFAULT_RECORDS_DIR"): "DEFAULT_RECORDS_DIR",
    ("snapshot_registry", "DEFAULT_INDEX_NAME"): "DEFAULT_INDEX_NAME",
    ("snapshot_registry", "PEEK_TTL_SECONDS"): "PEEK_TTL_SECONDS",
}

__all__ = [
    "DEFAULT_INDEX_NAME",
    "DEFAULT_RECORDS_DIR",
    "MIRRORED_AT_CONSUMER",
    "PEEK_TTL_SECONDS",
]
