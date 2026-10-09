"use client";

import Link from "next/link";
import { useEffect, type ReactNode } from "react";

import { ApiError } from "../lib/api";
import { isReplayProvenance, REPLAY_NOTICE, roleName, titleCase } from "../lib/format";

const ICONS: Record<string, string> = { lock: "⚿", clock: "◷", stop: "⊘", alert: "⚠", hourglass: "⧖", check: "✓", info: "ℹ" };

export function Icon({ name }: { name: string }) {
  return <span aria-hidden="true">{ICONS[name] ?? "•"}</span>;
}

/** Status is never colour alone: a glyph and a word always come with the colour. */
export function Pill({ tone, children, testId }: { tone?: "ok" | "warn" | "bad" | "info" | "stale"; children: ReactNode; testId?: string }) {
  return <span className={`badge ${tone ?? ""}`} data-testid={testId}>{children}</span>;
}

export function StancePill({ stance }: { stance: string | null | undefined }) {
  if (!stance) return null;
  const tone = stance === "supports" ? "ok" : stance === "contradicts" ? "bad" : "info";
  const glyph = stance === "supports" ? "+" : stance === "contradicts" ? "−" : "∼";
  return <Pill tone={tone}>{glyph} {titleCase(stance)}</Pill>;
}

export function SeverityPill({ severity }: { severity: string | null | undefined }) {
  const tone = severity === "blocking" ? "bad" : severity === "warning" ? "warn" : "info";
  const glyph = severity === "blocking" ? "⊘" : severity === "warning" ? "⚠" : "ℹ";
  return <Pill tone={tone}>{glyph} {titleCase(severity)}</Pill>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <div className="card muted" role="status" data-testid="loading">{label}...</div>;
}

export function Empty({ children, testId }: { children: ReactNode; testId?: string }) {
  return <div className="card muted" data-testid={testId ?? "empty"}>{children}</div>;
}

/** The server message and, for 401/403, the roles that may act (detail.allowed_roles). 404 gets a back link, 5xx a retry. Never a stack trace. */
export function ErrorBox({ error, onRetry, onDismiss }: { error: ApiError; onRetry?: () => void; onDismiss?: () => void }) {
  const roles = error.allowedRoles;
  if (error.status === 404) {
    return (
      <div className="banner warn" role="alert" data-testid="error-404">
        <strong>Not found.</strong> {error.message} <Link href="/">Back to the portfolio</Link>
      </div>
    );
  }
  const server = error.status >= 500 || error.status === 0;
  return (
    <div className={`banner ${server ? "bad" : "warn"}`} role="alert" data-testid="error-box" data-status={error.status}>
      <div>{server ? (error.status === 0 ? error.message : "Something went wrong on the server. Please retry.") : error.message}</div>
      {roles.length ? <div className="small" data-testid="error-roles">Allowed roles: {roles.map(roleName).join(", ")}</div> : null}
      <div className="row" style={{ marginTop: 6 }}>
        {server && onRetry ? <button className="btn small" onClick={onRetry}>Retry</button> : null}
        {onDismiss ? <button className="btn small" onClick={onDismiss}>Dismiss</button> : null}
      </div>
    </div>
  );
}

/** Wherever an LLM output is shown and its provenance is not a live model, this notice appears. */
export function ProvenanceNotice({ provenance, model }: { provenance: string | null | undefined; model?: string | null }) {
  if (!isReplayProvenance(provenance)) return null;
  return (
    <span className="badge warn" data-testid="provenance-notice" title={model ? `Model: ${model}` : undefined}>
      {REPLAY_NOTICE}
    </span>
  );
}

export function Modal({ title, onClose, children, testId }: { title: string; onClose: () => void; children: ReactNode; testId?: string }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} data-testid={testId}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Drawer({ title, onClose, children, testId }: { title: string; onClose: () => void; children: ReactNode; testId?: string }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <aside className="drawer" role="dialog" aria-label={title} data-testid={testId ?? "drawer"}>
      <div className="row center">
        <h2 style={{ margin: 0 }}>{title}</h2>
        <button className="btn small right" onClick={onClose} data-testid="drawer-close">Close</button>
      </div>
      <div className="stack" style={{ marginTop: 10 }}>{children}</div>
    </aside>
  );
}

export function KeyValues({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "max-content 1fr", gap: "4px 12px" }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt className="label" style={{ alignSelf: "center" }}>{k}</dt>
          <dd style={{ margin: 0 }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Field({ label, error, children, htmlFor }: { label: string; error?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className={`field${error ? " invalid" : ""}`}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {error ? <span className="error" role="alert">{error}</span> : null}
    </div>
  );
}
