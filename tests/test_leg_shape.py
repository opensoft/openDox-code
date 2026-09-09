"""Bootstrap-posture shape tests for the openDox-code leg.

Asserts the files a public, day-one-postured repository must carry — see
openxFactory openspec/changes/split-opendox-two-layer-product/tasks.md
§ 1.3-1.5.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".gitignore",
    "LICENSE",
    "SECURITY.md",
    ".github/CODEOWNERS",
]


@pytest.mark.parametrize("relpath", REQUIRED_FILES)
def test_required_file_exists(relpath: str) -> None:
    path = ROOT / relpath
    assert path.is_file(), f"expected {relpath} to exist at {path}"


def test_license_is_apache() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text


def test_role_directory_exists() -> None:
    # This is the code leg: its role directory is src/.
    assert (ROOT / "src").is_dir()


def test_branch_protection_evidence_exists() -> None:
    # tasks.md § 1.5's evidence line: a ruleset is a repository SETTING, so
    # the only thing a tree can assert is that the evidence file naming it is
    # present. Levelled across all six repositories by the OQ-O pass
    # (openxFactory#656).
    assert (ROOT / "docs" / "branch-protection.md").is_file(), (
        "docs/branch-protection.md is missing: tasks.md § 1.5 requires this "
        "repository to carry the evidence file naming its `validate` ruleset"
    )


def test_import_root_exists() -> None:
    # The import root created by the OQ-O levelling pass (openxFactory#656).
    # A `src/` layout needs one, or `import opendox` does not resolve under
    # `python -m pytest` run from the repository root once the carve lands,
    # and the required `validate` check goes red for a reason that has
    # nothing to do with the carve.
    assert (ROOT / "pyproject.toml").is_file(), (
        "pyproject.toml is missing: without the import root, a src/ layout does "
        "not resolve under `python -m pytest` from the repository root"
    )
    assert (ROOT / "conftest.py").is_file(), (
        "conftest.py is missing: the repository-root conftest is what puts src/ "
        "on sys.path for a runner that does not read pyproject.toml"
    )


def test_src_is_on_sys_path() -> None:
    # Proves the root `conftest.py` (or `pyproject.toml`'s pytest
    # `pythonpath` setting) actually RAN and put `src/` on sys.path, rather
    # than merely existing.
    assert str(ROOT / "src") in sys.path, (
        f"{ROOT / 'src'} is not on sys.path: the import root exists on disk but "
        "did not take effect, so carved modules will not import"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
