import type { ReactNode } from "react";

// A stand-in for next/link in the node test environment.
export default function Link({ href, children, ...rest }: { href: string; children?: ReactNode; [key: string]: unknown }) {
  return <a href={href} {...(rest as Record<string, unknown>)}>{children}</a>;
}
