# Demo script: the 5-minute path

> **Synthetic data.** FitConnect is a fictional company. Everything on screen comes from the deterministic engines and from *replayed fixtures* ("Replayed demo fixture, not live model output"). DDI is an evidence-risk heuristic, not a measure of decision quality.

**Setup (before the call):** `scripts/demo_check.py` shows all PASS; the servers run on 127.0.0.1:8000 and :3000; the demo state is fresh (`scripts/demo_prepare.py --reset`). Sign in as the Product Manager persona (the role switcher is "Demo identity only: not authentication"). Read the numbers off the screen; do not quote them from memory.

## The idea in one sentence (15 s)
"This is an AI deliberately constrained from making the decision. It scores how well the evidence supports a decision, shows exactly why, says what evidence to gather next, and a person records the decision."

## 1. Portfolio (20 s)
- Four decisions, one headline each: a DDI with its band, and "INSUFFICIENT EVIDENCE" for Onboarding. Point at the "Synthetic data" badge and the replay chip.
- Say: higher DDI means more evidence debt. It is not the probability that the decision is wrong.

## 2. AI Coach (about 2 minutes, the main story)
1. **Overview.** One headline, one next action, the status strip.
2. **Assessment tab, "Why this score?"** Seven dimensions and two penalties, each input marked Observed or Defaulted, then the support, the penalty multiplier, the cap and the displayed value. Talking point: the score is code; no model touched it, and the browser only displays stored values.
3. **Evidence tab.** The behavioral comparison is observational; the holdout experiment failed its sample-ratio check (30% against 50% planned). The three customer items arrived as *proposed* and entered the score only after a person approved them (the BA persona did this during preparation).
4. **Review tab.** A causal overclaim was reclassified to associative by the validators and flagged blocking by the (replayed) reviewer, so the verdict is needs rework and Validate is disabled until a person overrides with a written reason. Talking point: the verdict is derived by code from the findings.
5. **Brief.** After validation, a Validated Decision Brief with a traceability matrix: every sentence resolves to a claim, every claim to evidence and a source. No recommendation anywhere.

## 3. Onboarding (45 s)
- **No number, no band, no contribution.** The seeded android tracking defect is an open critical data-quality issue on the success metric. The gate card names it. The next-evidence list starts with fixing the instrumentation and shows "Resolves N blockers" instead of a DDI reduction. A Gated Evidence Summary can exist; a Decision Brief cannot.

## 4. Community and Pricing in brief (45 s)
- **Community:** the aggregate retention gain hides segments that diverge (one positive, one near zero, one negative); the heterogeneity flag fires and the contradiction penalty has a floor.
- **Pricing:** the experiment is inconclusive and underpowered. Open the Assessment tab and choose "Compare with current" on v1: D4 is **unchanged**; the drop between v1 and v2 came from the approved customer evidence, not from a stronger experiment.

## What NOT to claim
- **Not live AI.** Classification, synthesis and review are replayed fixtures and a keyword-rule stub ("stub, not model output"). No live model was ever called. Say "replayed", never "the AI found".
- **Reviewer quality is not measured.** The reviewer flags you see are hand-authored fixtures. Reviewer recall and false-flag rate are NOT EVIDENCED.
- **The score is not validated.** DDI is a proposed heuristic with proposed default parameters. Never call it objective, standard, predictive or a measure of decision quality.
- **The data is synthetic and templated** (195 distinct feedback sentences for 6,083 rows). Agreement with the generator's labels says nothing about real text.
- **Pricing's drop came from customer evidence**, not from the experiment. Do not say the price rise "was proven bad".
- **Community's band is high**, although the Day-1 manifest guessed moderate; the golden snapshot records what the frozen engine returns. Its next-evidence list does not include a segment-level analysis (a known gap).
- **Not a recommendation engine.** It never says approve or reject; a person records the decision.
- Power BI shows a CSV snapshot of the reporting views; say so.

## If something breaks
`scripts/demo_check.py` prints the exact fix command for each failed check. A stale or advanced demo is restored with `scripts/demo_prepare.py --reset`.
