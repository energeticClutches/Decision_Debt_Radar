import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, IDENTITY_KEY, toApiError } from "../lib/api";
import { citedClaimIds, parseClaimRefs, sentences } from "../lib/claims";
import { auditWords, fmtNumber, isReplayProvenance, REPLAY_NOTICE } from "../lib/format";

describe("[[id]] parsing", () => {
  it("splits text into plain and claim segments", () => {
    expect(parseClaimRefs("A [[c1]] and B [[c2]].", ["c1", "c2"])).toEqual([
      { type: "text", text: "A " }, { type: "claim", id: "c1" }, { type: "text", text: " and B " }, { type: "claim", id: "c2" }, { type: "text", text: "." },
    ]);
  });
  it("keeps an unknown id as plain text (the raw token)", () => {
    expect(parseClaimRefs("See [[zz]] here.", ["c1"])).toEqual([{ type: "text", text: "See [[zz]] here." }]);
  });
  it("treats markup as text and never produces anything but text and claim segments", () => {
    const parts = parseClaimRefs('<script>alert(1)</script> [[c1]] <b>bold</b>', ["c1"]);
    expect(parts.every((p) => p.type === "text" || p.type === "claim")).toBe(true);
    expect(parts[0]).toEqual({ type: "text", text: "<script>alert(1)</script> " });
  });
  it("handles empty text, empty brackets and repeated references", () => {
    expect(parseClaimRefs("", ["c1"])).toEqual([]);
    expect(parseClaimRefs("[[]]", ["c1"])).toEqual([{ type: "text", text: "[[]]" }]);
    expect(citedClaimIds("[[c1]] [[c1]] [[c2]] [[x]]", ["c1", "c2"])).toEqual(["c1", "c2"]);
  });
  it("splits sentences", () => {
    expect(sentences("One. Two [[c1]]! Three?")).toEqual(["One.", "Two [[c1]]!", "Three?"]);
  });
});

describe("errors", () => {
  it("maps the server error body (401/403 keep the allowed roles from detail)", () => {
    const e = toApiError(403, { error: { code: "forbidden", message: "Role 'pm' may not perform 'approve_evidence'.", detail: { allowed_roles: ["ba", "product_analyst"] } } });
    expect(e).toBeInstanceOf(ApiError);
    expect([e.status, e.code]).toEqual([403, "forbidden"]);
    expect(e.message).toContain("may not perform");
    expect(e.allowedRoles).toEqual(["ba", "product_analyst"]);
  });
  it("maps 404 and 409 with the server message", () => {
    expect(toApiError(404, { error: { code: "not_found", message: "Decision not found.", detail: {} } }).message).toBe("Decision not found.");
    expect(toApiError(409, { error: { code: "state_conflict", message: "A Decision Brief exists only after the assessment is validated.", detail: null } }).status).toBe(409);
  });
  it("maps a 422 with field messages (domain and FastAPI shapes)", () => {
    expect(toApiError(422, { error: { code: "invalid_input", message: "The decision canvas is invalid.", detail: { fields: { title: "title must be 1-120 characters" } } } }).fieldErrors)
      .toEqual({ title: "title must be 1-120 characters" });
    const f = toApiError(422, { detail: [{ loc: ["body", "outcome"], msg: "Input should be 'approve'" }] });
    expect(f.fieldErrors).toEqual({ outcome: "Input should be 'approve'" });
  });
  it("gives a generic message for 5xx and never exposes a body", () => {
    const e = toApiError(500, { detail: "Traceback (most recent call last): secret" });
    expect(e.message).toBe("Something went wrong on the server. Please retry.");
    expect(JSON.stringify(e)).not.toContain("Traceback");
  });
});

describe("api client", () => {
  const store = new Map<string, string>();
  beforeEach(() => {
    store.clear();
    vi.stubGlobal("window", { localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) } });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends X-Demo-User from localStorage to /api and parses JSON", async () => {
    store.set(IDENTITY_KEY, "user-123");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([{ id: "d1" }]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await api.decisions()).toEqual([{ id: "d1" }]);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/decisions");
    expect((init.headers as Record<string, string>)["X-Demo-User"]).toBe("user-123");
  });
  it("does not send an identity for the user list and throws ApiError on a failure", async () => {
    store.set(IDENTITY_KEY, "user-123");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: { code: "unauthorized", message: "Demo identity missing", detail: {} } }), { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.users()).rejects.toMatchObject({ status: 401, code: "unauthorized" });
    const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect((init.headers as Record<string, string>)["X-Demo-User"]).toBeUndefined();
  });
  it("turns a network failure into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("failed"); }));
    await expect(api.health()).rejects.toMatchObject({ status: 0, code: "network" });
  });
  it("posts JSON bodies", async () => {
    store.set(IDENTITY_KEY, "u");
    const fetchMock = vi.fn(async () => new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.postReview("a1", "ready", "because");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/assessments/a1/reviews");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ verdict: "ready", human_response: "because" });
  });
});

describe("format", () => {
  it("names the replay notice for every non-live provenance", () => {
    expect(REPLAY_NOTICE).toBe("Replayed demo fixture, not live model output");
    expect(isReplayProvenance("stub_not_model_output")).toBe(true);
    expect(isReplayProvenance("recorded_model_output")).toBe(true);
    expect(isReplayProvenance("live_model_output")).toBe(false);
    expect(isReplayProvenance(null)).toBe(false);
  });
  it("formats numbers and audit words", () => {
    expect(fmtNumber(null)).toBe("n/a");
    expect(fmtNumber(1.23456, 2)).toBe("1.23");
    expect(auditWords("evidence.approved")).toBe("Customer evidence approved");
    expect(auditWords("some.new_action")).toBe("Some new action");
  });
});
