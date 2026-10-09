import { expect, test } from "@playwright/test";

import { decisionByTitle, loginAs, openTab, openWorkspace } from "./support";

test.describe.serial("Community: heterogeneity, a contradicting theme, review and validation", () => {
  let id = "";
  test.beforeAll(async ({ request }) => {
    id = (await decisionByTitle(request, "community challenges")).id;
  });

  test("the heterogeneity element and the contradicting notifications_unwanted theme are visible", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "evidence");
    await page.getByTestId("evidence-sub-analyses").click();
    const het = page.getByTestId("heterogeneity");
    await expect(het).toBeVisible();
    await expect(het).toHaveAttribute("data-flag", "true");
    await expect(page.getByTestId("heterogeneity-flag")).toContainText("Heterogeneity flagged");
    await page.getByTestId("evidence-sub-customer").click();
    const card = page.getByTestId("customer-card-notifications_unwanted");
    await expect(card).toBeVisible();
    await expect(card).toContainText("Contradicts");
    await expect(card).toContainText("Set by taxonomy, not by AI");
    await expect(card).toHaveAttribute("data-status", "active");
    // every customer card names the replayed classification
    await expect(page.getByTestId("provenance-notice").first()).toHaveText("Replayed demo fixture, not live model output");
  });

  test("the assessment explains the score from stored values", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "assessment");
    await expect(page.getByTestId("ddi-card")).toHaveAttribute("data-state", "current");
    await expect(page.getByTestId("ddi-copy")).toHaveText("Higher = more evidence debt (weaker support). Not a probability the decision is wrong.");
    await expect(page.getByTestId("direction-copy")).toHaveText("Direction is separate from DDI.");
    for (const dim of ["D1", "D2", "D3", "D4", "D5", "D6", "D7"]) await expect(page.getByTestId(`dimension-${dim}`)).toBeVisible();
    await expect(page.getByTestId("penalty-P1")).toContainText("heterogeneity_flag");
    await expect(page.getByTestId("score-chain")).toContainText("Penalty multiplier");
    await expect(page.getByTestId("version-history")).toContainText("v2, current");
    await expect(page.getByTestId("version-history")).toContainText("v1, superseded");
  });

  test("the review is ready and validation works", async ({ page, request }) => {
    await loginAs(page, request, "pm");
    await openWorkspace(page, id, "review");
    await expect(page.getByTestId("reviewer-verdict")).toContainText("ready");
    await expect(page.getByTestId("next-action")).toHaveText("Validate the assessment");
    await page.getByTestId("next-action").click();
    await page.getByTestId("validate-checkbox").check();
    await page.getByTestId("validate-confirm").click();
    await expect(page.getByTestId("stepper")).toHaveAttribute("data-stage", "validated");
    await expect(page.getByTestId("validated-badge")).toContainText("Assessment validated by review");
    await openTab(page, "audit");
    await expect(page.getByTestId("audit-row").first()).toContainText("Assessment validated by review");
  });
});
