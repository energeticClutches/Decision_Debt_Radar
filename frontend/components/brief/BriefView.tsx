"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { fmtDateTime, fmtNumber, fmtPercent, REPLAY_NOTICE, titleCase } from "../../lib/format";
import type { BriefContent, BriefOut } from "../../lib/types";
import { Icon, Pill, StancePill } from "../ui";
import styles from "./BriefView.module.css";

type Sections = BriefContent["llm_sections"];

function isReplay(provenance: string | null | undefined): boolean {
  return provenance === "stub_not_model_output" || provenance === "recorded_model_output";
}

function Sentences({ items }: { items: Sections["summary"] }) {
  if (!items.length) return <p className="small muted">None stated.</p>;
  return (
    <ul style={{ margin: 0, paddingLeft: 18 }}>
      {items.map((s, i) => (
        <li key={i} className="small">
          {s.text}{" "}
          {s.claim_refs.map((r) => <span key={r.claim_id} className="chip" title="claim">{r.local_id}</span>)}
        </li>
      ))}
    </ul>
  );
}

/** The brief, rendered from the stored `content` JSON only (never from the markdown, never as HTML). There is NO recommendation section. */
export function BriefView({ brief }: { brief: BriefOut }) {
  const c = brief.content;
  const gated = c.kind === "gated_evidence_summary";
  const scored = c.ddi_panel.state === "scored";
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(new Blob([brief.markdown], { type: "text/markdown;charset=utf-8" }));
    setDownloadUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [brief.markdown]);
  const evidenceBy = useMemo(() => ({
    supports: c.evidence_table.filter((e) => e.stance === "supports" && e.status === "active"),
    contradicts: c.evidence_table.filter((e) => e.stance === "contradicts" && e.status === "active"),
  }), [c.evidence_table]);
  const replay = isReplay(c.synthesis?.provenance);
  const het = c.heterogeneity as { flag?: boolean | null };
  return (
    <article className={styles.brief} data-testid="brief" data-kind={c.kind}>
      <div className={styles.toolbar}>
        <Link href="/" className="btn small">Back</Link>
        <button className="btn small" onClick={() => window.print()} data-testid="brief-print">Print</button>
        {downloadUrl ? <a className="btn small" href={downloadUrl} download={`brief-${brief.id.slice(0, 8)}-v${brief.version}.md`} data-testid="brief-markdown">Download Markdown</a> : null}
      </div>

      {/* 1. header */}
      <header className={styles.section} data-testid="brief-header">
        <div className={styles.label} data-testid="brief-label-top">{c.label}</div>
        <h1>{c.title}</h1>
        <div className="row center">
          <Pill tone="info" testId="brief-synthetic">Synthetic data: FitConnect is a fictional company.</Pill>
          {replay ? <Pill tone="warn" testId="provenance-notice">{REPLAY_NOTICE}</Pill> : null}
        </div>
        {c.banners.map((b) => <div key={b} className="banner info small" style={{ marginTop: 6 }} data-testid="brief-banner">{b}</div>)}
        <details className="disclosure card" style={{ marginTop: 8 }}>
          <summary>Versions and hashes</summary>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            <li>Brief version {brief.version}; assessment version {c.header.assessment.version}, as of {c.header.assessment.as_of_date}</li>
            <li>Evidence fingerprint <span className="mono">{c.header.assessment.evidence_fingerprint}</span></li>
            {Object.entries(c.header.versions).map(([k, v]) => <li key={k}>{k}: <span className="mono">{v}</span></li>)}
          </ul>
        </details>
      </header>

      {/* 2. decision */}
      <section className={`card ${styles.section}`} data-testid="brief-decision">
        <h2>The decision</h2>
        <p><strong>{c.header.decision.title}</strong></p>
        <p className="small">Hypothesis: {c.header.decision.hypothesis}</p>
        <p className="small muted">Success metric: {c.header.decision.success_metric ?? "n/a"}. Stage: {c.header.decision.lifecycle_label}.</p>
      </section>

      {/* 3. what the evidence says */}
      <section className={`card ${styles.section}`} data-testid="brief-evidence-says">
        <h2>What the evidence says</h2>
        {c.synthesis ? <p className="small muted">AI-generated interpretation · validated by code checks · version {c.synthesis.version}</p> : <p className="small muted">No validated synthesis exists for this assessment.</p>}
        <Sentences items={c.llm_sections.summary} />
      </section>

      {/* 4. supporting and contradicting evidence */}
      <section className={`card ${styles.section}`} data-testid="brief-supporting-contradicting">
        <h2>Supporting and contradicting evidence</h2>
        <h3>Supporting</h3>
        <Sentences items={c.llm_sections.supporting} />
        <h3 style={{ marginTop: 8 }}>Contradicting</h3>
        <Sentences items={c.llm_sections.contradicting} />
        <div className="tbl-wrap" style={{ marginTop: 8 }}>
          <table className="tbl" data-testid="brief-evidence-table">
            <thead><tr><th>Evidence</th><th>Type</th><th>Stance</th><th>Grade</th><th>Source (tier)</th><th>Status</th></tr></thead>
            <tbody>
              {c.evidence_table.map((e) => (
                <tr key={e.id}><td className="small">{e.summary.slice(0, 120)}</td><td>{titleCase(e.evidence_type)}</td><td><StancePill stance={e.stance} /></td><td>{e.grade}</td><td className="small">{e.source} (tier {e.tier})</td><td>{titleCase(e.status)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="small muted">{evidenceBy.supports.length} supporting and {evidenceBy.contradicts.length} contradicting active item(s).</p>
      </section>

      {/* 5. uncertainty and gaps */}
      <section className={`card ${styles.section}`} data-testid="brief-uncertainty">
        <h2>Uncertainty and gaps</h2>
        <Sentences items={c.llm_sections.uncertainty} />
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          {c.uncertainties.map((u, i) => <li key={`u${i}`} className="small">Uncertainty: {u.text}</li>)}
          {c.gaps.map((g, i) => <li key={`g${i}`} className="small">Gap ({titleCase(g.gap_type)}): {g.text}</li>)}
        </ul>
      </section>

      {/* 6. DDI and direction, or the gate reasons */}
      <section className={`card ${styles.section}`} data-testid="brief-ddi">
        {scored && !gated ? (
          <>
            <h2>Decision Debt Index and direction</h2>
            <div data-region="ddi">
              <span className="big" data-testid="ddi-value" data-ddi-value={c.ddi_panel.ddi ?? undefined}>{c.ddi_panel.ddi?.toFixed(1)}</span>{" "}
              <Pill testId="ddi-band">{titleCase(c.ddi_panel.band)} band</Pill>
            </div>
            <p className="small">Higher = more evidence debt (weaker support). Not a probability the decision is wrong.</p>
            <p className="small muted">{c.ddi_panel.positioning}</p>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead><tr><th>Dimension or penalty</th><th>Score</th><th>Contribution</th></tr></thead>
                <tbody>
                  {c.ddi_panel.dimensions.map((d) => <tr key={d.id}><td>{d.id} {d.name}</td><td>{fmtNumber(d.score, 3)}</td><td>{fmtNumber(d.display_contribution, 2)}</td></tr>)}
                  {c.ddi_panel.penalties.map((p) => <tr key={p.id}><td>{p.id} {p.name}</td><td>{fmtNumber(p.score, 3)}</td><td>{fmtNumber(p.display_contribution, 2)}</td></tr>)}
                </tbody>
              </table>
            </div>
            <h3>Evidence direction</h3>
            <p>{titleCase(c.direction.label)}. <span className="small">Direction is separate from DDI.</span></p>
            <p className="small muted">Supporting {fmtPercent(c.direction.supporting_share, 0)}, contradicting {fmtPercent(c.direction.contradicting_share, 0)}.</p>
          </>
        ) : (
          <>
            <h2>Why there is no score</h2>
            <div data-region="ddi"><div className="big" data-testid="gate-label"><Icon name="stop" /> INSUFFICIENT EVIDENCE</div></div>
            <p className="small">No DDI, band, dimension or penalty exists for this assessment.</p>
            <ul data-testid="brief-gate-reasons">
              {c.gate_reasons.map((r) => <li key={r.code} className="small"><span className="mono">{r.code}</span>: {r.message}</li>)}
            </ul>
            {c.unblocking_actions?.length ? (
              <>
                <h3>Ways to unblock scoring (not advice on the decision)</h3>
                <ul>{c.unblocking_actions.map((a) => <li key={a.action_type} className="small">{a.description} ({a.blockers_resolved === 1 ? "resolves 1 blocker" : `resolves ${a.blockers_resolved} blockers`})</li>)}</ul>
              </>
            ) : null}
          </>
        )}
      </section>

      {/* 7. data quality and heterogeneity */}
      <section className={`card ${styles.section}`} data-testid="brief-dq">
        <h2>Data quality and heterogeneity</h2>
        {c.dq.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {c.dq.filter((d) => d.severity !== "pass").map((d, i) => <li key={i} className="small"><span className="mono">{d.target}</span> ({titleCase(d.severity)}, {d.status}): {d.finding}</li>)}
          </ul>
        ) : <p className="small muted">No data-quality findings are recorded.</p>}
        <p className="small" data-testid="brief-heterogeneity">Heterogeneity: {het.flag === true ? "flagged" : het.flag === false ? "not flagged" : "not available"}.</p>
      </section>

      {/* 8. NBE */}
      <section className={`card ${styles.section}`} data-testid="brief-nbe">
        <h2>Next best evidence</h2>
        <p className="small muted">Ways to gather more evidence. This is not advice on the decision.</p>
        {gated ? <p className="small muted">Unblocking actions are listed in the previous section.</p> : c.nbe.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>{c.nbe.map((a) => <li key={a.action_type} className="small">{a.description} (about {fmtNumber(a.effort_days, 1)} day(s))</li>)}</ul>
        ) : <p className="small muted">None listed.</p>}
      </section>

      {/* 9. review */}
      <section className={`card ${styles.section}`} data-testid="brief-review">
        <h2>Review</h2>
        {c.review.agent_review ? (
          <>
            <p><Pill tone={c.review.agent_review.verdict === "ready" ? "ok" : "bad"}>Verdict: {titleCase(c.review.agent_review.verdict)}</Pill> <span className="small muted">Verdict derived by code from finding severities.</span></p>
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {c.review.agent_review.findings.map((f, i) => <li key={i} className="small">{titleCase(f.severity)} · {f.source === "code" ? "Automated check" : "Reviewer"} · {f.category}: {f.rationale}</li>)}
            </ul>
          </>
        ) : <p><Pill tone="warn" testId="brief-no-review">No automated adversarial review</Pill></p>}
        {c.review.human_reviews.map((h) => <p key={h.review_id} className="small">Human review: {titleCase(h.verdict)}{h.human_response ? ` - ${h.human_response}` : ""} ({fmtDateTime(h.created_at)})</p>)}
      </section>

      {/* 10. what would change the conclusion */}
      <section className={`card ${styles.section}`} data-testid="brief-criteria">
        <h2>What would change the conclusion</h2>
        {c.criteria_assessment.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>{c.criteria_assessment.map((k) => <li key={k.criterion_index} className="small">{k.text}: <Pill>{titleCase(k.status)}</Pill></li>)}</ul>
        ) : <ul style={{ margin: 0, paddingLeft: 18 }}>{c.header.decision.criteria.map((k, i) => <li key={i} className="small">{k}</li>)}</ul>}
      </section>

      {/* 11. decision record */}
      <section className={`card ${styles.section}`} data-testid="brief-record">
        <h2>Decision record</h2>
        {c.decision_record ? <p><strong>{titleCase(c.decision_record.outcome)}</strong>: {c.decision_record.rationale}{c.decision_record.acknowledged_risk ? " (risk acknowledged)" : ""}</p> : <p className="small muted">No decision has been recorded.</p>}
      </section>

      {/* 12. traceability appendix */}
      <section className={`card ${styles.section}`} data-testid="brief-traceability">
        <h2>Traceability appendix</h2>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead><tr><th>Claim</th><th>Evidence</th><th>Source</th><th>Analysis</th><th>Status</th></tr></thead>
            <tbody>
              {c.traceability.map((t, i) => (
                <tr key={i} data-row-type={t.row_type}>
                  <td className="small">{t.claim_local_id ? <span className="chip">{t.claim_local_id}</span> : null} {t.claim_text}</td>
                  <td className="small">{t.evidence_summary?.slice(0, 80) ?? ""}</td>
                  <td className="small">{t.source_name ?? ""}</td>
                  <td>{t.analysis_type ? titleCase(t.analysis_type) : ""}</td>
                  <td>{t.evidence_status ? titleCase(t.evidence_status) : t.row_type === "gap" ? "Gap" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {gated ? <div className={styles.label} data-testid="brief-label-bottom">{c.label}</div> : null}
    </article>
  );
}
