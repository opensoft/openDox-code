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


def refusal(act, *args, **kwargs) -> LandingRefused:
    """The `LandingRefused` one call raises: ONE invocation inside the check."""
    with pytest.raises(LandingRefused) as refused:
        act(*args, **kwargs)
    return refused.value


def confirmation_refusal(act, *args, **kwargs) -> ConfirmationRefused:
    with pytest.raises(ConfirmationRefused) as refused:
        act(*args, **kwargs)
    return refused.value


def parents_of(world: World, commit: str) -> list[str]:
    return world.git("rev-list", "--parents", "-n", "1", commit).split()


# ==========================================================================
# F12.2's thirteen nodes
# ==========================================================================

def test_land_requires_an_explicit_human_act(world, monkeypatch):
    """Every way of building a confirmation that is not a human act is refused:
    a flag, a configuration key, a stdin that is not a terminal. The human act
    itself, the branch name typed at the controlling terminal, lands."""
    before = world.refs()
    port = lander(world)
    head = world.head(BRANCH)
    # A FLAG, or any value that stands in for one.
    for flag in (None, True, 1, "yes", "--yes", BRANCH, {"confirmed": True},
                 (BRANCH, head)):
        refused = refusal(port.land, BRANCH, confirmation=flag)
        assert refused.code == "confirmation:not-a-confirmation", flag
    # A CONFIGURATION KEY: the environment and git's own configuration.
    world.git("config", "opendox.confirm", "true")
    world.git("config", "opendox.autoland", "true")
    keyed = NeutralLander(world.root, env={
        **LOCAL, "OPENDOX_LAND_CONFIRM": "yes", "OPENDOX_AUTO_LAND": "1",
        "OPENDOX_LAND_WITHOUT_CONFIRMATION": "true"})
    refused = refusal(keyed.land, BRANCH, confirmation=None)
    assert refused.code == "confirmation:not-a-confirmation"
    assert world.refs() == before

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
    refused = confirmation_refusal(landing_confirm.confirm_at_terminal, BRANCH, head)
    assert refused.code == "stdin-not-a-terminal"

    def no_terminal():
        raise OSError(6, "No such device or address")
    monkeypatch.setattr(landing_confirm, "_stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(landing_confirm, "_open_controlling_terminal", no_terminal)
    refused = confirmation_refusal(landing_confirm.confirm_at_terminal, BRANCH, head)
    assert refused.code == "no-terminal"
    for answer in ("y\n", "yes\n", "\n", f"{BRANCH} \n", "main\n"):
        at_terminal(monkeypatch, answer)
        refused = confirmation_refusal(landing_confirm.confirm_at_terminal,
                                       BRANCH, head)
        assert refused.code == "answer-mismatch", answer
    assert world.refs() == before

    # THE HUMAN ACT: the branch's name typed at the controlling terminal.
    terminal = at_terminal(monkeypatch, f"{BRANCH}\n")
    confirmation = landing_confirm.confirm_at_terminal(BRANCH, head)
    assert BRANCH in terminal.shown
    assert head in terminal.shown
    assert confirmation.issuer == landing_confirm.ISSUER_TTY
    landed = port.land(BRANCH, confirmation=confirmation)
    assert world.head("refs/heads/main") == landed.merge_commit


def test_land_shows_a_conflict_and_does_not_resolve_it(tmp_path):
    world = World(tmp_path)
    world.branch_with(BRANCH, "doc.md", "the branch's words\n")
    world.on_main("doc.md", "main's words\n")
    before = (world.refs(), world.fingerprint())
    port, token = lander(world), mint(world)

    with pytest.raises(MergeConflict) as caught:
        port.land(BRANCH, confirmation=token)

    conflict = caught.value
    assert conflict.paths == ("doc.md",)
    assert conflict.code == "merge-conflict"
    assert "bring `main` into sess-1" in conflict.remedy
    assert "doc.md" in str(conflict)
    assert conflict.remedy in str(conflict)
    # nothing merged, nothing resolved, nothing left behind
    after = (world.refs(), world.fingerprint())
    assert after == before
    assert world.git("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False) == ""
    assert world.worktrees() == [world.root.resolve()]
    assert (world.root / "doc.md").read_text(encoding="utf-8") == "main's words\n"


def test_a_landed_merge_is_a_commit_that_git_revert_undoes(world):
    previous = world.head("refs/heads/main")
    head = world.head(BRANCH)

    landed = lander(world).land(BRANCH, confirmation=mint(world))

    assert isinstance(landed, Landed)
    assert landed.previous_main == previous
    assert landed.pushed is False
    assert landed.served_checkout == landing.SERVED_FAST_FORWARDED
    # a --no-ff MERGE COMMIT: main's old tip first, the branch's head second
    assert parents_of(world, landed.merge_commit) == [landed.merge_commit,
                                                      previous, head]
    assert world.head("refs/heads/main") == landed.merge_commit
    assert world.head() == landed.merge_commit
    assert (world.root / "notes/session.md").is_file()
    assert landed.revert_command == f"git revert -m 1 {landed.merge_commit}"
    # ...which `git revert -m 1` undoes: the tree is main's before the landing
    world.git("revert", "-m", "1", "--no-edit", landed.merge_commit)
    assert world.tree("HEAD") == world.tree(previous)
    assert not (world.root / "notes/session.md").exists()


def _teach_rerere(world: World, tmp_path: Path) -> None:
    """Record a resolution of the coming conflict, so a merge that consulted
    rerere would answer the conflict for the human."""
    teach = tmp_path / "teach"
    world.git("worktree", "add", "-q", "--detach", str(teach), "main")
    world.git("merge", "--no-ff", "--no-edit", BRANCH, cwd=teach, check=False)
    assert world.git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=teach,
                     check=False), "the teaching merge did not conflict"
    world.write("doc.md", "a recorded resolution\n", cwd=teach)
    world.git("add", "doc.md", cwd=teach)
    world.git("commit", "-q", "-m", "the recorded resolution", cwd=teach)
    world.git("worktree", "remove", "--force", str(teach))
    assert (world.root / ".git/rr-cache").is_dir()


def test_no_configuration_enables_automatic_landing(tmp_path):
    """The configuration surface, walked: no key switches a guardrail off.

    Statically, the two landing modules read no environment variable and no git
    configuration (the install mode is read through `runtime.config`, the one
    reading of the selector). Dynamically, every setting openDox declares is set,
    with every plausible landing key beside them, and git's own configuration is
    set every way that would skip a merge commit or answer a conflict for the
    human (a fast-forward-only merge, a recorded resolution, a strategy that
    keeps one side, an attribute or a fallback that picks a merge driver): still no landing
    without a confirmation, a conflict is still shown with its path, and a
    landing is still a two-parent merge commit."""
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
    union = tmp_path / "union.gitattributes"
    union.write_text("* merge=union\n", encoding="utf-8")
    git_config = (("merge.ff", "only"), ("rerere.enabled", "true"),
                  ("rerere.autoUpdate", "true"), ("pull.twohead", "ours"),
                  ("branch.main.mergeOptions", "-X theirs"),
                  ("core.attributesFile", str(union)), ("merge.default", "union"),
                  ("merge.directoryRenames", "true"),
                  ("opendox.autoland", "true"), ("opendox.confirm", "true"))

    world = World(tmp_path / "conflicting")
    world.branch_with(BRANCH, "doc.md", "the branch's words\n")
    world.on_main("doc.md", "main's words\n")
    world.git("config", "rerere.enabled", "true")
    world.git("config", "rerere.autoUpdate", "true")
    _teach_rerere(world, tmp_path)
    for key, value in git_config:
        world.git("config", key, value)

    configured = NeutralLander(world.root, env=everything)
    refused = refusal(configured.land, BRANCH, confirmation=None)
    assert refused.code == "confirmation:not-a-confirmation"
    token = mint(world)
    with pytest.raises(MergeConflict) as conflict:
        configured.land(BRANCH, confirmation=token)
    assert conflict.value.paths == ("doc.md",), (
        "configuration answered the conflict for the human")

    # and a clean landing is still a merge COMMIT, under the same configuration
    clean = World(tmp_path / "clean")
    for key, value in git_config:
        clean.git("config", key, value)
    clean.branch_with(BRANCH, "notes/session.md", "work\n")
    landed = NeutralLander(clean.root, env=everything).land(
        BRANCH, confirmation=mint(clean))
    assert len(parents_of(clean, landed.merge_commit)) == 3
    assert (clean.root / "notes/session.md").is_file()


def test_a_governed_repository_binds_no_lander(world):
    host = domain_profile.register(InstrumentedHost())
    before = world.refs()

    assert landing.repository_governance(world.root, env=LOCAL) == GOVERNED
    assert landing.bound_lander(world.root, env=LOCAL) is None
    # a lander built by hand lands nothing here either
    port, token = lander(world), mint(world)
    assert refusal(port.land, BRANCH, confirmation=token).code == "governed"
    # the landing is SUBMITTED through the host's instrument, and nothing merges
    token = mint(world)
    report = landing.request_landing(world.root, BRANCH, confirmation=token,
                                     env=LOCAL)
    assert report["ref"] == f"refs/heads/{BRANCH}"
    assert host.ports[-1].submitted == [BRANCH]
    assert world.refs() == before
    # ...and it is still a confirmed act: no confirmation, nothing submitted
    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=None, env=LOCAL)
    assert refused.code == "confirmation:not-a-confirmation"
    assert sum(len(port.submitted) for port in host.ports) == 1


def test_an_unknown_governance_binds_no_lander(tmp_path):
    world = World(tmp_path, declaration=None)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    before = world.refs()

    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "no-declaration")
    assert landing.bound_lander(world.root, env=LOCAL) is None
    port, token = lander(world), mint(world)
    assert refusal(port.land, BRANCH, confirmation=token).code == "no-declaration"
    token = mint(world)
    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)
    assert refused.code == "no-declaration"
    assert world.refs() == before


def test_a_host_profile_that_fails_to_load_binds_no_lander(world):
    domain_profile.register(HostThatFailsToLoad())

    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "host-failed-to-load")
    assert "the host's adapter module is not installed" in reading.reason
    assert landing.bound_lander(world.root, env=LOCAL) is None
    token = mint(world)
    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)
    assert refused.code == "host-failed-to-load"


def test_a_branch_cannot_declare_its_own_governance(tmp_path):
    world = World(tmp_path, declaration=None)
    # the branch ADDS the standalone declaration; `main` has none
    world.branch_with(BRANCH, DECLARATION_PATH, DECLARATION_CONTENT)
    # and the working tree carries one too, uncommitted
    world.write(DECLARATION_PATH, DECLARATION_CONTENT)
    before = world.refs()

    assert landing.repository_governance(world.root, env=LOCAL) == UNKNOWN
    assert landing.bound_lander(world.root, env=LOCAL) is None
    token = mint(world)
    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)
    assert refused.code == "no-declaration"
    port, token = lander(world), mint(world)
    assert refusal(port.land, BRANCH, confirmation=token).code == "no-declaration"
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
    token = mint(world)
    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)
    assert refused.code == "governed-without-an-instrument"


def test_a_branch_that_moves_before_the_submission_submits_nothing(world):
    """The confirmation binds a HEAD, and `submit(branch)` takes a name, so the
    head is read again immediately before the submission: a branch that moved
    while the instrument was built is refused, and nothing is submitted (Copilot
    review of openDox-code#90)."""

    class HostThatMovesTheBranch(InstrumentedHost):
        def SUBMISSION_INSTRUMENT(self, root: Path) -> RecordingSubmissions:  # noqa: N802
            world.branch_with(BRANCH, "notes/late.md", "a later commit\n")
            return super().SUBMISSION_INSTRUMENT(root)

    host = domain_profile.register(HostThatMovesTheBranch())
    confirmed = world.head(BRANCH)
    token = mint(world)

    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)

    assert refused.code == "confirmation:another-head"
    assert confirmed[:12] in str(refused)
    assert world.head(BRANCH) != confirmed
    assert [port.submitted for port in host.ports] == [[]]


def test_a_directly_constructed_confirmation_is_refused(world):
    before = world.refs()
    head = world.head(BRANCH)
    refused = confirmation_refusal(Confirmation, BRANCH, head, "tty")
    assert refused.code == "constructed-directly"
    assert confirmation_refusal(Confirmation).code == "constructed-directly"

    # built around the constructor, with every field a minted one would have
    forged = object.__new__(Confirmation)
    for name, value in (("_branch", BRANCH), ("_head", head),
                        ("_issuer", "tty"), ("_key", "0" * 64)):
        object.__setattr__(forged, name, value)
    bare = object.__new__(Confirmation)
    port = lander(world)
    for token in (forged, bare):
        refused = refusal(port.land, BRANCH, confirmation=token)
        assert refused.code == "confirmation:constructed-directly"
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
    port, token = lander(world), mint(world, "sess-2")
    assert refusal(port.land, BRANCH,
                   confirmation=token).code == "confirmation:another-branch"

    stale = mint(world)                              # minted at the old head
    world.branch_with(BRANCH, "notes/later.md", "a later commit\n")
    assert refusal(port.land, BRANCH,
                   confirmation=stale).code == "confirmation:another-head"
    assert world.head("refs/heads/main") == main


def test_a_spent_confirmation_is_refused(world):
    confirmation = mint(world)
    port = lander(world)
    landed = port.land(BRANCH, confirmation=confirmation)
    assert confirmation.spent is True

    world.branch_with(BRANCH, "notes/more.md", "more work\n")
    assert refusal(port.land, BRANCH,
                   confirmation=confirmation).code == "confirmation:spent"
    assert world.head("refs/heads/main") == landed.merge_commit

    # a confirmation refused for its binding is spent by that presentation too
    main = world.head("refs/heads/main")
    wrong = mint(world, "main", head=main)
    assert refusal(port.land, BRANCH,
                   confirmation=wrong).code == "confirmation:another-branch"
    refused = confirmation_refusal(landing_confirm.redeem, wrong, branch="main",
                                   head=main)
    assert refused.code == "spent"


# ---- the static check: no module outside the two layers calls an issuer ----

ALLOWED_CALLERS = frozenset({"opendox/cli_branch_actions.py",
                             "opendox/serve_branch_actions.py"})
REACH_NAMES = frozenset(landing_confirm.ISSUER_NAMES) | {"_mint", "_LIVE", "_SPENT"}


def _reach_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.alias):
        return node.asname if node.asname in REACH_NAMES else \
            node.name.rsplit(".", 1)[-1]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def issuer_reaches(source: str) -> list[tuple[int, str]]:
    """Every place a module's source names an issuer: as a name, an attribute,
    an imported name, or a string literal (a `getattr`)."""
    return [(getattr(node, "lineno", 0), name)
            for node in ast.walk(ast.parse(source))
            if (name := _reach_name(node)) in REACH_NAMES]


def _inside_landing_confirm() -> tuple[set[str], set[str], set[str]]:
    """Which functions of `landing_confirm` call `_mint`, build a token around
    the constructor, and record a live key."""
    tree = ast.parse(Path(landing_confirm.__file__).read_text(encoding="utf-8"))
    callers, builders, recorders = set(), set(), set()
    functions = [f for f in ast.walk(tree)
                 if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for function in functions:
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and node.id == "_mint" \
                    and function.name != "_mint":
                callers.add(function.name)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "__new__"
                    and getattr(node.func.value, "id", "") == "object"):
                builders.add(function.name)
            if (isinstance(node, ast.Subscript)
                    and getattr(node.value, "id", "") == "_LIVE"
                    and isinstance(node.ctx, ast.Store)):
                recorders.add(function.name)
    return callers, builders, recorders


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
    assert offenders == []

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
    callers, builders, recorders = _inside_landing_confirm()
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
    token = mint(world)
    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)
    assert refused.code == "no-main"
    assert "no branch named `main`" in str(refused)
    assert world.refs() == before


def test_no_declaration_refuses_naming_the_file_and_its_content(tmp_path):
    world = World(tmp_path, declaration=None)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    token = mint(world)

    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)
    message = str(refused)
    assert refused.code == "no-declaration"
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
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "dirty-served-checkout"
    assert "commit or stash" in str(refused)
    assert "doc.md" in str(refused)
    after = (world.refs(), world.fingerprint())
    assert after == before
    assert world.worktrees() == [world.root.resolve()]
    assert not (world.tmp / "plain-worktrees" / landing.LANDING_SUBDIR).exists()

    # an untracked file makes it not clean too
    world.git("checkout", "--", "doc.md")
    world.write("scratch.txt", "untracked\n")
    token = mint(world)
    assert refusal(port.land, BRANCH,
                   confirmation=token).code == "dirty-served-checkout"
    assert world.refs() == before[0]


# ==========================================================================
# the lander's mechanics (R2Q6 (a); N-16)
# ==========================================================================

class RecordingRunner(session_git.SubprocessGitRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[str, ...]]] = []

    def run(self, cwd, *args, **settings):
        self.calls.append((Path(cwd), tuple(args)))
        return super().run(cwd, *args, **settings)

    def subcommands(self) -> list[str]:
        return [session_git.command_subcommand(args) for _cwd, args in self.calls]


def _bare_remote(tmp_path: Path, name: str, *, initial: str | None = "main") -> Path:
    remote = tmp_path / f"{name}.git"
    argv = ["git", "init", "-q", "--bare", str(remote)]
    if initial:
        argv.insert(4, f"--initial-branch={initial}")
    subprocess.run(argv, check=True, capture_output=True)
    return remote


def _advance_remote_main(tmp_path: Path, remote: Path, label: str) -> None:
    """Someone else pushes a commit to the remote's `main`."""
    other = World(tmp_path / label, declaration=None)
    other.git("remote", "add", "origin", str(remote))
    other.git("fetch", "-q", "origin")
    other.git("reset", "-q", "--hard", "origin/main")
    other.write("theirs.md", "their work\n")
    other.commit("their work", "theirs.md")
    other.git("push", "-q", "origin", "main")


def test_the_lander_merges_in_its_own_worktree_and_pushes_nothing(world, tmp_path):
    remote = _bare_remote(tmp_path, "remote")
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
    assert len(no_ff) == 1
    assert container in no_ff[0].resolve().parents
    # the served checkout moved by the admitted fast-forward and nothing else
    served = [args for cwd, args in merges if cwd.resolve() == world.root.resolve()]
    assert served == [(*session_git.SERVED_FAST_FORWARD_ARGV, landed.merge_commit)]
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
    runner = RecordingRunner()

    landed = lander(world, runner=runner).land(BRANCH, confirmation=mint(world))

    assert landed.served_checkout == landing.SERVED_LEFT
    assert world.head("refs/heads/main") == landed.merge_commit
    assert world.fingerprint() == before
    # `main` moved WITH a working tree, the landing worktree's, never by its
    # ref alone: it took `main`, then fast-forwarded it
    container = (world.tmp / "plain-worktrees" / landing.LANDING_SUBDIR).resolve()
    moves = [(cwd, args) for cwd, args in runner.calls
             if session_git.command_subcommand(args) in {"switch", "update-ref"}
             or args == (*session_git.SERVED_FAST_FORWARD_ARGV, landed.merge_commit)]
    assert [args for _cwd, args in moves] == [
        ("switch", "--quiet", "main"),
        (*session_git.SERVED_FAST_FORWARD_ARGV, landed.merge_commit)]
    assert all(container in cwd.resolve().parents for cwd, _args in moves)


def test_no_working_tree_can_take_main_while_the_landing_moves_it(world, tmp_path):
    """The landing worktree HOLDS `main` while it moves it, and git refuses
    `main` to every other working tree meanwhile: the exclusive access a read
    of the holder followed by a ref update could not give (Copilot's second
    review of openDox-code#90)."""
    world.git("checkout", "-q", "-b", "elsewhere")
    late = tmp_path / "late-holder"

    class TriesToTakeMainBeforeTheMove(session_git.SubprocessGitRunner):
        attempt: subprocess.CompletedProcess | None = None

        def run(self, cwd, *args, **settings):
            if args[:2] == session_git.SERVED_FAST_FORWARD_ARGV:
                type(self).attempt = subprocess.run(
                    ["git", "worktree", "add", "-q", str(late), "main"],
                    cwd=str(world.root), text=True, capture_output=True)
            return super().run(cwd, *args, **settings)

    landed = lander(world, runner=TriesToTakeMainBeforeTheMove()).land(
        BRANCH, confirmation=mint(world))

    attempt = TriesToTakeMainBeforeTheMove.attempt
    assert attempt is not None, "the move was not made in a working tree"
    assert attempt.returncode != 0
    assert not late.exists()
    assert world.head("refs/heads/main") == landed.merge_commit
    assert world.worktrees() == [world.root.resolve()]


def test_main_held_by_another_working_tree_is_refused(world, tmp_path):
    world.git("checkout", "-q", "-b", "elsewhere")
    world.git("worktree", "add", "-q", str(tmp_path / "holder"), "main")
    before = world.refs()
    port, token = lander(world), mint(world)
    assert refusal(port.land, BRANCH,
                   confirmation=token).code == "main-checked-out-elsewhere"
    assert world.refs() == before


def test_main_checked_out_during_the_merge_is_refused_before_its_ref_moves(
        world, tmp_path):
    """A working tree that takes `main` while the detached merge is made would be
    left behind a moved ref, so `main` is moved only by a working tree that
    holds it: the landing worktree, which git refuses `main` while another
    holds it (Copilot reviews of openDox-code#90)."""
    world.git("checkout", "-q", "-b", "elsewhere")
    holder = tmp_path / "late-holder"

    class TakesMainDuringTheMerge(session_git.SubprocessGitRunner):
        def run(self, cwd, *args, **settings):
            done = super().run(cwd, *args, **settings)
            if "--no-ff" in args:
                world.git("worktree", "add", "-q", str(holder), "main")
            return done

    previous = world.head("refs/heads/main")
    port, token = lander(world, runner=TakesMainDuringTheMerge()), mint(world)
    refused = refusal(port.land, BRANCH, confirmation=token)
    assert refused.code == "main-checked-out-elsewhere"
    assert str(holder.resolve()) in str(refused)
    assert world.head("refs/heads/main") == previous


def test_a_served_checkout_switched_during_the_fast_forward_is_never_reported(
        world):
    """The guard's reads and the fast-forward are separate processes, and git
    offers no lock against a checkout switched between them. The move that race
    makes is never reported as `main` landing (Copilot review of #90)."""

    class SwitchesBeforeTheFastForward(session_git.SubprocessGitRunner):
        def run(self, cwd, *args, **settings):
            if "--ff-only" in args:
                world.git("checkout", "-q", "-b", "racer")
            return super().run(cwd, *args, **settings)

    previous = world.head("refs/heads/main")
    port = lander(world, runner=SwitchesBeforeTheFastForward())
    token = mint(world)
    refused = refusal(port.land, BRANCH, confirmation=token)
    assert refused.code == "fast-forward-no-longer-applies"
    assert "refs/heads/racer" in str(refused)
    assert world.head("refs/heads/main") == previous


def test_a_remote_main_that_local_main_lacks_is_refused_naming_the_remedy(world,
                                                                          tmp_path):
    remote = _bare_remote(tmp_path, "remote")
    world.git("remote", "add", "origin", str(remote))
    world.git("push", "-q", "origin", "main")
    _advance_remote_main(tmp_path, remote, "other")
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)
    assert refused.code == "remote-main-not-contained"
    assert "git pull" in str(refused)
    assert "origin" in str(refused)
    assert world.refs() == before


@pytest.mark.parametrize("case", ["no-remote", "empty-remote",
                                  "other-branches-only"])
def test_a_remote_with_no_main_and_no_remote_both_pass(tmp_path, case):
    world = World(tmp_path)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    if case != "no-remote":
        remote = _bare_remote(tmp_path, case, initial=None)
        world.git("remote", "add", "upstream", str(remote))
        if case == "other-branches-only":
            world.git("push", "-q", "upstream", f"{BRANCH}:refs/heads/side")
    landed = lander(world).land(BRANCH, confirmation=mint(world))
    assert world.head("refs/heads/main") == landed.merge_commit


def test_several_remotes_and_none_named_origin_are_each_checked(world, tmp_path):
    for name in ("first", "second"):
        world.git("remote", "add", name, str(_bare_remote(tmp_path, name)))
        world.git("push", "-q", name, "main")
    _advance_remote_main(tmp_path, tmp_path / "second.git", "second-clone")
    port, token = lander(world), mint(world)
    refused = refusal(port.land, BRANCH, confirmation=token)
    assert refused.code == "remote-main-not-contained"
    assert "'second'" in str(refused)


def test_a_fast_forward_that_no_longer_applies_refuses_leaving_main(world):
    class MainMovesDuringTheMerge(session_git.SubprocessGitRunner):
        moved: str | None = None

        def run(self, cwd, *args, **settings):
            done = super().run(cwd, *args, **settings)
            if "--no-ff" in args and self.moved is None:
                world.write("late.md", "late\n")
                type(self).moved = world.commit("a late commit on main", "late.md")
            return done

    port = lander(world, runner=MainMovesDuringTheMerge())
    token = mint(world)
    refused = refusal(port.land, BRANCH, confirmation=token)
    assert refused.code == "fast-forward-no-longer-applies"
    assert world.head("refs/heads/main") == MainMovesDuringTheMerge.moved
    assert world.worktrees() == [world.root.resolve()]


@pytest.mark.parametrize("to", ["a late commit", "the branch's head"])
def test_main_moved_under_a_left_checkout_refuses_leaving_main(world, to):
    """`main` is moved only from the tip the merge was made on: a `main` that
    moved meanwhile is refused, even to a commit the merge commit contains
    (where a bare fast-forward would still apply)."""
    world.git("checkout", "-q", "-b", "elsewhere")

    class MainMovesDuringTheMerge(session_git.SubprocessGitRunner):
        moved: str | None = None

        def run(self, cwd, *args, **settings):
            done = super().run(cwd, *args, **settings)
            if "--no-ff" in args and self.moved is None:
                if to == "a late commit":
                    tree = world.tree("refs/heads/main")
                    late = world.git("commit-tree", tree, "-p", "refs/heads/main",
                                     "-m", "late")
                else:
                    late = world.head(BRANCH)
                world.git("update-ref", "refs/heads/main", late)
                type(self).moved = late
            return done

    port = lander(world, runner=MainMovesDuringTheMerge())
    token = mint(world)
    assert refusal(port.land, BRANCH, confirmation=token).code == "main-moved"
    assert world.head("refs/heads/main") == MainMovesDuringTheMerge.moved


def test_a_main_that_does_not_land_on_the_merge_commit_is_never_reported(world):
    """A hook that moves `main` again after the landing worktree fast-forwards
    it: `main` is read after the move, and a landing is reported only where it
    holds the merge commit."""
    world.git("checkout", "-q", "-b", "elsewhere")
    hook = world.hooks / "post-merge"
    hook.write_text(
        "#!/bin/sh\n"
        "[ \"$(git symbolic-ref -q HEAD)\" = refs/heads/main ] || exit 0\n"
        "git update-ref refs/heads/main HEAD^1\n", encoding="utf-8")
    hook.chmod(0o755)
    previous = world.head("refs/heads/main")
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "main-moved"
    assert "did not land on the merge commit" in str(refused)
    assert world.head("refs/heads/main") == previous


def test_land_refuses_main_itself_and_a_branch_already_landed(world):
    port = lander(world)
    token = mint(world, "main", world.head("main"))
    assert refusal(port.land, "main", confirmation=token).code == "branch-is-main"
    refused = refusal(landing.request_landing, world.root, "main",
                      confirmation=None, env=LOCAL)
    assert refused.code == "branch-is-main"
    assert refusal(port.land, "no-such", confirmation=None).code == "no-such-branch"

    port.land(BRANCH, confirmation=mint(world))
    token = mint(world)
    assert refusal(port.land, BRANCH, confirmation=token).code == "already-landed"


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
# git's own merge drivers, and a failure that is not a conflict
# ==========================================================================

def _conflicting_world(tmp_path: Path, *, main_attributes: str | None = None) -> World:
    world = World(tmp_path)
    world.branch_with(BRANCH, "doc.md", "the branch's words\n")
    if main_attributes is not None:
        world.write(".gitattributes", main_attributes)
        world.commit("attributes on main", ".gitattributes")
    world.on_main("doc.md", "main's words\n")
    return world


def test_a_merge_attribute_in_the_tree_cannot_resolve_a_conflict(tmp_path):
    """`merge=union` on `main` would combine both sides' words into a clean merge
    commit; the landing merge takes `.gitattributes` out, so the conflict is
    shown (Copilot review of openDox-code#90)."""
    world = _conflicting_world(tmp_path, main_attributes="doc.md merge=union\n")
    before = world.refs()
    port, token = lander(world), mint(world)
    with pytest.raises(MergeConflict) as conflict:
        port.land(BRANCH, confirmation=token)
    assert conflict.value.paths == ("doc.md",)
    assert world.refs() == before


@pytest.mark.parametrize("attributes,config", [
    ("doc.md merge=union\n", ()),
    ("* merge=mine\n", (("merge.mine.driver", "cp %B %A"),)),
    # `text` NAMED is looked up among the configured drivers first
    ("doc.md merge=text\n", (("merge.text.driver", "cp %B %A"),)),
])
def test_a_merge_driver_this_machine_selects_is_refused_before_merging(
        tmp_path, attributes, config):
    world = _conflicting_world(tmp_path)
    info = Path(world.git("rev-parse", "--git-common-dir"))
    info = (info if info.is_absolute() else world.root / info) / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "attributes").write_text(attributes, encoding="utf-8")
    for key, value in config:
        world.git("config", key, value)
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "merge-driver"
    assert "doc.md" in str(refused)
    assert world.refs() == before
    assert world.worktrees() == [world.root.resolve()]


@pytest.mark.parametrize("config", [
    (("merge.default", "union"),),
    (("merge.default", "text"), ("merge.text.driver", "cp %B %A")),
    (("merge.default", ""), ("merge..driver", "cp %B %A")),
    (("merge.default", "mine"), ("merge.mine.driver", "cp %B %A")),
], ids=["union", "text-hijacked", "empty-name-hijacked", "a-named-driver"])
def test_a_configured_fallback_driver_cannot_resolve_a_conflict(tmp_path, config):
    """`merge.default` picks the driver for every file with NO `merge`
    attribute, so a configured `union` (or any driver configured by name) would
    answer an overlapping edit with a clean two-parent merge (Copilot's second
    review of openDox-code#90). The landing merge names a fallback no
    configuration can know, so git's own three-way merge shows the conflict."""
    world = _conflicting_world(tmp_path)
    for key, value in config:
        world.git("config", key, value)
    before = world.refs()
    port, token = lander(world), mint(world)

    with pytest.raises(MergeConflict) as conflict:
        port.land(BRANCH, confirmation=token)

    assert conflict.value.paths == ("doc.md",)
    assert world.refs() == before
    assert (world.root / "doc.md").read_text(encoding="utf-8") == "main's words\n"


def test_a_directory_rename_stays_a_conflict_whatever_git_is_configured_to_do(
        tmp_path):
    """`main` renames a directory and the branch adds a file under its old name.
    git's default stops and shows where the file should go; with
    `merge.directoryRenames=true` it places the file itself and the merge is
    clean (measured, git 2.43). The landing merge pins git's default."""
    world = World(tmp_path)
    world.write("old/one.md", "one\n")
    world.commit("a directory", "old/one.md")
    world.branch_with(BRANCH, "old/two.md", "the branch's new file\n")
    world.git("mv", "old", "new")
    world.git("commit", "-q", "-m", "main renames the directory")
    world.git("config", "merge.directoryRenames", "true")
    before = world.refs()
    port, token = lander(world), mint(world)

    with pytest.raises(MergeConflict) as conflict:
        port.land(BRANCH, confirmation=token)

    assert conflict.value.paths == ("new/two.md",)
    assert world.refs() == before


def test_a_conflict_names_its_paths_as_they_are_spelled(tmp_path):
    """git QUOTES a path with a non-ASCII byte or a quote unless it is asked for
    NUL-delimited names (`"d\\303\\266k.md"`), so the conflict's paths are read
    with `-z` (Copilot review of openDox-code#90)."""
    world = World(tmp_path)
    names = ("dök.md", 'say "hi".md')
    for name in names:
        world.branch_with(BRANCH, name, "the branch's words\n")
        world.on_main(name, "main's words\n")
    port, token = lander(world), mint(world)

    with pytest.raises(MergeConflict) as conflict:
        port.land(BRANCH, confirmation=token)

    assert conflict.value.paths == names
    assert all(name in str(conflict.value) for name in names)


def test_an_ambient_git_dir_cannot_redirect_the_landing(world, tmp_path):
    """`GIT_DIR` and `GIT_WORK_TREE` outrank the directory a command runs in,
    so a process started with them set (a git hook, an alias) would have had
    the guard approve the served checkout while git merged into another
    repository (Copilot review of openDox-code#90). Every git this product runs
    drops them, so the landing lands where it was asked to."""
    decoy = tmp_path / "decoy"
    world.git("clone", "-q", "--no-local", str(world.root), str(decoy))
    decoy_refs = world.git("for-each-ref", "--format=%(refname) %(objectname)",
                           cwd=decoy)
    port, token = lander(world), mint(world)

    with pytest.MonkeyPatch.context() as ambient:
        ambient.setenv("GIT_DIR", str(decoy / ".git"))
        ambient.setenv("GIT_WORK_TREE", str(decoy))
        landed = port.land(BRANCH, confirmation=token)

    assert world.head("refs/heads/main") == landed.merge_commit
    assert world.head() == landed.merge_commit
    after = world.git("for-each-ref", "--format=%(refname) %(objectname)",
                      cwd=decoy)
    assert after == decoy_refs
    assert world.git("worktree", "list", "--porcelain", cwd=decoy).count(
        "worktree ") == 1


def test_a_merge_that_fails_without_a_conflict_keeps_git_s_reason(world):
    """A conflict-free merge whose commit git cannot make (a hook refuses it)
    leaves `MERGE_HEAD` and no unmerged path: it is `merge-failed` with git's
    words, never a conflict with no paths (Copilot review of #90)."""
    hook = world.hooks / "pre-merge-commit"
    hook.write_text("#!/bin/sh\necho 'the hook refuses this merge' >&2\nexit 1\n",
                    encoding="utf-8")
    hook.chmod(0o755)
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert not isinstance(refused, MergeConflict)
    assert refused.code == "merge-failed"
    assert "the hook refuses this merge" in str(refused)
    assert world.refs() == before


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
    ("schema_version: 1\x00\nkind: opendox-governance\ngovernance: standalone\n",
     "not valid YAML"),
    ("schema_version: 1\nkind: 2001-02-30\ngovernance: standalone\n",
     "not valid YAML"),
    ("[" * 2000 + "]" * 2000 + "\n", "not valid YAML"),
    ("schema_version: 1\nkind: opendox-governance\ngovernance: standalone\n# "
     + "x" * 5000 + "\n", "bytes"),
])
def test_a_declaration_that_is_not_one_is_unknown(tmp_path, content, why):
    world = World(tmp_path, declaration=content)
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "invalid-declaration")
    assert why in reading.reason
    assert DECLARATION_CONTENT in reading.reason
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
    assert landing.repository_governance(world.root, local=True,
                                         env=HOSTED) == STANDALONE
    assert landing.repository_governance(world.root, env=LOCAL) == STANDALONE
    # and a flag and a setting that disagree are refused, naming both
    reading = landing.read_governance(world.root, local=True,
                                      env={"OPENDOX_INSTALL_MODE": "hosted"})
    assert (reading.governance, reading.code) == (UNKNOWN, "install-mode-refused")
    assert "--local" in reading.reason
    assert "OPENDOX_INSTALL_MODE" in reading.reason
    assert landing.bound_lander(world.root, env=HOSTED) is None
    port, token = NeutralLander(world.root, env=HOSTED), mint(world)
    assert refusal(port.land, BRANCH,
                   confirmation=token).code == "install-mode-disagrees"


def test_a_governed_declaration_with_no_host_is_governed_without_an_instrument(
        tmp_path):
    world = World(tmp_path,
                  declaration=DECLARATION_CONTENT.replace(STANDALONE, GOVERNED))
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (GOVERNED, "declared-governed")
    assert landing.bound_lander(world.root, env=LOCAL) is None
    token = mint(world)
    refused = refusal(landing.request_landing, world.root, BRANCH,
                      confirmation=token, env=LOCAL)
    assert refused.code == "governed-without-an-instrument"


def test_openDox_s_own_default_is_a_host_only_when_a_host_registered_it(world):
    """Provenance, not identity (Copilot review of #90): openDox's own default
    profile, registered by an ENTRY POINT, is no host; the same module registered
    by a host through `register()` is a host's registration."""
    from opendox import default_profile

    domain_profile.register_default(default_profile)
    assert landing.repository_governance(world.root, env=LOCAL) == STANDALONE
    assert isinstance(landing.bound_lander(world.root, env=LOCAL), NeutralLander)

    domain_profile.unregister()
    domain_profile.register(default_profile)
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (GOVERNED,
                                                  "host-without-an-instrument")
    assert landing.bound_lander(world.root, env=LOCAL) is None


def test_a_non_callable_instrument_is_a_host_that_failed_to_load(world):
    class BrokenHost(HostWithoutAnInstrument):
        SUBMISSION_INSTRUMENT = "not a factory"

    domain_profile.register(BrokenHost())
    reading = landing.read_governance(world.root, env=LOCAL)
    assert (reading.governance, reading.code) == (UNKNOWN, "host-failed-to-load")


def test_a_path_that_is_not_the_top_of_a_working_tree_is_unknown(world, tmp_path):
    (world.root / "notes").mkdir(exist_ok=True)
    for path in (tmp_path / "nowhere", world.root / "notes", tmp_path):
        reading = landing.read_governance(path, env=LOCAL)
        assert (reading.governance, reading.code) == (UNKNOWN, "not-a-repository")


def test_the_view_issuer_is_single_use_and_bound_to_its_branch(world):
    nonces = landing_confirm.LandingNonces()
    head = world.head(BRANCH)
    first = nonces.issue_nonce(BRANCH, head)
    second = nonces.issue_nonce(BRANCH, head)        # replaces the first
    refused = confirmation_refusal(nonces.confirm_nonce, BRANCH, first)
    assert refused.code == "nonce-mismatch"
    refused = confirmation_refusal(nonces.confirm_nonce, BRANCH, second)
    assert refused.code == "no-nonce"                # spent by the attempt above
    third = nonces.issue_nonce(BRANCH, head)
    confirmation = nonces.confirm_nonce(BRANCH, third)
    assert (confirmation.branch, confirmation.head, confirmation.issuer) == (
        BRANCH, head, landing_confirm.ISSUER_VIEW)
    assert confirmation_refusal(nonces.confirm_nonce, BRANCH,
                                third).code == "no-nonce"
    refused = confirmation_refusal(nonces.issue_nonce, BRANCH, "not-a-commit")
    assert refused.code == "bad-binding"


@pytest.mark.parametrize("presented", ["\ud800", "dök", b"bytes", None],
                         ids=["lone-surrogate", "non-ascii", "bytes", "none"])
def test_a_nonce_that_is_not_an_ascii_string_is_refused_not_raised(world,
                                                                   presented):
    """A JSON body can carry a lone surrogate (`"\\ud800"`), which `encode()`
    cannot encode: it is a mismatch, and the live nonce is spent by it (Copilot
    review of openDox-code#90)."""
    nonces = landing_confirm.LandingNonces()
    issued = nonces.issue_nonce(BRANCH, world.head(BRANCH))
    refused = confirmation_refusal(nonces.confirm_nonce, BRANCH, presented)
    assert refused.code == "nonce-mismatch"
    assert confirmation_refusal(nonces.confirm_nonce, BRANCH,
                                issued).code == "no-nonce"


# ==========================================================================
# T012's audit: every repository openDox creates is born on `main`
# ==========================================================================

GIT_RUNNER_CALLEES = frozenset({"_git", "out", "run", "git", "git_raw"})


def _call_words(node: ast.Call) -> list[str]:
    words: list[str] = []
    for arg in node.args:
        items = arg.elts if isinstance(arg, (ast.List, ast.Tuple)) else [arg]
        for item in items:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                words.append(item.value)
            elif isinstance(item, ast.JoinedStr) and item.values and isinstance(
                    item.values[0], ast.Constant):
                words.append(str(item.values[0].value) + "{}")
    return words


def _init_calls(source: str) -> list[tuple[int, list[str]]]:
    """Every `git init` an openDox module issues, with its string arguments."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        words = _call_words(node)
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
    assert unpinned == []


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
        assert held == "refs/heads/main", state
