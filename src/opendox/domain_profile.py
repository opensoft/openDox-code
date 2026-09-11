"""THE ONE REGISTRATION: the host's domain profile, held for late resolution.

WHY THIS FILE EXISTS. `split-opendox-two-layer-product` § 4.3 asks what becomes
of `profile_openxfactory` — the in-tree composition point `build_parser()` and
`build_server()` read their contributed subcommands and routes from. The § 3
carve files `profile_openxfactory.py` as `not_moved / deleted_at_carve` in
openxFactory's `docs/opendox-carve-manifest.yaml` ("the one file the § 3 carve
deletes rather than moves"), so the name exists at NEITHER destination while
`cli.py` still reads it — `build_parser()` raises `NameError:
profile_openxfactory` for every caller (recorded as the slice-2b finding,
`openxFactory#656` comment `5633826227`).

Brett Heap RULED ASK-2 option (2) on `openxFactory#656` comment `5628886636`:

    LAZY PROXY — a module in openDox-code resolves the profile at first
    attribute access; openxFactory registers the real module at process start;
    that operational contract is DOCUMENTED in the runbook.

This module is the REGISTRY half of that ruling. `profile_proxy.py` beside it is
the accessor half — the object the composition points name. The runbook is
`docs/profile-registration-runbook.md`.

WHY THE REGISTRY AND THE PROXY ARE TWO FILES. The registry is a SEAM other
packages resolve by dotted name; the proxy is one accessor that happens to sit
on top of it. openXdox-code's § 4.4 engine (`openxdox/domain_profile.py`,
openXdox-code #14) reaches `opendox.domain_profile` by that exact string and
duck-types it on `current()` / `is_registered()` — so this module's PATH is part
of a contract, and a file that also carried an accessor named for one particular
host would make an implementation detail load-bearing.

Q5 — ONE REGISTRATION, TWO ACCESSORS (RULED, `5634195861`). The two legs share
ONE host registration, and the shape that realizes it here is:

    THIS LEG'S REGISTRY IS THE SHARED SEAM. The host calls
    `opendox.domain_profile.register(<profile>)` ONCE at process start.
    openDox's own accessor (`profile_proxy.profile_openxfactory`) reads it
    directly. openXdox's accessor (`openxdox.domain_profile.current()`) reads
    it by DELEGATION: when its own registry is empty it imports
    `opendox.domain_profile` late and consults `is_registered()` / `current()`
    (openXdox-code #14 `_upstream()`, which names this module verbatim).

    THAT ADDS NO IMPORT BETWEEN THE TWO LEGS IN THE FORBIDDEN DIRECTION.
    openXdox PINS openDox (`contracts/opendox-pin.yaml`, § 4.2, RULED OQ-2), so
    openXdox reaching openDox is the lawful direction and the only one used.
    NOTHING here imports, names or requires `openxdox`: this module is
    import-side-effect-free and consumer-free, and `tests/test_consumer_reach.py`
    counts it at zero.

    THE ALTERNATIVE REJECTED: "the host calls BOTH legs' `register()` in one
    documented process-start hook". It is the simpler contract to write down and
    it was refused for two reasons. (1) It is TWO registrations wearing one
    hook's name — Q5's words are "one registration, two accessors", and a hook
    that makes two calls has two states that can disagree, which is precisely
    the "half a process reading the other half's vocabulary" failure openXdox's
    `AlreadyRegistered` refuses. (2) openXdox-code #14 has ALREADY built the
    delegation to this module (`_UPSTREAM_REGISTRY = "opendox.domain_profile"`,
    `a4bda011`); choosing the two-call hook would have left that code dead and
    required a second leg's PR to remove it. The one-call shape is also the one
    that survives a host that installs only openDox.

WHAT A "PROFILE" IS HERE, AND WHAT IT IS DELIBERATELY NOT. This module does NOT
type-check what it is handed, and that is the whole of its neutrality: openDox
cannot name `openxdox.domain_profile.DomainProfile` without recreating the
back-import the carve removed, and it cannot name openxFactory's profile module
either, because openxFactory is a DESCENDANT that openDox has never heard of.
So the registered object is whatever the host's adapter builds (D3: the adapter
code stays in openxFactory), and each accessor names ONLY what it reaches:

* openDox reaches `SUBCOMMAND_EXTENSIONS` and `ROUTE_EXTENSIONS` — see
  `profile_proxy.py`, which refuses by NAME when they are absent.
* openXdox type-checks its own `DomainProfile` and treats anything else as "not
  here", leaving its own refusal standing (#14 `_upstream()`).

A host that wants ONE object to serve both therefore registers a profile that
satisfies both readers — e.g. an `openxdox.domain_profile.DomainProfile`
subclass carrying the two extension tuples. That composition is the HOST's, is
documented in the runbook, and is deliberately not enforced from here: openDox
refusing an object for lacking a facet IT does not read would be openDox
legislating for the other leg.

REFUSAL, NOT A DEFAULT. When nothing is registered, the accessors REFUSE and
name the registration call. They do not hand back an empty tuple. An empty
tuple is the failure that cannot be seen: a CLI that silently lost its
contributed verbs and a server that silently lost its contributed routes both
look exactly like a working one until someone types the missing command. This is
the same stance openXdox-code #14 takes for the same reason, in the words
`domain-mapping-declaration` uses for it: a permissive default is the wrong
answer to a question that was asked precisely because permissiveness is unsafe.

A CREATED FILE: no row in openxFactory's `docs/opendox-carve-manifest.yaml`,
because the manifest declares what LEAVES openxFactory and never what a
destination assembles (RULED OQ-C).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AlreadyRegistered",
    "ProfileNotRegistered",
    "REGISTRATION_CALL",
    "current",
    "is_registered",
    "name_of",
    "register",
    "unregister",
]

#: The ONE call a host makes, quoted verbatim in every refusal so the message
#: names the fix rather than the symptom. Kept as a constant because the proxy
#: beside this module quotes it too, and a refusal that named a call spelled
#: differently in two files would send a reader looking for a third.
REGISTRATION_CALL = "opendox.domain_profile.register(<the host's profile>)"


class ProfileNotRegistered(RuntimeError):
    """No host profile has been registered, and openDox composes no profile.

    Raised instead of returning an empty contribution. openDox is the NEUTRAL
    product: it has no domain, no in-tree profile (the § 3 carve deleted the one
    it had) and therefore nothing to fall back TO. A process that builds a
    parser or a server from a host's profile registers that profile at start, or
    the composition refuses and says which call is missing.
    """


class AlreadyRegistered(RuntimeError):
    """A second, different profile was registered over a first.

    ONE registration is the contract (RULED ASK-4 Q5, `5634195861`). Swapping
    the profile under a process that has already composed a parser or a server
    is refused rather than applied: the composition is read ONCE, at build time,
    so a later swap would leave a live parser carrying the first profile's
    subcommands while every subsequent reader saw the second's, and nothing
    would report it. `unregister()` makes a deliberate swap explicit.

    Mirrors `openxdox.domain_profile.AlreadyRegistered` in name and stance, so
    the two accessors of Q5's one registration fail the same way (openXdox-code
    #14). It is NOT the same class — that would be an import between the legs.
    """


_registered: Any = None


def register(profile: Any) -> Any:
    """THE one registration. Called by the host's adapter at process start.

    Returns the profile, so a host can register and hold it in one expression.

    `profile` is a MODULE or an OBJECT — ASK-2's words are "openxFactory
    registers the real module at process start", and an object built from a YAML
    profile is the § 4.4 form of the same thing (RULED ASK-4 Q1: YAML canonical,
    dataclass the runtime form). Both are accepted and neither is type-checked,
    for the reason the module docstring gives: the only types worth checking
    live in packages openDox may not name.

    `None` is refused, because `register(None)` is how "my adapter returned
    nothing" arrives, and accepting it would store an unregistration under a
    name that promises the opposite.

    Re-registering the SAME object is a no-op, so an idempotent host start-up —
    two entry points that both call the hook, a test that re-enters it — is not
    punished. A DIFFERENT object raises `AlreadyRegistered`.
    """
    global _registered
    if profile is None:
        raise TypeError(
            "register() takes the host's profile module or object, not None. "
            "A host with nothing to contribute does not register: it leaves "
            "the registry empty, and the composition points refuse with the "
            "registration call named (ProfileNotRegistered), which is the "
            "state RULED ASK-2 asks for rather than a silent empty profile.")
    if _registered is not None and _registered is not profile:
        raise AlreadyRegistered(
            f"a host profile is already registered ({name_of(_registered)}), "
            f"and {name_of(profile)} would replace it. Registration happens "
            "ONCE, at process start (RULED ASK-4 Q5, openxFactory#656 comment "
            "5634195861): a parser or a server built before the swap keeps the "
            "first profile's contributed subcommands and routes, so a second "
            "registration would leave one process composing from two profiles "
            "with nothing to report it. Call "
            "opendox.domain_profile.unregister() first if the swap is "
            "deliberate.")
    _registered = profile
    return profile


def unregister() -> None:
    """Drop the registration. For test isolation and for a host tearing down."""
    global _registered
    _registered = None


def is_registered() -> bool:
    """Is a profile registered, without resolving anything or refusing?

    Part of the duck-typed contract openXdox's `_upstream()` consults
    (openXdox-code #14): it asks this BEFORE `current()` precisely so that "no
    profile here" is answered without provoking a refusal that is not its.
    """
    return _registered is not None


def current() -> Any:
    """The registered host profile, or a refusal naming the registration call.

    The SECOND half of the duck-typed contract openXdox's `_upstream()`
    consults. It is also what `profile_proxy` resolves through, so both of Q5's
    accessors read the same object from the same place — which is what makes it
    ONE registration rather than two that happen to agree.
    """
    if _registered is None:
        raise ProfileNotRegistered(
            "no host profile is registered, so openDox has no contributed "
            "subcommands and no contributed routes to compose from. openDox is "
            "the NEUTRAL product and ships no profile of its own: the § 3 carve "
            "deleted the in-tree `profile_openxfactory.py` rather than moving "
            "it, and the descendant that drives openDox registers its own "
            "profile at process start with\n\n    " + REGISTRATION_CALL +
            "\n\nbefore it calls `cli.build_parser()` or `serve.build_server()` "
            "(RULED ASK-2 option (2), openxFactory#656 comment 5628886636; the "
            "operational contract is docs/profile-registration-runbook.md). "
            "This is a REFUSAL, not a missing default: composing from an empty "
            "profile would produce a parser with its contributed verbs silently "
            "absent, which looks exactly like a working one.")
    return _registered


def name_of(profile: Any) -> str:
    """A profile's most nameable name, for a refusal message.

    PUBLIC because `profile_proxy.py` quotes it in its own refusal: the two
    accessors of one registration must name a profile the same way, and a
    private helper reached across a module boundary is a contract pretending
    not to be one.

    A module says `__name__`; an object says its type. Neither is required to
    exist on an object this module deliberately does not type-check, so the
    fallback is `repr`, and no branch of this may raise: a refusal that fails
    while formatting itself replaces the reader's problem with a worse one.
    """
    for attr in ("__name__", "mapping_id"):
        try:
            value = getattr(profile, attr)
        except Exception:      # noqa: BLE001 — naming must never out-raise
            continue
        if isinstance(value, str) and value:
            return value
    try:
        return f"a {type(profile).__name__}"
    except Exception:          # noqa: BLE001
        return "the registered profile"
