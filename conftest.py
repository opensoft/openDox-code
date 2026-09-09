"""Put this leg's ``src/`` layout on ``sys.path`` for pytest.

Created by the OQ-O scaffold-levelling pass (openxFactory#656) before any
carved content arrives; ``pyproject.toml`` records why the import root has to
exist at all. That file's ``[tool.pytest.ini_options] pythonpath = ["src"]``
does this same job whenever pytest reads that table; this module is the belt
to that pair of braces — it also runs under a runner invoked against a
different ini, and it is the root of the conftest chain that the suites
arriving under ``tests/`` are collected beneath.

A CREATED file: no manifest row (RULED OQ-C).
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"

if SRC.is_dir():
    _src = str(SRC)
    if _src not in sys.path:
        sys.path.insert(0, _src)
