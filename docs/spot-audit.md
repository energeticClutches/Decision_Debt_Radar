# Human spot-audit sheet (PRD section 19, layer 6)

> **Synthetic data.** The claims and findings below were produced by **replayed fixtures** (stub, not model output), stored by the demo path. The Product Owner fills the `agrees` and `note` columns. The implementer never does.

How to read it: a claim *agrees* if its text is a fair statement of the cited evidence; a finding *agrees* if the flag is justified. Sampling is deterministic: the five claims with the smallest SHA-256 of `scenario:claim id`.


## Ai Coach

Assessment v2 (scored). 8 stored claims; 5 sampled.

| # | Claim (stored) | Type | Stance | Confidence | Ref | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | The AI Coach holdout shows +0.293 workouts (95% CI +0.118 to +0.469) but its sample-ratio check failed, so its allocation cannot be trusted. | descriptive | neutral | low | D4 |  |  |
| 2 | Users with an ai_coach_session show 46.0% D90 retention against 22.9% for all other users, a difference of +23.0% (95% CI +21.7% to +24.4%) in an observational comparison. | associative | supports | medium | D6 |  |  |
| 3 | 706 relevant feedback mentions describe the AI Coach as helpful for staying on track. | customer | supports | low | D5 |  |  |
| 4 | 113 relevant feedback mentions describe the AI Coach as generic or as ignoring what the customer told it. | customer | contradicts | low | P1 |  |  |
| 5 | The higher D90 retention among AI Coach users is caused by the coach itself. | associative | supports | high | D6 |  |  |

Every finding of the stored review(s):

| # | Reviewer | Category | Severity | Source | Rationale | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | agent | causal_from_observational | blocking | model | The claim states that the coach causes the retention difference, but the cited comparison is observational and not randomised. |  |  |
| 2 | agent | uncertainty_understated | info | model | The summary could state that the holdout experiment is imbalanced. |  |  |


## Community

Assessment v2 (scored). 6 stored claims; 5 sampled.

| # | Claim (stored) | Type | Stance | Confidence | Ref | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | 970 relevant feedback mentions say that challenges keep the customer motivated. | customer | supports | low | D5 |  |  |
| 2 | 184 relevant feedback mentions complain that challenge notifications or reminders are too frequent, pushy or stressful. | customer | contradicts | medium | P1 |  |  |
| 3 | Users who joined a challenge show 37.8% D90 retention against 23.3% for all other users, a difference of +14.5% (95% CI +13.4% to +15.6%) in an observational comparison. | associative | supports | medium | D6 |  |  |
| 4 | The aggregate difference may mask opposite effects across engagement styles: the heterogeneity analysis flagged segments whose within-segment effects differ in direction, so the pooled figure should not be read as applying to every user. | risk | neutral | high | P1 |  |  |
| 5 | 210 relevant feedback mentions describe challenges as not particularly useful to the customer. | customer | neutral | low | D5 |  |  |

Every finding of the stored review(s):

| # | Reviewer | Category | Severity | Source | Rationale | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | agent | customer_overgeneralization | warning | model | Feedback mentions come from self-selected reviewers and do not describe all users. |  |  |
| 2 | agent | uncertainty_understated | info | model | The summary could name the engagement styles in which the effect differs. |  |  |


## Onboarding

Assessment v2 (insufficient_evidence). 2 stored claims; 5 sampled.

| # | Claim (stored) | Type | Stance | Confidence | Ref | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | 325 relevant feedback mentions describe getting stuck, looping or giving up during setup. | customer | supports | low | D5 |  |  |
| 2 | An open critical data-quality finding on the activation metric blocks scoring, and customer feedback alone cannot lift the block. | risk | neutral | high | gate |  |  |

Every finding of the stored review(s):

| # | Reviewer | Category | Severity | Source | Rationale | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | agent | evidence_overstated | warning | code | High confidence is stated on grade C or D evidence only. |  |  |
| 2 | agent | missing_evidence | info | model | No quantitative evidence exists while the data-quality finding is open. |  |  |


## Pricing

Assessment v2 (scored). 6 stored claims; 5 sampled.

| # | Claim (stored) | Type | Stance | Confidence | Ref | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | 1,126 relevant feedback mentions say the premium price is too high. | customer | contradicts | low | P1 |  |  |
| 2 | The price test found no harm to conversion from the higher price. | descriptive | neutral | high | D4 |  |  |
| 3 | 821 relevant feedback mentions say premium is worth the price. | customer | supports | low | D5 |  |  |
| 4 | The price test shows an effect of -0.0204 on conversion with a 95% CI from -0.0752 to +0.0343, so the result is inconclusive. | descriptive | neutral | medium | D4 |  |  |
| 5 | The test has a design power of 0.11 at the pre-registered MDE, so it could not reliably detect a conversion loss of that size. | risk | neutral | high | D4 |  |  |

Every finding of the stored review(s):

| # | Reviewer | Category | Severity | Source | Rationale | agrees | note |
|---|---|---|---|---|---|---|---|
| 1 | agent | evidence_overstated | warning | code | High confidence is stated on grade C or D evidence only. |  |  |
| 2 | agent | evidence_overstated | warning | code | High confidence is stated on grade C or D evidence only. |  |  |
| 3 | agent | statistical_misinterpretation | blocking | model | An inconclusive, underpowered test whose interval spans zero does not show the absence of harm. |  |  |

