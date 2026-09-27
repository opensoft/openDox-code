"""§ 5.4 clause (d)'s collection pin, held to the outcomes it promises.

`Pin the triple` is the required check's last step: it reads the JUnit report
the job writes and refuses a run that collected fewer cases than the floors,
that skipped a different number than the pinned one, that failed or errored at
all, or whose report did not appear. It is a shell script inside a workflow
file — the one kind of code in this repository that nothing executes until CI
does. openDox-code#29 added it and registered exactly that as its residue.

ONE REPORT SINCE plan 034 T036. The job used to run three pytest steps over
three file lists and sum three reports; it now runs the whole suite as one
invocation (#1144 requirement 9), so the step reads one. A missing report is
still a refusal, and now the only one that fires: with no report there is no
triple to compare, so the step names the file and stops.

SO THE STEP'S OWN SCRIPT IS WHAT RUNS HERE, extracted from the workflow rather
than restated. A copy of the script in a test is a test of the copy: the pin
this suite must protect is the one the runner will execute, and the two drift
the first time somebody edits one of them. Each case writes reports into its own
directory and runs the step there, with the step's OWN `env:` block — so the
numbers under test are the pinned numbers, and a re-pin does not need a matching
edit here.

The six cases are the five outcomes plus the one join, each isolated so that
exactly one refusal can fire:

  * the pinned state passes;
  * a report that did not appear is a refusal that NAMES the file, and it is
    the only refusal, rather than a zero read from nothing and failed against
    every floor;
  * one skip more is a refusal, with the floors still met;
  * one failure is a refusal, with both floors and the skip count still met
    (openDox-code#33, Copilot review comment 5738550542, finding R4: the step
    has six refusals and three had cases before this one; `FAILURES != 0` and
    `ERRORS != 0` did not);
  * one error is a refusal, on the same ground;
  * the report the step reads is the report the pytest step writes, so a
    rename of either cannot leave the pin reading a file nothing produces.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/validate.yml"

needs_a_shell = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="the step is a bash script that runs python3")


def _steps() -> list[dict]:
    """The required job's steps, in order."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["validate"]["steps"]


def _step() -> dict:
    """The `Pin the triple` step, with its `run` script and its `env` pins."""
    for step in _steps():
        if step.get("name") == "Pin the triple":
            return step
    raise AssertionError(
        "the required `validate` job has no `Pin the triple` step; clause (d)'s"
        " collection pin is what this file exists to hold")


def _report_name() -> str:
    """The one report the step reads, read off its own `REPORTS` line."""
    match = re.search(r"REPORTS = \(([^)]*)\)", _step()["run"])
    assert match, "the step no longer declares the reports it reads"
    names = re.findall(r'"([^"]+)"', match.group(1))
    assert len(names) == 1, (
        f"the step reads {names}; the whole suite is one invocation, so it "
        "writes one report")
    return names[0]


def _pins() -> tuple[int, int, int]:
    """(the smallest total that satisfies both floors, that total's skips,
    the pinned skip count) — read from the step, never restated."""
    env = _step()["env"]
    floor_selected = int(env["MIN_SELECTED"])
    floor_passed = int(env["MIN_PASSED"])
    skipped = int(env["EXPECT_SKIPPED"])
    return max(floor_selected, floor_passed + skipped), skipped, skipped


def _report(path: Path, tests: int, skipped: int, failures: int = 0,
            errors: int = 0) -> None:
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<testsuites><testsuite '
        f'name="pytest" errors="{errors}" failures="{failures}" '
        f'skipped="{skipped}" tests="{tests}" time="0.1"/></testsuites>\n',
        encoding="utf-8")


def _run(where: Path,
         reports: dict[str, tuple[int, int] | tuple[int, int, int, int]],
         ) -> subprocess.CompletedProcess[str]:
    """Write one report per entry, `(tests, skipped)` or `(tests, skipped,
    failures, errors)` — the shorter form is the common case and leaves
    failures and errors at `_report`'s own zero default."""
    step = _step()
    for name, spec in reports.items():
        _report(where / name, *spec)
    return subprocess.run(
        ("bash", "-c", step["run"]), cwd=where, capture_output=True, text=True,
        # A hermetic environment plus the step's own pins: an inherited
        # MISSING/SELECTED would be read by the `. ./triple.env` line below it.
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
             **{k: str(v) for k, v in step["env"].items()}})


@needs_a_shell
def test_the_pinned_state_passes() -> None:
    """The floors are floors and the skip count is exact, so the smallest state
    that meets all three is a pass — otherwise the pin refuses its own runs."""
    total, skipped, _ = _pins()
    with TemporaryDirectory() as directory:
        completed = _run(Path(directory), {_report_name(): (total, skipped)})
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert f"selected={total}" in completed.stdout, completed.stdout


@needs_a_shell
def test_a_report_that_did_not_appear_is_a_refusal_naming_the_file() -> None:
    """A pytest step that failed to write its report has taken every test out
    of the count, and a zero read from nothing is not a smaller run but a blind
    one. So the refusal names the file, and it is the ONLY refusal: the step
    stops there instead of failing a triple it never read against every floor.
    The stray report written here, under another name, is what a rename of the
    pytest step's `--junitxml` would leave behind."""
    total, skipped, _ = _pins()
    with TemporaryDirectory() as directory:
        completed = _run(Path(directory), {
            "pytest-report-renamed.xml": (total, skipped)})
    assert completed.returncode == 1, completed.stdout
    assert _report_name() in completed.stdout, completed.stdout
    assert completed.stdout.count("::error::") == 1, (
        "the missing report must be the ONLY refusal in this case, or the case"
        f" is not measuring it:\n{completed.stdout}")


@needs_a_shell
def test_one_skip_more_than_pinned_is_a_refusal() -> None:
    """The exact number is the load-bearing one. Here the extra case ships
    already-skipped, so both floors stay met and only the skip count moves —
    which is the shape the pin was written to catch."""
    total, skipped, pinned = _pins()
    with TemporaryDirectory() as directory:
        completed = _run(Path(directory), {
            _report_name(): (total + 1, skipped + 1)})
    assert completed.returncode == 1, completed.stdout
    assert f"skipped {pinned + 1}, pinned exactly {pinned}" in completed.stdout, completed.stdout
    assert completed.stdout.count("::error::") == 1, (
        "the moved skip count must be the ONLY refusal in this case:\n"
        f"{completed.stdout}")


@needs_a_shell
def test_a_failure_is_a_refusal_with_both_floors_and_the_skip_count_met() -> None:
    """Clause (d) requires zero failures on its own, not as a side effect of
    the floors: a suite that collected enough, passed enough and skipped
    exactly the pinned number can still have FAILED one test, and that is not
    a state this pin may wave through. `total + 1` is the same one-more
    adjustment `test_one_skip_more_than_pinned_is_a_refusal` uses, here
    covering the one test this case moves from passed to failed rather than
    from collected to skipped, so SELECTED and PASSED both still clear their
    floors and only FAILURES moves (openDox-code#33 Copilot review comment
    5738550542, finding R4)."""
    total, skipped, pinned = _pins()
    with TemporaryDirectory() as directory:
        completed = _run(Path(directory), {
            _report_name(): (total + 1, skipped, 1, 0)})
    assert completed.returncode == 1, completed.stdout
    assert "failures 1, clause (d) requires zero" in completed.stdout, completed.stdout
    assert completed.stdout.count("::error::") == 1, (
        "the failure must be the ONLY refusal in this case:\n"
        f"{completed.stdout}")


@needs_a_shell
def test_an_error_is_a_refusal_with_both_floors_and_the_skip_count_met() -> None:
    """Clause (d)'s other half: a collection ERROR is a distinct JUnit outcome
    from a failure, and this pin must catch it exactly as certainly. Same
    adjustment as the failure case above, so only ERRORS moves."""
    total, skipped, pinned = _pins()
    with TemporaryDirectory() as directory:
        completed = _run(Path(directory), {
            _report_name(): (total + 1, skipped, 0, 1)})
    assert completed.returncode == 1, completed.stdout
    assert "errors 1, clause (d) requires zero" in completed.stdout, completed.stdout
    assert completed.stdout.count("::error::") == 1, (
        "the error must be the ONLY refusal in this case:\n"
        f"{completed.stdout}")


def test_the_pin_reads_the_report_the_pytest_step_writes() -> None:
    """The join between the two steps, which neither step can check alone.

    The pytest step names its report with `--junitxml=` and this step names the
    one it reads in `REPORTS`. If either is renamed and the other is not, the
    pin reads a file nothing writes. The refusal above would then fire on
    every run, so the check would be red for a typo rather than for a
    regression. So the two names are held equal here, read off both steps."""
    written = [match
               for step in _steps()
               for match in re.findall(r"--junitxml=(\S+)", step.get("run", ""))]
    assert written == [_report_name()], (
        f"the pytest step writes {written} and the pin reads "
        f"{[_report_name()]}; the whole suite is one invocation and one report")
