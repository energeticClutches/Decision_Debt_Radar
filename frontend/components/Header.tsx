"use client";

import Link from "next/link";

import { useIdentity } from "../lib/identity";
import { roleName, REPLAY_NOTICE } from "../lib/format";
import { useTabsSlot } from "./AppShell";
import { LogoMark, SvgIcon } from "./icons";
import styles from "./Header.module.css";

export function Header() {
  const { users, me, health, select, failed } = useIdentity();
  const { setSlot } = useTabsSlot();
  return (
    <header className={styles.header}>
      <div className={styles.inner}>
        <div className={styles.top}>
          <Link href="/" className={styles.brand}><LogoMark />Decision Debt Radar</Link>
          <span className="badge micro" data-testid="synthetic-badge" title="All FitConnect data is synthetic">Synthetic data</span>
          {health?.llm_mode === "replay" ? (
            <span className="badge micro demo" data-testid="llm-chip" title={REPLAY_NOTICE}>Demo mode: replayed fixtures</span>
          ) : null}
          {health?.llm_mode === "off" ? <span className="badge micro" data-testid="llm-chip">LLM off</span> : null}
          <div className={styles.right}>
            <div className={styles.who}>
              <div className={styles.disclaimer} data-testid="auth-disclaimer">
                Demo identity only: not authentication
                {failed ? " · The API cannot be reached." : ""}
              </div>
              <label className={styles.switcher}>
                <span className="small muted">Acting as</span>
                <select
                  data-testid="identity-select"
                  aria-label="Demo identity"
                  value={me?.id ?? ""}
                  onChange={(e) => select(e.target.value)}
                  disabled={!users.length}
                >
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>{`${u.name} · ${roleName(u.role)}`}</option>
                  ))}
                </select>
              </label>
            </div>
            <span className={styles.avatar} aria-hidden="true"><SvgIcon name="user" size={18} /></span>
          </div>
        </div>
        <div className={styles.tabsrow} ref={setSlot} data-testid="topbar-tabs" />
      </div>
    </header>
  );
}
