"""Versioned prompt files with content-hash checks (docs/day-5-implementation-brief.md section 3).

prompts/<version>/<name>.md are hashed (SHA-256 of the bytes) in prompts/prompt_hashes.json. Loading raises ParamsError when the
file is missing, the version or prompt is not registered, the hash differs (a released prompt is immutable: a change is a new
version directory) or the first line does not declare the prompt id and version. Same discipline as the parameter files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.domain.errors import ParamsError

PROMPTS_DIR = Path(os.environ.get("DDR_PROMPTS_DIR") or Path(__file__).resolve().parents[3] / "prompts")
PROMPT_IDS = ("classify", "synthesize", "review")
_HEADER = re.compile(r"^<!--\s*prompt:\s*([a-z_]+)\s+(v[0-9][0-9.]*)\s*-->\s*$")


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    text: str
    sha256: str


def load_prompt(prompt_id: str, version: str | None = None, *, prompts_dir: Path | None = None) -> Prompt:
    if version is None:
        from app.core.config import get_settings
        version = get_settings().prompt_version
    base = Path(prompts_dir) if prompts_dir else PROMPTS_DIR
    try:
        registry = json.loads((base / "prompt_hashes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ParamsError(f"prompt hash registry unreadable: {exc}") from exc
    entry = (registry.get(version) or {}).get(prompt_id)
    if not entry or "sha256" not in entry:
        raise ParamsError(f"prompt {prompt_id} {version} is not registered in prompt_hashes.json")
    path = base / str(entry.get("file") or f"{version}/{prompt_id}.md")
    if not path.is_file():
        raise ParamsError(f"prompt file not found: {path.name}")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != entry["sha256"]:
        raise ParamsError(f"prompt file {path.name} does not match its registered hash (expected {entry['sha256'][:12]}..., "
                          f"got {actual[:12]}...). Released prompts are immutable: create a new version instead.")
    text = data.decode("utf-8")
    first = text.split("\n", 1)[0].strip()
    m = _HEADER.match(first)
    if m is None or m.group(1) != prompt_id or m.group(2) != version:
        raise ParamsError(f"prompt file {path.name}: the first line must declare '<!-- prompt: {prompt_id} {version} -->'")
    return Prompt(id=prompt_id, version=version, text=text, sha256=actual)
