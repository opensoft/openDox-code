"""openDox's OWN submit verb: `opendox submit` (plan 038 T015; #1144 12.4a;
openxFactory `specs/038-.../contracts/cli-http-submit-land.md`).

    opendox submit --repo-root PATH --branch BRANCH [--local] [--json]

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
such message is the port's own, which 12.1a redacts. A failure the port did
NOT name (any other exception, from the binding or from the port) is refused
with a fixed sentence naming its TYPE alone, as the route answers it: its text
is a host's port's, which this verb cannot vet, and it may carry a remote
URL's credential (12.1a).

IMPORT WEIGHT. The standard library alone at import, because
`opendox.default_profile` imports this module and must import with nothing
beyond the standard library (`tests/test_default_profile.py`).
`opendox.session_pr` is imported where it is used, since it re-exports the
landing seam (plan 038 T012), whose modules reach beyond the standard
library; so are `opendox.cli`, the runtime's configuration and the git
adapter.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


__all__ = [
    "LOCAL_BESIDE_HOSTED", "SUBMISSION_FIELDS", "UNNAMED_FAILURE",
    "BranchActionSubcommands", "cmd_submit", "submission_object",
    "submit_branch",
]

#: The `Submission` report's fields, in the order the verb prints them
#: (data-model.md § Submission; 12.1a).
SUBMISSION_FIELDS = ("remote", "ref", "url", "branch", "commit")

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


def _core():
    """The core CLI module of this module's own package, resolved when the
    verb RUNS, as `cli_project._core()` resolves it: the port binding is
    `cli._submission_port`, a named seam a host or a test replaces, so it is
    read at call time and never bound here."""
    from . import cli

    return cli


def submission_object(report) -> dict[str, str]:
    """The `Submission` report's five fields, read by name.

    A port answers ONLY on success (12.1a), so an answer that does not name
    where the work went is refused rather than printed: a report missing a
    field, or carrying one that is not a non-empty string. A host's port is
    the case this guards; `LocalGitSubmissions` always answers all five.
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
    return fields


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
    return submission_object(port.submit(branch))


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
        print(f"submit refused: {exc}", file=sys.stderr)
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


class BranchActionSubcommands:
    """The default profile's contributed verb: `submit`.

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
