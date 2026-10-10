"""scripts/demo_check.py is a read-only preflight (docs/day-7-implementation-brief.md section 6)."""

from __future__ import annotations

import re
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[2] / "scripts" / "demo_check.py").read_text(encoding="utf-8")


def test_the_preflight_never_writes():
    code = re.sub(r'""".*?"""', "", SOURCE, flags=re.S)
    assert not re.search(r"\b(insert|update|delete|truncate|drop|alter|create)\s+(into|table|from|index)\b", code, re.I)
    assert "commit" not in code and "session.add" not in code and "subprocess.run([\"docker\", \"compose\", \"up\"" not in code


def test_every_check_names_the_exact_fix_command():
    for fix in ("FIX_DB", "FIX_MIGRATE", "FIX_SEED", "FIX_DEMO", "FIX_API", "FIX_WEB"):
        assert re.search(rf"^{fix} = ", SOURCE, re.M), fix
    assert "127.0.0.1" in SOURCE and "http://localhost" not in SOURCE
