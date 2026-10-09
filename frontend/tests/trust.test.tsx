import { describe, expect, it } from "vitest";

import { ClaimText } from "../components/ClaimText";
import { DdiCard, GateCard, NbeTable, PartialCard, StaleBanner, VersionHistory } from "../components/assessment/Cards";
import { PortfolioCard } from "../components/Portfolio";
import { CustomerCard } from "../components/workspace/EvidenceTab";
import { Guarded } from "../components/workspace/Guarded";
import { OverviewTab } from "../components/workspace/OverviewTab";
import { StripView } from "../components/workspace/WorkspaceHeader";
import { statusStrip } from "../lib/actions";
import { assessment, decision, gated, html, recommendation, region, review, summary, text, user } from "./helpers";
import type { CustomerEvidence, EvidenceOut } from "../lib/types";
import type { WorkspaceActions, WorkspaceData } from "../components/workspace/types";

const noop = () => undefined;
const ACT: WorkspaceActions = { refresh: noop, perform: async () => ({ ok: false, error: undefined as never }), runPipeline: noop, goTab: noop, openItem: noop, openValidate: noop };

function ws(over: Partial<WorkspaceData> = {}): WorkspaceData {
  return {
    decision: decision(), me: user("pm"), users: [user("pm")], assessment: assessment(), assessments: [assessment()], recommendations: [recommendation({ group: "reduce_debt", blockers_resolved: 0 })],
    reviews: [review()], syntheses: [], evidence: [], customer: null, dq: [], analyses: [], briefs: [], traceability: [], record: null, audit: [], metrics: [], ...over,
  };
}

// ---------------------------------------------------------------- D6-05 rule 2: a gated assessment shows no DDI number anywhere
describe("gated suppression", () => {
  const g = gated();
  const recs = [recommendation(), recommendation({ id: "r2", rank: 2, blockers_resolved: 1, description: "Resolve the data-quality issue" })];

  it("the gate card has no DDI value attribute and no digit in the DDI region", () => {
    const markup = html(<GateCard assessment={g} recommendations={recs} />);
    expect(markup).toContain("INSUFFICIENT EVIDENCE");
    expect(markup).not.toContain("data-ddi-value");
    const ddi = region(markup, "data-region", "ddi");
    expect(ddi).not.toBeNull();
    expect(text(ddi as string)).not.toMatch(/\d/);
    expect(markup).toContain("min_items");                               // every reason with its code
    expect(markup).toContain("open_critical_dq");
    expect(markup).toContain('data-testid="gate-reasons"');
  });

  it("the DDI card renders nothing for a gated assessment", () => {
    expect(html(<DdiCard assessment={g} stale={false} />)).toBe("");
    expect(html(<DdiCard assessment={gated({ ddi: 99.9, band: "critical" })} stale={false} />)).toBe("");     // even a poisoned value is never shown
  });

  it("the gated NBE table replaces the reduction column by 'Resolves N blockers' and has no reduction region", () => {
    const markup = html(<NbeTable recommendations={recs} gated />);
    expect(markup).not.toContain('data-region="nbe-reduction"');
    expect(markup).not.toContain("nbe-reduction-head");
    expect(markup).toContain("Resolves 2 blockers");
    expect(markup).toContain("Resolves 1 blocker");
    expect(markup).not.toContain("12.5");                                   // the stored expected_reduction is never shown
  });

  it("the scored NBE table shows the reduction column", () => {
    const markup = html(<NbeTable recommendations={[recommendation({ group: "reduce_debt", blockers_resolved: 0 })]} gated={false} />);
    expect(markup).toContain('data-region="nbe-reduction"');
    expect(text(region(markup, "data-region", "nbe-reduction") as string)).toBe("12.5");
  });

  it("the whole overview of a gated decision has no DDI value, no reduction region and no band", () => {
    const d = decision({ current_assessment: summary({ state: "insufficient_evidence", ddi: null, band: null }) });
    const markup = html(<OverviewTab ws={ws({ decision: d, assessment: g, assessments: [g], recommendations: recs })} act={ACT} />);
    expect(markup).not.toContain("data-ddi-value");
    expect(markup).not.toContain('data-region="nbe-reduction"');
    expect(markup).not.toContain("ddi-card");
    expect(markup).not.toMatch(/high band|critical band|low band|moderate band/i);
    expect(text(region(markup, "data-region", "ddi") as string)).not.toMatch(/\d/);
  });

  it("the version history of a gated decision lists older versions only as 'vN, superseded'", () => {
    const markup = html(<VersionHistory versions={[{ id: "1", version: 1, state: "scored", created_at: "2026-09-01T00:00:00Z" }, { id: "2", version: 2, state: "insufficient_evidence", created_at: "2026-10-01T00:00:00Z" }]} currentVersion={2} />);
    expect(markup).toContain("v1, superseded");
    expect(markup).toContain("v2, current");
    expect(markup).not.toMatch(/\d\d\.\d/);
  });

  it("the portfolio card of a gated decision shows only INSUFFICIENT EVIDENCE", () => {
    const d = decision({ current_assessment: summary({ state: "insufficient_evidence", ddi: null, band: null }) });
    const markup = html(<PortfolioCard decision={d} />);
    expect(text(markup)).toContain("INSUFFICIENT EVIDENCE");
    expect(markup).not.toContain("data-ddi-value");
    expect(text(markup)).not.toMatch(/DDI \d/);
  });
});

// ---------------------------------------------------------------- D6-05 rule 1: a stale assessment never looks current
describe("stale handling", () => {
  it("the DDI card is greyed out and tagged Stale; the banner carries the copy, the reason and the time", () => {
    const d = decision({ assessment_stale: true, stale_reason: "customer evidence approved after the assessment", stale_at: "2026-10-02T09:30:00Z", lifecycle_stage: "evidence_gathered" });
    const card = html(<DdiCard assessment={assessment()} stale />);
    expect(card).toContain('data-state="stale"');
    expect(card).toContain("card stale");
    expect(card).toContain("ddi-stale-tag");
    const banner = html(<StaleBanner decision={d} onRerun={noop} canRerun />);
    expect(text(banner)).toContain("Stale: this assessment no longer reflects the current evidence.");
    expect(text(banner)).toContain("customer evidence approved after the assessment");
    expect(text(banner)).toContain("2026-10-02 09:30 UTC");
    expect(text(banner)).toContain("Re-run assessment");
  });

  it("a current assessment has neither the stale class nor the banner", () => {
    const card = html(<DdiCard assessment={assessment()} stale={false} />);
    expect(card).toContain('data-state="current"');
    expect(card).not.toContain("card stale");
    expect(card).not.toContain("ddi-stale-tag");
    expect(html(<StaleBanner decision={decision()} />)).toBe("");
  });

  it("the overview of a stale decision shows the banner, the greyed card and a stale NBE table", () => {
    const d = decision({ assessment_stale: true, lifecycle_stage: "evidence_gathered", stale_reason: "evidence added after the assessment", stale_at: "2026-10-02T09:30:00Z" });
    const markup = html(<OverviewTab ws={ws({ decision: d })} act={ACT} />);
    expect(markup).toContain("stale-banner");
    expect(markup).toContain('data-state="stale"');
    expect(markup).toContain("stale-rerun");
  });

  it("the portfolio card of a stale decision says Stale and shows no DDI number", () => {
    const d = decision({ assessment_stale: true });
    const markup = html(<PortfolioCard decision={d} />);
    expect(text(markup)).toContain("Stale");
    expect(markup).not.toContain("data-ddi-value");
    expect(text(markup)).not.toMatch(/DDI \d/);
    expect(markup).toContain('data-headline="stale"');
  });

  it("the status strip of a stale decision carries the same copy", () => {
    const strip = statusStrip(decision({ assessment_stale: true }), summary(), [review()]);
    expect(text(html(<StripView strip={strip} />))).toContain("Stale: this assessment no longer reflects the current evidence.");
  });
});

// ---------------------------------------------------------------- D6-05 rule 3: previous_scored_assessment is never the headline
describe("previous_scored_assessment", () => {
  const prev = summary({ version: 1, ddi: 77.7, band: "critical", historical: true });
  it("a partial current assessment is shown as PARTIAL and the previous version only as 'v1, superseded'", () => {
    const partial = assessment({ state: "partial", ddi: null, band: null, dimensions: [], penalties: [], blocking_reasons: [{ code: "stage_failed", message: "dq failed", detail: {} }], previous_scored_assessment: prev });
    const markup = html(<PartialCard assessment={partial} />);
    expect(text(markup)).toContain("PARTIAL ASSESSMENT");
    expect(text(markup)).toContain("v1, superseded");
    expect(markup).not.toMatch(/77\.7|critical/);
    expect(markup).not.toContain("data-ddi-value");
  });
  it("the portfolio card never shows the previous score", () => {
    const d = decision({ current_assessment: summary({ state: "partial", ddi: null, band: null }), previous_scored_assessment: prev });
    const markup = html(<PortfolioCard decision={d} />);
    expect(markup).not.toMatch(/77\.7|critical/);
    expect(text(markup)).toContain("PARTIAL ASSESSMENT");
  });
});

// ---------------------------------------------------------------- untrusted text
describe("untrusted text is never HTML", () => {
  it("a <script> quote and an unknown [[id]] render as text", () => {
    const markup = html(<ClaimText text={'He said <script>alert("x")</script> and [[c1]] then [[nope]]'} known={["c1"]} />);
    expect(markup).not.toContain("<script>");
    expect(markup).toContain("&lt;script&gt;");
    expect(markup).toContain("claim-chip-c1");
    expect(markup).not.toContain("claim-chip-nope");
    expect(text(markup)).toContain("[[nope]]");
  });
  it("a customer quote with markup in a card is escaped", () => {
    const e = { id: "e1", status: "active", stance: "supports", strength_grade: "C", summary: "<img src=x onerror=alert(1)> theme", source_name: "Feedback", reliability_tier: 3 } as unknown as EvidenceOut;
    const item: CustomerEvidence["items"][number] = {
      evidence: e, classification_counts: null,
      insight: { id: "i1", theme: "coach_helpful", sentiment: "positive", mentions: 5, relevance_observed: 1, relevance_note: "observed, not used by DDI v0.1", source_types: [], first_mention_date: null, last_mention_date: null, taxonomy_version: "t", segment_counts: null, sample_quotes: [{ text: "<script>steal()</script>" }] },
    };
    const markup = html(<CustomerCard item={item} ws={{ decision: decision(), me: user("ba") }} act={{ openItem: noop }} note="" setNote={noop} busy={false} />);
    expect(markup).not.toContain("<script>");
    expect(markup).not.toContain("<img");
    expect(markup).toContain("&lt;script&gt;");
  });
});

// ---------------------------------------------------------------- role gating of controls (display only)
describe("controls are disabled for roles that may not use them", () => {
  const d = decision();
  it("Validate is disabled for a product analyst and names the roles that can", () => {
    const markup = html(<Guarded action="validate" decision={d} me={user("product_analyst")} testId="validate-open">Validate</Guarded>);
    expect(markup).toMatch(/<button[^>]*disabled/);
    expect(text(markup)).toContain("Allowed roles:");
    expect(text(markup)).toContain("Product Manager");
  });
  it("Validate is enabled for a product manager", () => {
    const markup = html(<Guarded action="validate" decision={d} me={user("pm")} testId="validate-open">Validate</Guarded>);
    expect(markup).not.toMatch(/<button[^>]*disabled/);
  });
  it("every write control is disabled once the decision is decided", () => {
    const markup = html(<Guarded action="validate" decision={d} me={user("pm")} locked testId="x">Validate</Guarded>);
    expect(markup).toMatch(/<button[^>]*disabled/);
    expect(text(markup)).toContain("Decision recorded. Writes are frozen.");
  });
  it("a PM cannot approve a proposed customer item", () => {
    const e = { id: "e1", status: "proposed", stance: "supports", strength_grade: "C", summary: "s", source_name: "Feedback", reliability_tier: 3, approved_by: null } as unknown as EvidenceOut;
    const item: CustomerEvidence["items"][number] = { evidence: e, insight: null, classification_counts: null };
    const markup = html(<CustomerCard item={item} ws={{ decision: d, me: user("pm") }} act={{ openItem: noop }} note="a note" setNote={noop} busy={false} />);
    expect(markup).toMatch(/<button[^>]*disabled[^>]*data-testid="approve-e1"/);
    expect(text(markup)).toContain("Allowed roles: Business Analyst, Product Analyst");
    expect(text(markup)).toContain("Approval changes the evidence: the current assessment becomes stale. Rejection is permanent for this item.");
    expect(text(markup)).toContain("Set by taxonomy, not by AI");
    const ba = html(<CustomerCard item={item} ws={{ decision: d, me: user("ba") }} act={{ openItem: noop }} note="a note" setNote={noop} busy={false} />);
    expect(ba).not.toMatch(/<button[^>]*disabled[^>]*data-testid="approve-e1"/);
  });
});
