"use client";

import { useWaking, WAKING_MESSAGE } from "../lib/wake";

/** Shown under the header while the free API host is waking up and a request is being retried. */
export function WakingBanner() {
  const waking = useWaking();
  if (!waking) return null;
  return (
    <div className="banner info waking" role="status" data-testid="waking-banner">
      {WAKING_MESSAGE}
    </div>
  );
}
