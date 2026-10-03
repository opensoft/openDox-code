"""openDox's OWN defaults for the two doxBench seams: the schema validators and
the status-exemption rail (plan 034's T085; #1144's 4.3 as T007's batch G
amends it, and 16.4 in part; R1Q10 (a) and R1Q12 (a), `openxFactory#656`
comment `5850003126`).

WHY THIS FILE EXISTS. T027 made two of the eight reaches into openxFactory
seams: `serve_wire.py:1369`, which imported openxFactory's doxBench contract
validators, and `doxbench_packet.py:177`, which imported its `Status:` reader.
Each refuses, naming itself, when nothing is registered, and openxFactory
registers its own (T046). Standalone, nothing did, so the served model catalog
answered `catalog_unavailable` and no context packet could be assembled. Batch
G's addendum to 4.3 names the standalone defaults: *"openDox's default
validators run over its spec leg's two chat schemas,
`xfactory-workbench-chat-turn` and `xfactory-workbench-model-catalog`, and
there is no status exemption by default."* This module holds them.

THE ENTRY POINTS REGISTER THEM WHERE NO HOST HAS (R1Q3 (a), comment
`5817152735`). `cli.build_parser()`, `cli.main()`, `serve.build_server()` and
`serve.main()` call `register_defaults()`, beside their registrations of the
default profile, home corpus, generator and projection defaults. Each seam
keeps the projection seams' rules:

* a process that runs none of them still refuses, naming the seam and its
  call (4.2's discipline). A default is a registration an entry point makes,
  never a fallback inside a seam;
* a host's registration made before the default has been read replaces it;
* after the default has been read, a host's registration is refused (R1Q3
  (ii); RN-1 (a)), so one process never verifies its model routes against two
  factories, or marks its packets by two readers;
* the same registration again is a no-op.

THE TWO DEFAULTS.

* THE VALIDATORS: `opendox.validator.doxbench_validators`, openDox's own
  validator over its packaged copies of the two doxBench schemas (T057,
  R1Q12 (a)), one validator per wire kind. The seam calls it once per request,
  and each call proves every copy against its recorded digest before it is
  read, so a changed byte is refused on the request that reads it.
* THE RAIL: `NO_STATUS_EXEMPTION`. It marks NO source exempt from aggressive
  compression, whatever its status says. openDox has no lifecycle vocabulary
  of its own, and "exempt" is a word only such a vocabulary gives a status.
  It still REPORTS a document's own `Status:` line, the raw value, as the
  packet labels each source with it. Reporting none would label a document
  that carries one as having "no Status: header", which would be false. It
  reads the line the way openxFactory's reader does: the first `Status:` line
  among the first `STATUS_SCAN_LINES` real lines, where only CR, LF and CRLF
  end a line.

IMPORT WEIGHT. The standard library only. `register_defaults()` imports the
two seam modules and `opendox.validator` when it is CALLED, so importing this
module registers nothing and names no sibling.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import re

__all__ = ["NO_STATUS_EXEMPTION", "NoStatusExemption", "register_defaults"]

#: The real line separators: CR, LF and CRLF, and nothing else, so an exotic
#: separator (a form feed, U+2028) cannot move a `Status:` line into the
#: window or out of it.
_REAL_LINE_END = re.compile(r"\r\n|\r|\n")


class NoStatusExemption:
    """openDox's own status-exemption rail: no source is exempt.

    It carries `doxbench_packet.STATUS_EXEMPTION_REQUIRED`, and the two
    constants a reader of the rail's names may ask for on
    `opendox.doxbench_packet`."""

    #: The statuses whose content is exempt from aggressive compression: none.
    EXEMPT_STATUSES: frozenset[str] = frozenset()

    #: How many of a document's first real lines are read for its `Status:`.
    STATUS_SCAN_LINES = 15

    _STATUS_RE = re.compile(r"^Status:\s*(.+?)\s*$")

    def lifecycle_status(self, text: str) -> str | None:
        """The document's own declared `Status:`, raw, or None when it
        declares none in its first `STATUS_SCAN_LINES` real lines."""
        if not isinstance(text, str):
            return None
        for line in _REAL_LINE_END.split(text)[:self.STATUS_SCAN_LINES]:
            match = self._STATUS_RE.match(line)
            if match:
                return match.group(1)
        return None

    def is_compression_exempt(self, text: str) -> bool:
        """Never: there is no status exemption by default (batch G's addendum
        to #1144's 4.3)."""
        return False

    def __repr__(self) -> str:
        return "<openDox's own status-exemption rail: no exemption>"


#: The one rail an entry point registers.
NO_STATUS_EXEMPTION = NoStatusExemption()


def register_defaults() -> None:
    """Register openDox's OWN default at each of the two doxBench seams, where
    no host has registered one (R1Q10 (a), in R1Q3 (a)'s pattern).

    The entry points call this beside their other default registrations. It
    registers nothing over a host, and reads nothing, so a host registration
    made afterwards, and before any request reads a default, still replaces
    it. Importing this module registers nothing."""
    from opendox import doxbench_packet, serve_wire, validator

    serve_wire.register_default_doxbench_validators(validator.doxbench_validators)
    doxbench_packet.register_default_status_exemption(NO_STATUS_EXEMPTION)
