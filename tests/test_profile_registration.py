"""The ONE registration and the lazy proxy over it — § 4.3.

RULED ASK-2 option (2) (openxFactory#656 comment `5628886636`): the composition
point `profile_openxfactory` resolves at FIRST ATTRIBUTE ACCESS through a
profile the host registers at process start. This suite holds the two halves of
that to their word: `opendox.domain_profile` (the registration, which is also
Q5's shared seam — `5634195861`) and `opendox.profile_proxy` (the accessor).

WHAT IT ASSERTS, AND WHY EACH IS HERE RATHER THAN IMPLIED

1. NOTHING RESOLVES AT IMPORT TIME. The whole value of a lazy proxy is that
   importing it cannot fail for want of a host, so the check is an import in a
   SUBPROCESS that then reads the registry — `consumer_reach`'s own
   `test_importing_the_seam_resolves_nothing` for the same reason.
2. THE UNREGISTERED READ REFUSES, AND THE MESSAGE NAMES THE CALL. A refusal
   whose text does not name the fix is a stack trace with extra steps, so the
   assertion is on the CONTENT — the registration call, the ruling, the runbook
   — not merely on the exception type.
3. IT NEVER ANSWERS EMPTY. The one failure mode the ruling forecloses is a
   silent `()`: a parser whose contributed verbs are absent looks exactly like a
   working one. So a read is asserted to RAISE, not to return something falsy.
4. A REGISTERED PROFILE RESOLVES BOTH FACETS. `SUBCOMMAND_EXTENSIONS`
   (`cli.build_parser()`) and `ROUTE_EXTENSIONS` (`serve.build_server()`) come
   off the same object, which is what "one registration" means at this end.
5. DOUBLE REGISTRATION REFUSES; RE-REGISTERING THE SAME OBJECT DOES NOT. An
   idempotent host start-up is not a defect and must not be punished; a swap
   under a live process is.
6. THE PROBING RULES `consumer_reach` ALREADY SETTLED. Dunder lookups and
   `repr` must not resolve a profile, and a missing facet must stay an
   `AttributeError` — `hasattr`, `getattr(..., default)`, `copy` and pytest's
   own rewriting all depend on it.
7. THE SERVED COMPOSITION POINT IS EXECUTED, NOT DESCRIBED (RULED ASK-6 -> 1,
   `5635150678`). `serve.build_server()` now reads `ROUTE_EXTENSIONS` through
   this proxy, and `import opendox.serve` CANNOT be performed in this
   repository — `serve.py:181` still reaches `ideation_dashboard`, openxFactory's
   pre-carve package, which exists at neither carve destination (recorded in
   `test_consumer_reach.py`'s `STILL_REACHING` and owed to a later act). So the
   two statements that make up the composition point are lifted OUT of
   `build_server`'s body BY AST and executed against a stand-in `route_extension`
   seam. That runs the real source lines — an assertion about the tree, not a
   paraphrase of it — and it keeps working the day `serve.py` becomes importable.

`--noconftest` SAFE, deliberately: `validate` runs this file alongside
`test_leg_shape.py` and `test_consumer_reach.py` with conftest collection off
(RULED Q-L5 (b′)), so nothing here may need a fixture, a path insertion or an
installed consumer. The package itself is installed by the workflow's
`pip install -e ".[test]"`.

A CREATED file: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from opendox import domain_profile, profile_proxy
from opendox.profile_proxy import profile_openxfactory


SRC = Path(__file__).resolve().parent.parent / "src"


class _HostProfile:
    """What a host registers, at the shape openDox actually reads.

    Deliberately NOT an `openxdox.domain_profile.DomainProfile`: openDox
    type-checks nothing and may not name that class, and a test that registered
    one would be asserting a coupling this leg does not have. The two attributes
    below are the whole of what this package reaches for.
    """

    SUBCOMMAND_EXTENSIONS = ("the host's subcommands",)
    ROUTE_EXTENSIONS = ("the host's routes",)


@pytest.fixture(autouse=True)
def _empty_registry():
    """Every test starts and ends with NO registration.

    The registry is process-global by design — it is one registration — so the
    isolation has to be explicit, and `unregister()` exists for exactly this and
    for a host tearing down.
    """
    domain_profile.unregister()
    yield
    domain_profile.unregister()


# --------------------------------------------------------------------------
# 1 — nothing resolves at import time
# --------------------------------------------------------------------------

def test_importing_the_proxy_resolves_nothing() -> None:
    """`import opendox.profile_proxy` must not need a host, or a registration."""
    # `src` on the path EXPLICITLY, rather than relying on the install:
    # `validate` installs the package before it runs pytest, but this file also
    # has to hold for a developer running it out of a checkout, and a
    # subprocess inherits neither the parent's `sys.path` nor its `pythonpath`
    # ini entry. `test_consumer_reach.py` solves the same problem the same way.
    program = f"import sys; sys.path.insert(0, {str(SRC)!r})\n" + textwrap.dedent("""
        import opendox.profile_proxy as pp
        from opendox import domain_profile
        assert not domain_profile.is_registered(), "import registered something"
        assert pp.profile_openxfactory is not None
        print("clean")
    """)
    done = subprocess.run([sys.executable, "-c", program],
                          capture_output=True, text=True)
    assert done.returncode == 0, (
        "importing the composition point failed with no host registered, which "
        f"is the one thing a lazy proxy exists to prevent:\n{done.stderr}")
    assert "clean" in done.stdout


def test_the_registry_starts_empty_and_says_so_without_refusing() -> None:
    """`is_registered()` is the question openXdox's `_upstream()` asks first."""
    assert domain_profile.is_registered() is False


# --------------------------------------------------------------------------
# 2, 3 — the unregistered read refuses, and never answers empty
# --------------------------------------------------------------------------

@pytest.mark.parametrize("facet", ("SUBCOMMAND_EXTENSIONS", "ROUTE_EXTENSIONS"))
def test_an_unregistered_read_refuses_rather_than_answering_empty(facet: str) -> None:
    """The ruling's own terms: a refusal, not a fallback."""
    with pytest.raises(domain_profile.ProfileNotRegistered):
        getattr(profile_openxfactory, facet)


def test_the_refusal_names_the_registration_call_the_ruling_and_the_runbook() -> None:
    """A refusal that does not name the fix is a stack trace with extra steps."""
    with pytest.raises(domain_profile.ProfileNotRegistered) as caught:
        profile_openxfactory.SUBCOMMAND_EXTENSIONS
    message = str(caught.value)
    assert domain_profile.REGISTRATION_CALL in message, (
        "the refusal must quote the exact registration call a host is missing")
    for expected in ("5628886636", "docs/profile-registration-runbook.md",
                     "build_parser", "build_server", "REFUSAL"):
        assert expected in message, f"the refusal no longer names {expected!r}"


def test_current_refuses_the_same_way_as_the_proxy() -> None:
    """Both of Q5's accessors read through `current()`, so it carries the text."""
    with pytest.raises(domain_profile.ProfileNotRegistered):
        domain_profile.current()


# --------------------------------------------------------------------------
# 4 — a registered profile resolves, at first access, both facets
# --------------------------------------------------------------------------

def test_a_registered_profile_resolves_both_composition_points() -> None:
    profile = _HostProfile()
    assert domain_profile.register(profile) is profile, (
        "register() returns the profile so a host can register and hold it in "
        "one expression")
    assert domain_profile.is_registered() is True
    assert domain_profile.current() is profile
    assert profile_openxfactory.SUBCOMMAND_EXTENSIONS == ("the host's subcommands",)
    assert profile_openxfactory.ROUTE_EXTENSIONS == ("the host's routes",)


def test_a_module_registers_as_readily_as_an_object() -> None:
    """ASK-2's words are "registers the real MODULE"; § 4.4's form is an object.

    Both are accepted and neither is type-checked, so the suite registers a
    module too rather than leaving half the ruling's wording untested.
    """
    domain_profile.register(profile_proxy)      # any module will do; this one is here
    assert domain_profile.current() is profile_proxy


def test_the_proxy_does_not_cache_across_a_re_registration() -> None:
    """One registration stays one: an `unregister()` is seen at the next read."""
    first = _HostProfile()
    domain_profile.register(first)
    assert profile_openxfactory.SUBCOMMAND_EXTENSIONS == first.SUBCOMMAND_EXTENSIONS

    class _Second:
        SUBCOMMAND_EXTENSIONS = ("a second host's subcommands",)

    domain_profile.unregister()
    domain_profile.register(_Second())
    assert profile_openxfactory.SUBCOMMAND_EXTENSIONS == ("a second host's subcommands",), (
        "the proxy answered from a cached profile after the registry changed")


def test_none_is_refused_rather_than_stored() -> None:
    """`register(None)` is how "my adapter returned nothing" arrives."""
    with pytest.raises(TypeError):
        domain_profile.register(None)
    assert domain_profile.is_registered() is False


# --------------------------------------------------------------------------
# 5 — one registration, and an idempotent host start-up is not punished
# --------------------------------------------------------------------------

def test_a_second_different_registration_refuses() -> None:
    first = _HostProfile()
    domain_profile.register(first)
    with pytest.raises(domain_profile.AlreadyRegistered) as caught:
        domain_profile.register(_HostProfile())
    assert "5634195861" in str(caught.value), (
        "the refusal must cite RULED ASK-4 Q5, which is where ONE registration "
        "comes from")
    assert "unregister()" in str(caught.value), (
        "a refusal must name the deliberate way to do the thing it refused")
    assert domain_profile.current() is first, "the first registration survived"


def test_registering_the_same_object_twice_is_a_no_op() -> None:
    """An idempotent start-up — two entry points, one hook — is not a defect."""
    profile = _HostProfile()
    domain_profile.register(profile)
    domain_profile.register(profile)
    assert domain_profile.current() is profile


# --------------------------------------------------------------------------
# 6 — a registered profile that lacks the facet a reader named
# --------------------------------------------------------------------------

def test_a_missing_facet_is_its_own_refusal_naming_the_attribute() -> None:
    class _Partial:
        SUBCOMMAND_EXTENSIONS = ()

    domain_profile.register(_Partial())
    with pytest.raises(profile_proxy.ProfileFacetMissing) as caught:
        profile_openxfactory.ROUTE_EXTENSIONS
    message = str(caught.value)
    assert "ROUTE_EXTENSIONS" in message, "the refusal must name the attribute"
    assert "_Partial" in message, "the refusal must name the profile"
    assert "not a missing registration" in message, (
        "the whole point of this second refusal is that it does NOT send a host "
        "back to its process-start hook")


def test_a_missing_facet_stays_an_attribute_error() -> None:
    """`hasattr` and `getattr(..., default)` must keep the meaning they promise."""
    class _Partial:
        SUBCOMMAND_EXTENSIONS = ()

    domain_profile.register(_Partial())
    assert issubclass(profile_proxy.ProfileFacetMissing, AttributeError)
    assert hasattr(profile_openxfactory, "SUBCOMMAND_EXTENSIONS") is True
    assert hasattr(profile_openxfactory, "ROUTE_EXTENSIONS") is False
    assert getattr(profile_openxfactory, "ROUTE_EXTENSIONS", "fallback") == "fallback"


def test_a_dunder_lookup_does_not_resolve_the_profile() -> None:
    """`copy`, `pickle`, `inspect` and pytest all probe for dunders.

    Resolving a host profile because something asked for `__wrapped__` would
    fire the composition point at a moment no caller chose — and would raise
    `ProfileNotRegistered` where the prober was testing for `AttributeError`.
    """
    with pytest.raises(AttributeError):
        profile_openxfactory.__wrapped__
    assert domain_profile.is_registered() is False, "a dunder probe resolved"


def test_repr_does_not_resolve_the_profile() -> None:
    """A refusal raised while formatting a value is worse than the one it reports."""
    text = repr(profile_openxfactory)
    assert "unregistered" in text
    assert "build_parser" in text, "the repr names the reader it exists for"
    domain_profile.register(_HostProfile())
    assert "registered" in repr(profile_openxfactory)


def test_the_proxy_forwards_attribute_reads_and_nothing_else() -> None:
    """It is a composition point, not a facade: not callable, not iterable."""
    domain_profile.register(_HostProfile())
    with pytest.raises(TypeError):
        profile_openxfactory()
    with pytest.raises(TypeError):
        iter(profile_openxfactory)


# --------------------------------------------------------------------------
# 7 — Q5's other end: the seam openXdox reads, held to its duck type
# --------------------------------------------------------------------------

def test_the_registry_answers_the_duck_type_openxdox_delegates_to() -> None:
    """openXdox-code #14 `_upstream()` imports `opendox.domain_profile` by NAME.

    It then consults `is_registered()` and `current()` and type-checks the
    result against its own `DomainProfile`. This asserts OUR half of that
    contract — the module path, the two callables, and the fact that an empty
    registry answers `False` rather than raising — because a rename here would
    break a leg this repository cannot import and therefore cannot test against.
    """
    assert domain_profile.__name__ == "opendox.domain_profile", (
        "openxdox.domain_profile._UPSTREAM_REGISTRY names this module path "
        "verbatim (openXdox-code #14); renaming it silently breaks RULED ASK-4 "
        "Q5's one registration")
    assert callable(domain_profile.is_registered)
    assert callable(domain_profile.current)
    assert domain_profile.is_registered() is False

    profile = _HostProfile()
    domain_profile.register(profile)
    assert domain_profile.is_registered() is True
    assert domain_profile.current() is profile


# --------------------------------------------------------------------------
# 8 — how a refusal NAMES a profile (Copilot review threads on openDox-code#11)
# --------------------------------------------------------------------------

def test_two_opaque_profiles_of_one_class_are_named_apart() -> None:
    """`AlreadyRegistered` is reporting exactly this case, so it must tell them apart.

    A profile carrying neither `__name__` nor `mapping_id` falls back to `repr`,
    not to its type name: two registrations of the same class named "a
    _HostProfile" twice would name neither, and the whole message is about the
    difference between them.
    """
    first, second = _HostProfile(), _HostProfile()
    domain_profile.register(first)
    with pytest.raises(domain_profile.AlreadyRegistered) as caught:
        domain_profile.register(second)
    message = str(caught.value)
    assert domain_profile.name_of(first) != domain_profile.name_of(second)
    assert domain_profile.name_of(first) in message
    assert domain_profile.name_of(second) in message


def test_naming_a_profile_never_raises_and_never_runs_long() -> None:
    """`repr` is arbitrary code on an object this package does not type-check.

    A refusal that fails while formatting itself replaces the reader's problem
    with a worse one, and one that pastes a screenful buries its own words.
    """
    class _Hostile:
        @property
        def __name__(self):        # noqa: D105 - the point is that it raises
            raise RuntimeError("nope")

        def __repr__(self):        # noqa: D105
            raise RuntimeError("nope either")

    assert domain_profile.name_of(_Hostile()) == "a _Hostile"

    class _Verbose:
        def __repr__(self):        # noqa: D105
            return "x" * 5000

    named = domain_profile.name_of(_Verbose())
    assert len(named) <= 120 and named.endswith("…")


@pytest.mark.parametrize("facet,names,not_named", (
    ("ROUTE_EXTENSIONS", "serve.build_server()", "build_parser"),
    ("SUBCOMMAND_EXTENSIONS", "cli.build_parser()", "build_server"),
))
def test_a_missing_facet_names_the_one_reader_that_asked_for_it(
        facet: str, names: str, not_named: str) -> None:
    """Two readers now share ONE proxy, so the refusal must not name both.

    Before RULED ASK-6 -> 1 there was one reader and the label simply said so:
    `serve.build_server()` had no read at all (slice 2b removed it), and naming
    a reader that made no access misdirects the host the message exists to help
    (the Copilot review thread on openDox-code#11). Adding the routes half could
    have thrown that away by concatenating the two labels. It does not — the
    proxy maps FACET to READER, so each refusal still names exactly the
    composition point that asked.
    """
    class _Partial:
        pass

    setattr(_Partial, "SUBCOMMAND_EXTENSIONS" if facet == "ROUTE_EXTENSIONS"
            else "ROUTE_EXTENSIONS", ())
    domain_profile.register(_Partial())
    with pytest.raises(profile_proxy.ProfileFacetMissing) as caught:
        getattr(profile_openxfactory, facet)
    message = str(caught.value)
    assert names in message, f"the {facet} refusal must name {names}"
    assert not_named not in message, (
        f"the {facet} refusal names {not_named!r}, a reader that made no "
        "access — the misdirection the per-facet map exists to prevent")


def test_the_repr_names_the_whole_composition_surface() -> None:
    """`repr` is not a refusal: it has no facet, so it names both readers.

    A facet the map does not carry falls back to the same string, because for a
    name openDox does not yet read, naming too much is a smaller failure than
    naming wrong.
    """
    shown = repr(profile_openxfactory)
    assert "cli.build_parser()" in shown and "serve.build_server()" in shown

    class _Empty:
        pass

    domain_profile.register(_Empty())
    with pytest.raises(profile_proxy.ProfileFacetMissing) as caught:
        profile_openxfactory.SOMETHING_NEITHER_READS
    assert "cli.build_parser() / serve.build_server()" in str(caught.value)


# --------------------------------------------------------------------------
# 9 — the SERVED composition point (RULED ASK-6 -> 1, `5635150678`)
# --------------------------------------------------------------------------

SERVE = SRC / "opendox" / "serve.py"
PROXY_IMPORT = "opendox.profile_proxy"


def _build_server_body() -> list[ast.stmt]:
    """`build_server`'s statements, from the real `serve.py` on disk."""
    tree = ast.parse(SERVE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "build_server":
            return node.body
    raise AssertionError("serve.py no longer defines build_server()")


def _composition_statements() -> list[ast.stmt]:
    """The TWO statements that are the served composition point.

    Lifted by AST rather than by a line number or a regex: the whole point of
    the carve's declared-edit grammar is that line numbers move, and a test
    pinned to one would go green on the wrong statement the first time anything
    above it changed.
    """
    wanted: list[ast.stmt] = []
    for node in _build_server_body():
        if isinstance(node, ast.ImportFrom) and node.module == PROXY_IMPORT:
            wanted.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "route_bindings"
                for t in node.targets):
            wanted.append(node)
    assert len(wanted) == 2, (
        "expected `from opendox.profile_proxy import profile_openxfactory` and "
        f"the `route_bindings = ...` assignment in build_server(); found "
        f"{len(wanted)}")
    return wanted


class _RecordingSeam:
    """A stand-in for `route_extension`, which is all these two lines touch."""

    def __init__(self) -> None:
        self.handed: tuple = ()

    def collect_bindings(self, extensions):
        self.handed = tuple(extensions)
        return self.handed


def _run_composition(route_extensions: tuple) -> _RecordingSeam:
    """Execute the two real statements, and report what the seam was handed."""
    seam = _RecordingSeam()
    namespace: dict = {"route_extension": seam,
                       "route_extensions": route_extensions}
    module = ast.Module(body=_composition_statements(), type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SERVE), "exec"),  # noqa: S102
         namespace)
    return seam


def test_the_served_composition_point_binds_the_proxy_and_reads_the_facet() -> None:
    """The two statements are there, and they are the ones ASK-6 -> 1 ruled."""
    imports, assign = _composition_statements()
    assert [alias.name for alias in imports.names] == ["profile_openxfactory"]
    read = [node for node in ast.walk(assign)
            if isinstance(node, ast.Attribute) and node.attr == "ROUTE_EXTENSIONS"]
    assert read, "build_server() no longer reads ROUTE_EXTENSIONS off the proxy"


def test_the_served_binding_is_deferred_and_never_runs_at_import_time() -> None:
    """`serve.py` must not name the proxy where importing the module runs it.

    The proxy resolves nothing when imported, so this is not about failure — it
    is about POSTURE: a module-level binding would make the profile a thing
    `serve.py` has at import time, and the next reader would reasonably use it
    there. `test_consumer_reach.py` holds the same line for the consumer seam,
    for the same reason.
    """
    tree = ast.parse(SERVE.read_text(encoding="utf-8"))
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            continue
        for inner in ast.walk(node):
            assert not (isinstance(inner, ast.ImportFrom)
                        and inner.module == PROXY_IMPORT), (
                f"serve.py imports the proxy at import time (line {inner.lineno})")
            assert not (isinstance(inner, ast.Name)
                        and inner.id == "profile_openxfactory"), (
                f"serve.py names the profile at import time (line {inner.lineno})")


def test_the_served_routes_put_the_hosts_contribution_ahead_of_the_callers() -> None:
    """The carve's own order, restored: the host's routes first, then the caller's.

    This EXECUTES `serve.py`'s two lines. `route_extensions` stays the § 2.4
    seam for whatever a caller adds ON TOP, and the default `()` still means
    "add nothing" — so a caller who passes nothing gets exactly the host's.
    """
    domain_profile.register(_HostProfile)
    assert _run_composition(("the caller's",)).handed == \
        ("the host's routes", "the caller's")
    assert _run_composition(()).handed == ("the host's routes",)


def test_the_served_composition_point_refuses_when_no_host_registered() -> None:
    """ASK-2's "REFUSAL, NOT A DEFAULT", now true of the server as well.

    `domain_profile.current()`'s message has always told a host to register
    "before it calls `cli.build_parser()` or `serve.build_server()`". Until this
    slice that was half aspirational: slice 2b had removed serve's read, so a
    server composed from whatever it was handed and never asked. It asks now,
    and an unregistered process is told which call is missing rather than
    silently serving without its contributed routes.
    """
    with pytest.raises(domain_profile.ProfileNotRegistered) as caught:
        _run_composition(("the caller's",))
    assert domain_profile.REGISTRATION_CALL in str(caught.value)


def test_a_host_profile_without_routes_is_told_which_reader_wanted_them() -> None:
    """Registered but no `ROUTE_EXTENSIONS`: the server's refusal, at the server."""
    class _CliOnly:
        SUBCOMMAND_EXTENSIONS = ("the host's subcommands",)

    domain_profile.register(_CliOnly())
    with pytest.raises(profile_proxy.ProfileFacetMissing) as caught:
        _run_composition(())
    assert "serve.build_server()" in str(caught.value)
