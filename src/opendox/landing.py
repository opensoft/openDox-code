"""THE LANDING SEAM: `LandingPort`, the governance query, and the neutral lander
(#1144 12.6, 12.6a; plan 038 T012; spec FR-006, FR-007).

WHAT IT IS FOR. 12.6 is RULED (`#656` `5784155201`, *"merge yes"*): landing
authority follows whoever governs the repository. A governed host reserves
landing and routes it to its own instrument; a standalone owner IS the
governance, and openDox may land. So openDox ASKS the repository who governs it
rather than hard-coding either answer, and three guardrails hold in every mode,
none of them configurable: a landing is an explicit human act, a conflict is
shown and never resolved, and a landing is a merge COMMIT that `git revert -m 1`
undoes.

THE SUBMISSION PORT KEEPS ITS OPERATIONS. Landing is a SEPARATE protocol,
`LandingPort`, with ONE operation, `land(branch, *, confirmation) -> Landed`.
`session_pr` declares it, by re-exporting it and `repository_governance` from
here (FR-007; plan 038 ADV-23), and `PullRequestPort` still has no merge.

THE GOVERNANCE QUERY, `repository_governance(checkout_root)`, answers
`standalone`, `governed` or `unknown`, and FAILS CLOSED. In the order it asks:

1. The checkout must be the top of a git working tree, and it must have a
   branch named `main`, the landing default branch (R2Q7 (a)). With no `main`
   the repository is `unknown`, refused naming the absent branch.
2. The install mode must resolve: `OPENDOX_INSTALL_MODE` and `--local` may not
   disagree (`runtime.config.install_mode`), or it is `unknown`.
3. A REGISTERED HOST PROFILE decides, whatever any file says (R2Q4 (a)). With
   an instrument, the facet `SUBMISSION_INSTRUMENT` (a factory that builds the
   host's contributed `SubmissionPort` for a checkout), the repository is
   `governed` and a landing is submitted through it. Without one it is
   `governed` all the same, and a landing is refused as
   governed-without-an-instrument. A host profile whose facet cannot be read
   (it fails to load) makes it `unknown`. openDox's own default profile is not
   a host.
4. Otherwise the declaration decides: `.opendox/governance.yaml`, read from the
   blob at `main`'s tip and never from the working tree or the branch being
   landed (decision N-1). `governed` is `governed` (with no instrument, so a
   landing is refused). `standalone` is `standalone` only on the explicit local
   install (`OPENDOX_INSTALL_MODE=local`, or `--local`, which selects local
   exactly as the setting does; FR-007, ADV-38); on any other install the
   declaration disagrees with it and the repository is `unknown`. No file at
   all, an unreadable one, another `kind`, an unknown key or value: `unknown`,
   and the refusal names the exact file and content to commit (R2Q7 (a)).

A REGISTERED HOST WITHOUT AN INSTRUMENT IS STILL A HOST (step 3). 12.6a's
precedence runs one way, the host and then `main`'s declaration, and plan 038's
T019 asserts that with the real host registered no lander is bound and the host
outranks a declaration, though no production host declares an instrument in
release 2 (R2Q2 (a) with R2Q3 (a)). So a host's presence, not only its
instrument, outranks a declaration. That is the fail-closed reading of the two;
the other one would bind a lander under a host on the strength of a file.

THE NEUTRAL LANDER (`NeutralLander`), bound only under `standalone`
(`bound_lander`; T016 binds it through `landing_factory` and `_landing_port`).
Its `land` (R2Q6 (a)):

* refuses `main` itself (R2Q5 (a)), re-reads the governance at the moment of
  landing, and SPENDS the confirmation, which must be bound to the branch and
  its current head (`landing_confirm.redeem`);
* reads the remote's `main` with `ls-remote refs/heads/main`, never a fetch,
  and refuses if local `main` does not contain it; a remote with no `main`, or
  no remote, passes (N-16);
* refuses, before merging, when the served checkout holds `main` and is not
  clean, naming the remedy (ADV-08), and when another working tree holds `main`;
* makes the `--no-ff` merge commit in a landing worktree of its own under
  `<repo>-worktrees/landing/`, detached at `main`'s tip, with rerere off so no
  recorded resolution answers a conflict for the human; a conflict raises
  `MergeConflict` with the paths and the remedy, and nothing moves (OQ-038-1);
* then moves `main`: where the served checkout holds it (and is still clean),
  by `git merge --ff-only <merge commit>` there, the one move feature 007's
  guard admits at the served root (T013); where it holds another branch, by a
  compare-and-swap of the `main` ref alone, leaving the served checkout as it
  was (`left`);
* pushes NOTHING (R2Q6 (a)). A landed `main` leaves the machine only by the
  user's own `git push`.

Every git command goes through `session_git.SessionGit`, the one git-write
surface, so feature 007's guard sees every one of them.
"""

from __future__ import annotations

import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

import yaml

from .landing_confirm import Confirmation, ConfirmationRefused, redeem
from .session_git import GitError, GitRunner, SessionGit, SessionGitRefused

__all__ = [
    "DECLARATION_CONTENT",
    "DECLARATION_KIND",
    "DECLARATION_PATH",
    "DEFAULT_BRANCH",
    "GOVERNANCE_VALUES",
    "GOVERNED",
    "GovernanceReading",
    "INSTRUMENT_FACET",
    "LANDING_OPERATIONS",
    "LANDING_SUBDIR",
    "Landed",
    "LandingPort",
    "LandingRefused",
    "MergeConflict",
    "NeutralLander",
    "SERVED_FAST_FORWARDED",
    "SERVED_LEFT",
    "STANDALONE",
    "UNKNOWN",
    "bound_lander",
    "read_governance",
    "repository_governance",
    "request_landing",
]

STANDALONE = "standalone"
GOVERNED = "governed"
UNKNOWN = "unknown"
GOVERNANCE_VALUES: tuple[str, ...] = (STANDALONE, GOVERNED, UNKNOWN)

#: The landing default branch (R2Q7 (a)): openDox's existing session base.
DEFAULT_BRANCH = "main"

#: The port's WHOLE operation set, declared as data so a test can assert on it
#: and a second operation cannot arrive quietly (12.6a: ONE operation).
LANDING_OPERATIONS: tuple[str, ...] = ("land",)

#: The declaration (decision N-1), its kind, and the exact content a refusal
#: names for the owner to commit with git (R2Q7 (a)).
DECLARATION_PATH = ".opendox/governance.yaml"
DECLARATION_KIND = "opendox-governance"
DECLARATION_CONTENT = (
    "schema_version: 1\n"
    f"kind: {DECLARATION_KIND}\n"
    f"governance: {STANDALONE}\n"
)
_DECLARATION_KEYS = frozenset({"schema_version", "kind", "governance"})
_DECLARED_VALUES = (STANDALONE, GOVERNED)
#: The largest declaration read; the file is three short lines.
_DECLARATION_LIMIT = 4096

#: The host-profile facet that declares an instrument (R2Q4 (a)): a factory
#: `(checkout_root: Path) -> SubmissionPort`, the host's contributed port.
INSTRUMENT_FACET = "SUBMISSION_INSTRUMENT"

#: `Landed.served_checkout`'s two values (data-model.md § Landed).
SERVED_FAST_FORWARDED = "fast-forwarded"
SERVED_LEFT = "left"

#: Where landing worktrees live, below `<repo>-worktrees/`, beside (never in)
#: the `sessions/` directory the session bootstrap scans.
LANDING_SUBDIR = "landing"

_OBJECT_ID = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_GITLINK_OR_LINK = ("120000", "160000")
_REGULAR_FILE_MODES = ("100644", "100755")
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/@\s]*@")
_URL_QUERY_VALUE = re.compile(r"([?&][^=\s&#]+=)[^&\s#'\"]+")


def _read(git: SessionGit, cwd: Path, *args: str) -> str | None:
    """A git READ whose failure is an answer: its output, or None. Through the
    public funnel, so feature 007's guard sees it like every other command."""
    try:
        return git.git(cwd, *args)
    except GitError:
        return None


def _commit_at(git: SessionGit, ref: str) -> str | None:
    """The commit `ref` names, as a full object id, or None."""
    sha = _read(git, git.served_root, "rev-parse", "--verify", "--quiet",
                f"{ref}^{{commit}}")
    return sha if sha and _OBJECT_ID.match(sha) else None


def _redact(text: str) -> str:
    """A git message with any credential a remote URL carries removed: the
    userinfo of a URL and every query-string value (12.1a's rule)."""
    return _URL_QUERY_VALUE.sub(r"\1***", _URL_USERINFO.sub(r"\1***@", text or ""))


class LandingRefused(Exception):
    """A landing that did not happen, with the case named.

    `code` names the case for a caller that answers in a protocol (T016's
    routes): `branch-is-main`, `no-such-branch`, `already-landed`,
    `not-a-repository`, `no-main`, `no-declaration`, `invalid-declaration`,
    `install-mode-refused`, `install-mode-disagrees`, `host-failed-to-load`,
    `governed-without-an-instrument`, `instrument-failed`,
    `confirmation:<case>`, `remote-unreadable`, `remote-main-not-contained`,
    `dirty-served-checkout`, `main-checked-out-elsewhere`, `merge-failed`,
    `landing-worktree`, `not-a-merge-commit`,
    `fast-forward-no-longer-applies`, `main-moved`,
    `merge-conflict`, `governed` (a governed repository with an instrument
    binds no lander). Nothing was merged and `main` is where it was."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class MergeConflict(LandingRefused):
    """The branch conflicts with `main`. The conflict is SHOWN, never resolved:
    `paths` lists the conflicting files, `remedy` says what to do, and nothing
    was merged (requirement 11's eighth scenario; OQ-038-1)."""

    def __init__(self, branch: str, paths: tuple[str, ...]) -> None:
        self.branch = branch
        self.paths = tuple(paths)
        self.remedy = (
            f"bring `main` into {branch} and resolve the conflict there, on the "
            "branch, with git (for example `git merge main` in a checkout of "
            f"{branch}), then land again")
        listed = ", ".join(self.paths) if self.paths else "(git named no path)"
        super().__init__(
            f"{branch} conflicts with `main` in: {listed}. Nothing was merged and "
            f"`main` is where it was. Remedy: {self.remedy}",
            code="merge-conflict")


@dataclass(frozen=True)
class Landed:
    """A landing that happened (data-model.md § Landed).

    `merge_commit` is the `--no-ff` merge commit on `main`, so `git revert -m 1
    <merge_commit>` restores `previous_main`'s tree. `served_checkout` is
    `fast-forwarded` (it held `main` and was clean, and now holds the merge) or
    `left` (it holds another branch, and only the `main` ref moved). `pushed` is
    always False: `land` pushes nothing (R2Q6 (a))."""

    branch: str
    merge_commit: str
    previous_main: str
    served_checkout: str
    pushed: bool = field(default=False, init=False)

    @property
    def revert_command(self) -> str:
        return f"git revert -m 1 {self.merge_commit}"


@runtime_checkable
class LandingPort(Protocol):
    """Land a branch on `main` with ONE confirmed act. One operation, and the
    absence of every other one is 12.6a's."""

    def land(self, branch: str, *, confirmation: Confirmation) -> Landed: ...


@dataclass(frozen=True)
class GovernanceReading:
    """`repository_governance`'s answer, with what decided it.

    `code` is the machine name of the reason (see `LandingRefused.code`; a
    deciding reading carries `host-instrument`, `host-without-an-instrument`,
    `declared-governed` or `declared-standalone`). `reason` is the sentence a
    refusal shows. `instrument` is the host's factory where one decides."""

    governance: str
    code: str
    reason: str
    host: str | None = None
    instrument: Callable[[Path], Any] | None = None
    main: str | None = None


# --------------------------------------------------------------------------
# the governance query
# --------------------------------------------------------------------------

def _unknown(code: str, reason: str, **extra: Any) -> GovernanceReading:
    return GovernanceReading(UNKNOWN, code, reason, **extra)


def _no_declaration_reason(main: str) -> str:
    return (
        f"`main` ({main[:12]}) carries no {DECLARATION_PATH}, so openDox cannot "
        "tell who governs this repository and will not guess (#1144 12.6a; "
        "R2Q7 (a)). If you own it and land on it yourself, commit this file to "
        f"`main` with git, exactly as written:\n\n{DECLARATION_PATH}\n"
        f"{DECLARATION_CONTENT}\n"
        "and run openDox as the local install (OPENDOX_INSTALL_MODE=local, or "
        "--local). A repository someone else governs declares "
        f"`governance: {GOVERNED}` instead, and lands through its governance")


class _DuplicateKeyLoader(yaml.SafeLoader):
    """`yaml.SafeLoader` that refuses a duplicate key or a merge key rather than
    keeping one of two answers silently."""


def _strict_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode,
                    deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _value_node in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            raise yaml.constructor.ConstructorError(
                None, None, "a merge key (`<<`) is not allowed here",
                key_node.start_mark)
        key = loader.construct_object(key_node, deep=deep)
        try:
            repeated = key in seen
        except TypeError:
            raise yaml.constructor.ConstructorError(
                None, None, "a key is not a plain value", key_node.start_mark) from None
        if repeated:
            raise yaml.constructor.ConstructorError(
                None, None, f"the key {key!r} appears twice", key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _strict_mapping)


def _parse_declaration(text: str) -> tuple[str | None, str]:
    """The declared value, or None and why the file is not a declaration."""
    loader = _DuplicateKeyLoader(text)
    try:
        data = loader.get_single_data()
    except yaml.YAMLError as broken:
        first = (str(broken).splitlines() or ["unparseable"])[0]
        return None, f"it is not valid YAML ({first})"
    finally:
        loader.dispose()
    if not isinstance(data, dict):
        return None, "it is not a mapping"
    keys = set(data)
    if keys != _DECLARATION_KEYS:
        extra = sorted(str(k) for k in keys - _DECLARATION_KEYS)
        missing = sorted(_DECLARATION_KEYS - keys)
        parts = ([f"unknown key(s) {', '.join(extra)}"] if extra else []) + (
            [f"missing key(s) {', '.join(missing)}"] if missing else [])
        return None, "it has " + " and ".join(parts)
    version = data["schema_version"]
    if type(version) is not int or version != 1:
        return None, f"its schema_version is {version!r}, not 1"
    if data["kind"] != DECLARATION_KIND:
        return None, f"its kind is {data['kind']!r}, not {DECLARATION_KIND!r}"
    value = data["governance"]
    if value not in _DECLARED_VALUES:
        return None, (f"its governance is {value!r}, which is neither "
                      f"{STANDALONE!r} nor {GOVERNED!r}")
    return value, ""


def _read_declaration(git: SessionGit, main: str) -> tuple[str | None, str, str]:
    """`(value, code, why)` for the declaration in the blob at `main`'s tip."""
    root = git.served_root
    try:
        listed = git.git_raw(root, "ls-tree", "-z", main, "--", DECLARATION_PATH)
    except (GitError, UnicodeDecodeError) as failed:
        return None, "invalid-declaration", f"git could not list it ({failed})"
    entry = listed.split("\0", 1)[0]
    if not entry:
        return None, "no-declaration", ""
    meta, _tab, _path = entry.partition("\t")
    fields = meta.split()
    if len(fields) != 3:
        return None, "invalid-declaration", "git listed it in a shape it never uses"
    mode, kind, oid = fields
    if kind != "blob" or mode not in _REGULAR_FILE_MODES:
        what = ("a symbolic link or a submodule" if mode in _GITLINK_OR_LINK
                else f"a {kind} with mode {mode}")
        return None, "invalid-declaration", f"it is {what}, not a regular file"
    try:
        size = int(git.git(root, "cat-file", "-s", oid))
        if size > _DECLARATION_LIMIT:
            return None, "invalid-declaration", (
                f"it is {size} bytes, more than the {_DECLARATION_LIMIT} a "
                "declaration of three lines can need")
        text = git.git_raw(root, "cat-file", "blob", oid)
    except (GitError, UnicodeDecodeError, ValueError) as failed:
        return None, "invalid-declaration", f"it cannot be read as text ({failed})"
    value, why = _parse_declaration(text)
    if value is None:
        return None, "invalid-declaration", why
    return value, "", ""


@dataclass(frozen=True)
class _HostReading:
    name: str
    instrument: Callable[[Path], Any] | None = None
    failure: str | None = None


def _registered_host() -> _HostReading | None:
    """The registered HOST profile, or None when there is none.

    openDox's own default profile is not a host: it is the profile an entry
    point registers where no host did. A registration that cannot be read, or a
    facet that raises when read, is a host that FAILED TO LOAD."""
    from . import domain_profile

    if not domain_profile.is_registered():
        return None
    try:
        profile = domain_profile.current()
    except Exception as failed:                     # noqa: BLE001 - fail closed
        return _HostReading("the registered profile",
                            failure=f"{type(failed).__name__}: {failed}")
    from . import default_profile

    if profile is default_profile:
        return None
    name = domain_profile.name_of(profile)
    try:
        facet = getattr(profile, INSTRUMENT_FACET)
    except AttributeError:
        facet = None
    except Exception as failed:                     # noqa: BLE001 - fail closed
        return _HostReading(name, failure=f"{type(failed).__name__}: {failed}")
    if facet is None:
        return _HostReading(name)
    if not callable(facet):
        return _HostReading(name, failure=(
            f"its {INSTRUMENT_FACET} is a {type(facet).__name__}, not a factory "
            "that builds the host's SubmissionPort"))
    return _HostReading(name, instrument=facet)


def read_governance(checkout_root: Path | str, *, local: bool = False,
                    env: Mapping[str, str] | None = None,
                    runner: GitRunner | None = None) -> GovernanceReading:
    """Who governs `checkout_root`, and why: see the module docstring.

    `local` is `--local`, which selects the local install exactly as
    `OPENDOX_INSTALL_MODE=local` does; `env` is the environment the install
    mode is read from (the process's own when None)."""
    root = Path(checkout_root)
    if not root.is_dir():
        return _unknown("not-a-repository",
                        f"{root} is not a directory, so it is no repository")
    git = SessionGit(root, runner=runner)
    top = _read(git, git.served_root, "rev-parse", "--show-toplevel")
    try:
        is_top = bool(top) and Path(top).resolve() == git.served_root
    except OSError:
        is_top = False
    if not is_top:
        return _unknown("not-a-repository", (
            f"{root} is not the top of a git working tree, so openDox cannot "
            "read who governs it"))
    main = _commit_at(git, f"refs/heads/{DEFAULT_BRANCH}")
    if main is None:
        return _unknown("no-main", (
            f"this repository has no branch named `{DEFAULT_BRANCH}`, the branch "
            "openDox lands on (R2Q7 (a)), so its governance is unknown and "
            f"nothing lands. Create `{DEFAULT_BRANCH}` with git (for example "
            f"`git branch -m <your default branch> {DEFAULT_BRANCH}`) to land "
            "here"))

    from .runtime import config as runtime_config

    try:
        mode = runtime_config.install_mode(env, local_flag=local)
    except runtime_config.ConfigurationError as refused:
        return _unknown("install-mode-refused", str(refused), main=main)

    host = _registered_host()
    if host is not None:
        if host.failure is not None:
            return _unknown("host-failed-to-load", (
                f"the registered host profile {host.name} failed to load "
                f"({host.failure}), so who governs this repository is unknown "
                "and no lander is bound (#1144 12.6a)"), host=host.name, main=main)
        if host.instrument is not None:
            return GovernanceReading(GOVERNED, "host-instrument", (
                f"the registered host profile {host.name} governs this "
                f"repository and declares an instrument ({INSTRUMENT_FACET}), "
                "which outranks any declaration (R2Q4 (a))"),
                host=host.name, instrument=host.instrument, main=main)
        return GovernanceReading(GOVERNED, "host-without-an-instrument", (
            f"the registered host profile {host.name} governs this repository, "
            f"and it declares no instrument ({INSTRUMENT_FACET}): the repository "
            "is governed-without-an-instrument, so no lander is bound and "
            "nothing lands here; a governed repository lands through its "
            "governance (#1144 12.6a)"), host=host.name, main=main)

    value, code, why = _read_declaration(git, main)
    if value is None and code == "no-declaration":
        return _unknown(code, _no_declaration_reason(main), main=main)
    if value is None:
        return _unknown(code, (
            f"{DECLARATION_PATH} at `main` ({main[:12]}) is not a governance "
            f"declaration: {why}. It must read exactly:\n\n{DECLARATION_CONTENT}\n"
            f"(or `governance: {GOVERNED}`), so who governs this repository is "
            "unknown and nothing lands (#1144 12.6a)"), main=main)
    if value == GOVERNED:
        return GovernanceReading(GOVERNED, "declared-governed", (
            f"{DECLARATION_PATH} at `main` declares this repository governed, and "
            f"no registered host declares its instrument ({INSTRUMENT_FACET}): "
            "it is governed-without-an-instrument, so no lander is bound and "
            "nothing lands here; it lands through its governance (#1144 12.6a)"),
            main=main)
    if mode != runtime_config.INSTALL_MODE_LOCAL:
        return _unknown("install-mode-disagrees", (
            f"{DECLARATION_PATH} at `main` declares this repository standalone, "
            f"and this is the {mode} install: standalone needs the explicit "
            "local install, OPENDOX_INSTALL_MODE=local or --local (FR-007), so "
            "the declaration disagrees with the install and the governance is "
            "unknown"), main=main)
    return GovernanceReading(STANDALONE, "declared-standalone", (
        f"{DECLARATION_PATH} at `main` declares this repository standalone, on "
        "the local install"), main=main)


def repository_governance(checkout_root: Path | str, *, local: bool = False,
                          env: Mapping[str, str] | None = None,
                          runner: GitRunner | None = None) -> str:
    """`standalone`, `governed` or `unknown`, failing closed (12.6a; FR-007).
    `read_governance` says why."""
    return read_governance(checkout_root, local=local, env=env,
                           runner=runner).governance


def _governed_refusal(reading: GovernanceReading) -> LandingRefused:
    """Why no lander lands here: governed (with or without an instrument), or
    unknown, named."""
    if reading.governance == GOVERNED and reading.instrument is not None:
        return LandingRefused(
            f"{reading.reason}. No lander is bound for a governed repository: "
            "a landing is submitted through the instrument, and the merge stays "
            "the governance's act (R2Q4 (a))", code="governed")
    if reading.governance == GOVERNED:
        return LandingRefused(reading.reason, code="governed-without-an-instrument")
    return LandingRefused(reading.reason, code=reading.code)


# --------------------------------------------------------------------------
# the neutral lander
# --------------------------------------------------------------------------

def _flatten(branch: str) -> str:
    return branch.replace("/", "__")


class NeutralLander:
    """`LandingPort` for a STANDALONE repository: see the module docstring.

    Bound by `bound_lander` only under `standalone`, and it re-reads the
    governance itself at the moment of landing, so a lander constructed
    directly lands nothing in a repository that is not standalone."""

    def __init__(self, checkout_root: Path | str, *, local: bool = False,
                 env: Mapping[str, str] | None = None,
                 runner: GitRunner | None = None) -> None:
        self.git = SessionGit(checkout_root, runner=runner)
        self.checkout_root = self.git.served_root
        self._local = local
        self._env = env
        self._runner = runner

    # ---- reads ----
    def _ref(self, ref: str) -> str | None:
        return _commit_at(self.git, ref)

    def _holder_of_main(self) -> Path | None:
        held = self.git.checked_out_at(DEFAULT_BRANCH)
        if not held:
            return None
        try:
            return Path(held).resolve()
        except OSError:                              # pragma: no cover
            return Path(held)

    def _served_changes(self) -> tuple[str, ...]:
        listed = self.git.git_raw(self.checkout_root, "status", "--porcelain",
                                  "--untracked-files=all")
        return tuple(line for line in listed.splitlines() if line.strip())

    # ---- the checks ----
    def _require_branch(self, branch: str) -> str:
        if not isinstance(branch, str) or not branch:
            raise LandingRefused("`land` takes the name of a local branch",
                                 code="no-such-branch")
        if branch == DEFAULT_BRANCH:
            raise LandingRefused(
                f"`land` lands a branch ON `{DEFAULT_BRANCH}`, so it does not take "
                f"`{DEFAULT_BRANCH}` itself (R2Q5 (a))", code="branch-is-main")
        if not self.git.check_ref_format(branch):
            raise LandingRefused(f"{branch!r} is not a legal branch name",
                                 code="no-such-branch")
        return branch

    def _check_remotes(self, main: str) -> None:
        """N-16: local `main` must contain each checked remote's `main`."""
        listed = self.git.git(self.checkout_root, "remote")
        names = [name for name in listed.split() if name]
        if not names:
            return
        if "origin" in names:
            names = ["origin"]
        for name in names:
            if name.startswith("-"):
                raise LandingRefused(
                    f"a remote is named {name!r}, like an option; rename it before "
                    "landing", code="remote-unreadable")
            try:
                answer = self.git.git(self.checkout_root, "ls-remote", name,
                                      f"refs/heads/{DEFAULT_BRANCH}")
            except GitError as failed:
                raise LandingRefused(
                    f"`land` reads the remote {name!r}'s `{DEFAULT_BRANCH}` with "
                    f"`git ls-remote` before it merges, and could not "
                    f"({_redact(failed.stderr) or 'no reason given'}). It refuses "
                    "rather than land a `main` that may not contain the remote's; "
                    "fix or remove the remote, then land again",
                    code="remote-unreadable") from None
            tip = None
            for line in answer.splitlines():
                sha, _tab, ref = line.partition("\t")
                if ref.strip() == f"refs/heads/{DEFAULT_BRANCH}":
                    tip = sha.strip()
            if not tip:
                continue                             # N-16: no remote `main`
            if not (self.git.has_object(tip) and self.git.is_ancestor(tip, main)):
                raise LandingRefused(
                    f"the remote {name!r}'s `{DEFAULT_BRANCH}` is at {tip[:12]}, "
                    f"which your local `{DEFAULT_BRANCH}` does not contain. `land` "
                    "never fetches or pulls, so it refuses rather than make a "
                    f"`{DEFAULT_BRANCH}` that diverges from the remote's. Bring "
                    f"the remote's `{DEFAULT_BRANCH}` into yours yourself (for "
                    f"example `git pull` with `{DEFAULT_BRANCH}` checked out), then "
                    "land again", code="remote-main-not-contained")

    def _check_served(self) -> bool:
        """True when the served checkout holds `main` (and is clean). ADV-08."""
        holder = self._holder_of_main()
        if holder is None:
            return False
        if holder != self.checkout_root:
            raise LandingRefused(
                f"`{DEFAULT_BRANCH}` is checked out at {holder}, which is not the "
                f"served checkout {self.checkout_root}; `land` moves "
                f"`{DEFAULT_BRANCH}` only in the served checkout or where no "
                "working tree holds it. Switch that working tree off "
                f"`{DEFAULT_BRANCH}`, then land again",
                code="main-checked-out-elsewhere")
        changes = self._served_changes()
        if changes:
            shown = "; ".join(line.strip() for line in changes[:5])
            more = f" and {len(changes) - 5} more" if len(changes) > 5 else ""
            raise LandingRefused(
                f"the served checkout {self.checkout_root} holds "
                f"`{DEFAULT_BRANCH}` and is not clean ({shown}{more}). `land` "
                "fast-forwards a clean checkout only, and never switches, resets "
                "or stashes it, so nothing was merged. Remedy: commit or stash "
                f"those changes (`git stash --include-untracked`), then land "
                "again (ADV-08)", code="dirty-served-checkout")
        return True

    # ---- the landing worktree ----
    def _landing_path(self, branch: str) -> Path:
        from .branch_session import container_root

        base = container_root(self.checkout_root) / LANDING_SUBDIR
        candidate = base / f"{_flatten(branch)}-{secrets.token_hex(4)}"
        if base.resolve() not in candidate.resolve().parents:
            raise LandingRefused(
                f"a landing worktree for {branch!r} would resolve outside "
                f"{base}", code="no-such-branch")
        return candidate

    def _remove_worktree(self, path: Path) -> None:
        try:
            self.git.git(self.checkout_root, "worktree", "remove", "--force",
                         str(path))
        except (GitError, SessionGitRefused):
            shutil.rmtree(path, ignore_errors=True)
            try:
                self.git.git(self.checkout_root, "worktree", "prune")
            except (GitError, SessionGitRefused):    # pragma: no cover
                pass

    def _merge(self, path: Path, branch: str, head: str, main: str) -> str:
        message = (f"Merge branch '{branch}'\n\n"
                   f"Landed with `opendox land`: a human confirmed {branch} at "
                   f"{head}.\n")
        try:
            self.git.git_raw(path, "-c", "rerere.enabled=false", "merge",
                             "--no-ff", "--no-edit", "-m", message, head)
        except GitError as failed:
            in_merge = _read(self.git, path, "rev-parse", "-q", "--verify",
                             "MERGE_HEAD")
            unmerged = self.git.git(path, "diff", "--name-only",
                                    "--diff-filter=U")
            paths = tuple(p for p in unmerged.splitlines() if p.strip())
            if in_merge or paths:
                raise MergeConflict(branch, paths) from None
            raise LandingRefused(
                f"git could not merge {branch} ({_redact(failed.stderr)}); "
                "nothing was merged and `main` is where it was",
                code="merge-failed") from None
        merged = self.git.git(path, "rev-parse", "HEAD")
        parents = self.git.git(path, "rev-list", "--parents", "-n", "1",
                               merged).split()
        if parents != [merged, main, head]:
            raise LandingRefused(
                f"the merge of {branch} did not make a merge commit of `main` "
                f"and {branch} (git made {merged[:12]} with parents "
                f"{' '.join(p[:12] for p in parents[1:]) or 'none'}), so nothing "
                "lands: a landing is a `--no-ff` merge commit that `git revert -m "
                "1` undoes (#1144 12.6)", code="not-a-merge-commit")
        return merged

    def _advance_main(self, path: Path, merged: str, main: str,
                      holds_main: bool) -> str:
        if holds_main:
            if (self._holder_of_main() != self.checkout_root
                    or self._ref(f"refs/heads/{DEFAULT_BRANCH}") != main):
                raise LandingRefused(
                    f"`{DEFAULT_BRANCH}` or the served checkout changed while the "
                    "merge was made, so the fast-forward no longer applies; "
                    f"`{DEFAULT_BRANCH}` is where it was. Land again",
                    code="fast-forward-no-longer-applies")
            self._check_served()
            try:
                self.git.fast_forward_served(merged)
            except (GitError, SessionGitRefused) as failed:
                detail = getattr(failed, "stderr", "") or str(failed)
                raise LandingRefused(
                    f"the served checkout could not be fast-forwarded to the merge "
                    f"commit {merged[:12]} ({_redact(detail)}), so `main` is "
                    "where it was and nothing landed",
                    code="fast-forward-no-longer-applies") from None
            return SERVED_FAST_FORWARDED
        try:
            self.git.git(path, "update-ref", "-m", "opendox land",
                         f"refs/heads/{DEFAULT_BRANCH}", merged, main)
        except GitError:
            raise LandingRefused(
                f"`{DEFAULT_BRANCH}` moved while the merge was made, so it was "
                "left where it moved to and nothing landed. Land again",
                code="main-moved") from None
        return SERVED_LEFT

    # ---- the one operation ----
    def land(self, branch: str, *, confirmation: Confirmation) -> Landed:
        branch = self._require_branch(branch)
        reading = read_governance(self.checkout_root, local=self._local,
                                  env=self._env, runner=self._runner)
        if reading.governance != STANDALONE:
            raise _governed_refusal(reading)
        main = reading.main or ""
        head = self._ref(f"refs/heads/{branch}")
        if head is None:
            raise LandingRefused(f"there is no local branch {branch!r} to land",
                                 code="no-such-branch")
        try:
            redeem(confirmation, branch=branch, head=head)
        except ConfirmationRefused as refused:
            raise LandingRefused(str(refused),
                                 code=f"confirmation:{refused.code}") from None
        if self.git.is_ancestor(head, main):
            raise LandingRefused(
                f"{branch} at {head[:12]} is already contained in "
                f"`{DEFAULT_BRANCH}`: there is nothing to land",
                code="already-landed")
        self._check_remotes(main)
        holds_main = self._check_served()
        path = self._landing_path(branch)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.git.git(self.checkout_root, "worktree", "add", "--detach",
                         str(path), main)
        except (GitError, OSError) as failed:
            raise LandingRefused(
                f"the landing worktree {path} could not be made "
                f"({_redact(getattr(failed, 'stderr', '') or str(failed))}); "
                "nothing was merged and `main` is where it was",
                code="landing-worktree") from None
        try:
            merged = self._merge(path, branch, head, main)
            served = self._advance_main(path, merged, main, holds_main)
        finally:
            self._remove_worktree(path)
        return Landed(branch=branch, merge_commit=merged, previous_main=main,
                      served_checkout=served)


def bound_lander(checkout_root: Path | str, *, local: bool = False,
                 env: Mapping[str, str] | None = None,
                 runner: GitRunner | None = None) -> NeutralLander | None:
    """The lander `landing_factory` and `_landing_port` bind (T016): the neutral
    lander under `standalone`, and NOTHING otherwise. Under `governed` no lander
    is bound (R2Q4 (a)); under `unknown` none is either (12.6a)."""
    reading = read_governance(checkout_root, local=local, env=env, runner=runner)
    if reading.governance != STANDALONE:
        return None
    return NeutralLander(checkout_root, local=local, env=env, runner=runner)


def request_landing(checkout_root: Path | str, branch: str, *,
                    confirmation: Confirmation, local: bool = False,
                    env: Mapping[str, str] | None = None,
                    runner: GitRunner | None = None) -> Any:
    """A landing as the governance routes it (data-model.md § "The landing's
    states"). Under `standalone`, the neutral lander's `Landed`. Under
    `governed` with an instrument, the confirmed branch submitted through the
    host's `SubmissionPort`, whose report is returned, and NO merge: the merge
    stays the governance's act (R2Q4 (a)). Otherwise a refusal naming what is
    missing: governed-without-an-instrument, or why the governance is unknown."""
    if branch == DEFAULT_BRANCH:
        raise LandingRefused(
            f"`land` lands a branch ON `{DEFAULT_BRANCH}`, so it does not take "
            f"`{DEFAULT_BRANCH}` itself (R2Q5 (a))", code="branch-is-main")
    reading = read_governance(checkout_root, local=local, env=env, runner=runner)
    if reading.governance == STANDALONE:
        return NeutralLander(checkout_root, local=local, env=env,
                             runner=runner).land(branch, confirmation=confirmation)
    if reading.governance != GOVERNED or reading.instrument is None:
        raise _governed_refusal(reading)
    git = SessionGit(checkout_root, runner=runner)
    if not isinstance(branch, str) or not git.check_ref_format(branch):
        raise LandingRefused(f"{branch!r} is not a legal branch name",
                             code="no-such-branch")
    head = _commit_at(git, f"refs/heads/{branch}")
    if head is None:
        raise LandingRefused(f"there is no local branch {branch!r} to land",
                             code="no-such-branch")
    try:
        redeem(confirmation, branch=branch, head=head)
    except ConfirmationRefused as refused:
        raise LandingRefused(str(refused),
                             code=f"confirmation:{refused.code}") from None
    try:
        port = reading.instrument(git.served_root)
        submit = getattr(port, "submit", None)
        if not callable(submit):
            raise TypeError(f"{type(port).__name__} has no submit operation")
    except Exception as failed:                     # noqa: BLE001 - name it
        raise LandingRefused(
            f"the host's instrument ({INSTRUMENT_FACET} of {reading.host}) could "
            f"not be built ({type(failed).__name__}: {failed}); nothing was "
            "submitted", code="instrument-failed") from None
    return submit(branch)
