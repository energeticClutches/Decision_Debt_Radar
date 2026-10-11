"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "./api";
import { retryOnWake } from "./wake";

export interface Resource<T> {
  loading: boolean;
  error: ApiError | null;
  data: T | null;
  reload: () => void;
}

/** Loads a resource. The previous data stays while a reload is in flight (no flicker). `deps` re-run the fetcher; `enabled=false` skips it. */
export function useResource<T>(fetcher: () => Promise<T>, deps: readonly unknown[], enabled = true): Resource<T> {
  const [state, setState] = useState<{ loading: boolean; error: ApiError | null; data: T | null }>({ loading: enabled, error: null, data: null });
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!enabled) {
      setState({ loading: false, error: null, data: null });
      return;
    }
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    // A gateway failure (the free API host is waking up) is retried with a backoff while the waking state is shown; it is not an error yet.
    retryOnWake(() => fetcherRef.current(), () => cancelled).then(
      (data) => {
        if (!cancelled) setState({ loading: false, error: null, data });
      },
      (error: unknown) => {
        if (cancelled) return;
        const err = error instanceof ApiError ? error : new ApiError(0, "error", "Something went wrong. Please retry.");
        setState((s) => ({ loading: false, error: err, data: err.status === 404 ? null : s.data }));
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled]);

  return { loading: state.loading, error: state.error, data: state.data, reload };
}
