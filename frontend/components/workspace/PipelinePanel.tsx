"use client";

import { titleCase } from "../../lib/format";
import type { PipelineRun } from "../../lib/types";
import { ErrorBox, Modal, Pill } from "../ui";
import type { ApiError } from "../../lib/api";

const STAGE_NAMES: Record<string, string> = {
  dq: "Data quality", quant: "Quantitative analyses", customer: "Customer evidence", experiment: "Experiment analysis",
  materialize: "Evidence generation", assessment: "Assessment", synthesis: "Evidence synthesis", review: "Review",
};

function summary(stage: PipelineRun["stages"][number]): string {
  const o = stage.output ?? {};
  const outcome = typeof o.outcome === "string" ? titleCase(o.outcome) : "";
  if (stage.stage === "assessment") return `${titleCase(String(o.state ?? ""))}${typeof o.version === "number" ? `, version ${o.version}` : ""}`;
  if (stage.stage === "synthesis" || stage.stage === "review") return titleCase(String(o.status ?? stage.status));
  return outcome || stage.error || "";
}

/** The pipeline call is synchronous: a blocking progress panel while it runs, then the per-stage results the response returned. */
export function PipelinePanel({ running, result, error, onClose }: { running: boolean; result: PipelineRun | null; error: ApiError | null; onClose: () => void }) {
  return (
    <Modal title={running ? "Running the assessment pipeline" : "Pipeline finished"} onClose={running ? () => undefined : onClose} testId="pipeline-panel">
      {running ? (
        <div role="status" data-testid="pipeline-running">
          <p>Checking data quality, running the analyses, classifying customer feedback, scoring and reviewing. This can take a minute or two. Please keep this page open.</p>
          <p className="small muted">The controls are paused until the pipeline returns.</p>
        </div>
      ) : null}
      {error ? <ErrorBox error={error} /> : null}
      {result ? (
        <div data-testid="pipeline-result">
          {result.partial ? <div className="banner bad"><strong>Partial assessment.</strong> Stage {result.failed_stage} failed: {result.error}. No score exists for this version.</div> : null}
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Stage</th><th>Status</th><th>Result</th></tr></thead>
              <tbody>
                {result.stages.map((s) => (
                  <tr key={s.stage} data-testid="pipeline-stage" data-stage={s.stage}>
                    <td>{STAGE_NAMES[s.stage] ?? titleCase(s.stage)}</td>
                    <td><Pill tone={s.status === "succeeded" ? "ok" : s.status === "failed" ? "bad" : "warn"}>{titleCase(s.status)}</Pill></td>
                    <td className="small">{summary(s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.pending_approvals.length ? <p className="small">{result.pending_approvals.length} customer evidence item(s) await approval in the Evidence tab.</p> : null}
        </div>
      ) : null}
      {!running ? <div className="row" style={{ marginTop: 10 }}><button className="btn primary" onClick={onClose} data-testid="pipeline-close">Close</button></div> : null}
    </Modal>
  );
}
