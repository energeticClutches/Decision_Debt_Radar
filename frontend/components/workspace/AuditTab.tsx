"use client";

import { auditWords, fmtDateTime, fmtValue, roleName } from "../../lib/format";
import type { AuditRow, UserOut } from "../../lib/types";
import { Empty } from "../ui";
import type { TabProps } from "./types";

const HIDDEN_KEYS = new Set(["decision_id", "requested_by"]);

export function actorLabel(row: AuditRow, users: UserOut[]): string {
  if (row.actor_type === "user") {
    const u = users.find((x) => x.id === row.actor_id);
    return u ? `${u.name} (${roleName(u.role)})` : "A person";
  }
  return row.actor_type === "agent" ? "Automated agent" : "System";
}

/** The key before and after values of an audit row, as short "key: before to after" lines. */
export function keyChanges(row: AuditRow): string[] {
  const after = row.after ?? {};
  const before = row.before ?? {};
  const keys = Object.keys(after).filter((k) => !HIDDEN_KEYS.has(k));
  const lines: string[] = [];
  for (const k of keys) {
    const a = after[k];
    if (a !== null && typeof a === "object") continue;
    const b = before[k];
    lines.push(b !== undefined && b !== a ? `${k}: ${fmtValue(b)} to ${fmtValue(a)}` : `${k}: ${fmtValue(a)}`);
  }
  return lines.slice(0, 6);
}

export function AuditTimeline({ rows, users }: { rows: AuditRow[]; users: UserOut[] }) {
  if (!rows.length) return <Empty testId="audit-empty">No audit events yet.</Empty>;
  return (
    <ol className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }} data-testid="audit-timeline">
      {[...rows].reverse().map((r) => (
        <li key={r.id} className="card" data-testid="audit-row" data-action={r.action}>
          <div className="row center">
            <strong>{auditWords(r.action)}</strong>
            <span className="small muted">{actorLabel(r, users)} · {fmtDateTime(r.ts)}</span>
          </div>
          {keyChanges(r).length ? <div className="small">{keyChanges(r).join(" · ")}</div> : null}
          <details className="disclosure small"><summary>Raw event</summary><pre className="mono" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify({ before: r.before, after: r.after, entity: r.entity_type, entity_id: r.entity_id }, null, 2)}</pre></details>
        </li>
      ))}
    </ol>
  );
}

export function AuditTab({ ws }: TabProps) {
  return <div className="stack" data-testid="tab-panel-audit"><AuditTimeline rows={ws.audit} users={ws.users} /></div>;
}
