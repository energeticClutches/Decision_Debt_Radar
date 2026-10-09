"use client";

import type { ReactNode } from "react";

import { ROLE_ACTIONS, ROLE_LABEL, canOnDecision, type Action } from "../../lib/actions";
import type { DecisionOut, UserOut } from "../../lib/types";

export const FROZEN_HINT = "Decision recorded. Writes are frozen.";

export function rolesList(action: Action): string {
  return ROLE_ACTIONS[action].map((r) => ROLE_LABEL[r]).join(", ");
}

/** A write control. It is disabled when the decision is decided (writes are frozen) or the acting role is not allowed, and it then
 *  names the roles that can. This only hides or disables: the server repeats every permission check. */
export function Guarded({
  action, decision, me, locked = false, onClick, children, testId, className = "btn", extraDisabled = false, type = "button",
}: {
  action: Action;
  decision: DecisionOut | null;
  me: UserOut | null;
  locked?: boolean;
  onClick?: () => void;
  children: ReactNode;
  testId?: string;
  className?: string;
  extraDisabled?: boolean;
  type?: "button" | "submit";
}) {
  const allowed = canOnDecision(me, action, decision);
  const disabled = !allowed || locked || extraDisabled;
  const hint = locked ? FROZEN_HINT : !allowed ? `Allowed roles: ${rolesList(action)}` : null;
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      <button type={type} className={className} disabled={disabled} onClick={onClick} data-testid={testId} data-action={action} title={hint ?? undefined}>
        {children}
      </button>
      {hint ? <span className="small muted" data-testid={testId ? `${testId}-hint` : undefined}>{hint}</span> : null}
    </span>
  );
}
