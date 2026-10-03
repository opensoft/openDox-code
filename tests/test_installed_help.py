"""The installed `opendox --help` names openDox and nothing else (plan 034
T084; found by T099's PyPI writer).

`opendox --help` is the first thing a published install prints. It used to
print `usage: ideation-dashboard` and `cli.py`'s module docstring, which is
openxFactory's pre-carve history: "validates it against the pinned openxFactory
validator", `python3 -m ideation_dashboard.cli`, `scripts/ideation_dashboard/`.
On PyPI that text would be the product's own description of itself.

The case runs the INSTALLED console script, the file `pip` wrote into the
interpreter's scripts directory from `pyproject.toml`'s `[project.scripts]`,
as a user runs it: not `opendox.cli.main()` in process, which would pass
whatever the entry point string said. The suite always runs against an
installed package (`validate.yml` installs it with `pip install -e`), so a
missing script fails the case rather than skipping it.

A CREATED FILE: no carve-manifest row (RULED OQ-C).
"""

from __future__ import annotations

import importlib.metadata
import os
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

#: Words that name the governed host or the pre-carve package, none of which
#: belongs in the neutral product's own help.
FOREIGN = re.compile(r"openxfactory|xfactory|ideation[-_ ]dashboard|"
                     r"ideation_dashboard|split-opendox|\bscripts/",
                     re.IGNORECASE)


def _console_script() -> Path:
    """The installed `opendox` script, after checking that the entry point
    `pip` wrote it from is `opendox.cli:main`."""
    points = [ep for ep in importlib.metadata.entry_points(group="console_scripts")
              if ep.name == "opendox"]
    assert [ep.value for ep in points] == ["opendox.cli:main"], points
    name = "opendox.exe" if os.name == "nt" else "opendox"
    for directory in (Path(sysconfig.get_path("scripts")),
                      Path(sys.executable).parent):
        if (directory / name).is_file():
            return directory / name
    raise AssertionError(
        f"no installed `{name}` script beside {sys.executable}: the suite runs "
        "against an installed package (`pip install -e .`)")


def _help() -> str:
    done = subprocess.run([str(_console_script()), "--help"],
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, "COLUMNS": "100"})
    assert done.returncode == 0, done.stderr
    assert done.stderr == "", done.stderr
    return done.stdout


def test_the_installed_help_names_the_installed_command() -> None:
    out = _help()
    assert out.startswith("usage: opendox "), out.splitlines()[0]
    assert "openDox" in out, out


def test_the_installed_help_names_no_host_and_no_pre_carve_package() -> None:
    out = _help()
    found = sorted({match.group(0) for match in FOREIGN.finditer(out)})
    assert found == [], (
        f"`opendox --help` names {found}, which is not openDox's own "
        f"vocabulary:\n{out}")


def test_the_parser_carries_the_neutral_name_and_words() -> None:
    """The same, in process, so a failure names the attribute that moved."""
    from opendox import cli
    parser = cli.build_parser()
    assert parser.prog == cli.PROG == "opendox"
    assert parser.description == cli.PARSER_DESCRIPTION
    assert parser.epilog == cli.PARSER_EPILOG
    for text in (cli.PARSER_DESCRIPTION, cli.PARSER_EPILOG):
        assert not FOREIGN.search(text), text


def test_the_servers_own_help_names_openDox_only() -> None:
    """`python -m opendox.serve --help`, the server entry point's help, under
    the same rule (adversarial review 2): it printed
    `usage: ideation-dashboard-serve` and the module's pre-carve docstring."""
    from opendox import serve
    done = subprocess.run([sys.executable, "-m", "opendox.serve", "--help"],
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, "COLUMNS": "100"})
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith(f"usage: {serve.SERVE_PROG} "), \
        done.stdout.splitlines()[0]
    found = sorted({m.group(0) for m in FOREIGN.finditer(done.stdout)})
    assert found == [], f"the server's help names {found}:\n{done.stdout}"
