"""Run `opendox generate-and-open` for real, with ONLY its generation stood in.

`tests_runtime/test_bundled_postgres.py` launches this file as a child process
(`python tests_runtime/local_entrypoint_driver.py generate-and-open --local …`)
so that F13.1's local probe can be run the way F13.1 runs it: in the
BACKGROUND, reached over HTTP, asked about by a SECOND process
(`runtime status`), and then stopped with a signal (plan 034 T072).

WHAT IS STOOD IN, AND WHY IT IS ONLY THIS. At this stack's base, the generate
verbs still reach openXdox for three names (`corpus_root_refusal`,
`generate_snapshot`, `snapshot.write_snapshot`) and `serve` for two
(`_checkout_real`, `registry_mod`'s binding constants): phase 2's T055 and T056
(openDox-code#59 and its successor) give openDox its own, and a lone checkout
cannot ask for them before then. They are replaced here exactly as
`tests/test_doxbench_entrypoint.py` replaces them, and NOTHING ELSE is:
`cli.main`, the install shape, the bundled server, `build_server` and the serve
loop all run as a user's `opendox generate-and-open --local` runs them. Once
T055 and T056 have landed on this branch's base, this driver's stand-ins go and
the probe runs the real entry point on `tests/fixtures/plain-documents`.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path


class _StandInSource:
    """`build_server`'s snapshot source, as T011's `standalone` fixture has it."""

    refresh_binding = None
    baked_repository = None

    class registry:
        active = None

    def bootstrap(self):
        pass


def _generate_snapshot(repo_root, repository, *, source_revision=None,
                       **_ignored):
    return {"repository": repository,
            "generation": {"source_revision": source_revision},
            "documents": [{"id": "stand-in.md"}]}


def _write_snapshot(snapshot, output, boundary):
    Path(output).write_text(json.dumps(snapshot), encoding="utf-8")
    return output


def main(argv: list[str]) -> int:
    from opendox import cli as cli_mod
    from opendox import serve as serve_mod

    cli_mod.corpus_root_refusal = lambda root, shape=None: None
    cli_mod.generate_snapshot = _generate_snapshot
    cli_mod.snapshot_mod = types.SimpleNamespace(write_snapshot=_write_snapshot)
    serve_mod._checkout_real = lambda root: False
    serve_mod.registry_mod = types.SimpleNamespace(
        BINDING_REGENERATE="regenerate", BINDING_REFETCH="refetch")
    real_build_server = serve_mod.build_server

    def _build_server(*args, **kwargs):
        kwargs.setdefault("snapshot_source", _StandInSource())
        return real_build_server(*args, **kwargs)

    serve_mod.build_server = _build_server
    return cli_mod.main(argv)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(main(sys.argv[1:]))
