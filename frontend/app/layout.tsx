import type { ReactNode } from "react";

export const metadata = {
  title: "Decision Debt Radar",
  description:
    "Agentic Decision Intelligence for Evidence-Based Organizations. Portfolio project with synthetic demo data.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>{children}</body>
    </html>
  );
}
