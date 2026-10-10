import { Inter } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";
import { AppShell } from "../components/AppShell";

// Self-hosted at build time by next/font (no runtime request to Google, no CDN link).
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata = {
  title: "Decision Debt Radar",
  description: "Agentic Decision Intelligence for Evidence-Based Organizations. Portfolio project with synthetic demo data.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
