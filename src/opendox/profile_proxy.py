"""`profile_openxfactory`, the composition point, resolved at FIRST ACCESS.

WHY THIS FILE EXISTS. `cli.build_parser()` reads its contributed subcommands
from a bare name — `profile_openxfactory.SUBCOMMAND_EXTENSIONS` (`cli.py`:927)
— that nothing in this package binds: openxFactory's carve manifest files
`profile_openxfactory.py` as `not_moved / deleted_at_carve` ("the one file the
§ 3 carve deletes rather than moves"), so `build_parser()` raises `NameError:
profile_openxfactory` for every caller. The defect is recorded as the slice-2b
finding, `openxFactory#656` comment `5633826227`.

Brett Heap RULED ASK-2 option (2) (`5628886636`) that the name comes back as a
LAZY PROXY rather than as an injected parameter (option 1: 31 call sites across
27 test files, and a signature the carve's tests assert fixed) or a plugin
package openxFactory publishes (option 3: "the shape every future
`<Domainx>Dox` profile may want; not now"). This module is that proxy, and
`domain_profile.py` beside it is the registration it resolves through.

THE PATTERN IS THIS REPOSITORY'S OWN. `consumer_reach.py` (§ 4.1, landed)
already defers a name to first use — `_LateConsumerModule` defers an attribute
read, `_LateConsumerValue` defers the first OPERATION on a value — and refuses
with the layering spelled out instead of raising `ModuleNotFoundError` from an
import line a thousand lines away from the call. `_LateProfile` below is the
same shape pointed at a different question. It is NOT in `consumer_reach.py`,
deliberately: that module is for reaches into `openxdox`, the package that PINS
openDox, and every name in it is counted in a ratchet that must reach zero. A
host profile is not a reach into the consumer at all — the host may be an
openxFactory, a `MedxDox`, or a test — so filing it there would corrupt the one
number `tests/test_consumer_reach.py` exists to hold.

WHAT IT RESOLVES, AND WHEN. Nothing at import time. `import
opendox.profile_proxy` performs no lookup, touches no registry and cannot fail
for want of a host. The FIRST attribute read — `SUBCOMMAND_EXTENSIONS`,
`ROUTE_EXTENSIONS`, anything else a composition point comes to need — calls
`domain_profile.current()` and forwards. The resolved profile is deliberately
NOT cached here: `domain_profile` holds the one registration, caching a second
copy would let this module answer with a profile a host had since
`unregister()`ed, and the lookup is an attribute read on a module global.

HOW IT REFUSES, AND WHY IT NEVER RETURNS `()`. Two distinct failures, two
distinct messages:

* NOTHING REGISTERED -> `domain_profile.ProfileNotRegistered`, naming the exact
  registration call and the runbook. An empty tuple was refused by the ruling's
  own terms and by the failure mode: a parser whose contributed verbs are
  silently absent is indistinguishable from a working one until someone types
  the missing command, and the same is true of a server's contributed routes.
* REGISTERED, BUT LACKING THE FACET -> `ProfileFacetMissing`, naming the
  attribute, the profile and the reader. That is a real and reportable gap in a
  host's profile rather than a missing registration, and telling a host to
  "register a profile" when it just did would send it to the wrong end of its
  own adapter.

`ProfileFacetMissing` subclasses `AttributeError` on purpose: a proxy that
raised something else for a missing attribute would break `hasattr`,
`getattr(..., default)` and every library that probes an object politely, and a
composition point is exactly the sort of object a test harness probes.

A CREATED FILE: no row in openxFactory's `docs/opendox-carve-manifest.yaml`
(RULED OQ-C — the manifest declares what LEAVES openxFactory, never what a
destination assembles).
"""

from __future__ import annotations

from typing import Any

from opendox import domain_profile

__all__ = ["ProfileFacetMissing", "profile_openxfactory"]


class ProfileFacetMissing(AttributeError):
    """A profile IS registered and does not carry the facet a reader named.

    Distinct from `domain_profile.ProfileNotRegistered`, which is the absence of
    a registration; this is a registration that does not answer the question.
    The distinction is the whole value of the message: one sends the reader to
    the host's process-start hook, the other to the host's profile itself.

    An `AttributeError` subclass, so a caller who probes with `hasattr()` or
    `getattr(profile, name, default)` gets the answer those spellings promise.
    """


class _LateProfile:
    """A stand-in for the host's profile module, resolved on first attribute read.

    Deliberately the narrowest thing that answers `cli.py`:927. It forwards
    ATTRIBUTE reads and nothing else: it is not callable, not iterable and not a
    facade. A composition point reads names off a profile; anything else a
    caller wants to do to one is a sign the caller wanted `domain_profile
    .current()`, which is public, one line away, and says what it is doing.
    """

    __slots__ = ("_reader",)

    def __init__(self, reader: str) -> None:
        #: The composition point this stand-in exists for, quoted in refusals so
        #: a message names the READER as well as the missing name.
        self._reader = reader

    def resolve(self) -> Any:
        """The registered profile, or `ProfileNotRegistered` naming the call.

        Every read goes through `domain_profile.current()` — no local cache, so
        an `unregister()` is seen immediately and one registration stays one.
        """
        return domain_profile.current()

    def __getattr__(self, attr: str) -> Any:
        # Dunder lookups must NOT resolve the profile. `copy`, `pickle`,
        # `inspect`, `pytest`'s assertion rewriting and `unittest.mock` all
        # probe arbitrary objects for dunders, and resolving a host profile
        # because something asked for `__wrapped__` would fire the composition
        # point at a moment no caller chose — and would raise
        # `ProfileNotRegistered` where the prober was testing for
        # `AttributeError`. `consumer_reach._LateConsumerModule` holds the same
        # line for the same reason.
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(attr)
        profile = self.resolve()
        try:
            return getattr(profile, attr)
        except AttributeError:
            raise ProfileFacetMissing(
                f"the registered host profile "
                f"({domain_profile.name_of(profile)}) does not carry "
                f"{attr!r}, which {self._reader} reads. A profile IS registered "
                "— this is not a missing registration — so the gap is in the "
                "profile the host handed "
                f"`{domain_profile.REGISTRATION_CALL}`, not in when it handed "
                "it. openDox names only the attributes it reads and type-checks "
                "nothing (RULED ASK-2 option (2), openxFactory#656 comment "
                "5628886636): see docs/profile-registration-runbook.md for what "
                "a host's profile is expected to carry.") from None

    def __repr__(self) -> str:
        # Deliberately does NOT resolve: `repr` is what a debugger, a logging
        # call and a pytest assertion rewrite reach for, and a refusal raised
        # while formatting a value is a worse failure than the one it reports.
        state = "registered" if domain_profile.is_registered() else "unregistered"
        return f"<late host profile for {self._reader} ({state})>"


#: THE COMPOSITION POINT. `cli.py` binds this name and reads
#: `SUBCOMMAND_EXTENSIONS` off it at `build_parser()` time; `serve.py`'s
#: `ROUTE_EXTENSIONS` half is the same object's other facet, and is composed by
#: whatever act re-declares that line (see the runbook — BUILD slice 2b removed
#: `serve.py`'s reach outright and its restoration through this proxy is a
#: separate declared edit, not this one).
profile_openxfactory = _LateProfile(
    "cli.build_parser() / serve.build_server()")
