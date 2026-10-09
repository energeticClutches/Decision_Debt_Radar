import type { ReactNode } from "react";

import "./globals.css";
import { AppShell } from "../components/AppShell";

export const metadata = {
  title: "Decision Debt Radar",
  description: "Agentic Decision Intelligence for Evidence-Based Organizations. Portfolio project with synthetic demo data.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
