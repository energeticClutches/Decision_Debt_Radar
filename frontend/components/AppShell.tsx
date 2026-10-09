"use client";

import type { ReactNode } from "react";

import { IdentityProvider } from "../lib/identity";
import { Header } from "./Header";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <IdentityProvider>
      <Header />
      <main className="page">{children}</main>
    </IdentityProvider>
  );
}
