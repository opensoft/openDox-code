"""openDox's OWN branch verbs: `opendox submit` (plan 038 T015; #1144 12.4a)
and `opendox land` (plan 038 T016; #1144 12.6a), as openxFactory
`specs/038-.../contracts/cli-http-submit-land.md` shapes them.

    opendox submit --repo-root PATH --branch BRANCH [--local] [--json]
    opendox land   --repo-root PATH --branch BRANCH [--local] [--json]

12.4a's ratified shape (ADV-01). Before this module a standalone openDox could
not submit at all, `gh` or no `gh`: the only act that submitted was openXdox's
`gate open-pr`. This is openDox's own, in its own surface and not under
`gate`, and `opendox.serve_branch_actions` is its route.

A CONTRIBUTION OF openDox'S DEFAULT PROFILE (decision N-2, refined by ADV-14;
R2Q3 (a)). `opendox.default_profile` declares `BranchActionSubcommands` in
`SUBCOMMAND_EXTENSIONS`, so `cli.build_parser()` registers it through the § 2.4
seam with the runtime verbs. A host profile that replaces the default carries
no `submit`, and its command tree is what it was.

THE ACT, SHARED BY BOTH DOORS (`submit_branch`): refuse the default branch,
`main`, by name (R2Q5 (a)); push the branch through the bound `SubmissionPort`;
and answer the `Submission` report (12.1a), its five fields read by name. The
verb takes its port from `cli._submission_port` and the route from the
server's `submission_factory` (12.4's two bindings, T014). Each is
`LocalGitSubmissions` where nothing is injected, a plain `git push` that names
no platform and never runs `gh`. Where a governed host contributes its own
port through them, the act goes through that port and reports where the work
went (R2Q4 (a)). So the act is the same in every governance mode (CF-1), and it
reads no governance itself.

THE INSTALL MODE IS NOT READ (decision N-17; ADV-04). The verb pushes the
invoking user's own checkout with that user's own git, which a hosted plane
never holds, so it does not depend on the mode, and F12.2 runs it with neither
`--local` nor `OPENDOX_INSTALL_MODE`. `--local` is accepted, as
`generate-and-open` accepts it (R2Q9 (a) item 7), and is refused ONLY where it
disagrees with `OPENDOX_INSTALL_MODE=hosted`, naming both (the contract's
words). That value is read as `runtime.config.install_mode` reads it, stripped
and matched case included; any other value, one the selector itself would
refuse included, is not this verb's to judge, since the verb does not depend
on the mode.

NO ACTOR GATE (OQ-12-9). The verb runs as the invoking user, in that user's
checkout. F12.2 runs it non-interactively, with no actor.

REFUSALS: a named sentence on stderr and exit 1, with nothing pushed and no
traceback (requirement 11's fourth scenario): `main`; no remote, or several
and none named `origin` (`NoSubmissionTarget`); a remote with several push
URLs, a rejected push or a failed transport (`SubmissionRefused`). Every
such message is the port's own, with every credential-shaped URL redacted
again at this boundary (`refusal_text`; 12.1a), since a host's port's text
is not this module's to vet; the report's `url` and `remote` are redacted
the same way (`submission_object`). A failure the port did
NOT name (any other exception, from the binding or from the port) is refused
with a fixed sentence naming its TYPE alone, as the route answers it: its text
is a host's port's, which this verb cannot vet, and it may carry a remote
URL's credential (12.1a).

LAND (plan 038 T016; #1144 12.6a). `land` lands BRANCH on `main` with ONE
confirmed act, through the seam T012 declared (`opendox.landing`):

* ITS BINDING. The verb takes its lander from `cli._landing_port` and the
  route from the server's `landing_factory`, the two bindings 12.6a names.
  Each binds the neutral lander only where the repository is `standalone`
  (the explicit local install with `main`'s committed declaration), and
  nothing otherwise (`landing.bound_lander`).
* WHERE NO LANDER IS BOUND (`landing_refusal`). A `governed` repository with
  a host's contributed instrument submits through it and reports where the
  work went, and the merge stays the governance's act (R2Q4 (a)). Anything
  else is refused BY NAME, before any human is asked to confirm a landing
  that cannot happen: governed-without-an-instrument, or why the governance
  is `unknown` (no `main`; no declaration, naming the exact file and content
  to commit; a host that failed to load; the install mode), as
  `landing.read_governance` names it.
* THE CONFIRMATION. The verb asks at the CONTROLLING TERMINAL
  (`landing_confirm.confirm_at_terminal`, the first of the two issuers),
  showing the branch, its head and the OPERATION this landing performs: a
  merge commit onto `main` where a lander is bound, a submission to the
  host's instrument where the repository is governed (`landing_operation`,
  decided before the prompt from the reading `landing_refusal` uses; holder
  ruling item 10, #656 `6103915259`). The act performs exactly the
  operation the question named, or refuses (`operation-changed`). The
  human types the branch's name. There
  is NO flag that answers for the human (decision N-11; 12.6a: "refuses when
  there is none"), so a piped or scripted `land` is refused. This module and
  `opendox.serve_branch_actions` are the two interactive layers
  `landing_confirm.INTERACTIVE_LAYERS` names, and no other module may call an
  issuer.
* THE ANSWER (`land_branch`): the `Landed` object (`landed_object`) under
  `standalone`, or the instrument's `Submission` (`submission_object`) under
  `governed`; the two are told apart by their fields. A lander is a
  binding's answer (a host's or a test's), so its `Landed` is CHECKED field
  by field against data-model.md § Landed, as a report is, and never
  printed on trust (lane 3's MAJOR on #100 at `99c4e079`). The printed report
  names the merge commit and the `git revert -m 1` that undoes it. `land`
  pushes nothing.
* `--local` IS READ HERE, unlike `submit`'s: `standalone` needs the explicit
  local install, which `--local` selects exactly as `OPENDOX_INSTALL_MODE=local`
  does, and a flag and a setting that disagree are refused naming both
  (R2Q9 (a) item 7), by the governance reading itself.
* EVERY REFUSAL IS NAMED and passes through `redacted_text`, whoever wrote
  it: the lander's own are redacted already, and an instrument's are a
  host's, which this module cannot vet. A failure the instrument did not name
  is refused naming its TYPE alone, as `submit` refuses one.

IMPORT WEIGHT. The standard library alone at import, because
`opendox.default_profile` imports this module and must import with nothing
beyond the standard library (`tests/test_default_profile.py`).
`opendox.session_pr` is imported where it is used, since it re-exports the
landing seam (plan 038 T012), whose modules reach beyond the standard
library; so are `opendox.cli`, the runtime's configuration, the git adapter,
and the landing seam's own modules.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


__all__ = [
    "LANDED_FIELDS", "LANDED_NOT_THE_LANDINGS", "LOCAL_BESIDE_HOSTED",
    "NO_LANDER", "OPERATION_CHANGED", "SUBMISSION_FIELDS",
    "UNNAMED_FAILURE", "UNNAMED_LANDING_FAILURE",
    "BranchActionSubcommands", "branch_head", "cmd_land", "cmd_submit",
    "land_branch", "landed_object", "landing_operation", "landing_refusal",
    "main_refused", "redacted_text",
    "refusal_text", "submission_object", "submit_branch",
]

#: The `Submission` report's fields, in the order the verb prints them
#: (data-model.md § Submission; 12.1a).
SUBMISSION_FIELDS = ("remote", "ref", "url", "branch", "commit")

#: A `scheme://` URL inside free text, up to whitespace or a quoting mark.
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s`'\"<>]+")

#: A full git object name: 40 hex digits (sha1), or 64 (sha256).
_OBJECT_NAME = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")

#: The refusal of `--local` beside `OPENDOX_INSTALL_MODE=hosted` (N-17).
LOCAL_BESIDE_HOSTED = (
    "--local selects the LOCAL install and OPENDOX_INSTALL_MODE=hosted selects "
    "the HOSTED one. Both are explicit selections and they disagree, so "
    "neither overrides the other. submit does not depend on the install mode: "
    "drop the flag, or unset OPENDOX_INSTALL_MODE (or set it to `local`)")

#: The refusal of a failure the port did not name. `{kind}` is the
#: exception's type, and nothing else of it is printed (12.1a).
UNNAMED_FAILURE = (
    "the submission port raised {kind}, a failure it did not name, so nothing "
    "is reported as submitted. Its text is not printed: it is a host's port's, "
    "which this verb cannot vet")


#: The `Landed` object's fields, in the order the verb prints them
#: (data-model.md § Landed).
LANDED_FIELDS = ("branch", "merge_commit", "previous_main", "served_checkout",
                 "pushed")

#: The refusal where the repository is `standalone` and still no lander is
#: bound: a binding that answered nothing (a host's or a test's).
NO_LANDER = (
    "no lander is bound for this checkout, so nothing lands: the binding that "
    "supplies one (`landing_factory`, or `_landing_port`) answered none")

#: The refusal of a `Landed` answer that is not the landing's. `{field}` is
#: the field's NAME, and nothing the answer carried is repeated (12.1a).
#: The lander may have merged before it answered, so it says where to look.
LANDED_NOT_THE_LANDINGS = (
    "the lander answered a `Landed` whose `{field}` is not the landing's "
    "(data-model.md § Landed), so nothing is reported as landed. Whether "
    "`main` moved is git's to say: `git log -1 main`")

#: The refusal of an act that would not be the operation its confirmation
#: named (holder ruling item 10): the binding changed after the question.
OPERATION_CHANGED = (
    "the landing would not be the operation the confirmation named: what "
    "this checkout binds changed after the question was asked, so nothing "
    "landed and nothing was submitted. Ask again, and confirm what the new "
    "question names")

#: The refusal of a failure the landing did not name. `{kind}` is the
#: exception's type, and nothing else of it is printed (12.1a).
UNNAMED_LANDING_FAILURE = (
    "the landing raised {kind}, a failure it did not name, so nothing is "
    "reported as landed. Its text is not printed: it may be a host's "
    "instrument's, which this verb cannot vet")


def _core():
    """The core CLI module of this module's own package, resolved when the
    verb RUNS, as `cli_project._core()` resolves it: the port binding is
    `cli._submission_port`, a named seam a host or a test replaces, so it is
    read at call time and never bound here."""
    from . import cli

    return cli


def redacted_text(text: str) -> str:
    """`text` as either door may show it: every credential gone (12.1a).

    Every `scheme://` URL in it passes through
    `submission_push.redact_destination` first, which treats ANY userinfo of
    a non-ssh URL as a secret (a token spelled as a bare username included)
    and redacts every query and fragment value, keeping the scheme, host and
    path. The package's free-text redactor then runs over the result for the
    shapes that are not `scheme://` URLs. It spares a bare username, because
    after the first pass the only userinfo left in a URL is an ssh login name
    or the redaction marker, and so a refusal can still name the host that
    would not answer.
    """
    from opendox.runtime.local_git_adapter import redact_credentials
    from opendox.submission_push import redact_destination

    text = _URL_IN_TEXT.sub(lambda found: redact_destination(found.group(0)),
                            text)
    return redact_credentials(text, a_bare_username_is_not_a_secret=True)


def submission_object(report, branch: str) -> dict[str, str]:
    """The `Submission` report's five fields, read by name and checked.

    A port answers ONLY on success (12.1a), so an answer that does not name
    where the work went is refused rather than printed: a report missing a
    field, or carrying one that is not a non-empty string. A host's port is
    the case this guards; `LocalGitSubmissions` always answers all five.

    THE THREE FIELDS THAT NAME THE SUBMISSION ARE CHECKED, not printed on
    trust: `branch` must be the branch submitted, `ref` must be
    `refs/heads/<that branch>`, and `commit` must be a full object name (40
    hex digits, or 64 in a sha256 repository). A report that says anything
    else is refused by a fixed sentence that repeats none of it.

    THE TWO FIELDS THAT NAME A PLACE ARE REDACTED HERE, whoever answered
    (12.1a; Copilot on #96 at `7dc8214b`): `url` and `remote` pass through
    `redacted_text`, so a credential a host's port returns, whole or
    embedded, reaches neither the printed report nor the route's answer. It
    changes nothing the neutral port reports, which is redacted already.
    """
    from opendox.session_pr import SubmissionRefused

    fields: dict[str, str] = {}
    for name in SUBMISSION_FIELDS:
        value = getattr(report, name, None)
        if not isinstance(value, str) or not value:
            raise SubmissionRefused(
                "the submission port answered without naming where the work "
                f"went (its report carries no `{name}`), so nothing is "
                "reported as submitted")
        fields[name] = value
    for name, matches in (
            ("branch", fields["branch"] == branch),
            ("ref", fields["ref"] == "refs/heads/" + branch),
            ("commit", _OBJECT_NAME.fullmatch(fields["commit"]) is not None)):
        if not matches:
            raise SubmissionRefused(
                f"the submission port answered a report whose `{name}` is not "
                "the submission's, so nothing is reported as submitted")
    for name in ("url", "remote"):
        fields[name] = redacted_text(fields[name])
    return fields


def refusal_text(exc: BaseException) -> str:
    """A `SubmissionError`'s message as either door shows it (12.1a).

    The neutral port's refusals are redacted where they are raised; a host's
    contributed port's are not this module's to vet, so every refusal either
    door prints or answers passes through `redacted_text`, the report's own
    rule.
    """
    return redacted_text(str(exc))


def submit_branch(port, branch: str) -> dict[str, str]:
    """THE ACT: push `branch` through `port` and answer the report.

    Refuses the default branch BEFORE the port is asked (R2Q5 (a)), so no
    port, a host's included, is ever handed `main`. Raises `SubmissionError`
    (its `NoSubmissionTarget` or `SubmissionRefused`) on every failure, and
    returns only the report of a submission that happened.
    """
    from opendox.runtime.local_git_adapter import DEFAULT_BRANCH
    from opendox.session_pr import SubmissionRefused

    if branch == DEFAULT_BRANCH:
        raise SubmissionRefused(
            f"`{DEFAULT_BRANCH}` is the default branch, and a submission takes "
            "any local branch except it (R2Q5 (a)); nothing is pushed. Submit "
            "the branch the work is on.")
    return submission_object(port.submit(branch), branch)


def _install_mode_refusal(args: argparse.Namespace) -> str | None:
    """Why `--local` is refused here, or None (decision N-17).

    Without `--local` nothing is read. With it, the one selection the flag can
    disagree with is `OPENDOX_INSTALL_MODE=hosted`, read as the selector reads
    it (stripped, case included); every other value is accepted, since the
    verb does not depend on the mode.
    """
    if not args.local:
        return None
    from opendox.runtime import config as runtime_config

    selected = os.environ.get(runtime_config.PREFIX + "INSTALL_MODE", "")
    if selected.strip() == runtime_config.INSTALL_MODE_HOSTED:
        return LOCAL_BESIDE_HOSTED
    return None


def _report_lines(report: dict[str, str]) -> list[str]:
    """The printed report: where the work went (12.1a)."""
    return [f"submitted `{report['branch']}` to `{report['remote']}`",
            f"  ref:    {report['ref']}",
            f"  url:    {report['url']}",
            f"  commit: {report['commit']}"]


def cmd_submit(args: argparse.Namespace) -> int:
    """`opendox submit`: push one branch and print where it went."""
    refusal = _install_mode_refusal(args)
    if refusal is not None:
        print(f"submit refused: {refusal}", file=sys.stderr)
        return 1
    from opendox.session_pr import SubmissionError

    try:
        report = submit_branch(_core()._submission_port(Path(args.repo_root)),
                               args.branch)
    except SubmissionError as exc:
        print(f"submit refused: {refusal_text(exc)}", file=sys.stderr)
        return 1
    # A host's binding or port, unvetted: its type is all this verb prints.
    except Exception as exc:  # noqa: BLE001
        print("submit refused: "
              + UNNAMED_FAILURE.format(kind=type(exc).__name__),
              file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report))
    else:
        print("\n".join(_report_lines(report)))
    return 0


# --------------------------------------------------------------------------
# land (plan 038 T016; #1144 12.6a)
# --------------------------------------------------------------------------

def main_refused():
    """The refusal of `main` itself, as the lander words it (R2Q5 (a))."""
    from opendox.landing import DEFAULT_BRANCH, LandingRefused

    return LandingRefused(
        f"`land` lands a branch ON `{DEFAULT_BRANCH}`, so it does not take "
        f"`{DEFAULT_BRANCH}` itself (R2Q5 (a))", code="branch-is-main")


def branch_head(checkout_root, branch: str) -> str:
    """`branch`'s head, the commit a confirmation is bound to, or a refusal
    naming why there is none. Read through the one git surface,
    `session_git.SessionGit`, so feature 007's guard sees the read."""
    from opendox.landing import DEFAULT_BRANCH, LandingRefused
    from opendox.session_git import GitError, SessionGit

    if branch == DEFAULT_BRANCH:
        raise main_refused()
    git = SessionGit(Path(checkout_root))
    if not isinstance(branch, str) or not git.check_ref_format(branch):
        raise LandingRefused(f"{branch!r} is not a legal branch name",
                             code="no-such-branch")
    try:
        head = git.git(git.served_root, "rev-parse", "--verify", "--quiet",
                       f"refs/heads/{branch}^{{commit}}")
    except GitError:
        head = ""
    if not _OBJECT_NAME.fullmatch(head):
        raise LandingRefused(f"there is no local branch {branch!r} to land",
                             code="no-such-branch")
    return head


def _usable(lander):
    """`lander` where it can land (a callable `land`), else None. A binding's
    answer is a host's or a test's, so one with no `land` operation is NO
    lander: it must neither offer the act nor fail it with a 500 (Copilot at
    `1bba2b1c` on #100)."""
    if lander is None:
        return None
    try:
        return lander if callable(getattr(lander, "land", None)) else None
    except Exception:  # noqa: BLE001 - a binding that cannot be read lands nothing
        return None


def landing_refusal(lander, checkout_root, *, local: bool = False):
    """None where `land` can act on `checkout_root`, else the refusal that
    names why not (contracts § /capabilities, the `actions.land` row).

    `land` can act where a lander is bound (`standalone`), or where the
    repository is `governed` and a host's instrument is contributed, through
    which `land` submits (R2Q4 (a)). Otherwise the refusal is the governance
    reading's own: governed-without-an-instrument, or why it is `unknown`.
    """
    from opendox import landing

    if _usable(lander) is not None:
        return None
    reading = landing.read_governance(checkout_root, local=local)
    if reading.governance == landing.GOVERNED:
        if reading.instrument is not None:
            return None
        return landing.LandingRefused(reading.reason,
                                      code="governed-without-an-instrument")
    if reading.governance == landing.UNKNOWN:
        return landing.LandingRefused(reading.reason, code=reading.code)
    return landing.LandingRefused(NO_LANDER, code="no-lander-bound")


def landing_operation(lander, checkout_root, *, local: bool = False) -> str:
    """The operation `land` performs on `checkout_root`, decided from the
    reading `landing_refusal` makes, or that refusal raised.

    `landing_confirm.OPERATION_MERGE` where a lander is bound (a merge commit
    onto `main`), `OPERATION_SUBMIT` where the repository is `governed` and a
    host's instrument is contributed (R2Q4 (a)). Each issuer states it BEFORE
    it asks (holder ruling item 10, #656 `6103915259`), and `land_branch`
    performs it or refuses.
    """
    from opendox.landing_confirm import OPERATION_MERGE, OPERATION_SUBMIT

    # The binding is read ONCE, and that one reading decides the operation.
    usable = _usable(lander)
    refused = landing_refusal(usable, checkout_root, local=local)
    if refused is not None:
        raise refused
    return OPERATION_MERGE if usable is not None else OPERATION_SUBMIT


def landed_object(landed, branch: str) -> dict:
    """The `Landed` object's five fields, read by name and CHECKED.

    A lander is a binding's answer, a host's or a test's, so nothing it says
    is printed on trust (lane 3's MAJOR on #100 at `99c4e079`; one trust
    model, as `submission_object` holds a port's report to): each field is
    held to data-model.md § Landed. `branch` must be the branch landed,
    `merge_commit` and `previous_main` full object names (40 hex digits, or
    64), `served_checkout` `fast-forwarded` or `left`, and `pushed` exactly
    False. Each must be exactly that type, never a subclass that could print
    otherwise than it compares. Any other answer is refused by a fixed
    sentence that names the field and repeats nothing it carried.
    """
    from opendox import landing

    fields = {name: getattr(landed, name, None) for name in LANDED_FIELDS}

    def text(name: str) -> str | None:
        value = fields[name]
        return value if type(value) is str else None

    def object_name(name: str) -> bool:
        value = text(name)
        return value is not None and _OBJECT_NAME.fullmatch(value) is not None

    for name, matches in (
            ("branch", text("branch") == branch),
            ("merge_commit", object_name("merge_commit")),
            ("previous_main", object_name("previous_main")),
            ("served_checkout", text("served_checkout") in (
                landing.SERVED_FAST_FORWARDED, landing.SERVED_LEFT)),
            ("pushed", fields["pushed"] is False)):
        if not matches:
            raise landing.LandingRefused(
                LANDED_NOT_THE_LANDINGS.format(field=name),
                code="answer-not-the-landing")
    return fields


def land_branch(lander, checkout_root, branch: str, confirmation, *,
                operation: str, local: bool = False) -> dict:
    """THE LAND ACT, SHARED BY BOTH DOORS: land `branch` with `confirmation`.

    `operation` is the one the confirmation's question named
    (`landing_operation`, decided before the human was asked). The act
    performs exactly it: where the operation it would perform now is another
    (the binding changed after the question), it is refused by name
    (`operation-changed`), and neither the lander nor the instrument is
    asked (holder ruling item 10, #656 `6103915259`).

    Through the bound lander where there is one, answering the `Landed`
    object. Where there is none, through the host's instrument under
    `governed` (`landing.request_landing`, which spends the confirmation
    against the branch's head and submits), answering its `Submission`
    object, checked and redacted by `submission_object`. Otherwise refused by
    name (`landing_refusal`). `main` is refused before anything is asked.
    """
    from opendox import landing
    from opendox.landing_confirm import OPERATION_MERGE

    if branch == landing.DEFAULT_BRANCH:
        raise main_refused()
    performing = landing_operation(lander, checkout_root, local=local)
    if performing != operation:
        raise landing.LandingRefused(OPERATION_CHANGED, code="operation-changed")
    # the branch taken IS the operation decided: never a second reading
    if performing == OPERATION_MERGE:
        return landed_object(lander.land(branch, confirmation=confirmation),
                             branch)
    report = landing.request_landing(checkout_root, branch,
                                     confirmation=confirmation, local=local)
    return submission_object(report, branch)


def _landed_lines(landed: dict) -> list[str]:
    """The printed report: the merge commit, and the command that undoes it.
    The branch name is shown as the prompt shows it, escaped where it holds a
    character a terminal acts on (`session_git.shown`; Copilot at `1bba2b1c`)."""
    from opendox.session_git import shown

    merge = landed["merge_commit"]
    return [f"landed `{shown(landed['branch'])}` on `main` with the merge commit "
            f"{merge}",
            f"  previous main:   {landed['previous_main']}",
            f"  served checkout: {landed['served_checkout']}",
            "  pushed nothing:  `git push` publishes `main` when you choose",
            f"  undo:            git revert -m 1 {merge}"]


def _landing_failure_text(exc: BaseException) -> str | None:
    """A NAMED failure's text as the verb prints it, redacted; None for a
    failure nobody named."""
    from opendox.landing import LandingRefused
    from opendox.landing_confirm import ConfirmationRefused
    from opendox.session_pr import SubmissionError

    if isinstance(exc, (LandingRefused, ConfirmationRefused, SubmissionError)):
        return redacted_text(str(exc))
    return None


def cmd_land(args: argparse.Namespace) -> int:
    """`opendox land`: confirm at the terminal, land, and print what landed."""
    from opendox import landing_confirm
    from opendox.landing import DEFAULT_BRANCH

    root = Path(args.repo_root)
    try:
        # the argument's own fault first, before any read of the repository
        if args.branch == DEFAULT_BRANCH:
            raise main_refused()
        lander = _core()._landing_port(root, local=args.local)
        # what this landing performs, decided BEFORE the human is asked
        operation = landing_operation(lander, root, local=args.local)
        head = branch_head(root, args.branch)
        confirmation = landing_confirm.confirm_at_terminal(
            args.branch, head, operation=operation)
        answer = land_branch(lander, root, args.branch, confirmation,
                             operation=operation, local=args.local)
    # The lander's, the confirmation's or an instrument's NAMED failure, or
    # one nobody named: its type is all this verb prints of the last.
    except Exception as exc:  # noqa: BLE001
        said = _landing_failure_text(exc)
        print("land refused: " + (said if said is not None else
                                  UNNAMED_LANDING_FAILURE.format(
                                      kind=type(exc).__name__)),
              file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(answer))
    elif "merge_commit" in answer:
        print("\n".join(_landed_lines(answer)))
    else:
        print("\n".join(_report_lines(answer)
                        + ["  the merge stays the governance's act (R2Q4 (a))"]))
    return 0


class BranchActionSubcommands:
    """The default profile's contributed verbs: `submit` and `land`.

    Conforms to `subcommand_extension.SubcommandExtension` STRUCTURALLY, as
    `RuntimeSubcommand` does, importing nothing from it.
    """

    def register(self, subparsers) -> None:
        submit = subparsers.add_parser(
            "submit",
            help="push a local branch to its remote and report where it went",
            description=(
                "Push BRANCH, any local branch but main, to the remote named "
                "origin (else the sole remote), with plain git, and print the "
                "remote, the ref, the URL (any credential redacted) and the "
                "commit."))
        submit.add_argument("--repo-root", required=True,
                            help="the checkout the branch is in")
        submit.add_argument("--branch", required=True,
                            help="the local branch to push (any but main)")
        submit.add_argument(
            "--local", action="store_true",
            help="the local single-user install, as OPENDOX_INSTALL_MODE=local "
                 "selects it. submit does not depend on the install mode; the "
                 "flag is refused beside OPENDOX_INSTALL_MODE=hosted")
        submit.add_argument("--json", action="store_true",
                            help="print the report as one JSON object")
        submit.set_defaults(func=cmd_submit)

        # NO FLAG ANSWERS FOR THE HUMAN (decision N-11): these four options
        # are the whole verb, and `tests/test_landing_guardrails.py` holds them.
        land = subparsers.add_parser(
            "land",
            help="land a local branch on main with one merge commit, confirmed "
                 "at the terminal",
            description=(
                "Merge BRANCH, any local branch but main, into main with a "
                "--no-ff merge commit, after you type its name at the "
                "controlling terminal. A standalone repository (the local "
                "install, and main's own .opendox/governance.yaml) is merged "
                "here and nothing is pushed; a governed one is submitted "
                "through its governance's instrument. The report names the "
                "`git revert -m 1` that undoes a landing."))
        land.add_argument("--repo-root", required=True,
                          help="the checkout the branch is in")
        land.add_argument("--branch", required=True,
                          help="the local branch to land (any but main)")
        land.add_argument(
            "--local", action="store_true",
            help="the local single-user install, exactly as "
                 "OPENDOX_INSTALL_MODE=local selects it; refused beside "
                 "OPENDOX_INSTALL_MODE=hosted")
        land.add_argument("--json", action="store_true",
                          help="print what landed as one JSON object")
        land.set_defaults(func=cmd_land)
