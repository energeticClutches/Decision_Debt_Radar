"""Write prompts/prompt_hashes.json for ONE prompt version directory (a released version is never rehashed).

    python scripts/hash_prompts.py v0.1

Refuses to overwrite an existing entry for that version unless --force is given (a released prompt is immutable).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    version, force = argv[0], "--force" in argv
    registry_path = PROMPTS / "prompt_hashes.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    if version in registry and not force:
        print(f"{version} is already registered: released prompts are immutable. Create a new version directory instead.")
        return 1
    entries = {}
    for path in sorted((PROMPTS / version).glob("*.md")):
        entries[path.stem] = {"file": f"{version}/{path.name}", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    registry[version] = entries
    registry_path.write_bytes((json.dumps(registry, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
