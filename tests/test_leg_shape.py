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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
