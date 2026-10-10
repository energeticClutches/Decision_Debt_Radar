"use client";

import { useState } from "react";

import { canOnDecision } from "../../lib/actions";
import { DdiCard, DirectionCard, GateCard, NbeTable, PartialCard, StaleBanner, VersionComparison, VersionHistory, WhyThisScore } from "../assessment/Cards";
import { Empty } from "../ui";
import { isLocked, type TabProps } from "./types";

export function AssessmentTab({ ws, act }: TabProps) {
  const { decision, assessment } = ws;
  const stale = decision.assessment_stale;
  const [selected, setSelected] = useState<number | null>(null);
  const canRerun = canOnDecision(ws.me, "run_assessment", decision) && !isLocked(ws);
  if (!assessment) {
    return <div className="stack" data-testid="tab-panel-assessment"><Empty testId="no-assessment">No assessment yet. Run the assessment from the header.</Empty></div>;
  }
  const gated = assessment.state === "insufficient_evidence";
  // only a scored current assessment can be compared with an older version (a gated decision shows no contribution anywhere)
  const comparable = assessment.state === "scored" ? ws.assessments.filter((a) => a.version < assessment.version).map((a) => a.version) : [];
  const picked = ws.assessments.find((a) => a.version === selected && a.version !== assessment.version) ?? null;
  return (
    <div className="stack" data-testid="tab-panel-assessment">
      <StaleBanner decision={decision} onRerun={act.runPipeline} canRerun={canRerun} rerunHint={canRerun ? undefined : "Allowed roles: Product Manager, Business Analyst, Product Analyst"} />
      <div className="row">
        <div className="grow">
          <DdiCard assessment={assessment} stale={stale} />
          <GateCard assessment={assessment} recommendations={ws.recommendations} onOpenDq={() => act.goTab("evidence")} />
          <PartialCard assessment={assessment} />
        </div>
        <div className="grow"><DirectionCard assessment={assessment} /></div>
      </div>
      {assessment.state === "scored" ? (
        <div className={stale ? "card stale" : undefined}><WhyThisScore assessment={assessment} /></div>
      ) : null}
      {assessment.state !== "partial" ? <NbeTable recommendations={ws.recommendations} gated={gated} stale={stale} /> : null}
      <VersionHistory versions={[...ws.assessments].sort((a, b) => b.version - a.version)} currentVersion={assessment.version}
        selected={selected} onSelect={setSelected} comparable={comparable} />
      {picked ? <VersionComparison previous={picked} current={assessment} /> : null}
    </div>
  );
}
