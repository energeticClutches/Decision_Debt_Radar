import { describe, expect, it, vi } from "vitest";

import { ErrorBox, Loading } from "../components/ui";
import { ApiError, toApiError, WAKING_MESSAGE } from "../lib/api";
import { isWakingError, retryOnWake } from "../lib/wake";
// @ts-expect-error the Next.js config is a plain .mjs file without type declarations
import nextConfig from "../next.config.mjs";
import { html, text } from "./helpers";

describe("cold start of the free API host", () => {
  it("maps 502, 503 and 504 to a friendly 'waking up' error, never to a stack trace", () => {
    for (const status of [502, 503, 504]) {
      const e = toApiError(status, "<html>Bad gateway</html>");
      expect(e.code).toBe("unavailable");
      expect(e.message).toBe(WAKING_MESSAGE);
    }
    expect(WAKING_MESSAGE).toBe("The free demo server is waking up (about a minute). Retrying…");
    expect(toApiError(500, { error: { code: "internal_error", message: "x", detail: null } }).code).toBe("internal_error");
  });
  it("treats gateway statuses, network failures and timeouts as waking, and nothing else", () => {
    expect(isWakingError(new ApiError(503, "unavailable", "x"))).toBe(true);
    expect(isWakingError(new ApiError(0, "network", "x"))).toBe(true);
    expect(isWakingError(new ApiError(404, "not_found", "x"))).toBe(false);
    expect(isWakingError(new ApiError(409, "state_conflict", "x"))).toBe(false);
    expect(isWakingError(new ApiError(500, "internal_error", "x"))).toBe(false);
    expect(isWakingError(new Error("boom"))).toBe(false);
  });
  it("retries a read while the host wakes up and then returns the data", async () => {
    let calls = 0;
    const run = vi.fn(async () => {
      calls += 1;
      if (calls < 3) throw new ApiError(503, "unavailable", WAKING_MESSAGE);
      return "data";
    });
    await expect(retryOnWake(run, () => false, [1, 1, 1])).resolves.toBe("data");
    expect(run).toHaveBeenCalledTimes(3);
  });
  it("gives up after the last delay with the original error, and does not retry a real error", async () => {
    const down = vi.fn(async () => { throw new ApiError(502, "unavailable", WAKING_MESSAGE); });
    await expect(retryOnWake(down, () => false, [1, 1])).rejects.toMatchObject({ status: 502 });
    expect(down).toHaveBeenCalledTimes(3);
    const missing = vi.fn(async () => { throw new ApiError(404, "not_found", "Decision not found."); });
    await expect(retryOnWake(missing, () => false, [1, 1])).rejects.toMatchObject({ status: 404 });
    expect(missing).toHaveBeenCalledTimes(1);
  });
  it("shows the waking text, never a generic 'something went wrong', when a gateway error reaches the page", () => {
    const shown = text(html(<ErrorBox error={new ApiError(503, "unavailable", WAKING_MESSAGE)} onRetry={() => undefined} />));
    expect(shown).toContain("waking up");
    expect(shown).not.toContain("Something went wrong");
    expect(shown).toContain("Retry");
    expect(text(html(<ErrorBox error={new ApiError(500, "internal_error", "x")} />))).toContain("Something went wrong on the server");
  });
  it("renders the ordinary loading label when the host is awake", () => {
    expect(text(html(<Loading label="Loading decisions" />))).toBe("Loading decisions...");
  });
});

describe("production headers and the API target", () => {
  it("sets the security headers on every route", async () => {
    const rules = await nextConfig.headers!();
    expect(rules).toHaveLength(1);
    expect(rules[0].source).toBe("/:path*");
    const byKey = Object.fromEntries(rules[0].headers.map((h: { key: string; value: string }) => [h.key, h.value]));
    expect(byKey["X-Content-Type-Options"]).toBe("nosniff");
    expect(byKey["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(byKey["X-Frame-Options"]).toBe("DENY");
    expect(byKey["Permissions-Policy"]).toContain("camera=()");
    const csp = byKey["Content-Security-Policy"];
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).not.toMatch(/https?:\/\//);          // no third-party origin
  });
  it("rewrites /api/:path* to the API origin (default 127.0.0.1:8000)", async () => {
    const rewrites = (await nextConfig.rewrites!()) as Array<{ source: string; destination: string }>;
    expect(rewrites).toEqual([{ source: "/api/:path*", destination: "http://127.0.0.1:8000/:path*" }]);
  });
});
