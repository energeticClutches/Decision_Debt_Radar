"""CLI: python -m data.generator --out data/generated [--users N] [--seed S]

Writes SYNTHETIC FitConnect CSVs, the defect/pattern manifest and a SHA-256 digest file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from . import config as C
from .generate import generate
from .manifest import build_manifest

# csv name -> (fc_ table, ordered columns)
TABLE_SPECS: dict[str, list[str]] = {
    "users": ["user_id", "signup_ts", "platform", "country", "acquisition_channel", "engagement_style",
              "prior_engagement_tier", "is_synthetic"],
    "events": ["event_id", "user_id", "event_ts", "event_name", "platform", "app_version", "is_synthetic"],
    "subscriptions": ["subscription_id", "user_id", "plan", "price_monthly", "start_date", "end_date",
                      "status", "is_synthetic"],
    "feedback": ["feedback_id", "user_id", "created_at", "source", "rating", "body", "is_synthetic"],
    "feedback_ground_truth": ["feedback_id", "scenario_key", "theme", "sentiment", "is_synthetic"],
    "experiment_assignments": ["experiment_key", "user_id", "variant", "assigned_at", "is_synthetic"],
    "experiment_outcomes": ["experiment_key", "user_id", "metric_name", "value", "is_synthetic"],
    "ai_inference_costs": ["user_id", "cost_month", "sessions", "cost_usd", "is_synthetic"],
    "pricing_model_inputs": ["input_key", "value", "unit", "is_assumption", "source_note", "is_synthetic"],
}
# load order respects foreign keys
LOAD_ORDER = ["users", "events", "subscriptions", "feedback", "feedback_ground_truth",
              "experiment_assignments", "experiment_outcomes", "ai_inference_costs", "pricing_model_inputs"]


def write_dataset(cfg: C.GenConfig, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tables, meta = generate(cfg)
    manifest = build_manifest(cfg, meta)
    digests = {}
    for name in LOAD_ORDER:
        df = tables[name][TABLE_SPECS[name]]
        path = out / f"{name}.csv"
        df.to_csv(path, index=False, lineterminator="\n")
        digests[f"{name}.csv"] = hashlib.sha256(path.read_bytes()).hexdigest()
        meta.setdefault("row_counts", {})[name] = int(len(df))
    manifest_path = out / "manifest.json"
    manifest["row_counts"] = meta["row_counts"]
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    digests["manifest.json"] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (out / "digests.json").write_text(json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"meta": meta, "digests": digests}


def main() -> None:
    p = argparse.ArgumentParser(description="Generate SYNTHETIC FitConnect data (fictional company).")
    p.add_argument("--out", default="data/generated")
    p.add_argument("--users", type=int, default=C.GenConfig.users)
    p.add_argument("--seed", type=int, default=C.DEFAULT_SEED)
    a = p.parse_args()
    t = time.time()
    res = write_dataset(C.GenConfig(seed=a.seed, users=a.users), Path(a.out))
    print(json.dumps({"seconds": round(time.time() - t, 1), "meta": res["meta"]}, indent=2))


if __name__ == "__main__":
    main()
