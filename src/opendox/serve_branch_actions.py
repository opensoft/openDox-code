"""openDox's OWN submit route: `POST /actions/session/submit` (plan 038 T015;
#1144 12.4a; openxFactory `specs/038-.../contracts/cli-http-submit-land.md`).

12.4a gives openDox an act of its own: "CLI `submit --repo-root <repo> --branch
<session-branch>` and route `POST /actions/session/submit`". This module is the
route. `opendox.cli_branch_actions` is the verb, and it holds the ACT both
doors share (`submit_branch`): refuse the default branch, push through the
bound `SubmissionPort`, and answer the `Submission` report (12.1a).

A CONTRIBUTION OF openDox'S DEFAULT PROFILE, NOT A CORE ARM (decision N-2,
refined by ADV-14; R2Q3 (a)). `opendox.default_profile` declares this module's
`BranchActionRouteExtension` in `ROUTE_EXTENSIONS` and its `BranchActionRoutes`
mixin in `HANDLER_CONTRIBUTIONS`, and `serve.build_server()` composes both in
(`route_extension`). So a host profile that replaces the default carries
neither: its routes, its handler class and its `/capabilities` payload are what
they were. Under openDox's own profile the route behaves the same in every
governance mode (tier 2's CF-1).

THE GATE: THREE CLAUSES, IN ORDER, BEFORE ANY BODY BYTE IS READ (12.4a;
FR-004). The same three, in the same order, as the governed `gate open-pr`
(openXdox's `_handle_gate_action`):

  1. a request off loopback is refused (`loopback_only`). This is the HOSTED
     plane's refusal, and it is the route's own (ADV-04): a push spends the
     invoking user's own git credentials, which a hosted plane never holds;
  2. a request without the `session` capability or a resolved human actor is
     refused (`action_unavailable`). `compute_capabilities` grants `session`
     only to a loopback bind with a real checkout and a resolved actor;
  3. a request that is not the human console is refused (`agent_invocation`):
     the per-serve token, a trusted loopback `Host`, a JSON submission, and no
     foreign `Origin` or `Referer` (`serve._not_the_human_console`).

IT TAKES NO REPOSITORY FROM THE REQUEST (12.4a; F12.2's
`test_submit_route_takes_no_repository_from_the_request`). It submits a branch
of the checkout `build_server` was started on, through that server's own
`submission_factory` binding (`_session_submissions`). A body that carries
anything beside `branch` is refused whole, so no field can name another
checkout, and nothing is pushed.

WHAT IT ANSWERS: the `Submission` object (data-model.md) with 200, or a named
refusal, `{"ok": false, "error": <name>, "message": <sentence>}`. A refusal's
message is either a fixed sentence of this module's, which echoes nothing a
request carried, or the act's own (`submit_branch`, then the port's), which
is redacted by 12.1a's rule and may name the requested `branch` back to the
console that sent it, as JSON the view renders as text. Nothing else a request
carried is echoed. A failure the port did not name is answered with a fixed
sentence, and only the exception's type reaches the server log.

IMPORT WEIGHT. The standard library alone at import, because
`opendox.default_profile` imports this module and must import with nothing
beyond the standard library and `opendox` (`tests/test_default_profile.py`).
`route_extension` and the act are imported where they are used.
"""

from __future__ import annotations

import sys

__all__ = [
    "ACTIONS_SESSION_SUBMIT_ROUTE", "BRANCH_FIELD", "BranchActionRouteExtension",
    "BranchActionRoutes", "requested_branch",
]

#: The submit route (12.4a).
ACTIONS_SESSION_SUBMIT_ROUTE = "/actions/session/submit"

#: The one field a submit request carries.
BRANCH_FIELD = "branch"

#: The route's fixed sentences. None of them echoes anything a request carried.
LOOPBACK_ONLY = (
    "submit is loopback-only: it pushes with the invoking user's own git "
    "credentials, which a hosted plane never holds")
UNAVAILABLE = ("submit is unavailable on this plane (no real checkout or no "
               "resolved human actor)")
NO_PORT = ("no submission port could be built for this checkout, so nothing "
           "is pushed")
NOT_AN_OBJECT = "a submit request is a JSON object naming `branch`"
ONLY_THE_BRANCH = (
    "a submit request carries `branch` alone. The route takes no repository "
    "from the request (12.4a): it submits a branch of the checkout this server "
    "serves")
NO_BRANCH = "a submit request names the branch to submit, as a non-empty string"
FAILED = ("the submission failed for a reason its port did not name; nothing "
          "is reported as submitted. See the server log")


def requested_branch(body) -> tuple[str | None, str | None]:
    """`(branch, None)` for a well-formed submit request, else `(None, why)`.

    Well-formed is a JSON object whose ONE key is `branch`, naming a non-empty
    string. The name itself is the act's to judge (`submit_branch`, then the
    port's own ref-name check), so a malformed name is refused by name there.
    """
    if not isinstance(body, dict):
        return None, NOT_AN_OBJECT
    if set(body) != {BRANCH_FIELD}:
        return None, (ONLY_THE_BRANCH if set(body) - {BRANCH_FIELD}
                      else NO_BRANCH)
    branch = body[BRANCH_FIELD]
    if not isinstance(branch, str) or not branch:
        return None, NO_BRANCH
    return branch, None


class BranchActionRoutes:
    """The handler method the default profile's submit binding names.

    A MIXIN, composed onto the core handler at build time
    (`route_extension.compose_handler`), so it reaches the same gating every
    core route reaches: `self.loopback`, `self.capabilities`, `self.actor`,
    `self._not_the_human_console()` and the server's own
    `_session_submissions()`. It defines that one method and nothing else, so
    it can shadow no core name.
    """

    def _handle_session_submit(self) -> None:
        """`POST /actions/session/submit`: push `branch`, answer where it went."""
        if not self.loopback:
            self._send_json(403, {"ok": False, "error": "loopback_only",
                                  "message": LOOPBACK_ONLY})
            return
        if not self.capabilities.get("actions", {}).get("session") or not self.actor:
            self._send_json(403, {"ok": False, "error": "action_unavailable",
                                  "message": UNAVAILABLE})
            return
        console_refusal = self._not_the_human_console()
        if console_refusal is not None:
            from opendox.serve_wire import AGENT_INVOCATION_REFUSAL

            sys.stderr.write("[actions/session/submit] agent_invocation "
                             f"refused: {console_refusal}\n")
            self._send_json(403, {"ok": False, "error": "agent_invocation",
                                  "message": AGENT_INVOCATION_REFUSAL})
            return
        branch, problem = requested_branch(self._read_json_body())
        if problem is not None:
            self._send_json(400, {"ok": False, "error": "invalid_body",
                                  "message": problem})
            return
        port = self._session_submissions()
        if port is None:
            self._send_json(403, {"ok": False, "error": "action_unavailable",
                                  "message": NO_PORT})
            return
        from opendox import cli_branch_actions
        from opendox.session_pr import NoSubmissionTarget, SubmissionError

        try:
            report = cli_branch_actions.submit_branch(port, branch)
        except NoSubmissionTarget as exc:
            self._send_json(409, {"ok": False, "error": "no_submission_target",
                                  "message": str(exc)})
            return
        except SubmissionError as exc:
            self._send_json(409, {"ok": False, "error": "submission_refused",
                                  "message": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - a host's port, unvetted
            # THE TYPE ALONE reaches the log: the exception's own text is a
            # port's this module cannot vet, and 12.1a keeps a remote URL's
            # credential out of every message.
            sys.stderr.write("[actions/session/submit] the submission port "
                             f"raised {type(exc).__name__}\n")
            self._send_json(500, {"ok": False, "error": "submission_failed",
                                  "message": FAILED})
            return
        self._send_json(200, report)


class BranchActionRouteExtension:
    """The default profile's route contribution: the submit route alone.

    Conforms to `route_extension.RouteExtension` STRUCTURALLY, as every
    contributed extension does. The binding is built when `routes()` is
    called, at wiring time, so importing this module (and the default profile
    that names it) loads nothing beyond the standard library.
    """

    def routes(self) -> tuple:
        import route_extension

        return (route_extension.RouteBinding(
            "POST", ACTIONS_SESSION_SUBMIT_ROUTE, False,
            "_handle_session_submit"),)
