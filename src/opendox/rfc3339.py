"""openDox's OWN check of an RFC 3339 date-time: the shape a typed
`--generated-at` must have before a generate verb records it (plan 034's T055).

WHY IT IS HERE. `cli.py` refuses a malformed `--generated-at` before anything
is generated or written (`GeneratedAtRefused`), and it borrowed the check from
the consumer's generator through `consumer_reach`. The check is not the
generate operation, so the generator seam does not carry it (T052's own
record), and it is not the consumer's either: it is the neutral snapshot
contract's own rule, `generated-at-is-rfc3339` (openDox-spec's
`contracts/schemas/opendox-snapshot.schema.yaml`). So openDox owns it.

WHAT IT ADMITS. A full date, an explicit time and an explicit offset (`Z` or
`+hh:mm`), in either case of `T` and `Z`, with optional fractional seconds, on
a day the calendar has, and nothing else. That is the neutral rule, which is
narrower than RFC 3339 in two places: the year is never `0000`, and the
seconds never read `60`, which no git commit date can hold and neither Python's
`datetime` nor a browser's `Date` can read. Digits are ASCII only, and the
whole string must match: no surrounding space and no trailing newline, since
the value is recorded verbatim.

A CREATED FILE: it has no row in openxFactory's
`docs/opendox-carve-manifest.yaml`, because the manifest declares what LEAVES
openxFactory and never what a destination assembles (RULED OQ-C).
"""

from __future__ import annotations

import re
from datetime import datetime

__all__ = ["is_rfc3339_datetime"]

#: The shape, before the instant. `[0-9]`, never `\d`, which also matches the
#: digits of other scripts.
_SHAPE = re.compile(
    r"(?!0000)[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"[Tt](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?"
    r"(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def is_rfc3339_datetime(value: object) -> bool:
    """True when `value` is an RFC 3339 date-time as the neutral contract
    admits one: the shape above, AND an instant. The shape admits
    `2026-02-30T00:00:00Z`, which is no day, so the parse runs too."""
    if not isinstance(value, str) or not _SHAPE.fullmatch(value):
        return False
    stamp = value[:-1] + "+00:00" if value[-1] in "Zz" else value
    try:
        datetime.fromisoformat(stamp)
    except ValueError:
        return False
    return True
