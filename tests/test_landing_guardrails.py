"""The landing seam's guardrails, against REAL scratch repositories (#1144 12.6,
12.6a; plan 038 T012; spec FR-006, FR-007).

F12.2 names thirteen nodes in this file, and pytest exits non-zero for any node
that does not exist, so each is here under its ratified name:

    test_land_requires_an_explicit_human_act
    test_land_shows_a_conflict_and_does_not_resolve_it
    test_a_landed_merge_is_a_commit_that_git_revert_undoes
    test_no_configuration_enables_automatic_landing
    test_a_governed_repository_binds_no_lander
    test_an_unknown_governance_binds_no_lander
    test_a_host_profile_that_fails_to_load_binds_no_lander
    test_a_branch_cannot_declare_its_own_governance
    test_a_registered_host_outranks_any_declaration
    test_a_directly_constructed_confirmation_is_refused
    test_a_confirmation_for_another_branch_or_head_is_refused
    test_a_spent_confirmation_is_refused
    test_only_the_interactive_layers_call_an_issuer

Beside them, T012's own named nodes: R2Q7 (a)'s two refusals
(`test_a_repository_with_no_main_is_unknown_and_refused_naming_it`,
`test_no_declaration_refuses_naming_the_file_and_its_content`; lane
openXfactory-3's R2Q7 FIX) and ADV-08's
(`test_a_dirty_served_checkout_on_main_is_refused_before_merging`). Then the
lander's mechanics (R2Q6 (a)), the governance reading's edges, and the audit of
every place openDox creates a repository.

THE HOST SIDE RUNS HERE, against a registered TEST host profile that declares an
instrument (R2Q3 (a)): no production host declares one in release 2.

The surface nodes (the `land` verb, the routes and the confirm control) arrive
with T016; these exercise the seam itself.
"""

from __future__ import annotations

import ast
import copy
import pickle
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from session_fixtures import hooks_neutral_dir

from opendox import domain_profile, landing, landing_confirm, session_git, session_pr
from opendox.landing import (DECLARATION_CONTENT, DECLARATION_PATH, GOVERNED,
                             STANDALONE, UNKNOWN, Landed, LandingRefused,
                             MergeConflict, NeutralLander)
from opendox.landing_confirm import Confirmation, ConfirmationRefused
from opendox.runtime import config as runtime_config

#: The explicit local install (`OPENDOX_INSTALL_MODE=local`), passed as the
#: environment the install mode is read from, so no ambient setting decides.
LOCAL = {"OPENDOX_INSTALL_MODE": "local"}
HOSTED: dict[str, str] = {}

BRANCH = "sess-1"
PACKAGE = Path(landing.__file__).resolve().parent


# --------------------------------------------------------------------------
# the registry: no host unless a test registers one, and exactly restored
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_host_registered():
    """Every case starts with NOTHING registered and puts back what it found.

    The root `conftest.py` registers an empty `_SuiteProfile`, a HOST profile, at
    process start; a registered host decides governance (R2Q4 (a)), so a case
    that wants the declaration to decide must run without it. The restore reads
    the registry's three facts exactly as `test_profile_registration.py`'s
    `_empty_registry` does, and for the reason it gives: a restore through
    `register()` alone would hand an entry point's default back as a host's."""
    saved = (domain_profile._registered, domain_profile._is_default,
             domain_profile._built_from_default)
    domain_profile.unregister()
    yield
    domain_profile.unregister()
    (domain_profile._registered, domain_profile._is_default,
     domain_profile._built_from_default) = saved


class RecordingSubmissions:
    """The TEST host's contributed `SubmissionPort`: it records what it was asked
    to submit and reports where the work went, as a `Submission` would."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.submitted: list[str] = []

    def submit(self, branch: str) -> dict:
        self.submitted.append(branch)
        return {"remote": "governance", "ref": f"refs/heads/{branch}",
                "url": "governed.invalid/instrument", "branch": branch}


class InstrumentedHost:
    """A registered TEST host profile that declares an instrument (R2Q3 (a))."""

    SUBCOMMAND_EXTENSIONS: tuple = ()
    ROUTE_EXTENSIONS: tuple = ()

    def __init__(self) -> None:
        self.ports: list[RecordingSubmissions] = []

    def SUBMISSION_INSTRUMENT(self, root: Path) -> RecordingSubmissions:  # noqa: N802
        port = RecordingSubmissions(Path(root))
        self.ports.append(port)
        return port


class HostWithoutAnInstrument:
    """A registered host profile that declares no instrument."""

    SUBCOMMAND_EXTENSIONS: tuple = ()
    ROUTE_EXTENSIONS: tuple = ()


class HostThatFailsToLoad:
    """A registered host profile whose instrument facet cannot be read."""

    SUBCOMMAND_EXTENSIONS: tuple = ()
    ROUTE_EXTENSIONS: tuple = ()

    @property
    def SUBMISSION_INSTRUMENT(self):  # noqa: N802
        raise ImportError("the host's adapter module is not installed")


# --------------------------------------------------------------------------
# the scratch world: a plain repository, `main` and one session branch
# --------------------------------------------------------------------------

class World:
    def __init__(self, tmp_path: Path, *, initial: str = "main",
                 declaration: str | None = DECLARATION_CONTENT) -> None:
        self.tmp = tmp_path
        self.hooks = hooks_neutral_dir(tmp_path)
        self.root = tmp_path / "plain"
        self.root.mkdir(parents=True)
        self.git("init", "-q", f"--initial-branch={initial}")
        for key, value in (("user.email", "landing@example.invalid"),
                           ("user.name", "Landing Harness"),
                           ("commit.gpgsign", "false"),
                           ("core.hooksPath", str(self.hooks))):
            self.git("config", key, value)
        self.write("doc.md", "base\n")
        paths = ["doc.md"]
        if declaration is not None:
            self.write(DECLARATION_PATH, declaration)
            paths.append(DECLARATION_PATH)
        self.commit("seed", *paths)
        self.main = initial

    # ---- the harness's own git (never the product's) ----
    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        done = subprocess.run(["git", *args], cwd=str(cwd or self.root),
                              text=True, capture_output=True)
        if check and done.returncode != 0:
            raise AssertionError(f"git {' '.join(args)}: {done.stderr}")
        return done.stdout.strip()

    def write(self, rel: str, text: str, *, cwd: Path | None = None) -> Path:
        path = (cwd or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit(self, message: str, *paths: str, cwd: Path | None = None) -> str:
        self.git("add", "--", *paths, cwd=cwd)
        self.git("commit", "-q", "-m", message, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def head(self, ref: str = "HEAD") -> str:
        return self.git("rev-parse", ref)

    def tree(self, ref: str) -> str:
        return self.git("rev-parse", f"{ref}^{{tree}}")

    def branch_with(self, branch: str, rel: str, text: str, *,
                    base: str | None = None) -> str:
        """A commit on `branch` (made from `base`) writing `rel`; the served
        checkout is put back on the branch it held."""
        held = self.git("rev-parse", "--abbrev-ref", "HEAD")
        if self.git("branch", "--list", branch):
            self.git("checkout", "-q", branch)
        else:
            self.git("checkout", "-q", "-b", branch, base or self.main)
        self.write(rel, text)
        sha = self.commit(f"work on {branch}", rel)
        self.git("checkout", "-q", held)
        return sha

    def on_main(self, rel: str, text: str) -> str:
        held = self.git("rev-parse", "--abbrev-ref", "HEAD")
        self.git("checkout", "-q", self.main)
        self.write(rel, text)
        sha = self.commit(f"main: {rel}", rel)
        self.git("checkout", "-q", held)
        return sha

    def worktrees(self) -> list[Path]:
        listed = self.git("worktree", "list", "--porcelain")
        return [Path(line[len("worktree "):]).resolve()
                for line in listed.splitlines() if line.startswith("worktree ")]

    def fingerprint(self) -> tuple[str, str, str]:
        return (self.git("rev-parse", "--abbrev-ref", "HEAD"), self.head(),
                self.git("status", "--porcelain", "--untracked-files=all"))

    def refs(self) -> str:
        return self.git("for-each-ref", "--format=%(refname) %(objectname)")


def mint(world: World, branch: str = BRANCH, head: str | None = None) -> Confirmation:
    """A confirmation through the VIEW's issuer, as the confirm control gets one."""
    nonces = landing_confirm.LandingNonces()
    head = head or world.head(f"refs/heads/{branch}")
    return nonces.confirm_nonce(branch, nonces.issue_nonce(branch, head))


class FakeTerminal:
    """A controlling terminal that answers one line."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.shown = ""

    def __enter__(self) -> "FakeTerminal":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def write(self, text: str) -> int:
        self.shown += text
        return len(text)

    def flush(self) -> None:
        return None

    def readline(self, limit: int = -1) -> str:
        return self.answer


def at_terminal(monkeypatch, answer: str, *, stdin_tty: bool = True) -> FakeTerminal:
    terminal = FakeTerminal(answer)
    monkeypatch.setattr(landing_confirm, "_stdin_is_a_terminal", lambda: stdin_tty)
    monkeypatch.setattr(landing_confirm, "_open_controlling_terminal",
                        lambda: terminal)
    return terminal


@pytest.fixture
def world(tmp_path: Path) -> World:
    built = World(tmp_path)
    built.branch_with(BRANCH, "notes/session.md", "session work\n")
    return built


def lander(world: World, **kwargs) -> NeutralLander:
    kwargs.setdefault("env", LOCAL)
    return NeutralLander(world.root, **kwargs)


# ==========================================================================
# F12.2's thirteen nodes
# ==========================================================================

def test_land_requires_an_explicit_human_act(world, monkeypatch, tmp_path):
    """Every way of building a confirmation that is not a human act is refused:
    a flag, a configuration key, a stdin that is not a terminal. The human act
    itself, the branch name typed at the controlling terminal, lands."""
    before = world.refs()
    # A FLAG, or any value that stands in for one.
    for flag in (None, True, 1, "yes", "--yes", BRANCH, {"confirmed": True},
                 (BRANCH, world.head(BRANCH))):
        with pytest.raises(LandingRefused) as refused:
            lander(world).land(BRANCH, confirmation=flag)
        assert refused.value.code == "confirmation:not-a-confirmation", flag
    # A CONFIGURATION KEY: the environment and git's own configuration.
    world.git("config", "opendox.confirm", "true")
    world.git("config", "opendox.autoland", "true")
    keyed = {**LOCAL, "OPENDOX_LAND_CONFIRM": "yes", "OPENDOX_AUTO_LAND": "1",
             "OPENDOX_LAND_WITHOUT_CONFIRMATION": "true"}
    with pytest.raises(LandingRefused) as refused:
        NeutralLander(world.root, env=keyed).land(BRANCH, confirmation=None)
    assert refused.value.code == "confirmation:not-a-confirmation"
    assert world.refs() == before

    head = world.head(BRANCH)
    # A STDIN THAT IS NOT A TERMINAL, in a child with no controlling terminal
    # either, the branch name piped in: refused for the stdin, before the
    # terminal is even asked.
    child = textwrap.dedent(f"""
        import sys
        from opendox import landing_confirm
        try:
            landing_confirm.confirm_at_terminal({BRANCH!r}, {head!r})
        except landing_confirm.ConfirmationRefused as refused:
            print(refused.code)
            sys.exit(3)
        print("MINTED")
    """)
    done = subprocess.run([sys.executable, "-c", child], input=f"{BRANCH}\n",
                          text=True, capture_output=True, timeout=120,
                          start_new_session=True)
    assert (done.returncode, done.stdout.strip()) == (3, "stdin-not-a-terminal"), (
        done.stdout, done.stderr)
    # the same in process, and the two other ways the prompt refuses
    at_terminal(monkeypatch, f"{BRANCH}\n", stdin_tty=False)
    with pytest.raises(ConfirmationRefused) as refused:
        landing_confirm.confirm_at_terminal(BRANCH, head)
    assert refused.value.code == "stdin-not-a-terminal"

    def no_terminal():
        raise OSError(6, "No such device or address")
    monkeypatch.setattr(landing_confirm, "_stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(landing_confirm, "_open_controlling_terminal", no_terminal)
    with pytest.raises(ConfirmationRefused) as refused:
        landing_confirm.confirm_at_terminal(BRANCH, head)
    assert refused.value.code == "no-terminal"
    for answer in ("y\n", "yes\n", "\n", f"{BRANCH} \n", "main\n"):
        at_terminal(monkeypatch, answer)
        with pytest.raises(ConfirmationRefused) as refused:
            landing_confirm.confirm_at_terminal(BRANCH, head)
        assert refused.value.code == "answer-mismatch", answer
    assert world.refs() == before

    # THE HUMAN ACT: the branch's name typed at the controlling terminal.
    terminal = at_terminal(monkeypatch, f"{BRANCH}\n")
    confirmation = landing_confirm.confirm_at_terminal(BRANCH, head)
    assert BRANCH in terminal.shown and head in terminal.shown
    assert confirmation.issuer == landing_confirm.ISSUER_TTY
    landed = lander(world).land(BRANCH, confirmation=confirmation)
    assert world.head("refs/heads/main") == landed.merge_commit


def test_land_shows_a_conflict_and_does_not_resolve_it(tmp_path):
    world = World(tmp_path)
    world.branch_with(BRANCH, "doc.md", "the branch's words\n")
    world.on_main("doc.md", "main's words\n")
    before = (world.refs(), world.fingerprint())

    with pytest.raises(MergeConflict) as conflict:
        lander(world).land(BRANCH, confirmation=mint(world))

    assert conflict.value.paths == ("doc.md",)
    assert conflict.value.code == "merge-conflict"
    assert "bring `main` into sess-1" in conflict.value.remedy
    assert "doc.md" in str(conflict.value) and conflict.value.remedy in str(
        conflict.value)
    # nothing merged, nothing resolved, nothing left behind
    assert (world.refs(), world.fingerprint()) == before
    assert world.git("rev-parse", "-q", "--verify", "MERGE_HEAD",
                     check=False) == ""
    assert world.worktrees() == [world.root.resolve()]
    assert (world.root / "doc.md").read_text(encoding="utf-8") == "main's words\n"


def test_a_landed_merge_is_a_commit_that_git_revert_undoes(world):
    previous = world.head("refs/heads/main")
    head = world.head(BRANCH)

    landed = lander(world).land(BRANCH, confirmation=mint(world))

    assert isinstance(landed, Landed)
    assert landed.previous_main == previous and landed.pushed is False
    assert landed.served_checkout == landing.SERVED_FAST_FORWARDED
    # a --no-ff MERGE COMMIT: main's old tip first, the branch's head second
    parents = world.git("rev-list", "--parents", "-n", "1",
                        landed.merge_commit).split()
    assert parents == [landed.merge_commit, previous, head]
    assert world.head("refs/heads/main") == landed.merge_commit
    assert world.head() == landed.merge_commit
    assert (world.root / "notes/session.md").is_file()
    assert landed.revert_command == f"git revert -m 1 {landed.merge_commit}"
    # ...which `git revert -m 1` undoes: the tree is main's before the landing
    world.git("revert", "-m", "1", "--no-edit", landed.merge_commit)
    assert world.tree("HEAD") == world.tree(previous)
    assert not (world.root / "notes/session.md").exists()


def test_no_configuration_enables_automatic_landing(tmp_path):
    """The configuration surface, walked: no key switches a guardrail off.

    Statically, the two landing modules read no environment variable and no git
    configuration (the install mode is read through `runtime.config`, the one
    reading of the selector). Dynamically, every setting openDox declares is set,
    with every plausible landing key beside them, and git's own configuration is
    set the ways that would skip a merge commit or answer a conflict for the
    human: still no landing without a confirmation, a conflict is still shown
    with its paths, and a landing is still a two-parent merge commit."""
    for module in (landing, landing_confirm):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Attribute)
                        and node.attr in {"environ", "environb", "getenv"}), (
                module.__name__, node.lineno)
            assert not (isinstance(node, ast.Name)
                        and node.id in {"environ", "getenv"}), module.__name__
            assert not (isinstance(node, ast.Constant) and node.value == "config"), (
                f"{module.__name__}:{node.lineno} runs `git config`")

    everything = {setting.name: "1" for setting in runtime_config.SETTINGS}
    everything.update(LOCAL)
    everything.update({"OPENDOX_AUTO_LAND": "1", "OPENDOX_LAND_CONFIRM": "yes",
                       "OPENDOX_LAND_WITHOUT_CONFIRMATION": "true",
                       "OPENDOX_LAND_NO_FF": "false", "OPENDOX_GUARDRAILS": "off"})

    world = World(tmp_path)
    for key, value in (("merge.ff", "only"), ("rerere.enabled", "true"),
                       ("rerere.autoUpdate", "true"),
                       ("branch.main.mergeOptions", "-X theirs"),
                       ("opendox.autoland", "true"), ("opendox.confirm", "true")):
        world.git("config", key, value)
    world.branch_with(BRANCH, "doc.md", "the branch's words\n")
    world.on_main("doc.md", "main's words\n")
    # TEACH rerere this exact conflict's resolution, so a merge that consulted it
    # would answer the conflict for the human
    teach = tmp_path / "teach"
    world.git("worktree", "add", "-q", "--detach", str(teach), "main")
    world.git("merge", "--no-ff", "--no-edit", BRANCH, cwd=teach, check=False)
    assert world.git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=teach,
                     check=False), "the teaching merge did not conflict"
    world.write("doc.md", "a recorded resolution\n", cwd=teach)
    world.git("add", "doc.md", cwd=teach)
    world.git("commit", "-q", "-m", "the recorded resolution", cwd=teach)
    world.git("worktree", "remove", "--force", str(teach))
    assert world.git("rerere", "status") == "" and (world.root / ".git/rr-cache").is_dir()

    configured = NeutralLander(world.root, env=everything)
    with pytest.raises(LandingRefused) as refused:
        configured.land(BRANCH, confirmation=None)
    assert refused.value.code == "confirmation:not-a-confirmation"
    with pytest.raises(MergeConflict) as conflict:
        configured.land(BRANCH, confirmation=mint(world))
    assert conflict.value.paths == ("doc.md",), (
        "a recorded resolution answered the conflict for the human")

    # and a clean landing is still a merge COMMIT under `merge.ff=only`
    clean = World(tmp_path / "clean")
    clean.git("config", "merge.ff", "only")
    clean.branch_with(BRANCH, "notes/session.md", "work\n")
    landed = NeutralLander(clean.root, env=everything).land(
        BRANCH, confirmation=mint(clean))
    assert len(clean.git("rev-list", "--parents", "-n", "1",
                         landed.merge_commit).split()) == 3


def test_a_governed_repository_binds_no_lander(world):
    host = domain_profile.register(InstrumentedHost())
    before = world.refs()

    assert landing.repository_governance(world.root, env=LOCAL) == GOVERNED
    assert landing.bound_lander(world.root, env=LOCAL) is None
    # a lander built by hand lands nothing here either
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world))
    assert refused.value.code == "governed"
    # the landing is SUBMITTED through the host's instrument, and nothing merges
    report = landing.request_landing(world.root, BRANCH,
                                     confirmation=mint(world), env=LOCAL)
    assert report["ref"] == f"refs/heads/{BRANCH}"
    assert [port.submitted for port in host.ports][-1] == [BRANCH]
    assert world.refs() == before
    # ...and it is still a confirmed act: no confirmation, nothing submitted
    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, BRANCH, confirmation=None, env=LOCAL)
    assert refused.value.code == "confirmation:not-a-confirmation"
    assert sum(len(port.submitted) for port in host.ports) == 1


def test_an_unknown_governance_binds_no_lander(tmp_path):
    world = World(tmp_path, declaration=None)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    before = world.refs()

    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "no-declaration")
    assert landing.bound_lander(world.root, env=LOCAL) is None
    for attempt in (lambda: lander(world).land(BRANCH, confirmation=mint(world)),
                    lambda: landing.request_landing(world.root, BRANCH,
                                                    confirmation=mint(world),
                                                    env=LOCAL)):
        with pytest.raises(LandingRefused) as refused:
            attempt()
        assert refused.value.code == "no-declaration"
    assert world.refs() == before


def test_a_host_profile_that_fails_to_load_binds_no_lander(world):
    domain_profile.register(HostThatFailsToLoad())

    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "host-failed-to-load")
    assert "the host's adapter module is not installed" in reading.reason
    assert landing.bound_lander(world.root, env=LOCAL) is None
    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, BRANCH, confirmation=mint(world),
                                env=LOCAL)
    assert refused.value.code == "host-failed-to-load"


def test_a_branch_cannot_declare_its_own_governance(tmp_path):
    world = World(tmp_path, declaration=None)
    # the branch ADDS the standalone declaration; `main` has none
    world.branch_with(BRANCH, DECLARATION_PATH, DECLARATION_CONTENT)
    # and the working tree carries one too, uncommitted
    world.write(DECLARATION_PATH, DECLARATION_CONTENT)
    before = world.refs()

    assert landing.repository_governance(world.root, env=LOCAL) == UNKNOWN
    assert landing.bound_lander(world.root, env=LOCAL) is None
    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, BRANCH, confirmation=mint(world),
                                env=LOCAL)
    assert refused.value.code == "no-declaration"
    with pytest.raises(LandingRefused):
        lander(world).land(BRANCH, confirmation=mint(world))
    assert world.refs() == before

    # nor can a branch turn a governed `main` standalone
    governed = World(tmp_path / "governed",
                     declaration=DECLARATION_CONTENT.replace(STANDALONE, GOVERNED))
    governed.branch_with(BRANCH, DECLARATION_PATH, DECLARATION_CONTENT)
    assert landing.repository_governance(governed.root, env=LOCAL) == GOVERNED
    assert landing.bound_lander(governed.root, env=LOCAL) is None


def test_a_registered_host_outranks_any_declaration(world):
    assert landing.repository_governance(world.root, env=LOCAL) == STANDALONE
    host = domain_profile.register(InstrumentedHost())

    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (GOVERNED, "host-instrument")
    assert landing.bound_lander(world.root, env=LOCAL) is None
    landing.request_landing(world.root, BRANCH, confirmation=mint(world), env=LOCAL)
    assert host.ports[-1].submitted == [BRANCH]

    # a host that declares no instrument outranks the declaration too: the
    # repository is governed-without-an-instrument, and nothing lands
    domain_profile.unregister()
    domain_profile.register(HostWithoutAnInstrument())
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (GOVERNED,
                                                  "host-without-an-instrument")
    assert landing.bound_lander(world.root, env=LOCAL) is None
    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, BRANCH, confirmation=mint(world),
                                env=LOCAL)
    assert refused.value.code == "governed-without-an-instrument"


def test_a_directly_constructed_confirmation_is_refused(world):
    before = world.refs()
    with pytest.raises(ConfirmationRefused) as refused:
        Confirmation(BRANCH, world.head(BRANCH), "tty")
    assert refused.value.code == "constructed-directly"
    with pytest.raises(ConfirmationRefused):
        Confirmation()

    # built around the constructor, with every field a minted one would have
    forged = object.__new__(Confirmation)
    for name, value in (("_branch", BRANCH), ("_head", world.head(BRANCH)),
                        ("_issuer", "tty"), ("_key", "0" * 64)):
        object.__setattr__(forged, name, value)
    bare = object.__new__(Confirmation)
    for token in (forged, bare):
        with pytest.raises(LandingRefused) as refused:
            lander(world).land(BRANCH, confirmation=token)
        assert refused.value.code == "confirmation:constructed-directly"
    assert world.refs() == before

    # a minted one cannot be duplicated or rewritten either
    real = mint(world)
    for duplicate in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            duplicate(real)
    with pytest.raises(AttributeError):
        real._branch = "other"
    assert object.__getattribute__(real, "_key") not in repr(real)
    assert real.branch == BRANCH


def test_a_confirmation_for_another_branch_or_head_is_refused(world):
    world.branch_with("sess-2", "notes/other.md", "other work\n")
    main = world.head("refs/heads/main")
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world, "sess-2"))
    assert refused.value.code == "confirmation:another-branch"

    stale = mint(world)                              # minted at the old head
    world.branch_with(BRANCH, "notes/later.md", "a later commit\n")
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=stale)
    assert refused.value.code == "confirmation:another-head"
    assert world.head("refs/heads/main") == main


def test_a_spent_confirmation_is_refused(world):
    confirmation = mint(world)
    landed = lander(world).land(BRANCH, confirmation=confirmation)
    assert confirmation.spent is True

    world.branch_with(BRANCH, "notes/more.md", "more work\n")
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=confirmation)
    assert refused.value.code == "confirmation:spent"
    assert world.head("refs/heads/main") == landed.merge_commit

    # a confirmation refused for its binding is spent by that presentation too
    wrong = mint(world, "main", head=world.head("refs/heads/main"))
    with pytest.raises(LandingRefused):
        lander(world).land(BRANCH, confirmation=wrong)
    with pytest.raises(ConfirmationRefused) as refused:
        landing_confirm.redeem(wrong, branch="main", head=world.head("main"))
    assert refused.value.code == "spent"


# ---- the static check: no module outside the two layers calls an issuer ----

ALLOWED_CALLERS = frozenset({"opendox/cli_branch_actions.py",
                             "opendox/serve_branch_actions.py"})
REACH_NAMES = frozenset(landing_confirm.ISSUER_NAMES) | {"_mint", "_LIVE", "_SPENT"}


def issuer_reaches(source: str) -> list[tuple[int, str]]:
    """Every place a module's source names an issuer: as a name, an attribute,
    an imported name, or a string literal (a `getattr`)."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        name = None
        if isinstance(node, ast.Name):
            name = node.id
        elif isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.alias):
            name = node.asname if node.asname in REACH_NAMES else \
                node.name.rsplit(".", 1)[-1]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            name = node.value
        if name in REACH_NAMES:
            hits.append((getattr(node, "lineno", 0), name))
    return hits


def test_only_the_interactive_layers_call_an_issuer():
    """A STATIC check (12.6a): no module outside the `land` prompt's and the
    confirm route's modules names an issuer, and inside `landing_confirm` the one
    function that builds a token is reached from exactly the two issuers."""
    assert set(landing_confirm.INTERACTIVE_LAYERS) == ALLOWED_CALLERS
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE.parent).as_posix()
        if rel in ALLOWED_CALLERS or rel == "opendox/landing_confirm.py":
            continue
        for line, name in issuer_reaches(path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}:{line} names {name}")
    assert offenders == [], offenders

    # the check is not vacuous: each spelling of a reach is caught
    for planted in ("from opendox.landing_confirm import confirm_at_terminal\n",
                    "import opendox.landing_confirm as lc\nlc.confirm_at_terminal('b', 'h')\n",
                    "nonces = LandingNonces()\n",
                    "x.confirm_nonce('b', 'n')\n",
                    "getattr(lc, 'issue_nonce')\n",
                    "lc._mint('b', 'h', 'tty')\n"):
        assert issuer_reaches(planted), planted

    # INSIDE the module: `_mint` is reached from the two issuers and nowhere
    # else, only `_mint` builds a token around the constructor, and only `_mint`
    # records a live key. So no other issuer exists.
    source = Path(landing_confirm.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    callers, builders, recorders = set(), set(), set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and node.id == "_mint" and function.name != "_mint":
                callers.add(function.name)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "__new__"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "object"):
                builders.add(function.name)
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id == "_LIVE" and isinstance(node.ctx, ast.Store)):
                recorders.add(function.name)
    assert callers == {"confirm_at_terminal", "confirm_nonce"}
    assert builders == {"_mint"}
    assert recorders == {"_mint"}


# ==========================================================================
# T012's named nodes beside them: R2Q7 (a) and ADV-08
# ==========================================================================

def test_a_repository_with_no_main_is_unknown_and_refused_naming_it(tmp_path):
    world = World(tmp_path, initial="trunk")         # declared standalone, on trunk
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    before = world.refs()

    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "no-main")
    assert landing.repository_governance(world.root, env=LOCAL) == UNKNOWN
    assert landing.bound_lander(world.root, env=LOCAL) is None
    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, BRANCH, confirmation=mint(world),
                                env=LOCAL)
    assert refused.value.code == "no-main"
    assert "no branch named `main`" in str(refused.value)
    assert world.refs() == before


def test_no_declaration_refuses_naming_the_file_and_its_content(tmp_path):
    world = World(tmp_path, declaration=None)
    world.branch_with(BRANCH, "notes/session.md", "work\n")

    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, BRANCH, confirmation=mint(world),
                                env=LOCAL)
    message = str(refused.value)
    assert refused.value.code == "no-declaration"
    assert DECLARATION_PATH in message
    assert DECLARATION_CONTENT in message
    assert DECLARATION_CONTENT == ("schema_version: 1\nkind: opendox-governance\n"
                                   "governance: standalone\n")
    # the named file and content, committed to `main` with git, are the remedy
    world.write(DECLARATION_PATH, DECLARATION_CONTENT)
    world.commit("declare standalone", DECLARATION_PATH)
    landed = landing.request_landing(world.root, BRANCH, confirmation=mint(world),
                                     env=LOCAL)
    assert isinstance(landed, Landed)


def test_a_dirty_served_checkout_on_main_is_refused_before_merging(world):
    world.write("doc.md", "an uncommitted edit\n")
    before = (world.refs(), world.fingerprint())

    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world))

    assert refused.value.code == "dirty-served-checkout"
    assert "commit or stash" in str(refused.value) and "doc.md" in str(refused.value)
    assert (world.refs(), world.fingerprint()) == before
    assert world.worktrees() == [world.root.resolve()]
    assert not (world.tmp / "plain-worktrees" / landing.LANDING_SUBDIR).exists()

    # an untracked file makes it not clean too
    world.git("checkout", "--", "doc.md")
    world.write("scratch.txt", "untracked\n")
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world))
    assert refused.value.code == "dirty-served-checkout"
    assert world.refs() == before[0]


# ==========================================================================
# the lander's mechanics (R2Q6 (a); N-16)
# ==========================================================================

class RecordingRunner(session_git.SubprocessGitRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def run(self, cwd, *args):
        self.calls.append((Path(cwd), tuple(args)))
        return super().run(cwd, *args)

    def subcommands(self) -> list[str]:
        return [session_git.command_subcommand(args) for _cwd, args in self.calls]


def test_the_lander_merges_in_its_own_worktree_and_pushes_nothing(world, tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main",
                    str(remote)], check=True, capture_output=True)
    world.git("remote", "add", "origin", str(remote))
    world.git("push", "-q", "origin", "main")
    remote_before = subprocess.run(["git", "-C", str(remote), "for-each-ref"],
                                   text=True, capture_output=True).stdout
    runner = RecordingRunner()

    landed = lander(world, runner=runner).land(BRANCH, confirmation=mint(world))

    # the merge was made in a detached landing worktree under <repo>-worktrees/
    merges = [(cwd, args) for cwd, args in runner.calls
              if session_git.command_subcommand(args) == "merge"]
    no_ff = [cwd for cwd, args in merges if "--no-ff" in args]
    container = (tmp_path / "plain-worktrees" / landing.LANDING_SUBDIR).resolve()
    assert len(no_ff) == 1 and container in no_ff[0].resolve().parents
    # the served checkout moved by the admitted fast-forward and nothing else
    served = [args for cwd, args in merges if cwd.resolve() == world.root.resolve()]
    assert served == [("merge", "--ff-only", landed.merge_commit)]
    # nothing fetched, pulled or pushed, and the remote is as it was
    assert not {"fetch", "pull", "push"} & set(runner.subcommands())
    assert "ls-remote" in runner.subcommands()
    assert landed.pushed is False
    assert subprocess.run(["git", "-C", str(remote), "for-each-ref"], text=True,
                          capture_output=True).stdout == remote_before
    # and the landing worktree is gone
    assert world.worktrees() == [world.root.resolve()]
    assert list(container.iterdir()) == []


def test_a_served_checkout_on_another_branch_is_left_and_main_moves(world):
    world.git("checkout", "-q", "-b", "elsewhere")
    world.write("doc.md", "an edit on another branch, uncommitted\n")
    before = world.fingerprint()

    landed = lander(world).land(BRANCH, confirmation=mint(world))

    assert landed.served_checkout == landing.SERVED_LEFT
    assert world.head("refs/heads/main") == landed.merge_commit
    assert world.fingerprint() == before


def test_main_held_by_another_working_tree_is_refused(world, tmp_path):
    world.git("checkout", "-q", "-b", "elsewhere")
    world.git("worktree", "add", "-q", str(tmp_path / "holder"), "main")
    before = world.refs()
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world))
    assert refused.value.code == "main-checked-out-elsewhere"
    assert world.refs() == before


def test_a_remote_main_that_local_main_lacks_is_refused_naming_the_remedy(world,
                                                                          tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main",
                    str(remote)], check=True, capture_output=True)
    world.git("remote", "add", "origin", str(remote))
    world.git("push", "-q", "origin", "main")
    # someone else advances the remote's main
    other = World(tmp_path / "other", declaration=None)
    other.git("remote", "add", "origin", str(remote))
    other.git("fetch", "-q", "origin")
    other.git("reset", "-q", "--hard", "origin/main")
    other.write("theirs.md", "their work\n")
    other.commit("their work", "theirs.md")
    other.git("push", "-q", "origin", "main")
    before = world.refs()

    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world))
    assert refused.value.code == "remote-main-not-contained"
    assert "git pull" in str(refused.value) and "origin" in str(refused.value)
    assert world.refs() == before


def test_a_remote_with_no_main_and_no_remote_both_pass(tmp_path):
    for case in ("no-remote", "empty-remote", "other-branches-only"):
        world = World(tmp_path / case)
        world.branch_with(BRANCH, "notes/session.md", "work\n")
        if case != "no-remote":
            remote = tmp_path / f"{case}.git"
            subprocess.run(["git", "init", "-q", "--bare", str(remote)],
                           check=True, capture_output=True)
            world.git("remote", "add", "upstream", str(remote))
            if case == "other-branches-only":
                world.git("push", "-q", "upstream", f"{BRANCH}:refs/heads/side")
        landed = lander(world).land(BRANCH, confirmation=mint(world))
        assert world.head("refs/heads/main") == landed.merge_commit, case


def test_several_remotes_and_none_named_origin_are_each_checked(world, tmp_path):
    for name, ahead in (("first", False), ("second", True)):
        remote = tmp_path / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main",
                        str(remote)], check=True, capture_output=True)
        world.git("remote", "add", name, str(remote))
        world.git("push", "-q", name, "main")
        if ahead:
            other = World(tmp_path / f"{name}-clone", declaration=None)
            other.git("remote", "add", "origin", str(remote))
            other.git("fetch", "-q", "origin")
            other.git("reset", "-q", "--hard", "origin/main")
            other.write("theirs.md", "their work\n")
            other.commit("their work", "theirs.md")
            other.git("push", "-q", "origin", "main")
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world))
    assert refused.value.code == "remote-main-not-contained"
    assert "'second'" in str(refused.value)


def test_a_fast_forward_that_no_longer_applies_refuses_leaving_main(world):
    class MainMovesDuringTheMerge(session_git.SubprocessGitRunner):
        moved: str | None = None

        def run(self, cwd, *args):
            done = super().run(cwd, *args)
            if "--no-ff" in args and self.moved is None:
                world.write("late.md", "late\n")
                type(self).moved = world.commit("a late commit on main", "late.md")
            return done

    with pytest.raises(LandingRefused) as refused:
        lander(world, runner=MainMovesDuringTheMerge()).land(
            BRANCH, confirmation=mint(world))
    assert refused.value.code == "fast-forward-no-longer-applies"
    assert world.head("refs/heads/main") == MainMovesDuringTheMerge.moved
    assert world.worktrees() == [world.root.resolve()]


def test_main_moved_under_a_left_checkout_refuses_leaving_main(world):
    world.git("checkout", "-q", "-b", "elsewhere")

    class MainMovesDuringTheMerge(session_git.SubprocessGitRunner):
        moved: str | None = None

        def run(self, cwd, *args):
            done = super().run(cwd, *args)
            if "--no-ff" in args and self.moved is None:
                tree = world.tree("refs/heads/main")
                late = world.git("commit-tree", tree, "-p", "refs/heads/main",
                                 "-m", "late")
                world.git("update-ref", "refs/heads/main", late)
                type(self).moved = late
            return done

    with pytest.raises(LandingRefused) as refused:
        lander(world, runner=MainMovesDuringTheMerge()).land(
            BRANCH, confirmation=mint(world))
    assert refused.value.code == "main-moved"
    assert world.head("refs/heads/main") == MainMovesDuringTheMerge.moved


def test_land_refuses_main_itself_and_a_branch_already_landed(world):
    with pytest.raises(LandingRefused) as refused:
        lander(world).land("main", confirmation=mint(world, "main",
                                                     world.head("main")))
    assert refused.value.code == "branch-is-main"
    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, "main", confirmation=None, env=LOCAL)
    assert refused.value.code == "branch-is-main"
    with pytest.raises(LandingRefused) as refused:
        lander(world).land("no-such", confirmation=None)
    assert refused.value.code == "no-such-branch"

    lander(world).land(BRANCH, confirmation=mint(world))
    with pytest.raises(LandingRefused) as refused:
        lander(world).land(BRANCH, confirmation=mint(world))
    assert refused.value.code == "already-landed"


def test_the_seam_is_one_operation_declared_in_session_pr(world):
    assert landing.LANDING_OPERATIONS == ("land",)
    public = {name for name in dir(landing.LandingPort) if not name.startswith("_")}
    assert public == {"land"}
    assert session_pr.LandingPort is landing.LandingPort
    assert session_pr.repository_governance is landing.repository_governance
    assert {"LandingPort", "repository_governance"} <= set(session_pr.__all__)
    # the pull-request port keeps its three operations, and no merge
    assert session_pr.PORT_OPERATIONS == ("push", "open_or_update", "find_open")
    assert isinstance(lander(world), landing.LandingPort)
    with pytest.raises(TypeError):
        Landed(branch=BRANCH, merge_commit="a" * 40, previous_main="b" * 40,
               served_checkout=landing.SERVED_LEFT, pushed=True)


# ==========================================================================
# the governance reading's edges (fail closed)
# ==========================================================================

@pytest.mark.parametrize("content,why", [
    ("schema_version: 1\nkind: something-else\ngovernance: standalone\n", "kind"),
    ("schema_version: 1\nkind: opendox-governance\ngovernance: standalone\n"
     "auto_land: true\n", "unknown key"),
    ("schema_version: 1\nkind: opendox-governance\n", "missing key"),
    ("schema_version: '1'\nkind: opendox-governance\ngovernance: standalone\n",
     "schema_version"),
    ("schema_version: true\nkind: opendox-governance\ngovernance: standalone\n",
     "schema_version"),
    ("schema_version: 1\nkind: opendox-governance\ngovernance: Standalone\n",
     "neither"),
    ("schema_version: 1\nkind: opendox-governance\ngovernance: governed\n"
     "governance: standalone\n", "twice"),
    ("base: &b {schema_version: 1, kind: opendox-governance}\n<<: *b\n"
     "governance: standalone\n", "merge key"),
    ("- standalone\n", "not a mapping"),
    ("governance: [unclosed\n", "not valid YAML"),
    ("schema_version: 1\nkind: opendox-governance\ngovernance: standalone\n# "
     + "x" * 5000 + "\n", "bytes"),
])
def test_a_declaration_that_is_not_one_is_unknown(tmp_path, content, why):
    world = World(tmp_path, declaration=content)
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "invalid-declaration")
    assert why in reading.reason and DECLARATION_CONTENT in reading.reason
    assert landing.bound_lander(world.root, env=LOCAL) is None


def test_a_declaration_that_is_a_link_or_a_directory_is_unknown(tmp_path):
    linked = World(tmp_path / "linked", declaration=None)
    linked.write("elsewhere.yaml", DECLARATION_CONTENT)
    (linked.root / ".opendox").mkdir()
    (linked.root / DECLARATION_PATH).symlink_to("../elsewhere.yaml")
    linked.commit("a linked declaration", "elsewhere.yaml", DECLARATION_PATH)
    reading = landing.read_governance(linked.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "invalid-declaration")
    assert "symbolic link" in reading.reason

    directory = World(tmp_path / "directory", declaration=None)
    directory.write(f"{DECLARATION_PATH}/inside.txt", "x\n")
    directory.commit("a directory where the file belongs",
                     f"{DECLARATION_PATH}/inside.txt")
    assert landing.repository_governance(directory.root, env=LOCAL) == UNKNOWN


def test_standalone_needs_the_explicit_local_install(world):
    reading = landing.read_governance(world.root, env=HOSTED)
    assert (reading.governance, reading.code) == (UNKNOWN, "install-mode-disagrees")
    assert "OPENDOX_INSTALL_MODE=local or --local" in reading.reason
    assert landing.repository_governance(
        world.root, env={"OPENDOX_INSTALL_MODE": "hosted"}) == UNKNOWN
    # `--local` selects local exactly as the setting does (FR-007; ADV-38)
    assert landing.repository_governance(world.root, local=True, env=HOSTED) == \
        STANDALONE
    assert landing.repository_governance(world.root, env=LOCAL) == STANDALONE
    # and a flag and a setting that disagree are refused, naming both
    reading = landing.read_governance(world.root, local=True,
                                      env={"OPENDOX_INSTALL_MODE": "hosted"})
    assert (reading.governance, reading.code) == (UNKNOWN, "install-mode-refused")
    assert "--local" in reading.reason and "OPENDOX_INSTALL_MODE" in reading.reason
    assert landing.bound_lander(world.root, env=HOSTED) is None
    with pytest.raises(LandingRefused) as refused:
        NeutralLander(world.root, env=HOSTED).land(BRANCH, confirmation=mint(world))
    assert refused.value.code == "install-mode-disagrees"


def test_a_governed_declaration_with_no_host_is_governed_without_an_instrument(
        tmp_path):
    world = World(tmp_path,
                  declaration=DECLARATION_CONTENT.replace(STANDALONE, GOVERNED))
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (GOVERNED, "declared-governed")
    assert landing.bound_lander(world.root, env=LOCAL) is None
    with pytest.raises(LandingRefused) as refused:
        landing.request_landing(world.root, BRANCH, confirmation=mint(world),
                                env=LOCAL)
    assert refused.value.code == "governed-without-an-instrument"


def test_openDox_s_own_default_profile_is_not_a_host(world):
    from opendox import default_profile

    domain_profile.register_default(default_profile)
    assert landing.repository_governance(world.root, env=LOCAL) == STANDALONE
    assert isinstance(landing.bound_lander(world.root, env=LOCAL), NeutralLander)


def test_a_non_callable_instrument_is_a_host_that_failed_to_load(world):
    class BrokenHost(HostWithoutAnInstrument):
        SUBMISSION_INSTRUMENT = "not a factory"

    domain_profile.register(BrokenHost())
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "host-failed-to-load")


def test_a_path_that_is_not_the_top_of_a_working_tree_is_unknown(world, tmp_path):
    for path in (tmp_path / "nowhere", world.root / "notes", tmp_path):
        if path == world.root / "notes":
            path.mkdir(exist_ok=True)
        reading = landing.read_governance(path, env=LOCAL)
        assert (reading.governance, reading.code) == (UNKNOWN, "not-a-repository")


def test_the_view_issuer_is_single_use_and_bound_to_its_branch(world):
    nonces = landing_confirm.LandingNonces()
    head = world.head(BRANCH)
    first = nonces.issue_nonce(BRANCH, head)
    second = nonces.issue_nonce(BRANCH, head)        # replaces the first
    with pytest.raises(ConfirmationRefused) as refused:
        nonces.confirm_nonce(BRANCH, first)
    assert refused.value.code == "nonce-mismatch"
    with pytest.raises(ConfirmationRefused) as refused:
        nonces.confirm_nonce(BRANCH, second)           # spent by the attempt above
    assert refused.value.code == "no-nonce"
    third = nonces.issue_nonce(BRANCH, head)
    confirmation = nonces.confirm_nonce(BRANCH, third)
    assert (confirmation.branch, confirmation.head, confirmation.issuer) == (
        BRANCH, head, landing_confirm.ISSUER_VIEW)
    with pytest.raises(ConfirmationRefused):
        nonces.confirm_nonce(BRANCH, third)
    with pytest.raises(ConfirmationRefused) as refused:
        nonces.issue_nonce(BRANCH, "not-a-commit")
    assert refused.value.code == "bad-binding"


# ==========================================================================
# T012's audit: every repository openDox creates is born on `main`
# ==========================================================================

GIT_RUNNER_CALLEES = frozenset({"_git", "out", "run", "git", "git_raw"})


def _init_calls(source: str) -> list[tuple[int, list[str]]]:
    """Every `git init` an openDox module issues, with its string arguments."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        words: list[str] = []
        for arg in node.args:
            items = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
            for item in items:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    words.append(item.value)
                elif isinstance(item, ast.JoinedStr) and item.values and isinstance(
                        item.values[0], ast.Constant):
                    words.append(str(item.values[0].value) + "{}")
        callee = (node.func.attr if isinstance(node.func, ast.Attribute)
                  else getattr(node.func, "id", ""))
        after_git = any(a == "git" and b == "init" for a, b in zip(words, words[1:]))
        runner_init = callee in GIT_RUNNER_CALLEES and words[:1] == ["init"]
        if after_git or runner_init:
            found.append((node.lineno, words))
    return found


def test_every_repository_opendox_creates_names_its_initial_branch():
    sites = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for line, words in _init_calls(path.read_text(encoding="utf-8")):
            sites[f"{path.relative_to(PACKAGE).as_posix()}:{line}"] = words
    modules = {site.split(":", 1)[0] for site in sites}
    assert {"authoring.py", "conformance_corpus.py",
            "runtime/repository_act.py"} <= modules, sites
    unpinned = [site for site, words in sites.items()
                if not any(w.startswith("--initial-branch=") for w in words)]
    assert unpinned == [], unpinned


def test_the_conformance_corpus_is_born_on_main_whatever_git_defaults_to(
        tmp_path, monkeypatch):
    from opendox.conformance_corpus import EMPTY, POPULATED, transpose

    ambient = tmp_path / "ambient.gitconfig"
    ambient.write_text("[init]\n\tdefaultBranch = trunk\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(ambient))
    shipped = tmp_path / "shipped"
    (shipped / POPULATED / "notes").mkdir(parents=True)
    (shipped / POPULATED / "notes" / "a.md").write_text("# A\n", encoding="utf-8")

    built = transpose(shipped, tmp_path / "transposition")

    for state in (POPULATED, EMPTY):
        held = subprocess.run(["git", "symbolic-ref", "HEAD"], cwd=built / state,
                              text=True, capture_output=True).stdout.strip()
        assert held == "refs/heads/main", (state, held)
