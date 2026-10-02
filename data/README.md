# data/

> **All FitConnect data is SYNTHETIC.** FitConnect is a fictional company. Nothing here is real-world data and it must never be presented as such.

```
data/
├── generator/   seeded generator (config.py, generate.py, feedback.py, manifest.py, __main__.py)
├── manifest/    fitconnect_manifest.json (ground truth + 33 validation checks), fitconnect_digests.json
└── generated/   CSV output (git-ignored): users, events, subscriptions, feedback, ...
```

```bash
PYTHONPATH=. python -m data.generator --out data/generated [--users 50000] [--seed 20260401]
```

- **Fixed seed (20260401)** and deterministic ordering: the same seed and scale always produce byte-identical files and manifest.
- **Scale is configurable** (`--users`). Default is 50,000 users, about 2.1 million events, 12 months (2025-10-01 to 2026-09-30).
- The manifest documents the four scenarios, the seeded defects (DEF-ONB-001, DEF-ONB-002 with detection signals) and 33 SQL checks. `python -m database.seed.validate` runs them against the loaded database.
- Ground-truth feedback labels are loaded into `fc_.feedback_ground_truth` for later evaluation. They are not exposed through the analytical views.
