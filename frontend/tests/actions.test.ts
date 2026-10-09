import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  can, canOnDecision, headline, LEADER_OWN_TEAM_ONLY, nextAction, OWNER_ALSO_ALLOWED, ROLE_ACTIONS, ROLE_LABEL, statusStrip, STALE_BANNER_TEXT, type Action,
} from "../lib/actions";
import { STAGES } from "../lib/format";
import type { LifecycleStage, Role } from "../lib/types";
import { assessment, decision, gated, review, summary, user } from "./helpers";

const ROLES: Role[] = ["pm", "ba", "product_analyst", "bizops", "dept_leader", "executive"];

// ---------------------------------------------------------------- parity with backend/app/domain/permissions.py
function parsePermissions() {
  const src = readFileSync(resolve(__dirname, "../../backend/app/domain/permissions.py"), "utf-8");
  const constants = new Map<string, string>();
  for (const m of src.matchAll(/^([A-Z_]+)\s*=\s*"([a-z_]+)"/gm)) constants.set(m[1], m[2]);
  const block = src.slice(src.indexOf("ROLE_ACTIONS"), src.indexOf("# Actions where a department leader"));
  const actions = new Map<string, string[]>();
  for (const m of block.matchAll(/^\s*([A-Z_]+):\s*frozenset\(\{([^}]*)\}\)/gm)) {
    actions.set(constants.get(m[1]) ?? m[1], Array.from(m[2].matchAll(/"([a-z_]+)"/g)).map((x) => x[1]).sort());
  }
  const setOf = (name: string) => {
    const m = new RegExp(`^${name}\\s*=\\s*frozenset\\(\\{([^}]*)\\}\\)`, "m").exec(src);
    return m ? Array.from(m[1].matchAll(/([A-Z_]+)/g)).map((x) => constants.get(x[1]) ?? x[1]).sort() : [];
  };
  return { actions, leader: setOf("LEADER_OWN_TEAM_ONLY"), owner: setOf("OWNER_ALSO_ALLOWED") };
}

describe("can() parity with permissions.py", () => {
  const py = parsePermissions();
  it("has the same actions and the same roles for every action", () => {
    expect(py.actions.size).toBe(13);
    expect(Object.keys(ROLE_ACTIONS).sort()).toEqual(Array.from(py.actions.keys()).sort());
    for (const [action, roles] of py.actions) expect([...ROLE_ACTIONS[action as Action]].sort(), action).toEqual(roles);
  });
  it("has the same ownership rules", () => {
    expect([...LEADER_OWN_TEAM_ONLY].sort()).toEqual(py.leader);
    expect([...OWNER_ALSO_ALLOWED].sort()).toEqual(py.owner);
  });
  it("can() answers from the matrix", () => {
    for (const [action, roles] of py.actions) for (const role of ROLES) expect(can(role, action as Action), `${role} ${action}`).toBe(roles.includes(role));
    expect(can(null, "validate")).toBe(false);
  });
  it("applies the leader own-team and the owner rules", () => {
    const own = { teamId: "t1", decisionTeamId: "t1", userId: "u", decisionOwnerId: "o" };
    expect(can("dept_leader", "record_decision", own)).toBe(true);
    expect(can("dept_leader", "record_decision", { ...own, decisionTeamId: "t2" })).toBe(false);
    expect(can("dept_leader", "validate", { ...own, decisionTeamId: "t2" })).toBe(false);
    expect(can("pm", "record_decision", { ...own, userId: "o" })).toBe(true);      // the owner may always record
    expect(can("pm", "record_decision", own)).toBe(false);
    expect(can("executive", "record_decision", { ...own, decisionTeamId: "t2" })).toBe(true);
  });
});

// ---------------------------------------------------------------- nextAction across every stage and role
const EXPECTED: Record<string, { id: string; action: Action } | null> = {
  created: { id: "confirm_evidence", action: "confirm_evidence" },
  evidence_gathered: { id: "run_assessment", action: "run_assessment" },
  stale: { id: "rerun_assessment", action: "run_assessment" },
  pending: { id: "approve_evidence", action: "approve_evidence" },
  assessed: { id: "run_review", action: "run_synthesis" },
  assessed_with_agent_review: { id: "resolve_review", action: "human_review" },
  challenged_rework: { id: "resolve_review", action: "human_review" },
  challenged_ready: { id: "validate", action: "validate" },
  validated: { id: "record_decision", action: "record_decision" },
  decided: null,
};

function situation(name: string) {
  const sc = summary({ state: "scored" });
  switch (name) {
    case "created": return { d: decision({ lifecycle_stage: "created", current_assessment: null }), a: null, r: [] };
    case "evidence_gathered": return { d: decision({ lifecycle_stage: "evidence_gathered", current_assessment: null }), a: null, r: [] };
    case "stale": return { d: decision({ lifecycle_stage: "evidence_gathered", assessment_stale: true }), a: sc, r: [review()] };
    case "pending": return { d: decision({ lifecycle_stage: "evidence_gathered", pending_approvals: 2 }), a: null, r: [] };
    case "assessed": return { d: decision({ lifecycle_stage: "assessed" }), a: sc, r: [] };
    case "assessed_with_agent_review": return { d: decision({ lifecycle_stage: "assessed" }), a: sc, r: [review()] };
    case "challenged_rework": return { d: decision({ lifecycle_stage: "challenged" }), a: sc, r: [review({ verdict: "needs_rework" })] };
    case "challenged_ready": return { d: decision({ lifecycle_stage: "challenged" }), a: sc, r: [review({ verdict: "ready" })] };
    case "validated": return { d: decision({ lifecycle_stage: "validated" }), a: sc, r: [review({ verdict: "ready" })] };
    default: return { d: decision({ lifecycle_stage: "decided" }), a: sc, r: [review()] };
  }
}

describe("nextAction", () => {
  for (const name of Object.keys(EXPECTED)) {
    it(`${name}: one action, enabled exactly for the allowed roles, otherwise disabled and naming the roles`, () => {
      const expected = EXPECTED[name];
      for (const role of ROLES) {
        const { d, a, r } = situation(name);
        const me = user(role, { team_id: d.team_id, id: `u-${role}` });
        const next = nextAction(d, a, r, me);
        if (!expected) { expect(next).toBeNull(); continue; }
        expect(next?.id, `${name}/${role}`).toBe(expected.id);
        expect(next?.action).toBe(expected.action);
        const allowed = canOnDecision(me, expected.action, d);
        expect(next?.enabled).toBe(allowed);
        if (allowed) expect(next?.disabledReason).toBeNull();
        else {
          expect(next?.disabledReason).toContain("Allowed roles:");
          for (const allowedRole of ROLE_ACTIONS[expected.action]) {
            expect(next?.roles).toContain(allowedRole);
            expect(next?.disabledReason).toContain(ROLE_LABEL[allowedRole]);
          }
        }
      }
    });
  }
  it("covers every lifecycle stage", () => {
    const seen = new Set(Object.keys(EXPECTED).map((n) => situation(n).d.lifecycle_stage));
    for (const s of STAGES) expect(seen.has(s as LifecycleStage), s).toBe(true);
  });
  it("is disabled without an identity", () => {
    const { d, a, r } = situation("challenged_ready");
    expect(nextAction(d, a, r, null)?.enabled).toBe(false);
  });
  it("a product analyst cannot validate and an executive can record", () => {
    const v = situation("challenged_ready");
    expect(nextAction(v.d, v.a, v.r, user("product_analyst"))?.enabled).toBe(false);
    const rec = situation("validated");
    expect(nextAction(rec.d, rec.a, rec.r, user("executive"))?.enabled).toBe(true);
    expect(nextAction(rec.d, rec.a, rec.r, user("pm"))?.enabled).toBe(false);
  });
});

// ---------------------------------------------------------------- statusStrip priority
describe("statusStrip priority", () => {
  const rework = review({ verdict: "needs_rework", findings: [{ category: "c", severity: "blocking", severity_model: "warning", source: "model", target_type: "claim", target_id: "x", target_local_id: "c7", rationale: "r", evidence_ids: [], notes: [] }] });
  it("decided lock beats everything", () => {
    const d = decision({ lifecycle_stage: "decided", assessment_stale: true, pending_approvals: 3 });
    expect(statusStrip(d, summary({ state: "insufficient_evidence" }), [rework]).kind).toBe("decided");
  });
  it("stale beats gated, needs rework, review failed and pending approvals", () => {
    const d = decision({ assessment_stale: true, pending_approvals: 3, lifecycle_stage: "evidence_gathered" });
    const strip = statusStrip(d, summary({ state: "insufficient_evidence" }), [rework]);
    expect(strip.kind).toBe("stale");
    expect(strip.text).toBe(STALE_BANNER_TEXT);
  });
  it("gated beats needs rework", () => {
    expect(statusStrip(decision(), summary({ state: "insufficient_evidence" }), [rework]).kind).toBe("gated");
  });
  it("needs rework beats review failed and pending approvals", () => {
    expect(statusStrip(decision({ pending_approvals: 2 }), summary(), [rework]).kind).toBe("needs_rework");
  });
  it("review failed (no automated review) beats pending approvals", () => {
    const strip = statusStrip(decision({ pending_approvals: 2, lifecycle_stage: "assessed" }), summary(), []);
    expect(strip.kind).toBe("review_failed");
    expect(strip.text).toBe("No automated adversarial review");
  });
  it("pending approvals beat normal; otherwise normal", () => {
    expect(statusStrip(decision({ pending_approvals: 1 }), summary(), [review()]).kind).toBe("pending_approvals");
    expect(statusStrip(decision(), summary(), [review()]).kind).toBe("normal");
    expect(statusStrip(decision({ lifecycle_stage: "evidence_gathered", current_assessment: null }), null, []).kind).toBe("normal");
  });
  it("the decided text is the exact copy", () => {
    expect(statusStrip(decision({ lifecycle_stage: "decided" }), summary(), [review()]).text).toBe("Decision recorded. Writes are frozen.");
  });
});

describe("headline", () => {
  it("is exactly one of DDI x - Band, INSUFFICIENT EVIDENCE or Stale", () => {
    expect(headline(decision()).text).toBe("DDI 61.5 · High");
    expect(headline(decision({ current_assessment: summary({ state: "insufficient_evidence", ddi: null, band: null }) })).text).toBe("INSUFFICIENT EVIDENCE");
    expect(headline(decision({ assessment_stale: true })).text).toBe("Stale");
  });
  it("never uses previous_scored_assessment", () => {
    const prev = summary({ version: 1, ddi: 77.7, band: "critical", historical: true });
    const partial = decision({ current_assessment: summary({ state: "partial", ddi: null, band: null }), previous_scored_assessment: prev });
    expect(headline(partial).kind).toBe("partial");
    expect(headline(partial).text).not.toMatch(/77|critical/i);
    expect(headline(decision({ current_assessment: null, previous_scored_assessment: prev })).kind).toBe("none");
  });
});

// an assessment helper sanity check keeps the shared fixtures honest
describe("fixtures", () => {
  it("a gated assessment carries no number", () => {
    const g = gated();
    expect(g.ddi).toBeNull();
    expect(assessment().ddi).toBe(61.5);
  });
});
