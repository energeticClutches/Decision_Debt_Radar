"use client";

// Cold start of the free API host: a sleeping Render web service answers 502, 503 or 504 (or nothing) for about a minute. Reads are retried
// with a backoff while a friendly "waking up" state is shown; the page never says "no data" and never dumps an error for this case.

import { useSyncExternalStore } from "react";

import { ApiError, WAKING_MESSAGE } from "./api";

export { WAKING_MESSAGE };
export const WAKING_FAILED_MESSAGE = "The free demo server is still waking up. This can take a minute or two after it has been idle. Please retry.";

/** Waits before each retry (about 2 minutes 40 seconds in all). */
export const RETRY_DELAYS_MS: readonly number[] = [2000, 3000, 5000, 8000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000];

/** The API host is not answering: a gateway status (502, 503, 504), a network failure or a timeout. */
export function isWakingError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504 || error.code === "unavailable");
}

let waiting = 0;
const listeners = new Set<() => void>();
function mark(delta: number) {
  waiting = Math.max(0, waiting + delta);
  listeners.forEach((l) => l());
}
export function useWaking(): boolean {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => waiting > 0,
    () => false,
  );
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Runs `run`; while it fails with a waking error, shows the waking state, waits and tries again (not after `cancelled()` or the last delay). */
export async function retryOnWake<T>(run: () => Promise<T>, cancelled: () => boolean = () => false, delays: readonly number[] = RETRY_DELAYS_MS): Promise<T> {
  let attempt = 0;
  let marked = false;
  try {
    for (;;) {
      try {
        return await run();
      } catch (error) {
        if (!isWakingError(error) || attempt >= delays.length || cancelled()) throw error;
        if (!marked) {
          marked = true;
          mark(1);
        }
        await sleep(delays[attempt++]);
        if (cancelled()) throw error;
      }
    }
  } finally {
    if (marked) mark(-1);
  }
}
