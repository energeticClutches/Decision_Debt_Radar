"""Fixtures for the Day-7 evaluation suite.

The database fixtures (`sa_url`, `engine`, `session`, `seed`) are the ones of tests/backend/conftest.py: every test runs inside an outer
transaction that is rolled back, so the evaluation NEVER changes the demo database (brief section 0).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_TESTS = HERE.parent / "backend"
for p in (str(HERE), str(BACKEND_TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location("ddr_backend_test_conftest", BACKEND_TESTS / "conftest.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

sa_url = _mod.sa_url
engine = _mod.engine
session = _mod.session
seed = _mod.seed
Seed = _mod.Seed
