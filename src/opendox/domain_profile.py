"""THE ONE REGISTRATION: the host's domain profile, or openDox's own default, held for late resolution.

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

REFUSAL, NOT AN EMPTY DEFAULT. When nothing is registered, the accessors REFUSE
and name the registration call. They do not hand back an empty tuple. An empty
tuple is the failure that cannot be seen: a CLI that silently lost its
contributed verbs and a server that silently lost its contributed routes both
look exactly like a working one until someone types the missing command. This is
the same stance openXdox-code #14 takes for the same reason, in the words
`domain-mapping-declaration` uses for it: a permissive default is the wrong
answer to a question that was asked precisely because permissiveness is unsafe.

THE PRODUCT'S OWN DEFAULT IS A REGISTRATION AN ENTRY POINT MAKES (R1Q3 (a),
`openxFactory#656` comment `5817152735`). openDox ships a default profile for its
own domain, `opendox.default_profile`, as requirement 3 of
`add-neutral-product-standalone-operability` asks. It is not a fallback inside
`current()`, which would make the refusal above unreachable. `cli.build_parser()`,
`serve.build_server()` and both `main()`s call `register_default()` first, and it
registers the default only where nothing is registered. So:

* a process that BUILDS through an entry point composes from the host's profile
  where a host registered one, and from openDox's own default where none did;
* a process that builds NOTHING, which is the library caller's case, still has
  no registration and still meets `ProfileNotRegistered`. That is the case
  `profile_proxy` was written for (R1Q3 (i));
* a host registration made BEFORE anything is built from the default replaces
  it. One made AFTER a parser or a server was built from the default is refused
  as `AlreadyRegistered`, for ASK-4 Q5's reason (R1Q3 (ii); RN-1 (a), comment
  `5850003126`).

"Built from" is recorded where openDox composes. `profile_proxy` resolves the
profile through `current_for_build()`, which is `current()` plus that record.
`current()` itself records nothing, so openXdox's `_upstream()`, and any reader
that only asks which profile is registered, is never taken for a build.

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
    "current_for_build",
    "is_registered",
    "name_of",
    "register",
    "register_default",
    "unregister",
]

#: The ONE call a host makes, quoted verbatim in every refusal so the message
#: names the fix rather than the symptom. Kept as a constant because the proxy
#: beside this module quotes it too, and a refusal that named a call spelled
#: differently in two files would send a reader looking for a third.
REGISTRATION_CALL = "opendox.domain_profile.register(<the host's profile>)"

#: How much of a `repr` a refusal quotes before it stops being read. Long enough
#: to tell two instances apart, short enough that the refusal's own words are
#: still visible after it.
_NAME_LIMIT = 120


class ProfileNotRegistered(RuntimeError):
    """Nothing is registered: no host's profile, and no entry point's default.

    Raised instead of returning an empty contribution. openDox ships a default
    of its own, `opendox.default_profile`, but the default is a registration an
    ENTRY POINT makes and never a fallback here (R1Q3 (a)). `cli.build_parser()`,
    `serve.build_server()` and both `main()`s register it where no host has. So
    this is what a process meets when it asks for the profile without building
    anything through an entry point. That is the library caller's case, and the
    one `profile_proxy` was written for (R1Q3 (i)). A host registers its own
    profile at process start, before the first build.
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

    THE ENTRY POINT'S DEFAULT IS REPLACEABLE UNTIL SOMETHING IS BUILT FROM IT
    (R1Q3 (ii); RN-1 (a), `openxFactory#656` comment `5850003126`). A host
    registration made while openDox's own default is registered, and before
    any parser or server has been built from it, replaces the default: nothing
    has composed from it, so there is nothing left for a swap to strand. After
    a build, a host's registration meets this refusal for the reason above, and
    the message says that the registration it met is the default.
    """


#: THE one registration, host's or default, or `None`.
_registered: Any = None

#: Whether `_registered` is the default an ENTRY POINT registered
#: (`register_default()`), rather than a host's own `register()`.
_is_default: bool = False

#: Whether a parser or a server has been built from that default. Recorded by
#: `current_for_build()`, the accessor the composition points resolve through.
_built_from_default: bool = False


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

    OVER THE ENTRY POINT'S DEFAULT (R1Q3 (ii); RN-1 (a), `openxFactory#656`
    comment `5850003126`). Where the registration is openDox's own default,
    which an entry point registered because no host had, a host's profile
    REPLACES it while nothing has been built from it, and is refused as
    `AlreadyRegistered` once a parser or a server has been. Either way the host
    ends up holding the one registration, or knows why it does not.

    THE NO-OP HOLDS FOR THE DEFAULT TOO (Copilot review thread on
    openDox-code#42). `register(opendox.default_profile)` while an entry point's
    default is registered changes nothing at all. The registration stays the
    entry point's default, so a host's different profile still replaces it
    until something is built from it. A build from it stays on record, so a
    different profile after the build is still refused, with the message that
    names the default. Nothing is swapped, so there is nothing for ASK-4 Q5's
    refusal to prevent. Which kind a registration is, a host's or the entry
    point's default, is set by the call that MADE it: a host that registers the
    default itself, before any entry point has, holds a host's registration.
    """
    global _registered, _is_default, _built_from_default
    if profile is None:
        raise TypeError(
            "register() takes the host's profile module or object, not None. "
            "A host with nothing to contribute does not register: it leaves "
            "the registry empty, and the composition points refuse with the "
            "registration call named (ProfileNotRegistered), which is the "
            "state RULED ASK-2 asks for rather than a silent empty profile.")
    if _registered is profile:
        # The same object again: a no-op, before any bookkeeping is touched.
        # Falling through would clear `_is_default` and `_built_from_default`
        # and quietly turn an entry point's default into a host's registration.
        return profile
    if _registered is not None:
        if not _is_default:
            raise AlreadyRegistered(
                f"a host profile is already registered "
                f"({name_of(_registered)}), and {name_of(profile)} would "
                "replace it. Registration happens ONCE, at process start "
                "(RULED ASK-4 Q5, openxFactory#656 comment 5634195861): a "
                "parser or a server built before the swap keeps the first "
                "profile's contributed subcommands and routes, so a second "
                "registration would leave one process composing from two "
                "profiles with nothing to report it. Call "
                "opendox.domain_profile.unregister() first if the swap is "
                "deliberate.")
        if _built_from_default:
            raise AlreadyRegistered(
                f"openDox's own default profile ({name_of(_registered)}) is "
                "registered, because an entry point registered it where no "
                "host had, and a parser or a server has already been built from "
                f"it, so {name_of(profile)} cannot replace it now. The build "
                "keeps the default's contributed subcommands and routes, so a "
                "swap would leave one process composing from two profiles with "
                "nothing to report it (RULED ASK-4 Q5, openxFactory#656 comment "
                "5634195861). A host registration replaces the default only "
                "BEFORE anything is built from it (R1Q3 (ii), comment "
                "5817152735; RN-1 (a), comment 5850003126), so register the "
                "host's profile at process start, ahead of the first "
                "`cli.build_parser()` or `serve.build_server()`. Call "
                "opendox.domain_profile.unregister() first if the swap is "
                "deliberate.")
    _registered = profile
    _is_default = False
    _built_from_default = False
    return profile


def register_default(profile: Any) -> Any:
    """AN ENTRY POINT'S registration of the product's OWN default (R1Q3 (a)).

    `cli.build_parser()`, `serve.build_server()` and both `main()`s call this,
    with `opendox.default_profile`, before anything reads the profile. It
    registers `profile` ONLY where nothing is registered. A host's registration,
    or a default already registered, is left exactly as it is. Returns whatever
    is registered afterwards, so an entry point can name the profile it builds
    on in one expression.

    It is NOT for hosts. A host calls `register()`, and its profile replaces
    this one until something has been built from it (see `register()`).

    `None` is refused for the reason `register()` gives: it is how "my profile
    is missing" arrives, and storing it would record a registration that
    promises the opposite.
    """
    global _registered, _is_default, _built_from_default
    if profile is None:
        raise TypeError(
            "register_default() takes the product's default profile, not None. "
            "An entry point that has no default to offer registers nothing, "
            "and the composition points then refuse with the registration call "
            "named (ProfileNotRegistered).")
    if _registered is None:
        _registered = profile
        _is_default = True
        _built_from_default = False
    return _registered


def unregister() -> None:
    """Drop the registration, whether a host's or the entry point's default.

    For test isolation and for a host tearing down. The record of a build from
    the default goes with it, so a deliberate swap after `unregister()` is an
    ordinary first registration.
    """
    global _registered, _is_default, _built_from_default
    _registered = None
    _is_default = False
    _built_from_default = False


def is_registered() -> bool:
    """Is a profile registered, without resolving anything or refusing?

    Part of the duck-typed contract openXdox's `_upstream()` consults
    (openXdox-code #14): it asks this BEFORE `current()` precisely so that "no
    profile here" is answered without provoking a refusal that is not its.

    True for a host's registration and for the default an entry point
    registered alike (R1Q3 (a)): after `cli.build_parser()` in a process no host
    touched, it answers True, and `current()` names `opendox.default_profile`.
    """
    return _registered is not None


def current() -> Any:
    """The registered profile, or a refusal naming the registration call.

    The SECOND half of the duck-typed contract openXdox's `_upstream()`
    consults. `profile_proxy` resolves through it too, by way of
    `current_for_build()`, so both of Q5's accessors read the same object from
    the same place — which is what makes it ONE registration rather than two
    that happen to agree.

    It answers what is registered: a host's profile, or the default an entry
    point registered (R1Q3 (a)). It never falls back to the default itself, so
    a process that built nothing through an entry point meets the refusal
    below. Asking records nothing, either: only a build is a build.
    """
    if _registered is None:
        raise ProfileNotRegistered(
            "no profile is registered, so openDox has no contributed "
            "subcommands and no contributed routes to compose from. openDox "
            "ships a default profile of its own, `opendox.default_profile`, but "
            "the default is a registration an ENTRY POINT makes and never a "
            "fallback here (R1Q3 (a), openxFactory#656 comment 5817152735): "
            "`cli.build_parser()`, `serve.build_server()` and each `main()` "
            "register it where no host has, and this process has built nothing "
            "through one. A host that drives openDox registers its own profile "
            "at process start with\n\n    " + REGISTRATION_CALL +
            "\n\nbefore it calls `cli.build_parser()` or `serve.build_server()` "
            "(RULED ASK-2 option (2), openxFactory#656 comment 5628886636; the "
            "operational contract is docs/profile-registration-runbook.md). "
            "This is a REFUSAL, not a missing default: answering with an empty "
            "profile here would produce a parser with its contributed verbs "
            "silently absent, which looks exactly like a working one.")
    return _registered


def current_for_build() -> Any:
    """`current()`, for a composition point that is BUILDING from the profile.

    The one accessor `profile_proxy` resolves through, so every facet a parser
    or a server reads comes through here. It refuses exactly as `current()`
    does, and it records one thing more. Where the registered profile is the
    default an entry point registered, a parser or a server has now been built
    from it, and from that moment a host's `register()` is refused rather than
    applied (R1Q3 (ii); RN-1 (a), `openxFactory#656` comment `5850003126`). A
    host's own registration needs no record: it is refused against a different
    profile already.
    """
    global _built_from_default
    profile = current()
    if _is_default:
        _built_from_default = True
    return profile


def name_of(profile: Any) -> str:
    """A profile's most nameable name, for a refusal message.

    PUBLIC because `profile_proxy.py` quotes it in its own refusal: the two
    accessors of one registration must name a profile the same way, and a
    private helper reached across a module boundary is a contract pretending
    not to be one.

    A module says `__name__`; an object built from a profile YAML says
    `mapping_id` (§ 4.4's field). Neither is required to exist on an object this
    module deliberately does not type-check, so the last resort is `repr` —
    TRUNCATED, because an opaque profile's `repr` can be a screenful and a
    refusal is read, not parsed, but not REPLACED by the type name: two
    registrations of the same class are exactly the case `AlreadyRegistered` is
    reporting, and a message that called them both "a HostProfile" would name
    neither.

    NO BRANCH OF THIS MAY RAISE. A refusal that fails while formatting itself
    replaces the reader's problem with a worse one, and `repr` is arbitrary
    code on an object this module was handed. Hence the guard on every step and
    the final constant.

    (Copilot review thread on openDox-code#11: the docstring promised `repr` and
    the code returned the type name.)
    """
    for attr in ("__name__", "mapping_id"):
        try:
            value = getattr(profile, attr)
        except Exception:      # noqa: BLE001 — naming must never out-raise
            continue
        if isinstance(value, str) and value:
            return value
    try:
        text = repr(profile)
    except Exception:          # noqa: BLE001
        text = ""
    if text:
        return text if len(text) <= _NAME_LIMIT else text[:_NAME_LIMIT - 1] + "…"
    try:
        return f"a {type(profile).__name__}"
    except Exception:          # noqa: BLE001
        return "the registered profile"
