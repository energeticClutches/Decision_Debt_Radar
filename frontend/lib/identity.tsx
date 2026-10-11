"use client";

// The demo identity (role switcher). It is NOT authentication: the id is sent as X-Demo-User and the server reads the role from the database.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, getStoredUser, setStoredUser } from "./api";
import type { Health, UserOut } from "./types";
import { retryOnWake } from "./wake";

interface IdentityValue {
  users: UserOut[];
  me: UserOut | null;
  health: Health | null;
  ready: boolean;
  failed: boolean;
  select: (id: string) => void;
}

const Ctx = createContext<IdentityValue>({ users: [], me: null, health: null, ready: false, failed: false, select: () => undefined });

export function useIdentity(): IdentityValue {
  return useContext(Ctx);
}

export function IdentityProvider({ children }: { children: ReactNode }) {
  const [users, setUsers] = useState<UserOut[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [meId, setMeId] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    retryOnWake(() => Promise.all([api.users(), api.health().catch(() => null)]), () => cancelled).then(
      ([list, h]) => {
        if (cancelled) return;
        setUsers(list);
        setHealth(h);
        const stored = getStoredUser();
        const chosen = list.find((u) => u.id === stored) ?? list.find((u) => u.role === "pm") ?? list[0];
        if (chosen) {
          setStoredUser(chosen.id);
          setMeId(chosen.id);
        }
        setReady(true);
      },
      () => {
        if (!cancelled) {
          setFailed(true);
          setReady(true);
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const select = useCallback((id: string) => {
    setStoredUser(id);
    setMeId(id);
  }, []);

  const value = useMemo<IdentityValue>(
    () => ({ users, me: users.find((u) => u.id === meId) ?? null, health, ready, failed, select }),
    [users, meId, health, ready, failed, select],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
