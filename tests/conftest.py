"""Suite-wide test configuration (Day 5).

* the `llm` marker: tests that call a live model. They are skipped unless ANTHROPIC_API_KEY is set (opt-in, D5-12). CI never sets it.
* tests/fixtures/llm is put on sys.path so the stub classifier and the replay clients can be imported by name.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "llm"))


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return
    skip = pytest.mark.skip(reason="live LLM test: set ANTHROPIC_API_KEY to opt in (never in CI)")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)
