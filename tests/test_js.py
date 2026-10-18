"""Run the trainer's JavaScript tests through pytest.

The parsers and scoring rules live in static/trainer/js, so the suite that
pins them down is JavaScript too. Node's built-in test runner needs no
packages; skipping when node is absent keeps a Python-only checkout green.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_javascript_suite() -> None:
    # Node 22's test runner does not accept a directory argument, and older
    # Node treats .js as CommonJS. The explicit file list plus the root
    # package.json ("type": "module") keeps this working across versions.
    files = sorted(str(path) for path in (ROOT / "tests" / "js").glob("*.test.js"))
    proc = subprocess.run(
        [NODE, "--test", *files],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
