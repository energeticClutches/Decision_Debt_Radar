import type { ReactNode } from "react";

import { supersededLabel } from "../../lib/actions";
import { fmtDateTime, fmtNumber, fmtPercent, fmtValue, titleCase } from "../../lib/format";
import type { AssessmentOut, DecisionOut, DimensionOut, PenaltyOut, RecommendationOut } from "../../lib/types";
import { SvgIcon } from "../icons";
import { Icon, Pill, type Tone } from "../ui";

export const DDI_COPY = "Higher = more evidence debt (weaker support). Not a probability the decision is wrong.";
export const DIRECTION_COPY = "Direction is separate from DDI.";

/** Debt bands run on the slate-to-indigo scale; they are never red or green (the badge also names the band in words). */
export function bandTone(band: string | null | undefined): Tone {
  return band === "low" ? "band-low" : band === "moderate" ? "band-moderate" : band === "high" ? "band-high" : "band-critical";
}

/** The stale banner. A stale assessment never looks current: this banner and the greyed card always go together. */
export function StaleBanner({ decision, onRerun, canRerun, rerunHint }: { decision: DecisionOut; onRerun?: () => void; canRerun?: boolean; rerunHint?: string }) {
  if (!decision.assessment_stale) return null;
  return (
    <div className="banner stale" role="status" data-testid="stale-banner">
      <div><Icon name="clock" /> <strong>Stale: this assessment no longer reflects the current evidence.</strong></div>
      {decision.stale_reason ? <div className="small" data-testid="stale-reason">Reason: {decision.stale_reason}</div> : null}
      {decision.stale_at ? <div className="small" data-testid="stale-at">Since {fmtDateTime(decision.stale_at)}</div> : null}
      {onRerun ? (
        <div style={{ marginTop: 6 }}>
          <button className="btn primary small" onClick={onRerun} disabled={!canRerun} data-testid="stale-rerun" title={canRerun ? undefined : rerunHint}>Re-run assessment</button>
          {!canRerun && rerunHint ? <span className="small muted"> {rerunHint}</span> : null}
        </div>
      ) : null}
    </div>
  );
}

/** The DDI card. Rendered only for a SCORED assessment: the number, the band and every contribution exist nowhere else in the DOM. */
export function DdiCard({ assessment, stale }: { assessment: AssessmentOut; stale: boolean }) {
  if (assessment.state !== "scored" || assessment.ddi === null) return null;
  const sens = assessment.sensitivity;
  return (
    <section className={`card${stale ? " stale" : ""}`} data-testid="ddi-card" data-state={stale ? "stale" : "current"} aria-label="Decision Debt Index">
      <div data-region="ddi">
        <div className="card-title"><SvgIcon name="chart" size={16} />Decision Debt Index {stale ? <Pill tone="stale" testId="ddi-stale-tag"><Icon name="clock" /> Stale</Pill> : null}</div>
        <div className="row center" style={{ gap: 14 }}>
          <span className="big" data-testid="ddi-value" data-ddi-value={assessment.ddi}>{assessment.ddi.toFixed(1)}</span>
          <Pill tone={stale ? "stale" : bandTone(assessment.band)} testId="ddi-band">{titleCase(assessment.band)} band</Pill>
          {assessment.cap_applied ? <Pill tone="warn" testId="ddi-capped">Capped</Pill> : null}
        </div>
      </div>
      <p className="callout" data-testid="ddi-copy">{DDI_COPY}</p>
      {sens ? (
        <p className="small" data-testid="ddi-sensitivity">
          Sensitivity: {sens.label_text} Range {fmtNumber(sens.range[0], 1)} to {fmtNumber(sens.range[1], 1)} over {sens.count} perturbations ({sens.label}).
        </p>
      ) : null}
      <p className="card-foot" data-testid="ddi-params">
        As of {assessment.as_of_date}. Assessment v{assessment.version}. DDI parameters {assessment.params.ddi_params_version}, NBE parameters {assessment.params.nbe_params_version}.
      </p>
    </section>
  );
}

/** The gate card of an INSUFFICIENT EVIDENCE assessment: every reason with its code, the DQ links, the missing types and the unblocking actions. */
export function GateCard({ assessment, recommendations, onOpenDq }: { assessment: AssessmentOut; recommendations: RecommendationOut[]; onOpenDq?: () => void }) {
  if (assessment.state !== "insufficient_evidence") return null;
  const unblocking = recommendations.filter((r) => r.group === "unblock_scoring");
  return (
    <section className="card" data-testid="gate-card" aria-label="Insufficient evidence">
      <div data-region="ddi">
        <div className="card-title"><SvgIcon name="chart" size={16} />Decision Debt Index</div>
        <div className="big gate" data-testid="gate-label"><Icon name="stop" size={24} /> INSUFFICIENT EVIDENCE</div>
      </div>
      <p className="callout">No DDI is shown. The evidence does not yet meet the minimum needed to score this decision.</p>
      <h3>Why it is gated</h3>
      <ul data-testid="gate-reasons" style={{ marginTop: 0 }}>
        {assessment.blocking_reasons.map((r) => {
          const missing = (r.detail?.missing_types ?? r.detail?.missing) as unknown;
          const dq = r.detail?.dq_check_ids as unknown;
          return (
            <li key={r.code} data-testid={`gate-reason-${r.code}`}>
              <span className="mono">{r.code}</span>: {r.message}
              {Array.isArray(missing) && missing.length ? <div className="small muted">Missing evidence types: {missing.map(String).join(", ")}</div> : null}
              {Array.isArray(dq) && dq.length ? (
                <div className="small">
                  Data-quality issues: {dq.length}{" "}
                  {onOpenDq ? <button className="chip" onClick={onOpenDq} data-testid="gate-dq-link">open data quality</button> : null}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      <h3>What would unblock scoring</h3>
      {unblocking.length ? (
        <ul data-testid="gate-unblocking" style={{ marginTop: 0 }}>
          {unblocking.map((r) => <li key={r.id}>{r.description} <span className="muted small">({r.blockers_resolved === 1 ? "resolves 1 blocker" : `resolves ${r.blockers_resolved} blockers`})</span></li>)}
        </ul>
      ) : <p className="small muted">No unblocking action is listed.</p>}
      {assessment.params ? <p className="small muted">As of {assessment.as_of_date}. Assessment v{assessment.version}.</p> : null}
    </section>
  );
}

export function PartialCard({ assessment }: { assessment: AssessmentOut }) {
  if (assessment.state !== "partial") return null;
  return (
    <section className="card" data-testid="partial-card">
      <div data-region="ddi"><div className="big gate"><Icon name="stop" size={24} /> PARTIAL ASSESSMENT</div></div>
      <p>A pipeline stage failed, so no score exists for this version. Re-run the assessment after the cause is fixed.</p>
      {assessment.blocking_reasons.map((r) => <p key={r.code} className="small"><span className="mono">{r.code}</span>: {r.message}</p>)}
      {assessment.previous_scored_assessment ? (
        <p className="small muted" data-testid="previous-scored">{supersededLabel(assessment.previous_scored_assessment.version)}</p>
      ) : null}
    </section>
  );
}

export function DirectionCard({ assessment }: { assessment: AssessmentOut }) {
  const d = assessment.evidence_direction;
  if (!d) return null;
  const clamp = (v: number | null | undefined) => (v === null || v === undefined || Number.isNaN(v) ? null : Math.max(0, Math.min(1, v)));
  const sup = clamp(d.supporting_share) ?? 0;
  const con = clamp(d.contradicting_share) ?? 0;
  const thr = clamp(d.threshold);
  // No direction is claimed for a gated assessment: the stored shares stay as plain text below, but the prominent bar and tiles
  // are not drawn, so they cannot read as support (Opus verification of the restyle).
  const claimed = assessment.state === "scored";
  return (
    <section className="card" data-testid="direction-card" aria-label="Evidence direction">
      <div className="card-title"><SvgIcon name="arrows" size={16} />Evidence direction</div>
      <div className="big sm" data-testid="direction-label">{titleCase(d.label)}</div>
      {claimed ? <div className="splitbar" role="img" aria-label={`Supporting ${fmtPercent(d.supporting_share, 0)}, contradicting ${fmtPercent(d.contradicting_share, 0)}${thr === null ? "" : `, threshold ${fmtPercent(d.threshold, 0)}`}`}>
        <span className="seg-support" style={{ width: `${sup * 100}%` }} />
        <span className="seg-contradict" style={{ width: `${con * 100}%` }} />
        {thr === null ? null : <span className="tick" style={{ left: `${thr * 100}%` }} />}
      </div> : null}
      <p className="callout" data-testid="direction-copy">{DIRECTION_COPY}</p>
      {claimed ? <div className="tiles" aria-hidden="true">
        <div className="tile"><div className="label"><span className="swatch" style={{ background: "var(--accent)" }} />Supporting</div><div className="value">{fmtPercent(d.supporting_share, 0)}</div></div>
        <div className="tile"><div className="label"><span className="swatch" style={{ background: "var(--faint)" }} />Contradicting</div><div className="value">{fmtPercent(d.contradicting_share, 0)}</div></div>
        <div className="tile"><div className="label">Items</div><div className="value">{d.direction_bearing_items}</div><div className="sub">Threshold {fmtPercent(d.threshold, 0)}</div></div>
      </div> : null}
      <p className="small" style={{ marginTop: 16 }}>
        Supporting {fmtPercent(d.supporting_share, 0)}, contradicting {fmtPercent(d.contradicting_share, 0)} of the direction-bearing evidence.
        Direction-bearing items: {d.direction_bearing_items}. Threshold {fmtPercent(d.threshold, 0)}.
      </p>
      {d.explanation ? <p className="small muted card-foot">{d.explanation}</p> : null}
    </section>
  );
}

/** The next-best-evidence table. When the assessment is gated, the reduction column is replaced by "Resolves N blockers". */
export function NbeTable({ recommendations, gated, stale, limit }: { recommendations: RecommendationOut[]; gated: boolean; stale?: boolean; limit?: number }) {
  const rows = limit ? recommendations.slice(0, limit) : recommendations;
  if (!rows.length) return <div className="card muted" data-testid="nbe-empty">No next-best-evidence action is listed for this assessment.</div>;
  return (
    <div className={`card${stale ? " stale" : ""}`} data-testid="nbe-table" data-gated={gated ? "true" : "false"}>
      <div className="card-title"><SvgIcon name="bolt" size={16} />Next best evidence {stale ? <Pill tone="stale">Stale</Pill> : null}</div>
      <p className="small muted">{rows[0].note}</p>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th className="num">#</th><th>Action</th><th>Why this</th><th className="num">Effort (days)</th>
              {gated ? <th data-testid="nbe-resolves-head" className="num">Resolves</th> : <th data-testid="nbe-reduction-head" className="num">Potential DDI reduction</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} data-testid="nbe-row">
                <td className="num">{r.rank}</td>
                <td>{r.description}</td>
                <td className="small">{r.why_this}</td>
                <td className="num">{fmtNumber(r.effort_days, 1)}</td>
                {gated || r.group === "unblock_scoring" ? (
                  <td className="num" data-testid="nbe-resolves">{r.blockers_resolved === 1 ? "Resolves 1 blocker" : `Resolves ${r.blockers_resolved} blockers`}</td>
                ) : (
                  <td className="num" data-region="nbe-reduction" data-testid="nbe-reduction">{fmtNumber(r.potential_ddi_reduction, 1)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function InputList({ inputs }: { inputs: Array<{ name: string; value: unknown; source: string; default_reason: string | null }> }) {
  if (!inputs.length) return <span className="muted small">none</span>;
  return (
    <ul style={{ margin: 0, paddingLeft: 16 }}>
      {inputs.map((i) => (
        <li key={i.name} className="small">
          <span className="mono">{i.name}</span> = {fmtValue(i.value)}{" "}
          {i.source === "default" ? <Pill tone="warn">Defaulted</Pill> : <Pill tone="ok">Observed</Pill>}
          {i.source === "default" && i.default_reason ? <span className="muted"> ({i.default_reason})</span> : null}
        </li>
      ))}
    </ul>
  );
}

function Details({ details }: { details: Record<string, unknown> }) {
  const scalars = Object.entries(details).filter(([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v));
  if (!scalars.length) return null;
  return <div className="small muted">{scalars.map(([k, v]) => `${k}: ${fmtValue(v)}`).join("; ")}</div>;
}

/** "Why this score?" Everything is read from the stored assessment: D1 to D7, support, the penalty multiplier (P1, P2), uncapped, cap, displayed, band. */
export function WhyThisScore({ assessment }: { assessment: AssessmentOut }): ReactNode {
  if (assessment.state !== "scored") return null;
  return (
    <section className="card" data-testid="why-score">
      <h3>Why this score?</h3>
      <p className="small muted">Read from the stored assessment; nothing is recomputed in the browser.</p>
      <div className="tbl-wrap">
        <table className="tbl" data-testid="dimension-table">
          <thead><tr><th>Dimension</th><th className="num">Score</th><th className="num">Weight</th><th className="num">Contribution</th><th>Inputs</th><th>Explanation</th></tr></thead>
          <tbody>
            {assessment.dimensions.map((d) => (
              <tr key={d.id} data-testid={`dimension-${d.id}`}>
                <td><strong>{d.id}</strong> {d.name}{d.applicable ? "" : " (not applicable)"}</td>
                <td className="num">{fmtNumber(d.score, 3)}</td>
                <td className="num">{fmtNumber(d.weight, 3)}</td>
                <td className="num">{fmtNumber(d.display_contribution, 2)}</td>
                <td><InputList inputs={d.inputs} /></td>
                <td className="small">{d.explanation}<Details details={d.details} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 style={{ marginTop: 12 }}>From dimensions to the displayed value</h3>
      <ol data-testid="score-chain">
        <li>Support: {fmtNumber(assessment.support, 4)}</li>
        <li>
          Penalty multiplier: {fmtNumber(assessment.penalty_multiplier, 4)}
          <div className="tbl-wrap">
            <table className="tbl" data-testid="penalty-table">
              <thead><tr><th>Penalty</th><th className="num">Score</th><th className="num">Coefficient</th><th className="num">Contribution</th><th>Inputs and floor</th></tr></thead>
              <tbody>
                {assessment.penalties.map((p) => (
                  <tr key={p.id} data-testid={`penalty-${p.id}`}>
                    <td><strong>{p.id}</strong> {p.name}</td>
                    <td className="num">{fmtNumber(p.score, 3)}</td>
                    <td className="num">{fmtNumber(p.coefficient, 3)}</td>
                    <td className="num">{fmtNumber(p.display_contribution, 2)}</td>
                    <td><InputList inputs={p.inputs} /><Details details={p.details} /><div className="small">{p.explanation}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </li>
        <li>Uncapped: {fmtNumber(assessment.uncapped_ddi, 2)}</li>
        <li>Cap applied: {assessment.cap_applied ? "yes" : "no"}</li>
        <li>Displayed: {assessment.ddi === null ? "n/a" : assessment.ddi.toFixed(1)}</li>
        <li>Band: {titleCase(assessment.band)}</li>
      </ol>
      {assessment.what_drove_this_result ? <p className="small" data-testid="what-drove">{assessment.what_drove_this_result}</p> : null}
    </section>
  );
}

/** Version history. Older versions appear as "vN, superseded" (a date and a state, never a score in the list). A superseded SCORED version
 * can be opened for a per-dimension comparison with the current scored version (stored data only, see VersionComparison). */
export function VersionHistory({ versions, currentVersion, selected = null, onSelect, comparable = [] }: {
  versions: Array<{ id: string; version: number; state: string; created_at: string }>; currentVersion: number | null;
  selected?: number | null; onSelect?: (version: number | null) => void; comparable?: number[];
}) {
  return (
    <section className="card" data-testid="version-history">
      <h3>Version history</h3>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        {versions.map((v) => (
          <li key={v.id} data-testid="version-row">
            {v.version === currentVersion ? <strong>{`v${v.version}, current`}</strong> : supersededLabel(v.version)}
            <span className="muted small"> {titleCase(v.state)} · {fmtDateTime(v.created_at)}</span>
            {onSelect && v.version !== currentVersion && comparable.includes(v.version) ? (
              <button type="button" className="btn small" data-testid={`compare-v${v.version}`} aria-pressed={selected === v.version}
                onClick={() => onSelect(selected === v.version ? null : v.version)} style={{ marginLeft: 8 }}>
                {selected === v.version ? "Hide comparison" : "Compare with current"}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Per-dimension comparison of a superseded version with the current one. Every value is read from the two stored assessments; nothing is
 * computed. An insufficient or partial version shows "no DDI" and never a number; nothing is shown at all when the current assessment is
 * not scored (a gated decision shows no contribution anywhere). */
export function VersionComparison({ previous, current }: { previous: AssessmentOut; current: AssessmentOut }): ReactNode {
  if (current.state !== "scored") return null;
  if (previous.state !== "scored") {
    return (
      <section className="card" data-testid="version-compare">
        <h3>{`v${previous.version} compared with v${current.version}`}</h3>
        <p data-testid="compare-no-ddi">{`No DDI for v${previous.version}: ${previous.state === "insufficient_evidence" ? "INSUFFICIENT EVIDENCE" : "PARTIAL ASSESSMENT"}.`}</p>
      </section>
    );
  }
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  const prevDims = new Map(previous.dimensions.map((d) => [d.id, d]));
  const prevPens = new Map(previous.penalties.map((d) => [d.id, d]));
  type Row = { id: string; name: string; before: DimensionOut | PenaltyOut | undefined; now: DimensionOut | PenaltyOut };
  const rows: Row[] = [
    ...current.dimensions.map((d) => ({ id: d.id, name: d.name, before: prevDims.get(d.id), now: d })),
    ...current.penalties.map((p) => ({ id: p.id, name: p.name, before: prevPens.get(p.id), now: p })),
  ];
  const inputs = (r: DimensionOut | PenaltyOut | undefined) => (r ? <InputList inputs={r.inputs} /> : <span className="muted small">none</span>);
  return (
    <section className="card" data-testid="version-compare">
      <h3>{`v${previous.version} (superseded) compared with v${current.version} (current)`}</h3>
      <p className="small muted">Read from the two stored assessments; nothing is recomputed in the browser. Synthetic data.</p>
      <div className="tbl-wrap">
        <table className="tbl" data-testid="compare-table">
          <thead><tr><th>Dimension or penalty</th><th>{`Score v${previous.version}`}</th><th>{`Score v${current.version}`}</th><th>{`Contribution v${previous.version}`}</th><th>{`Contribution v${current.version}`}</th><th>Inputs before</th><th>Inputs now</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              // "unchanged" means the evidence-strength attributes (score and inputs) are identical; the contribution can still move because
              // the other dimensions and the cap rescale it, and it is shown in its own columns
              const unchanged = !!r.before && same(r.before.score, r.now.score) && same(r.before.inputs, r.now.inputs);
              return (
                <tr key={r.id} data-testid="compare-row" data-dim={r.id} data-unchanged={unchanged ? "true" : "false"}>
                  <td><strong>{r.id}</strong> {r.name}{unchanged ? <span className="muted small"> (score and inputs unchanged)</span> : null}</td>
                  <td>{fmtNumber(r.before?.score, 3)}</td>
                  <td>{fmtNumber(r.now.score, 3)}</td>
                  <td>{fmtNumber(r.before?.display_contribution, 2)}</td>
                  <td>{fmtNumber(r.now.display_contribution, 2)}</td>
                  <td>{inputs(r.before)}</td>
                  <td>{inputs(r.now)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="small" data-testid="compare-totals">{`Displayed value: v${previous.version} ${previous.ddi === null ? "n/a" : previous.ddi.toFixed(1)}, v${current.version} ${current.ddi === null ? "n/a" : current.ddi.toFixed(1)}. Band: ${titleCase(previous.band)} then ${titleCase(current.band)}.`}</p>
    </section>
  );
}
