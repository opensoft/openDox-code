"""openDox's OWN branch routes: `POST /actions/session/submit` (plan 038 T015;
#1144 12.4a), and `POST /actions/session/land-nonce` with `POST
/actions/session/land` (plan 038 T016; #1144 12.6a; OQ-12-13), as openxFactory
`specs/038-.../contracts/cli-http-submit-land.md` shapes them.

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
this boundary redacts by 12.1a's rule whoever raised it
(`cli_branch_actions.refusal_text`; the report's `url` and `remote` too) and
which may name the requested `branch` back to the
console that sent it, as JSON the view renders as text. Nothing else a request
carried is echoed. A failure the port did not name is answered with a fixed
sentence, and only the exception's type reaches the server log.

THE LAND ROUTES (plan 038 T016; OQ-12-13). Two steps, both behind the same
three clauses and the console token, and both taking no repository from the
request (12.4a):

  * `land-nonce` takes `{"branch": ...}` and answers `{"nonce", "branch",
    "head"}`: a nonce bound to that branch and its head, single-use, from
    THIS server's `landing_confirm.LandingNonces`, the second of the two
    issuers. It refuses, by name and before any nonce is issued, `main`, a
    branch that does not exist, and a repository where `land` cannot act
    (`cli_branch_actions.landing_refusal`: governed-without-an-instrument, or
    why the governance is `unknown`), so the view never asks a human to
    confirm a landing that cannot happen;
  * `land` takes `{"branch": ..., "nonce": ...}` and redeems the nonce, which
    the first attempt spends, matching or not, and lands through the act both
    doors share (`cli_branch_actions.land_branch`): the `Landed` object under
    `standalone` (the server's `landing_factory`), or the host instrument's
    `Submission` under `governed`, with no merge (R2Q4 (a)).

This module and `opendox.cli_branch_actions` are the two interactive layers
`landing_confirm.INTERACTIVE_LAYERS` names: no other module may call an
issuer. The nonces live on the server's own handler class, so each server
has one store and two servers never share one.

A land refusal answers `{"ok": false, "error": "landing_refused", "code":
<the refusal's code>, "message": <its sentence, redacted>}`; a conflict
answers `"error": "merge_conflict"` with its `paths` and `remedy` (OQ-038-1);
an instrument's refusal answers as `submit`'s does; a failure nobody named
answers a fixed sentence, and only its type reaches the server log.

IMPORT WEIGHT. The standard library alone at import, because
`opendox.default_profile` imports this module and must import with nothing
beyond the standard library and `opendox` (`tests/test_default_profile.py`).
`route_extension` and the act are imported where they are used.
"""

from __future__ import annotations

import sys
import threading

__all__ = [
    "ACTIONS_SESSION_LAND_NONCE_ROUTE", "ACTIONS_SESSION_LAND_ROUTE",
    "ACTIONS_SESSION_SUBMIT_ROUTE", "BRANCH_FIELD", "BranchActionRouteExtension",
    "BranchActionRoutes", "NONCE_FIELD", "requested_branch",
    "requested_landing", "requested_nonce_branch",
]

#: The submit route (12.4a).
ACTIONS_SESSION_SUBMIT_ROUTE = "/actions/session/submit"
#: The land routes (12.6a; OQ-12-13): the nonce, then the landing.
ACTIONS_SESSION_LAND_NONCE_ROUTE = "/actions/session/land-nonce"
ACTIONS_SESSION_LAND_ROUTE = "/actions/session/land"

#: The one field a submit request carries.
BRANCH_FIELD = "branch"
#: The second field a land request carries.
NONCE_FIELD = "nonce"

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

#: The land routes' fixed sentences. None echoes anything a request carried.
LAND_LOOPBACK_ONLY = (
    "land is loopback-only: it merges into the served checkout's `main` for "
    "its local human, which a hosted plane never serves")
LAND_UNAVAILABLE = ("land is unavailable on this plane (no real checkout or no "
                    "resolved human actor)")
LAND_NOT_AN_OBJECT = "a land request is a JSON object naming `branch` and `nonce`"
LAND_ONLY_THE_BRANCH = (
    "a land-nonce request carries `branch` alone. The route takes no "
    "repository from the request (12.4a): it lands a branch of the checkout "
    "this server serves")
LAND_ONLY_TWO_FIELDS = (
    "a land request carries `branch` and `nonce` alone. The route takes no "
    "repository from the request (12.4a): it lands a branch of the checkout "
    "this server serves")
LAND_NO_BRANCH = "a land request names the branch to land, as a non-empty string"
LAND_NO_NONCE = ("a land request carries the nonce `land-nonce` issued for its "
                 "branch, as a non-empty string")
LAND_FAILED = ("the landing failed for a reason it did not name; nothing is "
               "reported as landed. See the server log")

#: One lock for the lazy creation of each server's nonce store.
_NONCES_LOCK = threading.Lock()


def requested_landing(body) -> tuple[str | None, str | None, str | None]:
    """`(branch, nonce, None)` for a well-formed land request, else `(None,
    None, why)`: a JSON object whose keys are exactly `branch` and `nonce`,
    each a non-empty string."""
    if not isinstance(body, dict):
        return None, None, LAND_NOT_AN_OBJECT
    if set(body) - {BRANCH_FIELD, NONCE_FIELD}:
        return None, None, LAND_ONLY_TWO_FIELDS
    branch, nonce = body.get(BRANCH_FIELD), body.get(NONCE_FIELD)
    if not isinstance(branch, str) or not branch:
        return None, None, LAND_NO_BRANCH
    if not isinstance(nonce, str) or not nonce:
        return None, None, LAND_NO_NONCE
    return branch, nonce, None


def requested_nonce_branch(body) -> tuple[str | None, str | None]:
    """`(branch, None)` for a well-formed land-nonce request, else `(None,
    why)`: a JSON object whose ONE key is `branch`, a non-empty string."""
    if not isinstance(body, dict):
        return None, LAND_NOT_AN_OBJECT
    if set(body) - {BRANCH_FIELD}:
        return None, LAND_ONLY_THE_BRANCH
    branch = body.get(BRANCH_FIELD)
    if not isinstance(branch, str) or not branch:
        return None, LAND_NO_BRANCH
    return branch, None


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

    def _branch_action_refused_at_the_gate(self, route: str, loopback_only: str,
                                           unavailable: str) -> bool:
        """12.4a's THREE CLAUSES, in order, before any body byte is read: off
        loopback, no `session` capability or no resolved actor, not the human
        console. True, with the refusal sent, where one clause refuses."""
        if not self.loopback:
            self._send_json(403, {"ok": False, "error": "loopback_only",
                                  "message": loopback_only})
            return True
        if not self.capabilities.get("actions", {}).get("session") or not self.actor:
            self._send_json(403, {"ok": False, "error": "action_unavailable",
                                  "message": unavailable})
            return True
        console_refusal = self._not_the_human_console()
        if console_refusal is not None:
            from opendox.serve_wire import AGENT_INVOCATION_REFUSAL

            sys.stderr.write(f"[{route.lstrip('/')}] agent_invocation "
                             f"refused: {console_refusal}\n")
            self._send_json(403, {"ok": False, "error": "agent_invocation",
                                  "message": AGENT_INVOCATION_REFUSAL})
            return True
        return False

    def _handle_session_submit(self) -> None:
        """`POST /actions/session/submit`: push `branch`, answer where it went."""
        if self._branch_action_refused_at_the_gate(
                ACTIONS_SESSION_SUBMIT_ROUTE, LOOPBACK_ONLY, UNAVAILABLE):
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
                                  "message": cli_branch_actions.refusal_text(exc)})
            return
        except SubmissionError as exc:
            self._send_json(409, {"ok": False, "error": "submission_refused",
                                  "message": cli_branch_actions.refusal_text(exc)})
            return
        # A host's port, unvetted: its type is all this route logs.
        except Exception as exc:  # noqa: BLE001
            # THE TYPE ALONE reaches the log: the exception's own text is a
            # port's this module cannot vet, and 12.1a keeps a remote URL's
            # credential out of every message.
            sys.stderr.write("[actions/session/submit] the submission port "
                             f"raised {type(exc).__name__}\n")
            self._send_json(500, {"ok": False, "error": "submission_failed",
                                  "message": FAILED})
            return
        self._send_json(200, report)

    # ---- land (plan 038 T016; #1144 12.6a; OQ-12-13) ----

    def _branch_action_nonces(self):
        """THIS server's `LandingNonces`, the view's issuer: one per bound
        handler class, which `build_server` makes once per server, created on
        first use under a lock."""
        bound = type(self)
        with _NONCES_LOCK:
            nonces = bound.__dict__.get("_branch_action_nonce_store")
            if nonces is None:
                from opendox.landing_confirm import LandingNonces

                nonces = LandingNonces()
                bound._branch_action_nonce_store = nonces
        return nonces

    def _send_landing_refusal(self, exc) -> None:
        """A NAMED landing refusal, its sentence redacted (12.1a): a conflict
        with its paths and remedy, or any other with its code."""
        from opendox import cli_branch_actions
        from opendox.landing import MergeConflict
        from opendox.landing_confirm import ConfirmationRefused

        message = cli_branch_actions.redacted_text(str(exc))
        if isinstance(exc, MergeConflict):
            self._send_json(409, {
                "ok": False, "error": "merge_conflict", "code": exc.code,
                "paths": list(exc.paths), "remedy": exc.remedy,
                "message": message})
            return
        # A refused NONCE is named as the lander names a refused confirmation.
        code = (f"confirmation:{exc.code}" if isinstance(exc, ConfirmationRefused)
                else exc.code)
        self._send_json(409, {"ok": False, "error": "landing_refused",
                              "code": code, "message": message})

    def _handle_session_land_nonce(self) -> None:
        """`POST /actions/session/land-nonce`: a single-use nonce bound to
        `branch` and its head, where `land` can act on it."""
        if self._branch_action_refused_at_the_gate(
                ACTIONS_SESSION_LAND_NONCE_ROUTE, LAND_LOOPBACK_ONLY,
                LAND_UNAVAILABLE):
            return
        branch, problem = requested_nonce_branch(self._read_json_body())
        if problem is not None:
            self._send_json(400, {"ok": False, "error": "invalid_body",
                                  "message": problem})
            return
        from opendox import cli_branch_actions
        from opendox.landing import LandingRefused

        try:
            head = cli_branch_actions.branch_head(self.checkout_root, branch)
            refused = cli_branch_actions.landing_refusal(
                self._session_lander(), self.checkout_root)
            if refused is not None:
                raise refused
        except LandingRefused as exc:
            self._send_landing_refusal(exc)
            return
        # A read nobody named (git, or a host's profile): its TYPE alone
        # reaches the log, as the land route logs one.
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("[actions/session/land-nonce] the reading raised "
                             f"{type(exc).__name__}\n")
            self._send_json(500, {"ok": False, "error": "landing_failed",
                                  "message": LAND_FAILED})
            return
        nonce = self._branch_action_nonces().issue_nonce(branch, head)
        self._send_json(200, {"nonce": nonce, "branch": branch, "head": head})

    def _handle_session_land(self) -> None:
        """`POST /actions/session/land`: redeem the nonce, land, and answer
        what landed (or where a governed landing was submitted)."""
        if self._branch_action_refused_at_the_gate(
                ACTIONS_SESSION_LAND_ROUTE, LAND_LOOPBACK_ONLY, LAND_UNAVAILABLE):
            return
        branch, nonce, problem = requested_landing(self._read_json_body())
        if problem is not None:
            self._send_json(400, {"ok": False, "error": "invalid_body",
                                  "message": problem})
            return
        from opendox import cli_branch_actions
        from opendox.landing import DEFAULT_BRANCH, LandingRefused
        from opendox.landing_confirm import ConfirmationRefused
        from opendox.session_pr import NoSubmissionTarget, SubmissionError

        try:
            # `main` first, before the nonce store is asked (R2Q5 (a))
            if branch == DEFAULT_BRANCH:
                raise cli_branch_actions.main_refused()
            confirmation = self._branch_action_nonces().confirm_nonce(
                branch, nonce)
            answer = cli_branch_actions.land_branch(
                self._session_lander(), self.checkout_root, branch,
                confirmation)
        except (LandingRefused, ConfirmationRefused) as exc:
            self._send_landing_refusal(exc)
            return
        except NoSubmissionTarget as exc:
            self._send_json(409, {"ok": False, "error": "no_submission_target",
                                  "message": cli_branch_actions.refusal_text(exc)})
            return
        except SubmissionError as exc:
            self._send_json(409, {"ok": False, "error": "submission_refused",
                                  "message": cli_branch_actions.refusal_text(exc)})
            return
        # A host's instrument, or anything else unnamed: its TYPE alone
        # reaches the log, since its text may carry a remote URL's credential.
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write("[actions/session/land] the landing raised "
                             f"{type(exc).__name__}\n")
            self._send_json(500, {"ok": False, "error": "landing_failed",
                                  "message": LAND_FAILED})
            return
        self._send_json(200, answer)


class BranchActionRouteExtension:
    """The default profile's route contribution: the submit route, and the
    two land routes (plan 038 T016).

    Conforms to `route_extension.RouteExtension` STRUCTURALLY, as every
    contributed extension does. The binding is built when `routes()` is
    called, at wiring time, so importing this module (and the default profile
    that names it) loads nothing beyond the standard library.
    """

    def routes(self) -> tuple:
        import route_extension

        return (route_extension.RouteBinding(
                    "POST", ACTIONS_SESSION_SUBMIT_ROUTE, False,
                    "_handle_session_submit"),
                route_extension.RouteBinding(
                    "POST", ACTIONS_SESSION_LAND_NONCE_ROUTE, False,
                    "_handle_session_land_nonce"),
                route_extension.RouteBinding(
                    "POST", ACTIONS_SESSION_LAND_ROUTE, False,
                    "_handle_session_land"))
