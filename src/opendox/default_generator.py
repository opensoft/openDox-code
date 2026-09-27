"""openDox's OWN snapshot generator, declared as the generator seam's default.

WHY THIS FILE EXISTS. openDox's entry points register openDox's own generator
where no host has contributed one (R1Q10 (a), `openxFactory#656` comment
`5850003126`, in R1Q3 (a)'s pattern). They do so beside the default profile and
the default home corpus, which they register the same way. This module is what
they register: `GENERATOR`, a `generator_seam.SnapshotGenerator` that writes
the neutral snapshot contract, `generator_seam.NEUTRAL_SNAPSHOT_KIND` (plan
034's T053; R1Q11 (a)), and takes no input beyond the operation's own four.

ITS PROJECTION IS NOT BUILT YET, AND IT SAYS SO. Plan 034 orders the seam
before the projection. T054, openDox's small neutral projection over
`CorpusAdapter` (#1144's 5.1-5.3), comes after this task (T052). The entry
points' registration calls are this task's, because T054 edits neither
`cli.py` nor `serve.py`, whose single-writer order runs T052, then T055. So
`generate()` below refuses, naming itself and the task that builds it, and it
generates nothing. It never answers an empty snapshot, which would read exactly
like an honest one.

NO VERB REACHES IT YET. The generate verbs still call the consumer's generator,
through `consumer_reach`, until T055 routes them through the seam, and T055
comes after T054. The refusal is therefore reachable only by a library caller
that generates through the seam directly. T054 replaces it with the
projection, and the declaration below keeps its contract and its inputs.

HOW IT IS REGISTERED: by the entry points, and never at import (R1Q3 (a)'s
pattern). `cli.build_parser()`, `cli.main()`, `serve.build_server()` and
`serve.main()` call `generator_seam.register_default(GENERATOR)`, which
registers it only where nothing is registered. Importing this module registers
nothing.

IMPORT WEIGHT. `opendox.generator_seam` and the standard library. So this
module imports with no extra installed and no sibling present.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opendox import generator_seam

__all__ = ["GENERATOR", "NeutralProjectionNotBuilt", "generate"]


class NeutralProjectionNotBuilt(generator_seam.GeneratorSeamError):
    """openDox's own generator is declared, and its projection is not built.

    A subclass of the seam's own refusal, so a verb that reports the seam's
    refusals reports this one too. It goes when plan 034's T054 lands the
    projection."""


def generate(repo_root: Path, repository: str, *,
             source_revision: str | None = None,
             generated_at: str | None = None) -> dict[str, Any]:
    """The operation the seam hands over, for openDox's own generator.

    It REFUSES until plan 034's T054 builds the neutral projection. See the
    module docstring for why the declaration lands first."""
    raise NeutralProjectionNotBuilt(
        f"openDox's own generator is declared at the generator seam, writing "
        f"{generator_seam.NEUTRAL_SNAPSHOT_KIND!r}, but its projection is not "
        f"built at this commit (plan 034's T054 builds it), so nothing was "
        f"generated for {repository!r} at {str(repo_root)!r}. A host that has "
        f"a generator of its own registers it at process start with "
        f"{generator_seam.REGISTRATION_CALL}.")


#: openDox's OWN generator, as the entry points register it where no host has.
GENERATOR = generator_seam.SnapshotGenerator(
    contract=generator_seam.NEUTRAL_SNAPSHOT_KIND, generate=generate)
