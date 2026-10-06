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
  `<repo>-worktrees/landing/`, detached at `main`'s tip, with git's own
  strategy and drivers only: `.gitattributes` and the global attributes file
  are taken out of the merge, a driver this machine's own attributes still
  select is refused before merging, the fallback driver and directory-rename
  placement are pinned to git's defaults, and rerere is off, so nothing but a
  human answers a conflict; a conflict raises `MergeConflict` with the paths
  and the remedy, and nothing moves (OQ-038-1);
* then moves `main`: where the served checkout holds it (and is still clean),
  by `git merge --ff-only <merge commit>` there, the one move feature 007's
  guard admits at the served root (T013); where it holds another branch, the
  landing worktree takes `main` (git refuses that while any other working tree
  holds it, and refuses `main` to every other one meanwhile) and fast-forwards
  it there, leaving the served checkout as it was (`left`);
* pushes NOTHING (R2Q6 (a)). A landed `main` leaves the machine only by the
  user's own `git push`.

Every git command goes through `session_git.SessionGit`, the one git-write
surface, so feature 007's guard sees every one of them.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

import yaml

from .landing_confirm import Confirmation, ConfirmationRefused, redeem
from .session_git import (SERVED_FAST_FORWARD_ARGV, GitError, GitRunner,
                          SessionGit, SessionGitRefused)

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
#: The empty tree, per object format: the attribute source that carries no
#: `.gitattributes` at all (`git --attr-source`, git 2.42 and later).
_EMPTY_TREE = {
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}
#: The `merge` attribute's states that select git's OWN drivers WITHOUT a lookup
#: by name. Any named value is looked up among the drivers configured by name
#: FIRST, so even `text` or `binary` can name a configured driver (measured,
#: git 2.43: `merge.text.driver` answered `merge.default=text`); a driver can
#: resolve a conflict with no human.
_GITS_OWN_MERGE_VALUES = frozenset({"unspecified", "set", "unset"})
#: How many paths one `check-attr` call names.
_PATHS_PER_CHECK = 200
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


def _fresh_merge_driver_name() -> str:
    """A merge-driver name no configuration can have defined in advance: the
    landing merge's `merge.default`, so git's own three-way merge decides every
    file with no `merge` attribute."""
    return f"opendox-land-{secrets.token_hex(16)}"


def _commit_at(git: SessionGit, ref: str) -> str | None:
    """The commit `ref` names, as a full object id, or None."""
    sha = _read(git, git.served_root, "rev-parse", "--verify", "--quiet",
                f"{ref}^{{commit}}")
    return sha if sha and _OBJECT_ID.match(sha) else None


def _redact(text: str) -> str:
    """A git message with any credential a remote URL carries removed: the
    userinfo of a URL and every query-string value (12.1a's rule).

    The runtime's own `local_git_adapter.redact_credentials` runs FIRST: it
    knows a credential in a FRAGMENT (`#token=secret`) and a value after
    whitespace (`?token= secret`), and `git ls-remote` echoes a URL it could not
    read in exactly those shapes (Copilot's third review of openDox-code#90).
    Imported here rather than at the top, so this module keeps its light
    import."""
    from opendox.runtime.local_git_adapter import redact_credentials
    return _URL_QUERY_VALUE.sub(r"\1***", _URL_USERINFO.sub(
        r"\1***@", redact_credentials(text or "")))


def _shown(path: str) -> str:
    """A path as a message shows it: as it is, unless it holds a character a
    terminal would act on (a control, a format character such as a bidi
    override, a line separator), and then escaped, as `repr` spells it. A file
    name is the branch author's to choose, and a refusal is printed where the
    human reads it (Copilot's third review of openDox-code#90). Callers keep
    the path itself; only the message escapes it."""
    return path if path.isprintable() else repr(path)


class LandingRefused(Exception):
    """A landing that did not happen, with the case named.

    `code` names the case for a caller that answers in a protocol (T016's
    routes): `branch-is-main`, `no-such-branch`, `already-landed`,
    `not-a-repository`, `no-main`, `no-declaration`, `invalid-declaration`,
    `install-mode-refused`, `install-mode-disagrees`, `host-failed-to-load`,
    `governed-without-an-instrument`, `instrument-failed`,
    `confirmation:<case>`, `remote-unreadable`, `remote-main-not-contained`,
    `dirty-served-checkout`, `main-checked-out-elsewhere`, `merge-failed`,
    `landing-worktree`, `merge-driver`, `not-a-merge-commit`,
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
        listed = (", ".join(_shown(path) for path in self.paths) if self.paths
                  else "(git named no path)")
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
    `left` (it holds another branch, and `main` moved in the landing's own
    worktree). `pushed` is
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


#: Everything PyYAML raises on malformed input that fits the size bound: its own
#: errors (a NUL is a `ReaderError` raised while the loader is BUILT), a
#: `ValueError` from a constructor (an impossible date), and a `RecursionError`
#: from deep nesting. Each is a declaration that is not one, never a traceback
#: (the same set `doxbench_binding.read_settings_document` catches).
_PARSER_FAILURES = (yaml.YAMLError, ValueError, TypeError, RecursionError)


def _load_declaration(text: str) -> tuple[Any, str]:
    """The parsed document, or None and why it does not parse."""
    try:
        loader = _DuplicateKeyLoader(text)
    except _PARSER_FAILURES as broken:
        return None, _parse_failure(broken)
    try:
        return loader.get_single_data(), ""
    except _PARSER_FAILURES as broken:
        return None, _parse_failure(broken)
    finally:
        loader.dispose()


def _parse_failure(broken: BaseException) -> str:
    first = (str(broken).splitlines() or [type(broken).__name__])[0]
    return f"it is not valid YAML ({first})"


def _parse_declaration(text: str) -> tuple[str | None, str]:
    """The declared value, or None and why the file is not a declaration."""
    data, why = _load_declaration(text)
    if why:
        return None, why
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
    except (GitError, ValueError) as failed:     # UnicodeDecodeError is a ValueError
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

    # PROVENANCE, NOT IDENTITY. openDox's own default is not a host only where an
    # ENTRY POINT registered it (`register_default`). A host that registers the
    # same module itself holds a host's registration (`domain_profile.register`'s
    # docstring), so it governs like any host. `domain_profile` keeps that fact in
    # `_is_default` and publishes no accessor for it yet; it is read here rather
    # than inferred from the object.
    if profile is default_profile and getattr(domain_profile, "_is_default", False):
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


def _repository_reading(git: SessionGit, root: Path) -> GovernanceReading | str:
    """`main`'s tip, or why the checkout cannot be read at all (step 1)."""
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
    return main


def _host_governance(host: _HostReading, main: str) -> GovernanceReading:
    """A registered host decides, whatever any file says (step 3)."""
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


def _declared_governance(git: SessionGit, main: str, mode: str,
                         local_mode: str) -> GovernanceReading:
    """`main`'s declaration decides, where no host does (step 4)."""
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
    if mode != local_mode:
        return _unknown("install-mode-disagrees", (
            f"{DECLARATION_PATH} at `main` declares this repository standalone, "
            f"and this is the {mode} install: standalone needs the explicit "
            "local install, OPENDOX_INSTALL_MODE=local or --local (FR-007), so "
            "the declaration disagrees with the install and the governance is "
            "unknown"), main=main)
    return GovernanceReading(STANDALONE, "declared-standalone", (
        f"{DECLARATION_PATH} at `main` declares this repository standalone, on "
        "the local install"), main=main)


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
    main = _repository_reading(git, root)
    if isinstance(main, GovernanceReading):
        return main

    from .runtime import config as runtime_config

    try:
        mode = runtime_config.install_mode(env, local_flag=local)
    except runtime_config.ConfigurationError as refused:
        return _unknown("install-mode-refused", str(refused), main=main)
    host = _registered_host()
    if host is not None:
        return _host_governance(host, main)
    return _declared_governance(git, main, mode, runtime_config.INSTALL_MODE_LOCAL)


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
        """N-16: local `main` must contain each checked remote's `main`: the one
        named `origin`, else every attached remote."""
        listed = self.git.git(self.checkout_root, "remote")
        names = [name for name in listed.split() if name]
        if "origin" in names:
            names = ["origin"]
        for name in names:
            self._check_remote(name, main)

    def _push_url(self, name: str) -> str:
        """The ONE URL a `git push` to remote `name` reaches: its push URL, or
        its fetch URL where it has no `pushurl` (`git remote get-url --push`).
        The owner's later `git push` of `main` goes there, so that is the
        repository whose `main` local `main` must contain; `git ls-remote
        <name>` would read the FETCH URL, another repository where a `pushurl`
        differs (data-model.md § Landed, "The remote check"). A remote with
        several push URLs is refused by name, as `submit` refuses it."""
        try:
            listed = self.git.git(self.checkout_root, "remote", "get-url",
                                  "--push", "--all", name)
        except GitError as failed:
            raise LandingRefused(
                f"`land` could not read the remote {name!r}'s push URL "
                f"({_redact(failed.stderr) or 'no reason given'}); fix or remove "
                "the remote, then land again", code="remote-unreadable") from None
        urls = [url for url in listed.splitlines() if url.strip()]
        if len(urls) != 1:
            raise LandingRefused(
                f"the remote {name!r} has {len(urls)} push URLs, and `land` "
                f"checks the one repository a `git push` of `{DEFAULT_BRANCH}` "
                "reaches before it merges. Give the remote one push URL "
                "(`git remote set-url --push`), then land again",
                code="several-push-urls")
        return urls[0]

    def _check_remote(self, name: str, main: str) -> None:
        if name.startswith("-"):
            raise LandingRefused(
                f"a remote is named {name!r}, like an option; rename it before "
                "landing", code="remote-unreadable")
        url = self._push_url(name)
        try:
            # The push URL is read through a TRANSIENT remote passed in the
            # command's environment, so it never reaches git's argv, where any
            # local user could read a credential it carries.
            answer = self.git.ls_remote_url(self.checkout_root, url,
                                            f"refs/heads/{DEFAULT_BRANCH}")
        except GitError as failed:
            raise LandingRefused(
                f"`land` reads the remote {name!r}'s `{DEFAULT_BRANCH}` with "
                f"`git ls-remote` before it merges, and could not "
                f"({_redact(failed.stderr) or 'no reason given'}). It refuses "
                "rather than land a `main` that may not contain the remote's; "
                "fix or remove the remote, then land again",
                code="remote-unreadable") from None
        tips = [sha.strip() for sha, _tab, ref in
                (line.partition("\t") for line in answer.splitlines())
                if ref.strip() == f"refs/heads/{DEFAULT_BRANCH}"]
        if not tips:
            return                                   # N-16: no remote `main`
        tip = tips[-1]
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

    # ---- the merge: git's own drivers, and a conflict always shown ----
    def _attribute_neutral(self, path: Path) -> tuple[str, ...]:
        """The options that take `.gitattributes` and the global attributes file
        out of the merge, so no committed or ambient attribute selects a merge
        driver (Copilot review of openDox-code#90: `merge=union` resolved an
        overlapping edit into a clean two-parent merge)."""
        found = _read(self.git, path, "rev-parse", "--show-object-format")
        empty = _EMPTY_TREE.get(found or "sha1")
        if empty is None:
            raise LandingRefused(
                f"this repository's object format is {found!r}, which `land` does "
                "not know an empty tree for; nothing was merged",
                code="merge-failed")
        return (f"--attr-source={empty}", "-c", f"core.attributesFile={os.devnull}")

    def _changed_paths(self, path: Path, main: str, head: str) -> list[str]:
        """Every path either side changed since their merge base(s)."""
        bases = (_read(self.git, path, "merge-base", "--all", main, head) or "").split()
        changed: set[str] = set()
        for base in bases:
            for tip in (main, head):
                listed = self.git.git_raw(path, "diff", "--no-ext-diff",
                                          "--no-textconv", "--no-renames",
                                          "--name-only", "-z", base, tip)
                changed.update(name for name in listed.split("\0") if name)
        return sorted(changed)

    def _refuse_merge_drivers(self, path: Path, neutral: tuple[str, ...],
                              branch: str, main: str, head: str) -> None:
        """Refuse BEFORE merging where an attribute this machine still applies
        (its `$GIT_DIR/info/attributes`, or the system's) selects a merge driver
        other than git's own for a path either side changed: such a driver can
        resolve a conflict with no human (#1144 12.6)."""
        names = self._changed_paths(path, main, head)
        drivers: list[str] = []
        for start in range(0, len(names), _PATHS_PER_CHECK):
            listed = self.git.git_raw(path, *neutral, "check-attr", "-z", "merge",
                                      "--", *names[start:start + _PATHS_PER_CHECK])
            fields = listed.split("\0")
            for name, value in zip(fields[0::3], fields[2::3]):
                if name and value not in _GITS_OWN_MERGE_VALUES:
                    drivers.append(_shown(f"{name} (merge={value})"))
        if drivers:
            raise LandingRefused(
                f"{', '.join(drivers[:5])} carry a `merge` attribute that selects a "
                "driver other than git's own, set on this machine (in "
                "`$GIT_DIR/info/attributes` or the system's gitattributes). Such "
                "a driver can resolve a conflict with no human, and `land` never "
                "lets one (#1144 12.6), so nothing was merged. Remove the "
                f"attribute, or merge {branch} with git yourself",
                code="merge-driver")

    def _merge(self, path: Path, branch: str, head: str, main: str) -> str:
        neutral = self._attribute_neutral(path)
        self._refuse_merge_drivers(path, neutral, branch, main, head)
        message = (f"Merge branch '{branch}'\n\n"
                   f"Landed with `opendox land`: a human confirmed {branch} at "
                   f"{head}.\n")
        try:
            # `--strategy=ort`: git's own strategy, so no `pull.twohead` setting
            # chooses another (`ours` would drop the branch with no conflict);
            # rerere off, so no recorded resolution answers for the human. And
            # the two settings that would answer a conflict, pinned for this
            # merge (Copilot's second review of openDox-code#90; MEASURED, git
            # 2.43):
            # - `merge.default` names the driver for every file with NO `merge`
            #   attribute, so `merge.default=union` resolved an overlapping edit
            #   into a clean merge. git looks the name up among the drivers
            #   configured by name FIRST and falls back to its own three-way
            #   merge for a name it does not find, so a FRESH name no
            #   configuration can know is the one value no driver answers (an
            #   empty value was answered by a driver configured as
            #   `merge..driver`, and `text` by `merge.text.driver`);
            # - `merge.directoryRenames=true` places a file added under a
            #   directory the other side renamed, with no conflict, where git's
            #   default stops and shows it.
            self.git.git_raw(path, *neutral, "-c", "rerere.enabled=false",
                             "-c", f"merge.default={_fresh_merge_driver_name()}",
                             "-c", "merge.directoryRenames=conflict",
                             "merge", "--strategy=ort", "--no-ff", "--no-edit",
                             "-m", message, head)
        except GitError as failed:
            unmerged = self.git.git_raw(path, "diff", "--name-only", "-z",
                                        "--diff-filter=U")
            paths = tuple(dict.fromkeys(p for p in unmerged.split("\0") if p))
            if paths:
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
        return self._advance_main_here(path, merged, main)

    def _advance_main_here(self, path: Path, merged: str, main: str) -> str:
        """Advance `main` IN THE LANDING WORKTREE, where the served checkout
        holds another branch: the landing worktree TAKES `main`, then
        fast-forwards it to the merge commit, so `main` moves with a working
        tree's index and files and never by its ref alone.

        Taking it is the exclusive access. git refuses to check out a branch
        another working tree holds, and, while this one holds `main`, refuses
        every other working tree `main`; so no working tree can take `main`
        between a check and the move and be left behind a moved ref, which a
        read of the holder followed by a ref update could not promise (Copilot's
        second review of openDox-code#90)."""
        try:
            self.git.git(path, "switch", "--quiet", DEFAULT_BRANCH)
        except GitError as failed:
            holder = self._holder_of_main()
            if holder is not None:
                raise LandingRefused(
                    f"`{DEFAULT_BRANCH}` was checked out at {holder} while the "
                    f"merge was made, so the landing could not take it; "
                    f"`{DEFAULT_BRANCH}` is where it was. Land again",
                    code="main-checked-out-elsewhere") from None
            raise LandingRefused(
                f"the landing worktree could not take `{DEFAULT_BRANCH}` "
                f"({_redact(failed.stderr)}); `{DEFAULT_BRANCH}` is where it was",
                code="landing-worktree") from None
        try:
            if self.git.git(path, "rev-parse", "HEAD") != main:
                raise GitError(("rev-parse", "HEAD"), 1, "main moved")
            # The funnel pins the settings that could make this a merge
            # (`session_git.SERVED_FAST_FORWARD_SETTINGS`).
            self.git.git(path, *SERVED_FAST_FORWARD_ARGV, merged)
        except GitError:
            raise LandingRefused(
                f"`{DEFAULT_BRANCH}` moved while the merge was made, so it was "
                "left where it moved to and nothing landed. Land again",
                code="main-moved") from None
        if self._ref(f"refs/heads/{DEFAULT_BRANCH}") != merged:
            raise LandingRefused(
                f"`{DEFAULT_BRANCH}` did not land on the merge commit "
                f"{merged[:12]}, so nothing is reported as landed. Look at "
                f"`{DEFAULT_BRANCH}` before landing again", code="main-moved")
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
    # READ AGAIN, immediately before the submission: a branch that moved after
    # the human confirmed it (even while the instrument was built) is not the
    # head the human confirmed. `submit(branch)` takes a branch name (12.1), so
    # a move after this read stays the instrument's to see; it is a stated
    # limit (Copilot review of openDox-code#90).
    if _commit_at(git, f"refs/heads/{branch}") != head:
        raise LandingRefused(
            f"{branch} moved after the human confirmed it at {head[:12]}, so "
            "nothing was submitted: confirm the new head", code="confirmation:another-head")
    return submit(branch)
