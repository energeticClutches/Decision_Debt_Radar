"use client";

import { createContext, useContext, useState, type ReactNode } from "react";

import { IdentityProvider } from "../lib/identity";
import { Header } from "./Header";

/** The slot in the top bar where the workspace tabs are rendered (a portal target). null until the bar has mounted. */
const TabsSlot = createContext<{ slot: HTMLElement | null; setSlot: (el: HTMLElement | null) => void }>({ slot: null, setSlot: () => undefined });

export function useTabsSlot() {
  return useContext(TabsSlot);
}

export function AppShell({ children }: { children: ReactNode }) {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  return (
    <IdentityProvider>
      <TabsSlot.Provider value={{ slot, setSlot }}>
        <Header />
        <main className="page">{children}</main>
      </TabsSlot.Provider>
    </IdentityProvider>
  );
}
