"""Make the research scripts importable from the tests.

`scripts/` is not a package and is not installed: it ships with the repo
rather than with the wheel, and its modules import each other by plain
name. Putting the directory on `sys.path` is what lets a test import
`interpreters` the same way `dating.py` does.
"""

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

sys.path.insert(0, str(SCRIPTS))
