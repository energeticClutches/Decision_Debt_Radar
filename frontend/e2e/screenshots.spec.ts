import path from "node:path";

import { expect, test } from "@playwright/test";

import { API, decisionByTitle, loginAs, openTab, openWorkspace, userByName, PERSONAS } from "./support";

// @screenshots: runs ON DEMAND only (playwright.config.ts leaves it out unless SCREENSHOTS=1). It writes docs/screenshots/*.png with a fixed
// viewport (1280 x 800), the light theme and reduced motion. Every picture is SYNTHETIC data and the replayed demo (stub, not model output).
//
//   1. restore the canonical demo state:   scripts/demo_prepare.py --reset
//   2. SCREENSHOTS=1 E2E_SKIP_RESET=1 npx playwright test screenshots
//
// The first six captures only read. The last one validates Community and creates its Decision Brief through the API (a write), so run
// `scripts/demo_prepare.py --reset` again afterwards to restore the demo state.
const OUT = path.resolve(__dirname, "..", "..", "docs", "screenshots");
const shot = (name: string) => ({ path: path.join(OUT, name), animations: "disabled" as const });

test.use({ viewport: { width: 1280, height: 800 }, colorScheme: "light", reducedMotion: "reduce" });

test.describe.serial("@screenshots README captures (synthetic data)", () => {
  test("01 portfolio", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await page.goto("/");
    await expect(page.getByTestId("synthetic-badge")).toBeVisible();
    await expect(page.locator('[data-testid^="decision-card-"]').first()).toBeVisible();
    await page.screenshot(shot("01-portfolio.png"));
  });

  test("02 AI Coach overview", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    const d = await decisionByTitle(request, "AI Coach");
    await openWorkspace(page, d.id);
    await expect(page.getByTestId("ddi-card")).toBeVisible();
    await page.screenshot(shot("02-ai-coach-overview.png"));
  });

  test("03 Why this score?", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    const d = await decisionByTitle(request, "AI Coach");
    await openWorkspace(page, d.id, "assessment");
    const why = page.getByTestId("why-score");
    await expect(why).toBeVisible();
    await why.evaluate((el) => el.scrollIntoView({ block: "start" }));
    await page.evaluate(() => window.scrollBy(0, -190));        // clear the sticky workspace header
    await page.screenshot(shot("03-why-this-score.png"));
  });

  test("04 review tab", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    const d = await decisionByTitle(request, "AI Coach");
    await openWorkspace(page, d.id, "review");
    await expect(page.getByTestId("reviewer-verdict")).toBeVisible();
    await expect(page.getByTestId("provenance-notice").first()).toBeVisible();
    await page.screenshot(shot("04-review.png"));
  });

  test("05 Onboarding gate card", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    const d = await decisionByTitle(request, "onboarding redesign");
    await openWorkspace(page, d.id, "assessment");
    await expect(page.getByTestId("gate-card")).toBeVisible();
    await expect(page.getByTestId("nbe-row").first()).toBeVisible();      // the recommendations load in parallel: wait for them
    await expect(page.getByTestId("gate-card")).not.toContainText("No unblocking action is listed");
    await expect(page.locator("[data-ddi-value]")).toHaveCount(0);
    await page.screenshot(shot("05-onboarding-gate.png"));
  });

  test("06 customer evidence", async ({ page, request }) => {
    await loginAs(page, request, "ba");
    const d = await decisionByTitle(request, "community challenges");
    await openWorkspace(page, d.id, "evidence");
    await page.getByTestId("evidence-sub-customer").click();
    await page.screenshot(shot("06-customer-evidence.png"));
  });

  test("07 brief (validates Community through the API first)", async ({ page, request }) => {
    const pm = await userByName(request, PERSONAS.pm);
    const d = await decisionByTitle(request, "community challenges");
    const headers = { "X-Demo-User": pm.id };
    if (d.lifecycle_stage === "challenged") {
      const v = await request.post(`${API}/decisions/${d.id}/validate`, { headers });
      expect(v.ok()).toBeTruthy();
    }
    const assessmentId = d.current_assessment!.id;
    const b = await request.post(`${API}/assessments/${assessmentId}/briefs`, { headers, data: { kind: "decision_brief" } });
    expect(b.ok()).toBeTruthy();
    const brief = await b.json();
    await loginAs(page, request, "pm");
    await page.goto(`/briefs/${brief.id}`);
    await expect(page.getByTestId("brief")).toBeVisible();
    await page.screenshot(shot("07-brief.png"));
  });
});
