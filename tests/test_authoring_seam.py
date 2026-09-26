"""The home-corpus seam: ONE registration, read wherever a deferred reach
used to import a publisher's adapter by name (`split-opendox-two-layer-product`
§ 4.1, § 4.2; design.md D6, D7).

`authoring.py:318` used to read the publisher's factory by name INSIDE a
function body, so the module imported cleanly and the failure waited for the
call -- design.md D6's more dangerous class, because it survives any
import-based health check and fails in front of a user. This suite holds
`opendox.corpus_adapter`'s half of the repair to its two words: with NOTHING
registered, the seam REFUSES, naming itself and the exact call that is
missing; with a factory registered, the seam hands it back, unevaluated, for
the caller to invoke with its own root.

THIS FILE GROWS, in the order `tasks.md`'s single-writer table gives:
T020 (this task) adds the two cases below. T021 adds
`test_required_header_fields_come_from_the_registered_adapter`, once
`authoring.py:318` is routed through this seam. T022 adds
`test_an_entry_point_registers_the_local_git_corpus_when_no_host_has`, once
an entry point registers openDox's own default where no host has. Each lands
in its own PR, and none of the three needs `opendox.serve` or `opendox.cli`:
both still raise `ModuleNotFoundError: No module named 'ideation_dashboard'`
until T011 lands (measured at `1e4a57fb`), and any run with the root conftest
in play fails on the autouse `declared_human_console` fixture, which imports
`opendox.cli` (`tests/session_fixtures.py:397`). This file imports neither,
is `--noconftest` safe for exactly that reason, and the PR that adds it
quotes such a run.

A CREATED file: no carve-manifest row (RULED OQ-C -- the manifest declares
what LEAVES openxFactory, never what a destination assembles).
"""

from __future__ import annotations

import pytest

from opendox import corpus_adapter as ca


@pytest.fixture(autouse=True)
def _empty_home_registry():
    """Every test starts with NOTHING registered, and PUTS BACK what it found.

    Mirrors `test_profile_registration.py`'s `_empty_registry`, for the same
    reason: the registry is process-global by design (ONE registration, for
    the whole process), so a test that registers a stand-in must restore
    whatever the process itself relies on afterwards rather than merely clear
    it. Nothing registers a home corpus at this leg's process start today --
    that is T022, still open when this fixture was written -- so there is
    nothing yet to restore; the restore is here so the day T022 lands, or a
    conftest gains an autouse registration, this file does not silently start
    depending on collection order.
    """
    previous = ca._home_factory
    ca._home_factory = ca._UNSET
    yield
    ca._home_factory = previous


# --------------------------------------------------------------------------
# 4.2 -- nothing registered: `home()` refuses, naming the seam and the remedy
# --------------------------------------------------------------------------

def test_home_refuses_naming_the_seam_and_the_remedy_when_nothing_is_registered() -> None:
    """`CorpusRefused`, the interface's ONE exception, and nothing else.

    Never a `ModuleNotFoundError` raised from inside a function -- the defect
    this seam retires -- and never a silent local default: an entry point
    that wants one registers it explicitly (4.1a, T022), so an unregistered
    `home()` always refuses rather than falling back on its own.
    """
    with pytest.raises(ca.CorpusRefused) as caught:
        ca.home()
    refusal = caught.value.refusal
    assert refusal.kind == ca.ADAPTER_NOT_REGISTERED, (
        f"refused for another reason: {refusal.kind!r}")
    assert refusal.subject == "opendox.corpus_adapter", (
        f"the refusal does not name the seam: {refusal.subject!r}")
    assert "register_home" in refusal.detail, (
        f"the refusal does not name the remedy: {refusal.detail!r}")
    # `ADAPTER_NOT_REGISTERED` is a real member of the closed vocabulary, not
    # a one-off string a future edit could drift from `REFUSAL_KINDS`.
    assert ca.ADAPTER_NOT_REGISTERED in ca.REFUSAL_KINDS


def test_home_is_still_refused_after_a_registration_is_cleared() -> None:
    """The refusal is read off THIS process's registry, not cached once seen."""
    ca.register_home(lambda root: (root, root))
    ca.home()  # does not raise: something is registered

    ca._home_factory = ca._UNSET  # the shape `unregister()` would leave, were one asked for
    with pytest.raises(ca.CorpusRefused) as caught:
        ca.home()
    assert caught.value.refusal.kind == ca.ADAPTER_NOT_REGISTERED


# --------------------------------------------------------------------------
# 4.1 -- a registered factory is what `home()` returns
# --------------------------------------------------------------------------

def test_a_registered_factory_is_what_home_returns() -> None:
    """`home()` hands back the factory itself, unevaluated, not its result.

    `factory` has the shape `adapter, ref = factory(root)`. The seam stores
    it as given: no caller has a root to offer at registration time, so the
    caller that later has one (`authoring.py:324`, T021) is the one that
    invokes it -- `home()` only resolves WHICH factory that is.
    """
    calls: list[str] = []

    def stand_in(root: str) -> tuple[str, str]:
        calls.append(root)
        return (f"adapter-over-{root}", f"ref-for-{root}")

    returned = ca.register_home(stand_in)
    assert returned is stand_in, (
        "register_home() should return the factory, so a registrant can "
        "register and hold it in one expression, as domain_profile.register() "
        "does for a profile")

    factory = ca.home()
    assert factory is stand_in, "home() must return exactly what was registered"
    assert calls == [], "home() must not itself call the registered factory"

    adapter, ref = factory("/some/root")
    assert (adapter, ref) == ("adapter-over-/some/root", "ref-for-/some/root")
    assert calls == ["/some/root"], "the caller's own invocation is the only one"


def test_home_returns_the_latest_registration_and_does_not_cache() -> None:
    """One registration stays one: a second `register_home` replaces the first."""
    first = lambda root: ("first", root)   # noqa: E731 - a stand-in, not a policy
    second = lambda root: ("second", root)  # noqa: E731

    ca.register_home(first)
    assert ca.home() is first

    ca.register_home(second)
    assert ca.home() is second, (
        "home() answered from a stale registration after a new one replaced it")


def test_register_home_refuses_a_non_callable_factory() -> None:
    """Storing anything but a callable defers today's clean refusal to a raw
    `TypeError` on the caller's NEXT line -- `adapter, ref = home()(root)`
    cannot unpack what a non-callable would hand back. Consistent with
    `domain_profile.register()` rejecting `None` for the same reason
    (Copilot review, PR opensoft/openDox-code#37).
    """
    with pytest.raises(TypeError):
        ca.register_home(None)  # type: ignore[arg-type]
    with pytest.raises(ca.CorpusRefused):
        ca.home()  # nothing valid was ever stored

    stand_in = lambda root: (root, root)  # noqa: E731
    ca.register_home(stand_in)
    with pytest.raises(TypeError):
        ca.register_home("not-a-factory")  # type: ignore[arg-type]
    assert ca.home() is stand_in, (
        "a rejected registration must not clobber a good one already in place")
