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
import gc
import os
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

def test_land_requires_an_explicit_human_act(world, monkeypatch, capsys):
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

    # THE VERB (T016's surface; N-11): no flag stands in for the answer, and a
    # stdin that is not a terminal is refused through `opendox land` itself.
    assert verb_has_no_bypass_flag()
    monkeypatch.setenv("OPENDOX_INSTALL_MODE", "local")
    at_terminal(monkeypatch, f"{BRANCH}\n", stdin_tty=False)
    status, out, err = land_verb(capsys, world.root)
    assert (status, out) == (1, ""), err
    assert "standard input is not a terminal" in err, err
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
                  ("branch.HEAD.mergeOptions", "-X theirs"),
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

    # The landing merges on a DETACHED HEAD, where git applies the options
    # configured for a branch named `HEAD`: `-X theirs` would answer the
    # conflict, and `-s ours` would drop the branch's change with the parents
    # check passing (lane 3's review R2 of openDox-code#90, `6035652847`).
    for n, options in enumerate(("-X theirs", "-s ours")):
        world.git("config", "branch.HEAD.mergeOptions", options)
        with pytest.raises(MergeConflict) as conflict:
            NeutralLander(world.root, env=everything).land(
                BRANCH, confirmation=mint(world))
        assert conflict.value.paths == ("doc.md",), options
        detached = World(tmp_path / f"detached-{n}")
        for key, value in git_config:
            detached.git("config", key, value)
        detached.git("config", "branch.HEAD.mergeOptions", options)
        detached.branch_with(BRANCH, "notes/session.md", "work\n")
        landed = NeutralLander(detached.root, env=everything).land(
            BRANCH, confirmation=mint(detached))
        assert len(parents_of(detached, landed.merge_commit)) == 3
        assert (detached.root / "notes/session.md").is_file(), options


def test_a_governed_repository_binds_no_lander(world):
    host = domain_profile.register(InstrumentedHost())
    before = world.refs()

    assert landing.repository_governance(world.root, env=LOCAL) == GOVERNED
    assert landing.bound_lander(world.root, env=LOCAL) is None
    # ...and the CLI's binding binds none either (T016's surface)
    assert surface_binds_no_lander(world.root)
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
    assert surface_binds_no_lander(world.root)
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
    assert surface_binds_no_lander(world.root)
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
    assert surface_binds_no_lander(world.root)
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


# ---- the static check: only the lander issues the served fast-forward ----

#: The modules that may name the served fast-forward: the lander, and the
#: funnel that defines and guards it.
FAST_FORWARD_MOVERS = frozenset({"opendox/landing.py", "opendox/session_git.py"})
FAST_FORWARD_NAMES = frozenset({"fast_forward_served", "SERVED_FAST_FORWARD_ARGV",
                                "SERVED_FAST_FORWARD_SETTINGS",
                                "served_fast_forward_commit", "--ff-only"})


def _fast_forward_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.alias):
        return node.asname if node.asname in FAST_FORWARD_NAMES else \
            node.name.rsplit(".", 1)[-1]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def fast_forward_reaches(source: str) -> list[tuple[int, str]]:
    """Every place a module's source names the served fast-forward: its
    method, its argv, its settings or its recognizer, as a name, an attribute,
    an imported name or a string (a `getattr`, or `"--ff-only"` passed to
    git). A remedy MESSAGE that quotes the command is an f-string, never the
    string itself."""
    return [(getattr(node, "lineno", 0), name)
            for node in ast.walk(ast.parse(source))
            if (name := _fast_forward_name(node)) in FAST_FORWARD_NAMES]


def test_only_the_lander_issues_the_served_fast_forward():
    """FR-004a's exceptions admit `merge --ff-only <commit>` at the served root
    for ONE act, a confirmed landing fast-forwarding to that merge commit; the
    guard admits that argv for any `SessionGit` caller. So no module but the
    lander (and the funnel that defines it) names it, and a later product path
    that moved the served checkout with no human act turns this red (lane 3's
    review R2 of openDox-code#90, `6035652847`)."""
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE.parent).as_posix()
        if rel in FAST_FORWARD_MOVERS:
            continue
        for line, name in fast_forward_reaches(path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}:{line} names {name}")
    assert offenders == []

    # the check is not vacuous: each spelling of a reach is caught
    for planted in ("git.fast_forward_served(sha)\n",
                    "from opendox.session_git import SERVED_FAST_FORWARD_ARGV\n",
                    "git.git(root, *session_git.SERVED_FAST_FORWARD_ARGV, sha)\n",
                    "git.git(root, 'merge', '--ff-only', sha)\n",
                    "getattr(git, 'fast_forward_served')(sha)\n"):
        assert fast_forward_reaches(planted), planted
    assert not fast_forward_reaches(
        'message = f"run `git merge --ff-only {remote}/{base}`"\n')


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


def test_a_dirty_checkout_s_file_names_cannot_reorder_the_refusal(world):
    """With `core.quotePath=false`, `git status --porcelain` prints a bidi
    override in a file name as it is: the refusal shows it escaped (Copilot's
    fourth review of openDox-code#90)."""
    world.git("config", "core.quotePath", "false")
    world.write("a\u202ebc.md", "untracked\n")
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "dirty-served-checkout"
    assert "\u202e" not in str(refused)
    assert "\\u202e" in str(refused)


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


@pytest.mark.parametrize("ignored,committed", [
    ("local.env", "local.env"),
    ("build/sub/out.bin", "build/sub/out.bin"),
    ("keep", "keep/x"),
], ids=["the-path-itself", "under-an-ignored-directory",
        "a-file-where-a-directory-goes"])
def test_an_ignored_file_the_landing_would_overwrite_is_refused(tmp_path, ignored,
                                                                committed):
    """"Clean" leaves IGNORED files out, and `git merge --ff-only` overwrites an
    ignored file with no word, so a branch that commits an ignored path would
    replace the user's own file (MEASURED, git 2.43). The fast-forward is
    refused naming the file and the remedy; an ignored file out of the way
    blocks nothing (lane 3's review R2 of openDox-code#90, `6035652847`)."""
    world = World(tmp_path)
    world.write(".gitignore", "local.env\nbuild/\nkeep\n*.log\n")
    world.commit("ignore local files", ".gitignore")
    world.git("checkout", "-q", "-b", BRANCH)
    world.write(committed, "the branch's content\n")
    world.git("add", "-f", "--", committed)
    world.git("commit", "-q", "-m", "the branch commits an ignored path")
    world.git("checkout", "-q", "main")
    local = world.write(ignored, "SECRET=the user's own\n")
    aside = world.write("unrelated.log", "an ignored file out of the way\n")
    assert world.fingerprint()[2] == ""              # clean in git's own sense
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "ignored-files-in-the-way"
    assert ignored in str(refused)
    assert "unrelated.log" not in str(refused)
    assert local.read_text(encoding="utf-8") == "SECRET=the user's own\n"
    assert world.refs() == before
    assert world.worktrees() == [world.root.resolve()]

    # the remedy, followed, lands; the ignored file out of the way stays
    local.rename(tmp_path / "moved-aside")
    landed = port.land(BRANCH, confirmation=mint(world))
    assert landed.served_checkout == landing.SERVED_FAST_FORWARDED
    assert (world.root / committed).read_text(encoding="utf-8") == "the branch's content\n"
    assert aside.read_text(encoding="utf-8") == "an ignored file out of the way\n"


# ==========================================================================
# the lander's mechanics (R2Q6 (a); N-16)
# ==========================================================================

class RecordingRunner(session_git.SubprocessGitRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[str, ...]]] = []
        self.settings: list[dict] = []

    def run(self, cwd, *args, **settings):
        self.calls.append((Path(cwd), tuple(args)))
        self.settings.append(settings)
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
        ("-c", f"core.hooksPath={os.devnull}", "switch", "--quiet", "main"),
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


def test_the_remote_check_reads_the_push_url_not_the_fetch_url(world, tmp_path):
    """The owner's later `git push` of `main` goes to the remote's PUSH URL, so
    that is the repository whose `main` local `main` must contain; `ls-remote
    <remote>` would read the FETCH URL (data-model.md § Landed, "The remote
    check"). A remote with several push URLs is refused by name."""
    in_step = _bare_remote(tmp_path, "in-step")
    ahead = _bare_remote(tmp_path, "ahead")
    for remote in (in_step, ahead):
        world.git("push", "-q", str(remote), "main")
    _advance_remote_main(tmp_path, ahead, "ahead-clone")

    # the fetch URL is in step, the push URL is ahead: refused
    world.git("remote", "add", "origin", str(in_step))
    world.git("remote", "set-url", "--push", "origin", str(ahead))
    before = world.refs()
    port, token = lander(world), mint(world)
    refused = refusal(port.land, BRANCH, confirmation=token)
    assert refused.code == "remote-main-not-contained"
    assert "'origin'" in str(refused)
    assert world.refs() == before

    # two push URLs: refused by name, before anything is read or merged
    world.git("remote", "set-url", "--add", "--push", "origin", str(in_step))
    token = mint(world)
    refused = refusal(port.land, BRANCH, confirmation=token)
    assert refused.code == "several-push-urls"
    assert "'origin' has 2 push URLs" in str(refused)
    assert world.refs() == before

    # the fetch URL is ahead, the push URL is in step: it lands
    world.git("remote", "set-url", "origin", str(ahead))
    world.git("config", "--unset-all", "remote.origin.pushurl")
    world.git("remote", "set-url", "--push", "origin", str(in_step))
    landed = port.land(BRANCH, confirmation=mint(world))
    assert world.head("refs/heads/main") == landed.merge_commit


def test_the_push_url_never_reaches_git_argv(world, tmp_path):
    """A push URL may carry a credential, and an argv is readable by any local
    user: the URL travels as a TRANSIENT remote in the command's environment
    (`GIT_CONFIG_COUNT=1`, `remote.<transient>.url`), and the argv names only
    that remote."""
    remote = _bare_remote(tmp_path, "pushed-to-only")
    world.git("push", "-q", str(remote), "main")
    world.git("remote", "add", "origin", str(tmp_path / "fetched-from.git"))
    world.git("remote", "set-url", "--push", "origin", str(remote))
    runner = RecordingRunner()

    landed = lander(world, runner=runner).land(BRANCH, confirmation=mint(world))

    assert world.head("refs/heads/main") == landed.merge_commit
    assert not [args for _cwd, args in runner.calls
                if any(str(remote) in arg for arg in args)]
    probes = [(args, settings) for (_cwd, args), settings
              in zip(runner.calls, runner.settings)
              if session_git.command_subcommand(args) == "ls-remote"]
    assert len(probes) == 1
    (args, settings), = probes
    transient = args[1]
    assert transient.startswith("opendox-probe-")
    assert args == ("ls-remote", transient, "refs/heads/main")
    assert settings["config"] == ((f"remote.{transient}.url", str(remote)),)
    assert settings["env"] == session_git.PROBE_ENVIRONMENT
    assert settings["timeout"] == session_git.PROBE_TIMEOUT


def _a_helper_on_path(tmp_path: Path, monkeypatch, name: str) -> Path:
    """`git-remote-<name>` on PATH, which records that it ran."""
    bin_dir = tmp_path / "helper-bin"
    bin_dir.mkdir(exist_ok=True)
    ran = tmp_path / f"{name}-ran"
    helper = bin_dir / f"git-remote-{name}"
    helper.write_text(f"#!/bin/sh\necho ran >> '{ran}'\nexit 1\n", encoding="utf-8")
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return ran


@pytest.mark.parametrize("url", ["evil://example.invalid/remote.git",
                                 "evil::example.invalid/remote.git"],
                         ids=["scheme", "helper-form"])
def test_a_push_url_that_names_a_helper_is_refused_and_never_runs_it(
        world, tmp_path, monkeypatch, url):
    """`<scheme>://` that git does not carry, and every `<name>::`, makes git
    run `git-remote-<name>` from PATH; the probe refuses before anything runs
    (Copilot's sixth review of openDox-code#90)."""
    ran = _a_helper_on_path(tmp_path, monkeypatch, "evil")
    world.git("remote", "add", "origin", url)
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-transport"
    assert "git-remote-evil" in str(refused)
    assert not ran.exists()
    assert world.refs() == before


def test_a_helper_reached_by_a_url_rewrite_is_refused_and_never_runs(
        world, tmp_path, monkeypatch):
    """`git remote get-url` applies `url.<base>.insteadOf`, so a push URL
    spelled https and rewritten to a helper reads as the helper, and is
    refused before anything runs."""
    ran = _a_helper_on_path(tmp_path, monkeypatch, "evil")
    world.git("config", "url.evil://rewritten/.insteadOf",
              "https://rewrite.invalid/")
    world.git("remote", "add", "origin", "https://rewrite.invalid/remote.git")
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-transport"
    assert not ran.exists()


def test_a_helper_reached_by_a_second_rewrite_never_runs(world, tmp_path,
                                                         monkeypatch):
    """The probe applies `insteadOf` AGAIN to the URL `get-url` printed, so a
    second rewrite (https to https, then https to a helper) passes the
    transport check. The probe's environment admits only the transports git
    carries itself (`GIT_ALLOW_PROTOCOL`), so the helper never runs (MEASURED,
    git 2.43: without it, `git-remote-evil` ran; lane 3's review R2 of
    openDox-code#90 named the double rewrite as not reached)."""
    ran = _a_helper_on_path(tmp_path, monkeypatch, "evil")
    world.git("config", "url.https://second.invalid/.insteadOf",
              "https://first.invalid/")
    world.git("config", "url.evil::second/.insteadOf", "https://second.invalid/")
    world.git("remote", "add", "origin", "https://first.invalid/remote.git")
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-unreadable"
    assert "transport 'evil' not allowed" in str(refused)
    assert not ran.exists()


@pytest.mark.parametrize("url", ["file:///nonexistent/remote.git#ticket=private-value",
                                 "file:///nonexistent/remote.git?ticket= private-value"],
                         ids=["fragment", "spaced-value"])
def test_any_value_the_push_url_carries_never_reaches_a_refusal(world, url):
    """A value under a name no credential pattern knows (`ticket`) is removed
    BY VALUE, because the check holds the URL (Copilot's sixth review of
    openDox-code#90; `submission_push._scrubbed`)."""
    world.git("remote", "add", "origin", url)
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-unreadable"
    assert "private-value" not in str(refused)


def test_a_failed_probe_keeps_only_git_s_own_diagnostic(world, tmp_path):
    """Under `GIT_TRACE_CURL=1` or `GIT_CURL_VERBOSE=1` a failed HTTP probe's
    stderr carries every request header, an `http.extraheader` secret among
    them: the refusal keeps only git's `fatal:` and `error:` lines (Copilot's
    sixth review of openDox-code#90)."""
    remote = _bare_remote(tmp_path, "remote")
    world.git("remote", "add", "origin", str(remote))

    class TracedProbe(session_git.SubprocessGitRunner):
        def run(self, cwd, *args, **settings):
            if args[:1] == ("ls-remote",):
                return subprocess.CompletedProcess(
                    ["git", *args], 128, "",
                    "> GET /info/refs HTTP/1.1\n> X-Private: private-value\n"
                    "< HTTP/1.1 403 Forbidden\nfatal: unable to access "
                    "'https://example.invalid/': The requested URL returned "
                    "error: 403\n")
            return super().run(cwd, *args, **settings)

    port, token = lander(world, runner=TracedProbe()), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-unreadable"
    assert "private-value" not in str(refused)
    assert "X-Private" not in str(refused)
    assert "fatal: unable to access" in str(refused)


def test_the_probe_never_waits_on_a_prompt_or_a_stalled_remote(world, tmp_path,
                                                                monkeypatch):
    """The confirmation is spent before the probe, so the probe is bounded and
    asks no human: ssh runs in batch mode, git's terminal prompt is off, and a
    remote that never answers is refused when the bound passes (Copilot's
    sixth review of openDox-code#90)."""
    bin_dir = tmp_path / "ssh-bin"
    bin_dir.mkdir()
    seen = tmp_path / "ssh-seen"
    fake = bin_dir / "ssh"
    fake.write_text("#!/bin/sh\n"
                    f"echo \"$* prompt=$GIT_TERMINAL_PROMPT\" > '{seen}'\n"
                    "sleep 5\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(session_git, "PROBE_TIMEOUT", 1.0)
    # a repository's own `core.sshCommand` is outranked by the probe's
    # `GIT_SSH_COMMAND`, as it is for the runtime's own push
    # (`local_git_adapter.out_bounded`), so it never runs here
    configured = bin_dir / "configured-ssh"
    configured_ran = tmp_path / "configured-ssh-ran"
    configured.write_text(f"#!/bin/sh\necho ran > '{configured_ran}'\n",
                          encoding="utf-8")
    configured.chmod(0o755)
    world.git("config", "core.sshCommand", str(configured))
    world.git("remote", "add", "origin", "ssh://stalled.invalid/remote.git")
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-unreadable"
    assert "timed out after 1s" in str(refused)
    assert "BatchMode=yes" in seen.read_text(encoding="utf-8")
    assert "prompt=0" in seen.read_text(encoding="utf-8")
    assert not configured_ran.exists()


@pytest.mark.parametrize("spelled", ["\n{path}", "{path}\n"],
                         ids=["leading-newline", "trailing-newline"])
def test_a_push_url_holding_a_newline_is_refused_never_probed(world, tmp_path,
                                                              spelled):
    """A URL holding a newline prints as two records: it is refused, never
    trimmed and probed as another repository (Copilot's sixth review of
    openDox-code#90; `submission_push._the_one_push_url`)."""
    remote = _bare_remote(tmp_path, "remote")
    world.git("push", "-q", str(remote), "main")
    world.git("remote", "add", "origin", str(remote))
    world.git("config", "remote.origin.pushurl", spelled.format(path=remote))
    runner = RecordingRunner()
    port, token = lander(world, runner=runner), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "several-push-urls"
    assert "ls-remote" not in runner.subcommands()


def test_the_transports_are_the_submission_path_s(world):
    from opendox import submission_push
    assert landing._GIT_TRANSPORTS == submission_push._GIT_TRANSPORTS
    assert landing._KEPT_STDERR.pattern == submission_push._KEPT_PUSH_STDERR.pattern


@pytest.mark.parametrize("url", ["/nonexistent/remote.git#token=sekrit-fragment",
                                 "/nonexistent/remote.git?token= sekrit-spaced"],
                         ids=["fragment", "spaced-value"])
def test_a_credential_in_the_push_url_never_reaches_a_refusal(world, url):
    """`git ls-remote` echoes a URL it could not read, and a credential can sit
    in its fragment or after whitespace (Copilot's third review of
    openDox-code#90): the refusal names the remote and redacts the value."""
    world.git("remote", "add", "origin", url)
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-unreadable"
    assert "sekrit" not in str(refused)
    assert "'origin'" in str(refused)
    assert world.refs() == before


@pytest.mark.parametrize("served", ["holds main", "holds another branch"])
def test_no_hook_runs_while_land_moves_anything(world, tmp_path, served):
    """A hook is code, a hooks path inside the tree (husky's `.husky`) is the
    branch author's to write, and a `post-merge` hook that pushed would publish
    a landing that reports `pushed=False` (Copilot's fourth review of
    openDox-code#90). No hook runs in the landing worktree's checkout, the
    merge, the `switch`, or either fast-forward, and the remote is untouched."""
    if served == "holds another branch":
        world.git("checkout", "-q", "-b", "elsewhere")
    remote = _bare_remote(tmp_path, "remote")
    world.git("remote", "add", "origin", str(remote))
    world.git("push", "-q", "origin", "main")
    remote_before = subprocess.run(["git", "-C", str(remote), "for-each-ref"],
                                   text=True, capture_output=True).stdout
    ran = tmp_path / "hooks-ran"
    for name in ("post-checkout", "pre-merge-commit", "prepare-commit-msg",
                 "commit-msg", "post-merge"):
        hook = world.hooks / name
        hook.write_text(
            "#!/bin/sh\n"
            f"echo {name} >> '{ran}'\n"
            f"git push -q '{remote}' HEAD:refs/heads/pushed-by-{name} "
            ">/dev/null 2>&1\n"
            "exit 0\n", encoding="utf-8")
        hook.chmod(0o755)

    landed = lander(world).land(BRANCH, confirmation=mint(world))

    assert world.head("refs/heads/main") == landed.merge_commit
    assert landed.pushed is False
    assert not ran.exists(), ran.read_text(encoding="utf-8")
    assert subprocess.run(["git", "-C", str(remote), "for-each-ref"], text=True,
                          capture_output=True).stdout == remote_before


def test_a_push_url_is_read_as_spelled(world, tmp_path):
    """`/srv/remote.git ` and `/srv/remote.git` are two repositories, so the
    push URL keeps its trailing space (Copilot's fourth review of
    openDox-code#90)."""
    in_step = _bare_remote(tmp_path, "remote")
    world.git("push", "-q", str(in_step), "main")
    ahead = tmp_path / "remote.git "
    subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main",
                    str(ahead)], check=True, capture_output=True)
    world.git("push", "-q", str(ahead), "main")
    _advance_remote_main(tmp_path, ahead, "ahead-clone")
    world.git("remote", "add", "origin", str(in_step))
    world.git("remote", "set-url", "--push", "origin", str(ahead))
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "remote-main-not-contained"
    assert world.refs() == before


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
    """Something moves `main` again right after the landing worktree
    fast-forwards it: `main` is read after the move, and a landing is reported
    only where it holds the merge commit."""
    world.git("checkout", "-q", "-b", "elsewhere")

    class MovesMainAfterTheFastForward(session_git.SubprocessGitRunner):
        def run(self, cwd, *args, **settings):
            done = super().run(cwd, *args, **settings)
            if args[:2] == session_git.SERVED_FAST_FORWARD_ARGV:
                world.git("update-ref", "refs/heads/main", "refs/heads/main^1")
            return done

    previous = world.head("refs/heads/main")
    port = lander(world, runner=MovesMainAfterTheFastForward())
    token = mint(world)

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
    (("branch.HEAD.mergeOptions", "-X theirs"),),
    (("branch.HEAD.mergeOptions", "-s ours"),),
], ids=["union", "text-hijacked", "empty-name-hijacked", "a-named-driver",
        "detached-head-theirs", "detached-head-ours"])
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


@pytest.mark.parametrize("word", ["set", "unset", "unspecified"])
def test_a_driver_named_like_one_of_git_s_own_states_cannot_resolve_a_conflict(
        tmp_path, word):
    """`check-attr` prints `set`, `unset` and `unspecified` for the attribute's
    three states AND for the string values `merge=set`, `merge=unset` and
    `merge=unspecified`, and git looks a string value up among the configured
    drivers first. The driver check cannot tell them apart, so the landing
    merge pins a driver by each of those names to one that fails, and the
    conflict is shown (lane 3's review R2 of openDox-code#90, `6035652847`)."""
    world = _conflicting_world(tmp_path)
    info = Path(world.git("rev-parse", "--git-common-dir"))
    info = (info if info.is_absolute() else world.root / info) / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "attributes").write_text(f"doc.md merge={word}\n", encoding="utf-8")
    world.git("config", f"merge.{word}.driver", "cp %B %A")
    before = world.refs()
    port, token = lander(world), mint(world)

    with pytest.raises(MergeConflict) as conflict:
        port.land(BRANCH, confirmation=token)

    assert conflict.value.paths == ("doc.md",)
    assert world.refs() == before
    assert world.worktrees() == [world.root.resolve()]
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


def _a_name_that_is_not_utf8(tmp_path: Path) -> str | None:
    """A file name whose bytes are not UTF-8 (`\\xff`), as Python spells it
    (`surrogateescape`), where this filesystem takes one; None where not."""
    name = "bad\udcffname.md"
    probe = tmp_path / name
    try:
        probe.write_text("probe\n", encoding="utf-8")
        probe.unlink()
    except (OSError, UnicodeEncodeError):
        return None
    return name


def test_a_conflict_names_its_paths_as_they_are_spelled(tmp_path):
    """git QUOTES a path with a non-ASCII byte or a quote unless it is asked for
    NUL-delimited names (`"d\\303\\266k.md"`), so the conflict's paths are read
    with `-z` (Copilot review of openDox-code#90). They are read as BYTES too:
    text mode turned a carriage return into a newline and raised on a name
    that is not UTF-8 (Copilot 4195681954; openxFactory#656 `6026275158`)."""
    world = World(tmp_path / "world")
    names = ["dök.md", 'say "hi".md', "car\rriage.md"]
    not_utf8 = _a_name_that_is_not_utf8(tmp_path)
    if not_utf8 is not None:
        names.append(not_utf8)
    for name in names:
        world.branch_with(BRANCH, name, "the branch's words\n")
        world.on_main(name, "main's words\n")
    port, token = lander(world), mint(world)

    with pytest.raises(MergeConflict) as conflict:
        port.land(BRANCH, confirmation=token)

    assert set(conflict.value.paths) == set(names)
    assert all(session_git.shown(name) in str(conflict.value) for name in names)


def test_a_driver_set_for_a_name_with_a_carriage_return_is_refused(tmp_path):
    """The merge-driver check asks `check-attr` about the paths either side
    changed. Read in text mode, `car\\rriage.md` became `car\\nriage.md`, the
    check asked about a path no attribute names, and the merge then ran the
    driver this machine sets for the real one, resolving the conflict with no
    human (Copilot 4195681954; openxFactory#656 `6026275158`)."""
    world = World(tmp_path)
    name = "car\rriage.md"
    world.branch_with(BRANCH, name, "the branch's words\n")
    world.on_main(name, "main's words\n")
    info = Path(world.git("rev-parse", "--git-common-dir"))
    info = (info if info.is_absolute() else world.root / info) / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "attributes").write_text('"car\\rriage.md" merge=mine\n',
                                     encoding="utf-8")
    world.git("config", "merge.mine.driver", "cp %B %A")
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "merge-driver"
    assert repr(f"{name} (merge=mine)") in str(refused)
    assert world.refs() == before


def test_a_conflict_path_cannot_write_to_the_terminal(tmp_path):
    """A file name is the branch author's to choose, and the refusal is printed
    where the human reads it: a control character in a conflicting path is
    escaped in the message, and `paths` keeps the name itself (Copilot's third
    review of openDox-code#90)."""
    world = World(tmp_path)
    name = "e\x1b[2Jvil\nname.md"
    world.branch_with(BRANCH, name, "the branch's words\n")
    world.on_main(name, "main's words\n")
    port, token = lander(world), mint(world)

    with pytest.raises(MergeConflict) as conflict:
        port.land(BRANCH, confirmation=token)

    assert conflict.value.paths == (name,)
    message = str(conflict.value)
    assert "\x1b" not in message
    assert "\n" not in message
    assert repr(name) in message


def test_a_driver_refusal_cannot_write_to_the_terminal(tmp_path):
    world = World(tmp_path)
    name = "e\x1b]0;title\x07vil.md"
    world.branch_with(BRANCH, name, "the branch's words\n")
    info = Path(world.git("rev-parse", "--git-common-dir"))
    info = (info if info.is_absolute() else world.root / info) / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "attributes").write_text("* merge=mine\n", encoding="utf-8")
    world.git("config", "merge.mine.driver", "cp %B %A")
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "merge-driver"
    assert "\x1b" not in str(refused)
    assert "\x07" not in str(refused)
    assert repr(f"{name} (merge=mine)") in str(refused)


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
    """A conflict-free merge that git refuses (here, an unsigned branch under
    `merge.verifySignatures`; no hook runs in a landing) leaves no unmerged
    path: it is `merge-failed` with git's words, never a conflict with no paths
    (Copilot review of #90)."""
    world.git("config", "merge.verifySignatures", "true")
    before = world.refs()
    port, token = lander(world), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert not isinstance(refused, MergeConflict)
    assert refused.code == "merge-failed"
    assert "does not have a GPG signature" in str(refused)
    assert world.refs() == before


class GitWithoutAttrSource(session_git.SubprocessGitRunner):
    """A git older than `landing.ATTR_SOURCE_FLOOR`: `--attr-source` is an
    unknown option, answered as such a git answers it (exit 129, a usage
    text)."""

    def run(self, cwd, *args, **settings):
        refused = [arg for arg in args if arg.startswith("--attr-source")]
        if not refused:
            return super().run(cwd, *args, **settings)
        said = (f"unknown option: {refused[0]}\n"
                "usage: git [-v | --version] [-h | --help] [-C <path>] "
                "[-c <name>=<value>]\n")
        if settings.get("binary"):
            return subprocess.CompletedProcess(["git", *args], 129, b"",
                                               said.encode())
        return subprocess.CompletedProcess(["git", *args], 129, "", said)


@pytest.mark.parametrize("shape", ["changes a file", "an empty commit"])
def test_a_git_without_attr_source_is_refused_by_name(tmp_path, shape):
    """data-model.md § Landed: an older git is "refused by name". Where the
    branch changes a file, git stops at the driver check's `check-attr
    --attr-source`; where it changes none, at the merge. Either way the refusal
    is `merge-failed` naming the git `land` needs, never a raw `GitError`, and
    nothing moved (lane 3's review R2 of openDox-code#90, `6035652847`)."""
    world = World(tmp_path)
    if shape == "changes a file":
        world.branch_with(BRANCH, "notes/session.md", "work\n")
    else:
        world.git("checkout", "-q", "-b", BRANCH)
        world.git("commit", "-q", "--allow-empty", "-m", "nothing changed")
        world.git("checkout", "-q", "main")
    before = world.refs()
    port, token = lander(world, runner=GitWithoutAttrSource()), mint(world)

    refused = refusal(port.land, BRANCH, confirmation=token)

    assert refused.code == "merge-failed"
    assert f"git {landing.ATTR_SOURCE_FLOOR} or later" in str(refused)
    assert "usage:" not in str(refused)
    assert world.refs() == before
    assert world.worktrees() == [world.root.resolve()]


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


def test_a_checkout_whose_path_ends_in_a_space_is_read(tmp_path):
    """The working tree's top is compared as git spells it, a trailing space
    included (Copilot's fourth review of openDox-code#90)."""
    world = World(tmp_path)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    spaced = tmp_path / "plain "
    world.root.rename(spaced)
    world.root = spaced

    assert landing.repository_governance(spaced, env=LOCAL) == STANDALONE
    landed = NeutralLander(spaced, env=LOCAL).land(BRANCH,
                                                   confirmation=mint(world))
    assert world.head("refs/heads/main") == landed.merge_commit


def test_a_checkout_whose_path_ends_in_a_newline_is_read(tmp_path):
    """The top is asked of git (inside a working tree, empty prefix), never
    compared as a path, so a legal directory name ending in a newline reads
    (Copilot's sixth review of openDox-code#90)."""
    world = World(tmp_path)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    newline = tmp_path / "plain\n"
    world.root.rename(newline)
    world.root = newline

    assert landing.repository_governance(newline, env=LOCAL) == STANDALONE


def test_a_path_that_is_not_the_top_of_a_working_tree_is_unknown(world, tmp_path):
    (world.root / "notes").mkdir(exist_ok=True)
    bare = _bare_remote(tmp_path, "bare")
    for path in (tmp_path / "nowhere", world.root / "notes", tmp_path, bare,
                 world.root / ".git"):
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


def test_a_branch_name_cannot_reorder_a_refusal(tmp_path):
    """A bidi override in a branch name is shown escaped in every message that
    names the branch: the conflict, its remedy, and the already-landed
    refusal (Copilot's sixth review of openDox-code#90)."""
    world = World(tmp_path)
    name = "sess\u202e1"
    world.branch_with(name, "doc.md", "the branch's words\n")
    world.on_main("doc.md", "main's words\n")
    port = lander(world)

    with pytest.raises(MergeConflict) as conflict:
        port.land(name, confirmation=mint(world, name))

    assert "\u202e" not in str(conflict.value)
    assert repr(name) in conflict.value.remedy
    world.git("checkout", "-q", "main")
    world.git("merge", "-q", "-X", "ours", "--no-edit", name)
    refused = refusal(port.land, name, confirmation=mint(world, name))
    assert refused.code == "already-landed"
    assert "\u202e" not in str(refused)


@pytest.mark.parametrize("issuer", ["terminal", "view"])
def test_a_branch_name_ending_in_a_no_break_space_can_be_confirmed(
        world, monkeypatch, issuer):
    """git takes `sess-1\u00a0` as a branch, so both issuers mint for it: the
    binding refuses only an empty name, never one a strip would change
    (Copilot's sixth review of openDox-code#90)."""
    name = "sess-1\u00a0"
    world.branch_with(name, "notes/nbsp.md", "work\n")
    head = world.head(f"refs/heads/{name}")
    if issuer == "terminal":
        at_terminal(monkeypatch, name + "\n")
        token = landing_confirm.confirm_at_terminal(name, head)
    else:
        nonces = landing_confirm.LandingNonces()
        token = nonces.confirm_nonce(name, nonces.issue_nonce(name, head))
    assert (token.branch, token.head) == (name, head)
    landed = lander(world).land(name, confirmation=token)
    assert world.head("refs/heads/main") == landed.merge_commit


def test_the_prompt_shows_a_branch_name_escaped(world, monkeypatch):
    """git accepts a bidi override in a branch name, which would reorder the
    name the human reads at the prompt: it is shown escaped, and the answer
    must still be the exact name (Copilot's fourth review of
    openDox-code#90)."""
    name = "sess\u202e1"
    world.branch_with(name, "notes/bidi.md", "work\n")
    head = world.head(f"refs/heads/{name}")
    terminal = at_terminal(monkeypatch, name + "\n")

    token = landing_confirm.confirm_at_terminal(name, head)

    assert "\u202e" not in terminal.shown
    assert repr(name) in terminal.shown
    assert (token.branch, token.head) == (name, head)
    at_terminal(monkeypatch, repr(name) + "\n")
    refused = confirmation_refusal(landing_confirm.confirm_at_terminal, name, head)
    assert refused.code == "answer-mismatch"


def test_a_discarded_confirmation_leaves_no_record(world):
    """The registry forgets a key once its token is gone, so a long-running
    server keeps no record per confirmation it ever minted; a spent token still
    held keeps its record and is still refused as spent (Copilot's third review
    of openDox-code#90)."""
    nonces = landing_confirm.LandingNonces()
    head = world.head(BRANCH)
    unspent = nonces.confirm_nonce(BRANCH, nonces.issue_nonce(BRANCH, head))
    spent = nonces.confirm_nonce(BRANCH, nonces.issue_nonce(BRANCH, head))
    landing_confirm.redeem(spent, branch=BRANCH, head=head)
    keys = {object.__getattribute__(token, "_key") for token in (unspent, spent)}
    assert confirmation_refusal(landing_confirm.redeem, spent, branch=BRANCH,
                                head=head).code == "spent"

    del unspent, spent
    gc.collect()

    assert not keys & set(landing_confirm._LIVE)
    assert not keys & landing_confirm._SPENT


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


# ==========================================================================
# T016: the surface. The `land` verb, the two routes, the `actions.land`
# key and the confirm control (contracts/cli-http-submit-land.md; 12.6a;
# R2Q1, R2Q3, R2Q4, R2Q5, R2Q9 (a) item 7; N-2, N-11, OQ-12-13, OQ-12-14)
# ==========================================================================

import contextlib  # noqa: E402
import http.client  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import threading  # noqa: E402

import route_extension  # noqa: E402
from opendox import cli, cli_branch_actions, serve, serve_branch_actions  # noqa: E402

WEB = PACKAGE / "web"
NODE = shutil.which("node")
#: The two routes, as the contract spells them (OQ-12-13).
NONCE_ROUTE = "/actions/session/land-nonce"
LAND_ROUTE = "/actions/session/land"
#: The `Landed` object both doors answer (data-model.md § Landed).
LANDED_FIELDS = {"branch", "merge_commit", "previous_main", "served_checkout",
                 "pushed"}
#: A credential a host's instrument carries, ASSEMBLED, never spelled whole.
SECRET = "S3CRET-" + "from-the-instrument"


def surface_binds_no_lander(root: Path) -> bool:
    """T016's two bindings bind no lander for `root`: the CLI's `_landing_port`
    with and without `--local`, and the server's default `landing_factory`."""
    return (all(cli._landing_port(root, local=local) is None
                for local in (True, False))
            and serve.served_lander(root) is None)


def _land_parser():
    import argparse

    from opendox import default_profile

    parser = argparse.ArgumentParser(prog="opendox")
    sub = parser.add_subparsers(dest="command", required=True)
    for extension in default_profile.SUBCOMMAND_EXTENSIONS:
        extension.register(sub)
    return parser, sub.choices["land"]


def verb_has_no_bypass_flag() -> bool:
    """N-11: `land` takes exactly `--repo-root`, `--branch`, `--local` and
    `--json`, and every flag that could stand in for the human's answer is
    refused by the parser itself."""
    parser, land = _land_parser()
    options = {option for action in land._actions
               for option in action.option_strings}
    if options != {"-h", "--help", "--repo-root", "--branch", "--local", "--json"}:
        return False
    for flag in ("--yes", "-y", "--confirm", "--force", "--no-confirm",
                 "--non-interactive", "--assume-yes", "--confirmation=sess-1"):
        try:
            with contextlib.redirect_stderr(io_sink()):
                parser.parse_args(["land", "--repo-root", "r", "--branch", "b",
                                   flag])
        except SystemExit:
            continue
        return False
    return True


def io_sink():
    import io

    return io.StringIO()


def land_verb(capsys, root: Path, *extra: str, branch: str = BRANCH):
    """`opendox land` in this process: the exit status, stdout and stderr."""
    status = cli.main(["land", "--repo-root", str(root), "--branch", branch,
                       *extra])
    out, err = capsys.readouterr()
    return status, out, err


@pytest.fixture
def local_install(monkeypatch):
    """The explicit local install, as the environment selects it."""
    monkeypatch.setenv("OPENDOX_INSTALL_MODE", "local")


class SubmittingPort:
    """A governed host's instrument: a `SubmissionPort` whose `Submission`
    names where the work went, or that raises what it is given."""

    def __init__(self, root: Path, *, url: str = "https://forge.example/team/repo",
                 raises: BaseException | None = None) -> None:
        self.root = root
        self.url = url
        self.raises = raises
        self.submitted: list[str] = []

    def submit(self, branch: str):
        self.submitted.append(branch)
        if self.raises is not None:
            raise self.raises
        commit = subprocess.run(["git", "rev-parse", f"refs/heads/{branch}"],
                                cwd=self.root, text=True,
                                capture_output=True).stdout.strip()
        return session_pr.Submission(remote="review", ref=f"refs/heads/{branch}",
                                     url=self.url, branch=branch, commit=commit)


class SubmittingHost:
    """A registered TEST host that declares an instrument (R2Q3 (a))."""

    SUBCOMMAND_EXTENSIONS: tuple = ()
    ROUTE_EXTENSIONS: tuple = ()

    def __init__(self, **port) -> None:
        self.port_kwargs = port
        self.ports: list[SubmittingPort] = []

    def SUBMISSION_INSTRUMENT(self, root: Path) -> SubmittingPort:  # noqa: N802
        port = SubmittingPort(Path(root), **self.port_kwargs)
        self.ports.append(port)
        return port

    def submitted(self) -> list[str]:
        return [branch for port in self.ports for branch in port.submitted]


class SubmittingHostWithTheVerb(SubmittingHost):
    """The same test host, carrying openDox's own branch verbs, so the host
    side of `opendox land` runs (R2Q3 (a): no production host carries them)."""

    SUBCOMMAND_EXTENSIONS: tuple = (cli_branch_actions.BranchActionSubcommands(),)


class BranchActionsOnTop:
    """openDox's own branch-action routes and their mixin, contributed ON TOP
    of a test host, so the host side of the routes runs (R2Q3 (a))."""

    HANDLER_CONTRIBUTIONS = (serve_branch_actions.BranchActionRoutes,)

    def routes(self):
        return serve_branch_actions.BranchActionRouteExtension().routes()


@contextlib.contextmanager
def serving(root: Path, tmp_path: Path, *, host: str = "127.0.0.1",
            actor: str | None = "tester", **injected):
    """`serve.build_server` over `root`, serving on a thread."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"generation": {}}), encoding="utf-8")
    httpd = serve.build_server(WEB, snapshot, root, host=host, port=0,
                               actor=actor, **injected)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=10)


def ask(httpd, method: str, path: str, payload=None, *, token: str | None = None,
        headers: dict | None = None, raw: bytes | None = None):
    """One request over loopback: the status and the parsed JSON body."""
    connection = http.client.HTTPConnection(
        "127.0.0.1", httpd.server_address[1], timeout=60)
    try:
        body = raw if raw is not None else (
            None if payload is None else json.dumps(payload).encode())
        sent = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            sent[serve.CONSOLE_TOKEN_HEADER] = token
        sent.update(headers or {})
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        data = response.read()
        return response.status, (json.loads(data) if data else None)
    finally:
        connection.close()


def capabilities(httpd) -> dict:
    status, caps = ask(httpd, "GET", serve.CAPABILITIES_ROUTE)
    assert status == 200, caps
    return caps


def bound_class(httpd) -> type:
    return getattr(httpd.RequestHandlerClass, "func", httpd.RequestHandlerClass)


def nonce_for(httpd, branch: str = BRANCH) -> dict:
    status, body = ask(httpd, "POST", NONCE_ROUTE, {"branch": branch},
                       token=httpd.console_token)
    assert status == 200, body
    return body


# ---- the verb --------------------------------------------------------------

def test_the_land_verb_has_no_bypass_flag():
    """N-11 (12.6a: "refuses when there is none"): the verb's options are the
    ratified four, and no flag can answer for the human."""
    assert verb_has_no_bypass_flag()


def test_land_at_the_terminal_lands_and_names_the_revert(world, monkeypatch,
                                                         capsys, local_install):
    previous = world.head("refs/heads/main")
    terminal = at_terminal(monkeypatch, f"{BRANCH}\n")

    status, out, err = land_verb(capsys, world.root)

    assert (status, err) == (0, ""), err
    merge = world.head("refs/heads/main")
    assert parents_of(world, merge) == [merge, previous, world.head(BRANCH)]
    assert BRANCH in terminal.shown and world.head(BRANCH) in terminal.shown
    assert f"git revert -m 1 {merge}" in out
    assert "fast-forwarded" in out and previous in out
    assert "pushed nothing" in out


def test_land_json_prints_the_landed_object(world, monkeypatch, capsys,
                                            local_install):
    previous = world.head("refs/heads/main")
    at_terminal(monkeypatch, f"{BRANCH}\n")

    status, out, err = land_verb(capsys, world.root, "--json")

    assert (status, err) == (0, ""), err
    landed = json.loads(out)
    assert set(landed) == LANDED_FIELDS
    assert landed == {"branch": BRANCH,
                      "merge_commit": world.head("refs/heads/main"),
                      "previous_main": previous,
                      "served_checkout": landing.SERVED_FAST_FORWARDED,
                      "pushed": False}


def test_land_with_a_piped_stdin_and_no_terminal_is_refused(world, tmp_path):
    """The installed verb in a child with NO controlling terminal and the
    branch name piped to stdin: refused by name, no traceback, nothing moved."""
    before = world.refs()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "XF_"))}
    env["OPENDOX_INSTALL_MODE"] = "local"
    done = subprocess.run(
        [sys.executable, "-m", "opendox.cli", "land", "--repo-root",
         str(world.root), "--branch", BRANCH],
        input=f"{BRANCH}\n", text=True, capture_output=True, timeout=180,
        start_new_session=True, env=env, cwd=tmp_path)
    assert done.returncode == 1, (done.stdout, done.stderr)
    assert "land refused:" in done.stderr
    assert "standard input is not a terminal" in done.stderr
    assert "Traceback" not in done.stderr
    assert world.refs() == before


def test_land_refuses_main_before_it_asks(world, monkeypatch, capsys,
                                          local_install):
    before = world.refs()
    terminal = at_terminal(monkeypatch, "main\n")
    status, out, err = land_verb(capsys, world.root, branch="main")
    assert (status, out) == (1, ""), err
    assert "does not take `main` itself" in err
    assert terminal.shown == "", "the human was asked to confirm a refusal"
    assert world.refs() == before


def test_land_refuses_a_branch_that_does_not_exist_before_it_asks(
        world, monkeypatch, capsys, local_install):
    terminal = at_terminal(monkeypatch, "sess-9\n")
    status, _out, err = land_verb(capsys, world.root, branch="sess-9")
    assert status == 1
    assert "no local branch 'sess-9'" in err
    assert terminal.shown == ""


def test_land_with_no_declaration_names_the_file_and_content_before_it_asks(
        tmp_path, monkeypatch, capsys, local_install):
    world = World(tmp_path, declaration=None)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    before = world.refs()
    terminal = at_terminal(monkeypatch, f"{BRANCH}\n")
    status, _out, err = land_verb(capsys, world.root)
    assert status == 1
    assert DECLARATION_PATH in err and DECLARATION_CONTENT in err
    assert terminal.shown == ""
    assert world.refs() == before


def test_a_governed_declaration_with_no_host_is_refused_by_the_verb(
        tmp_path, monkeypatch, capsys, local_install):
    world = World(tmp_path,
                  declaration=DECLARATION_CONTENT.replace(STANDALONE, GOVERNED))
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    before = world.refs()
    at_terminal(monkeypatch, f"{BRANCH}\n")
    status, _out, err = land_verb(capsys, world.root)
    assert status == 1
    assert "governed-without-an-instrument" in err
    assert world.refs() == before


def test_land_local_beside_hosted_is_refused_naming_both(world, monkeypatch,
                                                         capsys):
    """R2Q9 (a) item 7: the flag and the setting disagree, so it is refused,
    naming both, and nothing lands."""
    monkeypatch.setenv("OPENDOX_INSTALL_MODE", "hosted")
    before = world.refs()
    terminal = at_terminal(monkeypatch, f"{BRANCH}\n")
    status, _out, err = land_verb(capsys, world.root, "--local")
    assert status == 1
    assert "--local" in err and "OPENDOX_INSTALL_MODE=hosted" in err
    assert terminal.shown == ""
    assert world.refs() == before


def test_land_without_the_local_install_is_refused(world, monkeypatch, capsys):
    """A standalone declaration on the HOSTED install (unset is hosted) is
    `unknown` (FR-007): no lander, and the verb names the local install."""
    monkeypatch.delenv("OPENDOX_INSTALL_MODE", raising=False)
    before = world.refs()
    status, _out, err = land_verb(capsys, world.root)
    assert status == 1
    assert "OPENDOX_INSTALL_MODE=local or --local" in err
    assert world.refs() == before
    # ...and `--local` is exactly the setting
    at_terminal(monkeypatch, f"{BRANCH}\n")
    status, _out, err = land_verb(capsys, world.root, "--local")
    assert (status, err) == (0, ""), err


def test_land_shows_a_conflict_through_the_verb(tmp_path, monkeypatch, capsys,
                                                local_install):
    world = World(tmp_path)
    world.branch_with(BRANCH, "doc.md", "the branch's words\n")
    world.on_main("doc.md", "main's words\n")
    before = world.refs()
    at_terminal(monkeypatch, f"{BRANCH}\n")
    status, out, err = land_verb(capsys, world.root)
    assert (status, out) == (1, ""), err
    assert "doc.md" in err and "bring `main` into sess-1" in err
    assert world.refs() == before


def test_land_under_a_governed_host_submits_through_the_instrument(
        world, monkeypatch, capsys, local_install):
    """R2Q4 (a): the verb submits through the host's instrument and reports
    where the work went; nothing merges here."""
    host = domain_profile.register(SubmittingHostWithTheVerb())
    before = world.refs()
    at_terminal(monkeypatch, f"{BRANCH}\n")
    status, out, err = land_verb(capsys, world.root, "--json")
    assert (status, err) == (0, ""), err
    assert json.loads(out) == {"remote": "review", "ref": f"refs/heads/{BRANCH}",
                               "url": "https://forge.example/team/repo",
                               "branch": BRANCH, "commit": world.head(BRANCH)}
    assert host.submitted() == [BRANCH]
    assert world.refs() == before


def test_an_instruments_words_are_redacted_by_the_verb(world, monkeypatch,
                                                       capsys, local_install):
    """12.1a at this boundary: an instrument's report URL, its refusal, and a
    failure it did not name reach no output with the credential in them."""
    leaky = f"https://alice:{SECRET}@forge.example/team/repo?token={SECRET}"
    domain_profile.register(SubmittingHostWithTheVerb(url=leaky))
    at_terminal(monkeypatch, f"{BRANCH}\n")
    status, out, err = land_verb(capsys, world.root)
    assert status == 0, err
    assert SECRET not in out + err and "forge.example/team/repo" in out

    # (the rule over-redacts what follows a `token=` value, the safe way, so
    # the refusal is held to its opening words and its host)
    for raised, said in (
            (session_pr.SubmissionRefused(f"push to {leaky} was rejected"),
             "push to https://<redacted>@forge.example/team/repo"),
            (RuntimeError(f"broke at {leaky}"), "raised RuntimeError")):
        domain_profile.unregister()
        domain_profile.register(SubmittingHostWithTheVerb(raises=raised))
        at_terminal(monkeypatch, f"{BRANCH}\n")
        status, out, err = land_verb(capsys, world.root)
        assert status == 1, (out, err)
        assert SECRET not in out + err, err
        assert said in err and "Traceback" not in err


def test_the_cli_binding_is_the_neutral_lander_only_under_standalone(
        world, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENDOX_INSTALL_MODE", raising=False)
    assert isinstance(cli._landing_port(world.root, local=True), NeutralLander)
    assert cli._landing_port(world.root) is None       # the hosted install
    monkeypatch.setenv("OPENDOX_INSTALL_MODE", "local")
    assert isinstance(cli._landing_port(world.root), NeutralLander)
    bare = World(tmp_path / "bare", declaration=None)
    assert cli._landing_port(bare.root, local=True) is None


def test_the_default_profile_contributes_land_beside_submit():
    """N-2: the verb, the two routes and their mixin are the default profile's
    contributions, and the mixin holds the routes' methods."""
    from opendox import default_profile

    _parser, land = _land_parser()
    assert land.get_default("func") is cli_branch_actions.cmd_land
    bindings = route_extension.collect_bindings(default_profile.ROUTE_EXTENSIONS)
    assert [(b.method, b.pattern, b.is_prefix, b.handler) for b in bindings] == [
        ("POST", "/actions/session/submit", False, "_handle_session_submit"),
        ("POST", NONCE_ROUTE, False, "_handle_session_land_nonce"),
        ("POST", LAND_ROUTE, False, "_handle_session_land"),
    ]
    assert (serve_branch_actions.ACTIONS_SESSION_LAND_NONCE_ROUTE,
            serve_branch_actions.ACTIONS_SESSION_LAND_ROUTE) == (NONCE_ROUTE,
                                                                 LAND_ROUTE)
    mixin = serve_branch_actions.BranchActionRoutes
    for binding in bindings:
        assert callable(getattr(mixin, binding.handler))


def test_a_host_profile_replacing_the_default_has_no_land_verb():
    domain_profile.register(InstrumentedHost())
    parser = cli.build_parser()
    with pytest.raises(SystemExit), contextlib.redirect_stderr(io_sink()):
        parser.parse_args(["land", "--repo-root", "r", "--branch", "b"])


# ---- the server's binding and the routes ------------------------------------

def test_the_server_binding_is_the_neutral_lander_only_under_standalone(
        world, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENDOX_INSTALL_MODE", "local")
    assert isinstance(serve.served_lander(world.root), NeutralLander)
    with serving(world.root, tmp_path) as httpd:
        handler = object.__new__(bound_class(httpd))
        assert isinstance(handler._session_lander(), NeutralLander)
    injected = object()
    with serving(world.root, tmp_path / "i",
                 landing_factory=lambda: injected) as httpd:
        assert object.__new__(bound_class(httpd))._session_lander() is injected
    # a hosted plane binds nothing, whatever the factory would build
    with serving(world.root, tmp_path / "h", host="0.0.0.0",
                 landing_factory=lambda: injected) as httpd:
        assert object.__new__(bound_class(httpd))._session_lander() is None
    monkeypatch.delenv("OPENDOX_INSTALL_MODE")
    assert serve.served_lander(world.root) is None


def test_the_routes_land_a_branch_once_with_the_views_nonce(world, tmp_path,
                                                            local_install):
    """OQ-12-13: `land-nonce` answers a nonce bound to the branch and its head;
    `land` with it answers `Landed`; the same nonce a second time is refused."""
    previous = world.head("refs/heads/main")
    head = world.head(BRANCH)
    with serving(world.root, tmp_path) as httpd:
        issued = nonce_for(httpd)
        assert set(issued) == {"nonce", "branch", "head"}
        assert (issued["branch"], issued["head"]) == (BRANCH, head)
        status, landed = ask(httpd, "POST", LAND_ROUTE,
                             {"branch": BRANCH, "nonce": issued["nonce"]},
                             token=httpd.console_token)
        assert status == 200, landed
        again = ask(httpd, "POST", LAND_ROUTE,
                    {"branch": BRANCH, "nonce": issued["nonce"]},
                    token=httpd.console_token)
    merge = world.head("refs/heads/main")
    assert landed == {"branch": BRANCH, "merge_commit": merge,
                      "previous_main": previous,
                      "served_checkout": landing.SERVED_FAST_FORWARDED,
                      "pushed": False}
    assert parents_of(world, merge) == [merge, previous, head]
    assert again[0] == 409 and again[1]["error"] == "landing_refused", again
    assert again[1]["code"] == "confirmation:no-nonce"
    assert world.head("refs/heads/main") == merge


@pytest.mark.parametrize("nonce", ["wrong", "", None, 7])
def test_the_land_route_refuses_any_other_nonce_and_spends_the_live_one(
        world, tmp_path, local_install, nonce):
    before = world.refs()
    with serving(world.root, tmp_path) as httpd:
        issued = nonce_for(httpd)
        status, body = ask(httpd, "POST", LAND_ROUTE,
                           {"branch": BRANCH, "nonce": nonce},
                           token=httpd.console_token)
        if nonce in ("", None, 7):
            assert (status, body["error"]) == (400, "invalid_body"), body
            assert world.refs() == before
            return
        assert (status, body["error"]) == (409, "landing_refused"), body
        assert body["code"] == "confirmation:nonce-mismatch"
        status, body = ask(httpd, "POST", LAND_ROUTE,
                           {"branch": BRANCH, "nonce": issued["nonce"]},
                           token=httpd.console_token)
    assert body["code"] == "confirmation:no-nonce", body
    assert world.refs() == before


def test_a_nonce_for_a_head_the_branch_has_left_is_refused(world, tmp_path,
                                                           local_install):
    with serving(world.root, tmp_path) as httpd:
        issued = nonce_for(httpd)
        world.branch_with(BRANCH, "notes/later.md", "a later commit\n")
        main = world.head("refs/heads/main")
        status, body = ask(httpd, "POST", LAND_ROUTE,
                           {"branch": BRANCH, "nonce": issued["nonce"]},
                           token=httpd.console_token)
    assert (status, body["code"]) == (409, "confirmation:another-head"), body
    assert world.head("refs/heads/main") == main


@pytest.mark.parametrize("route", ["nonce", "land"])
@pytest.mark.parametrize("clause", ["off-loopback", "no-actor", "no-token",
                                    "foreign-origin"])
def test_each_land_route_is_gated_like_submit(world, tmp_path, local_install,
                                              route, clause):
    """12.4a's three clauses on both routes, in order; nothing lands."""
    before = world.refs()
    kwargs = {"off-loopback": {"host": "0.0.0.0"}, "no-actor": {"actor": None}
              }.get(clause, {})
    expected = {"off-loopback": "loopback_only", "no-actor": "action_unavailable"
                }.get(clause, "agent_invocation")
    path = NONCE_ROUTE if route == "nonce" else LAND_ROUTE
    payload = {"branch": BRANCH} if route == "nonce" else {
        "branch": BRANCH, "nonce": "n" * 43}
    with serving(world.root, tmp_path, **kwargs) as httpd:
        token = None if clause == "no-token" else (httpd.console_token or "t")
        headers = ({"Origin": "https://evil.example"}
                   if clause == "foreign-origin" else None)
        status, body = ask(httpd, "POST", path, payload, token=token,
                           headers=headers)
    assert (status, body["error"]) == (403, expected), body
    assert world.refs() == before


@pytest.mark.parametrize("payload", [
    {"branch": BRANCH, "repo_root": "/elsewhere"},
    {"branch": BRANCH, "nonce": "n", "checkout_root": "/elsewhere"},
    {"nonce": "n"}, {}, ["sess-1"], "sess-1",
])
def test_the_land_routes_take_no_repository_from_the_request(
        world, tmp_path, local_install, payload):
    before = world.refs()
    with serving(world.root, tmp_path) as httpd:
        for path in (NONCE_ROUTE, LAND_ROUTE):
            status, body = ask(httpd, "POST", path, payload,
                               token=httpd.console_token)
            assert (status, body["error"]) == (400, "invalid_body"), (path, body)
            assert "/elsewhere" not in json.dumps(body)
    assert world.refs() == before


@pytest.mark.parametrize("branch, code", [
    ("main", "branch-is-main"), ("sess-9", "no-such-branch"),
    ("-x", "no-such-branch"),
])
def test_the_nonce_route_refuses_what_cannot_land(world, tmp_path, local_install,
                                                  branch, code):
    with serving(world.root, tmp_path) as httpd:
        status, body = ask(httpd, "POST", NONCE_ROUTE, {"branch": branch},
                           token=httpd.console_token)
    assert (status, body["error"], body["code"]) == (409, "landing_refused",
                                                     code), body


def test_the_nonce_route_refuses_where_nothing_can_land(tmp_path, local_install):
    world = World(tmp_path, declaration=None)
    world.branch_with(BRANCH, "notes/session.md", "work\n")
    with serving(world.root, tmp_path / "s") as httpd:
        status, body = ask(httpd, "POST", NONCE_ROUTE, {"branch": BRANCH},
                           token=httpd.console_token)
    assert (status, body["code"]) == (409, "no-declaration"), body
    assert DECLARATION_PATH in body["message"]


def test_the_land_route_shows_a_conflict_and_lands_nothing(tmp_path,
                                                           local_install):
    world = World(tmp_path)
    world.branch_with(BRANCH, "doc.md", "the branch's words\n")
    world.on_main("doc.md", "main's words\n")
    before = world.refs()
    with serving(world.root, tmp_path / "s") as httpd:
        issued = nonce_for(httpd)
        status, body = ask(httpd, "POST", LAND_ROUTE,
                           {"branch": BRANCH, "nonce": issued["nonce"]},
                           token=httpd.console_token)
    assert (status, body["error"], body["code"]) == (409, "merge_conflict",
                                                     "merge-conflict"), body
    assert body["paths"] == ["doc.md"]
    assert "bring `main` into sess-1" in body["remedy"]
    assert world.refs() == before


def test_the_land_route_under_a_governed_host_submits_through_the_instrument(
        world, tmp_path, local_install):
    """R2Q4 (a) through the route: the host's instrument receives the branch,
    the answer is its `Submission`, and nothing merges."""
    host = domain_profile.register(SubmittingHost())
    before = world.refs()
    with serving(world.root, tmp_path,
                 route_extensions=(BranchActionsOnTop(),)) as httpd:
        assert capabilities(httpd)["actions"]["land"] is True
        issued = nonce_for(httpd)
        status, body = ask(httpd, "POST", LAND_ROUTE,
                           {"branch": BRANCH, "nonce": issued["nonce"]},
                           token=httpd.console_token)
    assert status == 200, body
    assert body == {"remote": "review", "ref": f"refs/heads/{BRANCH}",
                    "url": "https://forge.example/team/repo", "branch": BRANCH,
                    "commit": world.head(BRANCH)}
    assert host.submitted() == [BRANCH]
    assert world.refs() == before


def test_an_instruments_words_are_redacted_by_the_route(world, tmp_path,
                                                        local_install, capsys):
    leaky = f"https://alice:{SECRET}@forge.example/team/repo?token={SECRET}"
    for host, status, error in (
            (SubmittingHost(url=leaky), 200, None),
            (SubmittingHost(raises=session_pr.SubmissionRefused(
                f"push to {leaky} was rejected")), 409, "submission_refused"),
            (SubmittingHost(raises=RuntimeError(f"broke at {leaky}")), 500,
             "landing_failed")):
        domain_profile.unregister()
        domain_profile.register(host)
        with serving(world.root, tmp_path / str(status),
                     route_extensions=(BranchActionsOnTop(),)) as httpd:
            issued = nonce_for(httpd)
            answer = ask(httpd, "POST", LAND_ROUTE,
                         {"branch": BRANCH, "nonce": issued["nonce"]},
                         token=httpd.console_token)
        assert answer[0] == status, answer
        assert error is None or answer[1]["error"] == error, answer
        assert SECRET not in json.dumps(answer[1])
    logged = capsys.readouterr().err
    assert SECRET not in logged and "raised RuntimeError" in logged


# ---- `actions.land`: present only under openDox's own profile, its value
# ---- where `land` can act (ADV-14; OQ-12-14; contracts § /capabilities) ------

def test_a_host_profile_sees_no_land_key(world, tmp_path, local_install):
    """The falsifier's node (R2Q3 (a)): a host profile that replaces the
    default carries no `actions.land` key and no land route."""
    domain_profile.register(SubmittingHost())
    with serving(world.root, tmp_path) as httpd:
        caps = capabilities(httpd)
        assert caps["actions"]["session"] is True, "not a local human's plane"
        for path in (NONCE_ROUTE, LAND_ROUTE):
            status, body = ask(httpd, "POST", path, {"branch": BRANCH},
                               token=httpd.console_token)
            assert (status, body["error"]) == (404, "unknown_action"), body
        assert not hasattr(bound_class(httpd), "_handle_session_land")
    assert "land" not in caps["actions"]
    assert set(caps["actions"]) == set(serve._DEFAULT_CAPABILITIES["actions"])


def test_the_land_key_is_true_where_land_can_act_and_false_otherwise(
        tmp_path, monkeypatch):
    """The falsifier's capability test: TRUE for `standalone` with a lander and
    for `governed` with an instrument; FALSE under `unknown`, under `governed`
    with no instrument, on the hosted plane, and with no local human."""
    def land_key(world, *, local=True, profile=None, **serve_kwargs):
        if local:
            monkeypatch.setenv("OPENDOX_INSTALL_MODE", "local")
        else:
            monkeypatch.delenv("OPENDOX_INSTALL_MODE", raising=False)
        domain_profile.unregister()
        if profile is not None:
            domain_profile.register(profile)
            serve_kwargs["route_extensions"] = (BranchActionsOnTop(),)
        with serving(world.root, world.tmp / f"s{len(seen)}",
                     **serve_kwargs) as httpd:
            seen.append(1)
            return capabilities(httpd)["actions"]["land"]

    seen: list[int] = []
    standalone = World(tmp_path / "standalone")
    standalone.branch_with(BRANCH, "notes/a.md", "a\n")
    assert land_key(standalone) is True
    assert land_key(standalone, profile=SubmittingHost()) is True    # governed + instrument
    assert land_key(standalone, profile=HostWithoutAnInstrument()) is False
    assert land_key(standalone, profile=HostThatFailsToLoad()) is False
    assert land_key(standalone, local=False) is False                 # not the local install
    assert land_key(standalone, actor=None) is False                  # no local human
    assert land_key(standalone, host="0.0.0.0") is False              # the hosted plane
    unknown = World(tmp_path / "unknown", declaration=None)
    assert land_key(unknown) is False
    declared = World(tmp_path / "declared",
                     declaration=DECLARATION_CONTENT.replace(STANDALONE, GOVERNED))
    assert land_key(declared) is False                                # governed, no instrument
    # an injected factory that binds nothing binds nothing
    assert land_key(standalone, landing_factory=lambda: None) is False


def test_the_land_key_follows_main_while_the_server_runs(tmp_path,
                                                         local_install):
    """The value is read where `land` can act NOW: committing the declaration
    to `main` makes the key true at the next `/capabilities`, no restart."""
    world = World(tmp_path, declaration=None)
    world.branch_with(BRANCH, "notes/a.md", "a\n")
    with serving(world.root, tmp_path / "s") as httpd:
        assert capabilities(httpd)["actions"]["land"] is False
        world.on_main(DECLARATION_PATH, DECLARATION_CONTENT)
        assert capabilities(httpd)["actions"]["land"] is True
        # the handler's own verdict object is never rewritten by a request
        assert bound_class(httpd).capabilities["actions"]["land"] is False


_LAND = route_extension.RouteBinding("POST", LAND_ROUTE, False, "h")
_NONCE = route_extension.RouteBinding("POST", NONCE_ROUTE, False, "h")


@pytest.mark.parametrize("binding, land, nonce", [
    (_LAND, True, False), (_NONCE, False, True),
    (route_extension.RouteBinding("POST", "/actions/session/", True, "h"),
     True, True),
    (route_extension.RouteBinding("GET", LAND_ROUTE, False, "h"), False, False),
    (route_extension.RouteBinding("POST", LAND_ROUTE + "x", False, "h"),
     False, False),
    (route_extension.RouteBinding("POST", "/actions/session/submit", False, "h"),
     False, False),
])
def test_what_answers_the_land_routes(binding, land, nonce):
    assert serve.answers_the_land(binding) is land
    assert serve.answers_the_land_nonce(binding) is nonce


def test_compute_capabilities_derives_the_land_key_from_the_bindings():
    base = dict(nlm_present=False, checkout_real=True, loopback=True, actor="a")
    assert "land" not in serve.compute_capabilities(**base)["actions"]
    for only in ((_LAND,), (_NONCE,)):
        assert "land" not in serve.compute_capabilities(
            route_bindings=only, landing_acts=True, **base)["actions"]
    both = (_LAND, _NONCE)
    assert serve.compute_capabilities(route_bindings=both, landing_acts=True,
                                      **base)["actions"]["land"] is True
    assert serve.compute_capabilities(route_bindings=both,
                                      **base)["actions"]["land"] is False
    for actor, loopback, real in ((None, True, True), ("a", False, True),
                                  ("a", True, False)):
        off = serve.compute_capabilities(
            nlm_present=False, checkout_real=real, loopback=loopback,
            actor=actor, route_bindings=both, landing_acts=True)
        assert off["actions"]["land"] is False, (actor, loopback, real)
    assert "land" not in serve._DEFAULT_CAPABILITIES["actions"]


def test_generate_and_open_local_binds_the_lander_without_the_setting(
        world, monkeypatch):
    """`generate-and-open --local` with no `OPENDOX_INSTALL_MODE`: the entry
    point declares the server's `landing_factory` with the install it
    resolved, so the served plane can land (quickstart § 3)."""
    import argparse

    monkeypatch.delenv("OPENDOX_INSTALL_MODE", raising=False)
    local = argparse.Namespace(install_mode="local")
    hosted = argparse.Namespace(install_mode="hosted")
    assert isinstance(cli._served_landing_factory(world.root, local)(),
                      NeutralLander)
    assert cli._served_landing_factory(world.root, hosted)() is None


# ---- R2Q5 (a): a live session whose branch lands ends by the merge observation

def test_a_live_session_whose_branch_lands_ends_by_the_merge_observation(world):
    from opendox import branch_session

    worktree = branch_session.sessions_root(world.root) / "sess-1"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    world.git("worktree", "add", "-q", str(worktree), BRANCH)
    git = session_git.SessionGit(world.root)
    assert branch_session.merge_state(git, BRANCH).merged is False

    landed = lander(world).land(BRANCH, confirmation=mint(world))

    observed = branch_session.merge_state(git, BRANCH)
    assert observed.merged is True, observed.reason
    assert observed.landed_by == landed.merge_commit
    session = branch_session.SessionOpen(
        repository="plain", tile=None, branch=BRANCH, worktree=worktree,
        joined=True, entry=None, notebook_alias="")
    ended = branch_session.reconcile_merged_session(git, session,
                                                    checkout_root=world.root)
    assert ended.merged is True
    assert world.git("branch", "--list", BRANCH) == ""
    assert not worktree.exists()
