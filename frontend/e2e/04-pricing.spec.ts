import { expect, test } from "@playwright/test";

import { decisionByTitle, loginAs, openWorkspace } from "./support";

test.describe("Pricing: an inconclusive experiment and a blocking 'no harm' finding", () => {
  let id = "";
  test.beforeAll(async ({ request }) => {
    id = (await decisionByTitle(request, "premium subscription price")).id;
  });

  test("the confidence interval spans zero and the experiment is shown as inconclusive", async ({ page, request }) => {
    await loginAs(page, request, "pm2");
    await openWorkspace(page, id, "evidence");
    await page.getByTestId("evidence-sub-analyses").click();
    const status = page.getByTestId("experiment-status");
    await expect(status).toBeVisible();
    await expect(status).toContainText("inconclusive");
    await expect(page.getByTestId("experiment-panel")).toContainText("The confidence interval spans 0");
    await page.getByTestId("evidence-sub-register").click();
    await expect(page.locator('[data-testid="evidence-row"]', { hasText: "Experiment" }).first()).toContainText("Neutral");
  });

  test("the blocking 'no harm' finding is visible, tagged as the reviewer's", async ({ page, request }) => {
    await loginAs(page, request, "pm2");
    await openWorkspace(page, id, "review");
    const blocking = page.locator('[data-testid="finding-blocking"][data-category="statistical_misinterpretation"]');
    await expect(blocking).toBeVisible();
    await expect(blocking.getByTestId("finding-source")).toHaveText("Reviewer");
    await expect(page.getByTestId("reviewer-verdict")).toContainText("needs rework");
    await expect(page.getByTestId("status-strip")).toHaveAttribute("data-kind", "needs_rework");
    await expect(page.getByTestId("synthesis-header").getByTestId("provenance-notice")).toBeVisible();
  });

  test("the DDI card is current and shows the engine's number", async ({ page, request }) => {
    await loginAs(page, request, "pm2");
    const d = await decisionByTitle(request, "premium subscription price");
    await openWorkspace(page, id, "assessment");
    await expect(page.getByTestId("ddi-card")).toHaveAttribute("data-state", "current");
    await expect(page.getByTestId("ddi-value")).toHaveText((d.current_assessment?.ddi as number).toFixed(1));
  });
});
