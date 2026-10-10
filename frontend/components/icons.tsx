import type { ReactNode } from "react";

/** Inline SVG icons (24 x 24 grid, 1.75 stroke). No icon library: every glyph is a few paths. Always decorative: the text or the label beside it carries the meaning. */
const PATHS: Record<string, ReactNode> = {
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  stop: <><circle cx="12" cy="12" r="9" /><path d="M5.6 5.6l12.8 12.8" /></>,
  alert: <><path d="M12 3.5l9.5 16.5h-19z" /><path d="M12 10v4.5M12 17.4v.1" /></>,
  hourglass: <><path d="M7 3h10M7 21h10" /><path d="M8 3v3.5a4 4 0 0 0 1.6 3.2L12 12l-2.4 2.3A4 4 0 0 0 8 17.5V21M16 3v3.5a4 4 0 0 1-1.6 3.2L12 12l2.4 2.3a4 4 0 0 1 1.6 3.2V21" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5M12 7.6v.1" /></>,
  bulb: <><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1 2V16h5.2v-.2c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z" /></>,
  user: <><circle cx="12" cy="8.5" r="3.6" /><path d="M5 20c.6-3.6 3.5-5.5 7-5.5s6.4 1.9 7 5.5" /></>,
  chart: <><path d="M4 20V4" /><path d="M4 20h16" /><path d="M8 16v-4M12 16V8M16 16v-6" /></>,
  arrows: <><path d="M4 8h14M14 4l4 4-4 4" /><path d="M20 16H6M10 12l-4 4 4 4" /></>,
  bolt: <path d="M13 2.5L5 13.5h6L10 21.5l8-11h-6z" />,
  doc: <><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>,
  scale: <><path d="M12 4v16M7 20h10" /><path d="M5 7h14" /><path d="M5 7l-2.5 6a3 3 0 0 0 5 0zM19 7l-2.5 6a3 3 0 0 0 5 0z" /></>,
  up: <path d="M12 19V6M6.5 11.5L12 6l5.5 5.5" />,
  down: <path d="M12 5v13M6.5 12.5L12 18l5.5-5.5" />,
  minus: <path d="M6 12h12" />,
  sparkle: <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  layers: <><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></>,
  link: <><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>,
  close: <path d="M6 6l12 12M18 6L6 18" />,
};

export type IconName = keyof typeof PATHS;

export function SvgIcon({ name, size = 16, className }: { name: string; size?: number; className?: string }) {
  const body = PATHS[name];
  return (
    <svg className={`icon${className ? ` ${className}` : ""}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {body ?? <circle cx="12" cy="12" r="2" />}
    </svg>
  );
}

/** The product mark: a radar ring with a sweep and a dot (decorative). */
export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill="var(--accent-tint)" stroke="var(--accent)" strokeWidth="1" />
      <circle cx="16" cy="16" r="8" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
      <circle cx="16" cy="16" r="3.5" fill="none" stroke="var(--accent)" strokeWidth="1.5" />
      <path d="M16 16L22.5 9.5" stroke="var(--accent)" strokeWidth="1.75" strokeLinecap="round" />
      <circle cx="22.5" cy="9.5" r="1.6" fill="var(--accent)" />
    </svg>
  );
}
